"""내구 저장과 Outbox — **판정이 재시작을 넘어가게 한다.**

implements: AI-B-05 (last-known-good 복구), AI-L-08 (학습·적용 계보 추적),
            AI-O-03 (오류 재현 정보), AI-C-04 (provider 경계), AI-C-16 (폐쇄망)
관련: AI-C-06 (전송 경계), AI-C-01 (공통 데이터 규약), AI-C-05
tests: tests/test_durable_store.py

## 메우는 구멍

`runtime/mlops_pipeline.py` 는 배정·배포·롤백을 **옳게** 판정하는데 그 기록이
`self._records` 딕셔너리에만 있다. 프로세스가 죽으면 "마지막 정상 버전" 이 함께
사라지고, AI-B-05 가 요구하는 last-known-good 복구는 말뿐이 된다. 재현(AI-O-03)과
계보(AI-L-08)도 같은 자리에서 끊긴다.

## 두 가지를 **한 트랜잭션**으로 묶는다

사실을 쓰는 것과 "그 사실을 바깥에 알리겠다" 를 적는 것이 갈라지면 둘 중 하나가
빠진다 — 상태는 바뀌었는데 아무도 모르거나, 알렸는데 상태가 없다. 그래서 기록과
발행 예약(outbox)을 같은 커밋에 넣는다.

    with store.transaction() as tx:
        tx.put("deployment", deployment_id, payload)
        tx.enqueue("deployment.applied", aggregate_id=deployment_id, payload=…)
    # 커밋된 뒤에야 publisher 가 outbox 를 비운다

## 전송은 하지 않는다

이 경계는 **쓰고 읽을 뿐** 발행하지 않는다. 어디로 보낼지는 `TransportProvider`
의 몫이다(AI-C-06). `drain()` 이 아직 안 보낸 항목을 주고 `mark_published()` 가
보낸 것을 지운다 — 그 사이에 죽으면 **다시 보낸다**(at-least-once). 그래서 받는
쪽이 `event_id` 로 중복을 접어야 하고, 그것이 AI-C-20 의 멱등성과 같은 규칙이다.

## 없어도 돌아간다

저장 provider 가 없는 배치는 **정상**이다(AI-C-05). `InMemoryDurableStore` 가
같은 계약을 만족하고, 그때 잃는 것은 "재시작을 넘는다" 하나뿐이며 그 사실이
`durability` 로 드러난다 — 있는 척하지 않는다.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol, runtime_checkable

from mission_runtime.contracts import data_dictionary as dd

#: 저장이 재시작을 넘기는가. **"있다/없다" 가 아니라 "무엇을 보장하는가" 다.**
DURABILITY_PROCESS = "process"      # 이 프로세스가 사는 동안만
DURABILITY_RESTART = "restart"      # 재시작을 넘긴다


@dataclass(frozen=True)
class OutboxEvent:
    """발행 예약 한 건. 사실과 **같은 커밋**에 들어간다."""

    event_id: str
    event_type: str
    aggregate_id: str
    payload: dict[str, Any]
    recorded_at: float
    sequence: int

    def as_wire(self) -> dict[str, Any]:
        """받는 쪽이 중복을 접을 수 있는 모양. `event_id` 가 그 열쇠다."""
        return {
            "event_id": self.event_id,
            dd.EVENT_TYPE: self.event_type,
            dd.AGGREGATE_ID: self.aggregate_id,
            dd.OUTBOX_SEQUENCE: self.sequence,
            "recorded_at": self.recorded_at,
            "payload": self.payload,
        }


class _Transaction:
    """모았다가 **커밋 때 한 번에** 쓴다. 예외가 나면 아무것도 쓰이지 않는다."""

    def __init__(self, store: "DurableStore") -> None:
        self._store = store
        self._writes: list[tuple[str, str, dict[str, Any]]] = []
        self._events: list[tuple[str, str, dict[str, Any]]] = []
        self._committed = False

    def put(self, kind: str, key: str, payload: dict[str, Any]) -> None:
        """사실 하나. 같은 `(kind, key)` 는 덮어쓴다 — 현재 상태를 담는 자리다."""
        self._writes.append((kind, key, dict(payload)))

    def enqueue(self, event_type: str, *, aggregate_id: str,
                payload: dict[str, Any] | None = None) -> None:
        """발행 예약. **커밋되지 않으면 발행도 없다.**"""
        self._events.append((event_type, aggregate_id, dict(payload or {})))

    # 내부 — `DurableStore.transaction()` 이 쓴다
    def _drain_writes(self) -> list[tuple[str, str, dict[str, Any]]]:
        return list(self._writes)

    def _drain_events(self) -> list[tuple[str, str, dict[str, Any]]]:
        return list(self._events)


@runtime_checkable
class DurableStoreProvider(Protocol):
    """사실과 발행 예약을 한 커밋에 쓰는 자리. 구현은 바뀌어도 이 계약은 같다."""

    @property
    def durability(self) -> str: ...

    def transaction(self) -> Any: ...

    def get(self, kind: str, key: str) -> dict[str, Any] | None: ...

    def list(self, kind: str) -> tuple[tuple[str, dict[str, Any]], ...]: ...

    def drain(self, limit: int = 100) -> tuple[OutboxEvent, ...]: ...

    def mark_published(self, event_ids: tuple[str, ...]) -> int: ...


class DurableStore:
    """계약의 뼈대. 실제 쓰기는 하위 클래스가 한다.

    트랜잭션을 컨텍스트 매니저로 두는 이유: 커밋 자리가 **하나**여야 "사실만 쓰고
    예약은 빠뜨린" 경로가 생기지 않는다.
    """

    def __init__(self) -> None:
        self._sequence = 0

    @property
    def durability(self) -> str:                      # pragma: no cover - 하위가 답한다
        raise NotImplementedError

    def transaction(self) -> "_TransactionContext":
        return _TransactionContext(self)

    # --- 하위 클래스가 채운다 ---------------------------------------------
    def _commit(self, writes: list[tuple[str, str, dict[str, Any]]],
                events: list[OutboxEvent]) -> None:   # pragma: no cover
        raise NotImplementedError

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def _make_events(self, raw: list[tuple[str, str, dict[str, Any]]],
                     now: float) -> list[OutboxEvent]:
        made = []
        for event_type, aggregate_id, payload in raw:
            seq = self._next_sequence()
            made.append(OutboxEvent(
                event_id=f"evt-{seq}-{aggregate_id}",
                event_type=event_type,
                aggregate_id=aggregate_id,
                payload=payload,
                recorded_at=now,
                sequence=seq,
            ))
        return made


class _TransactionContext:
    """`with store.transaction() as tx:` 의 몸통."""

    def __init__(self, store: DurableStore) -> None:
        self._store = store
        self._tx = _Transaction(store)

    def __enter__(self) -> _Transaction:
        return self._tx

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            return False                               # 아무것도 쓰지 않는다
        now = time.time()
        events = self._store._make_events(self._tx._drain_events(), now)
        self._store._commit(self._tx._drain_writes(), events)
        self._tx._committed = True
        return False


class InMemoryDurableStore(DurableStore):
    """저장 provider 가 없는 배치의 정상 동작. **재시작을 넘지 못한다고 말한다.**"""

    def __init__(self) -> None:
        super().__init__()
        self._facts: dict[tuple[str, str], dict[str, Any]] = {}
        self._outbox: list[OutboxEvent] = []

    @property
    def durability(self) -> str:
        return DURABILITY_PROCESS

    def _commit(self, writes, events) -> None:
        for kind, key, payload in writes:
            self._facts[(kind, key)] = payload
        self._outbox.extend(events)

    def get(self, kind: str, key: str) -> dict[str, Any] | None:
        found = self._facts.get((kind, key))
        return dict(found) if found is not None else None

    def list(self, kind: str) -> tuple[tuple[str, dict[str, Any]], ...]:
        return tuple(sorted(
            ((key, dict(payload)) for (k, key), payload in self._facts.items() if k == kind),
            key=lambda row: row[0]))

    def drain(self, limit: int = 100) -> tuple[OutboxEvent, ...]:
        return tuple(self._outbox[:limit])

    def mark_published(self, event_ids: tuple[str, ...]) -> int:
        wanted = set(event_ids)
        before = len(self._outbox)
        self._outbox = [e for e in self._outbox if e.event_id not in wanted]
        return before - len(self._outbox)


class SqliteDurableStore(DurableStore):
    """재시작을 넘는 구현. **표준 라이브러리만 쓴다**(AI-C-16: 폐쇄망에서도 선다).

    PostgreSQL 로 갈아끼우려면 같은 계약의 다른 클래스를 만들면 되고 부르는 쪽은
    바뀌지 않는다(AI-C-04). 여기서 sqlite 를 고른 이유는 하나다 — **새 의존성이
    없다.** 폴더 하나만 받은 기계에서 `pip install` 없이 돈다.
    """

    def __init__(self, path: str) -> None:
        super().__init__()
        import sqlite3                                  # noqa: PLC0415 - 표준 라이브러리

        self._path = path
        self._conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS facts ("
            " kind TEXT NOT NULL, key TEXT NOT NULL, payload TEXT NOT NULL,"
            " updated_at REAL NOT NULL, PRIMARY KEY (kind, key))")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS outbox ("
            " event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL,"
            " aggregate_id TEXT NOT NULL, payload TEXT NOT NULL,"
            " recorded_at REAL NOT NULL, sequence INTEGER NOT NULL)")
        row = self._conn.execute("SELECT MAX(sequence) FROM outbox").fetchone()
        # 재시작해도 **번호를 되쓰지 않는다** — 되쓰면 받는 쪽의 중복 접기가 거짓이 된다
        self._sequence = int(row[0] or 0)

    @property
    def durability(self) -> str:
        return DURABILITY_RESTART

    def _commit(self, writes, events) -> None:
        now = time.time()
        cur = self._conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        try:
            for kind, key, payload in writes:
                cur.execute(
                    "INSERT INTO facts (kind, key, payload, updated_at) VALUES (?,?,?,?)"
                    " ON CONFLICT(kind, key) DO UPDATE SET payload=excluded.payload,"
                    " updated_at=excluded.updated_at",
                    (kind, key, json.dumps(payload, ensure_ascii=False), now))
            for event in events:
                cur.execute(
                    "INSERT INTO outbox (event_id, event_type, aggregate_id, payload,"
                    " recorded_at, sequence) VALUES (?,?,?,?,?,?)",
                    (event.event_id, event.event_type, event.aggregate_id,
                     json.dumps(event.payload, ensure_ascii=False),
                     event.recorded_at, event.sequence))
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise

    def get(self, kind: str, key: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT payload FROM facts WHERE kind=? AND key=?", (kind, key)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, kind: str) -> tuple[tuple[str, dict[str, Any]], ...]:
        rows = self._conn.execute(
            "SELECT key, payload FROM facts WHERE kind=? ORDER BY key", (kind,)).fetchall()
        return tuple((key, json.loads(payload)) for key, payload in rows)

    def drain(self, limit: int = 100) -> tuple[OutboxEvent, ...]:
        rows = self._conn.execute(
            "SELECT event_id, event_type, aggregate_id, payload, recorded_at, sequence"
            " FROM outbox ORDER BY sequence LIMIT ?", (limit,)).fetchall()
        return tuple(OutboxEvent(r[0], r[1], r[2], json.loads(r[3]), r[4], r[5]) for r in rows)

    def mark_published(self, event_ids: tuple[str, ...]) -> int:
        if not event_ids:
            return 0
        marks = ",".join("?" * len(event_ids))
        cur = self._conn.execute(
            f"DELETE FROM outbox WHERE event_id IN ({marks})", tuple(event_ids))
        return cur.rowcount

    def close(self) -> None:
        self._conn.close()


@dataclass
class OutboxPublisher:
    """outbox 를 비우는 쪽. **보낸 뒤에만 지운다.**

    보내기 전에 지우면 그 사이에 죽었을 때 사건이 사라진다. 반대로 하면 **두 번
    보낼 수 있고**, 그쪽이 낫다 — 받는 쪽은 `event_id` 로 접을 수 있지만 없는
    사건은 복원할 수 없다(AI-C-20 과 같은 선택).
    """

    send: Any                                     # Callable[[dict], bool]
    batch: int = 50
    published: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def pump(self, store: DurableStoreProvider) -> int:
        """한 바퀴. 보낸 건수를 돌려준다. 실패는 **남겨 둔다**(다음에 다시 본다)."""
        sent: list[str] = []
        for event in store.drain(self.batch):
            try:
                ok = bool(self.send(event.as_wire()))
            except Exception:                     # noqa: BLE001 - 발행 실패는 축소다
                ok = False
            if ok:
                sent.append(event.event_id)
                self.published.append(event.event_id)
            else:
                self.failed.append(event.event_id)
                break                             # **순서를 지킨다** — 뒤를 먼저 보내지 않는다
        store.mark_published(tuple(sent))
        return len(sent)


class InboxDeduplicator:
    """받는 쪽의 중복 접기. at-least-once 를 **한 번 처리**로 만든다.

    `OutboxPublisher` 가 같은 사건을 두 번 보낼 수 있으므로 이것이 짝이다.
    `event_id` 를 이미 본 적이 있으면 **처리하지 않는다** — AI-C-20 의 "동일
    command_id 재전달은 물리 동작을 다시 실행하지 않는다" 와 같은 규칙이다.
    """

    def __init__(self, keep: int = 10_000) -> None:
        self._seen: dict[str, float] = {}
        self._keep = keep

    def accept(self, event: dict[str, Any]) -> bool:
        """처음 보는 사건이면 True. 이미 본 것이면 False 이고 **아무 일도 안 한다**."""
        event_id = str(event.get("event_id") or "")
        if not event_id:
            return True                           # 식별자가 없으면 접을 근거도 없다
        if event_id in self._seen:
            return False
        if len(self._seen) >= self._keep:
            oldest = min(self._seen, key=lambda k: self._seen[k])
            del self._seen[oldest]
        self._seen[event_id] = time.time()
        return True

    def seen_count(self) -> int:
        return len(self._seen)


def iter_unpublished(store: DurableStoreProvider, limit: int = 100) -> Iterator[OutboxEvent]:
    """아직 안 보낸 것들. 재시작 직후 **무엇이 남았는지** 보는 자리다."""
    yield from store.drain(limit)
