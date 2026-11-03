"""implements: AI-C-05, AI-C-13, AI-C-18, AI-B-03, AI-B-04, AI-O-02, AI-O-03, AI-O-04, AI-C-19 (review tooling)
tests: the 2nd-round status UI (장비 bring-up 계획 노트(비공개)
§3) over the hardware config — (a) `solo_roles` / `combo_roles` per mission (M1 solo
fixed_camera, M7 and M10 solo ugv, M5 no cover) and the greedy cover rule in
isolation, (b) the failure `trace` (M5 → observation.aerial @ uav → best candidate
x500-companion-camera → missing tag sensor.camera.imx708_wide; ACTIVE → empty;
DEGRADED covers the missing optional kind), (c) freshness: null when nothing was
verified, populated from the newest hw_smoke report (both field spellings), TTL
table equal to the harness's, never an invented timestamp, and the "미검증 장비
포함" list following it, (d) execution plans: a placement records one plan with
requester/correlation, retrievable by id and by correlation, reset clears the
log, `apply_placement` keeps its old return shape, (e) HTTP smoke on the
hardware config for /api/plans and the new fields, (f) labels: every literal
`t('key')` / `data-t` in index.html has ko/en and `labels_missing` is empty.

`tools/` is not a package; serve.py is imported by path under the same module
name the other status-UI tests use so the dataclasses are shared.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from mission_runtime.contracts.capability_contract import RuntimeInstance
from mission_runtime.runtime.execution_plan import Requester

FRAMEWORK_DIR = Path(__file__).resolve().parents[1]
SERVE_PY = FRAMEWORK_DIR / "tools" / "status_ui" / "serve.py"
INDEX_HTML = FRAMEWORK_DIR / "tools" / "status_ui" / "index.html"
CONFIG_DIR = FRAMEWORK_DIR / "config"
HARDWARE_CONFIG = CONFIG_DIR / "status_ui.hardware.example.json"
HARDWARE_MANIFEST = CONFIG_DIR / "providers.hardware.example.json"
LABELS = CONFIG_DIR / "status_ui.labels.json"

T0 = 1_790_000_000.0  # a fixed "now" so ages are deterministic


def _import_serve():
    name = "status_ui_serve_under_test"
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


def _hardware_raw(**overrides) -> dict:
    """The hardware config with absolute manifest/labels paths so a copy can
    live in tmp_path; `hw_smoke_reports` is dropped unless given."""
    raw = json.loads(HARDWARE_CONFIG.read_text(encoding="utf-8"))
    raw["providers_manifest"] = str(HARDWARE_MANIFEST)
    raw["labels"] = str(LABELS)
    raw.pop("hw_smoke_reports", None)
    raw.update(overrides)
    return raw


@pytest.fixture
def isolated_config(serve, tmp_path):
    """Hardware config without any hw_smoke directory: nothing verified."""
    path = tmp_path / "ui.json"
    path.write_text(json.dumps(_hardware_raw(), ensure_ascii=False), encoding="utf-8")
    return serve.load_ui_config(path)


@pytest.fixture
def service(serve, isolated_config):
    return serve.StatusService(isolated_config, control_mode="local", clock=lambda: T0)


@pytest.fixture
def functions(service):
    return {f["function_id"]: f for f in service.functions()["functions"]}


# --- (a) solo / combo roles ------------------------------------------------------


def test_m1_solo_fixed_camera(functions):
    m1 = functions["m1_continuous_surveillance"]
    assert m1["roles_by_kind"] == {"observation.fixed": ["fixed_camera"]}
    assert m1["solo_roles"] == ["fixed_camera"]
    assert m1["combo_roles"] == ["fixed_camera"]  # a solo tier is its own combo


def test_m7_solo_ugv(functions):
    m7 = functions["m7_object_retrieval"]
    assert m7["state"] == "ACTIVE"
    assert set(m7["roles_by_kind"]) == {"manipulation.grasp", "locomotion.ground", "locomotion.holonomic"}
    for kind in m7["roles_by_kind"]:
        assert m7["roles_by_kind"][kind] == ["ugv"], kind
    assert m7["solo_roles"] == ["ugv"] and m7["combo_roles"] == ["ugv"]


def test_m10_solo_ugv_even_though_other_tiers_help(functions):
    m10 = functions["m10_dt_map_update"]
    assert m10["state"] == "ACTIVE"
    rbk = m10["roles_by_kind"]
    assert rbk["observation.mobile"] == ["ugv"]
    assert rbk["perception.depth"] == ["ugv", "edge", "server"]  # depth is also served on edge/server
    assert rbk["pose.self_estimate"] == ["ugv", "uav"]
    # Only ugv serves *every* required kind; edge/server/uav each serve a subset.
    assert m10["solo_roles"] == ["ugv"]
    assert m10["combo_roles"] == ["ugv"]


def test_m5_has_no_solo_and_no_cover_because_aerial_view_is_unserved(functions):
    m5 = functions["m5_wide_area_search"]
    assert m5["state"] == "DISABLED"
    assert m5["roles_by_kind"]["observation.aerial"] == []
    assert m5["solo_roles"] == [] and m5["combo_roles"] == []


def test_every_configured_function_is_reported(isolated_config, functions):
    assert len(functions) == 15
    assert [f.function_id for f in isolated_config.functions] == list(functions)
    for fn in functions.values():
        assert {"roles_by_kind", "solo_roles", "combo_roles", "trace", "unverified_nodes"} <= set(fn)


def test_greedy_cover_rule_is_deterministic(serve):
    roles = ["a", "b", "c"]
    solo, combo = serve.solo_and_combo_roles(roles, {"k1": ["a"], "k2": ["b"], "k3": ["a", "b"]})
    assert solo == [] and combo == ["a", "b"]  # a covers 2 first, then b
    # ties are broken by config order: b and c both cover one kind, b comes first
    solo, combo = serve.solo_and_combo_roles(roles, {"k1": ["c", "b"]})
    assert solo == ["b", "c"] and combo == ["b"]
    # an unserved kind makes the cover impossible
    assert serve.solo_and_combo_roles(roles, {"k1": ["a"], "k2": []}) == ([], [])
    # no required kinds: vacuously every role is solo, and the cover is empty
    assert serve.solo_and_combo_roles(roles, {}) == (roles, [])


# --- (b) failure trace --------------------------------------------------------------


def test_m5_trace_names_the_drone_camera_tag_at_uav(functions, isolated_config):
    m5 = functions["m5_wide_area_search"]
    roles = isolated_config.roles()
    # required kinds first, one entry per role each
    aerial = [t for t in m5["trace"] if t["kind"] == "observation.aerial"]
    assert [t["role"] for t in aerial] == roles
    assert all(t["required"] for t in aerial)
    uav = next(t for t in aerial if t["role"] == "uav")
    assert uav["node_id"] == "x500-companion"
    assert uav["reason_token"] == "required_hw_tag_missing"
    assert uav["best_candidate"] == "x500-companion-camera"
    assert uav["missing_tags"] == ["sensor.camera.imx708_wide"]  # 원문 §6 "드론 카메라 미탑재"
    # on the edge tier the same kind fails on a different tag list
    edge = next(t for t in aerial if t["role"] == "edge")
    assert edge["reason_token"] == "required_hw_tag_missing"
    assert set(edge["missing_tags"]) == {"sensor.camera.imx708_wide", "tier.uav"}
    # a tag list is only split for tag reasons; a kind nobody registered has no fix-by-tag
    risk = functions["risk_analysis"]["trace"]
    assert risk and all(t["kind"] == "risk.event_input" for t in risk)
    assert {t["reason_token"] for t in risk} == {"no_provider_registered"}
    assert all(t["missing_tags"] == [] and t["best_candidate"] is None for t in risk)


def test_trace_is_empty_for_active_and_covers_optional_for_degraded(functions):
    assert functions["m7_object_retrieval"]["trace"] == []
    assert functions["m2_close_inspection"]["trace"] == []
    m1 = functions["m1_continuous_surveillance"]
    assert m1["state"] == "DEGRADED"
    kinds = {(t["kind"], t["required"]) for t in m1["trace"]}
    assert kinds == {("observation.low_light", False)}
    fixed_camera = next(t for t in m1["trace"] if t["role"] == "fixed_camera")
    assert fixed_camera["best_candidate"] == "imx708-noir-libcamera"
    assert fixed_camera["missing_tags"] == ["sensor.camera.noir"]


def test_missing_tags_helper_splits_only_tag_reasons(serve):
    assert serve._missing_tags("required_hw_tag_missing", "a,b") == ["a", "b"]
    assert serve._missing_tags("required_runtime_tag_missing", "runtime.x") == ["runtime.x"]
    assert serve._missing_tags("over_budget", "a") == []
    assert serve._missing_tags("no_provider_registered", None) == []


# --- (c) freshness ----------------------------------------------------------------


def test_freshness_is_null_when_nothing_was_verified(service):
    assert service.describe()["hw_smoke"]["reason"] == "not_configured"
    for node in service.fleet()["nodes"]:
        assert node["freshness"] is None
    for node in service.describe()["nodes"]:
        assert node["freshness"] is None
    assert service.resolve("pi6")["freshness"] is None
    assert service.freshness_for("pi6") is None


def test_missing_reports_dir_is_not_an_error(serve, tmp_path):
    path = tmp_path / "ui.json"
    path.write_text(json.dumps(_hardware_raw(hw_smoke_reports="nope"), ensure_ascii=False), encoding="utf-8")
    service = serve.StatusService(serve.load_ui_config(path), control_mode="local", clock=lambda: T0)
    assert service.describe()["hw_smoke"]["reason"] == "reports_dir_missing"
    assert service.freshness_for("pi6") is None


def _write_report(directory: Path, name: str, results: list[dict], generated_at: float) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps({"generated_at": generated_at, "results": results}), encoding="utf-8")
    return path


def test_freshness_comes_from_the_newest_report_in_both_spellings(serve, tmp_path):
    reports = tmp_path / "smoke"
    # an older report says pi6 was fine — must be ignored in favour of the newest
    old = _write_report(reports, "20260101-0000.json", [
        {"device_id": "pi6", "device_probe_level": 3, "ok": True, "device_probe_reason": "reachable", "probed_at": T0 - 5000},
    ], T0 - 5000)
    new = _write_report(reports, "20260928-1200.json", [
        # dictionary spelling: pi6 reached L1 but failed L2 → deepest level decides
        {"device_id": "pi6", "device_probe_level": 1, "ok": True, "device_probe_reason": "reachable", "probed_at": T0 - 10},
        {"device_id": "pi6", "device_probe_level": 2, "ok": False, "device_probe_reason": "tag_mismatch", "probed_at": T0 - 8},
        # short spelling: pi4 passed L1
        {"device_id": "pi4", "level": 1, "ok": True, "reason": "reachable", "probed_at": T0 - 30},
        # no probed_at → skipped: a time is never invented
        {"device_id": "go1-onboard", "level": 1, "ok": True, "reason": "reachable"},
        "garbage",
    ], T0)
    import os
    os.utime(old, (T0 - 5000, T0 - 5000))
    os.utime(new, (T0, T0))
    path = tmp_path / "ui.json"
    path.write_text(json.dumps(_hardware_raw(hw_smoke_reports="smoke"), ensure_ascii=False), encoding="utf-8")
    service = serve.StatusService(serve.load_ui_config(path), control_mode="local", clock=lambda: T0)

    info = service.describe()["hw_smoke"]
    assert info["report"] == str(new) and info["devices"] == 2 and info["reason"] is None

    pi6 = service.freshness_for("pi6")
    assert pi6 == {
        "healthy": False, "checked_at": T0 - 8, "age_s": 8.0, "ttl_s": 300.0, "fresh": False,
        "source": "hw_smoke", "deployment_ref": "hw_smoke:L2:tag_mismatch",
    }
    pi4 = service.freshness_for("pi4")
    assert pi4["healthy"] is True and pi4["fresh"] is True and pi4["ttl_s"] == 60.0 and pi4["age_s"] == 30.0
    assert service.freshness_for("go1-onboard") is None
    # the same dict rides on fleet/config nodes
    fleet = {n["node_id"]: n for n in service.fleet()["nodes"]}
    assert fleet["pi6"]["freshness"] == pi6 and fleet["pi4"]["freshness"] == pi4 and fleet["server-1"]["freshness"] is None
    config_nodes = {n["node_id"]: n for n in service.describe()["nodes"]}
    assert config_nodes["pi6"]["freshness"] == pi6

    # after the TTL the record is stale but still not invented
    later = service.freshness_for("pi4", now=T0 + 100)
    assert later["fresh"] is False and later["healthy"] is True and later["age_s"] == 130.0


def test_ttl_table_matches_the_smoke_harness(serve):
    if str(FRAMEWORK_DIR) not in sys.path:
        sys.path.insert(0, str(FRAMEWORK_DIR))
    from tools.hw_smoke import smoke

    assert serve.HW_SMOKE_LEVEL_TTL_S == smoke.LEVEL_TTL_S


def test_report_parser_tolerates_garbage(serve):
    assert serve.runtime_instances_from_report(None) == {}
    assert serve.runtime_instances_from_report({"results": "x"}) == {}
    assert serve.runtime_instances_from_report({"results": [{"device_id": "d", "level": "1", "probed_at": 1.0}]}) == {}
    instances = serve.runtime_instances_from_report(
        {"results": [{"device_id": "d", "level": 3, "ok": True, "reason": "reachable", "probed_at": 5.0}]}
    )
    assert instances["d"] == RuntimeInstance(
        instance_id="d", deployment_ref="hw_smoke:L3:reachable", healthy=True, health_ttl=600.0, health_checked_at=5.0
    )


def test_injected_and_probed_instances_have_their_own_sources(serve, isolated_config):
    injected = RuntimeInstance("pi6", "test", True, 60.0, T0 - 1)
    service = serve.StatusService(isolated_config, control_mode="local", runtime_instances={"pi6": injected}, clock=lambda: T0)
    assert service.freshness_for("pi6")["source"] == "injected"
    service.note_probe("pi4", healthy=False, checked_at=T0 - 2)
    pi4 = service.freshness_for("pi4")
    assert pi4["source"] == "device_probe" and pi4["healthy"] is False and pi4["checked_at"] == T0 - 2 and pi4["age_s"] == 2.0


def test_unverified_nodes_follow_verified_flag_and_freshness(serve, isolated_config, service):
    # nothing verified: every charged node is unverified
    m1 = {f["function_id"]: f for f in service.functions()["functions"]}["m1_continuous_surveillance"]
    charged = {e["node_id"] for e in m1["resources"]["by_kind"]}
    assert set(m1["unverified_nodes"]) == charged and "pi6" in charged
    # a freshness record for those nodes clears the note — unless the config says verified:false
    instances = {node_id: RuntimeInstance(node_id, "test", True, 60.0, T0) for node_id in charged}
    verified_service = serve.StatusService(isolated_config, control_mode="local", runtime_instances=instances, clock=lambda: T0)
    m1 = {f["function_id"]: f for f in verified_service.functions()["functions"]}["m1_continuous_surveillance"]
    assert m1["unverified_nodes"] == []
    m10 = {f["function_id"]: f for f in verified_service.functions()["functions"]}["m10_dt_map_update"]
    assert isolated_config.node("go1-onboard").verified is False
    assert "go1-onboard" in m10["unverified_nodes"]  # verified:false stays unverified even with a record
    assert isolated_config.node("pi6").verified is True


def test_verified_must_be_boolean(serve, tmp_path):
    raw = _hardware_raw()
    raw["nodes"][0]["verified"] = "no"
    path = tmp_path / "ui.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(serve.UiConfigError, match="verified"):
        serve.load_ui_config(path)


# --- (d) execution plans ---------------------------------------------------------------


def test_placement_records_a_plan_retrievable_by_id_and_correlation(service):
    plan = service.place(
        "edge-gpu", function_id="door_detection", requester=Requester("operator", "u1"), correlation_id="c-1"
    )
    assert plan.plan_id.startswith("plan-") and plan.node_id == "edge-gpu" and plan.created_at == T0
    assert plan.function_id == "door_detection" and plan.correlation_id == "c-1"
    assert plan.placement_actions and all(a.accepted for a in plan.placement_actions)

    summaries = service.plan_summaries()
    assert summaries["count"] == 1 and summaries["capacity"] == 200
    summary = summaries["plans"][0]
    assert summary["plan_id"] == plan.plan_id
    assert summary["requester"] == {"role": "operator", "id": "u1"}
    assert summary["node_role"] == "edge"
    assert summary["actions"] == summary["accepted"] == len(plan.placement_actions) and summary["rejected"] == 0
    assert "perception.classify" in summary["served_kinds"] and "locomotion.ground" in summary["unserved_kinds"]

    detail = service.plan_detail(plan.plan_id)
    assert detail["requester"] == {"role": "operator", "id": "u1"} and detail["node_role"] == "edge"
    assert {r["kind"] for r in detail["resolutions"]} == set(service.config.profile.active_capability_kinds)
    assert {a["kind"] for a in detail["placement_actions"]} <= {r["kind"] for r in detail["resolutions"]}
    # everything is an id or a token, never a label
    assert "가능" not in json.dumps(detail, ensure_ascii=False)

    other = service.place("edge-dev")
    assert other.function_id == "*" and other.requester is None and other.correlation_id is None
    assert [p["plan_id"] for p in service.plan_summaries()["plans"]] == [other.plan_id, plan.plan_id]  # newest first
    assert [p["plan_id"] for p in service.plan_summaries(correlation_id="c-1")["plans"]] == [plan.plan_id]
    assert service.plan_summaries(correlation_id="nope")["plans"] == []
    assert [e["payload"]["plan_id"] for e in service.recent_events() if e["name"] == "execution_plan_recorded"] == [
        plan.plan_id, other.plan_id
    ]


def test_apply_placement_keeps_its_shape_and_records_a_plan(service):
    actions = service.apply_placement("edge-gpu")
    assert actions and set(actions[0]) == {"kind", "provider_id", "command", "accepted", "rejection_reason"}
    assert service.plan_summaries()["count"] == 1
    assert service.plan_summaries()["plans"][0]["function_id"] == "*"
    # the second identical apply is a no-op placement but still one plan (a request happened)
    assert service.apply_placement("edge-gpu") == []
    assert service.plan_summaries()["count"] == 2
    assert service.plan_summaries()["plans"][0]["actions"] == 0


def test_reset_clears_plans_and_unknown_plan_is_an_error(service, serve):
    plan = service.place("edge-gpu", correlation_id="c-2")
    assert len(service.plans) == 1
    service.reset()
    assert len(service.plans) == 0 and service.plan_summaries()["plans"] == []
    with pytest.raises(serve.UiConfigError, match="unknown_plan"):
        service.plan_detail(plan.plan_id)


def test_plan_log_capacity_is_a_window(serve, isolated_config):
    service = serve.StatusService(isolated_config, control_mode="local", plan_capacity=2, clock=lambda: T0)
    ids = [service.place("edge-gpu").plan_id for _ in range(3)]
    assert [p["plan_id"] for p in service.plan_summaries()["plans"]] == [ids[2], ids[1]]
    assert service.plan_summaries()["capacity"] == 2


# --- (e) HTTP smoke on the hardware config --------------------------------------------


@pytest.fixture
def running_server(serve, service):
    service.set_mode(serve.MODE_REVIEW)   # 배치 적용까지 시험하는 스모크다
    server = serve.make_server(service, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield serve.server_url(server)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get(url: str):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, response.headers, json.loads(response.read().decode("utf-8"))


def _post(url: str, body: dict):
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_http_smoke_hardware_config_and_plans(running_server):
    base = running_server

    status, _, config = _get(base + "api/config")
    assert status == 200
    assert config["roles"] == ["fixed_camera", "ugv", "uav", "edge", "server"]
    assert len(config["functions"]) == 15
    assert config["labels_missing"] == []
    assert config["hw_smoke"]["reason"] == "not_configured"
    assert all("freshness" in n and "verified" in n for n in config["nodes"])

    status, _, functions = _get(base + "api/functions")
    by_id = {f["function_id"]: f for f in functions["functions"]}
    assert by_id["m1_continuous_surveillance"]["solo_roles"] == ["fixed_camera"]
    uav = next(t for t in by_id["m5_wide_area_search"]["trace"] if t["role"] == "uav" and t["kind"] == "observation.aerial")
    assert uav["missing_tags"] == ["sensor.camera.imx708_wide"]
    assert "가능" not in json.dumps(functions, ensure_ascii=False)

    status, _, plans = _get(base + "api/plans")
    assert status == 200 and plans == {"count": 0, "capacity": 200, "correlation_id": None, "plans": []}

    status, placed = _post(base + "api/placement", {
        "node_id": "edge-gpu", "function_id": "door_detection",
        "requester": {"role": "operator", "id": "jny"}, "correlation_id": "corr-1",
    })
    assert status == 200 and placed["plan_id"].startswith("plan-") and placed["correlation_id"] == "corr-1"
    assert placed["actions"] and placed["state"]["bound"]

    status, _, plans = _get(base + "api/plans?limit=5")
    assert plans["count"] == 1 and plans["plans"][0]["requester"] == {"role": "operator", "id": "jny"}
    status, _, by_corr = _get(base + "api/plans?correlation_id=corr-1")
    assert [p["plan_id"] for p in by_corr["plans"]] == [placed["plan_id"]]
    status, _, detail = _get(base + "api/plans/" + placed["plan_id"])
    assert detail["function_id"] == "door_detection" and detail["node_role"] == "edge" and detail["placement_actions"]

    with pytest.raises(urllib.error.HTTPError) as missing:
        _get(base + "api/plans/plan-nope")
    assert missing.value.code == 404
    with pytest.raises(urllib.error.HTTPError) as bad_requester:
        _post(base + "api/placement", {"node_id": "edge-gpu", "requester": {"id": "no-role"}})
    assert bad_requester.value.code == 400
    with pytest.raises(urllib.error.HTTPError) as bad_limit:
        _get(base + "api/plans?limit=0")
    assert bad_limit.value.code == 400

    status, reset = _post(base + "api/reset", {})
    assert status == 200 and reset["ok"] is True
    status, _, plans = _get(base + "api/plans")
    assert plans["count"] == 0

    # the page itself: served, has the executions tab, loads no external resource
    with urllib.request.urlopen(base, timeout=5) as response:
        html = response.read().decode("utf-8")
        assert response.headers["Content-Type"].startswith("text/html")
    assert 'id="tab-executions"' in html and 'data-tab="executions"' in html
    assert not re.search(r"https?://", html)


# --- (f) labels ---------------------------------------------------------------------------


def test_labels_complete_for_hardware_config_and_every_page_string(service):
    assert service.labels_missing() == []
    labels = service.labels()
    assert labels["languages"] == ["ko", "en"]
    html = INDEX_HTML.read_text(encoding="utf-8")
    used = set(re.findall(r"\bt\('([a-z0-9_]+)'", html)) | set(re.findall(r'data-t="([a-z0-9_]+)"', html))
    assert used, "no page strings found"
    missing = sorted(key for key in used if key not in labels["ui"])
    assert missing == [], missing
    for key in ("tab_executions", "solo_roles", "combo_roles", "failure_trace", "freshness_checked_ago",
                "freshness_unverified", "unverified_included", "plans", "reselection_trace", "requester"):
        assert labels["ui"][key]["ko"] and labels["ui"][key]["en"], key
    # the alias table is a cross-reference, not a label: the page shows it next to kind names
    assert labels["aliases"]["capability_kinds"]["observation.aerial"] == "C-04"
