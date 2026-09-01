"""implements: AI-C-15
covers: domain as data, no domain branching in core, unused capability stays off
"""

import json
import subprocess
from pathlib import Path

import pytest

from perception_framework.contracts.profile_loader import (
    DeploymentProfileError,
    is_capability_active,
    load_profile,
    profile_from_dict,
)

PROFILE_DIR = Path(__file__).resolve().parents[1] / "profiles"
PACKAGE_DIR = Path(__file__).resolve().parents[1] / "perception_framework"


@pytest.mark.parametrize("name", ["robot", "facility", "river"])
def test_each_shipped_domain_profile_loads(name):
    profile = load_profile(PROFILE_DIR / f"{name}.json")

    assert profile.domain_id
    assert profile.active_capability_kinds


def test_active_capability_set_differs_per_domain_without_code_change():
    robot = load_profile(PROFILE_DIR / "robot.json")
    river = load_profile(PROFILE_DIR / "river.json")

    # 같은 코드가 프로파일만 바뀌어 다른 기능 조합으로 동작한다 (AI-C-15).
    assert is_capability_active(robot, "perception.environment_map")
    assert not is_capability_active(river, "perception.environment_map")
    assert is_capability_active(river, "risk.state_machine")
    assert not is_capability_active(robot, "risk.state_machine")


def test_unknown_field_is_rejected_rather_than_silently_ignored():
    with pytest.raises(DeploymentProfileError):
        profile_from_dict(
            {"domain_id": "x", "active_capability_kinds": [], "activ_capability_kinds": ["typo"]}
        )


def test_missing_required_field_is_rejected():
    with pytest.raises(DeploymentProfileError):
        profile_from_dict({"domain_id": "x"})


def test_a_brand_new_domain_needs_only_a_file(tmp_path):
    path = tmp_path / "new_domain.json"
    path.write_text(
        json.dumps({"domain_id": "tunnel_inspection", "active_capability_kinds": ["perception.detect"]}),
        encoding="utf-8",
    )

    profile = load_profile(path)

    assert profile.domain_id == "tunnel_inspection"
    assert is_capability_active(profile, "perception.detect")


def test_core_code_contains_no_domain_name_branching():
    """절대 준수 원칙 #3: 도메인명을 기준으로 핵심 코드에 분기문을 추가하지 않는다.

    Enforced statically so the rule cannot rot: no domain identifier from
    any shipped profile may appear anywhere in the package source.
    """
    domain_ids = [load_profile(p).domain_id for p in PROFILE_DIR.glob("*.json")]
    assert domain_ids, "no profiles found to check"

    for domain_id in domain_ids:
        hit = subprocess.run(
            ["grep", "-rn", domain_id, str(PACKAGE_DIR)], capture_output=True, text=True
        )
        assert hit.returncode != 0, f"domain id {domain_id!r} leaked into core code:\n{hit.stdout}"
