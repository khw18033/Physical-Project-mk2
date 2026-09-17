"""implements: AI-E-04, AI-S-04, AI-S-06, AI-C-11

CLIP 모델 파일이 없는 노드에서는 이 optional provider의 테스트만 skip된다
(AI-C-11). 이 저장소에는 실측 검증에 쓰인 실제 door 클래스 설정과 프레임이
있어서 회귀 테스트로 "왜 이 점수가 나왔는지"까지 확인한다 —
`탐지_연동스키마_260912.md`에 실린 실제 예시(frame_000113.jpg, final_score
0.2696)와 대조 가능하다.
"""
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CLIP_DIR = REPO_ROOT / "models" / "openvocab" / "clip-vit-base-patch32"
VISION_MODEL = CLIP_DIR / "onnx" / "vision_model_quantized.onnx"
TEXT_MODEL = CLIP_DIR / "onnx" / "text_model_quantized.onnx"
TOKENIZER = CLIP_DIR / "tokenizer.json"
CLASS_FEATURES_PATH = REPO_ROOT / "demo" / "test" / "class_features.json"
DOOR_FRAME = REPO_ROOT / "datasets" / "20260910-134818_rot8" / "frame_000113.jpg"

# demo/test/class_finder_service.py의 BORDER_CROP_BOX = (114, 80, 351, 321) --
# 탐지_연동스키마_260912.md의 evidence.json 예시 box_xyxy는 border-cropped
# 좌표라, 원본 프레임 좌표로 되돌리려면 (114, 80)을 더해야 한다.
_BORDER_CROP_OFFSET = (114, 80)
_DOOR_BOX_BORDER_CROPPED = (140.76, 89.67, 160.93, 143.73)
DOOR_BOX_ORIGINAL = (
    _DOOR_BOX_BORDER_CROPPED[0] + _BORDER_CROP_OFFSET[0],
    _DOOR_BOX_BORDER_CROPPED[1] + _BORDER_CROP_OFFSET[1],
    _DOOR_BOX_BORDER_CROPPED[2] + _BORDER_CROP_OFFSET[0],
    _DOOR_BOX_BORDER_CROPPED[3] + _BORDER_CROP_OFFSET[1],
)

pytestmark = pytest.mark.skipif(
    not (VISION_MODEL.exists() and TEXT_MODEL.exists() and TOKENIZER.exists()
         and CLASS_FEATURES_PATH.exists() and DOOR_FRAME.exists()),
    reason="CLIP onnx 모델/토크나이저/클래스 설정/프레임 fixture 중 일부가 없음 (AI-C-11)",
)


def _engine():
    from perception_framework.edge.clip_dictionary_provider import ClipEngine

    return ClipEngine(VISION_MODEL, TEXT_MODEL, TOKENIZER)


def _door_provider():
    from perception_framework.edge.clip_dictionary_provider import ClipDictionaryPerceptionProvider

    class_dict = json.loads(CLASS_FEATURES_PATH.read_text(encoding="utf-8"))
    return ClipDictionaryPerceptionProvider("door", class_dict["door"], _engine(), repo_root=REPO_ROOT)


def test_empty_candidate_list_returns_no_results():
    provider = _door_provider()

    assert provider.score_candidates(_read_frame(), []) == []


def _read_frame():
    import cv2

    frame = cv2.imread(str(DOOR_FRAME))
    assert frame is not None, f"could not read fixture frame {DOOR_FRAME}"
    return frame


def test_known_door_candidate_passes_all_mandatory_gates():
    """실측 검증 재현: frame_000113.jpg의 실제 문 박스는 색/모양/기준영상/채도
    게이트를 전부 통과하고 점수가 target_sim_threshold 이상이어야 한다."""
    from perception_framework.contracts.data_dictionary import FEATURE_SIMILARITIES, MANDATORY_GATES

    provider = _door_provider()
    frame = _read_frame()

    results = provider.score_candidates(frame, [DOOR_BOX_ORIGINAL])

    assert len(results) == 1
    result = results[0]
    assert result.confidence >= provider.target_sim_threshold
    assert FEATURE_SIMILARITIES in result.detail
    assert MANDATORY_GATES in result.detail
    for gate_name, gate in result.detail[MANDATORY_GATES].items():
        assert gate["passed"] is True, f"gate {gate_name} unexpectedly failed: {gate}"
    # 2026-09-16 실제 로봇 리허설 반영(research/door_gate_harden) 회귀 확인:
    # hue_gate가 door 설정에 있고, 실제 door detail에 등장해야 한다.
    assert provider.hue_cfg is not None
    assert "hue" in result.detail[MANDATORY_GATES]
    assert "median_hue" in result.detail[MANDATORY_GATES]["hue"]


def test_color_and_shape_gates_report_their_tolerance_and_margin():
    """2026-09-16 door_gate_relax 반영: 1등이 아니라 마진 이내면 통과하는
    방식으로 바뀌었다 -- 근거(margin)가 evidence에 남아야 재현 가능하다."""
    provider = _door_provider()
    frame = _read_frame()

    results = provider.score_candidates(frame, [DOOR_BOX_ORIGINAL])

    from perception_framework.contracts.data_dictionary import MANDATORY_GATES

    color_gate = results[0].detail[MANDATORY_GATES]["color"]
    shape_gate = results[0].detail[MANDATORY_GATES]["shape"]
    assert color_gate["tolerance"] == provider.color_gate_tolerance
    assert "margin_from_winner" in color_gate
    assert shape_gate["tolerance"] == provider.shape_gate_tolerance
    assert "margin_positive_minus_negative" in shape_gate


def test_a_blank_crop_does_not_pass_the_door_gates():
    import numpy as np

    provider = _door_provider()
    frame = np.zeros((300, 300, 3), dtype="uint8")

    results = provider.score_candidates(frame, [(50.0, 50.0, 250.0, 250.0)])

    assert results == []


def test_detail_reports_which_color_won_the_gate():
    from perception_framework.contracts.data_dictionary import MANDATORY_GATES

    provider = _door_provider()
    frame = _read_frame()

    results = provider.score_candidates(frame, [DOOR_BOX_ORIGINAL])

    color_gate = results[0].detail[MANDATORY_GATES]["color"]
    assert "winning_color" in color_gate
    assert isinstance(color_gate["candidates"], dict)
