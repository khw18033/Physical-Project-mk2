"""Capability Registry: bookkeeping for available capabilities/providers.

implements: AI-C-10, AI-C-11, AI-B-04, AI-B-07

This registry only tracks what AI-side capabilities/providers exist and
whether they are currently healthy. It intentionally does NOT decide a
device's final availability — that stays the backend's job, integrating
task-transport status and observability status (AI-O-04, 절대 준수 원칙
#15). This registry may consume that backend verdict as an input (e.g.
by excluding a provider tied to a device the backend has marked
unavailable) but never recomputes it independently.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from ai_framework.contracts.capability import CapabilityRequirement
from ai_framework.contracts.profile import CompatibilityProfile


@dataclass
class ProviderRegistration:
    """One provider's registration entry for one capability kind."""

    capability_kind: str
    provider_id: str
    version: str
    compatibility: CompatibilityProfile = field(default_factory=CompatibilityProfile)
    requirement: CapabilityRequirement = field(default_factory=CapabilityRequirement)
    supported_inputs: tuple[str, ...] = ()
    supported_outputs: tuple[str, ...] = ()
    health_check: Callable[[], bool] | None = None
    registered_at: float = 0.0

    def is_healthy(self) -> bool:
        if self.health_check is None:
            return True
        try:
            return bool(self.health_check())
        except Exception:
            # A provider's own health probe failing must never crash the
            # registry or take down unrelated capabilities (AI-B-07).
            return False


class CapabilityRegistry:
    """Tracks, per capability kind, which providers are currently usable.

    Two layers are kept deliberately separate:
      - `_local`  : providers this node/process hosts itself. Always
                    authoritative regardless of central registry state.
      - `_remote` : the last snapshot merged in from a central/edge
                    registry. If the central registry becomes
                    temporarily unreachable, callers simply stop calling
                    `merge_remote_snapshot`, and this table keeps serving
                    its last known-good contents (AI-C-10: "중앙 등록
                    기능이 일시적으로 없어도... 마지막으로 확인된 로컬 기능
                    정보를 이용해 기존 기능을 계속 실행").
    """

    def __init__(self) -> None:
        self._local: dict[str, dict[str, ProviderRegistration]] = {}
        self._remote: dict[str, dict[str, ProviderRegistration]] = {}

    def register_local(self, reg: ProviderRegistration) -> None:
        reg.registered_at = time.time()
        self._local.setdefault(reg.capability_kind, {})[reg.provider_id] = reg

    def unregister_local(self, capability_kind: str, provider_id: str) -> None:
        self._local.get(capability_kind, {}).pop(provider_id, None)

    def merge_remote_snapshot(self, snapshot: dict[str, dict[str, ProviderRegistration]]) -> None:
        """Replace the remote-known table with a fresh central snapshot.

        Not calling this (e.g. because the central registry cannot be
        reached) is a valid, expected operating condition — it simply
        means `available_providers` keeps returning what was last known.
        """
        self._remote = {kind: dict(providers) for kind, providers in snapshot.items()}

    def available_providers(self, capability_kind: str) -> list[ProviderRegistration]:
        """Currently usable providers for a capability kind, healthy only.

        Local registrations take precedence over a remote entry with the
        same provider_id. Never raises for an unknown capability kind —
        an empty list is the correct answer for "not available right now"
        (구현 시 금지 사항: 특정 모델이 없으면 시스템을 시작하지 못하게 만들지
        않는다).
        """
        merged: dict[str, ProviderRegistration] = {}
        merged.update(self._remote.get(capability_kind, {}))
        merged.update(self._local.get(capability_kind, {}))
        return [reg for reg in merged.values() if reg.is_healthy()]

    def has_capability(self, capability_kind: str) -> bool:
        return len(self.available_providers(capability_kind)) > 0

    def known_capability_kinds(self) -> set[str]:
        """All capability kinds this node currently knows about, local or
        remote — used by conformance/verification harnesses, not by
        upper-layer AI logic (AI-B-09)."""
        return set(self._local.keys()) | set(self._remote.keys())
