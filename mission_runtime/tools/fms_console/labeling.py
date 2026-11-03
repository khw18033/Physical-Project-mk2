"""Ground truth a person made, kept apart from what a model guessed.

implements: AI-L-02 (학습 후보 격리·품질), AI-L-03 (사용자 확인·의미 정보 반영)
관련: AI-L-01, AI-L-09, AI-S-04, AI-C-08 (픽셀은 상태 계약으로 나가지 않는다), AI-C-19
tests: tests/test_fms_labeling.py

## 무엇을 만드는가

관제 웹에서 사람이 저장된 영상 위의 탐지를 보고, 상자를 끌어 고치고, class 와 거리를
바로잡아 **정답(GT)** 을 만든다. 그 GT 는 모델을 바로 바꾸지 않는다 — 사람이 확인한
학습 후보가 되어 AI-L-05 의 검증과 AI-L-07 의 단계적 적용을 지나야 운영에 닿는다.
그 분리가 AI-L-03 이고, 이 모듈이 그 경계를 지키는 자리다.

## 왜 모델이 낸 상자를 지우지 않는가

사람이 고친 상자만 남기면 "모델이 무엇을 틀렸는지" 가 사라진다. 틀린 정도가 바로
학습 가치이고, 그것을 버리면 어떤 사례가 어려웠는지 나중에 말할 수 없다. 그래서
`LabeledBox` 는 **모델이 낸 것**(`predicted`)과 **사람이 고친 것**(`corrected`)을
나란히 들고, 둘의 차이(IoU, 중심 이동, class 변경 여부)를 계산해 남긴다.

## 비어 있는 것과 아닌 것

사람이 **지운** 상자(모델이 없는 것을 봤다)와 **아직 손대지 않은** 상자는 다르다.
전자는 거짓 양성이라는 정답이고 후자는 정답이 없는 상태다. `BoxVerdict` 가 그 둘을
가르고, 손대지 않은 상자는 GT 에 들어가지 않는다 — 넣으면 검수하지 않은 모델 출력이
정답으로 승격되고, 그것이 AI-L-02 가 금지하는 바로 그 일이다.

## 프레임이 아니라 **출처**가 작업 단위다

라벨 목록을 프레임 한 줄로 늘어놓으면 그 상자가 어디서 온 데이터인지 사라진다.
우리 pi4 가 찍은 것과 공개 데이터셋에서 받은 것은 **다른 데이터**이고, 섞으면
기기별 학습(AI-L-09)이 오염된다 — 외부 데이터셋 사진을 라벨했는데 그 후보가
"pi4 가 본 것" 으로 적히면, 그 가중치가 어느 기기에서 나빠졌는지 되짚을 수 없다.

그래서 `LabelSource` 가 디렉터리마다 **무엇에서 왔는지**를 들고 다닌다. 우리 기기가
찍은 것(`device_capture`)과 임무 중 쌓인 것(`mission_capture`)에는 `device_id` 가
있고, 공개 데이터셋(`external_dataset`)에는 **없다** — 없는 것을 지어내지 않고
`dataset:<id>` 라는 다른 주체로 둔다. 출처 목록은 `config/label_sources*.json` 의
데이터이고 새 출처는 코드 변경이 아니다.

## 픽셀은 여기로 오지 않는다

프레임은 `frame_ref` 로 가리키고 바이트는 미디어 경로가 낸다(AI-C-08). 상자 좌표는
**정규화된 영상 좌표**(0..1)로 둔다 — 해상도가 다른 기기에서 같은 라벨을 쓸 수 있어야
하고, 픽셀 좌표로 두면 crop·zoom 이 바뀔 때 전부 틀린다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Iterable, Mapping

#: 상자 하나에 대한 사람의 판정.
class BoxVerdict(str, Enum):
    UNREVIEWED = "unreviewed"   # 아직 보지 않았다 — GT 가 아니다
    CONFIRMED = "confirmed"     # 모델이 맞았다
    ADJUSTED = "adjusted"       # 자리·크기를 고쳤다
    RELABELED = "relabeled"     # class 를 고쳤다
    REJECTED = "rejected"       # 없는 것을 봤다(거짓 양성)
    ADDED = "added"             # 모델이 놓친 것을 사람이 그렸다(거짓 음성)


#: GT 로 쓸 수 있는 판정. `UNREVIEWED` 가 빠져 있는 것이 요점이다.
GROUND_TRUTH_VERDICTS: frozenset[BoxVerdict] = frozenset({
    BoxVerdict.CONFIRMED, BoxVerdict.ADJUSTED, BoxVerdict.RELABELED,
    BoxVerdict.REJECTED, BoxVerdict.ADDED,
})

#: 사람이 고친 것으로 보는 판정 — 모델 출력과 다른 답을 담고 있다.
CORRECTING_VERDICTS: frozenset[BoxVerdict] = frozenset({
    BoxVerdict.ADJUSTED, BoxVerdict.RELABELED, BoxVerdict.REJECTED, BoxVerdict.ADDED,
})


#: 거리를 고쳤다고 볼 최소 차이(m). 부동소수 왕복으로 같은 값이 다르게 보이는 것을
#: 수정으로 세지 않기 위한 바닥일 뿐이며, 측정 정확도와는 상관이 없다.
RANGE_EPSILON_M = 0.01


class LabelingError(ValueError):
    """라벨 선언이 잘못됐다."""


def _check_box(box: tuple[float, float, float, float], where: str) -> tuple[float, ...]:
    """정규화 영상 좌표 (x1, y1, x2, y2). 픽셀이 아니다.

    해상도가 다른 기기에서 같은 라벨을 쓰려면 정규화해야 한다. 픽셀로 두면 crop 이나
    해상도가 바뀌는 순간 저장된 라벨 전부가 조용히 틀린 자리를 가리킨다.
    """
    if len(box) != 4:
        raise LabelingError(f"{where}: a box is four numbers, got {len(box)}")
    x1, y1, x2, y2 = (float(v) for v in box)
    if not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
        raise LabelingError(
            f"{where}: box must be normalised image coordinates with x1<x2, y1<y2: {box}")
    return (x1, y1, x2, y2)


def iou(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """두 상자의 겹침. 사람이 얼마나 고쳤는지를 재는 값이다."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    overlap = (ix2 - ix1) * (iy2 - iy1)
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - overlap
    return overlap / union if union > 0 else 0.0


def centre_shift(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """중심이 얼마나 옮겨졌는가(정규화 단위). 작게 흔든 것과 다른 것을 가리킨 것을
    구분하려면 겹침만으로는 부족하다 — 작은 상자는 조금 옮겨도 IoU 가 크게 떨어진다.
    """
    acx, acy = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
    bcx, bcy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return ((acx - bcx) ** 2 + (acy - bcy) ** 2) ** 0.5


@dataclass(frozen=True)
class PredictedBox:
    """모델이 낸 상자 하나. **지우지 않는다** — 틀린 정도가 학습 가치다."""

    box_id: str
    box: tuple[float, float, float, float]
    semantic_class: str | None = None
    confidence: float | None = None
    range_m: float | None = None
    provider_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "box", _check_box(self.box, f"predicted:{self.box_id}"))

    def as_dict(self) -> dict:
        body: dict[str, Any] = {"box_id": self.box_id, "box": list(self.box),
                                "provider_id": self.provider_id}
        for name in ("semantic_class", "confidence", "range_m"):
            value = getattr(self, name)
            if value is not None:
                body[name] = value
        return body


@dataclass(frozen=True)
class LabeledBox:
    """한 상자에 대한 사람의 판정. 모델이 낸 것과 사람이 고친 것을 나란히 둔다."""

    box_id: str
    verdict: BoxVerdict
    predicted: PredictedBox | None = None
    corrected_box: tuple[float, float, float, float] | None = None
    corrected_class: str | None = None
    corrected_range_m: float | None = None
    note: str = ""
    labeled_by: str = ""
    labeled_at: float | None = None

    def __post_init__(self) -> None:
        if self.corrected_box is not None:
            object.__setattr__(self, "corrected_box",
                               _check_box(self.corrected_box, f"corrected:{self.box_id}"))
        if self.verdict is BoxVerdict.ADDED and self.corrected_box is None:
            raise LabelingError(f"{self.box_id}: an added box needs its own coordinates")
        if self.verdict in GROUND_TRUTH_VERDICTS and not self.labeled_by:
            # 작성자 없는 정답은 되짚을 수 없다(AI-L-03).
            raise LabelingError(f"{self.box_id}: ground truth needs an author")

    @property
    def is_ground_truth(self) -> bool:
        return self.verdict in GROUND_TRUTH_VERDICTS

    @property
    def final_box(self) -> tuple[float, ...] | None:
        """정답으로 쓸 상자. 거짓 양성은 상자가 없다 — 없음이 곧 정답이다."""
        if self.verdict is BoxVerdict.REJECTED:
            return None
        if self.corrected_box is not None:
            return self.corrected_box
        return self.predicted.box if self.predicted else None

    @property
    def final_class(self) -> str | None:
        if self.verdict is BoxVerdict.REJECTED:
            return None
        if self.corrected_class is not None:
            return self.corrected_class
        return self.predicted.semantic_class if self.predicted else None

    def disagreement(self) -> dict:
        """모델과 사람이 얼마나 달랐는가. 이 값이 학습 후보의 가치를 말한다."""
        if self.predicted is None:
            return {"kind": "model_missed_it"}
        if self.verdict is BoxVerdict.REJECTED:
            return {"kind": "model_saw_nothing_there"}
        corrected = self.final_box
        if corrected is None:
            return {"kind": "no_final_box"}
        body = {
            "kind": "compared",
            "iou": round(iou(self.predicted.box, corrected), 4),
            "centre_shift": round(centre_shift(self.predicted.box, corrected), 4),
            "class_changed": self.final_class != self.predicted.semantic_class,
        }
        if self.corrected_range_m is not None and self.predicted.range_m is not None:
            body["range_error_m"] = round(
                self.corrected_range_m - self.predicted.range_m, 3)
        return body

    def as_dict(self) -> dict:
        body: dict[str, Any] = {
            "box_id": self.box_id, "verdict": self.verdict.value,
            "is_ground_truth": self.is_ground_truth,
            "labeled_by": self.labeled_by,
            "disagreement": self.disagreement(),
        }
        if self.predicted is not None:
            body["predicted"] = self.predicted.as_dict()
        if self.final_box is not None:
            body["final_box"] = list(self.final_box)
        for name in ("final_class",):
            value = getattr(self, name)
            if value is not None:
                body[name] = value
        for name in ("corrected_range_m", "labeled_at"):
            value = getattr(self, name)
            if value is not None:
                body[name] = value
        if self.note:
            body["note"] = self.note
        return body


@dataclass(frozen=True)
class LabelTask:
    """한 프레임에 대한 라벨 작업. 프레임은 참조이고 픽셀이 아니다(AI-C-08)."""

    task_id: str
    frame_ref: str
    #: 이 정답이 **누구의** 후보가 되는가. 기기이거나 `dataset:<id>` 다.
    device_id: str
    #: 어느 출처 묶음에서 왔는가. 되짚기의 입구다.
    source_id: str = ""
    source_kind: str = ""
    #: 미디어 경로에서 이 프레임을 받는 방법. 뷰어가 경로를 추측하지 않게 한다.
    media: Mapping[str, Any] = field(default_factory=dict)
    predicted: tuple[PredictedBox, ...] = ()
    model_version: str = ""
    zone_id: str | None = None
    created_at: float | None = None

    def as_dict(self) -> dict:
        return {
            "task_id": self.task_id, "frame_ref": self.frame_ref,
            "device_id": self.device_id, "zone_id": self.zone_id,
            "source_id": self.source_id, "source_kind": self.source_kind,
            "model_version": self.model_version,
            "media": dict(self.media),
            "predicted": [b.as_dict() for b in self.predicted],
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class GroundTruthRecord:
    """제출된 정답 한 벌. 학습 후보의 재료다."""

    task_id: str
    frame_ref: str
    device_id: str
    boxes: tuple[LabeledBox, ...]
    submitted_by: str
    submitted_at: float
    model_version: str = ""
    zone_id: str | None = None
    #: 왜 이 정답을 만들었는지. 계보가 요구하는 값이고, 다시 열었을 때 전에
    #: 무엇을 고치려 했는지 보이게 한다.
    reason: str = ""

    @property
    def reviewed(self) -> tuple[LabeledBox, ...]:
        return tuple(b for b in self.boxes if b.is_ground_truth)

    @property
    def corrections(self) -> tuple[LabeledBox, ...]:
        """모델과 다른 답을 담은 것들. 학습에서 실제로 값을 하는 부분이다."""
        return tuple(b for b in self.boxes if b.verdict in CORRECTING_VERDICTS)

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for box in self.boxes:
            counts[box.verdict.value] = counts.get(box.verdict.value, 0) + 1
        return {
            "task_id": self.task_id, "frame_ref": self.frame_ref,
            "device_id": self.device_id, "zone_id": self.zone_id,
            "model_version": self.model_version,
            "submitted_by": self.submitted_by, "submitted_at": self.submitted_at,
            "reason": self.reason,
            "box_count": len(self.boxes),
            "reviewed_count": len(self.reviewed),
            "correction_count": len(self.corrections),
            "by_verdict": counts,
            # 검수하지 않은 상자는 정답이 아니다. 그 수를 숨기지 않는다 — 숨기면
            # 절반만 검수한 프레임이 완성된 정답처럼 보인다.
            "unreviewed_count": counts.get(BoxVerdict.UNREVIEWED.value, 0),
        }

    def as_dict(self) -> dict:
        return {**self.summary(), "boxes": [b.as_dict() for b in self.boxes]}


def labeled_box_from_dict(raw: Mapping[str, Any], *,
                          predicted: Mapping[str, PredictedBox],
                          author: str, clock=time.time) -> LabeledBox:
    """웹에서 올라온 상자 하나를 판정으로 바꾼다.

    판정을 **클라이언트가 정하게 하지 않는다** — 좌표와 class 를 보고 서버가 정한다.
    클라이언트가 "confirmed" 라고 적어 보내면서 좌표를 바꿔 놓으면, 고친 사실이
    기록에서 사라진다.
    """
    box_id = str(raw.get("box_id") or "")
    if not box_id:
        raise LabelingError("box_id is required")
    source = predicted.get(box_id)

    if raw.get("rejected"):
        if source is None:
            raise LabelingError(f"{box_id}: nothing to reject")
        return LabeledBox(box_id=box_id, verdict=BoxVerdict.REJECTED, predicted=source,
                          note=str(raw.get("note") or ""), labeled_by=author,
                          labeled_at=float(clock()))

    corrected_box = raw.get("box")
    corrected_class = raw.get("semantic_class")
    corrected_range = raw.get("range_m")
    box_tuple = (tuple(float(v) for v in corrected_box)
                 if corrected_box is not None else None)

    if source is None:
        # 모델이 놓친 것을 사람이 그렸다.
        return LabeledBox(box_id=box_id, verdict=BoxVerdict.ADDED,
                          corrected_box=box_tuple, corrected_class=corrected_class,
                          corrected_range_m=(float(corrected_range)
                                             if corrected_range is not None else None),
                          note=str(raw.get("note") or ""), labeled_by=author,
                          labeled_at=float(clock()))

    moved = box_tuple is not None and _check_box(box_tuple, box_id) != source.box
    relabeled = corrected_class is not None and corrected_class != source.semantic_class
    # 거리만 고친 것도 고친 것이다. 이것을 `CONFIRMED` 로 적으면 판정이
    # `CORRECTING_VERDICTS` 에 들지 않아 **사람이 고친 거리가 학습 후보에서 조용히
    # 사라진다** — 거리는 기하이므로 자리 수정과 같은 칸에 넣는다.
    reranged = (corrected_range is not None
                and (source.range_m is None
                     or abs(float(corrected_range) - source.range_m) > RANGE_EPSILON_M))
    # 둘 다 바뀌면 class 변경으로 적는다 — 학습에서 더 무거운 쪽이 그것이다.
    verdict = (BoxVerdict.RELABELED if relabeled
               else BoxVerdict.ADJUSTED if moved or reranged
               else BoxVerdict.CONFIRMED)
    return LabeledBox(
        box_id=box_id, verdict=verdict, predicted=source,
        corrected_box=box_tuple if moved else None,
        corrected_class=corrected_class if relabeled else None,
        corrected_range_m=(float(corrected_range) if corrected_range is not None else None),
        note=str(raw.get("note") or ""), labeled_by=author, labeled_at=float(clock()))


# ---------------------------------------------------------------------------
# 작업 만들기 — 실제 프레임에 실제 추론을 돌린다
# ---------------------------------------------------------------------------

#: 라벨 작업이 쓰는 어휘. **데이터다** — 현장이 보는 것이 달라지면 이 목록이 바뀐다.
#: 열린 어휘 모델이라 여기 적은 이름이 그대로 질의가 된다.
DEFAULT_LABEL_VOCABULARY: tuple[str, ...] = (
    "person", "door", "box", "chair", "trash bag", "plastic bottle", "robot",
)

#: 추론 provider 가 없을 때의 사유. 장애가 아니라 "사람이 처음부터 그린다" 는 정상 경로다.
NO_DETECTOR = "no_detector_available"


#: 출처의 종류. 새 종류는 이 집합에 더하는 데이터이고 분기문이 아니다.
SOURCE_DEVICE_CAPTURE = "device_capture"
SOURCE_MISSION_CAPTURE = "mission_capture"
SOURCE_EXTERNAL_DATASET = "external_dataset"
SOURCE_KINDS: frozenset[str] = frozenset({
    SOURCE_DEVICE_CAPTURE, SOURCE_MISSION_CAPTURE, SOURCE_EXTERNAL_DATASET})

#: 기기에서 오지 않은 데이터의 주체 접두. 기기 id 자리에 이것이 들어가면 그 후보는
#: 어느 기기의 묶음에도 섞이지 않는다.
DATASET_SUBJECT_PREFIX = "dataset:"

#: 읽을 수 있는 이미지 확장자.
IMAGE_SUFFIXES: tuple[str, ...] = (".jpg", ".jpeg", ".png")

#: 한 출처에서 목록에 올리는 최대 프레임 수. 3,000 장짜리 공개 데이터셋을 한 번에
#: 내려보내면 화면이 그것을 그리다 멈춘다. 자르는 것이지 **없는 척하는 것이 아니라서**
#: 응답에 전체 수를 함께 적는다.
MAX_LISTED_FRAMES = 300


def resolve_frame(root, frame_name: str):
    """출처 뿌리 아래의 프레임 하나를 **뿌리 밖으로 못 나가게** 연다.

    하위 디렉터리를 허용하는 순간 `../` 한 번이면 자산 뿌리 밖의 아무 파일이나
    읽힌다. 이름 규약을 좁히는 것만으로는 부족해서, 푼 경로가 실제로 뿌리 아래인지
    확인한다 — 심볼릭 링크로 밖을 가리키는 경우까지 그 확인이 잡는다.
    """
    from pathlib import Path as _Path

    name = str(frame_name or "").replace("\\", "/")
    if not name or name.startswith("/") or any(
            part in ("", ".", "..") for part in name.split("/")):
        raise LabelingError(f"bad frame name: {frame_name!r}")
    root = _Path(root).resolve()
    candidate = (root / name).resolve()
    if root != candidate and root not in candidate.parents:
        raise LabelingError(f"frame outside its source: {frame_name!r}")
    return candidate


@dataclass(frozen=True)
class LabelSource:
    """라벨할 데이터 한 묶음이 **어디서 왔는가**.

    `device_id` 가 없는 것이 정상인 종류가 있다(공개 데이터셋). 없는 것을 기본값으로
    메우면 그 데이터가 우리 기기에서 온 것처럼 보이고, 그 거짓이 학습 후보의 조건에
    그대로 실린다(AI-L-09 는 기기별 구분을 요구한다).
    """

    source_id: str
    kind: str
    #: 자산 뿌리 기준 상대 경로.
    path: str
    device_id: str | None = None
    label: Mapping[str, str] = field(default_factory=dict)
    #: 하위 디렉터리까지 뒤지는가. 임무 기록처럼 폴더 안에 폴더가 있는 출처용이다.
    recursive: bool = False
    captured_at: str | None = None
    origin: str = ""
    license: str = ""
    #: 재배포해도 되는가. **모르면 None** 이고 그것은 "된다" 가 아니다.
    redistributable: bool | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if not self.source_id or not self.path:
            raise LabelingError("a label source needs a source_id and a path")
        if self.kind not in SOURCE_KINDS:
            raise LabelingError(f"unknown label source kind: {self.kind!r}")
        if self.kind == SOURCE_EXTERNAL_DATASET and self.device_id:
            # 공개 데이터셋에 기기를 달면 그 데이터가 우리 기기에서 온 것이 된다.
            raise LabelingError(
                f"{self.source_id}: an external dataset must not claim a device_id")
        if self.kind != SOURCE_EXTERNAL_DATASET and not self.device_id:
            raise LabelingError(f"{self.source_id}: {self.kind} needs a device_id")

    @property
    def subject_id(self) -> str:
        """이 출처의 정답이 누구의 후보가 되는가. 기기가 없으면 데이터셋 자신이다."""
        return self.device_id or f"{DATASET_SUBJECT_PREFIX}{self.source_id}"

    @property
    def from_our_device(self) -> bool:
        return self.device_id is not None

    def as_dict(self) -> dict:
        return {
            "source_id": self.source_id, "kind": self.kind, "path": self.path,
            "device_id": self.device_id, "subject_id": self.subject_id,
            "label": dict(self.label), "captured_at": self.captured_at,
            "origin": self.origin, "license": self.license,
            "redistributable": self.redistributable, "note": self.note,
        }


def label_sources_from_dict(raw: Mapping[str, Any]) -> tuple[LabelSource, ...]:
    """선언 파일을 출처 계약으로. 모르는 칸은 무시하고 적힌 것만 읽는다."""
    sources: list[LabelSource] = []
    seen: set[str] = set()
    for entry in raw.get("sources", ()):
        source = LabelSource(
            source_id=str(entry.get("source_id") or ""),
            kind=str(entry.get("kind") or ""),
            path=str(entry.get("path") or ""),
            device_id=entry.get("device_id") or None,
            label=dict(entry.get("label") or {}),
            recursive=bool(entry.get("recursive", False)),
            captured_at=entry.get("captured_at") or None,
            origin=str(entry.get("origin") or ""),
            license=str(entry.get("license") or ""),
            redistributable=entry.get("redistributable"),
            note=str(entry.get("note") or ""),
        )
        if source.source_id in seen:
            raise LabelingError(f"duplicate label source id: {source.source_id}")
        seen.add(source.source_id)
        sources.append(source)
    return tuple(sources)


@dataclass
class FrameLabelSource:
    """저장된 프레임을 라벨 작업으로 바꾼다.

    예측은 **실제 모델**이 낸다. 지어낸 상자로 라벨 화면을 채우면 그 화면이 증명하는
    것이 아무것도 없다. 모델이 없는 노드에서는 예측이 비고 사람이 처음부터 그리며,
    그것도 정상적인 라벨 작업이다(AI-C-05).

    프레임 바이트는 이 객체가 내보내지 않는다 — 미디어 경로가 낸다(AI-C-08). 여기서
    만드는 것은 참조와 좌표뿐이다.
    """

    frame_root: Any
    #: 이 묶음이 어디서 왔는가. 없으면 옛 호출 경로(단일 디렉터리)이고, 그때는
    #: `device_id` 가 주체다.
    source: LabelSource | None = None
    device_id: str = "pi4"
    zone_id: str | None = None
    vocabulary: tuple[str, ...] = DEFAULT_LABEL_VOCABULARY
    #: 프레임 하나에서 상자를 내는 것. `detect(frame_bgr) -> [PerceptionResult]`.
    detector_factory: Any | None = None
    _detector: Any | None = field(default=None, init=False)
    _unavailable_reason: str | None = field(default=None, init=False)
    _listed: tuple[tuple[str, ...], int] | None = field(default=None, init=False)

    @property
    def subject_id(self) -> str:
        """정답이 누구의 후보가 되는가. 출처가 있으면 출처가 정한다."""
        return self.source.subject_id if self.source is not None else self.device_id

    @property
    def source_id(self) -> str:
        return self.source.source_id if self.source is not None else self.device_id

    def frames(self) -> tuple[str, ...]:
        """라벨할 수 있는 프레임 이름들. 없으면 빈 묶음이고 오류가 아니다.

        하위 디렉터리가 있는 출처(임무 기록)에서는 뿌리 기준 **상대 경로**를 낸다 —
        파일 이름만 내면 서로 다른 임무의 같은 이름이 한 칸에 겹친다.
        """
        return self._listing()[0]

    def frame_count(self) -> int:
        """실제로 있는 프레임 수. 목록은 잘릴 수 있고 이 수는 잘리지 않는다."""
        return self._listing()[1]

    def _listing(self) -> tuple[tuple[str, ...], int]:
        if self._listed is not None:
            return self._listed
        root = self._root()
        if root is None or not root.is_dir():
            self._listed = ((), 0)
            return self._listed
        recursive = self.source is not None and self.source.recursive
        walk = root.rglob("*") if recursive else root.iterdir()
        names = sorted(
            str(path.relative_to(root)).replace("\\", "/")
            for path in walk
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)
        # 자른다는 사실을 숨기지 않는다 — 전체 수를 함께 들고 다닌다.
        self._listed = (tuple(names[:MAX_LISTED_FRAMES]), len(names))
        return self._listed

    def detector(self):
        """추론기를 한 번만 세운다. 없으면 사유를 남기고 None 을 돌려준다."""
        if self._detector is None and self._unavailable_reason is None:
            if self.detector_factory is None:
                self._unavailable_reason = NO_DETECTOR
            else:
                try:
                    candidate = self.detector_factory(list(self.vocabulary))
                except Exception as error:  # noqa: BLE001 - 선택 경로다
                    self._unavailable_reason = f"{NO_DETECTOR}:{type(error).__name__}"
                    candidate = None
                if candidate is None or not getattr(candidate, "is_available", lambda: True)():
                    self._unavailable_reason = NO_DETECTOR
                else:
                    self._detector = candidate
        return self._detector

    @property
    def detector_reason(self) -> str | None:
        self.detector()
        return self._unavailable_reason

    def _root(self):
        """프레임이 놓인 자리. **없을 수 있다** — 자산 없이 설치한 배치가 그렇다.

        그때 라벨 기능만 비고 콘솔은 그대로 돈다(AI-C-05). `Path(None)` 으로
        터지게 두면 선택 기능 결손이 화면 전체의 장애가 된다.
        """
        from pathlib import Path

        return None if self.frame_root is None else Path(self.frame_root)

    def task(self, frame_name: str, *, media_ref: Mapping[str, Any],
             clock=time.time) -> LabelTask:
        """프레임 하나에 대한 작업. 예측은 지금 실제로 돌려서 얻는다."""
        root = self._root()
        path = None if root is None else resolve_frame(root, frame_name)
        if path is None or not path.is_file():
            raise LabelingError(f"no such frame: {frame_name}")
        predicted: list[PredictedBox] = []
        model_version = ""
        detector = self.detector()
        if detector is not None:
            import cv2  # noqa: PLC0415 - 선택 경로다

            frame = cv2.imread(str(path))
            if frame is None:
                raise LabelingError(f"frame is not readable: {frame_name}")
            height, width = frame.shape[:2]
            model_version = getattr(detector, "model_version", None) or type(detector).__name__
            for index, result in enumerate(detector.detect(frame)):
                x1, y1, x2, y2 = result.box
                # 모델은 픽셀로 낸다. 저장은 정규화로 한다 — 해상도가 다른 기기에서
                # 같은 라벨을 쓸 수 있어야 하고, 픽셀로 두면 crop 이 바뀔 때 전부 틀린다.
                box = (max(0.0, x1 / width), max(0.0, y1 / height),
                       min(1.0, x2 / width), min(1.0, y2 / height))
                if not (box[0] < box[2] and box[1] < box[3]):
                    continue  # 폭·높이가 0 인 상자는 라벨할 대상이 아니다
                predicted.append(PredictedBox(
                    box_id=f"p{index}", box=box,
                    # `PerceptionResult.label` 이 정본이다. 열린 어휘 provider 는
                    # `matched_vocab` 으로도 같은 것을 내므로 둘 다 본다 — 한쪽만
                    # 보면 provider 를 바꿀 때 class 가 조용히 비어 버린다.
                    semantic_class=getattr(result, "label", None)
                    or getattr(result, "matched_vocab", None),
                    confidence=getattr(result, "confidence", None),
                    provider_id=model_version))
        return LabelTask(
            # 작업 id 와 프레임 참조는 **출처**로 가른다. 기기로 가르면 같은 기기의
            # 서로 다른 촬영이 한 칸에 겹치고, 데이터셋은 기기가 없어 겹칠 칸조차 없다.
            task_id=f"{self.source_id}:{frame_name}",
            frame_ref=f"{self.source_id}/{frame_name}",
            device_id=self.subject_id, zone_id=self.zone_id,
            source_id=self.source_id,
            source_kind=(self.source.kind if self.source is not None
                         else SOURCE_DEVICE_CAPTURE),
            media=dict(media_ref), predicted=tuple(predicted),
            model_version=model_version, created_at=float(clock()))
