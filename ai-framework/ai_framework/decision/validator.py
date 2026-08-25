"""Subtask validation, kept separate from generation (AI-D-02).

Validation is a pure function of (subtask, context): the same input
always yields the same verdict regardless of how the subtask was
generated, which is what lets it be reused against subtasks coming from
any planning technology (AI-D-02: "검증 기능은 계획 생성 기능과 분리해
동일 조건에서 재현 가능한 결과를 제공해야 한다").
"""

from __future__ import annotations

from dataclasses import dataclass

import jsonschema

from ai_framework.decision.subtask import Subtask

SUBTASK_JSON_SCHEMA = {
    "type": "object",
    "required": ["subtask_id", "zone_id", "action", "order_index"],
    "properties": {
        "subtask_id": {"type": "string", "minLength": 1},
        "zone_id": {"type": "string", "minLength": 1},
        "action": {"type": "string", "minLength": 1},
        "order_index": {"type": "integer", "minimum": 0},
        "resource_requirements": {"type": "object"},
    },
}


@dataclass(frozen=True)
class ValidationContext:
    known_zone_ids: set[str]
    active_conditions: set[str]
    known_facts: set[str]  # precondition ids currently confirmed true
    robot_resources: dict  # e.g. {"battery_pct": 80}


@dataclass(frozen=True)
class ValidationResult:
    executable: bool
    reasons: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()


class SubtaskValidator:
    """Checks structure, zone boundary, forbidden conditions, resource
    conditions and precondition confirmability before a subtask may run.
    """

    def validate(self, subtask: Subtask, context: ValidationContext) -> ValidationResult:
        try:
            jsonschema.validate(
                {
                    "subtask_id": subtask.subtask_id,
                    "zone_id": subtask.zone_id,
                    "action": subtask.action,
                    "order_index": subtask.order_index,
                    "resource_requirements": subtask.resource_requirements,
                },
                SUBTASK_JSON_SCHEMA,
            )
        except jsonschema.ValidationError as exc:
            return ValidationResult(False, reasons=(f"schema: {exc.message}",))

        reasons: list[str] = []

        if subtask.zone_id not in context.known_zone_ids:
            reasons.append(f"unknown_zone:{subtask.zone_id}")

        active_forbidden = sorted(set(subtask.forbidden_if) & context.active_conditions)
        if active_forbidden:
            reasons.append(f"forbidden_active:{active_forbidden}")

        for key, minimum in subtask.resource_requirements.items():
            have = context.robot_resources.get(key)
            if have is None or have < minimum:
                reasons.append(f"resource_insufficient:{key}")

        # Unconfirmed (not confirmable right now) preconditions only mark
        # *this* subtask unexecutable and surface what evidence is
        # needed — they are not treated as confirmed-false (AI-D-02:
        # "확인할 수 없는 필수 조건이 있으면 해당 행동만 실행 불가로 표시하고
        # 필요한 추가 근거를 요청해야 한다").
        missing_evidence = tuple(p for p in subtask.preconditions if p not in context.known_facts)
        if missing_evidence:
            reasons.append("preconditions_unconfirmed")

        return ValidationResult(executable=not reasons, reasons=tuple(reasons), missing_evidence=missing_evidence)
