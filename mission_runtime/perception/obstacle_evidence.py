"""Builds per-frame obstacle evidence from detections and a depth field.

implements: AI-E-01 (공통 인지 인터페이스), AI-S-06 (근거 누적), AI-C-02 (프레임 태깅)
관련: AI-R-02 (없는 입력을 임의 생성하지 않는다), AI-B-08, AI-E-02, AI-S-03, AI-S-04

이 모듈이 **내는 것** — 장애물의 그룹·역할, 로봇 로컬 좌표, 거리와 그 거리의
상태, TTC, 그리고 그 값을 만든 생산자. 이 모듈이 **내지 않는 것** — 회피 경로,
목표점, 속도·회전 명령, 정지 명령. 경로 후보는 `planning/path_candidates.py`,
채점은 `risk/path_evaluation.py`, 물리 명령 발급은 백엔드다(AI-C-19, AI-C-20).

좌표계(AI-C-02)
---------------
로봇 로컬만 쓴다. 원점은 로봇, **+y 전방 · +x 우측**, 단위 m. 프레임의
`rotation_deg` 로 돌려 여러 장을 한 스캔 기준에 모은다.

깊이는 **배열이 아니라 `DepthField`** 로 받는다
-----------------------------------------------
배열만 받으면 받는 쪽이 깊이 공간을 추측하게 된다. 그 추측이 실제 사고였다 —
UniDepth 용 보정식을 ZipDepth 역깊이에 대자 1110 개 박스 전부가 12.7~15.0cm 로
뭉개져 "바로 앞에 장애물" 이 화면 어디에나 생겼다(2026-09-20 실측). 그래서
`edge/depth_contract.py` 의 `DepthField` + 그 출력에 **묶인** 보정 프로파일만
받고, 어긋나면 `CalibrationMismatch` 로 멈춘다.

같은 이유로 박스 대표값의 퍼센타일도 여기서 정하지 않는다 — depth 는 p40,
역깊이는 근거리 쪽이 큰 값이라 p60 이 같은 의도이고, 어느 쪽인지는 프로파일이
안다.

거리가 없을 때
--------------
`distance_m is None` 은 "이 박스에서 거리를 확정하지 못했다" 이고 **0.0 이
아니다.** 옛 구현이 보정식의 음수 출력을 `max(0.0, …)` 로 잘라 **0cm** 를
돌려줬고 소비자는 그것을 "로봇 바로 앞" 으로 읽었다 — 없는 위험이 만들어졌다.
그 자리를 `None` + `distance_reason` 으로 갈라 둔다(AI-R-02).

방위각이 없을 때
----------------
역깊이 provider 는 fx·cx 를 내주지 않는다. 그런데도 각도를 내면 숫자는 나오고
근거는 없다. 그래서 방위각에는 **근거가 함께 붙는다** —
`depth_provider_intrinsics`(그 추론이 추정한 값) ·
`declared_intrinsics`(보정 프로파일이 선언한 값) ·
`unmeasured_no_intrinsics`(없음 — 각도를 지어내지 않고 프레임 방향만 쓴다).
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from mission_runtime.edge.depth_contract import (
    BEARING_MEASURED,
    BEARING_UNMEASURED_NO_INTRINSICS,
    STATUS_MEASURED,
    DepthCalibrationProfile,
    DepthField,
    bearing_deg,
    measure_distance,
)
from mission_runtime.perception.obstacle_taxonomy import (
    FLOOR_BASIS_NONE,
    FLOOR_NO_BASIS,
    ObstacleTaxonomy,
)

#: 깊이 출력 자체가 없었다 — provider 가 그 노드에 없거나 프레임을 못 읽었다.
REASON_NO_DEPTH = "no_depth_field"
#: 방위각 근거 토큰. `declared_intrinsics` 는 보정 프로파일이 선언한 fx·cx 다.
BEARING_FROM_PROVIDER = "depth_provider_intrinsics"
BEARING_FROM_DECLARATION = "declared_intrinsics"

_DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "depth_calibration.example.json"


@dataclass(frozen=True)
class Detection:
    """provider 중립 탐지 결과. 어떤 모델이 냈는지는 `source` 에만 남는다."""

    class_name: str
    score: float
    #: **원본 프레임 좌표.** crop·배율 환산은 깊이 쪽이 자기 `DepthField` 로 한다.
    box_xyxy: tuple[float, float, float, float]
    source: str
    #: 어느 어휘에서 온 이름인가. 제로샷과 미세조정은 같은 글자여도 다른 근거다.
    vocabulary: str = "zeroshot"
    #: 그 이름이 **어느 이름 공간에서** 왔는가(탐지기 선언의 `label_namespace`).
    #: `None` 은 "적지 않았다" 이고, 그때는 어휘가 선언한 이름 공간을 그대로 본다.
    #: 어휘를 받지 않는 탐지기(`model_builtin_vocabulary`)의 라벨에 이 칸을 채워야
    #: 운영자 어휘의 하한을 빌리지 않는다 — 빌리던 것이 결함이었다.
    label_namespace: str | None = None


@dataclass(frozen=True)
class ObstacleEvidence:
    """한 프레임에서 관측된 장애물 하나에 대한 근거."""

    evidence_id: str
    frame_ref: str
    rotation_deg: float
    class_name: str
    group: str
    group_priority: int
    #: 배경·객체·행위자·지면. 트윈이 "지도의 몸체인가 움직일 것인가" 를 가른다.
    role: str
    #: 이 이름이 확정 분류인가 가설인가. 제로샷은 끝까지 가설이다(AI-L-02).
    label_status: str
    vocabulary: str
    detector_score: float
    detector_source: str
    #: 깊이를 낸 provider 의 키. 어느 구성으로 잰 값인지가 근거에 남는다(AI-B-01).
    depth_source: str
    #: 그 깊이 값의 공간. 없으면 빈 문자열이다.
    depth_space: str
    box_xyxy: tuple[float, float, float, float]
    raw_depth: float | None
    distance_m: float | None
    #: 거리의 **상태**. 거리가 없으면 왜 없는지가 여기 있다.
    distance_reason: str
    #: 그 거리를 낸 보정 프로파일. 없으면 None 이다.
    calibration_profile_id: str | None
    bearing_deg: float | None
    #: 그 방위각이 **무엇을 근거로** 나왔는가. 없으면 지어내지 않았다는 뜻이다.
    bearing_basis: str
    #: 스캔 시작 기준(+우측). 방위각이 없으면 프레임 방향 그대로다.
    local_bearing_deg: float
    #: (x=우측, y=전방) m. **로봇 로컬**이고 전역이 아니다(AI-C-02).
    local_xy_m: tuple[float, float] | None
    ttc_s: float | None
    near_threshold_m: float
    near_threshold_basis: str
    risk_band: str
    frame: str = "robot-local"
    # 아래 셋은 **기본값이 "모른다" 라서 맨 뒤에 있다**(기본값 있는 칸은 뒤여야
    # 한다). 손으로 만든 레코드는 하한을 선언한 적이 없으므로 그 상태가 맞다 —
    # 기본값을 0.0 이나 `above_floor` 로 두면 선언한 적 없는 하한을 통과한 것처럼
    # 읽힌다.
    #: 이 라벨에 **선언된** 점수 하한. 근거가 없으면 `None` 이고 0 이 아니다.
    #: 여기 실리지만 **거름 조건으로 쓰이지 않는다** — 하한을 말할 근거가 없는 것은
    #: 그 관측이 틀렸다는 뜻이 아니고, 거르면 이름 없는 관측이 사라져 AI-S-04 가
    #: 막는 동작이 된다. 근거 충분도(AI-S-03)를 세는 쪽이 이 칸을 읽는다.
    score_floor: float | None = None
    #: 그 하한이 어디서 왔는가(`declared_for_class` · `vocabulary_default` ·
    #: `no_declared_floor`). 값만 보면 선언된 0.25 와 근거 없는 0.25 가 같아 보인다.
    score_floor_basis: str = FLOOR_BASIS_NONE
    #: 점수가 그 하한에 대해 어떤 상태인가(`above_floor` · `below_floor` ·
    #: `no_floor_declared`). **셋이고 둘이 아니다.**
    score_floor_state: str = FLOOR_NO_BASIS

    @property
    def distance_known(self) -> bool:
        return self.distance_m is not None

    def to_dict(self) -> dict:
        return asdict(self)


def load_calibration_profiles(path: str | Path | None = None) -> dict[str, DepthCalibrationProfile]:
    """선언된 보정 프로파일을 **provider_key 로** 색인해 읽는다.

    읽히지 않으면 빈 사전이고 예외가 아니다 — 보정 선언이 없는 배치가 정상이고
    그때는 거리만 미측정으로 나간다(AI-C-05).
    """
    try:
        with open(Path(path or _DEFAULT_CONFIG), encoding="utf-8") as fh:
            declared = json.load(fh).get("profiles") or []
    except (OSError, ValueError):
        return {}

    out: dict[str, DepthCalibrationProfile] = {}
    for row in declared:
        applies = row.get("applies_to") or {}
        key = str(applies.get("provider_key", ""))
        if not key:
            continue
        lo, hi = row.get("valid_rel_range") or (0.0, float("inf"))
        conditions = {k: v for k, v in applies.items()
                      if k not in ("provider_key", "depth_space")}
        coefficients = tuple(float(c) for c in row.get("coefficients") or ())
        out[key] = DepthCalibrationProfile(
            profile_id=str(row.get("profile_id", "")),
            version=int(row.get("version", 1)),
            applies_to_provider_key=key,
            applies_to_depth_space=str(applies.get("depth_space", "")),
            form=str(row.get("form", "")),
            roi_percentile=float(row.get("roi_percentile", 50.0)),
            valid_rel_range=(float(lo), float(hi)),
            min_valid_cm=float(row.get("min_valid_cm", 0.0)),
            status=str(row.get("status", "")),
            source=str(row.get("source", "")),
            created_at=str(row.get("created_at", "")),
            input_conditions=conditions,
            # 미측정 품질 항목은 **키가 없다**. `$` 로 시작하는 주석 키는 뺀다.
            quality={k: v for k, v in (row.get("quality") or {}).items()
                     if not k.startswith("$")},
            fn=_build_fn(str(row.get("model", "")), coefficients,
                         row.get("radial_correction") or {}),
        )
    return out


def _build_fn(model: str, coefficients: tuple[float, ...], radial: dict):
    """선언된 식 모양을 함수로 만든다. 모양을 모르면 **함수가 없다**(값을 내지 않는다)."""
    if not coefficients or not any(coefficients):
        return None
    if model == "cubic_depth_to_cm":
        def cubic(rel, *, bbox=None, image_w=0, image_h=0):
            cm = 0.0
            for c in coefficients:                       # Horner — 차수는 선언이 정한다
                cm = cm * rel + c
            if bbox is not None and radial and image_w and image_h:
                cm *= _radial_gain(bbox, image_w, image_h, radial)
            return cm
        return cubic
    if model == "reciprocal_inverse_depth_to_cm":
        p, q = (list(coefficients) + [0.0, 0.0])[:2]

        def reciprocal(rel, *, bbox=None, image_w=0, image_h=0):
            denominator = p * rel + q
            return None if abs(denominator) < 1e-12 else 1.0 / denominator
        return reciprocal
    return None


def _radial_gain(bbox, image_w: int, image_h: int, radial: dict) -> float:
    x1, y1, x2, y2 = bbox
    nx = ((x1 + x2) / 2.0 - image_w / 2.0) / (image_w / 2.0)
    ny = ((y1 + y2) / 2.0 - image_h / 2.0) / (image_h / 2.0)
    r = min(1.0, max(0.0, math.hypot(nx, ny)))
    gain = 1.0
    cr = float(radial.get("center_radius", 0.0))
    if cr and r < cr:
        gain *= 1.0 - float(radial.get("center_gain", 0.0)) * (1.0 - r / cr)
    er = float(radial.get("edge_radius", 0.0))
    if er and r > er:
        t = min(1.0, max(0.0, (r - er) / max(1e-9, 1.0 - er)))
        gain *= min(1.0 + float(radial.get("edge_gain", 0.0))
                    * (t ** float(radial.get("edge_exponent", 1.0))),
                    float(radial.get("edge_cap", float("inf"))))
    return gain


def fuse_detections(detections: list[Detection], iou_threshold: float) -> list[Detection]:
    """두 탐지기가 같은 물체를 잡으면 하나로 본다 — **합쳐진 출처를 남기고**.

    사라지는 쪽의 provider id 를 `source` 에 `a+b` 로 남긴다. 남기지 않으면 근거
    둘이 하나로 줄어든 사실이 보이지 않아 근거 충분도가 실제보다 커 보인다
    (AI-S-03 · AI-C-01 생산자 추적).
    """
    def iou(a, b) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
        ih = max(0.0, min(ay2, by2) - max(ay1, by1))
        inter = iw * ih
        if inter <= 0:
            return 0.0
        union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
        return inter / union if union > 0 else 0.0

    kept: list[Detection] = []
    for det in sorted(detections, key=lambda d: (-d.score, d.class_name, d.source)):
        for i, k in enumerate(kept):
            if iou(det.box_xyxy, k.box_xyxy) >= iou_threshold:
                merged = "+".join(sorted(set(k.source.split("+")) | {det.source}))
                if merged != k.source:
                    kept[i] = Detection(k.class_name, k.score, k.box_xyxy, merged,
                                        k.vocabulary, k.label_namespace)
                break
        else:
            kept.append(det)
    return kept


class ObstacleEvidenceBuilder:
    """Detection + DepthField → ObstacleEvidence. 경로·명령 메서드는 **의도적으로** 없다."""

    def __init__(self, taxonomy: ObstacleTaxonomy, *,
                 profiles: dict[str, DepthCalibrationProfile] | None = None,
                 declared_intrinsics: tuple[float, float] | None = None) -> None:
        self._tax = taxonomy
        #: provider_key → 그 출력 전용 보정. 없는 키는 거리를 내지 않는다.
        self._profiles = dict(profiles or {})
        #: 보정이 선언한 fx·cx. 깊이 provider 가 내주지 않을 때의 **차선 근거**이고,
        #: 이것도 없으면 방위각을 내지 않는다.
        self._declared_intrinsics = declared_intrinsics

    def profile_for(self, field_: DepthField | None) -> DepthCalibrationProfile | None:
        """그 출력에 **묶인** 프로파일만 돌려준다. 다른 구성의 것을 빌려주지 않는다."""
        if field_ is None:
            return None
        profile = self._profiles.get(field_.provider_key)
        if profile is None or profile.applies_to_depth_space != field_.depth_space:
            return None
        return profile

    def build(self, *, frame_ref: str, rotation_deg: float,
              detections: list[Detection], depth: DepthField | None = None,
              speed_mps: float | None = None) -> list[ObstacleEvidence]:
        near = self._tax.near_threshold_for_speed(speed_mps)
        profile = self.profile_for(depth)
        band_ratio = (self._tax.mid_threshold_m / self._tax.near_threshold_m
                      if self._tax.near_threshold_m else 1.2)

        out: list[ObstacleEvidence] = []
        for i, det in enumerate(detections):
            verdict = self._tax.classify(det.class_name, vocabulary=det.vocabulary,
                                         label_namespace=det.label_namespace)
            # 판정(`verdict`)이 하한 **값**을 이미 들고 오지만 상태(넘었나·못
            # 미쳤나·근거가 없나)는 점수가 있어야 나온다. 그 셈을 여기서 다시 적지
            # 않고 하한의 주인에게 묻는다 — 두 곳에서 세면 어느 날 갈린다.
            floor = self._tax.score_floor(det.class_name, vocabulary=det.vocabulary,
                                          label_namespace=det.label_namespace)

            if depth is None:
                raw, distance_m, reason, profile_id = None, None, REASON_NO_DEPTH, None
            else:
                measured = measure_distance(profile, depth, det.box_xyxy)
                raw = measured.rel_depth
                distance_m = measured.distance_m
                reason = "" if measured.status == STATUS_MEASURED else measured.status
                profile_id = measured.profile_id

            bearing, basis = self._bearing(depth, det.box_xyxy)
            local_bearing = ((rotation_deg + bearing) % 360.0 if bearing is not None
                             else rotation_deg % 360.0)

            local_xy = None
            if distance_m is not None:
                th = math.radians(local_bearing)
                local_xy = (round(distance_m * math.sin(th), 3),
                            round(distance_m * math.cos(th), 3))

            # TTC: 접근 속도를 모르면 **계산하지 않는다**. 0 이나 무한대로 채우면
            # hazard 가중합에서 "충돌 임박" 또는 "영원히 안전" 이 되어 버린다.
            ttc = None
            if distance_m is not None and speed_mps is not None and speed_mps > 0.05:
                closing = speed_mps * math.cos(math.radians(local_bearing))
                if closing > 0.05:
                    ttc = round(distance_m / closing, 3)

            if distance_m is None:
                band = "unknown"      # far 가 아니다 — 모르는 것을 안전으로 읽지 않는다
            elif distance_m <= near.value_m:
                band = "near"
            elif distance_m <= near.value_m * band_ratio:
                band = "mid"
            else:
                band = "far"

            out.append(ObstacleEvidence(
                evidence_id=f"{frame_ref}:{i:02d}",
                frame_ref=frame_ref,
                rotation_deg=round(float(rotation_deg), 2),
                class_name=verdict.class_name,
                group=verdict.group,
                group_priority=verdict.group_priority,
                role=verdict.role,
                label_status=verdict.label_status,
                vocabulary=verdict.vocabulary,
                detector_score=round(float(det.score), 4),
                detector_source=det.source,
                # 하한은 **근거로 실린다.** 여기서 거르지 않는다(AI-S-04).
                score_floor=None if floor.value != floor.value else floor.value,
                score_floor_basis=floor.basis,
                score_floor_state=floor.state(det.score),
                depth_source="" if depth is None else depth.provider_key,
                depth_space="" if depth is None else depth.depth_space,
                box_xyxy=tuple(round(float(v), 1) for v in det.box_xyxy),
                raw_depth=None if raw is None else round(raw, 6),
                distance_m=None if distance_m is None else round(distance_m, 3),
                distance_reason=reason,
                calibration_profile_id=profile_id,
                bearing_deg=None if bearing is None else round(bearing, 2),
                bearing_basis=basis,
                local_bearing_deg=round(local_bearing, 2),
                local_xy_m=local_xy,
                ttc_s=ttc,
                near_threshold_m=round(near.value_m, 3),
                near_threshold_basis=near.basis,
                risk_band=band,
            ))
        return out

    def _bearing(self, depth: DepthField | None, box) -> tuple[float | None, str]:
        """(방위각, 근거). **근거 없는 각도를 내지 않는다**(AI-C-02)."""
        if depth is not None and depth.intrinsics is not None:
            angle, status = bearing_deg(depth, box)
            if status == BEARING_MEASURED:
                return angle, BEARING_FROM_PROVIDER
        if self._declared_intrinsics is not None:
            fx, cx = self._declared_intrinsics
            if fx:
                return math.degrees(math.atan2((box[0] + box[2]) / 2.0 - cx, fx)), \
                    BEARING_FROM_DECLARATION
        return None, BEARING_UNMEASURED_NO_INTRINSICS
