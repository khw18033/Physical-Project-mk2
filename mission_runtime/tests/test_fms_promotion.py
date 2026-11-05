"""배선된 레코드 경로가 승격 사슬을 **실제로 돌리는지** 고정한다.

implements: AI-S-03, AI-S-05, AI-C-05, AI-C-19
covers: 콘솔의 융합 레코드가 승격 판정을 받는 것, 독립 소스가 모자라면 승격되지 않는
        것, 레지스트리가 없는 관측 장치는 사유와 함께 축소되는 것, 요청이 명령이
        아니라는 것, 승격 판정이 **요청으로만** 돌아가는 것

왜 이 파일이 따로 있는가: `tests/test_perception_loop.py` 는 사슬 자체를 보고, 여기서는
**그 사슬을 부르는 쪽이 실제로 있는지**를 본다. 둘을 한 파일에 두면 "모듈은 올바른데
아무도 부르지 않는" 상태가 다시 시험을 통과한다(`tests/test_module_wiring.py` 의 사유).
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONSOLE_DIR = PROJECT_ROOT / "tools" / "fms_console"
if str(CONSOLE_DIR) not in sys.path:
    sys.path.insert(0, str(CONSOLE_DIR))

from twin import (  # noqa: E402
    DeviceDetection,
    DevicePlacement,
    TwinFusionService,
)

from mission_runtime.contracts import data_dictionary as dd  # noqa: E402
from mission_runtime.contracts.capability import CapabilityState  # noqa: E402
from mission_runtime.contracts.profile import CompatibilityProfile  # noqa: E402
from mission_runtime.registry.capability_registry import (  # noqa: E402
    CapabilityRegistry,
    ProviderRegistration,
)
from mission_runtime.runtime import perception_loop as pl  # noqa: E402

ZONE = "z1"
PLACEMENTS = (
    DevicePlacement("cam-a", ZONE, (0.0, 0.0, 0.0), camera_id="a"),
    DevicePlacement("cam-b", ZONE, (10.0, 0.0, 180.0), camera_id="b"),
)
CENTRED_BBOX = (0.5, 0.4, 0.5, 0.6)


def registry(*kinds: str) -> CapabilityRegistry:
    reg = CapabilityRegistry()
    for kind in kinds:
        reg.register_local(ProviderRegistration(
            capability_kind=kind, provider_id=f"{kind}-p", version="1",
            compatibility=CompatibilityProfile()))
    return reg


def service(*, with_registry: bool = True) -> TwinFusionService:
    # **배치 어휘를 쓴다.** `detection` 같은 점 없는 이름으로 시험하면 통과하지만
    # 실제 manifest 는 `perception.detect` 를 쓰므로 운영에서는 모든 근거가
    # '만들 수 없음' 으로 떨어진다 — 그 어긋남을 시험이 잡아야 한다.
    registries = {"cam-a": registry("perception.detect", "perception.distance"),
                  "cam-b": registry("perception.detect")}
    instance = TwinFusionService(
        registry_for=(registries.get if with_registry else None))
    for placement in PLACEMENTS:
        instance.register_device(placement)
    return instance


def detection(detection_id: str, device_id: str, *, label: str) -> DeviceDetection:
    return DeviceDetection(
        detection_id=detection_id, device_id=device_id, track_local_id=1,
        frame_ref=f"frame-{device_id}", observed_at=1.0, bbox=CENTRED_BBOX,
        label=label, confidence=0.93, range_m=5.0, provider_id="detector")


def test_one_device_is_not_enough_to_promote_however_confident_it_is():
    instance = service()
    record = instance.ingest_detection(detection("d1", "cam-a", label="chair"))

    outcome = instance.promotion(record.object_id)

    assert outcome.confidence >= 0.9
    assert outcome.promotion_state == pl.PROMOTION_UNCONFIRMED
    assert "semantic_class" in outcome.unmet_evidence_kinds
    # 세는 쪽은 `(device_id, frame_ref)` 단위로 센다.
    assert outcome.evidence_assessment.evidence_count == 1


def test_two_independent_devices_agreeing_promote_the_record():
    instance = service()
    instance.ingest_detection(detection("d1", "cam-a", label="chair"))
    record = instance.ingest_detection(detection("d2", "cam-b", label="chair"))

    outcome = instance.promotion(record.object_id)

    assert outcome.promotion_state == pl.PROMOTION_CONFIRMED
    assert outcome.stop_decision is not None
    # 근거가 모였으면 더 요청하지 않는다.
    assert outcome.information_requests == ()


def test_the_same_device_and_frame_twice_is_one_observation():
    """같은 프레임을 두 번 읽은 것은 두 번의 확인이 아니다(AI-S-03, AI-S-06)."""
    instance = service()
    first = detection("d1", "cam-a", label="chair")
    second = DeviceDetection(
        detection_id="d2", device_id="cam-a", track_local_id=1,
        frame_ref=first.frame_ref, observed_at=1.0, bbox=CENTRED_BBOX,
        label="chair", confidence=0.88, range_m=5.0, provider_id="classifier")
    instance.ingest_detection(first)
    record = instance.ingest_detection(second)

    outcome = instance.promotion(record.object_id)

    assert outcome.evidence_assessment.evidence_count == 1
    assert outcome.evidence_assessment.duplicate_count == 1
    assert outcome.promotion_state == pl.PROMOTION_UNCONFIRMED


def test_an_observer_without_a_placement_registry_degrades_with_a_reason():
    instance = service(with_registry=False)
    record = instance.ingest_detection(detection("d1", "cam-a", label="chair"))

    result = instance.promotions(ZONE)
    outcome = instance.promotion(record.object_id)

    assert result.capability_state is CapabilityState.DEGRADED
    reasons = set(result.degraded_stage_reasons.values())
    assert pl.DEGRADE_NO_SELECTOR in reasons
    assert pl.DEGRADE_NO_PLANNER in reasons
    # 부족분은 조용히 사라지지 않고 요청으로 남는다.
    assert outcome.information_requests


def test_what_the_console_cannot_run_itself_goes_out_as_a_request_not_a_command():
    """콘솔에는 보조 실행기가 없다 — 그래서 고른 것은 **요청**으로 나간다(AI-C-19).

    침묵이 아니라 요청이어야 하는 이유: 모자란 레코드에 대해 아무 일도 일어나지
    않은 상태를 조용히 두면 그 이유가 어디에도 남지 않는다.
    """
    instance = service()
    record = instance.ingest_detection(detection("d1", "cam-a", label="chair"))

    requests = instance.promotion(record.object_id).information_requests

    assert requests
    assert any(r.information_request_reason == pl.REQUEST_AWAITS_EXECUTION
               for r in requests)
    for request in requests:
        body = request.as_dict()
        assert body[dd.OBJECT_ID] == record.object_id
        assert body[dd.NEEDED_INFORMATION]
        assert body[dd.OBSERVATION_CONDITIONS][dd.COORDINATE_FRAME] == "ZONE"
        assert body[dd.INFORMATION_REQUEST_REASON] in dd.INFORMATION_REQUEST_REASONS
        assert dd.COMMAND_ID not in body


def test_the_zone_snapshot_uses_only_dictionary_names():
    instance = service()
    instance.ingest_detection(detection("d1", "cam-a", label="chair"))

    body = instance.promotions(ZONE).as_dict()

    assert dd.unknown_fields(body) == ()
    assert dd.unknown_fields(body[dd.OBJECT_RECORDS][0]) == ()


def test_the_console_runs_the_chain_only_when_the_refresh_ledger_asks():
    """상시 갱신하면 아무도 보지 않는 구역의 판정까지 계속 돈다(AI-C-13, AI-O-01)."""
    from mission_runtime.runtime.refresh import RefreshLedger, Trigger, scope_of

    clock = [500.0]
    ledger = RefreshLedger(clock=lambda: clock[0])
    instance = service()
    instance.ingest_detection(detection("d1", "cam-a", label="chair"))
    seen: list[pl.LoopResult] = []
    scope = scope_of("twin", ZONE)

    first = ledger.request(scope, Trigger.OPERATOR_VIEW,
                           work=instance.promotion_work(ZONE, seen.append))
    second = ledger.request(scope, Trigger.OPERATOR_VIEW,
                            work=instance.promotion_work(ZONE, seen.append))

    assert first.performed and len(seen) == 1
    assert not second.performed and len(seen) == 1


def test_the_declared_kind_table_speaks_the_deployments_capability_vocabulary():
    """어휘가 갈리면 **대조 자체가 성립하지 않는다**(2026-11-04 에 실제로 갈려 있었다).

    `decision/evidence_gap.DEFAULT_KIND_PROVIDERS` 는 `detection` 처럼 점 없는 이름을
    쓰고 이 배치의 manifest 는 `perception.detect` 를 쓴다. 그대로 두면 모든 근거가
    "만들 수 없음" 으로 떨어져 **아무것도 승격되지 않고 요청도 나가지 않는다** — 그
    침묵은 통과하는 시험과 구분되지 않으므로 여기서 깨뜨린다.
    """
    import re

    from twin import (
        TWIN_KIND_PROVIDERS,
        TWIN_OBSERVATION_LEVELS,
        TWIN_PHYSICAL_ACTION_KINDS,
    )

    # **배치된 집합이 아니라 선언된 어휘**와 대조한다. 어느 현장에 그 provider 가
    # 없는 것은 정상이고(그때 그 근거는 '만들 수 없음' 이며 축소 경로다, AI-C-05),
    # 여기서 잡으려는 것은 **어느 선언에도 없는 이름**, 즉 오타와 어휘 표류다.
    pattern = re.compile(r'"capability_kind":\s*"([^"]+)"')
    declared: set[str] = set()
    for tree in ("config", "profiles"):
        for path in (PROJECT_ROOT / tree).rglob("*.json"):
            declared |= set(pattern.findall(path.read_text(encoding="utf-8")))
    named = (
        {kind for kinds in TWIN_KIND_PROVIDERS.values() for kind in kinds}
        | set(TWIN_OBSERVATION_LEVELS) | set(TWIN_PHYSICAL_ACTION_KINDS)
    )

    assert declared, "선언된 capability 어휘를 하나도 찾지 못했다 — 검출기가 눈을 감았다"
    assert named <= declared, sorted(named - declared)


# ---------------------------------------------------------------------------
# 콘솔 HTTP 경로가 실제로 사슬을 돈다 — "import 는 했는데 아무도 부르지 않는" 상태를
# 여기서 깨뜨린다. 실제 설정·실제 프로파일로 조립하고 가짜 데이터를 넣지 않는다.
# ---------------------------------------------------------------------------


def test_the_zone_view_carries_the_promotion_verdict_from_the_real_console():
    import importlib.util

    console_dir = PROJECT_ROOT / "tools" / "fms_console"
    for candidate in (console_dir, PROJECT_ROOT / "tools" / "status_ui"):
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
    spec = importlib.util.spec_from_file_location(
        "fms_console_serve_for_promotion", console_dir / "serve.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    from accounts import Caller

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        service = module.build_service(
            ui_config=PROJECT_ROOT / "config" / "status_ui.fms.example.json",
            zone_profile=PROJECT_ROOT / "profiles" / "domains.example.json",
            goal_kinds=PROJECT_ROOT / "profiles" / "goal_kinds.example.json",
            with_fleet=True,
            overlay_path=Path(tmp) / "edits.json",
        )
        admin = Caller.for_role("admin")
        service.ingest_detection(caller=admin, body={
            "detection_id": "p1", "device_id": "pi6", "track_local_id": 1,
            "frame_ref": "pi6/f1", "bbox": [0.48, 0.4, 0.52, 0.6],
            "label": "person", "confidence": 0.8, "range_m": 6.0,
        })
        view = service.twin_view("N4-1F-W", caller=admin)

    promotion = view["promotion"]
    assert promotion, "열었는데 승격 판정이 없으면 사슬이 돌지 않은 것이다"
    assert promotion[dd.CAPABILITY_STATE] in (
        "ACTIVE", "DEGRADED"), promotion[dd.CAPABILITY_STATE]
    assert promotion[dd.OBJECT_RECORDS], "탐지가 하나 들어왔으면 레코드도 하나다"
    row = promotion[dd.OBJECT_RECORDS][0]
    # 한 장치만 보았으므로 확정이 아니다 — 그것이 AI-S-03 의 요점이다.
    assert row[dd.PROMOTION_STATE] == pl.PROMOTION_UNCONFIRMED
    assert row[dd.COORDINATE_FRAME] == "ZONE"
    assert row[dd.FRAME_REF] == "pi6/f1"


def test_an_empty_zone_is_not_reported_as_fully_active():
    """볼 것이 없었던 회차를 ACTIVE 로 적으면 **없는 단계가 숨는다**.

    축소는 레코드의 성질이 아니라 조립의 성질이다 — 빈 구역에서도 무엇이 빠져
    있는지 말해야 운영자가 무엇을 들여야 하는지 안다(AI-C-05, AI-O-06).
    """
    result = service().promotions(ZONE)

    assert result.object_records == ()
    assert result.capability_state is CapabilityState.DEGRADED
    assert result.degraded_stage_reasons
