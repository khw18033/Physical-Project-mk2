"""implements: AI-E-02

조사 문서 §7.2 — 기존 보정이 더 이상 현실을 설명하지 않는 것을 누가 알아채는가.

이 파일이 고정하는 중심 성질은 **축이 합쳐지지 않는 것**이다(Moravec & Šára 의
monitoring/tracking 구분). 느린 축(윈도 지속)과 빠른 축(직전 대비 급변)이 같은 관측을
읽지만 서로 다른 임계값과 서로 다른 긴급도로 읽는다 — 하나로 합치면 둘 다 늦는다.
"""

import numpy as np
import pytest

from mission_runtime.edge.calibration import CalibrationEstimate
from mission_runtime.edge.calibration_monitor import (
    EVIDENCE_BASES,
    RECALIBRATION_SIGNAL_KINDS,
    CalibrationMonitor,
    RecalibrationSignal,
    immediate_signals,
)
from mission_runtime.edge.calibration_profile import (
    ApplicabilityScope,
    CalibrationProfileStore,
)
from mission_runtime.edge.calibration_transfer import InputTransform

_SCOPE = ApplicabilityScope("cam_a", (640, 480))


def _profile(*, valid: bool = True, valid_until: float | None = None):
    store = CalibrationProfileStore(camera_id="cam_a")
    return store.submit(
        CalibrationEstimate(np.eye(3), np.zeros(5), 0.4, valid),
        validated=valid, applicability=_SCOPE, method_id="planar_target",
        valid_until=valid_until,
    )


def _kinds(signals) -> set[str]:
    return {s.kind for s in signals}


# -- 없는 것과 나쁜 것 ---------------------------------------------------------


def test_a_healthy_profile_with_no_observations_produces_no_signals():
    """빈 묶음이 정상 상태다(AI-C-05)."""
    monitor = CalibrationMonitor("cam_a")

    assert monitor.signals(profile=_profile()) == ()
    assert monitor.due(profile=_profile()) is False


def test_no_profile_is_its_own_reason_and_suppresses_the_validity_axes():
    """없는 보정이 "틀렸다" 고 말하면 사유가 두 번 세어진다."""
    monitor = CalibrationMonitor("cam_a")
    for _ in range(10):
        monitor.observe_anchor_reprojection(9.0)
    monitor.observe_known_size(1.0, 2.0)

    signals = monitor.signals(profile=None)

    assert _kinds(signals) == {"no_profile"}
    assert signals[0].evidence_basis == "requirement"


def test_an_invalid_profile_is_treated_as_no_profile():
    monitor = CalibrationMonitor("cam_a")

    assert _kinds(monitor.signals(profile=_profile(valid=False))) == {"no_profile"}


# -- 두 축이 같은 관측을 다르게 읽는다 ----------------------------------------


def test_a_single_spike_does_not_trigger_the_slow_axis():
    """"한 프레임의 튐으로 재보정을 걸지 않는다"(문서 §7.2)."""
    monitor = CalibrationMonitor("cam_a", drift_threshold_px=2.0, drift_persistence=7)
    for error in (0.4, 0.5, 0.4, 0.6, 0.5):
        monitor.observe_anchor_reprojection(error)
    monitor.observe_anchor_reprojection(3.0)

    assert "anchor_reprojection_drift" not in _kinds(monitor.signals(profile=_profile()))


def test_persistent_excess_over_the_window_triggers_the_slow_axis_as_scheduled():
    monitor = CalibrationMonitor("cam_a", drift_threshold_px=2.0, drift_persistence=7)
    for _ in range(8):
        monitor.observe_anchor_reprojection(3.0)

    signals = [s for s in monitor.signals(profile=_profile())
               if s.kind == "anchor_reprojection_drift"]

    assert len(signals) == 1
    assert signals[0].urgency == "scheduled"
    assert signals[0].evidence_basis == "literature_transferred"
    assert signals[0].measurements["exceeding"] == 8.0
    assert signals[0].measurements["threshold_px"] == 2.0


def test_an_abrupt_jump_triggers_the_fast_axis_immediately_from_one_frame():
    """Moravec 의 LTO 축 — 장착 교란 직후 한 프레임으로 울려야 한다."""
    monitor = CalibrationMonitor("cam_a", abrupt_jump_px=6.0)
    for error in (0.4, 0.5, 0.4):
        monitor.observe_anchor_reprojection(error)
    monitor.observe_anchor_reprojection(12.0)

    signals = [s for s in monitor.signals(profile=_profile())
               if s.kind == "abrupt_reprojection_jump"]

    assert len(signals) == 1
    assert signals[0].urgency == "immediate"
    assert signals[0].measurements["jump_px"] == pytest.approx(11.6)
    # 느린 축은 아직 울리지 않는다 — 윈도 안에 한 건뿐이다.
    assert "anchor_reprojection_drift" not in _kinds(monitor.signals(profile=_profile()))


def test_the_two_axes_use_different_thresholds_and_do_not_share_state():
    """느린 축만 울리는 입력과 빠른 축만 울리는 입력이 모두 존재해야 분리가 사실이다."""
    slow = CalibrationMonitor("cam_a", drift_threshold_px=2.0, drift_persistence=7,
                              abrupt_jump_px=6.0)
    for _ in range(8):
        slow.observe_anchor_reprojection(3.0)

    fast = CalibrationMonitor("cam_a", drift_threshold_px=2.0, drift_persistence=7,
                              abrupt_jump_px=6.0)
    fast.observe_anchor_reprojection(0.4)
    fast.observe_anchor_reprojection(9.0)

    assert _kinds(slow.signals(profile=_profile())) == {"anchor_reprojection_drift"}
    assert _kinds(fast.signals(profile=_profile())) == {"abrupt_reprojection_jump"}


def test_both_axes_can_fire_and_stay_separate_facts():
    monitor = CalibrationMonitor("cam_a", drift_threshold_px=2.0, drift_persistence=7,
                                 abrupt_jump_px=6.0)
    monitor.observe_anchor_reprojection(0.5)
    monitor.observe_anchor_reprojection(9.0)
    for _ in range(8):
        monitor.observe_anchor_reprojection(9.0)

    kinds = _kinds(monitor.signals(profile=_profile()))

    assert kinds == {"anchor_reprojection_drift", "abrupt_reprojection_jump"}


def test_a_reported_mount_disturbance_clears_the_history_rather_than_signalling():
    """교란 자체는 신호가 아니다 — 신호는 교란 뒤의 관측이 낸다."""
    monitor = CalibrationMonitor("cam_a", drift_threshold_px=2.0, drift_persistence=7)
    for _ in range(8):
        monitor.observe_anchor_reprojection(3.0)
    assert "anchor_reprojection_drift" in _kinds(monitor.signals(profile=_profile()))

    monitor.note_mount_disturbance()

    assert monitor.signals(profile=_profile()) == ()


def test_negative_or_non_finite_errors_are_rejected_at_the_input():
    monitor = CalibrationMonitor("cam_a")

    with pytest.raises(ValueError):
        monitor.observe_anchor_reprojection(-1.0)
    with pytest.raises(ValueError):
        monitor.observe_anchor_reprojection(float("nan"))


# -- 범위 밖은 품질 저하가 아니다 ----------------------------------------------


def test_an_out_of_scope_input_condition_is_a_different_reason_and_immediate():
    """보정이 나빠진 게 아니라 **다른 조건의 보정**이 됐다(문서 §7.1)."""
    monitor = CalibrationMonitor("cam_a")

    signals = monitor.signals(
        profile=_profile(), current_scope=ApplicabilityScope("cam_a", (320, 240))
    )

    assert _kinds(signals) == {"input_condition_out_of_scope"}
    assert signals[0].urgency == "immediate"
    assert "transform_not_declared" in signals[0].detail


def test_a_declared_convertible_resize_does_not_demand_reestimation():
    """환산 가능한 변화에 재보정 신호를 내면 멀쩡한 보정을 버리게 된다."""
    monitor = CalibrationMonitor("cam_a")

    signals = monitor.signals(
        profile=_profile(),
        current_scope=ApplicabilityScope("cam_a", (320, 240)),
        input_transform=InputTransform("resize"),
    )

    assert signals == ()


def test_a_zoom_change_demands_reestimation_even_when_a_transform_is_declared():
    monitor = CalibrationMonitor("cam_a")

    signals = monitor.signals(
        profile=_profile(),
        current_scope=ApplicabilityScope("cam_a", (640, 480), zoom_token="3x"),
        input_transform=InputTransform("resize"),
    )

    assert _kinds(signals) == {"input_condition_out_of_scope"}
    assert "zoom_token_changed" in signals[0].detail


# -- 나머지 축 ----------------------------------------------------------------


def test_expiry_is_an_operational_policy_not_a_literature_claim():
    monitor = CalibrationMonitor("cam_a")
    profile = _profile(valid_until=1000.0)

    assert monitor.signals(profile=profile, now=999.0) == ()
    expired = monitor.signals(profile=profile, now=1001.0)
    assert _kinds(expired) == {"calibration_expired"}
    assert expired[0].evidence_basis == "operational_policy"


def test_a_profile_without_a_deadline_never_expires():
    assert CalibrationMonitor("cam_a").signals(profile=_profile(), now=1e12) == ()


def test_a_known_size_measured_wrong_suspects_the_scale():
    monitor = CalibrationMonitor("cam_a", known_size_error_frac=0.15)
    monitor.observe_known_size(2.0, 2.1)   # 5% — 통과
    monitor.observe_known_size(2.0, 2.8)   # 40% — 초과

    signals = [s for s in monitor.signals(profile=_profile())
               if s.kind == "known_size_mismeasured"]

    assert len(signals) == 1
    assert signals[0].measurements["relative_error"] == pytest.approx(0.4)
    assert signals[0].measurements["sample_count"] == 2.0
    assert signals[0].measurements["exceeding_count"] == 1.0


def test_known_size_needs_a_positive_expectation():
    with pytest.raises(ValueError):
        CalibrationMonitor("cam_a").observe_known_size(0.0, 1.0)


def test_cross_camera_disagreement_declares_that_its_basis_is_our_structure():
    """문서 §7.2 마지막 줄 — 이 축의 선행 연구를 **찾지 못했다**. 그 사실이 신호에 적힌다."""
    monitor = CalibrationMonitor("cam_a", cross_camera_disagreement_m=1.0)
    monitor.observe_cross_camera_disagreement("cam_b", 0.3)
    monitor.observe_cross_camera_disagreement("cam_c", 2.4)

    signals = [s for s in monitor.signals(profile=_profile())
               if s.kind == "cross_camera_disagreement"]

    assert len(signals) == 1
    assert signals[0].evidence_basis == "project_structure"
    assert signals[0].measurements["disagreement_m"] == pytest.approx(2.4)
    assert "cam_c" in signals[0].detail


def test_resetting_after_an_actual_recalibration_clears_every_axis():
    monitor = CalibrationMonitor("cam_a", drift_threshold_px=2.0, drift_persistence=7)
    for _ in range(8):
        monitor.observe_anchor_reprojection(3.0)
    monitor.observe_known_size(1.0, 2.0)
    monitor.observe_cross_camera_disagreement("cam_b", 5.0)
    assert len(monitor.signals(profile=_profile())) == 3

    monitor.reset_observations()

    assert monitor.signals(profile=_profile()) == ()


# -- 어휘와 긴급도 -------------------------------------------------------------


def test_every_signal_kind_is_reachable_and_registered():
    reached = {"no_profile", "calibration_expired", "input_condition_out_of_scope",
               "anchor_reprojection_drift", "abrupt_reprojection_jump",
               "known_size_mismeasured", "cross_camera_disagreement"}

    assert reached == set(RECALIBRATION_SIGNAL_KINDS)


def test_unregistered_kinds_urgencies_and_bases_are_refused_at_construction():
    with pytest.raises(ValueError):
        RecalibrationSignal("cam_a", "vibes_are_off", "immediate", "requirement")
    with pytest.raises(ValueError):
        RecalibrationSignal("cam_a", "no_profile", "whenever", "requirement")
    with pytest.raises(ValueError):
        RecalibrationSignal("cam_a", "no_profile", "immediate", "a_hunch")


def test_immediate_signals_are_separable_for_the_event_path():
    """치명 사건은 일반 요약 주기를 기다리지 않는다(AI-O-02)."""
    monitor = CalibrationMonitor("cam_a", drift_threshold_px=2.0, drift_persistence=7,
                                 abrupt_jump_px=6.0)
    monitor.observe_anchor_reprojection(0.5)
    monitor.observe_anchor_reprojection(9.0)
    for _ in range(8):
        monitor.observe_anchor_reprojection(9.0)

    signals = monitor.signals(profile=_profile())

    assert _kinds(immediate_signals(signals)) == {"abrupt_reprojection_jump"}
    assert len(signals) == 2


def test_signals_serialize_without_pixels_or_objects():
    monitor = CalibrationMonitor("cam_a")
    signal = monitor.signals(profile=None)[0]

    payload = signal.as_dict()

    assert payload["camera_id"] == "cam_a"
    assert payload["kind"] == "no_profile"
    assert set(payload) == {"camera_id", "kind", "urgency", "evidence_basis",
                            "measurements", "detail"}
    assert payload["evidence_basis"] in EVIDENCE_BASES


def test_the_monitor_never_reads_a_clock_itself():
    """같은 입력에 같은 신호가 나와야 거부 사유를 재현할 수 있다."""
    monitor = CalibrationMonitor("cam_a")
    profile = _profile(valid_until=1000.0)

    # now 를 주지 않으면 기한 축은 **수행되지 않는다** — 통과가 아니다.
    assert monitor.signals(profile=profile) == ()
