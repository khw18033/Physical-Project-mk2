"""implements: AI-C-10, AI-B-02, AI-B-03, AI-B-04, AI-B-05, AI-C-04, AI-C-05, AI-C-15 (review tooling)
tests: (a) 등록 파일이 없어도 화면은 그대로 뜬다, (b) 목록에는 자격증명 참조만
나가고 비밀은 구조적으로 없다, (c) 주소+목적 등록이 곧바로 배치 결정으로
이어진다, (d) group/world 읽기 가능한 자격증명 파일은 계속 거절되고 그것이
나머지 화면을 죽이지 않는다, (e) 닿지 않는 장치는 예외가 아니라 거절로
돌아온다, (f) 모르는 명령·필드·장치는 각각 제 상태코드로 거절된다,
(g) 장치 패널의 라벨이 두 언어 모두 채워져 있다.

`tools/status_ui/serve.py`는 패키지가 아니라 스크립트라 경로로 import한다
(tests/test_status_ui.py와 같은 방식). 실제 하드웨어는 필요 없다 — 닿지 않는
주소는 이 계층에서 정상 경로이기 때문이다(AI-C-05).
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

FRAMEWORK_DIR = Path(__file__).resolve().parents[1]
SERVE_PY = FRAMEWORK_DIR / "tools" / "status_ui" / "serve.py"
DEVICE_CONFIG = FRAMEWORK_DIR / "config" / "status_ui.devices.example.json"
PLAIN_CONFIG = FRAMEWORK_DIR / "config" / "status_ui.ondevice.example.json"

#: 라우팅되지 않는 문서화용 주소(RFC 5737 TEST-NET-1). 실제로 누구에게도 닿지 않는다.
UNREACHABLE = "192.0.2.13"
#: 즉시 거절되는 주소. 블랙홀 주소는 연결 타임아웃을 다 기다리게 해서
#: "닿지 않는 장치" 시험이 분 단위로 늘어난다 — 거절 경로를 보려는 것이지
#: 타임아웃 값을 재려는 것이 아니므로 즉시 거절되는 쪽을 쓴다.
REFUSED_HOST, REFUSED_PORT = "127.0.0.1", 1


def _import_serve():
    name = "status_ui_serve_devices_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SERVE_PY)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


serve = _import_serve()


def _config_with(tmp_path: Path, **overrides) -> Path:
    """장치 축 설정을 tmp로 복사한다 — 시험이 사람의 로컬 등록 파일에
    좌우되면 안 된다."""
    raw = json.loads(DEVICE_CONFIG.read_text(encoding="utf-8"))
    target = tmp_path / "status_ui.json"
    for key in ("providers_manifest", "labels", "device_purposes"):
        raw[key] = str((DEVICE_CONFIG.parent / raw[key]).resolve())
    raw["devices"] = str(tmp_path / "devices.json")
    raw["device_credentials"] = str(tmp_path / "device_credentials.json")
    raw["control_key"] = str(tmp_path / "keys" / "id_control")
    raw.update(overrides)
    target.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return target


@pytest.fixture
def service(tmp_path):
    return serve.StatusService(serve.load_ui_config(_config_with(tmp_path)))


# --- (a) 장치 축이 없어도 화면은 산다 ----------------------------------------


def test_a_config_without_devices_still_serves_everything_else():
    service = serve.StatusService(serve.load_ui_config(PLAIN_CONFIG))
    assert service.device_info["configured"] is False
    assert service.device_info["reason"] == "no_devices_file"
    assert service.device_rows()["devices"] == []
    # 나머지 축은 그대로다.
    assert service.residency("pi6")["purpose"]["purpose_id"] == "fixed_camera"
    assert service.functions()["functions"]


def test_the_device_axis_reports_itself_in_describe(service):
    described = service.describe()
    assert described["devices"]["configured"] is True
    assert "ssh" in described["devices"]["access_methods"]


# --- (b) 자격증명은 참조만 나간다 --------------------------------------------


def test_listing_devices_never_carries_a_secret(service):
    service.register_device(
        device_id="t1", address=UNREACHABLE, username="physical",
        purpose="fixed_camera", node_tags=["compute.cpu", "tier.fixed_camera"],
    )
    rows = service.device_rows()
    assert rows["configured"] is True
    row = next(d for d in rows["devices"] if d["device_id"] == "t1")
    dumped = json.dumps(rows)
    assert '"secret"' not in dumped and '"password"' not in dumped
    assert "has_secret" in dumped  # the redacted view is what is served instead
    assert row["credential"]["has_secret"] is False
    assert row["credential"]["auth_method"] == "key"


def test_the_persisted_device_file_holds_no_secret(service, tmp_path):
    service.register_device(
        device_id="t1", address=UNREACHABLE, username="physical", purpose="fixed_camera",
    )
    saved = json.loads((tmp_path / "devices.json").read_text(encoding="utf-8"))
    assert saved["devices"][0]["purpose_id"] == "fixed_camera"
    assert "secret" not in json.dumps(saved) and "password" not in json.dumps(saved)


def test_a_credential_file_readable_by_others_is_refused_without_killing_the_page(tmp_path):
    credentials = tmp_path / "device_credentials.json"
    credentials.write_text(json.dumps({"credentials": []}), encoding="utf-8")
    os.chmod(credentials, 0o644)
    service = serve.StatusService(serve.load_ui_config(_config_with(tmp_path)))

    assert service.device_info["configured"] is False
    assert "credential_store_rejected" in service.device_info["reason"]
    assert "group/world" in service.device_info["reason"]
    # 거절이 화면 전체를 죽이지 않는다(AI-C-05).
    assert service.residency("pi6")["purpose"]["purpose_id"] == "fixed_camera"
    assert any(e["name"] == "device_registry_unavailable" for e in service.recent_events())


# --- (c) 등록 → 목적 → 배치 결정 ----------------------------------------------


def test_registering_an_address_and_purpose_produces_a_residency_decision(service):
    result = service.register_device(
        device_id="cam-9", address=UNREACHABLE, username="physical",
        purpose="fixed_camera", node_tags=["compute.cpu", "tier.fixed_camera", "sensor.camera.imx708"],
    )
    residency = result["residency"]
    assert residency["purpose"]["purpose_id"] == "fixed_camera"
    assert "media.video_input" in residency["ondevice_kinds"]
    # 이 장치는 이제 노드로도 보인다 — 나머지 축이 그대로 쓰인다(AI-C-10).
    assert service.config.node("cam-9").purpose == "fixed_camera"
    assert any(n["node_id"] == "cam-9" for n in service.fleet()["nodes"])


def test_the_same_registration_with_a_different_purpose_plans_a_different_function_set(service):
    for purpose in ("fixed_camera", "ground_robot"):
        service.register_device(
            device_id="dual", address=UNREACHABLE, username="physical", purpose=purpose,
            node_tags=["compute.cpu", "tier.ondevice", "sensor.camera.imx708"],
        )
        planned = service.device_plan("dual")["plan"]
        if purpose == "fixed_camera":
            camera = set(planned.kinds)
        else:
            robot = set(planned.kinds)
    assert camera != robot
    assert "safety.local_judgment" in robot and "safety.local_judgment" not in camera


def test_an_unknown_purpose_is_a_typo_not_a_degraded_mode(service):
    with pytest.raises(serve.UiConfigError) as error:
        service.register_device(
            device_id="x", address=UNREACHABLE, username="physical", purpose="submarine",
        )
    assert "unknown purpose_id" in str(error.value)


def test_a_device_without_a_purpose_registers_but_has_no_plan(service):
    service.register_device(device_id="unassigned", address=UNREACHABLE, username="physical")
    row = next(d for d in service.device_rows()["devices"] if d["device_id"] == "unassigned")
    assert row["purpose"] is None
    with pytest.raises(serve.UiConfigError) as error:
        service.device_plan("unassigned")
    assert "device_has_no_purpose" in str(error.value)


# --- (e) 닿지 않는 장치 -------------------------------------------------------


def test_an_unreachable_device_rejects_instead_of_raising(service):
    service.register_device(
        device_id="gone", address=REFUSED_HOST, port=REFUSED_PORT, username="physical",
        purpose="fixed_camera",
        node_tags=["compute.cpu", "tier.fixed_camera", "sensor.camera.imx708"],
    )
    result = service.device_command("gone", "deploy")
    assert result["actions"], "an unreachable device still produces actions, all rejected"
    assert all(a["accepted"] is False for a in result["actions"])
    assert all(a["rejection_reason"] for a in result["actions"])
    # 거절은 이벤트로 남는다(AI-O-02).
    assert any(e["name"] == "placement_applied" and e["severity"] == "warning" for e in service.recent_events())


def test_probing_a_silent_address_is_measured_total_loss_not_a_guess(service):
    """재봤는데 아무것도 안 돌아온 것은 0.0이고, 아예 못 잰 것은 None이다.

    둘을 같은 숫자로 접으면 "측정 수단이 없는 장치"와 "정말 끊긴 장치"가
    구분되지 않는다(AI-N-03).
    """
    from mission_runtime.providers.link_probe import METHOD_ICMP, LinkMeasurement, link_profile_from

    service.register_device(
        device_id="gone", address=UNREACHABLE, username="physical", purpose="fixed_camera",
    )
    probed = service.probe_device_link("gone", count=2)
    assert probed["measurement"]["received"] == 0
    assert probed["profile"]["quality"] == 0.0
    assert probed["profile"]["source"].startswith("measured:")
    # 못 잰 경우는 같은 함수가 None을 돌려준다.
    assert link_profile_from(LinkMeasurement("h", METHOD_ICMP, reason="probe_tool_unavailable")) is None


# --- (f) 거절 상태코드 --------------------------------------------------------


def test_unknown_device_and_unknown_command_are_refused(service):
    with pytest.raises(serve.UiConfigError) as unknown_device:
        service.device_command("nope", "deploy")
    assert "unknown_device" in str(unknown_device.value)
    service.register_device(device_id="t1", address=UNREACHABLE, username="physical")
    with pytest.raises(serve.UiConfigError) as unknown_command:
        service.device_command("t1", "self_destruct")
    assert "unknown_device_command" in str(unknown_command.value)


def test_rollback_without_a_unit_is_refused(service):
    service.register_device(device_id="t1", address=UNREACHABLE, username="physical")
    with pytest.raises(serve.UiConfigError):
        service.device_command("t1", "rollback")


# --- HTTP ---------------------------------------------------------------------


def test_http_routes_serve_the_device_axis(service):
    service.set_mode(serve.MODE_REVIEW)   # 장치 축 제어 경로를 시험한다
    server = serve.make_server(service, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = serve.server_url(server).rstrip("/")

    def post(path, body):
        request = urllib.request.Request(
            f"{base}{path}", data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())

    try:
        with urllib.request.urlopen(f"{base}/api/devices", timeout=5) as response:
            listed = json.loads(response.read())
        assert listed["configured"] is True
        assert set(listed["purposes"]) >= {"fixed_camera", "ground_robot", "river_surveillance_drone"}
        assert "deploy" in listed["commands"]

        created = post("/api/devices", {
            "device_id": "http-1", "address": UNREACHABLE, "username": "physical",
            "purpose": "fixed_camera", "node_tags": ["compute.cpu", "tier.fixed_camera"],
        })
        assert created["residency"]["purpose"]["purpose_id"] == "fixed_camera"

        refreshed = post("/api/devices/command", {"device_id": "http-1", "command": "refresh"})
        assert refreshed["command"] == "refresh"

        for body, expected in (
            ({"device_id": "missing", "command": "refresh"}, 404),
            ({"device_id": "http-1", "command": "nonsense"}, 400),
            ({"command": "refresh"}, 400),
        ):
            with pytest.raises(urllib.error.HTTPError) as error:
                post("/api/devices/command", body)
            assert error.value.code == expected

        with pytest.raises(urllib.error.HTTPError) as error:
            post("/api/devices", {"device_id": "x", "address": UNREACHABLE,
                                  "username": "u", "smuggled": "value"})
        assert error.value.code == 400
        assert "unknown registration field" in json.loads(error.value.read())["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# --- (g) 라벨 -----------------------------------------------------------------


def test_the_device_panel_is_labelled_in_both_languages(service):
    assert service.labels_missing() == []
    ui = service.labels()["ui"]
    for key in ("devices", "device_register", "device_deploy", "device_rollback",
                "liveness", "readiness", "device_state", "device_bootstrap_note"):
        assert key in ui, f"the device panel uses ui.{key} but the labels file has no entry"
        for language in service.labels()["languages"]:
            assert ui[key].get(language), f"ui.{key}.{language} is empty"
