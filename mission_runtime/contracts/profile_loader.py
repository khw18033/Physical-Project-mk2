"""Loads deployment profiles from data files so a new domain is added by
shipping a file, never by editing core code.

implements: AI-C-15, AI-C-16, AI-N-03

AI-C-15: "새 도메인을 추가할 때 기존 인지·의사결정·실행관리 핵심 코드를 수정하지
않고 필요한 어댑터·규칙·기능 제공자와 설정을 추가하는 방식으로 확장할 수 있어야
한다. 특정 도메인에서 사용하지 않는 기능은 설치·실행을 요구하지 않아야 한다."

This loader knows nothing about robots, facilities or rivers — it only
turns a JSON object into a `DeploymentProfile`. Any file that parses is
a valid domain, which is exactly the property AI-C-15 asks for.
"""

from __future__ import annotations

import json
from pathlib import Path

from mission_runtime.contracts.capability import CapabilityRequirement
from mission_runtime.contracts.profile import (
    OUTAGE_BEHAVIORS,
    OUTAGE_UNAVAILABLE,
    CapabilityResidencySpec,
    DeploymentProfile,
    DevicePurposeProfile,
    LinkPostureThresholds,
    LinkProfile,
    ResidencyPolicy,
    ResourceBudget,
)
from mission_runtime.ondevice.link_handover import LinkPosture

_REQUIRED_FIELDS = ("domain_id", "active_capability_kinds")


class DeploymentProfileError(ValueError):
    pass


def load_profile(path: str | Path) -> DeploymentProfile:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return profile_from_dict(raw)


def profile_from_dict(raw: dict) -> DeploymentProfile:
    missing = [f for f in _REQUIRED_FIELDS if f not in raw]
    if missing:
        raise DeploymentProfileError(f"missing required profile fields: {missing}")

    unknown = set(raw) - {
        "domain_id",
        "active_capability_kinds",
        "rule_set_id",
        "node_tags",
        "closed_network",
        "internal_endpoints",
        # AI-C-07: optional wire-format policy fragment. It is deployment
        # configuration, not a capability, so it is accepted here and read
        # by `providers.serialization.load_policy_from_profile` rather than
        # being folded into DeploymentProfile.
        "serialization",
    }
    if unknown:
        # Fail loudly rather than silently ignoring a typo'd key that
        # would leave a capability unexpectedly inactive.
        raise DeploymentProfileError(f"unknown profile fields: {sorted(unknown)}")

    return DeploymentProfile(
        domain_id=str(raw["domain_id"]),
        active_capability_kinds=tuple(raw["active_capability_kinds"]),
        rule_set_id=raw.get("rule_set_id"),
        node_tags=tuple(raw.get("node_tags", ())),
        # AI-C-16: a deployment declares whether it is a closed network and
        # which locations count as internal; both are plain profile data.
        closed_network=bool(raw.get("closed_network", True)),
        internal_endpoints=tuple(raw.get("internal_endpoints", ())),
    )


def is_capability_active(profile: DeploymentProfile, capability_kind: str) -> bool:
    """Whether this deployment uses a capability at all.

    Callers ask this instead of branching on `domain_id`; core code must
    never contain a domain-name conditional (절대 준수 원칙 #3).
    """
    return capability_kind in profile.active_capability_kinds


# ---------------------------------------------------------------------------
# 장치 목적 프로파일 (AI-C-15, AI-N-03, AI-B-10)
#
# `load_profile`과 같은 성질을 유지한다: 이 로더는 드론도 로봇도 모르고,
# 파싱되는 파일은 전부 유효한 목적이다. 새 목적을 추가하는 일은 파일 한 개를
# 더 두는 일이지 코드를 고치는 일이 아니다.
# ---------------------------------------------------------------------------

_PURPOSE_FIELDS = {
    "purpose_id",
    "description",
    "capabilities",
    "node_tags",
    "preferred_node_tags",
    "budget",
    "link",
    "link_thresholds",
}
_RESIDENCY_SPEC_FIELDS = {
    "kind",
    "policy",
    "survives_outage",
    "quality_is_safety_affecting",
    "edge_service",
    "outage_behavior",
    "local_fallback_kind",
    "min_link_quality",
    "edge_payload",
    "is_core",
    "degrade_rank",
    "requirement",
    "note",  # 사람이 읽는 주석. 판정에 쓰이지 않는다.
}
_LINK_FIELDS = {"source", "quality", "stability", "declared_posture", "samples", "observed_at"}
_THRESHOLD_FIELDS = {"floor", "restore_margin", "min_stability", "min_samples"}
_BUDGET_FIELDS = {"compute_units", "memory_mb", "max_latency_ms"}


def _reject_unknown(where: str, raw: dict, allowed: set[str]) -> None:
    unknown = set(raw) - allowed
    if unknown:
        # 오타 난 키를 조용히 무시하면 "선언했는데 안 먹는다"가 된다.
        raise DeploymentProfileError(f"{where}: unknown fields {sorted(unknown)}")


def link_profile_from_dict(raw: dict | None) -> LinkProfile:
    if raw is None:
        return LinkProfile()
    if not isinstance(raw, dict):
        raise DeploymentProfileError("link: must be a JSON object")
    _reject_unknown("link", raw, _LINK_FIELDS)
    posture = raw.get("declared_posture")
    if posture is not None and posture not in {p.value for p in LinkPosture}:
        raise DeploymentProfileError(
            f"link.declared_posture: must be one of {sorted(p.value for p in LinkPosture)}"
        )
    return LinkProfile(
        source=str(raw.get("source", "unknown")),
        quality=None if raw.get("quality") is None else float(raw["quality"]),
        stability=None if raw.get("stability") is None else float(raw["stability"]),
        declared_posture=posture,
        samples=int(raw.get("samples", 0)),
        observed_at=None if raw.get("observed_at") is None else float(raw["observed_at"]),
    )


def _thresholds_from_dict(raw: dict | None) -> LinkPostureThresholds:
    if raw is None:
        return LinkPostureThresholds()
    if not isinstance(raw, dict):
        raise DeploymentProfileError("link_thresholds: must be a JSON object")
    _reject_unknown("link_thresholds", raw, _THRESHOLD_FIELDS)
    base = LinkPostureThresholds()
    return LinkPostureThresholds(
        floor=float(raw.get("floor", base.floor)),
        restore_margin=float(raw.get("restore_margin", base.restore_margin)),
        min_stability=float(raw.get("min_stability", base.min_stability)),
        min_samples=int(raw.get("min_samples", base.min_samples)),
    )


def _budget_from_dict(raw: dict | None) -> ResourceBudget | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise DeploymentProfileError("budget: must be a JSON object")
    _reject_unknown("budget", raw, _BUDGET_FIELDS)
    return ResourceBudget(
        compute_units=float(raw.get("compute_units", 0.0)),
        memory_mb=float(raw.get("memory_mb", 0.0)),
        max_latency_ms=None if raw.get("max_latency_ms") is None else float(raw["max_latency_ms"]),
    )


def residency_spec_from_dict(raw: dict) -> CapabilityResidencySpec:
    if not isinstance(raw, dict) or not isinstance(raw.get("kind"), str) or not raw["kind"]:
        raise DeploymentProfileError("capabilities[]: needs a non-empty 'kind'")
    where = f"capabilities[{raw['kind']}]"
    _reject_unknown(where, raw, _RESIDENCY_SPEC_FIELDS)

    policy_value = raw.get("policy", ResidencyPolicy.EDGE_SERVED.value)
    try:
        policy = ResidencyPolicy(policy_value)
    except ValueError:
        raise DeploymentProfileError(
            f"{where}.policy: must be one of {sorted(p.value for p in ResidencyPolicy)}"
        ) from None

    behavior = raw.get("outage_behavior", OUTAGE_UNAVAILABLE)
    if behavior not in OUTAGE_BEHAVIORS:
        raise DeploymentProfileError(f"{where}.outage_behavior: must be one of {list(OUTAGE_BEHAVIORS)}")

    requirement = raw.get("requirement", {})
    if not isinstance(requirement, dict):
        raise DeploymentProfileError(f"{where}.requirement: must be a JSON object")
    _reject_unknown(f"{where}.requirement", requirement, {"required", "optional"})

    return CapabilityResidencySpec(
        kind=raw["kind"],
        policy=policy,
        survives_outage=bool(raw.get("survives_outage", False)),
        quality_is_safety_affecting=bool(raw.get("quality_is_safety_affecting", False)),
        edge_service=raw.get("edge_service"),
        outage_behavior=behavior,
        local_fallback_kind=raw.get("local_fallback_kind"),
        min_link_quality=None if raw.get("min_link_quality") is None else float(raw["min_link_quality"]),
        edge_payload=str(raw.get("edge_payload", "metadata")),
        is_core=bool(raw.get("is_core", False)),
        degrade_rank=int(raw.get("degrade_rank", 0)),
        requirement=CapabilityRequirement(
            required=tuple(requirement.get("required", ())),
            optional=tuple(requirement.get("optional", ())),
        ),
    )


def device_purpose_from_dict(raw: dict) -> DevicePurposeProfile:
    if not isinstance(raw, dict):
        raise DeploymentProfileError("device purpose: must be a JSON object")
    if not isinstance(raw.get("purpose_id"), str) or not raw["purpose_id"]:
        raise DeploymentProfileError("device purpose: needs a non-empty 'purpose_id'")
    _reject_unknown(f"purpose[{raw['purpose_id']}]", raw, _PURPOSE_FIELDS)

    capabilities = raw.get("capabilities", [])
    if not isinstance(capabilities, list):
        raise DeploymentProfileError("capabilities: must be a JSON array")
    specs = tuple(residency_spec_from_dict(entry) for entry in capabilities)
    kinds = [spec.kind for spec in specs]
    if len(set(kinds)) != len(kinds):
        raise DeploymentProfileError("capabilities: duplicate kind")

    return DevicePurposeProfile(
        purpose_id=raw["purpose_id"],
        capabilities=specs,
        node_tags=tuple(raw.get("node_tags", ())),
        preferred_node_tags=tuple(raw.get("preferred_node_tags", ())),
        budget=_budget_from_dict(raw.get("budget")),
        link=link_profile_from_dict(raw.get("link")),
        link_thresholds=_thresholds_from_dict(raw.get("link_thresholds")),
        description=str(raw.get("description", "")),
    )


def load_device_purposes(path: str | Path) -> dict[str, DevicePurposeProfile]:
    """`{"purposes": [ ... ]}` 파일 하나를 purpose_id → 프로파일로 읽는다."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise DeploymentProfileError("device purposes file: top level must be a JSON object")
    entries = raw.get("purposes")
    if not isinstance(entries, list):
        raise DeploymentProfileError("device purposes file: 'purposes' must be a JSON array")
    purposes: dict[str, DevicePurposeProfile] = {}
    for entry in entries:
        purpose = device_purpose_from_dict(entry)
        if purpose.purpose_id in purposes:
            raise DeploymentProfileError(f"duplicate purpose_id: {purpose.purpose_id}")
        purposes[purpose.purpose_id] = purpose
    return purposes
