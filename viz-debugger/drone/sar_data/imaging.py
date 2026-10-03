"""데이터 서버의 「영상 만들기」 — 한 번에 하나씩, 뒤에서(스레드) 만든다.

요청이 오면 `images/passNN/image.json` 에 queued 를 바로 쓰고 큐에 넣는다. 화면은 그 파일을 다시 읽어
running → done(또는 failed)을 본다. 리플렉터 둘레가 먼저 나오고 전체 영상이 뒤따른다(`sar_image.pipeline`).

필요한 것: radar.json(레이더 사양 · 레버암)과 어댑터(레이더 원시 → 거리 압축). 둘 중 하나라도 없으면 501 로
무엇이 빠졌는지 알려 준다 — 지어 채우지 않는다.
"""

from __future__ import annotations

import csv
import json
import logging
import queue
import threading
import time
from pathlib import Path

log = logging.getLogger("sar_data.imaging")


def read_reflectors_csv(path: Path) -> list[tuple[float, float, float | None]]:
    """화면이 내려주는 reflectors.csv (name,lat,lon,…) 또는 lat,lon[,h] 줄."""
    out = []
    with path.open(encoding="utf-8") as f:
        for row in csv.reader(f):
            nums = []
            for cell in row:
                try:
                    nums.append(float(cell))
                except ValueError:
                    continue
            if len(nums) >= 2 and -90 <= nums[0] <= 90 and -180 <= nums[1] <= 180:
                out.append((nums[0], nums[1], None))
    return out


def parse_cr(text: str) -> list[tuple[float, float, float | None]]:
    """요청의 cr=lat,lon[,h];lat,lon …"""
    out = []
    for part in text.split(";"):
        nums = [float(x) for x in part.split(",") if x.strip()]
        if len(nums) >= 2:
            out.append((nums[0], nums[1], nums[2] if len(nums) > 2 else None))
    return out[:32]


class ImageJobs:
    def __init__(self, store, radar_json: Path | None, adapter: str | None,  # noqa: ANN001
                 reflectors_csv: Path | None = None, workers: int | None = None, full: bool = True,
                 former: str | None = None, focuser: str | None = None) -> None:
        self.store = store
        self.radar_json = radar_json
        self.adapter = adapter
        self.reflectors_csv = reflectors_csv
        self.workers = workers
        self.full = full
        self.former = former          # 팀의 영상 코드 "모듈:함수" (없으면 내장 백프로젝션)
        self.focuser = focuser        # 팀의 자동 초점 "모듈:함수" (없으면 내장 리플렉터 방식)
        self.q: queue.Queue = queue.Queue()
        self._busy: set[tuple[str, int]] = set()
        self._lock = threading.Lock()
        threading.Thread(target=self._run, name="sar-image", daemon=True).start()

    # ── 상태 ────────────────────────────────────────────────────────────────
    def missing(self) -> list[str]:
        out = []
        if self.radar_json is None or not self.radar_json.is_file():
            out.append("--radar-json (레이더 사양 · 레버암)")
        if not self.adapter:
            out.append("--adapter (레이더 원시 → 거리 압축, 예: sar_image.adapters:fmcw_dechirped_npz)")
        return out

    @staticmethod
    def out_dir(flight: Path, pass_no: int) -> Path:
        return flight / "images" / f"pass{pass_no:02d}"

    def status(self, flight: Path, pass_no: int) -> dict | None:
        p = self.out_dir(flight, pass_no) / "image.json"
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    # ── 요청 ────────────────────────────────────────────────────────────────
    def request(self, fid: str, pass_no: int, crs: list | None = None, force: bool = False) -> tuple[int, dict]:
        miss = self.missing()
        if miss:
            return 501, {"error": "이 서버에는 영상 설정이 없다", "missing": miss}
        flight = self.store.flight(fid)
        if flight is None:
            return 404, {"error": "not found"}
        info = next((p for p in self.store.passes(flight) if p["pass_no"] == pass_no), None)
        if info is None:
            return 404, {"error": f"패스 {pass_no} 가 없다"}
        cur = self.status(flight, pass_no)
        with self._lock:
            busy = (fid, pass_no) in self._busy
        if busy or (cur and cur.get("state") == "done" and not force and crs is None):
            return 200, cur or {"state": "queued"}
        if not info["radar_files"]:
            return 409, {"error": "이 패스에 맞는 레이더 원시 파일이 없다", "pass": pass_no}
        if crs is None:
            crs = self.flight_reflectors(flight, info)       # 비행 때 화면이 보낸 것 (정본)
        if not crs and self.reflectors_csv is not None and self.reflectors_csv.is_file():
            crs = read_reflectors_csv(self.reflectors_csv)
        out = self.out_dir(flight, pass_no)
        out.mkdir(parents=True, exist_ok=True)
        body = {"schema": "sar-image-0.1", "state": "queued", "queued_unix": time.time(), "reflectors": [], "full": None}
        # 화면이 2 초마다 읽는다 — 반쯤 쓴 파일을 읽지 않게 임시 파일에 쓰고 바꿔 끼운다
        tmp = out / "image.json.tmp"
        tmp.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        tmp.replace(out / "image.json")
        with self._lock:
            self._busy.add((fid, pass_no))
        self.q.put((fid, pass_no, crs or []))
        return 202, body

    @staticmethod
    def flight_reflectors(flight: Path, info: dict) -> list:
        try:
            meta = json.loads((flight / info["meta_json"]).read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError, TypeError):
            return []
        return [(r["lat"], r["lon"], r.get("h")) for r in meta.get("reflectors") or [] if "lat" in r and "lon" in r]

    def _run(self) -> None:
        while True:
            fid, pass_no, crs = self.q.get()
            try:
                self._form(fid, pass_no, crs)
            except Exception:  # noqa: BLE001 — 사유는 image.json 에 남았다
                log.exception("영상 실패 %s 패스 %s", fid, pass_no)
            finally:
                with self._lock:
                    self._busy.discard((fid, pass_no))

    def _form(self, fid: str, pass_no: int, crs: list) -> None:
        from sar_image.pipeline import form_pass
        from sar_image.radar import RadarConfig

        flight = self.store.flight(fid)
        info = next(p for p in self.store.passes(flight) if p["pass_no"] == pass_no)
        raw = [self.store.radar_path(flight, rf) for rf in info["radar_files"]]
        radar = RadarConfig.load(self.radar_json)  # type: ignore[arg-type]  — 요청마다 다시 읽는다(고친 값 바로 반영)
        log.info("영상 시작 %s 패스 %d · 원시 %d개 · 리플렉터 %d개", fid, pass_no, len(raw), len(crs))
        body = form_pass(flight / info["traj_csv"], raw, radar, self.adapter, self.out_dir(flight, pass_no),  # type: ignore[arg-type]
                         reflectors=crs, full=self.full, workers=self.workers, former=self.former, focuser=self.focuser)
        log.info("영상 끝 %s 패스 %d · %s · %s", fid, pass_no, body["state"], body["timings_s"])
