"""한 단계가 실패했을 때 "무엇 때문인가"를 이미 수집되는 관측 데이터로 되짚는다.

implements: AI-O-02 (오류·이상 사건 기록), AI-O-03 (오류 재현 정보 관리),
            AI-O-05 (계층별 지표 관측 — 미측정 구분)
관련: AI-B-03 (업무 책임 추적과 기술 처리 경로 추적의 분리), AI-O-01 (관측 실패가
      기능 실행을 멈추게 하지 않는다), AI-L-08 (학습·적용 계보)
tests: tests/test_failure_trace.py

개발자가 묻는 문장은 하나다 — "이 단계가 실패했는데, 모델인가 장치인가 링크인가
자원 예산인가 오케스트레이터인가, 그리고 무엇이 그렇다고 말하는가."

이 모듈은 그 질문에 **순위와 근거**로 답한다. 덤프를 내지 않고, 단정하지도 않는다.

왜 새 모듈인가 — 기존 것과의 경계
---------------------------------
이미 있는 것을 다시 만들지 않는다.

    `observability/events.py`       사건을 **쓴다**
    `observability/metrics.py`      엣지 상세 / 서버 요약을 **쌓는다**
    `observability/reproduction.py` 재현 참조를 **조립한다** (AI-O-03)
    `observability/layered_metrics.py` 미측정을 1급 상태로 **표현한다** (AI-O-05)
    `continual/lineage.py`          모델 버전의 학습·검증·승인 계보를 **적는다**

없는 것은 **읽는 쪽**이다. 위 모듈들은 모두 산출·기록 방향이고, 실패 하나를 놓고
"그 구간의 계측·구간·사건을 모아 와서 원인 후보를 세운다"는 소비 방향이 비어 있었다.
이 모듈이 그 자리이며, 위 다섯을 전부 **읽기 전용으로 조합**한다.

세 가지를 한 칸에 접지 않는다 (요건 1)
--------------------------------------
수집기에 닿지 못한 것, 닿았는데 그 이름으로 긁힌 표본이 없는 것, 긁혔고 정상인 것은
**서로 다른 답**이다. 앞의 둘을 "정상"으로 렌더하면 관측 공백이 무죄 증명으로
둔갑한다. 그래서 `DataState` 가 세 값이고, 목표 충족 판정은 AI-O-05 가 이미 정한
`MeetState`(MET/UNMET/NOT_MEASURED) 어휘를 **그대로 재사용**한다 — 새 어휘를 만들면
화면이 두 가지 "미측정"을 배워야 한다.

요약이 가린 사건은 요약을 읽어도 드러나야 한다 (요건 2)
-------------------------------------------------------
원칙 #14·AI-O-02: "장치 생사와 치명적 오류처럼 집계하면 안 되는 상태는 개별 상태로
유지한다." 그래서 이 모듈은 평균이 평온해 보이는 구간에서도 그 구간의 **개별 치명
사건**을 따로 들고 나온다(`fatal_events`). 규칙이 원인에 붙이지 못한 치명 사건조차
`unattributed_fatal_events` 로 남긴다 — 분류하지 못했다는 이유로 사건을 버리는 것이
바로 요건 2 가 금지하는 일이다.

순위는 매기고 단정은 하지 않는다 (요건 3)
-----------------------------------------
각 후보는 자기를 지지하는 관측 행을 들고 다니고, 확신도는 설명 가능한 산술이다 —
근거 몫(share) × 근거 포화도(saturation). 근거가 두 원인을 **가르지 못하면** 하나를
고르지 않고 `Tie` 로 적는다. 수락됐는데 종결 보고가 없는 명령이 전형적인 예다:
장치가 죽은 것과 링크가 끊긴 것을 그 사실만으로는 가를 수 없다.

업무 축과 기술 축은 섞이지 않는다 (요건 4)
------------------------------------------
AI-B-03·AI-O-03: command_id 기반 책임 추적과 OTel trace 기반 처리 경로·지연 추적은
목적이 다르다. 그래서 `business_chain` 과 `technical_spans` 는 끝까지 다른 필드이고,
한쪽이 빈 자리를 다른 쪽 값으로 메우는 일을 `AxisConfusion` 으로 거부한다 —
trace_id 자리에 command_id 를 넣는 것이 이 혼동의 실제 형태다.

관측이 죽어도 관측 대상은 죽지 않는다 (요건 5)
----------------------------------------------
reader 호출은 전부 provider 경계 뒤에 있고, 닿지 않는 수집기는 이 모듈만 축소시킨다
(AI-O-01). 백엔드가 아예 없는 노드에서도 import 되고 답한다 — 그 답이 "미측정"이다.

벤더 이름은 여기에 없다 (요건 6)
--------------------------------
이 모듈은 계측·구간·사건이라는 의미만 말한다. 질의 프로토콜과 저장 형식은
`providers/observability_query.py` 뒤에 있다(AI-C-04).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Callable, Mapping, Protocol, Sequence, runtime_checkable

from mission_runtime.contracts.physical_command import (
    Command,
    CommandAcceptance,
    CommandResult,
    CommandStatus,
    ExecutionStatus,
    RejectionCode,
)
from mission_runtime.continual.lineage import LearningLineage, LearningState
from mission_runtime.observability.layered_metrics import (
    Direction,
    Measurement,
    MeetState,
    TargetBaseline,
)
from mission_runtime.observability.reproduction import ReproductionReference


class AxisConfusion(Exception):
    """업무 책임 축과 기술 처리 축이 섞였다.

    AI-B-03 이 두 축을 따로 두라고 한 이유는 문장이 아니라 사고다 — 종결 보고가 없어
    trace_id 가 비었을 때 손에 있는 command_id 를 그 자리에 넣으면, 이후 누구도 "지연이
    어디서 났는가"와 "누가 무엇을 지시했는가"를 다시 가를 수 없다. 조립 시점에 막는다.
    """


# ── 세 값 데이터 상태 (요건 1) ────────────────────────────────────────────────


class DataState(str, Enum):
    """관측 하나를 묻고 받은 답. 셋이며 둘로 줄이지 않는다.

    PRESENT             값이 있다
    NOT_SCRAPED         백엔드에는 닿았는데 이 이름으로 긁힌 표본이 없다
    BACKEND_UNREACHABLE 백엔드 자체에 닿지 못했다
    """

    PRESENT = "PRESENT"
    NOT_SCRAPED = "NOT_SCRAPED"
    BACKEND_UNREACHABLE = "BACKEND_UNREACHABLE"

    @property
    def measured(self) -> bool:
        return self is DataState.PRESENT


#: 뒤의 두 상태는 AI-O-05 의 `MeetState.NOT_MEASURED` 로 접힌다 — 목표 충족 판정에서는
#: 둘 다 "못 쟀다"이고 **미달이 아니다**. 그러나 `DataState` 로서는 끝까지 구별된다.
_UNMEASURED_STATES = (DataState.NOT_SCRAPED, DataState.BACKEND_UNREACHABLE)


class CauseKind(str, Enum):
    """원인 후보의 축. 개발자가 실제로 묻는 다섯 가지다.

    자유 문자열이 아니라 enum 인 이유: 이 다섯은 서로 다른 **담당**으로 이어진다.
    MODEL 은 학습·검증 경로(AI-L), DEVICE 는 하드웨어, LINK 는 네트워크, RESOURCE 는
    실행 재구성(AI-B-06), ORCHESTRATOR 는 실행 제어면(AI-B-11)이다. 도메인·벤더
    이름이 아니므로 핵심 코드에 두어도 원칙 #1 에 걸리지 않는다.
    """

    MODEL = "MODEL"
    DEVICE = "DEVICE"
    LINK = "LINK"
    RESOURCE = "RESOURCE"
    ORCHESTRATOR = "ORCHESTRATOR"


class CauseVerdict(str, Enum):
    """한 원인 축에 대해 지금 말할 수 있는 것.

    CLEARED 는 **값을 봤고 정상이었다**일 때만 쓴다. 못 본 것은 CLEARED 가 아니라
    NOT_MEASURED 다 — 이 한 줄이 요건 1 의 전부다.
    """

    SUSPECT = "SUSPECT"
    CLEARED = "CLEARED"
    NOT_MEASURED = "NOT_MEASURED"


class EvidenceSource(str, Enum):
    """근거가 어느 평면에서 왔는가. 업무 축과 기술 축이 여기서도 갈린다."""

    METRIC = "METRIC"
    SPAN = "SPAN"
    EVENT = "EVENT"
    BUSINESS = "BUSINESS"
    LINEAGE = "LINEAGE"


#: 근거 사유 토큰. 표시 문구는 화면이 만든다(AI-C-19).
REASON_METRIC_UNMET = "metric_target_unmet"
REASON_FATAL_EVENT = "fatal_event"
REASON_SPAN_OVER_BUDGET = "span_over_budget"
REASON_COMMAND_REJECTED = "command_rejected"
REASON_NO_TERMINAL_RESULT = "no_terminal_result"
REASON_MODEL_NOT_OPERATIONALLY_VERIFIED = "model_not_operationally_verified"
REASON_MODEL_ROLLED_BACK = "model_rolled_back"

#: 동률 사유 토큰.
TIE_INDISTINGUISHABLE = "indistinguishable_evidence"
TIE_EQUAL_CONFIDENCE = "equal_confidence"

#: 미측정 주체 토큰 — 계측은 이름이 있고, 구간·사건은 평면 전체가 주체다.
SUBJECT_SPANS = "spans"
SUBJECT_EVENTS = "events"

#: provider 가 단위를 알 수 없을 때 표본에 붙이는 표시. 질의 프로토콜 다수가 단위를
#: 실어 보내지 않으므로 provider 는 **짐작하지 않고** 이것을 적고, 단위는 질의의
#: `TargetBaseline` 이 선언한다(단위를 코드 규약으로 유추하면 조용히 틀린다).
UNKNOWN_UNIT = "unknown"


# ── 가중치 (설명 가능한 산술의 입력) ──────────────────────────────────────────
#
# 숫자를 코드에 박아 두는 대신 상수로 꺼내 둔다. 정책을 갈아끼울 때(AI-C-13: 선택
# 방식은 교체 가능해야 한다) 무엇을 바꾸는지가 한 화면에 보여야 한다.

#: 개별 치명 사건. 가장 직접적인 근거다 — 요약이 가렸을 바로 그 사실이다.
W_FATAL_EVENT = 4.0
#: 수락 거부 사유. 업무 축의 1차 사실이고 해석이 끼지 않는다.
W_REJECTION = 3.0
#: 목표를 넘긴 계측.
W_METRIC_UNMET = 2.0
#: 예산을 넘긴 처리 구간.
W_SPAN_OVER_BUDGET = 2.0
#: 수락 뒤 종결 보고가 없다. 약하게 두는 이유는 이것이 **두 원인을 가리지 못하는**
#: 근거라서다 — 세게 주면 가르지 못한 채 순위가 생긴다.
W_SILENT_AFTER_ACCEPT = 1.5
#: 배포됐지만 운영 검증 전인 모델 버전. 혐의이고 판정이 아니다.
W_LINEAGE_UNVERIFIED = 1.5

#: 이 무게가 모이면 근거가 "충분히 모였다"고 본다. 한 줄짜리 약한 근거가 확신도
#: 1.0 을 받는 일을 막는 자리다 — 몫만 쓰면 근거 1개도 100% 가 된다.
EVIDENCE_SATURATION = 6.0

#: 이 차이 안쪽은 순위로 보지 않고 동률로 적는다.
DEFAULT_TIE_EPSILON = 0.05


# ── 시간 창과 관측 행 ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TimeWindow:
    """실패를 둘러싼 조회 구간. epoch 초."""

    start: float
    end: float

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"window ends before it starts: {self.start} .. {self.end}")

    @property
    def duration_s(self) -> float:
        return self.end - self.start

    def contains(self, at: float | None) -> bool:
        """시각이 없는 관측은 **배제하지 않는다.**

        시각 없는 치명 사건을 창 밖으로 떨어뜨리면, 타임스탬프를 붙이지 못한 노드의
        급사가 조용히 사라진다(AI-O-02). 못 믿을 근거로 버리는 쪽이 더 위험하다.
        """
        if at is None:
            return True
        return self.start <= at <= self.end

    @staticmethod
    def around(at: float, *, before_s: float, after_s: float = 0.0) -> TimeWindow:
        return TimeWindow(at - before_s, at + after_s)


@dataclass(frozen=True)
class MetricSeries:
    """한 계측 이름의 조회 결과.

    `samples` 가 비어 있는 것과 `state` 가 PRESENT 가 아닌 것은 다른 사실이므로 둘을
    따로 들고 다닌다. 표본은 `Measurement` 라 값 없는 점을 0 으로 메우지 않는다.
    """

    name: str
    state: DataState
    samples: tuple[Measurement, ...] = ()
    target: TargetBaseline | None = None
    selector: tuple[tuple[str, str], ...] = ()
    note: str | None = None

    def __post_init__(self) -> None:
        if self.state is DataState.PRESENT and not self.samples:
            raise ValueError(f"{self.name}: PRESENT 인데 표본이 없다 — NOT_SCRAPED 여야 한다")

    @property
    def measured_samples(self) -> tuple[Measurement, ...]:
        return tuple(s for s in self.samples if s.measured)

    @property
    def latest(self) -> Measurement | None:
        measured = self.measured_samples
        return measured[-1] if measured else None

    @property
    def worst(self) -> Measurement | None:
        """목표 방향에서 가장 나쁜 표본. 목표가 없으면 최신값으로 둔다.

        평균을 쓰지 않는 이유: 창 안에서 한 번 치솟은 지연은 평균에 묻히지만 실패를
        만든 것은 그 한 번이다(원칙 #14 의 요약 금지가 가리키는 바로 그 손실).
        """
        measured = self.measured_samples
        if not measured:
            return None
        if self.target is None:
            return measured[-1]
        if self.target.direction is Direction.AT_LEAST:
            return min(measured, key=lambda m: m.value if m.value is not None else 0.0)
        return max(measured, key=lambda m: m.value if m.value is not None else 0.0)

    @property
    def meet_state(self) -> MeetState:
        """AI-O-05 의 3값 판정을 그대로 쓴다. 미측정은 미달이 아니다."""
        worst = self.worst
        if self.state is not DataState.PRESENT or worst is None or self.target is None:
            return MeetState.NOT_MEASURED
        return self.target.evaluate(worst)


@dataclass(frozen=True)
class SpanRow:
    """기술 처리 경로의 한 구간. 업무 축의 어떤 식별자도 여기 들어오지 않는다."""

    name: str
    span_id: str
    trace_id: str | None = None
    parent_span_id: str | None = None
    duration_ms: float | None = None
    status: str | None = None
    started_at: float | None = None
    attributes: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class SpanView:
    state: DataState
    spans: tuple[SpanRow, ...] = ()
    note: str | None = None

    def __post_init__(self) -> None:
        if self.state is DataState.PRESENT and not self.spans:
            raise ValueError("PRESENT 인데 구간이 없다 — NOT_SCRAPED 여야 한다")


@dataclass(frozen=True)
class ObservedEvent:
    """구조화된 오류·이상 사건 1건 (AI-O-02).

    `severity` 는 wire 어휘(info/warning/error/critical/fatal)를 그대로 들고 온다 —
    화면 등급으로의 변환은 `dashboard_view.severity_from_wire` 의 몫이고 여기서
    두 어휘를 합치지 않는다.
    """

    name: str
    severity: str
    at: float | None = None
    payload: tuple[tuple[str, str], ...] = ()
    subject_id: str | None = None

    @property
    def is_fatal(self) -> bool:
        return self.severity.lower() in ("critical", "fatal")


@dataclass(frozen=True)
class EventView:
    state: DataState
    events: tuple[ObservedEvent, ...] = ()
    note: str | None = None

    def __post_init__(self) -> None:
        if self.state is DataState.PRESENT and not self.events:
            raise ValueError("PRESENT 인데 사건이 없다 — NOT_SCRAPED 여야 한다")

    def fatal(self) -> tuple[ObservedEvent, ...]:
        """개별 치명 사건만. 요약을 읽고 들어와도 이것은 따로 나온다(원칙 #14)."""
        return tuple(e for e in self.events if e.is_fatal)


# ── 읽기 경계 (AI-C-04) ───────────────────────────────────────────────────────


@runtime_checkable
class ObservabilityQueryProvider(Protocol):
    """관측 데이터를 **읽는** provider 경계.

    `providers/adapters.py` 의 `ObservabilityProvider` 는 쓰는 쪽(record_metric /
    record_event)만 선언한다. 실패를 되짚으려면 읽어야 하므로 그 짝을 여기 둔다 —
    상위 코드는 이 Protocol 만 보고, 질의 프로토콜·파일 형식·엔드포인트는 전부
    구현 모듈 뒤에 남는다(요건 6).

    세 메서드 모두 **예외를 던지지 않는다.** 닿지 못한 백엔드는 예외가 아니라
    `DataState.BACKEND_UNREACHABLE` 이고, 그것이 관측 장애를 이 모듈 안에
    가두는 방법이다(AI-O-01, 요건 5).
    """

    def is_reachable(self) -> bool: ...

    def metric_series(
        self, name: str, window: TimeWindow, selector: Mapping[str, str] | None = None
    ) -> MetricSeries: ...

    def span_view(self, window: TimeWindow, *, trace_id: str | None = None) -> SpanView: ...

    def event_view(self, window: TimeWindow, *, subject_id: str | None = None) -> EventView: ...


# ── 질의 선언 ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MetricSpec:
    """어느 계측이 **어느 원인 축을 대변하는가**는 배치가 선언한다.

    이 매핑을 코드에 박으면 계측 이름(= 배포 어휘)이 핵심 로직에 들어온다. 그래서
    질의가 들고 오고 이 모듈은 이름의 의미를 모른다(원칙 #1·#3).
    """

    name: str
    speaks_for: CauseKind
    target: TargetBaseline | None = None
    selector: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class SpanSpec:
    """처리 구간의 예산. 이름 접두로 묶는다 — 구간 이름도 배포 어휘다."""

    name_prefix: str
    speaks_for: CauseKind
    budget_ms: float | None = None


@dataclass(frozen=True)
class CommandRecords:
    """업무 책임 축의 입력 (AI-C-20).

    발급·수락/거부·진행·종결을 **각각** 받는다. 하나로 합친 "상태" 한 칸으로 받으면
    "전달됐다"와 "수락됐다"와 "끝났다"가 다시 구별되지 않는다.
    """

    command: Command | None = None
    acceptance: CommandAcceptance | None = None
    statuses: tuple[CommandStatus, ...] = ()
    result: CommandResult | None = None

    @property
    def command_id(self) -> str | None:
        for holder in (self.command, self.acceptance, self.result):
            if holder is not None:
                return holder.command_id
        for status in self.statuses:
            return status.command_id
        return None

    def chain(self) -> tuple[BusinessChainLink, ...]:
        """누가 무엇을 지시하고 무엇이 수락됐고 무엇이 끝났는가. 시간순."""
        links: list[BusinessChainLink] = []
        if self.command is not None:
            links.append(
                BusinessChainLink(
                    command_id=self.command.command_id,
                    phase="ISSUED",
                    detail=self.command.action,
                    at=None,
                    target=self.command.target,
                )
            )
        if self.acceptance is not None:
            accepted = self.acceptance.accepted
            links.append(
                BusinessChainLink(
                    command_id=self.acceptance.command_id,
                    phase="ACCEPTED" if accepted else "REJECTED",
                    detail=None
                    if accepted or self.acceptance.rejection is None
                    else self.acceptance.rejection.code.value,
                    at=self.acceptance.accepted_at,
                )
            )
        for status in sorted(self.statuses, key=lambda s: s.observed_at):
            links.append(
                BusinessChainLink(
                    command_id=status.command_id,
                    phase=status.status.value,
                    at=status.observed_at,
                )
            )
        if self.result is not None:
            links.append(
                BusinessChainLink(
                    command_id=self.result.command_id,
                    phase=self.result.status.value,
                    detail=None if self.result.failure is None else self.result.failure.code,
                    at=self.result.completed_at,
                )
            )
        return tuple(links)

    @property
    def accepted_without_terminal_result(self) -> bool:
        """수락은 받았고 종결 보고는 못 받았다 — 책임 축이 열린 채로 끝난 상태."""
        return (
            self.acceptance is not None and self.acceptance.accepted and self.result is None
        )


@dataclass(frozen=True)
class BusinessChainLink:
    """업무 책임 축의 한 칸. command_id 로 식별되고 span 과 섞이지 않는다 (AI-B-03)."""

    command_id: str
    phase: str
    at: float | None = None
    detail: str | None = None
    target: str | None = None


@dataclass(frozen=True)
class FailureQuery:
    """실패한 단계 하나를 되짚기 위한 질의.

    `subject_id` 는 미션·서브태스크·명령 중 무엇이든 될 수 있는 **그 단계의 식별자**다.
    이 모듈은 그 값으로 분기하지 않고 사건 필터와 보고서 표제로만 쓴다.
    """

    subject_id: str
    window: TimeWindow
    metric_specs: tuple[MetricSpec, ...] = ()
    span_specs: tuple[SpanSpec, ...] = ()
    #: 기술 처리 경로 축의 진입점. 업무 축의 command_id 를 여기 넣으면 거부된다.
    trace_id: str | None = None
    command_records: CommandRecords | None = None
    #: 모델 혐의를 계보로 뒷받침할 때 이름을 대는 버전 (AI-L-08).
    model_version: str | None = None
    #: 치명 사건 이름 → 원인 축. 사건 이름은 배포 어휘라 매핑을 질의가 들고 온다.
    fatal_event_causes: Mapping[str, CauseKind] = field(default_factory=dict)
    #: AI-O-03 재현 참조. 이 모듈이 다시 유도하지 않고 받아서 실어 보낸다.
    reproduction: ReproductionReference | None = None


# ── 근거와 후보 ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Evidence:
    """후보 하나를 지지하는 관측 1행. 근거 없는 후보는 만들지 않는다(요건 3)."""

    cause: CauseKind
    source: EvidenceSource
    reference: str
    detail: str
    weight: float
    at: float | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if self.weight <= 0.0:
            raise ValueError("근거의 무게는 양수여야 한다 — 0 이면 근거가 아니다")

    @property
    def fingerprint(self) -> tuple[str, str, str]:
        """원인을 뺀 지문. 두 후보가 **같은 관측**에 기대고 있는지 보는 자리다."""
        return (self.source.value, self.reference, self.detail)


@dataclass(frozen=True)
class CandidateCause:
    """원인 후보 1개. 확신도는 설명 가능한 산술의 결과다."""

    kind: CauseKind
    confidence: float
    evidence: tuple[Evidence, ...]
    #: 근거가 이 후보와 가르지 못하는 다른 후보들.
    contested_with: tuple[CauseKind, ...] = ()

    def __post_init__(self) -> None:
        if not self.evidence:
            raise ValueError(f"{self.kind.value}: 근거 없는 후보는 만들지 않는다")

    @property
    def total_weight(self) -> float:
        return sum(e.weight for e in self.evidence)

    def explain(self) -> str:
        """확신도가 어디서 나왔는지 그대로 적는다. 숫자를 믿으라고 하지 않는다."""
        lines = [f"{self.kind.value} confidence={self.confidence:.3f}"]
        for ev in self.evidence:
            lines.append(
                f"  [{ev.source.value}] {ev.reference} :: {ev.detail} (weight {ev.weight:.2f})"
                + (f" — {ev.note}" if ev.note else "")
            )
        if self.contested_with:
            lines.append(
                "  근거가 가르지 못하는 후보: "
                + ", ".join(c.value for c in self.contested_with)
            )
        return "\n".join(lines)


@dataclass(frozen=True)
class Tie:
    """가르지 못했다는 사실 자체. 하나를 고르는 대신 이것을 낸다(요건 3)."""

    causes: frozenset[CauseKind]
    reason: str

    def __post_init__(self) -> None:
        if len(self.causes) < 2:
            raise ValueError("동률은 둘 이상일 때만 성립한다")

    @property
    def ordered(self) -> tuple[CauseKind, ...]:
        return tuple(sorted(self.causes, key=lambda c: c.value))


@dataclass(frozen=True)
class NotMeasuredGap:
    """못 본 것의 목록. 보고서가 침묵으로 "정상"을 암시하지 않게 하는 자리."""

    subject: str
    state: DataState
    note: str | None = None

    def __post_init__(self) -> None:
        if self.state is DataState.PRESENT:
            raise ValueError("PRESENT 는 공백이 아니다")

    @property
    def meet_state(self) -> MeetState:
        """AI-O-05 어휘로의 환산. 두 공백 모두 미달이 아니라 미측정이다."""
        return MeetState.NOT_MEASURED


@dataclass(frozen=True)
class FailureAttribution:
    """한 실패에 대한 답. 순위·근거·공백·두 축·재현 참조가 한 덩어리로 나온다."""

    subject_id: str
    window: TimeWindow
    #: 확신도 내림차순, 같으면 이름 오름차순. 같은 입력이면 같은 순서다.
    candidates: tuple[CandidateCause, ...] = ()
    ties: tuple[Tie, ...] = ()
    verdicts: Mapping[CauseKind, CauseVerdict] = field(default_factory=dict)
    #: 개별 치명 사건 전부. 요약이 평온해도 여기 남는다(요건 2).
    fatal_events: tuple[ObservedEvent, ...] = ()
    #: 규칙이 원인에 붙이지 못한 치명 사건. 분류 실패를 사건 폐기로 바꾸지 않는다.
    unattributed_fatal_events: tuple[ObservedEvent, ...] = ()
    not_measured: tuple[NotMeasuredGap, ...] = ()
    #: 업무 책임 축 (AI-B-03). 기술 축과 영원히 다른 필드다.
    business_chain: tuple[BusinessChainLink, ...] = ()
    #: 기술 처리 경로 축 (AI-B-03).
    technical_spans: tuple[SpanRow, ...] = ()
    #: AI-O-03 재현 참조. 나중에 같은 실패를 다시 분석하기 위한 입구.
    reproduction: ReproductionReference = ReproductionReference()
    #: 읽어 본 평면별 상태. "왜 공백인가"를 보고서 안에서 답할 수 있게 둔다.
    backend_states: Mapping[str, DataState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 요건 4 의 실제 위반 형태를 조립 시점에 막는다: 종결 보고가 없어 trace 가
        # 비었을 때 손에 있는 command_id 를 trace_id 자리에 넣는 것.
        chain_ids = {link.command_id for link in self.business_chain}
        if self.reproduction.trace_id is not None and self.reproduction.trace_id in chain_ids:
            raise AxisConfusion(
                f"trace_id {self.reproduction.trace_id!r} 가 업무 축의 command_id 와 같다 — "
                "기술 처리 경로 추적을 책임 추적으로 대체할 수 없다 (AI-B-03)"
            )
        for span in self.technical_spans:
            if span.trace_id is not None and span.trace_id in chain_ids:
                raise AxisConfusion(
                    f"span {span.name!r} 의 trace_id 가 command_id 와 같다 (AI-B-03)"
                )

    @property
    def top_cause(self) -> CauseKind | None:
        """단독 1위. **동률이면 None** 이다 — 고르지 않는 것이 답이다."""
        if not self.candidates:
            return None
        top = self.candidates[0].kind
        if any(top in tie.causes for tie in self.ties):
            return None
        return top

    def tied_top(self) -> tuple[CauseKind, ...]:
        if not self.candidates:
            return ()
        top = self.candidates[0].kind
        for tie in self.ties:
            if top in tie.causes:
                return tie.ordered
        return (top,)

    @property
    def inconclusive(self) -> bool:
        """후보가 없거나 1위가 동률이다. 화면은 이 경우 원인을 적지 않는다."""
        return not self.candidates or self.top_cause is None

    def candidate(self, kind: CauseKind) -> CandidateCause | None:
        for cand in self.candidates:
            if cand.kind is kind:
                return cand
        return None

    def verdict(self, kind: CauseKind) -> CauseVerdict:
        return self.verdicts.get(kind, CauseVerdict.NOT_MEASURED)

    def axes(self) -> dict[str, tuple]:
        """두 축을 **이름으로** 내준다. 어느 쪽도 다른 쪽의 기본값이 아니다."""
        return {
            "business_accountability": self.business_chain,
            "technical_performance": self.technical_spans,
        }

    def explain(self) -> str:
        lines = [f"subject={self.subject_id} window={self.window.start:.3f}..{self.window.end:.3f}"]
        for cand in self.candidates:
            lines.append(cand.explain())
        for tie in self.ties:
            lines.append(
                "동률(" + tie.reason + "): " + ", ".join(c.value for c in tie.ordered)
            )
        for gap in self.not_measured:
            lines.append(f"미측정: {gap.subject} ({gap.state.value})")
        for event in self.fatal_events:
            lines.append(f"치명 사건: {event.name} severity={event.severity}")
        if not self.candidates:
            lines.append("원인 후보 없음 — 근거가 없다. 정상이라는 뜻이 아니다.")
        return "\n".join(lines)


# ── 규칙 (교체 가능한 정책, AI-C-13) ─────────────────────────────────────────


@dataclass(frozen=True)
class Signals:
    """규칙이 보는 전부. 규칙은 provider 도 질의도 모른다 — 모아 온 사실만 본다."""

    query: FailureQuery
    metrics: tuple[MetricSeries, ...] = ()
    spans: SpanView = SpanView(DataState.NOT_SCRAPED)
    events: EventView = EventView(DataState.NOT_SCRAPED)
    business_chain: tuple[BusinessChainLink, ...] = ()
    lineage: LearningLineage | None = None

    def metric(self, name: str) -> MetricSeries | None:
        for series in self.metrics:
            if series.name == name:
                return series
        return None


#: 규칙 하나는 모아 온 사실에서 근거 행을 뽑는 함수다. 목록 자체가 정책이고
#: 서비스 생성 시 갈아끼울 수 있다 — 점수식을 프레임워크에 고정하지 않는다(AI-C-13).
AttributionRule = Callable[[Signals], Sequence[Evidence]]


def rule_metric_targets(signals: Signals) -> Sequence[Evidence]:
    """목표를 넘긴 계측만 근거로 올린다. 미측정은 **근거가 아니다**."""
    out: list[Evidence] = []
    specs = {spec.name: spec for spec in signals.query.metric_specs}
    for series in signals.metrics:
        if series.meet_state is not MeetState.UNMET:
            continue
        spec = specs.get(series.name)
        if spec is None:
            continue
        worst = series.worst
        out.append(
            Evidence(
                cause=spec.speaks_for,
                source=EvidenceSource.METRIC,
                reference=series.name,
                detail=REASON_METRIC_UNMET,
                weight=W_METRIC_UNMET,
                at=worst.at if worst is not None else None,
                note=None
                if worst is None or series.target is None
                else f"worst {worst.value} {worst.unit} vs target "
                f"{series.target.direction.value} {series.target.value}",
            )
        )
    return out


def rule_fatal_events(signals: Signals) -> Sequence[Evidence]:
    """개별 치명 사건 → 근거. 창의 요약이 평온해도 이 길은 따로 열려 있다(요건 2).

    원인 축 매핑이 없는 사건은 근거가 되지 못하지만 보고서에서 사라지지도 않는다 —
    `unattributed_fatal_events` 가 그 자리이고, 서비스가 채운다.
    """
    mapping = signals.query.fatal_event_causes
    out: list[Evidence] = []
    for event in signals.events.fatal():
        cause = mapping.get(event.name)
        if cause is None:
            continue
        out.append(
            Evidence(
                cause=cause,
                source=EvidenceSource.EVENT,
                reference=event.name,
                detail=REASON_FATAL_EVENT,
                weight=W_FATAL_EVENT,
                at=event.at,
                note=f"severity={event.severity}",
            )
        )
    return out


def rule_span_budgets(signals: Signals) -> Sequence[Evidence]:
    """예산을 넘긴 처리 구간 → 근거. 지연이 **어디서** 났는지의 축이다."""
    out: list[Evidence] = []
    if signals.spans.state is not DataState.PRESENT:
        return out
    for spec in signals.query.span_specs:
        if spec.budget_ms is None:
            continue
        for span in signals.spans.spans:
            if not span.name.startswith(spec.name_prefix):
                continue
            if span.duration_ms is None or span.duration_ms <= spec.budget_ms:
                continue
            out.append(
                Evidence(
                    cause=spec.speaks_for,
                    source=EvidenceSource.SPAN,
                    reference=span.name,
                    detail=REASON_SPAN_OVER_BUDGET,
                    weight=W_SPAN_OVER_BUDGET,
                    at=span.started_at,
                    note=f"{span.duration_ms:.1f}ms > {spec.budget_ms:.1f}ms budget",
                )
            )
    return out


#: 거부 코드 → 원인 축. 이 어휘는 `contracts/physical_command.py` 가 소유한 **프레임워크
#: 어휘**라 여기 적어도 벤더·도메인이 섞이지 않는다. 나머지 코드는 의도적으로 비운다 —
#: INVALID_ARGUMENT 는 호출자 잘못이고 관측으로 원인을 세울 사안이 아니다.
REJECTION_CAUSES: Mapping[RejectionCode, CauseKind] = {
    RejectionCode.RESOURCE_EXHAUSTED: CauseKind.RESOURCE,
    RejectionCode.UNIMPLEMENTED: CauseKind.ORCHESTRATOR,
    RejectionCode.FAILED_PRECONDITION: CauseKind.DEVICE,
}


def rule_business_chain(signals: Signals) -> Sequence[Evidence]:
    """업무 책임 축이 **스스로 말하는** 것만 읽는다.

    두 경우가 있다. 거부는 사유 코드를 들고 오므로 원인 축이 하나로 정해진다. 반대로
    "수락됐는데 종결 보고가 없다"는 장치 급사와 링크 단절을 **가르지 못한다** — 그래서
    같은 지문의 근거 행을 두 축에 똑같이 올린다. 나중에 동률로 드러나는 것이 정직한
    결과이고, 둘 중 하나를 고르는 것이 거짓이다.
    """
    records = signals.query.command_records
    if records is None:
        return []
    out: list[Evidence] = []
    command_id = records.command_id or signals.query.subject_id
    acceptance = records.acceptance
    if acceptance is not None and not acceptance.accepted and acceptance.rejection is not None:
        cause = REJECTION_CAUSES.get(acceptance.rejection.code)
        if cause is not None:
            out.append(
                Evidence(
                    cause=cause,
                    source=EvidenceSource.BUSINESS,
                    reference=command_id,
                    detail=REASON_COMMAND_REJECTED,
                    weight=W_REJECTION,
                    at=acceptance.accepted_at,
                    note=acceptance.rejection.code.value,
                )
            )
    if records.accepted_without_terminal_result:
        last = records.statuses[-1].status if records.statuses else ExecutionStatus.ACCEPTED
        for cause in (CauseKind.DEVICE, CauseKind.LINK):
            out.append(
                Evidence(
                    cause=cause,
                    source=EvidenceSource.BUSINESS,
                    reference=command_id,
                    detail=REASON_NO_TERMINAL_RESULT,
                    weight=W_SILENT_AFTER_ACCEPT,
                    note=f"last seen {last.value}; 이 사실만으로는 장치와 링크를 가를 수 없다",
                )
            )
    return out


def rule_model_lineage(signals: Signals) -> Sequence[Evidence]:
    """모델이 혐의일 때 그 버전의 계보를 이름으로 댄다 (AI-L-08).

    계보를 다시 유도하지 않고 `continual/lineage.py` 가 적어 둔 것을 읽는다. 운영
    검증(VERIFIED)까지 간 버전은 계보만으로 혐의를 두지 않는다 — 그러면 모든 실패가
    언제나 모델 탓이 된다.
    """
    lineage = signals.lineage
    if lineage is None:
        return []
    version = signals.query.model_version or lineage.lineage_id
    if lineage.state is LearningState.DEPLOYED:
        return [
            Evidence(
                cause=CauseKind.MODEL,
                source=EvidenceSource.LINEAGE,
                reference=version,
                detail=REASON_MODEL_NOT_OPERATIONALLY_VERIFIED,
                weight=W_LINEAGE_UNVERIFIED,
                note=f"lineage {lineage.lineage_id} state={lineage.state.value}; "
                f"{len(lineage.events)} recorded transitions",
            )
        ]
    if lineage.state is LearningState.ROLLED_BACK:
        return [
            Evidence(
                cause=CauseKind.MODEL,
                source=EvidenceSource.LINEAGE,
                reference=version,
                detail=REASON_MODEL_ROLLED_BACK,
                weight=W_LINEAGE_UNVERIFIED,
                note=f"lineage {lineage.lineage_id} 가 이미 복구된 버전이다",
            )
        ]
    return []


DEFAULT_RULES: tuple[AttributionRule, ...] = (
    rule_metric_targets,
    rule_fatal_events,
    rule_span_budgets,
    rule_business_chain,
    rule_model_lineage,
)


# ── 서비스 ────────────────────────────────────────────────────────────────────


class FailureTraceService:
    """실패 하나를 받아 순위 있는 원인 후보와 공백 목록을 낸다.

    reader 는 provider 경계 뒤의 아무것이어도 되고, 아예 없어도 된다 — 없으면 전부
    미측정으로 답한다(요건 5). 생성자는 어떤 백엔드에도 접속하지 않는다.
    """

    def __init__(
        self,
        reader: ObservabilityQueryProvider | None = None,
        *,
        rules: Sequence[AttributionRule] = DEFAULT_RULES,
        lineage_lookup: Callable[[str], LearningLineage | None] | None = None,
        tie_epsilon: float = DEFAULT_TIE_EPSILON,
        evidence_saturation: float = EVIDENCE_SATURATION,
    ) -> None:
        self._reader = reader
        self._rules = tuple(rules)
        self._lineage_lookup = lineage_lookup
        self._tie_epsilon = tie_epsilon
        self._saturation = evidence_saturation

    # -- 수집 -------------------------------------------------------------

    def _unreachable_metric(self, spec: MetricSpec, note: str) -> MetricSeries:
        return MetricSeries(
            name=spec.name,
            state=DataState.BACKEND_UNREACHABLE,
            target=spec.target,
            selector=spec.selector,
            note=note,
        )

    def _collect(self, query: FailureQuery) -> Signals:
        """읽기 실패는 전부 상태로 환산한다. 예외가 이 함수 밖으로 나가지 않는다."""
        reader = self._reader
        if reader is None or not _reachable(reader):
            note = "no observability reader configured" if reader is None else "reader unreachable"
            return Signals(
                query=query,
                metrics=tuple(self._unreachable_metric(s, note) for s in query.metric_specs),
                spans=SpanView(DataState.BACKEND_UNREACHABLE, note=note),
                events=EventView(DataState.BACKEND_UNREACHABLE, note=note),
                business_chain=()
                if query.command_records is None
                else query.command_records.chain(),
                lineage=self._lineage(query),
            )

        metrics: list[MetricSeries] = []
        for spec in query.metric_specs:
            series = _safe(
                lambda s=spec: reader.metric_series(s.name, query.window, dict(s.selector)),
                fallback=None,
            )
            if series is None:
                metrics.append(self._unreachable_metric(spec, "metric query failed"))
                continue
            # 목표는 질의가 소유한다 — provider 는 값만 읽고 기준은 모른다.
            metrics.append(_apply_target(replace(series, selector=spec.selector), spec.target))

        spans = _safe(
            lambda: reader.span_view(query.window, trace_id=query.trace_id),
            fallback=SpanView(DataState.BACKEND_UNREACHABLE, note="span query failed"),
        )
        events = _safe(
            lambda: reader.event_view(query.window, subject_id=query.subject_id),
            fallback=EventView(DataState.BACKEND_UNREACHABLE, note="event query failed"),
        )
        return Signals(
            query=query,
            metrics=tuple(metrics),
            spans=spans,
            events=events,
            business_chain=()
            if query.command_records is None
            else query.command_records.chain(),
            lineage=self._lineage(query),
        )

    def _lineage(self, query: FailureQuery) -> LearningLineage | None:
        if self._lineage_lookup is None or query.model_version is None:
            return None
        return _safe(lambda: self._lineage_lookup(query.model_version), fallback=None)

    # -- 판정 -------------------------------------------------------------

    def attribute(self, query: FailureQuery) -> FailureAttribution:
        """이 모듈의 유일한 입구. 개발자 화면이 호출하는 한 줄이다."""
        signals = self._collect(query)
        evidence = [ev for rule in self._rules for ev in _safe(lambda r=rule: list(r(signals)), fallback=[])]
        candidates, ties = self._rank(evidence)
        return FailureAttribution(
            subject_id=query.subject_id,
            window=query.window,
            candidates=candidates,
            ties=ties,
            verdicts=self._verdicts(signals, candidates),
            fatal_events=signals.events.fatal(),
            unattributed_fatal_events=tuple(
                e for e in signals.events.fatal() if e.name not in query.fatal_event_causes
            ),
            not_measured=self._gaps(signals),
            business_chain=signals.business_chain,
            technical_spans=signals.spans.spans,
            reproduction=query.reproduction or ReproductionReference(),
            backend_states=self._backend_states(signals),
        )

    def _rank(
        self, evidence: Sequence[Evidence]
    ) -> tuple[tuple[CandidateCause, ...], tuple[Tie, ...]]:
        by_cause: dict[CauseKind, list[Evidence]] = {}
        for ev in evidence:
            by_cause.setdefault(ev.cause, []).append(ev)
        if not by_cause:
            return ((), ())

        total = sum(ev.weight for ev in evidence)
        # 확신도 = 근거 몫 × 근거 포화도. 몫만 쓰면 근거 1줄도 100% 가 되고, 포화도만
        # 쓰면 두 원인을 구별하지 못한다. 두 인자 모두 explain() 이 그대로 적는다.
        saturation = min(1.0, total / self._saturation) if self._saturation > 0 else 1.0

        raw: list[CandidateCause] = []
        for cause, rows in by_cause.items():
            weight = sum(r.weight for r in rows)
            raw.append(
                CandidateCause(
                    kind=cause,
                    confidence=round((weight / total) * saturation, 6),
                    evidence=tuple(sorted(rows, key=lambda r: (-r.weight, r.reference))),
                )
            )
        raw.sort(key=lambda c: (-c.confidence, c.kind.value))

        ties = self._find_ties(raw)
        contested: dict[CauseKind, set[CauseKind]] = {}
        for tie in ties:
            for cause in tie.causes:
                contested.setdefault(cause, set()).update(tie.causes - {cause})
        ranked = tuple(
            replace(
                cand,
                contested_with=tuple(sorted(contested.get(cand.kind, ()), key=lambda c: c.value)),
            )
            for cand in raw
        )
        return ranked, ties

    def _find_ties(self, candidates: Sequence[CandidateCause]) -> tuple[Tie, ...]:
        """가르지 못한 묶음을 찾는다. 두 가지 뜻이 있고 사유 토큰으로 구별한다."""
        ties: list[Tie] = []
        used: set[CauseKind] = set()
        for i, first in enumerate(candidates):
            if first.kind in used:
                continue
            group = [first]
            for second in candidates[i + 1 :]:
                if second.kind in used:
                    continue
                if abs(first.confidence - second.confidence) <= self._tie_epsilon:
                    group.append(second)
            if len(group) < 2:
                continue
            prints = [frozenset(e.fingerprint for e in cand.evidence) for cand in group]
            # 같은 관측에 기대고 있으면 "가를 수 없다", 그저 점수가 같으면 "같은 점수".
            shared = all(p == prints[0] for p in prints)
            ties.append(
                Tie(
                    causes=frozenset(cand.kind for cand in group),
                    reason=TIE_INDISTINGUISHABLE if shared else TIE_EQUAL_CONFIDENCE,
                )
            )
            used.update(cand.kind for cand in group)
        return tuple(ties)

    def _verdicts(
        self, signals: Signals, candidates: Sequence[CandidateCause]
    ) -> dict[CauseKind, CauseVerdict]:
        """축마다 "혐의 / 무혐의 / 못 봤다"를 적는다.

        CLEARED 는 **값을 보고 목표를 만족했을 때만** 쓴다. 공백은 CLEARED 가 아니고
        (요건 1), 그래서 수집기가 꺼진 노드의 보고서는 모든 축이 NOT_MEASURED 다.
        """
        suspect = {cand.kind for cand in candidates}
        cleared: set[CauseKind] = set()
        specs = {spec.name: spec for spec in signals.query.metric_specs}
        for series in signals.metrics:
            spec = specs.get(series.name)
            if spec is not None and series.meet_state is MeetState.MET:
                cleared.add(spec.speaks_for)
        if signals.spans.state is DataState.PRESENT:
            for spec in signals.query.span_specs:
                if spec.budget_ms is None:
                    continue
                matched = [s for s in signals.spans.spans if s.name.startswith(spec.name_prefix)]
                timed = [s for s in matched if s.duration_ms is not None]
                if timed and all(s.duration_ms <= spec.budget_ms for s in timed):
                    cleared.add(spec.speaks_for)
        return {
            kind: CauseVerdict.SUSPECT
            if kind in suspect
            else (CauseVerdict.CLEARED if kind in cleared else CauseVerdict.NOT_MEASURED)
            for kind in CauseKind
        }

    def _gaps(self, signals: Signals) -> tuple[NotMeasuredGap, ...]:
        gaps: list[NotMeasuredGap] = []
        for series in signals.metrics:
            if series.state in _UNMEASURED_STATES:
                gaps.append(NotMeasuredGap(series.name, series.state, series.note))
            elif series.target is None:
                # 값은 있지만 기준이 없다 — 정상이라고 말할 근거도 없다. 기준이 단위
                # 충돌로 떨어진 경우에는 그 사유가 더 구체적이므로 덮지 않는다.
                gaps.append(
                    NotMeasuredGap(
                        series.name,
                        DataState.NOT_SCRAPED,
                        series.note or "no target baseline declared",
                    )
                )
        if signals.spans.state in _UNMEASURED_STATES:
            gaps.append(NotMeasuredGap(SUBJECT_SPANS, signals.spans.state, signals.spans.note))
        if signals.events.state in _UNMEASURED_STATES:
            gaps.append(NotMeasuredGap(SUBJECT_EVENTS, signals.events.state, signals.events.note))
        return tuple(gaps)

    def _backend_states(self, signals: Signals) -> dict[str, DataState]:
        states = {SUBJECT_SPANS: signals.spans.state, SUBJECT_EVENTS: signals.events.state}
        for series in signals.metrics:
            states[series.name] = series.state
        return states


def _apply_target(
    series: MetricSeries, target: TargetBaseline | None
) -> MetricSeries:
    """질의가 선언한 기준을 계측에 붙인다. 단위를 맞출 수 없으면 기준을 **버린다**.

    provider 는 단위를 모르는 채 `UNKNOWN_UNIT` 을 적어 온다(위 상수 참조). 그 표본에
    질의가 선언한 단위를 찍는 것은 선언을 적용하는 일이지 값을 바꾸는 일이 아니다.
    그러나 표본이 **다른 단위를 명시**하고 있으면 그것은 진짜 계약 충돌이므로 조용히
    환산하지 않는다 — 기준 없이 두고 미측정 공백으로 드러낸다(AI-O-05: 못 잰 것을
    미달로 적지 않는다). 여기서 묻으면 "단위가 어긋난 기준선"이 판정에 쓰인다.
    """
    if target is None:
        return replace(series, target=None)
    stamped = tuple(
        replace(sample, unit=target.unit) if sample.unit == UNKNOWN_UNIT else sample
        for sample in series.samples
    )
    mismatched = {s.unit for s in stamped if s.unit != target.unit}
    if mismatched:
        return replace(
            series,
            samples=stamped,
            target=None,
            note=f"unit mismatch: target {target.unit!r} vs samples {sorted(mismatched)}",
        )
    return replace(series, samples=stamped, target=target)


def _reachable(reader: ObservabilityQueryProvider) -> bool:
    """닿는지 묻는 일조차 실패할 수 있다. 실패는 "닿지 않는다"로 읽는다."""
    return bool(_safe(reader.is_reachable, fallback=False))


def _safe(call, *, fallback):
    """관측 경로의 예외를 이 모듈 안에 가둔다 (AI-O-01, 요건 5).

    provider 가 계약을 깨고 예외를 던져도 관측 **대상**은 멈추지 않아야 하고, 이
    서비스는 축소된 답(미측정)을 내야 한다. 그래서 넓게 잡는다 — 여기서 좁게 잡으면
    예상하지 못한 한 줄이 실패 분석 전체를 못 쓰게 만든다.
    """
    try:
        return call()
    except Exception:
        return fallback
