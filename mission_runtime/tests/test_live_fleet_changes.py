"""도는 배치가 **지금** 바뀌는 두 가지 — 로봇의 자리와 새로 들인 장치.

하나는 닿지 않게 된 로봇이 **마지막으로 알린 자리**에 남는 것이다. 지도에서
지우면 "어디서 잃어버렸는가" 를 아무도 모르게 되고, 선언된 자리로 되돌리면 지금
거기 있는 것처럼 보인다 — 둘 다 틀렸다.

다른 하나는 ＋ 로 들인 장치가 **그 자리에서** 서는 것이다. 설정 한 줄을 사람이
파일에 붙여 넣고 서버를 다시 띄울 때까지 기다리면 "형식대로 넣으면 바로 연동"
이 아니다.

implements: AI-S-06, AI-O-04, AI-C-02, AI-B-09, AI-C-10, AI-C-18
tests: declared vs reported vs last_seen, position survives loss of contact,
       a joined device stands up at once, a join is not an availability verdict
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONSOLE_DIR = ROOT / "tools" / "fms_console"
for candidate in (CONSOLE_DIR, ROOT / "tools" / "status_ui"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from accounts import Caller  # noqa: E402


def _console():
    """`tools/fms_console/serve.py` 를 **경로로** 싣는다.

    `tools/status_ui/serve.py` 와 모듈 이름이 겹친다 — 이름으로 부르면 먼저 올라온
    쪽을 집고, 그 바람에 같은 묶음에서 돌던 status_ui 시험이 통째로 깨졌다
    (이 파일이 `import serve` 를 쓰던 동안 실제로 그랬다).
    """
    spec = importlib.util.spec_from_file_location(
        "fms_console_serve_live_fleet", CONSOLE_DIR / "serve.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


build_service = _console().build_service

ZONE = "zone-503"
ROBOT = "go1-001"


@pytest.fixture
def service():
    built = build_service(
        ui_config=ROOT / "config" / "status_ui.json",
        zone_profile=ROOT / "profiles" / "domains.json",
        goal_kinds=ROOT / "profiles" / "goal_kinds.example.json",
        with_fleet=False)
    # 닿아 있다는 사실을 세운다. 공지가 와야 `discovered` 이고, 그것이 "지금
    # 연락이 된다" 의 뜻이다 — 자세 보고와는 **다른 채널**이라 둘을 따로 세운다.
    built.fleet.discovery.note(ROBOT, ("move_forward", "turn", "stop"))
    return built


def _robot(service, node_id=ROBOT):
    rows = service.zone(ZONE)["robots"]
    return next(r for r in rows if r["node_id"] == node_id)


def _report(service, x, y):
    service.report_pose(caller=Caller.for_role("admin"), body={
        "device_id": ROBOT, "zone_id": ZONE,
        "pose": {"x": x, "y": y, "yaw_deg": 0.0},
        "pose_source": "robot_state_15201"})


def test_a_robot_that_never_reported_shows_its_declaration(service):
    """선언은 "있을 것이라고 적어 둔 곳" 이고, 관측이 아니라는 사실이 붙어 있다.

    닿아 있다고 해서 자리를 아는 것은 아니다 — 공지 채널과 자세 채널은 다르다.
    """
    robot = _robot(service)

    assert robot["at_origin"] == "declared"
    assert "position_source" not in robot


def test_a_reported_position_beats_the_declaration(service):
    """로봇이 움직이면 선언된 자리는 그 순간부터 거짓이다."""
    _report(service, 20.5, 30.25)
    robot = _robot(service)

    assert robot["at"] == {"x": 20.5, "y": 30.25}
    assert robot["at_origin"] == "reported"
    # 어느 경로로 들어온 값인지 남는다 — 선언과 섞이지 않는다(AI-S-06).
    assert robot["position_source"] == "robot_state_15201"


def test_losing_contact_keeps_the_last_place_it_was_seen(service):
    """닿지 않게 돼도 **자리를 지우지 않는다.** 출처만 바뀐다."""
    _report(service, 20.5, 30.25)
    assert _robot(service)["at_origin"] == "reported"

    # 그 장치의 공지가 끊긴다 — 백엔드 가용성 판정을 우리가 재판정하지 않고
    # 탐지가 사라졌다는 사실만 받는다(AI-O-04).
    service.fleet.discovery.forget(ROBOT)
    robot = _robot(service)

    assert robot["at"] == {"x": 20.5, "y": 30.25}, "마지막 자리가 남아야 한다"
    assert robot["at_origin"] == "last_seen"
    assert robot["presence"] != "discovered"


def test_the_declaration_is_not_restored_when_contact_is_lost(service):
    """선언된 자리로 되돌리면 지금 거기 있는 것처럼 보인다 — 가장 나쁜 쪽이다."""
    declared = _robot(service)["at"]
    _report(service, 20.5, 30.25)
    service.fleet.discovery.forget(ROBOT)

    assert _robot(service)["at"] != declared


def test_a_robot_with_no_declared_place_and_no_report_has_no_place(service):
    """자리를 모르는 로봇은 0,0 이 아니라 **자리가 없다**. 미측정은 좌표가 아니다."""
    other = _robot(service, "ep-001")

    assert other["at"] is None
    assert other["at_origin"] == "declared"


# ---------------------------------------------------------------------------
# ＋ 로 들인 장치는 **바로** 선다
# ---------------------------------------------------------------------------


def _join(service, device_id="go1-002", **over):
    body = {
        "device_id": device_id, "role": "ugv", "zone_id": ZONE,
        "node_tags": ["compute.cpu", "tier.ugv", "locomotion.legged", "sensor.imu"],
        "budget": {"compute_units": 6.0, "memory_mb": 4096},
        "declared_actions": ["move_forward", "turn", "stop", "emergency_stop"],
        "at": {"x": 12.0, "y": 8.0},
        "reason": "시험",
    }
    body.update(over)
    return service.join_device(caller=Caller.for_role("admin"), body=body)


def test_a_joined_device_stands_up_in_the_zone_immediately(service):
    """형식대로 넣으면 **바로** 연동된다 — 설정 파일을 고치고 다시 띄우지 않는다.

    전에는 조인이 설정 한 줄을 돌려주고 끝이라, 사람이 그 줄을 파일에 붙여 넣고
    서버를 다시 띄울 때까지 그 장치는 어디에도 없었다.
    """
    before = {r["node_id"] for r in service.zone(ZONE)["robots"]}
    assert "go1-002" not in before

    result = _join(service)

    assert result["outcome"]["accepted"] is True
    assert result["adopted_into_zone"] == ZONE
    after = {r["node_id"] for r in service.zone(ZONE)["robots"]}
    assert "go1-002" in after


def test_a_joined_device_is_declared_not_detected(service):
    """들였다는 것은 **가용성 판정이 아니다**(절대 준수 #15).

    공지가 오기 전까지는 `declared` 이고, 그 구분이 사라지면 "등록했으니 있다"
    가 되어 닿지 않는 장치에 임무가 간다.
    """
    _join(service)
    row = _robot(service, "go1-002")

    assert row["presence"] == "declared"
    assert row["at"] == {"x": 12.0, "y": 8.0}
    assert row["at_origin"] == "declared"


def test_a_join_without_a_zone_is_declared_but_not_placed(service):
    """자리를 모르는 장치를 아무 구역에나 넣지 않는다."""
    result = _join(service, device_id="go1-003", zone_id="")

    assert result["outcome"]["accepted"] is True
    assert result["adopted_into_zone"] is None
    assert "go1-003" not in {r["node_id"] for r in service.zone(ZONE)["robots"]}


def test_a_malformed_join_names_the_field_it_is_missing(service):
    """거절은 "안 된다" 가 아니라 **무엇이 없어서** 안 되는지를 말한다."""
    result = _join(service, device_id="go1-004", node_tags=None)

    assert result["outcome"]["accepted"] is False
    missing = {r["detail"] for r in result["outcome"]["rejections"]}
    assert "node_tags" in missing
    assert result["config_entry"] is None


def test_a_join_also_produces_what_the_visualisation_can_consume(service):
    """우리 화면에만 서는 장치는 임무를 받을 수 없다.

    가시화 계약이 직접 적는다 — "여기 없는 것은 assigned_targets 에 쓸 수 없다."
    모양 검증은 `tests/test_visualisation_handoff.py` 가 그쪽 스키마로 한다.
    """
    result = _join(service)
    entry = result["visualisation_entry"]

    assert entry["equipment_id"] == "go1-002"
    assert entry["zone_id"] == ZONE
    # 모르는 이름은 null 이다 — 장치 id 를 이름 자리에 복사하지 않는다.
    assert entry["label"] is None


def test_a_refused_join_hands_nothing_over(service):
    """받아들이지 않은 선언을 다른 파트에 넘기면 그쪽 목록이 오염된다."""
    result = _join(service, device_id="go1-005", node_tags=None)

    assert result["outcome"]["accepted"] is False
    assert result["visualisation_entry"] is None
