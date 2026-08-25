"""IOU-based multi-object tracker (AI-S-01).

Not tied to any specific tracking algorithm/library: this reference
tracker only needs per-frame detections and produces track identities
via simple greedy IOU matching. Upper-layer code should depend only on
`update()`'s return type, never on the matching algorithm inside it.
`track_or_raw` implements the required fallback: if no tracker is
available, callers keep using frame-by-frame detections directly
(AI-S-01: "추적 기능이 없거나 실패하면 프레임별 인지 결과만 유지해야 한다").
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Detection:
    box: tuple[float, float, float, float]  # x1, y1, x2, y2
    label: str | None = None


@dataclass
class Track:
    track_id: int
    box: tuple[float, float, float, float]
    label: str | None
    history: list[tuple[float, float, float, float]] = field(default_factory=list)
    missed_frames: int = 0


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


class IouTracker:
    """Greedy IOU matcher across consecutive frames.

    Tracks unmatched for more than `max_missed_frames` consecutive
    updates are dropped, so a brief occlusion does not lose identity.
    """

    def __init__(self, iou_threshold: float = 0.3, max_missed_frames: int = 2) -> None:
        self._iou_threshold = iou_threshold
        self._max_missed_frames = max_missed_frames
        self._tracks: dict[int, Track] = {}
        self._next_id = 1

    def update(self, detections: list[Detection]) -> list[Track]:
        unmatched = list(range(len(detections)))

        for track in self._tracks.values():
            best_idx, best_iou = None, 0.0
            for idx in unmatched:
                score = iou(track.box, detections[idx].box)
                if score > best_iou:
                    best_idx, best_iou = idx, score
            if best_idx is not None and best_iou >= self._iou_threshold:
                det = detections[best_idx]
                track.history.append(track.box)
                track.box = det.box
                track.label = det.label
                track.missed_frames = 0
                unmatched.remove(best_idx)
            else:
                track.missed_frames += 1

        for track_id in [tid for tid, t in self._tracks.items() if t.missed_frames > self._max_missed_frames]:
            del self._tracks[track_id]

        for idx in unmatched:
            det = detections[idx]
            self._tracks[self._next_id] = Track(track_id=self._next_id, box=det.box, label=det.label)
            self._next_id += 1

        return list(self._tracks.values())


def track_or_raw(tracker: IouTracker | None, detections: list[Detection]) -> list[Track] | list[Detection]:
    """AI-S-01 fallback path: no tracker (missing or failed) -> keep
    raw per-frame detections instead of failing."""
    if tracker is None:
        return list(detections)
    return tracker.update(detections)
