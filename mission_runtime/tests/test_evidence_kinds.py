"""implements: AI-S-03, AI-S-05, AI-S-06
관련: AI-E-04, AI-S-08, AI-C-01, AI-C-05
covers: 흩어진 모듈의 출력이 한 계약으로 옮겨지는 것, 비식별 근거가 쌓여도 식별 근거를
        뒤집지 못하는 것, 같은 원본 관측에서 나온 둘이 독립으로 세어지지 않는 것,
        고르지 못할 때 1 위를 고르지 않고 무엇이 없는지 내는 것, 제공자가 없는 종류가
        오류가 아니라 미측정으로 나오는 것.

**어댑터에 넣는 입력을 지어내지 않는다.** 여기 있는 시험은 공개 트리의 실제 사전
(config/device_appearance_classes.example.json, 진짜 CLIP 512 차 벡터)으로 실제
`AppearanceClassifier` 를 돌리고, 실제 `motion_probe` · 실제 `fuse_zone` · 실제
`TwinFusionService` · 실제 `PriorInfoStore` · 실제 `resource_tag_cue` 를 돌려서 나온
출력을 어댑터에 넣는다. 모형 입력으로 재면 계약이 실제 모양과 어긋난 것을 영영 모른다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from conftest import PACKAGE_DIR

from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.perception import evidence_kinds as ek
from mission_runtime.perception.appearance_classifier import (
    REASON_NO_DICTIONARY,
    AppearanceClassifier,
    AppearanceDictionary,
    AppearanceState,
)
from mission_runtime.perception.device_class_estimator import (
    ClassProfiles,
    resource_tag_cue,
)
from mission_runtime.perception.device_identity import (
    DISCRIMINATING_CUES,
    CueKind,
    DeviceIdentityResolver,
    TrackMotion,
    Verdict,
    appearance_cue,
    motion_probe,
)
from mission_runtime.perception.environment_prior import (
    PriorInfoRecord,
    PriorInfoStore,
)
from mission_runtime.perception.object_record import (
    CONFIRMING_GROUPS,
    Evidence,
    ProgressiveRecordBuilder,
)
from mission_runtime.perception.spatial_evidence import (
    KIND_DEPTH,
    KIND_HUMAN_SURVEY,
    KIND_MULTI_DEVICE_DETECTION,
    SpatialObservation,
    fuse_zone,
)

DICTIONARY_PATH = PACKAGE_DIR / "config" / "device_appearance_classes.example.json"

CONSOLE_DIR = PACKAGE_DIR / "tools" / "fms_console"
if str(CONSOLE_DIR) not in sys.path:
    sys.path.insert(0, str(CONSOLE_DIR))


# ---------------------------------------------------------------------------
# 종류 선언 — 같은 규칙을 두 값으로 재지 않는다
# ---------------------------------------------------------------------------


def test_every_registered_kind_declares_its_owner_module_and_tier():
    registry = ek.DEFAULT_KIND_REGISTRY
    assert registry.kinds()
    for kind in registry.kinds():
        spec = registry.spec(kind)
        assert spec.origin, kind
        assert spec.tier in dd.SPATIAL_EVIDENCE_TIERS, kind
        assert spec.note, kind


def test_the_discriminating_set_agrees_with_device_identity():
    """식별력 판정은 `device_identity` 가 소유한다 — 여기서 다시 정하지 않는다.

    그 모듈이 아는 다섯 단서에 대해 우리 선언이 한 칸이라도 다르면 두 화면이 서로
    다른 답을 말한다. 그래서 어휘를 비교하는 시험을 둔다.
    """
    for cue_kind in CueKind:
        assert ek.DEFAULT_KIND_REGISTRY.is_discriminating(cue_kind.value) is (
            cue_kind in DISCRIMINATING_CUES), cue_kind


def test_thresholds_are_read_from_the_modules_that_own_them():
    owner = DeviceIdentityResolver()
    assert ek.DISCRIMINATING_MIN_STRENGTH == owner.discriminating_min_strength
    assert ek.DISCRIMINATING_MARGIN == owner.discriminating_margin
    assert ek.MIN_INDEPENDENT_SUPPORT == CONFIRMING_GROUPS


def test_every_reason_token_is_in_the_dictionary_vocabulary():
    """모듈이 문자열을 정하고 사전이 어휘를 소유한다(AI-C-01)."""
    tokens = {v for k, v in vars(ek).items()
              if k.startswith("REASON_") and isinstance(v, str)}
    assert tokens
    assert tokens <= set(dd.EVIDENCE_SUFFICIENCY_REASONS)


def test_evidence_rows_use_only_dictionary_names():
    row = ek.GroundedEvidence(
        evidence_id="e1", evidence_kind=ek.KIND_FIDUCIAL_MARKER, claim="go1-a",
        source_group="cam-a", frame_ref="f1", observed_at=1.0, strength=0.9)
    # `detail` 만 자유 형식이다 — 그 안의 이름은 근거를 낸 모듈의 소관이다.
    assert dd.unknown_fields(row.as_dict()) == ("detail",)


def test_evidence_without_a_frame_ref_is_refused():
    """독립성의 단위가 없으면 중복이 지지가 된다 — 그래서 받지 않는다(AI-S-06)."""
    with pytest.raises(ValueError):
        ek.GroundedEvidence(
            evidence_id="e1", evidence_kind=ek.KIND_MOTION_CORRELATION, claim="go1-a",
            source_group="probe", frame_ref="", observed_at=1.0, strength=1.0)


# ---------------------------------------------------------------------------
# 실제 모듈을 돌려 나온 출력을 어댑터에 넣는다
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_dictionary() -> AppearanceDictionary:
    return AppearanceDictionary.load(DICTIONARY_PATH)


@pytest.fixture(scope="module")
def real_appearance_verdict(real_dictionary):
    """실제 사전의 실제 CLIP 벡터 하나를 probe 로 넣어 받은 **진짜** 판정.

    자기 참조영상을 넣으므로 그 기종이 1 위로 나오는 것이 정상이고, 중요한 것은
    점수가 아니라 이 모듈이 내는 **모양**이다 — 어댑터가 읽는 것이 그 모양이다.
    """
    classifier = AppearanceClassifier(real_dictionary)
    probe_class = real_dictionary.fit_classes[0]
    verdict = classifier.classify_embedding(probe_class.embeddings[0])
    assert verdict.state in (AppearanceState.CLASSIFIED, AppearanceState.AMBIGUOUS)
    assert verdict.ranked
    return verdict


def test_a_real_appearance_verdict_becomes_non_discriminating_evidence(
        real_appearance_verdict):
    batch = ek.from_appearance_verdict(
        real_appearance_verdict, frame_ref="cam-a:frame-7",
        source_group="cam-a", observed_at=100.0)

    assert batch.evidence, "실제 판정의 순위가 근거로 옮겨지지 않았다"
    assert not batch.inactive
    kinds = {row.evidence_kind for row in batch.evidence}
    assert kinds == {ek.KIND_APPEARANCE_REFERENCE_SIMILARITY}
    # 순위에 오른 기종 전부가 근거다 — 1 위만 남기면 "왜 못 골랐는지"를 그릴 수 없다.
    assert len(batch.evidence) == len(real_appearance_verdict.ranked)
    # 점수를 만든 참조영상 파일 이름이 남는다(화면에 그대로 띄우는 단위).
    top = max(batch.evidence, key=lambda r: r.strength)
    assert top.detail[dd.FEATURE_SIMILARITIES]
    assert not ek.DEFAULT_KIND_REGISTRY.is_discriminating(top.evidence_kind)


def test_a_real_appearance_verdict_alone_never_confirms_an_identity(
        real_appearance_verdict):
    """사진이 1 위를 뚜렷하게 내도 개체 식별은 `met` 이 되지 않는다.

    외형은 **종류**만 말한다. 이 한 줄이 무너지면 같은 기종 두 대가 영원히 구분되지
    않는 채로 명령 대상이 된다(AI-S-03 의 "신뢰도와 근거 충분도는 다른 축").
    """
    batch = ek.from_appearance_verdict(
        real_appearance_verdict, frame_ref="cam-a:frame-7",
        source_group="cam-a", observed_at=100.0)

    outcome = ek.identity_assessor().assess(
        batch.evidence, claim_subject="device_identity")

    assert outcome.sufficiency_state == "unmet"
    assert outcome.reason == ek.REASON_ONLY_NON_DISCRIMINATING
    assert outcome.claim is None
    assert not outcome.sufficient
    # 무엇이 없어서 못 고르는지가 함께 나온다(AI-S-05 의 입구).
    assert ek.REQUEST_MOTION_PROBE in outcome.resolution_requests


def test_a_real_motion_probe_outcome_decides_what_photos_could_not():
    """실제 `motion_probe` 를 돌려 얻은 단서 하나가 사진 근거들을 이긴다.

    `device_identity` 의 규칙 — 비식별 단서가 아무리 쌓여도 식별 단서 하나를 뒤집지
    못한다 — 이 어댑터를 거친 뒤에도 보존되는지가 이 시험의 전부다.
    """
    probe = motion_probe(
        "go1-a",
        [TrackMotion("t1", displacement_m=1.4, observed_from=10.0, observed_to=10.8),
         TrackMotion("t2", displacement_m=0.02, observed_from=10.0, observed_to=10.8)],
        commanded_at=10.0, window_s=1.0, expected_min_m=0.3, margin_m=0.5)
    assert probe.discriminated and probe.moved_track_ids == ("t1",)

    photos = appearance_cue(["go1-a", "go1-b"], observed_at=9.0, source="cam-a",
                            confidence=0.93, robot_class="go1")
    batch = ek.collect(
        ek.from_identity_cues(photos),
        ek.from_identity_cues([probe.cues["t1"]]),
    )

    outcome = ek.identity_assessor().assess(
        batch.evidence, claim_subject="device_identity")

    assert outcome.sufficient
    assert outcome.claim == "go1-a"
    assert outcome.reason.startswith(ek.REASON_DISCRIMINATING_SUPPORTS)
    # 결론을 끌어온 근거는 식별 근거만이다 — 사진을 같은 자리에 적으면 화면을 보는
    # 사람은 그 둘이 같은 격이라고 읽는다.
    winner = next(row for row in outcome.ranked if row.claim == "go1-a")
    assert {row.evidence.evidence_kind for row in winner.driving_evidence} == {
        ek.KIND_MOTION_CORRELATION}

    # 그 하나를 빼면 판정이 무너진다. 이것이 "무엇 때문인가"의 유일한 답이다.
    rows = {row.removed: row for row in outcome.leave_one_out(unit="evidence_kind")}
    assert rows[ek.KIND_MOTION_CORRELATION].changed
    assert rows[ek.KIND_MOTION_CORRELATION].sufficiency_state == "unmet"
    assert not rows[ek.KIND_APPEARANCE_CLASS].changed


def test_the_contract_reaches_the_same_verdict_as_the_identity_resolver():
    """같은 단서 묶음에 대해 주인 모듈과 **같은 답**을 낸다.

    규칙을 복제한 것이 아니라 같은 뜻으로 맞췄다는 주장을 시험으로 고정한다 — 어긋나면
    "추론 근거" 화면과 개체 결속 화면이 서로 다른 말을 한다.
    """
    photos = appearance_cue(["go1-a", "go1-b"], observed_at=9.0, source="cam-a",
                            confidence=0.93, robot_class="go1")

    assert DeviceIdentityResolver().resolve("t1", photos).verdict is Verdict.AMBIGUOUS
    assert not ek.identity_assessor().assess(
        ek.from_identity_cues(photos).evidence,
        claim_subject="device_identity").sufficient


def test_the_adapter_uses_the_origin_the_cue_itself_carries():
    """`IdentityCue` 가 자기 `frame_ref` 를 들고 오면 **그것이 정본이다**(AI-S-06).

    단서를 낸 쪽만 자기가 무엇을 보고 냈는지 안다. 어댑터가 `(source, observed_at)`
    로 환산하면, 같은 프레임을 다른 순간에 읽은 둘이 서로 다른 원본으로 세어진다 —
    그러면 중복이 독립 지지가 된다.
    """
    same_frame = "cam-a:frame-7"
    first = appearance_cue(["go1-a"], observed_at=9.0, source="cam-a", confidence=0.9,
                           robot_class="go1", frame_ref=same_frame)
    # 같은 프레임을 조금 뒤에 다시 읽었다. 시각은 달라도 **한 번 본 것**이다.
    again = appearance_cue(["go1-a"], observed_at=9.4, source="cam-a", confidence=0.9,
                           robot_class="go1", frame_ref=same_frame)

    batch = ek.collect(ek.from_identity_cues(first), ek.from_identity_cues(again))

    assert {row.frame_ref for row in batch.evidence} == {same_frame}
    assert {row.observation_unit for row in batch.evidence} == {("cam-a", same_frame)}


def test_a_cue_without_an_origin_still_falls_back_to_the_conservative_unit():
    """원본 참조를 못 들고 오는 단서는 옛 환산으로 돌아간다 — 그 환산은 보수적이다."""
    photos = appearance_cue(["go1-a"], observed_at=9.0, source="cam-a",
                            confidence=0.9, robot_class="go1")

    row = ek.from_identity_cues(photos).evidence[0]

    assert row.frame_ref == "cam-a@9.0"


def test_two_results_from_the_same_frame_are_one_independent_support():
    """같은 프레임을 탐지기와 분류기가 각각 읽은 것은 **한 번 본 것**이다(AI-S-06).

    같은 사진이 세 모듈을 거쳐 세 이름(`appearance_class` ·
    `appearance_embedding` · `appearance_reference_similarity`)으로 들어와도
    `frame_ref` 가 같으므로 지지는 하나다. 이 규칙이 없으면 모듈을 늘리는 것만으로
    근거가 늘어난다.
    """
    frame = "cam-a:frame-7"
    rows = [
        ek.GroundedEvidence(
            evidence_id=f"e{i}", evidence_kind=kind, claim="go1",
            source_group="cam-a", frame_ref=frame, observed_at=1.0, strength=0.9)
        for i, kind in enumerate((ek.KIND_APPEARANCE_CLASS,
                                  ek.KIND_APPEARANCE_EMBEDDING,
                                  ek.KIND_APPEARANCE_REFERENCE_SIMILARITY))
    ]

    outcome = ek.support_count_assessor().assess(rows, claim_subject="device_class")

    support = outcome.ranked[0]
    assert support.independent_support == 1
    roles = sorted(row.role for row in support.rows)
    assert roles == [ek.ROLE_DEPENDENT, ek.ROLE_DEPENDENT, ek.ROLE_INDEPENDENT]
    assert outcome.sufficiency_state == "unmet"
    assert outcome.reason.startswith(ek.REASON_INDEPENDENT_SUPPORT_SHORT)


def test_a_real_spatial_fusion_keeps_the_human_survey_above_the_sensors():
    """실제 `fuse_zone` 의 기여 내역을 옮긴 뒤에도 사람 실측이 센서에 밀리지 않는다.

    `spatial_evidence` 는 그것을 `overrides` 로 표현하고 이 계약은 **식별력**으로
    표현한다. 두 표현이 같은 뜻이어야 한다 — 센서 근거가 몇 개 쌓이든 사람이 잰 값을
    뒤집지 못한다.
    """
    frame = "site:zone-a"
    state = fuse_zone(
        [
            SpatialObservation(
                evidence_id="depth-1", source_group="cam-a", frame_ref="cam-a:f1",
                observed_at=10.0, evidence_kind=KIND_DEPTH,
                quantity_id="camera.c1.at", value=(3.0, 4.0), frame_id=frame,
                accuracy_m=0.8),
            SpatialObservation(
                evidence_id="det-1", source_group="cam-b", frame_ref="cam-b:f1",
                observed_at=10.5, evidence_kind=KIND_MULTI_DEVICE_DETECTION,
                quantity_id="camera.c1.at", value=(3.4, 4.2), frame_id=frame,
                accuracy_m=0.6),
            SpatialObservation(
                evidence_id="survey-1", source_group="ops_web.survey",
                frame_ref="survey:2026-11-03", observed_at=20.0,
                evidence_kind=KIND_HUMAN_SURVEY, quantity_id="camera.c1.at",
                value=(3.2, 4.1), frame_id=frame, accuracy_m=0.05,
                entered_by="surveyor-1", entered_at=20.0),
        ],
        zone_id="zone-a", frame_id=frame)
    quantity = state.quantity("camera.c1.at")
    assert quantity.human_override, "실제 융합이 사람 실측으로 결정되지 않았다"

    batch = ek.from_spatial_quantity(quantity)
    assert {row.evidence_kind for row in batch.evidence} == {
        KIND_DEPTH, KIND_MULTI_DEVICE_DETECTION, KIND_HUMAN_SURVEY}

    outcome = ek.identity_assessor().assess(
        batch.evidence, claim_subject="zone_quantity")
    assert outcome.sufficient
    assert outcome.claim == "camera.c1.at"
    winner = outcome.ranked[0]
    assert {row.evidence.evidence_kind for row in winner.driving_evidence} == {
        KIND_HUMAN_SURVEY}

    # 센서만으로는 식별 경로가 열리지 않는다 — 공간 값에서도 같은 축이다.
    sensors_only = tuple(row for row in batch.evidence
                         if row.evidence_kind != KIND_HUMAN_SURVEY)
    assert not ek.identity_assessor().assess(
        sensors_only, claim_subject="zone_quantity").sufficient
    # 독립 출처를 묻는 질문에는 센서 둘이 충분하다(`object_record` 와 같은 기준).
    counted = ek.support_count_assessor().assess(
        sensors_only, claim_subject="zone_quantity")
    assert counted.sufficient and counted.ranked[0].independent_support == 2


def test_a_real_twin_ledger_agrees_with_our_independence_rule():
    """`twin.py` 가 `(장치, 프레임)` 으로 세는 것과 우리가 세는 것이 같은 답이다.

    규칙을 두 곳에서 따로 정하면 같은 객체가 두 화면에서 서로 다른 지지 수를 갖는다.
    """
    import twin  # noqa: PLC0415 - 도구 디렉터리는 sys.path 를 넣은 뒤에만 보인다

    service = twin.TwinFusionService()
    service.register_device(twin.DevicePlacement("cam-a", "z1", (0.0, 0.0, 0.0),
                                                 camera_id="a"))
    bbox = (0.45, 0.4, 0.55, 0.6)
    for detection in (
        twin.DeviceDetection("d1", "cam-a", 1, "cam-a:f1", 10.0, bbox,
                             label="person", confidence=0.8, range_m=5.0,
                             provider_id="detector"),
        # 같은 프레임을 다른 provider 가 한 번 더 읽었다 — 두 번 본 것이 아니다.
        twin.DeviceDetection("d2", "cam-a", 1, "cam-a:f1", 10.0, bbox,
                             label="person", confidence=0.7, range_m=5.0,
                             provider_id="classifier"),
        twin.DeviceDetection("d3", "cam-a", 1, "cam-a:f2", 10.5, bbox,
                             label="person", confidence=0.75, range_m=5.0,
                             provider_id="detector"),
    ):
        service.ingest_detection(detection)

    records = service.records("z1")
    assert len(records) == 1
    object_id = records[0].object_id
    ledger = service.evidence_rows(object_id)
    assert len(ledger) == 3
    twin_independent = {row.evidence_id: row.independent for row in ledger}
    assert sum(twin_independent.values()) == 2, "twin 쪽 전제가 바뀌었다"

    batch = ek.from_twin_evidence_rows(ledger)
    outcome = ek.support_count_assessor().assess(
        batch.evidence, claim_subject="object_class")
    support = next(row for row in outcome.ranked if row.claim == "person")

    ours = {row.evidence.evidence_id: row.role == ek.ROLE_INDEPENDENT
            for row in support.rows}
    assert ours == twin_independent
    assert support.independent_support == 2
    assert outcome.sufficient


def test_real_object_record_evidence_moves_into_the_contract():
    """실제 `ProgressiveRecordBuilder` 가 소비한 근거를 같은 계약으로 옮긴다."""
    builder = ProgressiveRecordBuilder()
    rows = (
        Evidence("ev-1", "cam-a:f1", "det_a", 10.0, 10.1, "region", 0.8,
                 region=(0.0, 0.0, 1.0, 1.0), label="person"),
        Evidence("ev-2", "cam-b:f1", "det_b", 10.0, 10.2, "semantic", 0.7,
                 label="person"),
    )
    for row in rows:
        builder.ingest("obj-1", row, available_groups={"det_a", "det_b"})
    record = builder.records["obj-1"]
    assert record.evidence_sufficient, "object_record 쪽 전제가 바뀌었다"

    batch = ek.from_object_record_evidence(rows, object_id="obj-1")
    outcome = ek.support_count_assessor().assess(
        batch.evidence, claim_subject="object_class")

    assert {r.evidence_kind for r in batch.evidence} == {
        ek.KIND_RECORD_REGION, ek.KIND_RECORD_SEMANTIC}
    # 같은 결론에 두 출처 묶음이 붙었다 — object_record 의 CONFIRMING_GROUPS 와 같은 수.
    assert outcome.sufficient
    assert outcome.ranked[0].independent_support == CONFIRMING_GROUPS


def test_real_prior_records_never_confirm_on_their_own():
    """사전정보만으로는 확정하지 않는다(AI-S-08).

    유효한 사전정보가 둘이어서 독립 지지 수를 채워도 `met` 이 아니다 — 격이 전부
    `declared` 이기 때문이고, 그것이 "실제 관측과 분리해 관리한다" 의 코드상 표현이다.
    """
    store = PriorInfoStore()
    store.register(PriorInfoRecord(
        record_id="facility-1", kind="INFRASTRUCTURE", source="facility_cad",
        scope=("zone-a",), created_at=1.0, updated_at=1.0, version="v1"))
    store.register(PriorInfoRecord(
        record_id="history-1", kind="HISTORICAL_OBSERVATION", source="ops_log",
        scope=("zone-a",), created_at=2.0, updated_at=2.0, version="v1"))
    store.register(PriorInfoRecord(
        record_id="stale-1", kind="MISSION", source="mission_plan",
        scope=("zone-a",), created_at=0.0, updated_at=0.0, version="v1",
        valid_until=5.0))

    usable = store.usable(now=10.0, scope="zone-a")
    assert {r.record_id for r in usable} == {"facility-1", "history-1"}

    batch = ek.from_prior_records(
        store._records.values(), now=10.0, claim_of=lambda r: "door-at-north")
    assert len(batch.evidence) == 2
    assert ek.KIND_ENVIRONMENT_PRIOR not in batch.inactive  # 유효한 것이 있으므로

    outcome = ek.support_count_assessor().assess(
        batch.evidence, claim_subject="environment_state")
    assert outcome.ranked[0].independent_support == 2
    assert outcome.sufficiency_state == "unmet"
    assert outcome.reason == ek.REASON_ONLY_DECLARED_PRIORS


def test_a_real_resource_tag_cue_exclusion_cannot_be_outvoted_by_photos():
    """실제 `resource_tag_cue` 의 배제가 사진 지지를 이긴다.

    `device_class_estimator` 는 그것을 `ClassCueSpec.decisive` 로 표현하고 이 계약은
    `refutes` + 식별력으로 표현한다. 두 표현이 같은 뜻이어야 한다.
    """
    profiles = ClassProfiles.load(DICTIONARY_PATH)
    assert profiles.profiles, "공개 사전에 기종 프로파일이 없다"

    cue = resource_tag_cue(["platform.uav", "tier.uav"], profiles,
                           observed_at=10.0, source="join-declaration")
    assert cue.excludes, "실제 태그 단서가 아무 기종도 배제하지 않았다"
    excluded = sorted(cue.excludes)

    batch = ek.collect(
        ek.from_class_cues([cue]),
        ek.from_appearance_verdict(
            _fake_free_verdict(excluded[0]), frame_ref="cam-a:f1",
            source_group="cam-a", observed_at=9.0),
    )

    outcome = ek.support_count_assessor().assess(
        batch.evidence, claim_subject="device_class")

    blocked = next(row for row in outcome.ranked if row.claim == excluded[0])
    assert blocked.excluded
    assert blocked.excluded_by[0] == ek.KIND_RESOURCE_TAGS
    assert outcome.claim != excluded[0]


class _Score:
    """`AppearanceVerdict.ranked` 와 같은 모양의 최소 행.

    여기서만 모양을 흉내 낸다 — 배제 시험이 필요한 것은 "그 기종을 사진이 강하게
    지지한다" 는 상황 하나이고, 실제 분류기는 임의의 기종을 1 위로 내게 만들 수
    없기 때문이다. 어댑터가 읽는 칸만 들고 있다.
    """

    def __init__(self, class_name: str) -> None:
        self.class_name = class_name
        self.label = class_name
        self.score = 0.99
        self.driving_references = ()


class _Verdict:
    state = AppearanceState.CLASSIFIED
    reason = "separated_from_runner_up"
    model_version = "test"

    def __init__(self, class_name: str) -> None:
        self.ranked = (_Score(class_name),)


def _fake_free_verdict(class_name: str) -> _Verdict:
    return _Verdict(class_name)


# ---------------------------------------------------------------------------
# 없는 것이 정상인 설치 (AI-C-05)
# ---------------------------------------------------------------------------


def test_a_node_without_the_dictionary_reports_unmeasured_not_an_error():
    """사전이 없는 노드에서도 모듈이 돌고, 그 사실은 '정상' 이 아니라 '미측정' 이다."""
    classifier = AppearanceClassifier(AppearanceDictionary.missing(REASON_NO_DICTIONARY))
    verdict = classifier.classify_embedding([0.0] * 512)
    assert verdict.state is AppearanceState.NO_REFERENCE

    batch = ek.from_appearance_verdict(verdict, frame_ref="cam-a:f1",
                                       source_group="cam-a", observed_at=1.0)

    assert batch.evidence == ()
    assert batch.inactive == {
        ek.KIND_APPEARANCE_REFERENCE_SIMILARITY: REASON_NO_DICTIONARY}

    outcome = ek.identity_assessor().assess(
        batch.evidence, claim_subject="device_identity", inactive=batch.inactive)
    assert outcome.unavailable_kinds[ek.KIND_APPEARANCE_REFERENCE_SIMILARITY] == (
        REASON_NO_DICTIONARY)
    # 미측정과 미관측은 같은 칸에 들어가지 않는다.
    assert ek.KIND_APPEARANCE_REFERENCE_SIMILARITY not in outcome.unobserved_kinds
    assert ek.KIND_MOTION_CORRELATION in outcome.unobserved_kinds


def test_no_discriminating_provider_is_unobtainable_not_unmet():
    """가릴 수 있는 종류의 제공자가 하나도 없으면 그 질문은 지금 답할 수 없다.

    `unmet`("아직 모은 근거가 모자라다")과 `unobtainable`("이 배치로는 만들 수 없다")을
    같은 칸에 넣으면 운영자가 더 기다려야 하는지 장비를 들여야 하는지 알 수 없다.
    사진이 아무리 와도 같은 답이다 — 더 기다려서 될 일이 아니기 때문이다.
    """
    empty = ek.identity_assessor().assess(
        (), claim_subject="device_identity",
        available_capability_kinds={"perception.classify"})

    assert empty.sufficiency_state == "unobtainable"
    assert empty.reason == ek.REASON_NO_DISCRIMINATING_PROVIDER
    assert empty.sufficiency_state in dd.SUFFICIENCY_STATES

    photos = ek.from_identity_cues(appearance_cue(
        ["go1-a", "go1-b"], observed_at=1.0, source="cam-a",
        confidence=0.95, robot_class="go1")).evidence
    with_photos = ek.identity_assessor().assess(
        photos, claim_subject="device_identity",
        available_capability_kinds={"perception.classify"})

    assert with_photos.sufficiency_state == "unobtainable"
    assert with_photos.reason == ek.REASON_NO_DISCRIMINATING_PROVIDER


def test_evidence_from_a_vanished_source_is_absent_not_counter_evidence():
    """장치가 사라진 근거는 **반대 근거가 아니라 없는 것**이다(AI-C-05)."""
    rows = [
        ek.GroundedEvidence(
            evidence_id="probe-1", evidence_kind=ek.KIND_MOTION_CORRELATION,
            claim="go1-a", source_group="probe", frame_ref="probe:1",
            observed_at=1.0, strength=0.9),
    ]

    outcome = ek.identity_assessor().assess(
        rows, claim_subject="device_identity",
        available_capability_kinds={"perception.classify", "radio.ranging"})

    assert [row.reason for row in outcome.rejected] == [ek.REJECT_UNAVAILABLE]
    assert outcome.sufficiency_state == "unmet"
    assert outcome.reason == ek.REASON_NO_EVIDENCE
    assert ek.KIND_MOTION_CORRELATION in outcome.unavailable_kinds


def test_a_question_only_asks_for_what_its_own_scope_can_answer():
    """개체 식별 화면에 "구역을 실측해 달라" 가 뜨면 운영자는 엉뚱한 일을 하게 된다.

    범위 밖 근거는 조용히 쓰이지 않고 사유로 남고, 결손·요청도 범위 안에서만 낸다.
    """
    photos = ek.from_identity_cues(appearance_cue(
        ["go1-a"], observed_at=1.0, source="cam-a", confidence=0.9,
        robot_class="go1")).evidence
    spatial = (ek.GroundedEvidence(
        evidence_id="survey-1", evidence_kind=KIND_HUMAN_SURVEY,
        claim="go1-a", source_group="ops_web.survey", frame_ref="survey:1",
        observed_at=2.0, strength=1.0),)

    outcome = ek.identity_assessor().assess(
        photos + spatial, claim_subject=ek.SUBJECT_DEVICE_IDENTITY)

    assert [(row.evidence_kind, row.reason) for row in outcome.rejected] == [
        (KIND_HUMAN_SURVEY, ek.REJECT_OUT_OF_SCOPE)]
    assert not outcome.sufficient, "범위 밖 근거가 식별을 확정시켰다"
    assert ek.REQUEST_HUMAN_SURVEY not in outcome.resolution_requests
    assert KIND_HUMAN_SURVEY not in outcome.missing_kinds
    assert set(outcome.resolution_requests) == {
        ek.REQUEST_MOTION_PROBE, ek.REQUEST_ATTACH_FIDUCIAL,
        ek.REQUEST_ENABLE_RADIO_RANGING}


def test_one_assessor_answers_two_questions_without_leaking_conditions():
    """같은 평가자를 두 질문에 써도 앞 호출의 가용 집합이 다음 판정에 새지 않는다.

    가용 집합을 평가자에 저장하면 "식별 종류가 없다" 가 다음 질문으로 번지고, 그
    번짐은 화면에서 `unobtainable` 로 보인다 — 실제로는 가릴 수 있는 배치인데도.
    leave-one-out 은 반대로 **같은 조건**으로 다시 돌아야 한다.
    """
    assessor = ek.identity_assessor()
    probe = motion_probe(
        "go1-a", [TrackMotion("t1", 1.4, 10.0, 10.8)],
        commanded_at=10.0, window_s=1.0, expected_min_m=0.3, margin_m=0.5)
    rows = ek.from_identity_cues([probe.cues["t1"]]).evidence

    narrow = assessor.assess(
        (), claim_subject=ek.SUBJECT_DEVICE_IDENTITY,
        available_capability_kinds={"perception.classify"})
    assert narrow.sufficiency_state == "unobtainable"

    # 가용성을 모르는 호출은 모름을 '없음' 으로 바꾸지 않는다.
    unknown = assessor.assess(rows, claim_subject=ek.SUBJECT_DEVICE_IDENTITY)
    assert unknown.sufficient
    assert unknown.available_capability_kinds is None

    wide = assessor.assess(
        rows, claim_subject=ek.SUBJECT_DEVICE_IDENTITY,
        available_capability_kinds={"control.motion_probe"})
    assert wide.sufficient
    assert wide.available_capability_kinds == frozenset({"control.motion_probe"})
    # 조건은 판정에 실려 다니므로 leave-one-out 이 같은 조건으로 다시 돈다.
    for row in wide.leave_one_out(unit="evidence_kind"):
        assert row.sufficiency_state in dd.SUFFICIENCY_STATES


def test_an_unregistered_kind_is_rejected_with_a_reason_not_silently_dropped():
    rows = [
        ek.GroundedEvidence(
            evidence_id="x1", evidence_kind="typo_kind", claim="go1-a",
            source_group="cam-a", frame_ref="f1", observed_at=1.0, strength=1.0),
    ]

    outcome = ek.identity_assessor().assess(rows, claim_subject="device_identity")

    assert [row.reason for row in outcome.rejected] == [ek.REJECT_UNREGISTERED]
    assert outcome.ranked == ()


# ---------------------------------------------------------------------------
# 고르지 못하면 고르지 않는다 (AI-S-04, AI-S-05)
# ---------------------------------------------------------------------------


def test_two_discriminating_cues_that_are_too_close_do_not_pick_a_winner():
    rows = [
        ek.GroundedEvidence(
            evidence_id=f"radio-{device}", evidence_kind=ek.KIND_RADIO_RANGE,
            claim=device, source_group="radio", frame_ref=f"radio:{device}",
            observed_at=1.0, strength=strength)
        for device, strength in (("go1-a", 0.62), ("go1-b", 0.58))
    ]

    outcome = ek.identity_assessor().assess(rows, claim_subject="device_identity")

    assert outcome.sufficiency_state == "contested"
    assert outcome.reason.startswith(ek.REASON_DISCRIMINATING_TOO_CLOSE)
    assert outcome.claim is None
    assert set(outcome.contradicted_claims) == {"go1-a", "go1-b"}


def test_a_sole_candidate_without_a_discriminating_cue_is_named_but_not_bound():
    """`device_identity.SOLE_CANDIDATE` 와 같은 뜻 — 이름은 적고 결속으로는 쓰지 않는다."""
    photos = appearance_cue(["go1-a"], observed_at=1.0, source="cam-a",
                            confidence=0.9, robot_class="go1")

    outcome = ek.identity_assessor().assess(
        ek.from_identity_cues(photos).evidence, claim_subject="device_identity")

    assert outcome.claim == "go1-a"
    assert not outcome.sufficient
    assert outcome.reason == ek.REASON_SOLE_CANDIDATE


def test_the_same_input_always_yields_the_same_answer():
    """같은 입력이 실행마다 다른 순위를 내면 그 순위를 근거로 한 설명은 재현되지 않는다."""
    rows = [
        ek.GroundedEvidence(
            evidence_id=f"e{i}", evidence_kind=ek.KIND_APPEARANCE_CLASS, claim=claim,
            source_group=f"cam-{i}", frame_ref=f"cam-{i}:f1", observed_at=1.0,
            strength=0.5)
        for i, claim in enumerate(("go1-b", "go1-a", "go1-c"))
    ]
    first = ek.support_count_assessor().assess(rows, claim_subject="device_class")
    second = ek.support_count_assessor().assess(
        list(reversed(rows)), claim_subject="device_class")

    assert [row.claim for row in first.ranked] == [row.claim for row in second.ranked]
    assert first.claim == second.claim
    assert first.reason == second.reason


def test_the_explanation_carries_both_why_and_why_not():
    probe = motion_probe(
        "go1-a", [TrackMotion("t1", 1.4, 10.0, 10.8)],
        commanded_at=10.0, window_s=1.0, expected_min_m=0.3, margin_m=0.5)
    batch = ek.collect(
        ek.from_identity_cues([probe.cues["t1"]]),
        ek.from_identity_cues(appearance_cue(
            ["go1-a", "go1-b"], observed_at=9.0, source="cam-a",
            confidence=0.9, robot_class="go1")),
    )

    payload = ek.identity_assessor().assess(
        batch.evidence, claim_subject="device_identity").explanation()

    for name in (dd.CLAIM_SUBJECT, dd.SUFFICIENCY_STATE, dd.CLAIM, dd.SUFFICIENCY_REASON,
                 dd.OBSERVED_EVIDENCE_KINDS, dd.UNOBSERVED_EVIDENCE_KINDS,
                 dd.UNAVAILABLE_EVIDENCE_KINDS, dd.RESOLUTION_REQUESTS,
                 dd.LEAVE_ONE_OUT, dd.REJECTED_OBSERVATIONS):
        assert name in payload, name
    # 사전에 없는 최상위 이름은 표현용 세 칸뿐이다 — 늘어나면 사전에 먼저 등록한다.
    assert set(dd.unknown_fields(payload)) == {
        "sufficient", "ranked", "contradicted_claims"}
    assert payload[dd.LEAVE_ONE_OUT], "leave-one-out 이 비어 있으면 설명이 아니다"
