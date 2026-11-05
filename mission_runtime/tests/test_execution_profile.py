"""implements: AI-B-01 (실행 호환성·자원·검증 프로파일 관리)
관련: AI-B-09, AI-L-05/06/10, AI-O-05
tests: 구성 신원 · 미측정 구분 · 재측정 의무 · 구성 독립 지식 재사용,
       그리고 **실제 모델 둘로 실제로 잰 값**으로 같은 규칙을 한 번 더 고정한다.

이 시험이 지키려는 한 문장: **미측정 ≠ 0 ≠ 미달.** 그리고 그 짝 —
다른 구성에서 잰 값은 이 구성의 조건을 만족할 수 없다.

아래 D절은 합성 수치가 아니다. `<자산뿌리>/models/zipdepth/` 의 실제 가중치 둘을
실제 추론 런타임으로 돌려 재고, 그 측정값으로 "256 구성의 프로파일이 384 구성의
요구를 만족하지 못한다" 를 확인한다. 자산이나 런타임이 없는 기계에서는 그 묶음만
skip 한다(AI-C-05: 선택 구성요소 결손은 축소이지 실패가 아니다).
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
import statistics
import time

import pytest

from conftest import asset_path, asset_root_present
from mission_runtime.contracts.profile import (
    BINDING_CONFIGURATION,
    BINDING_INDEPENDENT,
    KNOWLEDGE_BUSINESS_REQUIREMENT,
    KNOWLEDGE_HUMAN_CONFIRMED,
    KNOWLEDGE_MEASUREMENT,
    KNOWLEDGE_VALIDATION_DATASET,
    MEASUREMENT_KINDS,
    MEASURE_COMPUTE_UNITS,
    MEASURE_FAILURE_RATE,
    MEASURE_LATENCY_MS,
    MEASURE_MEMORY_MB,
    MEASURE_QUALITY,
    MEASURE_THROUGHPUT_HZ,
    ExecutionConfiguration,
    KnowledgeRecord,
    MeasurementSet,
    VerifiedExecutionProfile,
)
from mission_runtime.runtime.execution_profile import (
    REASON_CHECK_NOT_RUN,
    REASON_ELIGIBLE,
    REASON_LATENCY_ABOVE_BUDGET,
    REASON_METRIC_NOT_MEASURED,
    REASON_NO_PROFILE_FOR_CONFIGURATION,
    REASON_QUALITY_BELOW_REQUIREMENT,
    REASON_THROUGHPUT_BELOW_REQUIREMENT,
    ExecutionProfileLedger,
    ProfileRequirement,
    Supersession,
)

KIND = "perception.depth"


def config(**overrides) -> ExecutionConfiguration:
    base = dict(
        capability_kind=KIND,
        implementation_ref="depth-model@a",
        runtime_ref="runtime@1",
        input_profile="resolution.256x256",
        hardware_tags=("compute.cpu", "tier.edge"),
    )
    base.update(overrides)
    return ExecutionConfiguration(**base)


def profile(configuration: ExecutionConfiguration, values: dict, **kwargs) -> VerifiedExecutionProfile:
    return VerifiedExecutionProfile(
        configuration=configuration,
        measurements=configuration.measure(values),
        **kwargs,
    )


# ── A. 실행 구성의 신원 ────────────────────────────────────────────────────────


def test_every_axis_changes_the_fingerprint():
    """AI-B-01: 모델·런타임·하드웨어·입력·전후처리·보정의 **조합**이 구성이다.

    한 축이라도 바뀌면 다른 구성이고, 그 사실은 지문 하나로 드러나야 한다.
    """
    base = config()
    changed = {
        "implementation_ref": "depth-model@b",
        "runtime_ref": "runtime@2",
        "input_profile": "resolution.384x384",
        "hardware_tags": ("compute.gpu",),
        "preprocess_ref": "letterbox",
        "postprocess_ref": "median-filter",
        "calibration_ref": "cam-1-v3",
    }
    for axis, value in changed.items():
        other = dataclasses.replace(base, **{axis: value})
        assert other.fingerprint != base.fingerprint, axis
        assert base.differing_axes(other) == (axis,)


def test_hardware_tag_order_is_not_a_different_configuration():
    """태그를 적은 순서가 다른 구성이 되면 같은 기계가 두 개의 신원을 갖는다."""
    a = config(hardware_tags=("compute.cpu", "tier.edge"))
    b = config(hardware_tags=("tier.edge", "compute.cpu"))
    assert a.fingerprint == b.fingerprint
    assert a.differing_axes(b) == ()


def test_a_new_deployment_axis_also_creates_a_remeasurement_duty():
    """배치가 축을 더하면 그것도 지문에 들어간다 — 모르는 축이 조용히 섞이지 않는다."""
    base = config()
    with_axis = config(extra_axes=(("thermal_state", "throttled"),))
    assert with_axis.fingerprint != base.fingerprint
    assert base.differing_axes(with_axis) == ("thermal_state",)
    # 벤더 열거형이 아니라 자유 문자열이라 새 축이 코드 변경을 요구하지 않는다.
    assert dict(with_axis.axes())["thermal_state"] == "throttled"


# ── B. 미측정은 0 도 미달도 아니다 ────────────────────────────────────────────


def test_unmeasured_items_simply_have_no_key():
    """AI-B-01: "미측정 항목은 구분해야 한다". 부재로 구분한다 — 0 이 아니다."""
    measured = config().measure({MEASURE_LATENCY_MS: 106.6})
    assert measured.has(MEASURE_LATENCY_MS)
    assert not measured.has(MEASURE_QUALITY)
    assert measured.value(MEASURE_QUALITY) is None
    assert measured.measured() == (MEASURE_LATENCY_MS,)
    assert MEASURE_QUALITY in measured.unmeasured()
    # AI-B-01 이 열거한 항목 전부가 어휘에 있다.
    for metric in (MEASURE_LATENCY_MS, MEASURE_THROUGHPUT_HZ, MEASURE_MEMORY_MB,
                   MEASURE_COMPUTE_UNITS, MEASURE_QUALITY, MEASURE_FAILURE_RATE):
        assert metric in MEASUREMENT_KINDS


def test_none_and_nan_are_refused_as_measurements():
    """`{"quality": None}` 을 허용하면 "키는 있는데 값이 없다" 는 세 번째 상태가 생긴다."""
    configuration = config()
    with pytest.raises(ValueError, match="None"):
        configuration.measure({MEASURE_QUALITY: None})
    with pytest.raises(ValueError, match="finite"):
        configuration.measure({MEASURE_LATENCY_MS: float("nan")})
    with pytest.raises(ValueError, match="finite"):
        configuration.measure({MEASURE_LATENCY_MS: float("inf")})


def test_measurements_cannot_exist_without_a_configuration():
    """측정값이 구성과 떨어져 떠다니면 어느 구성의 것인지 묻는 자리가 사라진다."""
    with pytest.raises(ValueError, match="configuration"):
        MeasurementSet(configuration_fingerprint="", values={MEASURE_LATENCY_MS: 1.0})


def test_unmeasured_resource_cost_is_absent_not_cheap():
    """0 으로 채운 비용은 예산 심사를 **언제나** 통과한다 — 가장 싼 후보가 된다."""
    partial = profile(config(), {MEASURE_LATENCY_MS: 106.6, MEASURE_MEMORY_MB: 43.1})
    assert partial.to_resource_cost() is None  # compute_units 미측정

    full = profile(config(), {MEASURE_LATENCY_MS: 106.6, MEASURE_MEMORY_MB: 43.1,
                              MEASURE_COMPUTE_UNITS: 1.0})
    cost = full.to_resource_cost()
    assert cost is not None and cost.memory_mb == 43.1 and cost.max_latency_ms == 106.6


def test_a_check_that_was_not_run_is_not_a_pass():
    """AI-B-01 의 "검증": 돌린 항목만 적고, 돌리지 않은 것은 여집합으로 드러난다."""
    verified = profile(config(), {MEASURE_LATENCY_MS: 106.6}, validated_by=("latency",))
    assert verified.not_validated(("latency", "memory", "failure_mode")) == ("memory", "failure_mode")

    ledger = ExecutionProfileLedger()
    ledger.record(verified)
    verdict = ledger.evaluate(ProfileRequirement(
        config(), max_latency_ms=200.0, required_checks=("latency", "failure_mode")))
    assert not verdict.is_eligible
    assert verdict.reason == f"{REASON_CHECK_NOT_RUN}:failure_mode"
    assert verdict.not_validated == ("failure_mode",)


def test_declaring_a_limit_creates_a_measurement_duty():
    """한계를 적었는데 그 항목을 재지 않으면 통과가 아니라 **미측정 탈락**이다."""
    ledger = ExecutionProfileLedger()
    ledger.record(profile(config(), {MEASURE_LATENCY_MS: 106.6}))

    needed = ProfileRequirement(config(), max_latency_ms=200.0, min_quality=0.6)
    assert needed.measurements_needed() == (MEASURE_LATENCY_MS, MEASURE_QUALITY)

    verdict = ledger.evaluate(needed)
    assert verdict.reason == f"{REASON_METRIC_NOT_MEASURED}:{MEASURE_QUALITY}"
    assert verdict.unmeasured == (MEASURE_QUALITY,)
    # 미측정과 미달은 다른 사실이다 — 수치가 있고 모자랄 때만 미달이라고 말한다.
    ledger.record(profile(config(), {MEASURE_LATENCY_MS: 106.6, MEASURE_QUALITY: 0.4}))
    assert ledger.evaluate(needed).reason == REASON_QUALITY_BELOW_REQUIREMENT


def test_allow_unmeasured_skips_the_comparison_instead_of_reading_zero():
    """명시적 허용은 "비교하지 않는다" 이지 "0 으로 비교한다" 가 아니다."""
    ledger = ExecutionProfileLedger()
    ledger.record(profile(config(), {MEASURE_LATENCY_MS: 106.6}))
    allowed = ProfileRequirement(config(), min_throughput_hz=30.0, allow_unmeasured=True)
    verdict = ledger.evaluate(allowed)
    assert verdict.is_eligible
    # 통과했어도 **무엇을 모르는 채 통과했는지**는 남는다(AI-L-06 미검증 범위).
    assert verdict.unmeasured == (MEASURE_THROUGHPUT_HZ,)

    measured_but_short = profile(
        config(), {MEASURE_LATENCY_MS: 106.6, MEASURE_THROUGHPUT_HZ: 9.4})
    ledger.record(measured_but_short)
    assert ledger.evaluate(allowed).reason == REASON_THROUGHPUT_BELOW_REQUIREMENT


def test_unmeasured_report_lists_what_each_configuration_does_not_know():
    ledger = ExecutionProfileLedger()
    ledger.record(profile(config(), {MEASURE_LATENCY_MS: 106.6}))
    report = ledger.unmeasured_report(among=(MEASURE_LATENCY_MS, MEASURE_QUALITY))
    assert report == {config().fingerprint: (MEASURE_QUALITY,)}


# ── C. 재측정 의무는 구조다 ───────────────────────────────────────────────────


def test_measurements_cannot_be_rebound_to_another_configuration():
    """구성이 바뀐 뒤 옛 숫자를 새 구성에 **옮겨 담을 길이 자료형에 없다.**

    이것이 "검토자가 기억해서가 아니라 구조로" 의 실제 내용이다. `replace()` 도
    같은 검사를 다시 거친다.
    """
    old = config()
    new = config(input_profile="resolution.384x384")
    measured = old.measure({MEASURE_LATENCY_MS: 106.6})

    with pytest.raises(ValueError, match="another execution configuration"):
        VerifiedExecutionProfile(configuration=new, measurements=measured)

    recorded = VerifiedExecutionProfile(configuration=old, measurements=measured)
    with pytest.raises(ValueError, match="another execution configuration"):
        dataclasses.replace(recorded, configuration=new)


def test_a_profile_covers_only_its_own_configuration():
    """'비슷한 구성' 이라는 상태를 두지 않는다 — 비슷함의 판정이 암묵지다."""
    old = config()
    recorded = profile(old, {MEASURE_LATENCY_MS: 106.6})
    assert recorded.covers(old)
    assert not recorded.covers(config(runtime_ref="runtime@2"))
    assert not recorded.covers(config(hardware_tags=("compute.gpu",)))


def test_a_changed_configuration_makes_the_old_numbers_unfindable():
    """장부의 열쇠가 지문이라 옛 값은 새 구성의 조회에 **잡히지 않는다**.

    그리고 "없다" 로 끝내지 않는다 — 어느 축이 어긋났는지를 함께 내어 재측정 의무가
    고장이 아니라 할 일로 보이게 한다.
    """
    old = config()
    new = config(implementation_ref="depth-model@b", input_profile="resolution.384x384")
    ledger = ExecutionProfileLedger()
    ledger.record(profile(old, {MEASURE_LATENCY_MS: 106.6, MEASURE_MEMORY_MB: 43.1}))

    assert ledger.profile_for(new) is None
    assert ledger.resource_cost(new) is None

    verdict = ledger.evaluate(ProfileRequirement(new, max_latency_ms=200.0))
    assert verdict.reason == REASON_NO_PROFILE_FOR_CONFIGURATION
    assert verdict.profile is None
    assert [d.fingerprint for d in verdict.measured_elsewhere] == [old.fingerprint]
    assert verdict.measured_elsewhere[0].axes == ("implementation_ref", "input_profile")


def test_divergences_are_ordered_by_how_far_away_they_are():
    """가장 가까운 구성이 재측정의 출발점이다."""
    target = config(input_profile="resolution.384x384")
    near = config(input_profile="resolution.512x512")                   # 1 축
    far = config(runtime_ref="runtime@9", hardware_tags=("compute.gpu",))  # 3 축
    ledger = ExecutionProfileLedger()
    ledger.record(profile(far, {MEASURE_LATENCY_MS: 10.0}))
    ledger.record(profile(near, {MEASURE_LATENCY_MS: 20.0}))

    found = ledger.divergences(target)
    assert [len(d.axes) for d in found] == [1, 3]
    assert found[0].fingerprint == near.fingerprint


def test_other_capability_kinds_are_not_offered_as_divergences():
    """다른 기능의 측정값은 이 기능의 재측정 출발점이 아니다."""
    ledger = ExecutionProfileLedger()
    ledger.record(profile(config(capability_kind="perception.classify"), {MEASURE_LATENCY_MS: 5.0}))
    assert ledger.divergences(config()) == ()


def test_superseding_keeps_the_old_record_for_comparison():
    """옛 기록을 지우지 않는다 — 지우면 기존 버전 대비 비교 근거까지 사라진다(AI-L-05)."""
    old = config()
    new = config(input_profile="resolution.384x384")
    ledger = ExecutionProfileLedger()
    ledger.record(profile(old, {MEASURE_LATENCY_MS: 106.6, MEASURE_MEMORY_MB: 43.1}))

    moved = ledger.supersede(old, new)
    assert moved.changed_axes == ("input_profile",)
    assert moved.must_remeasure == (MEASURE_LATENCY_MS, MEASURE_MEMORY_MB)
    assert not moved.is_same_configuration
    # 옛 구성은 그대로 조회되고, 새 구성은 여전히 비어 있다.
    assert ledger.profile_for(old) is not None
    assert ledger.profile_for(new) is None
    # 숫자를 옮기는 메서드가 없다.
    assert not any(name.startswith(("copy", "carry", "inherit")) for name in dir(Supersession))


def test_same_configuration_supersession_demands_nothing():
    same = ledger_with_one()
    moved = same[0].supersede(same[1], same[1])
    assert moved.is_same_configuration
    assert moved.changed_axes == ()


def ledger_with_one():
    configuration = config()
    ledger = ExecutionProfileLedger()
    ledger.record(profile(configuration, {MEASURE_LATENCY_MS: 106.6}))
    return ledger, configuration


# ── D. 구성과 독립인 지식은 재사용된다 ────────────────────────────────────────


def test_human_confirmation_survives_a_model_change():
    """AI-B-01 마지막 문장. 모델을 바꾼 것이 "저것은 소화기다" 를 다시 묻게 하면
    사람의 시간이 모델 교체 비용으로 청구된다.
    """
    old = config()
    new = config(implementation_ref="depth-model@b")
    ledger = ExecutionProfileLedger()
    ledger.record(profile(old, {MEASURE_LATENCY_MS: 106.6}))
    for knowledge_id, kind in (("entity-7.label", KNOWLEDGE_HUMAN_CONFIRMED),
                               ("heldout-2026-09", KNOWLEDGE_VALIDATION_DATASET),
                               ("mission.approach.min_quality", KNOWLEDGE_BUSINESS_REQUIREMENT)):
        ledger.record_knowledge(KnowledgeRecord(
            knowledge_id=knowledge_id, kind=kind, binding=BINDING_INDEPENDENT,
            subject=KIND, confirmed_by="operator-1"))

    moved = ledger.supersede(old, new, subject=KIND)
    assert moved.reusable_knowledge == (
        "entity-7.label", "heldout-2026-09", "mission.approach.min_quality")
    assert moved.invalidated_knowledge == (f"measurement:{old.fingerprint}",)
    assert [r.kind for r in ledger.reusable_knowledge(subject=KIND)] == [
        KNOWLEDGE_HUMAN_CONFIRMED, KNOWLEDGE_VALIDATION_DATASET, KNOWLEDGE_BUSINESS_REQUIREMENT]


def test_measurements_are_themselves_configuration_bound_knowledge():
    """측정 기록도 지식 1건이다 — 무엇이 무효가 되는지를 묻는 자리가 한 곳이어야 한다."""
    configuration = config()
    ledger = ExecutionProfileLedger()
    ledger.record(profile(configuration, {MEASURE_LATENCY_MS: 106.6}))
    bound = ledger.configuration_bound_knowledge(configuration)
    assert [r.kind for r in bound] == [KNOWLEDGE_MEASUREMENT]
    assert bound[0].binding == BINDING_CONFIGURATION
    assert not bound[0].reusable_across_configurations
    assert ledger.reusable_knowledge() == ()


def test_binding_declaration_cannot_contradict_itself():
    """구성에 묶이지 않는다고 선언하면서 구성을 들고 있으면 읽는 쪽이 고르게 된다."""
    with pytest.raises(ValueError, match="must name its execution configuration"):
        KnowledgeRecord(knowledge_id="k", kind=KNOWLEDGE_MEASUREMENT,
                        binding=BINDING_CONFIGURATION)
    with pytest.raises(ValueError, match="must not carry a configuration fingerprint"):
        KnowledgeRecord(knowledge_id="k", kind=KNOWLEDGE_HUMAN_CONFIRMED,
                        binding=BINDING_INDEPENDENT, configuration_fingerprint="abc")
    with pytest.raises(ValueError, match="unknown binding"):
        KnowledgeRecord(knowledge_id="k", kind=KNOWLEDGE_HUMAN_CONFIRMED, binding="maybe")


# ── E. 실제 모델 둘로 실제로 재서 같은 규칙을 확인한다 ────────────────────────
#
# 자산: `<자산뿌리>/models/zipdepth/` 의 단안 깊이 가중치. 같은 기능의 **다른 실행
# 구성** 이 실제로 존재하는 드문 자리다 — 입력 256/384 가 각각 따로 내보내져 있어
# AI-B-01 이 말하는 "같은 capability, 다른 조합" 이 합성이 아니라 실물이다.

MODEL_DIR = ("models", "zipdepth")
MODEL_SMALL = "zipdepth_base_256_int8.onnx"
MODEL_LARGE = "zipdepth_base_384_int8.onnx"


def _runtime_available() -> bool:
    try:
        import onnxruntime  # noqa: F401
    except Exception:
        return False
    return True


def _models_present() -> bool:
    return asset_root_present() and all(
        asset_path(*MODEL_DIR, name).exists() for name in (MODEL_SMALL, MODEL_LARGE))


needs_real_models = pytest.mark.skipif(
    not (_models_present() and _runtime_available()),
    reason="실제 깊이 모델 자산 또는 추론 런타임이 없다",
)


def _resident_mb() -> float | None:
    """이 프로세스의 상주 메모리(MB). 못 읽으면 `None` — 0 이 아니다."""
    try:
        for line in open("/proc/self/status", encoding="utf-8"):
            if line.startswith("VmRSS"):
                return float(re.findall(r"\d+", line)[0]) / 1024.0
    except OSError:
        return None
    return None


def _measure_real(name: str, side: int) -> tuple[ExecutionConfiguration, dict]:
    """모델 1건을 실제로 올려 돌리고 **잰 것만** 돌려준다.

    품질은 재지 않는다 — 이 기계에 깊이 정답(ground truth)이 없다. 그래서 반환
    dict 에 `quality` 키가 **없고**, 그 부재가 이 시험의 절반이다.
    """
    import numpy as np
    import onnxruntime as runtime_module

    path = asset_path(*MODEL_DIR, name)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    configuration = ExecutionConfiguration(
        capability_kind=KIND,
        # 모델 신원은 파일 내용에서 파생시킨다 — 이름이 같은 다른 파일이 같은
        # 구성으로 읽히지 않게(AI-B-02 의 무결성 식별과 같은 판단).
        implementation_ref=f"zipdepth@{digest}",
        runtime_ref=f"cpu-inference-runtime@{runtime_module.__version__}",
        input_profile=f"resolution.{side}x{side}",
        hardware_tags=("compute.cpu",),
        preprocess_ref="zeros-constant-input",
    )

    options = runtime_module.SessionOptions()
    options.intra_op_num_threads = 1  # 측정 조건을 고정한다
    before = _resident_mb()
    session = runtime_module.InferenceSession(
        str(path), options, providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    frame = np.zeros((1, 3, side, side), dtype=np.float32)
    for _ in range(2):
        session.run(None, {input_name: frame})
    samples = []
    for _ in range(10):
        started = time.perf_counter()
        session.run(None, {input_name: frame})
        samples.append((time.perf_counter() - started) * 1000.0)
    after = _resident_mb()

    latency = statistics.median(samples)
    values = {MEASURE_LATENCY_MS: latency, MEASURE_THROUGHPUT_HZ: 1000.0 / latency}
    if before is not None and after is not None:
        values[MEASURE_MEMORY_MB] = max(after - before, 0.0)
    return configuration, values


@pytest.fixture(scope="module")
def real_profiles():
    small_config, small_values = _measure_real(MODEL_SMALL, 256)
    large_config, large_values = _measure_real(MODEL_LARGE, 384)
    ledger = ExecutionProfileLedger()
    return {
        "ledger": ledger,
        "small": (small_config, small_values),
        "large": (large_config, large_values),
    }


@needs_real_models
def test_real_models_are_two_different_execution_configurations(real_profiles):
    """같은 기능·같은 런타임·같은 하드웨어인데 모델과 입력이 다르다 → 다른 구성."""
    small_config, _ = real_profiles["small"]
    large_config, _ = real_profiles["large"]
    assert small_config.fingerprint != large_config.fingerprint
    assert small_config.differing_axes(large_config) == ("implementation_ref", "input_profile")


@needs_real_models
def test_real_measurements_record_what_was_measured_and_omit_what_was_not(real_profiles):
    """실측값은 들어가고, **품질은 키가 없다** — 이 기계에 깊이 정답이 없으므로."""
    small_config, small_values = real_profiles["small"]
    recorded = real_profiles["ledger"].record(
        VerifiedExecutionProfile(
            configuration=small_config,
            measurements=small_config.measure(small_values, sample_count=10,
                                              evidence_refs=("tests/test_execution_profile.py::E",)),
            validated_by=("latency", "throughput"),
            measured_by="tests/test_execution_profile.py",
        ))
    assert recorded.value(MEASURE_LATENCY_MS) > 0.0
    assert recorded.value(MEASURE_QUALITY) is None
    assert MEASURE_QUALITY in recorded.unmeasured()
    # 연산 단위를 재지 않았으므로 예산용 비용으로 환산되지 않는다.
    assert recorded.to_resource_cost() is None
    # 품질을 요구하면 "미달" 이 아니라 "미측정" 이다.
    verdict = real_profiles["ledger"].evaluate(
        ProfileRequirement(small_config, min_quality=0.6))
    assert verdict.reason == f"{REASON_METRIC_NOT_MEASURED}:{MEASURE_QUALITY}"


@needs_real_models
def test_the_small_configuration_profile_does_not_satisfy_the_large_one(real_profiles):
    """**이 시험이 이 작업의 결론이다.**

    256 구성에서 실제로 잰 지연은 384 구성의 요구를 만족하지 못한다. 두 단계로
    확인한다.

    1. 384 프로파일을 아직 재지 않은 동안: 384 요구는 256 값으로 통과하지 못하고
       `no_profile_for_this_configuration` 이 된다 — 재측정 의무.
    2. 384 를 실제로 재서 넣은 뒤: 두 측정값 사이에 예산을 두면 256 구성은 적격,
       384 구성은 `latency_above_budget` 이다. 즉 256 의 숫자는 384 의 조건을
       어느 시점에도 만족한 적이 없다.
    """
    ledger = ExecutionProfileLedger()
    small_config, small_values = real_profiles["small"]
    large_config, large_values = real_profiles["large"]

    small_latency = small_values[MEASURE_LATENCY_MS]
    large_latency = large_values[MEASURE_LATENCY_MS]
    # 실측 사실: 입력 변이 2.25배인 구성이 실제로 더 느리다. 이 기계 기준
    # 2026-11-04 측정 — 256 p50 ≈ 107 ms, 384 p50 ≈ 211 ms.
    assert large_latency > small_latency * 1.3, (small_latency, large_latency)

    # 예산은 두 실측값 사이에서 **유도한다** — 손으로 적은 숫자를 쓰지 않는다.
    budget = (small_latency + large_latency) / 2.0

    ledger.record(VerifiedExecutionProfile(
        configuration=small_config, measurements=small_config.measure(small_values)))

    # (1) 384 구성의 요구는 256 측정값으로 판정되지 않는다.
    large_requirement = ProfileRequirement(large_config, max_latency_ms=budget)
    before = ledger.evaluate(large_requirement)
    assert before.reason == REASON_NO_PROFILE_FOR_CONFIGURATION
    assert [d.axes for d in before.measured_elsewhere] == [
        ("implementation_ref", "input_profile")]

    # (2) 실제로 재서 넣으면 그 구성의 값으로만 판정된다.
    ledger.record(VerifiedExecutionProfile(
        configuration=large_config, measurements=large_config.measure(large_values)))
    assert ledger.evaluate(large_requirement).reason == REASON_LATENCY_ABOVE_BUDGET
    assert ledger.evaluate(
        ProfileRequirement(small_config, max_latency_ms=budget)).reason == REASON_ELIGIBLE


@needs_real_models
def test_swapping_the_real_model_reopens_latency_but_not_the_human_label(real_profiles):
    """구성이 256 → 384 로 바뀌면 지연은 다시 재고, 사람 확인은 그대로 쓴다."""
    ledger = ExecutionProfileLedger()
    small_config, small_values = real_profiles["small"]
    large_config, _ = real_profiles["large"]
    ledger.record(VerifiedExecutionProfile(
        configuration=small_config, measurements=small_config.measure(small_values)))
    ledger.record_knowledge(KnowledgeRecord(
        knowledge_id="entity-7.label", kind=KNOWLEDGE_HUMAN_CONFIRMED,
        binding=BINDING_INDEPENDENT, subject=KIND, confirmed_by="operator-1",
        content_ref="fire_extinguisher"))

    moved = ledger.supersede(small_config, large_config, subject=KIND)
    assert MEASURE_LATENCY_MS in moved.must_remeasure
    assert MEASURE_THROUGHPUT_HZ in moved.must_remeasure
    assert moved.reusable_knowledge == ("entity-7.label",)
    assert moved.invalidated_knowledge == (f"measurement:{small_config.fingerprint}",)


# ── F. 기존 판정이 올바른 숫자를 본다 ────────────────────────────────────────


def test_an_unmeasured_profile_reaches_the_existing_gate_as_unmeasured():
    """판정을 새로 만들지 않는다 — `model_assignment` 의 기존 관문이 그대로 막는다."""
    from mission_runtime.runtime.execution_profile import model_version_from
    from mission_runtime.runtime.model_assignment import (
        REASON_UNMEASURED_NOT_ELIGIBLE,
        DeviceProfile,
        MissionRequirement,
        ModelAssigner,
    )

    configuration = config()
    candidate = model_version_from(
        profile(configuration, {MEASURE_LATENCY_MS: 94.3, MEASURE_MEMORY_MB: 46.1}),
        model_id="depth", version="256")
    assert candidate.latency_ms == 94.3
    assert candidate.quality is None          # 0 이 아니다
    assert not candidate.fully_measured
    assert candidate.verified_input_conditions == frozenset({"resolution.256x256"})

    assigner = ModelAssigner()
    assigner.register(candidate)
    device = DeviceProfile(device_id="edge-1", hw_tags=frozenset({"compute.cpu", "tier.edge"}),
                           input_conditions=frozenset({"resolution.256x256"}))
    mission = MissionRequirement(mission_id="m-1", capability_kind=KIND)
    assignment = assigner.assign(device, mission)
    assert not assignment.is_assigned
    assert assignment.rejected[0].reason == REASON_UNMEASURED_NOT_ELIGIBLE


@needs_real_models
def test_the_large_configuration_candidate_is_out_of_scope_on_a_small_input_device(real_profiles):
    """실측으로: 384 구성에서 잰 버전은 256 입력만 선언한 장치의 범위 밖이다."""
    from mission_runtime.runtime.execution_profile import model_version_from
    from mission_runtime.runtime.model_assignment import (
        REASON_SCOPE_CONDITION,
        DeviceProfile,
        MissionRequirement,
        ModelAssigner,
    )

    large_config, large_values = real_profiles["large"]
    candidate = model_version_from(
        VerifiedExecutionProfile(configuration=large_config,
                                 measurements=large_config.measure(large_values)),
        model_id="zipdepth", version="384")
    assigner = ModelAssigner()
    assigner.register(candidate)
    device = DeviceProfile(device_id="edge-1", hw_tags=frozenset({"compute.cpu"}),
                           input_conditions=frozenset({"resolution.256x256"}))
    assignment = assigner.assign(device, MissionRequirement(mission_id="m-1", capability_kind=KIND))
    assert not assignment.is_assigned
    assert assignment.rejected[0].reason == REASON_SCOPE_CONDITION
