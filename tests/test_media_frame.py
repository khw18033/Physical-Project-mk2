"""방식 B 프레이밍 — 왕복 · 헤더 검증(양성/음성) · 헤더 길이 상한 · 순번 기록 · source_id 대조 · 중복 ingest.

소켓 없이 패킷 배열만으로 돈다(`backend/gateway/media.py`는 소켓을 모른다). **음성 대조가 본체다** —
헤더 필수 누락·타입 오류·과대 헤더·JSON 아님은 `FrameRejected(stage)`로 막히고, 모르는 `encoding`은
막히지 않으며(M5), 순번 역전·불연속은 기록만 하고 거부하지 않는다.

implements: BE-T-07 (방식 B 프레이밍·헤더 검증), BE-C-03 (frame_ref 바이트 무개정)
tests: 왕복 · 페이로드 불개봉 · 음성 5(header 4 + schema 1) · av1 통과 · 순번 기록 · source_id 불일치 거부 · 4409 규칙
"""

from __future__ import annotations

import json
import struct

import pytest

from backend.gateway import media

HEADER = {
    "frame_ref": {"source_id": "go1-001_front", "capture_timestamp": "2026-09-18T12:00:00.123+09:00", "sequence_id": 7},
    "encoding": "h264", "keyframe": True, "width": 464, "height": 400, "codec": "avc1.42E01E", "correlation_id": None,
}
PAYLOAD = bytes([0, 0, 0, 1, 0x67]) + b"\x00\xff" * 500   # Annex-B 흉내 — 내용은 열지 않으므로 아무 바이트여도 된다


def _header(**changes):
    h = json.loads(json.dumps(HEADER))
    for k, v in changes.items():
        if v is media.Frame:      # 삭제 표시
            h.pop(k, None)
        else:
            h[k] = v
    return h


# ── 왕복 ────────────────────────────────────────────────────────────────────


def test_roundtrip_header_and_payload_untouched() -> None:
    blob = media.encode_frame(HEADER, PAYLOAD)
    frame = media.decode_frame(blob)
    assert frame.header == HEADER
    assert frame.payload == PAYLOAD                     # 페이로드는 슬라이스만 — 바이트 동일
    assert frame.raw == blob                            # 뷰어에 나가는 것은 받은 바이트 그대로(재직렬화 없음)
    assert frame.keyframe is True and frame.source_id == "go1-001_front" and frame.sequence_id == 7
    (declared_len,) = struct.unpack_from(">I", blob, 0)
    assert declared_len == len(blob) - 4 - len(PAYLOAD)


def test_frame_ref_bytes_survive_relay_path() -> None:
    """서버는 frame_ref 를 재생성하지 않는다 — 헤더 JSON 바이트가 raw 안에 원문 그대로 있다(M6 의 단위판)."""
    blob = media.encode_frame(HEADER, PAYLOAD)
    frame = media.decode_frame(blob)
    header_bytes = blob[4:4 + struct.unpack_from(">I", blob, 0)[0]]
    assert json.dumps(HEADER["frame_ref"], ensure_ascii=False, separators=(",", ":")).encode("utf-8") in header_bytes
    assert frame.raw[4:4 + len(header_bytes)] == header_bytes


# ── 음성: header 단계 ────────────────────────────────────────────────────────


def test_reject_too_short() -> None:
    with pytest.raises(media.FrameRejected) as exc:
        media.decode_frame(b"\x00\x00")
    assert exc.value.stage == "header"


def test_reject_header_len_over_limit() -> None:
    """헤더 길이 상한(기본 64KB) — 악의적·손상 입력에 메모리를 내주지 않는다. 본문을 읽기 전에 거부한다."""
    blob = struct.pack(">I", media.DEFAULT_MAX_HEADER_BYTES + 1) + b"x" * 10
    with pytest.raises(media.FrameRejected) as exc:
        media.decode_frame(blob)
    assert exc.value.stage == "header" and "상한" in exc.value.reason
    small = media.encode_frame(HEADER, PAYLOAD)
    with pytest.raises(media.FrameRejected):
        media.decode_frame(small, max_header_bytes=10)


def test_reject_header_len_beyond_message() -> None:
    blob = struct.pack(">I", 999) + b"{}"
    with pytest.raises(media.FrameRejected) as exc:
        media.decode_frame(blob)
    assert exc.value.stage == "header"


def test_reject_non_json_and_non_object_and_text() -> None:
    bad_json = struct.pack(">I", 5) + b"{oops" + PAYLOAD
    with pytest.raises(media.FrameRejected) as exc:
        media.decode_frame(bad_json)
    assert exc.value.stage == "header"
    not_object = struct.pack(">I", 3) + b"[1]" + PAYLOAD
    with pytest.raises(media.FrameRejected) as exc:
        media.decode_frame(not_object)
    assert exc.value.stage == "header"
    with pytest.raises(media.FrameRejected) as exc:
        media.decode_frame("text frame")  # type: ignore[arg-type]
    assert exc.value.stage == "header"


# ── 음성: schema 단계 · 양성: 모르는 encoding ───────────────────────────────


@pytest.mark.parametrize(
    "changes, expect",
    [
        ({"encoding": media.Frame}, "'encoding' is a required property"),
        ({"keyframe": "true"}, "keyframe: 'true' is not of type 'boolean'"),
        ({"width": 0}, "width: 0 is less than the minimum of 1"),
        ({"frame_ref": {"source_id": "go1-001_front", "capture_timestamp": "2026-09-18T12:00:00+0900", "sequence_id": 7}},
         "capture_timestamp: '2026-09-18T12:00:00+0900' is not a 'date-time'"),
    ],
)
def test_reject_schema_violations(changes, expect) -> None:
    """M2(단위판): 필수 누락·타입 오류·+0900 은 `stage=schema` 로 거부된다."""
    blob = media.encode_frame(_header(**changes), PAYLOAD)
    with pytest.raises(media.FrameRejected) as exc:
        media.decode_frame(blob)
    assert exc.value.stage == "schema"
    assert expect in exc.value.reason


def test_unknown_encoding_passes() -> None:
    """M5: `encoding: "av1"` 은 거부되지 않는다 — 값 어휘를 보지 않는다. 헤더 바깥 추가 필드도 통과."""
    frame = media.decode_frame(media.encode_frame(_header(encoding="av1", codec=None, vendor_note="x"), PAYLOAD))
    assert frame.header["encoding"] == "av1"


# ── 순번 기록(거부 아님) ────────────────────────────────────────────────────


def test_sequence_tracker_records_but_never_rejects() -> None:
    tracker = media.SequenceTracker()
    assert tracker.observe(10) is None
    assert tracker.observe(11) is None
    note = tracker.observe(15)
    assert note and "불연속" in note and tracker.gaps == 1
    note = tracker.observe(3)            # 재접속 리셋 — 정상이며 기록만
    assert note and "역전" in note and tracker.reversals == 1
    assert tracker.observe(4) is None


# ── Relay: source_id 대조 · 중복 ingest ─────────────────────────────────────


def test_relay_rejects_source_id_mismatch() -> None:
    relay = media.Relay()
    frame = media.decode_frame(media.encode_frame(HEADER, PAYLOAD))
    relay.check_source("go1-001_front", frame)           # 같으면 통과
    with pytest.raises(media.FrameRejected) as exc:
        relay.check_source("cctv-zoneA-03", frame)
    assert exc.value.stage == "schema" and "다르다" in exc.value.reason


def test_relay_duplicate_ingest_second_is_refused() -> None:
    """같은 source_id 로 엣지가 둘 붙으면 나중 것을 거부(4409 규칙). 첫 것이 떠나면 다시 붙을 수 있다."""
    relay = media.Relay()
    first, second = object(), object()
    assert relay.claim_ingest("go1-001_front", first) is True
    assert relay.claim_ingest("go1-001_front", first) is True     # 같은 주체의 재요청은 허용
    assert relay.claim_ingest("go1-001_front", second) is False
    relay.release_ingest("go1-001_front", second)                 # 남의 것을 풀 수 없다
    assert relay.claim_ingest("go1-001_front", second) is False
    relay.release_ingest("go1-001_front", first)
    assert relay.claim_ingest("go1-001_front", second) is True


def test_relay_sequence_reset_on_reconnect() -> None:
    relay = media.Relay()
    owner = object()
    relay.claim_ingest("s", owner)
    f10 = media.decode_frame(media.encode_frame(_header(frame_ref=dict(HEADER["frame_ref"], source_id="s", sequence_id=10)), PAYLOAD))
    f0 = media.decode_frame(media.encode_frame(_header(frame_ref=dict(HEADER["frame_ref"], source_id="s", sequence_id=0)), PAYLOAD))
    assert relay.note_sequence("s", f10) is None
    relay.release_ingest("s", owner)
    relay.claim_ingest("s", owner)
    assert relay.note_sequence("s", f0) is None, "재접속 뒤 순번 0 은 역전이 아니다 — 추적기가 리셋된다"


def test_parse_frames_helper() -> None:
    blobs = [media.encode_frame(_header(frame_ref=dict(HEADER["frame_ref"], sequence_id=i)), PAYLOAD) for i in range(3)]
    frames = media.parse_frames(blobs)
    assert [f.sequence_id for f in frames] == [0, 1, 2]
