# Junho_drone — 드론 파트 (SAR 드론) 작업 안내

이 브랜치는 팀 저장소 `khw18033/Physical-Project-mk2` 의 **드론 파트 담당(Junho)** 브랜치다.
컴공 팀의 화면 `viz-debugger`(React + Vite + TS)에 드론 · SAR 기능을 더했고, 드론 쪽 파이썬은 `viz-debugger/drone/` 에 있다.
사용자는 한국어로 말한다 — 답도 한국어로, 처음 보는 사람도 알기 쉽게.

## 꼭 지킬 것

- **이 브랜치(`Junho_drone`)만 바꾼다.** `khw_VZ`(컴공) · `HW` · `main` 등 다른 브랜치는 읽기만 한다(`git show origin/HW:…`, `git archive`). 절대 커밋 · 푸시 · 체크아웃 변경을 하지 않는다.
- 푸시는 사용자가 직접 한다. 하라고 할 때만.
- Pi 의 HW 파일(`~/hw/pi/…`, `drone-node.service`)은 고치지 않는다 — 덮어쓰기(drop-in)와 상속으로만 붙인다(`sar_pass/agent.py`, `deploy/pi/`).
- 검증된 조각마다 바로 커밋한다(세션이 자주 끊긴다). 오래 도는 시험 서버는 `setsid nohup … < /dev/null &` 로.
- 사용자는 드론 · SAR 개선을 **매번 묻지 말고 알아서** 진행하길 원한다. 화면은 초보자도 쓰기 쉽게, 데이터 저장은 버튼 하나로.

## 하드웨어 · 구성

Holybro X500 V2 + H743 FC(PX4) · QGroundControl · Raspberry Pi 5(FC TELEM 에 연결, mavlink-router: MAVSDK 14540 · TCP 5760) ·
지상국 노트북 ↔ Pi 는 핫스팟 WiFi · RTK 베이스 MicoAir M-RTK(USB → 노트북 → UDP 14660 → Pi → GPS_RTCM_DATA → FC) ·
레이더(cansar)는 `/home/physical/CAP_ON` 파일로 캡처를 켜고 끈다(CAP_ACK 로 확인).

SAR 비행 규칙: 고도 20 m 일정 · 직선 60 m 이상을 3~5 m/s 등속(가감속은 구간 밖) · 기수는 진행 방향 고정 ·
같은 선 같은 방향 2회 이상 · 패스 간격 10 s 이상 · CAP_ON 은 등속 진입 때 만들고 감속 전 · 중단 · RTL · 예외 때 반드시 지운다.

## 구조

| 위치 | 내용 |
|---|---|
| `viz-debugger/src/sar/` · `src/dronedash/` · `src/physical/sar*` `rtcm*` `fcx*` | 화면: SAR 패스 · RTK · 드론 상태판 · 위성 지도 · 영상 보기 |
| `viz-debugger/drone/sar_pass/` | 패스 비행(MAVSDK) · 캡처 · 판정 · 에이전트 연동 · 수레 시험 · .ulg 회수 |
| `viz-debugger/drone/rtk_relay/` · `fc_watch/` | RTK 보정 전달 · 상태판 텔레메트리 |
| `viz-debugger/drone/sar_data/` · `sar_image/` | 데이터 서버 · 노트북 미러 · SAR 영상 파이프라인(백프로젝션 · 자동 초점 · 레버암) |
| `viz-debugger/drone/deploy/` | Pi 설치(`install.sh`) · 노트북 실행(`sar-laptop.bat`) |
| `viz-debugger/drone/README.md` · `FIELD_CHECKLIST.md` | 자세한 설명 · 현장 체크리스트 |

## 새 컴퓨터에서 준비

```bash
git clone https://github.com/khw18033/Physical-Project-mk2.git && cd Physical-Project-mk2
git checkout Junho_drone
# 전체 앱을 띄우려면 컴공 쪽 옆 폴더가 필요하다 — khw_VZ 에서 **읽기만** 해서 꺼낸다(커밋하지 않는다)
git archive origin/khw_VZ contracts web-dashboard places equipment door_example gen-lab stt-lab | tar -x
printf '/contracts/\n/web-dashboard/\n/places/\n/equipment/\n/door_example/\n/gen-lab/\n/stt-lab/\n' >> .git/info/exclude
# 화면 (Node 22)
cd viz-debugger && npm ci && npm run dev          # http://localhost:5174
# 드론 쪽 (Python 3.12)
cd drone && python -m venv .venv && .venv/bin/pip install -e ".[test,image,base]" && .venv/bin/python -m pytest -q
```

## 고칠 때

- 화면 규칙은 `npm run verify:*` 스크립트(100개 남짓)가 지킨다: 문구는 `src/i18n/ko.ts` · `en.ts` 키로(소스에 한국어 글자 금지),
  컴포넌트마다 `useLang()`, 토픽 문자열은 `src/physical` 안에만, 명령은 commandTracker 로만. SAR 쪽은 `npm run verify:sar`
  (드론 Python 상수 · 빔 계산과 화면이 같은지 검사). 환경 탓으로 원래 실패하는 것: `verify:stt-port` · `stt-language` · `service-words` · `gen-prompt`.
- 줄바꿈: 저장소는 `.gitattributes` 를 따른다. 원래 CRLF 인 파일을 LF 로 통째로 바꾸지 않는다.
- 드론 쪽 시험: `cd viz-debugger/drone && .venv/bin/python -m pytest -q`. 실제 비행 논리는 PX4 SITL(`sitl/fly_sitl.py`, README 「PX4 SITL 로 시험」)로 확인했다.

## 지금까지 정한 것 (2026-10-04)

- 통신: Pi ↔ 지상국 노트북은 **휴대폰 핫스팟 WiFi, 2.4 GHz 고정**(레이더가 5.8 GHz — 5.65~5.95 GHz WiFi 면 패스 시작을 막는다).
  시리얼 텔레메트리는 SAR 데이터를 못 보내서 안 쓴다. MQTT 브로커는 노트북(keepalive 10 s) — 끊기면 찍던 패스만 마치고 RTL.
- 레이더: SDR Zynq-7020 + AD9361, 5.8 GHz, Pi 와 기가비트 이더넷. PPS 없음 → `install.sh --with-gpstime` + 리플렉터로 시각 보정.
- RTK: 베이스 MicoAir M-RTK(노트북 USB), 드론 MicoAir M-RTK Air F9P. 이동 기준선(F9P 하나 더)은 데이터가 필요하다고 할 때만.
- 처리: 무거운 영상 처리는 **연구실 GPU 서버**(RTX A6000)에서. 노트북이 SSH 터널(`deploy/laptop/sar-tunnel.*`)을 열고
  서버는 `deploy/server/sar-server.sh`(Pi → 노트북 → 서버 3단 미러). 노트북만으로도 영상은 나온다(인터넷 끊김 대비).
- 데이터 서버 포트 8766(Pi · 노트북), 서버 8768, 터널 18766(-R) · 8767(-L). 8765 는 컴공 백엔드라 피한다.
- 리플렉터는 지금은 보정 · 검증용, 최종 목표는 리플렉터 없이 영상(데이터 기반 자동 초점). 
- mm 변위(반복 패스 간섭, `sar_image/displacement.py`): **자동 초점 전 위상**으로 잰다(자동 초점은 패스마다 위상 기준이 달라 6~10 mm 틀림 —
  시험으로 확인). 안 움직인 리플렉터 셋 이상으로 평면 보정. 실험은 리플렉터 4개 이상 · 하나만 움직인다.
- 컴공 쪽 화면 실행 방식(`npm run dev`, package.json · dev-all · vite 설정)은 khw_VZ 와 똑같다. 2차 전달 기준은 khw_VZ `1426932`.
- 논문 후보: ① 리플렉터로 검증한 리플렉터 없는 자동 초점 ② PPS 없는 시각 동기 ③ 드론 반복 패스 mm 변위.

## 남은 일 (2026-10-04 기준)

- **레이더 팀 코드(10/4 받기로 함)**: 시각 기준(Pi 시계?) · 파일에 시각이 찍히나 · 표본 빠짐 처리 · IQ 형식 확인 →
  어댑터(`sar_image/sdr.py` 가 제안 형식) · CAP_ACK 경로 · 샘플로 시험
- **사용자의 백프로젝션 · 자동 초점 코드(GPU)** → `--former` · `--focuser` 로 꽂기 (README 「영상 코드 꽂기」). 리플렉터 없는 방식이면
  리플렉터 보정 영상과 비교하는 기능을 만든다(논문 ①)
- 컴공이 Pi 설치를 해 주기로 함: `deploy/pi/install.sh --with-gpstime` (`--with-agent` 는 HW 담당과 협의 후). `/etc/sar-drone.env` 의
  SAR_MQTT(노트북 IP 고정) · SAR_SDR_HOST · SAR_CAP_ACK · SAR_RADAR_DIR
- 레버암 실측 · QGC `EKF2_GPS_POS_*` · FC ↔ Pi 연결이 USB 인지 UART 인지(.ulg 속도)
- 현장: 수레 시험 → 호버(간섭 · 진동) → 저고도 → 본 비행. 첫 로그로 `TILT_PER_MPS` · `CROSS_KP` · `CROSS_KP_FAR` 보정
- 다음 후보: 리플렉터 정밀 분석 판(IRF · PSLR · ISLR) · 품질 지표 자동 표(논문용) · 서브어퍼처 보기 · 오차 예산표
- QGC 는 계속 같이 쓴다(펌웨어 · 캘리브레이션 · 페일세이프 · 비상). 우리 화면은 SAR 임무 · 캡처 · 데이터
