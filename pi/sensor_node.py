"""
피지컬팀 mk2 — 말단 센서 노드 (수위센서, 최종본)
==================================================
Phase 1~2에서 검증 완료된 기능:
  - Birth 등록 (HW-C-04): 접속 시 장치 정보를 담은 online status 발행 (retained)
  - Death (LWT): 급사 시 브로커가 offline을 대신 발행
  - 하트비트 (HW-S-05): 5초 주기 생존 신호
  - 명령 수신·ACK (HW-C-06): .../cmd 구독 → .../cmd/ack 회신 (command_id 상관키)
  - 평시 보고 + 임계값 즉시 발행 (HW-S-02): 매초 수집, 60초 주기 보고,
    임계(3.0m) 돌파/해제(히스테리시스 0.1m) 시 즉시 발행 (report-by-exception)

가짜 센서: read_water_level() — 평시 2.5m 평균회귀 잔물결,
  /tmp/rain 파일이 존재하면 강우 모드로 수위 상승.
  실제 센서 입고 시 이 함수 내부만 교체하면 됨 (HW-S-01).

실행: python3 sensor_node.py   (사전조건: /etc/device_id 존재, 브로커 가동)
"""
import json, time, random, os, uuid
import paho.mqtt.client as mqtt

BROKER = "192.168.50.244"      # 임시: 노트북 브로커. 엣지노드 구축 후 교체
DEVICE_ID = open("/etc/device_id").read().strip()
BASE = f"zoneA/sensor/{DEVICE_ID}"   # 임시 토픽: zoneA는 도메인 체계 협의 후 교체
FW_VERSION = "0.2.0"

HB_INTERVAL = 5        # 하트비트 주기(초) — 계획서 1Hz vs v4 5초, 협의 안건 (잠정 5초)
REPORT_INTERVAL = 60   # 평시 계측 보고 주기 (HW-S-02)
THRESHOLD = 3.0        # 임계 수위(m) — 넘으면 즉시 발행
HYST = 0.1             # 해제 여유: 2.9m 아래로 내려와야 해제 (경계 알림 반복 방지)

# ---------- 가짜 센서 (실제 센서 입고 시 이 함수만 교체) ----------
level = 2.5
def read_water_level():
    global level
    if os.path.exists("/tmp/rain"):                      # 강우 스위치 ON
        level += random.uniform(0.05, 0.15)              # 빠르게 상승
    else:
        level += (2.5 - level) * 0.05 + random.uniform(-0.02, 0.02)  # 평시 회귀 + 잔물결
    return round(level, 3)

def get_mac():
    """MAC은 등록 메시지의 참고 필드 (device_id 채번 결정사항)"""
    return ':'.join(f"{(uuid.getnode() >> i) & 0xff:02x}" for i in range(40, -1, -8))

def now_ts():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")

# ---------- 접속·Birth·LWT·명령 ----------
c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=DEVICE_ID)

# Death(LWT): 급사하면 브로커가 대신 발행
c.will_set(f"{BASE}/status",
           json.dumps({"device_id": DEVICE_ID, "status": "offline"}),
           qos=1, retain=True)

def on_message(client, userdata, m):
    """명령 수신 → ACK 회신. command_id는 명령↔결과 상관키(전 파트 통일 키)"""
    cmd = json.loads(m.payload)
    ack = {"device_id": DEVICE_ID, "command_id": cmd.get("command_id"),
           "result": "applied" if "command_id" in cmd else "rejected",
           "timestamp": now_ts()}
    client.publish(f"{BASE}/cmd/ack", json.dumps(ack), qos=1)   # 명령 응답은 QoS 1
    print("명령 수신 →", ack["result"])

c.on_message = on_message
c.connect(BROKER, 1883, keepalive=10)   # 10초 무소식이면 브로커가 LWT 발동
c.subscribe(f"{BASE}/cmd", qos=1)
c.loop_start()

# Birth: 접속하며 "살아있음 + 장치 정보" 선언 (retained: 늦은 구독자도 수신)
c.publish(f"{BASE}/status",
          json.dumps({"device_id": DEVICE_ID, "status": "online",
                      "device_type": "water_level", "fw_version": FW_VERSION,
                      "mac": get_mac(), "timestamp": now_ts()}),
          qos=1, retain=True)

# ---------- 메인 루프: 매초 수집, 조건부 보고 (HW-S-02) ----------
seq = hb_seq = 0
last_report = 0.0
last_hb = 0.0
alert = False

while True:
    wl = read_water_level()          # 수집(HW-S-01 자리)은 매초 — 수집과 보고의 분리
    now = time.time()

    crossed_up   = (not alert) and wl >= THRESHOLD          # 임계 돌파 순간
    crossed_down = alert and wl < THRESHOLD - HYST          # 임계 해제 순간
    periodic     = now - last_report >= REPORT_INTERVAL     # 평시 주기 도래

    if crossed_up or crossed_down or periodic:
        if crossed_up:   alert = True
        if crossed_down: alert = False
        state = {"schema_version": "1.2", "device_id": DEVICE_ID, "seq": seq,
                 "timestamp": now_ts(), "water_level_m": wl, "alert": alert,
                 "reason": ("threshold_exceeded" if crossed_up else
                            "threshold_cleared" if crossed_down else "periodic"),
                 "health": {"status": "ok"}}
        c.publish(f"{BASE}/state", json.dumps(state), qos=1)   # 계측값 유실 불가 → QoS 1
        print(f"state 발행: {wl}m ({state['reason']})")
        seq += 1
        last_report = now

    if now - last_hb >= HB_INTERVAL:
        c.publish(f"{BASE}/heartbeat",
                  json.dumps({"device_id": DEVICE_ID, "timestamp": now_ts(),
                              "seq": hb_seq}), qos=0)   # 하트비트는 유실 허용 → QoS 0
        hb_seq += 1
        last_hb = now

    time.sleep(1)
