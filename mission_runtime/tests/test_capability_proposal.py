"""기능 하나를 선언으로 들이는 길 — 되는지, 어디에, 안 되면 무엇이 더 필요한지.

implements: AI-B-09, AI-B-04, AI-C-18
관련: AI-B-01 (미측정은 0 이 아니다), AI-C-19 (추천이고 발령이 아니다), AI-B-13
tests: 선언 검증 · 미측정 비용이 거절과 다른 사유인 것 · 배치 정본에 위임하는 것 ·
       부족한 태그가 **어느 노드에도 없는 것만** 모이는 것 · 적용하지 않는 것

사용자가 든 예(2026-11-05)를 그대로 쓴다 — "3d 맵 구성 기능이 없다고 했을 때 해당
기능을 추가하려 했을 때 ... 현재 주어진 자원을 확인하고 배정 가능한지 판단하고
사용자에게 배정을 추천하고 불가능하다면 이유와 추가로 필요한 자원을 설명".
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mission_runtime.contracts.profile import ResourceCost  # noqa: E402
from mission_runtime.registry.capability_proposal import (  # noqa: E402
    REASON_COST_NOT_MEASURED,
    REASON_NO_PROVIDER_FOR_REQUIRED,
    REASON_ORACLE_UNAVAILABLE,
    CapabilityProposal,
    ProposalError,
    ProposedProvider,
    assess,
    proposal_from_dict,
)

#: 사용자가 든 예 — 3D 맵 구성. 선언 한 덩어리가 웹 폼이 보내는 모양이다.
MAP3D = {
    "function_id": "map_3d_build",
    "label": "3D 맵 구성",
    "rationale": "구역 진입 전에 지형을 미리 알아야 한다",
    "required_capabilities": ["perception.depth", "mapping.build_3d"],
    "optional_capabilities": ["perception.detect"],
    "providers": [
        {
            "capability_kind": "mapping.build_3d",
            "provider_id": "tsdf-fusion",
            "implementation_ref": "weights/mapping/tsdf.onnx",
            "compatibility": {
                "required_hw_tags": ["compute.gpu"],
                "preferred_hw_tags": ["media.hw_decode"],
                "cost": {"compute_units": 2.0, "memory_mb": 2048},
                "priority": 40,
            },
            "supported_inputs": ["image", "depth"],
            "supported_outputs": ["mesh"],
        },
        {
            "capability_kind": "perception.depth",
            "provider_id": "zipdepth-onnx",
            "implementation_ref": "weights/depth/zipdepth.onnx",
            "compatibility": {
                "required_hw_tags": ["compute.cpu"],
                "cost": {"compute_units": 1.0, "memory_mb": 512},
                "priority": 50,
            },
            "supported_outputs": ["depth"],
        },
    ],
}


class _Oracle:
    """정본 자리를 대신한다. **판정을 흉내내지 않고 받은 답을 그대로 돌려준다.**"""

    def __init__(self, rows):
        self.rows = rows
        self.asked: list[tuple[dict, list]] = []

    def assess_proposal(self, function_row, provider_rows):
        self.asked.append((dict(function_row), list(provider_rows)))
        return self.rows


# ── 선언이 성립하는가 (AI-C-18) ──────────────────────────────────────────────

def test_a_proposal_reads_the_shape_the_declaration_files_already_use():
    """모양을 새로 만들지 않는다 — 통과하면 그 줄을 그대로 선언 파일에 붙인다."""
    proposal = proposal_from_dict(MAP3D)

    assert proposal.function_id == "map_3d_build"
    assert proposal.kinds_offered == {"mapping.build_3d", "perception.depth"}
    row = proposal.as_function_row()
    assert row == {"function_id": "map_3d_build",
                   "required_capabilities": ["perception.depth", "mapping.build_3d"],
                   "optional_capabilities": ["perception.detect"]}
    manifest_row = proposal.providers[0].as_manifest_row()
    assert manifest_row["compatibility"]["cost"] == {"compute_units": 2.0,
                                                     "memory_mb": 2048.0}
    assert manifest_row["implementation_ref"] == "weights/mapping/tsdf.onnx", (
        "어느 모델로 돌릴지는 선언 항목이다 — provider_id 와 다르다")


def test_a_capability_less_declaration_is_refused_not_accepted_empty():
    """capability 를 하나도 안 적은 선언은 '무엇을 하는 기능인지' 가 없다."""
    with pytest.raises(ProposalError, match="capability"):
        CapabilityProposal(function_id="empty")


def test_a_duplicate_provider_id_is_refused():
    with pytest.raises(ProposalError, match="겹친다"):
        CapabilityProposal(
            function_id="f", required_capabilities=("k",),
            providers=(ProposedProvider("k", "same", cost=ResourceCost(1.0, 1.0)),
                       ProposedProvider("k", "same", cost=ResourceCost(1.0, 1.0))))


def test_a_required_capability_with_no_proposed_provider_is_named():
    """제안만으로 못 채우는 kind 를 **이름으로** 낸다 — 사용자가 무엇을 더 적어야
    하는지 알아야 한다."""
    proposal = proposal_from_dict(
        {**MAP3D, "providers": MAP3D["providers"][:1]})   # depth provider 를 뺀다

    assert proposal.required_without_provider() == ("perception.depth",)

    outcome = assess(proposal, _Oracle([]))
    assert not outcome.assignable
    assert any(r.startswith(REASON_NO_PROVIDER_FOR_REQUIRED) for r in outcome.blocking)
    assert "perception.depth" in outcome.blocking[0]


# ── 안 쟀으면 0 이 아니다 (AI-B-01, AI-B-09) ────────────────────────────────

def test_an_unmeasured_cost_is_a_measure_me_not_a_refusal():
    """**이 시험이 이 기능의 요점이다.**

    비용을 0 으로 두면 어느 노드에나 들어가는 공짜 기능이 되고 배치는 "들어갑니다"
    라고 답한다. 올리면 그 노드가 넘친다. 그래서 미측정은 거절이 아니라
    `needs_measurement` 다 — 운영자가 할 일은 **자원을 더하는 것이 아니라 재는 것**
    이고, 둘을 한 사유로 뭉개면 엉뚱한 하드웨어를 산다.
    """
    raw = {**MAP3D, "providers": [
        {**MAP3D["providers"][0], "compatibility": {"required_hw_tags": ["compute.gpu"]}},
        MAP3D["providers"][1],
    ]}
    proposal = proposal_from_dict(raw)

    assert proposal.providers[0].cost is None, "cost 키가 없으면 미측정이다"
    assert proposal.providers[0].cost_measured is False

    oracle = _Oracle([{"node_id": "edge-gpu", "state": "ACTIVE"}])
    outcome = assess(proposal, oracle)

    assert outcome.needs_measurement == ("tsdf-fusion",)
    assert any(r.startswith(REASON_COST_NOT_MEASURED) for r in outcome.blocking)
    assert not outcome.assignable
    # **배치를 아예 묻지 않는다.** 물어봤으면 그 답이 미측정을 0 으로 읽은 답이다.
    assert oracle.asked == [], "미측정 상태에서 정본을 부르면 순서가 뒤집힌다"


def test_an_unreadable_cost_is_also_unmeasured_not_zero():
    """비용 칸이 있는데 읽히지 않아도 0 이 아니다."""
    raw = {**MAP3D, "providers": [
        {**MAP3D["providers"][0],
         "compatibility": {"required_hw_tags": [], "cost": {"compute_units": "많음"}}},
        MAP3D["providers"][1],
    ]}

    assert proposal_from_dict(raw).providers[0].cost is None


def test_a_manifest_row_omits_the_cost_key_when_unmeasured():
    """0 을 적으면 그 0 이 실측처럼 읽힌다 — 그래서 키 자체를 싣지 않는다."""
    provider = ProposedProvider("k", "p", cost=None)

    assert "cost" not in provider.as_manifest_row()["compatibility"]


# ── 판정은 정본이 한다 (CLAUDE.md: 같은 판정을 두 곳에서 하지 않는다) ────────

def test_the_placement_question_goes_to_the_source_of_truth():
    proposal = proposal_from_dict(MAP3D)
    oracle = _Oracle([
        {"node_id": "edge-gpu", "state": "ACTIVE",
         "cost": {"compute_units": 3.0, "memory_mb": 2560.0}},
        {"node_id": "go1-onboard", "state": "DISABLED",
         "reason": "mapping.build_3d:missing_required",
         "missing_tags": ["compute.gpu"]},
    ])

    outcome = assess(proposal, oracle)

    assert outcome.assignable
    assert outcome.recommended.node_id == "edge-gpu", "정본이 준 순서의 머리를 집는다"
    assert outcome.recommended.cost == ResourceCost(3.0, 2560.0)
    # 제안을 **선언 모양 그대로** 넘겼는가 — 번역이 끼면 미리보기와 적용이 갈린다.
    function_row, provider_rows = oracle.asked[0]
    assert function_row == proposal.as_function_row()
    assert [r["provider_id"] for r in provider_rows] == ["tsdf-fusion", "zipdepth-onnx"]


def test_a_blocked_node_says_why_and_what_tag_is_missing():
    """"불가능하다면 이유와 추가로 필요한 자원을 설명" — 사용자가 든 요구 그대로다."""
    outcome = assess(proposal_from_dict(MAP3D), _Oracle([
        {"node_id": "go1-onboard", "state": "DISABLED",
         "reason": "mapping.build_3d:missing_required", "missing_tags": ["compute.gpu"]},
        {"node_id": "pi6", "state": "DISABLED",
         "reason": "mapping.build_3d:missing_required",
         "missing_tags": ["compute.gpu", "media.hw_decode"]},
    ]))

    assert not outcome.assignable
    assert outcome.recommended is None
    assert [v.reason for v in outcome.verdicts] == [
        "mapping.build_3d:missing_required", "mapping.build_3d:missing_required"]
    # **어느 노드에도 없는 태그만** 조달 목록에 넣는다. 한 노드에서만 빠진 태그를
    # 넣으면 운영자가 이미 되는 구성을 두고 장비를 산다.
    assert outcome.missing_tags == ("compute.gpu",)


def test_a_tag_missing_on_only_one_node_is_not_a_procurement_item():
    outcome = assess(proposal_from_dict(MAP3D), _Oracle([
        {"node_id": "edge-gpu", "state": "ACTIVE"},
        {"node_id": "pi6", "state": "DISABLED", "missing_tags": ["compute.gpu"]},
    ]))

    assert outcome.assignable
    assert outcome.missing_tags == (), "되는 노드가 있으면 살 것이 없다"


def test_not_being_able_to_ask_is_not_the_same_as_nowhere_to_put_it():
    """정본에 못 물어본 것과 "둘 곳이 없다" 는 다른 사실이다."""
    outcome = assess(proposal_from_dict(MAP3D), None)

    assert outcome.checked is False
    assert outcome.reason == REASON_ORACLE_UNAVAILABLE
    assert outcome.verdicts == ()
    assert not outcome.assignable, "검사하지 못한 것은 배정 가능이 아니다"


# ── 추천까지이고 적용은 아니다 (AI-C-19, AI-L-03) ───────────────────────────

def test_the_assessment_carries_the_declaration_but_applies_nothing():
    """통과하면 이 두 덩어리를 붙이면 된다. **붙이는 것은 사람이 하는 별개 행위다.**"""
    payload = assess(proposal_from_dict(MAP3D),
                     _Oracle([{"node_id": "edge-gpu", "state": "ACTIVE"}])).as_payload()

    assert payload["assignable"] is True
    assert payload["recommended"] == "edge-gpu"
    assert payload["declaration"]["function"]["function_id"] == "map_3d_build"
    assert len(payload["declaration"]["providers"]) == 2
    assert "applied" not in payload, "적용했다는 칸을 두지 않는다"


def test_the_payload_separates_what_to_buy_from_what_to_measure():
    """둘을 뭉개면 재면 되는 일에 하드웨어를 산다."""
    payload = assess(proposal_from_dict(MAP3D), None).as_payload()

    assert "missing_tags" in payload and "needs_measurement" in payload


def test_no_presentation_decision_leaves_the_payload():
    flat = repr(assess(proposal_from_dict(MAP3D), None).as_payload()).lower()

    for banned in ("color", "colour", "rgb", "pixel", "font"):
        assert banned not in flat


# ── 실제 현장 선언으로 (사용자가 든 3D 맵 예) ───────────────────────────────

@pytest.fixture(scope="module")
def site_service():
    """이 저장소의 **실제** 노드·provider 선언으로 배치 정본을 세운다.

    가짜 oracle 로만 시험하면 "제안을 넘긴다" 까지만 확인되고 **정본이 그 제안을
    실제로 해소할 수 있는지**는 확인되지 않는다. 그 둘이 갈리는 자리가 많다 —
    활성 kind 목록, spec 생성, 누적 예산이 전부 정본 쪽에 있다.

    `importlib` 로 **경로를 지정해** 올리는 이유(2026-11-05 고침): 이 저장소에는
    `serve.py` 가 둘 있고(`tools/status_ui/` 와 `tools/fms_console/`), `sys.path` 에
    디렉터리를 꽂아 이름으로 `import serve` 하면 **먼저 올라온 쪽이 잡힌다.** 처음
    판이 그랬고, 이 파일만 돌릴 때는 통과하고 전체 묶음에서는 콘솔 쪽 `serve` 가
    잡혀 `StatusService` 가 없다며 error 가 났다 — 단독 통과가 통과가 아니었다.
    """
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    config = root / "config" / "status_ui.example.json"
    module_path = root / "tools" / "status_ui" / "serve.py"
    if not config.is_file() or not module_path.is_file():
        pytest.skip("status_ui 도구·선언이 없는 배치 — 이 확인만 skip 된다(AI-C-05)")

    # 같은 디렉터리의 형제 모듈을 그 도구가 이름으로 import 하므로 경로는 필요하다.
    sys.path.insert(0, str(module_path.parent))
    name = "mission_runtime_status_ui_serve"
    spec = importlib.util.spec_from_file_location(name, module_path)
    module = importlib.util.module_from_spec(spec)
    # **`sys.modules` 에 먼저 넣는다.** 넣지 않으면 fixture 가 끝난 뒤 모듈 객체가
    # 수집되면서 그 전역이 비워지고, 거기서 정의된 메서드가 `NoneType has no
    # attribute '__dict__'` 로 죽는다 — 실제로 그렇게 났다.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.StatusService(module.load_ui_config(config))


def test_the_real_site_can_host_the_3d_map_on_its_gpu_nodes(site_service):
    """사용자가 든 예 그대로 — 없는 기능을 선언하면 어디에 들어가는지 답한다."""
    outcome = assess(proposal_from_dict(MAP3D), site_service)

    assert outcome.assignable, outcome.as_payload()
    assert outcome.recommended is not None
    # 정본의 선택 규칙(priority → cost → 선언 순서)이 고른 자리다. 이름을 박아 두는
    # 이유: 추천이 조용히 다른 노드로 옮겨가면 그것은 알아야 할 변화다.
    assert outcome.recommended.node_id == "edge-gpu"
    assert outcome.recommended.cost is not None, "쓸 수 있으면 비용이 나온다"


def test_a_node_without_the_gpu_says_the_tag_and_one_over_budget_says_the_budget(site_service):
    """**이 시험이 사용자의 요구다** — "불가능하다면 이유와 추가로 필요한 자원".

    요약 토큰 `no_compatible_provider_within_budget` 은 "태그가 없다" 와 "예산이
    모자라다" 를 한 칸에 담는다(공통 사전이 직접 그렇게 적는다). 그 둘은 운영자가
    할 일이 다르다 — 하드웨어를 들이는 것과 예산을 늘리는 것. 그래서 후보별 사유를
    읽어 가른다.
    """
    payload = assess(proposal_from_dict(MAP3D), site_service).as_payload()
    by_node = {n["node_id"]: n for n in payload["nodes"]}

    # GPU 가 없는 말단: 들여야 할 것이 하드웨어다.
    assert by_node["go1-onboard"]["missing_tags"] == ["compute.gpu"]
    assert by_node["go1-onboard"]["over_budget_kinds"] == []

    # 태그는 다 있는데 누적 예산이 모자란 엣지: 할 일이 **예산**이다.
    assert by_node["edge-dev"]["missing_tags"] == []
    assert by_node["edge-dev"]["over_budget_kinds"], "예산 부족을 사유로 남긴다"
    assert "edge-dev" in payload["needs_budget"]

    # 셋이 서로 다른 칸이다 — 뭉개면 엉뚱한 것을 고친다.
    assert payload["missing_tags"] == [], "둘 수 있는 노드가 있으면 살 것이 없다"
    assert payload["needs_measurement"] == []


def test_an_unusable_node_shows_no_cost_at_all(site_service):
    """둘 수 없는 노드에 부분 합을 적으면 "여기서는 이만큼 든다" 로 읽힌다 —
    그 수는 **올라가지 못한 몫이 빠진** 수다."""
    payload = assess(proposal_from_dict(MAP3D), site_service).as_payload()

    for node in payload["nodes"]:
        if node["state"] == "DISABLED":
            assert node["cost"] is None, node


def test_the_proposal_does_not_touch_the_declaration_files(site_service):
    """미리보기가 선언을 고치면 "돌려 봤는데 적용됐다" 가 된다(AI-L-03)."""
    config_path = Path(__file__).resolve().parents[1] / "config" / "status_ui.example.json"
    before = config_path.read_bytes()

    assess(proposal_from_dict(MAP3D), site_service)

    assert config_path.read_bytes() == before


def test_the_real_site_refuses_a_capability_no_proposed_provider_can_make(site_service):
    """제안이 필수 kind 를 못 채우면 배치를 묻기 전에 걸린다."""
    outcome = assess(
        proposal_from_dict({**MAP3D, "providers": MAP3D["providers"][:1]}),
        site_service)

    assert not outcome.assignable
    assert outcome.verdicts == (), "배치를 묻지 않았다"

