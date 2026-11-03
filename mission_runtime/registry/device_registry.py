"""On-device target registration: address + credential + node tags.

implements: AI-C-10, AI-B-04, AI-B-02, AI-B-10, AI-C-04, AI-C-18

AI-B-04: "각 실행 노드는 현재 제공 가능한 연산 자원, 아키텍처, 가속기,
센서·장치 연결, 런타임과 네트워크 특성을 공통 자원 규약으로 등록할 수 있어야
한다." 이 모듈은 그 등록의 *말단* 절반 — 오케스트레이터 제어면이 없는 노드를
"주소 + 자격증명 + 태그"만으로 등록하는 경로 — 를 담당한다.

Two boundaries are load-bearing here:

- **No transport knowledge.** A registration carries an `address`, a
  `username`, a `port` and a free-form `access_method` string. Whether the
  eventual control path is SSH, a serial console or something else is the
  provider's business, not this module's (AI-C-04, 절대 준수 원칙 #1). Nothing
  in `registry/` imports a client library.
- **No parallel capability mechanism.** `node_tags` are exactly the tag set
  `CompatibilityProfile.is_compatible()` already consumes, so a registered
  device feeds `selection/selector.py` unchanged (AI-C-10). A device does not
  get its own matcher.

Credentials never live in a registration, only a `credential_id` pointing
into a `CredentialStore` whose file is local-only and never committed
(AI-B-02: "자격증명·비밀정보를 이미지에 포함해서는 안 된다"). Every dataclass
here redacts secrets in `repr`, because a registration is routinely dumped
into a log line or an artifact.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field, replace
from pathlib import Path

from mission_runtime.contracts.profile import CompatibilityProfile, ResourceBudget

#: Free-form auth mechanism names. Deliberately plain strings, not an enum:
#: adding a mechanism must be data, and callers only ever compare against
#: these constants when deciding *how to authenticate*, never to branch on a
#: device's identity or domain (절대 준수 원칙 #3).
AUTH_PASSWORD = "password"
AUTH_KEY = "key"

#: Default local locations. Both are git-ignored (see repo `.gitignore`);
#: the committed files are the `*.example.json` siblings.
DEFAULT_CREDENTIAL_FILE = "config/device_credentials.json"
DEFAULT_DEVICE_FILE = "config/devices.json"

REDACTED = "***"


class DeviceRegistryError(ValueError):
    """A registration or credential file the framework refuses to use."""


@dataclass(frozen=True)
class DeviceCredential:
    """One device's secret material. Never serialized into an artifact.

    `secret` is the password (for `AUTH_PASSWORD`) or an optional key
    passphrase; `key_path` is a path on the *controlling* node, never on the
    device. `__repr__` is overridden so that an accidental `print(cred)`,
    an exception `repr`, or a structured log record cannot leak it.
    """

    credential_id: str
    auth_method: str = AUTH_KEY
    secret: str | None = None
    key_path: str | None = None

    def __repr__(self) -> str:  # pragma: no cover - trivial, but security-relevant
        held = REDACTED if self.secret else None
        return (
            f"DeviceCredential(credential_id={self.credential_id!r}, "
            f"auth_method={self.auth_method!r}, secret={held!r}, key_path={self.key_path!r})"
        )

    __str__ = __repr__

    def redacted(self) -> dict:
        """A safe-to-log view. The only shape callers should ever emit."""
        return {
            "credential_id": self.credential_id,
            "auth_method": self.auth_method,
            "has_secret": self.secret is not None,
            "key_path": self.key_path,
        }


class CredentialStore:
    """A local JSON file of `DeviceCredential`s, kept off the wire and off git.

    The file must not be group/world readable. A too-permissive file is a
    *rejection*, not a warning: silently continuing would mean the framework
    itself is the reason a secret became readable (AI-B-02).
    """

    def __init__(self, path: str | Path = DEFAULT_CREDENTIAL_FILE, *, strict_permissions: bool = True) -> None:
        self._path = Path(path)
        self._strict = strict_permissions
        self._entries: dict[str, DeviceCredential] = {}
        if self._path.exists():
            self.load()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> None:
        if not self._path.exists():
            raise DeviceRegistryError(f"credential file not found: {self._path}")
        self._check_permissions()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise DeviceRegistryError(f"{self._path}: not valid JSON: {error}") from error
        entries = raw.get("credentials")
        if not isinstance(entries, list):
            raise DeviceRegistryError(f"{self._path}: must have a top-level 'credentials' list")
        loaded: dict[str, DeviceCredential] = {}
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict) or "credential_id" not in entry:
                raise DeviceRegistryError(f"{self._path}: credentials[{index}] needs 'credential_id'")
            credential = DeviceCredential(
                credential_id=str(entry["credential_id"]),
                auth_method=str(entry.get("auth_method", AUTH_KEY)),
                secret=entry.get("secret"),
                key_path=entry.get("key_path"),
            )
            loaded[credential.credential_id] = credential
        self._entries = loaded

    def _check_permissions(self) -> None:
        if not self._strict or os.name != "posix":
            return
        mode = stat.S_IMODE(self._path.stat().st_mode)
        if mode & 0o077:
            raise DeviceRegistryError(
                f"{self._path}: credential file is group/world accessible (mode {mode:o}); "
                "chmod 600 it before use"
            )

    def put(self, credential: DeviceCredential) -> None:
        self._entries[credential.credential_id] = credential

    def get(self, credential_id: str) -> DeviceCredential | None:
        return self._entries.get(credential_id)

    def ids(self) -> list[str]:
        return sorted(self._entries)

    def save(self) -> None:
        """Write the store back out with owner-only permissions.

        The mode is set *before* the content is written, so the secret is
        never briefly present in a world-readable file.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(
                    {
                        "credentials": [
                            {
                                "credential_id": c.credential_id,
                                "auth_method": c.auth_method,
                                **({"secret": c.secret} if c.secret is not None else {}),
                                **({"key_path": c.key_path} if c.key_path is not None else {}),
                            }
                            for c in self._entries.values()
                        ]
                    },
                    stream,
                    indent=2,
                )
        finally:
            if self._path.exists() and os.name == "posix":
                os.chmod(self._path, 0o600)


@dataclass(frozen=True)
class DeviceRegistration:
    """One on-device execution target, described the way AI-B-04 asks for.

    `node_tags` is the node's own resource/hardware/runtime declaration —
    the same free-form tag vocabulary `CompatibilityProfile` matches against
    (`compute.cpu`, `accel.coral`, `sensor.camera`, `platform.terminal`...),
    so adding a device with a new accelerator is a tag, never a code change
    (절대 준수 원칙 #7).

    `role` is descriptive data only. Nothing in the framework may branch on
    it (절대 준수 원칙 #3); it exists so an operator listing devices can see
    what a node is for, and so a placement request can express a required
    tag if it wants a role honoured.

    `purpose_id` names a `DevicePurposeProfile` — "what this device is here
    to do" (AI-C-15, AI-B-04). It is read the same way `node_tags` is: as an
    **input** that `runtime/residency.py` consumes to decide what should live
    on the device. Nothing branches on its value either; an unknown or empty
    purpose simply means this device has no residency plan yet, which is a
    normal registration state (a device can be reachable before anyone has
    said what it is for).

    `budget` is what this node can currently afford; `None` means "not
    measured", which selection treats as unknown rather than zero
    (AI-C-18: 모든 항목이 항상 존재한다고 가정하지 않는다).
    """

    device_id: str
    address: str
    username: str
    credential_id: str
    port: int = 22
    node_tags: frozenset[str] = field(default_factory=frozenset)
    role: str = ""
    purpose_id: str = ""
    access_method: str = "ssh"
    budget: ResourceBudget | None = None

    def __post_init__(self) -> None:
        if not self.device_id:
            raise DeviceRegistryError("device_id must not be empty")
        if not self.address:
            raise DeviceRegistryError(f"{self.device_id}: address must not be empty")
        if not self.username:
            raise DeviceRegistryError(f"{self.device_id}: username must not be empty")
        object.__setattr__(self, "node_tags", frozenset(self.node_tags))

    def as_dict(self) -> dict:
        """Safe-to-persist view — contains a credential *reference*, no secret."""
        return {
            "device_id": self.device_id,
            "address": self.address,
            "username": self.username,
            "credential_id": self.credential_id,
            "port": self.port,
            "node_tags": sorted(self.node_tags),
            "role": self.role,
            "purpose_id": self.purpose_id,
            "access_method": self.access_method,
        }

    def supports(self, profile: CompatibilityProfile, budget: ResourceBudget | None = None) -> bool:
        """Whether this node satisfies a provider's compatibility profile.

        Delegates entirely to `CompatibilityProfile` so a device is judged by
        the same rule as any other execution target — required tags exclude,
        preferred tags do not (AI-B-04).
        """
        effective = budget or self.budget
        if effective is None:
            # Unmeasured budget must not silently exclude a node; only the tag
            # half of the contract can be decided here.
            return set(profile.required_hw_tags).issubset(self.node_tags) and set(
                profile.required_runtime_tags
            ).issubset(self.node_tags)
        return profile.is_compatible(set(self.node_tags), effective)


class DeviceRegistry:
    """The set of on-device targets this control plane may deploy to.

    Deliberately *not* an availability authority: a device being registered
    here says the edge knows how to reach it, never that the backend
    considers it available (절대 준수 원칙 #15, AI-O-04). Callers that need a
    verdict pass one in via `exclude_device_ids`.
    """

    def __init__(self, credentials: CredentialStore | None = None) -> None:
        self._devices: dict[str, DeviceRegistration] = {}
        self._credentials = credentials or CredentialStore(strict_permissions=True)

    # --- registration ----------------------------------------------------
    def register(self, device: DeviceRegistration) -> DeviceRegistration:
        """Add or replace a device. Registration alone performs no I/O.

        A device whose `credential_id` is unknown is still registered: the
        credential file may legitimately arrive later (or be supplied by a
        different operator), and refusing here would make the ordering of two
        local files a hard dependency.
        """
        self._devices[device.device_id] = device
        return device

    def register_address(
        self,
        device_id: str,
        address: str,
        username: str,
        *,
        credential: DeviceCredential | None = None,
        credential_id: str | None = None,
        node_tags: frozenset[str] | set[str] | tuple[str, ...] = (),
        role: str = "",
        purpose_id: str = "",
        port: int = 22,
        access_method: str = "ssh",
        budget: ResourceBudget | None = None,
    ) -> DeviceRegistration:
        """The "address + credentials only" entry point.

        Passing a `credential` stores it in the credential store (in memory;
        call `save_credentials()` to persist) and references it by id, so the
        secret never reaches the registration object itself.
        """
        if credential is not None:
            self._credentials.put(credential)
            credential_id = credential.credential_id
        if credential_id is None:
            raise DeviceRegistryError(f"{device_id}: either credential or credential_id is required")
        return self.register(
            DeviceRegistration(
                device_id=device_id,
                address=address,
                username=username,
                credential_id=credential_id,
                port=port,
                node_tags=frozenset(node_tags),
                role=role,
                purpose_id=purpose_id,
                access_method=access_method,
                budget=budget,
            )
        )

    def unregister(self, device_id: str) -> None:
        self._devices.pop(device_id, None)

    def get(self, device_id: str) -> DeviceRegistration | None:
        return self._devices.get(device_id)

    def credential_for(self, device_id: str) -> DeviceCredential | None:
        device = self._devices.get(device_id)
        if device is None:
            return None
        return self._credentials.get(device.credential_id)

    def set_credential(self, device_id: str, credential: DeviceCredential) -> None:
        """Rotate a device's credential — used after a key is installed on
        first contact so later connections stop using the password."""
        device = self._devices.get(device_id)
        if device is None:
            raise DeviceRegistryError(f"unknown device: {device_id}")
        self._credentials.put(credential)
        self._devices[device_id] = replace(device, credential_id=credential.credential_id)

    def save_credentials(self) -> None:
        self._credentials.save()

    # --- selection input (AI-C-10, AI-B-04) --------------------------------
    def node_tags(self, device_id: str) -> set[str]:
        """The tag set to hand to `CapabilitySelector.select(...)`.

        This is the whole integration with the existing machinery: a device
        is just another node, described by tags.
        """
        device = self._devices.get(device_id)
        return set(device.node_tags) if device else set()

    def devices(self, *, exclude_device_ids: frozenset[str] | set[str] = frozenset()) -> list[DeviceRegistration]:
        """Registered devices, minus any the caller's availability source has
        ruled out. The exclusion is an *input*; this class never computes it
        (절대 준수 원칙 #15)."""
        return [d for d in self._devices.values() if d.device_id not in set(exclude_device_ids)]

    def matching(
        self,
        profile: CompatibilityProfile,
        *,
        budget: ResourceBudget | None = None,
        exclude_device_ids: frozenset[str] | set[str] = frozenset(),
    ) -> list[DeviceRegistration]:
        """Devices a provider with this compatibility profile could run on."""
        return [d for d in self.devices(exclude_device_ids=exclude_device_ids) if d.supports(profile, budget)]

    # --- persistence (non-secret half only) --------------------------------
    def save(self, path: str | Path = DEFAULT_DEVICE_FILE) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"devices": [d.as_dict() for d in self._devices.values()]}, indent=2),
            encoding="utf-8",
        )

    def load(self, path: str | Path = DEFAULT_DEVICE_FILE) -> None:
        source = Path(path)
        if not source.exists():
            raise DeviceRegistryError(f"device file not found: {source}")
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise DeviceRegistryError(f"{source}: not valid JSON: {error}") from error
        entries = raw.get("devices")
        if not isinstance(entries, list):
            raise DeviceRegistryError(f"{source}: must have a top-level 'devices' list")
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise DeviceRegistryError(f"{source}: devices[{index}] must be an object")
            if "secret" in entry or "password" in entry:
                # A device file is committed-adjacent and is *not* the place
                # for a secret, even a well-meant one (AI-B-02).
                raise DeviceRegistryError(
                    f"{source}: devices[{index}] carries a secret; secrets belong in the credential store"
                )
            self.register(
                DeviceRegistration(
                    device_id=str(entry.get("device_id", "")),
                    address=str(entry.get("address", "")),
                    username=str(entry.get("username", "")),
                    credential_id=str(entry.get("credential_id", "")),
                    port=int(entry.get("port", 22)),
                    node_tags=frozenset(entry.get("node_tags", ())),
                    role=str(entry.get("role", "")),
                    purpose_id=str(entry.get("purpose_id", "")),
                    access_method=str(entry.get("access_method", "ssh")),
                )
            )
