"""Provider selection: compatibility filter + minimal-resource + degrade order.

implements: AI-B-01, AI-B-04, AI-B-06, AI-C-13, AI-C-16

Selection never assumes a specific provider exists. When nothing is
compatible with the current node tags/budget, callers get an explicit
`SelectionResult(provider=None, reason=...)` instead of an exception —
a missing optional capability must degrade the caller, not crash it
(AI-C-11; 구현 시 금지 사항: 특정 모델이 없으면 시스템을 시작하지 못하게
만들지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from perception_framework.contracts.capability_contract import TaskIntent
from perception_framework.contracts.profile import CompatibilityProfile, ResourceBudget
from perception_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration

#: Per-candidate outcome vocabulary. Every string a selector attaches to a
#: candidate or to a result is one of these (or one of the `*:`-prefixed
#: forms whose suffix carries data) — registered as the value vocabulary of
#: `contracts/data_dictionary.py::STATE_CHANGE_REASON` so that consumers
#: (가시화, 로그 분석) meet one stable set of words instead of free text.
REASON_SELECTED = "selected"
REASON_COMPATIBLE = "compatible"  # survived every filter, ranked below the winner
REASON_NO_PROVIDER_REGISTERED = "no_provider_registered"
REASON_NO_COMPATIBLE_WITHIN_BUDGET = "no_compatible_provider_within_budget"
REASON_REQUIRED_HW_TAG_MISSING = "required_hw_tag_missing"  # `required_hw_tag_missing:<tags>`
REASON_REQUIRED_RUNTIME_TAG_MISSING = "required_runtime_tag_missing"  # `required_runtime_tag_missing:<tags>`
REASON_OVER_BUDGET = "over_budget"
REASON_DEADLINE_EXCEEDED = "deadline_exceeded"
REASON_INPUT_TOO_STALE = "input_too_stale"
REASON_PROFILE_CONDITIONS_MISMATCH = "execution_profile_conditions_mismatch"
REASON_INSTANCE_UNHEALTHY_OR_EXPIRED = "runtime_instance_unhealthy_or_expired"
REASON_NO_KINDS_GIVEN = "no_capability_kinds_given"


@dataclass(frozen=True)
class CandidateOutcome:
    """What happened to one candidate that was *not* selected.

    `reason` is `REASON_COMPATIBLE` for a candidate that passed every filter
    and simply ranked below the winner, otherwise the filter that removed it.
    """

    provider_id: str
    reason: str


@dataclass(frozen=True)
class SelectionResult:
    """`provider` is the winner or `None`; `reason` says why (for the winner:
    `selected`; otherwise the first/last rejection that decided the outcome).

    `alternatives` lists every other candidate the selector looked at and
    what happened to it. Before 2026-09-17 this was computed and thrown
    away, so a consumer could see *that* a provider was chosen but never
    *over what* — which made the choice a black box to the operator and
    left "왜 안 됨?" unanswerable when `provider` was None (AI-C-13: 선택
    방법을 동일 조건에서 비교할 수 있어야 한다; AI-O-02: 선택 기능 비가용을
    구조화된 사건으로). The winner never appears in `alternatives`. Default
    `()` keeps every pre-existing constructor call valid.
    """

    provider: ProviderRegistration | None
    reason: str
    alternatives: tuple[CandidateOutcome, ...] = ()


def incompatibility_reason(profile: CompatibilityProfile, node_tags: set[str], budget: ResourceBudget) -> str | None:
    """Why `profile.is_compatible(node_tags, budget)` is False, or `None` if
    it is True. Mirrors `is_compatible`'s check order so the first failing
    check is the one reported."""
    missing_hw = [t for t in profile.required_hw_tags if t not in node_tags]
    if missing_hw:
        return f"{REASON_REQUIRED_HW_TAG_MISSING}:{','.join(missing_hw)}"
    missing_rt = [t for t in profile.required_runtime_tags if t not in node_tags]
    if missing_rt:
        return f"{REASON_REQUIRED_RUNTIME_TAG_MISSING}:{','.join(missing_rt)}"
    if not budget.can_afford(profile.cost):
        return REASON_OVER_BUDGET
    return None


class CapabilitySelector:
    """Picks the lowest-cost, highest-priority compatible provider."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        *,
        placement_filter: Callable[[ProviderRegistration], str | None] | None = None,
    ) -> None:
        """`placement_filter` returns `None` for a placeable provider, or a
        reason string for one that must not be placed in this deployment.

        It runs *before* compatibility/budget filtering so a deployment
        boundary — e.g. a closed network refusing a provider that declared
        outbound reach (AI-C-16) — is applied ahead of placement instead of
        surfacing as a runtime failure. The selector never learns what the
        boundary is about; it only passes the reason through.
        """
        self._registry = registry
        self._placement_filter = placement_filter

    def _ranked_candidates(
        self,
        capability_kind: str,
        node_tags: set[str],
        budget: ResourceBudget,
    ) -> tuple[list[ProviderRegistration], str | None, list[CandidateOutcome]]:
        """Shared candidate-gathering path for `select()` and
        `select_for_intent()`: placement filter, then compatibility/budget
        filter, then best-first ordering. Returns `(ranked, None, rejected)`
        on success or `(pending, reason, rejected)` when nothing survives —
        `pending` is only ever empty in the failure case. `rejected` carries
        one `CandidateOutcome` per candidate a filter removed, so the caller
        can report *what was considered*, not only what won.
        """
        rejected: list[CandidateOutcome] = []
        candidates = self._registry.available_providers(capability_kind)
        if not candidates:
            return [], REASON_NO_PROVIDER_REGISTERED, rejected

        if self._placement_filter is not None:
            rejections = {c.provider_id: self._placement_filter(c) for c in candidates}
            rejected.extend(
                CandidateOutcome(pid, reason) for pid, reason in rejections.items() if reason is not None
            )
            permitted = [c for c in candidates if rejections[c.provider_id] is None]
            if not permitted:
                # Only this capability kind loses its candidates; unrelated
                # kinds are untouched (AI-C-11, AI-C-16).
                first_reason = next(r for r in rejections.values() if r is not None)
                return [], first_reason, rejected
            candidates = permitted

        compatible: list[ProviderRegistration] = []
        for c in candidates:
            why_not = incompatibility_reason(c.compatibility, node_tags, budget)
            if why_not is None:
                compatible.append(c)
            else:
                rejected.append(CandidateOutcome(c.provider_id, why_not))
        if not compatible:
            return [], REASON_NO_COMPATIBLE_WITHIN_BUDGET, rejected

        # Lower priority number wins; then the provider whose *preferred*
        # resources this node actually has (AI-B-04 — preference ranks,
        # it never excludes); then lowest compute cost so resource usage
        # stays minimal by default (AI-C-13, 절대 준수 원칙 #5).
        ranked = sorted(
            compatible,
            key=lambda c: (
                c.compatibility.priority,
                c.compatibility.preference_penalty(node_tags),
                c.compatibility.cost.compute_units,
            ),
        )
        return ranked, None, rejected

    @staticmethod
    def _runners_up(ranked: list[ProviderRegistration], winner_index: int) -> list[CandidateOutcome]:
        """Candidates that passed every filter but were not chosen: those
        ranked below the winner are `compatible`; those ranked *above* it
        were skipped by a later per-candidate check and are reported by the
        caller with that check's reason, so they are excluded here."""
        return [CandidateOutcome(c.provider_id, REASON_COMPATIBLE) for c in ranked[winner_index + 1 :]]

    def select(
        self,
        capability_kind: str,
        node_tags: set[str],
        budget: ResourceBudget,
    ) -> SelectionResult:
        ranked, failure_reason, rejected = self._ranked_candidates(capability_kind, node_tags, budget)
        if failure_reason is not None:
            return SelectionResult(None, reason=failure_reason, alternatives=tuple(rejected))
        return SelectionResult(
            ranked[0], reason=REASON_SELECTED, alternatives=tuple(rejected + self._runners_up(ranked, 0))
        )

    def select_for_intent(
        self,
        capability_kind: str,
        intent: TaskIntent,
        node_tags: set[str],
        budget: ResourceBudget,
        *,
        now: float | None = None,
        frame_age: float | None = None,
        runtime: str | None = None,
        hardware_tags: tuple[str, ...] = (),
        input_profile: str | None = None,
    ) -> SelectionResult:
        """`select()` plus the `TaskIntent` hard constraints and, where a
        candidate carries a linked `ExecutionProfile`/`RuntimeInstance`
        (docs/ai/design/external-technology-decisions.md §4/§4.3), the
        evidence-reuse and TTL-expiry invariants those add.

        A provider with no `execution_profile`/`runtime_instance` attached
        is never excluded by those checks — this method degrades exactly
        to `select()`'s behaviour for registrations that predate the
        5-layer contract, so it is safe to call everywhere `select()` is
        already called (AI-C-05: 선택 정보 부재가 기존 기능을 막지 않는다).
        """
        if now is not None and not intent.is_within_deadline(now=now):
            return SelectionResult(None, reason=REASON_DEADLINE_EXCEEDED)
        if not intent.is_input_fresh_enough(frame_age=frame_age):
            return SelectionResult(None, reason=REASON_INPUT_TOO_STALE)

        ranked, failure_reason, rejected = self._ranked_candidates(capability_kind, node_tags, budget)
        if failure_reason is not None:
            return SelectionResult(None, reason=failure_reason, alternatives=tuple(rejected))

        last_reason = REASON_SELECTED
        skipped: list[CandidateOutcome] = []
        for index, candidate in enumerate(ranked):
            profile = candidate.execution_profile
            if (
                profile is not None
                and runtime is not None
                and input_profile is not None
                and not profile.matches_conditions(
                    runtime=runtime, hardware_tags=hardware_tags, input_profile=input_profile
                )
            ):
                last_reason = REASON_PROFILE_CONDITIONS_MISMATCH
                skipped.append(CandidateOutcome(candidate.provider_id, last_reason))
                continue

            instance = candidate.runtime_instance
            if instance is not None and now is not None and not instance.is_selectable(now=now):
                last_reason = REASON_INSTANCE_UNHEALTHY_OR_EXPIRED
                skipped.append(CandidateOutcome(candidate.provider_id, last_reason))
                continue

            return SelectionResult(
                candidate,
                reason=REASON_SELECTED,
                alternatives=tuple(rejected + skipped + self._runners_up(ranked, index)),
            )

        return SelectionResult(None, reason=last_reason, alternatives=tuple(rejected + skipped))

    def select_with_degrade(
        self,
        capability_kinds_by_priority: list[str],
        node_tags: set[str],
        budget: ResourceBudget,
    ) -> SelectionResult:
        """Try capability kinds in priority order, falling through to the
        next candidate kind when the previous has no usable provider.

        This is the step-down path AI-B-06 requires when a preferred
        provider/resource disappears: the caller supplies kinds ordered
        from richest to most conservative (e.g. ["risk.timeseries_model",
        "risk.rule_based"]) and gets the best one that is actually usable
        right now.
        """
        last_reason = REASON_NO_KINDS_GIVEN
        considered: list[CandidateOutcome] = []
        for kind in capability_kinds_by_priority:
            result = self.select(kind, node_tags, budget)
            if result.provider is not None:
                # Candidates from richer kinds that fell through are kept so
                # the step-down itself is visible to the consumer.
                return SelectionResult(
                    result.provider, reason=result.reason,
                    alternatives=tuple(considered) + result.alternatives,
                )
            last_reason = result.reason
            considered.extend(result.alternatives)
        return SelectionResult(None, reason=last_reason, alternatives=tuple(considered))
