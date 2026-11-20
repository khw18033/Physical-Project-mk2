"""Attachment declarations versus role tags, and the state where we could not look.

implements: AI-B-10 (말단 경량 실행 경계), AI-C-18 (구성요소 Capability 선언 규약)
관련: AI-S-08 (선언과 관측의 분리), 원칙 #15 (가용성은 백엔드가 판정한다)
tests: 실린 노드가 고정 역할 태그를 들었을 때 · 배제 어휘를 아무도 선언하지 않았을 때 ·
       부착 축을 적지 않은 선언이 어긋남으로 세어지지 않는 것 · 상대가 선언에 없을 때
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mission_runtime.contracts.device_attachment import (  # noqa: E402
    ATTACHMENT_CARRIED_BY,
    ATTACHMENT_STANDALONE,
    DeviceAttachment,
)
from mission_runtime.runtime.environment_profile import (  # noqa: E402
    REASON_CARRIED_HOLDS_STATIONARY_ROLE,
    REASON_CARRIER_NOT_DECLARED,
    REASON_EXCLUSION_UNDECLARED,
    DeclaredNode,
    load_carried_node_excluded_tags,
    report_attachment_conflicts,
)

#: 이 현장이 "고정 노드를 전제한다" 고 선언한 역할 태그들. **코드가 아니라 선언이
#: 주인이다** — 새 tier 는 문자열 하나이고 코드를 고치지 않는다(원칙 #1).
EXCLUDED = frozenset({"tier.edge", "tier.server"})


def _carried(node_id: str, carrier: str, tags: set[str]) -> DeclaredNode:
    return DeclaredNode(
        node_id=node_id,
        tags=frozenset(tags),
        attachment=DeviceAttachment(device_id=node_id, attachment=ATTACHMENT_CARRIED_BY,
                                    carrier_id=carrier, link="ethernet"),
    )


def test_a_carried_node_tagged_as_an_edge_tier_is_reported():
    """**실제 지형이 이 모양이다** — Pi 가 랜선으로 로봇에 붙어 컨테이너를 든다.

    그 Pi 가 `tier.edge` 로 읽히면 브로커·수집기 급 몫이 **움직이는 로봇에** 올라간다.
    AI-B-10 이 막으라고 한 바로 그것이고, 선언 두 줄이 서로 다른 말을 하고 있다.
    """
    nodes = [
        DeclaredNode("go1-001", frozenset({"tier.ugv"})),
        _carried("pi7", "go1-001", {"compute.cpu", "tier.edge"}),
    ]

    report = report_attachment_conflicts(nodes, excluded_tags_for_carried=EXCLUDED)

    assert not report.clean
    assert [(c.node_id, c.tag) for c in report.conflicts] == [("pi7", "tier.edge")]
    assert report.conflicts[0].reason == REASON_CARRIED_HOLDS_STATIONARY_ROLE
    # 보고이고 거절이 아니다 — 조인은 가용성 판정이 아니다(원칙 #15).
    assert report.checked is True


def test_an_undeclared_exclusion_vocabulary_is_not_a_clean_bill():
    """**선언 없음을 충돌 없음으로 읽으면 관문이 없는 것과 같다.**

    빈 목록 하나만 돌려주면 어휘를 빠뜨린 현장이 통과한 현장으로 보인다. 그래서
    `checked` 가 따로 있고 `clean` 은 검사했을 때만 참이다.
    """
    nodes = [_carried("pi7", "go1-001", {"tier.edge"})]

    report = report_attachment_conflicts(nodes, excluded_tags_for_carried=None)

    assert report.conflicts == (), "판단하지 못했으므로 어긋남을 지어내지 않는다"
    assert report.checked is False
    assert report.reason == REASON_EXCLUSION_UNDECLARED
    assert report.clean is False, "검사하지 못한 것은 clean 이 아니다"


def test_a_declaration_without_the_attachment_axis_is_not_a_conflict():
    """축을 **안 적은** 것과 혼자 서 있다고 적은 것은 다르고, 둘 다 어긋남이 아니다.

    안 적은 것을 어긋남으로 세면 지금까지의 선언 전부가 어긋남이 되어 이 보고가
    읽히지 않는다(`registry/onboarding.py` 의 덧붙임 규칙).
    """
    nodes = [
        DeclaredNode("edge-dev", frozenset({"tier.edge"})),          # 축을 안 적었다
        DeclaredNode("edge-gpu", frozenset({"tier.edge"}),
                     attachment=DeviceAttachment(device_id="edge-gpu",
                                                 attachment=ATTACHMENT_STANDALONE)),
    ]

    report = report_attachment_conflicts(nodes, excluded_tags_for_carried=EXCLUDED)

    assert report.clean


def test_a_carrier_that_is_not_a_declared_node_is_reported_separately():
    """싣고 있다고 적힌 상대가 현장에 없다 — 어긋남이지만 **다른 어긋남**이다."""
    nodes = [_carried("pi7", "go1-999", {"compute.cpu"})]

    report = report_attachment_conflicts(nodes, excluded_tags_for_carried=EXCLUDED)

    assert len(report.conflicts) == 1
    assert report.conflicts[0].reason.startswith(REASON_CARRIER_NOT_DECLARED)
    assert "go1-999" in report.conflicts[0].reason, "누구를 찾지 못했는지 남긴다"


def test_two_different_kinds_of_conflict_do_not_collapse_into_one():
    """역할 태그 어긋남과 상대 없음은 할 일이 다르다 — 태그를 고치거나, 상대를 들이거나."""
    nodes = [_carried("pi7", "go1-999", {"tier.edge"})]

    reasons = {c.reason.split(":")[0]
               for c in report_attachment_conflicts(
                   nodes, excluded_tags_for_carried=EXCLUDED).conflicts}

    assert reasons == {REASON_CARRIED_HOLDS_STATIONARY_ROLE, REASON_CARRIER_NOT_DECLARED}


def test_the_real_declaration_is_read_without_inventing_the_vocabulary():
    """이 저장소의 실제 선언으로 돌린다 — 어휘를 적지 않았으므로 `None` 이다.

    그것이 지금의 정상 상태이고, 이 시험은 "아직 선언하지 않았다" 를 **적어 두는**
    자리다. 현장이 어휘를 적는 날 이 시험이 바뀌고, 그때 검사가 실제로 돈다.
    """
    declared = load_carried_node_excluded_tags(
        Path(__file__).resolve().parents[1] / "config" / "status_ui.example.json")

    assert declared is None, "선언에 없으면 빈 집합이 아니라 None 이다"
    report = report_attachment_conflicts([], excluded_tags_for_carried=declared)
    assert report.checked is False
