"""명령 처리 — 드론 에이전트가 `sar_start` / `sar_abort` 를 받으면 여기로 넘긴다.

GUI 는 기존 명령 규약(`PhysicalCommandEnvelope.Command`, `map<string, double>`)으로 보낸다.
pi3 의 드론 에이전트가

  1. `Capability.actions` 에 `sar_start`, `sar_abort` 를 선언하고
  2. 그 두 action 을 받으면 `await controller.handle(action, params)` 를 부르고
  3. 돌려받은 `accepted / code / message` 로 `Acceptance` 를 답하면

화면의 버튼이 저절로 열린다(GUI 는 선언된 action 만 보낸다).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Awaitable, Callable

from .capture import CaptureFlag
from .mission import SarMission, SarPlan
from .vehicle import Vehicle

log = logging.getLogger("sar_pass.controller")

ACTIONS = ("sar_start", "sar_abort")


class SarController:
    def __init__(
        self,
        vehicle_factory: Callable[[], Awaitable[Vehicle]],
        cap: CaptureFlag,
        status_sink: Callable[[dict], None] | None = None,
        log_dir: Path | None = None,
        base_provider: Callable[[], dict | None] | None = None,
        ground_ok: Callable[[], bool] | None = None,
    ) -> None:
        self._factory = vehicle_factory
        self.ground_ok = ground_ok
        self.cap = cap
        self.sink = status_sink
        self.log_dir = log_dir
        self.base_provider = base_provider
        self.mission: SarMission | None = None
        self.task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    async def handle(self, action: str, params: dict[str, float]) -> dict:
        if action == "sar_start":
            return await self._start(params)
        if action == "sar_abort":
            return self._abort()
        return {"accepted": False, "code": "UNIMPLEMENTED", "message": f"action {action} not supported"}

    async def _start(self, params: dict[str, float]) -> dict:
        if self.running:
            return {"accepted": False, "code": "ALREADY_RUNNING", "message": "SAR mission already running"}
        try:
            plan = SarPlan.from_params(params)
        except (ValueError, TypeError) as exc:
            return {"accepted": False, "code": "INVALID_ARGUMENT", "message": str(exc)}
        problems = plan.problems()
        if problems:
            return {"accepted": False, "code": "INVALID_ARGUMENT", "message": "; ".join(problems)}
        vehicle = await self._factory()
        pass_log = traj = None
        if self.log_dir is not None:
            stamp = int(vehicle.clock.now())
            pass_log = self.log_dir / f"sar_passes_{stamp}.jsonl"
            traj = self.log_dir / f"flight_{stamp}"
        self.mission = SarMission(vehicle, plan, self.cap, self.sink, pass_log, traj_dir=traj,
                                  base_provider=self.base_provider, ground_ok=self.ground_ok)
        self.task = asyncio.create_task(self.mission.run())
        return {"accepted": True, "code": None, "message": "SAR mission started"}

    def _abort(self) -> dict:
        # 임무가 지우기 전에 **여기서 먼저** 지운다 — 임무 루프가 멎어 있어도 캡처는 꺼진다.
        self.cap.off("sar_abort")
        if self.running and self.mission is not None:
            self.mission.abort()
            return {"accepted": True, "code": None, "message": "abort requested"}
        return {"accepted": True, "code": None, "message": "no mission running (CAP_ON cleared)"}

    async def wait(self) -> str | None:
        if self.task is None:
            return None
        return await self.task
