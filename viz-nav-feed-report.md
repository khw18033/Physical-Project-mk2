# pi1 가시화 중계 (viz-nav-feed) — 구현 보고

- 대상: pi1 (`pi1.tailcb6bfb.ts.net` · `100.83.132.16`)
- 작업일: 2026-09-15 KST
- 앞선 문서: [§0 조사 보고](viz-nav-feed-s0-report.md)
- 상태: **서비스 가동 중 (부팅 자동 시작)**. 실제 유니티 경로로 보는 시험(§4.4)은 아직 안 함

## 요약

- 새 서비스 `viz-nav-feed` 가 `zoneA/robot/go1-001/nav_state`(2 Hz)와 `…/nav_event`(사건 즉시)를 pi1 로컬 브로커로 발행한다.
- 가시화 접속 주소: **`ws://pi1.tailcb6bfb.ts.net:9001/mqtt`** (MQTT 5, 인증 없음)
- **기존 파일은 하나도 고치지 않았다.** `go1-sdk` 는 재시작하지 않았고(NRestarts=0, 11:10:38 기동 그대로), 유니티 포트로 보낸 것도 없다. 중계는 어떤 포트도 bind 하지 않는다.
- 경로 사건은 **브리지 journal 로그**에서 얻는다(`physical` 이 `adm` 그룹이라 읽을 수 있었고, 그룹은 더하지 않았다).

### 아직 안 된 것

| 항목 | 상태 |
|---|---|
| §4.3 다른 테일넷 기기에서 WebSocket 접속 | 못 함. 켜진 기기가 Windows `desktop-oaujese` 뿐이고 접근할 수 없었다. pi1 자신에서 Tailscale 이름으로 붙는 것만 확인 |
| §4.4 실제 유니티 경로 시험 | 안 함. 사람 입회 + 가시화와 시간 맞춰 진행 필요 |
| journal 사건을 실제 `go1-sdk` 로그 줄로 확인 | 안 됨. 배포 뒤 경로가 실행되지 않았다. 같은 문구를 시험용 태그로 넣어 확인했다 |

---

## 1. §0 표

[§0 조사 보고](viz-nav-feed-s0-report.md)와 같다. 달라진 점은 **mosquitto 가 설치돼** 1883 · 9001(websockets)을 연다는 것 하나다.

| 항목 | 값 |
|---|---|
| Tailscale 이름 · IP | `pi1.tailcb6bfb.ts.net` · `100.83.132.16` |
| 유니티 UDP 를 받는 프로세스 | `go1-sdk.service` → `/home/physical/go1sdk/go1_sdk_pc` (C++) |
| 15101 mode 98/99 | 99 만, `path_done_notify` 로 **한 번만**. 98 은 코드에 없다 |
| 5009 state_change | 보낸다. 같은 포트로 `go1_detect_forward` 탐지 JSON 도 나간다 |
| mosquitto 1883 · 9001 | **이번에 설치** (원래 없었다) |
| robot-node | 컨테이너 `hw-robot-go1`, 엣지 브로커 `192.168.50.244:1883` 로 발행 (로컬에 없음) |
| zone · entity id | `zoneA` · `go1-001` |
| 유니티 PC · 보내는 곳 | `192.168.50.244` → pi1 wlan0 `192.168.50.243` |
| 방화벽 | ufw 없음. nftables INPUT accept, `tailscale0` accept |

---

## 2. 고른 방법

| 값 | 원천 | 비고 |
|---|---|---|
| `path_received` · `path_cancel` · `path_done` | **journal** — `journalctl -u go1-sdk -f -o json -n 0` | 브리지가 실제로 한 일(`fflush` 한 로그 줄). 시작할 때 읽을 수 있는지 확인해 자동 선택한다. **한 프로세스는 한 원천만 쓴다** |
| (위의 대안) | 15110 · 15101 mode 99 수동 캡처 | journal 을 못 읽을 때만 쓴다 |
| `cancel_ack` | 15101 mode **== 98** 캡처 | 로직만 있다. 현 브리지는 98 을 보내지 않으므로 **지금은 나오지 않는다** |
| `estop` | 15100 텔레옵 4번째 필드 0→1 | 15101 의 estop 필드(= `cmd.mode==1`, 서 있음)는 쓰지 않는다 |
| `yaw_deg` | 15101 브리지 yaw (rad → 도) | 1초 넘게 끊기면 IMU 로 대체 (`yaw_source` 로 구분) |
| `yaw_odometry_deg` | Go1 내부 MQTT `robot/state` yaw | 늘 함께 싣는다. 2초 넘게 끊기면 `null` |
| `battery_pct` | Go1 내부 MQTT `bms/state` byte[3] | 15초 넘게 끊기거나 전부 0 인 프레임이면 `null` |
| `moving` | 5009 에서 `state_change`·`motion_active` 가 둘 다 있는 JSON 의 `motion_active` | 2초 넘게 끊기면 `null` |

Go1 내부 MQTT(`192.168.123.161:1883`)는 고정 client id `viz-nav-feed-pi1` 로 **구독만** 한다. `Go1Link` 인스턴스는 만들지 않고 `go1_link` 의 상수와 `_bms_soc` 규칙만 import 한다.

### 안 된 방법과 이유

| 방법 | 이유 |
|---|---|
| robot-node 의 `…/state` 구독 | robot-node 가 엣지 브로커로 발행해 로컬에 값이 없다 |
| `AF_PACKET` 을 `ETH_P_IP` 로 열기 (처음 구현) | 커널은 **나가는** 패킷(브리지 → 유니티 15101·5009)을 `ETH_P_ALL` 소켓에만 복사한다. 실제 흐름에서 브리지 yaw 와 `moving` 이 안 잡혔다. `ETH_P_ALL` + 커널 BPF(`skb->protocol == IPv4` 확인)로 고쳤고, 고친 뒤 §4.2 를 다시 돌렸다 |

---

## 3. 파일 · 서비스 · 시스템 변경

### 더한 파일

| 파일 | 내용 |
|---|---|
| `~/hw/pi/robot/viz_nav_feed.py` | 중계 본체 |
| `~/hw/pi/deploy/viz-nav-feed.service` | systemd 유닛 (`/etc/systemd/system/` 로 복사) |
| `/etc/mosquitto/conf.d/hw-viz.conf` | 리스너 설정 (아래) |

```conf
listener 1883 0.0.0.0
allow_anonymous true

listener 9001 0.0.0.0
protocol websockets

max_keepalive 300
```

저장소에는 커밋하지 않았다(`git status`: 두 파일 `??`).

### 고친 기존 파일

**없다.** 참고로 `pi/robot/go1_sdk_pc.cpp` 는 작업 전부터 작업 트리에서 수정 상태(` M`)였다. 그래서 HW 브랜치의 줄 번호와 pi1 파일의 줄 번호가 몇 줄 다르다. 로그 문구는 같다.

### 시스템 변경

| 변경 | 시각 (KST) | 비고 |
|---|---|---|
| `apt install mosquitto` (2.0.21) + enable | 11:46:24 시작 | 직전 11:45:52 에 로봇 정지 확인(15101 1000줄 중 속도 ≠ 0 인 줄 0개) |
| `hw-viz.conf` 추가 후 mosquitto 재시작 | 11:46:39 완료 | 기본 `mosquitto.conf` 에 `include_dir /etc/mosquitto/conf.d` 있음 확인. persistence·persistence_location·log_dest 는 새 파일에 안 적음 |
| `viz-nav-feed` 설치·enable | 11:50 무렵 | |
| 시험 설정(`/etc/viz-nav-feed.env`) 삭제, 원래 포트로 재시작 | 11:54:36 | |

robot-node 의 엣지 브로커 설정은 건드리지 않았다. 새 브로커는 중계 전용이다.

### 서비스 상태

```
● viz-nav-feed.service - pi1 가시화 중계 (viz-nav-feed)
     Loaded: loaded (/etc/systemd/system/viz-nav-feed.service; enabled; preset: enabled)
     Active: active (running)
     CGroup: /system.slice/viz-nav-feed.service
             ├─ /home/physical/venv/bin/python3 -u -m robot.viz_nav_feed
             └─ journalctl -u go1-sdk -f -o json --no-pager -n 0
[viz-nav] Go1 MQTT 접속 192.168.123.161 rc=Success
[viz-nav] 시작 topic=zoneA/robot/go1-001 경로 사건 원천=journal ports path=15110 state=15101 teleop=15100 motion=5009
[viz-nav] event {"schema": "viz-nav/1", ..., "event": "feed_started", ..., "source": "startup", "note": "path_events=journal"} rc=0
[viz-nav] 캡처 열림 ports=[15101, 15100, 5009] SO_RCVBUF=8388608
```

| 점검 | 결과 |
|---|---|
| 실행 사용자 | `physical` (root 아님) |
| 권한 | `CapEff = CapAmb = 0x2000` (CAP_NET_RAW 하나), `NoNewPrivileges=true` |
| bind 한 포트 | 없음 (`ss -ulpn` 에 이 프로세스가 없음) |
| 자원 | 메모리 약 26 MB, CPU 약 1% (10초 측정) |
| `Restart` | `always` (2초) |
| 부팅 자동 시작 | `viz-nav-feed` · `mosquitto` 모두 enabled |

### 환경변수 (시험용 · 운영 기본값)

`/etc/viz-nav-feed.env` 에 적는다. 지금은 파일이 없으므로 기본값으로 돈다.

| 변수 | 기본값 |
|---|---|
| `VIZ_PATH_EVENT_SOURCE` | `auto` (`journal` / `capture` 강제 가능) |
| `VIZ_JOURNAL_MATCH` | `-u go1-sdk` |
| `VIZ_PATH_PORT` · `VIZ_STATE_PORT` · `VIZ_TELEOP_PORT` · `VIZ_MOTION_PORT` | `15110` · `15101` · `15100` · `5009` |
| `VIZ_RCVBUF` | 4 MiB 요청 (실제 8388608) |

---

## 4. §4 시험 출력

### §4.1 `nav_state` 0.5초 주기

```
zoneA/robot/go1-001/nav_state {"schema": "viz-nav/1", "node_id": "pi1", "entity_id": "go1-001", "ts_ms": 1789440671171, "battery_pct": 33, "yaw_deg": -139.0, "yaw_source": "go1_odometry", "yaw_odometry_deg": -139.0, "moving": null, "path_active": false, "path_id": null}
zoneA/robot/go1-001/nav_state {"schema": "viz-nav/1", "node_id": "pi1", "entity_id": "go1-001", "ts_ms": 1789440671671, "battery_pct": 33, "yaw_deg": -139.0, "yaw_source": "go1_odometry", "yaw_odometry_deg": -139.0, "moving": null, "path_active": false, "path_id": null}
zoneA/robot/go1-001/nav_state {"schema": "viz-nav/1", "node_id": "pi1", "entity_id": "go1-001", "ts_ms": 1789440672171, "battery_pct": 33, "yaw_deg": -139.0, "yaw_source": "go1_odometry", "yaw_odometry_deg": -139.0, "moving": null, "path_active": false, "path_id": null}
```

`ts_ms` 간격 500 ms. 시험 포트로 띄운 상태라 브리지 yaw 가 없어 `go1_odometry` 로 나왔다. 원래 포트에서는 5장처럼 `bridge_state` 로 나온다.

원래 포트로 되돌린 뒤:

```
zoneA/robot/go1-001/nav_state {"schema": "viz-nav/1", "node_id": "pi1", "entity_id": "go1-001", "ts_ms": 1789440876561, "battery_pct": 29, "yaw_deg": -179.96, "yaw_source": "bridge_state", "yaw_odometry_deg": -139.0, "moving": false, "path_active": false, "path_id": null}
zoneA/robot/go1-001/nav_state {"schema": "viz-nav/1", "node_id": "pi1", "entity_id": "go1-001", "ts_ms": 1789440877061, "battery_pct": 29, "yaw_deg": -179.96, "yaw_source": "bridge_state", "yaw_odometry_deg": -139.0, "moving": false, "path_active": false, "path_id": null}
```

### §4.2 사건 로직 — capture 원천, 비어 있는 포트

설정: `VIZ_PATH_EVENT_SOURCE=capture`, 포트 25110 / 25101 / 25100 / 25009 (아무도 bind 하지 않음 확인). `127.0.0.1` 로 흉내 패킷을 보냈다.

보낸 순서:
1. 15100 `0.000 0.000 0.000 0` (estop 기준값)
2. `go1_path` 1건 (path_id 3, 4점)
3. CHUNK 6조각으로 나눈 `go1_path` 1건 (path_id 4, 30점)
4. `PATH_CANCEL`
5. 15101 mode 98 ×3
6. 15101 mode 99 ×3
7. 15101 estop=1 · mode 1 줄 — **사건이 나오면 안 됨**
8. 15100 estop=1 ×2
9. 5009 `{"state_change": true, "motion_active": true}`

결과 (`ETH_P_ALL` 로 고친 뒤 다시 돌린 것):

```
zoneA/robot/go1-001/nav_event {"schema": "viz-nav/1", "node_id": "pi1", "entity_id": "go1-001", "seq": 2, "ts_ms": 1789440856671, "event": "path_received", "path_id": 3, "point_count": 4, "source": "udp15110", "note": ""}
zoneA/robot/go1-001/nav_event {"schema": "viz-nav/1", "node_id": "pi1", "entity_id": "go1-001", "seq": 3, "ts_ms": 1789440858472, "event": "path_received", "path_id": 4, "point_count": 30, "source": "udp15110", "note": ""}
zoneA/robot/go1-001/nav_event {"schema": "viz-nav/1", "node_id": "pi1", "entity_id": "go1-001", "seq": 4, "ts_ms": 1789440858772, "event": "path_cancel", "path_id": 4, "point_count": null, "source": "udp15110", "note": "path_active_before=true"}
zoneA/robot/go1-001/nav_event {"schema": "viz-nav/1", "node_id": "pi1", "entity_id": "go1-001", "seq": 5, "ts_ms": 1789440859072, "event": "cancel_ack", "path_id": 4, "point_count": null, "source": "udp15101_mode98", "note": ""}
zoneA/robot/go1-001/nav_event {"schema": "viz-nav/1", "node_id": "pi1", "entity_id": "go1-001", "seq": 6, "ts_ms": 1789440859972, "event": "path_done", "path_id": 4, "point_count": null, "source": "udp15101_mode99", "note": ""}
zoneA/robot/go1-001/nav_event {"schema": "viz-nav/1", "node_id": "pi1", "entity_id": "go1-001", "seq": 7, "ts_ms": 1789440861173, "event": "estop", "path_id": 4, "point_count": null, "source": "udp15100_estop", "note": ""}
```

- 각 사건이 **정확히 한 건씩** 나왔다 (mode 98 ×3 → 1건, mode 99 ×3 → 1건, estop=1 ×2 → 1건).
- 15101 estop=1 줄로는 사건이 나오지 않았다.
- 5009 흉내 JSON 뒤 `nav_state` 에 `"moving": true` 가 실렸다.

### §4.2 추가 — journal 원천

설정: `VIZ_JOURNAL_MATCH=-t viz-nav-test`. 브리지 로그와 같은 문구를 `systemd-cat -t viz-nav-test` 로 journal 에 넣고, 중간에 서비스를 재시작했다.

```
zoneA/robot/go1-001/nav_event {"schema": "viz-nav/1", "node_id": "pi1", "entity_id": "go1-001", "seq": 2, "ts_ms": 1789440743089, "event": "path_received", "path_id": 7, "point_count": 4, "source": "journal", "note": ""}
zoneA/robot/go1-001/nav_event {"schema": "viz-nav/1", "node_id": "pi1", "entity_id": "go1-001", "seq": 3, "ts_ms": 1789440744106, "event": "path_done", "path_id": 7, "point_count": null, "source": "journal", "note": ""}
zoneA/robot/go1-001/nav_event {"schema": "viz-nav/1", "node_id": "pi1", "entity_id": "go1-001", "seq": 4, "ts_ms": 1789440744615, "event": "path_received", "path_id": 8, "point_count": 5, "source": "journal", "note": ""}
zoneA/robot/go1-001/nav_event {"schema": "viz-nav/1", "node_id": "pi1", "entity_id": "go1-001", "seq": 5, "ts_ms": 1789440745124, "event": "path_cancel", "path_id": 8, "point_count": null, "source": "journal", "note": "path_active_before=true"}
    --- 서비스 재시작 ---
zoneA/robot/go1-001/nav_event {"schema": "viz-nav/1", "node_id": "pi1", "entity_id": "go1-001", "seq": 1, "ts_ms": 1789440748349, "event": "feed_started", "path_id": null, "point_count": null, "source": "startup", "note": "path_events=journal"}
zoneA/robot/go1-001/nav_event {"schema": "viz-nav/1", "node_id": "pi1", "entity_id": "go1-001", "seq": 2, "ts_ms": 1789440753196, "event": "path_received", "path_id": 9, "point_count": 3, "source": "journal", "note": ""}
```

- `[PATH] reached wp[0/4]`, `[PATH] canceled and stop requested…` 같은 다른 줄로는 사건이 나오지 않았다.
- 재시작한 뒤 id 7·8 이 **다시 나오지 않았다** (`-n 0`).

### §4.3 WebSocket 접속

**다른 테일넷 기기에서는 하지 못했다.** 아래는 **pi1 자신에서** Tailscale 이름으로 붙은 결과다.

```
connected Success
zoneA/robot/go1-001/nav_state b'{"schema": "viz-nav/1", "node_id": "pi1", "entity_id": "go1-001", "ts_ms": 1789440788350, "battery_pct": 31, "yaw_deg": '
zoneA/robot/go1-001/nav_state b'{"schema": "viz-nav/1", "node_id": "pi1", "entity_id": "go1-001", "ts_ms": 1789440788850, "battery_pct": 31, "yaw_deg": '
zoneA/robot/go1-001/nav_state b'{"schema": "viz-nav/1", "node_id": "pi1", "entity_id": "go1-001", "ts_ms": 1789440789350, "battery_pct": 31, "yaw_deg": '
```

nftables 가 `tailscale0` 입력을 전부 허용하므로 밖에서도 될 것으로 보지만 확인하지 않았다. 가시화 쪽에서 붙어 보고 결과를 알려 달라.

### §4.4 실제 유니티 경로 시험

**하지 않았다.**

### §4.5 원래 값으로 복귀

11:54:36 KST 에 `/etc/viz-nav-feed.env` 를 지우고 재시작했다. 캡처 포트는 15101 · 15100 · 5009, 경로 사건 원천은 journal(`-u go1-sdk`)이다.

---

## 5. yaw 두 원천 — 같은 순간

같은 `nav_state` 한 줄 (11:54 이후, 로봇 정지):

```
"yaw_deg": -179.96, "yaw_source": "bridge_state", "yaw_odometry_deg": -139.0
```

- 브리지 yaw = `wrap_pi(-yaw_rel + offset)` — **IMU 와 부호가 반대**다.
- 기준이 다시 잡히는 때: 유니티 Z 키(`[YAW0] reset`)와 경로를 받을 때마다(`offset 자동보정`).
- 이 시점에는 11:47:36 에 Z 키로 기준이 IMU -139.19° 에 맞춰진 상태였다.
- 그래서 두 값의 차이는 **고정된 상수가 아니다.** 가시화는 두 값을 나란히 보여야 한다.

---

## 6. 계약(§3)과 다르게 한 것 전부

| # | 항목 | 계약 | 실제 |
|---|---|---|---|
| 1 | `nav_state` 키 | 10개 | `yaw_odometry_deg` 추가 (요청대로, schema `viz-nav/1` 유지) |
| 2 | `yaw_source` | `yaw_deg` 가 있으면 싣는다 | `yaw_deg` 가 `null` 이면 `yaw_source` 도 `null` |
| 3 | `path_cancel` 의 `path_id` | 직전 경로의 id | 가장 최근 `path_received` 의 id (이미 끝난 경로여도). `note` 에 `path_active_before=true\|false` |
| 4 | `estop` | 15101 estop 또는 15100 | **15100 만**, `source: "udp15100_estop"`. 처음 본 값이 1 이면 0→1 이 아니므로 사건으로 치지 않음 |
| 5 | `path_done` 판정 | 0 이 아닌 mode 첫 주기 | mode **== 99** (98 도 == 98). 연달아 같은 값이면 처음 한 번만 |
| 6 | 경로 사건 원천 | 캡처 (`udp15110`·`udp15101_mode99`) | **journal**, `source: "journal"`. `-o short-unix` 대신 `-o json` 을 쓰고, `ts_ms` 는 `__REALTIME_TIMESTAMP`. journalctl 이 죽어 다시 띄울 때는 `--after-cursor` 로 이어 받음 |
| 7 | `point_count` (journal) | 경로 점 수 | 로그의 `waypoints=` 값. 브리지가 변환한 waypoint 수라 JSON points 수와 다를 수 있음 |
| 8 | 캡처 방식 | `SOCK_RAW` + `ETH_P_ALL`, hatype 으로 헤더 위치 | `SOCK_DGRAM` + `ETH_P_ALL` + 커널 BPF (IPv4·UDP·목적지 포트). lo 의 이중 수신은 나가는 쪽을 버림. 조각난 UDP 는 로그만 남기고 해석 안 함 |
| 9 | `battery_pct` | 0~100 숫자 | 정수 (BMS 바이트 그대로) |
| 10 | 브로커 단절 시 | — | `nav_state` 는 보내지 않음. `nav_event` 는 paho 큐(최대 200)에 두었다가 다시 붙으면 보냄 (`ts_ms` 는 사건 시각) |
| 11 | capture 원천(대안)의 `path_received` | — | 브리지가 버린 경로까지 셈. 알고 둔 한계이며 journal 원천인 지금은 해당 없음 |

토픽 · QoS · retain · 주기는 계약과 같다.

| 토픽 | QoS | retain | 주기 |
|---|---|---|---|
| `zoneA/robot/go1-001/nav_state` | 0 | false | 0.5 s |
| `zoneA/robot/go1-001/nav_event` | 1 | false | 즉시 |

---

## 7. 가시화 접속 주소

```
ws://pi1.tailcb6bfb.ts.net:9001/mqtt
```

---

## 참고

- **배터리 감소:** 11:18 에 71% → 11:54 에 29%. 다른 쪽에서 로봇을 구동 중이었기 때문으로 확인됐다. 중계는 원본 `bms/state` byte[3] 를 그대로 옮긴다(직접 읽은 원본 값과 일치).
- 운영 명령:
  ```bash
  journalctl -u viz-nav-feed -f                                 # 중계 로그
  mosquitto_sub -h localhost -t '+/robot/+/nav_event' -v        # 사건
  mosquitto_sub -h localhost -t '+/robot/+/nav_state' -v -C 4   # 상태
  sudo systemctl restart viz-nav-feed                           # 로봇에 영향 없음
  ```
