"""CLI for the connection smoke harness (`tools/hw_smoke/smoke.py`).

implements: AI-B-04, AI-B-09, AI-O-04 (bring-up tooling)

    .venv/bin/python tools/hw_smoke/run.py --devices config/devices.json \\
        --credentials config/device_credentials.json --level 3 --only pi6,pi4

Prints one row per device (L1 rtt/loss, L2 tags ok/missing, L3 result) and
writes `reports/hw_smoke/<YYYYMMDD-HHMM>.json`. Device failures are *results*
(exit 0); only a config error exits non-zero.

`--address-override id=host` reaches a registered device by another address
(e.g. its overlay name from a box outside its LAN) **without editing
config/devices.json**. `--adhoc id=user@host[:port][:tags=a,b][:cred=id]`
probes a device that is not registered at all — useful before deciding to
register it — and never persists anything.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

_FRAMEWORK_DIR = Path(__file__).resolve().parents[2]
if str(_FRAMEWORK_DIR) not in sys.path:
    sys.path.insert(0, str(_FRAMEWORK_DIR))

from mission_runtime.registry.device_registry import (  # noqa: E402
    AUTH_PASSWORD,
    CredentialStore,
    DeviceCredential,
    DeviceRegistration,
    DeviceRegistry,
    DeviceRegistryError,
)
from tools.hw_smoke import smoke  # noqa: E402

EXIT_CONFIG_ERROR = 2
ENV_PASSWORD_CREDENTIAL_ID = "env-password"


class CliError(ValueError):
    pass


def parse_adhoc(spec: str) -> DeviceRegistration:
    """`id=user@host[:port][:tags=a,b][:cred=credential_id]`."""
    if "=" not in spec:
        raise CliError(f"--adhoc: expected id=user@host[...], got {spec!r}")
    device_id, rest = spec.split("=", 1)
    parts = rest.split(":")
    target = parts[0]
    if "@" not in target:
        raise CliError(f"--adhoc {device_id}: expected user@host, got {target!r}")
    username, address = target.split("@", 1)
    port = 22
    tags: set[str] = set()
    credential_id = ""
    for part in parts[1:]:
        if part.isdigit():
            port = int(part)
        elif part.startswith("tags="):
            tags = {t for t in part[len("tags="):].split(",") if t}
        elif part.startswith("cred="):
            credential_id = part[len("cred="):]
        else:
            raise CliError(f"--adhoc {device_id}: unknown segment {part!r}")
    try:
        return DeviceRegistration(
            device_id=device_id, address=address, username=username, credential_id=credential_id,
            port=port, node_tags=frozenset(tags), role="adhoc",
        )
    except DeviceRegistryError as error:
        raise CliError(f"--adhoc {device_id}: {error}") from error


def parse_override(spec: str) -> tuple[str, str]:
    if "=" not in spec:
        raise CliError(f"--address-override: expected id=address, got {spec!r}")
    device_id, address = spec.split("=", 1)
    if not device_id or not address:
        raise CliError(f"--address-override: expected id=address, got {spec!r}")
    return device_id, address


def build_registry(args: argparse.Namespace) -> DeviceRegistry:
    store = CredentialStore(args.credentials, strict_permissions=True)
    if args.password_env:
        secret = os.environ.get(args.password_env)
        if not secret:
            raise CliError(f"--password-env: environment variable {args.password_env} is empty or unset")
        # In memory only — never saved, never printed (DeviceCredential redacts).
        store.put(DeviceCredential(ENV_PASSWORD_CREDENTIAL_ID, AUTH_PASSWORD, secret=secret))
    registry = DeviceRegistry(store)
    if args.devices:
        registry.load(args.devices)
    for spec in args.address_override:
        device_id, address = parse_override(spec)
        device = registry.get(device_id)
        if device is None:
            raise CliError(f"--address-override: unknown device {device_id!r}")
        registry.register(replace(device, address=address))
    for spec in args.adhoc:
        device = parse_adhoc(spec)
        if registry.get(device.device_id) is not None:
            raise CliError(f"--adhoc: {device.device_id!r} is already registered; use --address-override")
        registry.register(device)
    return registry


def _fmt_l1(result: smoke.ProbeResult | None) -> str:
    if result is None:
        return "-"
    m = result.measured
    if not result.ok:
        return f"FAIL {result.reason}"
    loss = m.get("loss_fraction")
    rtt = m.get("rtt_avg_ms")
    mdev = m.get("rtt_mdev_ms")
    rtt_s = f"{rtt:.1f}ms" if rtt is not None else "rtt ?"
    mdev_s = f"±{mdev:.1f}" if mdev is not None else ""
    loss_s = f"{loss * 100:.0f}% loss" if loss is not None else "loss ?"
    return f"ok {rtt_s}{mdev_s} {loss_s}"


def _fmt_l2(result: smoke.ProbeResult | None) -> str:
    if result is None:
        return "-"
    m = result.measured
    if result.reason == smoke.PROBE_TAG_MISMATCH:
        return f"FAIL tag_mismatch missing={','.join(m.get('missing', []))}"
    if not result.ok:
        return f"FAIL {result.reason}" + (f" ({m['error']})" if m.get("error") else "")
    extra = f" +{','.join(m['unregistered'])}" if m.get("unregistered") else ""
    return f"ok {m.get('arch', '?')} cams={','.join(m.get('cameras', [])) or '-'} tags {len(m.get('checked', []))}/{len(m.get('checked', []))}{extra}"


def _fmt_l3(result: smoke.ProbeResult | None) -> str:
    if result is None:
        return "-"
    m = result.measured
    kind = m.get("probe_kind", "?")
    if result.ok:
        if "frame_bytes" in m:
            return f"ok {kind} {m['frame_bytes']} bytes"
        return f"ok {kind}"
    return f"FAIL {result.reason} ({kind})"


def render_table(results: list[smoke.ProbeResult], device_ids: list[str]) -> str:
    by_device: dict[str, dict[int, smoke.ProbeResult]] = {}
    for r in results:
        by_device.setdefault(r.device_id, {})[r.level] = r
    rows = [("device", "L1 reach", "L2 identity", "L3 function")]
    for device_id in device_ids:
        levels = by_device.get(device_id, {})
        rows.append((device_id, _fmt_l1(levels.get(1)), _fmt_l2(levels.get(2)), _fmt_l3(levels.get(3))))
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    lines = ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip() for row in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--devices", default="config/devices.json", help="device registry file (default: config/devices.json)")
    parser.add_argument("--credentials", default="config/device_credentials.json", help="credential store (default: config/device_credentials.json)")
    parser.add_argument("--level", type=int, choices=smoke.LEVELS, default=smoke.LEVEL_FUNCTION, help="deepest level to attempt")
    parser.add_argument("--only", default="", help="comma-separated device ids (default: all registered + adhoc)")
    parser.add_argument("--address-override", action="append", default=[], metavar="ID=ADDRESS",
                        help="reach a registered device by another address; config is not modified")
    parser.add_argument("--adhoc", action="append", default=[], metavar="ID=USER@HOST[:PORT][:tags=a,b][:cred=ID]",
                        help="probe an unregistered device; nothing is persisted")
    parser.add_argument("--password-env", default="", metavar="VAR",
                        help=f"read a password from this env var as credential id '{ENV_PASSWORD_CREDENTIAL_ID}' (in memory only)")
    parser.add_argument("--icmp-count", type=int, default=5)
    parser.add_argument("--json", action="store_true", help="print the report JSON instead of the table")
    parser.add_argument("--no-report", action="store_true", help="do not write reports/hw_smoke/<stamp>.json")
    args = parser.parse_args(argv)

    try:
        registry = build_registry(args)
        device_ids = [d for d in args.only.split(",") if d] if args.only else [d.device_id for d in registry.devices()]
        for device_id in device_ids:
            if registry.get(device_id) is None:
                raise CliError(f"--only: unknown device {device_id!r}")
    except (CliError, DeviceRegistryError) as error:
        print(f"config error: {error}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    runner = smoke.SmokeRunner(registry, icmp_count=args.icmp_count)
    results = runner.run(args.level, device_ids)
    report_path = None if args.no_report else smoke.write_report(results)
    if args.json:
        print(json.dumps(smoke.report_payload(results), indent=2, ensure_ascii=False))
    else:
        print(render_table(results, device_ids))
    if report_path is not None:
        print(f"report: {report_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
