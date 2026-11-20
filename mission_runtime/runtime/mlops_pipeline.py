"""검증을 통과한 후보 하나를 그것을 실제로 돌릴 수 있는 실행영역에 올리는, 하나의 경로.

implements: AI-L-10, AI-L-07, AI-B-11, AI-B-02
관련: AI-B-05, AI-C-16, AI-C-19, AI-C-05, AI-L-05, AI-L-06, AI-L-08
tests: tests/test_mlops_pipeline.py

이 모듈은 새 기구가 아니라 **이미 있는 다섯 조각을 잇는 한 줄기**다.

    runtime/model_assignment.py   어느 버전을 어느 조건에 (AI-L-10)
    runtime/airgap.py             이 프로파일에서 올려도 되는가 (AI-C-16)
    runtime/clusters.py           어느 실행영역의 제어면으로 (AI-B-11)
    execution/control.py          올리고 내리는 공통 계약 (AI-B-03)
    continual/lineage.py          그 사실을 어디에 남기는가 (AI-L-08)

운영자의 MLOps 동작("이 모델을 바꿔라", "되돌려라")이 로봇마다 다른 특수 경로로
갈라지지 않게 하는 것이 전부다. 그래서 호출자는 K3s도, Docker도, 노드 이름도
말하지 않는다 — **무엇이 돌아야 하고 어떤 조건이어야 하는지**만 말하고 실행영역은
이 경로가 태그로 찾는다(AI-B-11: "중앙 서버와 모든 엣지가 동일한 오케스트레이터를
설치해야 한다는 전제를 두어서는 안 된다").

일부러 만들지 않은 것
---------------------
1. **두 번째 배정 기구를 만들지 않는다.** 어느 버전이 이 장치·임무에 맞는지는
   `ModelAssigner`가 그대로 판정하고 여기서는 그 결과와 사유를 소비만 한다.
   사유 토큰도 그쪽 어휘를 그대로 쓴다(AI-C-13).
2. **두 번째 상태 기계를 만들지 않는다.** 배포 사실은 `LearningLineage`를
   전진시켜 남긴다. 평행 장부를 따로 들면 "지금 운영에 걸린 버전"이 두 곳에서
   서로 다르게 읽힌다(AI-L-08).
3. **장치 가용성을 재판정하지 않는다.** `availability_source`는 백엔드의 통합
   판정을 받아 그대로 싣는 구멍이다(원칙 #15, AI-O-04).
4. **물리 명령을 내리지 않는다.** 임무 인계·종결은 실행 단위를 멈추고 올리고
   그 사실을 기록하는 일까지다. 액추에이터는 백엔드·하드웨어의 것이다(AI-C-19).
   이 파일에 `HardwareCommandProvider`가 import되지 않는 것이 그 경계다.

왜 낡은 버전이 배치 즉시 내려가지 않는가
----------------------------------------
AI-L-07은 승인된 후보를 "운영 판단에 영향을 주지 않는 검증 모드 또는 제한된
대상에서 **기존 정상 버전과** 결과·자원·오류 상태를 비교"하라고 요구한다. 비교
대상이 이미 내려가 있으면 비교할 것이 없다. 그래서 새 버전은 `VERIFICATION`에서
기존 버전과 **나란히** 올라가고, 기존 버전이 물러나는 것은 적용 범위가
`OPERATIONAL`까지 넓어지는 순간이다. 임무 인계도 그때 일어난다 — 그 전까지는
임무가 기대던 단위가 그대로 돌고 있으므로 끊긴 것이 없다.

세 값을 한 칸에 합치지 않는다
-----------------------------
`DeploymentStatus`는 배포 단계·프로세스 상태·장치 가용성·임무 결과를 **각각**
낸다. AI-B-05가 명시적으로 요구한다: "프로세스의 시작·liveness·readiness와 실제
장치의 운용 상태·안전 상태를 구분해야 하며 하나를 다른 상태의 근거로 대체해서는
안 된다." 임무 결과까지 셋째 축이다 — 배포가 성공했는데 그 배포가 끊은 임무는
결과 없이 끝났을 수 있고, 배포가 거부됐는데 장치는 멀쩡할 수 있다.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum

from mission_runtime.contracts.capability import CapabilityState
from mission_runtime.continual.lineage import LearningLineage, LearningState
from mission_runtime.execution.control import TargetStatus
from mission_runtime.execution.mission import MissionStatus
from mission_runtime.runtime.airgap import AirgapPolicy, ExternalDependency, PlacementVerdict
from mission_runtime.providers.durable_store import DurableStoreProvider
from mission_runtime.runtime.reservation import Lease, ReservationLedger
from mission_runtime.runtime.clusters import (
    ClusterBinding,
    MultiClusterControlProvider,
    PlacementRequest,
)
from mission_runtime.runtime.model_assignment import (
    REASON_ASSIGNED,
    Assignment,
    DeviceProfile,
    MissionRequirement,
    ModelAssigner,
    ModelVersion,
)

# ---------------------------------------------------------------------------
# 거부·사유 토큰.
#
# `clusters.py`와 `airgap.py`가 이미 쓰는 토큰은 새로 만들지 않고 그대로 재사용한다
# — 같은 사실이 경로에 따라 다른 이름으로 읽히면 운영 화면에서 두 가지 일로 보인다.
# ---------------------------------------------------------------------------

#: 계보가 AI-L-05 검증에 아직 도달하지 않았다.
REFUSE_NOT_VALIDATED = "candidate_not_validated"
#: 검증은 통과했지만 관리자 승인(AI-L-06)이 끝나지 않았다.
REFUSE_NOT_APPROVED = "candidate_not_approved"
#: 이미 배포된/되돌려진 계보를 다시 배포 요청했다.
REFUSE_LINEAGE_SPENT = "candidate_lineage_already_resolved"
#: 들고 온 계보가 **올라갈 버전을 든 적이 없다.** 콘솔 경로는 이미 둘째 칸을 없애
#: 이 상태를 표현할 수 없게 했지만(`ModelDesk.apply(version_reference=…)`), 이
#: 모듈은 라이브러리 API 라서 호출자가 여전히 짝을 들고 올 수 있다. 그리고 여기가
#: 둘이 **마지막으로 만나는 자리**다 — 계보 사건을 쓰는 것이 이 모듈이므로,
#: 어긋난 짝으로 쓰이면 적용된 버전에서 역추적이 다른 산출물에 닿는다(AI-L-08).
REFUSE_LINEAGE_MISMATCH = "lineage_never_cited_this_version"
#: 조건에 맞는 버전이 없다. 자세한 탈락 사유는 `plan.assignment.rejected`에 있다.
REFUSE_NO_ASSIGNMENT = "no_assignment_for_conditions"
#: 쓸 수 있는 제어면이 없다. `clusters.py`의 토큰과 같은 값이다.
REFUSE_NO_CONTROL_PLANE = "no_available_control_plane"
#: 폐쇄망에서 필수 외부 연결을 선언했다. `airgap.py::EgressGate`와 같은 값이다.
REFUSE_EGRESS_REQUIRED = "external_connection_required_in_closed_network"
#: 제어면이 start를 거부했다. ':' 뒤에 provider가 준 사유가 붙는다.
REFUSE_CONTROL_REJECTED = "control_plane_rejected"
#: 되돌릴 마지막 정상 버전이 없다.
REFUSE_NO_LAST_KNOWN_GOOD = "no_last_known_good_version"
#: 검증 모드 비교가 기준을 만족하지 못해 적용 범위를 넓히지 않았다.
REFUSE_VERIFICATION_NOT_MET = "operational_verification_not_met"
#: 이미 전체 운영까지 넓혀진 배포를 또 넓히려 했다.
REFUSE_ALREADY_OPERATIONAL = "scope_already_operational"
#: 끝난 배포에 대한 조작.
REFUSE_TERMINAL = "deployment_already_terminal"
#: 이미지가 **배정된 버전이 아닌 것을 싣는다고 선언했다.** 배포는 성공하고 올라간
#: 모델만 다른 상태가 되므로, 그 뒤의 모든 측정·계보·목표 판정이 엉뚱한 버전에
#: 붙는다. 계보 검증(`REFUSE_LINEAGE_MISMATCH`)은 **기록**을 지키고 이것은 **짐**을
#: 지킨다 — 둘 다 필요하다.
REFUSE_IMAGE_VERSION_MISMATCH = "image_does_not_carry_assigned_version"

#: 이미지가 그 버전을 싣는지 **확인했는가**. 세 값이다 — 확인됨 / 선언 없음 / 불일치.
#: "선언 없음" 을 "맞다" 로 적으면 확인하지 않은 것이 확인된 것으로 읽힌다(AI-B-01 의
#: "미측정 항목은 구분해야 한다" 와 같은 규칙).
CARRIAGE_VERIFIED = "verified"
CARRIAGE_NOT_DECLARED = "not_declared"
CARRIAGE_MISMATCH = "mismatch"
#: 선언은 배정과 맞지만 **이미지가 움직이는 태그**다. 실제 k3s 클러스터로 한 번
#: 돌려 보고 알았다(2026-11-20): `mission-runtime:cpu` 태그로 올린 pod 안의 패키지가
#: 어제의 빌드였다 — 선언은 맞았고 짐은 달랐다. 태그는 같은 이름으로 다른 내용을
#: 가리킬 수 있으므로 "맞다" 가 아니라 **확인할 수 없다** 가 정직하다. 배포 묶음
#: 선언을 거치면 digest 고정이 강제되지만(`image_not_pinned_to_digest`),
#: `control_params` 로 이미지를 직접 주는 경로는 그 검사를 지나친다.
CARRIAGE_UNPINNED = "declared_but_image_not_pinned"

DEPLOYMENT_REASONS: tuple[str, ...] = (
    REASON_ASSIGNED,
    REFUSE_NOT_VALIDATED,
    REFUSE_NOT_APPROVED,
    REFUSE_LINEAGE_SPENT,
    REFUSE_LINEAGE_MISMATCH,
    REFUSE_NO_ASSIGNMENT,
    REFUSE_NO_CONTROL_PLANE,
    REFUSE_EGRESS_REQUIRED,
    REFUSE_CONTROL_REJECTED,
    REFUSE_NO_LAST_KNOWN_GOOD,
    REFUSE_VERIFICATION_NOT_MET,
    REFUSE_ALREADY_OPERATIONAL,
    REFUSE_TERMINAL,
)

#: 계보 상태별 거부 사유. 승인 전 상태를 한 토큰으로 뭉개면 운영자가 "검증을 더
#: 해야 하는가"와 "내 승인을 기다리는가"를 구분할 수 없다(AI-L-06).
_LINEAGE_REFUSALS: Mapping[LearningState, str] = {
    LearningState.CANDIDATE: REFUSE_NOT_VALIDATED,
    LearningState.QUARANTINED: REFUSE_NOT_VALIDATED,
    LearningState.REVIEWED: REFUSE_NOT_VALIDATED,
    LearningState.STRATEGY_SELECTED: REFUSE_NOT_VALIDATED,
    LearningState.VALIDATED: REFUSE_NOT_APPROVED,
    LearningState.APPROVAL_PENDING: REFUSE_NOT_APPROVED,
    LearningState.DEPLOYED: REFUSE_LINEAGE_SPENT,
    LearningState.VERIFIED: REFUSE_LINEAGE_SPENT,
    LearningState.ROLLED_BACK: REFUSE_LINEAGE_SPENT,
}


class DeploymentPhase(str, Enum):
    """배포 하나가 있을 수 있는 단계. 프로세스 상태도 임무 결과도 아니다.

    PLACED      해석된 실행영역에서 돌고 있다. 적용 범위는 `scope`가 따로 말한다.
    REFUSED     운영에 도달하지 못했다. 종결 — 장치에는 아무 일도 일어나지 않았다.
    SUPERSEDED  뒤에 온 버전이 운영까지 올라가서 물러났다. 종결.
    ROLLED_BACK 마지막 정상 버전으로 되돌아갔다. 종결.
    WITHDRAWN   되돌릴 정상 버전 없이 내려갔다. 종결.

    `ROLLED_BACK`과 `WITHDRAWN`을 가르는 이유: "검증된 상태로 복구됐다"와 "그냥
    없어졌다"는 운영자에게 완전히 다른 사실이다. 후자를 복구로 적으면 지금 그
    기능을 제공하는 것이 없다는 사실이 가려진다.
    """

    PLACED = "PLACED"
    REFUSED = "REFUSED"
    SUPERSEDED = "SUPERSEDED"
    ROLLED_BACK = "ROLLED_BACK"
    WITHDRAWN = "WITHDRAWN"

    @property
    def is_terminal(self) -> bool:
        return self is not DeploymentPhase.PLACED


#: 배포가 끝날 수 있는 종결 단계 전부.
TERMINAL_PHASES: tuple[DeploymentPhase, ...] = tuple(
    phase for phase in DeploymentPhase if phase.is_terminal
)


class PromotionScope(str, Enum):
    """AI-L-07 단계적 적용. 승인된 것이 곧 전체 운영 적용은 아니다.

    VERIFICATION 운영 판단에 영향을 주지 않는 검증 모드. 기존 버전과 나란히 돈다.
    LIMITED      제한된 대상에만.
    OPERATIONAL  검증된 적용 범위 전체. 이때 기존 버전이 물러난다.
    """

    VERIFICATION = "VERIFICATION"
    LIMITED = "LIMITED"
    OPERATIONAL = "OPERATIONAL"


#: 넓히는 순서. 건너뛰기를 허용하지 않는 이유는 AI-L-07이 요구한 그대로다 —
#: "검증된 적용 범위를 벗어나 바로 전체 운영에 적용하지 않는다."
_WIDENING: Mapping[PromotionScope, PromotionScope | None] = {
    PromotionScope.VERIFICATION: PromotionScope.LIMITED,
    PromotionScope.LIMITED: PromotionScope.OPERATIONAL,
    PromotionScope.OPERATIONAL: None,
}


def next_scope(scope: PromotionScope) -> PromotionScope | None:
    """한 칸 넓힌 범위. 더 넓힐 곳이 없으면 None.

    공개하는 이유: 운영 화면이 "다음에 어디로 넓어지는가"를 적으려면 이 순서를
    알아야 하고, 화면이 자기 표를 따로 들면 건너뛰기 금지가 두 곳에 적히게 된다.
    """
    return _WIDENING[scope]


class MissionTransferOutcome(str, Enum):
    """진행 중이던 임무가 배포 때문에 끝나는 방식.

    HANDED_OVER 같은 기능을 올린 새 실행 단위가 이어받았다.
    TERMINATED  이어받을 단위가 없거나 이어받을 수 없다고 선언돼 종결했다.
    RETAINED    이 배포가 그 임무가 기대던 단위를 건드리지 않았다.

    셋 중 하나가 **반드시** 기록된다. 요구는 결과가 좋을 것이 아니라 "기록 없이
    반쯤 실행된 채로 남지 않을 것"이다.
    """

    HANDED_OVER = "HANDED_OVER"
    TERMINATED = "TERMINATED"
    RETAINED = "RETAINED"


#: 임무가 그렇게 끝난 사유 토큰.
TRANSFER_REASON_REPLACED = "unit_replaced_by_deployment"
TRANSFER_REASON_NOT_RESUMABLE = "mission_declared_not_resumable"
TRANSFER_REASON_NO_SUCCESSOR = "no_successor_unit_for_kind"
TRANSFER_REASON_UNTOUCHED = "unit_not_affected"

TRANSFER_REASONS: tuple[str, ...] = (
    TRANSFER_REASON_REPLACED,
    TRANSFER_REASON_NOT_RESUMABLE,
    TRANSFER_REASON_NO_SUCCESSOR,
    TRANSFER_REASON_UNTOUCHED,
)


# ---------------------------------------------------------------------------
# 선언 자료형
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Deployable:
    """배포될 기능 하나. 전부 선언이고 판정이 없다.

    `placement`가 실행영역을 고르는 **유일한** 입력이다. 클러스터 id도 노드
    이름도 여기 없고 태그만 있다 — 다른 오케스트레이터를 쓰는 실행영역이 늘어도
    이 자료형은 그대로다(AI-B-11).

    `control_params`는 현재 provider가 해석하는 값(이미지 참조, 노드 선택자 등)이
    그대로 지나가는 통로다. 상위 코드가 그 키의 뜻을 알 필요가 없다는 것이 요점이고,
    자격증명은 여기에 담지 않는다 — 비밀정보를 이미지와 구성에 넣지 않는다는
    AI-B-02의 규칙은 이 사전에도 그대로 적용된다.
    """

    deployable_id: str
    capability_kind: str
    placement: PlacementRequest = field(default_factory=PlacementRequest)
    #: 선언된 외부 연결. 폐쇄망 프로파일이 배치 **전에** 본다(AI-C-16).
    external_dependencies: tuple[ExternalDependency, ...] = ()
    control_params: Mapping[str, object] = field(default_factory=dict)
    #: 핵심 기능인가. 후보가 없을 때 DISABLED(핵심)와 DEGRADED(선택)를 가른다.
    core: bool = False
    #: **이 이미지가 싣는다고 선언한 모델 버전 참조**(`det@v1`). 선언이고 관측이
    #: 아니다 — 이미지 안을 들여다보지 않는다. `None` 은 "그 이미지가 어느 버전을
    #: 싣는지 말하지 않았다" 이고 "아무 버전도 싣지 않는다" 가 아니다.
    carries_model: str | None = None

    def __post_init__(self) -> None:
        if not self.deployable_id or not self.capability_kind:
            raise ValueError("deployable_id and capability_kind must not be empty")


@dataclass(frozen=True)
class InFlightMission:
    """지금 어떤 실행 단위에 기대고 있는 임무.

    `resumable`은 선언이다 — 이 경로가 임무 내용을 들여다보고 "이어받을 수 있다"를
    추론하지 않는다. 추론하면 그것이 두 번째 임무 판단 기구가 된다(AI-C-19).
    """

    mission_id: str
    capability_kind: str
    unit_id: str
    resumable: bool = True


@dataclass(frozen=True)
class MissionTransfer:
    """임무 하나가 배포를 통과한 결과."""

    mission_id: str
    outcome: MissionTransferOutcome
    from_unit: str
    to_unit: str | None
    reason: str

    @property
    def mission_status(self) -> MissionStatus | None:
        """임무 자체의 결과. 배포 단계와 다른 축이다.

        인계된 임무는 아직 끝나지 않았으니 결과가 `None`이다 — 성공이 아니다.
        종결된 임무는 요구 항목의 결과가 없으므로 `NOT_RUN`이고, 그것이
        `execution/mission.py`가 이미 쓰는 어휘다(새 어휘를 만들지 않는다).
        """
        if self.outcome is MissionTransferOutcome.TERMINATED:
            return MissionStatus.NOT_RUN
        return None


@dataclass(frozen=True)
class DeploymentPlan:
    """"지금 submit하면 무슨 일이 일어나는가". 아무것도 바꾸지 않는다.

    운영자는 커밋 전에 배정 사유를 봐야 한다(AI-C-13). 그래서 이 자료형은
    `submit()`이 실제로 쓰는 것과 **같은 계산**에서 나온다 — dry run과 실제가
    따로 계산되면 둘이 조용히 갈라지고, 그때 틀리는 쪽은 언제나 화면이다.
    """

    deployable_id: str
    assignment: Assignment
    #: 해석된 실행영역. 호출자가 고른 것이 아니라 태그로 찾아진 것이다.
    area_id: str | None
    unit_id: str | None
    egress: PlacementVerdict
    #: 후보가 없을 때 이 기능이 놓이는 상태(AI-C-05). 임의 배정의 자리가 아니다.
    function_state: CapabilityState
    refusal_reason: str | None
    #: 이 배포가 **운영까지 올라갔을 때** 진행 중 임무가 받을 결과. 배치 즉시가
    #: 아닌 이유는 모듈 docstring의 "왜 낡은 버전이 배치 즉시 내려가지 않는가".
    mission_transfers: tuple[MissionTransfer, ...] = ()
    #: 폐쇄망에서 꺼지는 선택 외부 의존. 거부가 아니라 축소다(AI-C-16).
    disabled_optional: tuple[str, ...] = ()
    #: 이미지가 배정된 버전을 싣는지 확인한 결과(세 값).
    version_carriage: str = CARRIAGE_NOT_DECLARED

    @property
    def would_place(self) -> bool:
        return self.refusal_reason is None

    @property
    def assignment_reason(self) -> str:
        """왜 이 버전인가 / 왜 아무것도 아닌가. `ModelAssigner`의 어휘 그대로."""
        return self.assignment.reason


@dataclass(frozen=True)
class DeploymentStatus:
    """배포 하나의 지금. 네 축을 **각각** 낸다(AI-B-05).

    - `phase`/`scope`       배포 자체가 어디까지 왔는가
    - `unit_status`         제어면이 보는 프로세스 상태. 장치 운용 상태가 아니다
    - `device_availability` 백엔드의 통합 판정을 받아 실은 것. 여기서 만들지 않는다
    - `mission_outcome`     이 배포가 끊은 임무의 결과. 배포 성공과 독립이다

    하나가 비었다고 다른 것을 끌어다 채우지 않는다. `None`은 "모름"이고 그것은
    "정상"도 "실패"도 아니다.
    """

    deployment_id: str
    deployable_id: str
    phase: DeploymentPhase
    scope: PromotionScope
    unit_status: TargetStatus | None
    device_availability: str | None
    mission_outcome: MissionStatus | None
    lineage_state: LearningState | None
    area_id: str | None
    unit_id: str | None
    version_reference: str | None
    reason: str | None
    mission_transfers: tuple[MissionTransfer, ...] = ()
    #: 이미지가 그 버전을 싣는지 확인한 결과(세 값). `not_declared` 는 **확인하지
    #: 않았다**는 사실이고 통과가 아니다.
    version_carriage: str | None = None


@dataclass(frozen=True)
class FleetRequest:
    """한 장치에 올릴 실행 단위 하나.

    **장치마다 계보가 따로다.** 한 계보를 N 번 전진시키면 어느 장치의 배포가 어느
    승인에 기댔는지 되짚을 수 없고(AI-L-08), 장치마다 배정되는 버전이 다를 수
    있으므로 하나의 계보가 모두를 정직하게 가리킬 수도 없다.
    """

    device: DeviceProfile
    deployable: Deployable
    lineage: LearningLineage


@dataclass(frozen=True)
class FleetEntry:
    """함대 배포 한 건의 결과. 장치와 단위를 **함께** 들고 있다 —
    `DeploymentStatus` 는 장치를 모르고, 그것이 그 자료형의 경계다."""

    device_id: str
    deployable_id: str
    status: DeploymentStatus

    @property
    def placed(self) -> bool:
        return self.status.phase is not DeploymentPhase.REFUSED


@dataclass(frozen=True)
class FleetOutcome:
    """여러 장치에 한 번에 요청한 결과.

    **부분 실패가 정상이다.** 통행 예약(`runtime/space_reservation.py`)이 경로를
    전부 아니면 전무로 잡는 것과 반대인데, 이유가 다르기 때문이다: 통행은 한
    로봇의 한 경로라 절반만 쥐면 교착이 생기고, 함대 배포는 **서로 다른 장치의
    독립 기능**이라 하나가 못 올라가도 나머지가 올라가는 것이 정상 축소다
    (AI-C-05). 한 대 때문에 전부 되돌리면 그것이 장애 전파다.
    """

    entries: tuple[FleetEntry, ...] = ()

    @property
    def placed(self) -> tuple[FleetEntry, ...]:
        return tuple(entry for entry in self.entries if entry.placed)

    @property
    def refused(self) -> tuple[FleetEntry, ...]:
        return tuple(entry for entry in self.entries if not entry.placed)

    def for_device(self, device_id: str) -> tuple[FleetEntry, ...]:
        return tuple(entry for entry in self.entries if entry.device_id == device_id)

    def reasons(self) -> dict[str, str | None]:
        """단위별 사유. **거절만 모으지 않는다** — 올라간 것의 사유(`assigned`)도
        같은 표에 있어야 "왜 이 버전인가" 를 한 자리에서 읽는다(AI-C-13)."""
        return {entry.deployable_id: entry.status.reason for entry in self.entries}

    def versions(self) -> dict[str, str | None]:
        """단위별로 **실제 배정된 버전**. 여러 모델을 한 함대에 섞어 올린 결과가
        여기서 드러난다(AI-L-10)."""
        return {entry.deployable_id: entry.status.version_reference
                for entry in self.entries}


@dataclass
class _Record:
    """가변 상태는 여기 한 곳에만 둔다. 밖으로는 frozen 스냅샷만 나간다."""

    deployment_id: str
    deployable: Deployable
    device_id: str
    plan: DeploymentPlan
    phase: DeploymentPhase
    scope: PromotionScope
    lineage: LearningLineage | None
    version: ModelVersion | None
    area_id: str | None
    unit_id: str | None
    reason: str | None
    #: 이 배포가 대체하려는 직전 배포의 id. 되돌림의 목적지이기도 하다.
    supersedes: str | None = None
    transfers: list[MissionTransfer] = field(default_factory=list)


_UNSAFE = re.compile(r"[^a-z0-9]+")


def _image_pinned(image: object) -> bool:
    """그 이미지 참조가 **변하지 않는 것**을 가리키나(digest 고정).

    맞춤법은 `runtime/deployment_bundle.py::ImageRef.pinned` 와 같고, 그 자료형을
    import 하지 않는 이유는 그 모듈이 이 모듈의 `Deployable` 을 import 하기 때문이다
    (순환이 된다). 글자가 둘로 갈라지지 않게 **같은 한 가지**만 본다 —
    `providers/k3s.py` 의 `require_image_digest` 검사도 같은 글자다.
    """
    return isinstance(image, str) and "@sha256:" in image


def unit_id_for(deployable_id: str, version: ModelVersion) -> str:
    """버전마다 다른 실행 단위 id.

    같은 id로 이미지만 갈아끼우지 않는 이유가 둘이다. 첫째, AI-L-07의 검증 모드는
    새 버전과 **기존 버전을 동시에** 돌려 비교하는 것이므로 둘이 같은 단위일 수
    없다. 둘째, 새 버전이 올라오는 순간과 낡은 버전이 내려가는 순간이 구분돼야 그
    사이에 걸쳐 있던 임무를 인계·종결로 처리할 수 있다. 한 id를 덮어쓰면 그 경계가
    사라지고 임무는 "기록 없이 반쯤 실행된" 상태가 된다. `device_deployment.py`도
    provider가 바뀌면 낡은 unit을 멈추고 새 unit을 올리는 쪽을 택했다.

    소문자·숫자·하이픈만 남긴다 — 현재 오케스트레이터 provider가 이 문자열을 자원
    이름으로 쓰기 때문이고, 그 제약을 provider 안에서 뒤늦게 터뜨리지 않는다.
    """
    raw = f"{deployable_id}-{version.model_id}-{version.version}"
    return _UNSAFE.sub("-", raw.lower()).strip("-")


class MlopsPipeline:
    """검증된 후보 → 실행영역 해석 → 배치 → 계보. 하나의 계약, 여러 오케스트레이터.

    실행영역을 늘리는 일은 `register_execution_area()`에 `ClusterBinding` 하나를
    더하는 것이고 이 클래스는 수정되지 않는다(원칙 #7). binding은 `ControlProvider`
    계약만 요구하므로 K3s든 systemd든 아직 없는 무엇이든 같은 자리에 들어간다.
    """

    def __init__(
        self,
        areas: Sequence[ClusterBinding] = (),
        *,
        assigner: ModelAssigner | None = None,
        airgap: AirgapPolicy | None = None,
        availability_source: Callable[[str], object] | None = None,
        observability: object | None = None,
        store: DurableStoreProvider | None = None,
        reservations: ReservationLedger | None = None,
        requested_by: str = "mlops_pipeline",
    ) -> None:
        self._areas: list[ClusterBinding] = list(areas)
        self._router = MultiClusterControlProvider(self._areas)
        self.assigner = assigner or ModelAssigner()
        self._airgap = airgap
        self._availability = availability_source
        self._observability = observability
        #: 내구 저장(AI-B-05 · AI-L-08). **없으면 축소다** — 판정은 그대로이고
        #: 재시작을 넘지 못할 뿐이며, 그 사실은 `durability` 가 말한다(AI-C-05).
        self._store = store
        #: 자원 예약(AI-B-04 · AI-L-10). 없으면 선점 없이 배정만 한다 — 단일 노드
        #: 배치의 정상 동작이고, 다중 노드에서는 주는 것이 맞다.
        self._reservations = reservations
        self._leases: dict[str, Lease] = {}
        self._requested_by = requested_by
        self._records: dict[str, _Record] = {}
        self._in_flight: dict[str, InFlightMission] = {}
        self._sequence = 0

    # --- 실행영역 등록 (AI-B-11) ------------------------------------------
    def register_execution_area(self, binding: ClusterBinding) -> None:
        """실행영역 하나를 더한다. 오케스트레이터 종류는 묻지 않는다.

        라우터를 다시 만들면서 감사·추적 기록은 넘겨받는다. 이미 돌고 있는 실행
        단위에는 아무 제어 호출도 가지 않는다 — 영역이 늘었다는 사실이 돌고 있는
        기능을 건드려야 할 이유는 없다(AI-B-11).
        """
        self._areas.append(binding)
        previous = self._router
        self._router = MultiClusterControlProvider(self._areas)
        self._router.audit_log.extend(previous.audit_log)
        self._router.trace_log.extend(previous.trace_log)

    def execution_areas(self) -> tuple[str, ...]:
        """지금 쓸 수 있는 실행영역. 제어면이 죽은 영역은 여기 없다."""
        return tuple(self._router.available_clusters())

    @property
    def router(self) -> MultiClusterControlProvider:
        """공통 제어 계약 자체. 감사(업무 책임)·추적(기술 지연) 기록을 읽을 때 쓴다."""
        return self._router

    # --- 등록 --------------------------------------------------------------
    def register_version(self, version: ModelVersion) -> None:
        """배정 후보를 더한다. 검증 범위는 버전 자신이 들고 있다(AI-B-01)."""
        self.assigner.register(version)

    def declare_in_flight(self, mission: InFlightMission) -> None:
        self._in_flight[mission.mission_id] = mission

    def in_flight(self) -> tuple[InFlightMission, ...]:
        return tuple(self._in_flight.values())

    # --- dry run -----------------------------------------------------------
    def plan(
        self,
        deployable: Deployable,
        device: DeviceProfile,
        requirement: MissionRequirement,
        *,
        lineage: LearningLineage | None = None,
    ) -> DeploymentPlan:
        """커밋하지 않고 결과를 본다. `submit()`이 쓰는 것과 같은 계산이다.

        거부 사유를 찾는 순서에 뜻이 있다. 계보 → 배정 → 폐쇄망 → 제어면 순으로
        보는 것은 **싼 거절을 먼저, 바깥 세계를 건드리는 판정을 나중에** 하기
        위해서다. 미검증 후보 때문에 제어면을 깨울 이유가 없다.
        """
        if deployable.capability_kind != requirement.capability_kind:
            # 조용히 다른 kind의 버전을 배정해 주는 쪽이 훨씬 나쁘다 — 그렇게 되면
            # 배포는 성공했는데 올라간 기능이 요청한 기능이 아니다.
            raise ValueError(
                "deployable and requirement disagree on capability_kind: "
                f"{deployable.capability_kind!r} != {requirement.capability_kind!r}"
            )

        refusal = self._lineage_refusal(lineage)

        assignment = self.assigner.assign(device, requirement)
        if refusal is None and not assignment.is_assigned:
            refusal = REFUSE_NO_ASSIGNMENT

        version = assignment.assigned
        # 버전이 정해진 **뒤에** 짝을 본다. 배정 전에는 무엇과 견줄지 모른다.
        # 유도로 바꿀 수 없는 이유: 버전은 배정기가 고르고 계보는 호출자가 들고
        # 오며, 그 버전의 승격 기록은 이 모듈이 소유하지 않는다. 그래서 여기서는
        # 검증이 유일한 길이고, `capability_kind` 불일치를 이미 거절하는 것과
        # 같은 자리에 둔다.
        if refusal is None and lineage is not None and version is not None:
            if not (lineage.cites(version.version) or lineage.cites(version.reference)):
                refusal = REFUSE_LINEAGE_MISMATCH

        # **이미지가 그 버전을 싣는지 본다.** 배정기는 "어느 버전이 조건에 맞는가" 를
        # 답하고 이미지는 "무엇이 실제로 올라가는가" 다 — 둘이 어긋나면 배포는
        # 성공하고 올라간 모델만 다르다. 선언이 없으면 확인할 수 없고, 확인할 수
        # 없는 것을 "맞다" 로 적지 않는다.
        carriage = CARRIAGE_NOT_DECLARED
        if version is not None and deployable.carries_model:
            if deployable.carries_model != version.reference:
                carriage = CARRIAGE_MISMATCH
                if refusal is None:
                    refusal = REFUSE_IMAGE_VERSION_MISMATCH
            elif _image_pinned(deployable.control_params.get("image")):
                carriage = CARRIAGE_VERIFIED
            else:
                # 선언은 맞는데 태그가 움직인다 — **거절하지는 않는다**(태그 배포가
                # 정상인 배치가 있다). 다만 확인된 것으로 적지 않는다.
                carriage = CARRIAGE_UNPINNED
        unit_id = unit_id_for(deployable.deployable_id, version) if version else None

        egress = self._egress_verdict(deployable)
        if refusal is None and not egress.placeable and egress.blocking_dependencies:
            refusal = REFUSE_EGRESS_REQUIRED

        # 실행영역 해석은 마지막이고, 여기서 영역 "이름"이 아니라 태그로 찾는다.
        # 제어면이 하나 죽어도 다른 영역의 후보는 그대로 나온다(AI-B-11).
        binding = self._router.select_cluster(deployable.placement)
        if refusal is None and binding is None:
            refusal = REFUSE_NO_CONTROL_PLANE

        return DeploymentPlan(
            deployable_id=deployable.deployable_id,
            assignment=assignment,
            area_id=binding.cluster_id if binding else None,
            unit_id=unit_id,
            egress=egress,
            function_state=self._function_state(deployable, assignment, refusal),
            refusal_reason=refusal,
            mission_transfers=self._projected_transfers(deployable, unit_id),
            disabled_optional=egress.disabled_optional,
            version_carriage=carriage,
        )

    # --- 배포 --------------------------------------------------------------
    def submit(
        self,
        deployable: Deployable,
        device: DeviceProfile,
        requirement: MissionRequirement,
        *,
        lineage: LearningLineage,
        actor: str,
        evidence_ref: str,
    ) -> DeploymentStatus:
        """검증된 후보 하나를 배포한다. 거부도 기록을 남기고 끝난다.

        거부에 기록을 남기는 것은 장식이 아니다 — 운영자가 "요청했는데 아무 일도
        일어나지 않았다"를 사후에 확인할 수 있어야 하고, 그것이 AI-O-02가 말하는
        "선택 기능이 없는 정상적인 축소 운용과 핵심 기능 실패를 구분"의 전제다.
        """
        plan = self.plan(deployable, device, requirement, lineage=lineage)
        self._sequence += 1
        deployment_id = f"{deployable.deployable_id}#{self._sequence}"

        if not plan.would_place:
            return self._refuse(deployment_id, deployable, device, plan, plan.refusal_reason)

        version = plan.assignment.assigned
        assert version is not None and plan.unit_id is not None  # would_place가 보장한다

        # **올리기 전에 잡는다.** 순서를 뒤집으면 둘이 같은 가속기에 올라가고,
        # 그 실패는 배정 로그 어디에도 이유가 없다(AI-B-04 · AI-L-10).
        lease = self._reserve(plan, deployment_id)
        if lease is not None and not hasattr(lease, "token"):
            reason = f"{REFUSE_CONTROL_REJECTED}:{getattr(lease, 'reason', 'reservation_refused')}"
            return self._refuse(deployment_id, deployable, device, plan, reason)

        result = self._router.request(
            "start",
            plan.unit_id,
            self._start_params(deployable),
            requested_by=self._requested_by,
        )
        if not result.accepted:
            self._unreserve(deployment_id)        # 못 올렸으면 쥐고 있을 이유가 없다
            reason = f"{REFUSE_CONTROL_REJECTED}:{result.rejection_reason}"
            return self._refuse(deployment_id, deployable, device, plan, reason)

        # 실제로 올라간 뒤에야 계보를 전진시킨다. 순서를 뒤집으면 제어면이 거부한
        # 배포가 계보에는 DEPLOYED로 남고, AI-L-08의 역추적이 거짓이 된다.
        lineage.advance(
            actor=actor,
            evidence_ref=evidence_ref,
            reason=f"placed:{version.reference}@{plan.area_id}",
        )

        record = _Record(
            deployment_id=deployment_id,
            deployable=deployable,
            device_id=device.device_id,
            plan=plan,
            phase=DeploymentPhase.PLACED,
            # 승인된 것이 곧 전체 운영이 아니다. 검증 모드에서 시작한다(AI-L-07).
            scope=PromotionScope.VERIFICATION,
            lineage=lineage,
            version=version,
            area_id=self._router.cluster_of(plan.unit_id) or plan.area_id,
            unit_id=plan.unit_id,
            reason=REASON_ASSIGNED,
            supersedes=self._incumbent(deployable.deployable_id),
        )
        self._records[deployment_id] = record
        self._event("mlops.deployment.placed", "info", record)
        return self.status(deployment_id)

    # --- 함대: 여러 모델 × 여러 노드 (AI-L-10 · AI-B-04 · AI-B-11) ---------
    def plan_fleet(
        self,
        requests: Sequence[FleetRequest],
        requirement: MissionRequirement,
    ) -> dict[str, DeploymentPlan]:
        """커밋하지 않고 **함대 전체**를 본다. `submit_fleet` 과 같은 계산이다.

        운영자가 "지금 올리면 몇 대가 되고 어느 대가 왜 안 되는가" 를 커밋 전에
        봐야 한다(AI-C-13). dry run 과 실제가 따로 계산되면 둘이 조용히 갈라지고,
        그때 틀리는 쪽은 언제나 화면이다.
        """
        return {request.deployable.deployable_id:
                self.plan(request.deployable, request.device, requirement,
                          lineage=request.lineage)
                for request in self._ordered(requests)}

    def submit_fleet(
        self,
        requests: Sequence[FleetRequest],
        requirement: MissionRequirement,
        *,
        actor: str,
        evidence_ref: str,
    ) -> FleetOutcome:
        """여러 장치에 한 번에 배포한다. **하나가 거절돼도 나머지는 계속한다.**

        순서는 입력 순서가 아니라 `(device_id, deployable_id)` 정렬 순이다 — 같은
        입력에 같은 결과여야 하고, 자원이 하나뿐일 때 "누가 먼저 잡는가" 가 호출
        순서에 따라 달라지면 재현할 수 없는 배포가 된다(AI-L-10 의 "같은 입력에
        같은 순서").

        예약 장부가 있으면 선점은 `submit()` 안에서 일어난다 — 여기서 다시 잡지
        않는다. 같은 실행영역을 두 단위가 노리면 둘째는 사유와 함께 거절되고
        첫째는 그대로 돈다.
        """
        seen: set[str] = set()
        entries: list[FleetEntry] = []
        for request in self._ordered(requests):
            unit = request.deployable.deployable_id
            if unit in seen:
                # 같은 id 로 둘을 올리면 **뒤의 것이 앞의 것을 가린다** — 그것은
                # 축소가 아니라 선언 오류이므로 조용히 넘기지 않는다.
                raise ValueError(f"duplicate deployable_id in fleet request: {unit!r}")
            seen.add(unit)
            status = self.submit(request.deployable, request.device, requirement,
                                 lineage=request.lineage, actor=actor,
                                 evidence_ref=evidence_ref)
            entries.append(FleetEntry(request.device.device_id, unit, status))
        return FleetOutcome(tuple(entries))

    @staticmethod
    def _ordered(requests: Sequence[FleetRequest]) -> list[FleetRequest]:
        return sorted(requests, key=lambda r: (r.device.device_id,
                                               r.deployable.deployable_id))

    # --- 단계적 적용 (AI-L-07) --------------------------------------------
    def widen(
        self,
        deployment_id: str,
        *,
        actor: str,
        evidence_ref: str,
        verification_met: bool = True,
    ) -> DeploymentStatus:
        """적용 범위를 한 칸 넓힌다. 한 칸씩인 것이 요구사항이다.

        `verification_met=False`는 실패가 아니라 "아직"이다 — 배포는 현재 범위에서
        그대로 돌고 넓히지 않은 사유만 남는다. 회귀가 확인된 경우는 넓히지 않는
        것이 아니라 `rollback()`이다.

        `OPERATIONAL`에 도달할 때 비로소 기존 버전이 물러나고 그 단위에 기대던
        임무가 인계 또는 종결된다.
        """
        record = self._require(deployment_id)
        if record.phase.is_terminal:
            return self._status_with_reason(record, REFUSE_TERMINAL)

        nxt = next_scope(record.scope)
        if nxt is None:
            return self._status_with_reason(record, REFUSE_ALREADY_OPERATIONAL)
        if not verification_met:
            return self._status_with_reason(record, REFUSE_VERIFICATION_NOT_MET)

        record.scope = nxt
        record.reason = f"widened:{nxt.value}"
        if nxt is PromotionScope.OPERATIONAL:
            self._retire_incumbent(record)
            # 전체 운영까지 간 것이 계보의 VERIFIED다. 검증 모드에서 도는 동안을
            # VERIFIED로 적으면 "운영에서 확인됐다"가 거짓이 된다.
            if record.lineage is not None and record.lineage.state is LearningState.DEPLOYED:
                record.lineage.advance(
                    actor=actor, evidence_ref=evidence_ref, reason="operational_scope"
                )
        return self.status(deployment_id)

    # --- 복구 (AI-L-07, AI-B-05) ------------------------------------------
    def rollback(
        self, deployment_id: str, *, actor: str, evidence_ref: str, reason: str
    ) -> DeploymentStatus:
        """마지막 정상 버전으로 되돌린다.

        순서가 "정상 버전을 먼저 올리고 그다음 현재 것을 내린다"인 이유: 반대로
        하면 그 사이 동안 이 기능을 제공하는 단위가 하나도 없고, 그 틈에 걸친
        임무는 이어받을 곳이 없어 전부 종결된다.

        되돌릴 정상 버전이 없으면 그것을 조용히 복구로 적지 않는다. 현재 것을
        내리고 `WITHDRAWN`으로 끝낸다.
        """
        record = self._require(deployment_id)
        if record.phase.is_terminal:
            return self._status_with_reason(record, REFUSE_TERMINAL)

        target = self._records.get(record.supersedes) if record.supersedes else None
        restored_unit = self._restore(target) if target is not None else None

        if record.unit_id and record.unit_id != restored_unit:
            self._router.request("stop", record.unit_id, requested_by=self._requested_by)

        if restored_unit is None:
            record.phase = DeploymentPhase.WITHDRAWN
            record.reason = f"{reason}:{REFUSE_NO_LAST_KNOWN_GOOD}"
        else:
            record.phase = DeploymentPhase.ROLLED_BACK
            record.reason = reason

        # 되돌아갔다는 사실은 계보에 남는다 — 평행 장부를 따로 들지 않는 이유가
        # 이 한 줄이다(AI-L-08).
        if record.lineage is not None and record.lineage.state in (
            LearningState.DEPLOYED,
            LearningState.VERIFIED,
        ):
            record.lineage.rollback(actor=actor, evidence_ref=evidence_ref, reason=reason)

        self._unreserve(deployment_id)            # 되돌렸으면 자원을 놓는다
        retired_unit = record.unit_id
        if retired_unit:
            record.transfers.extend(
                self._settle_missions(record.deployable, restored_unit, retired_unit)
            )
        self._event("mlops.deployment.rolled_back", "warning", record)
        return self.status(deployment_id)

    # --- 조회 --------------------------------------------------------------
    def deployments(self) -> tuple[str, ...]:
        return tuple(self._records)

    def status(self, deployment_id: str) -> DeploymentStatus:
        return self._snapshot(self._require(deployment_id))

    def transfers(self, deployment_id: str) -> tuple[MissionTransfer, ...]:
        return tuple(self._require(deployment_id).transfers)

    def last_known_good(self, deployment_id: str) -> ModelVersion | None:
        """이 배포가 되돌아갈 버전. 없으면 `None`이고 그때 되돌림은 `WITHDRAWN`이다."""
        record = self._require(deployment_id)
        target = self._records.get(record.supersedes) if record.supersedes else None
        return target.version if target is not None else None

    # --- 내부: 판정 --------------------------------------------------------
    def _lineage_refusal(self, lineage: LearningLineage | None) -> str | None:
        """AI-L-05/06을 통과하지 않은 후보는 운영에 닿지 않는다.

        `None` 계보는 "미검증"으로 읽는다. 계보 없이 배포되는 길을 열어두면 검증
        관문이 선택 사항이 된다.
        """
        if lineage is None:
            return REFUSE_NOT_VALIDATED
        if lineage.state is LearningState.APPROVED:
            return None
        return _LINEAGE_REFUSALS.get(lineage.state, REFUSE_NOT_VALIDATED)

    def _egress_verdict(self, deployable: Deployable) -> PlacementVerdict:
        if self._airgap is None:
            return PlacementVerdict(deployable.deployable_id, True)
        return self._airgap.evaluate(
            deployable.deployable_id, list(deployable.external_dependencies)
        )

    @staticmethod
    def _function_state(
        deployable: Deployable, assignment: Assignment, refusal: str | None
    ) -> CapabilityState:
        """후보가 없을 때 이 기능이 놓이는 상태(AI-C-05).

        여기가 "임의 배정"의 자리가 아니라는 것이 요점이다. 핵심 기능이면 그
        기능만 DISABLED이고 선택 기능이면 축소(DEGRADED)다. 어느 쪽도 다른 기능의
        시작·실행·복구를 막지 않는다.
        """
        if refusal is None and assignment.is_assigned:
            return CapabilityState.ACTIVE
        return CapabilityState.DISABLED if deployable.core else CapabilityState.DEGRADED

    def _start_params(self, deployable: Deployable) -> dict:
        """provider에 넘기는 값. `placement`는 라우터가 소비하고 나머지는 그대로 간다."""
        params = dict(deployable.control_params)
        params["placement"] = deployable.placement
        return params

    def _incumbent(self, deployable_id: str) -> str | None:
        """같은 기능으로 지금 올라가 있는 배포. 비교 대상이자 되돌림의 목적지다."""
        for deployment_id in reversed(list(self._records)):
            record = self._records[deployment_id]
            if (
                record.deployable.deployable_id == deployable_id
                and record.phase is DeploymentPhase.PLACED
            ):
                return deployment_id
        return None

    def _retire_incumbent(self, record: _Record) -> None:
        """기존 버전을 운영에서 물린다. 이것이 "대체"가 실제로 일어나는 지점이다."""
        incumbent = self._records.get(record.supersedes) if record.supersedes else None
        if incumbent is None or incumbent.phase is not DeploymentPhase.PLACED:
            return
        if incumbent.unit_id:
            self._router.request("stop", incumbent.unit_id, requested_by=self._requested_by)
        incumbent.phase = DeploymentPhase.SUPERSEDED
        incumbent.reason = f"superseded_by:{record.deployment_id}"
        if incumbent.unit_id:
            record.transfers.extend(
                self._settle_missions(record.deployable, record.unit_id, incumbent.unit_id)
            )
        self._event("mlops.deployment.superseded", "info", incumbent)

    def _restore(self, target: _Record) -> str | None:
        """되돌림 목적지를 다시 운영에 세운다. 이미 돌고 있으면 제어 호출이 없다.

        검증 모드에서 되돌리는 경우 기존 버전은 **내려간 적이 없다** — 그때 start를
        또 보내면 멱등하지 않은 provider에서 불필요한 재기동이 된다.
        """
        if target.unit_id is None:
            return None
        if target.phase is DeploymentPhase.PLACED:
            return target.unit_id
        restore = self._router.request(
            "start",
            target.unit_id,
            self._start_params(target.deployable),
            requested_by=self._requested_by,
        )
        if not restore.accepted:
            return None
        target.phase = DeploymentPhase.PLACED
        target.reason = "restored_as_last_known_good"
        return target.unit_id

    # --- 내부: 임무 인계·종결 ---------------------------------------------
    def _projected_transfers(
        self, deployable: Deployable, new_unit: str | None
    ) -> tuple[MissionTransfer, ...]:
        """dry run용 예정 결과. 상태를 바꾸지 않는다."""
        return tuple(
            self._decide_transfer(mission, new_unit)
            for mission in self._in_flight.values()
            if mission.capability_kind == deployable.capability_kind
        )

    def _settle_missions(
        self, deployable: Deployable, new_unit: str | None, retired_unit: str
    ) -> list[MissionTransfer]:
        """내려간 단위에 기대던 임무를 하나씩 결론 낸다. 결론 없이 남는 임무는 없다.

        인계는 "다른 단위가 같은 기능을 제공한다"는 사실의 기록이고 물리 동작이
        아니다(AI-C-19). 실제 재개는 임무를 소유한 쪽이 한다.
        """
        settled: list[MissionTransfer] = []
        for mission in list(self._in_flight.values()):
            if mission.capability_kind != deployable.capability_kind:
                continue
            if mission.unit_id != retired_unit:
                continue
            transfer = self._decide_transfer(mission, new_unit)
            settled.append(transfer)
            if transfer.outcome is MissionTransferOutcome.HANDED_OVER and new_unit:
                self._in_flight[mission.mission_id] = InFlightMission(
                    mission_id=mission.mission_id,
                    capability_kind=mission.capability_kind,
                    unit_id=new_unit,
                    resumable=mission.resumable,
                )
            else:
                self._in_flight.pop(mission.mission_id, None)
        return settled

    @staticmethod
    def _decide_transfer(mission: InFlightMission, new_unit: str | None) -> MissionTransfer:
        if mission.unit_id == new_unit:
            return MissionTransfer(
                mission.mission_id,
                MissionTransferOutcome.RETAINED,
                mission.unit_id,
                new_unit,
                TRANSFER_REASON_UNTOUCHED,
            )
        if new_unit is None:
            return MissionTransfer(
                mission.mission_id,
                MissionTransferOutcome.TERMINATED,
                mission.unit_id,
                None,
                TRANSFER_REASON_NO_SUCCESSOR,
            )
        if not mission.resumable:
            return MissionTransfer(
                mission.mission_id,
                MissionTransferOutcome.TERMINATED,
                mission.unit_id,
                None,
                TRANSFER_REASON_NOT_RESUMABLE,
            )
        return MissionTransfer(
            mission.mission_id,
            MissionTransferOutcome.HANDED_OVER,
            mission.unit_id,
            new_unit,
            TRANSFER_REASON_REPLACED,
        )

    # --- 내부: 기록 --------------------------------------------------------
    def _refuse(
        self,
        deployment_id: str,
        deployable: Deployable,
        device: DeviceProfile,
        plan: DeploymentPlan,
        reason: str | None,
    ) -> DeploymentStatus:
        record = _Record(
            deployment_id=deployment_id,
            deployable=deployable,
            device_id=device.device_id,
            plan=plan,
            phase=DeploymentPhase.REFUSED,
            scope=PromotionScope.VERIFICATION,
            lineage=None,  # 거부된 요청은 계보를 전진시키지 않는다
            version=None,
            area_id=plan.area_id,
            unit_id=None,
            reason=reason,
        )
        self._records[deployment_id] = record
        # 거부는 집계 주기를 기다리지 않는 개별 사건이다(AI-O-02).
        self._event("mlops.deployment.refused", "warning", record)
        return self._snapshot(record)

    def _require(self, deployment_id: str) -> _Record:
        record = self._records.get(deployment_id)
        if record is None:
            raise KeyError(f"unknown deployment {deployment_id!r}")
        return record

    def _snapshot(self, record: _Record) -> DeploymentStatus:
        return self._status_with_reason(record, record.reason)

    def _status_with_reason(self, record: _Record, reason: str | None) -> DeploymentStatus:
        return DeploymentStatus(
            deployment_id=record.deployment_id,
            deployable_id=record.deployable.deployable_id,
            phase=record.phase,
            scope=record.scope,
            unit_status=self._unit_status(record),
            device_availability=self._device_availability(record.device_id),
            mission_outcome=self._mission_outcome(record),
            lineage_state=record.lineage.state if record.lineage else None,
            area_id=record.area_id,
            unit_id=record.unit_id,
            version_reference=record.version.reference if record.version else None,
            reason=reason,
            mission_transfers=tuple(record.transfers),
            version_carriage=record.plan.version_carriage if record.plan else None,
        )

    def _unit_status(self, record: _Record) -> TargetStatus | None:
        """제어면이 보는 프로세스 상태. 장치 운용 상태로 읽어서는 안 된다(AI-B-05)."""
        if record.unit_id is None:
            return None
        try:
            return self._router.get_status(record.unit_id)
        except Exception:
            # 제어면을 지금 물어볼 수 없는 것은 "멈춤"이 아니라 "모름"이다.
            # STOPPED로 적으면 그것이 곧 장애 판정으로 읽힌다.
            return None

    def _device_availability(self, device_id: str) -> str | None:
        """백엔드의 통합 판정을 받아 그대로 싣는다. 여기서 만들지 않는다(원칙 #15)."""
        if self._availability is None:
            return None
        try:
            verdict = self._availability(device_id)
        except Exception:
            return None
        if verdict is None:
            return None
        return str(getattr(verdict, "value", verdict))

    @staticmethod
    def _mission_outcome(record: _Record) -> MissionStatus | None:
        """이 배포가 끊은 임무의 결과. 배포 성공과 독립이다.

        하나라도 종결된 임무가 있으면 그것이 이 축의 값이다 — 인계된 임무는 아직
        결과가 없고, 없음은 성공이 아니다.
        """
        for transfer in record.transfers:
            if transfer.mission_status is not None:
                return transfer.mission_status
        return None

    def _event(self, name: str, severity: str, record: _Record) -> None:
        self._persist(name, record)
        sink = getattr(self._observability, "record_event", None)
        if sink is None:
            return
        try:
            sink(
                name,
                severity,
                {
                    "deployment_id": record.deployment_id,
                    "deployable_id": record.deployable.deployable_id,
                    "phase": record.phase.value,
                    "scope": record.scope.value,
                    "area_id": record.area_id,
                    "unit_id": record.unit_id,
                    "reason": record.reason,
                },
            )
        except Exception:
            # 관측 경로 장애가 배포를 멈추지 않는다(AI-O-01/02).
            pass

    def _reserve(self, plan, deployment_id: str):
        """실행영역을 잡는다. 예약 장부가 없으면 `None` — **선점 없는 배정은 정상이다**.

        잡는 대상이 `area_id` 인 이유: 지금 계약에서 "어디에 올리는가" 의 단위가
        그것이다. 가속기 개체까지 좁히려면 장부에 그 id 로 자원을 선언하고 계획이
        그것을 들고 오면 되며, **이 코드는 바뀌지 않는다**(자원 id 는 데이터다).
        """
        if self._reservations is None or not plan.area_id:
            return None
        outcome = self._reservations.acquire(plan.area_id, holder=deployment_id)
        if hasattr(outcome, "token"):
            confirmed = self._reservations.confirm(outcome)
            self._leases[deployment_id] = confirmed
            return confirmed
        return outcome

    def _unreserve(self, deployment_id: str) -> None:
        lease = self._leases.pop(deployment_id, None)
        if lease is not None and self._reservations is not None:
            self._reservations.release(lease)

    def lease_of(self, deployment_id: str) -> Lease | None:
        """이 배포가 쥔 lease. fencing token 을 실행 쪽에 넘길 때 쓴다."""
        return self._leases.get(deployment_id)

    def _persist(self, name: str, record: _Record) -> None:
        """사실과 그 발행 예약을 **한 커밋**으로. 저장 장애는 배포를 멈추지 않는다.

        여기 한 곳인 이유: 사건이 나가는 자리가 `_event` 하나이므로 그 옆에 두면
        배포·되돌림·거부·승계 **모든 경로**가 자동으로 남는다. 경로마다 따로 적으면
        언젠가 한 곳을 빠뜨리고, 빠뜨린 그 경로가 하필 사후에 궁금한 것이 된다.
        """
        if self._store is None:
            return
        payload = {
            "deployment_id": record.deployment_id,
            "deployable_id": record.deployable.deployable_id,
            "phase": record.phase.value,
            "scope": record.scope.value,
            "area_id": record.area_id,
            "unit_id": record.unit_id,
            "reason": record.reason,
            "version": record.version.reference if record.version else None,
            "supersedes": record.supersedes,
        }
        try:
            with self._store.transaction() as tx:
                tx.put("deployment", record.deployment_id, payload)
                tx.enqueue(name, aggregate_id=record.deployment_id, payload=payload)
        except Exception:
            return


def declared_external_endpoints(deployables: Iterable[Deployable]) -> tuple[str, ...]:
    """폐쇄망 프로파일이 배치 **전에** 볼 수 있는, 선언된 외부 연결 전부.

    AI-C-16은 "어떤 실행 단위가 외부 연결을 요구하는지는 등록 정보로 드러나야
    하며 폐쇄망 프로파일에서는 배치 전에 이를 검증할 수 있어야 한다"고 요구한다.
    그 검증을 돌릴 때 필요한 목록이 이것이고, 선언 그대로 낸다.
    """
    return tuple(
        sorted(
            {
                dependency.endpoint
                for deployable in deployables
                for dependency in deployable.external_dependencies
            }
        )
    )
