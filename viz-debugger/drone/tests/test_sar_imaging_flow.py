"""Pi 데이터 서버 → 노트북 미러 → 영상 만들기 → 화면이 받는 파일까지. 레이더는 예시 FMCW 가짜 원시 파일."""

from __future__ import annotations

import json
import math
import os
import shutil
import threading
import time
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path

import pytest

from sar_data.imaging import ImageJobs, parse_cr, read_reflectors_csv
from sar_data.mirror import Mirror
from sar_data.server import Store, make_handler
from sar_image.fakeraw import write_fmcw_npz
from sar_image.pipeline import frame
from sar_image.radar import RadarConfig
from sar_image.trajectory import Trajectory

DATA = Path(__file__).parent / "data"
RADAR = Path(__file__).parent.parent / "sar_image" / "example_radar.json"
ADAPTER = "sar_image.adapters:fmcw_dechirped_npz"


def _serve(store, jobs=None, mirror=None):
    from http.server import ThreadingHTTPServer

    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store, jobs, mirror))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _get(url):
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


@pytest.fixture()
def pi_side(tmp_path):
    """SITL 로 날린 패스 하나 + 그 패스 시각에 맞춘 가짜 레이더 원시(리플렉터 하나 · 반대쪽 하나는 신호 없음)."""
    fdir = tmp_path / "pi" / "flight_1790957600"
    fdir.mkdir(parents=True)
    for f in DATA.glob("pass02_1790957682.*"):
        shutil.copy(f, fdir / f.name)
    meta = json.loads((fdir / "pass02_1790957682.json").read_text(encoding="utf-8"))
    traj = Trajectory.load_csv(fdir / "pass02_1790957682.csv")
    o, hd, length, h = frame(traj, meta)
    r = math.radians(hd)

    def ll(a, c):
        return o.latlon(a * math.sin(r) + c * math.cos(r), a * math.cos(r) - c * math.sin(r))

    seen, other = ll(40, 20), ll(40, -20)
    radar = replace(RadarConfig.load(RADAR), prf_hz=100.0, antenna_offset_m=[0.0, 0.1, 0.25])
    radar_json = tmp_path / "radar.json"
    radar.save(radar_json)
    raw_dir = tmp_path / "pi_radar"
    info = write_fmcw_npz(raw_dir / "cansar_0002.npz", radar, traj, o, [o.enu(*seen, o.h)], meta)
    end = meta["pass"]["end_unix"]
    os.utime(info["file"], (end + 3, end + 3))
    return tmp_path, radar_json, raw_dir, [seen, other]


def test_cr_parsing(tmp_path):
    assert parse_cr("37.5,126.9;37.6,127.0,12") == [(37.5, 126.9, None), (37.6, 127.0, 12.0)]
    f = tmp_path / "reflectors.csv"
    f.write_text("name,lat,lon,ok\nCR1,37.56650000,126.97839000,true\n", encoding="utf-8")
    assert read_reflectors_csv(f) == [(37.5665, 126.97839, None)]


def test_no_imaging_config_says_what_is_missing(pi_side):
    tmp, radar_json, raw_dir, _ = pi_side
    store = Store(tmp / "pi", raw_dir)
    srv, base = _serve(store, ImageJobs(store, None, None))
    try:
        code, body = _get(f"{base}/api/flights/flight_1790957600/image?pass=2")
        assert code == 501 and len(json.loads(body)["missing"]) == 2
    finally:
        srv.shutdown()


def test_pi_to_laptop_mirror_and_image(pi_side):
    tmp, radar_json, raw_dir, (seen, other) = pi_side
    pi_store = Store(tmp / "pi", raw_dir)
    pi_srv, pi_base = _serve(pi_store)
    lap_store = Store(tmp / "laptop", None)
    jobs = ImageJobs(lap_store, radar_json, ADAPTER, full=False)
    mirror = Mirror(pi_base, lap_store.flights)
    lap_srv, lap_base = _serve(lap_store, jobs, mirror)
    try:
        # 1) 미러 — 끝난 패스를 받는다. 두 번째에는 받을 것이 없다
        (tmp / "laptop").mkdir()
        assert mirror.sync_once() == [("flight_1790957600", 2)]
        assert mirror.sync_once() == []
        fl = json.loads(_get(f"{lap_base}/api/flights")[1])
        p = fl[0]["passes"][0]
        assert p["radar_files"][0]["name"] == "radar/pass02/cansar_0002.npz" and p["image"] is None
        # 2) 영상 — 화면이 보낸 리플렉터 둘(하나는 신호 없음)
        cr = ";".join(f"{la:.9f},{lo:.9f}" for la, lo in (seen, other))
        code, body = _get(f"{lap_base}/api/flights/flight_1790957600/image?pass=2&cr={cr}")
        assert code == 202 and json.loads(body)["state"] == "queued"
        for _ in range(600):
            st = json.loads(_get(f"{lap_base}/api/flights/flight_1790957600/images/pass02/image.json")[1])
            if st["state"] in ("done", "failed"):
                break
            time.sleep(0.1)
        assert st["state"] == "done", st.get("error")
        found = {r["name"]: r for r in st["reflectors"]}
        assert found["CR1"]["found"] and found["CR1"]["offset_m"] < 0.05 and found["CR1"]["res_along_m"] < 0.03
        assert not found["CR2"]["found"]
        assert st["lever_frd_m"] == [0.0, 0.1, 0.25] and st["autofocus"]["method"] == "single_reflector"
        code, png = _get(f"{lap_base}/api/flights/flight_1790957600/images/pass02/cr1.png")
        assert code == 200 and png[:4] == b"\x89PNG"
        assert _get(f"{lap_base}/api/flights/flight_1790957600/images/pass02/..%2fradar_map.json")[0] == 404
        # 3) 목록에 영상 상태가 붙고, 묶음에 영상이 들어간다
        p = json.loads(_get(f"{lap_base}/api/flights")[1])[0]["passes"][0]
        assert p["image"] == {"state": "done", "error": None, "reflectors": 2, "found": 1, "full": False}
        import io
        import zipfile
        z = zipfile.ZipFile(io.BytesIO(_get(f"{lap_base}/api/flights/flight_1790957600/bundle.zip?pass=2")[1]))
        names = z.namelist()
        assert "radar/pass02/cansar_0002.npz" in names and "images/pass02/cr1.png" in names
        h = json.loads(_get(f"{lap_base}/api/health")[1])
        assert h["imaging"]["ready"] and h["mirror"]["fetched_passes"] == 1
    finally:
        pi_srv.shutdown()
        lap_srv.shutdown()


def test_time_offset_found_and_applied(tmp_path):
    """레이더 시계가 30 ms 늦게 찍혀도 리플렉터 둘로 dt 를 찾아 고친다. 안 고친 영상보다 리플렉터가 밝다."""
    import numpy as np

    from sar_image.pipeline import form_pass

    csv = DATA / "pass02_1790957682.csv"
    meta = json.loads(csv.with_suffix(".json").read_text(encoding="utf-8"))
    traj = Trajectory.load_csv(csv)
    o, hd, length, h = frame(traj, meta)
    r = math.radians(hd)
    ll = [o.latlon(a * math.sin(r) + c * math.cos(r), a * math.cos(r) - c * math.sin(r)) for a, c in ((35, 18), (50, 24))]
    radar = replace(RadarConfig.load(RADAR), prf_hz=100.0)
    raw = tmp_path / "raw.npz"
    write_fmcw_npz(raw, radar, traj, o, [o.enu(la, lo, o.h) for la, lo in ll], meta)
    z = dict(np.load(raw))
    z["t"] = z["t"] - 0.030                              # 레이더 시계가 30 ms 늦다 → 고칠 값은 +30 ms
    np.savez(raw, **z)
    crs = [(la, lo, None) for la, lo in ll]
    fixed = form_pass(csv, [raw], radar, ADAPTER, tmp_path / "auto", reflectors=crs, full=False, autofocus=False)
    off = fixed["quicklook"]["time_offset"]
    assert off["combined"]["consistent"] and abs(off["applied_s"] - 0.030) < 0.001
    assert (tmp_path / "auto" / "rangetime.png").stat().st_size > 1000
    raw_only = form_pass(csv, [raw], radar, ADAPTER, tmp_path / "off", reflectors=crs, full=False, autofocus=False, time_offset=None)
    for a, b in zip(fixed["reflectors"], raw_only["reflectors"]):
        assert a["found"] and a["contrast_db"] > b["contrast_db"] + 3
