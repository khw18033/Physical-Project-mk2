# 문 탐색 미션 명령 규격 — 보내는 쪽이 볼 문서

> 갱신: 2026-09-10 · 담당: HW 파트 · 브랜치: `HW`
> 실물 Go1 + pi7 로 전 구간 실행 검증 완료(아래 §5 실측 로그).

상위(백엔드/관제)가 **물리 명령 통신 규약(MQTT5 + Protobuf)** 으로 명령 한 건을 보내면
로봇이 문 탐색 미션을 수행하고, **단계마다 ACK 를 되돌려준다.**

미션 내용: **오른쪽 45° × 8회(회전마다 ACK) → 왼쪽 45° 1회(문을 찾은 방향) ACK → 5m 직진 ACK**
— 각도·횟수·거리는 파라미터로 바꾼다.

---

## 1. 어디로 보내나

| | |
|---|---|
| 브로커 | **`pi7.local:1883`** (MQTT 5). 브로커는 로봇 옆 파이(pi7)에서 돈다 — 핫스팟으로 IP 가 바뀌어도 mDNS 이름은 그대로이고, 노트북이 꺼져도 명령 경로가 산다. 엣지노드 장비 구축 시 그쪽으로 이전 |
| 토픽(보냄) | `terminal/go1-001/downlink` |
| 토픽(받음) | `terminal/go1-001/uplink` — **응답 3종이 모두 이 하나로 온다**(Acceptance·CommandStatus·CommandResult). 종류는 토픽이 아니라 봉투의 `oneof body` 가 정한다 |
| payload | `PhysicalCommandEnvelope` (protobuf 직렬화 **바이트**, JSON 아님) |
| 스키마 | `schema/physical_command.proto` |

`go1-001` 은 로봇 노드의 device-id 다(`/etc/hw-robot.env` 의 `HW_ENTITY_ID`).

## 2. 무엇을 보내나

```
Command {
  command_id       = "cmd-2026091012345"   // 재전송 식별용 고유값
  target           = "go1-001"
  action           = "scan_mission"
  parameters = {                            // ⚠ map<string,double> — 숫자만 실린다
    "steps":     8,      // 오른쪽 회전 횟수      (1~36,  기본 8)
    "step_deg":  45,     // 1회 회전각(도)        (5~180, 기본 45)
    "forward_m": 5.0,    // 마지막 직진 거리(m)   (0~10,  기본 1.0)
    "vx":        0.15    // 직진 명령 속도(m/s)   (0.05~0.30, 생략 가능)
  }
  deadline_unix_ms = 0                      // 선택. 이 시각 넘으면 시작하지 않는다(§5-2)
}
```

**파라미터를 다 생략해도 된다** — 그러면 8 × 45° → 45° → 1.0m 로 돈다.
**`forward_m: 0` 은 유효한 값**이다 — 스캔만 하고 전진하지 않는다(ACK 는 steps+1 건).

### 전진만 시키려면 — `move_forward`

`scan_mission` 의 `forward_m` 은 "스캔을 마친 뒤의 전진"이다. 스캔 없이 이동만 시키려면
별도 action 을 쓴다.

```
Command {
  action     = "move_forward"
  parameters = { "distance_m": 1.0, "vx": 0.15 }   // distance_m 0.05~10, vx 생략 가능
}
```
ACK 는 1건(`event: "forward"`)이고 결과는 `{distance_m, odo_m, duration_s}` 다.

> **왜 임무 종류가 문자열 파라미터가 아니라 action 이름인가**
> 규약 `Command.parameters` 가 `map<string, double>` 이라 문자열을 실을 수 없다.
> 그래서 기존 `assign_mission`(mission_id·subtask 가 문자열)은 규약 경로로 호출할 수 없고,
> 로봇 임무는 **action 이름 자체를 어휘로** 쓴다. 규약에 문자열 파라미터가 생기면 통합한다.

## 3. 무엇이 돌아오나

`terminal/go1-001/uplink` 로 순서대로 온다. steps=8 이면 **ACK 10건**(스캔 8 + 문 방향 1 + 직진 1).

```
CommandAcceptance  accepted=true
CommandStatus      EXECUTING  "executing"
CommandStatus      EXECUTING  {"ack":1,"of":10,"event":"scan_turn","step":1,"steps":8,"yaw_deg":-36.6,"note":"ok"}
CommandStatus      EXECUTING  {"ack":2,"of":10,"event":"scan_turn","step":2,"steps":8,"yaw_deg":8.3,"note":"ok"}
   ...
CommandStatus      EXECUTING  {"ack":9,"of":10,"event":"door_turn","step":1,"steps":1,"yaw_deg":-74.2,"note":"ok"}
CommandStatus      EXECUTING  {"ack":10,"of":10,"event":"forward","step":1,"steps":1,"yaw_deg":-123.7,"note":"ok odo=1.00m cmd=2.00m"}
CommandResult      SUCCEEDED  {acks:10, turns_ok:9, steps:8, step_deg:45,
                               forward_m:1.0, odo_m:1.0, duration_s:62.3}
```

**`CommandStatus.detail` 은 JSON 문자열이다.** 규약의 `CommandStatus` 에는 구조를 실을 자리가
`detail`(문자열) 하나뿐이라(§3), 문자열 안에 구조를 넣는다. 관제 웹은 `JSON.parse(detail)` 로
바로 읽으면 된다.

| 필드 | 뜻 |
|---|---|
| `ack` / `of` | 이번 임무의 ACK 순번 / 총 ACK 수 |
| `event` | `scan_turn` · `door_turn` · `forward` · `aborted` |
| `step` / `steps` | **그 단계 안에서 몇 번째인가** — 회전 3/8 의 `3`, `8` |
| `yaw_deg` | 그 시점 방위(도). 모르면 `null` |
| `note` | `ok` · `turn_timeout` · `robot_state_lost` · `forward_timeout` … |

- `odo=` 는 로봇 오도메트리 실측 이동거리, `cmd=` 는 명령 적분값(참고용).
- 회전이 시한 안에 목표각에 못 닿으면 `note` 가 `turn_timeout` 이 된다(임무는 계속 진행).
- 임무 도중 로봇이 끊기면 `event: "aborted"` 가 마지막 ACK 로 오고 결과는 `ABORTED` 다.
- 사람이 눈으로도 확인할 수 있게 **ACK 마다 Go1 얼굴 라이트가 깜빡인다** —
  파랑 2회(스캔 회전) / 초록 3회(문 방향) / 보라 4회(직진 완료).

### 거부(수락 전)
| code | message | 뜻 |
|---|---|---|
| `FAILED_PRECONDITION` | `go1_sdk_not_running` | 로봇 구동 브리지(go1-sdk)가 안 떠 있다 |
| `FAILED_PRECONDITION` | `mission_in_progress` | 이미 미션 수행 중 |
| `FAILED_PRECONDITION` | `battery_too_low` | 배터리 경보 임계 이하 |
| `INVALID_ARGUMENT` | `steps_out_of_range` 등 | 파라미터 범위 밖 |
| `UNIMPLEMENTED` | `action not supported` | action 오타 |

`abort` 는 사전조건이 없다 — 언제 보내도 수락된다. 멈출 것이 없어도 성공이다.

## 4. 중간에 멈추려면 — 두 가지

### 4-1. `abort` — **무엇이 돌고 있든 다 멈춘다** (권장)

```
Command {
  action     = "abort"
  parameters = { "reason": 1 }        // 생략 가능. 숫자만(규약 map<string,double>)
}
```

command_id 를 몰라도 되고, 누가 무엇을 걸었든 멈춘다. 관제의 "일단 멈춰"가 이것이다.
멈추는 순서는 셋이고, **텔레옵까지 끊는 것이 핵심**이다 — 임무만 취소하면 촬영 도구나
Unity 가 흘리던 속도 명령으로 로봇이 계속 움직인다.

| | 내용 |
|---|---|
| ① | 진행 중인 임무 중단 |
| ② | 0속도 estop 프레임으로 흘러가던 속도 명령을 덮어쓴다 |
| ③ | 구동 브리지를 외부 명령 모드에서 뺀다 — **다른 쪽이 계속 보내도 무시**된다 |

응답: `SUCCEEDED { had_mission, sdk_reached, reason }`
(`sdk_reached` 는 구동 브리지가 실제로 응답했는지다. 0 이면 브리지가 죽어 있다 —
로봇이 이미 멈춰 있다는 뜻이기도 하고, 켜야 한다는 뜻이기도 하다.)
멈춰진 쪽 명령은 `ABORTED / aborted_by_command` 로 끝난다.

### 4-2. `CancelCommandRequest` — 그 명령 하나만 취소

```
CancelCommandRequest { command_id }
```
규약 표준 경로다. 해당 명령만 멈추고 `CancelCommandResponse(accepted=true)` 에 이어
`CommandResult(status=CANCELED)` 를 보낸다(§5-3 취소 우선).

> **둘 다 안전 E-stop 이 아니다.** E-stop 은 통신과 독립인 장치 자체 안전장치다(규약 §7).
> 통신이 끊긴 상황에서는 두 방법 모두 닿지 않는다.

## 5. 보내는 예 (참조 구현)

`pi/bench/send_physical_command.py` 가 위 규격 그대로 보내고 uplink 를 찍는다.

```bash
# pi/ 디렉터리에서
python3 -m bench.send_physical_command --broker pi7.local --device go1-001 \
        --action scan_mission --param steps=8 --param step_deg=45 --param forward_m=5.0
python3 -m bench.send_physical_command --broker pi7.local --device go1-001 --cancel cmd-ef5e5d8c
```

실측(2026-09-10, steps=1·forward 0.3m):
```
[Acceptance] accepted → [Status] ack 1/3 scan_turn 1/1 yaw=-82.6 ok
                       → [Status] ack 2/3 door_turn 1/1 yaw=-121.8 ok
                       → [Status] ack 3/3 forward 1/1 ok odo=0.30m cmd=0.68m
[Result] SUCCEEDED acks=3 turns_ok=2 odo_m=0.3 duration_s=13.4
```

## 5-1. 스키마 파일과 접속 주소

**`.proto` 파일**: 저장소 `schema/physical_command.proto` (브랜치 `HW`) 하나가 전부다.
이 파일만 있으면 어떤 언어로도 붙을 수 있다.

```bash
# 파이썬
protoc --python_out=. schema/physical_command.proto
# 자바스크립트(브라우저) — protobufjs 는 .proto 를 런타임에 읽을 수 있다
protobuf.load("physical_command.proto")
```

**접속 주소**

| 상황 | 주소 |
|---|---|
| 일반(백엔드·Unity) | `pi7.local:1883` (TCP, MQTT5) |
| 브라우저 | `ws://pi7.local:9001` (WebSocket) |
| **이름이 안 풀릴 때(발표장 등)** | 랩 네트워크에서는 **`192.168.50.172` 고정**(pi7 wlan0 정적 설정) |

핫스팟에서는 pi7 이 DHCP 로 주소를 받으므로 고정 IP 가 없다. 이름(mDNS)이 안 풀리는
환경이면 **발표 직전에 pi7 에서 `hostname -I` 로 확인**해 그 주소를 쓰거나,
그 핫스팟용 정적 주소를 미리 박아 둔다:

```bash
sudo nmcli connection modify hotspot-SysaiLAB ipv4.method manual      ipv4.addresses 192.168.137.50/24 ipv4.gateway 192.168.137.1
```
(위 값은 **Windows 모바일 핫스팟** 기준이다. 휴대폰 핫스팟이면 대역이 달라 그때 확인해야 한다.)

## 6. 로봇 쪽 구성 (참고)

```
 상위(백엔드)  ──MQTT5/protobuf──▶ pi7: robot-node (규약 서버, scan_mission)
                                        │ UDP 15100 "MISSION SCAN 8 45 5.0"
                                        ▼
                                   pi7: go1-sdk (go1_sdk_pc, 500Hz 제어)
                                        │ ACK JSON  UDP 15106 ─┐
                                        │ HighCmd UDP 8082     │
                                        ▼                      │
                                   Go1 로봇 ◀── 얼굴 라이트 UDP 7801 (헤드 Nano 브리지)
                                                               │
                            robot-node 가 ACK 를 CommandStatus 로 상위에 중계 ◀┘
```

두 서비스가 모두 떠 있어야 한다: `go1-sdk.service`(구동), `robot-node.service`(규약).
`go1-sdk` 는 기동 시 로봇이 기립하므로 부팅 자동시작이 기본 비활성이다.
