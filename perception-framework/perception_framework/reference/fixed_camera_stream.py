"""Reference implementation of AI-E-01 (인지) for a fixed camera node.

implements: AI-E-01
required capability kind:  media.video_input
optional capability kind:  perception.classify (or whatever perception.*
    provider this node actually hosts)

2026-09 온디바이스/엣지 재설계: 고정 카메라는 AI-N-01의 "이동형 에이전트"에
해당하지 않으므로 접근·충돌 안전 판단 자체가 없다 — 지킬 물리적 이동이
없다. 따라서 이 노드의 유일한 책임은 "가능한 범위의 영상 좌표 기반 인지
결과를 계속 제공"(AI-E-01)하는 것뿐이고, SafetyState 같은 보수적 fallback
상태 개념이 필요 없다: required 입력(영상)이 사라지면 그냥 이번 tick에 낼
결과가 없을 뿐이다.

이 노드는 상시 편도(one-way) producer다 — edge가 내려주는 것을 기다리거나
그것 없이는 동작하지 않는다는 뜻으로 "받을 필요 없다"고 한 설계 결정을
그대로 반영한다. 다만 완전히 무입력은 아니다: 카메라 보정 프로파일
갱신(AI-E-02)과 실행 설정 갱신(AI-N-02)은 이 스트림과 별도의, 저빈도
이벤트 기반 채널로 들어온다 — `edge/calibration_profile.py`,
`ondevice/config_apply.py`가 그 경로이고, 이 모듈은 그 두 채널이 있는지
없는지와 무관하게 계속 동작해야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from perception_framework.contracts.capability import CapabilityRequirement, CapabilityState
from perception_framework.providers.adapters import SerializerProvider, TransportProvider
from perception_framework.registry.capability_registry import CapabilityRegistry

REQUIREMENT = CapabilityRequirement(
    required=("media.video_input",),
    optional=("perception.classify",),
)


@dataclass(frozen=True)
class PerceptionPublishOutcome:
    capability_state: CapabilityState
    published: bool
    reason: str


class FixedCameraPerceptionStream:
    """Always-on, one-way perception producer for a fixed camera.

    Publishes whatever perception result the currently-available
    capability can produce (full or reduced -- AI-E-01: "보정이나 추가
    분석 기능이 없더라도 가능한 범위의 영상 좌표 기반 결과를 계속
    제공"), or stays silent -- never raises -- the instant the required
    video input itself is gone. Never blocks on, or expects, anything
    back from the edge in order to keep publishing.
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        serializer: SerializerProvider,
        transport: TransportProvider,
        topic: str,
    ) -> None:
        self._registry = registry
        self._serializer = serializer
        self._transport = transport
        self._topic = topic

    def _available_kind_names(self) -> set[str]:
        return {
            kind
            for kind in ("media.video_input", "perception.classify")
            if self._registry.has_capability(kind)
        }

    def publish_if_available(self, perception_result: dict) -> PerceptionPublishOutcome:
        capability_state = REQUIREMENT.evaluate(self._available_kind_names())

        if capability_state is CapabilityState.DISABLED:
            return PerceptionPublishOutcome(capability_state, published=False, reason="no_video_input")

        payload = self._serializer.encode(perception_result)
        self._transport.publish(self._topic, payload)
        return PerceptionPublishOutcome(capability_state, published=True, reason="ok")
