"""탐지 공급 — 미디어 한 줄기를 읽어 탐지 봉투로 바꾼다.

가시화 게이트웨이가 `detections` 채널을 채우는 자리다. **이 모듈은 소켓도 모르고
특정 카메라·모델도 모른다** — 미디어는 `MediaSourceProvider`, 탐지는
`PerceptionProvider` 뒤에 있고 둘 다 설정으로 들어온다(AI-C-04 · AI-C-08).

## 없으면 없다고 말한다

카메라가 없거나 탐지기가 없으면 **아무것도 발행하지 않고** 사유를 남긴다. 빈 배열을
보내면 화면이 "봤는데 아무것도 없다" 로 읽고, 그것은 "보지 않았다" 와 전혀 다른
사실이다(AI-C-05 · AI-O-04).

    none_configured   카메라를 지정하지 않았다
    media_unavailable 지정했는데 열리지 않는다(사유 동봉)
    no_detector       탐지 provider 가 뜨지 않았다(가중치 없음 등)
    no_frame          열렸는데 지금 프레임이 오지 않는다

## 픽셀은 나가지 않는다

봉투에는 **상자와 라벨만** 실린다. 프레임 자체는 미디어 경로의 몫이고 상태 계약에
얹지 않는다(AI-C-08, 절대 준수 #10).

## 좌표

상자는 **영상 좌표**다(`bbox_format="xyxy_pixel"`). 보정이나 전역 변환을 여기서
하지 않는다 — 보정 프로파일이 없어도 영상 좌표 결과는 계속 나가야 한다(AI-E-01).

implements: AI-E-01, AI-C-04, AI-C-05, AI-C-08, AI-S-02
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

#: 탐지기가 떴어도 프레임이 이보다 오래 끊기면 "지금 보고 있지 않다" 로 본다.
FRAME_GAP_S = 5.0


class MediaSource(Protocol):
    def read_frame(self) -> Any | None: ...
    def is_available(self) -> bool: ...
    def source_id(self) -> str: ...


class Detector(Protocol):
    def detect(self, frame: Any) -> list[Any]: ...


@dataclass
class FeedStatus:
    """지금 왜 내보내는가 / 왜 못 내보내는가. 레지스트리와 로그가 같은 값을 쓴다."""

    publishing: bool
    reason: str | None
    source_id: str | None = None
    model: str | None = None
    frames: int = 0
    detections: int = 0
    last_infer_ms: float | None = None

    def as_note(self) -> str:
        if self.publishing:
            return (f"detections 발행 중 — 소스 {self.source_id} · 모델 {self.model} · "
                    f"프레임 {self.frames} · 누적 탐지 {self.detections}")
        if self.reason is None:
            # 막힌 것이 **아니다** — 아직 첫 프레임을 읽지 않았을 뿐이다. 둘을 같은
            # 문구로 적으면 준비된 상태가 고장으로 읽힌다.
            return "detections 준비됨 — 아직 첫 프레임 전"
        return f"detections 발행하지 않음 — {self.reason}"


class DetectionFeed:
    """미디어 + 탐지기 한 쌍. 둘 중 하나라도 없으면 **조용히 비우지 않고** 사유를 든다."""

    def __init__(
        self,
        *,
        media: MediaSource | None,
        detector: Detector | None,
        model_name: str,
        producer: dict,
        camera_id: str,
        media_reason: str | None = None,
        detector_reason: str | None = None,
        clock=time.monotonic,
    ) -> None:
        self.media = media
        self.detector = detector
        self.model_name = model_name
        self.producer = dict(producer)
        self.camera_id = camera_id
        self._media_reason = media_reason
        self._detector_reason = detector_reason
        self._clock = clock
        self._seq = 0
        self._last_frame_at: float | None = None
        self.status = FeedStatus(publishing=False, reason=self._blocked_reason())

    def _blocked_reason(self) -> str | None:
        if self.media is None:
            return self._media_reason or "none_configured"
        if not self.media.is_available():
            return self._media_reason or "media_unavailable"
        if self.detector is None:
            return self._detector_reason or "no_detector"
        return None

    def tick(self) -> dict | None:
        """프레임 하나를 읽어 탐지 payload 를 만든다. 낼 것이 없으면 `None`.

        **`None` 과 「빈 detections」는 다른 뜻이다.** 앞은 보지 않은 것이고 뒤는
        보았는데 없었던 것이다.
        """
        blocked = self._blocked_reason()
        if blocked is not None:
            self.status = FeedStatus(publishing=False, reason=blocked,
                                     source_id=None, model=self.model_name,
                                     frames=self.status.frames,
                                     detections=self.status.detections)
            return None

        frame = self.media.read_frame()                     # type: ignore[union-attr]
        now = self._clock()
        if frame is None:
            stale = (self._last_frame_at is None
                     or now - self._last_frame_at > FRAME_GAP_S)
            if stale:
                self.status = FeedStatus(publishing=False, reason="no_frame",
                                         source_id=self.media.source_id(),  # type: ignore[union-attr]
                                         model=self.model_name,
                                         frames=self.status.frames,
                                         detections=self.status.detections)
            return None

        self._last_frame_at = now
        started = time.perf_counter()
        try:
            results = self.detector.detect(frame)           # type: ignore[union-attr]
        except Exception as exc:                            # noqa: BLE001
            # 탐지 실패가 게이트웨이를 멈추지 않는다 — 사유만 남기고 다음 프레임으로.
            self.status = FeedStatus(publishing=False,
                                     reason=f"detect_failed:{type(exc).__name__}",
                                     source_id=self.media.source_id(),  # type: ignore[union-attr]
                                     model=self.model_name,
                                     frames=self.status.frames,
                                     detections=self.status.detections)
            return None
        infer_ms = (time.perf_counter() - started) * 1000.0

        self._seq += 1
        height, width = _frame_size(frame)
        detections = [self._one(r) for r in results]
        self.status = FeedStatus(
            publishing=True, reason=None,
            source_id=self.media.source_id(),               # type: ignore[union-attr]
            model=self.model_name,
            frames=self.status.frames + 1,
            detections=self.status.detections + len(detections),
            last_infer_ms=round(infer_ms, 2))

        return {
            # 원본 관측으로 되짚을 참조. 같은 프레임의 파생 결과가 이것으로 묶인다(AI-C-03).
            "frame_ref": {"source_id": self.media.source_id(),  # type: ignore[union-attr]
                          "seq": self._seq},
            "emitted_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "model": self.model_name,
            "infer_ms": round(infer_ms, 2),
            "producer": self.producer,
            "width": width,
            "height": height,
            "bbox_format": "xyxy_pixel",
            # 다중 관측 연계는 **선택 기능**이고 이 배치에는 없다. 없을 때 연계
            # 신뢰도를 띄우면 없는 근거를 만드는 것이다(AI-S-02).
            "association": "unavailable",
            "detections": detections,
        }

    def _one(self, result: Any) -> dict:
        box = [float(v) for v in result.box]
        return {
            "label": str(result.label),
            "confidence": round(float(result.confidence), 4),
            "bbox": box,
            "camera_id": self.camera_id,
        }


def _frame_size(frame: Any) -> tuple[int, int]:
    shape = getattr(frame, "shape", None)
    if shape is not None and len(shape) >= 2:
        return int(shape[0]), int(shape[1])
    return 0, 0
