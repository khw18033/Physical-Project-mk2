"""Real OpenTelemetry `ObservabilityProvider` (OTLP export).

implements: AI-O-01, AI-O-02, AI-C-12, AI-C-14

원칙 #10: metric·log·trace는 OpenTelemetry 기반 관측 경로를 사용한다. 다만
AI 코드가 이 구현 기술의 API에 직접 의존해서는 안 되므로 `opentelemetry` 는
이 모듈에서만 import한다.

Two guarantees this module must keep and that the tests pin down:

1. **관측 실패가 기능 실행을 막지 않는다** (AI-O-01). Every export path is
   wrapped; a collector outage can never propagate to a caller.
2. **치명 오류·장치 생사는 metric 요약과 분리된 개별 사건으로 남는다**
   (원칙 #14, AI-O-02). `record_event` therefore goes to the log/event
   pipeline with its own severity, never into a metric aggregation, and
   is additionally kept in a local buffer so it survives a collector
   outage (AI-O-02: "외부 수집기가 일시적으로 사용할 수 없어도 로컬 오류
   기록은 남아야 한다").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_CRITICAL_SEVERITIES = {"critical", "fatal"}


@dataclass
class LocalEventRecord:
    name: str
    severity: str
    payload: dict | None
    exported: bool = False


@dataclass
class OtelConfig:
    """Endpoint/service identity for this deployment.

    Values come from the deployment profile, never hardcoded upstream
    (AI-C-12).
    """

    endpoint: str = "http://127.0.0.1:4317"
    service_name: str = "perception-framework"
    export_interval_ms: int = 1000
    timeout_s: int = 5
    resource_attributes: dict = field(default_factory=dict)


class OtlpObservabilityProvider:
    """ObservabilityProvider exporting metrics and events over OTLP."""

    def __init__(self, config: OtelConfig | None = None) -> None:
        self._config = config or OtelConfig()
        self._local_events: list[LocalEventRecord] = []
        self._meter = None
        self._logger = None
        self._provider = None
        self._counters: dict[str, Any] = {}
        self._started = False

    # --- lifecycle -----------------------------------------------------
    def start(self) -> bool:
        """Wire up the SDK. Returns False (never raises) if unavailable —
        the node then keeps running with local-only observability."""
        try:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            from opentelemetry.sdk.resources import Resource

            resource = Resource.create(
                {"service.name": self._config.service_name, **self._config.resource_attributes}
            )
            reader = PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=self._config.endpoint, insecure=True),
                export_interval_millis=self._config.export_interval_ms,
            )
            self._provider = MeterProvider(resource=resource, metric_readers=[reader])
            self._meter = self._provider.get_meter("perception_framework")
            self._logger = _build_event_logger(self._config)
            self._started = True
        except Exception:
            self._started = False
        return self._started

    def shutdown(self) -> None:
        for target in (self._provider, self._logger):
            try:
                if target is not None:
                    target.shutdown()
            except Exception:
                pass
        self._started = False

    def flush(self, timeout_ms: int = 5000) -> None:
        for target in (self._provider, self._logger):
            try:
                if target is not None:
                    target.force_flush(timeout_ms)
            except Exception:
                pass

    # --- ObservabilityProvider ------------------------------------------
    def record_metric(self, name: str, value: float, tags: dict | None = None) -> None:
        """General numeric metric — aggregatable, summarisable at the edge."""
        if not self._started:
            return
        try:
            counter = self._counters.get(name)
            if counter is None:
                counter = self._meter.create_counter(name)
                self._counters[name] = counter
            counter.add(value, attributes=_string_attrs(tags))
        except Exception:
            # 외부 관측 기능 장애가 실제 기능 실행을 중단시키지 않아야 한다 (AI-O-01).
            return

    def record_event(self, name: str, severity: str, payload: dict | None = None) -> None:
        """Individually significant event — never folded into a metric.

        Kept locally first so the record exists even when the collector
        is unreachable (AI-O-02).
        """
        record = LocalEventRecord(name=name, severity=severity, payload=payload)
        self._local_events.append(record)
        if not self._started or self._logger is None:
            return
        try:
            self._logger.emit_event(name, severity, payload)
            record.exported = True
        except Exception:
            return

    # --- local inspection ------------------------------------------------
    def local_events(self) -> list[LocalEventRecord]:
        return list(self._local_events)

    def critical_events(self) -> list[LocalEventRecord]:
        return [e for e in self._local_events if e.severity.lower() in _CRITICAL_SEVERITIES]

    def is_started(self) -> bool:
        return self._started


def _string_attrs(tags: dict | None) -> dict:
    return {str(k): str(v) for k, v in (tags or {}).items()}


def _build_event_logger(config: "OtelConfig"):
    """Event/log pipeline, kept separate from metrics on purpose."""
    from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.resources import Resource

    resource = Resource.create(
        {"service.name": config.service_name, **config.resource_attributes}
    )
    provider = LoggerProvider(resource=resource)
    provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=config.endpoint, insecure=True))
    )
    return _EventLogger(provider)


class _EventLogger:
    """Thin wrapper turning framework events into OTLP log records."""

    _SEVERITY = {
        "debug": 5,
        "info": 9,
        "warning": 13,
        "error": 17,
        "critical": 21,
        "fatal": 21,
    }

    def __init__(self, provider) -> None:
        self._provider = provider
        self._logger = provider.get_logger("perception_framework.events")

    def emit_event(self, name: str, severity: str, payload: dict | None) -> None:
        from opentelemetry._logs import SeverityNumber

        number = self._SEVERITY.get(severity.lower(), 9)
        self._logger.emit(
            body=name,
            severity_text=severity.upper(),
            severity_number=SeverityNumber(number),
            attributes={"event.name": name, **_string_attrs(payload)},
            event_name=name,
        )

    def force_flush(self, timeout_ms: int) -> None:
        self._provider.force_flush(timeout_ms)

    def shutdown(self) -> None:
        self._provider.shutdown()
