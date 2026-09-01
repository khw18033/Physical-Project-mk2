"""implements: AI-B-09, AI-C-04, AI-C-05, AI-C-15
"""
import json
from pathlib import Path

from perception_framework.contracts.capability import CapabilityState
from perception_framework.contracts.profile import ResourceBudget
from perception_framework.contracts.profile_loader import is_capability_active, load_profile
from perception_framework.providers.fakes import InMemoryTransportProvider
from perception_framework.runtime.application import ZoneApplication
from perception_framework.simulation.sources import ScriptedSeriesSource
from perception_framework.simulation.terminals import VirtualRiverTerminal, VirtualRobotTerminal

from .conftest import core_source_mentions, registration, spec

PROFILE_DIR = Path(__file__).resolve().parents[2] / "profiles"
BUDGET = ResourceBudget(compute_units=100.0, memory_mb=8192.0)

# The capability catalogue is data too: every kind any domain might use.
ALL_SPECS = [
    spec("safety.local_judgment", core=True),
    spec("perception.detect", rank=1),
    spec("perception.track", rank=2),
    spec("perception.associate", rank=3),
    spec("perception.environment_map", rank=4),
    spec("ondevice.link_transition", rank=5),
    spec("risk.state_machine", rank=6),
    spec("risk.rule_based", rank=7),
    spec("media.video_input", rank=8),
    spec("observation.adaptive", rank=9),
]


def registry_with_every_provider():
    from perception_framework.registry.capability_registry import CapabilityRegistry

    registry = CapabilityRegistry()
    for capability in ALL_SPECS:
        registry.register_local(registration(capability.kind, f"{capability.kind}-provider"))
    return registry


def run_domain(profile_path: Path):
    """The *only* thing that differs between domains is this argument."""
    profile = load_profile(profile_path)
    app = ZoneApplication(profile, registry_with_every_provider(), ALL_SPECS)
    app.resolve(BUDGET)
    return profile, app


def test_s12_robot_profile_activates_perception_and_mapping_but_no_risk_fsm():
    profile, app = run_domain(PROFILE_DIR / "robot.json")

    assert app.state_of("perception.detect") is CapabilityState.ACTIVE
    assert app.state_of("perception.environment_map") is CapabilityState.ACTIVE
    assert app.state_of("risk.state_machine") is CapabilityState.DISABLED
    assert not is_capability_active(profile, "risk.state_machine")


def test_s12_river_profile_activates_risk_and_leaves_mapping_uninstalled():
    profile, app = run_domain(PROFILE_DIR / "river.json")

    assert app.state_of("risk.state_machine") is CapabilityState.ACTIVE
    assert app.state_of("risk.rule_based") is CapabilityState.ACTIVE
    assert app.state_of("perception.environment_map") is CapabilityState.DISABLED
    # 사용하지 않는 기능은 설치·실행을 요구하지 않는다 (AI-C-15).
    assert "perception.environment_map" not in profile.active_capability_kinds


def test_s12_switching_profiles_requires_no_code_change_at_all():
    """같은 함수(run_domain)가 인자만 바뀌어 두 도메인을 모두 구동한다."""
    _, robot_app = run_domain(PROFILE_DIR / "robot.json")
    _, river_app = run_domain(PROFILE_DIR / "river.json")

    robot_running = set(robot_app.running_kinds())
    river_running = set(river_app.running_kinds())

    assert robot_running != river_running
    assert robot_running and river_running


def test_s12_core_code_contains_no_domain_identifier():
    """지표: Robot → River 전환 시 Core 코드 변경 0 LOC (정적 확인)."""
    for path in PROFILE_DIR.glob("*.json"):
        domain_id = json.loads(path.read_text(encoding="utf-8"))["domain_id"]
        assert core_source_mentions(domain_id) == []


def test_s12_both_domains_drive_their_own_virtual_terminal_through_one_contract():
    robot_transport, river_transport = InMemoryTransportProvider(), InMemoryTransportProvider()
    robot = VirtualRobotTerminal("virtual_robot_01", robot_transport)
    river = VirtualRiverTerminal(
        "virtual_river_01",
        river_transport,
        sources={"water_level": ScriptedSeriesSource("water_level", [1.2, 1.9, 2.6])},
    )
    robot.start()
    river.start()

    robot.publish_observation("robot_position", [1.0, 2.0])
    emitted = river.pump_once()

    assert emitted == {"water_level": 1.2}
    # 서로 다른 도메인의 말단이 동일한 전송 계약만 사용한다 (AI-C-04, AI-C-06).
    assert len(robot_transport.published) == len(river_transport.published) == 1


# --- Scenario 13 — a brand-new domain added after the fact -----------------

SURVEILLANCE = {
    "domain_id": "perimeter_surveillance",
    "active_capability_kinds": [
        "media.video_input",
        "perception.detect",
        "perception.track",
        "perception.associate",
    ],
    "rule_set_id": "perimeter_rules_v1",
    "node_tags": ["cpu", "fixed"],
}


def test_s13_a_new_domain_needs_only_a_profile_file(tmp_path):
    path = tmp_path / "surveillance.json"
    path.write_text(json.dumps(SURVEILLANCE), encoding="utf-8")

    profile, app = run_domain(path)

    assert profile.domain_id == "perimeter_surveillance"
    for kind in SURVEILLANCE["active_capability_kinds"]:
        assert app.state_of(kind) is CapabilityState.ACTIVE
    # 감시 도메인이 쓰지 않는 기능은 활성화되지 않는다.
    assert app.state_of("risk.state_machine") is CapabilityState.DISABLED
    assert app.state_of("perception.environment_map") is CapabilityState.DISABLED


def test_s13_the_new_domain_name_appears_nowhere_in_core_code():
    assert core_source_mentions("perimeter_surveillance") == []
    assert core_source_mentions("surveillance") == []


def test_s13_new_domain_shares_the_same_core_modules_as_the_existing_ones(tmp_path):
    """지표: 도메인 간 공유 Core module 비율."""
    path = tmp_path / "surveillance.json"
    path.write_text(json.dumps(SURVEILLANCE), encoding="utf-8")

    _, robot_app = run_domain(PROFILE_DIR / "robot.json")
    _, river_app = run_domain(PROFILE_DIR / "river.json")
    _, watch_app = run_domain(path)

    # 세 도메인 모두 같은 클래스가 구동한다.
    assert type(robot_app) is type(river_app) is type(watch_app) is ZoneApplication
    shared_kinds = set(robot_app.running_kinds()) & set(watch_app.running_kinds())
    assert shared_kinds, "domains should reuse capability implementations"
