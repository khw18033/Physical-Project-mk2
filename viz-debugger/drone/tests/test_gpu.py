"""GPU 백프로젝션 · 엔트로피 자동 초점 · 자동 초점 견주기. torch(CUDA) 가 없으면 GPU 시험은 건너뛴다."""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest

from sar_image.af_compare import perturb, run
from sar_image.backprojection import backproject_fast, line_grid
from sar_image.cansar import load_info, write_fake_flight
from sar_image.pipeline import frame
from sar_image.radar import RadarConfig
from sar_image.trajectory import Trajectory

DATA = Path(__file__).parent / "data"
RADAR = Path(__file__).parent.parent / "sar_image" / "example_radar_cansar.json"
try:
    import torch as _t
    CUDA = _t.cuda.is_available()
except ImportError:
    _t, CUDA = None, False


@pytest.fixture(scope="module")
def blurred(tmp_path_factory):
    """RTK 기록과 실제 궤적이 사인파로 3 cm 옆 · 2 cm 위 어긋난 가짜 CANSAR 비행(가운데 10 s)."""
    tmp = tmp_path_factory.mktemp("gpu")
    fl = tmp / "flight_1790957600"
    fl.mkdir()
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

    crs = [enu(a, radar.side_sign * c) for a, c in ((30, 16), (40, 20), (50, 18), (45, 24))]
    t0, t1 = traj.capture_window()
    info = write_fake_flight(tmp / "pi", 163150, radar, perturb(traj, o, hd, 0.03, 0.02, 8.0), o, crs, meta)
    return {"csv": csvp, "iq": Path(info["iq"]), "radar": radar, "tmp": tmp, "lla": [(*o.latlon(p[0], p[1]), None) for p in crs]}


@pytest.mark.skipif(not CUDA, reason="CUDA 없음")
def test_gpu_backprojection_matches_cpu(blurred):
    from sar_image.gpu import backproject_gpu
    o = load_info(blurred["iq"], blurred["radar"])
    rc, rng = o["rc"][:300], o["range"]
    pos = np.stack([np.linspace(0, 6, 300), np.zeros(300), np.full(300, 20.0)], 1)
    g, _ = line_grid((0, 0), 90.0, np.arange(-5, 10, 0.05), np.arange(-30, -10, 0.1))
    a = backproject_fast(rc, rng, pos, 0.0545, g)
    b = backproject_gpu(rc, rng, pos, 0.0545, g)
    assert 20 * np.log10(np.abs(a - b).max() / np.abs(a).max()) < -60


def test_af_compare_table_without_gpu(blurred):
    """리플렉터 자동 초점은 3차원(4개 동시)이 짧게만 풀리면 이어 붙이기로 내려가고, 초점 없음보다 낫다."""
    res = run(blurred["csv"], [blurred["iq"]], blurred["radar"], "sar_image.cansar:load", blurred["lla"],
              blurred["tmp"] / "cmp", methods=("none", "reflector"))
    m = res["median"]
    assert res["runs"]["reflector"]["autofocus"]["method"] == "stitched"
    assert m["reflector"]["offset_m"] < m["none"]["offset_m"]
    assert (blurred["tmp"] / "cmp" / "af_compare.md").is_file() and (blurred["tmp"] / "cmp" / "af_compare.csv").is_file()


@pytest.mark.skipif(not CUDA, reason="CUDA 없음")
def test_entropy_autofocus_without_reflectors(blurred):
    """엔트로피 자동 초점(레이더 팀 방식)은 리플렉터 좌표 없이 영상만 보고 PSLR · 위치를 낫게 한다."""
    res = run(blurred["csv"], [blurred["iq"]], blurred["radar"], "sar_image.cansar:load", blurred["lla"],
              blurred["tmp"] / "cmp2", methods=("none", "entropy"), former="sar_image.gpu:backproject_gpu",
              focuser_kw={"iters": 60})
    m, af = res["median"], res["runs"]["entropy"]["autofocus"]
    assert af["method"] == "entropy_knots" and af["entropy_after"] < af["entropy_before"]
    assert m["entropy"]["pslr_db"] < m["none"]["pslr_db"] - 5
