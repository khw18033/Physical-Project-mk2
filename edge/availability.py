"""
피지컬팀 mk2 — 엣지 가용성 판정기 (BE-T-04 / BACKEND_AGENDA 10-2·[G3] 임의 진행)
==================================================================================
**회신 대기로 멈추지 않기 위해, 하드웨어가 기본값을 정해 참조 구현으로 제공한다.**
백엔드가 다른 방식을 확정하면 이 구성요소를 대체하면 된다 — 말단 코드는 바뀌지 않는다.

## 10-2 를 이렇게 해소한다

v8 표5는 Prometheus `up` 으로 생사를 보지만, 말단은 push 전용이라 scrape 대상이
없다(포트를 열면 v8 §5-3의 push 설계와 모순). **해소: `up` 은 엣지가 파생한다.**
엣지는 어차피 말단의 하트비트·LWT 를 모두 받는 유일한 지점이다. 이 판정기가
MQTT 신호를 Prometheus 텍스트 형식으로 바꿔 `/metrics` 로 노출하면, 기존 Prometheus
는 **엣지 한 곳만 scrape** 하면 되고 말단은 포트를 열지 않는다.

## [G3] 상태 3층의 발행 주체 (기본값)

| 층 | 주체 | 근거 |
|---|---|---|
| device_status (자기보고) | **말단** | 이미 구현 — 자기 결함은 자기가 안다 |
| availability (생사 판정) | **엣지 (이 판정기)** | 단절 시각은 수신측 시계로 매겨야 한다. 말단의 LWT payload 는 접속 시점에 고정되어 죽은 시각을 모른다 |
| deployment (배치 상태) | 백엔드 | 배치는 백엔드만 안다 |

## 판정 규칙 (VZ-U-01: 계획된 재시작은 장애가 아니다)

    birth/rebirth/summary 수신  → online (up=1)
    shutdown 수신               → offline_planned (up=0, 장애 아님)
    death(LWT) 수신             → offline_fault  (up=0, 장애)
    하트비트 hb_interval×miss_limit 무소식 → stale (up=0, 장애 의심)
                                 — LWT 조차 없는 침묵. 브로커도 모르는 단절이다

하트비트 주기는 **관측으로 학습**한다(연속 간격의 중앙값). 노드 종류마다 주기가
다르고(HW-R-02: 로봇은 임무 중 하트비트 없음), 설정을 이중으로 두면 어긋난다.
로봇처럼 하트비트가 꺼지는 노드는 상태 요약(summary)이 생존 신호를 대신한다.

## 사용

    python -m availability                  # MQTT 접속 + :9105/metrics
    (시험: edge/test_edge.py — 브로커 없이 판정 규칙을 검증한다)
"""
import json
import statistics
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MISS_LIMIT = 4              # 말단 config.MISS_LIMIT 과 같은 값 — 하트비트 n 회 무소식이면 죽음
DEFAULT_HB = 5.0            # 학습 전 가정 주기 (말단 HB_INTERVAL 기본값)
UP, DOWN = 1, 0

# availability 상태값. up 으로 뭉개기 전의 원인 구분 — 계획 정지를 장애로 세면
# 재시작할 때마다 거짓 경보가 울린다(VZ-U-01).
ONLINE = "online"
OFFLINE_PLANNED = "offline_planned"
OFFLINE_FAULT = "offline_fault"
STALE = "stale"

_STATE_CODE = {ONLINE: 0, OFFLINE_PLANNED: 1, OFFLINE_FAULT: 2, STALE: 3}


class Entity:
    __slots__ = ("zone", "etype", "eid", "state", "last_seen", "last_hb",
                 "hb_gaps", "hb_interval", "reason")

    def __init__(self, zone, etype, eid, now):
        self.zone, self.etype, self.eid = zone, etype, eid
        self.state = ONLINE
        self.last_seen = now
        self.last_hb = None
        self.hb_gaps = []           # 최근 하트비트 간격 — 주기 학습용
        self.hb_interval = None
        self.reason = "first_message"


class AvailabilityTracker:
    """판정 규칙의 전부. MQTT 도 HTTP 도 모른다 — 그래서 브로커 없이 검증된다."""

    def __init__(self, miss_limit=MISS_LIMIT, default_hb=DEFAULT_HB):
        self.miss_limit = miss_limit
        self.default_hb = default_hb
        self.entities = {}          # (zone, etype, eid) -> Entity
        self._lock = threading.Lock()

    # ---------------- 입력 ----------------
    def on_message(self, topic, payload, now=None):
        """토픽 말미가 heartbeat/status 인 메시지를 먹는다. 그 외는 무시."""
        now = time.time() if now is None else now
        parts = topic.split("/")
        if len(parts) < 4:
            return
        channel = parts[-1]
        if channel not in ("heartbeat", "status"):
            return
        zone, etype, eid = parts[-4], parts[-3], parts[-2]
        try:
            msg = json.loads(payload) if payload else {}
        except ValueError:
            return                          # 깨진 payload 로 상태를 바꾸지 않는다
        key = (zone, etype, eid)
        with self._lock:
            e = self.entities.get(key)
            if e is None:
                e = self.entities[key] = Entity(zone, etype, eid, now)
            if channel == "heartbeat":
                self._on_heartbeat(e, now)
            else:
                self._on_status(e, msg, now)

    def _on_heartbeat(self, e, now):
        if e.last_hb is not None:
            gap = now - e.last_hb
            if 0 < gap < 3600:
                e.hb_gaps.append(gap)
                if len(e.hb_gaps) > 20:
                    e.hb_gaps.pop(0)
                # 중앙값: 재전송 몰림·일시 지연 같은 이상치에 흔들리지 않는다
                e.hb_interval = statistics.median(e.hb_gaps)
        e.last_hb = now
        e.last_seen = now
        if e.state != ONLINE:
            e.state, e.reason = ONLINE, "heartbeat"

    def _on_status(self, e, msg, now):
        e.last_seen = now
        event = msg.get("event")
        if event in ("birth", "rebirth", "summary"):
            e.state, e.reason = ONLINE, event
        elif event == "shutdown":
            # 계획 정지 — 장애가 아니다(VZ-U-01). LWT 보다 이 신호가 먼저 온다.
            e.state, e.reason = OFFLINE_PLANNED, "graceful_shutdown"
        elif event == "death" or msg.get("reason") == "lwt":
            # 브로커가 대신 발행한 급사 신호. 단절 시각은 지금(수신 시각)이다 —
            # payload 의 timestamp 는 접속 시점 값이라 쓰면 안 된다.
            e.state, e.reason = OFFLINE_FAULT, "lwt"

    # ---------------- 판정 ----------------
    def evaluate(self, now=None):
        """주기 호출. 하트비트 침묵을 stale 로 강등한다 — LWT 조차 없는 단절
        (전원 상실, 네트워크 분단)은 이 경로로만 잡힌다."""
        now = time.time() if now is None else now
        with self._lock:
            for e in self.entities.values():
                if e.state not in (ONLINE,):
                    continue
                if e.last_hb is None:
                    continue                # 하트비트를 안 쓰는 노드(임무 중 로봇)는
                                            # summary 가 신호다 — 침묵 판정 제외
                interval = e.hb_interval or self.default_hb
                if now - e.last_hb > interval * self.miss_limit:
                    e.state, e.reason = STALE, "heartbeat_silence"

    # ---------------- 출력 ----------------
    def snapshot(self):
        with self._lock:
            return {k: (e.state, e.reason) for k, e in self.entities.items()}

    def prometheus(self, now=None):
        """Prometheus 텍스트 형식. 기존 Prometheus 가 엣지만 scrape 하면 된다."""
        now = time.time() if now is None else now
        self.evaluate(now)
        lines = [
            "# HELP up 말단 생사 — 엣지가 하트비트·LWT 로 파생 (push 전용 말단은 scrape 불가)",
            "# TYPE up gauge",
        ]
        state_lines = ["# HELP hw_availability_state 0=online 1=offline_planned 2=offline_fault 3=stale",
                       "# TYPE hw_availability_state gauge"]
        age_lines = ["# HELP hw_heartbeat_age_seconds 마지막 하트비트 이후 경과",
                     "# TYPE hw_heartbeat_age_seconds gauge"]
        with self._lock:
            for (zone, etype, eid), e in sorted(self.entities.items()):
                label = f'{{zone="{zone}",entity_type="{etype}",entity_id="{eid}"}}'
                lines.append(f"up{label} {UP if e.state == ONLINE else DOWN}")
                state_lines.append(f"hw_availability_state{label} {_STATE_CODE[e.state]}")
                if e.last_hb is not None:
                    age_lines.append(f"hw_heartbeat_age_seconds{label} {now - e.last_hb:.1f}")
        return "\n".join(lines + state_lines + age_lines) + "\n"


# ---------------------------------------------------------------- 배선 (운용부)
def serve_metrics(tracker, port=9105):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path != "/metrics":
                return self.send_error(404)
            body = tracker.prometheus().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    import argparse
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--metrics-port", type=int, default=9105)
    # 토픽 구조가 바뀌면(AGENDA #2) 여기만 바꾼다 — 말단의 HW_TOPIC_TEMPLATE 와 짝
    ap.add_argument("--sub", default="+/+/+/heartbeat,+/+/+/status")
    args = ap.parse_args()

    import paho.mqtt.client as mqtt
    tracker = AvailabilityTracker()
    serve_metrics(tracker, args.metrics_port)

    def on_connect(c, u, flags, rc, props=None):
        for t in args.sub.split(","):
            c.subscribe(t.strip(), qos=1)
        print(f"[가용성] 구독 {args.sub}")

    def on_message(c, u, msg):
        tracker.on_message(msg.topic, msg.payload)

    c = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                    client_id="edge-availability")
    c.on_connect = on_connect
    c.on_message = on_message
    c.reconnect_delay_set(min_delay=1, max_delay=10)
    c.connect_async(args.broker, args.port, keepalive=30)
    print(f"[가용성] 브로커 {args.broker}:{args.port} → :{args.metrics_port}/metrics")
    c.loop_forever()


if __name__ == "__main__":
    main()
