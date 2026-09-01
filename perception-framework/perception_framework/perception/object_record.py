"""Progressive object record construction from heterogeneous evidence.

implements: AI-S-01, AI-S-02, AI-S-03, AI-S-04, AI-C-02, AI-C-03, AI-C-11

This is the element technology behind the digital-twin object state: results
from perception providers that finish at different times are folded into one
persistent record instead of being waited for or overwritten.

Framework boundary notes:

* No concrete model, runtime or camera appears here. Evidence carries only a
  ``source_group`` — an opaque provenance label supplied by whoever registered
  the provider — so adding a model means registering a provider, never editing
  this module (AI-C-04, AI-C-12).
* Resolution is evaluated against the source groups that are *currently
  available*. A source that disappears contributes no evidence; it must not be
  read as evidence against the current state. This is what keeps a capability
  loss from rewriting an object that nothing new was observed about (AI-C-11).
* Confidence and evidence sufficiency are reported separately, never merged
  into a single score (AI-S-03).
* Geometry stays in the frame it was observed in; no global transform is
  performed here (AI-C-02).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

from perception_framework.contracts.capability import CapabilityRequirement, CapabilityState

#: Required/optional dependencies of this capability. Only a spatial evidence
#: source is required; semantic and mask sources merely improve the record,
#: so losing them degrades rather than disables (AI-C-11).
REQUIREMENT = CapabilityRequirement(
    required=("perception.detect",),
    optional=("perception.segment", "perception.classify", "perception.depth"),
)

SPATIAL_CONSISTENCY_THRESHOLD = 0.45
UNKNOWN_CLASS = "unknown"


class Lifecycle(str, Enum):
    """Persistence of an object across successive observations."""

    PROVISIONAL = "provisional"
    CONFIRMED = "confirmed"
    STALE = "stale"
    EXPIRED = "expired"


STALE_AFTER_MISSES = 3
EXPIRE_AFTER_MISSES = 5
CONFIRMING_GROUPS = 2


@dataclass(frozen=True)
class Evidence:
    """One provider result, in the common form every provider is adapted to."""

    evidence_id: str
    frame_ref: str          #原 observation this derives from (AI-C-03)
    source_group: str       # provenance; independent sources support separately
    observed_at: float      # measurement time of the physical state
    available_at: float     # completion time, when this became usable
    kind: str               # "region" | "mask" | "semantic"
    confidence: float
    region: tuple[float, float, float, float] | None = None
    label: str | None = None
    frame_id: str = "image"   # coordinate frame of `region` (AI-C-02)


@dataclass(frozen=True)
class ObjectRecord:
    """Persistent state of one physical object."""

    object_id: str
    revision: int = 0
    geometry: tuple[float, float, float, float] | None = None
    geometry_kind: str = "region"
    frame_id: str = "image"
    semantic_class: str = UNKNOWN_CLASS
    lifecycle: Lifecycle = Lifecycle.PROVISIONAL
    observed_at: float = 0.0
    exposed_at: float = 0.0
    #: Highest single-source confidence — a model-reported number.
    confidence: float = 0.0
    #: How many independent source groups currently back the class, and how
    #: many are available at all. Reported apart from `confidence` because a
    #: confident model and a well-supported conclusion are different things
    #: (AI-S-03).
    supporting_groups: int = 0
    available_groups: int = 0
    capability_state: CapabilityState = CapabilityState.ACTIVE

    def visible_state(self) -> tuple:
        """Fields a consumer reacts to; a confidence-only change is not one."""
        return (self.lifecycle, self.semantic_class, self.geometry_kind,
                _quantize(self.geometry), self.frame_id)

    @property
    def evidence_sufficient(self) -> bool:
        return self.supporting_groups >= CONFIRMING_GROUPS


def _quantize(region: tuple[float, float, float, float] | None, step: float = 0.02):
    if region is None:
        return None
    return tuple(round(v / step) for v in region)


def _iou(a, b) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)
    return inter / union if union > 0 else 0.0


def _weighted_region(items: list[Evidence]):
    total = sum(e.confidence for e in items) or 1.0
    acc = [0.0, 0.0, 0.0, 0.0]
    for e in items:
        for i in range(4):
            acc[i] += e.region[i] * e.confidence
    return tuple(v / total for v in acc)


@dataclass
class RecordResolver:
    """Resolves an object's state from the evidence currently associated.

    `available_groups` is supplied by the caller from the capability registry
    rather than inferred from the evidence itself: the difference between
    "this source said nothing" and "this source is gone" is exactly what
    prevents a capability transition from being mistaken for an observation.
    """

    spatial_threshold: float = SPATIAL_CONSISTENCY_THRESHOLD

    def resolve(self, record: ObjectRecord, evidence: list[Evidence],
                available_groups: set[str] | None = None,
                standing: dict[str, tuple[str, float]] | None = None) -> ObjectRecord:
        usable = [e for e in evidence
                  if available_groups is None or e.source_group in available_groups]
        regions = [e for e in usable if e.kind == "region" and e.region]
        masks = [e for e in usable if e.kind == "mask" and e.region]

        geometry, kind, frame_id = record.geometry, record.geometry_kind, record.frame_id
        admissible = [
            m for m in masks
            if max((_iou(m.region, r.region) for r in regions), default=0.0)
            >= self.spatial_threshold
        ]
        if admissible:
            def family_score(mask: Evidence) -> float:
                per_group: dict[str, float] = {}
                for r in regions:
                    per_group[r.source_group] = max(
                        per_group.get(r.source_group, 0.0), _iou(mask.region, r.region))
                return sum(per_group.values()) / len(per_group) if per_group else 0.0
            best = max(admissible, key=family_score)
            geometry, kind, frame_id = best.region, "mask", best.frame_id
        elif regions:
            geometry, kind, frame_id = _weighted_region(regions), "region", regions[0].frame_id

        semantic, supporting = self._resolve_class(record, usable, standing)

        return replace(
            record,
            geometry=geometry, geometry_kind=kind, frame_id=frame_id,
            semantic_class=semantic,
            observed_at=max((e.observed_at for e in usable), default=record.observed_at),
            confidence=max((e.confidence for e in usable), default=0.0),
            supporting_groups=supporting,
            available_groups=(len(available_groups) if available_groups is not None
                              else len({e.source_group for e in usable})),
        )

    def _resolve_class(self, record: ObjectRecord, usable: list[Evidence],
                       standing: dict[str, tuple[str, float]] | None = None
                       ) -> tuple[str, int]:
        """Resolve the class from each source group's standing position.

        A group's vote is whatever it last said about this object, and it keeps
        standing until that group says something else. This is the difference
        between "not observed" and "contradicted": a group that disappears
        stops producing evidence, but the position it already took does not
        thereby become a vote for the challenger.

        Counting only currently-arriving evidence breaks exactly that. Two
        groups backing `person` and then going away would leave the held class
        with zero counted support, letting a single surviving group flip the
        record with one vote — a state change caused by a source vanishing
        rather than by anything observed (AI-C-11).
        """
        votes: dict[str, tuple[str, float]] = dict(standing or {})
        for e in usable:
            if not e.label:
                continue
            current = votes.get(e.source_group)
            if current is None or e.confidence >= current[1]:
                votes[e.source_group] = (e.label, e.confidence)
        if not votes:
            return record.semantic_class, record.supporting_groups

        support: dict[str, list[float]] = {}
        for label, conf in votes.values():
            support.setdefault(label, []).append(conf)
        best_count = max(len(v) for v in support.values())
        candidate = sorted(
            (c for c, v in support.items() if len(v) == best_count),
            key=lambda c: (-sum(support[c]), c),
        )[0]

        if record.semantic_class == UNKNOWN_CLASS:
            return candidate, best_count
        held = len(support.get(record.semantic_class, []))
        if best_count > held:
            return candidate, best_count
        return record.semantic_class, max(held, 1)


@dataclass
class ProgressiveRecordBuilder:
    """Applies resolution as provider results become available.

    A new revision is emitted only when the visible state changes, so a record
    is available from the first result and refined afterwards instead of
    waiting for the slowest provider.
    """

    resolver: RecordResolver = field(default_factory=RecordResolver)
    records: dict[str, ObjectRecord] = field(default_factory=dict)
    _misses: dict[str, int] = field(default_factory=dict)
    _groups_seen: dict[str, set[str]] = field(default_factory=dict)
    #: Each source group's standing position per object: what it last said.
    #: It survives that group becoming unavailable, which is what keeps a
    #: disappearance from acting as a vote (see RecordResolver._resolve_class).
    _standing: dict[str, dict[str, tuple[str, float]]] = field(default_factory=dict)
    _evidence: dict[str, list[Evidence]] = field(default_factory=dict)

    def capability_state(self, available_kinds: set[str]) -> CapabilityState:
        return REQUIREMENT.evaluate(available_kinds)

    def ingest(self, object_id: str, evidence: Evidence,
               available_groups: set[str] | None = None) -> ObjectRecord | None:
        """Fold one result into `object_id`; returns a new revision or None."""
        buffered = self._evidence.setdefault(object_id, [])
        if any(e.evidence_id == evidence.evidence_id for e in buffered):
            return None                      # duplicate delivery
        buffered.append(evidence)

        previous = self.records.get(object_id, ObjectRecord(object_id=object_id))
        seen = self._groups_seen.setdefault(object_id, set())
        if evidence.kind in ("region", "semantic"):
            seen.add(evidence.source_group)

        standing = self._standing.setdefault(object_id, {})
        resolved = self.resolver.resolve(previous, buffered, available_groups, standing)
        if evidence.label and (available_groups is None
                               or evidence.source_group in available_groups):
            standing[evidence.source_group] = (evidence.label, evidence.confidence)
        resolved = replace(resolved, lifecycle=self._lifecycle(previous, seen,
                                                               available_groups))
        if resolved.visible_state() == previous.visible_state():
            self.records[object_id] = replace(resolved, revision=previous.revision)
            return None
        resolved = replace(resolved, revision=previous.revision + 1,
                           exposed_at=evidence.available_at)
        self.records[object_id] = resolved
        return resolved

    def _lifecycle(self, previous: ObjectRecord, seen: set[str],
                   available_groups: set[str] | None) -> Lifecycle:
        if previous.lifecycle is Lifecycle.EXPIRED:
            return Lifecycle.EXPIRED
        confirming = seen if available_groups is None else seen  # historical support
        if len(confirming) >= CONFIRMING_GROUPS:
            return Lifecycle.CONFIRMED
        # A group that has gone away cannot un-confirm what it already backed.
        return (Lifecycle.CONFIRMED if previous.lifecycle is Lifecycle.CONFIRMED
                else Lifecycle.PROVISIONAL)

    def close_observation(self, seen_object_ids: set[str]) -> list[ObjectRecord]:
        """Age unseen objects and clear the per-observation evidence buffer."""
        aged: list[ObjectRecord] = []
        for object_id, record in list(self.records.items()):
            if object_id in seen_object_ids:
                self._misses[object_id] = 0
                continue
            misses = self._misses.get(object_id, 0) + 1
            self._misses[object_id] = misses
            if misses >= EXPIRE_AFTER_MISSES:
                lifecycle = Lifecycle.EXPIRED
            elif misses >= STALE_AFTER_MISSES:
                lifecycle = Lifecycle.STALE
            else:
                continue
            if lifecycle is not record.lifecycle:
                updated = replace(record, lifecycle=lifecycle,
                                  revision=record.revision + 1)
                self.records[object_id] = updated
                aged.append(updated)
        self._evidence.clear()
        return aged
