"""Capability contract shared by every AI feature in this framework.

A "capability" is anything the framework can activate/degrade/disable at
runtime: a perception provider, a safety judgment, a decision module, a
transport adapter, etc. This module defines the vocabulary every one of
them uses to declare what it needs and what state it is currently in.

implements: AI-C-05, AI-C-11
절대 준수 원칙 #4: 선택 기능의 추가·제거·장애가 관련 없는 기능의 시작·실행·복구를
방해해서는 안 된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CapabilityState(str, Enum):
    """Runtime state of one capability instance.

    ACTIVE    - every required and optional condition is met; full spec.
    DEGRADED  - required conditions are met, but at least one optional
                condition is missing or unhealthy; the feature keeps
                running on a reduced contract instead of stopping.
    DISABLED  - a required condition is missing or unhealthy; the
                feature is inactive but this must never block unrelated
                capabilities from starting, running or recovering.
    """

    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    DISABLED = "DISABLED"


@dataclass(frozen=True)
class CapabilityRequirement:
    """Declares what one capability needs in order to run.

    `required` names must all be present and healthy for the capability
    to leave DISABLED. `optional` names improve quality or efficiency;
    their absence only pushes the capability to DEGRADED, never to
    DISABLED, and must never cascade into unrelated capabilities
    (AI-C-11).

    Names in `required`/`optional` are capability-kind identifiers (e.g.
    "media.video_input", "perception.classify") resolved against a
    CapabilityRegistry — this module has no knowledge of what concrete
    sensor, model or runtime backs any of them.
    """

    required: tuple[str, ...] = field(default_factory=tuple)
    optional: tuple[str, ...] = field(default_factory=tuple)

    def evaluate(self, available: set[str]) -> CapabilityState:
        """Compute this capability's state given which dependency kinds
        currently have at least one healthy provider.
        """
        missing_required = [name for name in self.required if name not in available]
        if missing_required:
            return CapabilityState.DISABLED

        missing_optional = [name for name in self.optional if name not in available]
        if missing_optional:
            return CapabilityState.DEGRADED

        return CapabilityState.ACTIVE
