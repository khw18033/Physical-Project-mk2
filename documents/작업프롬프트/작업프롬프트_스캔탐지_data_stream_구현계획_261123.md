# 스캔 탐지를 data_stream 으로 — 가시화 쪽 구현 계획

> 작성 2026-11-23 · 대상: `viz-debugger` (가시화)
> data_stream 창구 명세: [`../협의/스캔탐지창구_요청_VZ_261123.md`](../협의/스캔탐지창구_요청_VZ_261123.md)
> 상태: **계획.** 구현하지 않았다. 창구는 data_stream 소스 서버에 붙고 대상 바꾸기도 data_stream 쪽이 한다(결정 9~12). 남은 상의는 요청 문서 §8-1.
> data_stream 기준: `data_stream` 브랜치 `70da254` (2026-11-23) — 지정 클래스 탐지(`targeted`)가 들어온 판. 무엇이 있고 없는지는 요청 문서 §0-1.

### data_stream 쪽에서 바뀐 것 (2026-11-23, `6013c10` ~ `70da254`)

- 옛 탐지기의 문 · 박스 판정이 `targeted` 대상 **`demo_door`**(main 문 근거 그대로) · **`demo_box`**(Box_Detection v9)로 옮겨졌다. 임의 물체는 **직접 입력(제로샷)** 대상으로 된다. 그래서 창구는 새 모델이 아니라 `targeted` live 결과를 **각도별로 묶고 모으는 얇은 층**이면 된다.
- 결과는 `GET /vision/frame?model=targeted&image=0`(소스 포트, CORS `*`)과 Redis `vision_stream:<소스>:targeted` 로 이미 나온다. 검출마다 `assess{score, suspect, cards}` · `dist{value, space, source}`, 판에 `provisional` · `profile.version`.
- **없는 것:** 밖에서 대상을 고르는 길(지금은 런처의 `profile.json` 파일 감시뿐, `/control/profile` 은 서버에 없음) · `mark` 각도 묶음 · 8방향 요약(data_stream 계획이 「옮기지 않는다」고 적음) · 스캔 시작 기준 방위(`demo_box` 의 `box_bearing` 만, `rotation_deg` 0 · 0~360) · 장치 ID → 소스 표(`go1-001` 없음).
- 근거 카드 문구가 **영어로만** 나온다(`70da254`). 대상 이름도 영어 모델 문구로 바로 들어간다 → @ 질의는 영어로 보내야 한다(결정 10).

## 0. 정한 것 (사용자 2026-11-23)

| # | 결정 |
|---|---|
| 1 | 흐름은 **준비 → 회전 → 산출 요청 → 결과 → 경로 → 이동**. 회전 중 각도마다 탐지를 기다리지 않는다. |
| 2 | data_stream 은 **위치**(방위 · 거리 · 근거)까지, **경로는 가시화**가 계산한다. |
| 3 | 문 편도 **도면 · 받침대 자세 추정을 쓰지 않는다** — 박스 편과 같다. |
| 4 | 각도별 판정 화면은 남긴다. **각도마다 대표 이미지 하나**(그 각도에서 잡은 프레임)를 띄운다. |
| 5 | **개선 전 시나리오는 그대로 남긴다.** 새 흐름은 새 편으로 더한다. |
| 6 | @ 편은 **문 · 박스 외 임의 물체를 같은 흐름으로 찾는 범용 편**이다. |
| 7 | **회전 방식을 세 편 모두 하나로 통일한다.** `scan_mission` 을 쓰지 않고 `turn 45°` 를 여러 번 보낸다. 각 회전 뒤 웹이 data_stream 에 「지금 이 각도」를 표시하고, data_stream 이 그 장치의 카메라 스트림에서 프레임을 잡는다. 그래서 **`turn` · `move_forward` 를 선언하고 data_stream 이 영상을 받는 장치면 어느 것이든** 쓸 수 있다. |
| 8 | 옛 편과 새 편은 **탐지 방식 설정**(`legacy` / `datastream`)으로 가른다(§3). |
| 9 | 문 편 대상은 **`demo_door` 하나만**. 일반 `door` 는 넣지 않는다. |
| 10 | @ 질의는 **LLM 으로 영어로 옮겨** `query` 에, 원문은 `query_ko` 에. |
| 11 | **가시화는 `/scan/*` 명령만 보낸다.** `profile.json` 을 판 동안 바꿨다 되돌리는 일은 data_stream 쪽(창구)이 한다. |
| 12 | 창구는 **data_stream 소스 서버**(`server_stream_multi_source.py`)에 붙는다. 가시화는 장치의 소스 포트(`robot1` `:10003` 등)로 부른다. |

## 1. 지금 구조 (바꾸기 전)

| 편 | 흐름 | 탐지 |
|---|---|---|
| `MSN-260909-01` 문 쪽으로 이동 | `robotFlow: 'door-scan'` · T-A1 도면 → T-A2 방위 → T-A3 회전 → T-A4-0~7 → T-A5 판단 → T-A6 근거 → T-B1 도면 경로 → T-B2 이동 → T-B3 정지 | 별도 탐지기 `:8000` `/detect/*` 폴링 |
| `MSN-261027-01` 박스 앞까지 이동 | 같은 흐름, T-A1 없음, `detectTarget: 'box'` | 같음 (`?target=box`) |
| `MSN-260929-01` 장치 하나를 @까지 이동 | `driver: 'local'` · 가상 맵 판정(`taskRunner.ts`) | **없음** — T-B6~B8 이 가상 맵 위치로 넘어간다 |

- 회전은 pi7 GO1 의 `scan_mission` 하나다. 로봇이 각도마다 MQTT `frame`(JPEG + `rotation_deg`)을 내고 `scan_hold` 로 멈추면, 웹이 그 각도 결과를 받은 뒤(`scanGate.ts`) `scan_continue` 로 푼다(`scanContinue.ts`). **그래서 이 흐름은 GO1 한 대에 묶여 있다.**
- 대본 매칭은 **둘 이상 맞으면 거부**한다(`matcher.ts`). 같은 문장의 옛 편 · 새 편이 함께 서면 둘 다 안 고른다 — §3 이 이 문제를 푼다.

## 2. 새 흐름

### 2-1. 새 편 셋

| 새 편 | 바탕 | `target` | data_stream `targeted` 대상 |
|---|---|---|---|
| `MSN-261123-01` 문 쪽으로 이동 (data_stream) | `MSN-260909-01` 에서 T-A1 · 도면 경로를 뺀 것 | `door` | `demo_door` |
| `MSN-261123-02` 박스 앞까지 이동 (data_stream) | `MSN-261027-01` | `box` | `demo_box` |
| `MSN-261123-03` 장치 하나를 @ 앞까지 이동 (data_stream) | 위 둘의 뼈대 + `@` 슬롯 | `object` · `query` = 발화의 @ 를 **영어로** 옮긴 것 · `query_ko` = 원문 | 직접 입력(제로샷) |

세 편 모두 대본에 `robotFlow: 'scan-detect'` 와 `scanTarget` 을 적는다. **옛 `'door-scan'` 흐름은 손대지 않는다.**

### 2-2. 과업 (세 편 공통, 이름만 대상에 맞춘다)

| 과업 | 하는 일 | 끝나는 조건 |
|---|---|---|
| **T-A0** 탐지 준비 | `POST /scan/prepare {device, target, query, query_ko}` → `GET /scan/status` 폴링. data_stream 이 그 장치의 소스를 못 찾거나(`no_stream`) 그 소스에 `targeted` 가 안 돌거나(`no_vision`) 대상 반영이 거절되면 여기서 실패한다. GroundingDINO · UniDepth 를 새로 올리면 수십 초 걸린다. | `ready` (60초 넘으면 실패) |
| T-A2 로봇 현재 방위 파악 | 지금 그대로 (`prepStage.ts`, 도면 없이). 방위를 못 주는 장치는 「모름」으로 넘어간다. | 방위 받음 / 모름 |
| T-A3 로봇이 1바퀴 돈다 | 아래 회전 순서 | 마지막 `turn` 완료 |
| T-A4-0~7 각도 탐색 | `mark` 응답이 오면 그 각도 칸에 잡힌 프레임을 띄운다. 결과 뒤 found / 아님을 칠한다. | 결과 도착 |
| **T-A5** 위치 산출 | 마지막 `mark` 뒤 `POST /scan/finish` → `GET /scan/result` 폴링 | `done` / `failed` (30초 한도) |
| T-A6 근거 가시화 | `evidence.cues[]` · `reason` · `crop` · `overlay` · `distance_source` · `provisional`(「측정 전 하한」 표시) | 표시 |
| T-B1 이동 경로 산출 | §2-4 | 경로 있음 (없으면 멈춤) |
| T-B2 경로 따라 이동 · T-B3 정지 · T-C1 종료 | 지금 그대로 (`turn` → `move_forward`) | |

- **T-A1 을 쓰지 않는다.** `usesFloorPlan()` 은 대본에 T-A1 이 있는지로 도면을 판정하므로, 새 흐름에서 T-A1 이라는 이름을 다른 뜻으로 쓰면 안 된다. 그래서 탐지 준비는 **T-A0** 이다.
- @ 편은 옛 편의 「장치 준비」(T-A1~A5 장치 점검) 단계를 **이번에는 넣지 않는다.** 들이면 위 이름 규칙과 부딪치고, `driver: 'local'` 판정기와 로봇 흐름이 섞인다.

### 2-3. 회전 순서 (결정 7)

```
mark(0)                                   ← 돌기 전, 지금 방향이 0°
turn 45 → 완료 응답 → mark(45)
turn 45 → 완료 응답 → mark(90)
  …
turn 45 → 완료 응답 → mark(315)
turn 45 → 완료 응답                       ← 여덟 번째 회전: 시작 방향으로 돌아온다 (mark 없음)
finish
```

- 회전 각도 · 횟수는 대본의 `viewpoint_count` · `viewpoint_step_deg`(8 · 45)에서 온다.
- `mark` 는 `POST /scan/mark {scan_id, rotation_deg}` 다. data_stream 이 그 시점 **뒤**(흔들림을 피해 약 0.5초 뒤)에 들어온 원본 프레임의 `targeted` 결과 하나를 그 각도에 묶고, 응답에 그 결과 번호(`n`)를 준다. 잡을 결과가 없으면 그 각도는 「받지 못함」이고 회전은 계속한다.
- `turn` 완료는 지금 명령 기록이 보는 완료 응답을 그대로 쓴다. 완료가 안 오면(시간 초과) 흐름을 멈춘다 — 로봇이 어디를 보는지 모르는 채로 다음 각도를 표시하면 안 된다.
- **장치 고르기:** `turn` · `move_forward` 를 선언한 장치. 영상 소스가 있는지는 T-A0 에서 data_stream 이 판정한다.

### 2-4. 경로 계산 (결정 2)

```
turn_deg     = best.bearing_deg − 회전 오차
forward_m    = best.distance_m − params.stop_distance_max_m
안 움직이는 경우: best == null · distance_valid == false · forward_m < 0.05 · forward_m > 이동 한도
```

- `distance_valid` 는 data_stream 이 정한다(요청 문서 §5 제안: `box_height` 는 검증 범위 50~300 cm 안, 그 밖은 `dist.space == "metric"`). `demo_box` 를 GO1 이 아닌 카메라로 돌리면 거리는 UniDepth 이고 `provisional` 이다 — 그대로 움직이되 근거 카드에 적는다.
- 여덟 번 돌고 나면 시작 방향으로 돌아왔다고 본다. 다만 `turn` 을 여러 번 나눠 보내므로 오차가 쌓일 수 있다. **장치가 방위를 주면**(T-A2 가 「모름」이 아니면) `회전 오차 = 지금 방위 − 시작 방위` 로 뺀다. 못 주면 0 으로 두고, 근거 카드에 「회전 오차 보정 없음」을 적는다.
- 지금 `pathCommands()` 는 탐지기의 한국어 문장(「왼쪽으로 78.7도」)에서 방향을 읽는다. 새 흐름은 부호 있는 각도를 그대로 받으므로 **숫자를 받는 짝 함수**를 하나 더 둔다. 5° · 0.05 m 하한은 그대로.
- 자동 접근(`approachAuto.ts`)과 「승인 필요」 설정은 그대로 따른다.

## 3. 옛 편과 새 편을 함께 두기 (결정 5 · 8)

같은 문장(「문 쪽으로 가」)이 두 편에 다 맞으면 매칭이 거부된다. 그래서 **탐지 방식 설정 하나**로 매칭에 설 편을 가른다.

| 설정 `scanDetectSource` | 매칭에 서는 편 | 목록(라이브러리) |
|---|---|---|
| `legacy` (처음 기본값) | 옛 셋 | 여섯 다 보임 — 새 셋에 「data_stream」 딱지 |
| `datastream` | 새 셋 | 여섯 다 보임 — 옛 셋에 「옛 탐지기」 딱지 |

- 대본 파일에 `detectSource: 'legacy' | 'datastream'` 을 적는다(옛 편은 안 적으면 `legacy`). 탐지와 상관없는 편(정량 명령 · 자율주행 등)은 설정과 상관없이 늘 선다.
- **매칭은 게이트웨이(`script-engine.ts`)와 브라우저가 같은 `matcher.ts` 를 쓴다.** 그래서 설정은 게이트웨이가 들고 있고, 브라우저는 게이트웨이에서 읽는다. 브라우저 혼자 들고 있으면 둘이 다른 편을 고른다.
- 설정은 연결 판에서 바꾼다. 임무가 도는 중에는 바꾸지 못한다.
- 옛 @ 편(`MSN-260929-01`)과 새 @ 편은 같은 설정 아래에서 동시에 서지 않으므로 문장이 같아도 된다. 다만 설정마다 문장이 정확히 한 편에만 맞는지 검사로 확인한다(§6).
- 새 편을 더하면 **게이트웨이를 다시 띄워야** 승인이 선다.

## 4. 각도별 판정 화면 (결정 4)

| 시점 | 각도 칸에 보이는 것 |
|---|---|
| 회전 중, 그 각도 `mark` 전 | 빈 칸 |
| 회전 중, `mark` 응답 뒤 | data_stream 이 잡은 **그 각도의 프레임**(`/scan/frame?kind=original`) · 「수집됨」 |
| 결과 뒤, `found` | `overlay` 그림 · 점수 · 초록 |
| 결과 뒤, 아님 | 원본 프레임 · `reason` · 회색 |
| 결과 뒤 / 회전 중, 프레임 못 잡음 | 「받지 못함」 · 주황 |

- 그림은 data_stream 에서 받는다. 로봇 MQTT 프레임에 기대지 않으므로 어느 장치든 같다.
- 브라우저는 **각도당 한 장만** 든다. 판이 바뀌면 비운다.
- 임무 기록에는 각도별 원본 · `overlay` · `crop` 을 data_stream 에서 받아 남긴다(지금 기록기의 그림 줄에 올린다).

## 5. 고칠 곳

| 단계 | 파일 | 할 일 |
|---|---|---|
| **S0 가짜 창구** | `scripts/scan-detect-mock.mjs` (새) | 요청 문서 §3 그대로 응답하는 가짜 서버. 상태 전이 · `mark` 프레임 없음 · 실패(`no_stream` · `no_vision` · 반영 거절) · 시간 초과 · 409 · `profile_version` 바뀜 · `provisional` 을 고를 수 있게. 근거 단서 이름은 data_stream 처럼 영어로. data_stream 없이 개발 · 검사한다(임무 이력 서버 때의 `history-server-mock.mjs` 와 같은 방식). |
| **S1 연결** | `src/detect/scan/ScanClient.ts` (새) · 연결 판 | 「스캔 탐지(data_stream)」 호스트 칸 하나(`scan.host`, `VITE_SCAN_DETECT_HOST`)와 **장치 → 소스 포트 표**(`scan.ports`, 처음 값 `go1-001 → 10003`). 창구가 소스 서버에 붙으므로(결정 12) 주소는 `http://<호스트>:<그 장치 포트>` 다. 표에 없는 장치는 T-A0 에서 「스캔 창구 주소 없음」으로 멈춘다. `prepare` · `status` · `mark` · `finish` · `result` · `frame` · `cancel` · `health`. 옛 `DetectClient.ts` 는 그대로. |
| **S2 흐름 갈래** | `src/scenarios/library.ts` · `types.ts` | `scanDetectFlow()` · `scanTargetOf()` 추가. 로봇 관문 · 준비처럼 두 흐름이 같이 쓰는 곳은 `scanFlow()` = 둘 중 하나. 옛 `doorScanFlow()` 의 뜻은 안 바꾼다. |
| **S3 준비 · 회전 · 산출** | `src/physical/scanDetectRun.ts` (새) · `missionLink.ts` · `robotSession.ts` · `prepStage.ts` | T-A0 를 앞에 세우고 `ready` 전에는 회전하지 않는다. §2-3 회전 순서(`turn` → 완료 → `mark`)를 도는 실행기. 마지막 회전 → T-A5 `finish`. 새 흐름에서는 `scan_mission` · `scanGate.ts` · `scanContinue.ts` 를 거치지 않는다. |
| **S4 결과 상태** | `src/detect/scan/scanStore.ts` · `scanPoll.ts` (새) | `scan_id` 하나에 상태 · 각도별 프레임 · 결과. 다른 `scan_id` 의 응답은 버린다(옛 `poll.ts` 의 지난 판 거르기와 같은 일). |
| **S5 각도 칸** | 각도 칸 뷰 · `scanStore.ts` | `mark` 응답 뒤 `/scan/frame` 그림을 각도 칸에 띄운다(§4). |
| **S6 경로 · 이동** | `src/physical/approachPlan.ts` · `missionLink.ts` | `best` 에서 경로 계산 · 회전 오차 보정(§2-4), 숫자 각도용 `pathCommands` 짝. |
| **S7 근거 카드** | `src/detect/views/` 아래 새 뷰 | `cues[]` 표 · `reason` · `crop` · `overlay` · 거리 출처 · 측정 전 하한 · 회전 오차 보정 여부. 단서 이름이 영어로 오므로 한국어 화면에서는 이름 표(`CLIP colour` → 「CLIP 색」 등, data_stream 계획 §3.1 런처 이름)로 옮기고, 표에 없으면 영어 그대로 둔다. 옛 `DetectViews.tsx` 는 그대로. |
| **S8 편 셋** | `scenarios/MSN-261123-0{1,2,3}.json` · `.en.json` · `manifest.ts` | §2-2 과업, `detectSource: 'datastream'`, @ 편 슬롯과 `query`(영어) · `query_ko`. @ 는 T-A0 직전에 가시화가 이미 쓰는 LLM 창구(`src/generate/LlmClient.ts` 쪽)로 영어 이름 하나로 옮긴다. 옮기기에 실패하거나 빈 답이면 `prepare` 를 보내지 않고 멈춘다. 옮긴 이름은 T-A0 노드 · 명령 기록에 원문과 함께 남긴다. `params.stop_distance_max_m`(0.9) · `viewpoint_count` · `viewpoint_step_deg`. |
| **S9 탐지 방식 설정** | `gateway/scenarios.ts` · `script-engine.ts` · `matcher.ts` 호출부 · 연결 판 | §3. 기본값 `legacy`. |
| **S10 정지 · 기록 · 문구** | `StopButton.tsx` · `record/` · `i18n/ko.ts` · `en.ts` | 정지 → 로봇 정지 + `/scan/cancel`. 명령 기록에 data_stream 명령(`prepare` · `mark` · `finish` · `cancel`)을 남긴다(노드는 T-A0 · T-A4-n · T-A5). 문구 한 · 영. |
| **S11 검사** | `scripts/verify-scan-detect.mjs` (새) · `verify-script-{door,box,at-move}.mjs` | 아래 §6. |

순서: **S0 → S1 → S2 → S8 → S9 → S3 → S4 → S5 → S6 → S7 → S10 → S11.** 편과 매칭(S8 · S9)을 먼저 세워야 흐름을 화면에서 돌려 볼 수 있다.

## 6. 검사

- **가짜 창구 + 가짜 장치로 끝까지:** 준비(loading → ready) → `mark(0)` → `turn` ×8 · `mark` ×7 → finish → done → 경로 → 이동 명령 두 개. 가짜 장치는 지금 `fakeDevice.ts` 를 쓴다(`turn` · `move_forward` 를 이미 선언한다).
- **회전 순서:** `mark` 가 해당 `turn` 완료 **뒤에만** 나간다. `turn` 완료가 안 오면 다음 `mark` · `turn` 이 안 나간다.
- **실패 갈래:** `prepare` 60초 넘김 · 영상 소스 없음 · `targeted` 안 돎 · 대상 반영 거절 · 판 도중 `profile_version` 바뀜 · `failed` · `best: null` · `distance_valid: false` · `mark` 둘이 「프레임 없음」 · 409 · 정지 버튼 → 어느 것도 이동 명령이 안 나간다(프레임 없음은 그 각도만 비고 결과는 받는다).
- **지난 판:** 다른 `scan_id` 의 결과가 오면 버린다.
- **경로 계산:** 방위 −170 · 5 미만 · 0.05 m 미만 · 이동 한도 초과 · 회전 오차 보정 있음 / 없음.
- **옛 편 무손상:** 설정 `legacy` 에서 `verify-script-door` · `verify-script-box` · `verify-script-at-move` 가 지금과 같이 통과.
- **매칭:** 설정마다 같은 문장이 정확히 한 편에만 맞는다. 탐지와 상관없는 편은 두 설정에서 다 맞는다.

## 7. 아직 정하지 않은 것

| # | 물음 | 지금 생각 |
|---|---|---|
| 1 | 판 동안 런처가 `profile.json` 을 바꾸면 | data_stream 쪽 회신을 본다(요청 문서 §8-1 의 1). 가시화는 결과의 `profile_version` 이 판 중에 바뀌면 `failed` 로 받아 멈춘다. 창구가 생기기 전까지 S0 가짜 창구로 진행한다. |
| 2 | @ 옮기기 LLM 요청 모양 | 영어 이름 하나만 돌려받는 짧은 요청. 생성 창구에 붙일지 따로 둘지는 S8 구현 때 정한다. |
| 3 | 정지 거리 | 옛 두 편의 `stop_distance_max_m` 0.9 m 를 그대로 쓴다. 지금은 탐지기가 `standoff_cm` 를 줬는데, 새 흐름은 대본 값이다. |
| 4 | 탐지 방식 기본값을 언제 `datastream` 으로 바꾸나 | 실물로 세 편이 한 번씩 통과한 뒤. |
| 5 | `mark` 뒤 기다리는 시간 | 0.5초로 시작해 실물에서 흔들림을 보고 맞춘다(요청 문서 §2). |
| 6 | GO1 아닌 장치의 하한 · 거리 | data_stream 값은 Go1 카메라에서 잰 `provisional`. 다른 장치로 돌리면 결과를 믿을 수 있는지 요청 문서 §8-1 의 3 회신을 본다. |
