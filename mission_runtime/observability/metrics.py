"""Execution performance/resource observation with edge detail + server
summary (AI-O-01).

implements: AI-O-01

General numeric metrics may be summarized before reaching the server,
but individual device liveness / fatal-error state must never be lost
inside that summary (AI-O-01: "개별 장치의 생사와 치명적 오류처럼 집계
과정에서 사라지면 안 되는 상태는 일반 수치 요약과 분리해 개별 상태로
유지해야 한다").
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricSample:
    name: str
    value: float
    at: float


@dataclass(frozen=True)
class MetricSummary:
    name: str
    count: int
    avg: float
    max: float
    min: float


class EdgeMetricStore:
    """Keeps full detail at the edge; `summarize()` is what would be
    forwarded to the server as a summary — the raw detail never leaves
    this store on its own.
    """

    def __init__(self) -> None:
        self._samples: dict[str, list[MetricSample]] = {}
        self._individual_state: dict[str, str] = {}

    def record(self, name: str, value: float, at: float) -> None:
        self._samples.setdefault(name, []).append(MetricSample(name, value, at))

    def detail(self, name: str) -> list[MetricSample]:
        return list(self._samples.get(name, []))

    def summarize(self, name: str) -> MetricSummary | None:
        samples = self._samples.get(name)
        if not samples:
            return None
        values = [s.value for s in samples]
        return MetricSummary(name, len(values), sum(values) / len(values), max(values), min(values))

    def set_individual_state(self, device_id: str, state: str) -> None:
        """Individual device liveness/fatal state — never folded into
        `summarize()`, always queried on its own."""
        self._individual_state[device_id] = state

    def individual_state(self, device_id: str) -> str | None:
        return self._individual_state.get(device_id)
