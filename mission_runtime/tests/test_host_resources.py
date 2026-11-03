"""implements: AI-O-05, AI-O-01, AI-C-05, AI-C-01
covers: 선언된 L1 가속기 목록에 **이 기계의 실측**을 입히는 경로 — 기능정의서
        §4.4 가 요구하는 [E] 리소스 현황이 선언 데이터가 아니라 계측이 되게 하고,
        못 잰 값이 0 이나 선언값으로 바뀌지 않게 고정한다.

2026-11-03 감사가 적은 결손은 "아홉 구역에 자리는 있는데 **그 자리를 채우는 것이
선언 데이터**"였다. 자리의 존재는 `tests/test_dashboard_regions.py` 가 보고, 이 파일은
그 자리에 들어온 숫자의 **출처**를 본다.

무엇을 고정하지 않는가
----------------------
이 기계에서 어떤 값이 실제로 읽히는지는 고정하지 않는다 — WSL 에는 CPU 온도 센서와
RAPL 이 없고 다른 기계에는 있다. 고정하는 것은 **읽히든 안 읽히든 응답이 거짓말을
하지 않는다**는 것이다: 못 쟀으면 값 칸이 없고, 선언 숫자가 실측 자리를 대신 채우지
않으며, 가속기는 목록에서 빠지지 않는다.
"""

from __future__ import annotations

import pytest

from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.observability.host_resources import (
    BOARD_PROBE_ID,
    PROBE_NEEDS_SECOND_SAMPLE,
    PROBE_NO_SENSOR,
    PROBE_OK,
    PROBE_TOOL_FAILED,
    PROBE_TOOL_MISSING,
    PROBE_TOOL_TIMEOUT,
    HOST_PROBE_REASONS,
    HostReadout,
    HostResourceReader,
    resolve_probes,
    with_host_measurements,
)
from mission_runtime.observability import host_resources
from mission_runtime.observability.layered_metrics import (
    MEASUREMENT_SOURCES,
    SOURCE_DECLARED,
    SOURCE_MEASURED,
    SOURCE_UNAVAILABLE,
    AcceleratorInstance,
    BoardResources,
    LayeredResourceView,
    Measurement,
    ServiceRuntime,
)

AT = 1793577600.0
RATIO, CELSIUS, WATT = "ratio", "celsius", "watt"


def declared_view() -> LayeredResourceView:
    """현장이 선언한 L1 목록. 기능정의서 §1.2 의 구성(동종 가속기 복수)을 닮게 둔다."""
    return LayeredResourceView(
        accelerators=(
            # 계측 지점을 지목한 개체 — 선언 숫자가 함께 있다(개념 예시).
            AcceleratorInstance("cpu-0", "cpu", attachment="builtin",
                                utilization=Measurement(0.41, RATIO, AT,
                                                        source=SOURCE_DECLARED),
                                temperature=Measurement(54.0, CELSIUS, AT,
                                                        source=SOURCE_DECLARED)),
            # 아무도 재지 않는 개체 — 선언만 있다.
            AcceleratorInstance("ext-npu-0", "npu", attachment="external",
                                vendor_label="외장 NPU #1",
                                utilization=Measurement(0.35, RATIO, AT,
                                                        source=SOURCE_DECLARED)),
            # 선언 숫자조차 없는 개체 — 아무도 채우지 않았다.
            AcceleratorInstance("ext-npu-1", "npu", attachment="external"),
            # 지목했지만 이 기계에 그 지점이 없는 경우를 만들려고 둔다.
            AcceleratorInstance("dgpu-0", "gpu", attachment="discrete"),
        ),
        services=(ServiceRuntime("orchestrator", "cpu-0"),),
        board=BoardResources(
            memory_utilization=Measurement(0.57, RATIO, AT, source=SOURCE_DECLARED),
            power=Measurement(18.4, WATT, AT, source=SOURCE_DECLARED),
            power_trend=(Measurement(16.1, WATT, AT, source=SOURCE_DECLARED),),
        ),
    )


def readout(*, gpu: bool = False, cpu_temperature: bool = False,
            power: bool = False) -> HostReadout:
    """계측기가 돌아온 결과 하나. 기계에 따라 달라지는 조건을 인자로 세운다."""
    accelerators = {
        "cpu": AcceleratorInstance(
            "cpu", "cpu", attachment="builtin",
            utilization=Measurement(0.07, RATIO, AT + 10, source=SOURCE_MEASURED),
            temperature=(Measurement(49.5, CELSIUS, AT + 10, source=SOURCE_MEASURED)
                         if cpu_temperature else Measurement(None, CELSIUS,
                                                             source=SOURCE_UNAVAILABLE)),
        ),
    }
    status = {
        "cpu.utilization": PROBE_OK,
        "cpu.temperature": PROBE_OK if cpu_temperature else PROBE_NO_SENSOR,
        "nvidia": PROBE_OK if gpu else PROBE_TOOL_MISSING,
        "board.memory_utilization": PROBE_OK,
        "board.power": PROBE_OK if power else PROBE_NO_SENSOR,
    }
    if gpu:
        accelerators["gpu-0"] = AcceleratorInstance(
            "gpu-0", "gpu", attachment="discrete", vendor_label="제품 이름",
            utilization=Measurement(0.0, RATIO, AT + 10, source=SOURCE_MEASURED),
            temperature=Measurement(35.0, CELSIUS, AT + 10, source=SOURCE_MEASURED),
        )
        status["gpu-0.utilization"] = PROBE_OK
        status["gpu-0.temperature"] = PROBE_OK
    return HostReadout(
        accelerators=accelerators,
        board=BoardResources(
            memory_utilization=Measurement(0.26, RATIO, AT + 10, source=SOURCE_MEASURED),
            power=(Measurement(21.3, WATT, AT + 10, source=SOURCE_MEASURED) if power
                   else Measurement(None, WATT, source=SOURCE_UNAVAILABLE)),
            power_trend=((Measurement(20.9, WATT, AT + 5, source=SOURCE_MEASURED),
                          Measurement(21.3, WATT, AT + 10, source=SOURCE_MEASURED))
                         if power else ()),
        ),
        probe_status=status,
    )


PROBES = {"cpu-0": "cpu", "dgpu-0": "gpu-0"}


def merged(**kwargs) -> LayeredResourceView:
    return with_host_measurements(declared_view(), readout(**kwargs),
                                  probe_by_instance=PROBES,
                                  board_probe=BOARD_PROBE_ID)


def accel(view: LayeredResourceView, instance_id: str) -> AcceleratorInstance:
    return next(a for a in view.accelerators if a.instance_id == instance_id)


# --- 실측이 선언 자리에 들어온다 (AI-O-05) -----------------------------------


def test_a_declared_accelerator_the_reader_identifies_gets_measured_values():
    """선언이 지목한 계측 지점이 읽히면 그 개체의 값은 **실측**이다."""
    view = merged(gpu=True)

    cpu = accel(view, "cpu-0")
    assert cpu.utilization.value == 0.07
    assert cpu.utilization.source == SOURCE_MEASURED
    assert cpu.utilization.at == AT + 10, "실측 시각이 선언 시각으로 남아 있다"
    # 종류·부착 형태는 선언이 소유한다 — 계측이 등록 데이터를 덮지 않는다.
    assert cpu.kind == "cpu" and cpu.attachment == "builtin"


def test_an_accelerator_nobody_measures_stays_declared_and_says_so():
    """재지 않는 개체의 숫자는 그대로 남고 **선언이라고 적힌다**.

    숫자가 있다는 것과 그 숫자가 계측이라는 것은 다른 사실이다. 둘을 구분하지 않으면
    화면은 개념 예시(기능정의서 §1)를 현재 계측으로 읽는다.
    """
    view = merged()

    npu = accel(view, "ext-npu-0")
    assert npu.utilization.value == 0.35
    assert npu.utilization.source == SOURCE_DECLARED
    # 아무도 채우지 않은 자리에는 출처도 없다 — unavailable 과 다른 사실이다.
    empty = accel(view, "ext-npu-1")
    assert empty.utilization.value is None and empty.utilization.source is None


def test_an_instance_named_like_the_probe_is_matched_without_extra_declaration():
    """개체 id 가 계측 지점 id 와 같으면 지목 없이도 이어진다.

    그 기계를 읽어 만든 선언(`tools/snapshot_ui`)이 그렇게 쓰므로 한 규칙으로 둔다.
    종류나 벤더 라벨로는 추측하지 않는다(원칙 #1).
    """
    declared = LayeredResourceView(accelerators=(AcceleratorInstance("cpu", "cpu"),))
    view = with_host_measurements(declared, readout())

    assert accel(view, "cpu").utilization.source == SOURCE_MEASURED
    assert resolve_probes(declared, readout()) == {"cpu": "cpu"}


def test_a_label_is_filled_only_when_the_declaration_left_it_empty():
    """제품명은 표시 라벨이다 — 선언이 적은 라벨을 계측기가 덮지 않는다(AI-O-05)."""
    view = merged(gpu=True)

    assert accel(view, "dgpu-0").vendor_label == "제품 이름"
    assert accel(view, "ext-npu-0").vendor_label == "외장 NPU #1"


# --- 미측정 ≠ 0 ≠ 선언값 (문서 §4.4·§4.5) -----------------------------------


def test_a_slot_the_reader_could_not_read_has_no_value_and_is_not_zero():
    """못 읽은 칸은 값이 없다. 0 을 넣으면 유휴와 고장이 화면에서 같아진다."""
    cpu = accel(merged(cpu_temperature=False), "cpu-0")

    assert cpu.temperature.value is None
    assert cpu.temperature.unit == CELSIUS, "단위는 값이 없어도 남는다(§4.5)"
    assert cpu.temperature.source == SOURCE_UNAVAILABLE


def test_a_probed_slot_does_not_fall_back_to_the_declared_number():
    """"이 칸은 여기서 잰다"고 적은 자리에 선언 숫자를 남기지 않는다.

    선언은 54.0 ℃ 를 적어 두었지만 이 기계에는 센서가 없다. 그 숫자를 그대로 두면
    화면은 그것을 현재 온도로 읽는다 — 미측정이라고 적는 편이 사실이다.
    """
    cpu = accel(merged(cpu_temperature=False), "cpu-0")

    assert cpu.temperature.value != 54.0
    assert cpu.temperature.value is None


def test_a_probe_this_machine_lacks_leaves_the_accelerator_unmeasured_not_absent():
    """nvidia-smi 가 없는 기계에서도 선언된 GPU 는 목록에 남는다(§4.1 완전성)."""
    view = merged(gpu=False)

    dgpu = accel(view, "dgpu-0")
    assert dgpu.utilization.value is None
    assert dgpu.utilization.source == SOURCE_UNAVAILABLE
    assert "dgpu-0" in view.unmeasured_accelerators()
    assert "dgpu-0" not in view.host_measured_accelerators()


def test_measured_zero_and_unmeasured_are_not_the_same_shape():
    """쟀더니 0(유휴 GPU)과 못 쟀다는 서로 다른 상태다."""
    view = merged(gpu=True)

    idle_gpu = accel(view, "dgpu-0").utilization
    assert idle_gpu.value == 0.0 and idle_gpu.source == SOURCE_MEASURED
    assert "dgpu-0" not in view.unmeasured_accelerators()
    assert accel(view, "ext-npu-1").utilization.value is None


def test_the_measured_list_is_not_the_complement_of_the_unmeasured_list():
    """실측·미측정·선언은 **세 상태**다. 둘로 줄이면 선언이 실측으로 읽힌다."""
    view = merged(gpu=True)

    measured = set(view.host_measured_accelerators())
    unmeasured = set(view.unmeasured_accelerators())
    declared_only = {
        a.instance_id for a in view.accelerators
        if a.utilization.source == SOURCE_DECLARED
    }
    assert measured == {"cpu-0", "dgpu-0"}
    assert unmeasured == {"ext-npu-1"}
    assert declared_only == {"ext-npu-0"}
    assert not measured & unmeasured and not measured & declared_only


# --- 전력 (구역 E, AI-O-01 관측 항목) ----------------------------------------


def test_power_is_reported_as_unmeasured_rather_than_omitted():
    """전력은 칸을 지우지 않는다 — 이 기계가 못 읽어도 "못 읽었다"가 응답이다."""
    board = merged(power=False).board

    assert board.power.unit == WATT
    assert board.power.value is None and board.power.source == SOURCE_UNAVAILABLE
    # 선언된 추이를 실측 자리에 붙이지 않는다 — 없는 선을 그리지 않는다.
    assert board.power_trend == ()


def test_power_is_measured_when_the_counter_exists():
    board = merged(power=True).board

    assert board.power.value == 21.3 and board.power.source == SOURCE_MEASURED
    assert [s.source for s in board.power_trend] == [SOURCE_MEASURED, SOURCE_MEASURED]


def test_the_board_stays_declared_when_no_probe_is_named():
    """보드를 지목하지 않은 배치에서는 선언값이 남고 선언이라고 적힌다."""
    view = with_host_measurements(declared_view(), readout(power=True),
                                  probe_by_instance=PROBES)

    assert view.board.power.value == 18.4
    assert view.board.power.source == SOURCE_DECLARED
    assert [s.source for s in view.board.power_trend] == [SOURCE_DECLARED]


# --- 목록의 완전성 (§4.1·§4.4) -----------------------------------------------


def test_measuring_neither_adds_nor_drops_an_accelerator():
    """실측은 목록을 바꾸지 않는다 — 개체는 선언이 정한다(§3 요구사항 2).

    계측기가 찾은 gpu-0 이 선언에 없다면 그것은 설정이 할 일이고, 화면에 없던 장치가
    임의로 생기면 선언이 정본이라는 요구가 깨진다.
    """
    declared = LayeredResourceView(accelerators=(AcceleratorInstance("ext-npu-1", "npu"),))
    view = with_host_measurements(declared, readout(gpu=True))

    assert [a.instance_id for a in view.accelerators] == ["ext-npu-1"]


def test_an_idle_accelerator_is_still_idle_after_measuring():
    """배치된 서비스가 없는 가속기는 실측이 붙어도 유휴로 남는다."""
    view = merged(gpu=True)

    assert set(view.idle_accelerators() and
               [a.instance_id for a in view.idle_accelerators()]) == {
        "ext-npu-0", "ext-npu-1", "dgpu-0"
    }
    assert view.placement()["dgpu-0"] == ()


# --- 관측 실패가 응답을 멈추지 않는다 (AI-O-01, AI-C-05) ---------------------


def test_the_reader_reports_a_missing_tool_as_a_reason_not_an_exception(monkeypatch):
    """psutil 이 없어도 읽기는 돌아온다 — 그 항목만 미측정이다."""
    monkeypatch.setattr(host_resources, "_psutil", lambda: None)
    monkeypatch.setattr(host_resources, "_query_nvidia", lambda t: ((), PROBE_TOOL_MISSING))

    result = HostResourceReader().readout()

    cpu = result.accelerators["cpu"]
    assert cpu.utilization.value is None and cpu.utilization.source == SOURCE_UNAVAILABLE
    assert result.probe_status["cpu.utilization"] == PROBE_TOOL_MISSING
    assert result.probe_status["board.memory_utilization"] == PROBE_TOOL_MISSING
    assert result.board.memory_utilization.value is None


def test_a_probe_that_raises_becomes_a_reason(monkeypatch):
    """권한 오류·깨진 출력도 사유다. 관측 하나가 조회 전체를 세우지 않는다."""
    class Exploding:
        def cpu_percent(self, interval=None):
            raise PermissionError("nope")

        def sensors_temperatures(self):
            raise OSError("nope")

        def virtual_memory(self):
            raise RuntimeError("nope")

    monkeypatch.setattr(host_resources, "_psutil", lambda: Exploding())
    monkeypatch.setattr(host_resources, "_query_nvidia", lambda t: ((), PROBE_TOOL_FAILED))

    result = HostResourceReader().readout()

    assert result.probe_status["cpu.utilization"] == PROBE_TOOL_FAILED
    assert result.probe_status["board.memory_utilization"] == PROBE_TOOL_FAILED
    assert result.probe_status["nvidia"] == PROBE_TOOL_FAILED
    assert result.accelerators["cpu"].utilization.value is None


def test_a_timeout_is_its_own_reason(monkeypatch):
    """도구가 매달리는 것과 없는 것은 다른 사실이다(AI-O-02: 사건을 구분해 적는다)."""
    import subprocess

    def hang(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=2.0)

    monkeypatch.setattr(subprocess, "run", hang)
    readings, reason = host_resources._query_nvidia(0.1)

    assert readings == () and reason == PROBE_TOOL_TIMEOUT


def test_the_first_interval_free_cpu_sample_is_not_a_measured_zero(monkeypatch):
    """psutil 규약상 간격 없는 첫 호출은 의미 없는 0.0 이다. 그것을 실측으로 내보내면
    유휴와 "아직 못 쟀다"가 같아진다(§4.4)."""
    calls = []

    class Primed:
        def cpu_percent(self, interval=None):
            calls.append(interval)
            return 0.0 if len(calls) == 1 else 31.0

        def sensors_temperatures(self):
            return {}

        def virtual_memory(self):
            class M:
                percent = 40.0
            return M()

    monkeypatch.setattr(host_resources, "_psutil", lambda: Primed())
    monkeypatch.setattr(host_resources, "_query_nvidia", lambda t: ((), PROBE_TOOL_MISSING))
    reader = HostResourceReader(cpu_interval_s=None)

    first = reader.readout()
    assert first.accelerators["cpu"].utilization.value is None
    assert first.probe_status["cpu.utilization"] == PROBE_NEEDS_SECOND_SAMPLE

    second = reader.readout()
    assert second.accelerators["cpu"].utilization.value == pytest.approx(0.31)
    assert second.probe_status["cpu.utilization"] == PROBE_OK


def test_a_utilisation_over_the_range_is_clamped_not_raised(monkeypatch):
    """관측값 하나가 응답 전체를 세우지 않는다(AI-O-01).

    `AcceleratorInstance` 는 0~1 밖의 사용률을 거부하고, 그 예외가 조회 경로로 번지면
    화면은 가속기 목록 전체를 잃는다.
    """
    class Odd:
        def cpu_percent(self, interval=None):
            return 143.0

        def sensors_temperatures(self):
            return {}

        def virtual_memory(self):
            class M:
                percent = 101.5
            return M()

    monkeypatch.setattr(host_resources, "_psutil", lambda: Odd())
    monkeypatch.setattr(host_resources, "_query_nvidia", lambda t: ((), PROBE_TOOL_MISSING))

    # 0.0 은 psutil 규약상 "간격 없음"이라 첫 표본이 기준점 잡기로 버려진다 —
    # 자르기를 보려면 값이 실제로 쓰이는 간격을 준다.
    result = HostResourceReader(cpu_interval_s=0.01).readout()

    assert result.accelerators["cpu"].utilization.value == 1.0
    assert result.board.memory_utilization.value == 1.0


# --- 이 기계에서 실제로 돌아본다 ---------------------------------------------


def test_this_machine_reads_without_raising_whatever_it_has():
    """실제 호스트를 한 번 읽는다. 무엇이 읽히는지는 기계마다 다르고 그것이 정상이다.

    고정하는 것은 둘이다 — 어떤 실패도 예외로 번지지 않고, 모든 측정 칸은 값이
    없어도 단위와(읽으려 했다면) 사유를 들고 있다.
    """
    result = HostResourceReader(cpu_interval_s=0.05).readout()

    assert "cpu" in result.accelerators
    for probe_id, accelerator in result.accelerators.items():
        for slot in (accelerator.utilization, accelerator.temperature):
            assert slot.unit
            assert slot.source in MEASUREMENT_SOURCES
            if slot.measured:
                assert slot.source == SOURCE_MEASURED
    for reason in result.probe_status.values():
        assert reason in HOST_PROBE_REASONS, reason


# --- 이름은 공통 사전에 (AI-C-01) --------------------------------------------


def test_the_provenance_names_and_vocabulary_are_registered():
    """새 이름을 편의상 와이어에 올리지 않는다.

    어휘의 정본은 코드(`layered_metrics.MEASUREMENT_SOURCES`)이고 사전은 이름과 뜻을
    등재한다. 둘이 갈라지면 소비자가 모르는 값이 응답에 나온다.
    """
    spec = dd.spec_for(dd.MEASUREMENT_SOURCE)
    assert spec.value_kind == "|".join(MEASUREMENT_SOURCES)
    assert tuple(dd.MEASUREMENT_SOURCES) == MEASUREMENT_SOURCES
    for name in (dd.HOST_PROBE_ID, dd.HOST_PROBE_STATUS):
        assert dd.spec_for(name).meaning
