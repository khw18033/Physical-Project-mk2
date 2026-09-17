"""implements: AI-S-05, AI-S-03
tests: gain proxy per blind-spot cause, net-reward gate, deterministic
       ranking, only-worthwhile candidates become EvidenceNeeds, and the
       resulting needs flow through the existing AI-S-05 request pipeline
       without any capability-selection logic being duplicated here
"""

import pytest

from perception_framework.contracts.capability import CapabilityRequirement
from perception_framework.contracts.profile import CompatibilityProfile, ResourceBudget, ResourceCost
from perception_framework.decision.info_request import DecisionSupportRequester
from perception_framework.perception.coverage import BlindSpot, BlindSpotCause, ObservationState
from perception_framework.perception.reobservation_policy import (
    ReobservationCandidate, ReobservationPolicy, default_gain,
)
from perception_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration


def spot(region, cause, fraction=0.0, uncertainty=0.5):
    state = (
        ObservationState.UNOBSERVED if fraction <= 0.0
        else ObservationState.OBSERVED if fraction >= 0.95
        else ObservationState.PARTIALLY_OBSERVED
    )
    return BlindSpot(region, cause, state, fraction, uncertainty, last_observed_at=None)


# -- default_gain -----------------------------------------------------------

def test_no_source_gain_is_the_uncovered_share():
    assert default_gain(spot("z", BlindSpotCause.NO_SOURCE, fraction=0.0)) == 1.0
    assert default_gain(spot("z", BlindSpotCause.INCOMPLETE, fraction=0.7)) == pytest.approx(0.3)


def test_stranded_coverage_gain_is_what_was_lost_not_what_was_never_seen():
    """A region that was fully covered and then failed has more at stake
    than one that was always thin -- the opposite ordering from NO_SOURCE."""
    mostly_lost = default_gain(spot("z", BlindSpotCause.SOURCE_FAILURE, fraction=0.9))
    barely_lost = default_gain(spot("z", BlindSpotCause.OCCLUDED, fraction=0.1))
    assert mostly_lost > barely_lost


def test_stale_with_zero_fraction_still_has_nonzero_gain():
    # Defensive floor -- a STALE/OCCLUDED/SOURCE_FAILURE spot should never
    # be reported as "nothing to gain" purely because fraction rounded to 0.
    assert default_gain(spot("z", BlindSpotCause.STALE, fraction=0.0)) == 1.0


# -- net reward gate ----------------------------------------------------

def test_worth_requesting_is_a_strict_positive_reward():
    c = ReobservationCandidate("z", BlindSpotCause.NO_SOURCE, expected_gain=1.0, cost=1.0)
    assert c.net_reward == 0.0
    assert not c.worth_requesting  # ties do not trigger a request

    cheaper = ReobservationCandidate("z", BlindSpotCause.NO_SOURCE, expected_gain=1.0, cost=0.9)
    assert cheaper.worth_requesting


# -- rank() ---------------------------------------------------------------

def test_rank_orders_worth_requesting_first_then_by_net_reward():
    spots = [
        spot("cheap-win", BlindSpotCause.NO_SOURCE, fraction=0.0),   # gain 1.0
        spot("not-worth-it", BlindSpotCause.INCOMPLETE, fraction=0.9),  # gain 0.1
        spot("big-win", BlindSpotCause.SOURCE_FAILURE, fraction=0.95),  # gain 0.95
    ]
    policy = ReobservationPolicy()
    ranked = policy.rank(spots, cost_fn=lambda s: 0.2)

    # net reward: cheap-win 1.0-0.2=0.8, big-win 0.95-0.2=0.75, not-worth-it 0.1-0.2<0
    assert [c.region_id for c in ranked] == ["cheap-win", "big-win", "not-worth-it"]
    assert ranked[0].worth_requesting and ranked[1].worth_requesting
    assert not ranked[2].worth_requesting  # 0.1 gain - 0.2 cost <= 0


def test_rank_is_deterministic_on_ties():
    spots = [spot("b", BlindSpotCause.NO_SOURCE, 0.0), spot("a", BlindSpotCause.NO_SOURCE, 0.0)]
    policy = ReobservationPolicy()
    ranked = policy.rank(spots, cost_fn=lambda s: 0.0)
    assert [c.region_id for c in ranked] == ["a", "b"]


def test_custom_gain_fn_overrides_the_default():
    policy = ReobservationPolicy(gain_fn=lambda s: 42.0)
    ranked = policy.rank([spot("z", BlindSpotCause.STALE)], cost_fn=lambda s: 1.0)
    assert ranked[0].expected_gain == 42.0


# -- to_evidence_needs / end-to-end into AI-S-05's request pipeline --------

def test_only_worthwhile_candidates_become_evidence_needs():
    policy = ReobservationPolicy()
    candidates = policy.rank(
        [
            spot("worth-it", BlindSpotCause.NO_SOURCE, fraction=0.0),
            spot("not-worth-it", BlindSpotCause.INCOMPLETE, fraction=0.9),
        ],
        cost_fn=lambda s: 0.2,
    )
    needs = policy.to_evidence_needs(candidates, ("perception.reobserve",))
    assert [n.evidence_id for n in needs] == ["reobserve:worth-it"]
    assert needs[0].candidate_capability_kinds == ("perception.reobserve",)


def test_evidence_needs_flow_through_the_existing_request_pipeline():
    """Confirms the gate hands off cleanly into AI-S-05's existing machinery
    -- no capability selection is reimplemented in the policy itself."""
    registry = CapabilityRegistry()
    registry.register_local(ProviderRegistration(
        capability_kind="perception.reobserve",
        provider_id="ptz-turn",
        version="1",
        compatibility=CompatibilityProfile(cost=ResourceCost(compute_units=1)),
        requirement=CapabilityRequirement(),
    ))

    policy = ReobservationPolicy()
    candidates = policy.rank([spot("blocked-hallway", BlindSpotCause.OCCLUDED, fraction=0.8)],
                              cost_fn=lambda s: 0.1)
    needs = policy.to_evidence_needs(candidates, ("perception.reobserve",))

    plan = DecisionSupportRequester(registry).plan(
        needs, node_tags=set(), budget=ResourceBudget(compute_units=10, memory_mb=512),
    )
    assert plan.fully_supported
    assert plan.requests[0].provider_id == "ptz-turn"
    assert plan.requests[0].evidence_id == "reobserve:blocked-hallway"
