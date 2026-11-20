"""정량 목표와 그 판정 — **숫자가 없으면 좋아졌는지 말할 수 없다.**

implements: AI-O-01 (실행 성능·자원 관측), AI-O-05 (목표 기준선과 충족 여부),
            AI-B-01 (미측정 항목 구분)
관련: AI-C-13 (동일 조건 비교), AI-L-05 (회귀 검증), AI-O-06
tests: tests/test_slo.py

## 메우는 구멍

이 저장소는 "무엇이 옳은가" 를 깐깐하게 적어 왔지만 **얼마나 빠른가·얼마나
자주 틀리는가** 에는 목표가 하나도 없었다. 그래서 정책을 바꿔도 좋아졌는지
말할 수 없고, 회귀가 생겨도 그것이 회귀인지 알 수 없다.

## 세 값이지 두 값이 아니다

충족 / 미달 / **미측정**. 재지 않은 것을 미달로 적으면 고칠 것이 없는데 빨간
줄이 서고, 0 으로 적으면 고쳐야 하는데 초록이 선다(AI-O-05). 그래서 판정은
`MET` · `MISSED` · `UNMEASURED` 셋이고, 표본이 모자라면 **미측정**이다.

## 백분위는 평균이 아니다

P95 를 쓰는 이유: 평균은 꼬리를 감춘다. 운영자가 겪는 것은 평균이 아니라 꼬리다.
표본이 적으면 P95 는 뜻이 없으므로 `min_samples` 아래에서는 재지 않았다고 말한다.

## 목표값은 **선언이다**

`SLO_TARGETS` 의 숫자는 PDF 설계서가 제안한 값이고 **실측이 아니다.** 파일럿에서
재고 나서 고친다. 그때 고치는 자리는 이 표 하나이고 판정 코드는 바뀌지 않는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from mission_runtime.contracts import data_dictionary as dd

MET = "met"
MISSED = "missed"
UNMEASURED = "unmeasured"

#: 비교 방향. 지연은 작을수록, 성공률은 클수록 좋다.
AT_MOST = "at_most"
AT_LEAST = "at_least"


@dataclass(frozen=True)
class SloTarget:
    """목표 하나. **제안값이며 실측이 아니다** — 파일럿 뒤에 고친다."""

    name: str
    statistic: str                   # "p95" · "p50" · "rate" · "count"
    direction: str                   # AT_MOST · AT_LEAST
    target: float
    unit: str
    min_samples: int = 5
    note: str = ""


#: PDF 캡스톤 설계서 p15·p22 가 제안한 값을 우리 어휘로 옮긴 것.
SLO_TARGETS: tuple[SloTarget, ...] = (
    SloTarget("assignment_latency", "p95", AT_MOST, 500.0, "ms",
              note="요청 접수 → 예약 확정. 소규모 LAN 기준"),
    SloTarget("state_reflection_latency", "p95", AT_MOST, 1000.0, "ms",
              note="이벤트 수신 → 화면 반영"),
    SloTarget("mission_success_rate", "rate", AT_LEAST, 0.95, "ratio",
              note="성공 임무 / 제출 임무. 취소·안전 중단은 **따로 센다**"),
    SloTarget("duplicate_executions", "count", AT_MOST, 0.0, "건",
              min_samples=1,
              note="같은 command_id 가 물리로 두 번 간 횟수. 0 이 아니면 AI-C-20 위반"),
    SloTarget("reservation_conflicts", "count", AT_MOST, 0.0, "건",
              min_samples=1,
              note="배타 자원을 둘이 동시에 쥔 횟수. 거절은 충돌이 아니다"),
    SloTarget("recovery_time", "p95", AT_MOST, 30000.0, "ms",
              note="연결 회복 → 상태 일치"),
)


def percentile(samples: list[float], fraction: float) -> float | None:
    """선형 보간 백분위. 표본이 없으면 **None 이고 0 이 아니다.**"""
    if not samples:
        return None
    ordered = sorted(samples)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


@dataclass(frozen=True)
class Verdict:
    """판정 하나. **세 값**이고 사유가 붙는다."""

    name: str
    state: str
    measured: float | None
    target: float
    unit: str
    samples: int
    reason: str = ""

    @property
    def met(self) -> bool:
        return self.state == MET


@dataclass
class SloRecorder:
    """표본을 모으고 판정한다. **판정을 두 번 하지 않는다** — 재는 자리는 여기 하나다.

    관측 실패가 측정 대상을 멈추면 안 되므로(AI-O-01) 모든 입력은 조용히 받고,
    모자람은 숫자가 아니라 **미측정**으로 드러난다.
    """

    targets: tuple[SloTarget, ...] = SLO_TARGETS
    samples: dict[str, list[float]] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    outcomes: dict[str, int] = field(default_factory=dict)

    # --- 넣기 -------------------------------------------------------------
    def observe(self, name: str, value: float) -> None:
        """지연 같은 연속값 하나."""
        self.samples.setdefault(name, []).append(float(value))

    def count(self, name: str, amount: int = 1) -> None:
        """있으면 안 되는 사건. **0 이 기본값이 아니라 '아직 안 셌다' 가 기본이다.**"""
        self.counters[name] = self.counters.get(name, 0) + amount

    def start_counting(self, name: str) -> None:
        """「0 건」을 주장하려면 **센 적이 있어야 한다.** 그 사실을 여기서 연다."""
        self.counters.setdefault(name, 0)

    def record_outcome(self, name: str, *, ok: bool) -> None:
        """성공률의 분자·분모. 취소·안전 중단은 부르는 쪽이 따로 센다."""
        self.outcomes[f"{name}.total"] = self.outcomes.get(f"{name}.total", 0) + 1
        if ok:
            self.outcomes[f"{name}.ok"] = self.outcomes.get(f"{name}.ok", 0) + 1

    # --- 판정 -------------------------------------------------------------
    def verdict(self, target: SloTarget) -> Verdict:
        measured, samples = self._measure(target)
        if measured is None:
            return Verdict(target.name, UNMEASURED, None, target.target,
                           target.unit, samples,
                           reason="표본이 없다" if samples == 0
                           else f"표본 {samples} < 최소 {target.min_samples}")
        ok = (measured <= target.target if target.direction == AT_MOST
              else measured >= target.target)
        return Verdict(target.name, MET if ok else MISSED, measured,
                       target.target, target.unit, samples)

    def verdicts(self) -> tuple[Verdict, ...]:
        return tuple(self.verdict(target) for target in self.targets)

    def summary(self) -> dict[str, int]:
        """충족·미달·미측정을 **따로** 센다. 합치면 셋 중 둘이 사라진다."""
        found = {MET: 0, MISSED: 0, UNMEASURED: 0}
        for verdict in self.verdicts():
            found[verdict.state] += 1
        return found

    def as_rows(self) -> list[dict[str, object]]:
        """운영 화면이 읽는 모양. 색·픽셀은 여기 없다(view-contract 와 같은 규칙)."""
        return [{
            dd.SLO_ID: v.name,
            dd.SLO_VERDICT: v.state,
            "measured": v.measured,
            "target": v.target,
            "unit": v.unit,
            "samples": v.samples,
            "reason": v.reason,
        } for v in self.verdicts()]

    # --- 내부 -------------------------------------------------------------
    def _measure(self, target: SloTarget) -> tuple[float | None, int]:
        if target.statistic == "count":
            if target.name not in self.counters:
                return None, 0                    # **세지 않은 것은 0 건이 아니다**
            return float(self.counters[target.name]), 1
        if target.statistic == "rate":
            total = self.outcomes.get(f"{target.name}.total", 0)
            if total < target.min_samples:
                return None, total
            return self.outcomes.get(f"{target.name}.ok", 0) / total, total
        values = self.samples.get(target.name, [])
        if len(values) < target.min_samples:
            return None, len(values)
        fraction = 0.95 if target.statistic == "p95" else 0.5
        return percentile(values, fraction), len(values)


def compare(before: SloRecorder, after: SloRecorder) -> list[dict[str, object]]:
    """두 실행을 **같은 기준**으로 견준다(AI-C-13 · AI-L-05).

    한쪽이 미측정이면 「좋아졌다」고 말하지 않는다 — 비교할 수 없다고 말한다.
    """
    rows: list[dict[str, object]] = []
    after_by_name = {v.name: v for v in after.verdicts()}
    for old in before.verdicts():
        new = after_by_name.get(old.name)
        if new is None:
            continue
        if old.measured is None or new.measured is None:
            rows.append({dd.SLO_ID: old.name, "change": None,
                         "reason": "한쪽이 미측정이라 견줄 수 없다"})
            continue
        rows.append({
            dd.SLO_ID: old.name,
            "before": old.measured,
            "after": new.measured,
            "change": new.measured - old.measured,
            "regressed": (new.state == MISSED and old.state == MET),
        })
    return rows
