"""tests for: AI-D-01"""

from ai_framework.decision.subtask import SubtaskGenerator, ZoneRule


def test_generates_subtask_for_allowed_action_in_unrestricted_zone():
    generator = SubtaskGenerator()
    zone_rules = {"zone-a": ZoneRule("zone-a", allowed_actions=("inspect",))}

    subtasks = generator.generate(("inspect",), zone_rules, active_conditions=set())

    assert len(subtasks) == 1
    assert subtasks[0].zone_id == "zone-a"
    assert subtasks[0].action == "inspect"


def test_skips_zone_with_active_forbidden_condition():
    generator = SubtaskGenerator()
    zone_rules = {"zone-a": ZoneRule("zone-a", forbidden_conditions=("flooded",), allowed_actions=("inspect",))}

    subtasks = generator.generate(("inspect",), zone_rules, active_conditions={"flooded"})

    assert subtasks == []


def test_only_uses_actions_the_mission_actually_allows():
    generator = SubtaskGenerator()
    zone_rules = {"zone-a": ZoneRule("zone-a", allowed_actions=("inspect", "patrol"))}

    subtasks = generator.generate(("inspect",), zone_rules, active_conditions=set())

    assert [s.action for s in subtasks] == ["inspect"]


def test_zone_without_a_registered_rule_is_never_planned_for():
    generator = SubtaskGenerator()
    # "zone-b" has no ZoneRule entry at all -- must not be guessed at.
    zone_rules = {"zone-a": ZoneRule("zone-a", allowed_actions=("inspect",))}

    subtasks = generator.generate(("inspect",), zone_rules, active_conditions=set())

    assert all(s.zone_id != "zone-b" for s in subtasks)
