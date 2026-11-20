"""implements: AI-C-18
covers: 5-layer target contract dataclasses, §4.3 selector invariants (3/4/5)
"""

from mission_runtime.contracts.capability import CapabilityState
import pytest

from mission_runtime.contracts.capability_contract import (
    CAPABILITY_DECLARATION_ITEMS,
    DECLARATION_ITEM_OWNERS,
    INVOCATION_MODES,
    ITEM_CANCELLABLE,
    ITEM_IDEMPOTENT,
    ITEM_SCOPE,
    Capability,
    DeclarationBasis,
    ExecutionProfile,
    Implementation,
    RuntimeInstance,
    TaskIntent,
)


def test_capability_optional_fields_default_when_unstated():
    # AI-C-18: "모든 항목이 항상 존재한다고 가정해서는 안 된다."
    cap = Capability(kind="perception.detect")

    assert cap.input_schema is None
    assert cap.properties == {}
    assert cap.preconditions == ()


def test_implementation_links_back_to_capability_kind():
    impl = Implementation(
        capability_kind="perception.detect",
        provider_id="cam-1",
        implementation_version="v3",
    )

    assert impl.capability_kind == "perception.detect"
    assert impl.model_ref is None


def test_execution_profile_matches_conditions_ignores_hardware_tag_order():
    profile = ExecutionProfile(
        implementation_ref="cam-1",
        runtime="onnxruntime",
        hardware_tags=("cpu", "arm64"),
        input_profile="320x320",
    )

    assert profile.matches_conditions(runtime="onnxruntime", hardware_tags=("arm64", "cpu"), input_profile="320x320")


def test_execution_profile_does_not_match_when_any_condition_differs():
    profile = ExecutionProfile(
        implementation_ref="cam-1",
        runtime="onnxruntime",
        hardware_tags=("cpu",),
        input_profile="320x320",
    )

    # AI-B-01: 조건이 하나라도 다르면 이 evidence를 재사용하지 않는다.
    assert not profile.matches_conditions(runtime="tensorrt", hardware_tags=("cpu",), input_profile="320x320")
    assert not profile.matches_conditions(runtime="onnxruntime", hardware_tags=("cuda",), input_profile="320x320")
    assert not profile.matches_conditions(runtime="onnxruntime", hardware_tags=("cpu",), input_profile="640x640")


def test_runtime_instance_unhealthy_is_never_selectable():
    instance = RuntimeInstance(
        instance_id="i-1", deployment_ref="d-1", healthy=False, health_ttl=30.0, health_checked_at=100.0
    )

    assert not instance.is_selectable(now=100.0)


def test_runtime_instance_expired_ttl_is_not_selectable_even_if_last_reported_healthy():
    # §4.3 불변조건 4: TTL이 만료된 instance는 과거 benchmark가 있어도 선택하지 않는다.
    instance = RuntimeInstance(
        instance_id="i-1", deployment_ref="d-1", healthy=True, health_ttl=30.0, health_checked_at=100.0
    )

    assert instance.is_selectable(now=120.0)
    assert not instance.is_selectable(now=131.0)


def test_task_intent_availability_delegates_to_capability_requirement():
    # 새 판정 로직을 만들지 않고 기존 AI-C-05 계약(CapabilityRequirement)에 위임한다.
    intent = TaskIntent(required_capabilities=("perception.detect",), optional_capabilities=("perception.depth",))

    assert intent.evaluate_availability({"perception.detect", "perception.depth"}) is CapabilityState.ACTIVE
    assert intent.evaluate_availability({"perception.detect"}) is CapabilityState.DEGRADED
    assert intent.evaluate_availability(set()) is CapabilityState.DISABLED


def test_task_intent_required_shortfall_is_not_papered_over_by_optional():
    # §4.3 불변조건 5: required 부족을 optional만으로 성공 처리하지 않는다.
    intent = TaskIntent(required_capabilities=("perception.detect",), optional_capabilities=("perception.depth",))

    assert intent.evaluate_availability({"perception.depth"}) is CapabilityState.DISABLED


def test_task_intent_deadline_and_input_age_are_hard_filters():
    intent = TaskIntent(deadline=100.0, max_input_age=5.0)

    assert intent.is_within_deadline(now=99.0)
    assert not intent.is_within_deadline(now=101.0)
    assert intent.is_input_fresh_enough(frame_age=4.0)
    assert not intent.is_input_fresh_enough(frame_age=6.0)


def test_task_intent_unmeasured_input_age_does_not_block():
    # 미측정 항목이 배치를 막지 않는다 — frame_age를 모르면 판정을 보류하고 통과.
    intent = TaskIntent(max_input_age=5.0)

    assert intent.is_input_fresh_enough(frame_age=None)


# --- AI-C-18 선언 항목이 **담길 자리를 갖는가** -----------------------------
# 2026-11-04: 그 전까지 이 계약에는 단위·좌표·시간 기준 / 취소 가능 여부 /
# 멱등성 / 동기·비동기 / 수행·관측 범위를 담을 칸이 아예 없었다. 요구사항이
# 열거한 항목을 토큰으로 고정하고 **주인을 시험으로 묻는다** — 항목이 늘거나
# 칸이 사라지면 여기서 깨진다.


def test_every_ai_c_18_item_has_exactly_one_owning_layer():
    owned = [item for items in DECLARATION_ITEM_OWNERS.values() for item in items]
    assert sorted(owned) == sorted(CAPABILITY_DECLARATION_ITEMS), (
        "담길 자리가 없는 항목이 있거나 표에 없는 토큰이 있다")
    assert len(owned) == len(set(owned)), (
        "한 항목을 두 계층이 담으면 같은 사실에 주인이 둘이 된다")


def test_unstated_cancellable_and_idempotent_are_unknown_not_no():
    """모른다와 안 된다는 **다른 값**이어야 한다(AI-C-18).

    False 로 접히면 상위 기능이 "이 장치는 취소를 거부한다" 로 읽고, 실제로는
    아무도 선언하지 않은 것이다. AI-C-20 의 취소 수락/CANCELED 도달 구분이
    이 선언 위에 서 있다.
    """
    silent = Capability(kind="hardware.action.stop")
    refused = Capability(kind="hardware.action.stop", cancellable=False, idempotent=False)

    assert silent.cancellable is None and silent.idempotent is None
    assert refused.cancellable is False and refused.idempotent is False
    assert ITEM_CANCELLABLE in silent.undeclared_items()
    assert ITEM_IDEMPOTENT in silent.undeclared_items()
    assert ITEM_CANCELLABLE not in refused.undeclared_items()
    assert ITEM_IDEMPOTENT not in refused.undeclared_items()


def test_declared_empty_scope_is_not_the_same_as_an_unstated_scope():
    unstated = Capability(kind="k")
    unbounded = Capability(kind="k", scope_tags=())

    assert unstated.scope_tags is None
    assert ITEM_SCOPE in unstated.undeclared_items()
    assert ITEM_SCOPE not in unbounded.undeclared_items()


def test_basis_is_absent_rather_than_empty_when_nobody_declared_it():
    """빈 기준 객체를 만들어 두면 "기준을 선언했다" 가 되어 미선언과 구분되지
    않는다 — 0.5 가 m 인지 m/s 인지 모르는 채로 물리 동작이 나간다."""
    assert Capability(kind="k").basis is None

    stated = Capability(kind="k", basis=DeclarationBasis(
        units={"distance_m": "m"}, reference_frame="device-local",
        time_basis="backend_ntp"))
    assert stated.basis.units["distance_m"] == "m"
    # 적지 않은 이름은 단위를 **모르는** 것이고 무단위가 아니다.
    assert "yaw_deg" not in stated.basis.units


def test_a_fully_stated_declaration_leaves_nothing_undeclared():
    cap = Capability(
        kind="hardware.action.navigate", input_schema="schema://p",
        output_schema="schema://r", preconditions=("mobility.base",),
        cancellable=True, idempotent=True, invocation=INVOCATION_MODES[1],
        basis=DeclarationBasis(time_basis="backend_ntp"), scope_tags=("zone.a",),
    )
    assert cap.undeclared_items() == ()
    assert cap.is_fully_declared() is True


def test_an_invocation_outside_the_vocabulary_is_refused():
    """어휘 밖 문자열을 받으면 소비자가 그것을 세 번째 모드로 읽는다. 모르는
    것은 None 이고, 그것이 어휘 밖 값과 다르다."""
    with pytest.raises(ValueError):
        Capability(kind="k", invocation="maybe")


def test_empty_execution_conditions_count_as_unstated_not_as_no_conditions():
    """보수적으로 틀리는 쪽은 없는 선언을 지어내지 않는 쪽이다."""
    assert "execution_conditions" in Capability(kind="k").undeclared_items()
    assert "execution_conditions" not in Capability(
        kind="k", optional_preconditions=("accel.npu",)).undeclared_items()


def test_declared_conditions_are_evaluated_by_the_existing_ai_c_05_contract():
    """선택 조건의 결손은 DEGRADED 까지만이다 — 새 판정을 만들지 않고 기존
    계약에 넘긴다(AI-C-05, 절대 준수 원칙 #4)."""
    cap = Capability(kind="perception.detect", preconditions=("media.video_input",),
                     optional_preconditions=("accel.npu",))
    requirement = cap.requirement()

    assert requirement.evaluate({"media.video_input", "accel.npu"}) is CapabilityState.ACTIVE
    assert requirement.evaluate({"media.video_input"}) is CapabilityState.DEGRADED
    assert requirement.evaluate({"accel.npu"}) is CapabilityState.DISABLED
