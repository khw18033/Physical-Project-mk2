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
    # 최근 프레임 간 중심 이동(px). 연관에만 쓰고 보고에는 쓰지 않는다.
    velocity: tuple[float, float] = (0.0, 0.0)
    # 이번 프레임 연관에 사용할 예측 박스. None이면 관측 박스를 그대로 쓴다.
    predicted: tuple[float, float, float, float] | None = None

    def match_box(self) -> tuple[float, float, float, float]:
        """연관에 쓸 박스. **보고되는 박스(`box`)와 일부러 분리한다.**

        예측 위치를 `box`에 써 버리면 관측하지 않은 좌표를 관측처럼 내보내게 된다
        (AI-S-03). 예측은 "이 트랙을 어느 검출과 이을까"를 정할 때만 쓰고, 이어진
        뒤 보고하는 좌표는 언제나 실제 검출 좌표다.
        """
        return self.predicted or self.box


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
                score = iou(track.match_box(), detections[idx].box)
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


def _global_shift(tracks: list[Track], detections: list[Detection],
                  max_probe: int = 48) -> tuple[float, float]:
    """검출만으로 **프레임 간 전역 이동**을 추정한다(카메라 팬).

    왜 필요한가: 트랙별 속도는 **매칭이 성립해야** 쌓이는데, 낮은 프레임률에서는
    첫 매칭부터 실패한다. 속도가 없으니 예측이 없고, 예측이 없으니 매칭이 없다 —
    닭과 달걀이다. 실제로 2026-09-21 첫 구현이 여기서 막혔다.

    드론에서 지배적인 움직임은 **모든 트랙이 공유하는 시야 이동**이므로, 개별 속도
    없이도 전역 값 하나를 추정할 수 있다. 각 트랙에서 가장 가까운 검출까지의 변위를
    모아 **중앙값**을 쓴다 — 중앙값이라 잘못 짝지어진 것이 섞여도 흔들리지 않는다.

    픽셀을 보지 않는다. 광학 흐름이나 phase correlation이 더 정확하겠지만 그러면
    추적기가 영상에 의존하게 되고, AI-S-01은 추적이 **인지 결과 계약에만** 의존하라고
    요구한다. 여기서 쓰는 입력은 박스뿐이다.
    """
    if not tracks or not detections:
        return (0.0, 0.0)
    dx: list[float] = []
    dy: list[float] = []
    for track in tracks[:max_probe]:
        tw = track.box[2] - track.box[0]
        th = track.box[3] - track.box[1]
        gate = 1.5 * max(tw, th, 1.0)          # 이 밖의 검출은 같은 물체로 보지 않는다
        tcx, tcy = (track.box[0] + track.box[2]) / 2, (track.box[1] + track.box[3]) / 2
        best, bd = None, gate
        for det in detections:
            # 크기가 크게 다르면 같은 물체가 아니다 — 가까워도 짝짓지 않는다.
            dw = det.box[2] - det.box[0]
            dh = det.box[3] - det.box[1]
            if not (0.5 <= dw / max(tw, 1e-6) <= 2.0 and 0.5 <= dh / max(th, 1e-6) <= 2.0):
                continue
            ccx, ccy = (det.box[0] + det.box[2]) / 2, (det.box[1] + det.box[3]) / 2
            d = ((ccx - tcx) ** 2 + (ccy - tcy) ** 2) ** 0.5
            if d < bd:
                best, bd = (ccx - tcx, ccy - tcy), d
        if best is not None:
            dx.append(best[0])
            dy.append(best[1])
    if len(dx) < 3:                            # 근거가 너무 적으면 추정하지 않는다
        return (0.0, 0.0)
    dx.sort()
    dy.sort()
    m = len(dx) // 2
    return (dx[m], dy[m])


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
            score = iou(track.match_box(), detections[idx].box)
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
        motion_prediction: bool = False,
        velocity_alpha: float = 0.5,
    ) -> None:
        self._high_thresh = high_thresh
        self._low_thresh = low_thresh
        self._iou_threshold = iou_threshold
        self._low_iou_threshold = low_iou_threshold
        self._max_missed_frames = max_missed_frames
        # **낮은 프레임률에서는 예측 없이 연관이 성립하지 않는다.** 2026-09-21 실측:
        # pi4 두 카메라를 번갈아 처리해 카메라당 1.1~2.1 fps였다. 0.5~0.9초 간격이면
        # 시야가 움직일 때 같은 물체의 프레임 간 IoU가 0에 가까워지고, 그러면 매 프레임
        # 새 track_id가 생겨 지연 근거를 붙일 앵커가 사라진다(사용자 보고: "화면 변화가
        # 생겼을 때 추론 결과가 매번 달라짐, track이 잘 안 됨").
        # 등속 예측은 Kalman보다 단순하지만 이 문제의 지배적인 부분(일정한 방향의
        # 시야 이동)을 덮는다. 더 복잡한 모델이 필요한지는 이것을 켠 뒤 재측정해 정한다.
        self._motion_prediction = motion_prediction
        self._velocity_alpha = velocity_alpha
        self._tracks: dict[int, Track] = {}
        self._next_id = 1

    def update(self, detections: list[Detection]) -> list[Track]:
        # 연관 전에 각 트랙의 예측 위치를 정한다. 보고용 box는 건드리지 않는다.
        # 트랙 자신의 속도가 있으면 그것을, 없으면 전역 이동 추정치를 쓴다 —
        # 후자가 없으면 낮은 프레임률에서 첫 매칭 자체가 성립하지 않는다.
        if self._motion_prediction and self._tracks:
            gx, gy = _global_shift(list(self._tracks.values()), detections)
        else:
            gx = gy = 0.0
        for t in self._tracks.values():
            if not self._motion_prediction:
                t.predicted = None
                continue
            vx, vy = t.velocity if (t.velocity[0] or t.velocity[1]) else (gx, gy)
            if not (vx or vy):
                t.predicted = None
                continue
            # 놓친 프레임만큼 더 멀리 갔다고 본다 — 가려졌다 나온 물체를 되찾는다.
            k = 1 + t.missed_frames
            t.predicted = (t.box[0] + vx * k, t.box[1] + vy * k,
                           t.box[2] + vx * k, t.box[3] + vy * k)

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

        def _accept(track: Track, det: Detection) -> None:
            """이어진 검출을 트랙에 반영한다. 보고 좌표는 **언제나 실제 검출**이다."""
            a = self._velocity_alpha
            ocx, ocy = (track.box[0] + track.box[2]) / 2, (track.box[1] + track.box[3]) / 2
            ncx, ncy = (det.box[0] + det.box[2]) / 2, (det.box[1] + det.box[3]) / 2
            k = max(1, 1 + track.missed_frames)
            track.velocity = (track.velocity[0] * (1 - a) + (ncx - ocx) / k * a,
                              track.velocity[1] * (1 - a) + (ncy - ocy) / k * a)
            track.history.append(track.box)
            track.box, track.label, track.missed_frames = det.box, det.label, 0
            track.predicted = None

        matched_this_frame: set[int] = set()
        for pos, det_idx in assigned_1.items():
            _accept(tracks[pos], detections[det_idx])
            matched_this_frame.add(track_ids[pos])
        for local_pos, det_idx in assigned_2.items():
            pos = unmatched_track_pos[local_pos]
            _accept(tracks[pos], detections[det_idx])
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
