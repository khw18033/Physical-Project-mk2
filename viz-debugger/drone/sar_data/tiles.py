"""지도 타일 캐시 — 인터넷 없는 현장에서도 위성 지도가 나오게, 노트북 데이터 서버가 타일을 받아 두고 내준다.

    python -m sar_data ... --tile-cache ~/sar_tiles        # 노트북 (sar-laptop 스크립트가 켠다)

  GET /tiles/<layer>/<z>/<x>/<y>.png      있으면 디스크에서, 없으면 원본에서 받아 저장하고 준다
  GET /api/tiles/prefetch?layer=satellite&s=&w=&n=&e=&zmin=15&zmax=20
                                          그 구역을 미리 받는다(뒤에서). 202 + 받을 타일 수
  GET /api/tiles/status                   진행 상황 · 저장된 타일 수 · 용량

화면: ⇄ 연결 관리 → 「드론 지도」의 위성 주소를 `http://127.0.0.1:8766/tiles/satellite/{z}/{x}/{y}.png` 로 둔다.
사무실(인터넷 있음)에서 현장 구역을 미리 받아 두면, 현장에서는 디스크에서만 나온다.

원본 이용 약관 때문에 한 번에 받는 양을 제한한다(`MAX_PREFETCH`). 넓은 구역 · 높은 확대는 나눠서 받는다.
"""

from __future__ import annotations

import logging
import math
import re
import threading
import time
import urllib.request
from pathlib import Path

log = logging.getLogger("sar_data.tiles")

UPSTREAM = {
    "satellite": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    "street": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
}
MAX_PREFETCH = 3000
USER_AGENT = "sar-drone-groundstation/0.1 (field tile cache)"
PATH_RE = re.compile(r"^(satellite|street)$")


def tile_xy(lat: float, lon: float, z: int) -> tuple[int, int]:
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    lr = math.radians(max(-85.05, min(85.05, lat)))
    y = int((1.0 - math.asinh(math.tan(lr)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def tiles_in(s: float, w: float, n: float, e: float, zmin: int, zmax: int) -> list[tuple[int, int, int]]:
    out = []
    for z in range(zmin, zmax + 1):
        x0, y0 = tile_xy(n, w, z)
        x1, y1 = tile_xy(s, e, z)
        out += [(z, x, y) for x in range(min(x0, x1), max(x0, x1) + 1) for y in range(min(y0, y1), max(y0, y1) + 1)]
    return out


class TileCache:
    def __init__(self, root: Path, upstream: dict[str, str] | None = None, timeout_s: float = 10.0) -> None:
        self.root = root
        self.upstream = upstream or UPSTREAM
        self.timeout_s = timeout_s
        self.job: dict = {"state": "idle"}
        self._lock = threading.Lock()

    def path(self, layer: str, z: int, x: int, y: int) -> Path:
        return self.root / layer / str(z) / str(x) / f"{y}.png"

    def get(self, layer: str, z: int, x: int, y: int, fetch: bool = True) -> Path | None:
        if not PATH_RE.match(layer) or not (0 <= z <= 22) or not (0 <= x < 2 ** z) or not (0 <= y < 2 ** z):
            return None
        p = self.path(layer, z, x, y)
        if p.is_file():
            return p
        if not fetch:
            return None
        url = self.upstream[layer].format(z=z, x=x, y=y)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:  # noqa: S310 — 정해진 타일 원본
                data = r.read()
        except Exception as exc:  # noqa: BLE001 — 인터넷이 없으면 없는 대로
            log.debug("타일 못 받음 %s: %s", url, exc)
            return None
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(p)
        return p

    def prefetch(self, layer: str, s: float, w: float, n: float, e: float, zmin: int, zmax: int) -> tuple[int, dict]:
        if not PATH_RE.match(layer):
            return 400, {"error": "layer 는 satellite · street"}
        if not (-85 <= s < n <= 85 and -180 <= w < e <= 180) or not (0 <= zmin <= zmax <= 21):
            return 400, {"error": "구역 · 확대 범위가 이상하다"}
        todo = tiles_in(s, w, n, e, zmin, zmax)
        if len(todo) > MAX_PREFETCH:
            return 413, {"error": f"타일 {len(todo)}개 — 한 번에 {MAX_PREFETCH}개까지. 구역을 좁히거나 최대 확대를 낮춘다", "tiles": len(todo)}
        with self._lock:
            if self.job.get("state") == "running":
                return 409, {"error": "이미 받는 중", **self.job}
            self.job = {"state": "running", "layer": layer, "total": len(todo), "done": 0, "fetched": 0, "failed": 0,
                        "started_unix": time.time()}
        threading.Thread(target=self._run, args=(layer, todo), name="tile-prefetch", daemon=True).start()
        return 202, dict(self.job)

    def _run(self, layer: str, todo: list[tuple[int, int, int]]) -> None:
        for z, x, y in todo:
            had = self.path(layer, z, x, y).is_file()
            ok = self.get(layer, z, x, y) is not None
            with self._lock:
                self.job["done"] += 1
                if ok and not had:
                    self.job["fetched"] += 1
                if not ok:
                    self.job["failed"] += 1
            if not had:
                time.sleep(0.05)           # 원본에 부담을 주지 않게
        with self._lock:
            self.job["state"] = "done"
            self.job["finished_unix"] = time.time()

    def status(self) -> dict:
        files = list(self.root.rglob("*.png")) if self.root.is_dir() else []
        with self._lock:
            job = dict(self.job)
        return {"job": job, "cached_tiles": len(files), "cached_mb": round(sum(f.stat().st_size for f in files) / 1e6, 1),
                "dir": str(self.root)}
