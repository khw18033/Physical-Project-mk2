# 드론 파트 — RTK · SAR 직선 패스

viz-debugger(컴퓨터공학과 GUI)에 드론 파트 기능을 붙였다. 화면은 **계획 · 명령 · 감시**만 하고,
비행과 레이더 캡처 트리거(`CAP_ON`)는 드론 위(Raspberry Pi 5)의 `sar_pass` 실행기가 맡는다.

```
 [브라우저: viz-debugger]                       [Raspberry Pi 5 (컴패니언)]                   [FC: PX4]
  캔버스 노드 「SAR 패스 비행」 ── sar_start ──▶  드론 에이전트 ─▶ sar_pass ── MAVSDK ──▶ 오프보드 속도 제어
            「RTK 상태」       ◀── sar 상태 ───  (MQTT ws :9001)     │                     (TELEM2 ↔ UART)
                               ◀── state(gps) ─                     └─ touch/unlink /home/physical/CAP_ON
                                                                                ▲
                                                                     cansar.service 가 보고 캡처
```

브라우저는 드론의 파일을 만질 수 없다. 그리고 링크가 끊겨도 캡처는 드론 안에서 꺼져야 한다.
그래서 CAP_ON 은 드론 쪽 코드만 다룬다.

## 비행 조건 (요구사항 그대로)

| 항목 | 값 | 코드 |
|---|---|---|
| 고도 | 20 m 일정 (기본값, 5~120 m 허용) | `SarPlan.alt_m` |
| 직선 캡처 구간 | **60 m 이상** | `MIN_LINE_M` |
| 속도 | **3~5 m/s 등속**. 가속·감속은 구간 밖(lead-in · lead-out)에서 | `MIN_SPEED` · `MAX_SPEED` |
| 헤딩 | 구간 동안 진행 방향으로 고정 | 오프보드 `VelocityNedYaw` 의 yaw |
| 반복 | 같은 선 · 같은 방향 **2회 이상** | `MIN_PASSES` |
| 패스 간격 | 캡처 끝 → 다음 캡처 시작 **10초 이상** | `MIN_GAP_S` |

화면(`src/sar/plan.ts`)과 드론(`sar_pass/mission.py`)은 같은 숫자를 쓴다. 어긋나면 `npm run verify:sar` 가 실패한다.

### CAP_ON 이 켜지고 꺼지는 때

- **켜짐**: 캡처 시작점을 지난 뒤 「등속」이 1초 이어진 순간. 등속의 기준은 속도 ±0.2 m/s, yaw ±5°, 횡오차 ±2 m 다.
  가속 구간 길이는 `v²/(2·1 m/s²) + v·2 s` 로 자동으로 잡는다(4 m/s 면 16 m).
- **꺼짐**: 캡처 끝점에 닿은 순간. 감속은 그 뒤에 시작한다.
- **어떤 경우에도 꺼진다**:
  - 임무 `finally`: 완료, 중단, 실패 모두
  - 조종기 개입: 오프보드가 풀리거나 POSCTL · RTL · LAND 등으로 모드가 바뀐 경우
  - `sar_abort` 명령: 받는 즉시
  - SIGINT · SIGTERM · `atexit`
  - 감시 시한: `구간 길이 ÷ 속도 × 1.5 + 10초` 를 넘기면 강제로 끈다
- 경로는 `/home/physical/CAP_ON` 절대경로다. root 로 실행해도 같은 파일을 쓴다.

### 로그

- 패스마다 번호, 시작·끝 시각(`time.time()`), 평균 속도, 최대 오차(속도 · 횡 · 고도 · yaw)를 남긴다.
  - 파일: `sar_logs/sar_passes_<시각>.jsonl`
  - 화면: 「⑤ 패스 기록」. CSV 로 내려받을 수 있다.
- 비행 후 QGC 에서 `.ulg` 를 받아 위 시각과 맞춰 본다.

## 빠르게 돌려 보기

```bash
cd viz-debugger/drone
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e '.[test]'
.venv/bin/python -m pytest -q          # 49건 — CAP_ON · 시계 · RTK 기록 · RTCM 전달 · 상태판 텔레메트리

# 시뮬레이터를 실제 시간으로 돌리며 상태를 MQTT 로 보낸다 (화면 연습용 — 드론 없이)
.venv/bin/python -m sar_pass sim --heading 45 --length 80 --cap /tmp/CAP_ON --mqtt <브로커>:1883
```

`sim` 을 pi3 에서 돌리면 브라우저의 「SAR 패스 비행」 노드에 진행이 그대로 뜬다.
비행 없이 화면과 MQTT 경로를 점검할 수 있다. `--cap /tmp/CAP_ON` 을 꼭 줘야 한다 — 안 주면 실제 레이더가 캡처를 시작한다.

## 실기체 준비 (Holybro X500 V2 · H743 FC · Raspberry Pi 5 · 핫스팟)

> **펌웨어는 PX4, 지상국은 QGroundControl 이다**(2026-10-02 확인). 실행기는 PX4 오프보드 속도 제어를 쓴다.

### 연결 구성

```
 FC TELEM2 ──UART── Raspberry Pi 5 ── mavlink-router ─┬─ UDP 14540  sar_pass (오프보드 · CAP_ON) — MAVSDK 제어 끝점
   (Pi 팀 drone-mavlink-router)                       ├─ UDP 14541  linkmon · 14542 detect (팀 서비스)
                                                      ├─ UDP 14543  드론 에이전트 drone-node (state · ping, 수신 전용)
                                                      └─ TCP 5760   ◀── 핫스팟 와이파이 ── QGC (노트북) · rtk_relay
                     Pi 5: MQTT 브로커 (ws 9001) ◀──── 핫스팟 와이파이 ── 브라우저 (viz-debugger)
```

- **오프보드 제어는 파이 안에서 닫힌다.** 와이파이가 끊겨도 패스 비행과 CAP_ON 끄기는 파이 안에서 계속 돈다.
  끊겨서 못 하게 되는 것은 화면 감시와 QGC 의 RTK 보정 주입뿐이다.
- **RTK 보정(RTCM)도 와이파이로 간다.** QGC → TCP 5760 → mavlink-router → FC 다.
  와이파이가 끊기면 보정이 멈추고, 몇 초 뒤 RTK Fixed 가 Float 로 떨어질 수 있다.
  캡처 중 fix 등급은 `live.gps_fix` 로 화면과 패스 기록에 남는다.
- **조종기(RC)가 안전 링크다.** 와이파이 거리는 핫스팟 기기에 따라 수십~백 m 수준이다.
  가속 구간을 포함하면 패스 하나가 100 m 를 넘을 수 있으니, 지상국은 선 가운데 옆에 둔다.

### 설정

1. **FC ↔ Pi 5 UART**: FC 의 TELEM2 를 Pi 5 의 GPIO14(TX)/15(RX) · GND 에 잇는다. TX↔RX 는 교차로 연결한다.
   - Pi 5 쪽:
     - `/boot/firmware/config.txt` 에 `dtparam=uart0=on` 을 넣으면 `/dev/ttyAMA0` 가 생긴다.
     - 시리얼 콘솔은 끈다(`raspi-config` → Interface → Serial: 로그인 셸 No, 하드웨어 Yes).
   - PX4 파라미터:
     - `MAV_1_CONFIG = TELEM 2`
     - `MAV_1_MODE = Onboard`
     - `SER_TEL2_BAUD = 921600`
2. **mavlink-router**: Pi 팀의 `drone-mavlink-router`(설정 `~/drone/config/mavlink-router.conf`)가 이미 끝점을 열어 두었다
   (14540 MAVSDK 제어 · 14541 linkmon · 14542 detect · 14543 drone-node · TCP 5760 QGC). **설정을 바꿀 필요가 없다.**
   - `sar_pass` 는 14540 에 붙는다. 이 끝점은 「한 번에 하나」라 SAR 비행 중에는 점검 스크립트(`check_link` 등)를 같이 돌리지 않는다.
   - QGC: Application Settings → Comm Links → Add → **TCP**, Host = Pi 의 핫스팟 IP, Port = 5760.
3. **브라우저 → MQTT**: 화면 ⇄ 연결 관리의 물리 장비 칸에 `ws://<Pi 핫스팟 IP>:9001` 을 적는다.
   - 기본 프리셋(`pi3.tailcb6bfb.ts.net`)은 Tailscale 이름이라, 핫스팟에 인터넷이 없으면 안 닿는다.
   - 핫스팟이 IP 를 바꿀 수 있으니, 핫스팟 기기에서 Pi 에 고정 IP 를 주거나 `<호스트명>.local`(mDNS)을 쓴다.
4. **오프보드 · 링크 안전 파라미터**: 이름은 PX4 버전마다 조금 다를 수 있으니 QGC 파라미터 검색으로 확인한다.
   - `COM_OF_LOSS_T`: 오프보드 설정값이 끊긴 뒤 판정까지의 시간. 실행기는 20 Hz 로 보낸다. 1초 안팎을 권장한다.
   - `COM_OBL_RC_ACT`: 오프보드가 끊겼을 때 할 동작. Hold 또는 RTL 을 권장한다.
   - `COM_RC_OVERRIDE`: 오프보드 중 스틱을 움직이면 조종기가 넘겨받게 하는 설정. **켜 두기를 권장한다.**
     실행기는 이것을 「조종기 개입」으로 보고 CAP_ON 을 지운 뒤 멈춘다.
   - `NAV_DLL_ACT` · `COM_DL_LOSS_T`: **지상국(QGC) 링크가 끊겼을 때의 페일세이프.** 핫스팟이라 실제로 끊길 수 있다.
     이것이 RTL 등으로 모드를 바꾸면 실행기는 조종기 개입과 같게 보고 CAP_ON 을 지운 뒤 멈춘다(안전한 쪽).
     오프보드 제어는 파이 안에서 닫히므로, 와이파이 순단 때문에 패스가 끊기는 것이 싫다면 이 동작을 팀이 정한다.
5. **RTK**: 보정(RTCM) 넣는 길은 둘이다. 아래 「RTK 보정 넣기」를 본다. **둘 중 하나만 쓴다.**
   실행기는 기본으로 **RTK Fixed 가 아니면 시작을 거절한다**. 끄려면 `--no-rtk` 를 주거나 화면에서 체크를 해제한다.
6. **설치 (Pi 5)**:
   ```bash
   cd drone && python3 -m venv .venv && .venv/bin/pip install -e .   # mavsdk-grpc 가 aarch64 용 mavsdk_server 를 같이 받는다
   ```
7. **첫 비행 순서 (권장)**:
   1. `sim --mqtt` 로 화면 경로를 점검한다.
   2. 프롭을 떼고 `run` 을 실행한다. 이륙 상태가 아니므로 비행 전 점검에서 거절되는지 본다.
   3. 넓은 곳에서 조종기로 이륙한 뒤 `run` 을 1회 실행한다.
   4. 비행 중 조종기로 모드를 바꿔 CAP_ON 이 지워지는지 확인한다.

## 비행 전 점검 — 날지 않는다

```bash
.venv/bin/python -m sar_pass check --connect udpin://0.0.0.0:14540 --mqtt 127.0.0.1:1883
```

```
 ✓  CAP_ON 자리       /home/physical 쓰기 가능
 ✓  시계 동기화       NTP 동기화됨
 ✓  cansar.service    active
 ✓  MQTT 브로커       127.0.0.1:1883
 ✓  FC 연결           udpin://0.0.0.0:14540
 ✓  GPS fix           RTK_FIXED · 위성 27개
 ✓  시계 오차         이 컴퓨터 − FC(GPS) = +0.041 s
```

✗ 가 하나라도 있으면 종료 코드 1 이다. `run` 의 비행 전 점검도 같은 것을 다시 본다.
- CAP_ON 자리가 없거나 쓸 수 없으면 거절한다.
- 지난 비행이 남긴 CAP_ON 은 지우고 시작한다.
- RTK Fixed 가 아니면 거절한다.
- 시계 오차가 ±1 s 를 넘으면 거절한다.

### 시간 동기화

패스 시각은 파이 시계(`time.time()`)다. `.ulg` 와 레이더 데이터에 맞추려면 이 시계가 맞아야 한다.
- 실행기는 FC 가 GPS 로 맞춘 UTC(MAVLink `SYSTEM_TIME`)와 파이 시계를 비교한다.
  ±1 s 를 넘으면 시작을 거절한다. `--allow-clock-skew` 로 넘길 수 있고, 그 경우 기록에 남는다.
- 패스 기록에는 두 시각을 함께 남긴다: 파이 시계 기준(`start_unix`)과 FC GPS 시각 기준(`fc_start_unix`).
  `.ulg` 와 맞출 때는 `fc_*` 를 쓴다.
- 핫스팟에 인터넷이 있으면 NTP 로 맞춘다. 없으면 비행 전에 노트북 시각으로 맞추거나(`sudo date -s @<epoch>`),
  chrony + GPS 시각을 쓴다.
- **레이더(cansar) 데이터에 같은 파이 시계가 찍히는지는 레이더 쪽과 확인해야 한다.**
  cansar 가 CAP_ON 을 몇 초마다 확인하는지도 물어볼 것. 확인 주기만큼 실제 캡처가 늦게 시작하고 늦게 끝난다
  (1 s 주기 · 4 m/s 면 최대 4 m).

### 등속 판정 기준 조정

실비행에서 바람 때문에 「등속」을 못 잡으면 그 패스는 「캡처 없음」으로 끝난다(안전한 쪽).
첫 비행 로그의 `max_speed_err_mps` 를 보고 기준을 조정한다.

```bash
python -m sar_pass run ... --speed-tol 0.3 --heading-tol 5 --cross-tol 2 --stable-hold 1.0
```

화면에서 보낼 때는 `sar_start` 파라미터 `speed_tol` · `heading_tol` · `cross_tol` · `stable_hold_s` 로 실린다.
안 주면 기본값(0.2 m/s · 5° · 2 m · 1 s)이다.

## RTK 보정 넣기 (PX4 · QGroundControl)

PX4 는 MAVLink `GPS_RTCM_DATA` 로 들어온 보정을 GPS 모듈로 그대로 흘린다. 보내는 쪽이 QGC 든 스크립트든 PX4 쪽 설정은 같다.
**두 방법을 동시에 쓰지 않는다.** 같은 베이스를 둘이 열 수 없고, 같이 넣으면 FC 에 보정이 두 번 들어간다.

> **우리 베이스는 MicoAir M-RTK 다(배터리 내장형).** 이 베이스는 공식적으로 Mission Planner 만 지원하고,
> Mission Planner 의 「RTK Inject」는 베이스 COM 포트의 RTCM 을 FC 로 그대로 넘겨 주는 기능이다.
> QGC 의 내장 RTK(방법 A)는 QGC 가 직접 설정할 줄 아는 수신기(u-blox 등)만 다루므로 이 베이스에는 맞지 않을 가능성이 높다.
> **그래서 이 구성의 기본은 방법 B 다.** 비행 · 설정은 PX4 + QGC 로 하고, 보정만 스크립트가 넣는다.
> 베이스 설정(Survey-in · 출력 메시지)은 MicoAir 쪽 도구에서 미리 해 둔다. 스크립트는 나오는 RTCM 을 옮기기만 한다.

### 방법 A — QGC 내장 기능 (스크립트 없음 · QGC 가 지원하는 베이스일 때만)

```
 베이스 ─USB─▶ 노트북 QGC ─TCP 5760(핫스팟)─▶ Pi mavlink-router ─▶ FC
```

1. 베이스 수신기를 QGC 노트북에 USB 로 꽂는다(u-blox M8P/F9P 계열은 QGC 가 자동 인식).
2. QGC → Application Settings → **RTK GPS**: Survey-in 정확도·시간을 정하거나 고정 기지국 좌표를 넣는다.
3. QGC 상단에 RTK 아이콘이 생기고, Survey-in 이 끝나면 QGC 가 보정을 기체 링크(TCP 5760)로 보낸다.
4. 화면 「RTK 상태」의 fix 가 RTK Float → Fixed 로 오르는지 본다. 「보정(RTCM)」 줄은 「전달기 보고 없음」으로 남는다(정상).

### 방법 B — 스크립트 직접 전달 (`rtk_relay`, MicoAir M-RTK 는 이것)

```
 베이스 ─USB─▶ 노트북 base_sender.py ─UDP 14660(핫스팟)─▶ Pi fc_injector.py ─GPS_RTCM_DATA─▶ mavlink-router(TCP 5760) ─▶ FC
```

- QGC 를 안 켜도 된다. Pi 팀 mavlink-router 설정도 바꾸지 않는다(QGC 와 같은 TCP 5760 에 손님으로 붙는다).
- 화면 「RTK 상태」에 **보정 수신 중 / 끊김**, 초당 프레임, 베이스 위치(1005/1006)가 뜬다. 그래서 Float 로 떨어졌을 때
  보정이 끊겨서인지 하늘이 나빠서인지 가를 수 있다.

```bash
# Pi (상주 — 보정이 이륙 전부터 계속 흘러야 Fixed 가 잡힌다)
.venv/bin/python -m rtk_relay.fc_injector --listen 0.0.0.0:14660 --fc tcp:127.0.0.1:5760 --mqtt 127.0.0.1:1883

# 노트북 (Windows 예 — pip install pyserial, drone/ 폴더에서)
python -m rtk_relay.base_sender --port COM12 --baud 115200 --to <Pi 핫스팟 IP>:14660   # M-RTK (CH340)
```

- **베이스 설정**: 베이스가 이미 RTCM3 를 내보내고 있어야 한다.
  - MicoAir M-RTK: Mission Planner 에서 쓰던 그대로 둔다. 같은 COM 포트를 Mission Planner 가 잡고 있으면 스크립트가 못 연다.
  - u-blox 면 u-center 에서 Survey-in(또는 고정 좌표)을 설정한다.
  - 출력 메시지는 1005, MSM(1077 · 1087 · 1097 · 1127), 1230 을 켠다.
  - 설정은 플래시에 저장해 둔다(방법 A 는 QGC 가 이것을 대신 해 준다).
- 노트북 스크립트는 CRC 가 맞는 RTCM3 프레임만 보낸다(NMEA 등이 섞여도 걸러진다). 5초마다 「보정 수신 중 · B/s · 메시지 · 베이스 위치」를 찍는다.
- Pi 스크립트는 받은 프레임을 다시 검사한다. 180 바이트씩 최대 4조각으로 나눠 `GPS_RTCM_DATA` 로 넣는다(QGC 와 같은 규칙).
  MAVLink 시스템 ID 는 252 를 쓴다(QGC 255 · MAVSDK 245 와 안 겹치게).
- 이미 쓰던 노트북 스크립트 `cansar_rtcm_send.py` 도 그대로 Pi 의 `fc_injector` 와 맞물린다(같은 UDP 14660 ·
  프레임 하나 = 데이터그램 하나). 단, `sendto` 를 `try/except OSError` 로 감싸야 와이파이가 끊겼을 때 스크립트가 안 죽는다.
- Pi 에서 `cansar_pi.py` 가 이미 14660 을 받아 주입하고 있다면 `fc_injector` 는 켜지 않는다(포트가 겹친다).
- 기존 MAVLink 프로그램(예: `cansar_pi.py`)에 직접 붙이려면 아래 한 줄이면 된다. 그 프로그램의 pymavlink 연결을 쓴다.
  ```python
  from rtk_relay.inject import PymavlinkInjector
  from rtk_relay.rtcm3 import Framer
  inj, framer = PymavlinkInjector(master), Framer()
  for frame in framer.feed(udp_bytes): inj.send_frame(frame)
  ```
- 핫스팟 와이파이에 의존하는 것은 방법 A 와 같다. 끊기면 화면에 「보정 끊김 · N초째」가 뜨고, 몇 초 뒤 Fixed 가 Float 로 떨어질 수 있다.
  캡처 중 가장 나빴던 fix 는 패스 기록의 「RTK 최저」에 남는다.

## 드론 상태판 (MicoConfigurator 처럼)

캔버스 팔레트의 **「드론 상태판」** 노드. 접힘은 상태 줄 한 줄이고, 확대(더블클릭)하면 아래가 다 나온다.

| 영역 | 내용 | 원천 |
|---|---|---|
| 상태 줄 | 링크(heartbeat 나이 · 초당 메시지) · 모드 · ARMED · GPS/RTK · **EKF POS·VEL·MAG·TER·VER** · 배터리 · RC RSSI · 보정 수신 · 시계 오차 | fcx (+state) |
| 자세 · 방위 | 인공수평의(롤 · 피치) · 나침반(기수 · 홈 방향) | fcx 또는 state |
| 지도 · 궤적 | 최근 3분 궤적 · 홈 · 드론 방향 · SAR 선(캡처 중 빨강) · 축척. 「지도 배경」을 켜면 OpenStreetMap(인터넷 필요) | fcx · sar |
| 그래프 | 고도 · 지면 속도 · 상승률 · 배터리 전압 (최근 2분, 십자선 툴팁) | fcx |
| GPS · RTK | fix · 위성 · HDOP/VDOP · 정확도 · RTK 기선/정확도/IAR · 위치 · 홈 | fcx (+state) |
| 센서 건강 | SYS_STATUS 의 센서마다 ✓/✕ · FC 부하 · 통신 손실 | fcx |
| 진동 | X/Y/Z m/s² (30 주의 · 60 위험) · 가속도 포화 | fcx |
| 배터리 | 전압 · 잔량 · 전류 · 소모 · 온도 · **셀 전압과 편차** | fcx (+state) |
| 메시지 | FC STATUSTEXT 콘솔 (경고 이상만 거르기) | fcx (없으면 state 의 최근 5줄) |

`fcx` 는 Pi 의 **수신 전용** 수집기 `fc_watch` 가 FC MAVLink 를 읽어 MQTT `zoneA/drone/<id>/fcx`(5 Hz, retained)로 낸다.
드론 에이전트의 `state`(1 Hz)에는 EKF · 센서 건강 · 진동 · 셀 전압 · 속도가 없어서, `fc_watch` 없이는 자세 · GPS · 배터리 · 모드만 나온다.
화면이 그 사실(「기본 상태만」)을 적는다.

```bash
# Pi — 따로 띄우거나
.venv/bin/python -m fc_watch --fc tcp:127.0.0.1:5760 --mqtt 127.0.0.1:1883
# 보정 주입기에 같이 태운다 (TCP 연결 하나로 둘 다)
.venv/bin/python -m rtk_relay.fc_injector --listen 0.0.0.0:14660 --fc tcp:127.0.0.1:5760 --mqtt 127.0.0.1:1883 --telemetry
```

- FC 로 아무것도 보내지 않는다. Pi 팀 mavlink-router 설정도 그대로다(QGC 와 같은 TCP 5760 에 손님으로 붙는다).
- EKF 표시는 PX4 의 `ESTIMATOR_STATUS` 비율로 판정한다(0.5 미만 ✓ · 1 미만 ! · 그 이상 ✕). QGC 와 MicoConfigurator 와 같은 기준이다.
  PX4 가 Onboard 링크로 이 메시지를 안 보내면 칩이 안 뜬다. 그때는 QGC 의 MAVLink 콘솔에서 `mavlink stream -d /dev/ttyS? -s ESTIMATOR_STATUS -r 2` 처럼 켠다.

## 실행

```bash
# 조종기로 20 m 근처까지 이륙한 뒤. 시작점은 지금 위치, 방위 45°, 80 m, 4 m/s, 2회.
sudo .venv/bin/python -m sar_pass run --heading 45 --length 80 --speed 4 --passes 2 --gap 10 \
     --mqtt 127.0.0.1:1883 --device x500-001
# 시작·끝점을 직접 줄 때
.venv/bin/python -m sar_pass run --start 37.56650,126.97800 --end 37.56701,126.97864 ...
```

Ctrl-C 를 누르면 중단한다. CAP_ON 을 지우고 hold 한다(`--rtl-on-abort` 를 주면 RTL).
`--mqtt` 를 주면 화면에 진행이 뜬다. 이 경우 화면의 「중단」 버튼은 에이전트 연동(아래) 뒤에 동작한다.

## 화면 ↔ 드론 규약

### 상태 — 드론 → 화면

- 토픽: `zoneA/drone/<device_id>/sar`
- 형식: JSON, **retained**, QoS 0, 0.5초마다와 상태가 바뀔 때마다
- 보내는 쪽: `sar_pass/status.py`
- 받는 쪽: `src/physical/sarFeed.ts`

```jsonc
{
  "schema_version": "sar-0.1", "channel": "sar",
  "source_id": "x500-001", "node_id": "pi3", "zone_id": "zoneA", "timestamp": "…",
  "state": "capture",            // idle preflight transit gap accel capture decel returning done aborted failed
  "pass": 2, "passes_total": 2,
  "capturing": true,             // CAP_ON 파일이 지금 있는가 (드론이 직접 확인)
  "plan": { "start_lat": …, "start_lon": …, "end_lat": …, "end_lon": …, "alt_m": 20, "speed_mps": 4,
            "passes": 2, "gap_s": 10, "lead_in_m": 16, "length_m": 80, "heading_deg": 45, "require_rtk": true },
  "live": { "ground_speed_mps": 4.01, "alt_rel_m": 20.1, "yaw_deg": 45.2, "heading_err_deg": 0.2,
            "along_m": 31.4, "cross_track_m": 0.12, "gps_fix": "RTK_FIXED", "flight_mode": "OFFBOARD" },
  "passes": [ { "pass_no": 1, "start_unix": …, "end_unix": …, "duration_s": 20.0, "captured": true,
                "mean_speed_mps": 4.01, "max_speed_err_mps": 0.16, "max_cross_track_m": 0.19,
                "max_alt_err_m": 0.08, "max_heading_err_deg": 0.9, "along_at_start_m": 0.1,
                "fc_start_unix": …, "fc_end_unix": …, "worst_fix": "RTK_FIXED", "note": "" } ],
  "clock_offset_s": 0.041,       // 파이 − FC(GPS). null 은 모름
  "warnings": [],
  "message": null, "error": null, "time": 1790930893.0
}
```

### 명령 — 화면 → 드론

기존 규약을 그대로 쓴다. `.proto` 는 바꾸지 않았다.

- `PhysicalCommandEnvelope.Command` 에 실어 `terminal/<id>/downlink` 로 보낸다.
- 파라미터는 `map<string,double>` 이다. 참·거짓은 1/0 으로 싣는다.

| action | parameters |
|---|---|
| `sar_start` | `start_lat start_lon end_lat end_lon alt_m speed_mps passes gap_s lead_in_m require_rtk rtl_on_abort rtl_on_done` |
| `sar_abort` | (없음) |

화면은 **장비가 `Capability.actions` 에 선언한 action 만 보낸다**(저장소 규칙).

- 선언이 없으면 시작 버튼이 닫힌다.
- 중단은 선언했거나, 선언 목록을 아직 못 받았으면(모름) 보낸다.

### 드론 에이전트 연동 (Pi 쪽 할 일)

pi3 의 드론 에이전트(`drone-node.service`)는 **저장소 어느 브랜치에도 없고 Pi 에만 있다**
(`~/hw/pi/drone/drone_node.py` · `drone_link.py`). HW 브랜치의 공통 틀 `pi/common/` 을 상속한다.
정확한 패치는 그 파일을 Pi 에서 받아 와서 쓴다. 공통 틀에서 확인한 사실은 다음과 같다.
- **Capability**: 노드의 `ACTIONS` 사전의 키가 그대로 선언된다(`pi/common/physical_command.py`).
- **처리 순서**: 명령이 오면 미선언 확인(UNIMPLEMENTED) → `validate(action, params)` → Acceptance → 스레드에서 실행.
- **스레드 방식이다(asyncio 아님).** paho 망 스레드에서 받아 명령마다 데몬 스레드로 돈다.

`SarController` 는 asyncio 라 전용 루프 하나를 데몬 스레드로 띄워 붙인다. `common/` 은 고치지 않는다.

```python
import asyncio, threading
from pathlib import Path
from sar_pass.controller import SarController, ACTIONS as SAR_ACTIONS
from sar_pass.capture import CaptureFlag
from sar_pass.mavsdk_vehicle import MavsdkVehicle
from common.physical_command import CommandError

class DroneNode(BaseNode):
    ACTIONS = {"ping": act_ping_drone, "sar_start": act_sar_start, "sar_abort": act_sar_abort}  # ① 선언

    def __init__(self, ...):
        self._aloop = asyncio.new_event_loop()                        # BaseNode.__init__ 이 곧바로 붙으므로 그 전에
        threading.Thread(target=self._aloop.run_forever, daemon=True).start()
        async def make_vehicle():
            v = MavsdkVehicle("udpin://0.0.0.0:14540"); await v.connect(); return v
        self.sar = SarController(make_vehicle, CaptureFlag(), status_sink=self._publish_sar,
                                 log_dir=Path("/var/lib/drone-node/sar"))  # ProtectSystem=strict → StateDirectory
        super().__init__(...)

    def _sar_call(self, action, params, timeout=10):
        return asyncio.run_coroutine_threadsafe(self.sar.handle(action, dict(params)), self._aloop).result(timeout)

    def validate(self, action, params):                                # ② Acceptance 전에 — 거절은 거절로
        if action in SAR_ACTIONS:
            r = self._sar_call(action, params)
            if not r["accepted"]:
                raise CommandError(r["code"] or "FAILED_PRECONDITION", r["message"])

def act_sar_start(node, params):                                       # ③ 실행 단계 보고
    yield "executing", None
    yield "completed", {"started": 1.0}

def act_sar_abort(node, params):
    yield "completed", {"aborted": 1.0}
```

- `_publish_sar` 는 MQTT `zoneA/drone/x500-001/sar`(retained)로 낸다. `sar_pass.status.MqttStatusPublisher` 와 같은 모양이다.
- `validate` 는 paho 망 스레드에서 돈다. MAVSDK 연결(최대 수 초)이 길어지면 MQTT 입출력이 그동안 멈춘다.
  기동 때 미리 붙여 두거나 시한을 짧게 둔다.
- 협의할 것(HW 담당):
  - 계약 §0·§4 의 「보기 전용 · FC 로 0 바이트」가 바뀐다. `drone_link` 의 `tx_bytes` 는 여전히 0 이다(MAVSDK 는 자기 소켓을 쓴다).
  - 14540 은 점검 스크립트와 한 번에 하나씩 쓴다.
  - `drone-node.service` 가 쓰는 venv 에 `mavsdk-grpc` 를 넣어야 한다.

연동 전에도 쓸 수 있다. Pi 에서 `python -m sar_pass run … --mqtt` 로 직접 돌리면 화면은 감시용으로 그대로 동작한다.

## 파일

| 위치 | 내용 |
|---|---|
| `drone/sar_pass/mission.py` | 패스 임무: 상태 기계, 등속 판정, CAP_ON 시점, 로그 |
| `drone/sar_pass/capture.py` | CAP_ON 켜기/끄기와 겹겹의 안전장치 |
| `drone/sar_pass/geometry.py` | 위경도 ↔ 지역 좌표, 진행/횡 거리 |
| `drone/sar_pass/vehicle.py` | 비행체 면 + 시뮬레이터 |
| `drone/sar_pass/mavsdk_vehicle.py` | PX4 실기체(MAVSDK) |
| `drone/sar_pass/controller.py` | 에이전트가 부르는 `sar_start` / `sar_abort` 처리 |
| `drone/sar_pass/status.py` | 화면으로 상태 보고(MQTT) |
| `drone/sar_pass/check.py` | 비행 전 점검(`python -m sar_pass check`) |
| `drone/rtk_relay/base_sender.py` | 노트북: 베이스 RTCM3 → UDP |
| `drone/rtk_relay/fc_injector.py` | Pi: UDP → GPS_RTCM_DATA → FC, 상태 MQTT `…/rtcm` |
| `drone/fc_watch/` | Pi: FC MAVLink → 상태판 텔레메트리 `…/fcx` (수신 전용) · 시험용 가짜 FC |
| `src/dronedash/` · `src/physical/fcxFeed.ts` · `src/shared/fcxStatus.ts` | 화면: 드론 상태판 |
| `drone/rtk_relay/rtcm3.py` · `inject.py` | RTCM3 프레임 · CRC · 1005 베이스 위치 · 조각내기 |
| `src/physical/rtcmFeed.ts` · `src/shared/rtcmStatus.ts` | 화면: 보정 전달 상태 수신 |
| `src/sar/` | 화면: RTK 노드, SAR 패스 노드, 계획 계산 |
| `src/physical/sarFeed.ts` · `sarCommands.ts` | 화면: 상태 수신, 명령 발행 |
| `src/shared/sarStatus.ts` | 화면: SAR 상태 저장소 |
| `scripts/verify-sar.mjs` | 화면 검사 (`npm run verify:sar`) |
