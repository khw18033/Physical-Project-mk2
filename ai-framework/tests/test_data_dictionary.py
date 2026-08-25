"""tests for: AI-C-01, AI-C-14
covers: common field names, producer payload checks, and data-plane mapping
"""

import pytest

from ai_framework.common.data_plane import DataPlane
from ai_framework.contracts import data_dictionary as dd
from ai_framework.contracts.data_dictionary import UnknownFieldError


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
