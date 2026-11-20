"""여러 모델 × 여러 노드 — 함대 배포와 **이미지가 그 버전을 싣는지** 확인.

implements: AI-L-10 (하드웨어·임무 조건 기반 모델 배정), AI-B-04 (자원 등록·배치),
            AI-B-11 (복수 실행영역), AI-B-01 (미측정 구분), AI-C-05 (부분 실패 격리),
            AI-C-13 (사유 노출)
tests: 장치마다 제 버전이 간다 · 한 대가 막혀도 나머지는 올라간다 · 같은 자리를 둘이
       못 잡는다 · 수용량은 선언이다 · 호출 순서가 결과를 바꾸지 않는다 ·
       이미지가 다른 버전을 싣는다고 하면 거절한다 · 선언이 없으면 **확인되지 않았다**
"""
from __future__ import annotations

import pytest

from mission_runtime.continual.lineage import LearningLineage, LearningState
from mission_runtime.execution.control import LocalControlSupervisor
from mission_runtime.runtime.clusters import ClusterBinding, PlacementRequest
from mission_runtime.runtime.mlops_pipeline import (
    CARRIAGE_MISMATCH,
    CARRIAGE_NOT_DECLARED,
    CARRIAGE_UNPINNED,
    CARRIAGE_VERIFIED,
    REFUSE_IMAGE_VERSION_MISMATCH,
    REFUSE_NO_ASSIGNMENT,
    Deployable,
    FleetRequest,
    MlopsPipeline,
)
from mission_runtime.runtime.model_assignment import (
    DeviceProfile,
    MissionRequirement,
    ModelVersion,
)
from mission_runtime.runtime.reservation import (
    REASON_CAPACITY,
    REASON_HELD_BY_OTHER,
    ReservationLedger,
    ResourceSlot,
)

KIND = "perception.detect"


def version(tag: str, hw: str, *, quality: float = 0.9,
            memory_mb: float = 256.0) -> ModelVersion:
    return ModelVersion(model_id="det", version=tag, capability_kind=KIND,
                        verified_hw_tags=frozenset({hw}),
                        quality=quality, latency_ms=50.0, memory_mb=memory_mb)


def device(device_id: str, hw: str, *, memory_mb: float = 4096.0) -> DeviceProfile:
    return DeviceProfile(device_id=device_id, hw_tags=frozenset({hw}),
                         memory_mb=memory_mb)


PINNED = "registry.internal/det@sha256:" + "c" * 64
MOVING = "registry.internal/det:latest"


def unit(name: str, tag: str, *, carries: str | None = None,
         image: str = PINNED) -> Deployable:
    return Deployable(deployable_id=name, capability_kind=KIND,
                      placement=PlacementRequest(required_tags=frozenset({tag})),
                      control_params={"image": image},
                      carries_model=carries)


def lineage(cites: str) -> LearningLineage:
    made = LearningLineage("lin-" + cites, actor="op", evidence_ref=cites,
                           reason="candidate")
    while made.state is not LearningState.APPROVED:
        made.advance(actor="op", evidence_ref=cites, reason="stage")
    return made


def pipeline(*areas: str, **over) -> MlopsPipeline:
    bindings = [ClusterBinding(area, LocalControlSupervisor(), frozenset({area}))
                for area in areas]
    return MlopsPipeline(bindings, **over)


def requirement() -> MissionRequirement:
    return MissionRequirement(mission_id="M-1", capability_kind=KIND)


def submit(pipe: MlopsPipeline, requests):
    return pipe.submit_fleet(requests, requirement(), actor="admin",
                             evidence_ref="ev-fleet")


# --------------------------------------------------------------- 여러 모델

def test_each_device_gets_the_version_verified_for_its_own_hardware():
    """**이것이 다중 모델의 요점이다.** 같은 기능인데 노드마다 다른 버전이 간다."""
    pipe = pipeline("edge-a", "edge-b")
    pipe.register_version(version("v1", "edge-a"))
    pipe.register_version(version("v2", "edge-b"))

    outcome = submit(pipe, [
        FleetRequest(device("pi-a", "edge-a"), unit("det-a", "edge-a"), lineage("det@v1")),
        FleetRequest(device("pi-b", "edge-b"), unit("det-b", "edge-b"), lineage("det@v2")),
    ])

    assert len(outcome.placed) == 2 and outcome.refused == ()
    assert outcome.versions() == {"det-a": "det@v1", "det-b": "det@v2"}


def test_a_device_with_no_eligible_version_is_the_only_one_refused():
    """부분 실패는 **정상 축소**다(AI-C-05). 한 대 때문에 전부 내리면 장애 전파다."""
    pipe = pipeline("edge-a", "edge-c")
    pipe.register_version(version("v1", "edge-a"))

    outcome = submit(pipe, [
        FleetRequest(device("pi-a", "edge-a"), unit("det-a", "edge-a"), lineage("det@v1")),
        FleetRequest(device("pi-c", "edge-c"), unit("det-c", "edge-c"), lineage("det@v1")),
    ])

    assert [entry.deployable_id for entry in outcome.placed] == ["det-a"]
    assert [entry.deployable_id for entry in outcome.refused] == ["det-c"]
    assert outcome.reasons()["det-c"] == REFUSE_NO_ASSIGNMENT


def test_a_version_too_big_for_one_device_still_goes_to_the_other():
    """메모리는 장치마다 다르다 — 그 차이가 배정에 그대로 드러나야 한다."""
    pipe = pipeline("edge-a", "edge-b")
    pipe.register_version(version("v1", "edge-a", memory_mb=128.0))
    pipe.register_version(version("big", "edge-b", memory_mb=8192.0))

    outcome = submit(pipe, [
        FleetRequest(device("pi-a", "edge-a", memory_mb=512.0),
                     unit("det-a", "edge-a"), lineage("det@v1")),
        FleetRequest(device("pi-b", "edge-b", memory_mb=512.0),
                     unit("det-b", "edge-b"), lineage("det@big")),
    ])

    assert outcome.versions()["det-a"] == "det@v1"
    assert outcome.reasons()["det-b"] == REFUSE_NO_ASSIGNMENT


# --------------------------------------------------------------- 여러 노드

def test_two_units_cannot_take_the_same_execution_area():
    """배정만 하고 잡지 않으면 **둘 다 올라가고 하나가 메모리로 죽는다.**"""
    ledger = ReservationLedger((ResourceSlot("edge-a"),))
    pipe = pipeline("edge-a", reservations=ledger)
    pipe.register_version(version("v1", "edge-a"))

    outcome = submit(pipe, [
        FleetRequest(device("pi-a", "edge-a"), unit("det-a", "edge-a"), lineage("det@v1")),
        FleetRequest(device("pi-b", "edge-a"), unit("det-b", "edge-a"), lineage("det@v1")),
    ])

    assert len(outcome.placed) == 1 and len(outcome.refused) == 1
    assert REASON_HELD_BY_OTHER in (outcome.refused[0].status.reason or "")
    assert outcome.placed[0].deployable_id == "det-a", "정렬 순이 결정한다"


def test_a_declared_capacity_of_two_lets_both_in_without_touching_code():
    """수용량은 **선언이다.** 코드가 아니라 장부의 한 줄이 둘을 들인다."""
    ledger = ReservationLedger((ResourceSlot("edge-a", capacity=2),))
    pipe = pipeline("edge-a", reservations=ledger)
    pipe.register_version(version("v1", "edge-a"))

    outcome = submit(pipe, [
        FleetRequest(device("pi-a", "edge-a"), unit("det-a", "edge-a"), lineage("det@v1")),
        FleetRequest(device("pi-b", "edge-a"), unit("det-b", "edge-a"), lineage("det@v1")),
    ])
    assert len(outcome.placed) == 2


def test_a_third_unit_is_refused_with_capacity_not_with_held_by_other():
    """"남이 쥐었다" 와 "자리가 다 찼다" 는 **할 일이 다르다**."""
    ledger = ReservationLedger((ResourceSlot("edge-a", capacity=2),))
    pipe = pipeline("edge-a", reservations=ledger)
    pipe.register_version(version("v1", "edge-a"))

    outcome = submit(pipe, [
        FleetRequest(device(f"pi-{n}", "edge-a"), unit(f"det-{n}", "edge-a"),
                     lineage("det@v1"))
        for n in ("a", "b", "c")
    ])

    assert len(outcome.placed) == 2
    assert REASON_CAPACITY in (outcome.refused[0].status.reason or "")


def test_the_call_order_does_not_change_who_wins():
    """같은 입력에 같은 결과여야 한다 — 호출 순서로 바뀌면 재현할 수 없는 배포다."""
    def run(order):
        ledger = ReservationLedger((ResourceSlot("edge-a"),))
        pipe = pipeline("edge-a", reservations=ledger)
        pipe.register_version(version("v1", "edge-a"))
        requests = {
            "a": FleetRequest(device("pi-a", "edge-a"), unit("det-a", "edge-a"),
                              lineage("det@v1")),
            "b": FleetRequest(device("pi-b", "edge-a"), unit("det-b", "edge-a"),
                              lineage("det@v1")),
        }
        return submit(pipe, [requests[key] for key in order]).placed[0].deployable_id

    assert run("ab") == run("ba") == "det-a"


def test_two_areas_mean_two_units_fit_even_with_single_capacity_each():
    """다중 노드가 **실제로** 늘어나는 자리."""
    ledger = ReservationLedger((ResourceSlot("edge-a"), ResourceSlot("edge-b")))
    pipe = pipeline("edge-a", "edge-b", reservations=ledger)
    pipe.register_version(version("v1", "edge-a"))
    pipe.register_version(version("v2", "edge-b"))

    outcome = submit(pipe, [
        FleetRequest(device("pi-a", "edge-a"), unit("det-a", "edge-a"), lineage("det@v1")),
        FleetRequest(device("pi-b", "edge-b"), unit("det-b", "edge-b"), lineage("det@v2")),
    ])
    assert len(outcome.placed) == 2
    assert {entry.status.area_id for entry in outcome.placed} == {"edge-a", "edge-b"}


def test_the_same_unit_id_twice_is_a_declaration_error_not_a_degrade():
    """뒤의 것이 앞의 것을 조용히 가리면 한 배포가 말없이 사라진다."""
    pipe = pipeline("edge-a")
    pipe.register_version(version("v1", "edge-a"))

    with pytest.raises(ValueError):
        submit(pipe, [
            FleetRequest(device("pi-a", "edge-a"), unit("det", "edge-a"), lineage("det@v1")),
            FleetRequest(device("pi-b", "edge-a"), unit("det", "edge-a"), lineage("det@v1")),
        ])


def test_each_device_advances_its_own_lineage():
    """한 계보를 N 번 전진시키면 **어느 장치가 어느 승인에 기댔는지** 사라진다."""
    pipe = pipeline("edge-a", "edge-b")
    pipe.register_version(version("v1", "edge-a"))
    pipe.register_version(version("v2", "edge-b"))
    first, second = lineage("det@v1"), lineage("det@v2")

    submit(pipe, [
        FleetRequest(device("pi-a", "edge-a"), unit("det-a", "edge-a"), first),
        FleetRequest(device("pi-b", "edge-b"), unit("det-b", "edge-b"), second),
    ])

    assert first is not second
    assert first.state is LearningState.DEPLOYED
    assert second.state is LearningState.DEPLOYED


# --------------------------------------------------------------- dry run

def test_the_dry_run_is_the_same_calculation_as_the_commit():
    pipe = pipeline("edge-a", "edge-c")
    pipe.register_version(version("v1", "edge-a"))
    requests = [
        FleetRequest(device("pi-a", "edge-a"), unit("det-a", "edge-a"), lineage("det@v1")),
        FleetRequest(device("pi-c", "edge-c"), unit("det-c", "edge-c"), lineage("det@v1")),
    ]

    plans = pipe.plan_fleet(requests, requirement())
    assert plans["det-a"].would_place is True
    assert plans["det-c"].refusal_reason == REFUSE_NO_ASSIGNMENT

    outcome = submit(pipe, requests)
    assert [entry.deployable_id for entry in outcome.placed] == ["det-a"]


def test_the_dry_run_changes_nothing():
    ledger = ReservationLedger((ResourceSlot("edge-a"),))
    pipe = pipeline("edge-a", reservations=ledger)
    pipe.register_version(version("v1", "edge-a"))
    requests = [FleetRequest(device("pi-a", "edge-a"), unit("det-a", "edge-a"),
                             lineage("det@v1"))]

    pipe.plan_fleet(requests, requirement())
    assert ledger.holders("edge-a") == (), "계획이 자원을 쥐면 보기만 해도 길이 막힌다"


# --------------------------------------------------------------- 모델↔이미지

def test_an_image_that_declares_another_version_is_refused():
    """**배포는 성공하고 올라간 모델만 다른 상태**를 막는다. 그 뒤의 모든 측정과
    계보 역추적이 엉뚱한 버전에 붙는다."""
    pipe = pipeline("edge-a")
    pipe.register_version(version("v2", "edge-a"))

    outcome = submit(pipe, [FleetRequest(
        device("pi-a", "edge-a"), unit("det-a", "edge-a", carries="det@v1"),
        lineage("det@v2"))])

    refused = outcome.refused[0].status
    assert refused.reason == REFUSE_IMAGE_VERSION_MISMATCH
    assert refused.version_carriage == CARRIAGE_MISMATCH


def test_a_matching_declaration_on_a_pinned_image_is_verified():
    pipe = pipeline("edge-a")
    pipe.register_version(version("v1", "edge-a"))

    outcome = submit(pipe, [FleetRequest(
        device("pi-a", "edge-a"), unit("det-a", "edge-a", carries="det@v1"),
        lineage("det@v1"))])

    assert outcome.placed[0].status.version_carriage == CARRIAGE_VERIFIED


def test_a_matching_declaration_on_a_moving_tag_is_not_verified():
    """**실제 k3s 로 돌려 보고 알았다**(2026-11-20): `mission-runtime:cpu` 태그로
    올린 pod 안의 패키지가 어제의 빌드였다. 선언은 맞았고 짐은 달랐다.

    거절하지는 않는다 — 태그 배포가 정상인 배치가 있다. 다만 확인된 것으로
    적지 않는다(AI-B-01: 미측정 항목은 구분해야 한다).
    """
    pipe = pipeline("edge-a")
    pipe.register_version(version("v1", "edge-a"))

    outcome = submit(pipe, [FleetRequest(
        device("pi-a", "edge-a"),
        unit("det-a", "edge-a", carries="det@v1", image=MOVING),
        lineage("det@v1"))])

    status = outcome.placed[0].status
    assert status.version_carriage == CARRIAGE_UNPINNED
    assert status.version_reference == "det@v1", "배포 자체는 정상이다"


def test_a_mismatch_beats_an_unpinned_tag_because_it_is_a_worse_fact():
    """태그가 움직이는 것은 "모른다" 이고, 다른 버전을 싣는다는 선언은 "틀렸다" 다."""
    pipe = pipeline("edge-a")
    pipe.register_version(version("v2", "edge-a"))

    outcome = submit(pipe, [FleetRequest(
        device("pi-a", "edge-a"),
        unit("det-a", "edge-a", carries="det@v1", image=MOVING),
        lineage("det@v2"))])

    assert outcome.refused[0].status.version_carriage == CARRIAGE_MISMATCH


def test_no_declaration_means_unverified_not_verified():
    """확인할 수 없는 것을 "맞다" 로 적으면 **확인하지 않은 것이 확인된 것으로**
    읽힌다(AI-B-01: 미측정 항목은 구분해야 한다). 올라가는 것은 정상이다 —
    모델을 싣지 않는 실행 단위도 같은 경로로 배포된다."""
    pipe = pipeline("edge-a")
    pipe.register_version(version("v1", "edge-a"))

    outcome = submit(pipe, [FleetRequest(
        device("pi-a", "edge-a"), unit("det-a", "edge-a"), lineage("det@v1"))])

    status = outcome.placed[0].status
    assert status.version_carriage == CARRIAGE_NOT_DECLARED
    assert status.version_reference == "det@v1"


def test_a_mismatched_image_does_not_hold_the_execution_area():
    """싼 거절이 자원을 쥐면 **맞는 후보가 영원히 못 올라간다.**"""
    ledger = ReservationLedger((ResourceSlot("edge-a"),))
    pipe = pipeline("edge-a", reservations=ledger)
    pipe.register_version(version("v2", "edge-a"))

    submit(pipe, [FleetRequest(device("pi-a", "edge-a"),
                               unit("det-a", "edge-a", carries="det@v1"),
                               lineage("det@v2"))])
    assert ledger.holders("edge-a") == ()


def test_the_bundle_declaration_carries_the_model_reference_through():
    """선언 한 건이 그 짐까지 적는다 — 코드 변경이 아니다(AI-B-09)."""
    from mission_runtime.runtime.deployment_bundle import bundle_from_dict

    bundle = bundle_from_dict({
        "bundle_id": "det-svc", "capability_kind": KIND,
        "image": "registry.internal/det@sha256:" + "a" * 64,
        "carries_model": "det@v1",
        "required_tags": ["edge-a"],
    })
    assert bundle.carries_model == "det@v1"
    assert bundle.to_deployable().carries_model == "det@v1"


def test_a_bundle_without_the_field_declares_nothing_rather_than_empty_string():
    from mission_runtime.runtime.deployment_bundle import bundle_from_dict

    bundle = bundle_from_dict({
        "bundle_id": "bridge", "capability_kind": "transport.bridge",
        "image": "registry.internal/bridge@sha256:" + "b" * 64,
    })
    assert bundle.carries_model is None
