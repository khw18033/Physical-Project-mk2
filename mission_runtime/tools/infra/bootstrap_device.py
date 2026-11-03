"""Register (or re-key) one terminal device from the command line.

implements: AI-B-02, AI-B-10, AI-C-04

`make bootstrap DEVICE=<id>` — the terminal gets exactly one thing installed:
our public key (then, on deploy, the single-file agent script). No broker, no
collector, no orchestrator agent (AI-B-10). The password is used once, read
from `AIF_DEVICE_PASSWORD` or an interactive prompt, and never written
anywhere — after the key is verified the registry's credential is replaced by
the key reference (`providers/ondevice_bootstrap.py::bootstrap_key_auth`).

The device must already be listed in `config/devices.json` (address, user,
tags, role). Registering *and* bootstrapping in one go is what the status UI's
device panel does; this CLI is the headless equivalent for the Makefile.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys

from mission_runtime.providers.ondevice_bootstrap import bootstrap_key_auth
from mission_runtime.registry.device_registry import (
    DEFAULT_CREDENTIAL_FILE,
    DEFAULT_DEVICE_FILE,
    CredentialStore,
    DeviceRegistry,
    DeviceRegistryError,
)

DEFAULT_KEY_PATH = "~/.ssh/mission_runtime_control"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--device", required=True, help="device_id in the device registry")
    parser.add_argument("--devices", default=DEFAULT_DEVICE_FILE)
    parser.add_argument("--credentials", default=DEFAULT_CREDENTIAL_FILE)
    parser.add_argument("--key-path", default=DEFAULT_KEY_PATH,
                        help="control key pair on this box (created if missing)")
    parser.add_argument("--json", action="store_true", help="print the BootstrapResult as JSON")
    args = parser.parse_args(argv)

    credentials = CredentialStore(args.credentials, strict_permissions=False)
    try:
        credentials.load()
    except DeviceRegistryError:
        pass  # a fresh box has no credential file yet; bootstrap creates the entry
    registry = DeviceRegistry(credentials)
    try:
        registry.load(args.devices)
    except DeviceRegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if registry.get(args.device) is None:
        print(f"error: unknown device {args.device!r} — add it to {args.devices} first", file=sys.stderr)
        return 2

    password = os.environ.get("AIF_DEVICE_PASSWORD") or getpass.getpass(f"password for {args.device}: ")
    try:
        result = bootstrap_key_auth(registry, args.device, password=password, key_path=args.key_path)
    except DeviceRegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        password = None  # noqa: F841 — drop the only reference on purpose

    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False))
    else:
        print(f"{args.device}: {'ok' if result.ok else 'failed'} — {result.reason}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
