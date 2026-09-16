# pi1 가시화 중계 — §0 조사 보고

- 대상: pi1 (`pi1.tailcb6bfb.ts.net`)
- 조사 시각: 2026-09-15 11:1x KST
- 상태: **조사만 끝남. 구현 전.** 결정 필요 사항 3건 (맨 아래)

조사 중 한 일은 읽기, 수동 캡처(AF_PACKET, bind 없음), Go1 내부 MQTT 1건 구독뿐이다.
기존 파일·서비스·설정은 바꾸지 않았고, 유니티 포트로 아무것도 보내지 않았다.

---

## 1. §0 표

| 항목 | 값 |
|---|---|
| Tailscale 이름 · IP | `pi1.tailcb6bfb.ts.net` · `100.83.132.16` (랜: wlan0 `192.168.50.243`, eth0 `192.168.123.162` = Go1 내부망) |
| 유니티 UDP 를 받는 프로세스 | `go1-sdk.service` → `/home/physical/go1sdk/go1_sdk_pc` (C++, `--robot_ip 192.168.123.161 --unity_ip 192.168.50.244`). 15100·15110 을 이 프로세스가 bind 한다. 소스 `~/go1sdk/go1_sdk_pc.cpp` 는 저장소 `pi/robot/go1_sdk_pc.cpp` 와 같다. `unity_bridge.py` 는 돌지 않는다 |
| 15101 에 mode 98/99 를 싣는가 | **99 만 싣는다.** `go1_sdk_pc.cpp:1753-1757` 에서 `send_unity_state(yaw_unity,0,0,0,1,99)` 를 **한 번만** 보낸다(여러 주기가 아니다). **98 은 코드에 없다.** `handle_path_cancel_from_unity()`(`:605-637`)는 정지만 하고 아무것도 보내지 않는다. 계약 문서(`bridge-contract.md` §4.1)에는 98 이 있지만 구현되지 않았다. 평소 mode 필드는 1(서기) 또는 2(걷기)라서 0 이 아닌 값이 늘 실린다 |
| 5009 state_change | 보낸다(`:921-936`, 바뀔 때 즉시 + 0.3초 하트비트). 형식: `{"state_change": b, "motion_active": b, "source": "go1_sdk_pc", "mode": n, ...}`. **같은 포트로 `go1_detect_forward` 의 탐지 JSON 도 나간다.** 두 키가 다 있는 것만 골라야 한다 |
| mosquitto 1883 · 9001 | **둘 다 없다. pi1 에는 mosquitto 브로커가 설치돼 있지 않다**(`mosquitto-clients` 만 있고 `/etc/mosquitto` 없음, localhost:1883 은 연결 거부) |
| robot-node · 로컬 `…/state` | 도커 컨테이너 `hw-robot-go1` 안에서 돈다(`python3 -m robot.robot_node`, network host). **로컬이 아니라 엣지 브로커 `192.168.50.244:1883` 로 발행하는데, 그 브로커도 조사 시점에 연결 거부였다.** `battery_pct`·`heading_deg` 실제 줄은 볼 수 없었다 |
| 배터리 · yaw 대안 원천 | Go1 내부 MQTT `192.168.123.161:1883` 구독이 된다: `bms/state` byte[3] = **71 (SOC %)**, `robot/state` yaw int16 = **-2°**. `robot.go1_link` 가 쓰는 방식과 같다 |
| zone · entity id | `zoneA` · `go1-001` (컨테이너 env: `HW_ZONE_ID=zoneA`, `HW_ENTITY_ID=go1-001`, `HW_NODE_ID=pi1`) |
| 유니티 PC IP · 보내는 곳 | 유니티 `192.168.50.244` → pi1 **wlan0 `192.168.50.243`**. 15100 텔레옵 약 26 Hz 를 캡처로 확인했다. 40초 캡처 동안 15110 은 오지 않았지만, 11:16:17 에 path id=1 을 받아 11:17:32 에 끝낸 로그(`done notify sent (mode=99)`)가 있다. 브리지는 15101 을 약 500 Hz 로 wlan0 을 거쳐 `.244` 로 보낸다. `lo` 에는 로컬 `MISSION PING`(15100)만 보였다 |
| 방화벽 | ufw 없음. nftables 에는 tailscale·docker 체인만 있고 INPUT policy 는 accept, `tailscale0` 은 accept |

### 참고 사실

- UDP 포트 사용 중: 15100·15110 (`go1_sdk_pc`), 그 밖에 `go1_sdk_pc`·`python3` 의 임시 포트, 5353, 41641, 323
- TCP 포트 사용 중: 22, 8090, 8443 (`bench.go1_cam_view`), 6444 (k3s), 34000 (tailscaled) 등. 1883·9001 은 비어 있다
- paho-mqtt 는 `/home/physical/venv` 에만 있다(2.1.0). 시스템 python 에는 없다
- AF_PACKET `recvfrom` 주소의 hatype 으로 링크 헤더 길이를 정한다: wlan0/eth0 = 1, lo = 772 → 14바이트, tun = 65534 → 0바이트
- 조사 시점에 **실기 시험 중**이었다(15101 `vx=0.160 mode 2`, path id=1 실행)

### 캡처 원문 (발췌)

```
1059 ('wlan0', 1, 0, '192.168.50.244', '192.168.50.243', 15100) b'0.000 0.000 0.000 0'
5000 ('?', 4, '192.168.50.243', '192.168.50.244', 15101) b'204021 521779.4 0.402675 4.930372 0.498429 0.160 0.000 -0.022 0 2'
 113 ('?', 4, '192.168.50.243', '192.168.50.244', 5009) b'{"timestamp":"1789438646.3753228","camera_id":"go1_front","detections":[...'
   8 ('lo', 772, 0, '127.0.0.1', '127.0.0.1', 15100) b'MISSION PING'
```

```
Sep 15 11:16:17 pi1 go1_sdk_pc[2225]: [PATH] activated id=1 waypoints=4 anchor_yaw=109.76deg
Sep 15 11:17:32 pi1 go1_sdk_pc[2225]: [PATH] finished.
Sep 15 11:17:32 pi1 go1_sdk_pc[2225]: [PATH] done notify sent (mode=99)
```

---

## 2. 결정이 필요한 것

### 2.1 브로커 설치 (승인 필요)

허락받은 예외는 "conf.d 에 새 파일"뿐인데 pi1 에는 브로커 자체가 없다.

- **제안:** `sudo apt install mosquitto` 를 한 뒤 `/etc/mosquitto/conf.d/hw-viz.conf` 에 `pi/deploy/mosquitto-hw.conf` 와 같은 내용(`listener 1883 0.0.0.0`, `listener 9001 0.0.0.0` + `protocol websockets`, `allow_anonymous true`, `max_keepalive 300`)을 새 파일로 둔다.
- 영향: 1883·9001 은 지금 아무도 쓰지 않고, robot-node 는 엣지로 발행하므로 기존 동작에 영향이 없다.
- 새 패키지 설치이므로 **승인 전에는 하지 않는다.**

### 2.2 배터리·yaw 비교값의 원천

로컬 브로커에 robot-node 값이 없으므로 Go1 내부 MQTT 에서 가져온다.

- `Go1Link` 는 그대로 쓰지 않는다. client_id 가 `hw-go1-<초>` 라서 robot-node 와 같은 초에 뜨면 서로 접속을 끊는다.
- 대신 고정 id `viz-nav-feed-pi1` 로 `bms/state`·`robot/state` 를 **구독만** 한다. 해석은 `go1_link` 의 상수와 `_bms_soc` 규칙(전부 0 이면 `null`)을 읽기 전용으로 가져다 쓴다.
- `battery_pct` 는 로봇 값 그대로이고, robot-node 를 거친 값이 아니다.
- yaw 는 계약대로 15101 의 값(`yaw_source: "bridge_state"`)을 먼저 쓰고, 없으면 `robot/state` 값(`"go1_odometry"`)을 쓴다.
- 참고: 브리지 yaw 는 `wrap_pi(-yaw_rel + offset)` 이고 offset 은 경로를 받을 때마다 다시 맞춰진다(`:1480`, `:1522`). IMU 값과 **부호가 반대이고 기준이 경로마다 바뀐다.** 같은 순간의 두 값은 구현 뒤 보고한다.

### 2.3 계약 그대로 하면 틀리는 사건 두 가지

**`estop`**

- 15101 의 estop 필드는 `(cmd.mode==1)`, 즉 "서 있음"이다(`:1657`, `:1685`, `:1746`). 로봇이 멈출 때마다 0→1 이 되고 mode 99 줄에도 1 이 실린다.
- 이걸 쓰면 경로가 끝날 때마다 가짜 `estop` 이 나고 `path_active` 가 잘못 꺼진다.
- **제안:** estop 사건은 **15100 텔레옵 4번째 필드(유니티가 보내는 실제 estop)의 0→1 로만** 센다. `source` 는 `"udp15100_estop"`. 15100 도 수동 캡처이고 포트는 환경변수로 둔다.

**`cancel_ack`**

- 브리지가 mode 98 을 보내지 않으므로 지금은 **절대 나오지 않는다.**
- **제안:** 로직은 넣어 두어 브리지가 98 을 더하면 그때부터 나오게 하고, 값을 지어내지 않는다.
- 가시화의 "취소 처리됐다" 단계는 당분간 `path_cancel` 만으로 판단해야 한다.

---

## 3. 막히는 것 없음 (조사 결과상 계약대로 가능)

- 15110 수동 캡처(wlan0·lo 포함 모든 인터페이스), CHUNK 재조립은 브리지와 같은 규칙(pid/total 이 바뀌면 초기화)으로 한다
- 15101 mode 99 는 처음 보인 줄만 `path_done` 으로 친다
- 5009 는 `state_change` 와 `motion_active` 가 둘 다 있는 JSON 만 `moving` 에 싣는다
- 서비스는 `User=physical`, `AmbientCapabilities=CAP_NET_RAW`, venv python 으로 돌린다
- 캡처 포트는 환경변수로 둔다(§4 시험에서 25110·25101 등으로 바꾼다)
- §4 브로커 시험과 yaw 두 값 비교는 로봇이 멈춰 있을 때 한다

## 4. 가시화가 붙을 주소 (브로커 설치 후)

`ws://pi1.tailcb6bfb.ts.net:9001/mqtt`
