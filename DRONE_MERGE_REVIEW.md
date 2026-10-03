# 드론 파트 → khw_VZ 전달 (2차)

1차(Junho_drone `1d7cfcc`)는 컴공 팀이 `khw_VZ` 에 합쳐 주셨습니다(`cb6c805`) — 감사합니다.
그 뒤 컴공 쪽에서 고친 것(상태판 · RTK · SAR 패스의 `deviceId` · `readOnly`, 드론 상세보기 탭, 3D 화면)은
**Junho_drone 에 그대로 받아 두었습니다**(`a841cef`). 그래서 지금 Junho_drone 의 viz-debugger 는
**khw_VZ `1426932` + 드론 파트의 새 작업** 입니다.

## 부탁드리는 것

아래 「새로 바뀐 것」을 보시고 괜찮으면 khw_VZ 에 얹어 주세요. 방법은 맨 아래에 있습니다.

## 새로 바뀐 것 (khw_VZ `1426932` 대비)

화면 코드는 **드론 파트 파일 위주**입니다. 컴공 쪽 공용 파일은 세 개이고 모두 덧붙임입니다:
`src/i18n/ko.ts` · `en.ts` (+33 줄씩, 새 문구 키) · `src/physical/PhysicalClient.ts` (+9 줄, 레이더 상태 토픽 구독 — 1차의 `/rtcm` 과 같은 자리 · 같은 모양).
새 파일은 `src/physical/radarFeed.ts` · `src/shared/radarStatus.ts` 둘입니다.
정확한 목록은 이 명령으로 보입니다:

```bash
git fetch origin
git diff --stat 1426932 origin/Junho_drone -- viz-debugger ':!viz-debugger/drone'
```

| 무엇 | 화면에서 |
|---|---|
| 비행 기록에 재처리 조건 저장 | 패스 시작 때 리플렉터 좌표 · 안테나 설정(radar.json)을 `sar_start` 파라미터로 함께 보냄 → 드론이 비행 폴더에 코드 버전과 같이 저장 |
| 리플렉터 자리 측량 | 「드론 위치를 리플렉터로」 버튼 — RTK Fixed 때 최근 3 초 평균(cm 단위) |
| 비행 컴퓨터(Pi) 상태 | 상태판에 「Pi」 칩 — 온도 · 스로틀링 · 전압 · 디스크 (`fcx.companion`) |
| 패스 지오펜스 | 계획 「비행 조건」에 켜고 끄기(기본 켬) — 드론이 패스 구역 울타리를 올렸다가 원래대로 되돌림 |
| 현장용 지도 미리 받기 | 지도에 「이 구역 지도 미리 받기」 — 노트북 데이터 서버에 타일 저장(인터넷 없는 현장) |
| 레이더 상태 | 상태판 · SAR 점검에 레이더 칸 — 새 토픽 `zoneA/drone/<id>/radar` (레이더 팀이 낼 것, `viz-debugger/drone/RADAR_INTERFACE.md`) |
| SAR 간단 모드 | SAR 패스 화면 위 「간단 / 자세히」 — 현장에서 지금 할 일과 큰 버튼만 |

드론 쪽(`viz-debugger/drone/`)은 비행 안전 점검(오프보드 끊김 동작) · GPS 간섭 지상 시험 · 안테나 장착 각도 추천 · PPS 시각 동기 ·
GitHub 자동 검사(`.github/workflows/drone.yml`, Junho_drone 푸시 때만) 등이 늘었습니다. 화면 빌드와는 상관없습니다.

## 지킨 규칙

- 문구는 전부 i18n 키 · 컴포넌트마다 `useLang()` · 토픽 문자열은 `src/physical` 안 · 명령은 commandTracker — `verify:*` 통과
- 새 npm 의존성 없음
- 컴공이 넣은 `deviceId` · `readOnly` 는 그대로 살렸습니다(새 기능도 `readOnly` 면 명령을 안 냅니다)
- verify: 못 넘는 것은 이 PC 환경 탓인 `stt-language` · `service-words` · `gen-prompt` 셋뿐(드론과 무관)

## 확인할 점

- **새 MQTT 토픽** `zoneA/drone/<id>/radar` (retained, 레이더 쪽이 냄). 1차의 `/sar` · `/rtcm` · `/fcx` 와 같은 방식입니다.
- **sar_start 파라미터가 늘었습니다** — 리플렉터 · 안테나를 숫자 키(`cr_n`, `cr0_lat` …, `ant_*`)로 펼쳐 싣습니다. 봉투 형식은 그대로입니다.
- **지도 타일**: 노트북 데이터 서버의 타일 캐시를 쓰려면 연결 관리 「드론 지도」 주소를 바꿉니다. 기본값은 그대로(Esri · OSM)입니다.

## 얹는 방법

khw_VZ 가 그사이 더 나아갔어도 되도록 **기준점(1426932)을 정해서** 차이를 만듭니다.
(`git diff origin/khw_VZ origin/Junho_drone` 처럼 지금 khw_VZ 와 바로 견주면, 그 뒤 컴공이 넣은 것을 되돌리는 patch 가 되니 쓰지 마세요.)

```bash
git fetch origin
git checkout -b drone-merge-2 origin/khw_VZ
git diff 1426932 origin/Junho_drone -- viz-debugger | git apply --3way --index
cd viz-debugger && npm ci && npx tsc -p . --noEmit && npm run verify:sar
git commit -m "드론 파트 2차 — Junho_drone 의 viz-debugger 변경 (기준 1426932)"
```

겹치면 i18n 끝부분 정도일 겁니다 — 둘 다 남기면 됩니다. 드론 파트가 맞춰서 다시 드려도 됩니다.

## 직접 보기

```bash
git checkout Junho_drone
cd viz-debugger && npm ci && npm run dev        # 캔버스에 「드론 상태판」 · 「SAR 패스 비행」 · 「RTK 상태」
cd drone && python -m sar_pass sim --mqtt 127.0.0.1:1883    # 드론 없이 시뮬레이터 비행이 상태를 냄
```

## 아직 확인 못 한 것

실기체 · 실제 레이더 · 실제 Pi 설치는 아직입니다. 지금까지는 PX4 SITL(시뮬레이터) · 가짜 레이더 데이터로 확인했습니다.

문의: 드론 파트 (Junho)
