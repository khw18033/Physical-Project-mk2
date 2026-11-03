"""implements: AI-B-15, AI-C-19, AI-C-05, AI-S-04
covers: 추천이 **발령이 아니라는 것**과, 근거 없는 추천을 하지 않는다는 것.
"""

from __future__ import annotations

import pytest

from mission_runtime.planning.mission_recommendation import (
    BLOCKED_MISSING_CAPABILITY,
    BLOCKED_NO_TRIGGER,
    RECOMMENDED,
    TRIGGER_ALWAYS,
    TRIGGER_DEPLOYMENT_PENDING,
    TRIGGER_IDLE_ACCELERATOR,
    TRIGGER_RISK_ELEVATED,
    TRIGGER_STALE_CALIBRATION,
    TRIGGER_UNRESOLVED_UNKNOWN,
    MissionCandidate,
    MissionRecommender,
    MissionTemplate,
    SituationSnapshot,
)

VISION = frozenset({"media.video_input", "perception.detect"})


def _recommender() -> MissionRecommender:
    recommender = MissionRecommender()
    recommender.register(MissionTemplate(
        "reobserve_unknown", "미확인 객체 재관측", "OBSERVE_REGION",
        VISION, frozenset({TRIGGER_UNRESOLVED_UNKNOWN}), priority=10))
    recommender.register(MissionTemplate(
        "weigh_object", "대상 무게 추정", "MEASURE_OBJECT",
        frozenset({"analysis.weight"}), frozenset({TRIGGER_UNRESOLVED_UNKNOWN}), priority=20))
    recommender.register(MissionTemplate(
        "recalibrate", "카메라 재보정", "CALIBRATE_CAMERA",
        frozenset({"media.video_input"}), frozenset({TRIGGER_STALE_CALIBRATION}), priority=30))
    return recommender


def test_a_mission_without_triggering_evidence_is_not_recommended():
    """상시 추천은 화면을 채우지만 운영자의 신뢰를 깎는다."""
    situation = SituationSnapshot(available_capabilities=VISION)

    by_kind = {c.mission_kind: c for c in _recommender().recommend(situation)}

    assert by_kind["reobserve_unknown"].recommended is False
    assert by_kind["reobserve_unknown"].reason == BLOCKED_NO_TRIGGER


def test_evidence_turns_a_mission_into_a_recommendation_with_its_subjects():
    situation = SituationSnapshot(
        available_capabilities=VISION,
        unresolved_unknown_object_ids=("obj-7", "obj-9"),
    )

    candidate = next(c for c in _recommender().recommend(situation)
                     if c.mission_kind == "reobserve_unknown")

    assert candidate.recommended is True
    assert candidate.reason == RECOMMENDED
    assert candidate.matched_triggers == (TRIGGER_UNRESOLVED_UNKNOWN,)
    # 무엇에 대한 임무인지 — 근거에서 끌어온다. 지어내지 않는다.
    assert candidate.subjects == ("obj-7", "obj-9")


def test_a_blocked_mission_says_which_capability_is_missing():
    """막힌 목록이 다음에 붙일 기능의 우선순위이고 외부 요청의 재료다(AI-B-13)."""
    situation = SituationSnapshot(
        available_capabilities=VISION,
        unresolved_unknown_object_ids=("obj-7",),
    )

    candidate = next(c for c in _recommender().recommend(situation)
                     if c.mission_kind == "weigh_object")

    assert candidate.recommended is False
    assert candidate.reason == BLOCKED_MISSING_CAPABILITY
    assert candidate.missing_capabilities == ("analysis.weight",)
    # 근거는 있었다는 사실도 남는다 — "기능만 없다"와 "할 이유가 없다"는 다르다.
    assert candidate.matched_triggers == (TRIGGER_UNRESOLVED_UNKNOWN,)


def test_recommended_candidates_come_first_and_the_order_is_deterministic():
    """같은 입력에 다른 순서가 나오면 화면이 흔들린다."""
    situation = SituationSnapshot(
        available_capabilities=VISION,
        unresolved_unknown_object_ids=("obj-7",),
        stale_calibration_camera_ids=("cam-1",),
    )

    first = [c.mission_kind for c in _recommender().recommend(situation)]
    second = [c.mission_kind for c in _recommender().recommend(situation)]

    assert first == second
    assert first[0] == "reobserve_unknown"      # 추천 + priority 10
    assert first[1] == "recalibrate"            # 추천 + priority 30
    assert first[-1] == "weigh_object"          # 막힘은 뒤로


@pytest.mark.parametrize("field, value, trigger", [
    ("unresolved_unknown_object_ids", ("o1",), TRIGGER_UNRESOLVED_UNKNOWN),
    ("idle_accelerators", ("npu-3",), TRIGGER_IDLE_ACCELERATOR),
    ("pending_external_request_ids", ("SDI-1",), TRIGGER_DEPLOYMENT_PENDING),
    ("stale_calibration_camera_ids", ("cam-1",), TRIGGER_STALE_CALIBRATION),
])
def test_each_situation_field_raises_its_own_trigger(field, value, trigger):
    situation = SituationSnapshot(**{field: value})

    assert trigger in situation.triggers()


@pytest.mark.parametrize("level, expected", [
    ("alert", True), ("watch", True), ("normal", False), (None, False),
])
def test_risk_triggers_only_at_elevated_levels_and_we_do_not_rejudge_it(level, expected):
    """위험 상태는 위험 분석이 낸 값을 그대로 받는다 — 다시 판정하면 두 주인이 생긴다."""
    situation = SituationSnapshot(risk_level=level)

    assert (TRIGGER_RISK_ELEVATED in situation.triggers()) is expected


def test_an_always_applicable_mission_needs_no_evidence():
    recommender = MissionRecommender()
    recommender.register(MissionTemplate(
        "patrol", "정기 순찰", "PATROL_ROUTE", VISION, frozenset({TRIGGER_ALWAYS})))

    candidate = recommender.recommend(SituationSnapshot(available_capabilities=VISION))[0]

    assert candidate.recommended is True


def test_an_empty_deployment_recommends_nothing_without_failing():
    """임무 목록이 없는 배치도 정상이다(AI-C-05)."""
    assert MissionRecommender().recommend(SituationSnapshot()) == ()


def test_an_unknown_trigger_token_is_refused_at_declaration_time():
    """나중에 조용히 안 걸리는 대신 등록할 때 막는다."""
    with pytest.raises(ValueError):
        MissionTemplate("x", "t", "G", frozenset(), frozenset({"made_up_trigger"}))


def test_registering_the_same_kind_twice_replaces_it():
    recommender = MissionRecommender()
    recommender.register(MissionTemplate("m", "첫 제목", "G", triggers=frozenset({TRIGGER_ALWAYS})))
    recommender.register(MissionTemplate("m", "바뀐 제목", "G", triggers=frozenset({TRIGGER_ALWAYS})))

    assert [c.title for c in recommender.recommend(SituationSnapshot())] == ["바뀐 제목"]


def test_this_module_cannot_issue_a_mission():
    """AI-C-19 — 임무를 띄우는 것은 승인을 거쳐 백엔드가 한다. 여기에 그 수단이 없다.

    자동 실행을 붙이자는 요구가 오면 그것은 요구사항 변경이지 이 모듈의 확장이 아니다.
    """
    from mission_runtime.planning import mission_recommendation

    functions = [
        name for name in dir(mission_recommendation)
        if not name.startswith("_") and name.islower()
        and callable(getattr(mission_recommendation, name))
    ]
    assert not [
        name for name in functions
        if any(verb in name for verb in ("execute", "issue", "dispatch", "start", "publish",
                                         "command", "launch", "approve"))
    ]
    # 후보 자료형에도 실행 수단이 없다.
    assert not [name for name in dir(MissionCandidate) if name.startswith("execute")]
