"""레이더 팀 quick-look 을 패스마다 돌리고(Pi) → 노트북 미러가 받고 → 화면 API 로 나간다."""

from __future__ import annotations

import json
import math
import shutil
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np

from sar_data.mirror import Mirror
from sar_data.quick import QuickLooks, parse_stdout
from sar_data.server import Store, make_handler
from sar_image.cansar import write_fake
from sar_image.pipeline import frame
from sar_image.radar import RadarConfig
from sar_image.trajectory import Trajectory

DATA = Path(__file__).parent / "data"
TEAM = DATA / "cansar" / "cansar_quick.py"


def _serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _get(url):
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _fake(tmp):
    csvp = DATA / "pass02_1790957682.csv"
    meta = json.loads(csvp.with_suffix(".json").read_text(encoding="utf-8"))
    traj = Trajectory.load_csv(csvp)
    o, hd, _, _ = frame(traj, meta)
    r = math.radians(hd)
    radar = RadarConfig.load(Path(__file__).parent.parent / "sar_image" / "example_radar_cansar.json")
    tg = np.array([45 * math.sin(r) + 24 * math.cos(r), 45 * math.cos(r) - 24 * math.sin(r), 0.0])
    t0, t1 = traj.capture_window()
    return write_fake(tmp / "pi", 163150, radar, traj, o, [tg], meta, t_window=(t0 + 4, t1 - 4))


def test_parse_radar_team_stdout():
    out = parse_stdout("[판정] #163150  20.12 s  3.84 MB/s  위치 10 Hz  속도 4.0±0.05 m/s → OK\n"
                       "[시각] events start #0 (pi_epoch 차 0.370 s)\n[!] 스윕 시각 밖\n"
                       "영상 첨두 94.1 dB @ 진행 +4.1 m, 옆 +24.0 m  (배경 중앙값 -61.2 dB)\n")
    assert out["verdict"] == "OK" and out["peak"] == {"db": 94.1, "along_m": 4.1, "side_m": 24.0, "background_db": -61.2}
    assert out["time_match_s"] == 0.37 and len(out["warnings"]) == 1


def test_pi_runs_quicklook_laptop_mirrors_it(tmp_path):
    info = _fake(tmp_path)
    pi = tmp_path / "pi"
    cap = tmp_path / "CAP_ON"
    q = QuickLooks(tmp_path / "pi_flights" / "cansar_quick", TEAM, pi / "flight", pi / "cansar_logs", "right", cap,
                   python=sys.executable, settle_s=0.0)
    assert q.missing() == []
    assert q.scan() == [163150] and q.scan() == []                       # 줄 세우기는 한 번
    n, body = q.q.get_nowait()
    res = q.run_one(n, body)
    assert res["state"] == "done", (res.get("error"), (tmp_path / "pi_flights" / "cansar_quick" / "163150" / "log.txt").read_text()[-600:])
    assert res["verdict"] == "OK" and abs(res["peak"]["side_m"] - 24.0) < 1.0 and res["label"] == "quick-look"
    assert not (tmp_path / "pi_flights" / "cansar_quick" / "163150" / "work").exists()   # 작업 폴더는 치운다
    q._queued.clear()
    assert q.scan() == []                                                   # 끝난 것은 다시 안 돈다

    pi_srv, pi_base = _serve(make_handler(Store(tmp_path / "pi_flights", None), quick=q))
    (tmp_path / "laptop").mkdir()
    lap_q = QuickLooks(tmp_path / "laptop" / "cansar_quick")
    m = Mirror(pi_base, tmp_path / "laptop")
    lap_srv, lap_base = _serve(make_handler(Store(tmp_path / "laptop", None), mirror=m, quick=lap_q))
    try:
        assert m.sync_quick() == [163150] and m.sync_quick() == []
        code, body = _get(f"{lap_base}/api/cansar")
        lst = json.loads(body)
        assert code == 200 and lst["runner"] is False and lst["items"][0]["n"] == 163150
        code, png = _get(f"{lap_base}/api/cansar/163150/quick.png")
        assert code == 200 and png[:4] == b"\x89PNG"
        assert _get(f"{lap_base}/api/cansar/163150/run")[0] == 501          # 노트북은 돌리지 않는다
        assert _get(f"{lap_base}/api/cansar/163150/..%2fx")[0] == 404
    finally:
        pi_srv.shutdown()
        lap_srv.shutdown()


def test_relative_paths_work(tmp_path, monkeypatch):
    """경로를 상대로 줘도(서비스 설정에서 흔하다) 작업 폴더에서 찾는다."""
    _fake(tmp_path)
    monkeypatch.chdir(tmp_path)
    shutil.copy(TEAM, tmp_path / "cq.py")
    shutil.copy(TEAM.with_name("cansar_flight.py"), tmp_path / "cansar_flight.py")
    q = QuickLooks(Path("out"), Path("cq.py"), Path("pi/flight"), Path("pi/cansar_logs"), python=sys.executable, settle_s=0.0)
    assert q.scan() == [163150]
    res = q.run_one(*q.q.get_nowait())
    assert res["state"] == "done", res.get("error")


def test_waits_while_capturing(tmp_path):
    q = QuickLooks(tmp_path / "q", TEAM, tmp_path, tmp_path, cap_path=tmp_path / "CAP_ON")
    (tmp_path / "CAP_ON").write_text("1")
    body = {"n": 1}
    t = threading.Thread(target=q._wait_capture, args=(body, tmp_path / "r.json"))
    t.start()
    t.join(1.5)
    assert t.is_alive() and json.loads((tmp_path / "r.json").read_text())["state"] == "waiting_capture"
    (tmp_path / "CAP_ON").unlink()
    t.join(3)
    assert not t.is_alive()
