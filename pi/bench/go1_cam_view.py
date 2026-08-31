"""
피지컬팀 mk2 — Go1 카메라 라이브 뷰어 (HW-R-07 검증용)
=========================================================
`robot/go1_camera.py` 가 받아오는 H.264 를 브라우저에서 눈으로 확인하기 위한 도구다.
운영 구성요소가 아니다 — 운영 경로는 엣지가 받는 것이고, 이건 **말단에서 영상이 실제로
나오는가**를 사람이 확인하기 위한 것이다.

    카메라 ──ws H.264──► pi7 ──ffmpeg──► MJPEG ──HTTP multipart──► 브라우저

MJPEG 로 바꾸는 이유는 하나뿐이다. `<img>` 태그 하나로 재생돼서 보는 쪽에 아무것도
설치할 필요가 없다. 대역폭은 원본보다 훨씬 크므로(0.55 Mbps → 약 3.6 Mbps) **검증용이지
운반 방식의 제안이 아니다.**

사용:
    ssh physical@pi7.local
    cd ~/hw/pi && python3 -m bench.go1_cam_view 8090
    # 브라우저에서 http://pi7.local:8090/

**실측 (pi7, 2026-08-31):** 카메라 1대 29 fps / 3.6 Mbps, 5대 동시에도 29 fps 유지,
CPU 0.65코어(4코어 중 17%). 로봇 쪽 부하·상태 변화 없음.
"""
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from robot.go1_camera import CAMS, Go1CameraSource

IDLE_STOP_S = 25.0          # 보는 사람이 없으면 이만큼 뒤 스스로 멈춘다
JPEG_QUALITY = "5"


class CameraWorker:
    """웹소켓 H.264 → ffmpeg → **최신 JPEG 한 장.**

    큐를 두지 않는 것이 핵심이다. 프레임을 쌓아 두면 보는 사람이 느릴 때 지연이
    그대로 누적돼 몇 초 전 장면을 보게 된다. 늦은 프레임은 버리는 편이 맞다.
    """

    def __init__(self, cam_id):
        self.cam_id = cam_id
        self.label = CAMS[cam_id][2]
        self.cond = threading.Condition()
        self.jpeg = None
        self.seq = 0
        self.fps = 0.0
        self.err = None
        self.last_want = 0.0
        self.running = False
        self.proc = None

    # ---------- 생애주기 ----------
    def want(self):
        """보는 사람이 있다는 표시. 꺼져 있으면 켠다."""
        self.last_want = time.time()
        if not self.running:
            self.running = True
            threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        self.proc = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             # `-fflags nobuffer` 는 **넣으면 안 된다.** 출력이 파이프일 때 두어 프레임만
             # 내보내고 나머지를 통째로 버린다 — 같은 입력이 파일 출력에서는 3.4MB,
             # 파이프 출력에서는 29KB 로 나왔다. 실시간으로 먹이므로 없어도 지연은 없다.
             #
             # `-threads 1` 이 지연의 핵심이다. ffmpeg 은 기본이 **프레임 단위 멀티스레딩**
             # 이라 스레드 수만큼 프레임을 쥐고 있다가 내보낸다. 처리량에는 좋지만
             # 실시간 감시에는 그 지연이 그대로 보인다. 입출력 양쪽을 1스레드로 묶어
             # 파이 내부 지연을 실측 301ms → 37ms 로 줄였다(디코더 -134, 인코더 -131).
             # 464x400 은 1스레드로도 29fps 를 유지하므로 잃는 것이 없다.
             "-threads", "1",
             "-probesize", "32k", "-analyzeduration", "0",
             "-f", "h264", "-i", "pipe:0",
             "-f", "mjpeg", "-q:v", JPEG_QUALITY, "-threads", "1", "pipe:1"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL)
        threading.Thread(target=self._pump, daemon=True).start()
        self._collect()

    def _pump(self):
        """웹소켓 → ffmpeg stdin. flush 를 빠뜨리면 파이썬 버퍼에 갇혀
        ffmpeg 이 한 바이트도 못 받는다."""
        try:
            for chunk in Go1CameraSource(self.cam_id):
                if not self.running:
                    break
                self.proc.stdin.write(chunk)
                self.proc.stdin.flush()
        except Exception as e:
            self.err = f"{type(e).__name__}: {e}"
        finally:
            try:
                self.proc.stdin.close()
            except Exception:
                pass

    def _collect(self):
        """ffmpeg stdout 의 연속 JPEG 를 SOI/EOI 로 잘라낸다."""
        buf = b""
        t0, n = time.time(), 0
        try:
            while self.running:
                # read(n) 은 n 바이트가 찰 때까지 막는다. os.read 로 오는 대로 받는다.
                d = os.read(self.proc.stdout.fileno(), 65536)
                if not d:
                    break
                buf += d
                while True:
                    s = buf.find(b"\xff\xd8")
                    e = buf.find(b"\xff\xd9", s + 2) if s >= 0 else -1
                    if s < 0 or e < 0:
                        break
                    with self.cond:
                        self.jpeg = buf[s:e + 2]
                        self.seq += 1
                        self.cond.notify_all()
                    buf = buf[e + 2:]
                    n += 1
                dt = time.time() - t0
                if dt >= 2.0:
                    self.fps, t0, n = round(n / dt, 1), time.time(), 0
                if time.time() - self.last_want > IDLE_STOP_S:
                    break
        except Exception as e:
            self.err = f"{type(e).__name__}: {e}"
        finally:
            self.stop()

    def stop(self):
        self.running = False
        if self.proc is not None:
            try:
                self.proc.kill()
            except Exception:
                pass
            self.proc = None
        with self.cond:
            self.cond.notify_all()

    def wait_frame(self, last_seq, timeout=8.0):
        with self.cond:
            if self.seq == last_seq:
                self.cond.wait(timeout)
            return self.seq, self.jpeg


WORKERS = {cid: CameraWorker(cid) for cid in CAMS}

PAGE = """<!doctype html><meta charset="utf-8"><title>Go1 카메라</title>
<style>
body{background:#111;color:#ddd;font:14px/1.6 system-ui,sans-serif;margin:0;padding:16px}
h1{font-size:16px;margin:0 0 10px;font-weight:600}
nav{margin-bottom:12px}
a{color:#7bf;text-decoration:none;margin-right:14px}
a:hover{text-decoration:underline}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
figure{margin:0;background:#000;border:1px solid #333;border-radius:6px;overflow:hidden}
figcaption{padding:6px 10px;font-size:13px;color:#9ad;border-top:1px solid #222}
img{width:100%;display:block;background:#000}
.big img{max-height:78vh;object-fit:contain}
</style>
<h1>Unitree Go1 카메라 — 실시간</h1>
<nav>%NAV%</nav><div class="grid">%BODY%</div>
"""


def nav_html():
    return ('<a href="/">전체</a>'
            + "".join(f'<a href="/cam/{c}">{c} {CAMS[c][2]}</a>' for c in CAMS))


def cell(cid, big=False):
    klass = ' class="big"' if big else ''
    return (f'<figure{klass}><img src="/stream/{cid}" alt="cam{cid}">'
            f'<figcaption>{cid} · {CAMS[cid][2]}</figcaption></figure>')


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass                                  # 프레임마다 로그가 찍히면 못 쓴다

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            return self._html("".join(cell(c) for c in CAMS))
        if path.startswith("/cam/") or path.startswith("/stream/"):
            try:
                cid = int(path.rsplit("/", 1)[1])
            except ValueError:
                return self.send_error(404)
            if cid not in CAMS:
                return self.send_error(404)
            if path.startswith("/cam/"):
                return self._html(cell(cid, big=True))
            return self._stream(cid)
        self.send_error(404)

    def _html(self, body):
        b = PAGE.replace("%NAV%", nav_html()).replace("%BODY%", body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _stream(self, cid):
        cam = WORKERS[cid]
        cam.want()
        self.send_response(200)
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=fr")
        self.end_headers()
        seq = -1
        try:
            while True:
                cam.want()                    # 연결이 살아 있는 동안 계속 요구한다
                seq, jpg = cam.wait_frame(seq)
                if jpg is None:
                    if cam.err:
                        break
                    continue
                self.wfile.write(b"--fr\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                 + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass                              # 브라우저가 닫은 것뿐이다


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    srv.daemon_threads = True
    print(f"대기 중 — http://<이 호스트>:{port}/")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        for w in WORKERS.values():
            w.stop()


if __name__ == "__main__":
    main()
