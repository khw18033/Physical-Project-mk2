"""Observation coverage and blind spots, accumulated from what was actually seen.

implements: AI-E-05, AI-C-02, AI-C-10, AI-C-11, AI-S-03

`environment_map.MapElement.kind` answers "무엇이 어디에 있는가" and its
vocabulary — traversable/obstacle/landmark — has no way to say "this area was
never looked at". Coverage is therefore a separate concept accumulated
alongside the map, not another element kind.

Consequences encoded here:

* Observation is **three-valued** — UNOBSERVED → PARTIALLY_OBSERVED →
  OBSERVED. A terminal fills a region progressively as it drives through it,
  so "seen" and "not seen" alone would force a premature verdict.
* A blind spot carries **why** it is blind, because the operator response
  differs: no source assigned, an available source occluded, a source the
  backend reports unusable, and an observation that has simply aged out are
  four different problems (AI-E-05).
* The materials for that verdict — source health, last good observation time —
  are **supplied by the caller**. Final device availability is integrated by
  the backend and consumed here as an input; this module never re-derives it
  (절대 준수 원칙 #15, AI-C-10).
* Coverage elements carry uncertainty like every other estimate. Having
  observed a region and being confident about it are different claims and are
  reported separately (AI-S-03).
* A source going away is not evidence that a region became unobserved. What
  was observed stays observed and its coverage never regresses; ageing is
  expressed as STALE instead, which is a different statement (AI-C-11).
* No global frame is defined. Extents reference an `Anchor` declared elsewhere
  by identifier only. Projecting installed camera FOV into a zone map and
  transforming to global coordinates belong to the digital twin (DT-03,
  DT-04, BE-C-04). DT-04 computes **where a camera could look**; this module
  accumulates **what was actually observed**.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import Enum

from perception_framework.contracts.capability import CapabilityRequirement, CapabilityState
from perception_framework.perception.environment_map import (
    BASE_UNCERTAINTY,
    MIN_UNCERTAINTY,
    Anchor,
)

#: Only an observation source is required. Segmentation, terminal pose and a
#: fixed-source pose sharpen coverage but their absence degrades rather than
#: disables it (AI-C-11).
REQUIREMENT = CapabilityRequirement(
    required=("perception.detect",),
    optional=("perception.segment", "state.terminal_pose",
              "reference.fixed_source_pose"),
)

#: Fraction at or above which a region counts as fully observed. Never 1.0:
#: coverage is estimated from observations, so demanding an exact unit value
#: would make OBSERVED unreachable in practice.
FULL_OBSERVATION = 0.95

#: Default age, in the caller's clock unit, past which the last good
#: observation of a region no longer supports a current verdict.
DEFAULT_STALE_AFTER = 30.0


class ObservationState(str, Enum):
    """How much of a region the accumulated observations account for.

    UNOBSERVED         - nothing has been observed here yet.
    PARTIALLY_OBSERVED - some of the region is accounted for; a terminal
                         moving through fills this up incrementally.
    OBSERVED           - the accumulated fraction reaches FULL_OBSERVATION.
    """

    UNOBSERVED = "UNOBSERVED"
    PARTIALLY_OBSERVED = "PARTIALLY_OBSERVED"
    OBSERVED = "OBSERVED"


class BlindSpotCause(str, Enum):
    """Why a region is not currently backed by a usable observation.

    NO_SOURCE      - no observation source is assigned to this region at all.
    OCCLUDED       - a source covers it but reports the view blocked.
    SOURCE_FAILURE - a source covers it but the backend's integrated verdict
                     says the device is unusable. Consumed, not recomputed.
    STALE          - the last good observation is older than the caller's
                     freshness bound (a region never observed is the limiting
                     case of this, not a separate cause).
    """

    NO_SOURCE = "NO_SOURCE"
    OCCLUDED = "OCCLUDED"
    SOURCE_FAILURE = "SOURCE_FAILURE"
    STALE = "STALE"
    #: Sources are healthy and the reading is current, but the region has
    #: simply not been covered yet. Kept apart from STALE because the two call
    #: for different responses: a stale region needs looking at again, an
    #: incomplete one has never been finished. Collapsing them made every
    #: partially-covered region report as aged-out.
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True)
class SourceStatus:
    """What the caller knows about one observation source, as an input.

    `available` is the backend's already-integrated device availability
    verdict (AI-O-04). This module reads it; it does not derive it from
    transport or observability signals of its own.
    """

    source_id: str
    available: bool = True
    occluded: bool = False
    last_observed_at: float | None = None


@dataclass(frozen=True)
class CoverageObservation:
    """One report that part of a region was actually observed."""

    observation_id: str
    source_id: str            # provenance: which source group observed it
    frame_ref: str            # observation this derives from (AI-C-03)
    observed_at: float
    #: Share of the region this single observation accounts for, in [0, 1].
    #: Overlap between observations is not resolved here — that is geometry,
    #: and geometry against an installed FOV belongs to DT-04.
    observed_fraction: float
    confidence: float
    anchor_id: str | None = None   # anchor the region is expressed against
    frame_id: str = "image"        # frame when unanchored (AI-C-02)


@dataclass(frozen=True)
class CoverageElement:
    """Accumulated observation coverage of one region, and why it is believed."""

    region_id: str
    observed_fraction: float = 0.0
    #: Estimated, never a known value. Reported alongside, never folded into,
    #: the sources' confidences (AI-S-03).
    uncertainty: float = BASE_UNCERTAINTY
    #: Mean reported confidence of the contributing observations. Distinct
    #: from `uncertainty`: how sure the sources were vs. how much the estimate
    #: as a whole can be leaned on.
    confidence: float = 0.0
    sources: tuple[str, ...] = ()
    contributions: int = 0
    last_observed_at: float | None = None
    anchor_id: str | None = None
    frame_id: str = "image"
    revision: int = 0

    @property
    def state(self) -> ObservationState:
        if self.observed_fraction <= 0.0:
            return ObservationState.UNOBSERVED
        if self.observed_fraction >= FULL_OBSERVATION:
            return ObservationState.OBSERVED
        return ObservationState.PARTIALLY_OBSERVED

    @property
    def anchored(self) -> bool:
        """Whether this coverage is expressed against a known reference."""
        return self.anchor_id is not None

    @property
    def independent_support(self) -> int:
        return len(self.sources)

    def is_stale(self, now: float, stale_after: float = DEFAULT_STALE_AFTER) -> bool:
        """Whether the last good observation is too old to stand for `now`.

        A region never observed is stale by the same rule; there is no last
        good observation to lean on.
        """
        if self.last_observed_at is None:
            return True
        return (now - self.last_observed_at) > stale_after


@dataclass(frozen=True)
class BlindSpot:
    """A region without a usable current observation, and the reason why."""

    region_id: str
    cause: BlindSpotCause
    state: ObservationState
    observed_fraction: float
    uncertainty: float
    last_observed_at: float | None
    #: Sources assigned to the region, whatever their present condition.
    sources: tuple[str, ...] = ()


def _uncertainty(sources: int, contributions: int, fraction: float) -> float:
    """Falls with independent sources first, repeated looks second.

    Two sources covering a region is worth more than one source passing twice,
    so the source count drives the term. Partial coverage cannot be as certain
    as full coverage, so the fraction scales the result back up — a thinly
    covered region may therefore exceed BASE_UNCERTAINTY, which is the value
    for a single source having seen all of it, not a ceiling. It is never
    reported as zero: coverage is observed, not known.
    """
    if sources <= 0:
        return BASE_UNCERTAINTY
    value = BASE_UNCERTAINTY / math.sqrt(sources) / math.sqrt(max(1, contributions) ** 0.5)
    value /= max(fraction, MIN_UNCERTAINTY)
    return max(MIN_UNCERTAINTY, value)


@dataclass
class CoverageEstimator:
    """Accumulates observation coverage and reports the gaps that remain."""

    anchors: dict[str, Anchor] = field(default_factory=dict)
    elements: dict[str, CoverageElement] = field(default_factory=dict)
    #: Which sources are nominally responsible for a region. Assignment comes
    #: from deployment configuration; it says nothing about whether the source
    #: is currently usable.
    assignments: dict[str, set[str]] = field(default_factory=dict)
    _seen: set[str] = field(default_factory=set)
    _confidence_sum: dict[str, float] = field(default_factory=dict)

    # -- references -------------------------------------------------------

    def declare_anchor(self, anchor: Anchor) -> None:
        """Register a reference whose pose the backend supplies as known."""
        self.anchors[anchor.anchor_id] = anchor

    def usable_anchor(self, anchor_id: str | None) -> str | None:
        anchor = self.anchors.get(anchor_id) if anchor_id else None
        return anchor.anchor_id if anchor and anchor.trusted else None

    def capability_state(self, available_kinds: set[str]) -> CapabilityState:
        return REQUIREMENT.evaluate(available_kinds)

    # -- configuration ----------------------------------------------------

    def assign_source(self, region_id: str, source_id: str) -> None:
        """Declare that `source_id` is responsible for observing `region_id`.

        Needed to tell NO_SOURCE apart from a source that exists and failed.
        An assignment is never removed on failure — a broken camera is still
        the camera assigned to that region.
        """
        self.assignments.setdefault(region_id, set()).add(source_id)
        self.elements.setdefault(region_id, CoverageElement(region_id=region_id))

    # -- accumulation -----------------------------------------------------

    def ingest(self, region_id: str, observation: CoverageObservation,
               available_sources: set[str] | None = None) -> CoverageElement | None:
        """Fold one observation into the coverage of `region_id`.

        `available_sources` comes from the capability registry. An observation
        from a source that is no longer available is skipped rather than read
        as evidence that the region stopped being observed.
        """
        if available_sources is not None and observation.source_id not in available_sources:
            return None
        if observation.observation_id in self._seen:
            return None                       # duplicate delivery
        self._seen.add(observation.observation_id)

        anchor_id = self.usable_anchor(observation.anchor_id)
        current = self.elements.get(region_id) or CoverageElement(region_id=region_id)

        share = max(0.0, min(1.0, observation.observed_fraction))
        # Monotone by construction: coverage accumulates and is capped, so no
        # later event can walk an already observed region back to UNOBSERVED.
        fraction = min(1.0, current.observed_fraction + share)
        sources = tuple(sorted(set(current.sources) | {observation.source_id}))
        contributions = current.contributions + 1
        conf_sum = self._confidence_sum.get(region_id, 0.0) + observation.confidence
        self._confidence_sum[region_id] = conf_sum

        element = replace(
            current,
            observed_fraction=fraction,
            uncertainty=_uncertainty(len(sources), contributions, fraction),
            confidence=conf_sum / contributions,
            sources=sources,
            contributions=contributions,
            last_observed_at=max(current.last_observed_at or observation.observed_at,
                                 observation.observed_at),
            # An anchor, once available, is kept; losing the anchor source must
            # not silently un-anchor coverage already expressed against it.
            anchor_id=current.anchor_id or anchor_id,
            frame_id=current.frame_id if current.contributions else observation.frame_id,
            revision=current.revision + 1,
        )
        self.elements[region_id] = element
        self.assignments.setdefault(region_id, set()).add(observation.source_id)
        return element

    # -- read-out ---------------------------------------------------------

    def coverage(self, region_id: str) -> CoverageElement:
        """Coverage of a region, including regions nothing has reached yet."""
        return self.elements.get(region_id) or CoverageElement(region_id=region_id)

    def state_of(self, region_id: str) -> ObservationState:
        return self.coverage(region_id).state

    def anchored_regions(self) -> list[CoverageElement]:
        """Coverage expressed against a known reference.

        Callers needing placement in a shared frame consume only these; the
        rest stay local and are never given an invented absolute position.
        """
        return [e for e in self.elements.values() if e.anchored]

    def classify(self, region_id: str, now: float,
                 source_status: dict[str, SourceStatus] | None = None,
                 stale_after: float = DEFAULT_STALE_AFTER) -> BlindSpot | None:
        """Report why `region_id` lacks a usable current observation, or None.

        `source_status` is supplied by the caller and consumed as given —
        availability was already integrated by the backend (AI-C-10).
        """
        status = source_status or {}
        element = self.coverage(region_id)
        assigned = tuple(sorted(self.assignments.get(region_id, set())))
        stale = element.is_stale(now, stale_after)
        covered = element.state is ObservationState.OBSERVED and not stale

        known = [status[s] for s in assigned if s in status]
        usable = [s for s in known if s.available]

        # Cause is decided before "is it covered", because an obstruction that
        # exists now outranks an observation that merely happened earlier: a
        # region fully mapped ten seconds ago is still blind if the only camera
        # looking at it has since failed or been blocked.
        if not assigned:
            if covered:
                return None
            cause = BlindSpotCause.NO_SOURCE
        elif known and not usable:
            # Backend verdict, consumed as given (AI-C-10).
            cause = BlindSpotCause.SOURCE_FAILURE
        elif usable and all(s.occluded for s in usable):
            cause = BlindSpotCause.OCCLUDED
        elif covered:
            return None
        elif stale:
            # There was a usable observation; it has aged past the horizon.
            cause = BlindSpotCause.STALE
        else:
            # Sources are healthy and the reading is current — the region has
            # just never been finished. Reporting this as STALE would send the
            # operator looking for an ageing problem that does not exist.
            cause = BlindSpotCause.INCOMPLETE
        return BlindSpot(
            region_id=region_id, cause=cause, state=element.state,
            observed_fraction=element.observed_fraction,
            uncertainty=element.uncertainty,
            last_observed_at=element.last_observed_at, sources=assigned,
        )

    def blind_spots(self, now: float,
                    source_status: dict[str, SourceStatus] | None = None,
                    stale_after: float = DEFAULT_STALE_AFTER) -> list[BlindSpot]:
        """Every region without a usable current observation, with its cause."""
        found = []
        for region_id in sorted(set(self.elements) | set(self.assignments)):
            spot = self.classify(region_id, now, source_status, stale_after)
            if spot is not None:
                found.append(spot)
        return found

    def reduced_view(self, available_sources: set[str]) -> list[CoverageElement]:
        """What coverage still rests on sources that remain.

        Coverage keeps standing on the sources still present. Only coverage
        whose entire support has gone away drops out of the view, and it is
        dropped from the view rather than deleted, so it returns with its
        source instead of having to be re-observed from nothing.
        """
        return [e for e in self.elements.values()
                if set(e.sources) & available_sources]
