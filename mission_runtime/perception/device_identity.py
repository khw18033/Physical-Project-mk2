"""Which *instance* is that robot in the picture?

implements: AI-S-02 (다중 관측 객체 연계), AI-S-04 (확정 label 강제 금지)
관련: AI-S-03 (근거 충분도), AI-S-05 (부족한 근거의 추가 요청), AI-S-06, AI-C-19
tests: tests/test_device_identity.py

## 문제

카메라는 "사족 로봇이 여기 있다"까지만 말한다. 같은 기종이 두 대 있으면 외형은
**개체를 가리지 못한다**. 그런데 명령은 개체에게 보낸다 — `go1-a` 에게 전진을
시켰는데 화면에서 움직인 것이 `go1-b` 였다면, 그 화면은 틀린 것을 보여 준 것이다.

그래서 이 모듈은 단서를 "개체를 가릴 수 있는가"로 **구조적으로** 나눈다. 점수만
합치면 외형 단서 두 개가 식별 단서 하나를 이길 수 있고, 그러면 같은 기종 두 대를
영원히 구분하지 못한다.

    외형 분류    appearance_class      종류만 — 개체 식별력 없음
    선언 배치    declared_placement    "있을 것" — 개체 식별력 없음
    무선 거리    radio_range           개체 id + 거친 거리 — 식별력 있음(약)
    운동 상관    motion_correlation    명령과 움직임의 상관 — 식별력 있음(강)
    기준 마커    fiducial_marker       개체 id 직접 — 식별력 있음(강)

## 판정 규칙 (임계값 하나로 끝내지 않는다)

하나의 track 에 대해:

1. 식별력 있는 단서가 **하나도 없고** 같은 외형의 후보가 둘 이상이면 `AMBIGUOUS` 다.
   이때 점수가 가장 높은 후보를 고르지 않는다 — 고르면 그것은 판단이 아니라 추측이고,
   그 추측이 명령 대상이 된다.
2. 식별력 있는 단서가 **반박**하면(다른 개체를 가리키면) 그 후보는 `CONTRADICTED` 다.
   외형·선언이 아무리 많이 지지해도 뒤집지 못한다.
3. 식별력 있는 단서가 지지하고 반박이 없으면 `CONFIRMED` 다.
4. 후보가 하나뿐이고 식별력 있는 단서가 없으면 `SOLE_CANDIDATE` — 확정이 아니라
   "달리 가능한 것이 없다"는 약한 상태로 남긴다.

## 모호하면 추측하지 않고 **무엇을 더 하면 풀리는지** 낸다

`AMBIGUOUS` 에는 항상 `resolution_requests` 가 붙는다 — 운동 프로브를 돌려라,
마커를 붙여라, 무선 측정을 켜라. 이것이 AI-S-05 의 추가 정보 요청이며, 그 요청의
실제 실행(명령 발급·마커 부착)은 이 모듈의 일이 아니다(AI-C-19).

## 운동 프로브를 1순위 해법으로 두는 이유

마커(ArUco/QR)는 개체를 직접 말해 주지만 **부착이 필요하고** 가려지면 사라진다.
무선 거리는 개체를 알지만 위치가 거칠어 두 대가 가까이 있으면 못 가린다. 운동
상관은 하드웨어 변경이 전혀 필요 없다 — 어차피 보낼 수 있는 명령 하나를 보내고
그 시간창에서 움직인 track 을 보면 된다. 그래서 기본 해법은 운동 프로브이고
마커는 "프로브를 돌릴 수 없는 배치"의 보완책이다.

## 이 모듈이 소유하지 않는 것

최종 "이 track 은 이 장치다" 라는 **권위 있는** 결속은 백엔드·디지털 트윈의 몫이다
(AI-C-19). 여기서 내는 것은 가설과 그 근거이고, 좌표도 로컬 좌표에 한정한다
(AI-C-02).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping, Sequence


class CueKind(str, Enum):
    """단서의 종류. 값이 아니라 **식별력**이 판정을 가른다."""

    APPEARANCE_CLASS = "appearance_class"
    DECLARED_PLACEMENT = "declared_placement"
    RADIO_RANGE = "radio_range"
    MOTION_CORRELATION = "motion_correlation"
    FIDUCIAL_MARKER = "fiducial_marker"


#: 개체를 가릴 수 있는 단서. 이 집합이 이 모듈의 핵심 주장이다 — 외형은 여기에 없다.
DISCRIMINATING_CUES: frozenset[CueKind] = frozenset({
    CueKind.RADIO_RANGE,
    CueKind.MOTION_CORRELATION,
    CueKind.FIDUCIAL_MARKER,
})

#: 단서별 가중치. **데이터다** — 현장에서 비교 실험으로 바꾼다(AI-C-13).
DEFAULT_CUE_WEIGHTS: Mapping[CueKind, float] = {
    CueKind.APPEARANCE_CLASS: 0.15,
    CueKind.DECLARED_PLACEMENT: 0.10,
    CueKind.RADIO_RANGE: 0.45,
    CueKind.MOTION_CORRELATION: 0.90,
    CueKind.FIDUCIAL_MARKER: 0.95,
}


#: 식별력 있는 단서가 이 값 미만이면 "봤지만 못 가렸다"로 본다. **이 모듈의 유일한
#: 선언 자리다** — 판정하는 resolver 와 프로브 결과가 각자 숫자를 적으면 한쪽을 고친
#: 날 두 자리가 서로 다른 답을 내고, 그 어긋남은 시험이 아니라 화면에서 발견된다.
DEFAULT_DISCRIMINATING_MIN_STRENGTH: float = 0.35


class Verdict(str, Enum):
    CONFIRMED = "CONFIRMED"
    SOLE_CANDIDATE = "SOLE_CANDIDATE"
    AMBIGUOUS = "AMBIGUOUS"
    CONTRADICTED = "CONTRADICTED"
    NO_CANDIDATE = "NO_CANDIDATE"


#: 모호할 때 낼 수 있는 해법 요청. 실행은 다른 파트가 한다(AI-C-19).
REQUEST_MOTION_PROBE = "run_motion_probe"
REQUEST_ATTACH_FIDUCIAL = "attach_fiducial_marker"
REQUEST_ENABLE_RADIO_RANGING = "enable_radio_ranging"


@dataclass(frozen=True)
class IdentityCue:
    """한 관측자가 "이 track 은 이 장치다" 라고 말한 근거 1건.

    `strength` 는 그 관측자가 말한 확신이고(0..1), 가중치와 곱해진다. 어디서 왔고
    언제 봤는지를 잃지 않는다 — 근거의 출처 추적은 AI-S-06 의 요구다
    ("각 근거는 생산자, 원본 관측, 생성·완료 시점과 필요한 출처 정보를 추적할 수
    있어야").
    """

    kind: CueKind
    device_id: str
    strength: float
    observed_at: float
    #: 이 단서를 낸 관측자(카메라·무선·프로브). 자유 문자열이다.
    source: str = ""
    #: 이 단서가 **무엇을 보고** 나왔는가 — 원본 관측 참조(프레임·측정 회차·프로브
    #: 시간창). `object_record.Evidence` · `spatial_evidence.SpatialObservation` 과
    #: 같은 이름을 쓴다. 선택이다: 선언 배치처럼 원본 관측이 애초에 없는 단서와, 아직
    #: 참조를 들고 오지 못하는 호출자가 있다. 비어 있으면 **모름**이고, 모름을
    #: 지어내지 않는다.
    frame_ref: str = ""
    detail: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.device_id:
            raise ValueError("device_id must not be empty")
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError(f"strength must be within 0..1, got {self.strength}")

    @property
    def discriminating(self) -> bool:
        return self.kind in DISCRIMINATING_CUES


@dataclass(frozen=True)
class Candidate:
    """한 후보 장치에 대한 집계. 왜 그 점수인지 함께 들고 있다."""

    device_id: str
    score: float
    cues: tuple[IdentityCue, ...]

    @property
    def discriminating_cues(self) -> tuple[IdentityCue, ...]:
        return tuple(cue for cue in self.cues if cue.discriminating)

    def as_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "score": round(self.score, 4),
            "cues": [
                {"kind": cue.kind.value, "strength": cue.strength, "source": cue.source,
                 "frame_ref": cue.frame_ref, "discriminating": cue.discriminating,
                 "detail": dict(cue.detail)}
                for cue in self.cues
            ],
        }


@dataclass(frozen=True)
class IdentityResolution:
    """한 track 의 개체 식별 결과. **가설이고 확정이 아니다**(AI-S-04)."""

    track_id: str
    verdict: Verdict
    device_id: str | None
    reason: str
    candidates: tuple[Candidate, ...] = ()
    resolution_requests: tuple[str, ...] = ()
    #: 식별력 있는 단서들이 서로 다른 장치를 가리킨 경우 그 장치들.
    conflicting_device_ids: tuple[str, ...] = ()

    @property
    def bound(self) -> bool:
        """명령 대상으로 써도 되는가. 확정만 참이다 — 약한 상태를 통과시키지 않는다."""
        return self.verdict is Verdict.CONFIRMED

    def as_dict(self) -> dict:
        return {
            "track_id": self.track_id,
            "verdict": self.verdict.value,
            "device_id": self.device_id,
            "bound": self.bound,
            "reason": self.reason,
            "candidates": [c.as_dict() for c in self.candidates],
            "resolution_requests": list(self.resolution_requests),
            "conflicting_device_ids": list(self.conflicting_device_ids),
        }


@dataclass
class DeviceIdentityResolver:
    """track 하나와 단서들을 받아 개체 가설을 낸다. 상태를 바꾸지 않는다."""

    weights: Mapping[CueKind, float] = field(
        default_factory=lambda: dict(DEFAULT_CUE_WEIGHTS))
    #: 식별력 있는 단서가 이 값 미만이면 "봤지만 못 가렸다"로 보고 식별로 세지 않는다.
    #: 무선 거리처럼 거친 단서가 두 후보에 거의 같은 값을 줄 때가 그 경우다.
    discriminating_min_strength: float = DEFAULT_DISCRIMINATING_MIN_STRENGTH
    #: 두 후보의 최상위 식별 단서 차이가 이 값 이하면 가렸다고 보지 않는다.
    discriminating_margin: float = 0.10

    def resolve(self, track_id: str, cues: Iterable[IdentityCue]) -> IdentityResolution:
        cues = tuple(cues)
        if not cues:
            return IdentityResolution(
                track_id, Verdict.NO_CANDIDATE, None, "no_cue",
                resolution_requests=(REQUEST_MOTION_PROBE, REQUEST_ENABLE_RADIO_RANGING))

        by_device: dict[str, list[IdentityCue]] = {}
        for cue in cues:
            by_device.setdefault(cue.device_id, []).append(cue)

        candidates = tuple(sorted(
            (
                Candidate(
                    device_id=device_id,
                    score=self._score(device_cues),
                    cues=tuple(sorted(device_cues, key=lambda c: (-self._weight(c), c.kind.value))),
                )
                for device_id, device_cues in by_device.items()
            ),
            key=lambda c: (-c.score, c.device_id),  # 동점은 id 순 — 재현 가능해야 한다
        ))

        # 식별력 있는 단서만 따로 본다. 여기서 쓸 만한 것이 있는지가 모든 것을 가른다.
        usable = {
            candidate.device_id: max(
                (cue.strength for cue in candidate.discriminating_cues
                 if cue.strength >= self.discriminating_min_strength),
                default=0.0)
            for candidate in candidates
        }
        supported = sorted(
            (device_id for device_id, strength in usable.items() if strength > 0.0),
            key=lambda device_id: (-usable[device_id], device_id))

        if len(supported) > 1:
            best, second = supported[0], supported[1]
            if usable[best] - usable[second] <= self.discriminating_margin:
                # 식별력 있는 단서가 둘을 거의 같게 가리켰다 — 가린 것이 아니다.
                return IdentityResolution(
                    track_id, Verdict.AMBIGUOUS, None,
                    f"discriminating_cues_too_close:{usable[best]:.2f}/{usable[second]:.2f}",
                    candidates=candidates,
                    resolution_requests=self._requests(cues),
                    conflicting_device_ids=tuple(supported))
            # 뚜렷한 차이가 있으면 약한 쪽은 **반박된 것**이지 무시된 것이 아니다.
            return IdentityResolution(
                track_id, Verdict.CONFIRMED, best,
                f"discriminating_cue_supports:{best}",
                candidates=candidates,
                conflicting_device_ids=tuple(supported[1:]))

        if len(supported) == 1:
            return IdentityResolution(
                track_id, Verdict.CONFIRMED, supported[0],
                f"discriminating_cue_supports:{supported[0]}",
                candidates=candidates)

        # 여기부터는 식별력 있는 단서가 없다.
        if len(candidates) == 1:
            return IdentityResolution(
                track_id, Verdict.SOLE_CANDIDATE, candidates[0].device_id,
                "only_candidate_but_no_discriminating_cue",
                candidates=candidates,
                resolution_requests=self._requests(cues))

        return IdentityResolution(
            track_id, Verdict.AMBIGUOUS, None,
            f"same_appearance_candidates:{len(candidates)}",
            candidates=candidates,
            resolution_requests=self._requests(cues),
            conflicting_device_ids=tuple(c.device_id for c in candidates))

    # -- 내부 ------------------------------------------------------------

    def _weight(self, cue: IdentityCue) -> float:
        return float(self.weights.get(cue.kind, 0.0))

    def _score(self, cues: Sequence[IdentityCue]) -> float:
        """같은 종류의 단서가 여러 번 와도 **합쳐서 1을 넘지 않게** 둔다.

        같은 카메라가 같은 프레임을 두 번 보낸 것이 두 배의 근거가 되면, 중복 관측이
        식별력을 만들어 낸다 — 그것이 바로 피해야 하는 것이다(AI-S-06: 중복·의존
        근거를 구분할 여지를 남긴다).
        """
        best_per_kind: dict[CueKind, float] = {}
        for cue in cues:
            value = self._weight(cue) * cue.strength
            best_per_kind[cue.kind] = max(best_per_kind.get(cue.kind, 0.0), value)
        # 독립적인 종류는 더하되 1.0 에서 포화시킨다.
        total = 0.0
        for value in best_per_kind.values():
            total += value * (1.0 - total)
        return total

    def _requests(self, cues: Sequence[IdentityCue]) -> tuple[str, ...]:
        """무엇을 더 하면 풀리는지. 이미 있는 수단은 다시 요청하지 않는다."""
        have = {cue.kind for cue in cues}
        requests: list[str] = []
        if CueKind.MOTION_CORRELATION not in have:
            requests.append(REQUEST_MOTION_PROBE)
        if CueKind.FIDUCIAL_MARKER not in have:
            requests.append(REQUEST_ATTACH_FIDUCIAL)
        if CueKind.RADIO_RANGE not in have:
            requests.append(REQUEST_ENABLE_RADIO_RANGING)
        return tuple(requests)


# ---------------------------------------------------------------------------
# 단서를 만드는 쪽 — 각 방법이 어떤 단서로 환산되는지 한곳에 모은다
# ---------------------------------------------------------------------------


def appearance_cue(device_ids: Iterable[str], *, observed_at: float, source: str,
                   confidence: float, robot_class: str,
                   frame_ref: str = "") -> tuple[IdentityCue, ...]:
    """외형 분류 결과를 단서로 바꾼다.

    같은 외형 class 를 가진 **모든** 후보에게 같은 단서를 준다. 이것이 외형이
    개체를 가리지 못한다는 사실의 코드상 표현이다 — 한 명에게만 주면 가린 척이 된다.

    한 프레임에서 나온 단서들은 같은 `frame_ref` 를 들고 나간다 — 그래야 아래
    소비자가 "이 셋은 한 번 본 것"임을 셀 수 있다(AI-S-06 의 중복·의존 근거 구분).
    """
    return tuple(
        IdentityCue(CueKind.APPEARANCE_CLASS, device_id, confidence, observed_at,
                    source=source, frame_ref=frame_ref,
                    detail={"robot_class": robot_class})
        for device_id in device_ids
    )


def declared_placement_cue(device_id: str, *, observed_at: float, zone_id: str,
                           frame_ref: str = "") -> IdentityCue:
    """선언된 배치. 가장 약한 근거이고 단독으로는 아무것도 확정하지 못한다.

    선언은 관측이 아니므로 원본 프레임이 없다. 대신 **어느 선언판에서 나왔는지**를
    `frame_ref` 로 받을 수 있다(`spatial_evidence` 가 프로파일 한 판을 하나의 원본으로
    세는 것과 같은 축).
    """
    return IdentityCue(CueKind.DECLARED_PLACEMENT, device_id, 1.0, observed_at,
                       source="zone_profile", frame_ref=frame_ref,
                       detail={"zone_id": zone_id})


def radio_range_cue(device_id: str, *, observed_at: float, measured_m: float,
                    expected_m: float, tolerance_m: float, source: str = "radio",
                    frame_ref: str = "") -> IdentityCue:
    """무선으로 잰 거리와 그 track 까지의 기대 거리를 맞춘 단서.

    `strength` 는 두 거리가 `tolerance_m` 안에서 얼마나 맞는지다. 거리 오차가 허용
    범위를 넘으면 0 이 되고, 그러면 식별로 세어지지 않는다 — 억지로 가리지 않는다.
    """
    error = abs(measured_m - expected_m)
    strength = max(0.0, 1.0 - error / tolerance_m) if tolerance_m > 0 else 0.0
    return IdentityCue(CueKind.RADIO_RANGE, device_id, min(1.0, strength), observed_at,
                       source=source, frame_ref=frame_ref,
                       detail={"measured_m": measured_m, "expected_m": expected_m,
                               "error_m": round(error, 3), "tolerance_m": tolerance_m})


def fiducial_cue(device_id: str, *, observed_at: float, marker_id: str, source: str,
                 pixel_size: float, min_pixel_size: float = 18.0,
                 frame_ref: str = "") -> IdentityCue:
    """ArUco/QR 마커. 개체를 직접 말하지만 **읽을 만큼 커야** 한다.

    너무 작게 찍힌 마커는 오독이 생긴다. 그래서 크기를 확신으로 환산하고, 기준
    미만이면 약한 단서로 떨어뜨려 식별로 세어지지 않게 한다.
    """
    strength = 0.0 if pixel_size <= 0 else min(1.0, pixel_size / max(min_pixel_size, 1.0))
    return IdentityCue(CueKind.FIDUCIAL_MARKER, device_id, strength, observed_at,
                       source=source, frame_ref=frame_ref,
                       detail={"marker_id": marker_id, "pixel_size": pixel_size,
                               "min_pixel_size": min_pixel_size})


@dataclass(frozen=True)
class TrackMotion:
    """프로브 시간창에서 한 track 이 움직인 거리. 로컬 좌표 기준이다(AI-C-02)."""

    track_id: str
    displacement_m: float
    observed_from: float
    observed_to: float


@dataclass(frozen=True)
class ProbeOutcome:
    """운동 프로브 1회의 결과. 가렸으면 그 track, 못 가렸으면 왜 못 가렸는지."""

    device_id: str
    commanded_at: float
    cues: Mapping[str, IdentityCue] = field(default_factory=dict)
    reason: str = ""
    moved_track_ids: tuple[str, ...] = ()
    #: "가렸다"고 볼 최소 세기. 숫자를 여기 베껴 적지 않고 판정하는 쪽
    #: (`DeviceIdentityResolver.discriminating_min_strength`)의 선언을 받아 들고 있다 —
    #: 두 자리가 각자 적으면 한쪽만 바뀐 날 프로브는 가렸다고 하고 resolver 는
    #: 모호하다고 한다.
    min_strength: float = DEFAULT_DISCRIMINATING_MIN_STRENGTH

    @property
    def discriminated(self) -> bool:
        return any(cue.strength >= self.min_strength for cue in self.cues.values())

    def as_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "commanded_at": self.commanded_at,
            "discriminated": self.discriminated,
            "min_strength": self.min_strength,
            "reason": self.reason,
            "moved_track_ids": list(self.moved_track_ids),
            "cues": {track_id: {"strength": cue.strength, "frame_ref": cue.frame_ref,
                                "detail": dict(cue.detail)}
                     for track_id, cue in self.cues.items()},
        }


#: 프로브 사유 어휘.
PROBE_NO_MOTION = "no_track_moved"
PROBE_SEVERAL_MOVED = "several_tracks_moved"
PROBE_WINDOW_MISMATCH = "motion_outside_window"
PROBE_DISCRIMINATED = "single_track_moved"


def motion_probe(
    device_id: str,
    motions: Iterable[TrackMotion],
    *,
    commanded_at: float,
    window_s: float,
    expected_min_m: float,
    margin_m: float,
    source: str = "motion_probe",
    frame_ref: str = "",
    resolver: DeviceIdentityResolver | None = None,
) -> ProbeOutcome:
    """한 장치에게 움직이라고 시킨 뒤 **어느 track 이 움직였는지** 본다.

    왜 이것이 1순위 해법인가: 마커 부착도, 무선 측위 장비도 필요 없다. 이미 보낼 수
    있는 명령 하나를 보내고 그 시간창의 변위를 보면 된다.

    세 가지를 구분해서 돌려준다 — 아무도 안 움직였다(프로브 실패), 여럿이
    움직였다(가리지 못했다), 하나만 움직였다(가렸다). 둘째를 "가장 많이 움직인
    쪽"으로 뭉개면 두 대가 같이 움직이는 상황에서 틀린 결속을 만든다.

    `resolver` 를 주면 "가렸다"의 기준을 **그 resolver 의 선언값**으로 맞춘다. 임계값을
    조정한 배치에서 프로브와 판정이 서로 다른 기준으로 말하지 않게 하는 자리다.
    `frame_ref` 는 이 프로브 회차의 원본 관측 참조이고, 단서에 그대로 실려 나간다
    (AI-S-06).
    """
    min_strength = (DEFAULT_DISCRIMINATING_MIN_STRENGTH if resolver is None
                    else resolver.discriminating_min_strength)
    in_window = [
        motion for motion in motions
        if motion.observed_from >= commanded_at - 1e-9
        and motion.observed_to <= commanded_at + window_s + 1e-9
    ]
    if not in_window:
        return ProbeOutcome(device_id, commanded_at, reason=PROBE_WINDOW_MISMATCH,
                            min_strength=min_strength)

    moved = sorted((m for m in in_window if m.displacement_m >= expected_min_m),
                   key=lambda m: (-m.displacement_m, m.track_id))
    if not moved:
        return ProbeOutcome(device_id, commanded_at, reason=PROBE_NO_MOTION,
                            min_strength=min_strength)

    best = moved[0]
    runner_up = moved[1].displacement_m if len(moved) > 1 else 0.0
    separation = best.displacement_m - runner_up
    if len(moved) > 1 and separation < margin_m:
        # 여럿이 비슷하게 움직였다 — 그중 하나를 고르지 않는다. 약한 단서만 남긴다.
        return ProbeOutcome(
            device_id, commanded_at,
            cues={
                motion.track_id: IdentityCue(
                    CueKind.MOTION_CORRELATION, device_id, 0.0, motion.observed_to,
                    source=source, frame_ref=frame_ref,
                    detail={"displacement_m": motion.displacement_m,
                            "separation_m": round(separation, 3),
                            "margin_m": margin_m, "reason": PROBE_SEVERAL_MOVED})
                for motion in moved
            },
            reason=PROBE_SEVERAL_MOVED,
            moved_track_ids=tuple(m.track_id for m in moved),
            min_strength=min_strength)

    strength = min(1.0, separation / margin_m) if margin_m > 0 else 1.0
    return ProbeOutcome(
        device_id, commanded_at,
        cues={best.track_id: IdentityCue(
            CueKind.MOTION_CORRELATION, device_id, strength, best.observed_to,
            source=source, frame_ref=frame_ref,
            detail={"displacement_m": best.displacement_m,
                    "runner_up_m": runner_up, "separation_m": round(separation, 3),
                    "margin_m": margin_m, "window_s": window_s,
                    "reason": PROBE_DISCRIMINATED})},
        reason=PROBE_DISCRIMINATED,
        moved_track_ids=(best.track_id,),
        min_strength=min_strength)


def expected_range_m(observer_at: tuple[float, float], track_at: tuple[float, float]) -> float:
    """관측자와 track 사이의 로컬 평면 거리. 무선 거리 단서의 기대값이 된다."""
    return math.dist(observer_at, track_at)
