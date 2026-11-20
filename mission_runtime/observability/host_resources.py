"""Reads Layer 1 resources off the real host — no fabricated numbers.

implements: AI-O-05 (계층별 자원·서비스 지표 관측), AI-O-01 (실행 성능·자원 관측)
관련: AI-O-06 (통합 상태 뷰), AI-C-04 (외부 기술은 provider 경계 뒤), AI-C-05

기능정의서 §4.4 가 요구하는 [E] 리소스 현황은 **실제 계측값**이다. 자료구조만 있고
값을 손으로 넣으면 화면은 돌지만 운영에서는 아무것도 못 본다. 그래서 이 모듈이
`LayeredResourceView` 를 이 기계에서 직접 읽어 만든다.

## 읽는 곳과 없을 때

| 값 | 어디서 | 없으면 |
|---|---|---|
| CPU 사용률 | `psutil.cpu_percent` | 측정 없음 |
| CPU 온도 | `psutil.sensors_temperatures` → `/sys/class/thermal` | 측정 없음 |
| GPU 사용률·온도 | `nvidia-smi --query-gpu` | 그 가속기는 목록에만 남고 값이 측정 없음 |
| 보드 메모리 | `psutil.virtual_memory` | 측정 없음 |
| 소비 전력 | `/sys/class/powercap` 의 energy_uj 두 번 읽어 차분 | 측정 없음 |

**없는 값에 0 을 넣지 않는다.** `Measurement(None, unit)` 이 "못 쟀다"이고, 0 은
"쟀더니 0"이다. 이 구분이 깨지면 유휴와 고장이 화면에서 같아진다(§4.4·§4.5).

도구가 없으면 그 항목만 빠진다 — psutil 이 없어도 GPU 는 읽히고, nvidia-smi 가
없어도 CPU 는 읽힌다(AI-C-05: 선택 구성요소 결손은 축소이지 실패가 아니다).

## 벤더 이름은 라벨이다

`nvidia-smi` 가 주는 제품명은 `vendor_label` 로만 들어간다. 선택·분기 근거로 쓰지
않는다 — 그러면 새 가속기가 올 때 핵심 코드를 고쳐야 한다(AI-O-05).

전력은 두 시점의 에너지 차분이라 **한 번 읽어서는 나오지 않는다.** 첫 호출은 전력을
측정 없음으로 두고, 같은 reader 로 다시 읽을 때부터 값이 생긴다. 지어내지 않는다.

## 선언된 개체에 실측을 입히는 길 (2026-11-03)

화면이 보는 가속기 목록은 **선언 데이터**다(기능정의서 §3 요구사항 2). 그래서 이
모듈은 선언을 대체하지 않고 `with_host_measurements` 로 **그 자리에 실측을 입힌다**.

* 선언이 `host_probe` 로 계측 지점을 지목하면(또는 선언 id 가 계측 지점 id 와 같으면)
  그 개체의 사용률·온도는 실측으로 바뀐다 — `source=measured`.
* **지목한 칸은 실측 아니면 `unavailable` 이다.** 선언값을 그 자리에 남기지 않는다 —
  "이 칸은 여기서 잰다"고 적은 자리에 과거의 선언 숫자를 두면 화면은 그것을 현재
  계측으로 읽는다. 값 없음이고 0 이 아니며, 단위는 남는다.
* 지목하지 않은 칸은 선언값이 그대로 남고 `source=declared` 다 — 숫자가 있어도
  계측이 아니라는 사실이 응답에 적힌다.
* 어느 경우에도 **목록에서 빠지지 않는다**(§4.1·§4.4 가속기 목록의 완전성). 실측이
  안 되는 외장 NPU 도 유휴로 남아 있어야 자원 여유를 판단할 수 있다.
* 계측기가 못 읽은 사유는 `HostReadout.probe_status` 에 사유 토큰으로 남는다. 관측
  실패는 응답을 멈추지 않는다(AI-O-01: "외부 관측 기능 장애가 실제 기능 실행을
  중단시키지 않아야 한다") — 모든 읽기는 예외를 사유로 바꾼다.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from mission_runtime.observability.layered_metrics import (
    SOURCE_DECLARED,
    SOURCE_MEASURED,
    SOURCE_UNAVAILABLE,
    AcceleratorInstance,
    BoardResources,
    LayeredResourceView,
    Measurement,
)

_THERMAL = Path("/sys/class/thermal")
_POWERCAP = Path("/sys/class/powercap")

#: nvidia-smi 호출이 매달리지 않게 하는 상한. 관측이 실행을 멈추게 하지 않는다(AI-O-01).
NVIDIA_SMI_TIMEOUT_S = 2.0

RATIO = "ratio"
CELSIUS = "celsius"
WATT = "watt"

# --- 계측 지점과 그 상태 사유 토큰 -------------------------------------------
#
# 사유는 **표시 문구가 아니라 토큰**이다(화면 문구는 가시화가 만든다, AI-C-19).
# "왜 이 칸이 비었는가"를 답하기 위한 것이고, 비었다는 사실 자체는 `Measurement` 의
# 값 부재가 이미 말한다.

#: 읽었다.
PROBE_OK = "ok"
#: 계측 도구가 이 기계에 없다(모듈 import 실패, 실행 파일 없음).
PROBE_TOOL_MISSING = "tool_missing"
#: 도구는 있는데 비정상 종료했거나 출력을 해석할 수 없었다(권한 포함).
PROBE_TOOL_FAILED = "tool_failed"
#: 도구가 제한 시간 안에 답하지 않았다.
PROBE_TOOL_TIMEOUT = "tool_timeout"
#: 그 센서·카운터가 이 기계에 없다(WSL 의 CPU 온도, powercap 없는 커널).
PROBE_NO_SENSOR = "no_sensor"
#: 도구는 돌았지만 그 항목을 `[N/A]` 로 돌려줬다. 0 으로 바꾸지 않는다.
PROBE_VALUE_NOT_AVAILABLE = "value_not_available"
#: 차분이 필요해 아직 값이 없다(전력, 간격 없는 첫 CPU 표본). 다음 읽기부터 나온다.
PROBE_NEEDS_SECOND_SAMPLE = "needs_second_sample"
#: 선언이 지목한 계측 지점이 이 기계에 없다.
PROBE_NOT_FOUND = "probe_not_found"

HOST_PROBE_REASONS: tuple[str, ...] = (
    PROBE_OK, PROBE_TOOL_MISSING, PROBE_TOOL_FAILED, PROBE_TOOL_TIMEOUT,
    PROBE_NO_SENSOR, PROBE_VALUE_NOT_AVAILABLE, PROBE_NEEDS_SECOND_SAMPLE,
    PROBE_NOT_FOUND,
)

#: 보드 수준 계측 지점의 id. 가속기 개체 id 공간과 겹치지 않는 이름이다.
BOARD_PROBE_ID = "board"
#: nvidia-smi 자체의 상태를 적는 자리. 개체별 칸(`gpu-0.utilization`)과 달리 **도구**의
#: 상태이고, 도구가 죽으면 개체가 몇 개인지조차 모르므로 개체 칸으로 적을 수 없다.
NVIDIA_TOOL_PROBE_ID = "nvidia"

#: 측정 슬롯 이름. 데이터 사전의 이름과 같다(AI-C-01).
SLOT_UTILIZATION = "utilization"
SLOT_TEMPERATURE = "temperature"
SLOT_MEMORY = "memory_utilization"
SLOT_POWER = "power"


def _unmeasured(unit: str) -> Measurement:
    """아무도 채우지 않은 자리. 출처가 없는 것이 사실이다."""
    return Measurement(None, unit)


def _unavailable(unit: str) -> Measurement:
    """재려 했으나 못 얻은 자리. 값은 없고 **시도했다**는 사실이 남는다."""
    return Measurement(None, unit, source=SOURCE_UNAVAILABLE)


def _ratio(percent: float, now: float) -> Measurement:
    """퍼센트를 0~1 비율로. 범위를 벗어난 값은 잘라낸다.

    psutil 이 드물게 100 을 넘는 값을 돌려주는 기계가 있고, 그 값은
    `AcceleratorInstance` 의 범위 검사에서 예외가 된다 — 관측값 하나가 응답 전체를
    세우지 않게 여기서 자른다(AI-O-01).
    """
    return Measurement(min(1.0, max(0.0, float(percent) / 100.0)), RATIO, now,
                       source=SOURCE_MEASURED)


def _psutil():
    try:
        import psutil
    except Exception:
        return None
    return psutil


def _cpu_temperature(psutil_module) -> tuple[float | None, str]:
    """CPU 온도와 그 사유. 센서가 없는 기계(WSL 등)에서는 None 이고 그것이 사실이다."""
    if psutil_module is not None:
        try:
            readings = psutil_module.sensors_temperatures() or {}
        except Exception:
            readings = {}
        for name in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
            entries = readings.get(name)
            if entries:
                return float(entries[0].current), PROBE_OK
        for entries in readings.values():
            if entries:
                return float(entries[0].current), PROBE_OK
    try:
        for zone in sorted(_THERMAL.glob("thermal_zone*/temp")):
            return int(zone.read_text().strip()) / 1000.0, PROBE_OK
    except Exception:
        return None, PROBE_TOOL_FAILED
    if psutil_module is None:
        return None, PROBE_TOOL_MISSING
    return None, PROBE_NO_SENSOR


@dataclass(frozen=True)
class GpuReading:
    index: int
    name: str
    utilization: float | None
    temperature: float | None


def _query_nvidia(timeout_s: float) -> tuple[tuple[GpuReading, ...], str]:
    """`nvidia-smi` 한 번 호출. 실패는 예외가 아니라 **사유**로 돌아온다."""
    try:
        completed = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=index,name,utilization.gpu,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=timeout_s, check=False,
        )
    except subprocess.TimeoutExpired:
        return (), PROBE_TOOL_TIMEOUT
    except FileNotFoundError:
        return (), PROBE_TOOL_MISSING
    except (OSError, subprocess.SubprocessError):
        return (), PROBE_TOOL_FAILED
    if completed.returncode != 0:
        # 드라이버가 없거나 권한이 없는 기계도 여기로 온다 — 비정상 종료 하나로
        # 묶고, GPU 가 0 대라는 뜻으로 읽지 않는다.
        return (), PROBE_TOOL_FAILED

    def number(token: str) -> float | None:
        token = token.strip()
        try:
            return float(token)
        except ValueError:
            return None

    readings = []
    for line in completed.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        index = number(parts[0])
        if index is None:
            continue
        util = number(parts[2])
        readings.append(GpuReading(
            index=int(index),
            name=parts[1],
            utilization=None if util is None else util / 100.0,
            temperature=number(parts[3]),
        ))
    return tuple(readings), PROBE_OK


def read_nvidia_gpus(*, timeout_s: float = NVIDIA_SMI_TIMEOUT_S) -> tuple[GpuReading, ...]:
    """`nvidia-smi` 가 있으면 GPU 개체별 값을. 없으면 빈 묶음.

    `[N/A]` 를 숫자로 바꾸지 않는다 — 드라이버가 못 준 값이고, 0 으로 적으면 유휴로
    보인다. 실패 **사유**가 필요하면 `_query_nvidia` 를 쓰는 `HostResourceReader.
    readout()` 을 본다.
    """
    return _query_nvidia(timeout_s)[0]


def _energy_uj() -> tuple[int | None, str]:
    try:
        for entry in sorted(_POWERCAP.glob("*/energy_uj")):
            return int(entry.read_text().strip()), PROBE_OK
    except Exception:
        # 카운터가 있는데 권한이 없는 경우가 여기다(루트 전용 RAPL).
        return None, PROBE_TOOL_FAILED
    return None, PROBE_NO_SENSOR


@dataclass(frozen=True)
class HostReadout:
    """이 기계를 한 번 읽은 결과. **계측 지점(probe) id 로 찾는다.**

    `accelerators` 의 키는 계측 지점 id 이고 `LayeredResourceView` 의 선언된 개체 id 와
    같을 필요가 없다 — 선언은 현장 이름(`cpu-0`, `ext-npu-1`)을 쓰고 계측기는 자기가
    찾은 것의 이름(`cpu`, `gpu-0`)을 쓴다. 둘을 잇는 것은 선언의 `host_probe` 다.

    `probe_status` 의 키는 `"<probe>.<slot>"`(개체 칸) 또는 `"<probe>"`(도구 자체)이고
    값은 `HOST_PROBE_REASONS` 의 토큰이다.
    """

    accelerators: Mapping[str, AcceleratorInstance]
    board: BoardResources
    probe_status: Mapping[str, str]

    def view(self) -> LayeredResourceView:
        """계측만으로 만든 L1 스냅샷. 서비스 계층은 실행관리가 채운다."""
        return LayeredResourceView(
            accelerators=tuple(self.accelerators.values()),
            services=(),
            board=self.board,
        )


@dataclass
class HostResourceReader:
    """이 기계의 Layer 1 자원을 `LayeredResourceView` 로 읽는다.

    같은 인스턴스를 들고 반복 호출한다 — 전력은 두 시점의 차분이라 상태가 필요하다.
    `cpu_instance_id` 는 등록 데이터다: 가속기 개체 id 를 코드가 정하지 않는다.
    """

    cpu_instance_id: str = "cpu"
    gpu_instance_prefix: str = "gpu"
    #: CPU 사용률 표본 구간. 0 이면 직전 호출 이후의 평균(psutil 규약).
    cpu_interval_s: float | None = None
    #: 보드 전력 추이로 들고 다닐 최근 표본 수. 선언된 추이와 섞지 않는다.
    power_trend_len: int = 12
    #: 가속기 사용률 추이의 최근 표본 수. 문서 §4.4 는 전력과 **같은 요구**를
    #: 사용률에도 둔다 — 현재값 하나로는 동종 가속기 간 부하 편중을 볼 수 없다.
    utilization_trend_len: int = 12
    _last_energy_uj: int | None = field(default=None, repr=False)
    _last_energy_at: float | None = field(default=None, repr=False)
    _cpu_primed: bool = field(default=False, repr=False)
    _power_trend: tuple[Measurement, ...] = field(default=(), repr=False)
    #: probe_id → 사용률 추이. 개체별로 따로 센다 — 한 묶음에 섞으면 동종 가속기
    #: 둘의 추이가 한 선으로 합쳐져 편중이 사라진다.
    _utilization_trend: dict = field(default_factory=dict, repr=False)

    def read(self) -> LayeredResourceView:
        return self.readout().view()

    def readout(self) -> HostReadout:
        """한 번 읽고, 못 읽은 칸마다 **사유**를 남긴다.

        어떤 계측 실패도 예외로 번지지 않는다 — 이 메서드가 던지면 상태 조회가
        멈추고, 그것은 "관측 장애가 실행을 멈추지 않는다"(AI-O-01)에 어긋난다.
        """
        now = time.time()
        psutil_module = _psutil()
        status: dict[str, str] = {}

        accelerators: dict[str, AcceleratorInstance] = {}
        accelerators[self.cpu_instance_id] = self._cpu(psutil_module, now, status)
        gpus, nvidia_reason = _query_nvidia(NVIDIA_SMI_TIMEOUT_S)
        status[NVIDIA_TOOL_PROBE_ID] = nvidia_reason
        for gpu in gpus:
            probe_id = f"{self.gpu_instance_prefix}-{gpu.index}"
            status[f"{probe_id}.{SLOT_UTILIZATION}"] = (
                PROBE_OK if gpu.utilization is not None else PROBE_VALUE_NOT_AVAILABLE)
            status[f"{probe_id}.{SLOT_TEMPERATURE}"] = (
                PROBE_OK if gpu.temperature is not None else PROBE_VALUE_NOT_AVAILABLE)
            _gpu_utilization = (_unavailable(RATIO) if gpu.utilization is None
                                else _ratio(gpu.utilization * 100.0, now))
            accelerators[probe_id] = AcceleratorInstance(
                instance_id=probe_id,
                kind="gpu",
                attachment="discrete",
                vendor_label=gpu.name,
                utilization=_gpu_utilization,
                utilization_trend=self._remember_utilization(probe_id, _gpu_utilization),
                temperature=(_unavailable(CELSIUS) if gpu.temperature is None
                             else Measurement(gpu.temperature, CELSIUS, now,
                                              source=SOURCE_MEASURED)),
            )
        return HostReadout(
            accelerators=accelerators,
            board=self._board(psutil_module, now, status),
            probe_status=status,
        )

    def _cpu(self, psutil_module, now: float, status: dict[str, str]) -> AcceleratorInstance:
        utilization, reason = self._cpu_utilization(psutil_module, now)
        status[f"{self.cpu_instance_id}.{SLOT_UTILIZATION}"] = reason
        temperature, temp_reason = _cpu_temperature(psutil_module)
        status[f"{self.cpu_instance_id}.{SLOT_TEMPERATURE}"] = temp_reason
        return AcceleratorInstance(
            instance_id=self.cpu_instance_id,
            kind="cpu",
            attachment="builtin",
            utilization=utilization,
            utilization_trend=self._remember_utilization(self.cpu_instance_id, utilization),
            temperature=(_unavailable(CELSIUS) if temperature is None
                         else Measurement(temperature, CELSIUS, now, source=SOURCE_MEASURED)),
        )

    def _remember_utilization(self, probe_id: str, sample: Measurement
                              ) -> tuple[Measurement, ...]:
        """잰 표본만 쌓는다. **못 잰 구간은 건너뛰고 0 을 넣지 않는다** — 넣으면
        추이가 거짓으로 내려가고 "유휴였다" 로 읽힌다(AI-O-05)."""
        if not sample.measured:
            return tuple(self._utilization_trend.get(probe_id, ()))
        kept = (tuple(self._utilization_trend.get(probe_id, ())) + (sample,))
        kept = kept[-max(1, self.utilization_trend_len):]
        self._utilization_trend[probe_id] = kept
        return kept

    def _cpu_utilization(self, psutil_module, now: float) -> tuple[Measurement, str]:
        if psutil_module is None:
            return _unavailable(RATIO), PROBE_TOOL_MISSING
        try:
            percent = psutil_module.cpu_percent(interval=self.cpu_interval_s)
        except Exception:
            return _unavailable(RATIO), PROBE_TOOL_FAILED
        if not self.cpu_interval_s and not self._cpu_primed:
            # psutil 규약: 간격 없는 **첫** 호출은 비교 대상이 없어 의미 없는 0.0 을
            # 돌려준다. 그 0 을 실측으로 내보내면 "유휴"와 "아직 못 쟀다"가 같아진다
            # (§4.4). 첫 호출은 기준점만 잡고 측정 없음으로 둔다.
            self._cpu_primed = True
            return _unavailable(RATIO), PROBE_NEEDS_SECOND_SAMPLE
        self._cpu_primed = True
        return _ratio(percent, now), PROBE_OK

    def _board(self, psutil_module, now: float, status: dict[str, str]) -> BoardResources:
        memory = _unavailable(RATIO)
        reason = PROBE_TOOL_MISSING
        if psutil_module is not None:
            try:
                memory = _ratio(psutil_module.virtual_memory().percent, now)
                reason = PROBE_OK
            except Exception:
                reason = PROBE_TOOL_FAILED
        status[f"{BOARD_PROBE_ID}.{SLOT_MEMORY}"] = reason
        power, power_reason = self._power(now)
        status[f"{BOARD_PROBE_ID}.{SLOT_POWER}"] = power_reason
        if power.measured:
            self._power_trend = (self._power_trend + (power,))[-max(1, self.power_trend_len):]
        return BoardResources(memory_utilization=memory, power=power,
                              power_trend=self._power_trend)

    def _power(self, now: float) -> tuple[Measurement, str]:
        energy, reason = _energy_uj()
        if energy is None:
            self._last_energy_uj, self._last_energy_at = None, None
            return _unavailable(WATT), reason
        previous, previous_at = self._last_energy_uj, self._last_energy_at
        self._last_energy_uj, self._last_energy_at = energy, now
        if previous is None or previous_at is None:
            # 첫 읽기는 차분이 없다. 0 W 로 적으면 전력을 쓰지 않는 기계로 보인다.
            return _unavailable(WATT), PROBE_NEEDS_SECOND_SAMPLE
        elapsed = now - previous_at
        if elapsed <= 0 or energy < previous:
            # 카운터가 되감겼거나 시간이 흐르지 않았다. 음수 전력을 만들지 않는다.
            return _unavailable(WATT), PROBE_NEEDS_SECOND_SAMPLE
        return Measurement((energy - previous) / 1e6 / elapsed, WATT, now,
                           source=SOURCE_MEASURED), PROBE_OK


# --- 선언된 개체에 실측을 입힌다 ---------------------------------------------


def _declared(measurement: Measurement) -> Measurement:
    """우리가 재지 않은 숫자는 **선언**이다. 출처가 비어 있으면 그렇게 적는다.

    값이 없는 자리는 건드리지 않는다 — 아무도 채우지 않은 것과 "재려 했으나 못
    얻었다"는 서로 다른 사실이고, 선언이라고 적을 근거가 없다.
    """
    if measurement.source is None and measurement.measured:
        return replace(measurement, source=SOURCE_DECLARED)
    return measurement


def _measured_slot(declared: Measurement, measured: Measurement | None) -> Measurement:
    """계측 지점이 지목된 칸. 실측이 있으면 실측, 없으면 `unavailable`.

    **선언값을 실측 자리에 남기지 않는다** — 선언이 "이 칸은 여기서 잰다"고 적었으면
    그 칸에 들어갈 수 있는 것은 측정값뿐이고, 못 쟀을 때 선언 숫자를 그대로 두면 화면은
    그것을 현재 계측으로 읽는다. 값은 없고 **단위는 남는다**: 단위가 사라지면 목표
    기준선을 같은 축에 올릴 수 없다(§4.5).
    """
    if measured is not None and measured.measured:
        return measured
    return _unavailable(declared.unit)


def probe_for(instance_id: str, probe_by_instance: Mapping[str, str] | None,
              known: Mapping[str, object]) -> str | None:
    """그 개체를 어느 계측 지점이 재는가.

    선언이 지목한 것이 먼저다. 지목이 없으면 개체 id 가 계측 지점 id 와 같은
    경우에만 잇는다 — 이름이 같은 것은 우연이 아니라 그 기계를 읽어 만든 선언이다.
    종류(`kind`)나 벤더 라벨로 추측하지 않는다(원칙 #1: 라벨은 분기 근거가 아니다).
    """
    if probe_by_instance and instance_id in probe_by_instance:
        return probe_by_instance[instance_id]
    return instance_id if instance_id in known else None


def resolve_probes(
    declared: LayeredResourceView,
    readout: HostReadout,
    probe_by_instance: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """개체 id → 그 개체를 재는 계측 지점 id. 아무도 재지 않는 개체는 칸이 없다.

    같은 규칙(`probe_for`)을 쓰는 한 자리다 — 어느 개체가 실측인지 판정하는 곳이
    둘이 되면 화면의 출처 표시와 실제 값이 어긋난다(AI-O-06 상태 일관성).
    """
    resolved = {}
    for accelerator in declared.accelerators:
        probe_id = probe_for(accelerator.instance_id, probe_by_instance, readout.accelerators)
        if probe_id is not None:
            resolved[accelerator.instance_id] = probe_id
    return resolved


def undeclared_probes(
    declared: LayeredResourceView,
    readout: HostReadout,
    probe_by_instance: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """계측기가 찾았는데 **아무 선언도 가리키지 않는** 계측 지점 id.

    implements: AI-O-05 (가속기 목록의 완전성), AI-O-01

    `with_host_measurements` 의 규칙 1 은 목록의 주인을 선언으로 두고 계측이 개체를
    더하지 못하게 한다. 그 규칙은 그대로 옳지만, 지키는 대신 **조용히 버리면** 화면은
    "이 기계에 가속기가 없다"와 "있는데 아무도 선언하지 않았다"를 구별할 수 없다.
    실제 현장 설정(`config/status_ui.json`)에 `dashboard` 선언이 없을 때가 바로 그
    경우다 — 계측기는 `cpu` 와 `gpu-0` 을 읽고 있는데 구역 [E] 는 빈 목록을 낸다.

    그래서 목록을 늘리지 않고 **빠진 사실만** 돌려준다. 이것으로 운영 화면은 선언이
    불완전하다고 말할 수 있고, 메우는 길은 여전히 선언 추가다(문서 §3 요구사항 2).
    목록에 없는 개체를 여기서 만들어 내지 않으므로 선언이 정본이라는 규약은 깨지지
    않는다.
    """
    claimed = set(resolve_probes(declared, readout, probe_by_instance).values())
    return tuple(probe_id for probe_id in readout.accelerators if probe_id not in claimed)


def with_host_measurements(
    declared: LayeredResourceView,
    readout: HostReadout,
    *,
    probe_by_instance: Mapping[str, str] | None = None,
    board_probe: str | None = None,
) -> LayeredResourceView:
    """선언된 L1 목록의 **같은 자리에** 실측을 입힌 새 스냅샷.

    implements: AI-O-05 (계층별 자원 관측), AI-O-01, AI-C-05

    세 규칙만 지킨다.

    1. 개체는 선언이 정한다 — 실측이 **목록을 늘리거나 줄이지 않는다**(§4.1 완전성).
       계측기가 찾았지만 선언에 없는 것은 여기서 더하지 않는다. 그것은 설정이 할 일이고
       (`host_probe` 로 선언을 추가한다), 화면에 없던 장치가 임의로 생기면 선언이
       정본이라는 §3 요구사항 2 가 깨진다.
    2. 지목된 칸은 실측이거나 `unavailable` 이다 — 선언 숫자가 실측 자리를 채우지 않는다.
    3. 지목이 없는 칸은 선언값이 남고 **선언이라고 적힌다**. 0 은 어디에도 넣지 않는다.
    """
    merged = []
    for accelerator in declared.accelerators:
        probe_id = probe_for(accelerator.instance_id, probe_by_instance, readout.accelerators)
        measured = readout.accelerators.get(probe_id) if probe_id else None
        if probe_id is None:
            # 아무도 이 개체를 재지 않는다. 선언을 선언이라고만 적고 그대로 둔다.
            merged.append(replace(
                accelerator,
                utilization=_declared(accelerator.utilization),
                temperature=_declared(accelerator.temperature),
            ))
            continue
        merged.append(replace(
            accelerator,
            # 종류·부착 형태는 선언이 소유한다. 계측기가 본 제품명은 선언에 라벨이
            # 없을 때만 채운다 — 라벨은 표시용이고 선언을 덮을 근거가 아니다.
            vendor_label=(accelerator.vendor_label
                          or (measured.vendor_label if measured else None)),
            utilization=_measured_slot(accelerator.utilization,
                                       measured.utilization if measured else None),
            temperature=_measured_slot(accelerator.temperature,
                                       measured.temperature if measured else None),
        ))

    board = declared.board
    if board_probe is None:
        board = BoardResources(
            memory_utilization=_declared(board.memory_utilization),
            power=_declared(board.power),
            power_trend=tuple(_declared(s) for s in board.power_trend),
        )
    else:
        measured_board = readout.board if board_probe == BOARD_PROBE_ID else None
        power = _measured_slot(board.power, measured_board.power if measured_board else None)
        board = BoardResources(
            memory_utilization=_measured_slot(
                board.memory_utilization,
                measured_board.memory_utilization if measured_board else None),
            power=power,
            # 추이도 현재값과 같은 출처여야 한다. 실측 전력 옆에 선언된 추이를 붙이면
            # 화면이 선언된 과거에서 실측된 현재로 이어지는 선을 그린다. 못 쟀으면
            # 추이도 없다 — 없는 선을 그리지 않는다.
            power_trend=(measured_board.power_trend if measured_board else ()),
        )
    return replace(declared, accelerators=tuple(merged), board=board)
