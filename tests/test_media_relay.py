"""미디어 중계 관통 — 실제 소켓: 송신 fixture → 서버 `/ingest`(8766) → `/media`(8765) 도착.

**서버에서 돈다**(상주 3개 systemd + 8766 도달). 컴퓨터·되돌린 뒤(단계 8, 8766 닫힘)에는 `ingest_url`
fixture 가 이 파일만 skip 한다. **게이트웨이를 pytest 안에서 띄우지 않는다** — `ws_echo.serve()`는 Kafka
소비 스레드와 SIGTERM 핸들러를 함께 걸어 컨슈머 그룹 오프셋 오염·시그널 충돌이 따라온다.

판정은 전부 pytest 의 WS 클라이언트로 한다(서버에 브라우저가 없다). 뷰어가 **먼저** 붙고 발행이 나중이다
(뷰어가 없으면 서버가 버리는 것이 정상이다).

음성 대조(지시서 §5 단계 4):
- M1 토큰 없는 접속 → 4401 + 프레임 0장 (서버 토큰이 비어 있으면 loopback 무토큰 모드라 skip)
- M2 헤더 필수 누락·타입 오류 → 뷰어에 안 나감 (+ `be_gateway_media_rejected{stage}` 증가는 관측 테스트)
- M3 드롭은 GOP 경계에서만 — 느린 뷰어에서 드롭 뒤 첫 전송이 keyframe
- M4 `/media`를 끊어도 `/state`가 Kafka 메시지를 계속 받는다
- M5 모르는 `encoding`(`av1`)이 통과한다
- M6 서버가 frame_ref 를 재생성하지 않는다 — 송신 원본과 도착분 **바이트 동일**
- M7 영상이 상태를 밀지 않는다 — 느린 뷰어 드롭 중에도 `/state` 도착 지연이 늘지 않는다
- M8 JPEG 에서도 지연 바운드가 같은 기준 — 게이트웨이 종료 로그(Loki)의 `max_buffered` 가 `T_drop`+한 장 이내이고
  `t_hard == t_drop`(GOP 없음)이다. 클라이언트는 TCP 버퍼 너머의 서버 큐를 볼 수 없어 관측 평면으로 판정한다
  (느린 뷰어 fixture: 수신 버퍼 32KB + `max_queue=1` + 「한 장 뒤 정지 → 소진」. 서버는 `/media` 소켓 `SO_SNDBUF` 를
  128KB 로 못 박아 커널이 정지분을 삼키지 못하게 한다 — 사용자 결정 A, 2026-09-19)
- M9 과대 프레임이 연결을 끊지 않는다 — 프레임만 버려지고 그 뒤 프레임이 온다
- 27-c 헤더 `frame_ref.source_id` ≠ 쿼리 `source_id` → 거부 · 같은 `source_id` 중복 ingest → 4409
- DoD 4-3 관측 평면으로 판정 — `be_gateway_media_frames{outcome="sent"}`·`media_ingress` 차분 증가, 멈추면 더 안 는다

implements: BE-T-07 (미디어 뷰어 중계), BE-C-03 (frame_ref 관통), BE-T-03 (경로 분리·토큰)
tests: 위 M1~M9 + 27-c + 4-3
"""

from __future__ import annotations

import asyncio
import json
import re
import socket
import statistics
import time
import urllib.parse
import uuid
from typing import Any, Dict, List, Optional

import pytest

import media_publisher as mp
import publisher
from obs_query import counter_delta, prom_scalar, wait_until

from backend import settings
from backend.gateway import media

try:
    from websockets.asyncio.client import connect as ws_connect
except ImportError:  # pragma: no cover — websockets 12 이하
    from websockets import connect as ws_connect  # type: ignore[attr-defined]
from websockets.exceptions import ConnectionClosed

pytestmark = pytest.mark.usefixtures("ingest_url")


def _sid(prefix: str = "mrt") -> str:
    return "{}-{}".format(prefix, uuid.uuid4().hex[:8])


def _media_url(source_id: str) -> str:
    return settings.ws_media_url(source_id)


def _ingest(source_id: str) -> str:
    return settings.media_ingest_url(source_id)


SLOW_RCVBUF = 32 * 1024   # 느린 뷰어의 커널 수신 버퍼 — loopback 이 수 MB 를 삼켜 드롭을 가리는 것을 막는다


def _small_socket(port: int) -> socket.socket:
    """수신 버퍼를 못 박은 loopback 소켓. `websockets.connect(sock=…)` 에 넘긴다(주소는 소켓이 들고 있다)."""
    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, SLOW_RCVBUF)
    sock.setblocking(False)
    return sock


async def _viewer(source_id: str, *, count: Optional[int] = None, duration_s: Optional[float] = None,
                  per_message_delay: float = 0.0, stall_after: Optional[int] = None, stall_s: float = 0.0,
                  slow: bool = False, opened: Optional[asyncio.Event] = None,
                  stop: Optional[asyncio.Event] = None) -> List[bytes]:
    """`/media` 뷰어. `count` 장 받거나 `duration_s` 지나거나 `stop` 이 켜지면 끝.

    느린 뷰어(3-3) 두 가지:
    - `per_message_delay` — 장마다 잔다(지속 백프레셔, M7 용).
    - `stall_after`/`stall_s` — `stall_after` 장 받은 뒤 `stall_s` 초 정지했다가 **빠르게** 소진한다. 정지 중 서버가
      버린 것이 소진 뒤 순번 불연속으로 드러난다(커널 버퍼에 가려지지 않는다).
    `slow=True` 면 수신 버퍼 32KB + `max_queue=1` 로 클라이언트 쪽 흡수를 최소화한다.
    """
    got: List[bytes] = []
    deadline = time.monotonic() + duration_s if duration_s else None
    kwargs: Dict[str, Any] = {"open_timeout": 10, "max_size": None, "compression": None}
    if slow:
        kwargs["sock"] = _small_socket(settings.ws_port())
        kwargs["max_queue"] = 1
    async with ws_connect(_media_url(source_id), **kwargs) as ws:
        if opened is not None:
            await asyncio.sleep(0.2)     # handshake 완료 → 서버 핸들러의 슬롯 등록 사이 미세 경쟁 여유(뷰어가 먼저 붙어야 한다)
            opened.set()
        while True:
            if count is not None and len(got) >= count:
                break
            if stop is not None and stop.is_set():
                break
            remaining = (deadline - time.monotonic()) if deadline else 15.0
            if remaining <= 0:
                break
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 15.0))
            except asyncio.TimeoutError:
                if deadline is None:
                    break
                continue
            if isinstance(msg, str):
                continue
            got.append(msg)
            if per_message_delay:
                await asyncio.sleep(per_message_delay)
            if stall_after is not None and len(got) == stall_after and stall_s > 0:
                await asyncio.sleep(stall_s)
    return got


def _frames_of(blobs: List[bytes]) -> List[media.Frame]:
    return [media.decode_frame(b) for b in blobs]


# ── 양성: 관통 · 첫 전송 keyframe · 바이트 동일 (DoD 3-1·3-2·2-3 · M6) ─────


def test_fast_viewer_receives_every_au_bytes_identical() -> None:
    sid = _sid()
    opened = asyncio.Event()

    async def run():
        viewer = asyncio.create_task(_viewer(sid, count=40, opened=opened))
        await asyncio.wait_for(opened.wait(), 10)
        sent = await mp.publish(_ingest(sid), mp.iter_frames("h264", source_id=sid, width=464, height=400, loop=False), fps=60, count=40)
        got = await asyncio.wait_for(viewer, 20)
        return sent, got

    sent, got = asyncio.run(run())
    assert len(sent) == 40
    assert len(got) == 40, "빠른 뷰어(loopback)인데 보낸 AU 수와 받은 수가 다르다: {} vs {}".format(len(sent), len(got))
    assert media.decode_frame(got[0]).keyframe is True, "새 뷰어의 첫 전송이 keyframe 이 아니다"
    assert got == [s.blob for s in sent], "도착분이 송신 원본과 바이트 단위로 다르다 — 서버가 재직렬화·재생성했다"
    for s, g in zip(sent, got):
        assert media.decode_frame(g).header["frame_ref"] == s.header["frame_ref"]


# ── M1: 토큰 ────────────────────────────────────────────────────────────────


async def _expect_close(url: str) -> Optional[int]:
    try:
        async with ws_connect(url, open_timeout=10) as ws:
            await asyncio.wait_for(ws.recv(), 5)
    except ConnectionClosed as exc:
        return exc.rcvd.code if exc.rcvd else None
    except asyncio.TimeoutError:
        return -1
    return None


def test_no_token_viewer_closed_4401_no_frames() -> None:
    if not settings.ws_token():
        pytest.skip("MK2_WS_TOKEN 이 비어 있다 — loopback 무토큰 모드에서는 M1 을 판정할 수 없다")
    sid = _sid()
    code = asyncio.run(_expect_close("ws://127.0.0.1:{}/media?source_id={}".format(settings.ws_port(), sid)))
    assert code == 4401, code
    code = asyncio.run(_expect_close("ws://127.0.0.1:{}/media?source_id={}&token=wrong".format(settings.ws_port(), sid)))
    assert code == 4401, code
    code = asyncio.run(_expect_close("ws://127.0.0.1:{}/state".format(settings.ws_port())))
    assert code == 4401, code


def test_no_token_edge_closed_4401() -> None:
    if not settings.edge_token():
        pytest.skip("MK2_EDGE_TOKEN 이 비어 있다 — loopback 무토큰 모드")
    sid = _sid()
    base = settings.media_ingest_url(sid).split("&token=")[0].split("?token=")[0]
    code = asyncio.run(_expect_close(base))
    assert code == 4401, code
    code = asyncio.run(_expect_close(base + "&token=wrong"))
    assert code == 4401, code


# ── M2 · 27-c · M5 · M9: 헤더 거부는 뷰어에 안 나가고, 연결은 산다 ─────────


def _raw_header(sid: str, seq: int, **changes: Any) -> Dict[str, Any]:
    h = mp.make_header(sid, seq, encoding="h264", keyframe=True, width=464, height=400, codec="avc1.42E01E")
    for k, v in changes.items():
        if v is None and k in ("encoding",):
            h.pop(k, None)
        else:
            h[k] = v
    return h


def test_bad_headers_not_forwarded_and_unknown_encoding_passes() -> None:
    sid = _sid()
    opened = asyncio.Event()
    au = mp.load_access_units()[0].data

    async def run():
        viewer = asyncio.create_task(_viewer(sid, count=2, opened=opened))
        await asyncio.wait_for(opened.wait(), 10)
        async with ws_connect(_ingest(sid), open_timeout=10, max_size=None, compression=None) as edge:
            await edge.send(media.encode_frame(_raw_header(sid, 0, encoding=None), au))             # M2 필수 누락
            await edge.send(media.encode_frame(_raw_header(sid, 1, keyframe="true"), au))           # M2 타입 오류
            other = _raw_header(sid, 2); other["frame_ref"]["source_id"] = "someone-else"
            await edge.send(media.encode_frame(other, au))                                          # 27-c source_id 불일치
            await edge.send(media.encode_frame(_raw_header(sid, 3), au))                            # 정상
            await edge.send(media.encode_frame(_raw_header(sid, 4, encoding="av1", codec=None), au)) # M5 모르는 encoding
            await asyncio.sleep(0.3)
            await edge.send(media.encode_frame(_raw_header(sid, 5), b"still-open"))                 # 연결이 살아 있다
        return await asyncio.wait_for(viewer, 15)

    got = _frames_of(asyncio.run(run()))
    assert [f.sequence_id for f in got] == [3, 4], [f.sequence_id for f in got]
    assert got[1].header["encoding"] == "av1"


def test_oversize_frame_dropped_but_connection_alive() -> None:
    """M9: `MK2_MEDIA_MAX_FRAME_BYTES` 를 넘는 프레임은 버려지고 기록되며, 엣지 연결은 그대로다(close 1009 아님)."""
    sid = _sid()
    opened = asyncio.Event()
    limit = settings.media_max_frame_bytes()

    async def run():
        viewer = asyncio.create_task(_viewer(sid, count=2, opened=opened))
        await asyncio.wait_for(opened.wait(), 10)
        async with ws_connect(_ingest(sid), open_timeout=10, max_size=None, compression=None) as edge:
            await edge.send(media.encode_frame(_raw_header(sid, 0), b"a" * 100))
            await edge.send(media.encode_frame(_raw_header(sid, 1), b"z" * (limit + 1)))   # 과대
            await edge.send(media.encode_frame(_raw_header(sid, 2), b"b" * 100))
            await asyncio.sleep(0.5)
            assert edge.state.name == "OPEN", "과대 프레임 뒤 엣지 연결이 닫혔다: {}".format(edge.state)
        return await asyncio.wait_for(viewer, 20)

    got = _frames_of(asyncio.run(run()))
    assert [f.sequence_id for f in got] == [0, 2], [f.sequence_id for f in got]


def test_duplicate_ingest_second_closed_4409() -> None:
    sid = _sid()

    async def run():
        async with ws_connect(_ingest(sid), open_timeout=10, compression=None) as first:
            code = await _expect_close(_ingest(sid))
            assert first.state.name == "OPEN"
            return code

    assert asyncio.run(run()) == 4409


# ── M3 · 3-3: 느린 뷰어 — 드롭이 실제로 나고, 드롭 뒤 첫 전송은 keyframe ────


def _stream_with_stall(sid: str, encoding: str, fps: float, seconds: float, stall_s: float):
    """뷰어(수신 버퍼 32KB)가 첫 장을 받은 뒤 `stall_s` 초 정지 → 그동안 서버가 버린다 → 정지 뒤 빠르게 소진."""
    async def run():
        opened, stop = asyncio.Event(), asyncio.Event()
        viewer = asyncio.create_task(_viewer(sid, duration_s=seconds + stall_s + 5, stall_after=1, stall_s=stall_s,
                                             slow=True, opened=opened, stop=stop))
        await asyncio.wait_for(opened.wait(), 10)
        frames = mp.iter_frames(encoding, source_id=sid, width=464, height=400, loop=True)
        pub_stop = asyncio.Event()
        pub = asyncio.create_task(mp.publish(_ingest(sid), frames, fps=fps, stop=pub_stop))
        await asyncio.sleep(seconds)
        pub_stop.set()
        sent = await asyncio.wait_for(pub, 15)
        await asyncio.sleep(2.0)                                   # 정지 뒤 소진 시간
        stop.set()
        got = await asyncio.wait_for(viewer, 40)
        return sent, got
    return run


def _check_gaps_resume_on_keyframe(sent, got) -> List[int]:
    frames = _frames_of(got)
    seqs = [f.sequence_id for f in frames]
    assert len(got) < len(sent), "느린 뷰어인데 드롭이 없다 (sent={} got={})".format(len(sent), len(got))
    gaps = [(a, b) for a, b in zip(seqs, seqs[1:]) if b != a + 1]
    assert gaps, "순번 불연속(드롭)이 없다: {}".format(seqs)
    assert all(b > a for a, b in zip(seqs, seqs[1:])), "역전이 있다 — 순서가 깨졌다"
    assert frames[0].keyframe, "첫 전송이 keyframe 이 아니다"
    after_gap = [frames[i + 1] for i, (a, b) in enumerate(zip(seqs, seqs[1:])) if b != a + 1]
    assert all(f.keyframe for f in after_gap), "드롭 뒤 첫 전송이 P프레임이다(GOP 경계가 아닌 곳에서 재개): {}".format(seqs)
    sent_by_seq = {s.header["frame_ref"]["sequence_id"]: s.blob for s in sent}
    assert all(sent_by_seq.get(q) == g for q, g in zip(seqs, got)), "도착분이 송신 원본 바이트와 다르다"
    return seqs


def test_slow_viewer_drops_and_resumes_on_keyframe() -> None:
    """M3 · 3-3: H.264 30fps, 뷰어 5초 정지 → 드롭이 나고 재개는 keyframe(IDR) 에서만."""
    sid = _sid()
    sent, got = asyncio.run(_stream_with_stall(sid, "h264", fps=30, seconds=8, stall_s=5.0)())
    assert len(sent) > 150
    _check_gaps_resume_on_keyframe(sent, got)


def _loki_media_close_line(loki_url: str, sid: str, timeout_s: float) -> Optional[str]:
    """게이트웨이의 `/media 종료 source_id=<sid> …` 로그 한 줄을 Loki 에서 찾는다(start·end 필수 — 제약 31)."""
    from obs_query import http_get_json

    def query() -> Optional[str]:
        now_ns = time.time_ns()
        params = {"query": '{service_name="be-gateway"} |= "/media 종료 source_id=' + sid + '"',
                  "start": str(now_ns - 10 * 60 * 10**9), "end": str(now_ns), "limit": "5"}
        data = http_get_json(loki_url + "/loki/api/v1/query_range?" + urllib.parse.urlencode(params))
        for stream in data.get("data", {}).get("result", []):
            for _, text in stream.get("values", []):
                if "max_buffered=" in text:
                    return text
        return None

    found: Dict[str, Optional[str]] = {"line": None}
    wait_until(lambda: (found.__setitem__("line", query()) or found["line"] is not None), timeout_s, interval=3.0)
    return found["line"]


def test_jpeg_slow_viewer_queue_bounded_by_t_drop(loki_url, observe_timeout_s) -> None:
    """M8: JPEG(전부 keyframe) 느린 뷰어에서 서버 큐 최대치가 `T_drop` 근처에 머물고 `T_hard == T_drop` 이다(4× 아님).

    클라이언트는 TCP 버퍼 너머의 서버 큐를 볼 수 없으므로, 게이트웨이가 뷰어 종료 때 남기는 회계 로그
    (`max_buffered`·그 시점 `t_drop_at_max`·`t_hard_at_max`·`gop_seen`)를 Loki 에서 읽어 판정한다(관측 평면).
    """
    sid = _sid()
    sent, got = asyncio.run(_stream_with_stall(sid, "jpeg", fps=15, seconds=8, stall_s=4.0)())
    assert len(sent) > 80
    _check_gaps_resume_on_keyframe(sent, got)          # JPEG 는 모든 프레임이 keyframe — 재개가 즉시다
    line = _loki_media_close_line(loki_url, sid, observe_timeout_s)
    assert line, "게이트웨이 /media 종료 로그를 Loki 에서 찾지 못했다(source_id={})".format(sid)
    m = {k: v for k, v in re.findall(r"(\w+)=([^\s]+)", line)}
    max_buffered, t_drop, t_hard, max_frame = int(m["max_buffered"]), float(m["t_drop_at_max"]), float(m["t_hard_at_max"]), int(m["max_frame"])
    assert m["gop_seen"] == "False", line
    assert t_hard == t_drop, "GOP 없는 스트림인데 T_hard ≠ T_drop: {}".format(line)
    assert max_buffered <= t_drop + max_frame, "큐 최대치가 T_drop 을 넘었다(경계 프레임 한 장 허용): {}".format(line)
    assert max_buffered < 4 * t_drop, "큐가 4×T_drop 까지 찼다: {}".format(line)


# ── M4 · M7: 상태 채널은 영상과 독립이다 ───────────────────────────────────


async def _state_roundtrip(broker: dict, timeout_s: float) -> float:
    """`/state` 에 붙어 MQTT state 1건을 발행하고 도착까지 걸린 초. 못 받으면 예외."""
    source_id = publisher.unique_source_id()
    payload = publisher.make_state_message(source_id=source_id, sequence_id=1)
    async with ws_connect(settings.ws_url(), open_timeout=10) as client:
        t0 = time.monotonic()
        publisher.publish(publisher.topic_for("state", eid=source_id), payload, host=broker["host"], port=broker["port"])
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            raw = await asyncio.wait_for(client.recv(), timeout=max(1.0, deadline - time.monotonic()))
            data = json.loads(raw)
            if data.get("message", {}).get("source_id") == source_id:
                return time.monotonic() - t0
    raise AssertionError("/state 로 도달하지 않았다")


def test_media_disconnect_keeps_state_flowing(broker, timeout_s) -> None:
    """M4: `/media` 를 붙였다 끊어도 `/state` 는 Kafka 메시지를 계속 받는다."""
    sid = _sid()

    async def run():
        before = await _state_roundtrip(broker, timeout_s)
        async with ws_connect(_media_url(sid), open_timeout=10) as m:
            assert m.state.name == "OPEN"
        after = await _state_roundtrip(broker, timeout_s)
        return before, after

    before, after = asyncio.run(run())
    assert before >= 0 and after >= 0


def test_state_latency_not_inflated_by_slow_media(broker, timeout_s) -> None:
    """M7: 느린 뷰어가 `/media` 에서 드롭을 내는 동안 `/state` 도착 지연이 늘지 않는다(writer 태스크 분리)."""
    sid = _sid()

    async def run():
        baseline = [await _state_roundtrip(broker, timeout_s) for _ in range(3)]
        opened = asyncio.Event()
        stop = asyncio.Event()
        viewer = asyncio.create_task(_viewer(sid, duration_s=20, per_message_delay=0.3, slow=True, opened=opened, stop=stop))
        await asyncio.wait_for(opened.wait(), 10)
        pub_stop = asyncio.Event()
        pub = asyncio.create_task(mp.publish(_ingest(sid), mp.iter_frames("h264", source_id=sid, width=464, height=400, loop=True), fps=30, stop=pub_stop))
        await asyncio.sleep(2.0)                                  # 드롭이 시작될 시간
        during = [await _state_roundtrip(broker, timeout_s) for _ in range(3)]
        pub_stop.set()
        sent = await asyncio.wait_for(pub, 15)
        stop.set()
        got = await asyncio.wait_for(viewer, 30)
        return baseline, during, len(sent), len(got)

    baseline, during, n_sent, n_got = asyncio.run(run())
    assert n_got < n_sent, "스트레스 중 드롭이 없었다 — M7 의 전제가 성립하지 않는다"
    b, d = statistics.median(baseline), statistics.median(during)
    assert d <= max(2.0, 3 * b), "영상 드롭 중 /state 지연이 늘었다: baseline={:.3f}s during={:.3f}s".format(b, d)


# ── DoD 4-3: 관측 평면으로 판정 — "떴다"가 아니라 "흐른다" ────────────────


def test_media_metrics_increase_then_stop(prometheus_url, observe_timeout_s) -> None:
    sid = _sid()
    q_sent = 'sum(be_gateway_media_frames_total{outcome="sent"})'
    q_in = 'sum(be_gateway_media_ingress_total)'
    before_sent, before_in = prom_scalar(prometheus_url, q_sent), prom_scalar(prometheus_url, q_in)
    opened = asyncio.Event()

    async def run():
        viewer = asyncio.create_task(_viewer(sid, count=60, opened=opened))
        await asyncio.wait_for(opened.wait(), 10)
        await mp.publish(_ingest(sid), mp.iter_frames("h264", source_id=sid, width=464, height=400, loop=False), fps=60, count=60)
        return await asyncio.wait_for(viewer, 20)

    got = asyncio.run(run())
    assert len(got) == 60
    ok = wait_until(
        lambda: counter_delta(before_sent, prom_scalar(prometheus_url, q_sent)) >= 60
        and counter_delta(before_in, prom_scalar(prometheus_url, q_in)) >= 60,
        observe_timeout_s,
    )
    assert ok, "be_gateway_media_frames{{outcome=sent}}·media_ingress 가 60 이상 늘지 않았다 (sent Δ={}, ingress Δ={})".format(
        counter_delta(before_sent, prom_scalar(prometheus_url, q_sent)), counter_delta(before_in, prom_scalar(prometheus_url, q_in)))
    # 멈추면 더 안 는다 — export 15s + scrape 5s 를 넘긴 두 시점의 값이 같다
    time.sleep(22)
    a = prom_scalar(prometheus_url, q_sent)
    time.sleep(22)
    b = prom_scalar(prometheus_url, q_sent)
    assert a == b, "발행을 멈췄는데 sent 가 계속 는다: {} → {}".format(a, b)


def test_rejected_metric_counts_stage(prometheus_url, observe_timeout_s) -> None:
    """M2(관측판): 헤더 거부가 `be_gateway_media_rejected_total{stage="schema"}` 로 센다."""
    sid = _sid()
    q = 'sum(be_gateway_media_rejected_total{stage="schema"})'
    before = prom_scalar(prometheus_url, q)

    async def run():
        async with ws_connect(_ingest(sid), open_timeout=10, compression=None) as edge:
            await edge.send(media.encode_frame(_raw_header(sid, 0, encoding=None), b"x"))
            await edge.send(media.encode_frame(_raw_header(sid, 1, keyframe="true"), b"x"))
            await asyncio.sleep(0.2)

    asyncio.run(run())
    assert wait_until(lambda: counter_delta(before, prom_scalar(prometheus_url, q)) >= 2, observe_timeout_s), \
        "media_rejected{stage=schema} 가 2 이상 늘지 않았다"
