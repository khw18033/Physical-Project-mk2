"""implements: AI-S-07
covers: purpose-defined required/preferred fields, per-purpose gap evaluation
"""

from perception_framework.perception.purpose_requirements import (
    PurposeRequirement,
    PurposeRequirementRegistry,
    evaluate_gap,
)


def test_same_object_can_be_sufficient_for_one_purpose_and_not_another():
    # AI-S-07: 동일 객체라도 목적마다 필요한 정보가 다르다.
    registry = PurposeRequirementRegistry()
    registry.register(PurposeRequirement("collision_avoidance", required_fields=("position", "extent")))
    registry.register(
        PurposeRequirement("asset_identification", required_fields=("position", "extent", "serial_number"))
    )

    available = {"position", "extent"}

    collision_gap = registry.evaluate("collision_avoidance", available)
    asset_gap = registry.evaluate("asset_identification", available)

    assert collision_gap.sufficient
    assert not asset_gap.sufficient
    assert asset_gap.missing_required == ("serial_number",)


def test_missing_preferred_field_alone_does_not_make_gap_insufficient():
    requirement = PurposeRequirement("risk_analysis", required_fields=("position",), preferred_fields=("velocity",))

    gap = evaluate_gap(requirement, {"position"})

    assert gap.sufficient
    assert gap.missing_preferred == ("velocity",)


def test_unregistered_purpose_returns_none_rather_than_guessing():
    registry = PurposeRequirementRegistry()

    assert registry.evaluate("unknown_purpose", {"position"}) is None


def test_evaluate_all_reports_every_registered_purpose_independently():
    registry = PurposeRequirementRegistry()
    registry.register(PurposeRequirement("a", required_fields=("x",)))
    registry.register(PurposeRequirement("b", required_fields=("y",)))

    gaps = registry.evaluate_all({"x"})

    by_purpose = {gap.purpose_id: gap for gap in gaps}
    assert by_purpose["a"].sufficient
    assert not by_purpose["b"].sufficient
