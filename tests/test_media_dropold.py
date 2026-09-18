"""drop-old 상태 기계 — 전이표 전수 · T_drop/T_hard 계산 · JPEG 가 같은 코드로 도는지 · 배출률 회계 · 뷰어 독립.

소켓·시계 없이 돈다(시각은 인자). **핵심 음성 대조:**

- 새 뷰어 슬롯은 `WAIT_IDR`로 시작해 **첫 전송이 반드시 keyframe** 이다(DoD 2-3 · M3).
- `T_drop`은 **배출률**(writer 가 비운 바이트 ÷ 시간) 기준이다 — 도착률로 재면 링크가 느려질 때 임계가 지연을
  바운드하지 못한다. 느린 writer 를 흉내 내면 T_drop 이 줄고 P프레임이 버려지며, 재개는 keyframe 이다.
- GOP 가 없는 스트림(최근 창에 `keyframe=false` 0건)에서는 `T_hard == T_drop` — JPEG 가 `4×T_drop` 이 아니라
  `T_drop` 근처에서 버린다(M8). `encoding` 값을 보지 않는다 — 전부 keyframe 인 H.264 도 같은 결과다.
- 드롭은 뷰어 슬롯마다 독립이다 — 느린 뷰어가 버려도 빠른 뷰어는 받는다.

implements: BE-T-07 (drop-old·채널 분리)
tests: 초기 WAIT_IDR · 전이표 8칸 · T_drop 하한/배출률/상한 · T_hard GOP 유무 · JPEG 동일 코드 · 배출률 회계 회귀 · 팬아웃 독립 · 콜드스타트
"""

from __future__ import annotations

import json

import pytest

from backend.gateway import media
from backend.gateway.media import Decision, DropOldConfig, DropOldPolicy, State


def _frame(keyframe: bool, size: int, seq: int = 0, source_id: str = "cam", encoding: str = "h264") -> media.Frame:
    header = {
        "frame_ref": {"source_id": source_id, "capture_timestamp": "2026-09-18T12:00:00.000+09:00", "sequence_id": seq},
        "encoding": encoding, "keyframe": keyframe, "width": 464, "height": 400,
    }
    header_bytes = json.dumps(header, separators=(",", ":")).encode()
    payload = b"\x00" * max(0, size - 4 - len(header_bytes))
    raw = media.HEADER_LEN_STRUCT.pack(len(header_bytes)) + header_bytes + payload
    return media.Frame(header=header, payload=payload, raw=raw)


# ── 초기 상태·전이표 ────────────────────────────────────────────────────────


def test_initial_state_wait_idr_first_send_is_keyframe() -> None:
    p = DropOldPolicy()
    assert p.state is State.WAIT_IDR
    assert p.decide(keyframe=False, size=2400, buffered=0) == (Decision.DROP, False)   # P프레임은 아무리 비어 있어도 버린다
    assert p.state is State.WAIT_IDR
    assert p.decide(keyframe=True, size=9000, buffered=0) == (Decision.SEND, False)
    assert p.state is State.FLOWING


def _primed(t_drop: float = 10_000.0, idr_max: int = 12_000, with_gop: bool = True) -> DropOldPolicy:
    """임계가 알려진 값이 되도록 표본을 심은 정책. 배출률 = t_drop/0.15 (bytes/s)."""
    p = DropOldPolicy(DropOldConfig(drop_window_s=0.150, buffer_max_bytes=1 << 20))
    p.observe_arrival(True, idr_max)
    if with_gop:
        for _ in range(10):
            p.observe_arrival(False, 2400)
    p.on_drained(1, 0.0)
    p.on_drained(int(t_drop / 0.150), 1.0)       # 1초에 그만큼 비웠다 → 배출률
    p.state = State.FLOWING
    return p


def test_transition_table_flowing() -> None:
    p = _primed()
    t_drop, t_hard = p.t_drop(), p.t_hard()
    assert t_hard == max(4 * t_drop, 2 * 12_000)
    # keyframe && buffered <= T_hard → 보낸다
    assert p.decide(True, 2400, int(t_hard))[0] is Decision.SEND and p.state is State.FLOWING
    # keyframe=false && buffered <= T_drop → 보낸다
    assert p.decide(False, 2400, int(t_drop))[0] is Decision.SEND and p.state is State.FLOWING
    # keyframe=false && buffered > T_drop → 버린다 + WAIT_IDR (GOP 절단)
    assert p.decide(False, 2400, int(t_drop) + 1) == (Decision.DROP, True) and p.state is State.WAIT_IDR
    assert p.gop_cuts == 1
    # 다시 FLOWING 으로 올려 keyframe && buffered > T_hard → 버린다 + WAIT_IDR
    p.state = State.FLOWING
    assert p.decide(True, 2400, int(p.t_hard()) + 1) == (Decision.DROP, True) and p.state is State.WAIT_IDR
    assert p.gop_cuts == 2


def test_transition_table_wait_idr() -> None:
    p = _primed()
    p.state = State.WAIT_IDR
    t_hard = p.t_hard()
    assert p.decide(False, 2400, 0) == (Decision.DROP, False) and p.state is State.WAIT_IDR      # P프레임 전부 버림
    assert p.decide(True, 2400, int(t_hard) + 1) == (Decision.DROP, False) and p.state is State.WAIT_IDR  # 계속 대기
    assert p.decide(True, 2400, int(p.t_hard())) == (Decision.SEND, False) and p.state is State.FLOWING


# ── 임계 계산 ───────────────────────────────────────────────────────────────


def test_t_drop_lower_bound_dominates_before_drain_samples() -> None:
    p = DropOldPolicy()
    p.observe_arrival(True, 2400)
    p.observe_arrival(False, 2400)
    assert p.drain_rate is None
    assert p.t_drop() == 2 * 2400                         # 하한 = 최근 AU 평균 × 2


def test_t_drop_is_time_times_drain_rate_and_capped() -> None:
    p = DropOldPolicy(DropOldConfig(drop_window_s=0.150, buffer_max_bytes=100_000))
    for _ in range(5):
        p.observe_arrival(False, 2400)
    p.on_drained(1, 0.0)
    p.on_drained(72_000, 1.0)                              # 72KB/s ≈ H.264 0.55Mbps
    assert p.t_drop() == pytest.approx(0.150 * 72_000)     # ≈ 10.8KB — 지시서 검산 10.3KB 근처
    p.on_drained(72_000 * 100, 2.0)                        # 매우 빠른 링크 → 상한
    assert p.t_drop() <= 100_000


def test_t_hard_with_and_without_gop() -> None:
    with_gop = _primed(t_drop=10_000, idr_max=12_000, with_gop=True)
    assert with_gop.has_gop()
    assert with_gop.t_hard() == max(4 * with_gop.t_drop(), 24_000)
    no_gop = _primed(t_drop=56_000, idr_max=25_000, with_gop=False)   # JPEG 15fps·25KB
    assert not no_gop.has_gop()
    assert no_gop.t_hard() == no_gop.t_drop()              # 🔴 GOP 없는 스트림에는 T_hard 를 적용하지 않는다


def test_gop_detection_is_observed_not_declared() -> None:
    """관측 기준이다 — 전부 keyframe 인 H.264 도 GOP 없음으로 보고, P프레임이 하나라도 오면 GOP 있음이다."""
    p = DropOldPolicy()
    for _ in range(3):
        p.observe_arrival(True, 25_000)
    assert not p.has_gop()
    p.observe_arrival(False, 2_000)
    assert p.has_gop()


# ── JPEG 가 같은 코드로 돈다 (M8 단위판) ────────────────────────────────────


def test_jpeg_drops_near_t_drop_not_4x() -> None:
    """모든 프레임이 keyframe 이면(JPEG) 큐가 T_drop 을 넘는 순간 버린다 — 4×T_drop 까지 쌓이지 않는다."""
    p = _primed(t_drop=56_000, idr_max=25_000, with_gop=False)
    t_drop = p.t_drop()
    assert p.decide(True, 25_000, int(t_drop)) == (Decision.SEND, False)
    assert p.decide(True, 25_000, int(t_drop) + 1) == (Decision.DROP, True)     # T_hard == T_drop 이라 여기서 버린다
    assert p.state is State.WAIT_IDR
    assert p.decide(True, 25_000, int(p.t_drop())) == (Decision.SEND, False)    # 다음 keyframe(= 다음 JPEG) 으로 즉시 재개
    assert p.state is State.FLOWING


def test_same_code_path_for_h264_and_jpeg_encodings() -> None:
    """정책은 encoding 문자열을 받지도 않는다 — 판정 재료는 keyframe·size·buffered(+정체 상한용 in_flight·stalled_s)뿐."""
    import inspect

    params = list(inspect.signature(DropOldPolicy.decide).parameters)
    assert params == ["self", "keyframe", "size", "buffered", "in_flight", "stalled_s"]
    assert "encoding" not in params and "codec" not in params


def test_stall_cap_shrinks_t_drop_immediately() -> None:
    """커널 버퍼가 첫 프레임들을 흡수해 EWMA 가 고속(1MB/s)이어도, 보내는 중인 25KB 가 0.5초째 안 끝나면
    배출률 상한은 50KB/s → T_drop 이 즉시 7.5KB 로 줄어 다음 프레임이 버려진다(정체 반응)."""
    p = DropOldPolicy(DropOldConfig(drop_window_s=0.150, buffer_max_bytes=1 << 20))
    for _ in range(5):
        p.observe_arrival(True, 25_000)
    p.on_drained(1, 0.0)
    p.on_drained(1_000_000, 1.0)                           # EWMA ≈ 1MB/s → T_drop 이 150KB
    assert p.t_drop() == pytest.approx(150_000)
    assert p.t_drop(in_flight=25_000, stalled_s=0.5) == pytest.approx(max(50_000, 0.150 * 50_000))
    p.state = State.FLOWING
    assert p.decide(True, 25_000, buffered=60_000, in_flight=25_000, stalled_s=0.5)[0] is Decision.DROP


# ── 배출률 회계 회귀 — 느린 writer 흉내 (3-3 의 단위판) ─────────────────────


def test_slow_drain_shrinks_t_drop_and_resume_is_keyframe() -> None:
    """도착 30fps·2.4KB 인데 writer 가 100ms 마다 한 장만 비운다 → T_drop 이 배출률(24KB/s)로 줄어 P프레임이 버려지고,
    버린 뒤 첫 전송은 keyframe 이다. 도착률(72KB/s)로 쟀다면 T_drop 이 3배라 훨씬 늦게 버렸을 것이다."""
    slot = media.ViewerSlot(source_id="cam", policy=DropOldPolicy(DropOldConfig(drop_window_s=0.150)), created_at=0.0)
    now = 0.0
    # GOP 15: IDR 하나(9KB) + P 14장(2.4KB). writer 는 100ms 에 한 장.
    def gop(seq0: int):
        yield _frame(True, 9_000, seq0)
        for i in range(1, 15):
            yield _frame(False, 2_400, seq0 + i)

    decisions = []
    next_drain = 0.0
    seq = 0
    for _ in range(4):                                     # 4 GOP = 60프레임 = 2초 도착
        for f in gop(seq):
            d, cut = slot.offer(f)
            decisions.append((f.keyframe, d, slot.policy.state))
            now += 1 / 30
            while now >= next_drain and slot.pending:
                blob = slot.take()
                slot.on_drained(len(blob), next_drain)
                next_drain += 0.100
            if not slot.pending:
                next_drain = max(next_drain, now)
        seq += 15
    dropped = [x for x in decisions if x[1] is Decision.DROP]
    assert dropped, "느린 writer 인데 드롭이 한 번도 없다 — 배출률 회계가 안 돈다"
    assert slot.policy.drain_rate is not None and slot.policy.drain_rate < 40_000, slot.policy.drain_rate  # 도착률 72KB/s 가 아니라 배출률
    assert slot.policy.t_drop() < 0.150 * 72_000, "T_drop 이 도착률 기준으로 계산됐다"
    # 드롭 직후 첫 SEND 는 반드시 keyframe
    for i, (kf, d, _) in enumerate(decisions):
        if d is Decision.DROP:
            nxt = next(((k, dd) for k, dd in ((x[0], x[1]) for x in decisions[i + 1:]) if dd is Decision.SEND), None)
            if nxt is not None:
                assert nxt[0] is True, "드롭 뒤 첫 전송이 P프레임이다"
            break
    assert slot.policy.gop_cuts >= 1


# ── 뷰어 독립·팬아웃·콜드스타트 ─────────────────────────────────────────────


def test_fan_out_is_independent_per_viewer() -> None:
    relay = media.Relay(media.DropOldConfig(), clock=lambda: 100.0)
    fast = relay.subscribe("cam")
    slow = relay.subscribe("cam")
    idr = _frame(True, 9_000, 0)
    assert {d for _, d, _ in relay.fan_out("cam", idr)} == {Decision.SEND}
    # 빠른 뷰어는 바로 비우고, 느린 뷰어는 큐가 그대로 쌓인다
    fast.take(); fast.on_drained(9_000, 100.1)
    for i in range(1, 30):
        results = {s: d for s, d, _ in relay.fan_out("cam", _frame(False, 2_400, i))}
        fast.take(); fast.on_drained(2_400, 100.1 + i / 30)
        if results[slow] is Decision.DROP:
            break
    assert slow.dropped_frames >= 1 and fast.dropped_frames == 0
    assert slow.policy.state is State.WAIT_IDR and fast.policy.state is State.FLOWING
    assert relay.viewer_count("cam") == 2
    relay.unsubscribe(slow)
    assert relay.viewer_count("cam") == 1 and slow.closed and not slow.pending


def test_no_viewer_means_drop_and_coldstart_once() -> None:
    clock = {"t": 10.0}
    relay = media.Relay(clock=lambda: clock["t"])
    assert relay.fan_out("cam", _frame(True, 100)) == []            # 뷰어가 없으면 버린다
    slot = relay.subscribe("cam")
    clock["t"] = 10.5
    relay.fan_out("cam", _frame(True, 100, 1))
    blob = slot.take()
    assert slot.on_drained(len(blob), 10.75) == pytest.approx(0.75)   # 연결(10.0) → 첫 전송(10.75)
    relay.fan_out("cam", _frame(False, 50, 2))
    blob = slot.take()
    assert slot.on_drained(len(blob), 10.8) is None                   # 두 번째부터는 콜드스타트가 아니다
    assert slot.sent_frames == 2 and slot.buffered == 0


def test_buffered_accounting_includes_in_flight() -> None:
    slot = media.ViewerSlot(source_id="cam", policy=DropOldPolicy(), created_at=0.0)
    f = _frame(True, 1_000)
    slot.offer(f)
    assert slot.buffered == f.size and len(slot.pending) == 1
    blob = slot.take()
    assert slot.buffered == f.size and slot.in_flight == f.size      # 보내는 중인 바이트도 buffered 다
    slot.on_drained(len(blob), 1.0)
    assert slot.buffered == 0 and slot.in_flight == 0
