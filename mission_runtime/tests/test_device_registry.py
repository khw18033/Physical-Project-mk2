"""implements: AI-C-10, AI-B-04, AI-B-02, AI-B-10, AI-C-04
covers: address+credential-only registration, secrets never inside a
        registration/repr/persisted device file, credential file permission
        gate, key rotation after first contact, node tags feeding the
        *existing* selector rather than a parallel matcher, preferred tags
        never excluding, backend availability consumed as an input.
"""

import json
import os
import stat

import pytest

from mission_runtime.contracts.profile import CompatibilityProfile, ResourceBudget, ResourceCost
from mission_runtime.registry.capability_registry import CapabilityRegistry
from mission_runtime.registry.device_registry import (
    AUTH_KEY,
    AUTH_PASSWORD,
    CredentialStore,
    DeviceCredential,
    DeviceRegistration,
    DeviceRegistry,
    DeviceRegistryError,
)
from mission_runtime.selection.selector import CapabilitySelector

from conftest import registration

SECRET = "not-a-real-password"


@pytest.fixture
def store(tmp_path):
    return CredentialStore(tmp_path / "device_credentials.json", strict_permissions=True)


@pytest.fixture
def registry(store):
    return DeviceRegistry(store)


# --- registration by address + credential only ---------------------------


def test_a_device_is_registered_from_address_and_credential_alone(registry):
    device = registry.register_address(
        "terminal-a",
        "192.0.2.11",
        "physical",
        credential=DeviceCredential("terminal-a-boot", AUTH_PASSWORD, secret=SECRET),
        node_tags={"platform.terminal", "compute.cpu"},
        role="mobile-agent",
    )

    assert registry.get("terminal-a") is device
    assert device.credential_id == "terminal-a-boot"
    assert registry.credential_for("terminal-a").secret == SECRET


def test_a_registration_holds_a_credential_reference_never_the_secret(registry):
    registry.register_address(
        "terminal-a", "192.0.2.11", "physical",
        credential=DeviceCredential("c1", AUTH_PASSWORD, secret=SECRET),
    )
    device = registry.get("terminal-a")

    assert SECRET not in repr(device)
    assert SECRET not in json.dumps(device.as_dict())
    assert "secret" not in device.as_dict()


def test_credential_repr_and_str_are_redacted():
    """AI-B-02: a credential routinely lands in a log line or a traceback."""
    credential = DeviceCredential("c1", AUTH_PASSWORD, secret=SECRET)

    assert SECRET not in repr(credential)
    assert SECRET not in str(credential)
    assert SECRET not in json.dumps(credential.redacted())
    assert credential.redacted()["has_secret"] is True


def test_registering_without_any_credential_is_rejected(registry):
    with pytest.raises(DeviceRegistryError):
        registry.register_address("terminal-a", "192.0.2.11", "physical")


@pytest.mark.parametrize("field", ["device_id", "address", "username"])
def test_an_incomplete_registration_is_rejected_at_construction(field):
    kwargs = {"device_id": "d", "address": "a", "username": "u", "credential_id": "c"}
    kwargs[field] = ""
    with pytest.raises(DeviceRegistryError):
        DeviceRegistration(**kwargs)


# --- credential file hygiene (AI-B-02) -----------------------------------


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes only")
def test_a_group_or_world_readable_credential_file_is_refused(tmp_path):
    path = tmp_path / "creds.json"
    path.write_text(json.dumps({"credentials": [{"credential_id": "c1", "secret": SECRET}]}))
    path.chmod(0o644)

    with pytest.raises(DeviceRegistryError, match="group/world accessible"):
        CredentialStore(path)


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes only")
def test_saving_a_credential_file_writes_owner_only_permissions(tmp_path):
    store = CredentialStore(tmp_path / "creds.json")
    store.put(DeviceCredential("c1", AUTH_PASSWORD, secret=SECRET))

    store.save()

    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    # And it round-trips through the permission gate it just satisfied.
    assert CredentialStore(store.path).get("c1").secret == SECRET


def test_a_device_file_carrying_a_secret_is_refused(tmp_path, registry):
    """The device file is the committable half; a secret in it is a mistake
    the loader must surface rather than accept (AI-B-02)."""
    path = tmp_path / "devices.json"
    path.write_text(json.dumps({"devices": [
        {"device_id": "d", "address": "a", "username": "u", "credential_id": "c", "secret": SECRET}
    ]}))

    with pytest.raises(DeviceRegistryError, match="carries a secret"):
        registry.load(path)


def test_saved_device_file_contains_no_secret_even_after_one_was_stored(tmp_path, registry):
    registry.register_address(
        "terminal-a", "192.0.2.11", "physical",
        credential=DeviceCredential("c1", AUTH_PASSWORD, secret=SECRET),
        node_tags={"compute.cpu"},
    )
    path = tmp_path / "devices.json"

    registry.save(path)

    assert SECRET not in path.read_text()
    assert json.loads(path.read_text())["devices"][0]["credential_id"] == "c1"


def test_device_file_round_trips_tags_and_role(tmp_path, registry):
    registry.register_address(
        "terminal-a", "192.0.2.11", "physical", credential_id="c1",
        node_tags={"compute.cpu", "accel.usb_tpu"}, role="mobile-agent", port=2222,
    )
    path = tmp_path / "devices.json"
    registry.save(path)

    reloaded = DeviceRegistry(CredentialStore(tmp_path / "creds.json", strict_permissions=False))
    reloaded.load(path)

    device = reloaded.get("terminal-a")
    assert device.node_tags == frozenset({"compute.cpu", "accel.usb_tpu"})
    assert (device.role, device.port) == ("mobile-agent", 2222)


# --- first contact with a password, key auth thereafter ------------------


def test_a_credential_can_be_rotated_from_password_to_key(registry):
    """Prefer installing a key on first contact and using key auth after."""
    registry.register_address(
        "terminal-a", "192.0.2.11", "physical",
        credential=DeviceCredential("boot", AUTH_PASSWORD, secret=SECRET),
    )

    registry.set_credential("terminal-a", DeviceCredential("steady", AUTH_KEY, key_path="~/.ssh/id_ed25519"))

    credential = registry.credential_for("terminal-a")
    assert credential.auth_method == AUTH_KEY
    assert credential.secret is None
    assert registry.get("terminal-a").credential_id == "steady"


def test_rotating_an_unknown_device_is_rejected(registry):
    with pytest.raises(DeviceRegistryError):
        registry.set_credential("nope", DeviceCredential("c", AUTH_KEY))


# --- node tags feed the EXISTING selector (AI-C-10, AI-B-04) -------------


def test_device_tags_drive_the_ordinary_capability_selector(registry):
    """AI-C-10: 상위 기능은 장치 이름이 아니라 필요한 capability로 탐색한다.

    The device contributes tags; everything after that is the selector the
    framework already has. No device-specific matcher exists.
    """
    registry.register_address("with-tpu", "192.0.2.11", "u", credential_id="c",
                              node_tags={"compute.cpu", "accel.usb_tpu"})
    registry.register_address("plain", "192.0.2.12", "u", credential_id="c",
                              node_tags={"compute.cpu"})

    capabilities = CapabilityRegistry()
    capabilities.register_local(registration("perception.detect", "tpu-model", hw_tags=("accel.usb_tpu",)))
    selector = CapabilitySelector(capabilities)
    budget = ResourceBudget(compute_units=10.0, memory_mb=1024.0)

    on_tpu = selector.select("perception.detect", registry.node_tags("with-tpu"), budget)
    on_plain = selector.select("perception.detect", registry.node_tags("plain"), budget)

    assert on_tpu.provider is not None and on_tpu.provider.provider_id == "tpu-model"
    # 축소는 예외가 아니라 정상 경로다.
    assert on_plain.provider is None
    assert on_plain.reason == "no_compatible_provider_within_budget"
    # The device's missing tag is named in the per-candidate outcome, so an
    # operator can see *which* tag ruled the node out (AI-O-02).
    assert [o.reason for o in on_plain.alternatives] == ["required_hw_tag_missing:accel.usb_tpu"]


def test_a_preferred_tag_never_excludes_a_device(registry):
    """AI-B-04: 선호 자원이 없으면 호환 가능한 일반 자원으로 대체한다."""
    registry.register_address("plain", "192.0.2.12", "u", credential_id="c", node_tags={"compute.cpu"})
    profile = CompatibilityProfile(
        required_hw_tags=("compute.cpu",),
        preferred_hw_tags=("accel.usb_tpu",),
        cost=ResourceCost(compute_units=1.0, memory_mb=64.0),
    )

    assert registry.matching(profile, budget=ResourceBudget(10.0, 1024.0)) != []
    assert registry.get("plain").supports(profile, ResourceBudget(10.0, 1024.0)) is True


def test_a_required_tag_does_exclude_a_device(registry):
    registry.register_address("plain", "192.0.2.12", "u", credential_id="c", node_tags={"compute.cpu"})
    profile = CompatibilityProfile(required_hw_tags=("accel.usb_tpu",))

    assert registry.matching(profile, budget=ResourceBudget(10.0, 1024.0)) == []


def test_an_unmeasured_budget_does_not_silently_exclude_a_device(registry):
    """AI-C-18: 모든 항목이 항상 존재한다고 가정하지 않는다 — 미측정은 0이 아니다."""
    registry.register_address("plain", "192.0.2.12", "u", credential_id="c", node_tags={"compute.cpu"})
    costly = CompatibilityProfile(required_hw_tags=("compute.cpu",), cost=ResourceCost(compute_units=999.0))

    assert registry.matching(costly) != []                                    # budget unknown
    assert registry.matching(costly, budget=ResourceBudget(1.0, 1.0)) == []   # budget known


# --- availability is an input, never recomputed here ---------------------


def test_backend_unavailability_is_consumed_not_recomputed(registry):
    """절대 준수 원칙 #15 / AI-O-04: 최종 가용성 판정은 백엔드 책임이다."""
    registry.register_address("a", "192.0.2.11", "u", credential_id="c", node_tags={"compute.cpu"})
    registry.register_address("b", "192.0.2.12", "u", credential_id="c", node_tags={"compute.cpu"})

    remaining = registry.devices(exclude_device_ids={"b"})

    assert [d.device_id for d in remaining] == ["a"]
    # The registry offers no verdict of its own to disagree with.
    assert not hasattr(registry, "is_available")


def test_unknown_device_yields_empty_tags_and_no_credential(registry):
    assert registry.node_tags("ghost") == set()
    assert registry.credential_for("ghost") is None
    assert registry.get("ghost") is None


def test_unregistering_removes_a_device(registry):
    registry.register_address("a", "192.0.2.11", "u", credential_id="c")
    registry.unregister("a")
    registry.unregister("a")  # idempotent

    assert registry.get("a") is None
