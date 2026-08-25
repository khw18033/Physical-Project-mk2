"""tests for: AI-C-04, AI-C-06, AI-C-07, AI-C-08, AI-C-09, AI-C-12, AI-B-08"""

import pytest

from ai_framework.providers.fakes import (
    InMemoryObservabilityProvider,
    InMemoryTransportProvider,
    JsonSerializerProvider,
    StubAIRuntimeProvider,
    SyntheticMediaSourceProvider,
)


def test_transport_publish_subscribe_round_trip():
    transport = InMemoryTransportProvider()
    received = []
    transport.subscribe("task/zone-1", received.append)

    transport.publish("task/zone-1", b"hello")

    assert received == [b"hello"]


def test_transport_disconnected_buffers_publish_without_delivery_or_crash():
    transport = InMemoryTransportProvider()
    received = []
    transport.subscribe("task/zone-1", received.append)
    transport.set_connected(False)

    transport.publish("task/zone-1", b"hello")  # must not raise

    assert received == []
    assert transport.published == [("task/zone-1", b"hello", "at_least_once")]


def test_json_serializer_round_trip():
    serializer = JsonSerializerProvider()
    obj = {"risk_state": "ALERT", "score": 0.8}

    payload = serializer.encode(obj)
    decoded = serializer.decode(payload)

    assert decoded == obj


def test_media_source_returns_none_and_reports_unavailable_when_video_lost():
    media = SyntheticMediaSourceProvider("cam-1", frames=[1, 2])

    assert media.read_frame() == 1
    media.set_available(False)

    assert media.read_frame() is None
    assert media.is_available() is False


def test_ai_runtime_provider_swap_does_not_change_caller_contract():
    def call_upper_layer(runtime, capability_kind, inputs):
        """Stand-in for upper-layer code: only depends on the
        AIRuntimeProvider Protocol, never on which backend it is."""
        if not runtime.is_available():
            return None
        return runtime.infer(capability_kind, inputs)

    local = StubAIRuntimeProvider(("perception.classify",), lambda kind, x: {"source": "local", "x": x})
    remote = StubAIRuntimeProvider(("perception.classify",), lambda kind, x: {"source": "remote", "x": x})

    assert call_upper_layer(local, "perception.classify", 1) == {"source": "local", "x": 1}
    assert call_upper_layer(remote, "perception.classify", 1) == {"source": "remote", "x": 1}


def test_ai_runtime_provider_unavailable_is_reported_not_raised():
    runtime = StubAIRuntimeProvider(("perception.classify",), available=False)

    assert runtime.is_available() is False


def test_ai_runtime_provider_rejects_unsupported_capability_kind():
    runtime = StubAIRuntimeProvider(("perception.classify",))

    with pytest.raises(ValueError):
        runtime.infer("perception.track", {})


def test_observability_separates_critical_events_from_metrics():
    obs = InMemoryObservabilityProvider()

    obs.record_metric("cpu_pct", 42.0)
    obs.record_event("device_dead", severity="fatal", payload={"device_id": "robot-1"})

    assert len(obs.metrics) == 1
    assert len(obs.critical_events()) == 1
    assert obs.critical_events()[0].name == "device_dead"


def test_observability_local_event_recording_survives_collector_outage():
    obs = InMemoryObservabilityProvider()
    obs.simulate_collector_down()

    with pytest.raises(RuntimeError):
        obs.record_metric("cpu_pct", 42.0)

    # The metric path failing must not take the event path down with it
    # (AI-O-01: "외부 관측 기능 장애가 실제 기능 실행을 중단시키지 않아야 한다").
    obs.record_event("classifier_crash", severity="critical")
    assert len(obs.critical_events()) == 1
