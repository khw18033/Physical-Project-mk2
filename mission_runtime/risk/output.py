"""Risk judgment output: a domain object plus a Serializer/Transport
call, independent of any specific messaging/serialization/storage
technology (AI-R-02).

implements: AI-R-02

구 AI-R-03("위험 판단 결과·권고 출력")은 §5 에서 AI-R-02 로 흡수됐다. 이 모듈이
내는 것(위험 상태·정도·근거·근거 충분도·모델 버전·권고)이 그 요구사항이 열거한
결과 항목 그대로다.

Actual actuator command generation and physical-motion confirmation are
explicitly out of scope here — they belong to the backend/hardware side
(AI-R-02: "실제 액추에이터 명령 생성과 물리 동작 확인은 백엔드·하드웨어가
담당하고" / AI-C-19: AI는 물리 명령 발급과 실제 액추에이터 제어를 직접
소유해서는 안 된다).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from mission_runtime.providers.adapters import SerializerProvider, TransportProvider


@dataclass(frozen=True)
class RiskJudgment:
    risk_state: str
    risk_level: float
    evidence_sufficiency: float
    evidence_used: tuple[str, ...]
    model_version: str
    recommendation: str


class RiskJudgmentPublisher:
    """AI logic depends only on SerializerProvider/TransportProvider —
    never on MQTT/Kafka/Protobuf directly (AI-C-06, AI-C-07)."""

    def __init__(self, serializer: SerializerProvider, transport: TransportProvider, topic: str) -> None:
        self._serializer = serializer
        self._transport = transport
        self._topic = topic

    def publish(self, judgment: RiskJudgment) -> None:
        payload = self._serializer.encode(asdict(judgment))
        self._transport.publish(self._topic, payload)
