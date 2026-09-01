"""implements: AI-O-03, AI-L-05, AI-L-08"""

from pathlib import Path

from perception_framework.observability import validation_artifacts as common


def test_frame_selection_is_lexicographic_and_bounded(tmp_path):
    for video in ("video_b", "video_a", "video_c"):
        folder = tmp_path / video
        folder.mkdir()
        (folder / "frame2.jpg").write_bytes(video.encode())
        (folder / "frame1.jpg").write_bytes(video.encode())

    selected = common.select_frame_paths(tmp_path, video_limit=2, frame_limit=3)

    assert [path.relative_to(tmp_path).as_posix() for path in selected] == [
        "video_a/frame1.jpg",
        "video_a/frame2.jpg",
        "video_b/frame1.jpg",
    ]


def test_manifest_records_hashes_without_model_based_selection(tmp_path):
    frame = tmp_path / "v" / "frame.jpg"
    frame.parent.mkdir()
    frame.write_bytes(b"fixed")

    manifest = common.build_manifest(tmp_path, [frame], purpose="smoke")

    assert manifest["selection"] == "lexicographic-video-prefix-then-frame-prefix"
    assert manifest["count"] == 1
    assert manifest["items"][0]["sha256"] == common.sha256_file(frame)
