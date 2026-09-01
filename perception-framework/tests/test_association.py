"""implements: AI-S-02"""

import pytest

from perception_framework.perception.association import MultiObservationAssociator, ObservedTrack


def test_links_using_appearance_only_when_time_and_space_absent():
    associator = MultiObservationAssociator()
    a = ObservedTrack("cam-1", 1, appearance_embedding=(1.0, 0.0, 0.0))
    b = ObservedTrack("cam-2", 5, appearance_embedding=(0.99, 0.01, 0.0))

    result = associator.associate(a, b)

    assert result.linked is True
    assert result.basis == ("appearance",)


def test_no_shared_evidence_at_all_does_not_link_or_crash():
    associator = MultiObservationAssociator()
    a = ObservedTrack("cam-1", 1)
    b = ObservedTrack("cam-2", 5)

    result = associator.associate(a, b)

    assert result.linked is False
    assert result.basis == ()


def test_uses_whatever_subset_of_signals_is_actually_present():
    associator = MultiObservationAssociator()
    a = ObservedTrack("cam-1", 1, observed_at=10.0, global_position=(0.0, 0.0))
    b = ObservedTrack("cam-2", 2, observed_at=10.1, global_position=(0.5, 0.5))
    # no appearance embedding on either side -> must still evaluate on time+space

    result = associator.associate(a, b)

    assert set(result.basis) == {"time", "space"}
    assert result.linked is True


def test_same_source_association_is_rejected():
    associator = MultiObservationAssociator()
    a = ObservedTrack("cam-1", 1)
    b = ObservedTrack("cam-1", 2)

    with pytest.raises(ValueError):
        associator.associate(a, b)
