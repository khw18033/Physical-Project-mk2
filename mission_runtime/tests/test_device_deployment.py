"""implements: AI-B-05, AI-B-02, AI-B-03, AI-B-04, AI-B-11, AI-C-04, AI-C-05, AI-C-10, AI-C-15, AI-N-03
covers: (a) 같은 코드가 목적 데이터만 바꿔 서로 다른 기능 집합을 배포한다,
(b) 배치 사유 같은 일시적 값은 아티팩트 정체성에 들어가지 않는다,
(c) provider가 없는 상주 kind는 오류가 아니라 사유가 남는 축소다,
(d) 두 번째 적용은 제어 호출 0건이고 계획이 바뀐 만큼만 start/stop이 나간다,
(e) access_method 표가 제어 채널을 고르고 모르는 방식은 조용히 기본값으로 떨어지지 않는다,
(f) 비밀번호는 최초 1회만 쓰이고 검증 실패 시 등록을 건드리지 않으며 어디에도 남지 않는다,
(g) 재지 못한 링크는 '나쁨'이 아니라 '모름'이다.

실제 장치 시험은 `tests/test_ondevice_ssh.py`·`tests/test_k3s_control.py`와 같은
방식으로 `PF_ONDEVICE_TEST_DEVICE`에 걸려 있다 — Pi가 없어도 위 전부가 돈다.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest

from mission_runtime.contracts.profile import LinkProfile
from mission_runtime.contracts.profile_loader import load_device_purposes
from mission_runtime.execution.control import ControlResult, TargetStatus
from mission_runtime.providers.adapters import ControlProvider, ModelDeploymentProvider
from mission_runtime.providers.device_control import (
    ACCESS_METHOD_SSH,
    ARTIFACT_PARAM,
    DeviceChannel,
    DeviceChannelError,
    open_channel,
    register_access_method,
    supported_access_methods,
)
from mission_runtime.providers.link_probe import (
    DEFAULT_MAPPING,
    LinkMeasurement,
    LinkQualityMapping,
    METHOD_ICMP,
    link_profile_from,
    parse_ping_output,
)
from mission_runtime.providers.ondevice_bootstrap import (
    REASON_KEY_VERIFY_FAILED,
    REASON_NO_PASSWORD,
    BootstrapResult,
    bootstrap_key_auth,
    ensure_control_keypair,
    install_public_key,
)
from mission_runtime.registry.device_registry import (
    AUTH_KEY,
    AUTH_PASSWORD,
    CredentialStore,
    DeviceCredential,
    DeviceRegistration,
    DeviceRegistry,
)
from mission_runtime.runtime.application import ZoneApplication
from mission_runtime.runtime.device_deployment import (
    DEFAULT_UNIT_SOURCE,
    UNIT_CONFIG_NAME,
    DeviceDeployment,
    build_unit_source,
    plan_device_units,
    unit_config_for,
)
from mission_runtime.runtime.residency import decide_residency

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
PURPOSES = load_device_purposes(CONFIG_DIR / "device_purposes.example.json")

SECRET = "not-a-real-password"

#: 제어 노드 키쌍은 `ssh-keygen` 이 만든다. 없는 노드에서
#: `providers/ondevice_bootstrap.py::ensure_control_keypair` 는 추측하지 않고
#: `REASON_KEYGEN_MISSING` 으로 거절하는데(그것이 올바른 축소, AI-C-05) 그러면
#: "만들어진 키의 권한" 과 "키 검증 실패 시 등록 보존" 은 볼 대상 자체가 없어진다.
#: 키를 **만들지 않는** 경로(비밀번호 없음·stdin 전달·멱등 설치)는 같은 파일의
#: 다른 시험이 이 도구 없이도 그대로 본다.
needs_keygen = pytest.mark.skipif(
    shutil.which("ssh-keygen") is None,
    reason="ssh-keygen 이 이 노드에 없다 — 키 기반 부트스트랩 provider 만 skip "
           "이다(AI-C-05). openssh-client 를 설치하면 돈다",
)


# --- 테스트용 채널 -----------------------------------------------------------


@dataclass
class FakePackage:
    version: str
    sha256: str
    path: Path


class RecordingControl:
    """`ControlProvider` 하나. 무엇을 받았는지만 기록한다."""

    def __init__(self, reject: set[str] | None = None) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.audit_log: list = []
        self._reject = reject or set()
        self._running: set[str] = set()

    def request(self, command, target_id, params=None, *, requested_by="unknown"):
        self.calls.append((command, target_id, dict(params or {})))
        if target_id in self._reject:
            return ControlResult(False, None, rejection_reason="device_unreachable")
        if command == "start":
            self._running.add(target_id)
        else:
            self._running.discard(target_id)
        return ControlResult(True, TargetStatus.RUNNING if command == "start" else TargetStatus.STOPPED)

    def get_status(self, target_id):
        return TargetStatus.RUNNING if target_id in self._running else TargetStatus.STOPPED


def fake_channel(device_id="dev-1", reject=None):
    control = RecordingControl(reject)

    def pack(source_dir, dest_dir):
        source = Path(source_dir)
        payload = json.dumps(
            sorted((str(p.relative_to(source)), p.read_bytes().hex()) for p in sorted(source.rglob("*")) if p.is_file())
        )
        import hashlib

        digest = hashlib.sha256(payload.encode()).hexdigest()
        Path(dest_dir).mkdir(parents=True, exist_ok=True)
        return FakePackage(f"sha256-{digest[:16]}", digest, Path(dest_dir) / f"{digest[:16]}.tar.gz")

    return DeviceChannel(device_id, "fake", control, deployment=None, pack_unit=pack), control


def _plan_for(purpose_id, node_tags, budget, link=None):
    """목적 하나를 기존 해석 경로에 그대로 통과시킨다 — 여기서 재판정 없음."""
    from mission_runtime.contracts.profile import DeploymentProfile, ResourceBudget
    from mission_runtime.registry.manifest import load_provider_manifest, register_all
    from mission_runtime.registry.capability_registry import CapabilityRegistry

    purpose = PURPOSES[purpose_id]
    plan = decide_residency(purpose, link=link)
    registry = CapabilityRegistry()
    register_all(load_provider_manifest(CONFIG_DIR / "providers.status_ui.ondevice.example.json"), registry)
    profile = plan.ondevice_profile(DeploymentProfile(domain_id="test", active_capability_kinds=purpose.kinds()))
    app = ZoneApplication(profile, registry, plan.capability_specs(purpose), node_tags=set(node_tags))
    resolutions = app.resolve(budget or ResourceBudget(compute_units=99.0, memory_mb=99999.0))
    return purpose, plan, resolutions


# --- (a) 같은 코드, 다른 데이터 ----------------------------------------------


def test_different_purposes_deploy_different_function_sets():
    """드론과 고정 카메라의 배포 집합이 다른 이유는 오직 목적 데이터다."""
    drone_tags = {"compute.cpu", "tier.ondevice", "platform.uav", "sensor.camera.uav"}
    camera_tags = {"compute.cpu", "tier.fixed_camera", "sensor.camera.imx708"}

    drone = plan_device_units("d", *_plan_for("river_surveillance_drone", drone_tags, None))
    camera = plan_device_units("c", *_plan_for("fixed_camera", camera_tags, None))

    assert "safety.local_judgment" in drone.kinds
    assert "mission.dispatch" in drone.kinds
    # 고정 카메라는 이동형이 아니므로 안전 판단 자체가 없다.
    assert "safety.local_judgment" not in camera.kinds
    assert set(camera.kinds) < set(drone.kinds) or set(camera.kinds) != set(drone.kinds)
    # 판정 코드는 하나뿐이고 두 결과 모두 같은 함수에서 나왔다.
    assert drone.purpose_id != camera.purpose_id


def test_go1_keeps_a_survival_set_but_never_pulls_the_heavy_stack_home():
    """AI-N-03 + AI-C-05: 링크가 끊겨도 장애물 감지·안전은 남고, zero-shot은
    말단으로 끌려오지 않는다(끌어오면 실시간이 아니게 되므로 local_fallback)."""
    tags = {"compute.cpu", "tier.ondevice", "sensor.camera.go1_front"}
    purpose = PURPOSES["ground_robot"]
    dead = LinkProfile(source="test", quality=0.0, stability=0.0, samples=20)
    plan = decide_residency(purpose, link=dead)

    survivors = set(plan.survives_outage_kinds())
    assert {"perception.depth", "safety.local_judgment", "control.locomotion"} <= survivors
    # 링크가 완전히 죽어도 zero-shot은 여전히 엣지 몫이다.
    ovd = plan.decision_for("perception.detect_ovd")
    assert ovd is not None and not ovd.is_ondevice
    assert ovd.local_fallback_kind == "perception.detect"
    report = plan.outage_survival_report()
    assert "perception.detect_ovd" in report["degrades_to_local_fallback"]
    assert not plan.violations, plan.violations


def test_no_domain_name_appears_in_the_deciding_modules():
    """절대 준수 원칙 #3: 판정·연결 코드에 도메인·장치 이름이 없어야 한다."""
    root = Path(__file__).resolve().parents[1]
    forbidden = ("drone", "go1", "robot", "river", "camera_purpose")
    for module in ("runtime/residency.py", "runtime/device_deployment.py", "providers/device_control.py"):
        text = (root / module).read_text(encoding="utf-8").lower()
        # 주석의 설명은 허용하되 코드 줄에는 없어야 한다.
        code = "\n".join(
            line for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#") and not line.strip().startswith("*")
        )
        for word in forbidden:
            assert f'"{word}' not in code and f"'{word}" not in code, f"{module} branches on {word}"


# --- (b) 아티팩트 정체성 -----------------------------------------------------


def test_unit_config_is_deterministic_and_carries_the_declaration():
    purpose, plan, _ = _plan_for("ground_robot", {"compute.cpu", "tier.ondevice"}, None)
    first = unit_config_for(purpose, plan, "perception.depth", "zipdepth-ondevice")
    second = unit_config_for(purpose, plan, "perception.depth", "zipdepth-ondevice")
    assert first == second
    assert first["unit_kind"] == "perception.depth"
    assert first["purpose_id"] == "ground_robot"
    assert first["quality_is_safety_affecting"] is True
    assert first["survives_outage"] is True


def test_transient_link_reason_never_enters_the_artifact(tmp_path):
    """링크 표현이 바뀌었다고 아티팩트 sha256이 바뀌면 안 된다.

    실제로 그렇게 만들었다가 확인한 churn이다 — 기능이 하나도 달라지지 않았는데
    `link_posture_requires_local:reducing` → `...:local_only`만으로 재배포가
    나갔다. AI-B-02의 "버전 = 코드 + 구성"에서 구성은 기능을 바꾸는 구성이다.
    """
    tags = {"compute.cpu", "tier.fixed_camera", "sensor.camera.imx708"}
    good = LinkProfile(source="t", quality=0.95, stability=1.0, samples=20)
    bad = LinkProfile(source="t", quality=0.30, stability=1.0, samples=20)

    a = plan_device_units("x", *_plan_for("fixed_camera", tags, None, link=good))
    b = plan_device_units("x", *_plan_for("fixed_camera", tags, None, link=bad))

    resident = "media.video_input"
    ca = next(u for u in a.units if u.kind == resident)
    cb = next(u for u in b.units if u.kind == resident)
    assert ca.config == cb.config, "resident kind's artifact must not change with the link"
    # 사유 자체는 계획에 남아 있어야 한다 — 숨기는 것이 아니라 옮긴 것이다.
    assert ca.residency_reason and cb.residency_reason
    # 링크가 나빠지면 인지가 말단으로 내려온다(link_dependent).
    assert "perception.detect" not in a.kinds
    assert "perception.detect" in b.kinds


def test_build_unit_source_writes_sorted_config(tmp_path):
    out = build_unit_source(DEFAULT_UNIT_SOURCE, tmp_path / "u", {"b": 2, "a": 1})
    text = (out / UNIT_CONFIG_NAME).read_text(encoding="utf-8")
    assert text.index('"a"') < text.index('"b"')
    assert (out / "run.sh").is_file() and (out / "unit.py").is_file()


# --- (c) provider 결손은 축소다 ----------------------------------------------


def test_missing_provider_becomes_a_skipped_kind_with_its_reason():
    """AI-C-05: 선택 기능의 결손은 정상이고, 사유는 기존 어휘 그대로 남는다."""
    from mission_runtime.contracts.profile import ResourceBudget

    # 예산을 거의 0으로 두면 상주 kind 대부분이 붙지 못한다.
    tags = {"compute.cpu", "tier.ondevice"}
    plan = plan_device_units(
        "x", *_plan_for("ground_robot", tags, ResourceBudget(compute_units=0.6, memory_mb=128.0))
    )
    assert plan.skipped, "a starved device must report skipped kinds"
    for skipped in plan.skipped:
        assert skipped.reason, "a skipped kind must say why"
    # 계획을 세우는 것 자체는 실패하지 않는다.
    assert isinstance(plan.units, tuple)


# --- (d) 두 번째 적용은 아무 일도 하지 않는다 --------------------------------


def test_apply_is_idempotent_and_diffs_only_what_changed(tmp_path):
    tags = {"compute.cpu", "tier.fixed_camera", "sensor.camera.imx708"}
    good = LinkProfile(source="t", quality=0.95, stability=1.0, samples=20)
    bad = LinkProfile(source="t", quality=0.30, stability=1.0, samples=20)

    channel, control = fake_channel()
    deployment = DeviceDeployment(channel=channel, staging_dir=tmp_path / "stage")

    purpose, plan, resolutions = _plan_for("fixed_camera", tags, None, link=good)
    unit_plan = plan_device_units("x", purpose, plan, resolutions)
    _, actions = deployment.apply(unit_plan, resolutions)
    assert [a.command for a in actions] == ["start"]
    assert all(a.accepted for a in actions)
    # 아티팩트가 start params로 실제로 실려 간다(AI-B-02).
    assert ARTIFACT_PARAM in control.calls[0][2]

    before = len(control.calls)
    _, again = deployment.apply(unit_plan, resolutions)
    assert again == ()
    assert len(control.calls) == before, "an unchanged plan must issue no control calls"

    purpose, plan, resolutions = _plan_for("fixed_camera", tags, None, link=bad)
    degraded = plan_device_units("x", purpose, plan, resolutions)
    _, actions = deployment.apply(degraded, resolutions)
    assert [(a.kind, a.command) for a in actions] == [("perception.detect", "start")]

    stopped = deployment.stop_all()
    assert {a.command for a in stopped} == {"stop"}


def test_a_rejected_unit_does_not_stop_the_others(tmp_path):
    """AI-C-05: 한 unit의 거절은 그 unit 하나의 문제여야 한다."""
    tags = {"compute.cpu", "tier.ondevice", "sensor.camera.go1_front"}
    purpose, plan, resolutions = _plan_for("ground_robot", tags, None)
    unit_plan = plan_device_units("x", purpose, plan, resolutions)
    victim = unit_plan.units[1].provider_id

    channel, control = fake_channel(reject={victim})
    deployment = DeviceDeployment(channel=channel, staging_dir=tmp_path / "stage")
    _, actions = deployment.apply(unit_plan, resolutions)

    rejected = [a for a in actions if not a.accepted]
    assert len(rejected) == 1 and rejected[0].provider_id == victim
    assert len([a for a in actions if a.accepted]) == len(unit_plan.units) - 1


def test_state_reports_three_health_readings_or_none(tmp_path):
    """health를 못 내놓는 채널도 정상이다(AI-C-18: 항상 존재한다고 가정 금지)."""
    tags = {"compute.cpu", "tier.fixed_camera", "sensor.camera.imx708"}
    purpose, plan, resolutions = _plan_for("fixed_camera", tags, None)
    channel, _ = fake_channel()
    deployment = DeviceDeployment(channel=channel, staging_dir=tmp_path / "stage")
    deployment.apply(plan_device_units("x", purpose, plan, resolutions), resolutions)
    state = deployment.state()
    assert state["units"]
    assert all(u["health"] is None for u in state["units"])  # fake channel offers none
    assert all(u["artifact_sha256"] for u in state["units"])


# --- (e) access_method 표 -----------------------------------------------------


def test_ssh_access_method_yields_the_two_protocols():
    device = DeviceRegistration("t", "192.0.2.9", "physical", "c1")
    channel = open_channel(device, DeviceCredential("c1", AUTH_KEY, key_path="~/.ssh/nope"))
    assert channel.access_method == ACCESS_METHOD_SSH
    assert isinstance(channel.control, ControlProvider)
    assert isinstance(channel.deployment, ModelDeploymentProvider)
    assert channel.pack_unit is not None


def test_unknown_access_method_is_refused_not_defaulted():
    device = DeviceRegistration("t", "192.0.2.9", "physical", "c1", access_method="carrier-pigeon")
    with pytest.raises(DeviceChannelError) as error:
        open_channel(device, None)
    assert "unsupported_access_method" in str(error.value)


def test_a_new_access_method_is_a_registration_not_a_code_change():
    name = f"test-{uuid.uuid4().hex[:6]}"
    register_access_method(name, lambda d, c=None, **k: DeviceChannel(d.device_id, name, RecordingControl()))
    assert name in supported_access_methods()
    device = DeviceRegistration("t", "192.0.2.9", "u", "c1", access_method=name)
    assert open_channel(device, None).access_method == name


# --- (f) 자격증명 -------------------------------------------------------------


class ScriptedRunner:
    """`SshRunner` 모양. argv에 무엇이 실렸는지 볼 수 있게 기록한다."""

    def __init__(self, device, credential=None, *, returncode=0, stdout="ok:installed\n"):
        self.device = device
        self.credential = credential
        self.seen: list[tuple[str, str | None]] = []
        self._returncode = returncode
        self._stdout = stdout

    def run(self, command, *, timeout=None, stdin=None):
        self.seen.append((command, stdin))
        return subprocess.CompletedProcess([], self._returncode, self._stdout, "")


@needs_keygen
def test_generated_control_key_is_owner_only(tmp_path):
    private, public = ensure_control_keypair(tmp_path / "keys" / "id_test")
    assert public.startswith("ssh-ed25519 ")
    assert stat.S_IMODE(private.stat().st_mode) == 0o600
    # 두 번째 호출은 기존 키를 그대로 쓴다(새로 만들지 않는다).
    again, public_again = ensure_control_keypair(tmp_path / "keys" / "id_test")
    assert again == private and public_again == public


def test_public_key_travels_on_stdin_never_in_argv():
    device = DeviceRegistration("t", "192.0.2.9", "u", "c1")
    runner = ScriptedRunner(device)
    key = "ssh-ed25519 AAAAC3Nz-fake-key operator@host"
    result = install_public_key(runner, key)
    assert result.key_installed is True
    command, stdin = runner.seen[0]
    assert key not in command, "the key must not be an argv element"
    assert stdin is not None and key in stdin


def test_install_is_idempotent_by_report():
    device = DeviceRegistration("t", "192.0.2.9", "u", "c1")
    runner = ScriptedRunner(device, stdout="ok:already_present\n")
    result = install_public_key(runner, "ssh-ed25519 AAA x")
    assert result.key_installed is True and result.already_present is True


def test_bootstrap_without_password_is_a_reason_not_an_exception(tmp_path):
    store = CredentialStore(tmp_path / "creds.json", strict_permissions=False)
    registry = DeviceRegistry(store)
    registry.register_address("t", "192.0.2.9", "u", credential=DeviceCredential("c1", AUTH_KEY))
    result = bootstrap_key_auth(registry, "t", password="", key_path=tmp_path / "k")
    assert result.reason == REASON_NO_PASSWORD and result.ok is False


@needs_keygen
def test_failed_verification_leaves_the_registration_alone(tmp_path, monkeypatch):
    """키가 안 먹는데 등록을 바꾸면 접속 수단을 잃는다(AI-B-05의 last-known-good)."""
    import mission_runtime.providers.ondevice_bootstrap as boot

    store = CredentialStore(tmp_path / "creds.json", strict_permissions=False)
    registry = DeviceRegistry(store)
    registry.register_address(
        "t", "192.0.2.9", "u", credential=DeviceCredential("boot", AUTH_PASSWORD, secret=SECRET)
    )
    monkeypatch.setattr(boot.shutil, "which", lambda name: "/usr/bin/sshpass")
    monkeypatch.setattr(boot, "install_public_key", lambda r, k, **kw: BootstrapResult("t", True, True))
    monkeypatch.setattr(boot, "_verify_key_auth", lambda runner: False)
    monkeypatch.setattr(
        "mission_runtime.providers.ondevice_ssh.SshRunner", lambda device, cred=None, **kw: ScriptedRunner(device, cred)
    )

    result = bootstrap_key_auth(registry, "t", password=SECRET, key_path=tmp_path / "k", persist=False)
    assert result.reason == REASON_KEY_VERIFY_FAILED and result.ok is False
    assert registry.get("t").credential_id == "boot", "a failed bootstrap must not rotate the credential"


def test_no_secret_reaches_a_persisted_device_file(tmp_path):
    store = CredentialStore(tmp_path / "creds.json", strict_permissions=False)
    registry = DeviceRegistry(store)
    registry.register_address(
        "t", "192.0.2.9", "u",
        credential=DeviceCredential("boot", AUTH_PASSWORD, secret=SECRET),
        purpose_id="fixed_camera",
    )
    registry.save(tmp_path / "devices.json")
    text = (tmp_path / "devices.json").read_text(encoding="utf-8")
    assert SECRET not in text
    assert "fixed_camera" in text, "purpose_id is declaration data and belongs in the device file"
    assert SECRET not in repr(registry.credential_for("t"))
    assert registry.credential_for("t").redacted()["has_secret"] is True


def test_world_readable_credential_file_stays_refused(tmp_path):
    path = tmp_path / "creds.json"
    path.write_text(json.dumps({"credentials": []}), encoding="utf-8")
    os.chmod(path, 0o644)
    with pytest.raises(Exception) as error:
        CredentialStore(path, strict_permissions=True)
    assert "group/world" in str(error.value)


# --- (g) 재지 못한 링크 -------------------------------------------------------


PING_GOOD = """20 packets transmitted, 20 received, 0% packet loss, time 3813ms
rtt min/avg/max/mdev = 6.073/7.706/13.642/1.780 ms"""
PING_BAD = """20 packets transmitted, 14 received, 30% packet loss, time 3815ms
rtt min/avg/max/mdev = 40.5/125.4/480.6/95.1 ms"""


def test_measurement_maps_to_quality_and_stability():
    good = link_profile_from(parse_ping_output("h", PING_GOOD))
    assert good is not None and good.quality == pytest.approx(1.0)
    bad = link_profile_from(parse_ping_output("h", PING_BAD))
    assert bad is not None and bad.quality < good.quality
    assert bad.source.startswith("measured:")


def test_unmeasurable_link_is_unknown_not_bad():
    """AI-N-03: 특정 측정값이 항상 존재한다고 가정하지 않는다."""
    nothing = LinkMeasurement("h", METHOD_ICMP, reason="probe_tool_unavailable")
    assert link_profile_from(nothing) is None
    assert nothing.loss_fraction is None


def test_total_loss_is_zero_quality_not_unknown():
    dead = LinkMeasurement("h", METHOD_ICMP, sent=20, received=0)
    profile = link_profile_from(dead)
    assert profile is not None and profile.quality == 0.0 and profile.stability == 0.0


def test_stability_counts_samples_below_the_floor():
    """평균이 좋아도 표본이 floor 아래로 내려간 비율이 stability다."""
    mapping = LinkQualityMapping(reference_rtt_ms=50.0, floor=0.25)
    spiky = LinkMeasurement(
        "h", METHOD_ICMP, sent=4, received=4, rtt_avg_ms=60.0,
        rtt_samples_ms=(10.0, 10.0, 10.0, 400.0),
    )
    assert mapping.stability(spiky) == pytest.approx(0.75)
    assert mapping.stability(LinkMeasurement("h", METHOD_ICMP, sent=4, received=4)) is None


def test_reference_rtt_matches_the_placement_floor():
    """환산표의 floor와 배치 판정의 floor가 갈라지면 말이 어긋난다."""
    from mission_runtime.contracts.profile import LinkPostureThresholds

    assert DEFAULT_MAPPING.floor == LinkPostureThresholds().floor


# --- 실제 장치 (PF_ONDEVICE_TEST_DEVICE) --------------------------------------

REAL_DEVICE = os.environ.get("PF_ONDEVICE_TEST_DEVICE")
needs_device = pytest.mark.skipif(
    not REAL_DEVICE or not (CONFIG_DIR / "devices.json").exists(),
    reason="set PF_ONDEVICE_TEST_DEVICE and provide config/devices.json to run against real hardware",
)


@pytest.fixture
def real_device_deployment(tmp_path):
    store = CredentialStore(CONFIG_DIR / "device_credentials.json")
    registry = DeviceRegistry(store)
    registry.load(CONFIG_DIR / "devices.json")
    device = registry.get(REAL_DEVICE)
    if device is None:
        pytest.skip(f"{REAL_DEVICE} not in config/devices.json")
    channel = open_channel(device, registry.credential_for(REAL_DEVICE), command_timeout_s=90)
    deployment = DeviceDeployment(channel=channel, staging_dir=tmp_path / "stage")
    yield deployment, device
    deployment.stop_all()
    for unit_id in tuple(deployment._units):  # never leave units behind on real hardware
        deployment.remove(unit_id)


@needs_device
def test_real_device_deploys_exactly_what_the_purpose_decided(real_device_deployment):
    deployment, device = real_device_deployment
    purpose_id = device.purpose_id or "fixed_camera"
    tags = set(device.node_tags) | {"tier.ondevice", "compute.cpu"}
    purpose, plan, resolutions = _plan_for(purpose_id, tags, None)
    unit_plan = plan_device_units(device.device_id, purpose, plan, resolutions)

    prepared, actions = deployment.apply(unit_plan, resolutions)
    assert actions and all(a.accepted for a in actions), [a for a in actions if not a.accepted]
    assert {u.kind for u in prepared.units} == set(plan.ondevice_kinds) - {s.kind for s in unit_plan.skipped}

    import time

    time.sleep(5)
    state = deployment.state()
    for unit in state["units"]:
        health = unit["health"]
        assert health is not None and health["reachable"] is True
        assert health["liveness"] == "ALIVE"
        # 세 갈래가 각각 읽힌다 — 하나로 접히지 않는다(AI-B-05).
        assert health["readiness"] in ("READY", "NOT_READY")
        assert health["device_state"] in ("NOMINAL", "THROTTLED", "UNKNOWN")

    # 두 번째 적용은 장치를 건드리지 않는다.
    _, again = deployment.apply(unit_plan, resolutions)
    assert again == ()
