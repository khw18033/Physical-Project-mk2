"""implements: AI-B-10, AI-E-01, AI-B-09

ultralytics/가중치가 없는 노드에서는 이 optional provider의 실물 추론
테스트만 skip된다 — 다른 capability의 검증을 막지 않는다(AI-C-11).
"""
from pathlib import Path

import numpy as np
import pytest

WEIGHTS_PATH = (
    Path(__file__).resolve().parents[2]
    / "research" / "oln_training" / "yolo_weights" / "yolov8n.pt"
)


def _ultralytics_importable() -> bool:
    try:
        import ultralytics  # noqa: F401
    except Exception:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not (_ultralytics_importable() and WEIGHTS_PATH.exists()),
    reason="ultralytics 미설치 또는 yolov8n.pt 가중치 없음 (AI-C-11: 이 provider만 skip)",
)


def test_is_available_reflects_weights_presence():
    from perception_framework.ondevice.rpn_propose import RpnProposalProvider

    provider = RpnProposalProvider(WEIGHTS_PATH)

    assert provider.is_available() is True


def test_missing_weights_reports_unavailable_not_an_error():
    from perception_framework.ondevice.rpn_propose import RpnProposalProvider

    provider = RpnProposalProvider("/nonexistent/path/yolov8n.pt", device="cpu")

    assert provider.is_available() is False
    assert provider.detect(np.zeros((64, 64, 3), dtype=np.uint8)) == []


def test_detect_returns_class_agnostic_proposals_on_a_blank_frame():
    from perception_framework.ondevice.rpn_propose import PROPOSAL_LABEL, RpnProposalProvider

    provider = RpnProposalProvider(WEIGHTS_PATH, device="cpu")
    frame = np.zeros((320, 320, 3), dtype=np.uint8)

    results = provider.detect(frame)

    # A blank frame need not yield any proposal, but whatever comes back must
    # be class-agnostic (label carries no semantic meaning here by design).
    assert all(r.label == PROPOSAL_LABEL for r in results)
    assert all(0.0 <= r.confidence <= 1.0 for r in results)


def test_device_defaults_to_a_probed_tag_not_a_hardcoded_vendor():
    from perception_framework.ondevice.rpn_propose import RpnProposalProvider
    from perception_framework.providers.compute import discover_node_tags

    provider = RpnProposalProvider(WEIGHTS_PATH)

    from perception_framework.providers.compute import TAG_GPU

    expected = "cuda" if TAG_GPU in discover_node_tags() else "cpu"
    assert provider.device == expected
