"""도는 서비스와 프레임워크가 **같은 사실에 같은 답**을 하는지 본다.

implements: AI-C-01 (이름·값의 주인을 한 곳에 둔다)
관련: AI-S-06 (지속 객체 레코드), AI-S-03 (근거 충분도), AI-C-19
tests: 생명주기 임계의 주인이 하나인지 · 뜻이 다른 임계를 합치지 않았는지 ·
       서비스가 프레임워크를 실제로 import 하는지

## 두 나무가 있다

`services/edge-node/` 는 **실제로 도는** 엣지 서비스다(실측 지연과 운영 경험이 그
안에 있다). `mission_runtime/` 의 모듈들은 공개 대상 프레임워크다. 2026-11-05 까지
서비스는 프레임워크에서 **아무것도 import 하지 않았고**, 그 결과 요구사항 ID 23 개가
두 번 주장되는 상태였다(`internal/docs-dev/ai/requirement-traceability.md` 참고).

통합은 1707 행을 다시 쓰는 일이 아니라 **이음새를 하나씩 모으는** 일이다. 이 시험은
그중 모은 자리를 지키고, 아직 안 모은 자리를 **세어서** 남긴다 — 세어 두지 않으면
"통합했다" 가 어디까지인지 아무도 말할 수 없다.

## 왜 값이 같을 때도 문제인가

지금 두 나무의 생명주기 임계는 값이 같았다(2 / 3 / 5). 값이 같으면 아무 일도 없다.
그런데 **한쪽만 고치면 "확정" 의 뜻이 두 개가 된다** — 프레임워크의 승격 관문과 도는
서비스가 서로 다른 객체를 확정하고, 둘 다 자기 시험을 통과한다. 그 어긋남은 현장에서
처음 보인다.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SERVICE_DIR = PACKAGE_ROOT / "services" / "edge-node"

sys.path.insert(0, str(PACKAGE_ROOT))
sys.path.insert(0, str(SERVICE_DIR))

from mission_runtime.perception import object_record as framework  # noqa: E402

pytestmark = pytest.mark.skipif(
    not (SERVICE_DIR / "object_tracks.py").is_file(),
    reason="엣지 서비스가 없는 배치 — 이 확인만 skip 된다(AI-C-05)")


@pytest.fixture(scope="module")
def service():
    """서비스 모듈. 이름이 겹치지 않게 경로로 올린다."""
    import importlib.util

    name = "mission_runtime_edge_node_object_tracks"
    spec = importlib.util.spec_from_file_location(
        name, SERVICE_DIR / "object_tracks.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module      # 전역이 수집되지 않게 먼저 등록한다
    spec.loader.exec_module(module)
    return module


# ── 모은 자리 ───────────────────────────────────────────────────────────────

def test_the_lifecycle_thresholds_have_one_owner(service):
    """**이 시험이 통합 1 단계가 지켜지는 자리다.**

    값을 비교하는 것으로는 부족하다 — 두 곳에 같은 수를 적어 두어도 통과한다. 그래서
    **같은 객체인지**(`is`)를 묻는다. 서비스가 자기 숫자를 다시 적으면 여기서 깨진다.
    """
    assert service.CONFIRM_GROUPS is framework.CONFIRMING_GROUPS
    assert service.STALE_MISSES is framework.STALE_AFTER_MISSES
    assert service.EXPIRE_MISSES is framework.EXPIRE_AFTER_MISSES


def test_the_service_really_imports_the_framework(service):
    """산문이 아니라 **import 로** 닿아 있는지. 주석만으로는 값이 하나가 되지 않는다."""
    tree = ast.parse((SERVICE_DIR / "object_tracks.py").read_text(encoding="utf-8"))
    sources = {
        node.module for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "mission_runtime.perception.object_record" in sources


# ── 아직 안 모은 자리 — 합치면 안 되는 것과 남은 것을 가른다 ─────────────────

def test_thresholds_that_mean_different_things_are_not_merged(service):
    """**값이 비슷해 보인다고 합치면 한 수가 두 질문에 답한다.**

    `SPATIAL_CONSISTENCY_THRESHOLD`(0.45)는 *그룹 간* 기하 일관성이고 서비스의
    `ASSOC_IOU`(0.30)는 *관측 내* 근거 클러스터링이다. 값도 뜻도 달라서 통합 대상이
    아니고, 그 사실을 적어 둔다 — 다음 사람이 "둘 다 IOU 니까" 로 합치지 않도록.
    """
    assert service.ASSOC_IOU != framework.SPATIAL_CONSISTENCY_THRESHOLD
    assert service.TRACK_IOU != service.ASSOC_IOU, (
        "관측 내 클러스터링과 관측 간 매칭도 다른 질문이다")


def test_the_service_still_declares_what_the_framework_has_no_pair_for(service):
    """짝이 없는 임계는 서비스가 들고 있는 것이 맞다 — 없는 짝을 지어내지 않는다."""
    for name in ("ASSOC_IOU", "TRACK_IOU", "INIT_CONF"):
        assert hasattr(service, name)
        assert not hasattr(framework, name), (
            f"{name} 의 짝이 프레임워크에 생겼다 — 그러면 주인을 하나로 모은다")


def test_the_remaining_overlap_is_counted_not_forgotten():
    """**아직 프레임워크를 쓰지 않는 서비스 모듈을 세어 둔다.**

    통합이 어디까지 왔는지는 세어 두지 않으면 말할 수 없다. 이 수가 **줄어드는**
    방향으로만 움직여야 하고, 늘어나면 새 모듈이 프레임워크를 비껴 들어온 것이다.

    `edge_server.py`(1707 행)가 아직 그중 하나다 — 실측 지연과 운영 결정이 그 안에
    있어서 다시 쓰는 것이 아니라 이음새부터 모으는 중이다.
    """
    unintegrated = []
    for path in sorted(SERVICE_DIR.glob("*.py")):
        if path.name.startswith("test_"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        uses_framework = any(
            isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "mission_runtime")
            for node in ast.walk(tree))
        if not uses_framework:
            unintegrated.append(path.name)

    # **수가 아니라 목록이다**(`config/module_wiring.json` 과 같은 이유). 숫자만 두면
    # 하나를 통합하고 다른 하나를 비껴 넣어도 통과한다. 줄을 지우는 것이 통합이고,
    # 줄이 늘어나는 것은 프레임워크 계약을 비껴 들어온 것이다.
    #
    # 각 줄 뒤는 **무엇을 모아야 하는가** 다 — 짝이 되는 프레임워크 모듈이다.
    expected = {
        "edge_server.py",      # 단계형 파이프라인. 실측 지연·운영 결정이 안에 있어
                               # 다시 쓰지 않고 이음새부터 모은다.
        "semantic.py",         # 짝을 아직 재지 않았다. CLIP 쪽은
                               # `edge/clip_dictionary_provider.py` 가 후보다.
        # 아래 둘은 **재 봤고 짝이 없다**(2026-11-05). 처음에 짝을 적었는데 틀렸고,
        # 틀린 짝이 적힌 장부는 없는 장부보다 나쁘다 — 다음 사람이 그 짝을 믿는다.
        "retention.py",        # 짝 없음: 프레임워크의 `continual/stream_learning.py` 는
                               # "무엇으로 학습하나" 의 거절 사유이고 이쪽은 "디스크에
                               # 무엇을 남기나" 다. 다른 관심사이고, 보존 정책 계약은
                               # 프레임워크에 아직 없다.
        "postprocess.py",      # 짝 없음: `absorb`/`merge_overlapping`(조각 흡수·병합)에
                               # 대응하는 것이 없다. `ondevice/rpn_propose.py` 의
                               # DEFAULT_IOU 는 탐지기 자신의 NMS 파라미터이고 다른 것이다.
        "common.py",           # `iou` 가 프레임워크 `object_record._iou` 와 겹친다 —
                               # 다만 값이 일치하므로(아래 시험) 합치기 전에 공개 기하
                               # 모듈을 둘지 먼저 정해야 한다. 사설 함수를 import 하게
                               # 하는 것은 경계를 망가뜨린다.
        "calibrate_margins.py",  # 도구(임계 재보정) — 프레임워크를 쓸 자리인지 미판정
    }

    assert set(unintegrated) == expected, (
        "통합 상태가 이 목록과 다르다. 모았으면 줄을 지우고, 새 모듈이 프레임워크를 "
        f"비껴 들어왔으면 그것이 결함이다.\n  지금: {sorted(unintegrated)}"
    )
    assert "object_tracks.py" not in unintegrated, (
        "통합 1 단계가 되돌려졌다 — `object_tracks.py` 가 프레임워크를 다시 쓰지 않는다")


# ── 통합 2 단계: 합의 판정 ───────────────────────────────────────────────────

@pytest.fixture(scope="module")
def consensus():
    import importlib.util

    sys.path.insert(0, str(SERVICE_DIR))      # 형제 모듈 `common` 을 이름으로 쓴다
    name = "mission_runtime_edge_node_consensus"
    spec = importlib.util.spec_from_file_location(name, SERVICE_DIR / "consensus.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


BOX = [0.0, 0.0, 10.0, 10.0]
CFG = {"agree_iou": 0.5, "agree_min_conf": 0.5}


def test_how_many_agreeing_sources_confirm_has_one_owner(consensus):
    """"둘이 합의하면 확정" 을 **구조로** 들고 있었다 — 적지 않은 규칙도 규칙이다.

    `CONFIRMING_GROUPS` 가 3 이 되는 날 프레임워크의 승격 관문은 셋을 요구하는데 이
    파일은 여전히 둘에 confident 를 붙인다. 둘 다 자기 시험을 통과하고, 어긋남은
    현장에서 처음 보인다.
    """
    assert consensus.CONFIRMING_GROUPS is framework.CONFIRMING_GROUPS


def test_a_pair_that_agrees_becomes_one_confident_detection(consensus):
    out, stats = consensus.merge_by_consensus(
        [{"label": "bottle", "conf": 0.71, "box": BOX}],
        [{"label": "bottle", "conf": 0.56, "box": BOX}], CFG)

    assert stats["agreed"] == 1
    assert [d["verdict"] for d in out] == ["confident"]
    assert out[0]["sources"] == ["prompt_free", "text_prompt"]


def test_a_pair_below_the_floor_keeps_both_rather_than_dropping_one(consensus):
    """**고친 결함**(2026-11-05): 검출 둘이 들어가 하나만 나왔다.

    짝을 **찾은 시점**에 secondary 를 소비했기 때문에, 라벨은 맞았지만 floor 를 못
    넘은 쌍의 secondary 가 조용히 사라졌다 — 통계는 `secondary: 1` 이라 적으면서
    산출에는 없었다. 이 파일 머리말이 "합의하지 않은 검출은 버리지 않는다" 고
    약속한 자리다. 확정하지 못한 관측을 지우면 관리자가 두 근거를 나란히 볼 길도,
    학습 후보로 올릴 길도 사라진다(AI-S-04, AI-L-03).
    """
    out, stats = consensus.merge_by_consensus(
        [{"label": "bottle", "conf": 0.71, "box": BOX}],
        [{"label": "bottle", "conf": 0.20, "box": BOX}], CFG)

    assert stats["agreed"] == 0
    assert len(out) == 2, f"검출이 사라졌다: {out}"
    assert sorted(d["sources"][0] for d in out) == ["prompt_free", "text_prompt"]
    assert all(d["verdict"] == "tentative" for d in out)
    # 통계가 산출과 어긋나지 않는다 — 어긋나면 어느 쪽이 참인지 알 수 없다.
    assert stats["tentative"] == len(out)


def test_an_unpaired_secondary_is_still_kept(consensus):
    """짝이 없는 secondary 도 남는다 — 이쪽은 전에도 맞았고, 함께 고정한다."""
    out, _ = consensus.merge_by_consensus(
        [{"label": "bottle", "conf": 0.71, "box": BOX}],
        [{"label": "keyboard", "conf": 0.80, "box": [50.0, 50.0, 60.0, 60.0]}], CFG)

    assert len(out) == 2
    assert {d["label"] for d in out} == {"bottle", "keyboard"}


# ── 아직 둘인 구현: 어긋나면 깨지도록 ───────────────────────────────────────

@pytest.fixture(scope="module")
def service_common():
    import importlib.util

    sys.path.insert(0, str(SERVICE_DIR))
    name = "mission_runtime_edge_node_common"
    spec = importlib.util.spec_from_file_location(name, SERVICE_DIR / "common.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


#: 경계를 포함한 경우들. 퇴화 상자(면적 0)와 역순 좌표를 넣는 이유는 두 구현이
#: **보통 입력에서는 쉽게 일치하고 경계에서 갈리기** 때문이다.
IOU_CASES = (
    ("완전 일치", (0, 0, 10, 10), (0, 0, 10, 10)),
    ("절반 겹침", (0, 0, 10, 10), (5, 0, 15, 10)),
    ("안 겹침", (0, 0, 10, 10), (20, 20, 30, 30)),
    ("선분으로 맞닿음", (0, 0, 10, 10), (10, 0, 20, 10)),
    ("포함", (0, 0, 10, 10), (2, 2, 8, 8)),
    ("한쪽 면적 0", (5, 5, 5, 5), (0, 0, 10, 10)),
    ("양쪽 면적 0", (5, 5, 5, 5), (5, 5, 5, 5)),
    ("역순 좌표", (10, 10, 0, 0), (0, 0, 10, 10)),
)


@pytest.mark.parametrize("name,a,b", IOU_CASES, ids=[c[0] for c in IOU_CASES])
def test_the_two_iou_implementations_do_not_disagree(service_common, name, a, b):
    """**구현이 둘인데 값은 같아야 한다.**

    `services/edge-node/common.py::iou` 와 `perception/object_record.py::_iou` 는
    같은 기하를 따로 구현한다. 2026-11-05 에 재 보니 경계 경우까지 전부 일치했으므로
    **지금은 합치지 않았다** — 프레임워크 쪽은 사설 함수(`_iou`)이고, 서비스가 그것을
    import 하게 하면 경계를 망가뜨린다. 공개 기하 모듈을 둘지는 따로 정할 일이다.

    합치지 않은 대신 **어긋나면 여기서 깨진다.** 한쪽에만 들어간 수정이 두 나무가
    같은 상자에서 다른 겹침을 계산하게 만드는 길이고, 그 차이는 확정 판정까지
    번진다(합의 IoU·추적 매칭이 모두 이 값을 쓴다).
    """
    from mission_runtime.perception.object_record import _iou as framework_iou

    assert service_common.iou(list(a), list(b)) == pytest.approx(
        framework_iou(tuple(a), tuple(b)), abs=1e-9), name


# ── 통합 3 단계: 벤치가 운영과 같은 전처리를 쓴다 ───────────────────────────

def test_the_benchmark_preprocesses_exactly_as_production_does():
    """**벤치가 운영과 다른 전처리를 쓰면 재는 대상이 다르다.**

    CLIP 정규화 상수를 두 곳에 적고 있었다(값은 같았다). 전처리가 한쪽만 바뀌면 이
    벤치는 운영이 돌리지 않는 파이프라인을 재고, 그 수를 보고 모델을 고르면 고른
    근거가 거짓이 된다. 벤치가 운영과 같은 전처리를 쓴다는 것은 벤치의 **전제**이고
    선택이 아니므로, 값이 아니라 **출처**를 하나로 모았다.
    """
    import importlib.util

    import numpy as np

    path = SERVICE_DIR / "bench_clip.py"
    if not path.is_file():
        pytest.skip("벤치 도구가 없는 배치")
    sys.path.insert(0, str(SERVICE_DIR))
    name = "mission_runtime_edge_node_bench_clip"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as error:                      # noqa: BLE001
        pytest.skip(f"벤치가 필요한 선택 의존성이 없다: {type(error).__name__}")

    from mission_runtime.edge.clip_dictionary_provider import _CLIP_MEAN, _CLIP_STD

    assert np.allclose(module.MEAN, np.array(_CLIP_MEAN, np.float32))
    assert np.allclose(module.STD, np.array(_CLIP_STD, np.float32))

    # 값 비교만으로는 두 곳에 같은 수를 적어 두어도 통과한다 — import 로 닿아 있는지도 본다.
    tree = ast.parse(path.read_text(encoding="utf-8"))
    sources = {node.module for node in ast.walk(tree)
               if isinstance(node, ast.ImportFrom) and node.module}
    assert "mission_runtime.edge.clip_dictionary_provider" in sources
