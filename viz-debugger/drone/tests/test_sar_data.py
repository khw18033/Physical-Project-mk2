"""데이터 서버 — 실제 임무가 남긴 비행 폴더 + 흉내 레이더 파일로 목록 · 파일 · ZIP 을 받아 본다."""

from __future__ import annotations

import asyncio
import io
import json
import os
import threading
import urllib.request
import zipfile

import pytest

from sar_data.server import serve
from test_quality import build


@pytest.fixture()
def flown(tmp_path):
    """시뮬레이터로 한 번 날려 진짜 비행 폴더를 만든다. 레이더 파일은 캡처 구간의 시각으로 찍는다."""
    plan, sim, cap, m, st = build(tmp_path, ack=False)
    assert asyncio.run(m.run()) == "done"
    flights = tmp_path / "traj"
    fdir = flights / f"flight_{int(m.records[0].start_unix)}"
    fdir.mkdir()
    for f in list(flights.iterdir()):
        if f.is_file():
            f.rename(fdir / f.name)
    radar = tmp_path / "radar"
    radar.mkdir()
    for r in m.records:
        f = radar / f"cap_{r.pass_no}.bin"
        f.write_bytes(os.urandom(2048))
        os.utime(f, (r.end_unix + 3, r.end_unix + 3))
    stray = radar / "old.bin"
    stray.write_bytes(b"x")
    os.utime(stray, (1, 1))
    return flights, radar, m


def get(url):
    with urllib.request.urlopen(url) as r:
        return r.status, dict(r.headers), r.read()


def test_list_files_and_bundles(flown):
    flights, radar, m = flown
    srv = serve(flights, radar, 0, "127.0.0.1")
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        _s, h, body = get(f"{base}/api/flights")
        assert h["Access-Control-Allow-Origin"] == "*"
        fl = json.loads(body)
        assert len(fl) == 1 and fl[0]["valid_passes"] == 2
        p1 = fl[0]["passes"][0]
        assert [x["name"] for x in p1["radar_files"]] == ["cap_1.bin"]          # 시각으로 짝지었다 · 엉뚱한 파일은 빠졌다
        _s, h, csvb = get(f"{base}/api/flights/{fl[0]['id']}/files/{p1['traj_csv']}")
        assert "attachment" in h["Content-Disposition"] and csvb.startswith(b"t_pi,t_fc")
        _s, _h, zb = get(f"{base}/api/flights/{fl[0]['id']}/bundle.zip?pass=1")
        names = zipfile.ZipFile(io.BytesIO(zb)).namelist()
        assert "manifest.json" in names and "radar/pass01/cap_1.bin" in names
        assert any(n.startswith("position/pass01_") and n.endswith(".csv") for n in names)
        assert not any("pass02_" in n for n in names)
        _s, _h, zb = get(f"{base}/api/flights/{fl[0]['id']}/bundle.zip?raw=0")
        names = zipfile.ZipFile(io.BytesIO(zb)).namelist()
        assert not any(n.startswith("radar/") for n in names) and sum(n.endswith(".csv") for n in names) == 2
        for bad in ("/api/flights/../x/files/a", f"/api/flights/{fl[0]['id']}/files/..%2Fpasses.jsonl", "/api/flights/nope/bundle.zip"):
            with pytest.raises(urllib.error.HTTPError) as e:
                get(base + bad)
            assert e.value.code == 404
        _s, h, rb = get(f"{base}/api/flights/{fl[0]['id']}/report.html")
        page = rb.decode()
        assert h["Content-Type"].startswith("text/html") and "SAR 비행 보고서" in page and "✓ 유효" in page and "<svg" in page
        assert "report.html" in zipfile.ZipFile(io.BytesIO(get(f"{base}/api/flights/{fl[0]['id']}/bundle.zip?raw=0")[2])).namelist()
        _s, _h, hb = get(f"{base}/api/health")
        assert json.loads(hb)["disk_free_bytes"] > 0
    finally:
        srv.shutdown()
