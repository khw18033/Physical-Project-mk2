"""Common depth-capability output and the calibration profile bound to it.

implements: AI-E-02 (보정 lifecycle), AI-B-08 (실행 provider 추상화), AI-C-02 (좌표 기준)
관련: AI-B-01 (다른 구성의 측정을 물려받지 않는다), AI-C-05, AI-R-02, AI-C-18

왜 이 모듈이 있는가
-------------------
단안 깊이 모델은 **스케일이 없는 상대값**을 낸다. 그 상대값을 미터로 바꾸는 식은
모델마다 다르고, 한 모델의 식을 다른 모델 출력에 대면 **값은 나오지만 전부
틀린다.** 데모 스택에서 실제로 일어났다(2026-09-20 실측):

    UniDepth 용 3차 보정식을 ZipDepth 출력에 적용 → 1110 개 박스 전부가
    12.7~15.0cm (MAE 42.7cm · bias −42.7cm)

"바로 앞에 장애물" 이 화면 어디에나 생기는 종류의 오류다. 예외도 나지 않는다.
그래서 보정식을 **provider_key + depth_space + 입력 조건**에 묶고, 어긋나면 값을
내지 않고 `CalibrationMismatch` 를 올린다. 이것이 그 경로를 막는 **유일한 코드
지점**이다 — 잡아서 축소하지 말고 코드를 고쳐야 하는 예외다.

두 깊이 공간
------------
``metric_m``
    값이 곧 거리. 값이 클수록 **멀다**.
``affine_invariant_inverse``
    역깊이. 값이 클수록 **가깝다**. ZipDepth 가 이쪽이다.

같은 "박스 대표값" 이라도 공간에 따라 퍼센타일이 달라진다 — depth 는 p40,
inverse 는 근거리 쪽이 큰 값이라 p60 이 같은 의도다. 어느 쪽을 쓰는지는 코드가
아니라 **프로파일**이 정한다.

거리가 없을 때
--------------
`distance_cm=None` 은 **0cm 가 아니라 미측정이다.** 0cm 클램프(`max(0.0, …)`)는
2026-09-14 리허설에서 없는 장애물을 만든 사고라 금지다. 그래서 바닥값 이하는
값이 아니라 상태로 나간다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

#: 값이 곧 거리인 공간. 값이 클수록 멀다.
DEPTH_SPACE_METRIC = "metric_m"
#: 역깊이 공간. 값이 클수록 **가깝다**. 스케일·오프셋이 미지라 affine-invariant 다.
DEPTH_SPACE_AFFINE_INVERSE = "affine_invariant_inverse"
DEPTH_SPACES: tuple[str, ...] = (DEPTH_SPACE_METRIC, DEPTH_SPACE_AFFINE_INVERSE)

#: 거리 측정 상태. **`None` 거리에는 항상 이 중 하나가 함께 나간다.**
STATUS_MEASURED = "measured"
STATUS_UNMEASURED_OUT_OF_RANGE = "unmeasured_out_of_range"
STATUS_UNMEASURED_NO_PROFILE = "unmeasured_no_profile"
STATUS_UNMEASURED_NO_DEPTH = "unmeasured_no_depth"
#: 프로파일은 이 출력에 묶여 있지만 **식이 아직 맞춰지지 않았다.** 범위 밖과
#: 구분한다 — 전자는 재측정해서 계수를 채우면 되고, 후자는 그 구간을 믿지 않기로
#: 한 결정이다. 한 토큰으로 묶으면 다음에 무엇을 해야 하는지가 사라진다.
STATUS_UNMEASURED_NO_FORMULA = "unmeasured_no_fitted_formula"
DISTANCE_STATUSES: tuple[str, ...] = (
    STATUS_MEASURED, STATUS_UNMEASURED_OUT_OF_RANGE,
    STATUS_UNMEASURED_NO_PROFILE, STATUS_UNMEASURED_NO_DEPTH,
    STATUS_UNMEASURED_NO_FORMULA,
)

#: 보정식이 어디서 왔는가. 로봇 실측과 **다른 경로를 기준으로 맞춘 식**은 같은
#: 확신이 아니다 — 승격 판단에 이 값이 필요하다(AI-L-06).
PROFILE_STATUS_DEPLOYED = "deployed"          # 로봇으로 직접 재서 만든 식
PROFILE_STATUS_PROVISIONAL = "provisional"    # 다른 provider 의 보정 경로를 기준으로 맞춘 식

#: 내부 파라미터가 없어 방위각을 낼 수 없는 상태. **각도 대신 이것이 나간다** —
#: 없는 기준으로 만든 각도는 좌표가 아니다(AI-C-02).
BEARING_UNMEASURED_NO_INTRINSICS = "unmeasured_no_intrinsics"
BEARING_MEASURED = "measured"


class CalibrationMismatch(RuntimeError):
    """보정 프로파일을 **다른 provider·다른 깊이 공간**의 출력에 적용하려 했다.

    조용히 틀린 cm 를 내는 대신 여기서 멈춘다. 이 예외가 나면 데이터가 아니라
    **코드가 잘못된 것**이다 — 잡아서 축소 경로로 넘기지 말고 고쳐야 한다.
    """


class DepthContractError(RuntimeError):
    """provider 가 내주지 않는 출력을 요구했다(예: 역깊이 provider 에 fx·cx)."""


@dataclass(frozen=True)
class DepthField:
    """깊이 capability 의 공통 출력. **채울 수 없는 칸은 None 으로 남는다.**

    서로 다른 provider 가 같은 자료형을 돌려주고, 상위 코드는 None 을 보고
    축소한다(AI-C-05). `depth_space` 가 `values` 의 의미를 정하므로 둘은 떨어질 수
    없다 — 배열만 넘기면 받는 쪽이 공간을 추측하게 되고, 그 추측이 위 실측 사고다.
    """

    values: Any                              # (H, W) 배열. 의미는 depth_space 가 정한다
    depth_space: str
    provider_key: str
    #: 추론에 들어간 이미지 (w, h) — **crop 이후** 크기다.
    source_wh: tuple[int, int]
    #: `values` 배열의 (w, h).
    infer_wh: tuple[int, int]
    #: (fx, cx), 추론 픽셀 좌표계. 내주지 않는 provider 는 None 이다.
    intrinsics: tuple[float, float] | None = None
    infer_ms: float = 0.0
    #: 추론 전에 잘라낸 **원본 좌표** 박스. 원본 프레임 좌표를 넘길 때는 이
    #: 오프셋을 먼저 빼야 한다 — 빼지 않으면 박스가 엉뚱한 자리의 깊이를 읽는다.
    crop_box: tuple[int, int, int, int] | None = None
    #: crop 이전의 원본 프레임 (w, h). crop 이 없으면 `source_wh` 와 같다.
    frame_wh: tuple[int, int] | None = None

    @property
    def scale_xy(self) -> tuple[float, float]:
        """source(crop 후) px → depth px 배율. 박스를 넘길 때 반드시 곱한다."""
        return (self.infer_wh[0] / self.source_wh[0],
                self.infer_wh[1] / self.source_wh[1])

    @property
    def original_wh(self) -> tuple[int, int]:
        return self.frame_wh or self.source_wh

    @property
    def nearer_is_larger(self) -> bool:
        """값이 클수록 가까운가. 역깊이면 참이다."""
        return self.depth_space == DEPTH_SPACE_AFFINE_INVERSE


class DepthProvider(Protocol):
    """공통 깊이 실행 인터페이스(AI-B-08). 구체 런타임은 이 뒤에 있다."""

    provider_key: str
    depth_space: str

    def is_available(self) -> bool: ...
    def estimate(self, frame: Any) -> DepthField: ...


# ── 좌표 환산 (4 겹 좌표계에서 가장 어긋나기 쉬운 자리) ──────────────────────

def box_to_depth_pixels(field_: DepthField, box_original) -> tuple[float, float, float, float]:
    """원본 프레임 좌표 박스 → 그 깊이 배열의 좌표.

    **crop 오프셋을 먼저 뺀다.** 빼지 않고 배율만 곱하면 박스가 옮겨져 다른
    물체의 깊이를 읽고, 그 값은 그럴듯해서 틀린 줄 모른다.
    """
    x1, y1, x2, y2 = box_original
    if field_.crop_box is not None:
        cx, cy = field_.crop_box[0], field_.crop_box[1]
        x1, y1, x2, y2 = x1 - cx, y1 - cy, x2 - cx, y2 - cy
    sx, sy = field_.scale_xy
    return (x1 * sx, y1 * sy, x2 * sx, y2 * sy)


def roi_representative(values, box_in_depth, percentile: float) -> float | None:
    """박스 안쪽 18% 를 수축한 뒤 주어진 퍼센타일. **퍼센타일은 인자다.**

    수축값과 최소 면적은 실측으로 굳힌 값이라 여기서 다시 튜닝하지 않는다.
    퍼센타일만 프로파일이 정한다 — depth 는 p40, 역깊이는 근거리 쪽이 큰 값이라
    같은 의도가 p60 이다.
    """
    import numpy as np

    x1, y1, x2, y2 = box_in_depth
    w, h = int(x2 - x1), int(y2 - y1)
    if w <= 0 or h <= 0:
        return None
    mx, my = int(w * 0.18), int(h * 0.18)
    rx1, ry1, rx2, ry2 = int(x1 + mx), int(y1 + my), int(x2 - mx), int(y2 - my)
    if rx2 <= rx1 or ry2 <= ry1 or (rx2 - rx1) * (ry2 - ry1) < 20:
        rx1, ry1, rx2, ry2 = int(x1), int(y1), int(x2), int(y2)
    roi = values[max(0, ry1):max(0, ry2), max(0, rx1):max(0, rx2)]
    if getattr(roi, "size", 0) == 0:
        return None
    valid = roi[np.isfinite(roi) & (roi > 0)]
    return float(np.percentile(valid, percentile)) if valid.size else None


# ── 보정 프로파일 (AI-E-02) ─────────────────────────────────────────────────

@dataclass(frozen=True)
class DepthCalibrationProfile:
    """상대 깊이 → cm. **한 provider 의 한 입력 조건에만** 적용된다."""

    profile_id: str
    version: int
    applies_to_provider_key: str
    applies_to_depth_space: str
    #: 사람이 읽는 식의 형태. 계수가 아니라 모양이다.
    form: str
    #: 박스 대표값을 뽑는 퍼센타일. 깊이 공간이 이 값을 바꾼다.
    roi_percentile: float
    #: 이 범위 밖의 상대값은 신뢰하지 않는다.
    valid_rel_range: tuple[float, float]
    #: 이 cm 이하는 **값이 아니라 미측정**이다. 0 으로 자르지 않는다.
    min_valid_cm: float
    status: str
    #: 계수가 나온 파일·함수. 출처 없는 계수를 두지 않는다.
    source: str
    created_at: str = ""
    #: 가중치·crop·전처리·대표값 규칙. 하나라도 다르면 다른 구성이다(AI-B-01).
    input_conditions: dict = field(default_factory=dict)
    #: 측정된 품질. 미측정 항목은 **키를 넣지 않는다**(0 으로 채우지 않는다).
    quality: dict = field(default_factory=dict)
    #: 범위 밖에서 식 값을 돌려줄지(표시만 함) 아예 None 으로 할지. 기준으로
    #: 검증되지 않은 구간은 내지 않는 편이 기본이다.
    out_of_range_returns_none: bool = True
    fn: Callable[..., float | None] | None = field(default=None, compare=False, repr=False)

    @property
    def is_robot_measured(self) -> bool:
        """로봇 실측으로 만든 식인가. 아니면 다른 경로를 기준으로 맞춘 것이다."""
        return self.status == PROFILE_STATUS_DEPLOYED

    def in_range(self, rel: float | None) -> bool:
        if rel is None or not math.isfinite(rel):
            return False
        lo, hi = self.valid_rel_range
        return lo <= rel <= hi

    def to_cm(self, rel: float | None, *, bbox_original=None,
              image_w: int = 0, image_h: int = 0) -> float | None:
        if rel is None or not math.isfinite(rel) or self.fn is None:
            return None
        cm = self.fn(rel, bbox=bbox_original, image_w=image_w, image_h=image_h)
        if cm is None:
            return None
        cm = float(cm)
        # **0cm 클램프 금지.** 바닥값 이하는 "거리 미확정" 이고 "로봇 바로 앞" 이 아니다.
        return None if cm <= self.min_valid_cm else cm

    def describe(self) -> dict:
        return {
            "profile_id": self.profile_id, "version": self.version, "status": self.status,
            "applies_to": {"provider_key": self.applies_to_provider_key,
                           "depth_space": self.applies_to_depth_space,
                           **self.input_conditions},
            "form": self.form, "roi_percentile": self.roi_percentile,
            "valid_rel_range": list(self.valid_rel_range),
            "min_valid_cm": self.min_valid_cm, "source": self.source,
            "created_at": self.created_at, "quality": dict(self.quality),
            "robot_measured": self.is_robot_measured,
        }


@dataclass(frozen=True)
class DistanceMeasurement:
    """박스 하나의 거리. **`distance_cm=None` 은 0cm 가 아니라 미측정이다.**"""

    rel_depth: float | None
    distance_cm: float | None
    in_range: bool
    status: str
    profile_id: str | None
    provider_key: str | None
    depth_space: str | None

    @property
    def distance_m(self) -> float | None:
        return None if self.distance_cm is None else self.distance_cm / 100.0


def calibrate_measurement(profile: DepthCalibrationProfile | None, field_: DepthField,
                          rel: float | None, *, bbox_original=None) -> DistanceMeasurement:
    """프로파일이 그 출력에 **적용 가능할 때만** cm 를 낸다.

    `provider_key` 나 `depth_space` 가 다르면 값을 내지 않고 예외를 올린다 — 한
    모델의 보정식이 다른 모델 출력에 닿는 경로는 코드상 여기뿐이고 여기서 막힌다.
    """
    if profile is None:
        return DistanceMeasurement(rel, None, False, STATUS_UNMEASURED_NO_PROFILE,
                                   None, field_.provider_key, field_.depth_space)
    if (profile.applies_to_provider_key != field_.provider_key
            or profile.applies_to_depth_space != field_.depth_space):
        raise CalibrationMismatch(
            f"보정 프로파일 {profile.profile_id} 은(는) "
            f"{profile.applies_to_provider_key}/{profile.applies_to_depth_space} 전용인데 "
            f"{field_.provider_key}/{field_.depth_space} 출력에 적용하려 했다 "
            f"(AI-E-02: 보정은 입력 조건에 묶인다)")
    if rel is None or not math.isfinite(rel):
        return DistanceMeasurement(None, None, False, STATUS_UNMEASURED_NO_DEPTH,
                                   profile.profile_id, field_.provider_key, field_.depth_space)

    if profile.fn is None:
        # 묶여는 있지만 식이 없다. 범위 밖이라고 적으면 "그 구간을 안 믿는다" 로
        # 읽히고, 실제로 필요한 일(같은 조건에서 재측정)이 가려진다.
        return DistanceMeasurement(rel, None, False, STATUS_UNMEASURED_NO_FORMULA,
                                   profile.profile_id, field_.provider_key,
                                   field_.depth_space)

    w, h = field_.original_wh
    within = profile.in_range(rel)
    if not within and profile.out_of_range_returns_none:
        return DistanceMeasurement(rel, None, False, STATUS_UNMEASURED_OUT_OF_RANGE,
                                   profile.profile_id, field_.provider_key, field_.depth_space)
    cm = profile.to_cm(rel, bbox_original=bbox_original, image_w=w, image_h=h)
    status = STATUS_MEASURED if (cm is not None and within) else STATUS_UNMEASURED_OUT_OF_RANGE
    return DistanceMeasurement(rel, cm, bool(within and cm is not None), status,
                               profile.profile_id, field_.provider_key, field_.depth_space)


def measure_distance(profile: DepthCalibrationProfile | None, field_: DepthField,
                     box_original) -> DistanceMeasurement:
    """원본 좌표 박스 → 프로파일의 퍼센타일로 뽑은 대표 상대값 → cm."""
    percentile = 50.0 if profile is None else profile.roi_percentile
    rel = roi_representative(field_.values, box_to_depth_pixels(field_, box_original),
                             percentile)
    return calibrate_measurement(profile, field_, rel, bbox_original=box_original)


def bearing_deg(field_: DepthField, box_original) -> tuple[float | None, str]:
    """(방위각, 상태). 내부 파라미터가 없으면 **각도를 지어내지 않는다.**

    역깊이 provider 는 fx·cx 를 내주지 않는다. 그런데도 각도를 내면 숫자는 나오고
    근거는 없다 — 그래서 `None` + `unmeasured_no_intrinsics` 다(AI-C-02).
    """
    if field_.intrinsics is None:
        return None, BEARING_UNMEASURED_NO_INTRINSICS
    fx, cx = field_.intrinsics
    x1, _, x2, _ = box_to_depth_pixels(field_, box_original)
    if not fx:
        return None, BEARING_UNMEASURED_NO_INTRINSICS
    return math.degrees(math.atan2((x1 + x2) / 2.0 - cx, fx)), BEARING_MEASURED
