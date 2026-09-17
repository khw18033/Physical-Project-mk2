"""implements: AI-C-02
covers: frame tagging, calibration-gated lifting, global transform boundary
"""

import pytest

from perception_framework.common.coordinates import (
    CoordinateFrame,
    SpatialValue,
    to_camera_local,
    to_global,
)


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


def test_global_transform_is_refused_inside_ai():
    # 전역 좌표 변환은 백엔드 디지털 트윈 책임 (AI-C-02).
    with pytest.raises(NotImplementedError):
        to_global(image_value())


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
