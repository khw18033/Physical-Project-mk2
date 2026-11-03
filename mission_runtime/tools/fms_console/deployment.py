"""비개발자가 웹에서 하는 네 가지 — 들이기 · 보정 · 학습 · 모델 교체.

implements: AI-B-09 (신규 확장 등록), AI-E-02 (보정 lifecycle),
            AI-L-09 (스트림 기반 지속학습), AI-L-10 (조건 기반 모델 배정)
관련: AI-C-18, AI-L-01/02/05/06/07/08, AI-B-01, AI-C-05, AI-C-16, AI-C-19
tests: tests/test_fms_deployment.py

이 모듈은 **판정을 새로 만들지 않는다.** 네 가지 행위의 판정은 이미 각자 주인이
있다 — 조인 선언은 `registry/onboarding.py`, 보정 승격은
`edge/calibration_profile.py`, 학습과 검증은 `continual/`, 배정과 단계적 적용은
`runtime/model_assignment.py` + `runtime/mlops_pipeline.py` 다. 여기 있는 것은
웹 폼의 입력을 그 계약의 자료형으로 옮기고 결과를 그대로 되돌려 주는 책상이다.
같은 판정을 여기서 다시 하면 화면과 런타임이 서로 다른 답을 말한다(FMS 콘솔 규칙).

왜 네 가지가 한 모듈인가
------------------------
넷은 **하나의 순서**다. 장치를 들이면 보정이 할 일로 남고(조인의 `next_steps`),
보정과 검수가 쌓이면 학습 후보가 되고, 학습 결과는 검증·승인을 지나야 기기에
적용된다. 쪼개 놓으면 그 순서가 화면에서만 존재하고 코드에는 없게 된다.

정직하게 비는 자리
------------------
- 선언된 카메라 정보는 **관측이 아니다**(AI-S-08). 그래서 렌즈 제원으로 계산한
  fx 는 활성 보정 프로파일이 되지 못하고 `declared` 로만 남는다. 측정이 없는데
  프로파일로 올리면 틀린 내부 파라미터가 조용히 투영에 들어간다.
- 보정판을 찾지 못한 것은 오류가 아니라 **아직 측정하지 않은 것**이다. 그때
  활성 프로파일은 손대지 않고(AI-E-02 의 last-known-good), 무엇이 없어서 못
  쟀는지를 사유로 남긴다.
- 학습은 사람이 확인한 후보만 쓴다(AI-L-02). 자동 추론 후보가 몇 건이든 그
  수는 "학습에 쓸 수 있는 수"가 아니다.
- 모델 교체는 계보가 승인(APPROVED)에 닿은 뒤에만 일어난다. 관문을 건너뛰는
  빠른 길을 두면 그 관문은 선택 사항이 된다.
"""

from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from mission_runtime.continual.lineage import LearningLineage, LearningState
from mission_runtime.continual.parameter_evaluation import (
    EvaluationGate,
    ParameterEvaluator,
    GateResult,
)
from mission_runtime.continual.stream_learning import (
    CandidateStore,
    ContinualLearner,
    InputConditions,
    ParameterSet,
    PrototypeLearningProvider,
    StreamSample,
    TrainingOutcome,
)
from mission_runtime.edge.calibration import CalibrationEstimate, CameraCalibrator
from mission_runtime.edge.calibration_profile import (
    ApplicabilityScope,
    CalibrationProfile,
    CalibrationProfileStore,
)
from mission_runtime.registry.onboarding import (
    JoinOutcome,
    JoinStep,
    NodeJoinManifest,
    NodeOnboarding,
    manifest_from_dict,
    node_config_entry,
)
from mission_runtime.runtime.clusters import ClusterBinding, PlacementRequest
from mission_runtime.runtime.model_assignment import (
    Assignment,
    DeviceProfile,
    MissionRequirement,
    ModelAssigner,
    ModelVersion,
    PinnedVersion,
)
from mission_runtime.runtime.mlops_pipeline import (
    Deployable,
    DeploymentStatus,
    MlopsPipeline,
    PromotionScope,
    next_scope,
)

# --- 보정 ---------------------------------------------------------------------

#: 보정 결과의 종류. 통제 어휘이고 화면 문구가 아니다.
CALIB_PROMOTED = "promoted"          # 측정했고 통과했다 — 활성 프로파일이 바뀌었다
CALIB_REJECTED = "rejected"          # 측정했지만 통과하지 못했다 — 이전 버전 유지
CALIB_NOT_MEASURED = "not_measured"  # 아직 재지 않았다 — 선언만 들어왔다

#: 재지 못한 사유.
NEED_BOARD_DECLARATION = "board_not_declared"
NEED_FRAMES = "no_calibration_frames"
NEED_BOARD_IN_FRAMES = "board_not_found_in_frames"     # + ":k/n"
NEED_MORE_VIEWS = "too_few_views"                      # + ":k/need"
NEED_OPENCV = "opencv_unavailable"

#: 승격을 막은 사유.
REJECT_RMS_TOO_HIGH = "reprojection_rms_above_limit"
REJECT_FX_DISAGREES = "fx_disagrees_with_declared_lens"
REJECT_SIZE_DISAGREES = "frames_disagree_with_declared_image_size"

#: 보정에 필요한 최소 시점 수. 한 장으로 구한 내부 파라미터는 조건이 퇴화한다.
MIN_CALIBRATION_VIEWS = 3

#: 측정 fx 와 선언된 렌즈 제원이 이만큼 어긋나면 승격시키지 않는다. 둘 중 하나가
#: 틀렸다는 뜻이고, 어느 쪽인지는 이 모듈이 알 수 없다 — 사람이 봐야 한다.
FX_DISAGREEMENT_LIMIT = 0.25

#: 보정판 캡처가 놓이는 **규약 경로**. 통합하는 쪽은 이 경로만 알면 된다.
CALIBRATION_ASSET_TEMPLATE = "{root}/calibration/{device_id}/"

_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp")

#: 파일 이름 규약. 미디어 경로와 같은 이유로 좁게 잡는다.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class CameraInfo:
    """사람이 적어 넣은 카메라 선언. **관측이 아니라 사전정보다**(AI-S-08).

    적지 않은 칸은 비어 있는 것이고 0 이 아니다 — 초점거리를 모르면 비교할 기준이
    없는 것이고, 그것을 0 으로 채우면 모든 측정이 "제원과 어긋난다"가 된다.
    """

    device_id: str
    width_px: int
    height_px: int
    #: 렌즈 초점거리(mm)와 센서 가로(mm). 둘이 함께 있어야 fx 를 유도할 수 있다.
    focal_mm: float | None = None
    sensor_width_mm: float | None = None
    #: 또는 수평 화각(deg). 제원표에 둘 중 하나만 있는 경우가 많다.
    hfov_deg: float | None = None
    zoom_token: str = ""
    mount_token: str = ""
    #: 보정판의 **내부 코너 수**와 한 칸 크기(mm). 없으면 측정을 시도하지 않는다.
    board_cols: int | None = None
    board_rows: int | None = None
    square_mm: float | None = None
    declared_by: str = ""
    reason: str = ""

    @property
    def image_size(self) -> tuple[int, int]:
        return (int(self.width_px), int(self.height_px))

    @property
    def board(self) -> tuple[int, int] | None:
        if not self.board_cols or not self.board_rows or not self.square_mm:
            return None
        return (int(self.board_cols), int(self.board_rows))

    def derived_fx(self) -> float | None:
        """제원에서 유도한 fx(px). 유도할 재료가 없으면 None 이고 0 이 아니다."""
        if self.focal_mm and self.sensor_width_mm:
            return self.width_px * float(self.focal_mm) / float(self.sensor_width_mm)
        if self.hfov_deg and 0.0 < float(self.hfov_deg) < 180.0:
            half = math.radians(float(self.hfov_deg) / 2.0)
            return (self.width_px / 2.0) / math.tan(half)
        return None

    def scope(self) -> ApplicabilityScope:
        return ApplicabilityScope(camera_id=self.device_id, image_size=self.image_size,
                                  zoom_token=self.zoom_token, mount_token=self.mount_token)

    def as_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "image_size": list(self.image_size),
            "focal_mm": self.focal_mm,
            "sensor_width_mm": self.sensor_width_mm,
            "hfov_deg": self.hfov_deg,
            "zoom_token": self.zoom_token,
            "mount_token": self.mount_token,
            "board": None if self.board is None else list(self.board),
            "square_mm": self.square_mm,
            # 유도한 값과 적어 넣은 값을 섞지 않는다 — 유도값은 측정값도 아니다.
            "derived_fx_px": self.derived_fx(),
            "declared_by": self.declared_by,
            "reason": self.reason,
        }


def camera_info_from_dict(raw: Mapping[str, Any]) -> CameraInfo:
    def _num(key: str) -> float | None:
        value = raw.get(key)
        if value is None or value == "":
            return None
        return float(value)

    def _int(key: str) -> int | None:
        value = _num(key)
        return None if value is None else int(value)

    width, height = _int("width_px"), _int("height_px")
    if not width or not height or width <= 0 or height <= 0:
        raise ValueError("image_size_required")
    return CameraInfo(
        device_id=str(raw.get("device_id") or ""),
        width_px=width, height_px=height,
        focal_mm=_num("focal_mm"), sensor_width_mm=_num("sensor_width_mm"),
        hfov_deg=_num("hfov_deg"),
        zoom_token=str(raw.get("zoom_token") or ""),
        mount_token=str(raw.get("mount_token") or ""),
        board_cols=_int("board_cols"), board_rows=_int("board_rows"),
        square_mm=_num("square_mm"),
        declared_by=str(raw.get("actor") or ""), reason=str(raw.get("reason") or ""),
    )


@dataclass(frozen=True)
class CalibrationRun:
    """보정 시도 1건의 결과. 세 가지 자세를 구분한다(승격·거절·미측정)."""

    device_id: str
    verdict: str
    #: 재지 못한·통과하지 못한 사유. 빈 것이 정상일 수 있다(승격한 경우).
    reasons: tuple[str, ...] = ()
    profile: CalibrationProfile | None = None
    #: 승격하지 못했을 때 그대로 유지된 버전. None 이면 아직 정상 프로파일이 없다.
    kept_version: int | None = None
    frames_offered: int = 0
    frames_used: int = 0
    measured_fx_px: float | None = None
    declared_fx_px: float | None = None
    reprojection_error_rms: float | None = None

    def as_dict(self) -> dict:
        body: dict[str, Any] = {
            "device_id": self.device_id,
            "verdict": self.verdict,
            "reasons": list(self.reasons),
            "kept_version": self.kept_version,
            "frames_offered": self.frames_offered,
            "frames_used": self.frames_used,
            "measured_fx_px": self.measured_fx_px,
            "declared_fx_px": self.declared_fx_px,
            "reprojection_error_rms": self.reprojection_error_rms,
        }
        if self.profile is not None:
            body["profile"] = _profile_dict(self.profile)
        return body


def _profile_dict(profile: CalibrationProfile) -> dict:
    matrix = profile.camera_matrix
    rows = [[float(v) for v in row] for row in matrix] if matrix is not None else []
    return {
        "version": profile.version,
        "valid": profile.valid,
        "created_at": profile.created_at,
        "method_id": profile.method_id,
        "reprojection_error_rms": profile.reprojection_error_rms,
        "camera_matrix": rows,
        "applicability": (None if profile.applicability is None
                          else profile.applicability.as_dict()),
        "validated_by": list(profile.validated_by),
        "quality": dict(profile.quality),
        "frame_refs": list(profile.frame_refs),
        # 외부 파라미터는 이 경로에서 나오지 않는다 — 자리는 실측·관측이 정한다.
        "has_extrinsic": profile.has_extrinsic,
    }


@dataclass
class CalibrationDesk:
    """카메라별 보정 계보. 선언과 측정을 **다른 칸에** 둔다.

    `frames_root` 가 없는 설치에서도 돌아간다 — 그때는 선언만 받고 측정을
    `not_measured` 로 남긴다(AI-C-05: 자산 없음은 오류가 아니다).
    """

    frames_root: Path | None = None
    max_acceptable_rms: float = 1.0
    _declared: dict[str, CameraInfo] = field(default_factory=dict, init=False)
    _stores: dict[str, CalibrationProfileStore] = field(default_factory=dict, init=False)
    _runs: dict[str, list[CalibrationRun]] = field(default_factory=dict, init=False)

    # -- 선언 -------------------------------------------------------------

    def declare(self, info: CameraInfo) -> CameraInfo:
        """카메라 정보를 받는다. 이것만으로는 어떤 프로파일도 활성이 되지 않는다."""
        if not info.device_id:
            raise ValueError("device_id_required")
        self._declared[info.device_id] = info
        return info

    def declared(self, device_id: str) -> CameraInfo | None:
        return self._declared.get(device_id)

    def store(self, device_id: str) -> CalibrationProfileStore:
        if device_id not in self._stores:
            self._stores[device_id] = CalibrationProfileStore(camera_id=device_id)
        return self._stores[device_id]

    def runs(self, device_id: str) -> tuple[CalibrationRun, ...]:
        return tuple(self._runs.get(device_id, ()))

    def frame_dir(self, device_id: str) -> Path | None:
        if self.frames_root is None or not _SAFE_NAME.match(device_id or ""):
            return None
        return self.frames_root / device_id

    def frame_files(self, device_id: str) -> tuple[Path, ...]:
        directory = self.frame_dir(device_id)
        if directory is None or not directory.is_dir():
            return ()
        return tuple(sorted(
            p for p in directory.iterdir()
            if p.is_file() and p.suffix.lower() in _IMAGE_SUFFIXES))

    # -- 측정 -------------------------------------------------------------

    def calibrate(self, device_id: str) -> CalibrationRun:
        """선언된 조건으로 실제 측정을 시도한다. 실패는 값으로 돌아온다."""
        info = self._declared.get(device_id)
        if info is None:
            raise KeyError(device_id)
        run = self._calibrate(info)
        self._runs.setdefault(device_id, []).append(run)
        return run

    def _calibrate(self, info: CameraInfo) -> CalibrationRun:
        store = self.store(info.device_id)
        kept = store.active.version if store.active else None
        declared_fx = info.derived_fx()
        board = info.board
        frames = self.frame_files(info.device_id)

        if board is None:
            return CalibrationRun(info.device_id, CALIB_NOT_MEASURED,
                                  (NEED_BOARD_DECLARATION,), kept_version=kept,
                                  frames_offered=len(frames), declared_fx_px=declared_fx)
        if not frames:
            return CalibrationRun(info.device_id, CALIB_NOT_MEASURED, (NEED_FRAMES,),
                                  kept_version=kept, declared_fx_px=declared_fx)

        try:
            import cv2  # noqa: PLC0415
            import numpy as np  # noqa: PLC0415
        except Exception:
            # 보정 제공자가 없는 설치에서는 보정만 비활성이고 나머지는 그대로 돈다.
            return CalibrationRun(info.device_id, CALIB_NOT_MEASURED, (NEED_OPENCV,),
                                  kept_version=kept, frames_offered=len(frames),
                                  declared_fx_px=declared_fx)

        cols, rows = board
        grid = np.zeros((cols * rows, 3), dtype=np.float32)
        grid[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
        grid *= float(info.square_mm) / 1000.0        # m 단위로 — 선언된 칸 크기다

        object_points: list[Any] = []
        image_points: list[Any] = []
        used: list[str] = []
        sizes: set[tuple[int, int]] = set()
        for path in frames:
            image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if image is None:
                continue
            sizes.add((int(image.shape[1]), int(image.shape[0])))
            found, corners = cv2.findChessboardCorners(image, (cols, rows), None)
            if not found:
                continue
            refined = cv2.cornerSubPix(
                image, corners, (11, 11), (-1, -1),
                (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001))
            object_points.append(grid.copy())
            image_points.append(refined)
            used.append(path.name)

        if len(used) < MIN_CALIBRATION_VIEWS:
            reason = (f"{NEED_BOARD_IN_FRAMES}:{len(used)}/{len(frames)}" if not used
                      else f"{NEED_MORE_VIEWS}:{len(used)}/{MIN_CALIBRATION_VIEWS}")
            return CalibrationRun(info.device_id, CALIB_NOT_MEASURED, (reason,),
                                  kept_version=kept, frames_offered=len(frames),
                                  frames_used=len(used), declared_fx_px=declared_fx)

        # 실제로 읽은 영상 크기로 푼다. 선언과 어긋나면 그 사실이 거절 사유다 —
        # 선언을 믿고 풀면 fx·cx 가 조용히 틀린 채 통과한다.
        measured_size = next(iter(sizes))
        calibrator = CameraCalibrator(max_acceptable_rms=self.max_acceptable_rms)
        estimate = calibrator.estimate(object_points, image_points, measured_size)
        measured_fx = float(estimate.camera_matrix[0][0])

        reasons: list[str] = []
        checks: list[str] = ["reprojection_rms"]
        if not estimate.stable:
            reasons.append(REJECT_RMS_TOO_HIGH)
        if measured_size != info.image_size:
            reasons.append(REJECT_SIZE_DISAGREES)
        if declared_fx is not None:
            checks.append("declared_lens_agreement")
            if abs(measured_fx - declared_fx) / declared_fx > FX_DISAGREEMENT_LIMIT:
                reasons.append(REJECT_FX_DISAGREES)

        quality: dict[str, float] = {
            "frames_used": float(len(used)),
            "frames_offered": float(len(frames)),
            "measured_fx_px": measured_fx,
        }
        if declared_fx is not None:
            quality["declared_fx_px"] = declared_fx

        profile = store.submit(
            estimate,
            validated=not reasons,
            validation_reasons=tuple(reasons),
            validated_by=tuple(checks),
            applicability=ApplicabilityScope(
                camera_id=info.device_id, image_size=measured_size,
                zoom_token=info.zoom_token, mount_token=info.mount_token),
            method_id="checkerboard_cv2",
            quality=quality,
            frame_refs=tuple(f"{info.device_id}/{name}" for name in used),
        )
        return CalibrationRun(
            info.device_id,
            CALIB_REJECTED if reasons else CALIB_PROMOTED,
            tuple(reasons), profile=profile,
            kept_version=(store.active.version if store.active else None),
            frames_offered=len(frames), frames_used=len(used),
            measured_fx_px=measured_fx, declared_fx_px=declared_fx,
            reprojection_error_rms=estimate.reprojection_error_rms,
        )

    def view(self, device_id: str) -> dict:
        """그 카메라의 지금 상태. 선언·활성·이력·거절을 **갈라서** 낸다."""
        store = self._stores.get(device_id)
        info = self._declared.get(device_id)
        active = store.active if store else None
        return {
            "device_id": device_id,
            "declared": None if info is None else info.as_dict(),
            "active": None if active is None else _profile_dict(active),
            "history": [_profile_dict(p) for p in (store.history if store else ())],
            "rejections": [
                {"version": r.version, "created_at": r.created_at,
                 "reasons": list(r.reasons), "kept_version": r.kept_version,
                 "reprojection_error_rms": r.reprojection_error_rms}
                for r in (store.rejections if store else ())
            ],
            "runs": [r.as_dict() for r in self.runs(device_id)],
            # 실제로 뒤지는 자리를 그대로 적는다. 규약 템플릿을 여기서 다시 조립하면
            # `frames_root` 가 이미 그 규약을 품고 있을 때 경로가 한 칸 더 깊어지고,
            # 화면을 보고 캡처를 넣은 사람은 **없는 자리**에 넣게 된다.
            "frame_dir": (None if self.frame_dir(device_id) is None
                          else f"{self.frame_dir(device_id)}/"),
            "frames_offered": len(self.frame_files(device_id)),
        }


# --- 들이기 -------------------------------------------------------------------


@dataclass
class JoinDesk:
    """조인 선언을 받는 책상. 가용성은 판정하지 않는다(절대 준수 원칙 #15)."""

    onboarding: NodeOnboarding = field(default_factory=NodeOnboarding)

    def submit(self, raw: Mapping[str, Any], *,
               announced_actions: Iterable[str] = (),
               replace: bool = False) -> tuple[JoinOutcome, NodeJoinManifest]:
        manifest = manifest_from_dict(raw)
        outcome = self.onboarding.submit(manifest, announced_actions=announced_actions,
                                         replace=replace)
        return outcome, manifest

    def view(self) -> dict:
        """지금 들어온 선언과 남은 할 일. 화면의 '해야 할 것'이 이것이다."""
        joined = []
        for device_id in self.onboarding.joined():
            manifest = self.onboarding.manifest(device_id)
            outcome = self.onboarding.outcome(device_id)
            joined.append({
                "manifest": _manifest_dict(manifest),
                "outcome": outcome.as_dict() if outcome else None,
                "config_entry": node_config_entry(manifest),
            })
        return {
            "joined": joined,
            "steps": [step.value for step in JoinStep],
            "pending": {step.value: list(self.onboarding.pending(step))
                        for step in JoinStep},
            # 거절도 보인다 — 안 보이면 "올렸는데 아무 일도 없었다" 가 된다.
            "refused": [o.as_dict() for o in self.onboarding.refused()],
        }

    def resolve(self, device_id: str, step: str) -> JoinOutcome | None:
        return self.onboarding.resolve_step(device_id, JoinStep(step))


def _manifest_dict(manifest: NodeJoinManifest | None) -> dict | None:
    if manifest is None:
        return None
    return {
        "device_id": manifest.device_id,
        "role": manifest.role,
        "node_tags": sorted(manifest.node_tags),
        "budget": (None if manifest.budget is None
                   else {"compute_units": manifest.budget.compute_units,
                         "memory_mb": manifest.budget.memory_mb}),
        "appearance_assets": list(manifest.appearance_assets),
        "appearance_class": manifest.appearance_class,
        "has_camera": manifest.has_camera,
        "calibration_profile_version": manifest.calibration_profile_version,
        "overlay_peer": manifest.overlay_peer,
        "declared_actions": list(manifest.declared_actions),
        "contract_version": manifest.contract_version,
    }


# --- 학습 ---------------------------------------------------------------------

#: 학습이 아무것도 내지 못한 사유.
NO_CONFIRMED = "no_confirmed_samples"
NO_TRAINING_SPLIT = "too_few_confirmed_to_hold_out"   # + ":k/need"
NO_HELD_OUT_SET = "no_held_out_set"

#: 검증을 미측정으로 두는 사유는 `continual/parameter_evaluation.py` 가 소유한다.
#: 여기서 새 사유를 만들지 않는다.

#: 후보 파라미터가 있을 수 있는 자리. 계보의 상태를 그대로 읽으므로 새 어휘가 아니다.
TRAINED = "trained"


@dataclass
class TrainedCandidate:
    """학습 1회의 산출. 어느 표본으로 만들었고 무엇을 남겼는지 함께 든다."""

    parameters: ParameterSet
    group_key: tuple
    conditions: InputConditions
    lineage: LearningLineage
    used_sample_ids: tuple[str, ...]
    held_out_sample_ids: tuple[str, ...]
    #: 보류 표본이 없어 **검증에서 재지 못한** 라벨. 승인 화면의 "미검증 범위"다.
    unmeasured_labels: tuple[str, ...] = ()
    report: Any | None = None
    #: 실제로 적용한 통과 기준. 기본값과 다를 수 있으므로 결과에 함께 싣는다.
    gate_used: EvaluationGate | None = None
    produced_by: str = ""

    @property
    def version(self) -> str:
        return self.parameters.version

    def as_dict(self) -> dict:
        report = self.report
        return {
            "version": self.version,
            "labels": list(self.parameters.labels()),
            "base_version": self.parameters.base_version,
            "produced_by": self.produced_by,
            "device_id": self.conditions.device_id,
            "used_sample_ids": list(self.used_sample_ids),
            "held_out_sample_ids": list(self.held_out_sample_ids),
            "unmeasured_labels": list(self.unmeasured_labels),
            "learning_lineage_id": self.lineage.lineage_id,
            "learning_state": self.lineage.state.value,
            "parameters": {
                label: {k: v for k, v in body.items() if k != "prototype"}
                for label, body in self.parameters.parameters.items()
            },
            "gate_used": None if self.gate_used is None else {
                "min_new_accuracy": self.gate_used.min_new_accuracy,
                "max_regression": self.gate_used.max_regression,
                "forbid_label_loss": self.gate_used.forbid_label_loss,
            },
            "evaluation": None if report is None else {
                "result": report.result.value,
                "reason": report.reason,
                "new": {"correct": report.new.correct, "total": report.new.total},
                "retained": {"correct": report.retained.correct,
                             "total": report.retained.total},
                "baseline": {"correct": report.baseline.correct,
                             "total": report.baseline.total},
                "regression": report.regression,
                "lost_labels": list(report.lost_labels),
            },
        }


class SampleLineageView(Mapping):
    """표본 id → 그 표본의 계보. 트윈의 원장을 **그때그때** 읽는다.

    사전을 한 번 복사해 두지 않는 이유: 운영자가 방금 올린 정답의 계보가 학습
    화면에서 빠지게 된다. 후보 수가 많지 않은 구간이라 매번 훑는 비용이 그보다 싸다.
    """

    def __init__(self, twin: Any) -> None:
        self._twin = twin

    def _index(self) -> dict[str, str]:
        ledger = self._twin.learning_candidates()
        return {c.learning_candidate_id: c.learning_lineage_id
                for c in (*ledger.human_confirmed, *ledger.auto_inference)}

    def __getitem__(self, key: str) -> LearningLineage:
        return self._twin.lineage(self._index()[key])

    def __iter__(self):
        return iter(self._index())

    def __len__(self) -> int:
        return len(self._index())


@dataclass
class TrainingDesk:
    """사람이 확인한 후보로 가중치를 갱신하고, 관문을 하나씩 지난다.

    후보 보관소를 **소유하지 않는다** — 트윈의 보관소를 그대로 읽는다. 복사해 오면
    운영자가 방금 고친 것이 학습 화면에 안 보이는 순간이 생긴다.

    특징 벡터의 한계를 적어 둔다. 정답 검수에서 온 후보의 `feature` 는 **상자
    좌표**다(트윈이 그 시점에 가진 것이 그것뿐이다). 상자 좌표끼리의 코사인
    유사도는 거의 1 에 몰려서 기본 제공자의 분위 임계가 아주 좁은 구간에서
    결정되고, 그래서 보류 집합 정확도가 낮게 나오는 것이 정상이다 — 배관의 고장이
    아니라 **그 특징 공간의 성질**이다. 더 나은 신호(외형 임베딩)를 쓰려면 바꿀
    자리는 `LearningProvider` 경계와 후보를 올릴 때의 `feature` 이고, 이 모듈은
    그대로 둔다(AI-B-08).
    """

    store: CandidateStore
    #: 표본별 계보. 트윈이 후보를 올릴 때 연 그 계보이고, 여기서 다시 만들지 않는다.
    sample_lineages: Mapping[str, LearningLineage] = field(default_factory=dict)
    provider: Any = field(default_factory=PrototypeLearningProvider)
    evaluator: ParameterEvaluator = field(default_factory=ParameterEvaluator)
    gate: EvaluationGate = field(default_factory=EvaluationGate)
    _bases: dict[tuple, ParameterSet] = field(default_factory=dict, init=False)
    _candidates: dict[str, TrainedCandidate] = field(default_factory=dict, init=False)
    _counter: int = field(default=0, init=False)

    @property
    def min_samples(self) -> int:
        return int(getattr(self.provider, "_min_samples", 3))

    # -- 조회 -------------------------------------------------------------

    def groups(self) -> list[dict]:
        """조건 묶음별 후보 수. **확인된 수와 전체 수를 갈라서** 낸다(AI-L-02)."""
        rows = []
        for conditions in self.store.groups():
            batch = self.store.batch_for(conditions)
            confirmed = batch.confirmed()
            rows.append({
                "group_key": _group_token(conditions),
                "device_id": conditions.device_id,
                "camera_id": conditions.camera_id,
                "resolution": (None if conditions.resolution is None
                               else list(conditions.resolution)),
                "accelerator_id": conditions.accelerator_id,
                "extra": {k: v for k, v in conditions.extra},
                "total": len(batch.samples),
                "confirmed": len(confirmed),
                "labels": sorted({s.label for s in confirmed}),
                "base_version": self._bases.get(conditions.group_key).version
                if conditions.group_key in self._bases else None,
                # 학습을 누를 수 있는가를 서버가 말한다 — 화면이 최소 표본 수를
                # 따로 알고 있으면 둘이 어긋난다.
                "trainable": len(confirmed) >= self.min_samples,
                "min_samples": self.min_samples,
            })
        return sorted(rows, key=lambda r: r["group_key"])

    def candidates(self) -> list[dict]:
        return [c.as_dict() for c in self._candidates.values()]

    def candidate(self, version: str) -> TrainedCandidate:
        return self._candidates[version]

    # -- 학습 -------------------------------------------------------------

    def train(self, group_token: str, *, actor: str, reason: str) -> dict:
        """그 묶음의 확인된 후보로 갱신한다. 실패는 사유로 돌아온다."""
        if not actor or not reason:
            raise ValueError("actor_and_reason_required")
        conditions = self._conditions(group_token)
        batch = self.store.batch_for(conditions)
        confirmed = batch.confirmed()
        if not confirmed:
            return {"produced": False, "reason": NO_CONFIRMED}

        train_part, held_out = _split_for_holdout(confirmed, self.min_samples)
        if not train_part:
            return {"produced": False,
                    "reason": f"{NO_TRAINING_SPLIT}:{len(confirmed)}/{self.min_samples}"}

        from mission_runtime.continual.stream_learning import CandidateBatch  # noqa: PLC0415

        base = self._bases.get(conditions.group_key)
        try:
            outcome: TrainingOutcome = self.provider.train(
                CandidateBatch(conditions=conditions, samples=tuple(train_part)),
                base=base)
        except Exception as error:      # 학습 실패가 운영을 멈추지 않는다(AI-L-09)
            return {"produced": False, "reason": f"provider_failed:{type(error).__name__}"}
        if outcome.parameters is None:
            return {"produced": False, "reason": outcome.reason}

        # 제공자는 라벨별 최소 표본 수를 못 채운 라벨을 버린다 — 학습에 **실제로**
        # 들어간 표본만 계보에 적는다. 넘긴 수를 적으면 계보가 거짓을 말한다.
        consumed = set(outcome.used_sample_ids)
        used = ([s for s in train_part if s.sample_id in consumed] if consumed
                else list(train_part))
        lineage = self._open_lineage(outcome.parameters, used, actor=actor, reason=reason)
        learned = set(outcome.parameters.labels())
        candidate = TrainedCandidate(
            parameters=outcome.parameters, group_key=conditions.group_key,
            conditions=conditions, lineage=lineage,
            used_sample_ids=tuple(s.sample_id for s in used),
            # 배우지 않은 라벨의 보류 표본은 검증 집합이 아니다 — 그것까지 섞으면
            # 쪼갠 방식의 결과를 모델의 성능으로 읽게 된다.
            held_out_sample_ids=tuple(s.sample_id for s in held_out
                                      if s.label in learned),
            unmeasured_labels=tuple(sorted(
                {s.label for s in train_part} - {s.label for s in held_out
                                                 if s.label in learned})),
            produced_by=str(getattr(self.provider, "name", "") or ""),
        )
        self._candidates[candidate.version] = candidate
        return {"produced": True, "candidate": candidate.as_dict()}

    def _open_lineage(self, parameters: ParameterSet, used: Sequence[StreamSample],
                      *, actor: str, reason: str) -> LearningLineage:
        """파라미터 버전의 계보를 열고 **실제로 수행한** 세 관문만 지난다.

        표본 계보와 따로 두는 이유: 한 파라미터는 여러 표본에서 나오고, 배포를
        가로막는 계보는 하나여야 한다. 양쪽은 `used_sample_ids` 로 이어진다.
        """
        self._counter += 1
        evidence = parameters.version
        lineage = LearningLineage(f"param-{self._counter}", actor=actor,
                                  evidence_ref=evidence, reason=reason)
        # AI-L-02 격리: 확인된 표본만 들어갔다는 사실.
        lineage.advance(actor=actor, evidence_ref=evidence,
                        reason=f"confirmed_only:{len(used)}")
        # AI-L-03 사람 확인: 그 확인이 어느 계보에서 왔는가.
        sample_refs = ",".join(
            self.sample_lineages[s.sample_id].lineage_id
            for s in used if s.sample_id in self.sample_lineages) or "no_sample_lineage"
        lineage.advance(actor=actor, evidence_ref=sample_refs, reason="human_confirmed")
        # AI-L-04 전략 선택: 어느 제공자가 냈는가.
        lineage.advance(actor=actor, evidence_ref=evidence,
                        reason=f"provider:{getattr(self.provider, 'name', 'unknown')}")
        for sample in used:
            consumed = self.sample_lineages.get(sample.sample_id)
            if consumed is not None and consumed.state is LearningState.CANDIDATE:
                consumed.advance(actor=actor, evidence_ref=evidence,
                                 reason=f"consumed_by:{lineage.lineage_id}")
        return lineage

    # -- 검증 (AI-L-05) ---------------------------------------------------

    def validate(self, version: str, *, actor: str, reason: str,
                 gate: EvaluationGate | None = None) -> dict:
        """보류한 표본에서 재고 게이트를 적용한다. 미측정은 통과가 아니다.

        `gate` 를 받는 이유: AI-L-05 는 통과 기준을 고정하라고 하지 않고 "동일 검증
        조건에서 비교해 선정·갱신" 하라고 한다. 그래서 기준은 데이터이고, 대신
        **무슨 기준으로 통과했는지가 계보에 남는다** — 남지 않으면 기준을 낮춰
        통과시킨 것과 기준을 넘은 것이 뒤에서 구분되지 않는다.
        """
        if not actor or not reason:
            raise ValueError("actor_and_reason_required")
        candidate = self._candidates[version]
        if candidate.lineage.state is not LearningState.STRATEGY_SELECTED:
            return {"advanced": False, "reason": f"state_is:{candidate.lineage.state.value}"}
        applied = gate or self.gate
        held_out = self._samples(candidate.held_out_sample_ids)
        base = self._bases.get(candidate.group_key)
        retained = self._samples(
            tuple(s.sample_id for s in self.store.batch_for(candidate.conditions).confirmed()
                  if s.sample_id in set(candidate.used_sample_ids))) if base else ()
        report = self.evaluator.evaluate(
            candidate.parameters, new_samples=held_out,
            retained_samples=retained, base=base, gate=applied)
        candidate.report = report
        candidate.gate_used = applied
        if report.result is not GateResult.PASS:
            # 미측정도 FAIL 도 승격시키지 않는다. 계보는 그 자리에 머문다.
            return {"advanced": False, "result": report.result.value,
                    "reason": report.reason or (NO_HELD_OUT_SET if not held_out else None),
                    "candidate": candidate.as_dict()}
        candidate.lineage.advance(
            actor=actor, evidence_ref=version,
            reason=f"{reason} [gate min_new={applied.min_new_accuracy},"
                   f"max_regression={applied.max_regression},"
                   f"forbid_label_loss={applied.forbid_label_loss}]")
        return {"advanced": True, "result": report.result.value,
                "candidate": candidate.as_dict()}

    # -- 승인 (AI-L-06) ---------------------------------------------------

    def approval_info(self, version: str) -> dict:
        """관리자가 판단할 재료. 검증을 통과하지 못한 후보는 올리지 않는다."""
        candidate = self._candidates[version]
        report = candidate.report
        return {
            "version": version,
            "eligible": candidate.lineage.state in (LearningState.VALIDATED,
                                                    LearningState.APPROVAL_PENDING),
            "learning_state": candidate.lineage.state.value,
            "why_trained": candidate.lineage.events[0].reason,
            "device_id": candidate.conditions.device_id,
            "sample_counts": {"used": len(candidate.used_sample_ids),
                              "held_out": len(candidate.held_out_sample_ids)},
            "labels": list(candidate.parameters.labels()),
            "base_version": candidate.parameters.base_version,
            "evaluation": candidate.as_dict()["evaluation"],
            "gate_used": candidate.as_dict()["gate_used"],
            # 미검증 범위는 둘로 갈린다 — 재지 못한 라벨과 기준이 알던 것을 잃은 라벨.
            "unmeasured_labels": list(candidate.unmeasured_labels),
            "lost_labels": sorted(set() if report is None else set(report.lost_labels)),
            "lineage": lineage_dict(candidate.lineage),
        }

    def request_approval(self, version: str, *, actor: str, reason: str) -> dict:
        return self._advance(version, LearningState.VALIDATED, actor=actor, reason=reason)

    def approve(self, version: str, *, actor: str, reason: str) -> dict:
        return self._advance(version, LearningState.APPROVAL_PENDING, actor=actor,
                             reason=reason)

    def _advance(self, version: str, expected: LearningState, *,
                 actor: str, reason: str) -> dict:
        if not actor or not reason:
            raise ValueError("actor_and_reason_required")
        candidate = self._candidates[version]
        if candidate.lineage.state is not expected:
            return {"advanced": False,
                    "reason": f"state_is:{candidate.lineage.state.value}"}
        candidate.lineage.advance(actor=actor, evidence_ref=version, reason=reason)
        return {"advanced": True, "candidate": candidate.as_dict(),
                "lineage": lineage_dict(candidate.lineage)}

    # -- 내부 -------------------------------------------------------------

    def _conditions(self, group_token: str) -> InputConditions:
        for conditions in self.store.groups():
            if _group_token(conditions) == group_token:
                return conditions
        raise KeyError(group_token)

    def _samples(self, sample_ids: Sequence[str]) -> tuple[StreamSample, ...]:
        wanted = set(sample_ids)
        found: list[StreamSample] = []
        for conditions in self.store.groups():
            for sample in self.store.batch_for(conditions).samples:
                if sample.sample_id in wanted:
                    found.append(sample)
        return tuple(found)


def _group_token(conditions: InputConditions) -> str:
    """묶음을 가리키는 짧은 이름. 화면이 돌려보낼 수 있어야 한다."""
    extra = ";".join(f"{k}={v}" for k, v in conditions.extra)
    resolution = ("" if conditions.resolution is None
                  else "x".join(str(v) for v in conditions.resolution))
    return "|".join((conditions.device_id, conditions.camera_id or "",
                     resolution, conditions.accelerator_id or "", extra))


def _split_for_holdout(samples: Sequence[StreamSample],
                       min_samples: int) -> tuple[list[StreamSample], list[StreamSample]]:
    """보류 집합을 **라벨별로** 떼어 낸다. 뗄 수 없는 라벨은 떼지 않는다.

    왜 라벨별인가: 기본 제공자는 라벨마다 따로 최소 표본 수를 요구한다. 통째로
    뒷부분을 떼면 어떤 라벨은 학습에서 통째로 빠지고, 그 라벨의 보류 표본은
    "배우지 않은 것을 맞히라"는 문제가 된다 — 검증은 실패하지만 그 실패는 모델이
    아니라 쪼갠 방식의 결과다.

    보류를 못 떼었다는 사실은 숨기지 않는다 — 그 라벨은 검증에서 미측정으로 남고,
    미측정은 통과가 아니다(AI-L-05).
    """
    by_label: dict[str, list[StreamSample]] = {}
    for sample in samples:
        by_label.setdefault(sample.label, []).append(sample)
    train_part: list[StreamSample] = []
    held_out: list[StreamSample] = []
    for label in sorted(by_label):
        rows = by_label[label]
        # 최소 표본 수를 깨지 않는 만큼만 뗀다. 깨면 그 라벨 자체를 못 배운다.
        spare = len(rows) - min_samples
        hold = min(spare, max(1, len(rows) // 3)) if spare > 0 else 0
        train_part += rows[:len(rows) - hold]
        held_out += rows[len(rows) - hold:]
    return train_part, held_out


def lineage_dict(lineage: LearningLineage) -> dict:
    return {
        "learning_lineage_id": lineage.lineage_id,
        "state": lineage.state.value,
        "events": [{"sequence": e.sequence, "requirement_id": e.requirement_id,
                    "state": e.state.value, "actor": e.actor,
                    "evidence_ref": e.evidence_ref, "reason": e.reason}
                   for e in lineage.events],
    }


# --- 모델 교체 ----------------------------------------------------------------

#: 적용 요청이 거절된 사유 중 **이 책상이 내는** 것. 나머지는 파이프라인 어휘다.
REFUSE_UNKNOWN_VERSION = "unknown_model_version"
REFUSE_UNKNOWN_DEVICE = "unknown_device"
REFUSE_NO_APPROVED_CANDIDATE = "no_approved_learning_candidate"

#: 선언된 모델 버전 목록의 자리. **데이터다** — 새 모델은 코드 변경이 아니다.
MODEL_REGISTRY_FILE = "model_versions.example.json"


def model_versions_from_dict(raw: Mapping[str, Any]) -> tuple[ModelVersion, ...]:
    """선언 파일을 배정 후보로. 적지 않은 수치는 **미측정**이고 0 이 아니다."""
    versions: list[ModelVersion] = []
    for entry in raw.get("versions", ()):
        versions.append(ModelVersion(
            model_id=str(entry["model_id"]),
            version=str(entry["version"]),
            capability_kind=str(entry["capability_kind"]),
            verified_hw_tags=frozenset(entry.get("verified_hw_tags") or ()),
            verified_input_conditions=frozenset(
                entry.get("verified_input_conditions") or ()),
            quality=entry.get("quality"),
            latency_ms=entry.get("latency_ms"),
            memory_mb=entry.get("memory_mb"),
        ))
    return tuple(versions)


def _version_dict(version: ModelVersion) -> dict:
    return {
        "reference": version.reference,
        "model_id": version.model_id,
        "version": version.version,
        "capability_kind": version.capability_kind,
        "verified_hw_tags": sorted(version.verified_hw_tags),
        "verified_input_conditions": sorted(version.verified_input_conditions),
        "quality": version.quality,
        "latency_ms": version.latency_ms,
        "memory_mb": version.memory_mb,
        # 미측정을 0 으로 채우지 않았다는 사실 자체를 화면이 읽어야 한다.
        "fully_measured": version.fully_measured,
    }


def _status_dict(status: DeploymentStatus) -> dict:
    return {
        "deployment_id": status.deployment_id,
        "deployable_id": status.deployable_id,
        "phase": status.phase.value,
        "scope": status.scope.value,
        "next_scope": (lambda s: None if s is None else s.value)(next_scope(status.scope)),
        "unit_status": None if status.unit_status is None else status.unit_status.value,
        "device_availability": status.device_availability,
        "mission_outcome": (None if status.mission_outcome is None
                            else status.mission_outcome.value),
        "lineage_state": (None if status.lineage_state is None
                          else status.lineage_state.value),
        "area_id": status.area_id,
        "unit_id": status.unit_id,
        "version_reference": status.version_reference,
        "reason": status.reason,
        "mission_transfers": [
            {"mission_id": t.mission_id, "outcome": t.outcome.value,
             "from_unit": t.from_unit, "to_unit": t.to_unit, "reason": t.reason}
            for t in status.mission_transfers
        ],
    }


@dataclass
class ModelDesk:
    """어느 기기에 어느 모델 버전을 올릴지. 판정은 전부 빌려 온다.

    배정은 `ModelAssigner`(AI-L-10), 단계적 적용과 계보 관문은
    `MlopsPipeline`(AI-L-07) 이 한다. 이 책상은 장치 사실을 `DeviceProfile` 로
    옮기고 결과를 화면 자료형으로 바꾼다.
    """

    pipeline: MlopsPipeline
    #: 장치별 하드웨어 사실. `RobotFacts` 를 그대로 받는다(여기서 다시 재지 않는다).
    device_profiles: Mapping[str, DeviceProfile] = field(default_factory=dict)
    #: 기기별 지금 배포. 장치 하나에 여러 kind 가 올 수 있어 (device, kind) 가 키다.
    _applied: dict[tuple[str, str], str] = field(default_factory=dict, init=False)
    _history: list[dict] = field(default_factory=list, init=False)
    #: 정책을 잠깐 바꿔 끼우는 구간을 감싼다 — 콘솔은 스레드 서버다.
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    # -- 조회 -------------------------------------------------------------

    def versions(self, capability_kind: str | None = None) -> list[dict]:
        return [_version_dict(v) for v in sorted(self.pipeline.assigner.versions,
                                                 key=lambda v: v.reference)
                if capability_kind in (None, v.capability_kind)]

    def devices(self) -> list[dict]:
        rows = []
        for device_id, profile in sorted(self.device_profiles.items()):
            rows.append({
                "device_id": device_id,
                "hw_tags": sorted(profile.hw_tags),
                "input_conditions": sorted(profile.input_conditions),
                "memory_mb": profile.memory_mb,
                "applied": {kind: deployment_id
                            for (dev, kind), deployment_id in self._applied.items()
                            if dev == device_id},
            })
        return rows

    def eligibility(self, device_id: str, requirement: MissionRequirement) -> list[dict]:
        """버전별 적격 여부와 사유. 배정 전에 운영자가 보는 것이 이것이다(AI-C-13)."""
        device = self._device(device_id)
        rows = []
        for version in sorted(self.pipeline.assigner.versions, key=lambda v: v.reference):
            if version.capability_kind != requirement.capability_kind:
                continue
            reason = self.pipeline.assigner.eligibility(version, device, requirement)
            rows.append({**_version_dict(version), "eligible": reason is None,
                         "reason": reason})
        return rows

    def plan(self, device_id: str, requirement: MissionRequirement,
             *, deployable: Deployable, lineage: LearningLineage | None = None) -> dict:
        """커밋하지 않고 결과를 본다. `apply()` 와 **같은 계산**이다."""
        plan = self.pipeline.plan(deployable, self._device(device_id), requirement,
                                  lineage=lineage)
        return {
            "would_place": plan.would_place,
            "refusal_reason": plan.refusal_reason,
            "area_id": plan.area_id,
            "unit_id": plan.unit_id,
            "function_state": plan.function_state.value,
            "assignment": _assignment_dict(plan.assignment),
        }

    # -- 적용 -------------------------------------------------------------

    def apply(self, device_id: str, requirement: MissionRequirement, *,
              deployable: Deployable, lineage: LearningLineage,
              actor: str, reason: str, pinned_reference: str | None = None) -> dict:
        """검증·승인을 지난 후보 하나를 그 기기에 올린다. 검증 모드에서 시작한다."""
        device = self._device(device_id)
        assigner = self.pipeline.assigner
        if pinned_reference:
            version = next((v for v in assigner.versions
                            if v.reference == pinned_reference), None)
            if version is None:
                return {"applied": False, "reason": REFUSE_UNKNOWN_VERSION}
            # 운영자가 고른 버전도 적격 판정을 지난다 — 고른 것이 곧 쓸 수 있는
            # 것은 아니고, 못 쓰는 이유를 적용 **전에** 말해야 한다.
            refusal = assigner.eligibility(version, device, requirement)
            if refusal is not None:
                return {"applied": False, "reason": refusal,
                        "version_reference": pinned_reference}

        with self._lock:
            previous = assigner.policy
            if pinned_reference:
                assigner.policy = PinnedVersion(pinned_reference)
            try:
                status = self.pipeline.submit(deployable, device, requirement,
                                              lineage=lineage, actor=actor,
                                              evidence_ref=reason)
            finally:
                assigner.policy = previous

        body = _status_dict(status)
        placed = status.phase.value == "PLACED"
        if placed:
            self._applied[(device_id, deployable.capability_kind)] = status.deployment_id
        self._history.append({"action": "apply", "device_id": device_id,
                              "actor": actor, "reason": reason, **body})
        return {"applied": placed, "status": body}

    def widen(self, deployment_id: str, *, actor: str, reason: str,
              verification_met: bool = True) -> dict:
        status = self.pipeline.widen(deployment_id, actor=actor, evidence_ref=reason,
                                     verification_met=verification_met)
        body = _status_dict(status)
        self._history.append({"action": "widen", "actor": actor, "reason": reason, **body})
        return {"status": body}

    def rollback(self, deployment_id: str, *, actor: str, reason: str) -> dict:
        status = self.pipeline.rollback(deployment_id, actor=actor,
                                        evidence_ref=reason, reason=reason)
        body = _status_dict(status)
        self._history.append({"action": "rollback", "actor": actor,
                              "reason": reason, **body})
        return {"status": body}

    def deployments(self) -> list[dict]:
        return [_status_dict(self.pipeline.status(d))
                for d in self.pipeline.deployments()]

    def history(self) -> list[dict]:
        return list(self._history)

    def _device(self, device_id: str) -> DeviceProfile:
        profile = self.device_profiles.get(device_id)
        if profile is None:
            raise KeyError(device_id)
        return profile


def _assignment_dict(assignment: Assignment) -> dict:
    return {
        "device_id": assignment.device_id,
        "mission_id": assignment.mission_id,
        "capability_kind": assignment.capability_kind,
        "assigned": (None if assignment.assigned is None
                     else _version_dict(assignment.assigned)),
        "reason": assignment.reason,
        "rejected": [{"version_reference": r.version_reference, "reason": r.reason}
                     for r in assignment.rejected],
    }


def device_profile_from_facts(device_id: str, facts: Any,
                              *, input_conditions: Iterable[str] = ()) -> DeviceProfile:
    """`RobotFacts` → `DeviceProfile`. 자원을 다시 재지 않고 옮기기만 한다."""
    return DeviceProfile(
        device_id=device_id,
        hw_tags=frozenset(getattr(facts, "tags", ()) or ()),
        input_conditions=frozenset(input_conditions),
        memory_mb=getattr(facts, "memory_mb", None),
    )


def local_pipeline(areas: Sequence[tuple[str, frozenset[str]]] = (),
                   *, versions: Sequence[ModelVersion] = ()) -> MlopsPipeline:
    """같은 프로세스에서 도는 실행영역으로 파이프라인을 세운다.

    `--broker` 없이 콘솔을 띄우는 경우와 같은 자세다 — 제어면 제품을 요구하지 않고
    같은 계약의 로컬 구현을 쓴다(AI-B-11: 모든 실행영역이 같은 오케스트레이터를
    설치해야 한다는 전제를 두지 않는다).
    """
    from mission_runtime.execution.control import LocalControlSupervisor  # noqa: PLC0415

    bindings = [ClusterBinding(cluster_id, LocalControlSupervisor(), tags)
                for cluster_id, tags in (areas or (("zone-edge",
                                                    frozenset({"zone-edge"})),))]
    pipeline = MlopsPipeline(bindings)
    for version in versions:
        pipeline.register_version(version)
    return pipeline


def deployable_for(capability_kind: str, device_id: str, *,
                   required_tags: Iterable[str] = ("zone-edge",),
                   core: bool = False) -> Deployable:
    """그 기기의 그 기능을 실행 단위로 선언한다. 클러스터 이름은 들어가지 않는다."""
    return Deployable(
        deployable_id=f"{capability_kind}@{device_id}",
        capability_kind=capability_kind,
        placement=PlacementRequest(required_tags=frozenset(required_tags)),
        control_params={"device_id": device_id},
        core=core,
    )
