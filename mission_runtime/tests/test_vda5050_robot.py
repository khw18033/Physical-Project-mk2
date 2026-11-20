"""VDA 5050 어댑터의 계약 — `providers/vda5050_robot.py`.

implements: AI-C-20, AI-C-04, AI-B-09, AI-C-18
tests: 같은 `RobotControlBackend` 계약을 만족한다 · 어휘 밖은 **보내지 않는다** ·
       보낸 것은 수락이 아니다 · 안전 경로가 없으면 없다고 말한다 · 전송을 열지 않는다
"""
from __future__ import annotations

import json

from mission_runtime.providers.adapters import RobotControlBackend
from mission_runtime.providers.vda5050_robot import (
    REASON_NO_LOCAL_STOP,
    REASON_NO_TRANSPORT,
    REASON_UNMAPPED,
    Vda5050RobotBackend,
    VehicleState,
    to_order,
)


def backend(**over) -> Vda5050RobotBackend:
    sent: list = []
    made = Vda5050RobotBackend(
        manufacturer="acme", serial_number="agv-01",
        publish=over.pop("publish", lambda topic, msg: sent.append((topic, msg)) or True),
        **over)
    made._captured = sent                       # type: ignore[attr-defined]
    return made


def test_it_satisfies_the_same_backend_contract_as_every_other_robot():
    """**이것이 이 어댑터를 만든 이유다** — 경계가 옳았다면 끼워 맞출 것이 없다."""
    assert isinstance(backend(), RobotControlBackend)


def test_it_declares_only_what_it_can_actually_do():
    """못 하는 것을 선언하면 상위가 그것으로 배정한다(AI-C-18)."""
    names = {capability.kind for capability in backend().declared_actions()}
    assert "move_to" in names and "charge" in names
    assert "fly" not in names


def test_an_action_outside_the_vocabulary_is_never_sent_to_a_real_robot():
    """억지로 가장 비슷한 것으로 바꾸면 **로봇이 시킨 적 없는 일을 한다.**"""
    robot = backend()
    ok, result, reason = robot.execute("somersault", {}, command_id="C-1")

    assert ok is False
    assert reason == REASON_UNMAPPED
    assert robot.sent == [], "어휘 밖 명령은 전송 자체가 없어야 한다"


def test_a_move_without_a_destination_is_refused_rather_than_invented():
    robot = backend()
    ok, _result, reason = robot.execute("move_to", {}, command_id="C-2")
    assert ok is False and reason == REASON_UNMAPPED
    assert robot.sent == []


def test_a_move_becomes_an_order_with_our_command_id_as_the_order_id():
    """우리 식별자가 정본이다 — 차량이 돌려주는 값으로 되짚을 수 있어야 한다(AI-C-03)."""
    robot = backend()
    ok, result, _ = robot.execute("move_to", {"nodes": ["n0", "n1"]}, command_id="C-7")

    assert ok is True
    topic, message = robot.sent[0]
    assert topic.endswith("/order")
    assert message["orderId"] == "C-7"
    assert [n["nodeId"] for n in message["nodes"]] == ["n0", "n1"]
    assert result["order_id"] == "C-7"


def test_an_instant_action_does_not_go_into_the_driving_queue():
    """충전·정지를 주행 열에 끼우면 **앞의 주행이 끝나야** 실행된다."""
    robot = backend()
    robot.execute("charge", {}, command_id="C-9")
    topic, message = robot.sent[0]
    assert topic.endswith("/instantActions")
    assert message["actions"][0]["actionType"] == "startCharging"
    assert "orderId" not in message


def test_publishing_is_not_acceptance():
    """보낸 것은 수락이 아니다(AI-C-20). 상태는 **차량이** 돌려준다."""
    robot = backend()
    ok, result, _ = robot.execute("move_to", {"nodes": ["n0"]}, command_id="C-3")
    assert ok is True
    assert "accepted" not in (result or {})
    assert robot.state.order_id is None, "보냈다고 상태를 지어내지 않는다"


def test_a_failed_publish_is_reported_not_swallowed():
    robot = backend(publish=lambda topic, msg: False)
    ok, _result, reason = robot.execute("move_to", {"nodes": ["n0"]}, command_id="C-4")
    assert ok is False and reason == "publish_failed"


def test_without_a_transport_it_says_so_instead_of_pretending():
    robot = Vda5050RobotBackend(manufacturer="acme", serial_number="agv-01")
    ready, why = robot.readiness()
    assert ready is False and why == REASON_NO_TRANSPORT
    assert robot.execute("move_to", {"nodes": ["n0"]}, command_id="C-5")[2] == REASON_NO_TRANSPORT


# --------------------------------------------------------------- 안전

def test_the_emergency_path_does_not_go_through_the_network():
    """상위 네트워크 명령만을 안전 기능의 **유일한 경로**로 쓰지 않는다(AI-C-20)."""
    stopped: list[str] = []
    robot = backend(local_stop=lambda reason: stopped.append(reason) or True)

    assert robot.emergency_stop("사람이 들어왔다") is True
    assert stopped == ["사람이 들어왔다"]
    assert robot.sent == [], "긴급정지가 전송을 타면 망이 끊겼을 때 멈출 수 없다"


def test_without_a_local_stop_path_it_refuses_and_names_the_gap():
    """있는 척하면 그게 가장 위험하다."""
    robot = backend()
    assert robot.emergency_stop("x") is False
    assert robot.emergency_stop_reason() == REASON_NO_LOCAL_STOP


def test_requesting_a_stop_means_the_procedure_started_not_that_motion_ceased():
    robot = backend()
    assert robot.request_stop("C-6") is True
    topic, message = robot.sent[-1]
    assert topic.endswith("/instantActions")
    assert message["actions"][0]["actionType"] == "stop"


# --------------------------------------------------------------- 상태

def test_vehicle_state_is_recorded_not_judged():
    """차량의 최종 가용성은 우리가 정하지 않는다(AI-O-04 · 원칙 #15)."""
    robot = backend()
    state = robot.accept_state(json.dumps({
        "orderId": "C-7", "lastNodeId": "n1", "driving": True,
        "batteryState": {"batteryCharge": 61.0},
        "errors": [{"errorType": "motorOverheat"}]}))

    assert isinstance(state, VehicleState)
    assert state.order_id == "C-7" and state.driving is True
    assert state.errors == ("motorOverheat",)
    assert state.battery_charge == 61.0
    assert not hasattr(state, "available"), "가용성 판정을 여기서 만들지 않는다"


def test_a_reported_error_makes_the_vehicle_not_ready_with_the_reason():
    robot = backend()
    robot.accept_state({"errors": [{"errorType": "motorOverheat"}]})
    ready, why = robot.readiness()
    assert ready is False and "motorOverheat" in why


def test_an_unmeasured_battery_is_none_not_zero():
    state = VehicleState.from_vda({"orderId": "x"})
    assert state.battery_charge is None


# --------------------------------------------------------------- 경계

def test_the_adapter_opens_no_socket_of_its_own():
    """전송을 직접 열면 브로커 없이는 시험이 못 돈다 — 그리고 경계가 깨진다(AI-C-04)."""
    import inspect

    from mission_runtime.providers import vda5050_robot

    source = inspect.getsource(vda5050_robot)
    for word in ("import paho", "import socket", "mqtt.Client", "requests."):
        assert word not in source, f"전송을 직접 연다: {word}"


def test_the_mapping_is_data_so_a_new_vendor_word_is_one_line():
    robot = backend(action_map={"scan_shelf": "customScan"})
    ok, _result, _reason = robot.execute("scan_shelf", {}, command_id="C-8")
    assert ok is True
    assert robot.sent[0][1]["actions"][0]["actionType"] == "customScan"


def test_to_order_is_a_pure_function_so_it_can_be_checked_without_a_robot():
    message = to_order("move_to", {"nodes": ["a", "b"]}, command_id="C-1")
    assert message["orderId"] == "C-1"
    assert len(message["edges"]) == 1
    assert to_order("nope", {}, command_id="C-1") is None
