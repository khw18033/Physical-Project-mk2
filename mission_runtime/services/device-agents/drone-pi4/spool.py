"""링크가 끊긴 동안 말단이 결과를 잃지 않게 하는 디스크 스풀.

implements: AI-N-03, AI-C-05, AI-B-10, AI-O-03, AI-C-06

**이 모듈이 온디바이스 RPN의 존재 이유다.** 프레임을 엣지로 그냥 흘려보내는
설계라면 링크가 끊긴 구간은 통째로 사라진다. RPN이 말단에 있으면 그 구간에도
후보가 계속 생산되고, 여기 쌓였다가 링크가 돌아올 때 올라간다.

설계 선택과 이유:

* **전송은 절대 RPN을 막지 않는다.** 전송은 워커 스레드가 하고, 실패하면 스풀에
  남긴다. 말단의 인지 주기가 링크 품질에 끌려가면 AI-N-01/AI-C-05 위반이다.
* **용량은 바이트가 아니라 개수·나이로 제한한다.** 드론 저장소는 유한하고, 오래된
  프레임은 가치가 빠르게 떨어진다. 한계에 닿으면 **오래된 것부터** 버리고 몇 개를
  버렸는지 센다 — 조용히 사라지면 안 된다(AI-O-02).
* **프레임(미디어)과 메타(업무)를 따로 쓴다.** 한 항목이 `.json` + `.jpg` 두
  파일이라, 나중에 미디어만 다른 경로로 보내도록 바꿀 때 이 구조가 그대로 남는다
  (AI-C-06). 용량이 급하면 `drop_frames_first`로 픽셀만 버리고 메타는 살린다.
* **원자적 쓰기.** `.tmp`로 쓰고 rename한다. 비행 중 전원이 끊겨도 반쯤 쓰인
  항목을 읽지 않는다.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


class Spool:
    def __init__(self, root: Path, *, max_items: int = 500,
                 max_age_s: float = 1800.0, drop_frames_first: bool = True):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_items = max_items
        self.max_age_s = max_age_s
        self.drop_frames_first = drop_frames_first
        self.dropped_old = 0
        self.dropped_overflow = 0
        self.frames_shed = 0

    # -- 적재 --------------------------------------------------------------
    def put(self, key: str, meta: dict, frame_jpeg: bytes | None) -> None:
        stem = self.root / f"{meta.get('seq', 0):08d}_{key}"
        tmp = stem.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, stem.with_suffix(".json"))
        if frame_jpeg:
            ftmp = stem.with_suffix(".jpg.tmp")
            ftmp.write_bytes(frame_jpeg)
            os.replace(ftmp, stem.with_suffix(".jpg"))
        self._enforce_limits()

    # -- 인출 --------------------------------------------------------------
    def pending(self) -> list[Path]:
        """오래된 것부터. 링크가 돌아오면 순서대로 올린다."""
        return sorted(self.root.glob("*.json"))

    def read(self, p: Path) -> tuple[dict, bytes | None]:
        meta = json.loads(p.read_text(encoding="utf-8"))
        jpg = p.with_suffix(".jpg")
        return meta, (jpg.read_bytes() if jpg.exists() else None)

    def done(self, p: Path) -> None:
        for q in (p, p.with_suffix(".jpg")):
            try:
                q.unlink()
            except FileNotFoundError:
                pass

    # -- 한계 --------------------------------------------------------------
    def _enforce_limits(self) -> None:
        items = self.pending()
        now = time.time()

        # 1) 나이 초과는 통째로 버린다 — 오래된 후보는 되살릴 가치가 낮다.
        for p in list(items):
            try:
                age = now - json.loads(p.read_text(encoding="utf-8")).get("captured_at", now)
            except Exception:
                age = 0.0
            if age > self.max_age_s:
                self.done(p)
                self.dropped_old += 1
                items.remove(p)

        # 2) 개수 초과: 먼저 오래된 항목의 **픽셀만** 버려 메타는 살린다.
        if self.drop_frames_first and len(items) > self.max_items:
            for p in items[: len(items) - self.max_items]:
                jpg = p.with_suffix(".jpg")
                if jpg.exists():
                    jpg.unlink()
                    self.frames_shed += 1
            items = self.pending()

        # 3) 그래도 넘치면 오래된 것부터 버린다.
        overflow = len(items) - self.max_items
        for p in items[:max(0, overflow)]:
            self.done(p)
            self.dropped_overflow += 1

    def stats(self) -> dict:
        items = self.pending()
        return {"pending": len(items),
                "dropped_old": self.dropped_old,
                "dropped_overflow": self.dropped_overflow,
                "frames_shed": self.frames_shed}
