"""링크가 끊겨도, 프로세스가 죽었다 살아나도 "나는 무슨 임무 중인가"를
말단 혼자 답할 수 있게 하는 임무 캐시.

implements: AI-N-02, AI-B-05, AI-C-19, AI-C-20, AI-C-05, AI-B-10
tests: tests/test_mission_cache.py

무엇을 푸는가
-------------
관리자가 가시화 UI에서 승인한 행동이 물리 명령 계약(AI-C-20)을 타고 말단까지
내려온다. 말단의 어댑터가 그것을 로봇 명령으로 옮겨 수행하는 동안 링크가
끊길 수 있고, 그 사이에 말단 프로세스가 재시작될 수도 있다. 그때 남아야 하는
것은 두 가지다 — **무엇을 하라고 받았는가(임무 내용)** 와 **어디까지 했는가
(진행 상태)**. 둘 다 메모리에만 있으면 재시작 한 번에 사라지고, 말단은 링크가
돌아올 때까지 자기가 무슨 임무 중인지 말할 수 없다.

`execution/mission.py`는 "임무 전체가 달성됐는가"를 판정하지만 메모리 안에서만
산다. 이 모듈은 그 판정기를 그대로 쓰되(중복 구현하지 않는다) 내용과 진행을
디스크에 남긴다.

무엇을 **하지 않는가** (경계가 이 모듈의 핵심이다)
--------------------------------------------------
* **명령 중복 실행 방지는 여기 없다.** 같은 `command_id` 재전달을 걸러내는
  책임은 `execution/command_execution.py::CommandExecutionSupervisor`가 이미
  SQLite로 가지고 있다(AI-C-20). 여기서 두 번째 idempotency 저장소를 만들면
  두 판정이 어긋나는 순간 어느 쪽이 참인지 말할 수 없게 된다. 이 캐시가
  보장하는 idempotency는 **내용의 idempotency** 뿐이다 — 같은
  `(mission_id, version)`을 두 번 적용해도 진행 상태가 되감기지 않는다.
* **임무를 만들지 않는다(AI-C-19).** 모든 `MissionDelivery`는 자신을 실어 나른
  물리 명령의 `origin_command_id`를 반드시 달고 와야 하며, 없으면 거부된다.
  AI가 "이런 임무가 필요하다"고 판단해 캐시에 밀어 넣는 경로는 존재하지 않는다.
* **물리 명령을 발급하지 않는다.** 이 모듈은 "이 항목은 링크 없이 이어서 해도
  되는가"라는 질문에만 답하고, 실제 실행은 어댑터(`execution/hardware_adapter.py`)
  뒤에서 일어난다.

자율 경계 — 왜 "이미 승인된 임무의 재개"는 "행동의 결정"이 아닌가
------------------------------------------------------------------
AI-C-19는 AI가 물리 명령 발급과 실제 제어를 소유하지 못하게 한다. 그런데 이미
관리자가 승인했고 이미 말단까지 전달된 임무를 링크 단절 중에 이어서 수행하는
것은 **새로운 판단이 아니라 전달된 판단의 집행**이다. 둘을 코드에서 구분할 수
있어야 그 주장이 검증 가능해지므로, 구분을 추론이 아니라 **데이터**로 둔다:
항목마다 발급자가 `MissionAutonomy`를 붙여 보내고, 붙어 있지 않으면 보수적인
`REQUIRES_FRESH_COMMAND`가 기본값이다. 즉 "이어서 해도 된다"는 말은 반드시
발급 시점에 사람이(백엔드가) 명시한 것이며 말단이 스스로 추론한 적이 없다.

`resumable_without_link()`가 돌려주는 목록은 그래서 "AI가 해도 된다고 판단한
일"이 아니라 "발급자가 미리 허가해 둔 일 중 아직 안 끝난 것"이다.
`blocked_pending_command()`는 그 반대편, 즉 링크가 돌아오고 새 명령이 와야만
움직일 수 있는 항목이다. 두 목록의 합집합이 항상 미완료 항목 전체다.

긴급정지 (AI-C-20)
------------------
"긴급정지는 일반 취소와 구분하고 상위 네트워크 명령만을 안전 기능의 유일한
경로로 사용해서는 안 된다." 그래서 `suspend_for_safety()`는 링크도 백엔드도
필요 없이 로컬에서 호출되며, 호출된 뒤에는 이 캐시가 어떤 항목에 대해서도
"이어서 해도 된다"고 말하지 않는다. 캐시는 정지를 **명령하는** 경로가 아니라
(그건 `reference/local_safety.py`와 물리적 정지 경로의 몫이다) 정지 위에 대고
"그래도 계속하라"고 말하지 못하게 막는 쪽이다. 해제는 반드시 명시적 호출로만
되고 그 사유가 스냅샷에 남는다.

AI-B-05 — 프로세스 생사와 장치 운용 상태는 다른 값이다
--------------------------------------------------------
재시작 시 `IN_PROGRESS`였던 항목은 `INTERRUPTED`가 된다. `FAILED`가 아니다 —
"실행 중에 프로세스가 죽었다"와 "실행해 봤더니 실패했다"는 후속 조치가 다르고
(AI-O-02), 전자를 후자로 적으면 임무 판정이 거짓이 된다. `MissionSnapshot`은
`process_restarts`를 따로 세어 두므로 프로세스 생사가 임무 성패 안으로
녹아들지 않는다.

AI-N-02 — 버전·검증·last-known-good
-----------------------------------
전달은 `ondevice/config_apply.py::ConfigUpdate`와 같은 모양이다(최초 full,
이후 delta, 검증 실패 시 기존 정상본 유지). 실제로 그 모듈의
`ConfigApplier`를 내부에서 **재사용**하므로 병합·검증·LKG 규칙이 두 벌로
갈라지지 않는다. 디스크에는 마지막 두 버전을 남겨, 재시작 때 활성 버전이
읽히지 않으면 직전 정상 버전으로 내려앉는다.

AI-B-10 — 말단 경량
-------------------
표준 라이브러리 sqlite3 파일 하나. 브로커도 수집기도 데몬도 없다.

도메인 중립 (절대 준수 원칙 #3)
-------------------------------
`item_id`, 파라미터, 자율 등급은 전부 발급자가 준 데이터다. 드론과 로봇의
차이는 이 파일의 분기가 아니라 전달된 항목의 내용 차이다.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping

from mission_runtime.execution.mission import (
    MissionItem,
    MissionItemOutcome,
    MissionSpec,
    MissionVerdict,
)
from mission_runtime.ondevice.config_apply import ConfigApplier, ConfigUpdate

# --- 사유 통제 어휘 ----------------------------------------------------------
# `SelectionResult.reason`·`residency`와 같은 규약: ':' 앞이 토큰, 뒤가 데이터.
# 등록처는 `contracts/data_dictionary.py::MISSION_CACHE_REASONS`.

MISSION_ACCEPTED = "mission_accepted"                       # + ":<version>"
MISSION_UNCHANGED = "mission_unchanged"                     # + ":<version>" 같은 버전 재전달
REJECT_MISSING_ORIGIN_COMMAND = "mission_rejected_no_origin_command"
REJECT_NO_BASELINE = "mission_rejected_no_baseline_for_delta"
REJECT_VERSION_NOT_NEWER = "mission_rejected_version_not_newer"   # + ":<new><active>"
REJECT_MISSION_MISMATCH = "mission_rejected_mission_id_mismatch"  # + ":<other>"
REJECT_VALIDATION_FAILED = "mission_rejected_validation_failed"
REJECT_MALFORMED = "mission_rejected_malformed"                   # + ":<detail>"

RESTORED_ACTIVE = "mission_restored"                        # + ":<version>"
RESTORED_LAST_KNOWN_GOOD = "mission_restored_last_known_good"  # + ":<version>"
RESTORE_FAILED = "mission_restore_failed"
PROGRESS_KEPT = "mission_progress_kept"                     # + ":<item_id>"
PROGRESS_RESET_CONTENT_CHANGED = "mission_progress_reset_content_changed"  # + ":<item_id>"
PROGRESS_DROPPED_ITEM_REMOVED = "mission_progress_dropped_item_removed"    # + ":<item_id>"
INTERRUPTED_BY_RESTART = "mission_item_interrupted_by_restart"             # + ":<item_id>"

BLOCKED_SAFETY_SUSPENDED = "mission_blocked_safety_suspended"
BLOCKED_DEADLINE_PASSED = "mission_blocked_deadline_passed"   # + ":<deadline>"
BLOCKED_NEEDS_FRESH_COMMAND = "mission_blocked_needs_fresh_command"  # + ":<item_id>"

#: 이 모듈이 만들어내는 모든 토큰. 사전이 소비한다.
MISSION_CACHE_REASONS: tuple[str, ...] = (
    MISSION_ACCEPTED,
    MISSION_UNCHANGED,
    REJECT_MISSING_ORIGIN_COMMAND,
    REJECT_NO_BASELINE,
    REJECT_VERSION_NOT_NEWER,
    REJECT_MISSION_MISMATCH,
    REJECT_VALIDATION_FAILED,
    REJECT_MALFORMED,
    RESTORED_ACTIVE,
    RESTORED_LAST_KNOWN_GOOD,
    RESTORE_FAILED,
    PROGRESS_KEPT,
    PROGRESS_RESET_CONTENT_CHANGED,
    PROGRESS_DROPPED_ITEM_REMOVED,
    INTERRUPTED_BY_RESTART,
    BLOCKED_SAFETY_SUSPENDED,
    BLOCKED_DEADLINE_PASSED,
    BLOCKED_NEEDS_FRESH_COMMAND,
)


class MissionAutonomy(str, Enum):
    """링크가 없을 때 이 항목을 이어서 해도 되는가 — **발급자가** 정한다.

    AI-C-19의 경계를 데이터로 표현한 것이다. 기본값이 보수적인 쪽인 이유는
    "말하지 않았다"를 "해도 된다"로 읽으면 AI가 자율 범위를 스스로 넓히는
    것과 같아지기 때문이다.
    """

    #: 이미 승인·전달됐고, 링크 없이 이어서 수행해도 된다고 발급자가 명시한 항목.
    AUTONOMOUS_WHEN_CACHED = "AUTONOMOUS_WHEN_CACHED"
    #: 수행하려면 링크가 돌아와 새 물리 명령을 받아야 하는 항목(기본값).
    REQUIRES_FRESH_COMMAND = "REQUIRES_FRESH_COMMAND"


class CachedItemState(str, Enum):
    """진행 상태. `MissionItemOutcome`(결과)과 다른 축이다.

    PENDING     - 아직 시작하지 않음
    IN_PROGRESS - 시작했고 아직 끝나지 않음
    DONE        - 끝났고 `outcome`이 있다
    INTERRUPTED - 시작했는데 프로세스가 죽어 실행 주체를 잃었다. FAILED가
                  아니다(AI-B-05: 프로세스 생사 ≠ 임무 성패).
    """

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    INTERRUPTED = "INTERRUPTED"


@dataclass(frozen=True)
class CachedMissionItem:
    """전달된 임무 항목 하나. 내용은 전부 발급자가 준 데이터다."""

    item_id: str
    required: bool = True
    autonomy: MissionAutonomy = MissionAutonomy.REQUIRES_FRESH_COMMAND
    order_index: int = 0
    action: str = ""
    parameters: dict = field(default_factory=dict)
    description: str = ""

    def content_fingerprint(self) -> str:
        """항목 **내용**의 지문. 진행 상태를 물려받아도 되는지 판정에 쓴다.

        `execution/command_execution.py`의 명령 지문과 목적이 다르다. 저쪽은
        "같은 명령의 재전달인가"를 보고, 이쪽은 "버전이 올라갔을 때 이 항목의
        기존 진행을 그대로 믿어도 되는가"를 본다. 내용이 바뀌었는데 DONE을
        물려받으면 하지 않은 일을 했다고 말하는 것이 된다.
        """
        import hashlib

        payload = json.dumps(
            {
                "item_id": self.item_id,
                "required": self.required,
                "action": self.action,
                "parameters": self.parameters,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "required": self.required,
            "autonomy": self.autonomy.value,
            "order_index": self.order_index,
            "action": self.action,
            "parameters": dict(self.parameters),
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, raw: Mapping) -> "CachedMissionItem":
        return cls(
            item_id=raw["item_id"],
            required=bool(raw.get("required", True)),
            autonomy=MissionAutonomy(raw.get("autonomy", MissionAutonomy.REQUIRES_FRESH_COMMAND.value)),
            order_index=int(raw.get("order_index", 0)),
            action=raw.get("action", ""),
            parameters=dict(raw.get("parameters", {})),
            description=raw.get("description", ""),
        )


@dataclass(frozen=True)
class MissionDelivery:
    """한 번의 임무 전달 — `ConfigUpdate`(AI-N-02)와 같은 모양.

    `origin_command_id`는 이 임무를 실어 나른 물리 명령의 식별자다(AI-C-20).
    필수인 이유는 AI-C-19다: 출처 없는 임무는 "누가 승인했는가"를 답할 수
    없으므로 캐시에 들어오지 못한다. 중복 실행 방지에는 쓰이지 않는다 —
    그건 `CommandExecutionSupervisor`의 몫이다.

    `deadline`은 `Command.deadline`과 같은 의미다: 이 시각 이후에는 새로 시작하지
    않는다. 링크 없는 동안 무기한 자율 수행을 막는 유일한 시간 경계이기도 하다.
    """

    mission_id: str
    version: int
    full: bool
    items: tuple[CachedMissionItem, ...]
    origin_command_id: str
    approved_by: str | None = None
    issued_at: float | None = None
    deadline: float | None = None

    def as_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "version": self.version,
            "origin_command_id": self.origin_command_id,
            "approved_by": self.approved_by,
            "issued_at": self.issued_at,
            "deadline": self.deadline,
            "items": [item.as_dict() for item in self.items],
        }


@dataclass(frozen=True)
class CachedMission:
    """캐시에 활성 상태로 들어 있는 임무의 내용(진행 상태는 별도)."""

    mission_id: str
    version: int
    items: tuple[CachedMissionItem, ...]
    origin_command_id: str
    approved_by: str | None = None
    issued_at: float | None = None
    deadline: float | None = None

    def item(self, item_id: str) -> CachedMissionItem | None:
        for candidate in self.items:
            if candidate.item_id == item_id:
                return candidate
        return None

    def spec(self) -> MissionSpec:
        """`execution/mission.py`의 판정기로 넘길 선언. 판정 규칙을 복제하지 않는다."""
        return MissionSpec(
            self.mission_id,
            [
                MissionItem(item.item_id, required=item.required, description=item.description)
                for item in self.items
            ],
        )


@dataclass(frozen=True)
class ItemProgress:
    item_id: str
    state: CachedItemState = CachedItemState.PENDING
    outcome: MissionItemOutcome | None = None
    updated_at: float | None = None
    #: 이 항목을 실제로 실행한 물리 명령. 추적용이며 수락 판정에는 쓰지 않는다.
    command_id: str | None = None


@dataclass(frozen=True)
class MissionApplyResult:
    accepted: bool
    reason: str
    version: int | None = None
    #: 진행 상태가 어떻게 이월됐는지 — 항목별 사유 토큰.
    progress_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class MissionSnapshot:
    """링크가 끊긴 채 재시작한 뒤에도 답할 수 있어야 하는 것 전부."""

    mission_id: str | None
    version: int | None
    origin_command_id: str | None
    approved_by: str | None
    deadline: float | None
    #: 항목별 진행. 완료/미완료가 여기서 갈린다.
    progress: tuple[ItemProgress, ...] = ()
    #: 링크 없이 이어서 해도 되는 항목(발급자가 미리 허가한 것만).
    resumable_without_link: tuple[str, ...] = ()
    #: 링크가 돌아와 새 명령을 받아야 움직이는 항목.
    blocked_pending_command: tuple[str, ...] = ()
    #: 자율 수행이 통째로 막힌 사유(있다면). 항목별 사유가 아니다.
    autonomy_block_reason: str | None = None
    safety_suspended: bool = False
    safety_suspension_reason: str | None = None
    #: 이 임무가 겪은 프로세스 재시작 횟수. 임무 성패와 섞지 않는다(AI-B-05).
    process_restarts: int = 0
    restore_reason: str | None = None

    def outstanding(self) -> tuple[str, ...]:
        return tuple(
            p.item_id for p in self.progress if p.state is not CachedItemState.DONE
        )

    def completed(self) -> tuple[str, ...]:
        return tuple(p.item_id for p in self.progress if p.state is CachedItemState.DONE)


#: 디스크에 남기는 버전 수. 활성본 + 직전 정상본(=last-known-good) 한 벌.
_KEEP_VERSIONS = 2


class MissionCache:
    """임무 내용과 진행을 디스크에 남기는 말단 캐시.

    `state_path`가 `None`이면 메모리 전용으로 동작한다(시험·시뮬레이터용).
    """

    def __init__(
        self,
        state_path: str | Path | None = None,
        *,
        validate_fn: Callable[[CachedMission], bool] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._clock = clock
        self._validate_fn = validate_fn
        self._active: CachedMission | None = None
        self._progress: dict[str, ItemProgress] = {}
        #: 항목별 내용 지문(진행 이월 판정용).
        self._fingerprints: dict[str, str] = {}
        self._safety_suspended = False
        self._safety_reason: str | None = None
        self._process_restarts = 0
        self._restore_reason: str | None = None
        # AI-N-02의 병합·검증·LKG 규칙을 재구현하지 않고 그대로 빌려 쓴다.
        # 여기서 다루는 "설정"은 항목 사전 `{item_id: item.as_dict()}`이다.
        self._applier = ConfigApplier(validate_fn=self._validate_items)
        self._pending_validation_target: CachedMission | None = None

        self._db = sqlite3.connect(str(state_path), check_same_thread=False) if state_path else None
        if self._db is not None:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS mission_content "
                "(mission_id TEXT NOT NULL, version INTEGER NOT NULL, delivery TEXT NOT NULL, "
                "active INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (mission_id, version))"
            )
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS mission_progress "
                "(mission_id TEXT NOT NULL, item_id TEXT NOT NULL, state TEXT NOT NULL, "
                "outcome TEXT, updated_at REAL, command_id TEXT, fingerprint TEXT, "
                "PRIMARY KEY (mission_id, item_id))"
            )
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS mission_flag (name TEXT PRIMARY KEY, value TEXT)"
            )
            self._db.commit()
            self._load()

    # --- 조회 ---------------------------------------------------------------

    @property
    def active_mission(self) -> CachedMission | None:
        return self._active

    @property
    def active_version(self) -> int | None:
        return self._active.version if self._active else None

    @property
    def safety_suspended(self) -> bool:
        return self._safety_suspended

    def progress(self) -> tuple[ItemProgress, ...]:
        if self._active is None:
            return ()
        return tuple(
            self._progress.get(item.item_id, ItemProgress(item.item_id))
            for item in sorted(self._active.items, key=lambda i: (i.order_index, i.item_id))
        )

    # --- 전달 적용 (AI-N-02) -------------------------------------------------

    def apply(self, delivery: MissionDelivery) -> MissionApplyResult:
        """임무 전달 1건을 적용한다. 거부되면 기존 정상본은 그대로 남는다."""
        if not delivery.origin_command_id:
            # AI-C-19: 출처 없는 임무는 들어오지 못한다.
            return MissionApplyResult(False, REJECT_MISSING_ORIGIN_COMMAND)
        if not delivery.mission_id:
            return MissionApplyResult(False, f"{REJECT_MALFORMED}:missing_mission_id")

        active = self._active
        if active is not None and delivery.mission_id != active.mission_id:
            if not delivery.full:
                # 다른 임무의 delta는 병합 대상이 없다.
                return MissionApplyResult(
                    False, f"{REJECT_MISSION_MISMATCH}:{active.mission_id}"
                )
            # 새 임무의 full 전달은 교체다. 이전 임무의 진행은 이월되지 않는다.
            self._applier = ConfigApplier(validate_fn=self._validate_items)
            active = None

        if active is None and not delivery.full:
            return MissionApplyResult(False, REJECT_NO_BASELINE)

        if active is not None:
            if delivery.version < active.version:
                return MissionApplyResult(
                    False, f"{REJECT_VERSION_NOT_NEWER}:{delivery.version}<{active.version}"
                )
            if delivery.version == active.version:
                # 같은 내용의 재전달은 무해한 반복이어야 한다 — 진행을 되감지 않는다.
                return MissionApplyResult(True, f"{MISSION_UNCHANGED}:{delivery.version}",
                                          version=active.version)

        candidate_items = {item.item_id: item.as_dict() for item in delivery.items}
        self._pending_validation_target = CachedMission(
            mission_id=delivery.mission_id,
            version=delivery.version,
            items=(),  # 검증 콜백이 병합 결과로 채운다
            origin_command_id=delivery.origin_command_id,
            approved_by=delivery.approved_by,
            issued_at=delivery.issued_at,
            deadline=delivery.deadline,
        )
        accepted = self._applier.apply(
            ConfigUpdate(version=delivery.version, full=delivery.full, items=candidate_items)
        )
        self._pending_validation_target = None
        if not accepted:
            return MissionApplyResult(False, REJECT_VALIDATION_FAILED)

        merged = tuple(
            sorted(
                (CachedMissionItem.from_dict(raw) for raw in self._applier.active_config.values()),
                key=lambda i: (i.order_index, i.item_id),
            )
        )
        mission = CachedMission(
            mission_id=delivery.mission_id,
            version=delivery.version,
            items=merged,
            origin_command_id=delivery.origin_command_id,
            approved_by=delivery.approved_by,
            issued_at=delivery.issued_at,
            deadline=delivery.deadline,
        )
        notes = self._carry_progress(mission)
        self._active = mission
        self._persist_content(delivery, mission)
        self._persist_all_progress()
        return MissionApplyResult(
            True, f"{MISSION_ACCEPTED}:{mission.version}", version=mission.version,
            progress_notes=notes,
        )

    def _validate_items(self, merged_raw: dict) -> bool:
        """`ConfigApplier`가 병합 결과를 넘겨주는 자리. 여기서만 거부한다."""
        target = self._pending_validation_target
        if target is None:
            return False
        try:
            items = tuple(CachedMissionItem.from_dict(raw) for raw in merged_raw.values())
        except (KeyError, ValueError, TypeError):
            return False
        try:
            # 임무 선언 규칙(필수 항목 최소 1개, 중복 id 금지)은 `MissionSpec`이
            # 이미 소유하고 있다 — 여기서 다시 쓰지 않고 그것으로 검증한다.
            candidate = replace(target, items=items)
            candidate.spec()
        except ValueError:
            return False
        if self._validate_fn is not None and not self._validate_fn(candidate):
            return False
        return True

    def _carry_progress(self, mission: CachedMission) -> tuple[str, ...]:
        """버전이 올라갈 때 진행 상태를 물려받거나 되돌린다."""
        notes: list[str] = []
        kept: dict[str, ItemProgress] = {}
        fingerprints = {item.item_id: item.content_fingerprint() for item in mission.items}
        for item_id, progress in self._progress.items():
            if item_id not in fingerprints:
                notes.append(f"{PROGRESS_DROPPED_ITEM_REMOVED}:{item_id}")
                continue
            previous_fp = self._fingerprints.get(item_id)
            if previous_fp is not None and previous_fp != fingerprints[item_id]:
                # 내용이 바뀐 항목의 DONE을 물려받으면 하지 않은 일을 했다고
                # 말하는 것이 된다.
                notes.append(f"{PROGRESS_RESET_CONTENT_CHANGED}:{item_id}")
                continue
            kept[item_id] = progress
            notes.append(f"{PROGRESS_KEPT}:{item_id}")
        self._progress = kept
        self._fingerprints = fingerprints
        return tuple(notes)

    # --- 진행 기록 -----------------------------------------------------------

    def begin(self, item_id: str, *, command_id: str | None = None) -> ItemProgress:
        return self._set(item_id, CachedItemState.IN_PROGRESS, None, command_id)

    def complete(
        self, item_id: str, outcome: MissionItemOutcome, *, command_id: str | None = None
    ) -> ItemProgress:
        return self._set(item_id, CachedItemState.DONE, outcome, command_id)

    def _set(
        self,
        item_id: str,
        state: CachedItemState,
        outcome: MissionItemOutcome | None,
        command_id: str | None,
    ) -> ItemProgress:
        if self._active is None or self._active.item(item_id) is None:
            raise ValueError(f"unknown mission item: {item_id!r}")
        existing = self._progress.get(item_id)
        progress = ItemProgress(
            item_id=item_id,
            state=state,
            outcome=outcome,
            updated_at=self._clock(),
            command_id=command_id or (existing.command_id if existing else None),
        )
        self._progress[item_id] = progress
        self._persist_progress(item_id)
        return progress

    # --- 자율 경계 (AI-C-19) --------------------------------------------------

    def _autonomy_block_reason(self, now: float | None = None) -> str | None:
        if self._safety_suspended:
            return BLOCKED_SAFETY_SUSPENDED
        if self._active is not None and self._active.deadline is not None:
            at = now if now is not None else self._clock()
            if at > self._active.deadline:
                return f"{BLOCKED_DEADLINE_PASSED}:{self._active.deadline:g}"
        return None

    def resumable_without_link(self, *, now: float | None = None) -> tuple[str, ...]:
        """링크 없이 이어서 수행해도 되는 미완료 항목.

        "AI가 해도 된다고 판단한 일"이 아니라 "발급자가 전달 시점에 미리
        허가해 둔 일 중 아직 안 끝난 것"이다(AI-C-19). 안전 정지 중이거나
        임무 유효기한이 지났으면 아무것도 돌려주지 않는다.
        """
        if self._active is None or self._autonomy_block_reason(now) is not None:
            return ()
        return tuple(
            p.item_id
            for p in self.progress()
            if p.state is not CachedItemState.DONE
            and self._active.item(p.item_id).autonomy is MissionAutonomy.AUTONOMOUS_WHEN_CACHED
        )

    def blocked_pending_command(self, *, now: float | None = None) -> tuple[str, ...]:
        """링크가 돌아와 새 물리 명령을 받아야만 움직일 수 있는 미완료 항목."""
        if self._active is None:
            return ()
        outstanding = tuple(
            p.item_id for p in self.progress() if p.state is not CachedItemState.DONE
        )
        if self._autonomy_block_reason(now) is not None:
            # 자율 수행이 통째로 막히면 미완료 전부가 명령 대기다.
            return outstanding
        resumable = set(self.resumable_without_link(now=now))
        return tuple(item_id for item_id in outstanding if item_id not in resumable)

    # --- 긴급정지 (AI-C-20) ---------------------------------------------------

    def suspend_for_safety(self, reason: str) -> None:
        """로컬 안전 정지. 링크도 백엔드도 필요 없다.

        AI-C-20: "상위 네트워크 명령만을 안전 기능의 유일한 경로로 사용해서는
        안 된다." 이 호출 이후 캐시는 어떤 항목에 대해서도 "이어서 해도 된다"고
        말하지 않는다.
        """
        self._safety_suspended = True
        self._safety_reason = reason
        self._persist_flag("safety_suspended", "1")
        self._persist_flag("safety_reason", reason)

    def clear_safety_suspension(self, reason: str) -> None:
        """해제는 반드시 명시적이어야 하고 사유가 남는다."""
        self._safety_suspended = False
        self._safety_reason = None
        self._persist_flag("safety_suspended", "0")
        self._persist_flag("safety_reason", "")
        self._persist_flag("safety_cleared_reason", reason)

    # --- 판정·스냅샷 ----------------------------------------------------------

    def verdict(self) -> MissionVerdict | None:
        """`execution/mission.py`의 판정기로 현재 진행을 판정한다.

        INTERRUPTED·IN_PROGRESS 항목은 결과를 보고하지 않으므로 필수 항목이
        남아 있으면 NOT_RUN이 된다 — FAILED가 아니다(AI-B-05, AI-O-02).
        """
        if self._active is None:
            return None
        outcomes = {
            p.item_id: p.outcome
            for p in self.progress()
            if p.state is CachedItemState.DONE and p.outcome is not None
        }
        return self._active.spec().evaluate(outcomes)

    def snapshot(self, *, now: float | None = None) -> MissionSnapshot:
        if self._active is None:
            return MissionSnapshot(
                mission_id=None, version=None, origin_command_id=None, approved_by=None,
                deadline=None, safety_suspended=self._safety_suspended,
                safety_suspension_reason=self._safety_reason,
                process_restarts=self._process_restarts,
                restore_reason=self._restore_reason,
            )
        return MissionSnapshot(
            mission_id=self._active.mission_id,
            version=self._active.version,
            origin_command_id=self._active.origin_command_id,
            approved_by=self._active.approved_by,
            deadline=self._active.deadline,
            progress=self.progress(),
            resumable_without_link=self.resumable_without_link(now=now),
            blocked_pending_command=self.blocked_pending_command(now=now),
            autonomy_block_reason=self._autonomy_block_reason(now),
            safety_suspended=self._safety_suspended,
            safety_suspension_reason=self._safety_reason,
            process_restarts=self._process_restarts,
            restore_reason=self._restore_reason,
        )

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    # --- 지속화 --------------------------------------------------------------

    def _persist_content(self, delivery: MissionDelivery, mission: CachedMission) -> None:
        if self._db is None:
            return
        stored = dict(delivery.as_dict())
        # 저장하는 것은 전달본이 아니라 **병합된 활성본**이다. 재시작 때 delta
        # 여러 개를 다시 접어 올릴 필요가 없어야 복원이 단순해진다.
        stored["items"] = [item.as_dict() for item in mission.items]
        # 다른 임무가 활성이 되면 이전 임무의 내용·진행은 남겨 두지 않는다 —
        # 남겨 두면 재시작 복원이 "어느 임무 중이었나"에 두 가지로 답하게 된다.
        self._db.execute(
            "DELETE FROM mission_content WHERE mission_id != ?", (mission.mission_id,)
        )
        self._db.execute(
            "DELETE FROM mission_progress WHERE mission_id != ?", (mission.mission_id,)
        )
        self._db.execute("UPDATE mission_content SET active = 0")
        self._db.execute(
            "INSERT OR REPLACE INTO mission_content (mission_id, version, delivery, active) "
            "VALUES (?, ?, ?, 1)",
            (mission.mission_id, mission.version, json.dumps(stored)),
        )
        # 활성본 + 직전 정상본만 남긴다(AI-N-02의 last-known-good).
        self._db.execute(
            "DELETE FROM mission_content WHERE mission_id = ? AND version NOT IN "
            "(SELECT version FROM mission_content WHERE mission_id = ? "
            " ORDER BY version DESC LIMIT ?)",
            (mission.mission_id, mission.mission_id, _KEEP_VERSIONS),
        )
        self._db.commit()

    def _persist_progress(self, item_id: str) -> None:
        if self._db is None or self._active is None:
            return
        progress = self._progress[item_id]
        self._db.execute(
            "INSERT OR REPLACE INTO mission_progress "
            "(mission_id, item_id, state, outcome, updated_at, command_id, fingerprint) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                self._active.mission_id, item_id, progress.state.value,
                progress.outcome.value if progress.outcome else None,
                progress.updated_at, progress.command_id,
                self._fingerprints.get(item_id),
            ),
        )
        self._db.commit()

    def _persist_all_progress(self) -> None:
        if self._db is None or self._active is None:
            return
        self._db.execute(
            "DELETE FROM mission_progress WHERE mission_id = ?", (self._active.mission_id,)
        )
        for item_id in self._progress:
            self._persist_progress(item_id)
        self._db.commit()

    def _persist_flag(self, name: str, value: str) -> None:
        if self._db is None:
            return
        self._db.execute(
            "INSERT OR REPLACE INTO mission_flag (name, value) VALUES (?, ?)", (name, value)
        )
        self._db.commit()

    def _load(self) -> None:
        """재시작 복원. 활성본이 읽히지 않으면 직전 정상본으로 내려앉는다."""
        assert self._db is not None
        rows = list(
            self._db.execute(
                "SELECT mission_id, version, delivery, active FROM mission_content "
                "ORDER BY active DESC, version DESC"
            )
        )
        if not rows:
            return
        self._process_restarts = int(self._read_flag("process_restarts") or 0) + 1
        self._persist_flag("process_restarts", str(self._process_restarts))
        self._safety_suspended = self._read_flag("safety_suspended") == "1"
        self._safety_reason = self._read_flag("safety_reason") or None

        restored: CachedMission | None = None
        reason = RESTORE_FAILED
        for index, (mission_id, version, raw, active) in enumerate(rows):
            try:
                stored = json.loads(raw)
                items = tuple(
                    sorted(
                        (CachedMissionItem.from_dict(item) for item in stored["items"]),
                        key=lambda i: (i.order_index, i.item_id),
                    )
                )
                candidate = CachedMission(
                    mission_id=mission_id, version=int(version), items=items,
                    origin_command_id=stored["origin_command_id"],
                    approved_by=stored.get("approved_by"),
                    issued_at=stored.get("issued_at"),
                    deadline=stored.get("deadline"),
                )
                candidate.spec()  # 선언 규칙 재검증
            except (KeyError, ValueError, TypeError, json.JSONDecodeError):
                continue
            restored = candidate
            reason = (
                f"{RESTORED_ACTIVE}:{candidate.version}"
                if active and index == 0
                else f"{RESTORED_LAST_KNOWN_GOOD}:{candidate.version}"
            )
            break

        self._restore_reason = reason
        if restored is None:
            return

        self._active = restored
        self._fingerprints = {item.item_id: item.content_fingerprint() for item in restored.items}
        self._applier = ConfigApplier(validate_fn=self._validate_items)
        self._pending_validation_target = restored
        self._applier.apply(
            ConfigUpdate(
                version=restored.version, full=True,
                items={item.item_id: item.as_dict() for item in restored.items},
            )
        )
        self._pending_validation_target = None
        self._load_progress(restored)

    def _load_progress(self, mission: CachedMission) -> None:
        assert self._db is not None
        interrupted: list[str] = []
        for item_id, state_raw, outcome_raw, updated_at, command_id, fingerprint in self._db.execute(
            "SELECT item_id, state, outcome, updated_at, command_id, fingerprint "
            "FROM mission_progress WHERE mission_id = ?",
            (mission.mission_id,),
        ):
            item = mission.item(item_id)
            if item is None:
                continue
            if fingerprint is not None and fingerprint != item.content_fingerprint():
                continue
            try:
                state = CachedItemState(state_raw)
            except ValueError:
                continue
            if state is CachedItemState.IN_PROGRESS:
                # 프로세스가 죽으면서 실행 주체를 잃었다. 실패가 아니다(AI-B-05).
                state = CachedItemState.INTERRUPTED
                interrupted.append(item_id)
            outcome = MissionItemOutcome(outcome_raw) if outcome_raw else None
            self._progress[item_id] = ItemProgress(
                item_id=item_id, state=state, outcome=outcome,
                updated_at=updated_at, command_id=command_id,
            )
        for item_id in interrupted:
            self._persist_progress(item_id)
        if interrupted and self._restore_reason:
            self._restore_reason = ";".join(
                [self._restore_reason] + [f"{INTERRUPTED_BY_RESTART}:{i}" for i in interrupted]
            )

    def _read_flag(self, name: str) -> str | None:
        if self._db is None:
            return None
        row = self._db.execute(
            "SELECT value FROM mission_flag WHERE name = ?", (name,)
        ).fetchone()
        return row[0] if row else None



def describe(snapshot: MissionSnapshot) -> str:
    """운영자가 한 줄로 읽는 상태 — 무엇을 스스로 할 수 있고 무엇이 막혔는가."""
    if snapshot.mission_id is None:
        return "no cached mission"
    parts = [
        f"{snapshot.mission_id}@v{snapshot.version}",
        f"done={len(snapshot.completed())}/{len(snapshot.progress)}",
        f"autonomous={list(snapshot.resumable_without_link)}",
        f"needs_command={list(snapshot.blocked_pending_command)}",
    ]
    if snapshot.autonomy_block_reason:
        parts.append(f"blocked={snapshot.autonomy_block_reason}")
    if snapshot.process_restarts:
        parts.append(f"restarts={snapshot.process_restarts}")
    return " ".join(parts)
