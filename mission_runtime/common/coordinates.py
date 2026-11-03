"""Coordinate-frame boundary: every spatial value carries what frame it
came from, and a promotion to the global frame costs a declared datum.

implements: AI-C-02, AI-C-19
tests: tests/test_coordinates.py

AI-C-02 (2026-11-03 개정): "AI가 산출하는 위치·방향·영상 좌표에는 어떤 기준 좌표계에서
나온 값인지 알 수 있는 정보가 포함되어야 한다 ... **전역 좌표 변환도 AI가 담당한다** ...
전역 변환은 현장 로컬↔전역 기준점(site datum)을 통해 수행하며, datum 은 출처·생성
시점·버전과 선언된 정확도를 가진 근거로 관리해야 한다. 미측정 정확도는 0 오차가 아니며,
검증되지 않은 datum 으로 유도한 전역 값은 그 재료인 로컬 측정보다 높은 확신을
주장해서는 안 된다."

## 소유권이 옮겨졌다는 것의 뜻

2026-11-02 까지 이 모듈은 전역 변환을 **거부**했다 — 그것이 백엔드 디지털 트윈의 몫
이었기 때문이다(BE-C-04, DT-03). 2026-11-03 에 소유가 AI 로 옮겨졌고, 그래서
`to_global()` 은 더 이상 `NotImplementedError` 가 아니다.

그런데 옛 규칙이 막고 있던 실패는 "AI 가 전역 좌표를 만든다"가 아니라 **같은 사실에
authoritative 주인이 둘**이었다. 소유권을 옮기는 것은 그 실패를 없애지 않고 자리만
옮긴다. 그래서 이 모듈은 거부를 걷어내는 대신 **값을 치르게** 한다.

* 로컬 값과 전역 값은 교환 가능하지 않다. 프레임은 끝까지 값에 붙어 다닌다.
* 전역 변환은 공리가 아니라 `SiteDatum` 이라는 **근거**를 요구한다. datum 에는 출처와
  생성 시점과 **선언된 정확도**가 있고, 정확도를 모르면 모르는 채로 남는다 — 0 오차가
  아니다.
* datum 이 없거나 검증되지 않은 현장은 **정상 상태**다. 전역 계층만 비활성이 되고
  로컬 판단은 그대로 돌아간다(AI-C-05). 그래서 `to_global` 은 예외가 아니라 사유를 담은
  거절을 돌려준다 — 단일 카메라·단일 구역 배치가 전역 기준점 없이도 끝까지 동작해야
  한다.

이 셋을 빼고 소유권만 가져오면, 검증되지 않은 기준점에서 유도한 전역 좌표가 실측 로컬
좌표와 같은 확신으로 화면에 올라간다. 그것이 이 모듈이 막는 구체적인 사고다.

The rule on the local side is unchanged and deliberately narrow: an
image-plane value may be lifted to a camera-local ray/space **only** when a
valid calibration profile is supplied.

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
    GLOBAL       - site/world frame. **AI 가 소유한다**(2026-11-03 개정). 다만
                   도달하려면 `SiteDatum` 이 필요하고, datum 이 없으면 이 프레임의
                   값은 만들어지지 않는다 — 없는 기준점을 가정해 만든 전역 좌표는
                   정확한 값이 아니라 그럴듯한 값이다.
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


#: 전역 변환이 거절되는 사유. 통제 어휘이고 표시 문구가 아니다 —
#: 등록처는 `contracts/data_dictionary.py::COORDINATE_REASONS`.
GLOBAL_NO_DATUM = "global_no_site_datum"
GLOBAL_DATUM_UNVERIFIED = "global_site_datum_unverified"
GLOBAL_DATUM_ZONE_MISMATCH = "global_site_datum_zone_mismatch"  # + ":<declared>/<asked>"
GLOBAL_NOT_LOCAL_INPUT = "global_input_not_in_local_frame"
GLOBAL_PROMOTED = "global_promoted"

#: datum 의 출처. 품질이 **자릿수 단위로** 다르므로 한 칸에 담지 않는다.
DATUM_SURVEYED = "surveyed_control_point"    # 측량 성과. 보통 cm 급
DATUM_GNSS_FIX = "gnss_fix"                  # 수신기 1점. 보통 m 급
DATUM_MAP_ALIGNED = "map_aligned"            # 도면·위성영상 정합. 수 m 급
DATUM_ADDRESS_APPROX = "address_approximate"  # 주소에서 찍은 근사. 수십 m 급

#: 검증된 것으로 보는 출처. 나머지는 쓸 수는 있으나 `verified` 가 아니고, 그 사실이
#: 유도된 전역 값에 그대로 전파된다.
VERIFIED_DATUM_SOURCES: frozenset[str] = frozenset({DATUM_SURVEYED, DATUM_GNSS_FIX})


@dataclass(frozen=True)
class SiteDatum:
    """현장 로컬 프레임을 전역 프레임에 묶는 기준점. **근거이고 공리가 아니다.**

    전역 기준은 WGS84 측지 좌표(lat/lon/alt)로 두고, 현장 로컬은 그 점에 접하는
    평면(ENU: x=동, y=북)으로 본다. 이 선택이 특별히 옳아서가 아니라 — 두 실제 현장의
    위치가 주소로 주어지고, GNSS 수신기가 내는 것이 이 좌표계이며, 도면 정합도 이
    평면에서 하기 때문이다. 다른 기준계를 쓰는 현장은 `reference_frame` 을 바꿔 선언하고
    변환 provider 를 교체한다(AI-C-04) — 이 모듈에 측지 변환 라이브러리를 들이지 않는다.

    `accuracy_m` 은 **선언값**이다. 모르면 `None` 으로 남고 0 이 되지 않는다. 이 값이
    유도된 전역 좌표의 정확도 하한이 된다 — 1 cm 로 잰 로컬 좌표를 30 m 오차의
    기준점으로 올리면 결과는 30 m 급이고, 그 사실이 지워지면 화면이 거짓을 말한다.
    """

    datum_id: str
    #: 이 datum 이 묶는 로컬 프레임의 주인. 다른 현장 값에 적용되지 않게 한다.
    zone_or_site_id: str
    latitude_deg: float
    longitude_deg: float
    altitude_m: float | None = None
    #: 로컬 x 축이 북(ENU 의 +y)에서 시계방향으로 얼마나 돌아 있는가.
    yaw_offset_deg: float = 0.0
    source: str = DATUM_ADDRESS_APPROX
    accuracy_m: float | None = None
    established_at: float | None = None
    version: str | None = None
    reference_frame: str = "WGS84"

    def __post_init__(self) -> None:
        if not self.datum_id or not self.zone_or_site_id:
            raise ValueError("a datum must name itself and the local frame it binds")
        if not -90.0 <= self.latitude_deg <= 90.0:
            raise ValueError(f"latitude out of range: {self.latitude_deg}")
        if not -180.0 <= self.longitude_deg <= 180.0:
            raise ValueError(f"longitude out of range: {self.longitude_deg}")
        if self.accuracy_m is not None and self.accuracy_m <= 0.0:
            # 0 이나 음수 정확도는 "오차 없음" 이 아니라 선언 오류다. 통과시키면
            # 그 datum 이 모든 비교에서 이긴다.
            raise ValueError(f"accuracy_m must be positive when declared: {self.accuracy_m}")

    @property
    def verified(self) -> bool:
        """측량·GNSS 로 잡힌 기준점만 검증된 것으로 본다."""
        return self.source in VERIFIED_DATUM_SOURCES

    def as_dict(self) -> dict:
        body: dict[str, object] = {
            "datum_id": self.datum_id,
            "zone_or_site_id": self.zone_or_site_id,
            "latitude_deg": self.latitude_deg,
            "longitude_deg": self.longitude_deg,
            "yaw_offset_deg": self.yaw_offset_deg,
            "source": self.source,
            "verified": self.verified,
            "reference_frame": self.reference_frame,
        }
        # 없는 칸은 null 로 채우지 않고 뺀다 — 모르는 것과 0 은 다르다.
        for name in ("altitude_m", "accuracy_m", "established_at", "version"):
            value = getattr(self, name)
            if value is not None:
                body[name] = value
        return body


@dataclass(frozen=True)
class GlobalPromotion:
    """전역 변환 1회의 결과. 성공해도 **얼마나 믿을 값인지** 함께 낸다."""

    reason: str
    value: SpatialValue | None = None
    datum_id: str | None = None
    #: 유도된 전역 값의 정확도 하한. datum 이 정확도를 선언하지 않았으면 `None` —
    #: 미측정이고 0 이 아니다.
    accuracy_floor_m: float | None = None
    datum_verified: bool = False

    @property
    def promoted(self) -> bool:
        return self.value is not None

    def as_dict(self) -> dict:
        body: dict[str, object] = {
            "reason": self.reason, "promoted": self.promoted,
            "datum_verified": self.datum_verified,
        }
        if self.datum_id is not None:
            body["datum_id"] = self.datum_id
        if self.accuracy_floor_m is not None:
            body["accuracy_floor_m"] = self.accuracy_floor_m
        return body


def to_global(
    value: SpatialValue,
    datum: SiteDatum | None,
    *,
    local_frame_id: str | None = None,
    require_verified_datum: bool = False,
) -> GlobalPromotion:
    """로컬 값을 전역 프레임으로 올린다. **예외를 던지지 않는다.**

    올릴 수 없는 경우가 장애가 아니라 정상 상태이기 때문이다 — datum 을 선언하지 않은
    현장이 대부분이고, 그 현장의 로컬 판단은 전역 기준점 없이 끝까지 동작해야 한다
    (AI-C-05). 그래서 결과는 사유를 담은 `GlobalPromotion` 이고, 호출자는 `promoted`
    가 False 인 경우를 축소 경로로 다룬다.

    `require_verified_datum=True` 는 전역 좌표가 책임 있는 판단에 쓰이는 자리에서
    쓴다 — 주소에서 찍은 근사 기준점으로 올린 좌표를 측량 성과처럼 소비하지 않게.
    """
    if value.frame is not CoordinateFrame.CAMERA_LOCAL:
        # IMAGE 값은 보정 없이 전역으로 갈 수 없고, 이미 GLOBAL 인 값을 두 번 올리면
        # 기준점이 두 번 적용된다.
        return GlobalPromotion(reason=GLOBAL_NOT_LOCAL_INPUT)
    if datum is None:
        return GlobalPromotion(reason=GLOBAL_NO_DATUM)

    asked = local_frame_id or value.source_id
    if datum.zone_or_site_id != asked:
        # 다른 현장의 기준점을 적용하면 좌표가 조용히 수백 m 어긋난다.
        return GlobalPromotion(
            reason=f"{GLOBAL_DATUM_ZONE_MISMATCH}:{datum.zone_or_site_id}/{asked}",
            datum_id=datum.datum_id)
    if require_verified_datum and not datum.verified:
        return GlobalPromotion(reason=GLOBAL_DATUM_UNVERIFIED, datum_id=datum.datum_id,
                               accuracy_floor_m=datum.accuracy_m)

    promoted = SpatialValue(
        values=value.values,
        frame=CoordinateFrame.GLOBAL,
        # 전역 값의 주인은 더 이상 그 카메라가 아니라 **그 기준점** 이다. source_id 를
        # 카메라로 남기면 서로 다른 카메라에서 온 전역 값이 비교 불가로 보인다.
        source_id=datum.datum_id,
        calibration_profile_version=value.calibration_profile_version,
        unit=value.unit,
        axis_convention=value.axis_convention,
    )
    return GlobalPromotion(
        reason=GLOBAL_PROMOTED,
        value=promoted,
        datum_id=datum.datum_id,
        # 유도된 전역 값은 기준점보다 정확할 수 없다. 이 하한이 지워지면 화면이
        # cm 급으로 잰 로컬 값과 수십 m 급 기준점에서 올린 값을 같게 그린다.
        accuracy_floor_m=datum.accuracy_m,
        datum_verified=datum.verified,
    )
