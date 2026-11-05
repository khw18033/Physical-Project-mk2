"""implements: AI-C-20, AI-C-07, AI-C-04, AI-C-18
covers: HW 파트 `package physical` 와이어 규약과의 정렬 회귀 — 필드번호·
        oneof 슬롯·enum 숫자를 **숫자로** 고정한다. 우리 코드끼리의 왕복
        시험은 양쪽이 같이 틀려 있어도 통과하므로(2026-09-19 이전이 정확히
        그 상태였다) 여기서는 바이트와 번호를 직접 본다.

배경: 정렬 전 우리 규약은 `ExecutionStatus` 한 enum 으로 진행·종료를 모두
표현했고 그 값 1이 `ACCEPTED` 였다. HW 규약에서 값 1은 `SUCCEEDED` 다.
같은 바이트가 한쪽에서는 "수락했다", 다른 쪽에서는 "성공했다"로 읽혔다 —
AI-C-20 이 구분하라고 못 박은 바로 그 지점이 조용히 붕괴했다.
"""

import pytest

from mission_runtime.contracts.capability_contract import DeclarationBasis
from mission_runtime.contracts.physical_command import (
    CancelCommandRequest,
    CancelCommandResponse,
    Capability,
    Command,
    CommandAcceptance,
    CommandResult,
    CommandStatus,
    ExecutionStatus,
    Failure,
    Rejection,
    RejectionCode,
)
from mission_runtime.contracts.proto import physical_command_pb2 as pb
from mission_runtime.providers.physical_command_protobuf import (
    TIME_SOURCE_EDGE_RECEIPT,
    PhysicalCommandProtobufSerializerProvider,
)


#: `hardware/schema/physical_command.proto`(정본, 2026-11-02 · traceparent 포함)에서
#: grpcio-tools 1.83.1 로 생성한 descriptor 의 SHA-256. 정본 파일로 직접 생성해
#: 비교했고 바이트가 같았다. 이 값이 깨지면 사본이 정본에서 벗어난 것이다.
CANONICAL_DESCRIPTOR_SHA256 = "0e2c2499ad6f640fe3dc16589648e1d32908c5224b26331175a2419d218cbdc7"


def _serializer() -> PhysicalCommandProtobufSerializerProvider:
    return PhysicalCommandProtobufSerializerProvider()


# -- 1. 번호 고정 (HW schema/physical_command.proto 를 그대로 옮긴 기대값) --

def test_wire_package_is_the_hardware_partys_package():
    assert pb.DESCRIPTOR.package == "physical"


def test_envelope_oneof_slots_match_the_hardware_schema():
    slots = {f.name: f.number for f in pb.PhysicalCommandEnvelope.DESCRIPTOR.fields}
    assert slots == {
        "command": 1, "cancel_request": 2, "acceptance": 3, "status": 4,
        "result": 5, "cancel_response": 6, "capability": 7,
    }


def test_terminal_status_enum_numbers_are_the_hardware_numbers():
    """값 1은 SUCCEEDED 다. 우리 쪽에서 ACCEPTED 가 아니다."""
    values = {v.name: v.number for v in pb.TerminalStatus.DESCRIPTOR.values}
    assert values == {
        "TERMINAL_STATUS_UNSPECIFIED": 0, "SUCCEEDED": 1, "ABORTED": 2, "CANCELED": 3,
    }
    assert "ACCEPTED" not in values


@pytest.mark.parametrize("message, expected", [
    (pb.Command, {"command_id": 1, "target": 2, "action": 3, "parameters": 4,
                  "deadline_unix_ms": 5, "traceparent": 6}),
    (pb.CancelCommandRequest, {"command_id": 1}),
    (pb.CommandAcceptance, {"command_id": 1, "accepted": 2, "rejection": 3}),
    (pb.CommandStatus, {"command_id": 1, "state": 2, "detail": 3}),
    (pb.CommandResult, {"command_id": 1, "status": 2, "result": 3, "failure": 4}),
    (pb.CancelCommandResponse, {"command_id": 1, "accepted": 2}),
    (pb.Capability, {"device_id": 1, "actions": 2}),
    (pb.Rejection, {"code": 1, "message": 2}),
    (pb.Failure, {"code": 1, "message": 2}),
])
def test_field_numbers_match_the_hardware_schema(message, expected):
    assert {f.name: f.number for f in message.DESCRIPTOR.fields} == expected


def test_command_field_5_is_a_deadline_not_a_correlation_id():
    """정렬 전 우리 필드 5는 correlation_id(string)였다. 지금은 int64 deadline."""
    field = pb.Command.DESCRIPTOR.fields_by_number[5]
    assert field.name == "deadline_unix_ms"
    assert field.type == field.TYPE_INT64


# -- 2. 바이트 고정 — "수락"과 "성공"이 실제로 다른 바이트인가 --------------

def test_acceptance_and_success_differ_on_the_wire_only_by_the_envelope_slot():
    """이 시험이 정렬 이전 상태였다면 실패했어야 한다.

    수락과 성공의 본문 바이트는 우연히 같다(`0a 03 "c-1" 10 01`). 둘을 가르는
    것은 봉투 슬롯 번호 하나뿐이다 — acceptance=3(0x1a), result=5(0x2a).
    그래서 봉투 슬롯이 어긋나면 "수락"이 "성공"으로 읽힌다. 숫자로 못 박는다.
    """
    body = b"\x0a\x03c-1\x10\x01"
    accepted = _serializer().encode(CommandAcceptance("c-1", True, 100.0))
    succeeded = _serializer().encode(
        CommandResult("c-1", ExecutionStatus.SUCCEEDED, 101.0)
    )
    assert accepted == b"\x1a" + bytes([len(body)]) + body
    assert succeeded == b"\x2a" + bytes([len(body)]) + body
    assert accepted != succeeded


def test_in_flight_states_never_travel_as_the_terminal_enum():
    """ACCEPTED/EXECUTING/CANCELING 은 숫자가 아니라 문자열로 간다."""
    payload = _serializer().encode(CommandStatus("c-1", ExecutionStatus.ACCEPTED, 100.0))
    envelope = pb.PhysicalCommandEnvelope()
    envelope.ParseFromString(payload)
    assert envelope.WhichOneof("body") == "status"
    assert envelope.status.state == "ACCEPTED"
    # 종료 상태를 CommandStatus 로 보내는 것은 계약 위반(spec §4).
    with pytest.raises(ValueError):
        _serializer().encode({
            "message_type": "status",
            "payload": {"command_id": "c-1", "status": "SUCCEEDED", "observed_at": 1.0},
        })


@pytest.mark.parametrize("status, number", [
    (ExecutionStatus.SUCCEEDED, 1), (ExecutionStatus.ABORTED, 2), (ExecutionStatus.CANCELED, 3),
])
def test_terminal_status_mapping_is_pinned_to_the_hardware_numbers(status, number):
    envelope = pb.PhysicalCommandEnvelope()
    envelope.ParseFromString(_serializer().encode(CommandResult("c-1", status, 1.0)))
    assert envelope.result.status == number


def test_a_device_speaking_the_hardware_schema_is_understood():
    """HW 구현(`pi/common/physical_command.py`)이 만드는 그대로를 읽는다."""
    envelope = pb.PhysicalCommandEnvelope()
    envelope.result.command_id = "c-7"
    envelope.result.status = pb.SUCCEEDED
    envelope.result.result["distance_moved"] = 1.0
    decoded = _serializer().decode(envelope.SerializeToString())
    assert decoded["message_type"] == "result"
    assert decoded["payload"]["status"] == ExecutionStatus.SUCCEEDED.value
    assert decoded["payload"]["result"] == {"distance_moved": 1.0}

    envelope = pb.PhysicalCommandEnvelope()
    envelope.status.command_id = "c-7"
    envelope.status.state = "EXECUTING"
    envelope.status.detail = "rotating"
    decoded = _serializer().decode(envelope.SerializeToString())
    assert decoded["payload"]["status"] == ExecutionStatus.EXECUTING.value
    assert decoded["payload"]["detail"] == "rotating"


# -- 3. AI-C-20 의미 구분이 정렬 후에도 남아 있는가 -------------------------

def test_rejection_is_an_acceptance_result_not_an_execution_state():
    payload = _serializer().encode(
        CommandAcceptance("c-2", False, 1.0, Rejection(RejectionCode.UNIMPLEMENTED, "no such action"))
    )
    decoded = _serializer().decode(payload)
    assert decoded["message_type"] == "acceptance"
    assert decoded["payload"]["accepted"] is False
    assert decoded["payload"]["rejection"]["code"] == "UNIMPLEMENTED"
    # 거부는 종료 상태 enum 어디에도 없다.
    assert "REJECTED" not in {v.name for v in pb.TerminalStatus.DESCRIPTOR.values}


def test_cancel_accepted_and_canceled_reached_are_two_different_messages():
    accepted = _serializer().decode(_serializer().encode(CancelCommandResponse("c-3", True)))
    reached = _serializer().decode(
        _serializer().encode(CommandResult("c-3", ExecutionStatus.CANCELED, 2.0))
    )
    assert accepted["message_type"] == "cancel_response"
    assert accepted["payload"]["accepted"] is True
    assert reached["message_type"] == "result"
    assert reached["payload"]["status"] == ExecutionStatus.CANCELED.value


def test_command_id_survives_every_message_so_idempotency_stays_checkable():
    messages = [
        Command("c-9", "robot1", "move_forward", {"distance": 1.0}),
        CancelCommandRequest("c-9"),
        CommandAcceptance("c-9", True, 1.0),
        CommandStatus("c-9", ExecutionStatus.EXECUTING, 1.0),
        CommandResult("c-9", ExecutionStatus.SUCCEEDED, 2.0),
        CancelCommandResponse("c-9", True),
    ]
    for message in messages:
        decoded = _serializer().decode(_serializer().encode(message))
        assert decoded["payload"]["command_id"] == "c-9"


def test_deadline_round_trips_as_unix_milliseconds():
    serializer = _serializer()
    decoded = serializer.decode(
        serializer.encode(Command("c-1", "r", "move_forward", {}, deadline=1_700_000_000.25))
    )
    assert decoded["payload"]["deadline"] == pytest.approx(1_700_000_000.25)
    # deadline 이 없으면 0 이 아니라 **키 자체가 없다**(결측을 0 으로 채우지 않는다).
    assert "deadline" not in serializer.decode(serializer.encode(Command("c-2", "r", "a")))["payload"]


# -- 4. 정렬의 대가 — 잃은 것이 조용히 사라지지 않는가 ----------------------

def test_correlation_id_is_recorded_as_a_wire_gap_not_silently_dropped():
    serializer = _serializer()
    payload = serializer.encode(Command("c-1", "r", "move_forward", {}, correlation_id="trace-1"))
    assert serializer.wire_gaps["command.correlation_id"] == 1
    assert b"trace-1" not in payload
    assert "correlation_id" not in serializer.decode(payload)["payload"]


def test_device_timestamps_have_no_wire_slot_and_decode_marks_the_substitution():
    serializer = _serializer()
    decoded = serializer.decode(serializer.encode(CommandAcceptance("c-1", True, 12345.0)))
    assert serializer.wire_gaps["acceptance.accepted_at"] == 1
    # 장치가 보고한 12345.0 이 아니라 우리가 받은 시각이고, 그렇다고 적혀 있다.
    assert decoded["payload"]["accepted_at"] != 12345.0
    assert decoded["payload"]["time_source"] == TIME_SOURCE_EDGE_RECEIPT

    serializer = _serializer()
    decoded = serializer.decode(
        serializer.encode(CommandResult("c-1", ExecutionStatus.ABORTED, 999.0,
                                        failure=Failure("INTERNAL", "boom")))
    )
    assert serializer.wire_gaps["result.completed_at"] == 1
    assert decoded["payload"]["time_source"] == TIME_SOURCE_EDGE_RECEIPT
    assert decoded["payload"]["failure"] == {"code": "INTERNAL", "message": "boom"}


def test_cancel_reason_has_no_wire_slot():
    serializer = _serializer()
    payload = serializer.encode(CancelCommandResponse("c-3", False, reason="unknown command"))
    assert serializer.wire_gaps["cancel_response.reason"] == 1
    assert b"unknown command" not in payload


def test_non_numeric_parameters_are_refused_rather_than_quietly_changed():
    """map<string,double> 는 문자열·불리언을 못 싣는다. 조용히 떨어뜨리면
    장치가 받는 명령의 의미가 달라지므로 보내기 전에 막는다."""
    for parameters in ({"hard": True}, {"mode": "fast"}, {"nested": {"a": 1}},
                       {"nan": float("nan")}):
        with pytest.raises(ValueError):
            _serializer().encode(Command("c-1", "r", "stop", parameters))
    # 결측은 키를 넣지 않는다(0 으로 채우지 않는다).
    serializer = _serializer()
    decoded = serializer.decode(serializer.encode(Command("c-1", "r", "stop", {"battery": None})))
    assert decoded["payload"]["parameters"] == {}
    assert serializer.wire_gaps["command.parameters.<null-value>"] == 1


def test_capability_declaration_loses_everything_but_the_action_name():
    """AI-C-18 선언 항목 중 이 와이어가 싣는 것은 action 이름뿐이다."""
    serializer = _serializer()
    payload = serializer.encode(Capability(
        "navigate.relative", "1.0", "schema://p", "schema://r",
        cancel_supported=True, required_resources=("mobility.base",),
    ))
    decoded = serializer.decode(payload)
    assert decoded["payload"]["actions"] == ["navigate.relative"]
    assert decoded["payload"]["declaration_scope"] == "actions_only"
    for lost in ("version", "parameter_schema", "result_schema",
                 "cancel_supported", "required_resources"):
        assert serializer.wire_gaps[f"capability.{lost}"] == 1
    assert b"schema://p" not in payload


def test_wire_gaps_can_be_pushed_into_an_event_sink():
    """관측 경로로 흘려보낼 수 있어야 손실을 운영에서도 볼 수 있다(AI-O-02)."""
    seen: list[str] = []
    serializer = PhysicalCommandProtobufSerializerProvider(on_gap=lambda f, _v: seen.append(f))
    serializer.encode(Command("c-1", "r", "stop", {}, correlation_id="trace-1"))
    assert seen == ["command.correlation_id"]


# -- 5. 계약을 어긴 uplink 는 거부한다 --------------------------------------

def test_unknown_in_flight_state_is_rejected_instead_of_guessed():
    envelope = pb.PhysicalCommandEnvelope()
    envelope.status.command_id = "c-1"
    envelope.status.state = "WARMING_UP"
    with pytest.raises(ValueError):
        _serializer().decode(envelope.SerializeToString())


def test_terminal_status_unspecified_is_not_treated_as_a_result():
    envelope = pb.PhysicalCommandEnvelope()
    envelope.result.command_id = "c-1"  # status 미설정 = 0
    with pytest.raises(ValueError):
        _serializer().decode(envelope.SerializeToString())


def test_a_rejection_without_a_reason_is_a_contract_violation():
    envelope = pb.PhysicalCommandEnvelope()
    envelope.acceptance.command_id = "c-1"
    envelope.acceptance.accepted = False
    with pytest.raises(ValueError):
        _serializer().decode(envelope.SerializeToString())


# -- 6. 정렬 이전 바이트는 무엇으로 읽히는가 (마이그레이션 문서화) ----------

def test_pre_alignment_bytes_are_mislabelled_not_rejected():
    """정렬 이전 봉투는 acceptance 를 슬롯 2에 실었다. 지금 그 슬롯은
    cancel_request 다 — 즉 옛 바이트는 **오류 없이 다른 메시지로 읽힌다.**
    그래서 옛 저장분을 새 코드로 다시 읽어서는 안 된다(보고서 §5 참고).
    """
    old_acceptance = b"\x12\x07\x0a\x03c-1\x10\x01"  # slot 2 (구 acceptance)
    decoded = _serializer().decode(old_acceptance)
    assert decoded["message_type"] == "cancel_request"   # 수락이 취소요청으로 읽힌다
    assert decoded["payload"]["command_id"] == "c-1"


# -- 7. JSON 디버깅 표현과 어긋나지 않는가 ----------------------------------

def test_decoded_payloads_validate_against_the_json_debug_schema():
    """`schemas/ai/physical-command.schema.json` 은 같은 의미 계약의 JSON
    표현이다. 와이어를 바꿨으니 이쪽도 같이 맞는지 시험이 붙들어 둔다."""
    import json
    import pathlib

    from jsonschema import Draft202012Validator

    schema = json.loads(
        (pathlib.Path(__file__).parents[1] / "schemas/ai/physical-command.schema.json")
        .read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)
    serializer = _serializer()
    messages = [
        Command("c-1", "robot1", "move_forward", {"distance": 1.0}, deadline=1_700_000_000.0),
        CancelCommandRequest("c-1"),
        CommandAcceptance("c-1", True, 1.0),
        CommandAcceptance("c-2", False, 1.0, Rejection(RejectionCode.UNIMPLEMENTED, "no")),
        CommandStatus("c-1", ExecutionStatus.EXECUTING, 1.0),
        CommandResult("c-1", ExecutionStatus.SUCCEEDED, 2.0, result={"distance_moved": 1.0}),
        CommandResult("c-2", ExecutionStatus.ABORTED, 2.0, failure=Failure("INTERNAL", "boom")),
        CancelCommandResponse("c-1", True),
        Capability("navigate.relative"),
    ]
    for message in messages:
        validator.validate(serializer.decode(serializer.encode(message)))

# -- 6. traceparent (2026-11-02 · 정본이 번호 6 을 정했다) ------------------

W3C_TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


def test_correlation_id_rides_the_wire_as_traceparent():
    """유효한 traceparent 는 번호 6 으로 실려 왕복한다. 손실 기록도 남지 않는다."""
    serializer = _serializer()
    command = Command(command_id="c-1", target="robot-01", action="move_forward",
                      correlation_id=W3C_TRACEPARENT)
    envelope = pb.PhysicalCommandEnvelope()
    envelope.ParseFromString(serializer.encode(command))
    assert envelope.command.traceparent == W3C_TRACEPARENT

    decoded = serializer.decode(serializer.encode(command), "command")
    assert decoded["payload"]["correlation_id"] == W3C_TRACEPARENT
    assert serializer.wire_gaps == {}


@pytest.mark.parametrize("value", [
    "not-a-traceparent",
    "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7",       # span 만 있고 flags 없음
    "00-" + "0" * 32 + "-00f067aa0ba902b7-01",                     # 전부 0 인 trace-id 는 무효
    "00-4bf92f3577b34da6a3ce929d0e0e4736-" + "0" * 16 + "-01",     # 전부 0 인 span-id 는 무효
    "00-4BF92F3577B34DA6A3CE929D0E0E4736-00F067AA0BA902B7-01",     # 대문자는 규격 밖
])
def test_malformed_correlation_id_is_not_put_on_the_wire(value):
    """형식이 아니면 싣지 않는다 — 받는 쪽의 trace 조립이 조용히 깨지기 때문이다.

    버리는 대신 `wire_gaps` 에 남기므로 운영 중에도 무엇이 잘렸는지 보인다.
    """
    serializer = _serializer()
    command = Command(command_id="c-2", target="robot-01", action="ping",
                      correlation_id=value)
    envelope = pb.PhysicalCommandEnvelope()
    envelope.ParseFromString(serializer.encode(command))
    assert envelope.command.traceparent == ""
    assert serializer.wire_gaps["command.correlation_id"] == 1


def test_absent_traceparent_does_not_become_an_empty_correlation_id():
    """빈 문자열은 "없음"이다. 상관 ID 칸을 만들지 않는다."""
    serializer = _serializer()
    command = Command(command_id="c-3", target="robot-01", action="ping")
    decoded = serializer.decode(serializer.encode(command), "command")
    assert "correlation_id" not in decoded["payload"]
    assert serializer.wire_gaps == {}


def test_descriptor_bytes_match_the_canonical_schema():
    """정본에서 생성한 descriptor 와 **바이트가 같다**.

    2026-11-02 통합 저장소가 `hardware/schema/physical_command.proto` 를 유일
    정본으로 정했다. 우리는 단독 생성·검증을 위해 사본을 두므로, 사본이 정본과
    같다는 사실을 번호 표(위 1절)와 이 지문으로 고정한다. 주석은 descriptor 에
    들어가지 않으므로 설명이 달라도 이 값은 변하지 않는다.
    """
    import hashlib

    fingerprint = hashlib.sha256(pb.DESCRIPTOR.serialized_pb).hexdigest()
    assert fingerprint == CANONICAL_DESCRIPTOR_SHA256, (
        "와이어 모양이 바뀌었다. 정본과 맞춘 변경이면 이 값을 갱신하고, "
        "아니면 필드를 되돌려라 — 사본이 먼저 어긋나면 로봇이 다른 메시지를 읽는다."
    )


# --- AI-C-18 선언 손실을 **항목 단위로** 센다 (spec §8-3 P7) ------------------


def test_a_declaration_that_says_cancel_is_not_supported_is_still_counted():
    """False 는 **선언된 값**이다. 조용히 사라지면 받는 쪽은 "취소 불가" 선언과
    미선언을 구분할 수 없다 — 그 둘을 가르는 것이 이번 변경의 전부다."""
    serializer = _serializer()
    serializer.encode(Capability(name="stop", cancel_supported=False, idempotent=False))
    assert serializer.wire_gaps["capability.cancel_supported"] == 1
    assert serializer.wire_gaps["capability.idempotent"] == 1


def test_an_unstated_item_is_not_counted_as_a_loss_because_there_was_nothing_to_lose():
    serializer = _serializer()
    serializer.encode(Capability(name="stop"))
    assert serializer.wire_gaps["capability.cancel_supported"] == 0
    assert serializer.wire_gaps["capability.idempotent"] == 0


def test_every_declaration_item_the_contract_owns_is_either_on_the_wire_or_counted():
    """목록을 손으로 적지 않는다. 계약에 필드를 더하고 이 경계를 잊으면 그
    항목만 조용히 사라지므로, 와이어가 싣는 셋을 뺀 **전부**를 센다."""
    from dataclasses import fields

    serializer = _serializer()
    declared = Capability(
        name="navigate.relative", version="1", parameter_schema="p", result_schema="r",
        cancel_supported=True, required_resources=("mobility.base",),
        optional_resources=("accel.npu",), idempotent=True, invocation="asynchronous",
        basis=DeclarationBasis(units={"distance_m": "m"}, reference_frame="device-local",
                               time_basis="backend_ntp"),
        scope_tags=("zone.a",), execution_profile_ref="profile://nav/1",
    )
    serializer.encode(declared)
    for f in fields(Capability):
        if f.name == "name":
            continue  # 와이어가 유일하게 싣는 칸
        assert serializer.wire_gaps[f"capability.{f.name}"] == 1, f.name


def test_a_decoded_announcement_names_every_item_it_could_not_carry():
    """빈 칸을 기본값으로 채우지 않는 대신 **이름으로** 남긴다. 그래야 받는
    쪽이 "장치가 그렇다고 선언했다" 와 "와이어에 자리가 없어 못 왔다" 를
    구분한다(AI-C-18)."""
    serializer = _serializer()
    decoded = serializer.decode(serializer.encode(Capability(name="stop")))
    items = decoded["payload"]["undeclared_items"]

    assert "cancellable" in items and "idempotent" in items
    assert "basis" in items and "scope" in items
    # 그 수가 곧 P7 의 크기다 — 항목마다 따로 센다.
    assert serializer.wire_gaps["capability.undeclared.cancellable"] == 1
    assert decoded["payload"]["declaration_scope"] == "actions_only"
