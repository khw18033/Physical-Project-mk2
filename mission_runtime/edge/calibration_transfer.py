"""입력 조건이 바뀌었을 때 — 환산할 수 있는 변화와 다시 재야 하는 변화.

implements: AI-E-02
관련: AI-C-02 (좌표계 경계), AI-B-01 (다른 구성의 측정값을 자동 재사용하지 않는다),
      AI-N-02 (버전 기반 구성 적용)
tests: tests/test_calibration_transfer.py

조사 정본은 `docs/research/automatic-camera-calibration.md` §7.1 이다. AI-E-02 는 보정을
다시 해야 하는 조건으로 "해상도·crop·zoom·장착 상태 등 입력 조건이 바뀌거나" 를 적는데,
조사에서 가장 실무적으로 유용했던 발견은 **그것이 한 가지 사건이 아니라 두 가지**라는
것이었다 — 기하적으로 환산 가능한 변화와 재추정을 요구하는 변화.

### 이 모듈의 중심 — 해상도만 보고는 구분할 수 없다

1920x1080 보정판을 가진 카메라가 960x540 프레임을 내기 시작했다. 무엇이 일어났는가?

- **축소(resize)**: 화각이 그대로다. fx, fy, cx, cy 를 0.5배 하면 **정확히** 맞는다.
- **중앙 crop**: 화각이 절반이다. 초점거리는 그대로이고 주점만 offset 만큼 옮겨진다.

두 경우의 `image_size` 는 **같다**. 그래서 해상도 값만으로는 판정할 수 없고, 추측해서
환산하면 틀린 보정이 조용히 투영에 들어간다. 이 모듈은 그래서 **선언된 변환**
(`InputTransform`)을 요구한다. 선언이 없으면 판정은 `requires_reestimation` 이다 —
문서 §7.1 의 결론("틀린 환산보다 '적용 불가' 가 안전하다")을 그대로 지킨다.

### 판정 넷

| 판정 | 조건 | 무엇을 하는가 |
|---|---|---|
| `unchanged` | 적용 범위가 그대로다 | 그 프로파일을 쓴다 |
| `convertible_resize` | 선언된 균일 배율 | fx·fy·cx·cy 를 배율로 환산. 왜곡 계수는 해상도 무관이라 그대로 |
| `convertible_crop` | 선언된 픽셀 offset | 주점만 옮긴다. 초점거리·왜곡은 그대로 |
| `requires_reestimation` | zoom 토큰 변경, 장착 변경, 선언 없음, binning/readout 변경 | 아무것도 환산하지 않는다. 이전 프로파일을 유지하고 재보정 신호를 낸다 |

`zoom_token` 변경은 **언제나** 재추정이다. 광학 zoom 은 초점거리를 바꾸고, 디지털
zoom 은 crop 이지만 토큰은 offset 을 말해 주지 않는다 — 환산에 필요한 수를 모르면
환산은 추측이다.

### 환산한 값은 재검증된 값이 아니다

환산된 프로파일은 `validated_by` 에 원래 검증 항목을 **물려받지 않는다.** 대신
`geometrically_transferred` 하나만 적고 `quality` 에 `transferred_from_version` 을
남긴다. 재투영 RMS 는 픽셀 단위이므로 배율만큼 같이 바뀌지만, 그 값은 **다시 측정한
것이 아니라 환산한 것**이라 `reprojection_rms_px_transferred` 라는 다른 키로 적는다 —
AI-B-01 이 "다른 구성에서 측정한 성능을 자동으로 동일하다고 가정해서는 안 된다" 고
적은 그 규칙이고, 키 이름이 다르면 나중에 둘을 섞어 평균할 수 없다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Literal

import numpy as np

from mission_runtime.edge.calibration_profile import (
    ApplicabilityScope,
    CalibrationProfile,
)

__all__ = [
    "INPUT_CHANGE_VERDICTS",
    "TRANSFER_REFUSAL_REASONS",
    "InputTransform",
    "TransferResult",
    "classify_input_change",
    "transfer_profile",
]

#: 입력 조건 변화의 판정 어휘. 서열이 아니라 **종류**다 — `requires_reestimation` 은
#: 실패가 아니고 "이 변화는 환산으로 못 넘긴다" 는 사실이다.
INPUT_CHANGE_VERDICTS: tuple[str, ...] = (
    "unchanged",
    "convertible_resize",
    "convertible_crop",
    "requires_reestimation",
)

#: 환산을 거절하는 사유.
TRANSFER_REFUSAL_REASONS: tuple[str, ...] = (
    "transform_not_declared",       # 해상도만 바뀐 것을 보았다 — resize 인지 crop 인지 모른다
    "zoom_token_changed",           # 초점거리가 바뀌었을 수 있다. 토큰은 수를 말하지 않는다
    "mount_token_changed",          # 외부 파라미터가 무효다
    "camera_id_mismatch",           # 다른 카메라의 보정이다
    "non_uniform_scale",            # 균일 배율이 아니다 — 화소 종횡비가 바뀌었다
    "declared_scale_inconsistent",  # 선언된 배율이 실제 해상도 비와 맞지 않는다
    "crop_outside_source_frame",    # 선언된 crop 창이 원본 밖이다
    "sensor_readout_changed",       # binning/windowing — 단순 배율이 아니다(문서 §7.1)
    "no_source_profile",            # 넘길 프로파일이 없다
)

#: 선언된 배율과 해상도 비가 이 비율 이상 어긋나면 선언을 믿지 않는다.
SCALE_CONSISTENCY_TOLERANCE = 0.01


@dataclass(frozen=True)
class InputTransform:
    """원본 보정 조건 → 현재 입력 조건으로 가는 **선언된** 변환.

    `kind` 가 "unknown" 인 것이 기본이고 그것이 정직한 기본값이다 — 미디어 경로가 새
    해상도의 프레임을 주기 시작했다는 사실만으로는 무엇이 일어났는지 알 수 없다.
    선언은 장치 조인(`registry/onboarding.py`)이나 카메라 정보 입력에서 온다.
    """

    kind: Literal["unknown", "resize", "crop"] = "unknown"
    #: resize 의 배율. None 이면 해상도 비에서 유도한다(그래도 선언된 kind 가 필요하다).
    scale: tuple[float, float] | None = None
    #: crop 의 좌상단 offset(px). 주점이 이만큼 **줄어든다**.
    crop_offset_px: tuple[int, int] | None = None
    #: 센서 readout 모드·binning 이 함께 바뀌었는가. True 면 단순 배율이 아니다.
    sensor_readout_changed: bool = False


@dataclass(frozen=True)
class TransferResult:
    """환산 결과. 거절도 결과다 — 사유가 재보정 신호의 입력이 된다."""

    verdict: str
    profile: CalibrationProfile | None
    reasons: tuple[str, ...] = ()

    @property
    def transferred(self) -> bool:
        return self.profile is not None


def classify_input_change(
    source: ApplicabilityScope | None,
    target: ApplicabilityScope,
    transform: InputTransform | None = None,
) -> tuple[str, tuple[str, ...]]:
    """두 적용 범위 사이의 변화를 판정한다. 판정과 사유를 함께 낸다.

    `source` 가 None(적용 범위를 선언하지 않은 옛 프로파일)이면 비교할 기준이 없으므로
    `requires_reestimation` 이다. 범위를 모르는 프로파일을 새 조건에 환산해 주면
    "모든 조건에서 검증됐다" 로 읽히기 시작한다.
    """
    reasons: list[str] = []
    if source is None:
        return ("requires_reestimation", ("transform_not_declared",))

    if source.camera_id and target.camera_id and source.camera_id != target.camera_id:
        return ("requires_reestimation", ("camera_id_mismatch",))
    if source.mount_token and target.mount_token and source.mount_token != target.mount_token:
        reasons.append("mount_token_changed")
    if source.zoom_token != target.zoom_token:
        reasons.append("zoom_token_changed")
    if transform is not None and transform.sensor_readout_changed:
        reasons.append("sensor_readout_changed")
    if reasons:
        return ("requires_reestimation", tuple(reasons))

    same_size = source.image_size == target.image_size
    if same_size and (transform is None or transform.kind == "unknown"):
        return ("unchanged", ())

    if transform is None or transform.kind == "unknown":
        return ("requires_reestimation", ("transform_not_declared",))

    if source.image_size is None or target.image_size is None:
        return ("requires_reestimation", ("transform_not_declared",))

    src_w, src_h = source.image_size
    dst_w, dst_h = target.image_size

    if transform.kind == "resize":
        scale = transform.scale or (dst_w / src_w, dst_h / src_h)
        sx, sy = float(scale[0]), float(scale[1])
        if sx <= 0.0 or sy <= 0.0:
            return ("requires_reestimation", ("declared_scale_inconsistent",))
        if (abs(sx * src_w - dst_w) > max(1.0, SCALE_CONSISTENCY_TOLERANCE * dst_w)
                or abs(sy * src_h - dst_h) > max(1.0, SCALE_CONSISTENCY_TOLERANCE * dst_h)):
            return ("requires_reestimation", ("declared_scale_inconsistent",))
        if abs(sx / sy - 1.0) > SCALE_CONSISTENCY_TOLERANCE:
            # 비균일 배율은 이상적인 pinhole 에서는 환산 가능하지만, 실제 센서에서
            # 종횡비가 바뀌는 것은 거의 항상 crop 이나 readout 변경이다(문서 §7.1).
            return ("requires_reestimation", ("non_uniform_scale",))
        return ("convertible_resize", ())

    if transform.kind == "crop":
        if transform.crop_offset_px is None:
            return ("requires_reestimation", ("transform_not_declared",))
        off_x, off_y = transform.crop_offset_px
        if off_x < 0 or off_y < 0 or off_x + dst_w > src_w or off_y + dst_h > src_h:
            return ("requires_reestimation", ("crop_outside_source_frame",))
        return ("convertible_crop", ())

    return ("requires_reestimation", ("transform_not_declared",))


def transfer_profile(
    profile: CalibrationProfile | None,
    target: ApplicabilityScope,
    transform: InputTransform | None = None,
    *,
    version: int | None = None,
) -> TransferResult:
    """환산 가능한 변화면 환산한 프로파일을, 아니면 사유를 낸다.

    환산된 프로파일은 **재검증된 것이 아니다** — `validated_by` 는
    `("geometrically_transferred",)` 하나이고, 원래 프로파일이 통과한 검증 항목을
    물려받지 않는다. 외부 파라미터는 그대로 따라간다(해상도·crop 은 카메라를 옮기지
    않는다). 그러나 `mount_token` 이 바뀐 경우는 애초에 `requires_reestimation` 이라
    여기에 도달하지 않는다.
    """
    if profile is None:
        return TransferResult("requires_reestimation", None, ("no_source_profile",))

    verdict, reasons = classify_input_change(profile.applicability, target, transform)
    if verdict == "unchanged":
        return TransferResult(verdict, profile, ())
    if verdict == "requires_reestimation":
        return TransferResult(verdict, None, reasons)

    matrix = np.asarray(profile.camera_matrix, dtype=float).copy()
    source_scope = profile.applicability
    assert source_scope is not None and source_scope.image_size is not None
    assert target.image_size is not None

    quality = dict(profile.quality)
    quality["transferred_from_version"] = float(profile.version)

    if verdict == "convertible_resize":
        src_w, src_h = source_scope.image_size
        dst_w, dst_h = target.image_size
        assert transform is not None
        sx, sy = transform.scale or (dst_w / src_w, dst_h / src_h)
        matrix[0, 0] *= sx
        matrix[0, 2] *= sx
        matrix[1, 1] *= sy
        matrix[1, 2] *= sy
        quality["transfer_scale"] = float(sx)
        # 픽셀 단위 품질은 배율만큼 같이 바뀐다 — 그러나 **환산값이라 키를 바꾼다**.
        if math.isfinite(profile.reprojection_error_rms):
            quality.pop("reprojection_rms_px", None)
            quality["reprojection_rms_px_transferred"] = (
                float(profile.reprojection_error_rms) * float(sx)
            )
        transferred_rms = (
            profile.reprojection_error_rms * float(sx)
            if math.isfinite(profile.reprojection_error_rms)
            else profile.reprojection_error_rms
        )
    else:  # convertible_crop — 주점만 옮긴다. 초점거리는 그대로다(문서 §7.1).
        assert transform is not None and transform.crop_offset_px is not None
        off_x, off_y = transform.crop_offset_px
        matrix[0, 2] -= float(off_x)
        matrix[1, 2] -= float(off_y)
        quality["transfer_crop_offset_x_px"] = float(off_x)
        quality["transfer_crop_offset_y_px"] = float(off_y)
        transferred_rms = profile.reprojection_error_rms

    return TransferResult(
        verdict,
        replace(
            profile,
            version=profile.version if version is None else version,
            camera_matrix=matrix,
            reprojection_error_rms=transferred_rms,
            applicability=target,
            method_id=f"{profile.method_id}+transferred" if profile.method_id else "transferred",
            validated_by=("geometrically_transferred",),
            quality=quality,
        ),
        (),
    )
