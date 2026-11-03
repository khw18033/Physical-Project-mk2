"""Separates model confidence from evidence sufficiency (AI-S-03).

implements: AI-S-03
tests: tests/test_uncertainty.py

A result must never be promoted to a confirmed state just because raw
model confidence is high if the amount of independent evidence backing
it is below what is required (AI-S-03: "충분한 근거가 없는 결과를 확정
상태로 승격해서는 안 된다"). Confidence calibration is applied only when
a calibration provider is actually supplied; otherwise raw confidence
and the evidence-sufficiency flag are reported side by side, uncombined.

## 근거의 수는 출처의 수다

AI-S-03 은 충분도를 단일 confidence 가 아니라 "확보된 관측의 **출처**, 최신성,
일관성, 누락 상태" 로 판정하라고 요구한다. 그래서 세는 단위는 결과의 개수가 아니라
원본 관측이다 — 같은 프레임을 탐지기와 분류기가 각각 읽은 것은 **한 번 본 것**이고,
같은 프레임을 세 번 읽은 것도 한 번 본 것이다. 단위 이름은 새로 짓지 않고
`perception/evidence_kinds.py` 의 것을 그대로 쓴다(`(source_group, frame_ref)` —
`GroundedEvidence.observation_unit`, `_unit_key` 와 같은 어휘).

옛 `evidence_count: int` 경로는 그대로 남지만 **약속이 다르다**: 정수는 출처를
들고 있지 않으므로 중복을 접을 수가 없다. 그 사실을 숨기지 않고
`origin_units_declared=False` 로 드러낸다 — 호출자가 2 라고 말한 것이 서로 다른 두
관측인지 같은 프레임 두 번인지 이 모듈은 알지 못한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Iterable

class EvidenceLevel(str, Enum):
    INSUFFICIENT = "INSUFFICIENT"
    SUFFICIENT = "SUFFICIENT"


@dataclass(frozen=True)
class EvidenceOrigin:
    """근거 1 건이 **어디서 왔는가**. 충분도를 세는 단위다.

    `object_record.Evidence` · `spatial_evidence.SpatialObservation` ·
    `evidence_kinds.GroundedEvidence` 가 모두 이 두 칸을 들고 있어서, 그 셋 중
    무엇이든 그대로 넘길 수 있다(`of()` 가 읽는다).
    """

    source_group: str
    frame_ref: str

    @property
    def observation_unit(self) -> tuple[str, str]:
        """같은 것을 한 번 본 단위. `GroundedEvidence.observation_unit` 과 같은 뜻이다."""
        return (self.source_group, self.frame_ref)

    @classmethod
    def of(cls, item: Any) -> "EvidenceOrigin":
        """근거처럼 생긴 것에서 출처 단위를 읽어 낸다.

        `(source_group, frame_ref)` 쌍, 또는 그 두 칸을 가진 객체를 받는다. 둘 다
        아니면 세는 단위를 알 수 없으므로 **거절한다** — 모르는 채 1 로 세면 중복이
        지지가 된다.
        """
        if isinstance(item, cls):
            return item
        source_group = getattr(item, "source_group", None)
        frame_ref = getattr(item, "frame_ref", None)
        if source_group is not None and frame_ref is not None:
            return cls(str(source_group), str(frame_ref))
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes)) \
                and len(item) == 2:
            return cls(str(item[0]), str(item[1]))
        raise TypeError(
            "evidence origin must be an (source_group, frame_ref) pair or carry "
            f"both attributes; got {item!r}")


@dataclass(frozen=True)
class UncertaintyAssessment:
    raw_confidence: float
    calibrated_confidence: float | None
    evidence_count: int
    evidence_level: EvidenceLevel
    confirmed: bool
    #: 세어진 원본 관측 단위들. 정수 경로에서는 비어 있다.
    counted_units: tuple[tuple[str, str], ...] = ()
    #: 호출자가 출처를 선언했는가. False 면 `evidence_count` 는 호출자가 말한 숫자
    #: 그대로이고 중복이 접혔다는 **보장이 없다**.
    origin_units_declared: bool = False
    #: 같은 원본 관측이라 세지 않은 근거의 수. 정수 경로에서는 언제나 0 이다.
    duplicate_count: int = 0

    def as_dict(self) -> dict:
        return {
            "raw_confidence": self.raw_confidence,
            "calibrated_confidence": self.calibrated_confidence,
            "evidence_count": self.evidence_count,
            "evidence_level": self.evidence_level.value,
            "confirmed": self.confirmed,
            "counted_units": [list(unit) for unit in self.counted_units],
            "origin_units_declared": self.origin_units_declared,
            "duplicate_count": self.duplicate_count,
        }


class UncertaintyEvaluator:
    def __init__(self, *, min_evidence_count: int = 2, confirm_threshold: float = 0.6) -> None:
        self._min_evidence_count = min_evidence_count
        self._confirm_threshold = confirm_threshold

    def evaluate(
        self,
        raw_confidence: float,
        evidence_count: int | None = None,
        calibrate_fn: Callable[[float], float] | None = None,
        *,
        evidence_origins: Iterable[Any] | None = None,
    ) -> UncertaintyAssessment:
        """신뢰도와 근거 충분도를 **따로** 낸다.

        `evidence_origins` 를 주면 같은 원본 관측에서 온 것들이 하나로 접힌 뒤 세어진다
        (AI-S-03 의 "출처"). `evidence_count` 정수를 주면 옛 경로가 그대로 돌지만 그
        숫자는 접히지 않은 채 쓰이고 그 사실이 결과에 남는다.
        """
        if (evidence_count is None) == (evidence_origins is None):
            raise ValueError(
                "declare the evidence exactly once: either evidence_origins "
                "(counted by (source_group, frame_ref)) or the weaker "
                "evidence_count int")

        counted_units: tuple[tuple[str, str], ...] = ()
        duplicates = 0
        if evidence_origins is not None:
            units: list[tuple[str, str]] = []
            for item in evidence_origins:
                unit = EvidenceOrigin.of(item).observation_unit
                if unit in units:
                    # 같은 프레임을 다시 읽은 것은 한 번 본 것이다 — 두 배의 근거가
                    # 아니다(AI-S-06 의 중복·의존 근거 구분과 같은 축).
                    duplicates += 1
                    continue
                units.append(unit)
            counted_units = tuple(units)
            effective_count = len(counted_units)
        else:
            effective_count = int(evidence_count)

        calibrated = calibrate_fn(raw_confidence) if calibrate_fn is not None else None
        effective_confidence = calibrated if calibrated is not None else raw_confidence

        evidence_level = (
            EvidenceLevel.SUFFICIENT if effective_count >= self._min_evidence_count
            else EvidenceLevel.INSUFFICIENT
        )
        confirmed = evidence_level is EvidenceLevel.SUFFICIENT and effective_confidence >= self._confirm_threshold

        return UncertaintyAssessment(
            raw_confidence=raw_confidence,
            calibrated_confidence=calibrated,
            evidence_count=effective_count,
            evidence_level=evidence_level,
            confirmed=confirmed,
            counted_units=counted_units,
            origin_units_declared=evidence_origins is not None,
            duplicate_count=duplicates,
        )
