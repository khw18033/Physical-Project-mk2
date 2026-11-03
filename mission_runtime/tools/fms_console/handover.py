"""implements: AI-N-03, AI-N-02, AI-C-05
tests: tests/test_fms_handover.py

구역을 넘나드는 로봇의 **입력과 사실**을 만드는 자리. 판단은 여기서 하지 않는다.

`ondevice/zone_handover.py` 가 "지금 다른 구역으로 넘어가고 있는가"를 이미
판정한다 — 세 겹의 이력 조건과 되돌아감 벌칙, 그리고 요청과 사실의 분리까지
그쪽이 소유한다. 이 모듈이 더하는 것은 두 가지뿐이다.

1. 그 정책이 먹을 **실제 입력**을 만든다. 로봇의 로컬 좌표와 배포 프로파일의
   AP 자리·RF 모델에서 신호 세기를 되계산해 `LinkSample`/`PeerObservation` 로
   옮긴다.
2. 전환이 실제로 일어났다는 **사실**과, 그 전환이 무선 재접속을 요구했는지·
   새 구역 구성을 다시 받아야 하는지를 따로 적는다.

왜 숫자를 되계산하는가 (드리프트 금지)
--------------------------------------
`profiles/domains.example.json` 의 `radius_m.{excellent,handover,floor}` 는
같은 파일의 `rf.<kind>` 모델(`tx_eirp_dbm`, `reference_loss_db_at_1m`,
`path_loss_exponent`)과 `thresholds_dbm` 에서 **유도된 값**이다. 그 반경을
코드에 상수로 베껴 두면 모델을 고치는 날 둘이 갈라지고, 화면은 어느 쪽이
참인지 말할 수 없게 된다. 그래서 이 모듈은 반경을 읽어 쓰지 않고 모델에서
다시 계산하며, 시험이 "다시 계산한 값 == 프로파일이 적어 둔 반경"을 고정한다.

    level_dbm(d) = tx_eirp_dbm - reference_loss_db_at_1m
                   - 10 * path_loss_exponent * log10(d)        (d >= 1m)

AP 와 구역은 1:1 이 아니다
--------------------------
옥외에서는 한 AP 가 수백 m 를 덮어 여러 구역을 함께 담는다. 그래서 후보는
AP 단위가 아니라 **구역 단위**로 만든다: 같은 AP 를 공유하는 두 구역은 같은
품질을 받으므로 정책이 그 경계를 품질 차이로 넘으려 하지 않고, 실제로 그
경계는 무선 전환이 아니다. 그 구분을 지우면 "구역을 넘었으니 재접속했을
것"이라는 틀린 가정이 생긴다(`FleetModel.zone_neighbours()` 의 같은 판정을
여기서 다시 쓰지 않고 그대로 소비한다).

같은 이유로 `config_refresh_required` 는 구역 id 가 바뀐 것만으로 서지 않는다.
프로파일이 선언한 외부 구성 서명(AP·RF 종류·엣지 노드·층)이 실제로 달라졌을
때만 선다 — 바뀐 것이 없는데 재적용을 돌리면 경계에서 왔다 갔다 할 때마다
공짜가 아닌 일이 따라붙는다(AI-N-02). 정책이 내놓은 원래 신호
(`ZoneEntry.requires_config_refresh`)는 숨기지 않고 `ZoneCrossing.entry` 에
그대로 남는다.

dBm 이 나와도 되는 자리
-----------------------
AI-N-03 은 상위 판단에 무선 규격·지표 이름이 나타나는 것을 금지하고, 그 이름이
사는 자리는 provider 구현뿐이다(`providers/rssi_link_quality.py` 의 docstring).
이 모듈은 그 provider 와 같은 쪽 — 좌표를 신호로 옮기는 변환기 — 이므로 dBm 이
여기 있는 것은 경계 위반이 아니다. 정규화는 그 provider 의 `RssiQualityMapping`
을 재사용한다: 기본값 조합에서 품질 0.25 가 정확히 -75dBm 이고, 그 값이
`LinkTransitionPolicy.floor` 이자 프로파일의 `handover` 문턱이다. 세 숫자가 한
곳에서 오지 않으면 "표본은 괜찮다는데 판정은 바닥"이 된다.

로컬은 링크에 걸리지 않는다 (AI-N-01, AI-N-03)
----------------------------------------------
이 런타임에는 로컬 기능을 멈추는 경로가 없다. `cache_state()` 는 조회 전용이고
`MissionCache.suspend_for_safety()` 를 호출하지 않는다 — 링크가 끊겼다는 사실이
이미 승인·전달된 항목의 수행 허가를 좁히면 안 되기 때문이다. 좁히는 쪽은
발급자가 붙인 `MissionAutonomy` 와 유효기한뿐이다(AI-C-19).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from mission_runtime.ondevice.link_handover import LinkPosture, LinkSample
from mission_runtime.ondevice.mission_cache import MissionCache
from mission_runtime.ondevice.zone_handover import (
    PeerObservation,
    ZoneEntry,
    ZoneHandoverDecision,
    ZoneHandoverPolicy,
)
from mission_runtime.providers.rssi_link_quality import DEFAULT_MAPPING, RssiQualityMapping
from mission_runtime.tools.fms_console.fleet import FleetModel, load_domain_profile

# --- 사유 통제 어휘 ----------------------------------------------------------
# ':' 앞이 토큰, 뒤가 데이터 — `zone_handover.py` 와 같은 규약.

TRANSIT_ALREADY_IN_ZONE = "transit_already_in_zone"            # + ":<zone>"
TRANSIT_NOT_REQUESTED = "transit_switch_not_requested"         # + ":<policy reason>"
TRANSIT_REJECTED = "transit_switch_rejected_by_provider"       # + ":<zone>"
TRANSIT_CONFIRMED = "transit_switch_confirmed"                 # + ":<zone>"
TRANSIT_UNKNOWN_ZONE = "transit_zone_not_in_this_domain"       # + ":<zone>"
TRANSIT_NO_ACCESS_POINT = "transit_zone_has_no_access_point"   # + ":<zone>"
TRANSIT_SAME_AP_BOUNDARY = "transit_same_access_point_boundary"  # + ":<zone>"
TRANSIT_NOT_IN_ZONE = "transit_position_not_in_zone"           # + ":<zone>"

TRANSIT_REASONS: tuple[str, ...] = (
    TRANSIT_ALREADY_IN_ZONE,
    TRANSIT_NOT_REQUESTED,
    TRANSIT_REJECTED,
    TRANSIT_CONFIRMED,
    TRANSIT_UNKNOWN_ZONE,
    TRANSIT_NO_ACCESS_POINT,
    TRANSIT_SAME_AP_BOUNDARY,
    TRANSIT_NOT_IN_ZONE,
)

#: 전환을 요청하게 만든 근거. 품질 우세폭을 기다려야 하는 쪽과 그럴 필요가 없는
#: 쪽을 구분한다 — 같은 AP 안의 경계는 무선이 할 일이 없어 기다릴 것이 없다.
REQUESTED_BY_LINK = "link_quality"
REQUESTED_BY_POSITION = "position"

#: 프로파일이 선언할 수 있는 RF 모델 이름. 모르는 모델은 추측하지 않고 거부한다.
LOG_DISTANCE = "log_distance"

#: 경로손실 기준거리. 이보다 가까운 거리는 모델의 적용 범위 밖이므로 눌러 쓴다.
REFERENCE_DISTANCE_M = 1.0


class RadioProfileError(ValueError):
    """RF·AP 선언을 그대로 쓸 수 없다. 조용히 기본값을 끼워 넣지 않는다."""


# --- RF 모델 -----------------------------------------------------------------


@dataclass(frozen=True)
class RfModel:
    """한 도메인의 한 RF 종류. 계수는 전부 프로파일 데이터다."""

    kind: str
    tx_eirp_dbm: float
    reference_loss_db_at_1m: float
    path_loss_exponent: float
    #: 프로파일이 적어 둔 유도값. **계산에 쓰지 않는다** — 비교용으로만 들고 있다.
    radius_m: Mapping[str, float] = field(default_factory=dict)
    thresholds_dbm: Mapping[str, float] = field(default_factory=dict)
    model: str = LOG_DISTANCE

    @classmethod
    def from_profile(cls, kind: str, raw: Mapping[str, Any]) -> "RfModel":
        model = raw.get("model")
        if model != LOG_DISTANCE:
            raise RadioProfileError(f"unsupported rf model for {kind!r}: {model!r}")
        for key in ("tx_eirp_dbm", "reference_loss_db_at_1m", "path_loss_exponent"):
            if key not in raw:
                raise RadioProfileError(f"rf model {kind!r} missing {key!r}")
        if float(raw["path_loss_exponent"]) <= 0:
            raise RadioProfileError(f"rf model {kind!r} needs a positive path loss exponent")
        return cls(
            kind=kind,
            tx_eirp_dbm=float(raw["tx_eirp_dbm"]),
            reference_loss_db_at_1m=float(raw["reference_loss_db_at_1m"]),
            path_loss_exponent=float(raw["path_loss_exponent"]),
            radius_m={k: float(v) for k, v in (raw.get("radius_m") or {}).items()},
            thresholds_dbm={k: float(v) for k, v in (raw.get("thresholds_dbm") or {}).items()},
            model=model,
        )

    def level_dbm(self, distance_m: float) -> float:
        """거리 → 신호 세기. 프로파일의 반경을 정한 것과 **같은** 식이다."""
        distance = max(float(distance_m), REFERENCE_DISTANCE_M)
        loss = self.reference_loss_db_at_1m + 10.0 * self.path_loss_exponent * math.log10(distance)
        return self.tx_eirp_dbm - loss

    def distance_m_for(self, level_dbm: float) -> float:
        """위 식의 역함수. 프로파일의 `radius_m` 과 맞춰 보는 쪽이 이 함수다."""
        budget = self.tx_eirp_dbm - self.reference_loss_db_at_1m - float(level_dbm)
        return 10.0 ** (budget / (10.0 * self.path_loss_exponent))


# --- AP·구역 지형 -------------------------------------------------------------


@dataclass(frozen=True)
class Position:
    """로봇의 **로컬** 좌표. 전역 좌표 변환은 백엔드의 몫이다(AI-C-02)."""

    x: float
    y: float
    level_id: str | None = None

    def distance_to(self, other: "Position | tuple[float, float]") -> float:
        ox, oy = (other.x, other.y) if isinstance(other, Position) else (other[0], other[1])
        return math.hypot(self.x - ox, self.y - oy)


@dataclass(frozen=True)
class AccessPoint:
    ap_id: str
    at: Position
    rf: RfModel
    #: 이 AP 가 덮는 구역들. 옥외에서는 하나가 아니다.
    zone_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ZoneReading:
    """한 구역에 대해 **되계산한** 값. 화면이 그대로 띄우는 숫자가 이것이다."""

    zone_id: str
    ap_id: str
    distance_m: float
    level_dbm: float
    quality: float
    #: 다른 층의 AP 는 평면도상 거리가 물리 거리가 아니므로 후보에서 뺀다.
    same_level: bool = True

    def as_dict(self) -> dict:
        return {
            "zone_id": self.zone_id,
            "ap_id": self.ap_id,
            "distance_m": round(self.distance_m, 2),
            "level_dbm": round(self.level_dbm, 1),
            "quality": round(self.quality, 3),
            "same_level": self.same_level,
        }


class ZoneRadioMap:
    """프로파일 한 도메인의 AP 자리·RF 모델을 읽어 신호를 되계산한다.

    `FleetModel` 을 읽기 전용으로 소비한다 — 구역 사전, 맞닿음, 그리고 "그
    경계가 무선 전환인가"는 그쪽이 이미 답하므로 여기서 다시 판정하지 않는다.
    """

    def __init__(self, fleet: FleetModel, domain_id: str, *,
                 mapping: RssiQualityMapping = DEFAULT_MAPPING) -> None:
        self._fleet = fleet
        self._domain_id = domain_id
        self._mapping = mapping
        domain = fleet.domain(domain_id)
        unit = (domain.get("space") or {}).get("unit")
        if unit != "meter":
            # 반경이 m 인데 좌표가 다른 단위면 거리가 조용히 틀린다.
            raise RadioProfileError(f"domain {domain_id!r} coordinates are in {unit!r}, not meter")

        self._models = {
            kind: RfModel.from_profile(kind, raw)
            for kind, raw in (domain.get("rf") or {}).items()
            if not kind.startswith("$")
        }
        self._zone_ap: dict[str, AccessPoint] = {}
        points: dict[str, list[str]] = {}
        for zone in domain["zones"]:
            wifi = zone.get("wifi") or {}
            ap_id, at, kind = wifi.get("ap_id"), wifi.get("at"), wifi.get("rf")
            if not ap_id or not at or kind not in self._models:
                continue  # 모르는 선언은 추측하지 않고 비운다 — 후보에서 그냥 빠진다
            self._zone_ap[zone["zone_id"]] = AccessPoint(
                ap_id=ap_id,
                at=Position(float(at["x"]), float(at["y"]), zone.get("level_id")),
                rf=self._models[kind],
            )
            points.setdefault(ap_id, []).append(zone["zone_id"])
        self._zone_ap = {
            zone_id: AccessPoint(ap.ap_id, ap.at, ap.rf, tuple(sorted(points[ap.ap_id])))
            for zone_id, ap in self._zone_ap.items()
        }

    @classmethod
    def from_profile(cls, path: str | Path, domain_id: str, **kwargs) -> "ZoneRadioMap":
        profile = load_domain_profile(path)
        return cls(FleetModel(domain_profile=profile, facts={}), domain_id, **kwargs)

    # --- 조회 ---------------------------------------------------------------

    @property
    def domain_id(self) -> str:
        return self._domain_id

    @property
    def mapping(self) -> RssiQualityMapping:
        return self._mapping

    @property
    def fleet(self) -> FleetModel:
        return self._fleet

    def rf_model(self, kind: str) -> RfModel:
        return self._models[kind]

    def rf_kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._models))

    def zone_ids(self) -> tuple[str, ...]:
        return tuple(z["zone_id"] for z in self._fleet.domain(self._domain_id)["zones"])

    def has_zone(self, zone_id: str) -> bool:
        return zone_id in set(self.zone_ids())

    def ap_of(self, zone_id: str) -> AccessPoint | None:
        """그 구역의 AP. 선언이 없으면 `None` — 0 이 아니라 모른다는 뜻이다."""
        return self._zone_ap.get(zone_id)

    def level_of(self, zone_id: str) -> str | None:
        return self._fleet.zone(zone_id).get("level_id")

    def zone_centre(self, zone_id: str) -> Position:
        rect = self._fleet.zone(zone_id)["rect"]
        return Position(
            rect["x"] + rect["w"] / 2.0, rect["y"] + rect["h"] / 2.0, self.level_of(zone_id)
        )

    def containing_zone(self, position: Position) -> str | None:
        """좌표가 들어 있는 구역. **기하가** 말하는 것이고 확인된 구역과 다르다."""
        for zone_id in self.zone_ids():
            if position.level_id is not None and self.level_of(zone_id) != position.level_id:
                continue
            rect = self._fleet.zone(zone_id)["rect"]
            if (rect["x"] <= position.x <= rect["x"] + rect["w"]
                    and rect["y"] <= position.y <= rect["y"] + rect["h"]):
                return zone_id
        return None

    # --- 되계산 -------------------------------------------------------------

    def readings_at(self, position: Position) -> tuple[ZoneReading, ...]:
        """구역마다 하나. 같은 AP 를 공유하는 구역은 같은 값을 받는다."""
        level = position.level_id
        rows: list[ZoneReading] = []
        for zone_id in self.zone_ids():
            ap = self._zone_ap.get(zone_id)
            if ap is None:
                continue
            distance = position.distance_to(ap.at)
            level_dbm = ap.rf.level_dbm(distance)
            rows.append(ZoneReading(
                zone_id=zone_id,
                ap_id=ap.ap_id,
                distance_m=distance,
                level_dbm=level_dbm,
                quality=self._mapping.quality_of_dbm(level_dbm),
                same_level=level is None or self.level_of(zone_id) == level,
            ))
        return tuple(rows)

    def peer_observations(self, position: Position) -> tuple[PeerObservation, ...]:
        """정책이 먹는 후보. 다른 층은 뺀다 — 평면도 거리는 물리 거리가 아니다."""
        return tuple(
            PeerObservation(peer_id=row.ap_id, quality=row.quality, zone_id=row.zone_id)
            for row in self.readings_at(position)
            if row.same_level
        )

    def sample_at(self, position: Position, *, at: float,
                  attached_ap: str | None = None) -> LinkSample | None:
        """붙어 있는 AP 의 표본. 붙을 AP 가 없으면 `None`(="모른다", ≠"나쁘다")."""
        rows = [row for row in self.readings_at(position) if row.same_level]
        if not rows:
            return None
        chosen = next((row for row in rows if row.ap_id == attached_ap), None)
        if chosen is None:
            if attached_ap is not None:
                # 붙어 있다고 아는 AP 가 이 자리에서 안 보인다. 다른 AP 의 값을
                # 그 AP 의 표본처럼 적으면 측정하지 않은 것을 측정했다고 말한다.
                return None
            chosen = max(rows, key=lambda row: (row.quality, row.ap_id))
        # 같은 AP 가 여러 구역을 덮으면 표본의 구역은 좌표가 정한다.
        here = self.containing_zone(position)
        zone_id = here if here is not None and self._zone_ap.get(here) is not None and \
            self._zone_ap[here].ap_id == chosen.ap_id else None
        return LinkSample(at=at, quality=chosen.quality, peer_id=chosen.ap_id, zone_id=zone_id)

    # --- 경계의 성격 ---------------------------------------------------------

    def radio_handover_required(self, from_zone: str | None, to_zone: str) -> bool:
        """그 경계를 넘는 것이 무선 전환인가. 맞닿은 구역은 `FleetModel` 이 답한다."""
        if from_zone is None:
            return True  # 처음 붙는 것은 언제나 접속이다
        if from_zone == to_zone:
            return False
        for row in self._fleet.zone_neighbours(from_zone):
            if row["zone_id"] == to_zone:
                return bool(row["radio_handover_required"])
        source, target = self._zone_ap.get(from_zone), self._zone_ap.get(to_zone)
        if source is None or target is None:
            return True  # 모르면 접속이 필요하다고 보는 쪽이 안전하다
        return source.ap_id != target.ap_id

    def config_signature(self, zone_id: str) -> tuple:
        """그 구역의 외부 구성이 무엇으로 정해지는가(AI-N-02 의 적용 대상)."""
        zone = self._fleet.zone(zone_id)
        wifi = zone.get("wifi") or {}
        return (wifi.get("ap_id"), wifi.get("rf"), zone.get("edge_node"), zone.get("level_id"))

    def config_refresh_required(self, from_zone: str | None, to_zone: str) -> bool:
        """구역 id 가 아니라 **선언된 구성**이 바뀌었는가."""
        if from_zone is None or from_zone == to_zone:
            return from_zone != to_zone
        return self.config_signature(from_zone) != self.config_signature(to_zone)


# --- 전환의 요청과 사실 --------------------------------------------------------


@dataclass(frozen=True)
class ZoneTransitDecision:
    """관측 1건의 결과. 정책의 답을 감싸기만 하고 고치지 않는다."""

    decision: ZoneHandoverDecision
    readings: tuple[ZoneReading, ...]
    attached_ap: str | None
    #: 좌표가 말하는 구역. 확인된 구역(`zone_id`)과 다를 수 있고, 다른 동안이
    #: 바로 "넘어가는 중"이다.
    containing_zone: str | None
    at: float

    @property
    def zone_id(self) -> str | None:
        return self.decision.zone_id

    @property
    def posture(self) -> LinkPosture:
        return self.decision.posture

    @property
    def requests_zone_switch(self) -> bool:
        return self.decision.requests_zone_switch

    @property
    def switch_to_zone(self) -> str | None:
        return self.decision.switch_to_zone

    @property
    def reason(self) -> str:
        return self.decision.zone_reason

    @property
    def quality(self) -> float | None:
        return self.decision.quality

    @property
    def in_transit(self) -> bool:
        return self.containing_zone is not None and self.containing_zone != self.zone_id

    def as_dict(self) -> dict:
        return {
            "at": self.at,
            "zone_id": self.zone_id,
            "containing_zone": self.containing_zone,
            "in_transit": self.in_transit,
            "posture": self.posture.value,
            "attached_ap": self.attached_ap,
            "quality": self.quality,
            "reason": self.reason,
            "requests_zone_switch": self.requests_zone_switch,
            "switch_to_zone": self.switch_to_zone,
            "switch_to_peer": self.decision.switch_to_peer,
            "readings": [row.as_dict() for row in self.readings],
        }


@dataclass(frozen=True)
class ZoneCrossing:
    """전환이 실제로 일어났다는 사실. provider 가 성공을 알렸을 때만 생긴다."""

    entry: ZoneEntry
    at: float
    radio_handover_required: bool
    config_refresh_required: bool
    attached_ap: str | None
    previous_ap: str | None
    attempt: int = 1

    @property
    def zone_id(self) -> str:
        return self.entry.zone_id

    @property
    def previous_zone(self) -> str | None:
        return self.entry.previous_zone

    @property
    def is_return(self) -> bool:
        return self.entry.is_return

    def as_dict(self) -> dict:
        return {
            "at": self.at,
            "zone_id": self.zone_id,
            "previous_zone": self.previous_zone,
            "attempt": self.attempt,
            "reason": self.entry.reason,
            "is_return": self.is_return,
            "radio_handover_required": self.radio_handover_required,
            "reconnect_required": self.radio_handover_required,
            "config_refresh_required": self.config_refresh_required,
            # 정책이 내놓은 원래 신호. 우리가 행동하지 않아도 숨기지 않는다.
            "entry_requires_config_refresh": self.entry.requires_config_refresh,
            "attached_ap": self.attached_ap,
            "previous_ap": self.previous_ap,
        }


@dataclass(frozen=True)
class CrossingAttempt:
    """한 번의 전환 시도. 요청과 사실이 **다른 칸**에 있다."""

    zone_id: str
    requested: bool
    confirmed: bool
    reason: str
    crossing: ZoneCrossing | None = None
    decisions: tuple[ZoneTransitDecision, ...] = ()
    attempt: int = 1
    #: 무엇이 전환을 요청했는가 — `REQUESTED_BY_LINK` 또는 `REQUESTED_BY_POSITION`.
    requested_by: str | None = None
    #: 이 경계를 넘는 것이 무선 전환이었는가. 아니면 재접속은 일어나지 않았다.
    radio_handover_required: bool = True

    @property
    def failed(self) -> bool:
        """요청은 했는데 사실이 되지 못한 시도. 성공처럼 보이지 않아야 한다."""
        return self.requested and not self.confirmed

    def as_dict(self) -> dict:
        return {
            "zone_id": self.zone_id,
            "attempt": self.attempt,
            "requested": self.requested,
            "requested_by": self.requested_by,
            "radio_handover_required": self.radio_handover_required,
            "confirmed": self.confirmed,
            "failed": self.failed,
            "reason": self.reason,
            "crossing": self.crossing.as_dict() if self.crossing else None,
            "decisions": [d.as_dict() for d in self.decisions],
        }


@dataclass
class ZoneTransitRuntime:
    """정책에 실제 입력을 먹이고, 전환의 사실을 적는다.

    `confirm_zone_fn` 이 네트워크·실행 provider 의 자리다(AI-N-03/AI-C-19:
    실제 무선 전환과 피어 선택은 AI 의 책임이 아니다). 그것이 거짓을 돌려주면
    구역은 바뀌지 않고 시도만 실패로 남는다 — 요청을 사실 칸에 적지 않는 것이
    이 런타임의 유일한 불변조건이다.
    """

    radio: ZoneRadioMap
    policy: ZoneHandoverPolicy = field(default_factory=ZoneHandoverPolicy)
    #: 전환을 실제로 수행하는 쪽. 기본값은 "언제나 성공" — 시험·시뮬레이터용이다.
    confirm_zone_fn: Callable[[str, float], bool] = lambda zone_id, at: True
    #: 링크가 없는 동안 무엇을 이어서 해도 되는지 아는 쪽. 조회만 한다.
    cache: MissionCache | None = None

    _attached_ap: str | None = None
    _last: ZoneTransitDecision | None = None
    _crossings: list[ZoneCrossing] = field(default_factory=list)
    _attempts: list[CrossingAttempt] = field(default_factory=list)

    # --- 조회 ---------------------------------------------------------------

    @property
    def zone_id(self) -> str | None:
        """확인된 구역. 요청 중인 구역은 여기 들어오지 않는다."""
        return self.policy.zone_id

    @property
    def posture(self) -> LinkPosture:
        return self.policy.posture

    @property
    def attached_ap(self) -> str | None:
        return self._attached_ap

    @property
    def last_decision(self) -> ZoneTransitDecision | None:
        return self._last

    @property
    def crossings(self) -> tuple[ZoneCrossing, ...]:
        return tuple(self._crossings)

    @property
    def attempts(self) -> tuple[CrossingAttempt, ...]:
        """시도 이력. 실패한 시도도 지우지 않는다."""
        return tuple(self._attempts)

    @property
    def failed_attempts(self) -> tuple[CrossingAttempt, ...]:
        return tuple(a for a in self._attempts if a.failed)

    @property
    def out_of_contact(self) -> bool:
        return self.posture is LinkPosture.LOCAL_ONLY

    # --- 관측 ---------------------------------------------------------------

    def observe_at(self, position: Position, *, at: float) -> ZoneTransitDecision:
        """좌표 1건 → 정책 판단. 구역은 절대 여기서 바뀌지 않는다."""
        sample = self.radio.sample_at(position, at=at, attached_ap=self._attached_ap)
        if sample is None and self._attached_ap is not None:
            # 아는 AP 가 안 보인다. 다른 AP 로 조용히 갈아타면 그 순간의 품질
            # 급변이 추세로 들어가므로, 먼저 붙을 AP 를 다시 고른다.
            sample = self.radio.sample_at(position, at=at)
            if sample is not None:
                self._attached_ap = sample.peer_id
        if sample is None:
            return self.observe_unmeasured(at=at)
        self._attached_ap = sample.peer_id
        decision = self.policy.observe(sample, list(self.radio.peer_observations(position)))
        self._last = ZoneTransitDecision(
            decision=decision,
            readings=self.radio.readings_at(position),
            attached_ap=self._attached_ap,
            containing_zone=self.radio.containing_zone(position),
            at=at,
        )
        return self._last

    def observe_unmeasured(self, *, at: float, reason: str = "") -> ZoneTransitDecision:
        """못 쟀다. 0.0 표본을 만들지 않고 "모른다"로 센다(AI-C-05)."""
        decision = self.policy.observe_unknown(at, reason)
        self._last = ZoneTransitDecision(
            decision=decision,
            readings=(),
            attached_ap=self._attached_ap,
            containing_zone=self._last.containing_zone if self._last else None,
            at=at,
        )
        return self._last

    # --- 사실 반영 -----------------------------------------------------------

    def confirm(self, zone_id: str, *, at: float) -> ZoneCrossing:
        """provider 가 전환에 성공했다. 여기서만 현재 구역이 바뀐다."""
        previous = self.policy.zone_id
        previous_ap = self._attached_ap
        radio = self.radio.radio_handover_required(previous, zone_id)
        refresh = self.radio.config_refresh_required(previous, zone_id)
        entry = self.policy.confirm_zone(zone_id, at=at)
        ap = self.radio.ap_of(zone_id)
        if radio and ap is not None:
            self._attached_ap = ap.ap_id
        crossing = ZoneCrossing(
            entry=entry,
            at=at,
            radio_handover_required=radio,
            config_refresh_required=refresh and entry.requires_config_refresh,
            attached_ap=self._attached_ap,
            previous_ap=previous_ap,
            attempt=sum(1 for c in self._crossings if c.zone_id == zone_id) + 1,
        )
        self._crossings.append(crossing)
        return crossing

    def cross_to(
        self,
        zone_id: str,
        *,
        at: float,
        position: Position | None = None,
        ticks: int | None = None,
        step_seconds: float = 1.0,
    ) -> CrossingAttempt:
        """목표 구역으로 넘어가 본다. 요청이 서지 않으면 넘어가지 않는다.

        같은 자리에서 표본을 되풀이하는 것이 아니라 **움직이는 동안** 연속으로
        관측한다고 본다 — 정책의 연속 표본 조건은 그 연속성을 요구하는 것이고,
        한 번 튄 값으로 구역을 바꾸지 않기 위한 장치다. 그래서 기본 횟수를
        정책이 요구하는 만큼(+체류시간을 넘길 만큼)으로 둔다.
        """
        attempt_no = sum(1 for a in self._attempts if a.zone_id == zone_id) + 1

        if not self.radio.has_zone(zone_id):
            return self._record(CrossingAttempt(
                zone_id, False, False, f"{TRANSIT_UNKNOWN_ZONE}:{zone_id}", attempt=attempt_no))
        if self.radio.ap_of(zone_id) is None:
            return self._record(CrossingAttempt(
                zone_id, False, False, f"{TRANSIT_NO_ACCESS_POINT}:{zone_id}",
                attempt=attempt_no))
        if self.policy.zone_id == zone_id:
            return self._record(CrossingAttempt(
                zone_id, False, True, f"{TRANSIT_ALREADY_IN_ZONE}:{zone_id}",
                attempt=attempt_no))

        where = position if position is not None else self.radio.zone_centre(zone_id)
        radio_needed = self.radio.radio_handover_required(self.policy.zone_id, zone_id)
        if not radio_needed:
            return self._cross_same_ap(zone_id, where, at=at, attempt_no=attempt_no)

        if ticks is None:
            dwell = self.policy.min_zone_dwell_seconds / max(step_seconds, 1e-9)
            ticks = max(self.policy.zone_hold_samples, int(math.ceil(dwell)) + 1)

        decisions: list[ZoneTransitDecision] = []
        for index in range(max(1, ticks)):
            decision = self.observe_at(where, at=at + index * step_seconds)
            decisions.append(decision)
            if decision.switch_to_zone == zone_id:
                moment = decision.at
                if not self.confirm_zone_fn(zone_id, moment):
                    # 요청했지만 실패했다. 구역은 그대로이고 그 사실이 남는다.
                    return self._record(CrossingAttempt(
                        zone_id, True, False, f"{TRANSIT_REJECTED}:{zone_id}",
                        decisions=tuple(decisions), attempt=attempt_no,
                        requested_by=REQUESTED_BY_LINK))
                crossing = self.confirm(zone_id, at=moment)
                return self._record(CrossingAttempt(
                    zone_id, True, True, f"{TRANSIT_CONFIRMED}:{zone_id}",
                    crossing=crossing, decisions=tuple(decisions), attempt=attempt_no,
                    requested_by=REQUESTED_BY_LINK,
                    radio_handover_required=crossing.radio_handover_required))

        last_reason = decisions[-1].reason if decisions else ""
        return self._record(CrossingAttempt(
            zone_id, False, False, f"{TRANSIT_NOT_REQUESTED}:{last_reason}",
            decisions=tuple(decisions), attempt=attempt_no,
            requested_by=REQUESTED_BY_LINK))

    def _cross_same_ap(self, zone_id: str, where: Position, *, at: float,
                       attempt_no: int) -> CrossingAttempt:
        """같은 AP 를 공유하는 구역 경계. 무선에는 할 일이 없다.

        품질 우세폭과 연속 표본은 **구성 재적용과 재접속을 아끼기 위한** 장치다.
        같은 AP 안에서는 아낄 것이 없고, 그런데도 기다리게 하면 전환이 요구하지
        않는 비용을 요구하는 셈이 된다. 그래서 여기서는 좌표가 실제로 그 구역에
        들어왔는지만 보고 provider 에게 사실 확인을 받는다 — 구역이 바뀌는 길은
        여전히 `confirm_zone()` 하나뿐이고, provider 가 거부하면 바뀌지 않는다.
        """
        decision = self.observe_at(where, at=at)
        if decision.containing_zone != zone_id:
            return self._record(CrossingAttempt(
                zone_id, False, False, f"{TRANSIT_NOT_IN_ZONE}:{zone_id}",
                decisions=(decision,), attempt=attempt_no,
                requested_by=REQUESTED_BY_POSITION, radio_handover_required=False))
        if not self.confirm_zone_fn(zone_id, at):
            return self._record(CrossingAttempt(
                zone_id, True, False, f"{TRANSIT_REJECTED}:{zone_id}",
                decisions=(decision,), attempt=attempt_no,
                requested_by=REQUESTED_BY_POSITION, radio_handover_required=False))
        crossing = self.confirm(zone_id, at=at)
        return self._record(CrossingAttempt(
            zone_id, True, True, f"{TRANSIT_SAME_AP_BOUNDARY}:{zone_id}",
            crossing=crossing, decisions=(decision,), attempt=attempt_no,
            requested_by=REQUESTED_BY_POSITION,
            radio_handover_required=crossing.radio_handover_required))

    def _record(self, attempt: CrossingAttempt) -> CrossingAttempt:
        self._attempts.append(attempt)
        return attempt

    def attempts_for(self, zone_id: str) -> tuple[CrossingAttempt, ...]:
        return tuple(a for a in self._attempts if a.zone_id == zone_id)

    # --- 링크가 없는 동안 (조회 전용) ------------------------------------------

    def cache_state(self, *, now: float | None = None) -> dict | None:
        """링크 없이 무엇을 이어서 해도 되는가. **읽기만** 한다.

        여기서 `suspend_for_safety()` 를 부르지 않는 이유는 AI-N-01/AI-N-03 이다:
        링크가 끊겼다는 사실이 이미 승인·전달된 항목의 허가를 좁히면, 연결이
        없는 동안 로컬이 멈춘다. 허가를 좁히는 것은 발급자가 붙인 자율 등급과
        유효기한뿐이다(AI-C-19).
        """
        if self.cache is None:
            return None
        snapshot = self.cache.snapshot(now=now)
        return {
            "out_of_contact": self.out_of_contact,
            "mission_id": snapshot.mission_id,
            "version": snapshot.version,
            "origin_command_id": snapshot.origin_command_id,
            "resumable_without_link": list(snapshot.resumable_without_link),
            "blocked_pending_command": list(snapshot.blocked_pending_command),
            "autonomy_block_reason": snapshot.autonomy_block_reason,
            "safety_suspended": snapshot.safety_suspended,
            "process_restarts": snapshot.process_restarts,
            "outstanding": list(snapshot.outstanding()),
            "completed": list(snapshot.completed()),
            "progress": [
                {"item_id": p.item_id, "state": p.state.value,
                 "outcome": p.outcome.value if p.outcome else None}
                for p in snapshot.progress
            ],
        }

    # --- 상태 ---------------------------------------------------------------

    def status(self, *, now: float | None = None) -> dict:
        """구역 전환은 링크 품질과 **다른 신호**다. 한 칸에 합치지 않는다."""
        last = self._last
        return {
            "signal": "zone_transit",
            "domain_id": self.radio.domain_id,
            "zone_id": self.zone_id,
            "containing_zone": last.containing_zone if last else None,
            "in_transit": bool(last and last.in_transit),
            "posture": self.posture.value,
            "out_of_contact": self.out_of_contact,
            "attached_ap": self._attached_ap,
            "decision": last.as_dict() if last else None,
            "zone_handover": self.policy.status(),
            "link_quality": self.policy.transition.status(),
            "crossings": [c.as_dict() for c in self._crossings],
            "attempts": [a.as_dict() for a in self._attempts],
            "failed_attempts": [a.as_dict() for a in self.failed_attempts],
            "cache": self.cache_state(now=now),
        }


def recomputed_radii(model: RfModel) -> dict[str, float]:
    """모델에서 다시 계산한 문턱별 반경. 프로파일이 적어 둔 값과 맞춰 보는 쪽.

    프로파일의 `radius_m` 을 읽어 쓰지 않는 이유가 이 함수의 존재 이유다 —
    둘이 어긋나면 시험이 깨지고, 깨져야 한다.
    """
    return {
        name: round(model.distance_m_for(level), 1)
        for name, level in sorted(model.thresholds_dbm.items())
    }


def cached_item_states(cache: MissionCache) -> dict[str, str]:
    """항목별 진행 상태 — 화면이 "어디까지 했는가"를 적는 데 쓴다."""
    return {p.item_id: p.state.value for p in cache.progress()}


__all__ = [
    "AccessPoint",
    "REQUESTED_BY_LINK",
    "REQUESTED_BY_POSITION",
    "CrossingAttempt",
    "LOG_DISTANCE",
    "Position",
    "RadioProfileError",
    "RfModel",
    "ZoneCrossing",
    "ZoneRadioMap",
    "ZoneReading",
    "ZoneTransitDecision",
    "ZoneTransitRuntime",
    "cached_item_states",
    "recomputed_radii",
    "TRANSIT_CONFIRMED",
    "TRANSIT_NOT_IN_ZONE",
    "TRANSIT_NOT_REQUESTED",
    "TRANSIT_REASONS",
    "TRANSIT_REJECTED",
    "TRANSIT_SAME_AP_BOUNDARY",
]
