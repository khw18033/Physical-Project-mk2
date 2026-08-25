"""
피지컬팀 mk2 — 엣지 오프라인 판정 (HW-S-07) 대역 스크립트
==========================================================
엣지노드가 맡을 로직을 임시로 대행: 구역 내 모든 장치의 하트비트를 구독해
"하트비트 4회(20초) 미수신 → OFFLINE" 판정을 내린다.

이중 감지 구조 (검증 완료):
  1) LWT (status 채널): 브로커가 TCP 끊김을 감지하면 즉시 offline 발행
  2) 하트비트 타임아웃 (이 스크립트): LWT가 못 잡는 어중간한 끊김까지 커버

토픽의 + 와일드카드 덕에 장치가 늘어도 코드 수정 불필요.
실행: python3 monitor.py   (엣지노드 구축 후 그쪽으로 이전 예정)
"""
import json, time, threading
import paho.mqtt.client as mqtt

BROKER = "192.168.50.244"   # 임시: 노트북 브로커
INTERVAL = 5                # 장치의 하트비트 주기
MISS_LIMIT = 4              # HW-S-07: 4회 미수신이면 오프라인

last_seen = {}              # 장치별 마지막 하트비트 수신 시각
state = {}                  # 장치별 현재 판정 상태

def on_message(client, userdata, m):
    dev, ch = m.topic.split('/')[2], m.topic.split('/')[3]
    if ch == "heartbeat":
        last_seen[dev] = time.time()          # 도착 시각 갱신 — 판정의 근거
        if state.get(dev) != "online":
            state[dev] = "online"
            print(f"[판정] {dev} ONLINE")
    elif ch == "status":                      # Birth/LWT 채널도 같이 관찰
        print(f"[수신] {dev} status = {json.loads(m.payload)['status']}")

def watchdog():
    """1초마다 전 장치의 침묵 시간을 점검 — '안 오는 것'은 이벤트가 아니라
    기다리는 쪽이 직접 시계를 봐야 한다"""
    while True:
        now = time.time()
        for dev, t in list(last_seen.items()):
            if now - t > INTERVAL * MISS_LIMIT and state.get(dev) == "online":
                state[dev] = "offline"
                print(f"[판정] {dev} OFFLINE — 하트비트 {MISS_LIMIT}회({INTERVAL*MISS_LIMIT}초) 미수신")
        time.sleep(1)

c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="edge-monitor")
c.on_message = on_message
c.connect(BROKER, 1883)
c.subscribe("zoneA/+/+/heartbeat")   # +: 한 칸 와일드카드 — 모든 타입·장치
c.subscribe("zoneA/+/+/status")
threading.Thread(target=watchdog, daemon=True).start()
print("엣지 감시 시작")
c.loop_forever()
