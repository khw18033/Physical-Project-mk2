"""IOU-based multi-object tracker (AI-S-01).

implements: AI-S-01

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
class ByteTrackFeatureProfile:
    """Explicitly separates this fixture from the official ByteTrack stack."""

    two_stage_score_association: bool = True
    low_score_track_recovery: bool = True
    kalman_motion_prediction: bool = False
    hungarian_assignment: bool = False


BYTE_TRACK_FEATURE_PROFILE = ByteTrackFeatureProfile()


@dataclass(frozen=True)
class Detection:
    box: tuple[float, float, float, float]  # x1, y1, x2, y2
    label: str | None = None
    score: float = 1.0


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


def _greedy_match(
    tracks: list[Track], detections: list[Detection], candidate_idx: list[int], iou_threshold: float
) -> tuple[dict[int, int], list[int]]:
    """One greedy IOU association pass.

    Matches each track (by its position in `tracks`) against at most one
    detection index drawn from `candidate_idx`. Returns
    `{track_position: matched_detection_index}` and the remaining
    unmatched candidate indices, in that order. Pure matching logic with
    no track/detection mutation, so both `IouTracker` and `ByteTracker`
    share one implementation instead of two copies that can drift.
    """
    remaining = list(candidate_idx)
    assigned: dict[int, int] = {}
    for pos, track in enumerate(tracks):
        best_idx, best_iou = None, 0.0
        for idx in remaining:
            score = iou(track.box, detections[idx].box)
            if score > best_iou:
                best_idx, best_iou = idx, score
        if best_idx is not None and best_iou >= iou_threshold:
            assigned[pos] = best_idx
            remaining.remove(best_idx)
    return assigned, remaining


class ByteTracker:
    """Two-stage IOU association (BYTE, Zhang et al. ECCV 2022).

    implements: AI-S-01 (교체 가능한 추적 provider)

    `docs/obsidian/papers/bytetrack.md`의 §4 구조를 그대로 따른다: 매 프레임의
    detection을 score로 high/low 두 그룹으로 나누고, 기존 track을 먼저
    high-score detection과 매칭한 뒤 아직 안 풀린 track만 low-score
    detection과 다시 매칭한다. New track은 **high-score의 미매칭분에서만**
    생성한다 — low-score box는 기존 track을 살리는 데만 쓰고 배경 오탐이
    새 track으로 태어나지 않게 막는 것이 BYTE의 핵심(papers/bytetrack.md
    §3 "Low-score Detection Box 복구").

    원 논문은 Kalman filter로 다음 프레임 위치를 예측한 뒤 그 예측 위치에
    대해 IOU를 계산한다. 이 구현은 `IouTracker`와 동일하게 **직전 프레임의
    관측 위치를 그대로 예측값으로 쓰는 가장 단순한 버전**이다 — Kalman
    filter 도입은 이 baseline과 비교해 실제 이득이 있는지 확인한 뒤
    별도로 검토한다(§21 "가장 단순한 baseline부터").
    """

    def __init__(
        self,
        high_thresh: float = 0.6,
        low_thresh: float = 0.1,
        iou_threshold: float = 0.3,
        low_iou_threshold: float = 0.5,
        max_missed_frames: int = 2,
    ) -> None:
        self._high_thresh = high_thresh
        self._low_thresh = low_thresh
        self._iou_threshold = iou_threshold
        self._low_iou_threshold = low_iou_threshold
        self._max_missed_frames = max_missed_frames
        self._tracks: dict[int, Track] = {}
        self._next_id = 1

    def update(self, detections: list[Detection]) -> list[Track]:
        high_idx = [i for i, d in enumerate(detections) if d.score >= self._high_thresh]
        low_idx = [i for i, d in enumerate(detections) if self._low_thresh <= d.score < self._high_thresh]

        track_ids = list(self._tracks.keys())
        tracks = [self._tracks[tid] for tid in track_ids]

        # stage 1: existing tracks vs high-score detections
        assigned_1, unmatched_high = _greedy_match(tracks, detections, high_idx, self._iou_threshold)
        unmatched_track_pos = [pos for pos in range(len(tracks)) if pos not in assigned_1]

        # stage 2: still-unmatched tracks vs low-score detections (recover, never spawn)
        remaining_tracks = [tracks[pos] for pos in unmatched_track_pos]
        assigned_2, _ = _greedy_match(remaining_tracks, detections, low_idx, self._low_iou_threshold)

        matched_this_frame: set[int] = set()
        for pos, det_idx in assigned_1.items():
            track, det = tracks[pos], detections[det_idx]
            track.history.append(track.box)
            track.box, track.label, track.missed_frames = det.box, det.label, 0
            matched_this_frame.add(track_ids[pos])
        for local_pos, det_idx in assigned_2.items():
            pos = unmatched_track_pos[local_pos]
            track, det = tracks[pos], detections[det_idx]
            track.history.append(track.box)
            track.box, track.label, track.missed_frames = det.box, det.label, 0
            matched_this_frame.add(track_ids[pos])

        for tid in track_ids:
            if tid not in matched_this_frame:
                self._tracks[tid].missed_frames += 1

        for tid in [t for t, tr in self._tracks.items() if tr.missed_frames > self._max_missed_frames]:
            del self._tracks[tid]

        for idx in unmatched_high:
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
