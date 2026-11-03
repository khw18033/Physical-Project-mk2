"""Consumes an externally generated mission plan (mission → milestones → tasks)
and turns it into a `TaskGraph` without re-deriving the plan.

implements: AI-B-12 (작업 그래프 실행 상태 관리)
관련: AI-C-01 (공통 데이터 규약), AI-C-19 (판단·권한 경계), AI-O-06 (통합 상태 뷰)

**생성은 우리 일이 아니다.** 미션을 마일스톤·태스크로 분해하는 계약은 생성 주체
(가시화 파트)가 소유한다(2026-10-27 결정: "우리가 소비"). 이 모듈은 그 계약을 읽어
실행 상태 관리용 그래프로 환산하는 **어댑터 한 장**이고, 분해 규칙을 다시 구현하지
않는다. 생성 계약이 바뀌면 이 파일만 고친다 — 그것이 어댑터를 둔 이유다.

환산 규칙과 그 근거
-------------------
입력 계약의 어휘가 표시 어휘보다 넓다. 그래서 **환산과 보존을 함께** 한다 —
`TaskNode.state` 는 표시용 6종으로 환산하고 `source_status` 에 원본 문자열을 그대로
남긴다. 되짚을 수 없는 환산은 하지 않는다.

    pending              → PENDING
    running              → EXECUTING
    rerunning            → EXECUTING   (회차는 attempt 가 들고 있다)
    awaiting_evaluation  → EXECUTING   (아직 종단이 아니다)
    done                 → SUCCEEDED
    failed               → FAILED
    skipped              → SKIPPED_BY_PLAN     (표시 어휘 밖 — 아래 설명)
    not_executed         → SKIPPED_BY_PLAN

`skipped` / `not_executed` 는 "분기에서 선택되지 않아 애초에 돌지 않는다"는 뜻이고
기능정의서의 6상태에 대응이 없다. 둘을 `PENDING` 으로 접으면 화면이 영원히 오지 않는
차례를 기다리는 노드로 그리고, `FAILED` 로 접으면 실패하지 않은 것을 실패로 센다.
그래서 표시 어휘를 늘리지 않고 **그래프에서 제외 가능한 별도 표식**으로 둔다 —
`PlanImport.skipped_node_ids` 가 그것이고, 그 노드는 그래프에 넣지 않는다. 화면이
갈래 전체를 보여야 한다면 이 목록을 함께 받는다.

관계 환산:

- `task.deps` → `depends_on` (결과 의존, 점선). 입력 계약이 쓴 그대로다.
- 마일스톤 순서 → `order_after` (실행 순서, 실선). 입력 계약이 "분기가 없으면 앞
  마일스톤 뒤에 그냥 이어진다"고 정했으므로, 앞 마일스톤의 **종단 태스크**(그 안에서
  아무도 의존하지 않는 태스크)를 선행으로 잇는다. 전체를 잇지 않는 이유는 간선 수가
  태스크 수의 곱으로 늘어 그래프가 읽히지 않기 때문이다.
- `branch` / `repeat_of` → `ReferenceEdge`. **`depends_on` 에 넣지 않는다** — 되풀이는
  순환이고 선행 관계가 아니다.
- 같은 마일스톤 안에서 선행 집합이 동일한 태스크들 → 같은 `parallel_group`. 입력 계약이
  "병렬은 제약이 없어서 남는 것"이라고 정의했으므로 병렬은 선언이 아니라 **파생**이다.
- `derived_from` → `origin_node_id` (재실행 계보).
- `target` → `target_device_id`. 장비이고 가속기가 아니다.
- `node_kind` → `node_kind` (자유 문자열, 분기 근거로 쓰지 않는다).

입력에 있는데 환산 대상이 아닌 것(`action_items`, `evaluation`, `assigned_targets`,
`utterance.confidence_signals` 등)은 버리지 않고 `PlanImport.unmapped` 에 경로로
남긴다. 조용히 사라지면 다음 사람이 그 계약을 다시 읽어야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mission_runtime.execution.task_graph import (
    NodeState,
    ReferenceEdge,
    TaskGraph,
    TaskNode,
)

#: 입력 계약의 상태 → 표시용 6종. 표에 없는 값은 환산하지 않고 거부한다(조용히
#: PENDING 으로 떨어뜨리면 새 상태가 생긴 것을 아무도 모른다).
STATUS_MAP: dict[str, NodeState] = {
    "pending": NodeState.PENDING,
    "running": NodeState.EXECUTING,
    "rerunning": NodeState.EXECUTING,
    "awaiting_evaluation": NodeState.EXECUTING,
    "done": NodeState.SUCCEEDED,
    "failed": NodeState.FAILED,
}

#: 그래프에서 제외하는 상태. 분기에서 선택되지 않은 갈래다.
SKIPPED_STATUSES: frozenset[str] = frozenset({"skipped", "not_executed"})


class PlanInvalid(Exception):
    """입력 계약을 읽을 수 없다. 필수 칸 누락이나 모르는 상태 어휘."""


@dataclass(frozen=True)
class PlanImport:
    """환산 결과와 환산하지 못한 것.

    `unmapped` 와 `skipped_node_ids` 가 비어 있지 않은 것은 오류가 아니다 — 입력
    계약이 더 많은 것을 담고 있다는 사실의 기록이다.
    """

    graph: TaskGraph
    mission_id: str
    utterance_text: str | None = None
    #: 분기에서 선택되지 않아 그래프에 넣지 않은 태스크. (task_id, 원본 상태)
    skipped_node_ids: tuple[tuple[str, str], ...] = ()
    #: 환산 대상이 아니었던 입력 경로. 예: "milestones[0].tasks[2].evaluation"
    unmapped: tuple[str, ...] = field(default_factory=tuple)


def _require(mapping: object, key: str, where: str):
    if not isinstance(mapping, dict) or key not in mapping:
        raise PlanInvalid(f"{where}: missing required key {key!r}")
    return mapping[key]


def task_graph_from_plan(plan: dict) -> PlanImport:
    """외부 미션 계획 한 건을 그래프로 환산한다.

    입력을 바꾸지 않고 읽기만 한다. 같은 입력이면 같은 결과가 나온다(정렬된 순회).
    """
    mission_id = _require(plan, "mission_id", "mission")
    if not isinstance(mission_id, str) or not mission_id:
        raise PlanInvalid("mission.mission_id must be a non-empty string")

    utterance = plan.get("utterance")
    utterance_text: str | None = None
    unmapped: list[str] = []
    if isinstance(utterance, dict):
        raw = utterance.get("text")
        utterance_text = raw if isinstance(raw, str) else None
        unmapped += [f"utterance.{k}" for k in sorted(utterance) if k != "text"]

    milestones = _require(plan, "milestones", "mission")
    if not isinstance(milestones, list):
        raise PlanInvalid("mission.milestones must be a list")

    ordered = sorted(
        enumerate(milestones),
        key=lambda pair: (pair[1].get("order", pair[0]) if isinstance(pair[1], dict)
                          else pair[0], pair[0]),
    )

    nodes: list[TaskNode] = []
    skipped: list[tuple[str, str]] = []
    reference_edges: list[ReferenceEdge] = []
    # 마일스톤별 (태스크 id, 그 안에서 아무도 의존하지 않는 종단 태스크 id)
    per_milestone: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
    first_task_of: dict[str, str] = {}
    last_task_of: dict[str, str] = {}

    for m_index, milestone in ordered:
        where = f"milestones[{m_index}]"
        if not isinstance(milestone, dict):
            raise PlanInvalid(f"{where}: must be an object")
        milestone_id = _require(milestone, "milestone_id", where)
        tasks = _require(milestone, "tasks", where)
        if not isinstance(tasks, list):
            raise PlanInvalid(f"{where}.tasks must be a list")
        unmapped += [
            f"{where}.{k}" for k in sorted(milestone)
            if k not in ("milestone_id", "tasks", "order", "branch", "repeat_of", "status",
                         "title")
        ]

        live_ids: list[str] = []
        dep_targets: set[str] = set()
        for t_index, task in enumerate(tasks):
            t_where = f"{where}.tasks[{t_index}]"
            if not isinstance(task, dict):
                raise PlanInvalid(f"{t_where}: must be an object")
            task_id = _require(task, "task_id", t_where)
            status = _require(task, "status", t_where)
            if status in SKIPPED_STATUSES:
                skipped.append((task_id, status))
                continue
            if status not in STATUS_MAP:
                raise PlanInvalid(
                    f"{t_where}: unknown status {status!r}; "
                    f"known: {sorted(STATUS_MAP) + sorted(SKIPPED_STATUSES)}"
                )
            deps = tuple(task.get("deps") or ())
            dep_targets.update(deps)
            live_ids.append(task_id)
            unmapped += [
                f"{t_where}.{k}" for k in sorted(task)
                if k not in ("task_id", "title", "deps", "status", "attempt",
                             "derived_from", "node_kind", "target")
            ]
            nodes.append(
                TaskNode(
                    node_id=task_id,
                    title=task.get("title") or task_id,
                    state=STATUS_MAP[status],
                    source_status=status,
                    depends_on=deps,
                    attempt=int(task.get("attempt") or 1),
                    origin_node_id=task.get("derived_from") or None,
                    target_device_id=task.get("target") or None,
                    node_kind=task.get("node_kind") or None,
                )
            )

        terminals = tuple(t for t in live_ids if t not in dep_targets)
        per_milestone.append((milestone_id, tuple(live_ids), terminals or tuple(live_ids)))
        if live_ids:
            first_task_of[milestone_id] = live_ids[0]
            last_task_of[milestone_id] = live_ids[-1]

        for edge_key, kind in (("branch", "branch"), ("repeat_of", "repeat")):
            spec = milestone.get(edge_key)
            if isinstance(spec, dict):
                other = spec.get("from") or spec.get("to")
                when = spec.get("when")
                if other is not None:
                    reference_edges.append(
                        ReferenceEdge(
                            from_node_id=other if edge_key == "branch" else milestone_id,
                            to_node_id=milestone_id if edge_key == "branch" else other,
                            kind=kind,
                            when=when,
                        )
                    )

    # 마일스톤 사이 실행 순서: 앞 마일스톤의 종단 태스크 → 뒤 마일스톤의 시작 태스크
    by_id = {n.node_id: n for n in nodes}
    for (prev_id, _prev_live, prev_terms), (cur_id, cur_live, _cur_terms) in zip(
        per_milestone, per_milestone[1:]
    ):
        del prev_id, cur_id
        for task_id in cur_live:
            node = by_id[task_id]
            if node.depends_on:
                continue    # 명시된 결과 의존이 있으면 순서를 덧씌우지 않는다
            by_id[task_id] = TaskNode(
                **{**node.__dict__, "order_after": tuple(prev_terms)}
            )

    nodes = [by_id[n.node_id] for n in nodes]

    # 병렬 그룹은 파생이다: 같은 마일스톤 안에서 선행 집합이 같으면 한 그룹
    for milestone_id, live, _terms in per_milestone:
        groups: dict[tuple[str, ...], list[str]] = {}
        for task_id in live:
            node = by_id[task_id]
            groups.setdefault(node.predecessors, []).append(task_id)
        for key, members in groups.items():
            del key
            if len(members) < 2:
                continue
            group_name = f"{milestone_id}:par{live.index(members[0])}"
            for task_id in members:
                node = by_id[task_id]
                by_id[task_id] = TaskNode(
                    **{**node.__dict__, "parallel_group": group_name}
                )

    nodes = [by_id[n.node_id] for n in nodes]

    # 참조 간선은 마일스톤 id 로 왔다 — 태스크 id 로 옮긴다(그려지는 단위가 태스크다)
    resolved: list[ReferenceEdge] = []
    for edge in reference_edges:
        src = last_task_of.get(edge.from_node_id)
        dst = first_task_of.get(edge.to_node_id)
        if src is None or dst is None:
            unmapped.append(f"reference_edge({edge.kind}):{edge.from_node_id}->{edge.to_node_id}")
            continue
        resolved.append(ReferenceEdge(src, dst, edge.kind, edge.when))

    graph = TaskGraph(
        mission_id=mission_id,
        nodes=tuple(nodes),
        reference_edges=tuple(resolved),
    )
    return PlanImport(
        graph=graph,
        mission_id=mission_id,
        utterance_text=utterance_text,
        skipped_node_ids=tuple(skipped),
        unmapped=tuple(dict.fromkeys(unmapped)),
    )
