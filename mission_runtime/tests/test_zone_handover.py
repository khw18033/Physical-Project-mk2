"""implements: AI-N-03, AI-C-05, AI-C-19, AI-N-02
covers: 전환 요청과 실제 전환의 분리, 구역 전환의 세 겹 히스테리시스(우세폭·
        연속표본·체류시간)와 되돌아가기 벌점, 바닥 아래에서의 완화, 모르는
        구역 배제, 같은 구역 안 피어 교체의 위임, 측정 실패를 나쁨으로 바꾸지
        않는 것, 구역 진입 시 구성 재적용 신호, 무선 규격·지표 이름 비유출

마지막 두 시험은 실제 이동 로봇 RSSI 기록(zenodo:1219249)을 재생해 히스테리시스가
없을 때와 있을 때의 전환 횟수를 **같은 입력으로** 비교한다.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from mission_runtime.ondevice import zone_handover
from mission_runtime.ondevice.link_handover import (
    LinkPosture,
    LinkSample,
    LinkTransitionPolicy,
)
from mission_runtime.ondevice.zone_handover import (
    LINK_UNKNOWN,
    LINK_UNKNOWN_FORCED_LOCAL,
    PeerObservation,
    ZONE_CANDIDATE_BELOW_MARGIN,
    ZONE_ENTERED,
    ZONE_ENTRY_REQUESTED,
    ZONE_HOLDING_DWELL,
    ZONE_HOLDING_SAMPLES,
    ZONE_NO_CANDIDATE,
    ZONE_SWITCH_FORCED_BY_FLOOR,
    ZONE_SWITCH_REQUESTED,
    ZONE_UNKNOWN,
    ZoneHandoverPolicy,
)

DATASET = (
    Path(__file__).resolve().parents[2] / "local"
    / "datasets" / "link_quality" / "robot_rssi_zenodo_1219249"
    / "experiment_2_garden_1.csv"
)


def seated(policy: ZoneHandoverPolicy, zone="zone-a", at=0.0) -> ZoneHandoverPolicy:
    """이미 한 구역에 자리 잡은 상태로 만든다(첫 진입은 별도 시험이 본다)."""
    policy.confirm_zone(zone, at=at)
    return policy


def feed(policy, quality, peers, *, start=10.0, step=1.0, count=1, peer="a1", zone="zone-a"):
    decision = None
    for index in range(count):
        decision = policy.observe(
            LinkSample(start + index * step, quality, peer, zone), list(peers)
        )
    return decision


# --- 요청과 사실의 분리 (AI-C-19) ----------------------------------------------


def test_a_switch_is_requested_but_never_performed_by_this_module():
    """실제 무선 전환은 네트워크 provider의 몫이다 — 요청만으로 구역이 바뀌면
    실패한 전환이 성공한 것처럼 보인다."""
    policy = seated(ZoneHandoverPolicy())
    entries_so_far = policy.zone_changes        # 최초 진입 1회
    neighbours = [PeerObservation("b1", 0.95, "zone-b")]

    decision = feed(policy, 0.5, neighbours, count=policy.zone_hold_samples, start=100.0)

    assert decision.switch_to_zone == "zone-b"
    assert decision.zone_reason.startswith(ZONE_SWITCH_REQUESTED)
    assert policy.zone_id == "zone-a"          # 아직 넘어가지 않았다
    assert policy.zone_changes == entries_so_far


def test_only_a_confirmed_entry_changes_the_zone_and_asks_for_config_reapply():
    """AI-N-02: 구역이 실제로 바뀌면 그 구역의 외부 구성을 다시 받아야 한다."""
    policy = seated(ZoneHandoverPolicy())

    entry = policy.confirm_zone("zone-b", at=120.0)

    assert entry.zone_id == "zone-b" and entry.previous_zone == "zone-a"
    assert entry.requires_config_refresh is True
    assert entry.reason.startswith(ZONE_ENTERED)
    assert policy.zone_id == "zone-b" and policy.zone_changes == 2   # 최초 진입 + 이번 전환


def test_confirming_the_zone_we_are_already_in_is_not_a_change():
    policy = seated(ZoneHandoverPolicy())

    entry = policy.confirm_zone("zone-a", at=50.0)

    assert entry.requires_config_refresh is False
    assert policy.zone_changes == 1            # 최초 진입 한 번뿐


def test_the_first_observation_requests_entry_instead_of_assuming_one():
    policy = ZoneHandoverPolicy()

    decision = policy.observe(
        LinkSample(0.0, 0.8, "a1", "zone-a"), [PeerObservation("a1", 0.8, "zone-a")]
    )

    assert decision.switch_to_zone == "zone-a"
    assert decision.zone_reason.startswith(ZONE_ENTRY_REQUESTED)
    assert policy.zone_id is None


def test_with_no_zone_information_at_all_the_policy_says_so():
    policy = ZoneHandoverPolicy()

    decision = policy.observe(LinkSample(0.0, 0.8, "a1"), [PeerObservation("b1", 0.9)])

    assert decision.zone_reason == ZONE_UNKNOWN
    assert decision.switch_to_zone is None


# --- 히스테리시스 세 겹 ---------------------------------------------------------


def test_a_marginally_better_neighbouring_zone_does_not_pull_the_terminal_over():
    policy = seated(ZoneHandoverPolicy())

    decision = feed(policy, 0.60, [PeerObservation("b1", 0.70, "zone-b")], count=5, start=100.0)

    assert decision.switch_to_zone is None
    assert decision.zone_reason.startswith(ZONE_CANDIDATE_BELOW_MARGIN)


def test_a_clearly_better_zone_still_has_to_stay_better_for_several_samples():
    policy = seated(ZoneHandoverPolicy())
    neighbours = [PeerObservation("b1", 0.95, "zone-b")]

    first = feed(policy, 0.5, neighbours, start=100.0)
    assert first.switch_to_zone is None
    assert first.zone_reason.startswith(ZONE_HOLDING_SAMPLES)

    last = feed(policy, 0.5, neighbours, start=101.0, count=policy.zone_hold_samples - 1)
    assert last.switch_to_zone == "zone-b"


def test_one_good_sample_between_bad_ones_resets_the_hold_counter():
    """경계에서 한 번 튄 값이 전환을 만들면 안 된다."""
    policy = seated(ZoneHandoverPolicy())
    strong = [PeerObservation("b1", 0.95, "zone-b")]
    weak = [PeerObservation("b1", 0.60, "zone-b")]

    feed(policy, 0.5, strong, start=100.0, count=policy.zone_hold_samples - 1)
    feed(policy, 0.5, weak, start=110.0)             # 후보가 잠시 나빠졌다
    decision = feed(policy, 0.5, strong, start=120.0)

    assert decision.switch_to_zone is None
    assert decision.zone_reason == f"{ZONE_HOLDING_SAMPLES}:1/{policy.zone_hold_samples}"


def test_a_terminal_that_just_arrived_will_not_leave_again_immediately():
    """체류시간 조건: 막 넘어온 구역에서 곧바로 되넘어가지 않는다."""
    policy = ZoneHandoverPolicy(min_zone_dwell_seconds=30.0)
    policy.confirm_zone("zone-a", at=100.0)
    neighbours = [PeerObservation("b1", 0.95, "zone-b")]

    decision = feed(policy, 0.5, neighbours, start=101.0, step=0.5,
                    count=policy.zone_hold_samples + 2)

    assert decision.switch_to_zone is None
    assert decision.zone_reason.startswith(ZONE_HOLDING_DWELL)


def test_after_the_dwell_time_the_same_evidence_does_move_it():
    policy = ZoneHandoverPolicy(min_zone_dwell_seconds=30.0)
    policy.confirm_zone("zone-a", at=100.0)
    neighbours = [PeerObservation("b1", 0.95, "zone-b")]

    decision = feed(policy, 0.5, neighbours, start=200.0, count=policy.zone_hold_samples)

    assert decision.switch_to_zone == "zone-b"


def test_going_straight_back_to_the_zone_we_just_left_needs_more_than_going_forward():
    """A→B→A 진동을 막는 것은 되돌아가기 벌점이다."""
    policy = ZoneHandoverPolicy(min_zone_dwell_seconds=0.0)
    policy.confirm_zone("zone-a", at=0.0)
    policy.confirm_zone("zone-b", at=100.0)          # 방금 A를 떠나 B로 왔다

    borderline = [PeerObservation("a1", 0.5 + policy.zone_switch_margin, "zone-a")]
    decision = feed(policy, 0.5, borderline, start=101.0, peer="b1", zone="zone-b",
                    count=policy.zone_hold_samples + 1)

    assert decision.switch_to_zone is None           # 일반 여유로는 모자라다
    assert decision.zone_reason.startswith(ZONE_CANDIDATE_BELOW_MARGIN)

    stronger = [PeerObservation("a1", 0.5 + policy.zone_switch_margin
                                + policy.return_penalty + 0.01, "zone-a")]
    decision = feed(policy, 0.5, stronger, start=110.0, peer="b1", zone="zone-b",
                    count=policy.zone_hold_samples)
    assert decision.switch_to_zone == "zone-a"


def test_the_return_penalty_expires_so_a_real_return_is_not_blocked_forever():
    policy = ZoneHandoverPolicy(min_zone_dwell_seconds=0.0, penalty_decay_seconds=10.0)
    policy.confirm_zone("zone-a", at=0.0)
    policy.confirm_zone("zone-b", at=100.0)

    borderline = [PeerObservation("a1", 0.5 + policy.zone_switch_margin + 0.01, "zone-a")]
    decision = feed(policy, 0.5, borderline, start=500.0, peer="b1", zone="zone-b",
                    count=policy.zone_hold_samples)

    assert decision.switch_to_zone == "zone-a"


# --- 바닥 아래에서의 완화 -------------------------------------------------------


def test_when_the_current_link_is_already_unusable_the_dwell_rule_is_waived():
    """지킬 것이 없는데 체류시간을 채우라고 하는 것은 안정성이 아니라 갇힘이다."""
    policy = ZoneHandoverPolicy(min_zone_dwell_seconds=60.0)
    policy.confirm_zone("zone-a", at=100.0)
    neighbours = [PeerObservation("b1", 0.8, "zone-b")]

    decision = feed(policy, 0.1, neighbours, start=101.0, count=policy.zone_hold_samples)

    assert decision.posture is LinkPosture.LOCAL_ONLY
    assert decision.switch_to_zone == "zone-b"
    assert decision.zone_reason.startswith(ZONE_SWITCH_FORCED_BY_FLOOR)


def test_a_candidate_that_is_also_below_the_floor_is_not_worth_switching_to():
    policy = ZoneHandoverPolicy(min_zone_dwell_seconds=60.0)
    policy.confirm_zone("zone-a", at=100.0)

    decision = feed(policy, 0.1, [PeerObservation("b1", 0.2, "zone-b")],
                    start=101.0, count=5)

    assert decision.switch_to_zone is None
    assert decision.zone_reason == ZONE_NO_CANDIDATE


# --- 모르는 구역·같은 구역 -----------------------------------------------------


def test_a_peer_whose_zone_is_unknown_is_never_a_zone_switch_target():
    """모르는 구역으로 넘어가면 어떤 구성을 적용해야 하는지도 모른다."""
    policy = seated(ZoneHandoverPolicy())

    decision = feed(policy, 0.3, [PeerObservation("x1", 0.99)], count=10, start=100.0)

    assert decision.switch_to_zone is None
    assert decision.zone_reason == ZONE_NO_CANDIDATE


def test_a_better_peer_in_the_same_zone_is_still_handled_by_the_existing_policy():
    """구역 전환이 아니라 피어 교체는 기존 `LinkTransitionPolicy`가 판정한다."""
    policy = seated(ZoneHandoverPolicy())

    decision = policy.observe(
        LinkSample(100.0, 0.6, "a1", "zone-a"),
        [PeerObservation("a2", 0.9, "zone-a")],
    )

    assert decision.switch_to_peer == "a2"
    assert decision.switch_to_zone is None


def test_a_neighbouring_zone_peer_cannot_win_the_narrow_intra_zone_margin():
    """다른 구역 후보를 같은 구역 후보와 섞으면 구역 전환이 좁은 여유로 결정된다."""
    policy = seated(ZoneHandoverPolicy())

    decision = policy.observe(
        LinkSample(100.0, 0.6, "a1", "zone-a"),
        [PeerObservation("b1", 0.78, "zone-b")],      # 피어 여유(0.15)는 넘지만
    )

    assert decision.switch_to_peer is None            # 구역 여유(0.25)는 못 넘는다
    assert decision.switch_to_zone is None


# --- 측정 실패 (AI-C-05) --------------------------------------------------------


def test_an_unmeasurable_link_is_counted_as_unknown_not_as_bad():
    policy = seated(ZoneHandoverPolicy())
    feed(policy, 0.9, [], count=3, start=100.0)
    trend_before = policy.transition.trend()

    decision = policy.observe_unknown(200.0)

    assert decision.posture is LinkPosture.REMOTE_OK
    assert decision.zone_reason.startswith(LINK_UNKNOWN)
    assert policy.transition.trend() == trend_before   # 가짜 표본이 추세를 오염시키지 않았다


def test_repeatedly_unmeasurable_links_do_eventually_stop_remote_reliance():
    policy = seated(ZoneHandoverPolicy(unknown_tolerance=3))
    feed(policy, 0.9, [], count=3, start=100.0)

    for index in range(3):
        decision = policy.observe_unknown(200.0 + index)

    assert decision.posture is LinkPosture.LOCAL_ONLY
    assert decision.zone_reason.startswith(LINK_UNKNOWN_FORCED_LOCAL)


def test_one_real_measurement_clears_the_unknown_run():
    policy = seated(ZoneHandoverPolicy(unknown_tolerance=3))
    policy.observe_unknown(100.0)
    policy.observe_unknown(101.0)

    policy.observe(LinkSample(102.0, 0.9, "a1", "zone-a"), [])

    assert policy.status()["unmeasured_run"] == 0


# --- 신호 분리·이름 비유출 -------------------------------------------------------


def test_zone_handover_is_reported_as_its_own_signal():
    policy = seated(ZoneHandoverPolicy())

    status = policy.status()

    assert status["signal"] == "zone_handover"
    assert status["zone_id"] == "zone-a"


def test_no_radio_standard_or_metric_name_is_hardcoded():
    """AI-N-03: 특정 무선 규격·지표가 핵심 판단에 나타나면 안 된다."""
    body = inspect.getsource(zone_handover).split('"""', 2)[-1].lower()
    for term in ("rssi", "wifi", "wi-fi", "dbm", "snr", "802.11", "lte", "5g", "bssid"):
        assert term not in body, f"{term} leaked into the zone decision"


# --- 실제 주행 RSSI 기록으로의 검증 ----------------------------------------------

needs_dataset = pytest.mark.skipif(
    not DATASET.exists(), reason=f"link-quality dataset not present at {DATASET}"
)


def _replay(**policy_kwargs):
    from mission_runtime.providers.rssi_link_quality import RssiTraceReplay

    zones = {"link0": "zone-a", "link1": "zone-b", "link2": "zone-c"}
    replay = RssiTraceReplay.from_csv(
        DATASET, peer_ids=("link0", "link1", "link2"), peer_zones=zones
    )
    policy = ZoneHandoverPolicy(**policy_kwargs)
    replay.follow(policy)
    return policy, len(replay)


@needs_dataset
def test_hysteresis_cuts_boundary_flapping_on_a_real_driving_trace():
    """같은 입력, 같은 코드, 히스테리시스만 끈 비교.

    zenodo:1219249 garden_1(402 표본, 30m 주행)에서 세 링크를 서로 다른 구역
    후보로 두고 재생하면, 여유·연속표본·체류시간을 모두 0으로 낮춘 탐욕적
    선택은 수십 번 구역을 오간다. 데이터셋에 구역 레이블이 있는 것은 아니므로
    (provider 모듈 docstring 참고) 이 숫자는 "실제 신호 변동에서 이력 조건이
    전환을 얼마나 줄이는가"의 비교값이지 현장 핸드오버 횟수의 추정이 아니다.
    """
    damped, samples = _replay()
    greedy, _ = _replay(
        zone_switch_margin=0.0, zone_hold_samples=1,
        min_zone_dwell_seconds=0.0, return_penalty=0.0,
    )

    assert samples > 300
    assert greedy.zone_changes > 20
    assert greedy.zone_returns > 10                  # 대부분이 왔다 갔다 한 것이다
    assert damped.zone_changes <= 5
    assert damped.zone_returns == 0
    assert damped.zone_changes * 5 < greedy.zone_changes


@needs_dataset
def test_reduction_starts_well_before_the_real_decline_reaches_the_floor():
    """AI-N-03: 완전 단절 후 대응하면 이미 기능이 중단돼 있다.

    같은 주행 기록의 하강 구간(-42 → -63dBm)을, 그 구간을 실제로 바닥까지
    끌고 내려가는 환산표로 재생한다. 환산 기준점이 데이터가기 때문에 가능한
    시험이다 — 환산식이 코드에 박혀 있었다면 이 배포 조건을 표현할 수 없다.
    """
    from mission_runtime.providers.rssi_link_quality import (
        RssiQualityMapping,
        RssiTraceReplay,
    )

    replay = RssiTraceReplay.from_csv(
        DATASET, peer_ids=("link0", "link1", "link2"),
        peer_zones={"link0": "zone-a"},
        mapping=RssiQualityMapping(excellent_dbm=-40.0, floor_dbm=-60.0),
    )
    policy = ZoneHandoverPolicy()
    first_reduction = None
    first_floor = None
    for step in replay.steps(attached_to="link0"):
        decision = policy.observe(step.sample, list(step.peers))
        if first_reduction is None and decision.posture is LinkPosture.REDUCING:
            first_reduction = step.sample
        if first_floor is None and step.sample.quality <= policy.transition.floor:
            first_floor = step.sample

    assert first_reduction is not None and first_floor is not None
    assert first_reduction.quality > policy.transition.floor   # 아직 쓸 수 있을 때 줄였다
    assert first_floor.at - first_reduction.at > 5.0           # 실측 여유: 약 8.4초


def test_every_zone_handover_reason_is_in_the_dictionary_vocabulary():
    from mission_runtime.contracts import data_dictionary as dd

    assert set(zone_handover.ZONE_HANDOVER_REASONS) <= set(dd.ZONE_HANDOVER_REASONS)
