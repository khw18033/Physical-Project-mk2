"""공간 그래프의 통행·충전 예약 — **같은 복도에서 둘이 마주 서지 않게.**

implements: AI-B-04 (실행 노드 자원 등록·배치), AI-B-06 (자원 상태 기반 재구성)
관련: AI-C-19 (예약은 명령이 아니다), AI-C-02 (프레임을 끝까지 들고 다닌다),
      AI-C-05 (선언이 없으면 이 계층만 비활성), AI-O-05 (미측정 ≠ 0), AI-C-18 (선언 규약)
tests: tests/test_space_reservation.py

## 무엇이 모자랐나

`runtime/reservation.py` 는 자원 하나의 **점유**를 센다. 가속기·추론 슬롯처럼
"몇 개를 동시에 쥘 수 있나" 로 끝나는 자원은 그것으로 충분하다. 통행은 그렇지
않다 — 복도 하나를 **양쪽에서** 들어오면 수용량은 2 라서 둘 다 통과하지만 실제로는
마주 서서 둘 다 못 간다. 수용량만으로는 표현할 수 없는 사실이 **방향**이다.

그래서 이 모듈에 새로 있는 것은 네 가지뿐이다.

1. **방향**: 한 방향으로 쥔 구간은 반대 방향에게 수용량이 남아 있어도 거절된다.
2. **경로는 전부 아니면 전무**: 다섯 칸 중 셋만 잡고 기다리면, 마주 오는 쪽이 남은
   둘을 쥐고 서로를 기다린다. 중간에 하나라도 거절되면 **잡았던 것을 모두 놓는다.**
3. **잡는 순서를 정한다**: 자원 id 정렬 순으로만 잡는다. 두 경로가 교차해도 잡는
   순서가 같으면 순환 대기가 **구조적으로** 생기지 않는다.
4. **프레임**: 그래프는 자기 기준 좌표계를 들고 있고, 다른 프레임의 노드를 섞은
   경로는 거절한다. 로컬 값과 전역 값은 같은 칸에 담지 않는다(AI-C-02).

충전은 새 코드가 **아니다.** 충전기는 `charger` 태그를 단 노드이고, 다 차 있으면
장부가 이미 내는 `retry_after_s` 가 "언제 비나" 를 말한다. 자원 축을 열어 두면
새 종류는 선언 한 줄이고 코드 변경이 아니다 — 그것이 열어 둔 이유였다.

**다만 지금 어느 배치도 충전소 노드를 선언하지 않는다**(2026-11-20 확인). 그래서
이 경로는 선언이 생기는 날 열리는 자리이고, 지금 운영자가 아는 충전 사실은 예약이
아니라 **상태**다 — 장치가 스스로 말하는 잔량·충전 중 여부를
`integration/device_telemetry_source.py` 가 받아 `GET /api/robot` 의 `charge` 로
낸다. 없는 자원을 예약하는 화면을 먼저 만들면, 아무 일도 하지 않는 단추가 생긴다.

## 점유의 주인은 하나다

이 모듈은 장부를 **따로 두지 않는다.** 점유는 `ReservationLedger` 가 authoritative
하게 알고, 여기 있는 방향 색인은 그 장부에서 **파생**된다 — 살아 있는 점유자
목록과 어긋나는 항목은 읽을 때마다 버린다. 같은 사실을 두 곳이 각자 적으면
어긋나는 날 둘이 다른 답을 말한다.

## 예약은 명령이 아니다

여기서 나오는 것은 "그 길을 지금 쥘 수 있는가" 하나다. 쥐었다고 로봇이 움직이지
않고, 쥘 수 없다고 우리가 다른 길을 고르지도 않는다 — 후보 산출은
`planning/path_candidates.py`, 실제 이동 명령은 제어 경계의 몫이다(AI-C-19).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.runtime.reservation import (
    Lease,
    Refusal,
    ReservationLedger,
    ResourceSlot,
)

#: 구간 자원 id 의 접두사. 노드 id 와 **섞이지 않게** 하려고 붙인다 — 같은 이름
#: 공간에 두면 `dock-1` 노드와 `dock-1` 구간이 같은 자원이 된다.
NODE_PREFIX = "node:"
EDGE_PREFIX = "edge:"

#: 충전기임을 말하는 태그. 벤더 열거형이 아니라 **선언 데이터**다(AI-C-18).
CHARGER_TAG = "charger"

#: 거절 사유 어휘. 장부의 사유와 **겹치지 않는 이름**만 더한다.
REASON_UNKNOWN_NODE = "node_not_declared"
REASON_NOT_ADJACENT = "nodes_not_adjacent"
REASON_EMPTY_ROUTE = "route_too_short"
REASON_HEAD_ON = "opposing_direction_held"
#: 같은 자리 이름이 **다른 프레임**으로 이미 장부에 있다. 적재 시점에 터진다.
REASON_FRAME_MISMATCH = "resource_declared_in_another_frame"
#: 충전기로 선언되지 않은 자리를 충전 기한(기본 10분)으로 잡으려 했다.
REASON_NOT_A_CHARGER = "node_not_declared_as_charger"


def node_resource(node_id: str) -> str:
    return f"{NODE_PREFIX}{node_id}"


def edge_resource(a: str, b: str) -> str:
    """구간 자원 id. 양방향 구간은 **방향에 무관하게 같은 자원**이다 —
    방향마다 다른 id 를 주면 마주 오는 둘이 서로를 전혀 보지 못한다."""
    first, second = sorted((a, b))
    return f"{EDGE_PREFIX}{first}|{second}"


@dataclass(frozen=True)
class GraphNode:
    """통행 그래프의 한 자리. **선언이다** — 관측이 아니다(AI-C-18).

    `capacity` 는 그 자리에 동시에 설 수 있는 수다. 교차로나 대기 구역은 1 보다
    클 수 있고, 충전기 두 구가 있는 자리는 2 다.
    """

    node_id: str
    capacity: int = 1
    tags: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_charger(self) -> bool:
        return CHARGER_TAG in self.tags


@dataclass(frozen=True)
class GraphEdge:
    """두 자리를 잇는 구간.

    `capacity` 는 같은 방향으로 동시에 들어갈 수 있는 수다. `oneway` 가 참이면
    `a → b` 만 허용한다 — 선언으로 막는 것과 점유로 막는 것은 다른 사실이다.
    """

    a: str
    b: str
    capacity: int = 1
    oneway: bool = False
    tags: frozenset[str] = field(default_factory=frozenset)

    @property
    def resource_id(self) -> str:
        return edge_resource(self.a, self.b)


class SpaceGraphError(ValueError):
    """선언이 잘못됐다. **적재 시점에 크게 터진다** — 조용히 좁은 쪽을 쓰면
    기능 하나가 말없이 사라진다(`contracts/profile_loader.py` 와 같은 규칙)."""


class SpaceGraph:
    """통행 그래프의 선언. 기하가 아니라 **인접 관계**만 담는다.

    좌표를 담지 않는 이유: 거리·각도는 `planning/path_candidates.py` 와
    `rf` 모델이 이미 소유한다. 여기서 또 적으면 같은 사실의 주인이 둘이 된다.
    """

    def __init__(self, frame_id: str, *, nodes: Iterable[GraphNode] = (),
                 edges: Iterable[GraphEdge] = ()) -> None:
        self.frame_id = frame_id
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[str, GraphEdge] = {}
        for node in nodes:
            self.declare_node(node)
        for edge in edges:
            self.declare_edge(edge)

    # --- 선언 -------------------------------------------------------------
    def declare_node(self, node: GraphNode) -> None:
        self._nodes[node.node_id] = node

    def declare_edge(self, edge: GraphEdge) -> None:
        """구간을 들인다. **양 끝이 선언되어 있어야 한다** — 없는 자리로 가는
        길을 받아 두면 경로 검증이 통과하고 실행만 실패한다."""
        for end in (edge.a, edge.b):
            if end not in self._nodes:
                raise SpaceGraphError(f"구간의 끝이 선언되지 않았다: {end}")
        if edge.a == edge.b:
            raise SpaceGraphError(f"자기 자리로 가는 구간: {edge.a}")
        self._edges[edge.resource_id] = edge

    def nodes(self) -> tuple[str, ...]:
        return tuple(sorted(self._nodes))

    def node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    def edges(self) -> tuple[GraphEdge, ...]:
        return tuple(self._edges[key] for key in sorted(self._edges))

    def edge_between(self, a: str, b: str) -> GraphEdge | None:
        return self._edges.get(edge_resource(a, b))

    def neighbors(self, node_id: str) -> tuple[str, ...]:
        """선언이 없는 자리는 **빈 목록이 아니라 빈 목록이다** — 없는 것과
        이웃이 없는 것을 구분해야 하면 `node()` 로 묻는다."""
        out: list[str] = []
        for edge in self._edges.values():
            if edge.a == node_id:
                out.append(edge.b)
            elif edge.b == node_id and not edge.oneway:
                out.append(edge.a)
        return tuple(sorted(out))

    def chargers(self) -> tuple[str, ...]:
        """충전기로 선언된 자리. **고르지는 않는다** — 어느 것을 쓸지는 선택기의
        몫이고 여기는 목록만 낸다."""
        return tuple(sorted(node_id for node_id, node in self._nodes.items()
                            if node.is_charger))

    # --- 장부에 들이기 -----------------------------------------------------
    def slots(self) -> tuple[ResourceSlot, ...]:
        """선언을 그대로 자원 슬롯으로 옮긴다. **새 자원 종류가 아니다** —
        기존 장부가 세던 것과 같은 것을 센다."""
        made: list[ResourceSlot] = []
        for node_id, node in sorted(self._nodes.items()):
            made.append(ResourceSlot(node_resource(node_id), node.capacity,
                                     node.tags | {"space.node", f"frame:{self.frame_id}"}))
        for key in sorted(self._edges):
            edge = self._edges[key]
            made.append(ResourceSlot(key, edge.capacity,
                                     edge.tags | {"space.edge", f"frame:{self.frame_id}"}))
        return tuple(made)


@dataclass(frozen=True)
class RouteHold:
    """경로 하나에 대한 점유 묶음. **칸마다 토큰이 다르다** — 실제로 쓰는 쪽은
    자기가 들어가는 칸의 번호를 본다(`FencingGuard`)."""

    holder: str
    route: tuple[str, ...]
    leases: tuple[Lease, ...]

    def token_for(self, resource_id: str) -> int | None:
        for lease in self.leases:
            if lease.resource_id == resource_id:
                return lease.token
        return None

    @property
    def resource_ids(self) -> tuple[str, ...]:
        return tuple(lease.resource_id for lease in self.leases)


class TrafficReservation:
    """통행·충전 예약. 점유는 장부가 알고, 여기는 **방향과 전부·전무**를 더한다."""

    def __init__(self, graph: SpaceGraph,
                 ledger: ReservationLedger | None = None) -> None:
        self.graph = graph
        self.ledger = ledger if ledger is not None else ReservationLedger()
        self._declare_into(self.ledger, graph)
        #: 구간 → [(점유자, 들어온 쪽, 나가는 쪽)]. **장부에서 파생된다** —
        #: 읽을 때마다 살아 있는 점유자와 맞춰 버린다.
        self._dirs: dict[str, list[tuple[str, str, str]]] = {}
        #: 거절을 센다. 「통행 충돌 0건」을 주장이 아니라 측정으로 만든다.
        self.refusals: list[Refusal] = []

    # --- 통행 -------------------------------------------------------------
    def hold_route(self, route: Sequence[str], *, holder: str,
                   ttl_s: float = 30.0) -> RouteHold | Refusal:
        """경로 전체를 잡거나, **하나도 잡지 않고** 사유를 낸다."""
        checked = self._validate(route)
        if isinstance(checked, Refusal):
            return checked

        wanted = self._resources_for(route)
        blocked = self._head_on(route, holder)
        if blocked is not None:
            return self._refuse(blocked)

        taken: list[Lease] = []
        for resource_id in sorted(wanted):           # **정렬 순으로만** 잡는다
            outcome = self.ledger.acquire(resource_id, holder=holder, ttl_s=ttl_s)
            if isinstance(outcome, Refusal):
                self._give_back(taken)               # 전부 아니면 전무
                return self._refuse(outcome)
            taken.append(outcome)

        self._remember_directions(route, holder)
        return RouteHold(holder, tuple(route), tuple(taken))

    def confirm(self, hold: RouteHold) -> RouteHold | Refusal:
        """실제로 들어가기 **직전에** 확정한다. 확정되지 않은 점유는 바깥에서
        해제되지 않는다(장부의 규칙)."""
        confirmed: list[Lease] = []
        for lease in hold.leases:
            outcome = self.ledger.confirm(lease)
            if isinstance(outcome, Refusal):
                return self._refuse(outcome)
            confirmed.append(outcome)
        return RouteHold(hold.holder, hold.route, tuple(confirmed))

    def release(self, hold: RouteHold) -> None:
        """다 지나갔다. **안 놓으면 그 길은 영원히 비지 않는다.**"""
        self._give_back(list(hold.leases))
        self._forget(hold.holder)

    def release_passed(self, hold: RouteHold, *, now_at: str) -> RouteHold | Refusal:
        """지나온 칸만 놓는다 — 긴 경로를 끝까지 쥐고 있으면 뒤차가 못 들어온다.

        `now_at` 은 **관측이 아니라 알려 준 값**이다. 우리가 로봇의 위치를
        authoritative 하게 알지 못하므로(AI-C-19) 어디까지 왔는지는 받아서 쓴다.
        """
        if now_at not in hold.route:
            return self._refuse(Refusal(node_resource(now_at), REASON_UNKNOWN_NODE))
        index = hold.route.index(now_at)
        passed = self._resources_for(hold.route[:index + 1]) - {node_resource(now_at)}
        keep: list[Lease] = []
        drop: list[Lease] = []
        for lease in hold.leases:
            (drop if lease.resource_id in passed else keep).append(lease)
        self._give_back(drop)
        self._prune_directions()
        return RouteHold(hold.holder, hold.route[index:], tuple(keep))

    # --- 충전 -------------------------------------------------------------
    def hold_charger(self, node_id: str, *, holder: str,
                     ttl_s: float = 600.0) -> Lease | Refusal:
        """충전기 한 자리를 잡는다. 다 차 있으면 장부가 `retry_after_s` 를 낸다.

        **새 판정이 없다.** 충전기는 태그를 단 노드이고 점유는 같은 장부가 센다.
        """
        node = self.graph.node(node_id)
        if node is None:
            return self._refuse(Refusal(node_resource(node_id), REASON_UNKNOWN_NODE))
        if not node.is_charger:
            # 충전 기한은 통행 기한보다 훨씬 길다. 충전기가 아닌 자리를 그 기한으로
            # 쥐면 **그 길이 10분 막힌다** — 태그가 없으면 거절한다.
            return self._refuse(Refusal(node_resource(node_id), REASON_NOT_A_CHARGER))
        return self.ledger.acquire(node_resource(node_id), holder=holder, ttl_s=ttl_s)

    # --- 보기 -------------------------------------------------------------
    def occupancy(self) -> dict[str, dict[str, object]]:
        """운영 화면이 읽는 모양. 선언된 자리는 **비어 있어도 빠지지 않는다**."""
        self._prune_directions()
        snapshot = self.ledger.snapshot()
        for resource_id, row in snapshot.items():
            held = self._dirs.get(resource_id)
            if held:
                row[dd.ROUTE_DIRECTION] = [
                    {dd.LEASE_HOLDER: who, "from": src, "to": dst}
                    for who, src, dst in held]
        return snapshot

    def free_at(self, node_id: str) -> int | None:
        """몇 대 더 들어갈 수 있나. **선언이 없으면 0 이 아니라 None 이다.**"""
        return self.ledger.free_capacity(node_resource(node_id))

    # --- 내부 -------------------------------------------------------------
    @staticmethod
    def _declare_into(ledger: ReservationLedger, graph: SpaceGraph) -> None:
        """그래프를 장부에 들인다.

        **두 현장이 같은 이름을 쓰는 날을 여기서 잡는다.** 창고 둘이 모두
        `dock-1` 을 선언하고 한 장부에 들어오면, 서로 아무 관계 없는 두 자리가
        같은 자원으로 점유를 다툰다 — 그 실패는 운영 로그 어디에도 이유가 없다.
        프레임은 공간 값의 신원이고(AI-C-02) 선언 시점에 어긋나면 크게 터진다.
        """
        existing = ledger.snapshot()
        mine = f"frame:{graph.frame_id}"
        for slot in graph.slots():
            already = existing.get(slot.resource_id)
            if already is not None:
                tags = {str(tag) for tag in already.get("tags", ())}
                theirs = {tag for tag in tags if tag.startswith("frame:")}
                if theirs and mine not in theirs:
                    raise SpaceGraphError(
                        f"{REASON_FRAME_MISMATCH}: {slot.resource_id} 는 이미 "
                        f"{sorted(theirs)} 로 선언되어 있다 (이번 프레임 {mine})")
            ledger.declare(slot)

    def _refuse(self, refusal: Refusal) -> Refusal:
        self.refusals.append(refusal)
        return refusal

    def _validate(self, route: Sequence[str]) -> None | Refusal:
        if len(route) < 2:
            return self._refuse(Refusal("", REASON_EMPTY_ROUTE))
        for node_id in route:
            if self.graph.node(node_id) is None:
                return self._refuse(Refusal(node_resource(node_id), REASON_UNKNOWN_NODE))
        for src, dst in zip(route, route[1:]):
            edge = self.graph.edge_between(src, dst)
            if edge is None:
                return self._refuse(Refusal(edge_resource(src, dst), REASON_NOT_ADJACENT))
            if edge.oneway and (edge.a, edge.b) != (src, dst):
                return self._refuse(Refusal(edge.resource_id, REASON_NOT_ADJACENT))
        return None

    def _resources_for(self, route: Sequence[str]) -> set[str]:
        wanted = {node_resource(node_id) for node_id in route}
        wanted |= {edge_resource(src, dst) for src, dst in zip(route, route[1:])}
        return wanted

    def _head_on(self, route: Sequence[str], holder: str) -> Refusal | None:
        """마주 오는 구간이 있나. **수용량이 남아 있어도 거절한다.**"""
        self._prune_directions()
        for src, dst in zip(route, route[1:]):
            resource_id = edge_resource(src, dst)
            for who, held_src, held_dst in self._dirs.get(resource_id, ()):
                if who == holder:
                    continue
                if (held_src, held_dst) == (dst, src):
                    return Refusal(resource_id, REASON_HEAD_ON, held_by=who)
        return None

    def _remember_directions(self, route: Sequence[str], holder: str) -> None:
        for src, dst in zip(route, route[1:]):
            entries = self._dirs.setdefault(edge_resource(src, dst), [])
            if (holder, src, dst) not in entries:
                entries.append((holder, src, dst))

    def _prune_directions(self) -> None:
        """장부가 정본이다. 살아 있는 점유자에 없는 방향 항목은 버린다."""
        for resource_id, entries in list(self._dirs.items()):
            live = set(self.ledger.holders(resource_id))
            kept = [entry for entry in entries if entry[0] in live]
            if kept:
                self._dirs[resource_id] = kept
            else:
                del self._dirs[resource_id]

    def _forget(self, holder: str) -> None:
        for resource_id, entries in list(self._dirs.items()):
            kept = [entry for entry in entries if entry[0] != holder]
            if kept:
                self._dirs[resource_id] = kept
            else:
                del self._dirs[resource_id]

    def _give_back(self, leases: list[Lease]) -> None:
        """잡았던 것을 놓는다.

        장부는 **확정된 것만** 해제한다 — 그래서 아직 HELD 인 점유는 확정한 뒤
        해제한다. 돌아가는 길이 하나뿐인 것은 의도다: "잡은 줄 알고 쓰기 시작한
        쪽" 을 바깥에서 지우지 못하게 하려고 그 규칙을 둔 것이고, 되돌리는 쪽은
        자기가 잡은 것이므로 확정할 자격이 있다.
        """
        for lease in leases:
            current = self.ledger.confirm(lease)
            self.ledger.release(current if isinstance(current, Lease) else lease)
        self._prune_directions()
