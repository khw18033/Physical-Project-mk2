"""외부 파라미터 — 카메라가 **어디 있고 어디를 보는가**, 그리고 그 값이 얼마나 틀렸는가.

implements: AI-E-02
관련: AI-C-02 (좌표계 경계·미측정 정확도), AI-S-08 (사전정보와 관측의 분리),
      AI-C-19 (AI 는 판정 근거를 내고 장치 제어를 소유하지 않는다)
tests: tests/test_calibration_extrinsics.py

조사 정본은 `docs/research/automatic-camera-calibration.md` 다. 이 모듈은 그 문서가
**§2 에서 남긴 두 번째 구멍**을 메운다 — "외부 파라미터를 누가 추정하는가".

내부 파라미터 기법 어느 것도 이것을 주지 않는다. Zhang 은 보정판의 자세를 주고,
자기보정은 뷰 사이 회전을 주고, 광선 회귀기는 방향장을 준다 — 전부 **카메라 기준**
값이다. 구역 좌표에서 카메라가 어디 있는지는 구역 좌표를 아는 무언가가 있어야 풀린다.

### 방법 — 앵커 방위 기반 2D 재단면 교회법(resection)

입력은 둘이다. (a) 구역 로컬 좌표를 아는 앵커 3개 이상(측량된 기둥·문틀·표지), (b) 그
앵커가 영상에서 보이는 **방위각**. 방위각은 내부 파라미터가 있어야 픽셀에서 환산되므로
(`atan2(u - cx, fx)`), 이 모듈은 내부 파라미터의 **하류**다 — 그래서 내부 파라미터가
없는 카메라는 외부 파라미터도 없고, 그것이 정상 상태다.

미지수는 셋(x, y, yaw)이고 앵커 하나가 방정식 하나를 준다. 그래서 3개가 최소이고,
4개 이상이면 잔차가 생겨 **잡음을 측정할 수 있다.**

### 이 모듈의 핵심은 추정값이 아니라 정확도다

문서 §1 의 마지막 줄이 조사 결과를 가장 많이 걸러낸 기준이었다 — 논문들은 추정값을
내고 그 추정값이 얼마나 틀렸는지는 내지 않는다. 외부 파라미터는 그 기준을 만족시킬 수
있는 **유일한 축**이다(문서 §9.4): 잔차의 Jacobian 에서 공분산이 표준 경로로 나온다
(`Σ = σ² (JᵗJ)⁻¹`, Hartley Ch.7 계열).

그래서 `accuracy_basis` 를 세 값으로 **구분한다**:

- `residual_measured` — 앵커가 4개 이상이고 잔차가 0 이 아니다. σ 를 잔차에서 쟀다.
  이것만이 "측정된 정확도" 다.
- `declared_bearing_noise` — 호출자가 방위 잡음을 선언했고 그것을 전파했다. 선언값의
  전파이므로 측정이 아니다(AI-S-08). 선언이 틀리면 정확도도 틀린다.
- `unmeasured` — 둘 다 없다. **정확도는 None 이고 0 이 아니다**(AI-C-02). 0 이면
  무한 가중이 되어 사람이 줄자로 잰 값을 이긴다(`perception/spatial_evidence.py` 규칙 2).

### 퇴화 — "위험원(danger circle)"

문서 §9.4 는 "앵커가 공선이거나" 퇴화한다고 적었다. **실측으로 확인한 결과 2D 방위
교회법에서는 그 서술이 반대다**(아래 `DANGER_CIRCLE_MARGIN_FLOOR` 주석 참고): 공선 배치는
오히려 잘 조건화되고, 실제 퇴화는 **카메라가 앵커 셋의 외접원 위에 있을 때**다. 그 원
위에서는 세 앵커의 내각이 원주각으로 같아져 위치가 결정되지 않는다 — 고전 측량에서
`위험원` 으로 불리는 조건이다. 공선 앵커의 "외접원" 은 직선이므로 그 직선 위에 카메라가
없으면 퇴화하지 않는다.

이 모듈은 그래서 두 가지를 모두 낸다: 위험원 근접도(기하 진단)와 공분산(결과 진단).
전자는 왜 정확도가 나쁜지를 설명하고 후자는 얼마나 나쁜지를 말한다.

### 전역 좌표가 아니다

산출은 **구역 로컬** (x_m, y_m, yaw_deg) 이다. 전역 변환은 site datum 을 거치는 별도
계층이고(AI-C-02, 2026-11-03 개정) datum 이 없는 현장은 정상 배치다. 로컬 값과 전역
값을 같은 칸에 담지 않는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

__all__ = [
    "ACCURACY_BASES",
    "EXTRINSIC_REJECTION_REASONS",
    "DANGER_CIRCLE_MARGIN_FLOOR",
    "AnchorBearing",
    "AnchorBearingExtrinsics",
    "ExtrinsicEstimate",
    "bearing_from_pixel",
]

#: `ExtrinsicEstimate.accuracy_basis` 의 값 어휘. **서열이 있다** — 측정이 선언을
#: 이기고 선언이 모름을 이긴다. `unmeasured` 는 0 도 아니고 "제한 없음" 도 아니다.
#: `contracts/data_dictionary.py` 의 `ACCURACY_LIMITS` 와 **다른 축이다**: 그쪽은
#: 무엇이 정확도를 제한하는가를 말하고 이쪽은 정확도를 어디서 얻었는가를 말한다.
ACCURACY_BASES: tuple[str, ...] = (
    "residual_measured",
    "declared_bearing_noise",
    "unmeasured",
)

#: 외부 파라미터가 프로파일이 되지 못하는 사유.
EXTRINSIC_REJECTION_REASONS: tuple[str, ...] = (
    "too_few_anchors",              # 3개 미만 — 미지수보다 방정식이 적다
    "duplicate_anchor_id",          # 같은 앵커를 두 번 넣으면 질량이 두 배가 된다
    "anchor_geometry_degenerate",   # 위험원 근접 — 기하가 위치를 결정하지 않는다
    "bearing_residual_exceeded",    # 적합이 방위를 설명하지 못한다
    "normal_matrix_singular",       # (JᵗJ) 를 뒤집을 수 없다
    "accuracy_unmeasured",          # 값은 나왔지만 정확도를 재지 못했다
)

#: 카메라와 앵커 외접원의 상대 거리 하한. `|d(center) - radius| / radius` 가 이 값보다
#: 작으면 위험원 근접으로 본다. 0.05 는 합성 실측에서 정한 값이다 — 직사각형 앵커 넷의
#: 외접원에 2% 근접한 배치에서 0.3° 방위 잡음이 0.6m 위치 오차로 증폭됐고, 공분산이
#: 그 오차를 0.36m 로 **같은 자리수로** 예측했다. 문헌의 수치가 아니라 우리 실측값이다.
DANGER_CIRCLE_MARGIN_FLOOR = 0.05


def bearing_from_pixel(pixel_u: float, cx: float, fx: float) -> float:
    """영상 가로 좌표를 광축 기준 방위각(라디안)으로 환산한다.

    오른쪽으로 벗어난 점은 **음의 방위**(시계방향)다 — 세계 yaw 가 반시계 양이므로
    `world_azimuth = yaw - atan2(u - cx, fx)` 가 성립해야 한다. 부호를 여기 한 곳에서만
    정하고 아래 잔차식이 같은 규약을 쓴다. `edge/self_localization.py::bearing_offset_deg`
    는 **로봇이 얼마나 돌아야 하는가**(회전 지시각)를 내므로 부호 규약이 반대이고, 두
    함수를 합치지 않는다 — 같은 수식이 다른 질문에 답한다.
    """
    if fx <= 0.0:
        raise ValueError(f"bearing_from_pixel requires fx > 0, got {fx}")
    return -math.atan2(pixel_u - cx, fx)


def _wrap(angles):
    return (np.asarray(angles, dtype=float) + np.pi) % (2.0 * np.pi) - np.pi


@dataclass(frozen=True)
class AnchorBearing:
    """앵커 1개의 구역 로컬 좌표와 그 앵커가 보이는 방위.

    `local_x_m`/`local_y_m` 은 **구역 로컬**이다(AI-C-02). `accuracy_m` 은 그 앵커
    좌표 자체의 측량 정확도이고, None 이면 미측정이다 — 앵커가 미측정이면 그것으로
    유도한 카메라 자리도 미측정 이상으로 좋아질 수 없다.
    """

    anchor_id: str
    local_x_m: float
    local_y_m: float
    #: 광축 기준 방위각(라디안). `bearing_from_pixel()` 이 픽셀에서 만든다.
    bearing_rad: float
    #: 앵커 좌표의 측량 정확도(m). None 은 미측정이고 0 이 아니다.
    accuracy_m: float | None = None
    frame_ref: str = ""


@dataclass(frozen=True)
class ExtrinsicEstimate:
    """카메라의 구역 로컬 자리 1건. **정확도의 출처가 값과 함께 붙어 있다.**"""

    local_x_m: float
    local_y_m: float
    yaw_deg: float
    anchor_count: int
    #: 방위 잔차 RMS(도). 적합이 관측을 얼마나 설명했는가.
    bearing_residual_rms_deg: float
    accuracy_basis: str
    #: 위치의 **1σ**(m), 보수적으로 공분산 위치 블록의 큰 고윳값에서 낸다.
    #: None 은 미측정이고 0 이 아니다(AI-C-02).
    position_accuracy_m: float | None = None
    yaw_accuracy_deg: float | None = None
    #: 위험원 근접도. 작으면 기하가 위치를 결정하지 않는다.
    danger_circle_margin: float | None = None
    quality: Mapping[str, float] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()
    frame_refs: tuple[str, ...] = ()
    #: 이 자리를 쓸 수 있는가. 거부여도 추정값은 남는다 — 운영자가 왜 거부됐는지
    #: 보려면 값이 있어야 하고, 승격은 `CalibrationProfileStore` 가 따로 막는다.
    usable: bool = True

    @property
    def accuracy_known(self) -> bool:
        return self.position_accuracy_m is not None

    @property
    def pose(self) -> tuple[float, float, float]:
        """`CalibrationProfile.extrinsic` 이 받는 (x_m, y_m, yaw_deg)."""
        return (self.local_x_m, self.local_y_m, self.yaw_deg)


def _danger_circle_margin(
    anchors: np.ndarray, camera_x: float, camera_y: float
) -> float | None:
    """카메라가 앵커 셋의 외접원에서 얼마나 떨어져 있는가(상대값).

    가장 큰 삼각형을 이루는 앵커 세 개의 외접원을 쓴다. 그 셋이 거의 공선이면 외접원의
    반지름이 발산하고 **그것은 퇴화가 아니다** — 공선 배치는 잘 조건화되므로 1.0(여유
    충분)을 낸다. None 은 계산할 앵커가 3개 미만이라는 뜻이다.
    """
    if len(anchors) < 3:
        return None
    best: tuple[float, tuple[int, int, int]] | None = None
    n = len(anchors)
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                a, b, c = anchors[i], anchors[j], anchors[k]
                area = abs(
                    (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])
                ) / 2.0
                if best is None or area > best[0]:
                    best = (area, (i, j, k))
    assert best is not None
    area, (i, j, k) = best
    a, b, c = anchors[i], anchors[j], anchors[k]
    side = max(
        float(np.linalg.norm(b - a)), float(np.linalg.norm(c - a)),
        float(np.linalg.norm(c - b)),
    )
    if side <= 0.0 or area < 1e-9 * side * side:
        return 1.0  # 사실상 공선 — 외접원이 직선이고 퇴화 조건이 아니다
    d = 2.0 * (
        a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1])
    )
    ux = (
        (a[0] ** 2 + a[1] ** 2) * (b[1] - c[1])
        + (b[0] ** 2 + b[1] ** 2) * (c[1] - a[1])
        + (c[0] ** 2 + c[1] ** 2) * (a[1] - b[1])
    ) / d
    uy = (
        (a[0] ** 2 + a[1] ** 2) * (c[0] - b[0])
        + (b[0] ** 2 + b[1] ** 2) * (a[0] - c[0])
        + (c[0] ** 2 + c[1] ** 2) * (b[0] - a[0])
    ) / d
    radius = float(np.hypot(a[0] - ux, a[1] - uy))
    if radius <= 0.0:
        return 1.0
    distance = float(np.hypot(camera_x - ux, camera_y - uy))
    return abs(distance - radius) / radius


class AnchorBearingExtrinsics:
    """앵커 방위에서 구역 로컬 (x, y, yaw) 과 **측정된 정확도**를 낸다.

    최적화는 격자 다중 시작 + Levenberg–Marquardt 다. 외부 최적화기를 들이지 않는 이유는
    의존성이 아니라 **결정성**이다 — 같은 입력에 같은 답이 나와야 거부 사유를 재현할 수
    있다. 격자 초기화가 필요한 이유는 실측에서 확인했다: 단일 시작 Gauss–Newton 은
    0.3° 잡음에서도 10^14 m 로 발산했고, LM 의 비용 역추적과 다중 시작이 그것을 없앴다.
    """

    method_id = "anchor_bearing_resection"

    def __init__(
        self,
        *,
        max_bearing_residual_deg: float = 2.0,
        grid_samples: int = 40,
        multi_starts: int = 6,
        lm_iterations: int = 120,
        max_condition_number: float = 1e9,
    ) -> None:
        self._max_residual_deg = max_bearing_residual_deg
        self._grid = grid_samples
        self._starts = multi_starts
        self._lm_iterations = lm_iterations
        self._max_condition = max_condition_number

    # -- 잔차와 Jacobian ----------------------------------------------------
    @staticmethod
    def _residuals(params: np.ndarray, anchors: np.ndarray, bearings: np.ndarray):
        dx = anchors[:, 0] - params[0]
        dy = anchors[:, 1] - params[1]
        return _wrap(np.arctan2(dy, dx) - params[2] + bearings)

    @staticmethod
    def _jacobian(params: np.ndarray, anchors: np.ndarray) -> np.ndarray:
        dx = anchors[:, 0] - params[0]
        dy = anchors[:, 1] - params[1]
        d2 = dx * dx + dy * dy
        return np.column_stack([dy / d2, -dx / d2, -np.ones(len(dx))])

    @staticmethod
    def _yaw_closed_form(
        x: float, y: float, anchors: np.ndarray, bearings: np.ndarray
    ) -> float:
        """위치를 고정하면 yaw 는 원형 평균으로 닫힌 형태다 — 탐색 차원이 2로 줄어든다."""
        theta = np.arctan2(anchors[:, 1] - y, anchors[:, 0] - x)
        return float(np.angle(np.exp(1j * (theta + bearings)).mean()))

    def _refine(
        self, params: np.ndarray, anchors: np.ndarray, bearings: np.ndarray
    ) -> tuple[np.ndarray, float]:
        lam = 1e-3
        residual = self._residuals(params, anchors, bearings)
        cost = float(residual @ residual)
        for _ in range(self._lm_iterations):
            residual = self._residuals(params, anchors, bearings)
            jac = self._jacobian(params, anchors)
            gradient = jac.T @ residual
            hessian = jac.T @ jac
            step = None
            for _attempt in range(30):
                damping = lam * np.diag(np.maximum(np.diag(hessian), 1e-12))
                try:
                    step = np.linalg.solve(hessian + damping + 1e-14 * np.eye(3), -gradient)
                except np.linalg.LinAlgError:
                    lam *= 10.0
                    continue
                trial = params + step
                trial[2] = float(_wrap(trial[2]))
                trial_residual = self._residuals(trial, anchors, bearings)
                trial_cost = float(trial_residual @ trial_residual)
                if trial_cost < cost:
                    params, cost = trial, trial_cost
                    lam = max(lam * 0.3, 1e-12)
                    break
                lam *= 10.0
            else:
                break
            if step is not None and float(np.linalg.norm(step)) < 1e-12:
                break
        return params, cost

    # -- 공개 경로 ----------------------------------------------------------
    def estimate(
        self,
        anchors: Sequence[AnchorBearing],
        *,
        declared_bearing_sigma_rad: float | None = None,
        search_bounds: tuple[float, float, float, float] | None = None,
    ) -> ExtrinsicEstimate:
        """앵커 방위에서 카메라의 구역 로컬 자리를 푼다.

        `declared_bearing_sigma_rad` 는 호출자가 아는 방위 잡음(검출 불확실도 / fx)이다.
        주면 앵커 3개에서도 정확도를 **전파**할 수 있지만 그것은 선언의 전파이고 측정이
        아니다 — `accuracy_basis` 가 그 차이를 적는다. 앵커가 4개 이상이고 잔차가 0 이
        아니면 잔차에서 **잰** σ 가 선언값보다 우선한다(관측이 선언을 이긴다, AI-S-08).
        """
        reasons: list[str] = []
        ids = [a.anchor_id for a in anchors]
        if len(set(ids)) != len(ids):
            reasons.append("duplicate_anchor_id")
        if len(anchors) < 3:
            return ExtrinsicEstimate(
                local_x_m=float("nan"), local_y_m=float("nan"), yaw_deg=float("nan"),
                anchor_count=len(anchors), bearing_residual_rms_deg=float("nan"),
                accuracy_basis="unmeasured",
                reasons=tuple([*reasons, "too_few_anchors"]),
                frame_refs=tuple(a.frame_ref for a in anchors if a.frame_ref),
                usable=False,
            )

        points = np.array([[a.local_x_m, a.local_y_m] for a in anchors], dtype=float)
        bearings = np.array([a.bearing_rad for a in anchors], dtype=float)

        if search_bounds is None:
            pad = max(float(np.ptp(points[:, 0])), float(np.ptp(points[:, 1])), 1.0)
            search_bounds = (
                float(points[:, 0].min()) - pad, float(points[:, 0].max()) + pad,
                float(points[:, 1].min()) - pad, float(points[:, 1].max()) + pad,
            )

        candidates: list[tuple[float, np.ndarray]] = []
        for x in np.linspace(search_bounds[0], search_bounds[1], self._grid):
            for y in np.linspace(search_bounds[2], search_bounds[3], self._grid):
                if float(np.min((points[:, 0] - x) ** 2 + (points[:, 1] - y) ** 2)) < 1e-4:
                    continue  # 앵커 위에 카메라를 두면 방위가 정의되지 않는다
                yaw = self._yaw_closed_form(float(x), float(y), points, bearings)
                start = np.array([float(x), float(y), yaw])
                residual = self._residuals(start, points, bearings)
                candidates.append((float(residual @ residual), start))
        if not candidates:
            return ExtrinsicEstimate(
                local_x_m=float("nan"), local_y_m=float("nan"), yaw_deg=float("nan"),
                anchor_count=len(anchors), bearing_residual_rms_deg=float("nan"),
                accuracy_basis="unmeasured",
                reasons=tuple([*reasons, "anchor_geometry_degenerate"]),
                usable=False,
            )
        candidates.sort(key=lambda item: item[0])

        best: tuple[np.ndarray, float] | None = None
        for _, start in candidates[: self._starts]:
            params, cost = self._refine(start.copy(), points, bearings)
            if best is None or cost < best[1]:
                best = (params, cost)
        assert best is not None
        params, _ = best

        residual = self._residuals(params, points, bearings)
        jac = self._jacobian(params, points)
        hessian = jac.T @ jac
        dof = len(anchors) - 3
        rms_deg = math.degrees(float(np.sqrt(np.mean(residual * residual))))
        condition = float(np.linalg.cond(hessian))
        margin = _danger_circle_margin(points, float(params[0]), float(params[1]))

        # σ 선택: 잰 것이 선언을 이긴다. 둘 다 없으면 미측정이다.
        measured_variance = float(residual @ residual) / dof if dof > 0 else 0.0
        if dof > 0 and measured_variance > 0.0:
            variance, basis = measured_variance, "residual_measured"
        elif declared_bearing_sigma_rad is not None and declared_bearing_sigma_rad > 0.0:
            variance, basis = float(declared_bearing_sigma_rad) ** 2, "declared_bearing_noise"
        else:
            variance, basis = None, "unmeasured"

        position_accuracy: float | None = None
        yaw_accuracy: float | None = None
        if variance is None:
            reasons.append("accuracy_unmeasured")
        elif condition > self._max_condition:
            reasons.append("normal_matrix_singular")
            basis = "unmeasured"
        else:
            try:
                covariance = variance * np.linalg.inv(hessian)
            except np.linalg.LinAlgError:
                reasons.append("normal_matrix_singular")
                basis = "unmeasured"
            else:
                eigenvalues = np.linalg.eigvalsh(covariance[:2, :2])
                largest = float(max(eigenvalues))
                if largest <= 0.0 or not math.isfinite(largest):
                    reasons.append("normal_matrix_singular")
                    basis = "unmeasured"
                else:
                    position_accuracy = math.sqrt(largest)
                    yaw_variance = float(covariance[2, 2])
                    if yaw_variance > 0.0 and math.isfinite(yaw_variance):
                        yaw_accuracy = math.degrees(math.sqrt(yaw_variance))

        if rms_deg > self._max_residual_deg:
            reasons.append("bearing_residual_exceeded")
        if margin is not None and margin < DANGER_CIRCLE_MARGIN_FLOOR:
            reasons.append("anchor_geometry_degenerate")

        quality: dict[str, float] = {
            "bearing_residual_rms_deg": rms_deg,
            "anchor_count": float(len(anchors)),
            "normal_matrix_condition": condition,
        }
        if margin is not None:
            quality["danger_circle_margin"] = margin
        if position_accuracy is not None:
            quality["position_accuracy_m"] = position_accuracy
        if yaw_accuracy is not None:
            quality["yaw_accuracy_deg"] = yaw_accuracy

        return ExtrinsicEstimate(
            local_x_m=float(params[0]),
            local_y_m=float(params[1]),
            yaw_deg=math.degrees(float(params[2])),
            anchor_count=len(anchors),
            bearing_residual_rms_deg=rms_deg,
            accuracy_basis=basis,
            position_accuracy_m=position_accuracy,
            yaw_accuracy_deg=yaw_accuracy,
            danger_circle_margin=margin,
            quality=quality,
            reasons=tuple(reasons),
            frame_refs=tuple(a.frame_ref for a in anchors if a.frame_ref),
            usable=not reasons,
        )
