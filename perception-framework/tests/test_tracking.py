"""implements: AI-S-01"""

from perception_framework.perception.tracking import ByteTracker, Detection, IouTracker, track_or_raw


def test_same_object_keeps_same_track_id_across_frames():
    tracker = IouTracker()

    tracks_1 = tracker.update([Detection(box=(0, 0, 10, 10))])
    tracks_2 = tracker.update([Detection(box=(1, 1, 11, 11))])

    assert len(tracks_1) == 1
    assert len(tracks_2) == 1
    assert tracks_1[0].track_id == tracks_2[0].track_id


def test_brief_occlusion_does_not_lose_identity():
    tracker = IouTracker(max_missed_frames=2)
    first = tracker.update([Detection(box=(0, 0, 10, 10))])[0]

    tracker.update([])  # missed frame 1
    still_there = tracker.update([Detection(box=(1, 1, 11, 11))])

    assert still_there[0].track_id == first.track_id


def test_unknown_object_keeps_identity_without_a_trained_class():
    tracker = IouTracker(max_missed_frames=2)

    first = tracker.update([Detection(box=(0, 0, 10, 10), label="unknown")])[0]
    tracker.update([])
    reacquired = tracker.update([Detection(box=(1, 1, 11, 11), label="unknown")])[0]

    assert reacquired.track_id == first.track_id
    assert reacquired.label == "unknown"


def test_track_dropped_after_too_many_missed_frames():
    tracker = IouTracker(max_missed_frames=1)
    first = tracker.update([Detection(box=(0, 0, 10, 10))])[0]

    tracker.update([])  # missed 1
    tracker.update([])  # missed 2 -> exceeds max_missed_frames

    survivors = tracker.update([Detection(box=(0, 0, 10, 10))])
    assert first.track_id not in [t.track_id for t in survivors]


def test_no_tracker_falls_back_to_raw_frame_by_frame_detections():
    detections = [Detection(box=(0, 0, 10, 10))]

    result = track_or_raw(None, detections)

    assert result == detections


# --- ByteTracker (papers/bytetrack.md §4의 2단계 연관) ----------------------


def test_bytetracker_low_score_detection_recovers_existing_track():
    """occlusion 등으로 score가 떨어진 low-score box도 기존 track을 살린다."""
    tracker = ByteTracker(high_thresh=0.6, low_thresh=0.1)
    first = tracker.update([Detection(box=(0, 0, 10, 10), score=0.9)])[0]

    # 다음 프레임: 같은 물체지만 score가 high_thresh 밑으로 떨어짐(occlusion 가정)
    recovered = tracker.update([Detection(box=(1, 1, 11, 11), score=0.2)])

    assert len(recovered) == 1
    assert recovered[0].track_id == first.track_id


def test_bytetracker_low_score_detection_never_spawns_new_track():
    """low-score box는 기존 track 복구에만 쓰이고 새 track을 만들지 않는다
    (배경 오탐이 새 track으로 태어나는 것을 막는 BYTE의 핵심 동작)."""
    tracker = ByteTracker(high_thresh=0.6, low_thresh=0.1)

    tracks = tracker.update([Detection(box=(0, 0, 10, 10), score=0.2)])

    assert tracks == []


def test_bytetracker_high_score_unmatched_detection_spawns_new_track():
    tracker = ByteTracker(high_thresh=0.6, low_thresh=0.1)

    tracks = tracker.update([Detection(box=(0, 0, 10, 10), score=0.9)])

    assert len(tracks) == 1


def test_bytetracker_below_low_thresh_detection_is_ignored():
    tracker = ByteTracker(high_thresh=0.6, low_thresh=0.1)
    first = tracker.update([Detection(box=(0, 0, 10, 10), score=0.9)])[0]

    # score가 low_thresh 밑 -> 매칭에도, 새 track 생성에도 쓰이지 않음
    tracker.update([Detection(box=(1, 1, 11, 11), score=0.05)])
    still_missed = tracker.update([Detection(box=(1, 1, 11, 11), score=0.05)])

    # 원래 track은 아직 max_missed_frames(기본 2) 안이라 살아있어야 함
    assert any(t.track_id == first.track_id for t in still_missed)
    # 하지만 그 low box로 위치가 갱신되지는 않았어야 함 (matched 안 됐으므로 box 그대로)
    kept = next(t for t in still_missed if t.track_id == first.track_id)
    assert kept.box == (0, 0, 10, 10)
