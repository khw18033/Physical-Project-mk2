"""implements: AI-O-02, AI-O-03, AI-O-05
관련: AI-B-03 (업무 축과 기술 축의 분리), AI-O-01 (관측 장애 격리), AI-L-08 (계보)
covers: 닿지 못한 수집기는 "정상"이 아니라 미측정이다 · 요약이 평온해도 개별 치명
        사건은 드러난다 · 가르지 못한 두 원인은 동률로 적는다 · 책임 축과 처리 경로
        축은 끝까지 다른 필드다 · 재현 참조가 실려 나간다 · 백엔드가 전혀 없는
        노드에서도 import 되고 답한다 · 실제 Collector 파일 왕복

실제 스택이 떠 있으면 실물 엔드포인트까지 한 바퀴 돌고, 없으면 그 묶음만 skip 한다
(`tests/test_real_stack.py` 의 방식). 선택 구성요소 결손은 축소이지 실패가 아니다.
"""

from __future__ import annotations

import importlib.util
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from mission_runtime.contracts.physical_command import (
    Command,
    CommandAcceptance,
    CommandResult,
    CommandStatus,
    ExecutionStatus,
    Failure,
    Rejection,
    RejectionCode,
)
from mission_runtime.continual.lineage import LearningLineage
from mission_runtime.observability.failure_trace import (
    UNKNOWN_UNIT,
    AxisConfusion,
    CandidateCause,
    CauseKind,
    CauseVerdict,
    CommandRecords,
    DataState,
    Evidence,
    EvidenceSource,
    EventView,
    FailureAttribution,
    FailureQuery,
    FailureTraceService,
    MetricSeries,
    MetricSpec,
    ObservabilityQueryProvider,
    ObservedEvent,
    REASON_FATAL_EVENT,
    REASON_NO_TERMINAL_RESULT,
    SUBJECT_EVENTS,
    SUBJECT_SPANS,
    SpanRow,
    SpanSpec,
    SpanView,
    TIE_INDISTINGUISHABLE,
    TimeWindow,
)
from mission_runtime.observability.layered_metrics import (
    Direction,
    Measurement,
    MeetState,
    TargetBaseline,
)
from mission_runtime.observability.metrics import EdgeMetricStore
from mission_runtime.observability.reproduction import (
    ReproductionReference,
    ReproductionReferenceBuilder,
)
from mission_runtime.providers.fakes import InMemoryObservabilityProvider
from mission_runtime.providers.observability_query import (
    CollectorFileExportReader,
    CompositeQueryProvider,
    HttpMetricQueryProvider,
    LocalEventQueryProvider,
    MetricQueryEndpoint,
)

WINDOW = TimeWindow(1000.0, 1060.0)

LATENCY_TARGET = TargetBaseline(50.0, Direction.AT_MOST, "ms")
UTILISATION_TARGET = TargetBaseline(0.9, Direction.AT_MOST, "ratio")

LATENCY = MetricSpec("inference.latency_ms", CauseKind.MODEL, LATENCY_TARGET)
UTILISATION = MetricSpec("accelerator.utilisation", CauseKind.RESOURCE, UTILISATION_TARGET)


# ── 손으로 만든 reader (경계만 지키고 백엔드는 없다) ─────────────────────────


class StubReader:
    """`ObservabilityQueryProvider` 를 만족하는 최소 구현. 무엇을 돌려줄지 시험이 정한다."""

    def __init__(self, *, reachable=True, metrics=None, spans=None, events=None) -> None:
        self._reachable = reachable
        self._metrics = metrics or {}
        self._spans = spans or SpanView(DataState.NOT_SCRAPED)
        self._events = events or EventView(DataState.NOT_SCRAPED)

    def is_reachable(self) -> bool:
        return self._reachable

    def metric_series(self, name, window, selector=None) -> MetricSeries:
        return self._metrics.get(
            name, MetricSeries(name=name, state=DataState.NOT_SCRAPED, note="not in stub")
        )

    def span_view(self, window, *, trace_id=None) -> SpanView:
        return self._spans

    def event_view(self, window, *, subject_id=None) -> EventView:
        return self._events


class ExplodingReader:
    """계약을 깨고 모든 호출에서 터지는 reader. 관측 장애의 가장 거친 형태."""

    def is_reachable(self) -> bool:
        return True

    def metric_series(self, name, window, selector=None):
        raise RuntimeError("query backend exploded")

    def span_view(self, window, *, trace_id=None):
        raise RuntimeError("query backend exploded")

    def event_view(self, window, *, subject_id=None):
        raise RuntimeError("query backend exploded")


def series(name, values, *, unit="ms", start=1010.0):
    return MetricSeries(
        name=name,
        state=DataState.PRESENT,
        samples=tuple(
            Measurement(value, unit, at=start + index) for index, value in enumerate(values)
        ),
    )


def fatal(name, at=1030.0, severity="fatal", **payload):
    return ObservedEvent(
        name=name,
        severity=severity,
        at=at,
        payload=tuple((str(k), str(v)) for k, v in payload.items()),
    )


# ── 요건 1: 못 봤다 ≠ 정상이다 ───────────────────────────────────────────────


def test_a_node_with_no_observability_backend_still_imports_and_answers():
    """백엔드가 아예 없어도 답한다. 그 답이 "미측정"이다 (요건 5)."""
    report = FailureTraceService().attribute(
        FailureQuery("step-7", WINDOW, metric_specs=(LATENCY, UTILISATION))
    )

    assert report.candidates == ()
    assert report.inconclusive
    assert report.top_cause is None
    # 다섯 축 전부 미측정. 어느 축도 무혐의로 적히지 않는다.
    assert set(report.verdicts.values()) == {CauseVerdict.NOT_MEASURED}
    assert {gap.subject for gap in report.not_measured} == {
        LATENCY.name,
        UTILISATION.name,
        SUBJECT_SPANS,
        SUBJECT_EVENTS,
    }
    assert all(gap.meet_state is MeetState.NOT_MEASURED for gap in report.not_measured)
    assert "정상이라는 뜻이 아니다" in report.explain()


def test_unreachable_collector_is_not_measured_rather_than_healthy():
    """닫힌 포트를 향한 실제 HTTP 질의 — 닿지 못함이 "정상"으로 접히지 않는다."""
    dead_port = _closed_port()
    reader = HttpMetricQueryProvider(
        MetricQueryEndpoint(base_url=f"http://127.0.0.1:{dead_port}", timeout_s=0.3)
    )
    assert reader.is_reachable() is False

    report = FailureTraceService(reader).attribute(
        FailureQuery("step-7", WINDOW, metric_specs=(LATENCY, UTILISATION))
    )

    assert report.verdict(CauseKind.MODEL) is CauseVerdict.NOT_MEASURED
    assert report.verdict(CauseKind.RESOURCE) is not CauseVerdict.CLEARED
    assert report.backend_states[LATENCY.name] is DataState.BACKEND_UNREACHABLE
    assert report.candidates == ()


def test_a_selector_on_a_label_the_deployment_refuses_explains_itself():
    """금지 라벨 선택자는 질의를 **보내지 않고** 사유를 적는다.

    `command_id` 같은 이름은 쓰는 쪽이 거부하므로 그 라벨이 붙은 시계열은 생기지
    않는다(`deployment_topology.FORBIDDEN_METRIC_LABELS`). 닫힌 포트를 꽂아 두고도
    BACKEND_UNREACHABLE 이 아닌 NOT_SCRAPED 가 나오는 것이 "보내지 않았다"의 증거다
    — 명령 하나를 되짚는 일은 계측이 아니라 업무 축과 구간의 몫이다(AI-B-03).
    """
    reader = HttpMetricQueryProvider(
        MetricQueryEndpoint(base_url=f"http://127.0.0.1:{_closed_port()}", timeout_s=0.3)
    )

    series = reader.metric_series(LATENCY.name, WINDOW, {"command_id": "cmd-1"})

    assert series.state is DataState.NOT_SCRAPED
    assert "command_id" in (series.note or "")
    assert series.meet_state is MeetState.NOT_MEASURED


def test_three_data_states_stay_three_answers():
    """닿지 못함 · 긁힌 표본 없음 · 긁혔고 정상 — 세 답이 하나로 접히지 않는다."""
    reader = StubReader(
        metrics={
            # 긁혔고 목표 안쪽
            LATENCY.name: series(LATENCY.name, [20.0, 22.0]),
            # 닿았는데 이 이름으로는 표본이 없다
            UTILISATION.name: MetricSeries(
                name=UTILISATION.name, state=DataState.NOT_SCRAPED, note="never scraped"
            ),
        },
        # 구간 평면 자체에 닿지 못했다
        spans=SpanView(DataState.BACKEND_UNREACHABLE, note="collector down"),
    )
    report = FailureTraceService(reader).attribute(
        FailureQuery("step-7", WINDOW, metric_specs=(LATENCY, UTILISATION))
    )

    assert report.backend_states[LATENCY.name] is DataState.PRESENT
    assert report.backend_states[UTILISATION.name] is DataState.NOT_SCRAPED
    assert report.backend_states[SUBJECT_SPANS] is DataState.BACKEND_UNREACHABLE
    # 값을 보고 목표를 만족한 축만 무혐의다.
    assert report.verdict(CauseKind.MODEL) is CauseVerdict.CLEARED
    assert report.verdict(CauseKind.RESOURCE) is CauseVerdict.NOT_MEASURED
    gaps = {gap.subject: gap.state for gap in report.not_measured}
    assert gaps[UTILISATION.name] is DataState.NOT_SCRAPED
    assert gaps[SUBJECT_SPANS] is DataState.BACKEND_UNREACHABLE


def test_a_metric_without_a_declared_target_cannot_clear_a_cause():
    """값은 있지만 기준이 없으면 "정상"이라고 말할 근거도 없다."""
    no_target = MetricSpec("inference.latency_ms", CauseKind.MODEL, target=None)
    reader = StubReader(metrics={no_target.name: series(no_target.name, [20.0])})

    report = FailureTraceService(reader).attribute(
        FailureQuery("step-7", WINDOW, metric_specs=(no_target,))
    )

    assert report.verdict(CauseKind.MODEL) is CauseVerdict.NOT_MEASURED
    gap = next(g for g in report.not_measured if g.subject == no_target.name)
    assert gap.note == "no target baseline declared"


def test_a_unit_mismatch_drops_the_target_instead_of_judging_with_it():
    """단위가 어긋난 기준선으로 판정하지 않는다 (AI-O-05)."""
    reader = StubReader(metrics={LATENCY.name: series(LATENCY.name, [900.0], unit="us")})

    report = FailureTraceService(reader).attribute(
        FailureQuery("step-7", WINDOW, metric_specs=(LATENCY,))
    )

    assert report.verdict(CauseKind.MODEL) is CauseVerdict.NOT_MEASURED
    gap = next(g for g in report.not_measured if g.subject == LATENCY.name)
    assert "unit mismatch" in (gap.note or "")


def test_provider_unit_unknown_is_stamped_from_the_declared_target():
    """단위를 실어 보내지 않는 질의 프로토콜에서도 선언된 기준으로 판정할 수 있다."""
    reader = StubReader(
        metrics={LATENCY.name: series(LATENCY.name, [90.0], unit=UNKNOWN_UNIT)}
    )

    report = FailureTraceService(reader).attribute(
        FailureQuery("step-7", WINDOW, metric_specs=(LATENCY,))
    )

    assert report.verdict(CauseKind.MODEL) is CauseVerdict.SUSPECT


# ── 요건 2: 요약이 가린 개별 사건 ────────────────────────────────────────────


def test_a_fatal_event_surfaces_even_when_the_summary_window_looks_normal():
    """원칙 #14 / AI-O-02: 창의 요약이 평온해도 개별 치명 사건은 따로 나온다."""
    healthy_values = [20.0, 21.0, 19.0, 22.0]
    summary_store = EdgeMetricStore()
    for index, value in enumerate(healthy_values):
        summary_store.record(LATENCY.name, value, at=1010.0 + index)
    summary = summary_store.summarize(LATENCY.name)
    assert summary is not None and summary.max < LATENCY_TARGET.value  # 요약은 평온하다

    reader = StubReader(
        metrics={LATENCY.name: series(LATENCY.name, healthy_values)},
        events=EventView(DataState.PRESENT, (fatal("device_death", device_id="robot-1"),)),
    )
    report = FailureTraceService(reader).attribute(
        FailureQuery(
            "step-7",
            WINDOW,
            metric_specs=(LATENCY,),
            fatal_event_causes={"device_death": CauseKind.DEVICE},
        )
    )

    # 요약을 읽고 들어왔어도 사건은 개별로 남아 있다.
    assert [event.name for event in report.fatal_events] == ["device_death"]
    assert report.top_cause is CauseKind.DEVICE
    assert report.verdict(CauseKind.MODEL) is CauseVerdict.CLEARED
    evidence = report.candidate(CauseKind.DEVICE).evidence
    assert [e.detail for e in evidence] == [REASON_FATAL_EVENT]
    assert evidence[0].source is EvidenceSource.EVENT


def test_a_fatal_event_the_rules_cannot_attribute_is_still_surfaced():
    """분류 실패를 사건 폐기로 바꾸지 않는다 (AI-O-02)."""
    reader = StubReader(
        events=EventView(DataState.PRESENT, (fatal("unknown_board_fault"),))
    )
    report = FailureTraceService(reader).attribute(FailureQuery("step-7", WINDOW))

    assert report.candidates == ()
    assert [e.name for e in report.fatal_events] == ["unknown_board_fault"]
    assert [e.name for e in report.unattributed_fatal_events] == ["unknown_board_fault"]


def test_a_non_fatal_event_is_not_promoted_to_a_fatal_one():
    """선택 기능 결손 같은 정상적 축소 운용을 치명 오류로 세지 않는다 (AI-O-02)."""
    reader = StubReader(
        events=EventView(
            DataState.PRESENT, (fatal("optional_capability_lost", severity="warning"),)
        )
    )
    report = FailureTraceService(reader).attribute(FailureQuery("step-7", WINDOW))

    assert report.fatal_events == ()
    assert report.unattributed_fatal_events == ()


# ── 요건 3: 순위와 근거, 그리고 가르지 못했다는 사실 ─────────────────────────


def test_two_indistinguishable_causes_produce_an_explicit_tie_not_a_pick():
    """수락됐고 종결 보고가 없다 — 장치 급사와 링크 단절을 가를 수 없다."""
    records = CommandRecords(
        command=Command(command_id="cmd-1", target="robot-1", action="move"),
        acceptance=CommandAcceptance("cmd-1", accepted=True, accepted_at=1005.0),
        statuses=(CommandStatus("cmd-1", ExecutionStatus.EXECUTING, 1006.0),),
        result=None,
    )
    report = FailureTraceService(StubReader()).attribute(
        FailureQuery("cmd-1", WINDOW, command_records=records)
    )

    assert {c.kind for c in report.candidates} == {CauseKind.DEVICE, CauseKind.LINK}
    assert len(report.ties) == 1
    tie = report.ties[0]
    assert tie.causes == frozenset({CauseKind.DEVICE, CauseKind.LINK})
    assert tie.reason == TIE_INDISTINGUISHABLE
    # 하나를 고르지 않는 것이 답이다.
    assert report.top_cause is None
    assert report.inconclusive
    assert report.tied_top() == (CauseKind.DEVICE, CauseKind.LINK)
    for candidate in report.candidates:
        other = CauseKind.LINK if candidate.kind is CauseKind.DEVICE else CauseKind.DEVICE
        assert candidate.contested_with == (other,)
        assert [e.detail for e in candidate.evidence] == [REASON_NO_TERMINAL_RESULT]
    assert "동률" in report.explain()


def test_an_extra_observation_breaks_the_tie_and_the_pick_is_then_named():
    """같은 질의에 치명 사건 하나가 더해지면 동률이 깨진다 — 근거가 갈랐을 때만."""
    records = CommandRecords(
        acceptance=CommandAcceptance("cmd-1", accepted=True, accepted_at=1005.0)
    )
    reader = StubReader(
        events=EventView(DataState.PRESENT, (fatal("device_death", device_id="robot-1"),))
    )
    report = FailureTraceService(reader).attribute(
        FailureQuery(
            "cmd-1",
            WINDOW,
            command_records=records,
            fatal_event_causes={"device_death": CauseKind.DEVICE},
        )
    )

    assert report.top_cause is CauseKind.DEVICE
    assert report.ties == ()
    assert report.candidates[0].confidence > report.candidates[1].confidence


def test_a_single_weak_observation_does_not_earn_full_confidence():
    """근거 몫만 쓰면 한 줄짜리 근거도 100% 가 된다. 포화도가 그것을 막는다."""
    records = CommandRecords(
        acceptance=CommandAcceptance("cmd-1", accepted=False, accepted_at=1005.0,
                                     rejection=Rejection(RejectionCode.UNIMPLEMENTED, "no capability"))
    )
    report = FailureTraceService(StubReader()).attribute(
        FailureQuery("cmd-1", WINDOW, command_records=records)
    )

    only = report.candidates[0]
    assert only.kind is CauseKind.ORCHESTRATOR
    assert only.total_weight == pytest.approx(3.0)
    # 유일한 후보라 몫은 1.0 이지만 확신도는 포화도만큼 깎인다.
    assert 0.0 < only.confidence < 1.0
    assert only.confidence == pytest.approx(3.0 / 6.0)


def test_every_candidate_carries_the_observations_that_support_it():
    """단정하지 않는다 — 후보마다 자기를 지지한 행을 들고 다닌다."""
    reader = StubReader(
        metrics={
            LATENCY.name: series(LATENCY.name, [120.0, 130.0]),
            UTILISATION.name: series(UTILISATION.name, [0.95], unit="ratio"),
        },
        spans=SpanView(
            DataState.PRESENT,
            (
                SpanRow(
                    name="inference.forward",
                    span_id="s1",
                    trace_id="trace-a",
                    duration_ms=410.0,
                    started_at=1020.0,
                ),
            ),
        ),
    )
    report = FailureTraceService(reader).attribute(
        FailureQuery(
            "step-7",
            WINDOW,
            metric_specs=(LATENCY, UTILISATION),
            span_specs=(SpanSpec("inference.", CauseKind.MODEL, budget_ms=100.0),),
            trace_id="trace-a",
        )
    )

    model = report.candidate(CauseKind.MODEL)
    assert {e.source for e in model.evidence} == {EvidenceSource.METRIC, EvidenceSource.SPAN}
    assert report.candidate(CauseKind.RESOURCE) is not None
    # 모델 쪽 근거가 둘이라 자원 쪽 한 줄보다 앞선다. 순서는 결정적이다.
    assert report.candidates[0].kind is CauseKind.MODEL
    assert [c.kind for c in report.candidates] == [CauseKind.MODEL, CauseKind.RESOURCE]
    explanation = model.explain()
    assert "METRIC" in explanation and "SPAN" in explanation and "weight" in explanation


def test_ranking_is_deterministic_for_the_same_input():
    reader = StubReader(
        metrics={
            LATENCY.name: series(LATENCY.name, [120.0]),
            UTILISATION.name: series(UTILISATION.name, [0.99], unit="ratio"),
        }
    )
    query = FailureQuery("step-7", WINDOW, metric_specs=(LATENCY, UTILISATION))
    service = FailureTraceService(reader)

    first = [(c.kind, c.confidence) for c in service.attribute(query).candidates]
    second = [(c.kind, c.confidence) for c in service.attribute(query).candidates]
    assert first == second
    # 같은 확신도면 이름 오름차순 — 임의 순서가 아니다.
    assert first == [(CauseKind.MODEL, first[0][1]), (CauseKind.RESOURCE, first[1][1])]


def test_a_candidate_cannot_exist_without_evidence():
    with pytest.raises(ValueError):
        CandidateCause(kind=CauseKind.MODEL, confidence=0.9, evidence=())


def test_evidence_with_no_weight_is_not_evidence():
    with pytest.raises(ValueError):
        Evidence(
            cause=CauseKind.MODEL,
            source=EvidenceSource.METRIC,
            reference="x",
            detail="y",
            weight=0.0,
        )


# ── 요건 4: 두 축은 끝까지 다르다 ────────────────────────────────────────────


def test_the_business_chain_and_the_span_view_stay_separate_fields():
    """AI-B-03: command_id 책임 추적과 trace 처리 경로 추적은 서로를 대신하지 않는다."""
    records = CommandRecords(
        command=Command(command_id="cmd-9", target="robot-1", action="inspect"),
        acceptance=CommandAcceptance("cmd-9", accepted=True, accepted_at=1005.0),
        statuses=(CommandStatus("cmd-9", ExecutionStatus.EXECUTING, 1006.0),),
        result=CommandResult(
            "cmd-9",
            ExecutionStatus.ABORTED,
            completed_at=1040.0,
            failure=Failure("SENSOR_TIMEOUT", "no frame"),
        ),
    )
    spans = SpanView(
        DataState.PRESENT,
        (
            SpanRow(
                name="perception.detect",
                span_id="s1",
                trace_id="trace-xyz",
                duration_ms=900.0,
                started_at=1020.0,
            ),
        ),
    )
    report = FailureTraceService(StubReader(spans=spans)).attribute(
        FailureQuery(
            "cmd-9",
            WINDOW,
            command_records=records,
            trace_id="trace-xyz",
            span_specs=(SpanSpec("perception.", CauseKind.DEVICE, budget_ms=200.0),),
            reproduction=ReproductionReference(
                business_correlation_id="cmd-9", trace_id="trace-xyz"
            ),
        )
    )

    axes = report.axes()
    assert set(axes) == {"business_accountability", "technical_performance"}
    # 업무 축은 수락·진행·종결을 각각 들고 있다. 전달 ACK 와 완료가 한 칸이 아니다.
    assert [link.phase for link in report.business_chain] == [
        "ISSUED",
        "ACCEPTED",
        "EXECUTING",
        "ABORTED",
    ]
    assert {link.command_id for link in report.business_chain} == {"cmd-9"}
    assert report.business_chain[-1].detail == "SENSOR_TIMEOUT"
    # 기술 축은 span 만 들고 있고 command_id 를 모른다.
    assert [span.trace_id for span in report.technical_spans] == ["trace-xyz"]
    assert not any("cmd-9" in (span.span_id, span.trace_id) for span in report.technical_spans)
    assert report.reproduction.business_correlation_id == "cmd-9"
    assert report.reproduction.trace_id == "trace-xyz"


def test_putting_a_command_id_in_the_trace_id_slot_is_refused():
    """책임 식별자를 처리 경로 식별자 자리에 넣는 것이 이 혼동의 실제 형태다."""
    with pytest.raises(AxisConfusion):
        FailureAttribution(
            subject_id="cmd-9",
            window=WINDOW,
            business_chain=(
                CommandRecords(
                    acceptance=CommandAcceptance("cmd-9", accepted=True, accepted_at=1.0)
                ).chain()
            ),
            reproduction=ReproductionReference(trace_id="cmd-9"),
        )


def test_a_rejection_is_not_reported_as_an_execution_state():
    """AI-C-20: 거부는 실행 상태가 아니라 별도 수락 결과다."""
    records = CommandRecords(
        acceptance=CommandAcceptance(
            "cmd-2",
            accepted=False,
            accepted_at=1005.0,
            rejection=Rejection(RejectionCode.RESOURCE_EXHAUSTED, "no compute"),
        )
    )
    report = FailureTraceService(StubReader()).attribute(
        FailureQuery("cmd-2", WINDOW, command_records=records)
    )

    phases = [link.phase for link in report.business_chain]
    assert phases == ["REJECTED"]
    assert not any(phase in ExecutionStatus.__members__ for phase in phases)
    assert report.top_cause is CauseKind.RESOURCE
    assert report.candidate(CauseKind.RESOURCE).evidence[0].note == "RESOURCE_EXHAUSTED"


# ── AI-O-03 재현 참조와 AI-L-08 계보 ────────────────────────────────────────


def test_reproduction_references_are_carried_through_untouched():
    """AI-O-03: 확보된 참조 범위에서 재현 정보를 남긴다. 이 모듈은 다시 유도하지 않는다."""
    reference = ReproductionReferenceBuilder().build(
        business_correlation_id="corr-7",
        trace_id="trace-7",
        within_short_term_retention=True,
        short_term_replay_ref="topic/ai.object_record@offset=4211",
        archive_ref="archive://2026-11-02/step-7",
    )
    report = FailureTraceService(StubReader()).attribute(
        FailureQuery("step-7", WINDOW, reproduction=reference)
    )

    assert report.reproduction is reference
    assert report.reproduction.short_term_replay_ref == "topic/ai.object_record@offset=4211"
    # 단기 보존 구간 안이므로 아카이브 참조는 고르지 않는다 — 그 선택은 builder 의 몫이다.
    assert report.reproduction.archive_ref is None
    assert "trace_id" in report.reproduction.available_refs()


def test_a_report_without_any_reference_says_so_instead_of_inventing_one():
    report = FailureTraceService(StubReader()).attribute(FailureQuery("step-7", WINDOW))
    assert report.reproduction.is_empty()


def test_a_model_suspicion_names_the_learning_lineage():
    """AI-L-08: 혐의가 모델 버전이면 그 버전의 학습·검증·승인 이력을 이름으로 댄다."""
    lineage = LearningLineage("lin-3", actor="ops", evidence_ref="ev-1", reason="미확인 객체 반복")
    for _ in range(7):  # CANDIDATE → ... → DEPLOYED
        lineage.advance(actor="ops", evidence_ref="ev-1", reason="진행")
    assert lineage.state.value == "deployed"

    report = FailureTraceService(
        StubReader(), lineage_lookup=lambda version: lineage
    ).attribute(FailureQuery("step-7", WINDOW, model_version="detector@3"))

    model = report.candidate(CauseKind.MODEL)
    assert model is not None
    evidence = model.evidence[0]
    assert evidence.source is EvidenceSource.LINEAGE
    assert evidence.reference == "detector@3"
    assert "lin-3" in (evidence.note or "")


def test_an_operationally_verified_model_is_not_suspected_from_lineage_alone():
    """그러지 않으면 모든 실패가 언제나 모델 탓이 된다."""
    lineage = LearningLineage("lin-4", actor="ops", evidence_ref="ev-1", reason="r")
    for _ in range(8):  # ... → VERIFIED
        lineage.advance(actor="ops", evidence_ref="ev-1", reason="진행")
    assert lineage.state.value == "verified"

    report = FailureTraceService(
        StubReader(), lineage_lookup=lambda version: lineage
    ).attribute(FailureQuery("step-7", WINDOW, model_version="detector@4"))

    assert report.candidate(CauseKind.MODEL) is None


# ── 요건 5: 관측 장애는 이 모듈만 축소시킨다 ────────────────────────────────


def test_a_reader_that_raises_degrades_this_module_and_nothing_else():
    report = FailureTraceService(ExplodingReader()).attribute(
        FailureQuery("step-7", WINDOW, metric_specs=(LATENCY,))
    )

    assert report.backend_states[LATENCY.name] is DataState.BACKEND_UNREACHABLE
    assert report.backend_states[SUBJECT_EVENTS] is DataState.BACKEND_UNREACHABLE
    assert set(report.verdicts.values()) == {CauseVerdict.NOT_MEASURED}


def test_a_broken_rule_does_not_lose_the_other_rules():
    def exploding_rule(signals):
        raise RuntimeError("policy bug")

    from mission_runtime.observability.failure_trace import rule_fatal_events

    reader = StubReader(events=EventView(DataState.PRESENT, (fatal("device_death"),)))
    report = FailureTraceService(
        reader, rules=(exploding_rule, rule_fatal_events)
    ).attribute(
        FailureQuery(
            "step-7", WINDOW, fatal_event_causes={"device_death": CauseKind.DEVICE}
        )
    )

    assert report.top_cause is CauseKind.DEVICE


def test_one_dead_axis_does_not_silence_the_others():
    """AI-C-05: 한 소스 결손은 그 축만 비운다."""
    local = InMemoryObservabilityProvider()
    local.record_event("device_death", "fatal", {"device_id": "robot-1"})
    composite = CompositeQueryProvider(
        metrics=HttpMetricQueryProvider(
            MetricQueryEndpoint(base_url=f"http://127.0.0.1:{_closed_port()}", timeout_s=0.3)
        ),
        events=LocalEventQueryProvider(local),
    )

    report = FailureTraceService(composite).attribute(
        FailureQuery(
            "step-7",
            TimeWindow(time.time() - 60.0, time.time() + 60.0),
            metric_specs=(LATENCY,),
            fatal_event_causes={"device_death": CauseKind.DEVICE},
        )
    )

    assert report.backend_states[LATENCY.name] is DataState.BACKEND_UNREACHABLE
    assert report.backend_states[SUBJECT_EVENTS] is DataState.PRESENT
    assert report.top_cause is CauseKind.DEVICE
    assert report.verdict(CauseKind.MODEL) is CauseVerdict.NOT_MEASURED


def test_the_local_event_buffer_answers_on_a_node_with_no_collector():
    """AI-O-02 / AI-B-10: 말단에는 질의 서버가 없다. 로컬 기록이 유일한 길이다."""
    local = InMemoryObservabilityProvider()
    local.simulate_collector_down()
    local.record_event("model_load_failed", "critical", {"model": "detector@3"})

    reader = LocalEventQueryProvider(local)
    assert reader.is_reachable()
    view = reader.event_view(TimeWindow(time.time() - 60.0, time.time() + 60.0))
    assert view.state is DataState.PRESENT
    assert [e.name for e in view.fatal()] == ["model_load_failed"]
    # 그 reader 에는 계측 이력이 없다 — 닿지 못한 것이 아니라 여기에 없는 것이다.
    assert reader.metric_series(LATENCY.name, WINDOW).state is DataState.NOT_SCRAPED


def test_an_event_without_a_timestamp_is_not_dropped_from_the_window():
    """시각을 못 붙인 노드의 급사를 창 밖으로 버리지 않는다 (AI-O-02)."""
    reader = StubReader(
        events=EventView(DataState.PRESENT, (fatal("device_death", at=None),))
    )
    report = FailureTraceService(reader).attribute(
        FailureQuery(
            "step-7", WINDOW, fatal_event_causes={"device_death": CauseKind.DEVICE}
        )
    )
    assert [e.name for e in report.fatal_events] == ["device_death"]


# ── 요건 6: 벤더 API 는 상위에 없다 ──────────────────────────────────────────


def test_every_reader_satisfies_the_query_boundary():
    for reader in (
        StubReader(),
        HttpMetricQueryProvider(),
        CollectorFileExportReader("/nonexistent/output.json"),
        LocalEventQueryProvider(InMemoryObservabilityProvider()),
        CompositeQueryProvider(),
    ):
        assert isinstance(reader, ObservabilityQueryProvider), reader


def test_the_attribution_logic_does_not_reach_for_a_provider():
    """AI-C-04: 상위 판단 코드는 어떤 구현 모듈도 import 하지 않는다."""
    from conftest import package_modules_importing

    source = (Path(__file__).parents[1] / "observability" / "failure_trace.py").read_text(
        encoding="utf-8"
    )
    assert "mission_runtime.providers" not in source
    # 읽기 구현은 아무 패키지 모듈도 import 하지 않는다 — 배포 조립 지점에서만 쓰인다.
    assert package_modules_importing("observability_query") == []
    assert package_modules_importing("urllib") == [
        "providers/observability_query.py",
        "runtime/airgap.py",
    ]


def test_the_module_imports_and_runs_with_no_optional_dependency_installed():
    """어떤 선택 의존성도 없는 노드에서 import 되고 답한다."""
    assert importlib.util.find_spec("mission_runtime.observability.failure_trace") is not None
    report = FailureTraceService(None).attribute(FailureQuery("step-7", TimeWindow(0.0, 1.0)))
    assert report.subject_id == "step-7"


# ── 실제 HTTP 질의 경로 ─────────────────────────────────────────────────────


class _MetricHandler(BaseHTTPRequestHandler):
    """Prometheus 호환 `query_range` 응답만 돌려주는 최소 서버.

    실제 Prometheus 가 이 기계에 떠 있지 않으므로, 적어도 **실제 HTTP 왕복과 실제
    응답 형식 파싱**은 검증한다. 떠 있는 날에는 아래 `needs_prometheus` 쪽이 돈다.
    """

    body = {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {
                    "metric": {"__name__": "inference_latency_ms"},
                    "values": [[1010.0, "20"], [1020.0, "180"], [1030.0, "25"]],
                }
            ],
        },
    }

    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler 규약)
        payload = json.dumps(self.body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.fixture
def metric_server():
    server = HTTPServer(("127.0.0.1", 0), _MetricHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def test_the_http_reader_parses_a_real_range_response_and_keeps_the_worst_point(metric_server):
    """평균이 아니라 **가장 나쁜 표본**을 본다 — 창 안의 한 번이 실패를 만들었다."""
    reader = HttpMetricQueryProvider(MetricQueryEndpoint(base_url=metric_server, timeout_s=2.0))
    assert reader.is_reachable()

    report = FailureTraceService(reader).attribute(
        FailureQuery("step-7", WINDOW, metric_specs=(LATENCY,))
    )

    assert report.backend_states[LATENCY.name] is DataState.PRESENT
    # 평균 75ms 가 아니라 180ms 가 목표(50ms 이하)를 깬 근거로 쓰인다.
    assert report.top_cause is CauseKind.MODEL
    evidence = report.candidate(CauseKind.MODEL).evidence[0]
    assert "180.0" in (evidence.note or "")


class _RefusingHandler(BaseHTTPRequestHandler):
    """질의를 거부하는 서버. 질의 API 가 문법 오류에 내는 답 그대로다."""

    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler 규약)
        payload = json.dumps(
            {"status": "error", "errorType": "bad_data", "error": 'unexpected character: "."'}
        ).encode()
        self.send_response(400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.fixture
def refusing_metric_server():
    server = HTTPServer(("127.0.0.1", 0), _RefusingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def test_a_refused_query_is_not_the_same_as_an_unreachable_backend(refusing_metric_server):
    """거부와 못 닿음은 다른 사실이고 다른 사람을 부른다.

    실물에서 실제로 겪은 경우다 — 점 구분 OTel 이름(`ai.x.y`)을 그대로 물으면 질의
    문법에 걸리고, 그것을 "수집기가 죽었다"로 적으면 사람이 수집기·망을 본다. 둘 다
    미측정이지만 사유가 달라야 하고, 거부는 **닿았다**는 뜻이기도 하다.
    """
    reader = HttpMetricQueryProvider(
        MetricQueryEndpoint(base_url=refusing_metric_server, timeout_s=2.0)
    )

    assert reader.is_reachable() is True  # 답을 했으니 닿은 것이다
    series = reader.metric_series("ai.inference.latency_ms", WINDOW)

    assert series.state is DataState.NOT_SCRAPED
    assert "refused" in (series.note or "")
    # 거부 본문의 사유를 버리지 않는다 — 이름이 틀렸다는 가장 빠른 단서다.
    assert "unexpected character" in (series.note or "")


# ── 실제 스택 (떠 있으면 돌고 없으면 skip) ──────────────────────────────────

COLLECTOR_HOST = "127.0.0.1"
COLLECTOR_GRPC, COLLECTOR_HTTP = 4317, 4318
COLLECTOR_OUTPUT = Path(__file__).parents[1] / "deploy" / "integration" / "artifacts" / "output.json"
PROMETHEUS_URL = "http://127.0.0.1:9090"


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection((COLLECTOR_HOST, port), timeout=0.5):
            return True
    except OSError:
        return False


def _closed_port() -> int:
    """아무도 듣지 않는 포트 하나. 닿지 못하는 백엔드를 실제로 만들기 위한 것."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


needs_collector = pytest.mark.skipif(
    not (_port_open(COLLECTOR_HTTP) and COLLECTOR_OUTPUT.is_file()),
    reason=f"OTel collector(:{COLLECTOR_HTTP}) 와 파일 exporter 출력이 없다",
)
needs_prometheus = pytest.mark.skipif(
    not _port_open(9090), reason="Prometheus(:9090) 가 이 기계에 떠 있지 않다"
)


@needs_collector
def test_a_real_collector_round_trip_feeds_the_attribution():
    """실물 한 바퀴: 실제 collector 가 받아 **자기 형식으로 다시 쓴** 구간을 읽는다.

    우리가 넣은 JSON 을 우리가 읽는 것이 아니다 — collector 의 pipeline 을 통과해
    파일 exporter 가 쓴 줄을 읽으므로, 형식 파싱이 실제 배포에서 성립하는지를 본다.
    """
    import urllib.request

    marker = f"ft-e2e-{int(time.time() * 1000)}"
    started = time.time()
    start_nano = int(started * 1e9)
    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": marker}}
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "mission_runtime.failure_trace"},
                        "spans": [
                            {
                                "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
                                "spanId": "00f067aa0ba902b7",
                                "name": f"{marker}.inference.forward",
                                "kind": 1,
                                "startTimeUnixNano": str(start_nano),
                                "endTimeUnixNano": str(start_nano + 450_000_000),
                                "status": {"code": 2, "message": "deadline exceeded"},
                            }
                        ],
                    }
                ],
            }
        ]
    }
    request = urllib.request.Request(
        f"http://{COLLECTOR_HOST}:{COLLECTOR_HTTP}/v1/traces",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status == 200

    reader = CollectorFileExportReader(COLLECTOR_OUTPUT)
    window = TimeWindow(started - 5.0, time.time() + 30.0)
    deadline = time.time() + 15.0
    while time.time() < deadline:
        view = reader.span_view(window)
        if any(span.name.startswith(marker) for span in view.spans):
            break
        time.sleep(0.25)
    else:
        pytest.fail("collector 가 이 실행의 구간을 파일로 내보내지 않았다")

    report = FailureTraceService(reader).attribute(
        FailureQuery(
            marker,
            TimeWindow(started - 5.0, time.time() + 30.0),
            span_specs=(SpanSpec(f"{marker}.", CauseKind.MODEL, budget_ms=100.0),),
        )
    )

    assert report.backend_states[SUBJECT_SPANS] is DataState.PRESENT
    assert report.top_cause is CauseKind.MODEL
    evidence = report.candidate(CauseKind.MODEL).evidence[0]
    assert evidence.source is EvidenceSource.SPAN
    assert "ms >" in (evidence.note or "")
    # 기술 축만 찼고 업무 축은 비어 있다 — 한쪽이 다른 쪽의 기본값이 아니다.
    assert report.business_chain == ()


@needs_collector
def test_a_real_collector_export_file_carries_individual_fatal_events():
    """실제 파일 exporter 출력에서 치명 사건이 개별로 읽힌다 (AI-O-02, 원칙 #14).

    치명 등급과 일반 등급을 한 번에 넣고 섞이지 않는지 본다. 등급을 섞으면 개별
    장애가 요약에 묻히는데, 이 평면은 애초에 요약하지 않는 평면이다 — 실제 배포에서
    log·trace 는 엣지 Collector 가 중앙으로 원본 그대로 보낸다.

    파일에는 이전 실행들이 남긴 줄도 섞여 있다. 그 섞인 상태 그대로 읽는다.
    """
    import urllib.request

    marker = f"ft-events-{int(time.time() * 1000)}"
    started = time.time()
    start_nano = int(started * 1e9)
    payload = {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": marker}}]
                },
                "scopeLogs": [
                    {
                        "scope": {"name": "mission_runtime.failure_trace"},
                        "logRecords": [
                            {
                                "timeUnixNano": str(start_nano),
                                "severityText": severity,
                                "body": {"stringValue": f"{marker}.{name}"},
                                "attributes": [
                                    {"key": "subject_id", "value": {"stringValue": marker}}
                                ],
                            }
                            for name, severity in (
                                ("device_death", "FATAL"),
                                ("queue_depth_rose", "INFO"),
                            )
                        ],
                    }
                ],
            }
        ]
    }
    request = urllib.request.Request(
        f"http://{COLLECTOR_HOST}:{COLLECTOR_HTTP}/v1/logs",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status == 200

    reader = CollectorFileExportReader(COLLECTOR_OUTPUT)
    window = TimeWindow(started - 5.0, time.time() + 30.0)
    deadline = time.time() + 15.0
    while time.time() < deadline:
        view = reader.event_view(window, subject_id=marker)
        if view.state is DataState.PRESENT and len(view.events) >= 2:
            break
        time.sleep(0.25)
    else:
        pytest.fail("collector 가 이 실행의 사건을 파일로 내보내지 않았다")

    # 치명 하나만 치명으로 올라오고 일반 하나는 섞이지 않는다.
    assert [e.name for e in view.fatal()] == [f"{marker}.device_death"]
    assert all(e.severity in ("critical", "fatal") for e in view.fatal())
    assert all(e.name for e in view.events)  # 이름을 지어내지 않고 들고 온다

    # 같은 창에서 계측 요약을 읽어도 이 사건은 사라지지 않는다 — 다른 평면이다.
    report = FailureTraceService(reader).attribute(
        FailureQuery(
            marker,
            window,
            fatal_event_causes={f"{marker}.device_death": CauseKind.DEVICE},
        )
    )
    assert [e.name for e in report.fatal_events] == [f"{marker}.device_death"]
    assert report.top_cause is CauseKind.DEVICE


@needs_prometheus
def test_a_real_prometheus_endpoint_answers_reachable():
    """닿는 것과 값이 있는 것은 다르다 — 여기서는 닿는 것까지만 본다.

    우리가 낸 계측이 실제로 긁혀 판정까지 가는 한 바퀴는
    `tests/test_real_prometheus_path.py` 가 돈다(이 스택을 함께 쓴다).
    """
    reader = HttpMetricQueryProvider(MetricQueryEndpoint(base_url=PROMETHEUS_URL))
    assert reader.is_reachable()
    # 없는 이름은 "정상"이 아니라 긁힌 표본 없음이다.
    series_result = reader.metric_series(
        "mission_runtime_does_not_exist", TimeWindow(time.time() - 60.0, time.time())
    )
    assert series_result.state is DataState.NOT_SCRAPED
