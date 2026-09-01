"""Classifies produced data into task / observability / media planes, and
marks control data as the special task subtype with stricter policy.

implements: AI-C-14

AI-C-14: "AI에서 발생하는 데이터는 업무 데이터와 시스템 관측 데이터로 구분하고,
영상 등 대용량 데이터는 별도 미디어 경로로 처리해야 한다. 물리 제어 명령은 업무
데이터에 포함하되 전달 보장, 순서, 실행 결과와 책임 추적이 필요한 제어 데이터로
별도 정책을 적용해야 한다. AI 기능은 데이터의 의미만 생산하고 실제 경로 선택은
전송·관측·미디어 어댑터가 담당해야 한다."

This module therefore returns a *plane and policy*, never a topic name,
broker address or protocol — which concrete adapter serves each plane is
the deployment profile's business (AI-C-12).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DataPlane(str, Enum):
    TASK = "TASK"  # 업무 데이터 (인지 결과, 위험 판단, 서브태스크 ...)
    OBSERVABILITY = "OBSERVABILITY"  # metric/log/trace
    MEDIA = "MEDIA"  # 영상 픽셀 등 대용량


class DataKind(str, Enum):
    """Semantic kind an AI capability declares for what it produced."""

    PERCEPTION_RESULT = "PERCEPTION_RESULT"
    RISK_VERDICT = "RISK_VERDICT"
    SUBTASK = "SUBTASK"
    CONTROL_COMMAND = "CONTROL_COMMAND"
    CONTROL_RESULT = "CONTROL_RESULT"
    HEARTBEAT = "HEARTBEAT"
    METRIC = "METRIC"
    LOG = "LOG"
    TRACE = "TRACE"
    VIDEO_FRAME = "VIDEO_FRAME"
    VIDEO_SEGMENT = "VIDEO_SEGMENT"


@dataclass(frozen=True)
class RoutingPolicy:
    """What the transport adapter must guarantee for this data.

    Control data lives on the task plane but demands delivery guarantee,
    ordering, a returned execution result and an audit trail — hence the
    separate flags rather than a separate plane (AI-C-14, AI-B-03).
    """

    plane: DataPlane
    delivery_guaranteed: bool = False
    ordered: bool = False
    result_expected: bool = False
    audit_tracked: bool = False
    summarizable: bool = True  # may be aggregated before leaving the edge (AI-O-01)


_CONTROL_POLICY = RoutingPolicy(
    plane=DataPlane.TASK,
    delivery_guaranteed=True,
    ordered=True,
    result_expected=True,
    audit_tracked=True,
    summarizable=False,
)

_POLICIES: dict[DataKind, RoutingPolicy] = {
    DataKind.PERCEPTION_RESULT: RoutingPolicy(DataPlane.TASK),
    DataKind.RISK_VERDICT: RoutingPolicy(DataPlane.TASK, delivery_guaranteed=True, audit_tracked=True),
    DataKind.SUBTASK: RoutingPolicy(DataPlane.TASK, delivery_guaranteed=True, ordered=True, audit_tracked=True),
    DataKind.CONTROL_COMMAND: _CONTROL_POLICY,
    DataKind.CONTROL_RESULT: _CONTROL_POLICY,
    # 장치 생사 신호는 집계되면 개별 의미를 잃는다 (원칙 #14, AI-O-04).
    DataKind.HEARTBEAT: RoutingPolicy(DataPlane.TASK, delivery_guaranteed=False, summarizable=False),
    DataKind.METRIC: RoutingPolicy(DataPlane.OBSERVABILITY, summarizable=True),
    DataKind.LOG: RoutingPolicy(DataPlane.OBSERVABILITY, summarizable=False),
    DataKind.TRACE: RoutingPolicy(DataPlane.OBSERVABILITY, summarizable=False),
    DataKind.VIDEO_FRAME: RoutingPolicy(DataPlane.MEDIA, summarizable=False),
    DataKind.VIDEO_SEGMENT: RoutingPolicy(DataPlane.MEDIA, summarizable=False),
}


def policy_for(kind: DataKind) -> RoutingPolicy:
    return _POLICIES[kind]


def is_control_data(kind: DataKind) -> bool:
    return policy_for(kind) is _CONTROL_POLICY


class DataPlaneViolation(RuntimeError):
    """Raised when data is about to be sent down the wrong plane."""


def assert_routable(kind: DataKind, plane: DataPlane) -> None:
    """Guard used by adapters before handing data to a concrete backend.

    Exists specifically to make the prohibition explicit and testable:
    "영상 픽셀을 MQTT/Kafka/OTLP 업무·관측 메시지에 직접 싣지 않는다"
    (구현 시 금지 사항).
    """
    expected = policy_for(kind).plane
    if expected is not plane:
        raise DataPlaneViolation(f"{kind.value} belongs to {expected.value} plane, not {plane.value}")
