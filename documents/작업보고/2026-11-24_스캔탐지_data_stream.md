# 작업 보고: 스캔 탐지를 data_stream 으로 — 돌며 표시하고, 위치는 data_stream 이, 경로는 가시화가

**날짜**: 2026-11-23 ~ 2026-11-24
**커밋**: 문서 `f4fe132` · `7df09e2` — 구현 `7d13d22`(바탕 층) · `d1d46cd` · `1abac2b`(화면 · 로봇 연결) · `889c97d`(뷰 노드 · 연결 검사) · `0a0bd31` · `3cbbc97`(기본값 data_stream) · `0566a5b` · `2ca2a2b`(방위 부호) · `a0234d4` · `1bca0f0` · `b4957b0`(회신 · 구현 보고 반영) · `851a926`(정지 거리) · `08f80e2`(임무 이력) · `5b427ce`(@ 편 넓은 인식) · `6f1efcc`(`a1e43f8` 대응) — 브랜치 `khw_VZ`
**관련**: 구현 계획 [`../작업프롬프트/작업프롬프트_스캔탐지_data_stream_구현계획_261123.md`](../작업프롬프트/작업프롬프트_스캔탐지_data_stream_구현계획_261123.md) ·
창구 요청 [`../협의/스캔탐지창구_요청_VZ_261123.md`](../협의/스캔탐지창구_요청_VZ_261123.md) ·
data_stream 창구 계획 [`../협의/스캔탐지_창구_계획_261124.md`](../협의/스캔탐지_창구_계획_261124.md) ·
data_stream 구현 보고 [`../협의/스캔탐지_창구_구현보고_261124.md`](../협의/스캔탐지_창구_구현보고_261124.md)
**작성**: 2026-11-24 — 작업 뒤에 커밋 기록 · 계획서 · 코드에서 다시 정리한 보고서
**상태**: **가시화 쪽 구현은 계획서 S0~S11 이 모두 「됨」이다.** 실물 Go1 판을 261124 에 몇 번 돌려 정지 거리 · 거리 믿음 · 한 각도 검출을 고쳤다. 고친 뒤 실물에서 끝까지 다시 돈 기록은 이 저장소에 없다(7절).

> 한 줄 요약 — 「문 쪽으로 이동」·「박스 앞까지 이동」은 별도 탐지기(`:8000`)와 pi7 GO1 의 `scan_mission` 하나에 묶여 있었다.
> 이제 가시화가 `turn 45°` 를 여덟 번 보내며 각도마다 data_stream 에 `/scan/mark` 로 「지금 이 각도」를 알리고, 끝에 data_stream 이 낸
> **위치(방위 · 거리 · 근거)** 로 가시화가 **경로를 계산**해 움직인다. 새 편 셋(`MSN-261123-01~03`, 문 · 박스 · @)을 더했고 옛 셋은 그대로 두었다.

---

## 1절 — 무엇을 정했나 (사용자 결정 2026-11-23)

| # | 결정 |
|---|---|
| 1 | 흐름은 **준비 → 회전 → 산출 요청 → 결과 → 경로 → 이동**. 회전 중 각도마다 탐지를 기다리지 않는다 |
| 2 | data_stream 은 **위치**(방위 · 거리 · 근거)까지, **경로는 가시화**가 계산한다 |
| 3 | 문 편도 도면 · 받침대 자세 추정을 쓰지 않는다 — 박스 편과 같다 |
| 4 | 각도별 판정 화면은 남긴다. 각도마다 대표 이미지 하나 |
| 5 | **개선 전 시나리오는 그대로 남긴다.** 새 흐름은 새 편으로 |
| 6 | @ 편은 문 · 박스 외 임의 물체를 같은 흐름으로 찾는 범용 편 |
| 7 | 회전은 세 편 모두 `scan_mission` 대신 `turn 45°` 여러 번. 그래서 `turn` · `move_forward` 를 선언하고 data_stream 이 영상을 받는 장치면 어느 것이든 |
| 8 | 옛 편과 새 편은 **탐지 방식 설정**(`legacy` / `datastream`)으로 매칭을 가른다 |
| 9 | 문 편 대상은 `demo_door` 하나만 |
| 10 | @ 질의는 LLM 으로 영어로 옮겨 `query` 에, 원문은 `query_ko` 에 |
| 11 | 가시화는 `/scan/*` 명령만 보낸다. 대상 바꾸기는 data_stream 쪽이 한다 |
| 12 | 창구는 data_stream 소스 서버에 붙고, 가시화는 장치의 소스 포트로 부른다 |
| 13 | 탐지 방식 **기본값은 `datastream`** (`3cbbc97`). 「옛 탐지기」를 고를 때만 옛 탐지기 주소 칸이 나타난다 |

계획서는 처음(`f4fe132`)에 data_stream 의 새 탐지기를 전제로 썼다가, data_stream `70da254` 에 지정 클래스 탐지(`targeted` — `demo_door` · `demo_box` · 제로샷)가 들어온 것을 보고 「그 위의 얇은 층」으로 다시 적었다(`7df09e2`, 결정 9~12).

## 2절 — 서버(data_stream)와의 약속

창구는 그 장치 소스의 서버 포트(`go1-001` → `:10003` 등)에 붙는다. 모든 응답 JSON · CORS `*`.

| 메서드 | 경로 | 하는 일 |
|---|---|---|
| POST | `/scan/prepare` | `{scan_id, device, target: door\|box\|object, query, query_ko, steps, step_deg}` — 대상 반영. `loading` → `ready` |
| GET | `/scan/status?scan_id=` | 1초마다. `ready` 때의 `profile_version` 이 그 판의 기준 |
| POST | `/scan/mark` | `{scan_id, rotation_deg}` — 약 0.5초 뒤 원본의 `targeted` 결과 하나를 그 각도에 묶는다. 2초 안에 응답, 못 잡으면 `frame_captured: false` |
| POST | `/scan/finish` | 수집을 닫고 산출 시작 |
| GET | `/scan/result?scan_id=` | `running` → `done` \| `failed`. `frames[]` · `best` · `evidence.cues[]` · `score_basis` |
| GET | `/scan/frame?scan_id=&rotation_deg=&kind=` | `original` · `overlay` · `crop`(found 각도만) JPEG |
| POST | `/scan/cancel` | 정지 버튼 |
| GET | `/health` | `vision.targeted.scan = {busy_scan_id, devices}` |

- **방위**는 스캔 시작 방향 기준 시계 +, −180~180. **거리**는 `distance_valid` 하나로 믿을지 가른다.
- 시간 한도: `prepare` → `ready` 60초 · `mark` 2초 · `finish` → `done` 30초. 넘기면 가시화는 멈추고 움직이지 않는다.
- 결과의 `profile_version` 이 `ready` 때와 다르면 그 결과로 움직이지 않는다.
- 앞 각도의 판정이 다음 각도로 넘어오지 않게 해 달라고 요청했다(`3cbbc97` 에서 요청 문서 §2 · §3-5 보탬). data_stream 은 (a) `mark` 마다 기억 비우기 · (b) 장 단위 값 둘 다 했다고 보고했다.

**오류.** data_stream 구현 보고 §3 의 모양을 따른다: `{error, detail, …}` — `busy` · `bad_state` · `unknown_scan` · `unknown_device` · `wrong_port` · `bad_request`. 판은 서버 전체에 하나이고, 겹치면 409 + `busy_scan_id` 다(가시화가 동의했다). `6f1efcc` 부터 @ 판의 400 `bad_query` 가 더해졌다.

## 3절 — 가시화 쪽에서 만든 것

### 창구 · 상태 · 실행기

| 파일 | 하는 일 |
|---|---|
| `scripts/scan-detect-mock.mjs` | 가짜 창구(`npm run scan:mock`). 처음 11가지 판에서 `no-focal` · `extinguisher` · `door-measured` · `isolated` 가 더해졌다 |
| `src/detect/scan/ScanClient.ts` · `parse.ts` · `types.ts` | 창구 클라이언트(fetch 주입, 사유 코드 `network` · `timeout` · `http` · `shape` · `busy` · `bad_query`) · 응답 모양 검사 |
| `src/detect/scan/scanAddress.ts` | 장치 → 창구 주소. **주소 칸을 따로 두지 않고** 연결 관리 「추론 스트림」 + 하드웨어 카드 포트 묶음(`vision/binding.ts`)을 쓴다 — 계획서 §5 S1 의 `scan.host` · 포트 표 안은 쓰지 않았다 |
| `src/detect/scan/scanStore.ts` | `scan_id` 하나의 상태 · 각도 칸 · 결과. 다른 `scan_id` 응답은 버린다 |
| `src/physical/scanDetectRun.ts` | 순서(순수, 의존성 주입): T-A0 준비 → T-A2 방위 → `mark(0)` · (`turn` → 완료 → `mark`) ×7 · 여덟 번째 `turn` → T-A5 `finish` · `result` |
| `src/physical/scanDetectLink.ts` | 실물 연결. `turn` 은 `issueStepsToEnd`, 노드 seq 6M 대역, data_stream 요청을 명령 기록에(`data_stream.prepare` 등) |
| `src/physical/scanApproach.ts` | `best` → `turn` · `move_forward` · 멈춤 사유. 회전 오차 보정 · 하한(5° · 0.05 m · 10 m)은 `approachPlan.ts` 것을 같이 씀 |
| `src/physical/scanApproachRun.ts` | 이동 계획 상태 · 승인 대기 · 정지 거리 고치기 · 노드 칠하기(`3cbbc97` 에서 떼어 냄) |

### 편 · 매칭 · 화면

| 자리 | 내용 |
|---|---|
| `scenarios/MSN-261123-01~03` (+ `.en.json`) | 문 · 박스 · @. `robotFlow: 'scan-detect'` · `scanTarget` · `detectSource: 'datastream'`. T-A1 을 빼고 T-A0 탐지 준비(`usesFloorPlan()` 이 T-A1 로 도면을 가리므로). 옛 셋에는 `detectSource: "legacy"` |
| `src/scenarios/library.ts` | `scanDetectFlow()` · `scanFlow()`(관문 · 준비 · 이동 전 승인 공통) · `scanTargetOf()`. 옛 `doorScanFlow()` 는 그대로 |
| `src/scenarios/detectSource.ts` · `detect/scan/detectSourceSync.ts` · `DetectSourceSwitch.tsx` | 매처가 설정으로 거른다(호출부 무수정). 게이트웨이 `GET/POST /scan-detect-source` · 기동 값 `SCAN_DETECT_SOURCE`. 연결 관리 「객체 탐지 추론 스트림」 칸 맨 위에서 고르고, 임무 중에는 못 바꾼다 |
| `src/detect/scan/ScanDetectViews.tsx` · `detect/views/DetectViews.tsx` | 노드 상세(준비 · 각도 그림 · 위치 · 근거 · 경로 · 이동 승인)와 팔레트 뷰 노드. 새 노드 종류 없이 `detect-cam` · `detect-reason` 이 새 편에서 갈래 |
| `gen-lab/server/main.py` `POST /generate/name_en` · `src/generate/nameEn.ts` | @ 를 영어 소문자 1~4 낱말로(문법으로 묶음). 엔진이 없으면 503 |
| `StopButton.tsx` · `i18n` | 정지 → `/scan/cancel` · 문구 `sd.*` 한 · 영 |
| `src/record/recorder.ts` 외 (`08f80e2`) | 각도 원본 · 찾은 각도 상자 그림 · 잘라낸 그림을 판 폴더(`scan_rot_<각도>_<종류>.jpg`)에, 판 상태 · 이동 계획을 `progress.json` 에. 이력에서 열면 창구가 아니라 기록 폴더 그림으로, 닫으면 비운다 |

`5b427ce` 로 @ 편이 「장치 하나」 없이도(「의자 앞까지 이동해」) 받게 넓혔다(보조 규칙 `also` · `target.required` · 옛 @ 편은 예시 문장에서 뺌). 같은 커밋의 영상 위 버튼 묶음은 다른 보고서가 다룬다.

## 4절 — 실물 시험 · 회신 반영

| 언제 · 무엇 | 본 것 | 고친 것 |
|---|---|---|
| 261123 실물 GO1 방위 | 왼쪽 90° 명령(`turn −90`)에 MQTT 상태 방위가 +83 → +172(+89) — 반시계 +. `turn` 은 오른쪽 + | `HEADING_TURN_SIGN = −1`(`0566a5b`). SDK ACK 의 `yaw_deg` 는 시계 + 였다 — 가짜 장치 회전 결과에 그 값을 같이 싣는다(`2ca2a2b`) |
| data_stream 회신 (261124) | 409 의 진행 중 판을 `busy_scan_id` 로 · 초점 거리를 모르면 `best.bearing_note`(방위 = 각도 정면) | `a0234d4` · `1bca0f0`. 회신 계획서에 A2 장치 ID(`a2-001`)와 판 하나 제약 동의를 채웠다 |
| data_stream 구현 보고 (261124) | 오류 모양 `{error, detail, stream}` · 409 는 `busy` 일 때만 · Go1 은 `bearing_note` 가 늘 붙음 | `b4957b0` — 사유에 싣고, `bad_state` 는 오류로, `bearing_note` 는 막지 않는 참고값 메모로 |
| 261124 실물 Go1 — 정지 거리 | `stop_distance_max_m` 0.9 m 라 탐지를 해도 대상 가까이 못 갔다 | 새 편 셋 기본 0.2 m. 「이동 경로 산출」(T-B1)에서 바꾸면(0~3 m) 다시 세고, 사람이 눌러야 출발(`851a926`) |
| 261124 실물 Go1 — 거리 · 한 각도 (`scanApproach.ts` 주석) | 13:30 문 판(5.82 m → 5.62 m 전진) · 13:35 소화기 판(4.29 m, 실제 1.5~2 m)에서 UniDepth 가 거리를 1.75~2.5배 부풀린 채 valid 로 왔다. 11:06 박스 판에서 컴퓨터 본체를 78.7점으로 시연 박스라 잡았다 — 한 각도에서만 보였다 | 아래 `a1e43f8` 대응 |

**data_stream `a1e43f8` 대응 (`6f1efcc`).** 코드 주석의 「변경 대응 요청 A · B · C」 갈래다(그 요청서는 이 저장소에 없다).

- **A 거리:** `distance_valid` 만 본다. 거짓이면 값이 있어도 전진하지 않고 `distance_note` 를 T-B1 노드와 알림에 띄운다. 참이면 **거리의 85% 만 믿고**(`SCAN_DISTANCE_TRUST`) 정지 거리를 뺀다 — 바닥선 거리가 실제보다 2~15% 길게 나왔다는 data_stream 대조를 따랐다.
- **B 한 각도:** `best.isolated` 면 계획은 세우되 승인 설정과 상관없이 사람이 그림을 보고 눌러야 출발한다. 각도 칸에 「1각도 / 같이 보인 각도」(`seen_at`)를 보인다.
- **C @ 이름:** `query_ko` 를 늘 보낸다(data_stream 이 아는 낱말이면 그것을 먼저 씀). 번역이 깨지면(소문자 영어 · 공백 · 하이픈만 · 40자 · `or` 없음 · 같은 낱말 되풀이 없음 — 마지막은 가시화가 더함) 보내지 않고 `query: null` 로. 400 `bad_query` 면 사유를 보이고 사람이 영어 이름을 적어 같은 판을 다시 준비한다. 결과의 `query_used` · `query_source` 를 표시한다.

## 5절 — 도중에 잡은 문제

| 문제 | 원인 | 고친 것 |
|---|---|---|
| 회전 오차를 거꾸로 뺄 뻔함 | 부호 기준을 가짜 장치(1)로 두었는데 실물 상태 방위는 반시계 + | `−1`. 다음 커밋에서 가짜 장치 상태 방위도 이미 반시계 + 였음을 확인하고 「가짜는 실물과 반대」라던 주석을 바로잡았다(`2ca2a2b`) |
| `verify:physical-port` 실패 | `types.ts` 주석에 하드웨어 장비 id | 주석에서 뺌(`d1d46cd`) |
| `verify:i18n-no-frozen` 실패 | `ScanDetectViews` 하위 컴포넌트에 `useLang()` 없음 | 추가(`0a0bd31`) |
| `verify:adjust-rewind` 실패 | 노드 상세 · 정지 버튼 묶음이 `nameEn` → `LlmClient` 를 거쳐 `contracts/` 까지 끌어왔다 | `nameEn` 이 `LlmClient` 를 import 하지 않게 · 이동 계획 상태를 `scanApproachRun.ts` 로 뗌(`3cbbc97`) |
| 옛 편 문장을 보는 매칭 검사 넷 | 기본값이 `datastream` 이면 옛 편이 매칭에 서지 않는다 | 그 검사들이 「옛 탐지기」 설정을 밝혀 대조(`3cbbc97`) |
| 임무 이력에서 스캔 판이 「판 없음」 | 각도 그림을 화면이 창구에서 그때그때 받아 그렸을 뿐, 기록 폴더 · `progress.json` 에 없었다 | `08f80e2` (3절) |
| 번역이 깨진 이름 | 「사람」 → `celedar or person orhumanbeingorhumanh`, 「소화기」 → `ionalescrollingtext uebaa uebaa uebaa` | `sendableQuery()` 검사 · `bad_query` 뒤 다시 준비(`6f1efcc`) |

## 6절 — 검사

| 명령 | 보는 것 |
|---|---|
| `npm run verify:scan-detect` | 실행기 순서(창구 도착 시각 기준) · 실패 갈래 · 프레임 없음 · 프로필 바뀜 · 409 · 지난 판 · 경로 계산 · 응답 모양 · `a1e43f8` 대응 |
| `npm run verify:scan-detect-link` | 승인 · 시작 → 준비(방위) · 추론 스트림 포트 · `turn 45°` ×8(완료 뒤 `mark`) · 산출 → 회전 오차 8° 를 뺀 경로 · 직진 · 정지. 대조: 찾지 못함 · 판 도중 정지 · 옛 편. 정지 거리 바꾸기 · 문 예시(전진 안 함 · 알림) · 소화기 예시(1.686 × 0.85 − 0.2) · `isolated` 누르기 전/후 · `bad_query` → 적은 이름으로 다시 준비 · 「↻ 처음부터」가 @ 를 지키는지 |
| `npm run verify:scan-record` | 각도 원본 · 상자 그림 · 잘라낸 그림 · 판 상태가 남는지, 이력에서 연 그림이 기록 폴더를 가리키는지, 닫으면 비는지. 대조: 못 받은 각도 · 찾지 못한 각도의 그림을 짓지 않는다 |

앞의 둘은 돌연변이(예: `turn` 완료를 안 기다림)로 검사가 실패를 잡는지 확인했다고 계획서 · 커밋에 적혀 있다. 매칭 쪽은 `verify-script-{door,box,at-move,library,...}` 의 기대표에 새 편 셋을 넣었다. 각 검사의 통과 건수는 커밋에 남아 있지 않다.

## 7절 — 쓰는 법과 한계 / 남은 것

- **쓰는 법:** 연결 관리 「객체 탐지 추론 스트림」에서 탐지 방식(기본 data_stream)을 확인하고, 그 장치의 추론 스트림 포트가 data_stream 소스 서버를 가리키게 한다. 「문 쪽으로 가」 등을 말하면 새 편이 선다. 새 편을 더한 뒤에는 게이트웨이를 다시 띄워야 승인이 선다.
- **data_stream 없이 시험:** `npm run scan:mock -- --mode <판>` 을 띄우고 포트 줄에 그 주소를 적는다.
- **옛 흐름으로 돌리기:** 연결 관리에서 「옛 탐지기」. 옛 편 셋과 `scan_mission` 흐름은 손대지 않았다.
- **방위는 참고값.** Go1 은 어안 보정이 없어 `bearing_note` 가 늘 붙는다. 초점 거리를 모르는 카메라는 방위가 그 각도 정면이다.
- **판은 서버 전체에 하나**이고, 판 동안 같은 비전 프로세스의 다른 소스도 판 대상만 찾는다(data_stream 보고 §6, 동의함).

**남은 것**

| 항목 | 내용 |
|---|---|
| 실물 끝까지 다시 돌기 | `6f1efcc` 뒤 실물 Go1 으로 문 · 박스 · @ 를 끝까지 돌려 맞게 섰는지의 기록이 이 저장소에 없다. 확인 필요 |
| 85% 믿음 비율 · 정지 거리 0.2 m | 시연 박스 대조와 261124 몇 판에서 정한 값이다. 다른 장면 · 대상에서 맞는지 모른다 |
| `mark` 여유 | data_stream 재생 시험에서 문 판 `mark` 응답이 최대 1.79초(한도 2초). 실물에서 각도를 놓치면 한도를 상의한다 |
| 두 번째 Go1 | data_stream `b73fc65`(261124)에서 pi1 이 Go1(robot2)에서 RoboMaster EP(`ep-001`)로 바뀌어 스캔 창구 장치 목록에서 `go1-002` 가 빠졌다. 지금 스캔 판을 돌릴 Go1 은 `go1-001`(:10003) 하나다 |
| Go1 아닌 장치 | `a2` 는 `fov_x_deg` 가 비어 방위가 각도 정면이다. 문 · 박스 하한은 Go1 카메라 기준 `provisional` |
| 「변경 대응 요청 A · B · C」 문서 | 코드 주석 · 가짜 창구가 가리키는 요청서가 `documents/협의/` 에 없다. 보낸 곳에서 가져와 남길지 정해야 한다 |
