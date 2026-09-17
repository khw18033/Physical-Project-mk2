"""Environment/prior information, kept distinct from live sensor observation.

implements: AI-S-08

AI-S-08: "AI가 사용하는 환경 사전정보와 장기 관측 정보는 실제 센서 관측과
구분하여 관리하고 출처, 대상 구역·객체, 생성·갱신 시점, 버전, 유효 범위와
현재 사용 가능 여부를 확인할 수 있어야 한다. 공간·시설·과거 관측·임무·환경
이벤트 등 서로 다른 종류의 사전정보를 특정 도메인에 고정하지 않고 선택 정보로
사용할 수 있어야 하며, 실제 관측과 충돌하는 사전정보만으로 객체·위험 상태를
확정해서는 안 된다. 반복적인 불일치나 오래된 사전정보는 재평가·갱신 대상으로
식별할 수 있어야 한다."

`perception/environment_map.py` already covers the anchor-relative
structure-estimate slice of this requirement (accumulating vision evidence
around a declared anchor). This module covers the broader "prior info"
half — facility/spatial/mission/historical/environmental-event records that
come from outside live perception and must carry their own provenance and
validity, independent of any anchor.

Design reference (D grade — no runtime dependency): ISO 19115 lineage/
quality model (source, scope, valid range, version) for the record shape;
W3C PROV-O's `wasRevisionOf` for "replace without erasing" instead of a
silent overwrite (docs/ai/design/external-technology-decisions.md §11.3).

This module deliberately has no "confirm" or "promote" operation — a prior
record is only ever data a caller may weigh alongside real observation.
The absence of any such method is the enforcement of "실제 관측과 충돌하는
사전정보만으로 확정해서는 안 된다": nothing here can confirm anything by
itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum


class PriorKind(str, Enum):
    """A handful of generic shapes AI-S-08 names explicitly. Not exhaustive
    on purpose — a deployment may tag a record with any free string kind
    instead; this framework does not special-case domains (원칙 #3).
    """

    SPATIAL = "SPATIAL"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    HISTORICAL_OBSERVATION = "HISTORICAL_OBSERVATION"
    MISSION = "MISSION"
    ENVIRONMENTAL_EVENT = "ENVIRONMENTAL_EVENT"
    OTHER = "OTHER"


@dataclass(frozen=True)
class PriorInfoRecord:
    """One piece of environment/prior information.

    `scope` names the zones/objects this applies to — not a coordinate,
    just identifiers the consumer already understands. `conflict_count`
    accumulates disagreements reported against this record by real
    observation; it is never used here to invalidate the record
    automatically, only to mark it a candidate for re-evaluation.
    """

    record_id: str
    kind: str
    source: str
    scope: tuple[str, ...]
    created_at: float
    updated_at: float
    version: str
    valid_from: float | None = None
    valid_until: float | None = None
    available: bool = True
    payload: dict[str, object] = field(default_factory=dict)
    revision_of: str | None = None
    conflict_count: int = 0

    def is_valid_at(self, now: float) -> bool:
        """Currently usable: marked available *and* inside its declared
        validity window (an unset bound means "no limit on that side").
        """
        if not self.available:
            return False
        if self.valid_from is not None and now < self.valid_from:
            return False
        if self.valid_until is not None and now > self.valid_until:
            return False
        return True

    def needs_reevaluation(
        self, *, now: float, conflict_threshold: int = 3, max_age: float | None = None
    ) -> bool:
        """반복적인 불일치나 오래된 사전정보를 재평가·갱신 대상으로 식별한다."""
        if self.conflict_count >= conflict_threshold:
            return True
        if max_age is not None and (now - self.updated_at) > max_age:
            return True
        return False


class PriorInfoStore:
    """Keeps prior info separate from any observation stream, with
    revision-not-overwrite semantics and explicit conflict tracking.
    """

    def __init__(self) -> None:
        self._records: dict[str, PriorInfoRecord] = {}

    def register(self, record: PriorInfoRecord) -> None:
        self._records[record.record_id] = record

    def get(self, record_id: str) -> PriorInfoRecord | None:
        return self._records.get(record_id)

    def revise(self, record_id: str, new_record: PriorInfoRecord) -> PriorInfoRecord:
        """Replace `record_id` with a new version without erasing the old
        one's identity — `revision_of` links back to it (PROV-O
        `wasRevisionOf`) so lineage survives updates rather than being
        overwritten in place.
        """
        previous = self._records.get(record_id)
        revised = replace(
            new_record,
            revision_of=previous.record_id if previous is not None else new_record.revision_of,
        )
        self._records[new_record.record_id] = revised
        return revised

    def report_conflict(self, record_id: str) -> PriorInfoRecord | None:
        """실제 관측과 충돌했음을 기록한다. 이 메서드는 레코드를 폐기하거나
        확정 근거로 승격하지 않는다 — 불일치 횟수만 누적해 재평가 후보 판정에
        쓰인다(`needs_reevaluation`).
        """
        current = self._records.get(record_id)
        if current is None:
            return None
        updated = replace(current, conflict_count=current.conflict_count + 1)
        self._records[record_id] = updated
        return updated

    def usable(self, *, now: float, scope: str | None = None) -> tuple[PriorInfoRecord, ...]:
        """Records currently valid and available, optionally narrowed to
        one scope id.
        """
        return tuple(
            r
            for r in self._records.values()
            if r.is_valid_at(now) and (scope is None or scope in r.scope)
        )

    def reevaluation_candidates(
        self, *, now: float, conflict_threshold: int = 3, max_age: float | None = None
    ) -> tuple[PriorInfoRecord, ...]:
        return tuple(
            r
            for r in self._records.values()
            if r.needs_reevaluation(now=now, conflict_threshold=conflict_threshold, max_age=max_age)
        )
