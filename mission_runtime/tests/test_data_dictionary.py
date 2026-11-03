"""implements: AI-C-01, AI-C-14
covers: common field names, producer payload checks, and data-plane mapping
"""

import pytest

from mission_runtime.common.data_plane import DataPlane
from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.contracts.data_dictionary import UnknownFieldError


def test_core_payload_names_are_registered_in_the_dictionary():
    payload = {
        dd.DEVICE_ID: "device-1",
        dd.OBSERVED_AT: 1720000000.0,
        dd.OBSERVATION_NAME: "water_level",
        dd.OBSERVATION_VALUE: 2.4,
        dd.COORDINATE_FRAME: "GLOBAL",
    }

    assert dd.assert_known(payload) is payload
    assert dd.unknown_fields(payload) == ()


def test_ad_hoc_field_names_are_reported_during_development():
    payload = {
        dd.DEVICE_ID: "device-1",
        "deviceId": "device-1",
    }

    assert dd.unknown_fields(payload) == ("deviceId",)
    with pytest.raises(UnknownFieldError):
        dd.assert_known(payload)


def test_specs_keep_meaning_producer_consumer_and_plane_together():
    spec = dd.spec_for(dd.COMMAND_ID)

    assert spec.name == "command_id"
    assert "명령" in spec.meaning
    assert "백엔드" in spec.produced_by
    assert "말단" in spec.consumed_by
    assert spec.plane is DataPlane.TASK


def test_node_pose_is_kept_separate_from_its_confidence_and_source():
    # 2026-09 재설계: 위치 자체와 "어떤 방법으로 얻었는지"를 같은 이름에 섞지 않는다 —
    # 고정 카메라가 본 위치와 로봇 자체 추정 위치는 신뢰도가 다르므로 근거로 구분한다.
    pose_spec = dd.spec_for(dd.NODE_POSE)
    source_spec = dd.spec_for(dd.POSE_SOURCE)
    uncertainty_spec = dd.spec_for(dd.POSE_UNCERTAINTY)

    assert pose_spec.plane is DataPlane.TASK
    assert "확정값 아님" in pose_spec.meaning
    assert source_spec.name != pose_spec.name
    assert uncertainty_spec.name != pose_spec.name


def test_camera_extrinsic_is_distinct_from_dynamic_node_pose():
    # 고정 카메라 위치는 매 틱 갱신되는 node_pose가 아니라 보정 프로파일처럼
    # 버전 관리되는 별도 개념이다(AI-E-02).
    extrinsic_spec = dd.spec_for(dd.CAMERA_EXTRINSIC)

    assert "엣지 보정" in extrinsic_spec.produced_by
    assert extrinsic_spec.name != dd.NODE_POSE


def test_unknown_spec_lookup_fails_closed():
    with pytest.raises(UnknownFieldError):
        dd.spec_for("undocumented_name")


def test_plane_queries_keep_business_and_observability_names_separate():
    task_fields = dd.fields_on_plane(DataPlane.TASK)
    observability_fields = dd.fields_on_plane(DataPlane.OBSERVABILITY)

    assert dd.COMMAND_OUTCOME in task_fields
    assert dd.TRACE_ID in observability_fields
    assert dd.OVERLAY_STATE in observability_fields
    assert set(task_fields).isdisjoint(observability_fields)


def test_every_dictionary_entry_has_a_unique_name_and_nonempty_contract():
    names = [entry.name for entry in dd.DATA_DICTIONARY.values()]

    assert len(names) == len(set(names))
    for entry in dd.DATA_DICTIONARY.values():
        assert entry.meaning
        assert entry.value_kind
        assert entry.produced_by
        assert entry.consumed_by


# --- 회귀 방지: 경계를 넘는 payload 는 사전에 등록된 이름만 쓴다 --------------
# 여기 걸리는 것은 "새 이름을 쓰지 말라"는 뜻이 아니라 "쓰기 전에 사전에 등록하라"는
# 뜻이다(AI-C-01). 검사 대상은 실제로 파트·모듈 경계를 넘는 payload 로 한정한다.

def test_wire_envelope_uses_only_dictionary_names():
    """봉투 필드는 파트 경계를 넘는다. 본문(payload) 내부 이름은 contracts/ai 스키마 소관."""
    from mission_runtime.integration.wire import MessageContext, build_message

    message = build_message(
        MessageContext(source_id="cam-1", node_id="edge-1", entity_id="e-1",
                       zone_id="zone-a", sequence_id=3),
        "detections", {"detections": []}, coordinate_frame="IMAGE",
    )

    assert dd.unknown_fields(message) == ()


def test_resource_sample_payload_uses_only_dictionary_names():
    from mission_runtime.collection.sampler import ResourceSample

    sample = ResourceSample(sampled_at=1.0, rss_mib=12.0, cpu_percent=3.0,
                            energy_uj=5, temperature_c=41.0)

    assert dd.unknown_fields(sample.as_payload()) == ()


def _session_entries():
    from mission_runtime.collection.session import CollectionSession
    from mission_runtime.observability.experiment import ExperimentRecorder, RunHeader

    class _Worker:
        worker_id = "w-1"
        source_group = "det_a"

        def is_available(self):
            return True

        def run(self, frame):
            return [{"kind": "region", "confidence": 0.8, "region": (0, 0, 1, 1),
                     "object_id": "obj-1"}]

    class _BadWorker(_Worker):
        worker_id = "w-2"

        def run(self, frame):
            raise RuntimeError("boom")

    class _Media:
        _frames = [object()]

        def is_available(self):
            return True

        def source_id(self):
            return "cam-1"

        def read_frame(self):
            return self._frames.pop() if self._frames else None

    session = CollectionSession(recorder=ExperimentRecorder(RunHeader("run-1", "d-1")),
                                workers=[_Worker(), _BadWorker()])
    session.set_available_groups({"det_a"}, reason="startup")
    session.run(_Media())
    return session.recorder.entries


def test_collection_session_capture_payloads_use_only_dictionary_names():
    """수집 세션이 run bundle 로 내보내는 이름 — 시나리오 러너가 이걸 읽는다."""
    checked = {"capability", "worker", "fault"}
    entries = [e for e in _session_entries() if e.channel in checked]

    assert entries, "세션이 아무것도 기록하지 않았다면 검사가 무의미하다"
    for entry in entries:
        assert dd.unknown_fields(entry.payload) == (), (entry.channel, entry.payload)


# -- STATE_CHANGE_REASON is a controlled vocabulary (2026-09-17, P2) ---------


def test_every_selector_reason_constant_is_in_the_dictionary_vocabulary():
    """The selector defines the strings; the dictionary owns the vocabulary.
    A new REASON_* constant that is not registered here fails this test —
    that is how the vocabulary stays closed instead of drifting back to
    free text."""
    from mission_runtime.selection import selector

    constants = {v for k, v in vars(selector).items() if k.startswith("REASON_") and isinstance(v, str)}
    assert constants  # guard against the prefix being renamed silently
    assert constants <= set(dd.STATE_CHANGE_REASONS)


def test_resolver_and_egress_gate_reasons_are_in_the_vocabulary():
    from mission_runtime.contracts.capability import CapabilityRequirement
    from mission_runtime.contracts.profile import DeploymentProfile, ResourceBudget
    from mission_runtime.registry.capability_registry import CapabilityRegistry
    from mission_runtime.runtime.application import CapabilitySpec, ZoneApplication

    app = ZoneApplication(
        DeploymentProfile(domain_id="t", active_capability_kinds=("a", "b")),
        CapabilityRegistry(),
        [
            CapabilitySpec("a", is_core=True, requirement=CapabilityRequirement(required=("x",))),
            CapabilitySpec("b"),
        ],
    )
    reasons = {r.reason for r in app.resolve(ResourceBudget(1, 1)).values()}

    assert reasons == {"missing_required:x", "core_capability_unplaced"}
    assert {dd.state_change_reason_token(r) for r in reasons} <= set(dd.STATE_CHANGE_REASONS)


def test_residency_reason_constants_are_in_the_dictionary_vocabulary():
    """배치 축(`runtime/residency.py`)도 선택기와 같은 규약을 따른다: 모듈이
    문자열을 정하고 사전이 어휘를 소유한다. 이 어휘를 STATE_CHANGE_REASONS와
    합치지 않는 이유는 질문이 다르기 때문이다 — "지금 돌 수 있는가"와
    "이 장치 안에 있어야 하는가"가 같은 칸에 들어가면 '예산이 모자라서
    엣지로 갔다'와 '링크가 나빠서 말단으로 왔다'를 구분할 수 없다."""
    from mission_runtime.contracts.profile import OUTAGE_BEHAVIORS
    from mission_runtime.ondevice.link_handover import LinkPosture
    from mission_runtime.runtime import residency

    assert set(residency.LINK_POSTURE_REASONS) <= set(dd.LINK_POSTURE_REASONS)
    assert set(residency.RESIDENCY_REASONS) <= set(dd.RESIDENCY_DECISION_REASONS)
    assert set(residency.RESIDENCY_VIOLATIONS) <= set(dd.RESIDENCY_VIOLATIONS)
    assert set(OUTAGE_BEHAVIORS) == set(dd.OUTAGE_BEHAVIOR_VALUES)
    # 배치 시점과 운행 중 전환이 같은 자세 어휘를 쓴다(AI-N-03).
    assert set(dd.LINK_POSTURES) == {p.value for p in LinkPosture}
    assert set(dd.CAPABILITY_RESIDENCIES) == {r.value for r in residency.Residency}


def test_residency_field_specs_list_their_vocabulary_not_str():
    for name in (dd.CAPABILITY_RESIDENCY, dd.RESIDENCY_DECISION_REASON, dd.LINK_POSTURE,
                 dd.LINK_POSTURE_REASON, dd.OUTAGE_BEHAVIOR):
        assert dd.spec_for(name).value_kind != "str"


def test_reason_token_strips_only_the_data_suffix():
    assert dd.state_change_reason_token("missing_required:media.video_input,perception.detect") == "missing_required"
    assert dd.state_change_reason_token("required_hw_tag_missing:compute.gpu") == "required_hw_tag_missing"
    assert dd.state_change_reason_token("selected") == "selected"


def test_state_change_reason_spec_lists_the_vocabulary_not_str():
    spec = dd.spec_for(dd.STATE_CHANGE_REASON)
    assert spec.value_kind != "str"
    assert set(spec.value_kind.split("|")) == set(dd.STATE_CHANGE_REASONS)


def test_device_probe_reason_constants_are_in_their_own_vocabulary():
    """연결 검증 하네스(`tools/hw_smoke/smoke.py`)도 같은 규약을 따른다: 모듈이
    문자열을 정하고 사전이 어휘를 소유한다. STATE_CHANGE_REASONS와 별개인 이유는
    질문이 다르기 때문이다 — "이 capability가 돌 수 있는가"와 "이 장치에 닿는가"가
    같은 칸에 들어가면 'provider 미등록'과 'SSH 거부'를 구분할 수 없다."""
    import sys
    from pathlib import Path

    framework_dir = str(Path(__file__).resolve().parents[1])
    if framework_dir not in sys.path:
        sys.path.insert(0, framework_dir)
    from tools.hw_smoke import smoke

    constants = {v for k, v in vars(smoke).items()
                 if k.startswith("PROBE_") and not k.startswith("PROBE_KIND") and isinstance(v, str)}
    assert constants
    assert constants <= set(dd.DEVICE_PROBE_REASONS)
    assert set(dd.DEVICE_PROBE_REASONS).isdisjoint(dd.STATE_CHANGE_REASONS)
    spec = dd.spec_for(dd.DEVICE_PROBE_REASON)
    assert set(spec.value_kind.split("|")) == set(dd.DEVICE_PROBE_REASONS)
    assert spec.plane is DataPlane.OBSERVABILITY
    for name in (dd.DEVICE_PROBE_LEVEL, dd.PROBED_AT):
        assert dd.spec_for(name).plane is DataPlane.OBSERVABILITY
        assert "연결 검증" in dd.spec_for(name).produced_by


def test_execution_plan_names_are_registered():
    """PLAN_ID / REQUESTER_ROLE (runtime/execution_plan.py, 2026-09-28) are dictionary names,
    and the plan's own as_dict() uses them."""
    from mission_runtime.runtime.execution_plan import build_plan

    assert dd.spec_for(dd.PLAN_ID).plane is DataPlane.OBSERVABILITY
    assert dd.spec_for(dd.REQUESTER_ROLE).plane is DataPlane.TASK
    d = build_plan("f", {}).as_dict()
    assert dd.PLAN_ID in d and dd.CORRELATION_ID in d
