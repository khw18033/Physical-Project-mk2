"""Common provider interfaces (adapters) between AI logic and infrastructure.

implements: AI-C-04, AI-C-06, AI-C-07, AI-C-08, AI-C-09, AI-C-12, AI-B-03, AI-B-08

절대 준수 원칙 #1, #2, #10: 특정 센서·프로토콜·직렬화·러ntime·오케스트레이터를
프레임워크 핵심 코드에 하드코딩하지 않는다. 상위 인지·판단·위험 분석·실행관리
로직은 아래 Protocol만 의존하고, 현재 배포에서 어떤 구현(MQTT/Kafka/OTel/K3s/
RTSP/Protobuf 등)을 쓰는지는 이 인터페이스 뒤에 숨긴 provider가 결정한다.

Each Protocol is intentionally minimal — enough for upper-layer code to
depend on, not a full spec of any one backend's API.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable


@runtime_checkable
class TransportProvider(Protocol):
    """Sends/receives task (업무) and control messages.

    Current deployment: MQTT between 말단<->구역 엣지, Kafka between
    구역 엣지<->서버 via an edge-local bidirectional bridge (AI-C-06,
    절대 준수 원칙 #11). AI logic must never import an MQTT/Kafka client
    directly — only this Protocol.
    """

    def publish(self, topic: str, payload: bytes, *, qos: str = "at_least_once") -> None: ...

    def subscribe(self, topic: str, handler: Callable[[bytes], None]) -> None: ...

    def is_connected(self) -> bool: ...


@runtime_checkable
class SerializerProvider(Protocol):
    """Converts domain objects to/from wire format (AI-C-07).

    No single binary/text format is a framework requirement; a
    machine-to-machine boundary and a human-facing boundary may
    legitimately pick different serializers behind this same interface.
    """

    def encode(self, obj: Any) -> bytes: ...

    def decode(self, payload: bytes, schema_hint: str | None = None) -> Any: ...


@runtime_checkable
class MediaSourceProvider(Protocol):
    """Common video/media input, hiding RTSP/local-camera/file specifics (AI-C-08).

    Pixels never travel over a TransportProvider/ObservabilityProvider —
    only over a MediaSourceProvider-backed path (절대 준수 원칙 #10, 구현 시
    금지 사항: 영상 픽셀을 MQTT/Kafka/OTLP에 직접 싣지 않는다).
    """

    def read_frame(self) -> Any | None: ...

    def is_available(self) -> bool: ...

    def source_id(self) -> str: ...


@runtime_checkable
class AIRuntimeProvider(Protocol):
    """Runs one AI capability locally or remotely (AI-B-08).

    Upper-layer code asks for a capability_kind and gets a result; it
    never knows whether this provider is a local ONNX/TensorRT model, a
    remote microservice, or a cloud API.
    """

    def infer(self, capability_kind: str, inputs: Any) -> Any: ...

    def is_available(self) -> bool: ...


@runtime_checkable
class ControlProvider(Protocol):
    """Start/stop/restart/reconfigure + status for one execution unit (AI-B-03).

    Current deployment routes this through 서버 Kafka -> 엣지 Bridge ->
    말단 MQTT, but AI code only ever calls this Protocol.
    """

    def request(self, command: str, target_id: str, params: dict | None = None) -> Any: ...

    def get_status(self, target_id: str) -> Any: ...


@runtime_checkable
class ObservabilityProvider(Protocol):
    """Metric/log/trace/event sink (AI-O-01, AI-O-02, AI-C-12).

    `record_event` is for structured, individually-significant events
    (device death, fatal error) that must not be lost inside a metric
    aggregation window (AI-O-01, 구현 시 금지 사항: 일반 metric 요약에 장치
    급사·치명 오류를 섞지 않는다) — callers pick the method that matches the
    data's actual semantics, not its size.
    """

    def record_metric(self, name: str, value: float, tags: dict | None = None) -> None: ...

    def record_event(self, name: str, severity: str, payload: dict | None = None) -> None: ...
