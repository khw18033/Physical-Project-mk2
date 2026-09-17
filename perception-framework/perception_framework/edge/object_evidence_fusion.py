"""Multi-instance evidence fusion orchestrator for one frame (AI-S-01, AI-S-06).

implements: AI-S-01, AI-S-02, AI-S-06, AI-C-02, AI-C-11

2026-09-16 door/pedestal 랜드마크 통합 설계. `perception/object_record.py`
(`ProgressiveRecordBuilder`)는 "이 object_id에 이 근거를 더하라"만 알고,
한 프레임 안에 같은 클래스의 물리 객체가 여러 개 있을 때 "이 박스가 어느
객체의 것인가"를 정하는 건 호출부의 책임이다(모듈 자체 docstring: "no global
transform is performed here"). 이 모듈이 그 association을 맡는다 — PoC에서
실측 검증된 방식(IoU **또는** 포함관계(containment) 중 하나만 넘으면 같은
물리 객체로 본다) 그대로다.

**왜 포함관계도 봐야 하는가(PoC에서 실측으로 확인된 이유)**: 같은 사람의
상반신 박스와 전신 박스처럼 스케일이 크게 다른 두 근거는 IoU만으로는 겹침이
낮게 나온다(예: 작은 박스가 큰 박스 안에 완전히 들어있어도 IoU는 낮을 수
있음). "작은 쪽이 큰 쪽 안에 거의 다 들어있다"는 포함관계를 OR 조건으로
추가해야 부위별로 조각난 근거가 같은 트랙으로 합쳐진다.

이 모듈은 어떤 모델을 쓰는지 전혀 모른다 — provider들이 이미 `PerceptionResult`
(혹은 `score_candidates`가 낸 `DictionaryPerceptionResult`)로 변환한 결과만
받는다(AI-C-04/AI-C-11).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from perception_framework.perception.detection import PerceptionResult
from perception_framework.perception.object_record import (
    Evidence,
    Lifecycle,
    ObjectRecord,
    ProgressiveRecordBuilder,
)

DEFAULT_ASSOCIATION_IOU_THRESHOLD = 0.30
DEFAULT_ASSOCIATION_CONTAINMENT_THRESHOLD = 0.7

#: 의미 투표에 참여하지 않는 소스(예: FastSAM -- "마스크 전용, 기하만 보강").
MASK_ONLY_SOURCE_GROUPS = frozenset({"fastsam"})


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _containment(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """작은 쪽 면적 대비 교집합 비율 — 스케일이 다른 박스가 서로를 완전히
    감싸는 경우(부위 박스 vs 전신 박스)를 IoU보다 잘 잡는다."""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    smaller = min(area_a, area_b)
    return inter / smaller if smaller > 0 else 0.0


@dataclass(frozen=True)
class EvidenceSource:
    """provider 하나가 한 프레임에 대해 낸 결과 묶음. `source_group`은 이 근거의
    출처를 나타내는 opaque 문자열이다(AI-C-04) — object_record.py는 이 문자열의
    의미를 모른다."""

    source_group: str
    results: tuple[PerceptionResult, ...]


def filter_evidence_by_label_and_score(
    results: list[PerceptionResult] | tuple[PerceptionResult, ...],
    *,
    exact_label: str | None = None,
    min_score: float | None = None,
) -> list[PerceptionResult]:
    """provider가 낸 결과 중 일부만 특정 클래스의 근거로 받아들인다.

    2026-09-16 실제 로봇 리허설 반영(`class_features.json`의 클래스별
    `grounding_dino_evidence` 설정, `research/door_gate_harden/RESULT.md`) --
    open-vocabulary provider(GroundingDINO 등)는 어휘를 여러 개 동시에 주면
    라벨이 "door pedestal"처럼 섞이거나 점수가 낮은 박스도 함께 낸다. 그걸
    그대로 근거로 받으면 그 provider 호출 임계값(0.15/0.15 등)과 별개로 이
    "합류 지점"에서 한 번 더 걸러야 하는 사례가 실측으로 확인됐다 — door
    라벨이 정확히 일치하지 않거나 점수가 낮은 박스(예: 단상·화이트보드가
    섞여 나온 것)를 받아들이면 오탐이 되살아난다. 클래스별로 다른
    exact_label/min_score를 적용해야 하므로(전역으로 올리면 다른 랜드마크가
    사라지는 실측 사례가 있었다), provider 자체가 아니라 이 오케스트레이션
    지점에서 필터링한다(AI-C-04: provider는 자기 존재를 모르는 소비자 규칙에
    맞출 필요가 없다)."""
    out = []
    for r in results:
        if exact_label is not None and r.label != exact_label:
            continue
        if min_score is not None and r.confidence < min_score:
            continue
        out.append(r)
    return out


@dataclass
class ObjectEvidenceFusion:
    """한 대상 클래스(예: "door")에 대해, 여러 프레임에 걸쳐 여러 provider의
    근거를 지속 객체(zone-local track)로 누적한다.

    `object_record.py`의 `ObjectRecord.object_id`는 여기서는 AI가 구역 내에서
    부여하는 `zone_local_track_id`로 쓰인다(백엔드 `object-reference.
    schema.json`과의 필드 분리 — 백엔드가 부여하는 전역 object_id는 별도다,
    계획 문서 "데이터 계약" §3 참고).
    """

    association_iou_threshold: float = DEFAULT_ASSOCIATION_IOU_THRESHOLD
    association_containment_threshold: float = DEFAULT_ASSOCIATION_CONTAINMENT_THRESHOLD
    #: 2026-09-16 실제 로봇 리허설 반영(`confirm_pair_iou_min`, `class_features.
    #: json`의 door 설정, `research/door_gate_harden/RESULT.md`): 서로 다른
    #: "계열"(사전 매칭 vs 개방어휘)의 박스 중 가장 잘 맞는 한 쌍의 IoU가 이
    #: 값 이상이어야 CONFIRMED로 올린다. 실측 오탐은 전부 작은 사전-매칭
    #: 조각(창문·짙은 옷)이 개방어휘 provider의 큰 단상·사람 박스 안에
    #: containment로만 묶여 "서로 다른 소스 2개 동의"가 성립한 경우였다 --
    #: **containment 기반 association 자체는 끄지 않는다**(같은 물체의 부위
    #: 증거를 못 묶어 오탐이 오히려 남는다, 실측 확인됨). None이면 이 게이트를
    #: 적용하지 않는다(기존 동작 그대로, 하위호환).
    confirm_pair_iou_min: float | None = None
    dictionary_source_groups: frozenset[str] = frozenset({"clip_dictionary"})
    open_vocabulary_source_groups: frozenset[str] = frozenset({"grounding_dino", "yolo_world"})
    builder: ProgressiveRecordBuilder = field(default_factory=ProgressiveRecordBuilder)
    _track_boxes: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)
    #: track_id -> {source_group: 그 소스가 이 트랙에 마지막으로 낸 박스}.
    #: `ProgressiveRecordBuilder._evidence`는 관측(observation) 하나가 끝날 때
    #: `close_observation()`이 비운다(그 관측 안에서만 쓰는 임시 버퍼) -- 이
    #: 게이트는 여러 관측(프레임)에 걸쳐 지속돼야 하므로 별도로 보관한다.
    _track_boxes_by_source: dict[str, dict[str, tuple[float, float, float, float]]] = field(default_factory=dict)
    _next_track_seq: int = 0

    def _match_or_create_track(self, box: tuple[float, float, float, float]) -> str:
        for track_id, existing_box in self._track_boxes.items():
            if (
                _iou(existing_box, box) >= self.association_iou_threshold
                or _containment(existing_box, box) >= self.association_containment_threshold
            ):
                return track_id
        self._next_track_seq += 1
        return f"zoneA-track-{self._next_track_seq}"

    def ingest_frame(
        self,
        frame_ref: str,
        observed_at: float,
        sources: list[EvidenceSource],
        *,
        available_groups: set[str] | None = None,
    ) -> list[ObjectRecord]:
        """한 프레임의 모든 provider 결과를 트랙별로 나눠 누적하고, 실제로
        가시 상태가 바뀐 레코드만 반환한다(`ProgressiveRecordBuilder.ingest`와
        동일한 "확인성 갱신만 노출" 규약)."""
        groups = available_groups if available_groups is not None else {s.source_group for s in sources}
        updated: list[ObjectRecord] = []
        seen_tracks: set[str] = set()
        for source_index, source in enumerate(sources):
            for result_index, result in enumerate(source.results):
                track_id = self._match_or_create_track(result.box)
                self._track_boxes[track_id] = result.box
                self._track_boxes_by_source.setdefault(track_id, {})[source.source_group] = result.box
                seen_tracks.add(track_id)
                evidence = Evidence(
                    evidence_id=f"{frame_ref}:{source.source_group}:{source_index}:{result_index}",
                    frame_ref=frame_ref,
                    source_group=source.source_group,
                    observed_at=observed_at,
                    available_at=time.time(),
                    kind="mask" if source.source_group in MASK_ONLY_SOURCE_GROUPS else "region",
                    confidence=result.confidence,
                    region=result.box,
                    label=None if source.source_group in MASK_ONLY_SOURCE_GROUPS else result.label,
                )
                record = self.builder.ingest(track_id, evidence, groups)
                if record is not None:
                    updated.append(record)
        self.builder.close_observation(seen_tracks)
        return updated

    def confirmed_objects(self) -> list[tuple[str, ObjectRecord]]:
        """`(zone_local_track_id, record)` — CONFIRMED lifecycle이고,
        `confirm_pair_iou_min`이 설정돼 있으면 그 게이트까지 통과한 것만."""
        return [
            (track_id, record)
            for track_id, record in self.builder.records.items()
            if record.lifecycle is Lifecycle.CONFIRMED and self._passes_pair_iou_gate(track_id)
        ]

    def _passes_pair_iou_gate(self, track_id: str) -> bool:
        if self.confirm_pair_iou_min is None:
            return True
        by_source = self._track_boxes_by_source.get(track_id, {})
        dict_boxes = [box for group, box in by_source.items() if group in self.dictionary_source_groups]
        ovd_boxes = [box for group, box in by_source.items() if group in self.open_vocabulary_source_groups]
        if not dict_boxes or not ovd_boxes:
            # 이 게이트는 "두 계열이 실제로 같은 지점을 가리키는가"를 묻는다 --
            # 애초에 한쪽 계열의 근거가 없으면(예: 사전 매칭 없이 개방어휘
            # 2개만 동의) 물을 수 없는 질문이므로 통과시키지 않는다. door
            # 랜드마크는 이미 `required_source`로 사전(CLIP) 동의를 강제하므로
            # 이 경로는 실무에서 도달하지 않는다.
            return False
        best_iou = max(_iou(d, o) for d in dict_boxes for o in ovd_boxes)
        return best_iou >= self.confirm_pair_iou_min
