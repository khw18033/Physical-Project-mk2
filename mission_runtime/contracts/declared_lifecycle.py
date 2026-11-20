"""선언된 업무 수명주기 — 도메인의 흐름을 **데이터로** 받는다.

implements: AI-C-15 (도메인·배포 프로파일 분리), AI-C-01 (성격이 다른 정보 구분),
            AI-C-19 (승인 주체는 우리가 아니다), AI-L-03 (작성자 없는 변경은 거절)
관련: AI-C-05 (선언이 없으면 이 계층만 비활성), AI-B-12 (조회 전용·frozen 규칙)
tests: tests/test_declared_lifecycle.py

## 왜 선언인가 — 이 저장소에는 이미 수명주기가 셋 있다

`execution/command_execution.py` 는 물리 명령의 lifecycle(AI-C-20),
`execution/external_request.py` 는 외부 개발 요청의 6 단계(AI-B-13),
`continual/lineage.py` 는 학습 결과의 승인(AI-L-06)이다. 셋 다 **요구사항이 단계를
정해 준 것**이라 타입으로 적혀 있고, 그래야 한다.

현장의 업무 요청은 다르다. 단계가 요구사항이 아니라 **현장의
업무 규칙**이고 현장마다 다르다. 그것을 코어에 타입으로 적으면 도메인이 코어에
들어오고, 두 번째 현장에서 분기문이 생긴다(절대 준수 원칙 #3). 그래서 상태와
전이를 선언으로 받고 **코어에는 업무 단어가 없다** — 시험이 그것을 고정한다.

## 승인은 상태가 아니라 **전이에 걸린 문**이다

승인을 별도 상태로 두면 "승인 대기" 와 "승인됨" 이 상태 두 칸을 먹고, 반려가
어느 칸으로 가는지가 선언마다 달라진다. 전이에 `requires_approval` 를 걸면 승인은
그 전이의 **조건**이고, 반려는 그냥 다른 전이다. 그리고 **요청자가 자기 요청을
승인하지 못한다** — 승인 주체는 우리가 아니고(AI-C-19), 같은 이름이 양쪽에 적히면
승인 기록은 아무것도 보증하지 않는다.

## 요청과 자산은 **서로를 끌고 가지 않는다**

요청이 종결돼도 자산은 그 자리에 있고, 자산이 점검에 들어가도 요청은 끝난 채
남는다. 둘을 한 상태로 합치면 "요청은 끝났는데 물건이 아직 어디 있는지" 를 적을
칸이 없어진다. 그래서 연결(`link`)은 **참조일 뿐 전이를 전파하지 않는다.**

## 잘못된 선언은 적재 시점에 터지고, 잘못된 전이는 사유를 낸다

`contracts/profile_loader.py` 와 같은 규칙이다. 선언이 깨졌으면 `LifecycleError`
로 크게 터뜨린다 — 조용히 좁은 쪽을 쓰면 기능 하나가 말없이 사라진다. 운영 중의
거절은 예외가 아니라 **사유 토큰**이고 화면이 그것으로 분기한다.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from mission_runtime.contracts import data_dictionary as dd

#: 거절 사유 어휘. 문구가 아니라 토큰이다.
REASON_NOT_DECLARED = "transition_not_declared"
REASON_WRONG_STATE = "transition_not_from_this_state"
REASON_TERMINAL = "instance_already_terminal"
REASON_NO_ACTOR = "actor_missing"
REASON_NO_EVIDENCE = "evidence_ref_missing"
REASON_NEEDS_APPROVAL = "approval_missing"
REASON_SELF_APPROVAL = "approver_is_the_requester"
REASON_MISSING_FIELD = "required_field_missing"
REASON_UNKNOWN_LIFECYCLE = "lifecycle_not_declared"
REASON_UNKNOWN_INSTANCE = "instance_not_found"
REASON_DUPLICATE_INSTANCE = "instance_already_exists"


class LifecycleError(ValueError):
    """선언이 잘못됐다. 운영 중 거절과 **다른 종류의 사건**이다."""


@dataclass(frozen=True)
class Transition:
    """상태 하나에서 다른 하나로. `requires` 는 이 전이가 **반드시 들고 와야 하는
    값의 이름들**이고, 의미는 도메인이 정한다 — 코어는 있는지만 본다."""

    name: str
    src: str
    dst: str
    requires_approval: bool = False
    requires: tuple[str, ...] = ()
    label: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LifecycleDeclaration:
    """수명주기 하나의 선언. 여기 있는 모든 것이 **파일에서 온다.**"""

    lifecycle_id: str
    initial: str
    states: tuple[str, ...]
    terminal: frozenset[str]
    transitions: tuple[Transition, ...]
    label: Mapping[str, str] = field(default_factory=dict)

    def transition(self, name: str) -> Transition | None:
        for candidate in self.transitions:
            if candidate.name == name:
                return candidate
        return None

    def outgoing(self, state: str) -> tuple[Transition, ...]:
        """그 자리에서 **지금 할 수 있는 일**. 화면이 버튼을 만드는 자리."""
        return tuple(t for t in self.transitions if t.src == state)

    def is_terminal(self, state: str) -> bool:
        return state in self.terminal


def declaration_from_mapping(raw: Mapping[str, Any]) -> LifecycleDeclaration:
    """선언 하나를 읽는다. **틀린 것은 여기서 터진다.**"""
    for key in ("lifecycle_id", "initial", "states", "transitions"):
        if key not in raw:
            raise LifecycleError(f"선언에 {key} 가 없다")

    states = tuple(str(state) for state in raw["states"])
    if len(set(states)) != len(states):
        raise LifecycleError(f"상태 이름이 겹친다: {states}")
    initial = str(raw["initial"])
    if initial not in states:
        raise LifecycleError(f"initial 이 states 에 없다: {initial}")

    terminal = frozenset(str(state) for state in raw.get("terminal", ()))
    unknown = terminal - set(states)
    if unknown:
        raise LifecycleError(f"terminal 이 states 에 없다: {sorted(unknown)}")

    transitions: list[Transition] = []
    seen: set[str] = set()
    for entry in raw["transitions"]:
        for key in ("name", "from", "to"):
            if key not in entry:
                raise LifecycleError(f"전이에 {key} 가 없다: {entry}")
        name = str(entry["name"])
        if name in seen:
            raise LifecycleError(f"전이 이름이 겹친다: {name}")
        seen.add(name)
        src, dst = str(entry["from"]), str(entry["to"])
        for end in (src, dst):
            if end not in states:
                raise LifecycleError(f"전이가 선언되지 않은 상태를 가리킨다: {end}")
        if src in terminal:
            # 종결 상태에서 나가는 전이가 있으면 그 상태는 종결이 **아니다.**
            # 둘 다 적어 두면 어느 쪽이 참인지 코드와 화면이 다르게 읽는다.
            raise LifecycleError(f"종결 상태에서 나가는 전이가 있다: {name}")
        transitions.append(Transition(
            name=name, src=src, dst=dst,
            requires_approval=bool(entry.get("requires_approval", False)),
            requires=tuple(str(item) for item in entry.get("requires", ())),
            label=dict(entry.get("label", {}))))

    if not transitions:
        raise LifecycleError(f"전이가 하나도 없다: {raw['lifecycle_id']}")

    reachable = {initial} | {t.dst for t in transitions}
    dead = set(states) - reachable
    if dead:
        # 닿을 수 없는 상태는 선언한 사람이 **의도한 흐름이 빠졌다**는 신호다.
        raise LifecycleError(f"어떤 전이로도 닿을 수 없는 상태: {sorted(dead)}")

    return LifecycleDeclaration(
        lifecycle_id=str(raw["lifecycle_id"]), initial=initial, states=states,
        terminal=terminal, transitions=tuple(transitions),
        label=dict(raw.get("label", {})))


def load_lifecycles(path: str | Path) -> dict[str, LifecycleDeclaration]:
    """파일 하나에 든 선언 묶음. 새 도메인은 **파일 한 장**이고 코드가 아니다."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = raw["lifecycles"] if isinstance(raw, dict) and "lifecycles" in raw else raw
    made: dict[str, LifecycleDeclaration] = {}
    for entry in entries:
        declaration = declaration_from_mapping(entry)
        if declaration.lifecycle_id in made:
            raise LifecycleError(f"수명주기 이름이 겹친다: {declaration.lifecycle_id}")
        made[declaration.lifecycle_id] = declaration
    return made


@dataclass(frozen=True)
class Step:
    """전이 한 번의 기록. **작성자 없는 변경은 없다**(AI-L-03 과 같은 규약)."""

    transition: str
    src: str
    dst: str
    actor: str
    evidence_ref: str
    at: float
    approved_by: str | None = None
    values: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LifecycleRefusal:
    """전이하지 못했다. **왜**가 함께 온다."""

    instance_id: str
    reason: str
    detail: str | None = None


@dataclass(frozen=True)
class Instance:
    """수명주기 하나의 진행. frozen 이고 전이는 **새 것을 반환**한다 —
    화면이 들고 있는 스냅샷을 제자리에서 바꿀 수 없다(AI-B-12 와 같은 규칙)."""

    instance_id: str
    lifecycle_id: str
    state: str
    history: tuple[Step, ...] = ()
    links: tuple[str, ...] = ()

    @property
    def requested_by(self) -> str | None:
        """처음 만든 사람. 승인 분리를 판정하는 기준이다."""
        return self.history[0].actor if self.history else None

    def with_link(self, instance_id: str) -> Instance:
        if instance_id in self.links:
            return self
        return Instance(self.instance_id, self.lifecycle_id, self.state,
                        self.history, self.links + (instance_id,))


class LifecycleRegistry:
    """선언과 진행을 들고 있는 자리. **전이를 전파하지 않는다.**"""

    def __init__(self, declarations: Mapping[str, LifecycleDeclaration] | None = None,
                 *, clock: Callable[[], float] | None = None) -> None:
        self._declarations: dict[str, LifecycleDeclaration] = dict(declarations or {})
        self._instances: dict[str, Instance] = {}
        self._clock = clock or time.time
        #: 거절을 센다. 「반려 0 건」을 주장이 아니라 측정으로 만든다.
        self.refusals: list[LifecycleRefusal] = []

    # --- 선언 -------------------------------------------------------------
    def declare(self, declaration: LifecycleDeclaration) -> None:
        self._declarations[declaration.lifecycle_id] = declaration

    def declared(self) -> tuple[str, ...]:
        return tuple(sorted(self._declarations))

    def declaration(self, lifecycle_id: str) -> LifecycleDeclaration | None:
        return self._declarations.get(lifecycle_id)

    # --- 진행 -------------------------------------------------------------
    def start(self, lifecycle_id: str, instance_id: str, *, actor: str,
              evidence_ref: str, links: tuple[str, ...] = ()
              ) -> Instance | LifecycleRefusal:
        declaration = self._declarations.get(lifecycle_id)
        if declaration is None:
            return self._refuse(instance_id, REASON_UNKNOWN_LIFECYCLE, lifecycle_id)
        if instance_id in self._instances:
            return self._refuse(instance_id, REASON_DUPLICATE_INSTANCE)
        if not actor:
            return self._refuse(instance_id, REASON_NO_ACTOR)
        if not evidence_ref:
            return self._refuse(instance_id, REASON_NO_EVIDENCE)

        opened = Step("start", declaration.initial, declaration.initial, actor,
                      evidence_ref, self._clock())
        made = Instance(instance_id, lifecycle_id, declaration.initial,
                        (opened,), tuple(links))
        self._instances[instance_id] = made
        return made

    def advance(self, instance_id: str, transition: str, *, actor: str,
                evidence_ref: str, approved_by: str | None = None,
                values: Mapping[str, Any] | None = None
                ) -> Instance | LifecycleRefusal:
        """전이하거나, **왜 못 했는지**를 돌려준다. 연결된 다른 진행은 건드리지 않는다."""
        current = self._instances.get(instance_id)
        if current is None:
            return self._refuse(instance_id, REASON_UNKNOWN_INSTANCE)
        declaration = self._declarations[current.lifecycle_id]

        if declaration.is_terminal(current.state):
            return self._refuse(instance_id, REASON_TERMINAL, current.state)
        wanted = declaration.transition(transition)
        if wanted is None:
            return self._refuse(instance_id, REASON_NOT_DECLARED, transition)
        if wanted.src != current.state:
            return self._refuse(instance_id, REASON_WRONG_STATE,
                                f"{current.state} → {transition}")
        if not actor:
            return self._refuse(instance_id, REASON_NO_ACTOR)
        if not evidence_ref:
            return self._refuse(instance_id, REASON_NO_EVIDENCE)

        carried = dict(values or {})
        for name in wanted.requires:
            if carried.get(name) in (None, ""):
                return self._refuse(instance_id, REASON_MISSING_FIELD, name)

        if wanted.requires_approval:
            if not approved_by:
                return self._refuse(instance_id, REASON_NEEDS_APPROVAL, transition)
            if approved_by in {actor, current.requested_by}:
                # 요청자가 자기 요청을 승인하면 그 기록은 아무것도 보증하지 않는다.
                return self._refuse(instance_id, REASON_SELF_APPROVAL, approved_by)

        step = Step(transition, current.state, wanted.dst, actor, evidence_ref,
                    self._clock(), approved_by, carried)
        made = Instance(current.instance_id, current.lifecycle_id, wanted.dst,
                        current.history + (step,), current.links)
        self._instances[instance_id] = made
        return made

    def link(self, instance_id: str, other_id: str) -> Instance | LifecycleRefusal:
        """두 진행을 **서로 참조만** 하게 묶는다. 전이는 전파되지 않는다."""
        current = self._instances.get(instance_id)
        other = self._instances.get(other_id)
        if current is None or other is None:
            return self._refuse(instance_id, REASON_UNKNOWN_INSTANCE, other_id)
        self._instances[instance_id] = current.with_link(other_id)
        self._instances[other_id] = other.with_link(instance_id)
        return self._instances[instance_id]

    # --- 보기 -------------------------------------------------------------
    def get(self, instance_id: str) -> Instance | None:
        return self._instances.get(instance_id)

    def linked(self, instance_id: str) -> tuple[Instance, ...]:
        current = self._instances.get(instance_id)
        if current is None:
            return ()
        return tuple(self._instances[other] for other in current.links
                     if other in self._instances)

    def available(self, instance_id: str) -> tuple[Transition, ...]:
        """지금 할 수 있는 전이. 화면이 버튼을 만드는 자리이고 **여기서 고르지 않는다.**"""
        current = self._instances.get(instance_id)
        if current is None:
            return ()
        return self._declarations[current.lifecycle_id].outgoing(current.state)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for instance_id in sorted(self._instances):
            current = self._instances[instance_id]
            declaration = self._declarations[current.lifecycle_id]
            out[instance_id] = {
                dd.WORK_LIFECYCLE_ID: current.lifecycle_id,
                dd.WORK_LIFECYCLE_STATE: current.state,
                "terminal": declaration.is_terminal(current.state),
                "steps": len(current.history),
                dd.LINKED_INSTANCES: list(current.links),
                "available": [t.name for t in declaration.outgoing(current.state)],
            }
        return out

    # --- 내부 -------------------------------------------------------------
    def _refuse(self, instance_id: str, reason: str,
                detail: str | None = None) -> LifecycleRefusal:
        refusal = LifecycleRefusal(instance_id, reason, detail)
        self.refusals.append(refusal)
        return refusal
