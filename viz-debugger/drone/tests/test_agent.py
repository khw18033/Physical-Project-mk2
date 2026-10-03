"""드론 에이전트에 붙이는 면 — 공통 틀(BaseNode)과 같은 모양의 가짜 노드 위에서."""

import asyncio

import pytest

from sar_pass.agent import SarBridge, SarRejected, with_sar
from sar_pass.capture import CaptureFlag
from sar_pass.vehicle import SimClock, SimVehicle

from test_controller import params
from test_mission import LAT0, LON0


class FakeIdentity:
    entity_id, node_id, zone_id, entity_type = "x500-001", "pi3", "zoneA", "drone"


class FakeDroneNode:
    """공통 틀에서 쓰는 것만: ACTIONS · validate · status_extra · publish · shutdown."""

    ACTIONS = {"ping": lambda node, p: iter([("completed", {"uptime_s": 1.0})])}

    def __init__(self):
        self.identity = FakeIdentity()
        self.base = "zoneA/drone/x500-001"
        self.published = []
        self.validated = []
        self.down = False

    def validate(self, action, params):
        self.validated.append(action)

    def status_extra(self):
        return {"fc": "ok"}

    def publish(self, topic, payload, qos=1, retain=False, allow_spool=True):
        self.published.append((topic, payload, retain, allow_spool))
        return True

    def shutdown(self):
        self.down = True


def make_node(tmp_path, fail_connect=False):
    sim = SimVehicle(LAT0, LON0, clock=SimClock(start=1e6))
    connects = []

    class Node(with_sar(FakeDroneNode)):
        def make_sar_bridge(self):
            async def factory():
                connects.append(1)
                if fail_connect:
                    raise TimeoutError()
                return sim

            from sar_pass.agent import publish_sar_status
            return SarBridge(factory, CaptureFlag(tmp_path / "CAP_ON", install_handlers=False),
                             status_sink=lambda s: publish_sar_status(self, s), log_dir=tmp_path)

    return Node(), connects


def run(handler, node, p):
    return list(handler(node, p))


def wait_mission(node, timeout=60):
    task = node.sar.controller.task
    return asyncio.run_coroutine_threadsafe(asyncio.wait_for(asyncio.shield(task), timeout), node.sar.loop).result(timeout + 5)


def test_declares_actions_and_keeps_original(tmp_path):
    node, _ = make_node(tmp_path)
    assert {"ping", "sar_start", "sar_abort"} <= set(node.ACTIONS)
    node.validate("ping", {})
    assert node.validated == ["ping"]          # 원래 검증은 그대로 불린다
    assert node.status_extra()["fc"] == "ok" and node.status_extra()["sar"]["running"] is False


def test_validate_rejects_bad_params_without_io(tmp_path):
    node, connects = make_node(tmp_path)
    with pytest.raises(SarRejected) as e:
        node.validate("sar_start", params(speed_mps=7.0))
    assert e.value.code == "INVALID_ARGUMENT" and "속도" in e.value.message
    with pytest.raises(SarRejected):
        node.validate("sar_start", {"alt_m": 20.0})
    node.validate("sar_abort", {})            # 중단은 언제나 받는다
    assert connects == []                     # 검증 단계에서는 FC 에 붙지 않는다


def test_start_flies_publishes_and_rejects_second(tmp_path):
    node, connects = make_node(tmp_path)
    node.validate("sar_start", params())
    stages = run(node.ACTIONS["sar_start"], node, params())
    assert stages[-1] == ("completed", {"started": 1.0})
    with pytest.raises(SarRejected) as e:
        node.validate("sar_start", params())
    assert e.value.code == "FAILED_PRECONDITION"
    assert wait_mission(node) == "done"
    sar = [(t, b, r, s) for t, b, r, s in node.published if t.endswith("/sar")]
    assert sar and all(r and not s for _, _, r, s in sar)
    assert sar[-1][0] == "zoneA/drone/x500-001/sar" and sar[-1][1]["state"] == "done"
    assert sar[-1][1]["source_id"] == "x500-001"
    assert any(b["capturing"] for _, b, _, _ in sar)
    assert not node.sar.cap.is_on and len(connects) == 1
    # 두 번째 임무는 FC 에 다시 붙지 않는다
    run(node.ACTIONS["sar_start"], node, params())
    assert wait_mission(node) == "done" and len(connects) == 1


def test_connect_failure_is_reported_and_retryable(tmp_path):
    node, connects = make_node(tmp_path, fail_connect=True)
    with pytest.raises(SarRejected) as e:
        run(node.ACTIONS["sar_start"], node, params())
    assert e.value.code == "UNAVAILABLE"
    node.validate("sar_start", params())       # 실패 뒤 다시 시도할 수 있다
    with pytest.raises(SarRejected):
        run(node.ACTIONS["sar_start"], node, params())
    assert len(connects) == 2


def test_abort_clears_flag_even_without_mission(tmp_path):
    node, _ = make_node(tmp_path)
    node.sar.cap.on()
    assert run(node.ACTIONS["sar_abort"], node, {})[-1] == ("completed", {"aborted": 1.0, "was_running": 0.0})
    assert not node.sar.cap.is_on


def test_abort_and_shutdown_stop_running_mission(tmp_path):
    node, _ = make_node(tmp_path)
    run(node.ACTIONS["sar_start"], node, params())
    stages = run(node.ACTIONS["sar_abort"], node, {})
    assert stages[-1][1]["was_running"] == 1.0
    assert wait_mission(node) == "aborted" and not node.sar.cap.is_on

    node2, _ = make_node(tmp_path)
    run(node2.ACTIONS["sar_start"], node2, params())
    node2.shutdown()
    assert node2.down and node2.sar.controller.task.done() and not node2.sar.cap.is_on
