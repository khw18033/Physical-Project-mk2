"""Builds the picture the FMS console shows: domains, zones, what is actually
there, and what each robot can do in that zone.

implements: AI-C-10 (기능·자원 등록·탐색), AI-C-18 (capability 선언), AI-C-15 (도메인은 데이터),
            AI-C-02 (좌표계 경계 — site datum 기반 전역 계층), AI-C-16 (폐쇄망 배포 경계 — 배경 타일)
관련: AI-B-04, AI-C-05, AI-N-03 (링크 품질 기반 전환), AI-O-06 (통합 상태 뷰)

## 세 층으로 본다

    도메인   college / river / facility / defense — 메인 맵이 보여 주는 것
    구역     그 도메인 안의 한 칸. AP 하나의 핸드오버 반경이 크기를 정했다.
    로봇     그 구역에서 선언되거나 탐지된 장치

도메인 이름으로 분기하는 코드는 없다(절대 준수 원칙 #3). 도메인이 늘어나면
`profiles/domains.example.json` 이 늘어나고 이 파일은 그대로다.

## 선언과 탐지를 섞지 않는다

구역에 **무엇이 있을 것인가**는 선언이고, **무엇이 실제로 있는가**는 탐지다 — 장치가
접속 직후 스스로 알리는 capability 공지가 근거다(정본 proto 의 `Capability`). 둘을
한 칸에 합치면 "선언했는데 없는 것"과 "있는데 선언에 없는 것"을 구분할 수 없고, 그
구분이 운영자가 알아야 하는 것이다.

    discovered   공지가 왔고 그 구역 선언에도 있다
    declared     선언에만 있다 — 아직 공지가 없다
    unexpected   공지는 왔는데 그 구역 선언에 없다

탐지가 "그 구역에 있다"까지 말해 주지는 않는다 — 공지는 장치 id 만 알려 준다. 화면
위 **어느 점이 어느 개체인가**는 별 문제이고 `perception/device_identity.py` 가
다룬다(외형은 종류만 말하므로 같은 기종 두 대는 외형으로 가릴 수 없다).

## 전역 좌표는 선택 계층이다

구역·장치의 자리는 **현장 로컬 좌표**(미터)다. 전역 좌표 변환은 2026-11-03 경계
개정으로 AI 소유가 됐지만(AI-C-02) 필수 계층이 아니다 — `site.datum` 이 있고 그
datum 이 검증된 현장에서만 전역 값을 유도하고, 없거나 미검증이면 **사유와 함께
거절하고 로컬 값을 유지한다**. datum 이 없는 현장은 정상 배치이므로 예시 도메인
둘에는 datum 이 없고, 그 도메인에서도 지도·구역·로봇은 그대로 돈다. 그 전역 값이
**공개 뷰 계약으로 나가는가**는 또 다른 조건이고 현장 선언이 정한다
(`site.boundary_agreement` — 아래 "전역 좌표 계층" 주석). 배경 지도 타일도 같은
성질의 선택 계층이고 기본값은 "타일 없음"이다 — 공개 타일을 기본으로 두면 폐쇄망
배치에서 메인 화면이 깨진다(AI-C-16).

## 기능 가용성을 여기서 다시 계산하지 않는다

배치의 정본은 `tools/status_ui/serve.py` 의 `StatusService.fleet()` 이다 — provider
manifest 를 노드 태그와 **누적 예산**에 맞춰 해소해 노드별로 어떤 kind 를 실제로
제공하는지까지 낸다. 이 모듈은 그 출력을 소비하고, 기능 판정은
`TaskIntent.evaluate_availability()` 에 위임한다(optional 결손은 DEGRADED 까지만 —
AI-C-05). 같은 판정을 두 곳에서 하면 두 화면이 서로 다른 답을 말한다.
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from mission_runtime.contracts.capability import CapabilityState
from mission_runtime.contracts.capability_contract import TaskIntent

#: 로봇이 그 구역에 있다고 볼 수 있는 상태.
PRESENCE_DISCOVERED = "discovered"
PRESENCE_DECLARED = "declared"
PRESENCE_UNEXPECTED = "unexpected"

#: 구역을 지금 쓸 수 있는가. 맵에서 색으로 가르는 대상이 이 값이다.
ZONE_OPERABLE = "operable"    # 탐지된 로봇이 있고 엣지도 선언되어 있다
ZONE_LIMITED = "limited"      # 탐지된 로봇은 있으나 엣지가 없다 — 원격 기능이 줄어든다
ZONE_IDLE = "idle"            # 로봇이 선언되어 있으나 아직 탐지되지 않았다
ZONE_NO_ROBOT = "no_robot"    # 로봇 선언 자체가 없다(고정 인프라만)

#: 무선 송출기의 장치 종류. 인프라 종류 이름과 같은 자리에서 쓰이므로 화면이
#: 종류별로 모양을 고를 때 이 값을 본다.
AP_KIND = "access_point"

#: 현장 선언에서 AP 자리의 실측 여부를 가리키는 항목 이름.
AP_PLACEMENT_FIELD = "ap_placement"

#: 접근 가능하다고 보는 구역 상태.
REACHABLE_STATES = frozenset({ZONE_OPERABLE, ZONE_LIMITED})

#: 구역 상태를 도메인 상태로 올릴 때의 서열. 가장 좋은 구역이 도메인을 대표한다 —
#: 평균을 내면 한 구역만 살아 있는 도메인과 전부 유휴인 도메인이 같아 보인다.
_ZONE_RANK = {ZONE_OPERABLE: 0, ZONE_LIMITED: 1, ZONE_IDLE: 2, ZONE_NO_ROBOT: 3}

_USABLE = (CapabilityState.ACTIVE.value, CapabilityState.DEGRADED.value)


class DomainProfileError(ValueError):
    """도메인·구역 선언을 읽을 수 없다."""


@dataclass(frozen=True)
class RobotFacts:
    """한 노드에 대해 **이미 해소된** 사실. 여기서 새로 계산하지 않는다."""

    node_id: str
    role: str | None = None
    label: str | None = None
    tags: tuple[str, ...] = ()
    compute_units: float | None = None
    memory_mb: float | None = None
    #: 그 노드가 실제로 제공하는 capability kind (ACTIVE/DEGRADED 인 것만).
    served_kinds: frozenset[str] = frozenset()
    #: 그 kind 를 실제로 맡은 provider. `fleet()` 의 배치 결과이고 예산 누적까지
    #: 반영된 값이다 — 서브태스크 분해가 이 배치를 다시 계산하지 않고 소비한다.
    placements: tuple[tuple[str, str], ...] = ()
    verified: bool = True

    def resources(self) -> dict:
        body: dict[str, Any] = {"tags": list(self.tags)}
        if self.compute_units is not None:
            body["compute_units"] = self.compute_units
        if self.memory_mb is not None:
            body["memory_mb"] = self.memory_mb
        return body


def facts_from_config_entry(entry: dict) -> RobotFacts:
    """조인이 만든 **설정 한 줄**을 그대로 노드 사실로 옮긴다.

    배치 결과(`served_kinds` · `placements`)는 비워 둔다 — 그것은 provider manifest 를
    노드 태그와 누적 예산에 맞춰 해소한 결과이고, 그 해소는 `StatusService.fleet()`
    한 곳이 한다. 여기서 흉내 내면 두 화면이 서로 다른 답을 말한다(CLAUDE.md §0).
    방금 들인 장치는 **기능이 아직 하나도 해소되지 않은 상태**로 보이고, 그것이
    사실이다 — 해소는 다음 기동이나 매니페스트 재해소에서 채워진다.

    implements: AI-B-09, AI-C-10, AI-C-18
    """
    budget = entry.get("budget") or {}
    return RobotFacts(
        node_id=entry["node_id"],
        role=entry.get("role"),
        label=entry.get("label"),
        tags=tuple(entry.get("tags", ())),
        compute_units=budget.get("compute_units"),
        memory_mb=budget.get("memory_mb"),
        verified=bool(entry.get("verified", False)),
    )


def robot_facts_from_fleet(fleet: dict) -> dict[str, RobotFacts]:
    """`StatusService.fleet()` 의 출력을 그대로 받아 노드별 사실로 옮긴다."""
    facts: dict[str, RobotFacts] = {}
    for node in fleet.get("nodes", []):
        budget = node.get("budget") or {}
        facts[node["node_id"]] = RobotFacts(
            node_id=node["node_id"],
            role=node.get("role"),
            label=node.get("label"),
            tags=tuple(node.get("tags", ())),
            compute_units=budget.get("compute_units"),
            memory_mb=budget.get("memory_mb"),
            served_kinds=frozenset(
                row["kind"] for row in node.get("rows", ()) if row.get("state") in _USABLE
            ),
            placements=tuple(
                (row["kind"], row["provider_id"])
                for row in node.get("rows", ())
                if row.get("state") in _USABLE and row.get("provider_id")
            ),
            verified=bool(node.get("verified", True)),
        )
    return facts


@dataclass(frozen=True)
class FunctionVerdict:
    """한 로봇에서 한 기능이 되는가. 안 되면 **무엇이 없어서**인지 함께 낸다."""

    function_id: str
    state: str
    missing_required: tuple[str, ...] = ()
    missing_optional: tuple[str, ...] = ()
    #: 로봇 자신은 못 내지만 그 구역 인프라가 메워 주는 kind — 협동이 필요한 지점이다.
    from_infrastructure: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        return self.state in _USABLE

    def as_dict(self) -> dict:
        body: dict[str, Any] = {"function_id": self.function_id, "state": self.state}
        if self.missing_required:
            body["missing_required"] = list(self.missing_required)
        if self.missing_optional:
            body["missing_optional"] = list(self.missing_optional)
        if self.from_infrastructure:
            body["from_infrastructure"] = list(self.from_infrastructure)
        return body


@dataclass
class Discovery:
    """탐지 결과. 게이트웨이가 capability 공지를 받아 채운다."""

    #: {device_id: 그 장치가 스스로 알린 action 이름들}
    actions: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: {device_id: 마지막 공지 시각}
    last_seen: dict[str, float] = field(default_factory=dict)

    def note(self, device_id: str, actions: Iterable[str], *, at: float | None = None) -> None:
        self.actions[device_id] = tuple(actions)
        self.last_seen[device_id] = time.time() if at is None else at

    def forget(self, device_id: str) -> None:
        """장치가 사라졌다. 선언은 남지만 탐지는 지워진다."""
        self.actions.pop(device_id, None)
        self.last_seen.pop(device_id, None)

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.actions))

    def age_s(self, device_id: str, *, now: float | None = None) -> float | None:
        seen = self.last_seen.get(device_id)
        if seen is None:
            return None
        return round(max(0.0, (time.time() if now is None else now) - seen), 1)


def load_domain_profile(path: str | Path) -> dict:
    """도메인·구역 선언을 읽는다. 모르는 칸은 통과시키고 필요한 칸만 본다(R12)."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("map", "domains"):
        if key not in raw:
            raise DomainProfileError(f"domain profile needs {key!r}")
    seen_zones: set[str] = set()
    for domain in raw["domains"]:
        for key in ("domain_id", "label", "rect", "space", "zones"):
            if key not in domain:
                raise DomainProfileError(f"domain entry missing {key!r}")
        for zone in domain["zones"]:
            for key in ("zone_id", "label", "rect"):
                if key not in zone:
                    raise DomainProfileError(f"zone entry missing {key!r}")
            # 구역 id 는 도메인을 가로질러 유일해야 한다 — 화면과 API 가 구역을
            # id 하나로 가리키므로, 겹치면 다른 도메인의 구역이 열린다.
            if zone["zone_id"] in seen_zones:
                raise DomainProfileError(f"duplicate zone_id across domains: {zone['zone_id']}")
            seen_zones.add(zone["zone_id"])
        # datum 과 경계 재합의 기록은 선택 칸이지만, **적혀 있으면** 여기서 읽어 본다.
        # 잘못 적힌 datum 을 조용히 통과시키면 그 사실이 전역 값을 처음 쓰는 현장에서
        # 드러나고, 반쯤 적힌 합의를 통과시키면 "누가 언제 합의했는지 모르는 합의" 가
        # 전역 숫자의 근거가 된다.
        read_site_datum(domain)
        read_boundary_agreement(domain)
    return raw


# ---------------------------------------------------------------------------
# 전역 좌표 계층 (선택) — site datum
# ---------------------------------------------------------------------------
#
# AI-C-02 는 2026-11-03 개정으로 전역 좌표 변환을 **AI 소유**로 옮겼다. 소유권만
# 옮기면 옛 경계가 막고 있던 실패("같은 사실에 authoritative 주인이 둘")가 없어지지
# 않고 자리만 바뀌므로, 같은 요구사항이 세 조건을 함께 건다. 이 구역의 코드는 그
# 셋을 그대로 옮긴 것이다.
#
#   (a) "모든 공간 값은 끝까지 자기 기준 좌표계를 들고 다니고 로컬 값과 전역 값은
#       교환 가능하지 않다" → `FleetModel.global_position()` 은 전역 값을 **자기 칸**에
#       담고 재료인 로컬 값을 `source_local` 에 따로 남긴다. 한 칸에 섞지 않는다.
#   (b) "현장 로컬↔전역 변환(site datum)은 공리가 아니라 출처와 선언된 정확도를 가진
#       근거다" → `SiteDatum` 은 출처·생성 시점·버전·정확도를 함께 읽는다. 미측정
#       정확도는 `None` 으로 남고 **그것은 0 이 아니다** — 0 으로 적으면 그 datum 으로
#       유도한 전역 값이 사람 실측보다 정확한 척하게 되므로 `accuracy_m: 0` 선언은
#       거절한다.
#   (c) "datum 이 없는 현장은 정상 상태다" → 전역 계층만 비활성이 되고 로컬 판단은
#       그대로 돈다. 비활성은 오류가 아니라 **사유가 있는 상태**다.
#
# 넷째 조건은 AI-C-02 가 아니라 AI-C-19 에서 온다 — 유도할 수 있다는 것과 공개
# 계약으로 **내보내도 된다**는 것이 다른 문제다. 그 경계는 아래 "경계 재합의 선언"
# 구역이 다루고, 판정은 `global_release()` 한 곳에서만 한다.

#: 전역 계층이 꺼진 사유. 통제 어휘 토큰이고 표시 문구가 아니다
#: (`docs/view-contract.md` §3.4 — 뷰어가 이 토큰을 자기 언어로 바꿔 그린다).
GEO_NO_DATUM = "no_datum"                   # 그 현장에 datum 선언이 없다
GEO_DATUM_UNVERIFIED = "datum_unverified"   # 있지만 실측으로 확인되지 않았다
GEO_NO_LOCAL_VALUE = "no_local_value"       # 올릴 로컬 좌표 자체가 없다
GEO_UNKNOWN_LEVEL = "unknown_level"         # 층을 쌓은 평면인데 어느 층인지 모른다

#: 전역 값을 유도할 수는 있어도 **공개 뷰 계약으로는** 내보내지 않는 사유. 위의 네
#: 토큰과 같은 어휘 자리에 있지만 묻는 것이 다르다 — 위는 "유도할 수 있는가",
#: 이 둘은 "그 숫자를 이 계약으로 내보내도 되는가" 다.
GEO_ACCURACY_UNMEASURED = "accuracy_unmeasured"        # 정확도가 미측정이다(0 이 아니다)
GEO_BOUNDARY_NOT_REAGREED = "boundary_not_reagreed"    # 경계 재합의 기록이 없다

#: 전역 계층의 두 상태. capability 의 ACTIVE/DEGRADED/DISABLED 와 **다른 축**이므로
#: 그 어휘를 빌려 쓰지 않는다 — 여기서 묻는 것은 "이 현장에서 전역 값을 유도할 수
#: 있는가" 하나다.
GEO_LAYER_ACTIVE = "active"
GEO_LAYER_DISABLED = "disabled"

#: 정확도가 어디서 왔는가. 미측정과 측정값 0 을 같은 칸에 담지 않기 위한 두 번째 축이다.
ACCURACY_UNMEASURED = "unmeasured"
ACCURACY_DECLARED = "declared"

#: 자산 뿌리(타일 묶음이 사는 자리)의 환경변수. `serve.py` 와 같은 규약이다.
ASSET_ROOT_ENV = "MISSION_RUNTIME_ASSETS"

#: 타일 레이어 종류. 벤더 열거형이 아니라 **외부 연결을 요구하는가**로 가른다(AI-C-16).
TILE_KIND_NONE = "none"
TILE_KIND_OFFLINE_PACK = "offline_pack"
TILE_KIND_REMOTE_XYZ = "remote_xyz"
#: 한 장짜리 바탕 그림 — 캠퍼스 조감도나 층 도면 같은 것. 타일 묶음과 다른 종류다:
#: 줌 단계가 없고 파일 하나이며, **앵커 두 점**이 픽셀과 현장 로컬 좌표를 잇는다.
#: 외부 연결을 요구하지 않으므로 폐쇄망에서도 그대로 돈다(AI-C-16).
TILE_KIND_STATIC_IMAGE = "static_image"

#: 그림이 선언된 자리에 없다. 없는 것은 고장이 아니라 **아직 놓지 않은 것**이고,
#: 그때 지도는 지금처럼 로컬 좌표 도면으로 그려진다(AI-C-05).
TILE_IMAGE_MISSING = "image_missing"

#: 그 레이어를 지금 쓸 수 없는 사유.
TILE_PACK_MISSING = "pack_missing"
TILE_EXTERNAL_CONNECTION_REQUIRED = "external_connection_required"


class SiteDatumError(ValueError):
    """site datum 선언을 읽을 수 없다. 거절은 사유와 함께 낸다(AI-C-02)."""


class MapTileError(ValueError):
    """배경 타일 선언을 읽을 수 없다."""


@dataclass(frozen=True)
class SiteDatum:
    """현장 로컬↔전역 기준점. **근거**이고 공리가 아니다(AI-C-02).

    `verified` 가 참이 아닌 동안 이 datum 으로는 전역 값을 유도하지 않는다 — 공개
    지도에서 받아 적은 기준점은 "그 근처"를 말할 뿐이고, 그 값을 그대로 전역 상태로
    올리면 로컬 실측보다 정확한 척하게 된다(§3 금지: "datum 이 없거나 검증되지
    않았으면 사유와 함께 거절하고 로컬 값을 유지한다").
    """

    datum_id: str
    lat: float
    lon: float
    crs: str
    verified: bool
    accuracy_m: float | None
    accuracy_basis: str
    source: dict
    version: str | None = None
    created_at: str | None = None
    #: 로컬 축이 가리키는 방위(진북 기준 시계방향 도). 실측이 아닐 수 있으므로
    #: `bearing_basis` 가 그 사실을 함께 말한다.
    x_bearing_deg: float = 90.0
    y_bearing_deg: float = 180.0
    bearing_basis: str = ACCURACY_UNMEASURED
    anchor: str = "space_origin"
    anchor_basis: str = ACCURACY_UNMEASURED
    #: 층을 로컬 y 로 쌓아 놓은 평면인가. 참이면 평면 y 는 `y - level.y_offset` 이다 —
    #: 이 보정 없이 올리면 4층이 1층보다 남쪽에 놓인다.
    level_stacked: bool = False

    @property
    def accuracy_state(self) -> str:
        """정확도가 선언된 값인가 미측정인가. 미측정은 0 이 아니다."""
        return ACCURACY_DECLARED if self.accuracy_m is not None else ACCURACY_UNMEASURED

    def metadata(self) -> dict:
        """datum 에 대해 **말할 수 있는 것**. 기준점 숫자는 들어가지 않는다.

        뷰 계약으로 나가는 블록이 이것을 그대로 싣는다. 기준점 숫자를 여기 넣지 않는
        이유는 둘이다 — 뷰어가 같은 변환을 다시 구현할 길을 열면 두 화면이 서로 다른
        전역 값을 말하고(AI-C-19), 유도된 전역 값이 나가는 조건은 datum 하나가 아니라
        `global_release()` 의 네 조건이다.
        """
        return {
            "datum_id": self.datum_id,
            "version": self.version,
            "created_at": self.created_at,
            "verified": self.verified,
            "crs": self.crs,
            "accuracy_m": self.accuracy_m,
            "accuracy_state": self.accuracy_state,
            "accuracy_basis": self.accuracy_basis,
            "source": dict(self.source),
            "local_frame": {
                "anchor": self.anchor,
                "anchor_basis": self.anchor_basis,
                "x_bearing_deg": self.x_bearing_deg,
                "y_bearing_deg": self.y_bearing_deg,
                "bearing_basis": self.bearing_basis,
                "level_stacked": self.level_stacked,
            },
        }

    def offset_to_global(self, east_m: float, north_m: float) -> tuple[float, float]:
        """기준점에서 (동, 북) 미터만큼 떨어진 점의 위경도.

        국소 접평면 근사이고 WGS84 자오선·묘유선 길이의 표준 전개식을 쓴다. 현장
        크기(수백 m)에서 이 근사의 오차는 cm 수준이지만, **그것이 datum 의 정확도를
        대신하지는 않는다** — 재료가 미측정이면 결과도 미측정이다.
        """
        phi = math.radians(self.lat)
        m_per_deg_lat = 111132.92 - 559.82 * math.cos(2 * phi) + 1.175 * math.cos(4 * phi)
        m_per_deg_lon = 111412.84 * math.cos(phi) - 93.5 * math.cos(3 * phi)
        return (self.lat + north_m / m_per_deg_lat,
                self.lon + east_m / m_per_deg_lon)

    def local_to_global(self, x: float, y: float) -> tuple[float, float]:
        """**평면** 로컬 좌표(m) 한 점을 위경도로 올린다.

        층 보정은 호출자가 이미 했다고 본다(이 객체는 어느 층인지 모른다).
        """
        bx, by = math.radians(self.x_bearing_deg), math.radians(self.y_bearing_deg)
        north = x * math.cos(bx) + y * math.cos(by)
        east = x * math.sin(bx) + y * math.sin(by)
        return self.offset_to_global(east, north)


def read_site_datum(domain: dict) -> SiteDatum | None:
    """도메인 선언에서 datum 을 읽는다. 없으면 `None` — 정상 상태다(AI-C-02).

    적혀 있으면 AI-C-02 가 요구하는 칸을 전부 본다: 기준점·출처·생성 시점·버전·
    선언된 정확도. 빠진 칸은 사유와 함께 거절한다 — 반쯤 적힌 datum 을 통과시키면
    "출처를 모르는 전역 값"이 생기고, 그것이 바로 이 요구사항이 막는 것이다.
    """
    site = domain.get("site") or {}
    raw = site.get("datum")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise SiteDatumError("site.datum must be an object")
    where = f"domain {domain.get('domain_id', '?')!r}"
    for key in ("datum_id", "reference_point", "source", "verified", "created_at", "version"):
        if key not in raw:
            raise SiteDatumError(f"{where}: site.datum needs {key!r} (AI-C-02)")
    point = raw["reference_point"]
    if not isinstance(point, dict) or "lat" not in point or "lon" not in point:
        raise SiteDatumError(f"{where}: site.datum.reference_point needs lat and lon")
    source = raw["source"]
    if not isinstance(source, dict) or not source.get("url") and not source.get("name"):
        raise SiteDatumError(
            f"{where}: site.datum.source must name where the point came from — "
            "a datum without provenance is an axiom, and AI-C-02 forbids that")

    # 정확도: 없으면 미측정이고 **0 이 아니다**. 0 이나 음수를 적는 것은 "오차가
    # 없다"는 주장이므로 거절한다 — 그 주장이 통과하면 미검증 datum 으로 유도한
    # 전역 값이 그 재료인 로컬 측정을 이긴다.
    accuracy = raw.get("accuracy_m")
    if accuracy is not None:
        accuracy = float(accuracy)
        if accuracy <= 0.0:
            raise SiteDatumError(
                f"{where}: site.datum.accuracy_m is {accuracy!r}; an unmeasured accuracy "
                "is null, not 0 (AI-C-02: \"미측정 정확도는 0 오차가 아니다\")")
    basis = raw.get("accuracy_basis") or (
        ACCURACY_DECLARED if accuracy is not None else ACCURACY_UNMEASURED)

    frame = raw.get("local_frame") or {}
    return SiteDatum(
        datum_id=str(raw["datum_id"]),
        lat=float(point["lat"]),
        lon=float(point["lon"]),
        crs=str(point.get("crs") or "EPSG:4326"),
        verified=bool(raw["verified"]),
        accuracy_m=accuracy,
        accuracy_basis=str(basis),
        source=source,
        version=raw["version"],
        created_at=raw["created_at"],
        x_bearing_deg=float(frame.get("x_bearing_deg", 90.0)),
        y_bearing_deg=float(frame.get("y_bearing_deg", 180.0)),
        bearing_basis=str(frame.get("bearing_basis") or ACCURACY_UNMEASURED),
        anchor=str(frame.get("anchor") or "space_origin"),
        anchor_basis=str(frame.get("anchor_basis") or ACCURACY_UNMEASURED),
        level_stacked=bool(frame.get("level_stacked", False)),
    )


# ---------------------------------------------------------------------------
# 경계 재합의 선언 (AI-C-19) — 전역 좌표 숫자가 뷰 계약으로 나가는 조건
# ---------------------------------------------------------------------------
#
# AI-C-02 는 소유를 AI 로 옮겼지만 같은 사실을 백엔드(BE-C-04)와 디지털 트윈(DT-03)이
# 아직 authoritative 로 적고 있고, 요구사항 자체가 "백엔드와의 경계 재합의가
# 선행되어야 한다"(AI-C-19)고 적는다. 그래서 전역 좌표 **숫자**는 그 재합의가
# **기록된 현장에서만** 공개 뷰 계약으로 나간다.
#
# 이 판정은 코드 상수가 아니라 **현장 선언**이다(`site.boundary_agreement`). 상수로
# 두면 둘 중 하나가 된다 — 거짓으로 두어 재합의가 끝난 현장에서도 숫자를 막거나,
# 참으로 올려 아직 합의하지 않은 현장에서도 내보내거나. 둘 다 사실과 다르고, 사실은
# 현장마다 다르다(재합의 기록은 그 현장의 트윈 소비자와 함께 생긴다).
#
# 선언되지 않은 현장은 **오늘과 똑같이** 동작한다 — 숫자는 나가지 않고 상태와 사유만
# 나간다. 그것이 기본값이어야 하는 이유는 AI-C-02 와 같다: 재합의되지 않은 현장은
# 오류가 아니라 정상 상태다. 그리고 없는 합의를 "있다"고 적을 길을 만들지 않기
# 위해 선언은 **누가·언제·어느 문서로** 합의했는지를 전부 요구하고, 빠지면 거절한다.

#: 재합의 선언이 가리키는 사실. 새 어휘를 만들지 않고 요구사항이 쓰는 말을 그대로
#: 쓴다 — 무엇이 재합의됐는지가 토큰에서 드러나야 추적이 끊기지 않는다.
AGREEMENT_SUBJECT_GLOBAL_COORDINATES = "global_coordinate_ownership"

#: 합의에 **반드시** 이름이 올라야 하는 파트. AI-C-19 가 선행 조건으로 적은 것은
#: AI↔백엔드 경계이므로, 둘 중 하나가 빠진 선언은 재합의가 아니다. 파트 이름은
#: 요구사항 정의서의 연관분야 어휘이고 제품·벤더 이름이 아니다.
AGREEMENT_PARTY_AI = "ai"
AGREEMENT_PARTY_BACKEND = "backend"


class BoundaryAgreementError(ValueError):
    """경계 재합의 선언을 읽을 수 없다. 거절은 사유와 함께 낸다(AI-C-19)."""


@dataclass(frozen=True)
class BoundaryAgreement:
    """"같은 사실의 주인을 하나로 정했다" 는 **기록**. 주장이 아니다.

    이 객체가 존재한다는 것은 그 현장에서 AI 가 전역 값을 authoritative 하게 낸다고
    관련 파트가 합의했고 그 합의가 문서로 남아 있다는 뜻이다. 그래서 누가·언제·어느
    문서로·무엇을 대체했는지가 전부 선언에 있어야 하고, 하나라도 없으면
    `read_boundary_agreement()` 가 거절한다 — 출처 없는 합의는 출처 없는 datum 과
    같은 종류의 공리다.
    """

    subject: str
    #: 합의한 파트들. `ai` 와 `backend` 가 반드시 들어 있다.
    agreed_by: tuple[str, ...]
    agreed_at: str
    #: 합의가 적힌 문서(이름·url·절). 전역 값의 책임을 나중에 역추적하는 출발점이다.
    document: dict
    #: 이 합의가 대체한 기록. 지금 배포에서는 `BE-C-04`·`DT-03` 이 그 대상이다.
    supersedes: tuple[str, ...] = ()
    #: 예시 현장의 선언인가. 참이면 실제 합의 기록이 아니다 — 예시 데이터가 실제
    #: 합의처럼 읽히면 이 모듈이 막으려는 것을 그대로 저지른다.
    example: bool = False
    note: str | None = None

    def metadata(self) -> dict:
        """뷰 계약으로 나가는 블록. 합의의 **사실**만 들어간다."""
        return {
            "subject": self.subject,
            "agreed_by": list(self.agreed_by),
            "agreed_at": self.agreed_at,
            "document": dict(self.document),
            "supersedes": list(self.supersedes),
            "example": self.example,
            "note": self.note,
        }


def read_boundary_agreement(domain: dict) -> BoundaryAgreement | None:
    """도메인 선언에서 경계 재합의 기록을 읽는다. 없으면 `None` — 정상 상태다.

    `None` 은 "합의하지 않았다" 이고 그때 전역 좌표 숫자는 뷰 계약으로 나가지 않는다.
    적혀 있으면 AI-C-19 가 요구하는 것을 전부 본다: 무엇에 대한 합의인지, 누가,
    언제, 어느 문서로, 어떤 기존 기록을 대체하는지. 빠진 칸은 사유와 함께 거절한다.
    """
    site = domain.get("site") or {}
    raw = site.get("boundary_agreement")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise BoundaryAgreementError("site.boundary_agreement must be an object")
    where = f"domain {domain.get('domain_id', '?')!r}"
    for key in ("subject", "agreed_by", "agreed_at", "document", "supersedes"):
        if key not in raw:
            raise BoundaryAgreementError(
                f"{where}: site.boundary_agreement needs {key!r} (AI-C-19)")

    # 아는 사실에 대한 합의만 이 문을 연다. 다른 subject 를 조용히 통과시키면 현장은
    # "적었으니 됐다" 고 믿고 우리는 "그 합의가 아니다" 로 막아, 양쪽이 서로 다른
    # 것을 본다.
    subject = str(raw["subject"])
    if subject != AGREEMENT_SUBJECT_GLOBAL_COORDINATES:
        raise BoundaryAgreementError(
            f"{where}: site.boundary_agreement.subject is {subject!r}; this gate only "
            f"knows {AGREEMENT_SUBJECT_GLOBAL_COORDINATES!r}")

    parties = tuple(str(p) for p in raw["agreed_by"])
    missing = [p for p in (AGREEMENT_PARTY_AI, AGREEMENT_PARTY_BACKEND)
               if p not in parties]
    if missing:
        raise BoundaryAgreementError(
            f"{where}: site.boundary_agreement.agreed_by does not name {missing} — "
            "AI-C-19 makes the AI↔backend re-agreement the precondition, so an "
            "agreement without both parties is not one")

    if not str(raw["agreed_at"]).strip():
        raise BoundaryAgreementError(f"{where}: site.boundary_agreement.agreed_at is empty")

    document = raw["document"]
    if not isinstance(document, dict) or not (document.get("url") or document.get("name")):
        raise BoundaryAgreementError(
            f"{where}: site.boundary_agreement.document must name where the agreement is "
            "recorded; an agreement nobody can read is a claim, not a record")

    superseded = tuple(str(s) for s in raw["supersedes"])
    if not superseded:
        raise BoundaryAgreementError(
            f"{where}: site.boundary_agreement.supersedes is empty; name the records that "
            "said otherwise (BE-C-04 · DT-03) or the hand-over cannot be traced")

    # 예시 현장의 선언은 **예시로 표시돼야** 한다. 표시 없이 통과시키면 예시 데이터가
    # 실제 합의 기록처럼 읽히고, 그것이 이 문이 막으려는 바로 그 잘못이다.
    example = bool(raw.get("example", False))
    if bool(site.get("example")) != example:
        raise BoundaryAgreementError(
            f"{where}: site.example is {bool(site.get('example'))} but "
            f"site.boundary_agreement.example is {example}; an example site may only carry "
            "an example agreement, and a real site may not carry one")

    return BoundaryAgreement(
        subject=subject,
        agreed_by=parties,
        agreed_at=str(raw["agreed_at"]),
        document=document,
        supersedes=superseded,
        example=example,
        note=raw.get("note"),
    )


def global_release(datum: SiteDatum | None,
                   agreement: BoundaryAgreement | None) -> dict:
    """전역 좌표 **숫자**가 공개 뷰 계약으로 나갈 수 있는가. 네 조건의 논리곱이다.

    datum 이 있고 · 검증됐고 · 정확도가 선언됐고 · 경계 재합의가 기록됐을 때만
    나간다. 하나라도 없으면 `released=False` 와 **무엇이 없어서인지**를 낸다 —
    "안 나간다" 만 말하면 현장이 다음에 무엇을 해야 하는지 알 수 없다.

    정확도를 조건에 넣는 이유는 AI-C-02 의 한 문장이다 — 미측정 정확도는 0 오차가
    아니다. 정확도를 모르는 채 전역 숫자를 공개 계약에 실으면 받는 쪽은 그 값의
    확신을 알 수 없고, 모르는 확신은 대개 "정확하다" 로 읽힌다.
    """
    if datum is None:
        reason: str | None = GEO_NO_DATUM
    elif not datum.verified:
        reason = GEO_DATUM_UNVERIFIED
    elif datum.accuracy_m is None:
        reason = GEO_ACCURACY_UNMEASURED
    elif agreement is None:
        reason = GEO_BOUNDARY_NOT_REAGREED
    else:
        reason = None
    return {
        "released": reason is None,
        "reason": reason,
        "agreement": agreement.metadata() if agreement is not None else None,
    }


# ---------------------------------------------------------------------------
# 배경 타일 provider 선언 (AI-C-16)
# ---------------------------------------------------------------------------


def _asset_root() -> Path | None:
    """타일 묶음이 사는 자리. `serve.py` 와 **같은 규약**을 쓴다.

    환경변수가 있으면 없는 자리라도 그대로 쓴다(조용히 다른 곳을 집으면 "왜 못
    찾느냐"를 추적할 수 없다). 없으면 개발 배치의 `../local` 이고, 그것도 없으면
    뿌리가 없다 — 없는 뿌리는 오류가 아니라 선언된 선택 조건이다.
    """
    override = os.environ.get(ASSET_ROOT_ENV)
    if override:
        return Path(override)
    # `parents[2]` 는 `mission_runtime/` 이다 — 그 **안**을 보면 자산 뿌리를 영원히
    # 못 찾는다. `local/` 은 저장소 루트에서 `mission_runtime/` 과 **나란히** 있고,
    # `serve.py::_resolve_asset_root()` 도 그 자리를 쓴다. 이 한 칸 때문에 타일
    # 묶음과 배경 그림이 늘 "없음"으로 나갔다.
    sibling = Path(__file__).resolve().parents[3] / "local"
    return sibling if sibling.is_dir() else None


def load_map_tiles(path: str | Path) -> dict:
    """배경 타일 선언을 읽는다(`config/map_tiles.example.json`).

    AI-C-16: "어떤 실행 단위가 외부 연결을 요구하는지는 등록 정보로 드러나야 하며
    폐쇄망 프로파일에서는 배치 전에 이를 검증할 수 있어야 한다." 그래서 두 가지를
    여기서 거절한다 — 외부 연결을 요구한다면서 어떤 호스트인지 적지 않은 레이어,
    그리고 `closed_network: true` 인 배치에서 **켜져 있는** 외부 레이어다. 둘 다
    배치 전에 파일만 보고 알 수 있는 잘못이고, 현장에서 발견할 이유가 없다.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if "layers" not in raw:
        raise MapTileError("map tile profile needs 'layers'")
    closed = bool(raw.get("closed_network", True))
    ids: set[str] = set()
    for layer in raw["layers"]:
        for key in ("layer_id", "kind", "requires_external_connection"):
            if key not in layer:
                raise MapTileError(f"tile layer missing {key!r}")
        layer_id = layer["layer_id"]
        if layer_id in ids:
            raise MapTileError(f"duplicate layer_id: {layer_id}")
        ids.add(layer_id)
        external = bool(layer["requires_external_connection"])
        if external and not layer.get("external_hosts"):
            raise MapTileError(
                f"layer {layer_id!r} requires an external connection but declares no "
                "external_hosts; AI-C-16 wants that requirement visible in the registration")
        if external and closed and layer.get("enabled"):
            raise MapTileError(
                f"layer {layer_id!r} needs an outbound connection and is enabled in a "
                "closed_network profile; an external provider is always optional (AI-C-16)")
        if not external and layer.get("external_hosts"):
            raise MapTileError(
                f"layer {layer_id!r} lists external_hosts but claims no external connection")
        if layer["kind"] == TILE_KIND_STATIC_IMAGE:
            _check_static_image(layer)
    default_id = raw.get("default_layer_id")
    if default_id is not None and default_id not in ids:
        raise MapTileError(f"default_layer_id {default_id!r} is not a declared layer")
    return raw


def _check_static_image(layer: dict) -> None:
    """한 장짜리 바탕 그림 선언을 읽을 수 있는지 **배치 전에** 본다.

    세 가지를 거절한다.

    * 그림의 자리와 픽셀 크기가 없는 선언 — 크기를 모르면 앵커가 어느 좌표계의
      점인지 알 수 없다.
    * 앵커가 둘 미만이거나 **한 줄 위에 있는** 경우. 픽셀↔로컬 변환은 두 점에서
      배율과 원점을 역산하는데, 두 점의 x(또는 y)가 같으면 그 축의 배율이
      0 으로 나누기가 된다. 현장에서 터질 이유가 없는 잘못이다.
    * 출처와 라이선스를 적지 않은 선언. 바탕 그림은 대개 남의 지도를 캡처한
      것이고, 그 사실이 선언에 없으면 공개 트리에 그대로 실려 나간다. 모르면
      "unknown" 이라고 **적어야** 하고 비워 두어서는 안 된다(AI-S-08 의 사전정보
      규약과 같은 이유다 — 출처 없는 자료는 출처가 없다는 사실이 남아야 한다).
    """
    layer_id = layer["layer_id"]
    image = layer.get("image") or {}
    for key in ("ref", "width_px", "height_px"):
        if not image.get(key):
            raise MapTileError(
                f"static image layer {layer_id!r} needs image.{key}")
    source = layer.get("source") or {}
    if not source.get("name") or not source.get("license"):
        raise MapTileError(
            f"static image layer {layer_id!r} must declare source.name and source.license; "
            "a captured map carries terms and an undeclared one ships silently")
    anchors = layer.get("anchors") or []
    if len(anchors) < 2:
        raise MapTileError(
            f"static image layer {layer_id!r} needs two anchors to tie pixels to "
            "local coordinates")
    for anchor in anchors:
        if not isinstance(anchor.get("pixel"), dict) or not isinstance(
                anchor.get("local"), dict):
            raise MapTileError(
                f"static image layer {layer_id!r}: every anchor needs pixel and local")
    first, second = anchors[0], anchors[1]
    for axis in ("x", "y"):
        if float(first["pixel"][axis]) == float(second["pixel"][axis]):
            raise MapTileError(
                f"static image layer {layer_id!r}: the two anchors share {axis} in pixels, "
                "so that axis has no scale")
        if float(first["local"][axis]) == float(second["local"][axis]):
            raise MapTileError(
                f"static image layer {layer_id!r}: the two anchors share {axis} locally, "
                "so that axis has no scale")


def static_image_for(declaration: dict | None, *, domain_id: str | None,
                     level_id: str | None = None,
                     zone_id: str | None = None) -> dict | None:
    """그 자리에 걸린 바탕 그림 한 장. 없으면 None 이고 그것이 기본값이다.

    **좁은 자리를 먼저** 찾는다 — 구역 도면이 있는데 층 도면을 깔면 방 하나를
    보려던 사람이 층 전체를 보고, 층 도면이 있는데 캠퍼스 조감도를 깔면 로봇이
    건물 지붕 위에 선다. 구역 → 층 → 도메인 → 현장 순으로 내려간다.

    `domain_id` 가 없으면 **현장 그림**을 찾는다. 현장 그림의 앵커는 현장 로컬
    좌표(원점 = datum)이고 도메인 로컬 좌표가 아니다 — 같은 그림을 두 프레임에서
    쓰면 둘 중 한 화면의 자리가 조용히 틀어진다(AI-C-02).

    변환 계수를 함께 낸다(`scale`·`offset`). 뷰어가 앵커 두 점에서 같은 계산을
    다시 하게 하면 두 화면이 반올림 한 자리에서 갈린다 — 계산은 한 곳에서 한다.

    implements: AI-C-02, AI-C-08, AI-C-16, AI-C-05
    """
    if not declaration:
        return None
    if not domain_id:
        wanted: list[tuple[str | None, str | None, str | None]] = [(None, None, None)]
    else:
        wanted = []
        if zone_id:
            wanted.append((domain_id, level_id, zone_id))
        if level_id:
            wanted.append((domain_id, level_id, None))
        wanted.append((domain_id, None, None))
    for want_domain, want_level, want_zone in wanted:
        for raw in declaration.get("layers", ()):
            if raw.get("kind") != TILE_KIND_STATIC_IMAGE:
                continue
            scope = raw.get("scope") or {}
            if (scope.get("domain_id") or None) != want_domain:
                continue
            if (scope.get("level_id") or None) != want_level:
                continue
            if (scope.get("zone_id") or None) != want_zone:
                continue
            return _static_image_block(raw)
    return None


def plane_of(image: dict) -> dict:
    """그림 한 장이 로컬 좌표에서 덮는 **평면**. 계수의 역이다.

    `px = local * scale + offset` 이므로 `local = (px - offset) / scale`. 지도의
    평면을 여기서 끌어내는 이유는 **핀과 그림이 한 사실에서 나와야** 하기
    때문이다 — 평면을 따로 선언해 두면 그림을 갈아 끼운 날 핀만 제자리에 남는다.
    """
    scale_x, scale_y = image["scale"]["x"], image["scale"]["y"]
    return {
        "origin": {"x": round(-image["offset"]["x"] / scale_x, 3),
                   "y": round(-image["offset"]["y"] / scale_y, 3)},
        "width": round(image["width_px"] / scale_x, 3),
        "height": round(image["height_px"] / scale_y, 3),
    }


def _static_image_block(raw: dict) -> dict:
    """선언 한 줄을 뷰 블록으로. 픽셀은 들어가지 않는다 — 참조만 나간다(AI-C-08)."""
    first, second = raw["anchors"][0], raw["anchors"][1]
    scale, offset = {}, {}
    for axis in ("x", "y"):
        d_pixel = float(second["pixel"][axis]) - float(first["pixel"][axis])
        d_local = float(second["local"][axis]) - float(first["local"][axis])
        scale[axis] = d_pixel / d_local
        offset[axis] = float(first["pixel"][axis]) - float(first["local"][axis]) * scale[axis]
    root = _asset_root()
    ref = raw["image"]["ref"]
    present = root is not None and (root / ref).is_file()
    block = {
        "layer_id": raw["layer_id"],
        "scope": dict(raw.get("scope") or {}),
        "width_px": raw["image"]["width_px"],
        "height_px": raw["image"]["height_px"],
        # 뷰어가 그대로 붙여 쓸 수 있는 참조다 — 칸 이름이 질의 인자 이름과 같아야
        # 뷰어가 둘을 번역하지 않는다(`/api/media?kind=map&file=<layer_id>`).
        "media": {"path": "/api/media", "kind": "map", "file": raw["layer_id"]},
        # 로컬 좌표 하나를 픽셀로 옮기는 계수. `px = local * scale + offset`.
        "scale": scale,
        "offset": offset,
        "source": dict(raw.get("source") or {}),
        "available": present,
    }
    if not present:
        # 자산 뿌리가 없는 노드에서도 "없다"고 말할 수 있어야 한다. 뿌리 자체가
        # 없는 것과 파일이 없는 것은 지금 구분하지 않는다 — 둘 다 그릴 수 없다.
        block["unavailable_reason"] = TILE_IMAGE_MISSING
    return block


def map_tiles_block(declaration: dict | None = None) -> dict:
    """선언을 뷰 응답 블록으로 옮긴다. **기본값은 타일 없음**이다.

    선언이 없는 배치에서도 블록은 나간다 — 칸이 아예 없으면 뷰어가 "서버가 옛
    판인가, 타일이 없는 배치인가"를 구분할 수 없다. 레이어 목록은 비고 기본 레이어는
    `none` 이며 외부 연결 요구는 거짓이다. 이것이 폐쇄망에서 전제 없이 도는 값이다
    (AI-C-16: 외부 서비스 provider 는 항상 선택 기능이다).

    표현은 들어가지 않는다 — 어떤 색으로 어떤 두께로 그릴지는 뷰어의 몫이고 여기
    나가는 것은 "어느 타일을 어디서 가져올 수 있는가" 뿐이다.
    """
    none_layer = {
        "layer_id": TILE_KIND_NONE,
        "kind": TILE_KIND_NONE,
        "enabled": True,
        "available": True,
        "requires_external_connection": False,
        "external_hosts": [],
    }
    if declaration is None:
        return {
            "declared": False,
            "default_layer_id": TILE_KIND_NONE,
            "requires_external_connection": False,
            "external_hosts": [],
            "layers": [none_layer],
        }

    root = _asset_root()
    layers: list[dict] = []
    for raw in declaration["layers"]:
        if raw.get("kind") == TILE_KIND_STATIC_IMAGE:
            # 한 장짜리 바탕 그림은 **이 블록으로 나가지 않는다.** 픽셀 크기와 그림
            # 참조는 표현에 가까운 값이고, 상태 계약에 섞이는 순간 "서버 응답에는
            # 색·픽셀·폰트가 없다" 는 경계가 무너진다(AI-C-08). 그 선언은
            # `/api/background` 로만 나가고 바이트는 `/api/media` 로만 나간다.
            continue
        layer = {k: v for k, v in raw.items() if not k.startswith("$")}
        layer.setdefault("enabled", False)
        layer.setdefault("external_hosts", [])
        kind = layer["kind"]
        if kind == TILE_KIND_OFFLINE_PACK:
            # 묶음이 실제로 그 자리에 있는가. 선언은 약속이고 이 값은 확인이다 —
            # 없는 묶음을 "있다"로 내면 폐쇄망에서 빈 배경이 뜨고 사유가 없다.
            pack = layer.get("pack_path")
            present = bool(pack) and root is not None and (root / pack).is_dir()
            layer["available"] = present
            if not present:
                layer["unavailable_reason"] = TILE_PACK_MISSING
        elif layer["requires_external_connection"]:
            # 켤 수 있는지는 배치가 정한다. 폐쇄망 선언에서는 `load_map_tiles` 가
            # 이미 켜진 것을 거절했으므로, 여기서는 "꺼져 있다"는 사실만 전한다.
            layer["available"] = bool(layer["enabled"])
            if not layer["enabled"]:
                layer["unavailable_reason"] = TILE_EXTERNAL_CONNECTION_REQUIRED
        else:
            layer["available"] = True
        layers.append(layer)

    default_id = declaration.get("default_layer_id") or TILE_KIND_NONE
    by_id = {layer["layer_id"]: layer for layer in layers}
    if default_id not in by_id:
        layers.insert(0, none_layer)
        default_id = TILE_KIND_NONE
        by_id = {layer["layer_id"]: layer for layer in layers}

    # 지금 이 배치가 외부로 나가야 하는가. **켜져 있고 쓸 수 있는** 레이어만 센다 —
    # 적혀만 있고 꺼진 레이어를 세면 폐쇄망 검증이 쓸 수 없는 답을 낸다.
    live = [layer for layer in layers if layer.get("enabled") and layer.get("available")]
    hosts = sorted({host for layer in live for host in layer.get("external_hosts", ())})
    return {
        "declared": True,
        "closed_network": bool(declaration.get("closed_network", True)),
        "default_layer_id": default_id,
        "requires_external_connection": any(
            layer["requires_external_connection"] for layer in live),
        "external_hosts": hosts,
        "layers": layers,
    }


@dataclass
class FleetModel:
    """도메인·구역·로봇·기능을 한곳에서 조립한다. 아무 상태도 바꾸지 않는다."""

    domain_profile: dict
    facts: dict[str, RobotFacts]
    #: `config/status_ui*.json` 의 functions[] 그대로.
    functions: tuple[dict, ...] = ()
    discovery: Discovery = field(default_factory=Discovery)
    #: 관제 웹에서 옮긴 고정 장치의 자리. 선언 파일을 덮어쓰지 않고 **위에 덧댄다** —
    #: 원본 선언이 무엇이었는지 잃지 않아야 수정 이력을 설명할 수 있다. 영속화는
    #: `tools/fms_console/overlay.py` 가 맡고, 여기에는 그 현재 값만 들어온다.
    placement_overrides: dict[str, dict] = field(default_factory=dict)
    #: `config/map_tiles.example.json` 선언 그대로(`load_map_tiles()` 의 출력). 없으면
    #: 배경 타일이 없는 배치다 — 그것이 기본값이고 폐쇄망에서 전제 없이 도는 값이다
    #: (AI-C-16). 배경 타일은 선택 계층이라 없어도 지도는 로컬 좌표 격자로 그려진다.
    map_tiles: dict | None = None
    _zone_index: dict[str, tuple[str, dict]] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self._reindex()

    def _reindex(self) -> None:
        self._zone_index = {
            zone["zone_id"]: (domain["domain_id"], zone)
            for domain in self.domain_profile["domains"]
            for zone in domain["zones"]
        }

    # -- 도메인 ----------------------------------------------------------

    def domain_ids(self) -> tuple[str, ...]:
        return tuple(d["domain_id"] for d in self.domain_profile["domains"])

    def domain(self, domain_id: str) -> dict:
        for domain in self.domain_profile["domains"]:
            if domain["domain_id"] == domain_id:
                return domain
        raise KeyError(domain_id)

    def domain_of(self, zone_id: str) -> str:
        return self._zone_index[zone_id][0]

    def zone_ids(self, domain_id: str | None = None) -> tuple[str, ...]:
        if domain_id is None:
            return tuple(self._zone_index)
        return tuple(z["zone_id"] for z in self.domain(domain_id)["zones"])

    def zone(self, zone_id: str) -> dict:
        try:
            return self._zone_index[zone_id][1]
        except KeyError as error:
            raise KeyError(zone_id) from error

    def domain_summary(self, domain_id: str) -> dict:
        """메인 맵의 한 칸. 커서를 올렸을 때 띄우는 내용이 이것이다."""
        domain = self.domain(domain_id)
        zone_states = [self.zone_state(z["zone_id"]) for z in domain["zones"]]
        best = min(zone_states, key=lambda s: _ZONE_RANK[s]) if zone_states else ZONE_NO_ROBOT
        declared = [d["node_id"] for z in domain["zones"] for d in z.get("declared_nodes", ())]
        discovered = [n for n in declared if n in self.discovery.actions]
        usable: set[str] = set()
        for zone in domain["zones"]:
            usable |= set(self.zone_summary(zone["zone_id"])["usable_functions"])
        return {
            "domain_id": domain_id,
            "label": domain["label"],
            "domain_profile": domain.get("domain_profile"),
            "site": self.site_view(domain_id),
            "example": bool(domain.get("site", {}).get("example")),
            # 전역 계층. datum 이 없는 도메인에서는 사유만 들어 있다 — 그것이 정상
            # 상태이고, 로컬 좌표(`rect`·`at`)는 전역 계층과 무관하게 그대로 돈다.
            "geo": self.domain_geo(domain_id),
            "rect": domain["rect"],
            # 현장 평면에서 이 도메인이 선 **점**. 현장 그림이 걸린 배치에서만
            # 뜻이 있고, 없으면 칸 자체가 없다 — 모르는 자리를 0 으로 채우면
            # 지도 왼쪽 위 구석에 건물이 하나 생긴다(AI-S-08).
            **({"site_at": self._site_at(domain)} if self._site_at(domain) else {}),
            "state": best,
            "reachable": best in REACHABLE_STATES,
            "zone_count": len(domain["zones"]),
            "level_count": len(domain.get("levels", ())),
            # 층 **이름**까지 낸다. 개수만으로는 뷰어가 층에 걸린 것(도면 같은
            # 것)을 도메인을 열기 전에 물어볼 수 없고, 못 물으면 "도면 없음" 으로
            # 보인다 — 실제로는 층에 걸려 있는데도.
            "level_ids": [l["level_id"] for l in domain.get("levels", ())],
            "declared_count": len(declared),
            "discovered_count": len(discovered),
            "reachable_zone_count": sum(1 for s in zone_states if s in REACHABLE_STATES),
            "usable_functions": sorted(usable),
            "rf": domain.get("rf", {}),
        }

    # -- 전역 좌표 계층 (선택) --------------------------------------------

    def site_datum(self, domain_id: str) -> SiteDatum | None:
        """그 현장의 datum. 없으면 `None` 이고 그것은 정상 상태다(AI-C-02)."""
        return read_site_datum(self.domain(domain_id))

    def boundary_agreement(self, domain_id: str) -> BoundaryAgreement | None:
        """그 현장의 경계 재합의 기록. 없으면 `None` 이고 그것이 기본값이다(AI-C-19)."""
        return read_boundary_agreement(self.domain(domain_id))

    def global_release(self, domain_id: str) -> dict:
        """그 현장에서 전역 좌표 숫자를 뷰 계약으로 낼 수 있는가, 못 내면 왜인가.

        판정은 여기 한 곳에서만 한다 — 같은 질문을 두 곳에서 묻게 하면 한 화면은
        숫자를 기다리고 다른 화면은 기다리지 않는다.
        """
        return global_release(self.site_datum(domain_id), self.boundary_agreement(domain_id))

    def site_view(self, domain_id: str) -> dict:
        """뷰 계약으로 나가는 `site`. 선언 전체가 아니라 말할 수 있는 것만 낸다.

        datum 과 경계 재합의 기록은 빼고 보낸다 — 둘 다 `geo` 블록이 말한다. 같은
        사실을 두 칸에 담지 않는 것이 이유다: `site.datum` 과 `geo` 가 각자 다르게
        말하면 뷰어가 어느 쪽을 믿어야 하는지 알 수 없다(AI-O-06).
        """
        hidden = ("datum", "boundary_agreement")
        site = {k: v for k, v in (self.domain(domain_id).get("site") or {}).items()
                if k not in hidden}
        return site

    def _level_offset(self, domain_id: str, level_id: str | None) -> float | None:
        for level in self.domain(domain_id).get("levels", ()):
            if level.get("level_id") == level_id:
                return float(level.get("y_offset", 0.0))
        return None

    def global_position(self, domain_id: str, at: dict | None, *,
                        level_id: str | None = None,
                        allow_unverified: bool = False) -> dict:
        """로컬 좌표 한 점을 전역으로 올린다 — 올릴 수 있을 때만.

        AI-C-02 와 §3 금지 사항이 요구하는 거절 경로가 본문의 절반이다: datum 이
        없거나 검증되지 않았으면 전역 값을 **만들지 않고** 사유를 낸다. 호출자는 그
        사유를 받아 로컬 값을 그대로 쓴다 — 거절은 장애가 아니라 선언된 상태다.

        `allow_unverified=True` 는 운영자가 "미검증 datum 이라도 대략 어디쯤인지
        보자"고 명시적으로 물을 때만 쓴다. 그때 나오는 값에는 `verified: false` 와
        `provisional: true` 가 붙고 정확도는 재료의 정확도(미측정이면 미측정)를
        그대로 물려받는다 — 재료보다 정확한 척하지 않는다.

        전역 값과 로컬 값은 **같은 칸에 담지 않는다**. 결과의 `lat`/`lon` 은 전역
        값이고, 그 재료인 로컬 좌표는 `source_local` 안에 자기 프레임과 함께 남는다.
        """
        datum = self.site_datum(domain_id)
        if datum is None:
            return {"layer": GEO_LAYER_DISABLED, "reason": GEO_NO_DATUM}
        if not datum.verified and not allow_unverified:
            return {"layer": GEO_LAYER_DISABLED, "reason": GEO_DATUM_UNVERIFIED,
                    "datum": datum.metadata()}
        if not at or "x" not in at or "y" not in at:
            return {"layer": GEO_LAYER_DISABLED, "reason": GEO_NO_LOCAL_VALUE,
                    "datum": datum.metadata()}

        planar_y = float(at["y"])
        if datum.level_stacked:
            # 층을 쌓은 평면에서는 어느 층인지 모르면 올릴 수 없다. 모르는 채로
            # 올리면 위층이 남쪽으로 밀려 **다른 건물 자리**에 놓인다.
            offset = self._level_offset(domain_id, level_id)
            if offset is None:
                return {"layer": GEO_LAYER_DISABLED, "reason": GEO_UNKNOWN_LEVEL,
                        "datum": datum.metadata()}
            planar_y -= offset

        lat, lon = datum.local_to_global(float(at["x"]), planar_y)
        space = self.domain(domain_id).get("space") or {}
        return {
            "layer": GEO_LAYER_ACTIVE,
            # 전역 값. 이 셋이 전역이라는 사실은 `crs` 가 말한다.
            "lat": round(lat, 7),
            "lon": round(lon, 7),
            "crs": datum.crs,
            # 유도한 값의 확신은 재료를 넘지 못한다(AI-C-02).
            "verified": datum.verified,
            "provisional": not datum.verified,
            "accuracy_m": datum.accuracy_m,
            "accuracy_state": datum.accuracy_state,
            "datum": datum.metadata(),
            # 재료인 로컬 값. 전역 값과 **다른 칸**이고 서로 교환 가능하지 않다.
            "source_local": {
                "x": float(at["x"]),
                "y": float(at["y"]),
                "frame": {
                    "kind": "site_local",
                    "domain_id": domain_id,
                    "level_id": level_id,
                    "unit": space.get("unit"),
                },
            },
        }

    def domain_geo(self, domain_id: str) -> dict:
        """그 도메인의 전역 계층 상태. `domain_summary()`·`domain_scene()` 이 싣는다.

        datum 이 없으면 사유만 낸다(`no_datum`) — 빈 좌표를 내지 않는다. 미검증이면
        계층은 비활성이고 사유는 `datum_unverified` 이며, datum 에 **대해** 말할 수
        있는 것(출처·버전·정확도 상태)은 함께 낸다. 기준점 숫자는 들어가지 않는다.

        전역 좌표 숫자가 이 계약으로 오는가는 `coordinates_in_view_contract` 가
        말하고, 오지 않으면 `coordinates_withheld_reason` 이 **무엇이 없어서**인지
        말한다. 둘은 `global_release()` 한 곳에서 나온다.
        """
        datum = self.site_datum(domain_id)
        release = self.global_release(domain_id)
        if datum is None:
            # 선언이 없는 현장의 블록은 사유 하나다 — 오늘과 같은 모양을 유지한다.
            return {"layer": GEO_LAYER_DISABLED, "reason": GEO_NO_DATUM}
        body: dict[str, Any] = {
            "layer": GEO_LAYER_ACTIVE if datum.verified else GEO_LAYER_DISABLED,
            "reason": None if datum.verified else GEO_DATUM_UNVERIFIED,
            "datum": datum.metadata(),
            # 뷰어가 "칸이 비었다"와 "칸이 없다"를 구분할 수 있어야 하므로 사실로
            # 적어 보낸다(§3.2). 거짓이면 사유가 함께 온다.
            "coordinates_in_view_contract": release["released"],
        }
        if not release["released"]:
            body["coordinates_withheld_reason"] = release["reason"]
        if release["agreement"] is not None:
            # 합의 기록은 **선언됐으면** 낸다 — 아직 datum 이 미검증이어서 숫자가
            # 나가지 않는 현장에서도, 무엇이 이미 되어 있고 무엇이 남았는지가 한
            # 블록에서 읽혀야 한다.
            body["boundary_agreement"] = release["agreement"]
        return body

    def global_cell(self, domain_id: str, at: dict | None, *,
                    level_id: str | None = None) -> dict | None:
        """로컬 자리 칸 **옆에** 놓는 전역 블록. 낼 수 없으면 `None` 이다.

        `None` 이면 칸이 아예 생기지 않는다 — 빈 전역 칸을 내보내면 뷰어가 그것을
        0 이나 "아직 로딩 중" 으로 읽는다(§3.2: 칸 없음과 `null` 은 다른 뜻이다).

        AI-C-02 의 마지막 문장("로컬 값과 전역 값은 같은 칸에 담지 않는다")이 이
        함수의 모양을 정했다: 로컬 숫자는 형제 칸 `at` 에 그대로 있고 여기에는 전역
        숫자와 그 **확신**(datum 의 선언된 정확도·검증 상태·판)만 들어간다. 로컬
        숫자를 여기 복사하지 않는 이유는 같은 사실의 주인을 둘로 만들지 않기
        위해서다(AI-O-06).
        """
        if not self.global_release(domain_id)["released"]:
            return None
        lifted = self.global_position(domain_id, at, level_id=level_id)
        if lifted["layer"] != GEO_LAYER_ACTIVE:
            return None   # 자리를 모르거나 층을 모른다 — 사유는 도메인 `geo` 가 말한다
        return {
            "lat": lifted["lat"],
            "lon": lifted["lon"],
            "crs": lifted["crs"],
            # 유도한 값의 확신은 재료를 넘지 못한다. 그래서 전역 칸 하나만 본
            # 소비자도 그 사실을 알 수 있게 정확도를 **이 칸에** 싣는다(AI-C-02).
            "verified": lifted["verified"],
            "accuracy_m": lifted["accuracy_m"],
            "accuracy_state": lifted["accuracy_state"],
            "datum_id": lifted["datum"]["datum_id"],
            "datum_version": lifted["datum"]["version"],
            # 어느 프레임의 값을 올린 것인가. 숫자는 들어가지 않는다 — 그것은 형제
            # 칸 `at` 의 것이다.
            "derived_from": lifted["source_local"]["frame"],
        }

    def _with_global(self, row: dict, *, domain_id: str, level_id: str | None) -> dict:
        """자리 칸이 있는 행에 전역 블록을 **덧붙인다**. 못 내면 아무것도 안 붙는다."""
        cell = self.global_cell(domain_id, row.get("at"), level_id=level_id)
        if cell is not None:
            row["at_global"] = cell
        return row

    def map_tiles_view(self) -> dict:
        """배경 타일 블록. 선언이 없으면 **타일 없음**이 기본값이다(AI-C-16)."""
        return map_tiles_block(self.map_tiles)

    # -- 자리 (선언 + 수정분) ---------------------------------------------

    def placement_of(self, device_id: str, declared_at: dict | None) -> dict | None:
        """그 장치의 현재 자리. 수정분이 있으면 그것이 이긴다."""
        override = self.placement_overrides.get(device_id)
        if override and "at" in override:
            return override["at"]
        return declared_at

    def placement_origin(self, device_id: str) -> str:
        return "operator_edit" if device_id in self.placement_overrides else "declared"

    def set_placement(self, device_id: str, at: dict, *, actor: str, reason: str = "") -> dict:
        """고정 장치의 자리를 옮긴다. 선언을 지우지 않고 덧댄 기록으로 남긴다."""
        for key in ("x", "y"):
            if key not in at:
                raise ValueError(f"placement needs {key!r}")
        entry = {
            "at": {"x": float(at["x"]), "y": float(at["y"])},
            "actor": actor,
            "reason": reason,
            "edited_at": time.time(),
        }
        self.placement_overrides[device_id] = entry
        return entry

    def clear_placement(self, device_id: str) -> None:
        """수정분을 버리고 선언된 자리로 되돌린다."""
        self.placement_overrides.pop(device_id, None)

    def access_point(self, zone_id: str) -> dict | None:
        """그 구역의 무선 송출기를 **장치 하나로** 낸다.

        라우터는 엣지 노드에 붙어 있지 않고 따로 선다. 그러면 그 자리는 실측값이고
        가상 환경에 보여야 하는 물건이며, 처음 적는 값은 거의 틀린다(실내는 AP 를
        천장 어디에 달았는지가 반경보다 구역 모양을 더 바꾼다). 그래서 다른 고정
        장치와 **같은 경로로** 사람이 옮길 수 있어야 한다.

        선언은 `zone.wifi` 한 곳에만 둔다 — 인프라 목록에 좌표를 한 번 더 적으면
        둘이 갈라지고, 어느 쪽이 참인지 말할 수 없게 된다. 여기서 만드는 것은 그
        선언에서 파생한 **보기**다.
        """
        zone = self.zone(zone_id)
        wifi = zone.get("wifi") or {}
        ap_id = wifi.get("ap_id")
        if not ap_id or not wifi.get("at"):
            return None
        row = {
            "id": ap_id, "kind": AP_KIND,
            "at": self.placement_of(ap_id, wifi["at"]),
            "at_origin": self.placement_origin(ap_id),
            "declared_at": wifi["at"],
            "rf": wifi.get("rf"),
            # 노드로 조인하지 않는 물건이다. 자원도 capability 도 없고, 없는 것을
            # 빈 칸으로 적어 "아직 안 보냈다" 로 읽히게 하지 않는다.
            "joins_as_node": ap_id in self.facts,
            # 이 자리가 실측으로 확인된 값인가. 현장이 `site.verified_fields` 에
            # `ap_placement` 를 **적었을 때만** 참이다 — 아무 말도 없는 것은 확인이
            # 아니라 침묵이고, 침묵을 확인으로 읽으면 선언값이 실측값처럼 보인다
            # (예시 도메인이 그렇게 되어 있었다).
            "placement_verified": AP_PLACEMENT_FIELD in (
                (self.domain(self.domain_of(zone_id)).get("site") or {})
                .get("verified_fields") or ()),
        }
        return self._with_global(row, domain_id=self.domain_of(zone_id),
                                 level_id=zone.get("level_id"))

    def movable_devices(self, zone_id: str) -> tuple[str, ...]:
        """자리를 옮길 수 있는 장치 — **스스로 움직이지 않는 것**만이다.

        판정 근거를 `kind == "fixed_camera"` 같은 종류 이름에 두지 않는다. 종류
        이름으로 거르면 고정 카메라만 옮길 수 있고, 같은 성질인 고정 매니퓰레이터나
        앞으로 들어올 고정 센서는 매번 이 함수를 고쳐야 한다(절대 준수 원칙 #7).
        실제 기준은 하나다 — `locomotion.*` 태그가 없으면 그 장치의 자리는 관측이
        아니라 실측값이므로 사람이 고치는 것이 맞다.

        반대로 이동형 로봇의 자리는 관측이 정하므로 끌어다 놓는 대상이 아니다. 끌 수
        있게 하면 사람이 넣은 값이 관측을 덮어써서 화면과 실제가 갈린다. 잘못된 융합
        결과를 고치는 것은 다른 일이고 그것은 객체 레코드 쪽에서 한다.
        """
        movable = []
        for item in self.zone(zone_id).get("infrastructure", ()):
            fact = self.facts.get(item["id"])
            if fact is None:
                continue  # 설정에 없는 장치의 자리를 고칠 수는 없다
            if any(tag.startswith("locomotion.") for tag in fact.tags):
                continue
            movable.append(item["id"])
        # 라우터도 스스로 움직이지 않으므로 같은 규칙에 든다. 노드로 조인하지
        # 않아 `facts` 에 없을 뿐이고, 없다는 것이 "옮기면 안 된다" 는 뜻은 아니다.
        access_point = self.access_point(zone_id)
        if access_point is not None:
            movable.append(access_point["id"])
        return tuple(movable)

    # -- capability ------------------------------------------------------

    def infrastructure_kinds(self, zone_id: str) -> frozenset[str]:
        """그 구역 고정 인프라가 제공하는 kind. 고정 카메라도 노드로 등록되어 있다."""
        kinds: set[str] = set()
        for item in self.zone(zone_id).get("infrastructure", ()):
            fact = self.facts.get(item["id"])
            if fact is not None:
                kinds |= set(fact.served_kinds)
        return frozenset(kinds)

    def infrastructure_placements(self, zone_id: str) -> tuple[tuple[str, str], ...]:
        """구역이 공급하는 (kind, provider). 어느 고정 장치가 내는지까지 남긴다."""
        rows: list[tuple[str, str]] = []
        for item in self.zone(zone_id).get("infrastructure", ()):
            fact = self.facts.get(item["id"])
            if fact is not None:
                rows.extend(fact.placements)
        return tuple(sorted(set(rows)))

    def available_kinds(self, node_id: str, *, zone_id: str | None = None) -> frozenset[str]:
        """그 로봇이 그 구역에서 쓸 수 있는 kind.

        로봇 자신이 내는 kind + 그 구역 인프라가 내는 kind + 장치가 스스로 알린
        action(AI-C-18). 장치 이름으로 분기하지 않는다.
        """
        fact = self.facts.get(node_id)
        kinds: set[str] = set(fact.served_kinds) if fact else set()
        if zone_id is not None:
            kinds |= set(self.infrastructure_kinds(zone_id))
        kinds |= {f"hardware.action.{a}" for a in self.discovery.actions.get(node_id, ())}
        return frozenset(kinds)

    def function_verdicts(self, node_id: str, *, zone_id: str | None = None
                          ) -> tuple[FunctionVerdict, ...]:
        own = self.facts[node_id].served_kinds if node_id in self.facts else frozenset()
        available = self.available_kinds(node_id, zone_id=zone_id)
        verdicts: list[FunctionVerdict] = []
        for entry in self.functions:
            required = tuple(entry.get("required_capabilities", ()))
            optional = tuple(entry.get("optional_capabilities", ()))
            intent = TaskIntent(
                required_capabilities=required, optional_capabilities=optional)
            verdicts.append(FunctionVerdict(
                function_id=entry["function_id"],
                state=intent.evaluate_availability(set(available)).value,
                missing_required=tuple(k for k in required if k not in available),
                missing_optional=tuple(k for k in optional if k not in available),
                from_infrastructure=tuple(
                    k for k in required + optional if k in available and k not in own),
            ))
        return tuple(verdicts)

    # -- 로봇 ------------------------------------------------------------

    def adopt_node(self, entry: dict, *, zone_id: str, at: dict | None = None) -> None:
        """들인 장치를 **지금 도는 배치에** 세운다. 다음 기동을 기다리지 않는다.

        조인이 받아들여지면 설정 한 줄이 나오는데, 그 줄을 사람이 파일에 붙여 넣고
        서버를 다시 띄울 때까지 그 장치는 어디에도 없었다. "형식대로 넣으면 바로
        연동" 이 되려면 그 줄이 **여기** 들어와야 한다.

        선언 프로파일을 고쳐 쓰지는 않는다 — 들인 장치는 그 구역의 선언 목록에
        덧붙고, 원래 선언이 무엇이었는지는 그대로 남는다(AI-L-03 의 같은 이유).

        implements: AI-B-09, AI-C-10, AI-C-18
        """
        node_id = entry["node_id"]
        self.facts[node_id] = facts_from_config_entry(entry)
        zone = self.zone(zone_id)
        declared = zone.setdefault("declared_nodes", [])
        if not any(d["node_id"] == node_id for d in declared):
            row = {"node_id": node_id}
            if at:
                row["at"] = at
            declared.append(row)
        # 색인은 다시 만들지 않는다. 색인이 들고 있는 것은 구역 dict **그 자체**이고
        # 위에서 그 dict 를 제자리에서 고쳤으므로 이미 반영돼 있다. 비우면 기동 때
        # 한 번 만들어지는 색인이 영영 빈 채로 남아 모든 구역이 사라진다(실제로 그랬다).

    def declared_zone_of(self, node_id: str) -> str | None:
        for zone_id, (_domain_id, zone) in self._zone_index.items():
            if any(d["node_id"] == node_id for d in zone.get("declared_nodes", ())):
                return zone_id
        return None

    def presence_of(self, node_id: str, zone_id: str) -> str:
        declared = any(d["node_id"] == node_id
                       for d in self.zone(zone_id).get("declared_nodes", ()))
        discovered = node_id in self.discovery.actions
        if discovered:
            return PRESENCE_DISCOVERED if declared else PRESENCE_UNEXPECTED
        return PRESENCE_DECLARED

    def robot(self, node_id: str, *, zone_id: str | None = None) -> dict:
        """커서를 올렸을 때 왼쪽에 띄우는 로봇 한 대의 자원과 기능."""
        if node_id not in self.facts:
            raise KeyError(node_id)
        fact = self.facts[node_id]
        zone_id = zone_id or self.declared_zone_of(node_id)
        verdicts = self.function_verdicts(node_id, zone_id=zone_id)
        return {
            "node_id": node_id,
            "zone_id": zone_id,
            "domain_id": self.domain_of(zone_id) if zone_id else None,
            "role": fact.role,
            "label": fact.label,
            "verified": fact.verified,
            "presence": self.presence_of(node_id, zone_id) if zone_id else PRESENCE_DECLARED,
            "last_seen_age_s": self.discovery.age_s(node_id),
            "announced_actions": list(self.discovery.actions.get(node_id, ())),
            "resources": fact.resources(),
            "served_kinds": sorted(fact.served_kinds),
            "infrastructure_kinds": sorted(self.infrastructure_kinds(zone_id)) if zone_id else [],
            "functions": [v.as_dict() for v in verdicts],
            "usable_functions": [v.function_id for v in verdicts if v.usable],
        }

    def _robot_marker(self, row: dict) -> dict:
        """도메인 장면에 찍히는 최소 정보. 상세는 `/api/robot` 이 낸다.

        전역 블록은 **있으면 그대로 옮긴다** — 같은 사실을 다시 계산하면 두 화면이
        서로 다른 전역 값을 말할 수 있다(AI-O-06).
        """
        marker = {
            "node_id": row["node_id"], "role": row["role"], "at": row["at"],
            "at_origin": row["at_origin"], "presence": row["presence"],
            "usable_function_count": len(row["usable_functions"]),
        }
        if "at_global" in row:
            marker["at_global"] = row["at_global"]
        return marker

    def robots_in(self, zone_id: str) -> tuple[dict, ...]:
        """그 구역의 로봇들. 선언된 것과 공지가 온 것을 합치되 상태로 가른다."""
        zone = self.zone(zone_id)
        placements: dict[str, dict | None] = {
            d["node_id"]: d.get("at") for d in zone.get("declared_nodes", ())
        }
        # 선언에 없는데 공지가 온 장치도 그 구역에 보여야 한다 — 어느 구역에도 선언되지
        # 않은 것만 여기 붙인다. 자리를 모르므로 좌표는 비운다.
        for device_id in self.discovery.ids():
            if device_id in placements or device_id not in self.facts:
                continue
            if self.declared_zone_of(device_id) is None:
                placements[device_id] = None

        rows = []
        domain_id = self.domain_of(zone_id)
        for node_id, at in placements.items():
            if node_id not in self.facts:
                continue
            row = self.robot(node_id, zone_id=zone_id)
            row["at"] = self.placement_of(node_id, at)
            row["at_origin"] = self.placement_origin(node_id)
            # 전역 블록은 **로컬 칸 옆에** 붙는다. 재합의가 기록되지 않은 현장에서는
            # 아무것도 붙지 않고 로컬 칸만 나간다 — 그것이 기본값이다(AI-C-19).
            self._with_global(row, domain_id=domain_id, level_id=zone.get("level_id"))
            rows.append(row)
        return tuple(sorted(rows, key=lambda r: r["node_id"]))

    # -- 구역 ------------------------------------------------------------

    def zone_state(self, zone_id: str) -> str:
        zone = self.zone(zone_id)
        declared = zone.get("declared_nodes", ())
        if not declared:
            return ZONE_NO_ROBOT
        discovered = [d["node_id"] for d in declared if d["node_id"] in self.discovery.actions]
        if not discovered:
            return ZONE_IDLE
        return ZONE_OPERABLE if zone.get("edge_node") else ZONE_LIMITED

    def zone_summary(self, zone_id: str) -> dict:
        """커서를 올렸을 때 띄우는 작은 팝업 하나의 내용."""
        zone = self.zone(zone_id)
        robots = self.robots_in(zone_id)
        state = self.zone_state(zone_id)
        usable: set[str] = set()
        for robot in robots:
            if robot["presence"] == PRESENCE_DECLARED:
                continue  # 아직 없는 로봇의 기능을 쓸 수 있다고 적지 않는다
            usable |= set(robot["usable_functions"])
        return {
            "zone_id": zone_id,
            "domain_id": self.domain_of(zone_id),
            "label": zone["label"],
            "level_id": zone.get("level_id"),
            "verified": zone.get("verified", True),
            "rooms": list(zone.get("rooms", ())),
            # 이름만 있는 방과 **안으로 들어갈 수 있는 방**은 다른 목록이다.
            # 한 칸에 담으면 21 개 방이 전부 열리는 것처럼 보인다.
            "interiors": [dict(r) for r in zone.get("interiors", ())],
            "state": state,
            "reachable": state in REACHABLE_STATES,
            "edge_node": zone.get("edge_node"),
            "wifi": zone.get("wifi", {}),
            "declared_count": len(zone.get("declared_nodes", ())),
            "discovered_count": sum(
                1 for r in robots if r["presence"] == PRESENCE_DISCOVERED),
            "unexpected_count": sum(
                1 for r in robots if r["presence"] == PRESENCE_UNEXPECTED),
            "infrastructure": [
                {"id": i["id"], "kind": i["kind"]} for i in zone.get("infrastructure", ())
            ],
            "usable_functions": sorted(usable),
        }

    def zone_detail(self, zone_id: str) -> dict:
        """클릭했을 때 여는 구역 상세 — 로봇과 그 자리까지."""
        zone = self.zone(zone_id)
        domain = self.domain(self.domain_of(zone_id))
        return {
            **self.zone_summary(zone_id),
            "rect": zone["rect"],
            "space": domain["space"],
            "rf": self._zone_rf(zone_id),
            "neighbours": [n for n in self.zone_neighbours(zone_id)],
            "movable_devices": list(self.movable_devices(zone_id)),
            "access_point": self.access_point(zone_id),
            "infrastructure": [
                self._with_global(
                    {**item,
                     "at": self.placement_of(item["id"], item.get("at")),
                     "at_origin": self.placement_origin(item["id"]),
                     # 선언된 자리를 함께 낸다 — 선언과 실측이 얼마나 어긋났는지가
                     # 현장 조사를 더 할지 판단하는 근거다.
                     "declared_at": item.get("at"),
                     # 설정에 없는 장치의 자원은 **칸 없이** 둔다. 빈 객체로 적으면
                     # "태그가 없는 장치" 로 읽히지만 사실은 "아직 조인하지 않아
                     # 모르는 장치" 다(칸 없음과 빈 값은 다른 뜻 — 뷰 계약 §3.2).
                     **({"resources": self.facts[item["id"]].resources()}
                        if item["id"] in self.facts else {})},
                    domain_id=domain["domain_id"], level_id=zone.get("level_id"))
                for item in zone.get("infrastructure", ())
            ],
            # 장소 지물 — 문·계단·엘리베이터. **장치가 아니다.** 지도에는 그려지고
            # 장치 목록에는 들어가지 않는다. 아무 capability 도 내지 않으므로
            # 고를 수 있는 것들과 같은 칸에 담으면 "문을 선택" 하게 된다.
            "landmarks": [
                self._with_global(
                    {**item, "at": item.get("at")},
                    domain_id=domain["domain_id"], level_id=zone.get("level_id"))
                for item in zone.get("landmarks", ())
            ],
            "robots": list(self.robots_in(zone_id)),
        }

    # -- RF·핸드오버 ------------------------------------------------------

    def _zone_rf(self, zone_id: str) -> dict:
        """그 구역 AP 의 RF 모델. 구역 크기를 정한 근거가 이 값이다."""
        zone = self.zone(zone_id)
        domain = self.domain(self.domain_of(zone_id))
        kind = (zone.get("wifi") or {}).get("rf")
        model = (domain.get("rf") or {}).get(kind, {})
        return {"kind": kind, **{k: v for k, v in model.items() if not k.startswith("$")}}

    def zone_neighbours(self, zone_id: str) -> tuple[dict, ...]:
        """맞닿은 구역과, 그 경계를 넘는 것이 **무선 전환인가**.

        같은 AP 를 공유하는 두 구역 사이의 이동은 무선 핸드오버가 아니다 — 옥외에서는
        한 AP 가 수백 m 를 덮어 구역 경계가 RF 경계와 일치하지 않는다. 그 구분을
        지우면 "구역을 넘었으니 재접속했을 것"이라는 틀린 가정이 생긴다.
        """
        zone = self.zone(zone_id)
        domain_id = self.domain_of(zone_id)
        mine = zone["rect"]
        my_ap = (zone.get("wifi") or {}).get("ap_id")
        out: list[dict] = []
        for other in self.domain(domain_id)["zones"]:
            if other["zone_id"] == zone_id:
                continue
            if other.get("level_id") != zone.get("level_id"):
                continue  # 다른 층은 맞닿은 것으로 보지 않는다 — 계단·엘리베이터는 별 경로다
            rect = other["rect"]
            touches = (
                mine["x"] <= rect["x"] + rect["w"] and rect["x"] <= mine["x"] + mine["w"]
                and mine["y"] <= rect["y"] + rect["h"] and rect["y"] <= mine["y"] + mine["h"]
            )
            if not touches:
                continue
            other_ap = (other.get("wifi") or {}).get("ap_id")
            out.append({
                "zone_id": other["zone_id"],
                "ap_id": other_ap,
                "same_ap": other_ap == my_ap,
                "radio_handover_required": other_ap != my_ap,
            })
        return tuple(sorted(out, key=lambda row: row["zone_id"]))

    # -- 맵 (렌더러에 독립적인 장면 데이터) -------------------------------

    @staticmethod
    def _site_at(domain: dict) -> dict | None:
        """도메인이 현장 평면에서 선 자리 — **선언**이고 관측이 아니다.

        `tools/profiles/locate_buildings.py` 가 공개 지도에서 받아 적는다. 그
        사실이 값과 함께 나가야 받는 쪽이 이것을 측량값으로 읽지 않는다.
        """
        declared = domain.get("site_local") or {}
        at = declared.get("at")
        if not at:
            return None
        return {"x": at["x"], "y": at["y"],
                "frame": "site-local",
                "verified": bool(declared.get("verified")),
                "basis": declared.get("basis"),
                "source": (declared.get("source") or {}).get("name")}

    def _any_site_datum(self) -> dict | None:
        """현장 평면이 기대는 datum. `site_datum(domain_id)` 과 달리 **현장
        하나**를 묻는 것이라 먼저 선언된 것을 쓴다 — 배경 그림이 그 datum 으로
        앉혀졌기 때문이다(AI-C-02)."""
        for domain_id in self.domain_ids():
            datum = (self.domain(domain_id).get("site") or {}).get("datum")
            if datum:
                return datum
        return None

    def site_image(self) -> dict | None:
        """현장 전체에 걸린 바탕 그림. 없는 것이 기본값이다(AI-C-05)."""
        return static_image_for(self.map_tiles, domain_id=None)

    def site_space(self) -> dict:
        """메인 맵의 좌표 평면.

        현장 그림이 걸려 있으면 그 그림이 덮는 **미터 평면**을 쓴다. 그러면 메인
        맵이 곧 현장 지도이고, 도메인은 그 위의 제 자리에 선다. 그림이 없으면
        지금까지와 같은 추상 격자다 — 배경 없는 현장이 정상 배치이기 때문이고,
        그 격자에서는 도메인이 자리가 아니라 **목록**으로 놓인다(AI-C-02).

        단위는 `unit` 이 말하고 프레임은 `frame` 이 말한다. 둘을 적지 않고 숫자만
        보내면 받는 쪽이 index 와 meter 를 같은 칸으로 읽는다.
        """
        image = self.site_image()
        if not image or not image.get("available"):
            return dict(self.domain_profile["map"])
        plane = plane_of(image)
        return {**plane, "unit": "meter", "frame": "site-local",
                "datum_id": (self._any_site_datum() or {}).get("datum_id"),
                "background_layer": image["layer_id"]}

    def scene(self) -> dict:
        """**메인 맵** — 도메인 목록. 그리는 쪽이 SVG 든 Unity 든 이 데이터만 읽는다.

        좌표는 현장 로컬 좌표다. 전역 좌표 변환은 2026-11-03 경계 개정으로 AI 가
        소유하지만(AI-C-02) **필수가 아닌 계층**이고, 그 상태는 도메인별 `geo` 가
        말한다 — 로컬 값과 전역 값을 같은 칸에 담지 않는다. 나중에 Unity 로 바꿀 때
        이 함수의 출력은 그대로 두고 그리는 쪽만 교체한다. 그래서 여기에는 색·픽셀·
        폰트가 없고, 배경 타일도 "어디서 가져올 수 있는가"만 있다.
        """
        return {
            "space": self.site_space(),
            "domains": [self.domain_summary(d) for d in self.domain_ids()],
            # 배경 지도는 선택 계층이다. 기본값은 타일 없음이고, 그 기본값은 외부
            # 연결을 요구하지 않는다 — 폐쇄망 배치에서 메인 화면이 깨지지 않아야
            # 하고 배치 전 검증도 이 선언을 보고 한다(AI-C-16).
            "map_tiles": self.map_tiles_view(),
        }

    def domain_scene(self, domain_id: str) -> dict:
        """도메인 하나를 열었을 때의 장면 — 그 안의 구역과 장치."""
        domain = self.domain(domain_id)
        return {
            "domain_id": domain_id,
            "label": domain["label"],
            "space": domain["space"],
            "levels": list(domain.get("levels", ())),
            "site": self.site_view(domain_id),
            # 이 현장에서 전역 계층을 쓸 수 있는가, 못 쓰면 무엇이 없어서인가.
            # datum 이 없는 현장은 `{"layer": "disabled", "reason": "no_datum"}` 하나이고
            # 그 상태에서도 아래 `zones[]` 의 로컬 좌표는 그대로 나간다(AI-C-02).
            "geo": self.domain_geo(domain_id),
            "rf": domain.get("rf", {}),
            "zones": [
                {
                    **self.zone_summary(zone["zone_id"]),
                    "rect": zone["rect"],
                    "infrastructure": [
                        self._with_global(
                            {"id": i["id"], "kind": i["kind"],
                             "at": self.placement_of(i["id"], i.get("at")),
                             "at_origin": self.placement_origin(i["id"]),
                             "pose": i.get("pose")},
                            domain_id=domain_id, level_id=zone.get("level_id"))
                        for i in zone.get("infrastructure", ())
                    ],
                    "robots": [
                        self._robot_marker(r)
                        for r in self.robots_in(zone["zone_id"])
                    ],
                }
                for zone in domain["zones"]
            ],
        }
