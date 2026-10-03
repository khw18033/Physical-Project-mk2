# PPS 시각 동기 (Pi 5 ↔ GPS)

레이더 펄스 시각과 드론 궤적 시각을 µs 수준으로 맞춘다. 소프트웨어 동기(`sar_pass timesync`)는 ±수 ms 이고,
4 m/s 에서 1 ms 는 4 mm — X대역 초점 한계(λ/8 ≈ 4 mm)와 같다.

## 우리 모듈(MicoAir M-RTK Air F9P)에는 PPS 핀이 없다

설명서 기준 커넥터는 6 핀(GND · VCC · RX1 · TX1 · SCL · SDA, FC 연결)과 4 핀(GND · VCC · TX2 · RX2, 보정 수신)뿐이고
PPS 는 밖으로 나와 있지 않다(안의 u-blox ZED-F9P 에는 TIMEPULSE 가 있지만 연결 안 됨). 그래서 셋 중 하나:

| 방법 | 어떻게 | 장단점 |
|---|---|---|
| **A. 시각용 GPS 를 하나 더 (권장)** | PPS 핀이 있는 작은 GNSS 모듈(u-blox M8/M9 계열 등, 3.3 V PPS)을 Pi 에 직접 — UART(NMEA) + PPS 를 GPIO18 로. 안테나는 위가 트인 곳 | 납땜 없음 · RTK 와 독립 · 수만 원. Pi 가 FC 없이도 시각을 안다. 무게 · 자리 조금 |
| B. F9P 의 TIMEPULSE 를 끌어내기 | 모듈을 열어 ZED-F9P 의 TIMEPULSE 핀(또는 그 선이 지나는 패드)에 가는 선을 납땜 | 부품 추가 없음. 미세 납땜 · 보증 · 진동에 끊길 위험 |
| C. PPS 없이 | 지금처럼 FC 의 GPS 시각(MAVLink) + 리플렉터로 레이더 시각 오프셋 추정 | 할 일 없음. 시각이 수 ms 흔들려 5.8 GHz 초점 한계(6.5 mm ≈ 1.6 ms)에 걸릴 수 있다 |

A 를 쓰면 chrony 설정은 `chrony-sar-gps.conf`(이 폴더)로 바꾼다 — FC 시각 대신 시각용 GPS 의 NMEA 로 「몇 초인지」, 그 PPS 로 「순간」.
SDR 보드에 PPS 입력이 있으면 같은 PPS 선을 나눠 SDR 에도 준다(두 곳에 주면 작은 버퍼를 하나 둔다).

## 배선 (한 가닥 + 접지)

| GPS 모듈 | Pi 5 |
|---|---|
| PPS (Holybro M9N/F9P 는 GPS 커넥터의 PPS 핀 · 3.3 V) | GPIO18 (핀 12) |
| GND | GND (핀 14) |

PPS 전압이 3.3 V 인지 먼저 잰다(5 V 면 분압). 선은 짧게, 모터 · ESC 선과 떨어뜨린다.

## 설치

```bash
sudo ./install.sh --with-pps        # chrony 설정 · sar-chrony 서비스 · /boot/firmware/config.txt 에 dtoverlay
sudo reboot
chronyc sources -v                  # PPS 줄 앞에 '*' 이면 PPS 로 맞추는 중
sudo ppstest /dev/pps0              # (선택) 1 초마다 펄스가 오는지
```

`config.txt` 에 넣는 줄: `dtoverlay=pps-gpio,gpiopin=18` (원본은 `config.txt.sar-backup` 으로 남긴다).

## 레이더 팀에게

Pi 시계가 GPS 에 맞으면 cansar 가 `time.time()` 으로 찍는 시각이 곧 GPS(UTC) 시각이다. 펄스마다 시각을 찍어 달라고 하고,
가능하면 레이더 보드도 같은 PPS 를 받게 한다.
