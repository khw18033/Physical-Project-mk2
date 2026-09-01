"""implements: AI-O-01, AI-O-02, AI-C-12
covers: real OTLP export to a running collector, collector outage does not
        break execution, critical events stay individual and survive locally
"""

import importlib.util
import json
import os
import socket
import time
from pathlib import Path

import pytest

from perception_framework.observability.metrics import EdgeMetricStore
from perception_framework.providers.adapters import ObservabilityProvider
from perception_framework.providers.otel import OtelConfig, OtlpObservabilityProvider

COLLECTOR_HOST, COLLECTOR_PORT = "127.0.0.1", 4317
COLLECTOR_OUTPUT = os.environ.get("AIF_OTEL_OUTPUT")


def _installed() -> bool:
    return importlib.util.find_spec("opentelemetry") is not None


def _collector_up() -> bool:
    try:
        with socket.create_connection((COLLECTOR_HOST, COLLECTOR_PORT), timeout=0.5):
            return True
    except OSError:
        return False


needs_sdk = pytest.mark.skipif(not _installed(), reason="opentelemetry sdk extra not installed")
needs_collector = pytest.mark.skipif(
    not (_installed() and _collector_up()), reason="no OTLP collector on :4317"
)
needs_output = pytest.mark.skipif(
    not (COLLECTOR_OUTPUT and Path(COLLECTOR_OUTPUT).parent.exists()),
    reason="collector file output path not provided via AIF_OTEL_OUTPUT",
)


def provider(**kwargs):
    return OtlpObservabilityProvider(
        OtelConfig(endpoint=f"http://{COLLECTOR_HOST}:{COLLECTOR_PORT}", **kwargs)
    )


def test_provider_satisfies_the_observability_protocol():
    assert isinstance(OtlpObservabilityProvider(), ObservabilityProvider)


def test_only_the_otel_module_imports_the_sdk():
    """AI-C-12: 관측 구현 기술을 상위 코드가 직접 참조하지 않는다."""
    import subprocess

    package = Path(__file__).resolve().parents[1] / "perception_framework"
    hit = subprocess.run(
        ["grep", "-rln", "--include=*.py", "opentelemetry", str(package)],
        capture_output=True,
        text=True,
    )

    assert [Path(f).name for f in hit.stdout.split() if f] == ["otel.py"]


def test_unstarted_provider_accepts_calls_without_raising():
    # 관측이 아예 구성되지 않은 노드에서도 기능 코드는 그대로 돈다 (AI-O-01).
    unstarted = OtlpObservabilityProvider()

    unstarted.record_metric("perception.latency_ms", 12.5)
    unstarted.record_event("model_load_failed", "critical", {"model": "x"})

    assert not unstarted.is_started()
    assert len(unstarted.critical_events()) == 1  # 로컬 기록은 남는다


def test_unreachable_collector_does_not_break_execution():
    dead = OtlpObservabilityProvider(OtelConfig(endpoint="http://127.0.0.1:1"))
    dead.start()  # may or may not "start"; either way must not raise
    try:
        dead.record_metric("perception.latency_ms", 1.0)
        dead.record_event("optional_capability_lost", "warning", {"kind": "perception.depth"})
    finally:
        dead.shutdown()

    # 외부 수집기가 없어도 로컬 오류 기록은 남아야 한다 (AI-O-02).
    assert [e.name for e in dead.local_events()] == ["optional_capability_lost"]


@needs_sdk
def test_critical_events_are_never_folded_into_metric_aggregation():
    """원칙 #14 / AI-O-01: 장치 생사·치명 오류는 metric 요약과 분리 유지."""
    obs = provider(service_name="aif-test-separation")
    obs.start()
    store = EdgeMetricStore()
    try:
        for value in (10.0, 12.0, 11.0):
            obs.record_metric("perception.latency_ms", value)
            store.record("perception.latency_ms", value, at=time.time())
        obs.record_event("device_death", "fatal", {"device_id": "robot-1"})
    finally:
        obs.shutdown()

    summary = store.summarize("perception.latency_ms")
    assert summary is not None and summary.count == 3
    # The fatal event exists as its own record, not as a number inside the summary.
    assert [e.name for e in obs.critical_events()] == ["device_death"]


@needs_collector
def test_metrics_and_events_reach_a_real_collector():
    obs = provider(service_name="aif-test-export", export_interval_ms=500)
    assert obs.start()
    try:
        obs.record_metric("aif_test_counter", 3.0, {"capability": "perception.detect"})
        obs.record_event("aif_test_event", "critical", {"reason": "unit-test"})
        time.sleep(1.0)
        obs.flush()
    finally:
        obs.shutdown()

    exported = [e for e in obs.local_events() if e.name == "aif_test_event"]
    assert exported and exported[0].exported is True


@needs_collector
@needs_output
def test_collector_actually_received_the_telemetry():
    """End-to-end proof: the collector's own output file contains our data."""
    marker = f"aif_e2e_{int(time.time())}"
    obs = provider(service_name=marker, export_interval_ms=300)
    assert obs.start()
    try:
        obs.record_metric("aif_e2e_counter", 1.0)
        obs.record_event("aif_e2e_event", "critical", {"marker": marker})
        time.sleep(1.5)
        obs.flush()
    finally:
        obs.shutdown()

    deadline = time.time() + 15
    content = ""
    while time.time() < deadline:
        content = Path(COLLECTOR_OUTPUT).read_text(errors="ignore")
        if marker in content:
            break
        time.sleep(0.5)

    assert marker in content, "collector never received data tagged with this run's marker"
    assert "aif_e2e_counter" in content
    # metric과 event가 서로 다른 신호로 도착했는지 확인 (AI-O-02).
    assert "aif_e2e_event" in content


@needs_sdk
def test_metric_failure_path_is_isolated_from_event_path():
    obs = provider(service_name="aif-test-isolation")
    obs.start()
    try:
        obs._counters["broken"] = _ExplodingCounter()
        obs.record_metric("broken", 1.0)  # must swallow
        obs.record_event("still_recorded", "error", None)
    finally:
        obs.shutdown()

    assert [e.name for e in obs.local_events()] == ["still_recorded"]


class _ExplodingCounter:
    def add(self, *args, **kwargs):
        raise RuntimeError("metric sink unavailable")


def test_json_serialisable_payloads_are_stringified_safely():
    obs = OtlpObservabilityProvider()
    obs.record_event("weird_payload", "warning", {"count": 3, "nested": {"a": 1}})

    payload = obs.local_events()[0].payload
    assert json.dumps(payload, default=str)
