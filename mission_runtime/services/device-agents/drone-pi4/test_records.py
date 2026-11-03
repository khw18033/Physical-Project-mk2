"""시점 반영 검증 — 지연 근거가 **정체성**으로 붙는지 수치로 확인한다.

implements: AI-S-06, AI-S-01, AI-C-03, AI-S-03
tests: late evidence attaches by track_id, observed_box comes from the track's own
       history (not the verdict's detection box), displacement measures real motion,
       dead-track evidence becomes an orphan instead of being promoted

왜 단위 테스트인가: 라이브 카메라로는 **화면 안에 움직이는 것이 있을 때만** 반영을
확인할 수 있다. 고정 카메라가 빈 벽을 보고 있으면 이동이 0이라 "정체성으로 붙였다"와
"좌표로 붙였다"가 구분되지 않는다. 여기서는 이동을 우리가 만들어 그 구분을 강제한다.

2026-09-21에 실제로 틀렸던 것을 그대로 시험한다: `observed_box`를 판정에 실려 온
검출 박스에서 가져오면, OVD의 거의 전체 화면짜리 박스와 작은 RPN 트랙의 중심 거리가
"300px 이동"으로 둔갑한다. 서로 다른 트랙 여럿이 **같은** observed_box를 들고 있었던
것이 그 증거였다. 아래 test_observed_box_is_not_the_verdict_box가 그 회귀를 막는다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from records import RecordStore  # noqa: E402


class T:
    """ByteTracker 트랙의 최소 대역 — track_id와 box만 있으면 된다."""

    def __init__(self, track_id: int, box):
        self.track_id, self.box = track_id, box


def _walk(store: RecordStore, tid: int, frames, t0: float = 1000.0):
    """트랙 하나를 프레임마다 옮기며 관측시킨다. (seq, box)를 돌려준다."""
    seen = []
    for i, box in enumerate(frames):
        store.observe([T(tid, box)], frame_seq=i, at=t0 + i * 0.25)
        seen.append((i, box))
    return seen


def test_late_evidence_attaches_by_identity_not_coordinates():
    """프레임 0에서 관측된 근거가 프레임 6의 **현재 박스**에 붙는다."""
    s = RecordStore()
    frames = [(10 + 40 * i, 20, 60 + 40 * i, 80) for i in range(7)]   # 오른쪽으로 이동
    _walk(s, tid=7, frames=frames)

    r = s.apply_verdict({
        "frame_id": "f0", "frame_seq": 0, "observed_at": 1000.0,
        "per_track": [{"track_id": 7, "ovd": {"label": "box", "conf": 0.9,
                                              "verdict": "confident",
                                              # 검출기 기하 — 써서는 안 되는 값
                                              "box": [0, 0, 960, 720]}}],
    }, current_seq=6, now=1001.5)

    assert r["applied"] == 1 and r["orphaned"] == 0, r
    assert r["frames_late"] == 6, r

    rec = s.records[7]
    assert rec.box == frames[-1], rec.box          # 박스는 언제나 최신 추적값
    ev = rec.latest("ovd")
    assert ev is not None
    # observed_box는 **프레임 0에서 이 트랙 자신이 있던 자리**여야 한다.
    assert ev.observed_box == frames[0], ev.observed_box
    # 그 사이 실제로 240px 움직였다. 중심 이동 = 6프레임 × 40px.
    assert abs(ev.displacement(rec.box) - 240.0) < 0.5, ev.displacement(rec.box)


def test_observed_box_is_not_the_verdict_box():
    """서로 다른 트랙에 같은 검출 박스가 실려 와도 observed_box는 각자 다르다.

    이것이 2026-09-21 실측에서 깨졌던 불변식이다 — tid 6270/6347/6819가 모두
    [0.1, 47.4, 345.4, 670.2]을 들고 "이동"을 보고했다.
    """
    s = RecordStore()
    # observe()는 프레임당 **전체 트랙 목록**을 받는다 — 목록에 없는 트랙은 죽은
    # 것으로 표시된다. 트랙마다 따로 호출하면 마지막 하나만 살아남는다.
    at = ((1, 0.0), (2, 300.0), (3, 600.0))
    s.observe([T(t, (x, 0, x + 40, 40)) for t, x in at], frame_seq=0, at=1000.0)
    s.observe([T(t, (x + 10, 5, x + 50, 45)) for t, x in at], frame_seq=3, at=1000.8)

    shared = [0.0, 0.0, 960.0, 720.0]        # OVD가 화면 전체를 잡은 경우
    s.apply_verdict({
        "frame_id": "f0", "frame_seq": 0, "observed_at": 1000.0,
        "per_track": [{"track_id": t, "ovd": {"label": "x", "conf": 0.5,
                                              "verdict": "tentative",
                                              "box": shared}}
                      for t in (1, 2, 3)],
    }, current_seq=3, now=1001.0)

    boxes = [s.records[t].latest("ovd").observed_box for t in (1, 2, 3)]
    assert len(set(boxes)) == 3, boxes           # 셋이 서로 달라야 한다
    assert all(b != tuple(shared) for b in boxes), boxes
    # 실제 이동은 프레임당 10px씩, 대각선으로 약 11.2px뿐이다.
    for t in (1, 2, 3):
        rec = s.records[t]
        d = rec.latest("ovd").displacement(rec.box)
        assert d < 15.0, (t, d)


def test_no_motion_reports_zero_not_success():
    """정지한 트랙은 이동 0을 보고한다 — 반영을 성공으로 위장하지 않는다."""
    s = RecordStore()
    _walk(s, tid=5, frames=[(10, 10, 50, 50)] * 5)
    s.apply_verdict({"frame_id": "f0", "frame_seq": 0, "observed_at": 1000.0,
                     "per_track": [{"track_id": 5,
                                    "clip": {"verdict": "unknown",
                                             "ranking": [{"class": "q", "score": 0.3}]}}]},
                    current_seq=4, now=1001.0)
    rec = s.records[5]
    assert rec.latest("clip").displacement(rec.box) == 0.0


def test_evidence_for_dead_track_becomes_orphan():
    """트랙이 사라진 뒤 도착한 근거는 승격하지 않고 학습 후보로 남는다(AI-L-01)."""
    s = RecordStore()
    s.observe([T(9, (0, 0, 20, 20))], frame_seq=0, at=1000.0)
    s.observe([], frame_seq=1, at=1000.3)          # 트랙 소실
    r = s.apply_verdict({"frame_id": "f0", "frame_seq": 0, "observed_at": 1000.0,
                         "per_track": [{"track_id": 9,
                                        "ovd": {"label": "z", "conf": 0.9,
                                                "verdict": "confident"}}]},
                        current_seq=1, now=1000.5)
    assert r["applied"] == 0 and r["orphaned"] == 1, r
    assert s.orphans[0]["reason"] == "track_not_alive"


def test_transmit_view_carries_verification_fields():
    """엣지로 보내는 뷰에 현재 박스·관측 박스·이동거리가 함께 실린다."""
    s = RecordStore()
    frames = [(0 + 30 * i, 0, 40 + 30 * i, 40) for i in range(5)]
    _walk(s, tid=3, frames=frames)
    s.apply_verdict({"frame_id": "f0", "frame_seq": 0, "observed_at": 1000.0,
                     "per_track": [{"track_id": 3,
                                    "ovd": {"label": "a", "conf": 0.8,
                                            "verdict": "confident"}}]},
                    current_seq=4, now=1001.0)
    view = s.transmit_view(now=1001.0)
    item = next(v for v in view if v["track_id"] == 3)
    assert item["box"] == [round(v, 1) for v in frames[-1]]
    assert item["ovd"]["observed_box"] == [round(v, 1) for v in frames[0]]
    assert abs(item["ovd"]["moved_px"] - 120.0) < 0.5, item["ovd"]["moved_px"]
    assert item["ovd"]["frames_late"] == 4


def test_consensus_survives_a_single_contradicting_frame():
    """한 프레임짜리 반대 근거가 누적된 다수를 뒤집지 못한다.

    2026-09-21 사용자 보고: 카메라와 피사체가 모두 고정인데 프레임마다 검출 결과가
    흔들린다. 실측하니 트랙은 90~100% 유지되는데 **라벨이** 초당 약 1개 바뀌었다 —
    마지막 도착 근거로 덮어쓰기 때문이다.
    """
    s = RecordStore(evidence_ttl_s=6.0)
    _walk(s, tid=4, frames=[(10, 10, 50, 50)] * 6, t0=1000.0)

    def verdict(seq, lab, t):
        s.apply_verdict({"frame_id": f"f{seq}", "frame_seq": seq, "observed_at": t,
                         "per_track": [{"track_id": 4,
                                        "ovd": {"label": lab, "conf": 0.7,
                                                "verdict": "confident"}}]},
                        current_seq=5, now=t + 0.1)

    for i in range(4):
        verdict(i, "chair", 1000.0 + i * 0.3)
    verdict(4, "treadmill", 1001.3)          # 한 프레임 흔들림

    rec = s.records[4]
    assert rec.latest("ovd").payload["label"] == "treadmill"      # 마지막은 흔들림
    win = rec.consensus("ovd", now=1001.4, ttl=6.0)
    assert win.payload["label"] == "chair", win.payload           # 다수는 유지

    item = next(v for v in s.transmit_view(now=1001.4) if v["track_id"] == 4)
    assert item["ovd"]["payload"]["label"] == "chair"
    assert item["ovd"]["support"] == 4, item["ovd"]["support"]


def test_expired_evidence_leaves_the_current_view_but_stays_recorded():
    """TTL이 지난 근거는 현재 상태에서 빠지되 레코드에는 남는다(학습 후보)."""
    s = RecordStore(evidence_ttl_s=2.0)
    _walk(s, tid=8, frames=[(0, 0, 30, 30)] * 3, t0=1000.0)
    s.apply_verdict({"frame_id": "f0", "frame_seq": 0, "observed_at": 1000.0,
                     "per_track": [{"track_id": 8,
                                    "ovd": {"label": "a", "conf": 0.9,
                                            "verdict": "confident"}}]},
                    current_seq=2, now=1000.2)
    assert "ovd" in next(v for v in s.transmit_view(now=1001.0) if v["track_id"] == 8)
    assert "ovd" not in next(v for v in s.transmit_view(now=1005.0) if v["track_id"] == 8)
    assert len(s.records[8].evidence) == 1          # 지우지는 않았다


def test_smoothing_absorbs_jitter_but_follows_real_motion():
    """떨림은 누르고 실제 이동은 지연 없이 따라간다.

    드론이 움직일 때 박스가 뒤처지면 이 파이프라인의 목적이 무너지므로, 평활화는
    '작은 변화'에만 걸려야 한다.
    """
    from records import smooth_box
    prev = (100.0, 100.0, 140.0, 140.0)

    # 떨림: 2px — 강하게 눌려야 한다
    jit = smooth_box(prev, (102.0, 100.0, 142.0, 140.0), alpha=0.35, snap_px=24.0)
    assert 0.5 < jit[0] - prev[0] < 1.0, jit        # 2px 입력이 1px 미만으로

    # 실제 이동: 40px — 그대로 따라가야 한다
    mov = smooth_box(prev, (140.0, 100.0, 180.0, 140.0), alpha=0.35, snap_px=24.0)
    assert abs(mov[0] - 140.0) < 0.01, mov

    # alpha=1이면 평활화 없음(원래 동작)
    raw = smooth_box(prev, (102.0, 100.0, 142.0, 140.0), alpha=1.0, snap_px=24.0)
    assert raw == (102.0, 100.0, 142.0, 140.0)


def test_reanchor_puts_detector_geometry_at_the_current_place():
    """검출 박스의 크기는 유지하고 트랙이 움직인 만큼 옮긴다."""
    from records import reanchor
    det = (100.0, 100.0, 160.0, 140.0)          # 정확한 OVD 박스 (60x40)
    obs = (90.0, 95.0, 170.0, 150.0)            # 그때 트랙 박스 (헐거움)
    cur = (190.0, 95.0, 270.0, 150.0)           # 지금 트랙 박스 — 오른쪽 100px
    out = reanchor(det, obs, cur)
    assert abs((out[2] - out[0]) - 60.0) < 0.01, out      # 크기 유지
    assert abs((out[3] - out[1]) - 40.0) < 0.01, out
    assert abs(out[0] - 200.0) < 0.01, out                # 100px 옮겨짐

    assert reanchor(det, None, cur) is None               # 모르면 추정하지 않는다
    assert reanchor(None, obs, cur) is None


def test_reanchored_box_reaches_the_transmit_view():
    s = RecordStore(box_alpha=1.0)
    _walk(s, tid=2, frames=[(0 + 50 * i, 0, 80 + 50 * i, 60) for i in range(4)])
    s.apply_verdict({"frame_id": "f0", "frame_seq": 0, "observed_at": 1000.0,
                     "per_track": [{"track_id": 2,
                                    "ovd": {"label": "a", "conf": 0.9,
                                            "verdict": "confident",
                                            "box": [10, 5, 60, 45]}}]},
                    current_seq=3, now=1000.5)
    item = next(v for v in s.transmit_view(now=1000.6) if v["track_id"] == 2)
    rb = item["ovd"]["reanchored_box"]
    assert abs((rb[2] - rb[0]) - 50.0) < 0.5, rb          # 검출 폭 50 유지
    assert rb[0] > item["ovd"]["observed_box"][0], rb     # 현재 쪽으로 옮겨졌다


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_"):
            continue
        try:
            fn()
            print(f"PASS  {name}")
        except AssertionError as exc:
            fails += 1
            print(f"FAIL  {name}: {exc}")
    print("\n" + ("모두 통과" if not fails else f"{fails}건 실패"))
    sys.exit(1 if fails else 0)
