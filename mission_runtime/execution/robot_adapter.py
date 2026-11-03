"""말단(로봇 옆 RPi)에서 물리 명령 계약을 그 로봇의 명령으로 옮기는 어댑터.

implements: AI-C-20, AI-C-19, AI-C-04, AI-C-05, AI-B-03, AI-B-05, AI-B-10, AI-N-02, AI-N-03
tests: tests/test_robot_adapter.py

무엇을 푸는가
-------------
관리자가 가시화 UI에서 승인하면 백엔드가 물리 명령을 발급하고, 그것이 합의된
규약(`specs/physical-command-interface.md`)을 타고 로봇 옆에 유선으로
붙어 있는 말단까지 내려온다. **그 말단에서 규약을 그 로봇의 어휘로 옮기는 자리**가
여기다. `execution/physical_command_gateway.py`가 같은 규약의 *엣지 쪽* 절반이라면
이 모듈은 *장치 쪽* 절반이다 — 같은 계약의 반대편이고, 그래서 둘 다 있어야 계약이
양끝에서 검증된다.

이 모듈이 소유하는 것과 소유하지 않는 것
----------------------------------------
소유한다(계약):
  * 수락과 거부의 분리 — 거부는 실행 상태가 아니다(AI-C-20).
  * 같은 `command_id` 재전달 시 물리 동작 재실행 금지(§5-1).
  * 유효기한 지난 명령 거부(§5-2), 취소 우선(§5-3), 미선언 action 거부(§5-4).
  * 취소 **수락**과 실제 `CANCELED` **도달**의 구분(AI-C-20).
  * 긴급정지를 일반 취소와 분리하고 네트워크 경로에 의존하지 않기(AI-C-20, §7).

소유하지 않는다:
  * **명령을 만들지 않는다(AI-C-19).** `submit()`은 이미 발급된 `Command`를 받을
    뿐이고, 이 파일 어디에도 `Command(...)`를 생성하는 경로가 없다. 대상 선택·
    우선순위 매기기도 없다.
  * **로봇의 구체 명령을 모른다(절대 준수 원칙 #1, #2, AI-C-04).** 실제 SDK·UDP·
    시리얼은 `RobotControlBackend`(providers/adapters.py) 뒤에 있고, 이 파일에는
    벤더 이름이 한 번도 나오지 않는다.
  * **장치 최종 가용성을 판정하지 않는다(AI-O-04, 원칙 #15).** `readiness()`는
    "지금 이 명령을 시작할 수 있는가"라는 사전조건일 뿐이다.
  * **구역이 바뀌면 캐시된 임무가 유효한가**를 정하지 않는다 — 그 계약은 아직
    합의되지 않았다(`reports/2026-09-20_0926_HW-협의-패치패키지.md` N2). 그래서
    `note_zone_entry()`는 사실만 기록하고 판단하지 않는다.

계약 판정을 두 벌 만들지 않는다
-------------------------------
멱등·유효기한·취소 우선·터미널 상태는 `execution/command_execution.py::
CommandExecutionSupervisor`가 이미 SQLite 지속성까지 포함해 구현한다. 여기서
다시 구현하면 두 판정이 어긋나는 순간 어느 쪽이 참인지 말할 수 없다. 이 어댑터는
그 감독자를 **구성(compose)** 하고, 감독자가 다루지 않는 것 하나만 앞에 붙인다 —
**수락 전 심사(admission gate)** 다. 감독자는 `ActionHandler`가 실패하면
`ABORTED`를 내지만, "애초에 수락하지 않는다"는 표현 수단이 없기 때문이다.

심사 순서는 HW 파트 장치 구현(HW 저장소 `pi/common/physical_command.py`)과
같은 순서로 맞췄다 — 멱등 → 유효기한 → 미선언 action → 사전조건. 같은 규약의
두 구현이 같은 입력에 다른 코드를 돌려주면 규약이 두 개인 것과 같다.

거부는 기억하지 않는다
----------------------
심사는 **처음 보는 `command_id`에만** 돈다. 이미 수락된 id가 다시 오면 심사를
건너뛰고 감독자의 캐시된 수락을 그대로 돌려준다 — §5-1이 "이전에 보냈던
`CommandAcceptance`를 그대로 다시 보낸다"고 하기 때문이다. 반대로 **거부된 id는
기억하지 않는다**: 거부는 아무것도 실행하지 않았으므로 재전달 시 다시 심사해야
하고, 그 사이에 사전조건이 회복됐을 수 있다. HW 구현도 수락된 것만 `seen`에
넣는다(같은 파일 `_on_command`).

자율 경계 — 링크가 끊긴 동안 무엇을 이어서 하는가
--------------------------------------------------
명령이 *도착했다*는 것은 링크가 있었다는 뜻이므로 `submit()` 경로에 자율 판정은
없다. 자율이 문제가 되는 것은 **이미 받아 둔 임무를 링크 없이 이어서 할 때**다.
그 판정은 `ondevice/mission_cache.py`가 이미 소유하므로(발급자가 붙인
`MissionAutonomy`, 기본값은 보수적인 `REQUIRES_FRESH_COMMAND`) 여기서는 판정하지
않고 **집행**만 한다 — `resume_without_link()`는 캐시가 허가한 목록만 backend로
내려보내고, 허가되지 않은 항목은 손대지 않는다.

**`autonomy` 값은 오늘 물리 명령 와이어로 오지 않는다.** `Command.parameters`가
`map<string, double>`이라 문자열 enum을 실을 자리가 없고(spec §8-3 P2), 임무 슬롯
제안(`MissionAssignment mission = 8`, 패치 패키지 §0 항목 M)은 HW 합의 전이라
적용하지 않았다. 그래서 오늘 경로는 둘뿐이다:

1. **외부 구성 경로(AI-N-02).** 구역 엣지가 주는 구성으로 `MissionDelivery`가
   들어오면 `autonomy`가 문자열로 그대로 실린다 — 이 경로는 물리 명령 와이어가
   아니므로 P2 제약을 받지 않는다. `ingest_mission()`이 그 입구다.
2. **물리 명령 경로.** 임무가 명령으로 오면 항목별 autonomy를 실을 자리가 없다.
   이때 `ingest_mission()`은 값을 **지어내지 않고** 캐시 기본값
   `REQUIRES_FRESH_COMMAND`를 그대로 두며, `wire_gaps["mission.autonomy"]`를
   올린다. 결과적으로 링크가 끊기면 그 임무는 아무것도 이어서 하지 않는다.
   보수적인 쪽으로 틀린다 — 미선언을 허가로 읽으면 AI가 자기 자율 범위를 스스로
   넓히는 것과 같기 때문이다(AI-C-19).

없는 선언을 지어내지 않는다 (AI-C-18, AI-C-05)
-----------------------------------------------
backend의 `Capability`는 이름만 있을 수 있다(현재 와이어가 그렇다 — §8-3 P7).
어댑터는 **이름으로만** 미선언 판정을 하고, 덜 선언된 것을 결손으로 취급해
거부하지 않는다. 대신 `wire_gaps`에 세어 둔다.
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from mission_runtime.contracts.physical_command import (
    CancelCommandRequest,
    CancelCommandResponse,
    Capability,
    Command,
    CommandAcceptance,
    CommandResult,
    ExecutionStatus,
    Rejection,
    RejectionCode,
)
from mission_runtime.execution.command_execution import CommandExecutionSupervisor
from mission_runtime.execution.mission import MissionItemOutcome

# --- 사유 통제 어휘 ----------------------------------------------------------
# `mission_cache`·`zone_handover`와 같은 규약: ':' 앞이 토큰, 뒤가 데이터.
# 등록처는 `contracts/data_dictionary.py::ROBOT_ADAPTER_REASONS`.

ACCEPTED = "robot_command_accepted"
REDELIVERED = "robot_command_redelivered"                 # 재전달 — 재실행 없음
REJECT_ACTION_NOT_DECLARED = "robot_rejected_action_not_declared"   # + ":<action>"
REJECT_DEADLINE_PASSED = "robot_rejected_deadline_passed"           # + ":<deadline>"
REJECT_BACKEND_NOT_READY = "robot_rejected_backend_not_ready"       # + ":<detail>"
REJECT_EMERGENCY_STOP_LATCHED = "robot_rejected_emergency_stop_latched"  # + ":<reason>"
REJECT_BACKEND_VALIDATION = "robot_rejected_backend_validation"     # + ":<detail>"

CANCEL_FORWARDED = "robot_cancel_forwarded"
CANCEL_REFUSED_BY_BACKEND = "robot_cancel_refused_by_backend"

ESTOP_ENGAGED = "robot_emergency_stop_engaged"            # + ":<reason>"
ESTOP_BACKEND_UNREACHABLE = "robot_emergency_stop_backend_unreachable"
ESTOP_CLEARED = "robot_emergency_stop_cleared"            # + ":<reason>"

RESUME_NO_MISSION_CACHE = "robot_resume_no_mission_cache"
RESUME_BLOCKED_EMERGENCY_STOP = "robot_resume_blocked_emergency_stop"
RESUME_EXECUTED = "robot_resume_executed"                 # + ":<item_id>"
RESUME_FAILED = "robot_resume_failed"                     # + ":<item_id>"
RESUME_ACTION_NOT_DECLARED = "robot_resume_action_not_declared"  # + ":<item_id>"
RESUME_BLOCKED_PENDING_COMMAND = "robot_resume_blocked_pending_command"  # + ":<item_id>"

ZONE_ENTERED = "robot_zone_entered"                       # + ":<zone>"

#: 와이어에 자리가 없어 이 어댑터가 받지 못한 정보의 카운터 키.
#: `providers/physical_command_protobuf.py::wire_gaps`와 같은 목적·같은 이름 규약이다.
WIRE_GAP_MISSION_AUTONOMY = "mission.autonomy"
WIRE_GAP_CAPABILITY_UNDER_DECLARED = "capability.under_declared"
WIRE_GAP_COMMAND_CORRELATION_ID = "command.correlation_id"


class RobotCommandRejected(Exception):
    """backend가 "이 명령은 수락할 수 없다"고 말하는 방법.

    `execute()` 중의 실패(→ ABORTED)와 **수락 전 거부**(→ 실행 상태에 들어가지
    않음)는 다른 사건이므로 표현 수단도 다르다(AI-C-20). backend가 선택적으로
    `validate(action, parameters)`를 제공하면 어댑터가 수락 전에 호출한다.
    """

    def __init__(self, code: RejectionCode | str, message: str = "") -> None:
        self.code = code if isinstance(code, RejectionCode) else RejectionCode(code)
        self.message = message
        super().__init__(f"{self.code.value}: {message}")


@dataclass(frozen=True)
class EmergencyStopOutcome:
    """긴급정지 1회의 결과.

    `backend_reached`가 False여도 `latched`는 True다 — 정지 경로에 닿았는지
    확인할 수 없을 때 명령을 계속 받는 쪽이 더 위험하기 때문이다. 둘을 같은
    불리언에 담으면 "멈췄다고 생각했는데 아니었다"가 표현되지 않는다.
    """

    reason: str
    at: float
    latched: bool
    backend_reached: bool
    #: 이 정지 때문에 CANCELING으로 넘어간 진행 중 명령들.
    canceling_command_ids: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResumeOutcome:
    """링크 없이 이어서 수행한 임무 항목 하나의 결과."""

    item_id: str
    reason: str
    executed: bool
    outcome: MissionItemOutcome | None = None
    detail: str | None = None


@dataclass(frozen=True)
class AdmissionVerdict:
    """수락 전 심사 결과. `accepted=False`면 실행 상태에 들어가지 않는다."""

    accepted: bool
    reason: str
    rejection: Rejection | None = None


@dataclass
class _ZoneState:
    zone_id: str | None = None
    requires_config_refresh: bool = False
    entered_at: float | None = None


class TerminalRobotAdapter:
    """물리 명령 계약(AI-C-20) ↔ 한 대의 로봇 사이의 말단 어댑터.

    로봇이 없어도 전부 돌릴 수 있다 — backend가 `RobotControlBackend`만
    만족하면 되고, 시험은 `providers/fakes.py::FakeRobotBackend`를 쓴다.
    """

    def __init__(
        self,
        backend: Any,
        *,
        device_id: str,
        mission_cache: Any | None = None,
        link_posture: Callable[[], Any] | None = None,
        state_path: str | Path | None = None,
        clock: Callable[[], float] = time.time,
        observability: Any | None = None,
    ) -> None:
        self._backend = backend
        self._device_id = device_id
        self._mission_cache = mission_cache
        self._link_posture = link_posture
        self._clock = clock
        self._observability = observability
        self._lock = threading.RLock()
        self._estop: tuple[str, float] | None = None
        self._zone = _ZoneState()
        self._reasons: list[str] = []
        self.wire_gaps: Counter = Counter()
        self._supervisor = CommandExecutionSupervisor(
            handler=self._run_action,
            cancel_handler=self._forward_stop,
            state_path=state_path,
        )

    # -- 선언 (AI-C-18) --------------------------------------------------

    def capabilities(self) -> tuple[Capability, ...]:
        """backend가 선언한 그대로. 덜 선언된 것을 채워 넣지 않는다."""
        declared = tuple(self._backend.declared_actions())
        for capability in declared:
            if not capability.is_fully_declared():
                self.wire_gaps[WIRE_GAP_CAPABILITY_UNDER_DECLARED] += 1
        return declared

    def declared_action_names(self) -> frozenset[str]:
        return frozenset(capability.name for capability in self._backend.declared_actions())

    # -- 수락 경로 (AI-C-20 §5) -------------------------------------------

    def submit(self, command: Command, *, now: float | None = None) -> CommandAcceptance:
        """명령 한 건을 수락하거나 거부하고, 수락했으면 동기 실행한다.

        `submit_async`와 달리 반환 시점에 이미 터미널 상태다. 실제 취소 경합을
        시험하려면 `submit_async`를 쓴다.
        """
        return self._submit(command, now=now, asynchronous=False)

    def submit_async(self, command: Command, *, now: float | None = None) -> CommandAcceptance:
        """수락만 즉시 돌려주고 실행은 워커에서 — 진짜 동시 취소가 가능해진다."""
        return self._submit(command, now=now, asynchronous=True)

    def _submit(self, command: Command, *, now: float | None, asynchronous: bool) -> CommandAcceptance:
        at = now if now is not None else self._clock()
        with self._lock:
            # §5-1: 이미 아는 id면 심사하지 않는다 — 캐시된 수락을 그대로.
            known = self._supervisor.get_status(command.command_id) is not None
            if known:
                self._note(REDELIVERED)
                return self._supervisor.submit(command, now=at)

            if command.correlation_id is None:
                # 와이어에 자리가 없어 잘린 것인지 원래 없는 것인지는 여기서
                # 구분할 수 없다. 세어만 둔다(§8-3 P1).
                self.wire_gaps[WIRE_GAP_COMMAND_CORRELATION_ID] += 1

            verdict = self._admit(command, at)
            if not verdict.accepted:
                self._note(verdict.reason)
                self._record_event("robot_command_rejected", "warning", {
                    "command_id": command.command_id, "reason": verdict.reason,
                })
                return CommandAcceptance(command.command_id, False, at, verdict.rejection)

        # 심사를 통과했다. 감독자가 멱등·유효기한·터미널 상태를 소유한다.
        self._note(ACCEPTED)
        submit = self._supervisor.submit_async if asynchronous else self._supervisor.submit
        return submit(command, now=at)

    def _admit(self, command: Command, at: float) -> AdmissionVerdict:
        """수락 전 심사. 순서는 HW 장치 구현과 같다(멱등은 호출자가 이미 처리)."""
        # §5-2 유효기한 — 감독자도 같은 판정을 하지만 여기서 먼저 걸러야
        # 미선언 action 보다 먼저 보고된다(HW 구현과 같은 순서).
        if command.deadline is not None and at > command.deadline:
            return AdmissionVerdict(
                False, f"{REJECT_DEADLINE_PASSED}:{command.deadline:g}",
                Rejection(RejectionCode.FAILED_PRECONDITION, "deadline already passed"),
            )

        # §5-4 미선언 action — execute 로직에 들어가기 전에 거부한다.
        if command.action not in self.declared_action_names():
            return AdmissionVerdict(
                False, f"{REJECT_ACTION_NOT_DECLARED}:{command.action}",
                Rejection(RejectionCode.UNIMPLEMENTED, f"action not supported: {command.action}"),
            )

        # 긴급정지가 걸려 있으면 새 물리 동작을 시작하지 않는다. 해제는 명시적
        # 로컬 호출로만 되고, 네트워크 명령이 해제 경로가 아니다(AI-C-20 §7).
        if self._estop is not None:
            reason, _ = self._estop
            return AdmissionVerdict(
                False, f"{REJECT_EMERGENCY_STOP_LATCHED}:{reason}",
                Rejection(RejectionCode.FAILED_PRECONDITION, f"emergency stop latched: {reason}"),
            )

        ready, detail = self._backend.readiness()
        if not ready:
            return AdmissionVerdict(
                False, f"{REJECT_BACKEND_NOT_READY}:{detail or 'unspecified'}",
                Rejection(RejectionCode.FAILED_PRECONDITION, detail or "backend not ready"),
            )

        # backend가 원하면 파라미터를 수락 전에 볼 수 있다. Protocol 필수 항목이
        # 아니다 — 없는 backend는 실패를 ABORTED로 표현하면 된다.
        validate = getattr(self._backend, "validate", None)
        if callable(validate):
            try:
                validate(command.action, dict(command.parameters))
            except RobotCommandRejected as rejected:
                return AdmissionVerdict(
                    False, f"{REJECT_BACKEND_VALIDATION}:{rejected.code.value}",
                    Rejection(rejected.code, rejected.message),
                )
        return AdmissionVerdict(True, ACCEPTED)

    def _run_action(self, command: Command) -> tuple[bool, dict | None, str | None]:
        """감독자가 EXECUTING 중에 부르는 핸들러. 여기서만 물리 동작이 일어난다."""
        try:
            return self._backend.execute(
                command.action, dict(command.parameters), command_id=command.command_id
            )
        except RobotCommandRejected as rejected:
            # 수락 후에 나온 거부는 거부가 아니다 — 이미 실행 상태에 들어왔으므로
            # ABORTED로 끝낸다(AI-C-20: 거부는 실행 상태에 포함하지 않는다).
            return False, None, f"{rejected.code.value}: {rejected.message}"
        except Exception as error:  # backend 예외가 말단 프로세스를 죽이지 않는다
            return False, None, f"backend_error: {error}"

    def _forward_stop(self, command_id: str) -> bool:
        try:
            return bool(self._backend.request_stop(command_id))
        except Exception:
            return False

    # -- 취소 (수락 ≠ 도달) -----------------------------------------------

    def cancel(self, request: CancelCommandRequest, *, now: float | None = None) -> CancelCommandResponse:
        """취소 **수락** 여부를 돌려준다. 실제 `CANCELED` 도달은 `get_result()`."""
        response = self._supervisor.cancel(request, now=now if now is not None else self._clock())
        self._note(CANCEL_FORWARDED if response.accepted else (
            CANCEL_REFUSED_BY_BACKEND if response.reason == "adapter_cancel_rejected"
            else f"{CANCEL_REFUSED_BY_BACKEND}:{response.reason}"
        ))
        return response

    # -- 긴급정지 (일반 취소와 다른 경로, AI-C-20 §7) ----------------------

    def emergency_stop(self, reason: str) -> EmergencyStopOutcome:
        """장치 자체 정지 경로를 건다. 네트워크도 백엔드 연결도 필요 없다.

        이 어댑터는 `TransportProvider`를 **참조조차 하지 않는다** — 그것이
        "상위 네트워크 명령만을 안전 기능의 유일한 경로로 사용하지 않는다"의
        코드로 확인 가능한 형태다. 호출 순서도 그 주장에 맞춘다: 장부 정리보다
        물리 정지가 먼저다.
        """
        at = self._clock()
        notes: list[str] = []
        try:
            backend_reached = bool(self._backend.emergency_stop(reason))
        except Exception as error:
            backend_reached = False
            notes.append(f"{ESTOP_BACKEND_UNREACHABLE}:{error}")
        if not backend_reached and not notes:
            notes.append(ESTOP_BACKEND_UNREACHABLE)

        with self._lock:
            self._estop = (reason, at)
            canceling: list[str] = []
            for command_id in self._supervisor.live_command_ids():
                response = self._supervisor.cancel(CancelCommandRequest(command_id), now=at)
                if response.accepted:
                    canceling.append(command_id)
        if self._mission_cache is not None:
            self._mission_cache.suspend_for_safety(reason)

        self._note(f"{ESTOP_ENGAGED}:{reason}")
        self._record_event("robot_emergency_stop", "critical", {
            "device_id": self._device_id, "reason": reason,
            "backend_reached": backend_reached,
        })
        return EmergencyStopOutcome(
            reason=reason, at=at, latched=True, backend_reached=backend_reached,
            canceling_command_ids=tuple(canceling), notes=tuple(notes),
        )

    def clear_emergency_stop(self, reason: str) -> None:
        """해제는 명시적 로컬 호출로만 된다. 사유가 남는다."""
        with self._lock:
            self._estop = None
        if self._mission_cache is not None:
            self._mission_cache.clear_safety_suspension(reason)
        self._note(f"{ESTOP_CLEARED}:{reason}")

    @property
    def emergency_stopped(self) -> bool:
        return self._estop is not None

    # -- 임무 캐시 연계 (AI-N-02, AI-C-19) --------------------------------

    def ingest_mission(self, delivery: Any, *, autonomy_on_wire: bool = True) -> Any:
        """이미 승인·전달된 임무를 캐시에 넣는다. 임무를 **만들지 않는다.**

        `autonomy_on_wire=False`는 "이 전달은 항목별 autonomy를 실을 수 없는
        경로로 왔다"는 뜻이다(오늘의 물리 명령 와이어가 그렇다 — 모듈 docstring
        참고). 그때도 값을 지어내지 않는다 — 캐시가 이미 보수적 기본값을 쓰므로
        결손을 세어 두기만 한다.
        """
        if self._mission_cache is None:
            raise RuntimeError("no mission cache configured")
        if not autonomy_on_wire:
            self.wire_gaps[WIRE_GAP_MISSION_AUTONOMY] += len(getattr(delivery, "items", ()))
        return self._mission_cache.apply(delivery)

    def resume_without_link(self, *, now: float | None = None) -> tuple[ResumeOutcome, ...]:
        """링크가 없는 동안 이어서 해도 되는 항목만 집행한다.

        "해도 되는가"는 판정하지 않는다 — `MissionCache.resumable_without_link()`가
        발급자가 붙인 `MissionAutonomy`로 이미 답하며(AI-C-19), 여기서는 그 목록을
        backend로 내려보내고 결과를 캐시에 되돌려 적을 뿐이다. 허가되지 않은
        항목은 **손대지 않고** 사유만 남긴다.
        """
        at = now if now is not None else self._clock()
        if self._mission_cache is None:
            self._note(RESUME_NO_MISSION_CACHE)
            return ()
        if self._estop is not None:
            self._note(RESUME_BLOCKED_EMERGENCY_STOP)
            return ()

        cache = self._mission_cache
        mission = cache.active_mission
        if mission is None:
            return ()

        outcomes: list[ResumeOutcome] = []
        for item_id in cache.blocked_pending_command(now=at):
            outcomes.append(ResumeOutcome(
                item_id, f"{RESUME_BLOCKED_PENDING_COMMAND}:{item_id}", executed=False,
            ))

        declared = self.declared_action_names()
        for item_id in cache.resumable_without_link(now=at):
            item = mission.item(item_id)
            if item is None or item.action not in declared:
                outcomes.append(ResumeOutcome(
                    item_id, f"{RESUME_ACTION_NOT_DECLARED}:{item_id}", executed=False,
                ))
                continue
            # 이 항목을 승인한 물리 명령의 id를 그대로 달고 간다 — "누가
            # 승인했는가"가 실행 기록에서 끊기지 않게(AI-C-19, AI-O-03).
            cache.begin(item_id, command_id=mission.origin_command_id)
            try:
                succeeded, _payload, failure = self._backend.execute(
                    item.action, dict(item.parameters), command_id=mission.origin_command_id
                )
            except Exception as error:
                succeeded, failure = False, f"backend_error: {error}"
            outcome = MissionItemOutcome.SUCCEEDED if succeeded else MissionItemOutcome.FAILED
            cache.complete(item_id, outcome, command_id=mission.origin_command_id)
            outcomes.append(ResumeOutcome(
                item_id,
                f"{RESUME_EXECUTED if succeeded else RESUME_FAILED}:{item_id}",
                executed=True, outcome=outcome, detail=None if succeeded else failure,
            ))
        for outcome in outcomes:
            self._note(outcome.reason)
        return tuple(outcomes)

    # -- 구역 전환 연계 (AI-N-03) ------------------------------------------

    def note_zone_entry(self, entry: Any) -> None:
        """`ZoneHandoverPolicy.confirm_zone()`의 결과를 사실로만 기록한다.

        구역이 바뀌었을 때 캐시된 임무가 여전히 유효한지는 **아직 합의되지 않은
        계약**이라(패치 패키지 N2) 여기서 정하지 않는다. `requires_config_refresh`를
        드러내 두어 구성 적용 쪽(AI-N-02)이 자기 책임으로 처리하게 한다.
        """
        with self._lock:
            self._zone = _ZoneState(
                zone_id=getattr(entry, "zone_id", None),
                requires_config_refresh=bool(getattr(entry, "requires_config_refresh", False)),
                entered_at=self._clock(),
            )
        self._note(f"{ZONE_ENTERED}:{self._zone.zone_id}")

    # -- 조회 --------------------------------------------------------------

    def get_status(self, command_id: str) -> ExecutionStatus | None:
        return self._supervisor.get_status(command_id)

    def get_result(self, command_id: str) -> CommandResult | None:
        return self._supervisor.get_result(command_id)

    def wait(self, command_id: str, timeout: float | None = None) -> CommandResult | None:
        return self._supervisor.wait(command_id, timeout)

    def reasons(self) -> tuple[str, ...]:
        return tuple(self._reasons)

    def status(self) -> dict:
        posture = None
        if self._link_posture is not None:
            try:
                value = self._link_posture()
                posture = getattr(value, "value", value)
            except Exception:
                posture = None
        snapshot = None
        if self._mission_cache is not None:
            snapshot = self._mission_cache.snapshot()
        return {
            "device_id": self._device_id,
            "emergency_stopped": self.emergency_stopped,
            "emergency_stop_reason": self._estop[0] if self._estop else None,
            "declared_actions": sorted(self.declared_action_names()),
            "link_posture": posture,
            "zone_id": self._zone.zone_id,
            "zone_requires_config_refresh": self._zone.requires_config_refresh,
            "mission_id": getattr(snapshot, "mission_id", None),
            "resumable_without_link": list(getattr(snapshot, "resumable_without_link", ())),
            "blocked_pending_command": list(getattr(snapshot, "blocked_pending_command", ())),
            "wire_gaps": dict(self.wire_gaps),
        }

    def close(self) -> None:
        self._supervisor.close()

    # -- 내부 --------------------------------------------------------------

    def _note(self, reason: str) -> None:
        self._reasons.append(reason)

    def _record_event(self, name: str, severity: str, payload: dict) -> None:
        if self._observability is None:
            return
        try:
            self._observability.record_event(name, severity, payload)
        except Exception:
            # 관측 경로 장애가 실제 기능 실행을 중단시키지 않는다(AI-O-01).
            return
