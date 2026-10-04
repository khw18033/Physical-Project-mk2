"""CANSAR-2(레이더 팀, 2026-10-04) 형식 — 가짜 비행을 그쪽 형식으로 만들어
① 그쪽 cansar_quick.py 가 그대로 돌고 ② 우리 어댑터 · 파이프라인이 리플렉터를 제자리에서 찾는지."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from sar_image.cansar import load_info, parse_sweeps, write_fake_flight
from sar_image.pipeline import form_pass, frame
from sar_image.radar import RadarConfig
from sar_image.trajectory import Trajectory

DATA = Path(__file__).parent / "data"
RADAR = Path(__file__).parent.parent / "sar_image" / "example_radar_cansar.json"
TEAM = DATA / "cansar"
PTS = [(30.0, 16.0), (40.0, 20.0), (50.0, 18.0), (45.0, 24.0)]       # (진행, 옆) m — CR4 가 가장 밝다(가장 멀고 빔 가운데)


@pytest.fixture(scope="module")
def flight(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("cansar")
    fl = tmp / "ours" / "flight_1790957600"
    fl.mkdir(parents=True)
    for f in DATA.glob("pass02_1790957682.*"):
        shutil.copy(f, fl / f.name)
    csvp = fl / "pass02_1790957682.csv"
    meta = json.loads(csvp.with_suffix(".json").read_text(encoding="utf-8"))
    traj = Trajectory.load_csv(csvp)
    o, hd, _, _ = frame(traj, meta)
    r = math.radians(hd)
    radar = RadarConfig.load(RADAR)

    def enu(a, c):
        return np.array([a * math.sin(r) + c * math.cos(r), a * math.cos(r) - c * math.sin(r), 0.0])

    crs = [enu(a, radar.side_sign * c) for a, c in PTS]
    info = write_fake_flight(tmp / "pi", 163150, radar, traj, o, crs, meta)
    return {"tmp": tmp, "csv": csvp, "radar": radar, "info": info, "lla": [(*o.latlon(p[0], p[1]), None) for p in crs]}


def test_adapter_reads_format_and_time(flight):
    out = load_info(flight["info"]["iq"], flight["radar"])
    i = out["info"]
    assert i["sweeps"] == flight["info"]["sweeps"] and i["dropped_markers"] <= 1          # 끝 표지 하나는 남는다
    assert abs(i["clock_offset_s"] - flight["info"]["offset_s"]) < 1e-3                  # events.csv 로 Pi 시각을 맞췄다
    assert out["rc"].shape == (i["sweeps"], out["range"].size)


def test_our_pipeline_finds_reflectors_in_place(flight):
    body = form_pass(flight["csv"], [Path(flight["info"]["iq"])], flight["radar"], "sar_image.cansar:load",
                     flight["tmp"] / "img", reflectors=flight["lla"], full=False)
    for rec in body["reflectors"]:
        assert rec["found"] and rec["offset_m"] < 0.05 and rec["res_along_m"] < 0.05, rec
    assert body["quicklook"]["time_offset"]["combined"]["consistent"]


def test_radar_team_quicklook_runs_on_same_files(flight, tmp_path):
    pi = flight["tmp"] / "pi"
    r = subprocess.run([sys.executable, str(TEAM / "cansar_quick.py"), "--nopull", "--data-dir", str(pi / "flight"),
                        "--logs-root", str(pi / "cansar_logs"), "--n", "163150", "--side", "right", "--noopen"],
                       cwd=tmp_path, capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "CUDA_VISIBLE_DEVICES": ""})                 # Pi 처럼 CPU 로
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-800:]
    assert (tmp_path / "quick_163150.png").is_file() and (tmp_path / "quick_163150.npz").is_file()
    m = re.search(r"영상 첨두 .* @ 진행 ([+-][\d.]+) m, 옆 ([+-][\d.]+) m", r.stdout)
    assert m and abs(float(m.group(2)) - 24.0) < 1.0                               # CR4 의 옆 거리
    assert "→ OK" in r.stdout


def test_missing_marker_is_counted(flight, tmp_path):
    src = Path(flight["info"]["iq"])
    d = np.fromfile(src, dtype=np.int16).reshape(-1, 4).copy()
    mk = np.flatnonzero(d[:, 0] == 0x5A5A)
    d[mk[100], 0] = 0                                                             # 표시 행 하나가 빠졌다
    bad = tmp_path / src.name
    d.tofile(bad)
    _, _, _, info = parse_sweeps(bad)
    assert info["sweeps"] == flight["info"]["sweeps"] - 1 and info["dropped_markers"] >= 7   # 망가진 스윕 하나만 버린다


def test_range_bias_tells_how_to_fix_roff(tmp_path):
    """실제 내부 지연 0.32 m 인데 어댑터는 0.40 m 를 빼면 → 레이더 거리가 8 cm 짧게 나온다고 알려 준다(roff 를 줄여라)."""
    from sar_image.cansar import write_fake_flight
    from sar_image.trajectory import Trajectory

    fl = tmp_path / "flight_1790957600"
    fl.mkdir()
    for f in DATA.glob("pass02_1790957682.*"):
        shutil.copy(f, fl / f.name)
    csvp = fl / "pass02_1790957682.csv"
    meta = json.loads(csvp.with_suffix(".json").read_text(encoding="utf-8"))
    traj = Trajectory.load_csv(csvp)
    o, hd, _, _ = frame(traj, meta)
    r = math.radians(hd)
    radar = RadarConfig.load(RADAR)
    crs = [np.array([a * math.sin(r) + c * radar.side_sign * math.cos(r), a * math.cos(r) - c * radar.side_sign * math.sin(r), 0.0])
           for a, c in ((35, 18), (45, 22))]
    t0, t1 = traj.capture_window()
    info = write_fake_flight(tmp_path / "pi", 163151, radar, traj, o, crs, meta, internal_delay_m=0.32, t_window=(t0 + 3, t1 - 3))
    body = form_pass(csvp, [Path(info["iq"])], radar, "sar_image.cansar:load", tmp_path / "img",
                     reflectors=[(*o.latlon(p[0], p[1]), None) for p in crs], full=False, autofocus=False)
    rb = body["quicklook"]["range_bias"]
    assert abs(rb["combined_m"] - (-0.08)) < 0.02, rb
    assert any("roff" in n and "줄인다" in n for n in body["notes"])


def test_store_matches_capture_by_its_own_time_not_mtime(tmp_path):
    """수정 시각이 같아도(복사가 한꺼번에 · 늦게) 캡처 구간(meta + events.csv)으로 그 패스의 것만 짝짓는다."""
    import os as _os

    from sar_data.server import Store
    from sar_image.cansar import capture_window, write_fake_flight

    fl = tmp_path / "flights" / "flight_1790957600"
    fl.mkdir(parents=True)
    for f in DATA.glob("pass02_1790957682.*"):
        shutil.copy(f, fl / f.name)
    csvp = fl / "pass02_1790957682.csv"
    meta = json.loads(csvp.with_suffix(".json").read_text(encoding="utf-8"))
    traj = Trajectory.load_csv(csvp)
    o, _, _, _ = frame(traj, meta)
    radar = RadarConfig.load(RADAR)
    t0, t1 = traj.capture_window()
    a = write_fake_flight(tmp_path / "pi", 163150, radar, traj, o, [], meta, t_window=(t0 + 2, t0 + 4))
    b = write_fake_flight(tmp_path / "pi", 163151, radar, traj, o, [], meta, t_window=(t1 + 60, t1 + 62))   # 다음 패스 것
    end = meta["pass"]["end_unix"]
    for f in (a["iq"], b["iq"]):
        _os.utime(f, (end + 3, end + 3))                                      # 둘 다 이 패스 끝 직후에 복사된 것처럼
    w = capture_window(a["iq"])
    assert w is not None and w["start"] < meta["pass"]["end_unix"]
    store = Store(tmp_path / "flights", tmp_path / "pi" / "flight", "iq_*.bin")
    names = [rf["name"] for rf in store.passes(fl)[0]["radar_files"]]
    assert names == ["iq_163150.bin"], names


def test_clock_rows_fit_offset_and_drift(flight, tmp_path):
    """1 초마다 clock 행이 있으면 start 행 대신 그것으로 — 오프셋이 start 행과 달라도(SSH 지연) 시계 행을 따르고, 흐름도 맞춘다."""
    import csv as _csv

    from sar_image.cansar import read_meta

    src = Path(flight["info"]["iq"])
    work = tmp_path / "pi"
    shutil.copytree(src.parent.parent, work)
    iq = work / "flight" / src.name
    meta = read_meta(iq.with_name("meta_163150.txt"))
    t0s, t1s = float(meta["t_start"]), float(meta["t_end"])
    ev = next((work / "cansar_logs").glob("*/events.csv"))
    rows = list(_csv.reader(ev.open(encoding="utf-8")))
    start_off = float(rows[1][1]) - float(rows[1][2])
    true_off, drift = start_off + 0.25, 40e-6                      # start 행은 SSH 지연으로 250 ms 틀렸다고 치자
    with ev.open("a", newline="", encoding="utf-8") as f:
        w = _csv.writer(f)
        for su in np.arange(t0s, t1s, 1.0):
            w.writerow(["clock", f"{su + true_off + drift * (su - t0s):.6f}", f"{su + 0.004:.2f}"])   # uptime 0.01 s 눈금
    out = load_info(iq, flight["radar"])
    i = out["info"]
    assert "clock" in i["clock_from"]
    base = load_info(src, flight["radar"])
    dt = out["t"] - base["t"]                                     # 시계 행을 쓴 시각 − start 행을 쓴 시각
    assert abs(dt[0] - 0.25) < 0.01 and abs((dt[-1] - dt[0]) - drift * (t1s - t0s)) < 0.002
