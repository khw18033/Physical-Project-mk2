"""합성 엣지 송신 fixture — 홉2(엣지 → 서버 `/ingest`) 방식 B 송신기의 **참조 구현**.

실물 엣지 송신기가 아니다(Phase 3의 `edge_probe_publisher`와 같은 성격). 엣지 실물이 없어 이것이
홉2를 대신하며, HW 회신 §8은 이 파일을 홉2 송신기 규격의 참조 구현으로 가리킨다.

무엇을 하나:
- **H.264 프로파일:** Annex-B 파일(`tests/fixtures/synthetic_464x400.h264`)을 **액세스 유닛 단위로** 잘라
  AU 마다 프레임 헤더(통합데이터규약 §3-5, 데이터 규약 v2)를 만든다 — 공통 머리 일곱 칸 + `camera_id`(인자) ·
  `sequence_id`(단조 증가) · `timestamp`(**ISO 밀리초 +09:00, 부여 시각** — `iso_ms()`). `keyframe`은 **IDR 여부**
  (AU 안에 NAL 타입 5)로 채운다. H.264 라 `keyframe`·`codec` 을 꼭 싣는다.
- **JPEG 프로파일:** 커밋된 JPEG 몇 장(`synthetic_464x400_NN.jpg`)을 반복 재생, `encoding="jpeg"`.
  v2 JPEG 헤더에는 `keyframe`·`codec` 을 싣지 않는다(JPEG 는 늘 키프레임 — 서버가 그렇게 본다).
- 방식 B(`[4B 헤더길이][JSON 헤더][페이로드]`)로 인코드해 `/ingest?camera_id=…&token=…`에 보낸다.
- 같은 프레임을 가리키는 **가짜 비전 결과**(§3-6)를 JSON 파일로 남길 수 있다(`--detections-out`) —
  `frame_ref{camera_id, sequence_id, timestamp}`, `alignment:"frame"`, `producer{edge, precise}`,
  `bbox=[x1, y1, x2, y2]` 픽셀(기준 = 결과의 `width`·`height` = 프레임 헤더 크기). 뷰어 오버레이 대조 재료.
- 2026-10-13 통합데이터규약 BE-11 로 v1 헤더(`frame_ref{source_id, capture_timestamp, sequence_id}` 묶음)에서
  바꿨다. 서버가 v1 헤더도 받는지는 `tests/test_media_frame.py` 의 v1/v2 시험이 본다(단계 5 까지).
- **MQTT·Kafka에 붙지 않는다**(원칙 3 — 영상은 미디어 경로로만).

액세스 유닛 경계 규칙(지시서 3-1 — 우리가 새로 정한 것이고 HW 양끝에는 아직 없다):
- Annex-B 를 3·4바이트 시작 코드로 NAL 로 자른다(HW `go1_relay.py::split_annexb`와 같은 규칙).
- SPS(7)·PPS(8)·SEI(6)·AUD(9)는 **뒤따르는 VCL NAL 과 한 AU 로** 묶는다.
- VCL NAL(1=non-IDR, 5=IDR)을 만나면 그 AU 를 **닫는다**(이 fixture 는 프레임당 슬라이스 1개).
- `keyframe = AU 안에 타입 5 가 있는가`.
같은 규칙이 홉2 송신기 규격의 전제다 — 로봇이 한 메시지에 AU 2개를 실으면 두 규칙이 갈린다.

🔴 **번호·시각(`sequence_id`·`timestamp`)을 매기는 시점 — 「AU 경계를 확정하는 순간」이지 「보내는 순간」이 아니다.**
이 파일은 **버리지 않으므로 둘이 같은 순간**이고, 그래서 여기서는 증상이 드러나지 않는다.
**실물 엣지는 다르다** — 송신 측 drop-old 를 하므로 두 시점이 갈린다. 거기서 **전송 시점에** 매기면
버린 프레임이 순번을 소비하지 않아 **순번이 연속으로 보이고, 뷰어가 손실을 알 방법이 사라진다.**

    (HW 실측 2026-09-21) 홉2 송신기를 처음 그렇게 만들었더니 64장을 버렸는데도 서버가
    「순번 0~624 · 불연속 0회」로 봤다. 시각(옛 `capture_timestamp`)과 같은 시점으로 옮기니 불연속이 나타났다.
    HW 가 발견해 고쳤고, 그 지적으로 이 참조 구현도 같은 구조임을 확인했다.

⚠ **이 파일의 구조가 그 함정을 그대로 보여 준다** — `iter_frames()` 가 제너레이터이고 `publish()` 가
지연 소비하므로 `make_header()`(= 순번·시각 부여)가 **전송 직전**에 실행된다. 버리지 않아서 잠복해
있을 뿐이다. **이 파일을 베껴 버리기를 더하면 그 순간 함정에 빠진다** — 헤더를 먼저 만들어 두고
버릴 때도 순번을 소비해야 한다.

CLI:
    python tests/media_publisher.py --camera-id go1-001_front --encoding h264 --fps 30 --loop
    python tests/media_publisher.py --camera-id cctv-zoneA-03_main --encoding jpeg --fps 15 --count 45
    (--url 기본값 = settings.media_ingest_url(camera_id) — MK2_MEDIA_INGEST_URL·MK2_EDGE_TOKEN 을 읽는다)
    (옛 인자 이름 --source-id 도 같은 뜻으로 받는다 — 값은 카메라 키다)

implements: BE-T-07 (홉2 송신기 참조 구현 — 합성), BE-C-03 (번호·시각 부여 지점 = AU 재조립)
⚠ 이 파일은 **버리지 않는 송신기**다. 버리기를 더할 때의 순번 규율은 모듈 독스트링 🔴 를 보라
   (HW 실측 2026-09-21 로 확인된 함정).
tests: tests/test_media_relay.py 가 `publish()`를 직접 부른다 · 컴퓨터 임시 엣지(단계 7)에서 CLI 로 쓴다
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend import settings  # noqa: E402
from backend.gateway import media  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
H264_FIXTURE = FIXTURES / "synthetic_464x400.h264"
JPEG_GLOB = "synthetic_464x400_*.jpg"

# 공통 머리(통합데이터규약 §3-1) — 이 송신기 자신. 실물 엣지라면 장비·컴퓨터 이름이 들어갈 자리다.
SCHEMA_VERSION = "2.0"
DEFAULT_NODE_ID = "media-publisher"     # 이 프레임 헤더를 만든 프로그램이 도는 곳(시험 송신기)
DEFAULT_ZONE = "zoneA"
SESSION_ID = uuid.uuid4().hex[:12]      # 1회 기동 ID — sequence_id 가 다시 시작되는 경계
KST = timezone(timedelta(hours=9))

NAL_NON_IDR, NAL_IDR, NAL_SEI, NAL_SPS, NAL_PPS, NAL_AUD = 1, 5, 6, 7, 8, 9
VCL_TYPES = (NAL_NON_IDR, NAL_IDR)


# ── Annex-B → NAL → 액세스 유닛 ───────────────────────────────────────────────


def split_annexb(data: bytes) -> List[bytes]:
    """3·4바이트 시작 코드로 NAL 을 자른다. 각 항목은 **시작 코드를 포함한** 바이트(뷰어 WebCodecs 가 Annex-B 를 기대)."""
    starts: List[int] = []
    i = 0
    n = len(data)
    while i < n - 2:
        if data[i] == 0 and data[i + 1] == 0:
            if data[i + 2] == 1:
                starts.append(i)
                i += 3
                continue
            if i < n - 3 and data[i + 2] == 0 and data[i + 3] == 1:
                starts.append(i)
                i += 4
                continue
        i += 1
    nals: List[bytes] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else n
        nals.append(data[start:end])
    return nals


def nal_type(nal: bytes) -> int:
    """시작 코드 뒤 첫 바이트의 하위 5비트."""
    off = 3 if nal[:3] == b"\x00\x00\x01" else 4
    return nal[off] & 0x1F


def sps_of(nal: bytes) -> Optional[bytes]:
    return nal[(3 if nal[:3] == b"\x00\x00\x01" else 4):] if nal_type(nal) == NAL_SPS else None


def codec_string(sps: bytes) -> str:
    """RFC 6381 `avc1.PPCCLL` — SPS 의 profile_idc · constraint_set · level_idc."""
    return "avc1.{:02X}{:02X}{:02X}".format(sps[1], sps[2], sps[3])


@dataclass(frozen=True)
class AccessUnit:
    data: bytes
    keyframe: bool
    nal_types: Tuple[int, ...]


def group_access_units(nals: Sequence[bytes]) -> List[AccessUnit]:
    """SPS·PPS·SEI·AUD 는 뒤따르는 VCL 과 한 AU. VCL(1·5)을 만나면 닫는다. keyframe = 타입 5 포함."""
    units: List[AccessUnit] = []
    pending: List[bytes] = []
    types: List[int] = []
    for nal in nals:
        t = nal_type(nal)
        pending.append(nal)
        types.append(t)
        if t in VCL_TYPES:
            units.append(AccessUnit(data=b"".join(pending), keyframe=(NAL_IDR in types), nal_types=tuple(types)))
            pending, types = [], []
    # 꼬리에 VCL 없는 NAL 만 남으면 버린다(반쪽 AU 를 만들지 않는다)
    return units


def load_access_units(path: Path = H264_FIXTURE) -> List[AccessUnit]:
    return group_access_units(split_annexb(path.read_bytes()))


def count_nal_types(path: Path = H264_FIXTURE) -> Dict[int, int]:
    """생성 스크립트의 검산 — 타입별 NAL 수(SPS 가 IDR 개수만큼 나와야 한다)."""
    counts: Dict[int, int] = {}
    for nal in split_annexb(path.read_bytes()):
        t = nal_type(nal)
        counts[t] = counts.get(t, 0) + 1
    return counts


# ── 프레임 헤더(번호·시각) 부여 · 방식 B 인코드 ─────────────────────────────


def iso_ms(t: Optional[float] = None) -> str:
    """epoch 초 → '2026-10-12T14:10:31.086+09:00'(통합데이터규약 §3-1 `iso_ms` — 밀리초 3자리 · +09:00 고정)."""
    return datetime.fromtimestamp(time.time() if t is None else t, KST).isoformat(timespec="milliseconds")


def now_iso() -> str:
    """부르는 곳이 있어 이름을 남긴다 — `iso_ms()` 와 같다(전에는 로컬 오프셋 `astimezone()` 이었다)."""
    return iso_ms()


def device_of(camera_id: str) -> str:
    """카메라 키 `<장비 source_id>_<위치>`(§2-3) → 장비 source_id. 밑줄이 없으면 카메라 키 그대로."""
    return camera_id.rsplit("_", 1)[0] if "_" in camera_id else camera_id


def make_header(camera_id: str, sequence_id: int, *, encoding: str, keyframe: bool, width: int, height: int,
                codec: Optional[str], timestamp: Optional[str] = None, source_id: Optional[str] = None,
                node_id: str = DEFAULT_NODE_ID, zone_id: str = DEFAULT_ZONE,
                session_id: Optional[str] = None) -> Dict[str, Any]:
    """프레임 헤더 v2(통합데이터규약 §3-5) — 평평하다. `frame_ref` 묶음이 없다.

    H.264 는 `keyframe`·`codec` 을 꼭 싣는다. JPEG 는 둘 다 싣지 않는다(늘 키프레임 — 서버가 그렇게 본다).
    """
    header: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source_id": source_id or device_of(camera_id),
        "node_id": node_id,
        "zone_id": zone_id,
        "timestamp": timestamp or iso_ms(),
        "sequence_id": sequence_id,
        "session_id": session_id or SESSION_ID,
        "camera_id": camera_id,
        "encoding": encoding,
        "width": width,
        "height": height,
    }
    if encoding != "jpeg":
        header["keyframe"] = keyframe
        header["codec"] = codec
    return header


def header_keyframe(header: Dict[str, Any]) -> bool:
    """헤더가 키프레임인가 — `media.Frame.keyframe` 과 같은 규칙(없으면 JPEG 는 키프레임)."""
    return bool(header.get("keyframe", header.get("encoding") == "jpeg"))


def make_detections(header: Dict[str, Any]) -> Dict[str, Any]:
    """같은 프레임을 가리키는 가짜 비전 결과(통합데이터규약 §3-6) — 뷰어 오버레이 대조 재료.

    머리의 `timestamp` = 원본 프레임 시각(R12 예외 — `frame_ref.timestamp` 와 같다). 결과가 나온 순간은 `emitted_at`.
    박스는 예전 정규화 상자(x 0.30 · y 0.30 · w 0.25 · h 0.30)를 프레임 크기 픽셀 `[x1, y1, x2, y2]` 로 옮긴 것.
    """
    w, h = header["width"], header["height"]
    return {
        "schema_version": SCHEMA_VERSION,
        "source_id": "media-publisher",          # 결과를 만든 프로그램
        "node_id": header.get("node_id", DEFAULT_NODE_ID),
        "zone_id": header.get("zone_id", DEFAULT_ZONE),
        "timestamp": header["timestamp"],
        "frame_ref": {"camera_id": header["camera_id"], "sequence_id": header["sequence_id"],
                      "timestamp": header["timestamp"]},
        "emitted_at": iso_ms(),
        "producer": {"tier": "edge", "kind": "precise"},
        "alignment": "frame",
        "model": "synthetic",
        "width": w,
        "height": h,
        "detections": [{"bbox": [round(0.30 * w, 1), round(0.30 * h, 1), round(0.55 * w, 1), round(0.60 * h, 1)],
                        "label": "synthetic", "confidence": 0.5}],
    }


def iter_frames(encoding: str, *, camera_id: str, width: int, height: int, loop: bool, start_seq: int = 0,
                h264_path: Path = H264_FIXTURE, jpeg_dir: Path = FIXTURES) -> Iterator[Tuple[Dict[str, Any], bytes]]:
    """(헤더, 페이로드) 열. `loop=True` 면 파일을 되풀이하되 `sequence_id`는 계속 증가한다.

    🔴 **`make_header()` 가 `yield` 시점에 실행된다** — 즉 순번·`timestamp` 가 호출자가 이 열을
    한 칸 당기는 순간에 매겨진다. `publish()` 가 보내면서 당기므로 **사실상 전송 시점**이다.
    이 파일은 버리지 않아 순번이 연속이고 증상이 없지만, **실물 엣지가 이 모양을 베끼면 안 된다**
    (모듈 독스트링의 🔴 참조). 실물은 AU 를 재조립한 순간 헤더를 만들어 두고, **버릴 때도 그 순번을
    소비**해야 뷰어가 불연속으로 손실을 본다.
    """
    seq = start_seq
    if encoding == "h264":
        units = load_access_units(h264_path)
        if not units:
            raise RuntimeError("AU 가 없다: {}".format(h264_path))
        sps = next((sps_of(n) for u in units for n in split_annexb(u.data) if sps_of(n)), None)
        codec = codec_string(sps) if sps else None
        while True:
            for unit in units:
                yield make_header(camera_id, seq, encoding="h264", keyframe=unit.keyframe, width=width, height=height, codec=codec), unit.data
                seq += 1
            if not loop:
                return
    elif encoding == "jpeg":
        files = sorted(jpeg_dir.glob(JPEG_GLOB))
        if not files:
            raise RuntimeError("JPEG fixture 가 없다: {}/{}".format(jpeg_dir, JPEG_GLOB))
        images = [p.read_bytes() for p in files]
        while True:
            for img in images:
                yield make_header(camera_id, seq, encoding="jpeg", keyframe=True, width=width, height=height, codec=None), img
                seq += 1
            if not loop:
                return
    else:
        raise ValueError("encoding 은 h264 | jpeg: {!r}".format(encoding))


# ── 송신 ────────────────────────────────────────────────────────────────────


@dataclass
class SentFrame:
    header: Dict[str, Any]
    blob: bytes


async def publish(url: str, frames: Iterator[Tuple[Dict[str, Any], bytes]], *, fps: float, count: Optional[int] = None,
                  on_sent: Optional[Callable[[SentFrame], None]] = None, open_timeout: float = 10.0,
                  stop: Optional[asyncio.Event] = None) -> List[SentFrame]:
    """`/ingest` 에 붙어 방식 B 로 보낸다. 보낸 (헤더, 바이트) 목록을 돌려준다 — 도착분과 바이트 대조(M6)에 쓴다.

    `count` 가 있으면 그만큼 보내고 닫는다. `stop` 이벤트가 켜지면 멈춘다. 엣지 입구에서는 버리지 않으므로
    송신기는 그냥 fps 로 밀어 넣는다(버림은 서버 뷰어 슬롯 몫).

    🔴 **그래서 이 함수에는 송신 측 drop-old 가 없다** — 홉2 송신기 규격(§8-2)은 「엣지도 서버와 같은
    규칙으로 버린다」를 요구한다. 그것을 더할 때 **순번을 전송 시점에 매기지 마라**(모듈 독스트링 🔴).
    """
    try:
        from websockets.asyncio.client import connect as ws_connect
    except ImportError:  # pragma: no cover — websockets 12 이하
        from websockets import connect as ws_connect  # type: ignore[attr-defined]

    sent: List[SentFrame] = []
    interval = 1.0 / fps if fps > 0 else 0.0
    async with ws_connect(url, open_timeout=open_timeout, max_size=None, compression=None) as ws:
        next_at = time.monotonic()
        for header, payload in frames:
            if stop is not None and stop.is_set():
                break
            blob = media.encode_frame(header, payload)
            await ws.send(blob)
            record = SentFrame(header=header, blob=blob)
            sent.append(record)
            if on_sent is not None:
                on_sent(record)
            if count is not None and len(sent) >= count:
                break
            if interval:
                next_at += interval
                delay = next_at - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                else:
                    next_at = time.monotonic()
    return sent


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="합성 엣지 송신 fixture — 홉2 방식 B 참조 구현")
    parser.add_argument("--camera-id", "--source-id", dest="camera_id", default="go1-001_front",
                        help="카메라 키(`<장비>_<위치>`). 옛 이름 --source-id 도 받는다")
    parser.add_argument("--encoding", choices=("h264", "jpeg"), default="h264")
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--loop", action="store_true", help="파일 끝에서 처음으로 되돌아간다(sequence_id 는 계속 증가)")
    parser.add_argument("--count", type=int, default=None, help="이만큼 보내고 끝낸다")
    parser.add_argument("--url", default=None, help="기본 settings.media_ingest_url(camera_id)")
    parser.add_argument("--width", type=int, default=464)
    parser.add_argument("--height", type=int, default=400)
    parser.add_argument("--detections-out", type=Path, default=None, help="keyframe 마다 그 프레임을 가리키는 가짜 비전 결과를 JSONL 로")
    args = parser.parse_args(argv)

    url = args.url or settings.media_ingest_url(args.camera_id)
    frames = iter_frames(args.encoding, camera_id=args.camera_id, width=args.width, height=args.height, loop=args.loop)
    det_fp = args.detections_out.open("a", encoding="utf-8") if args.detections_out else None
    sent_count = {"n": 0, "kf": 0}

    def on_sent(rec: SentFrame) -> None:
        sent_count["n"] += 1
        if header_keyframe(rec.header):
            sent_count["kf"] += 1
            if det_fp is not None:
                det_fp.write(json.dumps(make_detections(rec.header), ensure_ascii=False) + "\n")
                det_fp.flush()
        if sent_count["n"] % 30 == 0:
            print("sent={} keyframes={} last_seq={}".format(sent_count["n"], sent_count["kf"], rec.header["sequence_id"]), flush=True)

    print("송신 시작 → {} (token 마스킹) encoding={} fps={} loop={}".format(
        url.split("token=")[0] + ("token=***" if "token=" in url else ""), args.encoding, args.fps, args.loop), flush=True)
    try:
        asyncio.run(publish(url, frames, fps=args.fps, count=args.count, on_sent=on_sent))
    except KeyboardInterrupt:
        pass
    finally:
        if det_fp is not None:
            det_fp.close()
    print("송신 끝: {} 장 (keyframe {})".format(sent_count["n"], sent_count["kf"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
