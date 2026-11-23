"""방식 B 프레이밍 — 왕복 · 헤더 검증(양성/음성) · 헤더 길이 상한 · 순번 기록 · camera_id 대조 · 중복 ingest.

소켓 없이 패킷 배열만으로 돈다(`backend/gateway/media.py`는 소켓을 모른다). **음성 대조가 본체다** —
헤더 필수 누락·타입 오류·과대 헤더·JSON 아님은 `FrameRejected(stage)`로 막히고, 모르는 `encoding`은
막히지 않으며(M5), 순번 역전·불연속은 기록만 하고 거부하지 않는다.

헤더는 v2(통합데이터규약 §3-5 — 평평한 프레임 헤더)가 기본이다. **과도기 v1 헤더(`frame_ref` 묶음)도 받는지**를
맨 아래 「v1/v2 둘 다 받기」 절이 본다(BE-07 — 단계 5 에서 v1 갈래와 함께 지운다).

implements: BE-T-07 (방식 B 프레이밍·헤더 검증), BE-C-03 (번호·시각 바이트 무개정)
tests: 왕복 · 페이로드 불개봉 · 음성 5(header 4 + schema 1) · av1 통과 · JPEG keyframe 생략 · 순번 기록 · camera_id 불일치 거부
       · 4409 규칙 · v1/v2 같은 값 · frame_ref 도 camera_id 도 없으면 거부
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from backend.gateway import media

EXAMPLES = Path(__file__).resolve().parents[1] / "contracts" / "common" / "examples"

HEADER = {      # v2 프레임 헤더(§3-5)
    "schema_version": "2.0", "source_id": "go1-001", "node_id": "hw-edge", "zone_id": "zoneA",
    "timestamp": "2026-09-18T12:00:00.123+09:00", "sequence_id": 7, "session_id": "a1b2c3d4e5f6",
    "camera_id": "go1-001_front",
    "encoding": "h264", "keyframe": True, "width": 464, "height": 400, "codec": "avc1.42E01E",
}
HEADER_V1 = {   # 옛 헤더(과도기) — 같은 프레임
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
    assert frame.keyframe is True and frame.camera_id == "go1-001_front" and frame.sequence_id == 7
    assert frame.is_v1 is False
    (declared_len,) = struct.unpack_from(">I", blob, 0)
    assert declared_len == len(blob) - 4 - len(PAYLOAD)


def test_frame_ref_bytes_survive_relay_path() -> None:
    """서버는 번호·시각을 재생성하지 않는다 — 헤더 JSON 바이트가 raw 안에 원문 그대로 있다(M6 의 단위판)."""
    blob = media.encode_frame(HEADER, PAYLOAD)
    frame = media.decode_frame(blob)
    header_bytes = blob[4:4 + struct.unpack_from(">I", blob, 0)[0]]
    assert header_bytes == json.dumps(HEADER, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    for key in ("camera_id", "sequence_id", "timestamp"):
        assert json.dumps({key: HEADER[key]}, ensure_ascii=False, separators=(",", ":"))[1:-1].encode("utf-8") in header_bytes
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
        ({"timestamp": "2026-09-18T12:00:00+0900"}, "timestamp: '2026-09-18T12:00:00+0900' is not a 'date-time'"),
        ({"camera_id": media.Frame}, "'camera_id' is a required property"),
        ({"keyframe": media.Frame}, "'keyframe' is a required property"),        # H.264 는 keyframe 필수(if/then)
        ({"codec": media.Frame}, "'codec' is a required property"),              # H.264 는 codec 필수(if/then)
        ({"session_id": media.Frame}, "'session_id' is a required property"),    # 공통 머리
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


def test_jpeg_header_without_keyframe_is_keyframe() -> None:
    """v2 JPEG 헤더는 keyframe·codec 을 싣지 않는다 — 서버는 키프레임으로 본다(drop-old 첫 전송 조건)."""
    frame = media.decode_frame(media.encode_frame(_header(encoding="jpeg", keyframe=media.Frame, codec=media.Frame), PAYLOAD))
    assert frame.keyframe is True
    # 싣는다면 그 값을 쓴다(늘 true 겠지만 규격이 막지 않는다).
    frame = media.decode_frame(media.encode_frame(_header(encoding="jpeg", keyframe=False, codec=media.Frame), PAYLOAD))
    assert frame.keyframe is False


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


# ── Relay: camera_id 대조 · 중복 ingest ─────────────────────────────────────


def test_relay_rejects_camera_id_mismatch() -> None:
    relay = media.Relay()
    frame = media.decode_frame(media.encode_frame(HEADER, PAYLOAD))
    relay.check_source("go1-001_front", frame)           # 같으면 통과
    with pytest.raises(media.FrameRejected) as exc:
        relay.check_source("cctv-zoneA-03", frame)
    assert exc.value.stage == "schema" and "다르다" in exc.value.reason


def test_relay_duplicate_ingest_second_is_refused() -> None:
    """같은 camera_id 로 엣지가 둘 붙으면 나중 것을 거부(4409 규칙). 첫 것이 떠나면 다시 붙을 수 있다."""
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
    f10 = media.decode_frame(media.encode_frame(_header(camera_id="s", sequence_id=10), PAYLOAD))
    f0 = media.decode_frame(media.encode_frame(_header(camera_id="s", sequence_id=0), PAYLOAD))
    assert relay.note_sequence("s", f10) is None
    relay.release_ingest("s", owner)
    relay.claim_ingest("s", owner)
    assert relay.note_sequence("s", f0) is None, "재접속 뒤 순번 0 은 역전이 아니다 — 추적기가 리셋된다"


def test_parse_frames_helper() -> None:
    blobs = [media.encode_frame(_header(sequence_id=i), PAYLOAD) for i in range(3)]
    frames = media.parse_frames(blobs)
    assert [f.sequence_id for f in frames] == [0, 1, 2]


# ── v1/v2 둘 다 받기 (BE-07 과도기 — 단계 5 에서 v1 갈래와 함께 지운다) ──────────


def _example(name: str):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def test_v1_and_v2_headers_give_same_values() -> None:
    """같은 프레임을 v1 헤더와 v2 헤더로 각각 넣으면 둘 다 통과하고 camera_id·sequence_id·keyframe 이 같다."""
    v1 = media.decode_frame(media.encode_frame(HEADER_V1, PAYLOAD))
    v2 = media.decode_frame(media.encode_frame(HEADER, PAYLOAD))
    assert (v1.is_v1, v2.is_v1) == (True, False)
    assert (v1.camera_id, v1.sequence_id, v1.keyframe) == (v2.camera_id, v2.sequence_id, v2.keyframe) == ("go1-001_front", 7, True)
    relay = media.Relay()
    relay.check_source("go1-001_front", v1)               # 입구 대조도 두 판에서 같다
    relay.check_source("go1-001_front", v2)
    with pytest.raises(media.FrameRejected):
        relay.check_source("go1-001_rear", v1)


def test_v1_and_v2_contract_examples_decode() -> None:
    """규격 예제 두 판(`media-header-v1-valid.json` · `media-header-valid.json`)이 decode_frame 을 통과한다."""
    v1 = media.decode_frame(media.encode_frame(_example("media-header-v1-valid.json"), PAYLOAD))
    v2 = media.decode_frame(media.encode_frame(_example("media-header-valid.json"), PAYLOAD))
    assert v1.is_v1 and not v2.is_v1
    assert v1.camera_id == v2.camera_id
    assert isinstance(v1.sequence_id, int) and isinstance(v2.sequence_id, int)
    assert v1.keyframe is True and v2.keyframe is True


def test_v1_header_checked_by_v1_schema_even_if_v2_validator_given() -> None:
    """게이트웨이처럼 v2 검증기를 넘겨도, 헤더에 frame_ref 가 있으면 v1 검증기로 검사한다(옛 엣지가 끊기지 않게)."""
    v2_validator = media.header_validator()
    frame = media.decode_frame(media.encode_frame(HEADER_V1, PAYLOAD), validator=v2_validator)
    assert frame.is_v1 and frame.camera_id == "go1-001_front"
    frame = media.decode_frame(media.encode_frame(HEADER_V1, PAYLOAD), validator=v2_validator,
                               validator_v1=media.header_validator(v1=True))
    assert frame.sequence_id == 7


@pytest.mark.parametrize(
    "header, expect",
    [
        (dict(HEADER_V1, frame_ref={"source_id": "go1-001_front", "capture_timestamp": "2026-09-18T12:00:00+0900",
                                    "sequence_id": 7}),
         "capture_timestamp: '2026-09-18T12:00:00+0900' is not a 'date-time'"),
        (dict(HEADER_V1, frame_ref=dict(HEADER_V1["frame_ref"], rotation_deg=90)), "Additional properties"),   # v1 은 frame_id 는 허용(선택 칸)
        (dict(HEADER_V1, frame_ref={"camera_id": "go1-001_front", "sequence_id": 7,
                                    "timestamp": "2026-09-18T12:00:00.123+09:00"}), "'source_id' is a required property"),
    ],
)
def test_v1_header_negatives(header, expect) -> None:
    """v1 헤더도 v1 규격대로 막힌다 — 과도기라고 느슨하게 받지 않는다. v2 frame_ref 모양을 v1 헤더에 넣어도 거부."""
    with pytest.raises(media.FrameRejected) as exc:
        media.decode_frame(media.encode_frame(header, PAYLOAD))
    assert exc.value.stage == "schema"
    assert expect in exc.value.reason


def test_header_without_frame_ref_or_camera_id_rejected() -> None:
    """frame_ref 도 맨 위 camera_id 도 없는 헤더는 `stage=schema` 로 거부된다(v2 규격으로 검사 — camera_id 필수)."""
    h = {k: v for k, v in HEADER.items() if k != "camera_id"}
    with pytest.raises(media.FrameRejected) as exc:
        media.decode_frame(media.encode_frame(h, PAYLOAD))
    assert exc.value.stage == "schema" and "'camera_id' is a required property" in exc.value.reason
    h1 = {k: v for k, v in HEADER_V1.items() if k != "frame_ref"}       # 옛 헤더에서 frame_ref 만 빠진 것
    with pytest.raises(media.FrameRejected) as exc:
        media.decode_frame(media.encode_frame(h1, PAYLOAD))
    assert exc.value.stage == "schema" and "camera_id" in exc.value.reason
