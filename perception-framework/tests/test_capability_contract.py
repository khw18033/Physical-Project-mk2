"""implements: AI-C-18
covers: 5-layer target contract dataclasses, §4.3 selector invariants (3/4/5)
"""

from perception_framework.contracts.capability import CapabilityState
from perception_framework.contracts.capability_contract import (
    Capability,
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
