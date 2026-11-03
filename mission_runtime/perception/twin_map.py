"""탐지로 지은 지도. **아무도 보지 않은 자리를 비었다고 말하지 않는다.**

implements: AI-S-06, AI-S-08
관련: AI-C-02 (좌표계와 접지), AI-S-03 (신뢰도와 근거 충분도는 다른 축),
      AI-C-05 (선택 결손은 축소), AI-C-19 (판단·권한 경계)
tests: tests/test_twin_map.py

## 문제

우리가 가진 입력은 **희소한 탐지**다. 이종 장치 몇 대가 비동기로 보내는 박스와,
그중 일부에만 붙은 거리값. 촘촘한 깊이 스트림도, 연속 odometry 도, LiDAR 광선도 없다.

이 입력으로 지도를 지으면 **거짓말하는 방식이 하나 정해져 있다**: 점유 격자(occupancy
grid)의 고전적 갱신은 광선을 전제한다 — 거리값이 맞은 자리는 점유, 그 **앞쪽 전체는
자유**. 자유 공간은 추론이 아니라 측정이다(Moravec & Elfes 1985; Thrun et al.,
*Probabilistic Robotics* §9.2). 박스 하나는 광선을 주지 않는다. "카메라가 이 구역을
보는데 탐지가 없었다" 를 광선처럼 쓰는 순간 **제공자의 침묵이 비었다는 근거로
환산**되고, 그것이 이 프레임워크가 금지한 바로 그 환산이다(AI-C-05, 원칙 #4).

그래서 이 모듈은 누산기만 가져오고 광선을 버린다. 모든 탐지는 **양의 방향으로만**
갱신하고, 아무도 보지 않은 칸은 손대지 않은 기본값 — 모름 — 으로 남는다.

## 칸 하나가 숫자 하나면 모자란다

log-odds 는 칸마다 숫자 하나다. 그 하나로는 세 가지를 구분할 수 없다.

1. 아무도 안 봤다
2. 두 대가 "반쯤 점유" 로 합의했다
3. 한 대는 점유, 다른 한 대는 자유라고 했다

셋 다 log-odds ≈ 0 으로 떨어진다. Dempster-Shafer 증거 격자(Pagac et al. 1996;
Moras, Cherfaoui & Bonnifait, credibilist occupancy grids)는 이 셋을 나눈다 —
Ω={자유, 점유} 위에서 칸은 질량 네 개를 든다: `m(O)` · `m(F)` · `m(Ω)` ·
그리고 Dempster 결합이 버려야 했던 **충돌** `m(∅)`.

`m(Ω)` 가 1번(무지)이고 `m(∅)` 가 3번(불일치)이다. 우리의 절대 규칙 — 없음은 반대
근거가 아니다 — 는 이 표현에서 비로소 **말할 수 있는 성질**이 되고, 주석에만 적힌
약속에서 벗어난다. 그래서 두 숫자를 나누는 비용을 치른다.

## 지키는 규칙 (전부 시험으로 고정돼 있다)

1. **모름·비었음·점유는 세 상태다.** 아무도 보지 않은 칸은 자유가 아니다. 탐지로 지은
   지도가 거짓말하는 가장 흔한 길이 이 둘을 합치는 것이다. 여기에 넷째 읽기값
   `DISPUTED` 를 더 둔다 — 주장은 세 개이고, 충돌로 **아무 주장도 서지 않는 상태**를
   모름과 섞으면 "안 봤다" 와 "봐 놓고 싸운다" 가 한 칸이 된다.
2. **최신성이 값의 일부다.** 칸은 언제·누가 마지막으로 봤는지 말할 수 있고, 시간이
   가면 확신을 **모름 쪽으로** 놓는다(Dempster 할인; Kurdej et al. 의 노후화율).
   log-odds 를 0 으로 끌어내리는 감쇠와 다른 이유는 1번과 같다 — 0 은 충돌이 내는
   값이기도 하다. 그리고 감쇠는 **절대로 부재의 주장이 되지 않는다**: 질량은 `m(Ω)`
   로만 흐르고 `m(F)` 는 한 톨도 늘지 않는다.
3. **융합 뒤에도 출처가 남는다.** 칸은 받아들인 관측을 그대로 들고 있고, 읽을 때마다
   다시 융합한다. `leave_one_out()` 이 "그 장치를 빼면 이 칸이 무엇이 되는가" 에
   답한다 — 저장소에 융합 결과만 남기면 틀린 지도를 디버깅할 방법이 없다
   (Hydra 가 잘못된 loop closure 를 되돌리려고 병합 전 사본을 남기는 것과 같은 축).
4. **좌표계는 값에서 사라지지 않는다.** 칸과 융합은 전부 현장 로컬 미터다. 전역
   표현은 **선언된 datum 을 통과해서만** 나오고(`position_in`), datum 이 없거나
   정확도를 모르면 **지어내지 않고 사유와 함께 거절한다**. 로컬 값과 전역 값은
   서로 바꿔 쓸 수 있는 값이 아니다 — 한 칸에 합치면 전역 추정이 어느 측정에서
   나왔는지 되짚을 수 없다.
5. **사전정보는 관측이 아니다.** 도면·선언 설치물·과거 관측은 `declared` 격으로
   들어오고, 그것만으로는 어떤 칸도 주장하지 못한다(AI-S-08). 관측 격 지지가 0 인
   칸은 사전정보가 무엇을 말하든 `UNKNOWN` 으로 읽히고, 사전정보의 말은
   `prior_claim` 에 따로 적힌다. 도면을 정답으로 쓰는 것은 문헌에서도 알려진 결함이고
   (Scan-vs-BIM 은 "as-planned 자리 근처에 지어진" 부재만 인식한다; Bosché et al. 2015)
   그 결함의 증상은 조용한 계통 편향 — 실측이 어긋나면 "모델이 낡았다" 가 아니라
   "탐지가 틀렸다" 로 보고된다.
6. **자세 품질이 전파된다.** 검증되지 않은 선언 배치를 통과한 탐지는 검증된 보정을
   통과한 탐지와 같은 확신을 낼 수 없다. 할인은 Dempster 할인 그대로이고, 깎인 만큼은
   `m(Ω)` 로 간다 — 자유 질량으로 가지 않는다. 전역 표현을 물으면 datum 품질까지
   같은 축으로 더해진다(규칙 4).
7. **종류가 늘어도 `if` 가 늘지 않는다.** 관측 종류·자세 품질은 레지스트리에 등록되는
   **데이터**이고(AI-C-18 과 같은 축), 도메인 이름·제품 이름으로 갈라지는 분기가 이
   모듈에 없다(원칙 #1, #3).
8. **없는 제공자는 지도를 축소시키되 비우지 않는다.** 쓸 수 없는 출처의 관측은 반대
   근거가 아니라 무기여이고, 그 출처가 혼자 받치던 칸은 지워지지 않고 **모름으로
   돌아간다** — 출처가 돌아오면 칸도 돌아온다(AI-C-05).

## 조립한 것 — 어려운 부분은 이미 저장소에 있다

* 격(`measured`/`declared`/`estimated`)·독립성 단위(`frame_ref`)·leave-one-out 관용구는
  `perception/spatial_evidence.py` 의 것을 **그대로 수입해 쓴다**. 같은 뜻을 두 어휘로
  들고 다니면 근거를 서로 되짚을 수 없다.
* 앵커는 `perception/environment_map.py` 의 `Anchor`.
* 사전정보 레코드는 `perception/environment_prior.py` 의 `PriorInfoRecord` — 유효기간·
  충돌 누적·재평가 후보 판정은 거기 있고 여기서 다시 만들지 않는다.
* 객체 생존 추정은 Rosen, Mason & Leonard, "Towards Lifelong Feature-Based Mapping in
  Semi-Static Environments" (ICRA 2016) 의 persistence filter 를 그대로 쓴다. 이 필터가
  우리에게 맞는 이유는 성능이 아니라 **구조**다: "봤는데 없었다"(`y=0`) 는 검출기
  오검출률로 한계가 정해진 우도 인자로 들어가고, **보지 않았음**은 인자를 아예 넣지
  않는다. 믿음은 그 사이에도 내려가지만 생존 사전확률을 통해서만 내려간다. 규칙 8 이
  주석이 아니라 **수식의 성질**이 되는 자리다.

## 이 모듈이 소유하지 않는 것

* 영상 좌표를 미터 평면으로 옮기는 일(보정)은 AI-E-02 의 몫이고 여기서는 입력이다.
* 구역 커버리지·blind spot 의 **사유 분류**는 `perception/coverage.py` 가 소유한다.
  여기서 내는 `never_observed` 는 칸 단위 사실이고 그 사유가 아니다.
* 객체 식별·클래스 해석은 `perception/object_record.py`. 이 모듈은 **자리**에 대해서만
  말하고 그 자리에 무엇이 있는지는 레코드가 정한다.
* 사전정보의 노후·재평가 판정은 `environment_prior.PriorInfoStore`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Iterable, Mapping, Sequence

from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.contracts.capability import CapabilityRequirement, CapabilityState
from mission_runtime.perception.environment_map import Anchor
from mission_runtime.perception.environment_prior import PriorInfoRecord
from mission_runtime.perception.spatial_evidence import (
    ROLE_DEPENDENT,
    ROLE_INDEPENDENT,
    TIER_DECLARED,
    TIER_ESTIMATED,
    TIER_MEASURED,
)

#: 탐지 하나만 있으면 지도는 성립한다. 깊이·점군·사전정보·사람 실측·datum 은 전부
#: 선택이고 결손은 DEGRADED 까지만 내려간다(AI-C-05).
REQUIREMENT = CapabilityRequirement(
    required=("perception.detect",),
    optional=("perception.depth", "perception.point_cloud", "reference.zone_profile",
              "reference.human_survey", "reference.site_datum"),
)

#: 격의 서열. `spatial_evidence` 와 **같은 값**을 쓴다(수입한 상수).
_TIER_RANK = {TIER_MEASURED: 0, TIER_DECLARED: 1, TIER_ESTIMATED: 2}

#: `declared` 격은 사전정보 격이다 — 그것만으로는 어떤 칸도 주장하지 못한다(규칙 5).
PRIOR_TIERS: frozenset[str] = frozenset({TIER_DECLARED})

# --- 주장 어휘 (dd.TWIN_MAP_CLAIMS) ------------------------------------------
#: 관측이 칸에 대해 할 수 있는 말은 둘뿐이다. "모름" 은 주장이 아니라 **주장의 부재**
#: 이므로 여기에 들어가지 않는다 — 어휘에 넣으면 아무도 보지 않은 칸과 누군가
#: "모르겠다" 고 보낸 칸이 같은 자리에 적힌다.
CLAIM_OCCUPIED = "occupied"
CLAIM_FREE = "free"
MAP_CLAIMS: tuple[str, ...] = (CLAIM_OCCUPIED, CLAIM_FREE)

#: `as_dict()` 가 밝히는 이 층의 격(dd.MAP_AUTHORITIES). 전역 승격은 선언된 datum 을
#: 통과해야 하고 그 사실을 payload 에 적어 둔다 — 받는 쪽이 로컬 값을 전역으로
#: 오인하지 않게.
MAP_AUTHORITY_SITE_LOCAL = "site_local"


class CellState(str, Enum):
    """칸 하나를 읽은 결과.

    UNKNOWN  - 아무도 보지 않았거나, 선 주장이 없거나, 사전정보만 있다.
    FREE     - 비었다는 주장이 섰다. **광선을 가진 출처나 선언만** 낼 수 있다.
    OCCUPIED - 점유 주장이 섰다.
    DISPUTED - 봤고, 서로 다르게 봤다. 모름과 섞지 않는 이유는 대응이 다르기 때문이다 —
               모름은 가서 봐야 하고, 불일치는 어느 출처가 틀렸는지 찾아야 한다.
    """

    UNKNOWN = "UNKNOWN"
    FREE = "FREE"
    OCCUPIED = "OCCUPIED"
    DISPUTED = "DISPUTED"


#: 주장이 서기 위한 질량 경계. 0.5 를 넘겨야 하므로 질량이 반반인 칸은 주장하지 않는다.
CLAIM_THRESHOLD = 0.5
#: 이만큼 충돌이 쌓이면 어떤 주장도 세우지 않는다. 임계를 두는 이유는 한 번의 작은
#: 불일치로 칸 전체를 포기하지 않기 위해서다.
CONFLICT_THRESHOLD = 0.35
#: 마지막 관측이 이보다 오래되면 `stale` 이다. 호출자의 시계 단위.
DEFAULT_STALE_AFTER = 60.0

# --- 자세 품질 (등록 데이터, dd.POSE_QUALITIES) -------------------------------
#: 검증된 보정 프로파일을 통과했다.
POSE_VALIDATED = "validated"
#: 자기 추정 — 이동형이 스스로 낸 값. 검증은 없지만 측정에서 나왔다.
POSE_ESTIMATED = "estimated"
#: 설치자가 적었고 아무도 확인하지 않았다.
POSE_DECLARED = "declared"
#: 자세를 모른다.
POSE_UNKNOWN = "unknown"

POSE_QUALITIES: tuple[str, ...] = (POSE_VALIDATED, POSE_ESTIMATED, POSE_DECLARED,
                                   POSE_UNKNOWN)

#: 자세 품질 → Dempster 할인 계수. **데이터이고 분기가 아니다**: 새 품질 등급은
#: `TwinMapLayer.set_pose_discount()` 로 등록하고 이 모듈은 고치지 않는다.
#: 깎인 질량은 전부 `m(Ω)` 로 간다 — 나쁜 자세는 "비었다" 의 근거가 아니라 **모름**이다.
DEFAULT_POSE_DISCOUNT: Mapping[str, float] = {
    POSE_VALIDATED: 1.0,
    POSE_ESTIMATED: 0.6,
    POSE_DECLARED: 0.45,
    POSE_UNKNOWN: 0.2,
}

# --- 거절 사유 (dd.TWIN_MAP_REJECTION_REASONS) -------------------------------
REJECT_UNREGISTERED_KIND = "unregistered_kind"
REJECT_SOURCE_UNAVAILABLE = "source_unavailable"
REJECT_DUPLICATE = "duplicate_observation_id"
REJECT_FRAME_MISMATCH = "frame_mismatch"
REJECT_FREE_CLAIM_NOT_PERMITTED = "free_claim_not_permitted"
REJECT_UNKNOWN_CLAIM = "unregistered_claim"
REJECT_EMPTY_FOOTPRINT = "empty_footprint"

# --- 전역 표현 거절 사유 (dd.FRAME_REFUSAL_REASONS) --------------------------
REFUSE_NO_DATUM = "no_site_datum"
REFUSE_DATUM_ACCURACY_UNKNOWN = "datum_accuracy_unknown"
REFUSE_NO_LOCAL_VALUE = "no_local_value"
REFUSE_UNKNOWN_FRAME = "unregistered_frame"

# --- 정확도를 지배한 축 (dd.ACCURACY_LIMITS) ---------------------------------
#: 로컬 측정이 더 나쁘다 — 전역 값의 오차를 로컬 쪽이 지배한다.
LIMITED_BY_LOCAL = "local"
#: datum 이 더 나쁘다. 전역 값은 **datum 보다 좋을 수 없다**(규칙 4).
LIMITED_BY_DATUM = "datum"
#: 재료 중 하나가 미측정이다. **0 도 아니고 "제한 없음" 도 아니다** — 모르는 값을
#: 아는 값처럼 합성하면 그 추측이 측량값과 같은 칸에 앉는다.
LIMITED_BY_UNKNOWN = "accuracy_unknown"

#: 이 모듈이 다루는 좌표계 이름. 사전의 `coordinate_frame` 어휘 중 둘이다.
FRAME_ZONE = "ZONE"
FRAME_GLOBAL = "GLOBAL"


# ---------------------------------------------------------------------------
# 믿음 — 질량 넷
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BeliefMass:
    """Ω={자유, 점유} 위의 믿음. **무지와 불일치를 서로 다른 칸에 적는다.**

    `occupied` + `free` + `unknown` == 1 로 유지하고, `conflict` 는 질량이 아니라
    **감사 기록**이다 — Dempster 결합이 정규화로 버린 몫을 누적한 스칼라다. 이것을
    질량으로 되먹이면 대수가 깨진다(∅ ⊗ 무엇 = ∅)이고, 버리면 "두 대가 싸운다" 를
    말할 방법이 사라진다. 그래서 들고 있되 다음 결합에 넣지 않는다.
    """

    occupied: float = 0.0
    free: float = 0.0
    unknown: float = 1.0
    conflict: float = 0.0

    @classmethod
    def ignorant(cls) -> "BeliefMass":
        """아무도 보지 않은 칸. 전부 `m(Ω)` 이고 자유가 아니다."""
        return cls(0.0, 0.0, 1.0, 0.0)

    @classmethod
    def from_claim(cls, claim: str, strength: float) -> "BeliefMass":
        """관측 1건을 믿음으로. 남은 몫은 전부 모름이다.

        `strength` 를 1.0 으로 받지 않는 이유: 질량 1 은 어떤 반대 근거로도 움직이지
        않는 칸을 만든다(Dempster 결합에서 영원히 고정된다). 관측은 확정이 아니다.
        """
        s = max(0.0, min(_MAX_CLAIM_STRENGTH, strength))
        if claim == CLAIM_OCCUPIED:
            return cls(s, 0.0, 1.0 - s, 0.0)
        if claim == CLAIM_FREE:
            return cls(0.0, s, 1.0 - s, 0.0)
        raise ValueError(f"unknown claim {claim!r}; expected one of {MAP_CLAIMS}")

    def fuse(self, other: "BeliefMass") -> "BeliefMass":
        """Dempster 결합. 버린 몫은 `conflict` 로 **누적**한다."""
        k = self.occupied * other.free + self.free * other.occupied
        if k >= 1.0:
            # 완전 충돌 — 정규화할 것이 없다. 주장을 전부 내려놓고 불일치만 남긴다.
            # 0 으로 적으면 "안 봤다" 와 구분되지 않는다.
            return BeliefMass(0.0, 0.0, 1.0, 1.0)
        scale = 1.0 - k
        occupied = (self.occupied * other.occupied + self.occupied * other.unknown
                    + self.unknown * other.occupied) / scale
        free = (self.free * other.free + self.free * other.unknown
                + self.unknown * other.free) / scale
        unknown = (self.unknown * other.unknown) / scale
        # "한 단계에서라도 어긋났는가" 로 누적한다 — 단조이고 [0,1) 안에 머문다.
        conflict = 1.0 - (1.0 - self.conflict) * (1.0 - k)
        return BeliefMass(occupied, free, unknown, conflict)

    def discount(self, alpha: float) -> "BeliefMass":
        """특정성을 깎아 `m(Ω)` 로 보낸다. 노후화와 자세 품질이 같이 쓰는 연산.

        `alpha=1` 은 그대로, `alpha=0` 은 완전 무지. **`free` 가 늘어나는 경로가 없는
        것이 핵심이다** — 시간이 갔다는 사실은 비었다는 근거가 될 수 없고(규칙 2),
        자세가 나쁘다는 사실도 그렇다(규칙 6).
        """
        a = max(0.0, min(1.0, alpha))
        occupied = self.occupied * a
        free = self.free * a
        return BeliefMass(occupied, free, 1.0 - occupied - free, self.conflict)

    @property
    def total_claim(self) -> float:
        """주장에 걸린 질량. 1 - 모름."""
        return self.occupied + self.free

    def as_dict(self) -> dict:
        return {dd.MASS_OCCUPIED: round(self.occupied, 6),
                dd.MASS_FREE: round(self.free, 6),
                dd.MASS_UNKNOWN: round(self.unknown, 6),
                dd.MASS_CONFLICT: round(self.conflict, 6)}


#: 한 관측이 가질 수 있는 최대 질량. 1 미만이어야 칸이 영원히 고정되지 않는다.
_MAX_CLAIM_STRENGTH = 0.95


# ---------------------------------------------------------------------------
# 등록된 관측 종류
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MapObservationKindSpec:
    """지도 관측 1종의 선언. **데이터이고 코드 분기가 아니다**(AI-C-18).

    한 종류가 주장할 수 있는 성질은 네 가지다 — 어떤 격인가, **비었다고 말할 자격이
    있는가**, 카메라 자세를 통과해 왔는가, 얼마나 빨리 낡는가.
    """

    kind: str
    tier: str
    #: 비었다는 주장을 낼 수 있는가. 박스 탐지는 **없다**: 광선이 없으므로 앞쪽이
    #: 비었다고 말할 근거가 없고, 그 말을 허용하면 침묵이 부재로 환산된다(규칙 1).
    may_claim_free: bool = False
    #: 카메라 자세를 통과해 미터 자리로 왔는가. 참이면 자세 품질 할인이 걸린다.
    #: 사람이 줄자로 잰 값은 어떤 자세도 통과하지 않으므로 거짓이다(규칙 6).
    through_pose: bool = True
    #: 반감기(호출자 시계 단위). None 은 **낡지 않는다** 는 뜻이고 게으름이 아니다 —
    #: 도면에 적힌 벽은 최신성 주장을 하지 않으며, 사전정보의 노후 판정은
    #: `environment_prior.PriorInfoStore` 가 유효기간으로 따로 소유한다.
    half_life_s: float | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("kind must not be empty")
        if self.tier not in _TIER_RANK:
            raise ValueError(f"unknown evidence tier {self.tier!r}; "
                             f"expected one of {tuple(_TIER_RANK)}")
        if self.half_life_s is not None and not self.half_life_s > 0.0:
            raise ValueError(f"{self.kind}: half_life_s must be > 0 or None")

    @property
    def is_prior(self) -> bool:
        """사전정보 격인가. 참이면 이 종류만으로는 칸을 주장하지 못한다(규칙 5)."""
        return self.tier in PRIOR_TIERS


@dataclass
class MapObservationKindRegistry:
    """등록된 지도 관측 종류. 등록되지 않은 종류는 조용히 사라지지 않고 **사유로** 남는다 —
    종류 이름 오타가 지도를 바꾸지 않은 채 없어지는 것이 가장 찾기 어려운 버그다.
    """

    _specs: dict[str, MapObservationKindSpec] = field(default_factory=dict)

    def register(self, spec: MapObservationKindSpec) -> MapObservationKindSpec:
        self._specs[spec.kind] = spec
        return spec

    def spec(self, kind: str) -> MapObservationKindSpec | None:
        return self._specs.get(kind)

    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def copy(self) -> "MapObservationKindRegistry":
        return MapObservationKindRegistry(dict(self._specs))


def default_observation_kinds() -> MapObservationKindRegistry:
    """현재 배포가 아는 종류. 새 종류는 `register()` 로 늘리고 코드는 그대로다."""
    registry = MapObservationKindRegistry()
    for spec in (
        MapObservationKindSpec(
            "object_detection", TIER_ESTIMATED, may_claim_free=False,
            through_pose=True, half_life_s=120.0,
            note="박스 1건이 미터 자리로 투영된 것. 광선이 없으므로 비었다고 말할 수 "
                 "없고, 움직이는 것을 보므로 빨리 낡는다."),
        MapObservationKindSpec(
            "structure_detection", TIER_ESTIMATED, may_claim_free=False,
            through_pose=True, half_life_s=3600.0,
            note="고정 구조로 보이는 것. 같은 광선 부재지만 잘 안 움직이므로 천천히 낡는다."),
        MapObservationKindSpec(
            "swept_free_space", TIER_ESTIMATED, may_claim_free=True,
            through_pose=True, half_life_s=600.0,
            note="깊이·점군처럼 **광선을 가진** 출처가 '여기까지 아무것도 없었다' 를 "
                 "보고한 것. 비었다고 말할 자격이 있는 유일한 센서 종류다."),
        MapObservationKindSpec(
            "declared_obstacle", TIER_DECLARED, may_claim_free=False,
            through_pose=False, half_life_s=None,
            note="도면·프로파일에 적힌 설치물·벽. 실측이 아니라 선언이므로 혼자서는 "
                 "어떤 칸도 주장하지 못한다(AI-S-08)."),
        MapObservationKindSpec(
            "declared_free_space", TIER_DECLARED, may_claim_free=True,
            through_pose=False, half_life_s=None,
            note="도면이 통로라고 적은 자리. 선언은 관측을 **거들 뿐** 확정하지 않는다 — "
                 "도면을 정답으로 쓰면 as-built 가 어긋날 때 탐지가 범인이 된다."),
        MapObservationKindSpec(
            "human_survey", TIER_MEASURED, may_claim_free=True,
            through_pose=False, half_life_s=None,
            note="사람이 현장에서 재어 표시한 칸. 어떤 카메라 자세도 통과하지 않으므로 "
                 "자세 할인이 걸리지 않는다."),
        MapObservationKindSpec(
            "historical_observation", TIER_DECLARED, may_claim_free=False,
            through_pose=False, half_life_s=None,
            note="지난 운용의 관측을 사전정보로 되읽은 것. 과거 관측은 AI-S-08 기준 "
                 "**사전정보**이고 지금의 관측이 아니다."),
    ):
        registry.register(spec)
    return registry


#: 모듈 기본 레지스트리. 배치별로 바꿔야 하면 `copy()` 해서 쓴다.
DEFAULT_OBSERVATION_KINDS = default_observation_kinds()


# ---------------------------------------------------------------------------
# 현장 datum — 로컬에서 전역으로 가는 길, 그리고 그 길의 품질
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SiteDatum:
    """현장 로컬 프레임을 전역 프레임에 접지시키는 변환. **상수가 아니라 근거다.**

    같은 변환이라도 측량 기준점에서 나온 것과 주소를 보고 어림한 것은 품질이 전혀
    다르다. 그래서 datum 은 다른 모든 관측과 같은 형식을 쓴다 — 격(`tier`), 스스로
    **선언한** 정확도(`accuracy_m`, None 은 모름이고 모름으로 남는다), 출처, 생성 시점.

    정확도를 모르는 datum 으로 전역 좌표를 내지 않는 이유: 전역 값이 **얼마나 틀렸는지
    말할 수 없는 상태**로 나가면, 그 값을 받은 쪽은 로컬 측정과 같은 품질로 취급한다.
    그것이 두 authoritative 소유자가 생기는 실패와 같은 종류의 실패다 — 품질을 잃은
    값은 이미 다른 값이다.
    """

    datum_id: str
    #: 이 datum 이 접지시키는 로컬 프레임 이름.
    local_frame: str
    #: 접지된 전역 프레임 이름(사전 `coordinate_frame` 어휘의 GLOBAL).
    global_frame: str = FRAME_GLOBAL
    #: 로컬 원점이 전역에서 놓이는 자리. 단위는 전역 프레임의 단위다.
    offset: tuple[float, float] = (0.0, 0.0)
    #: 로컬 축을 전역 축에 맞추는 회전(도).
    rotation_deg: float = 0.0
    tier: str = TIER_ESTIMATED
    #: 이 변환이 스스로 선언한 1σ 정확도. None 은 모름이고 추정하지 않는다.
    accuracy_m: float | None = None
    source: str = ""
    established_at: float = 0.0
    note: str = ""

    def __post_init__(self) -> None:
        if not self.datum_id:
            raise ValueError("datum_id must not be empty")
        if not self.local_frame:
            raise ValueError("local_frame must not be empty")
        if self.tier not in _TIER_RANK:
            raise ValueError(f"unknown datum tier {self.tier!r}")
        if self.accuracy_m is not None and not self.accuracy_m > 0.0:
            # 0 은 "완벽" 이 아니다. 모르면 None 으로 적는다.
            raise ValueError(f"{self.datum_id}: accuracy_m must be > 0 or None")

    @property
    def quantified(self) -> bool:
        """전역 값의 품질을 말할 수 있는가. 거짓이면 전역 표현을 거절한다."""
        return self.accuracy_m is not None

    def to_global(self, local: tuple[float, float]) -> tuple[float, float]:
        """로컬 평면 점을 전역 프레임으로. 회전 뒤 평행이동, 그 이상 하지 않는다."""
        rad = math.radians(self.rotation_deg)
        cos_r, sin_r = math.cos(rad), math.sin(rad)
        x = local[0] * cos_r - local[1] * sin_r + self.offset[0]
        y = local[0] * sin_r + local[1] * cos_r + self.offset[1]
        return (x, y)

    def as_dict(self) -> dict:
        return {dd.DATUM_ID: self.datum_id,
                dd.COORDINATE_FRAME: self.global_frame,
                dd.EVIDENCE_TIER: self.tier,
                dd.ACCURACY_M: self.accuracy_m,
                dd.DATUM_SOURCE: self.source}


@dataclass(frozen=True)
class FramedPosition:
    """한 자리를, **어느 프레임의 값인지 잃지 않은 채로** 낸 결과.

    `value` 가 None 이면 그 프레임으로는 답하지 않았다는 뜻이고 `refused_because` 가
    사유를 든다. 지어낸 좌표를 내보내는 것보다 거절하는 편이 언제나 낫다 — 틀린 전역
    좌표는 조용히 전파되고, 거절은 눈에 보인다.
    """

    value: tuple[float, float] | None
    coordinate_frame: str
    #: 이 자리의 1σ 정확도. 전역 값은 **datum 보다 좋을 수 없다**(규칙 4, 6).
    accuracy_m: float | None = None
    #: 전역 값일 때 통과한 datum. 로컬 값이면 None.
    datum_id: str | None = None
    #: 이 값이 어느 로컬 값에서 나왔는가. 전역 추정의 출처를 잃지 않는 칸이다.
    derived_from: tuple[float, float] | None = None
    derived_frame: str | None = None
    #: 전역 값의 품질을 지배한 축: datum 과 로컬 중 나쁜 쪽.
    limited_by: str | None = None
    refused_because: str | None = None

    @property
    def available(self) -> bool:
        return self.value is not None

    @property
    def is_global(self) -> bool:
        return self.coordinate_frame == FRAME_GLOBAL

    def as_dict(self) -> dict:
        """로컬 값과 전역 값을 **서로 다른 칸**에 담는다(AI-C-02).

        한 칸(`fused_value`)에 담고 좌표계 이름만 옆에 적는 것으로는 부족하다 —
        전역 응답에서 그 칸을 읽는 쪽은 재료가 된 로컬 측정을 되짚을 수 없고, 로컬
        응답과 전역 응답이 같은 이름으로 와서 **교환 가능한 값처럼 보인다**. 그래서
        전역 응답에서도 `local_position` 은 비지 않고 그 전역 값이 유도된 재료를
        들며, 그것은 전역 값의 사본이 아니다.
        """
        local = self.derived_from if self.is_global else self.value
        return {dd.COORDINATE_FRAME: self.coordinate_frame,
                dd.LOCAL_POSITION: None if local is None else list(local),
                dd.GLOBAL_POSITION: (list(self.value) if self.is_global
                                     and self.value is not None else None),
                dd.DERIVED_FROM_FRAME: self.derived_frame,
                dd.ACCURACY_M: self.accuracy_m,
                dd.DATUM_ID: self.datum_id,
                dd.ACCURACY_LIMITED_BY: self.limited_by,
                dd.FRAME_REFUSAL_REASON: self.refused_because}


# ---------------------------------------------------------------------------
# 관측과 거절
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MapObservation:
    """지도에 대한 근거 1건.

    provenance 모양은 `object_record.Evidence` · `spatial_evidence.SpatialObservation`
    과 같은 칸 이름을 쓴다(`source_group` · `frame_ref` · `observed_at`) — 같은 뜻의
    출처 정보를 세 모양으로 들고 다니면 근거를 서로 되짚을 수 없다.

    `footprint` 는 **현장 로컬 미터**의 (x1, y1, x2, y2) 이다. 자리의 불확실성은
    footprint 크기로 들어오고(선언 정확도가 있으면 `observation_from_point` 가 키워
    준다), 자세의 불확실성은 `pose_quality` 할인으로 들어온다 — 두 축을 한 칸에
    합치면 "어디인지 모른다" 와 "카메라를 못 믿는다" 가 구분되지 않는다.
    """

    observation_id: str
    source_group: str          # provenance: 어느 출처 묶음이 냈는가
    frame_ref: str             # 원본 관측 — **독립성의 단위**
    observed_at: float
    observation_kind: str      # 등록된 종류
    claim: str                 # CLAIM_OCCUPIED | CLAIM_FREE
    footprint: tuple[float, float, float, float]
    frame_id: str              # 현장 로컬 프레임
    #: 할인 전 주장 세기 [0, 1).
    strength: float = 0.6
    pose_quality: str = POSE_DECLARED
    anchor_id: str | None = None
    #: 사전정보로 들어온 경우 그 레코드. 출처를 되짚는 칸이고 여기서 유효성을 재판정하지 않는다.
    prior_record_id: str | None = None
    detail: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.observation_id:
            raise ValueError("observation_id must not be empty")
        if not self.frame_ref:
            raise ValueError("frame_ref must not be empty")
        if not 0.0 <= self.strength < 1.0:
            # 1.0 은 어떤 반대 근거로도 움직이지 않는 칸을 만든다. 관측은 확정이 아니다.
            raise ValueError(f"{self.observation_id}: strength must be in [0, 1), "
                             f"got {self.strength}")
        x1, y1, x2, y2 = self.footprint
        if x2 < x1 or y2 < y1:
            raise ValueError(f"{self.observation_id}: footprint must be "
                             "(x1, y1, x2, y2) with x2 >= x1 and y2 >= y1")


@dataclass(frozen=True)
class RejectedMapObservation:
    """쓰지 못한 관측과 사유. 조용히 버리지 않는 이유는 규칙 3 과 같다."""

    observation_id: str
    observation_kind: str
    reason: str
    detail: str = ""

    def as_dict(self) -> dict:
        return {dd.OBSERVATION_ID: self.observation_id,
                dd.OBSERVATION_KIND: self.observation_kind,
                dd.REJECTION_REASON: self.reason,
                dd.REJECTION_DETAIL: self.detail}


# ---------------------------------------------------------------------------
# 칸 하나의 상태
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CellContribution:
    """한 관측이 이 칸에 어떻게 들어갔는가. 융합 뒤에도 이 줄이 남는다(규칙 3)."""

    observation_id: str
    observation_kind: str
    tier: str
    source_group: str
    frame_ref: str
    claim: str
    observed_at: float
    #: 등록 세기.
    declared_strength: float
    #: 자세 품질 할인 뒤.
    pose_discounted: float
    #: 노후화 할인까지 뒤 — 실제로 융합에 들어간 세기.
    applied_strength: float
    pose_quality: str
    role: str
    prior_record_id: str | None = None

    @property
    def weighted(self) -> bool:
        return self.role == ROLE_INDEPENDENT

    def as_dict(self) -> dict:
        """할인 **전**과 **후**를 같이 싣는다.

        적용된 세기만 내보내면 "약한 관측" 과 "센 관측을 못 믿는 자세로 깎은 것" 이
        같은 숫자로 보이고, 그러면 자세 품질을 고쳐야 하는지 센서를 고쳐야 하는지
        구분할 수 없다(규칙 3·6).
        """
        return {dd.OBSERVATION_ID: self.observation_id,
                dd.OBSERVATION_KIND: self.observation_kind,
                dd.EVIDENCE_TIER: self.tier,
                dd.SOURCE_GROUP: self.source_group,
                dd.FRAME_REF: self.frame_ref,
                dd.TWIN_MAP_CLAIM: self.claim,
                dd.OBSERVED_AT: self.observed_at,
                dd.EVIDENCE_STRENGTH: round(self.declared_strength, 6),
                dd.APPLIED_STRENGTH: round(self.applied_strength, 6),
                dd.POSE_QUALITY: self.pose_quality,
                dd.CONTRIBUTION_ROLE: self.role}


@dataclass(frozen=True)
class CellLeaveOneOut:
    """그 출처를 빼면 이 칸이 무엇이 되는가.

    `state_flipped` 가 참이면 그 출처 하나가 읽기값을 정하고 있었다는 뜻이다. 지도가
    틀렸다고 들고 왔을 때 먼저 보는 줄이 이것이다.
    """

    removed: str
    unit: str
    state: CellState
    mass: BeliefMass
    #: 점유 질량이 움직인 양. 부호가 있다 — 그 출처가 점유 쪽으로 끌었는지 반대인지.
    occupancy_influence: float
    state_flipped: bool

    def as_dict(self) -> dict:
        return {"removed": self.removed, "unit": self.unit,
                dd.CELL_STATE: self.state.value,
                dd.OCCUPANCY_INFLUENCE: round(self.occupancy_influence, 6),
                **self.mass.as_dict()}


@dataclass(frozen=True)
class CellBelief:
    """칸 하나의 현재 믿음과 **그렇게 된 이유** 전부."""

    cell: tuple[int, int]
    cell_size_m: float
    frame_id: str
    mass: BeliefMass
    #: 관측 격(measured/estimated)의 **독립** 지지 수. 같은 `frame_ref` 두 개는 하나다.
    observed_support: int = 0
    #: 사전정보 격 기여 수. 지지 수와 따로 세는 이유는 규칙 5 다.
    prior_support: int = 0
    last_observed_at: float | None = None
    source_groups: tuple[str, ...] = ()
    contributions: tuple[CellContribution, ...] = ()
    #: 사전정보만 있을 때 그 사전정보가 뭐라고 했는가. 읽기값은 여전히 UNKNOWN 이고
    #: 이 칸은 "도면은 벽이라고 한다" 를 **주장과 섞지 않고** 전한다(AI-S-08).
    prior_claim: str | None = None
    best_tier: str | None = None
    #: 이 칸을 받친 자세 품질 중 가장 나쁜 것. 전역 표현의 품질 상한에 들어간다.
    weakest_pose_quality: str | None = None
    #: 이 칸을 다시 융합할 수 있도록 받아들인 관측을 들고 있다. leave-one-out 이 쓴다.
    accepted: tuple[MapObservation, ...] = ()

    # -- 읽기값 -----------------------------------------------------------

    @property
    def state(self) -> CellState:
        """세 주장과 '봐 놓고 싸운 상태' 중 하나.

        순서가 중요하다. 사전정보만 있는 칸을 먼저 걸러내는 이유는 AI-S-08 이다 —
        도면이 벽이라고 적었다는 사실만으로 그 칸이 점유로 **확정되면**, as-built 가
        어긋난 현장에서 탐지는 영원히 틀린 쪽이 된다.
        """
        if not self.contributions:
            return CellState.UNKNOWN
        if self.observed_support <= 0:
            return CellState.UNKNOWN
        if self.mass.conflict >= CONFLICT_THRESHOLD:
            return CellState.DISPUTED
        if self.mass.occupied >= CLAIM_THRESHOLD and self.mass.occupied > self.mass.free:
            return CellState.OCCUPIED
        if self.mass.free >= CLAIM_THRESHOLD and self.mass.free > self.mass.occupied:
            return CellState.FREE
        return CellState.UNKNOWN

    @property
    def never_observed(self) -> bool:
        """관측 격 근거가 한 번도 닿지 않았는가. 사전정보는 관측이 아니다."""
        return self.last_observed_at is None

    @property
    def independent_support(self) -> int:
        return self.observed_support

    def is_stale(self, now: float, stale_after: float = DEFAULT_STALE_AFTER) -> bool:
        """마지막 관측이 지금을 받치기에 너무 오래됐는가.

        한 번도 관측되지 않은 칸은 같은 규칙으로 stale 이다 — 받칠 관측이 아예 없다.
        그러나 `never_observed` 와 **같은 상태가 아니다**: 하나는 가서 본 적이 없다는
        뜻이고 하나는 본 것이 낡았다는 뜻이며, 운영자의 대응이 다르다.
        """
        if self.last_observed_at is None:
            return True
        return (now - self.last_observed_at) > stale_after

    def as_dict(self) -> dict:
        return {
            dd.MAP_CELL_ID: f"{self.cell[0]},{self.cell[1]}",
            dd.COORDINATE_FRAME: FRAME_ZONE,
            dd.CELL_STATE: self.state.value,
            **self.mass.as_dict(),
            dd.OBSERVED_SUPPORT_COUNT: self.observed_support,
            dd.PRIOR_SUPPORT_COUNT: self.prior_support,
            dd.LAST_OBSERVED_AT: self.last_observed_at,
            dd.NEVER_OBSERVED: self.never_observed,
            dd.PRIOR_CLAIM: self.prior_claim,
            dd.EVIDENCE_TIER: self.best_tier,
            dd.POSE_QUALITY: self.weakest_pose_quality,
            dd.CONTRIBUTIONS: [row.as_dict() for row in self.contributions],
        }


@dataclass(frozen=True)
class RegionSummary:
    """사각 영역 하나를 칸 단위 사실로 요약한다. **모름을 숨기지 않는다.**

    `unknown_cells` 와 `never_observed_cells` 를 따로 세는 이유: 봤지만 주장이 서지
    않은 칸과 아예 본 적 없는 칸은 다른 문제다. 하나는 근거가 모자라고 하나는
    관측 자체가 없다.
    """

    frame_id: str
    region: tuple[float, float, float, float]
    total_cells: int
    unknown_cells: int
    free_cells: int
    occupied_cells: int
    disputed_cells: int
    never_observed_cells: int
    stale_cells: int
    oldest_observation_at: float | None = None
    newest_observation_at: float | None = None

    @property
    def claimed_fraction(self) -> float:
        """주장이 선 칸의 비율. '커버리지' 가 아니다 — 커버리지는 coverage.py 의 것이다."""
        if not self.total_cells:
            return 0.0
        return (self.free_cells + self.occupied_cells) / self.total_cells

    @property
    def unknown_fraction(self) -> float:
        if not self.total_cells:
            return 1.0
        return (self.unknown_cells + self.disputed_cells) / self.total_cells

    def as_dict(self) -> dict:
        return {dd.COORDINATE_FRAME: FRAME_ZONE,
                dd.MAP_REGION_ID: f"{self.region}",
                dd.TOTAL_CELL_COUNT: self.total_cells,
                dd.UNKNOWN_CELL_COUNT: self.unknown_cells,
                dd.FREE_CELL_COUNT: self.free_cells,
                dd.OCCUPIED_CELL_COUNT: self.occupied_cells,
                dd.DISPUTED_CELL_COUNT: self.disputed_cells,
                dd.NEVER_OBSERVED_CELL_COUNT: self.never_observed_cells,
                dd.STALE_CELL_COUNT: self.stale_cells}


# ---------------------------------------------------------------------------
# 생존 추정 — "안 봤다" 와 "봤는데 없었다" 를 나누는 자리
# ---------------------------------------------------------------------------

#: 음성 보고의 기본 미검출률 `P_M = p(y=0 | 있음)`. 보수적으로 크게 잡는다 — 작게
#: 잡으면 한 번의 오검출이 믿음을 무너뜨린다(persistence filter 의 알려진 민감성).
DEFAULT_MISS_RATE = 0.3
#: 양성 보고의 기본 오경보율 `P_F = p(y=1 | 없음)`.
DEFAULT_FALSE_ALARM_RATE = 0.05
#: 생존 사전확률의 기본 반감기.
DEFAULT_SURVIVAL_HALF_LIFE = 600.0

#: `PersistenceReport.explained_by` 어휘.
PERSISTENCE_BY_SIGHTING = "sighting"
PERSISTENCE_BY_NEGATIVE_REPORT = "negative_report"
PERSISTENCE_BY_PRIOR_DECAY = "prior_decay_only"


@dataclass(frozen=True)
class PersistenceReport:
    """한 요소가 아직 거기 있다고 믿는 정도, 그리고 **무엇 때문에** 그런가."""

    element_id: str
    belief: float
    #: 관측을 하나도 세지 않은 순수 생존 사전확률. 믿음과 나란히 적는 이유는
    #: "관측이 끌어내린 것" 과 "시간만 흐른 것" 을 구분하기 위해서다.
    survival_prior: float
    sightings: int
    negative_reports: int
    last_sighting_at: float | None
    last_report_at: float | None
    explained_by: str

    def as_dict(self) -> dict:
        """**봤다 · 봤는데 없었다 · 안 봤다** 를 세 칸으로 낸다.

        마지막으로 본 시각을 `last_observed_at` 이라는 이름으로 내보내면 음성 보고가
        관측에서 빠지고, 그러면 "봤는데 없었다" 와 "안 봤다" 가 payload 에서 같은
        모양이 된다 — 이 모듈 전체가 막는 바로 그 혼동이다. 그래서 본 시각
        (`last_sighting_at`)과 보고 시각(`last_report_at`)을 나누고, 양쪽 보고 수를
        함께 싣는다.
        """
        return {dd.MAP_ELEMENT_ID: self.element_id,
                dd.PERSISTENCE_BELIEF: round(self.belief, 6),
                dd.SURVIVAL_PRIOR: round(self.survival_prior, 6),
                dd.SIGHTING_COUNT: self.sightings,
                dd.NEGATIVE_REPORT_COUNT: self.negative_reports,
                dd.LAST_SIGHTING_AT: self.last_sighting_at,
                dd.LAST_REPORT_AT: self.last_report_at,
                dd.PERSISTENCE_EXPLAINED_BY: self.explained_by}


@dataclass
class ElementPersistence:
    """요소 하나의 생존 필터(Rosen, Mason & Leonard, ICRA 2016).

    왜 이 필터인가. 우리는 희소·비동기 탐지를 받고, 촘촘한 센서도 odometry 도 없다.
    이 필터는 그 셋을 하나도 요구하지 않으면서 우리에게 **가장 중요한 구분을 수식에
    넣는다**:

    * `record_sighting()` — 봤다(`y=1`). 우도 인자 `1 - P_F`.
    * `record_absence()`  — **봤는데 없었다**(`y=0`). 우도 인자 `P_M`. 믿음을 내리지만
      검출기의 미검출률이 그 크기의 상한이다.
    * 아무 호출도 하지 않음 — **보지 않았다**. 우도 인자가 아예 들어가지 않고, 믿음은
      생존 사전확률 `1 - F_T(t)` 를 통해서만 내려간다.

    마지막 줄이 핵심이다. 규칙 8("없는 제공자는 반대 근거가 아니다")이 주석에 적힌
    약속이 아니라 **수식의 성질**이 된다. 그래서 `record_absence()` 는 '봤다' 는 사실을
    아는 출처만 부를 수 있다 — 자기가 봤는지 안 봤는지 구분하지 못하는 provider 가
    이것을 부르면 침묵이 부재로 환산되고, 그것이 이 모듈 전체가 막는 실패다.
    """

    element_id: str
    born_at: float = 0.0
    half_life_s: float = DEFAULT_SURVIVAL_HALF_LIFE
    #: (시각, 봤는가, P_M, P_F) — 들어온 순서대로.
    reports: list[tuple[float, bool, float, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.half_life_s > 0.0:
            raise ValueError(f"{self.element_id}: half_life_s must be > 0")

    # -- 보고 ------------------------------------------------------------

    def record_sighting(self, at: float, *,
                        false_alarm_rate: float = DEFAULT_FALSE_ALARM_RATE,
                        miss_rate: float = DEFAULT_MISS_RATE) -> None:
        """봤다. `y=1`."""
        self.reports.append((at, True, _rate(miss_rate), _rate(false_alarm_rate)))

    def record_absence(self, at: float, *,
                       miss_rate: float = DEFAULT_MISS_RATE,
                       false_alarm_rate: float = DEFAULT_FALSE_ALARM_RATE) -> None:
        """**봤는데 없었다.** `y=0`.

        보지 않은 출처는 이것을 부르지 않는다 — 아무것도 부르지 않는 것이 "보지 않았다"
        의 표현이고, 그 경우 믿음은 생존 사전확률로만 내려간다.
        """
        self.reports.append((at, False, _rate(miss_rate), _rate(false_alarm_rate)))

    # -- 읽기 ------------------------------------------------------------

    def survival_prior(self, now: float) -> float:
        """`1 - F_T(t)`. 지수 생존 사전확률."""
        elapsed = max(0.0, now - self.born_at)
        return math.exp(-elapsed * math.log(2.0) / self.half_life_s)

    def belief(self, now: float) -> PersistenceReport:
        """`p(X_t = 1 | Y_{1:N})` 를 상수시간 재귀로 낸다."""
        ordered = sorted(self.reports, key=lambda r: r[0])
        # L_N — "이미 사라졌다" 쪽으로 간 증거 질량.
        evidence_gone = 0.0
        # p(Y_{1:N} | T >= t_N) — "아직 있다" 가정 아래의 우도.
        likelihood_present = 1.0
        previous_cdf = 0.0
        previous_time = self.born_at
        for at, seen, miss, false_alarm in ordered:
            cdf = 1.0 - self.survival_prior(at)
            accrued = max(0.0, cdf - previous_cdf)
            detector_absent = false_alarm if seen else (1.0 - false_alarm)
            # 사라졌다는 가지: 직전까지의 우도에 그 사이 쌓인 사전 질량을 곱해 더한다.
            evidence_gone = detector_absent * (
                evidence_gone + likelihood_present * accrued)
            likelihood_present *= (1.0 - miss) if seen else miss
            previous_cdf, previous_time = cdf, at

        last_time = previous_time
        survival_at_last = self.survival_prior(last_time)
        evidence = evidence_gone + likelihood_present * survival_at_last
        survival_now = self.survival_prior(now)
        if evidence <= 0.0:
            # 어느 가지도 질량을 갖지 못했다 — 믿을 근거가 없으므로 사전확률만 남긴다.
            belief = survival_now
        else:
            belief = min(1.0, max(0.0, likelihood_present * survival_now / evidence))

        sightings = sum(1 for _, seen, _, _ in ordered if seen)
        negatives = len(ordered) - sightings
        last_sighting = max((at for at, seen, _, _ in ordered if seen), default=None)
        if negatives and (last_sighting is None or
                          max(at for at, seen, _, _ in ordered if not seen) > last_sighting):
            explained = PERSISTENCE_BY_NEGATIVE_REPORT
        elif sightings:
            explained = PERSISTENCE_BY_SIGHTING
        else:
            explained = PERSISTENCE_BY_PRIOR_DECAY
        return PersistenceReport(
            element_id=self.element_id, belief=belief, survival_prior=survival_now,
            sightings=sightings, negative_reports=negatives,
            last_sighting_at=last_sighting,
            last_report_at=last_time if ordered else None,
            explained_by=explained,
        )


def _rate(value: float) -> float:
    """검출기 비율을 열린 구간 (0, 1) 로 가둔다.

    0 이나 1 을 허용하면 한 번의 보고가 믿음을 0 또는 1 로 못박고, 그 뒤 어떤 관측도
    그 칸을 움직이지 못한다.
    """
    return min(0.999, max(0.001, value))


# ---------------------------------------------------------------------------
# 지도 층
# ---------------------------------------------------------------------------

@dataclass
class TwinMapLayer:
    """탐지로 지은, 질의 가능한 현장 지도.

    칸과 융합은 **현장 로컬 미터**다. 전역 표현은 `position_in()` 이 선언된 datum 을
    통과해서만 내고, datum 이 없거나 정확도를 모르면 사유와 함께 거절한다. datum 이
    없는 현장은 정상 상태이고 로컬 지도는 그대로 동작한다(AI-C-05).

    믿음은 저장하지 않고 **읽을 때마다 받아들인 관측에서 다시 융합한다.** 비싸 보이지만
    이것이 규칙 2·3 을 동시에 만족하는 유일한 방법이다 — 노후화 할인이 관측별 나이로
    걸리므로 감쇠가 **상태가 아니라 함수**가 되고, 그래서 leave-one-out 이 근사치가
    아니라 정확한 재계산이 된다. 질량을 제자리에서 깎아 두면 출처 하나를 빼는 질문에
    답할 수 없다.
    """

    cell_size_m: float = 1.0
    frame_id: str = "zone"
    kinds: MapObservationKindRegistry = field(
        default_factory=DEFAULT_OBSERVATION_KINDS.copy)
    anchors: dict[str, Anchor] = field(default_factory=dict)
    #: 선언된 datum. 없으면 전역 표현만 거절되고 로컬은 그대로다.
    datum: SiteDatum | None = None
    pose_discount: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_POSE_DISCOUNT))
    stale_after: float = DEFAULT_STALE_AFTER
    #: 칸별로 받아들인 관측. 융합 결과가 아니라 **원재료**를 들고 있다.
    _cells: dict[tuple[int, int], list[MapObservation]] = field(default_factory=dict)
    _seen: set[str] = field(default_factory=set)
    _rejected: list[RejectedMapObservation] = field(default_factory=list)
    _persistence: dict[str, ElementPersistence] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.cell_size_m > 0.0:
            raise ValueError("cell_size_m must be positive")

    # -- 선언 -------------------------------------------------------------

    def capability_state(self, available_kinds: set[str]) -> CapabilityState:
        return REQUIREMENT.evaluate(available_kinds)

    def declare_anchor(self, anchor: Anchor) -> None:
        """백엔드가 알려 준 기준을 등록한다. 여기서 재판정하지 않는다."""
        self.anchors[anchor.anchor_id] = anchor

    def declare_datum(self, datum: SiteDatum) -> None:
        """현장 로컬 → 전역 변환을 **근거로** 등록한다.

        프레임 이름이 이 층의 로컬 프레임과 다르면 받지 않는다 — 다른 현장의 datum 으로
        이 현장 좌표를 옮기면 그 값은 어느 프레임의 값도 아니다.
        """
        if datum.local_frame != self.frame_id:
            raise ValueError(f"datum {datum.datum_id!r} grounds {datum.local_frame!r}, "
                             f"not this layer's frame {self.frame_id!r}")
        self.datum = datum

    def register_observation_kind(self, spec: MapObservationKindSpec) -> None:
        """새 관측 종류를 등록한다. 코드를 고치지 않고 늘리는 자리다(규칙 7)."""
        self.kinds.register(spec)

    def set_pose_discount(self, pose_quality: str, discount: float) -> None:
        """자세 품질 등급의 할인 계수를 등록·변경한다.

        새 등급이 생겨도 이 모듈에 `if` 가 늘지 않는 이유가 이 메서드다.
        """
        if not 0.0 <= discount <= 1.0:
            raise ValueError("discount must be in [0, 1]")
        self.pose_discount[pose_quality] = discount

    # -- 격자 -------------------------------------------------------------

    def cell_of(self, x: float, y: float) -> tuple[int, int]:
        """로컬 미터 점이 들어가는 칸."""
        return (math.floor(x / self.cell_size_m), math.floor(y / self.cell_size_m))

    def cell_centre(self, cell: tuple[int, int]) -> tuple[float, float]:
        """칸의 로컬 미터 중심."""
        return ((cell[0] + 0.5) * self.cell_size_m, (cell[1] + 0.5) * self.cell_size_m)

    def cells_in(self, region: tuple[float, float, float, float]) -> tuple[tuple[int, int], ...]:
        """영역이 건드리는 칸 전부. 한 번도 관측되지 않은 칸을 **생략하지 않는다** —
        목록에서 빠진 칸은 화면에서 비어 보이고, 그것이 규칙 1 을 깨는 길이다.
        """
        x1, y1, x2, y2 = region
        lo = self.cell_of(min(x1, x2), min(y1, y2))
        hi = self.cell_of(max(x1, x2), max(y1, y2))
        return tuple((ix, iy)
                     for ix in range(lo[0], hi[0] + 1)
                     for iy in range(lo[1], hi[1] + 1))

    # -- 누적 -------------------------------------------------------------

    def ingest(self, observation: MapObservation, *,
               available_sources: set[str] | None = None) -> tuple[tuple[int, int], ...]:
        """관측 1건을 지도에 넣고, 닿은 칸들을 돌려준다.

        `available_sources` 는 capability registry 에서 온다. 지금 쓸 수 없는 출처의
        관측은 **반대 근거가 아니라 없는 것**으로 다룬다(규칙 8, AI-C-05). 거절은
        예외로 올리지 않고 `rejected()` 에 사유로 남는다 — 선택 출처 하나의 문제가
        지도 전체를 멈추게 하지 않는다.
        """
        spec = self.kinds.spec(observation.observation_kind)
        if spec is None:
            self._reject(observation, REJECT_UNREGISTERED_KIND,
                         f"register a MapObservationKindSpec for "
                         f"{observation.observation_kind!r} first")
            return ()
        if observation.claim not in MAP_CLAIMS:
            self._reject(observation, REJECT_UNKNOWN_CLAIM, observation.claim)
            return ()
        if available_sources is not None and observation.source_group not in available_sources:
            self._reject(observation, REJECT_SOURCE_UNAVAILABLE, observation.source_group)
            return ()
        if observation.frame_id != self.frame_id:
            # 변환 없이 섞으면 그 값은 아무 프레임의 값도 아니다.
            self._reject(observation, REJECT_FRAME_MISMATCH,
                         f"{observation.frame_id!r} != layer frame {self.frame_id!r}")
            return ()
        if observation.claim == CLAIM_FREE and not spec.may_claim_free:
            # 여기가 이 모듈의 중심 규칙이다. 박스 탐지에 자유 주장을 허용하면
            # 제공자의 침묵이 "비었다" 로 환산되고 지도는 조용히 거짓말을 시작한다.
            self._reject(observation, REJECT_FREE_CLAIM_NOT_PERMITTED,
                         f"{spec.kind!r} has no ray model; only a swept or declared "
                         "source may claim free space")
            return ()
        if observation.observation_id in self._seen:
            self._reject(observation, REJECT_DUPLICATE)
            return ()

        cells = self.cells_in(observation.footprint)
        if not cells:
            self._reject(observation, REJECT_EMPTY_FOOTPRINT)
            return ()

        self._seen.add(observation.observation_id)
        for cell in cells:
            self._cells.setdefault(cell, []).append(observation)
        return cells

    def ingest_prior(self, record: PriorInfoRecord, *, now: float,
                     footprint: tuple[float, float, float, float],
                     claim: str = CLAIM_OCCUPIED,
                     observation_kind: str = "declared_obstacle",
                     strength: float = 0.4) -> tuple[tuple[int, int], ...]:
        """사전정보 레코드 1건을 **약한 격으로** 지도에 넣는다(AI-S-08).

        유효하지 않은(기간 밖이거나 사용 불가로 표시된) 레코드는 아무 칸도 건드리지
        않는다. 유효성 판정은 `environment_prior` 가 소유하므로 여기서 다시 만들지
        않고 물어보기만 한다 — 두 곳에서 판정하면 두 답이 생긴다.
        """
        if not record.is_valid_at(now):
            return ()
        return self.ingest(MapObservation(
            observation_id=f"prior:{record.record_id}:{claim}",
            source_group=record.source,
            # 레코드 한 판이 하나의 원본이다 — 같은 선언에서 뽑은 두 값은 서로
            # 독립인 지지가 아니다.
            frame_ref=f"prior_record:{record.record_id}@{record.version}",
            observed_at=record.updated_at,
            observation_kind=observation_kind,
            claim=claim, footprint=footprint, frame_id=self.frame_id,
            strength=strength, pose_quality=POSE_UNKNOWN,
            prior_record_id=record.record_id,
        ))

    def _reject(self, observation: MapObservation, reason: str, detail: str = "") -> None:
        self._rejected.append(RejectedMapObservation(
            observation.observation_id, observation.observation_kind, reason, detail))

    # -- 읽기 -------------------------------------------------------------

    def rejected(self) -> tuple[RejectedMapObservation, ...]:
        """쓰지 못한 관측 전부. 비어 있지 않아도 지도는 성립한다."""
        return tuple(self._rejected)

    def observed_kinds(self) -> tuple[str, ...]:
        kinds = {obs.observation_kind for rows in self._cells.values() for obs in rows}
        return tuple(sorted(kinds))

    def unobserved_kinds(self) -> tuple[str, ...]:
        """등록됐으나 관측이 없는 종류. **없음은 반대 근거가 아니다**(규칙 8)."""
        observed = set(self.observed_kinds())
        return tuple(k for k in self.kinds.kinds() if k not in observed)

    def cell(self, cell: tuple[int, int], *, now: float | None = None,
             available_sources: set[str] | None = None) -> CellBelief:
        """칸 하나를 지금 시점으로 다시 융합해 낸다.

        관측이 하나도 없는 칸도 **객체를 돌려준다** — None 을 돌려주면 호출자가
        "없음" 을 "비었음" 으로 읽을 자리가 생긴다(규칙 1).
        """
        rows = self._cells.get(cell, ())
        if available_sources is not None:
            rows = [obs for obs in rows if obs.source_group in available_sources]
        return self._fuse_cell(cell, tuple(rows), now)

    def state_of(self, cell: tuple[int, int], *, now: float | None = None) -> CellState:
        return self.cell(cell, now=now).state

    def state_at(self, x: float, y: float, *, now: float | None = None) -> CellState:
        """로컬 미터 점의 상태. 격자 인덱스를 호출자가 몰라도 되게 한다."""
        return self.state_of(self.cell_of(x, y), now=now)

    def known_cells(self) -> tuple[tuple[int, int], ...]:
        """근거가 하나라도 닿은 칸. 나머지는 모름이고 목록에 없다는 사실이 그 뜻이다."""
        return tuple(sorted(self._cells))

    def _fuse_cell(self, cell: tuple[int, int], rows: Sequence[MapObservation],
                   now: float | None) -> CellBelief:
        """받아들인 관측만으로 칸 하나를 정한다. 여기서 더 거절하지 않는다."""
        if not rows:
            return CellBelief(cell=cell, cell_size_m=self.cell_size_m,
                              frame_id=self.frame_id, mass=BeliefMass.ignorant())

        # 결정적 순서. 같은 입력에 같은 답을 내야 leave-one-out 이 비교 가능하다.
        ordered = sorted(rows, key=lambda o: (o.observed_at, o.observation_id))
        representatives, dependent = _representatives(ordered)

        mass = BeliefMass.ignorant()
        contributions: list[CellContribution] = []
        observed_frames: set[str] = set()
        prior_count = 0
        source_groups: set[str] = set()
        last_observed: float | None = None
        tiers: list[str] = []
        pose_ranks: list[tuple[int, str]] = []
        prior_claims: list[tuple[float, str]] = []

        for obs in representatives:
            spec = self.kinds.spec(obs.observation_kind)
            if spec is None:          # 정상 경로에서는 ingest 가 이미 걸렀다.
                continue
            pose_factor = (self._discount_for(obs.pose_quality)
                           if spec.through_pose else 1.0)
            pose_discounted = obs.strength * pose_factor
            age_factor = _age_discount(obs.observed_at, now, spec.half_life_s)
            applied = pose_discounted * age_factor
            mass = mass.fuse(BeliefMass.from_claim(obs.claim, applied))
            contributions.append(CellContribution(
                observation_id=obs.observation_id,
                observation_kind=obs.observation_kind, tier=spec.tier,
                source_group=obs.source_group, frame_ref=obs.frame_ref,
                claim=obs.claim, observed_at=obs.observed_at,
                declared_strength=obs.strength, pose_discounted=pose_discounted,
                applied_strength=applied, pose_quality=obs.pose_quality,
                role=ROLE_INDEPENDENT, prior_record_id=obs.prior_record_id))
            source_groups.add(obs.source_group)
            tiers.append(spec.tier)
            if spec.through_pose:
                pose_ranks.append((POSE_QUALITIES.index(obs.pose_quality)
                                   if obs.pose_quality in POSE_QUALITIES
                                   else len(POSE_QUALITIES), obs.pose_quality))
            if spec.is_prior:
                prior_count += 1
                prior_claims.append((obs.observed_at, obs.claim))
            else:
                # 관측 격만 지지로 센다. 독립성의 단위는 생산자가 아니라 원본 관측이다 —
                # 같은 프레임을 두 provider 가 읽어도 그 프레임이 두 번 관측된 것은 아니다.
                observed_frames.add(obs.frame_ref)
                last_observed = (obs.observed_at if last_observed is None
                                 else max(last_observed, obs.observed_at))

        for obs in dependent:
            spec = self.kinds.spec(obs.observation_kind)
            tier = spec.tier if spec else TIER_ESTIMATED
            contributions.append(CellContribution(
                observation_id=obs.observation_id,
                observation_kind=obs.observation_kind, tier=tier,
                source_group=obs.source_group, frame_ref=obs.frame_ref,
                claim=obs.claim, observed_at=obs.observed_at,
                declared_strength=obs.strength, pose_discounted=0.0,
                applied_strength=0.0, pose_quality=obs.pose_quality,
                role=ROLE_DEPENDENT, prior_record_id=obs.prior_record_id))
            source_groups.add(obs.source_group)

        best_tier = (min(tiers, key=lambda t: _TIER_RANK.get(t, 9)) if tiers else None)
        weakest_pose = max(pose_ranks)[1] if pose_ranks else None
        prior_claim = (sorted(prior_claims)[-1][1]
                       if prior_claims and not observed_frames else None)

        return CellBelief(
            cell=cell, cell_size_m=self.cell_size_m, frame_id=self.frame_id,
            mass=mass, observed_support=len(observed_frames),
            prior_support=prior_count, last_observed_at=last_observed,
            source_groups=tuple(sorted(source_groups)),
            contributions=tuple(contributions), prior_claim=prior_claim,
            best_tier=best_tier, weakest_pose_quality=weakest_pose,
            accepted=tuple(ordered),
        )

    def _discount_for(self, pose_quality: str) -> float:
        """등록되지 않은 자세 품질은 **가장 보수적으로** 다룬다.

        기본값을 1.0 으로 두면 오타 하나가 검증된 보정과 같은 확신을 만든다.
        """
        return self.pose_discount.get(pose_quality, DEFAULT_POSE_DISCOUNT[POSE_UNKNOWN])

    # -- 한 출처를 빼면 ---------------------------------------------------

    def without(self, name: str, *, unit: str = "source_group") -> "TwinMapLayer":
        """그 출처를 뺀 지도를 **다시 만들어서** 낸다.

        지우고 되돌리는 것이 아니다 — 원래 무엇이 들어왔는지가 남아야 같은 질문을
        여러 출처에 반복할 수 있다(규칙 3).
        """
        reduced = TwinMapLayer(
            cell_size_m=self.cell_size_m, frame_id=self.frame_id,
            kinds=self.kinds.copy(), anchors=dict(self.anchors), datum=self.datum,
            pose_discount=dict(self.pose_discount), stale_after=self.stale_after)
        for cell, rows in self._cells.items():
            keep = [obs for obs in rows if _unit_key(obs, unit) != name]
            if keep:
                reduced._cells[cell] = list(keep)
        reduced._seen = {obs.observation_id
                         for rows in reduced._cells.values() for obs in rows}
        return reduced

    def leave_one_out(self, cell: tuple[int, int], *, now: float | None = None,
                      unit: str = "source_group") -> tuple[CellLeaveOneOut, ...]:
        """출처별로 "빼면 이 칸이 무엇이 되는가" 를 전부 낸다."""
        current = self.cell(cell, now=now)
        names: list[str] = []
        for obs in current.accepted:
            key = _unit_key(obs, unit)
            if key not in names:
                names.append(key)
        out: list[CellLeaveOneOut] = []
        for name in sorted(names):
            reduced = self.without(name, unit=unit).cell(cell, now=now)
            out.append(CellLeaveOneOut(
                removed=name, unit=unit, state=reduced.state, mass=reduced.mass,
                occupancy_influence=current.mass.occupied - reduced.mass.occupied,
                state_flipped=reduced.state is not current.state))
        return tuple(out)

    def reduced_view(self, available_sources: set[str], *,
                     now: float | None = None) -> tuple[CellBelief, ...]:
        """쓸 수 있는 출처만으로 지도가 아직 무엇을 받치는가.

        혼자 받치던 출처가 사라진 칸은 지워지지 않고 **모름으로 돌아간다** — 지우면
        출처가 복구돼도 칸은 처음부터 다시 관측해야 하고, 비었다고 적으면 규칙 1 을
        깬다(AI-C-05).
        """
        return tuple(self.cell(cell, now=now, available_sources=available_sources)
                     for cell in self.known_cells())

    # -- 영역 질의 --------------------------------------------------------

    def summarize(self, region: tuple[float, float, float, float], *,
                  now: float | None = None,
                  stale_after: float | None = None) -> RegionSummary:
        """영역 하나를 칸 단위 사실로 요약한다. 관측되지 않은 칸을 세어 **내놓는다**."""
        horizon = self.stale_after if stale_after is None else stale_after
        cells = self.cells_in(region)
        counts = {s: 0 for s in CellState}
        never = stale = 0
        times: list[float] = []
        for cell in cells:
            belief = self.cell(cell, now=now)
            counts[belief.state] += 1
            if belief.never_observed:
                never += 1
            elif now is not None and belief.is_stale(now, horizon):
                stale += 1
            if belief.last_observed_at is not None:
                times.append(belief.last_observed_at)
        return RegionSummary(
            frame_id=self.frame_id, region=region, total_cells=len(cells),
            unknown_cells=counts[CellState.UNKNOWN],
            free_cells=counts[CellState.FREE],
            occupied_cells=counts[CellState.OCCUPIED],
            disputed_cells=counts[CellState.DISPUTED],
            never_observed_cells=never, stale_cells=stale,
            oldest_observation_at=min(times) if times else None,
            newest_observation_at=max(times) if times else None,
        )

    # -- 프레임 -----------------------------------------------------------

    def position_in(self, local: tuple[float, float] | None, frame: str, *,
                    local_accuracy_m: float | None = None) -> FramedPosition:
        """로컬 자리를 호출자가 요구한 프레임으로 낸다. **못 하면 거절한다.**

        전역 값의 정확도는 로컬 측정과 datum 을 직교 합성한 값이고, 따라서 **datum
        보다 좋을 수 없다**. 어림 datum 을 통과한 전역 좌표가 측량 datum 을 통과한
        것과 같은 품질로 보이면, 받는 쪽은 그 둘을 같은 값으로 쓴다 — 그것이 품질을
        잃은 값이 다른 값인 이유다(규칙 4).
        """
        if local is None:
            return FramedPosition(None, frame, refused_because=REFUSE_NO_LOCAL_VALUE)
        if frame in (FRAME_ZONE, self.frame_id):
            # 로컬 정확도를 모르면 그 사실을 적는다. None 으로 비워 두면 "제한이 없다"
            # 와 "재지 않았다" 가 같은 빈칸이 된다(규칙 4 와 같은 축).
            return FramedPosition(local, FRAME_ZONE, accuracy_m=local_accuracy_m,
                                  derived_from=local, derived_frame=self.frame_id,
                                  limited_by=(LIMITED_BY_LOCAL if local_accuracy_m is not None
                                              else LIMITED_BY_UNKNOWN))
        if frame != FRAME_GLOBAL:
            return FramedPosition(None, frame, refused_because=REFUSE_UNKNOWN_FRAME)
        if self.datum is None:
            # datum 없는 현장은 정상 상태다. 전역 층만 축소되고 로컬은 그대로다(AI-C-05).
            return FramedPosition(None, FRAME_GLOBAL, derived_from=local,
                                  derived_frame=self.frame_id,
                                  refused_because=REFUSE_NO_DATUM)
        if not self.datum.quantified:
            # 정확도를 모르는 변환으로 전역 값을 내면 그 값이 얼마나 틀렸는지 말할 수
            # 없다. 품질을 말할 수 없는 전역 좌표는 로컬 측정처럼 쓰이게 된다.
            return FramedPosition(None, FRAME_GLOBAL, derived_from=local,
                                  derived_frame=self.frame_id,
                                  datum_id=self.datum.datum_id,
                                  refused_because=REFUSE_DATUM_ACCURACY_UNKNOWN)
        datum_accuracy = self.datum.accuracy_m
        if local_accuracy_m is None:
            # 로컬 정확도가 모름이면 합성도 모름이다 — 기본값을 꽂으면 모르는 값이
            # 아는 값을 이긴다(spatial_evidence 규칙 2 와 같은 축).
            accuracy: float | None = None
            limited = LIMITED_BY_UNKNOWN
        else:
            accuracy = math.sqrt(local_accuracy_m ** 2 + datum_accuracy ** 2)
            limited = (LIMITED_BY_DATUM if datum_accuracy >= local_accuracy_m
                       else LIMITED_BY_LOCAL)
        return FramedPosition(
            self.datum.to_global(local), FRAME_GLOBAL, accuracy_m=accuracy,
            datum_id=self.datum.datum_id, derived_from=local,
            derived_frame=self.frame_id, limited_by=limited)

    def cell_position(self, cell: tuple[int, int], *, frame: str = FRAME_ZONE,
                      now: float | None = None) -> FramedPosition:
        """칸 중심을 요구된 프레임으로. 칸의 자세 품질이 로컬 정확도 하한을 정한다.

        검증되지 않은 자세를 통과한 칸은 검증된 칸과 같은 정확도를 주장할 수 없다 —
        규칙 6 이 전역 층까지 이어지는 자리다.
        """
        belief = self.cell(cell, now=now)
        local_accuracy = _cell_accuracy(self.cell_size_m, belief.weakest_pose_quality,
                                        self._discount_for)
        return self.position_in(self.cell_centre(cell), frame,
                                local_accuracy_m=local_accuracy)

    # -- 생존 -------------------------------------------------------------

    def element(self, element_id: str, *, born_at: float = 0.0,
                half_life_s: float = DEFAULT_SURVIVAL_HALF_LIFE) -> ElementPersistence:
        """요소의 생존 필터를 꺼낸다. 없으면 만든다."""
        existing = self._persistence.get(element_id)
        if existing is None:
            existing = ElementPersistence(element_id=element_id, born_at=born_at,
                                          half_life_s=half_life_s)
            self._persistence[element_id] = existing
        return existing

    def persistence(self, element_id: str, now: float) -> PersistenceReport:
        """요소가 아직 거기 있다고 믿는 정도. 등록되지 않은 요소는 사전확률만 낸다."""
        return self.element(element_id).belief(now)

    # -- 전체 읽기 --------------------------------------------------------

    def as_dict(self, region: tuple[float, float, float, float] | None = None, *,
                now: float | None = None) -> dict:
        """화면·백엔드가 읽는 형태. 최상위 이름은 전부 공통 데이터 사전에 등재돼 있다."""
        cells = self.cells_in(region) if region is not None else self.known_cells()
        body = {
            dd.COORDINATE_FRAME: FRAME_ZONE,
            dd.CELL_SIZE_M: self.cell_size_m,
            dd.MAP_AUTHORITY: MAP_AUTHORITY_SITE_LOCAL,
            dd.MAP_CELLS: [self.cell(cell, now=now).as_dict() for cell in cells],
            dd.UNOBSERVED_EVIDENCE_KINDS: list(self.unobserved_kinds()),
            dd.REJECTED_OBSERVATIONS: [row.as_dict() for row in self._rejected],
            dd.DATUM_ID: None if self.datum is None else self.datum.datum_id,
        }
        if region is not None:
            body[dd.MAP_REGION_ID] = str(region)
        return body


# ---------------------------------------------------------------------------
# 보조 — 독립성, 노후화, 투영
# ---------------------------------------------------------------------------

def _unit_key(obs: MapObservation, unit: str) -> str:
    if unit == "source_group":
        return obs.source_group
    if unit == "kind":
        return obs.observation_kind
    if unit == "frame_ref":
        return obs.frame_ref
    raise ValueError(f"unknown leave-one-out unit {unit!r}; "
                     "expected 'source_group', 'kind' or 'frame_ref'")


def _representatives(
    observations: Sequence[MapObservation],
) -> tuple[list[MapObservation], list[MapObservation]]:
    """원본 관측별로 대표 하나를 고른다.

    같은 `frame_ref` 에서 나온 값들은 서로를 확증하지 못하므로 그 안에서 가장 센
    주장 하나만 융합에 들어가고 나머지는 의존 기여로 남는다. 한 프레임을 두 번 읽어
    점유 질량을 두 배로 만드는 길을 구조적으로 막는 자리다(AI-S-06: 중복·의존 근거를
    구분할 여지를 유지해야 한다). Dempster 결합은 역분산 가중과 마찬가지로 중복
    계산에 대해 안전하지 않다 — 같은 관측을 두 번 넣으면 질량이 그만큼 커진다.
    """
    groups: dict[str, list[MapObservation]] = {}
    for obs in observations:
        groups.setdefault(obs.frame_ref, []).append(obs)

    chosen: list[MapObservation] = []
    dependent: list[MapObservation] = []
    for _, members in sorted(groups.items()):
        # 가장 센 주장이 대표. 동점은 id 로 가른다 — 같은 입력에 같은 답을 내야
        # leave-one-out 이 비교 가능하다.
        ranked = sorted(members, key=lambda o: (-o.strength, o.observation_id))
        chosen.append(ranked[0])
        dependent.extend(ranked[1:])
    return chosen, dependent


def _age_discount(observed_at: float, now: float | None,
                  half_life_s: float | None) -> float:
    """나이에 따른 Dempster 할인 계수.

    `now` 가 없으면 노후화를 적용하지 않는다 — 시계를 주지 않은 호출자에게 시간을
    지어내 주면 그 시간이 지도를 지배한다. `half_life_s` 가 None 이면 그 종류는
    최신성 주장을 하지 않는다(도면의 벽).

    미래 시각의 관측(시계 꼬임)은 할인하지 않고 그대로 둔다. 음의 나이로 질량을
    **키우면** 시계 오차가 확신으로 바뀐다.
    """
    if now is None or half_life_s is None:
        return 1.0
    age = now - observed_at
    if age <= 0.0:
        return 1.0
    return math.exp(-age * math.log(2.0) / half_life_s)


def _cell_accuracy(cell_size_m: float, weakest_pose: str | None,
                   discount_for) -> float | None:
    """칸 중심의 로컬 정확도 하한.

    칸 크기 자체가 양자화 오차를 주고, 그 위에 자세 품질이 곱해진다. 자세 품질을
    모르면(관측이 자세를 통과하지 않았거나 근거가 없으면) **모름으로 남긴다** —
    숫자를 지어내면 그 숫자가 전역 합성을 지배한다.
    """
    if weakest_pose is None:
        return None
    factor = discount_for(weakest_pose)
    if factor <= 0.0:
        return None
    # 할인이 작을수록 자세를 못 믿는다는 뜻이므로 정확도 수치는 커진다.
    return (cell_size_m / 2.0) / factor


# ---------------------------------------------------------------------------
# 입력 보조 — 탐지와 프로파일에서 관측 만들기
# ---------------------------------------------------------------------------

def observation_from_point(
    observation_id: str, *, source_group: str, frame_ref: str, observed_at: float,
    position: tuple[float, float], frame_id: str,
    observation_kind: str = "object_detection", claim: str = CLAIM_OCCUPIED,
    position_accuracy_m: float | None = None, strength: float = 0.6,
    pose_quality: str = POSE_DECLARED, anchor_id: str | None = None,
    detail: Mapping[str, object] | None = None,
) -> MapObservation:
    """미터 평면의 점 1개를 지도 관측으로.

    `position_accuracy_m` 가 footprint 를 키운다 — 자리가 불확실한 관측은 **더 많은
    칸을 약하게** 건드려야 한다. 한 칸만 세게 건드리면 자리의 불확실성이 확신으로
    보이고, 그것이 선언 자세로 투영한 탐지가 내는 전형적인 거짓말이다. 정확도를
    모르면 칸 하나 크기로 둔다(지어내지 않고 최소로).
    """
    radius = (position_accuracy_m if position_accuracy_m is not None
              else 0.0)
    x, y = position
    return MapObservation(
        observation_id=observation_id, source_group=source_group,
        frame_ref=frame_ref, observed_at=observed_at,
        observation_kind=observation_kind, claim=claim,
        footprint=(x - radius, y - radius, x + radius, y + radius),
        frame_id=frame_id, strength=strength, pose_quality=pose_quality,
        anchor_id=anchor_id, detail=dict(detail or {}),
    )


def declared_pose_quality(infrastructure_item: Mapping) -> str:
    """프로파일에 적힌 설치물의 자세 품질을 **선언으로부터** 읽는다.

    검증 시점이 적힌 보정 프로파일이 있으면 `validated`, 아니면 `declared`. 벤더
    이름이나 장치 종류로 갈라지지 않는다(규칙 7) — 판정 재료는 "누가 확인했다고
    적혀 있는가" 뿐이다.
    """
    calibration = infrastructure_item.get("calibration") or {}
    if calibration.get("verified_at"):
        return POSE_VALIDATED
    if calibration.get("profile_version"):
        # 프로파일 판은 있지만 확인 기록이 없다. 자기 추정과 같은 격으로 둔다.
        return POSE_ESTIMATED
    return POSE_DECLARED


def prior_observations_from_domain_profile(
    profile: Mapping, zone_id: str, *, frame_id: str | None = None,
    source_group: str = "zone_profile", footprint_m: float = 0.5,
    strength: float = 0.4,
) -> tuple[MapObservation, ...]:
    """프로파일에 **선언된** 설치물 자리를 사전정보 격 관측으로 옮긴다(AI-S-08).

    전부 `declared_obstacle` 이므로 이것만으로는 어떤 칸도 주장하지 못한다 — 도면은
    탐색을 거들 뿐 확정 근거가 아니다. 프로파일 한 판이 하나의 원본(`frame_ref`)인
    이유는 같은 파일에서 뽑은 두 줄이 서로 독립인 지지가 아니기 때문이다.
    """
    for domain in profile.get("domains", ()):
        for zone in domain.get("zones", ()):
            if zone.get("zone_id") != zone_id:
                continue
            frame = frame_id or "zone"
            origin = f"zone_profile:{domain.get('domain_id', '')}"
            rows: list[MapObservation] = []
            for item in zone.get("infrastructure", ()):
                at = item.get("at")
                if not at:
                    continue
                x, y = float(at["x"]), float(at["y"])
                rows.append(MapObservation(
                    observation_id=f"declared:{zone_id}:{item.get('id', '')}",
                    source_group=source_group, frame_ref=origin, observed_at=0.0,
                    observation_kind="declared_obstacle", claim=CLAIM_OCCUPIED,
                    footprint=(x - footprint_m, y - footprint_m,
                               x + footprint_m, y + footprint_m),
                    frame_id=frame, strength=strength,
                    pose_quality=declared_pose_quality(item),
                    detail={"kind": item.get("kind", "declared_node")},
                ))
            return tuple(rows)
    return ()


def gather_observations(
    sources: Mapping[str, object],
) -> tuple[tuple[MapObservation, ...], tuple[str, ...]]:
    """등록된 출처들을 돌며 관측을 모으고, 못 쓴 출처의 이름을 따로 낸다.

    provider 가 없거나(None) 호출이 실패하면 **아무 값도 내지 않고** 이름만 남는다 —
    선택 출처 하나의 장애가 지도를 멈추게 하지도, 비우게 하지도 않는다(규칙 8,
    AI-C-05). 빈 결과도 반대 근거가 아니다.
    """
    collected: list[MapObservation] = []
    unavailable: list[str] = []
    for name, source in sorted(sources.items()):
        if source is None:
            unavailable.append(name)
            continue
        try:
            rows = list(source() or ())            # type: ignore[operator]
        except Exception:                          # noqa: BLE001 - provider 장애 격리
            unavailable.append(name)
            continue
        collected.extend(rows)
    return tuple(collected), tuple(unavailable)


def datum_from_profile(profile: Mapping, domain_id: str, *,
                       local_frame: str = "zone") -> SiteDatum | None:
    """도메인 프로파일에서 datum 을 읽는다. 없으면 None 이고 그것은 정상이다.

    주소만 적힌 프로파일에서 datum 을 **만들어 내지 않는다.** 주소는 변환이 아니고
    정확도도 없다 — 거기서 전역 원점을 추측하면 그 추측이 측량값과 같은 칸에 앉는다
    (규칙 4). datum 은 배포가 명시적으로 선언해야 생긴다.
    """
    for domain in profile.get("domains", ()):
        if domain.get("domain_id") != domain_id:
            continue
        block = domain.get("datum")
        if not block:
            return None
        offset = block.get("offset") or {}
        return SiteDatum(
            datum_id=block.get("datum_id", f"datum:{domain_id}"),
            local_frame=block.get("local_frame", local_frame),
            global_frame=block.get("global_frame", FRAME_GLOBAL),
            offset=(float(offset.get("x", 0.0)), float(offset.get("y", 0.0))),
            rotation_deg=float(block.get("rotation_deg", 0.0)),
            tier=block.get("tier", TIER_ESTIMATED),
            accuracy_m=block.get("accuracy_m"),
            source=block.get("source", ""),
            established_at=float(block.get("established_at", 0.0)),
            note=block.get("note", ""),
        )
    return None
