"""화면에 보이는 저것이 **어떤 기종**인가.

implements: AI-E-01, AI-S-04, AI-L-09
관련: AI-S-03 (근거 충분도), AI-C-05 (선택 기능 결손), AI-C-19 (판단 경계)
tests: tests/test_appearance_classifier.py

## 이 모듈이 내는 것과 내지 않는 것

외형은 **종류**까지만 말한다. 같은 기종이 두 대 있으면 이 분류기는 둘을 영원히
구분하지 못하고, 그것이 고장이 아니라 설계다 — 개체 결속은
`perception/device_identity.py` 가 식별력 있는 단서(운동 프로브·마커·무선)로
따로 푼다. 그래서 이 모듈의 출력에는 `device_id` 가 **없다**. 호출자는 판정된
class 를 `device_identity.appearance_cue(...)` 에 넘기고, 그 함수가 같은 class 의
모든 후보에게 같은 단서를 나눠 준다.

## 판정을 하나의 임계값으로 끝내지 않는 이유

실측(사전의 `_meta.self_check`, 42 회 leave-one-out): 같은 기종 판정의 최저 점수가
0.6236 인데 **다른** 기종에서 나온 점수가 0.8915 까지 올라간다. 절대점수 구간이
겹치므로 "0.8 이상이면 그 기종"이라는 규칙은 어떤 값을 잡아도 성립하지 않는다.
가르는 것은 1 위와 2 위의 **차이**다. 그 차이가 마진 이하면 고르지 않는다 —
모호는 답이 없는 상태가 아니라 "지금 가진 사진으로는 가릴 수 없다"는 답이고
(AI-S-04: 확정하기 어려운 것을 기존 클래스에 강제 매핑하지 않는다), 틀린 확답은
그대로 다음 판단의 전제가 되어 되돌릴 수 없다.

절대점수 하한(`similarity_floor`)은 기종을 가르는 값이 아니라 "어느 참조영상과도
닮지 않았다"만 거르는 값이다. 둘을 한 값으로 뭉치면 위의 겹침이 보이지 않게 된다.

## 참조영상은 늘어나고, 운영자는 틀린 것을 내릴 수 있다

처음에 가질 수 있는 사진은 제품 사진뿐이고, 같은 장비를 현장에서 찍은 사진이
나중에 들어온다. 그래서 참조영상은 한 장씩 **덧붙는** 자료다 — 사전을 처음부터
다시 만들어야만 보강할 수 있다면 보강은 실제로 일어나지 않는다. 각 참조영상은
자기 출처(`origin`: 제품 사진인가 현장 사진인가)와 운영자 가중치(`weight`)를
들고 다니고, 0 으로 내려진 사진은 점수에서 빠지되 설명에는 남는다. 조용히 지우면
"왜 저 사진이 더 이상 근거가 아닌가"를 화면에서 되짚을 수 없고, 같은 사진이 다음
수집에서 다시 들어온다(AI-L-03: 사람이 확인한 것은 보존한다).

## 사전도 모델도 없는 노드가 정상이다

참조영상이 없는 기종, 사전 파일이 없는 배치, CLIP 모델이 없는 말단은 모두 **정상
축소 상태**다(AI-C-05, 원칙 #3: 특정 모델이 없다고 시작을 막지 않는다). 그래서
없음은 예외가 아니라 `AppearanceVerdict` 의 한 상태로 돌아오고, 참조영상 0 장인
기종은 후보 목록에서 빠지되 `unfit_classes` 에 사유와 함께 남는다 — 목록에서
조용히 사라지면 "그 기종이 안 보인다"와 "그 기종을 볼 능력이 없다"가 같은 모양이
된다.

`onnxruntime`/`cv2`/`numpy` 는 모듈 최상단이 아니라 쓰는 자리에서 지연 import
한다. 모델이 없는 노드에서도 이 모듈은 import 되어야 한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from mission_runtime.contracts.data_dictionary import (
    WEIGHTED_REFERENCE_SIMILARITY,
    FEATURE_SIMILARITIES,
    MANDATORY_GATES,
    MODEL_VERSION,
    SEMANTIC_CLASS,
)

#: 사전이 값을 적어 두지 않았을 때 쓰는 기본값. 근거는 모듈 docstring 과
#: `tools/appearance/build_dictionary.py` 의 self-check 수치다.
DEFAULT_AMBIGUITY_MARGIN = 0.05
DEFAULT_SIMILARITY_FLOOR = 0.55
DEFAULT_TOP_K_REFERENCES = 3

#: 참조영상이 없어 분류 대상이 될 수 없는 기종의 사유 어휘.
UNFIT_NO_REFERENCE = "no_reference_image"
#: 참조영상은 있지만 운영자가 전부 0 으로 내려 점수에 들어갈 것이 없는 경우.
UNFIT_ALL_WEIGHTS_ZERO = "all_references_weighted_out"

#: 참조영상의 출처. 제품 사진으로 시작해 현장 사진으로 보강한다 — 둘을 구분해야
#: "아직 제품 사진뿐"인 기종과 "현장에서 확인된" 기종이 화면에서 달라 보인다.
ORIGIN_WEB = "web_reference"
ORIGIN_FIELD = "field_capture"

#: 사전·모델이 없을 때의 사유 어휘. 장애가 아니라 축소 상태다(AI-C-05).
REASON_NO_DICTIONARY = "no_dictionary_file"
REASON_NO_FIT_CLASS = "no_class_has_a_reference_image"
REASON_NO_ENGINE = "no_embedding_model_available"


class AppearanceState(str, Enum):
    """판정 상태. `CLASSIFIED` 만 기종을 말하고 나머지는 전부 말하지 않는다."""

    CLASSIFIED = "CLASSIFIED"
    #: 1·2 위 차이가 마진 이하 — 고르지 않는다. 틀린 확답보다 싸다.
    AMBIGUOUS = "AMBIGUOUS"
    #: 가장 닮은 참조영상조차 하한 아래 — 우리가 아는 기종 중에 없다.
    UNRECOGNISED = "UNRECOGNISED"
    #: 사전·모델·참조영상이 없다. 판정을 시도한 적이 없는 상태다.
    NO_REFERENCE = "NO_REFERENCE"


@dataclass(frozen=True)
class ReferenceMatch:
    """참조영상 1 장과의 유사도. 화면에 그대로 띄울 수 있는 단위다.

    `origin` 은 그 사진이 제품 사진인지 현장 사진인지이고 `weight` 는 운영자
    교정이다. 가중치 0 은 점수에서 빠졌다는 뜻이지 사라졌다는 뜻이 아니다 —
    빼 버리면 "왜 저 사진이 더 이상 근거가 아닌가"를 화면에서 되짚을 수 없다.
    """

    file: str
    similarity: float
    source_url: str = ""
    origin: str = ORIGIN_WEB
    weight: float = 1.0

    @property
    def counted(self) -> bool:
        return self.weight > 0.0

    def as_dict(self) -> dict:
        return {"file": self.file, "similarity": round(self.similarity, 4),
                "source_url": self.source_url, "origin": self.origin,
                "weight": self.weight}


@dataclass(frozen=True)
class ClassScore:
    """한 기종의 점수와 그 점수를 만든 참조영상들."""

    class_name: str
    label: str
    score: float
    #: 유사도가 높은 순서. 점수에 실제로 들어간 것은 앞의 `driving_count` 장이다.
    matches: tuple[ReferenceMatch, ...]
    driving_count: int

    @property
    def driving_references(self) -> tuple[ReferenceMatch, ...]:
        """점수를 실제로 만든 참조영상. 가중치 0 은 여기 들어오지 않는다."""
        return tuple(m for m in self.matches if m.counted)[: self.driving_count]

    def as_dict(self) -> dict:
        return {
            SEMANTIC_CLASS: self.class_name,
            "label": self.label,
            # `confidence` 가 아니다. 이 값은 상위 k 장 참조영상 코사인 유사도의
            # **가중 평균**이고, 근거가 충분한가는 다른 축이다(AI-S-03 첫 문장).
            # 한 칸에 담아 두었을 때 화면은 "0.87 확신" 으로 읽었지만 실제로는
            # "참조영상과 0.87 닮음" 이었다 — 외형은 종류만 말한다.
            WEIGHTED_REFERENCE_SIMILARITY: round(self.score, 4),
            "reference_count": len(self.matches),
            "driving_references": [m.file for m in self.driving_references],
            "references": [m.as_dict() for m in self.matches],
            "reference_origins": {
                origin: sum(1 for m in self.matches if m.origin == origin)
                for origin in (ORIGIN_WEB, ORIGIN_FIELD)
            },
            # 사전 provider 와 같은 이름을 쓴다 — 같은 뜻("무엇과 얼마나 닮았나")의
            # 근거가 모듈마다 다른 이름으로 실리면 화면이 둘을 다른 것으로 그린다.
            FEATURE_SIMILARITIES: {m.file: round(m.similarity, 4) for m in self.matches},
        }


@dataclass(frozen=True)
class AppearanceVerdict:
    """한 crop 에 대한 외형 판정. **기종이지 개체가 아니다**(AI-C-19).

    `appearance_class` 는 `CLASSIFIED` 일 때만 값을 가진다. 모호·미인식·근거없음은
    전부 `None` 이며, 그 사유와 순위는 그대로 남아 화면이 "왜 못 골랐는지"를
    보여 줄 수 있다.
    """

    state: AppearanceState
    appearance_class: str | None
    reason: str
    ranked: tuple[ClassScore, ...] = ()
    #: 1 위와 2 위의 점수 차이. 후보가 하나뿐이거나 없으면 None 이다.
    margin: float | None = None
    margin_threshold: float = DEFAULT_AMBIGUITY_MARGIN
    similarity_floor: float = DEFAULT_SIMILARITY_FLOOR
    #: 참조영상이 없어 후보가 될 수 없었던 기종 → 사유.
    unfit_classes: Mapping[str, str] = field(default_factory=dict)
    model_version: str = ""

    @property
    def classified(self) -> bool:
        return self.state is AppearanceState.CLASSIFIED

    @property
    def runner_up(self) -> ClassScore | None:
        return self.ranked[1] if len(self.ranked) > 1 else None

    def explanation(self) -> dict:
        """화면이 "왜 이 판정인가"를 그리는 데 필요한 것 전부.

        고른 이유(닮은 참조영상)와 **고르지 못한 이유**(2 위와의 차이, 참조영상이
        없는 기종)를 같은 묶음에 넣는다 — 둘을 나누면 화면은 확정만 그리게 되고
        모호는 빈칸으로 보인다.
        """
        return {
            "state": self.state.value,
            SEMANTIC_CLASS: self.appearance_class,
            "reason": self.reason,
            MODEL_VERSION: self.model_version,
            "ranked": [score.as_dict() for score in self.ranked],
            "runner_up": self.runner_up.class_name if self.runner_up else None,
            MANDATORY_GATES: {
                "margin_to_runner_up": {
                    "passed": self.state is not AppearanceState.AMBIGUOUS,
                    "margin": None if self.margin is None else round(self.margin, 4),
                    "threshold_min": self.margin_threshold,
                },
                "similarity_floor": {
                    "passed": self.state is not AppearanceState.UNRECOGNISED,
                    WEIGHTED_REFERENCE_SIMILARITY:
                        round(self.ranked[0].score, 4) if self.ranked else None,
                    "threshold_min": self.similarity_floor,
                },
            },
            "unfit_classes": dict(self.unfit_classes),
        }

    def as_dict(self) -> dict:
        return self.explanation()


# ---------------------------------------------------------------------------
# 사전 — 없는 것이 정상인 자료
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReferenceInfo:
    """참조영상 1 장의 출처 기록. 벡터와 같은 순서로 보관된다."""

    file: str
    source_url: str = ""
    origin: str = ORIGIN_WEB
    #: 운영자 교정. 0 이면 점수에서 빠지되 설명에는 남는다(AI-L-03).
    weight: float = 1.0


@dataclass(frozen=True)
class ClassReferences:
    class_name: str
    label: str
    references: tuple[ReferenceInfo, ...] = ()
    #: shape (n_references, dim), 각 행이 L2 정규화된 임베딩.
    embeddings: Any = None
    top_k: int = DEFAULT_TOP_K_REFERENCES
    unfit_reason: str = ""

    @property
    def fit(self) -> bool:
        """점수를 낼 수 있는가. 전부 0 으로 내려진 기종은 후보가 아니다."""
        return (self.embeddings is not None
                and any(info.weight > 0.0 for info in self.references))


@dataclass(frozen=True)
class AppearanceDictionary:
    """기종별 참조영상 임베딩. 비어 있을 수 있고, 비어 있는 것은 오류가 아니다."""

    classes: tuple[ClassReferences, ...] = ()
    model_version: str = ""
    ambiguity_margin: float = DEFAULT_AMBIGUITY_MARGIN
    similarity_floor: float = DEFAULT_SIMILARITY_FLOOR
    top_k: int = DEFAULT_TOP_K_REFERENCES
    missing_reason: str = ""

    @property
    def fit_classes(self) -> tuple[ClassReferences, ...]:
        return tuple(entry for entry in self.classes if entry.fit)

    @property
    def unfit_classes(self) -> dict[str, str]:
        return {entry.class_name: (entry.unfit_reason or UNFIT_NO_REFERENCE)
                for entry in self.classes if not entry.fit}

    @classmethod
    def missing(cls, reason: str) -> AppearanceDictionary:
        return cls(missing_reason=reason)

    @classmethod
    def load(cls, path: str | Path) -> AppearanceDictionary:
        """사전을 읽는다. **파일이 없으면 예외가 아니라 빈 사전이다.**

        여기서 raise 하면 사전을 배포하지 않은 노드는 기동조차 못 한다 — 선택
        기능 하나의 결손이 프로세스 생사가 되는 것이 바로 AI-C-05 가 금지한
        모양이다.
        """
        import numpy as np

        path = Path(path)
        if not path.exists():
            return cls.missing(REASON_NO_DICTIONARY)
        payload = json.loads(path.read_text(encoding="utf-8"))
        meta = payload.get("_meta", {})
        thresholds = meta.get("thresholds", {})

        entries: list[ClassReferences] = []
        for class_name, entry in payload.items():
            if class_name.startswith("_"):
                continue
            label = entry.get("label", class_name)
            references = entry.get("references") or []
            if not references:
                entries.append(ClassReferences(
                    class_name, label,
                    unfit_reason=entry.get("unfit_reason") or UNFIT_NO_REFERENCE))
                continue
            infos = tuple(
                ReferenceInfo(r["file"], r.get("source_url", ""),
                              r.get("origin", ORIGIN_WEB), float(r.get("weight", 1.0)))
                for r in references
            )
            matrix = np.array([r["embedding"] for r in references], dtype=np.float32)
            # 사전은 반올림된 수를 싣는다. 다시 정규화하지 않으면 그 반올림이
            # 유사도에 그대로 섞여 들어가고, 판정 마진(0.05)보다 작다고 해서
            # 무시해도 되는 것은 아니다 — 기종마다 다르게 섞이기 때문이다.
            matrix = matrix / np.linalg.norm(matrix, axis=1, keepdims=True)
            entries.append(ClassReferences(
                class_name, label,
                references=infos,
                unfit_reason=("" if any(i.weight > 0.0 for i in infos)
                              else UNFIT_ALL_WEIGHTS_ZERO),
                embeddings=matrix,
                top_k=int(entry.get("score_top_k_references",
                                    thresholds.get("top_k_references",
                                                   DEFAULT_TOP_K_REFERENCES))),
            ))

        model = meta.get("embedding_model", {})
        version = "/".join(str(v) for v in (model.get("id"), model.get("vision_model")) if v)
        return cls(
            classes=tuple(entries),
            model_version=version,
            ambiguity_margin=float(thresholds.get("ambiguity_margin", DEFAULT_AMBIGUITY_MARGIN)),
            similarity_floor=float(thresholds.get("similarity_floor", DEFAULT_SIMILARITY_FLOOR)),
            top_k=int(thresholds.get("top_k_references", DEFAULT_TOP_K_REFERENCES)),
        )


# ---------------------------------------------------------------------------
# 분류기
# ---------------------------------------------------------------------------


class AppearanceClassifier:
    """crop 하나를 기종으로 환산한다. 상태를 바꾸지 않는다.

    `embed` 는 crop 목록을 (n, dim) L2 정규화 임베딩으로 바꾸는 콜러블이다.
    기본값은 CLIP ONNX 를 지연 로드하는 것이고, 로드에 실패하면 `None` 으로
    남아 분류만 비활성화된다 — 그 실패가 이 모듈의 import 나 호출자의 기동을
    막지 않는다(AI-C-05).
    """

    def __init__(
        self,
        dictionary: AppearanceDictionary,
        *,
        embed: Callable[[Sequence[Any]], Any] | None = None,
        ambiguity_margin: float | None = None,
        similarity_floor: float | None = None,
    ) -> None:
        self.dictionary = dictionary
        self._embed = embed
        self.ambiguity_margin = (dictionary.ambiguity_margin if ambiguity_margin is None
                                 else ambiguity_margin)
        self.similarity_floor = (dictionary.similarity_floor if similarity_floor is None
                                 else similarity_floor)

    # -- 구성 ------------------------------------------------------------

    @classmethod
    def from_files(
        cls,
        dictionary_path: str | Path,
        *,
        model_dir: str | Path | None = None,
        **kwargs,
    ) -> AppearanceClassifier:
        """사전 파일과 (있으면) CLIP 모델 디렉터리로 분류기를 만든다.

        둘 중 어느 쪽이 없어도 분류기는 만들어진다. 없는 것은 `classify` 가
        상태로 돌려준다.
        """
        dictionary = AppearanceDictionary.load(dictionary_path)
        embed = None if model_dir is None else _lazy_clip_embed(Path(model_dir))
        return cls(dictionary, embed=embed, **kwargs)

    @property
    def available(self) -> bool:
        """지금 분류를 할 수 있는가. 거짓이어도 정상 축소 상태다."""
        return bool(self.dictionary.fit_classes) and self._embed is not None

    @property
    def unavailable_reason(self) -> str:
        if self.dictionary.missing_reason:
            return self.dictionary.missing_reason
        if not self.dictionary.fit_classes:
            return REASON_NO_FIT_CLASS
        if self._embed is None:
            return REASON_NO_ENGINE
        return ""

    @property
    def unfit_classes(self) -> dict[str, str]:
        return self.dictionary.unfit_classes

    # -- 판정 ------------------------------------------------------------

    def classify(self, crop_bgr: Any) -> AppearanceVerdict:
        """crop 한 장을 기종으로 환산한다. 모델이 없으면 그 사실을 돌려준다."""
        if not self.available:
            return self._degraded()
        embeddings = self._embed([crop_bgr])
        return self.classify_embedding(embeddings[0])

    def classify_embedding(self, embedding: Any) -> AppearanceVerdict:
        """이미 뽑아 둔 임베딩으로 판정한다.

        모델 호출과 판정 규칙을 나눠 두면 규칙을 모델 없이도 실행·검증할 수 있고,
        인지 파이프라인이 같은 crop 을 여러 번 인코딩하지 않아도 된다.
        """
        import numpy as np

        if not self.dictionary.fit_classes:
            return self._degraded()

        probe = np.asarray(embedding, dtype=np.float32)
        norm = float(np.linalg.norm(probe))
        if norm > 0:
            probe = probe / norm

        scores: list[ClassScore] = []
        for entry in self.dictionary.fit_classes:
            similarities = entry.embeddings @ probe
            order = np.argsort(similarities)[::-1]
            matches = tuple(
                ReferenceMatch(
                    entry.references[int(i)].file, float(similarities[int(i)]),
                    entry.references[int(i)].source_url,
                    entry.references[int(i)].origin, entry.references[int(i)].weight)
                for i in order
            )
            counted = [m for m in matches if m.counted]
            k = max(1, min(entry.top_k, len(counted)))
            top = counted[:k]
            total_weight = sum(m.weight for m in top)
            scores.append(ClassScore(
                entry.class_name, entry.label,
                score=float(sum(m.weight * m.similarity for m in top) / total_weight),
                matches=matches, driving_count=k))

        # 동점은 기종 이름 순으로 깬다 — 같은 입력이 실행마다 다른 순위를 내면
        # 그 순위를 근거로 한 어떤 설명도 재현되지 않는다.
        ranked = tuple(sorted(scores, key=lambda s: (-s.score, s.class_name)))
        best = ranked[0]
        margin = best.score - ranked[1].score if len(ranked) > 1 else None

        common = {
            "ranked": ranked,
            "margin": margin,
            "margin_threshold": self.ambiguity_margin,
            "similarity_floor": self.similarity_floor,
            "unfit_classes": self.unfit_classes,
            "model_version": self.dictionary.model_version,
        }
        if best.score < self.similarity_floor:
            return AppearanceVerdict(
                AppearanceState.UNRECOGNISED, None,
                f"best_similarity_below_floor:{best.score:.4f}", **common)
        if margin is not None and margin <= self.ambiguity_margin:
            # 여기서 1 위를 고르면 그것은 판단이 아니라 추측이고, 그 추측은
            # 개체 결속의 입력이 되어 명령 대상까지 흔든다(device_identity.py).
            return AppearanceVerdict(
                AppearanceState.AMBIGUOUS, None,
                f"top_two_within_margin:{best.class_name}/{ranked[1].class_name}"
                f":{margin:.4f}", **common)
        return AppearanceVerdict(
            AppearanceState.CLASSIFIED, best.class_name,
            f"separated_from_runner_up:{best.class_name}", **common)

    # -- 내부 ------------------------------------------------------------

    def _degraded(self) -> AppearanceVerdict:
        return AppearanceVerdict(
            AppearanceState.NO_REFERENCE, None, self.unavailable_reason,
            margin_threshold=self.ambiguity_margin,
            similarity_floor=self.similarity_floor,
            unfit_classes=self.unfit_classes,
            model_version=self.dictionary.model_version)


def _lazy_clip_embed(model_dir: Path) -> Callable[[Sequence[Any]], Any] | None:
    """CLIP ONNX 임베더. 파일이 없으면 `None` 이고 그것으로 끝이다.

    세션 생성은 첫 호출까지 미룬다 — 모델을 한 번도 쓰지 않는 배치에서 수백 MB
    를 읽을 이유가 없다. 사전을 만들 때와 **같은** `ClipEngine` 을 쓴다: 전처리가
    다르면 같은 사진도 다른 점으로 찍힌다.
    """
    vision = model_dir / "onnx" / "vision_model_quantized.onnx"
    text = model_dir / "onnx" / "text_model_quantized.onnx"
    tokenizer = model_dir / "tokenizer.json"
    if not (vision.exists() and text.exists() and tokenizer.exists()):
        return None

    state: dict[str, Any] = {}

    def embed(crops: Sequence[Any]) -> Any:
        if "engine" not in state:
            from mission_runtime.edge.clip_dictionary_provider import ClipEngine

            state["engine"] = ClipEngine(vision, text, tokenizer)
        return state["engine"].embed_images(list(crops))

    return embed
