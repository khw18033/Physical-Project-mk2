"""반복 패스 리플렉터 변위 — 두 번째 패스에서 CR2 를 레이더 쪽으로 3 mm 옮기면 3 mm 로 잰다(5.8 GHz)."""

from __future__ import annotations

import json
import math
import shutil
from dataclasses import replace
from pathlib import Path

import numpy as np

from sar_image.displacement import measure
from sar_image.fakeraw import write_fmcw_npz
from sar_image.pipeline import form_pass, frame
from sar_image.radar import RadarConfig
from sar_image.trajectory import Trajectory

DATA = Path(__file__).parent / "data"
RADAR = Path(__file__).parent.parent / "sar_image" / "example_radar_sdr.json"
ADAPTER = "sar_image.adapters:fmcw_dechirped_npz"


def _two_passes(tmp_path, move_mm: float, af_exclude, rtk_bias_m=(0.0, 0.0, 0.0)):
    """CR1~CR5 를 장면에 흩어 둔다. 두 번째 패스는 CR2 를 레이더 쪽으로 move_mm, 실제 궤적이 rtk_bias_m(e, n, u)만큼
    기록과 어긋난다(RTK 오차 — 기록된 궤적은 그대로)."""
    fdir = tmp_path / "flight"
    fdir.mkdir()
    for f in DATA.glob("pass02_1790957682.*"):
        shutil.copy(f, fdir / f.name)
    csv = fdir / "pass02_1790957682.csv"
    meta = json.loads(csv.with_suffix(".json").read_text(encoding="utf-8"))
    traj = Trajectory.load_csv(csv)
    o, hd, length, h = frame(traj, meta)
    r = math.radians(hd)

    def enu(a, c):
        return np.array([a * math.sin(r) + c * math.cos(r), a * math.cos(r) - c * math.sin(r), 0.0])

    radar = replace(RadarConfig.load(RADAR), prf_hz=100.0, antenna_offset_m=[0.0, 0.0, 0.0])
    side = radar.side_sign
    crs = [enu(a, side * c) for a, c in ((30.0, 16.0), (40.0, 18.0), (50.0, 20.0), (40.0, 22.0), (35.0, 19.5))]
    lla = [(*o.latlon(p[0], p[1]), None) for p in crs]
    # 레이더 쪽 단위벡터(CR2 를 지날 때의 위상 중심 → CR2)
    t_mid = float(np.mean(traj.capture_window()))
    st = traj.at(o, np.array([t_mid]))
    here = np.array([st["e"][0], st["n"][0], st["u"][0]])
    a2 = 40.0
    here = enu(a2, 0.0) + np.array([0, 0, here[2]])
    u = (here - crs[1]) / np.linalg.norm(here - crs[1])
    moved = [p - np.array(rtk_bias_m) for p in crs]          # 궤적이 +b 어긋난 것 = 장면이 −b 어긋난 것
    moved[1] = moved[1] + u * move_mm / 1000.0
    out = {}
    for name, targets in (("a", crs), ("b", moved)):
        raw = write_fmcw_npz(tmp_path / f"raw_{name}.npz", radar, traj, o, targets, meta, noise=0.02, seed=7 if name == "a" else 8)
        out[name] = form_pass(csv, [Path(raw["file"])], radar, ADAPTER, tmp_path / f"img_{name}", reflectors=lla,
                              full=False, af_exclude=af_exclude, time_offset=None)
    return out["a"], out["b"]


def test_moved_reflector_measured_in_mm(tmp_path):
    ja, jb = _two_passes(tmp_path, 3.0, af_exclude=[2])
    assert all(r["found"] for r in ja["reflectors"]) and not ja["reflectors"][1]["af_used"]
    d = measure(ja, jb)
    by = {r["name"]: r for r in d["reflectors"]}
    assert d["method"] == "plane" and by["CR2"]["moved_flag"] and not by["CR2"]["reference"]
    assert abs(by["CR2"]["los_mm"] - 3.0) < 0.4, by          # 3 mm 를 0.4 mm 안으로
    assert all(abs(r["los_mm"]) < 0.3 for n, r in by.items() if n != "CR2")     # 안 움직인 것은 0
    assert d["ambiguity_mm"] > 12 and by["CR2"]["sigma_mm"] < 1.0 and d["stable_rms_mm"] < 0.3


def test_rtk_bias_between_passes_is_removed(tmp_path):
    """두 번째 패스의 실제 궤적이 1 cm 위 · 1 cm 옆으로 어긋나도(RTK 오차) 평면 맞추기로 지우고 3 mm 를 잰다."""
    ja, jb = _two_passes(tmp_path, 3.0, af_exclude=[2], rtk_bias_m=(0.01, 0.0, 0.01))
    raw = {r["name"]: r for r in measure(ja, jb, moved=["CR2"])["reflectors"]}
    d = measure(ja, jb)
    by = {r["name"]: r for r in d["reflectors"]}
    assert abs(by["CR2"]["los_mm"] - 3.0) < 0.5, (by, raw)
    assert d["stable_rms_mm"] < 0.5


def test_still_scene_reads_zero(tmp_path):
    ja, jb = _two_passes(tmp_path, 0.0, af_exclude=None)
    d = measure(ja, jb)
    assert all(abs(r["los_mm"]) < 0.4 for r in d["reflectors"]), d
