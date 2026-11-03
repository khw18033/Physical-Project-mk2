"""implements: AI-B-04, AI-B-11

`tools/infra/label_node.py` turns the framework's measured node tags into
`aif.io/<tag>=true` labels through the *same* function the placement
reconciler uses, so scheduler labels and selector tags cannot drift apart.
No cluster is needed for these tests; the real `kubectl` call is exercised by
`make check` on a box with K3s.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

from mission_runtime.runtime.placement import LABEL_PREFIX

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "infra" / "label_node.py"


def _import():
    name = "label_node_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_labels_use_the_reconciler_spelling():
    mod = _import()
    labels = mod.labels_for({"compute.gpu", "tier.edge", "compute.cpu"})
    assert labels == {
        f"{LABEL_PREFIX}compute.cpu": "true",
        f"{LABEL_PREFIX}compute.gpu": "true",
        f"{LABEL_PREFIX}tier.edge": "true",
    }


def test_illegal_tag_is_rejected_before_kubectl_is_touched():
    mod = _import()
    with pytest.raises(ValueError):
        mod.labels_for({"bad tag with spaces"})


def test_kubectl_args_are_deterministic_and_overwrite():
    mod = _import()
    args = mod.kubectl_label_args("node-a", {"aif.io/b": "true", "aif.io/a": "true"})
    assert args == ["kubectl", "label", "node", "node-a", "--overwrite", "aif.io/a=true", "aif.io/b=true"]


def test_dry_run_prints_command_without_a_cluster(capsys):
    mod = _import()
    rc = mod.main(["--dry-run", "--no-discover", "--tag", "tier.edge", "--node", "n1", "--kubectl", "/nonexistent/kubectl"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "aif.io/tier.edge=true" in out and "label node n1" in out


def test_discovered_tags_are_included_by_default(capsys):
    mod = _import()
    rc = mod.main(["--dry-run", "--node", "n1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "aif.io/compute.cpu=true" in out  # discover_node_tags() always reports the CPU
