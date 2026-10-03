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
.venv/bin/python -m pytest -q          # 61건 — CAP_ON · 품질/재비행 · 레이더 확인 · RTCM · 상태판 · 데이터 서버 · SAR 영상

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

## 코너리플렉터 확인 · SAR 영상 (`sar_image`)

> 레이더 정보는 `radar.json` 하나다(`sar_image/example_radar.json` 은 **예시 값** — X대역 9.6 GHz · 300 MHz 가정).
> 파장 · 대역폭 · PRF · 기록 거리 · 안테나 방향(좌/우) · 내려다보는 각 · 빔폭을 레이더 팀이 채운다.

```bash
# ① 리플렉터가 보일까 — 계획 선과 실제 비행 궤적 둘 다로 판정한다
python -m sar_image coverage --traj sar_logs/flight_*/pass02_*.csv --radar radar.json --cr 37.56650,126.97839
#   CR1: ✓ 보인다 · 지상거리 20.0 m · 경사 28.39 m · 진행 40.0 m · 개구 15.21 m (100%) · 빔 안 4.0 s

# ② 레이더 거리-시간 영상에 겹쳐 볼 예상 쌍곡선 (시각 = FC GPS UTC)
python -m sar_image predict --traj pass02.csv --radar radar.json --cr 37.56650,126.97839 --out cr1_range.csv

# ③ 레이더 없이 영상 형성까지 시험 (실제 궤적 + 합성 리플렉터 신호 → 백프로젝션)
python -m sar_image simulate --traj pass02.csv --radar radar.json --cr 37.56650,126.97839 --pos-error-mm 20 --autofocus --png out.png

# ④ 실제 영상 — 레이더 원시 형식에 맞춘 어댑터 하나만 쓰면 된다 (sar_image/adapters.py 의 규약)
python -m sar_image form --traj pass02.csv --radar radar.json --raw radar/pass02 --adapter mymod:load --autofocus-cr 37.5665,126.9784 --png img.png
```

### 알아낸 것 (PX4 SITL 궤적 · 예시 X대역 기준) — 레이더 팀과 공유할 것

| 궤적 위치 오차 | 리플렉터 봉우리 | 비고 |
|---|---|---|
| 0 | 0 dB | 정확한 위치 · 방위 해상도 측정 0.025 m = 이론 0.026 m |
| 4 mm (λ/8) | −2.5 dB | 한계 |
| 1 cm | −7.9 dB | |
| **2 cm (보통 RTK)** | **−13 dB · 0.45 m 엉뚱한 자리** | `screenshots/13_SAR영상_2_*` |

- **RTK 궤적만으로는 X대역 초점이 안 맞는다.** 초점에는 시선 방향 위치를 λ/8(≈4 mm)까지 알아야 한다.
- **리플렉터 1개 자동 초점**(`--autofocus`): 그 리플렉터는 −13 dB → −1.3 dB 로 돌아오고 제자리에 맺힌다.
  리플렉터 확인 · 위치 검증에는 충분하다. 다만 둘레 몇 m 만 맞는다(시선 방향이 달라지면 오차가 달라진다).
- **장면 전체**를 맞추려면 궤적 오차를 3차원으로 알아야 한다 — 리플렉터 **4개 이상이 동시에 빔 안에** 있으면
  `estimate_trajectory_error` 가 그 구간의 오차를 λ/8 아래로 푼다(3개로는 리플렉터별 상수가 안 풀린다).
  장면 전체를 덮으려면 선을 따라 리플렉터를 촘촘히 깔거나, 데이터 기반 자동 초점(PGA · 최소 엔트로피)이 다음 단계다.
- 파장이 길수록(L · C대역) 요구 정밀도가 그만큼 풀린다.
- 빔폭은 **안테나 면에서** 잰다 — 수평면에서 재면 개구가 짧게 잡힌다(28 m 에서 10.7 m vs 실제 15.2 m).

### 패스별 영상 — 노트북에서 자동으로 (`sar_data --mirror`)

Pi 는 비행 중 50 Hz 제어를 하므로 영상은 **노트북**에서 만든다. 노트북의 데이터 서버가 Pi 의 데이터 서버에서
끝난 패스(궤적 + 레이더 원시)를 가져와 영상을 만들고, 화면은 노트북 서버를 본다.

```bash
# 노트북 — 화면의 ⇄ 연결 관리 → 「드론 데이터 서버」를 http://127.0.0.1:8765 로
python -m sar_data --flights ~/sar_mirror --mirror http://<Pi IP>:8765 --bind 127.0.0.1 \
    --radar-json radar.json --adapter sar_image.adapters:fmcw_dechirped_npz \
    --reflectors reflectors.csv --auto-image
```

- 패스가 끝나고 20 초 뒤(레이더가 파일을 옮길 시간)에 받는다. 받자마자 영상을 만든다(`--auto-image`).
- 화면 「결과 · 내려받기」에서 패스마다 「영상 만들기 / 다시 만들기」를 누를 수 있다. 화면에 놓은 리플렉터가 같이 간다.
- 결과: 리플렉터별 「찍힘 / 안 보임」 · 밝기 대비 · 위치 차이 · 해상도 · 확대 그림 → 선 전체 영상 → 위성 지도 겹침.
- 자동 초점은 찍힌 리플렉터로 한다: 4개 이상 동시에 빔 안 → 3차원 궤적 보정, 아니면 이어 붙이기, 하나면 그 둘레만.
- 계산은 32비트 · 여러 코어(`backproject_fast`)다. 영상 중심으로 좌표를 옮긴 뒤 32비트로 바꾸므로 64비트와 −50 dB 아래로 같다
  (UTM 같은 큰 좌표를 그대로 32비트로 하면 깨진다 — 시험이 막는다). 선 전체(90 × 33 m, 5 × 10 cm) 한 패스에 약 20 초.
- 레이더 없이 전체 흐름 시험: `sar_image/fakeraw.py` 가 궤적에 맞춘 FMCW 가짜 원시를 쓴다.
- **레이더 팀이 할 일은 어댑터 하나**다(`sar_image/adapters.py` 규약): 원시 파일 → (펄스 시각 t_fc, 거리 축, 거리 압축 복소).

### 레버암 — 안테나 장착 위치 (`sar_image/attitude.py`)

RTK 가 주는 위치는 **GPS 안테나**(또는 FC)의 위치다. 영상에 필요한 것은 **레이더 안테나 위상중심**의 위치다.
둘 사이의 벡터(레버암)는 기체에 붙어 있어, 기체가 기울면 같이 돈다. 그래서 펄스마다 그 순간 자세로 돌려 더한다.

`radar.json` 에 자로 잰 값을 넣는다. 화면에서는 「SAR 패스」 → 안테나 설정 → 「안테나 장착 위치」에서 넣고 radar.json 을 내려받는다.

| 칸 | 뜻 (m, 기체 기준 앞 · 오른쪽 · 아래 +) |
|---|---|
| `antenna_offset_m` | FC 보드 중심 → 레이더 안테나 위상중심 |
| `gnss_offset_m` | FC 보드 중심 → GPS 안테나. QGC 파라미터 `EKF2_GPS_POS_X/Y/Z` 에도 같은 값을 넣는다. 모르면 `null` |
| `position_ref` | `auto`(기본) — 비행 기록의 `EKF2_GPS_POS` 가 0 이면 보고 위치를 GPS 안테나로, 아니면 FC 로 본다 |

`sar_pass` 는 패스마다 `EKF2_GPS_POS_X/Y/Z` 를 읽어 기록에 남기고, `check` 는 그 값이 0 인지 알려 준다.

알아낸 것 (SITL 궤적의 실제 롤 흔들림 ±3°, 예시 X대역):

| 레버암 (앞, 오른쪽, 아래) | 자세로 인한 안테나 흔들림 | 보정 안 함 | 평균만 뺌 | 자세로 보정 |
|---|---|---|---|---|
| 0, 0.1, 0.2 m | 3.9 mm | −0.7 dB | −0.5 dB | 0.00 dB |
| 0, 0.1, 0.4 m | 7.3 mm | −4.7 dB | −4.2 dB | 0.00 dB |
| 0.1, 0.2, 0.4 m | 7.8 mm | −3.7 dB | −1.8 dB | 0.00 dB |

- 안테나를 GPS 안테나에서 멀리 달수록 커진다. 「평균만 빼기」로는 안 되고, 자세 로그(50 Hz)로 돌려야 한다.
- 기체가 앞으로 숙이면 아래에 단 안테나는 그만큼 앞에 있다. SITL(피치 −22°)에서 보정하지 않으면 영상이 **16 cm 밀려** 맺혔다.
- 빔 방향도 자세 3축으로 돌린다. 기체 고정 안테나는 **앞으로 숙인 만큼 빔이 뒤로 비스듬해진다**.
  - 피치 −5° 면 3.5°, −22°(SIH 시뮬레이터)면 15° — 빔 반폭과 같아 리플렉터가 빔 끝에 걸린다.
  - 실기체 등속 피치를 첫 시험비행 로그에서 확인하고, 크면 안테나를 그만큼 들어 올려 달 것.

### 패스마다 영상 — 노트북에서 자동으로

영상은 **노트북**에서 만든다. Pi 는 비행 중 50 Hz 로 기체를 제어하고 있어, 거기서 계산하면 제어 주기가 흔들린다.

```
Pi   python -m sar_data --flights ~/sar_logs --radar ~/cansar_data            (지금처럼 — 8765)
          │  핫스팟
노트북 python -m sar_data --flights ~/sar_mirror --mirror http://<Pi IP>:8765 \
          --radar-json radar.json --adapter <레이더 어댑터> [--reflectors reflectors.csv] --auto-image --port 8765
화면  연결 관리 → 「드론 데이터 서버」 = http://127.0.0.1:8765
```

1. 노트북 서버가 Pi 에서 **끝난 패스**만 가져온다. 레이더가 파일을 옮길 시간 20 s 를 기다린 뒤, 궤적 · 메타 · 레이더 원시를 받는다.
2. `--auto-image` 면 바로 영상을 만든다. 리플렉터 둘레(촘촘히, 수 초) → 자동 초점 → 선 전체(수십 초) 순서다.
3. 화면 「6 결과 · 내려받기」에서 패스마다 「영상 완료 · 리플렉터 n/m」이 뜬다. 누르면 리플렉터별 판정 · 확대 그림 · 위성 지도 겹침 · 전체 영상이 나온다.
   「다시 만들기」는 화면에 놓은 리플렉터를 함께 보낸다.

| 판정 | 기준 |
|---|---|
| 찍힘 | 리플렉터 자리 밝기가 둘레 바닥보다 15 dB 넘게 밝고, 봉우리가 표시 위치에서 0.75 m 안 |
| 자동 초점 | 리플렉터 4개 이상이 동시에 빔에 → 궤적 3차원 보정. 아니면 이어 붙이기 → 1개 기준 순으로 내려간다 |

- 레이더 형식이 정해지기 전에는 `sar_image.adapters:fmcw_dechirped_npz`(예시 형식)와 `python -m sar_image fakeraw`(가짜 원시)로 전체를 시험할 수 있다.
  실제 형식이 오면 어댑터 함수 하나만 쓴다(`sar_image/adapters.py` 머리말).
- 영상 계산은 32비트 · 여러 코어로 한다(`backproject_fast`). 64비트 기준과의 차이는 −58 dB 이다.
  이 PC 기준 80 × 40 m · 10 cm 격자가 1 코어 22 s, 8 코어 7 s 걸린다(64비트 1 코어는 100 s).
  큰 좌표(UTM 등)를 넘겨도 안에서 영상 중심으로 옮기므로 32비트에서도 깨지지 않는다 — 시험이 지킨다.
- 결과는 `<비행>/images/passNN/` 에 남는다(`image.json` · `cr*.png` · `full.png` · `full_map.png`).
  「이 패스 전부 (ZIP)」에도 같이 들어간다.

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

pi3 의 드론 에이전트(`drone-node.service`, `~/hw/pi/drone/drone_node.py`)는 저장소 어느 브랜치에도 없고 **Pi 에만 있다**.
HW 브랜치의 공통 틀 `pi/common/` 을 상속한다. **그 파일들은 고치지 않는다.**
`sar_pass/agent.py` 가 그 `DroneNode` 를 상속해 `sar_start` / `sar_abort` 만 덧붙인다. 서비스의 실행 명령만 바꾼다.

```bash
# 1) Pi 에 이 저장소의 drone 폴더를 두고, 에이전트가 쓰는 venv 에 설치 (mavsdk-grpc 도 함께 들어간다)
/home/physical/venv/bin/pip install -e '/home/physical/Junho_drone/viz-debugger/drone'

# 2) 실행 명령만 바꾸는 덮어쓰기 파일 — 원래 서비스 파일은 그대로 둔다
sudo systemctl edit drone-node
#   [Service]
#   ExecStart=
#   ExecStart=/home/physical/venv/bin/python3 -u -m sar_pass.agent --node drone.drone_node:DroneNode
#   Environment=SAR_LOG_DIR=/var/lib/hw-node/sar
#   # 레이더가 CAP_ACK 를 쓰면: Environment=SAR_CAP_ACK=/home/physical/CAP_ACK
sudo systemctl restart drone-node && journalctl -u drone-node -f     # "SAR 명령 준비" 가 보이면 끝

# 되돌리기: sudo systemctl revert drone-node && sudo systemctl restart drone-node
```

- `WorkingDirectory` 는 원래 서비스의 것(`~/hw/pi`)을 쓴다. 그래서 `common` · `drone` 패키지가 그대로 import 된다.
- `SAR_LOG_DIR` 는 서비스가 쓸 수 있는 곳이어야 한다. `StateDirectory=hw-node` 가 있으면 `/var/lib/hw-node/…` 가 맞다.
  없으면 `/home/physical/sar_logs` 처럼 홈 아래로 둔다.
- 설정은 모두 환경변수다: `SAR_FC_URL`(기본 `udpin://0.0.0.0:14540`) · `SAR_CAP_PATH` · `SAR_CAP_ACK` · `SAR_LOG_DIR` ·
  `SAR_BASE_LISTEN` · `SAR_CONNECT_TIMEOUT`. 설명은 `sar_pass/agent.py` 머리말에 있다.

동작:
- **Capability**: 원래 명령(`ping` 등) + `sar_start` · `sar_abort` 가 선언된다. 화면의 「패스 시작」 버튼이 열린다.
- **검증**: Acceptance 전에 파라미터 · 중복 실행만 본다. 입출력은 하지 않아 MQTT 가 멎지 않는다.
  잘못된 값은 사유와 함께 `INVALID_ARGUMENT` 로, 이미 도는 중이면 `FAILED_PRECONDITION` 으로 거절한다.
- **실행**: 명령 스레드에서 FC 에 붙는다(처음 한 번만). 진행 단계는 `connecting_fc` 로 보고하고, 임무가 뜨면 `SUCCEEDED {started: 1}` 를 낸다.
  FC 연결에 실패하면 `ABORTED UNAVAILABLE` 이 되고, 다음 시작 때 다시 시도한다.
- **진행 상황**: 노드 자신의 MQTT 연결로 `zoneA/drone/<id>/sar`(retained)에 낸다. 노드의 10 초 요약(`…/status`)에도 `sar: {running, state, capturing}` 가 붙는다.
- **중단**: `sar_abort` 는 언제나 받는다. CAP_ON 을 그 자리에서 먼저 지운 뒤 임무를 멈춘다.
  에이전트가 내려갈 때(`systemctl stop` · 재부팅)도 같은 처리를 한다.

검증한 것:
- `tests/test_agent.py` 는 공통 틀 모양의 가짜 노드로 돈다.
- HW 브랜치의 실제 `pi/common`(BaseNode · PhysicalCommandServer · protobuf)으로도 확인했다.
  가짜 `drone_node` 와 PX4 SITL 로 `sar_start` 명령 → 수락 → 이륙 상태의 기체가 패스 비행 → RTL 까지.

HW 담당과 확인할 것:
- 계약 §0 · §4 의 「보기 전용 · FC 로 0 바이트」가 바뀐다. `drone_link`(14543)의 `tx_bytes` 는 여전히 0 이다.
  제어는 MAVSDK 가 mavlink-router 의 14540 으로 한다.
- 14540 은 한 번에 하나만 쓴다. 에이전트가 붙어 있는 동안 `python -m sar_pass check` / `run` 은 쓰지 말 것.
- 진짜 `drone_node.py` 가 `validate` · `status_extra` · `on_shutdown` 을 덮어쓰고 있어도 괜찮다. 덧붙인 클래스가 `super()` 로 원래 것을 먼저 부른다.

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
| `drone/sar_pass/agent.py` | 드론 에이전트(DroneNode)에 SAR 명령을 덧붙여 실행 — HW 파일 무수정 |
| `drone/sar_pass/status.py` | 화면으로 상태 보고(MQTT) |
| `drone/sar_pass/check.py` | 비행 전 점검(`python -m sar_pass check`) |
| `drone/rtk_relay/base_sender.py` | 노트북: 베이스 RTCM3 → UDP |
| `drone/rtk_relay/fc_injector.py` | Pi: UDP → GPS_RTCM_DATA → FC, 상태 MQTT `…/rtcm` |
| `drone/sar_image/` | 리플렉터 커버리지 · 예상 거리 이력 · 백프로젝션(32비트 고속) · 자동 초점 · 레버암 보정 · 패스 영상 파이프라인 · 가짜 원시 · 레이더 어댑터 규약 |
| `drone/sar_data/` | 비행 데이터 서버 — Pi: 위치 · 레이더 원시 ZIP / 노트북: `--mirror` 로 가져와 패스별 영상(`imaging.py` · `mirror.py`) |
| `drone/sitl/` | PX4 SITL 비행 스크립트 · 흉내 레이더 |
| `drone/fc_watch/` | Pi: FC MAVLink → 상태판 텔레메트리 `…/fcx` (수신 전용) · 시험용 가짜 FC |
| `src/dronedash/` · `src/physical/fcxFeed.ts` · `src/shared/fcxStatus.ts` | 화면: 드론 상태판 |
| `drone/rtk_relay/rtcm3.py` · `inject.py` | RTCM3 프레임 · CRC · 1005 베이스 위치 · 조각내기 |
| `src/physical/rtcmFeed.ts` · `src/shared/rtcmStatus.ts` | 화면: 보정 전달 상태 수신 |
| `src/sar/` | 화면: RTK 노드, SAR 패스 노드, 계획 계산 |
| `src/physical/sarFeed.ts` · `sarCommands.ts` | 화면: 상태 수신, 명령 발행 |
| `src/shared/sarStatus.ts` | 화면: SAR 상태 저장소 |
| `scripts/verify-sar.mjs` | 화면 검사 (`npm run verify:sar`) |
