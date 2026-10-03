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

## 남은 일 (2026-10-03 기준)

- 레이더 팀: `radar.json` 사양 · 원시 형식 + 샘플 → 어댑터(`sar_image/adapters.py` 규약) · CAP_ACK · PPS 여부
- 사용자가 줄 팀 백프로젝션 · 자동 초점 코드 → `--former` · `--focuser` 로 꽂기 (README 「영상 코드 꽂기」)
- HW 담당과 협의 후 Pi 에 `deploy/pi/install.sh --with-agent` · 실제 Pi 에서 설치 확인
- 레버암 실측 · QGC `EKF2_GPS_POS_*` · FC ↔ Pi 연결이 USB 인지 UART 인지 확인(.ulg 받는 속도)
- 현장: 수레 시험 → 호버(간섭 · 진동) → 저고도 → 본 비행. 첫 로그로 바람 기울기 계수(`TILT_PER_MPS`) · 선 복귀 게인(`CROSS_KP`) 보정
