"""implements: AI-N-03, AI-C-04, AI-C-05, AI-B-10
covers: 실제 장비 출력 파싱(/proc/net/wireless, NetworkManager terse), dBm→정규화
        환산의 단조성·포화, 측정 실패를 0으로 채우지 않는 것, 모르는 BSSID의
        구역을 추측하지 않는 것, 구역 정책에 물렸을 때의 동작, 그리고 실제 Pi를
        상대로 한 옵트인 시험

고정 입력 문자열은 2026-09-18에 pi6/pi2(Raspberry Pi 5)에서 실제로 받아 온
것이다. 그 장비에는 `iw`도 `iwconfig`도 `wpa_cli`도 없고 sudo도 없어서, 실제로
읽을 수 있는 경로가 이 두 가지뿐이라는 사실 자체가 이 provider의 설계 근거다.
실기기 시험은 `tests/test_ondevice_ssh.py`와 같은 방식으로 환경변수로 연다.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from mission_runtime.ondevice.link_handover import LinkPosture, LinkSample
from mission_runtime.ondevice.zone_handover import ZoneHandoverPolicy
from mission_runtime.providers.rssi_link_quality import (
    DEFAULT_MAPPING,
    REASON_INTERFACE_NOT_FOUND,
    REASON_SOURCE_UNAVAILABLE,
    RssiLinkQualityProvider,
    RssiQualityMapping,
    RssiReading,
    SOURCE_NM_SCAN,
    SOURCE_PROC_NET_WIRELESS,
    local_text_reader,
    parse_nm_scan,
    parse_proc_net_wireless,
    runner_text_reader,
)

# pi6 실측 (2026-09-18)
PROC_TEXT = (
    "Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE\n"
    " face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22\n"
    " wlan0: 0000   66.  -44.  -256        0      0      0      4      0        0\n"
)
# pi2 실측 — 같은 AP, 같은 시각대인데 7dB 더 낮다.
PROC_TEXT_WEAKER = (
    "Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE\n"
    " face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22\n"
    " wlan0: 0000   57.  -53.  -256        0      0      0      0      0        0\n"
)
# `nmcli -t -f IN-USE,SSID,BSSID,SIGNAL,FREQ dev wifi list` 실측. BSSID의 ':'가
# '\:'로 이스케이프돼 있다는 점이 파서의 핵심이다.
NM_TEXT = "*:SysAILAB_5GHz:04\\:42\\:1A\\:10\\:1F\\:34:76:5805 MHz\n"
NM_TEXT_TWO_APS = (
    "*:SysAILAB_5GHz:04\\:42\\:1A\\:10\\:1F\\:34:76:5805 MHz\n"
    " :SysAILAB_5GHz:04\\:42\\:1A\\:10\\:1F\\:99:52:5805 MHz\n"
)

BSSID_A = "04:42:1A:10:1F:34"
BSSID_B = "04:42:1A:10:1F:99"


def reader(text):
    return lambda: text


def failing_reader():
    return lambda: None


# --- 파싱 ---------------------------------------------------------------------


def test_proc_net_wireless_is_parsed_into_level_and_raw_link_quality():
    readings = parse_proc_net_wireless(PROC_TEXT, at=1.0)

    assert len(readings) == 1
    reading = readings[0]
    assert reading.interface == "wlan0"
    assert reading.level_dbm == -44.0
    assert reading.link_quality_raw == 66.0     # 드라이버 척도 — 해석하지 않고 보존
    assert reading.noise_dbm == -256.0
    assert reading.source == SOURCE_PROC_NET_WIRELESS


def test_the_header_lines_are_not_mistaken_for_readings():
    assert parse_proc_net_wireless("Inter-| sta-|\n face | tus |\n") == ()


def test_nm_scan_unescapes_the_bssid_and_keeps_the_in_use_marker():
    readings = parse_nm_scan(NM_TEXT_TWO_APS, at=1.0)

    assert [r.peer_id for r in readings] == [BSSID_A, BSSID_B]
    assert readings[0].interface == "*"          # 붙어 있는 AP
    assert readings[1].interface is None
    assert readings[0].signal_percent == 76.0
    assert readings[0].ssid == "SysAILAB_5GHz"
    assert readings[0].source == SOURCE_NM_SCAN


def test_scan_zone_comes_from_deployment_data_not_from_a_guess():
    readings = parse_nm_scan(NM_TEXT_TWO_APS, at=1.0, peer_zones={BSSID_A: "zone-a"})

    zones = {r.peer_id: r.zone_id for r in readings}
    assert zones[BSSID_A] == "zone-a"
    assert zones[BSSID_B] is None                # 모르는 AP의 구역을 지어내지 않는다


def test_a_malformed_scan_line_is_skipped_rather_than_half_read():
    assert parse_nm_scan("garbage\n:::\n") == ()


# --- 환산 ---------------------------------------------------------------------


def test_quality_is_monotonic_in_signal_strength():
    mapping = RssiQualityMapping()
    strong = mapping.quality_of_dbm(-44.0)
    weak = mapping.quality_of_dbm(-53.0)

    assert strong > weak
    assert 0.0 <= weak < strong <= 1.0


def test_quality_saturates_at_both_ends_instead_of_leaving_the_range():
    mapping = RssiQualityMapping(excellent_dbm=-45.0, floor_dbm=-85.0)

    assert mapping.quality_of_dbm(-20.0) == 1.0
    assert mapping.quality_of_dbm(-120.0) == 0.0


def test_the_two_measured_pis_map_to_the_order_the_measurement_showed():
    """pi6(-44dBm)과 pi2(-53dBm)는 같은 AP에 붙어 있었고 pi2가 실제로 더 나빴다."""
    pi6 = parse_proc_net_wireless(PROC_TEXT, at=1.0)[0]
    pi2 = parse_proc_net_wireless(PROC_TEXT_WEAKER, at=1.0)[0]

    assert DEFAULT_MAPPING.quality(pi6) > DEFAULT_MAPPING.quality(pi2)


def test_the_mapping_reference_points_are_data_not_code():
    """환산 기준점을 바꾸면 같은 신호가 다른 판정을 받는다 — 현장별 조정 경로."""
    reading = parse_proc_net_wireless(PROC_TEXT_WEAKER, at=1.0)[0]

    lenient = RssiQualityMapping(excellent_dbm=-45.0, floor_dbm=-85.0).quality(reading)
    strict = RssiQualityMapping(excellent_dbm=-40.0, floor_dbm=-55.0).quality(reading)

    assert lenient > strict


def test_an_inverted_mapping_is_refused_at_construction():
    with pytest.raises(ValueError):
        RssiQualityMapping(excellent_dbm=-90.0, floor_dbm=-45.0)


def test_a_reading_that_failed_has_no_quality_at_all():
    """AI-N-03: 못 잰 것을 0으로 채우면 '측정 불가'와 '단절'을 구분할 수 없다."""
    failed = RssiReading(peer_id=None, source=SOURCE_PROC_NET_WIRELESS, at=1.0,
                         reason=REASON_SOURCE_UNAVAILABLE)

    assert DEFAULT_MAPPING.quality(failed) is None
    assert failed.measured is False


# --- provider -----------------------------------------------------------------


def test_the_provider_turns_a_real_capture_into_one_normalised_sample():
    provider = RssiLinkQualityProvider(
        wireless_reader=reader(PROC_TEXT),
        scan_reader=reader(NM_TEXT),
        peer_zones={BSSID_A: "zone-a"},
        clock=lambda: 7.0,
    )

    sample = provider.sample()

    assert isinstance(sample, LinkSample)
    assert sample.at == 7.0
    assert sample.peer_id == BSSID_A            # 어느 AP인지 스캔이 알려 준다
    assert sample.zone_id == "zone-a"
    assert 0.0 < sample.quality <= 1.0
    assert provider.last_reason is None


def test_an_unreadable_source_yields_no_sample_and_a_reason():
    provider = RssiLinkQualityProvider(wireless_reader=failing_reader())

    assert provider.sample() is None
    assert provider.last_reason == REASON_SOURCE_UNAVAILABLE


def test_a_missing_interface_is_distinguished_from_a_missing_source():
    provider = RssiLinkQualityProvider(
        wireless_reader=reader(PROC_TEXT), interface="wlan9"
    )

    assert provider.sample() is None
    assert provider.last_reason == REASON_INTERFACE_NOT_FOUND


def test_without_a_scan_the_provider_still_reports_strength_but_no_peer():
    """AI-C-05: 선택 정보(스캔)가 없다고 필수 측정까지 포기하지 않는다."""
    provider = RssiLinkQualityProvider(wireless_reader=reader(PROC_TEXT))

    sample = provider.sample()

    assert sample is not None and sample.quality > 0
    assert sample.peer_id is None and sample.zone_id is None


def test_candidates_and_peer_observations_agree_with_each_other():
    provider = RssiLinkQualityProvider(
        wireless_reader=reader(PROC_TEXT),
        scan_reader=reader(NM_TEXT_TWO_APS),
        peer_zones={BSSID_A: "zone-a", BSSID_B: "zone-b"},
    )

    candidates = dict(provider.candidates())
    observations = {o.peer_id: o for o in provider.peer_observations()}

    assert set(candidates) == {BSSID_A, BSSID_B}
    assert candidates[BSSID_A] == pytest.approx(observations[BSSID_A].quality)
    assert observations[BSSID_B].zone_id == "zone-b"


def test_an_unknown_bssid_keeps_a_null_zone_so_the_policy_will_not_move_there():
    provider = RssiLinkQualityProvider(
        wireless_reader=reader(PROC_TEXT),
        scan_reader=reader(NM_TEXT_TWO_APS),
        peer_zones={BSSID_A: "zone-a"},
    )
    policy = ZoneHandoverPolicy()
    policy.confirm_zone("zone-a", at=0.0)

    sample = provider.sample()
    for index in range(policy.zone_hold_samples + 2):
        decision = policy.observe(
            LinkSample(index * 1.0, sample.quality, sample.peer_id, "zone-a"),
            list(provider.peer_observations()),
        )

    assert decision.switch_to_zone is None


def test_a_dead_reader_feeds_the_policy_unknowns_rather_than_zeros():
    """provider가 못 재면 정책은 '모른다'를 세고, 견디다 못하면 로컬로 내린다."""
    provider = RssiLinkQualityProvider(wireless_reader=failing_reader())
    policy = ZoneHandoverPolicy(unknown_tolerance=2)
    policy.confirm_zone("zone-a", at=0.0)
    policy.observe(LinkSample(0.0, 0.9, "a1", "zone-a"), [])

    decisions = []
    for index in range(2):
        sample = provider.sample()
        assert sample is None
        decisions.append(policy.observe_unknown(10.0 + index, provider.last_reason))

    assert decisions[-1].posture is LinkPosture.LOCAL_ONLY
    assert REASON_SOURCE_UNAVAILABLE in decisions[-1].zone_reason


# --- 읽기 경로 -----------------------------------------------------------------


def test_a_local_file_reader_answers_none_instead_of_raising(tmp_path):
    assert local_text_reader(tmp_path / "nope")() is None

    path = tmp_path / "wireless"
    path.write_text(PROC_TEXT)
    assert local_text_reader(path)() == PROC_TEXT


class _Runner:
    """`run(command)`만 있으면 된다 — ssh인지 지역 셸인지 알 필요가 없다(AI-C-04)."""

    def __init__(self, stdout="", returncode=0, raises=False):
        self.stdout = stdout
        self.returncode = returncode
        self.raises = raises
        self.commands: list[str] = []

    def run(self, command, **_kwargs):
        if self.raises:
            raise OSError("link down")
        self.commands.append(command)
        return subprocess.CompletedProcess([], self.returncode, self.stdout, "")


def test_a_runner_reader_passes_the_command_through_and_returns_stdout():
    runner = _Runner(stdout=PROC_TEXT)

    text = runner_text_reader(runner, "cat /proc/net/wireless")()

    assert text == PROC_TEXT
    assert runner.commands == ["cat /proc/net/wireless"]


def test_a_runner_that_fails_or_raises_reports_unknown_not_bad():
    assert runner_text_reader(_Runner(returncode=1), "x")() is None
    assert runner_text_reader(_Runner(raises=True), "x")() is None


def test_the_provider_works_the_same_over_a_runner_as_over_a_local_file():
    """같은 코드가 말단 안에서도, 원격 제어 경로 너머에서도 쓰인다."""
    runner = _Runner(stdout=PROC_TEXT)
    provider = RssiLinkQualityProvider(
        wireless_reader=runner_text_reader(runner, "cat /proc/net/wireless")
    )
    local = RssiLinkQualityProvider(wireless_reader=reader(PROC_TEXT))

    assert provider.sample().quality == local.sample().quality


# --- 실기기, 옵트인 -------------------------------------------------------------
#
# `PF_LINK_TEST_DEVICE=pi6 pytest tests/test_rssi_link_quality.py -q`
# `~/.ssh/config`에 별칭이 있고 키가 설치돼 있어야 한다. sudo는 쓰지 않는다.

REAL_DEVICE = os.environ.get("PF_LINK_TEST_DEVICE")
needs_device = pytest.mark.skipif(
    not REAL_DEVICE,
    reason="set PF_LINK_TEST_DEVICE=<ssh alias> to read signal strength off real hardware",
)


class _SshRunner:
    def __init__(self, host: str, timeout: float = 20.0) -> None:
        self.host = host
        self.timeout = timeout

    def run(self, command, **_kwargs):
        return subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", self.host, command],
            capture_output=True, text=True, timeout=self.timeout,
        )


@needs_device
def test_real_device_signal_strength_drives_the_provider():
    runner = _SshRunner(REAL_DEVICE)
    provider = RssiLinkQualityProvider(
        wireless_reader=runner_text_reader(runner, "cat /proc/net/wireless"),
        scan_reader=runner_text_reader(
            runner, "nmcli -t -f IN-USE,SSID,BSSID,SIGNAL,FREQ dev wifi list"
        ),
    )

    reading = provider.read()
    sample = provider.sample()

    assert reading is not None and reading.measured, f"no signal read: {provider.last_reason}"
    assert -100.0 < reading.level_dbm < 0.0        # 실제 dBm 범위
    assert sample is not None and 0.0 <= sample.quality <= 1.0
    assert reading.peer_id is not None              # 붙어 있는 AP를 식별했다


@needs_device
def test_real_device_samples_feed_the_zone_policy_without_any_fabrication():
    """연속으로 실제 값을 읽어 정책을 돌린다. 못 읽은 회차는 unknown으로 센다."""
    runner = _SshRunner(REAL_DEVICE)
    provider = RssiLinkQualityProvider(
        wireless_reader=runner_text_reader(runner, "cat /proc/net/wireless"),
        scan_reader=runner_text_reader(
            runner, "nmcli -t -f IN-USE,SSID,BSSID,SIGNAL,FREQ dev wifi list"
        ),
        peer_zones={},
    )
    policy = ZoneHandoverPolicy()
    qualities = []

    for _ in range(5):
        sample = provider.sample()
        if sample is None:
            policy.observe_unknown(0.0, provider.last_reason)
            continue
        qualities.append(sample.quality)
        policy.observe(sample, list(provider.peer_observations()))

    assert qualities, "no usable sample from the device"
    # 구역을 선언한 적이 없으므로 구역 전환은 일어나지 않는다.
    assert policy.zone_id is None
    assert policy.zone_changes == 0
