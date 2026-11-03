"""낮은 프레임률에서 연관이 성립하는지 — 등속 예측의 효과를 나란히 잰다.

implements: AI-S-01, AI-S-06, AI-C-03
tests: identity survives large inter-frame displacement, prediction is used only
       for association (reported box stays the measured one), no-motion case unchanged

배경(2026-09-21 실측): pi4가 두 카메라를 번갈아 처리해 카메라당 1.1~2.1 fps였다.
0.5~0.9초 간격에서 시야가 움직이면 같은 물체의 프레임 간 IoU가 0에 가까워지고,
순수 IOU 매칭은 매 프레임 새 track_id를 만든다. 그러면 지연 근거를 붙일 앵커가
사라져 "화면 변화가 생기면 결과가 매번 달라지는" 증상이 된다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tracking import ByteTracker, Detection, Track  # noqa: E402


def pan(n_frames: int, step: float, n_obj: int = 6):
    """시야가 일정 속도로 흐르는 장면. 물체는 매 프레임 step 픽셀씩 옮겨간다."""
    for f in range(n_frames):
        dets = []
        for i in range(n_obj):
            x = 60.0 + i * 150.0 - step * f
            dets.append(Detection(box=(x, 300.0, x + 90.0, 390.0),
                                  score=0.9 - i * 0.01))
        yield dets


def run(step: float, *, predict: bool) -> tuple[int, int]:
    """(마지막 프레임의 트랙 수, 총 발급된 id 수)를 돌려준다."""
    t = ByteTracker(high_thresh=0.6, low_thresh=0.1, iou_threshold=0.3,
                    low_iou_threshold=0.5, max_missed_frames=5,
                    motion_prediction=predict, velocity_alpha=0.5)
    ids = set()
    tracks = []
    for dets in pan(10, step):
        tracks = t.update(dets)
        ids.update(tr.track_id for tr in tracks)
    return len(tracks), len(ids)


def test_prediction_keeps_identity_when_frames_are_far_apart():
    """박스 폭(90px)의 3분의 2만큼 움직이면 예측 없이는 정체성이 무너진다."""
    step = 60.0                      # 1 fps에서 흔한 이동량
    n_no, ids_no = run(step, predict=False)
    n_yes, ids_yes = run(step, predict=True)

    # 물체는 6개뿐인데 예측이 없으면 id가 계속 새로 발급된다.
    assert ids_no > ids_yes, (ids_no, ids_yes)
    assert ids_yes <= 12, ids_yes            # 6개 + 초기 몇 개
    print(f"    step {step:.0f}px: 예측 없음 id {ids_no}개 / 예측 있음 id {ids_yes}개")


def test_slow_motion_is_unaffected():
    """느린 장면에서는 예측이 있든 없든 결과가 같아야 한다(회귀 방지)."""
    n_no, ids_no = run(5.0, predict=False)
    n_yes, ids_yes = run(5.0, predict=True)
    assert ids_no == ids_yes, (ids_no, ids_yes)


def test_reported_box_is_the_measured_box_not_the_prediction():
    """예측은 연관에만 쓴다 — 보고 좌표는 언제나 실제 검출 좌표다(AI-S-03).

    여기서는 IoU만으로도 이어지는 이동량(30px / 폭 90px)을 쓴다. 그래야 트랙 자신의
    속도가 쌓이고, 그 속도가 있는데도 보고 좌표는 관측값 그대로인지를 볼 수 있다.
    """
    t = ByteTracker(high_thresh=0.6, low_thresh=0.1, iou_threshold=0.3,
                    low_iou_threshold=0.5, max_missed_frames=5,
                    motion_prediction=True, velocity_alpha=0.5)
    boxes = [(100.0, 100.0, 190.0, 190.0),
             (130.0, 100.0, 220.0, 190.0),
             (160.0, 100.0, 250.0, 190.0)]
    last = None
    for b in boxes:
        last = t.update([Detection(box=b, score=0.9)])
    assert len(last) == 1, last
    assert last[0].box == boxes[-1], last[0].box     # 예측값이 아니라 관측값
    assert last[0].velocity[0] > 0                    # 속도는 쌓였다


def test_missed_frames_extrapolate_further():
    """가려졌다 다시 나타난 물체를 되찾는다 — 놓친 만큼 더 멀리 예측한다.

    속도가 쌓일 만큼(40px/프레임, IoU 0.39) 이어붙인 뒤 한 프레임을 통째로 비운다.
    다시 나타난 위치는 80px 뒤이므로 예측 없이는 IoU가 0이라 되찾을 수 없다.
    """
    t = ByteTracker(high_thresh=0.6, low_thresh=0.1, iou_threshold=0.3,
                    low_iou_threshold=0.5, max_missed_frames=5,
                    motion_prediction=True, velocity_alpha=1.0)
    tid = None
    for x in (100.0, 140.0, 180.0, 220.0):
        tid = t.update([Detection(box=(x, 0.0, x + 90.0, 90.0), score=0.9)])[0].track_id
    t.update([])                                      # 한 프레임 가려짐
    back = t.update([Detection(box=(300.0, 0.0, 390.0, 90.0), score=0.9)])
    assert len(back) == 1 and back[0].track_id == tid, [b.track_id for b in back]


def test_global_shift_needs_corroboration():
    """전역 이동 추정은 근거가 3개 미만이면 하지 않는다.

    한두 개의 잘못된 짝짓기로 **모든** 트랙을 엉뚱한 곳으로 옮기면 클러터에서
    정체성이 통째로 무너진다. 근거가 모자라면 추정하지 않고 per-track 속도에 맡긴다
    (AI-S-03: 모르면 만들어내지 않는다).
    """
    from tracking import _global_shift
    tr = [Track(track_id=1, box=(0.0, 0.0, 50.0, 50.0), label=None)]
    dets = [Detection(box=(30.0, 0.0, 80.0, 50.0), score=0.9)]
    assert _global_shift(tr, dets) == (0.0, 0.0)

    tr = [Track(track_id=i, box=(i * 200.0, 0.0, i * 200.0 + 50.0, 50.0), label=None)
          for i in range(4)]
    dets = [Detection(box=(i * 200.0 + 30.0, 0.0, i * 200.0 + 80.0, 50.0), score=0.9)
            for i in range(4)]
    assert _global_shift(tr, dets) == (30.0, 0.0)


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
