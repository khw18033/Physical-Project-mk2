"""
피지컬팀 mk2 — 노드 자기 관측 metric 5종 (HW-C-05 / BE-S-02)
=============================================================
업무 데이터(MQTT)와 관측 데이터(OTLP)는 평면을 나눈다. 업무 경로가 막혀도 "왜
막혔는지"는 관측 경로로 보여야 하기 때문에, 같은 통로로 보내면 장애 시 둘 다 눈이 먼다.

발신 대상은 구역 엣지의 Collector(Agent)이고, 엣지가 가공해 백엔드 Collector
(Gateway)로 모은다 — BE-S-02의 Agent+Gateway 구조.

metric 5종
  1) system.cpu.utilization      CPU 사용률
  2) system.memory.utilization   메모리 사용률
  3) system.filesystem.free      디스크 여유 공간 — HW-R-09 버퍼가 먹는 자원이라 포함
  4) hw.publish.count            발행 성공/실패 (outcome 속성으로 구분)
  5) hw.publish.duration         발행 지연(ms)

export 주기 60초(HW-C-05). 계획서 초안의 15초와 상충하여 요구사항 정의서를 따랐다.

SDK 미설치·엔드포인트 미설정이면 조용히 no-op으로 떨어진다. 관측이 없다고 해서
말단이 계측을 멈추면 안 되기 때문이다(관측은 업무의 전제조건이 아니다).
"""
import shutil

from common import config

try:
    import psutil
except ImportError:
    psutil = None


class _Noop:
    enabled = False

    def record_publish(self, ok, latency_ms):
        pass

    def shutdown(self):
        pass


class Metrics:
    enabled = True

    def __init__(self, identity):
        from opentelemetry import metrics
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource

        try:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,
            )
        except ImportError:
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                OTLPMetricExporter,
            )

        # Resource 속성으로 어느 노드의 지표인지 식별한다. 지표 이름에 장치 ID를
        # 넣으면 시계열이 장치 수만큼 폭발하므로 속성으로 붙이는 것이 정석이다.
        resource = Resource.create({
            "service.name": "hw-sensor-node",
            "service.version": config.FW_VERSION,
            "service.instance.id": identity.entity_id,
            "hw.entity_id": identity.entity_id,
            "hw.node_id": identity.node_id,
            "hw.zone_id": identity.zone_id,
        })
        reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=config.OTEL_ENDPOINT),
            export_interval_millis=int(config.OTEL_EXPORT_INTERVAL * 1000),
        )
        self._provider = MeterProvider(resource=resource, metric_readers=[reader])
        metrics.set_meter_provider(self._provider)
        meter = metrics.get_meter("hw.node")

        from opentelemetry.metrics import Observation

        def cpu(_):
            yield Observation(psutil.cpu_percent(interval=None) / 100.0)

        def mem(_):
            yield Observation(psutil.virtual_memory().percent / 100.0)

        def disk(_):
            yield Observation(float(shutil.disk_usage(_spool_dir()).free))

        if psutil:
            meter.create_observable_gauge("system.cpu.utilization", callbacks=[cpu],
                                          unit="1", description="CPU 사용률")
            meter.create_observable_gauge("system.memory.utilization", callbacks=[mem],
                                          unit="1", description="메모리 사용률")
        meter.create_observable_gauge("system.filesystem.free", callbacks=[disk],
                                      unit="By", description="버퍼가 쓰는 파티션의 여유 공간")
        self._count = meter.create_counter(
            "hw.publish.count", unit="1", description="MQTT 발행 성공/실패 건수")
        self._latency = meter.create_histogram(
            "hw.publish.duration", unit="ms", description="MQTT 발행 지연")

    def record_publish(self, ok, latency_ms):
        outcome = {"outcome": "ok" if ok else "fail"}
        self._count.add(1, outcome)
        self._latency.record(latency_ms, outcome)

    def shutdown(self):
        try:
            self._provider.shutdown()
        except Exception:
            pass


def _spool_dir():
    import os
    return os.path.dirname(config.SPOOL_PATH) or "."


def create(identity):
    """설정·의존성이 갖춰졌을 때만 실제 계측기를 만들고, 아니면 no-op."""
    if not config.OTEL_ENDPOINT:
        print("[otel] HW_OTEL_ENDPOINT 미설정 — 관측 발신 비활성")
        return _Noop()
    try:
        m = Metrics(identity)
        print(f"[otel] {config.OTEL_ENDPOINT} 로 {config.OTEL_EXPORT_INTERVAL:.0f}초마다 export")
        return m
    except Exception as e:
        print(f"[otel] 초기화 실패({type(e).__name__}: {e}) — 관측 없이 계속 동작")
        return _Noop()
