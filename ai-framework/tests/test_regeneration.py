"""tests for: AI-D-04"""

from ai_framework.decision.regeneration import RegenerationEvaluator, RegenerationScope


def test_blocking_event_triggers_zone_subtask_regeneration():
    decision = RegenerationEvaluator().evaluate("path_blocked")

    assert decision.scope == RegenerationScope.ZONE_SUBTASK


def test_mission_level_event_requests_backend_change():
    decision = RegenerationEvaluator().evaluate("mission_conflict")

    assert decision.scope == RegenerationScope.MISSION_BACKEND


def test_mere_observation_change_does_not_trigger_regeneration():
    decision = RegenerationEvaluator().evaluate("minor_position_update")

    assert decision.scope == RegenerationScope.NONE
