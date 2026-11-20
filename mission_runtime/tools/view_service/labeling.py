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


# ---------------------------------------------------------------------------
# 동일성 — **어느 개체인가**. class 와 다른 축이다
# ---------------------------------------------------------------------------
#
# class 는 **종류**를 말하고 동일성은 **개체**를 가린다. 둘을 한 칸에 담으면
# "스티로폼 상자" 가 한 개를 가리키는지 여러 개 중 하나를 가리키는지 알 수 없고,
# 서로 다른 카메라가 같은 물체를 봤는지 묻는 일(AI-S-02) 자체가 성립하지 않는다.
#
# ## 런타임이 묶은 번호와 사람이 확정한 동일성은 다른 것이다
#
# `perception/object_record.ObjectRecord.object_id` 는 AI 가 근거를 묶어 **판정한**
# 식별자이고, 여기 적히는 것은 사람이 **확인한** 동일성이다. 이름이 같은 축인 것은
# 공통 데이터 사전(AI-C-01)의 같은 의미 단위이기 때문이지만, 추적기가 낸 번호를 그대로
# 이 칸에 옮기면 **평가가 순환한다** — 방법이 낸 답이 그 방법을 채점할 정답이 된다.
# 그래서 이 칸은 GT 판정에만 붙고(`UNREVIEWED` 에는 붙지 않는다) 작성자를 요구한다.
#
# ## 갈리지 않은 것을 고르게 하지 않는다
#
# 눈으로 구별되지 않는 쌍둥이 물체(같은 모델 물통 둘)에서 한쪽을 찍으라고 하면 사람은
# 찍는다. 그렇게 만든 정답은 틀린 정답이고, 틀린 정답은 없는 정답보다 나쁘다. 그래서
# 세 상태를 둔다 — 확정(`object_id` 하나) · 후보 묶음(`object_id_candidates` 둘 이상)
# · 말하지 않음(둘 다 빈 값). 후보 묶음은 "이 둘 중 하나인데 어느 쪽인지 모른다" 는
# **정보가 있는 정답**이고, 1 위를 고르지 않는다는 AI-S-04·AI-S-03 의 그 자리다.
#
# ## 이름 공간이 **출처 밖에** 있어야 한다
#
# 판정 장부는 출처마다 갈려 있다(`<source_id>.jsonl`). 그 안에서만 뜻이 있는 번호를
# 적으면 카메라를 넘는 동일성을 적을 자리가 없다. `identity_scope` 가 출처 여럿을
# 묶는 이름 공간이고, 그 선언이 **어느 출처들이 같은 번호 체계를 쓰는지**를 정한다.

#: 동일성이 어떤 상태인가. 세 값이고 접지 않는다 — "모른다" 와 "둘 중 하나" 는
#: 다른 사실이다. 접으면 쌍둥이의 정답이 미검수와 같아 보인다.
IDENTITY_UNASSERTED = "unasserted"
IDENTITY_RESOLVED = "resolved"
IDENTITY_AMBIGUOUS = "ambiguous"
IDENTITY_STATES: tuple[str, ...] = (
    IDENTITY_UNASSERTED, IDENTITY_RESOLVED, IDENTITY_AMBIGUOUS)


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
class IdentityScope:
    """동일성 번호가 뜻을 갖는 **이름 공간** 하나.

    왜 선언이 필요한가: 번호를 자유 문자열로 두면 `river3-001` 과 `river3-01` 이
    서로 다른 두 개체가 된다. 오타가 조용히 새 개체를 만들고, 그 개체는 어느
    카메라에서도 한 번만 보이므로 **교차 카메라 정답에서 그냥 빠진다** — 빠진 것은
    0 점으로 세어지지 않고 아예 세어지지 않아서 눈에 띄지 않는다. 그래서 명부를
    선언하고 명부 밖 번호를 거절한다.

    `open=True` 는 명부를 미리 적을 수 없는 운영 데이터용이다. 그때도 번호는
    기록되지만 오타를 잡아 주지 못한다는 뜻이고, 통제 실험에서는 닫아 둔다.
    """

    scope_id: str
    #: 이 번호 체계를 **같이 쓰는 출처들**. 비어 있으면 아직 묶지 않은 것이고,
    #: 그 상태에서는 교차 출처 동일성을 주장할 근거가 없다.
    sources: tuple[str, ...] = ()
    #: 선언된 개체 명부. 닫힌 이름 공간에서는 이 목록이 허용되는 번호 전부다.
    members: tuple[str, ...] = ()
    #: 명부 밖 번호를 받는가. 통제 실험은 닫고 운영 수집은 연다.
    open: bool = False
    #: 개체마다 **선언된** 곁정보(종류·쌍둥이 상대 등). 관측이 아니라 사전정보다
    #: (AI-S-08) — 명부가 그렇게 적혀 있다는 사실이고 측정이 아니다. 계약은 내용을
    #: 해석하지 않고 그대로 들고 다닌다. 화면이 쌍둥이 묶음을 짓는 데 쓴다.
    roster: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    #: 통제 투하라면 **흘려보낸 순서**. 선언이고 도착 순서가 아니다.
    release_order: tuple[str, ...] = ()
    label: Mapping[str, str] = field(default_factory=dict)
    note: str = ""

    def __post_init__(self) -> None:
        if not self.scope_id:
            raise LabelingError("an identity scope needs a scope_id")
        object.__setattr__(self, "sources", tuple(self.sources))
        object.__setattr__(self, "members", tuple(self.members))
        if len(set(self.members)) != len(self.members):
            raise LabelingError(f"{self.scope_id}: duplicate member in the roster")
        object.__setattr__(self, "release_order", tuple(self.release_order))
        stray = [m for m in self.release_order if m not in self.members]
        if stray:
            raise LabelingError(
                f"{self.scope_id}: release order names non-members: {', '.join(stray)}")
        unknown = [k for k in self.roster if k not in self.members]
        if unknown:
            # 명부에 없는 개체의 곁정보는 **누구의 것도 아니다.** 오타가 거기 숨으면
            # 화면이 그 번호로 묶음을 짓고, 그 번호는 판정에서 거절된다.
            raise LabelingError(
                f"{self.scope_id}: roster has entries outside the member list: "
                f"{', '.join(sorted(unknown))}")
        if not self.open and not self.members:
            # 닫혀 있으면서 명부가 없으면 **아무 번호도 통과하지 못한다.** 그 상태를
            # 조용히 두면 라벨이 전부 거절되는 이유가 설정에 있다는 것을 모른다.
            raise LabelingError(
                f"{self.scope_id}: a closed identity scope needs a roster "
                "(declare members, or set open=true)")

    def release_order_members(self) -> tuple[str, ...]:
        """선언된 투하 순서. 적혀 있지 않으면 빈 묶음이고 그것도 정상이다 —
        통제 투하가 아닌 수집에는 순서가 없다.

        왜 칸을 따로 두는가: 이 순서는 **관측이 아니라 선언**이다(AI-S-08).
        도착 순서는 자료가 말하고 둘은 다를 수 있다 — 실제로 2026-11-16 자료에서
        나중에 던진 원통이 먼저 던진 나무상자를 앞질렀다. 두 축을 한 칸에 담으면
        그 추월이 보이지 않는다.
        """
        return tuple(self.release_order)

    def covers(self, source_id: str) -> bool:
        """그 출처가 이 번호 체계에 들어 있는가."""
        return source_id in self.sources

    def check(self, object_id: str) -> None:
        """명부에 있는 번호인가. 없으면 **거절한다** — 오타가 새 개체가 되지 않게."""
        if not object_id:
            raise LabelingError(f"{self.scope_id}: an empty object_id is not an identity")
        if self.open or object_id in self.members:
            return
        raise LabelingError(
            f"{self.scope_id}: {object_id!r} is not in the declared roster "
            f"({len(self.members)} members)")

    def as_dict(self) -> dict:
        return {"scope_id": self.scope_id, "sources": list(self.sources),
                "members": list(self.members), "open": self.open,
                "roster": {k: dict(v) for k, v in self.roster.items()},
                "release_order": list(self.release_order),
                "label": dict(self.label), "note": self.note}


def identity_scopes_from_dict(raw: Mapping[str, Any]) -> tuple[IdentityScope, ...]:
    """선언 파일을 이름 공간 계약으로. 새 실험은 이 파일 한 묶음이고 코드가 아니다."""
    scopes: list[IdentityScope] = []
    seen: set[str] = set()
    for entry in raw.get("scopes", ()):
        scope = IdentityScope(
            scope_id=str(entry.get("scope_id") or ""),
            sources=tuple(str(v) for v in (entry.get("sources") or ())),
            members=tuple(str(v) for v in (entry.get("members") or ())),
            open=bool(entry.get("open", False)),
            roster={str(k): dict(v or {})
                    for k, v in (entry.get("roster") or {}).items()},
            release_order=tuple(str(v) for v in (entry.get("release_order") or ())),
            label=dict(entry.get("label") or {}),
            note=str(entry.get("note") or ""),
        )
        if scope.scope_id in seen:
            raise LabelingError(f"duplicate identity scope id: {scope.scope_id}")
        seen.add(scope.scope_id)
        scopes.append(scope)
    return tuple(scopes)


def scope_for_source(scopes: Iterable[IdentityScope],
                     source_id: str) -> IdentityScope | None:
    """그 출처가 속한 이름 공간. 둘에 속하면 거절한다 — 같은 번호가 두 뜻을 갖는다."""
    found = [scope for scope in scopes if scope.covers(source_id)]
    if len(found) > 1:
        raise LabelingError(
            f"{source_id}: belongs to {len(found)} identity scopes "
            f"({', '.join(s.scope_id for s in found)}); one source, one numbering")
    return found[0] if found else None


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
    #: **어느 개체인가**(class 가 아니다). 이름 공간은 `identity_scope` 가 정한다.
    object_id: str = ""
    #: 갈리지 않을 때의 후보 묶음. 둘 이상이어야 하고 `object_id` 와 함께 쓰지 않는다.
    object_id_candidates: tuple[str, ...] = ()
    #: 그 번호가 어느 이름 공간의 번호인가. 출처 밖에서 뜻을 가지려면 필요하다.
    identity_scope: str = ""
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
        object.__setattr__(self, "object_id_candidates",
                           tuple(self.object_id_candidates))
        self._check_identity()

    def _check_identity(self) -> None:
        """동일성 선언이 구조적으로 성립하는가. 명부 대조는 `IdentityScope` 가 한다."""
        where = f"{self.box_id}"
        if self.object_id and self.object_id_candidates:
            # 확정과 후보가 함께 있으면 어느 쪽이 정답인지 읽는 쪽이 고르게 된다.
            raise LabelingError(
                f"{where}: an identity is either resolved or ambiguous, not both")
        if len(self.object_id_candidates) == 1:
            # 후보가 하나면 그것은 확정이다. 후보 칸에 두면 확정된 동일성이
            # "갈리지 않음" 으로 세어져 재현율이 거짓으로 낮아진다.
            raise LabelingError(
                f"{where}: one candidate is a resolved identity — put it in object_id")
        if len(set(self.object_id_candidates)) != len(self.object_id_candidates):
            raise LabelingError(f"{where}: duplicate identity candidate")
        if any(not c for c in self.object_id_candidates):
            raise LabelingError(f"{where}: an empty identity candidate")
        if self.identity_state == IDENTITY_UNASSERTED:
            return
        if not self.is_ground_truth:
            # 검수하지 않은 상자에 개체를 달면 추적기가 낸 번호가 정답으로 승격된다 —
            # 그러면 그 번호를 쓰는 방법을 그 번호로 채점한다(AI-L-02).
            raise LabelingError(
                f"{where}: identity belongs to reviewed ground truth, not {self.verdict.value}")
        if self.verdict is BoxVerdict.REJECTED:
            # 없는 것을 봤다는 정답에는 가리킬 개체가 없다.
            raise LabelingError(f"{where}: a rejected box has no individual to identify")
        if not self.identity_scope:
            raise LabelingError(
                f"{where}: an identity needs its identity_scope — a bare number means "
                "nothing outside one source")

    @property
    def identity_state(self) -> str:
        """확정 · 후보 묶음 · 말하지 않음. 뒤 둘을 접지 않는다."""
        if self.object_id:
            return IDENTITY_RESOLVED
        if self.object_id_candidates:
            return IDENTITY_AMBIGUOUS
        return IDENTITY_UNASSERTED

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
        # 동일성은 **늘 적는다** — 말하지 않았다는 사실도 읽는 쪽이 알아야 한다.
        # 칸을 비워 내보내면 "안 달았다" 와 "이 판에는 그 축이 없다" 가 같아 보인다.
        body["identity_state"] = self.identity_state
        if self.object_id:
            body["object_id"] = self.object_id
        if self.object_id_candidates:
            body["object_id_candidates"] = list(self.object_id_candidates)
        if self.identity_scope:
            body["identity_scope"] = self.identity_scope
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
        # 동일성 세 상태를 각각 센다. 확정과 "둘 중 하나" 를 한 수로 합치면 쌍둥이를
        # 가린 척하는 정답이 가린 정답처럼 보인다.
        identity = {state: 0 for state in IDENTITY_STATES}
        for box in self.boxes:
            identity[box.identity_state] += 1
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
            "by_identity_state": identity,
            # 검수하지 않은 상자는 정답이 아니다. 그 수를 숨기지 않는다 — 숨기면
            # 절반만 검수한 프레임이 완성된 정답처럼 보인다.
            "unreviewed_count": counts.get(BoxVerdict.UNREVIEWED.value, 0),
        }

    def as_dict(self) -> dict:
        return {**self.summary(), "boxes": [b.as_dict() for b in self.boxes]}


def identity_from_dict(raw: Mapping[str, Any]) -> dict:
    """올라온 몸체에서 동일성 칸만 뽑는다. 적지 않은 것은 빈 값이고 오류가 아니다 —
    class 라벨링만 하는 판에서는 이 축이 아예 없다."""
    candidates = raw.get("object_id_candidates") or ()
    if isinstance(candidates, str):
        # 쉼표로 적어 보내는 화면을 받는다. 공백만 있는 조각은 번호가 아니다.
        candidates = [part.strip() for part in candidates.split(",") if part.strip()]
    return {
        "object_id": str(raw.get("object_id") or "").strip(),
        "object_id_candidates": tuple(str(c).strip() for c in candidates),
        "identity_scope": str(raw.get("identity_scope") or "").strip(),
    }


def identity_index(entries: Iterable[Mapping[str, Any]]) -> dict:
    """장부 줄들을 **개체별로** 묶는다. 교차 카메라 정답이 실제로 생겼는지 보는 자리다.

    출처마다 장부가 갈려 있으므로 이 묶기는 여러 장부를 함께 읽어야 뜻이 있다.
    한 출처에서만 보이는 개체는 교차 카메라 쌍을 만들지 못하므로 `sources` 수를
    함께 낸다 — 그 수가 1 이면 그 개체는 교차 평가에 들어가지 않는다.
    """
    out: dict[tuple[str, str], dict] = {}
    for entry in entries:
        scope = str(entry.get("identity_scope") or "")
        ids = [str(entry["object_id"])] if entry.get("object_id") else []
        ids += [str(v) for v in (entry.get("object_id_candidates") or ())]
        resolved = bool(entry.get("object_id"))
        for object_id in ids:
            row = out.setdefault((scope, object_id), {
                "identity_scope": scope, "object_id": object_id,
                "resolved_count": 0, "ambiguous_count": 0,
                "sources": {}, "frames": []})
            row["resolved_count" if resolved else "ambiguous_count"] += 1
            source_id = str(entry.get("source_id") or "")
            row["sources"][source_id] = row["sources"].get(source_id, 0) + 1
            row["frames"].append({"source_id": source_id,
                                  "frame": str(entry.get("frame") or ""),
                                  "box_id": str(entry.get("box_id") or ""),
                                  "resolved": resolved})
    for row in out.values():
        row["source_count"] = len(row["sources"])
        # 한 출처에서만 보인 개체는 교차 카메라 쌍이 없다. 이것을 숨기면 정답이
        # 실제보다 많아 보인다.
        row["cross_source"] = row["source_count"] > 1
    return out


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
    identity = identity_from_dict(raw)

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
                          labeled_at=float(clock()), **identity)

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
        note=str(raw.get("note") or ""), labeled_by=author, labeled_at=float(clock()),
        **identity)


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

#: 목록이 상한을 넘을 때 **앞에서 자르지 않고 고르게 띄워** 고른다.
#:
#: 왜 바꿨는가: 프레임 이름이 시각 기반이라 정렬 = 시간순이고, 앞 300 개를 자르면
#: **가장 이른 300 장**이 된다. 연속 프레임은 서로 거의 같으니 그것은 중복이 가장
#: 큰 묶음이고, 능동 학습 문헌이 기준선으로 쓰는 무작위보다도 나쁘다
#: (`docs/research/hitl-data-and-weight-management.md` §9.1).
#:
#: **이것은 획득 함수가 아니다.** 어느 프레임이 더 가치 있는지 말하지 않고, 다만
#: 기본 묶음이 기록의 앞머리에만 몰리지 않게 한다. 검출 밀도 같은 실제 순위는
#: 추론을 돌려야 하고 그것은 이 목록을 만드는 자리에서 할 일이 아니다.
LISTING_STRATEGY_STRIDE = "even_stride_over_whole_source"


def _strided(names: list[str], limit: int) -> tuple[str, ...]:
    """상한 안에서 **원본 전체에 걸쳐** 고르게 고른다. 시간순은 유지한다.

    끝 프레임을 반드시 포함시키는 이유: 스캔의 마지막 방향이나 임무의 끝이 늘
    빠지면 그 구간은 영원히 라벨되지 않는다.
    """
    if limit <= 0 or len(names) <= limit:
        return tuple(names)
    # 마지막 한 자리를 끝 프레임에 비워 둔다 — 상한은 상한이고, 끝을 더해 넘기면
    # 화면이 받는 수가 선언과 달라진다.
    head = max(1, limit - 1)
    step = len(names) / float(head)
    picked = {names[min(len(names) - 1, int(i * step))] for i in range(head)}
    picked.add(names[-1])
    # 집합을 거쳐 왔으므로 정렬로 시간순을 되돌린다. 같은 입력에 같은 목록이 나온다.
    return tuple(sorted(picked))[:limit]


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

    @property
    def listing_strategy(self) -> str:
        """목록을 어떻게 골랐는가. 화면이 운영자에게 적어 줄 수 있어야 한다 —
        "전부 중 300장" 과 "앞에서 300장" 은 다른 묶음이다."""
        return LISTING_STRATEGY_STRIDE

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
        self._listed = (_strided(names, MAX_LISTED_FRAMES), len(names))
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
