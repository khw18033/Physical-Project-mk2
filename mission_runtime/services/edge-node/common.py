"""엣지 공통: 설정 로드와 기하 판정.

implements: AI-C-01, AI-S-04, AI-S-06

설정 로드는 양쪽이 같은 모양이지만 **설정 파일은 서로 다르다** — 말단은 RPN·통신·
추적·스풀만, 엣지는 의미 해석과 저장소만 안다(AI-B-10, AI-C-05). 그래서 이 모듈도
역할별로 갈라 두었고, 각 노드는 자기가 쓰는 함수만 가진다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else HERE / "config.json"
    cfg = json.loads(p.read_text(encoding="utf-8"))
    cfg["_config_path"] = str(p)
    cfg["_root"] = str(p.parent)
    return cfg


def resolve(cfg: dict, rel: str) -> Path:
    """설정 안의 상대경로를 config.json 위치 기준으로 푼다."""
    p = Path(rel)
    return p if p.is_absolute() else (Path(cfg["_root"]) / p).resolve()



# --------------------------------------------------------------------------
# 기하 — 미지 판정이 여기 한 곳에서만 정의된다
# --------------------------------------------------------------------------
def iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / ua if ua > 0 else 0.0


def expand_box(box, context: float, w: int, h: int):
    """crop용 컨텍스트 확대. 1.5배는 zeroshot_crops.py 실측과 같은 값이다."""
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    bw = max(1.0, x2 - x1) * context
    bh = max(1.0, y2 - y1) * context
    return (max(0, int(cx - bw / 2)), max(0, int(cy - bh / 2)),
            min(w, int(cx + bw / 2)), min(h, int(cy + bh / 2)))


def split_known_unknown(rpn_items, ovd_dets, match_iou: float):
    """RPN 후보를 OVD가 설명한 것 / 못 한 것으로 가른다.

    `rpn_items`는 {box, objectness, track_id?} dict 목록이다. box/score만 받으면
    **track_id가 유실된다** — 2026-09-21에 실제로 그 버그로 지연 반영이 0건이었다.
    말단이 판정을 현재 트랙에 붙이려면 이 id가 끝까지 살아 있어야 한다(records.py).

    "OVD에 안 잡힘"은 **미지 객체라는 증거가 아니라 미지 후보**다(AI-S-04).
    OVD 어휘에 없을 뿐인 흔한 물체도, 그냥 배경 오탐도 전부 여기 들어온다 —
    실제로 RPN precision@50은 0.19~0.25로 측정돼 있어 이 집합의 다수는 오탐이다.
    """
    ovd_boxes = [d["box"] for d in ovd_dets]
    known, unknown = [], []
    for item in rpn_items:
        b, s = item["box"], item.get("objectness", 1.0)
        tid = item.get("track_id")
        best_i, best_v = -1, 0.0
        for i, ob in enumerate(ovd_boxes):
            v = iou(b, ob)
            if v > best_v:
                best_i, best_v = i, v
        if best_v >= match_iou:
            known.append({"box": b, "objectness": s, "track_id": tid,
                          "ovd_index": best_i, "iou": best_v})
        else:
            unknown.append({"box": b, "objectness": s, "track_id": tid,
                            "best_iou": best_v})
    return known, unknown
