"""요구 증거 계약과 격차 계산.

implements: AI-S-07, AI-S-03, AI-S-05, AI-C-05
tests: required vs preferred separation, tolerance decides sufficiency, semantic
       sufficiency counts independent sources (not confidence), unobtainable is a
       degradation path rather than an endless request, gap ordering

근거: docs/obsidian/ideas/evidence-driven-orchestration-plan.md §3 S1·S2
"""

from __future__ import annotations

import pytest

from mission_runtime.contracts.evidence_contract import (
    MissionContract,
    RequiredEvidence,
    SufficiencyItem,
    SufficiencyVerdict,
)
from mission_runtime.decision.evidence_gap import evaluate, gap
from mission_runtime.perception.object_record import ObjectRecord


def _contract(**over) -> MissionContract:
    spec = dict(mission_id="nav", revision=1, required=(
        RequiredEvidence("semantic_class", tolerance=2),
        RequiredEvidence("region_2d", tolerance=0.4),
        RequiredEvidence("distance", tolerance=0.5),
        RequiredEvidence("mask", tolerance=0.5, necessity="preferred"),
    ))
    spec.update(over)
    return MissionContract(**spec)


def test_preferred_evidence_does_not_block_completion():
    """선택 근거가 비어도 충족이다 — AI-S-07: 모든 객체에 같은 완성도를 요구하지 않는다."""
    v = SufficiencyVerdict("m", 1, (
        SufficiencyItem("semantic_class", "met", "required"),
        SufficiencyItem("region_2d", "met", "required"),
        SufficiencyItem("mask", "unmet", "preferred"),
    ))
    assert v.complete
    assert v.unmet_kinds == ()


def test_semantic_sufficiency_counts_sources_not_confidence():
    """의미 충족은 **독립 소스 수**로 센다(AI-S-03).

    한 모델이 0.94로 틀리는 것이 실측됐고(2026-09-21 YOLOE), 그때 신뢰도 임계로는
    거를 수 없었다. 신뢰도를 충족 기준으로 쓰면 같은 실패를 계약 수준에서 반복한다.
    """
    c = _contract()
    confident_but_alone = ObjectRecord(
        "o", geometry=(0, 0, 10, 10), confidence=0.99,
        semantic_class="chair", supporting_groups=1)
    item = next(i for i in evaluate(c, confident_but_alone).items
                if i.kind == "semantic_class")
    assert item.state == "unmet", item.detail

    corroborated = ObjectRecord(
        "o", geometry=(0, 0, 10, 10), confidence=0.30,
        semantic_class="chair", supporting_groups=2)
    item = next(i for i in evaluate(c, corroborated).items
                if i.kind == "semantic_class")
    assert item.state == "met", item.detail


def test_tolerance_decides_and_missing_tolerance_accepts():
    c = _contract(required=(RequiredEvidence("region_2d", tolerance=0.9),))
    r = ObjectRecord("o", geometry=(0, 0, 1, 1), confidence=0.5)
    assert evaluate(c, r).items[0].state == "unmet"

    loose = _contract(required=(RequiredEvidence("region_2d"),))
    assert evaluate(loose, r).items[0].state == "met"


def test_unobtainable_is_reported_but_not_requested():
    """만들 수 없는 증거는 무한 요청이 아니라 축소 경로다(AI-C-05, AI-S-05)."""
    c = _contract()
    r = ObjectRecord("o", geometry=(0, 0, 10, 10), confidence=0.8,
                     semantic_class="chair", supporting_groups=2)
    v = evaluate(c, r, available_kinds=frozenset({"detection"}))
    states = {i.kind: i.state for i in v.items}
    assert states["distance"] == "unobtainable"
    assert not v.complete                     # 숨기지 않는다
    assert "distance" not in [n.evidence_id for n in
                              gap(c, r, available_kinds=frozenset({"detection"}))]


def test_blocked_when_only_unobtainable_remains():
    v = SufficiencyVerdict("m", 1, (
        SufficiencyItem("semantic_class", "met", "required"),
        SufficiencyItem("distance", "unobtainable", "required"),
    ))
    assert v.blocked and not v.complete


def test_gap_puts_required_before_preferred():
    c = _contract()
    r = ObjectRecord("o", geometry=(0, 0, 10, 10), confidence=0.8,
                     semantic_class="chair", supporting_groups=1)
    kinds = [n.evidence_id for n in gap(c, r)]
    assert kinds.index("semantic_class") < kinds.index("mask")
    assert kinds.index("distance") < kinds.index("mask")


def test_gap_empties_when_contract_is_met():
    c = _contract(required=(RequiredEvidence("region_2d", tolerance=0.4),))
    r = ObjectRecord("o", geometry=(0, 0, 10, 10), confidence=0.8)
    assert gap(c, r) == ()
    assert evaluate(c, r).complete


def test_contract_rejects_duplicate_and_unknown_kinds():
    with pytest.raises(ValueError):
        MissionContract("m", (RequiredEvidence("mask"), RequiredEvidence("mask")))
    with pytest.raises(ValueError):
        RequiredEvidence("teleportation")
    with pytest.raises(ValueError):
        RequiredEvidence("mask", necessity="optional")   # 어휘는 두 개뿐


def test_presence_layer_is_delegated_not_duplicated():
    """required/preferred의 정의는 기존 AI-S-07 구현 한 곳에만 있다.

    2026-09-22: `perception/purpose_requirements.py`가 이미 그 분리를 구현하고 있는데
    모르고 병렬 구현을 만들었다. 두 곳에 두면 반드시 어긋나므로 존재 층을 위임했고,
    이 테스트가 그 위임을 고정한다.
    """
    from mission_runtime.perception.purpose_requirements import (
        PurposeRequirement,
        evaluate_gap,
    )

    c = _contract()
    pr = c.as_purpose_requirement()
    assert isinstance(pr, PurposeRequirement)
    assert pr.purpose_id == c.mission_id
    assert pr.required_fields == c.required_kinds
    assert pr.preferred_fields == c.preferred_kinds

    # 같은 입력에 대해 두 경로가 같은 결손을 말해야 한다.
    empty = ObjectRecord("o")
    mine = {i.kind for i in evaluate(c, empty).items if i.state != "met"}
    theirs = set(evaluate_gap(pr, set()).missing_required) | \
        set(evaluate_gap(pr, set()).missing_preferred)
    assert mine == theirs, (mine, theirs)
