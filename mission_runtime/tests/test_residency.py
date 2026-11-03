"""implements: AI-C-15, AI-C-05, AI-B-04, AI-B-06, AI-B-10, AI-C-13, AI-N-03
tests: (a) 링크 특성 → 자세 환산표(선언·미측정·표본부족·바닥·여유·불안정·안정),
(b) 배치 시점 기준값이 운행 중 전환 정책과 같은 숫자를 쓴다, (c) 같은 코드가
데이터만 달라서 드론 답과 로봇 답을 낸다, (d) 같은 목적 + 나쁜 링크 = 상주
기능이 더 많아진다, (e) 모든 답이 통제 어휘의 기계 판독 사유를 들고 있다,
(f) 엣지 쪽 짝과 통신 단절 생존(드론의 사각 감시·출동 임무·안전 제어),
(g) 목적 데이터 자체의 모순 검출, (h) 계획이 기존 ZoneApplication 경로로
그대로 넘어가 예산·태그·축소가 두 번 구현되지 않는다, (i) 로더의 알 수 없는
키·값 거부, (j) 예시 데이터 파일이 실제로 그 답을 낸다.

배치 결정(`runtime/residency.py`)은 "이 기능이 이 장치 **안에** 있어야 하는가"에
답하고, 그 뒤의 "지금 돌 수 있는가"는 기존 `ZoneApplication.resolve()`가 그대로
담당한다. 이 파일이 고정하려는 성질은 그 경계가 유지된다는 것이다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mission_runtime.contracts.capability import CapabilityRequirement, CapabilityState
from mission_runtime.contracts.data_dictionary import (
    LINK_POSTURE_REASONS as DICT_LINK_REASONS,
    LINK_POSTURES,
    RESIDENCY_DECISION_REASONS,
    RESIDENCY_VIOLATIONS as DICT_VIOLATIONS,
    state_change_reason_token,
)
from mission_runtime.contracts.profile import (
    OUTAGE_LOCAL_FALLBACK,
    OUTAGE_QUEUED_FOR_EDGE,
    OUTAGE_UNAFFECTED,
    OUTAGE_UNAVAILABLE,
    CapabilityResidencySpec,
    DeploymentProfile,
    DevicePurposeProfile,
    LinkPostureThresholds,
    LinkProfile,
    Residency,
    ResidencyPolicy,
    ResourceBudget,
)
from mission_runtime.contracts.profile_loader import (
    DeploymentProfileError,
    device_purpose_from_dict,
    load_device_purposes,
)
from mission_runtime.ondevice.link_handover import LinkPosture, LinkTransitionPolicy
from mission_runtime.registry.capability_registry import CapabilityRegistry, ProviderRegistration
from mission_runtime.contracts.profile import CompatibilityProfile, ResourceCost
from mission_runtime.runtime.application import ZoneApplication
from mission_runtime.runtime.residency import (
    LINK_POSTURE_REASONS,
    RESIDENCY_REASONS,
    RESIDENCY_VIOLATIONS,
    assess_link,
    decide_residency,
    thresholds_from_transition_policy,
)

EXAMPLE_PURPOSES = Path(__file__).resolve().parents[1] / "config" / "device_purposes.example.json"


# --- (a) 링크 특성 → 자세 --------------------------------------------------


@pytest.mark.parametrize(
    "link, expected_posture, expected_token",
    [
        (LinkProfile(), LinkPosture.LOCAL_ONLY, "link_quality_unknown"),
        (LinkProfile(declared_posture="remote_ok"), LinkPosture.REMOTE_OK, "link_posture_declared"),
        (LinkProfile(declared_posture="local_only"), LinkPosture.LOCAL_ONLY, "link_posture_declared"),
        # 순간값 한 번은 배치 근거가 아니다 — 같은 장치를 다른 시각에 재면
        # 0% 손실과 33% 손실이 둘 다 나온다.
        (LinkProfile(source="measured", quality=0.95, samples=1), LinkPosture.LOCAL_ONLY, "link_samples_insufficient"),
        (LinkProfile(source="measured", quality=0.10, samples=10), LinkPosture.LOCAL_ONLY, "link_quality_at_or_below_floor"),
        (LinkProfile(source="measured", quality=0.30, samples=10), LinkPosture.REDUCING, "link_quality_below_restore_margin"),
        # 평균은 좋은데 자주 끊기는 링크 — 평균만 보면 좋은 링크로 보인다.
        (LinkProfile(source="measured", quality=0.90, stability=0.55, samples=10), LinkPosture.REDUCING, "link_stability_below_threshold"),
        (LinkProfile(source="measured", quality=0.90, stability=0.98, samples=10), LinkPosture.REMOTE_OK, "link_quality_stable"),
        # 안정성을 아예 모르는 것은 불안정하다는 뜻이 아니다(제공자 부재를
        # 반대 근거로 읽지 않는다).
        (LinkProfile(source="measured", quality=0.90, samples=10), LinkPosture.REMOTE_OK, "link_quality_stable"),
    ],
)
def test_link_characteristics_map_to_a_posture_with_a_reason(link, expected_posture, expected_token):
    result = assess_link(link)

    assert result.posture is expected_posture
    assert state_change_reason_token(result.reason) == expected_token
    assert result.permits_remote is (expected_posture is LinkPosture.REMOTE_OK)


def test_an_unparseable_declared_posture_is_not_read_optimistically():
    """잘못된 선언을 조용히 좋은 쪽으로 해석하면 단절 시 안전 기능이 함께 사라진다."""
    result = assess_link(LinkProfile(declared_posture="excellent"))

    assert result.posture is LinkPosture.LOCAL_ONLY


# --- (b) 운행 중 전환과 같은 기준 -------------------------------------------


def test_deploy_time_thresholds_default_to_the_runtime_transition_policy_numbers():
    """배치 판정과 운행 중 전환이 다른 기준을 쓰면 "배치는 엣지에 맡겼는데
    뜨자마자 런타임이 로컬로 내리는" 상태가 정상처럼 보인다(AI-N-03)."""
    runtime_policy = LinkTransitionPolicy()
    deploy_defaults = LinkPostureThresholds()

    assert deploy_defaults.floor == runtime_policy.floor
    assert deploy_defaults.restore_margin == runtime_policy.restore_margin

    derived = thresholds_from_transition_policy(LinkTransitionPolicy(floor=0.4, restore_margin=0.1))
    assert (derived.floor, derived.restore_margin) == (0.4, 0.1)


def test_posture_vocabulary_matches_the_runtime_enum():
    assert set(LINK_POSTURES) == {p.value for p in LinkPosture}


# --- 목적 데이터 (테스트가 직접 만든, 파일과 무관한 최소 데이터) ------------


def _spec(kind, policy, **kw):
    return CapabilityResidencySpec(kind=kind, policy=ResidencyPolicy(policy), **kw)


DRONE = DevicePurposeProfile(
    purpose_id="drone_under_test",
    capabilities=(
        _spec("media.video_input", "resident", is_core=True, survives_outage=True,
              outage_behavior=OUTAGE_UNAFFECTED),
        _spec("perception.coverage_estimate", "resident", is_core=True, survives_outage=True,
              outage_behavior=OUTAGE_QUEUED_FOR_EDGE),
        _spec("mission.dispatch", "resident", is_core=True, survives_outage=True,
              outage_behavior=OUTAGE_UNAFFECTED),
        _spec("safety.local_judgment", "resident", is_core=True, survives_outage=True,
              outage_behavior=OUTAGE_UNAFFECTED),
        _spec("perception.track", "link_dependent", edge_service="edge.tracker",
              outage_behavior=OUTAGE_LOCAL_FALLBACK, local_fallback_kind="perception.detect"),
        _spec("perception.classify", "edge_served", edge_service="edge.classifier",
              edge_payload="media", outage_behavior=OUTAGE_UNAVAILABLE),
    ),
    link=LinkProfile(source="declared:site_survey", quality=0.45, stability=0.62, samples=12),
)

ROBOT = DevicePurposeProfile(
    purpose_id="robot_under_test",
    capabilities=(
        _spec("media.video_input", "resident", is_core=True, survives_outage=True,
              outage_behavior=OUTAGE_UNAFFECTED),
        _spec("perception.detect", "resident", is_core=True, survives_outage=True,
              outage_behavior=OUTAGE_QUEUED_FOR_EDGE),
        _spec("perception.depth", "resident", is_core=True, survives_outage=True,
              quality_is_safety_affecting=True, outage_behavior=OUTAGE_UNAFFECTED),
        _spec("perception.track", "resident", is_core=True, survives_outage=True,
              outage_behavior=OUTAGE_UNAFFECTED),
        _spec("control.locomotion", "resident", is_core=True, survives_outage=True,
              outage_behavior=OUTAGE_UNAFFECTED),
        _spec("perception.detect_ovd", "link_dependent", edge_service="edge.open_vocabulary",
              edge_payload="media", min_link_quality=0.75, outage_behavior=OUTAGE_UNAVAILABLE),
        _spec("perception.classify", "edge_served", edge_service="edge.classifier",
              edge_payload="media", outage_behavior=OUTAGE_UNAVAILABLE),
    ),
    link=LinkProfile(source="measured:overlay_probe", quality=0.82, stability=0.97, samples=20),
)


# --- (c) 같은 코드, 다른 데이터 ---------------------------------------------


def test_the_same_function_produces_the_drone_answer_and_the_robot_answer():
    """두 답이 나오는 이유는 코드 분기가 아니라 `DevicePurposeProfile` 내용
    차이뿐이라는 것 — 이것이 AI-C-15와 절대 준수 원칙 #3의 핵심이다."""
    drone = decide_residency(DRONE)
    robot = decide_residency(ROBOT)

    # 드론: 불안정 링크라 link_dependent 추적까지 말단으로 끌려온다.
    assert drone.link.posture is LinkPosture.REDUCING
    assert set(drone.ondevice_kinds) == {
        "media.video_input", "perception.coverage_estimate",
        "mission.dispatch", "safety.local_judgment", "perception.track",
    }
    assert drone.edge_kinds == ("perception.classify",)

    # 로봇: 안정 링크라 "이 클래스를 찾아줘" 계열은 엣지가 맡는다.
    assert robot.link.posture is LinkPosture.REMOTE_OK
    assert set(robot.ondevice_kinds) == {
        "media.video_input", "perception.detect", "perception.depth",
        "perception.track", "control.locomotion",
    }
    assert set(robot.edge_kinds) == {"perception.detect_ovd", "perception.classify"}

    # 같은 kind가 목적에 따라 반대편에 놓인다 — 그래도 판정 코드는 하나다.
    assert drone.decision_for("perception.track").placement is Residency.ONDEVICE
    assert robot.decision_for("perception.track").placement is Residency.ONDEVICE
    assert drone.decision_for("perception.track").reason.startswith("link_posture_requires_local")
    assert robot.decision_for("perception.track").reason == "resident_by_purpose"


# --- (d) 링크가 나쁜 장치일수록 상주 기능이 늘어난다 -------------------------


def test_a_worse_link_leaves_more_function_resident_on_the_same_purpose():
    good = decide_residency(ROBOT)
    bad = decide_residency(ROBOT, link=LinkProfile(source="measured:icmp", quality=0.30, stability=0.55, samples=24))

    assert len(bad.ondevice_kinds) > len(good.ondevice_kinds)
    assert "perception.detect_ovd" in bad.ondevice_kinds
    assert "perception.detect_ovd" in good.edge_kinds
    # 목적 데이터는 손대지 않았다 — 바뀐 것은 링크뿐이다.
    assert bad.purpose_id == good.purpose_id


def test_a_media_carrying_capability_needs_a_better_link_than_a_metadata_one():
    """링크 저하 비용은 페이로드에 선형이 아니다 — 메타데이터 543B는 100ms
    링크에서 편도 1회분만 늘지만 21KB JPEG은 초기 혼잡 윈도를 넘겨 3배가
    된다. 그래서 자세가 REMOTE_OK여도 픽셀을 오가게 하는 kind는 엣지로
    보내지 않을 수 있어야 한다."""
    marginal = LinkProfile(source="measured", quality=0.60, stability=0.98, samples=20)

    plan = decide_residency(ROBOT, link=marginal)

    assert plan.link.posture is LinkPosture.REMOTE_OK  # 자세 자체는 원격 허용
    ovd = plan.decision_for("perception.detect_ovd")   # 그러나 이 kind는 0.75를 요구
    assert ovd.placement is Residency.ONDEVICE
    assert ovd.reason == "link_quality_below_kind_minimum:0.6<0.75"


def test_an_unverifiable_quality_is_not_read_as_satisfied():
    declared_ok_but_unmeasured = LinkProfile(source="declared", declared_posture="remote_ok")

    plan = decide_residency(ROBOT, link=declared_ok_but_unmeasured)

    assert plan.decision_for("perception.detect_ovd").reason == "link_quality_unverifiable_for_kind"


# --- (e) 기계 판독 사유 ------------------------------------------------------


def test_every_answer_carries_a_reason_from_the_controlled_vocabulary():
    for purpose in (DRONE, ROBOT):
        plan = decide_residency(purpose)
        assert state_change_reason_token(plan.link.reason) in DICT_LINK_REASONS
        for decision in plan.decisions:
            assert state_change_reason_token(decision.reason) in RESIDENCY_DECISION_REASONS


def test_the_modules_reason_constants_stay_inside_the_dictionary():
    """선택기와 같은 규약: 모듈이 문자열을 정하고 사전이 어휘를 소유한다."""
    assert set(LINK_POSTURE_REASONS) <= set(DICT_LINK_REASONS)
    assert set(RESIDENCY_REASONS) <= set(RESIDENCY_DECISION_REASONS)
    assert set(RESIDENCY_VIOLATIONS) <= set(DICT_VIOLATIONS)


# --- (f) 엣지 쪽 짝과 통신 단절 생존 -----------------------------------------


def test_the_edge_complement_names_a_server_and_an_outage_behaviour_for_every_absent_kind():
    plan = decide_residency(ROBOT)
    complement = {c.kind: c for c in plan.edge_complement()}

    assert set(complement) == set(plan.edge_kinds)
    assert complement["perception.classify"].edge_service == "edge.classifier"
    assert complement["perception.classify"].outage_behavior == OUTAGE_UNAVAILABLE


def test_the_drone_keeps_surveillance_dispatch_and_safety_through_an_outage():
    """사용자가 이름 붙인 요구 그대로: 사각 감시·출동 임무·안전 제어는
    통신이 끊긴 동안에도 살아 있어야 한다."""
    plan = decide_residency(DRONE)
    report = plan.outage_survival_report()
    alive = set(report["keeps_running"]) | set(report["keeps_running_results_queued"])

    assert {"perception.coverage_estimate", "mission.dispatch", "safety.local_judgment"} <= alive
    # 그러는 동안 엣지 기능 하나가 사라지는 것은 그 기능 하나의 문제다(AI-C-05).
    assert report["stops_until_link_returns"] == ("perception.classify",)
    assert set(plan.survives_outage_kinds()) >= {"mission.dispatch", "safety.local_judgment"}


def test_an_edge_kind_can_degrade_to_a_local_fallback_instead_of_stopping():
    stable = LinkProfile(source="measured", quality=0.9, stability=0.99, samples=20)
    plan = decide_residency(DRONE, link=stable)

    assert plan.decision_for("perception.track").placement is Residency.EDGE
    assert plan.outage_survival_report()["degrades_to_local_fallback"] == ("perception.track",)


# --- (g) 목적 데이터 자체의 모순 ---------------------------------------------


def test_an_outage_critical_capability_placed_on_the_edge_is_reported_as_a_contradiction():
    broken = DevicePurposeProfile(
        purpose_id="contradictory",
        capabilities=(
            _spec("safety.local_judgment", "edge_served", survives_outage=True, edge_service="edge.safety"),
        ),
        link=LinkProfile(declared_posture="remote_ok"),
    )

    plan = decide_residency(broken)

    assert plan.violations == ("outage_critical_not_resident:safety.local_judgment",)


def test_a_safety_affecting_capability_that_is_not_core_is_reported_as_a_contradiction():
    """depth 입력 해상도를 절반으로 낮추면 근접 장애물 안전 판정이 14/20 →
    4/20으로 무너진다. 그런 기능은 여유를 만들기 위한 축소 손잡이가 될 수
    없으므로 축소 대상이 아니어야(core) 한다."""
    broken = DevicePurposeProfile(
        purpose_id="shrinkable_depth",
        capabilities=(
            _spec("perception.depth", "resident", quality_is_safety_affecting=True, is_core=False, degrade_rank=3),
        ),
    )

    plan = decide_residency(broken)

    assert "safety_affecting_kind_not_core:perception.depth" in plan.violations


def test_a_local_fallback_without_a_named_kind_is_reported_as_a_contradiction():
    broken = DevicePurposeProfile(
        purpose_id="dangling_fallback",
        capabilities=(_spec("perception.track", "edge_served", outage_behavior=OUTAGE_LOCAL_FALLBACK),),
    )

    assert "local_fallback_kind_missing:perception.track" in decide_residency(broken).violations


def test_the_shipped_purposes_are_internally_consistent():
    for purpose in load_device_purposes(EXAMPLE_PURPOSES).values():
        assert decide_residency(purpose).violations == ()


# --- (h) 계획이 기존 ZoneApplication 경로로 넘어간다 -------------------------


def _registry(costs: dict[str, float]) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for kind, cost in costs.items():
        registry.register_local(
            ProviderRegistration(
                capability_kind=kind,
                provider_id=f"{kind}-provider",
                version="1",
                compatibility=CompatibilityProfile(cost=ResourceCost(compute_units=cost, memory_mb=16)),
            )
        )
    return registry


def test_the_plan_feeds_the_existing_resolver_rather_than_a_second_one():
    """배치는 여기서 정하고, "지금 돌 수 있는가"는 기존 경로가 정한다.
    예산 부족 시 축소도 기존 규칙(core 유지, degrade_rank 큰 것부터) 그대로."""
    plan = decide_residency(ROBOT)
    base = DeploymentProfile(domain_id="t", active_capability_kinds=())

    profile = plan.ondevice_profile(base)
    assert profile.active_capability_kinds == plan.ondevice_kinds
    assert profile.domain_id == "t"  # 나머지 배포 성질은 그대로 둔다

    specs = plan.capability_specs(ROBOT)
    assert [s.kind for s in specs] == list(plan.ondevice_kinds)
    assert all(s.is_core for s in specs)

    registry = _registry({k: 1.0 for k in plan.ondevice_kinds})
    app = ZoneApplication(profile, registry, specs, node_tags=set())
    states = {k: r.state for k, r in app.resolve(ResourceBudget(compute_units=99, memory_mb=9999)).items()}
    assert set(states.values()) == {CapabilityState.ACTIVE}


def test_a_link_driven_addition_that_the_terminal_cannot_afford_is_shed_not_forced():
    """나쁜 링크가 기능을 말단으로 끌어오지만 말단이 감당 못 하면, 선택
    기능 하나가 빠질 뿐 핵심 기능은 남는다(AI-N-03 → AI-B-06 → AI-C-05,
    그리고 말단 경량 경계 AI-B-10)."""
    bad = LinkProfile(source="measured:icmp", quality=0.30, stability=0.55, samples=24)
    plan = decide_residency(ROBOT, link=bad)
    assert "perception.detect_ovd" in plan.ondevice_kinds

    costs = {k: 1.0 for k in plan.ondevice_kinds}
    costs["perception.detect_ovd"] = 5.0
    app = ZoneApplication(
        plan.ondevice_profile(DeploymentProfile(domain_id="t", active_capability_kinds=())),
        _registry(costs),
        plan.capability_specs(ROBOT),
        node_tags=set(),
    )
    resolutions = app.resolve(ResourceBudget(compute_units=6.0, memory_mb=9999))

    assert resolutions["perception.detect_ovd"].state is CapabilityState.DISABLED
    assert all(
        resolutions[kind].state is CapabilityState.ACTIVE
        for kind in plan.ondevice_kinds
        if kind != "perception.detect_ovd"
    )


def test_optional_dependency_loss_still_only_degrades_after_placement():
    """배치 결정이 AI-C-05의 축소 규칙을 덮어쓰지 않는다."""
    purpose = DevicePurposeProfile(
        purpose_id="p",
        capabilities=(
            CapabilityResidencySpec(
                kind="safety.local_judgment", policy=ResidencyPolicy.RESIDENT, is_core=True,
                requirement=CapabilityRequirement(optional=("perception.distance",)),
            ),
        ),
    )
    plan = decide_residency(purpose)
    app = ZoneApplication(
        plan.ondevice_profile(DeploymentProfile(domain_id="t", active_capability_kinds=())),
        _registry({"safety.local_judgment": 0.1}),
        plan.capability_specs(purpose),
        node_tags=set(),
    )

    resolution = app.resolve(ResourceBudget(compute_units=9, memory_mb=99))["safety.local_judgment"]
    assert resolution.state is CapabilityState.DEGRADED


# --- (i) 로더 --------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, fragment",
    [
        ({"purpose_id": "p", "capabilities": [{"kind": "a", "polciy": "resident"}]}, "unknown fields"),
        ({"purpose_id": "p", "capabilities": [{"kind": "a", "policy": "sometimes"}]}, "policy"),
        ({"purpose_id": "p", "capabilities": [{"kind": "a", "outage_behavior": "shrug"}]}, "outage_behavior"),
        ({"purpose_id": "p", "link": {"declared_posture": "great"}}, "declared_posture"),
        ({"purpose_id": "p", "capabilities": [{"kind": "a"}, {"kind": "a"}]}, "duplicate"),
        ({"capabilities": []}, "purpose_id"),
    ],
)
def test_the_loader_refuses_data_it_cannot_honour(raw, fragment):
    """오타 난 키를 조용히 무시하면 "선언했는데 안 먹는다"가 된다."""
    with pytest.raises(DeploymentProfileError) as error:
        device_purpose_from_dict(raw)
    assert fragment in str(error.value)


def test_a_purpose_needs_no_link_information_at_all():
    """AI-N-03: 특정 측정값이 항상 존재한다고 가정하지 않는다."""
    purpose = device_purpose_from_dict(
        {"purpose_id": "p", "capabilities": [{"kind": "x", "policy": "link_dependent"}]}
    )

    plan = decide_residency(purpose)

    assert plan.link.posture is LinkPosture.LOCAL_ONLY
    assert plan.ondevice_kinds == ("x",)  # 모르는 링크는 보수적으로 상주시킨다


# --- (j) 배포된 예시 데이터 --------------------------------------------------


def test_the_shipped_example_file_produces_the_two_named_cases():
    purposes = load_device_purposes(EXAMPLE_PURPOSES)
    assert {"river_surveillance_drone", "ground_robot", "fixed_camera"} <= set(purposes)

    drone = decide_residency(purposes["river_surveillance_drone"])
    robot = decide_residency(purposes["ground_robot"])

    # 드론: 불안정 통신 + 사각 감시 + 출동 임무 + 안전 제어가 말단에 남는다.
    assert drone.link.posture is LinkPosture.REDUCING
    assert {"perception.coverage_estimate", "mission.dispatch", "safety.local_judgment"} <= set(drone.ondevice_kinds)
    alive = set(drone.outage_survival_report()["keeps_running"]) | set(
        drone.outage_survival_report()["keeps_running_results_queued"]
    )
    assert {"perception.coverage_estimate", "mission.dispatch", "safety.local_judgment"} <= alive

    # 로봇: 2026-09-08에 확정된 분리 그대로 — class-agnostic 인지 + depth/TTC +
    # hazard 지속성 추적 + 안전/회피 제어가 말단, 의미 분류와 개체 식별은 엣지.
    assert {"perception.detect", "perception.depth", "perception.track",
            "safety.local_judgment", "control.locomotion"} <= set(robot.ondevice_kinds)
    assert {"perception.classify", "perception.associate"} <= set(robot.edge_kinds)

    # 고정 카메라: 안전 기능이 하나도 없는 목적도 같은 코드가 처리한다.
    camera = decide_residency(purposes["fixed_camera"])
    assert camera.ondevice_kinds == ("media.video_input",)
    assert not any(d.kind.startswith("safety.") for d in camera.decisions)
