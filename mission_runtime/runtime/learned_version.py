"""검증을 통과한 **학습 후보**를 배정·배포가 실제로 고를 수 있는 버전으로 올린다.

implements: AI-L-07 (단계적 적용), AI-L-08 (학습·적용 계보 추적), AI-L-10 (모델 배정)
관련: AI-L-05 (검증), AI-L-06 (승인 정보), AI-L-09 (운영 스트림 학습),
      AI-B-01 (검증된 적용 범위·미측정 구분), AI-C-16 (내부 조달), AI-O-05 (미측정 ≠ 0)
tests: tests/test_model_promotion.py

이 모듈이 메우는 **끊긴 자리**
------------------------------
학습 쪽과 배포 쪽이 각각 완성되어 있으면서 **서로 닿지 않았다.**

    continual/stream_learning.py      ParameterSet        (후보 버전)
    continual/parameter_evaluation.py EvaluationReport    (AI-L-05 게이트)
    continual/lineage.py              LearningLineage     (AI-L-06 승인 상태)
            ↓  ←— 여기가 비어 있었다
    runtime/model_assignment.py       ModelVersion        (배정 후보)
    runtime/mlops_pipeline.py         submit/widen/rollback (AI-L-07)

증상이 조용했기 때문에 더 나쁘다. `MlopsPipeline.submit` 은 승인된 **계보**를
요구하고 그 관문은 제대로 동작한다. 그런데 실제로 올라가는 버전은
`ModelAssigner.versions` — 즉 손으로 적은 `config/model_versions.example.json` —
에서 나온다. 학습으로 만들어진 `ParameterSet` 은 그 목록에 **한 번도 등록되지
않는다.** 그래서 지금 경로는 "후보 sha256-abc 를 승인했다" 는 계보를 들고
`yolo-world@v2-s` 를 올릴 수 있다. 배포는 성공하고 계보는 남지만 **계보가 가리키는
학습과 실제로 올라간 것이 다른 것**이고, 그러면 AI-L-08 의 역추적이 바로 그 자리에서
거짓을 말한다. 이 모듈은 그 등록을 하고, 등록할 수 없는 경우를 사유로 거절한다.

올리지 않는 여섯 가지 — 전부 거절 사유가 된다
---------------------------------------------
1. **게이트를 통과하지 않은 후보.** `GateResult.PASS` 가 아니면 올리지 않는다.
   `NOT_MEASURED` 도 통과가 아니다(AI-L-05).
2. **다른 후보의 성적표.** `EvaluationReport.candidate_version` 이 그 후보의
   `version` 과 다르면 거절한다. 이것이 위에서 말한 실패의 축소판이다 — 성적표와
   물건이 짝이 맞지 않으면 품질 수치가 다른 물건의 것이 된다.
3. **성적표가 없는 후보.** `report=None` 은 "아직 안 쟀다" 이고 통과가 아니다.
4. **다른 후보의 계보.** 계보가 그 후보의 버전을 근거로 든 적이 없으면 거절한다
   (`LearningLineage.cites`). 2 와 같은 모양이지만 결과가 더 나쁘다 — 승인은
   사람의 행위라서, 어긋난 계보를 붙이면 운영자가 보지도 않은 물건을 그 사람이
   승인한 것으로 기록된다(AI-L-06). 통과한 계보는 `Promotion.lineage` 로 **그
   버전과 한 자료형에 묶여** 나간다. 적용하는 쪽이 계보와 버전을 따로 받으면
   그 자리에서 다시 어긋날 수 있기 때문이다.
5. **다른 기기의 검증 범위.** 후보는 특정 기기·입력 조건에서 나왔다
   (`InputConditions`). 그 기기가 아닌 장치의 하드웨어 태그를 검증 범위로 적으면
   "다른 구성에서 측정한 성능을 자동으로 동일하다고 가정" 하는 것이고 AI-B-01 이
   그것을 금지한다.
6. **재지 않은 지연·메모리.** 파라미터 갱신은 정확도만 잰다. `latency_ms` 와
   `memory_mb` 는 **호출자가 실제로 쟀을 때만** 들어가고 그 밖에는 `None` 이다.
   그 결과 올라간 버전은 `fully_measured` 가 아니고, 기본 정책에서
   `REASON_UNMEASURED_NOT_ELIGIBLE` 로 **적격이 아니다**. 이것은 고장이 아니라
   요구사항이다 — 운영자가 `allow_unmeasured` 로 명시적으로 받아들이거나 지연을
   먼저 재야 한다. 0 으로 채워 적격으로 만들면 배정이 없는 이득을 보고 고른다.

미검증 범위를 숨기지 않는다
---------------------------
AI-L-06 은 승인 정보에 "검증된 적용 범위와 **미검증 범위**" 를 함께 요구한다.
해상도를 모르는 후보는 `verified_input_conditions` 가 비게 되는데, 그 빈 값은
`ModelAssigner` 에서 "조건 무관" 으로 읽힌다 — 즉 모르는 것이 **더 넓은 주장**이
된다. 그래서 그 사실을 `Promotion.unverified_scope` 로 따로 낸다. 자료형이
주장하지 못하는 것을 기록이 말한다.

소유 경계
---------
이 모듈은 **승인하지 않는다.** 계보를 전진시키는 것은 승인 주체(운영자)의 일이고
여기서는 상태를 읽어 `APPROVED` 가 아니면 등록하지 않는다. 물리 명령도 내리지
않고, 장치 가용성도 재판정하지 않는다(AI-C-19).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Mapping

from mission_runtime.continual.lineage import LearningLineage, LearningState
from mission_runtime.continual.parameter_evaluation import EvaluationReport, GateResult
from mission_runtime.continual.stream_learning import InputConditions, ParameterSet
from mission_runtime.runtime.airgap import AssetRef
from mission_runtime.runtime.model_assignment import ModelVersion
from mission_runtime.runtime.model_deployment import ModelDeploymentRequest

if TYPE_CHECKING:  # 순환 import 를 만들지 않는다 — 형만 쓴다
    from mission_runtime.runtime.model_assignment import DeviceProfile

#: 승격이 거절된 사유 토큰. `':'` 앞이 토큰, 뒤가 자료다(기존 규약).
REASON_PROMOTED = "promoted"
REASON_GATE_NOT_PASSED = "evaluation_gate_not_passed"
REASON_REPORT_MISMATCH = "report_belongs_to_another_candidate"
REASON_DEVICE_MISMATCH = "device_outside_candidate_conditions"
REASON_NOT_APPROVED = "learning_candidate_not_approved"
REASON_QUALITY_NOT_MEASURED = "new_accuracy_not_measured"
#: 성적표가 아예 없다. 검증을 돌리지 않은 것은 통과가 아니다(AI-L-05).
REASON_NOT_EVALUATED = "candidate_not_evaluated"
#: 그 계보가 이 후보를 근거로 든 적이 없다 — **다른 후보의 승인**이다.
REASON_LINEAGE_MISMATCH = "lineage_never_cited_this_candidate"

PROMOTION_REASONS: tuple[str, ...] = (
    REASON_PROMOTED,
    REASON_GATE_NOT_PASSED,
    REASON_REPORT_MISMATCH,
    REASON_DEVICE_MISMATCH,
    REASON_NOT_APPROVED,
    REASON_QUALITY_NOT_MEASURED,
    REASON_NOT_EVALUATED,
    REASON_LINEAGE_MISMATCH,
)

#: 입력 조건 토큰의 머리. `config/model_versions.example.json` 의 어휘와 같다.
CONDITION_RESOLUTION = "resolution"
#: 학습된 파라미터를 조달 자산으로 가리킬 때의 종류 이름.
ASSET_KIND_PARAMETERS = "parameters"
#: 미검증 범위의 축 이름. 사유 토큰과 같은 통제 어휘다.
SCOPE_RESOLUTION = "resolution_unknown"
SCOPE_HARDWARE = "hardware_tags_undeclared"
SCOPE_LATENCY = "latency_not_measured"
SCOPE_MEMORY = "memory_not_measured"


def condition_tokens(conditions: InputConditions) -> frozenset[str]:
    """후보의 입력 조건 중 **장치 선언 어휘로 말할 수 있는 것만** 토큰으로.

    모델 이름·프롬프트 모드는 후보의 정체이지 장치의 입력 조건이 아니다. 그것을
    조건 토큰으로 내면 어떤 장치도 그 토큰을 선언하지 않아 영원히 적격이 아니고,
    그 거절은 "범위 밖" 처럼 보이지만 실제로는 어휘가 어긋난 것이다. 묶음 키에는
    그대로 남아 있으므로(`InputConditions.extra`) 추적은 끊기지 않는다.
    """
    if conditions.resolution is None:
        return frozenset()
    width, height = conditions.resolution
    return frozenset({f"{CONDITION_RESOLUTION}.{int(width)}x{int(height)}"})


@dataclass(frozen=True)
class Promotion:
    """승격 시도의 결과. 올린 것과 못 올린 사유, 그리고 **미검증 범위**를 낸다."""

    candidate_version: str
    version: ModelVersion | None
    reason: str
    #: 이 버전이 주장하지 **못하는** 범위. AI-L-06 의 "미검증 범위" 가 이것이다.
    unverified_scope: tuple[str, ...] = ()
    #: 학습에 쓰인 표본과 기준 버전. 계보가 이어지는 자리다(AI-L-08).
    base_version: str | None = None
    sample_ids: tuple[str, ...] = ()
    produced_by: str = ""
    #: **이 버전을 허가한 그 계보.** 승격이 이 둘을 한 자료형에 묶는 이유가 이것이다 —
    #: 적용하는 쪽이 계보와 버전을 따로 받으면 계보 A 를 들고 버전 B 를 올릴 수 있고,
    #: 그러면 AI-L-08 의 역추적은 *있는데 거짓*이 된다. 없는 것보다 나쁘다.
    lineage: LearningLineage | None = None

    @property
    def promoted(self) -> bool:
        return self.version is not None

    @property
    def reference(self) -> str | None:
        return None if self.version is None else self.version.reference


def promote(
    candidate: ParameterSet,
    report: EvaluationReport | None,
    *,
    model_id: str,
    capability_kind: str,
    device: "DeviceProfile",
    lineage: LearningLineage | None = None,
    measured_latency_ms: float | None = None,
    measured_memory_mb: float | None = None,
) -> Promotion:
    """검증을 통과한 후보를 배정 후보(`ModelVersion`)로 바꾼다.

    `lineage` 를 주면 `APPROVED` 가 아닌 후보를 여기서 먼저 거절한다. 주지 않으면
    거절하지 않는다 — 그 관문의 주인은 `MlopsPipeline._lineage_refusal` 이고,
    두 곳에서 판정하면 사유가 둘로 갈린다. 여기서 보는 것은 "운영자가 아직 승인
    하지 않은 것을 목록에 등록하지 않는다" 는 더 좁은 일이다.

    `measured_latency_ms`·`measured_memory_mb` 는 **실제로 쟀을 때만** 넘긴다.
    기본값이 `None` 인 것은 편의가 아니라 규칙이다(AI-B-01).
    """
    unverified: list[str] = []

    if lineage is not None and lineage.state is not LearningState.APPROVED:
        return Promotion(candidate.version, None,
                         f"{REASON_NOT_APPROVED}:{lineage.state.value}")

    if lineage is not None and not lineage.cites(candidate.version):
        # **다른 후보의 승인.** 성적표가 짝이 맞지 않는 것(바로 아래)과 같은 실패이고
        # 결과가 더 나쁘다 — 승인은 사람의 행위라서, 어긋난 계보를 붙이면 운영자가
        # 보지도 않은 물건을 그 사람이 승인한 것으로 기록된다(AI-L-06).
        return Promotion(candidate.version, None,
                         f"{REASON_LINEAGE_MISMATCH}:{lineage.lineage_id}")

    if report is None:
        # 검증을 돌리지 않은 것은 통과가 아니다(AI-L-05). 성적표 없는 승격을
        # 허용하면 아래 게이트 판정이 선택 사항이 된다.
        return Promotion(candidate.version, None, REASON_NOT_EVALUATED)

    if report.candidate_version != candidate.version:
        # 성적표와 물건이 짝이 맞지 않으면 품질 수치가 다른 물건의 것이 된다.
        return Promotion(candidate.version, None,
                         f"{REASON_REPORT_MISMATCH}:{report.candidate_version}")

    if report.result is not GateResult.PASS:
        return Promotion(candidate.version, None,
                         f"{REASON_GATE_NOT_PASSED}:{report.result.value}")

    if device.device_id != candidate.conditions.device_id:
        # 후보가 나온 기기가 아닌 장치의 태그를 검증 범위로 적지 않는다(AI-B-01).
        return Promotion(candidate.version, None,
                         f"{REASON_DEVICE_MISMATCH}:{candidate.conditions.device_id}")

    quality = report.new.ratio
    if quality is None:
        # 게이트가 PASS 인데 비율이 없을 수는 없지만, 그 불변식을 조용히 믿고
        # 0 을 넣는 대신 사유로 돌려준다.
        return Promotion(candidate.version, None, REASON_QUALITY_NOT_MEASURED)

    conditions = condition_tokens(candidate.conditions)
    if not conditions:
        # 빈 집합은 `ModelAssigner` 에서 "조건 무관" 으로 읽힌다 — 모르는 것이 더
        # 넓은 주장이 되는 자리다. 자료형이 말하지 못하는 것을 기록이 말한다.
        unverified.append(SCOPE_RESOLUTION)
    if not device.hw_tags:
        unverified.append(SCOPE_HARDWARE)
    if measured_latency_ms is None:
        unverified.append(SCOPE_LATENCY)
    if measured_memory_mb is None:
        unverified.append(SCOPE_MEMORY)

    version = ModelVersion(
        model_id=model_id,
        version=candidate.version,          # 내용에서 파생된 버전을 그대로 쓴다
        capability_kind=capability_kind,
        verified_hw_tags=frozenset(device.hw_tags),
        verified_input_conditions=conditions,
        quality=quality,
        latency_ms=measured_latency_ms,
        memory_mb=measured_memory_mb,
    )
    return Promotion(
        candidate_version=candidate.version,
        version=version,
        reason=REASON_PROMOTED,
        unverified_scope=tuple(unverified),
        base_version=candidate.base_version,
        sample_ids=candidate.sample_ids,
        produced_by=candidate.produced_by,
        lineage=lineage,
    )


def parameter_asset(candidate: ParameterSet, *, model_id: str) -> AssetRef:
    """학습된 파라미터를 **내부 조달 자산** 1건으로 가리킨다(AI-C-16).

    위치를 여기서 정하지 않는다 — 논리 id 와 버전만 내고 실제 위치는
    `AssetResolver` 가 배치 자료로 해소한다. 폐쇄망에서 공개 위치로 풀리면 그쪽이
    거절한다.
    """
    return AssetRef(asset_id=f"{ASSET_KIND_PARAMETERS}:{model_id}",
                    kind=ASSET_KIND_PARAMETERS, version=candidate.version)


def deployment_request(
    promotion: Promotion,
    *,
    deployment_id: str,
    artifact_ref: str,
    target_node_id: str,
) -> ModelDeploymentRequest:
    """말단·노드로 파라미터를 내보내는 요청 1건.

    `checksum` 은 `ParameterSet.version` 이다 — 내용에서 파생된 sha256 이므로
    무결성 정보를 따로 만들 필요가 없고, 만들면 같은 내용에 두 개의 신원이 생긴다
    (AI-B-02: "버전과 식별 가능한 무결성 정보를 유지").
    """
    if promotion.version is None:
        raise ValueError(f"cannot deploy a refused promotion: {promotion.reason}")
    return ModelDeploymentRequest(
        deployment_id=deployment_id,
        model_id=promotion.version.model_id,
        model_version=promotion.version.version,
        artifact_ref=artifact_ref,
        checksum=promotion.candidate_version,
        target_node_id=target_node_id,
    )


@dataclass
class LearnedVersionRegistrar:
    """승인된 학습 후보를 배정 목록에 등록한다. **등록만 한다.**

    `MlopsPipeline` 을 감싸지 않고 `register_version` 만 부른다 — 배정·배치·단계적
    적용·되돌림은 전부 그쪽 경로의 일이고, 여기서 한 겹 더 감싸면 "지금 운영에 걸린
    버전" 을 두 곳에서 읽게 된다(AI-L-08).
    """

    #: `register_version(ModelVersion)` 을 가진 무엇이든. `MlopsPipeline` 도
    #: `ModelAssigner` 도 받는다 — 구체 자료형을 요구하지 않는 것이 요점이다.
    sink: object
    #: 등록된 버전별 승격 기록. 승인 정보(AI-L-06)와 역추적(AI-L-08)의 재료다.
    promotions: dict[str, Promotion] = field(default_factory=dict)

    def register(self, promotion: Promotion) -> Promotion:
        """승격된 버전을 배정 후보로 등록한다. 거절된 승격은 등록하지 않는다."""
        if promotion.version is None:
            return promotion
        register = getattr(self.sink, "register_version", None) or getattr(
            self.sink, "register", None)
        if register is None:
            raise TypeError("sink must expose register_version() or register()")
        register(promotion.version)
        self.promotions[promotion.version.reference] = promotion
        return promotion

    def promote_and_register(self, *args, **kwargs) -> Promotion:
        """`promote()` 와 같은 인자를 받아 통과한 것만 등록한다."""
        return self.register(promote(*args, **kwargs))

    def record_of(self, reference: str) -> Promotion | None:
        return self.promotions.get(reference)

    def unverified_scopes(self) -> Mapping[str, tuple[str, ...]]:
        """등록된 버전별 미검증 범위. 승인 화면이 읽는 그 항목이다(AI-L-06)."""
        return {ref: p.unverified_scope for ref, p in sorted(self.promotions.items())}
