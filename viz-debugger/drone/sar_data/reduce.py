"""Pi 쪽 — 패스가 끝나면 레이더 원시를 거리 압축 파일로 줄여 둔다. 노트북 미러는 줄인 것만 핫스팟으로 가져간다.

    python -m sar_data --flights … --radar … --reduce-adapter sar_image.sdr:iq_npy --radar-json /home/physical/radar.json

SDR(AD9361) 원시는 패스 하나에 수백 MB~수 GB 다. 거리 압축(정합 필터)하고 기록 거리 창(range_min~max)만 남기면
수백 분의 일이 된다(시험: 120 MB → 0.1 MB). 원시는 그대로 두니 나중에 USB 로 옮겨 다시 처리할 수 있다.
결과: <비행>/radar_rc/passNN/<원시 이름>.rc.npz  (t · range_axis · rc complex64)
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import numpy as np

log = logging.getLogger("sar_data.reduce")


class Reducer:
    def __init__(self, store, radar_json: Path, adapter: str, settle_s: float = 15.0, interval_s: float = 5.0) -> None:  # noqa: ANN001
        self.store = store
        self.radar_json = radar_json
        self.adapter_spec = adapter
        self.settle_s = settle_s
        self.interval_s = interval_s
        self.failed: set[str] = set()
        self.done = 0
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._loop, name="sar-reduce", daemon=True).start()

    def state(self) -> dict:
        return {"ready": True, "adapter": self.adapter_spec, "reduced_files": self.done, "failed": sorted(self.failed)[-5:]}

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self.once()
            except Exception:  # noqa: BLE001
                log.exception("줄이기 확인 실패")

    def once(self, now: float | None = None) -> int:
        from sar_image.pipeline import load_adapter
        from sar_image.radar import RadarConfig

        now = time.time() if now is None else now
        adapter = load_adapter(self.adapter_spec)
        accepts = getattr(adapter, "accepts", None)
        radar = RadarConfig.load(self.radar_json)
        made = 0
        for d in self.store.flight_dirs():
            for p in self.store.passes(d):
                end = p.get("ack_end_unix") or p.get("end_unix")
                if not isinstance(p.get("pass_no"), int) or end is None or now < end + self.settle_s:
                    continue
                out_dir = d / "radar_rc" / f"pass{p['pass_no']:02d}"
                for rf in p["radar_files"]:
                    src = self.store.radar_path(d, rf)
                    if accepts is not None and not accepts(src):
                        continue
                    out = out_dir / (Path(rf["name"]).name + ".rc.npz")
                    key = str(src)
                    if out.exists() or key in self.failed:
                        continue
                    t0 = time.perf_counter()
                    try:
                        t, rng, rc = adapter(str(src), radar)
                        out_dir.mkdir(parents=True, exist_ok=True)
                        tmp = out.with_name(out.name + ".part.npz")
                        np.savez(tmp, t=np.asarray(t, dtype=np.float64), range_axis=np.asarray(rng, dtype=np.float64),
                                 rc=np.asarray(rc, dtype=np.complex64))
                        tmp.replace(out)
                        made += 1
                        self.done += 1
                        log.info("줄임 %s → %s (%.1f MB → %.1f MB, %.1f s)", src.name, out.name, src.stat().st_size / 1e6,
                                 out.stat().st_size / 1e6, time.perf_counter() - t0)
                    except Exception:  # noqa: BLE001 — 한 번 실패한 파일은 다시 시도하지 않는다(로그만)
                        self.failed.add(key)
                        log.exception("줄이기 실패 %s", src)
        return made
