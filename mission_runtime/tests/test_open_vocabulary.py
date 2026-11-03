"""implements: AI-E-01, AI-S-04

모델 파일(models/openvocab/)이 없는 노드에서는 이 optional provider의 테스트만
skip된다 — 다른 capability의 검증을 막지 않는다(AI-C-11).
"""
from pathlib import Path

import pytest

from conftest import asset_path, demo_asset_path

MODEL_DIR = asset_path("models", "openvocab", "owlvit-base-patch32")
MODEL_PATH = MODEL_DIR / "onnx" / "model_quantized.onnx"
TOKENIZER_PATH = MODEL_DIR / "tokenizer.json"
#: 사람이 찍힌 **실제 사진**. 옛 fixture(TAO 한 프레임)는 이 기계에 없고, 이 시험이
#: 요구하는 것은 "사람이 있는 실제 사진"이지 그 특정 프레임이 아니다. 데모 자산의
#: 사람 참조 사진을 쓴다 — 자리는 conftest 한 곳이 정한다.
FIXTURE_IMAGE = demo_asset_path("person_reference.jpg")

pytestmark = pytest.mark.skipif(
    not (MODEL_PATH.exists() and TOKENIZER_PATH.exists() and FIXTURE_IMAGE.exists()),
    reason="OWL-ViT model/tokenizer/fixture image not present (README §4 새 기기에서 환경 복원)",
)


def _provider(vocab, **kwargs):
    from mission_runtime.perception.open_vocabulary import OwlVitPerceptionProvider

    return OwlVitPerceptionProvider(MODEL_PATH, TOKENIZER_PATH, vocab=vocab, **kwargs)


def test_empty_vocab_is_rejected_at_construction():
    from mission_runtime.perception.open_vocabulary import OwlVitPerceptionProvider

    with pytest.raises(ValueError):
        OwlVitPerceptionProvider(MODEL_PATH, TOKENIZER_PATH, vocab=[])


def test_concrete_noun_finds_the_known_person_in_the_fixture_frame():
    import cv2

    provider = _provider(["a person"], score_thr=0.10)
    frame = cv2.imread(str(FIXTURE_IMAGE))

    results = provider.detect(frame)

    assert len(results) > 0
    assert all(r.matched_vocab == "a person" for r in results)
    assert all(0.0 <= r.confidence <= 1.0 for r in results)


def test_abstract_generic_prompt_grounds_far_weaker_than_concrete_noun():
    """0B/0C 실험에서 실측된 결과(RESULTS.md)를 회귀 검증한다: 같은 프레임에서
    'an object' 최대 점수가 'a person' 최대 점수보다 뚜렷이 낮아야 한다."""
    import cv2

    provider = _provider(["a person", "an object"], score_thr=0.0)
    frame = cv2.imread(str(FIXTURE_IMAGE))

    results = provider.detect(frame)

    person_max = max((r.confidence for r in results if r.matched_vocab == "a person"), default=0.0)
    object_max = max((r.confidence for r in results if r.matched_vocab == "an object"), default=0.0)
    assert person_max > object_max


def test_result_records_which_execution_provider_actually_ran():
    provider = _provider(["a person"])

    assert provider.active_execution_provider() in ("CUDAExecutionProvider", "CPUExecutionProvider")


def test_box_coordinates_stay_within_frame_bounds():
    import cv2

    provider = _provider(["a person"], score_thr=0.10)
    frame = cv2.imread(str(FIXTURE_IMAGE))
    h, w = frame.shape[:2]

    results = provider.detect(frame)

    for r in results:
        x1, y1, x2, y2 = r.box
        assert -1.0 <= x1 < x2 <= w + 1.0
        assert -1.0 <= y1 < y2 <= h + 1.0
