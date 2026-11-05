"""여러 장치가 본 것을 한 장의 구역 그림으로 모으고, 그것이 틀렸을 때 **누가 틀렸는지**
되짚고 사람이 고칠 수 있게 한다.

implements: AI-S-02 (다중 관측 객체 연계), AI-S-06 (이종 모델 결과의 점진적 객체 레코드),
            AI-L-01 (학습 후보 선별), AI-L-03 (사용자 확인·의미 정보 반영)
관련: AI-C-02 (좌표계 경계), AI-C-19 (판단·권한 경계), AI-S-03, AI-S-04, AI-L-08
tests: tests/test_fms_fusion.py

## 두 가지 일을 한 모듈에 둔 이유

(A) 융합과 (B) 추적·수정은 같은 자료를 쓴다. 융합이 버린 것은 되짚을 수 없고, 되짚을
수 없으면 사람이 고칠 대상을 가리킬 수 없다. 그래서 융합이 **출처를 버리지 않는 것**이
이 모듈의 설계 조건이고, 추적·수정 기능은 그 조건이 지켜졌을 때 공짜로 따라 나온다.

## 이 모듈이 소유하지 않는 것 — 먼저 적는다

* **전역 좌표를 만들지 않는다.** 산출 위치는 구역 로컬 평면(`FRAME_ZONE_LOCAL`)뿐이고
  `coordinate_frame` 은 항상 `ZONE` 이다. 전역 승격과 authoritative 디지털 트윈 상태는
  백엔드 몫이다(AI-C-02, AI-C-19). 공개 이름 어디에도 `global` 이 없는 것은 우연이 아니다.
* **모델을 바꾸지 않는다.** 사람의 수정은 레코드에 **즉시** 반영되지만 모델 파라미터는
  건드리지 않는다. 수정은 `HUMAN_CONFIRMED` 학습 후보 1건과 `CANDIDATE` 계보 1건을 남기고
  끝난다 — 승격은 기존 AI-L-05 검증과 AI-L-07 단계적 적용이 한다(AI-L-03).
* **장치의 최종 가용성을 판정하지 않는다.** `set_device_available()` 로 **받아** 쓴다.
* **관측된 쪽의 개체 식별을 하지 않는다.** 이 모듈의 `device_id` 는 언제나 **본 쪽**,
  즉 근거를 만든 관측 장치다. 보인 쪽이 어느 개체인가는 `perception/device_identity.py`
  의 일이고 거기서 외형은 종류만 가린다 — 여기서 외형으로 개체를 묶는 코드는 없다.

## 조립한 것들 — 어려운 부분은 이미 남이 갖고 있다

```
DeviceDetection(영상 좌표)
    │ project_detection()  — 선언된 배치 + 방위 + 거리 → 구역 로컬 위치
    ▼
ObservedTrack ──CrossSourceLinker.usable_evidence()──▶ 지금 써도 되는 근거 종류만 남긴다
    │                                                  (AI-S-02: 시간·공간·외형은 선택이다)
    │ GlobalTrajectoryAssociator.associate()  — 쌍 비교가 아니라 **집계와 비교**
    ▼
object_id ──Evidence──▶ ProgressiveRecordBuilder  — 비동기 결과의 점진적 누적(AI-S-06)
    │                     RecordResolver          — 기하·클래스 해석의 **유일한** 수식
    ▼
FusedRecord + 자체 근거 원장(ContributedEvidence) ──▶ trace() / 수정 ──▶ CandidateStore
                                                                        LearningLineage
```

`RecordResolver` 는 반사실 계산에도 **그대로** 쓴다(`_resolve_counterfactual`). 영향도를
손으로 평균 내면 그 평균이 실제 융합 수식과 어긋나는 날이 오고, 그때 추적은 거짓말을
시작한다. 같은 수식을 부분집합에 다시 돌리는 편이 유일하게 안전하다.

## 중복·의존 근거를 독립 확인으로 세지 않는다 (AI-S-06)

같은 `(장치, 프레임)` 에서 나온 두 결과는 **한 번 본 것**이다. 탐지기와 분류기가 같은
프레임을 각각 읽었다고 해서 그 프레임이 두 번 관측된 것이 되지는 않는다. 그래서
`(device_id, frame_ref)` 당 **대표 1건**만 공간 근거(`kind="region"`)로 올리고, 뒤따르는
것은 `depends_on` 으로 선행 근거를 가리키며 의미 근거(`kind="semantic"`)로만 들어간다.
이 규칙이 없으면 한 장치가 같은 프레임을 여러 번 보내 융합 위치를 끌어갈 수 있고, 그것은
관측이 아니라 중복이다.

## 없는 제공자는 반대 근거가 아니다 (AI-C-05)

등록만 되고 아무것도 보내지 않은 장치는 기여자 목록에도, 지지 수에도 없다. 음수 기여가
아니라 **무기여**다. 사라진 장치의 근거는 `available_groups` 로 걸러지지만 그 장치가 이미
밝힌 클래스 입장은 `object_record` 의 규칙대로 유지된다 — 사라짐이 표가 되면 안 된다.

## 영향도 순위는 점수가 아니라 반사실이다

"지금 값이 틀렸다. 누가 끌고 갔나, 얼마나?" 에 답해야 하므로 순위는 **그 장치의 근거를
빼면 값이 어디로 가는가**(leave-one-out)로 정한다. 지분(가중치)만 보면 "많이 보낸 장치"가
늘 1등이 되고 실제로 값을 끌어간 장치는 가려진다. 질문이 위치인지 클래스인지는
`trace(about=...)` 로 받는다 — 질문이 다르면 범인도 다르기 때문이다.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Callable, Iterable, Mapping, Sequence

from mission_runtime.continual.lineage import LearningLineage, LearningState
from mission_runtime.continual.stream_learning import (
    CandidateOrigin,
    CandidateStore,
    InputConditions,
    StreamSample,
)
from mission_runtime.perception.association import ObservedTrack
from mission_runtime.perception.cross_view_association import GlobalTrajectoryAssociator
from mission_runtime.perception.environment_map import (
    Anchor,
    EnvironmentMapEstimator,
    MapElement,
    StructureEvidence,
)
from mission_runtime.perception.multisource import CrossSourceLinker
from mission_runtime.perception.obstacle_taxonomy import ObstacleTaxonomy
from mission_runtime.contracts.evidence_contract import (
    MissionContract,
    RequiredEvidence,
)
from mission_runtime.contracts.capability import CapabilityState
from mission_runtime.decision.info_request import DecisionSupportRequester
from mission_runtime.perception.info_selection import AdditionalInfoSelector
from mission_runtime.perception.object_record import (
    CONFIRMING_GROUPS,
    UNKNOWN_CLASS,
    Evidence,
    Lifecycle,
    ObjectRecord,
    ProgressiveRecordBuilder,
)
from mission_runtime.perception.uncertainty import UncertaintyEvaluator
from mission_runtime.registry.capability_registry import CapabilityRegistry
from mission_runtime.risk.adjustment import ObservationLevelAdjuster
from mission_runtime.runtime.perception_loop import (
    LoopResult,
    PerceptionLoop,
    RecordInput,
    RecordOutcome,
)

#: 이 모듈이 내는 유일한 기하 좌표계. `object_record.Evidence.frame_id` 자리에 들어간다.
FRAME_ZONE_LOCAL = "zone"
#: 데이터 사전의 `coordinate_frame` 어휘 중 이 모듈이 쓰는 값. GLOBAL 로 올리는 것은
#: 백엔드 소관이므로 여기서는 나올 수 없다(AI-C-02).
COORDINATE_FRAME_ZONE = "ZONE"

#: `CrossSourceLinker` 의 근거→capability 사상. 기본값은 공간 근거를
#: `coordinates.global` 로 묶지만 우리는 구역 로컬 좌표만 쓰므로 바꿔 끼운다 —
#: 그 사상이 생성자 인자인 이유가 바로 이것이다.
ZONE_EVIDENCE_CAPABILITIES: Mapping[str, str] = {
    "time": "sync.time",
    "space": "coordinates.zone_local",
    "appearance": "reid.embedding",
}

#: 공간 근거 없이도 돌 수 있어야 하므로 기본 가용 집합에 외형은 넣지 않는다.
DEFAULT_AVAILABLE_KINDS: tuple[str, ...] = ("sync.time", "coordinates.zone_local")


#: 운영자 화면이 객체를 **확정으로 다루기 전에** 요구하는 근거(AI-S-07).
#: 선언이고 분기문이 아니다 — 배치가 `TwinFusionService(promotion_contract=...)` 로
#: 갈아 끼운다. `semantic_class` 의 경계를 `CONFIRMING_GROUPS` 에서 가져오는 이유:
#: "독립 소스 몇 개면 확정인가" 의 주인은 `perception/object_record.py` 하나여야
#: 하고, 여기 2 를 적으면 그 숫자가 두 곳에 생겨 한쪽만 고쳐진다.
TWIN_PROMOTION_CONTRACT = MissionContract(
    mission_id="twin_display",
    required=(
        RequiredEvidence(kind="existence", necessity="required"),
        RequiredEvidence(kind="semantic_class", tolerance=float(CONFIRMING_GROUPS),
                         necessity="required"),
        RequiredEvidence(kind="region_2d", necessity="preferred"),
    ),
    notes="운영자 상황 인식 — 이름을 확정해 보여 주기 전에 독립 소스 합의를 요구한다",
)

#: 근거 종류 → **이 배치의 어휘로** 그것을 만들 수 있는 capability kind.
#: `decision/evidence_gap.DEFAULT_KIND_PROVIDERS` 를 그대로 쓰지 않는 이유는 결함
#: 하나다(2026-11-04 발견): 그 기본표는 `detection` · `open_vocabulary_detection`
#: 처럼 **점 없는** 이름을 쓰는데 이 저장소의 provider manifest 와 노드 선언은
#: `perception.detect` · `perception.detect_ovd` 를 쓴다. 두 어휘가 갈려 있으면
#: 대조 자체가 성립하지 않고(`contracts/evidence_contract.py` 의 docstring 이 그
#: 조건을 적는다), 그 결과 **모든 근거가 '만들 수 없음' 으로 떨어져** 아무것도
#: 승격되지 않고 요청도 나가지 않는다. 바른 해소는 기본표를 배치 어휘로 옮기는
#: 것이지만 그 표를 읽는 소비자가 여럿이라, 여기서는 **이 배치의 표를 선언으로**
#: 넘긴다(그 표가 루프의 생성자 인자인 이유가 바로 이것이다).
TWIN_KIND_PROVIDERS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "existence": ("perception.detect", "perception.detect_ovd"),
    "semantic_class": ("perception.detect", "perception.detect_ovd",
                       "perception.classify"),
    "region_2d": ("perception.detect", "perception.detect_ovd"),
    "mask": ("perception.segment",),
    "geometry_3d": ("perception.depth",),
    "distance": ("perception.depth", "perception.distance"),
    "track_identity": ("perception.track", "perception.associate"),
    "calibration": ("media.video_input",),
    "cause_hypothesis": ("perception.anomaly",),
})

#: 요청할 관측·분석 **수준**, 낮은 것부터. 위험도가 오르거나 근거가 모자라면 높은
#: 쪽부터 고른다 — 그 오르내림의 주인은 `risk/adjustment.py` 이고 여기서는 목록만
#: 선언한다. 선언이므로 새 수준은 한 줄 추가이고 핵심 코드를 고치지 않는다(AI-R-02).
TWIN_OBSERVATION_LEVELS: tuple[str, ...] = (
    "perception.detect", "perception.detect_ovd", "perception.anomaly",
)

#: 물리 행동이 필요한 capability kind. 이 집합의 것은 루프가 **돌리지 않고 요청으로만**
#: 낸다 — 카메라를 돌리거나 로봇을 보내는 일은 제어 경계를 거친다(AI-C-19).
TWIN_PHYSICAL_ACTION_KINDS: frozenset[str] = frozenset({
    "observation.mobile",     # 이동형 관측자를 그 자리로 보내야 한다
    "observation.aerial",     # 띄워야 한다
    "perception.distance",    # 거리계를 대상 쪽으로 돌려야 한다
})

#: 운영자가 고칠 수 있는 단서 이름. 화면에서 사람이 판단할 수 있는 값만 둔다 —
#: 사람이 볼 수 없는 내부 값을 고치게 하면 그 수정은 근거가 아니라 추측이 된다.
CUE_SEMANTIC_CLASS = "semantic_class"
CUE_RANGE_M = "range_m"
CUE_NAMES: tuple[str, ...] = (CUE_SEMANTIC_CLASS, CUE_RANGE_M)

CORRECTION_KIND_POSITION = "position"
CORRECTION_KIND_CUE = "cue"

#: `trace()` 가 답하는 질문. 질문을 받지 않으면 상태를 쏟아낼 수밖에 없다.
TRACE_ABOUT_POSITION = "position"
TRACE_ABOUT_CLASS = "semantic_class"
TRACE_ABOUT: tuple[str, ...] = (TRACE_ABOUT_POSITION, TRACE_ABOUT_CLASS)

#: 순위 규칙을 값으로 내보낸다. 화면이 "무엇으로 줄 세웠는지" 적을 수 있어야 한다.
RANKING_LEAVE_ONE_OUT_POSITION = "leave_one_out_position_displacement"
RANKING_CLASS_FLIP_THEN_WEIGHT = "class_flip_then_vote_weight"

#: 기여자 순위 사유 토큰.
REASON_SOLE_SPATIAL_CONTRIBUTOR = "sole_spatial_contributor"
REASON_MOVED_FUSED_POSITION = "moved_fused_position"
REASON_NO_SPATIAL_EVIDENCE = "no_spatial_evidence"
REASON_FLIPS_CLASS = "flips_resolved_class"
REASON_CLASS_VOTE_ONLY = "class_vote_without_flip"

#: 학습 후보가 생긴 사유(AI-L-01: 후보가 된 이유를 함께 추적한다).
CANDIDATE_REASON_POSITION_CORRECTION = "operator_position_correction"
CANDIDATE_REASON_CUE_CORRECTION = "operator_cue_correction"
CANDIDATE_REASON_UNRESOLVED_CLASS = "multi_device_unresolved_class"

#: 한 장치의 위치 주장을 `Evidence.region` 으로 적을 때 쓰는 변의 길이(m).
#: `RecordResolver` 는 region 의 네 변을 신뢰도 가중 평균하므로 변의 길이가 같으면
#: 그 평균의 중심은 **위치의 신뢰도 가중 평균과 정확히 같다**. 점을 상자로 적는 것은
#: 수식을 바꾸지 않고 기존 해석기를 그대로 쓰기 위한 표현이다.
POSITION_SPREAD_M = 0.25


# ---------------------------------------------------------------------------
# 입력 — 장치가 선언한 것과 장치가 본 것
# ---------------------------------------------------------------------------


def _declared_taxonomy() -> ObstacleTaxonomy | None:
    """선언된 장애물 어휘. **없으면 None 이고 예외가 아니다.**

    어휘 선언은 선택 기능이다(AI-C-05). 없는 배치에서는 그룹 대역만 서지 않고
    정확 클래스 매칭과 나머지 융합은 그대로 돈다. 여기서 예외를 던지면 어휘 파일
    하나가 트윈 전체를 세운다.
    """
    try:
        return ObstacleTaxonomy.from_file()
    except (OSError, ValueError):
        return None


@dataclass(frozen=True)
class DevicePlacement:
    """장치가 **어디에 어떻게 놓였다고 선언됐는지**. 확정값이 아니라 입력이다.

    고정 카메라는 보정 프로파일이, 이동형은 자기 추정이 이 값을 준다. 어느 쪽이든
    이 모듈은 받아 쓰고 재판정하지 않는다 — `pose_source` 를 남기는 이유가 그것이다
    (같은 좌표라도 "고정 카메라가 봤다" 와 "로봇이 스스로 추정했다" 는 신뢰도가 다르다).
    """

    device_id: str
    zone_id: str
    #: (x_m, y_m, heading_deg). 구역 로컬 평면 기준이며 전역이 아니다(AI-C-02).
    pose: tuple[float, float, float]
    #: 영상 가로 화각. 영상 x 좌표를 방위로 바꾸는 데만 쓴다.
    horizontal_fov_deg: float = 60.0
    #: `bbox` 가 적힌 영상 가로 크기. 1.0 이면 정규화 좌표다.
    image_width: float = 1.0
    pose_source: str = "declared"
    camera_id: str | None = None
    resolution: tuple[int, int] | None = None
    accelerator_id: str | None = None
    #: 백엔드가 판정한 가용성을 **받아** 적는 칸(AI-O-04). 여기서 판정하지 않는다.
    available: bool = True

    def __post_init__(self) -> None:
        if not self.device_id:
            raise ValueError("device_id must not be empty")
        if not self.zone_id:
            raise ValueError("zone_id must not be empty")
        if self.horizontal_fov_deg <= 0:
            raise ValueError("horizontal_fov_deg must be positive")
        if self.image_width <= 0:
            raise ValueError("image_width must be positive")

    @property
    def input_conditions(self) -> InputConditions:
        """이 장치에서 나온 학습 후보가 들어갈 조건 묶음(AI-L-09)."""
        return InputConditions(
            device_id=self.device_id,
            camera_id=self.camera_id,
            resolution=self.resolution,
            accelerator_id=self.accelerator_id,
        )


@dataclass(frozen=True)
class DeviceDetection:
    """한 장치가 한 프레임에서 낸 인지 결과 1건. **영상 좌표로** 들어온다.

    `range_m` 이 없으면 방위만 아는 상태다. 그런 결과는 위치를 혼자 정하지 못하므로
    공간 근거가 되지 않고 의미 근거로만 쌓인다 — 없는 거리를 지어내서 확정 판단에
    쓰지 않는다(AI-R-02 와 같은 이유).
    """

    detection_id: str
    device_id: str
    track_local_id: int
    frame_ref: str
    observed_at: float
    #: (x1, y1, x2, y2) 영상 좌표.
    bbox: tuple[float, float, float, float]
    label: str | None = None
    confidence: float = 0.0
    range_m: float | None = None
    #: 이 결과를 만든 제공자. 출처 추적의 네 번째 축이다(장치·원본관측·시각·제공자).
    provider_id: str = ""
    available_at: float | None = None
    #: 모델이 낸 특징 벡터. 없으면 비워 두고 지어내지 않는다.
    feature: tuple[float, ...] = ()
    appearance_embedding: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        if not self.detection_id:
            raise ValueError("detection_id must not be empty")
        if not self.frame_ref:
            raise ValueError("frame_ref must not be empty")

    @property
    def usable_at(self) -> float:
        return self.observed_at if self.available_at is None else self.available_at


@dataclass(frozen=True)
class LocalPlacement:
    """영상 좌표 1건을 구역 로컬 평면으로 옮긴 결과. 추정치이고 확정값이 아니다."""

    bearing_deg: float
    range_m: float | None
    position: tuple[float, float] | None
    frame_id: str = FRAME_ZONE_LOCAL


def bearing_from_image(placement: DevicePlacement,
                       bbox: tuple[float, float, float, float]) -> float:
    """영상 가로 위치를 구역 로컬 방위로 바꾼다.

    화각 안에서 선형이라고 가정한다 — 렌즈 왜곡까지 풀려면 보정 프로파일(AI-E-02)이
    필요하고 그것은 이 모듈의 입력이지 책임이 아니다. 가정이 거칠다는 사실은 숨기지
    않고, 틀린 위치의 범인을 `trace()` 가 장치 단위로 가리키게 해서 드러낸다.
    """
    centre_x = (bbox[0] + bbox[2]) / 2.0
    offset = centre_x / placement.image_width - 0.5
    return placement.pose[2] + offset * placement.horizontal_fov_deg


def place_at(placement: DevicePlacement, bearing_deg: float,
             range_m: float) -> tuple[float, float]:
    """선언된 배치에서 방위·거리만큼 떨어진 구역 로컬 점."""
    x, y, _ = placement.pose
    radians = math.radians(bearing_deg)
    return (x + range_m * math.cos(radians), y + range_m * math.sin(radians))


def project_detection(placement: DevicePlacement,
                      detection: DeviceDetection) -> LocalPlacement:
    """영상 좌표 + 선언된 배치 → 구역 로컬 위치 추정."""
    bearing = bearing_from_image(placement, detection.bbox)
    if detection.range_m is None:
        return LocalPlacement(bearing_deg=bearing, range_m=None, position=None)
    return LocalPlacement(bearing_deg=bearing, range_m=detection.range_m,
                          position=place_at(placement, bearing, detection.range_m))


# ---------------------------------------------------------------------------
# 출력 — 융합 그림, 근거 원장, 추적, 수정
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContributedEvidence:
    """원장 1행. **출처가 하나도 빠지지 않은** 근거 기록이다(AI-S-06).

    `independent` 가 거짓이면 같은 `(장치, 프레임)` 에서 파생된 의존 근거이고
    `depends_on` 이 선행 근거를 가리킨다. 이 두 칸이 "두 번 봤다" 와 "한 번 본 것을
    두 번 읽었다" 를 구분한다.
    """

    evidence_id: str
    object_id: str
    device_id: str
    provider_id: str
    frame_ref: str
    observed_at: float
    available_at: float
    label: str | None
    confidence: float
    bearing_deg: float
    range_m: float | None
    position: tuple[float, float] | None
    frame_id: str
    independent: bool
    depends_on: str | None
    detection_id: str
    #: 운영자가 이 행의 단서를 고쳤다면 그 수정 식별자들.
    corrected_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClassHypothesis:
    """클래스 **가설** 1건. 확정 label 이 아니다(AI-S-04).

    서로 다른 분석 결과를 하나의 label 로 즉시 합치지 않고 지지 장치와 함께 쌓는다.
    """

    label: str
    devices: tuple[str, ...]
    best_confidence: float
    independent_support: int
    operator_confirmed: bool = False


@dataclass(frozen=True)
class CorrectionRecord:
    """사람이 고친 1건. 레코드에는 즉시, 모델에는 영향 없음(AI-L-03)."""

    correction_id: str
    object_id: str
    kind: str
    actor: str
    reason: str
    applied_at: float
    #: 이 수정의 책임을 돌릴 장치. 위치 수정은 `trace()` 1순위 기여자가 기본값이다.
    device_id: str
    cue_name: str | None = None
    reported_value: object | None = None
    corrected_value: object | None = None
    evidence_id: str | None = None
    offset_m: float | None = None
    learning_candidate_id: str | None = None
    learning_lineage_id: str | None = None


@dataclass(frozen=True)
class FusedRecord:
    """한 물리 객체의 현재 구역 그림. 화면이 읽는 유일한 형태다.

    `fused_position` 은 사람 수정까지 반영한 값이고 `sensor_fused_position` 은 장치
    근거만의 값이다. 둘을 한 칸에 합치면 "사람이 고쳤다" 와 "센서가 그렇게 봤다" 가
    구분되지 않고, 그러면 `position_disagreement_m` 이 가리키는 미해결 불일치도 사라진다.
    """

    object_id: str
    zone_id: str
    record_revision: int
    frame_id: str
    coordinate_frame: str
    fused_position: tuple[float, float] | None
    sensor_fused_position: tuple[float, float] | None
    position_disagreement_m: float | None
    semantic_class: str
    sensor_semantic_class: str
    #: 그 클래스가 속한 장애물 그룹. 판정은 `perception/obstacle_taxonomy.py` 가
    #: 소유하고 여기서는 **소비만** 한다 — 같은 객체가 두 화면에서 다른 그룹이 되지
    #: 않으려면 분류가 한 곳에만 있어야 한다. 어휘 선언이 없는 배치에서는 빈
    #: 문자열이고, 그때 에셋은 정확 클래스 단계만 돈다(AI-C-05).
    object_group: str
    #: 트윈에서 **무엇으로 다룰 것인가** — `background`(지도의 몸체) · `object`(따라
    #: 움직일 것) · `agent` · `ground`(바닥의 성질) · `unknown`. 벽과 의자는 같은
    #: 그룹이라 그룹에서 유도할 수 없고 따로 들고 온다.
    object_role: str
    lifecycle: str
    confidence: float
    supporting_device_count: int
    available_device_count: int
    evidence_sufficient: bool
    contributor_device_ids: tuple[str, ...]
    class_hypotheses: tuple[ClassHypothesis, ...]
    observed_at: float
    corrections: tuple[CorrectionRecord, ...]

    @property
    def operator_corrected(self) -> bool:
        return bool(self.corrections)


@dataclass(frozen=True)
class ContributorInfluence:
    """한 장치가 지금 값에 끼친 영향. 지분과 **반사실 변위**를 따로 적는다."""

    device_id: str
    contributor_weight: float
    claimed_position: tuple[float, float] | None
    offset_from_fused_m: float | None
    #: 이 장치의 근거를 빼면 융합 위치가 움직이는 거리. `None` 은 "빼면 공간 근거가
    #: 하나도 남지 않는다" 는 뜻이며 0 과 전혀 다른 상태다 — 0 으로 적으면 유일한
    #: 책임자가 꼴찌가 된다.
    position_influence_m: float | None
    class_vote: str | None
    #: 이 장치를 빼면 해석된 클래스가 무엇으로 바뀌는가. 안 바뀌면 `None`.
    flips_class_to: str | None
    independent_contributions: int
    dependent_rows: int
    evidence_ids: tuple[str, ...]
    frame_refs: tuple[str, ...]
    provider_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class RecordTrace:
    """하나의 질문에 대한 답. 상태 전체를 쏟아내지 않는다."""

    object_id: str
    about: str
    ranking_rule: str
    frame_id: str
    coordinate_frame: str
    fused_position: tuple[float, float] | None
    sensor_fused_position: tuple[float, float] | None
    semantic_class: str
    #: 보유 클래스는 끈적하다(`object_record._resolve_class`). 반사실은 전부 다시 푼
    #: 이 기준과 비교해야 하므로 비교 기준을 숨기지 않고 같이 낸다.
    baseline_semantic_class: str
    contributors: tuple[ContributorInfluence, ...]
    evidence_rows: tuple[ContributedEvidence, ...]
    corrections: tuple[CorrectionRecord, ...]


@dataclass(frozen=True)
class FiledCandidate:
    """제출된 학습 후보 1건과 그 계보 입구."""

    learning_candidate_id: str
    candidate_origin: str
    object_id: str
    device_id: str
    label: str
    reason: str
    learning_lineage_id: str
    learning_state: str
    filed_at: float
    frame_ref: str | None = None
    correction_id: str | None = None
    #: 정답 검수에서 온 후보라면 **어느 상자**였는지. 지속 객체에 묶이지 않는
    #: 후보(저장된 프레임 검수)는 `object_id` 가 비므로 되짚을 자리가 여기뿐이다.
    box_ref: str | None = None

    @property
    def human_confirmed(self) -> bool:
        return self.candidate_origin == CandidateOrigin.HUMAN_CONFIRMED.value


@dataclass(frozen=True)
class CandidateLedger:
    """제출된 후보를 **출처로 갈라서** 낸다(AI-L-02: 자동 추론과 사람 확인을 섞지 않는다)."""

    human_confirmed: tuple[FiledCandidate, ...]
    auto_inference: tuple[FiledCandidate, ...]

    @property
    def total(self) -> int:
        return len(self.human_confirmed) + len(self.auto_inference)


@dataclass(frozen=True)
class CorrectionOutcome:
    """수정 1건의 결과. 고쳐진 레코드와 **만들어진 후보·계보 식별자**를 같이 낸다."""

    record: FusedRecord
    correction: CorrectionRecord
    learning_candidate_id: str
    learning_lineage_id: str
    learning_state: str


@dataclass(frozen=True)
class DeviceStatus:
    """장치 1대가 지금까지 무엇을 기여했는지. 0 기여를 생략하지 않는다."""

    device_id: str
    zone_id: str
    available: bool
    pose: tuple[float, float, float]
    pose_source: str
    observation_count: int
    objects_contributed: tuple[str, ...]


@dataclass(frozen=True)
class ZoneView:
    """한 구역의 현재 그림: 객체 + 구조 + 장치. 전부 구역 로컬 좌표다."""

    zone_id: str
    frame_id: str
    coordinate_frame: str
    records: tuple[FusedRecord, ...]
    map_elements: tuple[MapElement, ...]
    devices: tuple[DeviceStatus, ...]


# ---------------------------------------------------------------------------
# 서비스
# ---------------------------------------------------------------------------


def _centre(region: tuple[float, float, float, float] | None) -> tuple[float, float] | None:
    if region is None:
        return None
    return ((region[0] + region[2]) / 2.0, (region[1] + region[3]) / 2.0)


def _distance(a: tuple[float, float] | None,
              b: tuple[float, float] | None) -> float | None:
    if a is None or b is None:
        return None
    return math.dist(a, b)


@dataclass
class TwinFusionService:
    """장치별 인지 결과를 구역 로컬 객체 레코드로 융합하고, 그 결과를 되짚고 고친다.

    협력자는 전부 주입된다. 전역 상태가 없으므로 한 프로세스에서 여러 인스턴스를
    띄워도 서로를 보지 않는다 — 시험이 실제 수식을 그대로 돌릴 수 있는 조건이다.
    """

    builder: ProgressiveRecordBuilder = field(default_factory=ProgressiveRecordBuilder)
    linker: CrossSourceLinker = field(
        default_factory=lambda: CrossSourceLinker(
            evidence_capabilities=ZONE_EVIDENCE_CAPABILITIES))
    #: 구역마다 독립된 집계를 둔다. 한 집계에 두 구역을 섞으면 서로 다른 구역의 객체가
    #: 좌표가 가깝다는 이유로 한 객체가 된다.
    associator_factory: Callable[[], GlobalTrajectoryAssociator] = GlobalTrajectoryAssociator
    candidate_store: CandidateStore = field(default_factory=CandidateStore)
    map_estimator: EnvironmentMapEstimator = field(default_factory=EnvironmentMapEstimator)
    clock: Callable[[], float] = time.time
    position_spread_m: float = POSITION_SPREAD_M
    #: 클래스→그룹·역할 어휘. **선택 협력자다** — 선언이 없으면 None 이고 그룹
    #: 대역만 서지 않는다(AI-C-05: 선택 결손은 그 기능만 축소한다).
    taxonomy: ObstacleTaxonomy | None = field(default_factory=_declared_taxonomy)
    #: 승격 전에 요구하는 근거. `None` 이면 승격 질문을 하지 않고 레코드 자신의
    #: lifecycle 만 남는다(그 축소 사유가 결과에 적힌다).
    promotion_contract: MissionContract | None = TWIN_PROMOTION_CONTRACT
    #: 관측 장치 id → 그 장치에 **실제로 배치된** provider 레지스트리. `None` 을
    #: 돌려주면 그 장치에 대해서는 부족분을 어디로도 보내지 않고 사유만 남는다.
    #: 배치의 정본은 `tools/status_ui/serve.py::StatusService.fleet()` 이고 여기서
    #: 그 판정을 다시 하지 않는다 — 콘솔이 그 결과로 만든 레지스트리를 받는다.
    registry_for: Callable[[str], CapabilityRegistry | None] | None = None
    #: 물리 행동이 필요한 kind 들. 선언이고 분기문이 아니다.
    physical_action_kinds: frozenset[str] = TWIN_PHYSICAL_ACTION_KINDS
    #: 근거 종류 → 이 배치의 capability kind. 위 TWIN_KIND_PROVIDERS 가 그 이유다.
    kind_providers: Mapping[str, tuple[str, ...]] = TWIN_KIND_PROVIDERS

    # -- 내부 상태 (전부 인스턴스 소유. 모듈 전역은 하나도 없다) -------------
    _placements: dict[str, DevicePlacement] = field(default_factory=dict, init=False)
    _associators: dict[str, GlobalTrajectoryAssociator] = field(default_factory=dict, init=False)
    _available_kinds: set[str] = field(
        default_factory=lambda: set(DEFAULT_AVAILABLE_KINDS), init=False)
    #: object_id -> 근거 원장. 출처를 하나도 버리지 않는 유일한 자리다.
    _ledger: dict[str, list[ContributedEvidence]] = field(default_factory=dict, init=False)
    #: (object_id, device_id, frame_ref) -> 그 묶음의 첫 근거. 중복 판정의 기준이다.
    _frame_rep: dict[tuple[str, str, str], str] = field(default_factory=dict, init=False)
    #: 같은 묶음 -> 공간 근거를 **실제로 들고 있는** 근거 1건. 묶음당 하나뿐이다.
    _frame_spatial: dict[tuple[str, str, str], str] = field(default_factory=dict, init=False)
    _track_objects: dict[tuple[str, str, int], str] = field(default_factory=dict, init=False)
    _trajectory_of: dict[str, str] = field(default_factory=dict, init=False)
    _object_zone: dict[str, str] = field(default_factory=dict, init=False)
    _detections: dict[str, DeviceDetection] = field(default_factory=dict, init=False)
    _detection_objects: dict[str, str] = field(default_factory=dict, init=False)
    _position_corrections: dict[str, CorrectionRecord] = field(default_factory=dict, init=False)
    _class_corrections: dict[str, CorrectionRecord] = field(default_factory=dict, init=False)
    _cue_corrections: dict[tuple[str, str, str], CorrectionRecord] = field(
        default_factory=dict, init=False)
    _corrections: dict[str, list[CorrectionRecord]] = field(default_factory=dict, init=False)
    _candidates: list[FiledCandidate] = field(default_factory=list, init=False)
    _lineages: dict[str, LearningLineage] = field(default_factory=dict, init=False)
    _auto_filed: set[str] = field(default_factory=set, init=False)
    _counter: int = field(default=0, init=False)
    #: 관측 장치 id → 그 장치용 승격 루프. 장치마다 배치된 provider 가 다르므로
    #: 루프도 장치마다 다르다(같은 루프를 공유하면 한 장치가 가진 기능을 다른
    #: 장치가 가진 것처럼 요청하게 된다).
    _loops: dict[str, PerceptionLoop] = field(default_factory=dict, init=False)

    # -- 등록 -------------------------------------------------------------

    def register_device(self, placement: DevicePlacement) -> None:
        """장치의 배치를 등록한다. **등록만으로는 아무 근거도 생기지 않는다** — 그래서
        한 번도 보내지 않은 장치는 기여자에도, 지지 수에도 나타나지 않는다(AI-C-05)."""
        self._placements[placement.device_id] = placement

    def placement_of(self, device_id: str):
        """그 장치가 알린 배치. 한 번도 알리지 않았으면 None 이다.

        지도가 "선언된 자리" 와 "장치가 알린 자리" 를 구분하려면 이 둘을 물어볼
        수 있어야 한다. 내부 사전을 밖에서 들여다보면 그 사전의 모양이 곧 계약이
        되어 버리므로 묻는 길을 하나 둔다.
        """
        return self._placements.get(device_id)

    def set_device_available(self, device_id: str, available: bool) -> None:
        """백엔드가 판정한 가용성을 **받아** 적는다. 여기서 재판정하지 않는다(AI-O-04)."""
        placement = self._placements.get(device_id)
        if placement is None:
            raise ValueError(f"unregistered device: {device_id}")
        self._placements[device_id] = replace(placement, available=available)

    def set_available_capability_kinds(self, kinds: Iterable[str]) -> None:
        """지금 등록돼 있는 capability kind 집합. 연계 근거의 사용 가능 여부가 여기서 갈린다."""
        self._available_kinds = set(kinds)

    def usable_evidence(self) -> tuple[str, ...]:
        """지금 연계에 쓸 수 있는 근거 종류. 비어 있으면 소스별 추적만 남는다(AI-S-02)."""
        return self.linker.usable_evidence(self._available_kinds)

    def declare_anchor(self, anchor: Anchor) -> None:
        self.map_estimator.declare_anchor(anchor)

    def ingest_structure(self, zone_id: str, element_id: str,
                         evidence: StructureEvidence) -> MapElement | None:
        """구역 지도의 구조 계층. 객체와 같은 평면에 그려지지만 다른 자료다."""
        return self.map_estimator.ingest(f"{zone_id}/{element_id}", evidence)

    # -- (A) 융합 ---------------------------------------------------------

    def ingest_detection(self, detection: DeviceDetection) -> FusedRecord:
        """장치 1건의 인지 결과를 융합 레코드에 접는다.

        같은 `detection_id` 재전달은 물리 관측이 한 번 더 일어난 것이 아니므로 아무것도
        더하지 않고 현재 레코드를 돌려준다.
        """
        placement = self._placements.get(detection.device_id)
        if placement is None:
            raise ValueError(f"unregistered device: {detection.device_id}")
        known = self._detection_objects.get(detection.detection_id)
        if known is not None:
            return self.record(known)

        local = project_detection(placement, detection)
        object_id = self._assign_object(placement, detection, local)
        group = (object_id, detection.device_id, detection.frame_ref)
        representative = self._frame_rep.get(group)
        independent = representative is None
        # 공간 근거는 묶음당 하나다. 같은 프레임을 두 번 읽은 것이 두 번의 확인이 되면
        # 중복이 융합 위치를 끌어갈 수 있다(AI-S-06).
        spatial = local.position is not None and group not in self._frame_spatial

        row = ContributedEvidence(
            evidence_id=detection.detection_id, object_id=object_id,
            device_id=detection.device_id, provider_id=detection.provider_id,
            frame_ref=detection.frame_ref, observed_at=detection.observed_at,
            available_at=detection.usable_at, label=detection.label,
            confidence=detection.confidence, bearing_deg=local.bearing_deg,
            range_m=local.range_m, position=local.position, frame_id=FRAME_ZONE_LOCAL,
            independent=independent, depends_on=representative,
            detection_id=detection.detection_id,
        )
        if independent:
            self._frame_rep[group] = detection.detection_id
        if spatial:
            self._frame_spatial[group] = detection.detection_id
        self._ledger.setdefault(object_id, []).append(row)
        self._detections[detection.detection_id] = detection
        self._detection_objects[detection.detection_id] = object_id

        self.builder.ingest(object_id, self._as_evidence(row, spatial),
                            self._available_devices(placement.zone_id))
        record = self._fused(object_id)
        self._maybe_file_auto_candidate(record, detection, placement)
        return record

    def records(self, zone_id: str | None = None) -> tuple[FusedRecord, ...]:
        """구역의 현재 융합 그림. `zone_id` 를 비우면 전부."""
        object_ids = sorted(oid for oid, zid in self._object_zone.items()
                            if zone_id is None or zid == zone_id)
        return tuple(self._fused(oid) for oid in object_ids)

    def record(self, object_id: str) -> FusedRecord:
        return self._fused(object_id)

    def evidence_rows(self, object_id: str) -> tuple[ContributedEvidence, ...]:
        """그 레코드를 만든 근거 전부. 출처가 한 칸도 빠지지 않는다(AI-S-06)."""
        return self._rows(object_id)

    # -- 승격과 부족분 — **판정은 전부 남의 것이다** ------------------------

    def _loop_for(self, device_id: str) -> PerceptionLoop:
        """그 관측 장치용 승격 루프. 장치마다 배치된 provider 가 다르다.

        루프 자신은 아무것도 판정하지 않는다(`runtime/perception_loop.py` 의 표를
        보라) — 여기서 하는 일은 **그 장치의 사실로 협력자를 고르는 것**뿐이다.
        레지스트리가 없는 장치(고정 인프라 등)는 부족분을 보낼 곳이 없고, 그 사실이
        결과의 축소 사유로 남는다(AI-C-05).
        """
        if device_id not in self._loops:
            registry = self.registry_for(device_id) if self.registry_for else None
            self._loops[device_id] = PerceptionLoop(
                # 요구 수의 주인을 하나로 둔다 — `CONFIRMING_GROUPS` 가 그 숫자다.
                evaluator=UncertaintyEvaluator(min_evidence_count=CONFIRMING_GROUPS),
                contract=self.promotion_contract,
                info_selector=(AdditionalInfoSelector(registry)
                               if registry is not None else None),
                request_planner=(DecisionSupportRequester(registry)
                                 if registry is not None else None),
                level_adjuster=(ObservationLevelAdjuster(
                    registry, list(TWIN_OBSERVATION_LEVELS))
                    if registry is not None else None),
                physical_action_kinds=self.physical_action_kinds,
                kind_providers=self.kind_providers,
            )
        return self._loops[device_id]

    def _available_capability_kinds(self, device_id: str) -> frozenset[str] | None:
        """그 장치가 지금 낼 수 있는 capability kind. `None` 은 **모른다**이고
        "없다" 가 아니다 — 모른다는 이유로 미리 포기하지 않는다(AI-S-05)."""
        registry = self.registry_for(device_id) if self.registry_for else None
        return None if registry is None else frozenset(registry.known_capability_kinds())

    def promotion(self, object_id: str) -> RecordOutcome:
        """그 레코드의 승격 판정과 부족분. **조회다** — 아무것도 바꾸지 않는다.

        근거 단위는 원장의 `(device_id, frame_ref)` 쌍을 **접지 않은 채** 넘긴다.
        같은 프레임을 두 번 읽은 것을 하나로 접는 규칙은 `perception/uncertainty.py`
        가 소유하고, 여기서 미리 접으면 접었다는 사실이 사라진다(AI-S-03). 원장의
        `independent`/`depends_on` 은 **어느 줄이 대표인가**를 적는 칸이고 개수를
        세는 칸이 아니다.
        """
        record = self.builder.records.get(object_id)
        if record is None:
            raise KeyError(object_id)
        rows = self._rows(object_id)
        device_id = rows[-1].device_id if rows else ""
        item = RecordInput(
            record=record,
            origins=tuple((row.device_id, row.frame_ref) for row in rows),
            frame_ref=rows[-1].frame_ref if rows else "",
            coordinate_frame=COORDINATE_FRAME_ZONE,
        )
        return self._loop_for(device_id).assess(
            item, available_kinds=self._available_capability_kinds(device_id))

    def promotions(self, zone_id: str) -> LoopResult:
        """그 구역 레코드 전부의 승격 판정. 한 스냅샷으로 낸다(AI-O-06).

        장치마다 협력자가 다르므로 레코드별로 그 장치의 루프에 묻고, 축소 상태는
        **가장 많이 줄어든 쪽**으로 모은다 — 한 장치가 요청을 못 보내는데 전체가
        ACTIVE 로 보이면 화면이 거짓을 말한다.
        """
        outcomes: list[RecordOutcome] = []
        # **볼 것이 없었던 회차를 ACTIVE 로 적지 않는다.** 축소는 레코드의 성질이
        # 아니라 조립의 성질이고, 빈 구역을 ACTIVE 로 내면 없는 단계가 숨는다.
        # 관측 장치를 모르는 상태의 조립(레지스트리 없음)이 그 기준선이다.
        state, reasons = self._loop_for("").degradation()
        frame_ref = ""
        for record in self.records(zone_id):
            outcome = self.promotion(record.object_id)
            outcomes.append(outcome)
            frame_ref = frame_ref or outcome.frame_ref
            rows = self._rows(record.object_id)
            device_id = rows[-1].device_id if rows else ""
            device_state, device_reasons = self._loop_for(device_id).degradation()
            if device_id:
                # 장치를 알게 됐으면 그 장치의 사실로 바꿔 쓴다. 기준선의 "모른다" 를
                # 그대로 남기면 레지스트리가 있는 장치도 없는 것처럼 보인다.
                reasons = dict(device_reasons)
                state = device_state
            if device_state is not CapabilityState.ACTIVE:
                state = device_state
        return LoopResult(frame_ref=frame_ref, capability_state=state,
                          degraded_stage_reasons=reasons,
                          object_records=tuple(outcomes))

    def promotion_work(self, zone_id: str,
                       sink: Callable[[LoopResult], None]) -> Callable[[], tuple[str, ...]]:
        """`RefreshLedger.request(work=...)` 자리에 들어가는 모양.

        억제되면 호출되지 않으므로 **보고 있지 않은 구역의 승격 판정은 돌지 않는다**
        (AI-C-13, AI-O-01). 반환은 이번에 건드린 레코드 식별자들이다.
        """
        def work() -> tuple[str, ...]:
            result = self.promotions(zone_id)
            sink(result)
            return tuple(o.zone_local_track_id for o in result.object_records)

        return work

    def zone_view(self, zone_id: str) -> ZoneView:
        return ZoneView(
            zone_id=zone_id,
            frame_id=FRAME_ZONE_LOCAL,
            coordinate_frame=COORDINATE_FRAME_ZONE,
            records=self.records(zone_id),
            map_elements=tuple(
                element for key, element in sorted(self.map_estimator.elements.items())
                if key.startswith(f"{zone_id}/")),
            devices=tuple(self._device_status(p) for p in sorted(
                (p for p in self._placements.values() if p.zone_id == zone_id),
                key=lambda p: p.device_id)),
        )

    # -- (B) 추적 ---------------------------------------------------------

    def trace(self, object_id: str, *, about: str = TRACE_ABOUT_POSITION) -> RecordTrace:
        """"지금 값이 틀렸다 — 누가 끌고 갔고, 얼마나?" 에 답한다.

        답은 지분이 아니라 **반사실**이다: 그 장치의 근거를 빼고 같은 해석기를 다시
        돌려 값이 어디로 가는지 본다. 질문이 위치인지 클래스인지로 순위가 갈린다 —
        질문이 다르면 범인도 다르기 때문이다.
        """
        if about not in TRACE_ABOUT:
            raise ValueError(f"unknown trace question: {about}")
        record = self._fused(object_id)
        rows = self._rows(object_id)
        available = self._available_devices(record.zone_id)
        evidence = self._corrected_evidence(object_id)
        baseline = self._resolve_subset(object_id, evidence, available)
        baseline_position = _centre(baseline.geometry)
        total_weight = sum(e.confidence for e in evidence if e.kind == "region")

        influences: list[ContributorInfluence] = []
        for device_id in sorted({row.device_id for row in rows}):
            device_rows = [row for row in rows if row.device_id == device_id]
            mine = [e for e in evidence if e.source_group == device_id]
            kept = [e for e in evidence if e.source_group != device_id]
            without = self._resolve_subset(object_id, kept, available - {device_id})
            alone = self._resolve_subset(object_id, mine, {device_id})
            spatial_count = sum(1 for e in mine if e.kind == "region")

            if spatial_count == 0:
                influence: float | None = 0.0
                reason = REASON_NO_SPATIAL_EVIDENCE
            elif _centre(without.geometry) is None:
                # 빼면 공간 근거가 하나도 남지 않는다. 0 이 아니라 "전부 이 장치 탓"이다.
                influence = None
                reason = REASON_SOLE_SPATIAL_CONTRIBUTOR
            else:
                influence = _distance(baseline_position, _centre(without.geometry)) or 0.0
                reason = REASON_MOVED_FUSED_POSITION

            flips = (without.semantic_class
                     if without.semantic_class != baseline.semantic_class else None)
            if about == TRACE_ABOUT_CLASS:
                reason = REASON_FLIPS_CLASS if flips else REASON_CLASS_VOTE_ONLY

            claimed = _centre(alone.geometry)
            influences.append(ContributorInfluence(
                device_id=device_id,
                contributor_weight=(sum(e.confidence for e in mine if e.kind == "region")
                                    / total_weight if total_weight else 0.0),
                claimed_position=claimed,
                offset_from_fused_m=_distance(claimed, record.fused_position),
                position_influence_m=influence,
                class_vote=self._device_vote(device_rows),
                flips_class_to=flips,
                independent_contributions=spatial_count,
                dependent_rows=sum(1 for row in device_rows if not row.independent),
                evidence_ids=tuple(row.evidence_id for row in device_rows),
                frame_refs=tuple(dict.fromkeys(row.frame_ref for row in device_rows)),
                provider_ids=tuple(dict.fromkeys(
                    row.provider_id for row in device_rows if row.provider_id)),
                reason=reason,
            ))

        if about == TRACE_ABOUT_POSITION:
            rule = RANKING_LEAVE_ONE_OUT_POSITION
            # `position_influence_m is None` 이 먼저 온다 — 유일한 공간 기여자는
            # 변위를 계산할 상대가 없을 뿐, 책임이 없는 것이 아니다.
            influences.sort(key=lambda c: (c.position_influence_m is not None,
                                           -(c.position_influence_m or 0.0),
                                           -c.contributor_weight, c.device_id))
        else:
            rule = RANKING_CLASS_FLIP_THEN_WEIGHT
            influences.sort(key=lambda c: (c.flips_class_to is None,
                                           -c.contributor_weight, c.device_id))

        return RecordTrace(
            object_id=object_id, about=about, ranking_rule=rule,
            frame_id=FRAME_ZONE_LOCAL, coordinate_frame=COORDINATE_FRAME_ZONE,
            fused_position=record.fused_position,
            sensor_fused_position=record.sensor_fused_position,
            semantic_class=record.semantic_class,
            baseline_semantic_class=baseline.semantic_class,
            contributors=tuple(influences), evidence_rows=rows,
            corrections=record.corrections,
        )

    # -- (B) 수정 ---------------------------------------------------------

    def apply_position_correction(self, object_id: str, position: Sequence[float], *,
                                  actor: str, reason: str,
                                  device_id: str | None = None) -> CorrectionOutcome:
        """운영자가 객체를 제자리로 옮긴다.

        레코드는 **즉시** 바뀌고 모델은 **전혀** 바뀌지 않는다. 남는 것은
        `HUMAN_CONFIRMED` 후보 1건과 `CANDIDATE` 계보 1건이며, 승격은 AI-L-05 검증과
        AI-L-07 단계적 적용이 한다(AI-L-03).

        책임은 `trace()` 1순위 기여자에게 돌린다 — 조건 없이 후보를 쌓으면 어느
        기기에서 나빠졌는지 되짚을 수 없다(AI-L-09).
        """
        self._require_actor(actor, reason)
        record = self._fused(object_id)
        corrected = (float(position[0]), float(position[1]))
        ranked = self.trace(object_id, about=TRACE_ABOUT_POSITION)
        culprit = device_id or (ranked.contributors[0].device_id
                               if ranked.contributors else None)
        if culprit is None or culprit not in self._placements:
            raise ValueError(
                f"{object_id}: a position correction must name the device whose evidence "
                "it corrects, and no contributor could be attributed")
        placement = self._placements[culprit]
        claimed = next((c.claimed_position for c in ranked.contributors
                        if c.device_id == culprit), None)
        target = self._correction_target(object_id, culprit)

        correction_id = self._next_id("corr")
        filed = self._file_candidate(
            object_id=object_id, placement=placement, label=record.semantic_class,
            feature=_placement_residual(placement, claimed, corrected),
            origin=CandidateOrigin.HUMAN_CONFIRMED,
            candidate_reason=CANDIDATE_REASON_POSITION_CORRECTION,
            actor=actor, lineage_reason=reason, evidence_ref=correction_id,
            frame_ref=target.frame_ref if target else None,
            correction_id=correction_id,
            confidence=target.confidence if target else None, similarity=None)

        correction = CorrectionRecord(
            correction_id=correction_id, object_id=object_id,
            kind=CORRECTION_KIND_POSITION, actor=actor, reason=reason,
            applied_at=self.clock(), device_id=culprit,
            reported_value=claimed, corrected_value=corrected,
            evidence_id=target.evidence_id if target else None,
            offset_m=_distance(record.sensor_fused_position, corrected),
            learning_candidate_id=filed.learning_candidate_id,
            learning_lineage_id=filed.learning_lineage_id,
        )
        self._position_corrections[object_id] = correction
        self._corrections.setdefault(object_id, []).append(correction)
        return CorrectionOutcome(
            record=self._fused(object_id), correction=correction,
            learning_candidate_id=filed.learning_candidate_id,
            learning_lineage_id=filed.learning_lineage_id,
            learning_state=filed.learning_state)

    def apply_cue_correction(self, object_id: str, *, device_id: str, cue_name: str,
                             corrected_value: object, actor: str,
                             reason: str) -> CorrectionOutcome:
        """운영자가 **한 장치가 낸 단서값**을 고친다.

        클래스 수정은 레코드 상태에 바로 반영되고(사람 확인은 센서 표결을 이긴다),
        거리 수정은 그 장치의 공간 주장을 다시 투영해 **같은 해석기로** 다시 융합한다 —
        손으로 평균을 내지 않는 이유는 그 평균이 실제 융합 수식과 어긋나기 시작하면
        추적이 거짓말을 하기 때문이다.

        어느 쪽이든 모델 파라미터는 건드리지 않는다(AI-L-03).
        """
        if cue_name not in CUE_NAMES:
            raise ValueError(f"unknown cue: {cue_name}; known cues are {CUE_NAMES}")
        self._require_actor(actor, reason)
        record = self._fused(object_id)
        placement = self._placements.get(device_id)
        if placement is None:
            raise ValueError(f"unregistered device: {device_id}")
        target = self._correction_target(object_id, device_id)
        if target is None:
            raise ValueError(
                f"{device_id} produced no evidence on {object_id}; there is no cue "
                "value to correct")

        correction_id = self._next_id("corr")
        if cue_name == CUE_SEMANTIC_CLASS:
            corrected: object = str(corrected_value)
            if not corrected:
                raise ValueError("a corrected semantic_class must not be empty")
            reported: object | None = target.label
            label = str(corrected)
            detection = self._detections[target.detection_id]
            # 특징 벡터가 없으면 모델이 그 표본에 대해 실제로 낸 것은 확신값 하나뿐이다.
            # 임계를 조정하는 제공자는 `similarity` 를 읽으므로 그 칸을 비우지 않는다.
            feature = detection.feature or (target.confidence,)
            similarity: float | None = target.confidence
        else:
            corrected = float(corrected_value)
            reported = target.range_m
            label = record.semantic_class
            feature = (float(reported) if reported is not None else 0.0, float(corrected))
            similarity = None

        filed = self._file_candidate(
            object_id=object_id, placement=placement, label=label, feature=feature,
            origin=CandidateOrigin.HUMAN_CONFIRMED,
            candidate_reason=CANDIDATE_REASON_CUE_CORRECTION,
            actor=actor, lineage_reason=reason, evidence_ref=correction_id,
            frame_ref=target.frame_ref, correction_id=correction_id,
            confidence=target.confidence, similarity=similarity)

        correction = CorrectionRecord(
            correction_id=correction_id, object_id=object_id,
            kind=CORRECTION_KIND_CUE, actor=actor, reason=reason,
            applied_at=self.clock(), device_id=device_id, cue_name=cue_name,
            reported_value=reported, corrected_value=corrected,
            evidence_id=target.evidence_id,
            learning_candidate_id=filed.learning_candidate_id,
            learning_lineage_id=filed.learning_lineage_id,
        )
        self._cue_corrections[(object_id, device_id, cue_name)] = correction
        if cue_name == CUE_SEMANTIC_CLASS:
            self._class_corrections[object_id] = correction
        self._corrections.setdefault(object_id, []).append(correction)
        return CorrectionOutcome(
            record=self._fused(object_id), correction=correction,
            learning_candidate_id=filed.learning_candidate_id,
            learning_lineage_id=filed.learning_lineage_id,
            learning_state=filed.learning_state)

    # -- 학습 후보 --------------------------------------------------------

    def learning_candidates(self) -> CandidateLedger:
        """제출된 후보를 출처로 갈라서 낸다. 섞으면 미검증 추론이 정답으로 승격한다."""
        return CandidateLedger(
            human_confirmed=tuple(c for c in self._candidates if c.human_confirmed),
            auto_inference=tuple(c for c in self._candidates if not c.human_confirmed),
        )

    def file_label_candidate(self, *, device_id: str, zone_id: str, box_ref: str,
                             label: str, box: Sequence[float] | None, verdict: str,
                             actor: str, reason: str, frame_ref: str | None,
                             confidence: float | None = None,
                             polarity=None, usage=None) -> FiledCandidate:
        """검수된 정답 상자 1건을 학습 후보로 올리고 계보를 연다(AI-L-01/02/08).

        정답 검수가 이 경로를 거치는 이유: 후보 보관소에 직접 넣으면 표본은 생기지만
        **원장에도 계보에도 나타나지 않는다.** 그러면 운영자가 손으로 고친 정답이
        후보 화면에서 보이지 않고, 나중에 그 가중치가 어느 검수에서 왔는지 되짚을
        입구가 없다. 자동 추론 후보와 같은 문을 쓰되 출처만 다르게 적는다.

        배치가 등록되지 않은 장치의 저장된 프레임도 검수 대상이다. 그때 배치를
        지어내지 않고 **신원만 있는 배치**를 쓴다 — 좌표를 0 으로 적어 넣으면
        그것이 관측된 자세인 것처럼 읽힌다.
        """
        self._require_actor(actor, reason)
        placement = self._placements.get(device_id)
        if placement is None:
            placement = DevicePlacement(device_id=device_id, zone_id=zone_id or "unplaced",
                                        pose=(0.0, 0.0, 0.0), pose_source="not_placed",
                                        camera_id=device_id)
        from mission_runtime.continual.stream_learning import (  # noqa: PLC0415
            SamplePolarity,
        )

        return self._file_candidate(
            # 저장된 프레임의 상자는 지속 객체에 묶이지 않는다. 묶이지 않았다고
            # 적는 편이 없는 object_id 를 지어내는 것보다 낫다(AI-S-06).
            object_id="", placement=placement, label=label,
            feature=tuple(box) if box else (0.0, 0.0, 0.0, 0.0),
            origin=CandidateOrigin.HUMAN_CONFIRMED,
            polarity=polarity or SamplePolarity.POSITIVE,
            usage=usage,
            # 판정별로 묶음이 갈린다 — 상자를 고친 것과 모델이 못 본 것은 서로
            # 다른 것을 가르친다. 상자 id 를 여기 넣으면 묶음이 상자마다 쪼개진다.
            candidate_reason=f"ground_truth:{verdict}",
            actor=actor, lineage_reason=reason or f"ground_truth:{verdict}",
            evidence_ref=frame_ref or box_ref, frame_ref=frame_ref,
            correction_id=None, confidence=confidence, similarity=None,
            box_ref=box_ref,
        )

    def lineage(self, lineage_id: str) -> LearningLineage:
        """계보를 그대로 넘긴다. 승격은 이것을 받은 기존 경로가 한다 — 여기서 밀지 않는다."""
        return self._lineages[lineage_id]

    # -- 내부: 연계 -------------------------------------------------------

    def _assign_object(self, placement: DevicePlacement, detection: DeviceDetection,
                       local: LocalPlacement) -> str:
        """이 track 이 어느 지속 객체에 속하는지. 쌍 비교가 아니라 집계와 비교다.

        `GlobalTrajectoryAssociator` 는 새 관측을 다른 카메라의 생 track 과 짝지어
        비교하지 않고 객체별 집계와 바로 맞춘다(AI-S-02). 집계는 구역마다 따로 둔다.
        """
        associator = self._associators.setdefault(placement.zone_id,
                                                  self.associator_factory())
        track = self._observed_track(detection, local)
        track_key = (placement.zone_id, detection.device_id, detection.track_local_id)
        known = self._track_objects.get(track_key)
        if known is not None:
            associator.update_trajectory(self._trajectory_of[known], track)
            return known

        match = associator.associate(track)
        if match.trajectory_id is None:
            trajectory_id = associator.start_trajectory(track)
        else:
            trajectory_id = match.trajectory_id
            associator.update_trajectory(trajectory_id, track)
        object_id = f"{placement.zone_id}/{trajectory_id}"
        self._trajectory_of[object_id] = trajectory_id
        self._track_objects[track_key] = object_id
        self._object_zone[object_id] = placement.zone_id
        return object_id

    def _observed_track(self, detection: DeviceDetection,
                        local: LocalPlacement) -> ObservedTrack:
        """등록되지 않은 근거는 값이 있어도 쓰지 않는다 — `CrossSourceLinker` 의 규칙."""
        usable = self.usable_evidence()
        return ObservedTrack(
            source_id=detection.device_id,
            track_local_id=detection.track_local_id,
            observed_at=detection.observed_at if "time" in usable else None,
            # `global_position` 은 association.py 가 정한 **칸 이름**이다. 여기 들어가는
            # 값은 구역 로컬 좌표이고 이 모듈은 그것을 전역으로 바꾸지 않는다(AI-C-02).
            global_position=local.position if "space" in usable else None,
            appearance_embedding=(detection.appearance_embedding
                                  if "appearance" in usable else None),
        )

    # -- 내부: 근거와 해석 -------------------------------------------------

    def _region(self, position: tuple[float, float]) -> tuple[float, float, float, float]:
        half = self.position_spread_m / 2.0
        x, y = position
        return (x - half, y - half, x + half, y + half)

    def _as_evidence(self, row: ContributedEvidence, spatial: bool) -> Evidence:
        return Evidence(
            evidence_id=row.evidence_id, frame_ref=row.frame_ref,
            source_group=row.device_id, observed_at=row.observed_at,
            available_at=row.available_at,
            kind="region" if spatial else "semantic",
            confidence=row.confidence,
            region=self._region(row.position) if spatial and row.position else None,
            label=row.label, frame_id=FRAME_ZONE_LOCAL,
        )

    def _corrected_evidence(self, object_id: str) -> list[Evidence]:
        """원장을 해석기 입력으로 되돌린다. 거리 단서 수정이 여기서 반영된다."""
        out: list[Evidence] = []
        for row in self._ledger.get(object_id, ()):
            group = (object_id, row.device_id, row.frame_ref)
            spatial = self._frame_spatial.get(group) == row.evidence_id
            position = row.position
            override = self._cue_corrections.get((object_id, row.device_id, CUE_RANGE_M))
            if spatial and override is not None and override.evidence_id == row.evidence_id:
                position = place_at(self._placements[row.device_id], row.bearing_deg,
                                    float(override.corrected_value))
            out.append(self._as_evidence(replace(row, position=position),
                                         spatial and position is not None))
        return out

    def _resolve_subset(self, object_id: str, evidence: Sequence[Evidence],
                        available: set[str]) -> ObjectRecord:
        """부분집합을 **같은 해석기로** 다시 푼다.

        기준 레코드를 비워서 호출한다 — 보유 클래스의 끈적함(`_resolve_class`)이 끼면
        "그 장치가 애초에 없었다면" 이 아니라 "그 장치가 방금 사라졌다면" 을 재는 셈이
        되고, 두 질문의 답은 다르다.
        """
        return self.builder.resolver.resolve(
            ObjectRecord(object_id=object_id), list(evidence), available, None)

    def _rows(self, object_id: str) -> tuple[ContributedEvidence, ...]:
        if object_id not in self._ledger:
            raise KeyError(object_id)
        marks: dict[str, list[str]] = {}
        for correction in self._corrections.get(object_id, ()):
            if correction.evidence_id:
                marks.setdefault(correction.evidence_id, []).append(correction.correction_id)
        return tuple(
            replace(row, corrected_by=tuple(marks[row.evidence_id]))
            if row.evidence_id in marks else row
            for row in self._ledger[object_id]
        )

    def _device_vote(self, device_rows: Sequence[ContributedEvidence]) -> str | None:
        """그 장치가 이 객체에 대해 들고 있는 입장: 가장 확신했던 label."""
        labelled = [row for row in device_rows if row.label]
        if not labelled:
            return None
        return max(labelled, key=lambda row: row.confidence).label

    def _correction_target(self, object_id: str,
                           device_id: str) -> ContributedEvidence | None:
        """고칠 대상 근거. 공간 근거를 들고 있는 행을 먼저 고른다 — 거리 수정이
        의존 근거에 붙으면 융합에 반영되지 않는다."""
        rows = [row for row in self._ledger.get(object_id, ())
                if row.device_id == device_id]
        spatial = [row for row in rows
                   if self._frame_spatial.get((object_id, device_id, row.frame_ref))
                   == row.evidence_id]
        if spatial:
            return spatial[-1]
        return rows[-1] if rows else None

    # -- 내부: 읽기 모델 ---------------------------------------------------

    def _available_devices(self, zone_id: str) -> set[str]:
        return {p.device_id for p in self._placements.values()
                if p.zone_id == zone_id and p.available}

    def _fused(self, object_id: str) -> FusedRecord:
        base = self.builder.records.get(object_id)
        if base is None:
            raise KeyError(object_id)
        zone_id = self._object_zone[object_id]
        rows = self._rows(object_id)
        sensor_position = _centre(base.geometry)

        position = sensor_position
        cue_position = self._cue_corrected_position(object_id, zone_id)
        if cue_position is not None:
            position = cue_position
        position_correction = self._position_corrections.get(object_id)
        if position_correction is not None:
            value = position_correction.corrected_value
            position = (float(value[0]), float(value[1]))   # type: ignore[index]

        class_correction = self._class_corrections.get(object_id)
        semantic = (str(class_correction.corrected_value) if class_correction is not None
                    else base.semantic_class)
        # 그룹·역할은 **확정된 클래스**에서 나온다. 사람이 클래스를 고쳤으면 고친
        # 쪽을 따른다 — 그래야 사람이 "저건 벽이다" 라고 고친 순간 트윈이 그것을
        # 지도의 몸체로 다루기 시작한다.
        group, role = self._grouping(semantic)

        return FusedRecord(
            object_id=object_id, zone_id=zone_id, record_revision=base.revision,
            frame_id=FRAME_ZONE_LOCAL, coordinate_frame=COORDINATE_FRAME_ZONE,
            fused_position=position, sensor_fused_position=sensor_position,
            position_disagreement_m=_distance(position, sensor_position),
            semantic_class=semantic, sensor_semantic_class=base.semantic_class,
            object_group=group, object_role=role,
            lifecycle=base.lifecycle.value, confidence=base.confidence,
            supporting_device_count=base.supporting_groups,
            available_device_count=base.available_groups,
            evidence_sufficient=base.evidence_sufficient,
            contributor_device_ids=tuple(sorted({row.device_id for row in rows})),
            class_hypotheses=self._hypotheses(rows, class_correction),
            observed_at=base.observed_at,
            corrections=tuple(self._corrections.get(object_id, ())),
        )

    def _grouping(self, semantic_class: str) -> tuple[str, str]:
        """(그룹, 역할). 어휘가 없거나 미등록 이름이면 빈 문자열이다.

        **미등록 이름을 비슷한 그룹으로 끌어오지 않는다** — taxonomy 가 그것을
        `UNKNOWN_OBSTACLE` 로 남기고, 여기서는 그 사실을 그대로 옮긴다.
        """
        if self.taxonomy is None or not semantic_class:
            return "", ""
        if semantic_class == UNKNOWN_CLASS:
            # 클래스가 아직 안 섰다. 그룹을 말할 근거가 없다.
            return "", ""
        verdict = self.taxonomy.classify(semantic_class)
        return verdict.group, verdict.role

    def _cue_corrected_position(self, object_id: str,
                                zone_id: str) -> tuple[float, float] | None:
        """거리 단서가 고쳐졌을 때의 융합 위치. 고친 것이 없으면 계산하지 않는다."""
        if not any(key[0] == object_id and key[2] == CUE_RANGE_M
                   for key in self._cue_corrections):
            return None
        resolved = self._resolve_subset(object_id, self._corrected_evidence(object_id),
                                        self._available_devices(zone_id))
        return _centre(resolved.geometry)

    def _hypotheses(self, rows: Sequence[ContributedEvidence],
                    class_correction: CorrectionRecord | None
                    ) -> tuple[ClassHypothesis, ...]:
        """서로 다른 분석 결과를 하나의 확정 label 로 즉시 합치지 않는다(AI-S-04)."""
        per_label: dict[str, list[ContributedEvidence]] = {}
        for row in rows:
            if row.label:
                per_label.setdefault(row.label, []).append(row)
        confirmed = (str(class_correction.corrected_value)
                     if class_correction is not None else None)
        hypotheses = [
            ClassHypothesis(
                label=label,
                devices=tuple(sorted({item.device_id for item in items})),
                best_confidence=max(item.confidence for item in items),
                independent_support=len({item.device_id for item in items}),
                operator_confirmed=(label == confirmed),
            )
            for label, items in per_label.items()
        ]
        # 사람이 확정한 이름이 센서 근거에 아예 없을 수 있다. 그래도 가설로 남긴다 —
        # 근거 없는 확정이라는 사실이 숨겨지면 다음에 무엇을 더 봐야 하는지가 사라진다.
        if confirmed is not None and confirmed not in per_label:
            hypotheses.append(ClassHypothesis(confirmed, (), 0.0, 0, True))
        return tuple(sorted(hypotheses, key=lambda h: (-h.independent_support,
                                                       -h.best_confidence, h.label)))

    def _device_status(self, placement: DevicePlacement) -> DeviceStatus:
        rows = [row for ledger in self._ledger.values() for row in ledger
                if row.device_id == placement.device_id]
        return DeviceStatus(
            device_id=placement.device_id, zone_id=placement.zone_id,
            available=placement.available, pose=placement.pose,
            pose_source=placement.pose_source, observation_count=len(rows),
            objects_contributed=tuple(sorted({row.object_id for row in rows})),
        )

    # -- 내부: 학습 후보 ---------------------------------------------------

    def _maybe_file_auto_candidate(self, record: FusedRecord, detection: DeviceDetection,
                                   placement: DevicePlacement) -> None:
        """여러 장치가 같은 것을 보고도 이름이 안 붙으면 그것은 모델이 모르는 것이다.

        그 사실 자체가 학습 후보의 사유이고(AI-L-01), 출처는 `AUTO_INFERENCE` 다 —
        검증되지 않은 추론이므로 `StreamSample.confirmed` 가 거짓이고 학습에 들어가지
        않는다(AI-L-02).
        """
        if record.object_id in self._auto_filed:
            return
        if record.sensor_semantic_class != UNKNOWN_CLASS:
            return
        if record.lifecycle != Lifecycle.CONFIRMED.value:
            return
        self._auto_filed.add(record.object_id)
        self._file_candidate(
            object_id=record.object_id, placement=placement, label=UNKNOWN_CLASS,
            feature=detection.feature or (detection.confidence,),
            origin=CandidateOrigin.AUTO_INFERENCE,
            candidate_reason=CANDIDATE_REASON_UNRESOLVED_CLASS,
            actor="ai.fusion", lineage_reason=CANDIDATE_REASON_UNRESOLVED_CLASS,
            evidence_ref=f"{record.object_id}@{detection.frame_ref}",
            frame_ref=detection.frame_ref, correction_id=None,
            confidence=detection.confidence, similarity=None)

    def _file_candidate(self, *, object_id: str, placement: DevicePlacement, label: str,
                        feature: Sequence[float], origin: CandidateOrigin,
                        candidate_reason: str, actor: str, lineage_reason: str,
                        evidence_ref: str, frame_ref: str | None,
                        correction_id: str | None, confidence: float | None,
                        similarity: float | None,
                        box_ref: str | None = None,
                        polarity=None, usage=None) -> FiledCandidate:
        """후보 1건을 보관소에 넣고 계보를 `CANDIDATE` 로 연다. **그 이상 밀지 않는다.**

        조건에 `candidate_reason` 을 넣는 이유: `InputConditions.group_key` 가 그것을
        포함하므로 위치 수정 후보와 단서 수정 후보가 다른 묶음이 된다. 배치 보정을
        배우는 제공자와 임계를 배우는 제공자는 서로 다른 것을 읽어야 한다(AI-L-09).
        """
        candidate_id = self._next_id("cand")
        lineage_id = self._next_id("lin")
        values = tuple(float(v) for v in feature) or (0.0,)
        from mission_runtime.continual.stream_learning import (  # noqa: PLC0415
            SamplePolarity,
            SampleUsage,
        )

        self.candidate_store.add(StreamSample(
            sample_id=candidate_id,
            conditions=InputConditions(
                device_id=placement.device_id, camera_id=placement.camera_id,
                resolution=placement.resolution,
                accelerator_id=placement.accelerator_id,
                extra=(("candidate_reason", candidate_reason),)),
            label=label or UNKNOWN_CLASS, feature=values, origin=origin,
            polarity=polarity or SamplePolarity.POSITIVE,
            usage=usage or SampleUsage.TRAINING,
            frame_ref=frame_ref, confidence=confidence, similarity=similarity,
            observed_at=self.clock(),
        ))
        lineage = LearningLineage(lineage_id, actor=actor, evidence_ref=evidence_ref,
                                  reason=lineage_reason)
        self._lineages[lineage_id] = lineage
        filed = FiledCandidate(
            learning_candidate_id=candidate_id, candidate_origin=origin.value,
            object_id=object_id, device_id=placement.device_id,
            label=label or UNKNOWN_CLASS, reason=candidate_reason,
            learning_lineage_id=lineage_id, learning_state=lineage.state.value,
            filed_at=self.clock(), frame_ref=frame_ref, correction_id=correction_id,
            box_ref=box_ref,
        )
        self._candidates.append(filed)
        return filed

    # -- 내부: 잡다 -------------------------------------------------------

    @staticmethod
    def _require_actor(actor: str, reason: str) -> None:
        """사람이 고쳤다면 **누가 왜** 고쳤는지가 있어야 한다 — 계보가 그것을 요구한다."""
        if not actor or not reason:
            raise ValueError("a correction needs both an actor and a reason")

    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}-{self._counter}"


def _wrap_deg(value: float) -> float:
    return ((value + 180.0) % 360.0) - 180.0


def _placement_residual(placement: DevicePlacement,
                        claimed: tuple[float, float] | None,
                        corrected: tuple[float, float]) -> tuple[float, float]:
    """그 장치의 주장이 **얼마나 어떻게** 틀렸는가: (방위 오차 deg, 거리 오차 m).

    위치 수정에서 이것을 특징으로 남기는 이유: 배치·보정을 배우는 제공자가 실제로
    읽을 수 있는 양이 이 둘이다. 고친 좌표만 남기면 "저기가 맞다"는 말은 되지만
    "이 카메라가 어느 쪽으로 얼마나 틀어졌다"는 되짚을 수 없다.
    """
    x, y, _ = placement.pose
    if claimed is None:
        return (corrected[0] - x, corrected[1] - y)
    claimed_bearing = math.degrees(math.atan2(claimed[1] - y, claimed[0] - x))
    corrected_bearing = math.degrees(math.atan2(corrected[1] - y, corrected[0] - x))
    return (_wrap_deg(corrected_bearing - claimed_bearing),
            math.dist((x, y), corrected) - math.dist((x, y), claimed))
