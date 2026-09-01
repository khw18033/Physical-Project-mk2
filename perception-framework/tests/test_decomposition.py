"""implements: AI-D-03 인접 (Milestone -> Task 분해, perception_framework.planning 참고)
tests: template materialization, missing required/optional capability,
       executor selection with DEGRADED-only fallback, unverifiable
       preconditions, resource floor, determinism of re-runs
"""

from perception_framework.contracts.capability import CapabilityRequirement, CapabilityState
from perception_framework.contracts.profile import CompatibilityProfile, ResourceBudget, ResourceCost
from perception_framework.planning.decomposition import (
    BindingSource,
    DecompositionContext,
    ExecutorCandidate,
    StepTemplate,
    SubtaskPlanValidator,
    TaskDecomposer,
    TaskTemplate,
    TaskTemplateLibrary,
)
from perception_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration

BUDGET = ResourceBudget(compute_units=100.0, memory_mb=4096.0)


def provider(kind, provider_id, cost_units=1.0):
    return ProviderRegistration(
        capability_kind=kind,
        provider_id=provider_id,
        version="1",
        compatibility=CompatibilityProfile(cost=ResourceCost(compute_units=cost_units)),
        requirement=CapabilityRequirement(),
    )


def observe_region_template():
    return TaskTemplate(
        goal_kind="OBSERVE_REGION",
        version="1.0.0",
        executor_requirement=CapabilityRequirement(
            required=("mobility", "camera"),
            optional=("local_perception",),
        ),
        steps=(
            StepTemplate("SELECT_AGENT", CapabilityRequirement(required=("mobility",))),
            StepTemplate(
                "NAVIGATE",
                CapabilityRequirement(required=("mobility",), optional=("navigation.map",)),
                preconditions=("zone_reachable",),
                forbidden_if=("zone_blocked",),
            ),
            StepTemplate("OBSERVE", CapabilityRequirement(required=("camera",))),
            StepTemplate(
                "ANALYZE",
                CapabilityRequirement(required=("local_perception",), optional=("perception.distance",)),
            ),
            StepTemplate("REPORT", CapabilityRequirement(required=("transport.task",))),
        ),
    )


def library():
    lib = TaskTemplateLibrary()
    lib.register(observe_region_template())
    return lib


def edge_registry(kinds=("transport.task",)):
    registry = CapabilityRegistry()
    for kind in kinds:
        registry.register_local(provider(kind, f"edge-{kind}"))
    return registry


def context(**overrides):
    base = dict(
        goal_id="mission-42",
        goal_kind="OBSERVE_REGION",
        zone_id="zone-a",
        budget=BUDGET,
        known_facts={"zone_reachable": True},
    )
    base.update(overrides)
    return DecompositionContext(**base)


def full_executor(executor_id="unit-01"):
    return ExecutorCandidate(
        executor_id=executor_id,
        capability_kinds=frozenset({"mobility", "camera", "local_perception"}),
    )


def test_decompose_produces_ordered_template_steps():
    plan = TaskDecomposer(edge_registry(), library()).decompose(context(), [full_executor()])

    assert [s.action for s in plan.subtasks] == [
        "SELECT_AGENT",
        "NAVIGATE",
        "OBSERVE",
        "ANALYZE",
        "REPORT",
    ]
    assert [s.order_index for s in plan.subtasks] == [0, 1, 2, 3, 4]
    assert plan.reason == "fully_executable"


def test_unknown_goal_kind_returns_empty_plan_instead_of_raising():
    plan = TaskDecomposer(edge_registry(), library()).decompose(
        context(goal_kind="NOT_DEPLOYED"), [full_executor()]
    )

    assert plan.subtasks == ()
    assert plan.reason == "no_template_for_goal_kind"
    assert plan.executor.executor_id is None


def test_missing_required_capability_marks_only_that_step_non_executable():
    # transport.task 를 제공하는 엣지 provider 가 없다 -> REPORT 만 실행 불가
    plan = TaskDecomposer(edge_registry(kinds=()), library()).decompose(context(), [full_executor()])

    blocked = {s.action for s in plan.blocked_subtasks}
    assert blocked == {"REPORT"}
    report = plan.subtasks[4]
    assert report.state is CapabilityState.DISABLED
    assert report.missing_required_capabilities == ("transport.task",)
    assert plan.reason == "partially_executable"


def test_missing_optional_capability_degrades_but_stays_executable():
    plan = TaskDecomposer(edge_registry(), library()).decompose(context(), [full_executor()])

    navigate = plan.subtasks[1]
    assert navigate.missing_optional_capabilities == ("navigation.map",)
    assert navigate.state is CapabilityState.DEGRADED
    assert navigate.executable is True


def test_executor_capability_is_used_when_edge_registry_cannot_supply_it():
    plan = TaskDecomposer(edge_registry(), library()).decompose(context(), [full_executor()])

    observe = plan.subtasks[2]
    binding = observe.bindings[0]
    assert binding.capability_kind == "camera"
    assert binding.source is BindingSource.EXECUTOR
    assert binding.provider_id == "unit-01"


def test_edge_registry_provider_wins_over_executor_hosted_capability():
    registry = edge_registry(kinds=("transport.task", "camera"))
    plan = TaskDecomposer(registry, library()).decompose(context(), [full_executor()])

    assert plan.subtasks[2].bindings[0].source is BindingSource.REGISTRY


def test_active_executor_is_preferred_over_degraded_one():
    degraded = ExecutorCandidate("a-unit", frozenset({"mobility", "camera"}))
    active = ExecutorCandidate("z-unit", frozenset({"mobility", "camera", "local_perception"}))

    plan = TaskDecomposer(edge_registry(), library()).decompose(context(), [degraded, active])

    assert plan.executor.executor_id == "z-unit"
    assert plan.executor.state is CapabilityState.ACTIVE


def test_degraded_only_executor_is_accepted_as_reduced_execution():
    degraded = ExecutorCandidate("a-unit", frozenset({"mobility", "camera"}))

    plan = TaskDecomposer(edge_registry(), library()).decompose(context(), [degraded])

    # AI-C-11: 선택 조건 결손은 비활성이 아니라 축소 실행이다.
    assert plan.executor.executor_id == "a-unit"
    assert plan.executor.state is CapabilityState.DEGRADED
    assert plan.executor.reason == "selected_degraded"
    assert plan.executor.missing_optional_capabilities == ("local_perception",)


def test_no_executor_meets_required_capabilities():
    unusable = ExecutorCandidate("sensor-only", frozenset({"camera"}))

    plan = TaskDecomposer(edge_registry(), library()).decompose(context(), [unusable])

    assert plan.executor.executor_id is None
    assert plan.executor.state is CapabilityState.DISABLED
    assert plan.executor.missing_required_capabilities == ("mobility",)
    assert plan.reason == "no_executor_meets_required_capabilities"


def test_no_executor_candidate_at_all():
    plan = TaskDecomposer(edge_registry(), library()).decompose(context(), [])

    assert plan.executor.reason == "no_executor_candidate"


def test_unknown_precondition_is_not_assumed_true():
    plan = TaskDecomposer(edge_registry(), library()).decompose(
        context(known_facts={}), [full_executor()]
    )

    navigate = plan.subtasks[1]
    assert navigate.unverified_preconditions == ("zone_reachable",)
    assert navigate.executable is False
    # capability 는 멀쩡하다 — 실행 불가 사유는 근거 부족이지 기능 부재가 아니다.
    assert navigate.missing_required_capabilities == ()


def test_explicitly_false_forbidden_condition_does_not_block():
    plan = TaskDecomposer(edge_registry(), library()).decompose(
        context(known_facts={"zone_reachable": True, "zone_blocked": False}), [full_executor()]
    )

    assert plan.subtasks[1].violated_forbidden_conditions == ()
    assert plan.subtasks[1].executable is True


def test_forbidden_condition_holding_blocks_only_that_step():
    plan = TaskDecomposer(edge_registry(), library()).decompose(
        context(known_facts={"zone_reachable": True, "zone_blocked": True}), [full_executor()]
    )

    assert plan.subtasks[1].violated_forbidden_conditions == ("zone_blocked",)
    assert {s.action for s in plan.blocked_subtasks} == {"NAVIGATE"}


def test_validator_reports_valid_plan():
    ctx = context()
    plan = TaskDecomposer(edge_registry(), library()).decompose(ctx, [full_executor()])

    report = SubtaskPlanValidator().validate(plan, ctx)

    assert report.valid is True
    assert report.structural_errors == ()


def test_validator_collects_missing_evidence_for_downstream_request():
    ctx = context(known_facts={})
    plan = TaskDecomposer(edge_registry(kinds=()), library()).decompose(ctx, [full_executor()])

    report = SubtaskPlanValidator().validate(plan, ctx)

    assert report.valid is False
    assert "zone_reachable" in report.missing_evidence
    assert "transport.task" in report.missing_evidence


def test_validator_flags_unknown_resource_instead_of_assuming_it():
    ctx = context(resource_floor={"energy_pct": 30.0}, executor_resources={})
    plan = TaskDecomposer(edge_registry(), library()).decompose(ctx, [full_executor()])

    report = SubtaskPlanValidator().validate(plan, ctx)

    assert report.valid is False
    assert all("unknown_resource:energy_pct" in f.reasons for f in report.findings)
    assert "resource:energy_pct" in report.missing_evidence


def test_validator_flags_insufficient_resource():
    ctx = context(resource_floor={"energy_pct": 30.0}, executor_resources={"energy_pct": 10.0})
    plan = TaskDecomposer(edge_registry(), library()).decompose(ctx, [full_executor()])

    report = SubtaskPlanValidator().validate(plan, ctx)

    assert report.valid is False
    assert "insufficient_resource:energy_pct" in report.findings[0].reasons


def test_validator_detects_zone_boundary_violation_independently():
    plan = TaskDecomposer(edge_registry(), library()).decompose(context(), [full_executor()])

    other_zone = context(zone_id="zone-b")
    report = SubtaskPlanValidator().validate(plan, other_zone)

    assert report.valid is False
    assert any(e.startswith("zone_boundary_violation:") for e in report.structural_errors)


def test_same_input_yields_identical_plan_and_report():
    decomposer = TaskDecomposer(edge_registry(), library())
    validator = SubtaskPlanValidator()
    ctx = context()
    candidates = [full_executor("b-unit"), full_executor("a-unit")]

    first = decomposer.decompose(ctx, candidates)
    second = decomposer.decompose(ctx, candidates)

    assert first == second
    assert validator.validate(first, ctx) == validator.validate(second, ctx)
    # 동점 후보는 id 순으로 확정된다 — 입력 순서에 흔들리지 않는다.
    assert first.executor.executor_id == "a-unit"


def test_no_domain_nouns_in_planning_module_identifiers():
    import ast
    import pathlib

    import perception_framework.planning.decomposition as module

    tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
    docstrings = {
        ast.get_docstring(node, clean=False)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
    }
    identifiers = set()
    for node in ast.walk(tree):
        for attr in ("name", "id", "arg", "attr"):
            value = getattr(node, attr, None)
            if isinstance(value, str):
                identifiers.add(value.lower())
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value not in docstrings:
                identifiers.add(node.value.lower())

    # 절대 준수 원칙 #3: 도메인 명사가 코드 식별자·리터럴에 들어가면 안 된다.
    # 이전 구현의 `robot_resources` 가 정확히 이 위반이었다.
    for noun in ("robot", "facility", "river", "drone", "vehicle"):
        offenders = [name for name in identifiers if noun in name]
        assert offenders == [], f"domain noun {noun!r} leaked into {offenders}"
