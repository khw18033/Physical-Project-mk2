"""tests for: AI-N-02"""

from ai_framework.ondevice.config_apply import ConfigApplier, ConfigUpdate


def test_first_update_must_be_full_delta_alone_is_rejected():
    applier = ConfigApplier()

    accepted = applier.apply(ConfigUpdate(version=1, full=False, items={"a": 1}))

    assert accepted is False
    assert applier.active_version is None


def test_full_update_establishes_baseline():
    applier = ConfigApplier()

    accepted = applier.apply(ConfigUpdate(version=1, full=True, items={"a": 1, "b": 2}))

    assert accepted is True
    assert applier.active_config == {"a": 1, "b": 2}


def test_delta_update_merges_only_changed_keys():
    applier = ConfigApplier()
    applier.apply(ConfigUpdate(version=1, full=True, items={"a": 1, "b": 2}))

    applier.apply(ConfigUpdate(version=2, full=False, items={"b": 20}))

    assert applier.active_config == {"a": 1, "b": 20}
    assert applier.active_version == 2


def test_failed_validation_keeps_the_existing_good_configuration():
    applier = ConfigApplier(validate_fn=lambda c: c.get("a", 0) >= 0)
    applier.apply(ConfigUpdate(version=1, full=True, items={"a": 1}))

    accepted = applier.apply(ConfigUpdate(version=2, full=False, items={"a": -5}))

    assert accepted is False
    assert applier.active_config == {"a": 1}
    assert applier.active_version == 1


def test_no_external_config_ever_applied_is_a_valid_starting_state():
    applier = ConfigApplier()

    assert applier.active_config == {}
    assert applier.active_version is None
