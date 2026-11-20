"""implements: AI-B-10, AI-E-01, AI-B-09

`ultralytics`가 없는 노드에서는 실물 추론 테스트만 skip된다 — 다른
capability의 검증을 막지 않는다(AI-C-05). 가중치 경로 존재 여부만 확인하는
`is_available()`, 누락 시 우아한 축소 경로, device 해석 테스트는 `ultralytics`
유무와 무관하게 항상 실행된다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from conftest import asset_path

#: 실제 가중치. 자리는 conftest 의 asset_root() 한 곳이 정한다.
WEIGHTS_PATH = asset_path("weights", "yolo", "FastSAM-s.pt")


def _ultralytics_importable() -> bool:
    try:
        import ultralytics  # noqa: F401
    except Exception:
        return False
    return True


def test_is_available_reflects_weights_presence():
    from mission_runtime.edge.fastsam_provider import FastSamPerceptionProvider

    provider = FastSamPerceptionProvider(WEIGHTS_PATH, device="cpu")

    assert provider.is_available() is WEIGHTS_PATH.exists()


def test_missing_weights_reports_unavailable_not_an_error():
    from mission_runtime.edge.fastsam_provider import FastSamPerceptionProvider

    provider = FastSamPerceptionProvider("/nonexistent/path/FastSAM-s.pt", device="cpu")

    assert provider.is_available() is False
    assert provider.detect(np.zeros((64, 64, 3), dtype=np.uint8)) == []


def test_device_defaults_to_a_probed_tag_not_a_hardcoded_vendor():
    from mission_runtime.edge.fastsam_provider import FastSamPerceptionProvider
    from mission_runtime.ondevice.rpn_propose import default_device

    provider = FastSamPerceptionProvider(WEIGHTS_PATH)

    # 규칙은 운영 코드가 소유한다 — 여기서 다시 유도하면 가속기를 쓰지 않기로 한
    # 선언이 시험만 비껴간다(실제로 그래서 이 시험 넷이 한 번 깨졌다).
    expected = default_device()
    assert provider.device == expected


def test_results_carry_the_fixed_non_semantic_label():
    from mission_runtime.edge.fastsam_provider import SEGMENT_ONLY_LABEL
    from mission_runtime.ondevice.rpn_propose import PROPOSAL_LABEL

    assert SEGMENT_ONLY_LABEL == PROPOSAL_LABEL


@pytest.mark.skipif(
    not (_ultralytics_importable() and WEIGHTS_PATH.exists()),
    reason="ultralytics 미설치 또는 FastSAM-s.pt 가중치 없음 (AI-C-05: 이 테스트만 skip)",
)
def test_detect_returns_class_agnostic_boxes_on_a_blank_frame():
    from mission_runtime.edge.fastsam_provider import SEGMENT_ONLY_LABEL, FastSamPerceptionProvider

    provider = FastSamPerceptionProvider(WEIGHTS_PATH, device="cpu")
    frame = np.zeros((320, 320, 3), dtype=np.uint8)

    results = provider.detect(frame)

    assert isinstance(results, list)
    assert all(r.label == SEGMENT_ONLY_LABEL for r in results)
    assert all(0.0 <= r.confidence <= 1.0 for r in results)
