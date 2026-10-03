# 드론 파트 합치기 검토 (Junho_drone → khw_VZ)

드론 파트가 viz-debugger 에 SAR 드론 기능을 더했습니다: **드론 상태판 · SAR 패스 비행 · RTK 상태 · SAR 영상**.
기존 코드는 지우지 않았고, 컴공 쪽 공용 파일은 목록에 항목을 더하는 정도로만 고쳤습니다.
보시고 합쳐도 괜찮은지 알려 주세요.

## 부탁드리는 것

1. 아래 「컴공 쪽 공용 파일」 9개 변경이 괜찮은지
2. 괜찮으면 `khw_VZ` 로 합칠지(방법은 아래), 아니면 드론 파트가 계속 따로 둘지
3. 바깥 지도 타일 요청 · 새 MQTT 토픽 · 새 명령 두 개에 대한 의견(「확인할 점」)

## 한눈에

| 항목 | 값 |
|---|---|
| 기준 | `khw_VZ` 51455e8 (2026-10-02, 지금 최신과 같음) |
| 화면 코드 (`viz-debugger/drone/` 제외) | 30개 파일 — 새 파일 21 · 고친 파일 9 |
| 지운 줄 | 7줄 — 목록(타입 · 배열)에 항목을 더하느라 바뀐 줄뿐 |
| khw_VZ 최신에 적용 | 충돌 없음 (`git apply --check` 로 확인) |
| verify 스크립트 | 100 / 104 통과 — 못 넘은 4개는 아래 「지킨 규칙」 참고 |
| 드론 파이썬 시험 | 83개 통과 (`viz-debugger/drone`) |

## 컴공 쪽 공용 파일 (9개, 전부 덧붙임)

| 파일 | + / − | 무엇을 |
|---|---|---|
| `src/tabs/viewNodes.tsx` | +30 / 0 | 보기 노드 3개 등록: `drone-rtk` · `sar-pass` · `drone-dash` (NodeGate 로 감쌈) |
| `src/scenarios/axes.ts` | +4 / −2 | 위 3개를 노드 종류 목록에 추가 (대본 축 표에는 없음 — 드론이 미는 값) |
| `scripts/verify-view-nodes.mjs` | +3 / −2 | 모든 편 팔레트 노드 목록에 3개 추가 |
| `src/physical/PhysicalClient.ts` | +28 / 0 | 토픽 3개 구독 `zoneA/+/+/sar` · `…/rtcm` · `…/fcx`, 장비 상태 표로 가기 전에 드론 저장소로 보냄 |
| `src/physical/encode.ts` | +3 / −1 | 명령 이름 `sar_start` · `sar_abort` 추가 |
| `src/shared/connections.ts` | +26 / −1 | 연결 대상 2개: `drone-data`(드론 데이터 서버) · `drone-map`(지도 타일 주소) |
| `src/i18n/ko.ts` · `en.ts` | +470 / 0 씩 | 새 문구 키(`sar.*` · `dash.*` · `rtk.*` · `img.*` · `pi.*` · `plan.*` …). 기존 키는 그대로 |
| `package.json` | +3 / −1 | 스크립트 `verify:sar` · `test:drone` |

새 파일: `src/sar/` · `src/dronedash/` · `src/physical/{sar,rtcm,fcx}Feed.ts` · `src/physical/sarCommands.ts` ·
`src/shared/{sar,rtcm,fcx}Status.ts` · `scripts/verify-sar.mjs`, 그리고 드론 쪽 `viz-debugger/drone/`(파이썬 · 설치 스크립트 · 문서).

변경 전체 보기:
```bash
git fetch origin
git diff --stat origin/khw_VZ origin/Junho_drone -- viz-debugger ':!viz-debugger/drone'
```

## 지킨 규칙

- 문구는 전부 i18n 키(소스에 한국어 글자 없음, 컴포넌트마다 `useLang()`) — `verify:no-raw-korean` · `verify:i18n-no-frozen` 통과
- 토픽 문자열은 `src/physical` 안에만, 명령은 commandTracker 로만 — `verify:command-through-tracker` · `verify:dep-rules` 통과
- 명령 버튼은 장비가 Capability 에 `sar_start` 를 선언했을 때만 열림(선언 안 한 장비에는 보내지 않음)
- 드론 쪽 식(빔 계산 · 품질 기준 · 상수)과 화면이 같은지 `verify:sar` 가 검사
- 못 넘은 4개 `verify:stt-port` · `stt-language` · `service-words` · `gen-prompt` 는 드론 파일과 무관한 검사입니다.
  이 PC 에 `python` 명령 · STT 서비스 기록이 없고, STT 포트 파일 줄바꿈 검사가 걸립니다.

## 확인할 점

- **바깥 요청**: 위성 지도 타일을 브라우저가 Esri World Imagery · OpenStreetMap 에서 받습니다.
  연결 관리 「드론 지도」에서 주소를 바꾸거나 지도 「없음」으로 끌 수 있습니다(인터넷 없는 현장 · 오프라인 타일 서버 대비).
- **새 MQTT 토픽**: `zoneA/drone/<id>/sar` · `/rtcm` · `/fcx` (모두 retained, 드론 쪽이 냄). 백엔드 · 브로커 ACL 에 영향이 있는지.
- **새 명령**: `sar_start` · `sar_abort` (기존 PhysicalCommandEnvelope 그대로). 드론 에이전트가 「보기 전용」에서 비행 명령을
  받는 쪽으로 바뀌므로 HW 담당과도 협의합니다. 에이전트 쪽은 HW 파일을 고치지 않고 systemd 덮어쓰기로 붙였습니다.
- **새 HTTP 서버**: Pi 의 드론 데이터 서버(:8765, 읽기 전용)를 화면이 직접 부릅니다. 게이트웨이를 거치지 않습니다.

## 직접 보기

```bash
git fetch origin
git checkout Junho_drone
cd viz-debugger && npm ci && npm run dev
# 캔버스 팔레트에서 「드론 상태판」 · 「SAR 패스 비행」 · 「RTK 상태」 노드
npm run verify:sar          # 드론 쪽 검사만
```

드론 없이 화면을 움직여 보려면: `cd viz-debugger/drone && python -m sar_pass sim --mqtt 127.0.0.1:1883`
(시뮬레이터 비행이 MQTT 로 상태를 냅니다).

스크린샷: [`screenshots/`](screenshots/) — 상태판 [18](screenshots/18_상태판_큰지도_빔_바람.png) ·
비행 계획 [22](screenshots/22_계획_바람_배터리.png) · 패스 재생 [19](screenshots/19_패스_자세히보기_재생.png) ·
SAR 영상 [17](screenshots/17_SAR영상_패스별.png) · 비행 데이터 [23](screenshots/23_비행데이터_패스카드.png)

## 합치는 방법 (괜찮다고 하시면)

Junho_drone 은 viz-debugger 폴더를 통째로 올린 브랜치라 khw_VZ 와 이력이 따로입니다.
그래서 `git merge` 대신 **viz-debugger 차이만** khw_VZ 에 얹는 방식이 깔끔합니다. 2026-10-03 기준 khw_VZ 최신에 충돌 없이 적용됩니다.

```bash
git fetch origin
git checkout -b drone-merge origin/khw_VZ
git diff origin/khw_VZ origin/Junho_drone -- viz-debugger | git apply --index
cd viz-debugger && npm ci && npm run verify:sar      # 필요하면 전체 verify
git commit -m "드론 파트(SAR 드론) 합치기 — Junho_drone 의 viz-debugger 변경"
# 확인 뒤 khw_VZ 에 반영 (PR 이든 직접이든 팀 방식대로)
```

khw_VZ 가 그사이 더 나아갔으면 `i18n/ko.ts` · `en.ts` · `viewNodes.tsx` · `connections.ts` 끝부분에서만 겹칠 수 있습니다 —
둘 다 남기면 됩니다. 드론 파트가 맞춰서 다시 드려도 됩니다.

문의: 드론 파트 (Junho)
