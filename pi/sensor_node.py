"""
피지컬팀 mk2 — 말단 센서 노드 (수위센서)
==========================================
구현 요구사항
  HW-C-04  등록(Birth)·Death + 상태 요약 10초 주기
  HW-C-06  명령 수신·ACK + 결과 4단계 승격 (BE-X-03: ACK→수행중→물리변화→완료/실패)
  HW-C-07  device_id 식별 + 네트워크·구역 변경 시 재등록
  HW-S-02  평시 60초 보고 + 임계 초과·해제·급변 시 즉시 발행 (report-by-exception)
  HW-S-03  이벤트 모드 1 Hz 고주기 보고
  HW-S-04  적응형 주기 전환 명령 수신
  HW-S-05  하트비트 1 Hz
  HW-S-08  전 메시지 타임스탬프
  HW-C-05  노드 자기 관측 metric 5종 OTLP 발신 (otel_metrics.py)
  HW-R-09  두절 시 버퍼링·재전송 (spool.py)

채널(토픽)
  <base>/status       등록·10초 요약·Death  (retained — 늦게 붙은 구독자도 즉시 현재값)
  <base>/heartbeat    1 Hz 생존 신호        (QoS 0 — 다음 신호가 곧 오므로 유실 허용)
  <base>/state        계측 보고             (QoS 1 — 계측값은 유실 불가)
  <base>/cmd          명령 수신
  <base>/cmd/ack      수신 확인(1단계)
  <base>/cmd/result   수행중·물리변화·완료/실패(2~4단계)

가짜 센서: read_water_level() — 평시 2.5m 평균회귀 잔물결, HW_RAIN_FLAG 파일이
  존재하면 강우 모드로 상승. 실센서 입고 시 이 함수 내부만 교체하면 된다(HW-S-01).

실행: python3 sensor_node.py   (사전조건: /etc/device_id, 브로커 가동)
"""
import json
import os
import queue
import random
import signal
import threading
import time
from collections import OrderedDict, deque

import paho.mqtt.client as mqtt

import config
import otel_metrics
import schema
from schema import Identity, envelope
from spool import Spool

# ---------- 가짜 센서 (실센서 입고 시 이 함수만 교체 — HW-S-01) ----------
_level = 2.5


def read_water_level():
    global _level
    if os.path.exists(config.RAIN_FLAG):                      # 강우 스위치 ON
        _level += random.uniform(0.05, 0.15)                  # 빠르게 상승
    else:
        _level += (2.5 - _level) * 0.05 + random.uniform(-0.02, 0.02)
    return round(_level, 3)


class CommandError(Exception):
    """명령을 수행할 수 없는 상태. 4단계 중 failed 로 귀결된다."""


class Node:
    def __init__(self):
        self.identity = Identity.resolve()
        self.base = self.identity.topic_base
        self.spool = Spool(config.SPOOL_PATH, config.SPOOL_MAX, config.SPOOL_REPLAY_BATCH)
        self.metrics = otel_metrics.create(self.identity)

        self.connected = False
        self.started = time.time()
        self.seq = 0
        self.hb_seq = 0

        # 보고 주기 상태 (HW-S-03 / HW-S-04)
        self.mode = "normal"
        self.mode_source = "auto"          # auto | command — 명령 지정이 자동 전환보다 우선
        self.report_interval = config.REPORT_INTERVAL_NORMAL

        # 계측 판정 상태 (HW-S-02)
        self.alert = False
        self.samples = deque()             # 급변 판정용 (t, level) 창
        self.last_rapid = 0.0
        self.last_report = 0.0
        self.sensor_fail = 0

        # 발행 상태
        self.pub_fail = 0
        self._inflight = {}                # mid -> 발행 시각 (지연 metric 산출용)
        self._connects = deque()           # 접속 시각 — client_id 중복(플래핑) 판정용

        # 명령 처리 (HW-C-06)
        self.cmd_q = queue.Queue()
        self.cmd_seen = OrderedDict()      # command_id -> ack (QoS 1 중복 배달 대비)

        self.client = None
        self._connect()
        threading.Thread(target=self._cmd_worker, daemon=True).start()

    # ================= 접속 =================
    def _connect(self):
        """클라이언트를 새로 만들어 붙인다. LWT는 접속 전에만 걸 수 있어서,
        구역 변경으로 토픽이 바뀌면 재접속이 가장 확실한 방법이다."""
        kw = {"callback_api_version": mqtt.CallbackAPIVersion.VERSION2,
              "client_id": self.identity.entity_id}
        if config.MQTT_V5:
            kw["protocol"] = mqtt.MQTTv5          # BE-T-01: 말단↔엣지 MQTT 5.0 확정
        c = mqtt.Client(**kw)

        if config.MQTT_USER:
            c.username_pw_set(config.MQTT_USER, config.MQTT_PASS)
        if config.TLS_CA:                          # BE-T-01의 TLS — 엣지 인증서 준비 시 활성
            c.tls_set(ca_certs=config.TLS_CA,
                      certfile=config.TLS_CERT or None,
                      keyfile=config.TLS_KEY or None)

        # Death(LWT): 급사하면 브로커가 대신 발행한다. payload는 접속 시점에 고정되므로
        # 여기 timestamp는 "죽은 시각"이 아니라 "접속한 시각"이다 — 실제 단절 시각은
        # 서버 판정(BE-T-04 availability)이 브로커 수신 시각으로 매긴다.
        death = envelope(self.identity)
        death.update({"channel": "status", "event": "death", "status": "offline",
                      "device_status": schema.STATUS_FAULT, "reason": "lwt"})
        c.will_set(f"{self.base}/status", json.dumps(death, ensure_ascii=False),
                   qos=1, retain=True)

        c.on_connect = self._on_connect
        c.on_disconnect = self._on_disconnect
        c.on_message = self._on_message
        c.on_publish = self._on_publish

        self.client = c
        # connect_async + loop_start: 브로커가 아직 안 떠 있어도 계속 재시도하고,
        # 끊겨도 스스로 다시 붙는다. 그 사이의 계측값은 spool 이 받아준다(HW-R-09).
        c.connect_async(config.BROKER_HOST, config.BROKER_PORT, keepalive=config.KEEPALIVE)
        c.loop_start()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            print(f"[접속 실패] {reason_code}")
            return
        self.connected = True
        print(f"[접속] {config.BROKER_HOST}:{config.BROKER_PORT} — {self.base}")
        self._flap_check()
        client.subscribe(f"{self.base}/cmd", qos=1)
        self.publish_status("birth")          # HW-C-04 등록
        if self.spool.pending:
            print(f"[버퍼] 미전송 {self.spool.pending}건 재전송 시작 (HW-R-09)")

    def _on_disconnect(self, client, userdata, flags=None, reason_code=None, properties=None):
        self.connected = False
        rc = getattr(reason_code, "value", reason_code)
        if rc == 142:                      # MQTT 5.0 0x8E "Session taken over"
            self._duplicate_id_alarm()
        print(f"[단절] rc={rc} 재접속 대기 — 이후 발행분은 버퍼로 "
              f"(미전송 {self.spool.pending}건)")

    def _flap_check(self):
        """같은 client_id 로 두 노드가 붙으면 서로를 밀어내며 초당 한 번씩 재접속한다.
        브로커 로그에는 'session taken over' 가 남지만 그 사유가 클라이언트까지
        전달되지 않는 경우가 있어(Mosquitto 2.x 실측), 접속 빈도로도 판정한다.
        device_id 중복은 채번 사고이므로 조용히 넘기면 안 된다(HW-C-07)."""
        now = time.time()
        self._connects.append(now)
        while self._connects and now - self._connects[0] > 20:
            self._connects.popleft()
        if len(self._connects) >= 3:
            self._duplicate_id_alarm()
            self._connects.clear()         # 경보 후 창을 비워 매 초 반복 출력을 막는다

    def _duplicate_id_alarm(self):
        print(f"[치명] 20초 내 재접속이 반복된다 — 같은 device_id "
              f"'{self.identity.entity_id}' 로 다른 노드가 접속했을 가능성이 높다. "
              f"채번 대장과 /etc/device_id 확인 필요")

    def _on_publish(self, client, userdata, mid, reason_code=None, properties=None):
        """PUBACK(QoS 1) 시점에 지연을 확정한다. publish() 호출 반환은 '큐에 넣었다'는
        뜻일 뿐이라 그걸 재면 항상 0에 가깝다 — 브로커까지의 왕복이 진짜 발행 지연."""
        t0 = self._inflight.pop(mid, None)
        if t0 is not None:
            self.metrics.record_publish(True, (time.perf_counter() - t0) * 1000)

    # ================= 발행 =================
    def publish(self, topic, payload, qos=1, retain=False, allow_spool=True):
        body = json.dumps(payload, ensure_ascii=False)
        if self.connected:
            info = self.client.publish(topic, body, qos=qos, retain=retain)
            if info.rc == mqtt.MQTT_ERR_SUCCESS:
                self._inflight[info.mid] = time.perf_counter()
                if len(self._inflight) > 1000:      # PUBACK이 끝내 안 온 것들 정리
                    self._inflight.clear()
                return True
        self.pub_fail += 1
        self.metrics.record_publish(False, 0)
        if allow_spool:
            self.spool.append(topic, payload, qos)
        return False

    def device_status(self):
        """BE-T-04 / [G3] 장치 자기보고 층. 서버 판정 가용성과는 별개다."""
        if self.sensor_fail >= 3:
            return schema.STATUS_FAULT
        if self.spool.pending or self.spool.dropped or not self.connected:
            return schema.STATUS_DEGRADED
        return schema.STATUS_OK

    def publish_status(self, event, extra=None):
        """등록·10초 요약·정상 종료가 모두 이 채널로 나간다(retained).
        늦게 붙은 구독자도 구독 즉시 현재 상태 1회를 받는다(BE-T-06/VZ-I-02).
        요약에 등록 정보를 같이 실어야 retained 가 요약으로 덮여도 장치 정보가 남는다."""
        payload = envelope(self.identity)
        payload.update({
            "channel": "status",
            "event": event,                       # birth | summary | rebirth | shutdown
            "status": "offline" if event == "shutdown" else "online",
            "device_status": self.device_status(),
            "registration": self.identity.registration(),
            "mode": self.mode,
            "mode_source": self.mode_source,
            "report_interval_s": self.report_interval,
            "alert": self.alert,
            "uptime_s": round(time.time() - self.started, 1),
            "buffer": {"pending": self.spool.pending, "dropped": self.spool.dropped},
            "publish_failures": self.pub_fail,
        })
        if extra:
            payload.update(extra)
        # 상태는 "지금"의 값이다. 두절 중 쌓아뒀다 나중에 보내면 낡은 상태로 retained 를
        # 덮어써 오히려 해로우므로 버퍼에 넣지 않는다.
        self.publish(f"{self.base}/status", payload, qos=1, retain=True, allow_spool=False)

    # ================= 주기 작업 =================
    def tick_heartbeat(self):
        payload = envelope(self.identity, seq=self.hb_seq)
        payload["channel"] = "heartbeat"
        # 하트비트도 버퍼 대상이 아니다 — "지금 살아있다"는 신호를 나중에 보내면 거짓말이 된다.
        self.publish(f"{self.base}/heartbeat", payload, qos=0, allow_spool=False)
        self.hb_seq += 1

    def tick_identity(self):
        """HW-C-07: 네트워크 또는 구역이 바뀌면 갱신. BE-T-05가 MAC↔구역 매핑으로
        라우팅하므로, 바뀐 걸 알리지 않으면 백엔드가 옛 경로로 찾아온다."""
        fresh = Identity.resolve()
        if fresh.fingerprint() == self.identity.fingerprint():
            return
        old = self.identity
        print(f"[식별자 변경] zone {old.zone_id}->{fresh.zone_id} "
              f"ip {old.ip}->{fresh.ip} mac {old.mac}->{fresh.mac}")
        self.identity = fresh
        if fresh.topic_base != old.topic_base:
            # 구역이 바뀌면 토픽이 통째로 바뀐다. 옛 토픽에 남은 retained 등록을
            # 빈 payload 로 지우지 않으면 그 구역에 유령 장치가 계속 보인다.
            self.client.publish(f"{old.topic_base}/status", "", qos=1, retain=True)
            time.sleep(0.5)
            self.client.disconnect()
            self.client.loop_stop()
            self.base = fresh.topic_base
            self._connect()          # 새 토픽으로 LWT를 다시 걸어야 하므로 재접속
        else:
            self.publish_status("rebirth")

    def tick_sensor(self, now):
        try:
            wl = read_water_level()
            self.sensor_fail = 0
        except Exception as e:
            self.sensor_fail += 1
            print(f"[센서 오류 {self.sensor_fail}회] {type(e).__name__}: {e}")
            return

        self.samples.append((now, wl))
        while self.samples and now - self.samples[0][0] > config.RAPID_WINDOW_S:
            self.samples.popleft()

        crossed_up = (not self.alert) and wl >= config.THRESHOLD
        crossed_down = self.alert and wl < config.THRESHOLD - config.HYST
        rapid = self._detect_rapid(now, wl)
        periodic = now - self.last_report >= self.report_interval

        reason = ("threshold_exceeded" if crossed_up else
                  "threshold_cleared" if crossed_down else
                  "rapid_change" if rapid else
                  "periodic" if periodic else None)
        if reason is None:
            return                       # 수집은 매 주기, 발행은 사건이 있을 때만

        if crossed_up:
            self.alert = True
            self.auto_mode("event")      # HW-S-03: 사건이면 스스로 고주기로
        if crossed_down:
            self.alert = False
            self.auto_mode("normal")
        if rapid:
            self.last_rapid = now

        payload = envelope(self.identity, seq=self.seq)
        payload.update({
            "channel": "state",
            "water_level_m": wl,
            "unit": "m",
            "alert": self.alert,
            "reason": reason,
            "mode": self.mode,
            "device_status": self.device_status(),
        })
        ok = self.publish(f"{self.base}/state", payload, qos=1)
        print(f"state {wl}m ({reason}, {self.mode})" + ("" if ok else " → 버퍼 적재"))
        self.seq += 1
        self.last_report = now

    def _detect_rapid(self, now, wl):
        """HW-S-02 '급변 시 즉시 발행'. 한 샘플씩 비교하면 잔물결도 급변으로 보이므로
        창(기본 10초) 양끝의 차이로 본다. 상승이 계속되는 동안 매초 알리지 않도록
        급변 보고 자체에 최소 간격을 둔다."""
        if now - self.last_rapid < config.RAPID_MIN_GAP_S:
            return False
        if not self.samples:
            return False
        t0, v0 = self.samples[0]
        if now - t0 < config.RAPID_WINDOW_S * 0.5:
            return False                 # 창이 덜 찼으면 판단 보류
        return abs(wl - v0) >= config.RAPID_DELTA_M

    # ================= 보고 주기 전환 (HW-S-03 / HW-S-04) =================
    def auto_mode(self, mode):
        """자동 전환. 엣지가 명령으로 주기를 지정해 둔 상태면 건드리지 않는다."""
        if self.mode_source == "command":
            return
        self.set_mode(mode, "auto")

    def set_mode(self, mode, source, interval=None):
        self.mode = mode
        self.mode_source = source
        self.report_interval = interval if interval is not None else (
            config.REPORT_INTERVAL_EVENT if mode == "event" else config.REPORT_INTERVAL_NORMAL)
        print(f"[모드] {mode} / 보고주기 {self.report_interval}s ({source})")
        self.last_report = 0.0            # 전환 직후 한 번 즉시 보고
        self.publish_status("summary")    # 상태 변화는 주기를 기다리지 않고 즉시(BE-T-04)

    # ================= 명령 (HW-C-06 / BE-X-03 4단계) =================
    def _on_message(self, client, userdata, msg):
        try:
            cmd = json.loads(msg.payload)
        except ValueError:
            self._ack(None, None, "rejected", "malformed_payload")
            return

        cid = cmd.get("command_id")       # BE-X-01: 백엔드가 발급, 말단은 에코만
        if not cid:
            self._ack(None, None, "rejected", "missing_command_id")
            return

        if cid in self.cmd_seen:
            # QoS 1은 재배달을 허용한다. 되돌리기 어려운 명령이 두 번 실행되지 않도록
            # 같은 command_id 는 다시 수행하지 않고 이전 응답만 되돌려준다.
            self.client.publish(f"{self.base}/cmd/ack",
                                json.dumps(self.cmd_seen[cid], ensure_ascii=False), qos=1)
            print(f"[명령 중복] {cid} — 재실행 없이 이전 ACK 재송신")
            return

        action, params = self._parse_action(cmd)
        expires = cmd.get("expires_at")   # VZ-O-01: 만료 후 실행 금지
        if expires and schema.iso_now() > expires:
            self._ack(cid, action, "rejected", "expired")
            return
        if action not in self.ACTIONS:
            self._ack(cid, action, "rejected", "unsupported_action")
            return

        self._ack(cid, action, "accepted")            # 1단계: 수신 확인
        self.cmd_q.put((cid, action, params))

    @staticmethod
    def _parse_action(cmd):
        """정본은 VZ-O-01/BE-A-01의 추상 action+params 형태.
        기존 테스트가 쓰던 평평한 형태({"levee":"open"})도 당분간 받아준다."""
        if "action" in cmd:
            return cmd["action"], cmd.get("params") or {}
        for legacy in ("levee",):
            if legacy in cmd:
                return legacy, {"position": cmd[legacy]}
        return cmd.get("action"), {}

    def _ack(self, cid, action, result, error=None):
        payload = envelope(self.identity, correlation_id=cid)
        payload.update({"channel": "cmd/ack",
                        "stage": "accepted" if result == "accepted" else "rejected",
                        "action": action, "result": result})
        if error:
            payload["error"] = error
        if cid:
            self.cmd_seen[cid] = payload
            while len(self.cmd_seen) > 200:
                self.cmd_seen.popitem(last=False)
        self.publish(f"{self.base}/cmd/ack", payload, qos=1)
        print(f"[명령] {action} {cid} -> {result}" + (f" ({error})" if error else ""))

    def _result(self, cid, action, stage, detail=None, physical=True):
        """2~4단계. BE-X-03이 이 stage 를 그대로 승격해 가시화에 반영한다.
        physical=False 는 '물리 상태 변화 단계가 없는 명령'이라는 뜻 — 설정 변경은
        ACK 다음이 곧 완료라서, 소비자가 물리 단계를 기다리지 않게 알려준다."""
        payload = envelope(self.identity, correlation_id=cid)
        payload.update({"channel": "cmd/result", "action": action,
                        "stage": stage, "physical": physical})
        if detail:
            payload["detail"] = detail
        self.publish(f"{self.base}/cmd/result", payload, qos=1)
        print(f"[명령] {action} {cid} -> {stage}")

    def _cmd_worker(self):
        """명령 수행은 별도 스레드. 수문 구동처럼 몇 초 걸리는 명령이 계측 루프를
        멈춰 세우면 안 되기 때문이다."""
        while True:
            cid, action, params = self.cmd_q.get()
            handler = self.ACTIONS[action]
            physical = action in self.PHYSICAL_ACTIONS
            try:
                for stage, detail in handler(self, params):
                    self._result(cid, action, stage, detail, physical)
            except CommandError as e:
                self._result(cid, action, "failed", {"error": str(e)}, physical)
            except Exception as e:
                self._result(cid, action, "failed",
                             {"error": f"{type(e).__name__}: {e}"}, physical)

    # ---- 명령 구현: (stage, detail) 을 순서대로 내놓는 제너레이터 ----
    def _act_ping(self, params):
        yield "executing", None
        yield "completed", {"uptime_s": round(time.time() - self.started, 1)}

    def _act_set_mode(self, params):
        """HW-S-04 적응형 주기 전환. mode=auto 면 자동 판정으로 되돌린다."""
        mode = params.get("mode")
        if mode not in ("normal", "event", "auto"):
            raise CommandError("invalid_mode")
        yield "executing", {"mode": mode}
        if mode == "auto":
            self.set_mode("event" if self.alert else "normal", "auto")
        else:
            self.set_mode(mode, "command")
        yield "completed", {"mode": self.mode, "report_interval_s": self.report_interval}

    def _act_set_report_interval(self, params):
        try:
            sec = float(params.get("seconds"))
        except (TypeError, ValueError):
            raise CommandError("invalid_seconds")
        if not 0.1 <= sec <= 3600:
            raise CommandError("out_of_range")
        yield "executing", {"seconds": sec}
        self.set_mode("custom", "command", interval=sec)
        yield "completed", {"report_interval_s": sec}

    def _act_levee(self, params):
        """수문 개폐 — 액추에이터 자리표시자(HW-A-02~04 자리).
        되돌리기 어려운 명령이라 ACK가 아니라 물리 상태 변화로 확정을 표시해야 한다
        (BE-X-03). 실제 구동부가 붙으면 sleep 자리에 구동·상태 폴링이 들어간다."""
        pos = params.get("position")
        if pos not in ("open", "close"):
            raise CommandError("invalid_position")
        yield "executing", {"position": pos}
        time.sleep(2)                                  # 구동 시간 (HW-A-04 진행 보고 자리)
        yield "state_changed", {"position": pos}
        yield "completed", {"position": pos}

    ACTIONS = {
        "ping": _act_ping,
        "set_mode": _act_set_mode,
        "set_report_interval": _act_set_report_interval,
        "levee": _act_levee,
    }
    PHYSICAL_ACTIONS = {"levee"}

    # ================= 메인 루프 =================
    def run(self):
        tick = min(config.SAMPLE_INTERVAL, config.HB_INTERVAL, 1.0)
        next_sample = next_hb = next_status = 0.0
        next_ident = time.time() + config.IDENTITY_CHECK_INTERVAL
        print(f"노드 시작 — entity={self.identity.entity_id} node={self.identity.node_id} "
              f"zone={self.identity.zone_id} / 하트비트 {config.HB_INTERVAL}s")
        while True:
            now = time.time()
            if now >= next_sample:
                self.tick_sensor(now)
                next_sample = now + config.SAMPLE_INTERVAL
            if now >= next_hb:
                self.tick_heartbeat()
                next_hb = now + config.HB_INTERVAL
            if now >= next_status:
                self.publish_status("summary")          # HW-C-04 10초 요약
                next_status = now + config.STATUS_SUMMARY_INTERVAL
            if now >= next_ident:
                self.tick_identity()                    # HW-C-07
                next_ident = now + config.IDENTITY_CHECK_INTERVAL
            if self.connected and self.spool.pending:
                sent = self.spool.replay(
                    lambda t, p, q: self.publish(t, p, qos=q, allow_spool=False))
                if sent:
                    print(f"[버퍼] {sent}건 재전송 (남은 {self.spool.pending}건)")
            time.sleep(tick)

    def shutdown(self):
        """정상 종료는 급사와 구분되어야 한다. 둘을 같은 offline 으로 뭉치면
        가시화가 '장애'와 '의도적 미배포'를 나눌 수 없다(VZ-U-01)."""
        print("\n종료 — Death(shutdown) 발행")
        self.publish_status("shutdown", {"reason": "graceful_shutdown"})
        time.sleep(0.3)
        self.client.disconnect()
        self.client.loop_stop()
        self.metrics.shutdown()


def _on_sigterm(signum, frame):
    """systemd 의 stop/restart 는 SIGTERM 을 보낸다. 이걸 받지 않으면 프로세스가
    그대로 죽어 브로커가 LWT(death/fault)를 띄우고, 계획된 재시작·재부팅이 전부
    장애로 보고된다. 가시화가 '장애'와 '의도적 미배포'를 나눠야 하므로(VZ-U-01)
    Ctrl+C 와 같은 정상 종료 경로로 합류시킨다."""
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _on_sigterm)
    node = Node()
    try:
        node.run()
    except KeyboardInterrupt:
        node.shutdown()
