"""지속 객체 레코드 — 논문 §3 규칙이 흔들림을 막는지 시험한다.

implements: AI-S-06, AI-S-03, AI-S-04
tests: class replacement needs strictly more group support, confidence-only change
       does not expose an update, exposed geometry is quantized, lifecycle counts
       consecutive missed observations, entry/exit change only the affected object

근거: internal/docs-dev/obsidian/ideas/progressive-object-record.pdf §3
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from object_tracks import ObjectTracks  # noqa: E402

CFG = {"object_tracks": {"geometry_quantum_px": 8.0}}


def det(box, label, conf, concept, sources, alt=None):
    d = {"box": list(box), "label": label, "conf": conf, "concept": concept,
         "sources": sources}
    if alt:
        d["alt"] = alt
    return d


def agreed(box, a, ca, b, cb, concept):
    """두 모델이 합의한 검출 — merge_by_consensus가 내보내는 모양."""
    return det(box, a, ca, concept, ["prompt_free", "text_prompt"],
               {"label": b, "conf": cb})


def test_static_scene_produces_no_new_updates():
    """장면이 그대로면 노출 갱신이 일어나지 않는다 — 사용자 요구의 핵심."""
    t = ObjectTracks(CFG)
    box = (100.0, 100.0, 200.0, 200.0)
    t.update([agreed(box, "computer chair", 0.80, "office chair", 0.40, "chair")], 1000.0)
    rec = list(t.objects.values())[0]
    t.update([agreed(box, "computer chair", 0.80, "office chair", 0.40, "chair")], 1001.0)
    r0 = rec.revision
    for i in range(6):
        # confidence만 흔들리고 박스는 1~2px 떤다 — 실제 관측이 그렇다.
        jit = (box[0] + (i % 2), box[1], box[2] + (i % 2), box[3])
        t.update([agreed(jit, "computer chair", 0.60 + 0.05 * (i % 3),
                         "office chair", 0.20 + 0.03 * (i % 2), "chair")], 1002.0 + i)
    assert rec.revision == r0, f"정지 장면인데 갱신 {rec.revision - r0}회"
    assert rec.confirmed_ready(), rec.lifecycle


def test_class_changes_only_with_strictly_more_group_support():
    """동수 지지로는 이름이 바뀌지 않는다(논문 §3.1).

    비교 대상은 그 클래스가 **확립된 지지 수준**이다. 소스 그룹이 둘뿐인 이 구성에서
    2그룹으로 확립된 클래스는 더 큰 지지가 있을 수 없으므로 객체가 만료될 때까지
    유지된다 — 흔들림을 없애기 위해 감수하는 대가이며, 잘못 확정되면 만료로만
    풀린다.
    """
    t = ObjectTracks(CFG)
    box = (10.0, 10.0, 110.0, 110.0)

    # 한 소스만 말한 상태로 확립한다(지지 1).
    t.update([det(box, "computer chair", 0.8, "chair", ["prompt_free"])], 1000.0)
    rec = list(t.objects.values())[0]
    assert rec.concept == "chair" and rec.class_groups == 1

    # 다른 단일 소스가 person이라 말한다 — 1 > 1이 아니므로 바뀌지 않는다.
    t.update([det(box, "person", 0.95, "person", ["text_prompt"])], 1001.0)
    assert rec.concept == "chair", rec.concept

    # 두 소스가 person으로 합의하면 2 > 1이라 바뀐다.
    t.update([agreed(box, "person", 0.9, "person", 0.7, "person")], 1002.0)
    assert rec.concept == "person", rec.concept
    assert rec.class_groups == 2

    # 이제 단일 소스 chair는 되돌리지 못한다.
    t.update([det(box, "computer chair", 0.99, "chair", ["prompt_free"])], 1003.0)
    assert rec.concept == "person", rec.concept


def test_geometry_is_quantized_on_exposure():
    """양자 이하의 이동은 노출 기하를 바꾸지 않는다."""
    t = ObjectTracks(CFG)
    b0 = (0.0, 0.0, 100.0, 100.0)
    t.update([agreed(b0, "bottle", 0.7, "bottle", 0.5, "bottle")], 1000.0)
    rec = list(t.objects.values())[0]
    exposed = rec.exposed_box
    t.update([agreed((2.0, 1.0, 102.0, 101.0), "bottle", 0.7, "bottle", 0.5, "bottle")],
             1001.0)
    assert rec.exposed_box == exposed, "2px 이동이 노출을 바꿨다"
    t.update([agreed((40.0, 0.0, 140.0, 100.0), "bottle", 0.7, "bottle", 0.5, "bottle")],
             1002.0)
    assert rec.exposed_box != exposed, "40px 이동이 반영되지 않았다"


def test_lifecycle_counts_consecutive_missed_observations():
    """stale 3회, expired 5회 — 벽시계가 아니라 연속 미관측 횟수(논문 식 9)."""
    t = ObjectTracks(CFG)
    box = (0.0, 0.0, 50.0, 50.0)
    t.update([agreed(box, "cup", 0.7, "cup", 0.5, "cup")], 1000.0)
    rec = list(t.objects.values())[0]
    assert rec.lifecycle == "confirmed"
    for _ in range(3):
        t.update([], 1001.0)
    assert rec.lifecycle == "stale", rec.lifecycle
    t.update([agreed(box, "cup", 0.7, "cup", 0.5, "cup")], 1002.0)   # 되살아난다
    assert rec.lifecycle == "confirmed", rec.lifecycle
    for _ in range(5):
        t.update([], 1003.0)
    assert rec.obj_id not in t.objects, "5회 미관측인데 남아 있다"


def test_entry_and_exit_touch_only_the_affected_object():
    """하나가 들어오면 그것만 추가되고, 나가면 그것만 사라진다."""
    t = ObjectTracks(CFG)
    a = (0.0, 0.0, 100.0, 100.0)
    b = (400.0, 0.0, 500.0, 100.0)
    for _ in range(2):
        t.update([agreed(a, "cup", 0.7, "cup", 0.5, "cup")], 1000.0)
    ids0 = {r.obj_id for r in t.objects.values()}

    t.update([agreed(a, "cup", 0.7, "cup", 0.5, "cup"),
              agreed(b, "bottle", 0.8, "bottle", 0.6, "bottle")], 1001.0)
    ids1 = {r.obj_id for r in t.objects.values()}
    assert ids0 < ids1 and len(ids1 - ids0) == 1, (ids0, ids1)

    for _ in range(5):
        t.update([agreed(a, "cup", 0.7, "cup", 0.5, "cup")], 1002.0)
    ids2 = {r.obj_id for r in t.objects.values()}
    assert ids2 == ids0, (ids0, ids2)


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
