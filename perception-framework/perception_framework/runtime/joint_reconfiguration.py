"""Reconfiguration driven by evidence sufficiency alongside resources.

implements: AI-B-06, AI-C-13, AI-R-04, AI-S-03, AI-S-05, AI-N-03, AI-C-11

`ResourceAdaptiveReconfigurer` decides from a resource snapshot alone. That is
enough while the only thing changing is headroom, and not enough once the
question is which capabilities are still worth running: the same snapshot can
mean "we have room to spare" and "the judgement we are producing has almost
nothing backing it", and only one of those calls for spending more.

What is borrowed and what is not
--------------------------------
Coordinating several adaptation loops through one objective is established work
(multi-MAPE coordination, utility-based trade-off). That machinery is borrowed,
not invented here. The confidence-driven adaptive-inference line likewise
already raised accuracy to a first-class term in resource decisions.

The one thing that differs is the signal. Those systems read *model
confidence* — a softmax response, a saturation score, a classifier margin —
which is what one model believes about its own output. When a provider
disappears, that number does not move: the surviving model is still confident.
Evidence sufficiency does move, because it counts how many independent
producers back the conclusion. The two therefore disagree in exactly one
situation, and it is the situation this framework was built for:

    providers 3 -> 1
      confidence  0.9 -> 0.9   "confident, skip the expensive check"
      sufficiency 3/3 -> 1/3   "this is precisely when to check"

Whether that difference is worth its cost is an experiment, not an assumption.
A simpler variant — confidence scaled by producer count — may capture the same
effect, and it is included as a baseline for exactly that reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from perception_framework.contracts.profile import ResourceBudget
from perception_framework.runtime.reconfiguration import ResourceSnapshot


@dataclass(frozen=True)
class JudgementState:
    """What the analysis layer currently has to work with.

    Kept separate from `ResourceSnapshot` because these answer different
    questions: one is about headroom, the other about whether the conclusion
    being produced is backed by anything (AI-S-03 keeps confidence and
    sufficiency apart, and this struct preserves that separation).
    """

    #: Highest single-source confidence. What the confidence-driven line reads.
    confidence: float = 0.0
    #: Independent producers currently supporting the conclusion.
    supporting_sources: int = 0
    #: Producers that could support it if all were available.
    expected_sources: int = 1
    #: How much support this deployment requires before a judgement is acted on.
    required_sources: int = 2
    #: Risk level from the analysis layer, when this deployment has one.
    risk_level: float = 0.0
    #: Normalised link quality toward remote providers, when observable.
    link_quality: float | None = None

    @property
    def sufficiency(self) -> float:
        """Fraction of the expected independent support that is present."""
        if self.expected_sources <= 0:
            return 0.0
        return min(1.0, self.supporting_sources / self.expected_sources)

    @property
    def shortfall(self) -> float:
        """How far short of the required support we are. 0 when satisfied."""
        if self.required_sources <= 0:
            return 0.0
        missing = max(0, self.required_sources - self.supporting_sources)
        return missing / self.required_sources


class ControlSignal(Protocol):
    """Turns the current situation into a budget multiplier.

    Above 1.0 asks for more capability than headroom alone would allow;
    below 1.0 gives headroom back. Keeping this a Protocol is what makes the
    comparison honest — every policy under test is swapped in here and sees
    the same snapshots.
    """

    name: str

    def __call__(self, snapshot: ResourceSnapshot, judgement: JudgementState) -> float: ...


@dataclass
class ResourceOnly:
    """Current behaviour: the judgement is not consulted at all."""

    name: str = "resource_only"

    def __call__(self, snapshot: ResourceSnapshot, judgement: JudgementState) -> float:
        return 1.0


@dataclass
class ConfidenceGated:
    """The confidence-driven line, ported: spend more only when unsure.

    Reads what those systems read and nothing else, so that the comparison
    isolates the signal rather than the mechanism.
    """

    name: str = "confidence_gated"
    threshold: float = 0.75
    boost: float = 0.5

    def __call__(self, snapshot: ResourceSnapshot, judgement: JudgementState) -> float:
        if judgement.confidence >= self.threshold:
            return 1.0
        return 1.0 + self.boost * (1.0 - judgement.confidence)


@dataclass
class ConfidenceTimesCount:
    """The simple variant that would make the proposal redundant.

    Included deliberately. If scaling confidence by producer count reproduces
    the effect, the separate sufficiency term is not earning its place.
    """

    name: str = "confidence_x_count"
    threshold: float = 0.75
    boost: float = 0.5

    def __call__(self, snapshot: ResourceSnapshot, judgement: JudgementState) -> float:
        scaled = judgement.confidence * judgement.sufficiency
        if scaled >= self.threshold:
            return 1.0
        return 1.0 + self.boost * (1.0 - scaled)


@dataclass
class SufficiencyAware:
    """The proposal: shortfall in independent support, risk, and link together.

    Weights are parameters, not findings. They are registered before the run
    and the same policy is also evaluated with every weight equal, because a
    result that only appears under hand-picked weights is a tuning artefact
    rather than an effect (this is the standing warning from the utility-based
    adaptation literature).

    Registered weights were 0.6 / 0.3 / 0.1 and equal weights were run as the
    control. The control won — 0.7297 against 0.6486 required-function
    availability on the compound scenario — so equal weighting is the default
    here. Weighting shortfall more heavily than risk and link turned out to
    under-serve the case where all three degrade together, which is the case
    this policy exists for.
    """

    name: str = "sufficiency_aware"
    w_shortfall: float = 1 / 3
    w_risk: float = 1 / 3
    w_link: float = 1 / 3
    #: Cap on how far the budget may be pushed past measured headroom.
    max_boost: float = 1.0

    @classmethod
    def uniform(cls) -> "SufficiencyAware":
        """Kept as a named alias now that equal weights are the default."""
        return cls(name="sufficiency_uniform")

    @classmethod
    def registered(cls) -> "SufficiencyAware":
        """The pre-registered weighting, kept so the comparison stays runnable."""
        return cls(name="sufficiency_registered", w_shortfall=0.6, w_risk=0.3, w_link=0.1)

    def __call__(self, snapshot: ResourceSnapshot, judgement: JudgementState) -> float:
        # Evidence that is already sufficient asks for nothing extra: the point
        # is to stop spending once the requirement is met (AI-C-13, AI-S-05).
        demand = self.w_shortfall * judgement.shortfall
        demand += self.w_risk * judgement.risk_level
        if judgement.link_quality is not None:
            # A failing link makes remote capability worth less, so the demand
            # it creates is for local capability, not for more of everything.
            demand += self.w_link * (1.0 - judgement.link_quality)
        total = self.w_shortfall + self.w_risk + (self.w_link if judgement.link_quality is not None else 0.0)
        if total <= 0:
            return 1.0
        return 1.0 + self.max_boost * min(1.0, demand / total)


@dataclass
class JointReconfigurer:
    """Applies a control signal on top of the measured budget.

    The signal never invents headroom that is not there in absolute terms —
    it reweights how much of the measured capacity this deployment is willing
    to commit, which is the decision AI-B-06 actually asks for ("실행 위치·
    처리주기·구성 수준을 조정").
    """

    signal: ControlSignal
    #: Hard ceiling as a multiple of measured headroom, so a runaway demand
    #: term cannot ask for capacity the node does not have.
    ceiling: float = 2.0
    history: list[tuple[float, float]] = field(default_factory=list)

    def budget_for(self, snapshot: ResourceSnapshot,
                   judgement: JudgementState) -> ResourceBudget:
        base = snapshot.to_budget()
        factor = min(self.ceiling, max(0.0, self.signal(snapshot, judgement)))
        self.history.append((factor, judgement.sufficiency))
        return ResourceBudget(
            compute_units=base.compute_units * factor,
            memory_mb=base.memory_mb * factor,
            max_latency_ms=base.max_latency_ms,
        )


#: Every policy under comparison, in one place so no run can quietly use a
#: different set than another.
POLICIES: dict[str, Callable[[], ControlSignal]] = {
    "resource_only": ResourceOnly,
    "confidence_gated": ConfidenceGated,
    "confidence_x_count": ConfidenceTimesCount,
    "sufficiency_aware": SufficiencyAware,
    "sufficiency_registered": SufficiencyAware.registered,
}
