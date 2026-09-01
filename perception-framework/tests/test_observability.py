"""implements: AI-O-01, AI-O-02, AI-O-03, AI-O-04"""

from perception_framework.contracts.capability import CapabilityState
from perception_framework.observability.availability import (
    AvailabilitySignals,
    RemoteFeatureGate,
    SignalStatus,
)
from perception_framework.observability.events import CapabilityEventReporter, CapabilityStateChange
from perception_framework.observability.metrics import EdgeMetricStore
from perception_framework.observability.reproduction import ReproductionReferenceBuilder
from perception_framework.providers.fakes import InMemoryObservabilityProvider


# AI-O-01
def test_summary_aggregates_but_individual_device_state_stays_separate():
    store = EdgeMetricStore()
    store.record("cpu_pct", 10.0, at=1.0)
    store.record("cpu_pct", 20.0, at=2.0)
    store.set_individual_state("robot-1", "DEAD")

    summary = store.summarize("cpu_pct")

    assert summary.count == 2
    assert summary.avg == 15.0
    # device liveness must be retrievable on its own, untouched by the
    # numeric summary above.
    assert store.individual_state("robot-1") == "DEAD"


def test_summarize_unknown_metric_returns_none_not_error():
    store = EdgeMetricStore()

    assert store.summarize("never_recorded") is None


# AI-O-02
def test_required_capability_disabled_is_reported_as_critical():
    obs = InMemoryObservabilityProvider()
    reporter = CapabilityEventReporter(obs)

    reporter.report_transition(
        CapabilityStateChange("safety.local_judge", CapabilityState.ACTIVE, CapabilityState.DISABLED)
    )

    assert len(obs.critical_events()) == 1


def test_optional_dependency_loss_causing_degraded_is_not_treated_as_critical():
    obs = InMemoryObservabilityProvider()
    reporter = CapabilityEventReporter(obs)

    reporter.report_transition(
        CapabilityStateChange("safety.local_judge", CapabilityState.ACTIVE, CapabilityState.DEGRADED)
    )

    assert len(obs.critical_events()) == 0
    assert len(obs.events) == 1  # still recorded, just not as critical


# AI-O-03
def test_within_retention_uses_short_term_replay_ref_not_archive():
    builder = ReproductionReferenceBuilder()

    ref = builder.build(
        business_correlation_id="task-42",
        trace_id="trace-1",
        within_short_term_retention=True,
        short_term_replay_ref="kafka-offset-123",
        archive_ref="archive-456",
    )

    assert ref.short_term_replay_ref == "kafka-offset-123"
    assert ref.archive_ref is None


def test_outside_retention_falls_back_to_archive_ref():
    builder = ReproductionReferenceBuilder()

    ref = builder.build(
        business_correlation_id=None,
        trace_id=None,
        within_short_term_retention=False,
        short_term_replay_ref="kafka-offset-123",
        archive_ref="archive-456",
    )

    assert ref.short_term_replay_ref is None
    assert ref.archive_ref == "archive-456"
    assert ref.available_refs() == ("archive_ref",)


def test_no_references_available_is_reported_empty_without_crashing():
    builder = ReproductionReferenceBuilder()

    ref = builder.build(
        business_correlation_id=None,
        trace_id=None,
        within_short_term_retention=False,
        short_term_replay_ref=None,
        archive_ref=None,
    )

    assert ref.is_empty() is True


# AI-O-04
def test_signal_status_distinguishes_all_four_combinations():
    assert AvailabilitySignals(True, True).status == SignalStatus.BOTH_PRESENT
    assert AvailabilitySignals(True, False).status == SignalStatus.TASK_TRANSPORT_ONLY
    assert AvailabilitySignals(False, True).status == SignalStatus.OBSERVABILITY_ONLY
    assert AvailabilitySignals(False, False).status == SignalStatus.NEITHER_PRESENT


def test_remote_feature_gate_defers_entirely_to_backend_verdict():
    gate = RemoteFeatureGate()

    # Even with both raw signals alive, the gate must not override a
    # backend verdict of "unavailable" with its own judgment.
    assert gate.may_select_remote_capability(backend_integrated_available=False) is False
    assert gate.may_select_remote_capability(backend_integrated_available=True) is True
