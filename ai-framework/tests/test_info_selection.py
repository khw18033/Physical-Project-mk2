"""tests for: AI-S-05"""

from ai_framework.contracts.profile import CompatibilityProfile, ResourceBudget
from ai_framework.perception.info_selection import AdditionalInfoSelector
from ai_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration


def make_registry(kinds):
    registry = CapabilityRegistry()
    for kind in kinds:
        registry.register_local(
            ProviderRegistration(
                capability_kind=kind, provider_id=f"{kind}-p", version="1", compatibility=CompatibilityProfile()
            )
        )
    return registry


def test_no_requests_when_evidence_already_sufficient():
    registry = make_registry(["perception.depth"])
    selector = AdditionalInfoSelector(registry)

    requests = selector.select_requests(
        {"perception.depth": 0.9},
        node_tags=set(),
        budget=ResourceBudget(10, 10),
        required_evidence_level=0.6,
        current_evidence_level=0.8,
    )

    assert requests == []


def test_never_requests_a_capability_kind_with_no_registered_provider():
    registry = make_registry(["perception.depth"])
    selector = AdditionalInfoSelector(registry)

    requests = selector.select_requests(
        {"perception.depth": 0.9, "perception.vlm": 0.99},
        node_tags=set(),
        budget=ResourceBudget(10, 10),
        required_evidence_level=0.9,
        current_evidence_level=0.1,
    )

    assert [r.capability_kind for r in requests] == ["perception.depth"]


def test_ranks_requests_by_expected_gain_descending():
    registry = make_registry(["perception.depth", "perception.reid"])
    selector = AdditionalInfoSelector(registry)

    requests = selector.select_requests(
        {"perception.depth": 0.3, "perception.reid": 0.9},
        node_tags=set(),
        budget=ResourceBudget(10, 10),
        required_evidence_level=0.9,
        current_evidence_level=0.1,
    )

    assert [r.capability_kind for r in requests] == ["perception.reid", "perception.depth"]
