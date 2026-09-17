"""implements: AI-B-04, AI-B-03, AI-B-06, AI-C-05, AI-O-02
covers: required tags -> nodeSelector labels (preferred never), illegal tag,
        first apply starts every deployable provider, unchanged table makes
        no call, provider swap = stop then start, DISABLED = stop only, one
        rejected start does not block the other kind, in-process providers
        never reach the control provider, LocalControlSupervisor and a fake
        ControlProvider yield the same call sequence behind the reconciler.
"""

import pytest

from perception_framework.contracts.capability import CapabilityState
from perception_framework.contracts.profile import CompatibilityProfile
from perception_framework.execution.control import ControlResult, LocalControlSupervisor, TargetStatus
from perception_framework.providers.fakes import InMemoryObservabilityProvider
from perception_framework.runtime.application import CapabilityResolution
from perception_framework.runtime.placement import (
    LABEL_PREFIX,
    PlacementAction,
    PlacementReconciler,
    node_selector_for,
)

from conftest import registration


class FakeControl:
    """Records every request; rejects targets it was told to reject."""

    def __init__(self, reject: dict[str, str] | None = None) -> None:
        self.calls: list[tuple[str, str, dict | None, str]] = []
        self._reject = reject or {}

    def request(self, command, target_id, params=None, *, requested_by="unknown"):
        self.calls.append((command, target_id, params, requested_by))
        if target_id in self._reject:
            return ControlResult(False, None, rejection_reason=self._reject[target_id])
        status = TargetStatus.RUNNING if command == "start" else TargetStatus.STOPPED
        return ControlResult(True, status)

    def get_status(self, target_id):
        return TargetStatus.STOPPED

    @property
    def sequence(self) -> list[tuple[str, str]]:
        return [(command, target) for command, target, _, _ in self.calls]


def resolved(kind, provider_id, *, hw_tags=(), preferred=(), state=CapabilityState.ACTIVE):
    reg = registration(kind, provider_id, hw_tags=hw_tags, preferred=preferred)
    return CapabilityResolution(kind, state, reg, "selected")


def disabled(kind, reason="no_compatible_provider_within_budget"):
    return CapabilityResolution(kind, CapabilityState.DISABLED, None, reason)


PARAMS = {
    "detect-gpu": {"image": "registry.internal/detect:1.2", "command": ["python", "-m", "detect"]},
    "detect-cpu": {"image": "registry.internal/detect-cpu:1.0"},
    "track-a": {"image": "registry.internal/track:0.9"},
}


# --- (1)(2) tag -> label ---------------------------------------------------


def test_required_tags_become_labels_and_preferred_tags_do_not():
    """AI-B-04: 선호 자원은 순위이지 제약이 아니다 — 라벨로 만들면 노드를 배제한다."""
    profile = CompatibilityProfile(
        required_hw_tags=("compute.gpu", "sensor.sonar"),
        preferred_hw_tags=("compute.npu",),
    )

    selector = node_selector_for(profile)

    assert selector == {
        f"{LABEL_PREFIX}compute.gpu": "true",
        f"{LABEL_PREFIX}sensor.sonar": "true",
    }
    assert not any("npu" in key for key in selector)


def test_no_required_tags_means_no_selector():
    assert node_selector_for(CompatibilityProfile()) == {}
    assert node_selector_for(CompatibilityProfile(preferred_hw_tags=("compute.gpu",))) == {}


@pytest.mark.parametrize(
    "bad",
    ["", "-leading", "trailing.", "has space", "a/b", "x" * 64, "über"],
)
def test_illegal_label_name_raises(bad):
    with pytest.raises(ValueError):
        node_selector_for(CompatibilityProfile(required_hw_tags=(bad,)))


# --- (3) first apply --------------------------------------------------------


def test_first_apply_starts_every_deployable_provider_with_image_and_selector():
    control = FakeControl()
    observability = InMemoryObservabilityProvider()
    reconciler = PlacementReconciler(control, deployment_params=PARAMS, observability=observability)

    actions = reconciler.apply({
        "perception.detect": resolved("perception.detect", "detect-gpu", hw_tags=("compute.gpu",)),
        "perception.track": resolved("perception.track", "track-a"),
    })

    assert control.sequence == [("start", "detect-gpu"), ("start", "track-a")]
    _, _, detect_params, requested_by = control.calls[0]
    assert detect_params == {
        "image": "registry.internal/detect:1.2",
        "command": ["python", "-m", "detect"],
        "node_selector": {f"{LABEL_PREFIX}compute.gpu": "true"},
    }
    assert requested_by == "placement_reconciler"
    # No required tags -> the key is omitted, not sent as an empty dict.
    assert "node_selector" not in control.calls[1][2]
    assert all(a.accepted for a in actions)
    assert reconciler.bound_provider("perception.detect") == "detect-gpu"
    assert reconciler.bound_provider("perception.track") == "track-a"

    events = [e for e in observability.events if e.name == "placement_applied"]
    assert [e.payload["command"] for e in events] == ["start", "start"]
    assert events[0].payload == {
        "capability_kind": "perception.detect",
        "provider_id": "detect-gpu",
        "command": "start",
        "accepted": True,
        "rejection_reason": None,
    }


def test_start_params_do_not_alias_the_caller_dict():
    control = FakeControl()
    params = {"detect-gpu": {"image": "img"}}
    reconciler = PlacementReconciler(control, deployment_params=params)

    reconciler.apply({"perception.detect": resolved("perception.detect", "detect-gpu", hw_tags=("compute.gpu",))})

    assert "node_selector" not in params["detect-gpu"]


# --- (4) idempotence --------------------------------------------------------


def test_identical_resolutions_make_no_control_call():
    control = FakeControl()
    reconciler = PlacementReconciler(control, deployment_params=PARAMS)
    table = {
        "perception.detect": resolved("perception.detect", "detect-gpu"),
        "perception.track": resolved("perception.track", "track-a"),
    }
    reconciler.apply(table)
    first = len(control.calls)

    actions = reconciler.apply(table)

    assert actions == ()
    assert len(control.calls) == first


# --- (5) swap ---------------------------------------------------------------


def test_provider_swap_stops_old_then_starts_new_in_that_order():
    control = FakeControl()
    reconciler = PlacementReconciler(control, deployment_params=PARAMS)
    reconciler.apply({"perception.detect": resolved("perception.detect", "detect-gpu")})
    control.calls.clear()

    actions = reconciler.apply({"perception.detect": resolved("perception.detect", "detect-cpu")})

    assert control.sequence == [("stop", "detect-gpu"), ("start", "detect-cpu")]
    assert [(a.command, a.provider_id) for a in actions] == [("stop", "detect-gpu"), ("start", "detect-cpu")]
    assert reconciler.bound_provider("perception.detect") == "detect-cpu"


# --- (6) DISABLED -----------------------------------------------------------


def test_disabled_kind_only_stops_the_old_provider():
    control = FakeControl()
    reconciler = PlacementReconciler(control, deployment_params=PARAMS)
    reconciler.apply({
        "perception.detect": resolved("perception.detect", "detect-gpu"),
        "perception.track": resolved("perception.track", "track-a"),
    })
    control.calls.clear()

    actions = reconciler.apply({
        "perception.detect": resolved("perception.detect", "detect-gpu"),
        "perception.track": disabled("perception.track"),
    })

    assert control.sequence == [("stop", "track-a")]
    assert actions == (PlacementAction("perception.track", "track-a", "stop", True, None),)
    assert reconciler.bound_provider("perception.track") is None
    assert reconciler.bound_provider("perception.detect") == "detect-gpu"


def test_kind_that_vanishes_from_the_table_is_stopped_too():
    control = FakeControl()
    reconciler = PlacementReconciler(control, deployment_params=PARAMS)
    reconciler.apply({"perception.track": resolved("perception.track", "track-a")})
    control.calls.clear()

    reconciler.apply({})

    assert control.sequence == [("stop", "track-a")]
    assert reconciler.bound_provider("perception.track") is None


# --- (7) rejection isolation (AI-C-05) -------------------------------------


def test_rejected_start_is_reported_and_does_not_block_the_other_kind():
    control = FakeControl(reject={"detect-gpu": "not_permitted"})
    observability = InMemoryObservabilityProvider()
    reconciler = PlacementReconciler(control, deployment_params=PARAMS, observability=observability)

    actions = reconciler.apply({
        "perception.detect": resolved("perception.detect", "detect-gpu"),
        "perception.track": resolved("perception.track", "track-a"),
    })

    by_kind = {a.kind: a for a in actions}
    assert by_kind["perception.detect"] == PlacementAction(
        "perception.detect", "detect-gpu", "start", False, "not_permitted"
    )
    assert by_kind["perception.track"].accepted is True
    assert control.sequence == [("start", "detect-gpu"), ("start", "track-a")]
    # The rejected kind is not bound, so the next apply retries it.
    assert reconciler.bound_provider("perception.detect") is None
    assert reconciler.bound_provider("perception.track") == "track-a"

    warnings = [e for e in observability.events if e.severity == "warning"]
    assert len(warnings) == 1
    assert warnings[0].payload["rejection_reason"] == "not_permitted"
    assert warnings[0].payload["capability_kind"] == "perception.detect"


def test_rejected_start_is_retried_on_the_next_apply():
    control = FakeControl(reject={"detect-gpu": "orchestrator_unavailable"})
    reconciler = PlacementReconciler(control, deployment_params=PARAMS)
    table = {"perception.detect": resolved("perception.detect", "detect-gpu")}
    reconciler.apply(table)
    control._reject.clear()

    actions = reconciler.apply(table)

    assert control.sequence == [("start", "detect-gpu"), ("start", "detect-gpu")]
    assert actions[0].accepted is True
    assert reconciler.bound_provider("perception.detect") == "detect-gpu"


def test_illegal_tag_on_one_provider_is_a_rejection_not_an_exception():
    control = FakeControl()
    reconciler = PlacementReconciler(control, deployment_params=PARAMS)

    actions = reconciler.apply({
        "perception.detect": resolved("perception.detect", "detect-gpu", hw_tags=("bad tag",)),
        "perception.track": resolved("perception.track", "track-a"),
    })

    by_kind = {a.kind: a for a in actions}
    assert by_kind["perception.detect"].accepted is False
    assert by_kind["perception.detect"].rejection_reason.startswith("invalid_placement_tag")
    assert control.sequence == [("start", "track-a")]


def test_control_provider_raising_is_a_rejection_not_a_crash():
    class Exploding(FakeControl):
        def request(self, command, target_id, params=None, *, requested_by="unknown"):
            raise ConnectionError("api server down")

    reconciler = PlacementReconciler(Exploding(), deployment_params=PARAMS)

    (action,) = reconciler.apply({"perception.detect": resolved("perception.detect", "detect-gpu")})

    assert action.accepted is False
    assert action.rejection_reason == "control_error:ConnectionError"


def test_observability_failure_never_blocks_placement():
    class BrokenSink:
        def record_metric(self, *a, **k):
            raise RuntimeError("down")

        def record_event(self, *a, **k):
            raise RuntimeError("down")

    control = FakeControl()
    reconciler = PlacementReconciler(control, deployment_params=PARAMS, observability=BrokenSink())

    (action,) = reconciler.apply({"perception.detect": resolved("perception.detect", "detect-gpu")})

    assert action.accepted is True
    assert control.sequence == [("start", "detect-gpu")]


# --- (8) in-process providers ----------------------------------------------


def test_in_process_provider_never_reaches_the_control_provider():
    control = FakeControl()
    observability = InMemoryObservabilityProvider()
    reconciler = PlacementReconciler(control, deployment_params=PARAMS, observability=observability)

    actions = reconciler.apply({
        "risk.rule_based": resolved("risk.rule_based", "rules-local"),
        "perception.track": resolved("perception.track", "track-a"),
    })

    assert control.sequence == [("start", "track-a")]
    assert PlacementAction("risk.rule_based", "rules-local", "in_process", True, None) in actions
    assert reconciler.bound_provider("risk.rule_based") == "rules-local"

    # Acknowledged once — not on every apply, and never stopped through control.
    control.calls.clear()
    assert reconciler.apply({
        "risk.rule_based": resolved("risk.rule_based", "rules-local"),
        "perception.track": resolved("perception.track", "track-a"),
    }) == ()
    reconciler.apply({"risk.rule_based": disabled("risk.rule_based"), "perception.track": disabled("perception.track")})
    assert control.sequence == [("stop", "track-a")]
    assert reconciler.bound_provider("risk.rule_based") is None


# --- (9) ControlProvider interchangeability (AI-B-03 / 원칙 #2) --------------


def test_local_supervisor_and_fake_yield_the_same_call_sequence():
    """Whatever ControlProvider is plugged in, the reconciler issues the same
    commands in the same order for the same resolution history."""
    history = [
        {
            "perception.detect": resolved("perception.detect", "detect-gpu", hw_tags=("compute.gpu",)),
            "perception.track": resolved("perception.track", "track-a"),
            "risk.rule_based": resolved("risk.rule_based", "rules-local"),
        },
        {
            "perception.detect": resolved("perception.detect", "detect-cpu"),
            "perception.track": resolved("perception.track", "track-a"),
            "risk.rule_based": resolved("risk.rule_based", "rules-local"),
        },
        {
            "perception.detect": resolved("perception.detect", "detect-cpu"),
            "perception.track": disabled("perception.track"),
            "risk.rule_based": resolved("risk.rule_based", "rules-local"),
        },
    ]

    fake = FakeControl()
    supervisor = LocalControlSupervisor()
    via_fake = PlacementReconciler(fake, deployment_params=PARAMS)
    via_supervisor = PlacementReconciler(supervisor, deployment_params=PARAMS)

    fake_actions = [via_fake.apply(table) for table in history]
    supervisor_actions = [via_supervisor.apply(table) for table in history]

    assert fake_actions == supervisor_actions
    assert fake.sequence == [(e.command, e.target_id) for e in supervisor.audit_log]
    assert fake.sequence == [
        ("start", "detect-gpu"),
        ("start", "track-a"),
        ("stop", "detect-gpu"),
        ("start", "detect-cpu"),
        ("stop", "track-a"),
    ]
    assert all(e.requested_by == "placement_reconciler" for e in supervisor.audit_log)
    assert supervisor.get_status("detect-cpu") is TargetStatus.RUNNING
    assert supervisor.get_status("detect-gpu") is TargetStatus.STOPPED
    assert supervisor.get_status("track-a") is TargetStatus.STOPPED
    assert supervisor.get_status("rules-local") is TargetStatus.STOPPED  # never touched
