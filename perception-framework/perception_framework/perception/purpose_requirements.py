"""Purpose-defined required evidence, independent of sensor, model or
domain implementation.

implements: AI-S-07

AI-S-07: "객체·환경 판단을 소비하는 업무나 태스크는 판단에 반드시 필요한 정보와
있으면 품질을 높이는 선택 정보를 의미 수준에서 정의할 수 있어야 한다. 동일
객체라도 충돌 회피, 자산 식별, 위험 분석 등 사용 목적에 따라 필요한 의미·공간·
시간·행동 정보가 다를 수 있으므로 모든 객체에 동일한 완성 상태를 요구해서는
안 된다. 요구 정보는 특정 센서·모델·도메인 구현에 종속되지 않아야 하며 현재
객체 레코드에 확보된 정보와 비교해 추가 정보 필요 여부를 평가할 수 있어야
한다."

Design reference (D grade — no runtime dependency): the JDL Data Fusion
Model's observation that different *consuming* purposes need different
levels/kinds of derived information (object refinement vs. situation vs.
impact assessment) — borrowed here only as the idea that required
information is a property of the purpose, not of the object, not as its
five-level taxonomy (docs/ai/design/external-technology-decisions.md §11.3).

This module never decides "is this object done" on its own — a caller
(object/environment record consumer) supplies `available_fields`, computed
however that record represents completeness, and this module only compares
it against a purpose's declared requirement. Field names are semantic
kinds from the common data dictionary (AI-C-01), never sensor or model
identifiers, and purpose ids are free strings — this module contains no
domain branching (원칙 #3: 도메인명으로 핵심 코드에 분기하지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PurposeRequirement:
    """What one consuming purpose needs from an object/environment record.

    `purpose_id` names a business purpose (e.g. "collision_avoidance",
    "asset_identification", "risk_analysis") — a free string, never a
    domain name branch. `required_fields`/`preferred_fields` name semantic
    field kinds (AI-C-01 vocabulary), not concrete sensors or models.
    """

    purpose_id: str
    required_fields: tuple[str, ...] = ()
    preferred_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceGap:
    """The result of comparing one purpose's requirement against what a
    record currently has available.
    """

    purpose_id: str
    missing_required: tuple[str, ...]
    missing_preferred: tuple[str, ...]

    @property
    def sufficient(self) -> bool:
        """Required-field shortfall is what drives "추가 정보 필요" — a
        missing preferred field only means lower quality, it never on its
        own triggers an additional-information request (same principle as
        AI-C-05's required/optional split).
        """
        return not self.missing_required


def evaluate_gap(requirement: PurposeRequirement, available_fields: set[str]) -> EvidenceGap:
    """Compare a purpose's declared requirement against fields currently
    available on some object/environment record.

    What counts as "available" is entirely the caller's judgment (e.g. an
    `ObjectRecord`'s confirmed attributes, an `EnvironmentMapEstimator`
    element's producers) — this function performs only the comparison, so
    it never becomes coupled to a specific record shape or sensor.
    """
    missing_required = tuple(f for f in requirement.required_fields if f not in available_fields)
    missing_preferred = tuple(f for f in requirement.preferred_fields if f not in available_fields)
    return EvidenceGap(requirement.purpose_id, missing_required, missing_preferred)


@dataclass
class PurposeRequirementRegistry:
    """Where consuming purposes register what they need.

    A task/consumer registers its requirement once; any object/environment
    record can then be checked against every registered purpose without
    perception code ever hardcoding purpose or domain names.
    """

    _requirements: dict[str, PurposeRequirement] = field(default_factory=dict)

    def register(self, requirement: PurposeRequirement) -> None:
        self._requirements[requirement.purpose_id] = requirement

    def evaluate(self, purpose_id: str, available_fields: set[str]) -> EvidenceGap | None:
        """Returns `None` for an unregistered purpose rather than guessing
        at a default requirement — an undeclared purpose must not silently
        pass or fail sufficiency.
        """
        requirement = self._requirements.get(purpose_id)
        if requirement is None:
            return None
        return evaluate_gap(requirement, available_fields)

    def evaluate_all(self, available_fields: set[str]) -> tuple[EvidenceGap, ...]:
        """Every registered purpose's gap against the same record — the
        same object can be "sufficient" for collision avoidance and
        "insufficient" for asset identification at once, which is the
        point of AI-S-07 (동일 객체라도 목적마다 필요한 정보가 다르다).
        """
        return tuple(evaluate_gap(r, available_fields) for r in self._requirements.values())
