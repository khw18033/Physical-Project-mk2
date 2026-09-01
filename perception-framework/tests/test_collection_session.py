"""implements: AI-S-06, AI-O-01, AI-O-03, AI-C-08, AI-C-11
tests: real completion ordering, worker failure isolation, availability
       capture, no pixels in the bundle, run replay
"""
import json
import time

import pytest

from perception_framework.collection import CollectionSession, new_session
from perception_framework.observability.experiment import replay
from perception_framework.providers.fakes import SyntheticMediaSourceProvider


class Worker:
    def __init__(self, worker_id, source_group, items, delay=0.0,
                 available=True, fail=False):
        self.worker_id = worker_id
        self.source_group = source_group
        self.items = items
        self.delay = delay
        self.available = available
        self.fail = fail
        self.calls = 0

    def run(self, frame):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("inference failed")
        return self.items

    def is_available(self):
        return self.available


def region(label, conf=0.8, object_id="obj-1"):
    return {"kind": "region", "confidence": conf, "region": (0, 0, 10, 10),
            "label": label, "object_id": object_id}


def session():
    return new_session("test_domain", profile_id="test", sample_interval=0.05)


def media(frames=3):
    return SyntheticMediaSourceProvider("cam-1", [{"pixels": [1, 2, 3]}] * frames)


def test_completion_times_are_measured_not_assumed():
    s = session()
    s.add_worker(Worker("fast", "det_a", [region("cup")], delay=0.02))
    s.add_worker(Worker("slow", "det_b", [region("cup")], delay=0.12))
    results = s.process_frame({"pixels": []}, "cam-1")
    by_id = {r.worker_id: r for r in results}
    assert by_id["fast"].completed_at < by_id["slow"].completed_at
    assert by_id["slow"].latency_ms > by_id["fast"].latency_ms


def test_a_failing_worker_does_not_stop_the_frame():
    s = session()
    s.add_worker(Worker("broken", "det_a", [], fail=True))
    s.add_worker(Worker("ok", "det_b", [region("cup")]))
    s.process_frame({"pixels": []}, "cam-1")
    faults = [e for e in s.recorder.entries if e.channel == "fault"]
    assert faults and faults[0].payload["error_code"] == "worker_failed"
    assert s.evidence_seen == 1          # the healthy worker still contributed


def test_unavailable_worker_is_skipped_without_error():
    s = session()
    s.add_worker(Worker("down", "det_a", [region("cup")], available=False))
    s.add_worker(Worker("up", "det_b", [region("cup")]))
    s.process_frame({"pixels": []}, "cam-1")
    assert s.evidence_seen == 1


def test_evidence_from_a_group_outside_availability_is_not_consumed():
    s = session()
    s.set_available_groups({"det_a"}, reason="link_loss")
    worker = Worker("b", "det_b", [region("cup")])
    s.add_worker(worker)
    s.add_worker(Worker("a", "det_a", [region("cup")]))
    s.process_frame({"pixels": []}, "cam-1")
    assert worker.calls == 0
    assert s.evidence_seen == 1


def test_availability_change_is_captured_individually_with_a_reason():
    s = session()
    s.set_available_groups({"det_a"}, reason="thermal")
    entries = [e for e in s.recorder.entries if e.channel == "capability"]
    assert entries and entries[0].payload["state_change_reason"] == "thermal"
    summary = s.recorder.summarize()
    assert not any(k.startswith("capability.") for k in summary["summary"])


def test_no_pixels_reach_the_run_bundle(tmp_path):
    s = session()
    s.add_worker(Worker("a", "det_a", [region("cup")]))
    s.run(media(2), max_frames=2)
    path = s.recorder.write(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "pixels" not in text


def test_run_bundle_records_conditions_and_replays(tmp_path):
    s = session()
    s.add_worker(Worker("a", "det_a", [region("cup")], delay=0.01))
    s.add_worker(Worker("b", "det_b", [region("cup")], delay=0.03))
    s.run(media(3), max_frames=3)
    path = s.recorder.write(tmp_path)
    bundle = json.loads(path.read_text(encoding="utf-8"))
    assert bundle["header"]["domain_id"] == "test_domain"
    assert s.frames_seen == 3
    evidence = replay(path, "evidence")
    assert len(evidence) == 6
    assert {e["source_group"] for e in evidence} == {"det_a", "det_b"}


def test_missing_media_is_recorded_and_ends_the_run():
    s = session()
    s.add_worker(Worker("a", "det_a", [region("cup")]))
    source = media(3)
    source.set_available(False)
    s.run(source)
    codes = [e.payload["error_code"] for e in s.recorder.entries if e.channel == "fault"]
    assert "media_unavailable" in codes
    assert s.frames_seen == 0


def test_resource_samples_are_attached_to_the_run():
    s = session()
    s.add_worker(Worker("a", "det_a", [region("cup")], delay=0.06))
    s.run(media(3), max_frames=3)
    assert any(e.channel == "resource" for e in s.recorder.entries)


def test_frame_with_no_usable_worker_is_recorded():
    s = session()
    s.add_worker(Worker("a", "det_a", [region("cup")], available=False))
    s.process_frame({"pixels": []}, "cam-1")
    codes = [e.payload["error_code"] for e in s.recorder.entries if e.channel == "fault"]
    assert "no_worker_available" in codes
