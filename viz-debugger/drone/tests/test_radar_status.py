"""레이더 상태 메시지 — 규약 칸만 받고, 마지막 값을 기억해 1 초마다 다시 낸다."""

import json
import time

import pytest

from sar_pass.radar_status import RadarStatusPublisher, make_body, radar_topic


class FakeClient:
    def __init__(self):
        self.sent = []

    def publish(self, topic, payload, qos=0, retain=False):
        self.sent.append((topic, json.loads(payload), retain))

    def loop_stop(self):
        pass

    def disconnect(self):
        pass


def test_body_and_validation():
    b = make_body("x500-001", state="recording", recording=True, pulses_per_s=199.5)
    assert b["schema_version"] == "radar-0.1" and b["source_id"] == "x500-001" and b["recording"] is True
    with pytest.raises(ValueError):
        make_body("x", stat="typo")
    with pytest.raises(ValueError):
        make_body("x", state="busy")
    assert radar_topic("x500-001") == "zoneA/drone/x500-001/radar"


def test_publisher_keeps_last_values():
    c = FakeClient()
    pub = RadarStatusPublisher(device_id="x500-001", period_s=0.05, client=c)
    pub.update(state="recording", recording=True, file="a.bin")
    pub.update(pulses_per_s=200.0)
    time.sleep(0.12)
    pub.close()
    topic, last, retain = c.sent[-1]
    assert topic == "zoneA/drone/x500-001/radar" and retain
    assert last["file"] == "a.bin" and last["pulses_per_s"] == 200.0 and len(c.sent) >= 3
