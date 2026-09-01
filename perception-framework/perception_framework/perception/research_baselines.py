"""Deterministic research-baseline primitives for small-scale validation.

implements: AI-S-04, AI-L-01, AI-L-02, AI-L-05

These functions isolate the observable scoring ideas described by FOMO,
OW-OVD, OWOBJ, and OVTR.  They are dependency-free functional fixtures, not
trained models and not claims of paper-level reproduction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import exp, log, sqrt
from typing import Mapping, Sequence


def _probability(value: float, name: str) -> float:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be in [0, 1]")
    return float(value)


@dataclass(frozen=True)
class FomoAttributeEvidence:
    """FOMO inference evidence: ``p_unknown = p_ood * p_attribute``.

    ``known_probabilities`` are normalized known-class probabilities and
    ``attribute_similarities`` are sigmoid similarities. Attribute generation,
    selection, refinement, and detector training remain outside this fixture.
    """

    known_probabilities: tuple[float, ...]
    attribute_similarities: tuple[float, ...]

    def score(self) -> float:
        if not self.known_probabilities or not self.attribute_similarities:
            raise ValueError("known probabilities and attribute similarities must be non-empty")
        known = tuple(_probability(v, "known probability") for v in self.known_probabilities)
        attributes = tuple(_probability(v, "attribute similarity") for v in self.attribute_similarities)
        return (1.0 - max(known)) * max(attributes)


def _normalize(values: Sequence[float]) -> tuple[float, ...]:
    if not values or any(value < 0 for value in values):
        raise ValueError("distribution must contain non-negative values")
    total = sum(values)
    if total <= 0:
        raise ValueError("distribution must have positive mass")
    return tuple(value / total for value in values)


def jensen_shannon_divergence(left: Sequence[float], right: Sequence[float]) -> float:
    """Jensen-Shannon divergence using natural logarithms."""
    if len(left) != len(right):
        raise ValueError("distributions must have equal length")
    p, q = _normalize(left), _normalize(right)
    midpoint = tuple((a + b) / 2.0 for a, b in zip(p, q, strict=True))

    def kl(source: Sequence[float], target: Sequence[float]) -> float:
        return sum(a * log(a / b) for a, b in zip(source, target, strict=True) if a > 0)

    return (kl(p, midpoint) + kl(q, midpoint)) / 2.0


@dataclass(frozen=True)
class AttributeDistribution:
    name: str
    annotated: tuple[float, ...]
    unannotated: tuple[float, ...]


def select_vsas_attributes(candidates: Sequence[AttributeDistribution], count: int) -> tuple[str, ...]:
    """Dependency-free VSAS core: select attributes with smallest positive/
    negative distribution JSD. The paper's embedding-similarity restriction is
    model-dependent and deliberately not simulated here.
    """
    if count < 0:
        raise ValueError("count must be non-negative")
    ranked = sorted(
        candidates,
        key=lambda item: (jensen_shannon_divergence(item.annotated, item.unannotated), item.name),
    )
    return tuple(item.name for item in ranked[:count])


def hauf_unknown_score(attribute_probability: float, known_probabilities: Sequence[float]) -> float:
    """HAUF inference-core proxy combining attribute, entropy, and OOD evidence.

    The arithmetic mean makes each documented evidence term inspectable. It is
    a validation oracle, not the learned/fitted fusion used for reported mAP.
    """
    attribute = _probability(attribute_probability, "attribute probability")
    known = tuple(_probability(v, "known probability") for v in known_probabilities)
    if len(known) < 2:
        raise ValueError("at least two known-class probabilities are required")
    total = sum(known)
    if total <= 0:
        raise ValueError("known probabilities must have positive mass")
    normalized = tuple(v / total for v in known)
    entropy = -sum(v * log(v) for v in normalized if v > 0) / log(len(normalized))
    ood = 1.0 - max(normalized)
    return (attribute + entropy + ood) / 3.0


def energy_score(logits: Sequence[float], temperature: float = 1.0) -> float:
    """Stable negative log-sum-exp energy used by OWOBJ-style separation."""
    if not logits or temperature <= 0:
        raise ValueError("logits must be non-empty and temperature positive")
    scaled = tuple(value / temperature for value in logits)
    peak = max(scaled)
    return -temperature * (peak + log(sum(exp(value - peak) for value in scaled)))


def energy_margin_loss(known_energy: float, unknown_energy: float, margin: float) -> float:
    """OWOBJ paper's ``max(0, E_unknown - E_known + margin)`` primitive."""
    if margin < 0:
        raise ValueError("margin must be non-negative")
    return max(0.0, unknown_energy - known_energy + margin)


def mahalanobis_objectness(vector: Sequence[float], mean: Sequence[float], variance: Sequence[float]) -> float:
    """Monotonic class-agnostic objectness proxy from diagonal Mahalanobis distance."""
    if not vector or len(vector) != len(mean) or len(vector) != len(variance):
        raise ValueError("vector, mean, and variance must have equal non-zero length")
    if any(value <= 0 for value in variance):
        raise ValueError("variance must be positive")
    distance = sqrt(sum((x - mu) ** 2 / var for x, mu, var in zip(vector, mean, variance, strict=True)))
    return exp(-0.5 * distance * distance)


@dataclass
class CategoryPropagation:
    """OVTR CIP-inspired track-level category evidence accumulator.

    Real OVTR propagates query content/position through a Transformer decoder.
    This model-independent fixture verifies only the externally visible
    invariant: evidence follows a track and is accumulated across frames.
    """

    decay: float = 0.8
    _tracks: dict[int, dict[str, float]] = field(default_factory=dict, init=False)

    def update(self, track_id: int, scores: Mapping[str, float]) -> dict[str, float]:
        if not 0.0 <= self.decay <= 1.0:
            raise ValueError("decay must be in [0, 1]")
        if not scores:
            raise ValueError("scores must be non-empty")
        current = {label: _probability(score, "category score") for label, score in scores.items()}
        previous = self._tracks.get(track_id, {})
        labels = previous.keys() | current.keys()
        combined = {
            label: self.decay * previous.get(label, 0.0) + (1.0 - self.decay) * current.get(label, 0.0)
            for label in labels
        }
        self._tracks[track_id] = combined
        return dict(combined)
