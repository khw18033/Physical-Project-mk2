"""벤더 SDK 뒤에 있는 실제 4족보행 로봇용 `RobotControlBackend` — **미완성·미검증**.

implements: AI-C-04, AI-C-20, AI-C-05
tests: tests/test_robot_adapter.py (미가용 경로만. 실기기 경로는 시험할 수 없다)

## 이 파일의 상태를 먼저 읽어라

**이 backend는 한 번도 실제 로봇에 대고 실행된 적이 없다.** `execute()`는
움직이는 시늉을 하지 않고 `RobotBackendUnavailable`을 던진다. 동작하는 척하는
스텁이 동작하지 않는 스텁보다 훨씬 위험하다 — 시험이 초록불이 되고 나서 현장에서
처음 거짓이 드러나기 때문이다. 그래서 여기서는 *열리지 않은 문*을 열린 것처럼
칠하지 않는다.

실제로 이 로봇에 명령을 넣는 경로는 지금 **HW 파트가 소유하고 있고 이미 실기기로
검증됐다**: 로봇 옆 RPi 에서 도는 `robot-node`(규약 서버)가 UDP 로 `go1-sdk`
브리지에 넘기고, 그 브리지가 500Hz 제어 루프를 돈다
(HW 파트 `HW-interface/mission-command.md` §6, 2026-09-10 실측).
AI 파트가 그것을 다시 구현할 이유가 없다. 이 파일이 존재하는 이유는 둘이다.

1. **경계를 코드로 고정하기 위해서.** 벤더 이름·SDK·UDP 포트·전송 방식이 나타나도
   되는 자리는 `providers/` 안쪽뿐이고, 그 바깥
   (`execution/robot_adapter.py`, 상위 인지·판단 코드)에는 한 글자도 없어야 한다
   (절대 준수 원칙 #1·#2, AI-C-04). 그 주장은 실제로 벤더 경로를 한 번 써 봐야
   검증된다 — 이 파일이 그 한 번이다.
2. **미가용이 정상 경로임을 보이기 위해서.** SDK 가 없는 개발 노트북에서도 이
   모듈은 **import 되고**, 어댑터에 꽂히며, `readiness()`가 이유와 함께 False 를
   돌려준다. 그 결과 어댑터는 명령을 `FAILED_PRECONDITION` 으로 **거부**하고
   (실행 상태에 넣지 않고) 나머지 기능은 그대로 돈다(AI-C-05). 벤더 SDK 가
   core dependency 가 아니라는 것이 import 가드로 확인 가능하다.

## 모듈 이름에 벤더명을 쓰지 않은 이유

`go1`, `unitree` 같은 제품명을 파일명·클래스명에 박으면 같은 계약을 만족하는 다른
4족보행 로봇이 왔을 때 파일을 복제하게 된다(구현 시 금지 사항: "특정 도메인 전용
클래스를 복제하여 별도 프레임워크를 만들지 않는다"). 구체 제품은 **데이터**로
들어온다 — `sdk_module`, `declared_actions`, `endpoint` 가 전부 생성자 인자다.
"""

from __future__ import annotations

import importlib
from typing import Any

from mission_runtime.contracts.physical_command import Capability


class RobotBackendUnavailable(RuntimeError):
    """벤더 경로가 이 노드에 없거나 아직 구현되지 않았다.

    `AIRuntimeProvider`가 없을 때와 같은 성격의 사건이다 — 장애가 아니라
    **이 노드의 구성**이며, 상위는 해당 선택 기능만 비활성화한다(AI-C-05).
    """


class QuadrupedSdkRobotBackend:
    """벤더 SDK 모듈을 런타임에 찾아 쓰는 `RobotControlBackend` 자리표.

    `sdk_module`은 문자열이다 — import 문으로 고정하면 그 순간 패키지 전체가
    벤더 SDK 없이는 import 되지 않는 물건이 된다. 문자열로 두면 SDK 가 없는
    노드에서 이 모듈을 import 해도 아무 일도 일어나지 않는다.
    """

    def __init__(
        self,
        *,
        sdk_module: str,
        declared_actions: tuple[str, ...] = (),
        endpoint: str | None = None,
    ) -> None:
        self._sdk_module_name = sdk_module
        self._endpoint = endpoint
        self._declared = tuple(
            # 이름만 있는 선언이다. 이 backend 는 자기 action 의 schema·자원
            # 조건·지연 특성을 아직 모르며, 모르는 것을 placeholder 로 지어내지
            # 않는다(AI-C-18: "모든 항목이 항상 존재한다고 가정해서는 안 된다").
            Capability(name=name)
            for name in declared_actions
        )
        self._sdk: Any | None = None
        self._import_error: str | None = None
        try:
            self._sdk = importlib.import_module(sdk_module)
        except Exception as error:  # ModuleNotFoundError 를 포함한 모든 실패
            self._import_error = f"{type(error).__name__}: {error}"

    # -- RobotControlBackend ------------------------------------------------

    def declared_actions(self) -> tuple[Capability, ...]:
        """SDK 가 없으면 **아무 action 도 선언하지 않는다.**

        선언은 "지금 제공 가능한 기능"이다(AI-C-10/AI-C-18). SDK 없이 이름만
        읊으면 상위 선택기가 이 장치를 후보로 고르고 나서야 실패한다.
        """
        return self._declared if self.available else ()

    @property
    def available(self) -> bool:
        return self._sdk is not None

    def readiness(self) -> tuple[bool, str | None]:
        if self._sdk is None:
            return False, f"sdk_module_unavailable:{self._sdk_module_name} ({self._import_error})"
        # SDK 가 import 되더라도 이 backend 는 아직 명령 경로를 구현하지 않았다.
        # 여기서 True 를 돌려주면 어댑터가 명령을 수락하고 나서 ABORTED 를 내며,
        # "수락했는데 못 했다"는 "애초에 못 한다"와 사고 후속 조치가 다르다.
        return False, "command_path_not_implemented:owned_by_hw_robot_node"

    def execute(self, action: str, parameters: dict, *, command_id: str):
        raise RobotBackendUnavailable(
            f"physical execution is not implemented in this backend (action={action!r}, "
            f"command_id={command_id!r}); the verified path is the HW part's robot-node "
            f"-> sdk bridge on the robot-side RPi"
        )

    def request_stop(self, command_id: str) -> bool:
        # 멈출 수 있다고 거짓말하지 않는다. False 는 어댑터에서
        # CancelCommandResponse(accepted=False, reason='adapter_cancel_rejected')
        # 가 되고, 그것이 사실이다.
        return False

    def emergency_stop(self, reason: str) -> bool:
        # 긴급정지는 이 통신·SDK 경로와 **독립인 장치 자체 안전장치**여야 한다
        # (규약 §7, AI-C-20). 소프트웨어 backend 가 그 역할을 자처하면 실제
        # 안전장치가 없는 배치에서도 "정지 가능"으로 보인다. False 를 돌려주면
        # 어댑터가 `backend_reached=False` 로 기록하면서도 latch 는 건다.
        return False
