#!/usr/bin/env python3
"""Fits a depth→cm profile from **reference distances**, or refuses with a reason.

implements: AI-E-02 (검증을 통과한 결과만 프로파일로), AI-B-01 (재측정 강제)
관련: AI-S-08 (선언과 관측의 분리), AI-L-06 (승격 판단에 필요한 정보)

왜 이것이 도구인가
------------------
상대 깊이를 cm 로 바꾸는 계수는 **잴 수밖에 없다.** 그래서 이 저장소에는 계수를
만들어 내는 코드가 없고, 기준 거리를 받아 **맞추는 도구**만 있다. 기준이 없으면
프로파일이 없고, 프로파일이 없으면 거리가 미측정으로 나간다 — 그 사슬이 끊기지
않게 하는 것이 이 파일의 목적이다.

기준 거리는 어디서 오나
-----------------------
셋뿐이고, 어느 것인지가 프로파일의 `status` 로 남는다.

``deployed``
    로봇으로 직접 잰 거리. 가장 강한 근거다.
``provisional``
    다른 경로(미터 깊이 모델, 측량된 랜드마크)를 기준으로 맞춘 것. 쓸 수 있지만
    실측 GT 가 아니고, 승격 판단에서 이 차이가 보여야 한다.
``unfitted``
    기준이 없다. 계수를 비워 두고 거리를 내지 않는다.

**다른 입력 조건에서 맞춘 계수를 가져다 쓰지 않는다**(AI-B-01). 가중치·crop·
전처리·대표값 규칙이 하나라도 다르면 다른 구성이고, 그 사실을 `applies_to` 가
들고 있어서 `measure_distance()` 가 어긋난 조합을 거절한다.

사용
----
    python3 tools/fit_depth_calibration.py samples.json [-o profile.json]

`samples.json` 은 다음 모양이다. `reference_cm` 이 기준 거리이고 이 도구는 그
값을 만들지 않는다.

    {"provider_key": "...", "depth_space": "affine_invariant_inverse",
     "reference_source": "surveyed_landmark | metric_depth_model | tape_measure",
     "input_conditions": {...},
     "samples": [{"rel_depth": 0.0712, "reference_cm": 140.0}, ...]}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

#: 역깊이는 `cm = 1/(p*z + q)` 로 맞춘다. 깊이가 거리에 반비례하므로 이 모양이
#: 맞고, 다항식으로 맞추면 유효 범위 밖에서 음수를 내 0 클램프 유혹이 생긴다.
MODEL_RECIPROCAL = "reciprocal_inverse_depth_to_cm"
MODEL_CUBIC = "cubic_depth_to_cm"

#: 이보다 적은 표본으로는 맞추지 않는다. 2 점이면 항상 완벽히 맞고 그 완벽함은
#: 적합도가 아니라 자유도가 0 인 것이다 — 잔차를 볼 수 없으면 품질을 말할 수 없다.
MIN_SAMPLES = 4

REASON_TOO_FEW = "too_few_reference_samples"
REASON_NO_SPREAD = "reference_distances_have_no_spread"
REASON_DEGENERATE = "fit_is_degenerate"
REASON_UNKNOWN_SPACE = "unknown_depth_space"

#: 기준의 출처 → 그 프로파일이 받을 수 있는 최대 지위.
STATUS_BY_SOURCE = {
    "tape_measure": "deployed",
    "surveyed_landmark": "provisional",
    "metric_depth_model": "provisional",
}


def fit(document: dict) -> dict:
    """표본에서 계수를 맞춘다. 맞출 수 없으면 **사유를 담은 거절**을 돌려준다."""
    space = str(document.get("depth_space", ""))
    samples = [(float(s["rel_depth"]), float(s["reference_cm"]))
               for s in document.get("samples") or ()
               if s.get("rel_depth") is not None and s.get("reference_cm") is not None]

    if space == "affine_invariant_inverse":
        model = MODEL_RECIPROCAL
    elif space == "metric_m":
        model = MODEL_CUBIC
    else:
        return _refused(REASON_UNKNOWN_SPACE, document, len(samples))

    if len(samples) < MIN_SAMPLES:
        return _refused(REASON_TOO_FEW, document, len(samples))
    distances = [cm for _, cm in samples]
    if max(distances) - min(distances) < 20.0:
        # 전부 같은 거리에서 잰 표본으로는 곡선을 맞출 수 없다. 맞춘 것처럼
        # 보이는 계수가 나오고 그 계수는 다른 거리에서 전부 틀린다.
        return _refused(REASON_NO_SPREAD, document, len(samples))

    coefficients, residual_cm = (_fit_reciprocal(samples) if model == MODEL_RECIPROCAL
                                 else _fit_cubic(samples))
    if coefficients is None:
        return _refused(REASON_DEGENERATE, document, len(samples))

    source = str(document.get("reference_source", ""))
    rels = [rel for rel, _ in samples]
    return {
        "profile_id": document.get("profile_id") or f"{document.get('provider_key', '')}.fitted.v1",
        "version": int(document.get("version", 1)),
        "applies_to": {"provider_key": document.get("provider_key", ""),
                       "depth_space": space,
                       **(document.get("input_conditions") or {})},
        "form": ("cm = 1/(p*z + q)" if model == MODEL_RECIPROCAL
                 else "cm = c3*z^3 + c2*z^2 + c1*z + c0"),
        "model": model,
        "coefficients": [round(c, 10) for c in coefficients],
        "roi_percentile": float(document.get("roi_percentile",
                                             60.0 if model == MODEL_RECIPROCAL else 40.0)),
        # 맞춘 범위를 넘겨 쓰지 않는다. 표본이 덮은 구간이 유효 범위다.
        "valid_rel_range": [round(min(rels), 6), round(max(rels), 6)],
        "min_valid_cm": float(document.get("min_valid_cm", 5.0)),
        # 기준이 무엇이었는지가 지위를 정한다. 도구가 올려 주지 않는다.
        "status": STATUS_BY_SOURCE.get(source, "provisional"),
        "source": f"tools/fit_depth_calibration.py ← {source or 'unspecified_reference'}",
        "created_at": str(document.get("created_at", "")),
        "quality": {
            # 측정된 것만 싣는다. 잔차는 쟀으니 들어가고, 재지 않은 항목은 키가 없다.
            "fit_residual_cm_rms": round(residual_cm, 3),
            "sample_count": len(samples),
            "fitted_rel_span": round(max(rels) - min(rels), 6),
        },
    }


def _refused(reason: str, document: dict, sample_count: int) -> dict:
    """거절도 프로파일 모양으로 낸다 — **계수가 비어 있고 사유가 적혀 있다.**

    모양을 맞춰 두면 선언 파일에 그대로 넣을 수 있고, `load_calibration_profiles`
    가 식 없는 프로파일로 읽어 거리를 `unmeasured_no_fitted_formula` 로 낸다.
    빈 파일이나 예외로 끝내면 그 사실이 어디에도 남지 않는다.
    """
    return {
        "profile_id": document.get("profile_id") or f"{document.get('provider_key', '')}.unfitted",
        "version": int(document.get("version", 1)),
        "applies_to": {"provider_key": document.get("provider_key", ""),
                       "depth_space": document.get("depth_space", ""),
                       **(document.get("input_conditions") or {})},
        "form": "", "model": "", "coefficients": [],
        "roi_percentile": float(document.get("roi_percentile", 50.0)),
        "valid_rel_range": [0.0, 0.0],
        "min_valid_cm": float(document.get("min_valid_cm", 5.0)),
        "status": "unfitted",
        "source": f"tools/fit_depth_calibration.py 거절: {reason}",
        "created_at": str(document.get("created_at", "")),
        "refusal_reason": reason,
        "quality": {"sample_count": sample_count},
    }


def _fit_reciprocal(samples) -> tuple[list[float] | None, float]:
    """`1/cm = p*z + q` 는 **1/cm 에 대해 선형**이라 최소제곱이 닫힌 형태다."""
    xs = [rel for rel, _ in samples]
    ys = [1.0 / cm for _, cm in samples if cm]
    if len(ys) != len(xs):
        return None, 0.0
    n = len(xs)
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denominator = n * sxx - sx * sx
    if abs(denominator) < 1e-18:
        return None, 0.0
    p = (n * sxy - sx * sy) / denominator
    q = (sy - p * sx) / n
    residuals = []
    for rel, cm in samples:
        value = p * rel + q
        if abs(value) < 1e-12:
            return None, 0.0
        residuals.append((1.0 / value) - cm)
    rms = (sum(r * r for r in residuals) / len(residuals)) ** 0.5
    return [p, q], rms


def _fit_cubic(samples) -> tuple[list[float] | None, float]:
    """미터 공간은 3차로 맞춘다. numpy 가 없으면 **맞추지 않는다**(추정하지 않는다)."""
    try:
        import numpy as np
    except ImportError:
        return None, 0.0
    xs = np.array([rel for rel, _ in samples], dtype=float)
    ys = np.array([cm for _, cm in samples], dtype=float)
    if len(xs) < 4:
        return None, 0.0
    coefficients = np.polyfit(xs, ys, 3)
    rms = float(np.sqrt(np.mean((np.polyval(coefficients, xs) - ys) ** 2)))
    return [float(c) for c in coefficients], rms


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("samples", type=Path, help="기준 거리가 담긴 JSON")
    parser.add_argument("-o", "--out", type=Path, default=None,
                        help="프로파일을 쓸 자리(기본: 표준출력)")
    args = parser.parse_args(argv)

    document = json.loads(args.samples.read_text(encoding="utf-8"))
    profile = fit(document)
    text = json.dumps(profile, ensure_ascii=False, indent=2) + "\n"
    if args.out is not None:
        args.out.write_text(text, encoding="utf-8")
        print(f"{args.out} 에 썼다 — status={profile['status']}")
    else:
        print(text, end="")
    # 거절이면 0 이 아닌 코드로 끝낸다. 파이프라인이 "맞췄다" 로 읽으면 안 된다.
    return 1 if profile.get("refusal_reason") else 0


if __name__ == "__main__":
    sys.exit(main())
