"""Link-quality driven execution transition on a mobile terminal.

implements: AI-N-03, AI-C-11, AI-C-13

The goal here is not to keep a link alive. Local functions must keep running
when the link is gone, so a failed transition is not a failure. What this
decides is *what to reduce, and when*, before the link is actually lost.

Design choices and why:

* An instantaneous reading is not enough — a moving terminal's signal swings —
  and reacting after the link is gone is already too late. So the decision runs
  on a short history: level plus trend, projected against the time reduction
  itself takes.
* Hysteresis is asymmetric. Reducing early is cheap; returning early is not,
  because a premature return re-enables remote features that are about to fail
  again. Reduction is quick, restoration is conservative.
* No wireless standard, metric name or unit appears here. A provider supplies
  a normalised quality value; whether it came from RSSI, SNR or loss rate is a
  deployment choice (AI-C-12).
* Link quality is reported as its own signal, separate from business transport
  state, observation state and overlay state, because the operator response
  differs (AI-O-04, AI-C-17).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class LinkPosture(str, Enum):
    """What the terminal is currently prepared to rely on."""

    REMOTE_OK = "remote_ok"        # remote-provided optional features usable
    REDUCING = "reducing"          # degradation predicted; shedding remote use
    LOCAL_ONLY = "local_only"      # operating on local capabilities alone


@dataclass(frozen=True)
class LinkSample:
    """One normalised link-quality reading. 1.0 best, 0.0 unusable."""

    at: float
    quality: float
    peer_id: str | None = None


class LinkQualityProvider(Protocol):
    """Supplies readings. The concrete radio and metric live behind this."""

    def sample(self) -> LinkSample: ...
    def candidates(self) -> list[tuple[str, float]]: ...


@dataclass(frozen=True)
class LinkDecision:
    posture: LinkPosture
    changed: bool
    reason: str
    projected_seconds: float | None = None
    switch_to: str | None = None
    quality: float = 0.0
    trend: float = 0.0


@dataclass
class LinkTransitionPolicy:
    """Projects the trend and decides reduction, switching, or restoration."""

    #: Quality at which remote reliance is no longer safe.
    floor: float = 0.25
    #: How long shedding remote reliance takes. Reduction must start at least
    #: this far ahead of the projected floor crossing.
    reduction_lead_seconds: float = 1.5
    #: Asymmetric margins: reduce as soon as it is likely, restore only when
    #: the link is clearly and persistently better.
    restore_margin: float = 0.20
    restore_hold_samples: int = 5
    #: A candidate peer must be better by this much to be worth switching to.
    switch_margin: float = 0.15
    history: int = 8

    _samples: list[LinkSample] = field(default_factory=list)
    _posture: LinkPosture = LinkPosture.REMOTE_OK
    _good_run: int = 0
    #: Reductions that the projection called for but which the link then
    #: disproved. Tracked so the margin can be widened rather than silently
    #: repeating a bad prediction.
    false_reductions: int = 0
    _reduced_at_quality: float | None = None

    @property
    def posture(self) -> LinkPosture:
        return self._posture

    def trend(self) -> float:
        """Quality change per second over the retained history."""
        if len(self._samples) < 2:
            return 0.0
        first, last = self._samples[0], self._samples[-1]
        span = last.at - first.at
        return (last.quality - first.quality) / span if span > 0 else 0.0

    def observe(self, sample: LinkSample,
                candidates: list[tuple[str, float]] | None = None) -> LinkDecision:
        self._samples.append(sample)
        del self._samples[:-self.history]
        slope = self.trend()
        previous = self._posture

        projected = None
        if slope < 0:
            projected = (sample.quality - self.floor) / -slope

        switch_to = None
        for peer, quality in sorted(candidates or [], key=lambda c: -c[1]):
            if peer != sample.peer_id and quality >= sample.quality + self.switch_margin:
                switch_to = peer
                break

        if sample.quality <= self.floor:
            self._enter(LinkPosture.LOCAL_ONLY, sample)
            reason = "quality at or below floor"
        elif projected is not None and projected <= self.reduction_lead_seconds:
            self._enter(LinkPosture.REDUCING, sample)
            reason = "projected to cross floor within reduction lead time"
        elif self._posture is not LinkPosture.REMOTE_OK:
            reason = self._consider_restore(sample)
        else:
            self._good_run += 1
            reason = "stable"

        return LinkDecision(
            posture=self._posture, changed=self._posture is not previous,
            reason=reason, projected_seconds=projected, switch_to=switch_to,
            quality=sample.quality, trend=slope,
        )

    def _enter(self, posture: LinkPosture, sample: LinkSample) -> None:
        if posture is not self._posture:
            self._reduced_at_quality = sample.quality
        self._posture = posture
        self._good_run = 0

    def _consider_restore(self, sample: LinkSample) -> str:
        """Restoration is deliberately slower than reduction."""
        if sample.quality < self.floor + self.restore_margin:
            self._good_run = 0
            return "below restore margin"
        self._good_run += 1
        if self._good_run < self.restore_hold_samples:
            return f"holding ({self._good_run}/{self.restore_hold_samples})"
        if (self._reduced_at_quality is not None
                and sample.quality > self._reduced_at_quality):
            # The link never actually deteriorated the way we projected.
            self.false_reductions += 1
            self.reduction_lead_seconds = max(0.5, self.reduction_lead_seconds * 0.8)
        self._posture = LinkPosture.REMOTE_OK
        self._good_run = 0
        self._reduced_at_quality = None
        return "restored after sustained recovery"

    def status(self) -> dict:
        """Link state as its own signal, not merged with transport or overlay."""
        return {
            "signal": "link_quality",
            "posture": self._posture.value,
            "quality": self._samples[-1].quality if self._samples else None,
            "trend": self.trend(),
            "false_reductions": self.false_reductions,
        }
