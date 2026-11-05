"""기존 보정이 더 이상 현실을 설명하지 않는 것을 누가 알아채는가.

implements: AI-E-02
관련: AI-O-02 (치명 사건은 요약을 기다리지 않는다), AI-C-05 (신호 부재는 정상),
      AI-S-08 (반복 불일치는 재평가 대상), AI-C-19 (AI 는 사유를 내고 명령을 내지 않는다)
tests: tests/test_calibration_monitor.py

조사 정본은 `docs/research/automatic-camera-calibration.md` §7.2 다. 이 모듈은 그 문서가
**§2 에서 남긴 세 번째 구멍**을 메운다 — 재보정이 **언제** 필요한지를 누가 말하는가.

AI-E-02 는 보정의 절반을 여기 둔다: "새로운 카메라가 등록되거나 해상도·crop·zoom·장착
상태 등 입력 조건이 바뀌거나 **기존 보정의 유효성이 낮아진 경우**".

### 감시(monitoring)와 추적(tracking)은 다른 축이다 — 합치면 둘 다 늦는다

문서 §7.2 가 lidar-카메라 외부 파라미터 감시 문헌(Moravec & Šára, OCAMO / LTO)에서
가져온 구분이 이 모듈의 골격이다. OCAMO 는 작은 decalibration 을 더 잘 잡고, LTO 는
**급격한** decalibration 에 더 빨리 반응한다. 두 성질을 하나의 임계값으로 합치면
느린 drift 를 잡을 만큼 민감한 임계값이 매 프레임 튐에도 울리고, 튐을 무시할 만큼
둔한 임계값은 급변을 놓친다.

그래서 이 모듈의 신호는 **축마다 상태가 따로 있다**:

| 신호 | 축 | 왜 따로인가 |
|---|---|---|
| `anchor_reprojection_drift` | 느림 — N 윈도 **지속** | 한 프레임의 튐으로 재보정을 걸지 않는다 |
| `abrupt_reprojection_jump` | 빠름 — 직전 대비 급변 | 장착 교란 직후 한 프레임으로 울려야 한다 |
| `input_condition_out_of_scope` | 범위 — 품질 저하가 아니다 | 보정이 나빠진 게 아니라 **다른 조건의 보정**이 됐다(§7.1) |
| `known_size_mismeasured` | 스케일 | 알려진 치수가 틀리게 측정되면 보정이 의심된다 |
| `calibration_expired` | 정책 | 문헌 근거가 필요한 항목이 아니다 |
| `no_profile` | 부재 | AI-E-02 의 가장 단순한 사유 |
| `cross_camera_disagreement` | 교차 | **문헌 근거가 아니라 우리 구조다**(아래) |

마지막 줄은 문서 §7.2 가 정직하게 남긴 것을 그대로 옮긴다: 카메라 간 교차 일관성을
보정 유효성 신호로 쓰는 선행 연구를 **찾지 못했다.** 이 신호를 두는 이유는 문헌이
아니라 우리 구조다 — `perception/spatial_evidence.py` 가 이미 여러 출처의 불일치와
leave-one-out 영향도를 계산하므로, 그 불일치가 보정 의심으로 올라올 통로를 공짜로
얻는다. 근거의 출처가 다르다는 사실을 `evidence_basis` 로 신호에 적어 둔다 — 나중에
이 임계값을 조정할 사람이 "이 숫자는 어디서 왔나" 를 물을 때 필요한 정보다.

### 이 모듈은 재보정을 실행하지 않는다

낸다: 사유와 긴급도. 내지 않는다: 카메라 선택, 물리 명령, 보정 실행 시점. 재보정은
운영 흐름(임무·운영자 요청·구역 열기)이 가져가고 이 모듈은 그 흐름의 **입력**이다
(AI-C-19, AI-C-13: 반영은 요청으로만 일어난다). 신호가 비어 있는 것이 정상 상태다.

### 임계값은 문헌에서 그대로 가져오지 않는다

문서 §11 이 적어 둔 그대로다: "재투영 오차 기반이라는 축은 이전 가능하지만 수치
(임계값·윈도 길이)는 그대로 가져오면 안 된다." 그래서 기본값은 전부 생성자 인자이고,
각 기본값 옆에 그것이 **측정값이 아니라 출발점**이라는 표시를 남긴다.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from mission_runtime.edge.calibration_profile import (
    ApplicabilityScope,
    CalibrationProfile,
)
from mission_runtime.edge.calibration_transfer import (
    InputTransform,
    classify_input_change,
)

__all__ = [
    "immediate_signals",
    "RECALIBRATION_SIGNAL_KINDS",
    "SIGNAL_URGENCIES",
    "EVIDENCE_BASES",
    "CalibrationMonitor",
    "RecalibrationSignal",
]

#: 재보정 신호의 종류. **각각이 독립 축이다** — 하나로 합치지 않는다(모듈 docstring).
RECALIBRATION_SIGNAL_KINDS: tuple[str, ...] = (
    "no_profile",
    "calibration_expired",
    "input_condition_out_of_scope",
    "anchor_reprojection_drift",
    "abrupt_reprojection_jump",
    "known_size_mismeasured",
    "cross_camera_disagreement",
)

#: 긴급도. `immediate` 는 일반 metric 요약 주기를 기다리지 않는다(AI-O-02).
SIGNAL_URGENCIES: tuple[str, ...] = ("immediate", "scheduled")

#: 그 신호의 임계값이 **어디서 왔는가**. 문헌과 우리 구조를 구분한다 — 구분하지 않으면
#: 다음 사람이 우리가 정한 숫자를 문헌값으로 읽는다(문서 §7.2 마지막 줄).
EVIDENCE_BASES: tuple[str, ...] = (
    "literature_transferred",  # 축은 문헌에서, 수치는 우리가 정했다
    "project_structure",       # 근거가 문헌이 아니라 우리 구조다
    "operational_policy",      # 운영 정책이고 문헌 근거가 필요하지 않다
    "requirement",             # 요구사항 원문이 직접 정한다
)


@dataclass(frozen=True)
class RecalibrationSignal:
    """"이 보정을 다시 확인해야 한다" 1건. 사유와 근거의 출처를 들고 다닌다."""

    camera_id: str
    kind: str
    urgency: str
    evidence_basis: str
    #: 그 판정을 만든 수치. 비어 있을 수 있다 — 부재(`no_profile`)는 수치가 없다.
    measurements: Mapping[str, float] = field(default_factory=dict)
    detail: str = ""

    def __post_init__(self) -> None:
        if self.kind not in RECALIBRATION_SIGNAL_KINDS:
            raise ValueError(f"unregistered recalibration signal kind {self.kind!r}")
        if self.urgency not in SIGNAL_URGENCIES:
            raise ValueError(f"unregistered urgency {self.urgency!r}")
        if self.evidence_basis not in EVIDENCE_BASES:
            raise ValueError(f"unregistered evidence basis {self.evidence_basis!r}")

    def as_dict(self) -> dict:
        return {
            "camera_id": self.camera_id, "kind": self.kind, "urgency": self.urgency,
            "evidence_basis": self.evidence_basis,
            "measurements": dict(self.measurements), "detail": self.detail,
        }


class CalibrationMonitor:
    """카메라 하나의 보정 유효성 감시. **판정을 내고 재보정을 실행하지 않는다.**

    시계를 읽지 않는다 — `now` 는 언제나 호출자가 준다. 감시기가 스스로 시간을 읽으면
    같은 입력에 다른 신호가 나오고, 그러면 거부 사유를 재현할 수 없다.
    """

    def __init__(
        self,
        camera_id: str,
        *,
        # 느린 축: N 윈도 **지속**. 문서 §7.2 "한 프레임의 튐으로 재보정을 걸지 않는다".
        drift_window: int = 10,
        drift_threshold_px: float = 2.0,
        drift_persistence: int = 7,
        # 빠른 축: 직전 대비 급변. 느린 축과 **다른 임계값**이고 윈도를 공유하지 않는다.
        abrupt_jump_px: float = 6.0,
        # 스케일 축: 알려진 치수의 상대 오차.
        known_size_error_frac: float = 0.15,
        # 교차 축: 두 카메라가 한 객체를 다르게 말하는 거리(m).
        cross_camera_disagreement_m: float = 1.0,
    ) -> None:
        self._camera_id = camera_id
        self._drift_window = drift_window
        self._drift_threshold = drift_threshold_px
        self._drift_persistence = drift_persistence
        self._abrupt_jump = abrupt_jump_px
        self._known_size_error_frac = known_size_error_frac
        self._cross_camera_m = cross_camera_disagreement_m

        self._errors: deque[float] = deque(maxlen=drift_window)
        self._last_error: float | None = None
        self._abrupt: tuple[float, float] | None = None  # (이전, 현재)
        self._size_errors: list[tuple[float, float]] = []  # (기대, 측정)
        self._cross: list[tuple[str, float]] = []          # (상대 카메라, 불일치 m)

    @property
    def camera_id(self) -> str:
        return self._camera_id

    # -- 관측 투입 ----------------------------------------------------------
    def observe_anchor_reprojection(self, error_px: float) -> None:
        """앵커 재투영 오차 1건. 느린 축과 빠른 축이 **같은 관측을 다르게 읽는다.**

        빠른 축은 직전 값과의 차이만 보고 윈도를 보지 않는다 — 장착이 교란된 직후
        한 프레임으로 울려야 하기 때문이다(Moravec 의 LTO 축). 느린 축은 윈도 안의
        **지속**만 보고 한 프레임의 튐을 무시한다(OCAMO 축).
        """
        if not math.isfinite(error_px) or error_px < 0.0:
            raise ValueError(f"observe_anchor_reprojection needs a finite error, got {error_px}")
        if self._last_error is not None and error_px - self._last_error >= self._abrupt_jump:
            self._abrupt = (self._last_error, error_px)
        self._last_error = error_px
        self._errors.append(error_px)

    def note_mount_disturbance(self) -> None:
        """장착이 교란됐다고 **보고받았다**. 오차 이력을 버린다.

        교란 전후의 오차를 같은 윈도에 섞으면 느린 축의 지속 판정이 교란으로 채워지고,
        그러면 교란 뒤의 진짜 drift 를 더 늦게 본다. 교란 자체는 신호가 아니다 —
        신호는 교란 뒤의 관측이 낸다.
        """
        self._errors.clear()
        self._last_error = None
        self._abrupt = None

    def observe_known_size(self, expected_m: float, measured_m: float) -> None:
        """알려진 크기의 물체가 얼마로 측정됐는가(문서 §7.2 의 역방향 사용)."""
        if expected_m <= 0.0:
            raise ValueError(f"observe_known_size needs expected_m > 0, got {expected_m}")
        self._size_errors.append((expected_m, measured_m))

    def observe_cross_camera_disagreement(self, other_camera_id: str, distance_m: float) -> None:
        """두 카메라가 한 객체의 자리를 얼마나 다르게 말했는가.

        **근거가 문헌이 아니라 우리 구조다**(모듈 docstring). 그 사실이 신호의
        `evidence_basis` 에 적혀 나간다.
        """
        if distance_m < 0.0:
            raise ValueError(f"disagreement distance must be >= 0, got {distance_m}")
        self._cross.append((other_camera_id, distance_m))

    def reset_observations(self) -> None:
        """재보정이 실제로 일어난 뒤 이력을 비운다. 신호를 끄는 것과 다르다."""
        self._errors.clear()
        self._last_error = None
        self._abrupt = None
        self._size_errors.clear()
        self._cross.clear()

    # -- 판정 ---------------------------------------------------------------
    def signals(
        self,
        *,
        profile: CalibrationProfile | None,
        current_scope: ApplicabilityScope | None = None,
        input_transform: InputTransform | None = None,
        now: float | None = None,
    ) -> tuple[RecalibrationSignal, ...]:
        """지금 재보정을 요구하는 사유 전부. **빈 묶음이 정상 상태다.**

        축마다 독립이므로 신호가 여러 개 나올 수 있고 그것을 하나로 합치지 않는다 —
        "급변했고 동시에 범위 밖" 은 두 사실이고, 운영자가 고칠 것이 다르다.
        """
        out: list[RecalibrationSignal] = []

        if profile is None or not profile.valid:
            out.append(RecalibrationSignal(
                camera_id=self._camera_id, kind="no_profile", urgency="scheduled",
                evidence_basis="requirement",
                detail="활성 프로파일이 없다 — 영상 좌표 기반 인지를 유지한다(AI-E-02)",
            ))
            # 프로파일이 없으면 그 프로파일의 유효성을 묻는 축들은 **수행되지 않는다.**
            # 없는 보정이 "틀렸다" 고 말하면 사유가 두 번 세어진다.
            return tuple(out)

        if now is not None and profile.valid_until is not None and now > profile.valid_until:
            out.append(RecalibrationSignal(
                camera_id=self._camera_id, kind="calibration_expired", urgency="scheduled",
                evidence_basis="operational_policy",
                measurements={"valid_until": float(profile.valid_until), "now": float(now)},
                detail="보정 기한이 지났다",
            ))

        if current_scope is not None:
            verdict, reasons = classify_input_change(
                profile.applicability, current_scope, input_transform
            )
            if verdict == "requires_reestimation":
                out.append(RecalibrationSignal(
                    camera_id=self._camera_id, kind="input_condition_out_of_scope",
                    urgency="immediate", evidence_basis="requirement",
                    detail=",".join(reasons) or "적용 범위 밖",
                ))

        if self._abrupt is not None:
            previous, current = self._abrupt
            out.append(RecalibrationSignal(
                camera_id=self._camera_id, kind="abrupt_reprojection_jump",
                urgency="immediate", evidence_basis="literature_transferred",
                measurements={
                    "previous_error_px": previous, "current_error_px": current,
                    "jump_px": current - previous, "threshold_px": self._abrupt_jump,
                },
                detail="직전 대비 급변 — 장착 교란 의심(Moravec LTO 축)",
            ))

        exceeding = [e for e in self._errors if e > self._drift_threshold]
        if len(self._errors) >= self._drift_persistence and len(exceeding) >= self._drift_persistence:
            out.append(RecalibrationSignal(
                camera_id=self._camera_id, kind="anchor_reprojection_drift",
                urgency="scheduled", evidence_basis="literature_transferred",
                measurements={
                    "window": float(len(self._errors)),
                    "exceeding": float(len(exceeding)),
                    "mean_error_px": float(sum(self._errors) / len(self._errors)),
                    "threshold_px": self._drift_threshold,
                },
                detail="윈도 안에서 지속적으로 임계 초과(OCAMO 축)",
            ))

        bad_sizes = [
            (expected, measured) for expected, measured in self._size_errors
            if abs(measured - expected) / expected > self._known_size_error_frac
        ]
        if bad_sizes:
            worst = max(bad_sizes, key=lambda pair: abs(pair[1] - pair[0]) / pair[0])
            out.append(RecalibrationSignal(
                camera_id=self._camera_id, kind="known_size_mismeasured",
                urgency="scheduled", evidence_basis="literature_transferred",
                measurements={
                    "expected_m": worst[0], "measured_m": worst[1],
                    "relative_error": abs(worst[1] - worst[0]) / worst[0],
                    "sample_count": float(len(self._size_errors)),
                    "exceeding_count": float(len(bad_sizes)),
                },
                detail="알려진 치수가 틀리게 측정됐다 — 스케일 의심",
            ))

        disagreeing = [
            (other, distance) for other, distance in self._cross
            if distance > self._cross_camera_m
        ]
        if disagreeing:
            worst_cross = max(disagreeing, key=lambda pair: pair[1])
            out.append(RecalibrationSignal(
                camera_id=self._camera_id, kind="cross_camera_disagreement",
                urgency="scheduled", evidence_basis="project_structure",
                measurements={
                    "disagreement_m": worst_cross[1],
                    "threshold_m": self._cross_camera_m,
                    "sample_count": float(len(self._cross)),
                },
                detail=(
                    f"{worst_cross[0]} 와 같은 객체의 자리를 다르게 말한다 — "
                    "이 축의 근거는 문헌이 아니라 우리 구조다(문서 §7.2)"
                ),
            ))

        return tuple(out)

    def due(self, **kwargs) -> bool:
        """신호가 하나라도 있는가. 운영 흐름이 묻는 가장 짧은 형태다."""
        return bool(self.signals(**kwargs))


def immediate_signals(
    signals: Sequence[RecalibrationSignal],
) -> tuple[RecalibrationSignal, ...]:
    """요약 주기를 기다리지 않고 나가야 하는 신호만(AI-O-02)."""
    return tuple(s for s in signals if s.urgency == "immediate")
