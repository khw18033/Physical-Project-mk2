"""확장이 **설정인가 코드인가** 를 다섯 번 실제로 해 보고 그 답을 고정한다.

implements: AI-B-09 (신규 확장 등록·호환성 검증), AI-C-15 (도메인·배포 프로파일 분리),
            AI-C-18 (구성요소 capability 선언 규약), AI-C-10 (기능·자원 등록·탐색),
            AI-C-05 (핵심·선택 기능 격리), AI-S-06 (이종 근거의 점진적 통합),
            AI-O-06 (통합 운영 상태 뷰)
관련: AI-C-20 (물리 명령 의미 계약), AI-C-02 (좌표계 경계), AI-C-04 (provider 경계)
tests: 새 도메인·구역 선언이 받아들여지고 콘솔이 그것을 그대로 서비스한다 ·
       처음 보는 명령 어휘를 적은 조인 선언이 받아들여져 설정 한 줄이 된다 ·
       새 provider 등록만으로 기능이 DISABLED→ACTIVE 로 바뀌고 태그 없는 노드에서는
       빠진 태그 이름과 함께 DISABLED 로 남는다 · 새 공간 근거 종류가 융합에 들어가고
       leave-one-out 이 그 영향을 말한다 · 등록되지 않은 종류는 사유와 함께 거절된다 ·
       세 번째 언어가 데이터 파일 하나이고 파이썬 표는 키 집합이 같은 채로 남는다
       · **그리고** 콘솔이 새 역할의 로봇을 세우지 못하는 한 자리를 그대로 드러낸다

## 왜 산문 안내서가 아니라 시험인가

`docs/guides/extending-walkthrough.md` 에 같은 다섯 걸음이 적혀 있다. 문서는 조용히
썩는다 — 로더가 키 하나를 더 요구하게 되거나 역할 표가 한 줄 늘어도 문서는 그대로
맞아 보인다. 그래서 다섯 걸음을 **실행해서** 결과를 고정한다. 여기가 깨지면
"확장은 설정이다" 라는 약속 중 정확히 어느 줄이 깨졌는지 시험 이름이 말한다.

## 고정하는 것 중 하나는 **깨져 있는 자리**다

`test_new_role_robot_is_not_stood_up_by_the_console_role_table` 는 통과하는 시험이지만
좋은 소식이 아니다 — 콘솔의 자동 기동 경로가 역할→명령 어휘 표(파이썬)를 거치기 때문에
**표에 없는 역할의 로봇은 세워지지 않는다**는 현재 동작을 고정한다. 바로 다음 시험이
같은 로봇을 한 줄로 세워 보여 주므로, 계약 자체는 성립하고 빠진 것은 선언을 그 한 줄에
잇는 연결뿐이라는 것이 두 시험의 대비로 남는다. 표가 데이터로 옮겨지면 앞 시험이
깨지고, 그때 이 docstring 과 함께 지우는 것이 맞다.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]
CONSOLE_DIR = PROJECT_DIR / "tools" / "fms_console"
STATUS_UI_DIR = PROJECT_DIR / "tools" / "status_ui"
AUTHORING_DIR = PROJECT_DIR / "tools" / "profiles"
for _candidate in (CONSOLE_DIR, STATUS_UI_DIR, AUTHORING_DIR):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from accounts import Caller  # noqa: E402

import author_zones as az  # noqa: E402
from strings import LOCALES, STRINGS  # noqa: E402  (tools/fms_console/strings.py)

from mission_runtime.contracts.profile import ResourceBudget  # noqa: E402
from mission_runtime.perception import spatial_evidence as se  # noqa: E402
from mission_runtime.providers.overlay import StaticOverlayProvider  # noqa: E402
from mission_runtime.registry.onboarding import (  # noqa: E402
    JoinStep,
    NodeJoinManifest,
    NodeOnboarding,
    node_config_entry,
)

# --- walkthrough 가 더한 데이터 파일 (코드가 아니다) --------------------------
SHIPPED_DOMAINS = PROJECT_DIR / "profiles" / "domains.example.json"
DECLARATION = PROJECT_DIR / "profiles" / "walkthrough_domain.declaration.json"
WALKTHROUGH_DOMAINS = PROJECT_DIR / "profiles" / "domains.walkthrough.example.json"
WALKTHROUGH_CONFIG = PROJECT_DIR / "config" / "status_ui.walkthrough.example.json"
GOAL_KINDS = PROJECT_DIR / "profiles" / "goal_kinds.example.json"
JA_STRINGS = PROJECT_DIR / "config" / "strings.ja.walkthrough.json"

NEW_DOMAIN = "transit"
NEW_ZONES = ("transit-b1-concourse", "transit-b2-platform")
NEW_KIND = "inspection.rail_gauge"
NEW_FUNCTION = "rail_gauge_inspection"
NEW_ROLE = "rail_crawler"
NEW_NODE = "railcrawler"
GAUGE_TAG = "sensor.gauge_probe"
#: 이 로봇이 스스로 알리는 어휘. `probe_rail_gauge` 는 기존 어느 역할에도 없다.
NEW_VOCABULARY = ("crawl_to_marker", "probe_rail_gauge", "return_home", "stop")
#: 태그를 갖지 않은 비교 노드. 같은 kind 를 요구해도 여기서는 켜지면 안 된다.
NODE_WITHOUT_TAG = "pi6"


def _load_module(name: str, path: Path):
    """경로로 싣는다 — `tools/fms_console/serve.py` 와 `tools/status_ui/serve.py` 가
    모듈 이름이 같아서 `import serve` 는 먼저 올라온 쪽을 집는다
    (`tests/test_fms_console_wiring.py` 와 같은 이유·같은 방법)."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


console = _load_module("fms_console_serve_walkthrough", CONSOLE_DIR / "serve.py")
status_ui = _load_module("status_ui_serve_walkthrough", STATUS_UI_DIR / "serve.py")


def _build_console(tmp: Path):
    """walkthrough 설정·프로파일만으로 콘솔을 세운다. 가짜 데이터를 넣지 않는다."""
    return console.build_service(
        ui_config=WALKTHROUGH_CONFIG,
        zone_profile=WALKTHROUGH_DOMAINS,
        goal_kinds=GOAL_KINDS,
        with_fleet=True,
        overlay_path=tmp / "operator_edits.json",
    )


@pytest.fixture(scope="module")
def service(tmp_path_factory):
    # 세우는 비용이 작지 않으므로 **읽기만 하는** 시험들은 한 번 세운 것을 공유한다.
    # 탐지 상태를 바꾸는 시험은 자기 것을 따로 세운다.
    return _build_console(tmp_path_factory.mktemp("fms_walkthrough"))


@pytest.fixture(scope="module")
def status_view():
    config = status_ui.load_ui_config(WALKTHROUGH_CONFIG)
    return status_ui.StatusService(config)


# =============================================================================
# 1. 새 도메인과 그 구역들
# =============================================================================

def test_the_declaration_carries_no_radius_so_the_model_stays_the_only_source():
    """현장 선언에 반경을 적지 않는다.

    적으면 log-distance 파라미터와 **따로 움직이고**, 그때 "구역 크기를 왜 이렇게
    잡았나" 의 근거가 사라진다(author_zones 가 드리프트를 거절하는 이유와 같다).
    """
    declaration = json.loads(DECLARATION.read_text(encoding="utf-8"))
    bands = declaration["domain"]["rf"]
    assert bands, "새 도메인은 자기 RF 밴드를 선언해야 한다"
    for name, band in bands.items():
        assert "radius_m" not in band, f"rf.{name} 에 반경이 손으로 적혀 있다"
        assert band["thresholds_dbm"], f"rf.{name} 에 임계가 없으면 반경을 낼 수 없다"


def test_new_domain_declaration_is_accepted_and_its_radius_is_derived():
    """선언 한 장이 도메인 조각이 된다 — 핵심 코드는 건드리지 않는다(AI-C-15).

    조각이 배포 파일에 붙은 것과 **같은지**까지 본다. 손으로 붙여 넣는 단계가
    사이에 있으므로, 그 단계에서 숫자가 바뀌면 여기서 드러나야 한다.
    """
    declaration = json.loads(DECLARATION.read_text(encoding="utf-8"))
    shipped = json.loads(SHIPPED_DOMAINS.read_text(encoding="utf-8"))

    fragment, findings = az.validate_declaration(declaration, against=shipped)

    assert fragment is not None, [str(f) for f in findings]
    assert [f.code for f in findings if f.severity == az.ERROR] == []
    assert fragment["domain_id"] == NEW_DOMAIN

    band = fragment["rf"]["station_indoor"]
    assert band["radius_m"] == az.derive_radii(band)

    spliced = json.loads(WALKTHROUGH_DOMAINS.read_text(encoding="utf-8"))
    deployed = [d for d in spliced["domains"] if d["domain_id"] == NEW_DOMAIN]
    assert deployed == [fragment], "배포된 조각이 선언에서 다시 만든 것과 다르다"


def test_new_domain_profile_passes_the_check_and_the_console_loader():
    """두 검사가 같은 답을 내야 한다 — 저작 도구와 콘솔 로더가 서로 다른 규칙을
    쓰면 통과한 파일이 배포 시점에 거절된다."""
    profile = json.loads(WALKTHROUGH_DOMAINS.read_text(encoding="utf-8"))
    errors = [str(f) for f in az.validate_profile(profile) if f.severity == az.ERROR]
    assert errors == []

    loaded = console.load_domain_profile(WALKTHROUGH_DOMAINS)
    assert [d["domain_id"] for d in loaded["domains"]][-1] == NEW_DOMAIN


def test_console_serves_the_new_domain_map_zone_and_robot_panels(service):
    """메인 맵·구역 상세·로봇 패널이 새 도메인에서 그대로 돈다(AI-O-06).

    세 화면이 각각 다른 조립을 쓰므로 하나만 보면 나머지가 비어 있는 것을 놓친다.
    """
    scene = service.scene()
    tiles = {d["domain_id"]: d for d in scene["domains"]}
    assert NEW_DOMAIN in tiles, sorted(tiles)

    tile = tiles[NEW_DOMAIN]
    assert tile["zone_count"] == len(NEW_ZONES)
    assert tile["level_count"] == 2, "두 층에 걸친 도메인이어야 한다"
    assert tile["example"] is True, "실존하지 않는 현장은 예시로 드러나야 한다"

    domain = service.domain(NEW_DOMAIN)
    assert tuple(z["zone_id"] for z in domain["zones"]) == NEW_ZONES
    assert len({z["level_id"] for z in domain["zones"]}) == 2

    zone = service.zone(NEW_ZONES[0])
    assert zone["domain_id"] == NEW_DOMAIN
    assert zone["edge_node"] == "edge-transit"
    assert zone["wifi"]["ap_id"] == "ap-transit-b1"
    assert NEW_NODE in {robot["node_id"] for robot in zone["robots"]}

    robot = service.robot(NEW_NODE, NEW_ZONES[0], caller=Caller.for_role("admin"))
    assert robot["role"] == NEW_ROLE
    assert robot["zone_id"] == NEW_ZONES[0]
    assert GAUGE_TAG in robot["resources"]["tags"]
    assert robot["verified"] is False, "실측 전 장비는 미검증으로 드러나야 한다"


# =============================================================================
# 2. 새 로봇 — 그 주인이 하는 네 걸음
# =============================================================================

def test_join_manifest_with_an_unseen_vocabulary_is_accepted(tmp_path):
    """조인 선언은 **입력**이고, 처음 보는 action 이름이 거절 사유가 아니다.

    `registry/onboarding.py` 가 약속한 네 걸음 중 1·2·3 걸음이 여기 있다 —
    오버레이에 닿고, 선언을 한 번 올리고, 어휘를 공지한다. 가용성은 백엔드가
    판정하므로(절대 준수 원칙 #15) `accepted` 는 "쓸 수 있다" 가 아니라
    "선언이 계약에 맞는다" 는 뜻이고, 남은 할 일은 숨기지 않고 목록으로 나온다.
    """
    overlay = StaticOverlayProvider(peers={NEW_NODE: True})
    onboarding = NodeOnboarding(overlay=overlay)

    manifest = _join_manifest()
    outcome = onboarding.submit(manifest, announced_actions=NEW_VOCABULARY)

    assert outcome.accepted, outcome.rejections
    assert outcome.rejections == ()
    # 선언한 것과 공지된 것이 정확히 같다 — 어댑터 구현 누락은 이 두 줄에 나타난다.
    assert outcome.undeclared_announcements == ()
    assert outcome.unannounced_declarations == ()
    # 카메라를 달고 왔고 보정 버전이 없으니 보정이 할 일로 남는다(AI-E-02).
    assert JoinStep.CALIBRATE_CAMERA in outcome.next_steps
    # 외형 이미지를 올리지 않았으니 분류를 흉내내지 않고 학습이 할 일로 남는다.
    assert JoinStep.LEARN_APPEARANCE in outcome.next_steps
    assert onboarding.joined() == (NEW_NODE,)


def test_an_unreachable_peer_is_refused_rather_than_half_registered():
    """오버레이에 닿지 않으면 그 사실로 거절한다 — 등록은 됐는데 닿지 않는
    장치를 만들지 않는다. 사유가 이름으로 남아야 통합하는 쪽이 어디를 고칠지 안다."""
    onboarding = NodeOnboarding(overlay=StaticOverlayProvider(peers={}))
    outcome = onboarding.submit(_join_manifest(), announced_actions=NEW_VOCABULARY)
    assert not outcome.accepted
    assert [code.value for code, _ in outcome.rejections] == ["not_reachable_on_overlay"]
    assert onboarding.joined() == ()


def test_the_join_manifest_is_exactly_the_shipped_config_row():
    """"시스템이 자원을 읽는다" 의 구체적인 뜻 — 선언이 그대로 설정 한 줄이 된다.

    배포된 설정의 그 줄과 **같은지**까지 본다. 손으로 적은 줄이 선언과 어긋나면
    화면에는 보이고 배치 계산에는 들어가지 않는 노드가 생긴다.
    """
    row = node_config_entry(_join_manifest())
    config = json.loads(WALKTHROUGH_CONFIG.read_text(encoding="utf-8"))
    deployed = [n for n in config["nodes"] if n["node_id"] == NEW_NODE]
    assert deployed == [row]


def test_a_new_role_robot_is_stood_up_from_its_own_declaration(tmp_path):
    """**이 시험은 고쳐진 동작을 고정한다.**

    원래 이 자리에는 깨진 동작을 고정한 시험이 있었다 — 콘솔의 자동 기동이 명령
    어휘를 `ROLE_ACTIONS` 라는 파이썬 표에서 **역할 이름으로** 찾았고, 표에 없는
    역할로 조인한 로봇은 아예 세워지지 않았다. 자원과 기능은 설정만으로 보이는데
    공지가 없어 탐지되지 않고 명령은 `device_not_attached` 로 거절됐다. 출하된
    `mt4`(role `fixed_manipulator`)도 같은 구멍에 있었다.

    2026-11-03 에 어휘의 정본을 **장치 자신의 선언**(`declared_actions`, AI-C-18)으로
    옮겼다. 역할 표는 아무것도 선언하지 않은 옛 노드를 위한 되돌림으로만 남는다.
    그래서 지금 확인하는 것은 "새 역할이어도 선언만으로 세워진다" 이다 — 역할
    이름으로 분기하던 문턱이 사라졌다는 뜻이고, 그것이 절대 준수 원칙 #3·#7 이
    요구한 상태다.
    """
    service = _build_console(tmp_path)

    # 선언에서 어휘가 왔으므로 공지까지 끝나 있다.
    assert NEW_NODE in service.fleet.discovery.ids()
    robot = service.robot(NEW_NODE, NEW_ZONES[0], caller=Caller.for_role("admin"))
    assert robot["presence"] == "discovered"
    assert tuple(robot["announced_actions"]) == NEW_VOCABULARY
    # 자원·기능은 전과 같이 설정만으로 돈다.
    assert robot["resources"]["compute_units"] == 2.0
    states = {f["function_id"]: f["state"] for f in robot["functions"]}
    assert states[NEW_FUNCTION] == "ACTIVE"

    issued = service.command(node_id=NEW_NODE, action="probe_rail_gauge",
                             caller=Caller.for_role("admin"), params={})
    assert issued["acceptance"]["accepted"] is True
    assert issued["result"]["status"] == "SUCCEEDED"


def test_the_role_table_is_only_a_fallback_for_nodes_that_declare_nothing(tmp_path):
    """역할 표가 1순위로 돌아오면 확장 문턱도 돌아온다.

    선언이 있는 장치는 표를 **쳐다보지 않아야** 한다. 그래서 표에 없는 역할
    (`rail_crawler`)이 선언만으로 세워진다는 사실 자체가 순서가 지켜졌다는 증거다.
    """
    from fleet_runtime import ROLE_ACTIONS, vocabularies_from_config

    assert NEW_ROLE not in ROLE_ACTIONS, "표에 넣어 해결하면 다음 역할에서 또 막힌다"
    declared = vocabularies_from_config(WALKTHROUGH_CONFIG)
    assert declared[NEW_NODE] == NEW_VOCABULARY


def test_announcing_the_vocabulary_makes_the_new_robot_discovered_and_commandable(tmp_path):
    """같은 로봇을 **한 줄로** 세우면 네 걸음 전부가 성립한다.

    `FleetRuntime.add` 는 `build_runtime` 이 쓰는 그 경로이고, 다른 것은 어휘를
    역할 표에서 찾지 않고 장치가 알린 것을 그대로 쓴다는 점뿐이다. 그러므로 계약
    자체는 어댑터 구현만으로 충족되고, 앞 시험이 고정한 결손은 선언과 이 호출을
    잇는 연결 하나다.
    """
    service = _build_console(tmp_path)
    runtime = service.commander

    # 선언으로 이미 세워져 있다. `add` 는 멱등이므로 같은 장치를 다시 세워도
    # 어휘가 바뀌지 않는다 — 그 성질이 깨지면 재조인이 어휘를 지운다.
    device = runtime.devices.get(NEW_NODE) or runtime.add(NEW_NODE, NEW_VOCABULARY)
    runtime.announce_all()

    # 탐지의 근거는 공지다 — 선언 파일을 탐지로 바꿔 읽지 않는다(AI-C-18).
    assert runtime.vocabulary(NEW_NODE) == NEW_VOCABULARY
    assert NEW_NODE in service.fleet.discovery.ids()

    robot = service.robot(NEW_NODE, NEW_ZONES[0], caller=Caller.for_role("admin"))
    assert robot["presence"] == "discovered"
    assert tuple(robot["announced_actions"]) == NEW_VOCABULARY

    issued = service.command(node_id=NEW_NODE, action="probe_rail_gauge",
                             caller=Caller.for_role("admin"), params={"marker": 3})
    # 전달·수락·결과는 서로 다른 사건이다(AI-C-20) — 한 칸으로 합쳐 읽지 않는다.
    assert issued["delivered"] is True
    assert issued["acceptance"]["accepted"] is True
    assert issued["result"]["status"] == "SUCCEEDED"
    # 물리 실행은 정확히 한 번. 같은 command_id 가 두 번 나오면 멱등 위반이다.
    assert [row[0] for row in device.physical_executions] == ["probe_rail_gauge"]

    # 알리지 않은 action 은 보내지 않는다 — 어휘는 장치가 정한다.
    unknown = service.command(node_id=NEW_NODE, action="takeoff", caller=Caller.for_role("admin"), params={})
    assert unknown["error"] == "action_not_announced"


def test_the_config_row_can_already_carry_the_declared_vocabulary(tmp_path):
    """고쳐야 할 자리가 **열려 있다**는 근거.

    설정 로더는 노드 줄의 모르는 칸을 통과시킨다. 그러니 선언의 `declared_actions`
    를 그 줄에 실어 보내는 것은 스키마 변경을 요구하지 않는다 — 읽는 쪽 두 군데만
    이으면 앞 시험의 결손이 사라진다.
    """
    raw = json.loads(WALKTHROUGH_CONFIG.read_text(encoding="utf-8"))
    raw["providers_manifest"] = str(
        (WALKTHROUGH_CONFIG.parent / raw["providers_manifest"]).resolve())
    raw["labels"] = str((WALKTHROUGH_CONFIG.parent / raw["labels"]).resolve())
    for node in raw["nodes"]:
        if node["node_id"] == NEW_NODE:
            node["declared_actions"] = list(NEW_VOCABULARY)
    path = tmp_path / "status_ui.with_vocabulary.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    config = status_ui.load_ui_config(path)
    assert config.node(NEW_NODE).role == NEW_ROLE


def _join_manifest() -> NodeJoinManifest:
    """통합하는 쪽이 한 번 올리는 선언. 빈 칸은 기본값이 아니라 **비어 있는 것**이다."""
    return NodeJoinManifest(
        device_id=NEW_NODE,
        role=NEW_ROLE,
        node_tags=frozenset({
            "compute.cpu", "tier.mobile", GAUGE_TAG,
            "sensor.camera.railcrawler", "actuator.rail_drive", "power.battery",
        }),
        budget=ResourceBudget(compute_units=2.0, memory_mb=1800.0),
        has_camera=True,
        overlay_peer=NEW_NODE,
        declared_actions=NEW_VOCABULARY,
        extra={"label": "궤도 점검차 · railcrawler (가상 장비 — 제원 미확인)"},
    )


# =============================================================================
# 3. 새 capability kind 와 그 provider
# =============================================================================

def test_a_registered_provider_flips_the_new_kind_to_active(status_view):
    """아무도 제공하지 않던 kind 가 manifest 등록 한 줄로 켜진다(AI-B-09).

    `registry/manifest.py` 는 kind 이름을 알지 못한다 — 그래서 새 kind 를 더하는
    데 로더도 레지스트리도 고칠 필요가 없다.
    """
    rows = {row["kind"]: row for row in status_view.resolve(NEW_NODE)["rows"]}
    assert NEW_KIND in rows, "새 kind 가 해소 표에 나타나지 않았다"
    row = rows[NEW_KIND]
    assert row["state"] == "ACTIVE"
    assert row["provider_id"] == "railcrawler-gauge-probe"
    assert row["reason"] == "selected"


def test_the_same_kind_stays_disabled_on_a_node_without_the_tag(status_view):
    """태그가 없는 노드에서는 켜지지 않고, **빠진 태그 이름**이 남는다.

    사유가 "안 된다" 로만 오면 무엇을 보태야 하는지 알 수 없다. 조건이 데이터이므로
    거절도 데이터로 설명된다.
    """
    rows = {row["kind"]: row for row in status_view.resolve(NODE_WITHOUT_TAG)["rows"]}
    row = rows[NEW_KIND]
    assert row["state"] == "DISABLED"
    assert row["provider_id"] is None
    reasons = {alt["reason_token"]: alt["reason_data"] for alt in row["alternatives"]}
    assert reasons.get("required_hw_tag_missing") == GAUGE_TAG


def test_a_function_requiring_the_new_kind_becomes_available(status_view):
    """기능 축도 같이 움직인다 — kind 만 켜지고 기능이 안 켜지면 반쪽이다."""
    functions = {f["function_id"]: f for f in status_view.functions()["functions"]}
    assert NEW_FUNCTION in functions, sorted(functions)
    function = functions[NEW_FUNCTION]
    assert function["state"] == "ACTIVE"
    # 그 기능을 혼자 수행할 수 있는 계층이 새 역할로 나온다(AI-B-04 의 배치 축).
    assert function["solo_roles"] == [NEW_ROLE]


def test_dropping_the_only_provider_disables_only_that_function(status_view):
    """provider 하나를 빼면 그 기능만 내려간다 — 다른 기능은 그대로다(AI-C-05).

    `exclude_providers` 는 what-if 질의이고 설정을 바꾸지 않는다. 선택 구성요소의
    결손이 관련 없는 기능을 멈추게 하지 않는다는 것을 같은 호출 안에서 확인한다.
    """
    overrides = {status_ui.OVERRIDE_ALL: {"exclude_providers": ["railcrawler-gauge-probe"]}}
    states = {f["function_id"]: f["state"]
              for f in status_view.functions(overrides)["functions"]}
    assert states[NEW_FUNCTION] == "DISABLED"
    # 비교 기준: 같은 질의에서 다른 기능 하나는 바뀌지 않았다.
    baseline = {f["function_id"]: f["state"]
                for f in status_view.functions()["functions"]}
    unaffected = [fid for fid in states if fid != NEW_FUNCTION]
    assert [states[fid] for fid in unaffected] == [baseline[fid] for fid in unaffected]


def test_the_new_kind_and_function_have_labels(status_view):
    """라벨 파일 자리는 설정이 정하므로 새 어휘의 라벨도 데이터다.

    `labels_missing()` 이 비지 않으면 화면에 id 가 그대로 노출된다 — 사람이 읽는
    자리는 그 자체로 계약이다.
    """
    missing = [entry for entry in status_view.labels_missing()
               if NEW_KIND in entry or NEW_FUNCTION in entry or NEW_ROLE in entry]
    assert missing == []


# =============================================================================
# 4. 새 공간 근거 종류
# =============================================================================

def _survey_kinds() -> se.SpatialEvidenceKindRegistry:
    """측량 토털스테이션 고정점을 등록한 레지스트리.

    `copy()` 해서 쓰는 이유는 배치별로 아는 종류가 다르기 때문이다 — 모듈 기본
    레지스트리를 늘리면 이 배치에 없는 센서가 다른 배치에도 등록된 것으로 보인다.
    사람 실측과 달리 `overrides=False` 다: 장비 실측은 격이 `measured` 이지만
    현재 값을 **덮지 않고** 선언한 정확도만큼의 가중으로 융합에 들어간다.
    """
    kinds = se.DEFAULT_KIND_REGISTRY.copy()
    kinds.register(se.EvidenceKindSpec(
        "total_station_fix", se.TIER_MEASURED,
        note="측량 토털스테이션으로 잡은 고정점. 정확도를 스스로 선언한다."))
    return kinds


def _fixed_camera_observations() -> list[se.SpatialObservation]:
    """한 고정 카메라 자리에 대한 세 가지 근거. 전부 현장 로컬 미터다(AI-C-02)."""
    return [
        se.SpatialObservation(
            "decl:gate-cam", "zone_profile", "zone_profile:transit", 0.0,
            se.KIND_INFRASTRUCTURE_DECLARATION, "infrastructure.transit-gate-cam.at",
            (8.0, 6.0), "site:transit"),
        se.SpatialObservation(
            "depth:gate-cam", "edge.depth", "frame:9001", 10.0,
            se.KIND_DEPTH, "infrastructure.transit-gate-cam.at",
            (8.6, 6.4), "site:transit", accuracy_m=0.4),
        se.SpatialObservation(
            "ts:gate-cam", "survey.total_station", "survey:run-1", 20.0,
            "total_station_fix", "infrastructure.transit-gate-cam.at",
            (8.05, 6.02), "site:transit", accuracy_m=0.005),
    ]


def test_a_registered_evidence_kind_enters_fusion_with_its_declared_accuracy():
    """등록 하나로 융합에 들어간다 — `if` 가 늘지 않는다(AI-S-06).

    선언한 정확도가 역분산 가중을 정하므로, 5 mm 실측이 40 cm 추정을 이기는 것은
    종류 이름 때문이 아니라 **선언한 숫자** 때문이다.
    """
    state = se.fuse_zone(_fixed_camera_observations(), zone_id=NEW_ZONES[0],
                         frame_id="site:transit", kinds=_survey_kinds())
    quantity = state.quantity("infrastructure.transit-gate-cam.at")

    assert "total_station_fix" in quantity.contributing_kinds
    assert quantity.decided_by == se.DECIDED_INVERSE_VARIANCE
    assert quantity.tier == se.TIER_MEASURED
    assert quantity.accuracy_m == pytest.approx(0.005, rel=1e-3)
    # 사람 입력이 아니므로 현재 상태를 덮지 않았다 — 덮기는 사람 실측만의 격이다.
    assert not quantity.human_override
    # 정확도를 선언하지 않은 프로파일 선언은 가중에서 보류된다(기본 σ 를 꽂지 않는다).
    declared = quantity.contribution("decl:gate-cam")
    assert declared.role == se.ROLE_ACCURACY_UNKNOWN
    assert declared.weight == 0.0


def test_leave_one_out_reports_the_new_kind_s_influence():
    """빼면 값이 얼마가 되는지 답할 수 있어야 한다 — 없으면 틀린 지도를 디버깅할
    방법이 없다. 새 종류도 기존 종류와 **같은 보고**에 들어간다."""
    state = se.fuse_zone(_fixed_camera_observations(), zone_id=NEW_ZONES[0],
                         frame_id="site:transit", kinds=_survey_kinds())
    quantity = state.quantity("infrastructure.transit-gate-cam.at")

    influence = {row.removed: row for row in quantity.leave_one_out(unit="kind")}
    assert "total_station_fix" in influence
    # 값을 실제로 정한 근거이므로 빼면 값이 눈에 보이게 움직인다.
    assert influence["total_station_fix"].influence_m > 0.1
    # 가중에서 보류된 선언은 값을 정하지 않았으므로 빼도 움직이지 않는다 —
    # 0 이 "영향이 없다" 를 말하고 None 이 "모른다" 를 말한다.
    assert influence[se.KIND_INFRASTRUCTURE_DECLARATION].influence_m == pytest.approx(0.0)
    assert not influence["total_station_fix"].vanished


def test_an_unregistered_evidence_kind_is_refused_with_a_reason():
    """오타난 종류 이름이 **조용히 사라지지 않는다**.

    값을 바꾸지 않은 채 근거가 없어지는 것이 가장 찾기 어려운 버그다. 그래서
    거절 사유와 "먼저 등록하라" 는 안내가 같이 남는다.
    """
    stray = se.SpatialObservation(
        "lidar:gate-cam", "lab.prototype", "frame:9002", 30.0,
        "lidar_sweep", "infrastructure.transit-gate-cam.at",
        (9.0, 7.0), "site:transit", accuracy_m=0.1)

    state = se.fuse_zone([*_fixed_camera_observations(), stray], zone_id=NEW_ZONES[0],
                         frame_id="site:transit", kinds=_survey_kinds())

    refused = {row.evidence_id: row for row in state.rejected}
    assert "lidar:gate-cam" in refused
    assert refused["lidar:gate-cam"].reason == se.REJECT_UNREGISTERED_KIND
    assert "lidar_sweep" in refused["lidar:gate-cam"].detail
    # 거절된 근거는 값에 들어가지 않았다.
    quantity = state.quantity("infrastructure.transit-gate-cam.at")
    assert "lidar_sweep" not in quantity.contributing_kinds
    assert quantity.contribution("lidar:gate-cam") is None


def test_the_module_default_registry_is_untouched_by_the_deployment_registration():
    """배치가 등록한 종류가 모듈 기본으로 새지 않는다 — 샜으면 이 센서가 없는
    배치에서도 등록된 것으로 보이고, 그 종류는 관측이 없을 뿐인 것으로 읽힌다."""
    _survey_kinds()
    assert "total_station_fix" not in se.DEFAULT_KIND_REGISTRY.kinds()


# =============================================================================
# 5. 콘솔의 새 언어
# =============================================================================

def test_a_third_locale_is_a_data_file_and_the_python_tables_are_unchanged():
    """세 번째 언어를 더하는 데 파이썬을 고치지 않는다(`docs/view-contract.md` §8).

    그 결과로 서버의 언어 목록은 늘지 않는다 — 뷰어는 서버가 아는 언어로 묻고
    표만 바꿔 쓴다. 두 파이썬 표의 키 집합이 같다는 불변조건도 그대로 남는다.
    """
    assert set(STRINGS["en"]) == set(STRINGS["ko"])
    assert LOCALES == ("en", "ko")
    assert "ja" not in LOCALES

    table = json.loads(JA_STRINGS.read_text(encoding="utf-8"))
    assert table["locale"] == "ja"
    # 키를 하나라도 새로 만들면 그 줄은 아무 자리에도 쓰이지 않는다.
    assert set(table["strings"]) == set(STRINGS["en"])
    assert [key for key, value in table["strings"].items() if not value.strip()] == []


def test_the_viewer_table_overlays_the_server_table_without_a_blank():
    """계약이 말한 대로 겹쳐 쓴다 — 빠진 키는 fallback 언어로 떨어지고 빈칸이
    생기지 않는다. 뷰어가 일부만 번역한 상태도 정상 구성이다."""
    table = json.loads(JA_STRINGS.read_text(encoding="utf-8"))
    fallback = STRINGS[table["fallback_locale"]]

    partial = dict(list(table["strings"].items())[:20])
    merged = {**fallback, **partial}

    assert set(merged) == set(fallback)
    assert [key for key, value in merged.items() if not value.strip()] == []
    assert merged["app.language"] == table["strings"]["app.language"]


def test_the_server_refuses_a_locale_it_does_not_know():
    """`?locale=ja` 는 400 이다 — 그것이 뷰어가 서버에 en 으로 묻는 이유다.

    모르는 값을 조용히 기본 언어로 바꿔 주면 뷰어는 자기 표가 쓰이고 있다고
    착각한다.
    """
    with pytest.raises(console.ApiError) as raised:
        console.FmsHandler._locale(None, {"locale": ["ja"]})
    assert raised.value.status == 400
    assert raised.value.reason == "unknown_locale"


def test_state_tokens_are_part_of_the_key_so_a_new_state_needs_no_branch():
    """상태 토큰이 키 안에 있어서 뷰어는 `"map.state." + state` 로 문구를 찾는다.

    새 언어가 늘어도 이 규칙은 그대로이므로, 번역한 표에도 같은 접두어가 있어야
    한다 — 없으면 그 상태만 영어로 남는다.
    """
    table = json.loads(JA_STRINGS.read_text(encoding="utf-8"))["strings"]
    for state in ("operable", "limited", "idle", "no_robot"):
        assert f"map.state.{state}" in table
    for state in ("ACTIVE", "DEGRADED", "DISABLED"):
        assert f"fn.state.{state}" in table


# =============================================================================
# 전체 — 다섯 걸음이 핵심 코드를 건드리지 않았는가
# =============================================================================

def test_no_core_module_mentions_anything_the_walkthrough_added():
    """다섯 걸음이 더한 이름 중 **어느 것도** 핵심 코드에 없다(원칙 #1, #3, #7).

    주석·docstring 까지 포함해 통째로 찾는다. `tests/conftest.py::core_source_mentions`
    는 문자열 토큰을 건너뛰는데, 하드코딩된 분기(`if kind == "inspection.rail_gauge"`)
    는 바로 그 문자열이라 그 도구로는 보이지 않는다. 여기서 더한 이름은 어제까지
    저장소에 없던 것들이므로, 통째로 찾아도 걸리는 것이 있다면 그것이 분기다.
    낱말 경계로 찾는 이유는 `transit` 가 `transitions` 의 앞부분이기 때문이다.
    """
    import re

    from tests.conftest import CORE_DIRS

    for token in (NEW_DOMAIN, NEW_ROLE, NEW_KIND, NEW_NODE, GAUGE_TAG,
                  "total_station_fix", "transit_station_surveillance"):
        pattern = re.compile(rf"\b{re.escape(token)}\b")
        hits = [
            str(path.relative_to(PROJECT_DIR))
            for directory in CORE_DIRS
            for path in sorted((PROJECT_DIR / directory).rglob("*.py"))
            if pattern.search(path.read_text(encoding="utf-8"))
        ]
        assert hits == [], f"{token!r} 가 핵심 코드에 들어갔다: {hits}"
