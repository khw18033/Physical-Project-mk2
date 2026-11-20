# -*- coding: utf-8 -*-
"""
피지컬팀 mk2 — RoboMaster EP 카메라 H.264 중계 (HW-R-07)
===========================================================
EP 카메라의 H.264 를 **디코드도 재인코딩도 하지 않고** 관제 웹에 WebSocket 으로 넘긴다.

    EP 카메라 ──SDK 스트림(H.264)──► 이 모듈 ──WebSocket──► 브라우저 WebCodecs

## 왜 무변환인가 — Go1 에서 이미 재본 값이다

`bench/go1_cam_view.py` 가 같은 결론에 먼저 도달했다(실측: 파이 내부 지연 37→0 ms,
CPU 0.65→0.02 코어, 대역폭 3.6→0.58 Mbps). 로봇이 이미 H.264 로 주는데 말단에서 풀어
다시 인코딩하면 지연·CPU·대역폭을 전부 잃는다. **와이어 포맷도 그 뷰어와 같게 뒀다** —
관제 웹이 이미 그 형식을 먹고 있어서, 다르게 만들면 웹을 고쳐야 한다.

## SDK 가 푸는 것을 가로챈다

RoboMaster SDK 의 `media.LiveView` 는 받은 H.264 를 `_h264_decode()` 로 풀어 프레임 큐에
넣는다. 우리는 **그 함수를 갈아끼워** 생 바이트를 가져가고 빈 목록을 돌려준다. 디코더가
돌지 않으므로 CPU 도 쓰지 않는다 — 중계에 푼 그림은 필요 없다.

⚠ SDK 연결은 하나뿐이다(RNDIS 독점). 그래서 이 모듈은 자기 연결을 만들지 않고
**EpLink 가 이미 연 로봇 객체를 빌려 쓴다.** 별도 프로세스로 띄우면 노드가 끊긴다.

## 첫 프레임은 반드시 키프레임

GOP 중간부터 보내면 디코더가 아무것도 그리지 못한 채 다음 IDR 까지 기다린다 — 화면은
검게 멈춰 있고 오류는 어디에도 안 남는다. 그래서 **붙은 뷰어에게는 IDR 이 올 때까지
아무것도 보내지 않는다.** 실측(2026-11-20, 720p)에서 IDR 은 약 21프레임마다 오므로
기다림은 1초 안쪽이다.

## 느린 뷰어의 프레임은 버린다

큐를 깊게 두면 뒤처진 뷰어가 몇 초 전 장면을 본다. 얕은 큐에서 밀리면 오래된 것부터
버린다 — 늦은 프레임은 가치가 없다.
"""
import base64
import hashlib
import json
import queue
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from common import config

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
QUEUE_MAX = 8               # 느린 뷰어 때문에 지연이 쌓이지 않도록 얕게 둔다
IDLE_STOP_S = 20.0          # 보는 사람이 없으면 이만큼 뒤 카메라를 끈다


# ---------------------------------------------------------------- Annex-B
def nal_types(chunk):
    """Annex-B 조각 안의 NAL 종류 집합. 5=IDR, 7=SPS, 8=PPS, 9=AUD."""
    out, i = set(), 0
    while True:
        j = chunk.find(b"\x00\x00\x01", i)
        if j < 0 or j + 3 >= len(chunk):
            return out
        out.add(chunk[j + 3] & 0x1F)
        i = j + 3


def codec_string(chunk):
    """SPS 에서 WebCodecs 코덱 문자열(avc1.PPCCLL)을 만든다. 없으면 None.

    프로파일·레벨을 박아 두면 펌웨어가 바뀔 때 조용히 어긋나므로 매번 읽는다."""
    i = 0
    while True:
        j = chunk.find(b"\x00\x00\x01", i)
        if j < 0 or j + 3 >= len(chunk):
            return None
        if (chunk[j + 3] & 0x1F) == 7 and j + 7 <= len(chunk):
            return "avc1." + chunk[j + 4:j + 7].hex()
        i = j + 3


# ---------------------------------------------------------------- 상류 소스
class EpCameraSource:
    """EP 카메라의 H.264 를 **액세스 유닛 단위로** 내는 이터레이터.

    SDK 가 돌려주는 조각은 프레임 경계와 무관하다(TCP 읽기 단위다). 그대로 흘리면
    키프레임 판정이 조각마다 갈려 뷰어가 GOP 중간에 붙는다. EP 는 매 프레임 앞에
    AUD(NAL 9)를 붙여 보내므로 그것을 경계로 모은다 — 경계가 없으면 SPS 를 쓴다.
    """

    def __init__(self, ep, resolution=None):
        self.ep = ep
        self.resolution = resolution or config.EP_CAM_RESOLUTION
        self.q = queue.Queue(maxsize=64)
        self._buf = bytearray()
        self._orig = None
        self._lv = None
        self.started_at = None

    # ---------- 탭 ----------
    def _boundary(self, data):
        """새 액세스 유닛의 시작 위치들. AUD 또는 SPS 가 경계다."""
        out, i = [], 0
        while True:
            j = data.find(b"\x00\x00\x01", i)
            if j < 0 or j + 3 >= len(data):
                return out
            t = data[j + 3] & 0x1F
            if t in (9, 7):
                # 4바이트 시작코드면 한 칸 앞이 진짜 시작이다.
                out.append(j - 1 if j > 0 and data[j - 1] == 0 else j)
            i = j + 3

    def _tap(self, data):
        """SDK 의 _h264_decode 자리. 바이트만 챙기고 **디코드하지 않는다.**"""
        self._buf.extend(data)
        bounds = self._boundary(self._buf)
        if len(bounds) >= 2:
            # 마지막 경계 앞까지는 완성된 액세스 유닛이다. 마지막 것은 아직 덜 왔다.
            cut = bounds[-1]
            unit = bytes(self._buf[bounds[0]:cut])
            del self._buf[:cut]
            if unit:
                try:
                    self.q.put_nowait((time.time(), unit))
                except queue.Full:
                    pass          # 아무도 안 가져가면 버린다. 쌓으면 지연만 는다.
        elif len(self._buf) > 4 << 20:
            # 경계를 영영 못 찾는 경우(포맷 가정이 틀렸다)에 메모리를 지키는 자리.
            del self._buf[:-(1 << 20)]
        return []

    # ---------- 생애주기 ----------
    def start(self):
        lv = self.ep.camera._liveview
        self._lv = lv
        self._orig = lv._h264_decode
        lv._h264_decode = self._tap
        ok = self.ep.camera.start_video_stream(display=False, resolution=self.resolution)
        if not ok:
            self.stop()
            raise RuntimeError("ep_camera_start_failed")
        self.started_at = time.time()

    def stop(self):
        try:
            self.ep.camera.stop_video_stream()
        except Exception:
            pass
        if self._lv is not None and self._orig is not None:
            self._lv._h264_decode = self._orig       # 탭을 반드시 되돌린다
        self._lv = self._orig = None

    def __iter__(self):
        while True:
            try:
                yield self.q.get(timeout=5.0)
            except queue.Empty:
                raise RuntimeError("ep_camera_stalled")


# ---------------------------------------------------------------- 허브
class Hub:
    """카메라 하나에 상류 하나. 뷰어가 몇이든 로봇에는 스트림 하나만 연다."""

    def __init__(self, get_ep):
        self.get_ep = get_ep
        self.lock = threading.Lock()
        self.subs = set()
        self.codec = None
        self.err = None
        self.running = False
        self.last_want = 0.0
        self.fps = 0.0
        self.frames = 0

    def subscribe(self):
        q = queue.Queue(maxsize=QUEUE_MAX)
        with self.lock:
            self.subs.add(q)
            self.last_want = time.time()
            if not self.running:
                self.running = True
                threading.Thread(target=self._run, daemon=True).start()
        return q

    def unsubscribe(self, q):
        with self.lock:
            self.subs.discard(q)

    def _fanout(self, item):
        with self.lock:
            subs = list(self.subs)
        for q in subs:
            try:
                q.put_nowait(item)
            except queue.Full:
                # 뒤처진 뷰어의 **오래된** 프레임을 버린다. 쌓아 두면 그 뷰어는 몇 초
                # 전 장면을 보게 된다 — 늦은 프레임은 버리는 편이 맞다.
                try:
                    q.get_nowait()
                    q.put_nowait(item)
                except queue.Empty:
                    pass

    def _run(self):
        src = None
        n, t0 = 0, time.time()
        try:
            ep = self.get_ep()
            if ep is None:
                raise RuntimeError("ep_not_connected")
            src = EpCameraSource(ep)
            src.start()
            self.err = None
            for ts, chunk in src:
                types = nal_types(chunk)
                if self.codec is None and 7 in types:
                    self.codec = codec_string(chunk)
                self._fanout((ts, 5 in types, chunk))
                n += 1
                self.frames += 1
                dt = time.time() - t0
                if dt >= 2.0:
                    self.fps, n, t0 = round(n / dt, 1), 0, time.time()
                with self.lock:
                    if not self.subs and time.time() - self.last_want > IDLE_STOP_S:
                        break
                    if self.subs:
                        self.last_want = time.time()
        except Exception as e:
            self.err = "%s: %s" % (type(e).__name__, e)
            print("[cam] 상류 중단 — %s" % self.err)
        finally:
            if src is not None:
                src.stop()
            # go1_cam_view 가 겪은 경합을 그대로 피한다: 유휴로 빠져나오는 중에 새
            # 구독자가 들어오면 running 이 아직 True 라 새 스레드가 안 뜨고, 곧바로
            # None 을 뿌려 **막 붙은 뷰어의 스트림이 즉시 끝난다.**
            with self.lock:
                self.running = False
                restart = bool(self.subs)
                if restart:
                    self.running = True
            if restart:
                time.sleep(0.5)          # 상류가 계속 실패할 때 스핀하지 않도록
                threading.Thread(target=self._run, daemon=True).start()
            else:
                self._fanout(None)


# ---------------------------------------------------------------- WebSocket
def ws_accept(key):
    return base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()


class WSConn:
    """서버→클라이언트 프레임 송신. 여러 스레드가 쓰므로 잠근다."""

    def __init__(self, sock):
        self.sock = sock
        self.lock = threading.Lock()

    def send(self, payload, opcode=0x2):
        n = len(payload)
        if n < 126:
            hdr = bytes((0x80 | opcode, n))
        elif n < 65536:
            hdr = bytes((0x80 | opcode, 126)) + n.to_bytes(2, "big")
        else:
            hdr = bytes((0x80 | opcode, 127)) + n.to_bytes(8, "big")
        with self.lock:
            self.sock.sendall(hdr + payload)

    def send_text(self, obj):
        self.send(json.dumps(obj).encode("utf-8"), opcode=0x1)


class _Handler(BaseHTTPRequestHandler):
    """`/ws/<카메라키>` 하나만 연다. 제어 메시지는 없다 — **붙는 것이 켜기이고
    끊는 것이 끄기다.** 상태 확인용으로 `/health` 만 덧붙인다."""

    protocol_version = "HTTP/1.1"
    hub = None
    cam_key = "ep-001"

    def log_message(self, *a):
        pass                      # 기본 구현은 프레임마다 stderr 에 쓴다

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            h = self.hub
            body = json.dumps({
                "cam": self.cam_key, "codec": h.codec, "fps": h.fps,
                "frames": h.frames, "viewers": len(h.subs), "err": h.err,
            }, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path in ("/ws/" + self.cam_key, "/ws", "/" + self.cam_key):
            return self._ws()
        self._explain(404, "없는 경로다. 영상은 /ws/%s, 상태는 /health 로 붙는다.\n"
                           % self.cam_key)

    def _explain(self, code, text):
        """사유를 **본문**에 담아 돌려준다.

        HTTP 상태줄은 latin-1 이다. 한글을 거기 실으면 send_response 가
        UnicodeEncodeError 로 죽고, 응답 없이 연결만 끊긴다 — 부른 쪽은 서버가
        죽었는지 경로가 틀렸는지 알 수 없다(실측 2026-11-20: curl 이 HTTP 000).
        상태줄은 ASCII 로 두고 설명은 본문에 넣는다."""
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _ws(self):
        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            return self._explain(
                400, "웹소켓 요청이 아니다. Upgrade: websocket 으로 붙는다.\n"
                     "경로: /ws/%s\n" % self.cam_key)
        self.close_connection = True
        self.wfile.write(("HTTP/1.1 101 Switching Protocols\r\n"
                          "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                          f"Sec-WebSocket-Accept: {ws_accept(key)}\r\n\r\n").encode())
        self.wfile.flush()
        # Nagle 을 끈다. 프레임이 MSS 에 못 미치는 조각을 남기는데, Nagle 은 그것을
        # 다음 데이터나 ACK 까지 붙든다 — 지연 ACK 와 겹치면 프레임당 수십 ms 가
        # 조용히 붙는다(go1_cam_view 실측).
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn = WSConn(self.connection)
        hub = self.hub
        q = hub.subscribe()
        try:
            sent_hello = False
            while True:
                item = q.get(timeout=15)
                if item is None:
                    break
                ts, is_key, chunk = item
                if not sent_hello:
                    # GOP 중간부터 보내면 디코더가 다음 IDR 까지 아무것도 못 그린다.
                    # 화면은 검게 멈추고 오류는 남지 않는다 — 키프레임을 기다린다.
                    if hub.codec is None or not is_key:
                        continue
                    conn.send_text({"t": "hello", "codec": hub.codec,
                                    "cam": self.cam_key})
                    sent_hello = True
                conn.send(bytes((1 if is_key else 0,))
                          + struct.pack(">d", ts * 1000.0) + chunk)
        except (queue.Empty, BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            hub.unsubscribe(q)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(get_ep, port=None, cam_key=None):
    """카메라 중계를 띄운다. 호출 즉시 돌아오고 서버는 뒤에서 돈다.

    `get_ep` 는 **호출할 때마다 현재 로봇 객체를 돌려주는 함수**다. 객체를 그대로
    받으면 EP 가 재접속해 객체가 갈렸을 때 죽은 연결을 계속 붙든다."""
    port = int(port or config.EP_CAM_PORT)
    cam_key = cam_key or config.EP_CAM_KEY or "ep-001"
    hub = Hub(get_ep)
    handler = type("_H", (_Handler,), {"hub": hub, "cam_key": cam_key})
    srv = _Server(("0.0.0.0", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("[cam] 영상 소켓 ws://<주소>:%d/ws/%s (health: /health)" % (port, cam_key))
    return srv, hub
