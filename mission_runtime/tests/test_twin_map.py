"""implements: AI-S-06, AI-S-08, AI-C-01, AI-C-02, AI-C-05
tests: 아무도 보지 않은 칸은 비어 있지 않다 · 불일치는 모름이 아니다 · 미관측은
       낡음이 아니다 · 광선 없는 출처는 "비었다" 를 말하지 못한다 · 사전정보만으로는
       칸을 주장하지 못한다 · 노후화와 나쁜 자세는 자유 질량을 만들지 않는다 ·
       같은 원본 관측을 두 번 세지 않는다 · 쓸 수 없는 출처가 받친 칸은 지워지지 않고
       모름으로 돌아간다 · datum 없는 현장은 정상이고 전역 값은 거절된다 · 로컬 값과
       전역 값은 같은 칸에 담기지 않는다 · 모듈이 내는 payload 의 이름은 전부 사전에
       등재돼 있다

이 모듈의 주장은 "지도가 맞다" 가 아니라 **"거짓말하지 않는다"** 다. 그래서 여기 있는
시험은 대부분 *무엇이 일어나지 않는가* 를 고정한다 — 침묵이 부재가 되지 않고, 미측정이
0 이 되지 않고, 모름이 비었음이 되지 않는다.

payload 이름을 전부 훑는 시험(`test_every_payload_name_is_in_the_data_dictionary`)이
있는 이유: 이 모듈은 사전에 없는 이름 36 개를 참조한 채로 커밋돼 있었고, 아무도
import 하지 않았기 때문에 시험이 초록이었다. `as_dict()` 를 한 번도 부르지 않는 시험은
그 상태를 다시 허용한다.
"""

from __future__ import annotations

import math

import pytest

from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.contracts.capability import CapabilityState
from mission_runtime.perception.environment_map import Anchor
from mission_runtime.perception.environment_prior import PriorInfoRecord
from mission_runtime.perception.spatial_evidence import (
    ROLE_DEPENDENT,
    ROLE_INDEPENDENT,
    TIER_DECLARED,
    TIER_ESTIMATED,
    TIER_MEASURED,
)
from mission_runtime.perception.twin_map import (
    CLAIM_FREE,
    CLAIM_OCCUPIED,
    DEFAULT_STALE_AFTER,
    FRAME_GLOBAL,
    FRAME_ZONE,
    LIMITED_BY_DATUM,
    LIMITED_BY_LOCAL,
    LIMITED_BY_UNKNOWN,
    MAP_AUTHORITY_SITE_LOCAL,
    MAP_CLAIMS,
    PERSISTENCE_BY_NEGATIVE_REPORT,
    PERSISTENCE_BY_PRIOR_DECAY,
    PERSISTENCE_BY_SIGHTING,
    POSE_DECLARED,
    POSE_QUALITIES,
    POSE_UNKNOWN,
    POSE_VALIDATED,
    REFUSE_DATUM_ACCURACY_UNKNOWN,
    REFUSE_NO_DATUM,
    REFUSE_NO_LOCAL_VALUE,
    REFUSE_UNKNOWN_FRAME,
    REJECT_DUPLICATE,
    REJECT_EMPTY_FOOTPRINT,
    REJECT_FRAME_MISMATCH,
    REJECT_FREE_CLAIM_NOT_PERMITTED,
    REJECT_SOURCE_UNAVAILABLE,
    REJECT_UNKNOWN_CLAIM,
    REJECT_UNREGISTERED_KIND,
    REQUIREMENT,
    BeliefMass,
    CellState,
    ElementPersistence,
    MapObservation,
    MapObservationKindSpec,
    SiteDatum,
    TwinMapLayer,
    datum_from_profile,
    declared_pose_quality,
    gather_observations,
    observation_from_point,
    prior_observations_from_domain_profile,
)

NOW = 1_000.0


def obs(observation_id: str, footprint, **kw) -> MapObservation:
    """시험용 관측 1건. 기본은 박스 탐지(광선 없음)다."""
    params = dict(
        source_group="camA", frame_ref=f"frame:{observation_id}", observed_at=NOW,
        observation_kind="object_detection", claim=CLAIM_OCCUPIED, frame_id="zone",
        strength=0.8, pose_quality=POSE_VALIDATED,
    )
    params.update(kw)
    return MapObservation(observation_id=observation_id, footprint=footprint, **params)


@pytest.fixture
def layer() -> TwinMapLayer:
    return TwinMapLayer(cell_size_m=1.0, frame_id="zone")


# --- 세 상태를 섞지 않는다 ---------------------------------------------------

def test_a_cell_nobody_looked_at_is_not_free(layer):
    """탐지로 지은 지도가 거짓말하는 가장 흔한 길이 모름과 비었음을 합치는 것이다."""
    untouched = layer.cell((9, 9), now=NOW)

    assert untouched.state is CellState.UNKNOWN
    assert untouched.state is not CellState.FREE
    assert untouched.never_observed is True
    # 질량 전부가 무지에 있다. **free 가 0 이라는 사실이 "비었다" 가 아니다.**
    assert untouched.mass.unknown == pytest.approx(1.0)
    assert untouched.mass.free == 0.0
    assert untouched.mass.occupied == 0.0
    assert untouched.contributions == ()
    # 관측이 없는 칸도 객체를 돌려준다 — None 이면 호출자가 "없음" 을 "비었음" 으로
    # 읽을 자리가 생긴다.
    assert layer.state_at(9.5, 9.5, now=NOW) is CellState.UNKNOWN


def test_a_disputed_cell_is_not_an_unknown_one(layer):
    """봤는데 서로 다르게 본 칸과 아예 안 본 칸은 대응이 다르다."""
    layer.register_observation_kind(MapObservationKindSpec(
        "swept", TIER_ESTIMATED, may_claim_free=True, through_pose=True))
    layer.ingest(obs("occ", (0.1, 0.1, 0.9, 0.9), strength=0.9))
    layer.ingest(obs("free", (0.1, 0.1, 0.9, 0.9), observation_kind="swept",
                     claim=CLAIM_FREE, strength=0.9, source_group="depthB",
                     frame_ref="frame:depth-1"))

    cell = layer.cell((0, 0), now=NOW)

    assert cell.state is CellState.DISPUTED
    assert cell.never_observed is False, "싸웠다는 것은 둘 다 봤다는 뜻이다"
    # 충돌은 질량이 아니라 감사 기록이고, **0 으로 적으면 모름과 구분되지 않는다.**
    assert cell.mass.conflict > 0.0
    assert cell.as_dict()[dd.MASS_CONFLICT] > 0.0
    assert cell.as_dict()[dd.CELL_STATE] == CellState.DISPUTED.value


def test_never_observed_and_stale_are_different_facts(layer):
    """하나는 가서 본 적이 없다는 뜻이고 하나는 본 것이 낡았다는 뜻이다."""
    layer.ingest(obs("old", (3.1, 3.1, 3.9, 3.9), observed_at=NOW))
    much_later = NOW + DEFAULT_STALE_AFTER * 10

    stale = layer.cell((3, 3), now=much_later)
    unseen = layer.cell((7, 7), now=much_later)

    assert stale.is_stale(much_later) and unseen.is_stale(much_later)
    # 같은 규칙으로 stale 이지만 **같은 상태가 아니다.**
    assert stale.never_observed is False
    assert unseen.never_observed is True
    assert stale.last_observed_at == NOW
    assert unseen.last_observed_at is None, "미관측은 0 이 아니라 모름이다"

    summary = layer.summarize((3.0, 3.0, 7.9, 7.9), now=much_later).as_dict()
    assert summary[dd.STALE_CELL_COUNT] == 1
    assert summary[dd.NEVER_OBSERVED_CELL_COUNT] == summary[dd.TOTAL_CELL_COUNT] - 1
    # 두 수를 따로 세지 않으면 "근거가 모자라다" 와 "관측 자체가 없다" 가 한 칸이 된다.
    assert summary[dd.UNKNOWN_CELL_COUNT] >= summary[dd.NEVER_OBSERVED_CELL_COUNT]


# --- 침묵은 부재가 아니다 ----------------------------------------------------

def test_a_box_detection_may_not_claim_free_space(layer):
    """광선 없는 출처에 자유 주장을 허용하면 침묵이 "비었다" 로 환산된다(규칙 1)."""
    touched = layer.ingest(obs("f1", (0.1, 0.1, 0.9, 0.9), claim=CLAIM_FREE))

    assert touched == (), "거절은 아무 칸도 건드리지 않는다"
    assert layer.cell((0, 0), now=NOW).state is CellState.UNKNOWN
    reasons = [row.reason for row in layer.rejected()]
    assert reasons == [REJECT_FREE_CLAIM_NOT_PERMITTED]
    # 거절은 예외로 올라가지 않는다 — 선택 출처 하나가 지도를 멈추게 하지 않는다.
    assert dd.unknown_fields(layer.rejected()[0].as_dict()) == ()


def test_a_swept_source_is_the_only_kind_that_may_claim_free(layer):
    """깊이·점군처럼 '여기까지 아무것도 없었다' 를 아는 출처만 비었다고 말한다."""
    layer.register_observation_kind(MapObservationKindSpec(
        "swept", TIER_ESTIMATED, may_claim_free=True, through_pose=True))
    layer.ingest(obs("sw", (1.1, 1.1, 1.9, 1.9), observation_kind="swept",
                     claim=CLAIM_FREE, strength=0.9))

    cell = layer.cell((1, 1), now=NOW)
    assert cell.state is CellState.FREE
    assert cell.mass.free > 0.5


def test_age_and_bad_pose_never_grow_the_free_mass(layer):
    """시간이 갔다는 사실도, 자세를 못 믿는다는 사실도 "비었다" 의 근거가 아니다."""
    layer.ingest(obs("p", (0.1, 0.1, 0.9, 0.9), pose_quality=POSE_UNKNOWN))
    fresh = layer.cell((0, 0), now=NOW)
    aged = layer.cell((0, 0), now=NOW + 10_000.0)

    assert aged.mass.occupied < fresh.mass.occupied, "낡으면 확신이 줄어든다"
    # 줄어든 몫은 전부 모름으로 간다. 자유 질량은 **한 톨도** 늘지 않는다(규칙 2·6).
    assert aged.mass.free == 0.0 == fresh.mass.free
    assert aged.mass.unknown > fresh.mass.unknown
    assert aged.mass.occupied + aged.mass.free + aged.mass.unknown == pytest.approx(1.0)


def test_discounting_only_moves_mass_to_unknown():
    """`BeliefMass.discount()` 의 대수적 성질. 자유 질량이 늘어나는 경로가 없다."""
    mass = BeliefMass.from_claim(CLAIM_OCCUPIED, 0.9)
    for alpha in (1.0, 0.6, 0.2, 0.0):
        out = mass.discount(alpha)
        assert out.free == 0.0
        assert out.occupied <= mass.occupied
        assert out.occupied + out.free + out.unknown == pytest.approx(1.0)
    assert mass.discount(0.0).unknown == pytest.approx(1.0)


def test_an_absent_kind_is_reported_as_unobserved_not_as_counter_evidence(layer):
    """등록됐으나 관측이 없는 종류는 반대 근거가 아니라 **미측정**이다(규칙 8)."""
    layer.ingest(obs("o", (0.1, 0.1, 0.9, 0.9)))

    body = layer.as_dict(now=NOW)
    assert "swept_free_space" in body[dd.UNOBSERVED_EVIDENCE_KINDS]
    assert "object_detection" not in body[dd.UNOBSERVED_EVIDENCE_KINDS]
    assert body[dd.MAP_AUTHORITY] == MAP_AUTHORITY_SITE_LOCAL


def test_an_unavailable_source_returns_its_cell_to_unknown_rather_than_erasing_it(layer):
    """혼자 받치던 출처가 사라진 칸은 지워지지도, 비었다고 적히지도 않는다(AI-C-05)."""
    layer.ingest(obs("a", (0.1, 0.1, 0.9, 0.9), source_group="camA"))
    assert layer.cell((0, 0), now=NOW).state is CellState.OCCUPIED

    reduced = layer.reduced_view({"camB"}, now=NOW)

    assert [c.cell for c in reduced] == [(0, 0)], "칸은 목록에서 사라지지 않는다"
    assert reduced[0].state is CellState.UNKNOWN
    assert reduced[0].state is not CellState.FREE
    assert reduced[0].never_observed is True
    # 출처가 돌아오면 칸도 돌아온다 — 원재료를 들고 있기 때문이다(규칙 3).
    assert layer.cell((0, 0), now=NOW).state is CellState.OCCUPIED


def test_a_failing_provider_contributes_nothing_and_leaves_its_name(layer):
    """provider 장애는 빈 결과이고 빈 결과는 반대 근거가 아니다."""
    def boom():
        raise RuntimeError("provider down")

    collected, unavailable = gather_observations({
        "good": lambda: [obs("g", (0.1, 0.1, 0.9, 0.9))],
        "broken": boom,
        "absent": None,
    })

    assert [o.observation_id for o in collected] == ["g"]
    assert unavailable == ("absent", "broken")


# --- 사전정보는 관측이 아니다 ------------------------------------------------

def test_prior_information_alone_never_claims_a_cell(layer):
    """도면이 벽이라고 적었다는 사실만으로 칸이 점유가 되면 탐지가 영원히 범인이 된다."""
    record = PriorInfoRecord(
        record_id="wall-7", kind="infrastructure", source="zone_profile",
        scope=("zone-a",), created_at=0.0, updated_at=0.0, version="v1")
    touched = layer.ingest_prior(record, now=NOW, footprint=(0.1, 0.1, 0.9, 0.9))

    assert touched == ((0, 0),), "사전정보는 들어온다"
    cell = layer.cell((0, 0), now=NOW)

    assert cell.state is CellState.UNKNOWN, "그러나 어떤 칸도 주장하지 못한다"
    assert cell.observed_support == 0
    assert cell.prior_support == 1
    assert cell.never_observed is True
    # 사전정보가 한 말은 주장과 **섞이지 않고 따로** 적힌다(AI-S-08).
    payload = cell.as_dict()
    assert payload[dd.PRIOR_CLAIM] == CLAIM_OCCUPIED
    assert payload[dd.CELL_STATE] == CellState.UNKNOWN.value
    assert payload[dd.OBSERVED_SUPPORT_COUNT] == 0
    assert payload[dd.PRIOR_SUPPORT_COUNT] == 1


def test_an_invalid_prior_record_touches_nothing_and_is_not_rejudged(layer):
    """유효성은 environment_prior 가 소유한다 — 두 곳에서 판정하면 두 답이 생긴다."""
    expired = PriorInfoRecord(
        record_id="old", kind="infrastructure", source="profile", scope=("z",),
        created_at=0.0, updated_at=0.0, version="v1", valid_until=NOW - 1.0)

    assert layer.ingest_prior(expired, now=NOW, footprint=(0.0, 0.0, 1.0, 1.0)) == ()
    assert layer.known_cells() == ()
    assert layer.rejected() == (), "기간 밖 레코드는 거절 사유가 아니라 비적용이다"


def test_a_prior_that_contradicts_the_observation_is_neither_hidden_nor_decisive(layer):
    """실측이 어긋날 때 "탐지가 틀렸다" 로도, "도면은 없었다" 로도 적지 않는다.

    선언이 센 관측과 정면으로 어긋나면 그 어긋남 자체가 읽기값에 나타난다(DISPUTED) —
    사전정보는 칸을 **확정하지 못하지만**(AI-S-08) 조용히 지워지지도 않는다. 운영자가
    볼 것은 "비었다" 가 아니라 "도면과 센서가 싸운다" 다.
    """
    record = PriorInfoRecord(
        record_id="w", kind="infrastructure", source="profile", scope=("z",),
        created_at=0.0, updated_at=0.0, version="v1")
    layer.register_observation_kind(MapObservationKindSpec(
        "swept", TIER_ESTIMATED, may_claim_free=True, through_pose=True))
    layer.ingest_prior(record, now=NOW, footprint=(0.1, 0.1, 0.9, 0.9))
    layer.ingest(obs("sw", (0.1, 0.1, 0.9, 0.9), observation_kind="swept",
                     claim=CLAIM_FREE, strength=0.9, source_group="depth"))

    cell = layer.cell((0, 0), now=NOW)
    assert cell.observed_support == 1
    assert cell.prior_support == 1
    assert cell.state is CellState.DISPUTED
    assert cell.state is not CellState.OCCUPIED, "선언만으로는 확정하지 못한다"
    # 관측 지지가 생기면 사전정보의 말은 따로 보고되지 않는다 — 융합이 이미 그것을
    # 포함했으므로 두 번 적으면 같은 사실의 주인이 둘이 된다.
    assert cell.prior_claim is None


def test_a_weak_prior_does_not_overturn_the_observation(layer):
    """어긋남이 충돌 임계 아래면 관측이 읽기값을 정한다 — 작은 불일치로 칸을
    포기하지 않는 것이 임계를 둔 이유다.
    """
    record = PriorInfoRecord(
        record_id="w", kind="infrastructure", source="profile", scope=("z",),
        created_at=0.0, updated_at=0.0, version="v1")
    layer.register_observation_kind(MapObservationKindSpec(
        "swept", TIER_ESTIMATED, may_claim_free=True, through_pose=True))
    layer.ingest_prior(record, now=NOW, footprint=(0.1, 0.1, 0.9, 0.9),
                       strength=0.2)
    layer.ingest(obs("sw", (0.1, 0.1, 0.9, 0.9), observation_kind="swept",
                     claim=CLAIM_FREE, strength=0.9, source_group="depth"))

    cell = layer.cell((0, 0), now=NOW)
    assert cell.state is CellState.FREE
    assert 0.0 < cell.mass.conflict < 0.35, "어긋남은 지워지지 않고 기록으로 남는다"


def test_the_declared_tier_is_the_prior_tier(layer):
    """`declared` 는 사전정보 격이다 — 정확도가 좋아도 격이 올라가지 않는다."""
    spec = layer.kinds.spec("declared_obstacle")
    assert spec is not None and spec.tier == TIER_DECLARED and spec.is_prior
    assert layer.kinds.spec("human_survey").tier == TIER_MEASURED
    assert not layer.kinds.spec("human_survey").is_prior
    assert layer.kinds.spec("object_detection").tier == TIER_ESTIMATED


# --- 중복을 두 번 세지 않는다 -------------------------------------------------

def test_two_reads_of_one_frame_are_one_support(layer):
    """Dempster 결합은 중복 계산에 안전하지 않다 — 같은 프레임을 두 번 넣으면 질량이
    두 배가 된다. 독립성의 단위는 생산자가 아니라 **원본 관측**이다(AI-S-06).
    """
    layer.ingest(obs("r1", (0.1, 0.1, 0.9, 0.9), frame_ref="frame:same", strength=0.8))
    layer.ingest(obs("r2", (0.1, 0.1, 0.9, 0.9), frame_ref="frame:same", strength=0.5,
                     source_group="camB"))

    cell = layer.cell((0, 0), now=NOW)

    assert cell.observed_support == 1, "한 프레임을 두 번 읽은 것은 한 번의 관측이다"
    roles = {row.observation_id: row.role for row in cell.contributions}
    assert roles == {"r1": ROLE_INDEPENDENT, "r2": ROLE_DEPENDENT}
    # 종속 기여는 지워지지 않고 세기 0 으로 남는다 — 조용히 버리면 왜 질량이 그만큼
    # 인지 설명할 수 없다(규칙 3).
    dependent = next(r for r in cell.contributions if r.role == ROLE_DEPENDENT)
    assert dependent.applied_strength == 0.0
    assert dependent.as_dict()[dd.EVIDENCE_STRENGTH] == pytest.approx(0.5)


def test_the_same_observation_id_is_ingested_once(layer):
    layer.ingest(obs("dup", (0.1, 0.1, 0.9, 0.9)))
    assert layer.ingest(obs("dup", (0.1, 0.1, 0.9, 0.9))) == ()
    assert [r.reason for r in layer.rejected()] == [REJECT_DUPLICATE]


def test_every_rejection_reason_is_reachable_and_named(layer):
    """오타 하나가 지도를 바꾸지 않은 채 사라지는 것이 가장 찾기 어려운 버그다."""
    layer.ingest(obs("k", (0.1, 0.1, 0.9, 0.9), observation_kind="no_such_kind"))
    layer.ingest(obs("c", (0.1, 0.1, 0.9, 0.9), claim="maybe"))
    layer.ingest(obs("s", (0.1, 0.1, 0.9, 0.9)), available_sources={"camZ"})
    layer.ingest(obs("f", (0.1, 0.1, 0.9, 0.9), frame_id="other_zone"))
    layer.ingest(obs("e", (0.1, 0.1, 0.9, 0.9), claim=CLAIM_FREE))
    layer.ingest(obs("d", (0.1, 0.1, 0.9, 0.9)))
    layer.ingest(obs("d", (0.1, 0.1, 0.9, 0.9)))

    reasons = [row.reason for row in layer.rejected()]
    assert reasons == [REJECT_UNREGISTERED_KIND, REJECT_UNKNOWN_CLAIM,
                       REJECT_SOURCE_UNAVAILABLE, REJECT_FRAME_MISMATCH,
                       REJECT_FREE_CLAIM_NOT_PERMITTED, REJECT_DUPLICATE]
    assert set(reasons) <= set(dd.TWIN_MAP_REJECTION_REASONS)
    # 거절이 쌓여도 지도는 성립한다.
    assert layer.known_cells() == ((0, 0),)


def test_an_empty_footprint_is_rejected_not_silently_dropped():
    """`REJECT_EMPTY_FOOTPRINT` 에 닿는 유일한 길은 격자가 칸을 내지 않는 것이다."""
    layer = TwinMapLayer(cell_size_m=1.0, frame_id="zone")
    assert layer.cells_in((0.1, 0.1, 0.9, 0.9)) != ()
    assert REJECT_EMPTY_FOOTPRINT in dd.TWIN_MAP_REJECTION_REASONS
    with pytest.raises(ValueError):
        obs("bad", (1.0, 1.0, 0.0, 0.0))     # x2 < x1 은 애초에 만들어지지 않는다


# --- 출처가 남는다 -----------------------------------------------------------

def test_leave_one_out_names_the_source_that_decided_the_cell(layer):
    """지도가 틀렸다고 들고 왔을 때 먼저 보는 줄."""
    layer.ingest(obs("a", (0.1, 0.1, 0.9, 0.9), source_group="camA",
                     frame_ref="frame:a", strength=0.9))
    layer.ingest(obs("b", (0.1, 0.1, 0.9, 0.9), source_group="camB",
                     frame_ref="frame:b", strength=0.2))

    rows = layer.leave_one_out((0, 0), now=NOW)
    by_name = {row.removed: row for row in rows}

    assert set(by_name) == {"camA", "camB"}
    assert by_name["camA"].occupancy_influence > by_name["camB"].occupancy_influence
    assert by_name["camA"].state_flipped is True, "camA 혼자 읽기값을 정하고 있었다"
    assert by_name["camB"].state_flipped is False
    # 사전은 leave-one-out 행의 구조 칸(`removed`·`unit`)을 spatial_evidence 와 같은
    # 모양으로 둔다 — 같은 관용구를 두 이름으로 적으면 근거를 되짚을 수 없다.
    payload = by_name["camA"].as_dict()
    assert dd.unknown_fields(payload) == ("removed", "unit")
    assert payload[dd.CELL_STATE] == CellState.UNKNOWN.value
    assert payload[dd.OCCUPANCY_INFLUENCE] > 0.0


def test_without_rebuilds_the_map_instead_of_mutating_it(layer):
    layer.ingest(obs("a", (0.1, 0.1, 0.9, 0.9), source_group="camA"))
    reduced = layer.without("camA")

    assert reduced.known_cells() == ()
    assert layer.known_cells() == ((0, 0),), "원본은 그대로 남는다"
    assert reduced.datum is layer.datum and reduced.frame_id == layer.frame_id


def test_an_unregistered_pose_quality_is_treated_most_conservatively(layer):
    """기본값을 1.0 으로 두면 오타 하나가 검증된 보정과 같은 확신을 만든다."""
    layer.ingest(obs("typo", (0.1, 0.1, 0.9, 0.9), pose_quality="valdiated"))
    layer.ingest(obs("good", (2.1, 2.1, 2.9, 2.9), pose_quality=POSE_VALIDATED))

    typo = layer.cell((0, 0), now=NOW)
    good = layer.cell((2, 2), now=NOW)
    assert typo.mass.occupied < good.mass.occupied
    assert typo.weakest_pose_quality == "valdiated"


def test_a_new_pose_grade_is_registration_not_a_branch(layer):
    """새 등급이 생겨도 이 모듈에 `if` 가 늘지 않는다(규칙 7)."""
    layer.set_pose_discount("surveyed_mount", 1.0)
    layer.ingest(obs("s", (0.1, 0.1, 0.9, 0.9), pose_quality="surveyed_mount"))

    assert layer.cell((0, 0), now=NOW).mass.occupied == pytest.approx(0.8)
    with pytest.raises(ValueError):
        layer.set_pose_discount("bogus", 1.5)


def test_a_source_that_bypasses_the_camera_pose_takes_no_pose_discount(layer):
    """사람이 줄자로 잰 값은 어떤 카메라 자세도 통과하지 않는다(규칙 6)."""
    layer.ingest(obs("survey", (0.1, 0.1, 0.9, 0.9), observation_kind="human_survey",
                     claim=CLAIM_FREE, strength=0.9, pose_quality=POSE_UNKNOWN,
                     source_group="surveyor"))

    cell = layer.cell((0, 0), now=NOW)
    assert cell.mass.free == pytest.approx(0.9)
    assert cell.weakest_pose_quality is None, "통과한 자세가 없으면 모름으로 남는다"


# --- 좌표계: 로컬과 전역은 교환 가능하지 않다 (AI-C-02) -----------------------

def test_a_site_without_a_datum_is_a_normal_deployment(layer):
    """전역 계층만 비활성이 되고 로컬 판단은 그대로 동작한다(AI-C-05)."""
    local = layer.position_in((1.5, 2.5), FRAME_ZONE, local_accuracy_m=0.2)
    refused = layer.position_in((1.5, 2.5), FRAME_GLOBAL)

    assert local.available and local.value == (1.5, 2.5)
    assert refused.available is False
    assert refused.refused_because == REFUSE_NO_DATUM
    assert refused.value is None, "지어낸 좌표보다 거절이 낫다"
    # 로컬 지도는 datum 과 무관하게 계속 돈다.
    layer.ingest(obs("o", (1.1, 1.1, 1.9, 1.9)))
    assert layer.cell((1, 1), now=NOW).state is CellState.OCCUPIED


def test_an_unquantified_datum_does_not_produce_a_global_value(layer):
    """정확도를 모르는 변환으로 낸 전역 값은 얼마나 틀렸는지 말할 수 없다."""
    layer.declare_datum(SiteDatum(datum_id="d0", local_frame="zone", accuracy_m=None,
                                  source="주소를 보고 어림"))
    out = layer.position_in((1.0, 0.0), FRAME_GLOBAL, local_accuracy_m=0.1)

    assert out.available is False
    assert out.refused_because == REFUSE_DATUM_ACCURACY_UNKNOWN
    assert out.datum_id == "d0", "거절도 어느 datum 때문인지 말한다"
    assert layer.datum.quantified is False
    # 미측정 정확도는 0 오차가 아니다 — 0 은 애초에 적을 수 없다.
    with pytest.raises(ValueError):
        SiteDatum(datum_id="d1", local_frame="zone", accuracy_m=0.0)


def test_a_local_value_and_a_global_value_never_share_a_cell(layer):
    """한 칸에 합치면 전역 추정이 어느 측정에서 나왔는지 되짚을 수 없다(AI-C-02)."""
    layer.declare_datum(SiteDatum(datum_id="survey-1", local_frame="zone",
                                  offset=(100.0, 200.0), accuracy_m=0.05,
                                  tier=TIER_MEASURED, source="측량 기준점"))

    local = layer.position_in((1.0, 2.0), FRAME_ZONE, local_accuracy_m=0.1).as_dict()
    glob = layer.position_in((1.0, 2.0), FRAME_GLOBAL, local_accuracy_m=0.1).as_dict()

    assert local[dd.LOCAL_POSITION] == [1.0, 2.0]
    assert local[dd.GLOBAL_POSITION] is None, "로컬 응답은 전역 칸을 채우지 않는다"
    assert local[dd.COORDINATE_FRAME] == FRAME_ZONE
    assert local[dd.DATUM_ID] is None

    assert glob[dd.GLOBAL_POSITION] == [101.0, 202.0]
    assert glob[dd.COORDINATE_FRAME] == FRAME_GLOBAL
    assert glob[dd.DATUM_ID] == "survey-1"
    # 전역 응답의 로컬 칸은 전역 값의 사본이 아니라 그 값이 유도된 **재료**다.
    assert glob[dd.LOCAL_POSITION] == [1.0, 2.0]
    assert glob[dd.LOCAL_POSITION] != glob[dd.GLOBAL_POSITION]
    assert glob[dd.DERIVED_FROM_FRAME] == "zone"


def test_a_global_value_is_never_better_than_the_datum_it_passed_through(layer):
    """어림 datum 을 통과한 좌표가 측량 datum 을 통과한 것처럼 보이면 둘이 같이 쓰인다."""
    layer.declare_datum(SiteDatum(datum_id="rough", local_frame="zone",
                                  accuracy_m=5.0, source="공개 지도"))
    out = layer.position_in((1.0, 0.0), FRAME_GLOBAL, local_accuracy_m=0.1)

    assert out.available
    assert out.accuracy_m == pytest.approx(math.sqrt(0.1 ** 2 + 5.0 ** 2))
    assert out.accuracy_m > 5.0, "합성은 재료보다 좋아지지 않는다"
    assert out.limited_by == LIMITED_BY_DATUM

    layer.declare_datum(SiteDatum(datum_id="tight", local_frame="zone",
                                  accuracy_m=0.01, source="측량"))
    assert layer.position_in((1.0, 0.0), FRAME_GLOBAL,
                             local_accuracy_m=1.0).limited_by == LIMITED_BY_LOCAL


def test_an_unmeasured_accuracy_stays_unmeasured_rather_than_becoming_a_number(layer):
    """기본값을 꽂으면 모르는 값이 아는 값을 이긴다. 0 도 "제한 없음" 도 아니다."""
    layer.declare_datum(SiteDatum(datum_id="d", local_frame="zone", accuracy_m=0.05,
                                  source="측량"))
    out = layer.position_in((1.0, 0.0), FRAME_GLOBAL, local_accuracy_m=None)

    assert out.available, "값은 낼 수 있다"
    assert out.accuracy_m is None
    assert out.accuracy_m != 0.0
    assert out.limited_by == LIMITED_BY_UNKNOWN
    # 로컬 응답도 같은 어휘를 쓴다 — 빈 칸으로 두면 "재지 않았다" 가 사라진다.
    local = layer.position_in((1.0, 0.0), FRAME_ZONE, local_accuracy_m=None)
    assert local.accuracy_m is None and local.limited_by == LIMITED_BY_UNKNOWN
    assert set(dd.ACCURACY_LIMITS) == {LIMITED_BY_LOCAL, LIMITED_BY_DATUM,
                                       LIMITED_BY_UNKNOWN}


def test_the_frame_refusals_are_distinguishable(layer):
    assert layer.position_in(None, FRAME_ZONE).refused_because == REFUSE_NO_LOCAL_VALUE
    assert layer.position_in((0.0, 0.0), "MOON").refused_because == REFUSE_UNKNOWN_FRAME
    assert layer.position_in((0.0, 0.0), FRAME_GLOBAL).refused_because == REFUSE_NO_DATUM


def test_a_datum_for_another_site_is_not_accepted(layer):
    """다른 현장의 datum 으로 옮긴 값은 어느 프레임의 값도 아니다."""
    with pytest.raises(ValueError):
        layer.declare_datum(SiteDatum(datum_id="elsewhere", local_frame="other_zone",
                                      accuracy_m=0.1))


def test_a_cell_position_carries_the_pose_quality_of_what_built_it(layer):
    """검증되지 않은 자세를 통과한 칸은 검증된 칸과 같은 정확도를 주장하지 않는다."""
    layer.ingest(obs("v", (0.1, 0.1, 0.9, 0.9), pose_quality=POSE_VALIDATED))
    layer.ingest(obs("d", (2.1, 2.1, 2.9, 2.9), pose_quality=POSE_DECLARED))

    validated = layer.cell_position((0, 0), now=NOW)
    declared = layer.cell_position((2, 2), now=NOW)

    assert validated.accuracy_m is not None and declared.accuracy_m is not None
    assert declared.accuracy_m > validated.accuracy_m
    # 자세 근거가 없는 칸은 정확도를 지어내지 않는다.
    assert layer.cell_position((8, 8), now=NOW).accuracy_m is None


def test_the_grid_lists_cells_it_has_never_seen(layer):
    """목록에서 빠진 칸은 화면에서 비어 보인다(규칙 1)."""
    cells = layer.cells_in((0.0, 0.0, 1.9, 1.9))
    assert set(cells) == {(0, 0), (0, 1), (1, 0), (1, 1)}
    assert layer.cell_of(-0.5, -0.5) == (-1, -1), "음수 좌표도 칸을 갖는다"
    assert layer.cell_centre((0, 0)) == (0.5, 0.5)


# --- 생존: "봤는데 없었다" 와 "안 봤다" ---------------------------------------

def test_not_looking_is_not_a_negative_report():
    """규칙 8 이 주석이 아니라 **수식의 성질**이 되는 자리."""
    quiet = ElementPersistence("e", born_at=0.0, half_life_s=600.0)
    seen_absent = ElementPersistence("e", born_at=0.0, half_life_s=600.0)
    seen_absent.record_absence(10.0)

    silent = quiet.belief(10.0)
    reported = seen_absent.belief(10.0)

    assert reported.belief < silent.belief, "봤는데 없었으면 더 많이 내려간다"
    assert silent.explained_by == PERSISTENCE_BY_PRIOR_DECAY
    assert reported.explained_by == PERSISTENCE_BY_NEGATIVE_REPORT
    # 아무 보고도 없으면 믿음은 생존 사전확률 그대로다.
    assert silent.belief == pytest.approx(silent.survival_prior)


def test_a_negative_report_cannot_destroy_the_belief_outright():
    """검출기의 미검출률이 그 크기의 상한이다 — 한 번의 오검출이 지도를 무너뜨리지 않는다."""
    element = ElementPersistence("e", born_at=0.0, half_life_s=10_000.0)
    element.record_absence(1.0)

    assert 0.0 < element.belief(1.0).belief < 1.0
    element.record_absence(2.0)
    element.record_absence(3.0)
    assert element.belief(3.0).belief > 0.0, "쌓여도 0 이 되지 않는다"


def test_a_sighting_is_not_published_under_the_name_of_an_observation():
    """음성 보고도 관측이다 — 본 시각과 보고 시각을 한 칸에 담으면 둘이 같아진다."""
    element = ElementPersistence("rock", born_at=0.0, half_life_s=600.0)
    element.record_sighting(10.0)
    element.record_absence(20.0)

    payload = element.belief(30.0).as_dict()

    assert payload[dd.LAST_SIGHTING_AT] == 10.0
    assert payload[dd.LAST_REPORT_AT] == 20.0
    assert payload[dd.SIGHTING_COUNT] == 1
    assert payload[dd.NEGATIVE_REPORT_COUNT] == 1
    assert payload[dd.PERSISTENCE_EXPLAINED_BY] == PERSISTENCE_BY_NEGATIVE_REPORT
    # 믿음과 사전확률을 나란히 싣는 이유: "관측이 끌어내린 것" 과 "시간만 흐른 것".
    assert payload[dd.PERSISTENCE_BELIEF] != payload[dd.SURVIVAL_PRIOR]
    assert dd.unknown_fields(payload) == ()


def test_an_element_nobody_reported_on_has_only_the_prior(layer):
    report = layer.persistence("unseen", NOW)

    assert report.sightings == 0 and report.negative_reports == 0
    assert report.last_sighting_at is None and report.last_report_at is None
    assert report.explained_by == PERSISTENCE_BY_PRIOR_DECAY
    assert report.belief == pytest.approx(report.survival_prior)


def test_a_sighting_explains_the_belief_when_it_is_the_latest_word():
    element = ElementPersistence("e", born_at=0.0, half_life_s=600.0)
    element.record_absence(5.0)
    element.record_sighting(10.0)
    assert element.belief(10.0).explained_by == PERSISTENCE_BY_SIGHTING


def test_detector_rates_are_clamped_open():
    """0 이나 1 을 허용하면 한 번의 보고가 믿음을 못박고 그 뒤 아무것도 움직이지 못한다."""
    element = ElementPersistence("e", born_at=0.0, half_life_s=600.0)
    element.record_absence(1.0, miss_rate=0.0)
    element.record_sighting(2.0, false_alarm_rate=1.0)
    belief = element.belief(3.0).belief
    assert 0.0 < belief < 1.0


# --- 어휘와 이름은 사전이 소유한다 (AI-C-01) ---------------------------------

def test_the_module_vocabularies_are_the_dictionary_vocabularies():
    """모듈이 문자열을 정하고 사전이 어휘를 소유한다(object_appearance 와 같은 규약)."""
    from mission_runtime.perception import twin_map as tm

    rejects = {v for k, v in vars(tm).items()
               if k.startswith("REJECT_") and isinstance(v, str)}
    refusals = {v for k, v in vars(tm).items()
                if k.startswith("REFUSE_") and isinstance(v, str)}
    limits = {v for k, v in vars(tm).items()
              if k.startswith("LIMITED_BY_") and isinstance(v, str)}
    persistence = {v for k, v in vars(tm).items()
                   if k.startswith("PERSISTENCE_BY_") and isinstance(v, str)}

    assert rejects and refusals and limits and persistence
    assert rejects <= set(dd.TWIN_MAP_REJECTION_REASONS)
    assert refusals <= set(dd.FRAME_REFUSAL_REASONS)
    assert limits <= set(dd.ACCURACY_LIMITS)
    assert persistence <= set(dd.PERSISTENCE_EXPLANATIONS)
    # 모듈에 **두 번째 목록**을 두지 않는다 — 갈라지면 어느 쪽이 정본인지 알 수 없다.
    assert {s.value for s in CellState} == set(dd.CELL_STATES)
    assert set(MAP_CLAIMS) == set(dd.TWIN_MAP_CLAIMS)
    assert set(POSE_QUALITIES) == set(dd.POSE_QUALITIES)
    assert MAP_AUTHORITY_SITE_LOCAL in dd.MAP_AUTHORITIES


def test_every_payload_name_is_in_the_data_dictionary(layer):
    """이 모듈은 사전에 없는 이름 36 개를 참조한 채로 커밋돼 있었다.

    아무도 import 하지 않아 시험이 초록이었고, 첫 `as_dict()` 호출이 `AttributeError`
    였다. 그래서 여기서 **공개 payload 전부**를 실제로 만들어 본다 — 등재되지 않은
    이름이 다시 조용히 들어올 수 없게.
    """
    layer.register_observation_kind(MapObservationKindSpec(
        "swept", TIER_ESTIMATED, may_claim_free=True, through_pose=True,
        half_life_s=600.0))
    layer.declare_anchor(Anchor(anchor_id="a1", pose=(0.0, 0.0, 0.0)))
    layer.declare_datum(SiteDatum(datum_id="d", local_frame="zone", offset=(10.0, 20.0),
                                  rotation_deg=30.0, accuracy_m=0.05,
                                  tier=TIER_MEASURED, source="측량"))
    record = PriorInfoRecord(record_id="p", kind="infra", source="profile",
                             scope=("z",), created_at=0.0, updated_at=0.0, version="v1")
    layer.ingest_prior(record, now=NOW, footprint=(0.1, 0.1, 0.9, 0.9))
    layer.ingest(obs("a", (0.1, 0.1, 0.9, 0.9), frame_ref="frame:a"))
    layer.ingest(obs("b", (0.1, 0.1, 0.9, 0.9), frame_ref="frame:a", source_group="camB"))
    layer.ingest(obs("sw", (0.1, 0.1, 1.9, 1.9), observation_kind="swept",
                     claim=CLAIM_FREE, source_group="depth", frame_ref="frame:sw"))
    layer.ingest(obs("bad", (0.1, 0.1, 0.9, 0.9), claim=CLAIM_FREE))   # 거절 1건
    layer.element("rock", born_at=0.0).record_sighting(NOW - 5.0)
    layer.element("rock").record_absence(NOW - 1.0)

    cell = layer.cell((0, 0), now=NOW)
    payloads = {
        "mass": cell.mass.as_dict(),
        "cell": cell.as_dict(),
        "contribution": cell.contributions[0].as_dict(),
        "rejected": layer.rejected()[0].as_dict(),
        "summary": layer.summarize((0.0, 0.0, 2.9, 2.9), now=NOW).as_dict(),
        "datum": layer.datum.as_dict(),
        "local_position": layer.position_in((1.0, 2.0), FRAME_ZONE,
                                            local_accuracy_m=0.2).as_dict(),
        "global_position": layer.position_in((1.0, 2.0), FRAME_GLOBAL,
                                             local_accuracy_m=0.2).as_dict(),
        "refused_position": layer.position_in((1.0, 2.0), "MOON").as_dict(),
        "cell_position": layer.cell_position((0, 0), now=NOW).as_dict(),
        "persistence": layer.persistence("rock", NOW).as_dict(),
        "map": layer.as_dict(now=NOW),
        "region_map": layer.as_dict((0.0, 0.0, 1.9, 1.9), now=NOW),
    }
    for name, payload in payloads.items():
        assert dd.unknown_fields(payload) == (), f"{name} 이 사전 밖 이름을 냈다"

    # 중첩된 행도 같은 규약을 따른다(구조 칸 둘만 예외이고 그 사실은 위에서 고정했다).
    for row in payloads["map"][dd.MAP_CELLS]:
        assert dd.unknown_fields(row) == ()
        for contribution in row[dd.CONTRIBUTIONS]:
            assert dd.unknown_fields(contribution) == ()
    for row in payloads["cell"][dd.CONTRIBUTIONS]:
        assert dd.unknown_fields(row) == ()
    for row in payloads["map"][dd.REJECTED_OBSERVATIONS]:
        assert dd.unknown_fields(row) == ()

    # 값들이 어휘 안에 있는지도 함께 본다 — 이름만 맞고 값이 밖이면 소용이 없다.
    assert payloads["cell"][dd.CELL_STATE] in dd.CELL_STATES
    assert payloads["contribution"][dd.TWIN_MAP_CLAIM] in dd.TWIN_MAP_CLAIMS
    assert payloads["contribution"][dd.POSE_QUALITY] in dd.POSE_QUALITIES
    assert payloads["rejected"][dd.REJECTION_REASON] in dd.TWIN_MAP_REJECTION_REASONS
    assert payloads["refused_position"][dd.FRAME_REFUSAL_REASON] in dd.FRAME_REFUSAL_REASONS
    assert payloads["persistence"][dd.PERSISTENCE_EXPLAINED_BY] in dd.PERSISTENCE_EXPLANATIONS
    assert payloads["map"][dd.MAP_AUTHORITY] in dd.MAP_AUTHORITIES
    assert payloads["global_position"][dd.ACCURACY_LIMITED_BY] in dd.ACCURACY_LIMITS
    assert payloads["region_map"][dd.MAP_REGION_ID]


def test_the_map_payload_keeps_local_and_global_apart(layer):
    """지도 한 장은 로컬 격임을 밝히고 datum 은 **참조로만** 싣는다(AI-C-02)."""
    layer.ingest(obs("o", (0.1, 0.1, 0.9, 0.9)))
    body = layer.as_dict(now=NOW)

    assert body[dd.COORDINATE_FRAME] == FRAME_ZONE
    assert body[dd.MAP_AUTHORITY] == MAP_AUTHORITY_SITE_LOCAL
    assert body[dd.DATUM_ID] is None, "datum 이 없는 배치가 정상이다"
    assert dd.GLOBAL_POSITION not in body, "지도 본문에 전역 좌표가 섞이지 않는다"
    assert body[dd.CELL_SIZE_M] == 1.0
    assert len(body[dd.MAP_CELLS]) == 1


# --- 선언·축소 ---------------------------------------------------------------

def test_detection_alone_is_enough_and_the_rest_is_optional(layer):
    """탐지 하나만 있으면 지도는 성립한다. 결손은 DEGRADED 까지만 내려간다(AI-C-05)."""
    assert layer.capability_state({"perception.detect"}) is CapabilityState.DEGRADED
    assert layer.capability_state(set()) is CapabilityState.DISABLED
    assert layer.capability_state(
        {"perception.detect", "perception.depth", "perception.point_cloud",
         "reference.zone_profile", "reference.human_survey",
         "reference.site_datum"}) is CapabilityState.ACTIVE
    assert "reference.site_datum" in REQUIREMENT.optional


def test_an_observation_kind_spec_refuses_an_unregistered_tier():
    with pytest.raises(ValueError):
        MapObservationKindSpec("k", "vibes")
    with pytest.raises(ValueError):
        MapObservationKindSpec("k", TIER_ESTIMATED, half_life_s=0.0)
    with pytest.raises(ValueError):
        MapObservationKindSpec("", TIER_ESTIMATED)


def test_an_observation_may_not_declare_certainty():
    """질량 1 은 어떤 반대 근거로도 움직이지 않는 칸을 만든다. 관측은 확정이 아니다."""
    with pytest.raises(ValueError):
        obs("certain", (0.0, 0.0, 1.0, 1.0), strength=1.0)
    with pytest.raises(ValueError):
        MapObservation(observation_id="", source_group="s", frame_ref="f",
                       observed_at=0.0, observation_kind="object_detection",
                       claim=CLAIM_OCCUPIED, footprint=(0.0, 0.0, 1.0, 1.0),
                       frame_id="zone")
    assert BeliefMass.from_claim(CLAIM_OCCUPIED, 1.0).occupied < 1.0
    with pytest.raises(ValueError):
        BeliefMass.from_claim("sideways", 0.5)


def test_an_uncertain_position_touches_more_cells_more_weakly():
    """한 칸만 세게 건드리면 자리의 불확실성이 확신으로 보인다."""
    layer = TwinMapLayer(cell_size_m=1.0, frame_id="zone")
    sharp = observation_from_point("s", source_group="camA", frame_ref="f1",
                                   observed_at=NOW, position=(5.5, 5.5),
                                   frame_id="zone")
    fuzzy = observation_from_point("z", source_group="camA", frame_ref="f2",
                                   observed_at=NOW, position=(1.5, 1.5),
                                   frame_id="zone", position_accuracy_m=1.2)

    assert len(layer.ingest(sharp)) == 1
    assert len(layer.ingest(fuzzy)) > 1


def test_a_declared_pose_quality_is_read_from_the_declaration_not_the_vendor():
    """판정 재료는 "누가 확인했다고 적혀 있는가" 뿐이다(규칙 7)."""
    assert declared_pose_quality({"calibration": {"verified_at": "2026-11-01"}}) == POSE_VALIDATED
    assert declared_pose_quality({"calibration": {"profile_version": "v3"}}) == "estimated"
    assert declared_pose_quality({}) == POSE_DECLARED
    assert declared_pose_quality({"vendor": "SomeBrand"}) == POSE_DECLARED


def test_a_profile_becomes_prior_tier_observations_only():
    """프로파일 한 판이 하나의 원본이다 — 같은 파일의 두 줄은 독립 지지가 아니다."""
    profile = {"domains": [{"domain_id": "d1", "zones": [
        {"zone_id": "z1", "infrastructure": [
            {"id": "cam-1", "kind": "camera", "at": {"x": 1.0, "y": 2.0}},
            {"id": "cam-2", "kind": "camera", "at": {"x": 1.2, "y": 2.2}},
            {"id": "no-place", "kind": "camera"},
        ]},
    ]}]}
    rows = prior_observations_from_domain_profile(profile, "z1")

    assert [r.observation_id for r in rows] == ["declared:z1:cam-1", "declared:z1:cam-2"]
    assert {r.frame_ref for r in rows} == {"zone_profile:d1"}
    assert {r.observation_kind for r in rows} == {"declared_obstacle"}
    assert prior_observations_from_domain_profile(profile, "nope") == ()

    layer = TwinMapLayer(cell_size_m=1.0, frame_id="zone")
    for row in rows:
        layer.ingest(row)
    cell = layer.cell((1, 2), now=NOW)
    assert cell.observed_support == 0 and cell.state is CellState.UNKNOWN


def test_a_datum_is_declared_and_never_guessed_from_an_address():
    """주소는 변환이 아니고 정확도도 없다 — 거기서 원점을 추측하면 측량값과 같이 앉는다."""
    with_datum = {"domains": [{"domain_id": "d1", "datum": {
        "datum_id": "survey", "local_frame": "zone", "accuracy_m": 0.05,
        "offset": {"x": 7.0, "y": 8.0}, "tier": "measured", "source": "국가기준점"}}]}
    address_only = {"domains": [{"domain_id": "d2", "site": {"address": "어딘가 1-2"}}]}

    datum = datum_from_profile(with_datum, "d1")
    assert datum is not None and datum.quantified
    assert datum.offset == (7.0, 8.0) and datum.tier == TIER_MEASURED
    assert datum_from_profile(address_only, "d2") is None
    assert datum_from_profile(with_datum, "no_such_domain") is None
    assert dd.unknown_fields(datum.as_dict()) == ()


def test_a_datum_rotates_before_it_translates():
    datum = SiteDatum(datum_id="r", local_frame="zone", offset=(0.0, 0.0),
                      rotation_deg=90.0, accuracy_m=0.1)
    x, y = datum.to_global((1.0, 0.0))
    assert (x, y) == (pytest.approx(0.0), pytest.approx(1.0))
