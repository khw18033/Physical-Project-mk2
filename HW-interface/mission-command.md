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
| 토픽(받음) | `terminal/go1-001/uplink` |
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

> **왜 임무 종류가 문자열 파라미터가 아니라 action 이름인가**
> 규약 `Command.parameters` 가 `map<string, double>` 이라 문자열을 실을 수 없다.
> 그래서 기존 `assign_mission`(mission_id·subtask 가 문자열)은 규약 경로로 호출할 수 없고,
> 로봇 임무는 **action 이름 자체를 어휘로** 쓴다. 규약에 문자열 파라미터가 생기면 통합한다.

## 3. 무엇이 돌아오나

`terminal/go1-001/uplink` 로 순서대로 온다. steps=8 이면 **ACK 10건**(스캔 8 + 문 방향 1 + 직진 1).

```
CommandAcceptance  accepted=true
CommandStatus      EXECUTING  "executing"
CommandStatus      EXECUTING  "ack 1/10 scan_turn 1/8 yaw=-36.6 ok"
CommandStatus      EXECUTING  "ack 2/10 scan_turn 2/8 yaw=8.3 ok"
   ...
CommandStatus      EXECUTING  "ack 9/10 door_turn 1/1 yaw=-74.2 ok"
CommandStatus      EXECUTING  "ack 10/10 forward 1/1 yaw=-123.7 ok odo=1.00m cmd=2.00m"
CommandResult      SUCCEEDED  {acks:10, turns_ok:9, steps:8, step_deg:45,
                               forward_m:1.0, odo_m:1.0, duration_s:62.3}
```

- `yaw` 는 Unity 규약 방위(도). `odo=` 는 로봇 오도메트리 실측 이동거리, `cmd=` 는 명령 적분값.
- 회전이 시한 안에 목표각에 못 닿으면 그 ACK 의 꼬리가 `turn_timeout` 이 된다(미션은 계속 진행).
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

## 4. 중간에 멈추려면

같은 규약의 취소를 쓴다 — `CancelCommandRequest { command_id }` 를 downlink 로.
로봇은 즉시 정지하고 `CancelCommandResponse(accepted=true)` 에 이어
`CommandResult(status=CANCELED)` 를 보낸다(§5-3 취소 우선).

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
