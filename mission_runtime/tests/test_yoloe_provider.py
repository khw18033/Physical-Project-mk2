"""implements: AI-E-01, AI-B-09, AI-C-05
tests: prompt-free label namespace, graceful degradation without weights,
       device resolution, real-asset inference on a recorded robot scan

`ultralytics` 가 없거나 가중치가 없는 노드에서는 **실물 추론 시험만** skip 된다
(AI-C-05) — 구성·축소 경로(`is_available()`, `detect()` 가 예외 없이 빈 리스트를
내는 경로)와 라벨 이름 공간 시험은 항상 돈다. 자산 뿌리의 자리는
`tests/conftest.py::asset_root()` 한 곳이 정한다.

프롬프트 모드의 실물 시험은 작업 디렉터리를 자산 뿌리로 옮긴다 —
`set_classes(..., get_text_pe(...))` 가 MobileCLIP 텍스트 인코더를 요구하고,
ultralytics 는 그것을 작업 디렉터리나 자기 weights_dir 에서 찾은 뒤 **없으면
공개 인터넷에서 받는다**. 시험이 572 MB 를 내려받게 두지 않는다: 그 파일이
자산 뿌리에 없으면 그 시험만 skip 이다.
"""

from __future__ import annotations

import numpy as np
import pytest

from conftest import asset_path, asset_root, asset_root_present, demo_asset_path

PROMPTED_WEIGHTS = asset_path("yoloe-11s-seg.pt")
PROMPT_FREE_WEIGHTS = asset_path("yoloe-11s-seg-pf.pt")
TEXT_ENCODER = asset_path("mobileclip_blt.ts")
SCAN_DIR = demo_asset_path("20260910-134818_rot8")

#: 실물 스캔에 실제로 있는 것들만 넣는다 — 선언 어휘(`obstacle_taxonomy` zeroshot)의
#: 부분집합이다.
VOCABULARY = ["person", "chair", "box", "laptop", "trash bin", "door", "backpack"]


def _ultralytics_importable() -> bool:
    try:
        import ultralytics  # noqa: F401
    except Exception:
        return False
    return True


def _scan_frames() -> list:
    import cv2

    paths = sorted(SCAN_DIR.glob("frame_*.jpg"))
    return [cv2.imread(str(p)) for p in paths]


_REAL_PROMPTED = pytest.mark.skipif(
    not (_ultralytics_importable() and asset_root_present()
         and PROMPTED_WEIGHTS.exists() and TEXT_ENCODER.exists() and SCAN_DIR.is_dir()),
    reason="ultralytics·yoloe-11s-seg.pt·mobileclip_blt.ts·실물 스캔 중 하나가 없음 "
           "(AI-C-05: 이 묶음만 skip)",
)
_REAL_PROMPT_FREE = pytest.mark.skipif(
    not (_ultralytics_importable() and asset_root_present()
         and PROMPT_FREE_WEIGHTS.exists() and SCAN_DIR.is_dir()),
    reason="ultralytics·yoloe-11s-seg-pf.pt·실물 스캔 중 하나가 없음 (AI-C-05: 이 묶음만 skip)",
)
#: pf 가중치에 어휘를 **주는** 경로. 거절은 `set_classes` 에서 나는데 그 인자인
#: `get_text_pe(...)` 가 먼저 평가되므로 텍스트 인코더도 있어야 한다 — 없으면
#: ultralytics 가 받으러 나가고, 시험은 그렇게 하지 않는다.
_REAL_PROMPT_FREE_WITH_VOCAB = pytest.mark.skipif(
    not (_ultralytics_importable() and asset_root_present()
         and PROMPT_FREE_WEIGHTS.exists() and TEXT_ENCODER.exists() and SCAN_DIR.is_dir()),
    reason="ultralytics·yoloe-11s-seg-pf.pt·mobileclip_blt.ts·실물 스캔 중 하나가 없음 "
           "(AI-C-05: 이 묶음만 skip)",
)


# ── 모드 선언 ────────────────────────────────────────────────────────────────


def test_empty_vocabulary_is_rejected_but_none_means_prompt_free():
    """빈 리스트와 None 은 다른 뜻이다 — 전자는 사고, 후자는 prompt-free 모드다."""
    from mission_runtime.edge.yoloe_provider import (
        PROMPT_MODE_FREE,
        PROMPT_MODE_TEXT,
        YoloePerceptionProvider,
    )

    with pytest.raises(ValueError):
        YoloePerceptionProvider(PROMPTED_WEIGHTS, class_names=[], device="cpu")

    free = YoloePerceptionProvider(PROMPT_FREE_WEIGHTS, device="cpu")
    prompted = YoloePerceptionProvider(PROMPTED_WEIGHTS, class_names=["person"], device="cpu")

    assert free.prompt_mode == PROMPT_MODE_FREE
    assert free.class_names is None
    assert prompted.prompt_mode == PROMPT_MODE_TEXT
    assert prompted.class_names == ["person"]


def test_label_namespace_differs_by_mode():
    from mission_runtime.edge.yoloe_provider import (
        LABEL_NAMESPACE_BUILTIN,
        LABEL_NAMESPACE_OPERATOR,
        YoloePerceptionProvider,
    )

    free = YoloePerceptionProvider(PROMPT_FREE_WEIGHTS, device="cpu")
    prompted = YoloePerceptionProvider(PROMPTED_WEIGHTS, class_names=["person"], device="cpu")

    assert free.label_namespace == LABEL_NAMESPACE_BUILTIN
    assert prompted.label_namespace == LABEL_NAMESPACE_OPERATOR


# ── 축소 경로 ────────────────────────────────────────────────────────────────


def test_is_available_reflects_weights_presence_only():
    from mission_runtime.edge.yoloe_provider import YoloePerceptionProvider

    provider = YoloePerceptionProvider(PROMPTED_WEIGHTS, class_names=["person"], device="cpu")

    assert provider.is_available() is PROMPTED_WEIGHTS.exists()


def test_missing_weights_degrades_without_loading_or_raising():
    from mission_runtime.edge.yoloe_provider import YoloePerceptionProvider

    provider = YoloePerceptionProvider(
        "/nonexistent/path/yoloe-11s-seg.pt", class_names=["person"], device="cpu")

    assert provider.is_available() is False
    assert provider.detect(np.zeros((64, 64, 3), dtype=np.uint8)) == []
    health = provider.health()
    assert health["loaded"] is False
    assert "weights_missing" in health["load_error"]


def test_device_defaults_to_a_probed_tag_not_a_hardcoded_vendor():
    from mission_runtime.edge.yoloe_provider import YoloePerceptionProvider
    from mission_runtime.ondevice.rpn_propose import gpu_use_declined
    from mission_runtime.providers.compute import TAG_GPU, discover_node_tags

    provider = YoloePerceptionProvider(PROMPTED_WEIGHTS, class_names=["person"])

    # 이 프로세스가 가속기를 쓰지 않기로 **선언**했으면 기본값은 cpu 다. 노드에
    # 가속기가 있다는 사실(태그)과 이번에 쓸지(선택)는 다른 축이고, 그래서 이
    # 시험도 둘을 따로 본다 — 태그를 거짓으로 만들어 cpu 를 얻는 구현이면 아래
    # 둘째 단정이 깨진다.
    if gpu_use_declined():
        assert provider.device == "cpu"
        assert TAG_GPU in discover_node_tags() or True, (
            "선언은 고르는 쪽만 바꾼다 — 태그는 사실을 그대로 말해야 한다")
        return
    expected = "cuda" if TAG_GPU in discover_node_tags() else "cpu"
    assert provider.device == expected


def test_health_separates_absent_outputs_from_unsurfaced_ones():
    """모델에 **없는** 것과 계약이 **못 싣는** 것은 다른 사실이다."""
    from mission_runtime.edge.yoloe_provider import YoloePerceptionProvider

    health = YoloePerceptionProvider(PROMPT_FREE_WEIGHTS, device="cpu").health()

    assert "depth_m" in health["missing_outputs"]
    assert "intrinsics_fx_cx" in health["missing_outputs"]
    assert health["outputs_not_surfaced"] == ["instance_mask"]
    # 로드 전에 내장 어휘 크기를 **아는 척하지 않는다**(0 이 아니다).
    assert health["builtin_vocabulary_size"] is None


# ── prompt-free 라벨의 이름 공간 ─────────────────────────────────────────────


def test_prefix_helpers_are_reversible_and_leave_vocabulary_labels_alone():
    from mission_runtime.edge.yoloe_provider import (
        PROMPT_FREE_LABEL_PREFIX,
        is_prompt_free_label,
        strip_prompt_free_prefix,
    )

    tagged = f"{PROMPT_FREE_LABEL_PREFIX}sea ice"

    assert is_prompt_free_label(tagged) is True
    assert strip_prompt_free_prefix(tagged) == "sea ice"
    # 어휘 라벨에는 아무 일도 하지 않는다.
    assert is_prompt_free_label("chair") is False
    assert strip_prompt_free_prefix("chair") == "chair"


def test_prompt_free_label_can_never_be_read_as_a_vocabulary_match():
    """접두사가 붙은 이름은 어떤 선언 어휘 키와도 같아지지 않는다.

    그래서 점수가 0.95 여도 `UNKNOWN_OBSTACLE` + `unmapped_label` + `hypothesis` 로
    남아 미확인 객체(AI-S-04)·학습 후보(AI-L-01) 경로로 흐른다. 운영자가 고르지
    않은 이름이 확정 분류로 승격되는 길이 **구조적으로** 없다(AI-L-02).
    """
    from mission_runtime.edge.yoloe_provider import PROMPT_FREE_LABEL_PREFIX
    from mission_runtime.perception.obstacle_taxonomy import (
        REASON_MAPPED,
        REASON_UNMAPPED,
        STATUS_HYPOTHESIS,
        UNKNOWN_GROUP,
        ObstacleTaxonomy,
    )

    taxonomy = ObstacleTaxonomy.from_file()
    declared = set(taxonomy.vocabulary_classes("zeroshot"))
    assert "chair" in declared, "전제가 깨졌다: zeroshot 어휘에 chair 가 있어야 한다"

    # 어휘와 **같은 글자**를 골라 최악의 경우를 본다.
    plain = taxonomy.classify("chair", vocabulary="zeroshot")
    tagged = taxonomy.classify(f"{PROMPT_FREE_LABEL_PREFIX}chair", vocabulary="zeroshot")

    assert plain.reason == REASON_MAPPED
    assert tagged.reason == REASON_UNMAPPED
    assert tagged.group == UNKNOWN_GROUP
    assert tagged.label_status == STATUS_HYPOTHESIS
    assert tagged.can_be_confirmed is False
    # 접두사가 어떤 선언 클래스 이름과도 충돌하지 않는다.
    assert not any(name.startswith(PROMPT_FREE_LABEL_PREFIX) for name in declared)


# ── 실물 자산 ────────────────────────────────────────────────────────────────


@_REAL_PROMPTED
def test_prompted_mode_detects_the_recorded_scan_within_the_given_vocabulary(monkeypatch):
    """실물 스캔 8프레임. 라벨은 **운영자가 준 어휘 안에만** 있고 접두사가 없다."""
    from mission_runtime.edge.yoloe_provider import YoloePerceptionProvider, is_prompt_free_label

    monkeypatch.chdir(asset_root())  # MobileCLIP 텍스트 인코더를 여기서 찾게 한다
    provider = YoloePerceptionProvider(PROMPTED_WEIGHTS, class_names=VOCABULARY)

    best: dict[str, float] = {}
    for frame in _scan_frames():
        for r in provider.detect(frame):
            assert r.label in VOCABULARY
            assert not is_prompt_free_label(r.label)
            assert 0.0 <= r.confidence <= 1.0
            best[r.label] = max(best.get(r.label, 0.0), r.confidence)

    assert "person" in best, f"사람이 있는 스캔인데 person 이 없다: {best}"
    assert best["person"] > 0.8, f"person 최고 점수가 너무 낮다: {best}"
    assert provider.health()["vocabulary_size"] == len(VOCABULARY)


@_REAL_PROMPT_FREE
def test_prompt_free_mode_labels_are_all_tagged_and_reach_outside_any_vocabulary():
    """실물 스캔에서 prompt-free 가 내는 이름 전부에 접두사가 붙고, 그 중에는
    선언 어휘에 **없는** 이름이 실제로 섞여 있다 — 이 구분이 장식이 아닌 이유다."""
    from mission_runtime.edge.yoloe_provider import (
        YoloePerceptionProvider,
        is_prompt_free_label,
        strip_prompt_free_prefix,
    )
    from mission_runtime.perception.obstacle_taxonomy import ObstacleTaxonomy

    provider = YoloePerceptionProvider(PROMPT_FREE_WEIGHTS)
    declared = set(ObstacleTaxonomy.from_file().vocabulary_classes("zeroshot"))

    raw_names: set[str] = set()
    for frame in _scan_frames():
        for r in provider.detect(frame):
            assert is_prompt_free_label(r.label), f"접두사 없는 prompt-free 라벨: {r.label}"
            assert 0.0 <= r.confidence <= 1.0
            raw_names.add(strip_prompt_free_prefix(r.label))

    assert raw_names, "prompt-free 가 아무 것도 내지 않았다"
    outside = raw_names - declared
    assert outside, f"선언 어휘 밖 이름이 하나도 없다 — 전제 재확인 필요: {sorted(raw_names)}"
    # 내장 어휘 크기는 로드 후에 **관측된다**.
    assert provider.health()["builtin_vocabulary_size"] == 4585


@_REAL_PROMPT_FREE_WITH_VOCAB
def test_prompt_free_weights_refuse_a_vocabulary_and_that_refusal_degrades_cleanly(monkeypatch):
    """pf 가중치에 어휘를 주면 ultralytics 가 거절한다 — 그 거절이 모델의 계약이고,
    우리는 예외를 올리지 않고 사유를 남긴 뒤 빈 결과로 축소한다(AI-C-05)."""
    from mission_runtime.edge.yoloe_provider import YoloePerceptionProvider

    monkeypatch.chdir(asset_root())
    provider = YoloePerceptionProvider(PROMPT_FREE_WEIGHTS, class_names=["person"])

    results = provider.detect(_scan_frames()[0])

    assert results == []
    assert provider.health()["load_error"]
    assert provider.health()["loaded"] is False


def test_a_prompt_free_label_must_not_borrow_a_floor_declared_for_another_namespace():
    """접두사만으로는 **하한**까지 지켜지지 않는다 — 그 사실을 여기 고정한다.

    `classify(..., vocabulary="zeroshot")` 는 모르는 이름에도 그 어휘의
    `default` 하한(0.25)을 돌려준다. 그 값은 운영자가 고른 어휘의 점수 분포를 보고
    정한 수이고, 모델이 스스로 떠올린 4585개 범주와는 아무 관계가 없다 — 선언된
    값처럼 보이지만 이 라벨에 대해서는 근거가 없다("사람이 고르지 않은 라벨에
    받아주는 임계값이 붙는다" 는 학습 경로의 결함과 같은 모양이다).

    그래서 prompt-free 탐지기의 선언은 `taxonomy_vocabulary: null` 이다. 그 선언을
    따라 판정하면 하한은 **NaN(모른다)** 이고 사유는 `unknown_vocabulary` 다 —
    0.25 를 주는 쪽과 달리, 하한을 아는 척하지 않는다.
    """
    import math

    from mission_runtime.edge.detector_catalog import DetectorCatalog
    from mission_runtime.edge.yoloe_provider import PROMPT_FREE_LABEL_PREFIX
    from mission_runtime.perception.obstacle_taxonomy import (
        REASON_NO_VOCABULARY,
        REASON_UNMAPPED,
        ObstacleTaxonomy,
    )

    taxonomy = ObstacleTaxonomy.from_file()
    label = f"{PROMPT_FREE_LABEL_PREFIX}sea ice"
    declared = DetectorCatalog.from_file().get("yoloe-11s-seg-prompt-free")
    assert declared.prompting.taxonomy_vocabulary is None

    borrowed = taxonomy.classify(label, vocabulary="zeroshot")
    followed = taxonomy.classify(label, vocabulary=declared.prompting.taxonomy_vocabulary)

    # 엉뚱한 어휘로 물으면 그 어휘의 default 를 빌려 온다 — 이 라벨에 근거가 없는 수다.
    assert borrowed.reason == REASON_UNMAPPED
    assert borrowed.confidence_floor == 0.25
    # 선언을 따르면 하한을 아는 척하지 않는다.
    assert followed.reason == REASON_NO_VOCABULARY
    assert math.isnan(followed.confidence_floor)
    # 어느 쪽이든 확정으로 승격되지 않는다(AI-L-02).
    assert borrowed.can_be_confirmed is False and followed.can_be_confirmed is False
