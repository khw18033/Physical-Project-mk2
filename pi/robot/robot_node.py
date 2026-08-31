"""
피지컬팀 mk2 — 로봇 온보드 노드 (HW-R 계열)
=============================================
공통 코어(BaseNode)를 상속하고 로봇 고유의 수집·보고·임무 처리만 구현한다.

  HW-R-01  제어기 → 온보드 내부 수집 50 Hz (controller_link.py)
  HW-R-02  하트비트 — **대기 중에만.** 임무 중엔 상태 데이터가 하트비트를 겸한다
  HW-R-03  상태 데이터 전달 — 임무 중 20 Hz / 대기 1 Hz. 임무 진행 보고를 포함
  HW-R-05  임무(서브태스크) 수신·검증
  HW-R-06  제어 명령 내부 전달 (controller_link.send_command)
  HW-R-09  두절 시 버퍼링·재전송 (공통 코어 + 정책 분리)

핵심 설계 두 가지

1) **수집과 전송의 주기가 다르다.** 내부는 50Hz로 읽고 외부로는 20Hz로 보낸다.
   전송 시점에 가장 최신 표본을 고르기 위해서다(HW-R-01).

2) **연속값과 이산 사건을 갈라 다룬다.** 20Hz 상태 스트림은 QoS 0으로 보내고
   두절 후엔 다운샘플 재전송한다 — 다음 표본이 50ms 뒤 오므로 유실이 상쇄되고,
   10분 두절분 12,000건을 전량 쏟으면 막 복구된 링크가 막힌다. 반면 모드 전환·
   배터리 경보·임무 상태 전이는 QoS 1 이산 사건으로 전량 재전송한다. 하나가
   빠지면 사건의 인과가 끊기기 때문이다 (SRS 9.4 / SDD 5.3·5.4).

실행: python3 -m robot.robot_node   (pi/ 디렉터리에서)
"""
import time

from common import config, node, schema
from common.commands import BASE_ACTIONS, CommandError
from common.node import BaseNode
from common.schema import envelope
from common.spool import CONTINUOUS, EVENT
from robot import controller_link


class RobotNode(BaseNode):
    ENTITY_TYPE = "robot"

    def __init__(self):
        self.link = controller_link.create(config.CONTROLLER_LINK)
        self.state = None                  # 최신 내부 표본 (50Hz)
        self.internal_seq = 0
        self.last_state_pub = 0.0
        self.mission = None                # {"mission_id", "subtask", "status"}
        self.prev_mode = "idle"
        self.battery_warned = False
        self.internal_fail = 0
        super().__init__()

    # ================= 수집·보고 (HW-R-01 / HW-R-03) =================
    def sample_interval(self):
        """내부 수집 주기. 외부 전송 주기보다 빠르다."""
        return config.ROBOT_INTERNAL_INTERVAL

    def state_interval(self):
        """임무 중 20Hz / 대기 1Hz (HW-R-03).
        ⚠ 20Hz 는 설정값이다 — 근거로 삼은 Nav2 controller_frequency 는 내부 제어
        루프 주기이지 네트워크 전송 주기가 아니어서, 실물 확보 후 무선망 실측으로
        재산정한다(SRS O-11). 코드 수정 없이 바꿀 수 있게 두었다."""
        return (config.ROBOT_STATE_INTERVAL_MISSION if self.in_mission()
                else config.ROBOT_STATE_INTERVAL_IDLE)

    def next_wakeup(self):
        """상태 발행 마감. 수집(50Hz)과 발행(20Hz)이 서로 배수가 아니므로
        루프에 직접 알려 줘야 20Hz 가 그대로 나온다."""
        return self.last_state_pub + self.state_interval()

    def on_tick(self, now):
        """연속 상태 보고 (HW-R-03). 수집(on_sample)과 분리해야 발행 주기가
        수집 틱에 양자화되지 않는다."""
        if self.state is None:
            return
        if now - self.last_state_pub >= self.state_interval():
            self._publish_state(now, "periodic", kind=CONTINUOUS,
                                qos=config.ROBOT_STATE_QOS)
            self.last_state_pub = now

    def in_mission(self):
        return self.mission is not None and self.mission.get("status") == "executing"

    def on_sample(self, now):
        # --- 내부 수집 50Hz (HW-R-01) ---
        try:
            self.state = self.link.read_state()
            self.internal_seq += 1
            self.internal_fail = 0
        except Exception as e:
            self.internal_fail += 1
            print(f"[내부링크 오류 {self.internal_fail}회] {type(e).__name__}: {e}")
            return

        # --- 이산 사건은 주기와 무관하게 즉시 (연속 보고는 on_tick 담당) ---
        self._check_discrete_events(now)

    def _publish_state(self, now, reason, kind, qos):
        s = self.state
        payload = envelope(self.identity, seq=self.seq)
        payload.update({
            "channel": "state",
            "reason": reason,
            "battery_pct": s.battery_pct,
            "position": {"x": s.x, "y": s.y, "heading_deg": s.heading_deg},
            "speed_mps": s.speed_mps,
            "robot_mode": s.mode,
            "internal_seq": self.internal_seq,
            "device_status": self.device_status(),
        })
        if self.mission:
            # HW-R-05: 수행 시작/완료/실패 보고는 상태 데이터에 포함해 회신한다
            payload["mission"] = dict(self.mission)
        self.publish(f"{self.base}/state", payload, qos=qos, kind=kind)

    def _check_discrete_events(self, now):
        """연속 표본과 달리 놓치면 인과가 끊기는 사건들. QoS 1 + 전량 재전송."""
        s = self.state
        if s.mode != self.prev_mode:
            self.prev_mode = s.mode
            self._publish_state(now, "mode_changed", kind=EVENT, qos=1)
            print(f"[로봇] 동작 모드 → {s.mode}")

        low = s.battery_pct <= config.ROBOT_BATTERY_WARN
        if low and not self.battery_warned:
            self.battery_warned = True
            self._publish_state(now, "battery_low", kind=EVENT, qos=1)
            print(f"[로봇] 배터리 경보 {s.battery_pct}%")
        elif not low and self.battery_warned:
            self.battery_warned = False   # 충전으로 회복되면 다음 하강에서 다시 알린다

    # ================= 공통 코어 훅 =================
    def heartbeat_enabled(self):
        """HW-R-02: 임무 중에는 상태 데이터(20Hz)가 하트비트를 겸하므로 별도
        하트비트를 보내지 않는다. 중복 트래픽을 줄이는 것이 요구사항의 취지다."""
        return not self.in_mission()

    def device_status_extra(self):
        if self.internal_fail >= 3 or self.link.link_health() == "fault":
            return schema.STATUS_FAULT
        if self.state and self.state.mode == "fault":
            return schema.STATUS_FAULT
        if self.link.link_health() == "degraded" or self.battery_warned:
            return schema.STATUS_DEGRADED
        return None

    def status_extra(self):
        d = {"robot_mode": self.state.mode if self.state else "unknown",
             "in_mission": self.in_mission(),
             "state_interval_s": self.state_interval(),
             "heartbeat_active": self.heartbeat_enabled(),
             "link": self.link.link_health(),
             "internal_seq": self.internal_seq}
        if self.state:
            d["battery_pct"] = self.state.battery_pct
        if self.mission:
            d["mission"] = dict(self.mission)
        return d

    # ================= 명령 어휘 (HW-R-05 / HW-R-06) =================
    def _act_assign_mission(self, params):
        """HW-R-05 임무 수신·검증. 검증을 통과해야 제어기로 내려보낸다(HW-R-06).
        서브태스크 단위로 어느 단계에서 실패했는지 판별할 수 있어야 하므로
        상태를 명시적으로 전이시킨다."""
        mission_id = params.get("mission_id")
        subtask = params.get("subtask")
        if not mission_id or not subtask:
            raise CommandError("invalid_mission")
        if self.in_mission():
            raise CommandError("mission_in_progress")
        if self.state and self.state.battery_pct <= config.ROBOT_BATTERY_WARN:
            raise CommandError("battery_too_low")

        yield "executing", {"mission_id": mission_id, "subtask": subtask}
        self.mission = {"mission_id": mission_id, "subtask": subtask,
                        "status": "executing", "started_at": schema.iso_now()}
        self.link.send_command("start_mission", params)      # HW-R-06 내부 전달
        # 임무 개시는 물리 상태 변화다 — 제어기가 실제로 모드를 바꿨는지 확인한다.
        deadline = time.time() + 3
        while time.time() < deadline:
            if self.state and self.state.mode == "mission":
                break
            time.sleep(0.05)
        else:
            self.mission["status"] = "failed"
            raise CommandError("controller_did_not_start")
        yield "state_changed", {"robot_mode": "mission"}
        yield "completed", {"mission_id": mission_id}

    def _act_abort_mission(self, params):
        if not self.mission:
            raise CommandError("no_mission")
        yield "executing", {"mission_id": self.mission["mission_id"]}
        self.link.send_command("abort_mission", params)
        deadline = time.time() + 3
        while time.time() < deadline:
            if self.state and self.state.mode != "mission":
                break
            time.sleep(0.05)
        self.mission["status"] = "aborted"
        yield "state_changed", {"robot_mode": self.state.mode if self.state else "?"}
        yield "completed", {"mission_id": self.mission["mission_id"]}
        self.mission = None

    def _act_stream(self, params):
        """HW-R-07 관제용 영상 온디맨드 — 세션 개폐 제어만 MQTT로 하고 미디어는
        별도 경로로 흐른다. Pi 5 에 H.264 하드웨어 인코더가 없어(SRS 9.3) 소프트웨어
        인코딩뿐이므로 상시 스트림은 CPU 예산상 성립하지 않는다. 온디맨드가
        설계상 필수 조건이다. 미디어 게이트웨이 확정 전까지 제어 경로만 둔다."""
        action = params.get("action")
        if action not in ("start", "stop"):
            raise CommandError("invalid_stream_action")
        yield "executing", {"action": action}
        raise CommandError("media_gateway_not_configured")

    ACTIONS = dict(BASE_ACTIONS, **{
        "assign_mission": _act_assign_mission,
        "abort_mission": _act_abort_mission,
        "stream": _act_stream,
    })
    PHYSICAL_ACTIONS = frozenset({"assign_mission", "abort_mission"})


if __name__ == "__main__":
    node.main(RobotNode)
