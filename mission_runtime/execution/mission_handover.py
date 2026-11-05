"""임무를 **다른 담당 노드**로, 또는 **다른 로봇**으로 넘긴다.

implements: AI-B-12 (인수인계도 회차로 보존하고 원 기록을 덮지 않는다),
            AI-B-05 (넘기기 실패는 마지막 정상 상태 유지), AI-B-06 (상태 변화에
            따른 재구성), AI-C-05 (넘길 이유가 없는 배치도 정상 상태),
            AI-C-19 (대상과 사유만 낸다 — 발령도 가용성 판정도 우리 것이 아니다),
            AI-C-20 (전달·수락·완료를 같은 칸에 담지 않는다),
            AI-N-03 (링크 자세는 넘길 사유의 하나다)
tests: tests/test_mission_handover.py

## 두 가지 인수인계는 다른 질문이다

이 저장소에는 이미 두 개의 "핸드오버"가 있고 **둘 다 임무 핸드오버가 아니다**.
`ondevice/link_handover.py` 는 "지금 원격 기능에 기대도 되는가"(자세)와 "같은 구역
안에서 더 나은 피어가 있는가"를 정하고, `ondevice/zone_handover.py` 는 "이 말단이
지금 다른 구역으로 넘어가고 있는가"를 정한다. 둘의 주어는 **링크와 말단**이다.
이 모듈의 주어는 **임무**다.

    custody   담당 노드가 바뀐다.  수행자는 그대로다.   일은 이어진다.
    assignee  수행자가 바뀐다.     담당 노드는 무관하다. 일은 다시 볼 것이 생긴다.

구역을 넘어 담당 엣지가 바뀌는 것(custody)은 **같은 로봇이 같은 일을 계속**하는
것이므로 반쯤 끝난 작업을 다시 할지 묻는 질문이 아예 없다. 로봇을 바꾸는 것
(assignee)은 그 질문이 반드시 생긴다 — 넘겨받은 로봇은 그 자리에 있지도 않았고
중간 상태를 들고 있지도 않다. 그래서 `HandoverDecision.executor_changes` 가 참일
때만 재개 선언을 따진다. 한 종류로 합치면 둘 중 한쪽에 틀린 답을 주게 된다.

## 넘기는 것은 "상태" 이고, 상태가 비면 넘긴 것이 아니다

`StateBaton` 이 실제로 건네지는 것이다 — 노드별 실행 상태·회차·버전. 넘기기가
"끊기지 않는다"고 주장하려면 그 주장을 **검사**해야 하므로, 바톤이 그래프의 노드를
다 덮지 않으면 `state_baton_incomplete` 로 거절한다. 덮지 못한 노드 이름을 함께
낸다. 진행 상태를 들고 오지 않은 출처(예: capability 상태만 가진 서브태스크 개정)는
`execution_state=None` 이고 그것은 PENDING 이 아니다 — 모른다는 뜻이다.

## 넘길 후보가 갈리지 않으면 고르지 않는다

`planning/path_candidates.py::choose` 와 **같은 규칙**이고 사유 토큰도 같은 이름을
쓴다(`candidates_not_separated` · `evidence_insufficient`). 두 로봇이 똑같이
적격이면 1위를 고르지 않고 둘을 함께 낸다. 고르면 "왜 저 로봇인가"에 아무도 답할 수
없고, 그 답 없는 선택이 곧 물리 명령의 대상이 된다(AI-C-19).

거절 사유를 **구분해서** 낸다. 셋은 다음에 할 일이 서로 다르다.

    no_candidate              후보가 없다 — 다른 로봇을 들여야 한다
    evidence_insufficient     후보 상태를 모른다 — 재면 갈릴 수 있다
    candidates_not_separated  쟀는데 비슷하다 — 더 재도 안 갈린다

## 가용성은 소비하고 재판정하지 않는다

`backend_available` 은 백엔드가 업무 전송 상태와 관측 상태를 통합해 낸 판정이고 이
모듈은 그것을 **입력으로 읽는다**(AI-C-19, 절대 준수 원칙 #15). 우리는 "이 로봇은
죽었다"고 정하지 않는다. `observability/availability.py::RemoteFeatureGate` 가 원격
capability 선택에서 같은 경계를 지키고 있고 여기서도 그 경계를 다시 긋지 않는다.

**`None` 은 `False` 가 아니다.** 아직 판정을 못 받은 것을 "사용 불가"로 읽으면 그
순간 우리가 판정한 것이 된다. 그래서 판정이 없는 후보는 `availability_not_received`
로 후보에서 빠지고(모르는 것에 임무를 보내지 않는다), 수행 중인 로봇의 판정이 없는
것은 **넘길 사유가 아니다**.

## 미측정은 0 이 아니다

배터리를 모르면 0% 가 아니다. `battery_pct is None` 은 넘길 사유를 만들지 않고,
후보 쪽에서는 `battery_level_unknown` 으로 빠진다 — `simulation/terminals.py` 가 이미
쓰는 토큰과 같은 이름이다. 선택에서 빠진 이유가 "비었다"와 "못 쟀다"로 갈려야 다음에
무엇을 할지가 달라진다. 배터리 예비선(`reserve_pct`)을 **선언하지 않은 배치**에서는
배터리를 아예 보지 않는다 — 임계값을 코드가 지어내지 않는다.

## 넘긴 기록은 덮지 않는다

`MissionHandoverLedger` 는 append-only 이고 한 인수인계는 회차(`handover_index`)
하나를 받는다. 단계 전이도 기록을 고치지 않고 **새 기록**을 쌓는다(AI-B-12 가 재실행에
요구한 것과 같은 성질이고, `tools/fms_console/overlay.py` 의 장부와 같은 방식이다).
`explain()` 이 "왜 다른 로봇이 하고 있는가"에 답한다.

## 요청과 사실을 같은 칸에 담지 않는다

단계는 `OFFERED → ACCEPTED → COMPLETED` 이고 **담당자는 COMPLETED 에서만 바뀐다**.
`ondevice/zone_handover.py` 가 `switch_to_zone`(요청)과 `confirm_zone()`(사실)을 가른
것과 같은 이유이며, AI-C-20 이 전달·수락·완료를 구분한 것과 같은 구조다. 거절은
단계가 아니라 `HandoverDecision.reason` 이다 — AI-C-20 이 "거부는 실행 상태에 포함하지
않고 별도 수락 결과로" 둔 것과 같다. 중단(`ABANDONED`)되면 담당은 **원래 자리에
남는다**(AI-B-05 의 last-known-good).

같은 사유가 다시 전달돼도 회차는 오르지 않는다 — 식별자는 (종류, 촉발 사유들,
넘기던 쪽)이고 `planning/replanning.py` 가 같은 변화의 재전달로 그래프를 늘리지 않는
것과 같은 성질이다(AI-C-20: 같은 command_id 의 재전달은 다시 물리 실행하지 않는다).
단, **중단된 회차는 막지 않는다** — 중단을 재시도 금지로 읽으면 한 번 실패한 임무를
영원히 넘길 수 없다.

## 우리 것이 아닌 것

물리 명령 발급과 실제 전환 수행은 여기서 하지 않는다. 이 모듈이 내는 것은 **누구에게,
왜** 까지이고 명령은 제어 경계를 거친다(AI-C-19, AI-C-20). 그래프를 고치는 일도 하지
않는다 — 다시 처음부터 할 노드 이름을 낼 뿐이고, 회차를 올린 새 노드를 만드는 일은
`planning/replanning.py` 가 이미 소유한다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Sequence

from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.contracts.capability import CapabilityRequirement, CapabilityState
from mission_runtime.execution.task_graph import NodeState
from mission_runtime.ondevice.link_handover import LinkPosture
from mission_runtime.perception.device_identity import Verdict

# ---------------------------------------------------------------------------
# 어휘
# ---------------------------------------------------------------------------

#: 담당 노드가 바뀐다. 수행자는 그대로이고 일은 이어진다.
KIND_CUSTODY = "custody"
#: 수행자가 바뀐다. 넘겨받은 쪽은 중간 상태를 들고 있지 않다.
KIND_ASSIGNEE = "assignee"

HANDOVER_KINDS: tuple[str, ...] = (KIND_CUSTODY, KIND_ASSIGNEE)

# -- 촉발 사유 ---------------------------------------------------------------
#
# 왜 **지금** 넘기려는가. 여러 개가 동시에 성립할 수 있으므로 하나로 접지 않는다 —
# "배터리도 낮고 링크도 끊겼다"를 하나로 접으면 다음에 무엇을 고쳐야 하는지가 사라진다.

#: 구역 전환이 **확정됐다**(`ondevice/zone_handover.py::confirm_zone` 의 사실).
TRIGGER_ZONE_CONFIRMED = "zone_entry_confirmed"
#: 지금 담당하고 있는 노드에 닿지 않는다.
TRIGGER_CUSTODIAN_LOST = "custodian_unreachable"
#: 백엔드 통합 가용성 판정이 내려갔다. **우리가 내린 판정이 아니다**(원칙 #15).
TRIGGER_BACKEND_UNAVAILABLE = "backend_availability_withdrawn"
#: 그 임무를 받치던 필수 capability 가 사라졌다. `planning/replanning.py` 의
#: `CHANGE_CAPABILITY_LOST` 와 **같은 토큰**이다 — 같은 사실에 이름이 둘이면
#: 재계획과 인수인계가 서로 다른 사실을 말하는 것처럼 보인다(AI-C-01).
TRIGGER_CAPABILITY_LOST = "capability_lost"
#: 선언된 예비선 아래로 내려갔다. 선언이 없으면 이 사유는 **생기지 않는다**.
TRIGGER_BELOW_RESERVE = "battery_below_reserve"
#: 장비가 고장을 신고했다. 코드 해석은 하지 않고 비어 있지 않은지만 본다.
TRIGGER_FAULT_DECLARED = "fault_declared"
#: 링크 자세가 LOCAL_ONLY 다(AI-N-03). 어휘의 정본은 `ondevice/link_handover.py`.
TRIGGER_LINK_LOCAL_ONLY = "link_local_only"
#: 운영자가 넘기라고 했다. 사유가 사람이면 그 사실을 적는다.
TRIGGER_OPERATOR_REQUESTED = "operator_requested"

HANDOVER_TRIGGERS: tuple[str, ...] = (
    TRIGGER_ZONE_CONFIRMED,
    TRIGGER_CUSTODIAN_LOST,
    TRIGGER_BACKEND_UNAVAILABLE,
    TRIGGER_CAPABILITY_LOST,
    TRIGGER_BELOW_RESERVE,
    TRIGGER_FAULT_DECLARED,
    TRIGGER_LINK_LOCAL_ONLY,
    TRIGGER_OPERATOR_REQUESTED,
)

# -- 단계 (AI-C-20 과 같은 구조) ---------------------------------------------

PHASE_OFFERED = "OFFERED"        # 넘기겠다고 **요청**했다. 담당은 아직 그대로다.
PHASE_ACCEPTED = "ACCEPTED"      # 받는 쪽이 받을 수 있다고 했다. 아직 사실이 아니다.
PHASE_COMPLETED = "COMPLETED"    # 받는 쪽이 상태를 들고 있다. **여기서만** 담당이 바뀐다.
PHASE_ABANDONED = "ABANDONED"    # 끝내 넘기지 못했다. 담당은 원래 자리에 남는다.

HANDOVER_PHASES: tuple[str, ...] = (
    PHASE_OFFERED, PHASE_ACCEPTED, PHASE_COMPLETED, PHASE_ABANDONED,
)

#: 허용 전이. 여기 없는 전이는 거부한다 — `execution/task_graph.py` 의
#: `_ALLOWED` 와 같은 이유다(화면이 보는 단계가 임의로 뒤집히면 안 된다).
_ALLOWED_PHASES: dict[str, frozenset[str]] = {
    PHASE_OFFERED: frozenset({PHASE_ACCEPTED, PHASE_ABANDONED}),
    PHASE_ACCEPTED: frozenset({PHASE_COMPLETED, PHASE_ABANDONED}),
    PHASE_COMPLETED: frozenset(),
    PHASE_ABANDONED: frozenset(),
}

# -- 결과 사유 ---------------------------------------------------------------

REASON_HANDED = "handed_over"                        # 대상이 정해졌다
REASON_NO_TRIGGER = "no_trigger"                     # 넘길 이유가 없다 — 정상이다
REASON_NO_CANDIDATE = "no_candidate"                 # 후보가 없다
REASON_NOT_SEPARATED = "candidates_not_separated"    # 쟀는데 비슷하다
REASON_EVIDENCE_INSUFFICIENT = "evidence_insufficient"  # 후보 상태를 모른다
REASON_IDENTITY_UNRESOLVED = "identity_unresolved"   # 같은 개체인지 못 가렸다
REASON_NO_CUSTODIAN_DECLARED = "no_custodian_declared"  # 그 구역의 담당 선언이 없다
REASON_CUSTODIAN_UNCHANGED = "custodian_unchanged"   # 넘길 데가 지금 그 자리다
REASON_ALREADY_HANDED_OVER = "already_handed_over"   # 같은 사유로 이미 넘겼다
REASON_BATON_INCOMPLETE = "state_baton_incomplete"   # 넘길 상태가 비었다

HANDOVER_REASONS: tuple[str, ...] = (
    REASON_HANDED,
    REASON_NO_TRIGGER,
    REASON_NO_CANDIDATE,
    REASON_NOT_SEPARATED,
    REASON_EVIDENCE_INSUFFICIENT,
    REASON_IDENTITY_UNRESOLVED,
    REASON_NO_CUSTODIAN_DECLARED,
    REASON_CUSTODIAN_UNCHANGED,
    REASON_ALREADY_HANDED_OVER,
    REASON_BATON_INCOMPLETE,
)

# -- 후보 탈락 사유 ----------------------------------------------------------

REJECT_IS_CURRENT_ASSIGNEE = "is_current_assignee"
#: 백엔드 통합 판정이 "사용 불가"다. 우리가 그렇게 정한 것이 아니다(원칙 #15).
REJECT_BACKEND_UNAVAILABLE = "backend_marked_unavailable"
#: 통합 판정을 **아직 못 받았다**. 위와 다른 사실이고 같은 칸에 담지 않는다.
REJECT_AVAILABILITY_NOT_RECEIVED = "availability_not_received"
#: 필수 capability 가 없다 — `CapabilityRequirement.evaluate` 가 DISABLED 를 냈다.
REJECT_CAPABILITY_SHORTFALL = "required_capability_missing"
#: 예비선이 선언된 배치에서 배터리를 못 쟀다. `simulation/terminals.py` 와 같은 토큰.
REJECT_BATTERY_UNKNOWN = "battery_level_unknown"
#: 쟀고, 예비선 아래였다.
REJECT_BELOW_RESERVE = "insufficient_battery"
#: 그 장비도 고장을 신고했다.
REJECT_FAULT_DECLARED = "fault_declared"

CANDIDATE_REJECTION_REASONS: tuple[str, ...] = (
    REJECT_IS_CURRENT_ASSIGNEE,
    REJECT_BACKEND_UNAVAILABLE,
    REJECT_AVAILABILITY_NOT_RECEIVED,
    REJECT_CAPABILITY_SHORTFALL,
    REJECT_BATTERY_UNKNOWN,
    REJECT_BELOW_RESERVE,
    REJECT_FAULT_DECLARED,
)

#: 이 사유들로 빠진 후보는 "부적합"이 아니라 **모르는 것**이다. 전부 이 사유로
#: 빠졌으면 결과 사유가 `no_candidate` 가 아니라 `evidence_insufficient` 다 —
#: 재면 갈릴 수 있는 것과 아무도 없는 것은 다음에 할 일이 다르다.
_MEASUREMENT_REJECTIONS: frozenset[str] = frozenset({
    REJECT_AVAILABILITY_NOT_RECEIVED,
    REJECT_BATTERY_UNKNOWN,
})

# -- 재개 선언 ---------------------------------------------------------------

RESUME = "resume"              # 이어서 한다 — **선언이 그렇게 적혀 있다**
RESTART = "restart"            # 처음부터 다시 한다 — 선언이 그렇게 적혀 있다
RESUMPTION_UNDECLARED = "undeclared"  # 선언이 없다. **지어내지 않는다**

RESUMPTIONS: tuple[str, ...] = (RESUME, RESTART, RESUMPTION_UNDECLARED)

#: 넘길 때 "이어서 할까 다시 할까"를 물어야 하는 상태. 끝난 노드는 물을 것이 없고
#: 시작하지 않은 노드도 없다. 실패 노드는 재계획(`planning/replanning.py`)의 일이다.
IN_FLIGHT_STATES: frozenset[str] = frozenset({NodeState.EXECUTING.value})

#: custody 인수인계에서 받는 쪽의 개체 판정으로 **통과시키는** 값.
#: `CONTRADICTED`·`AMBIGUOUS` 는 통과하지 않는다 — 못 가린 개체에 임무 상태를
#: 건네면 그 상태는 다른 로봇의 것이 된다(`perception/device_identity.py` 의 주장).
ACCEPTED_IDENTITY_VERDICTS: frozenset[str] = frozenset({
    Verdict.CONFIRMED.value, Verdict.SOLE_CANDIDATE.value,
})

#: 같은 등급의 두 후보가 이 퍼센트포인트 안에 있으면 **갈리지 않았다**고 본다.
#: 측정으로 정한 값이 아니라 어림이고, 그래서 인자로 바꿀 수 있다
#: (`planning/path_candidates.py::DEFAULT_RISK_MARGIN` 과 같은 성격).
DEFAULT_RESERVE_MARGIN_PCT = 10.0

#: capability 등급의 순위. DEGRADED 는 후보에서 빼지 않는다 — 선택 결손은 축소이고
#: 실패가 아니다(AI-C-05). 다만 ACTIVE 보다 뒤에 세운다.
_STATE_RANK: dict[str, int] = {
    CapabilityState.ACTIVE.value: 0,
    CapabilityState.DEGRADED.value: 1,
}


class HandoverPhaseRejected(Exception):
    """허용되지 않은 단계 전이. 거부는 예외이고 단계가 아니다 —
    `execution/task_graph.py::TransitionRejected` 와 같은 이유다."""


# ---------------------------------------------------------------------------
# 넘기는 것 — 상태 바톤
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BatonEntry:
    """노드 하나의 넘길 상태.

    `execution_state is None` 은 **"이 출처가 진행 상태를 들고 있지 않다"** 는 뜻이고
    PENDING 이 아니다. capability 상태만 가진 출처(서브태스크 개정)에서 바톤을 만들면
    이 칸이 빈다 — 그 빈 칸을 PENDING 으로 채우면 아직 시작도 안 한 일로 읽히고,
    실제로 돌고 있던 일이 조용히 사라진다.
    """

    node_id: str
    execution_state: str | None = None
    attempt_index: int = 1
    #: 재개 선언을 찾는 열쇠(노드의 문법 라벨 또는 action). 자유 문자열이고 이
    #: 모듈은 값으로 분기하지 않는다.
    work_kind: str | None = None
    origin_node_id: str | None = None

    @property
    def in_flight(self) -> bool:
        return self.execution_state in IN_FLIGHT_STATES

    def as_payload(self) -> dict:
        return {
            dd.TASK_NODE_ID: self.node_id,
            dd.TASK_NODE_STATE: self.execution_state,
            dd.TASK_ATTEMPT: self.attempt_index,
            "work_kind": self.work_kind,
            dd.ORIGIN_TASK_NODE_ID: self.origin_node_id,
        }


@dataclass(frozen=True)
class StateBaton:
    """임무 실행 상태 한 벌. **이것이 실제로 건네지는 것이다.**

    바톤이 불완전하면 인수인계를 거절한다. "끊기지 않는다"는 주장을 검사 없이 적어
    두면 그 주장은 넘기는 순간에만 참이고, 끊긴 사실은 화면에서 발견된다.
    """

    mission_id: str
    entries: tuple[BatonEntry, ...] = ()
    #: 그래프 개정 번호(`planning/replanning.py::GraphRevision.revision`). 모르면 None.
    graph_revision: int | None = None
    #: 이 임무를 수행하던 장비. 넘겨받는 쪽이 같은 개체인지 가릴 때의 기준이다.
    device_id: str | None = None
    #: 적용 중인 버전들(구성·모델·보정). 해석하지 않고 **그대로** 넘긴다.
    versions: Mapping[str, str] = field(default_factory=dict)
    captured_at: float | None = None

    @property
    def missing_execution_state(self) -> tuple[str, ...]:
        """진행 상태를 모르는 노드들. 비어 있어야 넘길 수 있다."""
        return tuple(e.node_id for e in self.entries if e.execution_state is None)

    @property
    def complete(self) -> bool:
        return bool(self.entries) and not self.missing_execution_state

    @property
    def in_flight(self) -> tuple[BatonEntry, ...]:
        return tuple(e for e in self.entries if e.in_flight)

    def digest(self) -> str:
        """어느 상태를 넘겼는지 **장부에 적을 수 있는** 지문. 결정적이다.

        시계도 난수도 쓰지 않는다 — 같은 상태면 같은 지문이어야 "넘긴 것과 받은 것이
        같은가"를 뒤에서 비교할 수 있다.
        """
        canonical = "|".join(
            f"{e.node_id}:{e.execution_state}:{e.attempt_index}"
            for e in sorted(self.entries, key=lambda e: e.node_id)
        )
        canonical += f"|rev={self.graph_revision}|dev={self.device_id}"
        canonical += "|" + ",".join(f"{k}={self.versions[k]}" for k in sorted(self.versions))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    def as_payload(self) -> dict:
        return {
            dd.MISSION_ID: self.mission_id,
            dd.GRAPH_REVISION: self.graph_revision,
            dd.DEVICE_ID: self.device_id,
            "versions": dict(self.versions),
            "captured_at": self.captured_at,
            "state_baton_digest": self.digest(),
            "complete": self.complete,
            "missing_execution_state": list(self.missing_execution_state),
            "entries": [e.as_payload() for e in self.entries],
        }


def baton_from_task_graph(graph, *, versions: Mapping[str, str] | None = None,
                          captured_at: float | None = None) -> StateBaton:
    """`execution/task_graph.py::TaskGraph` 에서 바톤을 뜬다. 그래프를 바꾸지 않는다.

    장비 id 는 노드들이 **한 목소리일 때만** 싣는다. 서로 다른 장비를 가리키는
    노드가 섞여 있으면 하나를 골라 적지 않는다 — 고르면 그것이 개체 판정이 된다.
    """
    devices = {n.target_device_id for n in graph.nodes if n.target_device_id}
    return StateBaton(
        mission_id=graph.mission_id,
        entries=tuple(
            BatonEntry(
                node_id=n.node_id,
                execution_state=n.state.value,
                attempt_index=n.attempt,
                work_kind=n.node_kind,
                origin_node_id=n.origin_node_id,
            )
            for n in sorted(graph.nodes, key=lambda n: n.node_id)
        ),
        device_id=next(iter(devices)) if len(devices) == 1 else None,
        versions=dict(versions or {}),
        captured_at=captured_at,
    )


def baton_from_revision(revision, *, execution_states: Mapping[str, str] | None = None,
                        mission_id: str | None = None, device_id: str | None = None,
                        versions: Mapping[str, str] | None = None,
                        captured_at: float | None = None) -> StateBaton:
    """서브태스크 개정(`planning/replanning.py::GraphRevision`)에서 바톤을 뜬다.

    그 개정의 노드 `state` 는 **capability 상태**(ACTIVE/DEGRADED/DISABLED)이고 실행
    진행 상태가 아니다. 두 축을 같은 칸에 담으면 "쓸 수 있다"가 "끝났다"로 읽힌다.
    그래서 진행 상태는 그것을 소유한 쪽이 `execution_states` 로 넣어 주고, 넣지 않은
    노드는 **빈 칸으로 남아** `state_baton_incomplete` 로 드러난다.

    밀려난(superseded) 노드는 살아 있는 일이 아니므로 바톤에서 빠진다 — 그 노드에
    진행 상태를 요구하면 완전한 바톤을 만들 수 없다. 이력은 개정이 들고 있다.

    개정 자료형을 import 하지 않고 속성으로 읽는다. `execution/` 이 `planning/` 을
    import 하면 계층이 거꾸로 되고, 거꾸로 된 의존은 다음에 순환이 된다.
    """
    states = dict(execution_states or {})
    nodes = [n for n in revision.ordered() if not getattr(n, "is_superseded", False)]
    return StateBaton(
        mission_id=mission_id or str(getattr(revision, "graph_id", "") or ""),
        entries=tuple(
            BatonEntry(
                node_id=n.subtask_id,
                execution_state=states.get(n.subtask_id),
                attempt_index=getattr(n, "attempt_index", 1),
                work_kind=getattr(n, "action", None),
                origin_node_id=getattr(n, "origin_subtask_id", None),
            )
            for n in nodes
        ),
        graph_revision=getattr(revision, "revision", None),
        device_id=device_id,
        versions=dict(versions or {}),
        captured_at=captured_at,
    )


# ---------------------------------------------------------------------------
# 반쯤 끝난 일을 어떻게 할지는 **선언이 정한다**
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NodeResumption:
    """넘겨받는 쪽이 그 노드를 어떻게 해야 하는가. 셋 중 하나이고 셋째는 "모른다"다."""

    node_id: str
    resumption: str
    work_kind: str | None = None

    @property
    def declared(self) -> bool:
        return self.resumption != RESUMPTION_UNDECLARED

    def as_payload(self) -> dict:
        return {
            dd.TASK_NODE_ID: self.node_id,
            "resumption": self.resumption,
            "work_kind": self.work_kind,
        }


@dataclass(frozen=True)
class ResumptionPolicy:
    """어떤 일이 이어지고 어떤 일이 처음부터인지의 **선언**.

    태스크마다 다르고 규칙으로 유도할 수 없다 — 촬영을 반쯤 한 것은 이어서 할 수
    있지만 집어 든 물건을 반쯤 옮긴 것은 그렇지 않다. 그 차이는 도메인 지식이므로
    데이터로 선언하고, 선언이 없으면 `undeclared` 를 낸다. 기본값을 "이어서 한다"로
    두면 선언을 깜박한 배치가 조용히 위험한 쪽으로 돈다.

    `by_node_id` 가 `by_work_kind` 보다 우선한다 — 한 노드만 예외인 경우가 있다.
    """

    by_work_kind: Mapping[str, str] = field(default_factory=dict)
    by_node_id: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for source in (self.by_work_kind, self.by_node_id):
            for key, value in source.items():
                if value not in (RESUME, RESTART):
                    raise ValueError(
                        f"{key!r}: resumption must be {RESUME!r} or {RESTART!r}, "
                        f"not {value!r} — 모름은 선언하지 않는 것으로 표현한다"
                    )

    def for_entry(self, entry: BatonEntry) -> NodeResumption:
        declared = self.by_node_id.get(entry.node_id)
        if declared is None and entry.work_kind is not None:
            declared = self.by_work_kind.get(entry.work_kind)
        return NodeResumption(
            node_id=entry.node_id,
            resumption=declared or RESUMPTION_UNDECLARED,
            work_kind=entry.work_kind,
        )


# ---------------------------------------------------------------------------
# 로봇 상태 — 사실이고 판정이 아니다
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RobotCondition:
    """한 로봇의 지금 상태. **전부 받은 사실이고 여기서 판정하지 않는다.**

    `backend_available` 은 백엔드가 업무 전송 상태와 관측 상태를 통합해 낸 판정이다
    (AI-O-04, 원칙 #15). `None` 은 "아직 못 받았다"이고 `False` 와 **다른 사실**이다.

    `battery_pct` 의 `None` 은 0% 가 아니다. 단위는 퍼센트이고
    `simulation/terminals.py` 의 `battery_pct` 와 같은 이름·같은 단위를 쓴다 —
    분수와 퍼센트를 섞으면 10% 가 1000% 로 읽히는 날이 온다.
    """

    robot_id: str
    backend_available: bool | None = None
    #: 이 로봇이 지금 낼 수 있는 capability kind 들.
    capability_kinds: frozenset[str] = frozenset()
    battery_pct: float | None = None
    #: 장비가 신고한 고장 코드. 해석하지 않고 비어 있는지만 본다.
    fault_codes: tuple[str, ...] = ()
    #: `ondevice/link_handover.py::LinkPosture` 의 값. 모르면 None.
    link_posture: str | None = None

    def capability_state(self, requirement: CapabilityRequirement) -> CapabilityState:
        """`contracts/capability.py` 가 판정한다. 여기서 다시 세지 않는다."""
        return requirement.evaluate(set(self.capability_kinds))

    @property
    def unmeasured(self) -> tuple[str, ...]:
        """재려 했으나 못 얻은 것들. 0 으로 채우지 않고 **이름으로 남긴다**."""
        out: list[str] = []
        if self.backend_available is None:
            out.append(dd.TASK_TRANSPORT_ALIVE)
        if self.battery_pct is None:
            out.append("battery_pct")
        if self.link_posture is None:
            out.append(dd.LINK_POSTURE)
        return tuple(out)

    def as_payload(self) -> dict:
        return {
            dd.DEVICE_ID: self.robot_id,
            "backend_available": self.backend_available,
            "capability_kinds": sorted(self.capability_kinds),
            "battery_pct": self.battery_pct,
            "fault_codes": list(self.fault_codes),
            dd.LINK_POSTURE: self.link_posture,
            "unmeasured": list(self.unmeasured),
        }


def triggers_for(condition: RobotCondition | None,
                 *,
                 requirement: CapabilityRequirement | None = None,
                 reserve_pct: float | None = None) -> tuple[str, ...]:
    """이 로봇 상태가 임무를 **넘겨야 할 사유**를 만드는가.

    만들지 않는 네 경우를 분명히 둔다.

    * `backend_available is None` — 판정을 못 받았을 뿐이다. 이것을 사유로 세면 그
      순간 우리가 가용성을 판정한 것이 된다(원칙 #15).
    * `battery_pct is None` — 못 쟀다. 0% 가 아니다.
    * `reserve_pct is None` — 예비선 선언이 없는 배치다. 임계값을 지어내지 않는다.
    * capability 가 `DEGRADED` — 선택 기능 결손은 축소이고 임무를 옮길 이유가
      아니다(AI-C-05, 절대 준수 원칙 #4).
    """
    if condition is None:
        return ()
    out: list[str] = []
    if condition.backend_available is False:
        out.append(TRIGGER_BACKEND_UNAVAILABLE)
    if condition.fault_codes:
        out.append(TRIGGER_FAULT_DECLARED)
    if condition.link_posture == LinkPosture.LOCAL_ONLY.value:
        out.append(TRIGGER_LINK_LOCAL_ONLY)
    if requirement is not None and condition.capability_state(requirement) is CapabilityState.DISABLED:
        out.append(TRIGGER_CAPABILITY_LOST)
    if reserve_pct is not None and condition.battery_pct is not None:
        if condition.battery_pct < reserve_pct:
            out.append(TRIGGER_BELOW_RESERVE)
    return tuple(out)


# ---------------------------------------------------------------------------
# 결정 — 고르지 않은 것도 결정이다
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateRejection:
    """후보 하나가 왜 빠졌는가. **버리지 않고 남긴다** — 다음에 무엇을 고치면
    그 로봇이 후보가 되는지의 답이다."""

    robot_id: str
    reason: str
    detail: str | None = None

    def as_payload(self) -> dict:
        return {dd.DEVICE_ID: self.robot_id, "candidate_rejection_reason": self.reason,
                "detail": self.detail}


@dataclass(frozen=True)
class HandoverDecision:
    """인수인계 한 건의 판단. **넘기지 않기로 한 것도 결과이고 예외가 아니다.**

    `target_id` 가 `None` 이면 `reason` 이 왜인지 말한다. 두 칸을 한 칸으로 합치면
    "못 골랐다"와 "고를 필요가 없었다"가 같은 모양이 된다.
    """

    mission_id: str
    kind: str
    trigger: tuple[str, ...] = ()
    target_id: str | None = None
    source_id: str | None = None
    reason: str = REASON_NO_TRIGGER
    #: 같은 등급에서 갈리지 않은 후보들. 운영자가 고를 수 있게 **함께** 낸다.
    tied: tuple[str, ...] = ()
    considered: int = 0
    margin: float | None = None
    rejections: tuple[CandidateRejection, ...] = ()
    #: assignee 인수인계에서 넘겨받는 쪽이 중간 상태의 일을 어떻게 할지.
    resumption: tuple[NodeResumption, ...] = ()
    #: 못 쟀던 것들. 판단에 들어가지 않았다는 사실의 기록이다.
    unmeasured: tuple[str, ...] = ()
    baton: StateBaton | None = None

    @property
    def decided(self) -> bool:
        return self.target_id is not None

    @property
    def executor_changes(self) -> bool:
        """수행자가 바뀌는가. custody 는 바뀌지 않으므로 재개를 따질 일이 없다."""
        return self.kind == KIND_ASSIGNEE

    @property
    def needs_resumption_decision(self) -> tuple[str, ...]:
        """선언이 없어 **우리가 답하지 못하는** 노드들. 지어내지 않고 올린다."""
        return tuple(r.node_id for r in self.resumption if not r.declared)

    @property
    def restart_node_ids(self) -> tuple[str, ...]:
        """처음부터 다시 할 노드들. 회차를 올린 새 노드를 만드는 일은 우리 것이
        아니다 — `planning/replanning.py` 가 그 계보를 이미 소유한다."""
        return tuple(r.node_id for r in self.resumption if r.resumption == RESTART)

    @property
    def resume_node_ids(self) -> tuple[str, ...]:
        return tuple(r.node_id for r in self.resumption if r.resumption == RESUME)

    @property
    def marker(self) -> str:
        """같은 사유의 재전달을 알아보는 식별자. 넘길 **대상**은 들어가지 않는다 —
        원인이 같으면 같은 사실이고, 대상은 그 사실의 결과다
        (`planning/replanning.py` 가 (action, 변화) 로 식별하는 것과 같다)."""
        return f"{self.kind}|{','.join(sorted(self.trigger))}|{self.source_id}"

    def as_payload(self) -> dict:
        body: dict[str, Any] = {
            dd.MISSION_ID: self.mission_id,
            "handover_kind": self.kind,
            "handover_trigger": list(self.trigger),
            "handover_reason": self.reason,
            "target_id": self.target_id,
            "source_id": self.source_id,
            "decided": self.decided,
            "executor_changes": self.executor_changes,
            "considered": self.considered,
            "tied": list(self.tied),
            "rejections": [r.as_payload() for r in self.rejections],
            "unmeasured": list(self.unmeasured),
            "resumption": [r.as_payload() for r in self.resumption],
            "needs_resumption_decision": list(self.needs_resumption_decision),
            "restart_node_ids": list(self.restart_node_ids),
            "resume_node_ids": list(self.resume_node_ids),
        }
        if self.margin is not None:
            body["margin"] = round(self.margin, 4)
        if self.baton is not None:
            body["state_baton"] = self.baton.as_payload()
        return body


# ---------------------------------------------------------------------------
# 장부 — append-only
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HandoverRecord:
    """인수인계 한 회차의 한 단계. **고치지 않고 쌓는다**(AI-B-12).

    같은 `handover_index` 를 가진 기록이 여러 개 있고 그것이 그 회차의 이력이다.
    단계가 바뀔 때 앞 기록을 고치면 "요청은 했는데 완료되지 않았다"가 사라진다.
    """

    mission_id: str
    handover_index: int
    kind: str
    phase: str
    from_id: str | None
    to_id: str | None
    trigger: tuple[str, ...] = ()
    reason: str | None = None
    at: float | None = None
    marker: str = ""
    baton_digest: str | None = None
    #: 단계가 바뀐 사유(중단 사유 등). 비어 있을 수 있다.
    detail: str | None = None

    def as_payload(self) -> dict:
        return {
            dd.MISSION_ID: self.mission_id,
            "handover_index": self.handover_index,
            "handover_kind": self.kind,
            "handover_phase": self.phase,
            "from_id": self.from_id,
            "to_id": self.to_id,
            "handover_trigger": list(self.trigger),
            "handover_reason": self.reason,
            dd.OCCURRED_AT: self.at,
            "state_baton_digest": self.baton_digest,
            "detail": self.detail,
        }


class MissionHandoverLedger:
    """누가 왜 무엇을 넘겼는지의 장부. **지우지 않고 덮지 않는다.**

    담당자는 `COMPLETED` 기록에서만 바뀐다 — 요청과 사실을 같은 칸에 담으면
    "요청했는데 실패한 인수인계"가 성공한 것처럼 보인다
    (`ondevice/zone_handover.py` 가 같은 이유로 요청과 확정을 갈라 두었다).
    """

    def __init__(self) -> None:
        self._records: list[HandoverRecord] = []

    # -- 쓰기 ---------------------------------------------------------------

    def offer(self, decision: HandoverDecision, *, at: float | None = None) -> HandoverRecord:
        """결정 하나를 회차로 올린다. 담당은 **아직 바뀌지 않는다**.

        고르지 못한 결정을 올리는 것은 배선 오류다 — 운영 중의 거절은 사유로 끝나고
        장부에 올라갈 일이 아니다(`planning/replanning.py` 가 등록 오류를 예외로,
        운영 거절을 사유로 가른 것과 같다).
        """
        if not decision.decided:
            raise ValueError(
                f"{decision.mission_id}: cannot offer an undecided handover "
                f"({decision.reason})"
            )
        index = self.next_index(decision.mission_id)
        record = HandoverRecord(
            mission_id=decision.mission_id,
            handover_index=index,
            kind=decision.kind,
            phase=PHASE_OFFERED,
            from_id=decision.source_id,
            to_id=decision.target_id,
            trigger=decision.trigger,
            reason=decision.reason,
            at=at,
            marker=decision.marker,
            baton_digest=decision.baton.digest() if decision.baton is not None else None,
        )
        self._records.append(record)
        return record

    def _advance(self, mission_id: str, handover_index: int, phase: str,
                 *, at: float | None, detail: str | None) -> HandoverRecord:
        last = self.latest(mission_id, handover_index)
        if last is None:
            raise KeyError(f"{mission_id}: no handover with index {handover_index}")
        if phase not in _ALLOWED_PHASES[last.phase]:
            raise HandoverPhaseRejected(
                f"{mission_id}#{handover_index}: {last.phase} -> {phase} is not allowed"
            )
        record = replace(last, phase=phase, at=at, detail=detail)
        self._records.append(record)
        return record

    def accept(self, mission_id: str, handover_index: int, *,
               at: float | None = None, detail: str | None = None) -> HandoverRecord:
        """받는 쪽이 받을 수 있다고 했다. 상태는 아직 넘어가지 않았다(AI-C-20)."""
        return self._advance(mission_id, handover_index, PHASE_ACCEPTED, at=at, detail=detail)

    def complete(self, mission_id: str, handover_index: int, *,
                 at: float | None = None, detail: str | None = None) -> HandoverRecord:
        """받는 쪽이 상태를 들고 있다. **여기서 담당이 바뀐다.**"""
        return self._advance(mission_id, handover_index, PHASE_COMPLETED, at=at, detail=detail)

    def abandon(self, mission_id: str, handover_index: int, *, reason: str,
                at: float | None = None) -> HandoverRecord:
        """끝내 넘기지 못했다. 담당은 **원래 자리에 남는다**(AI-B-05 last-known-good).

        중단은 삭제가 아니라 기록이다. 그리고 같은 사유의 재시도를 막지 않는다 —
        한 번 실패한 인수인계를 영원히 금지하면 임무가 그 로봇에 갇힌다.
        """
        return self._advance(mission_id, handover_index, PHASE_ABANDONED, at=at, detail=reason)

    # -- 읽기 ---------------------------------------------------------------

    def records(self, mission_id: str | None = None) -> tuple[HandoverRecord, ...]:
        if mission_id is None:
            return tuple(self._records)
        return tuple(r for r in self._records if r.mission_id == mission_id)

    def next_index(self, mission_id: str) -> int:
        existing = [r.handover_index for r in self.records(mission_id)]
        return (max(existing) + 1) if existing else 1

    def latest(self, mission_id: str, handover_index: int) -> HandoverRecord | None:
        for record in reversed(self._records):
            if record.mission_id == mission_id and record.handover_index == handover_index:
                return record
        return None

    def open_markers(self, mission_id: str) -> frozenset[str]:
        """아직 살아 있는 사유들 — 진행 중이거나 완료된 회차의 식별자.

        **중단된 회차는 빠진다.** 중단을 재시도 금지로 읽지 않기 위한 자리다.
        """
        latest: dict[int, HandoverRecord] = {}
        for record in self.records(mission_id):
            latest[record.handover_index] = record
        return frozenset(
            r.marker for r in latest.values() if r.phase != PHASE_ABANDONED and r.marker
        )

    def _last_completed(self, mission_id: str, kind: str) -> HandoverRecord | None:
        for record in reversed(self.records(mission_id)):
            if record.kind == kind and record.phase == PHASE_COMPLETED:
                return record
        return None

    def current_custodian(self, mission_id: str) -> str | None:
        """완료된 custody 인수인계의 도착지. 없으면 `None` — 장부가 모른다는 뜻이고
        호출자의 선언이 그대로 유효하다."""
        record = self._last_completed(mission_id, KIND_CUSTODY)
        return record.to_id if record is not None else None

    def current_assignee(self, mission_id: str) -> str | None:
        record = self._last_completed(mission_id, KIND_ASSIGNEE)
        return record.to_id if record is not None else None

    def explain(self, mission_id: str) -> tuple[dict, ...]:
        """**"왜 다른 로봇이 하고 있는가"** 의 답. 완료된 수행자 교체의 사슬이다."""
        return tuple(
            {
                "handover_index": r.handover_index,
                "from_id": r.from_id,
                "to_id": r.to_id,
                "handover_trigger": list(r.trigger),
                dd.OCCURRED_AT: r.at,
            }
            for r in self.records(mission_id)
            if r.kind == KIND_ASSIGNEE and r.phase == PHASE_COMPLETED
        )

    def as_payload(self, mission_id: str) -> dict:
        """조회 전용 한 덩어리(AI-O-06). 이 경로로 상태를 바꿀 수 없다."""
        return {
            dd.MISSION_ID: mission_id,
            "custodian_node_id": self.current_custodian(mission_id),
            "assignee_id": self.current_assignee(mission_id),
            "handover_count": self.next_index(mission_id) - 1,
            "records": [r.as_payload() for r in self.records(mission_id)],
            "why_this_assignee": list(self.explain(mission_id)),
        }


# ---------------------------------------------------------------------------
# 판단기
# ---------------------------------------------------------------------------


@dataclass
class MissionHandoverPlanner:
    """두 종류의 인수인계를 판단한다. **대상과 사유까지이고 발령은 하지 않는다.**

    `custodian_by_zone` 은 구역 → 담당 노드의 **선언**이고 비어 있는 배치가 정상이다
    (그 배치는 custody 인수인계를 하지 않는다 — AI-C-05). 담당 노드를 구역에서
    추측해 만들지 않는다.

    `reserve_pct` 가 `None` 인 배치에서는 배터리를 보지 않는다. 임계값을 코드가
    지어내면 그 숫자가 어디서 왔는지 아무도 모른다.
    """

    ledger: MissionHandoverLedger = field(default_factory=MissionHandoverLedger)
    custodian_by_zone: Mapping[str, str] = field(default_factory=dict)
    resumption_policy: ResumptionPolicy = field(default_factory=ResumptionPolicy)
    reserve_pct: float | None = None
    reserve_margin_pct: float = DEFAULT_RESERVE_MARGIN_PCT
    accepted_identity_verdicts: frozenset[str] = ACCEPTED_IDENTITY_VERDICTS

    # -- (1) 담당 노드가 바뀐다 ---------------------------------------------

    def plan_custody(
        self,
        baton: StateBaton,
        *,
        zone_entry: Any | None = None,
        custodian_unreachable: bool = False,
        current_custodian: str | None = None,
        identity_verdict: str | Verdict | None = None,
        operator_requested: bool = False,
    ) -> HandoverDecision:
        """구역이 바뀌어 담당 노드를 넘긴다. **수행자는 그대로다.**

        `zone_entry` 는 `ondevice/zone_handover.py::ZoneEntry` — 전환이 **실제로
        일어났다는 사실**이다. 전환 *요청*(`switch_to_zone`)으로는 넘기지 않는다.
        그쪽은 아직 일어나지 않은 일이고, 일어나지 않은 전환으로 담당을 옮기면
        실패한 전환 뒤에 임무 상태가 아무도 없는 노드에 남는다.

        `identity_verdict` 는 받는 쪽이 "이 장비가 바톤에 적힌 그 개체인가"를 가린
        결과다(`perception/device_identity.py`). `None` 은 그 질문이 제기되지
        않았다는 뜻이고(선언된 장비가 오버레이로 자기를 밝히는 보통의 경우),
        값이 들어오면 **그것이 통과를 가른다**.
        """
        triggers: list[str] = []
        zone_id: str | None = None
        if zone_entry is not None:
            zone_id = getattr(zone_entry, "zone_id", None) or None
            if zone_id:
                triggers.append(TRIGGER_ZONE_CONFIRMED)
        if custodian_unreachable:
            triggers.append(TRIGGER_CUSTODIAN_LOST)
        if operator_requested:
            triggers.append(TRIGGER_OPERATOR_REQUESTED)

        source = (current_custodian
                  if current_custodian is not None
                  else self.ledger.current_custodian(baton.mission_id))

        def answer(reason: str, *, target: str | None = None,
                   unmeasured: Iterable[str] = ()) -> HandoverDecision:
            return HandoverDecision(
                mission_id=baton.mission_id,
                kind=KIND_CUSTODY,
                trigger=tuple(triggers),
                target_id=target,
                source_id=source,
                reason=reason,
                baton=baton,
                unmeasured=tuple(unmeasured),
            )

        if not triggers:
            return answer(REASON_NO_TRIGGER)
        if not baton.complete:
            return answer(REASON_BATON_INCOMPLETE,
                          unmeasured=baton.missing_execution_state)

        target = self.custodian_by_zone.get(zone_id) if zone_id else None
        if target is None:
            # 담당을 지어내지 않는다. 선언이 없는 구역은 선언을 더하는 일이고
            # 코드를 고치는 일이 아니다(절대 준수 원칙 #7).
            return answer(REASON_NO_CUSTODIAN_DECLARED)
        if target == source:
            return answer(REASON_CUSTODIAN_UNCHANGED)

        verdict = (identity_verdict.value
                   if isinstance(identity_verdict, Verdict) else identity_verdict)
        if verdict is not None and verdict not in self.accepted_identity_verdicts:
            return answer(REASON_IDENTITY_UNRESOLVED)

        probe = HandoverDecision(
            mission_id=baton.mission_id, kind=KIND_CUSTODY,
            trigger=tuple(triggers), source_id=source,
        )
        if probe.marker in self.ledger.open_markers(baton.mission_id):
            return answer(REASON_ALREADY_HANDED_OVER)

        # custody 는 수행자를 바꾸지 않으므로 재개 선언을 따지지 않는다. 같은 로봇이
        # 같은 일을 계속하고 있고, 바뀐 것은 그 상태를 **누가 들고 보는가**다.
        return answer(REASON_HANDED, target=target)

    # -- (2) 수행자가 바뀐다 -------------------------------------------------

    def plan_assignee(
        self,
        baton: StateBaton,
        *,
        requirement: CapabilityRequirement,
        current: RobotCondition | None = None,
        candidates: Sequence[RobotCondition] = (),
        extra_triggers: Sequence[str] = (),
    ) -> HandoverDecision:
        """로봇 상태가 나빠져 임무를 **다른 로봇에게** 다시 보낸다.

        우리가 하는 일은 셋이다 — 넘길 사유가 성립하는지 보고, 적격 후보를 가리고,
        갈리면 하나를 낸다. 하지 않는 일도 셋이다 — 가용성을 판정하지 않고, 명령을
        발급하지 않고, 갈리지 않을 때 1위를 고르지 않는다.
        """
        triggers = list(triggers_for(
            current, requirement=requirement, reserve_pct=self.reserve_pct,
        ))
        for token in extra_triggers:
            if token not in triggers:
                triggers.append(token)

        source = (current.robot_id if current is not None
                  else self.ledger.current_assignee(baton.mission_id))
        unmeasured = current.unmeasured if current is not None else ()

        def answer(reason: str, *, target: str | None = None,
                   tied: Iterable[str] = (), considered: int = 0,
                   margin: float | None = None,
                   rejections: Iterable[CandidateRejection] = (),
                   resumption: Iterable[NodeResumption] = (),
                   extra_unmeasured: Iterable[str] = ()) -> HandoverDecision:
            return HandoverDecision(
                mission_id=baton.mission_id,
                kind=KIND_ASSIGNEE,
                trigger=tuple(triggers),
                target_id=target,
                source_id=source,
                reason=reason,
                tied=tuple(tied),
                considered=considered,
                margin=margin,
                rejections=tuple(rejections),
                resumption=tuple(resumption),
                unmeasured=tuple(unmeasured) + tuple(extra_unmeasured),
                baton=baton,
            )

        if not triggers:
            return answer(REASON_NO_TRIGGER)
        if not baton.complete:
            return answer(REASON_BATON_INCOMPLETE,
                          extra_unmeasured=baton.missing_execution_state)

        probe = HandoverDecision(
            mission_id=baton.mission_id, kind=KIND_ASSIGNEE,
            trigger=tuple(triggers), source_id=source,
        )
        if probe.marker in self.ledger.open_markers(baton.mission_id):
            return answer(REASON_ALREADY_HANDED_OVER, considered=len(candidates))

        eligible, rejections = self._filter(candidates, requirement, source)
        if not eligible:
            # 셋을 구분한다. 후보가 아예 없는 것, 전부 못 잰 것, 전부 부적격인 것.
            if not candidates:
                reason = REASON_NO_CANDIDATE
            elif rejections and all(r.reason in _MEASUREMENT_REJECTIONS for r in rejections):
                reason = REASON_EVIDENCE_INSUFFICIENT
            else:
                reason = REASON_NO_CANDIDATE
            return answer(reason, considered=len(candidates), rejections=rejections)

        ranked = self._rank(eligible, requirement)
        best = ranked[0]
        resumption = self._resumption_for(baton)

        if len(ranked) == 1:
            return answer(REASON_HANDED, target=best.robot_id,
                          considered=len(candidates), rejections=rejections,
                          resumption=resumption)

        second = ranked[1]
        best_rank = _STATE_RANK[best.capability_state(requirement).value]
        second_rank = _STATE_RANK[second.capability_state(requirement).value]
        if best_rank != second_rank:
            # capability 등급이 다르면 갈렸다. 등급은 선언된 사실이고 어림이 아니다.
            return answer(REASON_HANDED, target=best.robot_id,
                          considered=len(candidates), rejections=rejections,
                          resumption=resumption)

        if self.reserve_pct is None:
            # 같은 등급이고 비교할 축이 **선언되지 않았다**. 1위를 고르면 그것은
            # 정렬 순서이지 판단이 아니다. 둘을 함께 내고 사람이 고른다.
            return answer(REASON_NOT_SEPARATED,
                          tied=self._tied(ranked, best_rank, requirement),
                          considered=len(candidates), rejections=rejections)

        margin = _pct(best.battery_pct) - _pct(second.battery_pct)
        if margin < self.reserve_margin_pct:
            return answer(REASON_NOT_SEPARATED, margin=margin,
                          tied=self._tied(ranked, best_rank, requirement),
                          considered=len(candidates), rejections=rejections)
        return answer(REASON_HANDED, target=best.robot_id, margin=margin,
                      considered=len(candidates), rejections=rejections,
                      resumption=resumption)

    # -- 내부 ---------------------------------------------------------------

    def _filter(
        self,
        candidates: Sequence[RobotCondition],
        requirement: CapabilityRequirement,
        source: str | None,
    ) -> tuple[tuple[RobotCondition, ...], tuple[CandidateRejection, ...]]:
        """적격 후보와 탈락 사유. 탈락 사유를 **버리지 않는다**.

        `backend_available` 의 세 값(참·거짓·없음)이 서로 다른 세 결과를 낸다 —
        없음을 거짓으로 접으면 우리가 가용성을 판정한 것이 된다(원칙 #15).
        """
        eligible: list[RobotCondition] = []
        rejected: list[CandidateRejection] = []
        for candidate in candidates:
            if source is not None and candidate.robot_id == source:
                rejected.append(CandidateRejection(candidate.robot_id,
                                                   REJECT_IS_CURRENT_ASSIGNEE))
                continue
            if candidate.backend_available is False:
                rejected.append(CandidateRejection(candidate.robot_id,
                                                   REJECT_BACKEND_UNAVAILABLE))
                continue
            if candidate.backend_available is None:
                rejected.append(CandidateRejection(candidate.robot_id,
                                                   REJECT_AVAILABILITY_NOT_RECEIVED))
                continue
            if candidate.fault_codes:
                rejected.append(CandidateRejection(
                    candidate.robot_id, REJECT_FAULT_DECLARED,
                    detail=",".join(candidate.fault_codes)))
                continue
            state = candidate.capability_state(requirement)
            if state is CapabilityState.DISABLED:
                missing = sorted(set(requirement.required) - set(candidate.capability_kinds))
                rejected.append(CandidateRejection(
                    candidate.robot_id, REJECT_CAPABILITY_SHORTFALL,
                    detail=",".join(missing)))
                continue
            if self.reserve_pct is not None:
                if candidate.battery_pct is None:
                    rejected.append(CandidateRejection(candidate.robot_id,
                                                       REJECT_BATTERY_UNKNOWN))
                    continue
                if candidate.battery_pct < self.reserve_pct:
                    rejected.append(CandidateRejection(candidate.robot_id,
                                                       REJECT_BELOW_RESERVE))
                    continue
            eligible.append(candidate)
        return tuple(eligible), tuple(rejected)

    def _rank(self, eligible: Sequence[RobotCondition],
              requirement: CapabilityRequirement) -> tuple[RobotCondition, ...]:
        """등급이 앞이고, 선언된 예비선이 있으면 그 여유가 다음이다.

        마지막 열이 `robot_id` 인 이유는 **결정성**이다 — 같은 입력이면 같은 순서여야
        "갈리지 않았다"는 판정이 실행마다 달라지지 않는다.
        """
        def key(candidate: RobotCondition):
            rank = _STATE_RANK[candidate.capability_state(requirement).value]
            if self.reserve_pct is None:
                return (rank, 0.0, candidate.robot_id)
            return (rank, -_pct(candidate.battery_pct), candidate.robot_id)
        return tuple(sorted(eligible, key=key))

    def _tied(self, ranked: Sequence[RobotCondition], rank: int,
              requirement: CapabilityRequirement) -> tuple[str, ...]:
        """갈리지 않은 후보 **전부**. 둘만 내면 셋이 묶인 경우를 숨긴다.

        같은 등급이라도 예비선이 선언된 배치에서는 1 위와 여유 안에 있는 것들만
        묶인다 — 90%·85%·20% 에서 셋을 다 내면 운영자에게 고르라고 내민 목록에
        고를 이유가 없는 것이 섞인다.
        """
        same_rank = [c for c in ranked
                     if _STATE_RANK[c.capability_state(requirement).value] == rank]
        if self.reserve_pct is None or not same_rank:
            return tuple(c.robot_id for c in same_rank)
        top = _pct(same_rank[0].battery_pct)
        return tuple(c.robot_id for c in same_rank
                     if top - _pct(c.battery_pct) < self.reserve_margin_pct)

    def _resumption_for(self, baton: StateBaton) -> tuple[NodeResumption, ...]:
        """중간 상태인 노드만 묻는다. 끝난 일과 시작하지 않은 일은 물을 것이 없다."""
        return tuple(self.resumption_policy.for_entry(e) for e in baton.in_flight)


def _pct(value: float | None) -> float:
    """비교에만 쓰는 환산. **미측정이 여기 들어오지 않는다** — 예비선이 선언된
    배치에서 못 잰 후보는 `_filter` 가 이미 `battery_level_unknown` 으로 빼 두었고,
    선언이 없는 배치는 이 값을 보지 않는다. 그래도 0 을 내는 것은 비교 함수가
    None 으로 터지지 않게 하는 것뿐이며 "배터리가 없다"는 뜻이 아니다.
    """
    return 0.0 if value is None else float(value)
