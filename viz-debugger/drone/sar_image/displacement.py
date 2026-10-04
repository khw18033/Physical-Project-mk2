"""같은 선 두 패스 → 리플렉터별 **시선 방향 변위(mm)** — 반복 패스 간섭(리플렉터 InSAR).

원리. 백프로젝션 영상의 한 점 값은 exp(j·4π(R_격자 − R_실제)/λ) 를 따른다. 리플렉터가 레이더 쪽으로 d 만큼 다가오면
R_실제 가 d 줄어 위상이 4πd/λ 늘어난다:

    d_시선 = λ · Δφ / (4π)        (+ = 레이더 쪽으로 다가옴)

5.8 GHz(λ ≈ 51.7 mm)면 위상 1° 가 0.07 mm. 대신 ±λ/4 ≈ ±12.9 mm 를 넘으면 한 바퀴 돌아 헷갈린다(모호성).

두 패스의 궤적 오차(RTK 수 mm~cm)도 위상에 실린다. **움직이지 않은 리플렉터**들로 지운다:
  - 셋 이상이면 Δφ = c0 + c1·along + c2·cross 평면을 맞춰 뺀다(궤적이 통째로 어긋난 몫은 장면에서 매끈하다).
    맞춘 뒤 남은 값(안 움직인 리플렉터들의 잔차 RMS)이 **이번 측정의 실제 정밀도**다.
  - 둘이면 기준 하나를 뺀다(along 방향 기울기는 못 지운다). 하나뿐이면 참고값.

  - 위상은 **자동 초점 전** 데이터로 잰다(pipeline 이 `phase_rad` 로 적는다). 자동 초점은 패스마다 위상 기준을 따로 잡는다.
  - 움직인 리플렉터는 `af_exclude` 로 적어 둔다 — 기준 · 평면 맞추기에서 빠진다.
  - 정밀도(잡음만): σφ ≈ 1/√(2·SCR) (SCR = 리플렉터 대 둘레 바닥 전력비) → σd = λ/(4π)·√(σφa² + σφb²).
  - 시선은 비스듬하다(입사각 θ). 수평으로 선에서 멀어지면 시선 변위는 −d_h·sinθ, 위로 들리면 +d_v·cosθ.
"""

from __future__ import annotations

import math

import numpy as np


def _wrap(x: float) -> float:
    return (x + math.pi) % (2 * math.pi) - math.pi


def _sigma_phase(contrast_db: float | None) -> float:
    """리플렉터 대비(진폭 dB) → 위상 잡음 표준편차(rad). 대비를 모르면 크게."""
    if contrast_db is None:
        return 1.0
    scr = 10 ** (float(contrast_db) / 10.0)
    return min(1.0, 1.0 / math.sqrt(2.0 * max(scr, 1e-6)))


def measure(ja: dict, jb: dict, reference: str | None = None, moved: list[str] | None = None) -> dict:
    """두 image.json → 리플렉터별 변위.

    reference: 기준 리플렉터 이름(CR1 …) — 없으면 안 움직인 것 중 가장 밝은 것.
    moved: 움직였다고 아는 리플렉터 이름 — 없으면 두 image.json 의 af_exclude.
    """
    lam = float((ja.get("radar") or {}).get("wavelength_m") or 0.0)
    if lam <= 0:
        raise ValueError("파장(wavelength_m)을 모른다")
    k = lam / (4 * math.pi) * 1000.0                  # rad → mm
    head = {"schema": "sar-disp-0.1", "wavelength_m": lam, "ambiguity_mm": round(lam / 4 * 1000, 2),
            "sign": "+ = 레이더 쪽으로 다가옴(시선 거리 줄어듦)"}
    ra = {r["name"]: r for r in ja.get("reflectors", [])}
    rb = {r["name"]: r for r in jb.get("reflectors", [])}
    both = [n for n in ra if n in rb and ra[n].get("found") and rb[n].get("found")
            and ra[n].get("phase_rad") is not None and rb[n].get("phase_rad") is not None]
    if moved is None:
        moved_set = {f"CR{int(i)}" for j in (ja, jb) for i in (j.get("af_exclude") or [])}
    else:
        moved_set = set(moved)
    notes: list[str] = []
    if not both:
        return {**head, "reference": None, "method": None, "reflectors": [], "notes": ["두 패스에서 다 찍힌 리플렉터가 없다"]}
    still = [n for n in both if n not in moved_set]
    if not still:
        dphi = {n: _wrap(float(rb[n]["phase_rad"]) - float(ra[n]["phase_rad"])) for n in both}
        out = [{"name": n, "reference": False, "moved_flag": n in moved_set, "dphi_deg": round(math.degrees(dphi[n]), 2),
                "los_mm": round(dphi[n] * k, 2), "sigma_mm": None, "contrast_db": [ra[n].get("contrast_db"), rb[n].get("contrast_db")]}
               for n in both]
        return {**head, "reference": None, "method": "none", "stable_rms_mm": None, "reflectors": out,
                "notes": ["움직이지 않은 리플렉터가 없다 — 궤적 오차(RTK)가 그대로 실린 참고값이다"]}
    ref = reference if reference in still else max(
        still, key=lambda n: min(ra[n].get("contrast_db") or 0, rb[n].get("contrast_db") or 0))
    if reference and reference != ref:
        notes.append(f"기준 {reference} 은 쓸 수 없어(안 찍힘 · 움직임) {ref} 로 바꿨다")

    dphi = {n: _wrap(float(rb[n]["phase_rad"]) - float(ra[n]["phase_rad"])) for n in both}
    rel = {n: _wrap(dphi[n] - dphi[ref]) for n in both}           # 기준을 뺀 것
    pos = {n: (float(ra[n].get("along_m") or 0.0), float(ra[n].get("cross_m") or 0.0)) for n in both}

    method, stable_rms_mm = "reference", None
    corr = {n: 0.0 for n in both}
    if len(still) >= 3:
        # 맞출 항: 상수 + (리플렉터가 along 으로 퍼져 있으면) along + (cross 로 퍼져 있으면) cross
        terms = [lambda n: 1.0]
        if np.ptp([pos[n][0] for n in still]) >= 0.5:
            terms.append(lambda n: pos[n][0])
        if np.ptp([pos[n][1] for n in still]) >= 0.5:
            terms.append(lambda n: pos[n][1])
        A = np.array([[f(n) for f in terms] for n in still])
        c, *_ = np.linalg.lstsq(A, np.array([rel[n] for n in still]), rcond=None)
        corr = {n: float(sum(ci * f(n) for ci, f in zip(c, terms))) for n in both}
        res = np.array([_wrap(rel[n] - corr[n]) for n in still])
        dof = len(still) - len(terms)
        stable_rms_mm = round(float(np.sqrt(np.sum(res ** 2) / dof)) * k, 2) if dof > 0 else None
        method = {3: "plane", 2: "line", 1: "reference"}[len(terms)]
        if dof <= 0:
            notes.append("안 움직인 리플렉터 수가 맞출 값 수와 같아 정밀도(잔차)를 못 잰다 — 하나 더 두면 잰다")
    elif len(still) == 2:
        notes.append("안 움직인 리플렉터가 둘 — 기준 하나만 뺀다(궤적 기울기는 남는다). 셋 이상이면 평면으로 지운다")
    else:
        notes.append("안 움직인 리플렉터가 하나뿐 — 궤적 오차가 그대로 실린 참고값이다")

    out = []
    for n in both:
        d = _wrap(rel[n] - corr[n])
        sig = math.hypot(_sigma_phase(ra[n].get("contrast_db")), _sigma_phase(rb[n].get("contrast_db")))
        alt, cross = ja.get("flight_alt_m"), pos[n][1]
        inc = math.degrees(math.atan2(abs(cross), float(alt))) if alt else None
        out.append({"name": n, "reference": n == ref, "moved_flag": n in moved_set,
                    "dphi_deg": round(math.degrees(dphi[n]), 2),
                    "los_mm": round(d * k, 2), "sigma_mm": round(sig * k, 2),
                    "along_m": round(pos[n][0], 2), "cross_m": round(pos[n][1], 2),
                    "incidence_deg": None if inc is None else round(inc, 1),
                    "contrast_db": [ra[n].get("contrast_db"), rb[n].get("contrast_db")]})
    return {**head, "reference": ref, "method": method, "stable_rms_mm": stable_rms_mm,
            "reflectors": out, "notes": notes}


__all__ = ["measure"]
