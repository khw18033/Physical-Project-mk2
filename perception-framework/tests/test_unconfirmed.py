"""implements: AI-S-04"""

from perception_framework.perception.unconfirmed import CandidateStatus, UnconfirmedCandidateRegistry


def test_new_candidate_stays_unconfirmed_and_keeps_observation_history():
    registry = UnconfirmedCandidateRegistry()

    registry.register_observation("c1", {"frame": 1, "box": (0, 0, 10, 10)})
    registry.register_observation("c1", {"frame": 2, "box": (1, 1, 11, 11)})

    candidate = registry.get("c1")
    assert candidate.status == CandidateStatus.UNCONFIRMED
    assert len(candidate.raw_observations) == 2


def test_confirmation_requires_explicit_call_and_preserves_history():
    registry = UnconfirmedCandidateRegistry()
    registry.register_observation("c1", {"frame": 1})

    confirmed = registry.confirm("c1", label="debris", evidence={"user_ack": True})

    assert confirmed.status == CandidateStatus.CONFIRMED
    assert confirmed.confirmed_label == "debris"
    assert len(confirmed.raw_observations) == 2  # original + confirmation evidence


def test_unconfirmed_candidate_is_never_auto_mapped_to_an_existing_class():
    registry = UnconfirmedCandidateRegistry()
    registry.register_observation("c1", {"frame": 1})

    candidate = registry.get("c1")

    assert candidate.confirmed_label is None


def test_zero_shot_hint_does_not_confirm_the_candidate():
    registry = UnconfirmedCandidateRegistry()
    registry.register_observation("c1", {"frame": 1, "box": (0, 0, 10, 10)})

    candidate = registry.add_zero_shot_hint(
        "c1",
        label="fallen traffic cone",
        confidence=0.62,
        provider_id="open-vocabulary-edge",
        prompt="objects that should be removed from the walkway",
    )

    assert candidate.status == CandidateStatus.UNCONFIRMED
    assert candidate.confirmed_label is None
    assert candidate.zero_shot_hints[0].label == "fallen traffic cone"
