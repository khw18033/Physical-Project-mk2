"""implements: AI-E-01, AI-B-09

`transformers`가 없는 노드에서는 실물 추론(HF Hub 다운로드가 필요한) 테스트만
skip된다 — 다른 capability의 검증을 막지 않는다(AI-C-11). 구성/누락 시 우아한
축소 경로(`is_available()`, `detect()`가 예외 없이 빈 리스트를 반환하는 경로)와
device 해석 테스트는 `transformers` 유무와 무관하게 항상 실행된다 — 이
환경(.venv)에는 `transformers`가 설치돼 있지 않으므로, 그 경로가 실제로 예외
없이 동작하는지 확인하는 것이 이 테스트 파일의 핵심 목적 중 하나다.
"""

from __future__ import annotations

import numpy as np
import pytest


def _transformers_importable() -> bool:
    try:
        import transformers  # noqa: F401
    except Exception:
        return False
    return True


def test_empty_class_names_is_rejected_at_construction():
    from perception_framework.edge.grounding_dino_provider import GroundingDinoPerceptionProvider

    with pytest.raises(ValueError):
        GroundingDinoPerceptionProvider([], device="cpu")


def test_is_available_matches_actual_transformers_importability():
    from perception_framework.edge.grounding_dino_provider import GroundingDinoPerceptionProvider

    provider = GroundingDinoPerceptionProvider(["a person"], device="cpu")

    assert provider.is_available() is _transformers_importable()


def test_device_defaults_to_a_probed_tag_not_a_hardcoded_vendor():
    from perception_framework.edge.grounding_dino_provider import GroundingDinoPerceptionProvider
    from perception_framework.providers.compute import TAG_GPU, discover_node_tags

    provider = GroundingDinoPerceptionProvider(["a person"])

    expected = "cuda" if TAG_GPU in discover_node_tags() else "cpu"
    assert provider.device == expected


@pytest.mark.skipif(
    _transformers_importable(),
    reason="이 테스트는 transformers 부재 경로를 검증한다 -- 설치된 환경에서는 대상이 아니다",
)
def test_missing_transformers_reports_unavailable_and_detect_returns_empty_without_raising():
    from perception_framework.edge.grounding_dino_provider import GroundingDinoPerceptionProvider

    provider = GroundingDinoPerceptionProvider(["a person"], device="cpu")

    assert provider.is_available() is False
    assert provider.detect(np.zeros((64, 64, 3), dtype=np.uint8)) == []


@pytest.mark.skipif(not _transformers_importable(), reason="transformers 미설치 (AI-C-11: 이 테스트만 skip)")
def test_detect_on_synthetic_frame_is_best_effort_and_respects_contract_shape():
    """HF Hub 다운로드가 필요한 best-effort 테스트다: 네트워크가 없어 모델을 받지
    못하면 provider가 예외 없이 빈 리스트를 반환하는 것까지만 확인한다 -- 그
    경로도 이 provider가 지켜야 할 계약의 일부다(AI-C-05: 선택 기능 실패가 다른
    기능을 막지 않는다)."""
    from perception_framework.edge.grounding_dino_provider import GroundingDinoPerceptionProvider

    provider = GroundingDinoPerceptionProvider(["a person"], device="cpu")
    frame = np.zeros((64, 64, 3), dtype=np.uint8)

    results = provider.detect(frame)

    assert isinstance(results, list)
    assert all(0.0 <= r.confidence <= 1.0 for r in results)
