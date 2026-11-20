"""Capability Registry: bookkeeping for available capabilities/providers.

implements: AI-C-10, AI-C-05, AI-B-04, AI-B-05

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

from mission_runtime.contracts.capability import CapabilityRequirement
from mission_runtime.contracts.capability_contract import (
    DECLARATION_ITEM_OWNERS,
    ITEM_CANCELLABLE,
    ITEM_IDEMPOTENT,
    Capability as CapabilityDeclaration,
    ExecutionProfile,
    RuntimeInstance,
)
from mission_runtime.contracts.profile import CompatibilityProfile


#: 참·거짓으로 선언되는 AI-C-18 항목 → 선언에서 그 값을 읽는 법. 표로 두는
#: 이유는 `providers_declaring` 이 항목 이름으로 호출되기 때문이다 — 호출자가
#: 필드 이름을 알아야 하면 선언 계약의 변경이 호출자까지 번진다.
_BOOLEAN_ITEM_READERS = {
    ITEM_CANCELLABLE: lambda d: d.cancellable,
    ITEM_IDEMPOTENT: lambda d: d.idempotent,
}


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
    # AI-C-18 5-layer target contract (docs/technology-boundaries.md
    # §4/§10-2) linked in by reference, not required — both default to `None` so every
    # existing registration keeps working unchanged. When present, `selection/selector.py`'s
    # `select_for_intent` applies their extra §4.3 invariants (3: reuse measured evidence
    # only under matching conditions; 4: TTL-expired instance excluded even with a past
    # benchmark) on top of the existing compatibility/budget filter.
    execution_profile: ExecutionProfile | None = None
    runtime_instance: RuntimeInstance | None = None
    # AI-C-18 선언 그대로. `None` 은 이 provider 가 선언을 들고 오지 않았다는
    # 뜻이고, 들고 왔더라도 그 안의 칸은 또 비어 있을 수 있다 — 두 단계 모두
    # "없음" 과 "모름" 을 구분한다.
    declaration: CapabilityDeclaration | None = None

    def declared_items_missing(self) -> tuple[str, ...]:
        """이 등록이 적지 않은 AI-C-18 항목들. 선언이 아예 없으면 그 계층이
        담는 항목 전부가 미선언이다 — 빈 등록을 "조건 없는 provider" 로
        읽지 않기 위한 자리다."""
        if self.declaration is None:
            return DECLARATION_ITEM_OWNERS["Capability"]
        return self.declaration.undeclared_items()

    def is_healthy(self) -> bool:
        if self.health_check is None:
            return True
        try:
            return bool(self.health_check())
        except Exception:
            # A provider's own health probe failing must never crash the
            # registry or take down unrelated capabilities (AI-B-05).
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

    def providers_declaring(
        self, capability_kind: str, item: str, *, expected: bool = True
    ) -> tuple[list[ProviderRegistration], list[ProviderRegistration]]:
        """선언된 성질로 후보를 가른다. 돌려주는 것은 **두 묶음**이다 —
        `(그렇다고 선언한 것들, 아무도 선언하지 않은 것들)`.

        세 묶음이 아니라 둘인 이유: "아니라고 선언한 것" 은 요청과 어긋난
        후보이므로 어느 쪽에도 들어가지 않는다. 미선언을 **거부로 접지도,
        조건 충족으로 세지도 않는다** — 둘 다 없는 선언을 지어내는 것이고,
        AI-C-18 이 "모든 항목이 항상 존재한다고 가정해서는 안 된다" 로 금지한
        그 자리다. 호출자는 미선언 묶음을 쓸지(그리고 그 위험을 안을지) 직접
        정한다. 지금 와이어로 온 장치 선언은 전부 미선언 묶음에 들어온다
        (`specs/physical-command-interface.md` §8-3 P7).

        `item` 은 `CAPABILITY_DECLARATION_ITEMS` 의 불리언 항목 토큰
        (`cancellable` / `idempotent`) 이다.
        """
        getter = _BOOLEAN_ITEM_READERS.get(item)
        if getter is None:
            raise ValueError(
                f"'{item}' 은 참·거짓으로 선언되는 항목이 아니다 "
                f"(허용: {sorted(_BOOLEAN_ITEM_READERS)})"
            )
        matching: list[ProviderRegistration] = []
        undeclared: list[ProviderRegistration] = []
        for reg in self.available_providers(capability_kind):
            value = None if reg.declaration is None else getter(reg.declaration)
            if value is None:
                undeclared.append(reg)
            elif value is expected:
                matching.append(reg)
        return matching, undeclared

    def known_capability_kinds(self) -> set[str]:
        """All capability kinds this node currently knows about, local or
        remote — used by conformance/verification harnesses, not by
        upper-layer AI logic (AI-B-09)."""
        return set(self._local.keys()) | set(self._remote.keys())
