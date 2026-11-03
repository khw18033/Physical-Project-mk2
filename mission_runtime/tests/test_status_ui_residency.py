"""implements: AI-C-15, AI-C-05, AI-B-04, AI-B-10, AI-N-03 (review tooling)
tests: (a) 설정이 장치 목적·링크를 읽는다, (b) 등록된 장치 하나의 상주 결정이
사유와 함께 나온다, (c) "링크가 나빠지면" what-if이 배치를 바꾼다, (d) 목적을
선언하지 않은 노드에서도 화면이 죽지 않는다, (e) 온디바이스 행은 기존
ZoneApplication 해석을 그대로 싣는다, (f) 사유·자세·단절 동작이 전부 통제
어휘다, (g) HTTP 경로 smoke, (h) 예시 설정의 라벨이 두 언어 모두 채워져 있다.

`tools/status_ui/serve.py`는 패키지가 아니라 스크립트라 경로로 import한다
(tests/test_status_ui.py와 같은 방식).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

from mission_runtime.contracts.data_dictionary import (
    LINK_POSTURE_REASONS,
    LINK_POSTURES,
    RESIDENCY_DECISION_REASONS,
    state_change_reason_token,
)
from mission_runtime.contracts.profile import OUTAGE_BEHAVIORS

FRAMEWORK_DIR = Path(__file__).resolve().parents[1]
SERVE_PY = FRAMEWORK_DIR / "tools" / "status_ui" / "serve.py"
RESIDENCY_CONFIG = FRAMEWORK_DIR / "config" / "status_ui.ondevice.example.json"

#: 화면의 "링크 저하" 버튼이 보내는 것과 같은 값.
DEGRADED_LINK = {"source": "whatif:link_degrades", "quality": 0.2, "stability": 0.4, "samples": 10}


def _import_serve():
    name = "status_ui_serve_residency_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SERVE_PY)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def serve():
    return _import_serve()


@pytest.fixture
def service(serve):
    return serve.StatusService(serve.load_ui_config(RESIDENCY_CONFIG), control_mode="local")


def rows_by_kind(payload: dict) -> dict[str, dict]:
    return {row["kind"]: row for row in payload["rows"]}


# --- (a) 설정 ---------------------------------------------------------------


def test_config_reads_device_purposes_and_per_node_link(serve):
    config = serve.load_ui_config(RESIDENCY_CONFIG)

    assert set(config.purposes) == {"river_surveillance_drone", "ground_robot", "fixed_camera"}
    assert config.node("drone-1").purpose == "river_surveillance_drone"
    assert config.node("go1-onboard").purpose == "ground_robot"
    # 같은 목적이지만 이 장치만 자기 링크 관측을 들고 있다.
    assert config.node("pi2").purpose == "ground_robot"
    assert config.node("pi2").link is not None
    assert config.node("go1-onboard").link is None
    assert config.node("edge-gpu").purpose is None

    assert config.purpose_for("drone-1").purpose_id == "river_surveillance_drone"
    assert config.purpose_for("edge-gpu") is None


def test_an_unknown_purpose_id_fails_at_load_time(serve, tmp_path):
    raw = json.loads(RESIDENCY_CONFIG.read_text(encoding="utf-8"))
    raw["nodes"][0]["purpose"] = "no_such_purpose"
    raw["providers_manifest"] = str(RESIDENCY_CONFIG.parent / raw["providers_manifest"])
    raw["device_purposes"] = str(RESIDENCY_CONFIG.parent / raw["device_purposes"])
    raw["labels"] = str(RESIDENCY_CONFIG.parent / raw["labels"])
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(serve.UiConfigError) as error:
        serve.load_ui_config(path)
    assert "unknown purpose_id:no_such_purpose" in str(error.value)


# --- (b) 한 장치의 상주 결정 -------------------------------------------------


def test_residency_answers_which_functions_live_on_the_drone_and_why(service):
    result = service.residency("drone-1")

    assert result["purpose"]["purpose_id"] == "river_surveillance_drone"
    assert result["link"]["posture"] == "reducing"
    assert result["link_origin"] == "purpose"  # 이 노드는 자기 링크 관측이 없다

    rows = rows_by_kind(result)
    # 사용자가 이름 붙인 세 가지가 말단에 남는다.
    for kind in ("perception.coverage_estimate", "mission.dispatch", "safety.local_judgment"):
        assert rows[kind]["placement"] == "ondevice"
        assert rows[kind]["reason"] == "resident_by_purpose"
        assert rows[kind]["survives_outage"] is True
    # 불안정 링크가 link_dependent 기능을 끌어왔다.
    assert rows["perception.track"]["reason"] == "link_posture_requires_local:reducing"
    # 의미 분류는 엣지가 맡고, 단절 중에는 그 기능만 멈춘다.
    assert rows["perception.classify"]["placement"] == "edge"
    assert rows["perception.classify"]["edge_service"] == "edge.classifier"
    assert "perception.classify" in result["outage"]["stops_until_link_returns"]


def test_residency_answers_the_robot_case_from_the_same_endpoint(service):
    rows = rows_by_kind(service.residency("go1-onboard"))

    # 말단에 남는 것은 엣지 파이프라인의 축소판이 아니라 **더 가벼운 다른 스택**이다.
    for kind in ("perception.detect", "perception.depth", "perception.track", "control.locomotion"):
        assert rows[kind]["placement"] == "ondevice"
    # "이 특정 클래스를 찾아줘"와 zero-shot 인식은 엣지에 묻는다.
    assert rows["perception.classify"]["placement"] == "edge"
    assert rows["perception.detect_ovd"]["placement"] == "edge"
    # edge_served이지 link_dependent가 아니다 — 링크가 나빠졌다고 이것을 말단으로
    # 끌어오면 121ms가 2223ms가 되어 실시간이 아니게 된다(실측). 끌어오는 대신
    # 이미 상주하는 class-agnostic proposal로 내려간다.
    assert rows["perception.detect_ovd"]["reason"] == "edge_served_by_purpose"
    assert rows["perception.detect_ovd"]["local_fallback_kind"] == "perception.detect"
    # depth는 해상도를 줄여 여유를 만드는 손잡이가 아니라고 선언돼 있다.
    assert rows["perception.depth"]["quality_is_safety_affecting"] is True


def test_two_devices_with_the_same_purpose_differ_only_by_their_link(service):
    """같은 목적, 다른 링크 → 다른 상주 집합.

    고정 카메라로 보인다. `ground_robot`은 이제 link_dependent kind가 하나도
    없는데, 그것이 의도다 — 그 목적의 원격 기능은 링크가 나빠져도 말단으로
    끌려오지 않고 더 가벼운 상주 기능으로 내려간다. 링크가 배치를 바꾸는
    성질 자체는 목적과 무관한 프레임워크 성질이므로, 실제로 link_dependent를
    선언한 목적에서 확인하는 것이 맞다.
    """
    good = service.residency("pi6")
    bad = service.residency("pi6", link=DEGRADED_LINK)

    assert good["purpose"]["purpose_id"] == bad["purpose"]["purpose_id"] == "fixed_camera"
    assert good["link"]["posture"] == "remote_ok"
    assert bad["link"]["posture"] == "local_only"
    assert good["link_origin"] == "node"
    assert len(bad["ondevice_kinds"]) > len(good["ondevice_kinds"])
    assert "perception.detect" in bad["ondevice_kinds"]
    assert "perception.detect" not in good["ondevice_kinds"]


# --- (c) "링크가 나빠지면" what-if --------------------------------------------


def test_the_link_degrades_whatif_moves_function_onto_the_device(service):
    result = service.residency_whatif("pi6", link=DEGRADED_LINK)

    assert result["baseline"]["link"]["posture"] == "remote_ok"
    assert result["override"]["link"]["posture"] == "local_only"
    changed = [d for d in result["diff"] if d["changed"]]
    assert [d["kind"] for d in changed] == ["perception.detect"]
    assert changed[0]["before_placement"] == "edge"
    assert changed[0]["after_placement"] == "ondevice"
    assert changed[0]["after_reason"] == "link_posture_requires_local:local_only"


def test_the_heavy_remote_stack_never_comes_home_however_bad_the_link(service):
    """AI-C-05의 축소는 "같은 것을 못 하는 곳에서 돌리기"가 아니다.

    링크가 완전히 죽어도 zero-shot 인식은 엣지 몫으로 남고, 대신 이미 말단에
    있는 더 가벼운 기능으로 내려간다. 이것을 말단으로 끌어오는 축소는
    실시간성을 잃으므로 축소가 아니라 고장이다(엣지 121ms vs 말단 전량 2223ms).
    """
    result = service.residency_whatif("go1-onboard", link=DEGRADED_LINK)

    assert result["override"]["link"]["posture"] == "local_only"
    assert [d["kind"] for d in result["diff"] if d["changed"]] == []
    rows = rows_by_kind(result["override"])
    assert rows["perception.detect_ovd"]["placement"] == "edge"
    outage = result["override"]["outage"]
    assert "perception.detect_ovd" in outage["degrades_to_local_fallback"]
    # 내려갈 자리는 실제로 말단에 있어야 한다.
    assert rows["perception.detect_ovd"]["local_fallback_kind"] in result["override"]["ondevice_kinds"]


def test_the_same_whatif_on_a_fixed_camera_picks_the_accelerator_that_device_has(service):
    """AI-B-04: 같은 kind라도 장치가 가진 자원에 따라 다른 provider가 붙는다.
    pi6에는 Coral(accel.edgetpu_usb)이 실제로 꽂혀 있고 pi4에는 없다."""
    pi6 = rows_by_kind(service.residency("pi6", link=DEGRADED_LINK))["perception.detect"]
    pi4 = rows_by_kind(service.residency("pi4", link=DEGRADED_LINK))["perception.detect"]

    assert pi6["placement"] == pi4["placement"] == "ondevice"
    assert pi6["resolution"]["provider_id"] == "rpn-edgetpu"
    assert pi4["resolution"]["provider_id"] == "rpn-ondevice"
    assert pi6["resolution"]["cost"]["compute_units"] < pi4["resolution"]["cost"]["compute_units"]


# --- (d) 목적이 없는 노드 ----------------------------------------------------


def test_a_node_without_a_declared_purpose_is_a_normal_configuration(service):
    result = service.residency("edge-gpu")

    assert result["purpose"] is None
    assert result["rows"] == []
    assert result["outage"] is None
    # 그 노드의 기존 화면은 그대로 동작해야 한다.
    assert service.resolve("edge-gpu")["rows"]


# --- (e) 기존 해석 경로 ------------------------------------------------------


def test_ondevice_rows_carry_the_existing_resolution_and_edge_rows_do_not(service):
    rows = rows_by_kind(service.residency("drone-1"))

    resident = rows["safety.local_judgment"]
    assert resident["resolution"]["state"] in ("ACTIVE", "DEGRADED")
    assert resident["resolution"]["provider_id"]
    # 엣지 kind는 이 장치가 돌릴 것이 아니므로 상태가 없다.
    assert rows["perception.classify"]["resolution"] is None


def test_a_resident_kind_the_terminal_cannot_afford_shows_its_budget_reason(service):
    """상주로 결정된 기능도 말단이 감당 못 하면 그 기능만 빠진다
    (AI-B-06 → AI-C-05, 말단 경량 경계 AI-B-10).

    트리거가 바뀌었다: 예전에는 나쁜 링크가 끌어온 기능이 예산을 넘었다.
    이제 `ground_robot`의 원격 기능은 끌려오지 않으므로, 예산을 넘기는 것은
    상주 집합 자체다. 확인하려는 성질은 같다 — 감당 못 하는 기능 **하나만**
    빠지고 핵심은 남는다.
    """
    rows = rows_by_kind(service.residency("pi2"))
    starved = [
        row for row in rows.values()
        if row["placement"] == "ondevice" and row["resolution"] and row["resolution"]["state"] == "DISABLED"
    ]
    assert starved, "pi2's declared resident set should not fit its budget"
    for row in starved:
        assert row["resolution"]["reason_token"] == "no_compatible_provider_within_budget"
        assert any(alt["reason_token"] == "over_budget" for alt in row["resolution"]["alternatives"])
        assert row["is_core"] is False, "a core kind must not be the one shed for budget"
    # 핵심 기능은 남아 있다.
    assert rows["safety.local_judgment"]["resolution"]["state"] in ("ACTIVE", "DEGRADED")
    assert rows["perception.depth"]["resolution"]["state"] in ("ACTIVE", "DEGRADED")


def test_excluding_a_provider_only_affects_the_kind_it_served(service):
    rows = rows_by_kind(service.residency("go1-onboard", exclude_providers=["ttc-from-depth"]))

    # optional 의존 결손은 DEGRADED까지만 (AI-C-05).
    assert rows["safety.local_judgment"]["resolution"]["state"] == "DEGRADED"
    assert rows["perception.detect"]["resolution"]["state"] == "ACTIVE"


# --- (f) 통제 어휘 -----------------------------------------------------------


def test_every_word_the_residency_view_emits_is_in_the_dictionary(service):
    for node_id in ("drone-1", "go1-onboard", "pi2", "pi6", "pi4"):
        result = service.residency(node_id)
        assert result["link"]["posture"] in LINK_POSTURES
        assert result["link"]["reason_token"] in LINK_POSTURE_REASONS
        for row in result["rows"]:
            assert row["reason_token"] in RESIDENCY_DECISION_REASONS
            assert row["outage_behavior"] in OUTAGE_BEHAVIORS
            assert row["placement"] in ("ondevice", "edge")
        for violation in result["violations"]:
            assert state_change_reason_token(violation["violation"]) == violation["violation_token"]


def test_the_vocabulary_endpoint_publishes_the_residency_axis(service):
    vocab = service.vocabulary()

    assert vocab["link_postures"] == list(LINK_POSTURES)
    assert set(vocab["residency_reasons"]) <= set(RESIDENCY_DECISION_REASONS)
    assert vocab["outage_behaviors"] == list(OUTAGE_BEHAVIORS)


# --- (g) HTTP ----------------------------------------------------------------


def test_http_routes_serve_the_residency_axis(serve, service):
    server = serve.make_server(service, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = serve.server_url(server).rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/api/residency?node_id=drone-1", timeout=5) as response:
            payload = json.loads(response.read())
        assert payload["purpose"]["purpose_id"] == "river_surveillance_drone"

        request = urllib.request.Request(
            f"{base}/api/residency/whatif",
            data=json.dumps({"node_id": "pi6", "link": DEGRADED_LINK}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            whatif = json.loads(response.read())
        assert [d["kind"] for d in whatif["diff"] if d["changed"]] == ["perception.detect"]

        with urllib.request.urlopen(f"{base}/api/config", timeout=5) as response:
            config = json.loads(response.read())
        assert [p["purpose_id"] for p in config["device_purposes"]]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# --- (h) 라벨 -----------------------------------------------------------------


def test_the_labels_file_covers_every_residency_id_in_both_languages(service):
    assert service.labels_missing() == []
    labels = service.labels()
    assert set(labels["purposes"]) >= {"river_surveillance_drone", "ground_robot", "fixed_camera"}
    assert set(labels["link_postures"]) == set(LINK_POSTURES)
