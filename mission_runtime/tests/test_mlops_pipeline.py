"""implements: AI-L-10, AI-L-07, AI-B-11, AI-B-02
covers: 미검증 후보 거부, 이름으로 분기하지 않는 배정, 검증 범위 밖 미배정,
        후보 없음 = 축소/비활성, 제어면 하나가 죽어도 다른 영역에 배포,
        마지막 정상 버전으로의 복구와 계보 기록, 배포 상태·장치 가용성·임무
        결과의 분리, 폐쇄망에서 외부 연결 필수 선언의 거부, 단계적 적용,
        실제 K3s provider 경로(클러스터가 없으면 축소 동작을 확인)

여기서 쓰는 "가짜"는 두 개뿐이고 둘 다 저장소에 이미 있는 것이다 —
`LocalControlSupervisor`(기준 ControlProvider)와
`simulation/backend.py::BackendAvailabilityIntegrator`(백엔드 가용성 판정 대역).
쓸 수 없는 제어면도 새로 만들지 않고 실제 `K3sControlProvider`에 없는 CLI 이름을
주어 만든다 — 축소 동작을 흉내내지 않고 실제 코드 경로로 확인한다.
"""

import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from mission_runtime.contracts.capability import CapabilityState
from mission_runtime.continual.lineage import LearningLineage, LearningState
from mission_runtime.execution.control import LocalControlSupervisor, TargetStatus
from mission_runtime.execution.mission import MissionStatus
from mission_runtime.providers.adapters import ControlProvider
from mission_runtime.providers.k3s import K3sControlProvider
from mission_runtime.runtime.airgap import AirgapPolicy, AssetResolver, ExternalDependency
from mission_runtime.runtime.clusters import ClusterBinding, PlacementRequest
from mission_runtime.runtime.mlops_pipeline import (
    REFUSE_CONTROL_REJECTED,
    REFUSE_EGRESS_REQUIRED,
    REFUSE_NO_ASSIGNMENT,
    REFUSE_NO_CONTROL_PLANE,
    REFUSE_NO_LAST_KNOWN_GOOD,
    REFUSE_NOT_APPROVED,
    REFUSE_LINEAGE_MISMATCH,
    REFUSE_NOT_VALIDATED,
    REFUSE_TERMINAL,
    REFUSE_VERIFICATION_NOT_MET,
    TERMINAL_PHASES,
    TRANSFER_REASON_NOT_RESUMABLE,
    TRANSFER_REASON_REPLACED,
    Deployable,
    DeploymentPhase,
    InFlightMission,
    MissionTransferOutcome,
    MlopsPipeline,
    PromotionScope,
    declared_external_endpoints,
    unit_id_for,
)
from mission_runtime.runtime.model_assignment import (
    REASON_ASSIGNED,
    REASON_SCOPE_HARDWARE,
    REASON_UNMEASURED_NOT_ELIGIBLE,
    DeviceProfile,
    MissionRequirement,
    ModelVersion,
)
from mission_runtime.simulation.backend import BackendAvailabilityIntegrator

KIND = "object_detection"


# --- helpers ---------------------------------------------------------------


def approved_lineage(lineage_id: str = "lin-1", *, cites: str = "1") -> LearningLineage:
    """AI-L-05 검증과 AI-L-06 승인을 모두 통과한 계보.

    각 전이가 actor·근거를 요구하므로 여기서도 생략할 수 없다 — 그 강제가
    `continual/lineage.py`의 것이고 이 경로가 우회하지 않는다는 점이 요지다.

    `cites` 를 받는 이유: 전에는 `"ev-0"` 을 인용했고, 그것은 **아무 버전에 대한
    것도 아닌 계보**였다. 그 상태로는 "계보 A, 버전 B" 를 거절하는 시험을 쓸 수
    없다 — 모든 짝이 어긋난 짝이기 때문이다. 기본값이 배정기가 고르는 버전과
    같아서 기존 호출은 그대로 통과한다.
    """
    lineage = LearningLineage(lineage_id, actor="op", evidence_ref=cites, reason="candidate")
    while lineage.state is not LearningState.APPROVED:
        lineage.advance(actor="op", evidence_ref=cites, reason="stage")
    return lineage


def version(model_id: str, ver: str = "1", *, quality: float = 0.9, latency: float = 20.0,
            memory: float = 256.0, hw: frozenset[str] = frozenset()) -> ModelVersion:
    return ModelVersion(
        model_id=model_id,
        version=ver,
        capability_kind=KIND,
        verified_hw_tags=hw,
        quality=quality,
        latency_ms=latency,
        memory_mb=memory,
    )


def edge_pipeline(**kwargs) -> MlopsPipeline:
    """엣지 한 영역만 있는 기본 구성."""
    return MlopsPipeline(
        [ClusterBinding("zone-edge", LocalControlSupervisor(), frozenset({"zone-edge"}))],
        **kwargs,
    )


DEPLOYABLE = Deployable(
    deployable_id="detector",
    capability_kind=KIND,
    placement=PlacementRequest(required_tags=frozenset({"zone-edge"})),
)
DEVICE = DeviceProfile("dev-1", hw_tags=frozenset({"cpu", "zone-edge"}), memory_mb=2048.0)
REQUIREMENT = MissionRequirement("mission-1", KIND, min_quality=0.5, max_latency_ms=100.0)


def submit(pipeline: MlopsPipeline, *, deployable: Deployable = DEPLOYABLE,
           device: DeviceProfile = DEVICE, requirement: MissionRequirement = REQUIREMENT,
           lineage: LearningLineage | None = None, cites: str = "1"):
    return pipeline.submit(
        deployable,
        device,
        requirement,
        lineage=lineage or approved_lineage(cites=cites),
        actor="operator",
        evidence_ref="ev-deploy",
    )


# --- 검증 관문 (AI-L-05, AI-L-06) -----------------------------------------


@pytest.mark.parametrize(
    "stop_at, expected",
    [
        (LearningState.CANDIDATE, REFUSE_NOT_VALIDATED),
        (LearningState.REVIEWED, REFUSE_NOT_VALIDATED),
        (LearningState.VALIDATED, REFUSE_NOT_APPROVED),
        (LearningState.APPROVAL_PENDING, REFUSE_NOT_APPROVED),
    ],
)
def test_candidate_that_has_not_passed_validation_is_refused_with_a_named_reason(stop_at, expected):
    pipeline = edge_pipeline()
    pipeline.register_version(version("det"))
    lineage = LearningLineage("lin", actor="op", evidence_ref="ev", reason="start")
    while lineage.state is not stop_at:
        lineage.advance(actor="op", evidence_ref="ev", reason="stage")

    status = submit(pipeline, lineage=lineage)

    assert status.phase is DeploymentPhase.REFUSED
    assert status.reason == expected
    # 거부는 장치를 건드리지 않는다 — 제어면에 아무 명령도 가지 않았다.
    assert pipeline.router.audit_log == []
    # 거부된 요청이 계보를 전진시키지 않는다(AI-L-08: 역추적이 거짓이 되면 안 된다).
    assert lineage.state is stop_at


def test_refused_submission_still_leaves_a_record():
    """운영자가 "요청했는데 아무 일도 일어나지 않았다"를 사후에 확인해야 한다."""
    pipeline = edge_pipeline()
    pipeline.register_version(version("det"))
    status = submit(pipeline, lineage=LearningLineage("l", actor="o", evidence_ref="e", reason="r"))

    assert status.deployment_id in pipeline.deployments()
    assert pipeline.status(status.deployment_id).phase is DeploymentPhase.REFUSED


def test_a_deployment_without_a_lineage_is_not_a_shortcut():
    pipeline = edge_pipeline()
    pipeline.register_version(version("det"))
    plan = pipeline.plan(DEPLOYABLE, DEVICE, REQUIREMENT, lineage=None)
    assert plan.refusal_reason == REFUSE_NOT_VALIDATED
    assert plan.would_place is False


def test_an_approval_for_another_version_is_not_an_approval_for_this_one():
    """AI-L-08: 승인은 받았으나 **다른 버전에 대한** 승인이면 통과시키지 않는다.

    이 관문이 없을 때가 더 나빴다 — 계보는 `"ev"` 를, 버전은 `"det@1"` 을 쓰고
    있어서 두 이름이 **아예 만날 수 없었다**. 그래서 어긋난 짝을 쓰는 시험을
    적을 수조차 없었고, 짝이 맞는지 아무도 보지 않은 채 전부 통과했다.
    """
    pipeline = edge_pipeline()
    pipeline.register_version(version("det", "2"))

    plan = pipeline.plan(
        DEPLOYABLE, DEVICE, REQUIREMENT, lineage=approved_lineage(cites="1")
    )

    assert plan.refusal_reason == REFUSE_LINEAGE_MISMATCH
    assert plan.would_place is False
    # 버전이 없는 것과는 다른 사유다 — 승인 자체는 있었다.
    assert plan.refusal_reason != REFUSE_NOT_VALIDATED


def test_the_lineage_may_cite_either_the_version_or_its_reference():
    """`"2"` 와 `"det@2"` 는 같은 것을 가리키는 두 표기다."""
    for cited in ("2", "det@2"):
        pipeline = edge_pipeline()
        pipeline.register_version(version("det", "2"))
        plan = pipeline.plan(
            DEPLOYABLE, DEVICE, REQUIREMENT, lineage=approved_lineage(cites=cited)
        )
        assert plan.refusal_reason is None, cited
        assert plan.would_place is True


# --- 이름으로 분기하지 않는다 (AI-L-10) -----------------------------------


def test_assignment_does_not_branch_on_a_model_name():
    """같은 프로파일, 다른 이름 → 같은 결과. 사유 토큰까지 같아야 한다."""
    outcomes = []
    for model_id in ("aaa-detector", "zzz-detector"):
        pipeline = edge_pipeline()
        pipeline.register_version(version(model_id, quality=0.8, latency=30.0, memory=512.0))
        status = submit(pipeline)
        outcomes.append(status)

    first, second = outcomes
    assert first.phase is second.phase is DeploymentPhase.PLACED
    assert first.reason == second.reason == REASON_ASSIGNED
    assert first.scope is second.scope is PromotionScope.VERIFICATION
    assert first.area_id == second.area_id == "zone-edge"
    assert first.unit_status is second.unit_status is TargetStatus.RUNNING
    # 다른 것은 식별자뿐이다 — 버전마다 다른 실행 단위라는 사실의 결과다.
    assert first.unit_id != second.unit_id


def test_assignment_does_not_branch_on_a_device_name():
    pipeline = edge_pipeline()
    pipeline.register_version(version("det"))
    tags = frozenset({"cpu", "zone-edge"})
    results = [
        submit(pipeline, device=DeviceProfile(device_id, hw_tags=tags, memory_mb=2048.0))
        for device_id in ("robot-left", "robot-right")
    ]
    assert {r.reason for r in results} == {REASON_ASSIGNED}
    assert {r.version_reference for r in results} == {"det@1"}


def test_version_outside_its_verified_scope_is_not_assigned():
    """AI-B-01: 다른 조합에서 잰 성능을 같다고 가정하지 않는다."""
    pipeline = edge_pipeline()
    pipeline.register_version(version("gpu-only", hw=frozenset({"cuda"})))

    plan = pipeline.plan(DEPLOYABLE, DEVICE, REQUIREMENT, lineage=approved_lineage())

    assert plan.assignment.assigned is None
    assert plan.refusal_reason == REFUSE_NO_ASSIGNMENT
    assert ("gpu-only@1", REASON_SCOPE_HARDWARE) in [
        (r.version_reference, r.reason) for r in plan.assignment.rejected
    ]


def test_unmeasured_version_is_not_eligible():
    pipeline = edge_pipeline()
    pipeline.register_version(
        ModelVersion("partial", "1", KIND, quality=0.9)  # 지연·메모리 미측정
    )
    plan = pipeline.plan(DEPLOYABLE, DEVICE, REQUIREMENT, lineage=approved_lineage())
    assert plan.refusal_reason == REFUSE_NO_ASSIGNMENT
    assert [r.reason for r in plan.assignment.rejected] == [REASON_UNMEASURED_NOT_ELIGIBLE]


# --- 후보가 없을 때 (AI-C-05) ---------------------------------------------


@pytest.mark.parametrize(
    "core, expected",
    [(True, CapabilityState.DISABLED), (False, CapabilityState.DEGRADED)],
)
def test_no_fitting_candidate_reduces_or_disables_instead_of_assigning_something(core, expected):
    pipeline = edge_pipeline()
    pipeline.register_version(version("slow", latency=5000.0))  # 예산 밖
    deployable = Deployable(
        deployable_id="detector",
        capability_kind=KIND,
        placement=PlacementRequest(required_tags=frozenset({"zone-edge"})),
        core=core,
    )

    plan = pipeline.plan(deployable, DEVICE, REQUIREMENT, lineage=approved_lineage())

    assert plan.assignment.assigned is None  # 임의 배정이 없다
    assert plan.function_state is expected
    status = submit(pipeline, deployable=deployable)
    assert status.phase is DeploymentPhase.REFUSED
    assert status.unit_id is None


def test_one_function_having_no_candidate_does_not_block_another():
    """선택 기능 결손이 관련 없는 기능의 시작을 막지 않는다(원칙 #4)."""
    pipeline = edge_pipeline()
    pipeline.register_version(version("det"))
    pipeline.register_version(
        ModelVersion("tracker", "1", "tracking", quality=0.7, latency_ms=10.0, memory_mb=64.0)
    )
    tracking_dep = Deployable(
        "tracker", "tracking", PlacementRequest(required_tags=frozenset({"zone-edge"}))
    )

    blocked = submit(
        pipeline,
        deployable=Deployable(
            "segmenter", "segmentation", PlacementRequest(required_tags=frozenset({"zone-edge"}))
        ),
        requirement=MissionRequirement("m", "segmentation"),
    )
    assert blocked.phase is DeploymentPhase.REFUSED

    ok = submit(
        pipeline, deployable=tracking_dep, requirement=MissionRequirement("m", "tracking")
    )
    assert ok.phase is DeploymentPhase.PLACED


# --- 하나의 계약, 여러 오케스트레이터 (AI-B-11) ---------------------------


def test_an_unavailable_control_plane_degrades_only_what_it_owned():
    """제어면 하나가 죽어도 다른 영역의 배포는 그대로 나간다."""
    pipeline = MlopsPipeline(
        [
            # 실제 provider에 없는 CLI를 주면 is_available()이 False다 — 축소
            # 동작을 흉내내지 않고 실제 코드 경로로 만든다.
            ClusterBinding(
                "server",
                K3sControlProvider(kubectl="kubectl-does-not-exist"),
                frozenset({"server", "gpu"}),
            ),
            ClusterBinding("zone-edge", LocalControlSupervisor(), frozenset({"zone-edge"})),
        ]
    )
    pipeline.register_version(version("det"))

    assert pipeline.execution_areas() == ("zone-edge",)

    on_edge = submit(pipeline)
    assert on_edge.phase is DeploymentPhase.PLACED
    assert on_edge.area_id == "zone-edge"

    needs_dead_plane = Deployable(
        "detector-gpu", KIND, PlacementRequest(required_tags=frozenset({"gpu"}))
    )
    refused = submit(pipeline, deployable=needs_dead_plane)
    assert refused.phase is DeploymentPhase.REFUSED
    assert refused.reason == REFUSE_NO_CONTROL_PLANE

    # 죽은 제어면이 이미 돌고 있던 것을 끌고 내려가지 않는다.
    assert pipeline.status(on_edge.deployment_id).unit_status is TargetStatus.RUNNING


def test_adding_an_execution_area_is_a_registration_not_a_code_change():
    pipeline = edge_pipeline()
    pipeline.register_version(version("det"))
    on_prem = Deployable("detector", KIND, PlacementRequest(required_tags=frozenset({"server"})))

    assert submit(pipeline, deployable=on_prem).reason == REFUSE_NO_CONTROL_PLANE

    pipeline.register_execution_area(
        ClusterBinding("central", LocalControlSupervisor(), frozenset({"server"}))
    )
    placed = submit(pipeline, deployable=on_prem)
    assert placed.phase is DeploymentPhase.PLACED
    assert placed.area_id == "central"


def test_registering_an_area_does_not_disturb_what_is_already_running():
    pipeline = edge_pipeline()
    pipeline.register_version(version("det"))
    running = submit(pipeline)
    before = len(pipeline.router.audit_log)

    pipeline.register_execution_area(
        ClusterBinding("central", LocalControlSupervisor(), frozenset({"server"}))
    )

    assert len(pipeline.router.audit_log) == before  # 기록이 넘어오고 새 명령은 없다
    assert pipeline.status(running.deployment_id).unit_status is TargetStatus.RUNNING


def test_a_rejecting_control_plane_is_reported_with_the_providers_own_reason():
    """제어면 거부는 예외가 아니라 사유다. provider의 어휘를 잃지 않는다.

    `LocalControlSupervisor`는 start를 늘 받아들이므로 거부가 나오지 않는다. 실제
    K3s provider의 `missing_image` 경로를 쓰는 편이 흉내보다 정확하다.
    """
    if not cluster_reachable():
        pytest.skip("provider-level rejection path needs a reachable cluster")
    pipeline = MlopsPipeline(
        [ClusterBinding("zone-edge", K3sControlProvider(), frozenset({"zone-edge"}))]
    )
    pipeline.register_version(version("det"))
    status = submit(pipeline)  # control_params에 image가 없다
    assert status.phase is DeploymentPhase.REFUSED
    assert status.reason.startswith(REFUSE_CONTROL_REJECTED)


def test_the_pipeline_names_no_orchestrator():
    """원칙 #1·§3: 상위 경로가 구체 기술 API를 알지 않는다.

    import 목록이 아니라 소스 전체를 본다 — 문자열로 기술 이름을 흘리는 것도
    같은 결합이기 때문이다. 설명으로서의 언급과 구별하려고 코드 줄만 검사한다.
    """
    source = Path(__file__).resolve().parents[1] / "runtime" / "mlops_pipeline.py"
    code = [
        line
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    # docstring 본문은 제외하고 실제 식별자·문자열만 남긴다.
    body = "\n".join(code).lower()
    for forbidden in ("kubectl", "subprocess", "import docker", "containerd"):
        assert forbidden not in body


# --- 단계적 적용 (AI-L-07) ------------------------------------------------


def test_promotion_starts_in_verification_scope_and_widens_one_step_at_a_time():
    pipeline = edge_pipeline()
    pipeline.register_version(version("det"))
    lineage = approved_lineage()
    status = submit(pipeline, lineage=lineage)

    assert status.scope is PromotionScope.VERIFICATION
    assert status.lineage_state is LearningState.DEPLOYED

    status = pipeline.widen(status.deployment_id, actor="op", evidence_ref="ev-1")
    assert status.scope is PromotionScope.LIMITED
    # 검증 모드를 벗어나기 전에는 "운영에서 확인됐다"고 적지 않는다.
    assert status.lineage_state is LearningState.DEPLOYED

    status = pipeline.widen(status.deployment_id, actor="op", evidence_ref="ev-2")
    assert status.scope is PromotionScope.OPERATIONAL
    assert status.lineage_state is LearningState.VERIFIED


def test_widening_is_refused_when_operational_verification_is_not_met():
    pipeline = edge_pipeline()
    pipeline.register_version(version("det"))
    placed = submit(pipeline)

    status = pipeline.widen(
        placed.deployment_id, actor="op", evidence_ref="ev", verification_met=False
    )

    assert status.reason == REFUSE_VERIFICATION_NOT_MET
    assert status.scope is PromotionScope.VERIFICATION  # 그대로 돌고 있다
    assert status.phase is DeploymentPhase.PLACED


def test_the_incumbent_keeps_running_while_the_candidate_is_in_verification_scope():
    """AI-L-07: 기존 정상 버전과 비교해야 하므로 둘이 동시에 돌아야 한다."""
    pipeline = edge_pipeline()
    pipeline.register_version(version("det", "1", quality=0.80))
    first = submit(pipeline)
    for _ in range(2):
        first = pipeline.widen(first.deployment_id, actor="op", evidence_ref="ev")

    pipeline.register_version(version("det", "2", quality=0.95))
    second = submit(pipeline, cites="2")

    assert second.version_reference == "det@2"
    assert pipeline.status(first.deployment_id).unit_status is TargetStatus.RUNNING
    assert second.unit_status is TargetStatus.RUNNING

    second = pipeline.widen(second.deployment_id, actor="op", evidence_ref="ev")
    second = pipeline.widen(second.deployment_id, actor="op", evidence_ref="ev")
    retired = pipeline.status(first.deployment_id)
    assert retired.phase is DeploymentPhase.SUPERSEDED
    assert retired.unit_status is TargetStatus.STOPPED


# --- 복구 (AI-L-07, AI-B-05) ----------------------------------------------


def test_rollback_returns_to_the_last_known_good_and_records_it_in_the_lineage():
    pipeline = edge_pipeline()
    good = version("det", "1", quality=0.80)
    pipeline.register_version(good)
    first = submit(pipeline)
    for _ in range(2):
        first = pipeline.widen(first.deployment_id, actor="op", evidence_ref="ev")

    pipeline.register_version(version("det", "2", quality=0.95))
    candidate_lineage = approved_lineage("lin-2", cites="2")
    second = submit(pipeline, lineage=candidate_lineage)
    for _ in range(2):
        second = pipeline.widen(second.deployment_id, actor="op", evidence_ref="ev")

    assert pipeline.last_known_good(second.deployment_id) == good

    rolled = pipeline.rollback(
        second.deployment_id, actor="op", evidence_ref="ev-rb", reason="quality_regression"
    )

    assert rolled.phase is DeploymentPhase.ROLLED_BACK
    assert rolled.unit_status is TargetStatus.STOPPED
    assert candidate_lineage.state is LearningState.ROLLED_BACK
    assert candidate_lineage.events[-1].reason == "quality_regression"
    # 마지막 정상 버전이 다시 돌고 있다.
    restored = pipeline.status(first.deployment_id)
    assert restored.phase is DeploymentPhase.PLACED
    assert restored.unit_status is TargetStatus.RUNNING
    assert restored.version_reference == "det@1"


def test_rollback_with_no_previous_version_is_withdrawn_not_recovered():
    pipeline = edge_pipeline()
    pipeline.register_version(version("det"))
    only = submit(pipeline)

    status = pipeline.rollback(only.deployment_id, actor="op", evidence_ref="ev", reason="bad")

    assert status.phase is DeploymentPhase.WITHDRAWN
    assert status.reason.endswith(REFUSE_NO_LAST_KNOWN_GOOD)
    assert status.unit_status is TargetStatus.STOPPED


def test_rollback_during_verification_scope_leaves_the_incumbent_untouched():
    """검증 모드에서 되돌리는 것은 기존 버전을 다시 올리는 일이 아니다.

    그때 기존 버전은 **내려간 적이 없다**. 여기에 또 start를 보내면 멱등하지 않은
    provider에서 돌고 있는 기능이 불필요하게 재기동된다.
    """
    pipeline = edge_pipeline()
    pipeline.register_version(version("det", "1", quality=0.80))
    first = submit(pipeline)
    for _ in range(2):
        first = pipeline.widen(first.deployment_id, actor="op", evidence_ref="ev")
    restarts_before = sum(
        1 for e in pipeline.router.audit_log if e.target_id == first.unit_id
    )

    pipeline.register_version(version("det", "2", quality=0.95))
    candidate = submit(pipeline, cites="2")
    rolled = pipeline.rollback(
        candidate.deployment_id, actor="op", evidence_ref="ev", reason="shadow_regression"
    )

    assert rolled.phase is DeploymentPhase.ROLLED_BACK  # 복구할 것이 있었다
    assert pipeline.status(first.deployment_id).phase is DeploymentPhase.PLACED
    assert (
        sum(1 for e in pipeline.router.audit_log if e.target_id == first.unit_id)
        == restarts_before
    )


def test_operations_on_a_terminal_deployment_are_refused():
    pipeline = edge_pipeline()
    pipeline.register_version(version("det"))
    placed = submit(pipeline)
    pipeline.rollback(placed.deployment_id, actor="op", evidence_ref="ev", reason="bad")

    assert pipeline.widen(placed.deployment_id, actor="op", evidence_ref="ev").reason == (
        REFUSE_TERMINAL
    )
    assert pipeline.rollback(
        placed.deployment_id, actor="op", evidence_ref="ev", reason="again"
    ).reason == REFUSE_TERMINAL


# --- 임무 인계·종결 (요구 5, AI-C-19) ------------------------------------


def test_a_mission_in_flight_is_handed_over_when_its_unit_is_replaced():
    pipeline = edge_pipeline()
    first_version = version("det", "1", quality=0.80)
    pipeline.register_version(first_version)
    first = submit(pipeline)
    for _ in range(2):
        first = pipeline.widen(first.deployment_id, actor="op", evidence_ref="ev")

    pipeline.declare_in_flight(
        InFlightMission("survey-1", KIND, unit_id_for("detector", first_version))
    )

    pipeline.register_version(version("det", "2", quality=0.95))
    second = submit(pipeline, cites="2")
    # 검증 모드에서는 끊긴 것이 없다 — 기존 단위가 그대로 돌고 있다.
    assert pipeline.transfers(second.deployment_id) == ()

    for _ in range(2):
        second = pipeline.widen(second.deployment_id, actor="op", evidence_ref="ev")

    transfers = pipeline.transfers(second.deployment_id)
    assert [t.outcome for t in transfers] == [MissionTransferOutcome.HANDED_OVER]
    assert transfers[0].reason == TRANSFER_REASON_REPLACED
    assert transfers[0].to_unit == second.unit_id
    # 인계된 임무는 새 단위에 기대고 있다.
    assert pipeline.in_flight()[0].unit_id == second.unit_id


def test_a_mission_that_cannot_be_resumed_is_terminated_through_a_defined_outcome():
    pipeline = edge_pipeline()
    first_version = version("det", "1", quality=0.80)
    pipeline.register_version(first_version)
    first = submit(pipeline)
    for _ in range(2):
        first = pipeline.widen(first.deployment_id, actor="op", evidence_ref="ev")
    pipeline.declare_in_flight(
        InFlightMission(
            "weld-1", KIND, unit_id_for("detector", first_version), resumable=False
        )
    )

    pipeline.register_version(version("det", "2", quality=0.95))
    second = submit(pipeline, cites="2")
    for _ in range(2):
        second = pipeline.widen(second.deployment_id, actor="op", evidence_ref="ev")

    transfer = pipeline.transfers(second.deployment_id)[0]
    assert transfer.outcome is MissionTransferOutcome.TERMINATED
    assert transfer.reason == TRANSFER_REASON_NOT_RESUMABLE
    assert transfer.to_unit is None
    # 반쯤 실행된 채로 남지 않는다 — 더 이상 진행 중이 아니다.
    assert pipeline.in_flight() == ()


def test_rollback_hands_a_mission_back_to_the_restored_unit():
    pipeline = edge_pipeline()
    good = version("det", "1", quality=0.80)
    pipeline.register_version(good)
    first = submit(pipeline)
    for _ in range(2):
        first = pipeline.widen(first.deployment_id, actor="op", evidence_ref="ev")

    pipeline.register_version(version("det", "2", quality=0.95))
    second = submit(pipeline, cites="2")
    for _ in range(2):
        second = pipeline.widen(second.deployment_id, actor="op", evidence_ref="ev")
    pipeline.declare_in_flight(InFlightMission("survey-2", KIND, second.unit_id))

    rolled = pipeline.rollback(
        second.deployment_id, actor="op", evidence_ref="ev", reason="regression"
    )

    handover = [t for t in rolled.mission_transfers if t.mission_id == "survey-2"]
    assert handover and handover[0].outcome is MissionTransferOutcome.HANDED_OVER
    assert handover[0].to_unit == unit_id_for("detector", good)


# --- 세 값의 분리 (AI-B-05, AI-O-04) --------------------------------------


def test_deployment_status_device_availability_and_mission_outcome_are_three_values():
    backend = BackendAvailabilityIntegrator()
    backend.report("dev-1", task_transport_alive=True, observability_alive=True)
    pipeline = edge_pipeline(availability_source=lambda d: backend.verdict(d).availability)

    first_version = version("det", "1", quality=0.80)
    pipeline.register_version(first_version)
    first = submit(pipeline)
    for _ in range(2):
        first = pipeline.widen(first.deployment_id, actor="op", evidence_ref="ev")
    pipeline.declare_in_flight(
        InFlightMission("m-1", KIND, unit_id_for("detector", first_version), resumable=False)
    )

    pipeline.register_version(version("det", "2", quality=0.95))
    second = submit(pipeline, cites="2")
    for _ in range(2):
        second = pipeline.widen(second.deployment_id, actor="op", evidence_ref="ev")

    # 배포는 성공, 프로세스는 돌고, 장치는 가용, 그런데 임무는 결과 없이 끝났다.
    assert second.phase is DeploymentPhase.PLACED
    assert second.unit_status is TargetStatus.RUNNING
    assert second.device_availability == "AVAILABLE"
    assert second.mission_outcome is MissionStatus.NOT_RUN

    # 장치 가용성이 바뀌어도 배포 단계와 프로세스 상태는 그대로다 — 하나를 다른
    # 것의 근거로 대체하지 않는다.
    backend.report("dev-1", task_transport_alive=False, observability_alive=True)
    again = pipeline.status(second.deployment_id)
    assert again.device_availability == "UNAVAILABLE"
    assert again.phase is DeploymentPhase.PLACED
    assert again.unit_status is TargetStatus.RUNNING
    assert again.mission_outcome is MissionStatus.NOT_RUN


def test_availability_is_consumed_never_recomputed():
    """원칙 #15: AI는 백엔드의 판정을 받아 싣기만 한다."""
    pipeline = edge_pipeline(availability_source=lambda d: "ANYTHING_THE_BACKEND_SAYS")
    pipeline.register_version(version("det"))
    assert submit(pipeline).device_availability == "ANYTHING_THE_BACKEND_SAYS"


def test_an_unknown_availability_is_not_a_failure():
    pipeline = edge_pipeline()  # 가용성 출처 없음
    pipeline.register_version(version("det"))
    status = submit(pipeline)
    assert status.device_availability is None
    assert status.phase is DeploymentPhase.PLACED


def test_an_availability_source_that_raises_does_not_break_the_deployment():
    def broken(_device_id):
        raise RuntimeError("backend down")

    pipeline = edge_pipeline(availability_source=broken)
    pipeline.register_version(version("det"))
    status = submit(pipeline)
    assert status.device_availability is None
    assert status.phase is DeploymentPhase.PLACED


# --- 폐쇄망 (AI-C-16) ------------------------------------------------------


def closed_profile() -> AirgapPolicy:
    resolver = AssetResolver(
        base_locations={"generic": "registry.internal/assets"},
        internal_suffixes=frozenset({".internal"}),
    )
    return AirgapPolicy(resolver, closed_network=True)


def test_a_deployable_that_needs_outbound_internet_is_rejected_under_the_airgapped_profile():
    pipeline = edge_pipeline(airgap=closed_profile())
    pipeline.register_version(version("det"))
    needs_internet = Deployable(
        "detector",
        KIND,
        PlacementRequest(required_tags=frozenset({"zone-edge"})),
        external_dependencies=(
            ExternalDependency("https://api.vendor.example.com/v1", "weights", optional=False),
        ),
    )

    status = submit(pipeline, deployable=needs_internet)

    assert status.phase is DeploymentPhase.REFUSED
    assert status.reason == REFUSE_EGRESS_REQUIRED
    assert pipeline.router.audit_log == []  # 배치 전에 걸러진다


def test_an_optional_outbound_dependency_is_a_reduction_not_a_refusal():
    pipeline = edge_pipeline(airgap=closed_profile())
    pipeline.register_version(version("det"))
    optional_cloud = Deployable(
        "detector",
        KIND,
        PlacementRequest(required_tags=frozenset({"zone-edge"})),
        external_dependencies=(
            ExternalDependency("https://api.vendor.example.com/v1", "nice-to-have"),
        ),
    )

    plan = pipeline.plan(optional_cloud, DEVICE, REQUIREMENT, lineage=approved_lineage())
    status = submit(pipeline, deployable=optional_cloud)

    assert plan.disabled_optional == ("https://api.vendor.example.com/v1",)
    assert status.phase is DeploymentPhase.PLACED


def test_an_internal_endpoint_is_placeable_in_a_closed_network():
    pipeline = edge_pipeline(airgap=closed_profile())
    pipeline.register_version(version("det"))
    internal = Deployable(
        "detector",
        KIND,
        PlacementRequest(required_tags=frozenset({"zone-edge"})),
        external_dependencies=(
            ExternalDependency("https://registry.internal/assets", "weights", optional=False),
        ),
    )
    assert submit(pipeline, deployable=internal).phase is DeploymentPhase.PLACED


def test_declared_outbound_connections_are_visible_before_placement():
    units = (
        Deployable("a", KIND, external_dependencies=(ExternalDependency("https://x.example"),)),
        Deployable("b", KIND, external_dependencies=(ExternalDependency("https://y.example"),)),
    )
    assert declared_external_endpoints(units) == ("https://x.example", "https://y.example")


# --- dry run ---------------------------------------------------------------


def test_the_dry_run_shows_the_assignment_reason_and_changes_nothing():
    pipeline = edge_pipeline()
    pipeline.register_version(version("det", quality=0.9))
    pipeline.register_version(version("det-lite", quality=0.6))

    plan = pipeline.plan(DEPLOYABLE, DEVICE, REQUIREMENT, lineage=approved_lineage())

    assert plan.would_place is True
    assert plan.assignment_reason == REASON_ASSIGNED
    assert plan.assignment.assigned.reference == "det@1"
    assert plan.area_id == "zone-edge"
    # 탈락한 쪽도 사유와 함께 보인다(AI-C-13).
    assert "det-lite@1" in [r.version_reference for r in plan.assignment.rejected]
    # 아무것도 바뀌지 않았다.
    assert pipeline.router.audit_log == []
    assert pipeline.deployments() == ()


def test_the_dry_run_and_the_real_submission_agree():
    pipeline = edge_pipeline()
    pipeline.register_version(version("det"))
    plan = pipeline.plan(DEPLOYABLE, DEVICE, REQUIREMENT, lineage=approved_lineage())
    status = submit(pipeline)
    assert (plan.area_id, plan.unit_id) == (status.area_id, status.unit_id)
    assert plan.assignment.assigned.reference == status.version_reference


def test_the_dry_run_projects_which_missions_would_be_affected():
    pipeline = edge_pipeline()
    first_version = version("det", "1", quality=0.80)
    pipeline.register_version(first_version)
    pipeline.declare_in_flight(
        InFlightMission("m", KIND, unit_id_for("detector", first_version), resumable=False)
    )
    pipeline.register_version(version("det", "2", quality=0.95))

    plan = pipeline.plan(
        DEPLOYABLE, DEVICE, REQUIREMENT, lineage=approved_lineage(cites="2")
    )

    assert [t.outcome for t in plan.mission_transfers] == [MissionTransferOutcome.TERMINATED]
    assert pipeline.in_flight()[0].mission_id == "m"  # 투영은 상태를 바꾸지 않는다


def test_a_capability_kind_mismatch_is_a_programming_error_not_a_silent_assignment():
    pipeline = edge_pipeline()
    pipeline.register_version(version("det"))
    with pytest.raises(ValueError, match="capability_kind"):
        pipeline.plan(DEPLOYABLE, DEVICE, MissionRequirement("m", "tracking"))


# --- 공통 계약 확인 --------------------------------------------------------


def test_the_router_the_pipeline_deploys_through_is_the_common_control_contract():
    pipeline = edge_pipeline()
    assert isinstance(pipeline.router, ControlProvider)
    assert isinstance(LocalControlSupervisor(), ControlProvider)
    assert isinstance(K3sControlProvider(), ControlProvider)


def test_a_deployment_can_only_end_in_a_declared_terminal_phase():
    """"기록 없이 반쯤 실행된 채로" 남는 자리가 없다는 것을 어휘 수준에서 고정한다."""
    assert set(TERMINAL_PHASES) == {
        DeploymentPhase.REFUSED,
        DeploymentPhase.SUPERSEDED,
        DeploymentPhase.ROLLED_BACK,
        DeploymentPhase.WITHDRAWN,
    }
    assert DeploymentPhase.PLACED not in TERMINAL_PHASES


def test_audit_and_trace_stay_separate_through_the_pipeline():
    """AI-B-03: 업무 책임 추적과 기술 지연 추적은 다른 기록이다."""
    pipeline = edge_pipeline(requested_by="mlops-operator")
    pipeline.register_version(version("det"))
    submit(pipeline)
    assert [e.requested_by for e in pipeline.router.audit_log] == ["mlops-operator"]
    assert all(e.latency_ms >= 0 for e in pipeline.router.trace_log)


def test_observability_failure_does_not_stop_a_deployment():
    class BrokenSink:
        def record_event(self, *_args, **_kwargs):
            raise RuntimeError("collector down")

    pipeline = edge_pipeline(observability=BrokenSink())
    pipeline.register_version(version("det"))
    assert submit(pipeline).phase is DeploymentPhase.PLACED


def test_significant_deployment_events_are_recorded_individually():
    class Sink:
        def __init__(self):
            self.events = []

        def record_event(self, name, severity, payload=None):
            self.events.append((name, severity))

    sink = Sink()
    pipeline = edge_pipeline(observability=sink)
    pipeline.register_version(version("det"))
    placed = submit(pipeline)
    pipeline.rollback(placed.deployment_id, actor="op", evidence_ref="ev", reason="bad")
    assert ("mlops.deployment.placed", "info") in sink.events
    assert ("mlops.deployment.rolled_back", "warning") in sink.events


# --- 실제 오케스트레이터 경로 ---------------------------------------------


def cluster_reachable() -> bool:
    if shutil.which("kubectl") is None:
        return False
    try:
        return (
            subprocess.run(
                ["kubectl", "get", "--raw", "/readyz"], capture_output=True, timeout=10
            ).returncode
            == 0
        )
    except (subprocess.TimeoutExpired, OSError):
        return False


needs_cluster = pytest.mark.skipif(
    not cluster_reachable(), reason="no reachable Kubernetes/K3s API"
)

REAL_IMAGE = "busybox:latest"
REAL_PARAMS = {"image": REAL_IMAGE, "command": ["sh", "-c", "sleep 600"]}


def test_without_an_orchestrator_the_path_degrades_instead_of_raising():
    """클러스터가 없는 기계에서도 이 경로는 터지지 않고 사유를 낸다(AI-B-05)."""
    provider = K3sControlProvider(kubectl="kubectl-definitely-absent")
    assert provider.is_available() is False
    pipeline = MlopsPipeline(
        [ClusterBinding("zone-edge", provider, frozenset({"zone-edge"}))]
    )
    pipeline.register_version(version("det"))
    status = submit(pipeline)
    assert status.phase is DeploymentPhase.REFUSED
    assert status.reason == REFUSE_NO_CONTROL_PLANE


@needs_cluster
def test_real_orchestrator_place_replace_and_rollback():
    """같은 공개 API로 실제 클러스터에 올리고, 교체하고, 되돌린다."""
    suffix = uuid.uuid4().hex[:8]
    deployable = Deployable(
        deployable_id=f"mlopstest-{suffix}",
        capability_kind=KIND,
        placement=PlacementRequest(required_tags=frozenset({"zone-edge"})),
        control_params=REAL_PARAMS,
    )
    provider = K3sControlProvider()
    pipeline = MlopsPipeline(
        [ClusterBinding("zone-edge", provider, frozenset({"zone-edge"}))]
    )
    good = version("det", "1", quality=0.80)
    candidate = version("det", "2", quality=0.95)
    units = [unit_id_for(deployable.deployable_id, v) for v in (good, candidate)]
    try:
        pipeline.register_version(good)
        first = submit(pipeline, deployable=deployable)
        assert first.phase is DeploymentPhase.PLACED
        assert provider.wait_ready(first.unit_id, timeout_s=120)
        assert pipeline.status(first.deployment_id).unit_status is TargetStatus.RUNNING
        for _ in range(2):
            first = pipeline.widen(first.deployment_id, actor="op", evidence_ref="ev")

        pipeline.register_version(candidate)
        second = submit(pipeline, deployable=deployable, cites="2")
        assert second.version_reference == "det@2"
        assert provider.wait_ready(second.unit_id, timeout_s=120)
        # 검증 모드에서는 둘이 나란히 돈다(AI-L-07).
        assert provider.get_status(first.unit_id) is TargetStatus.RUNNING

        for _ in range(2):
            second = pipeline.widen(second.deployment_id, actor="op", evidence_ref="ev")
        assert provider.get_status(first.unit_id) is TargetStatus.STOPPED

        rolled = pipeline.rollback(
            second.deployment_id, actor="op", evidence_ref="ev", reason="regression"
        )
        assert rolled.phase is DeploymentPhase.ROLLED_BACK
        assert provider.wait_ready(first.unit_id, timeout_s=120)
        assert provider.get_status(first.unit_id) is TargetStatus.RUNNING
        assert provider.get_status(second.unit_id) is TargetStatus.STOPPED
    finally:
        for unit in units:
            provider.delete(unit)


@needs_cluster
def test_real_orchestrator_rejects_an_image_without_a_digest_when_asked():
    """AI-B-02: 이미지와 구성은 식별 가능한 무결성 정보를 유지한다."""
    suffix = uuid.uuid4().hex[:8]
    deployable = Deployable(
        deployable_id=f"mlopsdigest-{suffix}",
        capability_kind=KIND,
        placement=PlacementRequest(required_tags=frozenset({"zone-edge"})),
        control_params={"image": REAL_IMAGE, "require_image_digest": True},
    )
    provider = K3sControlProvider()
    pipeline = MlopsPipeline(
        [ClusterBinding("zone-edge", provider, frozenset({"zone-edge"}))]
    )
    pipeline.register_version(version("det"))
    try:
        status = submit(pipeline, deployable=deployable)
        assert status.phase is DeploymentPhase.REFUSED
        assert status.reason == f"{REFUSE_CONTROL_REJECTED}:image_digest_required"
    finally:
        provider.delete(unit_id_for(deployable.deployable_id, version("det")))
