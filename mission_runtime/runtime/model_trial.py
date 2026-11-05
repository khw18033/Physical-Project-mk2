"""Try a candidate model on chosen frames, and say exactly what the try can prove.

implements: AI-B-09 (운영 후보가 되기 전 검증), AI-L-06 (관리자 판단 정보)
관련: AI-B-01 (구성별 측정과 재측정), AI-C-08 (픽셀은 상태 계약으로 나가지 않는다),
      AI-S-03 (근거 충분도), AI-L-02 (미검증 추론을 정답으로 승격하지 않는다), AI-C-19

운영자가 웹에서 개방어휘 탐지기 여럿을 같은 그림에 돌려 보고 고르는 경로다. 그
경로가 쉽게 틀리는 자리가 셋이라 이 모듈이 그 셋을 막는다.

1. 시도는 측정이 아니다
-----------------------
그림 한 장에 돌린 지연 시간은 **표본 1개**다. 그것이 실행 프로파일의 지연으로
쓰이면 AI-B-01 이 세운 구조가 무너진다 — 그래서 `TrialRun` 은 `MeasurementSet` 을
만들 수 없고, 만들려는 호출에는 **사유를 돌려준다**(아래 `why_not_a_measurement`).
시도는 사람이 눈으로 고르는 재료이고, 배포 판정은 기존 승인 경로를 그대로 지난다.

2. 정답이 없으면 "어느 쪽이 맞나" 를 말할 수 없다
-------------------------------------------------
**이것이 가장 중요하다.** 운영자가 아무 프레임을 골라 두 모델을 돌리면 한쪽이 7개,
다른 쪽이 3개를 찾는다. 화면이 그 수만 보여 주면 사람은 7개를 "더 잘 찾는다" 로
읽는다. 그런데 7개 중 4개가 거짓 양성일 수 있고, **정답이 없는 프레임에서는 그것을
알 길이 없다.** 그래서 비교 결과는 두 종류로 갈린다.

``descriptive``
    정답 없음. 몇 개를 찾았는지·어떤 이름으로·점수 분포가 어떤지·두 모델이 서로
    얼마나 겹치는지만 말한다. **우열을 말하지 않는다.**
``scored``
    그 프레임에 사람이 만든 정답이 있다. 그때만 적중·놓침·거짓 양성을 센다. 정답은
    `tools/fms_console/labeling.py` 의 사람 검수에서 온다 — 즉 **모델 비교가 제대로
    되려면 먼저 사람이 그 프레임을 라벨해야 한다**(AI-L-03). 그 사실이 이 모듈의
    설계이고 우회로를 두지 않았다.

3. 다른 프레임에서 돌린 결과를 견주지 않는다
--------------------------------------------
A 를 1번 그림에, B 를 2번 그림에 돌린 결과를 나란히 두면 그 비교는 아무 뜻이 없다.
`compare()` 가 프레임 집합이 다르면 **사유와 함께 거절한다.**

픽셀은 여기 없다
----------------
`TrialFrame` 은 프레임 참조와 미디어 경로의 위치만 들고 다닌다. 오버레이 그림은
`/api/media` 가 따로 낸다(AI-C-08).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from mission_runtime.contracts.profile import ExecutionConfiguration

#: 비교의 종류. 둘을 한 칸에 담지 않는다 — 담으면 "셌다" 와 "맞혔다" 가 섞인다.
COMPARISON_DESCRIPTIVE = "descriptive_no_ground_truth"
COMPARISON_SCORED = "scored_against_ground_truth"

#: 거절 사유 토큰.
REASON_FRAME_SETS_DIFFER = "trial_frame_sets_differ"
REASON_SINGLE_RUN = "only_one_run_to_compare"
#: **아무것도 돌지 않았다.** 하나 돌린 것과 다른 사실이다 — 둘을 한 토큰으로 적으면
#: 화면이 "하나만 돌렸다" 고 말하는데 실제로는 고른 후보가 전부 세워지지 못한
#: 경우다(그때 알아야 할 것은 후보마다의 사유이고, 그것은 `unavailable[]` 에 있다).
REASON_NO_RUN = "no_run_succeeded"
REASON_NO_GROUND_TRUTH = "no_ground_truth_for_these_frames"
REASON_NOT_A_MEASUREMENT = "trial_is_not_a_measurement"

#: 상자 두 개를 "같은 것을 가리킨다" 로 볼 최소 IoU. 합의 계산에만 쓰이고 판정에는
#: 쓰이지 않는다 — 합의는 설명이고 우열이 아니다.
AGREEMENT_IOU = 0.5


@dataclass(frozen=True)
class TrialFrame:
    """시도에 쓴 그림 하나. **픽셀이 아니라 참조다.**"""

    frame_ref: str
    #: 미디어 경로에서 이 그림을 꺼낼 위치. 상태 계약에는 참조만 실린다(AI-C-08).
    media_ref: str = ""


@dataclass(frozen=True)
class TrialDetection:
    """시도 결과 상자 하나."""

    label: str
    score: float
    box_xyxy: tuple[float, float, float, float]
    frame_ref: str
    #: 그 이름이 **운영자가 준 어휘에서 왔는가**. 프롬프트를 받지 않는 모델의 라벨은
    #: 어휘 일치가 아니므로 거짓이고, 그 차이가 보여야 어휘를 고치는 판단이 선다.
    from_vocabulary: bool = True


@dataclass(frozen=True)
class TrialRun:
    """한 구성을 고른 그림들에 돌린 결과. **측정이 아니다.**"""

    configuration: ExecutionConfiguration
    frames: tuple[TrialFrame, ...]
    detections: tuple[TrialDetection, ...]
    #: 프레임별 실측 처리 시간. 표본 수가 곧 프레임 수다 — 분포를 말할 수 없는 수다.
    latency_ms: tuple[float, ...] = ()
    #: 이 시도를 돌린 사람. 누가 무엇을 보고 골랐는지가 남아야 한다(AI-L-06).
    actor: str = ""
    ran_at: float = 0.0

    @property
    def frame_refs(self) -> tuple[str, ...]:
        return tuple(f.frame_ref for f in self.frames)

    @property
    def sample_count(self) -> int:
        return len(self.latency_ms)

    @property
    def median_latency_ms(self) -> float | None:
        """표본이 없으면 None. **0 이 아니다.**"""
        if not self.latency_ms:
            return None
        ordered = sorted(self.latency_ms)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2.0

    def labels(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for det in self.detections:
            out[det.label] = out.get(det.label, 0) + 1
        return out

    def score_span(self) -> tuple[float, float] | None:
        """점수의 최소·최대. 평균을 내지 않는다 — 한 점수가 전체를 대표하지 않는다."""
        if not self.detections:
            return None
        scores = [d.score for d in self.detections]
        return (min(scores), max(scores))

    def why_not_a_measurement(self) -> str:
        """왜 이 결과가 실행 프로파일의 측정값이 될 수 없는가.

        **메서드로 두는 이유**: 다음 사람이 "시도 결과를 프로파일에 넣는 함수" 를
        찾았을 때 아무것도 없으면 직접 만든다. 여기 사유가 있으면 읽고 그만둔다.
        """
        return (f"{REASON_NOT_A_MEASUREMENT}: 표본 {self.sample_count}개 "
                f"(프레임 {len(self.frames)}장) 로는 지연 분포도 품질도 말할 수 없다. "
                f"AI-B-01 의 측정값은 `ExecutionConfiguration.measure()` 로만 만든다")


@dataclass(frozen=True)
class RunSummary:
    """한 시도의 **설명**. 우열 판정이 없다."""

    configuration_fingerprint: str
    implementation_ref: str
    prompt_ref: str
    #: 후처리 축(점수 하한 등). **이 칸이 없으면 같은 구현의 두 설정이 화면에서
    #: 똑같이 보인다** — 설정을 바꿨을 때의 변화를 보려는 기능인데 바로 그것이
    #: 안 보이게 된다. 실제로 한 번 그랬다.
    postprocess_ref: str
    detection_count: int
    labels: dict[str, int]
    score_span: tuple[float, float] | None
    median_latency_ms: float | None
    latency_sample_count: int
    #: 어휘에서 오지 않은 라벨 수(프롬프트 없는 모델). 0 이면 전부 어휘에서 왔다.
    off_vocabulary_count: int


@dataclass
class TrialComparison:
    """같은 그림에 돌린 시도들을 나란히 둔 것."""

    kind: str
    runs: tuple[RunSummary, ...] = ()
    frame_refs: tuple[str, ...] = ()
    #: 쌍별 상자 합의. 키는 **구성 지문**이다 — 구현 이름으로 키를 잡으면 같은
    #: 구현의 두 설정이 자기 자신과 비교한 것처럼 보인다(실제로 그렇게 나왔다).
    agreement: dict[tuple[str, str], int] = field(default_factory=dict)
    #: 정답이 있을 때만 채워진다. 없으면 빈 사전이고 0 이 아니다.
    scored: dict[str, dict] = field(default_factory=dict)
    reason: str | None = None
    #: 화면이 그대로 읽는 경고. 비교가 말할 수 없는 것을 사람에게 적어 준다.
    caveats: tuple[str, ...] = ()

    @property
    def comparable(self) -> bool:
        return self.reason is None

    def as_payload(self) -> dict:
        return {
            "kind": self.kind,
            "frame_refs": list(self.frame_refs),
            "runs": [
                {"configuration_fingerprint": r.configuration_fingerprint,
                 "implementation_ref": r.implementation_ref,
                 "prompt_ref": r.prompt_ref,
                 "postprocess_ref": r.postprocess_ref,
                 "detection_count": r.detection_count,
                 "labels": dict(sorted(r.labels.items())),
                 "score_span": (None if r.score_span is None
                                else [round(r.score_span[0], 4), round(r.score_span[1], 4)]),
                 "median_latency_ms": (None if r.median_latency_ms is None
                                       else round(r.median_latency_ms, 2)),
                 "latency_sample_count": r.latency_sample_count,
                 "off_vocabulary_count": r.off_vocabulary_count}
                for r in self.runs
            ],
                # 지문 쌍만 내면 운영자가 어느 두 줄인지 못 찾는다. 지문은 `runs[]` 의
            # 같은 칸과 이어지는 열쇠이고, 화면이 그것으로 두 줄을 짚는다.
            "agreement": [{"pair": list(pair), "shared_boxes": count}
                          for pair, count in sorted(self.agreement.items())],
            "scored": self.scored,
            "reason": self.reason,
            "caveats": list(self.caveats),
        }


def summarise(run: TrialRun) -> RunSummary:
    return RunSummary(
        configuration_fingerprint=run.configuration.fingerprint,
        implementation_ref=run.configuration.implementation_ref,
        prompt_ref=run.configuration.prompt_ref,
        postprocess_ref=run.configuration.postprocess_ref,
        detection_count=len(run.detections),
        labels=run.labels(),
        score_span=run.score_span(),
        median_latency_ms=run.median_latency_ms,
        latency_sample_count=run.sample_count,
        off_vocabulary_count=sum(1 for d in run.detections if not d.from_vocabulary),
    )


def compare(runs, *, ground_truth=None) -> TrialComparison:
    """시도들을 견준다. **같은 그림에 돌린 것만.**

    `ground_truth` 는 `{frame_ref: [(label, box_xyxy), ...]}` 다. 주어지면 그
    프레임에 대해서만 적중·놓침·거짓 양성을 세고, 없으면 설명만 낸다 — 정답 없이
    개수를 견주는 것은 비교가 아니라 **숫자 나열**이다.
    """
    runs = list(runs)
    if len(runs) < 2:
        # 0 과 1 은 다른 사실이다. 0 을 "하나만 돌렸다" 로 적으면 고른 후보가 전부
        # 세워지지 못한 경우가 운영 화면에서 "하나만 골랐다" 로 읽힌다.
        return TrialComparison(
            kind=COMPARISON_DESCRIPTIVE,
            reason=(REASON_SINGLE_RUN if runs else REASON_NO_RUN),
            runs=tuple(summarise(r) for r in runs))

    frame_sets = {tuple(sorted(set(r.frame_refs))) for r in runs}
    if len(frame_sets) != 1:
        # 서로 다른 그림에서 나온 수를 나란히 두면 그 비교는 아무 뜻이 없다.
        return TrialComparison(kind=COMPARISON_DESCRIPTIVE,
                               reason=REASON_FRAME_SETS_DIFFER,
                               runs=tuple(summarise(r) for r in runs))

    frames = next(iter(frame_sets))
    summaries = tuple(summarise(r) for r in runs)
    pairs: dict[tuple[str, str], int] = {}
    for i, left in enumerate(runs):
        for right in runs[i + 1:]:
            key = tuple(sorted((left.configuration.fingerprint,
                                right.configuration.fingerprint)))
            pairs[key] = _shared_boxes(left, right)

    covered = [f for f in frames if (ground_truth or {}).get(f)]
    if not covered:
        return TrialComparison(
            kind=COMPARISON_DESCRIPTIVE, runs=summaries, frame_refs=frames,
            agreement=pairs,
            caveats=(
                "정답이 없는 프레임이다 — **더 많이 찾은 쪽이 더 나은 쪽이 아니다.**"
                " 많이 찾은 쪽에 거짓 양성이 섞여 있어도 여기서는 알 수 없다.",
                "우열을 가리려면 그 프레임을 먼저 라벨해야 한다(AI-L-03).",
                f"지연은 프레임 {len(frames)}장 표본이고 실행 프로파일의 지연이 아니다"
                " — 배포 판정은 재측정을 지난다(AI-B-01).",
            ))

    scored = {}
    for summary, run in zip(summaries, runs):
        scored[summary.configuration_fingerprint] = _score(run, ground_truth or {}, covered)
    uncovered = [f for f in frames if f not in covered]
    caveats = [
        f"정답이 있는 프레임 {len(covered)}장에 대해서만 센 값이다.",
        "표본이 적으므로 이 수치는 실행 프로파일의 품질이 아니다(AI-B-01).",
    ]
    if uncovered:
        caveats.append(f"정답이 없어 셈에서 빠진 프레임 {len(uncovered)}장: "
                       + ", ".join(sorted(uncovered)[:5]))
    return TrialComparison(kind=COMPARISON_SCORED, runs=summaries, frame_refs=frames,
                           agreement=pairs, scored=scored, caveats=tuple(caveats))


def _score(run: TrialRun, ground_truth: dict, covered) -> dict:
    """적중·놓침·거짓 양성. **정답이 있는 프레임만** 센다."""
    hit = missed = spurious = 0
    for frame in covered:
        truth = list(ground_truth.get(frame) or ())
        found = [d for d in run.detections if d.frame_ref == frame]
        used = set()
        for index, (label, box) in enumerate(truth):
            match = None
            for candidate in found:
                if id(candidate) in used or candidate.label != label:
                    continue
                if _iou(candidate.box_xyxy, box) >= AGREEMENT_IOU:
                    match = candidate
                    break
            if match is None:
                missed += 1
            else:
                hit += 1
                used.add(id(match))
        spurious += sum(1 for d in found if id(d) not in used)
    total_truth = hit + missed
    return {
        "frames_scored": len(covered),
        "hit": hit, "missed": missed, "spurious": spurious,
        # 정답이 하나도 없으면 비율을 내지 않는다 — 0/0 을 0.0 으로 적으면 "전부
        # 놓쳤다" 로 읽힌다.
        "recall": (None if not total_truth else round(hit / total_truth, 4)),
        "precision": (None if not (hit + spurious) else round(hit / (hit + spurious), 4)),
    }


def _shared_boxes(left: TrialRun, right: TrialRun) -> int:
    """같은 이름·같은 자리를 둘이 함께 잡은 상자 수. 합의는 **설명**이다.

    둘이 합의했다는 것이 둘이 맞았다는 뜻은 아니다 — 같은 오탐을 공유할 수 있고,
    실제로 그 일이 이 프로젝트에서 위치 추정을 깨뜨린 적이 있다.
    """
    used = set()
    shared = 0
    for a in left.detections:
        for b in right.detections:
            if id(b) in used or a.frame_ref != b.frame_ref or a.label != b.label:
                continue
            if _iou(a.box_xyxy, b.box_xyxy) >= AGREEMENT_IOU:
                shared += 1
                used.add(id(b))
                break
    return shared


def _iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union if union > 0 else 0.0
