"""Turns a clicked function into the subtask node graph the console draws.

implements: AI-B-12 (작업 그래프 실행 상태 관리), AI-C-15 (goal kind 는 데이터)
관련: AI-C-05 (선택 결손은 축소까지), AI-B-13 (수행 불가 → 외부 요청 후보)

## 분해를 여기서 다시 만들지 않는다

서브태스크 산출은 `planning/decomposition.py` 의 `TaskDecomposer` 가 정본이다 —
템플릿·레지스트리·실행자·문맥만 보고 결정적으로 같은 답을 낸다(시계도 난수도 LLM 도
쓰지 않는다). 이 모듈이 하는 일은 셋뿐이다.

1. `profiles/goal_kinds.example.json` 을 `TaskTemplateLibrary` 로 싣는다.
2. 누른 (로봇, 구역, 기능) 을 `DecompositionContext` 로 옮긴다.
3. 나온 `SubtaskPlan` 에 **간선**을 붙여 그래프로 만든다.

## 간선은 자료 흐름에서 유도한다

모델이나 사람이 간선을 적지 않는다 — 각 단계가 무엇을 내고(`produces`) 무엇을
받는지(`consumes`) 만 데이터로 적고, 간선은 규칙이 계산한다. 어떤 단계가 `X` 를
받으면, `X` 를 내는 **가장 가까운 앞 단계**에서 간선이 온다. 같은 것을 내는 앞 단계가
없으면 그 입력은 `unmet_inputs` 로 남는다 — 조용히 이어 붙이지 않는다.

순서만 있는 사슬이 아니라 실제 의존 그래프가 나오는 이유가 이것이다. 예를 들어
`m10_dt_map_update` 에서 `submit_map_patch` 는 `structure` 와 `pose` 를 받으므로
`measure_structure` 와 `locate_self` 양쪽에서 간선이 온다.

## 실행 위치는 binding source 가 말한다

`CapabilityBinding.source` 가 `registry` 면 그 단계는 **로봇 위에서** 돈다(로봇의
태그·예산으로 provider 가 해소됐다). `executor` 면 **구역이 공급한다**(고정 카메라·
엣지가 내는 kind). 운영자가 알아야 하는 "이 단계는 어디서 도는가"가 그 값이다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from mission_runtime.contracts.capability import CapabilityRequirement, CapabilityState
from mission_runtime.contracts.profile import ResourceBudget, ResourceCost
from mission_runtime.planning.decomposition import (
    DecompositionContext,
    ExecutorCandidate,
    StepTemplate,
    SubtaskPlan,
    TaskDecomposer,
    TaskTemplate,
    TaskTemplateLibrary,
)
from mission_runtime.registry.capability_registry import CapabilityRegistry
from mission_runtime.registry.manifest import load_provider_manifest, register_all

#: 구역이 공급하는 capability 를 들고 있는 가상 실행자의 id 접두. 로봇이 아니라
#: 구역이 낸다는 사실을 화면에 그대로 적기 위한 이름이다.
ZONE_SUPPLY_PREFIX = "zone-supply"


class GoalKindError(ValueError):
    """goal kind 데이터를 읽을 수 없다."""


@dataclass(frozen=True)
class StepFlow:
    """한 단계의 자료 흐름. 코어 계약이 아니라 `params` 에 실려 오는 화면용 데이터다."""

    produces: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()


def _requirement(raw: Mapping[str, Any] | None) -> CapabilityRequirement:
    raw = raw or {}
    return CapabilityRequirement(
        required=tuple(raw.get("required", ())),
        optional=tuple(raw.get("optional", ())),
    )


def _cost(raw: Mapping[str, Any] | None) -> ResourceCost:
    raw = raw or {}
    return ResourceCost(
        compute_units=float(raw.get("compute_units", 0.0)),
        memory_mb=float(raw.get("memory_mb", 0.0)),
    )


def load_goal_kinds(path: str | Path) -> tuple[TaskTemplateLibrary, dict[str, str]]:
    """goal kind 데이터를 템플릿 라이브러리로 싣는다.

    두 번째 반환값은 `facts` 어휘의 뜻 — 화면이 사전조건을 사람 말로 적을 때 쓴다.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = raw.get("goal_kinds")
    if not isinstance(entries, list):
        raise GoalKindError("goal kind file needs a 'goal_kinds' list")

    library = TaskTemplateLibrary()
    for entry in entries:
        for key in ("goal_kind", "version", "steps"):
            if key not in entry:
                raise GoalKindError(f"goal kind entry missing {key!r}")
        steps = tuple(
            StepTemplate(
                action=step["action"],
                requirement=_requirement(step.get("requirement")),
                preconditions=tuple(step.get("preconditions", ())),
                forbidden_if=tuple(step.get("forbidden_if", ())),
                cost=_cost(step.get("cost")),
                params=dict(step.get("params", {})),
            )
            for step in entry["steps"]
        )
        library.register(TaskTemplate(
            goal_kind=entry["goal_kind"],
            version=str(entry["version"]),
            steps=steps,
            executor_requirement=_requirement(entry.get("executor_requirement")),
        ))

    facts = {k: v for k, v in (raw.get("facts") or {}).items() if not k.startswith("$")}
    return library, facts


def registry_from_manifest(path: str | Path) -> CapabilityRegistry:
    """실제 provider manifest 를 그대로 싣는다 — 데모용 가짜 등록이 아니다."""
    registry = CapabilityRegistry()
    register_all(load_provider_manifest(path), registry)
    return registry


def placement_registry(
    manifest_path: str | Path,
    placements: Iterable[tuple[str, str]],
) -> CapabilityRegistry:
    """**이미 배치된** (kind, provider) 만 담은 레지스트리를 만든다.

    왜 manifest 전체를 넘기지 않는가: `StatusService.fleet()` 은 노드 예산을
    **누적해서** 배치한다(먼저 놓인 kind 가 예산을 먹으면 다음 provider 는
    `over_budget` 으로 떨어진다). 반면 분해기의 `_bind` 는 kind 마다 전체 예산을
    다시 보므로, manifest 전체를 주면 "노드 상태 화면에서는 못 한다고 하는데
    서브태스크 화면에서는 된다고 하는" 모순이 생긴다. 배치의 정본은 `fleet()`
    하나이고, 분해는 그 결과를 소비한다.
    """
    wanted = {(kind, provider_id) for kind, provider_id in placements}
    registry = CapabilityRegistry()
    for registration in load_provider_manifest(manifest_path).registrations:
        if (registration.capability_kind, registration.provider_id) in wanted:
            registry.register_local(registration)
    return registry


def derive_edges(plan: SubtaskPlan, library: TaskTemplateLibrary, goal_kind: str
                 ) -> tuple[list[dict], dict[str, list[str]]]:
    """자료 흐름에서 간선을 계산한다.

    되돌아가는 간선은 만들지 않는다 — 입력을 내는 **앞** 단계만 본다. 그래서 결과는
    항상 비순환이고, 화면이 위상 정렬 없이 그대로 그릴 수 있다.
    """
    template = library.get(goal_kind)
    if template is None:
        return [], {}

    flows = [
        StepFlow(
            produces=tuple(step.params.get("produces", ())),
            consumes=tuple(step.params.get("consumes", ())),
        )
        for step in template.steps
    ]
    ids = [s.subtask_id for s in plan.subtasks]

    edges: list[dict] = []
    unmet: dict[str, list[str]] = {}
    for index, flow in enumerate(flows):
        if index >= len(ids):
            break
        for item in flow.consumes:
            producer = None
            for earlier in range(index - 1, -1, -1):
                if item in flows[earlier].produces:
                    producer = earlier
                    break
            if producer is None:
                unmet.setdefault(ids[index], []).append(item)
                continue
            edges.append({"from": ids[producer], "to": ids[index], "item": item})
    return edges, unmet


@dataclass
class SubtaskGraphBuilder:
    """(로봇, 구역, 기능) → 서브태스크 그래프."""

    library: TaskTemplateLibrary
    registry: CapabilityRegistry
    facts_vocabulary: Mapping[str, str]

    def build(
        self,
        *,
        goal_kind: str,
        goal_id: str,
        zone_id: str,
        robot_id: str,
        robot_tags: Iterable[str],
        budget: ResourceBudget,
        zone_supplied_kinds: Iterable[str],
        known_facts: Mapping[str, bool],
    ) -> dict:
        decomposer = TaskDecomposer(self.registry, self.library)
        context = DecompositionContext(
            goal_id=goal_id,
            goal_kind=goal_kind,
            zone_id=zone_id,
            node_tags=frozenset(robot_tags),
            budget=budget,
            known_facts=dict(known_facts),
        )
        # 구역이 공급하는 kind 를 실행자 후보로 넘긴다 — 로봇이 못 내는 단계가
        # 구역 덕분에 되는 경우를 source=executor 로 구분해 보여 준다.
        supply = tuple(sorted(set(zone_supplied_kinds)))
        candidates = [ExecutorCandidate(
            executor_id=f"{ZONE_SUPPLY_PREFIX}:{zone_id}",
            capability_kinds=frozenset(supply),
        )]
        plan = decomposer.decompose(context, candidates)
        edges, unmet = derive_edges(plan, self.library, goal_kind)

        nodes = []
        for subtask in plan.subtasks:
            nodes.append({
                "subtask_id": subtask.subtask_id,
                "action": subtask.action,
                "order_index": subtask.order_index,
                "state": subtask.state.value,
                "executable": subtask.executable,
                "runs_on": sorted({
                    ("robot" if b.source.value == "registry" else "zone")
                    for b in subtask.bindings
                }),
                "bindings": [
                    {"capability_kind": b.capability_kind, "provider_id": b.provider_id,
                     "source": b.source.value, "optional": b.optional}
                    for b in subtask.bindings
                ],
                "missing_required": list(subtask.missing_required_capabilities),
                "missing_optional": list(subtask.missing_optional_capabilities),
                "unverified_preconditions": [
                    {"fact": f, "means": self.facts_vocabulary.get(f)}
                    for f in subtask.unverified_preconditions
                ],
                "violated_forbidden": list(subtask.violated_forbidden_conditions),
                "unmet_inputs": unmet.get(subtask.subtask_id, []),
                "cost": {"compute_units": subtask.resource_cost.compute_units,
                         "memory_mb": subtask.resource_cost.memory_mb},
            })

        blocked_kinds = sorted({
            kind for subtask in plan.subtasks
            for kind in subtask.missing_required_capabilities
        })
        return {
            "plan_id": plan.plan_id,
            "goal_id": plan.goal_id,
            "goal_kind": goal_kind,
            "zone_id": zone_id,
            "robot_id": robot_id,
            "generator": plan.generator,
            "template_version": plan.template_version,
            "reason": plan.reason,
            "executor": {
                "executor_id": plan.executor.executor_id,
                "state": plan.executor.state.value,
                "reason": plan.executor.reason,
            },
            "nodes": nodes,
            "edges": edges,
            # 필수 kind 가 없어 막힌 단계가 있으면 그것이 외부 개발 요청 후보다(AI-B-13).
            "escalation_capabilities": blocked_kinds,
            "cost_total": {
                "compute_units": round(sum(n["cost"]["compute_units"] for n in nodes), 3),
                "memory_mb": round(sum(n["cost"]["memory_mb"] for n in nodes), 1),
            },
        }
