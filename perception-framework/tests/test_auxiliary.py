"""implements: AI-E-04"""

from perception_framework.contracts.profile import CompatibilityProfile, ResourceBudget
from perception_framework.perception.auxiliary import AuxiliaryExecutionOrchestrator
from perception_framework.providers.fakes import StubAIRuntimeProvider
from perception_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration


def make_registry_and_runtimes(kinds):
    registry = CapabilityRegistry()
    runtimes = {}
    for kind in kinds:
        provider_id = f"{kind}-p"
        registry.register_local(
            ProviderRegistration(
                capability_kind=kind, provider_id=provider_id, version="1", compatibility=CompatibilityProfile()
            )
        )
        runtimes[provider_id] = StubAIRuntimeProvider((kind,), lambda k, x, kind=kind: f"result-of-{kind}")
    return registry, runtimes


def test_stops_immediately_once_evidence_check_is_satisfied():
    registry, runtimes = make_registry_and_runtimes(["aux.depth", "aux.vlm"])
    orchestrator = AuxiliaryExecutionOrchestrator(registry, runtimes)

    records = orchestrator.run_until_sufficient(
        ["aux.depth", "aux.vlm"],
        inputs={},
        node_tags=set(),
        budget=ResourceBudget(10, 10),
        evidence_check=lambda records: len(records) >= 1,  # sufficient after first run
    )

    assert [r.capability_kind for r in records] == ["aux.depth"]


def test_runs_all_candidates_when_evidence_never_becomes_sufficient():
    registry, runtimes = make_registry_and_runtimes(["aux.depth", "aux.vlm"])
    orchestrator = AuxiliaryExecutionOrchestrator(registry, runtimes)

    records = orchestrator.run_until_sufficient(
        ["aux.depth", "aux.vlm"],
        inputs={},
        node_tags=set(),
        budget=ResourceBudget(10, 10),
        evidence_check=lambda records: False,
    )

    assert [r.capability_kind for r in records] == ["aux.depth", "aux.vlm"]


def test_candidate_with_no_registered_provider_is_skipped_not_an_error():
    registry, runtimes = make_registry_and_runtimes(["aux.depth"])
    orchestrator = AuxiliaryExecutionOrchestrator(registry, runtimes)

    records = orchestrator.run_until_sufficient(
        ["aux.nonexistent", "aux.depth"],
        inputs={},
        node_tags=set(),
        budget=ResourceBudget(10, 10),
        evidence_check=lambda records: False,
    )

    assert [r.capability_kind for r in records] == ["aux.depth"]
