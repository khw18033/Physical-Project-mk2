"""implements: AI-R-02"""

from perception_framework.risk.path_evaluation import PathCandidate, PathCandidateRiskEvaluator
from perception_framework.risk.scoring import RuleBasedRiskScorer, maximum

WEIGHTS = {"proximity": 1.0}


def hazard_map(known: dict[tuple[float, float], dict[str, float]]) -> callable:
    def lookup(point: tuple[float, float]) -> dict[str, float]:
        return known.get(point, {})
    return lookup


def test_candidate_with_no_probe_points_is_zero_risk_zero_sufficiency():
    scorer = RuleBasedRiskScorer(WEIGHTS, aggregation=maximum)
    evaluator = PathCandidateRiskEvaluator(scorer.score, hazard_map({}))

    result = evaluator.evaluate(PathCandidate("c1", hazard_probe_points=()))

    assert result.max_risk == 0.0
    assert result.evidence_sufficiency == 0.0
    assert result.points_evaluated == 0


def test_worst_point_along_candidate_decides_max_risk():
    scorer = RuleBasedRiskScorer(WEIGHTS, aggregation=maximum)
    known = {
        (0.0, 0.0): {"proximity": 0.1},
        (1.0, 0.0): {"proximity": 0.9},
        (2.0, 0.0): {"proximity": 0.3},
    }
    evaluator = PathCandidateRiskEvaluator(scorer.score, hazard_map(known))

    result = evaluator.evaluate(
        PathCandidate("c1", hazard_probe_points=tuple(known.keys()))
    )

    assert result.max_risk == 0.9
    assert result.worst_point == (1.0, 0.0)
    assert result.points_evaluated == 3
    assert result.points_missing_evidence == 0


def test_points_with_no_hazard_evidence_are_never_fabricated_as_zero_risk():
    # AI-R-02: missing evidence must be reported as missing, not silently
    # treated as "safe" (0.0) -- so it must be excluded from the score
    # while still being counted so the caller can see the coverage gap.
    scorer = RuleBasedRiskScorer(WEIGHTS, aggregation=maximum)
    known = {(0.0, 0.0): {"proximity": 0.7}}
    evaluator = PathCandidateRiskEvaluator(scorer.score, hazard_map(known))

    result = evaluator.evaluate(
        PathCandidate("c1", hazard_probe_points=((0.0, 0.0), (5.0, 5.0)))
    )

    assert result.max_risk == 0.7
    assert result.points_evaluated == 1
    assert result.points_missing_evidence == 1


def test_two_candidates_are_scored_independently_never_ranked_by_this_module():
    # This module reports each candidate's own risk; picking a "better"
    # one is left to the caller (AI-C-19 keeps path selection out of AI).
    scorer = RuleBasedRiskScorer(WEIGHTS, aggregation=maximum)
    known = {(0.0, 0.0): {"proximity": 0.2}, (1.0, 1.0): {"proximity": 0.8}}
    evaluator = PathCandidateRiskEvaluator(scorer.score, hazard_map(known))

    safer = evaluator.evaluate(PathCandidate("safer", hazard_probe_points=((0.0, 0.0),)))
    riskier = evaluator.evaluate(PathCandidate("riskier", hazard_probe_points=((1.0, 1.0),)))

    assert safer.max_risk == 0.2
    assert riskier.max_risk == 0.8
    assert not hasattr(PathCandidateRiskEvaluator, "rank")
    assert not hasattr(PathCandidateRiskEvaluator, "select")
