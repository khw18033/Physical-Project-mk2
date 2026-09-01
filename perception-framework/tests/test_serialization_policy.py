"""Wire-format substitutability and boundary policy.

implements: AI-C-07, AI-C-04, AI-C-12
tests: binary round-trip, cross-format semantic equivalence, serializer swap
       leaves the transport path identical, policy is deployment config,
       new format registration touches no business code
"""
import json

import pytest

from perception_framework.integration.wire import publish_message
from perception_framework.providers.adapters import SerializerProvider
from perception_framework.providers.fakes import InMemoryTransportProvider, JsonSerializerProvider
from perception_framework.providers.serialization import (
    CompactBinarySerializerProvider,
    SerializationPolicy,
    available_formats,
    build_serializer,
    load_policy_from_profile,
    register_serializer,
)
from perception_framework.risk.output import RiskJudgmentPublisher
from perception_framework.simulation.terminals import VirtualRobotTerminal

ALL_FORMATS = ["json", "compact_binary_v1"]

MESSAGES = [
    {},
    {"a": 1, "b": -2, "c": 0},
    {"nested": {"list": [1, 2.5, "x", None, True, False]}},
    {"unicode": "하천 위험 ALERT", "empty_list": [], "empty_dict": {}},
    {"big_int": 2**62 - 1, "neg": -(2**62), "float": 1.7976931348623157e308},
    {"bytes": b"\x00\xff\xfe"},
    [1, [2, [3, [4]]]],
    "bare string",
    None,
]


@pytest.mark.parametrize("fmt", ALL_FORMATS)
@pytest.mark.parametrize("obj", MESSAGES)
def test_every_registered_format_round_trips(fmt, obj):
    serializer = build_serializer(fmt)
    payload = serializer.encode(obj)
    assert isinstance(payload, bytes)
    decoded = serializer.decode(payload)
    if fmt == "json" and isinstance(obj, dict) and "bytes" in obj:
        # Documented format limit, not a defect: JSON has no bytes type, so
        # the `default=str` fallback stringifies it. A deployment carrying
        # raw bytes must therefore not map that boundary to "json" — which
        # is precisely the kind of decision AI-C-07 puts in configuration.
        assert decoded["bytes"] == str(obj["bytes"])
        return
    assert decoded == obj


@pytest.mark.parametrize("obj", [m for m in MESSAGES if not (isinstance(m, dict) and "bytes" in m)])
def test_formats_agree_on_meaning(obj):
    """AI-C-07: if two formats disagreed about what a message means, upper
    layers could tell them apart and substitution would not be real."""
    results = [build_serializer(f).decode(build_serializer(f).encode(obj)) for f in ALL_FORMATS]
    assert all(r == results[0] for r in results)


def test_binary_format_actually_produces_bytes_not_text():
    serializer = CompactBinarySerializerProvider()
    payload = serializer.encode({"risk_state": "ALERT", "risk_level": 0.91})
    assert isinstance(payload, bytes)
    with pytest.raises(UnicodeDecodeError):
        # Genuinely binary: tag/varint bytes are not valid UTF-8 text.
        payload.decode("utf-8")


@pytest.mark.parametrize("payload", [b"", b"\x99", b"\x05\x10ab", b"\x03", b"\x00\x00"])
def test_binary_decoder_rejects_corrupt_payloads(payload):
    with pytest.raises(ValueError):
        CompactBinarySerializerProvider().decode(payload)


@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_both_formats_satisfy_the_serializer_protocol(fmt):
    assert isinstance(build_serializer(fmt), SerializerProvider)


# --- swapping the serializer must not change the transport path -----------

@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_risk_publisher_is_unchanged_by_the_wire_format(fmt):
    """Same business code, same topic, same delivered meaning — only the
    bytes differ (AI-C-07)."""
    serializer = build_serializer(fmt)
    transport = InMemoryTransportProvider()
    received = []
    transport.subscribe("risk/zone-1", received.append)

    publisher = RiskJudgmentPublisher(serializer, transport, topic="risk/zone-1")
    from perception_framework.risk.output import RiskJudgment

    judgment = RiskJudgment(
        risk_state="ALERT",
        risk_level=0.8,
        evidence_sufficiency=0.5,
        evidence_used=("water_level",),
        model_version="rule-based-v1",
        recommendation="notify_operator",
    )
    publisher.publish(judgment)

    assert len(received) == 1
    decoded = serializer.decode(received[0])
    assert decoded["risk_state"] == "ALERT"
    assert decoded["risk_level"] == 0.8
    assert decoded["recommendation"] == "notify_operator"


@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_publish_message_helper_is_unchanged_by_the_wire_format(fmt):
    serializer = build_serializer(fmt)
    transport = InMemoryTransportProvider()
    received = []
    transport.subscribe("ai/risk/zone-a", received.append)
    message = {"zone_id": "zone-a", "risk_level": 0.42}
    publish_message(message, serializer, transport, "ai/risk/zone-a")
    assert serializer.decode(received[0]) == message


@pytest.mark.parametrize("fmt", ALL_FORMATS)
def test_terminal_command_path_works_under_either_format(fmt):
    """The 말단 command/result loop (AI-B-03) is format-blind: injecting a
    different SerializerProvider changes no terminal code."""
    serializer = build_serializer(fmt)
    transport = InMemoryTransportProvider()
    robot = VirtualRobotTerminal("virtual_robot_01", transport, serializer=serializer)
    robot.start()
    results = []
    transport.subscribe(robot.result_topic, results.append)

    transport.publish(
        robot.command_topic,
        serializer.encode({"command_id": "c1", "command": "START_TASK",
                           "params": {"target": [3.0, 4.0]}}),
    )

    outcomes = [serializer.decode(p)["outcome"] for p in results]
    assert outcomes == ["RECEIVED", "SUCCESS"]
    assert robot.state.get("position") == (3.0, 4.0)


def test_a_terminal_observation_survives_a_format_swap_identically():
    payloads = {}
    for fmt in ALL_FORMATS:
        serializer = build_serializer(fmt)
        transport = InMemoryTransportProvider()
        robot = VirtualRobotTerminal("t1", transport, serializer=serializer)
        robot.publish_observation("water_level_m", 3.25)
        payloads[fmt] = serializer.decode(transport.published[0][1])

    reference = payloads[ALL_FORMATS[0]]
    for fmt in ALL_FORMATS:
        # frame_id/observed_at differ per call; compare the stable fields.
        assert payloads[fmt]["terminal_id"] == reference["terminal_id"]
        assert payloads[fmt]["name"] == reference["name"]
        assert payloads[fmt]["value"] == reference["value"]


# --- the policy, not the caller, picks the format -------------------------

def test_default_policy_follows_the_requirements_boundary_split():
    """AI-C-07: 기계 간 통신은 크기·처리속도, 사람이 확인하는 경계는 가독성."""
    policy = SerializationPolicy.default()
    assert policy.format_for("edge_to_server") == "compact_binary_v1"
    assert policy.format_for("terminal_to_edge") == "compact_binary_v1"
    assert policy.format_for("operator_view") == "json"
    assert policy.format_for("diagnostics") == "json"


def test_human_boundary_output_is_actually_human_readable():
    serializer = SerializationPolicy.default().serializer_for("operator_view")
    text = serializer.encode({"risk_state": "ALERT"}).decode("utf-8")
    assert json.loads(text) == {"risk_state": "ALERT"}


def test_unknown_boundary_falls_back_to_the_default_format():
    policy = SerializationPolicy.default()
    assert policy.format_for("some_future_boundary") == "json"


def test_policy_comes_from_deployment_config_not_code():
    policy = SerializationPolicy.from_config(
        {"default_format": "json", "by_boundary": {"edge_to_server": "json"}}
    )
    assert policy.format_for("edge_to_server") == "json"
    # unspecified boundaries keep the default mapping
    assert policy.format_for("terminal_to_edge") == "compact_binary_v1"


def test_absent_config_still_yields_a_working_policy():
    assert SerializationPolicy.from_config(None).by_boundary == SerializationPolicy.default().by_boundary
    assert SerializationPolicy.from_config({}).format_for("control") == "compact_binary_v1"


def test_profile_file_supplies_the_policy():
    policy = load_policy_from_profile("profiles/robot.json")
    assert isinstance(policy.serializer_for("edge_to_server"), SerializerProvider)


def test_policy_rejects_an_unregistered_format_at_config_time():
    """AI-C-16: a bad procurement/config decision must surface before
    deployment, not as a runtime encode failure."""
    with pytest.raises(KeyError):
        SerializationPolicy.from_config({"by_boundary": {"control": "protobuf_v9"}})


def test_a_new_format_is_added_by_registration_only():
    """AI-C-04/AI-C-12: adding a wire format touches no business module."""

    class UpperJsonSerializer:
        def encode(self, obj):
            return json.dumps(obj).upper().encode()

        def decode(self, payload, schema_hint=None):
            return json.loads(payload.decode().lower())

    register_serializer("test_upper_json", UpperJsonSerializer)
    try:
        assert "test_upper_json" in available_formats()
        policy = SerializationPolicy.from_config(
            {"by_boundary": {"edge_to_server": "test_upper_json"}}
        )
        transport = InMemoryTransportProvider()
        received = []
        transport.subscribe("t", received.append)
        serializer = policy.serializer_for("edge_to_server")
        publish_message({"a": 1}, serializer, transport, "t")
        assert serializer.decode(received[0]) == {"a": 1}
    finally:
        from perception_framework.providers import serialization

        serialization._REGISTRY.pop("test_upper_json", None)


def test_json_provider_is_still_reachable_under_its_original_name():
    assert isinstance(build_serializer("json"), JsonSerializerProvider)
