"""Splices new subtask nodes into an existing graph when the situation changes.

implements: AI-B-12 (작업 그래프 실행 상태 관리 — 회차 보존), AI-B-14 (서브태스크
            산출의 capability 접지)
관련: AI-B-13 (수행 불가 → 외부 개발 요청), AI-C-05 (재계획이 없는 배치도 정상),
      AI-C-01 (변화 어휘의 정본은 데이터 사전), AI-C-15 (도메인 이름으로 분기하지
      않는다), AI-C-19 (AI 는 순서와 사유만 내고 발령·그리기는 남의 몫이다)

## 왜 새 모듈인가

`planning/decomposition.py` 는 **한 번** 분해한다 — (템플릿, 레지스트리, 실행자,
문맥) 이 같으면 항상 같은 그래프다. `planning/template_proposal.py` 는 생성된 단계를
**접지**한다. 둘 다 "지금 무엇을 할 수 있는가"의 답이고, 어느 쪽도 *상황이 달라진
뒤* 의 질문에 답하지 않는다: **"이동하려던 길이 막혔으면 새로운 서브태스크 노드를
만들어 그래프에 연결해야 한다."** 그 결정층이 이 모듈이다.

분해도 접지도 여기서 다시 쓰지 않는다. 허용 어휘는 `CapabilityMenu` 를 그대로 쓰고,
provider 해소는 `CapabilitySelector` 가 하고, 거부 사유 토큰은
`template_proposal.py` 와 같은 이름을 쓴다 — 같은 사실에 사유 이름이 둘이면 외부
개발 요청 경로가 둘로 갈린다.

## 원 그래프를 고치지 않는다

모든 자료구조가 frozen 이고 재계획은 **새 개정(`GraphRevision`)을 반환**한다. 원
개정 객체는 그대로 남고, 새 개정은 자기가 어느 개정에서 나왔는지(`parent_revision`),
무엇이 달라져서 나왔는지(`applied_changes`), 어느 노드가 새것·그대로·밀려남인지
(`NODE_LINEAGE`) 를 적는다. AI-B-12: "재실행은 원 노드를 덮지 않고 회차를 구분해
보존해야 하며". 밀려난 노드도 **지우지 않는다** — 지우면 왜 다시 계획됐는지를 되짚을
대상이 사라진다.

호출 한 번이 개정 하나다. 변화마다 번호를 올리면 호출자에게 건네지지 않은 중간 개정
번호가 `parent_revision` 에 남아 가리킬 데 없는 부모가 생긴다. 계보도 **그 호출에
들어온 그래프**를 기준으로 적는다 — 노드에 적혀 있던 앞 개정의 계보를 그대로 물려주면
개정 10 에서도 개정 3 에 생긴 노드가 "새것"이라고 말한다.

같은 변화가 다시 전달되면 그래프는 늘어나지 않는다. 식별자는 (action, 그 단계를 낳은
변화) 쌍이고 재실행도 같은 식별자를 쓰므로, 전달 횟수가 회차를 올리지 않는다
(AI-C-20 이 같은 command_id 의 재전달을 다시 물리 실행하지 않게 한 것과 같은 성질이다).
다른 자리에서 다시 막힌 것은 다른 사실이므로 그건 끼워진다.

## 변화는 데이터, 대응은 규칙

`if 하천:` / `if 길막힘:` 같은 분기를 두지 않는다. 상황 변화 종류는 데이터 사전의
`SITUATION_CHANGE_KINDS` 어휘이고, 그 종류에 대응하는 단계는 `ReplanRule` 로
등록한다. 새 변화 종류를 더하는 일은 **사전에 한 줄 + 규칙 하나**이고 이 모듈을
고치는 일이 아니다(절대 준수 원칙 #1·#3·#7). 그래프에 붙일 자리를 찾는 방법
(`match_on`)과 붙이는 방식(`anchor_mode`)도 통제 어휘 + 분배표이지 도메인 분기가
아니다.

## 의존은 규칙이 계산하고 순환은 구조적으로 불가능하다

끼워 넣은 단계의 간선을 규칙이 적지 않는다. 불변식 하나로 끝낸다 — **모든 실행
간선은 `order_index` 가 낮은 쪽에서 높은 쪽으로만 간다.** 끼워 넣기는 삽입만 하고
기존 노드의 상대 순서를 바꾸지 않으므로 기존 간선도 전방을 유지하고, 새 간선은 삽입
위치에서 계산된다. `GraphRevision.__post_init__` 이 이 불변식을 검사하므로 순환을
가진 개정은 애초에 만들어지지 않는다(가시화 쪽 `generate/solveDeps.ts` 가 같은
결론에 먼저 도달했다 — 모델은 노드만 내고 의존은 규칙이 센다).

## 분기는 선언된 결과이고 BPMN 런타임이 아니다

판정 노드(`NODE_ROLE == "decision"`)는 질문과 분기 목록을 payload 로 들고, 분기
간선은 `edges` 가 아니라 `branch_edges` 로 따로 나간다. 되돌아가는 분기를
`edges` 에 넣으면 되풀이가 순환이 되므로 `execution/task_graph.py` 의
`ReferenceEdge` 와 같은 이유로 분리한다. BPMN 에서 가져온 것은 **모양**(작업 ·
판정 게이트웨이 · 분기 · 시작/종료)뿐이고 어떤 BPMN 런타임도 들여오지 않는다
(§3 금지: 차용한 설계 개념을 이유로 해당 runtime 을 의존성으로 설치하지 않는다).
시작·종료 표식도 노드를 새로 만들어 끼우지 않는다 — 들어오는 간선이 없는 노드와
나가는 간선이 없는 노드를 `entry_nodes`/`terminal_nodes` 로 내고, 그것을 시작·종료
사건으로 그리는 것은 화면의 일이다.

## 경로는 그래프를 따라간다

그래프가 바뀌면 방문 순서가 같이 바뀐다. 그 순서를 `visit_order` 로 낸다 —
**자리의 식별자와 순서뿐이고 좌표도 픽셀도 없다**(AI-C-19, AI-C-08). 밀려난 노드의
자리는 순서에서 빠진다.

## 없는 것이 정상인 경우

재계획 규칙이 없는 배치, 어휘 밖의 변화, 아무 규칙도 답하지 못하는 변화, 끼울 단계
전부가 접지에서 떨어진 경우 — 넷 다 예외가 아니라 **사유를 가진 무변경**이다.
`ReplanResult.graph is base` 가 성립하고 선언된 계획은 계속 돈다(AI-C-05).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Mapping, Sequence

from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.contracts.capability import CapabilityRequirement, CapabilityState
from mission_runtime.contracts.profile import ResourceBudget, ResourceCost
from mission_runtime.execution.task_graph import GraphInvalid
from mission_runtime.planning.template_proposal import CapabilityMenu
from mission_runtime.registry.capability_registry import CapabilityRegistry
from mission_runtime.selection.selector import CapabilitySelector

# ---------------------------------------------------------------------------
# 어휘 — 정본은 데이터 사전이고 여기 상수는 그 값을 가리키는 이름이다 (AI-C-01)
# ---------------------------------------------------------------------------

#: 지나려던 자리에 못 간다. `subject` 는 도달 불가가 된 자리의 식별자다.
CHANGE_ROUTE_LEG_BLOCKED = "route_leg_blocked"
#: 그 단계를 받치던 필수 capability 가 사라졌다. `subject` 는 capability kind.
CHANGE_CAPABILITY_LOST = "capability_lost"
#: 그 단계를 수행했으나 실패했다. `subject` 는 subtask_id.
CHANGE_STEP_FAILED = "step_failed"

#: 선언 어휘. **사전의 부분집합이어야 한다** — 시험이 그것을 붙잡는다.
BASELINE_CHANGE_KINDS: tuple[str, ...] = (
    CHANGE_ROUTE_LEG_BLOCKED,
    CHANGE_CAPABILITY_LOST,
    CHANGE_STEP_FAILED,
)

# 노드 계보 (NODE_LINEAGES)
LINEAGE_KEPT = "kept"
LINEAGE_NEW = "new"
LINEAGE_SUPERSEDED = "superseded"

# 노드 역할 (NODE_ROLES)
ROLE_TASK = "task"
ROLE_DECISION = "decision"

# 재계획 사유 (REPLAN_REASONS)
REASON_NO_REPLANNER = "no_replanner_configured"
REASON_NO_SITUATION_CHANGE = "no_situation_change"
REASON_UNKNOWN_CHANGE_KIND = "unknown_change_kind"
REASON_NO_RULE = "no_rule_for_change"
REASON_NO_ANCHOR = "no_anchor_node_for_change"
REASON_ALL_REFUSED = "all_insertions_refused"
REASON_REPLANNED = "replanned"

#: 이 모듈이 실제로 내는 사유 전부. **사전 어휘의 부분집합이어야 한다** — 시험이
#: 그것을 붙잡는다(AI-C-01).
REPLAN_REASONS_USED: tuple[str, ...] = (
    REASON_NO_REPLANNER,
    REASON_NO_SITUATION_CHANGE,
    REASON_UNKNOWN_CHANGE_KIND,
    REASON_NO_RULE,
    REASON_NO_ANCHOR,
    REASON_ALL_REFUSED,
    REASON_REPLANNED,
)

# 끼워 넣기 거부 사유 (INSERTION_REFUSAL_REASONS)
REFUSE_UNKNOWN_CAPABILITY = "unknown_capability"
REFUSE_NO_PROVIDER = "no_provider"
REFUSE_NO_CAPABILITY_NAMED = "no_capability_named"
REFUSE_DUPLICATE_ACTION = "duplicate_action"

INSERTION_REFUSAL_REASONS_USED: tuple[str, ...] = (
    REFUSE_UNKNOWN_CAPABILITY,
    REFUSE_NO_PROVIDER,
    REFUSE_NO_CAPABILITY_NAMED,
    REFUSE_DUPLICATE_ACTION,
)

#: 그래프에 붙일 자리를 **어떻게 찾는가**. 분배표이지 도메인 분기가 아니다.
MATCH_VISIT_TARGET = "visit_target"
MATCH_ACTION = "action"
MATCH_SUBTASK_ID = "subtask_id"
MATCH_BOUND_CAPABILITY = "bound_capability"

#: 찾은 자리에 **어떻게 붙이는가**.
ANCHOR_BEFORE_SUBJECT = "before_subject"
ANCHOR_AFTER_SUBJECT = "after_subject"
ANCHOR_SUPERSEDE_SUBJECT = "supersede_subject"
ANCHOR_AT_END = "at_end"
ANCHOR_MODES: tuple[str, ...] = (
    ANCHOR_BEFORE_SUBJECT,
    ANCHOR_AFTER_SUBJECT,
    ANCHOR_SUPERSEDE_SUBJECT,
    ANCHOR_AT_END,
)

#: 분기가 가리킬 수 있는 특수 대상. 실행 노드 id 가 아니라 **자리의 뜻**이다.
TARGET_ANCHOR = "@anchor"  # 원래 가려던 그 단계로 돌아간다
TARGET_END = "@end"        # 여기서 끝난다 — 화면은 종료 사건으로 그린다

#: 실행 간선의 `item` 이 없는 경우. 자료가 아니라 **순서만** 잇는 간선이다.
SEQUENCE_ITEM: str | None = None


# ---------------------------------------------------------------------------
# 상황 변화 — 데이터다
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SituationChange:
    """무엇이 달라졌는가. 종류별로 자료형을 늘리지 않는다.

    `subject` 의 뜻은 종류가 정한다(자리 id · capability kind · subtask_id). 종류마다
    칸을 따로 두면 새 종류가 자료형 변경이 되고, 그러면 "새 변화는 데이터 + 규칙"이
    성립하지 않는다(절대 준수 원칙 #7).

    `params` 는 규칙이 읽는 부가 자료다 — 예컨대 우회로가 어디인지는 변화를 관측한
    쪽이 알고 규칙은 그 칸 이름만 안다. 핵심 코드가 그 값을 해석하지 않는다.
    """

    change_kind: str
    subject: str
    detail: str | None = None
    at: float | None = None
    params: Mapping[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict:
        return {
            dd.CHANGE_KIND: self.change_kind,
            dd.CHANGE_SUBJECT: self.subject,
            "detail": self.detail,
            "at": self.at,
        }


@dataclass
class SituationChangeVocabulary:
    """등록된 변화 종류와 그 뜻. 어휘 밖의 변화는 **조용히 무시되지 않는다**.

    기본 어휘는 데이터 사전의 `SITUATION_CHANGE_KINDS` 가 정본이다 — 여기서 따로
    적으면 같은 사실에 이름이 둘이 된다(AI-C-01).
    """

    kinds: dict[str, str] = field(default_factory=dict)

    def register(self, change_kind: str, meaning: str = "") -> None:
        if not change_kind:
            raise ValueError("change_kind must not be empty")
        self.kinds[change_kind] = meaning

    def __contains__(self, change_kind: object) -> bool:
        return change_kind in self.kinds

    def as_tuple(self) -> tuple[str, ...]:
        return tuple(sorted(self.kinds))


def default_change_vocabulary() -> SituationChangeVocabulary:
    """사전에 등록된 변화 종류 전부. 사전에 한 줄 더하면 여기 자동으로 들어온다."""
    return SituationChangeVocabulary({kind: "" for kind in dd.SITUATION_CHANGE_KINDS})


# ---------------------------------------------------------------------------
# 규칙 — 끼워 넣을 단계와 붙일 자리의 선언
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Branch:
    """판정 노드의 **선언된 결과** 하나. 하드코딩된 두 갈래가 아니다.

    `to` 는 같은 규칙 안의 다른 단계 `action`, 또는 `TARGET_ANCHOR` / `TARGET_END`.
    등록 시점에 검사하므로 가리킬 데 없는 분기는 애초에 등록되지 않는다.
    """

    name: str
    condition: str
    to: str = TARGET_ANCHOR

    def as_payload(self) -> dict:
        return {dd.BRANCH_NAME: self.name, dd.BRANCH_CONDITION: self.condition, "to": self.to}


@dataclass(frozen=True)
class InsertedStep:
    """규칙이 끼워 넣겠다고 **선언한** 단계 하나. 아직 접지되지 않았다.

    `requirement` 는 capability *kind* 만 적는다 — 모델 이름도 장치 이름도 아니다.
    접지를 통과하지 못하면 이 단계는 그래프에 들어가지 않고 사유로 남는다(AI-B-14).
    """

    action: str
    requirement: CapabilityRequirement = field(default_factory=CapabilityRequirement)
    role: str = ROLE_TASK
    #: 판정 노드가 묻는 질문. 분기가 있으면 채운다.
    question: str | None = None
    branches: tuple[Branch, ...] = ()
    #: 이 단계가 가는 자리. 고정 id 를 적거나,
    visit_target: str | None = None
    #: 변화의 `params` 에서 읽을 칸 이름을 적는다(둘 중 하나만 쓴다).
    visit_target_param: str | None = None
    #: 변화의 `subject` 가 곧 그 자리인 경우.
    visit_target_is_subject: bool = False
    cost: ResourceCost = field(default_factory=ResourceCost)
    params: Mapping[str, Any] = field(default_factory=dict)

    def resolved_visit_target(self, change: SituationChange) -> str | None:
        if self.visit_target is not None:
            return self.visit_target
        if self.visit_target_is_subject:
            return change.subject
        if self.visit_target_param is not None:
            value = change.params.get(self.visit_target_param)
            return value if isinstance(value, str) and value else None
        return None


@dataclass(frozen=True)
class ReplanRule:
    """한 변화 종류에 대한 대응. 전부 선언이고 실행 코드가 없다."""

    rule_id: str
    change_kind: str
    steps: tuple[InsertedStep, ...]
    anchor_mode: str = ANCHOR_BEFORE_SUBJECT
    match_on: str = MATCH_VISIT_TARGET
    #: 밀려난 노드를 **새 노드로** 다시 수행하는가. 원 노드는 그대로 남는다(AI-B-12).
    re_execute_subject: bool = False


#: `match_on` 분배표. 노드의 어느 축을 변화의 `subject` 와 맞추는가.
_MATCHERS: dict[str, Callable[["GraphNode", str], bool]] = {
    MATCH_VISIT_TARGET: lambda node, subject: node.visit_target == subject,
    MATCH_ACTION: lambda node, subject: node.action == subject,
    MATCH_SUBTASK_ID: lambda node, subject: node.subtask_id == subject,
    MATCH_BOUND_CAPABILITY: lambda node, subject: subject in node.capability_kinds,
}


class ReplanRuleBook:
    """변화 종류 → 규칙들. 등록만으로 늘어나고 이 클래스는 값으로 분기하지 않는다."""

    def __init__(self, vocabulary: SituationChangeVocabulary | None = None) -> None:
        self._vocabulary = vocabulary if vocabulary is not None else default_change_vocabulary()
        self._rules: dict[str, list[ReplanRule]] = {}

    @property
    def vocabulary(self) -> SituationChangeVocabulary:
        return self._vocabulary

    def register(self, rule: ReplanRule) -> None:
        """규칙을 등록한다. **배선 오류는 여기서 터진다** — 상황 처리 중이 아니다.

        운영 중의 거부는 사유이고 예외가 아니지만(AI-C-05), 가리킬 데 없는 분기나
        어휘 밖 변화 종류를 등록하는 것은 배포 선언의 오류이므로 조용히 통과시키면
        나중에 그래프가 조용히 비어 나온다.
        """
        if rule.change_kind not in self._vocabulary:
            raise ValueError(
                f"{rule.rule_id}: change kind {rule.change_kind!r} is not in the vocabulary; "
                "register it there first (AI-C-01)"
            )
        if rule.anchor_mode not in ANCHOR_MODES:
            raise ValueError(f"{rule.rule_id}: unknown anchor mode {rule.anchor_mode!r}")
        if rule.match_on not in _MATCHERS:
            raise ValueError(f"{rule.rule_id}: unknown match axis {rule.match_on!r}")
        if not rule.steps and not rule.re_execute_subject:
            raise ValueError(f"{rule.rule_id}: rule inserts nothing")
        actions = [step.action for step in rule.steps]
        if len(actions) != len(set(actions)):
            raise ValueError(f"{rule.rule_id}: duplicate action in declared steps")
        for step in rule.steps:
            for branch in step.branches:
                if branch.to in (TARGET_ANCHOR, TARGET_END):
                    continue
                if branch.to not in actions:
                    raise ValueError(
                        f"{rule.rule_id}: branch {branch.name!r} points at {branch.to!r} "
                        "which is neither a declared step nor a target token"
                    )
        self._rules.setdefault(rule.change_kind, []).append(rule)

    def knows(self, change_kind: str) -> bool:
        return change_kind in self._vocabulary

    def rules_for(self, change_kind: str) -> tuple[ReplanRule, ...]:
        return tuple(self._rules.get(change_kind, ()))


# ---------------------------------------------------------------------------
# 그래프 — 콘솔 payload 와 모양이 같다
# ---------------------------------------------------------------------------

#: `GraphNode` 가 직접 소유하는 payload 칸. 그 밖의 칸은 **그대로 보존한다**
#: (`unverified_preconditions`·`unmet_inputs` 처럼 콘솔이 이미 내는 칸을 재계획이
#: 삼키면 화면이 설명을 잃는다).
_OWNED_NODE_KEYS: frozenset[str] = frozenset({
    "subtask_id", "action", "order_index", "state", "executable", "runs_on", "bindings",
    "missing_required", "missing_optional", "cost",
    dd.NODE_ROLE, dd.NODE_LINEAGE, dd.INSERTED_BY, dd.VISIT_TARGET,
    dd.ATTEMPT_INDEX, dd.ORIGIN_SUBTASK_ID, "decision",
})


@dataclass(frozen=True)
class NodeBinding:
    """한 노드가 어느 provider 로 받쳐지는가. 콘솔 payload 와 같은 모양이다."""

    capability_kind: str
    provider_id: str
    source: str = "registry"
    optional: bool = False

    def as_payload(self) -> dict:
        return {
            dd.CAPABILITY_KIND: self.capability_kind,
            dd.PROVIDER_ID: self.provider_id,
            "source": self.source,
            "optional": self.optional,
        }

    @staticmethod
    def from_payload(raw: Mapping[str, Any]) -> NodeBinding:
        return NodeBinding(
            capability_kind=str(raw.get(dd.CAPABILITY_KIND, "")),
            provider_id=str(raw.get(dd.PROVIDER_ID, "")),
            source=str(raw.get("source", "registry")),
            optional=bool(raw.get("optional", False)),
        )


@dataclass(frozen=True)
class Decision:
    """판정 노드가 들고 있는 질문과 분기들. 조건은 payload 에 적혀 나간다."""

    question: str | None
    branches: tuple[Branch, ...]

    def as_payload(self) -> dict:
        return {
            dd.DECISION_QUESTION: self.question,
            "branches": [b.as_payload() for b in self.branches],
        }


@dataclass(frozen=True)
class GraphNode:
    """그래프의 노드 하나. 콘솔 노드 payload + 재계획이 더한 칸."""

    subtask_id: str
    action: str
    order_index: int
    state: str = CapabilityState.ACTIVE.value
    executable: bool = True
    runs_on: tuple[str, ...] = ()
    bindings: tuple[NodeBinding, ...] = ()
    missing_required: tuple[str, ...] = ()
    missing_optional: tuple[str, ...] = ()
    cost: ResourceCost = field(default_factory=ResourceCost)
    node_role: str = ROLE_TASK
    node_lineage: str = LINEAGE_KEPT
    inserted_by: str | None = None
    visit_target: str | None = None
    attempt_index: int = 1
    origin_subtask_id: str | None = None
    decision: Decision | None = None
    #: 콘솔이 이미 내는 다른 칸들. 손대지 않고 그대로 되돌려 보낸다.
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.subtask_id:
            raise GraphInvalid("subtask_id must not be empty")
        if self.attempt_index < 1:
            raise GraphInvalid(f"attempt_index must be >= 1: {self.attempt_index}")

    @property
    def capability_kinds(self) -> tuple[str, ...]:
        """이 노드가 실제로 쓰거나 못 써서 막힌 capability 전부."""
        seen: list[str] = []
        for name in (
            tuple(b.capability_kind for b in self.bindings)
            + self.missing_required
            + self.missing_optional
        ):
            if name and name not in seen:
                seen.append(name)
        return tuple(seen)

    @property
    def is_superseded(self) -> bool:
        return self.node_lineage == LINEAGE_SUPERSEDED

    def as_payload(self) -> dict:
        payload = dict(self.extra)
        payload.update({
            dd.SUBTASK_ID: self.subtask_id,
            "action": self.action,
            "order_index": self.order_index,
            "state": self.state,
            "executable": self.executable,
            "runs_on": list(self.runs_on),
            "bindings": [b.as_payload() for b in self.bindings],
            "missing_required": list(self.missing_required),
            "missing_optional": list(self.missing_optional),
            "cost": {"compute_units": self.cost.compute_units, "memory_mb": self.cost.memory_mb},
            dd.NODE_ROLE: self.node_role,
            dd.NODE_LINEAGE: self.node_lineage,
            dd.INSERTED_BY: self.inserted_by,
            dd.VISIT_TARGET: self.visit_target,
            dd.ATTEMPT_INDEX: self.attempt_index,
            dd.ORIGIN_SUBTASK_ID: self.origin_subtask_id,
            "decision": self.decision.as_payload() if self.decision is not None else None,
        })
        return payload

    @staticmethod
    def from_payload(raw: Mapping[str, Any], *, visit_target: str | None = None) -> GraphNode:
        cost_raw = raw.get("cost") or {}
        decision_raw = raw.get("decision")
        decision = None
        if isinstance(decision_raw, Mapping):
            decision = Decision(
                question=decision_raw.get(dd.DECISION_QUESTION),
                branches=tuple(
                    Branch(
                        name=str(b.get(dd.BRANCH_NAME, "")),
                        condition=str(b.get(dd.BRANCH_CONDITION, "")),
                        to=str(b.get("to", TARGET_ANCHOR)),
                    )
                    for b in decision_raw.get("branches", ())
                    if isinstance(b, Mapping)
                ),
            )
        return GraphNode(
            subtask_id=str(raw[dd.SUBTASK_ID]),
            action=str(raw.get("action", "")),
            order_index=int(raw.get("order_index", 0)),
            state=str(raw.get("state", CapabilityState.ACTIVE.value)),
            executable=bool(raw.get("executable", True)),
            runs_on=tuple(raw.get("runs_on", ()) or ()),
            bindings=tuple(
                NodeBinding.from_payload(b)
                for b in raw.get("bindings", ()) or ()
                if isinstance(b, Mapping)
            ),
            missing_required=tuple(raw.get("missing_required", ()) or ()),
            missing_optional=tuple(raw.get("missing_optional", ()) or ()),
            cost=ResourceCost(
                compute_units=float(cost_raw.get("compute_units", 0.0)),
                memory_mb=float(cost_raw.get("memory_mb", 0.0)),
            ),
            node_role=str(raw.get(dd.NODE_ROLE, ROLE_TASK)),
            node_lineage=str(raw.get(dd.NODE_LINEAGE, LINEAGE_KEPT)),
            inserted_by=raw.get(dd.INSERTED_BY),
            visit_target=(visit_target if visit_target is not None
                          else raw.get(dd.VISIT_TARGET)),
            attempt_index=int(raw.get(dd.ATTEMPT_INDEX, 1) or 1),
            origin_subtask_id=raw.get(dd.ORIGIN_SUBTASK_ID),
            decision=decision,
            extra={k: v for k, v in raw.items() if k not in _OWNED_NODE_KEYS},
        )


@dataclass(frozen=True)
class GraphEdge:
    """실행 간선. **낮은 order_index 에서 높은 쪽으로만** 간다."""

    from_id: str
    to_id: str
    #: 흘러가는 자료의 이름. 순서만 잇는 간선은 None 이고 화면은 라벨 없이 그린다.
    item: str | None = None

    def as_payload(self) -> dict:
        return {"from": self.from_id, "to": self.to_id, "item": self.item}

    @staticmethod
    def from_payload(raw: Mapping[str, Any]) -> GraphEdge:
        return GraphEdge(str(raw["from"]), str(raw["to"]), raw.get("item"))


@dataclass(frozen=True)
class BranchEdge:
    """판정 결과로 갈라지는 간선. **`edges` 에 넣지 않는다**.

    `to_id is None` 은 "그 결과면 여기서 끝난다"는 뜻이고 화면은 종료 사건으로
    그린다. 되돌아가는 분기를 실행 간선에 섞으면 되풀이가 순환이 되므로
    `execution/task_graph.py::ReferenceEdge` 와 같은 이유로 분리한다.
    """

    from_id: str
    to_id: str | None
    branch_name: str
    condition: str

    def as_payload(self) -> dict:
        return {
            "from": self.from_id,
            "to": self.to_id,
            dd.BRANCH_NAME: self.branch_name,
            dd.BRANCH_CONDITION: self.condition,
        }

    @staticmethod
    def from_payload(raw: Mapping[str, Any]) -> BranchEdge:
        return BranchEdge(
            from_id=str(raw["from"]),
            to_id=raw.get("to"),
            branch_name=str(raw.get(dd.BRANCH_NAME, "")),
            condition=str(raw.get(dd.BRANCH_CONDITION, "")),
        )


@dataclass(frozen=True)
class GraphRevision:
    """그래프 한 개정. 다음 개정이 이것을 **덮지 않는다**(AI-B-12).

    `base` 는 콘솔 payload 의 노드·간선 밖 칸들(plan_id, goal_kind, executor, …)을
    그대로 들고 있는 자리다 — 재계획이 그것을 해석하지 않고 되돌려 보낸다.
    """

    graph_id: str
    revision: int
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...] = ()
    branch_edges: tuple[BranchEdge, ...] = ()
    parent_revision: int | None = None
    #: **이 개정을 만든** 변화들. 전체 이력이 아니다 — 이력은 `parent_revision` 을
    #: 따라 앞 개정으로 거슬러 읽는다. 한 개정의 payload 가 자기만으로 설명되어야
    #: 화면이 개정 하나를 떼어 보여줄 수 있다.
    applied_changes: tuple[SituationChange, ...] = ()
    base: Mapping[str, Any] = field(default_factory=dict)
    #: 앞 개정의 방문 자리 순서. 바뀌었는지를 말하려면 비교 대상이 있어야 한다.
    parent_visit_places: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        ids = [n.subtask_id for n in self.nodes]
        if len(ids) != len(set(ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise GraphInvalid(f"duplicate subtask ids: {dupes}")
        position = {n.subtask_id: n.order_index for n in self.nodes}
        for edge in self.edges:
            missing = [i for i in (edge.from_id, edge.to_id) if i not in position]
            if missing:
                raise GraphInvalid(f"edge references unknown nodes: {missing}")
            # 불변식 하나로 순환을 구조적으로 막는다 — 전방 간선만 존재한다.
            if position[edge.from_id] >= position[edge.to_id]:
                raise GraphInvalid(
                    f"non-forward edge would allow a cycle: {edge.from_id} "
                    f"(order {position[edge.from_id]}) -> {edge.to_id} "
                    f"(order {position[edge.to_id]})"
                )
        for branch in self.branch_edges:
            if branch.from_id not in position:
                raise GraphInvalid(f"branch edge from unknown node: {branch.from_id}")
            if branch.to_id is not None and branch.to_id not in position:
                raise GraphInvalid(f"branch edge to unknown node: {branch.to_id}")

    # -- 조회 ---------------------------------------------------------------

    def node(self, subtask_id: str) -> GraphNode:
        for n in self.nodes:
            if n.subtask_id == subtask_id:
                return n
        raise KeyError(subtask_id)

    def ordered(self) -> tuple[GraphNode, ...]:
        return tuple(sorted(self.nodes, key=lambda n: (n.order_index, n.subtask_id)))

    def nodes_by_lineage(self) -> dict[str, tuple[str, ...]]:
        out: dict[str, list[str]] = {name: [] for name in dd.NODE_LINEAGES}
        for node in self.ordered():
            out.setdefault(node.node_lineage, []).append(node.subtask_id)
        return {k: tuple(v) for k, v in out.items()}

    def visit_order(self) -> tuple[tuple[str, str, int], ...]:
        """그래프 순서를 따라 방문하는 (자리, 노드, 순서). 밀려난 노드는 빠진다.

        연속 중복은 접는다 — 같은 자리에서 두 단계를 하는 것이 두 번 가는 것은
        아니다. 자리의 좌표도 거리도 여기서 내지 않는다(AI-C-19).
        """
        out: list[tuple[str, str, int]] = []
        for node in self.ordered():
            if node.visit_target is None or node.is_superseded:
                continue
            if out and out[-1][0] == node.visit_target:
                continue
            out.append((node.visit_target, node.subtask_id, node.order_index))
        return tuple(out)

    def visit_places(self) -> tuple[str, ...]:
        return tuple(place for place, _, _ in self.visit_order())

    @property
    def visit_order_changed(self) -> bool:
        """앞 개정과 방문 순서가 다른가. **최초 개정은 False** — 비교 대상이 없는
        것을 "바뀌었다"로 적으면 아무것도 하지 않은 그래프가 변경으로 읽힌다."""
        if self.parent_revision is None:
            return False
        return self.visit_places() != self.parent_visit_places

    def visit_order_delta(self) -> dict[str, tuple[str, ...]]:
        """순서에서 빠진 자리와 새로 든 자리. 순서가 왜 달라졌는지의 자리 쪽 답이고,
        사유 쪽 답은 `applied_changes` 와 각 노드의 `inserted_by` 다."""
        before = self.parent_visit_places
        after = self.visit_places()
        if not self.visit_order_changed:
            return {"added": (), "removed": ()}
        return {
            "added": tuple(p for p in after if p not in before),
            "removed": tuple(p for p in before if p not in after),
        }

    def entry_nodes(self) -> tuple[str, ...]:
        """들어오는 실행 간선이 없는 노드. 화면이 시작 사건을 그릴 자리다."""
        incoming = {e.to_id for e in self.edges}
        return tuple(n.subtask_id for n in self.ordered() if n.subtask_id not in incoming)

    def terminal_nodes(self) -> tuple[str, ...]:
        outgoing = {e.from_id for e in self.edges}
        return tuple(n.subtask_id for n in self.ordered() if n.subtask_id not in outgoing)

    # -- payload ------------------------------------------------------------

    def as_payload(self) -> dict:
        payload = {k: v for k, v in self.base.items() if k not in ("nodes", "edges")}
        payload.update({
            "graph_id": self.graph_id,
            dd.GRAPH_REVISION: self.revision,
            dd.PARENT_GRAPH_REVISION: self.parent_revision,
            "nodes": [n.as_payload() for n in self.ordered()],
            "edges": [e.as_payload() for e in self.edges],
            "branch_edges": [b.as_payload() for b in self.branch_edges],
            "applied_changes": [c.as_payload() for c in self.applied_changes],
            # 노드별 `node_lineage` 를 묶어 둔 **색인**이다. 같은 사실을 두 모양으로
            # 내보내지 않으려고 이름을 따로 둔다 — 노드 칸의 이름은 `node_lineage`
            # (문자열 하나)이고 이쪽은 그것을 모은 것이다.
            "nodes_by_lineage": self.nodes_by_lineage_payload(),
            dd.VISIT_ORDER: [
                {"place_id": place, dd.SUBTASK_ID: sid, "order_index": index}
                for place, sid, index in self.visit_order()
            ],
            "visit_order_changed": self.visit_order_changed,
            "previous_visit_order": list(self.parent_visit_places),
            "visit_order_delta": {k: list(v) for k, v in self.visit_order_delta().items()},
            "entry_nodes": list(self.entry_nodes()),
            "terminal_nodes": list(self.terminal_nodes()),
        })
        return payload

    def nodes_by_lineage_payload(self) -> dict:
        return {k: list(v) for k, v in self.nodes_by_lineage().items()}

    @staticmethod
    def from_payload(
        payload: Mapping[str, Any],
        *,
        graph_id: str | None = None,
        revision: int | None = None,
        visit_targets: Mapping[str, str] | None = None,
    ) -> GraphRevision:
        """콘솔 payload(`nodes` + `edges`)를 개정 하나로 읽는다.

        `visit_targets` 는 subtask_id → 자리 id 다. 선언 템플릿의 `params` 에 있는
        값을 호출자가 옮겨 주는 자리이고, 없는 노드는 경로에 나타나지 않는다 —
        방문 자리를 추측해 채우지 않는다(사실과 추측을 같은 칸에 담지 않는다).
        """
        targets = dict(visit_targets or {})
        nodes = tuple(
            GraphNode.from_payload(raw, visit_target=targets.get(str(raw[dd.SUBTASK_ID])))
            for raw in payload.get("nodes", ())
            if isinstance(raw, Mapping)
        )
        edges = tuple(
            GraphEdge.from_payload(raw)
            for raw in payload.get("edges", ())
            if isinstance(raw, Mapping)
        )
        branch_edges = tuple(
            BranchEdge.from_payload(raw)
            for raw in payload.get("branch_edges", ())
            if isinstance(raw, Mapping)
        )
        return GraphRevision(
            graph_id=graph_id or str(payload.get("graph_id") or payload.get("plan_id") or ""),
            revision=revision if revision is not None else int(payload.get(dd.GRAPH_REVISION, 1)),
            nodes=nodes,
            edges=edges,
            branch_edges=branch_edges,
            parent_revision=payload.get(dd.PARENT_GRAPH_REVISION),
            base={k: v for k, v in payload.items() if k not in ("nodes", "edges", "branch_edges")},
        )


# ---------------------------------------------------------------------------
# 거부와 결과
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InsertionRejection:
    """끼워 넣지 못한 단계 하나와 그 이유. **버리지 않고 남긴다**(AI-B-13)."""

    change_kind: str
    subject: str
    action: str
    reason: str
    requested_capability: str | None = None

    def as_payload(self) -> dict:
        return {
            dd.CHANGE_KIND: self.change_kind,
            dd.CHANGE_SUBJECT: self.subject,
            "action": self.action,
            dd.INSERTION_REFUSAL_REASON: self.reason,
            dd.REQUESTED_CAPABILITY: self.requested_capability,
        }


@dataclass(frozen=True)
class ReplanResult:
    """재계획 한 번의 끝. 바뀌지 않은 것도 결과이고 예외가 아니다(AI-C-05)."""

    graph: GraphRevision
    changed: bool
    reason: str
    rejections: tuple[InsertionRejection, ...] = ()

    @property
    def escalation_capabilities(self) -> tuple[str, ...]:
        """외부 개발 요청으로 올릴 capability 이름들(중복 제거, 순서 고정)."""
        seen: list[str] = []
        for rejection in self.rejections:
            name = rejection.requested_capability
            if name and name not in seen:
                seen.append(name)
        return tuple(seen)

    def as_payload(self) -> dict:
        payload = self.graph.as_payload()
        payload["graph_changed"] = self.changed
        payload[dd.REPLAN_REASON] = self.reason
        payload["insertion_rejections"] = [r.as_payload() for r in self.rejections]
        # 기존 키를 덮지 않고 **합친다** — 분해에서 막힌 kind 와 재계획에서 거부된
        # kind 는 둘 다 같은 외부 요청 경로의 재료다(AI-B-13).
        existing = payload.get("escalation_capabilities") or []
        merged = list(existing) + [
            name for name in self.escalation_capabilities if name not in existing
        ]
        payload["escalation_capabilities"] = merged
        return payload


# ---------------------------------------------------------------------------
# 재계획기
# ---------------------------------------------------------------------------


def replan_menu(
    registry: CapabilityRegistry | None,
    zone_supplied_kinds: Iterable[str] = (),
) -> CapabilityMenu:
    """허용 어휘 = 지금 provider 가 있는 kind + 구역이 공급하는 kind.

    등록만 되어 있고 provider 가 없는 kind 를 넣지 않는 이유는 `template_proposal`
    과 같다 — 그러면 접지는 통과하고 실행에서 떨어진다(AI-B-14).
    """
    kinds: set[str] = set(zone_supplied_kinds)
    if registry is not None:
        kinds |= set(CapabilityMenu.from_registry(registry).kinds)
    return CapabilityMenu(tuple(sorted(kinds)))


@dataclass
class Replanner:
    """상황 변화를 받아 **새 개정**을 낸다. 원 개정은 손대지 않는다.

    `rulebook is None` 은 "이 배치에 재계획이 없다"는 정상 상태다 — 선언된 계획은
    그대로 돌고 `REASON_NO_REPLANNER` 가 사유로 나간다(AI-C-05).
    """

    rulebook: ReplanRuleBook | None = None
    registry: CapabilityRegistry | None = None
    node_tags: frozenset[str] = frozenset()
    budget: ResourceBudget = ResourceBudget(compute_units=100.0, memory_mb=8192.0)
    #: 구역 인프라가 내는 kind. 로봇이 못 내는 단계가 구역 덕분에 되는 경우를
    #: `runs_on == ["zone"]` 로 구분해 보여 준다(`tools/fms_console/subtasks.py` 와 같은 규약).
    zone_supplied_kinds: frozenset[str] = frozenset()
    menu: CapabilityMenu | None = None

    def effective_menu(self) -> CapabilityMenu:
        if self.menu is not None:
            return self.menu
        return replan_menu(self.registry, self.zone_supplied_kinds)

    # -- 입구 ---------------------------------------------------------------

    def replan(
        self,
        graph: GraphRevision,
        changes: Sequence[SituationChange],
    ) -> ReplanResult:
        """변화들을 **순서대로** 적용해 개정 **하나**를 낸다.

        한 번의 호출이 한 개정이다 — 변화마다 번호를 올리면 호출자에게 건네지지 않은
        중간 개정 번호가 `parent_revision` 에 남아, 가리키는 데 없는 부모가 생긴다.
        그래서 번호는 `graph.revision + 1` 하나이고 그 개정의 `applied_changes` 에
        실제로 그래프를 바꾼 변화들이 들어간다.

        한 변화가 무변경으로 끝나도 다음 변화는 계속 본다 — 하나가 답을 못 찾은 것이
        나머지를 막을 이유가 아니다(AI-C-05). 전부 무변경이면 들어온 그래프를 **그
        객체 그대로** 돌려주므로 호출자가 `result.graph is graph` 로 확인할 수 있다.
        """
        if self.rulebook is None:
            return ReplanResult(graph, False, REASON_NO_REPLANNER)
        if not changes:
            return ReplanResult(graph, False, REASON_NO_SITUATION_CHANGE)

        current = graph
        rejections: list[InsertionRejection] = []
        reasons: list[str] = []
        applied: tuple[SituationChange, ...] = ()
        for change in changes:
            step = self._apply_one(graph, current, change, applied)
            rejections.extend(step.rejections)
            reasons.append(step.reason)
            if step.changed:
                current = step.graph
                applied = current.applied_changes
        changed = current is not graph
        reason = REASON_REPLANNED if changed else _first_reason(reasons)
        return ReplanResult(current, changed, reason, tuple(rejections))

    # -- 변화 하나 ----------------------------------------------------------

    def _apply_one(
        self,
        base: GraphRevision,
        current: GraphRevision,
        change: SituationChange,
        applied: tuple[SituationChange, ...],
    ) -> ReplanResult:
        """`base` 는 이 호출이 들어올 때의 그래프(개정 번호·계보의 기준)이고
        `current` 는 앞 변화까지 반영된 초안이다. 둘을 가르지 않으면 계보가 "이
        호출에서 무엇이 새것인가"를 말하지 못한다."""
        assert self.rulebook is not None  # replan() guarantees it
        if not self.rulebook.knows(change.change_kind):
            return ReplanResult(current, False, REASON_UNKNOWN_CHANGE_KIND)
        rules = self.rulebook.rules_for(change.change_kind)
        if not rules:
            return ReplanResult(current, False, REASON_NO_RULE)

        rejections: list[InsertionRejection] = []
        reasons: list[str] = []
        for rule in rules:
            outcome = self._apply_rule(base, current, change, rule, applied)
            rejections.extend(outcome.rejections)
            if outcome.changed:
                return ReplanResult(outcome.graph, True, REASON_REPLANNED, tuple(rejections))
            reasons.append(outcome.reason)
        return ReplanResult(current, False, _first_reason(reasons), tuple(rejections))

    def _apply_rule(
        self,
        base: GraphRevision,
        graph: GraphRevision,
        change: SituationChange,
        rule: ReplanRule,
        applied: tuple[SituationChange, ...] = (),
    ) -> ReplanResult:
        ordered = list(graph.ordered())
        matcher = _MATCHERS[rule.match_on]
        matches = [n for n in ordered if matcher(n, change.subject)]

        if rule.anchor_mode == ANCHOR_AT_END:
            anchor = ordered[-1] if ordered else None
            insert_at = len(ordered)
        else:
            if not matches:
                return ReplanResult(graph, False, REASON_NO_ANCHOR)
            anchor = matches[0]
            anchor_pos = ordered.index(anchor)
            insert_at = anchor_pos if rule.anchor_mode == ANCHOR_BEFORE_SUBJECT else anchor_pos + 1

        new_revision = base.revision + 1
        # 같은 변화가 다시 전달돼도 같은 단계를 두 번 끼우지 않는다 — 식별자는
        # (action, 그 단계를 낳은 변화) 쌍이다. action 하나만 보면 다른 자리에서 다시
        # 막힌 경우에 우회를 못 끼운다(AI-C-20 이 같은 command_id 의 재전달을 다시
        # 물리 실행하지 않게 한 것과 같은 성질이다).
        existing_insertions = {(n.action, n.inserted_by) for n in ordered}
        existing_ids = {n.subtask_id for n in ordered}

        grounded: list[GraphNode] = []
        rejections: list[InsertionRejection] = []
        for step in rule.steps:
            node, rejection = self._ground(
                step, change, rule, new_revision, existing_insertions, existing_ids
            )
            if node is None:
                rejections.append(rejection)  # type: ignore[arg-type]
                continue
            existing_insertions.add((node.action, node.inserted_by))
            existing_ids.add(node.subtask_id)
            grounded.append(node)

        re_exec: GraphNode | None = None
        if rule.re_execute_subject and anchor is not None:
            re_exec, rejection = self._re_execution_of(
                anchor, graph, change, existing_insertions, existing_ids
            )
            if rejection is not None:
                rejections.append(rejection)

        if not grounded and re_exec is None:
            return ReplanResult(graph, False, REASON_ALL_REFUSED, tuple(rejections))

        inserted = tuple(grounded + ([re_exec] if re_exec is not None else []))

        # -- 노드 목록: 삽입만 한다. 기존 노드의 상대 순서는 바꾸지 않는다.
        superseded_ids: set[str] = set()
        if rule.anchor_mode == ANCHOR_SUPERSEDE_SUBJECT:
            superseded_ids = {n.subtask_id for n in matches}

        # 계보는 **이 호출의 기준 그래프**에 비추어 정한다. 노드에 적혀 있던 앞
        # 개정의 계보를 그대로 보존하면 개정 10 에서도 개정 3 에 생긴 노드가
        # "새것"이라고 말한다 — 그러면 "이번에 무엇이 달라졌는가"를 못 읽는다.
        # 밀려남은 달라붙는다(한 번 밀려난 노드가 다음 개정에서 되살아나지 않는다).
        base_ids = {n.subtask_id for n in base.nodes}
        kept = [
            replace(n, node_lineage=LINEAGE_SUPERSEDED)
            if (n.subtask_id in superseded_ids or n.is_superseded)
            else replace(
                n,
                node_lineage=LINEAGE_KEPT if n.subtask_id in base_ids else LINEAGE_NEW,
            )
            for n in ordered
        ]
        merged = kept[:insert_at] + list(inserted) + kept[insert_at:]
        renumbered = tuple(replace(n, order_index=i) for i, n in enumerate(merged))
        position = {n.subtask_id: n.order_index for n in renumbered}

        edges = self._edges_for(
            graph=graph,
            ordered_before=ordered,
            inserted=inserted,
            insert_at=insert_at,
        )
        branch_edges = graph.branch_edges + self._branch_edges_for(
            inserted=inserted, anchor=anchor, position=position,
        )

        return ReplanResult(
            GraphRevision(
                graph_id=base.graph_id,
                revision=new_revision,
                nodes=renumbered,
                edges=edges,
                branch_edges=branch_edges,
                parent_revision=base.revision,
                applied_changes=applied + (change,),
                base=base.base,
                parent_visit_places=base.visit_places(),
            ),
            True,
            REASON_REPLANNED,
            tuple(rejections),
        )

    # -- 접지 (AI-B-14) ------------------------------------------------------

    def _ground(
        self,
        step: InsertedStep,
        change: SituationChange,
        rule: ReplanRule,
        new_revision: int,
        existing_insertions: set[tuple[str, str | None]],
        existing_ids: set[str],
    ) -> tuple[GraphNode | None, InsertionRejection | None]:
        """선언된 단계 하나를 **지금 쓸 수 있는 어휘**에 비춘다.

        목록 밖이면 조용히 끼우지 않고 사유와 **요구한 이름**을 남긴다 — 그 이름이
        외부 개발 요청의 재료다(AI-B-13). 선택 capability 결손은 끼우기를 막지 않고
        DEGRADED 까지만 내린다(AI-C-05).
        """
        def refuse(reason: str, capability: str | None = None) -> tuple[None, InsertionRejection]:
            return None, InsertionRejection(
                change_kind=change.change_kind,
                subject=change.subject,
                action=step.action,
                reason=reason,
                requested_capability=capability,
            )

        marker = f"{change.change_kind}:{change.subject}"
        if (step.action, marker) in existing_insertions:
            return refuse(REFUSE_DUPLICATE_ACTION)
        if not step.requirement.required:
            return refuse(REFUSE_NO_CAPABILITY_NAMED)

        menu = self.effective_menu()
        bindings: list[NodeBinding] = []
        missing_optional: list[str] = []
        for kind in step.requirement.required:
            if kind not in menu:
                return refuse(REFUSE_UNKNOWN_CAPABILITY, kind)
            binding = self._bind(kind, optional=False)
            if binding is None:
                return refuse(REFUSE_NO_PROVIDER, kind)
            bindings.append(binding)
        for kind in step.requirement.optional:
            binding = self._bind(kind, optional=True) if kind in menu else None
            if binding is None:
                missing_optional.append(kind)
            else:
                bindings.append(binding)

        state = CapabilityState.DEGRADED if missing_optional else CapabilityState.ACTIVE
        node_id = _unique_id(f"{step.action}@r{new_revision}", existing_ids)
        return GraphNode(
            subtask_id=node_id,
            action=step.action,
            order_index=0,  # 삽입 후 다시 번호를 매긴다
            state=state.value,
            executable=True,
            # `tools/fms_console/subtasks.py` 와 같은 규약: registry 로 해소된 단계는
            # 로봇 위에서, 구역 공급으로 해소된 단계는 구역에서 돈다.
            runs_on=tuple(sorted({("robot" if b.source == "registry" else "zone")
                                  for b in bindings})),
            bindings=tuple(bindings),
            missing_required=(),
            missing_optional=tuple(missing_optional),
            cost=step.cost,
            node_role=step.role,
            node_lineage=LINEAGE_NEW,
            inserted_by=marker,
            visit_target=step.resolved_visit_target(change),
            decision=(Decision(step.question, step.branches)
                      if step.branches or step.question else None),
            extra=({"params": dict(step.params), "rule_id": rule.rule_id}
                   if step.params else {"rule_id": rule.rule_id}),
        ), None

    def _bind(self, kind: str, *, optional: bool) -> NodeBinding | None:
        """kind 하나를 구체 provider 로 해소한다. `None` 은 정상적인 답이다.

        레지스트리를 먼저 보고(노드 태그·예산으로 해소되면 그 단계는 로봇 위에서
        돈다) 구역 공급을 뒤에 본다 — `planning/decomposition.py::_bind` 와 같은
        순서여야 두 화면이 다른 답을 말하지 않는다.
        """
        if self.registry is not None:
            result = CapabilitySelector(self.registry).select(
                kind, set(self.node_tags), self.budget
            )
            if result.provider is not None:
                return NodeBinding(kind, result.provider.provider_id, "registry", optional)
        if kind in self.zone_supplied_kinds:
            return NodeBinding(kind, "zone-supply", "executor", optional)
        return None

    # -- 회차 (AI-B-12) ------------------------------------------------------

    def _re_execution_of(
        self,
        origin: GraphNode,
        graph: GraphRevision,
        change: SituationChange,
        existing_insertions: set[tuple[str, str | None]],
        existing_ids: set[str],
    ) -> tuple[GraphNode | None, InsertionRejection | None]:
        """원 노드를 덮지 않고 회차를 올린 **새 노드**를 만든다.

        AI-B-12: "재실행은 원 노드를 덮지 않고 회차를 구분해 보존해야 하며". 원
        노드는 `superseded` 로 남고 이 노드가 그것을 가리킨다.

        같은 실패가 다시 전달돼도 회차를 또 올리지 않는다 — 끼워 넣는 단계와 같은
        식별자((action, 그 단계를 낳은 변화))를 쓴다. 회차가 전달 횟수만큼 쌓이면
        몇 번 **수행했는지**를 그 숫자에서 읽을 수 없다.
        """
        marker = f"{change.change_kind}:{change.subject}"
        if (origin.action, marker) in existing_insertions:
            return None, InsertionRejection(
                change_kind=change.change_kind,
                subject=change.subject,
                action=origin.action,
                reason=REFUSE_DUPLICATE_ACTION,
            )
        root = origin.origin_subtask_id or origin.subtask_id
        attempts = [n.attempt_index for n in graph.nodes
                    if n.subtask_id == root or n.origin_subtask_id == root]
        attempt = max(attempts or [origin.attempt_index]) + 1
        return replace(
            origin,
            subtask_id=_unique_id(f"{root}#a{attempt}", existing_ids),
            order_index=0,
            node_lineage=LINEAGE_NEW,
            attempt_index=attempt,
            origin_subtask_id=root,
            # 선언 노드의 재실행이면 "왜 이 노드가 생겼는가"가 비어 있었다 — 그 자리를
            # 이 재실행을 낳은 변화로 채운다.
            inserted_by=marker,
        ), None

    # -- 간선: 규칙이 계산하고 생성 주체가 적지 않는다 --------------------------

    def _edges_for(
        self,
        *,
        graph: GraphRevision,
        ordered_before: list[GraphNode],
        inserted: tuple[GraphNode, ...],
        insert_at: int,
    ) -> tuple[GraphEdge, ...]:
        """기존 간선은 그대로 두고 삽입이 요구하는 간선만 더한다.

        기존 간선을 다시 계산하지 않는 이유: 선언 그래프의 자료 흐름 간선은 이미
        `tools/fms_console/subtasks.py::derive_edges` 가 `produces`/`consumes` 에서
        유도했고, 그 입력은 payload 에 남아 있지 않다. 다시 만들려면 추측해야 하고,
        추측한 의존은 의존이 아니다.

        더하는 간선은 넷뿐이고 전부 전방이다.
          - 끼운 단계들을 **사슬로** 잇는다.
          - 앞 자리 노드 → 첫 끼운 단계 (끼운 사슬이 떠 있지 않게).
          - 마지막 끼운 단계 → 뒤 자리 노드 (사슬이 본래 흐름으로 돌아오게).
        """
        if not inserted:
            return graph.edges

        edges = list(graph.edges)
        chain = list(inserted)
        for earlier, later in zip(chain, chain[1:]):
            edges.append(GraphEdge(earlier.subtask_id, later.subtask_id, SEQUENCE_ITEM))

        before = ordered_before[insert_at - 1] if insert_at > 0 else None
        after = ordered_before[insert_at] if insert_at < len(ordered_before) else None
        if before is not None:
            edges.append(GraphEdge(before.subtask_id, chain[0].subtask_id, SEQUENCE_ITEM))
        if after is not None:
            edges.append(GraphEdge(chain[-1].subtask_id, after.subtask_id, SEQUENCE_ITEM))

        # 중복 간선은 한 번만. 같은 쌍을 두 번 그리면 화면이 두 번 그린다.
        seen: list[GraphEdge] = []
        for edge in edges:
            if edge not in seen:
                seen.append(edge)
        # 전방 검사는 GraphRevision.__post_init__ 이 한다 — 여기서 걸러 버리면
        # 규칙의 오류가 조용히 사라진다.
        return tuple(seen)

    def _branch_edges_for(
        self,
        *,
        inserted: tuple[GraphNode, ...],
        anchor: GraphNode | None,
        position: Mapping[str, int],
    ) -> tuple[BranchEdge, ...]:
        """선언된 분기를 간선으로 푼다. 실행 간선에 섞지 않는다."""
        by_action = {n.action: n.subtask_id for n in inserted}
        out: list[BranchEdge] = []
        for node in inserted:
            if node.decision is None:
                continue
            for branch in node.decision.branches:
                if branch.to == TARGET_END:
                    target: str | None = None
                elif branch.to == TARGET_ANCHOR:
                    target = anchor.subtask_id if anchor is not None else None
                else:
                    target = by_action.get(branch.to)
                if target is not None and target not in position:
                    target = None
                out.append(BranchEdge(node.subtask_id, target, branch.name, branch.condition))
        return tuple(out)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _first_reason(reasons: Sequence[str]) -> str:
    """무변경 사유 중 **가장 설명력 있는 것**을 고른다.

    "규칙이 없다"보다 "자리가 없다"가, 그보다 "전부 거부됐다"가 더 많은 것을 말한다.
    거부는 요구한 capability 이름까지 들고 있으므로 그것이 남아야 외부 개발 요청으로
    이어진다(AI-B-13).
    """
    priority = (
        REASON_ALL_REFUSED,
        REASON_NO_ANCHOR,
        REASON_NO_RULE,
        REASON_UNKNOWN_CHANGE_KIND,
        REASON_NO_SITUATION_CHANGE,
        REASON_NO_REPLANNER,
    )
    for token in priority:
        if token in reasons:
            return token
    return reasons[0] if reasons else REASON_NO_SITUATION_CHANGE


def _unique_id(candidate: str, taken: Iterable[str]) -> str:
    """결정적으로 충돌을 피한다 — 시계도 난수도 쓰지 않는다."""
    existing = set(taken)
    if candidate not in existing:
        return candidate
    index = 2
    while f"{candidate}~{index}" in existing:
        index += 1
    return f"{candidate}~{index}"
