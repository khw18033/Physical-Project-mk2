"""가시화 게이트웨이 — 핸드셰이크 · 봉투 · 구독 매칭.

이 묶음이 생긴 계기를 적어 둔다. `_GUID` 에 **한 글자 오타**(마지막 묶음에서 앞의
`C` 가 빠지고 뒤에 `F` 가 붙음)가 있었고, 증상은 "브라우저가 붙었다가 바로 끊긴다"
였다. 서버 로그에는 101 을 보낸 것으로 찍히고 accept 값도 스스로 계산한 것과 같아서
원인이 전혀 드러나지 않았다 — 계산기와 검산기가 **같은 틀린 상수**를 썼기 때문이다.

그래서 여기서는 **바깥에서 온 벡터**로 잰다. RFC 6455 §1.3 의 예시 한 쌍은 우리가
만든 값이 아니라서, 상수가 틀어지면 반드시 깨진다.

implements: AI-C-01, AI-C-02, AI-C-04, AI-C-06, AI-O-04
tests: RFC handshake vector, envelope frames, quality tiers, selector matching,
       write hook carries body and headers, an optional header does not kill the
       response, a read-only port refuses POST before reading the body,
       unknown channel is dropped loudly
"""
from __future__ import annotations

import base64
import json
import os
import socket
import struct
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from integration.vz_wire import (  # noqa: E402
    SPATIAL_CHANNELS,
    VIEWER_CHANNELS,
    Selector,
    SubscriptionTable,
    quality_of,
    to_envelope,
)
from providers.ws_server import WsHttpServer, _accept_key  # noqa: E402


# ── 핸드셰이크 ──────────────────────────────────────────────────────────────

def test_accept_key_matches_the_rfc_example():
    """RFC 6455 §1.3 의 예시 한 쌍.

    **우리가 만든 기대값이 아니다.** 이 한 줄이 `_GUID` 오타를 잡는다 — 틀린
    상수로는 어떤 브라우저도 붙지 못하는데, 서버 혼자 검산하면 늘 통과한다.
    """
    assert _accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


def _handshake(port: int) -> tuple[socket.socket, bool, bytes]:
    """표준 라이브러리로 직접 붙어 본다. accept 를 **클라이언트가 다시 계산해** 검사한다.

    HTTP 응답을 읽는 `recv` 가 **뒤따르는 프레임까지 함께 삼킬 수 있으므로** 남은
    바이트를 돌려준다 — 서버가 인사를 바로 보내면 같은 세그먼트에 실려 온다.
    """
    key = base64.b64encode(os.urandom(16)).decode()
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    sock.sendall(f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
                 f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                 f"Sec-WebSocket-Version: 13\r\n\r\n".encode())
    raw = b""
    while b"\r\n\r\n" not in raw:
        chunk = sock.recv(8192)
        if not chunk:
            break
        raw += chunk
    head, _, rest = raw.partition(b"\r\n\r\n")
    text = head.decode("latin-1")
    ok = ("101" in text.split("\r\n")[0]
          and f"Sec-WebSocket-Accept: {_accept_key(key)}" in text)
    return sock, ok, rest


def _send_text(sock: socket.socket, obj: object) -> None:
    data = json.dumps(obj).encode()
    mask = os.urandom(4)
    body = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    size = len(data)
    header = bytes([0x81]) + (bytes([0x80 | size]) if size < 126
                              else bytes([0x80 | 126]) + struct.pack(">H", size))
    sock.sendall(header + mask + body)


def _read_text(sock: socket.socket, pending: bytes = b"") -> dict | None:
    """`pending` 은 핸드셰이크 recv 가 먼저 삼킨 바이트다."""
    buf = bytearray(pending)

    def need(n: int) -> bytes | None:
        while len(buf) < n:
            chunk = sock.recv(8192)
            if not chunk:
                return None
            buf.extend(chunk)
        out = bytes(buf[:n])
        del buf[:n]
        return out

    head = need(2)
    if head is None:
        return None
    size = head[1] & 0x7F
    if size == 126:
        raw = need(2)
        if raw is None:
            return None
        size = struct.unpack(">H", raw)[0]
    body = need(size) if size else b""
    if body is None:
        return None
    return json.loads(body.decode("utf-8"))


@pytest.fixture()
def server():
    seen: list[dict] = []
    srv = WsHttpServer(
        "127.0.0.1", 0,
        on_message=lambda client, message: seen.append(message),
        on_open=lambda client: client.send_json({"type": "hello"}),
        http_get=lambda path, headers=None: ((200, "application/json", b'{"ok":true}')
                               if path == "/registry" else None))
    srv.start()
    srv.seen = seen                                          # type: ignore[attr-defined]
    yield srv
    srv.stop()


def test_a_real_client_completes_the_handshake_and_is_greeted(server):
    """클라이언트가 **스스로 다시 계산한** accept 로 검사한다 — 서버 자기검산이 아니다."""
    sock, ok, rest = _handshake(server.port)
    try:
        assert ok, "accept 가 클라이언트 계산과 다르다 — 브라우저도 같은 이유로 끊는다"
        assert _read_text(sock, rest) == {"type": "hello"}
    finally:
        sock.close()


def test_the_server_reads_a_masked_client_frame(server):
    """클라이언트 프레임은 **반드시** 마스킹돼 있다. 언마스킹을 빼먹으면 JSON 이 깨진다."""
    sock, ok, rest = _handshake(server.port)
    try:
        assert ok
        _read_text(sock, rest)                                # hello 를 비운다
        _send_text(sock, {"type": "subscribe", "id": "sub-1"})
        deadline = time.monotonic() + 3
        while not server.seen and time.monotonic() < deadline:  # type: ignore[attr-defined]
            time.sleep(0.02)
        assert server.seen == [{"type": "subscribe", "id": "sub-1"}]  # type: ignore[attr-defined]
    finally:
        sock.close()


def test_plain_http_still_works_on_the_same_port(server):
    """뷰어가 WS 와 레지스트리를 **같은 주소**로 쓴다."""
    sock = socket.create_connection(("127.0.0.1", server.port), timeout=5)
    try:
        sock.sendall(b"GET /registry HTTP/1.1\r\nHost: x\r\n\r\n")
        raw = sock.recv(8192).decode("latin-1")
        assert "200" in raw.split("\r\n")[0] and '{"ok":true}' in raw
    finally:
        sock.close()


# ── 봉투 ────────────────────────────────────────────────────────────────────

def test_quality_separates_never_seen_from_stale():
    """한 번도 못 받은 것과 오래된 것은 **다른 상태**다(AI-O-04).

    합치면 "아직 안 붙은 장치" 와 "붙었다가 끊긴 장치" 가 같은 색으로 보인다.
    """
    assert quality_of(last_seen_s=None, stale_after_s=60) == "unknown"
    assert quality_of(last_seen_s=5, stale_after_s=60) == "good"
    assert quality_of(last_seen_s=120, stale_after_s=60) == "degraded"


def test_coordinate_frame_only_rides_on_channels_that_carry_coordinates():
    """좌표가 없는 채널에 프레임 이름을 적으면 받는 쪽이 그 값으로 환산하려 든다."""
    spatial = to_envelope(entity="go1-001", node="go1-001", zone="zone-503",
                          channel="state", payload={}, seq=1,
                          coordinate_frame="zone-local")
    flat = to_envelope(entity="cpu", node="host", zone=None,
                       channel="metrics", payload={}, seq=2,
                       coordinate_frame="zone-local")
    assert spatial["coordinate_frame"] == "zone-local"
    assert flat["coordinate_frame"] is None, "metrics 는 좌표를 담지 않는다"
    assert "metrics" not in SPATIAL_CHANNELS


def test_the_envelope_never_claims_a_global_frame():
    """이 현장의 datum 은 미검증이고 경계 재합의도 끝나지 않았다(AI-C-02)."""
    envelope = to_envelope(entity="go1-001", node="go1-001", zone="zone-503",
                           channel="state", payload={}, seq=1,
                           coordinate_frame="zone-local")
    assert "global" not in str(envelope["coordinate_frame"])


# ── 구독 매칭 ───────────────────────────────────────────────────────────────

def test_selector_wildcards_match_every_axis():
    everything = Selector(entity="*", node="*", channel="*")
    narrow = Selector(entity="go1-001", node="*", channel="state")
    assert everything.matches(entity="x", node="y", channel="state")
    assert narrow.matches(entity="go1-001", node="pi7", channel="state")
    assert not narrow.matches(entity="ep-001", node="pi7", channel="state")
    assert not narrow.matches(entity="go1-001", node="pi7", channel="metrics")


def test_a_channel_the_viewer_does_not_know_is_dropped_loudly():
    """뷰어가 모르는 채널은 보내 봐야 `sub` 매칭에서 사라진다.

    조용히 버리면 "연결은 됐는데 화면이 빈" 상태가 되고 원인이 드러나지 않는다 —
    그래서 **계수기에 남긴다.**
    """
    table = SubscriptionTable()
    table.add({"id": "sub-1", "selector": {"entity": "*", "node": "*", "channel": "*"}})

    known = to_envelope(entity="go1-001", node="go1-001", zone=None,
                        channel="state", payload={}, seq=1)
    unknown = to_envelope(entity="go1-001", node="go1-001", zone=None,
                          channel="evidence_breakdown", payload={}, seq=2)

    assert len(table.frames_for(known)) == 1
    assert table.frames_for(unknown) == []
    assert table.dropped == {"evidence_breakdown": 1}
    assert "evidence_breakdown" not in VIEWER_CHANNELS


def test_frames_carry_the_viewers_own_subscription_id():
    """뷰어는 **자기가 붙인 id** 로만 봉투를 찾는다. 다른 값을 넣으면 통째로 버려진다."""
    table = SubscriptionTable()
    table.add({"id": "sub-7", "selector": {"entity": "*", "node": "*", "channel": "state"}})
    frames = table.frames_for(to_envelope(entity="a", node="b", zone=None,
                                          channel="state", payload={}, seq=1))
    assert frames[0]["type"] == "data" and frames[0]["sub"] == "sub-7"


def test_subscribe_without_an_id_is_rejected():
    assert SubscriptionTable().add({"selector": {}}) is None


# ---------------------------------------------------------------------------
# 쓰기 훅 (2026-11-05 — FMS 를 별도 웹에서 지우면서)
# ---------------------------------------------------------------------------


def _http(port: int, method: str, path: str, body: bytes = b"",
          extra: str = "") -> tuple[int, dict[str, str], bytes]:
    """머리를 직접 읽는다 — 조건부 머리 하나가 더해지며 응답이 사라진 적이 있다."""
    import socket as _socket

    sock = _socket.create_connection(("127.0.0.1", port), timeout=5)
    try:
        request = (f"{method} {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                   f"Content-Length: {len(body)}\r\n{extra}Connection: close\r\n\r\n")
        sock.sendall(request.encode("latin-1") + body)
        raw = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            raw += chunk
    finally:
        sock.close()
    head, _, payload = raw.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split(" ")[1])
    headers = {}
    for line in lines[1:]:
        key, _, value = line.partition(":")
        headers[key.strip()] = value.strip()
    return status, headers, payload


def test_without_a_write_hook_a_post_is_refused_before_the_body_is_read(server):
    """훅을 걸지 않은 자리는 **조회 포트다**(AI-O-06).

    모양도 스키마 하나다 — 전에는 `{"error":{"reason":…}}` 로 중첩이어서 같은
    오류에 두 모양이 있었다.
    """
    status, _headers, body = _http(server.port, "POST", "/registry", b'{"a":1}')
    assert status == 405
    assert json.loads(body.decode("utf-8")) == {"error": "read_only_endpoint"}


def test_a_response_survives_the_optional_server_header():
    """`_write` 가 머리를 `+` 로 이어 붙이다 `str + bytes` 가 되어 `TypeError` 를
    냈고, `except OSError` 가 그것을 잡지 못해 **응답 없이 연결이 끊겼다**.
    화면에는 "서버가 죽었다" 로 보였다. 조건부 머리가 더해지는 순간 터졌다."""
    srv = WsHttpServer("127.0.0.1", 0, on_message=lambda *a: None,
                       http_get=lambda path, headers=None:
                           (200, "application/json", b'{"ok":true}'),
                       server_name="FMS/9.9")
    srv.start()
    try:
        status, headers, body = _http(srv.port, "GET", "/anything")
        assert status == 200
        assert headers.get("Server") == "FMS/9.9"
        # **노출하지 않으면 보내는 의미가 없다.** 교차 출처에서 JS 가 읽을 수 있는
        # 응답 머리는 몇 개로 제한되고 `Server` 는 그 안에 없다 — 브라우저에서
        # 실제로 `null` 이었다. 판을 싣는 목적이 뷰어가 자기 기대와 맞추는 것이므로
        # 읽히지 않으면 문서에만 있는 것과 같다.
        assert "Server" in headers.get("Access-Control-Expose-Headers", "")
        assert json.loads(body.decode("utf-8")) == {"ok": True}
    finally:
        srv.stop()


def test_the_write_hook_receives_the_body_and_the_headers():
    seen: dict = {}

    def http_post(path, body, headers):
        seen.update(path=path, body=body, auth=headers.get("authorization"))
        return 202, "application/json", b'{"accepted":true}'

    srv = WsHttpServer("127.0.0.1", 0, on_message=lambda *a: None,
                       http_post=http_post)
    srv.start()
    try:
        status, headers, body = _http(
            srv.port, "POST", "/api/command", b'{"robot":"r1"}',
            extra="Authorization: Bearer tok-123\r\n")
        assert status == 202
        assert json.loads(body.decode("utf-8")) == {"accepted": True}
        assert seen["path"] == "/api/command"
        assert json.loads(seen["body"].decode("utf-8")) == {"robot": "r1"}
        assert seen["auth"] == "Bearer tok-123"
        # 훅이 걸렸을 때만 POST 와 Authorization 을 알린다.
        assert "POST" in headers["Access-Control-Allow-Methods"]
        assert "Authorization" in headers["Access-Control-Allow-Headers"]
    finally:
        srv.stop()


def test_a_body_larger_than_the_cap_is_refused_rather_than_buffered():
    """상한이 없으면 포트 하나로 메모리를 말릴 수 있다. 픽셀은 이 계약으로
    오지 않는다(AI-C-08)."""
    srv = WsHttpServer("127.0.0.1", 0, on_message=lambda *a: None,
                       http_post=lambda *a: (202, "application/json", b"{}"))
    srv.start()
    try:
        import socket as _socket

        sock = _socket.create_connection(("127.0.0.1", srv.port), timeout=5)
        try:
            # 본문을 **보내지 않고** 큰 길이만 알린다 — 서버가 읽기 전에 끊어야 한다.
            sock.sendall(
                f"POST /api/command HTTP/1.1\r\nHost: x\r\n"
                f"Content-Length: {srv.MAX_BODY + 1}\r\n"
                "Connection: close\r\n\r\n".encode("latin-1"))
            raw = sock.recv(65536)
        finally:
            sock.close()
        assert b"413" in raw.split(b"\r\n")[0]
        assert b'"body_too_large"' in raw
    finally:
        srv.stop()


def test_a_read_only_server_does_not_advertise_post():
    srv = WsHttpServer("127.0.0.1", 0, on_message=lambda *a: None,
                       http_get=lambda path, headers=None:
                           (200, "application/json", b"{}"))
    srv.start()
    try:
        _status, headers, _body = _http(srv.port, "GET", "/x")
        assert "POST" not in headers["Access-Control-Allow-Methods"]
        assert "Authorization" not in headers["Access-Control-Allow-Headers"]
        # 판을 적지 않은 자리는 노출할 것도 없다 — 빈 목록을 보내지 않는다.
        assert "Access-Control-Expose-Headers" not in headers
    finally:
        srv.stop()
