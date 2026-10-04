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


def plugin_former(rc, range_axis, positions, wavelength_m, grid, **ctx):  # noqa: ANN001, ANN003, ANN201
    """시험용 '팀 영상 코드' — 내장 백프로젝션을 그대로 부르고 받은 문맥을 적어 둔다."""
    from sar_image.backprojection import backproject

    plugin_former.seen = sorted(ctx)
    return backproject(rc, range_axis, positions, wavelength_m, grid)


def plugin_focuser(rc, range_axis, positions, wavelength_m, reflectors, **ctx):  # noqa: ANN001, ANN003, ANN201
    return {"method": "team-af", "iterations": 3}


def test_team_code_plugs_in(tmp_path):
    from sar_image.pipeline import form_pass

    csv = DATA / "pass02_1790957682.csv"
    meta = json.loads(csv.with_suffix(".json").read_text(encoding="utf-8"))
    traj = Trajectory.load_csv(csv)
    o, hd, length, h = frame(traj, meta)
    r = math.radians(hd)
    la, lo = o.latlon(40 * math.sin(r) + 20 * math.cos(r), 40 * math.cos(r) - 20 * math.sin(r))
    radar = replace(RadarConfig.load(RADAR), prf_hz=100.0)
    raw = tmp_path / "raw.npz"
    write_fmcw_npz(raw, radar, traj, o, [o.enu(la, lo, o.h)], meta)
    b = form_pass(csv, [raw], radar, ADAPTER, tmp_path / "out", reflectors=[(la, lo, None)], full=False,
                  former="test_sar_imaging_flow:plugin_former", focuser="test_sar_imaging_flow:plugin_focuser")
    assert b["state"] == "done" and b["reflectors"][0]["found"]
    assert b["autofocus"] == {"method": "team-af", "reflectors": 1, "iterations": 3}
    assert {"t", "radar", "traj", "origin", "heading_deg", "workers"} <= set(plugin_former.seen)


def test_sdr_iq_gated_and_stream_with_drops(tmp_path):
    """Zynq-7020 + AD9361 SDR(5.8 GHz · 50 MHz) 제안 형식 — 정합 필터로 리플렉터가 제자리에 찍히고,
    연속 스트림에서 표본이 빠져도 `dropped` 를 적으면 시각이 맞는다(안 적으면 밀린다)."""
    import numpy as np

    from sar_image import sdr
    from sar_image.pipeline import form_pass

    csv = DATA / "pass02_1790957682.csv"
    meta = json.loads(csv.with_suffix(".json").read_text(encoding="utf-8"))
    traj = Trajectory.load_csv(csv)
    o, hd, length, h = frame(traj, meta)
    r = math.radians(hd)
    pts = [(35, 18), (50, 24)]
    ll = [o.latlon(a * math.sin(r) + c * math.cos(r), a * math.cos(r) - c * math.sin(r)) for a, c in pts]
    crs = [o.enu(la, lo, o.h) for la, lo in ll]
    radar = RadarConfig.load(RADAR.with_name("example_radar_sdr.json"))
    sdr.write_fake(tmp_path / "g.npy", radar, traj, o, crs, meta)
    b = form_pass(csv, [tmp_path / "g.npy"], radar, "sar_image.sdr:iq_npy", tmp_path / "g", reflectors=[(la, lo, None) for la, lo in ll],
                  full=False, autofocus=False)
    assert all(x["found"] and x["offset_m"] < 0.1 for x in b["reflectors"])

    # 연속 스트림 — 낮은 표본화로 작게, 가운데 400 펄스만, 중간에 표본 1234 개가 빠졌다
    small = replace(radar, bandwidth_hz=4e6)
    info = sdr.write_fake(tmp_path / "s.npy", small, traj, o, crs[:1], meta, fs=5e6, layout="stream", max_pulses=400, drop=(5_000_000, 1234))
    t, rng, rc = sdr.iq_npy(str(tmp_path / "s.npy"), small)
    assert t.size == info["pulses"] - 1                                  # 빠진 곳에 걸린 펄스 하나만 버렸다
    m = json.loads((tmp_path / "s.json").read_text())
    m["stream"]["dropped"] = []                                          # 빠진 걸 안 적으면
    (tmp_path / "s.json").write_text(json.dumps(m))
    t_bad, _, rc_bad = sdr.iq_npy(str(tmp_path / "s.npy"), small)
    k = t.size - 10
    assert abs(t_bad[k] - t[k]) > 1e-4 or not np.allclose(rc_bad[k], rc[k])   # 그 뒤 시각이 어긋난다


def test_pi_reduces_sdr_raw_and_laptop_fetches_only_reduced(tmp_path):
    """Pi: SDR 원시(본체 .npy + 옆 파일 _idx.npy · .json)를 패스 뒤 거리 압축으로 줄여 둔다 → 노트북 미러는 줄인 것만 받아 영상을 만든다."""
    from sar_data.reduce import Reducer
    from sar_image import sdr

    fdir = tmp_path / "pi" / "flight_1790957600"
    fdir.mkdir(parents=True)
    for f in DATA.glob("pass02_1790957682.*"):
        shutil.copy(f, fdir / f.name)
    meta = json.loads((fdir / "pass02_1790957682.json").read_text(encoding="utf-8"))
    traj = Trajectory.load_csv(fdir / "pass02_1790957682.csv")
    o, hd, length, h = frame(traj, meta)
    r = math.radians(hd)
    la, lo = o.latlon(40 * math.sin(r) + 20 * math.cos(r), 40 * math.cos(r) - 20 * math.sin(r))
    radar = RadarConfig.load(RADAR.with_name("example_radar_sdr.json"))
    radar_json = tmp_path / "radar.json"
    radar.save(radar_json)
    raw_dir = tmp_path / "pi_radar"
    sdr.write_fake(raw_dir / "cap_0002.npy", radar, traj, o, [o.enu(la, lo, o.h)], meta)
    end = meta["pass"]["end_unix"]
    for f in raw_dir.iterdir():
        os.utime(f, (end + 3, end + 3))
    pi_store = Store(tmp_path / "pi", raw_dir)
    red = Reducer(pi_store, radar_json, "sar_image.sdr:iq_npy")
    assert red.once(now=end + 100) == 1 and red.once(now=end + 100) == 0          # 본체 하나만, 두 번은 안 한다
    p = pi_store.passes(fdir)[0]
    assert len(p["radar_files"]) == 3 and len(p["rc_files"]) == 1 and p["rc_bytes"] < p["radar_bytes"]
    pi_srv, pi_base = _serve(pi_store)
    lap_store = Store(tmp_path / "laptop", None)
    jobs = ImageJobs(lap_store, radar_json, "sar_image.sdr:iq_npy", full=False)
    (tmp_path / "laptop").mkdir()
    try:
        assert Mirror(pi_base, lap_store.flights).sync_once() == [("flight_1790957600", 2)]
        got = list((tmp_path / "laptop" / "flight_1790957600" / "radar").rglob("*"))
        assert [f.name for f in got if f.is_file()] == ["cap_0002.npy.rc.npz"]               # 원시는 안 왔다
        lap_srv, lap_base = _serve(lap_store, jobs)
        try:
            code, _ = _get(f"{lap_base}/api/flights/flight_1790957600/image?pass=2&cr={la:.9f},{lo:.9f}")
            assert code == 202
            for _ in range(600):
                st = json.loads(_get(f"{lap_base}/api/flights/flight_1790957600/images/pass02/image.json")[1])
                if st["state"] in ("done", "failed"):
                    break
                time.sleep(0.1)
            assert st["state"] == "done", st.get("error")
            assert st["reflectors"][0]["found"] and st["reflectors"][0]["offset_m"] < 0.1
        finally:
            lap_srv.shutdown()
    finally:
        pi_srv.shutdown()


def test_pi_laptop_server_chain(pi_side):
    """Pi → 노트북 미러 → 처리 서버 미러(영상). 서버는 노트북이 연 SSH 역터널로 노트북 데이터 서버를 본다 — 코드는 같은 미러다."""
    tmp, radar_json, raw_dir, (seen, other) = pi_side
    mj = tmp / "pi" / "flight_1790957600" / "pass02_1790957682.json"
    meta = json.loads(mj.read_text(encoding="utf-8"))
    meta["reflectors"] = [{"lat": seen[0], "lon": seen[1]}]          # 비행 때 화면이 보낸 리플렉터(정본)
    mj.write_text(json.dumps(meta), encoding="utf-8")
    pi_srv, pi_base = _serve(Store(tmp / "pi", raw_dir))
    (tmp / "laptop").mkdir()
    lap_store = Store(tmp / "laptop", None)
    lap_mirror = Mirror(pi_base, lap_store.flights)
    lap_srv, lap_base = _serve(lap_store, None, lap_mirror)
    (tmp / "server").mkdir()
    srv_store = Store(tmp / "server", None)
    jobs = ImageJobs(srv_store, radar_json, ADAPTER, full=False)
    srv_mirror = Mirror(lap_base, srv_store.flights, on_pass=lambda fid, n: jobs.request(fid, n))
    srv_srv, srv_base = _serve(srv_store, jobs, srv_mirror)
    try:
        assert lap_mirror.sync_once() == [("flight_1790957600", 2)]
        assert srv_mirror.sync_once() == [("flight_1790957600", 2)]
        assert srv_mirror.sync_once() == []
        for _ in range(600):
            st = json.loads(_get(f"{srv_base}/api/flights/flight_1790957600/images/pass02/image.json")[1])
            if st.get("state") in ("done", "failed"):
                break
            time.sleep(0.1)
        assert st["state"] == "done", st.get("error")
        assert any(r["found"] for r in st["reflectors"])           # 비행 때 보낸 리플렉터가 서버까지 따라왔다
    finally:
        for s in (pi_srv, lap_srv, srv_srv):
            s.shutdown()
