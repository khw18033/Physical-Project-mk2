"""Reference implementation of AI-N-01 (로컬 안전 판단).

Demonstrates the pattern every capability in this framework should
follow: declare required vs optional sub-capabilities, step the judgment
level down as optional providers disappear, and fall back to one fixed
conservative state the instant the single *required* input (video) is
gone — all without any exception, without requiring a specific model or
runtime, and without any dependency on network/edge availability.

implements: AI-N-01
required capability kind:  media.video_input
optional capability kinds: deployment-declared subset of
    perception.classify, perception.track, perception.distance
    (see `expected_optional_kinds` below)

2026-09 온디바이스/엣지 재설계: 이동형 에이전트(사족보행 등)는 의미 분류·
추적을 edge로 옮기고 온디바이스엔 class-agnostic proposal(공간 위험
판단용) + distance/TTC만 남긴다(로봇/고정 카메라 설계 대화 참고). 이 경우
perception.classify/track는 "잃어버린 것"이 아니라 애초에 이 노드에
등록되지 않는 것이 정상이므로, `evaluate()`가 구분 못 하는 "설계상 없음"과
"장애로 없음"을 이 판단기 레벨에서 갈라야 한다 — 그래서 optional kind
목록을 배포 시점에 좁힐 수 있게 생성자 인자로 뺐다(과거엔 모듈 상수
고정값이라 이 구분이 불가능했다 — tests/test_local_safety.py의
`test_ondevice_profile_without_classify_or_track_is_monitored`가 그 문제를
pin 해뒀던 것). 기본값은 기존 전체 3종 그대로라 기존 호출부는 동작이
바뀌지 않는다.
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


_OPTIONAL_KIND_ORDER = ("perception.classify", "perception.track", "perception.distance")

#: Default judge scope: every optional perception feature this framework
#: knows about. Unchanged from before this module took a constructor
#: argument, so every existing caller keeps its current behavior.
FULL_OPTIONAL_KINDS = _OPTIONAL_KIND_ORDER

#: Reference scope for a mobile agent under the 2026-09 split: semantic
#: classification and identity tracking are produced asynchronously on the
#: edge (AI-S-01/06), never on-device, so a mobile agent's judge should be
#: constructed with only this tuple -- not the full default -- to make
#: FULL_AWARENESS reachable at its actual designed scope instead of being
#: permanently capped at MONITORED for capabilities it was never meant to
#: host locally.
MOBILE_AGENT_OPTIONAL_KINDS = ("perception.distance",)

REQUIREMENT = CapabilityRequirement(required=("media.video_input",), optional=FULL_OPTIONAL_KINDS)


class LocalSafetyJudge:
    """On-device, network-independent access/collision safety judgment.

    Must keep producing a conservative answer regardless of:
      - total loss of edge/network connectivity,
      - any subset (including none) of the optional perception providers
        being present or healthy,
    and must fall back to SAFE_STOP the instant the required video input
    itself becomes unavailable (AI-N-01).

    `expected_optional_kinds` is what *this deployment* considers a
    complete on-device picture -- not necessarily every optional kind the
    framework can name. A capability outside this tuple is simply never
    looked at here, so a mobile agent that by design never hosts
    perception.classify/track locally is not stuck at MONITORED forever;
    it reaches FULL_AWARENESS on video+distance alone, exactly as designed.
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        expected_optional_kinds: tuple[str, ...] = FULL_OPTIONAL_KINDS,
    ) -> None:
        self._registry = registry
        self._expected_optional_kinds = tuple(expected_optional_kinds)
        self._requirement = CapabilityRequirement(
            required=("media.video_input",),
            optional=self._expected_optional_kinds,
        )

    def _available_kind_names(self) -> set[str]:
        return {
            kind
            for kind in ("media.video_input", *self._expected_optional_kinds)
            if self._registry.has_capability(kind)
        }

    def judge(self) -> SafetyJudgment:
        available = self._available_kind_names()
        capability_state = self._requirement.evaluate(available)

        if capability_state is CapabilityState.DISABLED:
            # Required video input missing -> pre-defined conservative
            # state, never an exception, never "no answer" (AI-N-01:
            # "영상 입력 자체가 사라지면 사전에 정의된 보수적 안전 상태로 전이").
            return SafetyJudgment(SafetyState.SAFE_STOP, basis=(), capability_state=capability_state)

        basis = tuple(kind for kind in self._expected_optional_kinds if kind in available)
        if not basis:
            state = SafetyState.CAUTION
        elif set(basis) == set(self._expected_optional_kinds):
            state = SafetyState.FULL_AWARENESS
        else:
            state = SafetyState.MONITORED

        return SafetyJudgment(state, basis=basis, capability_state=capability_state)
