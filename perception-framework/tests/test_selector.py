"""implements: AI-B-01, AI-B-04, AI-B-06, AI-C-13, AI-C-18"""

from perception_framework.contracts.capability import CapabilityRequirement
from perception_framework.contracts.capability_contract import ExecutionProfile, RuntimeInstance, TaskIntent
from perception_framework.contracts.profile import CompatibilityProfile, ResourceBudget, ResourceCost
from perception_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration
from perception_framework.selection.selector import CandidateOutcome, CapabilitySelector


def reg_of(kind, provider_id, priority, cost_units, hw=()):
    return ProviderRegistration(
        capability_kind=kind,
        provider_id=provider_id,
        version="1",
        compatibility=CompatibilityProfile(
            required_hw_tags=hw,
            priority=priority,
            cost=ResourceCost(compute_units=cost_units),
        ),
        requirement=CapabilityRequirement(),
    )


def test_select_returns_none_without_exception_when_nothing_registered():
    registry = CapabilityRegistry()
    selector = CapabilitySelector(registry)

    result = selector.select("perception.distance", node_tags=set(), budget=ResourceBudget(1, 1))

    assert result.provider is None
    assert result.reason == "no_provider_registered"


def test_select_excludes_provider_whose_required_hw_tag_is_absent():
    registry = CapabilityRegistry()
    registry.register_local(reg_of("perception.classify", "gpu-model", priority=10, cost_units=8, hw=("gpu",)))
    registry.register_local(reg_of("perception.classify", "cpu-model", priority=50, cost_units=2))
    selector = CapabilitySelector(registry)

    result = selector.select(
        "perception.classify", node_tags=set(), budget=ResourceBudget(compute_units=10, memory_mb=1024)
    )

    # gpu-model has higher priority (lower number) but this node has no
    # "gpu" tag, so the compatible cpu-model must be chosen instead.
    assert result.provider.provider_id == "cpu-model"


def test_select_prefers_lower_priority_number_among_compatible_providers():
    registry = CapabilityRegistry()
    registry.register_local(reg_of("perception.classify", "gpu-model", priority=10, cost_units=8, hw=("gpu",)))
    registry.register_local(reg_of("perception.classify", "cpu-model", priority=50, cost_units=2))
    selector = CapabilitySelector(registry)

    result = selector.select(
        "perception.classify", node_tags={"gpu"}, budget=ResourceBudget(compute_units=10, memory_mb=1024)
    )

    assert result.provider.provider_id == "gpu-model"


def test_select_excludes_provider_over_budget():
    registry = CapabilityRegistry()
    registry.register_local(reg_of("perception.classify", "heavy", priority=1, cost_units=100))
    selector = CapabilitySelector(registry)

    result = selector.select(
        "perception.classify", node_tags=set(), budget=ResourceBudget(compute_units=5, memory_mb=1024)
    )

    assert result.provider is None
    assert result.reason == "no_compatible_provider_within_budget"


def test_degrade_falls_through_ordered_capability_kinds():
    registry = CapabilityRegistry()
    registry.register_local(reg_of("risk.timeseries_model", "heavy-model", priority=1, cost_units=100))
    registry.register_local(reg_of("risk.rule_based", "cheap-rules", priority=1, cost_units=1))
    selector = CapabilitySelector(registry)

    result = selector.select_with_degrade(
        ["risk.timeseries_model", "risk.rule_based"],
        node_tags=set(),
        budget=ResourceBudget(compute_units=5, memory_mb=64),
    )

    # The richer capability kind is over budget; selector falls through
    # to the next, more conservative kind instead of returning nothing
    # (AI-B-06 단계적 축소).
    assert result.provider.provider_id == "cheap-rules"


def test_degrade_returns_none_when_every_kind_is_unusable():
    registry = CapabilityRegistry()
    selector = CapabilitySelector(registry)

    result = selector.select_with_degrade(
        ["risk.timeseries_model", "risk.rule_based"], node_tags=set(), budget=ResourceBudget(1, 1)
    )

    assert result.provider is None


# -- select_for_intent (AI-C-18 5-layer contract connection) ---------------


def test_select_for_intent_degrades_to_plain_select_when_no_profile_attached():
    # 기존 등록(execution_profile/runtime_instance 없음)은 select()와 동일하게 동작해야
    # 한다 — 신규 계약이 기존 선택 결과를 바꾸지 않는다.
    registry = CapabilityRegistry()
    registry.register_local(reg_of("perception.classify", "cpu-model", priority=50, cost_units=2))
    selector = CapabilitySelector(registry)

    result = selector.select_for_intent(
        "perception.classify",
        TaskIntent(required_capabilities=("perception.classify",)),
        node_tags=set(),
        budget=ResourceBudget(compute_units=10, memory_mb=1024),
    )

    assert result.provider.provider_id == "cpu-model"
    assert result.reason == "selected"


def test_select_for_intent_rejects_past_deadline_before_touching_candidates():
    registry = CapabilityRegistry()
    registry.register_local(reg_of("perception.classify", "cpu-model", priority=50, cost_units=2))
    selector = CapabilitySelector(registry)

    result = selector.select_for_intent(
        "perception.classify",
        TaskIntent(required_capabilities=("perception.classify",), deadline=100.0),
        node_tags=set(),
        budget=ResourceBudget(compute_units=10, memory_mb=1024),
        now=101.0,
    )

    assert result.provider is None
    assert result.reason == "deadline_exceeded"


def test_select_for_intent_rejects_stale_input():
    registry = CapabilityRegistry()
    registry.register_local(reg_of("perception.classify", "cpu-model", priority=50, cost_units=2))
    selector = CapabilitySelector(registry)

    result = selector.select_for_intent(
        "perception.classify",
        TaskIntent(required_capabilities=("perception.classify",), max_input_age=1.0),
        node_tags=set(),
        budget=ResourceBudget(compute_units=10, memory_mb=1024),
        frame_age=5.0,
    )

    assert result.provider is None
    assert result.reason == "input_too_stale"


def test_select_for_intent_skips_candidate_whose_execution_profile_conditions_mismatch():
    # §4.3 불변조건 3: 조건이 다른 evidence는 재사용하지 않는다 — 조건 불일치 후보를
    # 건너뛰고 다음 후보로 넘어간다.
    registry = CapabilityRegistry()
    mismatched = reg_of("perception.classify", "gpu-trt", priority=1, cost_units=2)
    mismatched.execution_profile = ExecutionProfile(
        implementation_ref="gpu-trt", runtime="tensorrt", hardware_tags=("cuda",), input_profile="640x640"
    )
    fallback = reg_of("perception.classify", "cpu-onnx", priority=50, cost_units=2)
    fallback.execution_profile = ExecutionProfile(
        implementation_ref="cpu-onnx", runtime="onnxruntime", hardware_tags=("cpu",), input_profile="640x640"
    )
    registry.register_local(mismatched)
    registry.register_local(fallback)
    selector = CapabilitySelector(registry)

    result = selector.select_for_intent(
        "perception.classify",
        TaskIntent(required_capabilities=("perception.classify",)),
        node_tags=set(),
        budget=ResourceBudget(compute_units=10, memory_mb=1024),
        runtime="onnxruntime",
        hardware_tags=("cpu",),
        input_profile="640x640",
    )

    assert result.provider.provider_id == "cpu-onnx"


def test_select_for_intent_excludes_runtime_instance_past_health_ttl():
    # §4.3 불변조건 4: TTL 만료 instance는 과거 benchmark가 있어도 선택하지 않는다.
    registry = CapabilityRegistry()
    expired = reg_of("perception.classify", "stale-instance", priority=1, cost_units=2)
    expired.runtime_instance = RuntimeInstance(
        instance_id="i-1", deployment_ref="d-1", healthy=True, health_ttl=10.0, health_checked_at=0.0
    )
    registry.register_local(expired)
    selector = CapabilitySelector(registry)

    result = selector.select_for_intent(
        "perception.classify",
        TaskIntent(required_capabilities=("perception.classify",)),
        node_tags=set(),
        budget=ResourceBudget(compute_units=10, memory_mb=1024),
        now=100.0,
    )

    assert result.provider is None
    assert result.reason == "runtime_instance_unhealthy_or_expired"


def test_select_for_intent_selects_when_profile_and_instance_both_match():
    registry = CapabilityRegistry()
    reg = reg_of("perception.classify", "cpu-onnx", priority=1, cost_units=2)
    reg.execution_profile = ExecutionProfile(
        implementation_ref="cpu-onnx", runtime="onnxruntime", hardware_tags=("cpu",), input_profile="640x640"
    )
    reg.runtime_instance = RuntimeInstance(
        instance_id="i-1", deployment_ref="d-1", healthy=True, health_ttl=30.0, health_checked_at=95.0
    )
    registry.register_local(reg)
    selector = CapabilitySelector(registry)

    result = selector.select_for_intent(
        "perception.classify",
        TaskIntent(required_capabilities=("perception.classify",)),
        node_tags=set(),
        budget=ResourceBudget(compute_units=10, memory_mb=1024),
        now=100.0,
        runtime="onnxruntime",
        hardware_tags=("cpu",),
        input_profile="640x640",
    )

    assert result.provider.provider_id == "cpu-onnx"
    assert result.reason == "selected"


# -- alternatives: what was considered, not only what won (2026-09-17, P1) --


def test_alternatives_keep_each_rejected_candidate_with_its_own_reason():
    registry = CapabilityRegistry()
    registry.register_local(reg_of("perception.classify", "gpu-model", priority=10, cost_units=8, hw=("gpu",)))
    registry.register_local(reg_of("perception.classify", "heavy-cpu", priority=20, cost_units=100))
    registry.register_local(reg_of("perception.classify", "cpu-model", priority=50, cost_units=2))
    selector = CapabilitySelector(registry)

    result = selector.select(
        "perception.classify", node_tags=set(), budget=ResourceBudget(compute_units=10, memory_mb=1024)
    )

    assert result.provider.provider_id == "cpu-model"
    by_id = {a.provider_id: a.reason for a in result.alternatives}
    assert by_id == {"gpu-model": "required_hw_tag_missing:gpu", "heavy-cpu": "over_budget"}


def test_winner_never_appears_in_alternatives_and_runners_up_are_marked_compatible():
    registry = CapabilityRegistry()
    registry.register_local(reg_of("perception.classify", "first", priority=1, cost_units=2))
    registry.register_local(reg_of("perception.classify", "second", priority=2, cost_units=2))
    registry.register_local(reg_of("perception.classify", "third", priority=3, cost_units=2))
    selector = CapabilitySelector(registry)

    result = selector.select(
        "perception.classify", node_tags=set(), budget=ResourceBudget(compute_units=10, memory_mb=1024)
    )

    assert result.provider.provider_id == "first"
    assert [(a.provider_id, a.reason) for a in result.alternatives] == [
        ("second", "compatible"),
        ("third", "compatible"),
    ]


def test_alternatives_explain_a_none_result_and_are_empty_when_nothing_is_registered():
    registry = CapabilityRegistry()
    selector = CapabilitySelector(registry)
    assert selector.select("perception.classify", set(), ResourceBudget(1, 1)).alternatives == ()

    registry.register_local(reg_of("perception.classify", "heavy", priority=1, cost_units=100))
    result = selector.select("perception.classify", set(), ResourceBudget(compute_units=5, memory_mb=1024))

    # "왜 안 됨?" — the aggregate reason plus the per-candidate one.
    assert result.provider is None
    assert result.reason == "no_compatible_provider_within_budget"
    assert result.alternatives == (CandidateOutcome("heavy", "over_budget"),)


def test_placement_filter_rejections_are_reported_per_candidate():
    registry = CapabilityRegistry()
    registry.register_local(reg_of("perception.classify", "cloud-vlm", priority=1, cost_units=2))
    registry.register_local(reg_of("perception.classify", "local", priority=5, cost_units=2))
    selector = CapabilitySelector(
        registry,
        placement_filter=lambda reg: "external_connection_required_in_closed_network"
        if reg.provider_id == "cloud-vlm" else None,
    )

    result = selector.select("perception.classify", set(), ResourceBudget(compute_units=10, memory_mb=1024))

    assert result.provider.provider_id == "local"
    assert result.alternatives == (
        CandidateOutcome("cloud-vlm", "external_connection_required_in_closed_network"),
    )


def test_select_for_intent_reports_candidates_skipped_by_profile_or_instance_checks():
    registry = CapabilityRegistry()
    mismatched = reg_of("perception.classify", "gpu-trt", priority=1, cost_units=2)
    mismatched.execution_profile = ExecutionProfile(
        implementation_ref="gpu-trt", runtime="tensorrt", hardware_tags=("cuda",), input_profile="640x640"
    )
    expired = reg_of("perception.classify", "stale", priority=2, cost_units=2)
    expired.runtime_instance = RuntimeInstance(
        instance_id="i-1", deployment_ref="d-1", healthy=True, health_ttl=10.0, health_checked_at=0.0
    )
    winner = reg_of("perception.classify", "cpu-onnx", priority=3, cost_units=2)
    spare = reg_of("perception.classify", "cpu-spare", priority=4, cost_units=2)
    for reg in (mismatched, expired, winner, spare):
        registry.register_local(reg)
    selector = CapabilitySelector(registry)

    result = selector.select_for_intent(
        "perception.classify",
        TaskIntent(required_capabilities=("perception.classify",)),
        node_tags=set(),
        budget=ResourceBudget(compute_units=10, memory_mb=1024),
        now=100.0,
        runtime="onnxruntime",
        hardware_tags=("cpu",),
        input_profile="640x640",
    )

    assert result.provider.provider_id == "cpu-onnx"
    assert [(a.provider_id, a.reason) for a in result.alternatives] == [
        ("gpu-trt", "execution_profile_conditions_mismatch"),
        ("stale", "runtime_instance_unhealthy_or_expired"),
        ("cpu-spare", "compatible"),
    ]


def test_degrade_result_carries_the_candidates_of_the_kinds_it_fell_through():
    registry = CapabilityRegistry()
    registry.register_local(reg_of("risk.timeseries_model", "heavy-model", priority=1, cost_units=100))
    registry.register_local(reg_of("risk.rule_based", "cheap-rules", priority=1, cost_units=1))
    selector = CapabilitySelector(registry)

    result = selector.select_with_degrade(
        ["risk.timeseries_model", "risk.rule_based"], node_tags=set(), budget=ResourceBudget(5, 64)
    )

    assert result.provider.provider_id == "cheap-rules"
    assert result.alternatives == (CandidateOutcome("heavy-model", "over_budget"),)
