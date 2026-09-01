"""implements: AI-R-02"""

from perception_framework.risk.scoring import RuleBasedRiskScorer


def test_all_inputs_present_gives_full_evidence_sufficiency():
    scorer = RuleBasedRiskScorer({"water_level": 0.6, "flow_rate": 0.4})

    result = scorer.score({"water_level": 0.8, "flow_rate": 0.2})

    assert result.evidence_sufficiency == 1.0
    assert result.inputs_used == ("water_level", "flow_rate")


def test_missing_one_input_lowers_sufficiency_without_fabricating_it():
    scorer = RuleBasedRiskScorer({"water_level": 0.6, "flow_rate": 0.4})

    result = scorer.score({"water_level": 0.8})

    assert result.evidence_sufficiency == 0.6
    assert result.inputs_used == ("water_level",)
    assert result.level == 0.8  # only the present input contributes


def test_no_inputs_present_returns_zero_without_crashing():
    scorer = RuleBasedRiskScorer({"water_level": 0.6, "flow_rate": 0.4})

    result = scorer.score({})

    assert result.level == 0.0
    assert result.evidence_sufficiency == 0.0
    assert result.inputs_used == ()
