"""Provider manifest: a JSON file → `ProviderRegistration` loader.

implements: AI-C-10, AI-C-18, AI-B-01, AI-B-09, AI-C-15

AI-B-09: "새로운 센서, 하드웨어, AI 기능, 모델, 런타임 또는 외부 서비스 제공자가
추가되면 기존 핵심 코드를 수정하지 않고 어댑터와 capability 등록 정보만으로 연결할
수 있어야 한다." Until now the *registration* half of that sentence was a Python
constant: `edge/model_config.py` builds provider *objects* from a config file,
but which capability kind / cost / priority / requirement each one is registered
under still lived in code (or in a simulator scenario). This module closes that
gap (docs/ai/design/capability-ui-orchestration-plan.md §4 P3): a manifest file
carries the same fields `ProviderRegistration` has, so adding or re-costing a
provider is an edit to `config/providers*.json`, never to `registry/` or to the
provider's own module.

Design notes:

- JSON, not YAML — same reason as `edge/model_config.py` and
  `contracts/profile_loader.py`: no new third-party dependency.
- 필수 누락만 거부, 알 수 없는 필드는 통과. Only `capability_kind`, `provider_id`
  and `version` are mandatory; every other field defaults exactly like the
  dataclass it feeds, and unknown keys are ignored so a manifest written for a
  newer loader still registers on an older one (same philosophy as the backend
  contract schemas). This is deliberately the opposite of `profile_loader.py`,
  which rejects unknown keys: a typo there silently deactivates a capability,
  whereas a typo here merely leaves a default in place and the registration
  still shows up in `available_providers`.
- No paths are resolved. A registration carries no file paths, and the loader
  does not guess which strings inside `deployment` are paths — it records the
  manifest's own directory on the result (`ProviderManifest.base_dir`) so the
  eventual consumer of `deployment` (a ControlProvider `start`, P4) can resolve
  relative entries against the file that declared them, the way
  `edge/model_config.py` does for its known keys.
- `health_check` and `runtime_instance` are never populated from a manifest:
  the first is a callable, the second is *live* health state (KServe
  live/ready 패턴 — "지금 응답 가능한가"), and neither belongs in a static file.
  They stay `None`, which every consumer already treats as "unknown, not
  excluded" (AI-C-18: 모든 항목이 항상 존재한다고 가정하지 않는다).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from perception_framework.contracts.capability import CapabilityRequirement
from perception_framework.contracts.capability_contract import ExecutionProfile
from perception_framework.contracts.profile import CompatibilityProfile, ResourceCost
from perception_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration

_REQUIRED_ENTRY_KEYS = ("capability_kind", "provider_id", "version")
_REQUIRED_EXECUTION_PROFILE_KEYS = ("implementation_ref", "runtime", "hardware_tags", "input_profile")


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class ProviderManifest:
    """Everything one manifest file declared, already turned into contracts.

    `deployment_params` maps provider_id → the entry's raw `deployment` section
    (e.g. `{"image": ..., "command": [...]}`), passed through untouched. It is
    what a ControlProvider `start` receives later; providers that run
    in-process simply omit it and do not appear here.
    """

    registrations: tuple[ProviderRegistration, ...]
    deployment_params: dict[str, dict] = field(default_factory=dict)
    base_dir: Path | None = None


def load_provider_manifest(path: str | Path) -> ProviderManifest:
    """Read a manifest file. Relative `deployment` entries are *not* resolved
    here (see module docstring); the file's directory is recorded instead."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ManifestError(f"{path}: not valid JSON: {error}") from error
    return registrations_from_dict(raw, base_dir=path.parent)


def registrations_from_dict(data: dict, *, base_dir: Path | None = None) -> ProviderManifest:
    """Pure conversion of an already-parsed manifest object; tests use it
    without touching the filesystem."""
    if not isinstance(data, dict):
        raise ManifestError(f"manifest must be a JSON object, got {type(data).__name__}")
    entries = data.get("providers")
    if not isinstance(entries, list):
        raise ManifestError("manifest must have a top-level 'providers' list")

    registrations: list[ProviderRegistration] = []
    deployment_params: dict[str, dict] = {}
    seen: set[tuple[str, str]] = set()

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ManifestError(f"providers[{index}]: entry must be a JSON object")
        missing = [key for key in _REQUIRED_ENTRY_KEYS if key not in entry]
        if missing:
            raise ManifestError(f"providers[{index}]: missing required key(s) {missing}")

        reg = _registration_from_entry(index, entry)
        identity = (reg.capability_kind, reg.provider_id)
        if identity in seen:
            raise ManifestError(
                f"providers[{index}]: duplicate provider {reg.provider_id!r} for capability "
                f"{reg.capability_kind!r}"
            )
        seen.add(identity)
        registrations.append(reg)

        deployment = entry.get("deployment")
        if deployment is not None:
            if not isinstance(deployment, dict):
                raise ManifestError(f"providers[{index}].deployment: must be a JSON object")
            previous = deployment_params.get(reg.provider_id)
            if previous is not None and previous != deployment:
                # Same provider_id under two capability kinds is allowed, but
                # they must agree on how the provider is started — one
                # process, one deployment section.
                raise ManifestError(
                    f"providers[{index}]: provider {reg.provider_id!r} declares a 'deployment' "
                    "section that differs from an earlier entry with the same provider_id"
                )
            deployment_params[reg.provider_id] = deployment

    return ProviderManifest(
        registrations=tuple(registrations),
        deployment_params=deployment_params,
        base_dir=base_dir,
    )


def register_all(manifest: ProviderManifest, registry: CapabilityRegistry) -> None:
    """Register every manifest entry as a *local* provider (this node hosts
    it — the authoritative layer of `CapabilityRegistry`)."""
    for reg in manifest.registrations:
        registry.register_local(reg)


# --- per-entry conversion ---------------------------------------------------


def _registration_from_entry(index: int, entry: dict) -> ProviderRegistration:
    where = f"providers[{index}]"
    execution_profile = entry.get("execution_profile")
    return ProviderRegistration(
        capability_kind=_non_empty_str(where, "capability_kind", entry["capability_kind"]),
        provider_id=_non_empty_str(where, "provider_id", entry["provider_id"]),
        version=_non_empty_str(where, "version", entry["version"]),
        compatibility=_compatibility_from(where, entry.get("compatibility", {})),
        requirement=_requirement_from(where, entry.get("requirement", {})),
        supported_inputs=_str_tuple(where, "supported_inputs", entry.get("supported_inputs", ())),
        supported_outputs=_str_tuple(where, "supported_outputs", entry.get("supported_outputs", ())),
        health_check=None,
        execution_profile=(
            None if execution_profile is None else _execution_profile_from(where, execution_profile)
        ),
        runtime_instance=None,
    )


def _compatibility_from(where: str, raw: Any) -> CompatibilityProfile:
    where = f"{where}.compatibility"
    raw = _object(where, raw)
    defaults = CompatibilityProfile()
    return CompatibilityProfile(
        required_hw_tags=_str_tuple(where, "required_hw_tags", raw.get("required_hw_tags", ())),
        preferred_hw_tags=_str_tuple(where, "preferred_hw_tags", raw.get("preferred_hw_tags", ())),
        required_runtime_tags=_str_tuple(
            where, "required_runtime_tags", raw.get("required_runtime_tags", ())
        ),
        cost=_cost_from(where, raw.get("cost", {})),
        priority=_int(where, "priority", raw.get("priority", defaults.priority)),
        external_endpoints=_str_tuple(where, "external_endpoints", raw.get("external_endpoints", ())),
        external_optional=bool(raw.get("external_optional", defaults.external_optional)),
    )


def _cost_from(where: str, raw: Any) -> ResourceCost:
    where = f"{where}.cost"
    raw = _object(where, raw)
    defaults = ResourceCost()
    return ResourceCost(
        compute_units=_number(where, "compute_units", raw.get("compute_units", defaults.compute_units)),
        memory_mb=_number(where, "memory_mb", raw.get("memory_mb", defaults.memory_mb)),
        max_latency_ms=_optional_number(where, "max_latency_ms", raw.get("max_latency_ms")),
    )


def _requirement_from(where: str, raw: Any) -> CapabilityRequirement:
    where = f"{where}.requirement"
    raw = _object(where, raw)
    return CapabilityRequirement(
        required=_str_tuple(where, "required", raw.get("required", ())),
        optional=_str_tuple(where, "optional", raw.get("optional", ())),
    )


def _execution_profile_from(where: str, raw: Any) -> ExecutionProfile:
    """`ExecutionProfile` has four positional fields with no defaults
    (implementation_ref/runtime/hardware_tags/input_profile — the *conditions*
    a measurement is only valid under, AI-B-01). If the section is present at
    all those are required; every measured value stays optional and
    `unmeasured_fields` is passed through so a manifest can say which numbers
    it does not have (AI-B-01: 미측정 항목은 구분해야 한다)."""
    where = f"{where}.execution_profile"
    raw = _object(where, raw)
    missing = [key for key in _REQUIRED_EXECUTION_PROFILE_KEYS if key not in raw]
    if missing:
        raise ManifestError(f"{where}: missing required key(s) {missing}")
    return ExecutionProfile(
        implementation_ref=_non_empty_str(where, "implementation_ref", raw["implementation_ref"]),
        runtime=_non_empty_str(where, "runtime", raw["runtime"]),
        hardware_tags=_str_tuple(where, "hardware_tags", raw["hardware_tags"]),
        input_profile=_non_empty_str(where, "input_profile", raw["input_profile"]),
        latency_ms=_optional_number(where, "latency_ms", raw.get("latency_ms")),
        quality=_number_map(where, "quality", raw.get("quality", {})),
        resources=_number_map(where, "resources", raw.get("resources", {})),
        evidence_ref=_optional_str(where, "evidence_ref", raw.get("evidence_ref")),
        measured_at=_optional_number(where, "measured_at", raw.get("measured_at")),
        unmeasured_fields=_str_tuple(where, "unmeasured_fields", raw.get("unmeasured_fields", ())),
    )


# --- small typed accessors (every failure names the entry and key) ----------


def _object(where: str, value: Any) -> dict:
    if not isinstance(value, dict):
        raise ManifestError(f"{where}: must be a JSON object, got {type(value).__name__}")
    return value


def _non_empty_str(where: str, key: str, value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ManifestError(f"{where}.{key}: must be a string, got {type(value).__name__}")
    text = str(value)
    if not text:
        raise ManifestError(f"{where}.{key}: must not be empty")
    return text


def _optional_str(where: str, key: str, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ManifestError(f"{where}.{key}: must be a string or null, got {type(value).__name__}")
    return value


def _str_tuple(where: str, key: str, value: Any) -> tuple[str, ...]:
    # A bare string is rejected rather than iterated character by character.
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ManifestError(f"{where}.{key}: must be a list of strings")
    for item in value:
        if not isinstance(item, str):
            raise ManifestError(f"{where}.{key}: must be a list of strings, found {item!r}")
    return tuple(value)


def _number(where: str, key: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManifestError(f"{where}.{key}: must be a number, got {type(value).__name__}")
    return float(value)


def _optional_number(where: str, key: str, value: Any) -> float | None:
    return None if value is None else _number(where, key, value)


def _int(where: str, key: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestError(f"{where}.{key}: must be an integer, got {type(value).__name__}")
    return value


def _number_map(where: str, key: str, value: Any) -> dict[str, float]:
    raw = _object(f"{where}.{key}", value)
    return {str(name): _number(f"{where}.{key}", str(name), number) for name, number in raw.items()}
