"""Coordinate-frame boundary: every spatial value carries what frame it
came from, and global transforms stay outside this framework.

implements: AI-C-02

AI-C-02: "AI가 산출하는 위치·방향·영상 좌표에는 어떤 기준 좌표계에서 나온 값인지
알 수 있는 정보가 포함되어야 한다 ... 전역 좌표 변환은 백엔드 디지털 트윈이
담당해야 한다. 보정 정보나 전역 변환 기능이 없으면 로컬 영상 좌표 결과를 유지해야
한다."

The rule this module enforces is deliberately narrow: an image-plane
value may be lifted to a camera-local ray/space **only** when a valid
calibration profile is supplied, and it is never promoted to a global
frame here at all — that promotion belongs to the backend digital twin
(BE-C-04, DT-03).

`unit`/`axis_convention` follow ROS REP-103/REP-105's distinction between
body convention (x-forward/y-left/z-up) and camera optical convention
(z-forward/x-right/y-down) — two CAMERA_LOCAL values can share a frame and
`source_id` yet disagree on which axis convention they were produced in
(e.g. one provider emits raw OpenCV optical-frame rays, another rotates
into body frame first). Both fields are free-form tags, not an enum, per
the project's "벤더 enum이 아니라 자유 문자열 태그" convention — and both
default to `None` ("not stated") rather than an assumed value, so existing
callers that never set them keep comparing exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CoordinateFrame(str, Enum):
    """Which reference frame a spatial value is expressed in.

    IMAGE        - pixel coordinates of one specific source frame. Always
                   available; requires no calibration at all.
    CAMERA_LOCAL - metric/ray coordinates relative to one camera, only
                   reachable with a valid calibration profile (AI-E-03).
    GLOBAL       - site/world frame. This framework never produces it;
                   the enum member exists only so incoming values from
                   the backend can be labelled and passed through.
    """

    IMAGE = "IMAGE"
    CAMERA_LOCAL = "CAMERA_LOCAL"
    GLOBAL = "GLOBAL"


@dataclass(frozen=True)
class SpatialValue:
    """A spatial result tagged with its frame and its origin source.

    `source_id` identifies which camera/sensor produced it, so two values
    in CAMERA_LOCAL frames from different cameras are never silently
    treated as comparable.
    """

    values: tuple[float, ...]
    frame: CoordinateFrame
    source_id: str
    calibration_profile_version: str | None = None
    unit: str | None = None
    axis_convention: str | None = None

    def is_comparable_with(self, other: "SpatialValue") -> bool:
        """Two values may be compared directly only in the same frame, and
        for camera-local frames only when they came from the same source
        *and*, where both sides declared it, the same unit/axis convention
        (REP-103) — unset fields on either side never block comparison,
        they just mean the check could not confirm agreement.
        """
        if self.frame is not other.frame:
            return False
        if self.frame is CoordinateFrame.GLOBAL:
            return True
        if self.source_id != other.source_id:
            return False
        if self.unit is not None and other.unit is not None and self.unit != other.unit:
            return False
        if (
            self.axis_convention is not None
            and other.axis_convention is not None
            and self.axis_convention != other.axis_convention
        ):
            return False
        return True


def to_camera_local(
    value: SpatialValue,
    calibration_profile: object | None,
    *,
    profile_version: str | None = None,
    unit: str | None = None,
    axis_convention: str | None = None,
) -> SpatialValue:
    """Lift an image-plane value into the camera-local frame if — and only
    if — a calibration profile is actually available.

    When `calibration_profile` is None the input is returned unchanged in
    IMAGE frame rather than raising: a missing optional calibration must
    degrade the result, never disable perception (AI-C-02, AI-E-01).

    `unit`/`axis_convention` are optional and default to `None` (not
    stated) — a caller that knows which REP-103 convention its calibration
    routine produces should pass it through so `is_comparable_with` can
    catch a mismatch against another provider later.
    """
    if value.frame is not CoordinateFrame.IMAGE:
        return value
    if calibration_profile is None:
        return value
    return SpatialValue(
        values=value.values,
        frame=CoordinateFrame.CAMERA_LOCAL,
        source_id=value.source_id,
        calibration_profile_version=profile_version,
        unit=unit,
        axis_convention=axis_convention,
    )


def to_global(value: SpatialValue) -> SpatialValue:
    """Global transformation is out of scope for AI by requirement.

    Kept as an explicit failure rather than an omission so that any future
    attempt to compute a global pose inside AI code is caught immediately
    (AI-C-02: 전역 좌표 변환은 백엔드 디지털 트윈이 담당).
    """
    raise NotImplementedError(
        "global coordinate transformation is the backend digital twin's responsibility (AI-C-02)"
    )
