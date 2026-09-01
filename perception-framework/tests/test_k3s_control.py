"""implements: AI-B-03, AI-B-05, AI-B-07, AI-C-12
covers: same ControlProvider contract as the standalone supervisor,
        orchestrator absence degrades instead of failing, audit/trace stay
        separate, real cluster start/stop/status when a cluster is present

Cluster tests skip when no API server answers — which is also the
requirement's own fallback case (AI-B-05: 오케스트레이터가 일시적으로 사용할
수 없어도 이미 실행 중인 핵심 기능은 계속 동작해야 한다).
"""

import shutil
import subprocess
import time
import uuid

import pytest

from perception_framework.execution.control import LocalControlSupervisor, TargetStatus
from perception_framework.providers.adapters import ControlProvider
from perception_framework.providers.k3s import K3sControlProvider

TEST_IMAGE = "busybox:latest"


def cluster_reachable() -> bool:
    if shutil.which("kubectl") is None:
        return False
    try:
        return (
            subprocess.run(
                ["kubectl", "get", "--raw", "/readyz"], capture_output=True, timeout=10
            ).returncode
            == 0
        )
    except (subprocess.TimeoutExpired, OSError):
        return False


needs_cluster = pytest.mark.skipif(not cluster_reachable(), reason="no reachable Kubernetes/K3s API")


@pytest.fixture
def target_id():
    name = f"selftest-{uuid.uuid4().hex[:8]}"
    provider = K3sControlProvider()
    yield name
    provider.delete(name)  # never leave workloads behind on a real cluster


# --- contract, no cluster needed ---------------------------------------


def test_orchestrator_provider_satisfies_the_same_contract_as_standalone():
    """AI-B-02/원칙 #2: 기능 로직은 K3s 없이도 동일 계약으로 실행된다."""
    assert isinstance(LocalControlSupervisor(), ControlProvider)
    assert isinstance(K3sControlProvider(), ControlProvider)


def test_unreachable_orchestrator_rejects_instead_of_raising():
    unreachable = K3sControlProvider(kubectl="kubectl-does-not-exist")

    assert unreachable.is_available() is False
    result = unreachable.request("start", "anything", {"image": TEST_IMAGE})

    # 예외가 아니라 거부 사유 — 호출자는 standalone supervisor로 계속 간다.
    assert result.accepted is False
    assert result.rejection_reason.startswith("orchestrator_error")


def test_unsupported_command_is_rejected_with_a_reason():
    provider = K3sControlProvider(kubectl="kubectl-does-not-exist")

    result = provider.request("teleport", "x")

    assert result.accepted is False
    assert result.rejection_reason == "unsupported_command:teleport"


def test_start_without_an_image_is_rejected_before_touching_the_cluster():
    provider = K3sControlProvider(kubectl="kubectl-does-not-exist")

    result = provider.request("start", "x", {})

    assert result.rejection_reason == "missing_image"


def test_business_audit_and_technical_trace_are_kept_separate():
    """AI-B-03/원칙 #16: 책임 추적과 기술 성능 추적을 하나로 합치지 않는다."""
    provider = K3sControlProvider(kubectl="kubectl-does-not-exist")

    provider.request("start", "x", {"image": TEST_IMAGE}, requested_by="operator-1")

    assert provider.audit_log[0].requested_by == "operator-1"
    assert provider.audit_log[0].command == "start"
    assert provider.trace_log[0].latency_ms >= 0
    assert not hasattr(provider.audit_log[0], "latency_ms")


def test_name_mapping_is_cluster_safe():
    provider = K3sControlProvider(name_prefix="aif-")

    assert provider._name("Perception_Node") == "aif-perception-node"


# --- real cluster --------------------------------------------------------


@needs_cluster
def test_cluster_is_reported_available():
    assert K3sControlProvider().is_available() is True


@needs_cluster
def test_start_stop_and_status_against_a_real_cluster(target_id):
    provider = K3sControlProvider()

    started = provider.request(
        "start", target_id, {"image": TEST_IMAGE, "command": ["sh", "-c", "sleep 3600"]}
    )
    assert started.accepted, started.rejection_reason

    stopped = provider.request("stop", target_id)
    assert stopped.accepted
    assert stopped.final_status is TargetStatus.STOPPED
    assert provider.get_status(target_id) is TargetStatus.STOPPED


@needs_cluster
def test_stopping_an_unknown_target_is_rejected_not_raised():
    provider = K3sControlProvider()

    result = provider.request("stop", f"missing-{uuid.uuid4().hex[:8]}")

    assert result.accepted is False
    assert result.rejection_reason == "unknown_target"


@needs_cluster
def test_status_of_an_unknown_target_is_stopped_not_an_error():
    provider = K3sControlProvider()

    assert provider.get_status(f"missing-{uuid.uuid4().hex[:8]}") is TargetStatus.STOPPED


@needs_cluster
def test_rollback_of_a_target_without_history_is_rejected_cleanly(target_id):
    """AI-B-07: 롤백 불가 상황도 거부 사유로 표현되며 예외가 되지 않는다."""
    provider = K3sControlProvider()

    result = provider.rollback(target_id)

    assert result.accepted is False
    assert result.rejection_reason == "rollback_unavailable"


@needs_cluster
def test_update_image_works_on_a_deployment_this_provider_did_not_create():
    """The container name is read, not assumed.

    Assuming it matched the deployment name meant the provider could only
    update workloads it had created itself — which is not the normal case for
    anything already running in a cluster (AI-B-05).
    """
    namespace = f"aif-t-updimg-{uuid.uuid4().hex[:8]}"
    provider = K3sControlProvider(namespace=namespace)
    try:
        subprocess.run(["kubectl", "create", "ns", namespace], capture_output=True)
        subprocess.run(["kubectl", "create", "deployment", "aif-foreign",
                        "--image=busybox", "-n", namespace,
                        "--", "sh", "-c", "sleep 3600"], capture_output=True)
        # A deployment whose container is named by whoever made it.
        subprocess.run(["kubectl", "patch", "deployment", "aif-foreign", "-n", namespace,
                        "--type", "json", "-p",
                        '[{"op":"replace","path":"/spec/template/spec/containers/0/name",'
                        '"value":"not-the-deployment-name"}]'], capture_output=True)

        assert provider._container_names("foreign") == ["not-the-deployment-name"]
        result = provider.update_image("foreign", "busybox:1.36")
        assert result.accepted, result.rejection_reason

        applied = subprocess.run(
            ["kubectl", "get", "deployment", "aif-foreign", "-n", namespace, "-o",
             "jsonpath={.spec.template.spec.containers[0].image}"],
            capture_output=True, text=True).stdout
        assert applied == "busybox:1.36"
        assert provider.rollback("foreign").accepted
    finally:
        subprocess.run(["kubectl", "delete", "ns", namespace, "--wait=false"],
                       capture_output=True)


@needs_cluster
def test_a_missing_target_is_reported_rather_than_silently_updated():
    """The counter-case: no deployment means no update to accept."""
    namespace = f"aif-t-missing-{uuid.uuid4().hex[:8]}"
    provider = K3sControlProvider(namespace=namespace)
    try:
        subprocess.run(["kubectl", "create", "ns", namespace], capture_output=True)
        result = provider.update_image("never-created", "busybox:1.36")
        assert not result.accepted
        assert result.rejection_reason == "target_not_found"
    finally:
        subprocess.run(["kubectl", "delete", "ns", namespace, "--wait=false"],
                       capture_output=True)


@needs_cluster
def test_node_selection_reaches_the_workload_as_a_scheduling_constraint():
    """A placement decision that never reaches the workload is not a placement.

    The selection already excluded unlabelled nodes correctly; the gap was that
    the intent never became a constraint, so the pod landed wherever the
    scheduler liked (AI-B-04). The constraint is applied at creation rather
    than patched afterwards, so no unconstrained pod ever runs.
    """
    namespace = f"aif-t-placement-{uuid.uuid4().hex[:8]}"
    provider = K3sControlProvider(namespace=namespace)
    try:
        subprocess.run(["kubectl", "create", "ns", namespace], capture_output=True)
        result = provider.request("start", "placed", {
            "image": "busybox", "command": ["sh", "-c", "sleep 3600"],
            "node_selector": {"aif-test.io/zone": "nowhere"}})
        assert result.accepted, result.rejection_reason

        selector = subprocess.run(
            ["kubectl", "get", "deployment", "aif-placed", "-n", namespace, "-o",
             "jsonpath={.spec.template.spec.nodeSelector}"],
            capture_output=True, text=True).stdout
        assert "aif-test.io/zone" in selector

        # No node carries that label, so nothing may be scheduled.
        deadline = time.time() + 15
        while time.time() < deadline:
            nodes = subprocess.run(
                ["kubectl", "get", "pods", "-n", namespace, "-o",
                 "jsonpath={.items[*].spec.nodeName}"],
                capture_output=True, text=True).stdout.strip()
            assert nodes == "", f"unconstrained pod scheduled on {nodes}"
            time.sleep(1)
    finally:
        subprocess.run(["kubectl", "delete", "ns", namespace, "--wait=false"],
                       capture_output=True)
