"""재접속 재동기화 — **놓친 것을 아는 것**이 놓치지 않는 것보다 먼저다.

implements: AI-O-06 (통합 운영 상태 뷰 — 한 번도 안 온 것과 오래된 것의 구분),
            AI-C-06 (전송 경계), AI-C-03 (처리 순서)
관련: AI-C-20 (중복 재전달), AI-C-05, AI-O-04
tests: tests/test_event_cursor.py

## 메우는 구멍

`integration/vz_wire.py` 의 봉투에는 이미 `seq` 가 있다. 그런데 **받는 쪽이 그것을
쓰지 않는다** — 연결이 끊겼다 붙으면 그 사이 것을 그냥 모른 채로 이어 간다. 화면은
조용히 과거를 들고 현재인 척한다.

## 세 가지를 가른다

| 상태 | 뜻 | 할 일 |
|---|---|---|
| `CONTINUOUS` | 번호가 이어졌다 | 없다 |
| `GAP` | 빠진 구간이 있다 | 그 구간만 다시 달라고 한다 |
| `RESET` | 번호가 뒤로 갔다(발행자 재시작) | **전체 스냅샷**을 다시 받는다 |

뒤로 간 번호를 "빠짐" 으로 읽으면 없는 구간을 영원히 조른다. 발행자가 재시작하면
번호가 1 부터 다시 시작할 수 있고, 그것은 손실이 아니라 **다른 세대**다. 그래서
`boot_id` 를 함께 본다 — 번호만으로는 두 사실을 가를 수 없다.

## 중복은 버린다, 순서는 지킨다

이미 본 번호는 처리하지 않는다(AI-C-20 과 같은 규칙). 건너뛴 번호가 오면 **쌓아
두었다가** 빈 자리가 채워질 때 순서대로 낸다 — 뒤를 먼저 내면 받는 쪽의 상태가
거꾸로 간다. 무한정 쌓지 않는다: `max_pending` 을 넘으면 그 사실과 함께 비우고
전체 스냅샷을 요구한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from mission_runtime.contracts import data_dictionary as dd

CONTINUOUS = "continuous"
GAP = "gap"
RESET = "reset"
DUPLICATE = "duplicate"

#: 한 번도 받은 적이 없다. **오래된 것과 다른 사실이다**(AI-O-06).
NEVER_RECEIVED = "never_received"


@dataclass(frozen=True)
class Cursor:
    """어디까지 봤는가. 재접속할 때 이것을 그대로 보낸다."""

    boot_id: str | None = None
    seq: int | None = None

    @property
    def is_fresh(self) -> bool:
        """한 번도 안 받았다. 0 이 아니라 **없음**이다."""
        return self.seq is None

    def as_query(self) -> dict[str, Any]:
        """`?cursor=` 에 실리는 모양. 없으면 비어 있고 0 을 보내지 않는다."""
        if self.is_fresh:
            return {}
        return {dd.BOOT_ID: self.boot_id, "seq": self.seq}

    @classmethod
    def from_query(cls, raw: dict[str, Any] | None) -> "Cursor":
        if not raw:
            return cls()
        seq = raw.get("seq")
        return cls(boot_id=raw.get("boot_id") or None,
                   seq=int(seq) if seq is not None else None)


@dataclass(frozen=True)
class Delivery:
    """봉투 하나를 받은 결과. **낼 것과 요구할 것**이 함께 나온다."""

    state: str
    deliver: tuple[dict[str, Any], ...] = ()
    missing_from: int | None = None
    missing_to: int | None = None
    reason: str = ""

    @property
    def needs_snapshot(self) -> bool:
        return self.state == RESET


@dataclass
class EventCursor:
    """받는 쪽의 순서·결손 판정. **전송을 모른다** — WS 든 SSE 든 같다.

    판정만 하고 다시 달라고 보내지는 않는다. 어디로 어떻게 요청하는지는 전송
    provider 의 몫이다(AI-C-06).
    """

    max_pending: int = 256
    boot_id: str | None = None
    last_seq: int | None = None
    pending: dict[int, dict[str, Any]] = field(default_factory=dict)
    #: 겪은 일들. 「상태 반영 지연」·「복구 시간」의 재료가 된다.
    gaps_seen: list[tuple[int, int]] = field(default_factory=list)
    resets_seen: int = 0
    duplicates_dropped: int = 0

    @property
    def cursor(self) -> Cursor:
        return Cursor(self.boot_id, self.last_seq)

    def receive(self, envelope: dict[str, Any]) -> Delivery:
        """봉투 하나. 돌려받은 `deliver` 만 윗단에 넘긴다."""
        boot_id = envelope.get("boot_id")
        seq = envelope.get("seq")
        if seq is None:
            # 번호가 없는 봉투는 순서를 말하지 않는다 — 그대로 통과시킨다
            return Delivery(CONTINUOUS, (envelope,), reason="no_sequence")
        seq = int(seq)

        if self.boot_id is not None and boot_id is not None and boot_id != self.boot_id:
            return self._reset(boot_id, seq, "publisher_restarted")

        if self.last_seq is None:
            self.boot_id, self.last_seq = boot_id, seq
            return Delivery(CONTINUOUS, (envelope,), reason=NEVER_RECEIVED)

        if seq <= self.last_seq:
            if seq in self.pending:
                self.pending.pop(seq, None)
            self.duplicates_dropped += 1
            return Delivery(DUPLICATE, (), reason="already_seen")

        if seq == self.last_seq + 1:
            self.last_seq = seq
            out = [envelope, *self._drain_contiguous()]
            return Delivery(CONTINUOUS, tuple(out))

        # 건너뛰었다 — 쌓아 두고 **빠진 구간을 말한다**
        self.pending[seq] = envelope
        if len(self.pending) > self.max_pending:
            return self._reset(boot_id, seq, "too_many_pending")
        missing = (self.last_seq + 1, seq - 1)
        self.gaps_seen.append(missing)
        return Delivery(GAP, (), missing_from=missing[0], missing_to=missing[1],
                        reason="sequence_skipped")

    def accept_backfill(self, envelopes: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
        """다시 받은 구간을 넣는다. 자리가 채워지면 **순서대로** 나온다."""
        for envelope in envelopes:
            seq = envelope.get("seq")
            if seq is None:
                continue
            seq = int(seq)
            if self.last_seq is not None and seq <= self.last_seq:
                self.duplicates_dropped += 1
                continue
            self.pending[seq] = envelope
        return tuple(self._drain_contiguous())

    def adopt_snapshot(self, *, boot_id: str | None, seq: int | None) -> Cursor:
        """전체 스냅샷을 받았다. 쌓아 둔 조각은 **버린다** — 스냅샷이 더 새것이다."""
        self.boot_id, self.last_seq = boot_id, seq
        self.pending.clear()
        return self.cursor

    def freshness(self) -> str:
        """한 번도 안 받았는지. 「미수신」과 「오래됨」은 다른 사실이다(AI-O-06)."""
        return NEVER_RECEIVED if self.last_seq is None else "received"

    # --- 내부 -------------------------------------------------------------
    def _drain_contiguous(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        while self.last_seq is not None and (self.last_seq + 1) in self.pending:
            self.last_seq += 1
            out.append(self.pending.pop(self.last_seq))
        return out

    def _reset(self, boot_id: str | None, seq: int, reason: str) -> Delivery:
        self.resets_seen += 1
        self.pending.clear()
        self.boot_id, self.last_seq = boot_id, seq
        return Delivery(RESET, (), reason=reason)


def resume_query(cursor: Cursor) -> dict[str, Any]:
    """재접속 요청에 실을 것. **없으면 비어 있다** — 0 을 보내면 처음부터 다시 받는다."""
    return cursor.as_query()
