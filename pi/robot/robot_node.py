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
import json
import re
import time

from common import config, node, schema
from common.base_actions import BASE_ACTIONS
from common.physical_command import CommandError
from common.node import BaseNode
from common.schema import envelope
from common.spool import CONTINUOUS, EVENT
from robot import controller_link, go1_mission, media


def _odo_from_note(note):
    """ACK note("ok odo=1.00m cmd=2.00m")에서 실측 이동거리를 뽑는다. 없으면 None.

    규약 result 는 map<string,double> 라 문자열 note 도, null 도 실을 수 없다.
    그래서 "모름"은 **키를 아예 넣지 않는 것**으로 표현한다 — 0.0 으로 채우면
    "제자리에 있었다"는 거짓 사실이 되고, 상위는 그걸 구별할 방법이 없다."""
    m = re.search(r"odo=([0-9.]+)", note or "")
    return float(m.group(1)) if m else None


class RobotNode(BaseNode):
    ENTITY_TYPE = "robot"

    def __init__(self):
        self.link = controller_link.create(config.CONTROLLER_LINK)
        self.media = media.create()          # HW-R-07 영상 송출 (v8 §5-10)
        self.state = None                  # 최신 내부 표본 (50Hz)
        self.internal_seq = 0
        self.last_state_pub = 0.0
        self.mission = None                # {"mission_id", "subtask", "status"}
        self.mission_client = None         # 진행 중인 문 탐색 미션(go1_sdk_pc) 핸들
        self.prev_mode = "idle"
        self.battery_warned = False
        self.internal_fail = 0
        self.sdk_alive_cache = None        # go1_sdk_pc 생존(캐시). None = 아직 모름
        self.sdk_probe_at = 0.0
        super().__init__()
        self._register_metrics()

    # ================= 관측 지표 (HW-C-05) =================
    def _register_metrics(self):
        """이 노드가 재는 것. 오늘(2026-09-10) 사람이 로그를 뒤져서 찾아낸 장애 세 건이
        전부 여기 하나씩 대응한다 — 지표가 있었다면 그래프 한 줄로 끝났을 것들이다.

          미션이 8회전 내내 헛돎     -> robot.telemetry.alive / robot.sdk.alive
          배터리 경보 오발동         -> robot.battery.percent (모르면 미발행)
          키를 눌러도 안 움직임      -> robot.sdk.alive

        게이지 콜백은 **모르면 None** 을 돌려준다. 0 을 내보내면 "쟀더니 0" 과 구별되지
        않는다(common/schema.py 결측 표현 규칙)."""
        m = self.metrics
        m.observe("robot.telemetry.alive",
                  lambda: 1.0 if self.state is not None else 0.0,
                  description="로봇이 상태를 올려보내고 있는가(0/1)")
        m.observe("robot.battery.percent",
                  lambda: self.state.battery_pct if self.state else None,
                  unit="%", description="배터리 잔량. 모르면 발행하지 않는다")
        m.observe("robot.sdk.alive", lambda: self.sdk_alive_cache,
                  description="구동 브리지(go1_sdk_pc)가 살아 있고 로봇 상태를 받는가(0/1)")
        m.observe("robot.mission.active",
                  lambda: 1.0 if self.in_mission() else 0.0,
                  description="임무 수행 중인가(0/1)")
        self.m_ack = m.counter("robot.mission.ack.count",
                               description="임무 단계 ACK 건수(event 속성으로 구분)")
        self.m_mission_dur = m.histogram("robot.mission.duration", unit="s",
                                         description="임무 1건의 소요 시간")

    def _probe_sdk(self, now):
        """구동 브리지 생존을 낮은 주기로 확인해 캐시한다.

        지표 콜백 안에서 직접 물으면 export 스레드가 UDP 타임아웃만큼 멈춘다.
        주기는 5초 — 이 값이 바뀌어도 관측 해상도만 달라지고 동작은 그대로다."""
        if now - self.sdk_probe_at < 5.0:
            return
        self.sdk_probe_at = now
        try:
            up, state_ok = go1_mission.MissionClient().probe(timeout=0.3)
        except Exception:
            up, state_ok = False, False
        self.sdk_alive_cache = 1.0 if (up and state_ok) else 0.0

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
        self._probe_sdk(now)
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

        if s.battery_pct is None:
            return                      # 배터리를 모르는 동안은 경보도 해제도 하지 않는다
        low = s.battery_pct <= config.ROBOT_BATTERY_WARN
        if low and not self.battery_warned:
            self.battery_warned = True
            self._publish_state(now, "battery_low", kind=EVENT, qos=1)
            print(f"[로봇] 배터리 경보 {s.battery_pct}%")
        elif not low and self.battery_warned:
            self.battery_warned = False   # 충전으로 회복되면 다음 하강에서 다시 알린다

    def validate(self, action, params):
        """ACK 전 검증. 이미 열린 스트림에 start 를 또 보내면 두 번째 ffmpeg 가
        같은 포트로 붙어 엣지가 두 스트림을 섞어 받는다 — 받기 전에 막는다."""
        if action == "stream":
            a = params.get("action")
            if a not in ("start", "stop"):
                raise CommandError("INVALID_ARGUMENT", "invalid_stream_action")
            if a == "start" and self.media.is_running():
                raise CommandError("ALREADY_EXISTS", "stream_already_open")

        if action == "move_forward":
            d = float(params.get("distance_m") or 1.0)
            vx = float(params.get("vx") or 0.0)
            if not 0.05 <= d <= 10.0:
                raise CommandError("INVALID_ARGUMENT", "distance_m_out_of_range")
            if vx and not 0.05 <= vx <= 0.30:
                raise CommandError("INVALID_ARGUMENT", "vx_out_of_range")
            if self.in_mission():
                raise CommandError("FAILED_PRECONDITION", "mission_in_progress")
            sdk_up, state_ok = go1_mission.MissionClient().probe()
            if not sdk_up:
                raise CommandError("FAILED_PRECONDITION", "go1_sdk_not_running")
            if not state_ok:
                raise CommandError("FAILED_PRECONDITION", "robot_state_dead")

        if action == "scan_mission":
            # 범위 밖 값은 받기 전에 막는다 — 수락해 놓고 로봇이 이상하게 도는 것보다
            # 거부 사유를 돌려주는 편이 상위가 고칠 수 있다.
            steps = int(params.get("steps") or 8)
            step_deg = float(params.get("step_deg") or 45.0)
            forward_m = float(params.get("forward_m") or 1.0)
            vx = float(params.get("vx") or 0.0)
            if not 1 <= steps <= 36:
                raise CommandError("INVALID_ARGUMENT", "steps_out_of_range")
            if not 5.0 <= step_deg <= 180.0:
                raise CommandError("INVALID_ARGUMENT", "step_deg_out_of_range")
            if not 0.0 <= forward_m <= 10.0:
                raise CommandError("INVALID_ARGUMENT", "forward_m_out_of_range")
            # forward_m=0 은 유효하다 — "스캔만 하고 전진하지 않는다"
            if vx and not 0.05 <= vx <= 0.30:
                raise CommandError("INVALID_ARGUMENT", "vx_out_of_range")
            if self.in_mission():
                raise CommandError("FAILED_PRECONDITION", "mission_in_progress")
            # 실행 주체(go1_sdk_pc)와 로봇 상태를 **수락 전에** 본다. 수락해 놓고
            # 로봇이 아무것도 하지 않거나, 각도 되먹임 없이 도는 것이 최악이다.
            sdk_up, state_ok = go1_mission.MissionClient().probe()
            if not sdk_up:
                raise CommandError("FAILED_PRECONDITION", "go1_sdk_not_running")
            if not state_ok:
                # 로봇이 HighState 를 안 올려보내는 상태. 회전을 IMU 로 닫을 수 없어
                # 8번 모두 타임아웃까지 열린 루프로 돈다 — 시작하지 않는다.
                raise CommandError("FAILED_PRECONDITION", "robot_state_dead")

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

    def on_shutdown(self):
        if self.media.is_running():
            print("[영상] 송출 중지")
            self.media.stop()

    def status_extra(self):
        d = {"robot_mode": self.state.mode if self.state else "unknown",
             "in_mission": self.in_mission(),
             "state_interval_s": self.state_interval(),
             "heartbeat_active": self.heartbeat_enabled(),
             "link": self.link.link_health(),
             "internal_seq": self.internal_seq,
             "media": self.media.status()}
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
            raise CommandError("INVALID_ARGUMENT", "invalid_mission")
        if self.in_mission():
            raise CommandError("FAILED_PRECONDITION", "mission_in_progress")
        if (self.state and self.state.battery_pct is not None
                and self.state.battery_pct <= config.ROBOT_BATTERY_WARN):
            raise CommandError("FAILED_PRECONDITION", "battery_too_low")

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
            raise CommandError("INTERNAL", "controller_did_not_start")
        yield "state_changed", {"robot_mode": "mission"}
        yield "completed", {"mission_id": mission_id}

    def _act_abort_mission(self, params):
        if not self.mission:
            raise CommandError("FAILED_PRECONDITION", "no_mission")
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

    def _act_scan_mission(self, params):
        """문 탐색 미션 (HW-R-05/06).

        오른쪽 `step_deg` 씩 `steps` 번 회전(회전마다 ACK) → 왼쪽 `step_deg` 1회
        (문을 찾은 방향) ACK → `forward_m` 직진 ACK.

        **규약 parameters 는 map<string,double> 라 문자열을 못 싣는다.** 그래서 임무
        종류를 문자열 파라미터로 받지 않고 action 이름 자체를 어휘로 쓰고, 값은 숫자만
        받는다. 이 제약 때문에 기존 `assign_mission`(mission_id/subtask 가 문자열)은
        규약 경로로 호출할 수 없다 — 규약 확장 전까지 로봇 임무는 이 어휘를 쓴다.

        실제 구동은 같은 파이의 `go1_sdk_pc`(C++ 500Hz 제어 루프)가 한다. 여기서는
        UDP 한 줄로 걸고 ACK 를 받아 **단계마다 진행보고로 되돌려준다** — 상위는
        CommandStatus 를 steps+2 번 받고 마지막에 CommandResult 를 받는다."""
        steps = int(params.get("steps") or 8)
        step_deg = float(params.get("step_deg") or 45.0)
        forward_m = float(params.get("forward_m") or 1.0)
        vx = float(params.get("vx") or 0.0)

        if (self.state and self.state.battery_pct is not None
                and self.state.battery_pct <= config.ROBOT_BATTERY_WARN):
            raise CommandError("FAILED_PRECONDITION", "battery_too_low")

        mc = go1_mission.MissionClient()

        mission_id = "scan-%d" % int(time.time())
        # 스캔 steps + 문 방향 1 + (직진 1, forward_m>0 일 때만)
        expected = steps + 1 + (1 if forward_m > 0 else 0)
        budget = go1_mission.MissionClient.budget(steps, step_deg, forward_m, vx)
        started = time.time()

        mc.start(steps, step_deg, forward_m, vx)
        self.mission_client = mc
        self.mission = {"mission_id": mission_id, "subtask": "door_scan",
                        "status": "executing", "started_at": schema.iso_now()}
        yield "executing", {"steps": steps, "step_deg": step_deg,
                            "forward_m": forward_m, "expected_acks": expected}

        acks = turns_ok = 0
        odo_m = None
        aborted = None
        try:
            for ack in mc.acks(expected, budget):
                acks += 1
                event = ack.get("event", "?")
                note = str(ack.get("note", ""))
                if event in ("scan_turn", "door_turn") and note == "ok":
                    turns_ok += 1
                if event == "forward":
                    odo_m = _odo_from_note(note)
                if event == "aborted":
                    # 미션 도중 로봇이 끊겼다. 성공으로 끝내면 안 된다.
                    aborted = note or "aborted"
                self.m_ack.add(1, {"event": event,
                                   "outcome": "ok" if note.startswith("ok") else "other"})
                # 규약 서버는 stage 문자열을 CommandStatus.detail 로 보낸다.
                # **JSON 으로 보낸다** — 관제 웹이 "몇 번째 회전인지"를 문자열 파싱 없이
                # 읽을 수 있어야 하기 때문이다. CommandStatus 에는 detail(문자열) 말고
                # 구조를 실을 자리가 없어서(규약 §3), 문자열 안에 구조를 넣는다.
                yield json.dumps({
                    "ack": ack.get("ack_seq", acks),   # 이번 미션의 ACK 순번
                    "of": expected,                    # 총 ACK 수
                    "event": event,                    # scan_turn | door_turn | forward | aborted
                    "step": ack.get("step"),           # 그 단계 안에서 몇 번째(회전 3/8 의 3)
                    "steps": ack.get("total"),         # 그 단계의 총 횟수(8)
                    "yaw_deg": ack.get("yaw_deg"),     # 그 시점 방위(모르면 null)
                    "note": note,                      # ok | turn_timeout | robot_state_lost …
                }, ensure_ascii=False), None
        except go1_mission.MissionError as e:
            mc.cancel()
            if self.mission:
                self.mission["status"] = "failed"
            # 취소로 끊긴 것은 내부 오류가 아니다 — 사유가 그대로 드러나야 한다.
            if str(e) == "canceled":
                raise CommandError("ABORTED", "aborted_by_command")
            raise CommandError("INTERNAL", str(e))
        finally:
            mc.close()
            self.mission_client = None
            if self.mission and self.mission.get("status") == "executing":
                self.mission["status"] = "completed"
            self.mission = None

        if aborted:
            raise CommandError("ABORTED", aborted)

        yield "state_changed", {"robot_mode": self.state.mode if self.state else "?"}
        self.m_mission_dur.record(time.time() - started, {"mission": "door_scan"})
        result = {"acks": acks, "turns_ok": turns_ok, "steps": steps,
                  "step_deg": step_deg, "forward_m": forward_m,
                  "duration_s": round(time.time() - started, 1)}
        if odo_m is not None:
            result["odo_m"] = odo_m        # 모르면 키를 빼는 것이 0 을 싣는 것보다 정확하다
        yield "completed", result

    def _act_move_forward(self, params):
        """전진만 (HW-R-06). 스캔 없이 지정 거리를 직진하고 ACK 1건을 돌려준다.

        `scan_mission` 의 forward_m 은 "스캔을 마친 뒤의 전진"이라 스캔 없이 이동만
        시킬 수단이 없었다. 관제에서 "조금만 앞으로"가 필요한 경우가 그것이다."""
        distance_m = float(params.get("distance_m") or 1.0)
        vx = float(params.get("vx") or 0.0)

        mc = go1_mission.MissionClient()
        mission_id = "fwd-%d" % int(time.time())
        budget = go1_mission.MissionClient.budget(0, 0, distance_m, vx) 
        started = time.time()

        mc.start_forward(distance_m, vx)
        self.mission_client = mc
        self.mission = {"mission_id": mission_id, "subtask": "move_forward",
                        "status": "executing", "started_at": schema.iso_now()}
        yield "executing", {"distance_m": distance_m}

        odo_m = None
        aborted = None
        try:
            for ack in mc.acks(1, budget):
                event = ack.get("event", "?")
                note = str(ack.get("note", ""))
                if event == "forward":
                    odo_m = _odo_from_note(note)
                if event == "aborted":
                    aborted = note or "aborted"
                self.m_ack.add(1, {"event": event,
                                   "outcome": "ok" if note.startswith("ok") else "other"})
                yield json.dumps({"ack": 1, "of": 1, "event": event,
                                  "yaw_deg": ack.get("yaw_deg"), "note": note},
                                 ensure_ascii=False), None
        except go1_mission.MissionError as e:
            mc.cancel()
            if str(e) == "canceled":
                raise CommandError("ABORTED", "aborted_by_command")
            raise CommandError("INTERNAL", str(e))
        finally:
            mc.close()
            self.mission_client = None
            self.mission = None

        if aborted:
            raise CommandError("ABORTED", aborted)

        result = {"distance_m": distance_m,
                  "duration_s": round(time.time() - started, 1)}
        if odo_m is not None:
            result["odo_m"] = odo_m
        yield "completed", result

    def _act_abort(self, params):
        """**진행 중인 모든 동작을 즉시 멈춘다** (HW-R-06).

        규약의 취소(CancelCommandRequest)는 command_id 를 알아야 하고 그 명령 하나만
        멈춘다. 관제에서 "일단 멈춰"는 그게 아니다 — 무엇이 돌고 있든, 누가 걸었든
        멈춰야 한다. 그래서 별도 action 으로 둔다.

        멈추는 것: 진행 중인 임무 + 외부 텔레옵(촬영 도구·Unity 가 흘리던 속도 명령).
        텔레옵까지 끊는 것이 핵심이다 — 임무만 취소하면 다른 쪽이 보내던 속도로
        로봇이 계속 움직인다.

        `reason` 은 숫자만 실을 수 있어(규약 map<string,double>) 코드값으로 받는다.
        무엇을 뜻하는지는 상위가 정하고, 여기서는 그대로 기록만 한다.

        ※ 안전 E-stop 이 아니다. E-stop 은 통신과 독립인 장치 자체 안전장치다(규약 §7).
          통신이 끊긴 상황에서는 이 명령이 닿지 않는다."""
        reason = params.get("reason")
        had_mission = bool(self.mission)
        mission_id = (self.mission or {}).get("mission_id")

        yield "executing", {"reason": reason}

        # 진행 중인 임무 핸들러에게 먼저 알린다(그 명령은 ABORTED 로 끝난다).
        mc = self.mission_client
        if mc is not None:
            mc.cancel()

        # 그리고 구동 자체를 끊는다. 임무가 없어도 텔레옵이 돌고 있을 수 있다.
        client = go1_mission.MissionClient()
        try:
            client.stop_all()
        except OSError:
            pass
        # UDP 는 받는 쪽이 없어도 send 가 성공한다 — 그래서 "보냈다"로 도달을 판정하면
        # SDK 가 죽어 있어도 sdk_reached=1 이라는 거짓이 올라간다. 응답으로 확인한다.
        reached = client.probe(timeout=0.5)[0]

        if self.mission:
            self.mission["status"] = "aborted"
        self.mission = None

        print(f"[로봇] abort — 임무={mission_id or '없음'} reason={reason} "
              f"sdk_reached={reached}")

        yield "state_changed", {"robot_mode": "idle", "aborted": True}
        result = {"had_mission": 1.0 if had_mission else 0.0,
                  "sdk_reached": 1.0 if reached else 0.0}
        if reason is not None:
            result["reason"] = float(reason)
        yield "completed", result

    def cancel(self, command_id):
        """규약 §5-3 취소 — 실제 정지를 유도한다. CommandResult=CANCELED 보고는
        규약 서버가 핸들러 종료 시 낸다."""
        mc = self.mission_client
        if mc is not None:
            mc.cancel()

    def _act_stream(self, params):
        """HW-R-07 관제용 영상 온디맨드 (아키텍처 v8 §5-10).

        **제어는 MQTT, 미디어는 별도 경로.** 세션을 여닫는 신호만 이 명령으로 오가고
        픽셀은 RTP/UDP 로 엣지에 직접 흐른다. 온디맨드인 이유는 CPU 가 아니라
        **무선 대역폭**이다 — 1080p@15 JPEG 가 약 9.7 Mbps 를 쓴다(실측).

        물리 명령으로 다룬다. 스트림이 실제로 열렸는지(프로세스 생존)를 확인한
        뒤에야 `state_changed` 를 낸다 — 열렸다고 보고해 놓고 아무것도 나가지 않는
        상태가 가장 나쁘기 때문이다."""
        action = params.get("action")
        if action == "start":
            dest_host = (params.get("dest_host") or config.MEDIA_DEST_HOST
                         or config.BROKER_HOST)
            dest_port = int(params.get("dest_port") or config.MEDIA_DEST_PORT)
            session_id = params.get("session_id") or f"s-{int(time.time())}"
            yield "executing", {"dest": f"{dest_host}:{dest_port}",
                                "session_id": session_id}
            try:
                self.media.start(dest_host, dest_port, session_id)
            except RuntimeError as e:
                raise CommandError("INTERNAL", str(e))
            yield "state_changed", self.media.status()
            yield "completed", {"session_id": session_id}
            return

        if action == "stop":
            yield "executing", None
            self.media.stop()
            if self.media.is_running():
                raise CommandError("INTERNAL", "stream_stop_failed")
            yield "state_changed", {"streaming": False}
            yield "completed", None
            return

        raise CommandError("INVALID_ARGUMENT", "invalid_stream_action")

    ACTIONS = dict(BASE_ACTIONS, **{
        "assign_mission": _act_assign_mission,
        "abort_mission": _act_abort_mission,
        "scan_mission": _act_scan_mission,
        "move_forward": _act_move_forward,
        "abort": _act_abort,
        "stream": _act_stream,
    })
    PHYSICAL_ACTIONS = frozenset({"assign_mission", "abort_mission", "stream"})


if __name__ == "__main__":
    node.main(RobotNode)
