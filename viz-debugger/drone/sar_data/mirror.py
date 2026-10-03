"""노트북 쪽 미러 — Pi 의 데이터 서버에서 끝난 패스를 가져와 같은 모양으로 둔다.

    python -m sar_data --flights ~/sar_mirror --mirror http://<pi>:8765 \\
        --radar-json radar.json --adapter sar_image.adapters:fmcw_dechirped_npz --auto-image

패스가 끝나고(레이더가 파일을 옮길 시간 POST_S 를 더해) 끝난 것만 `bundle.zip?pass=N&raw=1` 로 받는다.
레이더 파일은 `<비행>/radar/passNN/` 에 풀고, 어느 패스의 것인지 `radar_map.json` 에 적는다 —
내려받은 파일은 수정 시각이 바뀌어 Pi 처럼 시각으로 짝을 지을 수 없기 때문이다.
Pi 쪽 레이더 파일 크기가 바뀌면(늦게 옮겨진 파일) 다시 받는다.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable

log = logging.getLogger("sar_data.mirror")


class Mirror:
    def __init__(self, base_url: str, flights: Path, on_pass: Callable[[str, int], None] | None = None,
                 interval_s: float = 5.0, settle_s: float = 20.0, timeout_s: float = 60.0) -> None:
        self.base = base_url.rstrip("/")
        self.flights = flights
        self.on_pass = on_pass
        self.interval_s = interval_s
        self.settle_s = settle_s
        self.timeout_s = timeout_s
        self.last_ok: float | None = None
        self.last_error: str | None = None
        self.fetched = 0
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._loop, name="sar-mirror", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def state(self) -> dict:
        return {"source": self.base, "last_ok_unix": self.last_ok, "last_error": self.last_error, "fetched_passes": self.fetched}

    # ── 한 바퀴 ─────────────────────────────────────────────────────────────
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.sync_once()
                self.last_ok, self.last_error = time.time(), None
            except Exception as exc:  # noqa: BLE001 — 핫스팟이 끊겨도 계속 다시 시도한다
                if self.last_error != str(exc):
                    log.warning("미러 실패: %s", exc)
                self.last_error = f"{type(exc).__name__}: {exc}"
            self._stop.wait(self.interval_s)

    def _get(self, path: str) -> bytes:
        with urllib.request.urlopen(self.base + path, timeout=self.timeout_s) as r:  # noqa: S310 — 사용자가 준 Pi 주소
            return r.read()

    def sync_once(self, now: float | None = None) -> list[tuple[str, int]]:
        now = time.time() if now is None else now
        got = []
        for f in json.loads(self._get("/api/flights")):
            fid = f["id"]
            if not fid.startswith("flight_") or "/" in fid:
                continue
            d = self.flights / fid
            rmap = self._read_map(d)
            for p in f.get("passes", []):
                n = p.get("pass_no")
                end = p.get("ack_end_unix") or p.get("end_unix")
                if not isinstance(n, int) or end is None or now < end + self.settle_s:
                    continue                                   # 아직 비행 중이거나 레이더가 파일을 옮기는 중
                have = rmap.get(str(n))
                meta_ok = p.get("meta_json") and (d / p["meta_json"]).exists()
                if meta_ok and have is not None and have.get("remote_radar_bytes") == p.get("radar_bytes"):
                    continue
                self._fetch(fid, n, p, d, rmap)
                got.append((fid, n))
                self.fetched += 1
                if self.on_pass is not None:
                    try:
                        self.on_pass(fid, n)
                    except Exception:  # noqa: BLE001
                        log.exception("새 패스 처리 실패")
        return got

    # ── 받기 · 풀기 ─────────────────────────────────────────────────────────
    @staticmethod
    def _read_map(d: Path) -> dict:
        try:
            return json.loads((d / "radar_map.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _fetch(self, fid: str, n: int, p: dict, d: Path, rmap: dict) -> None:
        log.info("받는 중 %s 패스 %d (레이더 %.1f MB)", fid, n, (p.get("radar_bytes") or 0) / 1e6)
        d.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.NamedTemporaryFile(prefix="sar_mirror_", suffix=".zip", delete=False)
        tmp.close()
        try:
            with urllib.request.urlopen(f"{self.base}/api/flights/{fid}/bundle.zip?pass={n}&raw=1",  # noqa: S310
                                        timeout=self.timeout_s) as r, open(tmp.name, "wb") as out:
                shutil.copyfileobj(r, out, 1024 * 1024)
            files = []
            prefix = f"radar/pass{n:02d}/"
            with zipfile.ZipFile(tmp.name) as z:
                for info in z.infolist():
                    name = PurePosixPath(info.filename)
                    if info.is_dir() or ".." in name.parts or name.is_absolute():
                        continue
                    if name.parts[0] == "position" and len(name.parts) == 2 and name.parts[1] != "radar_map.json":
                        target = d / name.parts[1]
                    elif info.filename.startswith(prefix):
                        rel = PurePosixPath("radar", f"pass{n:02d}", *name.parts[2:])
                        target = d / Path(*rel.parts)
                        files.append({"name": str(rel), "size": info.file_size})
                    else:
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
            rmap[str(n)] = {"files": files, "remote_radar_bytes": p.get("radar_bytes"), "fetched_unix": time.time()}
            tmp_map = d / "radar_map.json.tmp"
            tmp_map.write_text(json.dumps(rmap, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_map.replace(d / "radar_map.json")
        finally:
            Path(tmp.name).unlink(missing_ok=True)
