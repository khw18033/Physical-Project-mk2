"""보정판 없는 현장에서 내부 파라미터를 얻는다 — 교체 가능한 방법 경계 뒤에서.

implements: AI-E-02
관련: AI-C-02 (좌표계 경계), AI-C-05 (방법 부재는 그 방법만 비가용), AI-C-08 (미디어 경로),
      AI-S-08 (선언된 사전정보와 관측의 분리), AI-B-01 (미측정 항목을 구분한다)
tests: tests/test_auto_calibration.py

조사 정본은 `docs/research/automatic-camera-calibration.md` 다. 이 모듈은 그 문서가
**§2 에서 남긴 첫 번째 구멍**을 메운다 — "광선을 줄 상류가 없는 현장에서 내부
파라미터를 어디서 얻는가".

AI-E-02 는 방법을 고르라고 하지 않고 고정하지 말라고 한다:

> "보정 방식은 사전 보정, 보정판 기반, 영상 시퀀스 self-calibration, 학습 기반 추정 등
> 특정 방법을 프레임워크의 필수 방식으로 고정하지 않아야 한다."

그래서 이 모듈의 중심은 알고리즘이 아니라 **경계**다. `IntrinsicsMethodRegistry` 는
`evidence_kind`(그 방법이 요구하는 입력의 종류) → 방법 들의 사상이고, 새 방법은
등록 한 줄로 늘어난다. 입력 종류가 서로 다른 것을 하나의 request 자료형으로 억지로
합치지 않는다 — 보정판은 코너를 요구하고 자기보정은 호모그래피를 요구하며 학습 기반
회귀기는 광선을 요구한다. 같은 척 하면 쓰지 않는 칸을 0 으로 채우게 된다.

지금 등록되는 방법 셋(문서 §9 의 채택 결론):

1. `planar_target` — Zhang / `cv2.calibrateCamera`. 입력: 보정판 스펙 + 검출 코너.
   **왜곡까지 추정하는 유일한 경로**이고 정확도가 가장 믿을 만한 기준선이다. 다만
   대부분의 현장에 보정판이 없다(문서 §3.1).
2. `pure_rotation_homography` — Hartley 계열 자기보정(문서 §5.3). 입력: 미디어 경로로
   이미 엣지에 도착한 프레임 2장 + 그 사이 특징 대응. 조달할 가중치도 GPU 도 보정판도
   필요 없다 — **보정판 없는 현장에서 입력이 실제로 존재하는 유일한 비학습 경로**다.
3. `pixel_ray_correspondence` — 기존 `anycalib_style_recovery.RayFieldIntrinsicsRecovery`
   를 같은 경계에 올린 것. 입력: 픽셀↔광선 대응. 지금은 상류가 비어 있지만 이 자리가
   **비어 있지 않다**는 것이 문서 §4.5(GeoCalib) 후보가 핵심 코드 수정 없이 들어올 수
   있다는 증거다(AI-B-09: 검증 전에는 선택 후보가 아니다, 그러나 자리는 있다).

### 자기보정이 성립하는 조건과, 성립하지 않을 때 무엇이 일어나는가

순수 회전에서 두 뷰 사이 호모그래피는 `H = K R K⁻¹` 이고, 따라서 `K⁻¹ H K` 는 **회전
행렬이어야 한다**. 그 직교성 위반량이 f 하나에 대한 1차원 비용함수가 된다(절대원뿔의
쌍대 영상 DIAC 제약의 같은 말이다). 문헌이 미리 경고한 것은 이 계열이 "순수 회전이라는
단순한 특수 경우에서조차 잡음에 매우 민감" 하다는 점이고, 문서 §5.4 의 실측이 그 경고를
우리 자산에서 재현했다 — 이동 로봇은 카메라 광학 중심이 아니라 **자기 몸통 축**으로
돌기 때문에 병진이 섞이고 그 순간 가정이 깨진다.

그래서 이 모듈은 추정값만 내지 않고 **직교성 잔차와 복원된 화각을 함께 낸다.**
`IntrinsicsValidator` 가 그 두 수치로 승격을 막고, 막힌 사유는 `CalibrationProfileStore`
의 `rejections` 에 남아 이전 정상 프로파일이 유지된다(AI-E-02 의 fallback). 숨겨진
실패가 아니라 기록된 거부다.

### 미측정은 0 이 아니다

자기보정은 **왜곡을 추정하지 않는다.** 그래서 `IntrinsicsCandidate.dist_coeffs` 는
`None` 이고 0 벡터가 아니다 — 0 벡터는 "왜곡이 없다고 측정했다" 는 뜻이 되어, 광각
렌즈의 왜곡을 측정했는데 없었다는 거짓이 투영에 들어간다(AI-B-01: 미측정 항목은
구분한다). 같은 이유로 `quality` 는 **실제로 잰 키만** 담는다.

### 선언과 관측이 모순되면 평균하지 않는다

선언된 센서 태그(`sensor.camera.imx708` 등)의 공칭 화각은 **사전정보이고 관측이
아니다**(AI-S-08). 추정된 화각이 그 밴드를 벗어나면 그것은 평균해 없앨 잡음이 아니라
모순이고(문서 §8), 가능한 원인 전부가 운영자가 알아야 하는 것들이다 — 태그가 틀렸거나,
렌즈가 교체됐거나, 추정이 퇴화했거나. 어느 쪽이 맞는지는 AI 가 판정하지 않는다
(AI-C-19). 모순은 **검증 실패 사유로 적고 프로파일을 승격하지 않는** 방식으로 다룬다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence, runtime_checkable

import numpy as np

from mission_runtime.edge.anycalib_style_recovery import (
    RayCorrespondence,
    RayFieldIntrinsicsRecovery,
)
from mission_runtime.edge.calibration import CalibrationEstimate, CameraCalibrator

__all__ = [
    "INTRINSICS_EVIDENCE_KINDS",
    "MAX_ROTATION_RESIDUAL",
    "INTRINSICS_REJECTION_REASONS",
    "DEFAULT_SENSOR_FOV_PRIORS",
    "IntrinsicsCandidate",
    "IntrinsicsMethod",
    "IntrinsicsMethodRegistry",
    "IntrinsicsValidation",
    "IntrinsicsValidator",
    "PlanarTargetEvidence",
    "PlanarTargetIntrinsics",
    "PointCorrespondences",
    "PureRotationEvidence",
    "RayCorrespondenceEvidence",
    "RayCorrespondenceIntrinsics",
    "RotationHomographyIntrinsics",
    "SensorFovPrior",
    "ViewPairHomography",
    "default_method_registry",
    "homography_from_correspondences",
]


#: 내부 파라미터 추정에 쓰이는 **입력의 종류**. 방법 이름이 아니라 입력 이름이다 —
#: 같은 입력을 쓰는 두 방법(예: 광선 대응을 쓰는 우리 선형해와 나중의 학습 회귀기)은
#: 같은 자리에서 교체되어야 하고, 입력이 다른 방법은 애초에 서로 대체재가 아니다.
INTRINSICS_EVIDENCE_KINDS: tuple[str, ...] = (
    "planar_target_corners",       # 보정판 코너 ↔ 알려진 평면 기하
    "pure_rotation_homographies",  # 광학 중심 축 회전으로 얻은 뷰 사이 호모그래피
    "pixel_ray_correspondences",   # 픽셀 ↔ 광선 방향 (상류가 광선을 준다)
)

#: 승격을 막는 사유 어휘. **전부 "왜 프로파일이 되지 못했는가" 의 답이고 오류 코드가
#: 아니다** — 보정판이 없는 현장에서 자기보정이 거부되는 것은 정상 운용이다(AI-C-05).
#: 이 이름들은 아직 `contracts/data_dictionary.py` 에 등록되어 있지 않다(그 파일은 이
#: 작업의 소유 범위 밖이다). 전송 계약으로 나가기 전에 등록이 필요하다.
INTRINSICS_REJECTION_REASONS: tuple[str, ...] = (
    "rotation_assumption_violated",   # 직교성 잔차 초과 — H = K R K⁻¹ 가 성립하지 않았다
    "fov_physically_implausible",      # 복원 화각이 어떤 렌즈로도 불가능한 값
    "fov_conflicts_declared_sensor",   # 선언된 센서 태그의 공칭 화각과 모순(문서 §8)
    "reprojection_rms_exceeded",       # 대응 자체가 그 호모그래피로 설명되지 않는다
    "too_few_correspondences",         # 표본이 모자라 잔차가 의미를 갖지 못한다
    "principal_point_outside_image",   # 주점이 영상 밖 — 퇴화한 적합
    "aspect_ratio_implausible",        # fx/fy 가 센서 화소가 설명할 수 없는 비율
    "unstable_estimate",               # 방법 자신의 안정성 판정이 실패했다
)

#: 순수 회전 직교성 잔차의 승격 상한. **실측으로 정한 값이다.**
#:
#: 실자산 `local/physical_demo_assets/20260910-134818_rot8/` (464x400, 8방향 회전 스캔)
#: 과 그 실제 픽셀에 알려진 `K R K⁻¹` warp 을 걸어 ORB(4000) + crossCheck BF + RANSAC
#: 으로 측정한 분포는 이렇게 갈렸다.
#:
#: | 입력 | 잔차 | f 복원 |
#: |---|---|---|
#: | 실제 픽셀 + 알려진 warp (f=320/480/700, yaw 12°/20°) | 0.003 ~ 0.033 | ±3.2% 이내 |
#: | 실제 rot8 연속 쌍 7개 (로봇이 실제로 몸통 축으로 회전) | **0.25 ~ 1.40** | 수평화각 49~145° |
#:
#: 두 묶음 사이에 **한 자리수 가까운 빈 구간**이 있고, 0.05 는 그 안이다 — 유효한 적합의
#: 최대(0.033)보다 크고 깨진 적합의 최소(0.25)보다 5배 작다. 처음 쓴 0.02 는 유효한
#: f=700 적합(잔차 0.025·0.033, f 오차 +2.8%/+3.2%)을 잔차만으로 **잘못 거부**했다.
#: 0.05 로 옮긴 뒤 그 둘은 잔차 검사를 통과하고, 남는 거부 사유는 선언 모순 하나다 —
#: 464px 폭에서 f=700 은 수평화각 36° 이고 선언된 `imx708`(66°)과 맞지 않으므로 그
#: 거부는 **옳다**(문서 §8). 선언 태그를 주지 않으면 여섯 줄 전부 통과한다.
#:
#: 문서 §11 이 "수치는 문헌에서 그대로 가져오면 안 된다" 고 남긴 항목이고, 다른 특징
#: 매처·해상도로 바꾸면 이 분포도 바뀌므로 다시 재야 한다(AI-B-01).
MAX_ROTATION_RESIDUAL = 0.05

#: 어떤 렌즈로도 불가능한 화각의 절대 경계. 어안 상한을 넉넉히 잡아 둔다 — 이 검사는
#: "렌즈가 무엇인가" 를 가리지 않고 **퇴화한 적합**만 걸러낸다.
MIN_PLAUSIBLE_HFOV_DEG = 5.0
MAX_PLAUSIBLE_HFOV_DEG = 175.0


@dataclass(frozen=True)
class SensorFovPrior:
    """선언된 센서 태그의 공칭 화각과 허용 밴드. **관측이 아니다.**

    `tolerance_frac` 은 상대 밴드다 — 0.25 면 공칭 66° 가 49.5°~82.5° 를 허용한다.
    문서 §5.4 의 실측 실패값(같은 카메라에서 102~126° 또는 7°)은 이 밴드가 잡아내고,
    렌즈 개체차·제원표 오차는 통과한다.
    """

    sensor_tag: str
    nominal_hfov_deg: float
    tolerance_frac: float = 0.25
    source: str = "declared"

    def __post_init__(self) -> None:
        if not 0.0 < self.nominal_hfov_deg < 180.0:
            raise ValueError(
                f"{self.sensor_tag}: nominal_hfov_deg must be in (0, 180), "
                f"got {self.nominal_hfov_deg}"
            )
        if not 0.0 < self.tolerance_frac < 1.0:
            raise ValueError(
                f"{self.sensor_tag}: tolerance_frac must be in (0, 1), "
                f"got {self.tolerance_frac}"
            )

    @property
    def band_deg(self) -> tuple[float, float]:
        lo = self.nominal_hfov_deg * (1.0 - self.tolerance_frac)
        hi = self.nominal_hfov_deg * (1.0 + self.tolerance_frac)
        return (lo, hi)

    def admits(self, hfov_deg: float) -> bool:
        lo, hi = self.band_deg
        return lo <= hfov_deg <= hi


#: 선언된 센서 태그의 **공칭** 수평 화각. 관측이 아니라 사전정보다(AI-S-08).
#: 출처는 문서 §3.3 — Camera Module 3 표준 66° / 광각 102°, 유통사 제원표이고
#: Raspberry Pi 공식 페이지는 대각값만 적는다. 문서 §11 이 "경계값을 조일 때는
#: **실측**으로 확정해야 한다" 고 남긴 항목이므로 밴드를 넉넉히 둔다.
#: 새 카메라는 이 사상에 한 줄을 더하는 것으로 늘고 핵심 코드는 고치지 않는다(원칙 #7).
#: `sensor.camera.360` 은 **의도적으로 없다** — 파노라마에는 pinhole 화각이 없고,
#: 공칭값을 적어 두면 그것이 pinhole 승격의 근거로 읽힌다(문서 §6, equirect_views.py).
DEFAULT_SENSOR_FOV_PRIORS: Mapping[str, SensorFovPrior] = {
    "sensor.camera.imx708": SensorFovPrior(
        "sensor.camera.imx708", 66.0, source="vendor_spec_sheet"),
    "sensor.camera.imx708_wide": SensorFovPrior(
        "sensor.camera.imx708_wide", 102.0, source="vendor_spec_sheet"),
}


@dataclass(frozen=True)
class IntrinsicsCandidate:
    """추정 1건. **아직 프로파일이 아니다** — 검증을 통과해야 승격된다.

    `dist_coeffs` 가 None 인 것은 "왜곡이 없다" 가 아니라 **"이 방법은 왜곡을 추정하지
    않았다"** 는 뜻이다. 0 벡터로 채우면 그 구분이 사라지고, 사라진 자리에서 광각 렌즈의
    왜곡이 "측정해 보니 없었다" 로 읽힌다(AI-B-01).
    """

    fx: float
    fy: float
    cx: float
    cy: float
    image_size: tuple[int, int]
    method_id: str
    evidence_kind: str
    #: 추정된 왜곡 계수. **None 은 미추정이고 0 이 아니다.**
    dist_coeffs: tuple[float, ...] | None = None
    #: 그 계수가 어떤 모델의 계수인가(문서 §3.3: 모델 선택은 화각이 정한다).
    distortion_model: str | None = None
    #: **실제로 잰** 품질 수치만 담는다. 재지 않은 항목은 키를 넣지 않는다.
    quality: Mapping[str, float] = field(default_factory=dict)
    #: 방법별 진단값(직교성 잔차, 복원 회전각 등). 검증기가 읽는 자리다.
    diagnostics: Mapping[str, float] = field(default_factory=dict)
    #: 추정에 쓴 원본 관측 참조. 픽셀은 들어오지 않는다(AI-C-08).
    frame_refs: tuple[str, ...] = ()
    #: 방법 자신의 안정성 판정. 검증기의 판정과 **다른 축이다**.
    stable: bool = True

    @property
    def horizontal_fov_deg(self) -> float:
        width = float(self.image_size[0])
        return 2.0 * math.degrees(math.atan(width / (2.0 * self.fx)))

    @property
    def vertical_fov_deg(self) -> float:
        height = float(self.image_size[1])
        return 2.0 * math.degrees(math.atan(height / (2.0 * self.fy)))

    @property
    def distortion_estimated(self) -> bool:
        return self.dist_coeffs is not None

    def camera_matrix(self) -> np.ndarray:
        return np.array(
            [[self.fx, 0.0, self.cx], [0.0, self.fy, self.cy], [0.0, 0.0, 1.0]],
            dtype=float,
        )

    def as_calibration_estimate(self, *, stable: bool | None = None) -> CalibrationEstimate:
        """`CalibrationProfileStore.submit()` 이 받는 자료형으로 옮긴다.

        `reprojection_error_rms` 는 **잰 값이 있을 때만** 들어간다. 자기보정은 보정판
        재투영 오차를 내지 않으므로 그 자리에 호모그래피 inlier 재투영 RMS 를 넣고,
        그것조차 없으면 NaN 을 넣어 "이 축으로는 재지 않았다" 를 남긴다 — 0 을 넣으면
        측정한 적 없는 완벽한 보정이 된다.
        """
        rms = self.quality.get("reprojection_rms_px")
        return CalibrationEstimate(
            camera_matrix=self.camera_matrix(),
            dist_coeffs=None if self.dist_coeffs is None else np.array(self.dist_coeffs, dtype=float),
            reprojection_error_rms=float("nan") if rms is None else float(rms),
            stable=self.stable if stable is None else bool(stable),
        )


# --- 방법 경계 ---------------------------------------------------------------


@runtime_checkable
class IntrinsicsMethod(Protocol):
    """내부 파라미터 추정 방법 하나. `evidence_kind` 가 **요구하는 입력**을 선언한다."""

    method_id: str
    evidence_kind: str

    def estimate(self, evidence: object) -> IntrinsicsCandidate:
        ...


class IntrinsicsMethodRegistry:
    """입력 종류 → 그 입력으로 돌 수 있는 방법들.

    상위 코드는 "보정판을 쓸까 자기보정을 쓸까" 를 묻지 않는다 — **지금 어떤 입력이
    들어와 있는가**를 묻고, 그 입력을 쓸 수 있는 방법이 없으면 그 방법만 비가용이다
    (AI-C-05). 등록되지 않은 입력 종류는 조용히 무시되지 않고 거절된다 — 오타가
    "방법 없음" 으로 읽히면 다음 사람이 provider 를 찾아 헤맨다.
    """

    def __init__(self) -> None:
        self._by_kind: dict[str, list[IntrinsicsMethod]] = {}

    def register(self, method: IntrinsicsMethod) -> IntrinsicsMethod:
        if method.evidence_kind not in INTRINSICS_EVIDENCE_KINDS:
            raise ValueError(
                f"unregistered evidence kind {method.evidence_kind!r} for method "
                f"{method.method_id!r}; add it to INTRINSICS_EVIDENCE_KINDS first"
            )
        self._by_kind.setdefault(method.evidence_kind, []).append(method)
        return method

    def methods_for(self, evidence_kind: str) -> tuple[IntrinsicsMethod, ...]:
        if evidence_kind not in INTRINSICS_EVIDENCE_KINDS:
            raise ValueError(f"unregistered evidence kind {evidence_kind!r}")
        return tuple(self._by_kind.get(evidence_kind, ()))

    def method_ids(self) -> tuple[str, ...]:
        return tuple(
            m.method_id for kind in INTRINSICS_EVIDENCE_KINDS
            for m in self._by_kind.get(kind, ())
        )

    def available_evidence_kinds(self) -> tuple[str, ...]:
        return tuple(k for k in INTRINSICS_EVIDENCE_KINDS if self._by_kind.get(k))


# --- 1. 보정판 기반 (문서 §3.1, 기존 CameraCalibrator 를 같은 경계에 올린다) -----


@dataclass(frozen=True)
class PlanarTargetEvidence:
    """알려진 평면 기하 ↔ 검출된 코너. 보정판이 있는 현장만 이 입력을 낸다."""

    object_points: Sequence[np.ndarray]
    image_points: Sequence[np.ndarray]
    image_size: tuple[int, int]
    frame_refs: tuple[str, ...] = ()


class PlanarTargetIntrinsics:
    """Zhang / `cv2.calibrateCamera`. **왜곡까지 추정하는 유일한 등록 방법.**"""

    method_id = "planar_target"
    evidence_kind = "planar_target_corners"

    def __init__(self, *, max_acceptable_rms: float = 1.0) -> None:
        self._calibrator = CameraCalibrator(max_acceptable_rms=max_acceptable_rms)

    def estimate(self, evidence: object) -> IntrinsicsCandidate:
        if not isinstance(evidence, PlanarTargetEvidence):
            raise TypeError(f"{self.method_id} requires PlanarTargetEvidence")
        est = self._calibrator.estimate(
            list(evidence.object_points), list(evidence.image_points), evidence.image_size
        )
        k = np.asarray(est.camera_matrix, dtype=float)
        dist = np.asarray(est.dist_coeffs, dtype=float).ravel()
        return IntrinsicsCandidate(
            fx=float(k[0, 0]), fy=float(k[1, 1]), cx=float(k[0, 2]), cy=float(k[1, 2]),
            image_size=evidence.image_size,
            method_id=self.method_id,
            evidence_kind=self.evidence_kind,
            dist_coeffs=tuple(float(c) for c in dist),
            distortion_model="brown_conrady",
            quality={
                "reprojection_rms_px": float(est.reprojection_error_rms),
                "view_count": float(len(evidence.object_points)),
            },
            frame_refs=evidence.frame_refs,
            stable=bool(est.stable),
        )


# --- 2. 순수 회전 자기보정 (문서 §5.3 — 보정판 없는 유일한 비학습 경로) ----------


@dataclass(frozen=True)
class PointCorrespondences:
    """두 뷰 사이 점 대응. 픽셀이 아니라 **좌표**다(AI-C-08)."""

    points_a: np.ndarray  # (N, 2)
    points_b: np.ndarray  # (N, 2)
    frame_ref_a: str = ""
    frame_ref_b: str = ""


@dataclass(frozen=True)
class ViewPairHomography:
    """뷰 한 쌍 사이의 호모그래피와 **그것이 대응을 얼마나 설명했는가**."""

    matrix: np.ndarray  # (3, 3)
    inlier_count: int
    inlier_reprojection_rms_px: float | None = None
    frame_ref_a: str = ""
    frame_ref_b: str = ""

    def normalized(self) -> np.ndarray:
        h = np.asarray(self.matrix, dtype=float)
        if abs(h[2, 2]) > 1e-12:
            h = h / h[2, 2]
        return h


@dataclass(frozen=True)
class PureRotationEvidence:
    """광학 중심 축 회전으로 얻었다고 **주장되는** 뷰 쌍들.

    주장이 맞는지는 이 자료형이 보증하지 않는다 — 직교성 잔차가 판정하고, 문서 §5.4
    의 실측대로 이동 로봇의 몸통 회전은 그 판정에서 떨어진다.
    """

    homographies: Sequence[ViewPairHomography]
    image_size: tuple[int, int]
    #: 주점을 아는 배치(이전 프로파일·보정판 이력)에서는 그것을 쓴다. None 이면
    #: 영상 중심을 **가정**하고, 그 가정이 진단값으로 남는다.
    principal_point: tuple[float, float] | None = None


def homography_from_correspondences(
    correspondences: PointCorrespondences,
    *,
    ransac_threshold_px: float = 3.0,
) -> ViewPairHomography | None:
    """점 대응에서 RANSAC 호모그래피 1개. 못 구하면 None(예외가 아니다).

    대응을 만드는 특징 검출기는 이 함수의 책임이 아니다 — 호출자가 ORB 를 쓰든 수동
    클릭을 쓰든 학습 매처를 쓰든 같은 자리에 들어온다. 그것이 교체 가능성이고, 이
    함수가 영상을 받지 않는 이유다.
    """
    import cv2

    pts_a = np.asarray(correspondences.points_a, dtype=np.float32).reshape(-1, 1, 2)
    pts_b = np.asarray(correspondences.points_b, dtype=np.float32).reshape(-1, 1, 2)
    if len(pts_a) < 4 or len(pts_a) != len(pts_b):
        return None
    matrix, mask = cv2.findHomography(pts_a, pts_b, cv2.RANSAC, ransac_threshold_px)
    if matrix is None or mask is None:
        return None
    inliers = mask.ravel() > 0
    inlier_count = int(inliers.sum())
    rms: float | None = None
    if inlier_count > 0:
        projected = cv2.perspectiveTransform(pts_a, matrix).reshape(-1, 2)
        target = pts_b.reshape(-1, 2)
        err = np.sum((projected - target) ** 2, axis=1)[inliers]
        rms = float(math.sqrt(float(np.mean(err))))
    return ViewPairHomography(
        matrix=np.asarray(matrix, dtype=float),
        inlier_count=inlier_count,
        inlier_reprojection_rms_px=rms,
        frame_ref_a=correspondences.frame_ref_a,
        frame_ref_b=correspondences.frame_ref_b,
    )


def _rotation_orthogonality_residual(
    homography: np.ndarray, focal: float, cx: float, cy: float
) -> float:
    """`K⁻¹ H K` 가 회전행렬에서 얼마나 벗어났는가.

    스케일에 불변해야 하므로 중간 특이값으로 정규화한다 — 회전행렬의 특이값은 셋 다
    1 이므로, 적합이 맞을 때만 `MᵗM = I` 가 된다.
    """
    k = np.array([[focal, 0.0, cx], [0.0, focal, cy], [0.0, 0.0, 1.0]], dtype=float)
    m = np.linalg.solve(k, homography @ k)
    singular = np.linalg.svd(m, compute_uv=False)
    if singular[1] < 1e-12:
        return float("inf")
    m = m / singular[1]
    return float(np.linalg.norm(m.T @ m - np.eye(3)))


def _recovered_rotation_deg(
    homography: np.ndarray, focal: float, cx: float, cy: float
) -> float:
    """복원된 뷰 사이 회전각(도). 타당성 확인용 진단값이다."""
    k = np.array([[focal, 0.0, cx], [0.0, focal, cy], [0.0, 0.0, 1.0]], dtype=float)
    m = np.linalg.solve(k, homography @ k)
    u, _, vt = np.linalg.svd(m)
    r = u @ vt
    if np.linalg.det(r) < 0:
        u[:, -1] *= -1.0
        r = u @ vt
    cos_theta = (float(np.trace(r)) - 1.0) / 2.0
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_theta))))


class RotationHomographyIntrinsics:
    """순수 회전 호모그래피에서 초점거리 하나를 1차원 탐색으로 푼다(문서 §5.3).

    **푸는 것**: fx = fy = f. 정사각 화소와 skew 0 을 가정하고, 주점은 호출자가 주지
    않으면 영상 중심을 가정한다. 그 가정들을 숨기지 않고 `diagnostics` 에
    `principal_point_assumed` 로 적는다.

    **푸지 않는 것**: 왜곡(그래서 `dist_coeffs=None`), 비정사각 화소, 외부 파라미터.
    외부 파라미터는 `edge/calibration_extrinsics.py` 가 다른 입력으로 푼다.
    """

    method_id = "pure_rotation_homography"
    evidence_kind = "pure_rotation_homographies"

    def __init__(
        self,
        *,
        max_acceptable_residual: float = MAX_ROTATION_RESIDUAL,
        focal_search_span: tuple[float, float] = (0.05, 20.0),
        coarse_samples: int = 400,
        refine_iterations: int = 60,
    ) -> None:
        self._max_residual = max_acceptable_residual
        self._span = focal_search_span
        self._coarse_samples = coarse_samples
        self._refine_iterations = refine_iterations

    def estimate(self, evidence: object) -> IntrinsicsCandidate:
        if not isinstance(evidence, PureRotationEvidence):
            raise TypeError(f"{self.method_id} requires PureRotationEvidence")
        homographies = [h.normalized() for h in evidence.homographies]
        if not homographies:
            raise ValueError(
                f"{self.method_id} requires at least one view-pair homography"
            )
        width, height = evidence.image_size
        if evidence.principal_point is None:
            cx, cy = width / 2.0, height / 2.0
            assumed = 1.0
        else:
            cx, cy = evidence.principal_point
            assumed = 0.0

        def cost(focal: float) -> float:
            if focal <= 0.0:
                return float("inf")
            return sum(
                _rotation_orthogonality_residual(h, focal, cx, cy) for h in homographies
            ) / len(homographies)

        lo = self._span[0] * width
        hi = self._span[1] * width
        grid = np.geomspace(lo, hi, self._coarse_samples)
        costs = [cost(float(f)) for f in grid]
        best = int(np.argmin(costs))
        a = float(grid[max(0, best - 1)])
        b = float(grid[min(len(grid) - 1, best + 1)])
        # 황금분할 — 1차원이고 비용함수가 비싸지 않으므로 외부 최적화기를 들이지 않는다.
        golden = (math.sqrt(5.0) - 1.0) / 2.0
        for _ in range(self._refine_iterations):
            c = b - golden * (b - a)
            d = a + golden * (b - a)
            if cost(c) < cost(d):
                b = d
            else:
                a = c
        focal = (a + b) / 2.0
        residual = cost(focal)

        rotations = [_recovered_rotation_deg(h, focal, cx, cy) for h in homographies]
        inlier_counts = [h.inlier_count for h in evidence.homographies]
        rms_values = [
            h.inlier_reprojection_rms_px
            for h in evidence.homographies
            if h.inlier_reprojection_rms_px is not None
        ]
        quality: dict[str, float] = {
            "orthogonality_residual": residual,
            "view_pair_count": float(len(homographies)),
            "min_inlier_count": float(min(inlier_counts)) if inlier_counts else 0.0,
        }
        if rms_values:
            quality["reprojection_rms_px"] = float(max(rms_values))

        frame_refs = tuple(
            ref
            for h in evidence.homographies
            for ref in (h.frame_ref_a, h.frame_ref_b)
            if ref
        )
        return IntrinsicsCandidate(
            fx=focal, fy=focal, cx=float(cx), cy=float(cy),
            image_size=evidence.image_size,
            method_id=self.method_id,
            evidence_kind=self.evidence_kind,
            dist_coeffs=None,            # 이 방법은 왜곡을 추정하지 않는다
            distortion_model=None,
            quality=quality,
            diagnostics={
                "principal_point_assumed": assumed,
                "min_recovered_rotation_deg": float(min(rotations)),
                "max_recovered_rotation_deg": float(max(rotations)),
            },
            frame_refs=frame_refs,
            stable=residual <= self._max_residual,
        )


# --- 3. 광선 대응 (기존 anycalib_style_recovery 를 같은 경계에) -----------------


@dataclass(frozen=True)
class RayCorrespondenceEvidence:
    """픽셀 ↔ 광선 방향. 상류가 광선을 주는 배치에서만 이 입력이 존재한다."""

    correspondences: Sequence[RayCorrespondence]
    image_size: tuple[int, int]
    #: 광선을 만든 상류의 이름. 깊이 provider 인지 학습 회귀기인지가 계보에 남는다.
    ray_source: str = ""
    frame_refs: tuple[str, ...] = ()


class RayCorrespondenceIntrinsics:
    """`RayFieldIntrinsicsRecovery` 를 방법 경계에 올린 어댑터.

    새 코드는 없다 — 이 어댑터의 존재 자체가 요점이다. 문서 §4.5 의 GeoCalib 가
    조달되면 그 네트워크가 광선을 내고, **이 자리는 고치지 않는다**(AI-B-09).
    """

    method_id = "pixel_ray_correspondence"
    evidence_kind = "pixel_ray_correspondences"

    def __init__(self, *, max_acceptable_rms: float = 1.0) -> None:
        self._recovery = RayFieldIntrinsicsRecovery(max_acceptable_rms=max_acceptable_rms)

    def estimate(self, evidence: object) -> IntrinsicsCandidate:
        if not isinstance(evidence, RayCorrespondenceEvidence):
            raise TypeError(f"{self.method_id} requires RayCorrespondenceEvidence")
        est = self._recovery.estimate(list(evidence.correspondences))
        return IntrinsicsCandidate(
            fx=est.fx, fy=est.fy, cx=est.cx, cy=est.cy,
            image_size=evidence.image_size,
            method_id=self.method_id,
            evidence_kind=self.evidence_kind,
            dist_coeffs=None,            # 선형해는 pinhole 만 본다
            distortion_model=None,
            quality={
                "ray_residual_rms_px": float(est.residual_rms),
                "correspondence_count": float(len(evidence.correspondences)),
            },
            diagnostics={},
            frame_refs=evidence.frame_refs,
            stable=bool(est.stable),
        )


def default_method_registry(*, max_acceptable_rms: float = 1.0) -> IntrinsicsMethodRegistry:
    """문서 §9 가 채택한 세 방법을 등록한 레지스트리.

    기본 등록이 셋뿐인 것이 결론이다 — 나머지는 품질이 아니라 **입력이 없어서** 빠졌고
    (가중치 조달·GPU·장면 구조), 그 사유는 조사 문서에 남아 있다.
    """
    registry = IntrinsicsMethodRegistry()
    registry.register(PlanarTargetIntrinsics(max_acceptable_rms=max_acceptable_rms))
    registry.register(RotationHomographyIntrinsics())
    registry.register(RayCorrespondenceIntrinsics(max_acceptable_rms=max_acceptable_rms))
    return registry


# --- 검증 — 승격을 막는 자리 --------------------------------------------------


@dataclass(frozen=True)
class IntrinsicsValidation:
    """검증 결과. **통과 항목과 실패 사유를 모두 들고 다닌다.**

    `checks_passed` 가 중요한 이유: 프로파일에 `validated_by` 로 들어가면 **무엇을
    검증하지 않았는지**가 그 목록의 여집합으로 드러난다. 통과/실패 한 비트만 남기면
    "왜곡을 검증했는가" 를 나중에 물을 수 없다.
    """

    passed: bool
    reasons: tuple[str, ...]
    checks_passed: tuple[str, ...]
    #: 선언된 센서와 비교했는가. False 면 비교할 사전정보가 없었다는 뜻이고,
    #: 그것은 통과가 아니라 **미수행**이다(AI-S-08).
    compared_with_declared_sensor: bool = False


class IntrinsicsValidator:
    """추정 1건이 프로파일이 될 자격이 있는가.

    검증기는 방법을 모른다 — `IntrinsicsCandidate` 의 공개 수치만 본다. 그래서 새
    방법이 들어와도 이 클래스는 고치지 않는다(원칙 #7). 반대로 어떤 방법이 어떤
    진단값을 내지 않으면 그 검사는 **수행되지 않았다**로 남고 통과로 세지 않는다.
    """

    def __init__(
        self,
        *,
        max_orthogonality_residual: float = MAX_ROTATION_RESIDUAL,
        max_reprojection_rms_px: float = 2.0,
        min_inlier_count: int = 30,
        max_aspect_ratio_deviation: float = 0.2,
        fov_priors: Mapping[str, SensorFovPrior] | None = None,
    ) -> None:
        self._max_residual = max_orthogonality_residual
        self._max_rms = max_reprojection_rms_px
        self._min_inliers = min_inlier_count
        self._max_aspect_deviation = max_aspect_ratio_deviation
        self._fov_priors = dict(DEFAULT_SENSOR_FOV_PRIORS if fov_priors is None else fov_priors)

    def validate(
        self, candidate: IntrinsicsCandidate, *, declared_sensor_tag: str = ""
    ) -> IntrinsicsValidation:
        reasons: list[str] = []
        passed_checks: list[str] = []

        if not candidate.stable:
            reasons.append("unstable_estimate")

        hfov = candidate.horizontal_fov_deg
        if not MIN_PLAUSIBLE_HFOV_DEG <= hfov <= MAX_PLAUSIBLE_HFOV_DEG:
            reasons.append("fov_physically_implausible")
        else:
            passed_checks.append("fov_physically_plausible")

        width, height = candidate.image_size
        if not (0.0 < candidate.cx < width and 0.0 < candidate.cy < height):
            reasons.append("principal_point_outside_image")
        else:
            passed_checks.append("principal_point_inside_image")

        if candidate.fy > 0.0:
            deviation = abs(candidate.fx / candidate.fy - 1.0)
            if deviation > self._max_aspect_deviation:
                reasons.append("aspect_ratio_implausible")
            else:
                passed_checks.append("aspect_ratio_plausible")
        else:
            reasons.append("aspect_ratio_implausible")

        residual = candidate.quality.get("orthogonality_residual")
        if residual is not None:
            if not math.isfinite(residual) or residual > self._max_residual:
                reasons.append("rotation_assumption_violated")
            else:
                passed_checks.append("rotation_assumption_holds")

        rms = candidate.quality.get("reprojection_rms_px")
        if rms is not None:
            if not math.isfinite(rms) or rms > self._max_rms:
                reasons.append("reprojection_rms_exceeded")
            else:
                passed_checks.append("reprojection_rms_within_budget")

        inliers = candidate.quality.get("min_inlier_count")
        counts = candidate.quality.get("correspondence_count")
        sample = inliers if inliers is not None else counts
        if sample is not None:
            if sample < self._min_inliers:
                reasons.append("too_few_correspondences")
            else:
                passed_checks.append("sample_size_sufficient")

        prior = self._fov_priors.get(declared_sensor_tag) if declared_sensor_tag else None
        if prior is not None:
            if prior.admits(hfov):
                passed_checks.append("fov_matches_declared_sensor")
            else:
                reasons.append("fov_conflicts_declared_sensor")

        return IntrinsicsValidation(
            passed=not reasons,
            reasons=tuple(reasons),
            checks_passed=tuple(passed_checks),
            compared_with_declared_sensor=prior is not None,
        )
