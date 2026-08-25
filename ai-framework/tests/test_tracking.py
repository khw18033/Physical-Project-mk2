"""tests for: AI-S-01"""

from ai_framework.perception.tracking import Detection, IouTracker, track_or_raw


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
