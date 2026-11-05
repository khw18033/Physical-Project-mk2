"""FMS console — one command serves the operations screen.

implements: AI-O-06 (통합 운영 상태 뷰), AI-C-10, AI-C-18, AI-B-12
관련: AI-C-19 (AI 는 물리 명령을 직접 소유하지 않는다), AI-C-05, AI-B-13

## 무엇이 정본인가

이 서버는 **판정을 하지 않는다**. 다른 모듈이 이미 내는 값을 모아 한 스냅샷으로 낸다.

    배치(어느 노드가 어떤 kind 를 실제로 내는가)  tools/status_ui/serve.py  StatusService.fleet()
    구역·존재·기능 가용성                          tools/fms_console/fleet.py FleetModel
    서브태스크 분해                                planning/decomposition.py  TaskDecomposer
    임무 추천                                      planning/mission_recommendation.py
    물리 명령 생애                                 execution/physical_command_gateway.py

같은 사실을 두 곳에서 계산하면 두 화면이 서로 다른 답을 말한다. 그래서 여기에는
판정이 없고 조립과 직렬화만 있다.

## 조회와 제어를 한 계약에 두지 않는다

상태 조회는 전부 GET 이고 아무것도 바꾸지 않는다(AI-O-06: 상태 뷰는 조회 전용).
바꾸는 것은 POST 뿐이고 그것은 상태 뷰가 아니라 **별도 계약**이다 — 명령 발급
(`/api/command`)과 단서 수정(`/api/correction`). 둘 다 관리자 권한에서만 받는다.
이 데모의 권한 확인은 시연용이고 운영의 실제 차단은 백엔드가 역할·범위로 한다 —
그래서 화면 문구로는 쓰지 않고 이 주석에만 남긴다.

## 맵은 데이터로 내고 그리는 쪽만 교체한다

`/api/scene` 은 좌표와 상태만 담은 장면 데이터다. 색도 픽셀도 폰트도 없다. 지금은
페이지가 인라인 SVG 로 그리고, 나중에 Unity WebGL 로 바꿀 때 이 응답은 그대로 두고
그리는 쪽만 바꾼다(AI-C-04 의 provider 경계를 화면에도 적용한 것).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from typing import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

_CONSOLE_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _CONSOLE_DIR.parents[1]

# 콘솔의 이웃 모듈(fleet·overlay·strings…)과 `tools/status_ui` 는 패키지가 아니라
# 스크립트로 싣는다 — 그래서 자리를 sys.path 에 넣어야 한다.
for _candidate in (_CONSOLE_DIR, _PROJECT_DIR / "tools" / "status_ui"):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

# `mission_runtime` 자체는 **설치되어 있으면 설치된 것을 쓴다**. 저장소를 clone 만 하고
# 설치하지 않은 사람도 바로 띄울 수 있어야 하므로 그때만 상위 디렉터리를 길에 넣는다.
# 무조건 넣으면 패키지 바깥의 남의 디렉터리가 import 경로가 되어, 설치본과 트리가
# 섞인 채로 돌 수 있다(AI-B-02: 실행 단위의 재현성).
if importlib.util.find_spec("mission_runtime") is None:
    sys.path.insert(0, str(_PROJECT_DIR.parent))

from fleet import (  # noqa: E402
    Discovery,
    FleetModel,
    PRESENCE_DISCOVERED,
    REACHABLE_STATES,
    load_domain_profile,
    load_map_tiles,
    robot_facts_from_fleet,
)
from overlay import (  # noqa: E402
    KIND_CALIBRATION,
    KIND_CUE_CORRECTION,
    KIND_GROUND_TRUTH,
    KIND_MODEL_ASSIGNMENT,
    KIND_NODE_JOIN,
    KIND_TRAINING,
    KIND_PERMISSION,
    KIND_OBJECT_POSITION,
    KIND_PLACEMENT,
    KIND_SURVEY,
    KIND_THRESHOLD,
    OperatorOverlay,
    OverlayError,
    default_overlay_path,
    state_root,
)
from accounts import (  # noqa: E402
    ALL_PERMISSIONS,
    PERM_CALIBRATE,
    PERM_COMMAND,
    PERM_CORRECT,
    PERM_DEPLOY_MODEL,
    PERM_EDIT_PLACEMENT,
    PERM_LABEL,
    PERM_MANAGE_ACCOUNTS,
    PERM_ONBOARD,
    PERM_SEE_INTERNALS,
    PERM_TRAIN,
    PERM_VIEW,
    ROLE_PERMISSIONS,
    AccountError,
    AccountStore,
    Caller,
)
from strings import LOCALES, STRINGS  # noqa: E402
from subtasks import (  # noqa: E402
    SubtaskGraphBuilder,
    load_goal_kinds,
    placement_registry,
)

from mission_runtime.contracts.profile import ResourceBudget  # noqa: E402
from mission_runtime.runtime.refresh import (  # noqa: E402
    DEFAULT_STALE_AFTER_S,
    RefreshLedger,
    Trigger,
    scope_of,
)
from mission_runtime.planning.mission_recommendation import (  # noqa: E402
    TRIGGER_ALWAYS,
    TRIGGER_IDLE_ACCELERATOR,
    TRIGGER_RISK_ELEVATED,
    TRIGGER_STALE_CALIBRATION,
    TRIGGER_UNRESOLVED_UNKNOWN,
    MissionRecommender,
    MissionTemplate,
    SituationSnapshot,
)

DEFAULT_PORT = 8800
#: 세션 토큰이 실려 오는 쿠키 이름. 질의 인자로는 받지 않는다 — 질의 문자열은 접근
#: 로그와 브라우저 이력에 남고, 거기 남은 토큰은 비밀이 아니다.
SESSION_COOKIE = "fms_session"
DEFAULT_LOCALE = "ko"

#: 뷰 계약의 버전. 별도 가시화(Unity·다른 웹)가 호환 여부를 **문서가 아니라 응답에서**
#: 확인할 수 있어야 하므로 bootstrap 에 실어 보낸다 — `docs/view-contract.md` 가 정본.
#: 2026-11-03: `role`/`capabilities` 를 `identity` 로 바꾸고 `roles` 를 능력 목록의
#: 표로 바꿨다(권한이 역할 이름이 아니라 능력이 되었다). 뷰어가 모양 변화를 응답에서
#: 알 수 있어야 하므로 **올린다** — 버전이 그대로면 옛 뷰어가 조용히 빈 칸을 그린다.
#: 2026-11-03(둘째): 전역 좌표 블록이 더해졌다 — 로컬 칸 **옆에** `at_global`,
#: 그리고 `geo` 에 보류 사유와 선언된 경계 재합의. 더하기만 했으므로 minor 다:
#: 2.0 뷰어는 새 칸을 모르는 필드로 받고 하던 대로 그린다. 두 자리(여기와
#: `schemas/view_snapshot.schema.json` 의 `x-view-contract-version`)를 **함께**
#: 올린다 — 한쪽만 올리면 서버가 내지 않는 판을 문서가 약속하게 된다.
VIEW_CONTRACT_VERSION = "2.2"

#: 공개 트리 밖의 실제 자산(모델·외형 참조 사진)이 있는 자리. 자산이 없으면 그 기능만
#: 비활성이 되고 나머지는 그대로 돈다(AI-C-05).
#:
#: 개발 저장소에서는 `mission_runtime/` 옆에 `local/` 이 있다. 그런데 그 자리를
#: `_PROJECT_DIR.parent` 로 **무조건** 적으면 패키지만 설치한 사람에게는 그것이
#: `site-packages/local` 을 가리킨다 — 남의 디렉터리를 자산 뿌리로 집는 것이다.
#: 그래서 환경변수가 없고 개발 배치의 `local/` 도 실제로 없으면 뿌리를 **없다고**
#: 둔다. 없는 뿌리는 오류가 아니라 선언된 선택 조건이고, 그 사실은
#: `/api/samples` 의 `samples_root_present` 와 기동 로그가 말한다.
ASSET_ROOT_ENV = "MISSION_RUNTIME_ASSETS"


def _resolve_asset_root() -> Path | None:
    override = os.environ.get(ASSET_ROOT_ENV)
    if override:
        # 사람이 명시한 자리는 없더라도 그대로 쓴다 — 조용히 다른 곳을 집으면
        # "왜 자산을 못 찾느냐"를 추적할 수 없다.
        return Path(override)
    sibling = _PROJECT_DIR.parent / "local"
    return sibling if sibling.is_dir() else None


_ASSET_ROOT = _resolve_asset_root()

#: 외형 참조 사진의 자리. 미디어 경로가 이 아래만 내보낸다. 뿌리가 없으면 None 이고
#: 사진 목록은 빈 목록, `/api/media` 는 404 다.
_APPEARANCE_ROOT = None if _ASSET_ROOT is None else _ASSET_ROOT / "appearance"

#: 보정판 캡처가 놓이는 자리. 장치마다 하위 디렉터리 하나다(규약 경로). 없으면
#: 보정은 선언만 받고 측정을 `not_measured` 로 남긴다 — 오류가 아니다(AI-C-05).
_CALIBRATION_FRAME_ROOT = (None if _ASSET_ROOT is None
                           else _ASSET_ROOT / "calibration")

#: 선언된 모델 버전 목록. **데이터다** — 새 모델은 코드 변경이 아니다(AI-L-10).
_MODEL_REGISTRY = _PROJECT_DIR / "config" / "model_versions.example.json"

#: 라벨할 데이터가 어디서 왔는가. **데이터다** — 새 출처는 코드 변경이 아니다.
_LABEL_SOURCES = _PROJECT_DIR / "config" / "label_sources.example.json"

#: 파일 이름 규약. 경로 탈출을 막으려면 허용 문자를 좁히는 것이 가장 확실하다.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

#: 추천할 임무들. **데이터다** — 새 임무는 코드 변경이 아니다(AI-B-15).
#: `goal_kind` 는 goal_kinds.example.json 의 키와 같은 어휘라 추천을 누르면 그대로
#: 분해로 이어진다.
MISSION_TEMPLATES: tuple[MissionTemplate, ...] = (
    MissionTemplate(
        mission_kind="close_inspection",
        title="Close inspection of an unresolved object",
        goal_kind="m2_close_inspection",
        required_capabilities=frozenset({"observation.mobile", "locomotion.ground"}),
        triggers=frozenset({TRIGGER_UNRESOLVED_UNKNOWN}),
        priority=10,
    ),
    MissionTemplate(
        mission_kind="blind_spot_fill",
        title="Fill a blind spot with a mobile view",
        goal_kind="m3_blind_spot_fill",
        required_capabilities=frozenset({"observation.mobile", "pose.self_estimate"}),
        triggers=frozenset({TRIGGER_IDLE_ACCELERATOR, TRIGGER_ALWAYS}),
        priority=40,
    ),
    MissionTemplate(
        mission_kind="twin_map_update",
        title="Refresh the digital twin map of this zone",
        goal_kind="m10_dt_map_update",
        required_capabilities=frozenset(
            {"observation.mobile", "perception.depth", "pose.self_estimate"}),
        triggers=frozenset({TRIGGER_ALWAYS}),
        priority=50,
    ),
    MissionTemplate(
        mission_kind="patrol",
        title="Patrol the zone on a planned route",
        goal_kind="m9_patrol",
        required_capabilities=frozenset({"navigation.autonomous_route", "observation.mobile"}),
        triggers=frozenset({TRIGGER_ALWAYS}),
        priority=60,
    ),
    MissionTemplate(
        mission_kind="onsite_warning",
        title="Issue an on-site warning",
        goal_kind="m8_onsite_warning",
        required_capabilities=frozenset({"signal.audio_visual", "locomotion.ground"}),
        triggers=frozenset({TRIGGER_RISK_ELEVATED}),
        priority=5,
    ),
    MissionTemplate(
        mission_kind="stale_calibration_recheck",
        title="Re-observe a camera whose calibration went stale",
        goal_kind="m1_continuous_surveillance",
        required_capabilities=frozenset({"observation.fixed"}),
        triggers=frozenset({TRIGGER_STALE_CALIBRATION}),
        priority=20,
    ),
    MissionTemplate(
        mission_kind="wide_area_search",
        title="Search a wide area from the air",
        goal_kind="m5_wide_area_search",
        required_capabilities=frozenset(
            {"locomotion.aerial", "observation.aerial", "pose.gps"}),
        triggers=frozenset({TRIGGER_ALWAYS}),
        priority=70,
    ),
)


class ApiError(Exception):
    """클라이언트가 고칠 수 있는 요청 오류. 상태 코드를 들고 다닌다."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


def _jsonable(value: Any) -> Any:
    """계약 객체를 자료로 바꾼다.

    `str(dataclass)` 로 때우지 않는다 — 그러면 뷰어가 파이썬 repr 을 파싱해야 하고,
    그 순간 뷰 계약은 "자료만 보낸다"를 지키지 못한다(docs/view-contract.md).
    """
    if hasattr(value, "as_dict"):
        return value.as_dict()
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _jsonable(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _budget_of(fact) -> ResourceBudget:
    return ResourceBudget(
        compute_units=float(fact.compute_units or 0.0),
        memory_mb=float(fact.memory_mb or 0.0),
    )


@dataclass
class FmsService:
    """화면이 묻는 것에 답한다. 순수하고, HTTP 를 모른다."""

    fleet: FleetModel
    manifest_path: Path
    goal_kinds_path: Path
    #: 선택 — 없으면 명령 탭이 "관리자 권한 필요" 가 아니라 "경로 없음"으로 정직하게 빈다.
    commander: Any | None = None
    #: 종합상황정보 구역(B~I)의 정본 조립기(`tools/status_ui` 의 `StatusService`).
    #: 콘솔은 그 스냅샷을 **그대로 옮긴다** — 같은 판정을 여기서 다시 하면 두 화면이
    #: 서로 다른 답을 말한다(CLAUDE.md §0, AI-O-06 상태 일관성). 없으면 그 끝점만
    #: "기능 없음"으로 비고 나머지 탭은 그대로 돈다(AI-C-05).
    status: Any | None = None
    evidence: Any | None = None
    #: 운영자가 고친 값의 append-only 장부. None 이면 수정이 메모리에만 남는다.
    overlay: OperatorOverlay | None = None
    #: 계정과 세션. 없으면 만들어 쓰고, 계정 파일이 없는 설치는 조회만 열린다.
    accounts: AccountStore = field(default_factory=AccountStore)
    #: 무엇을 언제 왜 반영했는지. 상시 폴링을 대신한다(AI-C-13).
    refresh: RefreshLedger = field(default_factory=RefreshLedger)
    #: 노드별 **선언된 수요** — 그 노드에 과금된 kind 들의 선언 비용 합.
    #: 판정은 `StatusService.fleet()` 이 이미 했고(kind 당 한 번, `served[kind][0]`
    #: 에 과금) 여기서는 그 결론을 옮기기만 한다. 콘솔이 같은 판정을 다시 하면 두
    #: 화면이 서로 다른 답을 말한다(CLAUDE.md §0). 측정값이 아니라 **선언값**이므로
    #: 화면도 그 사실을 적는다(AI-O-05: 미측정은 0 이 아니다).
    declared_demand: dict[str, dict] = field(default_factory=dict)
    _graphs: dict[str, SubtaskGraphBuilder] = field(default_factory=dict, init=False)
    _twin: Any | None = field(default=None, init=False)
    _radios: dict[str, Any] = field(default_factory=dict, init=False)
    _transits: dict[str, Any] = field(default_factory=dict, init=False)
    #: 임무 러너. 로봇·목표마다 하나이고 **이력을 들고 있다** — 매 요청마다 새로
    #: 만들면 재실행 회차(AI-B-12 가 "원 노드를 덮지 않고 회차를 구분해 보존")가
    #: 매번 1 로 돌아가고, 두 번째 시도가 첫 번째처럼 보인다.
    _runners: dict[str, Any] = field(default_factory=dict, init=False)
    _failures: Any | None = field(default=None, init=False)
    _appearance: Any | None = field(default=None, init=False)
    _labels: dict[str, Any] = field(default_factory=dict, init=False)
    _label_sources: tuple | None = field(default=None, init=False)
    #: 제출된 정답. 디스크에는 운영자 장부(overlay)로 남고, 여기에는 이번 세션의
    #: 레코드를 들고 있어 화면이 바로 되읽을 수 있게 한다.
    _ground_truth: dict[str, Any] = field(default_factory=dict, init=False)
    #: 배포 책상들. 쓰지 않는 탭의 비용을 미리 치르지 않으므로 전부 지연 생성이다.
    _joins: Any | None = field(default=None, init=False)
    _calibration: Any | None = field(default=None, init=False)
    _training: Any | None = field(default=None, init=False)
    _models: Any | None = field(default=None, init=False)
    #: 탐지 세부 임계값 선언과 장애물 어휘. 둘 다 **읽기 전용**이고 판정의 주인은
    #: `perception/` 쪽이다 — 콘솔은 그 답을 폼에 옮기고 결과를 세기만 한다.
    _thresholds: Any | None = field(default=None, init=False)
    _taxonomy: Any | None = field(default=None, init=False)
    #: 가상환경 대역물 해소기. 선언 카탈로그 하나를 읽어 둔다.
    _proxies: Any | None = field(default=None, init=False)
    #: 관측된 객체를 저장 자산에 묶어 **유지하는** 묶음기. 한 요청에서 만들고 버리면
    #: 묶음 회차(AI-B-12 규약)가 매번 1 로 돌아가고, 맵은 같은 자산을 옮기는 대신 매
    #: 프레임 새로 세운다 — 그것이 "이동 되도록" 의 반대다.
    _object_binder: Any | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._library, self._facts_vocabulary = load_goal_kinds(self.goal_kinds_path)
        self._recommender = MissionRecommender()
        for template in MISSION_TEMPLATES:
            self._recommender.register(template)

    # -- 그래프 빌더는 로봇마다 다르다(배치가 다르다) -----------------------

    def _graph_for(self, node_id: str) -> SubtaskGraphBuilder:
        if node_id not in self._graphs:
            fact = self.fleet.facts[node_id]
            self._graphs[node_id] = SubtaskGraphBuilder(
                library=self._library,
                registry=placement_registry(self.manifest_path, fact.placements),
                facts_vocabulary=self._facts_vocabulary,
            )
        return self._graphs[node_id]

    # -- 하위 시스템 (필요할 때 만든다 — 쓰지 않는 탭의 비용을 미리 치르지 않는다) --

    def twin(self):
        """다중 장치 융합·추적·정정. 장치 배치를 선언에서 한 번 등록한다."""
        if self._twin is None:
            from twin import DevicePlacement, TwinFusionService  # noqa: PLC0415

            service = TwinFusionService(registry_for=self._observer_registry)
            for zone_id in self.fleet.zone_ids():
                zone = self.fleet.zone(zone_id)
                for item in zone.get("infrastructure", ()):
                    at = self.fleet.placement_of(item["id"], item.get("at"))
                    if at is None:
                        continue
                    pose = item.get("pose") or {}
                    service.register_device(DevicePlacement(
                        device_id=item["id"], zone_id=zone_id,
                        pose=(float(at["x"]), float(at["y"]),
                              float(pose.get("yaw_deg", 0.0))),
                        camera_id=item["id"] if item.get("kind") == "fixed_camera" else None,
                    ))
                # 이동형 로봇도 관측자다. 고정 인프라만 등록하면 "로봇이 본 것"이
                # 융합에 들어갈 자리가 없어 다중 장치 융합이 고정 카메라끼리로 좁아진다.
                # 로봇의 자리는 관측이 정하므로 pose_source 를 구분해 둔다.
                for robot in self.fleet.robots_in(zone_id):
                    at = robot.get("at")
                    if at is None:
                        continue
                    service.register_device(DevicePlacement(
                        device_id=robot["node_id"], zone_id=zone_id,
                        pose=(float(at["x"]), float(at["y"]), 0.0),
                        pose_source=robot.get("at_origin") or "declared",
                        available=robot["presence"] == PRESENCE_DISCOVERED,
                    ))
            self._twin = service
        return self._twin

    def _observer_registry(self, device_id: str):
        """그 관측 장치에 **실제로 배치된** provider 들의 레지스트리.

        배치 판정을 여기서 다시 하지 않는다 — 선언된 manifest 전체를 주면 노드 상태
        화면("이 노드에서는 못 한다")과 승격 화면("된다")이 서로 다른 답을 말한다.
        `placement_registry` 가 그 이유를 적는 자리이고 정본은 `fleet()` 하나다.
        배치 사실이 없는 장치(고정 인프라 등)는 `None` 이고, 그때 부족분은 요청으로도
        가지 않고 사유만 남는다(AI-C-05).
        """
        try:
            fact = self.fleet.facts[device_id]
        except KeyError:
            return None
        return placement_registry(self.manifest_path, fact.placements)

    def radio(self, domain_id: str):
        if domain_id not in self._radios:
            from handover import ZoneRadioMap  # noqa: PLC0415

            self._radios[domain_id] = ZoneRadioMap(self.fleet, domain_id)
        return self._radios[domain_id]

    def transit(self, node_id: str):
        """로봇 한 대의 구역 이동 런타임. 로봇마다 자기 이력을 가진다."""
        if node_id not in self._transits:
            from handover import ZoneTransitRuntime  # noqa: PLC0415

            zone_id = self.fleet.declared_zone_of(node_id)
            if zone_id is None:
                raise ApiError(400, "robot_has_no_declared_zone")
            self._transits[node_id] = ZoneTransitRuntime(
                radio=self.radio(self.fleet.domain_of(zone_id)))
        return self._transits[node_id]

    def mission_runner(self, node_id: str, goal_kind: str, *, caller: Caller):
        """그 로봇·그 목표의 임무 러너. 같은 쌍이면 같은 러너다.

        계획(`plan`)과 실행(`run`)이 같은 객체를 쓰는 것이 요점이다 — 러너가
        구역별 시도 이력을 들고 있고, 재실행은 원 기록을 덮지 않고 회차를
        올린다(AI-B-12).

        implements: AI-B-12
        """
        from mission import ZoneMissionRunner  # noqa: PLC0415

        key = f"{node_id}:{goal_kind}"
        if key not in self._runners:
            fact = self.fleet.facts[node_id]
            self._runners[key] = ZoneMissionRunner(
                transit=self.transit(node_id),
                library=self._library,
                registry=placement_registry(self.manifest_path, fact.placements),
                budget=_budget_of(fact),
                node_tags=frozenset(fact.tags),
                known_facts_fn=lambda zone: self.known_facts(zone, caller=caller),
            )
        return self._runners[key]

    def proxies(self):
        """가상환경 대역물 해소기. 카탈로그가 없으면 **비활성이고 오류가 아니다**.

        화면이 로봇과 객체를 "비슷한 물건" 으로 그리려면 무엇으로 그릴지를 누군가
        정해야 한다. 그 선택은 선언 카탈로그(`config/object_models.example.json`)가
        가지고, 여기서는 그것을 읽어 두기만 한다 — 콘솔이 다시 고르면 같은 객체가
        두 화면에서 다른 모양이 된다.

        `require_asset_file=False` 인 이유: 자산 파일은 공개 트리 밖에 있고 대부분의
        노드에 없다. 파일이 없다고 대역을 **지우면** 화면이 "이 종류는 그릴 것이
        없다" 로 읽지만 사실은 "그릴 것은 정해졌고 파일만 아직 없다" 이다. 둘은
        다른 상태이므로 대역은 남기고 `asset_present` 로 사실을 적는다.

        implements: AI-S-06, AI-C-05, AI-C-08, AI-C-15
        """
        if self._proxies is None:
            from mission_runtime.perception.object_appearance import (  # noqa: PLC0415
                ProxyCatalog,
                ProxyResolver,
            )

            path = _PROJECT_DIR / "config" / "object_models.example.json"
            self._proxies = ProxyResolver(
                catalog=ProxyCatalog.load(path), asset_root=_ASSET_ROOT,
                require_asset_file=False)
        return self._proxies

    def _proxy_for(self, subject_id: str, *, tags, at, frame_id: str,
                   source: str, role: str = ""):
        """선언된 태그로 대역을 고른다. 고르는 **규칙은 카탈로그의 것**을 쓴다.

        한 장치가 여러 태그를 선언한다(`locomotion.legged` 와 `tier.ugv` 를 함께).
        어느 태그가 더 구체적인가를 여기서 새로 정하면 그것이 두 번째 규칙이 되므로,
        태그마다 후보를 모아 **카탈로그가 이미 선언한 우선순위**로 고른다.

        고른 것은 **종류**이지 개체가 아니다(AI-C-19) — 선언에서 온 근거이므로 격은
        `declared` 이고 확신은 미측정이다.
        """
        from mission_runtime.perception.object_appearance import (  # noqa: PLC0415
            declared_kind_claim,
            local_placement,
            unknown_placement,
        )

        resolver = self.proxies()
        best_tag, best_key = None, None
        for tag in sorted(tags or ()):
            for asset in resolver.catalog.for_kind(tag):
                key = (asset.priority, asset.proxy_id)
                if best_key is None or key < best_key:
                    best_tag, best_key = tag, key
                break
        claim = declared_kind_claim(best_tag or role or "", source=source,
                                    observed_at=0.0) if (best_tag or role) else None
        placement = (local_placement((float(at["x"]), float(at["y"])), frame_id=frame_id)
                     if at else unknown_placement(frame_id=frame_id))
        if claim is None:
            from mission_runtime.perception.object_appearance import (  # noqa: PLC0415
                KindClaim,
            )

            claim = KindClaim(kind=None, reason="no_declared_kind")
        return resolver.resolve(subject_id, claim, placement=placement).as_dict()

    def appearance(self):
        """외형 분류기. 사전·모델이 없으면 **비활성이고 오류가 아니다**(AI-C-05)."""
        if self._appearance is None:
            from mission_runtime.perception.appearance_classifier import (  # noqa: PLC0415
                AppearanceClassifier,
            )

            # 자산 뿌리가 없으면 모델 자리도 없다. `from_files` 는 없는 자리를
            # `available=False` + 사유로 환산하므로 여기서 판정하지 않는다.
            model_dir = (None if _ASSET_ROOT is None
                         else _ASSET_ROOT / "models" / "openvocab" / "clip-vit-base-patch32")
            self._appearance = AppearanceClassifier.from_files(
                _PROJECT_DIR / "config" / "device_appearance_classes.example.json",
                model_dir=model_dir)
        return self._appearance

    def _label_detector(self, vocabulary: list[str]):
        """열린 어휘 탐지기. 가중치가 없으면 None 이고 사람이 처음부터 그린다."""
        from mission_runtime.edge.yolo_world_provider import (  # noqa: PLC0415
            YoloWorldPerceptionProvider,
        )

        if _ASSET_ROOT is None:
            return None
        weights = _ASSET_ROOT / "weights" / "yolo" / "yolov8s-worldv2.pt"
        if not weights.exists():
            return None
        return YoloWorldPerceptionProvider(vocabulary, weights, device="cpu")

    def label_sources(self) -> tuple:
        """선언된 출처들. 자산 뿌리가 없으면 빈 묶음이고 오류가 아니다(AI-C-05)."""
        if self._label_sources is None:
            from labeling import label_sources_from_dict  # noqa: PLC0415

            if not _LABEL_SOURCES.exists():
                self._label_sources = ()
            else:
                self._label_sources = label_sources_from_dict(
                    json.loads(_LABEL_SOURCES.read_text(encoding="utf-8")))
        return self._label_sources

    def labels(self, source_id: str | None = None):
        """출처 하나에 매인 라벨 작업 묶음. 프레임이 없으면 빈 목록이고 오류가 아니다.

        출처마다 따로 세우는 이유: 탐지기는 하나지만 **주체가 다르다**. 한 객체를
        돌려쓰면 공개 데이터셋 사진의 정답이 직전에 쓰던 기기의 후보로 들어간다.
        """
        from labeling import FrameLabelSource  # noqa: PLC0415

        sources = {s.source_id: s for s in self.label_sources()}
        if source_id is None:
            source_id = next(iter(sources), None)
        if source_id is not None and source_id not in sources:
            raise ApiError(404, "unknown_label_source")
        if source_id is None:
            # 선언된 출처가 하나도 없는 배치. 빈 묶음을 내되 모양은 같게 둔다.
            return FrameLabelSource(frame_root=None, device_id="",
                                    detector_factory=self._label_detector)
        if source_id not in self._labels:
            source = sources[source_id]
            root = None if _ASSET_ROOT is None else _ASSET_ROOT / source.path
            self._labels[source_id] = FrameLabelSource(
                frame_root=root, source=source,
                device_id=source.device_id or source.subject_id,
                zone_id=(self.fleet.declared_zone_of(source.device_id)
                         if source.device_id else None),
                detector_factory=self._label_detector)
        return self._labels[source_id]

    def failures(self):
        if self._failures is None:
            from mission_runtime.observability.failure_trace import (  # noqa: PLC0415
                FailureTraceService,
            )

            # reader 없이 만든다 — 관측 백엔드가 없는 노드에서도 모듈이 돌고,
            # 그 사실이 "정상"이 아니라 "미측정"으로 나온다(AI-O-05).
            self._failures = FailureTraceService()
        return self._failures

    # -- 배포 책상 (들이기·보정·학습·모델) ---------------------------------

    def joins(self):
        """조인 선언을 받는 책상. 이미 아는 장치 id 를 넣어 중복 조인을 막는다."""
        if self._joins is None:
            from deployment import JoinDesk  # noqa: PLC0415
            from mission_runtime.registry.onboarding import NodeOnboarding  # noqa: PLC0415

            self._joins = JoinDesk(onboarding=NodeOnboarding(
                known_device_ids=set(self.fleet.facts)))
        return self._joins

    def calibration(self):
        """카메라별 보정 계보. 캡처 뿌리가 없으면 선언만 받는다(AI-C-05)."""
        if self._calibration is None:
            from deployment import CalibrationDesk  # noqa: PLC0415

            self._calibration = CalibrationDesk(frames_root=_CALIBRATION_FRAME_ROOT)
        return self._calibration

    def training(self):
        """학습 책상. 후보 보관소는 **트윈의 것**을 그대로 읽는다(복사하지 않는다)."""
        if self._training is None:
            from deployment import SampleLineageView, TrainingDesk  # noqa: PLC0415

            self._training = TrainingDesk(store=self.twin().candidate_store,
                                          sample_lineages=SampleLineageView(self.twin()))
        return self._training

    def models(self):
        """모델 배정·배포. 선언 파일이 없으면 후보 0 개이고 오류가 아니다."""
        if self._models is None:
            from deployment import (  # noqa: PLC0415
                ModelDesk,
                device_profile_from_facts,
                local_pipeline,
                model_versions_from_dict,
            )

            versions = ()
            if _MODEL_REGISTRY.exists():
                versions = model_versions_from_dict(
                    json.loads(_MODEL_REGISTRY.read_text(encoding="utf-8")))
            profiles = {
                node_id: device_profile_from_facts(node_id, facts)
                for node_id, facts in self.fleet.facts.items()
            }
            self._models = ModelDesk(pipeline=local_pipeline(versions=versions),
                                     device_profiles=profiles)
        return self._models

    # -- 세계 사실 ---------------------------------------------------------

    def known_facts(self, zone_id: str | None, *, caller: Caller) -> dict[str, bool]:
        """분해기에 넘길 사실. **아는 것만** 넣는다 — 모르는 것을 참으로 채우면
        막혀야 할 단계가 통과한 것처럼 보인다(decomposition.py 의 규칙과 같다).
        """
        facts: dict[str, bool] = {}
        if zone_id is None:
            return facts
        zone = self.fleet.zone(zone_id)
        if self.fleet.zone_state(zone_id) in REACHABLE_STATES:
            facts["zone_reachable"] = True
        if zone.get("edge_node"):
            facts["edge_available"] = True
        if any(item.get("calibration") for item in zone.get("infrastructure", ())):
            facts["calibration_valid"] = True
        if caller.may(PERM_COMMAND):
            facts["operator_present"] = True
        return facts

    # -- 조회 --------------------------------------------------------------

    def bootstrap(self, *, caller: Caller, locale: str) -> dict:
        return {
            # 별도 가시화가 호환 여부를 응답에서 확인할 수 있어야 한다. 문서에만 적혀
            # 있으면 버전이 어긋난 뷰어가 조용히 틀린 화면을 그린다.
            "view_contract_version": VIEW_CONTRACT_VERSION,
            # 언제부터 오래된 것으로 볼지를 뷰어마다 따로 정하면 같은 값이 한 화면에서는
            # 신선하고 다른 화면에서는 오래된 것이 된다. 경계는 서버가 말한다.
            "freshness": {
                "stale_after_s": {
                    "default": self.refresh.stale_after_s,
                    "discovery": DEFAULT_STALE_AFTER_S,
                },
                "states": ["never", "fresh", "stale"],
            },
            "locale": locale,
            "locales": list(LOCALES),
            "strings": STRINGS[locale],
            # 화면은 "내가 누구이고 무엇을 할 수 있는가" 만 알면 된다. 역할 이름으로
            # 분기하지 않으므로 능력 목록이 그 답이다.
            "identity": caller.as_dict(),
            "roles": {name: sorted(perms) for name, perms in ROLE_PERMISSIONS.items()},
            "commanding_available": self.commander is not None,
            # 추론 근거를 실제로 낼 수 있는지는 **분류기에게 물어서** 적는다. 여기서
            # 다른 값을 적으면 뷰어가 멀쩡한 탭을 비활성으로 그리거나 그 반대가 된다.
            "evidence_available": self.appearance().available,
            "evidence_reason": self.appearance().unavailable_reason or None,
            # 메인 맵은 도메인 목록이다. 구역은 도메인을 열 때 받는다 — 전부 미리
            # 내려보내면 층이 여러 개인 도메인에서 쓰지 않는 구역까지 실린다.
            "scene": self.fleet.scene(),
            "domains": [self.fleet.domain_summary(d) for d in self.fleet.domain_ids()],
            "functions": [entry["function_id"] for entry in self.fleet.functions],
            "facts_vocabulary": dict(self._facts_vocabulary),
        }

    def scene(self) -> dict:
        return self.fleet.scene()

    def domain(self, domain_id: str) -> dict:
        try:
            return self.fleet.domain_scene(domain_id)
        except KeyError as error:
            raise ApiError(404, "unknown_domain") from error

    def zone(self, zone_id: str) -> dict:
        try:
            detail = self.fleet.zone_detail(zone_id)
        except KeyError as error:
            raise ApiError(404, "unknown_zone") from error
        self._with_reported_position(detail)
        # 관측된 객체를 **무엇으로 어디에 세울지**. 로봇·인프라는 선언에서 오고(위
        # `robots`·`infrastructure`) 이 칸은 **인지가 만든** 객체다 — 둘을 한 목록에
        # 담으면 선언된 것과 관측된 것이 구분되지 않는다. 비어 있는 것이 정상이다:
        # 아직 아무 장치도 보고하지 않은 구역은 빈 목록이고 0 개가 아니라 '없음'이다.
        detail["object_placements"] = self.object_placements(zone_id)
        return detail

    #: 트윈이 들고 있는 자세가 **선언에서 온 것**임을 말하는 출처 토큰. 이 값으로
    #: 등록된 자세는 관측이 아니라 선언을 되읽은 것이고(위 `twin()` 이 선언된 자리로
    #: 장치를 등록한다) 그것을 관측으로 적으면 아무도 본 적 없는 자리가 "장치가 알린
    #: 자리" 가 된다.
    _DECLARED_POSE_SOURCES: frozenset[str] = frozenset({"declared", "operator_edit"})

    def _with_reported_position(self, detail: dict) -> None:
        """로봇의 자리를 **관측이 있으면 관측으로** 바꾸고 그 출처를 적는다.

        선언된 자리는 "있을 것이라고 적어 둔 곳" 이고 로봇이 움직이면 그 순간부터
        거짓이 된다. 장치가 알린 자리가 있으면 그것이 이긴다.

        닿지 않게 된 로봇은 **자리를 지우지 않는다.** 마지막으로 알린 곳에 그대로
        둔다 — 사라진 로봇을 지도에서 지우면 "어디서 잃어버렸는가" 를 아무도 모르게
        되고, 선언된 자리로 되돌리면 지금 거기 있는 것처럼 보인다. 둘 다 틀렸고,
        마지막으로 본 자리가 맞다.

        ## 세 가지는 서로 다른 축이고 한 칸에 담지 않는다 (2026-11-04 수정)

        이 함수는 전에 `at_origin` 에 네 값(`declared`·`operator_edit`·`reported`·
        `last_seen`)을 적었다. 그 칸은 **선언의 출처**를 말하는 닫힌 어휘인데
        (`schemas/view_snapshot.schema.json` 의 `$defs/at_origin`: `declared` ·
        `operator_edit`) 거기에 "관측이냐 선언이냐" 와 "지금 살아 있냐" 가 함께
        들어가 있었다. 셋을 가른다.

        1. `at_origin` — **선언**이 어디서 왔는가(선언 프로파일 / 사람의 수정).
           관측이 들어와도 바뀌지 않는다. 그 선언은 사라지지 않았다.
        2. `position_source` — 지금 `at` 에 있는 값을 **무엇이 만들었는가**(열린
           어휘, 트윈의 `pose_source` 그대로). 칸이 없으면 `at` 은 선언값이다(§3.2).
        3. 살아 있는가 — `presence` 와 `last_seen_age_s` 가 이미 말한다. 옛
           `reported`/`last_seen` 은 `presence == discovered` 를 그대로 뒤집어 적은
           **파생값**이어서 지우면 잃는 것이 없다.

        그래서 선언에서 온 트윈 자세로는 `at` 을 덮지 않는다 — 같은 값을 되쓰면서
        출처만 "관측" 으로 바꾸는 것이 옛 코드의 조용한 거짓이었다.

        implements: AI-S-06, AI-O-04, AI-C-02
        """
        twin = self._twin
        if twin is None:
            return
        for robot in detail.get("robots", ()):
            placement = twin.placement_of(robot["node_id"])
            if placement is None or not getattr(placement, "pose", None):
                continue
            source = str(getattr(placement, "pose_source", "") or "")
            if source in self._DECLARED_POSE_SOURCES or not source:
                # 선언을 되읽은 자세다. 선언값은 이미 `at` 에 있고 출처도 `at_origin`
                # 이 말한다 — 관측이 없는데 관측 칸을 채우지 않는다.
                continue
            x, y = placement.pose[0], placement.pose[1]
            robot["at"] = {"x": round(float(x), 3), "y": round(float(y), 3)}
            robot["position_source"] = source

    def placement(self, *, caller: Caller, body: dict) -> dict:
        """고정 장치의 자리를 고친다. 상태 조회가 아니라 **별도 계약**이다.

        이동형 로봇은 대상이 아니다 — 그 자리는 관측이 정하고, 사람이 끌어다 놓은
        값이 관측을 덮으면 화면과 실제가 갈린다. 고친 값도 선언을 지우지 않고 위에
        덧대어, 원래 선언이 무엇이었는지 남는다.
        """
        if not caller.may(PERM_EDIT_PLACEMENT):
            raise ApiError(403, f"missing_permission:{PERM_EDIT_PLACEMENT}")
        device_id = body.get("device_id") or ""
        zone_id = body.get("zone_id") or ""
        if not device_id or not zone_id:
            raise ApiError(400, "device_and_zone_required")
        try:
            movable = self.fleet.movable_devices(zone_id)
        except KeyError as error:
            raise ApiError(404, "unknown_zone") from error
        if device_id not in movable:
            raise ApiError(400, "device_not_movable")
        reason = str(body.get("reason") or "")
        if body.get("reset"):
            self.fleet.clear_placement(device_id)
            if self.overlay is not None:
                # 되돌림도 삭제가 아니라 기록이다 — 무엇을 되돌렸는지 남아야 한다.
                self.overlay.reset(KIND_PLACEMENT, device_id, actor=caller.actor,
                                   reason=reason, scope=zone_id)
            return {"device_id": device_id, "at_origin": "declared",
                    "history": self._placement_history(device_id)}
        at = body.get("at") or {}
        try:
            entry = self.fleet.set_placement(device_id, at, actor=caller.actor, reason=reason)
        except (KeyError, TypeError, ValueError) as error:
            raise ApiError(400, "bad_placement") from error
        if self.overlay is not None:
            self.overlay.record(KIND_PLACEMENT, device_id, {"at": entry["at"]},
                                actor=caller.actor, reason=reason, scope=zone_id)
        return {"device_id": device_id, "at_origin": "operator_edit", **entry,
                "history": self._placement_history(device_id)}

    def _placement_history(self, device_id: str) -> list[dict]:
        if self.overlay is None:
            return []
        return list(self.overlay.history(KIND_PLACEMENT, device_id))

    def survey(self, *, caller: Caller, body: dict) -> dict:
        """사람이 줄자로 잰 값 같은 공간 실측값을 받는다.

        센서 추정과 **같은 칸에 담지 않는다** — 사람이 잰 값은 출처와 작성자가 있는
        다른 종류의 근거이고, 융합 뒤에도 구분되어야 한다(AI-S-08, AI-L-03).
        """
        if not caller.may(PERM_EDIT_PLACEMENT):
            raise ApiError(403, f"missing_permission:{PERM_EDIT_PLACEMENT}")
        if self.overlay is None:
            raise ApiError(503, "no_overlay_path")
        quantity_id = body.get("quantity_id") or ""
        zone_id = body.get("zone_id") or ""
        if not quantity_id or not zone_id:
            raise ApiError(400, "quantity_and_zone_required")
        if "value" not in body:
            raise ApiError(400, "value_required")
        try:
            self.fleet.zone(zone_id)
        except KeyError as error:
            raise ApiError(404, "unknown_zone") from error
        payload = {"value": body["value"], "unit": body.get("unit"),
                   "accuracy_m": body.get("accuracy_m")}
        entry = self.overlay.record(
            KIND_SURVEY, f"{zone_id}/{quantity_id}",
            {k: v for k, v in payload.items() if v is not None},
            actor=caller.actor, reason=str(body.get("reason") or ""), scope=zone_id)
        return {"target_id": entry.target_id, "recorded": entry.as_dict()}

    def overlay_log(self, *, kind: str | None, target_id: str | None) -> dict:
        """무엇을 누가 언제 왜 고쳤는지. 개발자 화면이 원인을 되짚는 입구다."""
        if self.overlay is None:
            return {"available": False, "entries": [], "stats": None}
        try:
            entries = [e.as_dict() for e in self.overlay.entries(kind, target_id)]
        except OverlayError as error:
            raise ApiError(400, str(error)) from error
        return {"available": True, "entries": entries, "stats": self.overlay.stats()}

    def robot(self, node_id: str, zone_id: str | None, *, caller: Caller) -> dict:
        try:
            body = self.fleet.robot(node_id, zone_id=zone_id)
        except KeyError as error:
            raise ApiError(404, "unknown_robot") from error
        # 경과만 주면 뷰어가 자기 시계로 절대 시각을 되만들어야 하고, 시계가 어긋나면
        # 그 계산이 틀린다. 절대 시각을 함께 낸다(둘 다 없을 수 있다 — 미수신).
        body["last_received_at"] = self.fleet.discovery.last_seen.get(node_id)
        # 선언된 예산 옆에 **그 예산에 얹힌 선언 수요**를 둔다. 예산만 보여 주면
        # "6 유닛" 이 여유인지 포화인지 알 수 없고, 측정값처럼 보여 주면 거짓이 된다.
        # 수요가 없는 노드는 빈 칸이 아니라 0 개 기능이라는 사실을 말한다.
        body["declared_demand"] = dict(self.declared_demand.get(node_id, {}))
        body["recommendations"] = self.recommend(node_id, body["zone_id"], caller=caller)
        if self.commander is not None:
            body["command_vocabulary"] = list(
                self.commander.vocabulary(node_id))
        return body

    def recommend(self, node_id: str, zone_id: str | None, *, caller: Caller) -> list[dict]:
        """지금 이 로봇·구역에서 권할 임무. 상황은 다른 모듈이 낸 값만 쓴다."""
        if node_id not in self.fleet.facts:
            raise ApiError(404, "unknown_robot")
        available = self.fleet.available_kinds(node_id, zone_id=zone_id)
        situation = SituationSnapshot(
            available_capabilities=frozenset(available),
            # 아직 의미가 확정되지 않은 객체·유휴 가속기·위험 수준은 각각 다른 모듈이
            # 내는 값이다. 그 모듈이 붙기 전에는 **비워 둔다** — 지어내면 추천이
            # 거짓 근거로 올라온다.
            stale_calibration_camera_ids=tuple(
                item["id"]
                for item in (self.fleet.zone(zone_id).get("infrastructure", ())
                             if zone_id else ())
                if item.get("kind") == "fixed_camera" and not item.get("calibration")
            ),
        )
        rows = []
        for candidate in self._recommender.recommend(situation):
            rows.append({
                "mission_kind": candidate.mission_kind,
                "title": candidate.title,
                "goal_kind": candidate.goal_kind,
                "recommended": candidate.recommended,
                "reason": candidate.reason,
                "matched_triggers": list(candidate.matched_triggers),
                "missing_capabilities": list(candidate.missing_capabilities),
                "subjects": list(candidate.subjects),
                "priority": candidate.priority,
            })
        return rows

    def subtasks(self, node_id: str, zone_id: str | None, goal_kind: str, *, caller: Caller) -> dict:
        if node_id not in self.fleet.facts:
            raise ApiError(404, "unknown_robot")
        if self._library.get(goal_kind) is None:
            raise ApiError(404, "unknown_goal_kind")
        fact = self.fleet.facts[node_id]
        zone_id = zone_id or self.fleet.declared_zone_of(node_id)
        if zone_id is None:
            raise ApiError(400, "zone_required")
        graph = self._graph_for(node_id).build(
            goal_kind=goal_kind,
            goal_id=f"{zone_id}:{node_id}:{goal_kind}",
            zone_id=zone_id,
            robot_id=node_id,
            robot_tags=fact.tags,
            budget=_budget_of(fact),
            zone_supplied_kinds=self.fleet.infrastructure_kinds(zone_id),
            known_facts=self.known_facts(zone_id, caller=caller),
        )
        graph["zone_supply_placements"] = [
            {"capability_kind": kind, "provider_id": provider}
            for kind, provider in self.fleet.infrastructure_placements(zone_id)
        ]
        return graph

    # -- 융합된 그림과 그 원인 (개발자 화면) -------------------------------

    def twin_view(self, zone_id: str, *, caller: Caller) -> dict:
        """그 구역의 융합된 객체와 지도 요소. 조회만 한다.

        반영은 요청으로만 일어난다(AI-C-13) — 운영자가 이 구역을 열었다는 사실이
        그 요청이고, 억제되면 방금 받은 값을 그대로 쓴다.
        """
        try:
            self.fleet.zone(zone_id)
        except KeyError as error:
            raise ApiError(404, "unknown_zone") from error
        scope = scope_of("twin", zone_id)
        # 승격 판정과 부족분은 **이 요청 때만** 돈다. 상시 돌리면 아무도 보지 않는
        # 구역의 판정·요청까지 계속 돌고, 그 비용이 임무가 들어왔을 때 쓸 여유를
        # 깎는다(AI-C-13, AI-O-01). 억제되면 `work` 는 호출되지 않는다.
        promotion: dict = {}
        decision = self.refresh.request(
            scope, Trigger.OPERATOR_VIEW, requested_by=caller.actor,
            work=self.twin().promotion_work(
                zone_id, lambda result: promotion.update(result.as_dict())))
        view = self.twin().zone_view(zone_id)
        return {
            "zone_id": zone_id,
            "records": [_jsonable(r) for r in view.records],
            "map_elements": [_jsonable(m) for m in view.map_elements],
            "devices": [_jsonable(d) for d in view.devices],
            # 무엇을 **무엇으로 그릴 것인가**. 픽셀도 색도 여기 없다 — 어느 대역
            # 자산을 쓸 것인지와 그 근거뿐이고, 그리는 일은 뷰어가 한다(AI-C-08).
            "proxies": self.zone_proxies(zone_id),
            # 위 `proxies` 는 **선언된 장치**의 대역이고 이것은 **인지가 만든 객체**의
            # 묶음이다. `/api/zone` 과 같은 값을 같은 출처에서 낸다(AI-O-06).
            "object_placements": self.object_placements(zone_id),
            "refresh": decision.as_dict(),
            # 승격했는가 · 무엇이 모자란가 · 무엇을 더 **요청**하는가. 비어 있으면
            # 이번 요청이 억제된 것이고(그 사유는 위 `refresh` 가 적는다) 값이 없는
            # 것이 아니다 — 한 번도 받지 않은 것과 방금 받은 것은 다른 상태다.
            "promotion": promotion,
            "as_of": self.refresh.as_of(scope),
            "freshness": self.refresh.freshness(scope).value,
        }

    def zone_proxies(self, zone_id: str) -> list[dict]:
        """그 구역의 장치들을 대역물로 환산한다. 카탈로그가 없으면 빈 목록이다.

        로봇과 인프라를 함께 낸다 — 운영자에게는 "거기 무엇이 서 있는가" 가 한
        가지 물음이고, 움직이는 것만 모양을 갖는 화면은 절반만 그린 것이 된다.
        """
        rows: list[dict] = []
        try:
            zone = self.fleet.zone(zone_id)
        except KeyError:
            return rows
        frame_id = f"zone:{zone_id}"
        for robot in self.fleet.robots_in(zone_id):
            rows.append(self._proxy_for(
                robot["node_id"], tags=(robot.get("resources") or {}).get("tags", ()),
                at=robot.get("at"), frame_id=frame_id, source="join_declaration",
                role=robot.get("role") or ""))
        for item in zone.get("infrastructure", ()):
            rows.append(self._proxy_for(
                item["id"], tags=(f"tier.{item.get('kind')}",) if item.get("kind") else (),
                at=item.get("at"), frame_id=frame_id, source="zone_profile",
                role=item.get("kind") or ""))
        return rows

    def object_binder(self):
        """관측된 객체 ↔ 저장 자산 묶음기. 카탈로그가 없으면 **비활성이고 오류가 아니다**.

        두 선언 파일을 함께 싣는다 — `object_models.example.json` 은 장치·부유물의
        대역이고 `object_assets.example.json` 은 탐지 클래스와 그룹 대역이다. 고르는
        규칙은 하나여야 하므로 카탈로그로 겹쳐서 쓴다(`merge_catalogs`).

        `require_asset_file=False` 인 이유는 `proxies()` 와 같다: 자산 파일은 공개 트리
        밖에 있고, 파일이 없는 것과 그릴 것이 없는 것은 다른 상태다.

        implements: AI-S-06, AI-C-05, AI-C-08, AI-C-15
        """
        if self._object_binder is None:
            from mission_runtime.perception.object_asset_binding import (  # noqa: PLC0415
                binder_from_catalogs,
            )

            self._object_binder = binder_from_catalogs(
                _PROJECT_DIR / "config" / "object_models.example.json",
                _PROJECT_DIR / "config" / "object_assets.example.json",
                asset_root=_ASSET_ROOT, require_asset_file=False)
        return self._object_binder

    @staticmethod
    def _group_of(record) -> str:
        """그 레코드가 말하는 장애물 **그룹** 토큰. 없으면 빈 문자열이다.

        이 콘솔은 그룹을 **계산하지 않는다** — 어떤 클래스가 어느 그룹인지는
        `perception/obstacle_taxonomy.py` 가 소유하고, 융합 레코드가 그 칸을 들고 오면
        그룹 대역이 저절로 선다. 여기서 분류를 다시 하면 같은 객체가 두 화면에서 다른
        그룹이 된다(CLAUDE.md §0: 콘솔은 판정을 하지 않는다).

        지금 배치에서는 그 칸이 아직 없어서 **정확 클래스 단계만** 돈다. 그것이 조용한
        결손이 되지 않게 묶음 산출의 `object_group` 이 null 로 그 사실을 적는다.
        """
        return str(getattr(record, "obstacle_group", "")
                   or getattr(record, "object_group", "") or "")

    def object_placements(self, zone_id: str) -> list[dict]:
        """그 구역에서 관측된 객체들을 **무엇으로 어디에 세울지**.

        맵이 읽는 유일한 형태다. 픽셀도 색도 여기 없고(AI-C-08) 나가는 것은 자산 참조와
        현장 로컬 자리뿐이다(AI-C-02). 묶이지 않은 객체도 **빼지 않는다** — 자리는 아는데
        모양이 없는 것은 정상 상태이고, 목록에서 빼면 "거기 아무것도 없다" 가 된다
        (AI-C-05).

        묶음기는 서비스가 들고 있으므로 같은 객체가 움직이면 같은 자산이 옮겨진다. 이
        함수는 판정을 새로 만들지 않고 융합 레코드(`twin.FusedRecord`)가 이미 낸
        클래스·자리를 묶음 계약으로 옮긴다.

        implements: AI-S-06, AI-C-02, AI-C-08, AI-B-12
        """
        from mission_runtime.perception.object_appearance import (  # noqa: PLC0415
            local_placement,
            unknown_placement,
        )
        from mission_runtime.perception.object_asset_binding import (  # noqa: PLC0415
            claim_for_class,
        )

        binder = self.object_binder()
        frame_id = f"zone:{zone_id}"
        rows: list[dict] = []
        for record in self.twin().records(zone_id):
            # 사람 수정까지 반영된 자리를 쓴다. 센서만의 자리와 갈릴 수 있지만 맵이
            # 그릴 것은 "지금 가장 맞다고 보는 자리" 하나다 — 두 자리를 함께 내면
            # 뷰어가 어느 쪽에 모양을 세울지 스스로 판정하게 된다.
            at = record.fused_position
            placement = (local_placement((float(at[0]), float(at[1])), frame_id=frame_id)
                         if at is not None else unknown_placement(frame_id=frame_id))
            # "unknown 은 클래스가 아니다" 를 여기서 다시 판정하지 않는다 — 그 규칙은
            # `claim_for_class` 하나가 소유한다(AI-S-04).
            claim = claim_for_class(record.semantic_class, source="zone_fusion",
                                    observed_at=record.observed_at,
                                    confidence=record.confidence)
            binding = binder.bind(record.object_id, claim, placement=placement,
                                  group=self._group_of(record),
                                  at=record.observed_at)
            rows.append(binding.as_dict())
        return rows

    def object_trace(self, object_id: str, *, about: str, caller: Caller) -> dict:
        """이 객체가 왜 여기 있다고 나오는가 — 어느 장치의 근거가 값을 옮겼는지."""
        if not caller.may(PERM_SEE_INTERNALS):
            # 계약 원문과 provider 내부는 개발자 화면이다. 운영자 화면에 쏟지 않는다.
            raise ApiError(403, f"missing_permission:{PERM_SEE_INTERNALS}")
        try:
            trace = self.twin().trace(object_id, about=about)
        except KeyError as error:
            raise ApiError(404, "unknown_object") from error
        except ValueError as error:
            raise ApiError(400, str(error)) from error
        return _jsonable(trace)

    def correction(self, *, caller: Caller, body: dict) -> dict:
        """잘못된 융합 결과를 사람이 고친다.

        객체 상태는 **즉시** 바뀌고 모델 파라미터는 **바뀌지 않는다** — 그 분리가
        AI-L-03 이다. 고친 값은 사람이 확인한 학습 후보로 등록되어 AI-L-05 검증과
        AI-L-07 단계적 적용을 거친 뒤에야 모델에 반영된다.
        """
        if not caller.may(PERM_CORRECT):
            raise ApiError(403, f"missing_permission:{PERM_CORRECT}")
        object_id = body.get("object_id") or ""
        if not object_id:
            raise ApiError(400, "object_id_required")
        reason = str(body.get("reason") or "")
        twin = self.twin()
        try:
            if "at" in body:
                at = body["at"]
                outcome = twin.apply_position_correction(
                    object_id, (float(at["x"]), float(at["y"])),
                    actor=caller.actor, reason=reason, device_id=body.get("device_id"))
                kind, payload = KIND_OBJECT_POSITION, {"at": {"x": at["x"], "y": at["y"]}}
            else:
                cue_name = body.get("cue_name") or ""
                if not cue_name or "value" not in body:
                    raise ApiError(400, "cue_name_and_value_required")
                outcome = twin.apply_cue_correction(
                    object_id, device_id=body.get("device_id") or "",
                    cue_name=cue_name, corrected_value=body["value"],
                    actor=caller.actor, reason=reason)
                kind = KIND_CUE_CORRECTION
                payload = {"cue_name": cue_name, "value": body["value"],
                           "device_id": body.get("device_id")}
        except (KeyError, TypeError, ValueError) as error:
            raise ApiError(400, f"bad_correction:{type(error).__name__}") from error

        if self.overlay is not None:
            self.overlay.record(kind, object_id, payload, actor=caller.actor, reason=reason,
                                scope=body.get("zone_id"))
        return _jsonable(outcome)

    def report_pose(self, *, caller: Caller, body: dict) -> dict:
        """장치가 자기 자세를 알린다.

        이동형 로봇의 방향은 선언 상수가 아니라 관측값이다 — 프로파일에 박으면 로봇이
        돌아선 순간부터 그 값이 거짓이 되고, 그 거짓 방향으로 투영한 탐지는 엉뚱한
        자리에 객체를 만든다. 그래서 자세는 런타임에 들어오고, 그 출처를
        `pose_source` 로 구분해 선언과 섞이지 않게 한다(AI-S-06).
        """
        from twin import DevicePlacement  # noqa: PLC0415

        device_id = body.get("device_id") or ""
        if not device_id:
            raise ApiError(400, "device_id_required")
        if device_id not in self.fleet.facts:
            raise ApiError(404, "unknown_device")
        zone_id = body.get("zone_id") or self.fleet.declared_zone_of(device_id)
        if zone_id is None:
            raise ApiError(400, "zone_required")
        pose = body.get("pose") or {}
        for key in ("x", "y"):
            if key not in pose:
                raise ApiError(400, f"pose_needs_{key}")
        placement = DevicePlacement(
            device_id=device_id, zone_id=zone_id,
            pose=(float(pose["x"]), float(pose["y"]), float(pose.get("yaw_deg", 0.0))),
            pose_source=str(body.get("pose_source") or "reported"),
            horizontal_fov_deg=float(body.get("horizontal_fov_deg", 60.0)),
            available=bool(body.get("available", True)),
        )
        self.twin().register_device(placement)
        # 자세 보고는 반영 요청이다 — 그 장치가 있는 구역만, 억제 규칙 그대로.
        decision = self.refresh.request(
            scope_of("zone", zone_id), Trigger.SUBTASK_DEMAND, requested_by=caller.actor)
        return {"device_id": device_id, "zone_id": zone_id,
                "pose": list(placement.pose), "pose_source": placement.pose_source,
                "refresh": decision.as_dict()}

    def ingest_detection(self, *, caller: Caller, body: dict) -> dict:
        """장치가 본 것을 하나 받아 융합한다.

        탐지는 **밖에서** 들어온다 — 콘솔이 지어낸 값은 관측이 아니고, 그것으로 융합된
        그림은 아무것도 증명하지 않는다. 그래서 장치(또는 장치 에이전트)가 이 경로로
        올리기 전까지 융합된 객체는 비어 있는 것이 정상이다(AI-C-05).
        """
        from twin import DeviceDetection  # noqa: PLC0415

        required = ("detection_id", "device_id", "frame_ref", "bbox")
        missing = [k for k in required if k not in body]
        if missing:
            raise ApiError(400, f"missing:{','.join(missing)}")
        bbox = body["bbox"]
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            raise ApiError(400, "bbox_must_be_four_numbers")
        try:
            detection = DeviceDetection(
                detection_id=str(body["detection_id"]),
                device_id=str(body["device_id"]),
                track_local_id=int(body.get("track_local_id", 0)),
                frame_ref=str(body["frame_ref"]),
                observed_at=float(body.get("observed_at") or time.time()),
                bbox=tuple(float(v) for v in bbox),
                label=body.get("label"),
                confidence=float(body.get("confidence", 0.0)),
                range_m=(float(body["range_m"]) if body.get("range_m") is not None else None),
                provider_id=str(body.get("provider_id") or ""),
            )
            record = self.twin().ingest_detection(detection)
        except (KeyError, TypeError, ValueError) as error:
            raise ApiError(400, f"bad_detection:{type(error).__name__}") from error
        return _jsonable(record)

    def learning_candidates(self, *, caller: Caller) -> dict:
        """사람이 확인한 후보와 자동 추론 후보를 섞지 않고 낸다(AI-L-02)."""
        ledger = self.twin().learning_candidates()
        return _jsonable(ledger)

    def lineage(self, lineage_id: str, *, caller: Caller) -> dict:
        """후보 1건의 계보를 되짚는다(AI-L-08). 개발자 탭이 원인을 추적하는 입구다."""
        if not caller.may(PERM_SEE_INTERNALS):
            raise ApiError(403, f"missing_permission:{PERM_SEE_INTERNALS}")
        try:
            record = self.twin().lineage(lineage_id)
        except KeyError as error:
            raise ApiError(404, "unknown_lineage") from error
        # 계보 하나만 주면 "이 후보가 어디서 왔나" 에는 답하지만 "그 후보가 지금
        # 어느 상자였나" 에는 답하지 못한다. 원장에서 그 쌍을 찾아 같이 낸다.
        ledger = self.twin().learning_candidates()
        owner = next((c for c in (*ledger.human_confirmed, *ledger.auto_inference)
                      if c.learning_lineage_id == lineage_id), None)
        # `LearningLineage` 는 dataclass 가 아니라 append-only 객체다. 반사로 긁지
        # 않고 모양을 여기서 적는다 — 내부 필드가 그대로 계약이 되면 안 된다.
        return _jsonable({
            "lineage": {
                "learning_lineage_id": record.lineage_id,
                "state": record.state.value,
                "events": [{"sequence": e.sequence, "requirement_id": e.requirement_id,
                            "state": e.state.value, "actor": e.actor,
                            "evidence_ref": e.evidence_ref, "reason": e.reason}
                           for e in record.events],
            },
            "candidate": owner,
        })

    # -- 구역 이동과 다중 구역 임무 ----------------------------------------

    def transit_status(self, node_id: str, *, caller: Caller) -> dict:
        if node_id not in self.fleet.facts:
            raise ApiError(404, "unknown_robot")
        return self.transit(node_id).status()

    def mission_plan(self, *, node_id: str, goal_kind: str, zones: tuple[str, ...],
                     caller: Caller) -> dict:
        """메인 태스크를 구역별 서브태스크로 **순서대로** 나눈다. 실행은 하지 않는다."""
        from mission import derive_zone_order  # noqa: PLC0415

        if node_id not in self.fleet.facts:
            raise ApiError(404, "unknown_robot")
        if self._library.get(goal_kind) is None:
            raise ApiError(404, "unknown_goal_kind")
        start = self.fleet.declared_zone_of(node_id)
        if start is None:
            raise ApiError(400, "robot_has_no_declared_zone")
        runner = self.mission_runner(node_id, goal_kind, caller=caller)
        # 구역 순서를 주지 않으면 인접성에서 유도한다. 빈 순서를 그대로 넘기면
        # "구역이 없는 임무"가 되어 아무것도 계획되지 않는다.
        order = zones or derive_zone_order(self.fleet, start)
        try:
            legs = runner.plan(mission_id=f"{node_id}:{goal_kind}", goal_kind=goal_kind,
                               zone_order=order, start_zone=start)
        except (KeyError, ValueError) as error:
            raise ApiError(400, f"bad_mission:{type(error).__name__}") from error
        # 임무를 부여한 것은 반영 요청이다(AI-C-13) — 그 구역들만, 억제 없이.
        decisions = self.refresh.request_many(
            [scope_of("zone", leg.zone_id) for leg in legs],
            Trigger.MISSION_ASSIGNED, requested_by=caller.actor)
        return {
            "robot": node_id, "goal_kind": goal_kind, "start_zone": start,
            "zone_order": list(order),
            "legs": [_jsonable(leg) for leg in legs],
            "refresh": [d.as_dict() for d in decisions],
            # 조회 경로가 **실행 상태도** 함께 낸다. 상태를 따로 받으러 가게 하면
            # 두 응답 사이에 상태가 변해 계획과 진행이 어긋나 보인다(AI-O-06:
            # 같은 사실은 한 출처에서 파생한다). 이 경로는 읽기만 한다.
            "status": runner.status(),
        }

    def mission_run(self, *, node_id: str, goal_kind: str, zone_id: str | None,
                    zones: tuple[str, ...], caller: Caller) -> dict:
        """임무를 **한 구역씩** 또는 통째로 진행시킨다.

        `zone_id` 를 주면 그 구역 하나만 지난다 — 화면의 "이 서브태스크 진행"
        단추가 그것이고, 한 칸씩 가야 진행이 실제로 보인다. 주지 않으면 계획된
        순서를 끝까지 간다.

        여기서 나오는 것은 **임무 기록**이지 물리 명령의 수락이 아니다. 전달·수락·
        완료는 서로 다른 사실이고(AI-C-20) 그 lifecycle 은 명령 경로가 따로
        가진다. 이 응답의 `outcomes` 는 "그 단계를 시도했고 결과가 이랬다" 까지다.

        implements: AI-B-12, AI-C-19, AI-C-20
        """
        if node_id not in self.fleet.facts:
            raise ApiError(404, "unknown_robot")
        if self._library.get(goal_kind) is None:
            raise ApiError(404, "unknown_goal_kind")
        runner = self.mission_runner(node_id, goal_kind, caller=caller)
        start = self.fleet.declared_zone_of(node_id)
        order = (zone_id,) if zone_id else (zones or None)
        try:
            run = runner.run(mission_id=f"{node_id}:{goal_kind}", goal_kind=goal_kind,
                             zones=order, start_zone=runner.transit.zone_id or start)
        except (KeyError, ValueError) as error:
            raise ApiError(400, f"bad_mission:{type(error).__name__}") from error
        # 임무를 진행시킨 것도 반영 요청이다(AI-C-13) — 지난 구역만.
        decisions = self.refresh.request_many(
            [scope_of("zone", attempt.zone_id) for attempt in run.attempts],
            Trigger.MISSION_ASSIGNED, requested_by=caller.actor)
        return {
            "robot": node_id, "goal_kind": goal_kind,
            "ran": list(zone_id and [zone_id] or [a.zone_id for a in run.attempts]),
            "run": run.as_dict(),
            "status": runner.status(),
            "refresh": [d.as_dict() for d in decisions],
        }

    # -- 실패 원인 ---------------------------------------------------------

    def failure_trace(self, *, subject_id: str, caller: Caller) -> dict:
        """임무 한 단계가 왜 실패했는지. 미측정과 정상을 섞지 않는다(AI-O-05)."""
        if not caller.may(PERM_SEE_INTERNALS):
            raise ApiError(403, f"missing_permission:{PERM_SEE_INTERNALS}")
        from mission_runtime.observability.failure_trace import (  # noqa: PLC0415
            FailureQuery,
            TimeWindow,
        )

        now = time.time()
        report = self.failures().attribute(FailureQuery(
            subject_id, TimeWindow.around(now, before_s=300.0)))
        return report.as_dict() if hasattr(report, "as_dict") else {
            "subject_id": subject_id,
            "inconclusive": getattr(report, "inconclusive", True),
            "explain": report.explain() if hasattr(report, "explain") else "",
        }

    # -- 추론 근거 (설명 가능성) -------------------------------------------

    def explain(self, *, sample_class: str, sample_file: str, caller: Caller) -> dict:
        """모델이 왜 그 class 라고 했는지. 사진 자체는 참조로만 가리킨다.

        픽셀을 이 응답에 담지 않는다 — 업무·상태 경로에 영상을 싣지 않는 경계가
        AI-C-08 이고, 뷰어는 `media` 의 참조로 `/api/media` 에서 받아 그린다. 그래야
        같은 설명을 Unity 뷰어가 받아도 자기 방식으로 그릴 수 있다.
        """
        self.require_evidence_path()
        classifier = self.appearance()
        path = self._appearance_file(sample_class, sample_file)
        try:
            import cv2  # noqa: PLC0415

            crop = cv2.imread(str(path))
        except ImportError as error:
            raise ApiError(503, "no_image_decoder") from error
        if crop is None:
            raise ApiError(404, "sample_not_readable")
        verdict = classifier.classify(crop)
        body = verdict.explanation()
        body["sample"] = {"appearance_class": sample_class, "file": sample_file,
                          "media": self._media_ref(sample_class, sample_file)}
        # 근거 사진도 참조로 바꿔 준다. 뷰어가 경로 조립을 추측하지 않아도 되게.
        for row in body.get("ranked", ()):
            for reference in row.get("references", ()):
                reference["media"] = self._media_ref(
                    row.get("semantic_class", ""), reference.get("file", ""))
        return body

    def background(self, *, domain_id: str | None, level_id: str | None,
                   zone_id: str | None = None) -> dict:
        """그 자리 아래에 깔 바탕 그림. 없으면 없다고 말한다.

        `domain_id` 가 없으면 **현장 그림**을 묻는 것이다 — 메인 맵이 그 그림 위에
        그려진다. 좁은 자리부터 찾으므로 구역 도면이 있으면 그것이 층 도면을
        이긴다(`static_image_for`).

        **상태 계약과 다른 경로다.** 그림의 픽셀 크기와 파일 참조는 표현에 가까운
        값이고, 그것이 `/api/scene`·`/api/domain`·`/api/zone` 에 섞이는 순간 "서버
        응답에는 색·픽셀·폰트가 없다" 는 경계가 무너진다(AI-C-08). 그래서 바탕은
        이 경로로만 나가고, 그림 **바이트**는 다시 `/api/media` 로만 나간다.

        그림이 없는 배치는 정상이다 — 지도는 지금처럼 로컬 좌표 도면으로 그려진다.

        implements: AI-C-02, AI-C-08, AI-C-16, AI-C-05
        """
        from fleet import static_image_for  # noqa: PLC0415

        block = static_image_for(self.fleet.map_tiles, domain_id=domain_id,
                                 level_id=level_id, zone_id=zone_id)
        where = {"domain_id": domain_id, "level_id": level_id, "zone_id": zone_id}
        if block is None:
            return {**where, "declared": False, "image": None}
        return {**where, "declared": True, "image": block}

    def evidence_kinds(self, *, capability: str | None, available: tuple[str, ...]) -> dict:
        """어떤 근거를 **낼 수 있는가**, 그리고 그중 무엇이 결론을 가를 수 있는가.

        화이트박스의 바닥이다. 모델이 낸 점수 하나만 보여 주면 "왜 그렇게 봤는가"
        에 답할 수 없고, 더 나쁘게는 **가릴 수 없는 근거**(외형 같은 것)가 쌓인
        것을 가릴 수 있는 근거처럼 읽게 된다. 그래서 종류마다 셋을 함께 낸다 —
        단계(사람 실측 / 선언 / 센서 추정), 가릴 수 있는가, 그것을 만들어 주는
        capability 가 지금 있는가.

        `available` 에 없는 capability 가 내는 종류는 **미측정**이고 오류가 아니다
        (AI-C-05). 0 으로 적지 않는다.

        implements: AI-S-03, AI-S-06, AI-C-18, AI-O-06
        """
        from mission_runtime.perception.evidence_kinds import (  # noqa: PLC0415
            default_kind_registry,
        )

        registry = default_kind_registry()
        have = set(available)
        rows = []
        for kind in registry.kinds():
            spec = registry.spec(kind)
            if capability and spec.capability_kind and spec.capability_kind != capability:
                continue
            rows.append({
                "kind": spec.kind,
                "tier": spec.tier,
                "discriminating": spec.discriminating,
                "origin": spec.origin,
                "capability_kind": spec.capability_kind,
                "request": spec.request,
                "note": spec.note,
                # 세 값이다: 지금 낼 수 있다 / 낼 수 없다 / 어떤 capability 도
                # 필요 없다(선언·사람 입력에서 온다). 마지막을 "낼 수 없다"로
                # 적으면 사람이 확인한 값이 미측정으로 보인다.
                "producible": (True if not spec.capability_kind
                               else spec.capability_kind in have),
                "needs_capability": bool(spec.capability_kind),
            })
        return {
            "capability": capability,
            "available_capabilities": sorted(have),
            "kinds": rows,
            "discriminating_kinds": list(registry.discriminating_kinds()),
            "capability_kinds": list(registry.capability_kinds()),
        }

    def require_evidence_path(self) -> None:
        """근거 경로가 없으면 503 으로 끝낸다. 사유 문구는 **여기 한 곳**에서만
        만든다 — 두 곳에서 지으면 라우터와 서비스가 다른 말을 한다."""
        classifier = self.appearance()
        if not classifier.available:
            raise ApiError(503, f"no_evidence_path:{classifier.unavailable_reason}")

    def appearance_samples(self) -> dict:
        """설명해 볼 수 있는 사진 목록. 없으면 빈 목록이고 오류가 아니다."""
        classifier = self.appearance()
        samples: dict[str, list[str]] = {}
        if _APPEARANCE_ROOT is not None and _APPEARANCE_ROOT.exists():
            for directory in sorted(p for p in _APPEARANCE_ROOT.iterdir() if p.is_dir()):
                files = sorted(
                    f.name for f in directory.iterdir()
                    if f.is_file() and _SAFE_NAME.match(f.name)
                    and f.suffix.lower() in (".jpg", ".jpeg", ".png")
                    and "contact_sheet" not in f.name)
                if files:
                    samples[directory.name] = files
        return {
            "available": classifier.available,
            "reason": classifier.unavailable_reason,
            "unfit_classes": dict(classifier.unfit_classes),
            "samples": samples,
            # 빈 목록이 "사진이 없다"인지 "사진 뿌리 자체가 없다"인지 구분해 준다.
            # 둘을 한 값으로 뭉치면 운영자가 설정 실수와 정상 축소를 못 가린다(AI-O-06).
            "samples_root": None if _APPEARANCE_ROOT is None else str(_APPEARANCE_ROOT),
            "samples_root_present": bool(
                _APPEARANCE_ROOT is not None and _APPEARANCE_ROOT.is_dir()),
        }

    def _appearance_file(self, sample_class: str, sample_file: str) -> Path:
        if _APPEARANCE_ROOT is None:
            # 뿌리가 없으면 어떤 이름도 가리킬 것이 없다. 이름 검사보다 먼저 답한다.
            raise ApiError(404, "no_appearance_root")
        if not _SAFE_NAME.match(sample_class or "") or not _SAFE_NAME.match(sample_file or ""):
            raise ApiError(400, "bad_sample_name")
        path = (_APPEARANCE_ROOT / sample_class / sample_file).resolve()
        root = _APPEARANCE_ROOT.resolve()
        # 이름을 좁혔더라도 최종 경로가 뿌리 밖이면 거절한다 — 심링크로 빠져나갈 수 있다.
        if root not in path.parents or not path.is_file():
            raise ApiError(404, "sample_not_found")
        return path

    @staticmethod
    def _media_ref(sample_class: str, sample_file: str) -> dict:
        return {"path": "/api/media", "kind": "appearance",
                "class": sample_class, "file": sample_file}

    def media_bytes(self, *, kind: str, sample_class: str, sample_file: str) -> tuple[bytes, str]:
        """픽셀은 **여기서만** 나간다. 상태 계약과 분리된 경로다(AI-C-08)."""
        if kind == "frame":
            # 라벨 화면이 그릴 프레임. 상태 계약이 아니라 **이 경로**로만 나간다.
            from labeling import LabelingError, resolve_frame  # noqa: PLC0415

            bundle = self.labels(sample_class or None)
            root = bundle._root()
            if root is None:
                raise ApiError(503, "no_frame_assets")
            try:
                # 하위 디렉터리를 허용하되 출처 뿌리 밖으로는 못 나간다.
                path = resolve_frame(root, sample_file or "")
            except LabelingError as error:
                raise ApiError(400, f"bad_frame:{error}") from error
            if not path.is_file():
                raise ApiError(404, "frame_not_found")
            suffix = path.suffix.lower()
            return path.read_bytes(), (
                "image/png" if suffix == ".png" else "image/jpeg")
        if kind == "map":
            # 바탕 그림. 선언에 적힌 참조만 받아들인다 — 임의 경로를 받으면
            # 이 경로가 파일 읽기 도구가 된다.
            from fleet import TILE_KIND_STATIC_IMAGE  # noqa: PLC0415

            layer = next((row for row in (self.fleet.map_tiles or {}).get("layers", ())
                          if row.get("kind") == TILE_KIND_STATIC_IMAGE
                          and row.get("layer_id") == sample_file), None)
            if layer is None:
                raise ApiError(404, "unknown_map_layer")
            if _ASSET_ROOT is None:
                raise ApiError(503, "no_map_assets")
            path = _ASSET_ROOT / layer["image"]["ref"]
            if not path.is_file():
                raise ApiError(404, "map_image_not_found")
            suffix = path.suffix.lower()
            return path.read_bytes(), (
                "image/png" if suffix == ".png" else "image/jpeg")
        if kind != "appearance":
            raise ApiError(404, "unknown_media_kind")
        path = self._appearance_file(sample_class, sample_file)
        suffix = path.suffix.lower()
        media_type = "image/png" if suffix == ".png" else "image/jpeg"
        return path.read_bytes(), media_type

    # -- 공간 근거 ---------------------------------------------------------

    def spatial_state(self, zone_id: str, *, caller: Caller) -> dict:
        """선언·센서·사람이 잰 값을 합친 공간 상태와, 한 출처를 빼면 어떻게 되는지."""
        from mission_runtime.perception.spatial_evidence import (  # noqa: PLC0415
            fuse_zone,
            load_survey_observations,
            observations_from_domain_profile,
        )

        try:
            self.fleet.zone(zone_id)
        except KeyError as error:
            raise ApiError(404, "unknown_zone") from error
        observations = list(observations_from_domain_profile(
            self.fleet.domain_profile, zone_id))
        observations.extend(load_survey_observations(
            _PROJECT_DIR / "profiles" / "space_survey.example.json", zone_id=zone_id))
        state = fuse_zone(observations, zone_id=zone_id)
        return _jsonable(state)

    # -- 정답 만들기 (라벨) -------------------------------------------------

    def label_tasks(self, source_id: str | None, *, caller: Caller) -> dict:
        """출처 목록과, 고른 출처의 프레임. 추론기가 없으면 그 사실을 적는다.

        프레임을 한 줄로 늘어놓지 않고 출처로 가른다 — 어디서 온 데이터인지가
        사라지면 그 정답이 누구의 학습 후보인지도 사라진다(AI-L-09).
        """
        declared = self.label_sources()
        chosen = self.labels(source_id)
        rows = []
        for entry in declared:
            bundle = self.labels(entry.source_id)
            rows.append({
                **entry.as_dict(),
                "frame_count": bundle.frame_count(),
                "listed": len(bundle.frames()),
                # 자산이 없는 설치에서는 선언만 있고 파일이 없다 — 그 사실을 적는다.
                "present": bundle.frame_count() > 0,
            })
        return {
            "sources": rows,
            "selected": chosen.source_id or None,
            "device_id": chosen.subject_id,
            "zone_id": chosen.zone_id,
            "frames": list(chosen.frames()),
            "frame_count": chosen.frame_count(),
            "vocabulary": list(chosen.vocabulary),
            # 추론기 부재는 장애가 아니라 "사람이 처음부터 그린다" 는 정상 경로다.
            "detector_available": chosen.detector() is not None,
            "detector_reason": chosen.detector_reason,
            "submitted": sorted(self._ground_truth),
            "assets_root_present": _ASSET_ROOT is not None,
        }

    def label_task(self, frame_name: str, *, source_id: str | None,
                   caller: Caller) -> dict:
        """프레임 하나와 **지금 실제로 돌린** 모델 예측. 픽셀은 미디어 경로로."""
        from labeling import LabelingError  # noqa: PLC0415

        source = self.labels(source_id)
        if frame_name not in source.frames():
            raise ApiError(404, "unknown_frame")
        try:
            task = source.task(frame_name, media_ref={
                "path": "/api/media", "kind": "frame",
                "source": source.source_id, "file": frame_name})
        except LabelingError as error:
            raise ApiError(400, str(error)) from error
        body = task.as_dict()
        # 이미 제출된 정답이 있으면 같이 낸다 — 다시 열었을 때 처음부터 하게 하면
        # 라벨 작업이 두 배가 되고, 두 번째 답이 첫 번째와 달라도 알 수 없다.
        existing = self._ground_truth.get(task.task_id)
        body["ground_truth"] = existing.as_dict() if existing is not None else None
        return body

    def submit_labels(self, *, caller: Caller, body: dict) -> dict:
        """사람이 만든 정답을 받는다.

        **모델을 바로 바꾸지 않는다.** 사람이 확인한 학습 후보가 되어 AI-L-05 검증과
        AI-L-07 단계적 적용을 지나야 운영에 닿는다(AI-L-03). 여기서 하는 일은 정답을
        기록하고 그 후보를 여는 것까지다.
        """
        from labeling import (  # noqa: PLC0415
            GroundTruthRecord,
            LabelingError,
            labeled_box_from_dict,
        )

        frame_name = str(body.get("frame") or "")
        rows = body.get("boxes")
        if not frame_name or not isinstance(rows, list):
            raise ApiError(400, "frame_and_boxes_required")
        # 왜 그렇게 고쳤는지가 없으면 계보를 열 수 없다 — 나중에 이 정답으로
        # 배운 가중치를 보고도 어떤 판단이었는지 되짚을 수 없다(AI-L-08).
        reason = str(body.get("reason") or "").strip()
        if not reason:
            raise ApiError(400, "reason_required")
        source = self.labels(str(body.get("source") or "") or None)
        if frame_name not in source.frames():
            raise ApiError(404, "unknown_frame")
        try:
            task = source.task(frame_name, media_ref={})
            predicted = {b.box_id: b for b in task.predicted}
            boxes = tuple(
                labeled_box_from_dict(row, predicted=predicted, author=caller.actor)
                for row in rows)
            record = GroundTruthRecord(
                task_id=task.task_id, frame_ref=task.frame_ref,
                device_id=task.device_id, boxes=boxes, submitted_by=caller.actor,
                submitted_at=time.time(), model_version=task.model_version,
                zone_id=task.zone_id, reason=reason)
        except LabelingError as error:
            raise ApiError(400, f"bad_labels:{error}") from error
        self._ground_truth[record.task_id] = record

        # 정답은 운영자 수정이므로 장부에 남는다 — 누가 언제 무엇을 정답이라 했는지.
        if self.overlay is not None:
            self.overlay.record(KIND_GROUND_TRUTH, record.task_id,
                                {k: v for k, v in record.summary().items()
                                 if k in ("reviewed_count", "correction_count",
                                          "unreviewed_count", "model_version")},
                                actor=caller.actor, reason=reason,
                                scope=record.zone_id)

        candidates = self._file_label_candidates(record, caller=caller, reason=reason)
        return {**record.as_dict(), "learning_candidates": candidates}

    def _file_label_candidates(self, record, *, caller: Caller, reason: str) -> list[dict]:
        """정답에서 **모델과 다른 답만** 학습 후보로 올린다.

        모델이 맞힌 것을 후보로 넣으면 후보가 전체 스트림으로 불어나고, 그것이
        AI-L-01 이 피하라고 적은 상태다 — 재검토 가치가 있는 사례만 고른다.

        후보 보관소에 직접 넣지 않고 트윈의 `file_label_candidate` 를 거친다.
        그래야 같은 건이 후보 원장(AI-L-02)과 계보(AI-L-08)에 함께 나타난다 —
        보관소에만 넣으면 표본은 남지만 운영자가 고친 정답이 후보 화면에서
        사라지고 가중치의 출처를 되짚을 입구가 없다.
        """
        from mission_runtime.continual.stream_learning import (  # noqa: PLC0415
            SamplePolarity,
            SampleUsage,
        )

        filed: list[dict] = []
        # 모델이 맞았다고 사람이 확인한 상자는 **학습 후보가 아니다**(AI-L-01: 후보가
        # 전체 스트림으로 불어난다). 그렇다고 버릴 것도 아니다 — 그것은 "전에 되던
        # 것" 의 집합이고 회귀를 재는 데 가장 맞는 자료다. 후보가 학습에 쓴 표본에서
        # 회귀를 재면 train-set 평가가 되어 깨진 것이 보이지 않는다.
        from labeling import CORRECTING_VERDICTS  # noqa: PLC0415

        for box in record.reviewed:
            if box.verdict in CORRECTING_VERDICTS:
                continue   # 수정은 아래에서 학습 후보로 간다
            if box.final_class is None or box.final_box is None:
                continue
            self.twin().file_label_candidate(
                device_id=record.device_id, zone_id=record.zone_id or "",
                box_ref=f"{record.task_id}:{box.box_id}", label=box.final_class,
                box=box.final_box, verdict=box.verdict.value, actor=caller.actor,
                reason=reason, frame_ref=record.frame_ref,
                confidence=(box.predicted.confidence if box.predicted else None),
                usage=SampleUsage.EVALUATION_ONLY)
        for box in record.corrections:
            # **지운 상자는 "absent" 라는 클래스의 예가 아니다.** 그것은 모델이
            # 주장한 그 클래스의 **반례**다 — "저기 의자가 있다" 에 사람이 아니라고
            # 한 것이므로, 음성 라벨은 모델이 말한 이름이어야 한다.
            #
            # 한때 `label = box.final_class or "absent"` 였다. `final_class` 는
            # REJECTED 에서 None 이라 그 줄이 `"absent"` 라는 이름을 **지어냈고**,
            # 상자도 없어 특징이 (0,0,0,0) 이 되고, 셋이 모이면
            # `parameters["absent"]` 가 **임계 0.0 — 모든 것을 받아들이는 클래스**로
            # 생겼다(2026-11-04 재현 확인). 한 줄이 사람의 정답을 뒤집었다.
            rejected = box.final_class is None
            label = box.final_class or (
                box.predicted.semantic_class if box.predicted else "")
            if not label:
                # 모델이 주장한 이름도 없으면 가리킬 클래스가 없다. 지어내지 않는다.
                continue
            candidate = self.twin().file_label_candidate(
                polarity=(SamplePolarity.NEGATIVE if rejected
                          else SamplePolarity.POSITIVE),
                device_id=record.device_id, zone_id=record.zone_id or "",
                box_ref=f"{record.task_id}:{box.box_id}", label=label,
                box=(box.final_box if not rejected
                     else (box.predicted.box if box.predicted else None)),
                verdict=box.verdict.value,
                actor=caller.actor, reason=reason, frame_ref=record.frame_ref,
                confidence=(box.predicted.confidence if box.predicted else None),
            )
            filed.append({
                "learning_candidate_id": candidate.learning_candidate_id,
                "learning_lineage_id": candidate.learning_lineage_id,
                "learning_state": candidate.learning_state,
                "box_ref": candidate.box_ref, "label": label,
                "verdict": box.verdict.value,
                "disagreement": box.disagreement(),
            })
        return filed

    # -- 종합상황정보 구역 B~I (조회 전용) ----------------------------------

    def dashboard(self, *, pin: str | None = None) -> dict:
        """구역 B~I 를 **한 스냅샷**으로 옮긴다. 조립도 판정도 여기서 하지 않는다.

        implements: AI-O-06 (통합 운영 상태 뷰), AI-O-05 (계층별 지표),
                    AI-B-12 (작업 그래프 실행 상태), AI-B-13 (외부 개발 요청)

        종합상황정보 Dashboard 기능정의서 §3 요구사항 1 은 "소스별로 개별 조회하는
        것이 아니라 **통합된 상태 뷰**"를 요구하고 §5 는 같은 사실이 여러 구역에
        나타날 때 값이 상충하지 않기를 요구한다. 그 조립의 정본은
        `tools/status_ui/serve.py` 의 `StatusService.dashboard()` 이고, 운영 콘솔이
        같은 조립을 다시 하면 두 화면이 서로 다른 답을 말한다(CLAUDE.md §0).
        그래서 이 메서드는 **옮기기만** 한다.

        `pin` 은 기준 노드 고정이고 관찰 방식의 변경이다(문서 §1.1·§2) — 실행 상태를
        바꾸지 않으므로 조회 경로에 남는다.
        """
        if self.status is None:
            # 경로가 없는 배치는 정상이다. 빈 본문 대신 "기능 없음"을 말한다 —
            # 빈 목록을 내려보내면 화면이 "볼 것이 없다"와 "연결되지 않았다"를
            # 구분하지 못한다(AI-C-05).
            raise ApiError(503, "no_dashboard_path:status_service_absent")
        try:
            return self.status.dashboard(pin=pin)
        except Exception as error:   # noqa: BLE001 — 아래 한 사유만 옮긴다
            # 없는 노드를 가리킨 고정은 404 다 — 조회가 조용히 다른 노드로 옮겨
            # 가면 화면은 자기가 무엇을 보고 있는지 모른다. 정본 쪽 예외 클래스는
            # 경로로 실은 모듈에 있어 이름으로 잡을 수 없으므로 사유 토큰으로
            # 가른다. 나머지 예외는 그대로 올려 보낸다 — 삼키지 않는다.
            if str(error).startswith("unknown_task_node:"):
                raise ApiError(404, "unknown_task_node") from error
            raise

    # -- 배포 (들이기 · 보정 · 학습 · 모델 교체) ----------------------------

    def deployment_view(self, *, caller: Caller) -> dict:
        """네 가지 일의 **하나의 스냅샷**(AI-O-06).

        권한이 없는 구역은 빈 값이 아니라 "무슨 능력이 필요한가"를 적는다 — 빈
        목록으로 내려보내면 화면이 "할 일이 없다"와 "볼 수 없다"를 구분하지 못한다.
        """
        body: dict[str, Any] = {"permissions": {
            "join": PERM_ONBOARD, "calibration": PERM_CALIBRATE,
            "training": PERM_TRAIN, "model": PERM_DEPLOY_MODEL,
        }}
        joins = self.joins().view()
        body["join"] = {
            **joins,
            # 어떤 장치가 보정·외형학습·자리확인을 기다리는지는 조회 권한으로 보인다.
            "may_submit": caller.may(PERM_ONBOARD),
            "known_device_ids": sorted(self.fleet.facts),
        }
        from deployment import MIN_CALIBRATION_VIEWS  # noqa: PLC0415

        # 보정 대상은 **카메라를 달고 있다고 선언한 것** 전부다. 고정 카메라만 세면
        # 로봇 온보드 카메라가 영원히 보정 대기 목록에 나타나지 않는다(AI-E-02 는
        # 카메라 종류로 갈라지지 않는다).
        cameras = []
        for zone_id in self.fleet.zone_ids():
            for item in self.fleet.zone(zone_id).get("infrastructure", ()):
                if item.get("kind") != "fixed_camera":
                    continue
                cameras.append({**self.calibration().view(item["id"]), "zone_id": zone_id,
                                "role": item.get("kind"),
                                "declared_profile": item.get("calibration")})
        for device_id in self.joins().onboarding.joined():
            manifest = self.joins().onboarding.manifest(device_id)
            if manifest is None or not manifest.has_camera:
                continue
            cameras.append({**self.calibration().view(device_id),
                            "zone_id": self.fleet.declared_zone_of(device_id),
                            "role": manifest.role,
                            "declared_profile": (
                                None if not manifest.calibration_profile_version else
                                {"profile_version": manifest.calibration_profile_version})})
        body["calibration"] = {
            "cameras": cameras,
            "frames_root_present": _CALIBRATION_FRAME_ROOT is not None,
            "min_views": MIN_CALIBRATION_VIEWS,
            "may_submit": caller.may(PERM_CALIBRATE),
        }
        training = self.training()
        body["training"] = {
            "groups": training.groups() if caller.may(PERM_TRAIN) else [],
            "candidates": training.candidates() if caller.may(PERM_TRAIN) else [],
            "may_submit": caller.may(PERM_TRAIN),
        }
        models = self.models()
        body["model"] = {
            "versions": models.versions(),
            "devices": models.devices(),
            "deployments": models.deployments(),
            "capability_kinds": sorted({v["capability_kind"] for v in models.versions()}),
            "may_submit": caller.may(PERM_DEPLOY_MODEL),
            # 화면이 적용할 버전을 **이 행에서** 고른다. 각 행이 자기 계보와
            # 미검증 범위를 이미 들고 있어서, 계보를 따로 들고 오는 길이 없다 —
            # 그 길이 "계보 A, 버전 B" 라는 거짓 기록의 입구였다(AI-L-08).
            # 계보 식별자가 실려 있으므로 `GET /api/lineage` 와 같은 권한에 둔다.
            "promotions": models.promotions() if caller.may(PERM_DEPLOY_MODEL) else [],
        }
        return body

    def join_device(self, *, caller: Caller, body: dict) -> dict:
        """조인 선언 1건. 받아들였다는 뜻은 "쓸 수 있다"가 아니라 "계약에 맞는다"다.

        최종 가용성은 백엔드가 업무·관측 상태를 통합해 판정한다(절대 준수 원칙 #15).
        """
        reason = str(body.get("reason") or "").strip()
        if not reason:
            raise ApiError(400, "reason_required")
        announced = body.get("announced_actions")
        if announced is None:
            # 공지 목록을 따로 주지 않으면 선언한 어휘를 그대로 공지로 읽는다.
            # 비워 두면 선언한 action 전부가 "공지되지 않았다" 로 나와, 장치가 직접
            # 공지하는 경로가 아직 없는 배치에서 어댑터 누락 경보가 거짓으로 뜬다.
            announced = body.get("declared_actions") or []
        if not isinstance(announced, list):
            raise ApiError(400, "announced_actions_must_be_a_list")
        outcome, manifest = self.joins().submit(
            body, announced_actions=announced, replace=bool(body.get("replace")))
        from deployment import _manifest_dict, node_config_entry  # noqa: PLC0415

        entry = node_config_entry(manifest) if outcome.accepted else None
        adopted_zone = None
        if outcome.accepted:
            if self.overlay is not None:
                self.overlay.record(KIND_NODE_JOIN, manifest.device_id,
                                    {"role": manifest.role,
                                     "node_tags": sorted(manifest.node_tags),
                                     "next_steps": [s.value for s in outcome.next_steps]},
                                    actor=caller.actor, reason=reason)
            # **바로 연동**한다. 전에는 설정 한 줄을 돌려주고 끝이라, 사람이 그 줄을
            # 파일에 붙여 넣고 서버를 다시 띄울 때까지 그 장치는 어디에도 없었다.
            zone_id = str(body.get("zone_id") or "")
            if zone_id:
                try:
                    self.fleet.adopt_node(entry, zone_id=zone_id, at=body.get("at"))
                    adopted_zone = zone_id
                except KeyError as error:
                    raise ApiError(404, "unknown_zone") from error
        # 가시화 파트가 받을 수 있는 모양으로도 한 벌 낸다. 그쪽 계약이 직접
        # 적는다 — "여기 없는 것은 assigned_targets 에 쓸 수 없다." 우리 화면에만
        # 서는 장치는 임무를 받을 수 없으므로 들이는 일이 거기서 끝나면 확장이
        # 아니다. 계약이 `additionalProperties: false` 라 우리가 아는 것을 더
        # 실어 보낼 수 없고, 그것이 두 계약을 섞지 않는 경계다(AI-C-04).
        handoff = None
        if outcome.accepted:
            from visualisation import equipment_entry  # noqa: PLC0415

            handoff = equipment_entry(
                {"device_id": manifest.device_id, "role": manifest.role,
                 "label": body.get("label"), "aliases": body.get("aliases", ())},
                zone_id=adopted_zone)
        return {"outcome": outcome.as_dict(), "manifest": _manifest_dict(manifest),
                "config_entry": entry,
                # 어느 구역에 세웠는가. 구역을 주지 않으면 선언만 받고 세우지 않는다 —
                # 자리를 모르는 장치를 아무 구역에나 넣지 않는다.
                "adopted_into_zone": adopted_zone,
                "visualisation_entry": handoff}

    def resolve_join_step(self, *, caller: Caller, body: dict) -> dict:
        """할 일 하나를 끝낸 것으로 표시한다. 선언 자체는 바꾸지 않는다."""
        device_id = str(body.get("device_id") or "")
        step = str(body.get("step") or "")
        reason = str(body.get("reason") or "").strip()
        if not device_id or not step or not reason:
            raise ApiError(400, "device_id_step_and_reason_required")
        try:
            outcome = self.joins().resolve(device_id, step)
        except ValueError as error:
            raise ApiError(400, f"unknown_step:{step}") from error
        if outcome is None:
            raise ApiError(404, "unknown_device")
        if self.overlay is not None:
            self.overlay.record(KIND_NODE_JOIN, device_id,
                                {"resolved_step": step}, actor=caller.actor, reason=reason)
        return {"outcome": outcome.as_dict()}

    def submit_camera_info(self, *, caller: Caller, body: dict) -> dict:
        """카메라 정보를 받고, 재료가 있으면 그 자리에서 실제로 측정한다.

        선언만으로는 어떤 프로파일도 활성이 되지 않는다 — 제원에서 유도한 값은
        관측이 아니다(AI-S-08). 측정이 없으면 `not_measured` 이고, 그때 활성
        프로파일은 손대지 않는다(AI-E-02 의 last-known-good).
        """
        from deployment import camera_info_from_dict  # noqa: PLC0415

        reason = str(body.get("reason") or "").strip()
        if not reason:
            raise ApiError(400, "reason_required")
        device_id = str(body.get("device_id") or "")
        if not device_id:
            raise ApiError(400, "device_id_required")
        try:
            info = camera_info_from_dict({**body, "actor": caller.actor})
        except (ValueError, TypeError) as error:
            raise ApiError(400, f"bad_camera_info:{error}") from error
        desk = self.calibration()
        desk.declare(info)
        run = desk.calibrate(device_id)
        if self.overlay is not None:
            self.overlay.record(KIND_CALIBRATION, device_id,
                                {"declared": info.as_dict(), "verdict": run.verdict,
                                 "reasons": list(run.reasons),
                                 "frames_used": run.frames_used},
                                actor=caller.actor, reason=reason)
        return {"run": run.as_dict(), "camera": desk.view(device_id)}

    def calibration_view(self, device_id: str, *, caller: Caller) -> dict:
        del caller      # 조회는 로그인한 모든 계정에 열려 있다
        if not device_id:
            raise ApiError(400, "device_required")
        return self.calibration().view(device_id)

    def run_training(self, *, caller: Caller, body: dict) -> dict:
        """학습·검증·승인요청. 어느 관문인지는 `step` 이 말한다.

        한 호출로 끝까지 밀지 않는다 — 관문을 건너뛰는 빠른 길을 두면 그 관문은
        선택 사항이 된다(AI-L-05/06).
        """
        reason = str(body.get("reason") or "").strip()
        if not reason:
            raise ApiError(400, "reason_required")
        step = str(body.get("step") or "train")
        desk = self.training()
        try:
            if step == "train":
                group = str(body.get("group_key") or "")
                if not group:
                    raise ApiError(400, "group_key_required")
                result = desk.train(group, actor=caller.actor, reason=reason)
                target = group
            elif step in ("validate", "request_approval"):
                version = str(body.get("version") or "")
                if not version:
                    raise ApiError(400, "version_required")
                result = (desk.validate(version, actor=caller.actor, reason=reason,
                                        gate=_gate_from(body))
                          if step == "validate"
                          else desk.request_approval(version, actor=caller.actor,
                                                     reason=reason))
                target = version
            else:
                raise ApiError(400, f"unknown_step:{step}")
        except KeyError as error:
            raise ApiError(404, f"unknown_target:{error.args[0] if error.args else ''}") from error
        except ValueError as error:
            raise ApiError(400, str(error)) from error
        if self.overlay is not None:
            self.overlay.record(KIND_TRAINING, target,
                                {"step": step,
                                 **{k: v for k, v in result.items() if k != "candidate"}},
                                actor=caller.actor, reason=reason)
        return {"step": step, **result,
                "groups": desk.groups(), "candidates": desk.candidates()}

    def approval_info(self, version: str, *, caller: Caller) -> dict:
        """관리자가 판단할 재료(AI-L-06). 검증을 통과하지 못한 후보는 `eligible=False`."""
        del caller
        try:
            return self.training().approval_info(version)
        except KeyError as error:
            raise ApiError(404, "unknown_version") from error

    # --- 세부 임계값: 선언 · 시도 · 적용 (AI-S-08 · AI-B-01 · AI-L-03) --------

    def thresholds(self):
        """탐지 세부 임계값 선언. 파일이 없으면 **빈 선언**이고 오류가 아니다.

        값 자체는 `config/detection_thresholds.example.json` 이 소유하고 이 메서드는
        읽어 두기만 한다 — 콘솔이 기본값을 따로 들고 있으면 선언을 고쳐도 화면이
        옛 수를 보여 준다.
        """
        if self._thresholds is None:
            from mission_runtime.perception.detection_thresholds import (  # noqa: PLC0415
                DetectionThresholds,
            )

            path = _PROJECT_DIR / "config" / "detection_thresholds.example.json"
            try:
                self._thresholds = DetectionThresholds.from_file(path)
            except (OSError, ValueError):
                # 선언이 깨졌거나 없는 배치. 추측해 채우지 않고 빈 선언으로 둔다 —
                # 그러면 모든 해소가 `no_declaration` 이 되어 그 사실이 화면에 뜬다.
                self._thresholds = DetectionThresholds.empty()
        return self._thresholds

    def taxonomy(self):
        """장애물 어휘. 어휘별 라벨 하한의 주인이다. 없으면 None 이다(AI-C-05)."""
        if self._taxonomy is None:
            from mission_runtime.perception.obstacle_taxonomy import (  # noqa: PLC0415
                ObstacleTaxonomy,
            )

            try:
                self._taxonomy = ObstacleTaxonomy.from_file()
            except (OSError, ValueError):
                self._taxonomy = False      # "읽어 봤고 없다" — None 과 구분한다
        return self._taxonomy or None

    def _operator_thresholds(self) -> dict:
        """장부의 현재 유효 임계값 수정. 선언을 덮지 않고 따로 들고 온다(AI-L-03)."""
        from mission_runtime.perception.detection_thresholds import (  # noqa: PLC0415
            operator_values_from_overlay,
        )

        if self.overlay is None:
            return {}
        return operator_values_from_overlay(
            self.overlay.current_payloads(KIND_THRESHOLD))

    def _detector_row(self, implementation_ref: str) -> dict:
        """탐지기 선언 한 행. 없으면 빈 사전이다 — 없는 선언을 추측하지 않는다."""
        try:
            from mission_runtime.edge.detector_catalog import characteristics  # noqa: PLC0415
        except ImportError:
            return {}
        try:
            # 뿌리가 없으면 **없다고 넘긴다.** 전에는 `or _PROJECT_DIR` 로 다른
            # 자리를 집었는데, 그러면 "제자리를 보고 없었다"(weights_present=False)
            # 가 되어 뿌리를 가리키면 해결되는 상태가 가중치 결손으로 보인다.
            # 자리를 **거절할 때와 같은 값으로** 넘긴다. 넘기지 않으면 카탈로그는
            # 보수적으로 "나가는 연결이 필요하다" 고 답하는데, 그러면 화면은 경고를
            # 띄우고 같은 콘솔의 시도 경로는 그 탐지기를 그냥 세운다 — 방향만
            # 반대인 같은 어긋남이다(실측: `yolo-world-v2-s` 의 CLIP 인코더가
            # 작업 디렉터리에 있어서 거절되지 않는데 화면만 경고했다).
            rows = characteristics(
                asset_root=_ASSET_ROOT,
                runtime_search_paths=self._runtime_asset_search_paths())
        except (OSError, ValueError):
            return {}
        return next((r for r in rows
                     if r.get("implementation_ref") == implementation_ref), {})

    def _trial_declared(self, implementation_ref: str) -> dict:
        """그 탐지기를 **선언된 값으로** 돌리기 위한 재료.

        여기가 "임계값이 코드 상수가 아니다" 가 실제로 성립하는 자리다 — 폼이 수를
        적지 않으면 선언(그리고 운영자 장부)의 값이 들어가고, 각 값의 출처가
        `param_basis` 로 함께 간다. 어휘와 이름 공간도 **선언이 정한다**:
        `"zeroshot"` 을 여기 적어 넣으면 프롬프트를 받지 않는 모델의 라벨이 운영자
        어휘의 기본 하한을 빌리게 되고, 그것이 고치려는 결함이다.
        """
        row = self._detector_row(implementation_ref)
        prompting = row.get("prompting") or {}
        params, basis = self.thresholds().params_for(
            implementation_ref,
            capability_kind=row.get("capability_kind") or None,
            label_namespace=prompting.get("label_namespace") or None,
            accepted=tuple(row.get("accepted_params") or ()) or None,
            operator_values=self._operator_thresholds())
        return {
            "params": params,
            "param_basis": {name: resolved.basis for name, resolved in basis.items()},
            "prompt_free": bool(row.get("prompt_free", False)),
            "taxonomy_vocabulary": prompting.get("taxonomy_vocabulary"),
            "label_namespace": str(prompting.get("label_namespace") or ""),
        }

    def _trial_floor(self, label: str, score: float, vocabulary,
                     label_namespace: str) -> dict:
        """그 라벨·그 점수의 하한 상태. **판정하지 않고 주인에게 묻는다.**

        어휘 라벨은 `ObstacleTaxonomy.score_floor` 가, 어휘에 속하지 않는 라벨
        (프롬프트프리)은 `detection_thresholds` 의 이름 공간 선언이 답한다. 둘 다
        말하지 않으면 `no_floor_declared` 이고 **그 상자를 버리지 않는다**(AI-S-04) —
        세는 것이 전부다.

        `vocabulary` 가 비어 있는(= 어떤 어휘에도 속하지 않는) 탐지기에 대고
        `"zeroshot"` 을 넣지 않는 것이 이 함수의 요점이다. 넣으면 그 어휘의
        `default`(0.25)가 나오고, 그 수는 운영자 어휘의 점수 분포에서 나온 값이라
        모델이 스스로 떠올린 범주에 대해서는 근거가 없다.
        """
        from mission_runtime.perception.obstacle_taxonomy import (  # noqa: PLC0415
            FLOOR_ABOVE,
            FLOOR_BELOW,
            FLOOR_NO_BASIS,
        )

        taxonomy = self.taxonomy()
        if taxonomy is not None and vocabulary:
            floor = taxonomy.score_floor(label, vocabulary=vocabulary,
                                         label_namespace=label_namespace or None)
            if floor.declared:
                return {**floor.as_dict(), "state": floor.state(score),
                        "owner": "obstacle_taxonomy", "threshold_id": None}

        # 어휘가 없거나 어휘가 말하지 않는 라벨. 이름 공간 선언을 본다.
        resolved = self.thresholds().resolve(
            "label_score_floor", label_namespace=label_namespace or None,
            operator_values=self._operator_thresholds())
        if resolved.known:
            state = FLOOR_ABOVE if float(score) >= resolved.value else FLOOR_BELOW
        else:
            state = FLOOR_NO_BASIS
        return {"class_name": str(label), "vocabulary": vocabulary,
                "label_namespace": label_namespace,
                "value": resolved.value, "basis": resolved.basis, "state": state,
                "owner": "detection_thresholds",
                "threshold_id": (None if resolved.declaration is None
                                 else resolved.declaration.threshold_id)}

    def apply_threshold(self, *, caller: Caller, body: dict) -> dict:
        """운영자가 고른 임계값을 **적용한다** — 선언 파일은 고치지 않는다.

        세 가지가 이 메서드의 요점이다.

        1. 선언은 읽기 전용이고 수정은 append-only 장부에 쌓인다. 되돌림도 삭제가
           아니라 `action=reset` 항목이다(AI-L-03). 작성자 없는 수정은 거절된다.
        2. **임계값을 바꾼 것은 다른 실행 구성이다**(AI-B-01). 응답이 바뀐
           `postprocess_ref` 와 구성 지문을 함께 내서 옛 측정값이 새 값에 붙지
           않는다는 사실을 화면이 그대로 읽는다.
        3. 돌려 보는 것(`POST /api/trial-run`)과 적용하는 것은 **다른 경로·다른
           권한**이다. 같은 경로에 두면 화면을 띄운 사람이 운영 값을 바꾼다.
        """
        from mission_runtime.perception.detection_thresholds import (  # noqa: PLC0415
            ThresholdDeclarationError,
        )

        threshold_id = str(body.get("threshold_id") or "")
        if not threshold_id:
            raise ApiError(400, "threshold_id_required")
        reason = str(body.get("reason") or "").strip()
        if not reason:
            # 왜 고쳤는지 없는 수정은 뒤에서 설명할 수 없다.
            raise ApiError(400, "reason_required")
        try:
            declared = self.thresholds().get(threshold_id)
        except ThresholdDeclarationError as error:
            raise ApiError(404, "unknown_threshold") from error
        if self.overlay is None:
            raise ApiError(503, "no_overlay_ledger")

        action = str(body.get("action") or "set")
        if action == "reset":
            entry = self.overlay.reset(KIND_THRESHOLD, threshold_id,
                                       actor=caller.actor, reason=reason)
        elif action == "set":
            if body.get("value") is None:
                raise ApiError(400, "value_required")
            try:
                value = float(body["value"])
            except (TypeError, ValueError) as error:
                raise ApiError(400, "value_not_a_number") from error
            if not declared.permits(value):
                raise ApiError(400, f"value_out_of_bounds:{declared.bounds}")
            entry = self.overlay.record(
                KIND_THRESHOLD, threshold_id,
                {"value": value, "parameter": declared.parameter,
                 "applies_to": declared.applies_to.as_dict(),
                 # 선언값을 **함께 적는다**. 장부만 보고도 무엇을 무엇으로 바꿨는지
                 # 알 수 있어야 하고, 선언이 나중에 바뀌어도 그 사실이 남는다.
                 "declared_value": declared.value,
                 # 어느 시도를 보고 골랐는가. 없으면 빈 문자열이고 0 이 아니다.
                 "trial_fingerprint": str(body.get("trial_fingerprint") or "")},
                actor=caller.actor, reason=reason)
        else:
            raise ApiError(400, f"unknown_action:{action}")

        resolved = self.thresholds().resolve(
            declared.parameter,
            detector_id=declared.applies_to.detector_id,
            capability_kind=declared.applies_to.capability_kind,
            vocabulary=declared.applies_to.vocabulary,
            class_name=declared.applies_to.class_name,
            label_namespace=declared.applies_to.label_namespace,
            operator_values=self._operator_thresholds())
        return {
            "threshold_id": threshold_id,
            "action": entry.action,
            "actor": entry.actor,
            "reason": entry.reason,
            "edited_at": entry.edited_at,
            # 선언과 수정은 **다른 칸**이다. 끝까지 구분된다.
            "declaration": declared.as_row(),
            "effective": resolved.as_dict(),
            "configuration": self._threshold_configuration(declared),
            # 적용은 측정이 아니다. 바뀐 구성의 옛 숫자는 이 값에 대한 것이 아니다.
            "invalidates_prior_measurements": True,
            "history": self.overlay.history(KIND_THRESHOLD, threshold_id),
        }

    def _threshold_configuration(self, declared) -> dict:
        """그 임계값이 들어가는 **실행 구성 축**과, 바뀐 뒤의 지문.

        `postprocess_ref` 가 달라지면 지문이 달라진다 — 임계값 변경이 재측정 의무를
        만드는 것이 선언이 아니라 **자료형의 성질**이라는 뜻이다(AI-B-01).
        `detector_id` 가 없는 선언(이름 공간 하한)은 구성 하나로 좁혀지지 않으므로
        지문을 내지 않는다. 지어내지 않는 것이 맞다.
        """
        from mission_runtime.contracts.profile import (  # noqa: PLC0415
            AXIS_POSTPROCESS,
            ExecutionConfiguration,
        )

        detector_id = declared.applies_to.detector_id
        if not detector_id:
            return {"axis": AXIS_POSTPROCESS, "fingerprint": None,
                    "postprocess_ref": None,
                    "reason": "not_scoped_to_one_implementation"}
        operator = self._operator_thresholds()
        row = self._detector_row(detector_id)
        prompting = row.get("prompting") or {}
        before, _ = self.thresholds().params_for(
            detector_id, label_namespace=prompting.get("label_namespace") or None,
            accepted=tuple(row.get("accepted_params") or ()) or None)
        after, _ = self.thresholds().params_for(
            detector_id, label_namespace=prompting.get("label_namespace") or None,
            accepted=tuple(row.get("accepted_params") or ()) or None,
            operator_values=operator)

        def ref(params: dict) -> str:
            return ",".join(f"{k}={params[k]}" for k in sorted(params))

        def fingerprint(params: dict) -> str:
            return ExecutionConfiguration(
                capability_kind=str(row.get("capability_kind")
                                    or "perception.detect_ovd"),
                implementation_ref=detector_id,
                runtime_ref="", input_profile="",
                postprocess_ref=ref(params)).fingerprint

        return {
            "axis": AXIS_POSTPROCESS,
            "declared_postprocess_ref": ref(before),
            "postprocess_ref": ref(after),
            "declared_fingerprint": fingerprint(before),
            "fingerprint": fingerprint(after),
            "changed": ref(before) != ref(after),
        }

    # --- 돌려 보고 고르기 (AI-B-09 · AI-L-06) -------------------------------

    def _trial_detector(self, implementation_ref: str, vocabulary: list[str],
                        params: dict):
        """구현 참조 하나를 실제 provider 로 세운다. 없으면 **None** 이고 장애가 아니다.

        탐지기 선언이 있으면 그것을 쓰고, 없으면 이 노드에 있는 가중치로 간다 —
        선언이 도착하면 이 함수만 그 쪽을 보게 되고 호출자는 그대로다.
        """
        if _ASSET_ROOT is None:
            return None
        try:
            from mission_runtime.edge.detector_catalog import provider_for  # noqa: PLC0415
        except ImportError:
            provider_for = None
        if provider_for is not None:
            # **세우기 전에 나가는 연결이 필요한지 본다.** 선언이 외부 자산을
            # 요구하는데 그 자산을 추론 런타임이 찾을 자리에 없으면, 세우는 행위
            # 자체가 수백 MB 를 끌어온다 — 실측: 프롬프트형 YOLOE 의 텍스트
            # 인코더가 572MB 이고, 콘솔 CWD 에서는 찾지 못해 네트워크로 간다.
            # 판정은 카탈로그가 하고(`outbound_network_reason`) 이쪽은 런타임이
            # 보는 자리만 넘긴다 — 같은 판정을 두 곳에서 하지 않는다.
            refusal = self._would_reach_network(implementation_ref)
            if refusal is not None:
                return refusal
            return provider_for(implementation_ref, vocabulary=vocabulary,
                                params=params, asset_root=_ASSET_ROOT)

        # 선언이 아직 없는 배치의 차선 경로. 아는 구현 하나만 세운다 — 모르는
        # 참조를 비슷한 가중치로 바꿔 세우지 않는다(그러면 운영자가 고른 것과
        # 돌아간 것이 달라진다).
        from mission_runtime.edge.yolo_world_provider import (  # noqa: PLC0415
            YoloWorldPerceptionProvider,
        )

        known = {"yolov8s-worldv2": _ASSET_ROOT / "weights" / "yolo" / "yolov8s-worldv2.pt"}
        weights = known.get(implementation_ref)
        if weights is None or not weights.exists() or not vocabulary:
            return None
        return YoloWorldPerceptionProvider(
            vocabulary, weights, device="cpu",
            conf=float(params.get("conf", 0.10)))

    #: 추론 런타임이 **외부 자산을 찾는 자리들.** 가중치와 다르다 — 가중치는 우리가
    #: 경로를 넘겨 읽히지만 외부 자산은 라이브러리가 자기 자리에서 찾고 없으면
    #: 받아 온다(ultralytics: 작업 디렉터리와 자기 weights_dir). **선언된 상대 경로
    #: 그대로** 본다. 파일명만 보면 `weights/clip/ViT-B-32.pt` 를 `<repo>/ViT-B-32.pt`
    #: 에서 찾게 되어 **실제로 잘 돌던 YOLO-World 를 거짓으로 거절한다**(한 번
    #: 그랬다). 자산 뿌리는 넣지 않는다 — 거기 있어도 런타임이 보지 않는다.
    @staticmethod
    def _runtime_asset_search_paths() -> tuple:
        from pathlib import Path  # noqa: PLC0415

        return (Path.cwd(), Path.cwd().parent)

    @classmethod
    def _would_reach_network(cls, implementation_ref: str) -> str | None:
        """세우면 나가는 연결이 생기는가. 생기면 **사유 문자열**, 아니면 None.

        다운로드는 배포가 하는 일이다(AI-B-02 가 이미지·자산 조달을 소유한다).
        조회와 시도가 그것을 일으키면 운영자 클릭 하나가 폐쇄망 경계를 넘는다.

        **판정은 카탈로그가 한다.** 여기서 하는 일은 *어디를 보는지* 를 넘기는
        것뿐이다 — 그 자리를 아는 쪽은 provider 를 세우는 이 모듈이고, 무엇이
        필요한지를 아는 쪽은 선언이다. 전에는 양쪽이 각자 판정해서 같은 탐지기를
        두고 카탈로그는 "연결 불필요", 이 함수는 "인코더 때문에 연결 필요" 라고
        서로 다르게 말했다(자산 뿌리에는 있고 런타임 자리에는 없는 572MB 인코더).
        같은 사실의 주인이 둘이면 운영 화면과 거절이 어긋난다.
        """
        from trial import REASON_WOULD_REACH_NETWORK  # noqa: PLC0415

        try:
            from mission_runtime.edge.detector_catalog import (  # noqa: PLC0415
                WEIGHTS_SOURCE_REASON,
                DetectorCatalog,
                DetectorCatalogError,
            )
        except ImportError:
            return None
        try:
            detector = DetectorCatalog.from_file().get(implementation_ref)
        except (DetectorCatalogError, OSError, ValueError):
            return None
        reason = detector.outbound_network_reason(
            _ASSET_ROOT, runtime_search_paths=cls._runtime_asset_search_paths())
        if reason is None:
            return None
        if reason == WEIGHTS_SOURCE_REASON:
            return REASON_WOULD_REACH_NETWORK
        return f"{REASON_WOULD_REACH_NETWORK}:{reason}"

    def trial_options(self, *, capability_kind: str | None = None,
                      source_id: str | None = None) -> dict:
        """무엇을 돌려 볼 수 있는가. **돌리지 않는다** — 조회 전용이다.

        후보 목록과 적격 사유는 `ModelDesk` 가 소유하고(AI-L-10), 여기서는 그 위에
        "이 노드에 가중치가 있는가" 와 "고를 수 있는 그림" 을 더한다.
        """
        kind = capability_kind or "perception.detect_ovd"
        bundle = self.labels(source_id)
        try:
            declared = self.models().versions(kind)
        except Exception:  # noqa: BLE001 - 선언이 없는 배치는 정상이다
            declared = []
        try:
            from mission_runtime.edge.detector_catalog import characteristics  # noqa: PLC0415

            # 거절할 때와 같은 자리를 넘긴다 — 화면의 사전 경고와 시도 경로의
            # 거절이 **같은 한 번의 판정**에서 나와야 어긋나지 않는다.
            traits = characteristics(
                asset_root=_ASSET_ROOT,
                runtime_search_paths=self._runtime_asset_search_paths())
        except ImportError:
            # 특성 선언이 아직 없는 배치. **빈 목록으로 두고 그 사실을 적는다** —
            # 없는 특성을 추측해 채우면 운영자가 그것을 선언으로 읽는다.
            traits = []
        return {
            "capability_kind": kind,
            "declared_versions": declared,
            "detectors": traits,
            "detector_declaration_present": bool(traits),
            # 무엇을 **바꿔 가며** 돌려 볼 수 있는가. 선언과 운영자 수정이 다른
            # 칸이고(AI-L-03), 아무도 선언하지 않은 값은 `declared: false` 로 남는다
            # — 0 으로 채우면 운영자가 그것을 선언으로 읽는다(AI-S-08).
            "thresholds": self._threshold_options(traits),
            # 고를 수 있는 그림. 픽셀이 아니라 참조와 꺼낼 자리다(AI-C-08).
            "frames": [{"frame_ref": name,
                        "media": {"path": "/api/media", "kind": "frame",
                                  "source": bundle.source_id, "file": name}}
                       for name in bundle.frames()],
            "frame_count": bundle.frame_count(),
            "max_frames_per_trial": self._trial_max_frames(),
            "label_source": bundle.source_id,
            # "전부 중 고르게 띄워 고른 것" 과 "앞에서 자른 것" 은 다른 묶음이다.
            # 어느 쪽인지 적지 않으면 운영자가 목록을 전부로 읽는다.
            "frame_listing_strategy": bundle.listing_strategy,
        }

    def _threshold_options(self, traits) -> dict:
        """바꿔 볼 수 있는 임계값 목록. **조회이고 아무것도 바꾸지 않는다.**

        선언 행에 그 임계값이 **지금 어느 값으로 쓰이는지**(`effective`)를 붙인다.
        둘을 한 칸에 합치지 않는 이유는 선언 파일과 운영자 장부가 끝까지 구분되어야
        하기 때문이다 — 합치면 "원래 이 값이었다" 를 더는 말할 수 없다(AI-L-03).
        """
        declaration = self.thresholds()
        operator = self._operator_thresholds()
        accepted = {str(row.get("implementation_ref")): list(row.get("accepted_params") or ())
                    for row in (traits or ())}
        rows = []
        for item in declaration.all():
            resolved = declaration.resolve(
                item.parameter,
                detector_id=item.applies_to.detector_id,
                capability_kind=item.applies_to.capability_kind,
                vocabulary=item.applies_to.vocabulary,
                class_name=item.applies_to.class_name,
                label_namespace=item.applies_to.label_namespace,
                operator_values=operator)
            detector_id = item.applies_to.detector_id
            rows.append({
                **item.as_row(),
                "effective": resolved.as_dict(),
                # 이 이름이 그 탐지기에 **실제로 전달되는가**. 전달되지 않는 이름을
                # 폼에 띄우면 운영자가 고친 값이 조용히 버려진다.
                "reaches_provider": (None if detector_id is None
                                     else item.parameter in accepted.get(detector_id, ())),
            })
        return {
            "declaration_present": bool(declaration.threshold_ids),
            "parameters": list(declaration.parameters()),
            "rows": rows,
            # 적용은 조회가 아니다 — 쓰는 이름과 읽는 이름이 겹치지 않는다(AI-O-06).
            "apply_path": "/api/threshold",
            "overlay_kind": KIND_THRESHOLD,
        }

    @staticmethod
    def _trial_max_frames() -> int:
        from trial import MAX_TRIAL_FRAMES  # noqa: PLC0415

        return MAX_TRIAL_FRAMES

    def run_trial(self, *, caller: Caller, body: dict) -> dict:
        """고른 후보들을 **같은 그림들에** 돌린다. 모델을 바꾸지 않는다.

        정답이 있는 프레임이면 적중·거짓 양성까지 세고, 없으면 설명만 낸다 —
        정답 없이 개수를 견주는 것은 비교가 아니다. 정답은 라벨 화면의 사람 검수에서
        오고(AI-L-03), 그래서 모델 비교가 라벨링에 묶여 있다.
        """
        from trial import TrialDesk, candidates_from_body  # noqa: PLC0415

        # 폼이 수를 적지 않으면 **선언된 값**으로 돈다(코드 상수가 아니다).
        candidates = candidates_from_body(body.get("candidates"),
                                          declared=self._trial_declared)
        frame_refs = [str(f) for f in (body.get("frame_refs") or ()) if str(f)]
        source = self.labels(body.get("source") or None)
        root = source._root()
        if root is None:
            from trial import REASON_NO_FRAME_ASSETS  # noqa: PLC0415

            raise ApiError(503, REASON_NO_FRAME_ASSETS)

        def load(frame_ref: str):
            from labeling import LabelingError, resolve_frame  # noqa: PLC0415

            try:
                path = resolve_frame(root, frame_ref)
            except LabelingError:
                return None
            import cv2  # noqa: PLC0415

            image = cv2.imread(str(path))
            if image is None:
                return None
            return image, (image.shape[1], image.shape[0])

        desk = TrialDesk(
            resolver=self._trial_detector,
            frame_loader=load,
            media_ref=lambda ref: {"path": "/api/media", "kind": "frame",
                                   "source": source.source_id, "file": ref},
            # 라벨별 하한 상태를 **세기만** 한다. 판정의 주인은 taxonomy 와 임계값
            # 선언이고, 못 미친 상자도 응답에서 빠지지 않는다(AI-S-04).
            floor_lookup=self._trial_floor,
            capability_kind=str(body.get("capability_kind")
                                or "perception.detect_ovd"))
        return desk.run(candidates=candidates, frame_refs=frame_refs,
                        actor=caller.actor,
                        ground_truth=self._trial_ground_truth(frame_refs))

    def _trial_ground_truth(self, frame_refs) -> dict:
        """사람이 만든 정답에서 그 프레임들의 상자를 꺼낸다. 없으면 빈 사전이다.

        **모델이 낸 상자를 정답으로 쓰지 않는다**(AI-L-02) — 사람이 검수한
        `GroundTruthRecord` 만 본다.
        """
        wanted = set(frame_refs)
        truth: dict[str, list] = {}
        for record in self._ground_truth.values():
            frame = str(getattr(record, "frame_ref", "") or "")
            if frame not in wanted:
                continue
            for box in getattr(record, "boxes", ()):
                label = getattr(box, "final_class", None)
                corner = getattr(box, "final_box", None)
                if not label or corner is None:
                    continue
                truth.setdefault(frame, []).append((str(label), tuple(corner)))
        return truth

    def manage_model(self, *, caller: Caller, body: dict) -> dict:
        """승인·적용·넓히기·되돌리기. 적용은 검증 모드에서 시작한다(AI-L-07)."""
        from deployment import deployable_for  # noqa: PLC0415
        from mission_runtime.runtime.model_assignment import (  # noqa: PLC0415
            MissionRequirement,
        )

        reason = str(body.get("reason") or "").strip()
        if not reason:
            raise ApiError(400, "reason_required")
        step = str(body.get("step") or "")
        models, training = self.models(), self.training()
        try:
            if step == "approve":
                version = str(body.get("version") or "")
                result = training.approve(version, actor=caller.actor, reason=reason)
                target = version
            elif step in ("plan", "apply"):
                device_id = str(body.get("device_id") or "")
                kind = str(body.get("capability_kind") or "")
                if not device_id or not kind:
                    raise ApiError(400, "device_id_and_capability_kind_required")
                requirement = MissionRequirement(
                    mission_id=str(body.get("mission_id") or "operator_request"),
                    capability_kind=kind,
                    min_quality=_optional_float(body.get("min_quality")),
                    max_latency_ms=_optional_float(body.get("max_latency_ms")),
                    allow_unmeasured=bool(body.get("allow_unmeasured")),
                )
                deployable = deployable_for(kind, device_id,
                                            required_tags=body.get("required_tags")
                                            or ("zone-edge",))
                # 적용 신원은 **버전 참조 하나**다. 계보는 그 버전의 승격 기록에서
                # 나온다 — 계보를 따로 들고 오던 길이 어긋난 짝의 자리였다(AI-L-08).
                # 확인된 모양: 후보 sha256-deadbeef… 의 계보를 들고 yolo-world@v2-s
                # 가 올라가, 적용된 버전에서 역추적하면 **다른 산출물**의 학습·검증·
                # 승인에 닿았다. 짝을 검사하지 않고 **둘째 칸을 없앴다.**
                reference = (str(body.get("version_reference"))
                             if body.get("version_reference") else None)
                if step == "plan":
                    return {"step": step,
                            "plan": models.plan(device_id, requirement,
                                                deployable=deployable,
                                                version_reference=reference),
                            "eligibility": models.eligibility(device_id, requirement),
                            # 화면이 고를 행이 계보를 이미 들고 있다 — "계보를 직접
                            # 들고 오는" 길이 바로 그 구멍이었다.
                            "promotions": models.promotions()}
                if reference is None:
                    # 승격된 후보가 없으면 적용하지 않는다. 그 사실을 사유로 말한다.
                    from deployment import REFUSE_NO_APPROVED_CANDIDATE  # noqa: PLC0415

                    return {"step": step, "applied": False,
                            "reason": REFUSE_NO_APPROVED_CANDIDATE}
                result = models.apply(
                    device_id, requirement, deployable=deployable,
                    version_reference=reference, actor=caller.actor, reason=reason)
                target = f"{kind}@{device_id}"
            elif step == "register":
                # 승인과 적용 사이에 **빠져 있던 단계**다. 승인된 후보를 모델 버전으로
                # 올려 두지 않으면 적용할 수 있는 것이 선언 파일의 손으로 적은 버전뿐이고,
                # 그 버전에는 계보가 없다 — 그것이 거짓 기록의 입구였다.
                version = str(body.get("version") or "")
                device_id = str(body.get("device_id") or "")
                kind = str(body.get("capability_kind") or "")
                model_id = str(body.get("model_id") or "")
                if not (version and device_id and kind and model_id):
                    raise ApiError(400, "version_device_kind_and_model_id_required")
                # 지연·메모리는 **실제로 쟀을 때만** 넘어간다. 0 으로 채우면 미측정
                # 후보가 적격이 되고, 배정이 없는 이득을 보고 고른다(AI-O-05).
                result = models.register_learned(
                    training.candidate(version), model_id=model_id,
                    capability_kind=kind, device_id=device_id,
                    actor=caller.actor, reason=reason,
                    measured_latency_ms=_optional_float(body.get("measured_latency_ms")),
                    measured_memory_mb=_optional_float(body.get("measured_memory_mb")))
                target = version
            elif step in ("widen", "rollback"):
                deployment_id = str(body.get("deployment_id") or "")
                if not deployment_id:
                    raise ApiError(400, "deployment_id_required")
                result = (models.widen(deployment_id, actor=caller.actor, reason=reason,
                                       verification_met=bool(
                                           body.get("verification_met", True)))
                          if step == "widen"
                          else models.rollback(deployment_id, actor=caller.actor,
                                               reason=reason))
                target = deployment_id
            else:
                raise ApiError(400, f"unknown_step:{step}")
        except KeyError as error:
            raise ApiError(404, f"unknown_target:{error.args[0] if error.args else ''}") from error
        except ValueError as error:
            raise ApiError(400, str(error)) from error
        if self.overlay is not None:
            self.overlay.record(KIND_MODEL_ASSIGNMENT, target,
                                {"step": step,
                                 **{k: v for k, v in result.items()
                                    if k in ("applied", "advanced", "registered", "reason")}},
                                actor=caller.actor, reason=reason)
        return {"step": step, **result, "deployments": models.deployments()}

    # -- 계정 관리 (관리자) -------------------------------------------------

    def account_list(self, *, caller: Caller) -> dict:
        """관리자 화면이 그리는 계정·권한 표."""
        return {
            "auth_mode": self.accounts.auth_mode,
            "accounts": list(self.accounts.accounts()),
            "roles": {name: sorted(perms) for name, perms in ROLE_PERMISSIONS.items()},
            "all_permissions": sorted(ALL_PERMISSIONS),
            # 예시 자세의 계정은 메모리에만 있다. 화면이 "저장되지 않는다" 를 적을 수
            # 있어야 운영자가 그것을 실제 계정으로 착각하지 않는다.
            "persisted": self.accounts.configured,
        }

    def manage_account(self, *, caller: Caller, body: dict) -> dict:
        """계정 하나의 권한을 고친다. 관리자만 들어온다(라우팅에서 이미 걸렀다)."""
        account_id = str(body.get("account_id") or "")
        action = str(body.get("action") or "")
        if not account_id or not action:
            raise ApiError(400, "account_and_action_required")
        try:
            if action == "grant":
                result = self.accounts.grant(
                    account_id, str(body.get("permission") or ""), actor=caller.actor)
            elif action == "revoke":
                result = self.accounts.revoke(
                    account_id, str(body.get("permission") or ""), actor=caller.actor)
            elif action == "set_role":
                result = self.accounts.set_role(
                    account_id, str(body.get("role") or ""), actor=caller.actor)
            elif action == "disable":
                result = {"account_id": account_id, "change": "disabled",
                          "actor": caller.actor,
                          "account": self.accounts.disable(account_id).as_public()}
            else:
                raise ApiError(400, f"unknown_action:{action}")
        except AccountError as error:
            # 저장소가 거절한 사유를 그대로 올린다 — "역할이 주는 능력이다",
            # "마지막 관리자를 잠근다" 는 화면이 사람 말로 바꿔 보여 줄 것들이다.
            raise ApiError(409, str(error)) from error
        if self.overlay is not None:
            # 권한 변경도 운영자 수정이다. 누가 언제 무엇을 바꿨는지 남아야 한다.
            self.overlay.record(KIND_PERMISSION, account_id,
                                {k: v for k, v in result.items()
                                 if k in ("change", "permission", "role")},
                                actor=caller.actor,
                                reason=str(body.get("reason") or ""))
        return result

    # -- 제어 (별도 계약) ---------------------------------------------------

    def command(self, *, node_id: str, action: str, caller: Caller,
                params: dict | None) -> dict:
        if not caller.may(PERM_COMMAND):
            raise ApiError(403, f"missing_permission:{PERM_COMMAND}")
        if self.commander is None:
            raise ApiError(503, "no_command_path")
        if node_id not in self.fleet.facts:
            raise ApiError(404, "unknown_robot")
        return self.commander.issue(node_id, action, params or {})



# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

_ROUTES_GET = ("/api/bootstrap", "/api/scene", "/api/domain", "/api/zone", "/api/robot",
               "/api/recommend", "/api/subtasks", "/api/explain", "/api/twin",
               "/api/object", "/api/candidates", "/api/transit", "/api/mission",
               "/api/failure", "/api/spatial", "/api/overlay", "/api/lineage",
               "/api/deployment", "/api/calibration", "/api/approval",
               "/api/dashboard",
               "/api/evidence-kinds", "/api/background", "/api/trial")
_ROUTES_POST = ("/api/login", "/api/logout", "/api/assume", "/api/account",
                "/api/command", "/api/correction", "/api/placement", "/api/survey",
                "/api/detection", "/api/pose", "/api/label", "/api/join",
                "/api/join-step", "/api/camera-info", "/api/training", "/api/model",
                "/api/mission-run", "/api/trial-run", "/api/threshold")

#: 바꾸는 경로 → 그 일에 필요한 능력. 표에 없는 경로는 라우팅에서 이미 막힌다.
#: 로그인·로그아웃은 세션을 만드는 쪽이라 이 표에 없다.
_POST_PERMISSIONS: dict[str, str] = {
    "/api/command": PERM_COMMAND,
    "/api/correction": PERM_CORRECT,
    "/api/placement": PERM_EDIT_PLACEMENT,
    "/api/survey": PERM_EDIT_PLACEMENT,
    # 탐지와 자세는 **장치가** 올리는 것이다. 사람 권한이 아니라 장치 등록 권한에
    # 묶이는 것이 맞고, 지금은 장치 인증 경로가 없어 온보딩 권한으로 대신 막는다 —
    # 그 한계를 숨기지 않기 위해 여기 적어 둔다(인수인계 문서 참고).
    "/api/detection": PERM_ONBOARD,
    "/api/pose": PERM_ONBOARD,
    "/api/account": PERM_MANAGE_ACCOUNTS,
    "/api/label": PERM_LABEL,
    # 배포 네 가지는 서로 다른 능력이다. 한 묶음으로 두면 라벨 작업자에게 모델
    # 교체 권한이, 운영자에게 학습 실행 권한이 함께 간다.
    "/api/join": PERM_ONBOARD,
    "/api/join-step": PERM_ONBOARD,
    "/api/camera-info": PERM_CALIBRATE,
    "/api/training": PERM_TRAIN,
    # 승인·적용은 학습을 돌린 사람과 **다른 사람** 이어야 한다(AI-L-06). 그래서
    # 승인이 /api/training 이 아니라 여기 있다.
    "/api/model": PERM_DEPLOY_MODEL,
    # 임무를 **진행시키는** 것은 조회가 아니다. 계획(`GET /api/mission`)은 누구나
    # 읽을 수 있지만 한 걸음 내딛는 것은 명령 능력이 있어야 한다(AI-C-19).
    "/api/mission-run": PERM_COMMAND,
    # 돌려 보는 것은 **모델을 바꾸는 것이 아니다.** 추론을 돌릴 뿐이므로 배포 권한이
    # 아니라 학습 권한 쪽에 둔다 — 라벨 작업자가 어느 모델이 이 그림에서 어떻게
    # 보는지 확인하는 것이 이 기능의 목적이고, 그 사람에게 모델 교체 권한을 함께
    # 주면 안 된다(AI-L-06: 승인은 다른 사람이어야 한다).
    "/api/trial-run": PERM_TRAIN,
    # **돌려 보는 것과 적용하는 것은 다른 권한이다.** 시도는 추론만 돌리고 아무것도
    # 바꾸지 않지만, 임계값 적용은 운영 중인 탐지가 무엇을 내보내는지를 바꾼다 —
    # 모델 버전을 갈아 끼우는 것과 같은 종류의 행위이고(AI-B-01: 임계값을 바꾼 것은
    # 다른 실행 구성이다) 그래서 배포 권한 쪽에 둔다. 같은 권한에 두면 돌려 보라고
    # 권한을 준 사람이 운영 값까지 바꾼다(AI-L-06: 승인은 다른 사람이어야 한다).
    "/api/threshold": PERM_DEPLOY_MODEL,
}


def _gate_from(body: dict):
    """요청이 통과 기준을 선언했으면 그것을, 아니면 None(기본 기준).

    기준을 요청에서 받는 것은 AI-L-05 가 기준을 고정하지 말라고 요구하기
    때문이다. 대신 적용한 값이 응답과 계보에 남아, 기준을 낮춰 통과시킨 것과
    기준을 넘은 것이 뒤에서 구분된다.
    """
    keys = ("min_new_accuracy", "max_regression", "forbid_label_loss")
    if not any(k in body for k in keys):
        return None
    from mission_runtime.continual.parameter_evaluation import (  # noqa: PLC0415
        EvaluationGate,
    )

    defaults = EvaluationGate()
    try:
        return EvaluationGate(
            min_new_accuracy=float(body.get("min_new_accuracy",
                                            defaults.min_new_accuracy)),
            max_regression=float(body.get("max_regression", defaults.max_regression)),
            forbid_label_loss=bool(body.get("forbid_label_loss",
                                            defaults.forbid_label_loss)),
        )
    except (TypeError, ValueError) as error:
        raise ApiError(400, f"bad_gate:{error}") from error


def _optional_float(value: Any) -> float | None:
    """빈 칸은 **조건 없음**이고 0 이 아니다. 0 으로 읽으면 모든 후보가 통과한다."""
    if value is None or value == "":
        return None
    return float(value)


def _single(query: dict[str, list[str]], key: str, default: str | None = None) -> str | None:
    values = query.get(key)
    return values[0] if values else default


class FmsHandler(BaseHTTPRequestHandler):
    # 응답 머리의 판과 공표한 스키마의 판은 **같아야 한다** — 한쪽만
    # 올리면 그것을 믿은 뷰어가 틀린다.
    server_version = f"FMS/{VIEW_CONTRACT_VERSION}"
    service: FmsService  # 서버가 심는다

    # 요청 로그는 콘솔을 가린다 — 오류만 남긴다.
    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def log_error(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("fms: " + (fmt % args) + "\n")

    # -- 응답 도우미 -------------------------------------------------------

    def _send(self, status: int, body: bytes, content_type: str,
              *, set_cookie: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if set_cookie is not None:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: dict, *, session_token: str | None = None,
              clear_session: bool = False) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        cookie = None
        if session_token is not None:
            # HttpOnly: 페이지 스크립트가 토큰을 읽을 수 없게 한다 — 읽을 수 있으면
            # 스크립트 주입 하나로 세션이 새어 나간다. SameSite=Strict: 다른 사이트에서
            # 온 요청에 쿠키를 붙이지 않는다(CSRF). Secure 는 붙이지 않는다 — 현장
            # 배포가 평문 HTTP 인 구간이 있고, 붙이면 그 구간에서 로그인이 아예 안 된다.
            # 그 한계를 숨기지 않기 위해 여기 적어 둔다.
            cookie = (f"{SESSION_COOKIE}={session_token}; Path=/; HttpOnly; "
                      "SameSite=Strict")
        elif clear_session:
            cookie = f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
        self._send(status, body, "application/json; charset=utf-8", set_cookie=cookie)

    def _error(self, status: int, reason: str) -> None:
        self._json(status, {"error": reason})

    def _session_token(self) -> str | None:
        """요청에서 세션 토큰을 꺼낸다.

        헤더와 쿠키 둘 다 받는다 — 브라우저는 쿠키가 편하고(새로고침에도 남는다),
        스크립트·다른 뷰어는 `Authorization: Bearer` 가 편하다. **질의 인자로는 받지
        않는다**: 질의 문자열은 서버 접근 로그와 브라우저 이력에 그대로 남고, 그러면
        토큰이 비밀이 아니게 된다.
        """
        header = self.headers.get("Authorization") or ""
        if header.startswith("Bearer "):
            return header[len("Bearer "):].strip() or None
        cookie = self.headers.get("Cookie") or ""
        for part in cookie.split(";"):
            name, _, value = part.strip().partition("=")
            if name == SESSION_COOKIE and value:
                return value
        return None

    def _caller(self) -> Caller:
        return self.service.accounts.caller(self._session_token())

    def _locale(self, query: dict[str, list[str]]) -> str:
        """언어는 표시 설정이고 권한이 아니다 — 그래서 질의 인자로 남는다."""
        locale = _single(query, "locale", DEFAULT_LOCALE) or DEFAULT_LOCALE
        if locale not in STRINGS:
            raise ApiError(400, "unknown_locale")
        return locale

    def _require(self, permission: str) -> Caller:
        """능력이 없으면 **본문을 읽기 전에** 끊는다.

        401 과 403 을 구분한다 — 들어오지 않았으니 로그인하라는 것과, 들어왔지만 그
        일은 못 한다는 것은 화면이 다르게 그려야 하는 서로 다른 상태다.
        """
        caller = self._caller()
        if caller.may(permission):
            return caller
        if caller.actor == "unauthenticated":
            raise ApiError(401, "login_required")
        raise ApiError(403, f"missing_permission:{permission}")

    def _assume(self, body: dict) -> None:
        """예시 계정을 골라 들어온다 — 예시 자세에서만.

        역할이 아니라 계정을 고른다. 역할을 고르게 하면 관리자가 한 사람에게
        부여한 능력이 그 사람에게 생기지 않는다.
        """
        account_id = str(body.get("account") or body.get("role") or "")
        if not account_id:
            raise ApiError(400, "account_required")
        try:
            session, reason = self.service.accounts.assume_account(account_id)
        except AccountError as error:
            raise ApiError(400, str(error)) from error
        if session is None:
            # 계정이 있는 배포에서 이 길은 닫혀 있다. 403 으로 "지금은 비밀번호로
            # 들어와야 한다" 를 말한다.
            return self._json(403, {"error": reason})
        return self._json(200, self.service.accounts.identify(session.token),
                          session_token=session.token)

    def _login(self, body: dict) -> None:
        """계정으로 들어온다. 실패 사유를 자세히 말하지 않는다.

        어느 계정이 존재하는지 알려 주지 않기 위해서다 — 저장소가 이미 "없는 계정"과
        "틀린 비밀번호"를 같은 사유로 돌려주므로, 여기서 그것을 더 쪼개지 않는다.
        """
        account_id = str(body.get("account_id") or "")
        password = str(body.get("password") or "")
        if not account_id or not password:
            raise ApiError(400, "account_and_password_required")
        session, reason = self.service.accounts.login(account_id, password)
        if session is None:
            return self._json(401, {"error": reason})
        return self._json(200, self.service.accounts.identify(session.token),
                          session_token=session.token)

    # -- GET ---------------------------------------------------------------

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            locale = self._locale(query)
            if parsed.path.endswith(".js") and "/" not in parsed.path[1:]:
                # 콘솔이 쓰는 스크립트 한 묶음. 이름에 디렉터리가 들어간 경로는
                # 여기서 받지 않는다 — 받으면 이 경로가 파일 읽기 도구가 된다.
                asset = UI_DIR / parsed.path.lstrip("/")
                if not asset.is_file():
                    raise ApiError(404, "unknown_script")
                return self._send(200, asset.read_bytes(),
                                  "text/javascript; charset=utf-8")
            if parsed.path in ("/", "/index.html"):
                # 페이지 자체는 누구에게나 준다 — 로그인 화면이 그 안에 있다. 페이지를
                # 막으면 로그인할 자리가 없어진다.
                page = (UI_DIR / "index.html").read_bytes()
                return self._send(200, page, "text/html; charset=utf-8")
            if parsed.path == "/api/identity":
                # 누구인지 묻는 것은 권한이 필요 없다 — 답이 "아무도 아니다" 일 수
                # 있어야 화면이 로그인 폼을 그릴 수 있다.
                return self._json(200, self.service.accounts.identify(
                    self._session_token()))

            # 여기부터는 전부 조회 권한이 필요하다. 계정이 없는 설치에서는 조회가
            # 열려 있고(그 사실을 /api/identity 가 말한다), 계정이 하나라도 생기면
            # 익명 조회는 닫힌다.
            caller = self._require(PERM_VIEW)
            if parsed.path == "/api/bootstrap":
                return self._json(200, self.service.bootstrap(caller=caller, locale=locale))
            if parsed.path == "/api/scene":
                return self._json(200, self.service.scene())
            if parsed.path == "/api/domain":
                domain_id = _single(query, "id")
                if not domain_id:
                    raise ApiError(400, "id_required")
                return self._json(200, self.service.domain(domain_id))
            if parsed.path == "/api/zone":
                zone_id = _single(query, "id")
                if not zone_id:
                    raise ApiError(400, "id_required")
                return self._json(200, self.service.zone(zone_id))
            if parsed.path == "/api/robot":
                node_id = _single(query, "id")
                if not node_id:
                    raise ApiError(400, "id_required")
                return self._json(200, self.service.robot(
                    node_id, _single(query, "zone"), caller=caller))
            if parsed.path == "/api/recommend":
                node_id = _single(query, "robot")
                if not node_id:
                    raise ApiError(400, "robot_required")
                return self._json(200, {"recommendations": self.service.recommend(
                    node_id, _single(query, "zone"), caller=caller)})
            if parsed.path == "/api/subtasks":
                node_id = _single(query, "robot")
                goal_kind = _single(query, "function")
                if not node_id or not goal_kind:
                    raise ApiError(400, "robot_and_function_required")
                return self._json(200, self.service.subtasks(
                    node_id, _single(query, "zone"), goal_kind, caller=caller))
            if parsed.path == "/api/samples":
                return self._json(200, self.service.appearance_samples())
            if parsed.path == "/api/explain":
                # 경로 자체가 없는 배치에서 인자 타박을 먼저 하면, 뷰어는 "인자를
                # 고치면 될 것"으로 읽고 영원히 다시 묻는다. 없는 것이 기능이면
                # 그것을 먼저 말한다 — 503 `no_evidence_path:<사유>`(AI-C-05).
                self.service.require_evidence_path()
                sample_class = _single(query, "class")
                sample_file = _single(query, "file")
                if not sample_class or not sample_file:
                    raise ApiError(400, "class_and_file_required")
                return self._json(200, self.service.explain(
                    sample_class=sample_class, sample_file=sample_file, caller=caller))
            if parsed.path == "/api/media":
                payload, media_type = self.service.media_bytes(
                    kind=_single(query, "kind", "appearance") or "appearance",
                    # 프레임에서는 `source`, 외형 사진에서는 `class` 가 묶음 이름이다.
                    sample_class=(_single(query, "source")
                                  or _single(query, "class") or ""),
                    sample_file=_single(query, "file") or "")
                return self._send(200, payload, media_type)
            if parsed.path == "/api/twin":
                zone_id = _single(query, "zone")
                if not zone_id:
                    raise ApiError(400, "zone_required")
                return self._json(200, self.service.twin_view(zone_id, caller=caller))
            if parsed.path == "/api/object":
                caller = self._require(PERM_SEE_INTERNALS)
                object_id = _single(query, "id")
                if not object_id:
                    raise ApiError(400, "id_required")
                return self._json(200, self.service.object_trace(
                    object_id, about=_single(query, "about", "position"), caller=caller))
            if parsed.path == "/api/label/tasks":
                caller = self._require(PERM_LABEL)
                return self._json(200, self.service.label_tasks(
                    _single(query, "source"), caller=caller))
            if parsed.path == "/api/label/task":
                caller = self._require(PERM_LABEL)
                frame_name = _single(query, "frame")
                if not frame_name:
                    raise ApiError(400, "frame_required")
                return self._json(200, self.service.label_task(
                    frame_name, source_id=_single(query, "source"), caller=caller))
            if parsed.path == "/api/accounts":
                caller = self._require(PERM_MANAGE_ACCOUNTS)
                return self._json(200, self.service.account_list(caller=caller))
            if parsed.path == "/api/lineage":
                lineage_id = _single(query, "id")
                if not lineage_id:
                    raise ApiError(400, "id_required")
                return self._json(200, self.service.lineage(lineage_id, caller=caller))
            if parsed.path == "/api/candidates":
                return self._json(200, self.service.learning_candidates(caller=caller))
            if parsed.path == "/api/transit":
                node_id = _single(query, "robot")
                if not node_id:
                    raise ApiError(400, "robot_required")
                return self._json(200, self.service.transit_status(node_id, caller=caller))
            if parsed.path == "/api/mission":
                node_id = _single(query, "robot")
                goal_kind = _single(query, "function")
                if not node_id or not goal_kind:
                    raise ApiError(400, "robot_and_function_required")
                zones = tuple(z for z in (_single(query, "zones", "") or "").split(",") if z)
                return self._json(200, self.service.mission_plan(
                    node_id=node_id, goal_kind=goal_kind, zones=zones, caller=caller))
            if parsed.path == "/api/background":
                # 도메인을 적지 않으면 **현장** 그림을 묻는 것이다. 메인 맵이 그
                # 그림 위에 그려지므로 이 경로에 기본값이 있어야 한다.
                return self._json(200, self.service.background(
                    domain_id=_single(query, "domain") or None,
                    level_id=_single(query, "level") or None,
                    zone_id=_single(query, "zone") or None))
            if parsed.path == "/api/evidence-kinds":
                robot = _single(query, "robot")
                available: tuple[str, ...] = ()
                if robot:
                    if robot not in self.service.fleet.facts:
                        raise ApiError(404, "unknown_robot")
                    available = tuple(self.service.fleet.available_kinds(
                        robot, zone_id=_single(query, "zone") or None))
                return self._json(200, self.service.evidence_kinds(
                    capability=_single(query, "capability") or None,
                    available=available))
            if parsed.path == "/api/failure":
                caller = self._require(PERM_SEE_INTERNALS)
                subject = _single(query, "subject")
                if not subject:
                    raise ApiError(400, "subject_required")
                return self._json(200, self.service.failure_trace(
                    subject_id=subject, caller=caller))
            if parsed.path == "/api/spatial":
                zone_id = _single(query, "zone")
                if not zone_id:
                    raise ApiError(400, "zone_required")
                return self._json(200, self.service.spatial_state(zone_id, caller=caller))
            if parsed.path == "/api/overlay":
                caller = self._require(PERM_SEE_INTERNALS)
                return self._json(200, self.service.overlay_log(
                    kind=_single(query, "kind"), target_id=_single(query, "target")))
            if parsed.path == "/api/dashboard":
                # `pin=` 은 기준 노드 고정(§2) 이고 관찰 방식의 변경이다. 빈 값이
                # 고정 해제이므로 "인자 없음"과 "빈 인자"를 가른다.
                pin = _single(query, "pin")
                return self._json(200, self.service.dashboard(
                    pin=pin if "pin" in query else None))
            if parsed.path == "/api/trial":
                # **무엇을 돌려 볼 수 있는가** — 기능별 선언된 후보, 이 노드에
                # 가중치가 있는지, 그리고 고를 수 있는 그림들. 돌리지는 않는다.
                return self._json(200, self.service.trial_options(
                    capability_kind=_single(query, "capability_kind"),
                    source_id=_single(query, "source")))
            if parsed.path == "/api/deployment":
                return self._json(200, self.service.deployment_view(caller=caller))
            if parsed.path == "/api/calibration":
                device_id = _single(query, "device")
                if not device_id:
                    raise ApiError(400, "device_required")
                return self._json(200, self.service.calibration_view(
                    device_id, caller=caller))
            if parsed.path == "/api/approval":
                version = _single(query, "version")
                if not version:
                    raise ApiError(400, "version_required")
                return self._json(200, self.service.approval_info(version, caller=caller))
            return self._error(404, "unknown_path")
        except ApiError as error:
            return self._error(error.status, error.reason)
        except FileNotFoundError:
            return self._error(500, "page_missing")
        except Exception as error:  # noqa: BLE001 - 아래 주석 참고
            # 하위 시스템 하나가 터져도 **빈 응답**을 내보내지 않는다. 빈 본문은
            # 화면에서 "읽는 중"으로 영원히 남아 고장을 숨긴다. 종류를 적어 내보내고
            # 서버 로그에 전체 추적을 남긴다(AI-C-05: 선택 기능 장애를 전체 실패로
            # 취급하지 않는다).
            self.log_error("%s %s failed: %s", self.command, self.path,
                           type(error).__name__)
            import traceback

            traceback.print_exc(file=sys.stderr)
            return self._error(500, f"subsystem_failed:{type(error).__name__}")

    # -- POST (상태 뷰가 아니라 별도 계약) ----------------------------------

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path not in _ROUTES_POST:
            # 조회 경로로는 아무것도 바꿀 수 없다 — AI-O-06.
            return self._error(405, "read_only_path")
        try:
            self._locale(parse_qs(parsed.query))
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw or b"{}")
            if not isinstance(body, dict):
                raise ApiError(400, "body_must_be_object")

            # 로그인·로그아웃은 세션을 **만드는** 경로이므로 세션을 요구할 수 없다.
            if parsed.path == "/api/login":
                return self._login(body)
            if parsed.path == "/api/assume":
                # 예시 자세에서 비밀번호 없이 역할을 고르는 길. 계정이 하나라도
                # 있으면 저장소가 거절한다 — 여기서 그 판정을 복제하지 않는다.
                return self._assume(body)
            if parsed.path == "/api/logout":
                self.service.accounts.logout(self._session_token() or "")
                return self._json(200, {"logged_out": True}, clear_session=True)

            # 바꾸는 경로마다 **그 일에 필요한 능력**만 요구한다. 하나의 큰 권한으로
            # 묶으면 GT 만 만들 사람에게 로봇을 움직일 권한까지 주게 된다.
            caller = self._require(_POST_PERMISSIONS[parsed.path])

            if parsed.path == "/api/command":
                return self._json(202, self.service.command(
                    node_id=body.get("robot", ""), action=body.get("action", ""),
                    caller=caller, params=body.get("params")))
            if parsed.path == "/api/placement":
                return self._json(202, self.service.placement(caller=caller, body=body))
            if parsed.path == "/api/label":
                return self._json(202, self.service.submit_labels(
                    caller=caller, body=body))
            if parsed.path == "/api/account":
                return self._json(202, self.service.manage_account(
                    caller=caller, body=body))
            if parsed.path == "/api/survey":
                return self._json(202, self.service.survey(caller=caller, body=body))
            if parsed.path == "/api/detection":
                return self._json(202, self.service.ingest_detection(caller=caller, body=body))
            if parsed.path == "/api/mission-run":
                robot = str(body.get("robot") or "")
                goal_kind = str(body.get("goal_kind") or "")
                if not robot or not goal_kind:
                    raise ApiError(400, "robot_and_goal_kind_required")
                zones = tuple(str(z) for z in (body.get("zones") or ()))
                return self._json(200, self.service.mission_run(
                    node_id=robot, goal_kind=goal_kind,
                    zone_id=(str(body["zone"]) if body.get("zone") else None),
                    zones=zones, caller=caller))
            if parsed.path == "/api/pose":
                return self._json(202, self.service.report_pose(caller=caller, body=body))
            if parsed.path == "/api/join":
                return self._json(202, self.service.join_device(caller=caller, body=body))
            if parsed.path == "/api/join-step":
                return self._json(202, self.service.resolve_join_step(
                    caller=caller, body=body))
            if parsed.path == "/api/camera-info":
                return self._json(202, self.service.submit_camera_info(
                    caller=caller, body=body))
            if parsed.path == "/api/training":
                return self._json(202, self.service.run_training(caller=caller, body=body))
            if parsed.path == "/api/model":
                return self._json(202, self.service.manage_model(caller=caller, body=body))
            if parsed.path == "/api/trial-run":
                return self._json(200, self.service.run_trial(caller=caller, body=body))
            if parsed.path == "/api/threshold":
                # 선언을 덮지 않고 장부에 쌓는다. 202 인 이유는 적용이 **요청**이고
                # 그 값이 실제로 쓰이는 시점은 다음 반영(runtime/refresh.py)이라서다.
                return self._json(202, self.service.apply_threshold(
                    caller=caller, body=body))
            return self._json(202, self.service.correction(caller=caller, body=body))
        except ApiError as error:
            return self._error(error.status, error.reason)
        except json.JSONDecodeError:
            return self._error(400, "body_not_json")
        except Exception as error:  # noqa: BLE001 - do_GET 의 같은 이유
            self.log_error("%s %s failed: %s", self.command, self.path,
                           type(error).__name__)
            import traceback

            traceback.print_exc(file=sys.stderr)
            return self._error(500, f"subsystem_failed:{type(error).__name__}")


UI_DIR = _CONSOLE_DIR


# ---------------------------------------------------------------------------
# 조립
# ---------------------------------------------------------------------------


def _load_status_ui():
    """`tools/status_ui/serve.py` 를 **경로로** 싣는다.

    두 도구의 진입 파일 이름이 모두 `serve.py` 라서 `import serve` 는 먼저 올라온
    쪽을 집는다 — 이 파일이 `serve` 로 올라와 있으면 자기 자신을 다시 집는다.
    이름이 아니라 경로로 실어 그 모호함을 없앤다.
    """
    import importlib.util

    path = _PROJECT_DIR / "tools" / "status_ui" / "serve.py"
    spec = importlib.util.spec_from_file_location("mission_runtime_status_ui_serve", path)
    if spec is None or spec.loader is None:  # pragma: no cover - 파일이 있으면 생기지 않는다
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_service(
    *,
    ui_config: str | Path,
    zone_profile: str | Path,
    goal_kinds: str | Path,
    discovery: Discovery | None = None,
    with_fleet: bool = True,
    broker: tuple[str, int] | None = None,
    overlay_path: str | Path | None = None,
    accounts_path: str | Path | None = None,
) -> FmsService:
    """실제 설정에서 서비스를 만든다. 가짜 데이터를 넣지 않는다.

    `with_fleet` 이면 선언된 로봇들을 정본 wire 위에 세우고 **공지로** 탐지한다 —
    선언을 탐지로 바꿔 읽지 않는다(AI-C-18). `broker` 를 주면 실제 MQTT 브로커를
    쓰고, 없으면 같은 Protocol 의 in-process 전송을 쓴다. 두 경우 모두 코드 경로는
    같다 — 다른 것은 provider 뿐이다(AI-C-06).
    """
    status_ui = _load_status_ui()

    config = status_ui.load_ui_config(ui_config)
    status = status_ui.StatusService(config)
    resolved_fleet = status.fleet()
    facts = robot_facts_from_fleet(resolved_fleet)
    functions = tuple(
        {
            "function_id": entry.function_id,
            "required_capabilities": list(entry.required_capabilities),
            "optional_capabilities": list(entry.optional_capabilities),
        }
        for entry in config.functions
    )
    # 운영자가 고친 값을 먼저 읽는다 — 재시작해도 수정이 살아 있어야 하고, 선언
    # 프로파일은 그대로 두고 위에 덧댄다(원본과 사람이 고친 값을 끝까지 구분한다).
    # 자리를 주지 않으면 사용자 상태 디렉터리다. 설치 트리 안에 쓰지 않는 이유는
    # `overlay.py` 의 "설치 트리 밖, 그러나 사용자 상태 디렉터리 안" 절에 적었다.
    overlay = OperatorOverlay(
        path=Path(overlay_path) if overlay_path else default_overlay_path())
    # 배경 선언을 실제로 읽는다. 지금까지 `FleetModel.map_tiles` 는 늘 None 이었고,
    # 그래서 `config/map_tiles.example.json` 은 **아무 데도 닿지 않는 파일**이었다.
    # 선언 파일이 없는 설치도 정상이다 — 그때는 배경이 없는 배치다(AI-C-16).
    tiles_path = _PROJECT_DIR / "config" / "map_tiles.example.json"
    tiles = load_map_tiles(tiles_path) if tiles_path.is_file() else None
    model = FleetModel(
        domain_profile=load_domain_profile(zone_profile),
        facts=facts,
        functions=functions,
        discovery=discovery or Discovery(),
        placement_overrides=overlay.current_payloads(KIND_PLACEMENT),
        map_tiles=tiles,
    )
    service = FmsService(
        fleet=model,
        manifest_path=Path(config.providers_manifest),
        goal_kinds_path=Path(goal_kinds),
        overlay=overlay,
        # 계정 파일이 없으면 계정이 없는 설치다 — 조회만 열리고 그 사실을
        # `/api/identity` 가 말한다. 기본 계정을 만들어 두지 않는다(AI-B-02).
        # 쓰기 상태의 자리는 한 곳이 정한다(`state_root()`) — 설치 트리 안에 쓰면
        # 설치된 패키지를 고치는 것이 되고, 상위 `local/` 을 가정하면 클론한 사람에게
        # 없는 경로가 된다.
        accounts=AccountStore(
            path=Path(accounts_path) if accounts_path
            else state_root() / "fms_accounts" / "accounts.json"),
        declared_demand=_declared_demand(resolved_fleet),
        # 구역 B~I 의 조립을 **정본 하나에서** 가져온다. 콘솔이 같은 조립을 다시
        # 하면 두 화면이 서로 다른 답을 말한다(CLAUDE.md §0, AI-O-06).
        status=status,
    )
    if with_fleet:
        # 설정 파일의 자리를 그대로 넘긴다. 어휘를 역할 이름 표에서만 찾으면 표에 없는
        # 역할의 장치가 세워지지 않고, 그러면 "확장은 등록이지 코드 수정이 아니다"가
        # 깨진다 — 선언한 `declared_actions` 를 읽으려면 그 자리를 알아야 한다.
        service.commander = _start_fleet(model, broker, config_path=ui_config)
    return service


def _declared_demand(resolved: dict) -> dict[str, dict]:
    """노드별 선언 수요. `StatusService.fleet()` 의 과금 규칙을 **그대로 읽는다**.

    그 규칙은 그 함수의 docstring 이 적는다 — kind 는 한 번만 세고 `served[kind][0]`,
    즉 priority 가 낮고 비용이 낮은 제공자가 있는 노드에 과금한다. 여기서 다시
    고르지 않는 이유는 CLAUDE.md §0 에 적힌 것과 같다: 콘솔이 같은 판정을 다시 하면
    두 화면이 서로 다른 답을 말한다.

    implements: AI-O-05 (계층별 자원 지표 — 하드웨어 칸과 서비스 칸을 가른다),
    AI-B-04 (선언된 자원 규약)
    """
    demand: dict[str, dict] = {}
    for kind, entries in (resolved.get("served") or {}).items():
        if not entries:
            continue
        charged = entries[0]
        node_id = charged.get("node_id")
        if not node_id:
            continue
        row = demand.setdefault(node_id, {"compute_units": 0.0, "memory_mb": 0.0,
                                          "kinds": []})
        cost = charged.get("cost") or {}
        row["compute_units"] += float(cost.get("compute_units") or 0.0)
        row["memory_mb"] += float(cost.get("memory_mb") or 0.0)
        row["kinds"].append({"kind": kind, "provider_id": charged.get("provider_id"),
                             "state": charged.get("state"),
                             "compute_units": cost.get("compute_units"),
                             "memory_mb": cost.get("memory_mb")})
    for row in demand.values():
        row["compute_units"] = round(row["compute_units"], 3)
        row["memory_mb"] = round(row["memory_mb"], 3)
        row["kinds"].sort(key=lambda item: item["kind"])
    return demand


def _start_fleet(model: FleetModel, broker: tuple[str, int] | None,
                 *, config_path: str | Path | None = None):
    """선언된 로봇을 세우고 공지까지 끝낸다. 실패하면 명령 경로만 없는 채로 돈다."""
    from fleet_runtime import build_runtime  # noqa: PLC0415 - 선택 경로다

    from mission_runtime.registry.capability_registry import CapabilityRegistry

    transport = None
    if broker is not None:
        from mission_runtime.providers.mqtt import MqttTransportProvider

        transport = MqttTransportProvider(broker[0], broker[1], client_id="fms-console")

    placements = {
        declared["node_id"]: model.facts[declared["node_id"]].role
        for zone_id in model.zone_ids()
        for declared in model.zone(zone_id).get("declared_nodes", ())
        if declared["node_id"] in model.facts
    }
    return build_runtime(
        discovery=model.discovery,
        registry=CapabilityRegistry(),
        placements=placements,
        transport=transport,
        config_path=config_path,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the FMS console.")
    # 실제 장치 목록. 예시는 시험이 쓰고 화면은 실제를 쓴다.
    parser.add_argument("--config",
                        default=str(_PROJECT_DIR / "config" / "status_ui.json"))
    # 기본은 **실제** 배치다. 예시 현장은 더 이상 두지 않는다 — 예시를 기본으로 두면
    # 화면에 보이는 것이 실제인지 예시인지 매번 확인해야 한다.
    parser.add_argument("--domains", "--zones", dest="zones",
                        default=str(_PROJECT_DIR / "profiles" / "domains.json"))
    parser.add_argument("--goal-kinds", default=str(_PROJECT_DIR / "profiles" / "goal_kinds.example.json"))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-fleet", action="store_true",
                        help="선언된 로봇을 세우지 않는다 — 탐지가 전부 비는 화면을 본다")
    parser.add_argument("--broker", default=None, metavar="HOST:PORT",
                        help="실제 MQTT 브로커로 장치 경로를 돌린다 (기본은 in-process)")
    parser.add_argument("--overlay", default=None, metavar="PATH",
                        help="운영자 수정 장부의 자리 "
                             f"(기본: {state_root() / 'fms_overlay'})")
    parser.add_argument("--accounts", default=None, metavar="PATH",
                        help="계정 파일의 자리 "
                             f"(기본: {state_root() / 'fms_accounts'}). 계정이 "
                             "없으면 조회만 열린다 — 첫 계정은 "
                             "`python tools/fms_console/accounts.py add <id> --role admin`")
    args = parser.parse_args(argv)

    broker = None
    if args.broker:
        host, _, port = args.broker.partition(":")
        broker = (host or "127.0.0.1", int(port or 1883))

    service = build_service(
        ui_config=args.config, zone_profile=args.zones, goal_kinds=args.goal_kinds,
        with_fleet=not args.no_fleet, broker=broker, overlay_path=args.overlay,
        accounts_path=args.accounts)

    FmsHandler.service = service
    httpd = ThreadingHTTPServer((args.host, args.port), FmsHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"FMS console: {url}")
    detected = service.fleet.discovery.ids()
    print(f"  domains {len(service.fleet.domain_ids())}  zones {len(service.fleet.zone_ids())}  "
          f"nodes {len(service.fleet.facts)}  functions {len(service.fleet.functions)}")
    print(f"  detected by announcement: {', '.join(detected) if detected else '-'}")
    if broker is not None:
        print(f"  device path: MQTT {broker[0]}:{broker[1]}")
    # 자산이 없는 배치가 정상이라면 그 사실도 기동 시점에 보여야 한다 — 화면에서
    # 탭이 비활성인 것을 보고서야 이유를 찾게 두지 않는다(AI-O-06).
    if _ASSET_ROOT is None:
        print(f"  assets: none (set ${ASSET_ROOT_ENV} to enable model-backed evidence)")
    else:
        print(f"  assets: {_ASSET_ROOT}"
              f"{'' if _ASSET_ROOT.is_dir() else ' (absent)'}")
    appearance = service.appearance()
    if not appearance.available:
        print(f"  evidence path: disabled ({appearance.unavailable_reason})")
    if service.overlay is not None:
        stats = service.overlay.stats()
        print(f"  operator edits: {stats['entry_count']} recorded at {stats['path']}")
    if service.accounts.configured:
        print(f"  accounts: {len(service.accounts.accounts())} at {service.accounts.path}")
    else:
        # 잠기지 않은 문을 조용히 두지 않는다. 읽기만 열려 있다는 사실을 띄운다.
        print(f"  accounts: none configured at {service.accounts.path} — "
              "read-only until you create one "
              "(python tools/fms_console/accounts.py add <id> --role admin)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
