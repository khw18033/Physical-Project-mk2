"""파노라마에는 pinhole 내부 파라미터가 없다 — 거절하거나 원근 뷰로 가른다.

implements: AI-E-02
관련: AI-C-02 (좌표계 경계), AI-C-08 (미디어 경로), AI-C-05 (입력 없는 방법은 비가용),
      AI-B-01 (미측정 항목을 구분한다)
tests: tests/test_equirect_views.py

조사 정본은 `docs/research/automatic-camera-calibration.md` §6 이다. 결론은 한 줄이다:
**스티칭된 등장방형(equirectangular) 파노라마에는 자기 pinhole 내부 파라미터가 없다.**
조사한 세 가지 대응이 전부 "파노라마에 pinhole 을 씌우지 말라" 고 말한다.

1. 스티칭 **전** 렌즈별로 보정한다 — 렌즈별 원본에 접근해야 한다. 우리는 못 한다
   (`sensor.camera.360` 은 "제어 없음, 라이브 스트림 수신만" 으로 선언돼 있다).
2. 구면 모델을 쓴다 — 픽셀을 각도로 먼저 환산한다. 역시 pinhole 이 아니다.
3. **원근 뷰를 뽑아 그걸 쓴다** — 이 모듈이 구현하는 경로다.

### 이 모듈이 하는 두 가지

**(a) 거절.** `refuse_pinhole_calibration()` 이 사유를 낸다. 중요한 것은 그 사실이
조용히 사라지지 않는 것이다 — 360 소스에 pinhole 프로파일을 적용하는 일이 없어야 하고,
`ApplicabilityScope.projection` 이 그것을 막는다(문서 §6 이 "`ApplicabilityScope` 가
카메라를 식별해야 한다" 고 남긴 자리다). 거절은 오류가 아니다: 360 소스가 있는 배치에서
pinhole 기반 기능만 비가용이고 나머지는 계속 돈다(AI-C-05).

**(b) 원근 뷰 유도.** 등장방형 프레임에서 원근 투영 여러 장을 뽑는다. 실증 배치의
`e2p_sweep` 도구가 같은 일을 15° 간격 24장의 90° 뷰로 하고 있었다 — 이 모듈은 그
코드를 가져오지 않고 **같은 접근을 provider 경계 뒤에서** 구현한다(그 도구가 쓰는
py360convert 는 우리 의존성이 아니다). 유도 계획(`perspective_sweep_plan`)과 실제
렌더(`render_perspective_view`)를 분리해 두었으므로, 외부 도구가 뽑아 둔 뷰를 받는
자리도 같은 `PerspectiveViewSpec` 하나다.

### 유도된 뷰의 내부 파라미터는 **측정값이 아니라 구성값**이다

여기가 이 모듈에서 가장 쉽게 틀리는 자리다. 등장방형에서 원근 뷰를 뽑을 때 초점거리는
**우리가 고른다** — `fx = (W/2) / tan(hfov/2)` 는 선택한 화각의 정의이고 렌즈를 측정한
결과가 아니다. 그래서:

- 유도된 뷰를 `pure_rotation_homography` 로 "보정" 하면 우리가 고른 값을 되찾을 뿐이다.
  그것은 보정이 아니라 자기확인이다.
- 유도된 뷰의 내부 파라미터는 **파노라마의 각도 격자에 대해서만** 정확하다. 그 격자
  자체가 얼마나 정확한지(스티칭 오차)는 **미측정**이고, 우리는 렌즈별 원본에 접근하지
  못하므로 지금 측정할 수 없다. `intrinsics_basis="by_construction"` 과
  `stitching_accuracy_deg=None` 이 그 사실을 들고 다닌다 — None 은 0 이 아니다.

쓸 수 있는 자리는 있다. 유도된 뷰는 **픽셀↔광선 대응을 공짜로 준다**(광선이 각도
격자에서 바로 나온다). 그것이 `anycalib_style_recovery.RayFieldIntrinsicsRecovery` 가
요구하는 바로 그 입력이고, 그래서 360 소스는 pinhole 보정의 대상이 아니지만 **pinhole
투영을 쓰는 하류 기능의 입력**은 될 수 있다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from mission_runtime.edge.anycalib_style_recovery import RayCorrespondence
from mission_runtime.edge.calibration_profile import ApplicabilityScope

__all__ = [
    "EQUIRECT_REFUSAL_REASONS",
    "PanoramaSource",
    "PerspectiveViewSpec",
    "derived_view_scope",
    "perspective_sweep_plan",
    "refuse_pinhole_calibration",
    "render_perspective_view",
    "view_ray_correspondences",
]

#: 파노라마에 pinhole 보정을 적용하지 않는 사유. **오류 코드가 아니다**(문서 §6).
EQUIRECT_REFUSAL_REASONS: tuple[str, ...] = (
    "equirectangular_has_no_pinhole_intrinsics",  # 애초에 성립하지 않는다
    "per_lens_frames_unavailable",                # 스티칭 전 원본에 접근권이 없다
    "stitching_accuracy_unmeasured",              # 각도 격자의 정확도를 재지 못했다
    "projection_mismatch",                        # 프로파일의 투영과 소스의 투영이 다르다
)


@dataclass(frozen=True)
class PanoramaSource:
    """스티칭된 등장방형 소스 1개. **pinhole 보정의 대상이 아니다.**

    `per_lens_access` 가 False 인 것이 현재 배치의 사실이다(문서 §6 판정) — 그 값이
    True 가 되는 날 대응 1번(렌즈별 보정)이 열리고, 그때 이 모듈은 고치지 않고 새
    provider 가 하나 생긴다.
    """

    camera_id: str
    width_px: int
    height_px: int
    projection: str = "equirectangular"
    per_lens_access: bool = False
    #: 스티칭이 만든 각도 격자의 정확도(도). **None 은 미측정이고 0 이 아니다.**
    stitching_accuracy_deg: float | None = None

    def __post_init__(self) -> None:
        if self.width_px <= 0 or self.height_px <= 0:
            raise ValueError(f"{self.camera_id}: panorama size must be positive")

    @property
    def horizontal_degrees_per_px(self) -> float:
        return 360.0 / float(self.width_px)

    @property
    def vertical_degrees_per_px(self) -> float:
        return 180.0 / float(self.height_px)


def refuse_pinhole_calibration(source: PanoramaSource) -> tuple[str, ...]:
    """이 소스에 pinhole 보정을 적용하지 않는 사유 전부. 빈 묶음이면 적용해도 된다.

    `projection` 이 `pinhole` 인 소스는 빈 묶음을 받는다 — 이 함수를 모든 미디어
    소스에 걸어도 일반 카메라는 통과한다. 그렇게 해야 호출자가 "360 이면" 하는 분기를
    쓰지 않는다(원칙 #3: 도메인·제품 이름으로 분기하지 않는다).
    """
    if source.projection == "pinhole":
        return ()
    reasons = ["equirectangular_has_no_pinhole_intrinsics"]
    if not source.per_lens_access:
        reasons.append("per_lens_frames_unavailable")
    if source.stitching_accuracy_deg is None:
        reasons.append("stitching_accuracy_unmeasured")
    return tuple(reasons)


@dataclass(frozen=True)
class PerspectiveViewSpec:
    """등장방형에서 뽑을(또는 외부 도구가 뽑아 둔) 원근 뷰 1장의 명세.

    내부 파라미터는 이 명세에서 **유도**된다 — 측정된 것이 아니다(모듈 docstring).
    `yaw_deg`/`pitch_deg` 는 파노라마 기준 프레임의 방향이고 세계 좌표가 아니다
    (AI-C-02: 공간 값은 끝까지 자기 기준 좌표계를 들고 다닌다).
    """

    yaw_deg: float
    pitch_deg: float
    hfov_deg: float
    width_px: int
    height_px: int
    view_id: str = ""
    #: 이 뷰의 좌표가 어느 프레임의 값인가. 파노라마 기준이고 전역이 아니다.
    reference_frame: str = "panorama_body"
    #: 내부 파라미터의 출처. `by_construction` 은 "우리가 골랐다" 는 뜻이다.
    intrinsics_basis: str = "by_construction"

    def __post_init__(self) -> None:
        if not 0.0 < self.hfov_deg < 180.0:
            raise ValueError(f"hfov_deg must be in (0, 180), got {self.hfov_deg}")
        if self.width_px <= 0 or self.height_px <= 0:
            raise ValueError("view size must be positive")

    @property
    def fx(self) -> float:
        return (self.width_px / 2.0) / math.tan(math.radians(self.hfov_deg) / 2.0)

    @property
    def fy(self) -> float:
        # 정사각 화소를 **구성으로** 강제한다 — 리샘플링이 만드는 뷰이므로 그렇게 고를
        # 수 있다. 실제 렌즈에서는 이것을 가정이 아니라 측정으로 확인해야 한다.
        return self.fx

    @property
    def cx(self) -> float:
        return self.width_px / 2.0

    @property
    def cy(self) -> float:
        return self.height_px / 2.0

    @property
    def vertical_fov_deg(self) -> float:
        return 2.0 * math.degrees(math.atan((self.height_px / 2.0) / self.fy))

    def camera_matrix(self) -> np.ndarray:
        return np.array(
            [[self.fx, 0.0, self.cx], [0.0, self.fy, self.cy], [0.0, 0.0, 1.0]],
            dtype=float,
        )

    def rotation(self) -> np.ndarray:
        """뷰 카메라 프레임 → 파노라마 기준 프레임. yaw(Y축) 후 pitch(X축).

        부호 규약: +yaw 는 경도 +(오른쪽), **+pitch 는 지평선 위**다. 카메라 프레임의
        +y 가 아래를 가리키므로 위를 보는 광선의 y 는 음이 되고, 등장방형 위도가
        `asin(-y)` 라 +30° pitch 가 위도 +30° 를 샘플링한다. 이 규약은
        `render_perspective_view()` 와 같은 회전을 쓰는 것으로 한 곳에만 둔다.
        """
        yaw = math.radians(self.yaw_deg)
        pitch = math.radians(self.pitch_deg)
        r_yaw = np.array(
            [[math.cos(yaw), 0.0, math.sin(yaw)],
             [0.0, 1.0, 0.0],
             [-math.sin(yaw), 0.0, math.cos(yaw)]], dtype=float)
        r_pitch = np.array(
            [[1.0, 0.0, 0.0],
             [0.0, math.cos(pitch), -math.sin(pitch)],
             [0.0, math.sin(pitch), math.cos(pitch)]], dtype=float)
        return r_yaw @ r_pitch

    def ray_in_view_frame(self, pixel_u: float, pixel_v: float) -> tuple[float, float, float]:
        """뷰 픽셀 → 뷰 카메라 프레임의 광선(정규화하지 않는다, z = 1)."""
        return (
            (pixel_u - self.cx) / self.fx,
            (pixel_v - self.cy) / self.fy,
            1.0,
        )

    def ray_in_panorama_frame(self, pixel_u: float, pixel_v: float) -> tuple[float, float, float]:
        """뷰 픽셀 → 파노라마 기준 프레임의 단위 광선."""
        ray = np.array(self.ray_in_view_frame(pixel_u, pixel_v), dtype=float)
        world = self.rotation() @ ray
        norm = float(np.linalg.norm(world))
        return (float(world[0] / norm), float(world[1] / norm), float(world[2] / norm))


def perspective_sweep_plan(
    *,
    hfov_deg: float = 90.0,
    step_deg: float = 15.0,
    pitch_deg: float = 0.0,
    width_px: int = 640,
    height_px: int = 640,
    view_id_prefix: str = "e2p",
) -> tuple[PerspectiveViewSpec, ...]:
    """360°를 겹치는 원근 뷰로 덮는 계획.

    기본값(90° 화각 · 15° 간격 · 24장)은 실증 배치의 `e2p_sweep` 도구가 실제로 쓰고
    있는 값이다 — 그 도구의 코드를 복사하지 않고 **같은 계획을 데이터로** 적는다.
    간격이 화각보다 훨씬 작은 것이 요점이다: 인접 뷰가 크게 겹쳐야 뷰 사이 특징 대응이
    생기고, 그 대응이 있어야 하류의 SfM·자기보정이 입력을 갖는다.

    계획은 렌더와 분리되어 있다. 외부 도구(py360convert 등)가 같은 명세로 뽑아 둔
    뷰를 받는 자리도 이 자료형 하나다 — 그것이 "우리 코드가 아니어도 같은 경계" 다.
    """
    if step_deg <= 0.0:
        raise ValueError(f"step_deg must be > 0, got {step_deg}")
    count = int(round(360.0 / step_deg))
    return tuple(
        PerspectiveViewSpec(
            yaw_deg=i * step_deg, pitch_deg=pitch_deg, hfov_deg=hfov_deg,
            width_px=width_px, height_px=height_px,
            view_id=f"{view_id_prefix}_{i:02d}",
        )
        for i in range(count)
    )


def render_perspective_view(
    panorama: np.ndarray,
    spec: PerspectiveViewSpec,
    *,
    interpolation: int | None = None,
) -> np.ndarray:
    """등장방형 영상에서 원근 뷰 1장을 리샘플링한다.

    등장방형 규약: 가로가 경도 -180°~+180°(왼→오), 세로가 위도 +90°(위)~-90°(아래).
    영상 y 축이 아래로 증가하므로 카메라 프레임의 +y 는 아래를 가리키고, 그래서
    위도는 `asin(-y)` 다. 이 규약을 한 곳에만 적어 두고 `ray_in_panorama_frame()` 과
    같은 회전을 쓴다 — 두 곳에서 따로 정하면 뷰와 광선이 다른 방향을 가리킨다.
    """
    import cv2

    if interpolation is None:
        interpolation = cv2.INTER_LINEAR
    pano = np.asarray(panorama)
    if pano.ndim < 2:
        raise ValueError("panorama must be a 2D or 3D array")
    pano_h, pano_w = pano.shape[0], pano.shape[1]

    us, vs = np.meshgrid(
        np.arange(spec.width_px, dtype=np.float64),
        np.arange(spec.height_px, dtype=np.float64),
    )
    x = (us - spec.cx) / spec.fx
    y = (vs - spec.cy) / spec.fy
    z = np.ones_like(x)
    directions = np.stack([x, y, z], axis=-1)
    directions /= np.linalg.norm(directions, axis=-1, keepdims=True)
    world = directions @ spec.rotation().T

    longitude = np.arctan2(world[..., 0], world[..., 2])
    latitude = np.arcsin(np.clip(-world[..., 1], -1.0, 1.0))
    map_x = ((longitude / (2.0 * math.pi)) + 0.5) * pano_w
    map_y = (0.5 - latitude / math.pi) * pano_h
    return cv2.remap(
        pano, map_x.astype(np.float32), map_y.astype(np.float32),
        interpolation, borderMode=cv2.BORDER_WRAP,
    )


def view_ray_correspondences(
    spec: PerspectiveViewSpec, *, samples: int = 5
) -> list[RayCorrespondence]:
    """유도된 뷰의 픽셀↔광선 대응. `RayFieldIntrinsicsRecovery` 의 입력 형식이다.

    광선은 **뷰 카메라 프레임**에서 낸다(파노라마 프레임이 아니다) — 그 복원 대수가
    푸는 것이 뷰 자신의 내부 파라미터이기 때문이다. 이 대응으로 복원된 값은 우리가
    고른 값과 같아야 하고, 그것이 기존 선형해 자리가 **실제로 연결되는지** 확인하는
    경로다. 측정이 아니라 자기확인이라는 점을 잊지 않는다(모듈 docstring).
    """
    if samples < 2:
        raise ValueError(f"need at least 2 samples per axis, got {samples}")
    out: list[RayCorrespondence] = []
    for u in np.linspace(0.0, spec.width_px - 1.0, samples):
        for v in np.linspace(0.0, spec.height_px - 1.0, samples):
            rx, ry, rz = spec.ray_in_view_frame(float(u), float(v))
            out.append(RayCorrespondence(float(u), float(v), rx, ry, rz))
    return out


def derived_view_scope(source: PanoramaSource, spec: PerspectiveViewSpec) -> ApplicabilityScope:
    """유도된 뷰의 적용 범위. 투영이 `pinhole` 이고 **토큰이 뷰를 식별한다.**

    `zoom_token` 에 뷰 식별자가 들어가는 이유: 같은 360 소스에서 뽑은 두 뷰는 서로
    **다른 입력 조건**이다. 한 뷰의 보정이 다른 뷰에 적용되면 yaw 가 다른 카메라의
    주점이 쓰인다. 문서 §4.4(Perspective Fields)가 지적한 crop 민감성과 같은 종류의
    문제이고, 그 지적이 `zoom_token` 을 둔 근거였다.
    """
    token = spec.view_id or f"yaw{spec.yaw_deg:g}_pitch{spec.pitch_deg:g}_fov{spec.hfov_deg:g}"
    return ApplicabilityScope(
        camera_id=source.camera_id,
        image_size=(spec.width_px, spec.height_px),
        zoom_token=f"e2p:{token}",
        projection="pinhole",
    )
