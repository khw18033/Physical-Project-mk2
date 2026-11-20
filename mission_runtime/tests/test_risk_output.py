"""implements: AI-R-02 (구 AI-R-03 은 §5 에서 여기로 흡수됐다)"""

from mission_runtime.providers.fakes import InMemoryTransportProvider, JsonSerializerProvider
from mission_runtime.risk.output import RiskJudgment, RiskJudgmentPublisher


def test_publish_encodes_and_sends_through_provider_interfaces_only():
    serializer = JsonSerializerProvider()
    transport = InMemoryTransportProvider()
    received = []
    transport.subscribe("risk/zone-1", received.append)
    publisher = RiskJudgmentPublisher(serializer, transport, topic="risk/zone-1")

    judgment = RiskJudgment(
        risk_state="ALERT",
        risk_level=0.8,
        evidence_sufficiency=0.9,
        evidence_used=("water_level", "flow_rate"),
        model_version="rule-based-v1",
        recommendation="evacuate_zone",
    )

    publisher.publish(judgment)

    decoded = serializer.decode(received[0])
    assert decoded["risk_state"] == "ALERT"
    assert decoded["risk_level"] == 0.8
    assert decoded["recommendation"] == "evacuate_zone"
