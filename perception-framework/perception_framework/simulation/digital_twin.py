"""Mock of the *backend digital twin's* global coordinate transform and
cross-source observation map.

implements (as a *stand-in* for): DT-01, DT-03, BE-C-04
tests: simulator scenario `digital-twin-global-coords`

BE-C-04 / AI-C-02: "전역 좌표 변환은 백엔드 디지털 트윈이 담당해야 한다."
`perception_framework.common.coordinates.to_global` raises `NotImplementedError`
on purpose (AI code must not compute this itself); this module is where
that transform lives instead, standing in for the real backend the same
way `simulation.backend.BackendAvailabilityIntegrator` stands in for the
backend's device-availability verdict (원칙 #19, AI-C-19).

Deliberately *not* here: real camera calibration, lens distortion,
uncertainty-weighted fusion, occlusion reasoning, map persistence. The
fixed-camera pose is supplied as a known value by the caller, and the
transform is a plain pinhole ground-plane intersection. If a scenario
needs more fidelity than this, that is the DT 파트's job.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from perception_framework.common.coordinates import CoordinateFrame, SpatialValue


@dataclass(frozen=True)
class CameraPose:
    """Known installation parameters of one fixed observation source.

    Given, not estimated — DT-03 은 고정 카메라 설치 구성에서 기하학적으로
    결정되는 값을 다룬다(AI-S-08와의 경계).

    `yaw_rad` rotates the camera's forward axis in the global x-z ground
    plane; `height_m` is the mounting height above that plane;
    `pitch_rad` is the downward tilt (positive = looking down).
    """

    source_id: str
    x_m: float
    z_m: float
    height_m: float
    yaw_rad: float = 0.0
    pitch_rad: float = math.pi / 6
    horizontal_fov_rad: float = math.pi / 3
    image_width: int = 1920
    image_height: int = 1080


class GlobalCoordinateService:
    """Backend-side global transform (BE-C-04).

    Consumes SpatialValue in IMAGE frame plus a registered CameraPose and
    returns a GLOBAL-frame SpatialValue on the x-z ground plane.
    """

    def __init__(self) -> None:
        self._poses: dict[str, CameraPose] = {}

    def register_camera(self, pose: CameraPose) -> None:
        self._poses[pose.source_id] = pose

    def known_sources(self) -> tuple[str, ...]:
        return tuple(sorted(self._poses))

    def to_global(self, value: SpatialValue) -> SpatialValue:
        """Image point -> ground-plane (x, z) in the global frame.

        Raises for an unregistered source rather than guessing a pose:
        AI-S-08 금지사항 "기준점이 없는 배치에서 임의의 절대 위치 생성".
        """
        if value.frame is CoordinateFrame.GLOBAL:
            return value
        pose = self._poses.get(value.source_id)
        if pose is None:
            raise KeyError(
                f"no registered camera pose for source {value.source_id!r}; "
                "refusing to invent a global position"
            )
        if value.frame is not CoordinateFrame.IMAGE:
            raise ValueError(
                f"mock transforms IMAGE-frame values only, got {value.frame.value}"
            )
        u, v = value.values[0], value.values[1]

        # Normalised image offsets, then per-axis angles from the optical axis.
        aspect = pose.image_height / pose.image_width
        vertical_fov = pose.horizontal_fov_rad * aspect
        dx = (u / pose.image_width) - 0.5
        dy = (v / pose.image_height) - 0.5
        yaw = pose.yaw_rad + dx * pose.horizontal_fov_rad
        pitch = pose.pitch_rad + dy * vertical_fov

        if pitch <= 1e-6:
            raise ValueError(
                "ray does not intersect the ground plane (looking at or above horizon)"
            )
        ground_range = pose.height_m / math.tan(pitch)
        gx = pose.x_m + ground_range * math.sin(yaw)
        gz = pose.z_m + ground_range * math.cos(yaw)
        return SpatialValue(
            values=(gx, gz),
            frame=CoordinateFrame.GLOBAL,
            source_id=value.source_id,
            calibration_profile_version=value.calibration_profile_version,
        )


@dataclass(frozen=True)
class PlacedObservation:
    """One local result placed into the global frame."""

    entity_id: str
    source_id: str
    position: SpatialValue
    evidence_sufficient: bool = False
    confidence: float | None = None


@dataclass
class ObservationMap:
    """Integrated map of observations from several sources (DT-01 stand-in).

    Fusion here is intentionally trivial — the placements are simply
    grouped by entity. Uncertainty-weighted fusion is DT 파트 소관이며
    AI-S-06 은 그 *입력*만 만든다.
    """

    placements: list[PlacedObservation] = field(default_factory=list)

    def by_entity(self) -> dict[str, list[PlacedObservation]]:
        grouped: dict[str, list[PlacedObservation]] = {}
        for p in self.placements:
            grouped.setdefault(p.entity_id, []).append(p)
        return grouped

    def sources(self) -> tuple[str, ...]:
        return tuple(sorted({p.source_id for p in self.placements}))

    def blind_spot_entities(self) -> tuple[str, ...]:
        """Entities backed by no source with sufficient evidence."""
        return tuple(
            sorted(
                entity
                for entity, items in self.by_entity().items()
                if not any(i.evidence_sufficient for i in items)
            )
        )


def build_observation_map(
    service: GlobalCoordinateService,
    local_results: list[PlacedObservation],
) -> ObservationMap:
    """Place local-frame results into the global frame (DT-01/DT-03)."""
    placed = [
        PlacedObservation(
            entity_id=r.entity_id,
            source_id=r.source_id,
            position=service.to_global(r.position),
            evidence_sufficient=r.evidence_sufficient,
            confidence=r.confidence,
        )
        for r in local_results
    ]
    return ObservationMap(placements=placed)
