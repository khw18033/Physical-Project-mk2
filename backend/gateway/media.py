"""미디어 중계 코어 — 방식 B 프레이밍 · drop-old 상태 기계 · source_id 라우팅. **소켓을 모른다.**

미디어 경로(02-media-path §1-3-3·§1-5)의 서버 몫은 "형식을 주고 중계한다"다. 엣지가 8766 `/ingest`로
올린 방식 B 메시지를 **헤더만 읽고** 그 `source_id`를 구독 중인 뷰어(8765 `/media`)에 분기한다.
페이로드는 열지 않는다 — 디코드·재인코딩·트랜스코딩이 없다는 것이 방식 B 중계의 성립 근거다(제약 9).
`frame_ref`는 엣지가 한 번 부여한 것을 **바이트 그대로** 전파한다(원칙 10 — 서버는 재생성하지 않는다).

이 모듈이 소켓을 모르는 이유: 프레이밍·상태 기계·라우팅이 **패킷 배열만으로** 단위 검증돼야 한다
(HW `edge/media_gateway.py`가 같은 구조다). `websockets`·asyncio 큐·writer 태스크는 `ws_echo.py`가 감싼다.

## 방식 B 프레이밍 (§2-2)

    [4바이트 빅엔디언 헤더 길이][JSON 헤더(UTF-8)][페이로드 바이트]

한 메시지 = 한 프레임(H.264면 한 액세스 유닛). 헤더는 `contracts/common/media-header.schema.json`으로
**필수·타입만** 검증한다(값 어휘를 보지 않는다 — `encoding: "av1"`도 통과). 거부 사유는 셋뿐이다 —
헤더 길이 상한 초과·JSON 아님(`stage=header`), 규격 위반(`stage=schema`), 그리고 헤더의
`frame_ref.source_id`가 입구 쿼리의 `source_id`와 다름(`stage=schema`로 센다 — 둘 중 하나를 믿고 나머지를
무시하면 조용히 엉뚱한 뷰어로 간다). **순번 역전·불연속은 기록만 한다** — 재접속 시 `sequence_id`가
리셋되는 것이 규격이다.

## drop-old 상태 기계 (§2-3) — 뷰어 소켓마다 독립

    FLOWING   : keyframe=true  && buffered <= T_hard  → 보낸다
                keyframe=true  && buffered >  T_hard  → 버린다 + WAIT_IDR
                keyframe=false && buffered >  T_drop  → 버린다 + WAIT_IDR   (GOP 절단)
                keyframe=false && buffered <= T_drop  → 보낸다
    WAIT_IDR  : keyframe=false                        → 전부 버린다
                keyframe=true  && buffered <= T_hard  → 보낸다 + FLOWING
                keyframe=true  && buffered >  T_hard  → 버린다 (계속 WAIT_IDR)

- **초기 상태는 WAIT_IDR** — 새 뷰어의 첫 전송은 반드시 keyframe 이다. JPEG 는 모든 프레임이
  `keyframe=true`라 즉시 풀린다. **코드는 한 벌이다**(encoding 값으로 분기하지 않는다).
- **`buffered`는 우리가 든다** — 파이썬 `websockets`에는 브라우저의 `bufferedAmount`가 없다. 뷰어 소켓마다
  송신 큐(`ViewerSlot.pending`)를 두고 **큐에 쌓인 바이트 + 지금 writer 가 보내는 중인 바이트**를 `buffered`로
  센다. 중계 코어는 `send`를 부르지 않고 큐에 넣을지 버릴지만 판단한다. writer 가 `await send()`를 마치면
  `on_drained()`로 알려 준다. 회계에서 빠지는 것은 `websockets` 전송 버퍼(`write_limit`)와 커널 송신 버퍼
  (`SO_SNDBUF`)이므로 지연 바운드는 **`T_drop + write_limit + sndbuf`**다 — 그래서 `write_limit`을 작게(8KB) 명시하고
  `/media` 소켓의 `SO_SNDBUF`도 못 박는다(단계 2-4 + 사용자 결정 A, 2026-09-19 — `ws_echo.py`).
- **임계는 시간 기준이다.** `T_drop = drop_window(150ms) × 배출률`. 배출률은 **도착률이 아니라 배출률** —
  writer 가 실제로 비운 바이트 ÷ 경과 시간의 소켓별 EWMA(최근 60프레임 지평). 링크가 느려질 때(= drop-old 가
  필요한 바로 그때) 도착률과 배출률은 갈라지고, 도착률로 재면 임계가 실제 지연을 바운드하지 못한다.
  하한 = 최근 60프레임 AU 평균 × 2, 상한 = `buffer_max_bytes`(1MB). 표본이 모이기 전에는 하한이 지배한다.
- `T_hard = max(4 × T_drop, 최근 IDR 5개 최대 × 2)` — IDR 하나가 통째로 들어갈 여유. 🔴 **GOP 가 없는
  스트림에는 T_hard 를 적용하지 않는다** — 최근 창(60프레임)에 `keyframe=false`가 0건이면 `T_hard := T_drop`.
  모든 프레임이 독립이면 절단할 GOP 가 없고, 이 규칙이 없으면 JPEG 는 T_drop 을 한 번도 쓰지 않는다
  (15fps·25KB 기준 실효 지연 상한이 150ms 가 아니라 약 600ms 가 된다). 관측 기준이지 `encoding` 분기가 아니다.
- **GOP 절단 카운트**는 FLOWING → WAIT_IDR 전이마다 1 이다(P프레임 드롭이든 IDR 드롭이든 이후 GOP 가 통째로
  버려진다). 느린 소비자의 프레임률이 GOP 경계로 불균일해지는 것은 알려진 성질이며 이번에 고치지 않는다.
- **엣지 입구에서는 버리지 않는다.** 받아서 분기만 한다. **뷰어가 없으면 버린다.**

implements: BE-T-07 (미디어 뷰어 중계 — drop-old·채널 분리·frame_ref 관통), BE-C-03 (헤더의 frame_ref 무개정 전파)
tests: tests/test_media_frame.py (프레이밍 왕복·헤더 검증 양성/음성·길이 상한·순번 기록) ·
       tests/test_media_dropold.py (전이표 전수·T_drop/T_hard·JPEG 동일 코드·배출률 회계) ·
       tests/test_media_relay.py (실제 소켓 관통 — ws_echo 가 감싼 것)
"""

from __future__ import annotations

import json
import logging
import struct
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Set, Tuple

LOG = logging.getLogger("mk2.gateway.media")

HEADER_LEN_BYTES = 4
HEADER_LEN_STRUCT = struct.Struct(">I")          # 4바이트 빅엔디언 무부호
DEFAULT_MAX_HEADER_BYTES = 64 * 1024              # 헤더 길이 상한(§2-2) — 악의적·손상 입력에 메모리를 내주지 않는다
MEDIA_HEADER_SCHEMA = "media-header.schema.json"

# drop-old 창 크기(§2-3 "기본값이고 media.py 상수로 둔다")
AU_WINDOW = 60          # 최근 AU 평균·P프레임 유무 판정 창(프레임)
IDR_WINDOW = 5          # 최근 IDR 최대 바이트 창(개)
DRAIN_EWMA_HORIZON = 60 # 배출률 EWMA 지평(드레인 표본 수) → alpha = 2/(N+1)


# ── 방식 B 프레이밍 ──────────────────────────────────────────────────────────


class FrameRejected(Exception):
    """헤더 거부. `stage`는 관측 라벨(`header` | `schema`)과 같은 어휘다."""

    def __init__(self, stage: str, reason: str) -> None:
        super().__init__(reason)
        self.stage = stage
        self.reason = reason


@dataclass(frozen=True)
class Frame:
    """디코드된 방식 B 메시지 한 장. `raw`는 받은 바이트 그대로(뷰어에 그대로 보낸다 — 재직렬화 없음)."""

    header: Dict[str, Any]
    payload: bytes
    raw: bytes

    @property
    def keyframe(self) -> bool:
        return bool(self.header["keyframe"])

    @property
    def source_id(self) -> str:
        return self.header["frame_ref"]["source_id"]

    @property
    def sequence_id(self) -> int:
        return int(self.header["frame_ref"]["sequence_id"])

    @property
    def size(self) -> int:
        return len(self.raw)


def encode_frame(header: Dict[str, Any], payload: bytes) -> bytes:
    """방식 B 인코드 — 송신 fixture(`tests/media_publisher.py`)와 테스트가 쓴다. 서버는 부르지 않는다(재직렬화 금지)."""
    header_bytes = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return HEADER_LEN_STRUCT.pack(len(header_bytes)) + header_bytes + payload


def header_validator():
    """미디어 헤더 검증기(+$ref 레지스트리) — envelope.py 의 캐시를 쓴다(이름별 1회 생성). 게이트웨이는 기동 시 미리 만든다."""
    # 지역 import — 이 모듈은 jsonschema 를 직접 알 필요가 없다.
    from backend.ingest import envelope

    return envelope.contract_validator(MEDIA_HEADER_SCHEMA)


_default_validator = header_validator


def decode_frame(blob: bytes, *, max_header_bytes: int = DEFAULT_MAX_HEADER_BYTES,
                 validator: Any = None) -> Frame:
    """방식 B 디코드 + 헤더 검증(필수·타입만). 실패는 `FrameRejected(stage, reason)`.

    - `stage="header"`: 4바이트 미만 · 헤더 길이 상한 초과 · 헤더 길이가 본문보다 큼 · UTF-8/JSON 아님 · 객체 아님
    - `stage="schema"`: `media-header.schema.json` 위반(필수 누락·타입 오류·`frame_ref.capture_timestamp` 포맷 등)

    페이로드는 슬라이스만 하고 열지 않는다. 검증기는 한 번 만들어 재사용한다(프레임마다 새로 만들지 않는다).
    """
    if not isinstance(blob, (bytes, bytearray, memoryview)):
        raise FrameRejected("header", "바이너리 메시지가 아니다(텍스트 프레임)")
    blob = bytes(blob)
    if len(blob) < HEADER_LEN_BYTES:
        raise FrameRejected("header", "4바이트 헤더 길이조차 없다(len={})".format(len(blob)))
    (header_len,) = HEADER_LEN_STRUCT.unpack_from(blob, 0)
    if header_len > max_header_bytes:
        raise FrameRejected("header", "헤더 길이 {}가 상한 {}를 넘는다".format(header_len, max_header_bytes))
    if HEADER_LEN_BYTES + header_len > len(blob):
        raise FrameRejected("header", "헤더 길이 {}가 메시지 길이 {}를 넘는다".format(header_len, len(blob)))
    try:
        header = json.loads(blob[HEADER_LEN_BYTES:HEADER_LEN_BYTES + header_len].decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise FrameRejected("header", "헤더가 UTF-8 이 아니다: {}".format(exc)) from exc
    except json.JSONDecodeError as exc:
        raise FrameRejected("header", "헤더가 JSON 이 아니다: {}".format(exc)) from exc
    if not isinstance(header, dict):
        raise FrameRejected("header", "헤더가 JSON 객체가 아니다: {}".format(type(header).__name__))
    checker = validator if validator is not None else _default_validator()
    errors = sorted(checker.iter_errors(header), key=lambda e: list(e.absolute_path))
    if errors:
        raise FrameRejected("schema", " | ".join(
            "{}: {}".format("/".join(str(p) for p in err.absolute_path) or "(root)", err.message) for err in errors
        ))
    return Frame(header=header, payload=blob[HEADER_LEN_BYTES + header_len:], raw=blob)


# ── 순번 기록 (거부하지 않는다) ─────────────────────────────────────────────


class SequenceTracker:
    """소스 하나의 `sequence_id` 연속성. 역전·불연속을 **기록만** 한다 — 재접속 시 리셋이 정상이다."""

    def __init__(self) -> None:
        self.last: Optional[int] = None
        self.reversals = 0
        self.gaps = 0

    def observe(self, sequence_id: int) -> Optional[str]:
        """이상이 있으면 한 줄 설명을 돌려준다(호출부가 로그로 남긴다). 없으면 `None`."""
        note = None
        if self.last is not None:
            if sequence_id < self.last:
                self.reversals += 1
                note = "순번 역전(기록만): {} → {}".format(self.last, sequence_id)
            elif sequence_id > self.last + 1:
                self.gaps += 1
                note = "순번 불연속(기록만): {} → {} ({}개 건너뜀)".format(self.last, sequence_id, sequence_id - self.last - 1)
        self.last = sequence_id
        return note


# ── drop-old 상태 기계 ───────────────────────────────────────────────────────


class State(str, Enum):
    WAIT_IDR = "WAIT_IDR"
    FLOWING = "FLOWING"


class Decision(str, Enum):
    SEND = "send"
    DROP = "dropped"


@dataclass
class DropOldConfig:
    drop_window_s: float = 0.150        # MK2_MEDIA_DROP_WINDOW_MS / 1000
    buffer_max_bytes: int = 1024 * 1024 # MK2_MEDIA_BUFFER_MAX_BYTES — T_drop 상한
    au_window: int = AU_WINDOW
    idr_window: int = IDR_WINDOW
    drain_horizon: int = DRAIN_EWMA_HORIZON


class DropOldPolicy:
    """뷰어 소켓 하나의 drop-old 상태 기계 + 임계 계산. 소켓·시계를 모른다(시각은 인자로 받는다).

    입력은 셋뿐 — 프레임의 `keyframe`·`size`, 그리고 지금 `buffered`. 출력은 `Decision`과 GOP 절단 여부.
    """

    def __init__(self, config: Optional[DropOldConfig] = None) -> None:
        self.config = config or DropOldConfig()
        self.state = State.WAIT_IDR
        # 스트림 통계(도착 기준) — 창은 프레임 수
        self._au_sizes: Deque[int] = deque(maxlen=self.config.au_window)
        self._au_keyframes: Deque[bool] = deque(maxlen=self.config.au_window)
        self._idr_sizes: Deque[int] = deque(maxlen=self.config.idr_window)
        # 배출률(EWMA, bytes/s) — writer 가 실제로 비운 것만 반영
        self._drain_rate: Optional[float] = None
        self._last_drain_at: Optional[float] = None
        self._alpha = 2.0 / (self.config.drain_horizon + 1)
        self.gop_cuts = 0

    # 통계 갱신 ---------------------------------------------------------------

    def observe_arrival(self, keyframe: bool, size: int) -> None:
        """프레임이 이 소켓 앞에 도착했다(보내든 버리든). 임계 계산의 도착 측 표본."""
        self._au_sizes.append(size)
        self._au_keyframes.append(keyframe)
        if keyframe:
            self._idr_sizes.append(size)

    def on_drained(self, size: int, now: float) -> None:
        """writer 가 프레임 하나를 실제로 보냈다(`await send()` 반환). 배출률 표본."""
        if self._last_drain_at is not None:
            dt = now - self._last_drain_at
            if dt > 0:
                inst = size / dt
                self._drain_rate = inst if self._drain_rate is None else (self._alpha * inst + (1 - self._alpha) * self._drain_rate)
        self._last_drain_at = now

    # 임계 --------------------------------------------------------------------

    @property
    def drain_rate(self) -> Optional[float]:
        """완료된 드레인 표본의 EWMA(bytes/s). 정체 중인 전송은 `effective_drain_rate()`가 얹는다."""
        return self._drain_rate

    def effective_drain_rate(self, in_flight: int = 0, stalled_s: float = 0.0) -> Optional[float]:
        """지금 쓸 배출률. EWMA 에 **정체 상한**을 얹는다 — 보내는 중인 프레임(`in_flight` 바이트)이 `stalled_s`
        동안 아직 안 끝났다면 현재 배출률은 `in_flight / stalled_s` 를 넘을 수 없다.

        이것이 없으면 커널·전송 버퍼가 첫 수십 프레임을 흡수한 뒤 링크가 멈춰도, 완료된 표본만 보는 EWMA 는
        60표본(정체 시 수십 초) 동안 낡은 고속값을 유지해 T_drop 이 상한(1MB)에 붙어 버린다. 도착률이 아니라
        여전히 **배출** 기준이다 — 실제로 나가고 있는 속도의 상한을 쓰는 것이다.
        """
        rate = self._drain_rate
        if in_flight > 0 and stalled_s > 0:
            cap = in_flight / stalled_s
            rate = cap if rate is None else min(rate, cap)
        return rate

    def au_average(self) -> float:
        return (sum(self._au_sizes) / len(self._au_sizes)) if self._au_sizes else 0.0

    def has_gop(self) -> bool:
        """최근 창에 `keyframe=false`가 하나라도 있는가(관측 기준 — encoding 값이 아니다)."""
        return any(not k for k in self._au_keyframes)

    def t_drop(self, in_flight: int = 0, stalled_s: float = 0.0) -> float:
        lower = 2.0 * self.au_average()
        rate = self.effective_drain_rate(in_flight, stalled_s)
        if rate is None:
            value = lower                                  # 표본이 없을 때는 하한이 지배한다
        else:
            value = max(lower, self.config.drop_window_s * rate)
        return min(value, float(self.config.buffer_max_bytes))

    def t_hard(self, in_flight: int = 0, stalled_s: float = 0.0) -> float:
        t_drop = self.t_drop(in_flight, stalled_s)
        if not self.has_gop():
            return t_drop                                  # 절단할 GOP 가 없으면 T_hard 를 적용하지 않는다
        idr_max = max(self._idr_sizes) if self._idr_sizes else 0
        return max(4.0 * t_drop, 2.0 * idr_max)

    # 전이 --------------------------------------------------------------------

    def decide(self, keyframe: bool, size: int, buffered: int, *, in_flight: int = 0,
               stalled_s: float = 0.0) -> Tuple[Decision, bool]:
        """전이표(§2-3) 그대로. 반환 = (판정, 이번 판정이 GOP 절단인가).

        `in_flight`·`stalled_s`는 정체 상한(`effective_drain_rate`) 재료다 — `encoding` 은 받지 않는다.
        """
        self.observe_arrival(keyframe, size)
        t_drop = self.t_drop(in_flight, stalled_s)
        t_hard = self.t_hard(in_flight, stalled_s)
        gop_cut = False
        if self.state is State.FLOWING:
            if keyframe:
                if buffered <= t_hard:
                    decision = Decision.SEND
                else:
                    decision, self.state, gop_cut = Decision.DROP, State.WAIT_IDR, True
            else:
                if buffered <= t_drop:
                    decision = Decision.SEND
                else:
                    decision, self.state, gop_cut = Decision.DROP, State.WAIT_IDR, True
        else:  # WAIT_IDR
            if not keyframe:
                decision = Decision.DROP
            elif buffered <= t_hard:
                decision, self.state = Decision.SEND, State.FLOWING
            else:
                decision = Decision.DROP
        if gop_cut:
            self.gop_cuts += 1
        return decision, gop_cut


# ── 뷰어 슬롯 + 라우팅 ───────────────────────────────────────────────────────


@dataclass(eq=False)   # eq=False → 정체성 해시. 슬롯은 집합·dict 키로 쓰인다(값이 같아도 다른 뷰어다)
class ViewerSlot:
    """뷰어 소켓 하나의 큐·회계·상태 기계. `pending`은 writer 가 비우는 송신 큐(바이트 그대로)."""

    source_id: str
    policy: DropOldPolicy
    created_at: float
    pending: Deque[bytes] = field(default_factory=deque)
    buffered: int = 0                 # 큐 바이트 + 지금 보내는 중인 바이트
    in_flight: int = 0
    in_flight_since: Optional[float] = None
    sent_frames: int = 0
    dropped_frames: int = 0
    first_sent_at: Optional[float] = None
    closed: bool = False
    # 회계 최대치 — 종료 로그에 남겨 "큐가 T_drop 근처에 머물렀나"(M8)를 관측 평면(Loki)에서 판정한다
    max_buffered: int = 0
    t_drop_at_max: float = 0.0
    t_hard_at_max: float = 0.0
    max_frame: int = 0

    def offer(self, frame: Frame, now: Optional[float] = None) -> Tuple[Decision, bool]:
        """중계 코어의 유일한 진입점 — 큐에 넣을지 버릴지. `send`를 부르지 않는다.

        `now`를 주면 지금 보내는 중인 프레임의 정체 시간이 배출률 상한에 반영된다(안 주면 EWMA 만).
        """
        stalled_s = 0.0
        if now is not None and self.in_flight > 0 and self.in_flight_since is not None:
            stalled_s = max(0.0, now - self.in_flight_since)
        decision, gop_cut = self.policy.decide(frame.keyframe, frame.size, self.buffered,
                                               in_flight=self.in_flight, stalled_s=stalled_s)
        self.max_frame = max(self.max_frame, frame.size)
        if decision is Decision.SEND:
            self.pending.append(frame.raw)
            self.buffered += frame.size
            if self.buffered > self.max_buffered:
                self.max_buffered = self.buffered
                self.t_drop_at_max = self.policy.t_drop(self.in_flight, stalled_s)
                self.t_hard_at_max = self.policy.t_hard(self.in_flight, stalled_s)
        else:
            self.dropped_frames += 1
        return decision, gop_cut

    def summary(self) -> str:
        """종료 로그 한 줄(라벨이 아니라 로그 본문 — 값이 매번 달라도 된다)."""
        return ("sent={} dropped={} gop_cut={} max_buffered={} t_drop_at_max={:.0f} t_hard_at_max={:.0f} "
                "max_frame={} gop_seen={}").format(
            self.sent_frames, self.dropped_frames, self.policy.gop_cuts, self.max_buffered,
            self.t_drop_at_max, self.t_hard_at_max, self.max_frame, self.policy.has_gop())

    def take(self, now: Optional[float] = None) -> Optional[bytes]:
        """writer 가 다음에 보낼 바이트를 꺼낸다. 아직 `buffered`에서 빼지 않는다(보내는 중이다)."""
        if not self.pending:
            return None
        blob = self.pending.popleft()
        self.in_flight = len(blob)
        self.in_flight_since = now
        return blob

    def on_drained(self, size: int, now: float) -> Optional[float]:
        """writer 가 `await send()`를 마쳤다. 회계에서 빼고 배출률 표본을 준다. 첫 전송이면 콜드스타트(초)를 돌려준다."""
        self.buffered = max(0, self.buffered - size)
        self.in_flight = 0
        self.in_flight_since = None
        self.sent_frames += 1
        self.policy.on_drained(size, now)
        if self.first_sent_at is None:
            self.first_sent_at = now
            return now - self.created_at
        return None


class Relay:
    """`source_id → 뷰어 슬롯 집합` 라우팅 테이블 + 소스별 순번 기록. 소켓·스레드·시계를 모른다."""

    def __init__(self, config: Optional[DropOldConfig] = None, clock: Callable[[], float] = time.monotonic) -> None:
        self.config = config or DropOldConfig()
        self.clock = clock
        self._viewers: Dict[str, Set[ViewerSlot]] = {}
        self._sequences: Dict[str, SequenceTracker] = {}
        self._ingest_owner: Dict[str, Any] = {}   # source_id → 엣지 연결 식별자(중복 ingest 거부용)

    # 엣지 입구 --------------------------------------------------------------

    def claim_ingest(self, source_id: str, owner: Any) -> bool:
        """같은 `source_id`로 엣지가 둘 붙으면 **나중 것을 거부**한다(§2-2c, close 4409). 성공이면 True."""
        current = self._ingest_owner.get(source_id)
        if current is not None and current is not owner:
            return False
        self._ingest_owner[source_id] = owner
        self._sequences.setdefault(source_id, SequenceTracker())
        return True

    def release_ingest(self, source_id: str, owner: Any) -> None:
        if self._ingest_owner.get(source_id) is owner:
            del self._ingest_owner[source_id]
            self._sequences.pop(source_id, None)   # 재접속 시 순번이 리셋되는 것이 정상 — 이전 값을 들고 있지 않는다

    def check_source(self, expected_source_id: str, frame: Frame) -> None:
        """헤더의 `frame_ref.source_id`가 입구 쿼리의 `source_id`와 다르면 거부(`stage=schema`)."""
        if frame.source_id != expected_source_id:
            raise FrameRejected(
                "schema",
                "헤더 frame_ref.source_id={!r} 가 입구 source_id={!r} 와 다르다 — 어느 쪽도 믿지 않고 거부한다".format(
                    frame.source_id, expected_source_id),
            )

    def note_sequence(self, source_id: str, frame: Frame) -> Optional[str]:
        tracker = self._sequences.setdefault(source_id, SequenceTracker())
        return tracker.observe(frame.sequence_id)

    # 뷰어 --------------------------------------------------------------------

    def subscribe(self, source_id: str) -> ViewerSlot:
        """뷰어가 `/media?source_id=…`에 붙었다 = 켜기. 슬롯은 WAIT_IDR 로 시작한다."""
        slot = ViewerSlot(source_id=source_id, policy=DropOldPolicy(self.config), created_at=self.clock())
        self._viewers.setdefault(source_id, set()).add(slot)
        return slot

    def unsubscribe(self, slot: ViewerSlot) -> None:
        """끊는 것이 끄기. 큐를 비우고 표에서 뺀다."""
        slot.closed = True
        slot.pending.clear()
        slot.buffered = 0
        viewers = self._viewers.get(slot.source_id)
        if viewers is not None:
            viewers.discard(slot)
            if not viewers:
                del self._viewers[slot.source_id]

    def viewers_of(self, source_id: str) -> List[ViewerSlot]:
        return list(self._viewers.get(source_id, ()))

    def viewer_count(self, source_id: Optional[str] = None) -> int:
        if source_id is None:
            return sum(len(v) for v in self._viewers.values())
        return len(self._viewers.get(source_id, ()))

    def fan_out(self, source_id: str, frame: Frame, now: Optional[float] = None) -> List[Tuple[ViewerSlot, Decision, bool]]:
        """엣지 입구에서 받은 프레임을 구독 뷰어마다 독립 판정해 큐에 넣는다. 뷰어가 없으면 버린다(빈 목록).

        엣지 입구에서는 버리지 않는다 — 여기 도달한 프레임은 이미 검증을 통과한 것이고, 버림은 뷰어 슬롯마다
        따로 일어난다(느린 브라우저 하나가 다른 뷰어를 굶기지 않는다). `now`는 정체 상한 재료(안 주면 EWMA 만).
        """
        results: List[Tuple[ViewerSlot, Decision, bool]] = []
        for slot in self.viewers_of(source_id):
            if slot.closed:
                continue
            decision, gop_cut = slot.offer(frame, now)
            results.append((slot, decision, gop_cut))
        return results


def parse_frames(blobs: Iterable[bytes], **kwargs: Any) -> List[Frame]:
    """테스트 편의 — 패킷 배열을 프레임 배열로. 거부는 예외 그대로 올린다."""
    return [decode_frame(b, **kwargs) for b in blobs]
