"""Reference implementation of AI-N-01 (로컬 안전 판단).

Demonstrates the pattern every capability in this framework should
follow: declare required vs optional sub-capabilities, step the judgment
level down as optional providers disappear, and fall back to one fixed
conservative state the instant the single *required* input (video) is
gone — all without any exception, without requiring a specific model or
runtime, and without any dependency on network/edge availability.

implements: AI-N-01
required capability kind:  media.video_input
optional capability kinds: perception.classify, perception.track, perception.distance
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from perception_framework.contracts.capability import CapabilityRequirement, CapabilityState
from perception_framework.registry.capability_registry import CapabilityRegistry


class SafetyState(str, Enum):
    """Ordered from most to least conservative on purpose: the fallback
    path must always be able to name the *most* conservative state
    (SAFE_STOP) without needing any optional capability to be present.
    """

    SAFE_STOP = "SAFE_STOP"  # no usable video input -> stop, most conservative
    CAUTION = "CAUTION"  # video only, no perception feature usable
    MONITORED = "MONITORED"  # some but not all optional perception available
    FULL_AWARENESS = "FULL_AWARENESS"  # classify + track + distance all available


@dataclass(frozen=True)
class SafetyJudgment:
    state: SafetyState
    basis: tuple[str, ...]  # which optional capability kinds actually informed this judgment
    capability_state: CapabilityState


REQUIREMENT = CapabilityRequirement(
    required=("media.video_input",),
    optional=("perception.classify", "perception.track", "perception.distance"),
)

_OPTIONAL_KIND_ORDER = ("perception.classify", "perception.track", "perception.distance")


class LocalSafetyJudge:
    """On-device, network-independent access/collision safety judgment.

    Must keep producing a conservative answer regardless of:
      - total loss of edge/network connectivity,
      - any subset (including none) of the optional perception providers
        being present or healthy,
    and must fall back to SAFE_STOP the instant the required video input
    itself becomes unavailable (AI-N-01).
    """

    def __init__(self, registry: CapabilityRegistry) -> None:
        self._registry = registry

    def _available_kind_names(self) -> set[str]:
        return {
            kind
            for kind in ("media.video_input", *_OPTIONAL_KIND_ORDER)
            if self._registry.has_capability(kind)
        }

    def judge(self) -> SafetyJudgment:
        available = self._available_kind_names()
        capability_state = REQUIREMENT.evaluate(available)

        if capability_state is CapabilityState.DISABLED:
            # Required video input missing -> pre-defined conservative
            # state, never an exception, never "no answer" (AI-N-01:
            # "영상 입력 자체가 사라지면 사전에 정의된 보수적 안전 상태로 전이").
            return SafetyJudgment(SafetyState.SAFE_STOP, basis=(), capability_state=capability_state)

        basis = tuple(kind for kind in _OPTIONAL_KIND_ORDER if kind in available)
        if not basis:
            state = SafetyState.CAUTION
        elif set(basis) == set(_OPTIONAL_KIND_ORDER):
            state = SafetyState.FULL_AWARENESS
        else:
            state = SafetyState.MONITORED

        return SafetyJudgment(state, basis=basis, capability_state=capability_state)
