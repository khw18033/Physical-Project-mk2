"""RPN 후보 후처리 — 조각 흡수·병합 판정.

implements: AI-S-04, AI-S-06, AI-E-04, AI-B-01

**왜 필요한가**(2026-09-21 오버레이 실측): 미지로 분류된 노란 박스의 대부분이 실제로는
미지 객체가 아니라 **이미 OVD가 이름 붙인 객체의 조각이거나 여러 객체를 한꺼번에 감싼
박스**였다. 그런데도 미지로 샌 이유는 `split_known_unknown`이 **IoU만** 봤기 때문이다.

IoU가 이 두 경우를 못 잡는다:

    조각(fragment)   차 문짝만 딴 작은 박스 ⊂ car 박스
                     교집합은 작은 박스 전체지만 합집합은 car 전체 → IoU 낮음
    병합(merged)     차 3대를 한꺼번에 감싼 큰 박스 ⊃ car 박스 3개
                     어느 car와도 IoU가 낮음

그래서 축을 셋으로 나눈다. 셋 다 "OVD가 이미 설명한 것"으로 보고 미지에서 뺀다.

    match       IoU ≥ match_iou                     기존 동작. 같은 것을 봤다.
    fragment    후보 면적의 대부분이 한 OVD 박스 안  그 객체의 일부다.
    merged      후보가 OVD 박스 여러 개를 덮음       이미 아는 것들의 묶음이다.

그리고 남은 미지끼리 겹치는 것은 합친다(`merge_overlapping`) — RPN은 같은 자리에
여러 박스를 내므로, 안 합치면 같은 대상이 crop 여러 장으로 저장되고 가시화가 덮인다.

**흡수는 버리는 것이 아니다.** 흡수된 후보에는 사유(`absorbed_by`)와 근거 수치가 남아
`known` 쪽에 실린다 — 나중에 "이 조각을 흡수한 게 맞았나"를 되짚을 수 있어야 한다
(AI-B-01: 판정 근거를 남긴다). 다만 CLIP crop으로는 가지 않는다.
"""

from __future__ import annotations

from common import iou


def _area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _inter(a, b) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    return max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)


def containment(inner, outer) -> float:
    """inner 면적 중 outer 안에 들어간 비율. 조각 판정의 축이다."""
    a = _area(inner)
    return (_inter(inner, outer) / a) if a > 0 else 0.0


def union_box(boxes):
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def absorb(rpn_items, ovd_dets, cfg_unknown: dict):
    """RPN 후보를 `known`(OVD가 **확신을 갖고** 설명함)과 `unknown`으로 가른다.

    **확신 OVD만 흡수한다**(사용자 2026-09-21). OVD가 낮은 conf로 이름을 붙인 것은
    "배경이 아닌데 뭔지 모르는 것"이지 설명된 것이 아니다 — 미식별과 같은 범주이고,
    다만 OVD 쪽 근거가 하나 더 붙어 있을 뿐이다. 그래서 잠정 OVD와 겹친 후보는
    unknown으로 보내되 그 라벨을 `ovd_hint`로 실어 보낸다. 그러면 CLIP 근거까지
    붙어 **두 근거를 나란히** 관리자에게 보여줄 수 있다(AI-S-03, AI-L-03).

    반환: (known, unknown, stats). stats는 어느 규칙이 몇 개를 흡수했는지 — 규칙을
    켜고 끌 때 효과를 바로 볼 수 있어야 한다(AI-O-01).
    """
    match_iou = float(cfg_unknown.get("match_iou", 0.3))
    frag_c = float(cfg_unknown.get("fragment_containment", 0.70))
    # **큰 검출은 조각을 삼키지 못한다.** 2026-09-21 실측: 화면 88%를 덮는
    # `water surface` 검출이 후보 298개를 fragment로 흡수했고, 다음 프레임에서 그
    # conf가 0.35를 0.019 차이로 못 넘자 흡수가 102개로 무너지며 미지가 3배로 튀었다
    # (frame 002→003). 화면의 상당 부분을 덮는 박스는 '객체'가 아니라 장면이며,
    # 그 안에 든 것을 그 객체의 조각으로 볼 근거가 없다.
    # 부유목 더미처럼 **검출 대상이면서 큰** 객체에도 같은 보호가 필요하다 —
    # 더미 위에 얹힌 페트병이 더미의 조각으로 흡수되면 안 된다(사용자 2026-09-21).
    max_abs = float(cfg_unknown.get("max_absorber_area_frac", 0.80))
    min_ratio = float(cfg_unknown.get("min_fragment_ratio", 0.05))
    frame_area = float(cfg_unknown.get("_frame_area", 0.0))
    merge_cov = float(cfg_unknown.get("merged_coverage", 0.55))
    merge_min = int(cfg_unknown.get("merged_min_dets", 2))

    # 흡수 대상은 확신 검출뿐이다. verdict가 없으면(구버전 호출) 전부 대상으로 본다.
    def _can_absorb(d) -> bool:
        """흡수 자격: 확신이고, 프레임을 통째로 덮지 않는 검출.

        `max_absorber_area_frac`는 '장면을 덮는 박스'만 걸러낸다(수면 88%). 부유목
        더미(16~45%)처럼 **검출 대상이면서 큰** 객체는 흡수 자격을 유지해야 한다 —
        그 조각까지 미식별로 보내면 관리자가 볼 것이 조각으로 뒤덮인다.
        더미 안의 작은 쓰레기를 지키는 일은 아래 `min_fragment_ratio`가 맡는다.
        """
        if d.get("verdict", "confident") != "confident":
            return False
        if frame_area <= 0 or max_abs >= 1.0:
            return True
        return (_area(d["box"]) / frame_area) <= max_abs

    conf_idx = [i for i, d in enumerate(ovd_dets) if _can_absorb(d)]
    ovd_boxes = [ovd_dets[i]["box"] for i in conf_idx]
    tent_idx = [i for i, d in enumerate(ovd_dets)
                if d.get("verdict", "confident") == "tentative"]

    known, unknown = [], []
    stats = {"match": 0, "fragment": 0, "merged": 0, "unknown": 0, "with_ovd_hint": 0,
             "absorbers": len(conf_idx),
             "too_large_to_absorb": sum(
                 1 for d in ovd_dets
                 if d.get("verdict", "confident") == "confident" and not _can_absorb(d))}

    for item in rpn_items:
        b = item["box"]
        s = item.get("objectness", 1.0)
        tid = item.get("track_id")
        base = {"box": b, "objectness": s, "track_id": tid}

        # 1) 기존 매칭 — 같은 것을 봤다
        best_i, best_v = -1, 0.0
        for i, ob in enumerate(ovd_boxes):
            v = iou(b, ob)
            if v > best_v:
                best_i, best_v = i, v
        if best_v >= match_iou:
            known.append({**base, "ovd_index": conf_idx[best_i], "iou": best_v,
                          "absorbed_by": "match"})
            stats["match"] += 1
            continue

        # 2) 조각 — 후보 면적의 대부분이 한 OVD 박스 안에 있다
        c_i, c_v = -1, 0.0
        for i, ob in enumerate(ovd_boxes):
            v = containment(b, ob)
            if v > c_v:
                c_i, c_v = i, v
        # **조각이려면 그 객체의 상당 부분이어야 한다.** 2026-09-21 실측: 하천에서
        # 미식별 후보의 면적 중앙값은 프레임의 0.347%인데 확신 박스 중앙값은 16.4%다
        # — 작은 쓰레기는 큰 박스의 **2.1%** 크기다. containment만 보면 부유목 더미
        # 위에 얹힌 페트병도 "더미 안에 있으니 더미의 조각"이 되어 삼켜진다.
        # 상대 크기 하한을 두면 조각(더미의 10~30%)은 흡수되고 쓰레기(2%)는 살아남는다
        # (사용자 2026-09-21: "부유목 안으로 다른 클래스가 흡수되지 않도록").
        if c_v >= frag_c and c_i >= 0:
            ratio = _area(b) / max(1e-9, _area(ovd_boxes[c_i]))
            if ratio < min_ratio:
                c_v = 0.0                      # 조각으로 보지 않는다
                stats["kept_small_inside"] = stats.get("kept_small_inside", 0) + 1
        if c_v >= frag_c:
            # **iou는 기록된 짝의 IoU여야 한다.** 여기서 고르는 것은 containment
            # 승자 c_i인데 예전에는 best_v(다른 검출의 IoU)를 적었다. 그 값이
            # 0.849처럼 높게 찍혀 있어 짝이 맞는 것처럼 보였지만 실제로는 두 박스가
            # 거의 겹치지 않았다 — 조용한 거짓말이었다(2026-09-21).
            known.append({**base, "ovd_index": conf_idx[c_i],
                          "iou": round(iou(b, ovd_boxes[c_i]), 3),
                          "containment": round(c_v, 3), "absorbed_by": "fragment"})
            stats["fragment"] += 1
            continue

        # 3) 병합 — 후보가 OVD 박스 여러 개를 상당 부분 덮는다.
        #    각 OVD 박스가 후보 안에 얼마나 들어왔는지로 센다(후보가 크므로
        #    반대 방향 containment를 본다).
        inside = [i for i, ob in enumerate(ovd_boxes)
                  if containment(ob, b) >= merge_cov]
        if len(inside) >= merge_min:
            known.append({**base, "ovd_index": conf_idx[inside[0]],
                          "iou": round(iou(b, ovd_boxes[inside[0]]), 3),
                          "covers_ovd": [conf_idx[i] for i in inside],
                          "absorbed_by": "merged"})
            stats["merged"] += 1
            continue

        # 잠정 OVD와 겹치면 그 라벨을 근거로 싣는다 — 버리지 않는다.
        hint, hv = None, 0.0
        for i in tent_idx:
            v = max(iou(b, ovd_dets[i]["box"]),
                    containment(b, ovd_dets[i]["box"]))
            if v > hv:
                hint, hv = ovd_dets[i], v
        item_out = {**base, "best_iou": best_v, "best_containment": round(c_v, 3)}
        if hint is not None and hv >= match_iou:
            item_out["ovd_hint"] = {"label": hint["label"],
                                    "conf": round(hint["conf"], 3),
                                    "overlap": round(hv, 3)}
            stats["with_ovd_hint"] += 1
        unknown.append(item_out)

    stats["unknown"] = len(unknown)
    return known, unknown, stats


def merge_overlapping(unknown, iou_thresh: float):
    """남은 미지 후보끼리 겹치는 것을 합친다.

    RPN은 같은 대상에 박스를 여러 개 낸다(NMS를 통과해도 남는다). 안 합치면 같은
    것이 crop 여러 장으로 저장되고 오버레이가 박스로 덮인다.

    합칠 때 박스는 **합집합**을 쓰고 objectness는 **최대값**을 쓴다. track_id는
    가장 objectness가 높은 구성원 것을 남긴다 — 말단이 붙일 앵커는 하나여야 한다.
    `merged_from`에 몇 개가 합쳐졌는지 남긴다.
    """
    if iou_thresh <= 0 or len(unknown) < 2:
        return unknown, 0

    order = sorted(range(len(unknown)),
                   key=lambda i: -unknown[i].get("objectness", 0.0))
    used = [False] * len(unknown)
    out = []
    merged_away = 0

    for oi in order:
        if used[oi]:
            continue
        group = [oi]
        used[oi] = True
        for oj in order:
            if used[oj]:
                continue
            if iou(unknown[oi]["box"], unknown[oj]["box"]) >= iou_thresh:
                group.append(oj)
                used[oj] = True
        if len(group) == 1:
            out.append(unknown[oi])
            continue
        members = [unknown[i] for i in group]
        lead = members[0]                      # objectness 최대 (order가 정렬돼 있다)
        out.append({**lead,
                    "box": union_box([m["box"] for m in members]),
                    "objectness": max(m.get("objectness", 0.0) for m in members),
                    "merged_from": len(members)})
        merged_away += len(members) - 1
    return out, merged_away
