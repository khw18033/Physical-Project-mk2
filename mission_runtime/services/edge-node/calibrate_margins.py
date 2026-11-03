"""CLIP 판정 임계(background_margin / confident_margin) 재보정.

implements: AI-B-01, AI-S-03, AI-S-04, AI-O-01

왜 필요한가: 두 margin은 int8 ONNX 점수 분포에서 눈대중으로 잡은 값이다. 2026-09-21에
CLIP 백엔드를 torch CUDA fp16으로 바꾸면서 **점수 척도가 달라졌다**(같은 crop에서
int8 임베딩과 코사인 0.879). AI-B-01은 다른 구성의 측정값을 자동으로 전이하지 말라고
요구하므로 임계도 새 분포에서 다시 잡아야 한다.

이 스크립트는 `store/unknown_crops/*.json`에 남은 **실제 판정 근거**를 읽는다.
새로 추론하지 않으므로 파이프라인이 실제로 본 분포 그대로다.

무엇을 보는가:
  * `top1_gap` 분포 — 1등과 2등의 차이. 두 margin이 모두 이 값을 자른다.
  * 1등이 배경 클래스인 경우와 아닌 경우의 gap 분포를 **따로** 본다. 두 분포가
    겹치면 하나의 임계로는 가를 수 없다는 뜻이고, 그 사실 자체가 결과다.
  * 임계 후보별로 background / undecided / confident가 몇 개가 되는지.

**이 스크립트는 정답을 고르지 않는다.** 배경 crop의 정답 라벨이 없으므로 정밀도를
계산할 수 없고, 분포와 그 임계에서 생기는 결과만 보여준다. 최종 선택은 사람이 한다
(AI-C-19: AI는 판단 근거를 제공하고 결정은 담당 주체가 한다).
"""

from __future__ import annotations

import glob
import json
import sys

import numpy as np


def load(background_classes: set[str]):
    rows = []
    for f in sorted(glob.glob("store/unknown_crops/*.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        clip = d.get("clip") or {}
        rank = clip.get("ranking") or []
        if len(rank) < 2:
            continue
        rows.append({
            "top1": rank[0]["class"],
            "top1_score": rank[0]["score"],
            "top2_score": rank[1]["score"],
            "gap": clip.get("top1_gap", rank[0]["score"] - rank[1]["score"]),
            "is_bg_top1": rank[0]["class"] in background_classes,
            "objectness": d.get("objectness"),
        })
    return rows


def pct(a, qs=(5, 10, 25, 50, 75, 90, 95)):
    return {f"p{q}": round(float(np.percentile(a, q)), 4) for q in qs}


def main() -> None:
    cfg = json.load(open("config.json", encoding="utf-8"))
    # 배경 목록은 사전이 선언한다 — config에 두었다가 어긋난 적이 있다(2026-09-21).
    dom = cfg["clip"].get("active_domain", "urban")
    dpath = cfg["clip"]["domains"][dom]["dictionary"]
    fdict = json.load(open(dpath, encoding="utf-8"))
    bg = {k for k, v in fdict.items() if not k.startswith("_") and v.get("background")}
    cur_bg = float(cfg["clip"].get("background_margin", 0.010))
    cur_cf = float(cfg["clip"].get("confident_margin", 0.030))
    backend = cfg["clip"].get("backend")

    rows = load(bg)
    if not rows:
        sys.exit("store/unknown_crops/*.json 이 없다. 파이프라인을 먼저 돌린다.")

    gaps = np.array([r["gap"] for r in rows])
    bg_gaps = np.array([r["gap"] for r in rows if r["is_bg_top1"]])
    ob_gaps = np.array([r["gap"] for r in rows if not r["is_bg_top1"]])
    s1 = np.array([r["top1_score"] for r in rows])

    print(f"백엔드 {backend} · crop {len(rows)}개 (배경 1등 {len(bg_gaps)} / "
          f"비배경 1등 {len(ob_gaps)})")
    print(f"현재 임계: background_margin {cur_bg} / confident_margin {cur_cf}\n")

    print("top1 점수 분포 :", pct(s1))
    print("top1_gap 전체  :", pct(gaps))
    if len(bg_gaps):
        print("  1등=배경     :", pct(bg_gaps))
    if len(ob_gaps):
        print("  1등=비배경   :", pct(ob_gaps))

    # 두 분포가 겹치면 단일 임계로 못 가른다 — 그 사실을 수치로 보여준다.
    if len(bg_gaps) and len(ob_gaps):
        overlap = float(np.mean(ob_gaps[:, None] > bg_gaps[None, :]))
        print(f"\n비배경 gap이 배경 gap보다 큰 비율: {overlap:.3f} "
              f"(0.5면 두 분포가 구분되지 않는다는 뜻)")

    print("\n임계 후보별 결과 (background_margin, confident_margin):")
    print("%-22s %10s %10s %10s" % ("(bg, cf)", "background", "undecided", "confident"))
    for bm in (0.002, 0.005, 0.010, 0.020, 0.030):
        for cm in (0.010, 0.020, 0.030, 0.050, 0.080):
            if cm < bm:
                continue
            nb = sum(1 for r in rows if r["is_bg_top1"] and r["gap"] >= bm)
            nc = sum(1 for r in rows if (not r["is_bg_top1"]) and r["gap"] >= cm)
            nu = len(rows) - nb - nc
            print("%-22s %10d %10d %10d" % (f"({bm:.3f}, {cm:.3f})", nb, nu, nc))

    print("\n권고 근거 — 아래 값은 '정답'이 아니라 분위수다. 배경 crop의 정답 라벨이")
    print("없어 정밀도를 계산할 수 없으므로 이 스크립트는 선택하지 않는다.")
    if len(bg_gaps):
        print(f"  배경 1등 gap 중앙값 {np.median(bg_gaps):.4f} "
              f"→ background_margin을 이보다 낮추면 배경을 더 많이 버린다")
    if len(ob_gaps):
        print(f"  비배경 1등 gap p75 {np.percentile(ob_gaps,75):.4f} "
              f"→ confident_margin을 이보다 높이면 확신이 상위 25% 미만으로 줄어든다")

    json.dump({
        "backend": backend, "n": len(rows),
        "current": {"background_margin": cur_bg, "confident_margin": cur_cf},
        "top1_score": pct(s1), "gap_all": pct(gaps),
        "gap_bg_top1": pct(bg_gaps) if len(bg_gaps) else None,
        "gap_obj_top1": pct(ob_gaps) if len(ob_gaps) else None,
    }, open("calibrate_margins_results.json", "w", encoding="utf-8"),
        ensure_ascii=False, indent=1)
    print("\n→ calibrate_margins_results.json")


if __name__ == "__main__":
    main()
