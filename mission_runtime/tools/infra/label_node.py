"""Label a K3s/Kubernetes node with this machine's *measured* hardware tags.

implements: AI-B-04, AI-B-11, AI-C-04

The selector decides placement from free-string tags (`CompatibilityProfile.
required_hw_tags`), and `runtime/placement.py::node_selector_for` turns each
required tag into the label `aif.io/<tag>=true`. For that label to mean
anything the node has to carry it — on 2026-09-17 it was attached by hand
(`kubectl label node ... aif.io/compute.cpu=true`). This tool closes that gap:
it runs the same `providers/compute.py::discover_node_tags()` probe the
framework uses at runtime and writes exactly those tags as labels, so the
scheduler's view of a node and the selector's view of it come from one
measurement (AI-B-04: 실제 자원을 기준으로 배치).

Boundaries kept on purpose:
- kubectl is shelled out to, never imported — no Python Kubernetes client
  (AI-B-10; same posture as `providers/k3s.py`).
- Tag→label spelling is imported from `runtime/placement.py`, not
  re-implemented, so the two can never drift.
- When NFD (Node Feature Discovery) is adopted this tool is simply not run;
  the label vocabulary was chosen to coexist with NFD's own prefix.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys

from mission_runtime.providers.compute import discover_node_tags
from mission_runtime.runtime.placement import LABEL_PREFIX, node_selector_for
from mission_runtime.contracts.profile import CompatibilityProfile


def labels_for(tags: set[str] | frozenset[str] | list[str]) -> dict[str, str]:
    """`{"aif.io/<tag>": "true"}` for every tag, validated by the same rule the
    reconciler applies (an illegal tag raises `ValueError`, naming it)."""
    return node_selector_for(CompatibilityProfile(required_hw_tags=tuple(sorted(set(tags)))))


def kubectl_label_args(node: str, labels: dict[str, str], *, kubectl: str = "kubectl") -> list[str]:
    args = [kubectl, "label", "node", node, "--overwrite"]
    args += [f"{key}={value}" for key, value in sorted(labels.items())]
    return args


def current_node_name(*, kubectl: str = "kubectl", timeout: int = 15) -> str | None:
    """The single node of a one-node cluster, else `None` (caller must pass
    `--node`)."""
    proc = subprocess.run(
        [kubectl, "get", "nodes", "-o", "jsonpath={.items[*].metadata.name}"],
        capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        return None
    names = proc.stdout.split()
    return names[0] if len(names) == 1 else None


def existing_aif_labels(node: str, *, kubectl: str = "kubectl", timeout: int = 15) -> dict[str, str]:
    proc = subprocess.run(
        [kubectl, "get", "node", node, "-o", "json"], capture_output=True, text=True, timeout=timeout
    )
    if proc.returncode != 0:
        return {}
    try:
        labels = json.loads(proc.stdout).get("metadata", {}).get("labels", {})
    except ValueError:
        return {}
    return {k: v for k, v in labels.items() if k.startswith(LABEL_PREFIX)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--node", help="node name; default = the only node of the cluster")
    parser.add_argument("--tag", action="append", default=[],
                        help="extra tag to label in addition to the measured ones (e.g. tier.edge). Repeatable")
    parser.add_argument("--no-discover", action="store_true", help="label only --tag values, skip discover_node_tags()")
    parser.add_argument("--dry-run", action="store_true", help="print the kubectl command and exit")
    parser.add_argument("--kubectl", default="kubectl")
    args = parser.parse_args(argv)

    tags: set[str] = set(args.tag)
    if not args.no_discover:
        tags |= discover_node_tags()
    try:
        labels = labels_for(tags)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    node = args.node
    if node is None and not args.dry_run:
        if shutil.which(args.kubectl) is None:
            print("error: kubectl not found and --dry-run not given", file=sys.stderr)
            return 2
        node = current_node_name(kubectl=args.kubectl)
        if node is None:
            print("error: cluster has zero or several nodes — pass --node", file=sys.stderr)
            return 2

    argv_out = kubectl_label_args(node or "<node>", labels, kubectl=args.kubectl)
    print("tags   :", " ".join(sorted(tags)))
    print("labels :", " ".join(f"{k}={v}" for k, v in sorted(labels.items())))
    print("command:", " ".join(argv_out))
    if args.dry_run:
        return 0

    before = existing_aif_labels(node, kubectl=args.kubectl)
    proc = subprocess.run(argv_out, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        print(f"error: kubectl label failed: {proc.stderr.strip()}", file=sys.stderr)
        return 1
    after = existing_aif_labels(node, kubectl=args.kubectl)
    added = sorted(set(after) - set(before))
    print(f"node {node}: {len(after)} aif.io labels ({len(added)} new): " + " ".join(added))
    return 0


if __name__ == "__main__":
    sys.exit(main())
