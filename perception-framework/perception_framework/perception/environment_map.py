"""Environment structure estimated from vision and terminal motion data.

implements: AI-E-05, AI-C-02, AI-C-03, AI-C-11

What this produces is an *estimate*, and it is built that way on purpose. The
only quantity available as a known value is the installed pose of a fixed
observation source; everything else — where the floor is traversable, where a
static obstacle stands, which landmark is which — comes out of perception and
terminal motion data and therefore carries uncertainty.

Consequences encoded here:

* Positions are expressed **relative to a declared anchor**, which this module
  references by identifier and never defines. Defining the global frame and
  placing the result in the digital twin belong to the backend (BE-C-04,
  AI-C-02). Without a usable anchor the estimate stays in the observing
  source's own frame and no anchored position is emitted.
* Evidence accumulates onto the same element rather than replacing it, so
  adding an observation source lowers uncertainty instead of restarting the
  estimate.
* A producer that goes away contributes nothing; its absence is not evidence
  against an element that other producers still support (AI-C-11).
* This module answers "what was observed to be there", not "which coordinate
  does it occupy" and not "which area can a camera see" — those are the
  digital-twin side (DT-03, DT-04).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from perception_framework.contracts.capability import CapabilityRequirement, CapabilityState

REQUIREMENT = CapabilityRequirement(
    required=("perception.detect",),
    optional=("perception.segment", "perception.depth", "state.terminal_pose",
              "reference.fixed_source_pose"),
)

#: Uncertainty assigned to an element supported by a single producer, in the
#: unit of the extent it describes. Accumulating independent producers reduces
#: it; it is never reported as zero, because nothing here is a known value.
BASE_UNCERTAINTY = 1.0
MIN_UNCERTAINTY = 0.01


@dataclass(frozen=True)
class Anchor:
    """A reference whose pose is supplied as a known value by the backend.

    Only fixed observation sources qualify. This module stores the identifier
    and the pose it was told, and performs no global transform of its own.
    """

    anchor_id: str
    pose: tuple[float, float, float]
    trusted: bool = True


@dataclass(frozen=True)
class StructureEvidence:
    """One observation supporting an environment element."""

    evidence_id: str
    producer: str            # provenance: which source group produced it
    frame_ref: str           # observation this derives from (AI-C-03)
    observed_at: float
    kind: str                # "traversable" | "obstacle" | "landmark"
    extent: tuple[float, float, float, float]
    confidence: float
    anchor_id: str | None = None   # anchor the extent is expressed against
    frame_id: str = "image"        # frame when unanchored (AI-C-02)


@dataclass(frozen=True)
class MapElement:
    """An estimated environment element and the record of why it is believed."""

    element_id: str
    kind: str
    extent: tuple[float, float, float, float]
    #: Estimated, never a known value. Reported alongside, never folded into,
    #: the producers' confidences.
    uncertainty: float = BASE_UNCERTAINTY
    producers: tuple[str, ...] = ()
    contributions: int = 0
    observed_at: float = 0.0
    anchor_id: str | None = None
    frame_id: str = "image"
    revision: int = 0

    @property
    def anchored(self) -> bool:
        """Whether this element is positioned against a known reference."""
        return self.anchor_id is not None

    @property
    def independent_support(self) -> int:
        return len(self.producers)


def _merge_extent(current, incoming, current_weight: float, incoming_weight: float):
    total = current_weight + incoming_weight or 1.0
    return tuple((c * current_weight + i * incoming_weight) / total
                 for c, i in zip(current, incoming))


def _uncertainty(producers: int, contributions: int) -> float:
    """Falls with independent producers first, repeated looks second.

    Two producers agreeing is worth more than one producer looking twice, so
    the producer count drives the term and contributions only refine it.
    """
    if producers <= 0:
        return BASE_UNCERTAINTY
    value = BASE_UNCERTAINTY / math.sqrt(producers) / math.sqrt(max(1, contributions) ** 0.5)
    return max(MIN_UNCERTAINTY, value)


@dataclass
class EnvironmentMapEstimator:
    """Accumulates structure evidence into a progressively refined estimate."""

    anchors: dict[str, Anchor] = field(default_factory=dict)
    elements: dict[str, MapElement] = field(default_factory=dict)
    _seen: set[str] = field(default_factory=set)
    _producer_hits: dict[str, dict[str, int]] = field(default_factory=dict)

    # -- references -------------------------------------------------------

    def declare_anchor(self, anchor: Anchor) -> None:
        """Register a reference whose pose the backend supplies as known."""
        self.anchors[anchor.anchor_id] = anchor

    def usable_anchor(self, anchor_id: str | None) -> str | None:
        anchor = self.anchors.get(anchor_id) if anchor_id else None
        return anchor.anchor_id if anchor and anchor.trusted else None

    def capability_state(self, available_kinds: set[str]) -> CapabilityState:
        return REQUIREMENT.evaluate(available_kinds)

    # -- accumulation -----------------------------------------------------

    def ingest(self, element_id: str, evidence: StructureEvidence,
               available_producers: set[str] | None = None) -> MapElement | None:
        """Fold one observation into `element_id`.

        `available_producers` comes from the capability registry. Evidence from
        a producer that is no longer available is skipped rather than treated
        as disagreement.
        """
        if available_producers is not None and evidence.producer not in available_producers:
            return None
        if evidence.evidence_id in self._seen:
            return None                       # duplicate delivery
        self._seen.add(evidence.evidence_id)

        anchor_id = self.usable_anchor(evidence.anchor_id)
        current = self.elements.get(element_id)
        hits = self._producer_hits.setdefault(element_id, {})
        hits[evidence.producer] = hits.get(evidence.producer, 0) + 1

        if current is None:
            element = MapElement(
                element_id=element_id, kind=evidence.kind, extent=evidence.extent,
                uncertainty=_uncertainty(1, 1), producers=(evidence.producer,),
                contributions=1, observed_at=evidence.observed_at,
                anchor_id=anchor_id, frame_id=evidence.frame_id, revision=1,
            )
        else:
            producers = tuple(sorted(set(current.producers) | {evidence.producer}))
            contributions = current.contributions + 1
            extent = _merge_extent(current.extent, evidence.extent,
                                   current.contributions, evidence.confidence)
            element = replace(
                current,
                extent=extent,
                uncertainty=_uncertainty(len(producers), contributions),
                producers=producers, contributions=contributions,
                observed_at=max(current.observed_at, evidence.observed_at),
                # An anchor, once available, is kept; losing the anchor source
                # must not silently un-anchor an estimate already built on it.
                anchor_id=current.anchor_id or anchor_id,
                revision=current.revision + 1,
            )
        self.elements[element_id] = element
        return element

    # -- read-out ---------------------------------------------------------

    def anchored_elements(self) -> list[MapElement]:
        """Elements positioned against a known reference.

        Callers that need placement in a shared frame consume only these; the
        rest stay local and are never given an invented absolute position.
        """
        return [e for e in self.elements.values() if e.anchored]

    def local_elements(self) -> list[MapElement]:
        return [e for e in self.elements.values() if not e.anchored]

    def reduced_view(self, available_producers: set[str]) -> list[MapElement]:
        """What the estimate still supports when producers are missing.

        Elements keep standing on the producers that remain. Only an element
        whose entire support has gone away drops out, and it is dropped from
        the view rather than deleted, so it returns when its producer does.
        """
        return [e for e in self.elements.values()
                if set(e.producers) & available_producers]
