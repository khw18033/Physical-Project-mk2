"""Adapters from AI domain objects to the repository-wide JSON contracts.

implements: AI-C-01, AI-C-07, AI-C-06

**2026-10-27: 백엔드 통합데이터규약 v3(데이터 규약 v2)에 맞췄다.** 바뀐 것은 네 가지이고
모두 규약이 지정한 것이다 — 봉투를 평탄화(본문 칸을 공통 머리와 같은 층에), 시각을
ISO 8601 밀리초 `+09:00` 고정, `schema_version` 을 "2.0" 으로, 그리고 모르는 값은 칸을
빼는 것(`null` 을 싣지 않는다). 규약 쪽 지시 항목은 `docs/integration/be-conformance-reply.md`
에 항목별로 대응을 적었다.

`timestamp` 의 뜻도 함께 바뀌었다 — **데이터 시각**(그 데이터가 가리키는 순간)이고
메시지를 조립한 순간이 아니다. 비전 결과는 원본 프레임 시각과 같은 값을 쓴다.

The domain modules remain independent of backend and visualization naming.
Only this module knows the structures in ``schemas/ai``. This keeps a
TypeScript/UI field change from leaking into perception or risk
logic while still giving every other part one stable wire representation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence
from secrets import token_hex
from uuid import uuid4

from mission_runtime.common.timing import FrameReference
from mission_runtime.contracts.capability import CapabilityState
from mission_runtime.observability.events import CapabilityStateChange
from mission_runtime.perception.detection import PerceptionResult
from mission_runtime.risk.output import RiskJudgment
from mission_runtime.runtime.model_deployment import ModelDeploymentResult


SCHEMA_VERSION = "2.0"

#: 규약 R5/D1 — 시각은 ISO 8601, 밀리초 3자리, `+09:00` 고정.
KST = timezone(timedelta(hours=9))
AI_CHANNELS = frozenset(
    {
        "detections",
        "risk_state",
        "ai_failure",
        "capability_status",
        "model_deployment_result",
        # 운영 화면이 구독하는 통합 상태 뷰 한 장(AI-O-06). 구역마다 채널을 쪼개지
        # 않는 이유는 integration/status_wire.py 의 머리글에 적어 두었다.
        "status_snapshot",
    }
)


#: 이 프로세스의 1회 기동 식별자(규약 §3-1, 12자리 hex). 상태·프레임 계열은 필수이고
#: 비전 결과는 선택이다. 기동할 때 한 번 정하고 바꾸지 않는다.
SESSION_ID = token_hex(6)


def iso_ms(value: datetime | float | str | None = None) -> str:
    """규약 R5 의 시각 표기. `2026-10-12T14:10:31.086+09:00` 꼴이다.

    밀리초 아래는 버린다. 문자열은 ISO-8601 로 읽어 **같은 순간을 규약 표기로** 바꾼다 —
    순간은 그대로이고 표기만 하나로 모으는 것이다. 읽을 수 없는 문자열은 조용히
    통과시키지 않고 거부한다(규약이 표기를 고정했으므로 모양이 틀린 값은 오류다).
    """
    if isinstance(value, str):
        text = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"timestamp is not ISO-8601: {value!r}") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(KST).isoformat(timespec="milliseconds")
    if isinstance(value, (int, float)):
        instant = datetime.fromtimestamp(value, tz=KST)
    elif isinstance(value, datetime):
        instant = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        instant = instant.astimezone(KST)
    else:
        instant = datetime.now(KST)
    return instant.isoformat(timespec="milliseconds")


#: 과도기 호출부 호환용 별칭. 새 코드는 `iso_ms` 를 쓴다.
_timestamp = iso_ms


@dataclass(frozen=True)
class MessageContext:
    """Cross-part identity and ordering fields owned by the backend contract."""

    source_id: str
    node_id: str
    #: 규약은 선택이다("1:1 이면 칸을 뺀다"). 비우면 봉투에서 그 칸이 사라진다.
    entity_id: str | None = None
    #: 규약은 필수이고 `minLength: 1` 이다 — 비우면 백엔드가 격리한다.
    zone_id: str | None = None
    sequence_id: int = 0
    correlation_id: str | None = None
    timestamp: datetime | float | str | None = None
    message_id: str | None = None
    #: 생산 프로세스의 1회 기동 식별자. 비우면 모듈 전역값을 쓴다.
    session_id: str | None = None


@dataclass(frozen=True)
class DetectionObservation:
    """One detection in the AI-native x1/y1/x2/y2 representation."""

    box_xyxy: tuple[float, float, float, float]
    label: str
    confidence: float
    track_id: str | int | None = None
    class_confidence: float | None = None
    approach: str | None = None
    trail: tuple[tuple[float, float], ...] = ()
    source_id: str | None = None
    linked_sources: tuple[str, ...] = ()
    link_confidence: float | None = None


@dataclass(frozen=True)
class RiskReason:
    label: str
    value: str
    contribution: float = 0.0


def build_message(
    context: MessageContext,
    channel: str,
    payload: dict,
    *,
    coordinate_frame: str | None = None,
) -> dict:
    """공통 머리와 본문을 **한 층에** 담은 메시지를 만든다(규약 AI-01).

    `payload` 를 한 겹 더 감싸지 않는다 — 규약의 메시지 모양이 평탄하고, 받는 쪽이
    머리와 본문을 같은 층에서 읽는다. 모르는 값은 `null` 로 싣지 않고 **칸을 뺀다**
    (R8) — `correlation_id: null` 은 규약이 옛 모양으로 등재한 것이다.
    """
    if channel not in AI_CHANNELS:
        raise ValueError(f"unsupported AI channel: {channel}")
    if context.sequence_id < 0:
        raise ValueError("sequence_id must be non-negative")
    for field_name in ("source_id", "node_id", "zone_id"):
        if not getattr(context, field_name):
            raise ValueError(f"{field_name} must not be empty")

    envelope = {
        "schema_version": SCHEMA_VERSION,
        "message_id": context.message_id or str(uuid4()),
        "source_id": context.source_id,
        "node_id": context.node_id,
        "zone_id": context.zone_id,
        "channel": channel,
        "timestamp": iso_ms(context.timestamp),
        "sequence_id": context.sequence_id,
        "session_id": context.session_id or SESSION_ID,
    }
    # 해당이 없으면 칸을 뺀다(R8). coordinate_frame 은 position 칸이 있을 때만이다.
    if context.entity_id:
        envelope["entity_id"] = context.entity_id
    if context.correlation_id:
        envelope["correlation_id"] = context.correlation_id
    if coordinate_frame is not None:
        envelope["coordinate_frame"] = coordinate_frame

    collisions = sorted(set(envelope) & set(payload))
    if collisions:
        raise ValueError(
            f"payload keys collide with the envelope header: {collisions}"
        )
    envelope.update({k: v for k, v in payload.items() if v is not None})
    return envelope


def frame_reference_to_wire(reference: FrameReference) -> dict:
    """규약 D13 의 세 칸만 싣는다.

    `frame_id` 와 `time_sync_state` 는 규약이 지웠다(읽는 곳도 채우는 생산자도 없었다).
    카메라 식별자는 `camera_id` 이고 시각 칸 이름은 `timestamp` 다 — 프레임을 처음
    손에 넣은 기기가 붙인 값을 그대로 옮기며 AI 가 다시 만들지 않는다(규약 원칙 10).
    """
    return {
        "camera_id": reference.source_id,
        "sequence_id": reference.local_sequence,
        "timestamp": iso_ms(reference.observed_at),
    }


def observations_from_perception(
    results: Iterable[PerceptionResult],
    *,
    source_id: str,
) -> list[DetectionObservation]:
    return [
        DetectionObservation(
            box_xyxy=result.box,
            label=result.label,
            confidence=result.confidence,
            source_id=source_id,
        )
        for result in results
    ]


def _box_to_wire(box_xyxy: tuple[float, float, float, float]) -> list[float]:
    """규약 V1: `bbox` 는 `[x1, y1, x2, y2]` 픽셀이다.

    안쪽이 이미 xyxy 이므로 변환하지 않는다 — 규약 AI-03 이 `{x, y, width, height}`
    로 바꾸던 변환을 없애라고 지정했다. 기준 해상도는 결과 최상위 `width`·`height` 다.
    """
    x1, y1, x2, y2 = box_xyxy
    if x2 < x1 or y2 < y1:
        raise ValueError(f"invalid xyxy box: {box_xyxy}")
    return [x1, y1, x2, y2]


def _observation_to_wire(observation: DetectionObservation, default_source_id: str) -> dict:
    if not 0 <= observation.confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")
    if observation.class_confidence is not None and not 0 <= observation.class_confidence <= 1:
        raise ValueError("class_confidence must be between 0 and 1")
    if observation.approach not in (None, "closing", "steady", "receding"):
        raise ValueError(f"unsupported approach: {observation.approach}")
    if observation.link_confidence is not None and not observation.linked_sources:
        raise ValueError("link_confidence requires linked_sources")

    link = None
    if observation.linked_sources:
        confidence = observation.link_confidence
        if confidence is None or not 0 <= confidence <= 1:
            raise ValueError("linked detections require link_confidence between 0 and 1")
        link = {
            "linked_sources": list(observation.linked_sources),
            "confidence": confidence,
        }

    detection: dict = {
        "label": observation.label,
        "confidence": observation.confidence,
        "bbox": _box_to_wire(observation.box_xyxy),
        # 규약 N9: 검출 안의 카메라 칸 이름은 `camera_id` 다(봉투의 source_id 와
        # 뜻이 다르므로 같은 이름을 쓰지 않는다).
        "camera_id": observation.source_id or default_source_id,
    }
    # 모르면 칸을 뺀다(R8).
    if observation.track_id is not None:
        detection["track_id"] = str(observation.track_id)
    if observation.class_confidence is not None:
        detection["class_confidence"] = observation.class_confidence
    if observation.approach is not None:
        detection["approach"] = observation.approach
    if observation.trail:
        detection["trail"] = [{"x": x, "y": y} for x, y in observation.trail]
    if link is not None:
        detection["link"] = link
    return detection


def detection_message(
    reference: FrameReference,
    observations: Sequence[DetectionObservation],
    context: MessageContext,
    *,
    reference_size: tuple[int, int],
    tier: str = "edge",
    kind: str = "precise",
    optional: bool = True,
    label: str = "",
    bbox_format: str = "absolute",
    association: str = "unavailable",
    model: str,
    infer_ms: float | None = None,
    emitted_at: datetime | float | str | None = None,
    corridor_xyxy: tuple[float, float, float, float] | None = None,
) -> dict:
    """규약 §3-6 의 비전 결과 모양으로 조립한다.

    `model` 은 규약 필수 칸이라 기본값을 두지 않는다 — 어느 모델이 낸 결과인지
    모르면 소비자가 결과를 해석할 수 없다.

    `infer_ms` 는 **모델이 계산한 시간만**이다(규약 이름사전 T-? 의 정의). 프레임
    수신부터 결과까지의 전체 지연이 아니다 — 전체 지연에는 전송·대기가 섞여 생산자가
    분리해 낼 수 없고, 규약 R9 가 계산해서 나오는 값은 싣지 말라고 한다. 못 쟀으면
    `None` 이고 칸이 빠진다(0 을 넣지 않는다).
    """
    if tier not in ("device", "edge", "server"):
        raise ValueError(f"unsupported detection tier: {tier}")
    if kind not in ("safety_minimal", "precise", "derived"):
        raise ValueError(f"unsupported detection kind: {kind}")
    if bbox_format not in ("absolute", "normalized"):
        raise ValueError(f"unsupported bbox format: {bbox_format}")
    if association not in ("enabled", "unavailable"):
        raise ValueError(f"unsupported association state: {association}")
    width, height = reference_size
    if width <= 0 or height <= 0:
        raise ValueError("reference_size must contain positive dimensions")

    if not model:
        raise ValueError("model must name the model that produced this result")

    corridor = None
    if corridor_xyxy is not None:
        corridor = list(_box_to_wire(corridor_xyxy))     # 규약 N9: corridor 도 xyxy 픽셀

    frame_ref = frame_reference_to_wire(reference)
    # 규약 D5/R12 예외: 비전 결과의 `timestamp` 는 **원본 프레임 시각**이고
    # `frame_ref.timestamp` 와 같은 값이어야 한다. 두 칸을 같은 변수(reference)에서
    # 내보내므로 어긋날 수 없다 — 봉투 쪽 시각을 프레임 시각으로 덮는다.
    context = replace(context, timestamp=reference.observed_at)
    payload: dict = {
        "frame_ref": frame_ref,
        "emitted_at": iso_ms(emitted_at),
        "model": model,
        # 규약 N5: 출처 묶음 이름은 `producer` 다(안의 칸은 그대로).
        "producer": {"tier": tier, "kind": kind, "optional": optional, "label": label},
        # 규약 V1: 박스 기준 해상도는 결과 최상위 width·height 다(bbox_space 는 지웠다).
        "width": width,
        "height": height,
        "bbox_format": bbox_format,
        "association": association,
        "detections": [
            _observation_to_wire(observation, reference.source_id) for observation in observations
        ],
    }
    if infer_ms is not None:
        payload["infer_ms"] = infer_ms
    if corridor is not None:
        payload["corridor"] = corridor
    # coordinate_frame 은 position 칸이 있을 때만 싣는다(규약 AI-01) — 영상 좌표
    # 결과에는 position 이 없으므로 넣지 않는다.
    return build_message(context, "detections", payload)


def risk_judgment_message(
    judgment: RiskJudgment,
    context: MessageContext,
    *,
    reasons: Sequence[RiskReason] | None = None,
    decided_at: datetime | float | str | None = None,
) -> dict:
    state = judgment.risk_state.lower()
    if state not in ("normal", "watch", "alert", "recovery"):
        raise ValueError(f"unsupported risk state: {judgment.risk_state}")
    reason_items = list(reasons or ())
    if not reason_items:
        reason_items = [RiskReason(label=item, value="used", contribution=0.0) for item in judgment.evidence_used]

    payload = {
        "state": state,
        "score": judgment.risk_level,
        "evidence_sufficiency": judgment.evidence_sufficiency,
        "evidence_used": list(judgment.evidence_used),
        "reasons": [
            {"label": reason.label, "value": reason.value, "contribution": reason.contribution}
            for reason in reason_items
        ],
        "recommendation": judgment.recommendation,
        "model_version": judgment.model_version,
        "decided_at": _timestamp(decided_at),
    }
    return build_message(context, "risk_state", payload)


def ai_failure_message(
    context: MessageContext,
    *,
    component: str,
    error_code: str,
    detail: str,
    severity: str = "critical",
    model_version: str | None = None,
    input_ref: str | None = None,
    trace_id: str | None = None,
    capability_state_before: CapabilityState | None = None,
    capability_state_after: CapabilityState | None = None,
    occurred_at: datetime | float | str | None = None,
    event_id: str | None = None,
) -> dict:
    if severity not in ("info", "warning", "critical"):
        raise ValueError(f"unsupported failure severity: {severity}")
    payload = {
        "event_id": event_id or str(uuid4()),
        "component": component,
        "model_version": model_version,
        "input_ref": input_ref,
        "error_code": error_code,
        "detail": detail,
        "severity": severity,
        "capability_state_before": capability_state_before.value if capability_state_before else None,
        "capability_state_after": capability_state_after.value if capability_state_after else None,
        "trace_id": trace_id,
        "occurred_at": _timestamp(occurred_at),
    }
    return build_message(context, "ai_failure", payload)


def capability_status_message(
    change: CapabilityStateChange,
    context: MessageContext,
    *,
    reason: str | None = None,
    provider_id: str | None = None,
    cluster_id: str | None = None,
    changed_at: datetime | float | str | None = None,
) -> dict:
    payload = {
        "capability_kind": change.capability_kind,
        "provider_id": provider_id,
        "state": change.current.value,
        "reason": reason,
        "cluster_id": cluster_id,
        "changed_at": _timestamp(changed_at),
    }
    return build_message(context, "capability_status", payload)


def model_deployment_result_message(
    context: MessageContext,
    *,
    deployment_id: str,
    model_id: str,
    model_version: str,
    artifact_ref: str,
    checksum: str,
    target_node_id: str,
    status: str,
    previous_version: str | None = None,
    reason: str | None = None,
    occurred_at: datetime | float | str | None = None,
) -> dict:
    allowed = {"REQUESTED", "DOWNLOADING", "VALIDATING", "APPLIED", "FAILED", "ROLLED_BACK"}
    if status not in allowed:
        raise ValueError(f"unsupported model deployment status: {status}")
    payload = {
        "deployment_id": deployment_id,
        "model_id": model_id,
        "model_version": model_version,
        "artifact_ref": artifact_ref,
        "checksum": checksum,
        "target_node_id": target_node_id,
        "status": status,
        "previous_version": previous_version,
        "reason": reason,
        "occurred_at": _timestamp(occurred_at),
    }
    return build_message(context, "model_deployment_result", payload)


def model_deployment_record_message(result: ModelDeploymentResult, context: MessageContext) -> dict:
    """Convert the lifecycle manager's final/intermediate record without field duplication."""

    return model_deployment_result_message(
        context,
        deployment_id=result.deployment_id,
        model_id=result.model_id,
        model_version=result.model_version,
        artifact_ref=result.artifact_ref,
        checksum=result.checksum,
        target_node_id=result.target_node_id,
        status=result.status.value,
        previous_version=result.previous_version,
        reason=result.reason,
        occurred_at=result.occurred_at,
    )


def publish_message(message: dict, serializer, transport, topic: str) -> None:
    """Publish one already-built contract message through provider interfaces."""

    transport.publish(topic, serializer.encode(message))
