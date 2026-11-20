"""implements: AI-O-01, AI-O-05, AI-C-06, AI-C-04
관련: AI-O-02 (치명 사건은 개별로 남는다), AI-O-03, AI-B-10 (말단에는 질의 서버가 없다)
covers: 실물 한 바퀴 — 우리가 OTLP 로 낸 계측이 Collector 의 exporter 를 거쳐 실제
        Prometheus 에 긁히고, `HttpMetricQueryProvider` 가 되짚어 와 귀속 판정에
        이른다 · 아무도 내지 않는 이름은 "정상"이 아니라 미측정이다 · 계측 백엔드가
        살아 있어도 치명 사건을 계측에서 읽지 않는다 · 계측 질의가 죽어도 다른 축은
        답한다 · 금지 라벨 선택자는 조용히 비지 않고 사유를 들고 온다

왜 따로 떠 있는 Prometheus 가 필요한가 — `tests/test_failure_trace.py` 의 손으로 만든
HTTP 서버는 **우리가 짠 응답을 우리가 파싱**한다. 실제 배포에서 깨지는 것은 그 사이에
있는 것들이다: 점 구분 OTel 이름이 Prometheus 표기로 바뀌는 방식, `service.name` 이
`job` 이 아니라 `exported_job` 으로 들어오는 것, `external_labels` 가 직접 질의에는
보이지 않는 것, 묶어 보내는 지연. 그 셋을 실물로만 확인할 수 있다.

스택이 없으면 이 묶음만 skip 한다(`tests/test_real_stack.py` 의 방식) — 선택 구성요소
결손은 축소이지 실패가 아니다(AI-C-05).

    cd mission_runtime && docker compose -f deploy/integration/docker-compose.yml up -d
"""

from __future__ import annotations

import json
import os
import re
import socket
import time
import urllib.request

import pytest

from mission_runtime.integration.deployment_topology import (
    AI_METRIC_NAME_PREFIX,
    COLLECTOR_SCRAPE_INTERVAL_S,
    PORT_EDGE_METRIC_QUERY,
    SERVICE_LABEL_AS_SCRAPED,
    metric_reaches_central,
    prometheus_metric_name,
)
from mission_runtime.observability.failure_trace import (
    SUBJECT_EVENTS,
    SUBJECT_SPANS,
    CauseKind,
    CauseVerdict,
    DataState,
    EvidenceSource,
    FailureQuery,
    FailureTraceService,
    MetricSpec,
    TimeWindow,
)
from mission_runtime.observability.layered_metrics import (
    Direction,
    MeetState,
    TargetBaseline,
)
from mission_runtime.providers.observability_query import (
    CompositeQueryProvider,
    HttpMetricQueryProvider,
    MetricQueryEndpoint,
)

HOST = "127.0.0.1"
COLLECTOR_OTLP_HTTP = 4318
PROMETHEUS_URL = f"http://{HOST}:{PORT_EDGE_METRIC_QUERY}"

#: 이 시험이 내는 계측. 점 구분 OTel 이름으로 내고 Prometheus 표기는 Collector 가
#: 만든다 — 우리가 `_` 를 직접 넣지 않는다(파트 접두 규약).
OTEL_METRIC_NAME = f"{AI_METRIC_NAME_PREFIX}failure_trace.probe_latency_ms"
PROM_METRIC_NAME = prometheus_metric_name(OTEL_METRIC_NAME)
#: 허용 라벨. 컴포넌트를 가르는 축은 `service.name` 이 아니라 이것이다.
COMPONENT = "failure_trace"
#: 이 프로세스를 가리키는 라벨. **같은 기계에서 이 묶음이 둘 이상 돌 때** 서로의
#: 시계열을 덮지 않게 하는 축이다(아래 `scraped_gauge` 의 설명).
#:
#: pid 를 쓰는 이유: 실행마다 새 값(타임스탬프·uuid)을 쓰면 시계열이 실행 수만큼
#: 늘어나지만 pid 는 OS 가 재사용하므로 늘어나지 않는다 — 개발 스택의 시계열 증식을
#: 막으려던 원래 의도를 그대로 지킨다. 어떤 선택자도 이 라벨을 고르지 않으므로
#: `{"component": COMPONENT}` 질의는 전처럼 이 묶음의 점을 전부 본다.
WRITER = str(os.getpid())
SERVICE_NAME, SERVICE_NAMESPACE = "ai-failure-trace-probe", "mk2"

LATENCY_BUDGET = TargetBaseline(50.0, Direction.AT_MOST, "ms")


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection((HOST, port), timeout=0.5):
            return True
    except OSError:
        return False


def _closed_port() -> int:
    """아무도 듣지 않는 포트 하나 — 닿지 못하는 백엔드를 실제로 만들기 위한 것."""
    with socket.socket() as probe:
        probe.bind((HOST, 0))
        return probe.getsockname()[1]


needs_stack = pytest.mark.skipif(
    not (_port_open(PORT_EDGE_METRIC_QUERY) and _port_open(COLLECTOR_OTLP_HTTP)),
    reason=(
        f"실물 계측 스택(Prometheus :{PORT_EDGE_METRIC_QUERY} · "
        f"Collector OTLP/HTTP :{COLLECTOR_OTLP_HTTP})이 이 기계에 떠 있지 않다"
    ),
)


def _publish_gauge(value: float) -> None:
    """OTLP/HTTP 로 gauge 한 점. SDK 를 들이지 않는다 — 와이어 형식만 쓴다.

    `providers/otel.py` 가 `opentelemetry` import 를 독점하는 경계 시험이 있으므로
    시험 쪽에서 SDK 를 끌어오지 않는다.
    """
    payload = {
        "resourceMetrics": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": SERVICE_NAME}},
                        {
                            "key": "service.namespace",
                            "value": {"stringValue": SERVICE_NAMESPACE},
                        },
                    ]
                },
                "scopeMetrics": [
                    {
                        "scope": {"name": "mission_runtime.failure_trace"},
                        "metrics": [
                            {
                                "name": OTEL_METRIC_NAME,
                                # 단위를 비워 둔다 — `unit` 을 주면 Collector 가
                                # `_milliseconds` 접미사를 더 붙여 이름이 달라진다.
                                "gauge": {
                                    "dataPoints": [
                                        {
                                            "asDouble": value,
                                            "timeUnixNano": str(int(time.time() * 1e9)),
                                            "attributes": [
                                                {
                                                    "key": "component",
                                                    "value": {"stringValue": COMPONENT},
                                                },
                                                {
                                                    "key": "writer",
                                                    "value": {"stringValue": WRITER},
                                                },
                                            ],
                                        }
                                    ]
                                },
                            }
                        ],
                    }
                ],
            }
        ]
    }
    request = urllib.request.Request(
        f"http://{HOST}:{COLLECTOR_OTLP_HTTP}/v1/metrics",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status == 200


@pytest.fixture(scope="module")
def scraped_gauge():
    """우리가 낸 값 하나가 실제로 긁힐 때까지 기다린다.

    2026-11-04: 전에는 **값만으로** 이 실행을 가렸고 라벨은 전부 같았다. 그러면
    같은 기계에서 이 묶음이 둘 이상 돌 때 두 프로세스가 **같은 시계열 하나**에
    쓴다. Prometheus 는 긁을 때마다 그 시계열의 **마지막 값 하나**만 담으므로,
    늦게 쓴 쪽이 이른 쪽의 값을 매 긁기마다 덮고 — 덮인 쪽은 자기 값을 60 초 동안
    한 번도 못 보고 아래 `pytest.fail` 에 닿는다. fixture 안의 실패는 **setup
    ERROR** 라서, 이 fixture 를 받는 시험 여섯이 한꺼번에 error 가 된다(실측:
    프로세스 셋을 동시에 돌리면 `8 passed` 하나와 `2 passed, 6 errors` 둘).
    혼자 돌리면 늘 통과하므로 그 의존은 눈에 보이지 않는다.

    그래서 `writer` 라벨로 **프로세스마다 다른 시계열**을 쓴다. 값 확인은 그대로
    남는다 — 내 시계열 안에서 내 점을 가리는 일은 여전히 값이 한다. 시계열 증식을
    막으려던 원래 의도는 pid 가 재사용되는 값이라 유지된다(`WRITER` 설명).

    기다리는 구간이 긴 것은 실제 배포 그대로다 — Collector 가 5초 묶음으로 보내고
    Prometheus 가 5초마다 긁는다. 그 지연을 없애면 사이트에서 처음 만난다.
    """
    nonce = int(time.time() * 1000) % 1000
    value = 150.0 + nonce / 1000.0  # 50ms 예산을 확실히 깨는 값
    started = time.time()
    reader = HttpMetricQueryProvider(
        MetricQueryEndpoint(base_url=PROMETHEUS_URL, timeout_s=3.0)
    )
    _publish_gauge(value)

    deadline = time.time() + 60.0
    while time.time() < deadline:
        series = reader.metric_series(
            PROM_METRIC_NAME,
            TimeWindow(started - 1.0, time.time() + 1.0),
            {"component": COMPONENT},
        )
        if series.state is DataState.PRESENT and any(
            abs(sample.value - value) < 1e-6 for sample in series.samples
        ):
            return reader, started, value
        time.sleep(COLLECTOR_SCRAPE_INTERVAL_S / 2.0)
    pytest.fail(
        f"우리가 낸 {PROM_METRIC_NAME}={value} 가 60초 안에 긁히지 않았다 — "
        "Collector 의 prometheus exporter(:8889)와 Prometheus 수집 잡을 확인하라"
    )


@needs_stack
def test_a_real_metric_round_trip_reaches_a_verdict(scraped_gauge):
    """실물 한 바퀴가 귀속 판정까지 간다.

    이 시험이 고정하는 것은 "Prometheus 가 답한다"가 아니라 **우리가 낸 계측이
    우리 판정의 근거로 돌아온다**는 것이다. 중간의 이름 변환·라벨 변환이 어긋나면
    여기서 깨진다.
    """
    reader, started, value = scraped_gauge
    window = TimeWindow(started - 1.0, time.time() + 1.0)

    report = FailureTraceService(reader).attribute(
        FailureQuery(
            "step-real-prometheus",
            window,
            metric_specs=(
                MetricSpec(
                    PROM_METRIC_NAME,
                    CauseKind.MODEL,
                    LATENCY_BUDGET,
                    selector=(("component", COMPONENT),),
                ),
            ),
        )
    )

    assert report.backend_states[PROM_METRIC_NAME] is DataState.PRESENT
    assert report.top_cause is CauseKind.MODEL
    assert report.verdicts[CauseKind.MODEL] is CauseVerdict.SUSPECT
    # 가장 나쁜 표본이 근거로 쓰인다 — 평균이 아니다.
    #
    # 그 표본이 **이번 실행이 낸 값이라고 단정하지 않는다.** exporter 의
    # `metric_expiration` 이 5분이므로 앞선 실행이 마지막으로 낸 값이 그 동안 계속
    # 긁힌다 — 생산자가 멈춘 뒤에도 시계열은 5분 더 산다. 이번 값이 실제로 긁혔다는
    # 것은 fixture 가 값으로 확인했고, 여기서 보는 것은 "창 안의 최악값이 예산을
    # 깨고 근거가 됐다"다.
    evidence = report.candidate(CauseKind.MODEL).evidence[0]
    assert evidence.source is EvidenceSource.METRIC
    note = evidence.note or ""
    assert "vs target AT_MOST 50.0" in note
    worst = float(re.search(r"worst ([0-9.]+)", note).group(1))
    assert worst >= min(value, 150.0) > 50.0
    # 계측 축만 찼다. 업무 축은 비어 있고 한쪽이 다른 쪽의 기본값이 아니다(AI-B-03).
    assert report.business_chain == ()


@needs_stack
def test_the_collector_renames_our_metric_exactly_the_way_we_recorded(scraped_gauge):
    """점 구분 이름 → Prometheus 표기. 우리가 적어 둔 변환이 실물과 같은지.

    `prometheus_metric_name()` 이 틀리면 질의가 영원히 비는데, 그 공백은
    NOT_SCRAPED 로 보여서 "계측이 없다"처럼 읽힌다 — 이름이 틀렸다고는 아무도
    말해 주지 않는다. 그래서 실물로 못 박는다.
    """
    reader, started, _ = scraped_gauge
    window = TimeWindow(started - 1.0, time.time() + 1.0)

    assert PROM_METRIC_NAME == "ai_failure_trace_probe_latency_ms"
    assert reader.metric_series(PROM_METRIC_NAME, window).state is DataState.PRESENT
    # 점이 그대로 남은 이름은 존재하지 않는다 — Collector 가 바꾼다.
    assert reader.metric_series(OTEL_METRIC_NAME, window).state is DataState.NOT_SCRAPED


@needs_stack
def test_service_name_is_not_the_job_label(scraped_gauge):
    """`service.name` 으로는 고를 수 없다 — `exported_job` 으로 들어온다.

    백엔드 통지(`server/docs/be/vz-observability-namespace.md` §3)가 적은 함정이고,
    실물에서 그대로 확인된다. 컴포넌트를 가르는 축은 `component` 라벨이다.
    """
    reader, started, _ = scraped_gauge
    window = TimeWindow(started - 1.0, time.time() + 1.0)
    service = f"{SERVICE_NAMESPACE}/{SERVICE_NAME}"

    assert SERVICE_LABEL_AS_SCRAPED == "exported_job"
    assert reader.metric_series(PROM_METRIC_NAME, window, {"job": service}).state is (
        DataState.NOT_SCRAPED
    )
    assert reader.metric_series(
        PROM_METRIC_NAME, window, {SERVICE_LABEL_AS_SCRAPED: service}
    ).state is DataState.PRESENT


@needs_stack
def test_our_metric_does_not_reach_central_today(scraped_gauge):
    """엣지에 있다는 것이 중앙에 있다는 뜻은 아니다.

    중앙은 `/federate` 로 `match[]` 가 고른 것만 당겨 간다. 우리 이름은 그 목록에
    없다 — 업무 평면의 브릿지 토픽 목록과 똑같은 모양의 벽이다. 엣지에서 PRESENT 인
    것을 중앙 화면이 읽는다고 가정한 코드를 두지 않기 위해 같은 시험에서 못 박는다.
    """
    reader, started, _ = scraped_gauge
    window = TimeWindow(started - 1.0, time.time() + 1.0)

    assert reader.metric_series(PROM_METRIC_NAME, window).state is DataState.PRESENT
    assert metric_reaches_central(PROM_METRIC_NAME) is False


@needs_stack
def test_a_name_nobody_exports_is_not_measured_rather_than_healthy():
    """**떠 있는 Prometheus 가 공백을 정상으로 바꾸지 않는다.**

    닿는 백엔드가 있으면 "조회가 성공했다"와 "지표가 정상이다"를 섞기 쉽다. 아무도
    내지 않는 이름을 물었을 때 MET 이 나오면 관측 공백이 무죄 증명으로 둔갑한다
    (AI-O-05 의 미측정은 미달이 아니고 0 도 아니다).
    """
    reader = HttpMetricQueryProvider(MetricQueryEndpoint(base_url=PROMETHEUS_URL))
    assert reader.is_reachable()  # 백엔드는 살아 있다
    window = TimeWindow(time.time() - 60.0, time.time())
    absent = f"{prometheus_metric_name(AI_METRIC_NAME_PREFIX)}nobody_exports_this"

    series = reader.metric_series(absent, window)
    assert series.state is DataState.NOT_SCRAPED
    assert series.samples == ()

    report = FailureTraceService(reader).attribute(
        FailureQuery(
            "step-absent",
            window,
            metric_specs=(MetricSpec(absent, CauseKind.MODEL, LATENCY_BUDGET),),
        )
    )
    # 두 미측정 사유(NOT_SCRAPED · BACKEND_UNREACHABLE)는 목표 판정에서 하나로
    # 접히지만, 접히는 쪽은 MeetState.NOT_MEASURED 이고 MET 도 UNMET 도 아니다.
    assert report.backend_states[absent] is DataState.NOT_SCRAPED
    assert report.verdicts[CauseKind.MODEL] is CauseVerdict.NOT_MEASURED
    gap = next(g for g in report.not_measured if g.subject == absent)
    assert gap.state is DataState.NOT_SCRAPED
    assert report.candidates == ()  # 공백은 혐의가 아니다


@needs_stack
def test_a_live_metric_backend_never_supplies_fatal_events():
    """계측 백엔드가 살아 있다고 치명 사건을 집계에서 읽어 오지 않는다 (원칙 #14).

    "Prometheus 가 떴으니 사건도 거기서 읽자"가 정확히 금지된 일이다 — 장치 생사와
    치명 오류는 집계하면 안 되는 개별 상태이고 log·trace 경로로 간다. 그래서 이
    reader 는 닿아 있어도 사건·구간 축에서 **없다**고 답해야 하고, 보고서의 빈
    치명 사건 목록은 "치명 사건이 없다"가 아니라 공백으로 기록되어야 한다.
    """
    reader = HttpMetricQueryProvider(MetricQueryEndpoint(base_url=PROMETHEUS_URL))
    window = TimeWindow(time.time() - 60.0, time.time())
    assert reader.is_reachable()

    assert reader.event_view(window).state is DataState.NOT_SCRAPED
    assert reader.span_view(window).state is DataState.NOT_SCRAPED

    report = FailureTraceService(reader).attribute(FailureQuery("step-events", window))
    assert report.fatal_events == ()
    assert report.backend_states[SUBJECT_EVENTS] is DataState.NOT_SCRAPED
    assert report.backend_states[SUBJECT_SPANS] is DataState.NOT_SCRAPED
    assert {gap.subject for gap in report.not_measured} >= {SUBJECT_EVENTS, SUBJECT_SPANS}


@needs_stack
def test_a_forbidden_label_selector_says_why_it_is_empty(scraped_gauge):
    """금지 라벨로 고르면 조용히 비지 않고 사유가 남는다.

    `command_id` 같은 이름은 쓰는 쪽에서 거부되므로 그 라벨이 붙은 시계열은 생기지
    않는다. 질의를 보내도 결과는 같지만 "왜 비었는가"가 사라지고, 사람은 그 공백을
    백엔드 쪽에서 찾는다. 같은 이름·같은 창에서 허용 라벨은 PRESENT 가 나오므로
    비어 있는 쪽이 백엔드 탓이 아님을 이 시험이 가른다.
    """
    reader, started, _ = scraped_gauge
    window = TimeWindow(started - 1.0, time.time() + 1.0)

    allowed = reader.metric_series(PROM_METRIC_NAME, window, {"component": COMPONENT})
    refused = reader.metric_series(
        PROM_METRIC_NAME, window, {"component": COMPONENT, "command_id": "cmd-1"}
    )

    assert allowed.state is DataState.PRESENT
    assert refused.state is DataState.NOT_SCRAPED
    assert "command_id" in (refused.note or "")
    assert refused.meet_state is MeetState.NOT_MEASURED


@needs_stack
def test_losing_the_metric_query_degrades_only_the_metric_axis(scraped_gauge):
    """계측 질의가 죽어도 관측 대상은 죽지 않고, 다른 축도 죽지 않는다 (AI-O-01).

    Prometheus 를 실제로 내려 보는 대신 **닿지 않는 주소**를 같은 reader 에 꽂는다
    — 코드 경로는 같고 결과만 BACKEND_UNREACHABLE 이다. 같은 창에서 실물 reader 는
    PRESENT 를 내므로, 두 상태가 같은 구현에서 갈라진다는 것까지 보인다.
    """
    live, started, _ = scraped_gauge
    window = TimeWindow(started - 1.0, time.time() + 1.0)
    dead = HttpMetricQueryProvider(
        MetricQueryEndpoint(base_url=f"http://{HOST}:{_closed_port()}", timeout_s=0.3)
    )

    assert dead.is_reachable() is False
    assert dead.metric_series(PROM_METRIC_NAME, window).state is (
        DataState.BACKEND_UNREACHABLE
    )

    spec = MetricSpec(
        PROM_METRIC_NAME, CauseKind.MODEL, LATENCY_BUDGET, selector=(("component", COMPONENT),)
    )
    # 한 축이 죽어도 예외가 아니라 보고서가 나온다. 그것이 격리의 모양이다.
    degraded = FailureTraceService(dead).attribute(
        FailureQuery("step-degraded", window, metric_specs=(spec,))
    )
    assert degraded.backend_states[PROM_METRIC_NAME] is DataState.BACKEND_UNREACHABLE
    assert degraded.verdicts[CauseKind.MODEL] is CauseVerdict.NOT_MEASURED

    # 축마다 reader 를 달리 꽂으면, 한 축의 결손이 산 축을 가리지 않는다. 구간·사건
    # reader 를 아예 꽂지 않은 노드가 현재 배포의 흔한 모양이다 — 계측은 엣지
    # Prometheus 가, log·trace 는 Collector 가 들고 있고 둘은 따로 죽는다.
    composite = CompositeQueryProvider(metrics=live)
    report = FailureTraceService(composite).attribute(
        FailureQuery("step-mixed", window, metric_specs=(spec,))
    )
    assert report.backend_states[PROM_METRIC_NAME] is DataState.PRESENT
    assert report.backend_states[SUBJECT_SPANS] is DataState.BACKEND_UNREACHABLE
    assert report.top_cause is CauseKind.MODEL
