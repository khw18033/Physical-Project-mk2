"""Unconfirmed object candidate management (AI-S-04).

implements: AI-S-04

An object that cannot be confidently classified into an available class
must be kept UNCONFIRMED — never force-mapped onto an existing class
just because no open-vocabulary/VLM model is present (AI-S-04:
"open-vocabulary 모델이나 VLM이 없으면 기존 클래스에 강제 매핑하지
않아야 한다"). Its raw observations must be retained so later analysis
or a human confirmation can still act on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CandidateStatus(str, Enum):
    UNCONFIRMED = "UNCONFIRMED"
    CONFIRMED = "CONFIRMED"


@dataclass
class ZeroShotHint:
    label: str
    confidence: float
    provider_id: str
    prompt: str | None = None


@dataclass
class UnconfirmedCandidate:
    candidate_id: str
    raw_observations: list[dict] = field(default_factory=list)
    status: CandidateStatus = CandidateStatus.UNCONFIRMED
    confirmed_label: str | None = None
    zero_shot_hints: list[ZeroShotHint] = field(default_factory=list)


class UnconfirmedCandidateRegistry:
    def __init__(self) -> None:
        self._candidates: dict[str, UnconfirmedCandidate] = {}

    def register_observation(self, candidate_id: str, observation: dict) -> UnconfirmedCandidate:
        candidate = self._candidates.setdefault(candidate_id, UnconfirmedCandidate(candidate_id))
        candidate.raw_observations.append(observation)
        return candidate

    def confirm(self, candidate_id: str, label: str, *, evidence: dict | None = None) -> UnconfirmedCandidate:
        """Only additional evidence or a user confirmation may promote a
        candidate — never an automatic forced mapping."""
        candidate = self._candidates[candidate_id]
        if evidence is not None:
            candidate.raw_observations.append(evidence)
        candidate.status = CandidateStatus.CONFIRMED
        candidate.confirmed_label = label
        return candidate

    def add_zero_shot_hint(
        self,
        candidate_id: str,
        *,
        label: str,
        confidence: float,
        provider_id: str,
        prompt: str | None = None,
    ) -> UnconfirmedCandidate:
        """Attach an open-vocabulary suggestion without confirming class.

        Zero-shot output is useful for triage and later labeling, but it is
        still a hint. Confirmation remains an explicit separate transition.
        """
        candidate = self._candidates.setdefault(candidate_id, UnconfirmedCandidate(candidate_id))
        candidate.zero_shot_hints.append(ZeroShotHint(label, confidence, provider_id, prompt))
        return candidate

    def get(self, candidate_id: str) -> UnconfirmedCandidate:
        return self._candidates[candidate_id]
