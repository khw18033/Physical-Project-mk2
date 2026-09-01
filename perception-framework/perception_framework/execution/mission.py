"""Mission-level outcome judgment: aggregates per-item results into one
verdict that records *what was given up* on the way to success.

implements: AI-C-05, AI-C-11, AI-C-13, AI-B-06

AI-C-05: "선택 기능이 추가·제거·고장 나면 해당 기능만 활성·축소·비활성화하고
나머지 기능은 계속 실행해야 한다."
절대 준수 원칙 #4: 선택 기능의 결손은 관련 없는 기능을 막지 않는다.

`CapabilityRequirement` (contracts/capability.py) answers "can this one
capability run?". This module answers the different question "did the
mission as a whole achieve what it had to?" — required items gate
success, optional items only lower the recorded quality level, and the
verdict keeps the list of sacrificed optional items so a plain
SUCCESS/FAIL never hides the reduction.

Domain neutrality (절대 준수 원칙 #3, AI-C-15): this module knows no
mission kinds. Item ids, and which of them are required vs optional, are
declared entirely by the caller — `facility`, `robot`, `river` and any
future domain use the same code path with different declarations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from perception_framework.contracts.capability import CapabilityState


class MissionItemOutcome(str, Enum):
    """Result of one declared mission item.

    SUCCEEDED   - the item produced the evidence it was asked for.
    FAILED      - the item ran and could not produce it.
    UNAVAILABLE - the item could not even be attempted because a needed
                  capability/provider was absent. Kept distinct from
                  FAILED because "정상적인 축소 운용과 핵심 기능 실패"를
                  구분해야 한다(AI-O-02).
    """

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNAVAILABLE = "UNAVAILABLE"

    @property
    def is_success(self) -> bool:
        return self is MissionItemOutcome.SUCCEEDED


class MissionStatus(str, Enum):
    """Mission-level verdict.

    SUCCESS    - every required item succeeded.
    FAILED     - at least one required item failed or was unavailable.
    NOT_RUN    - no result was reported for at least one required item.
    """

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    NOT_RUN = "NOT_RUN"


@dataclass(frozen=True)
class MissionItem:
    """One declared unit of mission work.

    `item_id` is an opaque caller-chosen identifier (e.g. "observe.area_a").
    This module never interprets it.
    """

    item_id: str
    required: bool = True
    description: str = ""


@dataclass(frozen=True)
class MissionVerdict:
    """Outcome of one mission, including what was sacrificed.

    `optional_quality` reuses the ACTIVE/DEGRADED/DISABLED vocabulary of
    CapabilityState so that mission reporting and capability reporting
    speak the same language:
      ACTIVE   - every optional item succeeded (or none were declared)
      DEGRADED - some optional items succeeded, some did not
      DISABLED - optional items were declared and none succeeded
    Optional quality never affects `status` (AI-C-05).
    """

    status: MissionStatus
    optional_quality: CapabilityState
    outcomes: dict[str, MissionItemOutcome] = field(default_factory=dict)
    satisfied_required: tuple[str, ...] = ()
    failed_required: tuple[str, ...] = ()
    missing_required: tuple[str, ...] = ()
    satisfied_optional: tuple[str, ...] = ()
    sacrificed_optional: tuple[str, ...] = ()

    @property
    def succeeded(self) -> bool:
        return self.status is MissionStatus.SUCCESS

    @property
    def is_reduced(self) -> bool:
        """True when the mission succeeded but gave something up."""
        return self.succeeded and bool(self.sacrificed_optional)

    def summary(self) -> str:
        """One-line human-readable record of the trade-off actually made."""
        if not self.sacrificed_optional:
            return f"{self.status.value} (optional {self.optional_quality.value})"
        given_up = ", ".join(self.sacrificed_optional)
        return (
            f"{self.status.value} (optional {self.optional_quality.value};"
            f" sacrificed: {given_up})"
        )


class MissionSpec:
    """A caller-declared set of required and optional mission items.

    The framework supplies the aggregation rule; the caller supplies the
    mission content. No domain branch exists here.
    """

    def __init__(self, mission_id: str, items: list[MissionItem] | tuple[MissionItem, ...]):
        seen: set[str] = set()
        ordered: list[MissionItem] = []
        for item in items:
            if item.item_id in seen:
                raise ValueError(f"duplicate mission item id: {item.item_id}")
            seen.add(item.item_id)
            ordered.append(item)
        if not any(i.required for i in ordered):
            raise ValueError(
                "a mission must declare at least one required item; "
                "otherwise success is vacuous"
            )
        self.mission_id = mission_id
        self.items: tuple[MissionItem, ...] = tuple(ordered)

    @property
    def required_ids(self) -> tuple[str, ...]:
        return tuple(i.item_id for i in self.items if i.required)

    @property
    def optional_ids(self) -> tuple[str, ...]:
        return tuple(i.item_id for i in self.items if not i.required)

    def evaluate(self, outcomes: dict[str, MissionItemOutcome]) -> MissionVerdict:
        """Aggregate per-item outcomes into a mission verdict.

        Unknown item ids in `outcomes` are rejected: silently ignoring
        them would let a mis-declared mission report a success it never
        earned. A required item with no reported outcome yields NOT_RUN
        rather than FAILED — "실행되지 않음"과 "실행 후 실패"는 후속
        조치가 다르다(AI-O-02).
        """
        unknown = sorted(set(outcomes) - {i.item_id for i in self.items})
        if unknown:
            raise ValueError(f"outcome reported for undeclared item(s): {unknown}")

        satisfied_req: list[str] = []
        failed_req: list[str] = []
        missing_req: list[str] = []
        satisfied_opt: list[str] = []
        sacrificed_opt: list[str] = []

        for item in self.items:
            outcome = outcomes.get(item.item_id)
            if item.required:
                if outcome is None:
                    missing_req.append(item.item_id)
                elif outcome.is_success:
                    satisfied_req.append(item.item_id)
                else:
                    failed_req.append(item.item_id)
            else:
                # A missing optional outcome is treated as not achieved,
                # never as a mission-blocking gap (AI-C-11).
                if outcome is not None and outcome.is_success:
                    satisfied_opt.append(item.item_id)
                else:
                    sacrificed_opt.append(item.item_id)

        if missing_req:
            status = MissionStatus.NOT_RUN
        elif failed_req:
            status = MissionStatus.FAILED
        else:
            status = MissionStatus.SUCCESS

        if not self.optional_ids:
            quality = CapabilityState.ACTIVE
        elif not sacrificed_opt:
            quality = CapabilityState.ACTIVE
        elif not satisfied_opt:
            quality = CapabilityState.DISABLED
        else:
            quality = CapabilityState.DEGRADED

        return MissionVerdict(
            status=status,
            optional_quality=quality,
            outcomes=dict(outcomes),
            satisfied_required=tuple(satisfied_req),
            failed_required=tuple(failed_req),
            missing_required=tuple(missing_req),
            satisfied_optional=tuple(satisfied_opt),
            sacrificed_optional=tuple(sacrificed_opt),
        )
