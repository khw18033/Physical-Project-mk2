"""implements: AI-B-03"""

from perception_framework.execution.control import LocalControlSupervisor, TargetStatus


def test_start_command_is_accepted_and_status_updates():
    supervisor = LocalControlSupervisor()

    result = supervisor.request("start", "perception-node-1", requested_by="operator-1")

    assert result.accepted is True
    assert result.final_status == TargetStatus.RUNNING
    assert supervisor.get_status("perception-node-1") == TargetStatus.RUNNING


def test_restart_of_unknown_target_is_rejected_with_reason():
    supervisor = LocalControlSupervisor()

    result = supervisor.request("restart", "never-started")

    assert result.accepted is False
    assert result.rejection_reason == "unknown_target"


def test_unsupported_command_is_rejected_not_raised():
    supervisor = LocalControlSupervisor()

    result = supervisor.request("teleport", "perception-node-1")

    assert result.accepted is False
    assert "unsupported_command" in result.rejection_reason


def test_audit_log_and_trace_log_are_kept_separate():
    supervisor = LocalControlSupervisor()

    supervisor.request("start", "perception-node-1", requested_by="operator-1")

    assert len(supervisor.audit_log) == 1
    assert supervisor.audit_log[0].requested_by == "operator-1"
    assert len(supervisor.trace_log) == 1
    assert supervisor.trace_log[0].latency_ms >= 0
    # the two logs are genuinely distinct records, not one merged log.
    assert not hasattr(supervisor.audit_log[0], "latency_ms")
    assert not hasattr(supervisor.trace_log[0], "requested_by")
