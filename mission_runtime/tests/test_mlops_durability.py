"""MLOps 파이프라인의 **내구성과 선점** — 배선이 실제로 걸렸는가.

implements: AI-B-05 (last-known-good), AI-L-08 (계보), AI-B-04 · AI-L-10 (배정·선점),
            AI-C-05 (없으면 축소)
tests: 배포 사실이 재시작을 넘는다 · 둘이 같은 실행영역을 못 잡는다 · 저장이 없어도
       배포는 된다 · 저장 장애가 배포를 멈추지 않는다 · 되돌리면 자원을 놓는다
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mission_runtime.continual.lineage import LearningLineage, LearningState
from mission_runtime.execution.control import LocalControlSupervisor
from mission_runtime.providers.durable_store import (
    InMemoryDurableStore,
    SqliteDurableStore,
)
from mission_runtime.runtime.clusters import ClusterBinding
from mission_runtime.runtime.clusters import PlacementRequest
from mission_runtime.runtime.mlops_pipeline import Deployable, MlopsPipeline
from mission_runtime.runtime.model_assignment import (
    DeviceProfile,
    MissionRequirement,
    ModelVersion,
)
from mission_runtime.runtime.reservation import (
    REASON_HELD_BY_OTHER,
    ReservationLedger,
    ResourceSlot,
)

KIND = "perception.detect"


def version() -> ModelVersion:
    return ModelVersion(model_id="det", version="v1", capability_kind=KIND,
                        verified_hw_tags=frozenset({"zone-edge"}),
                        quality=0.9, latency_ms=50.0, memory_mb=256.0)


def deployable(name: str = "det-svc") -> Deployable:
    return Deployable(
        deployable_id=name, capability_kind=KIND,
        placement=PlacementRequest(required_tags=frozenset({"zone-edge"})))


def device() -> DeviceProfile:
    return DeviceProfile(device_id="edge-1", hw_tags=frozenset({"zone-edge"}),
                         memory_mb=4096.0)


def requirement() -> MissionRequirement:
    return MissionRequirement(mission_id="M-1", capability_kind=KIND)


def lineage() -> LearningLineage:
    """승인까지 간 계보. 기존 시험(`test_mlops_pipeline.py`)과 **같은 방식**으로 만든다 —
    여기서 다른 길로 만들면 두 시험이 서로 다른 전제를 갖게 된다."""
    # **배정될 버전을 인용해야 한다.** 아무것도 인용하지 않은 계보는 어느 버전에
    # 대한 것도 아니고, 파이프라인이 `lineage_never_cited_this_version` 으로 거절한다.
    cites = version().reference
    made = LearningLineage("lin-dur", actor="op", evidence_ref=cites, reason="candidate")
    while made.state is not LearningState.APPROVED:
        made.advance(actor="op", evidence_ref=cites, reason="stage")
    return made


def pipeline(**over) -> MlopsPipeline:
    made = MlopsPipeline(
        [ClusterBinding("zone-edge", LocalControlSupervisor(), frozenset({"zone-edge"}))],
        **over)
    made.register_version(version())
    return made


def place(pipe: MlopsPipeline, name: str = "det-svc"):
    return pipe.submit(deployable(name), device(), requirement(),
                       lineage=lineage(), actor="admin", evidence_ref="ev-3")


# --------------------------------------------------------------- 내구성

def test_a_placement_survives_a_restart(tmp_path: Path):
    """**AI-B-05 의 last-known-good 가 말뿐이 아니게 되는 자리.**"""
    path = str(tmp_path / "mlops.db")
    store = SqliteDurableStore(path)
    status = place(pipeline(store=store))
    assert status.phase.value in ("placed", "verification", "PLACED")
    store.close()

    reopened = SqliteDurableStore(path)                 # 프로세스가 죽었다 다시 떴다
    rows = dict(reopened.list("deployment"))
    assert rows, "배포 사실이 남아 있어야 한다"
    only = next(iter(rows.values()))
    assert only["deployable_id"] == "det-svc"
    assert only["version"] == "det@v1"
    reopened.close()


def test_the_announcement_waits_in_the_outbox_until_someone_sends_it():
    """사실만 쓰고 알리지 않으면 **상태는 바뀌었는데 아무도 모른다.**"""
    store = InMemoryDurableStore()
    place(pipeline(store=store))

    events = store.drain()
    assert events, "발행 예약이 같은 커밋에 들어가야 한다"
    assert any(e.event_type.startswith("mlops.deployment") for e in events)
    assert all(e.aggregate_id for e in events)


def test_a_refusal_is_recorded_too_not_just_a_success():
    """"요청했는데 아무 일도 없었다" 를 사후에 확인할 수 있어야 한다(AI-O-02)."""
    store = InMemoryDurableStore()
    pipe = MlopsPipeline([], store=store)               # 실행영역이 없다 → 거부
    pipe.register_version(version())
    place(pipe)

    kinds = [event.event_type for event in store.drain()]
    assert any("refused" in kind for kind in kinds), kinds


def test_without_a_store_the_placement_still_happens():
    """저장 provider 가 없는 배치는 **정상**이다(AI-C-05) — 판정은 그대로다."""
    status = place(pipeline())
    assert status.phase.value in ("placed", "verification", "PLACED")


def test_a_broken_store_does_not_stop_a_deployment():
    """저장 장애가 배포를 멈추면, 기록하려다 **기록할 일 자체를 없앤다.**"""

    class Exploding:
        def transaction(self):
            raise RuntimeError("디스크가 꽉 찼다")

    status = place(pipeline(store=Exploding()))
    assert status.phase.value in ("placed", "verification", "PLACED")


# --------------------------------------------------------------- 선점

def test_two_deployments_cannot_take_the_same_execution_area():
    """**다중 노드로 가는 순간 생기는 문제.** 배정만 하고 잡지 않으면 둘 다 올라간다."""
    ledger = ReservationLedger((ResourceSlot("zone-edge"),))
    pipe = pipeline(reservations=ledger)

    first = place(pipe, "det-a")
    assert first.phase.value in ("placed", "verification", "PLACED")

    second = place(pipe, "det-b")
    assert second.phase.value in ("refused", "REFUSED")
    assert REASON_HELD_BY_OTHER in (second.reason or ""), second.reason


def test_rolling_back_gives_the_resource_up():
    """되돌렸는데 쥐고 있으면 그 자리는 **영원히 비지 않는다.**"""
    ledger = ReservationLedger((ResourceSlot("zone-edge"),))
    pipe = pipeline(reservations=ledger)
    status = place(pipe, "det-a")

    pipe.rollback(status.deployment_id, actor="admin",
                  evidence_ref="ev-4", reason="회귀")
    assert ledger.holders("zone-edge") == ()
    assert place(pipe, "det-b").phase.value in ("placed", "verification", "PLACED")


def test_the_lease_token_is_reachable_for_the_executing_side():
    """fencing 은 **실제로 쓰는 쪽**이 들고 있어야 뜻이 있다."""
    ledger = ReservationLedger((ResourceSlot("zone-edge"),))
    pipe = pipeline(reservations=ledger)
    status = place(pipe, "det-a")

    lease = pipe.lease_of(status.deployment_id)
    assert lease is not None and lease.token >= 1


def test_without_a_ledger_placement_is_unchanged():
    """단일 노드 배치에서 선점은 없어도 된다 — 없는 것이 **정상**이다."""
    pipe = pipeline()
    assert place(pipe, "det-a").phase.value in ("placed", "verification", "PLACED")
    assert pipe.lease_of("whatever") is None


def test_a_control_rejection_does_not_leave_the_resource_held():
    """못 올렸는데 쥐고 있으면 다음 시도가 **영원히 막힌다.**"""

    class Rejecting:
        def request(self, *_args, **_kwargs):
            from mission_runtime.execution.control import ControlResult
            return ControlResult(False, None, rejection_reason="no_capacity")

        def get_status(self, _target):
            return None

        def is_available(self) -> bool:
            return True

    ledger = ReservationLedger((ResourceSlot("zone-edge"),))
    pipe = MlopsPipeline([ClusterBinding("zone-edge", Rejecting(),
                                         frozenset({"zone-edge"}))],
                         reservations=ledger)
    pipe.register_version(version())
    refused = place(pipe, "det-a")

    assert refused.phase.value in ("refused", "REFUSED")
    assert ledger.holders("zone-edge") == (), "거부 뒤에는 자원을 놓아야 한다"
