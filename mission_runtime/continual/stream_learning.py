"""Continual learning from the operational data stream: keep per-device
candidates, update parameters behind a replaceable provider, version the result.

implements: AI-L-09 (운영 데이터 스트림 기반 지속학습 실행)
관련: AI-L-01 (학습 후보 선별), AI-L-02 (후보 격리·품질), AI-L-03 (사용자 확인),
      AI-L-05 (검증), AI-L-07 (단계적 적용), AI-L-08 (계보), AI-B-08 (제공자 추상화)

이 모듈이 메우는 공백
---------------------
`continual/` 의 기존 모듈들은 **학습하지 않는다**고 스스로 선언한다(h2st 는 판정,
dgs 는 그룹화, ekya 는 자원 배분, replay 는 선별). `AIRuntimeProvider` 에도 `infer` 와
`is_available` 밖에 없어서 "가중치를 갱신한다"는 동사가 provider 경계에 아예 없었다.
그래서 학습 동사를 경계에 추가하고, 기기 스트림에서 온 데이터로 그것을 돌린다.

왜 프로토타입·임계 갱신이 기본 구현인가
---------------------------------------
이 시스템이 실제로 바꾸는 파라미터는 **클래스별 특징 벡터와 판정 임계**다
(데모의 `class_features.json` — 클래스마다 참조 특징 몇 개와 `target_sim_threshold`,
형태·채도·비율 게이트). 기울기 학습은 저장소 밖 오프라인 스크립트에 있고 말단에서
돌지 않는다. 그래서 **기본 제공자는 프로토타입·임계 갱신**이다 — 말단에서 돌고,
결정적이고, 결과를 사람이 읽을 수 있다. 기울기 학습이 필요하면 같은
`LearningProvider` 경계에 붙이면 되고 이 모듈은 바뀌지 않는다.

지키는 경계
-----------
- **확인되지 않은 추론 결과를 정답으로 승격하지 않는다**(AI-L-02). 후보는
  `confirmed` 가 참일 때만 학습에 들어간다. 자동 추론 결과는 후보로만 쌓인다.
- **기기와 입력 조건을 함께 보존한다**(AI-L-09). 같은 클래스라도 카메라·해상도·
  가속기가 다르면 다른 후보 묶음이다 — 한 묶음으로 섞으면 어느 기기에서 나빠졌는지
  되짚을 수 없다.
- **학습 장애가 운영을 멈추지 않는다.** 이 모듈은 추론 경로를 호출하지 않고, 실패는
  예외가 아니라 `TrainingOutcome` 의 사유로 돌아온다.
- 갱신 결과는 **후보 버전**이고 운영 적용은 기존 검증·승인·단계적 적용 경로를 거친다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Protocol, Sequence

#: 후보가 학습에 쓰일 수 없는 사유 토큰.
REASON_NOT_CONFIRMED = "candidate_not_confirmed"
REASON_NO_CONFIRMED_SAMPLES = "no_confirmed_samples"
REASON_TOO_FEW_SAMPLES = "too_few_confirmed_samples"
REASON_DIMENSION_MISMATCH = "feature_dimension_mismatch"
REASON_PROVIDER_FAILED = "learning_provider_failed"

TRAINING_REASONS: tuple[str, ...] = (
    REASON_NOT_CONFIRMED,
    REASON_NO_CONFIRMED_SAMPLES,
    REASON_TOO_FEW_SAMPLES,
    REASON_DIMENSION_MISMATCH,
    REASON_PROVIDER_FAILED,
)


class CandidateOrigin(str, Enum):
    """후보가 어디서 왔는가. 자동 추론과 사람 확인을 섞지 않는다."""

    AUTO_INFERENCE = "AUTO_INFERENCE"
    HUMAN_CONFIRMED = "HUMAN_CONFIRMED"
    EXTERNAL_LABEL = "EXTERNAL_LABEL"


class SamplePolarity(str, Enum):
    """그 표본이 라벨의 **예** 인가 **반례** 인가.

    왜 필요했는가
    -------------
    사람이 "여기 아무것도 없다" 로 지운 상자는 **확인된 음성**이고, 그것은
    `ConfirmedAcceptanceScorer` 가 docstring 에 "진짜 판별 수치가 필요하면 확인된
    음성 표본이 먼저 있어야 한다" 고 적어 둔 바로 그 자료다. 그런데 극성 칸이 없어서
    그 음성이 **양성 후보로** 들어왔다. `label` 이 비어 `"absent"` 라는 이름이
    붙고, 상자가 없어 특징이 `(0,0,0,0)` 이 되고, 그 셋이 모이면
    `parameters["absent"]` 가 **임계 0.0 — 모든 것을 받아들이는 클래스** 로
    생긴다(2026-11-04 재현 확인). 한 칸이 없어서 사람의 정답이 뒤집혔다.

    음성은 **버리지도** 않는다. 버리면 임계를 교정할 자료가 사라지고, 위 scorer 가
    기다리는 음성이 영원히 오지 않는다.
    """

    POSITIVE = "POSITIVE"
    #: 그 라벨이 **아니라고** 사람이 확인한 표본. 프로토타입의 재료가 아니고
    #: 임계 교정의 재료다.
    NEGATIVE = "NEGATIVE"


class SampleUsage(str, Enum):
    """그 표본이 파라미터를 **바꾸는** 데 쓰이는가 **재는** 데 쓰이는가.

    왜 필요했는가
    -------------
    회귀는 "전에 되던 것이 아직 되는가" 다. 그런데 그 측정을 후보가 **학습에 쓴
    표본**에서 하면 train-set 평가이고, 전에 되던 것이 깨졌는지는 거기서 보이지
    않는다 — 후보는 그 표본에 맞춰진 것이기 때문이다.

    마침 그 측정에 가장 맞는 자료가 이미 만들어져 있고 아무 데도 가지 않는다:
    사람이 검수해서 **모델이 맞았다고 확인한** 상자들이다. 그것을 학습 후보로
    올리지 않는 기존 판단은 맞다(AI-L-01: 후보가 전체 스트림으로 불어난다). 다만
    올리지 않는 것과 **버리는 것**은 다르고, 지금까지는 버려지고 있었다.

    `EVALUATION_ONLY` 는 파라미터를 바꾸지 않는다. 섞으면 후보가 "이미 맞히던
    것" 쪽으로 당겨지고, 그것은 반대 방향의 같은 편향이며 train/eval 분리도
    사라진다. 출처: `docs/research/hitl-data-and-weight-management.md` §9.7.
    """

    TRAINING = "TRAINING"
    EVALUATION_ONLY = "EVALUATION_ONLY"


@dataclass(frozen=True)
class InputConditions:
    """후보를 만든 입력 조건. 기기별 구분의 근거다(AI-L-09).

    값은 전부 자유 문자열·숫자이고 이 모듈은 어느 값으로도 분기하지 않는다.
    """

    device_id: str
    camera_id: str | None = None
    #: (width, height). 모르면 None 이고 지어내지 않는다.
    resolution: tuple[int, int] | None = None
    accelerator_id: str | None = None
    #: 추가 조건(렌즈·crop·조명 등). 키 이름은 호출자가 정한다.
    extra: tuple[tuple[str, str], ...] = ()

    @property
    def group_key(self) -> tuple:
        """같은 묶음으로 볼 조건. 기기·카메라·해상도·가속기가 같아야 한 묶음이다."""
        return (self.device_id, self.camera_id, self.resolution, self.accelerator_id,
                self.extra)


@dataclass(frozen=True)
class StreamSample:
    """스트림에서 받은 후보 1건.

    `feature` 는 모델이 낸 특징 벡터다. 픽셀은 담지 않는다 — 업무·관측 메시지에
    픽셀을 싣지 않는 기존 경계(AI-C-08)와 같은 이유이고, 원본이 필요하면
    `frame_ref` 로 되짚는다.
    """

    sample_id: str
    conditions: InputConditions
    label: str
    feature: tuple[float, ...]
    origin: CandidateOrigin
    #: 원본 관측을 되짚는 참조(프레임·시퀀스). 자유 문자열이다.
    frame_ref: str | None = None
    confidence: float | None = None
    #: 이 표본이 선언된 라벨의 기준(프로토타입·프롬프트)과 얼마나 닮았는가.
    #: 임계를 조정하는 제공자가 이 값을 읽는다. 특징 벡터가 없는 파이프라인
    #: (텍스트 프롬프트 기반)에서도 임계 학습이 가능하도록 별 칸으로 둔다.
    similarity: float | None = None
    observed_at: float | None = None
    #: 라벨의 예인가 반례인가. 기본이 양성이라 기존 호출 경로는 그대로다.
    polarity: SamplePolarity = SamplePolarity.POSITIVE
    #: 파라미터를 바꾸는 데 쓰는가, 재는 데만 쓰는가. 기본이 학습이라 기존 호출
    #: 경로는 그대로다.
    usage: SampleUsage = SampleUsage.TRAINING

    def __post_init__(self) -> None:
        if not self.sample_id:
            raise ValueError("sample_id must not be empty")
        if not self.label:
            raise ValueError("label must not be empty")
        if not self.feature:
            raise ValueError("feature must not be empty")

    @property
    def confirmed(self) -> bool:
        """학습에 쓸 수 있는가. 자동 추론 결과는 **아니다**(AI-L-02)."""
        return self.origin in (CandidateOrigin.HUMAN_CONFIRMED,
                               CandidateOrigin.EXTERNAL_LABEL)


@dataclass(frozen=True)
class CandidateBatch:
    """한 조건 묶음의 후보들."""

    conditions: InputConditions
    samples: tuple[StreamSample, ...] = ()

    def confirmed(self) -> tuple[StreamSample, ...]:
        return tuple(s for s in self.samples if s.confirmed)

    def confirmed_positives(self) -> tuple[StreamSample, ...]:
        """프로토타입의 재료. **음성도 평가 전용도 들어오지 않는다.**"""
        return tuple(s for s in self.confirmed()
                     if s.polarity is SamplePolarity.POSITIVE
                     and s.usage is SampleUsage.TRAINING)

    def confirmed_negatives(self) -> tuple[StreamSample, ...]:
        """임계 교정의 재료. "그 라벨이 아니다" 라고 사람이 확인한 표본들."""
        return tuple(s for s in self.confirmed()
                     if s.polarity is SamplePolarity.NEGATIVE
                     and s.usage is SampleUsage.TRAINING)

    def evaluation_only(self) -> tuple[StreamSample, ...]:
        """재는 데만 쓰는 표본. **파라미터를 바꾸지 않는다.**

        회귀를 이 집합에서 재면 후보가 맞춰지지 않은 자료에서 재는 것이 된다.
        """
        return tuple(s for s in self.confirmed()
                     if s.usage is SampleUsage.EVALUATION_ONLY)

    def labels(self) -> tuple[str, ...]:
        return tuple(sorted({s.label for s in self.confirmed()}))


class CandidateStore:
    """기기·입력 조건별 후보 보관. 보존 한도를 넘으면 오래된 것부터 버린다.

    저장 자체는 백엔드 책임이므로(AI-L-02) 이것은 **프로세스 안의 단기 보관**이고
    장기 보존은 외부 저장소가 받는다. 그 경계를 흐리지 않도록 영속화를 하지 않는다.
    """

    def __init__(self, *, per_group_limit: int = 500) -> None:
        if per_group_limit < 1:
            raise ValueError("per_group_limit must be at least 1")
        self._limit = per_group_limit
        self._groups: dict[tuple, list[StreamSample]] = {}

    def add(self, sample: StreamSample) -> None:
        bucket = self._groups.setdefault(sample.conditions.group_key, [])
        bucket.append(sample)
        if len(bucket) > self._limit:
            del bucket[: len(bucket) - self._limit]

    def extend(self, samples: Sequence[StreamSample]) -> None:
        for sample in samples:
            self.add(sample)

    def groups(self) -> tuple[InputConditions, ...]:
        return tuple(
            batch.conditions for batch in sorted(
                (self.batch(key) for key in self._groups),
                key=lambda b: str(b.conditions.group_key),
            )
        )

    def batch(self, group_key: tuple) -> CandidateBatch:
        samples = tuple(self._groups.get(group_key, ()))
        if not samples:
            raise KeyError(group_key)
        return CandidateBatch(conditions=samples[0].conditions, samples=samples)

    def batch_for(self, conditions: InputConditions) -> CandidateBatch:
        return self.batch(conditions.group_key)

    def confirmed_count(self) -> int:
        return sum(len(CandidateBatch(s[0].conditions, tuple(s)).confirmed())
                   for s in self._groups.values() if s)

    def total_count(self) -> int:
        return sum(len(s) for s in self._groups.values())


# -- 학습 제공자 경계 --------------------------------------------------------


@dataclass(frozen=True)
class ParameterSet:
    """학습 결과. 어떤 조건에서 어떤 데이터로 만들었는지 함께 들고 다닌다.

    `version` 은 내용에서 파생한다 — 같은 입력이면 같은 버전이고, 다른 입력이면
    다른 버전이다. 이름을 사람이 붙이면 같은 이름 다른 내용이 생긴다.
    """

    #: 클래스별 파라미터. 예: {"door": {"prototype": [...], "threshold": 0.27}}
    parameters: dict[str, dict]
    conditions: InputConditions
    base_version: str | None = None
    sample_ids: tuple[str, ...] = ()
    #: 이 파라미터를 만든 제공자 이름. 비교·재현에 쓴다.
    produced_by: str = ""

    @property
    def version(self) -> str:
        payload = json.dumps(
            {
                "parameters": self.parameters,
                "conditions": list(map(str, self.conditions.group_key)),
                "base": self.base_version,
                "by": self.produced_by,
            },
            sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        return f"sha256-{digest}"

    def labels(self) -> tuple[str, ...]:
        return tuple(sorted(self.parameters))


@dataclass(frozen=True)
class TrainingOutcome:
    """학습 시도의 결과. 실패도 값으로 돌아온다 — 예외로 운영을 흔들지 않는다."""

    parameters: ParameterSet | None
    reason: str | None = None
    used_sample_ids: tuple[str, ...] = ()

    @property
    def produced(self) -> bool:
        return self.parameters is not None


class LearningProvider(Protocol):
    """가중치·파라미터를 갱신하는 경계.

    `AIRuntimeProvider` 에 없던 동사다. 구현은 프로토타입 갱신일 수도, 기울기
    학습일 수도 있고 이 계약은 둘을 구분하지 않는다 — 어떤 방법이 맞는지는 데이터와
    장치에 따라 달라지므로 요구사항이 고정하지 않는다(AI-L-04).
    """

    @property
    def name(self) -> str: ...

    def train(self, batch: CandidateBatch, *, base: ParameterSet | None) -> TrainingOutcome: ...


class PrototypeLearningProvider:
    """확인된 후보의 특징 평균으로 클래스 프로토타입과 임계를 갱신한다.

    이 시스템이 실제로 바꾸는 파라미터가 그것이기 때문에 기본 구현으로 둔다. 기울기
    학습을 쓰지 않으므로 말단에서 돌고 같은 입력이면 같은 결과가 나온다.

    임계는 **확인된 표본과 프로토타입 사이 유사도의 하위 분위**로 정한다. 평균을
    쓰면 표본 절반이 임계 아래로 떨어지고, 최솟값을 쓰면 이상치 하나가 임계를
    끌어내린다. `quantile` 로 그 사이를 고른다.
    """

    def __init__(self, *, min_samples: int = 3, quantile: float = 0.1,
                 momentum: float = 0.0) -> None:
        if min_samples < 1:
            raise ValueError("min_samples must be at least 1")
        if not 0.0 <= quantile <= 1.0:
            raise ValueError("quantile must be between 0 and 1")
        if not 0.0 <= momentum < 1.0:
            raise ValueError("momentum must be in [0, 1)")
        self._min_samples = min_samples
        self._quantile = quantile
        self._momentum = momentum

    @property
    def name(self) -> str:
        return (f"prototype(min_samples={self._min_samples},"
                f"quantile={self._quantile},momentum={self._momentum})")

    def train(self, batch: CandidateBatch, *, base: ParameterSet | None) -> TrainingOutcome:
        # **양성만** 프로토타입의 재료다. 음성을 섞으면 "그 라벨이 아니다" 로 확인된
        # 표본이 그 라벨의 평균으로 들어간다 — 사람의 정답이 뒤집힌다.
        confirmed = batch.confirmed_positives()
        negatives = batch.confirmed_negatives()
        if not confirmed:
            return TrainingOutcome(None, REASON_NO_CONFIRMED_SAMPLES)

        dimension = len(confirmed[0].feature)
        if any(len(s.feature) != dimension for s in confirmed):
            return TrainingOutcome(None, REASON_DIMENSION_MISMATCH)

        by_label: dict[str, list[StreamSample]] = {}
        for sample in confirmed:
            by_label.setdefault(sample.label, []).append(sample)

        parameters: dict[str, dict] = {}
        used: list[str] = []
        for label in sorted(by_label):
            samples = by_label[label]
            if len(samples) < self._min_samples:
                continue
            prototype = _mean(tuple(s.feature for s in samples))
            previous = (base.parameters.get(label, {}).get("prototype")
                        if base is not None else None)
            if previous is not None and len(previous) == dimension and self._momentum:
                prototype = tuple(
                    self._momentum * float(p) + (1.0 - self._momentum) * n
                    for p, n in zip(previous, prototype)
                )
            similarities = sorted(_cosine(s.feature, prototype) for s in samples)
            threshold = similarities[
                min(len(similarities) - 1, int(self._quantile * (len(similarities) - 1)))
            ]
            entry = {
                "prototype": [round(v, 6) for v in prototype],
                "threshold": round(threshold, 6),
                "sample_count": len(samples),
            }
            used += [s.sample_id for s in samples]

            # 확인된 음성이 있으면 임계를 그 위로 올린다. 양성만으로 정한 임계는
            # "받아들이는 몫" 만 말하고 **거짓 양성을 걸러 내는지는 말하지 못한다** —
            # OpenMax(Bendale & Boult, CVPR 2016)도 절대 임계를 양성만으로 교정하기
            # 어렵다고 적고 open-set 표본을 함께 썼다. 음성을 전부 밀어낼 수 없으면
            # **임계를 올리지 않고 그 사실을 적는다** — 올려 버리면 양성까지 잘린다.
            against = [s for s in negatives if s.label == label
                       and len(s.feature) == dimension]
            if against:
                negative_best = max(_cosine(s.feature, prototype) for s in against)
                entry["negative_sample_count"] = len(against)
                entry["negative_max_similarity"] = round(negative_best, 6)
                if negative_best < threshold:
                    entry["threshold_separates_negatives"] = True
                else:
                    # 음성이 양성 임계 안에 들어온다. 이 특징 공간에서는 그 둘이
                    # 갈리지 않는다는 사실이고, 숨기면 임계가 괜찮은 척한다.
                    entry["threshold_separates_negatives"] = False
                used += [s.sample_id for s in against]
            parameters[label] = entry

        if not parameters:
            return TrainingOutcome(None, REASON_TOO_FEW_SAMPLES)

        return TrainingOutcome(
            ParameterSet(
                parameters=parameters,
                conditions=batch.conditions,
                base_version=base.version if base is not None else None,
                sample_ids=tuple(used),
                produced_by=self.name,
            ),
            used_sample_ids=tuple(used),
        )


def _mean(vectors: Sequence[tuple[float, ...]]) -> tuple[float, ...]:
    count = len(vectors)
    return tuple(sum(v[i] for v in vectors) / count for i in range(len(vectors[0])))


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# -- 스트림 → 학습 루프 ------------------------------------------------------


@dataclass
class ContinualLearner:
    """스트림을 받아 조건 묶음별로 후보 버전을 만든다.

    운영 적용은 하지 않는다 — 만들어진 `ParameterSet` 은 후보이고, 검증(AI-L-05)과
    승인·단계적 적용(AI-L-06/07)을 거쳐야 운영에 들어간다. 그 경계를 이 클래스가
    넘지 않도록 적용 메서드를 두지 않았다.
    """

    provider: LearningProvider
    store: CandidateStore = field(default_factory=CandidateStore)
    #: 조건 묶음별 현재 기준 파라미터. 없으면 처음부터 만든다.
    bases: dict[tuple, ParameterSet] = field(default_factory=dict)

    def ingest(self, sample: StreamSample) -> None:
        self.store.add(sample)

    def ingest_many(self, samples: Sequence[StreamSample]) -> None:
        self.store.extend(samples)

    def train_group(self, conditions: InputConditions) -> TrainingOutcome:
        try:
            batch = self.store.batch_for(conditions)
        except KeyError:
            return TrainingOutcome(None, REASON_NO_CONFIRMED_SAMPLES)
        base = self.bases.get(conditions.group_key)
        try:
            outcome = self.provider.train(batch, base=base)
        except Exception as error:      # 학습 실패가 운영을 멈추지 않는다
            return TrainingOutcome(None, f"{REASON_PROVIDER_FAILED}:{type(error).__name__}")
        return outcome

    def train_all(self) -> dict[tuple, TrainingOutcome]:
        return {c.group_key: self.train_group(c) for c in self.store.groups()}

    def adopt(self, outcome: TrainingOutcome) -> None:
        """다음 학습의 기준을 이 결과로 바꾼다.

        **운영 적용이 아니다.** 검증·승인을 통과한 뒤 호출자가 부르는 것이고, 여기서
        부르면 다음 갱신이 이 버전 위에 쌓인다.
        """
        if outcome.parameters is None:
            raise ValueError("an outcome without parameters cannot become the base")
        self.bases[outcome.parameters.conditions.group_key] = outcome.parameters

    def base_version(self, conditions: InputConditions) -> str | None:
        base = self.bases.get(conditions.group_key)
        return base.version if base is not None else None
