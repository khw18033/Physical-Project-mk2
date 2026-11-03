"""implements: AI-S-02, AI-S-04, AI-S-06
covers: appearance cannot discriminate instances, probe/marker/radio can,
        ambiguity yields a resolution request instead of a guess,
        every cue traces back to the observation it came from (AI-S-06),
        the probe and the resolver share one discrimination floor
"""

import pytest

from mission_runtime.perception.device_identity import (
    DEFAULT_DISCRIMINATING_MIN_STRENGTH,
    DISCRIMINATING_CUES,
    REQUEST_ATTACH_FIDUCIAL,
    REQUEST_ENABLE_RADIO_RANGING,
    REQUEST_MOTION_PROBE,
    PROBE_NO_MOTION,
    PROBE_SEVERAL_MOVED,
    PROBE_WINDOW_MISMATCH,
    CueKind,
    DeviceIdentityResolver,
    IdentityCue,
    TrackMotion,
    Verdict,
    appearance_cue,
    declared_placement_cue,
    expected_range_m,
    fiducial_cue,
    motion_probe,
    radio_range_cue,
)


def resolver():
    return DeviceIdentityResolver()


def appearance_only():
    """같은 기종 두 대가 보이고 외형·선언만 있는 상태."""
    cues = list(appearance_cue(["go1-a", "go1-b"], observed_at=1.0, source="pi6",
                               confidence=0.92, robot_class="quadruped"))
    cues.append(declared_placement_cue("go1-a", observed_at=0.0, zone_id="z1"))
    cues.append(declared_placement_cue("go1-b", observed_at=0.0, zone_id="z1"))
    return cues


# --- 식별력의 구조 ----------------------------------------------------------


def test_appearance_and_declaration_are_not_discriminating():
    assert CueKind.APPEARANCE_CLASS not in DISCRIMINATING_CUES
    assert CueKind.DECLARED_PLACEMENT not in DISCRIMINATING_CUES


def test_probe_marker_and_radio_are_discriminating():
    assert DISCRIMINATING_CUES == {
        CueKind.RADIO_RANGE, CueKind.MOTION_CORRELATION, CueKind.FIDUCIAL_MARKER}


def test_appearance_cue_is_given_to_every_candidate_of_that_class():
    """외형이 개체를 가리지 못한다는 사실의 코드상 표현 — 한 명에게만 주면 가린 척이 된다."""
    cues = appearance_cue(["a", "b", "c"], observed_at=1.0, source="cam",
                          confidence=0.8, robot_class="quadruped")

    assert sorted(cue.device_id for cue in cues) == ["a", "b", "c"]


# --- 모호하면 추측하지 않는다 ------------------------------------------------


def test_same_appearance_without_a_discriminating_cue_is_ambiguous():
    out = resolver().resolve("track-1", appearance_only())

    assert out.verdict is Verdict.AMBIGUOUS
    assert out.device_id is None
    assert out.bound is False


def test_ambiguity_names_what_would_resolve_it():
    out = resolver().resolve("track-1", appearance_only())

    assert out.resolution_requests == (
        REQUEST_MOTION_PROBE, REQUEST_ATTACH_FIDUCIAL, REQUEST_ENABLE_RADIO_RANGING)


def test_many_weak_cues_never_outrank_one_discriminating_cue():
    """점수만 합치면 외형 단서 여러 개가 식별 단서 하나를 이긴다 — 그래서 점수가
    아니라 구조로 가른다."""
    cues = appearance_only()
    for index in range(10):  # 같은 외형 단서를 열 번 더 받아도
        cues.extend(appearance_cue(["go1-a"], observed_at=1.0 + index, source=f"cam{index}",
                                   confidence=1.0, robot_class="quadruped"))
    cues.append(fiducial_cue("go1-b", observed_at=2.0, marker_id="m7", source="pi6",
                             pixel_size=40.0))

    out = resolver().resolve("track-1", cues)

    assert out.verdict is Verdict.CONFIRMED
    assert out.device_id == "go1-b"


def test_repeated_identical_cues_do_not_accumulate_into_discrimination():
    """같은 프레임을 두 번 보낸 것이 두 배의 근거가 되면 중복 관측이 식별력을 만든다."""
    once = resolver().resolve("t", appearance_cue(["a"], observed_at=1.0, source="cam",
                                                  confidence=0.9, robot_class="q"))
    twice_cues = list(appearance_cue(["a"], observed_at=1.0, source="cam",
                                     confidence=0.9, robot_class="q"))
    twice_cues += appearance_cue(["a"], observed_at=1.1, source="cam",
                                 confidence=0.9, robot_class="q")
    twice = resolver().resolve("t", twice_cues)

    assert once.candidates[0].score == pytest.approx(twice.candidates[0].score)


def test_a_single_candidate_without_a_discriminating_cue_is_not_confirmed():
    out = resolver().resolve("track-1", appearance_cue(
        ["only-one"], observed_at=1.0, source="cam", confidence=0.95, robot_class="q"))

    assert out.verdict is Verdict.SOLE_CANDIDATE
    assert out.bound is False, "약한 상태를 명령 대상으로 통과시키지 않는다"


def test_no_cue_at_all_is_reported_as_no_candidate():
    out = resolver().resolve("track-1", [])

    assert out.verdict is Verdict.NO_CANDIDATE
    assert REQUEST_MOTION_PROBE in out.resolution_requests


# --- 운동 프로브 ------------------------------------------------------------


def test_probe_confirms_the_only_track_that_moved():
    outcome = motion_probe("go1-a",
                           [TrackMotion("t1", 0.8, 10.0, 12.0),
                            TrackMotion("t2", 0.02, 10.0, 12.0)],
                           commanded_at=10.0, window_s=3.0,
                           expected_min_m=0.25, margin_m=0.3)

    assert outcome.discriminated is True
    out = resolver().resolve("t1", appearance_only() + [outcome.cues["t1"]])
    assert (out.verdict, out.device_id) == (Verdict.CONFIRMED, "go1-a")


def test_probe_refuses_to_pick_when_several_tracks_moved_alike():
    outcome = motion_probe("go1-a",
                           [TrackMotion("t1", 0.80, 10.0, 12.0),
                            TrackMotion("t2", 0.76, 10.0, 12.0)],
                           commanded_at=10.0, window_s=3.0,
                           expected_min_m=0.25, margin_m=0.3)

    assert outcome.reason == PROBE_SEVERAL_MOVED
    assert outcome.discriminated is False
    assert resolver().resolve("t1", appearance_only() + [outcome.cues["t1"]]).verdict \
        is Verdict.AMBIGUOUS


def test_probe_reports_no_motion_rather_than_picking_the_largest_jitter():
    outcome = motion_probe("go1-a", [TrackMotion("t1", 0.04, 10.0, 12.0)],
                           commanded_at=10.0, window_s=3.0,
                           expected_min_m=0.25, margin_m=0.3)

    assert outcome.reason == PROBE_NO_MOTION
    assert outcome.cues == {}


def test_motion_outside_the_window_is_not_credited_to_the_command():
    outcome = motion_probe("go1-a", [TrackMotion("t1", 2.0, 100.0, 102.0)],
                           commanded_at=10.0, window_s=3.0,
                           expected_min_m=0.25, margin_m=0.3)

    assert outcome.reason == PROBE_WINDOW_MISMATCH


# --- 마커·무선 -------------------------------------------------------------


def test_a_marker_too_small_to_read_does_not_discriminate():
    small = fiducial_cue("go1-b", observed_at=2.0, marker_id="m7", source="pi6",
                         pixel_size=6.0)

    assert resolver().resolve("t", appearance_only() + [small]).verdict is Verdict.AMBIGUOUS


def test_radio_ranges_that_fit_both_candidates_stay_ambiguous():
    near_a = radio_range_cue("go1-a", observed_at=2.0, measured_m=5.0,
                             expected_m=5.2, tolerance_m=2.0)
    near_b = radio_range_cue("go1-b", observed_at=2.0, measured_m=5.1,
                             expected_m=5.2, tolerance_m=2.0)

    out = resolver().resolve("t", appearance_only() + [near_a, near_b])

    assert out.verdict is Verdict.AMBIGUOUS
    assert set(out.conflicting_device_ids) == {"go1-a", "go1-b"}


def test_radio_range_out_of_tolerance_scores_zero_rather_than_a_weak_match():
    cue = radio_range_cue("go1-b", observed_at=2.0, measured_m=18.0,
                          expected_m=5.2, tolerance_m=2.0)

    assert cue.strength == 0.0


def test_expected_range_is_plain_local_distance():
    assert expected_range_m((0.0, 0.0), (3.0, 4.0)) == pytest.approx(5.0)


def test_cue_strength_outside_zero_to_one_is_rejected():
    with pytest.raises(ValueError):
        IdentityCue(CueKind.FIDUCIAL_MARKER, "a", 1.4, 1.0)


# --- 근거는 자기 원본 관측을 들고 다닌다 (AI-S-06) ---------------------------


def test_a_cue_carries_the_observation_it_was_made_from():
    """AI-S-06: "각 근거는 생산자, 원본 관측, 생성·완료 시점과 필요한 출처 정보를
    추적할 수 있어야." 출처 묶음(`source`)만으로는 **무엇을 보고** 냈는지가 없다."""
    marker = fiducial_cue("go1-b", observed_at=2.0, marker_id="m7", source="pi6",
                          pixel_size=40.0, frame_ref="frame:pi6:1001")
    ranged = radio_range_cue("go1-a", observed_at=2.0, measured_m=5.0, expected_m=5.0,
                             tolerance_m=2.0, frame_ref="radio_sweep:88")
    seen = appearance_cue(["go1-a", "go1-b"], observed_at=1.0, source="pi6",
                          confidence=0.9, robot_class="quadruped",
                          frame_ref="frame:pi6:1001")

    assert marker.frame_ref == "frame:pi6:1001"
    assert ranged.frame_ref == "radio_sweep:88"
    # 한 프레임에서 나온 외형 단서들은 같은 원본을 가리킨다 — 그래야 소비자가 "이
    # 둘은 한 번 본 것"임을 셀 수 있다.
    assert {cue.frame_ref for cue in seen} == {"frame:pi6:1001"}


def test_an_unknown_origin_stays_empty_rather_than_being_invented():
    """원본 참조를 못 주는 호출자도 있다. 비어 있는 것이 지어낸 값보다 낫다."""
    assert fiducial_cue("go1-b", observed_at=2.0, marker_id="m7", source="pi6",
                        pixel_size=40.0).frame_ref == ""


def test_the_resolution_payload_keeps_each_cue_origin():
    out = resolver().resolve("t", [fiducial_cue(
        "go1-b", observed_at=2.0, marker_id="m7", source="pi6", pixel_size=40.0,
        frame_ref="frame:pi6:1001")])

    payload = out.as_dict()["candidates"][0]["cues"][0]
    assert payload["frame_ref"] == "frame:pi6:1001"


def test_the_probe_cue_names_the_probe_round_it_came_from():
    outcome = motion_probe("go1-a", [TrackMotion("t1", 0.8, 10.0, 12.0)],
                           commanded_at=10.0, window_s=3.0, expected_min_m=0.25,
                           margin_m=0.3, frame_ref="probe:go1-a@10.0")

    assert outcome.cues["t1"].frame_ref == "probe:go1-a@10.0"
    assert outcome.as_dict()["cues"]["t1"]["frame_ref"] == "probe:go1-a@10.0"


# --- 임계값은 한 곳에서만 선언된다 -------------------------------------------


def test_the_probe_reads_its_discrimination_floor_from_the_resolver():
    """프로브가 "가렸다"고 말하는 기준과 resolver 가 확정하는 기준이 **같은 숫자**여야
    한다. 각자 적으면 한쪽만 조정한 날 프로브는 가렸다고 하고 판정은 모호하다고 한다."""
    tuned = DeviceIdentityResolver(discriminating_min_strength=0.9)
    outcome = motion_probe("go1-a", [TrackMotion("t1", 0.15, 10.0, 12.0)],
                           commanded_at=10.0, window_s=3.0, expected_min_m=0.1,
                           margin_m=0.3, resolver=tuned)

    assert outcome.cues["t1"].strength == pytest.approx(0.5)   # 0.35 < 0.5 < 0.9
    assert outcome.min_strength == 0.9
    assert outcome.discriminated is False
    # 두 자리가 같은 답을 한다.
    assert tuned.resolve("t1", appearance_only() + [outcome.cues["t1"]]).verdict \
        is Verdict.AMBIGUOUS


def test_the_default_floor_is_the_one_the_resolver_declares():
    assert DeviceIdentityResolver().discriminating_min_strength \
        == DEFAULT_DISCRIMINATING_MIN_STRENGTH
    outcome = motion_probe("go1-a", [TrackMotion("t1", 0.8, 10.0, 12.0)],
                           commanded_at=10.0, window_s=3.0, expected_min_m=0.25,
                           margin_m=0.3)
    assert outcome.min_strength == DEFAULT_DISCRIMINATING_MIN_STRENGTH
