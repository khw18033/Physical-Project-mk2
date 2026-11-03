"""Builds the one worked example behind the `status_snapshot` contract.

implements: AI-O-06, AI-O-05, AI-B-12, AI-B-13, AI-L-10
covers: schemas/ai/examples/status-snapshot.json 의 생산 코드

예제를 손으로 적지 않는 이유는 하나다 — 손으로 적은 예제는 생산 코드가 바뀌어도
그대로 남아 계약을 **거짓으로** 증명한다. 그래서 여기서 실제 자료구조로 만들고,
시험이 커밋된 예제와 바이트로 비교한다. 다시 쓰려면:

    ./.venv/bin/python tests/dashboard_example.py --write

구성은 기능정의서 §1.2 의 1차년도 가정값(AI-SBC 보드 · 가속기 6개 · 서비스 5개 ·
예비 NPU 1개 미할당)을 그대로 따르고, 미션 문구는 가시화 10편(MSN-261027-01)의
발화를 빌렸다 — 양쪽이 같은 사례를 가리키면 통합할 때 대조가 쉽다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from mission_runtime.execution.external_request import (
    ExternalRequest,
    ExternalRequestLog,
    FinalVerdict,
    RequestReason,
    RequestStage,
)
from mission_runtime.execution.task_graph import (
    NodeState,
    ReferenceEdge,
    TaskGraph,
    TaskNode,
)
from mission_runtime.integration.status_wire import OFF_DEVICE, status_snapshot_message
from mission_runtime.integration.wire import MessageContext
from mission_runtime.observability.dashboard_view import (
    ConditionItem,
    DashboardSnapshot,
    EventKind,
    EventRecord,
    MissionSummary,
    NodeVerdict,
    Region,
    Severity,
    SourceState,
)
from mission_runtime.observability.layered_metrics import (
    AcceleratorInstance,
    BoardResources,
    Direction,
    Indicator,
    LayeredResourceView,
    Measurement,
    ServiceRuntime,
    TargetBaseline,
)
from mission_runtime.runtime.model_assignment import (
    Assignment,
    ModelVersion,
    REASON_ASSIGNED,
    REASON_NO_CANDIDATE,
    REASON_SCOPE_HARDWARE,
    Rejection,
)

EXAMPLE_PATH = (
    Path(__file__).resolve().parents[1] / "schemas" / "ai" / "examples" / "status-snapshot.json"
)

#: 예제의 시각 기준. 고정값이라 예제가 돌릴 때마다 바뀌지 않는다.
T0 = 1793577600.0  # 2026-11-02T09:00:00+09:00


def _indicators_of(service_id: str) -> tuple[Indicator, ...]:
    return tuple(i for i in example_indicators() if i.service_id == service_id)


def example_snapshot() -> DashboardSnapshot:
    mission = MissionSummary(
        mission_id="MSN-261027-01",
        utterance="박스 앞까지 이동해",
        status="running",
        accepted_at=T0,
    )

    nodes = (
        TaskNode("T-A2", "로봇 현재 자세 확인", NodeState.SUCCEEDED,
                 service_id="vlm_map", accelerator_id="ext-npu-1",
                 node_kind="sense", target_device_id="robot-01",
                 state_changed_at=T0 + 4.0, started_at=T0 + 1.0,
                 progress_ratio=1.0, input_command="로봇의 현재 방위를 확인한다",
                 source_status="done"),
        TaskNode("T-A3", "한 바퀴 돌며 박스 탐지", NodeState.EXECUTING,
                 service_id="vlm", accelerator_id="ext-npu-2",
                 node_kind="act", target_device_id="robot-01",
                 order_after=("T-A2",), parallel_group="scan",
                 state_changed_at=T0 + 5.0, started_at=T0 + 5.0,
                 estimated_completion_at=T0 + 68.0, progress_ratio=0.5,
                 input_command="scan_mission: 45도씩 8칸", source_status="running"),
        TaskNode("T-A4", "각도별 근거 수집", NodeState.EXECUTING,
                 service_id="vlm", accelerator_id="ext-npu-2",
                 node_kind="sense", parallel_group="scan",
                 order_after=("T-A2",), depends_on=("T-A3",),
                 state_changed_at=T0 + 6.0, started_at=T0 + 6.0,
                 progress_ratio=0.5, source_status="running"),
        TaskNode("T-B1", "이동 경로 산출", NodeState.BLOCKED,
                 service_id="vlm_map", accelerator_id="ext-npu-1",
                 node_kind="decide", depends_on=("T-A4",),
                 input_command="탐지 결과로 접근 경로를 낸다",
                 source_status="pending"),
        TaskNode("T-B2", "회전·직진 실행", NodeState.PENDING,
                 service_id="vla", accelerator_id="npu-xdna",
                 node_kind="act", target_device_id="robot-01",
                 order_after=("T-B1",), source_status="pending"),
        # 미지원 기능으로 외부 요청이 걸린 노드. 온디바이스에서 돌지 않으므로
        # 실행 가속기 자리에 "여기서 돌지 않는다"를 명시한다(§4.6).
        TaskNode("T-C1", "박스 무게 추정", NodeState.EXTERNAL_REQUESTED,
                 service_id=None, accelerator_id=OFF_DEVICE,
                 node_kind="verify", depends_on=("T-B2",),
                 external_request_id="SDI-2026-1102-007",
                 state_changed_at=T0 + 40.0, source_status="awaiting_evaluation"),
        # 재실행 2건. 원 노드를 덮지 않고 회차로 남는다(§4.2·§4.8).
        # 2회차는 시뮬에서는 되는데 실물에서 실패해 외부 요청으로 올라갔고,
        # 3회차는 그 배포를 적용해 다시 돈 결과다.
        TaskNode("T-A2#2", "로봇 현재 자세 확인", NodeState.FAILED,
                 service_id="vlm_map", accelerator_id="ext-npu-1",
                 node_kind="sense", attempt=2, origin_node_id="T-A2",
                 external_request_id="SDI-2026-1102-003",
                 state_changed_at=T0 + 12.0, started_at=T0 + 10.0,
                 source_status="failed"),
        TaskNode("T-A2#3", "로봇 현재 자세 확인", NodeState.SUCCEEDED,
                 service_id="vlm_map", accelerator_id="ext-npu-1",
                 node_kind="sense", attempt=3, origin_node_id="T-A2",
                 external_request_id="SDI-2026-1102-003",
                 state_changed_at=T0 + 38.0, started_at=T0 + 36.0,
                 progress_ratio=1.0, source_status="done"),
    )

    graph = TaskGraph(
        mission_id="MSN-261027-01",
        nodes=nodes,
        reference_edges=(
            ReferenceEdge("T-B1", "T-A3", "repeat", "fail"),
        ),
    )

    resources = LayeredResourceView(
        accelerators=(
            AcceleratorInstance("cpu", kind="cpu", attachment="builtin",
                                utilization=Measurement(0.41, "ratio", T0 + 60.0),
                                temperature=Measurement(58.0, "celsius", T0 + 60.0)),
            AcceleratorInstance("igpu", kind="igpu", attachment="builtin",
                                utilization=Measurement(0.22, "ratio", T0 + 60.0),
                                temperature=Measurement(54.0, "celsius", T0 + 60.0)),
            AcceleratorInstance("npu-xdna", kind="npu", attachment="builtin",
                                vendor_label="XDNA",
                                utilization=Measurement(0.67, "ratio", T0 + 60.0),
                                temperature=Measurement(61.0, "celsius", T0 + 60.0)),
            AcceleratorInstance("ext-npu-1", kind="npu", attachment="external",
                                vendor_label="mobilint",
                                utilization=Measurement(0.73, "ratio", T0 + 60.0),
                                temperature=Measurement(66.0, "celsius", T0 + 60.0)),
            AcceleratorInstance("ext-npu-2", kind="npu", attachment="external",
                                vendor_label="deepx",
                                utilization=Measurement(0.88, "ratio", T0 + 60.0),
                                temperature=Measurement(71.0, "celsius", T0 + 60.0)),
            # 예비. 배치된 서비스가 없어도 목록에서 빠지지 않는다(§4.1·§4.4).
            AcceleratorInstance("ext-npu-3", kind="npu", attachment="external",
                                utilization=Measurement(0.0, "ratio", T0 + 60.0),
                                temperature=Measurement(44.0, "celsius", T0 + 60.0)),
        ),
        # [E′] 지표는 서비스에 붙는다 — 지표가 어느 서비스·가속기에서 나왔는지를
        # 화면이 되짚을 수 있어야 한다는 §4.5 요구의 자료구조 쪽 대응이다.
        services=(
            ServiceRuntime("orchestrator", "cpu", role="그래프 생성·노드 배정·판정"),
            ServiceRuntime("video_preprocess", "igpu", role="카메라 입력 디코딩·정규화"),
            ServiceRuntime("vla", "npu-xdna", role="행동 명령 생성",
                           model_name="vla-base", model_version="0.4.1",
                           indicators=_indicators_of("vla")),
            ServiceRuntime("vlm_map", "ext-npu-1", role="공간 지도·경로",
                           model_name="vlm-map", model_version="1.2.0",
                           indicators=_indicators_of("vlm_map")),
            ServiceRuntime("vlm", "ext-npu-2", role="장면 이해·물체 인식",
                           model_name="clip-gate", model_version="2026.10.3",
                           indicators=_indicators_of("vlm")),
        ),
        board=BoardResources(
            memory_utilization=Measurement(0.62, "ratio", T0 + 60.0),
            power=Measurement(38.4, "watt", T0 + 60.0),
            power_trend=(
                Measurement(31.0, "watt", T0 + 30.0),
                Measurement(35.2, "watt", T0 + 45.0),
                Measurement(38.4, "watt", T0 + 60.0),
            ),
        ),
    )

    verdicts = (
        NodeVerdict(
            "T-A3",
            completion=(
                ConditionItem("all_eight_angles_observed", False, "4_of_8"),
                ConditionItem("target_found_in_any_angle", True, "found_at_270deg"),
            ),
            failure=(
                ConditionItem("scan_timeout", False),
                ConditionItem("camera_frozen", False),
            ),
            resource=(
                ConditionItem("accelerator_temperature_within_limit", True),
                # 판정할 근거가 없는 조건. 참으로 세지 않는다.
                ConditionItem("board_power_headroom", None, "not_measured"),
            ),
        ),
        NodeVerdict(
            "T-A2#2",
            completion=(ConditionItem("pose_estimated", False, "no_pedestal_in_frame"),),
            failure=(ConditionItem("sim_real_mismatch", True, "passed_in_sim_failed_on_hardware"),),
            resource=(ConditionItem("accelerator_available", True),),
            escalated_request_id="SDI-2026-1102-003",
        ),
        NodeVerdict(
            "T-C1",
            completion=(ConditionItem("weight_estimate_available", False, "no_provider"),),
            failure=(ConditionItem("no_on_device_capability", True, "missing_required_capability"),),
            resource=(),
            escalated_request_id="SDI-2026-1102-007",
        ),
    )

    requests = ExternalRequestLog(
        mission_id="MSN-261027-01",
        requests=(
            # 1단계(판정) 시각도 남긴다 — 레코드 존재만으로 판정 사실은 알지만
            # **언제** 판정했는지는 전이를 한 번 적어야 남는다(§4.9 1단계 "판정 시각").
            ExternalRequest(
                request_id="SDI-2026-1102-007",
                reason=RequestReason.UNSUPPORTED_CAPABILITY,
                reason_detail="무게 추정 capability 가 온디바이스에 없다",
                origin_node_id="T-C1",
            )
            .advance(RequestStage.JUDGED, at=T0 + 40.5)
            .advance(RequestStage.SENT, at=T0 + 41.0)
            .advance(RequestStage.SERVER_WORKING, at=T0 + 42.0),
            # 6단계까지 간 요청 하나. 배포 버전·재실행 회차·최종 판정이 다 찬 모양을
            # 예제가 보여 주어야 화면이 그 칸들을 비워 둔 채로 만들어지지 않는다.
            ExternalRequest(
                request_id="SDI-2026-1102-003",
                reason=RequestReason.SIM_REAL_MISMATCH,
                reason_detail="시뮬에서는 자세 추정이 되는데 실물 프레임에서 실패했다",
                origin_node_id="T-A2#2",
            )
            .advance(RequestStage.JUDGED, at=T0 + 13.0)
            .advance(RequestStage.SENT, at=T0 + 13.5)
            .advance(RequestStage.SERVER_WORKING, at=T0 + 14.0)
            .advance(RequestStage.DEPLOYED, at=T0 + 33.0, deployment_version="1.4.2")
            .advance(RequestStage.RE_EXECUTING, at=T0 + 36.0, re_executed_node_id="T-A2#3")
            # settle() 이 6단계 전이와 판정을 함께 한다 — 단계만 올리고 판정을
            # 비워 두는 상태가 생기지 않게 묶여 있다.
            .settle(FinalVerdict.SUCCEEDED, at=T0 + 38.5),
        ),
    )

    events = (
        EventRecord(T0 + 5.0, Severity.INFO, EventKind.EXECUTION, "T-A3 실행 시작", "T-A3", 1),
        EventRecord(T0 + 12.0, Severity.WARN, EventKind.EXECUTION,
                    "T-A2 재실행이 실패했다 (ext-npu-1)", "T-A2#2", 2),
        EventRecord(T0 + 33.0, Severity.INFO, EventKind.EXTERNAL_REQUEST,
                    "배포 1.4.2 수신 — 적용 후 재실행", "T-A2#2", 2, "SDI-2026-1102-003"),
        EventRecord(T0 + 38.5, Severity.INFO, EventKind.EXTERNAL_REQUEST,
                    "재실행 성공 — 요청 종결", "T-A2#3", 3, "SDI-2026-1102-003"),
        EventRecord(T0 + 41.0, Severity.INFO, EventKind.EXTERNAL_REQUEST,
                    "SDI 요청 발신 — 미지원 기능", "T-C1", 1, "SDI-2026-1102-007"),
        EventRecord(T0 + 60.0, Severity.WARN, EventKind.RESOURCE,
                    "ext-npu-2 사용률 0.88 — 임계 0.85 초과"),
    )

    sources = (
        SourceState("ai-sbc-board", "L1", T0 + 60.0,
                    (Region.MISSION_SUMMARY, Region.RESOURCES, Region.VERDICT)),
        SourceState("vla", "L2", T0 + 59.0,
                    (Region.MISSION_SUMMARY, Region.RESOURCES, Region.INDICATORS,
                     Region.NODE_DETAIL)),
        SourceState("vlm_map", "L2", T0 + 58.0,
                    (Region.MISSION_SUMMARY, Region.RESOURCES, Region.INDICATORS,
                     Region.NODE_DETAIL)),
        SourceState("vlm", "L2", T0 + 59.5,
                    (Region.MISSION_SUMMARY, Region.RESOURCES, Region.INDICATORS,
                     Region.NODE_DETAIL)),
        SourceState("orchestrator", "L3", T0 + 60.0,
                    (Region.MISSION_SUMMARY, Region.TASK_GRAPH, Region.EVENTS,
                     Region.NODE_DETAIL, Region.VERDICT, Region.NODE_EVENTS,
                     Region.EXTERNAL_REQUESTS)),
        # 한 번도 받지 못한 소스. 이 소스만 먹이는 구역이 없으므로 다른 구역은
        # 정상이고, 지식·경험 메모리가 비었다는 사실만 남는다(§3 요구사항 5).
        SourceState("knowledge_memory", "L3", None, (Region.VERDICT,)),
    )

    return DashboardSnapshot(
        mission=mission,
        graph=graph,
        resources=resources,
        events=events,
        verdicts=verdicts,
        external_requests=requests,
        sources=sources,
    )


def example_indicators() -> tuple[Indicator, ...]:
    """[E′] 주요 성능 지표. 하나는 **측정 없음**이다 — 미달과 섞이지 않는 자리다."""
    return (
        Indicator(
            name="inference_fps",
            measurement=Measurement(9.4, "fps", T0 + 60.0),
            service_id="vla",
            accelerator_id="npu-xdna",
            target=TargetBaseline(8.0, Direction.AT_LEAST, "fps"),
            trend=(
                Measurement(8.8, "fps", T0 + 30.0),
                Measurement(9.1, "fps", T0 + 45.0),
                Measurement(9.4, "fps", T0 + 60.0),
            ),
        ),
        Indicator(
            name="map_update_interval",
            measurement=Measurement(0.42, "second", T0 + 58.0),
            service_id="vlm_map",
            accelerator_id="ext-npu-1",
            target=TargetBaseline(0.5, Direction.AT_MOST, "second"),
        ),
        Indicator(
            name="scene_latency",
            # 서비스가 대기 상태라 산출되지 않았다. 0 이 아니다(§4.5).
            measurement=Measurement(None, "millisecond"),
            service_id="vlm",
            accelerator_id="ext-npu-2",
            target=TargetBaseline(120.0, Direction.AT_MOST, "millisecond"),
        ),
    )


def example_assignments() -> tuple[Assignment, ...]:
    """모델 배정 2건. 하나는 **후보가 없어 배정되지 않았다**(AI-C-05)."""
    chosen = ModelVersion(
        model_id="clip-gate", version="2026.10.3", capability_kind="scene_understanding",
        verified_hw_tags=frozenset({"npu", "external"}),
        quality=0.81, latency_ms=96.0, memory_mb=1800.0,
    )
    return (
        Assignment(
            device_id="ai-sbc-01", mission_id="MSN-261027-01",
            capability_kind="scene_understanding", assigned=chosen,
            reason=REASON_ASSIGNED,
            rejected=(Rejection("clip-gate@2026.09.1", REASON_SCOPE_HARDWARE),),
        ),
        Assignment(
            device_id="ai-sbc-01", mission_id="MSN-261027-01",
            capability_kind="weight_estimation", assigned=None,
            reason=REASON_NO_CANDIDATE, rejected=(),
        ),
    )


def example_message() -> dict:
    """커밋된 예제와 **같아야 하는** 메시지 한 건."""
    context = MessageContext(
        source_id="orchestrator",
        node_id="ai-sbc-01",
        zone_id="zoneA",
        sequence_id=184,
        timestamp=T0 + 60.0,
        message_id="msg-status-0184",
        session_id="0a1b2c3d4e5f",
        entity_id="MSN-261027-01",
    )
    return status_snapshot_message(
        example_snapshot(), context, assignments=example_assignments(), now=T0 + 60.0
    )


def main(argv: list[str]) -> int:
    message = example_message()
    text = json.dumps(message, ensure_ascii=False, indent=2) + "\n"
    if "--write" in argv:
        EXAMPLE_PATH.write_text(text, encoding="utf-8")
        print(f"wrote {EXAMPLE_PATH}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
