"""가짜 B층 발신자 — 말단 노드가 엣지 Collector(Agent)로 미는 관측 신호를 흉내 낸다.

HW `pi/common/otel_metrics.py`(metric 5종·resource 속성·no-op 규율)와 `otel_trace.py`(명령 경로 span)를
**그대로 흉내 낸다.** 실 말단은 `HW_OTEL_ENDPOINT`가 꺼져 있어 관측을 발신하지 않으므로, Phase 3의
Agent→Gateway 사슬(엣지 Collector → 서버 Collector → Loki·Tempo)과 페더레이션(엣지 Prometheus →
서버 Prometheus)은 이 발신자로 검증한다. **검증 범위의 한계: B층은 가짜 발신이다.**

무엇을 내나 (엣지 Collector `localhost:4317`로 OTLP gRPC push — 말단은 `/metrics`를 열지 않는다):

| 종류 | 이름 | HW 원본 |
|---|---|---|
| metric | `system.cpu.utilization` · `system.memory.utilization` · `system.filesystem.free` · `hw.publish.count{outcome}` · `hw.publish.duration` | `otel_metrics.py` 5종 |
| log | `hw.node` 로거의 INFO/WARNING 1줄 이상 (주기마다) | (HW는 아직 로그를 안 낸다 — 사슬 검증용) |
| trace | `cmd.receive`(SERVER) → `cmd.execute` → `cmd.result` (주기마다 1사슬, 고빈도 경로엔 없음) | `otel_trace.py` 범위 |

resource 속성은 세 신호가 **똑같다** — `service.name = hw-{entity_type}-node` · `service.version` ·
`service.instance.id = entity_id` · `hw.entity_id` · `hw.node_id` · `hw.zone_id`. 그래야 Collector·Grafana에서
같은 주체로 묶인다. export 주기 15초(HW `BACKEND_AGENDA` §10-1 종결값).

⚠ **엔드포인트는 서버가 아니라 엣지 Collector다.** 서버로 직접 쏘면 Agent를 건너뛰어 8-7이 검증하려는
사슬이 성립하지 않는다(지시서 8-7 d-1).

실행(컴퓨터 = 엣지):
    python tests/edge_probe_publisher.py                       # localhost:4317, 15초마다, Ctrl+C 로 종료
    python tests/edge_probe_publisher.py --interval 5          # 검증 중 빨리 보기
    python tests/edge_probe_publisher.py --entity-type robot   # service.name=hw-robot-node
    python tests/edge_probe_publisher.py --rounds 3            # 3주기 내고 flush 후 종료

implements: BE-S-02 (B층 가짜 발신 — Agent→Gateway 사슬 검증 재료), BE-S-03 (엣지 raw 보관 → 페더레이션 요약)
tests: 수동 — 단계 8 DoD (엣지 Prometheus 에 hw_*·system_* · 서버 페더레이션 · 서버 Loki/Tempo 에 엣지 log/span)
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import shutil
import sys
import time

try:
    import psutil
except ImportError:  # psutil 이 없으면 합성값 — 사슬 검증에는 값의 진위가 중요하지 않다
    psutil = None

LOG = logging.getLogger("hw.node")

DEFAULT_ENDPOINT = os.environ.get("EDGE_PROBE_ENDPOINT", "http://localhost:4317")
FW_VERSION = "0.3.0-probe"


def build_resource(entity_type: str, entity_id: str, node_id: str, zone_id: str):
    from opentelemetry.sdk.resources import Resource

    # otel_metrics.py:62-71 / otel_trace.py:147-154 와 같은 키.
    return Resource.create({
        "service.name": f"hw-{entity_type}-node",
        "service.version": FW_VERSION,
        "service.instance.id": entity_id,
        "hw.entity_id": entity_id,
        "hw.node_id": node_id,
        "hw.zone_id": zone_id,
    })


class Probe:
    def __init__(self, endpoint: str, resource, interval_s: float) -> None:
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.metrics import Observation
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry import trace as ot

        insecure = not endpoint.startswith("https://")

        # ── metric 5종 (otel_metrics.Metrics 그대로) ──────────────────────
        reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=endpoint, insecure=insecure),
            export_interval_millis=int(interval_s * 1000),
        )
        self.meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
        meter = self.meter_provider.get_meter("hw.node")

        if psutil:
            psutil.cpu_percent(interval=None)   # 첫 호출은 항상 0.0 — 미리 태워 둔다

        def cpu(_):
            yield Observation((psutil.cpu_percent(interval=None) if psutil else random.uniform(5, 40)) / 100.0)

        def mem(_):
            yield Observation((psutil.virtual_memory().percent if psutil else random.uniform(30, 70)) / 100.0)

        def disk(_):
            yield Observation(float(shutil.disk_usage(os.getcwd()).free))

        meter.create_observable_gauge("system.cpu.utilization", callbacks=[cpu], unit="1", description="CPU 사용률")
        meter.create_observable_gauge("system.memory.utilization", callbacks=[mem], unit="1", description="메모리 사용률")
        meter.create_observable_gauge("system.filesystem.free", callbacks=[disk], unit="By", description="버퍼가 쓰는 파티션의 여유 공간")
        self._count = meter.create_counter("hw.publish.count", unit="1", description="MQTT 발행 성공/실패 건수")
        self._latency = meter.create_histogram("hw.publish.duration", unit="ms", description="MQTT 발행 지연")

        # ── log (같은 resource) ──────────────────────────────────────────
        self.logger_provider = LoggerProvider(resource=resource)
        self.logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint, insecure=insecure))
        )
        handler = LoggingHandler(level=logging.NOTSET, logger_provider=self.logger_provider)
        LOG.addHandler(handler)
        LOG.setLevel(logging.INFO)

        # ── trace (otel_trace.Traces 와 같은 resource, 명령 경로만) ──────
        self.tracer_provider = TracerProvider(resource=resource)
        self.tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=insecure)))
        self._tracer = self.tracer_provider.get_tracer("hw.node.commands")
        self._ot = ot
        self._cmd_seq = 0

    def record_publish(self, ok: bool, latency_ms=None) -> None:
        outcome = {"outcome": "ok" if ok else "fail"}
        self._count.add(1, outcome)
        if latency_ms is not None:                  # 측정된 것만 넣는다(otel_metrics.py:109-112)
            self._latency.record(latency_ms, outcome)

    def command_chain(self) -> str:
        """`cmd.receive` → `cmd.execute` → `cmd.result` 한 사슬. command_id 는 속성으로 항상 붙는다."""
        self._cmd_seq += 1
        cid = f"probe-cmd-{self._cmd_seq:04d}"
        ot = self._ot
        receive = self._tracer.start_span("cmd.receive", kind=ot.SpanKind.SERVER)
        receive.set_attribute("hw.command.action", "set_report_interval")
        receive.set_attribute("hw.command.id", cid)
        receive.set_attribute("hw.command.result", "accepted")
        receive_ctx = ot.set_span_in_context(receive)
        receive.end()
        execute = self._tracer.start_span("cmd.execute", context=receive_ctx)
        execute.add_event("stage.executing")
        exec_ctx = ot.set_span_in_context(execute)
        with self._tracer.start_as_current_span("cmd.result", context=exec_ctx) as result:
            result.set_attribute("hw.command.stage", "completed")
        execute.end()
        return cid

    def shutdown(self) -> None:
        for provider in (self.meter_provider, self.logger_provider, self.tracer_provider):
            try:
                provider.shutdown()
            except Exception:  # noqa: BLE001
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="MK2 가짜 B층 발신자 (엣지 Collector 로 OTLP push)")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help=f"엣지 Collector OTLP gRPC. 기본 {DEFAULT_ENDPOINT}")
    parser.add_argument("--entity-type", default="sensor", choices=["sensor", "robot", "actuator"])
    parser.add_argument("--entity-id", default="wl-edge-001")
    parser.add_argument("--node-id", default="edge-pc")
    parser.add_argument("--zone-id", default="zoneA")
    parser.add_argument("--interval", type=float, default=15.0, help="export 주기(초). HW 와 같은 15 가 기본")
    parser.add_argument("--rounds", type=int, default=0, help="이 횟수만큼 내고 종료. 0 이면 Ctrl+C 까지")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", stream=sys.stdout)
    resource = build_resource(args.entity_type, args.entity_id, args.node_id, args.zone_id)
    probe = Probe(args.endpoint, resource, args.interval)
    print(f"[probe] service.name=hw-{args.entity_type}-node → {args.endpoint} 로 {args.interval:.0f}초마다 export "
          f"(metric 5 · log · span 사슬). 종료는 Ctrl+C")

    rounds = 0
    try:
        while True:
            # 발행 3건(성공 2 · 실패 1)을 흉내 낸다 — outcome 라벨이 둘 다 생기게.
            probe.record_publish(True, latency_ms=random.uniform(3, 40))
            probe.record_publish(True, latency_ms=random.uniform(3, 40))
            probe.record_publish(False)
            cid = probe.command_chain()
            LOG.info("publish ok=2 fail=1 command=%s zone=%s node=%s", cid, args.zone_id, args.node_id)
            if rounds % 4 == 3:
                LOG.warning("publish fail streak (probe synthetic) command=%s", cid)
            rounds += 1
            if args.rounds and rounds >= args.rounds:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("[probe] 종료 — 남은 표본을 flush 한다")
    finally:
        probe.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
