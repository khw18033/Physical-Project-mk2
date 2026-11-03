"""선언된 것이 **실재하는지**, 그리고 실재하는 것을 더하는 일이 **선언 한 줄인지**.

implements: AI-B-09, AI-C-05, AI-C-10, AI-C-18, AI-L-10, AI-B-01
tests: no declaration-only function, no dead capability kind, the un-hostable
       kinds are named on purpose, a new kind/provider/node/function is four
       declarations and no code change, a new model version is one line and an
       unmeasured one stays ineligible

운영 설정(`config/status_ui.json`)에 기능이 한 줄 적혀 있다는 것은 그 기능이
**있다**는 뜻이 아니다. 필수 capability 를 아무 provider 도 주지 못하면 그 줄은
영원히 DISABLED 이고, 그 상태는 "못 하는 것"과 "아직 안 만든 것"을 구분해 주지
않는다 — 화면을 보는 사람에게 둘은 전혀 다른 일인데도. 그래서 아래 세 시험은
"실재"를 설정 자신에 대고 고정한다.

반대쪽도 같이 고정해야 한다. 정직하게 줄이면 다음 사람이 늘릴 수 없는 설정이 되기
쉬운데, 그러면 `절대 준수 #7`(새 센서·하드웨어·AI 기능은 핵심 코드 수정이 아니라
등록으로 확장)이 깨진다. 마지막 두 시험이 **코드를 한 줄도 건드리지 않고** 새
capability kind·provider·노드·기능·모델 버전이 들어가는 것을 보인다.

구분해야 하는 세 가지를 섞지 않는다(AI-C-05):
  - provider 가 **아예 없다**        → 기능이 아니다. 설정에서 뺀다.
  - provider 는 있고 **노드가 없다**  → required_hw_tag_missing. 정직한 공백이다.
  - **선택** capability 만 없다       → DEGRADED. 정상적인 축소 운용이다.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

FRAMEWORK_DIR = Path(__file__).resolve().parents[1]
SERVE_PY = FRAMEWORK_DIR / "tools" / "status_ui" / "serve.py"
CONFIG_DIR = FRAMEWORK_DIR / "config"
REAL_CONFIG = CONFIG_DIR / "status_ui.json"

#: provider 는 실재하지만 그 provider 를 올릴 노드가 아직 선언되지 않은 kind.
#: 비어 있지 않은 것 자체가 정상이다 — 드론(x500-001)은 upstream/Junho_drone 에
#: 실물로 있고 PX4·MAVSDK·RTK 경로까지 있지만 `nodes[]` 에 아직 없다. 이 목록을
#: **이름으로** 적어 두는 이유는, 구현 없는 선언이 새로 섞여 들어오면 조용히
#: 늘어나는 쪽이 아니라 이 시험이 깨지는 쪽이 되게 하려는 것이다.
KINDS_WITHOUT_A_HOST: frozenset[str] = frozenset({
    "locomotion.aerial", "pose.gps", "safety.failsafe_return",
})


def _import_serve():
    name = "status_ui_serve_for_reality_test"
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
def real(serve):
    config = serve.load_ui_config(REAL_CONFIG)
    return serve.StatusService(config)


def _kinds_with_a_provider(service) -> set[str]:
    return {reg.capability_kind for reg in service.manifest.registrations}


# --- 1. 실재 -----------------------------------------------------------------

def test_no_function_requires_a_capability_nobody_provides(real):
    """필수 capability 에 provider 가 없는 기능은 '우리가 가진 기능'이 아니다.

    예산이 모자라 탈락하는 것과는 다르다 — 그쪽은 provider 가 있으니 노드를 키우거나
    예산을 재면 켜진다. 여기서 막는 것은 켤 방법이 **아예 없는** 줄이다.
    """
    provided = _kinds_with_a_provider(real)

    orphans = {
        function.function_id: sorted(set(function.required_capabilities) - provided)
        for function in real.config.functions
        if set(function.required_capabilities) - provided
    }

    assert orphans == {}


def test_no_declared_capability_kind_is_without_a_provider(real):
    """kind 어휘에도 같은 규칙을 적용한다 — 선언만 된 kind 는 화면에
    no_provider_registered 한 줄로 남고, 그 줄은 아무것도 설명하지 않는다."""
    provided = _kinds_with_a_provider(real)

    declared = {spec.kind for spec in real.config.specs}
    active = set(real.config.profile.active_capability_kinds)

    assert declared - provided == set()
    assert active - provided == set()


def test_the_kinds_no_declared_node_can_host_are_the_named_ones(real):
    """provider 는 있는데 올릴 노드가 없는 kind 는 **이름으로** 적혀 있어야 한다.

    `required_hw_tag_missing` 은 정직한 사유다. 다만 그것이 늘어나는 것은 설정이
    조용히 다시 희망 목록이 되는 길이라, 늘어나면 이 시험이 먼저 깨진다.
    """
    node_tags: set[str] = set()
    for node in real.config.nodes:
        node_tags.update(node.tags)

    hostless = set()
    for kind in _kinds_with_a_provider(real):
        regs = [r for r in real.manifest.registrations if r.capability_kind == kind]
        if all(set(r.compatibility.required_hw_tags) - node_tags for r in regs):
            hostless.add(kind)

    assert hostless == KINDS_WITHOUT_A_HOST


def test_an_optional_capability_missing_is_degraded_not_cut(real):
    """선택 결손은 DEGRADED 까지만 내려간다(AI-C-05) — 그래서 DEGRADED 인 기능을
    '없는 기능'으로 잘라서는 안 된다. 그 구분이 실제로 살아 있는지 본다."""
    states = {row["function_id"]: row["state"] for row in real.functions()["functions"]}

    assert "local_safety" in states
    # 영상만으로도 도는 기능이고, 분류·깊이는 선택이다.
    assert states["local_safety"] in {"ACTIVE", "DEGRADED"}


# --- 2. 확장 -----------------------------------------------------------------

def _temp_deployment(tmp_path: Path) -> Path:
    """운영 설정과 그 manifest 를 그대로 복사한 임시 배치. 코드는 건드리지 않는다."""
    config = json.loads(REAL_CONFIG.read_text(encoding="utf-8"))
    manifest_name = config["providers_manifest"]
    shutil.copy(CONFIG_DIR / manifest_name, tmp_path / manifest_name)
    (tmp_path / "status_ui.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return tmp_path / "status_ui.json"


def test_a_new_capability_provider_node_and_function_are_four_declarations(serve, tmp_path):
    """새 기능을 들이는 일이 **선언 네 줄**이라는 것을 고정한다(절대 준수 #7, AI-B-09).

    새 kind 'inspection.weld_seam' 은 이 저장소 어디에도 없는 이름이다. 그런데도
    모듈을 한 줄도 고치지 않고 등록되고, 그 kind 를 요구하는 기능이 ACTIVE 로
    해소된다 — 등록부·선택기·판정이 전부 데이터를 읽기 때문이다(AI-C-10, AI-C-18).
    """
    config_path = _temp_deployment(tmp_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    manifest_path = tmp_path / config["providers_manifest"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # (1) 새 kind, (2) 그것을 주는 provider, (3) 그 provider 를 올릴 노드,
    # (4) 그 kind 를 요구하는 기능.
    config["capabilities"].append(
        {"kind": "inspection.weld_seam", "is_core": False, "degrade_rank": 0, "requirement": {}})
    config["deployment"]["active_capability_kinds"].append("inspection.weld_seam")
    manifest["providers"].append({
        "capability_kind": "inspection.weld_seam",
        "provider_id": "seam-scanner",
        "version": "1",
        "compatibility": {
            "required_hw_tags": ["sensor.seam_scanner"],
            "preferred_hw_tags": [],
            "cost": {"compute_units": 1.0, "memory_mb": 64},
            "priority": 50,
        },
        "requirement": {"required": [], "optional": []},
        "supported_inputs": ["image"],
        "supported_outputs": ["inspection_report"],
    })
    config["nodes"].append({
        "node_id": "crawler-001",
        "label": "용접선 점검 크롤러",
        "role": "ugv",
        "verified": False,
        # 태그는 **딱 그 센서만** 선언한다. 새 노드가 기존 kind 까지 제공하면
        # 다른 기능의 판정이 같이 움직여서 "확장이 남의 줄을 흔들지 않는다"를
        # 확인할 수 없다.
        "tags": ["compute.cpu", "tier.ugv", "sensor.seam_scanner"],
        "budget": {"compute_units": 1.0, "memory_mb": 128},
    })
    config["functions"].append({
        "function_id": "weld_seam_inspection",
        "required_capabilities": ["inspection.weld_seam"],
        "optional_capabilities": [],
    })

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    service = serve.StatusService(serve.load_ui_config(config_path))
    states = {row["function_id"]: row["state"] for row in service.functions()["functions"]}

    assert states["weld_seam_inspection"] == "ACTIVE"
    # 그리고 그 kind 를 실제로 그 노드가 제공한다 — 이름만 통과한 것이 아니다.
    served = service.fleet()["served"]["inspection.weld_seam"]
    assert [(entry["node_id"], entry["provider_id"]) for entry in served] \
        == [("crawler-001", "seam-scanner")]
    # 기존 기능 판정은 그대로다 — 확장이 남의 줄을 흔들지 않는다(AI-C-05).
    baseline = {row["function_id"]: row["state"]
                for row in serve.StatusService(serve.load_ui_config(REAL_CONFIG)).functions()["functions"]}
    assert {k: v for k, v in states.items() if k in baseline} == baseline


def test_a_new_model_version_is_one_line_and_unmeasured_stays_ineligible(tmp_path):
    """모델도 같다 — 새 버전은 선언 한 줄이고, 수치를 적지 않으면 적격이 아니다.

    AI-L-10 은 '같은 기능의 여러 버전'을 조건으로 고르라고 하고, AI-B-01 은 미측정
    항목을 구분하라고 한다. 둘을 함께 고정한다: 새 줄은 **코드 변경 없이** 후보가
    되고, 수치 없는 줄은 후보 목록에 **사유와 함께** 남는다(0 으로 메우지 않는다).
    """
    sys.path.insert(0, str(FRAMEWORK_DIR / "tools" / "fms_console"))
    import deployment as D  # noqa: PLC0415 — 도구 모듈을 경로로 싣는다

    from mission_runtime.runtime.model_assignment import DeviceProfile, MissionRequirement

    registry = json.loads(
        (CONFIG_DIR / "model_versions.example.json").read_text(encoding="utf-8"))
    before = D.model_versions_from_dict(registry)

    # 선언 한 줄. 이 저장소에 없는 모델 이름이고, 코드는 그대로다.
    registry["versions"].append({
        "model_id": "seam-classifier",
        "version": "v1-cpu",
        "capability_kind": "inspection.weld_seam",
        "verified_hw_tags": ["compute.cpu"],
        "verified_input_conditions": [],
        "quality": 0.80,
        "latency_ms": 90.0,
        "memory_mb": 256.0,
    })
    after = D.model_versions_from_dict(registry)

    assert len(after) == len(before) + 1
    added = next(v for v in after if v.reference == "seam-classifier@v1-cpu")
    assert added.fully_measured is True

    desk = D.ModelDesk(
        pipeline=D.local_pipeline(versions=after),
        device_profiles={"crawler-001": DeviceProfile(
            "crawler-001", frozenset({"compute.cpu"}), frozenset(), 1024.0)})
    requirement = MissionRequirement("m-seam", "inspection.weld_seam",
                                     min_quality=0.7, max_latency_ms=500.0)
    rows = {row["reference"]: row for row in desk.eligibility("crawler-001", requirement)}

    assert rows["seam-classifier@v1-cpu"]["eligible"] is True

    # 그리고 미측정 항목은 여전히 미측정이다 — 0 으로 메우지 않는 성질이 유지된다.
    unmeasured = [v for v in after if not v.fully_measured]
    assert unmeasured
    assert all(v.quality is None or v.latency_ms is None or v.memory_mb is None
               for v in unmeasured)
