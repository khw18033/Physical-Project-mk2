"""Functional validation fixtures for V11~V14; no model training is run.

implements: AI-L-01, AI-L-02, AI-L-03, AI-L-04, AI-L-05, AI-L-06, AI-L-07, AI-L-08
"""

import pytest

from perception_framework.continual import (
    Box,
    DynamicTaskGrouper,
    HierarchicalTwoSampleDetector,
    LearningLineage,
    LearningState,
    MicroProfile,
    PseudoLabel,
    ReplayCandidate,
    ReplaySelector,
    ResourceAllocator,
    ResourceJob,
)


def test_h2st_cascade_identifies_task_and_rejects_ood() -> None:
    detector = HierarchicalTwoSampleDetector(alpha=0.05)
    detector.add_task("indoor", ((0.0, 0.1), (0.1, 0.0), (-0.1, 0.0), (0.0, -0.1)))
    detector.add_task("outdoor", ((4.9, 5.0), (5.0, 4.9), (5.1, 5.0), (5.0, 5.1)))

    known = detector.decide(((4.9, 5.1), (5.0, 5.0), (5.1, 4.9), (5.0, 5.1)))
    unknown = detector.decide(((10.0, -10.0), (10.2, -9.9), (9.9, -10.2), (10.1, -10.1)))

    assert known.in_distribution and known.task_id == "outdoor"
    assert tuple(task for task, _ in known.p_values) == ("indoor", "outdoor")
    assert not unknown.in_distribution and unknown.task_id is None


def test_replay_quality_and_cross_sampling_are_objective() -> None:
    selector = ReplaySelector(confidence_min=0.7, similarity_min=0.5)
    strong = PseudoLabel("cat", 0.9, Box(0, 0, 10, 10))
    weak = PseudoLabel("cat", 0.6, Box(0, 0, 10, 10))
    confusing = ReplayCandidate(
        "c1", "old", strong, PseudoLabel("dog", 0.8, Box(1, 1, 11, 11))
    )
    agreed = ReplayCandidate(
        "c2", "old", strong, PseudoLabel("cat", 0.8, Box(1, 1, 11, 11))
    )

    assert selector.select_pseudo_labels((strong, weak)) == (strong,)
    assert selector.select_scs((confusing, agreed)) == (confusing,)


def test_dgs_groups_similar_tasks_and_consolidates_state() -> None:
    grouper = DynamicTaskGrouper(divergence_max=5.0)
    first = grouper.assign("rain-1", ((0.0, 0.0), (0.2, 0.2)), (1.0, 0.0))
    merged = grouper.assign("rain-2", ((0.05, 0.05), (0.25, 0.25)), (0.0, 1.0))
    separate = grouper.assign("night", ((9.0, 9.0), (10.0, 10.0)), (0.5, 0.5))

    assert first.group_id == merged.group_id
    assert merged.task_ids == ("rain-1", "rain-2")
    assert merged.adapter_state == pytest.approx((0.5, 0.5))
    assert separate.group_id != merged.group_id


def test_dgs_forgetting_gate_isolates_instead_of_consolidating_on_large_shift() -> None:
    # AI-L-05: 새 지식만 보고 병합하면 기존 검증된 group의 adapter_state를 과도하게
    # 흔들 수 있다 — divergence는 통과해도 병합 후 상태 이동이 크면 병합 대신 격리한다
    # (Kayenta류 baseline-vs-candidate 회귀 게이트).
    grouper = DynamicTaskGrouper(divergence_max=5.0, forgetting_max=0.1)
    first = grouper.assign("rain-1", ((0.0, 0.0), (0.2, 0.2)), (1.0, 0.0))
    # divergence는 낮지만(같은 그룹으로 매칭될 조건) adapter_state가 크게 달라 병합하면
    # 기존 상태(1.0, 0.0)를 거의 지워버린다.
    isolated = grouper.assign("rain-2", ((0.05, 0.05), (0.25, 0.25)), (0.0, 100.0))

    assert isolated.group_id != first.group_id
    assert isolated.adapter_state == pytest.approx((0.0, 100.0))
    # 격리됐으므로 원래 그룹의 검증된 adapter_state는 그대로 보존된다.
    assert grouper.groups[0].adapter_state == pytest.approx((1.0, 0.0))


def test_dgs_forgetting_gate_disabled_by_default() -> None:
    # forgetting_max를 지정하지 않으면 기존 동작(순수 divergence 기반 병합)을 그대로
    # 유지한다 — 새 게이트가 기본값으로 기존 회귀 스위트를 바꾸지 않는다.
    grouper = DynamicTaskGrouper(divergence_max=5.0)
    grouper.assign("rain-1", ((0.0, 0.0), (0.2, 0.2)), (1.0, 0.0))
    merged = grouper.assign("rain-2", ((0.05, 0.05), (0.25, 0.25)), (0.0, 100.0))

    assert merged.task_ids == ("rain-1", "rain-2")


def test_ekya_policy_selects_profiles_and_allocates_all_chunks() -> None:
    jobs = (
        ResourceJob("camera-a", (MicroProfile("fast", 0.1, 0.6, 0.7, 10),)),
        ResourceJob("camera-b", (MicroProfile("slow", 0.1, 0.5, 0.9, 100),), minimum_chunks=1),
    )
    allocation = ResourceAllocator().allocate(jobs, total_chunks=4)

    assert sum(chunks for _, chunks in allocation.values()) == 4
    assert allocation["camera-a"][1] > allocation["camera-b"][1]
    assert allocation["camera-a"][0] == "fast"


def test_ai_l_lineage_is_complete_auditable_and_rollback_capable() -> None:
    lineage = LearningLineage("run-1", actor="selector", evidence_ref="raw/candidates.json", reason="drift")
    while lineage.state != LearningState.VERIFIED:
        lineage.advance(actor="reviewer", evidence_ref=f"evidence/{len(lineage.events)}.json", reason="gate passed")

    assert [event.sequence for event in lineage.events] == list(range(1, 10))
    assert {event.requirement_id for event in lineage.events} == {
        "AI-L-01", "AI-L-02", "AI-L-03", "AI-L-04", "AI-L-05", "AI-L-06", "AI-L-07", "AI-L-08"
    }
    rollback = lineage.rollback(actor="operator", evidence_ref="metrics/regression.json", reason="regression")
    assert rollback.state == LearningState.ROLLED_BACK


def test_lineage_rejects_skipped_gates_and_missing_evidence() -> None:
    lineage = LearningLineage("run-2", actor="selector", evidence_ref="candidate.json", reason="novelty")
    with pytest.raises(ValueError):
        lineage.rollback(actor="operator", evidence_ref="metric.json", reason="too early")
    with pytest.raises(ValueError):
        lineage.advance(actor="", evidence_ref="quarantine.json", reason="quality gate")
