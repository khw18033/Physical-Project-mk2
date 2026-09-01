"""implements: AI-O-01, AI-O-02, AI-O-03, AI-C-05
tests: capture failure isolation, non-aggregatable channels, run replay
"""
import json

from perception_framework.observability.experiment import (
    ExperimentRecorder, NullRecorder, RunHeader, replay,
)


def header():
    return RunHeader(run_id="demo-001", domain_id="river_hazard",
                     profile_id="river", versions={"rules": "v1"})


def test_liveness_and_faults_stay_individual_in_the_summary():
    r = ExperimentRecorder(header())
    r.capture_resource(latency_ms=90.0)
    r.capture_resource(latency_ms=110.0)
    r.capture("fault", code="model_load_failed", value=1)
    r.capture("liveness", node="edge-1", up=0)
    summary = r.summarize()
    assert summary["summary"]["resource.latency_ms"]["avg"] == 100.0
    assert not any(k.startswith(("fault.", "liveness.")) for k in summary["summary"])
    assert len(summary["individual"]) == 2


def test_network_is_summarized_but_reconfiguration_stays_individual():
    r = ExperimentRecorder(header())

    r.capture_network(link_delay_ms=10.0, queue_depth=1)
    r.capture_network(link_delay_ms=20.0, queue_depth=3)
    r.capture_reconfiguration(
        capability_kind="perception.detect",
        previous_provider="pi-cpu-detector",
        next_provider="edge-accelerator-detector",
        reason="node_has_accelerator",
    )

    summary = r.summarize()
    assert summary["summary"]["network.link_delay_ms"]["avg"] == 15.0
    assert summary["summary"]["network.queue_depth"]["max"] == 3
    assert not any(k.startswith("reconfiguration.") for k in summary["summary"])
    assert summary["individual"][0]["channel"] == "reconfiguration"


def test_capture_failure_never_raises_into_the_caller():
    r = ExperimentRecorder(header())

    class Unserializable:
        __dataclass_fields__ = {"boom": None}

    r.capture_record(Unserializable())      # must not raise
    assert r.enabled is False
    r.capture("note", text="still safe")    # must remain silent


def test_run_bundle_round_trips_for_offline_analysis(tmp_path):
    r = ExperimentRecorder(header())
    r.capture("evidence", evidence_id="e1", source_group="det_a", confidence=0.8)
    path = r.write(tmp_path)
    assert path is not None
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["header"]["domain_id"] == "river_hazard"
    assert stored["header"]["versions"] == {"rules": "v1"}
    assert replay(path, "evidence")[0]["evidence_id"] == "e1"


def test_capacity_limit_drops_instead_of_growing_without_bound():
    r = ExperimentRecorder(header(), limit=2)
    for i in range(5):
        r.capture("note", i=i)
    assert len(r.entries) == 2 and r.dropped == 3


def test_null_recorder_is_inert_for_profiles_without_capture():
    r = NullRecorder()
    r.capture("evidence", evidence_id="x")
    assert r.entries == [] and r.enabled is False
