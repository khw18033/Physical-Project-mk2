"""Decomposes a zone-level task goal into edge-local executable Task units.

implements: AI-D-03 인접 (Milestone -> Task 분해)
관련: AI-C-05, AI-C-11 (선택 기능 축소), AI-C-13 (자원 최소화), AI-C-15 (도메인 중립)

관할 경계
---------
Goal→Milestone→Task→Action Item 계층에서 Milestone/Task는 AI 소관으로
확정됐다(docs/integration/subtask-handoff-to-visualization.md §계층 경계 확정
2026-08-28). AI-D-01(서브태스크=Action Item 생성)과 AI-D-02(검증)은 2026-08-26에
가시화 파트로 이관되어 AI 저장소에서 삭제됐고, 이 모듈은 그 복원이 아니다.
삭제 시점 스키마(plan-proposal)는 근거로만 참고했고 그대로 복원하지 않았다 —
특히 이관 문서가 문제로 지적한 `robot_resources`처럼 핵심 코드에 도메인
명사가 들어간 이름은 쓰지 않는다(절대 준수 원칙 #3).

왜 Task Template + Capability 기반인가
--------------------------------------
AI-D-01: "계획 생성 방식은 특정 LLM이나 계획 라이브러리를 필수로 하지 않고
검증 가능한 행동 단위와 조건 표현을 사용해야 한다."

그래서 자유 생성이 아니라 (1) 목표 종류별 단계 순서를 데이터로 선언한
task template 과 (2) 현재 registry 에서 실제로 실행 가능한 capability 로
각 단계를 채우는 구체화, 두 단계로 나눈다. 이 설계를 고른 이유는
**재현 가능성과 설명 가능성**이다. 같은 입력(템플릿 + registry 상태 + 사실
집합)이면 항상 같은 계획이 나오고, 어떤 단계가 왜 실행 불가인지 "무슨
capability 가 없어서"라는 형태로 그대로 설명된다. LLM planner 를 쓰고 싶다면
`TaskTemplate` 를 생성하는 선택 provider 로 붙이면 되고, 이 모듈의 검증·구체화
계약은 그대로 유지된다(AI-C-09).

생성(`TaskDecomposer`)과 검증(`SubtaskPlanValidator`)은 분리되어 있다.
검증기는 생성 결과와 컨텍스트만 읽는 순수 함수이므로 동일 입력에 동일 결과를
낸다(AI-D-02: "검증 기능은 계획 생성 기능과 분리해 동일 조건에서 재현 가능한
결과를 제공해야 한다").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

from perception_framework.contracts.capability import CapabilityRequirement, CapabilityState
from perception_framework.contracts.profile import ResourceBudget, ResourceCost
from perception_framework.registry.capability_registry import CapabilityRegistry
from perception_framework.selection.selector import CapabilitySelector

# ---------------------------------------------------------------------------
# Template layer (data only — no domain names, no branching on domain_id)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StepTemplate:
    """One ordered action in a task template.

    `requirement` names capability *kinds*, never concrete sensors, models
    or runtimes; they are resolved against a CapabilityRegistry at
    decomposition time. `preconditions` are opaque fact ids the caller's
    world model is expected to answer; unknown ones are NOT assumed true.
    """

    action: str
    requirement: CapabilityRequirement = field(default_factory=CapabilityRequirement)
    preconditions: tuple[str, ...] = ()
    forbidden_if: tuple[str, ...] = ()
    cost: ResourceCost = field(default_factory=ResourceCost)
    params: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskTemplate:
    """Ordered step sequence for one goal kind.

    `goal_kind` is a free-form identifier (e.g. "OBSERVE_REGION") supplied
    by a deployment profile. Core code never branches on its value — it is
    only a dictionary key (AI-C-15).
    """

    goal_kind: str
    version: str
    steps: tuple[StepTemplate, ...]
    executor_requirement: CapabilityRequirement = field(default_factory=CapabilityRequirement)


class TaskTemplateLibrary:
    """Registry of task templates. Adding a goal kind is data, not code."""

    def __init__(self) -> None:
        self._templates: dict[str, TaskTemplate] = {}

    def register(self, template: TaskTemplate) -> None:
        self._templates[template.goal_kind] = template

    def get(self, goal_kind: str) -> TaskTemplate | None:
        """Unknown goal kinds return None rather than raising — an
        undeployed goal kind is a normal reduced-scope condition."""
        return self._templates.get(goal_kind)

    def known_goal_kinds(self) -> set[str]:
        return set(self._templates)


# ---------------------------------------------------------------------------
# Execution context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExecutorCandidate:
    """One entity that could carry out the executor-bound steps.

    Deliberately named `Executor`, not after any vehicle/robot/fixture
    class: the same type describes a mobile agent, a fixed sensor mast or
    a remote analysis node (절대 준수 원칙 #3).
    """

    executor_id: str
    capability_kinds: frozenset[str]
    node_tags: frozenset[str] = frozenset()
    resources: Mapping[str, float] = field(default_factory=dict)

    def state_for(self, requirement: CapabilityRequirement) -> CapabilityState:
        return requirement.evaluate(set(self.capability_kinds))


@dataclass(frozen=True)
class DecompositionContext:
    """Everything the decomposer is allowed to look at.

    `known_facts` is deliberately a *partial* map. A precondition absent
    from it is unknown, not true — AI-D-02 requires unverifiable
    conditions to mark that action non-executable and to name the missing
    evidence, never to be optimistically assumed.

    `executor_resources` carries the numeric resource state of the chosen
    executor (battery, storage, ... — keys are deployment-defined). The
    handoff doc flagged the old `robot_resources` field name as a domain
    leak; this is its domain-neutral replacement.
    """

    goal_id: str
    goal_kind: str
    zone_id: str
    node_tags: frozenset[str] = frozenset()
    budget: ResourceBudget = ResourceBudget(compute_units=0.0, memory_mb=0.0)
    known_facts: Mapping[str, bool] = field(default_factory=dict)
    executor_resources: Mapping[str, float] = field(default_factory=dict)
    resource_floor: Mapping[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


class BindingSource(str, Enum):
    """Where a step's capability was satisfied from."""

    REGISTRY = "registry"
    EXECUTOR = "executor"


@dataclass(frozen=True)
class CapabilityBinding:
    capability_kind: str
    provider_id: str
    source: BindingSource
    optional: bool = False


@dataclass(frozen=True)
class Subtask:
    subtask_id: str
    zone_id: str
    action: str
    order_index: int
    state: CapabilityState
    bindings: tuple[CapabilityBinding, ...]
    missing_required_capabilities: tuple[str, ...]
    missing_optional_capabilities: tuple[str, ...]
    unverified_preconditions: tuple[str, ...]
    violated_forbidden_conditions: tuple[str, ...]
    resource_cost: ResourceCost

    @property
    def executable(self) -> bool:
        return (
            self.state is not CapabilityState.DISABLED
            and not self.unverified_preconditions
            and not self.violated_forbidden_conditions
        )


@dataclass(frozen=True)
class ExecutorSelection:
    """Outcome of picking an executor.

    AI-C-11: ACTIVE 후보가 있으면 그것을 고르고, DEGRADED 후보밖에 없으면
    전체를 포기하는 대신 축소 실행으로 그것을 채택한다.
    """

    executor_id: str | None
    state: CapabilityState
    reason: str
    missing_required_capabilities: tuple[str, ...] = ()
    missing_optional_capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class SubtaskPlan:
    plan_id: str
    goal_id: str
    zone_id: str
    generator: str
    template_version: str
    executor: ExecutorSelection
    subtasks: tuple[Subtask, ...]
    reason: str

    @property
    def executable_subtasks(self) -> tuple[Subtask, ...]:
        return tuple(s for s in self.subtasks if s.executable)

    @property
    def blocked_subtasks(self) -> tuple[Subtask, ...]:
        return tuple(s for s in self.subtasks if not s.executable)


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

GENERATOR_NAME = "template-capability-decomposer"


class TaskDecomposer:
    """Turns (goal, template, current capabilities) into concrete subtasks.

    Determinism contract: the output depends only on the template, the
    registry contents, the executor candidates and the context. No wall
    clock, no random ids, no LLM call. Callers that want a timestamped
    envelope add it outside this module (AI-C-01/AI-C-03 are the
    transport-side concern, not the planner's).
    """

    def __init__(self, registry: CapabilityRegistry, library: TaskTemplateLibrary) -> None:
        self._registry = registry
        self._selector = CapabilitySelector(registry)
        self._library = library

    # -- executor choice ---------------------------------------------------

    def select_executor(
        self,
        candidates: list[ExecutorCandidate],
        requirement: CapabilityRequirement,
    ) -> ExecutorSelection:
        if not candidates:
            return ExecutorSelection(None, CapabilityState.DISABLED, "no_executor_candidate")

        rank = {CapabilityState.ACTIVE: 0, CapabilityState.DEGRADED: 1, CapabilityState.DISABLED: 2}
        scored = sorted(
            ((rank[c.state_for(requirement)], c.executor_id, c) for c in candidates),
            key=lambda item: (item[0], item[1]),  # 동점은 id 순 — 재현 가능해야 한다
        )
        best_rank, _, best = scored[0]
        state = best.state_for(requirement)
        have = set(best.capability_kinds)
        missing_required = tuple(k for k in requirement.required if k not in have)
        missing_optional = tuple(k for k in requirement.optional if k not in have)

        if best_rank == rank[CapabilityState.DISABLED]:
            return ExecutorSelection(
                None,
                CapabilityState.DISABLED,
                "no_executor_meets_required_capabilities",
                missing_required,
                missing_optional,
            )

        reason = "selected" if state is CapabilityState.ACTIVE else "selected_degraded"
        return ExecutorSelection(best.executor_id, state, reason, missing_required, missing_optional)

    # -- decomposition -----------------------------------------------------

    def decompose(
        self,
        context: DecompositionContext,
        candidates: list[ExecutorCandidate],
    ) -> SubtaskPlan:
        template = self._library.get(context.goal_kind)
        if template is None:
            return SubtaskPlan(
                plan_id=f"{context.goal_id}:none",
                goal_id=context.goal_id,
                zone_id=context.zone_id,
                generator=GENERATOR_NAME,
                template_version="",
                executor=ExecutorSelection(None, CapabilityState.DISABLED, "no_template"),
                subtasks=(),
                reason="no_template_for_goal_kind",
            )

        executor = self.select_executor(candidates, template.executor_requirement)
        chosen = next((c for c in candidates if c.executor_id == executor.executor_id), None)

        subtasks = tuple(
            self._materialize(step, index, context, chosen)
            for index, step in enumerate(template.steps)
        )

        if executor.executor_id is None:
            reason = executor.reason
        elif any(not s.executable for s in subtasks):
            reason = "partially_executable"
        else:
            reason = "fully_executable"

        return SubtaskPlan(
            plan_id=f"{context.goal_id}:{template.goal_kind}:{template.version}",
            goal_id=context.goal_id,
            zone_id=context.zone_id,
            generator=GENERATOR_NAME,
            template_version=template.version,
            executor=executor,
            subtasks=subtasks,
            reason=reason,
        )

    def _materialize(
        self,
        step: StepTemplate,
        index: int,
        context: DecompositionContext,
        executor: ExecutorCandidate | None,
    ) -> Subtask:
        bindings: list[CapabilityBinding] = []
        missing_required: list[str] = []
        missing_optional: list[str] = []

        for kind in step.requirement.required:
            binding = self._bind(kind, context, executor, optional=False)
            if binding is None:
                missing_required.append(kind)
            else:
                bindings.append(binding)

        for kind in step.requirement.optional:
            binding = self._bind(kind, context, executor, optional=True)
            if binding is None:
                missing_optional.append(kind)
            else:
                bindings.append(binding)

        # 선택 결손은 DEGRADED 까지만, 필수 결손만 DISABLED (AI-C-11).
        if missing_required:
            state = CapabilityState.DISABLED
        elif missing_optional:
            state = CapabilityState.DEGRADED
        else:
            state = CapabilityState.ACTIVE

        # 확인할 수 없는 사전조건은 참으로 가정하지 않는다 (AI-D-02).
        unverified = tuple(
            fact for fact in step.preconditions if context.known_facts.get(fact) is not True
        )
        violated = tuple(
            fact for fact in step.forbidden_if if context.known_facts.get(fact) is True
        )

        return Subtask(
            subtask_id=f"{context.zone_id}:{step.action}:{index}",
            zone_id=context.zone_id,
            action=step.action,
            order_index=index,
            state=state,
            bindings=tuple(bindings),
            missing_required_capabilities=tuple(missing_required),
            missing_optional_capabilities=tuple(missing_optional),
            unverified_preconditions=unverified,
            violated_forbidden_conditions=violated,
            resource_cost=step.cost,
        )

    def _bind(
        self,
        kind: str,
        context: DecompositionContext,
        executor: ExecutorCandidate | None,
        optional: bool,
    ) -> CapabilityBinding | None:
        """Resolve one capability kind to a concrete provider.

        Edge-local registry providers are tried first (they are cheaper to
        reason about and cost the executor nothing); an executor-hosted
        capability is the fallback. Returning None is a normal answer.
        """
        result = self._selector.select(kind, set(context.node_tags), context.budget)
        if result.provider is not None:
            return CapabilityBinding(kind, result.provider.provider_id, BindingSource.REGISTRY, optional)
        if executor is not None and kind in executor.capability_kinds:
            return CapabilityBinding(kind, executor.executor_id, BindingSource.EXECUTOR, optional)
        return None


# ---------------------------------------------------------------------------
# Validation (separate from generation — AI-D-02)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubtaskFinding:
    subtask_id: str
    executable: bool
    reasons: tuple[str, ...]
    missing_evidence: tuple[str, ...]


@dataclass(frozen=True)
class ValidationReport:
    plan_id: str
    valid: bool
    structural_errors: tuple[str, ...]
    findings: tuple[SubtaskFinding, ...]

    @property
    def missing_evidence(self) -> tuple[str, ...]:
        """Flattened, de-duplicated evidence gaps — feeds AI-D-03's
        `plan_for_validation_gaps` directly."""
        seen: list[str] = []
        for finding in self.findings:
            for ev in finding.missing_evidence:
                if ev not in seen:
                    seen.append(ev)
        return tuple(seen)


class SubtaskPlanValidator:
    """Re-derives executability from the plan + context, independently.

    This intentionally does not trust `Subtask.executable`: it recomputes
    structure, zone boundary, ordering, precondition and resource
    conditions from the same inputs so that a plan produced by *any*
    generator (including a future LLM-backed one) can be checked under one
    reproducible rule set (AI-D-02).
    """

    def validate(self, plan: SubtaskPlan, context: DecompositionContext) -> ValidationReport:
        structural: list[str] = []
        if not plan.plan_id:
            structural.append("empty_plan_id")
        if plan.goal_id != context.goal_id:
            structural.append("goal_id_mismatch")
        if not plan.subtasks:
            structural.append("no_subtasks")
        if plan.executor.executor_id is None:
            structural.append("no_executor_bound")

        seen_ids: set[str] = set()
        for expected_index, subtask in enumerate(plan.subtasks):
            if subtask.subtask_id in seen_ids:
                structural.append(f"duplicate_subtask_id:{subtask.subtask_id}")
            seen_ids.add(subtask.subtask_id)
            if subtask.order_index != expected_index:
                structural.append(f"order_index_gap:{subtask.subtask_id}")
            if subtask.zone_id != context.zone_id:
                structural.append(f"zone_boundary_violation:{subtask.subtask_id}")

        findings = tuple(self._check(subtask, context) for subtask in plan.subtasks)
        valid = not structural and all(f.executable for f in findings)
        return ValidationReport(plan.plan_id, valid, tuple(structural), findings)

    def _check(self, subtask: Subtask, context: DecompositionContext) -> SubtaskFinding:
        reasons: list[str] = []
        missing_evidence: list[str] = []

        for kind in subtask.missing_required_capabilities:
            reasons.append(f"missing_required_capability:{kind}")
            missing_evidence.append(kind)

        for fact in subtask.unverified_preconditions:
            reasons.append(f"unverified_precondition:{fact}")
            missing_evidence.append(fact)

        for fact in subtask.violated_forbidden_conditions:
            reasons.append(f"forbidden_condition_holds:{fact}")

        for key, floor in sorted(context.resource_floor.items()):
            have = context.executor_resources.get(key)
            if have is None:
                reasons.append(f"unknown_resource:{key}")
                missing_evidence.append(f"resource:{key}")
            elif have < floor:
                reasons.append(f"insufficient_resource:{key}")

        if not context.budget.can_afford(subtask.resource_cost):
            reasons.append("compute_budget_exceeded")

        return SubtaskFinding(
            subtask_id=subtask.subtask_id,
            executable=not reasons,
            reasons=tuple(reasons),
            missing_evidence=tuple(missing_evidence),
        )
