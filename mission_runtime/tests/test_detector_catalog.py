"""implements: AI-C-18, AI-C-15, AI-B-01, AI-C-16
tests: declaration loads, a fourth detector is a config line, no vendor enum in
       the loader, no measurement numbers in the declaration, declared weights
       match the real files

이 시험이 지키는 경계 둘.

1. **선언과 측정의 주인이 다르다.** 품질·지연·메모리 수치가 이 파일에 들어오는
   순간 같은 사실의 주인이 둘이 된다 — 그 수치는 `contracts/profile.py` 의
   `MeasurementSet`/`VerifiedExecutionProfile`(AI-B-01) 과
   `config/model_versions.example.json` 것이다.
2. **네 번째 탐지기는 설정 한 항목이다.** 로더가 탐지기 이름이나 태그를 알고
   있으면 그 말이 거짓이 되므로, 로더의 실행 코드에 그런 이름이 없음을 토큰
   단위로 확인한다.
"""

from __future__ import annotations

import json
import tokenize
from pathlib import Path

import pytest

from conftest import asset_root, asset_root_present

PROJECT_DIR = Path(__file__).resolve().parents[1]
CATALOG_FILE = PROJECT_DIR / "config" / "detector_characteristics.example.json"
LOADER_FILE = PROJECT_DIR / "edge" / "detector_catalog.py"


@pytest.fixture
def catalog():
    from mission_runtime.edge.detector_catalog import DetectorCatalog

    return DetectorCatalog.from_file()


# ── 선언이 실제로 읽히는가 ───────────────────────────────────────────────────


def test_shipped_declaration_loads_and_covers_the_three_zero_shot_families(catalog):
    ids = set(catalog.detector_ids)

    assert {"yolo-world-v2-s", "grounding-dino-tiny",
            "yoloe-11s-seg-prompted", "yoloe-11s-seg-prompt-free"} <= ids
    # 같은 capability 를 제공하는 후보들이라 **이름이 아니라 capability 로** 뽑힌다.
    assert len(catalog.of_capability("perception.detect_ovd")) == len(ids)


def test_the_vocabulary_channel_actually_differs_between_the_families(catalog):
    """세 계열이 어휘를 받는 방식이 다르다는 것이 이 선언의 존재 이유다."""
    world = catalog.get("yolo-world-v2-s").prompting
    dino = catalog.get("grounding-dino-tiny").prompting
    prompted = catalog.get("yoloe-11s-seg-prompted").prompting
    free = catalog.get("yoloe-11s-seg-prompt-free").prompting

    # 넷의 어휘 통로가 모두 다르거나, 최소한 prompt-free 는 나머지와 다르다.
    assert len({world.vocabulary_channel, dino.vocabulary_channel,
                prompted.vocabulary_channel, free.vocabulary_channel}) >= 3

    # 프롬프트가 필요한가 — prompt-free 만 아니다.
    assert world.prompt_required and dino.prompt_required and prompted.prompt_required
    assert free.prompt_required is False

    # 어휘를 바꾸는 값. GroundingDINO 는 모델이 호출마다 받을 수 있고(원리상 싸다)
    # 나머지 둘은 텍스트 인코더를 다시 돌려야 한다.
    assert dino.model_supports_per_call_prompt is True
    assert world.model_supports_per_call_prompt is False
    assert prompted.model_supports_per_call_prompt is False
    assert "text_encoder_pass" in world.vocabulary_change_requires
    assert "text_encoder_pass" in prompted.vocabulary_change_requires
    assert "text_encoder_pass" not in dino.vocabulary_change_requires

    # prompt-free 는 바꿀 어휘가 없으므로 바꾸는 값도 없다.
    assert catalog.get("yoloe-11s-seg-prompt-free").vocabulary_change_is_free is True
    assert catalog.get("yolo-world-v2-s").vocabulary_change_is_free is False


def test_prompt_free_entry_agrees_with_the_provider_about_the_label_namespace(catalog):
    """선언과 코드가 같은 말을 해야 한다 — 갈리면 콘솔이 보는 값과 흐르는 값이 다르다."""
    from mission_runtime.edge import yoloe_provider as P

    free = catalog.get("yoloe-11s-seg-prompt-free").prompting
    prompted = catalog.get("yoloe-11s-seg-prompted").prompting

    assert free.label_prefix == P.PROMPT_FREE_LABEL_PREFIX
    assert free.label_namespace == P.LABEL_NAMESPACE_BUILTIN
    assert prompted.label_prefix is None
    assert prompted.label_namespace == P.LABEL_NAMESPACE_OPERATOR
    # 어휘가 없으므로 선언된 어떤 어휘로도 판정되지 않는다 — "모른다"가 아니다.
    assert free.taxonomy_vocabulary is None


def test_declared_taxonomy_vocabularies_exist(catalog):
    from mission_runtime.perception.obstacle_taxonomy import ObstacleTaxonomy

    declared = set(ObstacleTaxonomy.from_file().vocabularies)

    for detector in catalog.all():
        name = detector.prompting.taxonomy_vocabulary
        if name is not None:
            assert name in declared, f"{detector.detector_id}: 없는 어휘 {name}"


def test_declared_provider_paths_import(catalog):
    """선언의 provider_path 가 죽은 문자열이 아닌지 확인한다."""
    import importlib

    for detector in catalog.all():
        path = detector.provider_path
        assert path, f"{detector.detector_id}: provider_path 가 비어 있다"
        module_name, _, class_name = path.partition(":")
        module = importlib.import_module(module_name)
        assert hasattr(module, class_name), f"{path} 가 없다"


def test_outputs_separate_absent_from_unsurfaced(catalog):
    """YOLOE seg 는 마스크를 **계산하지만** 계약이 못 싣는다. 그 둘을 가른다."""
    yoloe = catalog.get("yoloe-11s-seg-prompted").outputs
    world = catalog.get("yolo-world-v2-s").outputs

    assert "instance_mask" in yoloe.not_surfaced
    assert "instance_mask" not in yoloe.missing
    # YOLO-World 는 detect 가중치라 마스크 자체가 없다.
    assert "instance_mask" in world.missing
    assert world.not_surfaced == ()

    for detector in catalog.all():
        assert detector.gives("box_xyxy") and detector.gives("label") and detector.gives("score")
        assert detector.gives("depth_m") is False
        assert "depth_m" in detector.outputs.missing


# ── 선언에 들어가면 안 되는 것 ───────────────────────────────────────────────

#: 실행 구성마다 다시 재는 값들. 모델의 성질이 아니라 **구성의 성질**이라
#: AI-B-01 이 주인이고, 여기 복사되면 같은 사실의 주인이 둘이 된다.
_MEASUREMENT_TOKENS = (
    "quality", "latency", "memory", "fps", "throughput", "accuracy", "map50", "precision",
    "recall", "infer_ms", "p95", "p50",
)


def _walk_keys(node, path="") -> list[str]:
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            out.append(f"{path}.{k}")
            out.extend(_walk_keys(v, f"{path}.{k}"))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out.extend(_walk_keys(v, f"{path}[{i}]"))
    return out


def test_declaration_carries_no_measurement_numbers():
    raw = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))

    offenders = [
        key for key in _walk_keys(raw)
        if any(token in key.rsplit(".", 1)[-1].lower() for token in _MEASUREMENT_TOKENS)
    ]

    assert offenders == [], (
        f"측정값은 contracts/profile.py(AI-B-01)의 것이다 — 여기 적으면 주인이 둘이 된다: {offenders}")


def test_loader_knows_no_detector_name_and_no_vendor_enum():
    """로더의 **실행 코드**에 탐지기·벤더 이름이 없어야 네 번째 추가가 설정 한
    항목이다(원칙 #1). 주석·docstring 은 설명이라 제외한다."""
    forbidden = ("yoloe", "yolo", "world", "grounding", "dino", "mobileclip",
                 "ultralytics", "transformers", "clip", "promptfree", "nvidia", "cuda")

    hits = []
    with open(LOADER_FILE, "rb") as handle:
        for tok in tokenize.tokenize(handle.readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            lowered = tok.string.lower()
            hits.extend(f"line {tok.start[0]}: {tok.string}" for f in forbidden if f in lowered)

    assert hits == [], f"로더가 구체 기술 이름을 알고 있다: {hits}"


def test_loader_declares_no_enum_type():
    """자유 문자열 태그다 — enum 을 만들면 새 하드웨어·새 탐지기가 코드 변경이 된다."""
    source = LOADER_FILE.read_text(encoding="utf-8")

    assert "from enum import" not in source
    assert "import enum" not in source
    assert "Enum" not in source


# ── 네 번째 탐지기는 설정 한 항목이다 ───────────────────────────────────────


def test_a_fourth_detector_is_a_config_entry_not_a_code_change(tmp_path):
    """저장소 코드를 **한 줄도 바꾸지 않고** 새 탐지기를 더한다. 이름·태그·어휘
    통로 전부 로더가 처음 보는 값이어야 한다."""
    from mission_runtime.edge.detector_catalog import DetectorCatalog, DetectorCatalogError

    raw = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    raw["detectors"].append({
        "detector_id": "invented-detector-9",
        "display_name": "Invented Detector 9",
        "capability_kind": "perception.detect_ovd",
        "provider_path": "mission_runtime.edge.detector_catalog:DetectorCatalog",
        "tags": ["a_tag_nobody_declared", "tier.somewhere_new"],
        "prompting": {
            "vocabulary_channel": "an_unheard_of_channel",
            "prompt_required": True,
            "prompt_syntax": "whatever_syntax",
            "model_supports_per_call_prompt": True,
            "provider_fixes_prompt_at_construction": False,
            "vocabulary_change_requires": ["a_cost_nobody_declared"],
            "vocabulary_change_invalidates_results": True,
            "builtin_vocabulary_size": 7,
            "label_namespace": "some_other_namespace",
            "label_prefix": "invented:",
            "taxonomy_vocabulary": None,
        },
        "outputs": {"provided": ["box_xyxy", "label", "score", "a_new_output"],
                    "not_surfaced": [], "missing": ["depth_m"]},
        "weights": {"source": "an_unheard_of_source", "path": "nowhere/invented.bin",
                    "size_bytes": 123, "outbound_network_if_absent": False},
        "external_assets": [],
    })
    path = tmp_path / "detector_characteristics.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    catalog = DetectorCatalog.from_file(path)
    added = catalog.get("invented-detector-9")

    assert "invented-detector-9" in catalog.detector_ids
    assert added.prompting.vocabulary_channel == "an_unheard_of_channel"
    assert added.prompting.vocabulary_change_requires == ("a_cost_nobody_declared",)
    assert added.tags == ("a_tag_nobody_declared", "tier.somewhere_new")
    assert added.gives("a_new_output") is True
    assert added.weights.source == "an_unheard_of_source"
    assert len(catalog.of_capability("perception.detect_ovd")) == len(catalog.detector_ids)

    with pytest.raises(DetectorCatalogError):
        catalog.get("still-not-declared")


def test_structural_errors_are_rejected_but_value_contents_are_not_judged(tmp_path):
    from mission_runtime.edge.detector_catalog import DetectorCatalog, DetectorCatalogError

    def write(body) -> Path:
        path = tmp_path / f"c{abs(hash(json.dumps(body, sort_keys=True)))}.json"
        path.write_text(json.dumps(body), encoding="utf-8")
        return path

    with pytest.raises(DetectorCatalogError):
        DetectorCatalog.from_file(write({"nothing": []}))
    with pytest.raises(DetectorCatalogError):
        DetectorCatalog.from_file(write({"detectors": [{"display_name": "no id"}]}))
    with pytest.raises(DetectorCatalogError):
        DetectorCatalog.from_file(write({"detectors": [{"detector_id": "x"},
                                                       {"detector_id": "x"}]}))
    # 반대로, 내용이 낯설다고 거절하지는 않는다.
    ok = DetectorCatalog.from_file(write({"detectors": [{"detector_id": "bare"}]}))
    assert ok.get("bare").prompting.vocabulary_channel == ""
    assert ok.get("bare").weights.path is None
    assert ok.get("bare").weights_present(tmp_path) is None


# ── 선언과 관측의 분리 ───────────────────────────────────────────────────────


def test_presence_is_computed_not_declared(tmp_path, catalog):
    """`present: true` 는 선언 파일에 없다 — 기계마다 다른 사실이다."""
    raw = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    assert "present" not in json.dumps(raw)

    # 빈 자산 뿌리: 로컬 파일 출처는 전부 '없음', hub 출처는 '해당 없음'.
    presence = catalog.presence(tmp_path)
    assert presence["yoloe-11s-seg-prompted"]["weights_present"] is False
    assert presence["grounding-dino-tiny"]["weights_present"] is None
    assert presence["yoloe-11s-seg-prompted"]["missing_external_assets"] == [
        "mobileclip-blt-text-encoder"]
    # 가중치도 인코더도 없으니 나가는 연결이 필요하다(AI-C-16).
    assert presence["yoloe-11s-seg-prompted"]["outbound_network_required"] is True
    # prompt-free 는 텍스트 인코더를 요구하지 않는다 — 빠진 외부 자산이 없다.
    assert presence["yoloe-11s-seg-prompt-free"]["missing_external_assets"] == []


def test_present_weights_and_encoder_remove_the_outbound_requirement(tmp_path, catalog):
    """가중치와 외부 자산이 **각자의 자리에** 있으면 나가는 연결이 사라진다.

    두 자리가 다르다는 것이 요점이다. 가중치는 우리가 경로를 넘겨 읽히므로 자산
    뿌리에 있으면 되고, 외부 자산은 라이브러리가 자기 자리에서 찾으므로 **런타임이
    보는 자리**에 있어야 한다. 전에는 둘을 한 자리로 묻다가, 뿌리에만 있는 572MB
    인코더를 두고 카탈로그가 "연결 불필요" 라고 말하고 시도 경로는 같은 탐지기를
    거절했다 — 같은 사실에 주인이 둘이었던 자리다.
    """
    detector = catalog.get("yoloe-11s-seg-prompted")
    (tmp_path / detector.weights.path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / detector.weights.path).write_bytes(b"x")
    for asset in detector.external_assets:
        (tmp_path / asset.path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / asset.path).write_bytes(b"x")

    assert detector.weights_present(tmp_path) is True
    # 조달 질문: 뿌리에 다 있다.
    assert detector.missing_external_assets(tmp_path) == ()
    # 판정 질문: 런타임이 보는 자리를 **넘겨야** 답이 나온다.
    assert detector.outbound_network_required(
        tmp_path, runtime_search_paths=(tmp_path,)) is False
    assert detector.outbound_network_reason(
        tmp_path, runtime_search_paths=(tmp_path,)) is None


def test_an_asset_the_runtime_cannot_see_still_reaches_the_network(tmp_path, catalog):
    """뿌리에 있어도 **런타임이 그 자리를 보지 않으면** 받아 온다.

    실측으로 드러난 자리다 — `mobileclip_blt.ts`(572MB)가 자산 뿌리에 있는 기계에서
    카탈로그는 "연결 불필요" 라고 말했고 `tools/fms_console/serve.py` 의 시도 경로는
    같은 탐지기를 `would_reach_outbound_network:mobileclip-blt-text-encoder` 로
    거절했다. 운영자는 경고를 못 보고 고른 뒤 거절에서 처음 알게 된다(AI-C-16).

    그래서 자리를 모를 때는 **보수적으로** 답한다. 배치 전 검증이 거짓으로
    통과하는 것보다 한 번 더 경고하는 편이 낫다.
    """
    detector = catalog.get("yoloe-11s-seg-prompted")
    (tmp_path / detector.weights.path).write_bytes(b"x")
    for asset in detector.external_assets:
        (tmp_path / asset.path).write_bytes(b"x")
    elsewhere = tmp_path / "runtime-cwd"
    elsewhere.mkdir()

    # 뿌리에는 있다 — 조달은 끝났다.
    assert detector.missing_external_assets(tmp_path) == ()
    # 그런데 런타임이 보는 자리에는 없다 — 그러면 받아 온다.
    assert detector.external_assets_absent_from((elsewhere,)) == (
        "mobileclip-blt-text-encoder",)
    assert detector.outbound_network_reason(
        tmp_path, runtime_search_paths=(elsewhere,)) == "mobileclip-blt-text-encoder"
    # 자리를 아예 넘기지 않으면 "받아 오지 않는다" 고 말하지 않는다.
    assert detector.outbound_network_reason(tmp_path) == "mobileclip-blt-text-encoder"

    # 어휘를 받지 않는 형제는 그 인코더를 요구하지 않는다 — 모드 축이 선언에
    # 이미 들어 있어서(`external_assets: []`) 한 답으로 접히지 않는다.
    prompt_free = catalog.get("yoloe-11s-seg-prompt-free")
    (tmp_path / prompt_free.weights.path).write_bytes(b"x")
    assert prompt_free.external_assets == ()
    assert prompt_free.outbound_network_reason(tmp_path) is None


def test_a_node_without_an_asset_root_is_a_reason_not_an_exception(catalog):
    """자산 뿌리가 **없는 노드**는 정상 배치다 — 예외가 아니라 사유로 답한다.

    공개 트리만 받은 사람에게 `local/` 은 없다. 그 상태에서 `Path(None)` 이
    `TypeError` 가 되면 선택 결손이 장애로 번지고, 받는 쪽은 자기 환경을 의심한다
    (AI-C-05: 선택 조건 결손은 그 기능만 비활성이다).

    그리고 **세 사실이 갈라져 있어야 한다** — 물어볼 자리가 없는 것, 자리를 보고
    없었던 것, 애초에 물어볼 로컬 경로가 없는 출처. 셋을 한 값에 담으면 운영자가
    "뿌리를 가리키면 되는 일" 과 "가중치를 받아와야 하는 일" 을 구분할 수 없다
    (AI-O-05: 미측정 ≠ 0 ≠ 미달).
    """
    from mission_runtime.edge.detector_catalog import (
        PRESENCE_MEASURED,
        PRESENCE_NO_ASSET_ROOT,
        PRESENCE_SOURCE_NOT_LOCAL,
        characteristics,
        provider_for,
    )

    local_weights = catalog.get("yoloe-11s-seg-prompted")
    hub_weights = catalog.get("grounding-dino-tiny")

    # (1) 자리가 없다 — "없다"(False)가 아니라 "묻지 못했다"(None)이고 사유가 붙는다.
    assert local_weights.weights_present(None) is None
    assert local_weights.presence_reason(None) == PRESENCE_NO_ASSET_ROOT
    # (2) 같은 탐지기, 자리는 있고 파일이 없다 — 이쪽이 False 다.
    assert local_weights.weights_present("/nonexistent-asset-root") is False
    assert local_weights.presence_reason("/nonexistent-asset-root") == PRESENCE_MEASURED
    # (3) 로컬 경로를 선언하지 않은 출처는 뿌리와 무관하다.
    assert hub_weights.presence_reason("/nonexistent-asset-root") == PRESENCE_SOURCE_NOT_LOCAL

    # 조달 가능성: 뿌리가 없으면 로컬 가중치 선언은 세울 수 없고, 뿌리를 쓰지 않는
    # 출처는 그대로 남는다. 둘을 함께 끄면 "뿌리만 주면 되는 것" 이 사라진다.
    assert local_weights.buildable_here(None) is False
    assert hub_weights.buildable_here(None) is True
    # 보지 않은 자산을 "있다"로 접으면 폐쇄망 배치 전 검증이 거짓으로 통과한다.
    assert local_weights.missing_external_assets(None) == ()
    assert local_weights.outbound_network_required(None) is True

    # 운영 화면이 부르는 두 이름도 예외를 내지 않는다.
    rows = characteristics(asset_root=None)
    assert rows and all(row["presence_reason"] == PRESENCE_NO_ASSET_ROOT for row in rows)
    assert provider_for("yoloe-11s-seg-prompted", vocabulary=("box",), params={},
                        asset_root=None) is None


# ── 실물 자산 ────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not asset_root_present(),
                    reason="자산 뿌리 없음 (AI-C-05: 이 시험만 skip)")
def test_declared_weights_paths_and_sizes_match_the_real_files(catalog):
    """크기를 적어 두는 이유는 운영자가 고르기 전에 **얼마나 큰지** 알아야 하기
    때문이고, 그렇다면 적힌 값이 실제와 같아야 한다."""
    root = asset_root()
    checked = 0

    for detector in catalog.all():
        if detector.weights.path is None:
            continue
        path = root / detector.weights.path
        if not path.exists():
            continue
        assert detector.weights.size_bytes == path.stat().st_size, (
            f"{detector.detector_id}: 선언 크기와 실제 파일 크기가 다르다")
        checked += 1

    assert checked >= 3, f"실물로 확인한 가중치가 너무 적다({checked}) — 자산 배치 확인 필요"


@pytest.mark.skipif(not asset_root_present(),
                    reason="자산 뿌리 없음 (AI-C-05: 이 시험만 skip)")
def test_declared_external_asset_sizes_match_the_real_files(catalog):
    root = asset_root()

    for detector in catalog.all():
        for asset in detector.external_assets:
            if asset.path is None:
                continue
            path = root / asset.path
            if not path.exists():
                continue
            assert asset.size_bytes == path.stat().st_size, (
                f"{detector.detector_id}/{asset.asset_id}: 선언 크기와 실제 크기가 다르다")


# ── 구성 축과의 화해(AI-B-01 의 prompt_ref) ─────────────────────────────────


def test_prompt_ref_delegates_to_the_configuration_axis_normaliser(catalog):
    """정규화의 주인은 `contracts/profile.py` 하나다 — 여기서 다시 정하지 않는다.

    세 상태가 서로 다른 값이어야 한다: 어휘를 받지 않는 모델 · 어휘를 받지만 아직
    아무도 고르지 않은 상태 · 어휘가 정해진 상태. 셋을 접으면 어느 측정값이 어느
    구성의 것인지 알 수 없다.
    """
    from mission_runtime.contracts.profile import prompt_ref_for

    prompted = catalog.get("yoloe-11s-seg-prompted")
    free = catalog.get("yoloe-11s-seg-prompt-free")

    # 어휘를 받지 않는 모델: 리터럴 "prompt_free".
    assert free.prompt_ref() == "prompt_free"
    assert free.prompt_ref(["person"]) == "prompt_free"
    # 어휘를 받지만 아직 안 고른 상태: 빈 문자열. 위와 **다른 상태**다.
    assert prompted.prompt_ref() == ""
    assert prompted.prompt_ref() != free.prompt_ref()
    # 순서·대소문자는 같은 구성, 하나 더하면 다른 구성.
    assert prompted.prompt_ref(["Person", "box"]) == prompted.prompt_ref(["box", "person"])
    assert prompted.prompt_ref(["person", "box"]) != prompted.prompt_ref(["person", "box", "cat"])
    # 위임이지 재구현이 아니다.
    assert prompted.prompt_ref(["person"]) == prompt_ref_for(["person"])


# ── 운영 콘솔이 부르는 두 이름 ───────────────────────────────────────────────


def test_characteristics_rows_carry_what_the_console_needs(tmp_path):
    from mission_runtime.edge.detector_catalog import characteristics

    rows = characteristics(asset_root=tmp_path)
    by_ref = {r["implementation_ref"]: r for r in rows}

    assert len(rows) == 5
    # 고른 이름과 세워지는 이름이 같아야 결과를 되짚을 수 있다.
    assert by_ref["yoloe-11s-seg-prompted"]["detector_id"] == "yoloe-11s-seg-prompted"
    # 시도 경로가 구성 축을 채우는 값.
    assert by_ref["yoloe-11s-seg-prompt-free"]["prompt_free"] is True
    assert by_ref["yoloe-11s-seg-prompted"]["prompt_free"] is False
    # 받아들여지는 파라미터가 **고르기 전에** 드러난다(조용히 버리지 않는다).
    assert by_ref["grounding-dino-tiny"]["accepted_params"] == ["conf", "device", "text_conf"]
    assert by_ref["yolo-world-v2-s"]["accepted_params"] == ["conf", "device"]
    # 선언과 관측이 같은 행에 있지만 이름이 갈려 있다.
    assert by_ref["yoloe-11s-seg-prompted"]["weights_present"] is False
    assert by_ref["grounding-dino-tiny"]["weights_present"] is None
    assert by_ref["yoloe-11s-seg-prompted"]["outbound_network_required"] is True
    assert by_ref["yoloe-11s-seg-prompt-free"]["prompting"]["label_prefix"] == "promptfree:"


def test_provider_for_maps_operator_params_onto_each_constructor(tmp_path):
    """같은 `conf` 가 모델마다 다른 인자 이름이다 — 그 차이는 선언에 있다."""
    from mission_runtime.edge.detector_catalog import provider_for

    dino = provider_for("grounding-dino-tiny", vocabulary=["person", "box"],
                        params={"conf": 0.3, "text_conf": 0.2, "device": "cpu"},
                        asset_root=tmp_path)

    assert dino is not None
    assert dino.box_threshold == 0.3
    assert dino.text_threshold == 0.2
    assert dino.class_names == ["person", "box"]


def test_provider_for_ignores_params_it_never_declared(tmp_path):
    from mission_runtime.edge.detector_catalog import provider_for

    dino = provider_for("grounding-dino-tiny", vocabulary=["person"],
                        params={"a_param_nobody_declared": 1, "device": "cpu"},
                        asset_root=tmp_path)

    assert dino is not None  # 모르는 파라미터로 생성이 깨지지 않는다
    assert dino.box_threshold == 0.15  # provider 기본값 그대로


@pytest.mark.parametrize("ref,vocab", [
    ("not-a-declared-detector", ["person"]),   # 선언에 없는 참조
    ("yoloe-11s-seg-prompted", []),            # 어휘가 필요한데 비어 있다
    ("yolo-world-v2-s", []),
])
def test_provider_for_returns_none_when_it_cannot_build(tmp_path, ref, vocab):
    """None 은 장애가 아니라 "이 노드에서는 안 된다" 다(AI-C-05)."""
    from mission_runtime.edge.detector_catalog import provider_for

    assert provider_for(ref, vocabulary=vocab, params={}, asset_root=tmp_path) is None


def test_provider_for_returns_none_when_declared_weights_are_absent(tmp_path):
    from mission_runtime.edge.detector_catalog import provider_for

    assert provider_for("yoloe-11s-seg-prompted", vocabulary=["person"],
                        params={}, asset_root=tmp_path) is None
    assert provider_for("yoloe-11s-seg-prompt-free", vocabulary=[],
                        params={}, asset_root=tmp_path) is None


def test_a_fourth_detector_is_buildable_from_config_alone(tmp_path):
    """`provider_for()` 도 네 번째 탐지기에 손대지 않는다.

    선언만으로 **실제 객체**가 세워지는지 본다 — 조립 규약이 데이터인지 아니면
    로더가 아는 세 이름에만 되는지가 여기서 갈린다. 일부러 탐지기가 아닌 클래스를
    가리켜 "로더가 아는 것이 하나도 없는" 경우를 만든다.
    """
    from mission_runtime.edge.detector_catalog import characteristics, provider_for
    from mission_runtime.perception.detection import BrightBlobDetector

    raw = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    raw["detectors"].append({
        "detector_id": "invented-detector-9",
        "display_name": "Invented Detector 9",
        "capability_kind": "perception.detect_ovd",
        "provider_path": "mission_runtime.perception.detection:BrightBlobDetector",
        "tags": ["a_tag_nobody_declared"],
        "prompting": {"vocabulary_channel": "no_channel_at_all", "prompt_required": False,
                      "label_namespace": "some_other_namespace", "label_prefix": "invented:",
                      "taxonomy_vocabulary": None},
        "outputs": {"provided": ["box_xyxy", "label", "score"], "missing": ["depth_m"]},
        "weights": {"source": "no_weights_at_all", "path": None, "size_bytes": None,
                    "outbound_network_if_absent": False},
        "external_assets": [],
        "construction": {"weights_kwarg": None, "vocabulary_kwarg": None,
                         "param_kwargs": {"conf": "threshold", "min_area": "min_area"},
                         "fixed_kwargs": {}},
    })
    path = tmp_path / "detector_characteristics.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    provider = provider_for("invented-detector-9", vocabulary=[], params={"conf": 200},
                            asset_root=tmp_path, catalog_path=path)

    assert isinstance(provider, BrightBlobDetector)
    assert provider._threshold == 200
    rows = {r["implementation_ref"]: r for r in characteristics(asset_root=tmp_path,
                                                                catalog_path=path)}
    assert rows["invented-detector-9"]["prompt_free"] is True
    assert rows["invented-detector-9"]["accepted_params"] == ["conf", "min_area"]


def test_declared_construction_recipes_match_the_real_constructors(catalog):
    """선언한 인자 이름이 실제 생성자에 있는가. 없으면 선언이 거짓말이다."""
    import importlib
    import inspect

    for detector in catalog.all():
        module_name, _, class_name = detector.provider_path.partition(":")
        target = getattr(importlib.import_module(module_name), class_name)
        accepted = set(inspect.signature(target.__init__).parameters)
        recipe = detector.construction
        expected = set(recipe.param_kwargs.values()) | set(recipe.fixed_kwargs)
        for name in (recipe.weights_kwarg, recipe.vocabulary_kwarg):
            if name is not None:
                expected.add(name)
        missing = expected - accepted
        assert not missing, f"{detector.detector_id}: 생성자에 없는 인자 {missing}"


@pytest.mark.skipif(not asset_root_present(),
                    reason="자산 뿌리 없음 (AI-C-05: 이 시험만 skip)")
def test_provider_for_builds_the_real_providers_on_this_node():
    """실제 가중치가 있는 노드에서 선언만으로 세 계열이 모두 세워진다."""
    from mission_runtime.edge.detector_catalog import provider_for
    from mission_runtime.edge.yoloe_provider import PROMPT_MODE_FREE, PROMPT_MODE_TEXT

    root = asset_root()

    free = provider_for("yoloe-11s-seg-prompt-free", vocabulary=[],
                        params={"device": "cpu"}, asset_root=root)
    prompted = provider_for("yoloe-11s-seg-prompted", vocabulary=["person", "chair"],
                            params={"device": "cpu", "conf": 0.2}, asset_root=root)
    world = provider_for("yolo-world-v2-s", vocabulary=["person"],
                         params={"device": "cpu"}, asset_root=root)

    assert free is not None and free.prompt_mode == PROMPT_MODE_FREE
    assert free.is_available() is True
    # 어휘를 넣어도 prompt-free 모델에는 전달되지 않는다 — 선언에 그 인자가 없다.
    assert free.class_names is None

    assert prompted is not None and prompted.prompt_mode == PROMPT_MODE_TEXT
    assert prompted.class_names == ["person", "chair"]
    assert prompted.conf == 0.2
    assert prompted.is_available() is True

    assert world is not None and world.class_names == ["person"]
    assert world.is_available() is True
