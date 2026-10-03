# PPS 시각 동기 (Pi 5 ↔ GPS)

레이더 펄스 시각과 드론 궤적 시각을 µs 수준으로 맞춘다. 소프트웨어 동기(`sar_pass timesync`)는 ±수 ms 이고,
4 m/s 에서 1 ms 는 4 mm — X대역 초점 한계(λ/8 ≈ 4 mm)와 같다.

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
