"""Landmark-based self-localization + target-bearing refinement (AI-E-04, AI-S-06).

implements: AI-E-04, AI-C-02, AI-C-19, AI-C-20

2026-09-16 door/pedestal 랜드마크 통합 설계(계획 문서 "데모 파이프라인의
perception-framework 통합 설계" 참고). 검증된 PoC(demo/test/navigate_to_target_service.py)
의 자기위치추정 + 회전각/거리 계산 로직을 옮긴다. UniDepth 같은 무거운 CUDA
모델은 AI-E-04("선택형 보조 기능")이라 엣지에서만 돈다 — 이 모듈은 그 실행을
`UniDepthCameraProvider`(지연 import) 뒤로 숨기고, 실제 각도·거리 계산은 순수
함수로 분리해 모델 없이도 단위테스트가 가능하게 한다.

**이 세션에서 실측으로 발견/수정한 핵심 버그(재발 방지를 위해 명시)**: 8방향
회전 스캔은 45도 간격 8단계뿐이라, "그 프레임에서 탐지된 물체가 화면 정중앙에
있다"고 가정해버리면 회전 지시각이 항상 45의 배수로만 나오는 구조적 결함이
생긴다(사용자 실측 지적: "60~70도 정도로 나와야 함"). 탐지 박스가 화면 중심에서
얼마나 벗어났는지를 그 프레임에서 카메라가 스스로 추정한 내부파라미터(fx, cx)로
각도 보정하면 45도 배수 제약 없는 연속값을 얻는다 — `bearing_offset_deg`/
`refined_target_bearing_deg`가 그 수정된 계산이다. 로봇 자신의 위치·거리 계산
(랜드마크 collinear 가정, `estimate_robot_position`)은 이 세션에서 손대지 않은
기존 로직 그대로다.

물리 명령(회전/전진)은 여기서 직접 로봇에 보내지 않는다 — `contracts.
physical_command.Command`로 감싸 `execution.command_execution.
CommandExecutionSupervisor`에 제출하는 것까지만 이 모듈의 책임이다(AI-C-19:
AI는 물리 명령 발급과 실제 액추에이터 제어를 직접 소유하지 않는다). 실제
하드웨어 전달은 HW 브랜치 `pi/robot/go1_link.py`가 아직 `send_command()`를
`NotImplementedError`로 의도적으로 막아 둔 것에서 보듯 별도 어댑터의 책임이다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from perception_framework.contracts.physical_command import Command

#: 박스가 프레임 폭의 이 비율 이상을 채우면 중심점을 신뢰하지 않는다(초근접
#: 촬영된 랜드마크는 픽셀 오프셋이 실제 각도와 무관해진다 — 실측 확인됨).
MAX_RELIABLE_BOX_WIDTH_FRACTION = 0.6

#: 목적지 정지 거리 기본값(타겟 클래스별로 다를 수 있음, 예: door=80cm).
DEFAULT_STANDOFF_CM = 30.0

#: 2026-09-17 조사 결론(계획 문서 "로봇 RSSI 기반 위치추정" 참고): RSSI
#: 삼변측량/핑거프린팅은 실내에서 보통 0.6~6m 오차라 문 앞 80cm 정지
#: 목표에는 못 미친다 -- **주 위치추정 대체 수단이 아니라, 단상이 하나도
#: 안 보일 때(위 estimate_robot_position도 실패할 때)의 최후 보조
#: fallback**으로만 자리를 남겨 둔다. Tailscale 등 메시-VPN 링크 품질은
#: 물리적 거리와 상관이 약해(AI-N-03의 링크 품질과는 다른 목적) 이 신호로
#: 안 쓴다 -- 쓰려면 전용 BLE 비콘(3~4개 + 1회 핑거프린팅 조사)이 새
#: 물리 인프라로 필요하며, 이번 통합의 필수 범위에는 없다(별도 후속 과제).
#: `POSE_SOURCE`(contracts.data_dictionary) 값으로 이 이름을 쓸 자리만 예약.
BLE_BEACON_FINGERPRINT_POSE_SOURCE = "ble_beacon_fingerprint"


def bearing_offset_deg(
    box_xyxy: tuple[float, float, float, float],
    frame_width_px: float,
    fx: float,
    cx: float,
) -> float | None:
    """탐지 박스 중심이 프레임 중심(주점 cx)에서 벗어난 정도를 pinhole 모델
    (atan2(x_offset, fx))로 각도 환산한다.

    회전 스캔이 8단계(45도 간격)뿐이라 "탐지 = 화면 정중앙"으로 가정하면 회전
    지시각이 45의 배수로만 나오는 구조적 결함이 생긴다(모듈 docstring 참고) —
    이 함수가 그 결함을 없애는 연속값 보정이다. 박스가 프레임의 상당 부분을
    채우면(예: 초근접 랜드마크) 중심점 자체를 못 믿으므로 None을 반환한다.
    """
    x1, y1, x2, y2 = box_xyxy
    box_width_fraction = (x2 - x1) / frame_width_px if frame_width_px > 0 else 1.0
    if box_width_fraction > MAX_RELIABLE_BOX_WIDTH_FRACTION:
        return None
    center_x = (x1 + x2) / 2.0
    return math.degrees(math.atan2(center_x - cx, fx))


def circular_mean_deg(angles_deg: list[float]) -> float:
    """각도들의 평균을 0/360 경계를 넘나드는 wrap-around 없이 구한다."""
    if not angles_deg:
        raise ValueError("angles_deg must be non-empty")
    sin_sum = sum(math.sin(math.radians(a)) for a in angles_deg)
    cos_sum = sum(math.cos(math.radians(a)) for a in angles_deg)
    return math.degrees(math.atan2(sin_sum, cos_sum)) % 360.0


@dataclass(frozen=True)
class BearingObservation:
    """한 회전 스캔 프레임에서의 원시 관측 하나."""

    rotation_deg: float
    box_xyxy: tuple[float, float, float, float]
    frame_width_px: float


@dataclass(frozen=True)
class RefinedBearing:
    """`refined_target_bearing_deg`의 산출 과정을 그대로 남긴 결과 —
    "왜 이 회전각인가"를 재현할 수 있어야 한다(AI-C-19 근거 재현)."""

    refined_target_rotation_deg: float
    per_observation: tuple[tuple[float, float | None, float | None], ...]
    #: (rotation_deg, pixel_offset_angle_deg 또는 None, refined_rotation_deg 또는 None)
    spread_deg: float | None  # 관측이 2개 이상일 때만: 서로 다른 관측 간 불일치 폭


def refined_target_bearing_deg(
    observations: list[BearingObservation],
    fx: float,
    cx: float,
) -> RefinedBearing | None:
    """타겟 자신의 관측(들)만으로 연속값 회전각을 직접 구한다 — 로봇의 지도상
    위치나 다른 랜드마크(예: 단상)를 거치지 않는다. 그래서 "그 랜드마크가 안
    보여도" 성립한다(이관메모의 B단계 완화안과 일치).
    """
    per_observation: list[tuple[float, float | None, float | None]] = []
    refined: list[float] = []
    for obs in observations:
        offset = bearing_offset_deg(obs.box_xyxy, obs.frame_width_px, fx, cx)
        if offset is None:
            per_observation.append((obs.rotation_deg, None, None))
            continue
        r = (obs.rotation_deg + offset) % 360.0
        per_observation.append((obs.rotation_deg, offset, r))
        refined.append(r)
    if not refined:
        return None
    target = circular_mean_deg(refined)
    spread = (max(refined) - min(refined)) if len(refined) > 1 else None
    return RefinedBearing(target, tuple(per_observation), spread)


def turn_signed_deg(target_bearing_deg: float, current_heading_deg: float = 0.0) -> float:
    """`current_heading_deg`에서 `target_bearing_deg`를 향하도록 회전해야 하는
    최단 각도(부호: 오른쪽(시계)=+, 왼쪽(반시계)=- — 로봇 팀과 확정된 부호
    규약, `detection-protocol_0914.md`/`이관메모_260914.md` 참고)."""
    return (target_bearing_deg - current_heading_deg + 180.0) % 360.0 - 180.0


@dataclass(frozen=True)
class LandmarkGeometry:
    """도면상 고정 위치가 알려진 랜드마크(단상) 기준 로봇 위치 추정에 필요한
    기하 정보. PoC의 `PEDESTAL_BOX_CM`/`PEDESTAL_CENTER_CM`에 대응한다."""

    center_cm: tuple[float, float]
    half_width_cm: float
    half_height_cm: float


def estimate_robot_position(
    landmark: LandmarkGeometry,
    target_position_cm: tuple[float, float],
    landmark_distance_cm: float,
) -> tuple[float, float]:
    """랜드마크(단상) 표면에서 실측된 거리만큼, 랜드마크→목표 방향으로 나아간
    지점을 로봇 위치로 본다.

    **정직한 한계**(PoC 모듈 docstring 그대로 유지): "로봇이 랜드마크를 바라보며
    촬영한 시점의 시선 방향이 곧 랜드마크→목표 방향과 일치한다"는 이 배치
    환경 특유의 기하 가정이다 — 일반적인 다각도 삼변측량이 아니다. 이 가정은
    이번 세션에서 손대지 않았다(회전각만 `refined_target_bearing_deg`로
    대체됐고, 거리·위치 추정은 기존 방식 유지).
    """
    dx = target_position_cm[0] - landmark.center_cm[0]
    dy = target_position_cm[1] - landmark.center_cm[1]
    length = math.hypot(dx, dy)
    if length == 0:
        raise ValueError("landmark and target positions coincide")
    ux, uy = dx / length, dy / length

    cx, cy = landmark.center_cm
    px1 = cx - landmark.half_width_cm
    px2 = cx + landmark.half_width_cm
    py1 = cy - landmark.half_height_cm
    py2 = cy + landmark.half_height_cm
    t_x = ((px2 if ux > 0 else px1) - cx) / ux if ux != 0 else float("inf")
    t_y = ((py2 if uy > 0 else py1) - cy) / uy if uy != 0 else float("inf")
    t_exit = min(t_x, t_y)
    surface_x = cx + t_exit * ux
    surface_y = cy + t_exit * uy
    return (surface_x + landmark_distance_cm * ux, surface_y + landmark_distance_cm * uy)


@dataclass(frozen=True)
class NavigationPlan:
    """경로 산출 결과 — `contracts.data_dictionary`의 TURN_DEG/FORWARD_DISTANCE_M/
    STANDOFF_CM 이름을 그대로 쓴다."""

    turn_deg: float
    forward_distance_m: float
    standoff_cm: float
    distance_to_target_cm: float
    goal_cm: tuple[float, float]


def plan_navigation(
    robot_position_cm: tuple[float, float],
    target_position_cm: tuple[float, float],
    target_bearing_deg: float,
    current_heading_deg: float,
    *,
    standoff_cm: float = DEFAULT_STANDOFF_CM,
) -> NavigationPlan:
    dx = target_position_cm[0] - robot_position_cm[0]
    dy = target_position_cm[1] - robot_position_cm[1]
    distance_to_target_cm = math.hypot(dx, dy)
    ux, uy = (dx / distance_to_target_cm, dy / distance_to_target_cm) if distance_to_target_cm > 0 else (1.0, 0.0)

    turn = turn_signed_deg(target_bearing_deg, current_heading_deg)
    forward_distance_cm = distance_to_target_cm - standoff_cm
    goal_cm = (
        robot_position_cm[0] + forward_distance_cm * ux,
        robot_position_cm[1] + forward_distance_cm * uy,
    )
    return NavigationPlan(
        turn_deg=turn,
        forward_distance_m=forward_distance_cm / 100.0,
        standoff_cm=standoff_cm,
        distance_to_target_cm=distance_to_target_cm,
        goal_cm=goal_cm,
    )


def build_navigation_command(
    plan: NavigationPlan,
    *,
    command_id: str,
    target: str,
    correlation_id: str | None = None,
) -> Command:
    """`plan`을 물리 명령 계약(`Command`)으로 감싼다.

    `action`/`parameters`는 이 계약에서 의도적으로 opaque하다(AI-C-19) — 실제
    로봇에 어떻게 전달할지는 하드웨어 어댑터가 정한다. 여기서는 로봇 팀과
    이미 합의된 필드 모양(`이관메모_260914.md` §5-4: "turn.deg는 오른쪽이
    +", "move_forward.distance_m에는 standoff가 이미 반영됨")을 그대로 쓴다.
    """
    return Command(
        command_id=command_id,
        target=target,
        action="navigate_to_standoff",
        parameters={
            "turn": {"deg": plan.turn_deg},
            "move_forward": {"distance_m": plan.forward_distance_m},
            "standoff_cm": plan.standoff_cm,
            "note": "turn.deg는 오른쪽이 +(왼쪽이 음수). move_forward.distance_m에는 "
                    "standoff가 이미 반영돼 있다 -- 또 빼지 말 것.",
        },
        correlation_id=correlation_id,
    )


#: 2026-09-16 실제 로봇 리허설 반영(이관메모_260914.md B/C 단계, physical_demo
#: 저장소 커밋 "단상이 안 잡혀도 문만으로 위치와 경로를 내고..." 그대로 포팅).
#: 리허설에서 로봇 실물 프레임 8장 중 단상이 한 장에도 안 잡혀 단상 기반
#: 위치추정(estimate_robot_position)이 완전히 실패했다. 문 depth는 UniDepth
#: 보정식 유효범위 밖(rel_depth≈10)이라 거리로 못 쓴다 -- 그래서 **문의
#: 겉보기 크기**(핀홀: 크기가 거리에 반비례)로 거리를 어림한다.
#: K값은 단상 기반 위치추정이 성공한 판(데이터셋 8장, 로봇-문 실측 715.4cm)
#: 에서 역산한 값이고, 464x400 프레임(테두리 자르기 237x241) 전용이다.
DOOR_SIZE_K_WIDTH = 14333.0
DOOR_SIZE_K_HEIGHT = 38674.0
#: 프레임 가장자리에 닿아 잘린 치수는 왜곡되므로 버린다(리허설에서 잘린
#: 315도 프레임의 폭이 이렇게 걸러졌다).
EDGE_CLIP_MARGIN_PX = 1.5
#: 이 범위 밖 추정치는 명백히 잘못된 것으로 보고 버린다.
PLAUSIBLE_DOOR_DISTANCE_CM = (150.0, 1500.0)


@dataclass(frozen=True)
class ApparentSizeObservation:
    """문(등, 도면상 실제 크기를 모르는 대상)이 한 프레임에서 보인 크기."""

    box_xyxy: tuple[float, float, float, float]
    frame_width_px: float
    frame_height_px: float


def estimate_distance_from_apparent_size(
    observations: list[ApparentSizeObservation],
    *,
    k_width: float = DOOR_SIZE_K_WIDTH,
    k_height: float = DOOR_SIZE_K_HEIGHT,
    edge_clip_margin_px: float = EDGE_CLIP_MARGIN_PX,
    plausible_range_cm: tuple[float, float] = PLAUSIBLE_DOOR_DISTANCE_CM,
) -> float | None:
    """핀홀 모델(거리 ∝ 1/겉보기 크기)로 거리를 어림한다 -- depth가 유효범위
    밖일 때(먼 물체)의 대체 경로(이관메모 C단계). 폭과 높이 각각에서 추정치를
    얻고, 프레임 가장자리에 잘린 치수·비합리적 범위 밖 추정치는 버린 뒤
    **중앙값**을 쓴다 -- 한 치수가 틀려도(비스듬한 폭, 일부만 잡힌 높이)
    끌려가지 않게 한다. 쓸 수 있는 추정치가 하나도 없으면 None(정직한 실패)."""
    estimates: list[float] = []
    for obs in observations:
        x1, y1, x2, y2 = obs.box_xyxy
        w, h = x2 - x1, y2 - y1
        width_clipped = x1 <= edge_clip_margin_px or x2 >= obs.frame_width_px - edge_clip_margin_px
        height_clipped = y1 <= edge_clip_margin_px or y2 >= obs.frame_height_px - edge_clip_margin_px
        if w > 0 and not width_clipped:
            estimates.append(k_width / w)
        if h > 0 and not height_clipped:
            estimates.append(k_height / h)
    plausible = sorted(d for d in estimates if plausible_range_cm[0] <= d <= plausible_range_cm[1])
    if not plausible:
        return None
    mid = len(plausible) // 2
    if len(plausible) % 2 == 1:
        return plausible[mid]
    return (plausible[mid - 1] + plausible[mid]) / 2.0


def backtrace_robot_position_from_target(
    target_position_cm: tuple[float, float],
    refined_target_rotation_deg: float,
    distance_cm: float,
    *,
    assumed_current_heading_deg: float = 0.0,
) -> tuple[float, float]:
    """단상 없이 문만으로 로봇 위치를 **역산**한다 -- 실제 측정이 아니라
    "로봇 시작 방향이 assumed_current_heading_deg였다면"이라는 가정 위의
    추정이므로 지도 표시용일 뿐이다(이관메모: "역추적"). 회전 지시각/전진
    거리(`plan_navigation`이 필요로 하지 않는 것과 달리) 이 값 자체는 물리
    명령에 쓰지 않는다 -- turn_signed_deg(refined_bearing, 0.0)만으로 회전은
    이미 충분히 구해진다(로봇 위치를 몰라도 성립, 모듈 docstring 참고)."""
    absolute_bearing_deg = (refined_target_rotation_deg + assumed_current_heading_deg) % 360.0
    rad = math.radians(absolute_bearing_deg)
    return (
        target_position_cm[0] - distance_cm * math.cos(rad),
        target_position_cm[1] - distance_cm * math.sin(rad),
    )


def plan_navigation_target_only(
    distance_to_target_cm: float,
    target_bearing_deg: float,
    *,
    current_heading_deg: float = 0.0,
    standoff_cm: float = DEFAULT_STANDOFF_CM,
) -> NavigationPlan:
    """단상(또는 다른 랜드마크) 없이, 목표 자신의 관측만으로 회전각+거리를
    구한다(이관메모 B/C 단계) -- `goal_cm`은 로봇의 실제 지도 위치를 모르므로
    `(0, 0)` 기준 상대좌표로만 둔다(지도에 그리려면
    `backtrace_robot_position_from_target`로 얻은 "가정 위치"를 origin으로
    따로 더해야 하고, 이 함수는 그 가정을 강제하지 않는다)."""
    turn = turn_signed_deg(target_bearing_deg, current_heading_deg)
    forward_distance_cm = distance_to_target_cm - standoff_cm
    ux, uy = math.cos(math.radians(target_bearing_deg)), math.sin(math.radians(target_bearing_deg))
    return NavigationPlan(
        turn_deg=turn,
        forward_distance_m=forward_distance_cm / 100.0,
        standoff_cm=standoff_cm,
        distance_to_target_cm=distance_to_target_cm,
        goal_cm=(forward_distance_cm * ux, forward_distance_cm * uy),
    )


class UniDepthCameraProvider:
    """UniDepth(무거운 CUDA 모델, AI-E-04 선택 기능)로 프레임의 depth와, 그
    프레임에서 스스로 추정한 카메라 내부파라미터(fx, cx)를 함께 낸다.

    `unidepth`는 모듈 최상단이 아니라 생성자 안에서 지연 import한다(AI-C-11 —
    `open_vocabulary.py::OwlVitPerceptionProvider`와 동일 패턴). 이 provider가
    없어도(예: UniDepth 미설치 노드) 이 모듈의 순수 함수(`bearing_offset_deg`
    등)는 계속 동작한다 — 그 함수들은 fx/cx/depth를 인자로만 받는다.
    """

    def __init__(self, model_id: str = "lpiccinelli/unidepth-v2-vitb14", *, device: str = "cuda") -> None:
        self.model_id = model_id
        self.device = device
        self._model: Any | None = None

    def is_available(self) -> bool:
        try:
            import unidepth  # noqa: F401
        except Exception:
            return False
        return True

    def _load(self) -> Any:
        if self._model is None:
            from unidepth.models import UniDepthV2

            self._model = UniDepthV2.from_pretrained(self.model_id).to(self.device).eval()
        return self._model

    def infer(self, rgb_chw_tensor: Any) -> tuple[Any, float, float]:
        """returns (depth_map, fx, cx) for the given preprocessed frame tensor."""
        import torch

        model = self._load()
        with torch.inference_mode():
            out = model.infer(rgb_chw_tensor, camera=None, normalize=True)
        intr = out["intrinsics"][0].cpu().numpy()
        fx, cx = float(intr[0, 0]), float(intr[0, 2])
        return out["depth"][0, 0].cpu().numpy(), fx, cx
