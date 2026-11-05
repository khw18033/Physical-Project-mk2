"""Turns one in-process dashboard snapshot into one wire message.

implements: AI-O-06 (통합 운영 상태 뷰 제공), AI-C-06 (데이터 유형별 전송 경계)
관련: AI-B-12 (작업 그래프 실행 상태), AI-B-13 (외부 개발 요청), AI-O-05 (계층별 지표),
      AI-L-10 (모델 배정), AI-C-01 (공통 데이터 규약), AI-C-19 (조회·제어 분리)

기능정의서(§3)가 요구한 것은 "소스별 개별 조회가 아니라 **하나의 통합 상태 뷰를
구독**"이다. 그래서 채널을 구역마다 쪼개지 않고 `status_snapshot` **하나**로 둔다.
구역별로 나누면 같은 사실이 두 채널로 와서 도착 순서에 따라 화면이 서로 어긋나고
(§5 상태 일관성), 구독 한 번으로 화면 전체가 갱신된다는 요구도 깨진다.

## 싣지 않는 것 — 세면 나오는 값

규약 R9(계산하면 나오는 값은 싣지 않는다)와 기능정의서 §4.1("상태별 노드 수는
실행 그래프의 노드 상태를 **집계한 값**이며 그래프와 항상 일치해야 한다")이 같은
결론을 가리킨다. 그래서 다음은 **보내지 않고** 화면이 `task_nodes` 에서 센다.

    상태별 노드 수      노드 목록에서 센다
    가속기별 노드 부하   노드의 accelerator_instance_id + 상태에서 센다
    미션 경과 시간      accepted_at 과 지금 시각의 차
    조건 충족 집계      조건 목록에서 센다

둘을 함께 실으면 반드시 어긋나는 날이 온다 — 한쪽만 갱신된 스냅샷이 나가는 순간이다.

## 측정 없음과 0 (§4.4·§4.5)

미측정은 `value` **칸을 아예 빼서** 표현한다(규약 R8: 모르는 값에 null 을 싣지
않는다). 0 을 넣으면 "쟀더니 0" 과 구별되지 않고, 화면은 그것을 "미달"로 그린다.
목표 기준선 충족 여부는 `target_meet_state` 3값(MET/UNMET/NOT_MEASURED)으로 따로
싣는다 — 화면이 미측정을 미달과 섞지 않게 하는 자리가 이것이다.

## 시각

전부 규약 D1(ISO-8601, 밀리초 3자리, `+09:00`)로 바꿔 싣고, 모르는 시각은 칸을
뺀다. 내부 표현(epoch 초)을 그대로 내보내지 않는다.

## 조회 전용

이 모듈에는 상태를 바꾸는 함수가 없다. 스냅샷을 메시지로 옮기는 단방향 사상이고,
`pin` 같은 관찰 방식 변경조차 여기서 다루지 않는다(§1.1 조회 전용 원칙, AI-C-19).
"""

from __future__ import annotations

from typing import Iterable, Mapping

from mission_runtime.execution.external_request import (
    ExternalRequest,
    ExternalRequestLog,
)
from mission_runtime.execution.task_graph import ReferenceEdge, TaskGraph, TaskNode
from mission_runtime.integration.wire import MessageContext, build_message, iso_ms
from mission_runtime.observability.dashboard_view import (
    DashboardSnapshot,
    EventRecord,
    NodeVerdict,
    RegionState,
    SourceState,
)
from mission_runtime.observability.layered_metrics import (
    AcceleratorInstance,
    BoardResources,
    Indicator,
    LayeredResourceView,
    Measurement,
    ServiceRuntime,
    TargetBaseline,
)
from mission_runtime.runtime.model_assignment import Assignment

#: 이 채널의 논리 이름. 구역이 아니라 **스냅샷 한 장**이 단위다.
STATUS_SNAPSHOT_CHANNEL = "status_snapshot"

#: 온디바이스 가속기에서 돌지 않는 노드의 실행 가속기 표시(§4.6). 가속기 id 자리에
#: 빈 값을 두면 "아직 모른다"와 "여기서 돌지 않는다"가 구별되지 않는다.
OFF_DEVICE = "off_device"


def _at(value: float | None) -> str | None:
    return None if value is None else iso_ms(value)


def _prune(mapping: dict) -> dict:
    """None 인 칸을 뺀다(R8). 빈 목록은 남긴다 — "0건"은 아는 사실이다."""
    return {key: value for key, value in mapping.items() if value is not None}


def measurement_to_wire(measurement: Measurement) -> dict:
    """측정 1건. 값이 없으면 `value` 칸이 없다 — 그것이 "측정 없음"이다."""
    return _prune({
        "value": measurement.value,
        "unit": measurement.unit,
        "measured_at": _at(measurement.at),
    })


def _target_to_wire(target: TargetBaseline) -> dict:
    return {"value": target.value, "direction": target.direction.value, "unit": target.unit}


def indicator_to_wire(indicator: Indicator) -> dict:
    """[E′] 지표 1건. 추이와 기준선을 같이 싣는다.

    기준선을 그래프 위 **실제 값 위치**에 그리라는 요구(§4.5)를 지키려면 화면이
    기준선과 표본을 같은 단위로 받아야 한다. 그래서 단위를 양쪽에 모두 싣는다 —
    단위가 다르면 `Indicator.series_range()` 가 이미 거부한다.
    """
    body = _prune({
        "indicator_name": indicator.name,
        "service_id": indicator.service_id,
        "accelerator_instance_id": indicator.accelerator_id,
        "measurement": measurement_to_wire(indicator.measurement),
        "target": _target_to_wire(indicator.target) if indicator.target else None,
        "target_meet_state": indicator.meet_state.value,
    })
    if indicator.trend:
        body["trend"] = [measurement_to_wire(sample) for sample in indicator.trend]
    return body


def accelerator_to_wire(accelerator: AcceleratorInstance) -> dict:
    """[B]/[E] 가속기 1개. **유휴여도 목록에서 빠지지 않는다**(§4.1·§4.4).

    배치된 기능이 없는 가속기를 생략하면 자원 여유와 부하 편중을 볼 수 없다. 그래서
    유휴 판정은 화면이 `services` 목록에서 파생시키고 여기서는 개체만 싣는다.
    """
    return _prune({
        "accelerator_instance_id": accelerator.instance_id,
        "accelerator_kind": accelerator.kind,
        "accelerator_attachment": accelerator.attachment,
        "accelerator_vendor_label": accelerator.vendor_label,
        "utilization": measurement_to_wire(accelerator.utilization),
        # 사용률 추이는 전력 추이와 **같은 요구**다(§4.4). 표본이 없으면 칸이
        # 없다 — 빈 배열을 보내면 "쟀는데 아무것도 없었다" 로 읽힌다.
        "utilization_trend": ([measurement_to_wire(s) for s in accelerator.utilization_trend]
                              if accelerator.utilization_trend else None),
        "temperature": measurement_to_wire(accelerator.temperature),
    })


def service_to_wire(service: ServiceRuntime) -> dict:
    """[B]/[E]/[F] 서비스 1개. 배치 가속기를 **반드시** 함께 싣는다(§4.4).

    `accelerator_instance_id` 가 None 인 것은 "미배치"라는 사실이고 지어내지 않는다.
    서비스 지연이 모델 탓인지 가속기 탓인지 좁히려면 이 둘이 한 칸에 합쳐져서는
    안 된다(§4.6: "하나의 수행 위치 항목으로 합쳐서는 안 된다").
    """
    body = _prune({
        "service_id": service.service_id,
        "accelerator_instance_id": service.accelerator_id,
        "service_role": service.role,
        "model": service.model_name,
        "model_version": service.model_version,
    })
    if service.indicators:
        body["indicators"] = [indicator_to_wire(i) for i in service.indicators]
    return body


def _board_to_wire(board: BoardResources) -> dict:
    body = {
        "memory_utilization": measurement_to_wire(board.memory_utilization),
        "power": measurement_to_wire(board.power),
    }
    if board.power_trend:
        body["power_trend"] = [measurement_to_wire(s) for s in board.power_trend]
    return body


def task_node_to_wire(node: TaskNode) -> dict:
    """[C]/[F] 노드 1개. 회차를 들고 다니므로 재실행이 원 노드를 덮지 않는다(§4.2).

    `source_status` 는 생성 주체의 원본 상태 문자열이다. 표시 어휘 6종으로 환산한
    뒤에도 원본을 남기는 이유는 환산이 되짚을 수 없는 손실이 되지 않게 하는 것이다.
    """
    body = _prune({
        "task_node_id": node.node_id,
        "node_title": node.title,
        "task_node_state": node.state.value,
        "source_status": node.source_status,
        "service_id": node.service_id,
        "accelerator_instance_id": node.accelerator_id,
        "node_kind": node.node_kind,
        "target_device_id": node.target_device_id,
        "state_changed_at": _at(node.state_changed_at),
        "started_at": _at(node.started_at),
        "estimated_completion_at": _at(node.estimated_completion_at),
        "progress_ratio": node.progress_ratio,
        "input_command": node.input_command,
        "task_attempt": node.attempt,
        "origin_task_node_id": node.origin_node_id,
        "external_request_id": node.external_request_id,
        "parallel_group": node.parallel_group,
    })
    # 관계는 빈 목록이어도 싣는다 — "선행이 없다"는 아는 사실이고, 칸이 없으면
    # 화면은 "모른다"와 구별할 수 없다.
    body["order_after"] = list(node.order_after)
    body["depends_on"] = list(node.depends_on)
    return body


def _reference_edge_to_wire(edge: ReferenceEdge) -> dict:
    return _prune({
        "from_task_node_id": edge.from_node_id,
        "to_task_node_id": edge.to_node_id,
        "reference_edge_kind": edge.kind,
        "reference_edge_when": edge.when,
    })


def _condition_to_wire(item) -> dict:
    return _prune({
        "condition_item_id": item.item_id,
        "condition_satisfied": item.satisfied,
        "condition_reason": item.reason_token,
    })


def verdict_to_wire(verdict: NodeVerdict) -> dict:
    """[G] 판정 1건. 3축을 **서로 다른 목록**으로 싣고 집계는 싣지 않는다(§4.7).

    "각 조건은 개별 항목 단위로 표시되어야 하며 요약 수치만 제공해서는 안 된다"가
    요구이므로, 집계만 받아서는 화면이 요구를 지킬 수 없다. 반대 방향(항목에서
    집계)은 화면에서 언제든 가능하다.
    """
    return _prune({
        "task_node_id": verdict.node_id,
        "completion": [_condition_to_wire(i) for i in verdict.completion],
        "failure": [_condition_to_wire(i) for i in verdict.failure],
        "resource": [_condition_to_wire(i) for i in verdict.resource],
        "escalated_request_id": verdict.escalated_request_id,
    })


def event_to_wire(event: EventRecord) -> dict:
    """[D]/[H] 사건 1건. 등급과 유형을 다른 칸에 둔다(§4.3).

    문서는 "INFO / WARN / ERROR / SDI 등 등급·유형 구분"이라고 적었지만 SDI 는 등급이
    아니라 유형이다. 한 칸에 섞으면 SDI 사건의 심각도를 표현할 자리가 사라진다.
    """
    return _prune({
        "occurred_at": _at(event.at),
        "event_severity": event.severity.value,
        "event_kind": event.kind.value,
        "event_message": event.message,
        "task_node_id": event.node_id,
        "task_attempt": event.attempt,
        "external_request_id": event.external_request_id,
    })


def external_request_to_wire(request: ExternalRequest) -> dict:
    """[I] 외부 기능 요청 1건. 서버 내부는 싣지 않는다(§4.9).

    3단계(서버 처리)는 **진행 중 여부만** 표시 대상이다. 그래서 담당자·빌드 상태 같은
    칸을 만들지 않고, 대신 `server_work_is_opaque` 로 "지금 그 구간에 있다"만 알린다.
    배포 미수신은 `deployment_version: null` 로 적지 않는다(R8). 대신 받은 사실을
    `deployment_received` 로 따로 싣고 버전 칸은 받았을 때만 만든다 — 그러면 "아직
    안 왔다"(received=false)와 "받았다"(버전 문자열)가 한 칸의 유무로 흐려지지 않는다.
    """
    body = _prune({
        "external_request_id": request.request_id,
        "external_request_reason": request.reason.value,
        "external_request_reason_detail": request.reason_detail,
        "task_node_id": request.origin_node_id,
        "requested_at": _at(request.requested_at),
        "external_request_stage": request.stage.value,
        "server_work_is_opaque": request.server_work_is_opaque,
        "deployment_version": request.deployment_version,
        "deployment_received": request.deployment_received,
        "re_execution_count": request.re_execution_count,
        "external_request_verdict": request.verdict.value,
        "re_request_of": request.re_request_of,
    })
    body["stage_times"] = [
        _prune({"external_request_stage": t.stage.value, "stage_entered_at": _at(t.at)})
        for t in request.transitions
    ]
    if request.re_executed_nodes:
        body["re_executed_task_node_ids"] = list(request.re_executed_nodes)
    return body


def assignment_to_wire(assignment: Assignment) -> dict:
    """모델 배정 1건 (AI-L-10). **고른 것과 탈락 사유를 함께** 싣는다.

    기능정의서는 모델명·버전을 B/E/F 에 요구하고(§4.1·§4.4·§4.6), 운영자가 "왜 이
    모델인가"를 묻는 자리는 §4.7 이다. 배정 사유 없이 모델명만 보내면 교체가 일어난
    뒤 화면이 그 이유를 설명할 수 없다. 조건을 만족하는 후보가 없어 배정되지 않은
    것도 정상 상태이므로 `model` 칸이 없는 배정을 그대로 싣는다(AI-C-05).
    """
    body = _prune({
        "device_id": assignment.device_id,
        "mission_id": assignment.mission_id,
        "capability_kind": assignment.capability_kind,
        "model": assignment.assigned.model_id if assignment.assigned else None,
        "model_version": assignment.assigned.version if assignment.assigned else None,
        "assignment_reason": assignment.reason,
    })
    body["rejected"] = [
        {"model_reference": r.version_reference, "assignment_reason": r.reason}
        for r in assignment.rejected
    ]
    return body


def _source_to_wire(source: SourceState, *, now: float | None, ttl_s: float) -> dict:
    """소스 1개의 수신 상태 (§3·§5).

    한 번도 못 받은 것과 받았지만 오래된 것을 구분한다. 전자는 `last_received_at`
    칸이 없고, 후자는 시각이 있으면서 `source_stale` 이 참이다. 시각을 지어내 채우면
    화면이 "단절 사실을 명시"할 근거를 잃는다.
    """
    stale = False if now is None else source.is_stale(now, ttl_s)
    return _prune({
        "source_id": source.source_id,
        "source_layer": source.layer,
        "last_received_at": _at(source.last_received_at),
        "source_stale": stale,
        "feeds": [region.value for region in source.feeds] or None,
    })


def _region_to_wire(state: RegionState) -> dict:
    return _prune({
        "region_id": state.region.value,
        "region_available": state.available,
        "region_reason": state.reason_token,
        "missing_sources": list(state.missing_sources) or None,
    })


def status_snapshot_payload(
    snapshot: DashboardSnapshot,
    *,
    assignments: Iterable[Assignment] | Mapping[str, Assignment] = (),
    now: float | None = None,
    source_ttl_s: float = 30.0,
) -> dict:
    """스냅샷 한 장을 채널 본문으로 옮긴다. 상태를 바꾸지 않는다.

    `assignments` 는 모델 배정 결과다. 스냅샷 자료구조에 넣지 않고 인자로 받는
    이유는 배정이 **관측이 아니라 결정**이고 주기가 다르기 때문이다 — 지표는 초
    단위로 바뀌고 배정은 임무·하드웨어가 바뀔 때만 바뀐다.
    """
    graph: TaskGraph = snapshot.graph
    resources: LayeredResourceView = snapshot.resources
    focus = graph.focus()
    requests: ExternalRequestLog | None = snapshot.external_requests
    assignment_list = list(
        assignments.values() if isinstance(assignments, Mapping) else assignments
    )

    payload: dict = {
        "mission": _prune({
            "mission_id": snapshot.mission.mission_id,
            "utterance_text": snapshot.mission.utterance,
            "mission_status": snapshot.mission.status,
            "accepted_at": _at(snapshot.mission.accepted_at),
        }),
        "focus": _prune({
            "task_node_id": focus.node_id,
            "focus_pinned": focus.pinned,
            "focus_reason": focus.reason,
        }),
        "task_nodes": [task_node_to_wire(node) for node in graph.nodes],
        "reference_edges": [_reference_edge_to_wire(e) for e in graph.reference_edges],
        "accelerators": [accelerator_to_wire(a) for a in resources.accelerators],
        "services": [service_to_wire(s) for s in resources.services],
        "board": _board_to_wire(resources.board),
        "verdicts": [verdict_to_wire(v) for v in snapshot.verdicts],
        # [D] 전체 사건 스트림. 노드별 필터([H])는 화면이 task_node_id 로 한다 —
        # 같은 사건을 두 목록으로 보내면 둘이 어긋나는 날이 온다.
        "events": [event_to_wire(e) for e in snapshot.recent_events()],
        "external_requests": [
            external_request_to_wire(r) for r in (requests.requests if requests else ())
        ],
        "model_assignments": [assignment_to_wire(a) for a in assignment_list],
        "sources": [
            _source_to_wire(s, now=now, ttl_s=source_ttl_s) for s in snapshot.sources
        ],
        "regions": [_region_to_wire(state) for state in snapshot.region_states()],
    }
    return payload


def status_snapshot_message(
    snapshot: DashboardSnapshot,
    context: MessageContext,
    *,
    assignments: Iterable[Assignment] | Mapping[str, Assignment] = (),
    now: float | None = None,
    source_ttl_s: float = 30.0,
) -> dict:
    """구독자가 받는 메시지 1건. 봉투는 다른 채널과 같은 규약을 쓴다(AI-C-01)."""
    return build_message(
        context,
        STATUS_SNAPSHOT_CHANNEL,
        status_snapshot_payload(
            snapshot, assignments=assignments, now=now, source_ttl_s=source_ttl_s
        ),
    )
