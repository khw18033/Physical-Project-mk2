"""Unknown-object likelihood scoring over open-vocabulary evidence.

implements: AI-S-03, AI-S-04, AI-C-13

Framework boundary notes:

* An open-vocabulary provider (`open_vocabulary.OwlVitPerceptionProvider`)
  already returns *labels* for whatever cleared its own per-vocab threshold,
  but never decides whether a detection is a known object or a novel one —
  that decision belongs here, kept as a separate, swappable policy so no
  single scoring algorithm is hardcoded into the perception pipeline
  (AI-C-13: 교체 가능한 선택 정책; AI-B-01: 다른 구성의 성능을 자동으로 같다고
  가정하지 않는다 — each `policy_id` is measured independently).
* This module has no knowledge of ONNX/OWL-ViT internals beyond the
  `RawVocabScores` shape it consumes; a different open-vocabulary provider
  could feed the same policies as long as it produces that shape.
* Output is a *likelihood*, not a classification. Callers (object record
  resolution, `UnconfirmedCandidateRegistry`) decide what to do with it —
  this module never force-labels anything (AI-S-04).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from perception_framework.perception.research_baselines import (
    FomoAttributeEvidence,
    energy_margin_loss,
    energy_score,
    hauf_unknown_score,
)
from perception_framework.perception.unconfirmed import UnconfirmedCandidateRegistry

if TYPE_CHECKING:
    from perception_framework.perception.open_vocabulary import RawVocabScores

_BOX_TOLERANCE = 1e-4


@dataclass(frozen=True)
class UnknownnessScore:
    """One box's unknown-object likelihood from one policy."""

    box: tuple[float, float, float, float]
    best_known_label: str
    best_known_probability: float
    p_unknown: float
    policy_id: str


def _boxes_match(a: tuple, b: tuple) -> bool:
    if len(a) != len(b):
        return False
    return all(
        abs(x1 - x2) < _BOX_TOLERANCE
        for box_a, box_b in zip(a, b, strict=True)
        for x1, x2 in zip(box_a, box_b, strict=True)
    )


def _require_aligned(known_raw: "RawVocabScores", attribute_raw: "RawVocabScores") -> None:
    """Both raw runs must be `detect_raw()` calls on the *same frame* from the
    *same* OWL-ViT provider family. Box regression there is computed from the
    image tower alone (text-independent — see `RawVocabScores` docstring), so
    matching boxes is the observable proof the two runs are actually aligned;
    a mismatch means the caller passed results from different frames.
    """
    if not _boxes_match(known_raw.boxes, attribute_raw.boxes):
        raise ValueError(
            "known-vocab and attribute-vocab raw scores do not share the same "
            "boxes — they must come from detect_raw() on the same frame"
        )


class UnknownnessPolicy(Protocol):
    """Common interface every unknown-object scoring policy implements."""

    policy_id: str

    def score(
        self, known_raw: "RawVocabScores", attribute_raw: "RawVocabScores"
    ) -> list[UnknownnessScore]: ...

    def is_unknown(self, score: UnknownnessScore) -> bool: ...


@dataclass
class FomoAttributePolicy:
    """FOMO (Zohar et al., CVPR-W 2023-style) policy: p_unknown = (1 - max(known)) * max(attribute).

    `research_baselines.FomoAttributeEvidence` supplies the validated scoring
    primitive (V03); this class is only the adapter that feeds it real
    per-box probability vectors from two aligned `detect_raw()` calls.
    """

    threshold: float = 0.5
    policy_id: str = "fomo_attribute"

    def score(
        self, known_raw: "RawVocabScores", attribute_raw: "RawVocabScores"
    ) -> list[UnknownnessScore]:
        _require_aligned(known_raw, attribute_raw)
        out = []
        for box_i, box in enumerate(known_raw.boxes):
            known_probs = tuple(float(v) for v in known_raw.probs[box_i])
            attribute_probs = tuple(float(v) for v in attribute_raw.probs[box_i])
            p_unknown = FomoAttributeEvidence(known_probs, attribute_probs).score()
            best_i = max(range(len(known_probs)), key=known_probs.__getitem__)
            out.append(
                UnknownnessScore(
                    box=box,
                    best_known_label=known_raw.vocab[best_i],
                    best_known_probability=known_probs[best_i],
                    p_unknown=p_unknown,
                    policy_id=self.policy_id,
                )
            )
        return out

    def is_unknown(self, score: UnknownnessScore) -> bool:
        return score.p_unknown >= self.threshold


@dataclass
class OwOvdHaufPolicy:
    """OW-OVD (Xi et al., CVPR 2025)-style HAUF fusion: mean(attribute, known
    entropy, OOD). Uses the same aligned known/attribute raw scores as
    `FomoAttributePolicy` — the two policies are directly comparable because
    they consume identical inputs (AI-B-01: same-condition comparison).
    """

    threshold: float = 0.5
    policy_id: str = "ow_ovd_hauf"

    def score(
        self, known_raw: "RawVocabScores", attribute_raw: "RawVocabScores"
    ) -> list[UnknownnessScore]:
        _require_aligned(known_raw, attribute_raw)
        out = []
        for box_i, box in enumerate(known_raw.boxes):
            known_probs = tuple(float(v) for v in known_raw.probs[box_i])
            attribute_probs = tuple(float(v) for v in attribute_raw.probs[box_i])
            best_i = max(range(len(known_probs)), key=known_probs.__getitem__)
            p_unknown = hauf_unknown_score(max(attribute_probs), known_probs)
            out.append(
                UnknownnessScore(
                    box=box,
                    best_known_label=known_raw.vocab[best_i],
                    best_known_probability=known_probs[best_i],
                    p_unknown=p_unknown,
                    policy_id=self.policy_id,
                )
            )
        return out

    def is_unknown(self, score: UnknownnessScore) -> bool:
        return score.p_unknown >= self.threshold


@dataclass
class OwobjEnergyPolicy:
    """OWOBJ (Zhang et al., CVPR 2025)-style energy separation.

    OWOBJ's official code/weights are not released (papers/owobj.md §6) —
    there is no authoritative baseline to check this reimplementation
    against. `unknown_likely` here is a monotonic transform of the raw
    negative-log-sum-exp energy over known-class logits (lower energy =
    denser/more known-like region, per the paper's own framing), NOT a
    claim that this reproduces the paper's learned variational objectness
    head or its reported numbers.
    """

    known_energy_reference: float
    margin: float = 1.0
    threshold: float = 0.0
    policy_id: str = "owobj_energy"

    def score(
        self, known_raw: "RawVocabScores", attribute_raw: "RawVocabScores"
    ) -> list[UnknownnessScore]:
        _require_aligned(known_raw, attribute_raw)
        out = []
        for box_i, box in enumerate(known_raw.boxes):
            known_probs = tuple(float(v) for v in known_raw.probs[box_i])
            best_i = max(range(len(known_probs)), key=known_probs.__getitem__)
            box_energy = energy_score(known_probs)
            p_unknown = energy_margin_loss(self.known_energy_reference, box_energy, self.margin)
            out.append(
                UnknownnessScore(
                    box=box,
                    best_known_label=known_raw.vocab[best_i],
                    best_known_probability=known_probs[best_i],
                    p_unknown=p_unknown,
                    policy_id=self.policy_id,
                )
            )
        return out

    def is_unknown(self, score: UnknownnessScore) -> bool:
        return score.p_unknown > self.threshold


# --- glue to the rest of the pipeline (AI-S-04, AI-S-06) --------------------
#
# Neither `object_record.py` nor `collection/session.py` needs to change to
# consume this module's output: `Evidence.label` is already optional and
# `RecordResolver._resolve_class` already skips unlabeled evidence, so
# flagging a box as unknown is expressed as "no label" rather than a new
# branch in the vote-counting logic (AI-C-11: 여기서 무슨 provider가 unknown을
# 계산했는지 object_record.py는 알 필요가 없다).


def to_worker_item(score: UnknownnessScore, policy: UnknownnessPolicy) -> dict:
    """One box's `UnknownnessScore`, shaped as a `collection.session.PerceptionWorker`
    result item. `label` is omitted (None) when the policy calls it unknown —
    that is what keeps `object_record.RecordResolver` from voting a novel
    object onto an existing class (AI-S-04)."""

    is_unknown = policy.is_unknown(score)
    return {
        "kind": "region",
        "region": score.box,
        "confidence": score.best_known_probability,
        "label": None if is_unknown else score.best_known_label,
        "unknown_likelihood": score.p_unknown,
        "unknownness_policy_id": score.policy_id,
    }


def register_unconfirmed_candidates(
    scores: list[UnknownnessScore],
    policy: UnknownnessPolicy,
    registry: UnconfirmedCandidateRegistry,
    *,
    frame_ref: str,
) -> list[str]:
    """Route every box `policy` calls unknown into `registry` as a candidate
    with the closest known label kept only as a zero-shot hint, never a
    confirmed class (AI-S-04). Returns the touched candidate ids."""

    touched: list[str] = []
    for index, score in enumerate(scores):
        if not policy.is_unknown(score):
            continue
        candidate_id = f"{frame_ref}:{index}"
        registry.register_observation(
            candidate_id, {"box": score.box, "frame_ref": frame_ref, "p_unknown": score.p_unknown}
        )
        registry.add_zero_shot_hint(
            candidate_id,
            label=score.best_known_label,
            confidence=score.best_known_probability,
            provider_id=score.policy_id,
        )
        touched.append(candidate_id)
    return touched
