"""Constraint-based subtask generation (AI-D-01).

Not tied to any specific LLM or planning library: this reference
generator uses verifiable action templates and explicit condition
expressions. A zone with no registered `ZoneRule` is simply skipped —
generation only ever uses information that is actually confirmable
right now (AI-D-01: "환경 사전정보나 추가 인지 결과가 없으면 현재 확인
가능한 정보 범위에서만 계획을 생성").
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Subtask:
    subtask_id: str
    zone_id: str
    action: str
    order_index: int
    params: dict = field(default_factory=dict)
    preconditions: tuple[str, ...] = ()
    forbidden_if: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ()
    resource_requirements: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ZoneRule:
    zone_id: str
    forbidden_conditions: tuple[str, ...] = ()
    allowed_actions: tuple[str, ...] = ()


class SubtaskGenerator:
    """Turns a main mission's allowed actions + per-zone rules + the
    conditions currently known to be active into executable subtasks.
    """

    def generate(
        self,
        mission_action_ids: tuple[str, ...],
        zone_rules: dict[str, ZoneRule],
        active_conditions: set[str],
    ) -> list[Subtask]:
        subtasks: list[Subtask] = []
        order = 0
        for zone_id, rule in zone_rules.items():
            if set(rule.forbidden_conditions) & active_conditions:
                continue  # zone currently forbidden -> generate nothing for it
            for action in mission_action_ids:
                if action not in rule.allowed_actions:
                    continue
                subtasks.append(
                    Subtask(
                        subtask_id=f"{zone_id}:{action}:{order}",
                        zone_id=zone_id,
                        action=action,
                        order_index=order,
                        preconditions=(f"zone_reachable:{zone_id}",),
                        forbidden_if=rule.forbidden_conditions,
                    )
                )
                order += 1
        return subtasks
