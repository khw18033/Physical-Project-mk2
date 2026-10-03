"""지도 타일 캐시 — 원본 대신 가짜 원본(로컬 HTTP)으로. 한 번 받으면 원본이 꺼져도 나온다."""

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sar_data.server import Store, make_handler
from sar_data.tiles import TileCache, tile_xy, tiles_in


def test_tile_math():
    assert tile_xy(0.0, 0.0, 1) == (1, 1) and tile_xy(85.0, -180.0, 3) == (0, 0)
    t = tiles_in(37.5660, 126.9775, 37.5670, 126.9785, 18, 19)
    assert all(z in (18, 19) for z, _, _ in t) and 2 <= len(t) <= 40


def _serve(handler):  # noqa: ANN001
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def test_cache_through_and_prefetch(tmp_path):
    hits = []

    class Origin(BaseHTTPRequestHandler):
        def log_message(self, *a):  # noqa: ANN002
            pass

        def do_GET(self):  # noqa: N802
            hits.append(self.path)
            body = b"\x89PNG fake " + self.path.encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    origin, op = _serve(Origin)
    cache = TileCache(tmp_path / "tiles", {"satellite": f"http://127.0.0.1:{op}/{{z}}/{{y}}/{{x}}",
                                           "street": f"http://127.0.0.1:{op}/s/{{z}}/{{x}}/{{y}}.png"})
    srv, sp = _serve(make_handler(Store(tmp_path / "f", None), tiles=cache))
    base = f"http://127.0.0.1:{sp}"
    try:
        body = urllib.request.urlopen(f"{base}/tiles/satellite/18/223300/101300.png").read()
        assert body.endswith(b"/18/101300/223300") and len(hits) == 1          # Esri 는 z/y/x
        urllib.request.urlopen(f"{base}/tiles/satellite/18/223300/101300.png").read()
        assert len(hits) == 1                                                   # 두 번째는 디스크에서
        r = urllib.request.urlopen(f"{base}/api/tiles/prefetch?s=37.566&w=126.9775&n=37.567&e=126.9785&zmin=17&zmax=18")
        assert r.status == 202
        for _ in range(100):
            st = json.loads(urllib.request.urlopen(f"{base}/api/tiles/status").read())
            if st["job"]["state"] == "done":
                break
            time.sleep(0.05)
        assert st["job"]["failed"] == 0 and st["cached_tiles"] >= st["job"]["total"]
        origin.shutdown()                                                       # 현장: 인터넷 없음
        assert urllib.request.urlopen(f"{base}/tiles/satellite/18/223300/101300.png").status == 200
        try:
            urllib.request.urlopen(f"{base}/api/tiles/prefetch?s=30&w=120&n=40&e=130&zmin=10&zmax=18")
            raise AssertionError("너무 넓은 구역을 받아들였다")
        except urllib.error.HTTPError as e:
            assert e.code == 413
    finally:
        srv.shutdown()
