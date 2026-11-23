"""관측 파이프라인 회귀 — 발행 → 백엔드(A층·C층) → Collector → Prometheus / Loki / Tempo 도달.

"떠 있다"가 아니라 **"흐른다"**를 본다(지시서 9-C). 각 확인은 **발행 전 값 → 발행 → 값이 실제로
늘었다/나타났다**의 차분이다. counter 는 재기동마다 0으로 리셋되고 Collector exporter 가 옛 값을 5분간
더 내보내므로, 차분은 `obs_query.counter_delta()`(리셋이면 `after` 자체가 증가분 — `rate()`와 같은 규칙)로
잰다. 절대값을 그대로 비교하면 재기동 직후 헛되이 실패한다(2026-09-16 실측).

전제: 서버에서 실행. ingest·저장 소비자·WS echo(systemd)와 Collector·Prometheus·Loki·Tempo 가
떠 있어야 한다. 관측 저장소가 없으면 `conftest.py`의 fixture 가 **이 파일만 skip** 한다.
새 의존성 없음 — 조회는 표준 `urllib`, 가짜 span 은 서버 venv 의 OTel SDK(없으면 그 테스트만 skip).

| 판정 | 무엇 |
|---|---|
| 16 · 17 | A층 지표가 Prometheus 에 도달하고 라벨에 `source_id` 가 없다 |
| 18 ★음성 | 본문 불합격 발행 후 `be_ingest_rejected_total{stage="payload"}` 가 실제로 는다 |
| 19 | `be_pipeline_lag_seconds_count` 가 발행 건수만큼 는다 (값의 출처는 `telemetry.lag_s`) |
| 23 · 24 · 25 ★음성 | C층 `be_telemetry_water_level_m{source_id=…}` 가 나타나고, `{value:null,state}` 발행분은 시계열이 **없다** |
| 16(게이트웨이) | WS 클라이언트가 붙어 있는 동안 `be_gateway_clients` ≥ 1, push 가 는다 |
| 20 | Loki `{service_name="be-ingest"}` 에 방금 발행한 `source_id` 가 든 로그가 있다 |
| 21 | 가짜 span 1건이 서버 Collector 를 거쳐 Tempo 에 꽂히고 `service.name` 태그값에 나타난다 |
| 33 ★음성 | 중앙 직접 수집분(`be_*`)에는 `agg_layer` 라벨이 없다 |

⚠ 대기 시간이 길다 — export 15s + scrape 5s 라 항목당 최대 45초(`MK2_OBSERVE_TIMEOUT`)를 기다린다.
테스트 행(`wl-obs-*`)은 TSDB 에 남는다(`mk2_app` 에 DELETE 권한이 없다 — 의도).

implements: BE-S-02 (관측 파이프라인 3종 · A층 · C층), BE-S-07 (lag 측정 수단)
tests: 위 표 — 양성 6 + 음성 3
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.parse
import uuid
from typing import Any, Dict, List

import pytest

import publisher
from obs_query import counter_delta, http_get_json, prom_query, prom_scalar, wait_until

from backend import settings

A_LAYER_DEVICE_LABELS = {"source_id", "zone_id", "entity_type", "session_id", "sequence_id", "internal_seq"}


def _unique(prefix: str = "wl-obs") -> str:
    return "{}-{}".format(prefix, uuid.uuid4().hex[:8])


def _publish_state(broker, source_id: str, count: int = 1, **kw: Any) -> None:
    for i in range(count):
        payload = publisher.make_message("state", "sensor", source_id=source_id, sequence_id=i + 1, **kw)
        publisher.publish(publisher.topic_for("state", eid=source_id), payload, host=broker["host"], port=broker["port"])


# ── 16 · 17 · 19 — A층 counter·histogram 이 실제로 는다, 라벨에 source_id 없음 ─────


A_LAYER_EXPRS = {
    "received": 'sum(be_ingest_received_total{channel="state"})',
    # ⚠ produce 의 전달 콜백은 poll() 에서만 처리된다 — 브릿지가 1초 주기 poll 스레드를 두어야 조용한
    #   파이프라인에서도 마지막 건이 세진다(2026-09-16 실측: 그 스레드가 없을 때 received 28 / produce 27 로 1건 지연).
    "produce": 'sum(be_kafka_produce_total{channel="state",outcome="ok"})',
    "consumed": 'sum(be_storage_consumed_total{channel="state"})',
    "write": 'sum(be_storage_write_total{channel="state",outcome="ok"})',
    "lag": 'sum(be_pipeline_lag_seconds_count{channel="state"})',
}


def _deltas(prometheus_url: str, before: Dict[str, float]) -> Dict[str, float]:
    return {key: counter_delta(before[key], prom_scalar(prometheus_url, expr)) for key, expr in A_LAYER_EXPRS.items()}


def test_a_layer_metrics_increase_after_publish(prometheus_url, broker, observe_timeout_s) -> None:
    before = {key: prom_scalar(prometheus_url, expr) for key, expr in A_LAYER_EXPRS.items()}
    _publish_state(broker, _unique(), count=2)

    ok = wait_until(lambda: all(d >= 2 for d in _deltas(prometheus_url, before).values()), observe_timeout_s)
    deltas = _deltas(prometheus_url, before)
    short = {key: (before[key], deltas[key]) for key in A_LAYER_EXPRS if deltas[key] < 2}
    assert ok, "A층 지표가 발행 2건만큼 늘지 않았다 — 모자란 것(before, 증가분): {}".format(short)

    # 17 — A층 라벨 집합에 장치 식별·금지 라벨이 없다 (지표 하나가 아니라 A층 전부).
    for name in ["be_ingest_received_total", "be_storage_consumed_total", "be_pipeline_lag_seconds_count",
                 "be_kafka_produce_total", "be_storage_write_total", "be_registry_observe_total"]:
        for series in prom_query(prometheus_url, name):
            leaked = A_LAYER_DEVICE_LABELS.intersection(series["metric"])
            assert not leaked, "{} 에 A층 금지 라벨이 붙었다: {}".format(name, leaked)
            assert series["metric"].get("component") in ("ingest", "storage", "gateway")


# ── 18 ★음성 — 본문 불합격이 rejected{stage=payload} 로 실제로 세진다 ────────


def test_rejected_payload_counter_increases(prometheus_url, broker, observe_timeout_s) -> None:
    expr = 'sum(be_ingest_rejected_total{stage="payload"})'
    before = prom_scalar(prometheus_url, expr)
    kind = "payload-missing-device-status"
    source_id = _unique("wl-obs-bad")
    payload = publisher.load_invalid(kind, source_id=source_id)
    publisher.publish(
        publisher.topic_for("state", etype=publisher.INVALID_ETYPE[kind], eid=source_id),
        payload, host=broker["host"], port=broker["port"],
    )
    ok = wait_until(lambda: counter_delta(before, prom_scalar(prometheus_url, expr)) >= 1, observe_timeout_s)
    assert ok, "본문 불합격 1건이 be_ingest_rejected_total{{stage=\"payload\"}} 에 잡히지 않았다 (before={}, after={})".format(
        before, prom_scalar(prometheus_url, expr)
    )


# ── 23 · 24 · 25 — C층 gauge 가 나타나고, 값이 없는 발행은 시계열을 만들지 않는다 ─


def test_c_layer_gauge_appears_and_null_makes_no_series(prometheus_url, broker, observe_timeout_s) -> None:
    ok_id = _unique("wl-obs-c")
    null_id = _unique("wl-obs-null")
    _publish_state(broker, ok_id, water_level_m=2.53)
    _publish_state(broker, null_id, water_level_m={"value": None, "state": "unavailable"})

    ok_expr = 'be_telemetry_water_level_m{{source_id="{}"}}'.format(ok_id)
    assert wait_until(lambda: bool(prom_query(prometheus_url, ok_expr)), observe_timeout_s), (
        "C층 be_telemetry_water_level_m 이 Prometheus 에 나타나지 않았다 (source_id={})".format(ok_id)
    )
    series = prom_query(prometheus_url, ok_expr)[0]
    assert float(series["value"][1]) == 2.53
    labels = series["metric"]
    assert labels["zone_id"] == "zoneA" and labels["entity_type"] == "sensor" and labels["channel"] == "state"
    assert not {"session_id", "sequence_id", "internal_seq", "timestamp"}.intersection(labels)

    # ★음성 N4 — 같은 창에 같이 발행한 null 형태는 시계열이 없다 (0 으로 둔갑하지 않는다).
    null_series = prom_query(prometheus_url, '{{__name__=~"be_telemetry_.*",source_id="{}"}}'.format(null_id))
    assert null_series == [], "값이 null 인 발행이 시계열을 만들었다: {}".format(null_series)


# ── 16(게이트웨이) — WS 클라이언트가 붙어 있는 동안 clients·push 가 잡힌다 ────────


def test_gateway_metrics_with_ws_client(prometheus_url, ws_url, broker, observe_timeout_s) -> None:
    try:
        from websockets.asyncio.client import connect as ws_connect
    except ImportError:  # pragma: no cover
        from websockets import connect as ws_connect  # type: ignore[attr-defined]

    push_before = prom_scalar(prometheus_url, 'sum(be_gateway_push_total)')
    source_id = _unique("wl-obs-ws")

    async def run() -> Dict[str, Any]:
        async with ws_connect(ws_url, open_timeout=10) as client:
            _publish_state(broker, source_id)
            deadline = time.time() + observe_timeout_s
            got = False
            while time.time() < deadline and not got:
                raw = await asyncio.wait_for(client.recv(), timeout=max(1.0, deadline - time.time()))
                got = json.loads(raw).get("message", {}).get("source_id") == source_id
            # 접속을 유지한 채 Prometheus 를 본다 — clients 는 접속 중일 때만 ≥1 이다.
            clients_ok = await asyncio.to_thread(
                wait_until, lambda: prom_scalar(prometheus_url, 'sum(be_gateway_clients)') >= 1, observe_timeout_s
            )
            # push 도 export(15s)+scrape(5s) 를 기다린다. 이전 판은 clients 대기가 그 시간을 대신 벌어 준다고 기댔는데,
            # 다른 뷰어(브라우저 등)가 이미 붙어 있으면 clients 가 즉시 ≥1 이라 push 를 export 전에 읽어 헛되이
            # 실패했다(Phase 4 단계 7, 2026-09-19 서버 실측).
            push_ok = await asyncio.to_thread(
                wait_until,
                lambda: counter_delta(push_before, prom_scalar(prometheus_url, 'sum(be_gateway_push_total)')) >= 1,
                observe_timeout_s,
            )
            return {"got": got, "clients_ok": clients_ok, "push_ok": push_ok}

    result = asyncio.run(run())
    assert result["got"], "WS 로 발행값이 도달하지 않았다"
    assert result["clients_ok"], "be_gateway_clients 가 접속 중에 1 이상이 되지 않았다"
    assert result["push_ok"], "be_gateway_push_total 이 늘지 않았다"


# ── 20 — 백엔드 로그가 Loki 에 도달한다 ─────────────────────────────────────


def _loki_lines(loki_url: str, query: str, minutes: int = 10) -> List[str]:
    now_ns = time.time_ns()
    params = urllib.parse.urlencode({
        "query": query, "limit": 50,
        "start": now_ns - minutes * 60 * 10**9, "end": now_ns,
    })
    data = http_get_json(loki_url + "/loki/api/v1/query_range?" + params)
    return [value[1] for stream in data["data"]["result"] for value in stream["values"]]


def test_backend_logs_reach_loki(loki_url, broker, observe_timeout_s) -> None:
    source_id = _unique("wl-obs-log")
    _publish_state(broker, source_id)
    query = '{{service_name="be-ingest"}} |= "{}"'.format(source_id)
    assert wait_until(lambda: bool(_loki_lines(loki_url, query)), observe_timeout_s), (
        "ingest 의 produce 로그(source_id={})가 Loki 에 나타나지 않았다 — OTel 로그 경로(Collector→Loki) 확인".format(source_id)
    )
    line = _loki_lines(loki_url, query)[0]
    assert "produce" in line and source_id in line


# ── 21 — 가짜 span 1건이 Collector 를 거쳐 Tempo 에 꽂힌다 ──────────────────


def test_fake_span_reaches_tempo(tempo_url, observe_timeout_s) -> None:
    """백엔드 span 생산은 Phase 6 이다. 이번엔 **테스트가 span 1건을 서버 Collector(127.0.0.1:4316)로**
    보내 traces 파이프라인(Collector → Tempo)이 실제로 흐르는지만 본다. 단계 0 에서 Tempo 의
    service.name 태그값은 `[]` 였다.
    """
    pytest.importorskip("opentelemetry.sdk", reason="OTel SDK 미설치 — 가짜 span 테스트를 건너뛴다")
    endpoint = settings.otel_endpoint()
    if not endpoint:
        pytest.skip("MK2_OTEL_ENDPOINT 가 비어 있다 — 발신 대상이 없다")
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    service_name = _unique("be-test-span")
    provider = TracerProvider(resource=Resource.create({"service.name": service_name, "service.namespace": "mk2"}))
    provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=not endpoint.startswith("https://"))))
    with provider.get_tracer("mk2.tests").start_as_current_span("be.test.fake_span") as span:
        span.set_attribute("mk2.test", True)
    provider.force_flush()
    provider.shutdown()

    def _found() -> bool:
        data = http_get_json(tempo_url + "/api/search?" + urllib.parse.urlencode({"tags": "service.name=" + service_name, "limit": 5}))
        return bool(data.get("traces"))

    assert wait_until(_found, observe_timeout_s), "가짜 span 이 Tempo 검색에 나타나지 않았다 (service.name={})".format(service_name)
    values = http_get_json(tempo_url + "/api/search/tag/service.name/values").get("tagValues", [])
    assert service_name in values, "service.name 태그값에 {} 가 없다: {}".format(service_name, values)


# ── 33 ★음성 — 중앙 직접 수집분에는 agg_layer 가 없다 ────────────────────────


def test_central_series_have_no_agg_layer(prometheus_url) -> None:
    assert prom_query(prometheus_url, 'count({__name__=~"be_.*",agg_layer!=""})') == [], (
        "중앙이 직접 수집한 be_* 시계열에 agg_layer 라벨이 붙어 있다 — 경계 표기 규약(부재=중앙) 위반"
    )
