"""tests for: AI-D-02"""

from ai_framework.decision.subtask import Subtask
from ai_framework.decision.validator import SubtaskValidator, ValidationContext


def make_ctx(**overrides):
    base = dict(
        known_zone_ids={"zone-a"},
        active_conditions=set(),
        known_facts={"zone_reachable:zone-a"},
        robot_resources={"battery_pct": 80},
    )
    base.update(overrides)
    return ValidationContext(**base)


def test_valid_subtask_passes():
    subtask = Subtask("s1", "zone-a", "inspect", 0, preconditions=("zone_reachable:zone-a",))

    result = SubtaskValidator().validate(subtask, make_ctx())

    assert result.executable is True
    assert result.reasons == ()


def test_unknown_zone_is_rejected():
    subtask = Subtask("s1", "zone-x", "inspect", 0)

    result = SubtaskValidator().validate(subtask, make_ctx())

    assert result.executable is False
    assert any("unknown_zone" in r for r in result.reasons)


def test_active_forbidden_condition_blocks_execution():
    subtask = Subtask("s1", "zone-a", "inspect", 0, forbidden_if=("flooded",))

    result = SubtaskValidator().validate(subtask, make_ctx(active_conditions={"flooded"}))

    assert result.executable is False


def test_insufficient_resource_blocks_execution():
    subtask = Subtask("s1", "zone-a", "inspect", 0, resource_requirements={"battery_pct": 90})

    result = SubtaskValidator().validate(subtask, make_ctx())

    assert result.executable is False
    assert any("resource_insufficient" in r for r in result.reasons)


def test_unconfirmed_precondition_marks_unexecutable_and_requests_evidence():
    subtask = Subtask("s1", "zone-a", "inspect", 0, preconditions=("target_confirmed",))

    result = SubtaskValidator().validate(subtask, make_ctx())

    assert result.executable is False
    assert result.missing_evidence == ("target_confirmed",)


def test_malformed_subtask_fails_schema_validation():
    subtask = Subtask("", "zone-a", "inspect", -1)

    result = SubtaskValidator().validate(subtask, make_ctx())

    assert result.executable is False
    assert any(r.startswith("schema:") for r in result.reasons)
