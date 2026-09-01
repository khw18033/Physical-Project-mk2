"""implements: AI-C-01, AI-C-14
covers: common field names, producer payload checks, and data-plane mapping
"""

import pytest

from perception_framework.common.data_plane import DataPlane
from perception_framework.contracts import data_dictionary as dd
from perception_framework.contracts.data_dictionary import UnknownFieldError


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
    from perception_framework.integration.wire import MessageContext, build_message

    message = build_message(
        MessageContext(source_id="cam-1", node_id="edge-1", entity_id="e-1",
                       zone_id="zone-a", sequence_id=3),
        "detections", {"detections": []}, coordinate_frame="IMAGE",
    )

    assert dd.unknown_fields(message) == ()


def test_resource_sample_payload_uses_only_dictionary_names():
    from perception_framework.collection.sampler import ResourceSample

    sample = ResourceSample(sampled_at=1.0, rss_mib=12.0, cpu_percent=3.0,
                            energy_uj=5, temperature_c=41.0)

    assert dd.unknown_fields(sample.as_payload()) == ()


def _session_entries():
    from perception_framework.collection.session import CollectionSession
    from perception_framework.observability.experiment import ExperimentRecorder, RunHeader

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
