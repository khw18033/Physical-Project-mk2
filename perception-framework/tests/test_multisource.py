"""implements: AI-S-02, AI-C-11
tests: capability-gated evidence masking, single-source deployment, no-evidence fallback
"""

from perception_framework.perception.association import ObservedTrack
from perception_framework.perception.multisource import CrossSourceLinker

ALL = {"sync.time", "coordinates.global", "reid.embedding"}


def _pair():
    a = ObservedTrack("cam-a", 1, observed_at=10.0, global_position=(0.0, 0.0),
                      appearance_embedding=(1.0, 0.0, 0.0))
    b = ObservedTrack("cam-b", 7, observed_at=10.05, global_position=(0.2, 0.1),
                      appearance_embedding=(0.98, 0.05, 0.0))
    return [a, b]


def test_links_when_all_evidence_capabilities_are_registered():
    out = CrossSourceLinker().link(_pair(), ALL)
    assert out.usable_evidence == ("time", "space", "appearance")
    assert len(out.links) == 1
    assert set(out.links[0].basis) == {"time", "space", "appearance"}


def test_unregistered_capability_is_not_used_even_if_the_track_carries_the_value():
    out = CrossSourceLinker().link(_pair(), {"sync.time"})
    assert out.usable_evidence == ("time",)
    assert out.links and out.links[0].basis == ("time",)


def test_no_evidence_disables_linking_but_keeps_per_source_tracks():
    out = CrossSourceLinker().link(_pair(), set())
    assert out.links == ()
    assert out.association_active is False
    assert out.per_source_tracks == {"cam-a": (1,), "cam-b": (7,)}


def test_single_source_deployment_is_a_normal_configuration_not_an_error():
    tracks = [ObservedTrack("cam-a", 1, observed_at=1.0),
              ObservedTrack("cam-a", 2, observed_at=1.0)]
    out = CrossSourceLinker().link(tracks, ALL)
    assert out.links == ()
    assert out.same_source_pairs == 1
    assert out.per_source_tracks == {"cam-a": (1, 2)}


def test_per_source_tracks_are_identical_across_every_evidence_subset():
    tracks = _pair()
    baseline = CrossSourceLinker().link(tracks, ALL).per_source_tracks
    for subset in ({"sync.time"}, {"coordinates.global"}, {"reid.embedding"}, set()):
        assert CrossSourceLinker().link(tracks, subset).per_source_tracks == baseline
