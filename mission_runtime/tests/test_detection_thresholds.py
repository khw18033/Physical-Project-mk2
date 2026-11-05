"""implements: AI-S-08, AI-B-01, AI-S-04, AI-C-15, AI-L-03
covers: 세부 임계값이 **선언 데이터**이고, 그 선언이 값만이 아니라 적용 대상·출처·
        측정 여부를 함께 들고 다니는가. 그리고 하한을 말할 근거가 없는 상태가
        0 도 미달도 아닌 **세 번째 상태**로 끝까지 남는가 — 그 상태를 거름 조건으로
        쓰면 이름 없는 관측이 사라져 AI-S-04 가 막는 동작이 된다.
"""

import json
import math

import pytest

from mission_runtime.perception.detection_thresholds import (
    BASIS_AMBIGUOUS,
    BASIS_DECLARED,
    BASIS_NO_DECLARATION,
    BASIS_OPERATOR_EDIT,
    DetectionThresholds,
    OperatorValue,
    ThresholdDeclarationError,
    operator_values_from_overlay,
)
from mission_runtime.perception.obstacle_taxonomy import (
    FLOOR_ABOVE,
    FLOOR_BASIS_CLASS,
    FLOOR_BASIS_NONE,
    FLOOR_BASIS_VOCABULARY_DEFAULT,
    FLOOR_BELOW,
    FLOOR_NO_BASIS,
    ObstacleTaxonomy,
)

PROMPT_FREE_FLOOR = "label_namespace.model_builtin_vocabulary.label_score_floor"
PROMPT_FREE_CONF = "detector.yoloe-11s-seg-prompt-free.score_floor"
BUILTIN_NAMESPACE = "model_builtin_vocabulary"


@pytest.fixture()
def declared() -> DetectionThresholds:
    return DetectionThresholds.from_file()


@pytest.fixture()
def tax() -> ObstacleTaxonomy:
    return ObstacleTaxonomy.from_file()


def _row(**over) -> dict:
    body = {
        "threshold_id": "t1", "parameter": "conf",
        "applies_to": {"detector_id": "d1"},
        "value": 0.3, "unit": "detector_score", "bounds": [0.0, 1.0],
        "provenance": {"source": "손으로 적었다", "measured": False},
    }
    body.update(over)
    return body


def _catalog(*rows) -> DetectionThresholds:
    return DetectionThresholds({"thresholds": list(rows)})


# ---------------------------------------------------------------------------
# 1. 선언은 값만 옮긴 것이 아니다
# ---------------------------------------------------------------------------


def test_every_declared_threshold_says_where_its_number_came_from(declared):
    """출처 없는 설정값은 **주석이 달린 코드 상수보다 나쁘다.** 그래서 출처를
    적지 않은 선언은 적재 자체가 거절된다."""
    for row in declared.all():
        assert row.provenance.source, row.threshold_id

    with pytest.raises(ThresholdDeclarationError, match="source"):
        _catalog(_row(provenance={"measured": False}))


def test_a_declaration_must_say_whether_the_number_was_measured_or_guessed(declared):
    """AI-S-08: 선언값과 실측값은 같은 칸을 쓰지 않는다. 그래서 `measured` 는
    비워 둘 수 없고, 재지 않은 값에 오차를 붙이는 것도 거절된다 — 붙이면 그 오차가
    실측처럼 읽힌다(`depth_calibration.example.json` 의 `accuracy_cm: null` 규칙)."""
    with pytest.raises(ThresholdDeclarationError, match="measured"):
        _catalog(_row(provenance={"source": "어딘가"}))

    with pytest.raises(ThresholdDeclarationError, match="samples/accuracy"):
        _catalog(_row(provenance={"source": "어딘가", "measured": False,
                                  "accuracy": 0.0}))

    # 재지 않았으면 그 키가 **응답에 없다**. 0 으로 채우지 않는다.
    guessed = _catalog(_row()).get("t1").provenance.as_dict()
    assert "accuracy" not in guessed and "samples" not in guessed
    assert guessed["measured"] is False


def test_a_value_cannot_be_absent_and_measured_at_once():
    with pytest.raises(ThresholdDeclarationError, match="measured=true"):
        _catalog(_row(value=None, provenance={"source": "어딘가", "measured": True}))


def test_the_same_fact_cannot_have_two_owners():
    """같은 파라미터·같은 적용 대상을 둘이 선언하면 운영 중에 하나를 임의로 골라야
    한다. 그 선택이 틀리는 날 운영자가 고친 쪽과 쓰이는 쪽이 달라진다."""
    with pytest.raises(ThresholdDeclarationError, match="중복 선언"):
        _catalog(_row(threshold_id="a"), _row(threshold_id="b"))

    with pytest.raises(ThresholdDeclarationError, match="duplicate threshold_id"):
        _catalog(_row(), _row(applies_to={"detector_id": "d2"}))


def test_an_unknown_scope_axis_is_refused_rather_than_silently_dropped():
    """모르는 축을 버리면 운영자가 적은 한정이 사라지고, 그 임계값은 자기가 적지
    않은 대상에까지 적용된다."""
    with pytest.raises(ThresholdDeclarationError, match="모르는 축"):
        _catalog(_row(applies_to={"detector_id": "d1", "device_model": "go1"}))


def test_a_value_outside_its_own_bounds_is_refused():
    with pytest.raises(ThresholdDeclarationError, match="bounds"):
        _catalog(_row(value=1.5))


# ---------------------------------------------------------------------------
# 2. 세 번째 상태 — 미측정 ≠ 0 ≠ 미달
# ---------------------------------------------------------------------------


def test_a_threshold_nobody_declared_is_a_third_state_and_not_zero(declared):
    """프롬프트프리 라벨의 하한이 그 자리다. 선언 파일에 항목은 **있고** 값이 없다 —
    그래서 소비자가 '여기 하한이 없다'를 조용히 모르고 지나가지 않는다."""
    row = declared.get(PROMPT_FREE_FLOOR)
    assert row.value is None and row.declared is False

    resolved = declared.resolve("label_score_floor",
                                label_namespace=BUILTIN_NAMESPACE)
    assert resolved.basis == BASIS_NO_DECLARATION
    assert resolved.value is None          # 0.0 이 아니다
    assert resolved.known is False
    # 그래도 **어느 선언이 비어 있는지**는 가리킨다 — 채울 자리를 알려 주는 것이
    # 이 상태의 쓸모다.
    assert resolved.declaration.threshold_id == PROMPT_FREE_FLOOR
    assert resolved.as_dict()["provenance"]["measured"] is False


def test_a_scoped_declaration_does_not_apply_when_the_asker_omits_that_axis(declared):
    """**이 파일이 생긴 원인이 이 규칙이다.** 축에 값을 적은 선언은 묻는 쪽이 그
    축을 함께 줘야 적용된다 — 그렇지 않으면 어휘를 모른 채 어휘 전용 하한을 빌려
    오고, 빌려 온 수가 선언된 하한처럼 보인다."""
    assert declared.resolve("label_score_floor").basis == BASIS_NO_DECLARATION
    assert declared.resolve("label_score_floor",
                            label_namespace="operator_vocabulary").declaration \
        .threshold_id == "label_namespace.operator_vocabulary.label_score_floor"


def test_a_narrower_declaration_wins_and_a_tie_refuses_to_choose():
    catalog = _catalog(
        _row(threshold_id="wide", applies_to={}, value=0.1),
        _row(threshold_id="narrow", applies_to={"detector_id": "d1"}, value=0.4))
    assert catalog.resolve("conf", detector_id="d1").value == 0.4
    assert catalog.resolve("conf", detector_id="other").value == 0.1

    # 같은 좁기의 두 선언이 같은 파라미터를 말하면 **고르지 않는다.** 위험도가
    # 비슷하면 1 위를 고르지 않는 것과 같은 규칙이다 — 임의로 고르면 운영자가 고친
    # 쪽과 쓰이는 쪽이 달라질 수 있다.
    same = _catalog(
        _row(threshold_id="by-class", applies_to={"class_name": "box"}, value=0.4),
        _row(threshold_id="by-namespace-and-kind",
             applies_to={"label_namespace": "operator_vocabulary",
                         "capability_kind": "perception.detect_ovd"}, value=0.5))
    verdict = same.resolve("conf", class_name="box",
                           label_namespace="operator_vocabulary",
                           capability_kind="perception.detect_ovd")
    assert verdict.basis == BASIS_AMBIGUOUS
    assert verdict.value is None
    assert set(verdict.conflicting) == {"by-class", "by-namespace-and-kind"}


# ---------------------------------------------------------------------------
# 3. 운영자 수정은 선언을 덮지 않는다
# ---------------------------------------------------------------------------


def test_the_declared_value_and_the_operator_value_never_share_a_cell(declared):
    """AI-L-03: 원래 선언과 사람이 고친 값이 끝까지 구분되어야 어긋남과 수정 이력을
    설명할 수 있다."""
    edits = {PROMPT_FREE_CONF: OperatorValue(0.4, "jny", "현장이 너무 시끄럽다", 1.0)}
    resolved = declared.resolve("conf", detector_id="yoloe-11s-seg-prompt-free",
                                operator_values=edits)

    assert resolved.basis == BASIS_OPERATOR_EDIT
    assert resolved.value == 0.4
    assert resolved.declared_value == 0.05          # 선언은 그대로다
    assert resolved.operator_value.actor == "jny"
    body = resolved.as_dict()
    assert body["declared_value"] == 0.05 and body["operator_value"]["value"] == 0.4

    # 수정이 없으면 선언이 쓰인다.
    plain = declared.resolve("conf", detector_id="yoloe-11s-seg-prompt-free")
    assert (plain.basis, plain.value) == (BASIS_DECLARED, 0.05)


def test_an_operator_value_outside_the_declared_bounds_is_not_used(declared):
    """선언이 적은 범위가 운영자 수정에도 걸린다 — 걸리지 않으면 장부 한 줄로
    모든 탐지를 끌 수 있다."""
    edits = {PROMPT_FREE_CONF: OperatorValue(9.0, "jny", "오타", 1.0)}
    resolved = declared.resolve("conf", detector_id="yoloe-11s-seg-prompt-free",
                                operator_values=edits)
    assert resolved.basis == BASIS_DECLARED and resolved.value == 0.05


def test_a_malformed_ledger_entry_does_not_empty_the_whole_resolution():
    """장부는 append-only 라 옛 형식 항목이 남아 있을 수 있다. 하나 때문에 전체
    해소가 멈추면 운영 화면이 통째로 빈다(AI-C-05)."""
    values = operator_values_from_overlay({
        "good": {"value": 0.3, "actor": "a", "reason": "r", "edited_at": 2.0},
        "bad": {"actor": "a"},
        "worse": {"value": "자연수가 아니다"},
    })
    assert set(values) == {"good"}


# ---------------------------------------------------------------------------
# 4. 선언이 실제 조립 규약과 맞물리는가
# ---------------------------------------------------------------------------


def test_every_detector_threshold_names_a_parameter_that_reaches_the_provider(declared):
    """선언한 이름이 `construction.param_kwargs` 에 없으면 그 값은 생성자에 도달하지
    않는다 — 운영자는 고친 줄 알고 아무것도 바뀌지 않는다. 두 선언 파일이 **같은
    어휘**를 쓰는지 여기서 고정한다."""
    from mission_runtime.edge.detector_catalog import DetectorCatalog

    catalog = DetectorCatalog.from_file()
    for row in declared.all():
        detector_id = row.applies_to.detector_id
        if detector_id is None:
            continue
        assert detector_id in catalog.detector_ids, row.threshold_id
        assert row.parameter in catalog.get(detector_id).accepted_params, row.threshold_id


def test_params_for_leaves_out_what_the_detector_does_not_take(declared):
    params, basis = declared.params_for("yoloe-11s-seg-prompt-free",
                                        accepted=("conf", "device"))
    assert params == {"conf": 0.05}
    # 값이 없는 파라미터는 **사전에 넣지 않는다** — 넣지 않으면 provider 자기
    # 기본값이 쓰이고, 그 사실이 근거에 남는다.
    assert basis["device"].basis == BASIS_NO_DECLARATION
    assert basis["conf"].basis == BASIS_DECLARED

    narrowed, _ = declared.params_for("grounding-dino-tiny", accepted=("conf",))
    assert narrowed == {"conf": 0.15}       # text_conf 는 받지 않기로 했으니 없다


def test_an_absent_declaration_file_is_a_normal_deployment():
    """선언이 없는 배치는 오류가 아니다(AI-C-05) — 모든 해소가 세 번째 상태다."""
    empty = DetectionThresholds.empty()
    assert empty.threshold_ids == ()
    assert empty.resolve("conf", detector_id="whatever").basis == BASIS_NO_DECLARATION
    assert empty.params_for("whatever", accepted=("conf",))[0] == {}


# ---------------------------------------------------------------------------
# 5. 어휘 하한의 세 상태 (perception/obstacle_taxonomy.py)
# ---------------------------------------------------------------------------


def test_a_label_floor_carries_its_basis_so_two_identical_numbers_are_not_confused(tax):
    """`0.25` 가 두 뜻을 가질 수 있다 — 그 클래스에 선언된 값이거나, 아무 말도
    없어 어휘 기본값이 된 값이거나. 값만 보면 둘이 같아 보인다."""
    exact = tax.score_floor("box", vocabulary="zeroshot")
    fallback = tax.score_floor("보지 못한 이름", vocabulary="zeroshot")

    assert (exact.basis, exact.value) == (FLOOR_BASIS_CLASS, 0.12)
    assert (fallback.basis, fallback.value) == (FLOOR_BASIS_VOCABULARY_DEFAULT, 0.25)
    # 둘 다 선언에서 왔으므로 출처가 붙는다.
    assert exact.source and fallback.source
    assert exact.measured is False          # 굳힌 것과 재는 것은 다르다


def test_a_vocabulary_that_declares_no_default_gets_no_invented_floor():
    """옛 구현은 여기서 **코드에 박힌 0.25** 를 돌려줬다 — 선언 파일이 아무 말도
    하지 않았는데 선언된 하한처럼 보이는 수가 나오는 자리였다."""
    bare = ObstacleTaxonomy({"vocabularies": {"bare": {"label_status": "hypothesis",
                                                       "class_conf": {}}}})
    floor = bare.score_floor("chair", vocabulary="bare")
    assert floor.basis == FLOOR_BASIS_NONE
    assert math.isnan(floor.value)
    assert floor.as_dict()["value"] is None          # 0.0 이 아니다
    assert bare.floor_state("chair", 0.99, vocabulary="bare") == FLOOR_NO_BASIS


def test_a_prompt_free_label_does_not_borrow_the_operator_vocabularys_floor(tax):
    """선언을 따르면 빌리지 않는다. 접두사를 taxonomy 가 들여다보는 것이 아니라
    **이름 공간 선언**으로 가른다 — 접두사를 여기서 알면 새 탐지기가 코드 변경이
    된다(원칙 #1·#7)."""
    label = "promptfree:sea ice"

    borrowed = tax.score_floor(label, vocabulary="zeroshot")
    followed = tax.score_floor(label, vocabulary="zeroshot",
                               label_namespace=BUILTIN_NAMESPACE)

    assert borrowed.basis == FLOOR_BASIS_VOCABULARY_DEFAULT     # 묻는 쪽이 틀린 경우
    assert followed.basis == FLOOR_BASIS_NONE
    assert math.isnan(followed.value)
    assert followed.state(0.99) == FLOOR_NO_BASIS
    # 어휘가 자기 이름 공간을 선언하고 있어야 이 판정이 선다.
    assert tax.label_namespace_of("zeroshot") == "operator_vocabulary"


def test_the_floor_has_three_states_and_no_basis_is_not_a_pass(tax):
    assert tax.floor_state("box", 0.3, vocabulary="zeroshot") == FLOOR_ABOVE
    assert tax.floor_state("box", 0.01, vocabulary="zeroshot") == FLOOR_BELOW
    assert tax.floor_state("box", 0.99, vocabulary="어디서온어휘") == FLOOR_NO_BASIS

    # 참·거짓만 묻는 겉면에서 "모른다" 는 참이 아니다 — 참으로 주면 미검증 라벨이
    # 확정처럼 통과한다(AI-L-02).
    assert tax.passes_floor("box", 0.3, vocabulary="zeroshot") is True
    assert tax.passes_floor("box", 0.99, vocabulary="어디서온어휘") is False
    assert tax.passes_floor("box", 0.01, vocabulary="zeroshot") is False


def test_the_verdict_carries_the_floor_basis_too(tax):
    assert tax.classify("box", vocabulary="zeroshot").confidence_floor_basis \
        == FLOOR_BASIS_CLASS
    assert tax.classify("chair", vocabulary="없는어휘").confidence_floor_basis \
        == FLOOR_BASIS_NONE
    assert tax.classify("promptfree:sea ice", vocabulary="zeroshot",
                        label_namespace=BUILTIN_NAMESPACE).confidence_floor_basis \
        == FLOOR_BASIS_NONE


# ---------------------------------------------------------------------------
# 6. **하한이 없다는 것이 거름 조건이 아니다** (AI-S-04)
# ---------------------------------------------------------------------------


def test_a_label_with_no_declared_floor_still_becomes_evidence(tax):
    """AI-S-04: "기존 클래스에 강제 매핑하지 않고 미확인 상태의 지속 객체로
    유지해야 한다." 하한을 말할 근거가 없다고 그 관측을 버리면 미확인 객체 경로와
    학습 후보 경로가 함께 사라진다 — 그래서 근거 생성기는 하한을 **싣고 거르지
    않는다**."""
    from mission_runtime.perception.obstacle_evidence import (
        Detection,
        ObstacleEvidenceBuilder,
    )

    builder = ObstacleEvidenceBuilder(tax)
    detections = [
        Detection("promptfree:sea ice", 0.61, (10, 10, 50, 50), "yoloe-pf"),
        Detection("box", 0.01, (60, 10, 90, 50), "yolo-world"),       # 하한 미달
        Detection("person", 0.9, (100, 10, 140, 50), "yolo-world"),
    ]

    evidence = builder.build(frame_ref="f1", rotation_deg=0.0, detections=detections)

    assert len(evidence) == 3, "하한으로 거른 것이 없어야 한다"
    assert {e.class_name for e in evidence} == {"promptfree:sea ice", "box", "person"}
    # 이름을 모르는 것은 **모르는 자리**에 남는다(강제 매핑이 아니다).
    unknown = next(e for e in evidence if e.class_name.startswith("promptfree:"))
    assert unknown.group == "UNKNOWN_OBSTACLE" and unknown.label_status == "hypothesis"

    # 하한은 **근거로 실린다** — 거르는 대신 세 상태가 레코드에 남아 근거 충분도
    # (AI-S-03)를 세는 쪽이 읽는다.
    states = {e.class_name: e.score_floor_state for e in evidence}
    assert states["box"] == FLOOR_BELOW
    assert states["person"] == FLOOR_ABOVE


def test_a_detection_that_declares_its_namespace_does_not_borrow_the_floor(tax):
    """탐지기 선언을 따라 `label_namespace` 를 적으면 어휘 하한을 빌리지 않는다 —
    그것이 이 작업이 고친 결함이다. 그래도 **버려지지 않는다**(AI-S-04)."""
    from mission_runtime.perception.obstacle_evidence import (
        Detection,
        ObstacleEvidenceBuilder,
    )

    builder = ObstacleEvidenceBuilder(tax)
    borrowed, followed = builder.build(frame_ref="f1", rotation_deg=0.0, detections=[
        Detection("promptfree:sea ice", 0.61, (0, 0, 9, 9), "yoloe-pf"),
        Detection("promptfree:sea ice", 0.61, (0, 0, 9, 9), "yoloe-pf",
                  label_namespace=BUILTIN_NAMESPACE),
    ])

    assert borrowed.score_floor == 0.25          # 묻는 쪽이 이름 공간을 안 적었다
    assert borrowed.score_floor_basis == FLOOR_BASIS_VOCABULARY_DEFAULT
    assert followed.score_floor is None          # 0.0 이 아니다
    assert followed.score_floor_basis == FLOOR_BASIS_NONE
    assert followed.score_floor_state == FLOOR_NO_BASIS
    # 둘 다 근거로 남는다 — 어느 쪽도 응답에서 빠지지 않는다.
    assert borrowed.class_name == followed.class_name == "promptfree:sea ice"


def test_the_shipped_declaration_file_loads_and_stays_json(declared):
    """선언이 코드가 아니라 데이터임을 고정한다 — 새 임계값은 이 파일 한 항목이다."""
    from mission_runtime.perception.detection_thresholds import (
        DEFAULT_THRESHOLDS_PATH,
    )

    raw = json.loads(DEFAULT_THRESHOLDS_PATH.read_text(encoding="utf-8"))
    assert len(raw["thresholds"]) == len(declared.threshold_ids)
    assert PROMPT_FREE_CONF in declared.threshold_ids
    # 코드 상수에서 옮겨 온 사실이 출처에 남아 있다.
    assert "DEFAULT_CONF" in declared.get(PROMPT_FREE_CONF).provenance.source
