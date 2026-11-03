"""implements: AI-C-18, AI-C-10, AI-C-05, AI-B-01, AI-B-04, AI-C-15 (hardware contract data)
tests: the hardware/mission mapping document (장비 기능·임무 매핑 자료(비공개) →
장비 capability 계약 노트(비공개)) turned into data —
`config/providers.hardware.example.json` + `config/status_ui.hardware.example.json`
+ labels — reproduces the document's own §4 verdicts through the unchanged
`tools/status_ui/serve.py` resolution path: (1) M1 is served by the
fixed-camera tier only, (2) M7 needs EP's gripper and says so when the tag is
gone, (3) M5/M6 fail on the document's own gap — the drone carries no camera —
with `required_hw_tag_missing:sensor.camera.imx708_wide` on the uav tier,
(4) M11 fails because no node has a NoIR camera, (5) M4 is legged-only,
(6) every C-xx alias maps to a labelled kind and every manifest kind is
labelled, (7) the role vocabulary is exactly fixed_camera/ugv/uav/edge/server,
(8) the hardware config is a superset of the door-demo example and the
manifest's multi-registration ("A or B" requirements) loads as declared.

원문 §1: "장비끼리 비교가 되려면 기능 이름부터 같아야 한다" — the comparison
here is done by the registry/selector, never by device name (원칙 #1, AI-C-18:
"특정 장치·모델 이름이 아니라 필요한 capability와 조건을 기준으로").
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

from mission_runtime.registry.manifest import load_provider_manifest

FRAMEWORK_DIR = Path(__file__).resolve().parents[1]
SERVE_PY = FRAMEWORK_DIR / "tools" / "status_ui" / "serve.py"
CONFIG_DIR = FRAMEWORK_DIR / "config"
HARDWARE_CONFIG = CONFIG_DIR / "status_ui.hardware.example.json"
HARDWARE_MANIFEST = CONFIG_DIR / "providers.hardware.example.json"
EXAMPLE_CONFIG = CONFIG_DIR / "status_ui.example.json"
LABELS = CONFIG_DIR / "status_ui.labels.json"

ROLE_VOCABULARY = {"fixed_camera", "ugv", "uav", "edge", "server"}

# 원문 §1 기능 분류 → kind. C-50/60/61/70/71 are deliberately absent: they are
# execution tier / transport / control path / endurance, i.e. node tags.
EXPECTED_ALIASES = {
    "observation.fixed": "C-01",
    "observation.panoramic": "C-02",
    "observation.mobile": "C-03",
    "observation.aerial": "C-04",
    "perception.depth": "C-05",
    "observation.low_light": "C-06",
    "locomotion.ground": "C-10",
    "locomotion.rough_terrain": "C-11",
    "locomotion.holonomic": "C-12",
    "locomotion.aerial": "C-13",
    "navigation.autonomous_route": "C-14",
    "pose.self_estimate": "C-20",
    "pose.gps": "C-21",
    "manipulation.grasp": "C-30",
    "gaze.control": "C-31",
    "signal.audio_visual": "C-40",
    "perception.detect": "C-51",
    "safety.failsafe_return": "C-80",
}
NOT_KINDS = {"C-50", "C-60", "C-61", "C-70", "C-71"}
TAG_ONLY_CONCEPTS = {"tier.ugv", "tier.uav", "tier.fixed_camera", "media.ingest", "power.external", "endurance.long"}


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


@pytest.fixture(scope="module")
def config(serve):
    return serve.load_ui_config(HARDWARE_CONFIG)


@pytest.fixture(scope="module")
def service(serve, config):
    return serve.StatusService(config, control_mode="local")


@pytest.fixture(scope="module")
def functions(service):
    payload = service.functions()
    return {f["function_id"]: f for f in payload["functions"]}


@pytest.fixture(scope="module")
def labels():
    return json.loads(LABELS.read_text(encoding="utf-8"))


def required_row(fn: dict, kind: str) -> dict:
    return {row["kind"]: row for row in fn["required"]}[kind]


def supplement_for(fn: dict, kind: str, role: str) -> dict:
    return next(s for s in fn["supplement"] if s["kind"] == kind and s["role"] == role)


# --- (1) M1 상시 감시: fixed-camera tier only -------------------------------


def test_m1_is_served_by_the_fixed_camera_tier_only(functions):
    m1 = functions["m1_continuous_surveillance"]
    fixed = required_row(m1, "observation.fixed")
    assert fixed["missing"] is False
    assert {s["role"] for s in fixed["served_by"]} == {"fixed_camera"}
    # 원문 §4 M1 단독 수행: Pi Cam 3, Insta360 Pro 2 — the 360 camera counts as
    # a fixed viewpoint too (multi-registration expresses "C-01 또는 C-02").
    assert {s["node_id"] for s in fixed["served_by"]} == {"pi6", "pi4", "insta360-pro2"}
    # Every required kind is served, so the mission is available; it is
    # DEGRADED rather than ACTIVE only because the optional NoIR observation
    # (C-06 ◐) has no node yet — optional 결손은 DEGRADED까지만 (AI-C-05).
    assert m1["state"] == "DEGRADED"
    low_light = {row["kind"]: row for row in m1["optional"]}["observation.low_light"]
    assert low_light["missing"] is True


# --- (2) M7 물체 회수·조작: EP's gripper ------------------------------------


def test_m7_needs_ep_gripper_and_says_so_without_it(config, service, functions):
    m7 = functions["m7_object_retrieval"]
    assert m7["state"] == "ACTIVE"
    grasp = required_row(m7, "manipulation.grasp")
    assert [(s["node_id"], s["role"], s["provider_id"]) for s in grasp["served_by"]] == [
        ("ep-onboard", "ugv", "ep-arm-gripper")
    ]
    holonomic = required_row(m7, "locomotion.holonomic")
    assert [s["node_id"] for s in holonomic["served_by"]] == ["ep-onboard"]  # 원문: 평지 한정, EP만

    ep_tags = [t for t in config.node("ep-onboard").tags if t != "actuator.gripper"]
    after = service.functions({"ep-onboard": {"tags": ep_tags}})
    m7_after = {f["function_id"]: f for f in after["functions"]}["m7_object_retrieval"]
    assert m7_after["state"] == "DISABLED"
    assert m7_after["reason_token"] == "required_hw_tag_missing"
    ugv = supplement_for(m7_after, "manipulation.grasp", "ugv")
    assert ugv["reason"] == "required_hw_tag_missing:actuator.gripper"
    assert ugv["provider_id"] == "ep-arm-gripper"

    diff = {d["function_id"]: d for d in service.whatif_functions({"ep-onboard": {"tags": ep_tags}})["diff"]}
    assert diff["m7_object_retrieval"] == {
        "function_id": "m7_object_retrieval", "before_state": "ACTIVE", "after_state": "DISABLED", "changed": True,
    }
    # only the missions that need the gripper move; the rest are untouched (AI-C-05)
    assert {fid for fid, d in diff.items() if d["changed"]} == {"m7_object_retrieval"}


# --- (3) M5/M6: the drone has no camera --------------------------------------


@pytest.mark.parametrize("function_id", ["m5_wide_area_search", "m6_advance_recon"])
def test_m5_m6_fail_on_the_documented_drone_camera_gap(functions, function_id):
    fn = functions[function_id]
    assert fn["state"] == "DISABLED" and fn["reason_token"] == "required_hw_tag_missing"
    # flight itself is fine — the only missing required kind is the aerial view
    assert required_row(fn, "locomotion.aerial")["served_by"][0]["node_id"] == "x500-companion"
    missing = [row["kind"] for row in fn["required"] if row["missing"]]
    assert missing == ["observation.aerial"]
    uav = supplement_for(fn, "observation.aerial", "uav")
    # 원문 §6: "현재 X500 구성에 카메라가 없어 C-04가 비어 있음. 컴패니언 파이에
    # Camera Module 3 Wide를 다는 게 가장 빠름" — the supplement names exactly
    # that tag, and nothing else, on the uav tier.
    assert uav["reason"] == "required_hw_tag_missing:sensor.camera.imx708_wide"
    assert uav["provider_id"] == "x500-companion-camera" and uav["node_id"] == "x500-companion"


def test_m6_failsafe_is_served_by_the_flight_controller(functions):
    m6 = functions["m6_advance_recon"]
    failsafe = required_row(m6, "safety.failsafe_return")
    assert [(s["node_id"], s["provider_id"]) for s in failsafe["served_by"]] == [("x500-companion", "px4-flight")]


# --- (4) M11 야간 감시: no NoIR camera anywhere --------------------------------


def test_m11_fails_because_no_node_has_a_noir_camera(config, functions):
    assert not any("sensor.camera.noir" in node.tags for node in config.nodes)
    m11 = functions["m11_night_surveillance"]
    assert m11["state"] == "DISABLED" and m11["reason_token"] == "required_hw_tag_missing"
    assert required_row(m11, "observation.low_light")["missing"] is True
    for s in m11["supplement"]:
        assert s["reason"] == "required_hw_tag_missing:sensor.camera.noir", s


# --- (5) M4 비정형 지형: legged only -----------------------------------------


def test_m4_rough_terrain_is_served_by_go1_only(service, functions):
    m4 = functions["m4_rough_terrain_entry"]
    assert m4["state"] == "ACTIVE"
    rough = required_row(m4, "locomotion.rough_terrain")
    assert [(s["node_id"], s["role"], s["provider_id"]) for s in rough["served_by"]] == [
        ("go1-onboard", "ugv", "go1-adapter")
    ]
    # EP is the same ugv tier but wheeled: the legged adapter is rejected on
    # a tag, not on the robot's name.
    ep_rows = {row["kind"]: row for row in service.resolve("ep-onboard")["rows"]}
    alternatives = {a["provider_id"]: a["reason"] for a in ep_rows["locomotion.rough_terrain"]["alternatives"]}
    assert alternatives["go1-adapter"] == "required_hw_tag_missing:locomotion.legged"
    # and flat-ground locomotion is shared by both ground robots (원문 C-10 ● Go1, ● EP)
    ground = required_row(functions["m2_close_inspection"], "locomotion.ground")
    assert {s["node_id"] for s in ground["served_by"]} == {"go1-onboard", "ep-onboard"}


# --- (6) aliases and labels ---------------------------------------------------


def test_every_c_code_alias_maps_to_a_labelled_kind(labels, service):
    aliases = labels["aliases"]["capability_kinds"]
    assert aliases == EXPECTED_ALIASES
    codes = list(aliases.values())
    assert len(set(codes)) == len(codes)
    assert all(re.fullmatch(r"C-\d\d", code) for code in codes)
    assert not (set(codes) & NOT_KINDS)  # tier/transport/control-path/endurance are tags, not kinds
    for kind in aliases:
        entry = labels["capability_kinds"][kind]
        assert entry["ko"] and entry["en"], kind

    manifest = load_provider_manifest(HARDWARE_MANIFEST)
    manifest_kinds = {reg.capability_kind for reg in manifest.registrations}
    for kind in manifest_kinds:
        entry = labels["capability_kinds"][kind]
        assert entry["ko"] and entry["en"], kind
    # every hardware-vocabulary kind the manifest or config uses carries its C code
    hardware_prefixes = ("observation.", "locomotion.", "navigation.", "pose.", "manipulation.", "gaze.", "signal.", "safety.failsafe")
    for kind in manifest_kinds | set(service.config.profile.active_capability_kinds):
        if kind.startswith(hardware_prefixes):
            assert kind in aliases, kind
    assert service.labels_missing() == []
    ids = service.label_ids()
    assert ids["roles"] == ["fixed_camera", "ugv", "uav", "edge", "server"]
    for fid in ids["functions"]:
        assert labels["functions"][fid]["label"]["ko"] and labels["functions"][fid]["description"]["en"], fid


def test_tag_only_concepts_are_node_tags_not_kinds(config, service):
    all_kinds = set(service.config.profile.active_capability_kinds) | {
        reg.capability_kind for reg in service.manifest.registrations
    }
    assert not any(kind.startswith(("tier.", "media.ingest", "power.", "endurance.")) for kind in all_kinds)
    node_tags = {tag for node in config.nodes for tag in node.tags}
    assert TAG_ONLY_CONCEPTS <= node_tags


# --- (7) role vocabulary --------------------------------------------------------


@pytest.mark.parametrize(
    "config_path",
    [
        HARDWARE_CONFIG,
        EXAMPLE_CONFIG,
        CONFIG_DIR / "status_ui.ondevice.example.json",
        CONFIG_DIR / "status_ui.devices.example.json",
    ],
    ids=lambda p: p.name,
)
def test_roles_use_the_2026_09_28_vocabulary(serve, config_path, labels):
    cfg = serve.load_ui_config(config_path)
    assert set(cfg.roles()) <= ROLE_VOCABULARY, cfg.roles()
    assert set(labels["roles"]) == ROLE_VOCABULARY
    assert "ondevice" not in labels["roles"]  # renamed to ugv; residencies.ondevice (말단 상주) is a different axis
    assert labels["residencies"]["ondevice"]["ko"]


def test_hardware_nodes_have_their_declared_roles_and_tier_tags(config):
    roles = {node.node_id: node.role for node in config.nodes}
    assert roles == {
        "pi6": "fixed_camera", "pi4": "fixed_camera", "insta360-pro2": "fixed_camera",
        "go1-onboard": "ugv", "ep-onboard": "ugv", "x500-companion": "uav",
        "edge-dev": "edge", "edge-gpu": "edge", "server-1": "server",
    }
    for node in config.nodes:
        assert f"tier.{node.role}" in node.tags, node.node_id
    # Go1 (legged) and EP (wheeled) are the same tier; the difference is a tag
    assert "locomotion.legged" in config.node("go1-onboard").tags
    assert "locomotion.wheeled" in config.node("ep-onboard").tags
    # 원문 [확인] 항목은 확정값이 아니다 — one flag, no new status vocabulary
    raw = json.loads(HARDWARE_CONFIG.read_text(encoding="utf-8"))
    verified = {n["node_id"]: n.get("verified") for n in raw["nodes"]}
    assert {k for k, v in verified.items() if v is False} == {"insta360-pro2", "go1-onboard", "ep-onboard", "x500-companion"}
    assert all(v is None for k, v in verified.items() if k in ("pi6", "pi4", "edge-dev", "edge-gpu", "server-1"))


# --- (8) superset of the door-demo example + manifest shape -----------------------


def test_hardware_config_is_a_superset_of_the_example(serve, config):
    example = serve.load_ui_config(EXAMPLE_CONFIG)
    assert {f.function_id for f in example.functions} <= {f.function_id for f in config.functions}
    assert {n.node_id for n in example.nodes} <= {n.node_id for n in config.nodes}
    assert set(example.profile.active_capability_kinds) <= set(config.profile.active_capability_kinds)
    mission_ids = [f.function_id for f in config.functions if f.function_id.startswith("m")]
    assert [m.split("_", 1)[0] for m in mission_ids] == [f"m{i}" for i in range(1, 12)]  # 원문 §4 M1~M11, in order


def test_manifest_multi_registration_expresses_a_or_b_requirements():
    manifest = load_provider_manifest(HARDWARE_MANIFEST)
    kinds_of: dict[str, set[str]] = {}
    for reg in manifest.registrations:
        kinds_of.setdefault(reg.provider_id, set()).add(reg.capability_kind)
    # M1: C-01 또는 C-02 — the panoramic camera is also a fixed viewpoint
    assert kinds_of["insta360-live-ingest"] == {"observation.panoramic", "observation.fixed", "media.video_input"}
    # M10: C-03 또는 C-04 — the aerial camera is also a moving one
    assert kinds_of["x500-companion-camera"] == {"observation.aerial", "observation.mobile", "media.video_input"}
    # every observation.* camera also feeds media.video_input; every ground
    # locomotion provider also serves control.locomotion (existing functions keep working)
    for pid, kinds in kinds_of.items():
        if any(k.startswith("observation.") for k in kinds) and pid != "imx708-noir-libcamera":
            assert "media.video_input" in kinds, pid
        if "locomotion.ground" in kinds:
            assert "control.locomotion" in kinds, pid
    # C-51 내장 인식 is just a low-priority perception.detect provider
    builtin = next(r for r in manifest.registrations if r.provider_id == "ep-builtin-vision")
    assert builtin.capability_kind == "perception.detect" and builtin.compatibility.priority == 90
    # go1-adapter keeps its deployment section, shared by its three kinds
    assert set(manifest.deployment_params) >= {"go1-adapter", "grounding-dino", "yolo-world", "clip-dictionary-cuda"}
    assert kinds_of["go1-adapter"] == {"locomotion.ground", "locomotion.rough_terrain", "control.locomotion"}
    # the ◐ options require a tag the example node does not have — that is the honest state
    raw = json.loads(HARDWARE_MANIFEST.read_text(encoding="utf-8"))
    by_id = {e["provider_id"]: e for e in raw["providers"]}
    assert by_id["ep-tof-depth"]["compatibility"]["required_hw_tags"] == ["sensor.tof"]
    assert by_id["imx708-noir-libcamera"]["compatibility"]["required_hw_tags"] == ["sensor.camera.noir"]
    assert by_id["insta360-stereo-depth"]["compatibility"]["required_hw_tags"] == ["sensor.camera.360_stereo"]
    hardware_ids = {pid for pid in by_id if pid not in (
        "rpn-ondevice", "unidepth", "grounding-dino", "clip-dictionary", "clip-dictionary-cuda",
        "yolo-world", "fastsam", "media-path-ingest",
    )}
    assert all(by_id[pid].get("verified") is False for pid in hardware_ids), "hardware costs are unmeasured placeholders"


def test_ep_builtin_vision_is_the_fallback_detector_on_ep(service):
    rows = {row["kind"]: row for row in service.resolve("ep-onboard")["rows"]}
    detect = rows["perception.detect"]
    assert detect["state"] == "ACTIVE" and detect["provider_id"] == "ep-builtin-vision"
    assert {a["provider_id"]: a["reason"] for a in detect["alternatives"]}["rpn-ondevice"] == "over_budget"
    # the ToF option is missing on this EP — reported, not hidden
    depth_alternatives = {a["provider_id"]: a["reason"] for a in rows["perception.depth"]["alternatives"]}
    assert depth_alternatives["ep-tof-depth"] == "required_hw_tag_missing:sensor.tof"
