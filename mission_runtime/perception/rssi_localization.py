"""카메라가 못 보는 자리에서 "어느 구역에 있는가" 를 무선 신호로 답한다.

implements: AI-N-03, AI-S-02, AI-S-03, AI-C-02, AI-E-04
tests: tests/test_rssi_localization.py

## 문제

영상은 보이는 곳만 말한다. 복도 모퉁이를 돌거나 방에 들어가면 그 로봇은 화면에서
사라지는데, 그렇다고 사라진 것은 아니다. 무선 신호 세기는 **보이지 않아도** 들어온다 —
대신 그것이 말해 주는 자리는 훨씬 거칠다.

이 계층이 하는 일은 그 거친 사실을 거친 그대로 내는 것이다. `edge/self_localization.py`
가 2026-09-17 에 적어 둔 결론("RSSI 삼변측량은 실내 0.6~6m 오차라 문 앞 80cm 정지에는
못 미친다 — 주 수단이 아니라 랜드마크가 하나도 안 보일 때의 보조")을 뒤집지 않는다.
여기서 노리는 답은 미터가 아니라 **구역**이다.

## 왜 점이 아니라 영역인가

log-distance 식은 거리의 **평균**만 말한다. 실제 RSSI 는 다중경로·차폐·사람 몸으로
같은 자리에서도 수 dB 흔들리고, dB 의 덧셈 오차는 거리에서 **곱셈 오차**가 된다. 이
현장의 계수(n=3.5)와 미실측 σ=6dB 조합에서 1σ 구간은 ±48% 다 — 핸드오버 문턱
(-75dBm, 25.1m)에서 1σ 구간이 16.9~37.3m 라는 뜻이다.

그래서 이 모듈은 좌표 한 쌍을 돌려주지 않는다. 좌표 한 쌍을 돌려주면 화면은 그것을
측량값으로 읽고, 그 위에 핀을 꽂고, 운영자는 로봇이 거기 있다고 믿는다. 산출물은
격자 위의 **가능 영역**과 구역별 확률 질량(`zone_posterior`)이며, 가장 그럴듯한 칸이
있어도 그 칸을 "위치" 라고 부르지 않는다.

## AP 가 한 대라는 사실을 숨기지 않는다

`profiles/domains.json` 의 이 현장에는 AP 가 `ap-n4-5f` 하나뿐이다. 한 대로는
**거리만** 나오고 방향이 나오지 않는다 — 가능 영역은 AP 를 중심으로 한 고리(annulus)
이고, 그 고리를 구역과 교차시킨 것이 답의 전부다. 그 사실은 `anchor_count` 와
`geometry`(`RANGE_ONLY` / `TWO_LOBED` / `BOUNDED`)로 결과에 **적혀 나간다**.

덧붙여 그 한 대의 자리는 실측이 아니다. 프로파일의 `site.unverified_fields` 에
`ap_placement` 가 들어 있고, 선언문이 "복도 교차점에 두면 먼 모서리가 바닥 반경
밖이라 지금은 덮이는 자리에 선언해 두었다" 고 적는다. 즉 **지금 덮인다는 결론 자체가
편의로 고른 자리 덕분**이다. `CoverageAssessment` 는 덮임 여부와 그 자리가 미실측이라는
사실을 같이 들고 나가고, 숫자는 전부 데이터에서 계산한다(모서리 거리도, 바닥 반경도
코드에 없다).

## 미측정 ≠ 0 ≠ 범위 밖

세 상태를 다른 칸에 둔다. `RangeState.UNMEASURED` 는 거리가 `None` 이고 0 이 아니다.
`RangeState.BEYOND_FLOOR` 는 수신 바닥 아래라 값 자체를 못 믿는 상태이므로 점 추정을
내지 않고 **하한만**(`lower_bound_m`) 낸다 — 그리고 그 측정은 격자에서 중도절단
(censored) 가능도 `P(level <= floor | cell)` 로 들어간다. 지도의 어느 칸과도
맞지 않으면 억지로 맞추지 않고 `BeliefState.OUT_OF_MAP` 으로 거절한다.

## 좌표계는 끝까지 붙어 다닌다 (AI-C-02)

모든 자리는 현장 로컬 프레임(`site:<domain_id>`)의 값이고 `coordinate_frame` 은
`ZONE` 이다. 이 현장의 datum 은 `verified: false` 이므로 전역 값은 **만들지 않는다**.
프레임이 다른 입력은 섞지 않고 `REASON_FRAME_MISMATCH` 로 거절한다 — 로컬과 전역은
교환 가능하지 않다.

## device_identity 의 `radio_range` 단서를 실제로 채운다

`perception/device_identity.py` 는 `radio_range` 를 "개체를 가릴 수 있는 단서 8종"
가운데 하나로 이미 등재해 두었지만 그 자리를 채우는 경로가 없었다. 이 모듈의
`radio_range_cues()` 가 그 경로다. 규칙은 그쪽 것을 그대로 쓴다 — 허용 오차는 이
모듈이 임의로 정하지 않고 **그 측정의 1σ 거리 반폭**이고, 그래서 흔들림이 크면 두
후보가 모두 높은 세기를 받아 그쪽의 `discriminating_margin` 규칙이 `AMBIGUOUS` 로
잡는다. 못 가리면 1위를 고르지 않는다는 규칙이 숫자를 손대지 않고 그대로 성립한다.

측정이 없을 때는 **세기 0 의 단서를 만들지 않고 단서를 아예 내지 않는다**. 0 을 내면
그쪽의 `_requests()` 가 "무선 측정은 이미 있다" 고 보고 `enable_radio_ranging` 요청을
빼버린다 — 없는 것을 있다고 세는 순간 해법 요청이 사라진다(AI-S-05).

## 이 모듈이 소유하지 않는 것

dBm 파싱과 경로손실 계수 해석은 `providers/rssi_link_quality.py` 의 것이다(AI-N-03:
무선 규격 이름은 provider 안에서만 산다). 최종 "이 track 은 이 장치다" 라는 권위 있는
결속과 장치 최종 가용성, 물리 명령 발급은 백엔드·하드웨어의 몫이다(AI-C-19). 실제
무선 전환도 네트워크 provider 가 한다 — 이 모듈은 자리에 대한 **믿음**만 낸다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping, Sequence

from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.contracts.capability import CapabilityRequirement
from mission_runtime.perception.device_identity import (
    IdentityCue,
    expected_range_m,
    radio_range_cue,
)
from mission_runtime.perception.spatial_evidence import is_local_frame
from mission_runtime.providers.rssi_link_quality import (
    LogDistancePathLoss,
    RadioModelError,
    RssiReading,
)

#: 이 계층의 의존. **required 가 비어 있다** — AP 선언도 측정도 없는 배치에서 이 모듈은
#: `UNMEASURED` 를 내며 정상 동작하고, import 를 막지 않는다(AI-C-05).
REQUIREMENT = CapabilityRequirement(
    required=(),
    optional=("radio.ranging", "radio.link_quality", "reference.zone_profile"),
)

#: 산출된 자리의 좌표계. 이 현장 datum 은 미검증이라 전역으로 올라가지 않는다(AI-C-02).
COORDINATE_FRAME = "ZONE"

#: `pose_source`(dd.POSE_SOURCE) 에 남길 방법 이름. 자유 문자열이다 —
#: `edge/self_localization.py` 가 BLE 비콘 쪽 이름을 예약해 둔 것과 같은 축이고,
#: 그쪽(랜드마크)과 이쪽(무선 범위)은 신뢰도가 전혀 다르므로 이름이 달라야 한다.
POSE_SOURCE_RADIO_RANGE = "radio_range_likelihood"

#: 프로파일이 AP 자리를 실측하지 않았음을 적는 `site.unverified_fields` 의 항목 이름.
AP_PLACEMENT_FIELD = "ap_placement"

#: 바닥(수신 한계) 문턱의 이름. 프로파일 `thresholds_dbm`·`radius_m` 의 키다.
FLOOR_THRESHOLD = "floor"


# --- 사유 어휘 ---------------------------------------------------------------
# ':' 앞이 토큰, 뒤가 데이터 — 저장소 공통 규약.

REASON_NO_MEASUREMENT = "no_radio_measurement"          # 측정 자체가 없다
REASON_NO_ANCHOR = "no_declared_access_point"           # 선언된 AP 가 없다
REASON_UNKNOWN_ANCHOR = "access_point_not_in_radio_map"  # + ":<ap_id>"
REASON_FRAME_MISMATCH = "frame_mismatch"                # + ":<frame>"
REASON_RANGE_ONLY = "single_anchor_range_only"          # + ":<ap_id>"
REASON_TWO_LOBED = "two_anchors_mirror_ambiguity"
REASON_BOUNDED = "anchors_bound_the_region"             # + ":<n>"
REASON_BEYOND_FLOOR = "level_at_or_below_receive_floor"  # + ":<dbm>"
REASON_OUT_OF_MAP = "no_cell_consistent_with_measurement"  # + ":<residual σ>"
REASON_EMPTY_MAP = "radio_map_has_no_zone_extent"

LOCALIZATION_REASONS: tuple[str, ...] = (
    REASON_NO_MEASUREMENT, REASON_NO_ANCHOR, REASON_UNKNOWN_ANCHOR,
    REASON_FRAME_MISMATCH, REASON_RANGE_ONLY, REASON_TWO_LOBED, REASON_BOUNDED,
    REASON_BEYOND_FLOOR, REASON_OUT_OF_MAP, REASON_EMPTY_MAP,
)

#: 모호할 때 낼 수 있는 해법 요청. 실행은 다른 파트가 한다(AI-C-19, AI-S-05).
#: 이름은 `device_identity`·`evidence_kinds` 가 쓰는 것을 그대로 쓴다 — 같은 뜻을 두
#: 어휘로 적으면 화면이 두 요청을 따로 띄운다.
REQUEST_ENABLE_RADIO_RANGING = "enable_radio_ranging"
REQUEST_MOTION_PROBE = "run_motion_probe"
#: 새 이름: AP 가 한 대뿐이라 방향이 안 나온다는 사실에 대한 요청.
REQUEST_ADD_ANCHOR = "declare_additional_access_point"
#: 새 이름: AP 자리가 실측이 아니라 덮임 결론이 그 자리에 매달려 있다.
REQUEST_SURVEY_AP_PLACEMENT = "survey_access_point_placement"


class RangeState(str, Enum):
    """한 AP 에 대한 거리 측정의 상태. **세 가지가 서로 다른 칸이다**."""

    #: 재지 못했다. `range_m` 은 `None` 이고 0 이 아니다.
    UNMEASURED = "UNMEASURED"
    #: 모델 적용 범위 안에서 쟀다.
    IN_RANGE = "IN_RANGE"
    #: 수신 바닥 아래 — 값을 못 믿으므로 하한만 낸다.
    BEYOND_FLOOR = "BEYOND_FLOOR"


class Geometry(str, Enum):
    """몇 대로 쟀는지가 **답의 모양**을 정한다. 숨기지 않고 이름으로 낸다."""

    #: 한 대 — 거리만. 가능 영역은 고리이고 방향은 없다.
    RANGE_ONLY = "RANGE_ONLY"
    #: 두 대 — 두 고리가 두 점에서 만나 좌우 거울상이 남는다.
    TWO_LOBED = "TWO_LOBED"
    #: 세 대 이상 — 영역이 닫힌다.
    BOUNDED = "BOUNDED"
    #: 쓸 측정이 없다.
    NONE = "NONE"


class BeliefState(str, Enum):
    UNMEASURED = "UNMEASURED"
    LOCATED = "LOCATED"
    #: 지도의 어느 칸과도 맞지 않는다. 억지로 맞춘 영역을 내지 않는다.
    OUT_OF_MAP = "OUT_OF_MAP"


# --- 무선 지도 ---------------------------------------------------------------


@dataclass(frozen=True)
class Anchor:
    """측정의 기준이 되는 AP 한 대. 자리는 **로컬** 좌표다(AI-C-02).

    `ap_id` 와 `band` 는 자유 문자열이고 벤더 enum 이 아니다 — 새 AP 는 선언을 더하는
    일이지 이 파일을 고치는 일이 아니다(절대 준수 원칙 #7).
    """

    ap_id: str
    at: tuple[float, float]
    frame_id: str
    model: LogDistancePathLoss
    zone_ids: tuple[str, ...] = ()
    #: 이 자리가 실측인가. 프로파일의 `site.unverified_fields` 에서 읽는다.
    placement_verified: bool = False
    #: 왜 그 자리인가(자유 문자열). 미실측이면 그 사유가 결과까지 따라간다.
    placement_basis: str = ""

    def distance_to(self, at: tuple[float, float]) -> float:
        return math.dist(self.at, at)

    @property
    def floor_radius_m(self) -> float | None:
        return self.model.radius_for_threshold(FLOOR_THRESHOLD)


@dataclass(frozen=True)
class ZoneExtent:
    """한 구역의 평면 범위. 격자를 깔 바탕이고 판정을 하지 않는다."""

    zone_id: str
    frame_id: str
    #: (x, y, w, h) — 프로파일 `zones[].rect` 그대로.
    rect: tuple[float, float, float, float]
    level_id: str | None = None
    verified: bool = False

    def contains(self, at: tuple[float, float]) -> bool:
        x, y, w, h = self.rect
        return x <= at[0] <= x + w and y <= at[1] <= y + h

    def corners(self) -> tuple[tuple[float, float], ...]:
        x, y, w, h = self.rect
        return ((x, y), (x + w, y), (x, y + h), (x + w, y + h))


@dataclass(frozen=True)
class CoverageAssessment:
    """한 구역이 그 AP 한 대로 **정말 덮이는가**. 숫자는 전부 데이터에서 나온다.

    `covered` 가 참이어도 `placement_verified` 가 거짓이면 그 결론은 **편의로 고른
    자리 덕분**이다. 둘을 한 칸에 합치면 그 사실이 사라진다.
    """

    zone_id: str
    ap_id: str
    floor_radius_m: float | None
    max_corner_distance_m: float
    uncovered_corners: tuple[tuple[float, float], ...]
    placement_verified: bool
    placement_basis: str = ""

    @property
    def covered(self) -> bool:
        """바닥 반경을 모르면 덮인다고 **주장하지 않는다**."""
        return self.floor_radius_m is not None and not self.uncovered_corners

    def as_dict(self) -> dict:
        return {
            dd.ZONE_ID: self.zone_id,
            "ap_id": self.ap_id,
            "covered": self.covered,
            "floor_radius_m": self.floor_radius_m,
            "max_corner_distance_m": round(self.max_corner_distance_m, 2),
            "uncovered_corners": [list(c) for c in self.uncovered_corners],
            "placement_verified": self.placement_verified,
            "placement_basis": self.placement_basis,
        }


@dataclass(frozen=True)
class RadioMap:
    """한 도메인의 AP·구역 기하. 전부 프로파일 데이터이며 코드 상수가 없다."""

    domain_id: str
    frame_id: str
    anchors: tuple[Anchor, ...] = ()
    zones: tuple[ZoneExtent, ...] = ()

    def anchor(self, ap_id: str) -> Anchor | None:
        return next((a for a in self.anchors if a.ap_id == ap_id), None)

    def zone(self, zone_id: str) -> ZoneExtent | None:
        return next((z for z in self.zones if z.zone_id == zone_id), None)

    def coverage(self) -> tuple[CoverageAssessment, ...]:
        """선언된 (구역, AP) 짝마다 덮임을 계산한다. 반경을 베껴 쓰지 않는다."""
        rows: list[CoverageAssessment] = []
        for anchor in self.anchors:
            floor = anchor.floor_radius_m
            for zone_id in anchor.zone_ids:
                zone = self.zone(zone_id)
                if zone is None:
                    continue
                distances = [anchor.distance_to(c) for c in zone.corners()]
                uncovered = (
                    () if floor is None
                    else tuple(c for c in zone.corners()
                               if anchor.distance_to(c) > floor)
                )
                rows.append(CoverageAssessment(
                    zone_id=zone_id, ap_id=anchor.ap_id, floor_radius_m=floor,
                    max_corner_distance_m=max(distances) if distances else 0.0,
                    uncovered_corners=uncovered,
                    placement_verified=anchor.placement_verified,
                    placement_basis=anchor.placement_basis))
        return tuple(rows)

    @classmethod
    def from_domain_profile(
        cls, profile: Mapping, *, domain_id: str | None = None,
        frame_id: str | None = None,
    ) -> "RadioMap":
        """`profiles/domains.json` 한 도메인을 무선 지도로 옮긴다.

        프레임 이름은 `spatial_evidence.observations_from_domain_profile` 과 **같은
        규약**(`site:<domain_id>`)을 쓴다 — 두 모듈이 같은 자리를 다른 프레임 이름으로
        부르면 그 둘은 섞을 수 없게 된다.

        모르는 RF 모델, 선언 없는 AP 는 조용히 기본값으로 떨어지지 않는다.
        """
        domains = tuple(profile.get("domains", ()))
        if not domains:
            raise RadioModelError("profile declares no domain")
        if domain_id is None:
            domain = domains[0]
        else:
            domain = next((d for d in domains if d.get("domain_id") == domain_id), None)
            if domain is None:
                raise RadioModelError(f"profile has no domain {domain_id!r}")
        did = str(domain.get("domain_id", ""))
        frame = frame_id or f"site:{did}"
        if not is_local_frame(frame):
            raise RadioModelError(f"{frame!r} is a global frame; local frames only")

        models = {kind: LogDistancePathLoss.from_profile(kind, raw)
                  for kind, raw in (domain.get("rf") or {}).items()}
        unverified = set((domain.get("site") or {}).get("unverified_fields") or ())
        placement_verified = AP_PLACEMENT_FIELD not in unverified
        placement_basis = (
            "" if placement_verified
            else f"declared_unverified:{AP_PLACEMENT_FIELD}")

        zones: list[ZoneExtent] = []
        by_ap: dict[str, dict] = {}
        for zone in domain.get("zones", ()):
            zone_id = str(zone.get("zone_id", ""))
            rect = zone.get("rect") or {}
            zones.append(ZoneExtent(
                zone_id=zone_id, frame_id=frame,
                rect=(float(rect.get("x", 0.0)), float(rect.get("y", 0.0)),
                      float(rect.get("w", 0.0)), float(rect.get("h", 0.0))),
                level_id=zone.get("level_id"),
                verified=bool(zone.get("verified", False))))
            wifi = zone.get("wifi")
            if not wifi or not wifi.get("at"):
                continue
            ap_id = str(wifi["ap_id"])
            kind = str(wifi.get("rf", ""))
            if kind not in models:
                raise RadioModelError(
                    f"zone {zone_id!r} points at rf {kind!r} which the domain "
                    f"does not declare")
            slot = by_ap.setdefault(ap_id, {
                "at": (float(wifi["at"]["x"]), float(wifi["at"]["y"])),
                "model": models[kind], "zone_ids": []})
            slot["zone_ids"].append(zone_id)

        anchors = tuple(
            Anchor(ap_id=ap_id, at=slot["at"], frame_id=frame, model=slot["model"],
                   zone_ids=tuple(slot["zone_ids"]),
                   placement_verified=placement_verified,
                   placement_basis=placement_basis)
            for ap_id, slot in sorted(by_ap.items()))
        return cls(domain_id=did, frame_id=frame, anchors=anchors,
                   zones=tuple(zones))


# --- 한 AP 에 대한 거리 ------------------------------------------------------


@dataclass(frozen=True)
class RangeEstimate:
    """한 측정 1건을 거리로 옮긴 결과. **점이 아니라 구간이다**.

    `range_m` 이 `None` 인 경우가 두 가지이고 둘은 `state` 로 구분된다 —
    `UNMEASURED`(재지 못했다)와 `BEYOND_FLOOR`(재봤지만 바닥 아래라 못 믿는다).
    어느 쪽도 0 이 아니다.
    """

    ap_id: str
    state: RangeState
    frame_id: str
    reason: str
    observed_at: float | None = None
    level_dbm: float | None = None
    range_m: float | None = None
    lower_m: float | None = None
    upper_m: float | None = None
    #: `BEYOND_FLOOR` 일 때의 하한(= 바닥 반경). 상한은 없다.
    lower_bound_m: float | None = None
    sigma_db: float | None = None
    sigma_basis: str = ""
    k_sigma: float = 1.0
    #: 원본 측정 참조. 독립성의 단위이고 `IdentityCue.frame_ref` 로 그대로 나간다.
    frame_ref: str = ""
    source: str = ""

    @property
    def measured(self) -> bool:
        return self.state is not RangeState.UNMEASURED

    @property
    def half_width_m(self) -> float | None:
        """1σ(정확히는 k σ) 거리 반폭. 단서의 허용 오차가 되는 값이다."""
        if self.lower_m is None or self.upper_m is None:
            return None
        return (self.upper_m - self.lower_m) / 2.0

    def as_dict(self) -> dict:
        return {
            "ap_id": self.ap_id,
            "state": self.state.value,
            dd.COORDINATE_FRAME: COORDINATE_FRAME,
            "frame_id": self.frame_id,
            dd.OBSERVED_AT: self.observed_at,
            "level_dbm": self.level_dbm,
            "range_m": None if self.range_m is None else round(self.range_m, 2),
            "lower_m": None if self.lower_m is None else round(self.lower_m, 2),
            "upper_m": None if self.upper_m is None else round(self.upper_m, 2),
            "lower_bound_m": (None if self.lower_bound_m is None
                              else round(self.lower_bound_m, 2)),
            "shadowing_sigma_db": self.sigma_db,
            "shadowing_basis": self.sigma_basis,
            "k_sigma": self.k_sigma,
            dd.FRAME_REF: self.frame_ref,
            "source": self.source,
            "reason": self.reason,
        }


# --- 가능 영역 ---------------------------------------------------------------


@dataclass(frozen=True)
class Region:
    """격자 위의 가능 영역. **여기에 핀을 꽂을 점은 없다**.

    `cells` 는 누적 질량이 `mass` 에 닿을 때까지 모은 칸들(신뢰 영역)이고,
    `peak_at` 은 가장 그럴듯한 칸이지만 "위치" 가 아니다 — 그 이름을 쓰지 않는 이유는
    화면이 그것을 측량값으로 읽기 때문이다. 영역의 크기(`area_m2`·`bbox`)가 그 점을
    믿어도 되는 정도를 말한다.
    """

    #: (x, y, 질량) 삼짝. 질량은 정규화돼 있고 합이 `mass` 다.
    cells: tuple[tuple[float, float, float], ...]
    cell_size_m: float
    #: 이 영역이 담은 확률 질량(0..1).
    mass: float
    bbox: tuple[float, float, float, float]
    peak_at: tuple[float, float]
    #: 질량 가중 중심. 고리 모양에서는 **영역 안에 있지도 않다** — 그래서 점으로 쓰면
    #: 안 된다는 증거로 함께 낸다.
    centroid_at: tuple[float, float]
    #: 중심에서의 질량 가중 표준거리(m). 영역이 얼마나 퍼졌는가.
    spread_m: float
    centroid_inside: bool

    @property
    def area_m2(self) -> float:
        return len(self.cells) * self.cell_size_m * self.cell_size_m

    def as_dict(self) -> dict:
        return {
            "cell_size_m": self.cell_size_m,
            "cell_count": len(self.cells),
            "area_m2": round(self.area_m2, 2),
            "mass": round(self.mass, 4),
            "bbox": [round(v, 2) for v in self.bbox],
            "peak_at": [round(v, 2) for v in self.peak_at],
            "centroid_at": [round(v, 2) for v in self.centroid_at],
            "centroid_inside": self.centroid_inside,
            "spread_m": round(self.spread_m, 2),
        }


@dataclass(frozen=True)
class RssiPositionBelief:
    """무선 신호로 본 자리에 대한 **믿음**. 좌표 한 쌍이 아니다.

    `zone_posterior` 가 이 계층의 실제 산출물이다 — "어느 구역에 있는가" 에 숫자로
    답하고, 그 답이 쓸모 없을 때(한 AP 가 구역 하나를 통째로 덮을 때)는 질량이 그
    구역에 1.0 으로 몰려 **아무 것도 가르지 못한다는 사실**이 그대로 보인다.
    """

    state: BeliefState
    reason: str
    frame_id: str
    geometry: Geometry = Geometry.NONE
    ranges: tuple[RangeEstimate, ...] = ()
    region: Region | None = None
    zone_posterior: Mapping[str, float] = field(default_factory=dict)
    coverage: tuple[CoverageAssessment, ...] = ()
    resolution_requests: tuple[str, ...] = ()
    observed_at: float | None = None
    #: 가장 잘 맞는 칸에서도 남은 잔차(σ). 작을수록 측정이 지도와 맞는다. 영역을
    #: 냈다는 것과 **잘 맞는다는 것은 다른 축이다** — 겨우 맞은 영역도 영역이다.
    fit_residual_sigma: float | None = None

    @property
    def anchor_count(self) -> int:
        """실제로 **쓸 수 있었던** 측정의 수. 선언된 AP 수가 아니다."""
        return sum(1 for r in self.ranges if r.state is RangeState.IN_RANGE)

    @property
    def bearing_resolved(self) -> bool:
        """방향이 나왔는가. 한 대로는 영원히 거짓이다."""
        return self.geometry is Geometry.BOUNDED

    @property
    def most_likely_zone(self) -> str | None:
        """질량이 가장 큰 구역. **하나뿐이면 아무 것도 가린 것이 아니다.**"""
        if not self.zone_posterior:
            return None
        return max(sorted(self.zone_posterior), key=lambda z: self.zone_posterior[z])

    def as_dict(self) -> dict:
        return {
            "state": self.state.value,
            "reason": self.reason,
            dd.COORDINATE_FRAME: COORDINATE_FRAME,
            "frame_id": self.frame_id,
            dd.POSE_SOURCE: POSE_SOURCE_RADIO_RANGE,
            dd.OBSERVED_AT: self.observed_at,
            "geometry": self.geometry.value,
            "fit_residual_sigma": (None if self.fit_residual_sigma is None
                                   else round(self.fit_residual_sigma, 2)),
            "anchor_count": self.anchor_count,
            "bearing_resolved": self.bearing_resolved,
            "ranges": [r.as_dict() for r in self.ranges],
            "region": None if self.region is None else self.region.as_dict(),
            "zone_posterior": {z: round(m, 4)
                               for z, m in sorted(self.zone_posterior.items())},
            "most_likely_zone": self.most_likely_zone,
            "coverage": [c.as_dict() for c in self.coverage],
            "resolution_requests": list(self.resolution_requests),
        }


# --- 추정기 ------------------------------------------------------------------


def _normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


@dataclass
class RssiLocalizer:
    """측정들을 받아 가능 영역과 구역 확률을 낸다. 상태를 바꾸지 않는다.

    모든 조정값은 **선언된 자리 하나**에 있다. 격자 간격을 좁히면 정확도가 올라가는
    것이 아니라 비용만 올라간다 — 영역의 크기를 정하는 것은 σ 이고 격자가 아니다.
    """

    radio_map: RadioMap
    #: 거리 구간을 몇 σ 로 낼 것인가. 1.0 이면 약 68% 구간이다.
    k_sigma: float = 1.0
    #: 격자 간격(m). 영역 해상도이고 정확도가 아니다.
    grid_step_m: float = 1.0
    #: 신뢰 영역이 담을 질량. 0.68 이면 "1σ 영역" 과 같은 뜻이다.
    region_mass: float = 0.68
    #: 가장 좋은 칸의 잔차가 이 σ 를 넘으면 지도 밖으로 **거절한다**. 억지로 맞추지
    #: 않는 쪽이 낫다 — 틀린 영역은 조용히 전파되고 거절은 눈에 보인다.
    reject_k_sigma: float = 3.0

    # --- 한 측정 -----------------------------------------------------------

    def range_for(self, reading: RssiReading) -> RangeEstimate:
        """측정 1건 → 거리 구간. 못 쓰는 측정도 사유를 달고 돌아온다."""
        ap_id = reading.peer_id or ""
        anchor = self.radio_map.anchor(ap_id) if ap_id else None
        frame = self.radio_map.frame_id
        # 원본 측정 참조 — 독립성의 단위다. `RssiReading` 은 이 칸을 들고 있지 않아
        # 여기서 (AP, 시각) 으로 짓는다. 같은 측정에서 나온 두 값은 한 번 본 것이다.
        frame_ref = f"radio:{ap_id or 'unknown'}@{reading.at}"

        if not reading.measured or reading.level_dbm is None:
            # 재지 못한 것과 세기가 나쁜 것은 다른 상태다. 여기서 0 을 쓰지 않는다.
            return RangeEstimate(
                ap_id=ap_id, state=RangeState.UNMEASURED, frame_id=frame,
                reason=reading.reason or REASON_NO_MEASUREMENT,
                observed_at=reading.at, frame_ref=frame_ref, source=reading.source)
        if anchor is None:
            return RangeEstimate(
                ap_id=ap_id, state=RangeState.UNMEASURED, frame_id=frame,
                reason=f"{REASON_UNKNOWN_ANCHOR}:{ap_id}",
                observed_at=reading.at, level_dbm=reading.level_dbm,
                frame_ref=frame_ref, source=reading.source)

        model = anchor.model
        level = float(reading.level_dbm)
        floor_dbm = model.thresholds_dbm.get(FLOOR_THRESHOLD)
        if floor_dbm is not None and level <= floor_dbm:
            # 바닥 아래의 dBm 은 수신기 한계에 눌린 값이라 거리로 환산하면 거짓말이
            # 된다. 하한만 낸다 — "범위 밖" 은 "미측정" 도 "0" 도 아니다.
            return RangeEstimate(
                ap_id=ap_id, state=RangeState.BEYOND_FLOOR, frame_id=frame,
                reason=f"{REASON_BEYOND_FLOOR}:{level:g}",
                observed_at=reading.at, level_dbm=level,
                lower_bound_m=model.radius_for_threshold(FLOOR_THRESHOLD),
                sigma_db=model.shadowing_sigma_db,
                sigma_basis=model.shadowing_basis, k_sigma=self.k_sigma,
                frame_ref=frame_ref, source=reading.source)

        lower, upper = model.distance_bounds_for(level, k_sigma=self.k_sigma)
        return RangeEstimate(
            ap_id=ap_id, state=RangeState.IN_RANGE, frame_id=frame,
            reason=f"{REASON_RANGE_ONLY}:{ap_id}",
            observed_at=reading.at, level_dbm=level,
            range_m=model.distance_m_for(level), lower_m=lower, upper_m=upper,
            sigma_db=model.shadowing_sigma_db, sigma_basis=model.shadowing_basis,
            k_sigma=self.k_sigma, frame_ref=frame_ref, source=reading.source)

    # --- 여러 측정 ---------------------------------------------------------

    def locate(
        self, readings: Iterable[RssiReading], *,
        zone_ids: Sequence[str] | None = None,
    ) -> RssiPositionBelief:
        """측정들 → 가능 영역 + 구역 확률.

        `zone_ids` 로 바탕 격자를 좁힐 수 있다(쓸 구역을 이미 아는 호출자). 주지
        않으면 지도의 모든 구역이 바탕이다.
        """
        ranges = tuple(self.range_for(r) for r in readings)
        coverage = self.radio_map.coverage()
        observed = [r.observed_at for r in ranges if r.observed_at is not None]
        at = max(observed) if observed else None

        usable = tuple(r for r in ranges
                       if r.state in (RangeState.IN_RANGE, RangeState.BEYOND_FLOOR))
        if not usable:
            reason = (REASON_NO_ANCHOR if not self.radio_map.anchors
                      else (ranges[0].reason if ranges else REASON_NO_MEASUREMENT))
            return RssiPositionBelief(
                state=BeliefState.UNMEASURED, reason=reason,
                frame_id=self.radio_map.frame_id, geometry=Geometry.NONE,
                ranges=ranges, coverage=coverage,
                resolution_requests=self._requests(0, 0, coverage), observed_at=at)

        zones = tuple(z for z in self.radio_map.zones
                      if zone_ids is None or z.zone_id in set(zone_ids))
        if not zones:
            return RssiPositionBelief(
                state=BeliefState.UNMEASURED, reason=REASON_EMPTY_MAP,
                frame_id=self.radio_map.frame_id, geometry=Geometry.NONE,
                ranges=ranges, coverage=coverage,
                resolution_requests=self._requests(len(usable), 0, coverage),
                observed_at=at)

        in_range = tuple(r for r in usable if r.state is RangeState.IN_RANGE)
        geometry = (Geometry.NONE if not in_range
                    else Geometry.RANGE_ONLY if len(in_range) == 1
                    else Geometry.TWO_LOBED if len(in_range) == 2
                    else Geometry.BOUNDED)

        cells, best_residual = self._likelihood(usable, zones)
        if not cells or best_residual > self.reject_k_sigma:
            return RssiPositionBelief(
                state=BeliefState.OUT_OF_MAP,
                reason=f"{REASON_OUT_OF_MAP}:{best_residual:.1f}",
                frame_id=self.radio_map.frame_id, geometry=geometry,
                ranges=ranges, coverage=coverage,
                fit_residual_sigma=(None if best_residual == math.inf
                                    else best_residual),
                resolution_requests=self._requests(len(usable), len(in_range),
                                                   coverage),
                observed_at=at)

        region = self._region(cells, zones)
        posterior = self._zone_posterior(cells, zones)
        reason = (f"{REASON_RANGE_ONLY}:{in_range[0].ap_id}" if len(in_range) == 1
                  else REASON_TWO_LOBED if len(in_range) == 2
                  else f"{REASON_BOUNDED}:{len(in_range)}"
                  if in_range else usable[0].reason)
        return RssiPositionBelief(
            state=BeliefState.LOCATED, reason=reason,
            frame_id=self.radio_map.frame_id, geometry=geometry, ranges=ranges,
            region=region, zone_posterior=posterior, coverage=coverage,
            fit_residual_sigma=best_residual,
            resolution_requests=self._requests(len(usable), len(in_range), coverage),
            observed_at=at)

    # --- 내부 --------------------------------------------------------------

    def _grid(self, zones: Sequence[ZoneExtent]):
        step = self.grid_step_m
        seen: set[tuple[int, int]] = set()
        for zone in zones:
            x0, y0, w, h = zone.rect
            nx = max(1, int(w / step))
            ny = max(1, int(h / step))
            for ix in range(nx):
                for iy in range(ny):
                    x = x0 + (ix + 0.5) * step
                    y = y0 + (iy + 0.5) * step
                    key = (round(x / step), round(y / step))
                    if key in seen:
                        continue
                    seen.add(key)
                    yield (x, y)

    def _likelihood(
        self, ranges: Sequence[RangeEstimate], zones: Sequence[ZoneExtent],
    ) -> tuple[tuple[tuple[float, float, float], ...], float]:
        """격자 칸마다 가능도를 계산해 정규화한다.

        `IN_RANGE` 는 정규 가능도, `BEYOND_FLOOR` 는 **중도절단** 가능도
        `P(level <= floor | cell)` 로 들어간다. 바닥 아래 측정도 "멀다" 는 정보를
        들고 있으므로 버리지 않되, 눌린 값을 거리로 환산하지도 않는다.
        """
        anchors = {r.ap_id: self.radio_map.anchor(r.ap_id) for r in ranges}
        rows: list[tuple[float, float, float]] = []
        best_loglik = -math.inf
        best_residual = math.inf
        for x, y in self._grid(zones):
            loglik = 0.0
            residual = 0.0
            for r in ranges:
                anchor = anchors.get(r.ap_id)
                if anchor is None or r.level_dbm is None:
                    continue
                model = anchor.model
                sigma = model.shadowing_sigma_db
                predicted = model.level_dbm(anchor.distance_to((x, y)))
                if r.state is RangeState.BEYOND_FLOOR:
                    floor_dbm = model.thresholds_dbm[FLOOR_THRESHOLD]
                    p = _normal_cdf((floor_dbm - predicted) / sigma)
                    loglik += math.log(max(p, 1e-12))
                    residual = max(residual,
                                   max(0.0, (predicted - floor_dbm) / sigma))
                    continue
                z = (float(r.level_dbm) - predicted) / sigma
                loglik += -0.5 * z * z
                residual = max(residual, abs(z))
            rows.append((x, y, loglik))
            if loglik > best_loglik:
                best_loglik = loglik
            best_residual = min(best_residual, residual)
        if not rows or best_loglik == -math.inf:
            return (), math.inf
        weights = [(x, y, math.exp(ll - best_loglik)) for x, y, ll in rows]
        total = sum(w for _, _, w in weights)
        if total <= 0.0:
            return (), math.inf
        return tuple((x, y, w / total) for x, y, w in weights), best_residual

    def _region(
        self, cells: Sequence[tuple[float, float, float]],
        zones: Sequence[ZoneExtent],
    ) -> Region:
        ordered = sorted(cells, key=lambda c: (-c[2], c[0], c[1]))
        kept: list[tuple[float, float, float]] = []
        mass = 0.0
        for cell in ordered:
            kept.append(cell)
            mass += cell[2]
            if mass >= self.region_mass:
                break
        xs = [c[0] for c in kept]
        ys = [c[1] for c in kept]
        cx = sum(c[0] * c[2] for c in kept) / mass
        cy = sum(c[1] * c[2] for c in kept) / mass
        spread = math.sqrt(
            sum(c[2] * ((c[0] - cx) ** 2 + (c[1] - cy) ** 2) for c in kept) / mass)
        inside = any(abs(c[0] - cx) <= self.grid_step_m
                     and abs(c[1] - cy) <= self.grid_step_m for c in kept)
        return Region(
            cells=tuple(kept), cell_size_m=self.grid_step_m, mass=mass,
            bbox=(min(xs), min(ys), max(xs), max(ys)),
            peak_at=(ordered[0][0], ordered[0][1]), centroid_at=(cx, cy),
            spread_m=spread, centroid_inside=inside)

    @staticmethod
    def _zone_posterior(
        cells: Sequence[tuple[float, float, float]], zones: Sequence[ZoneExtent],
    ) -> dict[str, float]:
        posterior: dict[str, float] = {}
        for x, y, w in cells:
            for zone in zones:
                if zone.contains((x, y)):
                    posterior[zone.zone_id] = posterior.get(zone.zone_id, 0.0) + w
        return posterior

    def _requests(
        self, measured: int, in_range: int, coverage: Sequence[CoverageAssessment],
    ) -> tuple[str, ...]:
        """무엇을 더 하면 풀리는가. 실행은 다른 파트의 몫이다(AI-C-19).

        측정이 **하나도 없는** 것과 측정은 됐지만 바닥 아래인 것을 가른다 — 둘을
        합치면 이미 켜져 있는 무선 측정을 다시 켜라고 요청하게 된다.
        """
        requests: list[str] = []
        if measured == 0:
            requests.append(REQUEST_ENABLE_RADIO_RANGING)
        if in_range < 3:
            # 세 대 미만이면 방향이 닫히지 않는다. 한 대짜리 현장에서 이 요청이 늘
            # 서 있는 것이 정상이고, 그 사실을 감추지 않는다.
            requests.append(REQUEST_ADD_ANCHOR)
        if any(not c.placement_verified for c in coverage):
            requests.append(REQUEST_SURVEY_AP_PLACEMENT)
        if in_range < 3:
            # 자리를 가릴 수 없을 때의 1순위 해법은 하드웨어 변경이 없는 운동
            # 프로브다 — `device_identity.py` 가 세운 순서를 그대로 따른다.
            requests.append(REQUEST_MOTION_PROBE)
        return tuple(requests)


# ---------------------------------------------------------------------------
# device_identity 의 `radio_range` 단서를 채우는 경로 (AI-S-02)
# ---------------------------------------------------------------------------

CUE_OK = "radio_range_cue_emitted"
CUE_UNMEASURED = "no_usable_range_measurement"
CUE_BEYOND_FLOOR = "range_is_a_lower_bound_only"
CUE_FRAME_MISMATCH = "frame_mismatch"
CUE_NO_ANCHOR = "anchor_position_unknown"


@dataclass(frozen=True)
class RangeCueOutcome:
    """단서 1건을 만들려 한 결과. **만들지 못한 이유도 산출물이다**.

    `cue` 가 `None` 인 것은 "세기 0 의 단서" 와 다르다. 0 을 내면 `device_identity`
    의 `_requests()` 가 무선 측정이 이미 있다고 보고 `enable_radio_ranging` 요청을
    빼버린다 — 없는 것을 있다고 세면 해법 요청이 사라진다(AI-S-05).
    """

    device_id: str
    track_id: str
    reason: str
    cue: IdentityCue | None = None
    measured_m: float | None = None
    expected_m: float | None = None
    tolerance_m: float | None = None
    #: `BEYOND_FLOOR` 일 때의 하한. 단서는 못 되지만 "멀다" 는 사실은 남는다.
    lower_bound_m: float | None = None

    def as_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "track_id": self.track_id,
            "reason": self.reason,
            "has_cue": self.cue is not None,
            "strength": None if self.cue is None else round(self.cue.strength, 4),
            "measured_m": None if self.measured_m is None else round(self.measured_m, 2),
            "expected_m": None if self.expected_m is None else round(self.expected_m, 2),
            "tolerance_m": (None if self.tolerance_m is None
                            else round(self.tolerance_m, 2)),
            "lower_bound_m": (None if self.lower_bound_m is None
                              else round(self.lower_bound_m, 2)),
        }


def radio_range_cue_for_track(
    belief: RssiPositionBelief,
    *,
    device_id: str,
    track_id: str,
    track_at: tuple[float, float],
    track_frame_id: str,
    anchor: Anchor,
    source: str = "radio_range_localization",
) -> RangeCueOutcome:
    """"이 track 이 그 장치인가" 를 무선 거리로 묻는다.

    장치가 **스스로 잰** AP 까지의 거리와, 화면이 본 track 자리에서 그 AP 까지의
    기대 거리를 맞춘다. 둘이 맞으면 그 track 이 그 장치일 수 있다.

    허용 오차는 이 함수가 정하지 않는다 — 그 측정의 kσ 거리 반폭이다. 흔들림이
    크면 오차가 넓어져 두 후보가 모두 높은 세기를 받고, 그때 1위를 고르는 것은
    `DeviceIdentityResolver` 의 `discriminating_margin` 이 막는다(`AMBIGUOUS`).
    여기서 임계값을 따로 적지 않는 이유가 그것이다.
    """
    if track_frame_id != belief.frame_id or track_frame_id != anchor.frame_id:
        # 로컬과 전역은 교환 가능하지 않다. 섞으면 그 거리는 아무 프레임의 값도 아니다.
        return RangeCueOutcome(device_id, track_id, CUE_FRAME_MISMATCH)
    if not is_local_frame(track_frame_id):
        return RangeCueOutcome(device_id, track_id, CUE_FRAME_MISMATCH)

    estimate = next((r for r in belief.ranges if r.ap_id == anchor.ap_id), None)
    if estimate is None or estimate.state is RangeState.UNMEASURED:
        return RangeCueOutcome(device_id, track_id, CUE_UNMEASURED)
    if estimate.state is RangeState.BEYOND_FLOOR:
        return RangeCueOutcome(device_id, track_id, CUE_BEYOND_FLOOR,
                               lower_bound_m=estimate.lower_bound_m)

    tolerance = estimate.half_width_m
    if estimate.range_m is None or tolerance is None or tolerance <= 0.0:
        return RangeCueOutcome(device_id, track_id, CUE_UNMEASURED)

    expected = expected_range_m(anchor.at, track_at)
    cue = radio_range_cue(
        device_id, observed_at=estimate.observed_at or 0.0,
        measured_m=estimate.range_m, expected_m=expected, tolerance_m=tolerance,
        source=source, frame_ref=estimate.frame_ref)
    return RangeCueOutcome(
        device_id, track_id, CUE_OK, cue=cue, measured_m=estimate.range_m,
        expected_m=expected, tolerance_m=tolerance)


def radio_range_cues(
    beliefs: Mapping[str, RssiPositionBelief],
    *,
    track_id: str,
    track_at: tuple[float, float],
    track_frame_id: str,
    anchor: Anchor,
    source: str = "radio_range_localization",
) -> tuple[RangeCueOutcome, ...]:
    """후보 장치들의 믿음을 한 track 에 대한 단서들로 옮긴다.

    결과를 `DeviceIdentityResolver.resolve(track_id, [o.cue for o in out if o.cue])`
    에 그대로 넣을 수 있다. 단서가 못 나온 후보는 **빠지는 것이 아니라** 사유를 달고
    남는다 — 왜 그 후보가 세어지지 않았는지는 산출물이어야 한다.
    """
    return tuple(
        radio_range_cue_for_track(
            belief, device_id=device_id, track_id=track_id, track_at=track_at,
            track_frame_id=track_frame_id, anchor=anchor, source=source)
        for device_id, belief in sorted(beliefs.items()))


__all__ = [
    "COORDINATE_FRAME", "POSE_SOURCE_RADIO_RANGE", "FLOOR_THRESHOLD",
    "AP_PLACEMENT_FIELD", "REQUIREMENT", "LOCALIZATION_REASONS",
    "RangeState", "Geometry", "BeliefState",
    "Anchor", "ZoneExtent", "CoverageAssessment", "RadioMap",
    "RangeEstimate", "Region", "RssiPositionBelief", "RssiLocalizer",
    "RangeCueOutcome", "radio_range_cue_for_track", "radio_range_cues",
    "REQUEST_ENABLE_RADIO_RANGING", "REQUEST_MOTION_PROBE",
    "REQUEST_ADD_ANCHOR", "REQUEST_SURVEY_AP_PLACEMENT",
    "CUE_OK", "CUE_UNMEASURED", "CUE_BEYOND_FLOOR", "CUE_FRAME_MISMATCH",
    "CUE_NO_ANCHOR",
]
