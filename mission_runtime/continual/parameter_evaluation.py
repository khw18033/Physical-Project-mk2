"""Held-out evaluation of a candidate parameter set: did it improve, and did it
lose anything it used to get right.

implements: AI-L-05 (학습 결과 검증·기존 지식 보존), AI-L-09
관련: AI-B-01 (미측정 항목 구분), AI-O-05 (목표 기준선 3값 판정)

왜 필요했는가
-------------
기존 `continual/` 에는 품질 검증이 없었다 — `dgs` 의 forgetting 게이트는 adapter
state 의 이동량을 보는 **대리지표**이고 기본값이 꺼져 있으며, held-out 평가가 아니다.
그래서 후보 파라미터가 "새 데이터에서 나아졌는가"와 "전에 맞히던 것을 잃었는가"를
각각 재는 자리가 비어 있었다. 승격 게이트가 자유 문자열 근거를 받는 것도 그 때문이다.

두 축을 따로 잰다
-----------------
한 수치로 합치면 새 것에서 오른 만큼 옛 것에서 내려간 경우가 통과한다. 그래서
`new` 와 `regression` 을 분리하고, **둘 다** 기준을 넘어야 통과다(AI-L-05: "새
데이터·환경에 대한 개선 여부와 기존에 검증된 ... 성능 저하 여부를 함께 평가").

못 쟨 것은 통과가 아니다
------------------------
평가 집합이 비어 있으면 `NOT_MEASURED` 이고 이것은 PASS 가 아니다. 측정이 없는데
통과시키면 게이트가 아무것도 막지 못한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Sequence

from mission_runtime.continual.stream_learning import ParameterSet, StreamSample, _cosine


class GateResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_MEASURED = "NOT_MEASURED"


#: 게이트가 막은 사유 토큰.
REASON_NEW_BELOW_MIN = "new_accuracy_below_minimum"
REASON_REGRESSION_TOO_LARGE = "regression_exceeds_allowance"
REASON_NO_EVALUATION_SET = "no_evaluation_samples"
REASON_LABEL_LOST = "previously_known_label_missing"
#: 집계는 괜찮은데 **개별 표본이 깨진** 경우. 아래 `FlipCount` 참조.
REASON_TOO_MANY_NEGATIVE_FLIPS = "negative_flips_exceed_allowance"

GATE_REASONS: tuple[str, ...] = (
    REASON_NEW_BELOW_MIN,
    REASON_REGRESSION_TOO_LARGE,
    REASON_NO_EVALUATION_SET,
    REASON_LABEL_LOST,
    REASON_TOO_MANY_NEGATIVE_FLIPS,
)


class ParameterScorer(Protocol):
    """파라미터 집합으로 한 표본을 분류한다. 교체 가능하다."""

    def predict(self, parameters: ParameterSet, sample: StreamSample) -> str | None: ...


class PrototypeScorer:
    """프로토타입 유사도가 임계를 넘는 클래스 중 가장 가까운 것으로 분류한다.

    임계를 넘는 것이 없으면 `None` 이다 — 억지로 가장 가까운 클래스를 붙이지 않는다.
    미확인을 기존 클래스에 강제 매핑하지 않는 기존 규칙(AI-S-04)과 같은 판단이다.
    """

    def predict(self, parameters: ParameterSet, sample: StreamSample) -> str | None:
        best: tuple[float, str] | None = None
        for label, spec in parameters.parameters.items():
            prototype = spec.get("prototype")
            threshold = spec.get("threshold")
            if not prototype or threshold is None:
                continue
            if len(prototype) != len(sample.feature):
                continue
            similarity = _cosine(sample.feature, prototype)
            if similarity < float(threshold):
                continue
            if best is None or similarity > best[0]:
                best = (similarity, label)
        return None if best is None else best[1]


class ConfirmedAcceptanceScorer:
    """선언된 임계가 **확인된 표본을 아직 받아들이는가**를 본다.

    왜 따로 필요했는가
    ------------------
    `PrototypeScorer` 는 `prototype` 벡터를 요구한다. 그런데 운영 스트림 입구
    (`continual/operational_stream.py`)에서 오는 후보는 특징 벡터가 없다 — 검출기가
    내는 수치는 신뢰도 하나이고, 거기에 맞는 학습 제공자가
    `ThresholdLearningProvider` 다. 그 제공자가 만든 파라미터
    (`prompts` + `threshold`, `prototype` 없음)를 `PrototypeScorer` 로 재면 **언제나
    `None`** 이 나와 정확도가 0이 되고, 그러면 실제 자료로 만든 후보는 AI-L-05 검증을
    **구조적으로 통과할 수 없다.** 그 자리를 메운다.

    이 수치가 무엇이 **아닌지**
    ---------------------------
    이것은 판별 성능이 아니다. 표본이 들고 온 라벨을 입력으로 쓰므로 오탐을 잴 수
    없다 — 운영 스트림에는 "이것은 그 라벨이 아니다" 라고 **확인된** 표본이 없기
    때문이다. 즉 이 비율은 "확인된 관측 중 이 임계가 여전히 받아들이는 몫" 이고,
    임계를 낮추면 올라간다. 그래서 이 점수만으로 임무의 품질 요구
    (`MissionRequirement.min_quality`)를 만족한다고 읽어서는 안 된다. 진짜 판별
    수치가 필요하면 확인된 음성 표본이 먼저 있어야 하고, 그것은 사용자 확인
    (AI-L-03)에서 온다. 이름에 `Acceptance` 를 넣어 둔 것이 그 경계이고, 이 설명을
    지우고 이름만 바꾸면 그 경계가 사라진다.

    회귀 축은 그대로 뜻이 있다
    --------------------------
    같은 표본 집합에서 기준 임계와 후보 임계를 각각 재므로, 임계가 올라가 전에
    받아들이던 관측을 더 이상 받아들이지 못하는 것이 `regression` 으로 나온다.
    AI-L-05 가 요구하는 "기존에 검증된 ... 성능 저하 여부" 가 이 축이다.
    """

    def predict(self, parameters: ParameterSet, sample: StreamSample) -> str | None:
        spec = parameters.parameters.get(sample.label)
        if spec is None:
            return None
        threshold = spec.get("threshold")
        if threshold is None:
            # 임계를 재지 않은 라벨은 통과도 탈락도 아니다 — 미측정이다.
            return None
        score = sample.similarity
        if score is None:
            return None
        return sample.label if float(score) >= float(threshold) else None


@dataclass(frozen=True)
class Accuracy:
    """맞힌 수와 전체. 비율만 들고 다니면 표본 수가 사라진다."""

    correct: int
    total: int

    @property
    def measured(self) -> bool:
        return self.total > 0

    @property
    def ratio(self) -> float | None:
        return None if self.total == 0 else self.correct / self.total


@dataclass(frozen=True)
class FlipCount:
    """표본 단위로 **뒤집힌** 수. 집계 회귀가 못 보는 축이다.

    왜 집계로는 부족한가
    --------------------
    `regression` 은 `baseline.ratio - retained.ratio` 다. 그래서 기준이 맞혔던 것
    **5개를 깨고** 틀렸던 것 5개를 고친 후보는 회귀가 **0 이고 통과한다.** 집계만
    보면 "변화 없음" 이지만 운영에서는 전에 되던 것 5개가 안 되기 시작한다.

    문헌 근거: Yan et al., *Positive-Congruent Training*(CVPR 2021)은 재학습한
    ResNet-50 이 정확도를 약 12% 올리면서도 표본의 3.56% 를 negative flip 으로
    깼다고 보고한다(영상 분류, ImageNet). 집계 개선과 개별 파괴가 **함께** 일어난다.

    `negative` 와 `positive` 를 따로 세는 이유는 상쇄를 막기 위해서다 — 차이만
    들고 다니면 그것이 바로 집계 회귀이고 이 자료형의 목적이 사라진다.
    """

    #: 기준은 맞혔는데 후보가 틀린 표본 수. **이것이 운영에서 깨지는 것들이다.**
    negative: int = 0
    #: 기준이 틀렸는데 후보가 맞힌 표본 수.
    positive: int = 0
    #: 쌍으로 견준 표본 수. 0 이면 미측정이고 "뒤집힘 없음" 이 아니다.
    total: int = 0

    @property
    def measured(self) -> bool:
        return self.total > 0

    @property
    def negative_ratio(self) -> float | None:
        """미측정이면 None. **0.0 이 아니다** — 재지 않은 것을 "안 깨졌다" 로
        읽으면 그 게이트는 아무것도 막지 못한다."""
        return None if self.total == 0 else self.negative / self.total

    def as_dict(self) -> dict:
        return {"negative": self.negative, "positive": self.positive,
                "total": self.total,
                "negative_ratio": (None if self.negative_ratio is None
                                   else round(self.negative_ratio, 6))}


@dataclass(frozen=True)
class EvaluationReport:
    """후보 파라미터의 검증 결과. 승격 게이트가 이 수치를 요구한다."""

    candidate_version: str
    base_version: str | None
    new: Accuracy
    #: 기존 검증 집합에서의 정확도(후보 적용 시).
    retained: Accuracy
    #: 같은 집합에서의 기준 버전 정확도. 기준이 없으면 미측정이다.
    baseline: Accuracy
    #: 같은 집합에서 표본 단위로 뒤집힌 수. 집계 회귀와 **다른 축**이다.
    flips: FlipCount = FlipCount()
    lost_labels: tuple[str, ...] = ()
    result: GateResult = GateResult.NOT_MEASURED
    reason: str | None = None

    @property
    def regression(self) -> float | None:
        """기준 대비 떨어진 양(양수면 나빠졌다). 한쪽이라도 미측정이면 None."""
        if self.retained.ratio is None or self.baseline.ratio is None:
            return None
        return self.baseline.ratio - self.retained.ratio


@dataclass(frozen=True)
class EvaluationGate:
    """통과 조건. 두 축을 따로 본다."""

    #: 새 데이터에서 요구하는 최소 정확도.
    min_new_accuracy: float = 0.7
    #: 기존 집합에서 허용하는 하락폭. 0.0 이면 어떤 하락도 허용하지 않는다.
    max_regression: float = 0.02
    #: 기준이 알던 라벨이 후보에서 사라지는 것을 막는다.
    forbid_label_loss: bool = True
    #: 기준이 맞혔던 표본 중 후보가 깨도 되는 몫. **집계 회귀와 별도로** 걸린다 —
    #: 상쇄된 파괴를 막는 유일한 축이다. 허용치의 근거는 아직 우리 자료에서 재지
    #: 않았다(인용한 3.56% 는 ImageNet 분류 수치다). 그래서 기본값을 0.0 보다
    #: 느슨하게 두지 않는다 — 느슨한 기본값은 근거 없이 파괴를 허용하는 것이다.
    max_negative_flip_ratio: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_new_accuracy <= 1.0:
            raise ValueError("min_new_accuracy must be between 0 and 1")
        if self.max_regression < 0.0:
            raise ValueError("max_regression must not be negative")
        if not 0.0 <= self.max_negative_flip_ratio <= 1.0:
            raise ValueError("max_negative_flip_ratio must be between 0 and 1")


class ParameterEvaluator:
    """후보를 새 집합과 기존 집합에서 각각 재고 게이트를 적용한다."""

    def __init__(self, scorer: ParameterScorer | None = None) -> None:
        self._scorer = scorer or PrototypeScorer()

    def _accuracy(self, parameters: ParameterSet | None,
                  samples: Sequence[StreamSample]) -> Accuracy:
        if parameters is None or not samples:
            return Accuracy(0, 0)
        correct = sum(
            1 for s in samples if self._scorer.predict(parameters, s) == s.label
        )
        return Accuracy(correct, len(samples))

    def _flips(self, candidate: ParameterSet, base: ParameterSet | None,
               samples: Sequence[StreamSample]) -> FlipCount:
        """같은 표본에서 **쌍으로** 견준다. 기준이 없으면 미측정이다.

        `_accuracy` 가 이미 같은 집합에서 둘을 각각 재고 있었다 — 빠져 있던 것은
        표본별 짝짓기뿐이고, 그 짝이 없으면 깨진 것과 고친 것이 서로를 지운다.
        """
        if base is None or not samples:
            return FlipCount()
        negative = positive = 0
        for sample in samples:
            was_right = self._scorer.predict(base, sample) == sample.label
            is_right = self._scorer.predict(candidate, sample) == sample.label
            if was_right and not is_right:
                negative += 1
            elif is_right and not was_right:
                positive += 1
        return FlipCount(negative=negative, positive=positive, total=len(samples))

    def evaluate(
        self,
        candidate: ParameterSet,
        *,
        new_samples: Sequence[StreamSample],
        retained_samples: Sequence[StreamSample],
        base: ParameterSet | None = None,
        gate: EvaluationGate | None = None,
    ) -> EvaluationReport:
        gate = gate or EvaluationGate()
        new = self._accuracy(candidate, new_samples)
        retained = self._accuracy(candidate, retained_samples)
        baseline = self._accuracy(base, retained_samples)
        flips = self._flips(candidate, base, retained_samples)

        lost = ()
        if base is not None:
            lost = tuple(sorted(set(base.labels()) - set(candidate.labels())))

        report = EvaluationReport(
            candidate_version=candidate.version,
            base_version=base.version if base is not None else None,
            new=new, retained=retained, baseline=baseline, flips=flips,
            lost_labels=lost,
        )

        if not new.measured:
            return _with(report, GateResult.NOT_MEASURED, REASON_NO_EVALUATION_SET)
        assert new.ratio is not None
        if new.ratio < gate.min_new_accuracy:
            return _with(report, GateResult.FAIL, REASON_NEW_BELOW_MIN)
        if gate.forbid_label_loss and lost:
            return _with(report, GateResult.FAIL, REASON_LABEL_LOST)
        regression = report.regression
        if regression is not None and regression > gate.max_regression:
            return _with(report, GateResult.FAIL, REASON_REGRESSION_TOO_LARGE)
        # 집계가 통과한 뒤에 본다. 집계 회귀 0 인 후보가 여기서 걸리는 것이 이
        # 축의 존재 이유다 — 5개를 깨고 5개를 고친 후보가 그렇다.
        flip_ratio = report.flips.negative_ratio
        if flip_ratio is not None and flip_ratio > gate.max_negative_flip_ratio:
            return _with(report, GateResult.FAIL, REASON_TOO_MANY_NEGATIVE_FLIPS)
        return _with(report, GateResult.PASS, None)


def _with(report: EvaluationReport, result: GateResult, reason: str | None) -> EvaluationReport:
    from dataclasses import replace

    return replace(report, result=result, reason=reason)
