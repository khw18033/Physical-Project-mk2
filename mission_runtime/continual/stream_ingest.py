"""Turns a robot's rotation-scan frame stream into learning candidates, and
loads the tuned class parameters that the demo pipeline already uses.

implements: AI-L-09 (운영 데이터 스트림 기반 지속학습 실행)
관련: AI-L-01 (학습 후보 선별), AI-L-02 (격리), AI-C-06 (전송 경계), AI-C-08 (미디어),
      AI-N-02 (외부 구성 적용), AI-B-12 (임무 단위)

이 모듈은 **데모 저장소(`physical_demo`)의 실측 규약을 그대로 받아 적은 것**이다.
그 규약이 현장에서 이미 돌고 있고, 거기에 두 개의 "반드시 지켜야 하는 것"이 있는데
둘 다 틀리면 조용히 잘못된 학습 데이터를 만든다.

    1. `duplicate_of_prev` — 카메라가 얼어붙어도 프레임은 계속 나오고 그림만 멈춘다.
       같은 그림을 여러 방향으로 오해하면 **방향이 통째로 틀어진다.** 그래서 그 표시가
       붙은 프레임이 하나라도 있으면 **판(scan) 전체를 버린다.** 한 장만 빼면 남은
       프레임의 방향 짝이 어긋난 채로 남는다.
    2. `yaw_deg` 는 판마다 기준점이 옮겨지므로 방향에 쓰면 안 된다. 방향은 언제나
       `rotation_deg`(0/45/…/315, 오른쪽=시계)로만 정한다. 이 모듈은 `yaw_deg` 를
       읽지 않으며 시험이 그것을 고정한다.

규약은 로봇이 직전 한 장과만 견주므로 **건너뛴 중복은 못 잡는다.** 그래서 판 안에서
본 digest 를 우리도 직접 모아 본다.

픽셀은 담지 않는다
------------------
프레임 바이트는 미디어 경로의 것이고 학습 후보에는 `frame_ref` 와 특징·유사도만
남는다(AI-C-08). 원본이 필요하면 참조로 되짚는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from mission_runtime.continual.stream_learning import (
    CandidateOrigin,
    InputConditions,
    ParameterSet,
    StreamSample,
    TrainingOutcome,
    CandidateBatch,
)

#: 판을 버린 사유 토큰.
REASON_DUPLICATE_FRAME = "scan_discarded_duplicate_frame"
REASON_REPEATED_DIGEST = "scan_discarded_repeated_digest"
REASON_INCOMPLETE = "scan_discarded_frames_missing"
REASON_NOT_SUCCEEDED = "scan_discarded_outcome_not_succeeded"
REASON_DUPLICATE_ROTATION = "scan_discarded_duplicate_rotation"

SCAN_DISCARD_REASONS: tuple[str, ...] = (
    REASON_DUPLICATE_FRAME,
    REASON_REPEATED_DIGEST,
    REASON_INCOMPLETE,
    REASON_NOT_SUCCEEDED,
    REASON_DUPLICATE_ROTATION,
)

#: 정상 종료된 판만 학습 후보가 된다. 중단된 판은 사진이 모자란다.
OUTCOME_SUCCEEDED = "SUCCEEDED"


@dataclass(frozen=True)
class FrameEnvelope:
    """프레임 1건의 메타. 그림 바이트는 담지 않는다.

    `shot_index` 와 `rotation_deg` 는 로봇이 짝을 맞춰 보내므로 우리가 다시 계산하지
    않는다. `digest` 는 그림의 해시이고 중복 판정에 쓴다.
    """

    device_id: str
    camera_id: str
    scan_id: str
    shot_index: int
    rotation_deg: float
    digest: str | None = None
    duplicate_of_prev: bool = False
    resolution: tuple[int, int] | None = None
    accelerator_id: str | None = None
    received_at: float | None = None

    def __post_init__(self) -> None:
        if not self.device_id or not self.camera_id or not self.scan_id:
            raise ValueError("device_id, camera_id and scan_id must not be empty")
        if self.shot_index < 0:
            raise ValueError("shot_index must not be negative")

    @property
    def conditions(self) -> InputConditions:
        return InputConditions(
            device_id=self.device_id,
            camera_id=self.camera_id,
            resolution=self.resolution,
            accelerator_id=self.accelerator_id,
            extra=(("rotation_deg", f"{self.rotation_deg:g}"),),
        )

    @property
    def frame_ref(self) -> str:
        return f"{self.camera_id}#{self.scan_id}:{self.shot_index}"


@dataclass(frozen=True)
class ScanOutcome:
    """판 경계. `expected_frames` 와 `frames_sent` 를 견주라고 규약이 적어 두었다."""

    scan_id: str
    outcome: str
    expected_frames: int
    frames_sent: int


@dataclass(frozen=True)
class ScanVerdict:
    """판을 학습에 쓸 수 있는가와 그 사유."""

    scan_id: str
    accepted: bool
    reason: str | None = None
    frames: tuple[FrameEnvelope, ...] = ()


@dataclass
class ScanAssembler:
    """판 단위로 프레임을 모으고 규약의 두 함정을 걸러낸다."""

    frames: dict[str, list[FrameEnvelope]] = field(default_factory=dict)

    def add_frame(self, frame: FrameEnvelope) -> None:
        self.frames.setdefault(frame.scan_id, []).append(frame)

    def add_frames(self, frames: Iterable[FrameEnvelope]) -> None:
        for frame in frames:
            self.add_frame(frame)

    def close(self, boundary: ScanOutcome) -> ScanVerdict:
        """판을 닫고 쓸 수 있는지 판정한다. 버린 이유는 사유 토큰으로 남는다."""
        frames = tuple(sorted(self.frames.pop(boundary.scan_id, []),
                              key=lambda f: f.shot_index))

        if boundary.outcome != OUTCOME_SUCCEEDED:
            return ScanVerdict(boundary.scan_id, False, REASON_NOT_SUCCEEDED, frames)
        if len(frames) != boundary.expected_frames or boundary.frames_sent != len(frames):
            return ScanVerdict(boundary.scan_id, False, REASON_INCOMPLETE, frames)
        if any(f.duplicate_of_prev for f in frames):
            # 한 장만 빼지 않는다 — 남은 프레임의 방향 짝이 어긋난 채로 남는다.
            return ScanVerdict(boundary.scan_id, False, REASON_DUPLICATE_FRAME, frames)

        digests = [f.digest for f in frames if f.digest]
        if len(digests) != len(set(digests)):
            # 로봇은 직전 한 장과만 견주므로 건너뛴 중복은 여기서 잡는다.
            return ScanVerdict(boundary.scan_id, False, REASON_REPEATED_DIGEST, frames)

        rotations = [f.rotation_deg for f in frames]
        if len(rotations) != len(set(rotations)):
            return ScanVerdict(boundary.scan_id, False, REASON_DUPLICATE_ROTATION, frames)

        return ScanVerdict(boundary.scan_id, True, None, frames)


@dataclass(frozen=True)
class FrameObservation:
    """한 프레임에서 나온 관측 하나. 학습 후보의 재료다."""

    frame: FrameEnvelope
    label: str
    origin: CandidateOrigin
    feature: tuple[float, ...] = ()
    similarity: float | None = None
    confidence: float | None = None


def candidates_from_scan(
    verdict: ScanVerdict, observations: Sequence[FrameObservation]
) -> tuple[StreamSample, ...]:
    """정상 판의 관측만 학습 후보로 바꾼다.

    버린 판에서는 **아무 후보도 나오지 않는다** — 그 판의 그림이 틀렸을 수 있으므로
    일부만 쓰는 것이 더 위험하다.
    """
    if not verdict.accepted:
        return ()
    kept = {f.frame_ref for f in verdict.frames}
    samples: list[StreamSample] = []
    for index, observation in enumerate(observations):
        if observation.frame.frame_ref not in kept:
            continue
        samples.append(
            StreamSample(
                sample_id=f"{observation.frame.frame_ref}:{index}",
                conditions=observation.frame.conditions,
                label=observation.label,
                feature=observation.feature or (observation.similarity or 0.0,),
                origin=observation.origin,
                frame_ref=observation.frame.frame_ref,
                confidence=observation.confidence,
                similarity=observation.similarity,
                observed_at=observation.frame.received_at,
            )
        )
    return tuple(samples)


# -- 데모가 쓰는 조정된 파라미터를 기준으로 받아들인다 -----------------------

#: 이 파라미터 모양에서 임계 칸의 이름.
THRESHOLD_KEY = "threshold"
#: 프롬프트 칸. **벡터가 아니라 텍스트 프롬프트 목록**이다 — 데모의
#: `class_features.json` 의 `features` 가 그 모양이다.
PROMPTS_KEY = "prompts"
#: 형태·채도·색·비율 게이트. 그대로 실어 두고 해석하지 않는다.
GATES_KEY = "gates"


def parameter_set_from_class_features(
    data: dict, *, conditions: InputConditions, produced_by: str = "curated"
) -> ParameterSet:
    """데모의 클래스 파라미터 파일을 `ParameterSet` 으로 받아들인다.

    그 파일의 `features` 는 **CLIP 텍스트 프롬프트**이고 특징 벡터가 아니다. 벡터인
    척 바꾸지 않고 `prompts` 로 그대로 싣는다 — 모양을 바꾸면 사람이 손으로 조정한
    근거(`*_rationale` 문장들)와 값이 어긋난다.

    게이트는 해석하지 않고 통째로 보존한다. 어떤 게이트가 있는지는 클래스마다 다르고
    이 모듈이 그 목록을 알 필요가 없다.
    """
    parameters: dict[str, dict] = {}
    for label, spec in data.items():
        if label.startswith("_") or not isinstance(spec, dict):
            continue        # `_meta` 같은 머리말은 클래스가 아니다
        prompts = spec.get("features")
        if not isinstance(prompts, list):
            continue
        threshold = spec.get("target_sim_threshold")
        gates = {
            key: value for key, value in spec.items()
            if key != "features" and not key.endswith("_rationale")
            and not key.startswith("rationale")
        }
        parameters[label] = {
            PROMPTS_KEY: list(prompts),
            THRESHOLD_KEY: None if threshold is None else float(threshold),
            GATES_KEY: gates,
        }
    if not parameters:
        raise ValueError("no class entries found in the parameter file")
    return ParameterSet(parameters=parameters, conditions=conditions,
                        produced_by=produced_by)


class ThresholdLearningProvider:
    """확인된 후보의 유사도 분포로 **임계만** 조정한다.

    프롬프트 기반 파이프라인에서 실제로 조정되는 값이 임계다(데모의 임계는 사람이
    sweep 으로 맞춘 것이고, 그 작업을 운영 데이터로 잇는 것이 이 제공자다).
    프롬프트는 바꾸지 않는다 — 프롬프트 변경은 사람이 근거를 적어 바꾸는 일이고
    자동으로 흔들면 조정 근거가 무의미해진다.

    임계는 확인된 표본 유사도의 하위 분위에서 고르고, `floor` 아래로는 내리지
    않는다. 임계가 끝없이 내려가면 아무것도 걸러내지 못한다.
    """

    def __init__(self, *, min_samples: int = 5, quantile: float = 0.05,
                 floor: float = 0.05, max_step: float = 0.05) -> None:
        if min_samples < 1:
            raise ValueError("min_samples must be at least 1")
        if not 0.0 <= quantile <= 1.0:
            raise ValueError("quantile must be between 0 and 1")
        if not 0.0 <= floor <= 1.0:
            raise ValueError("floor must be between 0 and 1")
        if max_step <= 0.0:
            raise ValueError("max_step must be positive")
        self._min_samples = min_samples
        self._quantile = quantile
        self._floor = floor
        self._max_step = max_step

    @property
    def name(self) -> str:
        return (f"threshold(min_samples={self._min_samples},quantile={self._quantile},"
                f"floor={self._floor},max_step={self._max_step})")

    def train(self, batch: CandidateBatch, *, base: ParameterSet | None) -> TrainingOutcome:
        from mission_runtime.continual.stream_learning import (
            REASON_NO_CONFIRMED_SAMPLES,
            REASON_TOO_FEW_SAMPLES,
        )

        if base is None:
            raise ValueError(
                "threshold adaptation needs the current parameters as its base"
            )
        confirmed = [s for s in batch.confirmed() if s.similarity is not None]
        if not confirmed:
            return TrainingOutcome(None, REASON_NO_CONFIRMED_SAMPLES)

        by_label: dict[str, list[float]] = {}
        used: dict[str, list[str]] = {}
        for sample in confirmed:
            by_label.setdefault(sample.label, []).append(float(sample.similarity))
            used.setdefault(sample.label, []).append(sample.sample_id)

        parameters = {label: dict(spec) for label, spec in base.parameters.items()}
        changed: list[str] = []
        for label, scores in sorted(by_label.items()):
            if label not in parameters or len(scores) < self._min_samples:
                continue
            scores.sort()
            target = scores[
                min(len(scores) - 1, int(self._quantile * (len(scores) - 1)))
            ]
            current = parameters[label].get(THRESHOLD_KEY)
            if current is None:
                moved = target
            else:
                # 한 번에 크게 움직이지 않는다 — 표본 한 묶음이 임계를 뒤집으면
                # 운영이 흔들린다.
                delta = max(-self._max_step, min(self._max_step, target - float(current)))
                moved = float(current) + delta
            parameters[label][THRESHOLD_KEY] = round(max(self._floor, moved), 6)
            parameters[label]["sample_count"] = len(scores)
            changed += used[label]

        if not changed:
            return TrainingOutcome(None, REASON_TOO_FEW_SAMPLES)

        return TrainingOutcome(
            ParameterSet(
                parameters=parameters,
                conditions=batch.conditions,
                base_version=base.version,
                sample_ids=tuple(changed),
                produced_by=self.name,
            ),
            used_sample_ids=tuple(changed),
        )
