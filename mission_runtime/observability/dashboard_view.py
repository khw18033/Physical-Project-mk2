"""One read-only snapshot that carries every dashboard region, with per-source
"not received" marking so a silent source degrades only its own region.

implements: AI-O-06 (통합 운영 상태 뷰 제공), AI-B-12 (기준 노드·상태 집계)
관련: AI-O-01 (집계하면 안 되는 상태는 개별 유지), AI-O-02 (사건 즉시 기록),
      AI-O-04 (전송 신호와 관측 신호의 구분), AI-C-05 (한 소스 결손은 그 구역만),
      AI-C-19 (가시화는 표현·입력 전달, 판단 로직을 중복 구현하지 않는다)

요구사항 출처는 `docs/20260928-종합상황정보_Dashboard_기능정의서_2.docx` §2·§3·§4·§5
이며, 2026-10-27 에 요구사항 시트에 등재했다(CLAUDE.md §5).

왜 한 덩어리로 내는가
---------------------
문서 §3 요구사항 1: "화면은 소스별로 개별 조회하는 것이 아니라 **통합된 상태 뷰를
구독**하여 갱신되어야 한다." 그리고 §5 상태 일관성: "동일한 사실이 여러 구역에 표시될
경우 값이 상충하지 않아야 한다." 구역별로 따로 조회하면 그 두 요구를 동시에 지킬 수
없다 — 그래서 **한 스냅샷**을 조립하고, 여러 구역이 같은 사실을 보여야 할 때는
**한 출처에서 파생**시킨다(상태별 집계는 그래프에서, 자원 조건은 자원 뷰에서).

전송은 담지 않는다
------------------
이 모듈은 구독 메커니즘(WebSocket·SSE·MQTT·폴링)을 구현하지 않는다. 스냅샷을 만들고
무엇이 비었는지 말하는 것까지가 경계이고, 어떻게 밀어 보내는지는 provider 의 몫이다
(AI-C-04·AI-C-06). 조회 전용 원칙(문서 §1.1)도 그래서 지켜진다 — 이 자료구조에는
실행 상태를 바꾸는 수단이 없다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

from mission_runtime.execution.external_request import ExternalRequestLog
from mission_runtime.execution.task_graph import Focus, NodeState, StateCounts, TaskGraph
from mission_runtime.observability.layered_metrics import (
    Indicator,
    LayeredResourceView,
    MeetState,
)


class Region(str, Enum):
    """문서 §2 구역 기호. A(글로벌 내비게이션)는 문서가 정의 범위 외로 둔다."""

    MISSION_SUMMARY = "B"
    TASK_GRAPH = "C"
    EVENTS = "D"
    RESOURCES = "E"
    INDICATORS = "E_PRIME"
    NODE_DETAIL = "F"
    VERDICT = "G"
    NODE_EVENTS = "H"
    EXTERNAL_REQUESTS = "I"


class Severity(str, Enum):
    """사건 등급 (문서 §4.3·§4.8).

    문서는 "INFO / WARN / ERROR / SDI 등 **등급·유형** 구분"이라고 적었다. 등급과
    유형은 서로 다른 축이므로 한 enum 에 섞지 않는다 — SDI 는 등급이 아니라 유형이고
    (`EventKind`), SDI 사건에도 INFO/WARN/ERROR 가 각각 있을 수 있다.
    """

    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


class EventKind(str, Enum):
    """사건 유형. 문서 §4.3: "SDI 연계 이벤트는 별도 유형으로 구분하여, 일반 실행
    이벤트와 섞이지 않고 식별 가능해야 한다."
    """

    EXECUTION = "EXECUTION"
    EXTERNAL_REQUEST = "EXTERNAL_REQUEST"
    RESOURCE = "RESOURCE"


#: 기존 wire 어휘(info/warning/critical)와 화면 등급의 대응. 두 어휘를 한쪽으로
#: 합치지 않고 변환만 둔다 — wire 쪽은 파트 간 합의 대상이라 여기서 바꿀 수 없다.
_WIRE_SEVERITY: dict[str, Severity] = {
    "info": Severity.INFO,
    "warning": Severity.WARN,
    "critical": Severity.ERROR,
}


def severity_from_wire(value: str) -> Severity:
    try:
        return _WIRE_SEVERITY[value]
    except KeyError as exc:
        raise ValueError(f"unknown wire severity: {value!r}") from exc


@dataclass(frozen=True)
class SourceState:
    """소스 하나의 수신 상태 (문서 §3 소스 표, §5 연결 상태 표시).

    `last_received_at is None` 이면 한 번도 받은 적이 없다는 뜻이고 시각을 지어내지
    않는다. 화면은 "마지막 수신 시각과 단절 사실을 명시"한다(§5).
    """

    source_id: str
    #: 어느 계층의 소스인가. 자유 문자열("L1"/"L2"/"L3"/"external"/"stream").
    layer: str
    last_received_at: float | None = None
    #: 이 소스가 비면 어떤 구역이 비는가. 한 소스 결손이 다른 구역을 막지 않는다.
    feeds: tuple[Region, ...] = ()

    @property
    def received(self) -> bool:
        return self.last_received_at is not None

    def is_stale(self, now: float, ttl_s: float) -> bool:
        """마지막 수신이 ttl 을 넘었는가. 못 받은 적 없는 소스는 stale 이 아니라 미수신."""
        if self.last_received_at is None:
            return False
        return (now - self.last_received_at) > ttl_s


@dataclass(frozen=True)
class MissionSummary:
    """[B] 현재 미션 (문서 §4.1).

    `utterance` 는 사용자가 준 자연어 명령 **원문**이다. 문서가 미션명으로 이것을
    요구하므로 요약·번역본으로 대체하지 않는다.
    """

    mission_id: str
    utterance: str | None = None
    status: str | None = None
    accepted_at: float | None = None

    def elapsed_s(self, now: float) -> float | None:
        if self.accepted_at is None:
            return None
        return max(0.0, now - self.accepted_at)


@dataclass(frozen=True)
class EventRecord:
    """[D]/[H] 사건 1건.

    `node_id` 는 문서 §4.3 의 "관련 노드"다. 작업 노드를 가리키지 않는 사건도 있어
    선택이지만, 있으면 화면이 그래프 강조와 상세 전환의 진입점으로 쓴다.
    `attempt` 를 함께 들고 다니므로 재실행이 이전 회차 로그를 덮지 않는다(§4.8).
    """

    at: float | None
    severity: Severity
    kind: EventKind
    message: str
    node_id: str | None = None
    attempt: int | None = None
    external_request_id: str | None = None


@dataclass(frozen=True)
class ConditionItem:
    """[G] 조건 1개. 항목 단위로 들고 다니는 것이 요점이다.

    문서 §4.7: "각 조건은 상태가 **개별 항목 단위로** 표시되어야 하며, 요약 수치만
    제공해서는 안 된다." 그래서 집계는 이 목록에서 파생시키고 반대로 하지 않는다.
    """

    item_id: str
    #: 충족/발생/정상 여부. 판정할 근거가 없으면 None 이고 그것이 "미확인"이다.
    satisfied: bool | None
    #: 왜 그렇게 판정했는지의 통제 어휘 토큰. 표시 문구는 화면이 만든다.
    reason_token: str | None = None


@dataclass(frozen=True)
class NodeVerdict:
    """[G] 한 노드의 판정 근거 3축 (문서 §4.7).

    완료 조건 / 실패 조건 / 자원 조건을 **서로 다른 목록**으로 둔다. 하나로 합치면
    "무엇을 만족해야 성공인가"와 "무엇이 생기면 실패인가"가 섞인다.
    """

    node_id: str
    completion: tuple[ConditionItem, ...] = ()
    failure: tuple[ConditionItem, ...] = ()
    resource: tuple[ConditionItem, ...] = ()
    #: 승격 표시 — 외부 기능 요청으로 올라갔다면 그 식별자. 문서 §4.7:
    #: "판정 결과와 후속 조치가 끊기지 않고 연결되어야 한다."
    escalated_request_id: str | None = None

    @staticmethod
    def _tally(items: tuple[ConditionItem, ...]) -> tuple[int, int]:
        """(참으로 판정된 수, 전체 수). 미확인은 참으로 세지 않는다."""
        return (sum(1 for i in items if i.satisfied is True), len(items))

    @property
    def completion_tally(self) -> tuple[int, int]:
        return self._tally(self.completion)

    @property
    def failure_tally(self) -> tuple[int, int]:
        return self._tally(self.failure)

    @property
    def resource_tally(self) -> tuple[int, int]:
        return self._tally(self.resource)

    @property
    def escalated(self) -> bool:
        return self.escalated_request_id is not None


@dataclass(frozen=True)
class RegionState:
    """구역 하나가 표시 가능한지와 그 이유."""

    region: Region
    available: bool
    #: 비었을 때의 사유 토큰. 비어 있지 않으면 None.
    reason_token: str | None = None
    missing_sources: tuple[str, ...] = ()


REASON_SOURCE_NOT_RECEIVED = "source_not_received"
REASON_NO_DATA = "no_data_yet"

REGION_REASONS: tuple[str, ...] = (REASON_SOURCE_NOT_RECEIVED, REASON_NO_DATA)


@dataclass(frozen=True)
class DashboardSnapshot:
    """한 시점의 전체 상태. 조회 전용이며 실행 상태를 바꾸는 수단이 없다.

    문서 §1.1: "화면의 모든 조작은 표시 대상의 선택·필터링·확대 등 관찰 방식의
    변경에 한정된다." 그래서 이 클래스의 공개 메서드는 전부 조회·필터이고
    시작·중지·배포·취소에 해당하는 것이 하나도 없다(테스트가 그것을 고정한다).
    """

    mission: MissionSummary
    graph: TaskGraph
    resources: LayeredResourceView = field(default_factory=LayeredResourceView)
    events: tuple[EventRecord, ...] = ()
    verdicts: tuple[NodeVerdict, ...] = ()
    external_requests: ExternalRequestLog | None = None
    sources: tuple[SourceState, ...] = ()
    #: 최근 N 건만 보여 주고 전체 이력은 별도 화면에서 조회한다(문서 §4.3).
    event_window: int = 50

    def __post_init__(self) -> None:
        if self.external_requests is not None and (
            self.external_requests.mission_id != self.mission.mission_id
        ):
            raise ValueError("external request log belongs to another mission")
        if self.graph.mission_id != self.mission.mission_id:
            raise ValueError("task graph belongs to another mission")

    # -- [B] 미션 상태 요약 ----------------------------------------------

    def state_counts(self) -> StateCounts:
        """그래프에서 파생한다 — [B] 와 [C] 가 어긋날 수 없다(문서 §4.1·§5)."""
        return self.graph.state_counts()

    def placement(self) -> dict[str, tuple[str, ...]]:
        """가속기 → 배치 서비스. 유휴 가속기가 빠지지 않는다(문서 §4.1)."""
        return self.resources.placement()

    def node_load(self) -> dict[str, tuple[int, int]]:
        """가속기별 (현재 실행 중 노드 수, 배정된 전체 노드 수) — 문서 §4.1 "노드 부하".

        가속기를 기준 축으로 삼으므로 배정이 없는 가속기도 (0, 0) 으로 남는다.
        """
        load: dict[str, tuple[int, int]] = {}
        for acc in self.resources.accelerators:
            assigned = [n for n in self.graph.nodes if n.accelerator_id == acc.instance_id]
            running = [n for n in assigned if n.state is NodeState.EXECUTING]
            load[acc.instance_id] = (len(running), len(assigned))
        return load

    # -- [F]/[G]/[H] 기준 노드 축 ----------------------------------------

    def focus(self) -> Focus:
        return self.graph.focus()

    def focused_verdict(self) -> NodeVerdict | None:
        node_id = self.focus().node_id
        if node_id is None:
            return None
        for v in self.verdicts:
            if v.node_id == node_id:
                return v
        return None

    def events_for(self, node_id: str, *, include_attempts: bool = True) -> tuple[EventRecord, ...]:
        """[H] 선택 노드로 필터된 사건.

        `include_attempts` 가 참이면 같은 논리 작업의 **모든 회차**를 포함한다 —
        문서 §4.8: "재실행된 노드는 회차별 이력이 모두 조회 가능해야 한다."
        """
        ids = {node_id}
        if include_attempts:
            try:
                ids |= {n.node_id for n in self.graph.attempts_of(node_id)}
            except KeyError:
                pass
        return tuple(e for e in self.events if e.node_id in ids)

    def recent_events(self) -> tuple[EventRecord, ...]:
        """[D] 최신이 앞. 창을 넘는 이력은 별도 화면 몫이다."""
        ordered = sorted(self.events, key=lambda e: (-(e.at or 0.0),))
        return tuple(ordered[: self.event_window])

    def external_request_events(self) -> tuple[EventRecord, ...]:
        """SDI 유형만. 일반 실행 이벤트와 섞이지 않는다(문서 §4.3)."""
        return tuple(e for e in self.events if e.kind is EventKind.EXTERNAL_REQUEST)

    # -- [E]/[E′] --------------------------------------------------------

    def indicators(self) -> tuple[Indicator, ...]:
        return self.resources.indicators()

    def resource_alerts(self) -> tuple[Indicator, ...]:
        """목표 미달 지표. 측정 없음은 경고가 아니다(문서 §4.5)."""
        return tuple(i for i in self.indicators() if i.meet_state is MeetState.UNMET)

    # -- [I] -------------------------------------------------------------

    def has_external_requests(self) -> bool:
        return self.external_requests is not None and not self.external_requests.is_empty

    # -- §3·§5 구역별 가용성 ---------------------------------------------

    def source(self, source_id: str) -> SourceState:
        for s in self.sources:
            if s.source_id == source_id:
                return s
        raise KeyError(source_id)

    def region_state(self, region: Region) -> RegionState:
        """한 소스가 조용해도 나머지 구역은 정상이고, 그 구역만 미수신으로 적는다.

        문서 §3 요구사항 5 / AI-C-05 와 같은 규칙이다 — 결손은 축소이지 전체 실패가
        아니다.
        """
        feeding = [s for s in self.sources if region in s.feeds]
        missing = tuple(s.source_id for s in feeding if not s.received)
        if feeding and len(missing) == len(feeding):
            return RegionState(region, False, REASON_SOURCE_NOT_RECEIVED, missing)
        if region is Region.TASK_GRAPH and not self.graph.nodes:
            return RegionState(region, False, REASON_NO_DATA, missing)
        if region is Region.VERDICT and not self.verdicts:
            return RegionState(region, False, REASON_NO_DATA, missing)
        # [E]·[E′] 도 같은 규칙을 받는다. 자원 계층에 사실이 하나도 없는데 구역을
        # "표시 가능"으로 적으면 화면은 빈 칸을 그리면서 **왜 비었는지 말할 근거를
        # 잃는다** — 가속기 선언이 없는 배치와 계측이 끊긴 배치가 같아 보인다
        # (문서 §3 요구사항 5, §4.4 목록의 완전성). 비었다는 사실과 그 사유를 함께
        # 적는 것이 구역을 지우지 않는 길이다(AI-C-05: 결손은 축소이지 실패가 아니다).
        if region is Region.RESOURCES and self.resources.is_empty:
            return RegionState(region, False, REASON_NO_DATA, missing)
        if region is Region.INDICATORS and not self.indicators():
            return RegionState(region, False, REASON_NO_DATA, missing)
        return RegionState(region, True, None, missing)

    def region_states(self) -> tuple[RegionState, ...]:
        return tuple(self.region_state(r) for r in Region)

    def unavailable_regions(self) -> tuple[Region, ...]:
        return tuple(rs.region for rs in self.region_states() if not rs.available)

    # -- 관찰 방식의 변경만 (문서 §1.1) ----------------------------------

    def pin(self, node_id: str | None) -> DashboardSnapshot:
        """기준 노드 고정/해제. 표시 대상의 선택이며 실행에 개입하지 않는다."""
        return replace(self, graph=self.graph.pin(node_id))

    def with_event_window(self, size: int) -> DashboardSnapshot:
        if size < 1:
            raise ValueError("event_window must be at least 1")
        return replace(self, event_window=size)
