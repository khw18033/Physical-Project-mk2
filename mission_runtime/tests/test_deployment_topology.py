"""implements: AI-C-06, AI-C-04, AI-B-11, AI-C-16
covers: 현재 배포의 전송 지형과 우리 채널이 **맞물리는지**. 특히 "엣지에서 발행했는데
        중앙에 오지 않는다"를 사이트가 아니라 여기서 발견하게 한다.

implements 추가(2026-11-03): AI-O-01, AI-O-05 — 관측 평면의 전제도 여기서 고정한다.

이 파일이 고정하는 사실.
  1. 브릿지가 넘기는 토픽은 텔레메트리 3채널과 terminal 양방향뿐이다.
  2. 우리 AI 채널은 그 목록에 **없다** — 넘기려면 배포·하드웨어 쪽 변경이 필요하다.
  3. 중앙 접점은 터널·사설 주소여야 한다(원칙 #10).
  4. 관측 평면에도 같은 모양의 벽이 하나 더 있다 — 중앙은 `/federate` 로 `match[]` 가
     고른 것만 당겨 가고 우리 계측은 그 목록에 없다. 치명 사건은 그 벽과 무관하게
     log·trace 로 원본이 중앙까지 간다(원칙 #14).
  5. 계측 이름·라벨·포트·간격·보존은 추측이 아니라 통합 저장소에서 옮겨 적은 값이다.
     그쪽이 바꾸면 **이 시험이 깨져야 한다** — 깨지지 않으면 우리는 옛 전제로 계속
     질의하고 그 질의는 오류 없이 빈다.
"""

from __future__ import annotations

import pytest

from mission_runtime.integration.deployment_topology import (
    AI_METRIC_NAME_PREFIX,
    BRIDGED_TELEMETRY_CHANNELS,
    CENTRAL_METRIC_RETENTION_DAYS,
    COLLECTOR_SCRAPE_INTERVAL_S,
    DEVICE_SCOPED_METRIC_LABELS,
    EDGE_EXTERNAL_LABELS,
    EDGE_METRIC_RETENTION_DAYS,
    ENV_CENTRAL_METRIC_RETENTION,
    ENV_EDGE_BIND,
    ENV_EDGE_LAN_BIND,
    ENV_EDGE_METRIC_RETENTION,
    ENV_EDGE_TUNNEL_BIND,
    FEDERATED_METRIC_NAME_PATTERNS,
    FORBIDDEN_METRIC_LABELS,
    METRIC_EXPIRATION_S,
    METRIC_NAME_PREFIX_BY_PART,
    PORT_CENTRAL_METRIC_QUERY_ADMIN,
    PORT_COLLECTOR_METRIC_EXPORT,
    PORT_COLLECTOR_SELF_METRICS,
    PORT_EDGE_METRIC_QUERY,
    PORT_KAFKA_EDGE_UNUSED,
    PORT_MQTT,
    PORT_OTLP,
    PORT_OTLP_ALT,
    SCRAPE_INTERVAL_S,
    SELF_METRIC_LABELS,
    SERVICE_LABEL_AS_SCRAPED,
    CentralEndpoint,
    TopologyError,
    UNBRIDGED_AI_CHANNELS,
    forbidden_labels_in,
    is_tunnel_or_private,
    metric_reaches_central,
    prometheus_metric_name,
    reaches_central,
    telemetry_topic,
    terminal_topic,
)
from mission_runtime.integration.wire import AI_CHANNELS


def test_the_bridge_forwards_only_three_telemetry_channels():
    """엣지 브릿지 설정과 같아야 한다 — 늘리거나 줄이면 중앙 수신이 달라진다."""
    assert BRIDGED_TELEMETRY_CHANNELS == {"state", "status", "heartbeat"}


@pytest.mark.parametrize("channel", sorted(BRIDGED_TELEMETRY_CHANNELS))
def test_a_bridged_channel_reaches_central(channel):
    assert reaches_central(telemetry_topic("zoneA", "robot", "go1-001", channel))


@pytest.mark.parametrize("direction", [True, False])
def test_command_topics_cross_the_bridge_in_both_directions(direction):
    """명령은 중앙에서 발행되고 결과는 올라간다 — 양쪽이 다 넘어가야 한다(AI-C-20)."""
    assert reaches_central(terminal_topic("go1-001", downlink=direction))


def test_our_ai_channels_do_not_reach_central_today():
    """**이것이 지금의 사실이다.** 통과를 전제로 코드를 쓰면 사이트에서 조용히 비어 있다.

    브릿지 토픽 목록에 추가되는 날 이 시험을 고치고, 그때까지는 중앙 소비자가
    AI 채널을 받지 못한다는 것을 코드가 알고 있어야 한다.
    """
    assert set(UNBRIDGED_AI_CHANNELS) == set(AI_CHANNELS), (
        "AI 채널 목록이 바뀌었다 — 브릿지 통과 여부를 다시 확인하고 이 목록을 맞춰라"
    )
    for channel in UNBRIDGED_AI_CHANNELS:
        assert not reaches_central(telemetry_topic("zoneA", "ai", "edge-a", channel))


def test_a_topic_with_an_empty_part_is_refused():
    """`zoneA//x/state` 는 와일드카드 구독에는 걸리지만 사람이 읽을 수 없다."""
    with pytest.raises(TopologyError):
        telemetry_topic("zoneA", "", "go1-001", "state")


@pytest.mark.parametrize("bad", ["zone/A", "zone+", "zone#"])
def test_wildcards_in_identifiers_are_refused(bad):
    """식별자에 와일드카드가 섞이면 엉뚱한 구독에 걸린다."""
    with pytest.raises(TopologyError):
        telemetry_topic(bad, "robot", "go1-001", "state")


def test_the_edge_kafka_listener_is_recorded_as_unused():
    """1.0 배포에서 엣지는 Kafka 에 붙지 않는다 — 번호만 대조용으로 남긴다."""
    assert (PORT_MQTT, PORT_OTLP) == (1883, 4317)
    assert PORT_KAFKA_EDGE_UNUSED == 9095


@pytest.mark.parametrize("host, expected", [
    ("100.70.1.2", True),       # tailnet(CGNAT) 주소
    ("192.168.1.10", True),     # 사설망
    ("127.0.0.1", True),        # loopback
    ("edge-a.example.ts.net", True),
    ("8.8.8.8", False),         # 공개 인터넷
    ("1.1.1.1", False),         # 공개 인터넷
])
def test_central_endpoints_must_look_like_a_tunnel_or_private_address(host, expected):
    """구역 엣지↔서버는 공개 인터넷을 경유하지 않는다(원칙 #10).

    RFC 5737 문서용 대역(192.0.2.0/24 · 203.0.113.0/24)은 파이썬 표준 라이브러리가
    `is_private` 로 분류하므로 여기서도 통과한다 — 실제로 라우팅되지 않는 주소라
    그 분류가 맞다.

    이름 기반 주소는 판정하지 않는다 — tailnet 이름만 통과시키면 사이트가 쓰는 다른
    내부 DNS 이름을 거짓으로 막는다. 그래서 이 검사는 설정 실수를 잡는 용도이고
    보안 장치가 아니다.
    """
    assert is_tunnel_or_private(host) is expected


def test_a_central_endpoint_needs_a_host():
    with pytest.raises(TopologyError):
        CentralEndpoint("", PORT_MQTT, "업무")


# ── 관측 평면 (2026-11-03 통합 저장소 `main` @ `30f5ee94a` 대조) ──────────────
#
# 아래는 모두 **그쪽 설정 파일에서 옮겨 적은 값**이다. 그쪽이 바꾸면 이 시험이
# 깨져야 한다 — 깨지지 않으면 우리는 옛 전제로 계속 질의하고, 그 질의는 오류 없이
# 빈다. 파일 이름을 각 시험에 적어 두는 이유가 그것이다.


def test_the_metric_query_ports_match_the_real_edge_stack():
    """엣지 Prometheus 9090 · Collector exporter 8889 · Collector 자기 관측 8888.

    `deploy/edge/docker-compose.yml`(prometheus 포트)와
    `deploy/edge/config/{prometheus,otel-collector}.yaml`(타깃·exporter).
    """
    assert PORT_EDGE_METRIC_QUERY == 9090
    assert PORT_COLLECTOR_METRIC_EXPORT == 8889
    assert PORT_COLLECTOR_SELF_METRICS == 8888
    # 중앙 Prometheus 는 운영자용 7861 로 나온다 — 우리가 붙는 자리가 아니다.
    assert PORT_CENTRAL_METRIC_QUERY_ADMIN == 7861


def test_our_default_metric_query_endpoint_points_at_the_edge():
    """실패 분석은 중앙 요약이 아니라 **엣지 상세값**을 본다 (AI-O-01, 원칙 #14).

    기본 엔드포인트가 중앙을 가리키면 요약이 가린 것을 되짚을 수 없다.
    """
    from mission_runtime.providers.observability_query import MetricQueryEndpoint

    endpoint = MetricQueryEndpoint()
    assert endpoint.base_url.endswith(f":{PORT_EDGE_METRIC_QUERY}")
    # 질의 step 이 수집 간격보다 굵으면 표본이 있는데도 건너뛴 점이 생긴다.
    assert endpoint.step_s <= COLLECTOR_SCRAPE_INTERVAL_S


def test_the_collector_keeps_a_series_alive_for_five_minutes_after_the_producer_stops():
    """`metric_expiration: 5m` — 생산자가 멈춰도 시계열은 5분 더 산다.

    이 값을 모르면 "값이 보인다"를 "지금 보내고 있다"로 읽는다. 반대로 5분이 지나면
    시계열은 0 이 되는 것이 아니라 **사라진다** — 그 공백이 NOT_SCRAPED 다.
    """
    assert METRIC_EXPIRATION_S == 300.0
    assert SCRAPE_INTERVAL_S == 15.0
    assert COLLECTOR_SCRAPE_INTERVAL_S == 5.0


def test_metric_retention_is_short_and_is_not_the_archive():
    """계측은 장기 저장소가 아니다 (AI-O-03, 원칙 #17)."""
    assert (EDGE_METRIC_RETENTION_DAYS, CENTRAL_METRIC_RETENTION_DAYS) == (7, 15)


def test_each_part_has_its_own_metric_name_prefix():
    """접두가 겹치면 같은 이름이 다른 뜻으로 섞이고 나중에 가를 수 없다.

    `hw.`·`be.`·`vz.` 는 그쪽 규약에 등재된 값이고, `ai.` 는 우리가 고른 값이다
    (등재 요청은 `docs/integration-handover.md`). 겹치지 않는 것만 여기서 본다.
    """
    prefixes = list(METRIC_NAME_PREFIX_BY_PART.values())
    assert len(set(prefixes)) == len(prefixes)
    assert AI_METRIC_NAME_PREFIX == "ai."
    for other in ("hw.", "be.", "vz."):
        assert not AI_METRIC_NAME_PREFIX.startswith(other)
        assert not other.startswith(AI_METRIC_NAME_PREFIX)


@pytest.mark.parametrize("otel_name, expected", [
    ("ai.failure_trace.probe_latency_ms", "ai_failure_trace_probe_latency_ms"),
    ("hw.publish.count", "hw_publish_count"),
    ("system.cpu.utilization", "system_cpu_utilization"),
])
def test_dotted_otel_names_become_underscored_prometheus_names(otel_name, expected):
    """우리가 `_` 를 직접 넣지 않고 점 구분 이름을 낸다 — 변환은 Collector 가 한다.

    이 변환이 틀리면 질의가 영원히 비는데, 그 공백은 NOT_SCRAPED 로 보여서 "계측이
    없다"처럼 읽힌다. 실물 대조는 `tests/test_real_prometheus_path.py` 가 한다.
    """
    assert prometheus_metric_name(otel_name) == expected


def test_our_metrics_do_not_cross_the_edge_federation_today():
    """**업무 평면의 브릿지 벽과 똑같은 벽이 관측 평면에도 있다.**

    중앙은 `/federate` 로 `match[]` 가 고른 것만 당겨 간다
    (`deploy/server/config/prometheus.yml:68-71`). 지금 그 목록은 `hw_.*` 와
    `system_cpu_.*|system_memory_.*` 뿐이라 우리 계측은 중앙 Prometheus 에 없다.
    목록이 넓어지는 날 이 시험을 고친다 — 그때까지 중앙 화면이 AI 계측을 읽는다고
    가정한 코드를 두지 않는다.
    """
    assert FEDERATED_METRIC_NAME_PATTERNS == (
        r"hw_.*",
        r"system_cpu_.*|system_memory_.*",
    )
    assert metric_reaches_central("hw_publish_count_total") is True
    assert metric_reaches_central("system_cpu_utilization_ratio") is True
    assert metric_reaches_central("system_memory_usage_bytes") is True
    for name in ("ai_failure_trace_probe_latency_ms", "ai_selector_overhead_ms"):
        assert metric_reaches_central(name) is False
    # 부분 일치로 통과시키지 않는다 — `x_hw_y` 는 `hw_.*` 가 아니다.
    assert metric_reaches_central("x_hw_publish_count") is False


def test_the_fatal_event_path_is_not_the_federation_path():
    """요약 벽 뒤에서도 개별 치명 사건은 가려지지 않는다 (원칙 #14, AI-O-02).

    계측은 엣지에 남지만 log·trace 는 엣지 Collector 가 **원본 그대로** 중앙으로
    보낸다(`deploy/edge/config/otel-collector.yaml` 의 traces·logs pipeline). 두
    사실이 같은 자리에 적혀 있어야 "중앙에 AI 지표가 없으니 요약을 넓히자"는 잘못된
    해법이 나오지 않는다 — 치명 사건은 애초에 계측 평면의 것이 아니다.
    """
    from mission_runtime.observability.failure_trace import DataState
    from mission_runtime.providers.observability_query import (
        HttpMetricQueryProvider,
        MetricQueryEndpoint,
    )
    from mission_runtime.observability.failure_trace import TimeWindow

    reader = HttpMetricQueryProvider(MetricQueryEndpoint(base_url="http://127.0.0.1:1"))
    # 계측 reader 는 닿든 못 닿든 사건 축에서 "여기에 없다"고 답한다.
    assert reader.event_view(TimeWindow(0.0, 1.0)).state is DataState.NOT_SCRAPED


def test_labels_the_deployment_refuses_cannot_be_selected():
    """쓰는 쪽이 거부한 라벨로는 고를 수 없다 — 그 시계열은 생기지 않는다.

    `server/contracts/common/README.md:215-222` 의 금지 라벨 전수. 명령·임무·프레임
    식별자와 시각이 전부 여기 있고, 그래서 명령 하나를 되짚는 일은 계측이 아니라
    업무 축(command_id)과 구간(trace)의 몫이다(AI-B-03).
    """
    assert {"command_id", "mission_id", "frame_ref", "sequence_id"} <= FORBIDDEN_METRIC_LABELS
    assert {"sent_at", "received_at", "emitted_at"} <= FORBIDDEN_METRIC_LABELS
    assert forbidden_labels_in({"component": "x"}) == ()
    assert forbidden_labels_in({"component": "x", "command_id": "c", "ts": "1"}) == (
        "command_id",
        "ts",
    )
    assert forbidden_labels_in(None) == ()
    # 허용 라벨과 금지 라벨이 겹치지 않는다 — 겹치면 규약이 자기 모순이다.
    assert not (SELF_METRIC_LABELS | DEVICE_SCOPED_METRIC_LABELS) & FORBIDDEN_METRIC_LABELS
    # `zone_id` 는 장치별 지표에만 — 자기 관측에 붙이면 구역 수만큼 시계열이 곱해진다.
    assert "zone_id" in DEVICE_SCOPED_METRIC_LABELS
    assert "zone_id" not in SELF_METRIC_LABELS


def test_the_service_name_does_not_arrive_as_the_job_label():
    """`service.name` 은 `exported_job` 으로 들어온다 — `job` 은 수집 잡 이름이다.

    백엔드 통지(`server/docs/be/vz-observability-namespace.md` §3)가 적은 함정이다.
    컴포넌트를 가르려면 `component` 라벨을 직접 붙인다.
    """
    assert SERVICE_LABEL_AS_SCRAPED == "exported_job"
    assert "component" in SELF_METRIC_LABELS


def test_external_labels_are_not_visible_on_a_direct_edge_query():
    """`agg_layer=edge` 는 `/federate` 에만 실린다 (2026-11-03 실측).

    엣지 엔드포인트에 `agg_layer` 선택자를 걸면 표본 0 이다. 중앙에서 쓰던 질의를
    그대로 엣지로 가져오면 조용히 빈다 — 그 사실을 적어 둔다.
    """
    assert EDGE_EXTERNAL_LABELS == {"agg_layer": "edge"}
    assert "agg_layer" not in SELF_METRIC_LABELS | DEVICE_SCOPED_METRIC_LABELS


def test_the_two_edge_bind_variables_are_different_machines():
    """이름이 비슷하고 가리키는 기계가 다르다 — 사이트가 반대로 적기 쉬운 자리.

    `MK2_EDGE_BIND` 는 중앙 서버가 엣지에게 여는 입구(중앙 `deploy/.env:21`),
    `MK2_EDGE_LAN_BIND` 는 엣지에서 말단이 붙는 입구(`deploy/edge/.env.example:14`).
    """
    assert ENV_EDGE_BIND != ENV_EDGE_LAN_BIND
    assert (ENV_EDGE_BIND, ENV_EDGE_LAN_BIND) == ("MK2_EDGE_BIND", "MK2_EDGE_LAN_BIND")
    assert ENV_EDGE_TUNNEL_BIND == "MK2_EDGE_TUNNEL_BIND"
    assert (ENV_EDGE_METRIC_RETENTION, ENV_CENTRAL_METRIC_RETENTION) == (
        "MK2_EDGE_PROMETHEUS_RETENTION",
        "MK2_PROMETHEUS_RETENTION",
    )


def test_the_central_collector_answers_on_two_otlp_ports():
    """4316 과 4317 은 같은 수신단이다 (통합 저장소 `docs/PORTS.md:12`).

    우리는 표준 번호를 쓴다. 다른 쪽 설정이 4316 으로 적혀 있어도 틀린 것이 아니라는
    사실을 적어 두지 않으면 "포트가 다르다"로 보고된다.
    """
    assert (PORT_OTLP, PORT_OTLP_ALT) == (4317, 4316)
