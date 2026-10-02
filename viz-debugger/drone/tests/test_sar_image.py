"""SAR 영상 도구 — PX4 SITL 로 실제 날린 패스 궤적(tests/data)으로 시험한다."""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from sar_image.__main__ import frame_for, load_pass, main
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
