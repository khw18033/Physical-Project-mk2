"""SAR 비행 데이터 서버 (Pi) — 읽기 전용. 화면에서 버튼 한 번으로 받게 한다.

  python -m sar_data --flights /home/physical/sar_logs --radar /home/physical/cansar_data --port 8765

  GET /api/health                              살아 있나 · 디스크 여유
  GET /api/flights                             비행 목록 (패스 · 유효 여부 · 궤적/메타 파일 · 맞는 레이더 원시 파일)
  GET /api/flights/<id>/files/<name>           궤적 CSV · 메타 JSON 하나
  GET /api/flights/<id>/bundle.zip[?pass=N][&raw=0|1]
                                               위치 데이터(+원시 레이더) 묶음. raw 기본 1

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
            if t0 is not None and t1 is not None:
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
            })
        return out

    def flights_json(self) -> list[dict]:
        radar = self.radar_files()
        out = []
        for d in self.flight_dirs():
            stamp = int(FLIGHT_RE.match(d.name).group(1))  # type: ignore[union-attr]
            passes = self.passes(d, radar)
            out.append({
                "id": d.name, "started_unix": stamp, "passes": passes,
                "valid_passes": sum(1 for p in passes if p["valid"]),
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

    def bundle(self, fid: str, pass_no: int | None, raw: bool) -> Path | None:
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
            for f in sorted(d.iterdir()):
                if not f.is_file():
                    continue
                if pass_no is not None and not f.name.startswith(f"pass{pass_no:02d}_") and f.suffix != ".jsonl":
                    continue
                z.write(f, f"position/{f.name}")
            if raw and self.radar is not None:
                seen: set[str] = set()
                for p in passes:
                    for rf in p["radar_files"]:
                        if rf["name"] in seen:
                            continue
                        seen.add(rf["name"])
                        # 이미 압축된 원시 자료는 다시 압축해도 안 준다 — 그대로 담는다(빠르다)
                        z.write(self.radar / rf["name"], f"radar/pass{p['pass_no']:02d}/{rf['name']}",
                                compress_type=zipfile.ZIP_STORED)
        return Path(tmp.name)

    def health(self) -> dict:
        target = self.flights if self.flights.exists() else Path("/")
        du = shutil.disk_usage(target)
        return {"ok": True, "flights_dir": str(self.flights), "radar_dir": None if self.radar is None else str(self.radar),
                "disk_free_bytes": du.free, "disk_total_bytes": du.total, "time": time.time()}


def make_handler(store: Store):  # noqa: ANN201
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

        def _file(self, path: Path, download_name: str, ctype: str) -> None:
            size = path.stat().st_size
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
            self.end_headers()
            with path.open("rb") as f:
                shutil.copyfileobj(f, self.wfile, 1024 * 1024)

        def do_GET(self) -> None:  # noqa: N802
            u = urlparse(self.path)
            parts = [unquote(x) for x in u.path.split("/") if x]
            q = parse_qs(u.query)
            try:
                if parts == ["api", "health"]:
                    return self._json(store.health())
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
                    raw = q.get("raw", ["1"])[0] != "0"
                    z = store.bundle(parts[2], pass_no, raw)
                    if z is None:
                        return self._json({"error": "not found"}, 404)
                    try:
                        suffix = f"_pass{pass_no:02d}" if pass_no is not None else ""
                        return self._file(z, f"{parts[2]}{suffix}{'' if raw else '_position'}.zip", "application/zip")
                    finally:
                        os.unlink(z)
                if parts and parts[0] == "api" and len(parts) >= 3 and parts[-1] == "image":
                    # 다음 단계: 버튼 하나로 SAR 영상 만들기 — 레이더 원시 형식을 받으면 여기에 붙인다.
                    return self._json({"error": "not implemented yet", "todo": "radar raw format needed"}, 501)
                return self._json({"error": "not found"}, 404)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:  # noqa: BLE001
                log.exception("요청 처리 실패")
                return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    return Handler


def serve(flights: Path, radar: Path | None, port: int, bind: str = "0.0.0.0", radar_glob: str = "**/*") -> ThreadingHTTPServer:
    store = Store(flights, radar, radar_glob)
    return ThreadingHTTPServer((bind, port), make_handler(store))


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="sar_data", description="SAR 비행 데이터 서버 (읽기 전용)")
    p.add_argument("--flights", type=Path, default=Path("sar_logs"), help="sar_pass --log-dir 와 같은 폴더")
    p.add_argument("--radar", type=Path, help="cansar 가 원시 데이터를 쓰는 폴더")
    p.add_argument("--radar-glob", default="**/*", help="레이더 파일 고르기 (예: '*.bin')")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--bind", default="0.0.0.0")
    a = p.parse_args(argv)
    srv = serve(a.flights, a.radar, a.port, a.bind, a.radar_glob)
    log.info("http://%s:%d  flights=%s radar=%s", a.bind, a.port, a.flights, a.radar)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
