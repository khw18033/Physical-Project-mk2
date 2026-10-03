"""SAR 비행 데이터 서버 (Pi) — 읽기 전용. 화면에서 버튼 한 번으로 받게 한다.

  python -m sar_data --flights /home/physical/sar_logs --radar /home/physical/cansar_data --port 8766

  GET /api/health                              살아 있나 · 디스크 여유
  GET /api/flights                             비행 목록 (패스 · 유효 여부 · 궤적/메타 파일 · 맞는 레이더 원시 파일)
  GET /api/flights/<id>/files/<name>           궤적 CSV · 메타 JSON 하나
  GET /api/flights/<id>/report.html           비행 보고서 한 장 (팀원에게 공유)
  GET /api/flights/<id>/bundle.zip[?pass=N][&raw=0|1]
                                               위치 데이터(+원시 레이더 · 만든 영상) 묶음. raw 기본 1
  GET /api/flights/<id>/image?pass=N[&cr=lat,lon;…][&force=1]
                                               SAR 영상 만들기 시작 · 진행 상황(image.json). 202 = 줄 섰다
  GET /api/flights/<id>/images/passNN/<file>   만든 영상(png · kmz) · image.json
  GET /api/flights/<id>/compare?a=N&b=M        두 패스 비교 — 기준선 · 일치도 · 밝기 변화 (compare_NN_MM/)

영상은 노트북에서 만든다(`--mirror` 로 Pi 의 패스를 가져와서) — sar_data/mirror.py · sar_data/imaging.py.

레이더 원시 파일은 cansar 가 쓰는 폴더(`--radar`)에서 **시각으로** 짝을 짓는다 — 파일 수정 시각이
그 패스의 실제 기록 구간(CAP_ACK 가 있으면 그것, 없으면 요청 구간) 앞 5 s ~ 뒤 15 s(데이터 옮기는 10 s 간격 포함)에
들어오면 그 패스의 것이다. cansar 의 파일 형식은 모른다 — 이름과 내용은 손대지 않고 그대로 묶는다.

비행 폴더는 sar_pass 가 만드는 `flight_<시각>/pass##_<시각>.csv|.json` 이다.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

log = logging.getLogger("sar_data")

PRE_S = 5.0
POST_S = 15.0
FLIGHT_RE = re.compile(r"^flight_(\d+)$")


class Store:
    def __init__(self, flights: Path, radar: Path | None, radar_glob: str = "**/*") -> None:
        self.flights = flights.resolve()
        self.radar = None if radar is None else radar.resolve()
        self.radar_glob = radar_glob

    # ── 목록 ────────────────────────────────────────────────────────────────
    def flight_dirs(self) -> list[Path]:
        if not self.flights.is_dir():
            return []
        out = [p for p in self.flights.iterdir() if p.is_dir() and FLIGHT_RE.match(p.name)]
        return sorted(out, key=lambda p: p.name, reverse=True)

    def radar_files(self) -> list[tuple[Path, float, int]]:
        if self.radar is None or not self.radar.is_dir():
            return []
        out = []
        for p in self.radar.glob(self.radar_glob):
            if p.is_file():
                st = p.stat()
                out.append((p, st.st_mtime, st.st_size))
        return out

    def passes(self, flight: Path, radar: list[tuple[Path, float, int]] | None = None) -> list[dict]:
        radar = self.radar_files() if radar is None else radar
        out = []
        for meta_path in sorted(flight.glob("pass*.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            p = meta.get("pass", {})
            t0 = p.get("ack_start_unix") or p.get("start_unix")
            t1 = p.get("ack_end_unix") or p.get("end_unix")
            matched = []
            mapped = self._radar_map(flight).get(str(p.get("pass_no")))
            if mapped is not None:      # 미러로 받은 패스 — 짝은 받을 때 적어 둔 것
                for rf in mapped.get("files", []):
                    f = flight / rf["name"]
                    if f.is_file():
                        matched.append({"name": rf["name"], "size": f.stat().st_size, "mtime": f.stat().st_mtime, "src": "flight"})
            elif t0 is not None and t1 is not None:
                for path, mtime, size in radar:
                    if t0 - PRE_S <= mtime <= t1 + POST_S:
                        matched.append({"name": str(path.relative_to(self.radar)), "size": size, "mtime": mtime})
            out.append({
                "pass_no": p.get("pass_no"), "valid": p.get("valid"), "reasons": p.get("reasons", []),
                "start_unix": p.get("start_unix"), "end_unix": p.get("end_unix"),
                "fc_start_unix": p.get("fc_start_unix"), "fc_end_unix": p.get("fc_end_unix"),
                "ack_start_unix": p.get("ack_start_unix"), "ack_end_unix": p.get("ack_end_unix"),
                "eff_start_along_m": p.get("eff_start_along_m"), "eff_end_along_m": p.get("eff_end_along_m"),
                "traj_csv": meta.get("traj_csv"), "meta_json": meta_path.name,
                "radar_files": matched, "radar_bytes": sum(m["size"] for m in matched),
                **self._rc_files(flight, p.get("pass_no")),
                "image": self._image_summary(flight, p.get("pass_no")),
            })
        return out

    @staticmethod
    def _rc_files(flight: Path, pass_no) -> dict:  # noqa: ANN001
        """Pi 가 줄여 둔 거리 압축 파일 (sar_data/reduce.py)."""
        d = flight / "radar_rc" / f"pass{pass_no:02d}" if isinstance(pass_no, int) else None
        files = sorted(d.glob("*.rc.npz")) if d is not None and d.is_dir() else []
        rc = [{"name": str(f.relative_to(flight)), "size": f.stat().st_size, "mtime": f.stat().st_mtime, "src": "flight"} for f in files]
        return {"rc_files": rc, "rc_bytes": sum(r["size"] for r in rc)}

    @staticmethod
    def _radar_map(flight: Path) -> dict:
        try:
            return json.loads((flight / "radar_map.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _image_summary(flight: Path, pass_no) -> dict | None:  # noqa: ANN001
        if not isinstance(pass_no, int):
            return None
        try:
            b = json.loads((flight / "images" / f"pass{pass_no:02d}" / "image.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        crs = b.get("reflectors") or []
        return {"state": b.get("state"), "error": b.get("error"), "reflectors": len(crs),
                "found": sum(1 for r in crs if r.get("found")), "full": bool(b.get("full"))}

    def radar_path(self, flight: Path, rf: dict) -> Path:
        if rf.get("src") == "flight":
            return flight / rf["name"]
        return self.radar / rf["name"]  # type: ignore[operator]

    def flights_json(self) -> list[dict]:
        radar = self.radar_files()
        out = []
        for d in self.flight_dirs():
            stamp = int(FLIGHT_RE.match(d.name).group(1))  # type: ignore[union-attr]
            passes = self.passes(d, radar)
            out.append({
                "id": d.name, "started_unix": stamp, "passes": passes,
                "valid_passes": sum(1 for p in passes if p["valid"]),
                "ulogs": [{"name": f.name, "size": f.stat().st_size} for f in sorted(d.glob("*.ulg"))],
                "size_bytes": sum(f.stat().st_size for f in d.iterdir() if f.is_file()) + sum(p["radar_bytes"] for p in passes),
            })
        return out

    # ── 파일 · 묶음 ─────────────────────────────────────────────────────────
    def flight(self, fid: str) -> Path | None:
        if not FLIGHT_RE.match(fid):
            return None
        d = (self.flights / fid).resolve()
        return d if d.is_dir() and d.parent == self.flights else None

    def flight_file(self, fid: str, name: str) -> Path | None:
        d = self.flight(fid)
        if d is None or "/" in name or "\\" in name or name.startswith("."):
            return None
        f = (d / name).resolve()
        return f if f.is_file() and f.parent == d else None

    def bundle(self, fid: str, pass_no: int | None, raw: bool | str) -> Path | None:
        """raw: True = 레이더 원시 그대로 · "rc" = Pi 가 줄여 둔 거리 압축만(핫스팟으로 빨리) · False = 위치만."""
        d = self.flight(fid)
        if d is None:
            return None
        passes = [p for p in self.passes(d) if pass_no is None or p["pass_no"] == pass_no]
        if pass_no is not None and not passes:
            return None
        tmp = tempfile.NamedTemporaryFile(prefix="sar_bundle_", suffix=".zip", delete=False)
        tmp.close()
        manifest = {"flight": fid, "made_unix": time.time(), "passes": passes, "raw_included": raw,
                    "note": "궤적 CSV 의 t_fc 는 FC GPS 시각(UTC 초). 레이더 원시 파일은 cansar 가 쓴 그대로다."}
        with zipfile.ZipFile(tmp.name, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            try:
                from .report import flight_report
                z.writestr("report.html", flight_report(d, self.passes(d)))
            except Exception:  # noqa: BLE001 — 보고서가 실패해도 데이터는 묶는다
                pass
            for f in sorted(d.iterdir()):
                if not f.is_file():
                    continue
                if pass_no is not None and not f.name.startswith(f"pass{pass_no:02d}_") and f.suffix != ".jsonl":
                    continue
                z.write(f, f"position/{f.name}")
            if raw == "rc":
                for p in passes:
                    for rf in p.get("rc_files", []):
                        z.write(d / rf["name"], f"radar/pass{p['pass_no']:02d}/{Path(rf['name']).name}", compress_type=zipfile.ZIP_STORED)
            elif raw:
                seen: set[str] = set()
                for p in passes:
                    for rf in p["radar_files"]:
                        if rf["name"] in seen:
                            continue
                        seen.add(rf["name"])
                        prefix = f"radar/pass{p['pass_no']:02d}/"
                        name = rf["name"][len(prefix):] if rf.get("src") == "flight" and rf["name"].startswith(prefix) else rf["name"]
                        # 이미 압축된 원시 자료는 다시 압축해도 안 준다 — 그대로 담는다(빠르다)
                        z.write(self.radar_path(d, rf), f"{prefix}{name}", compress_type=zipfile.ZIP_STORED)
            # 만든 영상이 있으면 같이 (큰 npy 는 뺀다)
            for p in passes:
                img_dir = d / "images" / f"pass{p['pass_no']:02d}"
                if img_dir.is_dir():
                    for f in sorted(img_dir.iterdir()):
                        if f.is_file() and f.suffix in (".png", ".json", ".kmz"):
                            z.write(f, f"images/{img_dir.name}/{f.name}")
        return Path(tmp.name)

    def health(self) -> dict:
        target = self.flights if self.flights.exists() else Path("/")
        du = shutil.disk_usage(target)
        return {"ok": True, "flights_dir": str(self.flights), "radar_dir": None if self.radar is None else str(self.radar),
                "disk_free_bytes": du.free, "disk_total_bytes": du.total, "time": time.time()}


def make_handler(store: Store, jobs=None, mirror=None, tiles=None, reducer=None):  # noqa: ANN001, ANN201
    class Handler(BaseHTTPRequestHandler):
        server_version = "sar_data/0.1"

        def log_message(self, fmt: str, *args) -> None:  # noqa: ANN002
            log.info("%s %s", self.address_string(), fmt % args)

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(HTTPStatus.NO_CONTENT)
            self._cors()
            self.end_headers()

        def _json(self, body: object, status: int = 200) -> None:
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _file(self, path: Path, download_name: str, ctype: str, inline: bool = False) -> None:
            # 먼저 열고 **연 파일의** 크기를 잰다 — 영상 작업이 image.json 을 새 파일로 갈아 끼우는 사이에
            # 이름으로 크기를 재면 옛 크기 · 새 내용이 섞여 응답이 잘린다(시험에서 가끔 JSON 이 깨졌다).
            f = path.open("rb")
            size = os.fstat(f.fileno()).st_size
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            if inline:      # 화면이 <img> 로 바로 보여 준다 — 다시 만들면 바뀌므로 캐시하지 않는다
                self.send_header("Cache-Control", "no-store")
            else:
                self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
            self.end_headers()
            with f:
                shutil.copyfileobj(f, self.wfile, 1024 * 1024)

        def do_GET(self) -> None:  # noqa: N802
            u = urlparse(self.path)
            parts = [unquote(x) for x in u.path.split("/") if x]
            q = parse_qs(u.query)
            try:
                if tiles is not None and len(parts) == 5 and parts[0] == "tiles" and parts[4].endswith(".png"):
                    try:
                        z, x, y = int(parts[2]), int(parts[3]), int(parts[4][:-4])
                    except ValueError:
                        return self._json({"error": "not found"}, 404)
                    f = tiles.get(parts[1], z, x, y)
                    if f is None:
                        return self._json({"error": "타일 없음 (인터넷이 없고 미리 받지도 않았다)"}, 404)
                    data = f.read_bytes()
                    self.send_response(200)
                    self._cors()
                    self.send_header("Content-Type", "image/png" if parts[1] == "street" else "image/jpeg")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "max-age=86400")
                    self.end_headers()
                    self.wfile.write(data)
                    return None
                if parts == ["api", "tiles", "prefetch"]:
                    if tiles is None:
                        return self._json({"error": "이 서버는 지도를 받아 두지 않는다 (--tile-cache)"}, 501)
                    try:
                        g = lambda k, d=None: q[k][0] if k in q else d  # noqa: E731
                        status, body = tiles.prefetch(g("layer", "satellite"), float(g("s")), float(g("w")), float(g("n")), float(g("e")),
                                                      int(g("zmin", "15")), int(g("zmax", "20")))
                    except (TypeError, ValueError):
                        return self._json({"error": "s · w · n · e (위경도) 가 필요하다"}, 400)
                    return self._json(body, status)
                if parts == ["api", "tiles", "status"]:
                    return self._json(tiles.status() if tiles is not None else {"error": "no tile cache"}, 200 if tiles else 501)
                if parts == ["api", "health"]:
                    h = store.health()
                    h["tiles"] = None if tiles is None else {"ready": True}
                    h["reduce"] = None if reducer is None else reducer.state()
                    h["imaging"] = None if jobs is None else {"ready": not jobs.missing(), "missing": jobs.missing()}
                    h["mirror"] = None if mirror is None else mirror.state()
                    return self._json(h)
                if parts == ["api", "flights"]:
                    return self._json(store.flights_json())
                if len(parts) == 5 and parts[:2] == ["api", "flights"] and parts[3] == "files":
                    f = store.flight_file(parts[2], parts[4])
                    if f is None:
                        return self._json({"error": "not found"}, 404)
                    ctype = "text/csv" if f.suffix == ".csv" else "application/json"
                    return self._file(f, f"{parts[2]}_{f.name}", ctype)
                if len(parts) == 4 and parts[:2] == ["api", "flights"] and parts[3] == "bundle.zip":
                    pass_no = int(q["pass"][0]) if "pass" in q else None
                    rv = q.get("raw", ["1"])[0]
                    raw = "rc" if rv == "rc" else rv != "0"
                    z = store.bundle(parts[2], pass_no, raw)
                    if z is None:
                        return self._json({"error": "not found"}, 404)
                    try:
                        suffix = f"_pass{pass_no:02d}" if pass_no is not None else ""
                        return self._file(z, f"{parts[2]}{suffix}{'' if raw else '_position'}.zip", "application/zip")
                    finally:
                        os.unlink(z)
                if len(parts) == 4 and parts[:2] == ["api", "flights"] and parts[3] == "report.html":
                    d = store.flight(parts[2])
                    if d is None:
                        return self._json({"error": "not found"}, 404)
                    from .report import flight_report
                    data = flight_report(d, store.passes(d)).encode()
                    self.send_response(200)
                    self._cors()
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return None
                if len(parts) == 4 and parts[:2] == ["api", "flights"] and parts[3] == "image":
                    if jobs is None:
                        return self._json({"error": "이 서버에는 영상 설정이 없다", "missing": ["--radar-json", "--adapter"]}, 501)
                    if "pass" not in q:
                        return self._json({"error": "pass=N 이 필요하다"}, 400)
                    from .imaging import parse_cr
                    crs = parse_cr(q["cr"][0]) if "cr" in q else None
                    status, body = jobs.request(parts[2], int(q["pass"][0]), crs, force=q.get("force", ["0"])[0] == "1")
                    return self._json(body, status)
                if len(parts) == 6 and parts[:2] == ["api", "flights"] and parts[3] == "images":
                    d = store.flight(parts[2])
                    if (d is None or not re.fullmatch(r"pass\d{2}|compare_\d{2}_\d{2}", parts[4])
                            or not re.fullmatch(r"[\w.-]+\.(png|json|kmz)", parts[5])):
                        return self._json({"error": "not found"}, 404)
                    f = d / "images" / parts[4] / parts[5]
                    if not f.is_file():
                        return self._json({"error": "not found"}, 404)
                    ctype = {".png": "image/png", ".json": "application/json", ".kmz": "application/vnd.google-earth.kmz"}[f.suffix]
                    return self._file(f, f"{parts[2]}_{parts[4]}_{f.name}", ctype, inline=f.suffix != ".kmz")
                if len(parts) == 4 and parts[:2] == ["api", "flights"] and parts[3] == "compare":
                    # 같은 선 두 패스 비교 — 두 영상이 다 있어야 한다(몇 초, 그 자리에서 만든다)
                    d = store.flight(parts[2])
                    if d is None or "a" not in q or "b" not in q:
                        return self._json({"error": "a=N&b=M 이 필요하다"}, 400)
                    na, nb = sorted((int(q["a"][0]), int(q["b"][0])))
                    da, db = d / "images" / f"pass{na:02d}", d / "images" / f"pass{nb:02d}"
                    if not (da / "full.npy").is_file() or not (db / "full.npy").is_file():
                        return self._json({"error": "두 패스 모두 선 전체 영상이 있어야 한다"}, 409)
                    out = d / "images" / f"compare_{na:02d}_{nb:02d}"
                    if not (out / "compare.json").is_file() or q.get("force", ["0"])[0] == "1":
                        from sar_image.compare import compare_passes
                        compare_passes(da, db, out, d)
                    body = json.loads((out / "compare.json").read_text(encoding="utf-8"))
                    body["dir"] = out.name
                    return self._json(body)
                return self._json({"error": "not found"}, 404)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:  # noqa: BLE001
                log.exception("요청 처리 실패")
                return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    return Handler


def serve(flights: Path, radar: Path | None, port: int, bind: str = "0.0.0.0", radar_glob: str = "**/*",
          jobs=None, mirror=None) -> ThreadingHTTPServer:  # noqa: ANN001
    store = jobs.store if jobs is not None else Store(flights, radar, radar_glob)
    return ThreadingHTTPServer((bind, port), make_handler(store, jobs, mirror))


def auto_image_loop(store: Store, jobs, stop, settle_s: float = POST_S + 5, interval_s: float = 5.0) -> None:  # noqa: ANN001
    """끝난 패스 중 레이더 파일이 있고 영상이 아직 없는 것을 줄 세운다(미러로 받은 것 포함)."""
    while not stop.is_set():
        try:
            now = time.time()
            for f in store.flights_json():
                for p in f["passes"]:
                    end = p.get("ack_end_unix") or p.get("end_unix")
                    if p["image"] is None and p["radar_files"] and isinstance(p["pass_no"], int) and end and now > end + settle_s:
                        jobs.request(f["id"], p["pass_no"])
        except Exception:  # noqa: BLE001
            log.exception("자동 영상 확인 실패")
        stop.wait(interval_s)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="sar_data", description="SAR 비행 데이터 서버 (읽기 전용)")
    p.add_argument("--flights", type=Path, default=Path("sar_logs"), help="sar_pass --log-dir 와 같은 폴더")
    p.add_argument("--radar", type=Path, help="cansar 가 원시 데이터를 쓰는 폴더")
    p.add_argument("--radar-glob", default="**/*", help="레이더 파일 고르기 (예: '*.bin')")
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--bind", default="0.0.0.0")
    g = p.add_argument_group("영상 (노트북)")
    g.add_argument("--mirror", help="Pi 데이터 서버 주소 (예: http://192.168.137.2:8766) — 끝난 패스를 가져온다")
    g.add_argument("--radar-json", type=Path, help="레이더 사양 · 레버암 (sar_image/example_radar.json 모양)")
    g.add_argument("--adapter", help="레이더 원시 → 거리 압축 (예: sar_image.adapters:fmcw_dechirped_npz)")
    g.add_argument("--reflectors", type=Path, help="화면에서 내려받은 reflectors.csv — 영상 요청에 리플렉터가 없을 때 쓴다")
    g.add_argument("--auto-image", action="store_true", help="새 패스가 들어오면 바로 영상을 만든다")
    g.add_argument("--image-workers", type=int, help="영상 계산 스레드 (기본: 코어 수, 최대 8)")
    g.add_argument("--former", help="팀의 영상 코드 모듈:함수 (없으면 내장 백프로젝션)")
    g.add_argument("--focuser", help="팀의 자동 초점 모듈:함수 (없으면 내장 리플렉터 방식)")
    g.add_argument("--reduce-adapter", help="Pi: 패스마다 레이더 원시를 거리 압축 파일로 줄여 둔다 (예: sar_image.sdr:iq_npy, --radar-json 필요)")
    g.add_argument("--tile-cache", type=Path, help="지도 타일을 받아 둘 폴더 — 인터넷 없는 현장용 (/tiles/…)")
    a = p.parse_args(argv)
    import threading

    store = Store(a.flights, a.radar, a.radar_glob)
    jobs = mirror = None
    if a.adapter or a.auto_image:
        from .imaging import ImageJobs
        jobs = ImageJobs(store, a.radar_json, a.adapter, a.reflectors, a.image_workers, former=a.former, focuser=a.focuser)
        if jobs.missing():
            log.warning("영상 설정이 빠졌다: %s", ", ".join(jobs.missing()))
    if a.mirror:
        from .mirror import Mirror
        a.flights.mkdir(parents=True, exist_ok=True)
        mirror = Mirror(a.mirror, store.flights)
        mirror.start()
    stop = threading.Event()
    if a.auto_image and jobs is not None and not jobs.missing():
        threading.Thread(target=auto_image_loop, args=(store, jobs, stop), name="sar-auto-image", daemon=True).start()
    tiles = None
    if a.tile_cache:
        from .tiles import TileCache
        tiles = TileCache(a.tile_cache)
    reducer = None
    if a.reduce_adapter:
        if not a.radar_json:
            p.error("--reduce-adapter 에는 --radar-json 이 필요하다")
        from .reduce import Reducer
        reducer = Reducer(store, a.radar_json, a.reduce_adapter)
        reducer.start()
    srv = ThreadingHTTPServer((a.bind, a.port), make_handler(store, jobs, mirror, tiles, reducer))
    log.info("http://%s:%d  flights=%s radar=%s mirror=%s imaging=%s", a.bind, a.port, a.flights, a.radar, a.mirror,
             None if jobs is None else ("ready" if not jobs.missing() else "incomplete"))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
