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

GATE_REASONS: tuple[str, ...] = (
    REASON_NEW_BELOW_MIN,
    REASON_REGRESSION_TOO_LARGE,
    REASON_NO_EVALUATION_SET,
    REASON_LABEL_LOST,
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
class EvaluationReport:
    """후보 파라미터의 검증 결과. 승격 게이트가 이 수치를 요구한다."""

    candidate_version: str
    base_version: str | None
    new: Accuracy
    #: 기존 검증 집합에서의 정확도(후보 적용 시).
    retained: Accuracy
    #: 같은 집합에서의 기준 버전 정확도. 기준이 없으면 미측정이다.
    baseline: Accuracy
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

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_new_accuracy <= 1.0:
            raise ValueError("min_new_accuracy must be between 0 and 1")
        if self.max_regression < 0.0:
            raise ValueError("max_regression must not be negative")


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

        lost = ()
        if base is not None:
            lost = tuple(sorted(set(base.labels()) - set(candidate.labels())))

        report = EvaluationReport(
            candidate_version=candidate.version,
            base_version=base.version if base is not None else None,
            new=new, retained=retained, baseline=baseline, lost_labels=lost,
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
        return _with(report, GateResult.PASS, None)


def _with(report: EvaluationReport, result: GateResult, reason: str | None) -> EvaluationReport:
    from dataclasses import replace

    return replace(report, result=result, reason=reason)
