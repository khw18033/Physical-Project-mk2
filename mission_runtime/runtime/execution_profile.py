"""실행 구성별 측정 프로파일의 장부 — 재측정 의무를 **조회 구조로** 만든다.

implements: AI-B-01 (실행 호환성·자원·검증 프로파일 관리)
관련: AI-B-09 (새 조합은 프로파일을 새로 만든다), AI-C-13 (실측 프로파일로 고른다),
      AI-L-05/06 (검증·미검증 범위), AI-L-10 (검증 범위를 벗어난 배정 금지),
      AI-O-05 (미측정은 0 도 미달도 아니다), AI-C-19 (판정 소유 경계)
tests: tests/test_execution_profile.py

무엇을 하고 무엇을 하지 않는가
------------------------------
이 모듈은 **측정값을 보관하고 조회한다.** 어느 모델을 어느 장치에 올릴지는
`runtime/model_assignment.py` 가 정하고, 어느 provider 를 쓸지는
`selection/selector.py` 가 정한다. 그 둘은 이미 미측정 후보를 거절하고
(`REASON_UNMEASURED_NOT_ELIGIBLE`) 검증 범위를 강제한다 — 여기서 같은 판정을 다시
하면 같은 질문에 두 개의 답이 생긴다. 이 모듈이 메우는 자리는 그 앞이다:
**그 판정이 소비하는 숫자가 어느 구성에서 나왔는지**를 들고 있는 것.

왜 장부가 지문으로 색인되는가
-----------------------------
AI-B-01: "다른 구성에서 측정한 성능·비용을 자동으로 동일하다고 가정해서는 안 되며
새 구성은 재측정·재검증해야 한다."

이 요구를 규율로 지키면("모델을 바꾸면 수치 칸을 비우세요") 언젠가 잊는다. 잊은
자리는 조용하다 — 숫자가 남아 있고, 그 숫자는 그럴듯하며, 틀렸다는 사실은 운영에서
드러난다. 그래서 여기서는 규율이 아니라 **조회 실패**로 만든다. 장부의 열쇠는
구성의 지문이고, 축 하나가 달라지면 열쇠가 달라지므로 옛 측정값은 새 구성의 조회에
**잡히지 않는다.** 숫자를 지우는 사람이 없어도 쓸 수 없다.

다만 "없다" 로만 끝내지 않는다. 비슷한 구성의 측정값이 장부에 있다면 그 사실과
**어느 축이 어긋났는지**를 함께 낸다(`AxisDivergence`). 재측정 의무가 왜 생겼는지
사람이 읽을 수 있어야 그 의무가 수행되기 때문이다 — "값이 없다" 는 운영자에게
고장처럼 보이고, "같은 모델의 256 입력 구성 값은 있는데 지금은 384 다" 는 할 일처럼
보인다.

구성과 독립인 지식은 같은 장부에 다르게 들어온다
-----------------------------------------------
AI-B-01 의 마지막 문장은 반대 방향이다 — "사람에게 확인된 의미 정보, 검증 데이터와
업무 요구처럼 구성과 독립적인 지식은 재사용할 수 있어야 한다." 모델을 바꾼 것이
"저 물체는 소화기다" 를 사람에게 다시 묻게 만들면 그 시스템은 사람의 시간을 모델
교체 비용으로 청구하는 것이다.

그래서 측정값 자체도 지식 1건으로 장부에 들어가되 `BINDING_CONFIGURATION` 이고,
사람 확인·검증 데이터셋·업무 요구는 `BINDING_INDEPENDENT` 다. `supersede()` 는 그
두 묶음을 가른 결과를 낸다 — 다시 재야 하는 것과 그대로 쓰는 것. 두 목록을 한
자리에서 내는 이유는, 구성이 바뀔 때 운영자가 실제로 묻는 것이 그 한 쌍이기 때문이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Mapping, Sequence

from mission_runtime.contracts.profile import (
    BINDING_CONFIGURATION,
    BINDING_INDEPENDENT,
    KNOWLEDGE_MEASUREMENT,
    MEASUREMENT_KINDS,
    MEASURE_FAILURE_RATE,
    MEASURE_LATENCY_MS,
    MEASURE_MEMORY_MB,
    MEASURE_QUALITY,
    MEASURE_THROUGHPUT_HZ,
    ExecutionConfiguration,
    KnowledgeRecord,
    ResourceCost,
    VerifiedExecutionProfile,
)

if TYPE_CHECKING:  # 순환 import 를 만들지 않는다 — 형만 쓴다
    from mission_runtime.runtime.model_assignment import ModelVersion

#: 적격·탈락 사유 토큰. `':'` 앞이 토큰, 뒤가 자료다(기존 규약 —
#: `runtime/learned_version.py`, `selection/selector.py` 와 같은 모양).
REASON_ELIGIBLE = "profile_eligible"
#: 이 구성의 측정값이 장부에 없다 = **재측정 의무**. 다른 구성 값이 있다는 사실은
#: `ProfileVerdict.measured_elsewhere` 가 따로 말한다.
REASON_NO_PROFILE_FOR_CONFIGURATION = "no_profile_for_this_configuration"
REASON_METRIC_NOT_MEASURED = "metric_not_measured"          # `:<metric>`
REASON_CHECK_NOT_RUN = "verification_check_not_run"         # `:<check>`
REASON_LATENCY_ABOVE_BUDGET = "latency_above_budget"
REASON_THROUGHPUT_BELOW_REQUIREMENT = "throughput_below_requirement"
REASON_MEMORY_ABOVE_CAPACITY = "memory_above_capacity"
REASON_QUALITY_BELOW_REQUIREMENT = "quality_below_requirement"
REASON_FAILURE_RATE_ABOVE_ALLOWANCE = "failure_rate_above_allowance"

PROFILE_REASONS: tuple[str, ...] = (
    REASON_ELIGIBLE,
    REASON_NO_PROFILE_FOR_CONFIGURATION,
    REASON_METRIC_NOT_MEASURED,
    REASON_CHECK_NOT_RUN,
    REASON_LATENCY_ABOVE_BUDGET,
    REASON_THROUGHPUT_BELOW_REQUIREMENT,
    REASON_MEMORY_ABOVE_CAPACITY,
    REASON_QUALITY_BELOW_REQUIREMENT,
    REASON_FAILURE_RATE_ABOVE_ALLOWANCE,
)

#: 측정 기록을 지식 1건으로 부를 때의 id 머리.
MEASUREMENT_KNOWLEDGE_PREFIX = "measurement"


@dataclass(frozen=True)
class AxisDivergence:
    """장부에 있는 다른 구성 1건과, 그것이 **어느 축에서** 어긋나는가.

    이 자료형이 있는 이유는 위 머리말의 "할 일처럼 보이게" 다. 어긋난 축의 이름이
    곧 재측정 범위이고, 축이 하나면 그 축만 바꿔 다시 재면 된다.
    """

    fingerprint: str
    axes: tuple[str, ...]


@dataclass(frozen=True)
class ProfileRequirement:
    """어떤 구성에서, 어떤 조건으로 쓰려는가. 조건을 선언하면 **측정 의무가 생긴다**.

    implements: AI-B-01

    선언된 한계마다 그 항목의 측정값을 요구한다 — `max_latency_ms` 를 적었는데
    지연을 재지 않은 프로파일은 `metric_not_measured:latency_ms` 로 탈락이고 통과가
    아니다. "재지 않았으니 넘겼다" 가 되는 순간 한계값은 장식이 된다.

    `required_measurements` 는 한계 없이도 값이 있어야 하는 항목이다(예: 배치
    전에 메모리를 알아야 하지만 상한은 장치가 정한다). `required_checks` 는 돌렸어야
    하는 검증 항목이고, 돌리지 않은 것은 통과로 세지 않는다.

    `allow_unmeasured` 는 운영자가 **명시적으로** 미측정을 받아들이는 경로다
    (`runtime/model_assignment.py::MissionRequirement.allow_unmeasured` 와 같은
    기본값·같은 뜻). 기본이 False 인 것이 규칙이고, True 는 사람이 적은 예외다.
    """

    configuration: ExecutionConfiguration
    max_latency_ms: float | None = None
    min_throughput_hz: float | None = None
    max_memory_mb: float | None = None
    min_quality: float | None = None
    max_failure_rate: float | None = None
    required_measurements: tuple[str, ...] = ()
    required_checks: tuple[str, ...] = ()
    allow_unmeasured: bool = False
    #: 누가 왜 이 조건을 요구하는가(임무·업무 id). 사유 추적용 자유 문자열.
    requested_by: str = ""

    def measurements_needed(self) -> tuple[str, ...]:
        """이 조건을 판정하기 위해 **반드시 재어져 있어야** 하는 항목."""
        needed: list[str] = []
        for limit, metric in (
            (self.max_latency_ms, MEASURE_LATENCY_MS),
            (self.min_throughput_hz, MEASURE_THROUGHPUT_HZ),
            (self.max_memory_mb, MEASURE_MEMORY_MB),
            (self.min_quality, MEASURE_QUALITY),
            (self.max_failure_rate, MEASURE_FAILURE_RATE),
        ):
            if limit is not None and metric not in needed:
                needed.append(metric)
        for metric in self.required_measurements:
            if metric not in needed:
                needed.append(metric)
        return tuple(needed)


@dataclass(frozen=True)
class ProfileVerdict:
    """판정 결과. 적격이면 프로파일을, 아니면 사유를 낸다.

    `unmeasured` 와 `not_validated` 는 적격일 때도 비어 있지 않을 수 있다 — 조건이
    요구하지 않은 항목을 재지 않은 것은 정상이지만, **무엇을 모르는 채 통과했는지**
    는 남아야 한다(AI-L-06 의 "미검증 범위").
    """

    configuration_fingerprint: str
    profile: VerifiedExecutionProfile | None
    reason: str
    unmeasured: tuple[str, ...] = ()
    not_validated: tuple[str, ...] = ()
    #: 같은 capability 의 **다른 구성**에 측정값이 있다는 사실과 어긋난 축.
    measured_elsewhere: tuple[AxisDivergence, ...] = ()

    @property
    def is_eligible(self) -> bool:
        return self.profile is not None and self.reason == REASON_ELIGIBLE


@dataclass(frozen=True)
class Supersession:
    """구성이 바뀌었다 — 다시 재야 하는 것과 그대로 쓰는 것.

    implements: AI-B-01

    `must_remeasure` 는 **옛 구성에서 재어 두었던 항목**이다. 비어 있지 않다는 것은
    "그 숫자들이 있었고, 지금은 쓸 수 없다" 는 뜻이고, 그것이 재측정 범위다.
    `reusable_knowledge` 는 구성과 무관한 지식 — 사람 확인·검증 데이터·업무 요구 —
    이고 구성이 바뀌어도 그대로 쓴다(AI-B-01 마지막 문장).

    이 객체는 **아무것도 옮겨 적지 않는다.** 숫자를 새 구성으로 복사하는 메서드를
    두지 않은 것이 이 모듈의 요점이다.
    """

    previous_fingerprint: str
    fingerprint: str
    changed_axes: tuple[str, ...]
    must_remeasure: tuple[str, ...] = ()
    reusable_knowledge: tuple[str, ...] = ()
    invalidated_knowledge: tuple[str, ...] = ()

    @property
    def is_same_configuration(self) -> bool:
        return not self.changed_axes


@dataclass
class ExecutionProfileLedger:
    """구성 지문으로 색인된 측정 프로파일 장부 + 지식 기록.

    implements: AI-B-01

    `profiles` 의 열쇠가 지문이라는 사실 하나가 재측정 의무의 전부다. 구성 축이
    바뀌면 다른 열쇠가 되고, 옛 값은 조회에 잡히지 않는다 — 지우는 사람이 없어도.
    """

    profiles: dict[str, VerifiedExecutionProfile] = field(default_factory=dict)
    knowledge: dict[str, KnowledgeRecord] = field(default_factory=dict)

    # -- 기록 ---------------------------------------------------------------

    def record(self, profile: VerifiedExecutionProfile) -> VerifiedExecutionProfile:
        """프로파일 1건을 그 구성의 지문 아래 넣는다.

        같은 지문의 기존 기록은 대체된다 — 같은 구성을 다시 잰 것이므로 그것이
        맞다. 다른 구성은 다른 열쇠라 덮이지 않는다.

        측정 기록 자체도 **구성 결속 지식** 1건으로 함께 남긴다. 구성이 바뀔 때
        무엇이 무효가 되는지를 묻는 자리(`supersede`)가 한 곳이어야 하기 때문이다.
        """
        self.profiles[profile.fingerprint] = profile
        knowledge_id = f"{MEASUREMENT_KNOWLEDGE_PREFIX}:{profile.fingerprint}"
        self.knowledge[knowledge_id] = KnowledgeRecord(
            knowledge_id=knowledge_id,
            kind=KNOWLEDGE_MEASUREMENT,
            binding=BINDING_CONFIGURATION,
            subject=profile.configuration.capability_kind,
            content_ref=",".join(profile.measurements.measured()),
            recorded_at=profile.measurements.measured_at,
            configuration_fingerprint=profile.fingerprint,
        )
        return profile

    def record_knowledge(self, record: KnowledgeRecord) -> KnowledgeRecord:
        """지식 1건. 구성 독립 선언은 `KnowledgeRecord` 가 생성 시 검사한다."""
        self.knowledge[record.knowledge_id] = record
        return record

    # -- 조회 ---------------------------------------------------------------

    def profile_for(
        self, configuration: ExecutionConfiguration
    ) -> VerifiedExecutionProfile | None:
        """그 구성의 프로파일, 또는 `None`. **비슷한 구성으로 대체하지 않는다.**"""
        return self.profiles.get(configuration.fingerprint)

    def resource_cost(self, configuration: ExecutionConfiguration) -> ResourceCost | None:
        """그 구성의 실측 자원 비용, 또는 `None`(미측정이거나 프로파일이 없음).

        선택기가 예산 심사에 쓰는 값이다. `None` 을 0 으로 바꾸는 호출자가 있으면
        그 호출자가 AI-B-01 을 깨는 것이고, 이 함수는 그 변환을 하지 않는다.
        """
        profile = self.profile_for(configuration)
        return None if profile is None else profile.to_resource_cost()

    def divergences(
        self, configuration: ExecutionConfiguration
    ) -> tuple[AxisDivergence, ...]:
        """같은 capability 의 다른 구성 측정값과, 어긋난 축.

        어긋난 축이 적은 것부터 낸다 — 가장 가까운 구성이 재측정의 출발점이다.
        """
        found = [
            AxisDivergence(
                fingerprint=fingerprint,
                axes=configuration.differing_axes(profile.configuration),
            )
            for fingerprint, profile in sorted(self.profiles.items())
            if profile.configuration.capability_kind == configuration.capability_kind
            and fingerprint != configuration.fingerprint
        ]
        return tuple(sorted(found, key=lambda d: (len(d.axes), d.fingerprint)))

    def evaluate(self, requirement: ProfileRequirement) -> ProfileVerdict:
        """그 구성의 측정값으로 이 조건을 만족하는가.

        순서가 뜻을 가진다. 프로파일 유무 → 돌리지 않은 검증 → 재지 않은 항목 →
        수치 비교. 재지 않은 항목을 수치 비교보다 먼저 보는 이유는, 비교 자체가
        불가능한 상태와 비교해서 미달인 상태가 **다른 사실**이기 때문이다
        (AI-O-05: 미측정 ≠ 미달).
        """
        configuration = requirement.configuration
        fingerprint = configuration.fingerprint
        profile = self.profiles.get(fingerprint)
        if profile is None:
            return ProfileVerdict(
                configuration_fingerprint=fingerprint,
                profile=None,
                reason=REASON_NO_PROFILE_FOR_CONFIGURATION,
                unmeasured=requirement.measurements_needed(),
                not_validated=tuple(requirement.required_checks),
                measured_elsewhere=self.divergences(configuration),
            )

        not_validated = profile.not_validated(requirement.required_checks)
        needed = requirement.measurements_needed()
        unmeasured = profile.measurements.unmeasured(needed)

        def verdict(reason: str) -> ProfileVerdict:
            return ProfileVerdict(
                configuration_fingerprint=fingerprint,
                profile=profile if reason == REASON_ELIGIBLE else None,
                reason=reason,
                unmeasured=unmeasured,
                not_validated=not_validated,
            )

        if not_validated:
            # 돌리지 않은 검증은 통과가 아니다.
            return verdict(f"{REASON_CHECK_NOT_RUN}:{not_validated[0]}")
        if unmeasured and not requirement.allow_unmeasured:
            return verdict(f"{REASON_METRIC_NOT_MEASURED}:{unmeasured[0]}")

        checks: tuple[tuple[float | None, str, bool, str], ...] = (
            (requirement.max_latency_ms, MEASURE_LATENCY_MS, True, REASON_LATENCY_ABOVE_BUDGET),
            (requirement.max_memory_mb, MEASURE_MEMORY_MB, True, REASON_MEMORY_ABOVE_CAPACITY),
            (requirement.max_failure_rate, MEASURE_FAILURE_RATE, True,
             REASON_FAILURE_RATE_ABOVE_ALLOWANCE),
            (requirement.min_throughput_hz, MEASURE_THROUGHPUT_HZ, False,
             REASON_THROUGHPUT_BELOW_REQUIREMENT),
            (requirement.min_quality, MEASURE_QUALITY, False, REASON_QUALITY_BELOW_REQUIREMENT),
        )
        for limit, metric, is_upper_bound, reason in checks:
            if limit is None:
                continue
            measured = profile.value(metric)
            if measured is None:
                # `allow_unmeasured` 로 통과한 경로. 미측정을 0 으로 읽어 비교하지
                # 않는다 — 비교하지 않고 넘긴다는 것이 그 허용의 내용이다.
                continue
            if is_upper_bound and measured > limit:
                return verdict(reason)
            if not is_upper_bound and measured < limit:
                return verdict(reason)

        return verdict(REASON_ELIGIBLE)

    # -- 구성 변경 -----------------------------------------------------------

    def supersede(
        self,
        previous: ExecutionConfiguration,
        current: ExecutionConfiguration,
        *,
        subject: str | None = None,
    ) -> Supersession:
        """구성이 `previous` → `current` 로 바뀌었다. 무엇을 다시 재고 무엇을 쓰는가.

        장부를 **고치지 않는다.** 옛 프로파일은 옛 지문 아래 그대로 남고, 새 구성의
        조회는 여전히 비어 있다 — 비워 두는 것이 재측정 의무의 표현이다. 옛 기록을
        지우면 "그 구성에서는 이랬다" 는 비교 근거까지 사라진다(AI-L-05 의 기존 버전
        대비 비교).

        `subject` 를 주면 재사용 가능 지식을 그 대상으로 좁힌다.
        """
        old = self.profiles.get(previous.fingerprint)
        reusable: list[str] = []
        invalidated: list[str] = []
        for record in sorted(self.knowledge.values(), key=lambda r: r.knowledge_id):
            if subject is not None and record.subject != subject:
                continue
            if record.reusable_across_configurations:
                reusable.append(record.knowledge_id)
            elif record.configuration_fingerprint == previous.fingerprint:
                invalidated.append(record.knowledge_id)
        return Supersession(
            previous_fingerprint=previous.fingerprint,
            fingerprint=current.fingerprint,
            changed_axes=previous.differing_axes(current),
            must_remeasure=() if old is None else old.measurements.measured(),
            reusable_knowledge=tuple(reusable),
            invalidated_knowledge=tuple(invalidated),
        )

    def reusable_knowledge(self, *, subject: str | None = None) -> tuple[KnowledgeRecord, ...]:
        """구성이 바뀌어도 그대로 쓰는 지식(AI-B-01 마지막 문장)."""
        return tuple(
            record
            for record in sorted(self.knowledge.values(), key=lambda r: r.knowledge_id)
            if record.binding == BINDING_INDEPENDENT
            and (subject is None or record.subject == subject)
        )

    def configuration_bound_knowledge(
        self, configuration: ExecutionConfiguration
    ) -> tuple[KnowledgeRecord, ...]:
        """그 구성에만 해당하는 지식. 구성이 바뀌면 함께 무효가 되는 묶음이다."""
        return tuple(
            record
            for record in sorted(self.knowledge.values(), key=lambda r: r.knowledge_id)
            if record.configuration_fingerprint == configuration.fingerprint
        )

    def unmeasured_report(
        self, *, among: Sequence[str] | None = None
    ) -> Mapping[str, tuple[str, ...]]:
        """구성별 미측정 항목. 승인·운영 화면이 읽는 "무엇을 모르는가" 다(AI-L-06).

        비어 있지 않은 것이 **정상**일 수 있다 — 모든 항목을 재는 배치는 없다. 요점은
        모르는 것이 0 으로 보이지 않는 것이다.
        """
        names = tuple(among) if among is not None else MEASUREMENT_KINDS
        return {
            fingerprint: profile.measurements.unmeasured(names)
            for fingerprint, profile in sorted(self.profiles.items())
        }


# ── 기존 판정이 소비하는 자료형으로 ───────────────────────────────────────────


def model_version_from(
    profile: VerifiedExecutionProfile, *, model_id: str, version: str
) -> "ModelVersion":
    """측정 프로파일 1건을 배정 후보(`ModelVersion`)로 옮긴다.

    implements: AI-B-01
    관련: AI-L-10 (배정), AI-B-09 (새 조합은 새 프로파일)

    **판정은 여기서 하지 않는다.** 미측정 후보를 적격으로 보지 않는 규칙은 이미
    `runtime/model_assignment.py` 가 소유하고(`REASON_UNMEASURED_NOT_ELIGIBLE`),
    검증 범위 강제도 그쪽이 한다. 이 함수가 하는 일은 그 판정이 **올바른 숫자를
    보게** 하는 것이다 — 재지 않은 항목은 `None` 으로 남고 0 으로 바뀌지 않으며,
    검증 범위는 그 구성이 실제로 돌았던 하드웨어 태그와 입력 조건이 된다.

    입력 조건 토큰의 어휘는 `config/model_versions.example.json` 의 그것과 같다
    (`resolution.<W>x<H>`) — 어휘가 갈리면 어떤 장치도 그 토큰을 선언하지 않아
    영원히 적격이 아니게 되고, 그 거절은 "범위 밖" 처럼 보이지만 실제로는 이름이
    어긋난 것이다(`runtime/learned_version.py::condition_tokens` 와 같은 함정).
    """
    from mission_runtime.runtime.model_assignment import ModelVersion

    configuration = profile.configuration
    conditions = (
        frozenset({configuration.input_profile}) if configuration.input_profile else frozenset()
    )
    return ModelVersion(
        model_id=model_id,
        version=version,
        capability_kind=configuration.capability_kind,
        verified_hw_tags=frozenset(configuration.hardware_tags),
        verified_input_conditions=conditions,
        quality=profile.value(MEASURE_QUALITY),
        latency_ms=profile.value(MEASURE_LATENCY_MS),
        memory_mb=profile.value(MEASURE_MEMORY_MB),
    )
