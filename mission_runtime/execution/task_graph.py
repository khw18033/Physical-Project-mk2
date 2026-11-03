"""Task graph with a runtime node state machine, re-execution lineage and a
deterministic focus rule.

implements: AI-B-12 (작업 그래프 실행 상태 관리)
관련: AI-B-03 (실행 제어와 물리 명령의 분리), AI-C-19 (판단·권한 경계),
      AI-C-05 (선택 기능 결손은 축소이지 실패가 아니다)

요구사항 출처는 `docs/20260928-종합상황정보_Dashboard_기능정의서_2.docx` §2·§4.1·§4.2·§4.6
이며, 2026-10-27 에 그 요구를 AI-B-12 로 요구사항 시트에 등재했다(CLAUDE.md §5).

왜 새 모듈인가
--------------
`planning/decomposition.py` 는 "지금 무엇을 실행할 수 있는가"를 capability 기준으로
낸다 — 그 결과의 `state` 는 `CapabilityState`(ACTIVE/DEGRADED/DISABLED)이고 **실행
진행 상태가 아니다**. `ondevice/mission_cache.py` 의 `ItemProgress` 는 말단 한 대의
진행만 본다. 대시보드가 요구하는 것은 그 둘과 다른 세 번째 축이다: 미션 하나가 분해된
**노드들의 구조(의존·병렬)와 런타임 상태**. 기존 두 축에 상태를 더 끼워 넣으면
"가용성 / 진행 / 결과"를 섞지 말라는 기존 경계(AI-B-05, AI-O-04)가 깨지므로 분리한다.

조회 전용 (문서 §1.1·§5)
------------------------
모든 자료구조가 frozen 이고 상태 전이는 **새 그래프를 반환**한다. 화면이 들고 있는
스냅샷을 제자리에서 바꿀 수 없으므로 "화면의 어떠한 조작도 실행 상태를 변경하지
않는다"가 타입 수준에서 성립한다.

도메인 중립 (절대 준수 원칙 #3)
-------------------------------
노드 제목·서비스 id·가속기 id 는 전부 호출자가 주는 자유 문자열이다. 이 모듈에는
`VLA`·`VLM`·로봇·하천 같은 이름이 없고 노드 수·깊이·분기 수에 대한 상한도 없다
(문서 §4.2 "시나리오 일반성": 예시 그래프를 화면에 고정하지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum


class NodeState(str, Enum):
    """문서 §4.2 "노드 상태 정의" 6종을 그대로 쓴다.

    PENDING            대기 중 — 선행 조건이 아직 도래하지 않음
    BLOCKED            대기(의존) — 선행 노드의 결과를 기다리는 중
    EXECUTING          실행 중 — 담당 서비스에서 수행 중
    SUCCEEDED          완료 — 완료 조건 충족
    FAILED             실패/주의 — 실패 조건 충족 또는 임계값 이탈
    EXTERNAL_REQUESTED 외부 기능 요청 중 — 서버로 기능 요청이 발신되어 배포 대기

    `BLOCKED` 를 `PENDING` 과 합치지 않는 이유: 문서가 둘을 다른 색으로 요구하고,
    운영자가 "아직 차례가 아니다"와 "앞의 결과를 기다린다"를 구분해야 어디서
    멈췄는지 알 수 있다.
    """

    PENDING = "PENDING"
    BLOCKED = "BLOCKED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    EXTERNAL_REQUESTED = "EXTERNAL_REQUESTED"

    @property
    def is_terminal(self) -> bool:
        return self in (NodeState.SUCCEEDED, NodeState.FAILED)

    @property
    def needs_attention(self) -> bool:
        """문서 §4.2: 실패·주의와 외부 요청 노드는 다른 상태보다 우선 인지."""
        return self in (NodeState.FAILED, NodeState.EXTERNAL_REQUESTED)


#: 허용 전이. 여기 없는 전이는 거부한다 — 화면이 보는 상태가 임의로 뒤집히면
#: "같은 사실이 여러 구역에서 상충하지 않는다"(문서 §5 상태 일관성)를 지킬 수 없다.
_ALLOWED: dict[NodeState, frozenset[NodeState]] = {
    NodeState.PENDING: frozenset({NodeState.BLOCKED, NodeState.EXECUTING, NodeState.FAILED}),
    NodeState.BLOCKED: frozenset({NodeState.PENDING, NodeState.EXECUTING, NodeState.FAILED}),
    NodeState.EXECUTING: frozenset(
        {NodeState.SUCCEEDED, NodeState.FAILED, NodeState.EXTERNAL_REQUESTED}
    ),
    NodeState.FAILED: frozenset({NodeState.EXTERNAL_REQUESTED}),
    NodeState.EXTERNAL_REQUESTED: frozenset({NodeState.FAILED, NodeState.SUCCEEDED}),
    NodeState.SUCCEEDED: frozenset(),
}

#: 외부(온디바이스 아님)에서 수행되는 노드의 실행 가속기 표기. 문서 §4.6:
#: "온디바이스 가속기에서 수행되지 않는 노드는 실행 가속기 항목에 온디바이스
#: 외부임을 명시한다." 값은 id 가 아니라 통제 어휘다.
OFF_DEVICE = "off_device"

#: 자동 추종이 기준 노드를 고른 사유 토큰. 화면은 문자열을 그대로 쓰지 않고
#: 이 토큰으로 라벨을 찾는다(언어 중립).
FOCUS_REASON_PINNED = "focus_pinned_by_operator"
FOCUS_REASON_ATTENTION = "focus_attention_first"
FOCUS_REASON_LATEST_EXECUTING = "focus_latest_executing"
FOCUS_REASON_NO_CANDIDATE = "focus_no_candidate"

FOCUS_REASONS: tuple[str, ...] = (
    FOCUS_REASON_PINNED,
    FOCUS_REASON_ATTENTION,
    FOCUS_REASON_LATEST_EXECUTING,
    FOCUS_REASON_NO_CANDIDATE,
)


class TransitionRejected(Exception):
    """허용되지 않은 상태 전이. 거부는 예외이고 상태가 아니다 — 거부를 노드
    상태로 섞으면 AI-C-20 이 수락 결과와 실행 상태를 가른 것과 같은 혼동이 난다."""


class GraphInvalid(Exception):
    """구조 자체가 성립하지 않는 그래프(미지 선행 노드, 순환)."""


@dataclass(frozen=True)
class TaskNode:
    """실행 단위 1개 (문서 §4.2 "노드", §4.6 "선택 노드 상세").

    담당 서비스(L2)와 실행 가속기(L1)를 **별도 필드로 둔다** — 문서 §4.6 이
    "하나의 '수행 위치' 항목으로 합쳐서는 안 된다"고 명시한다. 둘 다 선택이며
    아직 배정되지 않은 노드는 None 이다(모르면 0 이 아니라 없음).
    """

    node_id: str
    title: str
    state: NodeState = NodeState.PENDING
    #: L2 담당 서비스 식별자. 배정 전이면 None.
    service_id: str | None = None
    #: L1 실행 가속기 식별자, 또는 OFF_DEVICE. 배정 전이면 None.
    accelerator_id: str | None = None
    #: 상태가 이 값으로 바뀐 시각(epoch seconds). 문서 §4.2 "상태 전이 시각".
    state_changed_at: float | None = None
    started_at: float | None = None
    #: 잔여 예상 소요가 아니라 예상 완료 시각으로 들고 있는다 — 화면이 경과를
    #: 실시간으로 늘리는 쪽이고, 잔여값을 재전송하면 두 값이 어긋난다.
    estimated_completion_at: float | None = None
    #: 0.0~1.0. 측정 수단이 없으면 None 이며 화면은 "측정 없음"으로 적는다.
    progress_ratio: float | None = None
    #: 이 노드에 전달된 명령/지시문 원문. 문서 §4.6: "생략되어서는 안 된다."
    input_command: str | None = None
    #: 실행 순서(실선). 선행 노드가 끝나야 시작하지만 결과에 종속되지는 않는다.
    order_after: tuple[str, ...] = ()
    #: 의존 관계(점선). 선행 노드의 **결과**에 종속된다.
    depends_on: tuple[str, ...] = ()
    #: 동시 실행 묶음. 같은 값이면 한 그룹으로 묶어 그린다.
    parallel_group: str | None = None
    #: 재실행 회차. 원 노드는 1.
    attempt: int = 1
    #: 재실행 노드가 가리키는 원 노드. 원 노드는 None — 원 실패 노드의 이력이
    #: 소실되지 않도록 재실행은 **새 노드**로 만든다(문서 §4.2·§4.8).
    origin_node_id: str | None = None
    #: 외부 기능 요청 식별자. 발급 주체는 백엔드이고 여기서는 받아 싣는 자리다
    #: (AI-C-19 — AI 는 요청 사유·필요 정보만 내고 발급하지 않는다).
    external_request_id: str | None = None
    #: 생성 주체가 쓴 원본 상태 문자열. 생성 측 어휘가 표시 어휘(6종)보다 넓을 때
    #: 손실 없이 보존한다(AI-B-12) — 환산 때문에 원본이 사라지면 어느 쪽이 맞는지
    #: 되짚을 수 없다.
    source_status: str | None = None
    #: 이 작업을 수행하는 **장비** 식별자. 서비스(L2)·가속기(L1)와 다른 축이다 —
    #: 어느 로봇이 하는가와 어느 연산기에서 도는가는 같은 질문이 아니다.
    target_device_id: str | None = None
    #: 생성 주체가 붙인 노드 문법 라벨(관측·판단·행동·검증·보고 등). 자유 문자열이며
    #: 이 모듈은 값으로 분기하지 않는다.
    node_kind: str | None = None

    def __post_init__(self) -> None:
        if not self.node_id:
            raise GraphInvalid("node_id must not be empty")
        if self.attempt < 1:
            raise GraphInvalid(f"attempt must be >= 1: {self.attempt}")
        if self.progress_ratio is not None and not 0.0 <= self.progress_ratio <= 1.0:
            raise GraphInvalid(f"progress_ratio out of range: {self.progress_ratio}")
        if self.node_id in self.order_after or self.node_id in self.depends_on:
            raise GraphInvalid(f"node depends on itself: {self.node_id}")

    @property
    def predecessors(self) -> tuple[str, ...]:
        """순서·의존을 합친 선행 노드. 중복은 한 번만 센다."""
        seen: list[str] = []
        for nid in self.order_after + self.depends_on:
            if nid not in seen:
                seen.append(nid)
        return tuple(seen)

    @property
    def is_re_execution(self) -> bool:
        return self.origin_node_id is not None


@dataclass(frozen=True)
class StateCounts:
    """문서 §4.1 "상태별 노드 수". 그래프에서 파생하므로 그래프와 어긋날 수 없다."""

    total: int
    by_state: dict[str, int]

    @property
    def attention(self) -> int:
        """실패·주의 + 외부 요청. 1건 이상이면 화면이 강조한다(문서 §4.1)."""
        return self.by_state.get(NodeState.FAILED.value, 0) + self.by_state.get(
            NodeState.EXTERNAL_REQUESTED.value, 0
        )


@dataclass(frozen=True)
class Focus:
    """기준 노드와 그 선정 사유 (문서 §2 "핵심 상호작용 원칙")."""

    node_id: str | None
    pinned: bool
    reason: str


@dataclass(frozen=True)
class ReferenceEdge:
    """DAG 에 넣지 않는 참조 간선 — 분기와 되풀이.

    선행 관계가 아니라 **판정 결과로 갈라지거나 되돌아가는** 관계다. `depends_on` 에
    넣으면 되풀이가 순환이 되어 깊이 계산이 무한 재귀한다(생성 주체가 같은 이유로
    분리해 둔 것을 그대로 받는다). 그래서 순환 검사 대상에서 제외한다.
    """

    from_node_id: str
    to_node_id: str
    #: "branch"(판정 결과로 갈라짐) / "repeat"(되돌아감) 등. 자유 문자열이다.
    kind: str
    #: 어느 판정 결과일 때인가. 생성 주체의 어휘를 그대로 쓴다.
    when: str | None = None


@dataclass(frozen=True)
class TaskGraph:
    """미션 하나가 분해된 노드 집합. 구조는 런타임에 받은 그대로 담는다.

    노드 수·깊이·병렬 분기 수에 상한을 두지 않는다 — 문서 §4.2 가 "특정 작업명이나
    특정 노드 수를 전제로 한 레이아웃 구현은 허용되지 않는다"고 한 요구의 자료구조
    쪽 대응이다.
    """

    mission_id: str
    nodes: tuple[TaskNode, ...]
    #: 운영자가 고정한 노드. None 이면 자동 추종.
    pinned_node_id: str | None = None
    #: 분기·되풀이 참조 간선. 순환 검사와 `ready()` 판정에 들어가지 않는다.
    reference_edges: tuple[ReferenceEdge, ...] = ()

    def __post_init__(self) -> None:
        ids = [n.node_id for n in self.nodes]
        if len(ids) != len(set(ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise GraphInvalid(f"duplicate node ids: {dupes}")
        known = set(ids)
        for node in self.nodes:
            unknown = [p for p in node.predecessors if p not in known]
            if unknown:
                raise GraphInvalid(f"{node.node_id} references unknown nodes: {unknown}")
            if node.origin_node_id is not None and node.origin_node_id not in known:
                raise GraphInvalid(
                    f"{node.node_id} re-executes unknown node: {node.origin_node_id}"
                )
        if self.pinned_node_id is not None and self.pinned_node_id not in known:
            raise GraphInvalid(f"pinned node not in graph: {self.pinned_node_id}")
        for edge in self.reference_edges:
            missing = [n for n in (edge.from_node_id, edge.to_node_id) if n not in known]
            if missing:
                raise GraphInvalid(f"reference edge references unknown nodes: {missing}")
        self._assert_acyclic(known)

    def _assert_acyclic(self, known: set[str]) -> None:
        colour: dict[str, int] = {nid: 0 for nid in known}
        preds = {n.node_id: n.predecessors for n in self.nodes}

        def visit(nid: str, trail: tuple[str, ...]) -> None:
            if colour[nid] == 1:
                cycle = list(trail[trail.index(nid):]) + [nid]
                raise GraphInvalid(f"dependency cycle: {' -> '.join(cycle)}")
            if colour[nid] == 2:
                return
            colour[nid] = 1
            for p in preds[nid]:
                visit(p, trail + (nid,))
            colour[nid] = 2

        for nid in sorted(known):
            visit(nid, ())

    # -- 조회 ------------------------------------------------------------

    def node(self, node_id: str) -> TaskNode:
        for n in self.nodes:
            if n.node_id == node_id:
                return n
        raise KeyError(node_id)

    def state_counts(self) -> StateCounts:
        by_state = {s.value: 0 for s in NodeState}
        for n in self.nodes:
            by_state[n.state.value] += 1
        return StateCounts(total=len(self.nodes), by_state=by_state)

    def executing(self) -> tuple[TaskNode, ...]:
        return tuple(n for n in self.nodes if n.state is NodeState.EXECUTING)

    def attention_nodes(self) -> tuple[TaskNode, ...]:
        return tuple(n for n in self.nodes if n.state.needs_attention)

    def parallel_groups(self) -> dict[str, tuple[str, ...]]:
        groups: dict[str, list[str]] = {}
        for n in self.nodes:
            if n.parallel_group is not None:
                groups.setdefault(n.parallel_group, []).append(n.node_id)
        return {g: tuple(ids) for g, ids in sorted(groups.items())}

    def attempts_of(self, node_id: str) -> tuple[TaskNode, ...]:
        """한 논리 작업의 회차 전체를 오래된 순으로. 원 노드와 그 재실행들을 잇는다.

        문서 §4.8: "재실행이 이전 회차의 로그를 덮어써서는 안 된다." 회차를 별
        노드로 두고 이 함수로 묶으면 원 노드가 그대로 남는다.
        """
        root = node_id
        seen: set[str] = set()
        while True:
            node = self.node(root)
            if node.origin_node_id is None or node.origin_node_id in seen:
                break
            seen.add(root)
            root = node.origin_node_id
        chain = [self.node(root)]
        changed = True
        while changed:
            changed = False
            have = {n.node_id for n in chain}
            for n in self.nodes:
                if n.origin_node_id in have and n.node_id not in have:
                    chain.append(n)
                    changed = True
        return tuple(sorted(chain, key=lambda n: (n.attempt, n.node_id)))

    def ready(self, node_id: str) -> bool:
        """선행 노드가 모두 완료됐는가. 실패·외부요청은 완료가 아니다."""
        node = self.node(node_id)
        return all(self.node(p).state is NodeState.SUCCEEDED for p in node.predecessors)

    # -- 기준 노드 -------------------------------------------------------

    def focus(self) -> Focus:
        """기준 노드를 정한다 (문서 §2).

        수동 고정이 있으면 그것이고, 없으면 자동 추종이다. 문서가 "실행 중인
        노드가 복수(병렬)인 경우 자동 추종의 선택 기준을 정의해야 한다"고 요구하므로
        규칙을 여기 한 곳에 못박고 사유 토큰으로 드러낸다.

            1) 주의가 필요한 노드(실패·주의 / 외부 요청 중)가 있으면 그것부터.
               문서 §4.2 가 그 둘을 다른 상태보다 우선 인지하도록 요구한다.
            2) 없으면 실행 중 노드 중 **상태 전이가 가장 최근인** 것.
            3) 동률이면 node_id 사전순 — 같은 입력이면 항상 같은 노드를 고른다
               (화면이 깜빡이지 않게 하려면 결정적이어야 한다).
            4) 후보가 없으면 None 이고 사유를 남긴다.
        """
        if self.pinned_node_id is not None:
            return Focus(self.pinned_node_id, True, FOCUS_REASON_PINNED)

        def newest(candidates: tuple[TaskNode, ...]) -> TaskNode:
            return sorted(
                candidates,
                key=lambda n: (-(n.state_changed_at or 0.0), n.node_id),
            )[0]

        attention = self.attention_nodes()
        if attention:
            return Focus(newest(attention).node_id, False, FOCUS_REASON_ATTENTION)
        running = self.executing()
        if running:
            return Focus(newest(running).node_id, False, FOCUS_REASON_LATEST_EXECUTING)
        return Focus(None, False, FOCUS_REASON_NO_CANDIDATE)

    # -- 전이 (항상 새 그래프를 반환) ------------------------------------

    def pin(self, node_id: str | None) -> TaskGraph:
        """수동 고정 / 고정 해제. 고정 해제는 자동 추종으로의 복귀다(문서 §2)."""
        return replace(self, pinned_node_id=node_id)

    def transition(
        self,
        node_id: str,
        to: NodeState,
        *,
        at: float | None = None,
        progress_ratio: float | None = None,
        estimated_completion_at: float | None = None,
        external_request_id: str | None = None,
    ) -> TaskGraph:
        """한 노드의 상태를 바꾼 **새 그래프**를 돌려준다.

        관측 변화가 없는데 레코드를 임의로 바꾸지 않는다 — 같은 상태로의 전이는
        거부한다(no-op 을 전이로 기록하면 상태 전이 시각이 의미를 잃는다).
        """
        node = self.node(node_id)
        if to not in _ALLOWED[node.state]:
            raise TransitionRejected(
                f"{node_id}: {node.state.value} -> {to.value} is not allowed"
            )
        if to is NodeState.EXTERNAL_REQUESTED and external_request_id is None:
            raise TransitionRejected(
                f"{node_id}: EXTERNAL_REQUESTED needs an external_request_id"
            )
        updated = replace(
            node,
            state=to,
            state_changed_at=at if at is not None else node.state_changed_at,
            started_at=(at if to is NodeState.EXECUTING and node.started_at is None
                        else node.started_at),
            progress_ratio=(progress_ratio if progress_ratio is not None
                            else (1.0 if to is NodeState.SUCCEEDED else node.progress_ratio)),
            estimated_completion_at=(estimated_completion_at
                                     if estimated_completion_at is not None
                                     else node.estimated_completion_at),
            external_request_id=(external_request_id if external_request_id is not None
                                 else node.external_request_id),
        )
        return replace(self, nodes=tuple(updated if n.node_id == node_id else n
                                        for n in self.nodes))

    def add_re_execution(
        self,
        origin_node_id: str,
        *,
        node_id: str,
        at: float | None = None,
        service_id: str | None = None,
        accelerator_id: str | None = None,
    ) -> TaskGraph:
        """실패했거나 외부 요청 중이던 노드를 다시 수행할 **새 노드**를 더한다.

        원 노드는 그대로 남고 회차가 1 늘어난다. 문서 §4.2: "재실행 노드는 원 노드와
        구분 가능해야 한다 ... 원 실패 노드의 이력이 소실되어서는 안 된다."
        """
        origin = self.node(origin_node_id)
        if origin.state not in (NodeState.FAILED, NodeState.EXTERNAL_REQUESTED):
            raise TransitionRejected(
                f"{origin_node_id}: only a FAILED or EXTERNAL_REQUESTED node is re-executed"
            )
        attempt = max(n.attempt for n in self.attempts_of(origin_node_id)) + 1
        fresh = TaskNode(
            node_id=node_id,
            title=origin.title,
            state=NodeState.PENDING,
            service_id=service_id if service_id is not None else origin.service_id,
            accelerator_id=(accelerator_id if accelerator_id is not None
                            else origin.accelerator_id),
            state_changed_at=at,
            input_command=origin.input_command,
            order_after=origin.order_after,
            depends_on=origin.depends_on,
            parallel_group=origin.parallel_group,
            attempt=attempt,
            origin_node_id=origin_node_id,
            external_request_id=origin.external_request_id,
        )
        return replace(self, nodes=self.nodes + (fresh,))
