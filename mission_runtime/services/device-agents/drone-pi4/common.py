"""말단(pi4) 공통: 설정 로드와 후보 후처리.

implements: AI-C-01, AI-C-06, AI-B-10

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


def edge_url(cfg: dict, path: str) -> str:
    """업무 메타와 미디어 프레임을 함께 싣는 엣지 종단점.

    AI-C-06: 이 슬라이스는 HTTP 하나를 쓰지만 페이로드는 meta(업무)와 frame(미디어)로
    **나눠서** 실린다. 실제 배포에서 meta를 MQTT, frame을 별도 미디어 경로로 옮길 때
    고칠 곳은 이 함수와 전송부뿐이고 판정 로직은 그대로다.
    """
    e = cfg["edge"]
    return f"http://{e['host']}:{e['port']}{path}"


def filter_candidates(boxes, scores, cfg_rpn: dict, w: int, h: int):
    """objectness·면적 필터 + top_n.

    면적 필터가 있는 이유는 실측이다: 2026-09-21 VisDrone 10장에서 상위 100개가
    건물 전면 같은 거대 박스로 쏠렸다(`rpn_visdrone_pi4.json`). 이건 recall 문제가
    아니라 **랭킹** 문제라, 모델을 바꾸지 않고 후처리에서 먼저 확인해 본다.
    기본값을 끄고 싶으면 config에서 max_box_area_frac=1.0으로 둔다.
    """
    min_obj = float(cfg_rpn.get("min_objectness", 0.0))
    max_frac = float(cfg_rpn.get("max_box_area_frac", 1.0))
    top_n = int(cfg_rpn.get("top_n", 100))
    frame_area = float(w * h) or 1.0

    out_b, out_s = [], []
    for b, s in zip(boxes, scores):
        if s < min_obj:
            continue
        area = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
        if area / frame_area > max_frac:
            continue
        out_b.append(b)
        out_s.append(s)
        if len(out_b) >= top_n:
            break
    return out_b, out_s
