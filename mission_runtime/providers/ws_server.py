"""최소 WebSocket 서버 — **전송 provider 구현이다.**

왜 손으로 쓰는가: 이 프레임워크의 핵심 의존성은 `jsonschema · numpy · opencv ·
protobuf` 넷뿐이고, 전송 구현은 전부 선택 의존성 뒤에 있다(AI-C-06 · AI-C-04).
가시화 한 화면을 붙이려고 핵심 의존성을 늘리면 그 규칙이 깨진다. RFC 6455 의
**텍스트 프레임 한 갈래**만 필요하므로 표준 라이브러리로 충분하다.

하지 않는 것을 먼저 적는다 — 확장(permessage-deflate) · 단편화된 연속 프레임 ·
바이너리 프레임 · TLS. 필요해지면 그때 `websockets` 를 선택 의존성으로 넣고 이
파일을 교체하면 된다. 상위 로직은 이 파일을 모르고 `on_message` 콜백만 안다.

같은 포트에서 평범한 HTTP GET 도 받는다(`/registry` 같은 것). 업그레이드 헤더가
없으면 HTTP 로 처리한다 — 뷰어가 WS 와 HTTP 를 같은 주소로 쓰기 때문이다.

implements: AI-C-04, AI-C-06
"""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import struct
import threading
from collections.abc import Callable

#: RFC 6455 §1.3 의 고정 GUID. **한 글자라도 틀리면 모든 브라우저가
#: "Incorrect Sec-WebSocket-Accept" 로 거절한다** — 검산은 RFC 의 예시
#: 한 쌍으로 한다(아래 `_RFC_EXAMPLE`). 그 검산이 어긋나면 GUID 를 의심한다.
_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

#: RFC 6455 §1.3 의 예시 한 쌍. 이 상수가 맞는지를 import 시점에 바로 확인한다 —
#: 틀린 GUID 는 핸드셰이크 전부를 조용히 깨뜨리고, 증상(연결됐다 끊김)이 원인을
#: 가리키지 않아 찾는 데 오래 걸린다.
_RFC_EXAMPLE = ("dGhlIHNhbXBsZSBub25jZQ==", "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

OP_TEXT, OP_CLOSE, OP_PING, OP_PONG = 0x1, 0x8, 0x9, 0xA


def _accept_key(client_key: str) -> str:
    digest = hashlib.sha1((client_key + _GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


assert _accept_key(_RFC_EXAMPLE[0]) == _RFC_EXAMPLE[1], (
    "Sec-WebSocket-Accept 계산이 RFC 6455 §1.3 예시와 어긋난다 — _GUID 를 확인하라")


def _frame(payload: bytes, opcode: int = OP_TEXT) -> bytes:
    """서버 → 클라이언트 프레임. 서버는 마스킹하지 않는다(RFC 6455 §5.1)."""
    header = bytes([0x80 | opcode])
    size = len(payload)
    if size < 126:
        header += bytes([size])
    elif size < (1 << 16):
        header += bytes([126]) + struct.pack(">H", size)
    else:
        header += bytes([127]) + struct.pack(">Q", size)
    return header + payload


class _Reader:
    """한 소켓에서 프레임을 하나씩 꺼낸다. 클라이언트 프레임은 **반드시** 마스킹돼 있다."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._buf = b""

    def _need(self, n: int) -> bytes | None:
        while len(self._buf) < n:
            chunk = self._sock.recv(65536)
            if not chunk:
                return None
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def read(self) -> tuple[int, bytes] | None:
        head = self._need(2)
        if head is None:
            return None
        opcode = head[0] & 0x0F
        masked = bool(head[1] & 0x80)
        size = head[1] & 0x7F
        if size == 126:
            raw = self._need(2)
            if raw is None:
                return None
            size = struct.unpack(">H", raw)[0]
        elif size == 127:
            raw = self._need(8)
            if raw is None:
                return None
            size = struct.unpack(">Q", raw)[0]
        mask = self._need(4) if masked else b""
        if masked and mask is None:
            return None
        body = self._need(size) if size else b""
        if body is None:
            return None
        if masked:
            body = bytes(b ^ mask[i % 4] for i, b in enumerate(body))
        return opcode, body


class WsClient:
    """연결 하나. 전송은 잠금으로 직렬화한다 — 두 스레드가 한 소켓에 겹쳐 쓰면 프레임이 깨진다."""

    def __init__(self, sock: socket.socket, addr: object) -> None:
        self.sock = sock
        self.addr = addr
        self.alive = True
        self._lock = threading.Lock()

    def send_json(self, message: object) -> bool:
        """보내지 못하면 **예외 대신 False**. 한 연결이 죽어도 방송 루프가 끊기지 않는다."""
        if not self.alive:
            return False
        try:
            data = json.dumps(message, ensure_ascii=False).encode("utf-8")
            with self._lock:
                self.sock.sendall(_frame(data))
            return True
        except OSError:
            self.alive = False
            return False

    def close(self) -> None:
        self.alive = False
        try:
            with self._lock:
                self.sock.sendall(_frame(b"", OP_CLOSE))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class WsHttpServer:
    """같은 포트에서 WebSocket 과 평범한 HTTP GET 을 함께 받는다.

    `on_message(client, dict)` 가 뷰어가 보낸 메시지를 받고, `on_open(client)` 가
    접속 직후 불린다. `http_get(path)` 는 `(status, content_type, body)` 를 돌려
    주거나 `None`(404)을 돌려준다.
    """

    def __init__(
        self,
        host: str,
        port: int,
        *,
        on_message: Callable[[WsClient, dict], None],
        on_open: Callable[[WsClient], None] | None = None,
        on_close: Callable[[WsClient], None] | None = None,
        http_get: Callable[[str], tuple[int, str, bytes] | None] | None = None,
    ) -> None:
        self.host, self.port = host, port
        self._on_message = on_message
        self._on_open = on_open
        self._on_close = on_close
        self._http_get = http_get
        self._server: socket.socket | None = None
        self._clients: set[WsClient] = set()
        self._clients_lock = threading.Lock()
        self._stop = threading.Event()

    # -- 수명 ---------------------------------------------------------------
    def start(self) -> int:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(32)
        self._server = srv
        self.port = srv.getsockname()[1]
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return self.port

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
        for client in self.clients():
            client.close()

    def clients(self) -> list[WsClient]:
        with self._clients_lock:
            return [c for c in self._clients if c.alive]

    def broadcast(self, message: object) -> int:
        sent = 0
        for client in self.clients():
            if client.send_json(message):
                sent += 1
        return sent

    # -- 내부 ---------------------------------------------------------------
    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                sock, addr = self._server.accept()        # type: ignore[union-attr]
            except OSError:
                return
            threading.Thread(target=self._serve, args=(sock, addr), daemon=True).start()

    def _serve(self, sock: socket.socket, addr: object) -> None:
        client: WsClient | None = None
        try:
            raw = b""
            while b"\r\n\r\n" not in raw:
                chunk = sock.recv(65536)
                if not chunk:
                    sock.close()
                    return
                raw += chunk
            head, _, rest = raw.partition(b"\r\n\r\n")
            lines = head.decode("latin-1").split("\r\n")
            request = lines[0].split(" ")
            path = request[1] if len(request) > 1 else "/"
            headers = {}
            for line in lines[1:]:
                key, _, value = line.partition(":")
                headers[key.strip().lower()] = value.strip()

            if headers.get("upgrade", "").lower() != "websocket":
                self._serve_http(sock, path)
                return

            key = headers.get("sec-websocket-key", "")
            response = (
                b"HTTP/1.1 101 Switching Protocols\r\n"
                b"Upgrade: websocket\r\n"
                b"Connection: Upgrade\r\n"
                b"Sec-WebSocket-Accept: " + _accept_key(key).encode("ascii")
                + b"\r\n\r\n")
            sock.sendall(response)

            client = WsClient(sock, addr)
            with self._clients_lock:
                self._clients.add(client)
            if self._on_open is not None:
                self._on_open(client)

            reader = _Reader(sock)
            reader._buf = rest
            while client.alive and not self._stop.is_set():
                got = reader.read()
                if got is None:
                    break
                opcode, body = got
                if opcode == OP_CLOSE:
                    break
                if opcode == OP_PING:
                    with client._lock:
                        try:
                            sock.sendall(_frame(body, OP_PONG))
                        except OSError:
                            break
                    continue
                if opcode != OP_TEXT:
                    continue
                try:
                    message = json.loads(body.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
                if isinstance(message, dict):
                    # 한 메시지의 실패가 연결을 끊지 않는다.
                    try:
                        self._on_message(client, message)
                    except Exception:                      # noqa: BLE001
                        pass
        except OSError:
            pass
        finally:
            # 핸드셰이크 전에 끊기면 client 가 없다 — 그 경우도 소켓은 닫는다.
            if client is not None:
                client.alive = False
                with self._clients_lock:
                    self._clients.discard(client)
                if self._on_close is not None:
                    self._on_close(client)
            try:
                sock.close()
            except OSError:
                pass

    def _serve_http(self, sock: socket.socket, path: str) -> None:
        result = self._http_get(path) if self._http_get is not None else None
        if result is None:
            body = b'{"error":"not_found"}'
            status, ctype = 404, "application/json"
        else:
            status, ctype, body = result
        reason = {200: "OK", 404: "Not Found", 405: "Method Not Allowed"}.get(status, "OK")
        try:
            sock.sendall(
                f"HTTP/1.1 {status} {reason}\r\nContent-Type: {ctype}\r\n"
                f"Content-Length: {len(body)}\r\n"
                # 뷰어가 다른 포트(5173)에서 뜨므로 조회는 열어 둔다.
                "Access-Control-Allow-Origin: *\r\n"
                "Connection: close\r\n\r\n".encode("latin-1") + body)
        except OSError:
            pass
        finally:
            try:
                sock.close()
            except OSError:
                pass
