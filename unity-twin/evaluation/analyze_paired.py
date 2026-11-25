"""가상 실험 짝지은 분석: A(로봇 탐지+정지 재탐색) / B(로봇 탐지+무정지 교체) / C(인프라 탐지+무정지 교체).

사용: python analyze_paired.py <세션 폴더 | runs.csv> [<세션 폴더> ...]
출력: 콘솔 요약 + 첫 세션 폴더의 paired_summary.csv, condition_summary.csv

포함 규칙(사전 고정): 같은 session, 같은 trial 안에서 비교하는 두 조건의 run이 모두 있고,
두 run 모두 실제 장애물이 등장했으며(appear_t >= 0), end_reason이 infra_/rollout_으로
시작하지 않는 trial만 짝으로 쓴다. 시간과 정지는 장애물 등장 시점(appear) 기준이다.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

PAIRS = [("C_InfraNoStop", "A_RobotStop"), ("C_InfraNoStop", "B_OnboardReplan"),
         ("C_InfraNoStop", "D_OnboardDStarLite"), ("C_InfraNoStop", "E_OnboardDWA"),
         ("C_InfraNoStop", "O_KnownAtStart"), ("B_OnboardReplan", "A_RobotStop")]
# 접촉 판정: 몸체 중심에서 실제 장애물 표면까지 거리가 시뮬 로봇 충돌 반경(0.162 m)보다 작을 때
BODY_RADIUS = 0.162
CONT = [
    ("t_total", "재주행 시작~종료 시간 (s)"),
    ("t_after_appear", "장애물 등장~종료 시간 (s)"),
    ("stopped_after_appear", "장애물 등장 후 정지 시간 (s)"),
    ("stopped_wait", "그중 재탐색 대기로 선 시간 (s)"),
    ("stopped_turn", "그중 제자리 회전 시간 (s)"),
    ("stop_events", "장애물 등장 후 정지 횟수"),
    ("travel", "주행 거리 (m)"),
    ("min_clearance_obs", "실제 장애물 최소 간격 (m)"),
]


def load(args):
    frames = []
    for a in args:
        p = Path(a)
        csv = p / "runs.csv" if p.is_dir() else p
        df = pd.read_csv(csv)
        df["session"] = csv.parent.name
        frames.append(df)
    first = Path(args[0])
    return pd.concat(frames, ignore_index=True), (first if first.is_dir() else first.parent)


def bootstrap_ci(d, n=10000, seed=0):
    if len(d) == 0:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    med = np.median(rng.choice(d, size=(n, len(d)), replace=True), axis=1)
    return tuple(np.percentile(med, [2.5, 97.5]))


def usable(df):
    bad = df["end_reason"].astype(str).str.startswith(("infra_", "rollout_"))
    return df[~bad & (df["appear_t"] >= 0)]


def condition_table(df):
    rows = []
    for (place, nobs, lat, sigma, cond), g in usable(df).groupby(["placement", "obstacle_count", "detect_latency", "noise_sigma", "condition"]):
        ok = g[g.success == 1]
        rows.append({
            "placement": place, "obstacles": nobs, "latency": lat, "noise_sigma": sigma, "condition": cond, "n": len(g),
            "detected_n_mean": g.detected_count.mean(),
            "detected": (g.spawned == 1).mean(),
            "detect_dist_med": g.detect_actual_dist[g.detect_actual_dist >= 0].median(),
            "plan_ms_med": g.plan_ms_mean[g.plan_ms_mean >= 0].median(),
            "success": g.success.mean(),
            "contact_rate": ((g.min_clearance_obs >= 0) & (g.min_clearance_obs < BODY_RADIUS)).mean(),
            "detour_rate": g.detour_exists.mean(),
            "stop_events_med": ok.stop_events.median(),
            "stopped_after_appear_med": ok.stopped_after_appear.median(),
            "stopped_wait_med": ok.stopped_wait.median(),
            "stopped_turn_med": ok.stopped_turn.median(),
            "t_after_appear_med": ok.t_after_appear.median(),
            "t_total_med": ok.t_total.median(),
            "travel_med": ok.travel.median(),
            "min_clearance_obs_med": ok.min_clearance_obs.median(),
            "min_clearance_obs_min": g.min_clearance_obs[g.min_clearance_obs >= 0].min(),
            "switches_med": g.switches.median(),
            "stop_replans_med": g.stop_replans.median(),
            "fallback_runs": int((g.fallbacks > 0).sum()),
        })
    return pd.DataFrame(rows)


def paired(df, x_name, y_name):
    u = usable(df)
    u = u.assign(key=u["session"] + ":" + u["trial"].astype(str))
    x = u[u.condition == x_name].drop_duplicates("key").set_index("key")
    y = u[u.condition == y_name].drop_duplicates("key").set_index("key")
    keys = x.index.intersection(y.index)
    x, y = x.loc[keys], y.loc[keys]
    out = []
    if len(keys) == 0:
        return out
    sx, sy = x.success.astype(int), y.success.astype(int)
    b, c = int(((sx == 1) & (sy == 0)).sum()), int(((sx == 0) & (sy == 1)).sum())
    out.append({"compare": f"{x_name} - {y_name}", "measure": "success", "x": sx.mean(), "y": sy.mean(),
                "diff": sx.mean() - sy.mean(), "test": f"McNemar exact (b={b}, c={c})",
                "p": stats.binomtest(b, b + c, 0.5).pvalue if b + c > 0 else 1.0, "n": len(keys)})
    both = (sx == 1) & (sy == 1)
    for col, label in CONT:
        a, bb = x.loc[both, col].astype(float), y.loc[both, col].astype(float)
        ok = (a >= 0) & (bb >= 0)
        a, bb = a[ok], bb[ok]
        d = (a - bb).to_numpy()
        p = stats.wilcoxon(a, bb).pvalue if len(d) > 0 and np.any(d != 0) else np.nan
        lo, hi = bootstrap_ci(d)
        out.append({"compare": f"{x_name} - {y_name}", "measure": col, "label": label,
                    "x": a.median() if len(a) else np.nan, "y": bb.median() if len(bb) else np.nan,
                    "diff": np.median(d) if len(d) else np.nan, "ci_lo": lo, "ci_hi": hi,
                    "test": "Wilcoxon signed-rank (median, both succeeded)", "p": p, "n": len(d)})
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    df, outdir = load(sys.argv[1:])
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(f"runs {len(df)} | 쓸 수 있는 run {len(usable(df))}")
    print(df.groupby(["placement", "obstacle_count", "detect_latency", "noise_sigma", "condition", "end_reason"]).size().to_string())

    ct = condition_table(df)
    print("\n== 조건별 요약 (중앙값은 성공한 run만) ==")
    print(ct.to_string(index=False, float_format=lambda v: f"{v:.3g}"))
    ct.to_csv(outdir / "condition_summary.csv", index=False, encoding="utf-8-sig")

    rows = []
    for (place, nobs, lat, sigma), g in df.groupby(["placement", "obstacle_count", "detect_latency", "noise_sigma"]):
        for x_name, y_name in PAIRS:
            for r in paired(g, x_name, y_name):
                rows.append({"placement": place, "obstacles": nobs, "latency": lat, "noise_sigma": sigma, **r})
    if rows:
        ps = pd.DataFrame(rows)
        print("\n== 짝지은 비교 (x - y) ==")
        print(ps.drop(columns=["label"], errors="ignore").to_string(index=False, float_format=lambda v: f"{v:.4g}"))
        ps.to_csv(outdir / "paired_summary.csv", index=False, encoding="utf-8-sig")
    print("\n저장:", outdir)


if __name__ == "__main__":
    main()
