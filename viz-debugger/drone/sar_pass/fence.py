"""패스 동안만 쓰는 지오펜스 — 제어 코드가 잘못돼도 기체가 패스 구역 밖으로 못 나간다.

울타리 = (선의 가속 구간 앞 ~ 감속 구간 뒤) × (좌우 여유) 사각형에 **지금 기체 위치**를 더한 볼록 껍질.
지금 위치에서 시작점까지 가는 길도 껍질 안이라 이동 중에 걸리지 않는다.

PX4 는 울타리를 넘으면 `GF_ACTION` 대로 한다(기본 2 = Hold). Hold 가 되면 임무는 「조종기 개입」과 같이 멈추고
CAP_ON 을 지운다. 끝나면(어떤 이유로든) **원래 있던 울타리로 되돌린다** — QGC 로 넣어 둔 울타리를 지우지 않는다.
"""

from __future__ import annotations


def _hull(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """볼록 껍질 (Andrew monotone chain) — 반시계."""
    pts = sorted(set(pts))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):  # noqa: ANN001, ANN202
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def fence_polygon(plan, here_lat: float, here_lon: float, margin_m: float | None = None) -> list[tuple[float, float]]:  # noqa: ANN001
    """패스 울타리 꼭짓점 [(lat, lon), …]. 여유는 횡 허용 · 기록 여유보다 넉넉하게(기본 15 m)."""
    m = plan.fence_margin_m if margin_m is None else margin_m
    line = plan.line
    frame = line.frame
    un, ue = line.unit
    rn, re = -ue, un                                    # 오른쪽
    decel = plan.speed_mps ** 2 / (2 * plan.accel_mps2) + plan.speed_mps * 2     # 감속 + 반응
    from .mission import MAX_EXTRA_LEAD_M
    a0 = -(plan.effective_lead_in_m + MAX_EXTRA_LEAD_M + m)     # 적응형 가속 구간이 최대로 늘어도 안쪽
    a1 = line.length_m + decel + m
    pts = [(un * a + rn * c, ue * a + re * c) for a in (a0, a1) for c in (-m, m)]
    hn, he = frame.to_local(here_lat, here_lon)
    pts += [(hn + dn, he + de) for dn in (-m / 2, m / 2) for de in (-m / 2, m / 2)]
    return [frame.to_global(n, e) for n, e in _hull(pts)]


def inside(poly: list[tuple[float, float]], lat: float, lon: float) -> bool:
    """점이 다각형 안인가 (짝홀 규칙, 수백 m 안에서는 위경도 평면으로 충분)."""
    hit = False
    j = len(poly) - 1
    for i in range(len(poly)):
        yi, xi = poly[i]
        yj, xj = poly[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-15) + xi:
            hit = not hit
        j = i
    return hit


__all__ = ["fence_polygon", "inside"]
