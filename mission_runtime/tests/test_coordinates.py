"""implements: AI-C-02
covers: frame tagging, calibration-gated lifting, global transform boundary
"""

import pytest

from mission_runtime.common.coordinates import (
    CoordinateFrame,
    DATUM_ADDRESS_APPROX,
    DATUM_GNSS_FIX,
    DATUM_SURVEYED,
    GLOBAL_DATUM_UNVERIFIED,
    GLOBAL_DATUM_ZONE_MISMATCH,
    GLOBAL_NOT_LOCAL_INPUT,
    GLOBAL_NO_DATUM,
    SiteDatum,
    SpatialValue,
    to_camera_local,
    to_global,
)


def camera_local_value() -> SpatialValue:
    return SpatialValue((1.2, 3.4), CoordinateFrame.CAMERA_LOCAL, "cam-1", unit="m")


def surveyed_datum() -> SiteDatum:
    """측량 성과로 잡은 기준점. 검증된 것으로 보는 출처다."""
    return SiteDatum(datum_id="site-datum", zone_or_site_id="cam-1",
                     latitude_deg=36.3504, longitude_deg=127.3845,
                     source=DATUM_SURVEYED, accuracy_m=0.03, version="2026-11-03.1")


def approximate_datum() -> SiteDatum:
    """주소에서 찍은 근사 기준점. 쓸 수는 있으나 검증된 것이 아니다."""
    return SiteDatum(datum_id="rough-datum", zone_or_site_id="cam-1",
                     latitude_deg=36.35, longitude_deg=127.38,
                     source=DATUM_ADDRESS_APPROX, accuracy_m=30.0)


def image_value(source_id="cam-1"):
    return SpatialValue(values=(100.0, 200.0), frame=CoordinateFrame.IMAGE, source_id=source_id)


def test_image_value_stays_image_frame_without_calibration():
    # 보정 정보가 없으면 로컬 영상 좌표 결과를 유지해야 한다 (AI-C-02).
    result = to_camera_local(image_value(), calibration_profile=None)

    assert result.frame is CoordinateFrame.IMAGE
    assert result.calibration_profile_version is None


def test_image_value_is_lifted_only_when_calibration_profile_present():
    result = to_camera_local(image_value(), calibration_profile=object(), profile_version="v3")

    assert result.frame is CoordinateFrame.CAMERA_LOCAL
    assert result.calibration_profile_version == "v3"
    assert result.values == (100.0, 200.0)


def test_camera_local_values_from_different_sources_are_not_comparable():
    a = to_camera_local(image_value("cam-1"), calibration_profile=object())
    b = to_camera_local(image_value("cam-2"), calibration_profile=object())

    assert not a.is_comparable_with(b)
    assert a.is_comparable_with(a)


def test_image_and_camera_local_are_never_mixed():
    raw = image_value()
    lifted = to_camera_local(raw, calibration_profile=object())

    assert not raw.is_comparable_with(lifted)


def test_a_global_promotion_needs_a_declared_datum():
    """2026-11-03 경계 개정: 전역 좌표는 우리 소유가 됐다.

    그 전까지 이 자리에는 `to_global` 이 `NotImplementedError` 를 던지는지 보는 시험이
    있었다 — 전역 변환이 백엔드 몫이었기 때문이다. 소유가 옮겨졌으니 확인할 것도
    바뀐다: **거부되는가** 가 아니라 **값을 치르는가**.

    옛 규칙이 막던 실패는 "AI 가 전역 좌표를 만든다" 가 아니라 *같은 사실에
    authoritative 주인이 둘* 이었고, 소유권 이전은 그 실패를 없애지 않고 자리만 옮긴다.
    그래서 datum 없이는 올라가지 않는다 — 예외가 아니라 사유를 담은 거절이다. datum 을
    선언하지 않은 현장이 정상 상태이기 때문이다(AI-C-05).
    """
    refused = to_global(camera_local_value(), None)

    assert refused.promoted is False
    assert refused.reason == GLOBAL_NO_DATUM
    assert refused.value is None


def test_a_promoted_value_is_owned_by_its_datum_not_by_the_camera():
    promoted = to_global(camera_local_value(), surveyed_datum())

    assert promoted.promoted is True
    assert promoted.value.frame is CoordinateFrame.GLOBAL
    # 전역 값의 주인은 그 카메라가 아니라 기준점이다 — 카메라로 남기면 서로 다른
    # 카메라에서 온 전역 값이 비교 불가로 보인다.
    assert promoted.value.source_id == "site-datum"


def test_a_global_value_never_claims_better_accuracy_than_its_datum():
    """cm 로 잰 로컬 좌표를 수십 m 오차의 기준점으로 올리면 결과는 수십 m 급이다."""
    rough = to_global(camera_local_value(), approximate_datum())

    assert rough.accuracy_floor_m == 30.0
    assert rough.datum_verified is False


def test_an_undeclared_datum_accuracy_stays_unknown_rather_than_zero():
    datum = SiteDatum(datum_id="site-datum", zone_or_site_id="cam-1",
                      latitude_deg=36.0, longitude_deg=127.0, source=DATUM_GNSS_FIX)

    promoted = to_global(camera_local_value(), datum)

    assert promoted.promoted is True
    assert promoted.accuracy_floor_m is None, "미측정 정확도는 0 오차가 아니다"


def test_a_declared_accuracy_of_zero_is_a_declaration_error():
    with pytest.raises(ValueError):
        SiteDatum(datum_id="d", zone_or_site_id="z", latitude_deg=0.0,
                  longitude_deg=0.0, accuracy_m=0.0)


def test_an_unverified_datum_is_refused_where_verification_is_required():
    """책임 있는 판단에 쓰이는 자리에서는 근사 기준점을 측량 성과처럼 소비하지 않는다."""
    refused = to_global(camera_local_value(), approximate_datum(),
                        require_verified_datum=True)

    assert refused.promoted is False
    assert refused.reason == GLOBAL_DATUM_UNVERIFIED
    # 거절해도 그 기준점이 무엇이었는지는 남긴다 — 운영자가 보완할 대상이다.
    assert refused.datum_id == "rough-datum"


def test_another_sites_datum_is_refused_rather_than_applied():
    """다른 현장의 기준점을 적용하면 좌표가 조용히 수백 m 어긋난다."""
    other = SiteDatum(datum_id="elsewhere", zone_or_site_id="cam-9",
                      latitude_deg=36.0, longitude_deg=127.0)

    refused = to_global(camera_local_value(), other)

    assert refused.promoted is False
    assert refused.reason.startswith(GLOBAL_DATUM_ZONE_MISMATCH)


def test_an_image_value_cannot_skip_the_local_frame():
    """보정 없이 픽셀에서 전역으로 뛰면 보정이 하던 일이 사라진다."""
    refused = to_global(image_value(), surveyed_datum())

    assert refused.promoted is False
    assert refused.reason == GLOBAL_NOT_LOCAL_INPUT


def test_promoting_an_already_global_value_is_refused():
    """두 번 올리면 기준점이 두 번 적용된다."""
    once = to_global(camera_local_value(), surveyed_datum()).value

    assert to_global(once, surveyed_datum()).promoted is False



def test_camera_local_values_with_mismatched_axis_convention_are_not_comparable():
    # REP-103: body convention과 camera optical convention을 같은 frame/source_id로
    # 착각하면 두 provider가 서로 다른 축 관례를 쓰고도 comparable로 오판될 수 있다.
    a = to_camera_local(
        image_value("cam-1"), calibration_profile=object(), axis_convention="ros_rep103_optical"
    )
    b = to_camera_local(
        image_value("cam-1"), calibration_profile=object(), axis_convention="ros_rep103_body"
    )

    assert not a.is_comparable_with(b)


def test_camera_local_values_with_unstated_axis_convention_stay_comparable():
    # 두 값 다 axis_convention을 명시하지 않았다면(None) 기존 동작(같은 source_id면
    # comparable)을 그대로 유지한다 — optional 정보 부재가 축소를 강제하지 않는다.
    a = to_camera_local(image_value("cam-1"), calibration_profile=object())
    b = to_camera_local(image_value("cam-1"), calibration_profile=object())

    assert a.is_comparable_with(b)


def test_camera_local_values_with_mismatched_unit_are_not_comparable():
    a = to_camera_local(image_value("cam-1"), calibration_profile=object(), unit="m")
    b = to_camera_local(image_value("cam-1"), calibration_profile=object(), unit="mm")

    assert not a.is_comparable_with(b)
