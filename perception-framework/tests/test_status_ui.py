"""implements: AI-C-05, AI-C-13, AI-C-18, AI-B-04, AI-B-06, AI-O-02 (review tooling)
tests: (a) config loader builds nodes/specs/functions, (b) derive_grade mapping
is display-only, (c) example config resolves as documented (edge-gpu ACTIVE for
every kind but the on-device-only locomotion, pi6 sheds optionals and shows
required_hw_tag_missing), (d) what-if diff flips a kind on a tag/budget change,
(e) placement is idempotent and exclusion yields stop->start, (f) HTTP smoke on
127.0.0.1 port 0, (g) the function axis — `TaskIntent.evaluate_availability`
over the fleet's served kinds, resources per tier, minimal supplement per tier,
(h) the ko/en labels file covers every id the page can show.

`tools/status_ui/serve.py` is a stdlib-only review panel over
`ZoneApplication.resolve()` / `TaskIntent` / `PlacementReconciler`; `tools/`
is not a package, so it is imported by path.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from perception_framework.contracts.capability import CapabilityState

FRAMEWORK_DIR = Path(__file__).resolve().parents[1]
SERVE_PY = FRAMEWORK_DIR / "tools" / "status_ui" / "serve.py"
EXAMPLE_CONFIG = FRAMEWORK_DIR / "config" / "status_ui.example.json"


def _import_serve():
    name = "status_ui_serve_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SERVE_PY)
    module = importlib.util.module_from_spec(spec)
    # `from __future__ import annotations` + dataclass needs the module in
    # sys.modules before exec, otherwise field-type resolution fails.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def serve():
    return _import_serve()


@pytest.fixture
def service(serve):
    return serve.StatusService(serve.load_ui_config(EXAMPLE_CONFIG), control_mode="local")


def rows_by_kind(result: dict) -> dict[str, dict]:
    return {row["kind"]: row for row in result["rows"]}


# --- (a) config -------------------------------------------------------------


def test_load_ui_config_builds_nodes_and_specs(serve):
    config = serve.load_ui_config(EXAMPLE_CONFIG)

    assert [n.node_id for n in config.nodes] == ["go1-onboard", "pi6", "pi4", "edge-dev", "edge-gpu", "server-1"]
    assert config.node("pi6").tags == ("compute.cpu", "tier.fixed_camera", "sensor.camera.imx708")
    assert config.node("pi6").role == "fixed_camera"
    assert config.node("pi6").budget.compute_units == 4.0
    assert [n.role for n in config.nodes] == ["ondevice", "fixed_camera", "fixed_camera", "edge", "edge", "server"]
    assert config.roles() == ["ondevice", "fixed_camera", "edge", "server"]
    assert config.providers_manifest == (EXAMPLE_CONFIG.parent / "providers.status_ui.example.json").resolve()
    assert config.labels_path == (EXAMPLE_CONFIG.parent / "status_ui.labels.json").resolve()
    assert config.profile.domain_id == "door-demo"
    assert config.profile.closed_network is False

    functions = {f.function_id: f for f in config.functions}
    assert set(functions) == {"local_safety", "door_detection", "go_to_door", "risk_analysis"}
    assert functions["go_to_door"].required_capabilities[-1] == "control.locomotion"
    assert functions["risk_analysis"].required_capabilities == ("risk.event_input",)
    intent = functions["door_detection"].intent()
    assert intent.required_capabilities == ("media.video_input", "perception.detect", "perception.classify")

    specs = {s.kind: s for s in config.specs}
    assert specs["media.video_input"].is_core is True
    assert specs["perception.detect"].requirement.required == ("media.video_input",)
    assert specs["perception.segment"].degrade_rank == 4
    assert specs["perception.segment"].requirement.optional == ("perception.depth",)
    with pytest.raises(serve.UiConfigError):
        config.node("nope")


def test_unknown_deployment_key_is_rejected_like_profile_loader(serve, tmp_path):
    raw = json.loads(EXAMPLE_CONFIG.read_text(encoding="utf-8"))
    raw["deployment"]["typo_key"] = 1
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        serve.load_ui_config(path)


# --- (b) derived grade ------------------------------------------------------


@pytest.mark.parametrize(
    "state, reason, grade",
    [
        (CapabilityState.ACTIVE, "selected", "READY"),
        ("ACTIVE", "selected", "READY"),
        (CapabilityState.DEGRADED, "selected", "DEGRADED"),
        (CapabilityState.DISABLED, "missing_required:media.video_input", "MISSING"),
        (CapabilityState.DISABLED, "no_provider_registered", "MISSING"),
        (CapabilityState.DISABLED, "runtime_instance_unhealthy_or_expired", "STALE"),
        (CapabilityState.DISABLED, "input_too_stale", "STALE"),
        (CapabilityState.DISABLED, "deadline_exceeded", "STALE"),
        (CapabilityState.DISABLED, "no_compatible_provider_within_budget", "BLOCKED"),
        (CapabilityState.DISABLED, "core_capability_unplaced", "BLOCKED"),
        (CapabilityState.DISABLED, "external_connection_required_in_closed_network", "BLOCKED"),
        (CapabilityState.DISABLED, "", "BLOCKED"),
    ],
)
def test_derive_grade_mapping(serve, state, reason, grade):
    assert serve.derive_grade(state, reason) == grade


def test_grade_is_derived_only_not_a_framework_state(serve, service):
    """§3-2: the framework has three states; the grade is display-only."""
    assert "derived for display only" in serve.derive_grade.__doc__
    assert set(service.vocabulary()["capability_states"]) == {"ACTIVE", "DEGRADED", "DISABLED"}
    assert set(serve.GRADE_DESCRIPTIONS) == {"READY", "DEGRADED", "MISSING", "STALE", "BLOCKED"}


# --- (c) example resolves as documented -------------------------------------


def test_edge_gpu_is_fully_active(service):
    result = service.resolve("edge-gpu")
    assert result["rows"], "no rows"
    assert result["role"] == "edge"
    # control.locomotion is served by the on-device tier only (go1-adapter
    # requires tier.ondevice); every other kind is ACTIVE on the GPU edge.
    perception_rows = [row for row in result["rows"] if row["kind"] != "control.locomotion"]
    assert {row["state"] for row in perception_rows} == {"ACTIVE"}
    assert {row["derived_grade"] for row in perception_rows} == {"READY"}
    rows = rows_by_kind(result)
    assert rows["control.locomotion"]["state"] == "DISABLED"
    assert [a["reason"] for a in rows["control.locomotion"]["alternatives"]] == ["required_hw_tag_missing:tier.ondevice"]
    assert rows["perception.classify"]["provider_id"] == "clip-dictionary-cuda"
    assert rows["perception.classify"]["priority"] == 10
    assert rows["perception.classify"]["required_hw_tags"] == ["compute.gpu"]
    assert rows["perception.classify"]["node_selector"] == {"aif.io/compute.gpu": "true"}
    # the CPU variant is reported as a runner-up, never silently dropped (P1)
    assert [a["reason_token"] for a in rows["perception.classify"]["alternatives"]] == ["compatible"]


def test_pi6_sheds_optionals_and_reports_missing_gpu_tag(service, serve):
    from perception_framework.contracts.data_dictionary import STATE_CHANGE_REASONS

    rows = rows_by_kind(service.resolve("pi6"))
    assert rows["media.video_input"]["state"] == "ACTIVE" and rows["media.video_input"]["is_core"]
    assert rows["perception.detect"]["state"] == "ACTIVE"
    assert rows["control.locomotion"]["state"] == "DISABLED"
    assert rows["control.locomotion"]["alternatives"][0]["reason"] == "required_hw_tag_missing:tier.ondevice"

    classify_alts = {a["provider_id"]: a for a in rows["perception.classify"]["alternatives"]}
    assert classify_alts["clip-dictionary-cuda"]["reason"] == "required_hw_tag_missing:compute.gpu"
    assert classify_alts["clip-dictionary-cuda"]["reason_token"] == "required_hw_tag_missing"
    assert classify_alts["clip-dictionary-cuda"]["reason_data"] == "compute.gpu"

    shed = [
        row for row in rows.values()
        if not row["is_core"] and row["state"] == "DISABLED"
        and any(a["reason_token"] == "over_budget" for a in row["alternatives"])
    ]
    assert shed, "expected at least one budget-shed optional kind on pi6"
    for row in shed:
        assert row["reason_token"] == "no_compatible_provider_within_budget"
        assert row["derived_grade"] == "BLOCKED"
        assert row["provider_id"] is None and row["cost"] is None and row["node_selector"] is None

    # every reason the panel shows is inside the controlled vocabulary (P2)
    for row in rows.values():
        assert row["reason_token"] in STATE_CHANGE_REASONS
        for alt in row["alternatives"]:
            assert alt["reason_token"] in STATE_CHANGE_REASONS


def test_resolve_never_mutates_shared_registry(service):
    before = {k: [r.provider_id for r in service.registry.available_providers(k)] for k in service.registry.known_capability_kinds()}
    service.resolve("edge-gpu", exclude_providers=("unidepth", "fastsam"))
    after = {k: [r.provider_id for r in service.registry.available_providers(k)] for k in service.registry.known_capability_kinds()}
    assert before == after


# --- (d) what-if ------------------------------------------------------------


def test_whatif_diff_flips_classify_when_gpu_tag_added(service):
    result = service.whatif("pi6", tags=[*service.config.node("pi6").tags, "compute.gpu"], budget={"compute_units": 8.0})

    diff = {d["kind"]: d for d in result["diff"]}
    classify = diff["perception.classify"]
    assert classify["changed"] is True
    assert (classify["before_state"], classify["after_state"]) == ("DISABLED", "ACTIVE")
    assert (classify["before_provider"], classify["after_provider"]) == (None, "clip-dictionary-cuda")
    assert diff["media.video_input"]["changed"] is False
    assert result["baseline"]["tags"] == ["compute.cpu", "sensor.camera.imx708", "tier.fixed_camera"]  # sorted
    assert result["override"]["budget"]["compute_units"] == 8.0
    assert result["override"]["budget"]["memory_mb"] == 7900.0  # partial budget keeps the node default


def test_whatif_exclusion_shows_degraded_and_core_unplaced(service):
    degraded = rows_by_kind(service.whatif("edge-gpu", exclude_providers=("unidepth",))["override"])
    assert degraded["perception.depth"]["reason"] == "no_provider_registered"
    assert degraded["perception.depth"]["derived_grade"] == "MISSING"
    assert degraded["perception.segment"]["state"] == "DEGRADED"
    assert degraded["perception.segment"]["derived_grade"] == "DEGRADED"

    # A core kind that cannot be placed reserves the headroom: every optional
    # kind after it is withheld with `core_capability_unplaced` *before* its
    # own requirement is even evaluated (AI-B-06: 핵심 기능은 유지).
    unplaced = rows_by_kind(service.whatif("edge-gpu", exclude_providers=("rpn-ondevice",))["override"])
    assert unplaced["perception.detect"]["state"] == "DISABLED"
    assert unplaced["perception.detect"]["reason"] == "no_provider_registered"
    assert unplaced["perception.detect"]["derived_grade"] == "MISSING"
    assert unplaced["perception.classify"]["reason"] == "core_capability_unplaced"
    assert unplaced["perception.depth"]["reason"] == "core_capability_unplaced"
    assert unplaced["perception.depth"]["derived_grade"] == "BLOCKED"

    # `missing_required` is visible on a *core* kind whose required dep is gone.
    no_video = rows_by_kind(service.whatif("edge-gpu", exclude_providers=("imx708-libcamera", "imx708-wide-libcamera", "go1-front-camera", "media-path-ingest"))["override"])
    assert no_video["media.video_input"]["reason"] == "no_provider_registered"
    assert no_video["perception.detect"]["reason"] == "missing_required:media.video_input"
    assert no_video["perception.detect"]["reason_data"] == "media.video_input"
    assert no_video["perception.detect"]["derived_grade"] == "MISSING"


# --- (e) placement ----------------------------------------------------------


def test_apply_placement_is_idempotent_and_exclusion_swaps(service):
    first = service.apply_placement("edge-gpu")
    commands = {(a["kind"], a["provider_id"]): a["command"] for a in first}
    assert commands[("perception.classify", "clip-dictionary-cuda")] == "start"
    assert commands[("perception.detect_ovd", "grounding-dino")] == "start"
    assert commands[("perception.detect", "rpn-ondevice")] == "in_process"
    assert all(a["accepted"] for a in first)

    second = service.apply_placement("edge-gpu")
    assert second == []

    third = service.apply_placement("edge-gpu", exclude_providers=("grounding-dino",))
    assert [(a["command"], a["provider_id"]) for a in third] == [
        ("stop", "grounding-dino"),
        ("start", "yolo-world"),
    ]

    state = service.placement_state("edge-gpu")
    bound = {b["kind"]: b for b in state["bound"]}
    assert bound["perception.detect_ovd"]["provider_id"] == "yolo-world"
    assert bound["perception.classify"]["node_selector"] == {"aif.io/compute.gpu": "true"}
    assert bound["perception.classify"]["status"] == "RUNNING"
    assert [e["command"] for e in state["audit_log"]] == ["start", "start", "stop", "start"]
    assert all(e["requested_by"] == "status_ui:edge-gpu" for e in state["audit_log"])

    names = [e["name"] for e in service.recent_events()]
    assert names.count("placement_applied") == len(first) + len(third)

    service.reset()
    assert service.recent_events()[-1]["name"] == "reset"
    assert service.placement_state("edge-gpu")["bound"] == []
    assert service.apply_placement("edge-gpu") == first


def test_k3s_request_falls_back_to_local_when_no_orchestrator(serve, monkeypatch):
    monkeypatch.setattr(serve.K3sControlProvider, "is_available", lambda self: False)
    service = serve.StatusService(serve.load_ui_config(EXAMPLE_CONFIG), control_mode="k3s", namespace="demo")

    assert service.control_info == {
        "requested": "k3s", "active": "local", "reason": "orchestrator_unavailable", "namespace": "demo",
    }
    assert isinstance(service.control, serve.LocalControlSupervisor)
    assert service.recent_events()[0]["name"] == "control_fallback"
    assert service.describe()["control"]["active"] == "local"


# --- (g) function axis ------------------------------------------------------


def functions_by_id(payload: dict) -> dict[str, dict]:
    return {f["function_id"]: f for f in payload["functions"]}


def test_functions_baseline_states_follow_task_intent(service):
    payload = service.functions()
    fns = functions_by_id(payload)

    assert fns["local_safety"]["state"] == "ACTIVE"
    assert fns["door_detection"]["state"] == "ACTIVE" and fns["door_detection"]["derived_grade"] == "READY"
    assert fns["go_to_door"]["state"] == "ACTIVE"
    # locomotion comes from the on-device tier (go1-adapter requires tier.ondevice)
    loco = {row["kind"]: row for row in fns["go_to_door"]["required"]}["control.locomotion"]
    assert loco["missing"] is False
    assert [(s["node_id"], s["role"], s["provider_id"]) for s in loco["served_by"]] == [("go1-onboard", "ondevice", "go1-adapter")]
    # nodes that cannot serve it are explained, never hidden
    assert {w["role"] for w in loco["why"]} == {"fixed_camera", "edge", "server"}
    assert all(w["reason_token"] == "no_compatible_provider_within_budget" for w in loco["why"])

    risk = fns["risk_analysis"]
    assert risk["state"] == "DISABLED" and risk["derived_grade"] == "MISSING"
    assert risk["reason_token"] == "no_provider_registered"
    required = risk["required"][0]
    assert required["kind"] == "risk.event_input" and required["missing"] is True and required["activated"] is False
    assert {s["kind"] for s in risk["supplement"]} == {"risk.event_input"}
    assert [s["role"] for s in risk["supplement"]] == ["ondevice", "fixed_camera", "edge", "server"]
    assert all(s["reason_token"] == "no_provider_registered" for s in risk["supplement"])
    assert risk["resources"] == {"by_role": {}, "by_kind": [], "required_hw_tags": []}

    # every reason token on the function axis is inside the controlled vocabulary (P2)
    from perception_framework.contracts.data_dictionary import STATE_CHANGE_REASONS

    for fn in payload["functions"]:
        for row in fn["required"] + fn["optional"]:
            for why in row["why"]:
                assert why["reason_token"] is None or why["reason_token"] in STATE_CHANGE_REASONS
        for s in fn["supplement"]:
            assert s["reason_token"] in STATE_CHANGE_REASONS


def test_functions_resources_by_role_and_choice_rule(service):
    fns = functions_by_id(service.functions())
    door = fns["door_detection"]
    by_role = door["resources"]["by_role"]
    assert set(by_role) == {"ondevice", "edge"}
    for role, cost in by_role.items():
        assert cost["compute_units"] > 0 and cost["memory_mb"] > 0, role
    # classify is charged to clip-dictionary-cuda (priority 10 beats 50) → GPU tag required
    assert "compute.gpu" in door["resources"]["required_hw_tags"]
    by_kind = {k["kind"]: k for k in door["resources"]["by_kind"]}
    assert by_kind["perception.classify"]["provider_id"] == "clip-dictionary-cuda"
    assert by_kind["perception.classify"]["role"] == "edge"
    # priorities tie for video_input → lowest cost → config order: go1-onboard is charged
    assert by_kind["media.video_input"]["node_id"] == "go1-onboard"
    assert by_kind["perception.detect_ovd"]["required"] is False
    # go_to_door adds the on-device locomotion adapter to the on-device bill
    go = fns["go_to_door"]
    assert go["resources"]["by_role"]["ondevice"]["compute_units"] == pytest.approx(0.5 + 2.0 + 0.5)
    assert set(go["resources"]["required_hw_tags"]) == {"compute.gpu", "tier.ondevice", "sensor.camera.go1_front"}
    # the rule is documented where it is implemented
    assert "lowest" in service.fleet.__doc__ and "priority" in service.functions.__doc__


def test_functions_whatif_without_gpu_falls_back_to_cpu_classifier(service):
    no_gpu = {
        node_id: {"tags": [tag for tag in service.config.node(node_id).tags if tag != "compute.gpu"]}
        for node_id in ("edge-dev", "edge-gpu", "server-1")
    }
    result = service.whatif_functions(no_gpu)
    diff = {d["function_id"]: d for d in result["diff"]}
    assert diff["go_to_door"] == {"function_id": "go_to_door", "before_state": "ACTIVE", "after_state": "ACTIVE", "changed": False}
    after = functions_by_id(result["after"])
    classify = {row["kind"]: row for row in after["go_to_door"]["required"]}["perception.classify"]
    assert classify["served_by"] and all(s["provider_id"] == "clip-dictionary" for s in classify["served_by"])
    assert "compute.gpu" not in after["go_to_door"]["resources"]["required_hw_tags"]
    assert result["after"]["overrides"]["edge-gpu"]["tags"] == no_gpu["edge-gpu"]["tags"]
    assert result["after"]["overrides"]["pi6"] == {}


def test_functions_whatif_excluding_depth_disables_go_to_door_only(serve, service):
    result = service.whatif_functions({"*": {"exclude_providers": ["unidepth"]}})
    diff = {d["function_id"]: d for d in result["diff"]}
    assert (diff["go_to_door"]["before_state"], diff["go_to_door"]["after_state"]) == ("ACTIVE", "DISABLED")
    assert diff["door_detection"]["changed"] is False and diff["door_detection"]["after_state"] == "ACTIVE"
    assert (diff["local_safety"]["before_state"], diff["local_safety"]["after_state"]) == ("ACTIVE", "DEGRADED")  # optional depth gone

    go = functions_by_id(result["after"])["go_to_door"]
    assert go["derived_grade"] == "MISSING" and go["reason_token"] == "no_provider_registered"
    assert [(s["kind"], s["role"]) for s in go["supplement"]] == [
        ("perception.depth", "ondevice"), ("perception.depth", "fixed_camera"), ("perception.depth", "edge"), ("perception.depth", "server"),
    ]
    # per-node exclusion is honoured as well; unknown node ids are rejected
    only_edge = service.whatif_functions({"edge-dev": {"exclude_providers": ["unidepth"]}, "edge-gpu": {"exclude_providers": ["unidepth"]}})
    assert {d["function_id"]: d["after_state"] for d in only_edge["diff"]}["go_to_door"] == "ACTIVE"  # server-1 still serves depth
    with pytest.raises(serve.UiConfigError):
        service.functions({"ghost": {}})


def test_supplement_prefers_best_alternative_reason(service):
    """A missing kind's tier hint names the best candidate's own blocker
    (e.g. required_hw_tag_missing:compute.gpu), not the aggregate
    no_compatible_provider_within_budget."""
    # shrink every node so classify cannot fit anywhere, and strip GPUs so the
    # cuda variant is blocked by a tag rather than by budget
    overrides = {
        node.node_id: {"tags": [t for t in node.tags if t != "compute.gpu"], "budget": {"compute_units": 3.0}}
        for node in service.config.nodes
    }
    fns = functions_by_id(service.functions(overrides))
    door = fns["door_detection"]
    assert door["state"] == "DISABLED"
    classify_supp = [s for s in door["supplement"] if s["kind"] == "perception.classify"]
    assert [s["role"] for s in classify_supp] == ["ondevice", "fixed_camera", "edge", "server"]
    for s in classify_supp:
        assert s["reason"] == "required_hw_tag_missing:compute.gpu"
        assert s["provider_id"] == "clip-dictionary-cuda"
    assert door["derived_grade"] == "BLOCKED"


# --- (h) labels ------------------------------------------------------------


def test_labels_cover_every_id_in_both_languages(service):
    labels = service.labels()
    assert labels["languages"] == ["ko", "en"]
    assert service.labels_missing() == []

    ids = service.label_ids()
    assert "risk.event_input" in ids["capability_kinds"] and "control.locomotion" in ids["capability_kinds"]
    assert ids["functions"] == ["local_safety", "door_detection", "go_to_door", "risk_analysis"]
    assert ids["states"] == ["ACTIVE", "DEGRADED", "DISABLED"]
    assert set(ids["grades"]) == {"READY", "DEGRADED", "MISSING", "STALE", "BLOCKED"}
    from perception_framework.contracts.data_dictionary import STATE_CHANGE_REASONS

    assert ids["reasons"] == list(STATE_CHANGE_REASONS)
    assert ids["roles"] == ["ondevice", "fixed_camera", "edge", "server"]
    assert ids["commands"] == ["start", "stop", "in_process"]
    for section, section_ids in ids.items():
        for ident in section_ids:
            entry = labels[section][ident]
            if section == "functions":
                assert entry["label"]["ko"] and entry["label"]["en"], ident
                assert entry["description"]["ko"] and entry["description"]["en"], ident
            else:
                assert entry["ko"] and entry["en"], f"{section}.{ident}"
    for key, entry in labels["ui"].items():
        assert entry["ko"] and entry["en"], f"ui.{key}"
    assert labels["states"] == {
        "ACTIVE": {"ko": "가능", "en": "Available"},
        "DEGRADED": {"ko": "일부만 가능", "en": "Partial"},
        "DISABLED": {"ko": "불가", "en": "Unavailable"},
    }


def test_labels_missing_reports_gaps_and_missing_file_is_not_fatal(serve, tmp_path):
    raw = json.loads(EXAMPLE_CONFIG.read_text(encoding="utf-8"))
    raw["providers_manifest"] = str(EXAMPLE_CONFIG.parent / "providers.status_ui.example.json")
    labels = json.loads((EXAMPLE_CONFIG.parent / "status_ui.labels.json").read_text(encoding="utf-8"))
    del labels["roles"]["server"]["en"]
    del labels["functions"]["go_to_door"]["description"]
    labels["ui"]["title"] = {"ko": "제목"}
    (tmp_path / "labels.json").write_text(json.dumps(labels, ensure_ascii=False), encoding="utf-8")
    raw["labels"] = "labels.json"
    (tmp_path / "ui.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    service = serve.StatusService(serve.load_ui_config(tmp_path / "ui.json"), control_mode="local")
    assert service.labels_missing() == [
        "functions.go_to_door.description.ko",
        "functions.go_to_door.description.en",
        "roles.server.en",
        "ui.title.en",
    ]

    raw["labels"] = "nope.json"
    (tmp_path / "ui2.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    service = serve.StatusService(serve.load_ui_config(tmp_path / "ui2.json"), control_mode="local")
    assert service.labels()["ui"] == {} and service.labels_missing() == []  # ids fall back to raw ids in the page


# --- (f) HTTP smoke ---------------------------------------------------------


@pytest.fixture
def running_server(serve, service):
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


def test_http_smoke(running_server):
    base = running_server
    assert base.startswith("http://127.0.0.1:")

    status, headers, config = _get(base + "api/config")
    assert status == 200
    assert headers["Cache-Control"] == "no-store"
    assert headers["Content-Type"].startswith("application/json")
    assert {"nodes", "capabilities", "providers", "all_tags", "control", "deployment", "roles", "functions"} <= set(config)
    assert "compute.gpu" in config["all_tags"]
    assert config["roles"] == ["ondevice", "fixed_camera", "edge", "server"]
    assert config["labels_missing"] == []

    status, _, labels = _get(base + "api/labels")
    assert status == 200
    assert labels["languages"] == ["ko", "en"]
    assert labels["states"]["ACTIVE"] == {"ko": "가능", "en": "Available"}
    assert labels["reasons"]["required_hw_tag_missing"]["en"] == "Required hardware tag missing"

    status, _, functions = _get(base + "api/functions")
    assert status == 200
    by_id = {f["function_id"]: f for f in functions["functions"]}
    assert by_id["door_detection"]["state"] == "ACTIVE"
    assert by_id["risk_analysis"]["state"] == "DISABLED"
    assert {"required", "optional", "resources", "supplement", "derived_grade"} <= set(by_id["go_to_door"])
    # language-neutral: no label text anywhere in the payload, ids only
    assert "가능" not in json.dumps(functions, ensure_ascii=False)

    status, _, fleet = _get(base + "api/fleet")
    assert status == 200 and [n["node_id"] for n in fleet["nodes"]] == ["go1-onboard", "pi6", "pi4", "edge-dev", "edge-gpu", "server-1"]
    assert fleet["served"]["control.locomotion"][0]["role"] == "ondevice"

    status, fn_whatif = _post(base + "api/functions/whatif", {"overrides": {"*": {"exclude_providers": ["unidepth"]}}})
    assert status == 200
    fn_diff = {d["function_id"]: d for d in fn_whatif["diff"]}
    assert fn_diff["go_to_door"] == {"function_id": "go_to_door", "before_state": "ACTIVE", "after_state": "DISABLED", "changed": True}
    with pytest.raises(urllib.error.HTTPError) as bad_override:
        _post(base + "api/functions/whatif", {"overrides": {"ghost": {"tags": []}}})
    assert bad_override.value.code == 404

    status, _, resolved = _get(base + "api/resolve?node_id=pi6")
    assert status == 200
    assert resolved["node_id"] == "pi6"
    assert {"kind", "state", "derived_grade", "provider_id", "reason", "reason_token", "alternatives", "cost", "node_selector"} <= set(resolved["rows"][0])

    status, _, vocab = _get(base + "api/vocabulary")
    assert status == 200 and "state_change_reasons" in vocab

    status, whatif = _post(base + "api/whatif", {"node_id": "pi6", "tags": ["compute.cpu", "compute.gpu"], "budget": {"compute_units": 8}})
    assert status == 200 and any(d["changed"] for d in whatif["diff"])

    status, placed = _post(base + "api/placement", {"node_id": "edge-gpu"})
    assert status == 200 and placed["actions"] and "bound" in placed["state"]

    status, _, events = _get(base + "api/events")
    assert status == 200 and events["events"]

    with urllib.request.urlopen(base, timeout=5) as response:
        assert response.status == 200
        html = response.read().decode("utf-8")
    assert 'id="lang-toggle"' in html and "KO" in html and "EN" in html  # instant ko/en switch
    assert 'data-tab="functions"' in html and 'data-tab="tiers"' in html and 'data-tab="developer"' in html
    assert "/api/labels" in html and "/api/functions/whatif" in html
    assert "http://" not in html.replace(base, "") and "https://" not in html  # no external resource
    assert "<link" not in html and "src=" not in html  # everything inline

    with pytest.raises(urllib.error.HTTPError) as unknown:
        _get(base + "api/nope")
    assert unknown.value.code == 404
    with pytest.raises(urllib.error.HTTPError) as bad_node:
        _get(base + "api/resolve?node_id=ghost")
    assert bad_node.value.code == 404

    status, reset = _post(base + "api/reset", {})
    assert status == 200 and reset["ok"] is True
