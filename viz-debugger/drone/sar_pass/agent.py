"""드론 에이전트에 `sar_start` / `sar_abort` 를 붙인다 — **HW 쪽 파일은 한 줄도 고치지 않는다.**

pi3 의 드론 에이전트(`drone-node.service`, `~/hw/pi/drone/drone_node.py`)는 HW 브랜치의 공통 틀
`pi/common/node.py::BaseNode` 를 상속한다. 여기서는 그 `DroneNode` 를 다시 상속해 명령 두 개만 덧붙인
클래스를 만들고, 서비스의 실행 명령만 이 모듈로 바꾼다.

    # Pi — drone-node.service 의 ExecStart 를 바꾸는 덮어쓰기 파일(README 「드론 에이전트 연동」)
    python -m sar_pass.agent                        # 기본: drone.drone_node:DroneNode 를 감싼다
    python -m sar_pass.agent --node drone.drone_node:DroneNode

공통 틀이 하는 일(그대로 쓴다):
  - `ACTIONS` 사전의 키가 Capability 로 나간다 → 화면의 「패스 시작」 버튼이 열린다.
  - 명령이 오면 미선언 거절 → `validate()` → Acceptance → 데몬 스레드에서 핸들러(제너레이터) 실행.
  - 핸들러가 던진 예외의 `code` / `message` 가 결과(ABORTED)의 사유가 된다.

여기서 지키는 것:
  - `validate()` 는 paho 망 스레드에서 돈다 → **입출력 없이** 파라미터 · 중복 실행만 본다.
    FC 연결(최대 수 초)은 실행 스레드에서 한다. MQTT 가 그동안 멎지 않는다.
  - `SarController` 는 asyncio 다 → 전용 이벤트 루프 하나를 데몬 스레드로 띄워 그 위에서만 돌린다.
  - 중단은 루프를 거치지 않고 **CAP_ON 부터 바로** 지운다(루프가 막혀 있어도 캡처는 꺼진다).
  - 에이전트가 내려갈 때(systemd stop) 임무를 멈추고 CAP_ON 을 지운다.
  - FC 연결은 MAVSDK 가 자기 소켓(mavlink-router 14540)으로 한다. 기존 `drone_link`(14543, 수신 전용)는 그대로.

설정은 환경변수(`/etc/hw-node.env` 등):
  SAR_FC_URL            기본 udpin://0.0.0.0:14540
  SAR_CAP_PATH          기본 /home/physical/CAP_ON
  SAR_CAP_ACK           비우면 끔. 레이더(cansar)가 CAP_ACK 를 쓰면 그 경로
  SAR_LOG_DIR           기본 /var/lib/hw-node/sar  (서비스의 StateDirectory 안 — 쓰기 가능)
  SAR_BASE_LISTEN       1 이면 …/rtcm 에서 베이스 좌표를 받아 패스 기록에 싣는다(기본 1)
  SAR_CONNECT_TIMEOUT   FC 연결 시한 초(기본 20)
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .capture import DEFAULT_CAP_PATH, CaptureFlag
from .controller import ACTIONS as SAR_ACTIONS
from .controller import SarController
from .mission import SarPlan

log = logging.getLogger("sar_pass.agent")

DEFAULT_FC_URL = "udpin://0.0.0.0:14540"
DEFAULT_LOG_DIR = Path("/var/lib/hw-node/sar")
DEFAULT_NODE = "drone.drone_node:DroneNode"

# 공통 틀은 gRPC 코드 어휘를 쓴다. SarController 가 내는 고유 코드를 거기로 옮긴다.
_CODE = {"ALREADY_RUNNING": "FAILED_PRECONDITION"}


class SarRejected(Exception):
    """공통 틀의 `CommandError` 와 같은 모양(`code` · `message`) — 그 모듈을 들이지 않고도 사유가 그대로 간다."""

    def __init__(self, code: str, message: str) -> None:
        self.code = _CODE.get(code, code)
        self.message = message
        super().__init__(f"{self.code}: {message}")


class SarBridge:
    """스레드에서 부르는 면. 안쪽은 전용 asyncio 루프 하나에서만 돈다."""

    def __init__(self, vehicle_factory: Callable[[], Any], cap: CaptureFlag,
                 status_sink: Callable[[dict], None] | None = None, log_dir: Path | None = None,
                 base_provider: Callable[[], dict | None] | None = None, call_timeout_s: float = 30.0,
                 ground_ok: Callable[[], bool] | None = None) -> None:
        self.cap = cap
        self.call_timeout_s = call_timeout_s
        self._make_vehicle = vehicle_factory
        self._vehicle = None
        self._starting = threading.Lock()
        self.last_status: dict | None = None
        self._sink = status_sink
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self.loop.run_forever, name="sar-loop", daemon=True)
        self._thread.start()
        self.controller = SarController(self._vehicle_once, cap, status_sink=self._on_status,
                                        log_dir=log_dir, base_provider=base_provider, ground_ok=ground_ok)

    # ── 안쪽(루프 스레드) ───────────────────────────────────────────────────
    async def _vehicle_once(self):
        """FC 연결은 한 번만 — 패스 사이에 다시 붙지 않는다. 실패하면 다음 시작 때 다시 시도한다."""
        if self._vehicle is None:
            self._vehicle = await self._make_vehicle()
        return self._vehicle

    def _on_status(self, status: dict) -> None:
        self.last_status = status
        if self._sink is not None:
            try:
                self._sink(status)
            except Exception:  # noqa: BLE001 — 상태 발행 실패로 비행을 멈추지 않는다
                log.exception("SAR 상태 발행 실패")

    def _call(self, action: str, params: dict) -> dict:
        fut = asyncio.run_coroutine_threadsafe(self.controller.handle(action, params), self.loop)
        return fut.result(self.call_timeout_s)

    # ── 바깥(스레드) ────────────────────────────────────────────────────────
    @property
    def running(self) -> bool:
        return self.controller.running

    def precheck(self, action: str, params: dict) -> None:
        """Acceptance 전에 — 입출력 없이. 안 되면 SarRejected."""
        if action == "sar_abort":
            return                                     # 중단은 언제나 받는다
        if action != "sar_start":
            raise SarRejected("UNIMPLEMENTED", f"action {action} not supported")
        if self.running or self._starting.locked():
            raise SarRejected("FAILED_PRECONDITION", "SAR mission already running")
        try:
            plan = SarPlan.from_params(params)
        except (ValueError, TypeError) as exc:
            raise SarRejected("INVALID_ARGUMENT", str(exc)) from None
        problems = plan.problems()
        if problems:
            raise SarRejected("INVALID_ARGUMENT", "; ".join(problems))

    def start(self, params: dict) -> dict:
        """FC 에 붙고 임무를 띄운다(수 초). 임무 자체는 루프에서 계속 돈다 — 진행은 …/sar 토픽으로."""
        if not self._starting.acquire(blocking=False):
            raise SarRejected("FAILED_PRECONDITION", "SAR mission already starting")
        try:
            try:
                reply = self._call("sar_start", dict(params))
            except (TimeoutError, asyncio.TimeoutError, ConnectionError, OSError) as exc:
                raise SarRejected("UNAVAILABLE", f"FC 연결 실패: {exc or type(exc).__name__}") from None
            if not reply["accepted"]:
                raise SarRejected(reply["code"] or "FAILED_PRECONDITION", reply["message"])
            return reply
        finally:
            self._starting.release()

    def abort(self, why: str = "sar_abort") -> bool:
        """CAP_ON 을 **먼저 여기서** 지우고, 임무에는 루프를 통해 알린다. 돌던 임무가 있었으면 True."""
        self.cap.off(why)
        was = self.running
        if was and self.controller.mission is not None:
            self.loop.call_soon_threadsafe(self.controller.mission.abort)
        return was

    def shutdown(self, wait_s: float = 5.0) -> None:
        """에이전트 종료 — 임무를 멈추고(임무가 정한 중단 동작: hold/rtl) CAP_ON 을 지운다."""
        if self.abort("agent_shutdown") and self.controller.task is not None:
            fut = asyncio.run_coroutine_threadsafe(asyncio.wait({self.controller.task}, timeout=wait_s), self.loop)
            try:
                fut.result(wait_s + 1)
            except Exception:  # noqa: BLE001
                pass
        self.cap.off("agent_shutdown")
        # FC 연결(mavsdk_server)도 닫는다 — 남으면 14540 을 쥔 채 다음 에이전트와 응답을 나눠 가진다
        # (SITL 에서 오프보드 전환 응답이 남은 서버로 가서 「오프보드로 안 바뀌었다」가 났다).
        vehicle, self._vehicle = self._vehicle, None
        if vehicle is not None and hasattr(vehicle, "close"):
            try:
                asyncio.run_coroutine_threadsafe(vehicle.close(), self.loop).result(5)
            except Exception:  # noqa: BLE001
                log.warning("FC 연결을 닫지 못했다")


# ── 핸들러(공통 틀의 규약: (stage, detail) 제너레이터) ─────────────────────────
def act_sar_start(node, params):
    yield "connecting_fc", None
    node.sar.start(params)
    yield "completed", {"started": 1.0}


def act_sar_abort(node, params):
    was = node.sar.abort()
    yield "completed", {"aborted": 1.0, "was_running": 1.0 if was else 0.0}


SAR_HANDLERS = {"sar_start": act_sar_start, "sar_abort": act_sar_abort}
assert set(SAR_HANDLERS) == set(SAR_ACTIONS)


def _env_path(name: str, default: Path | None) -> Path | None:
    v = os.environ.get(name)
    if v is None:
        return default
    return Path(v) if v.strip() else None


def default_bridge(node) -> SarBridge:
    """실기체용 — 환경변수로 설정. 시험에서는 `make_sar_bridge` 를 덮어 다른 다리를 넣는다."""
    from .mavsdk_vehicle import MavsdkVehicle

    url = os.environ.get("SAR_FC_URL", DEFAULT_FC_URL)
    timeout = float(os.environ.get("SAR_CONNECT_TIMEOUT", "20"))

    async def make_vehicle():
        v = MavsdkVehicle(url)
        await v.connect(timeout_s=timeout)
        return v

    cap = CaptureFlag(_env_path("SAR_CAP_PATH", DEFAULT_CAP_PATH), install_handlers=False,
                      ack_path=_env_path("SAR_CAP_ACK", None))
    log_dir = _env_path("SAR_LOG_DIR", DEFAULT_LOG_DIR)
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
    base_provider = None
    if os.environ.get("SAR_BASE_LISTEN", "1") == "1":
        try:
            from common import config  # 공통 틀의 브로커 설정을 그대로 따른다

            from .status import RtcmBaseListener
            ident = node_identity(node)
            listener = RtcmBaseListener(config.BROKER_HOST, config.BROKER_PORT, device_id=ident["source_id"],
                                        zone=ident["zone_id"], entity_type=ident["entity_type"])
            base_provider = listener.base
        except Exception:  # noqa: BLE001 — 베이스 좌표는 있으면 좋은 것
            log.warning("베이스 좌표 수신을 못 켰다 — 패스 기록에 베이스 좌표 없이 간다")
    return SarBridge(make_vehicle, cap, status_sink=lambda s: publish_sar_status(node, s), log_dir=log_dir,
                     base_provider=base_provider, call_timeout_s=timeout + 10,
                     # 브로커는 지상국 노트북에 있다 — 공통 틀의 MQTT 연결이 곧 지상국 연결이다(keepalive 10 s)
                     ground_ok=lambda: getattr(node, "connected", True) is not False)


def node_identity(node) -> dict:
    ident = getattr(node, "identity", None)
    return {"source_id": getattr(ident, "entity_id", "x500-001"), "node_id": getattr(ident, "node_id", ""),
            "zone_id": getattr(ident, "zone_id", "zoneA"), "entity_type": getattr(ident, "entity_type", "drone")}


def publish_sar_status(node, status: dict) -> None:
    """`MqttStatusPublisher` 와 같은 모양으로 `<base>/sar`(retained)에 — 노드 자신의 MQTT 연결로."""
    ident = node_identity(node)
    body = {**status, "source_id": ident["source_id"], "node_id": ident["node_id"], "zone_id": ident["zone_id"],
            "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")}
    # 상태는 "지금" 값이다 — 두절 중에 쌓았다가 늦게 보내면 낡은 상태가 retained 를 덮는다.
    node.publish(f"{node.base}/sar", body, qos=0, retain=True, allow_spool=False)


def with_sar(node_cls: type) -> type:
    """`node_cls` 를 상속해 SAR 명령을 덧붙인 클래스. 원래 명령 · 검증 · 종료 처리는 그대로 산다."""

    class SarNode(node_cls):  # type: ignore[misc, valid-type]
        ACTIONS = {**getattr(node_cls, "ACTIONS", {}), **SAR_HANDLERS}

        def __init__(self, *args, **kwargs):
            # 공통 틀의 __init__ 이 곧바로 브로커에 붙고 명령을 받기 시작하는데, 다리는 노드(토픽 · 식별자)가
            # 있어야 만든다. 그 사이(1 초 미만)에 온 SAR 명령은 validate 가 UNAVAILABLE 로 거절한다.
            self.sar = None
            super().__init__(*args, **kwargs)
            self.sar = self.make_sar_bridge()
            log.info("SAR 명령 준비 — %s", ", ".join(SAR_HANDLERS))

        def make_sar_bridge(self) -> SarBridge:
            return default_bridge(self)

        def validate(self, action, params):
            if action in SAR_HANDLERS:
                if self.sar is None:
                    raise SarRejected("UNAVAILABLE", "SAR not ready yet")
                self.sar.precheck(action, params)
                return
            parent = getattr(super(), "validate", None)
            if parent is not None:
                parent(action, params)

        def status_extra(self):
            extra = dict(super().status_extra() or {})
            st = self.sar.last_status if self.sar is not None else None
            extra["sar"] = {"running": bool(self.sar and self.sar.running),
                            "state": (st or {}).get("state"), "capturing": bool((st or {}).get("capturing"))}
            return extra

        def on_shutdown(self):
            if self.sar is not None:
                self.sar.shutdown()
            parent = getattr(super(), "on_shutdown", None)
            if parent is not None:
                parent()

        def shutdown(self):
            # 공통 틀의 shutdown() 이 on_shutdown() 을 부르지 않는 판도 있다 — 여기서 확실히 한 번.
            if self.sar is not None:
                self.sar.shutdown()
            super().shutdown()

    SarNode.__name__ = SarNode.__qualname__ = f"Sar{node_cls.__name__}"
    return SarNode


def load_class(spec: str) -> type:
    mod, _, name = spec.partition(":")
    return getattr(importlib.import_module(mod), name or "DroneNode")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m sar_pass.agent",
                                 description="드론 에이전트(DroneNode)에 sar_start / sar_abort 를 붙여 실행")
    ap.add_argument("--node", default=os.environ.get("SAR_AGENT_NODE", DEFAULT_NODE),
                    help=f"감쌀 노드 클래스 module:Class (기본 {DEFAULT_NODE})")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from common.node import main as node_main  # 공통 틀의 진입점(SIGTERM → 정상 종료 경로)

    node_main(with_sar(load_class(a.node)))


if __name__ == "__main__":
    main()
