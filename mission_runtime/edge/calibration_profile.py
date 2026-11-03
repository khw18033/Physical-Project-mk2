"""검증을 통과한 보정만 프로파일이 된다 — 버전·적용 범위·품질과 함께.

implements: AI-E-02
관련: AI-C-02 (좌표계 경계), AI-N-02 (버전 기반 구성 적용), AI-S-08 (사전정보와 관측의 분리)
tests: tests/test_calibration_profile.py, tests/test_auto_calibration.py

AI-E-02: "검증을 통과한 결과만 적용 조건·품질·생성 시점·버전을 포함한 보정
프로파일로 관리·배포해야 한다. 새 보정이 실패하면 마지막 정상 프로파일 또는 영상
좌표 기반 인지를 유지해야 한다."

이 모듈이 지키는 것은 세 가지다.

1. **승격은 검증 통과에만 일어난다.** `submit()` 은 추정을 언제나 이력에 남기지만
   활성 프로파일은 검증을 통과했을 때만 바뀐다. 실패한 추정이 조용히 사라지지 않도록
   `rejections` 에 사유와 **그때 유지된 버전**을 함께 적는다 — 운영자가 "왜 보정이
   안 바뀌었나" 를 물을 수 있어야 재추정 실패와 재추정 미실행이 구분된다.
2. **프로파일은 자기 적용 범위를 들고 다닌다**(`ApplicabilityScope`). 같은 카메라라도
   해상도·crop·zoom·장착이 바뀌면 그 보정은 **다른 조건의 보정**이고, 범위 밖에
   적용하면 틀린 값이 조용히 투영에 쓰인다.
3. **픽셀은 들어오지 않는다.** 프로파일은 추정에 쓴 원본 관측을 `frame_refs` 로만
   가리킨다(AI-C-08) — 업무·구성 경로로 나가는 것은 작은 프로파일뿐이다.

2026-11-03 메모: 이 모듈의 옛 머리말은 `AI-E-03` 을 달고 있었다. CLAUDE.md §5 가
비어 있는 과거 번호는 **재사용하지 않는다**고 적은 그 번호다 — 보정 lifecycle 의
요구사항 ID 는 AI-E-02 하나이므로 머리말을 그쪽으로 정정했다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping, Sequence

from mission_runtime.edge.calibration import CalibrationEstimate


@dataclass(frozen=True)
class ApplicabilityScope:
    """이 보정이 **어떤 입력 조건에서 검증됐는가**(AI-E-02 "적용 조건").

    `image_size`·`zoom_token`·`mount_token` 중 하나라도 선언되지 않았으면 그 축은
    제약하지 않는다 — 모르는 조건을 "아무 조건" 으로 읽는 쪽이 "모든 조건에서
    검증됐다" 로 읽는 쪽보다 안전하다. 다만 선언된 축이 어긋나면 그 프로파일은
    적용 대상이 아니고, 그 불일치가 재보정 신호의 사유가 된다.
    """

    camera_id: str
    #: (width_px, height_px). 해상도가 바뀌면 fx·cx 가 같이 바뀐다.
    image_size: tuple[int, int] | None = None
    #: 광학·디지털 zoom / crop 상태를 가리키는 배치 토큰. 벤더 열거형이 아니다(원칙 #1).
    zoom_token: str = ""
    #: 장착 상태(거치대·각도 프리셋) 토큰. 재장착은 외부 파라미터를 무효화한다.
    mount_token: str = ""

    def covers(self, other: "ApplicabilityScope") -> bool:
        """`other` 조건의 영상에 이 프로파일을 적용해도 되는가."""
        if self.camera_id and other.camera_id and self.camera_id != other.camera_id:
            return False
        for mine, theirs in ((self.image_size, other.image_size),
                             (self.zoom_token, other.zoom_token),
                             (self.mount_token, other.mount_token)):
            if mine and theirs and mine != theirs:
                return False
        return True

    def as_dict(self) -> dict:
        return {"camera_id": self.camera_id,
                "image_size": None if self.image_size is None else list(self.image_size),
                "zoom_token": self.zoom_token, "mount_token": self.mount_token}


@dataclass(frozen=True)
class ProfileRejection:
    """승격되지 못한 추정 1건. **조용한 덮어쓰기의 반대말**이다.

    `kept_version` 이 None 이면 그 카메라에는 아직 정상 프로파일이 없다는 뜻이고,
    소비자는 영상 좌표 기반 인지를 계속 쓴다(AI-E-02 의 마지막 fallback).
    """

    version: int
    created_at: str
    reasons: tuple[str, ...]
    kept_version: int | None
    method_id: str = ""
    reprojection_error_rms: float | None = None


@dataclass(frozen=True)
class CalibrationProfile:
    """배포 단위. 기존 네 칸(행렬·왜곡·품질·유효성)에 적용 범위와 계보를 더했다.

    새 칸은 전부 기본값이 있다 — 보정판 한 장으로 내부 파라미터만 구한 배치에서는
    외부 파라미터 칸이 비어 있는 것이 정상이고, 비어 있음을 0 으로 채우면 "카메라가
    원점에 있다" 는 거짓이 투영에 들어간다.
    """

    version: int
    camera_matrix: object
    dist_coeffs: object
    reprojection_error_rms: float
    created_at: str
    valid: bool
    #: 어느 카메라의 보정인가. 빈 문자열은 단일 카메라 배치의 옛 호출 경로다.
    camera_id: str = ""
    #: 어떤 방법이 냈는가. 방법을 고정하지 않는 요구사항에서 **무엇이 냈는지**는
    #: 프로파일에 남아야 한다(AI-E-02: 특정 방법을 필수로 두지 않는다).
    method_id: str = ""
    applicability: ApplicabilityScope | None = None
    #: (x_m, y_m, yaw_deg) 구역 로컬 외부 파라미터. 전역 좌표가 아니다(AI-C-02).
    extrinsic: tuple[float, float, float] | None = None
    #: 그 외부 파라미터의 **측정된** 1σ 위치 정확도(m). None 은 미측정이고 0 이 아니다 —
    #: 0 은 무한 가중이 되어 사람 실측을 이긴다(AI-S-08, spatial_evidence 규칙 2).
    extrinsic_accuracy_m: float | None = None
    #: 그 자리를 만든 방법. 가시화·트윈이 `pose_source` 로 그대로 읽는다.
    extrinsic_source: str = "estimated"
    #: 통과한 검증 항목 이름. 무엇을 **검증하지 않았는지**도 이 목록의 여집합으로 드러난다.
    validated_by: tuple[str, ...] = ()
    #: 측정된 품질 수치. 미측정 항목은 키를 넣지 않는다(0 으로 채우지 않는다, AI-B-01).
    quality: Mapping[str, float] = field(default_factory=dict)
    #: 추정에 쓴 원본 관측 참조. 픽셀은 여기 들어오지 않는다(AI-C-08).
    frame_refs: tuple[str, ...] = ()
    estimated_at: float = 0.0
    #: 이 보정을 다시 확인해야 하는 시각(epoch). None 은 기한을 선언하지 않았다는 뜻이다.
    valid_until: float | None = None

    @property
    def has_extrinsic(self) -> bool:
        return self.extrinsic is not None

    @property
    def extrinsic_accuracy_known(self) -> bool:
        """외부 파라미터의 정확도를 **실제로 쟀는가**. 거짓이면 미측정이다."""
        return self.extrinsic_accuracy_m is not None

    def applies_to(self, scope: ApplicabilityScope) -> bool:
        """적용 범위를 선언하지 않은 옛 프로파일은 범위를 제한하지 않는다."""
        return self.applicability is None or self.applicability.covers(scope)


class CalibrationProfileStore:
    """카메라 하나의 보정 계보. 활성 프로파일은 검증 통과로만 바뀐다."""

    def __init__(self, *, camera_id: str = "") -> None:
        self._camera_id = camera_id
        self._active: CalibrationProfile | None = None
        self._history: list[CalibrationProfile] = []
        self._rejections: list[ProfileRejection] = []
        self._next_version = 1

    @property
    def camera_id(self) -> str:
        return self._camera_id

    @property
    def active(self) -> CalibrationProfile | None:
        return self._active

    @property
    def history(self) -> list[CalibrationProfile]:
        return list(self._history)

    @property
    def rejections(self) -> list[ProfileRejection]:
        """승격되지 못한 추정들. 비어 있지 않은 것이 **정상 운용**일 수 있다."""
        return list(self._rejections)

    @property
    def last_rejection(self) -> ProfileRejection | None:
        return self._rejections[-1] if self._rejections else None

    def submit(
        self,
        estimate: CalibrationEstimate,
        *,
        validated: bool | None = None,
        validation_reasons: Sequence[str] = (),
        validated_by: Sequence[str] = (),
        applicability: ApplicabilityScope | None = None,
        method_id: str = "",
        extrinsic: tuple[float, float, float] | None = None,
        extrinsic_accuracy_m: float | None = None,
        extrinsic_source: str = "estimated",
        quality: Mapping[str, float] | None = None,
        frame_refs: Sequence[str] = (),
        estimated_at: float = 0.0,
        valid_until: float | None = None,
    ) -> CalibrationProfile:
        """추정 1건을 계보에 넣고, 통과했을 때만 활성 프로파일로 승격한다.

        `validated` 를 주지 않으면 추정 스스로의 `stable` 만 본다 — 외부 검증기를
        붙이지 않은 옛 호출 경로를 그대로 유지하기 위한 것이고, 검증기를 붙인
        경로에서는 두 조건을 **모두** 만족해야 승격된다. 통과하지 못하면 이전 활성
        프로파일은 손대지 않고 `rejections` 에 사유와 유지된 버전이 남는다.
        """
        passed = bool(estimate.stable) and (validated is None or bool(validated))
        created_at = datetime.now(timezone.utc).isoformat()
        profile = CalibrationProfile(
            version=self._next_version,
            camera_matrix=estimate.camera_matrix,
            dist_coeffs=estimate.dist_coeffs,
            reprojection_error_rms=estimate.reprojection_error_rms,
            created_at=created_at,
            valid=passed,
            camera_id=self._camera_id or getattr(estimate, "camera_id", "") or "",
            method_id=method_id or getattr(estimate, "method_id", "") or "",
            applicability=applicability,
            extrinsic=extrinsic,
            extrinsic_accuracy_m=extrinsic_accuracy_m,
            extrinsic_source=extrinsic_source,
            validated_by=tuple(validated_by),
            quality=dict(quality or {}),
            frame_refs=tuple(frame_refs),
            estimated_at=estimated_at,
            valid_until=valid_until,
        )
        self._next_version += 1
        self._history.append(profile)
        if passed:
            self._active = profile
            return profile

        reasons = tuple(validation_reasons) or (
            ("unstable_estimate",) if not estimate.stable else ("validation_failed",))
        self._rejections.append(ProfileRejection(
            version=profile.version, created_at=created_at, reasons=reasons,
            kept_version=self._active.version if self._active else None,
            method_id=profile.method_id,
            reprojection_error_rms=estimate.reprojection_error_rms,
        ))
        return profile
