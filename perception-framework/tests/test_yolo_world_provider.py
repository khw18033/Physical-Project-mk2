"""implements: AI-B-10, AI-E-01, AI-B-09

`ultralytics`가 없는 노드에서는 실물 추론 테스트만 skip된다 — 다른
capability의 검증을 막지 않는다(AI-C-11). 가중치 경로 존재 여부만 확인하는
`is_available()`, 누락 시 우아한 축소 경로, device 해석 테스트는 `ultralytics`
유무와 무관하게 항상 실행된다 — 이 환경(.venv)에는 `ultralytics`가 설치돼
있지 않지만 가중치 파일 자체는 저장소에 있으므로(연구 브랜치 산출물), 그
경로가 실제로 예외 없이 동작하는지 확인하는 것이 이 테스트 파일의 핵심 목적
중 하나다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

WEIGHTS_PATH = (
    Path(__file__).resolve().parents[2]
    / "research" / "oln_training" / "yolo_weights" / "yolov8s-worldv2.pt"
)


def _ultralytics_importable() -> bool:
    try:
        import ultralytics  # noqa: F401
    except Exception:
        return False
    return True


def test_empty_class_names_is_rejected_at_construction():
    from perception_framework.edge.yolo_world_provider import YoloWorldPerceptionProvider

    with pytest.raises(ValueError):
        YoloWorldPerceptionProvider([], WEIGHTS_PATH, device="cpu")


def test_is_available_reflects_weights_presence():
    from perception_framework.edge.yolo_world_provider import YoloWorldPerceptionProvider

    provider = YoloWorldPerceptionProvider(["door"], WEIGHTS_PATH, device="cpu")

    assert provider.is_available() is WEIGHTS_PATH.exists()


def test_missing_weights_reports_unavailable_not_an_error():
    from perception_framework.edge.yolo_world_provider import YoloWorldPerceptionProvider

    provider = YoloWorldPerceptionProvider(["door"], "/nonexistent/path/yolov8s-worldv2.pt", device="cpu")

    assert provider.is_available() is False
    assert provider.detect(np.zeros((64, 64, 3), dtype=np.uint8)) == []


def test_device_defaults_to_a_probed_tag_not_a_hardcoded_vendor():
    from perception_framework.edge.yolo_world_provider import YoloWorldPerceptionProvider
    from perception_framework.providers.compute import TAG_GPU, discover_node_tags

    provider = YoloWorldPerceptionProvider(["door"], WEIGHTS_PATH)

    expected = "cuda" if TAG_GPU in discover_node_tags() else "cpu"
    assert provider.device == expected


@pytest.mark.skipif(
    not (_ultralytics_importable() and WEIGHTS_PATH.exists()),
    reason="ultralytics 미설치 또는 yolov8s-worldv2.pt 가중치 없음 (AI-C-11: 이 테스트만 skip)",
)
def test_detect_returns_open_vocabulary_proposals_on_a_blank_frame():
    from perception_framework.edge.yolo_world_provider import YoloWorldPerceptionProvider

    provider = YoloWorldPerceptionProvider(["door", "person"], WEIGHTS_PATH, device="cpu")
    frame = np.zeros((320, 320, 3), dtype=np.uint8)

    results = provider.detect(frame)

    assert isinstance(results, list)
    assert all(0.0 <= r.confidence <= 1.0 for r in results)
    assert all(r.label in ("door", "person") for r in results)
