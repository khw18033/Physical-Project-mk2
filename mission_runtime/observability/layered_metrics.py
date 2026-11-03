"""Layer-1 accelerator instances and Layer-2 service indicators, kept apart,
with three-valued target evaluation (met / unmet / not measured).

implements: AI-O-05 (계층별 자원·서비스 지표 관측)
관련: AI-O-01 (실행 성능·자원 관측, 엣지 상세 / 서버 요약), AI-B-01 (미측정 항목 구분),
      AI-B-04 (자원 등록), AI-C-04 (벤더 중립)

요구사항 출처는 `docs/20260928-종합상황정보_Dashboard_기능정의서_2.docx` §1.2·§4.4·§4.5
이며, 2026-10-27 에 요구사항 시트에 등재했다(CLAUDE.md §5).

기존 관측과 무엇이 다른가
-------------------------
`observability/metrics.py` 는 이름이 붙은 수치 표본을 모아 요약한다. 거기에는
**가속기 개체**라는 것이 없다 — 실행 조건은 `compute.gpu` 같은 자유 태그이고 같은
종류의 가속기가 여러 개일 때 서로 구분되지 않는다. 문서 §4.4 는 "가속기별 사용률·온도"
와 "미할당·유휴 가속기도 목록에서 생략하지 않는다"를 요구하므로 **개체 식별**이 필요하다.
그래서 태그(무엇을 할 수 있는가)와 인스턴스(어느 물건인가)를 분리해 더한다.

벤더 중립 (절대 준수 원칙 #1)
-----------------------------
`kind`·`attachment`·`vendor_label` 은 전부 **등록 데이터로 들어오는 자유 문자열**이고
이 모듈에 enum 이나 분기가 없다. 문서가 예시로 든 제품명은 `vendor_label` 에 담아
화면이 그대로 표시할 수 있지만, 어떤 로직도 그 값으로 갈라지지 않는다.

측정 없음 ≠ 0 (문서 §4.4·§4.5)
------------------------------
"서비스가 대기 상태여서 지표가 산출되지 않는 경우, 0 이 아니라 측정 없음으로 표시",
"지표가 산출되지 않는 구간은 '미달'이 아니라 측정 없음으로 구분". 그래서 측정값은
`Measurement` 로 감싸 값 없음을 1급 상태로 두고, 목표 충족 판정은 **3값**이다.

값의 출처 (AI-O-05 · AI-C-01)
-----------------------------
같은 자리에 들어오는 숫자가 **이 기계에서 읽은 값**일 수도 있고 **등록·선언 데이터**일
수도 있다. 둘을 구분하지 않으면 화면은 선언된 예시를 계측으로 읽는다 — 2026-11-03
감사가 적은 결손이 바로 이것이었다. 그래서 `Measurement.source` 를 값의 유무와 **다른
축**으로 둔다.

| source | 뜻 | 값 칸 |
|---|---|---|
| `measured` | 계측기가 이 호스트에서 실제로 읽었다 | 있다 |
| `declared` | 선언·등록 데이터다(사전정보, AI-S-08) | 있다 |
| `unavailable` | 재려 했으나 얻지 못했다(도구 없음·권한·시간초과) | **없다** |
| `None` | 아무도 그 자리를 채우지 않았다 | 없다 |

`unavailable` 과 `None` 은 둘 다 미측정이지만 서로 다른 사실이다 — 전자는 계측을
시도했다는 뜻이고 후자는 시도조차 없었다는 뜻이다. 어느 쪽도 0 이 아니다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


#: 이 호스트에서 계측기가 실제로 읽은 값.
SOURCE_MEASURED = "measured"
#: 선언·등록 데이터에서 온 값. 숫자가 있어도 계측이 아니다.
SOURCE_DECLARED = "declared"
#: 계측을 시도했지만 얻지 못했다. 값 칸은 비어 있고 0 이 아니다.
SOURCE_UNAVAILABLE = "unavailable"
#: 등재된 출처 어휘. `None`(아무도 채우지 않음)은 값이 아니라 부재이므로 여기 없다.
MEASUREMENT_SOURCES: tuple[str, ...] = (
    SOURCE_MEASURED, SOURCE_DECLARED, SOURCE_UNAVAILABLE,
)


class MeetState(str, Enum):
    """목표 기준선 충족 여부. 세 값이며 둘로 줄이지 않는다.

    MET          기준을 만족한다
    UNMET        기준에 미달한다
    NOT_MEASURED 측정값이 없다 — **미달이 아니다**
    """

    MET = "MET"
    UNMET = "UNMET"
    NOT_MEASURED = "NOT_MEASURED"


class Direction(str, Enum):
    """목표가 하한인지 상한인지. FPS 는 하한, 지연은 상한이다."""

    AT_LEAST = "AT_LEAST"
    AT_MOST = "AT_MOST"


class UnitMismatch(Exception):
    """측정값과 목표의 단위가 다르다.

    문서 §4.5: "목표 기준선은 그래프상 실제 값 위치에 표시되어야 한다. 위치가
    임의로 고정된 기준선은 허용되지 않는다." 단위가 어긋난 기준선은 그 위치를
    정할 수 없으므로 조립 시점에 거부한다.
    """


@dataclass(frozen=True)
class Measurement:
    """한 번의 계측. 값이 없으면 `value is None` 이고 그것이 정상 상태다."""

    value: float | None
    unit: str
    at: float | None = None
    #: 이 값이 어디서 왔는가(`MEASUREMENT_SOURCES`). `None` 은 아무도 채우지 않은
    #: 자리다 — 소비자가 계측과 선언을 **추측하지 않고** 가를 수 있게 하는 축이다.
    source: str | None = None

    @property
    def measured(self) -> bool:
        return self.value is not None

    @property
    def from_host(self) -> bool:
        """이 호스트에서 실제로 읽은 값인가. 숫자의 유무와 다른 질문이다."""
        return self.source == SOURCE_MEASURED

    @staticmethod
    def not_measured(unit: str, *, source: str | None = None) -> Measurement:
        """값 없는 측정. `source=SOURCE_UNAVAILABLE` 이면 "재려 했으나 못 얻었다"다."""
        return Measurement(None, unit, source=source)


@dataclass(frozen=True)
class TargetBaseline:
    """지표 하나의 목표값. 화면은 이것을 실제 값과 같은 축에 올려 그린다."""

    value: float
    direction: Direction
    unit: str

    def evaluate(self, measurement: Measurement) -> MeetState:
        if measurement.unit != self.unit:
            raise UnitMismatch(
                f"target is in {self.unit!r} but the measurement is in {measurement.unit!r}"
            )
        if not measurement.measured:
            return MeetState.NOT_MEASURED
        assert measurement.value is not None
        if self.direction is Direction.AT_LEAST:
            return MeetState.MET if measurement.value >= self.value else MeetState.UNMET
        return MeetState.MET if measurement.value <= self.value else MeetState.UNMET


@dataclass(frozen=True)
class Indicator:
    """주요 성능 지표 1개 (문서 §4.5).

    지표명만으로는 어느 서비스·가속기의 수치인지 알 수 없으므로 산출 서비스와
    가속기를 함께 들고 다닌다("추론 FPS (VLA / XDNA)" 같은 표기를 화면이 만들 수
    있도록 — 값은 전부 id 이고 표시 문구는 화면이 조립한다).
    """

    name: str
    measurement: Measurement
    service_id: str | None = None
    accelerator_id: str | None = None
    target: TargetBaseline | None = None
    #: 최근 구간 추이. 비어 있으면 추세를 그리지 않는다(없는 선을 그리지 않는다).
    trend: tuple[Measurement, ...] = ()

    def __post_init__(self) -> None:
        if self.target is not None and self.target.unit != self.measurement.unit:
            raise UnitMismatch(
                f"{self.name}: target unit {self.target.unit!r} != "
                f"measurement unit {self.measurement.unit!r}"
            )
        for sample in self.trend:
            if sample.unit != self.measurement.unit:
                raise UnitMismatch(
                    f"{self.name}: trend sample unit {sample.unit!r} != "
                    f"measurement unit {self.measurement.unit!r}"
                )

    @property
    def meet_state(self) -> MeetState:
        if self.target is None:
            return MeetState.NOT_MEASURED if not self.measurement.measured else MeetState.MET
        return self.target.evaluate(self.measurement)

    def measured_trend(self) -> tuple[Measurement, ...]:
        """값이 있는 표본만. 빈 구간을 0 으로 메우지 않는다."""
        return tuple(s for s in self.trend if s.measured)

    def series_range(self) -> tuple[float, float] | None:
        """추이와 목표선을 같은 축에 올리기 위한 값 범위. 측정이 없으면 None.

        목표선을 임의 위치에 고정하지 못하게 하려면 화면이 실제 값 범위를 알아야
        한다. 목표값이 범위 밖이면 그것까지 포함해 돌려준다 — 기준선이 화면 밖으로
        밀려 보이지 않는 일을 막는다.
        """
        values = [s.value for s in self.measured_trend() if s.value is not None]
        if self.measurement.measured and self.measurement.value is not None:
            values.append(self.measurement.value)
        if not values:
            return None
        lo, hi = min(values), max(values)
        if self.target is not None:
            lo, hi = min(lo, self.target.value), max(hi, self.target.value)
        return (lo, hi)


@dataclass(frozen=True)
class AcceleratorInstance:
    """Layer 1 가속기 **개체** 1개 (문서 §1.2·§4.4).

    `kind`·`attachment`·`vendor_label` 은 등록 데이터이고 분기 근거가 아니다.
    사용률·온도는 `Measurement` 라 못 잰 상태를 0 으로 내지 않는다.
    """

    instance_id: str
    #: 자유 문자열. 예: "cpu" / "integrated_gpu" / "npu". enum 으로 좁히지 않는다.
    kind: str
    #: 자유 문자열. 예: "builtin" / "external". 내장·외장 구분을 화면이 쓰되
    #: 이 모듈은 값으로 갈라지지 않는다.
    attachment: str | None = None
    #: 표시용 제품 라벨. 핵심 로직은 이 값을 읽지 않는다(원칙 #1).
    vendor_label: str | None = None
    utilization: Measurement = Measurement(None, "ratio")
    temperature: Measurement = Measurement(None, "celsius")

    def __post_init__(self) -> None:
        if not self.instance_id:
            raise ValueError("instance_id must not be empty")
        if self.utilization.value is not None and not 0.0 <= self.utilization.value <= 1.0:
            raise ValueError(f"utilization out of range: {self.utilization.value}")


@dataclass(frozen=True)
class ServiceRuntime:
    """Layer 2 서비스 1개 (문서 §1.2·§4.4).

    `accelerator_id` 는 **필수 표기**다 — 문서 §4.4: "서비스 카드에는 반드시 배치
    가속기가 병기되어야 한다. 서비스 지연이 모델의 문제인지 가속기의 문제인지를 이
    화면에서 좁힐 수 있어야 한다." 아직 배치되지 않았으면 None 이고, 그 None 자체가
    "미배치"라는 정보다(빈 문자열로 가리지 않는다).
    """

    service_id: str
    accelerator_id: str | None
    role: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    indicators: tuple[Indicator, ...] = ()

    def __post_init__(self) -> None:
        if not self.service_id:
            raise ValueError("service_id must not be empty")
        for ind in self.indicators:
            if ind.accelerator_id is not None and ind.accelerator_id != self.accelerator_id:
                raise ValueError(
                    f"{self.service_id}: indicator {ind.name} claims accelerator "
                    f"{ind.accelerator_id!r} but the service runs on {self.accelerator_id!r}"
                )

    def indicator(self, name: str) -> Indicator:
        for ind in self.indicators:
            if ind.name == name:
                return ind
        raise KeyError(name)


@dataclass(frozen=True)
class BoardResources:
    """보드 수준 자원 (문서 §4.4 "보드 메모리", "소비 전력")."""

    memory_utilization: Measurement = Measurement(None, "ratio")
    power: Measurement = Measurement(None, "watt")
    #: 전력·사용률처럼 변동하는 항목의 최근 구간 추이.
    power_trend: tuple[Measurement, ...] = ()


@dataclass(frozen=True)
class LayeredResourceView:
    """L1 과 L2 를 **명시적으로 구분해** 담은 조회 전용 스냅샷.

    문서 §4.4: "본 구역은 Layer 1 과 Layer 2 를 명시적으로 구분하여 표시한다."
    두 계층을 한 목록에 섞지 않는 것이 이 자료구조의 존재 이유다.
    """

    accelerators: tuple[AcceleratorInstance, ...] = ()
    services: tuple[ServiceRuntime, ...] = ()
    board: BoardResources = BoardResources()

    def __post_init__(self) -> None:
        ids = [a.instance_id for a in self.accelerators]
        if len(ids) != len(set(ids)):
            raise ValueError(
                f"duplicate accelerator ids: {sorted({i for i in ids if ids.count(i) > 1})}"
            )
        known = set(ids)
        for svc in self.services:
            if svc.accelerator_id is not None and svc.accelerator_id not in known:
                raise ValueError(
                    f"{svc.service_id} is placed on unknown accelerator {svc.accelerator_id!r}"
                )

    # -- 가속기 목록의 완전성 (문서 §4.1·§4.4) ---------------------------

    def services_on(self, instance_id: str) -> tuple[ServiceRuntime, ...]:
        return tuple(s for s in self.services if s.accelerator_id == instance_id)

    def idle_accelerators(self) -> tuple[AcceleratorInstance, ...]:
        """배치된 서비스가 없는 가속기. **목록에서 빼지 않고** 유휴로 드러낸다.

        문서 §4.1: "미할당 가속기는 목록에서 생략하지 않고 미할당 상태로 표시한다."
        자원 여유를 판단하려면 목록이 완전해야 한다.
        """
        return tuple(a for a in self.accelerators if not self.services_on(a.instance_id))

    def placement(self) -> dict[str, tuple[str, ...]]:
        """가속기 → 배치 서비스. **가속기를 기준 축으로** 돌려준다.

        문서 §4.1 이 방향을 못박았다: "가속기를 기준 축으로 삼아야 유휴 가속기가
        드러나며, 부하 편중을 판단할 수 있다." 그래서 서비스→가속기 방향의 dict 를
        내지 않는다.
        """
        return {
            a.instance_id: tuple(s.service_id for s in self.services_on(a.instance_id))
            for a in self.accelerators
        }

    def unmeasured_accelerators(self) -> tuple[str, ...]:
        """사용률을 못 잰 가속기. 화면은 이것을 0% 로 그리지 않는다."""
        return tuple(a.instance_id for a in self.accelerators if not a.utilization.measured)

    def host_measured_accelerators(self) -> tuple[str, ...]:
        """사용률을 **이 호스트에서 실제로 읽은** 가속기 (AI-O-05).

        `unmeasured_accelerators` 의 여집합이 아니다 — 선언된 숫자가 있는 가속기는
        둘 중 어디에도 들지 않는다. 그 셋을 한 축으로 합치면 계측과 선언이 같아진다.
        """
        return tuple(a.instance_id for a in self.accelerators if a.utilization.from_host)

    def indicators(self) -> tuple[Indicator, ...]:
        return tuple(ind for s in self.services for ind in s.indicators)

    def unmet_indicators(self) -> tuple[Indicator, ...]:
        """목표 미달 지표만. 측정 없음은 여기 들어오지 않는다."""
        return tuple(i for i in self.indicators() if i.meet_state is MeetState.UNMET)

    def not_measured_indicators(self) -> tuple[Indicator, ...]:
        return tuple(i for i in self.indicators() if i.meet_state is MeetState.NOT_MEASURED)

    # -- 구성 변경 (항상 새 스냅샷) --------------------------------------

    def with_accelerator(self, instance: AcceleratorInstance) -> LayeredResourceView:
        """가속기가 추가·교체되어도 화면 구조를 바꾸지 않는다(문서 §3·§5 구성 가변성).

        같은 id 면 갈아끼우고 없으면 더한다.
        """
        existing = [a.instance_id for a in self.accelerators]
        if instance.instance_id in existing:
            return replace(self, accelerators=tuple(
                instance if a.instance_id == instance.instance_id else a
                for a in self.accelerators
            ))
        return replace(self, accelerators=self.accelerators + (instance,))

    def with_service(self, service: ServiceRuntime) -> LayeredResourceView:
        existing = [s.service_id for s in self.services]
        if service.service_id in existing:
            return replace(self, services=tuple(
                service if s.service_id == service.service_id else s for s in self.services
            ))
        return replace(self, services=self.services + (service,))
