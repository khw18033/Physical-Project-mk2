"""RGR-IOD-style replay candidate contracts without image generation/training.

implements: AI-L-01, AI-L-02, AI-L-04, AI-L-05
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Box:
    x1: float
    y1: float
    x2: float
    y2: float

    def __post_init__(self) -> None:
        if self.x2 <= self.x1 or self.y2 <= self.y1:
            raise ValueError("box must have positive area")


@dataclass(frozen=True)
class PseudoLabel:
    class_name: str
    confidence: float
    box: Box


@dataclass(frozen=True)
class ReplayCandidate:
    candidate_id: str
    task_id: str
    old_prediction: PseudoLabel | None
    new_prediction: PseudoLabel | None


class ReplaySelector:
    """Applies confidence filtering and similarity-based cross sampling."""

    def __init__(self, *, confidence_min: float = 0.7, similarity_min: float = 0.5) -> None:
        if not 0 <= confidence_min <= 1 or not 0 <= similarity_min <= 1:
            raise ValueError("thresholds must be in [0, 1]")
        self.confidence_min = confidence_min
        self.similarity_min = similarity_min

    def select_pseudo_labels(self, labels: tuple[PseudoLabel, ...]) -> tuple[PseudoLabel, ...]:
        """Return stable-order labels that satisfy the declared quality gate."""

        return tuple(label for label in labels if label.confidence >= self.confidence_min)

    def select_scs(self, candidates: tuple[ReplayCandidate, ...]) -> tuple[ReplayCandidate, ...]:
        """Select localized candidates on which old/new classifiers disagree."""

        selected: list[ReplayCandidate] = []
        for candidate in candidates:
            old, new = candidate.old_prediction, candidate.new_prediction
            if old is None or new is None:
                continue
            if min(old.confidence, new.confidence) < self.confidence_min:
                continue
            if old.class_name != new.class_name and _iou(old.box, new.box) >= self.similarity_min:
                selected.append(candidate)
        return tuple(selected)


def _iou(left: Box, right: Box) -> float:
    width = max(0.0, min(left.x2, right.x2) - max(left.x1, right.x1))
    height = max(0.0, min(left.y2, right.y2) - max(left.y1, right.y1))
    intersection = width * height
    left_area = (left.x2 - left.x1) * (left.y2 - left.y1)
    right_area = (right.x2 - right.x1) * (right.y2 - right.y1)
    return intersection / (left_area + right_area - intersection)
