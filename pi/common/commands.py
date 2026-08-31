"""
피지컬팀 mk2 — 명령 엔진 (HW-C-06 / BE-X-03)
==============================================
명령 하나의 수명을 4단계로 승격시켜 발행한다.

    cmd 수신 ─► [검증] ─► accepted   (cmd/ack)      1단계: "받았다"
                          │
                          ├─► executing      (cmd/result)  2단계: 수행 시작
                          ├─► state_changed  (cmd/result)  3단계: 물리 상태 변화
                          └─► completed / failed           4단계: 확정

**ACK는 "받았다"이지 "했다"가 아니다.** 수문·펌프처럼 되돌리기 어려운 명령은
3단계(피드백으로 확인한 실제 상태 변화)가 확정 근거다(HW-A-04, BE-X-03).
물리 단계가 없는 설정 명령은 `physical:false`로 표시해, 소비자가 오지 않을
단계를 무한정 기다리지 않게 한다.

명령 어휘는 노드가 소유한다(`owner.ACTIONS`). 엔진은 검증·중복 억제·단계 승격만
맡는다 — 센서·로봇·액추에이터가 같은 절차를 공유하고 어휘만 달라지기 때문이다.
"""
import json
import queue
import threading
import time
from collections import OrderedDict

from common import schema


class CommandError(Exception):
    """명령을 수행할 수 없는 상태. 4단계 중 failed 로 귀결된다."""


class CommandEngine:
    def __init__(self, owner, publish, base_topic, log=print):
        self.owner = owner              # 액션 핸들러가 받는 노드 인스턴스
        self.publish = publish          # publish(topic, payload, qos=..., kind=...)
        self.base = base_topic
        self.log = log
        self.q = queue.Queue()
        self.seen = OrderedDict()       # command_id -> ack (QoS 1 중복 배달 대비)
        threading.Thread(target=self._worker, daemon=True).start()

    # ---------------- 수신·검증 ----------------
    def on_message(self, client, payload_bytes):
        try:
            cmd = json.loads(payload_bytes)
        except ValueError:
            self._ack(None, None, "rejected", "malformed_payload")
            return

        cid = cmd.get("command_id")     # BE-X-01: 백엔드가 발급, 말단은 에코만
        if not cid:
            self._ack(None, None, "rejected", "missing_command_id")
            return

        if cid in self.seen:
            # QoS 1은 재배달을 허용한다. 되돌리기 어려운 명령이 두 번 실행되지 않도록
            # 같은 command_id 는 다시 수행하지 않고 이전 응답만 되돌려준다.
            client.publish(f"{self.base}/cmd/ack",
                           json.dumps(self.seen[cid], ensure_ascii=False), qos=1)
            self.log(f"[명령 중복] {cid} — 재실행 없이 이전 ACK 재송신")
            return

        action, params = self._parse(cmd)
        expires = cmd.get("expires_at")     # VZ-O-01: 만료 후 실행 금지
        if expires and schema.iso_now() > expires:
            self._ack(cid, action, "rejected", "expired")
            return
        if action not in self.owner.ACTIONS:
            self._ack(cid, action, "rejected", "unsupported_action")
            return

        self._ack(cid, action, "accepted")          # 1단계
        self.q.put((cid, action, params))

    @staticmethod
    def _parse(cmd):
        """정본은 VZ-O-01/BE-A-01의 추상 action+params 형태.
        기존 테스트가 쓰던 평평한 형태({"levee":"open"})도 당분간 받아준다."""
        if "action" in cmd:
            return cmd["action"], cmd.get("params") or {}
        for legacy in ("levee",):
            if legacy in cmd:
                return legacy, {"position": cmd[legacy]}
        return cmd.get("action"), {}

    # ---------------- 발행 ----------------
    def _ack(self, cid, action, result, error=None):
        payload = schema.envelope(self.owner.identity, correlation_id=cid)
        payload.update({"channel": "cmd/ack",
                        "stage": "accepted" if result == "accepted" else "rejected",
                        "action": action, "result": result})
        if error:
            payload["error"] = error
        if cid:
            self.seen[cid] = payload
            while len(self.seen) > 200:
                self.seen.popitem(last=False)
        self.publish(f"{self.base}/cmd/ack", payload, qos=1)
        self.log(f"[명령] {action} {cid} -> {result}" + (f" ({error})" if error else ""))

    def _result(self, cid, action, stage, detail=None, physical=True):
        payload = schema.envelope(self.owner.identity, correlation_id=cid)
        payload.update({"channel": "cmd/result", "action": action,
                        "stage": stage, "physical": physical})
        if detail:
            payload["detail"] = detail
        self.publish(f"{self.base}/cmd/result", payload, qos=1)
        self.log(f"[명령] {action} {cid} -> {stage}")

    # ---------------- 수행 ----------------
    def _worker(self):
        """명령 수행은 별도 스레드. 수문 구동처럼 몇 초 걸리는 명령이 계측 루프를
        멈춰 세우면 안 되기 때문이다."""
        while True:
            cid, action, params = self.q.get()
            handler = self.owner.ACTIONS[action]
            physical = action in self.owner.PHYSICAL_ACTIONS
            try:
                for stage, detail in handler(self.owner, params):
                    self._result(cid, action, stage, detail, physical)
            except CommandError as e:
                self._result(cid, action, "failed", {"error": str(e)}, physical)
            except Exception as e:
                self._result(cid, action, "failed",
                             {"error": f"{type(e).__name__}: {e}"}, physical)


# ---------------- 어느 노드에나 있는 기본 어휘 ----------------
def act_ping(node, params):
    yield "executing", None
    yield "completed", {"uptime_s": round(time.time() - node.started, 1)}


def act_diag(node, params):
    """진단 — 노드가 지금 무엇을 하고 있는지 한 번에 돌려준다. 현장에서
    journalctl 을 못 볼 때 원격으로 상태를 확인하는 경로."""
    yield "executing", None
    yield "completed", node.diagnostics()


BASE_ACTIONS = {"ping": act_ping, "diag": act_diag}
