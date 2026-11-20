"""증거 종류 → capability kind 매핑이 **배포가 실제로 쓰는 어휘**인지 본다.

implements: AI-C-01 (이름의 주인을 한 곳에 둔다), AI-S-03, AI-S-05
관련: AI-C-15 (도메인 차이는 구성), AI-C-05 (결손은 축소이고 침묵이 아니다)
tests: 매핑의 값이 선언 어휘에 있는지 · 선언이 없을 때 추측하지 않는지 ·
       매핑 없는 종류가 `unobtainable` 과 갈리는지

## 왜 이 시험이 생겼는가 (2026-11-05)

같은 표가 `decision/evidence_gap.py` 안의 코드 상수였고, **거기 적힌 capability
kind 11 개가 이 저장소의 선언 어휘와 하나도 맞지 않았다** — 표는 `detection` ·
`open_vocabulary_detection` · `range_sensing` 을, manifest 와 노드 선언은
`perception.detect` · `perception.detect_ovd` · `perception.distance` 를 썼다.

결과가 **가장 나쁜 방식으로 조용했다**: 모든 증거 종류가 `unobtainable` 로 떨어지고,
`gap()` 은 `unobtainable` 을 요청으로 내보내지 않으므로(만들 사람이 없는 것을
요청해도 소용없다) **아무것도 승격되지 않고 아무 요청도 나가지 않았다.** 그 상태의
산출은 "할 일이 없다" 와 글자 하나 다르지 않아서, 시험도 화면도 통과했다.

이 시험이 묻는 것은 하나다 — **표가 말하는 이름을 이 배치가 알아듣는가.**
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mission_runtime.contracts.evidence_contract import EVIDENCE_KINDS  # noqa: E402
from mission_runtime.contracts.evidence_contract import (  # noqa: E402
    MissionContract,
    RequiredEvidence,
)
from mission_runtime.decision.evidence_gap import (  # noqa: E402
    DEFAULT_KIND_PROVIDERS,
    DEFAULT_KIND_PROVIDERS_PATH,
    evaluate,
    gap,
    load_kind_providers,
    unanswerable_kinds,
)
from mission_runtime.perception.object_record import ObjectRecord  # noqa: E402

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _declared_capability_kinds() -> set[str]:
    """이 배치의 선언들이 쓰는 capability kind 전부.

    manifest 와 노드·기능 선언을 함께 본다 — 어느 한쪽만 보면 "provider 는 있는데
    기능이 안 쓴다" 같은 정상 상태를 어긋남으로 셀 수 있다.
    """
    kinds: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("capability_kind", "kind") and isinstance(value, str):
                    kinds.add(value)
                if key in ("required_capabilities", "optional_capabilities",
                           "active_capability_kinds") and isinstance(value, list):
                    kinds.update(v for v in value if isinstance(v, str))
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for path in itertools.chain((PACKAGE_ROOT / "config").glob("*.json"),
                                (PACKAGE_ROOT / "profiles").glob("*.json")):
        try:
            walk(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return kinds


def test_the_declaration_exists_and_is_read():
    assert DEFAULT_KIND_PROVIDERS_PATH.is_file(), (
        "매핑 선언이 없다. 없어도 도는 것이 설계이지만(빈 사전 → "
        "provider_mapping_undeclared) 이 저장소에는 있어야 한다")
    assert load_kind_providers(), "선언을 읽었는데 비어 있다"


def test_the_code_side_default_is_empty_on_purpose():
    """**그럴듯한 기본값을 두면 그 거짓이 조용해진다.**

    전에 여기 있던 11 개 후보가 바로 그것이었다 — 이름이 하나도 맞지 않는데 기본값이
    있어서 "표가 있다" 로 보였다.
    """
    assert DEFAULT_KIND_PROVIDERS == {}


def test_every_mapped_capability_kind_is_a_name_this_deployment_knows():
    """**이 시험이 그 결함을 잡는 자리다.**

    표가 가리키는 이름을 배치가 알아듣지 못하면 그 증거는 영원히 `unobtainable` 이고,
    `gap()` 이 그것을 요청으로 내보내지 않으므로 전체가 조용히 멈춘다.
    """
    declared = _declared_capability_kinds()
    assert declared, "선언에서 capability kind 를 하나도 못 읽었다 — 이 검사가 빈다"

    stray = {
        kind: [c for c in candidates if c not in declared]
        for kind, candidates in load_kind_providers().items()
    }
    stray = {k: v for k, v in stray.items() if v}

    assert not stray, (
        "매핑이 이 배치가 모르는 capability kind 를 가리킨다 — 그 증거는 영원히 "
        "`unobtainable` 이 되고 요청도 나가지 않는다. 선언 어휘로 고치거나, 그 "
        f"provider 종류를 선언에 추가한다:\n  {stray}"
    )


def test_every_mapped_evidence_kind_is_a_real_evidence_kind():
    """증거 종류 쪽 어휘의 주인은 `contracts/evidence_contract.py` 다."""
    unknown = sorted(set(load_kind_providers()) - set(EVIDENCE_KINDS))

    assert not unknown, f"모르는 증거 종류를 매핑에 적었다: {unknown}"


def test_an_absent_declaration_does_not_get_guessed():
    """선언이 없으면 빈 사전이다 — 추측하면 그 추측이 조용히 틀린다."""
    assert load_kind_providers(PACKAGE_ROOT / "config" / "no-such-file.json") == {}


def test_an_empty_list_and_an_absent_key_are_different_facts():
    """`[]` 는 "찾아봤고 없다", 키가 없는 것은 "아직 정하지 않았다" 다(AI-S-08)."""
    table = load_kind_providers({"evidence_kind_providers": {"mask": []}})

    assert table == {"mask": ()}, "빈 목록은 키로 남는다"
    assert "existence" not in table, "적지 않은 키는 생기지 않는다"


# ── 침묵이 드러나는가 ───────────────────────────────────────────────────────

def _contract(*kinds: str) -> MissionContract:
    return MissionContract(mission_id="m",
                           required=tuple(RequiredEvidence(kind=k) for k in kinds))


def test_an_unmapped_kind_is_told_apart_from_an_unobtainable_one():
    """둘은 **고칠 곳이 다르다** — 선언이냐 현장이냐.

    섞으면 `gap()` 이 둘 다 내보내지 않으므로 호출자에게는 똑같이 빈 목록으로
    보이고, 운영자는 장비를 사러 간다.
    """
    record = ObjectRecord(object_id="o1")

    # 매핑이 없다 → 무엇을 요청해야 하는지 모른다.
    unmapped = evaluate(_contract("existence"), record,
                        frozenset({"perception.detect"}), {})
    assert unmapped.items[0].state == "provider_mapping_undeclared"

    # 매핑은 있는데 그 종류를 내는 provider 가 지금 없다 → 현장의 축소 상태.
    unobtainable = evaluate(_contract("existence"), record,
                            frozenset(), {"existence": ("perception.detect",)})
    assert unobtainable.items[0].state == "unobtainable"

    assert unmapped.items[0].state != unobtainable.items[0].state


def test_the_unanswerable_kinds_are_listed_rather_than_dropped():
    """요청으로 못 나간 이유가 **선언 쪽**이면 그 목록이 나와야 한다."""
    record = ObjectRecord(object_id="o1")
    verdict = evaluate(_contract("existence"), record,
                       frozenset({"perception.detect"}), {})

    assert gap(_contract("existence"), record,
               frozenset({"perception.detect"}), {}) == (), "요청으로는 안 나간다"
    assert unanswerable_kinds(verdict) == ("existence",), "그 사실이 목록으로 나온다"


def test_the_real_declaration_lets_requests_flow():
    """고친 뒤의 정상 동작 — 선언 어휘로 돌면 요청이 실제로 나간다."""
    record = ObjectRecord(object_id="o1")
    available = frozenset({"perception.detect", "perception.distance"})

    needs = gap(_contract("existence", "distance"), record, available)

    assert {n.evidence_id for n in needs} == {"existence", "distance"}
    for need in needs:
        assert need.candidate_capability_kinds, "무엇이 답할 수 있는지 함께 낸다"
