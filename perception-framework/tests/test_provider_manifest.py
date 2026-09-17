"""implements: AI-C-10, AI-C-18, AI-B-01, AI-B-09, AI-C-15
tests: manifest round-trip, required-key rejection, duplicate rejection,
unknown-key tolerance, register_all, example manifest == s11 scenario selection

`registry/manifest.py` turns a JSON manifest into `ProviderRegistration`s so a
provider is *registered* by editing a file, not a Python constant (AI-B-09:
"기존 핵심 코드를 수정하지 않고 어댑터와 capability 등록 정보만으로 연결").
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

from perception_framework.contracts.capability import CapabilityRequirement
from perception_framework.contracts.capability_contract import ExecutionProfile
from perception_framework.contracts.profile import CompatibilityProfile, ResourceBudget, ResourceCost
from perception_framework.registry.capability_registry import CapabilityRegistry
from perception_framework.registry.manifest import (
    ManifestError,
    ProviderManifest,
    load_provider_manifest,
    register_all,
    registrations_from_dict,
)
from perception_framework.selection.selector import CapabilitySelector

FRAMEWORK_DIR = Path(__file__).resolve().parents[1]
EXAMPLE_MANIFEST = FRAMEWORK_DIR / "config" / "providers.example.json"
S11_SCENARIO = FRAMEWORK_DIR / "simulator" / "scenarios" / "s11-door-detection-fusion.json"
SIMULATOR_DIR = FRAMEWORK_DIR / "simulator"


FULL_ENTRY = {
    "capability_kind": "perception.detect",
    "provider_id": "rpn-ondevice",
    "version": "1",
    "compatibility": {
        "required_hw_tags": ["cpu"],
        "preferred_hw_tags": ["compute.gpu"],
        "required_runtime_tags": ["runtime.onnx"],
        "cost": {"compute_units": 2.0, "memory_mb": 256, "max_latency_ms": 40.0},
        "priority": 1,
        "external_endpoints": ["inference.internal:8000"],
        "external_optional": False,
    },
    "requirement": {"required": ["media.video_input"], "optional": ["perception.classify"]},
    "supported_inputs": ["image"],
    "supported_outputs": ["region_proposal"],
    "execution_profile": {
        "implementation_ref": "rpn-ondevice@1",
        "runtime": "onnxruntime-cpu",
        "hardware_tags": ["cpu"],
        "input_profile": "640x480@5fps",
        "latency_ms": 31.5,
        "quality": {"recall_at_100": 0.62},
        "resources": {"memory_mb": 210.0},
        "evidence_ref": "bench/2026-09-16/rpn.json",
        "measured_at": 1758000000.0,
        "unmeasured_fields": ["throughput"],
    },
    "deployment": {"image": "registry.internal/rpn:1", "command": ["python", "-m", "rpn"]},
}


def _manifest(*entries: dict) -> ProviderManifest:
    return registrations_from_dict({"providers": [copy.deepcopy(e) for e in entries]})


# --- (a) round-trip --------------------------------------------------------


def test_every_field_round_trips_into_a_provider_registration():
    manifest = _manifest(FULL_ENTRY)

    assert len(manifest.registrations) == 1
    reg = manifest.registrations[0]
    assert reg.capability_kind == "perception.detect"
    assert reg.provider_id == "rpn-ondevice"
    assert reg.version == "1"
    assert reg.compatibility == CompatibilityProfile(
        required_hw_tags=("cpu",),
        preferred_hw_tags=("compute.gpu",),
        required_runtime_tags=("runtime.onnx",),
        cost=ResourceCost(compute_units=2.0, memory_mb=256.0, max_latency_ms=40.0),
        priority=1,
        external_endpoints=("inference.internal:8000",),
        external_optional=False,
    )
    assert reg.requirement == CapabilityRequirement(
        required=("media.video_input",), optional=("perception.classify",)
    )
    assert reg.supported_inputs == ("image",)
    assert reg.supported_outputs == ("region_proposal",)
    assert reg.execution_profile == ExecutionProfile(
        implementation_ref="rpn-ondevice@1",
        runtime="onnxruntime-cpu",
        hardware_tags=("cpu",),
        input_profile="640x480@5fps",
        latency_ms=31.5,
        quality={"recall_at_100": 0.62},
        resources={"memory_mb": 210.0},
        evidence_ref="bench/2026-09-16/rpn.json",
        measured_at=1758000000.0,
        unmeasured_fields=("throughput",),
    )
    # Callables and live health state cannot come from a static file.
    assert reg.health_check is None
    assert reg.runtime_instance is None
    assert reg.is_healthy() is True
    # `deployment` is passed through raw, keyed by provider_id.
    assert manifest.deployment_params == {
        "rpn-ondevice": {"image": "registry.internal/rpn:1", "command": ["python", "-m", "rpn"]}
    }
    assert manifest.base_dir is None


def test_minimal_entry_uses_the_dataclass_defaults():
    manifest = _manifest({"capability_kind": "perception.track", "provider_id": "t", "version": "2"})

    reg = manifest.registrations[0]
    assert reg.compatibility == CompatibilityProfile()
    assert reg.requirement == CapabilityRequirement()
    assert reg.supported_inputs == ()
    assert reg.supported_outputs == ()
    assert reg.execution_profile is None
    assert reg.runtime_instance is None
    assert reg.health_check is None
    # No deployment section -> in-process provider, nothing to hand to a ControlProvider.
    assert manifest.deployment_params == {}


def test_execution_profile_matches_conditions_after_loading():
    """The loaded profile must behave like a hand-built one for the selector's
    AI-B-01 evidence-reuse check (§4.3 invariant 3)."""
    reg = _manifest(FULL_ENTRY).registrations[0]

    assert reg.execution_profile.matches_conditions(
        runtime="onnxruntime-cpu", hardware_tags=("cpu",), input_profile="640x480@5fps"
    )
    assert not reg.execution_profile.matches_conditions(
        runtime="tensorrt", hardware_tags=("cpu",), input_profile="640x480@5fps"
    )


# --- (b) required keys -----------------------------------------------------


@pytest.mark.parametrize("missing_key", ["capability_kind", "provider_id", "version"])
def test_missing_required_key_names_the_entry_index_and_key(missing_key):
    ok = {"capability_kind": "perception.detect", "provider_id": "a", "version": "1"}
    bad = dict(ok)
    del bad[missing_key]

    with pytest.raises(ManifestError) as excinfo:
        _manifest(ok, bad)

    assert "providers[1]" in str(excinfo.value)
    assert missing_key in str(excinfo.value)


def test_execution_profile_section_requires_its_condition_fields():
    entry = copy.deepcopy(FULL_ENTRY)
    del entry["execution_profile"]["input_profile"]

    with pytest.raises(ManifestError) as excinfo:
        _manifest(entry)

    assert "providers[0].execution_profile" in str(excinfo.value)
    assert "input_profile" in str(excinfo.value)


def test_top_level_shape_is_validated():
    with pytest.raises(ManifestError):
        registrations_from_dict({"nope": []})
    with pytest.raises(ManifestError):
        registrations_from_dict({"providers": "not-a-list"})
    with pytest.raises(ManifestError) as excinfo:
        registrations_from_dict({"providers": [{"capability_kind": "x", "provider_id": "y", "version": "1"}, "junk"]})
    assert "providers[1]" in str(excinfo.value)


def test_list_fields_reject_a_bare_string():
    """A bare string must not be silently iterated into single characters."""
    entry = {"capability_kind": "x", "provider_id": "y", "version": "1", "supported_inputs": "image"}

    with pytest.raises(ManifestError) as excinfo:
        _manifest(entry)

    assert "providers[0].supported_inputs" in str(excinfo.value)


# --- (c) duplicates --------------------------------------------------------


def test_duplicate_kind_and_provider_id_is_rejected():
    entry = {"capability_kind": "perception.detect", "provider_id": "dup", "version": "1"}

    with pytest.raises(ManifestError) as excinfo:
        _manifest(entry, entry)

    assert "providers[1]" in str(excinfo.value)
    assert "dup" in str(excinfo.value)


def test_same_provider_id_under_two_kinds_is_allowed():
    """One process may serve two capability kinds; the identity is (kind, id)."""
    a = {"capability_kind": "perception.detect", "provider_id": "multi", "version": "1"}
    b = {"capability_kind": "perception.classify", "provider_id": "multi", "version": "1"}

    manifest = _manifest(a, b)

    assert [(r.capability_kind, r.provider_id) for r in manifest.registrations] == [
        ("perception.detect", "multi"),
        ("perception.classify", "multi"),
    ]


def test_same_provider_id_with_conflicting_deployment_sections_is_rejected():
    a = {"capability_kind": "perception.detect", "provider_id": "multi", "version": "1",
         "deployment": {"image": "img:1"}}
    b = {"capability_kind": "perception.classify", "provider_id": "multi", "version": "1",
         "deployment": {"image": "img:2"}}

    with pytest.raises(ManifestError):
        _manifest(a, b)


# --- (d) unknown keys ------------------------------------------------------


def test_unknown_keys_are_ignored_at_every_level():
    entry = copy.deepcopy(FULL_ENTRY)
    entry["vendor_note"] = "ignored"
    entry["compatibility"]["gpu_model"] = "ignored"
    entry["compatibility"]["cost"]["watts"] = 12
    entry["requirement"]["nice_to_have"] = ["ignored"]
    entry["execution_profile"]["operator"] = "ignored"

    reg = _manifest(entry).registrations[0]

    assert reg == _manifest(FULL_ENTRY).registrations[0]


# --- (e) register_all ------------------------------------------------------


def test_register_all_makes_every_entry_available_in_the_registry():
    manifest = _manifest(
        {"capability_kind": "perception.detect", "provider_id": "a", "version": "1"},
        {"capability_kind": "perception.detect", "provider_id": "b", "version": "1"},
        {"capability_kind": "perception.classify", "provider_id": "c", "version": "1"},
    )
    registry = CapabilityRegistry()

    register_all(manifest, registry)

    assert {r.provider_id for r in registry.available_providers("perception.detect")} == {"a", "b"}
    assert {r.provider_id for r in registry.available_providers("perception.classify")} == {"c"}
    assert registry.known_capability_kinds() == {"perception.detect", "perception.classify"}
    assert all(r.registered_at > 0 for r in registry.available_providers("perception.detect"))


# --- file loading ----------------------------------------------------------


def test_load_records_the_manifest_directory_and_rejects_bad_json(tmp_path):
    good = tmp_path / "providers.json"
    good.write_text(json.dumps({"providers": [FULL_ENTRY]}), encoding="utf-8")
    manifest = load_provider_manifest(good)
    assert manifest.base_dir == tmp_path
    # deployment values are passed through *raw* -- no path resolution.
    assert manifest.deployment_params["rpn-ondevice"]["image"] == "registry.internal/rpn:1"

    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ManifestError):
        load_provider_manifest(bad)


# --- (f) example manifest reproduces the s11 scenario ----------------------


@pytest.mark.skipif(not EXAMPLE_MANIFEST.exists(), reason="config/providers.example.json not present")
def test_example_manifest_loads_six_providers():
    manifest = load_provider_manifest(EXAMPLE_MANIFEST)

    assert len(manifest.registrations) == 6
    assert manifest.deployment_params == {}  # all in-process today


@pytest.mark.skipif(
    not (EXAMPLE_MANIFEST.exists() and S11_SCENARIO.exists()),
    reason="example manifest or s11 scenario not present",
)
def test_example_manifest_selects_the_same_providers_as_the_s11_scenario():
    """The scenario registers its providers via `simulator/devs/common.py::
    build_registration` (Python dicts); the manifest registers the same ones
    from JSON. `CapabilitySelector` must not be able to tell the difference
    for any capability kind the scenario declares."""
    if str(SIMULATOR_DIR) not in sys.path:
        sys.path.insert(0, str(SIMULATOR_DIR))
    from devs.common import HealthBoard, build_registration  # noqa: E402

    scenario = json.loads(S11_SCENARIO.read_text(encoding="utf-8"))
    node = scenario["nodes"][0]
    node_tags = set(node["profile"]["node_tags"])
    budget = ResourceBudget(**node["budget"])

    scenario_registry = CapabilityRegistry()
    for entry in node["providers"]:
        scenario_registry.register_local(build_registration(entry, HealthBoard()))

    manifest_registry = CapabilityRegistry()
    register_all(load_provider_manifest(EXAMPLE_MANIFEST), manifest_registry)

    scenario_selector = CapabilitySelector(scenario_registry)
    manifest_selector = CapabilitySelector(manifest_registry)
    for kind in node["profile"]["active_capability_kinds"]:
        expected = scenario_selector.select(kind, node_tags, budget)
        actual = manifest_selector.select(kind, node_tags, budget)
        assert expected.provider is not None, kind
        assert actual.provider is not None, kind
        assert actual.provider.provider_id == expected.provider.provider_id, kind
        assert actual.provider.compatibility == expected.provider.compatibility, kind
        assert actual.provider.requirement == expected.provider.requirement, kind
