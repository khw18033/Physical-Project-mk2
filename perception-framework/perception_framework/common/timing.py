"""Frame reference, observation time and local processing order.

implements: AI-C-03

AI-C-03: "영상·센서 입력과 파생 결과는 원본 관측을 다시 찾을 수 있는 참조와 측정
시각, 처리 순서를 유지해야 한다 ... 시간 동기화가 일시적으로 깨져도 단일 노드의
로컬 처리와 순서는 유지하되 노드 간 정합이 필요한 기능은 정확도가 저하된 상태로
처리해야 한다."

Two clocks are kept apart on purpose:
  - `observed_at`: the synchronised wall-clock reading (NTP today, per
    BE-C-03). Usable for cross-node fusion only while sync is healthy.
  - `local_sequence`: a strictly increasing per-node counter that never
    depends on the wall clock, so single-node ordering survives a sync
    outage untouched.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class TimeSyncState(str, Enum):
    """Health of this node's clock synchronisation."""

    SYNCED = "SYNCED"
    DEGRADED = "DEGRADED"  # sync lost/uncertain -> cross-node fusion is degraded, local work continues


@dataclass(frozen=True)
class FrameReference:
    """Identifies one original observation so it can be found again.

    Carried by every derived result (detection, track, risk verdict) so
    overlay rendering, latency measurement and error reproduction all
    resolve back to the same input (AI-O-03, VZ-I-07).
    """

    source_id: str
    frame_id: str
    observed_at: float
    local_sequence: int
    sync_state: TimeSyncState = TimeSyncState.SYNCED

    def supports_cross_node_fusion(self) -> bool:
        """Cross-node/multi-source alignment needs a trustworthy common
        time base; local processing does not (AI-C-03).
        """
        return self.sync_state is TimeSyncState.SYNCED


class FrameReferenceFactory:
    """Stamps observations with a reference, keeping local order intact
    regardless of clock health.

    `clock` is injectable so a test can freeze, rewind or corrupt the wall
    clock without the local ordering guarantee changing.
    """

    def __init__(self, source_id: str, clock: Callable[[], float] | None = None) -> None:
        self._source_id = source_id
        self._clock = clock or __import__("time").time
        self._counter = itertools.count()
        self._sync_state = TimeSyncState.SYNCED

    def set_sync_state(self, state: TimeSyncState) -> None:
        """Reported by whatever monitors NTP; this module does not probe it."""
        self._sync_state = state

    def next_reference(self, frame_id: str) -> FrameReference:
        return FrameReference(
            source_id=self._source_id,
            frame_id=frame_id,
            observed_at=self._clock(),
            local_sequence=next(self._counter),
            sync_state=self._sync_state,
        )


@dataclass
class DerivedResult:
    """Any AI output, always bound to the observation it came from."""

    reference: FrameReference
    payload: object
    produced_by: str = ""
    versions: dict[str, str] = field(default_factory=dict)


def in_local_order(results: list[DerivedResult]) -> list[DerivedResult]:
    """Order results by the node-local counter, never by wall clock.

    A backwards clock jump during a sync outage must not reorder a single
    node's own processing sequence (AI-C-03).
    """
    return sorted(results, key=lambda r: r.reference.local_sequence)
