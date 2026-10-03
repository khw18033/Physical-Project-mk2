"""SAR 영상 도구 — PX4 SITL 로 실제 날린 패스 궤적(tests/data)으로 시험한다."""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from sar_image.__main__ import frame_for, load_pass, main
from sar_image.attitude import frd_to_enu, lever_arm, tilt_motion_mm
from sar_image.autofocus import apply_correction, estimate_phase_error, estimate_trajectory_error
from sar_image.backprojection import backproject, line_grid, peak_metrics
from sar_image.coverage import line_coverage, predicted_history, summarize_history, swath_ground_ranges
from sar_image.radar import RadarConfig
from sar_image.simulate import synthesize

DATA = Path(__file__).parent / "data" / "pass02_1790957682.csv"
RADAR = Path(__file__).parent.parent / "sar_image" / "example_radar.json"


@pytest.fixture(scope="module")
def setup():
    radar = replace(RadarConfig.load(RADAR), prf_hz=100.0)    # 시험은 가볍게 (4 m/s 에 4 cm 간격)
    traj, meta = load_pass(DATA)
    # SIH 시뮬레이터는 공기저항이 커서 4 m/s 등속에 피치가 −22° 다(실기체 X500 은 수 도). 기체 고정 안테나는 그만큼
    # 빔이 뒤로 15° 틀어져 리플렉터가 빔 끝에 걸린다. 흔들림은 살리고 평균만 실기체 수준(−4°)으로 옮긴다.
    traj.pitch = traj.pitch - np.mean(traj.pitch[traj.capture]) - 4.0
    o, end, heading, length, h = frame_for(traj, meta)
    hd = math.radians(heading)
    ue, un = math.sin(hd), math.cos(hd)
    P = lambda a, c, u=0.0: np.array([a * ue + c * un, a * un - c * ue, u])  # noqa: E731
    return radar, traj, meta, o, end, heading, length, h, P


def test_plan_coverage_and_swath(setup):
    radar, traj, meta, o, end, heading, length, h, P = setup
    near, far = swath_ground_ranges(radar, h)
    assert near == pytest.approx(h / math.tan(math.radians(65)), rel=1e-6)
    assert far == pytest.approx(h / math.tan(math.radians(25)), rel=1e-6)
    ok = line_coverage(radar, (0, 0), end, h, tuple(P(40, 20)))
    assert ok.ok and ok.aperture_fraction == pytest.approx(1.0)
    left = line_coverage(radar, (0, 0), end, h, tuple(P(40, -20)))
    assert left.ok is False and "반대쪽" in left.why[0]
    too_far = line_coverage(radar, (0, 0), end, h, tuple(P(40, 60)))
    assert too_far.ok is False
    edge = line_coverage(radar, (0, 0), end, h, tuple(P(2, 20)))
    assert edge.ok is False and edge.aperture_fraction < 0.7


def test_flown_history_matches_plan(setup):
    radar, traj, meta, o, end, heading, length, h, P = setup
    s = summarize_history(predicted_history(radar, traj, o, P(40, 20)))
    assert s["seen"] and s["closest_range_m"] == pytest.approx(math.hypot(20, h), abs=0.6)
    ap = 2 * s["closest_range_m"] * math.tan(math.radians(15))
    assert s["in_beam_seconds"] == pytest.approx(ap / 4.0, rel=0.15)      # 안테나 면에서 잰 개구 / 속도


def _image(radar, rc, rng, pos, heading, center, half=0.4):
    along = np.arange(center[0] - half, center[0] + half, 0.004)
    cross = np.arange(center[1] - 0.5, center[1] + 0.5, 0.025)
    g, _ = line_grid((0.0, 0.0), heading, along, cross, 0.0)
    return backproject(rc, rng, pos, radar.wavelength_m, g), along, cross


def test_backprojection_focuses_at_reflector(setup):
    radar, traj, meta, o, end, heading, length, h, P = setup
    rng = np.arange(5, 60, 0.05)
    t, pos, rc = synthesize(radar, traj, o, [P(40, 20)], rng, noise=0.02)
    img, along, cross = _image(radar, rc, rng, pos, heading, (40, 20))
    m = peak_metrics(img, along, cross)
    assert abs(m["peak_along_m"] - 40) < 0.01 and abs(m["peak_cross_m"] - 20) < 0.03
    theory = radar.wavelength_m * math.hypot(20, h) / (2 * 2 * math.hypot(20, h) * math.tan(math.radians(15)))
    assert m["res_along_m"] < 1.5 * theory


def test_rtk_error_defocuses_and_reflector_autofocus_recovers(setup):
    radar, traj, meta, o, end, heading, length, h, P = setup
    rng = np.arange(5, 60, 0.05)
    t, pos, rc = synthesize(radar, traj, o, [P(40, 20), P(46, 24)], rng, noise=0.02)
    gen = np.random.default_rng(1)
    a = math.exp(-0.01 / 2.0)
    err = np.zeros_like(pos)
    w = gen.standard_normal(pos.shape) * 0.02 * math.sqrt(1 - a * a)
    for i in range(1, len(t)):
        err[i] = a * err[i - 1] + w[i]
    ref = np.abs(_image(radar, rc, rng, pos, heading, (40, 20))[0]).max()
    blur = np.abs(_image(radar, rc, rng, pos + err, heading, (40, 20))[0]).max()
    fe = estimate_phase_error(rc, rng, pos + err, radar.wavelength_m, P(40, 20))
    fixed_img, along, cross = _image(radar, apply_correction(rc, fe["phase_err"]), rng, pos + err, heading, (40, 20))
    loss_blur = 20 * math.log10(blur / ref)
    loss_fixed = 20 * math.log10(np.abs(fixed_img).max() / ref)
    assert loss_blur < -6                        # RTK 수준 오차로는 크게 흐려진다
    assert loss_fixed > -3                       # 리플렉터 자동 초점으로 회복
    m = peak_metrics(fixed_img, along, cross)
    assert abs(m["peak_along_m"] - 40) < 0.01
    # 리플렉터 하나로 잰 오차는 그 리플렉터가 빔 안에 있던 펄스에서만 맞다 — 6 m 떨어진 표적은 덜 회복된다
    other_ref = np.abs(_image(radar, rc, rng, pos, heading, (46, 24))[0]).max()
    one = np.abs(_image(radar, apply_correction(rc, fe["phase_err"]), rng, pos + err, heading, (46, 24))[0]).max()
    # 리플렉터 4개가 동시에 보이는 펄스에서는 궤적 오차를 3차원으로 풀어, 다른 표적의 시선 방향 오차도 λ/8 아래로 준다
    crs = [P(42, 18), P(45, 26), P(49, 17), P(51, 24)]
    tgt = P(46, 22)
    t2, pos2, rc2 = synthesize(radar, traj, o, crs + [tgt], rng, noise=0.02)
    te = estimate_trajectory_error(rc2, rng, pos2 + err, radar.wavelength_m, crs)
    J = te["solved"]
    ut = (pos2 + err - tgt) / np.linalg.norm(pos2 + err - tgt, axis=1)[:, None]
    true = (err * ut).sum(1)[J]
    est = (te["pos_err"] * ut).sum(1)[J]
    resid = (true - true.mean()) - (est - est.mean())
    assert J.sum() > 100
    assert np.sqrt(np.mean(resid ** 2)) < radar.wavelength_m / 8          # 2 cm 오차가 λ/8(3.9 mm) 아래로
    assert np.std(true) > 3 * radar.wavelength_m / 8                      # 보정 전에는 훨씬 컸다
    with pytest.raises(ValueError):
        estimate_trajectory_error(rc2, rng, pos2 + err, radar.wavelength_m, crs[:3])   # 3개로는 안 된다(상수가 안 풀린다)


def test_cli_coverage_and_predict(tmp_path, capsys):
    out = tmp_path / "r.csv"
    assert main(["coverage", "--traj", str(DATA), "--radar", str(RADAR), "--cr", "37.56649789,126.97838609"]) == 0
    assert "✓ 보인다" in capsys.readouterr().out
    assert main(["predict", "--traj", str(DATA), "--radar", str(RADAR), "--cr", "37.56649789,126.97838609", "--out", str(out)]) == 0
    lines = out.read_text().splitlines()
    assert lines[0].startswith("t_fc_gps,range_m") and len(lines) > 500


def test_attitude_rotation_conventions():
    # 앞(FRD x)은 yaw 방향, 오른쪽 아래로 단 안테나는 롤 + 에 더 아래로, 앞 숙임(피치 −)에 뒤로 간다
    assert np.allclose(frd_to_enu([1, 0, 0], 90, 0, 0), [1, 0, 0], atol=1e-12)            # yaw 90 = 동쪽
    assert np.allclose(frd_to_enu([0, 0, 1], 0, 0, 0), [0, 0, -1], atol=1e-12)            # 아래 = −u
    r = frd_to_enu([0, 0, 0.2], 0, 0, 2.0)                                                 # 0.2 m 아래, 롤 2°
    assert r[0] == pytest.approx(-0.2 * math.sin(math.radians(2)), abs=1e-9)               # 7 mm 왼쪽(서)으로
    p = frd_to_enu([0, 0, 0.2], 0, -10.0, 0)
    assert p[1] == pytest.approx(-0.2 * math.sin(math.radians(10)), abs=1e-9)              # 숙이면 아래 점이 뒤로


def test_lever_arm_reference_point():
    radar = replace(RadarConfig(), antenna_offset_m=[0.05, 0.10, 0.25], gnss_offset_m=[0.0, 0.0, -0.15])
    lev, notes = lever_arm(radar, {"ekf2_gps_pos": [0.0, 0.0, 0.0]})          # PX4 기본 → 보고 위치 = GPS 안테나
    assert np.allclose(lev, [0.05, 0.10, 0.40]) and not notes
    lev, notes = lever_arm(radar, {"ekf2_gps_pos": [0.0, 0.0, -0.15]})        # 넣었으면 → 보고 위치 = FC
    assert np.allclose(lev, [0.05, 0.10, 0.25]) and not notes
    _, notes = lever_arm(radar, {"ekf2_gps_pos": [0.0, 0.0, -0.30]})          # 둘이 다르면 알린다
    assert notes and "다르다" in notes[0]
    _, notes = lever_arm(replace(radar, gnss_offset_m=None), {})               # 모르는 값은 모른다고
    assert any("EKF2_GPS_POS" in n for n in notes) and any("gnss_offset_m" in n for n in notes)


def test_lever_arm_correction_restores_focus(setup):
    """안테나가 GPS 안테나보다 0.4 m 아래 · 0.1 m 오른쪽. SITL 궤적의 실제 롤 흔들림(±3°)으로 신호를 만든다."""
    radar, traj, meta, o, end, heading, length, h, P = setup
    rng = np.arange(5, 60, 0.05)
    lever = np.array([0.0, 0.1, 0.4])
    t, ant, rc = synthesize(radar, traj, o, [P(40, 20)], rng, noise=0.02, lever_frd=lever)
    st = traj.at(o, t)
    gps = np.stack([st["e"], st["n"], st["u"]], axis=1)
    from sar_image.attitude import phase_center
    fixed = phase_center(gps, st["yaw"], st["pitch"], st["roll"], lever)
    assert np.abs(fixed - ant).max() < 1e-9
    ref = np.abs(_image(radar, rc, rng, ant, heading, (40, 20))[0]).max()
    # 고정 성분(평균)만 빼 주는 어설픈 보정 — 흔들림은 그대로 남는다
    mean_only = gps + (ant - gps).mean(axis=0)
    loss_mean = 20 * math.log10(np.abs(_image(radar, rc, rng, mean_only, heading, (40, 20))[0]).max() / ref)
    loss_fixed = 20 * math.log10(np.abs(_image(radar, rc, rng, fixed, heading, (40, 20))[0]).max() / ref)
    assert tilt_motion_mm(lever, st["roll"], st["pitch"]) > 4.0                # λ/8 보다 크게 흔들린다
    assert loss_mean < -1.0                                                   # 자세를 안 쓰면 흐려진다
    assert loss_fixed > -0.01                                                 # 자세로 돌리면 그대로
