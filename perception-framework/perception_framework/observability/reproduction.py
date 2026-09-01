"""Error reproduction reference bundle (AI-O-03).

implements: AI-B-03, AI-O-03

Collects whatever references are actually available (business/audit
correlation id, short-term replay position, archive reference, trace
id) instead of requiring all of them — a technology missing at one
boundary must not prevent recording what *is* available (AI-O-03:
"특정 전송·관측 기술이 없더라도 확보된 참조 범위에서 재현 정보를 남겨야
한다"). Business/audit correlation and technical trace stay separate
fields for the same reason AI-B-03 keeps its two logs separate.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReproductionReference:
    business_correlation_id: str | None = None
    short_term_replay_ref: str | None = None
    archive_ref: str | None = None
    trace_id: str | None = None

    def available_refs(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, value in (
                ("business_correlation_id", self.business_correlation_id),
                ("short_term_replay_ref", self.short_term_replay_ref),
                ("archive_ref", self.archive_ref),
                ("trace_id", self.trace_id),
            )
            if value is not None
        )

    def is_empty(self) -> bool:
        return not self.available_refs()


class ReproductionReferenceBuilder:
    """Chooses short-term replay ref while the event is still within
    retention, otherwise falls back to an archive ref if one exists.
    """

    def build(
        self,
        *,
        business_correlation_id: str | None,
        trace_id: str | None,
        within_short_term_retention: bool,
        short_term_replay_ref: str | None,
        archive_ref: str | None,
    ) -> ReproductionReference:
        replay_ref = short_term_replay_ref if within_short_term_retention else None
        chosen_archive_ref = None if within_short_term_retention else archive_ref
        return ReproductionReference(
            business_correlation_id=business_correlation_id,
            short_term_replay_ref=replay_ref,
            archive_ref=chosen_archive_ref,
            trace_id=trace_id,
        )
