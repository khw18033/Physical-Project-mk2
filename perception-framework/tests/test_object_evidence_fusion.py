"""implements: AI-S-01, AI-S-02, AI-S-06, AI-C-02, AI-C-11

Pure logic tests -- no ML model needed, synthetic PerceptionResult inputs.
"""
from perception_framework.edge.object_evidence_fusion import (
    EvidenceSource,
    ObjectEvidenceFusion,
    filter_evidence_by_label_and_score,
)
from perception_framework.perception.detection import PerceptionResult
from perception_framework.perception.object_record import Lifecycle


def test_single_object_needs_two_distinct_source_groups_to_confirm():
    fusion = ObjectEvidenceFusion()
    box = (10.0, 10.0, 50.0, 50.0)

    fusion.ingest_frame(
        "frame-1", 1.0,
        [EvidenceSource("clip_dictionary", (PerceptionResult(box, "door", 0.9),))],
    )
    assert fusion.confirmed_objects() == []

    fusion.ingest_frame(
        "frame-1", 1.0,
        [EvidenceSource("grounding_dino", (PerceptionResult(box, "door", 0.8),))],
    )
    confirmed = fusion.confirmed_objects()
    assert len(confirmed) == 1
    track_id, record = confirmed[0]
    assert record.semantic_class == "door"
    assert record.lifecycle is Lifecycle.CONFIRMED


def test_two_non_overlapping_instances_of_the_same_class_stay_separate():
    """2026-09 세션에서 실측 검증된 요구사항: 한 프레임에 같은 클래스가 여러
    개 있을 수 있고, 최상위 하나만 남기면 안 된다."""
    fusion = ObjectEvidenceFusion()
    box_left = (0.0, 0.0, 20.0, 20.0)
    box_right = (200.0, 0.0, 220.0, 20.0)

    for group in ("clip_dictionary", "grounding_dino"):
        fusion.ingest_frame(
            "frame-1", 1.0,
            [EvidenceSource(group, (
                PerceptionResult(box_left, "person", 0.7),
                PerceptionResult(box_right, "person", 0.7),
            ))],
        )

    confirmed = fusion.confirmed_objects()
    assert len(confirmed) == 2
    track_ids = {track_id for track_id, _ in confirmed}
    assert len(track_ids) == 2


def test_overlapping_boxes_from_different_sources_merge_into_one_track():
    fusion = ObjectEvidenceFusion()
    # Same physical object, slightly different boxes from two providers.
    fusion.ingest_frame(
        "frame-1", 1.0,
        [
            EvidenceSource("clip_dictionary", (PerceptionResult((10.0, 10.0, 50.0, 50.0), "door", 0.9),)),
            EvidenceSource("yolo_world", (PerceptionResult((12.0, 11.0, 49.0, 52.0), "door", 0.6),)),
        ],
    )

    confirmed = fusion.confirmed_objects()
    assert len(confirmed) == 1


def test_containment_merges_a_part_box_into_a_whole_box_track():
    """IoU만으로는 못 합치는 스케일 차이 큰 부위/전신 박스를 containment로
    같은 트랙으로 합친다."""
    fusion = ObjectEvidenceFusion()
    whole_body = (0.0, 0.0, 100.0, 200.0)
    upper_body_only = (10.0, 0.0, 90.0, 80.0)  # entirely inside whole_body, low IoU

    fusion.ingest_frame(
        "frame-1", 1.0,
        [
            EvidenceSource("grounding_dino", (PerceptionResult(whole_body, "person", 0.7),)),
            EvidenceSource("yolo_world", (PerceptionResult(upper_body_only, "person", 0.6),)),
        ],
    )

    confirmed = fusion.confirmed_objects()
    assert len(confirmed) == 1


def test_mask_only_source_contributes_geometry_but_not_semantic_votes():
    fusion = ObjectEvidenceFusion()
    box = (10.0, 10.0, 50.0, 50.0)

    # fastsam alone (mask-only, no label) must never confirm anything by itself.
    fusion.ingest_frame(
        "frame-1", 1.0,
        [EvidenceSource("fastsam", (PerceptionResult(box, "unused-label", 0.5),))],
    )
    assert fusion.confirmed_objects() == []

    fusion.ingest_frame(
        "frame-1", 1.0,
        [EvidenceSource("clip_dictionary", (PerceptionResult(box, "door", 0.9),))],
    )
    # Still only one distinct *semantic* source group (fastsam doesn't count).
    assert fusion.confirmed_objects() == []


def test_no_evidence_yields_no_confirmed_objects():
    fusion = ObjectEvidenceFusion()

    assert fusion.confirmed_objects() == []


def test_filter_evidence_by_label_and_score_drops_mismatched_or_weak_results():
    """2026-09-16 리허설 반영: 'door pedestal'처럼 섞인 라벨이나 저점수 박스는
    특정 클래스의 근거로 받아들이지 않는다."""
    results = [
        PerceptionResult((0, 0, 10, 10), "door", 0.4),
        PerceptionResult((0, 0, 10, 10), "door pedestal", 0.5),
        PerceptionResult((0, 0, 10, 10), "door", 0.1),
    ]

    filtered = filter_evidence_by_label_and_score(results, exact_label="door", min_score=0.25)

    assert filtered == [results[0]]


def test_confirm_pair_iou_min_rejects_a_containment_only_agreement():
    """2026-09-16 리허설 반영 회귀 테스트: 실측 오탐 패턴 -- 작은 사전(CLIP)
    박스가 개방어휘(OVD)의 훨씬 큰 박스 안에 포함되기만 해서(짝 IoU는 낮음)
    두 소스가 "동의"했다고 잘못 확정되는 걸 막는다."""
    fusion = ObjectEvidenceFusion(confirm_pair_iou_min=0.42)
    small_dictionary_box = (40.0, 40.0, 60.0, 60.0)     # area 400, tightly inside the big box
    big_ovd_box = (0.0, 0.0, 200.0, 200.0)              # area 40000 -- low IoU with the small box

    fusion.ingest_frame(
        "frame-1", 1.0,
        [
            EvidenceSource("clip_dictionary", (PerceptionResult(small_dictionary_box, "door", 0.9),)),
            EvidenceSource("grounding_dino", (PerceptionResult(big_ovd_box, "door", 0.5),)),
        ],
    )

    assert fusion.confirmed_objects() == []


def test_confirm_pair_iou_min_accepts_a_genuinely_overlapping_pair():
    fusion = ObjectEvidenceFusion(confirm_pair_iou_min=0.42)
    box_a = (10.0, 10.0, 50.0, 50.0)
    box_b = (12.0, 11.0, 49.0, 52.0)  # near-identical box -> high IoU

    fusion.ingest_frame(
        "frame-1", 1.0,
        [
            EvidenceSource("clip_dictionary", (PerceptionResult(box_a, "door", 0.9),)),
            EvidenceSource("grounding_dino", (PerceptionResult(box_b, "door", 0.6),)),
        ],
    )

    assert len(fusion.confirmed_objects()) == 1


def test_confirm_pair_iou_min_is_opt_in_and_does_not_change_default_behavior():
    fusion = ObjectEvidenceFusion()  # confirm_pair_iou_min defaults to None
    small_dictionary_box = (40.0, 40.0, 60.0, 60.0)
    big_ovd_box = (0.0, 0.0, 200.0, 200.0)

    fusion.ingest_frame(
        "frame-1", 1.0,
        [
            EvidenceSource("clip_dictionary", (PerceptionResult(small_dictionary_box, "door", 0.9),)),
            EvidenceSource("grounding_dino", (PerceptionResult(big_ovd_box, "door", 0.5),)),
        ],
    )

    assert len(fusion.confirmed_objects()) == 1
