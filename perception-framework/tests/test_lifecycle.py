"""implements: AI-B-05"""

from perception_framework.execution.lifecycle import ComponentState, LifecycleManager


def test_healthy_deploy_activates_and_remembers_last_good_version():
    manager = LifecycleManager()
    manager.register("perception", is_core=True)

    manager.deploy("perception", "v1", health_check_passes=True)

    assert manager.state_of("perception") == ComponentState.RUNNING


def test_failed_deploy_rolls_back_to_last_known_good_version():
    manager = LifecycleManager()
    manager.register("perception", is_core=True)
    manager.deploy("perception", "v1", health_check_passes=True)

    component = manager.deploy("perception", "v2-broken", health_check_passes=False)

    assert component.active_version == "v1"
    assert manager.state_of("perception") == ComponentState.RUNNING


def test_optional_component_without_prior_good_version_degrades_not_stops():
    manager = LifecycleManager()
    manager.register("aux-classifier", is_core=False)

    manager.deploy("aux-classifier", "v1-broken", health_check_passes=False)

    assert manager.state_of("aux-classifier") == ComponentState.DEGRADED


def test_optional_component_failure_does_not_affect_running_core_component():
    manager = LifecycleManager()
    manager.register("perception", is_core=True)
    manager.register("aux-classifier", is_core=False)
    manager.deploy("perception", "v1", health_check_passes=True)

    manager.deploy("aux-classifier", "v1-broken", health_check_passes=False)

    assert manager.state_of("perception") == ComponentState.RUNNING
    assert manager.core_components_all_running() is True
