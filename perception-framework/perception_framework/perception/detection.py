"""Common perception interface + a lightweight reference detector (AI-E-01).

implements: AI-B-09, AI-E-01

Perception must not branch on camera type, execution hardware, model
structure or runtime — callers depend only on the `PerceptionProvider`
Protocol. When no detector is available at all, callers still get
image-coordinate-only results (an empty detection list, not an error)
instead of failing (AI-E-01: "보정이나 추가 분석 기능이 없더라도 가능한
범위의 영상 좌표 기반 결과를 계속 제공"). `BrightBlobDetector` is a
dependency-light reference provider built only from cv2 primitives
(threshold + contour) that ship in every opencv-python build; it exists
to prove the `PerceptionProvider` contract is swappable, not to set an
accuracy bar — a YOLO/DNN-backed provider can replace it without any
caller change (AI-B-09: 검증 목적은 정확도가 아니라 인터페이스 준수 확인).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import cv2
import numpy as np


@dataclass(frozen=True)
class PerceptionResult:
    box: tuple[float, float, float, float]  # image-coordinate x1, y1, x2, y2
    label: str
    confidence: float


class PerceptionProvider(Protocol):
    def detect(self, frame: np.ndarray) -> list[PerceptionResult]: ...


class NullPerceptionProvider:
    """No detector available -- returns no detections, never raises."""

    def detect(self, frame: np.ndarray) -> list[PerceptionResult]:
        return []


class BrightBlobDetector:
    """Thresholds the frame and returns one bounding box per connected
    bright region above `min_area`.
    """

    def __init__(self, *, threshold: int = 127, min_area: float = 4.0) -> None:
        self._threshold = threshold
        self._min_area = min_area

    def detect(self, frame: np.ndarray) -> list[PerceptionResult]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        _, binary = cv2.threshold(gray, self._threshold, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        results = []
        for contour in contours:
            if cv2.contourArea(contour) < self._min_area:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            results.append(
                PerceptionResult(
                    box=(float(x), float(y), float(x + w), float(y + h)),
                    label="bright_object",
                    confidence=1.0,
                )
            )
        return results
