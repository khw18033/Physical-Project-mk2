"""implements: AI-E-01, AI-S-02, AI-S-03, AI-S-04

여기서 검증하는 것은 "추정이 맞는가"보다 먼저 **틀릴 수 있는 상황에서 무엇을 하는가**
다: 외형이 틀리게 확신할 때, 단서가 서로 다른 기종을 가리킬 때, 아무 단서도 없을 때,
등록되지 않은 종류가 들어올 때. 네 경우 모두 예외도 추측도 아니어야 한다.

점수 계산은 공개 트리의 실제 사전(config/device_appearance_classes.example.json)에
실린 **진짜 CLIP 벡터와 진짜 프로파일**로 돌린다 — 지어낸 값으로 재면 사전에 적힌
임계값이 맞는지는 영영 알 수 없다.
"""

import json
from dataclasses import replace

import pytest

from conftest import PACKAGE_DIR
from mission_runtime.contracts.data_dictionary import (
    CONTRIBUTIONS,
    LEAVE_ONE_OUT,
    SEMANTIC_CLASS,
    UNOBSERVED_EVIDENCE_KINDS,
)
from mission_runtime.perception.appearance_classifier import (
    AppearanceClassifier,
    AppearanceDictionary,
    AppearanceState,
)
from mission_runtime.perception.device_class_estimator import (
    DEFAULT_CUE_KINDS,
    KIND_ANNOUNCED_ACTIONS,
    KIND_APPEARANCE,
    KIND_MOTION,
    KIND_RESOURCE_TAGS,
    REASON_NO_CUE,
    REASON_NO_PROFILE,
    REQUEST_REGISTER_TAGS,
    ClassCue,
    ClassCueSpec,
    ClassProfile,
    ClassProfiles,
    ClassState,
    DeviceClassEstimator,
    announced_action_cue,
    apparent_size_cue,
    apparent_size_m,
    appearance_cue,
    declared_zone_cue,
    motion_cue,
    resource_tag_cue,
)

DICTIONARY_PATH = PACKAGE_DIR / "config" / "device_appearance_classes.example.json"


@pytest.fixture(scope="module")
def profiles() -> ClassProfiles:
    return ClassProfiles.load(DICTIONARY_PATH)


@pytest.fixture
def estimator(profiles) -> DeviceClassEstimator:
    return DeviceClassEstimator(profiles)


@pytest.fixture(scope="module")
def dictionary() -> AppearanceDictionary:
    return AppearanceDictionary.load(DICTIONARY_PATH)


def _appearance(class_name: str, *, score: float = 0.9, runner_up: str | None = None,
                runner_score: float = 0.6, state=AppearanceState.CLASSIFIED) -> ClassCue:
    """외형 단서 하나를 손으로 만든다. 지지 점수는 코사인 유사도 자리를 그대로 쓴다."""
    from mission_runtime.perception.appearance_classifier import (
        AppearanceVerdict,
        ClassScore,
    )

    ranked = [ClassScore(class_name, class_name, score, (), 0)]
    if runner_up:
        ranked.append(ClassScore(runner_up, runner_up, runner_score, (), 0))
    verdict = AppearanceVerdict(
        state, class_name if state is AppearanceState.CLASSIFIED else None,
        "test", tuple(ranked),
        margin=None if len(ranked) < 2 else score - runner_score)
    return appearance_cue(verdict, observed_at=1.0)


# --- 없는 것이 정상인 상태 ---------------------------------------------------


def test_an_estimator_without_profiles_degrades_instead_of_raising(tmp_path):
    """프로파일을 적지 않은 배치는 추정만 비활성이고 기동은 막히지 않는다(AI-C-05)."""
    empty = ClassProfiles.load(tmp_path / "nothing.json")

    estimate = DeviceClassEstimator(empty).estimate([_appearance("go1")])

    assert estimate.state is ClassState.NO_CUE
    assert estimate.reason == REASON_NO_PROFILE
    assert estimate.device_class is None
    assert estimate.classified is False


def test_no_cue_at_all_is_a_state_and_asks_for_what_would_help(estimator):
    estimate = estimator.estimate([])

    assert estimate.state is ClassState.NO_CUE
    assert estimate.reason == REASON_NO_CUE
    # 무엇을 더 하면 풀리는지를 낸다. 실행은 다른 파트가 한다(AI-S-05, AI-C-19).
    assert REQUEST_REGISTER_TAGS in estimate.resolution_requests


def test_a_silent_cue_is_never_evidence_against_anything(estimator, profiles):
    """거리가 없고 운동이 없는 것은 **침묵**이지 반대 근거가 아니다(규칙 2)."""
    silent_size = apparent_size_cue(None, profiles, observed_at=1.0)
    silent_motion = motion_cue(None, profiles, observed_at=1.0)
    assert silent_size.silent and silent_motion.silent

    alone = estimator.estimate([_appearance("go1")])
    with_silence = estimator.estimate([_appearance("go1"), silent_size, silent_motion])

    assert with_silence.state is alone.state
    assert with_silence.device_class == alone.device_class
    # 침묵한 종류는 숨지 않고 "관측되지 않음"으로 드러난다.
    assert "apparent_size" in with_silence.explanation()[UNOBSERVED_EVIDENCE_KINDS]


def test_standing_still_is_not_evidence_of_being_a_fixed_device(estimator, profiles):
    """대기 중인 로봇도 가만히 있다. 작은 변위로 고정 기종을 지지하면 안 된다."""
    cue = motion_cue(0.01, profiles, observed_at=1.0)

    assert cue.silent is True
    assert cue.detail["reason"] == "standing_still_is_not_evidence_of_being_fixed"
    assert cue.excludes == {}


# --- 가리지 못하는 단서가 판정하지 못한다 ------------------------------------


def test_three_supporting_cues_cannot_outvote_one_decisive_exclusion(estimator, profiles):
    """외형·구역이 아무리 지지해도 **배제된 기종은 돌아오지 않는다**(규칙 1).

    점수를 한 줄로 더하면 이 시험은 통과하지 못한다 — 그것이 이 모듈이 격을 타입에
    남기는 이유다.
    """
    estimate = estimator.estimate([
        _appearance("insta360", score=0.95),
        declared_zone_cue("zone-a", profiles, observed_at=1.0),
        # 이 노드는 UAV 태그를 달고 조인했다. insta360 은 같은 가족의 다른 태그를
        # 선언했으므로 그 기종일 수 없다.
        resource_tag_cue(["tier.uav", "platform.uav", "sensor.gps"], profiles, observed_at=1.0),
    ])

    assert "insta360" in estimate.excluded_classes
    assert estimate.device_class != "insta360"
    row = next(r for r in estimate.ranked if r.class_name == "insta360")
    assert row.excluded is True
    # 배제됐어도 외형이 얼마나 지지했는지는 남는다 — 지우면 왜 무시됐는지를 못 되짚는다.
    assert row.supporting_score > 0.0


def test_an_announced_takeoff_excludes_the_bench_manipulator(estimator, profiles):
    """`takeoff` 를 공지한 장치는 책상에 고정된 매니퓰레이터가 아니다.

    배치에 실린 네 기종 모두 어휘를 **완전하다고 선언했으므로** 넷이 다 탈락하고
    쿼드콥터만 남는다. 어휘를 다 적지 않은 기종은 탈락하지 않는다는 규칙은 아래
    시험이 따로 고정한다 — 실제 기종이 덜 선언한 상태에 기대면, 그 기종의 선언이
    채워지는 순간 규칙의 시험이 함께 사라진다.
    """
    cue = announced_action_cue(["takeoff", "land", "goto_waypoint"], profiles, observed_at=1.0)

    assert cue.separated == "holybro_x500_v2"
    assert {"go1", "ep01", "insta360", "mt4"} == set(cue.excludes)


def test_a_class_that_did_not_finish_declaring_its_vocabulary_is_not_excluded(profiles):
    """모르는 것을 반대 근거로 쓰지 않는다(규칙 2). 어휘를 다 적지 않았다고 선언한
    기종은 낯선 action 이 와도 탈락하지 않고, 지지만 낮아진다."""
    partial = ClassProfile(
        class_name="half_declared", label="half declared",
        action_vocabulary=("stop",), action_vocabulary_complete=False,
        signature_tags=frozenset({"tier.ugv"}), size_m=None, mobile=True, zones=())
    with_partial = replace(profiles, profiles=(*profiles.profiles, partial))

    cue = announced_action_cue(["takeoff", "land"], with_partial, observed_at=1.0)

    assert "half_declared" not in cue.excludes
    assert cue.support["half_declared"] == 0.0
    # 완전하다고 선언한 기종은 같은 입력에서 탈락한다 — 그 차이가 이 규칙이다.
    assert "mt4" in cue.excludes


def test_a_cue_that_cannot_separate_says_so_instead_of_picking(profiles):
    """go1 과 ep01 은 역할이 같아 공지 어휘가 같다. 공지로는 둘을 가를 수 없다."""
    cue = announced_action_cue(["move_forward", "turn", "stop"], profiles, observed_at=1.0)

    assert cue.separated is None
    assert cue.tied == ("ep01", "go1")
    assert cue.support["go1"] == cue.support["ep01"] == 1.0


def test_motion_excludes_the_fixed_classes_but_supports_every_mobile_one(estimator, profiles):
    cue = motion_cue(1.4, profiles, observed_at=1.0)

    assert set(cue.excludes) == {"insta360", "mt4"}
    # 셋이 다 움직일 수 있으므로 운동은 **가르지 못한다**. 그래도 둘을 지웠다.
    assert cue.separated is None
    estimate = estimator.estimate([_appearance("mt4", score=0.93), cue])
    assert estimate.device_class != "mt4"


# --- 모순은 결과다 -----------------------------------------------------------


def test_appearance_against_the_announced_vocabulary_is_a_named_conflict(estimator, profiles):
    """외형이 insta360, 공지가 `takeoff` 면 평균하지 않고 **양쪽을 이름으로** 낸다."""
    estimate = estimator.estimate([
        _appearance("insta360", score=0.91),
        announced_action_cue(["takeoff", "land"], profiles, observed_at=1.0),
    ])

    assert estimate.state is ClassState.CONFLICTED
    # 결정적 단서 쪽을 적되 확정으로 승격하지는 않는다.
    assert estimate.device_class == "holybro_x500_v2"
    assert estimate.classified is False
    claims = {(c.kind, c.claims, c.against_kind) for c in estimate.conflicts}
    assert (KIND_APPEARANCE, "insta360", KIND_ANNOUNCED_ACTIONS) in claims


def test_two_decisive_cues_that_disagree_do_not_get_a_winner(estimator, profiles):
    """결정적 단서 둘이 다른 기종을 가리키면 그중 하나를 고르지 않는다."""
    legged = resource_tag_cue(
        ["tier.ugv", "locomotion.legged", "sensor.imu", "actuator.led_speaker"],
        profiles, observed_at=1.0)
    flying = announced_action_cue(["takeoff", "land", "goto_waypoint", "stop", "return_home"],
                                  profiles, observed_at=2.0)

    estimate = estimator.estimate([legged, flying])

    assert estimate.state is ClassState.CONFLICTED
    assert estimate.device_class is None
    assert estimate.resolution_requests  # 무엇을 더 하면 풀리는지는 남는다


def test_every_class_excluded_is_reported_rather_than_silently_empty(estimator, profiles):
    """배제가 전부를 지우면 그 사실이 결과다 — 빈 목록으로 조용히 끝나지 않는다."""
    estimate = estimator.estimate([
        # 2cm 짜리 물체. 선언된 어떤 기종의 크기 범위에도 들어가지 않는다.
        apparent_size_cue(0.02, profiles, observed_at=1.0),
    ])

    assert estimate.state is ClassState.CONFLICTED
    assert estimate.device_class is None
    assert set(estimate.excluded_classes) == set(profiles.names)


# --- 모호는 정답의 한 종류다 --------------------------------------------------


def test_nobody_separating_leaves_the_estimate_ambiguous_with_a_reason(estimator, profiles):
    """외형이 모호하고 공지도 둘을 못 가르면 고르지 않는다(AI-S-04)."""
    estimate = estimator.estimate([
        _appearance("go1", score=0.82, runner_up="ep01", runner_score=0.81,
                    state=AppearanceState.AMBIGUOUS),
        announced_action_cue(["move_forward", "turn", "stop"], profiles, observed_at=1.0),
    ])

    assert estimate.state is ClassState.AMBIGUOUS
    assert estimate.device_class is None
    # 무엇과 무엇을 못 갈랐는지가 사유에 남아야 화면이 "왜 빈칸인가"를 그릴 수 있다.
    assert "ep01,go1" in estimate.reason
    assert REQUEST_REGISTER_TAGS in estimate.resolution_requests


def test_a_tag_that_separates_resolves_what_appearance_could_not(estimator, profiles):
    """같은 모호 상황에 다리/바퀴 태그 하나가 들어오면 그것으로 갈린다.

    이것이 다중 단서의 실제 이득이다 — 외형을 더 잘 만드는 것이 아니라, 외형이
    **원래 가를 수 없는** 구간을 다른 격의 근거가 가른다.
    """
    appearance = _appearance("go1", score=0.82, runner_up="ep01", runner_score=0.81,
                             state=AppearanceState.AMBIGUOUS)
    tags = resource_tag_cue(["tier.ugv", "locomotion.wheeled", "sensor.imu", "actuator.gripper"],
                            profiles, observed_at=1.0)

    estimate = estimator.estimate([appearance, tags])

    assert estimate.state is ClassState.ESTIMATED
    assert estimate.device_class == "ep01"
    assert estimate.reason.startswith("decisive_cue_separated:")


def test_only_one_class_left_says_so_instead_of_claiming_a_cue_separated_it(
        estimator, profiles):
    """"남은 것이 하나뿐"과 "가른 단서가 있다"는 다른 일이고 사유에서 갈린다.

    `tier.ugv` 는 go1 과 ep01 을 **똑같이** 지지하고(둘 다 ugv) 나머지 셋을 배제한다.
    0.82 m 는 ep01 의 선언 범위(0.28~0.5 m)를 허용오차 밖으로 벗어나 ep01 을 배제하되,
    go1(1.0)과 x500(0.844)의 차이가 `separation_min` 에 못 미쳐 **아무것도 가르지
    못한다**. 그래서 go1 만 남지만 그것을 가른 단서는 없다.
    """
    estimate = estimator.estimate([
        resource_tag_cue(["tier.ugv"], profiles, observed_at=1.0),
        apparent_size_cue(0.82, profiles, observed_at=1.0),
    ])

    assert estimate.state is ClassState.ESTIMATED
    assert estimate.device_class == "go1"
    assert estimate.reason.startswith("only_class_left_after_exclusions:")
    # 어느 단서도 혼자 가르지 않았다는 것이 요점이다 — 가른 단서가 있었다면
    # 사유가 `decisive_cue_separated:` 였어야 한다.
    assert all(cue.separated is None for cue in estimate.cues)


def test_a_tag_and_real_movement_that_contradict_exclude_everything(estimator, profiles):
    """고정 카메라라고 등록된 장치가 2 m 를 움직였다. 둘 중 하나를 고르지 않는다.

    태그는 insta360 만 남기고 운동은 insta360 을 배제한다 — 남는 기종이 없다.
    여기서 "그래도 둘 중 하나" 를 고르면 그 선택을 한 근거가 어디에도 없다.
    """
    estimate = estimator.estimate([
        resource_tag_cue(["tier.fixed_camera"], profiles, observed_at=1.0),
        motion_cue(2.0, profiles, observed_at=1.0),
        apparent_size_cue(0.8, profiles, observed_at=1.0),
    ])

    assert estimate.state is ClassState.CONFLICTED
    assert estimate.device_class is None
    assert estimate.reason == "every_known_class_was_excluded"
    # 무엇을 하면 풀리는지를 함께 낸다(AI-S-05: 요청만 하고 실행은 다른 파트).
    assert estimate.resolution_requests


# --- 설명이 산출물이다 --------------------------------------------------------


def test_the_explanation_carries_per_cue_contributions_and_leave_one_out(
        estimator, profiles):
    estimate = estimator.estimate([
        _appearance("go1", score=0.88, runner_up="ep01", runner_score=0.70),
        resource_tag_cue(["tier.ugv", "locomotion.legged", "sensor.imu",
                          "actuator.led_speaker"], profiles, observed_at=1.0),
        motion_cue(1.1, profiles, observed_at=1.0),
    ])
    explanation = estimate.explanation()

    assert explanation[SEMANTIC_CLASS] == "go1"
    winner = next(row for row in explanation["ranked"] if row[SEMANTIC_CLASS] == "go1")
    kinds = {row["kind"] for row in winner[CONTRIBUTIONS]}
    assert {KIND_APPEARANCE, KIND_RESOURCE_TAGS, KIND_MOTION} <= kinds
    # 격이 기여마다 남아 있어야 화면이 "약한 근거가 셋"과 "결정적 근거가 하나"를
    # 다르게 그릴 수 있다.
    assert any(row["decisive"] for row in winner[CONTRIBUTIONS])
    assert any(not row["decisive"] for row in winner[CONTRIBUTIONS])

    # 단서를 하나씩 빼면 판정이 무엇이 되는가. 이것이 없으면 틀린 판정을 디버깅할
    # 방법이 없다(spatial_evidence.leave_one_out 과 같은 축).
    rows = {row["removed"]: row for row in explanation[LEAVE_ONE_OUT]}
    assert set(rows) == {KIND_APPEARANCE, KIND_RESOURCE_TAGS, KIND_MOTION}
    # 여기서는 **어느 하나를 빼도 답이 선다.** 태그가 가르고, 태그를 빼면 외형이
    # 혼자 go1 을 가른다(0.88 vs 0.70). 그 중복이 보이는 것이 이 표의 쓸모다 —
    # 전부 True 로 나오는 표는 모든 단서가 필수라는 뜻이고, 그건 다른 상황이다.
    assert all(row["changed"] is False for row in rows.values())
    assert rows[KIND_RESOURCE_TAGS]["reason"] == \
        f"supporting_cue_separated:{KIND_APPEARANCE}"


def test_leave_one_out_shows_when_a_single_cue_carried_the_whole_verdict(
        estimator, profiles):
    """외형이 1·2 위를 가르지 못하면 판정은 태그 하나에 걸려 있다. 그 사실이 표에
    나와야 운영자가 "저 태그가 틀리면 저 판정도 틀린다" 를 알 수 있다."""
    estimate = estimator.estimate([
        _appearance("go1", score=0.84, runner_up="ep01", runner_score=0.83,
                    state=AppearanceState.AMBIGUOUS),
        resource_tag_cue(["tier.ugv", "locomotion.legged", "sensor.imu",
                          "actuator.led_speaker"], profiles, observed_at=1.0),
        motion_cue(1.1, profiles, observed_at=1.0),
    ])
    rows = {row["removed"]: row for row in estimate.explanation()[LEAVE_ONE_OUT]}

    assert estimate.device_class == "go1"
    assert estimate.reason == f"decisive_cue_separated:{KIND_RESOURCE_TAGS}"
    assert rows[KIND_RESOURCE_TAGS]["changed"] is True
    assert rows[KIND_RESOURCE_TAGS]["state"] == ClassState.AMBIGUOUS.value
    assert rows[KIND_MOTION]["changed"] is False
    # 모호한 외형은 침묵이 아니다 — 지지는 하되 가르지 않는다.
    assert rows[KIND_APPEARANCE]["changed"] is False


def test_the_explanation_names_the_reference_images_behind_the_appearance_part(
        estimator, dictionary):
    """외형 기여가 어떤 **사진** 때문인지까지 내려가야 사람이 틀린 참조를 찾는다."""
    entry = next(e for e in dictionary.fit_classes if e.class_name == "go1")
    verdict = AppearanceClassifier(dictionary).classify_embedding(entry.embeddings[0])
    cue = appearance_cue(verdict, observed_at=1.0)

    driving = cue.detail["driving_references"]["go1"]

    assert driving and all(name.startswith("go1_") for name in driving)
    assert cue.as_dict()["detail"]["driving_references"]["go1"] == driving


def test_ranking_is_deterministic_for_the_same_input(estimator, profiles):
    """같은 입력이 실행마다 다른 순위를 내면 그 순위를 근거로 한 설명은 재현되지 않는다."""
    cues = [_appearance("go1", score=0.8, runner_up="ep01", runner_score=0.8),
            declared_zone_cue("zone-a", profiles, observed_at=1.0)]

    first = [row.class_name for row in estimator.estimate(cues).ranked]
    second = [row.class_name for row in estimator.estimate(cues).ranked]

    assert first == second


# --- 종류와 값은 데이터다 -----------------------------------------------------


def test_a_new_cue_kind_arrives_by_registration_not_by_editing_this_module(profiles):
    """새 단서 종류는 레지스트리에 **등록**으로 들어온다(AI-C-18 의 선언 규약과 같은 축)."""
    kinds = DEFAULT_CUE_KINDS.copy()
    kinds.register(ClassCueSpec("thermal_signature", decisive=True, weight=0.6,
                                request="request_thermal_frame",
                                note="시험용 — 배치가 열화상을 가진 경우의 새 종류."))
    estimator = DeviceClassEstimator(profiles, kinds=kinds)

    estimate = estimator.estimate([ClassCue(
        "thermal_signature", "thermal_cam", 1.0,
        support={"holybro_x500_v2": 0.9}, separated="holybro_x500_v2",
        excludes={"mt4": "no_motor_heat"})])

    assert estimate.state is ClassState.ESTIMATED
    assert estimate.device_class == "holybro_x500_v2"
    assert estimate.excluded_classes == {"mt4": "no_motor_heat"}


def test_an_unregistered_cue_kind_is_ignored_but_shows_up_as_unobserved(estimator):
    """등록되지 않은 종류는 조용히 쓰이지 않는다 — 이름 오타가 판정을 바꾸지 않는다."""
    estimate = estimator.estimate([ClassCue(
        "appearnce_embedding", "typo", 1.0, support={"go1": 1.0}, separated="go1")])

    assert estimate.state is ClassState.NO_CUE
    assert KIND_APPEARANCE in estimate.unobserved_kinds


def test_a_supporting_cue_cannot_exclude_even_if_it_claims_to(estimator):
    """보조 단서가 배제를 적어 보내도 받지 않는다. 받으면 사진 한 장이 기종을 지운다."""
    rogue = ClassCue(KIND_APPEARANCE, "rogue", 1.0, support={"go1": 0.9},
                     separated="go1", excludes={"mt4": "i_say_so"})

    estimate = estimator.estimate([rogue])

    assert estimate.excluded_classes == {}
    assert estimate.device_class == "go1"


def test_cue_weights_come_from_the_dictionary_and_can_be_overridden(profiles):
    """무게는 데이터이고 교체 가능해야 한다(AI-C-13)."""
    assert profiles.weights[KIND_ANNOUNCED_ACTIONS] > profiles.weights[KIND_APPEARANCE]

    default = DeviceClassEstimator(profiles)
    tuned = DeviceClassEstimator(profiles, weights={KIND_APPEARANCE: 0.99})

    assert default.weight_of(KIND_APPEARANCE) == profiles.weights[KIND_APPEARANCE]
    assert tuned.weight_of(KIND_APPEARANCE) == 0.99


def test_raising_the_appearance_weight_still_cannot_overturn_an_exclusion(profiles):
    """무게를 끝까지 올려도 배제는 뒤집히지 않는다 — 판정은 점수가 아니라 구조다."""
    estimator = DeviceClassEstimator(profiles, weights={KIND_APPEARANCE: 1.0,
                                                        KIND_RESOURCE_TAGS: 0.01})
    estimate = estimator.estimate([
        _appearance("insta360", score=0.99),
        resource_tag_cue(["tier.uav", "platform.uav"], profiles, observed_at=1.0),
    ])

    assert "insta360" in estimate.excluded_classes
    assert estimate.device_class == "holybro_x500_v2"


def test_the_shipped_dictionary_declares_a_profile_for_every_classifiable_class(
        dictionary, profiles):
    """사진은 있는데 프로파일이 없는 기종이 남아 있으면 그것은 보고될 사실이다."""
    with_pictures = {entry.class_name for entry in dictionary.fit_classes}

    assert with_pictures <= set(profiles.names), (
        f"프로파일이 없는 기종: {sorted(with_pictures - set(profiles.names))}")


def test_the_declared_sizes_are_marked_as_declared_not_measured():
    """제원에서 적은 범위를 실측처럼 적어 두면 다음 사람이 그것을 측정값으로 읽는다."""
    payload = json.loads(DICTIONARY_PATH.read_text(encoding="utf-8"))

    for name, entry in payload.items():
        profile = entry.get("estimation_profile") if not name.startswith("_") else None
        if profile and profile.get("size_m"):
            assert profile["size_source"] == "declared_not_measured"


# --- 광학 환산은 입력이지 이 모듈의 일이 아니다 -------------------------------


def test_apparent_size_needs_a_range_and_says_nothing_without_one():
    assert apparent_size_m((0, 0, 100, 200), range_m=None, focal_px=800) is None
    assert apparent_size_m((0, 0, 100, 200), range_m=0.0, focal_px=800) is None
    assert apparent_size_m((0, 0, 0, 0), range_m=3.0, focal_px=800) is None

    size = apparent_size_m((0, 0, 100, 200), range_m=3.0, focal_px=800)

    assert size == pytest.approx(0.75, abs=1e-6)


def test_size_usually_excludes_rather_than_separates(profiles):
    """사족 로봇과 쿼드콥터는 크기가 겹친다 — 겹치는 둘을 가른 척하지 않는다."""
    cue = apparent_size_cue(0.65, profiles, observed_at=1.0)

    assert cue.separated is None
    assert cue.tied == ("go1", "holybro_x500_v2")
    assert cue.support["go1"] == cue.support["holybro_x500_v2"] == 1.0


def test_a_size_inside_the_tolerance_is_weak_support_not_an_exclusion(profiles):
    """0.65 m 는 탁상 팔의 선언 범위(…~0.45 m)보다 1.44 배 크다. 허용오차가 1.6 이니
    배제하지 않는다 — 배제하면 거리 환산 오차 한 번이 기종을 지워 버린다.

    배제는 허용오차를 **넘을 때** 나온다. 두 경계를 함께 고정해 두어야 나중에
    `_meta.estimation` 의 허용오차를 고칠 때 무엇이 달라지는지 보인다.
    """
    inside = apparent_size_cue(0.65, profiles, observed_at=1.0)
    outside = apparent_size_cue(0.9, profiles, observed_at=1.0)

    assert "mt4" not in inside.excludes
    assert 0.0 < inside.support["mt4"] < 1.0
    assert "insta360" in inside.excludes, "0.65 m 는 360 카메라의 6 배다"

    assert set(outside.excludes) == {"ep01", "insta360", "mt4"}
    assert outside.separated == "go1"


# --- 실제 사전으로 끝까지 --------------------------------------------------


def test_a_real_reference_vector_and_the_real_profile_agree(dictionary, estimator, profiles):
    """사전의 실제 벡터로 외형을 재고 그 기종의 실제 선언을 얹으면 같은 답이 나와야 한다.

    여기서 갈라지면 사전의 `estimation_profile` 이 사진과 다른 기종을 가리키고 있는
    것이다 — 그 불일치는 조용히 지나가면 운영에서 모순으로만 보인다.
    """
    classifier = AppearanceClassifier(dictionary)
    for entry in dictionary.fit_classes:
        profile = profiles.get(entry.class_name)
        assert profile is not None
        verdict = classifier.classify_embedding(entry.embeddings[0])
        estimate = estimator.estimate([
            appearance_cue(verdict, observed_at=1.0),
            announced_action_cue(profile.action_vocabulary, profiles, observed_at=1.0),
            resource_tag_cue(profile.signature_tags, profiles, observed_at=1.0),
        ])

        assert estimate.state is ClassState.ESTIMATED, (
            f"{entry.class_name}: {estimate.reason} / {estimate.conflicts}")
        assert estimate.device_class == entry.class_name


def test_a_wrong_confident_appearance_becomes_a_conflict_not_a_wrong_answer(
        dictionary, estimator, profiles):
    """사전에 기록된 두 번의 1 위 뒤집힘을 모사한다.

    외형이 틀린 기종을 확신해도, 그 장치가 스스로 공지·등록한 것이 있으면 결과는
    틀린 확답이 아니라 **이름이 붙은 모순**이어야 한다. 이것이 다중 단서를 쓰는
    두 번째 이유다(첫 번째는 외형이 가를 수 없는 구간을 가르는 것).
    """
    classifier = AppearanceClassifier(dictionary)
    entry = next(e for e in dictionary.fit_classes if e.class_name == "insta360")
    verdict = classifier.classify_embedding(entry.embeddings[0])
    flipped = replace(verdict, appearance_class="go1",
                      ranked=tuple(sorted(verdict.ranked,
                                          key=lambda s: 0 if s.class_name == "go1" else 1)))

    estimate = estimator.estimate([
        appearance_cue(flipped, observed_at=1.0),
        resource_tag_cue(profiles.get("insta360").signature_tags, profiles, observed_at=1.0),
    ])

    assert estimate.state is ClassState.CONFLICTED
    assert estimate.classified is False
    assert estimate.device_class == "insta360"
    assert any(c.claims == "go1" for c in estimate.conflicts)
