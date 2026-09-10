# 다중 로봇 규약 — 여러 대·여러 기종을 하나의 디지털트윈에

2026-09-08 신규. 기존 트윈은 **로봇 한 대 전용**이었다. 상태 스트림(15101)에 신원이
없어서 두 번째 로봇이 들어오면 같은 가상 로봇을 두 대가 나눠 흔드는 꼴이 된다.
Unitree Go1 이 두 대 들어오거나 RoboMaster EP 가 섞이면 대응이 안 된다.

이 문서는 그 확장 규약이다. 좌표 규약은 [coordinate-contract.md](coordinate-contract.md)
를 그대로 따른다.

## 1. 신원 — 로봇 한 대를 무엇으로 세는가

```
로봇 한 대 = (node_id, robot_type, robot_id)
```

| 필드 | 뜻 | 예 |
|---|---|---|
| `node_id` | **이 상태를 전달한 온보딩 라즈베리파이** | `pi1`, `pi7` |
| `robot_type` | 기종 | `go1`, `robomaster_ep` |
| `robot_id` | 그 파이 안에서의 로봇 번호 | `go1-1`, `ep-1` |

`node_id` 가 맨 앞에 오는 게 핵심이다. 같은 기종이 여러 대 들어와도 **어느 파이가
보냈는지**로 먼저 갈라지므로, 로봇들이 서로 같은 `robot_id` 를 써도 충돌하지 않는다.
실제로 검증에서 `pi7/go1/go1-1` 과 `pi1/go1/go1-1` 이 동시에 떠 있다 — 기종도 ID도
같지만 전달한 파이가 달라서 별개의 로봇으로 잡힌다.

`node_id` 는 **릴레이가 정한다.** 발신자가 무엇을 주장하든 덮어쓴다. 어느 파이를
거쳐 왔는지는 그 파이 자신만 확실히 알기 때문이다.

## 2. 포트

| 포트 | 방향 | 내용 |
|---|---|---|
| `15200/udp` | 로봇·피더 → **파이 릴레이** | 로봇 상태 ingress. 파이마다 하나 |
| `15201/udp` | **파이 릴레이** → Unity | 신원이 찍힌 상태. 모든 파이가 이 하나로 보낸다 |

기존 단일 로봇 경로(15100 텔레옵 / 15101 상태 / 5009 / 15102 / 15104 / 15110)는
**그대로 둔다.** 다중 로봇 경로는 별도 포트라 서로 간섭하지 않는다.

## 3. 메시지

Unity 로 가는 형식(v2). 공백 구분 텍스트 14필드.

```
ROBOT <node_id> <robot_type> <robot_id> <seq> <tms> <x> <z> <yaw> <vx> <vy> <wz> <estop> <mode>
```

뒤쪽 10필드는 기존 15101 페이로드와 **완전히 같다**. 좌표 규약도 같다
(위치 = Unity world X,Z / yaw = `eulerAngles.y` 규약, 시계 +, +Z 기준).

릴레이가 받아주는 형식은 세 가지다.

| # | 형식 | 쓰는 곳 |
|---|---|---|
| 1 | `ROBOT <node> <type> <id> + 10필드` | 릴레이 체인 |
| 2 | `<type> <id> + 10필드` | 피더, `go1_sdk_pc --relay_ip` |
| 3 | 10필드만 | 레거시. `type/id` 는 릴레이 기본값 |

## 4. 구성 요소

```
  가상 로봇 피더 ┐
                 ├─(15200)→ robot_state_relay.py (pi1) ─┐
  실물 로봇 ─────┘                                       ├─(15201)→ Unity
                                                         │          MultiRobotManager
  go1_sdk_pc --relay_ip 127.0.0.1 ─(15200)→ relay (pi7) ─┘
```

| 파일 | 위치 | 역할 |
|---|---|---|
| `pi/robot/robot_state_relay.py` | 각 파이 | 상태를 받아 `node_id` 를 찍어 Unity 로 전달 |
| `pi/robot/virtual_robot_feeder.py` | 아무 데나 | 가상 로봇 상태 생성 → 릴레이로 송출 |
| `pi/robot/go1_sdk_pc.cpp` | pi7 | `--relay_ip` 를 주면 상태를 릴레이로도 한 벌 보냄(**옵트인**) |
| `HW/Assets/Code/Multi/*.cs` | Unity | 수신·레지스트리·배치·시각화 |
| `HW/Assets/Editor/MultiRobotVerify.cs` | Unity | 배치모드 검증 + 화면 캡처 |

## 5. Unity 쪽 동작

- `MultiRobotStateReceiver` — 15201 을 별도 스레드에서 받아 큐에 넣는다.
- `MultiRobotManager` — 신원별로 가상 로봇을 만들고 갱신한다.
  - **파이마다 월드 기준점(lane)** 을 하나씩 준다(기본 6m 간격, 처음 보인 순서대로).
    로봇이 보고하는 `x,z` 를 그 기준점에 얹으므로 파이가 늘어도 겹치지 않는다.
  - 색은 파이별로 고정(`pi7` 청록 / `pi1` 주황), 형상은 기종별로 다르게 그린다.
  - `robotTimeoutSec`(기본 3초) 동안 상태가 없으면 지운다. **로봇이 빠져도 트윈은
    계속 돈다** — 남은 로봇들은 그대로 움직인다.
- `MultiRobotBootstrap` — 런타임 초기화 훅으로 어느 씬에서든 자동으로 뜬다.
  기존 씬(`lab.unity` 등)을 **수정하지 않는다**. 끄려면 Scripting Define 에
  `HW_NO_MULTIROBOT_BOOTSTRAP` 추가.

갱신 로직은 `MonoBehaviour.Update()` 가 아니라 `Tick(now)` 에 있다. 그래서 Play 모드와
에디터 배치 검증이 **같은 코드**를 돌린다.

## 6. 실행

파이마다 릴레이를 하나씩 띄운다.

```bash
# pi7
python3 ~/hw/pi/robot/robot_state_relay.py --node_id pi7 --unity_ip 192.168.50.244
# pi1
python3 ~/hw/pi/robot/robot_state_relay.py --node_id pi1 --unity_ip 192.168.50.244
```

가상 로봇을 붙인다.

```bash
python3 pi/robot/virtual_robot_feeder.py --relay <파이IP> --type go1 --count 2
python3 pi/robot/virtual_robot_feeder.py --relay <파이IP> --type robomaster_ep --count 1
```

실물 Go1 을 이 화면에 합류시키려면 SDK 에 릴레이 주소를 준다(기본은 꺼져 있다).

```bash
go1_sdk_pc --robot_ip 192.168.123.161 --unity_ip 192.168.50.244 \
           --relay_ip 127.0.0.1 --robot_id go1-real
```

## 7. 검증

```bash
"D:/editor/6000.3.5f2/Editor/Unity.exe" -batchmode -projectPath HW \
  -executeMethod MultiRobotVerify.RunAll -logFile <log> \
  -mrDuration 95 -mrOut pic -mrPort 15201
```

Unity 를 배치모드로 돌리면서 로봇 구성이 바뀔 때마다 화면을 `pic/step*.png` 로 남기고,
`pic/steps.md` 에 그 시점의 로봇 목록을 적는다.

**2026-09-08 결과** — 패킷 2952개 수신, 파싱 2952, 버림 0.

| 단계 | 상황 | 확인한 것 |
|---|---|---|
| 00 | 빈 트윈 | 수신 대기 |
| 01 | pi7 + Go1 ×1 | 등장·배치 |
| 02 | pi7 + Go1 ×2 | 같은 파이·같은 기종 다중 |
| 03 | pi1 + Go1 ×1 | **`pi7/go1/go1-1` 과 `pi1/go1/go1-1` 공존** — 기종·ID 가 같아도 파이로 구분 |
| 04 | pi1 + RoboMaster EP | 이기종 혼재 |
| 05 | pi7 피더 종료 | 타임아웃 이탈, **남은 pi1 로봇은 계속 주행** |
| 06~07 | 전부 종료 | 정리 후에도 트윈 유지 |
