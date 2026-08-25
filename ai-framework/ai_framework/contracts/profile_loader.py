"""Loads deployment profiles from data files so a new domain is added by
shipping a file, never by editing core code.

implements: AI-C-15

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

from ai_framework.contracts.profile import DeploymentProfile

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

    unknown = set(raw) - {"domain_id", "active_capability_kinds", "rule_set_id", "node_tags"}
    if unknown:
        # Fail loudly rather than silently ignoring a typo'd key that
        # would leave a capability unexpectedly inactive.
        raise DeploymentProfileError(f"unknown profile fields: {sorted(unknown)}")

    return DeploymentProfile(
        domain_id=str(raw["domain_id"]),
        active_capability_kinds=tuple(raw["active_capability_kinds"]),
        rule_set_id=raw.get("rule_set_id"),
        node_tags=tuple(raw.get("node_tags", ())),
    )


def is_capability_active(profile: DeploymentProfile, capability_kind: str) -> bool:
    """Whether this deployment uses a capability at all.

    Callers ask this instead of branching on `domain_id`; core code must
    never contain a domain-name conditional (절대 준수 원칙 #3).
    """
    return capability_kind in profile.active_capability_kinds
