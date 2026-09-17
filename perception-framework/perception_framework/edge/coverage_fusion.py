"""Edge-side fusion of coverage observations from several terminals into one
shared `CoverageEstimator`, plus its capability registration.

implements: AI-S-03, AI-B-04, AI-C-10

A single RPi5-class terminal only ever sees its own camera(s); "is this space
fully covered right now" is answerable only once several terminals'
observations are combined, which is why this fusion — unlike
`perception.detect`/`perception.track` — is naturally an edge-only
capability rather than a local/remote variant a selector picks between.
`CoverageEstimator` (`perception/coverage.py`) already accumulates from
arbitrary `source_id`s; nothing here changes that accumulation logic. This
module only adds the multi-terminal boundary `CoverageEstimator` does not
know about on its own:

* A `source_id` a terminal uses locally (e.g. a camera literally named
  "cam0") is not guaranteed unique across terminals watching the same
  space, so this module qualifies it by `terminal_id` before it ever reaches
  the estimator — a terminal keeps reporting whatever local name it already
  had, and never has to know about the qualification scheme.
* The fused estimator is registered as a `perception.coverage_estimate`
  capability with `required_hw_tags=("edge_node",)`, so a terminal's
  selector only ever finds this provider where multiple cameras' data can
  actually be combined (AI-B-04) — it is never a candidate for on-device
  placement.
* Wiring this registration across the actual network boundary (a terminal
  discovering it) is the transport/gateway layer's job (AI-C-06), already
  solved generically elsewhere — `execution/physical_command_gateway.py`
  shows the same "capability arrives over the wire -> `ProviderRegistration`"
  pattern for physical commands. This module only produces the
  `ProviderRegistration` such a transport-facing service would publish.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from perception_framework.contracts.profile import CompatibilityProfile, ResourceCost
from perception_framework.perception.coverage import (
    REQUIREMENT,
    BlindSpot,
    CoverageElement,
    CoverageEstimator,
    CoverageObservation,
    SourceStatus,
)
from perception_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration

#: The capability kind a terminal asks its selector for when it needs a
#: space-wide (not just its own camera's) coverage/blind-spot view.
CAPABILITY_KIND = "perception.coverage_estimate"


def qualify(terminal_id: str, local_id: str) -> str:
    """Namespaces a terminal-local id so two terminals naming something the
    same way locally (two cameras both called "cam0") do not collide once
    both terminals' reports land in the same estimator.
    """
    return f"{terminal_id}:{local_id}"


@dataclass
class EdgeCoverageFusionService:
    """Combines coverage observations reported by several terminals
    watching one space into a single `CoverageEstimator`.
    """

    estimator: CoverageEstimator = field(default_factory=CoverageEstimator)
    #: Qualified source id -> terminal it came from. Diagnostics/audit only;
    #: fusion itself needs nothing beyond the qualified id being unique.
    terminal_by_source: dict[str, str] = field(default_factory=dict)

    def assign_source(self, region_id: str, terminal_id: str, source_id: str) -> None:
        """Declares that `terminal_id`'s `source_id` (e.g. one of its
        cameras) is responsible for observing `region_id`."""
        qualified = qualify(terminal_id, source_id)
        self.terminal_by_source[qualified] = terminal_id
        self.estimator.assign_source(region_id, qualified)

    def ingest_from_terminal(
        self,
        terminal_id: str,
        region_id: str,
        observation: CoverageObservation,
        available_sources: set[str] | None = None,
    ) -> CoverageElement | None:
        """Folds one terminal's observation in under its qualified source id.

        `observation.source_id`/`observation.observation_id` are read as the
        terminal's own local names and rewritten before reaching the
        estimator. `available_sources`, when given, must already use
        qualified ids — availability at this level is the edge's own view
        across all terminals (AI-C-10), not one terminal's local names.
        """
        qualified_source = qualify(terminal_id, observation.source_id)
        self.terminal_by_source[qualified_source] = terminal_id
        qualified_observation = replace(
            observation,
            observation_id=qualify(terminal_id, observation.observation_id),
            source_id=qualified_source,
        )
        return self.estimator.ingest(region_id, qualified_observation, available_sources)

    # -- read-out, delegated straight to the wrapped estimator -------------

    def coverage(self, region_id: str) -> CoverageElement:
        return self.estimator.coverage(region_id)

    def blind_spots(
        self,
        now: float,
        source_status: dict[str, SourceStatus] | None = None,
        stale_after: float | None = None,
    ) -> list[BlindSpot]:
        kwargs = {} if stale_after is None else {"stale_after": stale_after}
        return self.estimator.blind_spots(now, source_status, **kwargs)

    # -- capability registration (AI-B-04, AI-C-10) -------------------------

    def register(
        self,
        registry: CapabilityRegistry,
        *,
        provider_id: str,
        version: str = "1.0",
        priority: int = 50,
    ) -> ProviderRegistration:
        """Publishes this fused view as a `perception.coverage_estimate`
        provider, placeable only at the edge — a single terminal never has
        enough independent sources of its own to answer "is the space
        covered" (AI-B-04: required tag, never satisfied on-device).
        """
        registration = ProviderRegistration(
            capability_kind=CAPABILITY_KIND,
            provider_id=provider_id,
            version=version,
            compatibility=CompatibilityProfile(
                required_hw_tags=("edge_node",),
                cost=ResourceCost(compute_units=1.0, memory_mb=64.0),
                priority=priority,
            ),
            requirement=REQUIREMENT,
            supported_outputs=("perception.coverage_element", "perception.blind_spot"),
            health_check=lambda: True,
        )
        registry.register_local(registration)
        return registration
