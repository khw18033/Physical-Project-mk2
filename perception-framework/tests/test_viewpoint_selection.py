"""implements: AI-S-05, AI-S-03
tests: SCOUT ratio-score arithmetic, the qualitative claim that travel cost
       genuinely changes the ranking (not just "always highest gain" nor
       "always cheapest"), travel_cost <= 0 rejection, best() on an empty
       set is a normal degraded state (AI-C-05), and composition with
       reobservation_policy.ReobservationPolicy's already-gated output.
"""

import pytest

from perception_framework.perception.coverage import BlindSpot, BlindSpotCause, ObservationState
from perception_framework.perception.reobservation_policy import ReobservationPolicy
from perception_framework.perception.viewpoint_selection import (
    ViewpointCandidate, ViewpointRanking, ViewpointSelectionPolicy,
)


# -- basic ratio-math correctness -------------------------------------------

def test_rank_matches_hand_computed_scores_and_order():
    # score = (certainty_weight*certainty_gain + coverage_weight*coverage_gain) / travel_cost
    a = ViewpointCandidate("a", certainty_gain=2.0, coverage_gain=1.0, travel_cost=2.0)  # (2+1)/2 = 1.5
    b = ViewpointCandidate("b", certainty_gain=1.0, coverage_gain=1.0, travel_cost=1.0)  # (1+1)/1 = 2.0
    c = ViewpointCandidate("c", certainty_gain=4.0, coverage_gain=0.0, travel_cost=4.0)  # 4/4 = 1.0

    policy = ViewpointSelectionPolicy()
    ranked = policy.rank([a, b, c])

    assert ranked == [
        ViewpointRanking("b", 2.0),
        ViewpointRanking("a", 1.5),
        ViewpointRanking("c", 1.0),
    ]


def test_rank_honors_custom_weights():
    d = ViewpointCandidate("d", certainty_gain=1.0, coverage_gain=2.0, travel_cost=1.0)
    policy = ViewpointSelectionPolicy(certainty_weight=2.0, coverage_weight=0.5)
    ranked = policy.rank([d])
    # (2.0*1.0 + 0.5*2.0) / 1.0 = 3.0
    assert ranked[0].score == pytest.approx(3.0)


def test_rank_breaks_ties_by_region_id():
    x = ViewpointCandidate("x", certainty_gain=1.0, coverage_gain=0.0, travel_cost=1.0)
    y = ViewpointCandidate("y", certainty_gain=1.0, coverage_gain=0.0, travel_cost=1.0)
    ranked = ViewpointSelectionPolicy().rank([y, x])
    assert [r.region_id for r in ranked] == ["x", "y"]


# -- the qualitative claim: travel cost genuinely matters --------------------

def test_travel_cost_can_flip_the_ranking_in_either_direction(capsys):
    """SCOUT's actual point is that S_final is a *ratio*, not gain minus
    cost and not gain alone. Demonstrate both directions with the same
    'moderate' candidate: when the far candidate's cost dominates, the
    moderate-but-close one wins; when the far candidate's cost is only
    moderately higher, its much larger gain still wins.
    """
    moderate = ViewpointCandidate("moderate", certainty_gain=3.0, coverage_gain=0.0, travel_cost=1.0)
    policy = ViewpointSelectionPolicy()

    # Case 1: cost difference dominates -- moderate-but-close beats high-but-far.
    far_and_costly = ViewpointCandidate("far", certainty_gain=10.0, coverage_gain=0.0, travel_cost=20.0)
    ranked_1 = policy.rank([moderate, far_and_costly])
    scores_1 = {r.region_id: r.score for r in ranked_1}
    print(f"case 1 (cost dominates): moderate={scores_1['moderate']}, far={scores_1['far']}")
    assert scores_1["moderate"] == pytest.approx(3.0)
    assert scores_1["far"] == pytest.approx(0.5)
    assert ranked_1[0].region_id == "moderate"
    assert scores_1["moderate"] > scores_1["far"]  # travel cost mattered: gain alone would favor "far"

    # Case 2: the opposite -- high gain still wins despite a moderately higher cost.
    far_but_reachable = ViewpointCandidate("far", certainty_gain=10.0, coverage_gain=0.0, travel_cost=3.0)
    ranked_2 = policy.rank([moderate, far_but_reachable])
    scores_2 = {r.region_id: r.score for r in ranked_2}
    print(f"case 2 (gain dominates): moderate={scores_2['moderate']}, far={scores_2['far']}")
    assert scores_2["moderate"] == pytest.approx(3.0)
    assert scores_2["far"] == pytest.approx(10.0 / 3.0)
    assert ranked_2[0].region_id == "far"
    assert scores_2["far"] > scores_2["moderate"]  # not "always pick cheapest" either


# -- travel_cost validation --------------------------------------------------

@pytest.mark.parametrize("bad_cost", [0.0, -1.0])
def test_non_positive_travel_cost_raises(bad_cost):
    candidate = ViewpointCandidate("z", certainty_gain=1.0, coverage_gain=1.0, travel_cost=bad_cost)
    with pytest.raises(ValueError):
        ViewpointSelectionPolicy().rank([candidate])


# -- best() on empty input ----------------------------------------------------

def test_best_on_empty_candidates_returns_none_not_an_exception():
    assert ViewpointSelectionPolicy().best([]) is None


def test_best_returns_top_ranked_candidate():
    a = ViewpointCandidate("a", certainty_gain=1.0, coverage_gain=0.0, travel_cost=1.0)  # 1.0
    b = ViewpointCandidate("b", certainty_gain=5.0, coverage_gain=0.0, travel_cost=1.0)  # 5.0
    assert ViewpointSelectionPolicy().best([a, b]) == ViewpointRanking("b", 5.0)


# -- composition with reobservation_policy (no duplication) -----------------

def _spot(region, cause, fraction):
    state = (
        ObservationState.UNOBSERVED if fraction <= 0.0
        else ObservationState.OBSERVED if fraction >= 0.95
        else ObservationState.PARTIALLY_OBSERVED
    )
    return BlindSpot(region, cause, state, fraction, uncertainty=0.5, last_observed_at=None)


def test_composes_with_reobservation_policy_output():
    """Intended pipeline: ReobservationPolicy gates 'worth requesting at
    all' (no travel cost involved); ViewpointSelectionPolicy then ranks
    among the survivors by travel cost. Neither module recomputes the
    other's job.
    """
    blind_spots = [
        _spot("hallway-a", BlindSpotCause.NO_SOURCE, fraction=0.0),      # gain 1.0
        _spot("hallway-b", BlindSpotCause.SOURCE_FAILURE, fraction=0.9),  # gain 0.9
        _spot("hallway-c", BlindSpotCause.INCOMPLETE, fraction=0.9),      # gain 0.1, filtered out below
    ]
    reobs_policy = ReobservationPolicy()
    # Cost here is the reobservation-mechanism cost consumed by the net-reward
    # gate -- unrelated to travel cost used for viewpoint ranking below.
    reobs_candidates = reobs_policy.rank(blind_spots, cost_fn=lambda s: 0.2)
    worth_requesting = [c for c in reobs_candidates if c.worth_requesting]
    assert {c.region_id for c in worth_requesting} == {"hallway-a", "hallway-b"}

    # Made-up per-candidate travel costs, as this module requires from the caller.
    travel_costs = {"hallway-a": 5.0, "hallway-b": 1.0}
    viewpoint_candidates = [
        ViewpointCandidate(
            region_id=c.region_id,
            certainty_gain=c.expected_gain,
            coverage_gain=1.0 - _spot(c.region_id, c.cause, 0.0).observed_fraction,
            travel_cost=travel_costs[c.region_id],
        )
        for c in worth_requesting
    ]

    best = ViewpointSelectionPolicy().best(viewpoint_candidates)
    assert best is not None
    # hallway-a: (1.0 + 1.0)/5.0 = 0.4 ; hallway-b: (0.9 + 1.0)/1.0 = 1.9 -> hallway-b wins
    assert best.region_id == "hallway-b"
