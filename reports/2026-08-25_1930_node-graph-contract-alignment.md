# 2026-08-25 19:30 — 노드 그래프 계약 정합과 누락 요건 보완

**직전 보고서**: `2026-08-25_1804_node-graph-doc-code-audit.md`

**기준**: `REQ-1001`~`REQ-1007` · `contracts/pipeline.schema.json` · 등록 디스크립터/렌더러/데이터소스

**범위**: `REQ-1002` 무손실 왕복, `REQ-1003` 카탈로그 자동 구성, `REQ-1007` 역방향 관측, 대상 ID 고정 해제, 관련 문서 정정

## 결과

대조 보고서가 찾은 세 공백을 메웠다. 계약 스키마 파일은 바꾸지 않았고 기존 임무 관제의
`plan`·`plan_progress` 흐름도 바꾸지 않았다.

| 요건 | 결과 | 근거 |
|---|---|---|
| `REQ-1002` | 완료 | 초안을 `{ pipeline, layout }`으로 분리하고 공용 직렬화 계층과 스키마 왕복 검증 추가 |
| `REQ-1003` | 완료 | 코드 상수 노드 목록을 제거하고 `contracts/examples/` 등록 파일에서 카탈로그 파생 |
| `REQ-1007` | 완료 (**목 경계 포함**) | 반영 그래프의 노드별 최근 수신·건수·마지막 값 표시. 시험 결과와 별도 영역·별도 응답 |
| 대상 고정 해제 | 완료 | 임무 대상과 근거 후보를 레지스트리 및 실제 수신 채널에서 구성 |

## 1. 계약 무손실 왕복

- 편집기 초안의 표준형을 `pipeline.schema.json` 계약 본문과 별도 `layout`으로 나눴다.
- `source`·`transform`·`sink` 노드는 각각 계약이 요구하는 설정 객체를 가진다.
- 화면과 목 게이트웨이가 `web-dashboard/shared/pipeline-contract.ts`의 같은 직렬화·검증
  계층을 사용한다.
- 계약 JSON을 내보낼 때 좌표가 제거되고, 같은 계약과 레이아웃을 다시 읽으면 원래 초안이
  복원된다. 레이아웃이 없으면 자동 배치하되 계약 본문은 그대로 유지한다.
- `contracts/validate_instance.py`는 기존 `validate_examples.py`와 같은 JSON Schema 검증
  방식으로 단일 인스턴스를 검사한다.

`verify:contract-roundtrip`은 생성 계약의 스키마 통과, 계약 밖 키 0건, 일부러 넣은 좌표의
스키마 거부, 등록된 유효 파이프라인 예시 5건의 계약→초안→계약 동일성을 확인한다.

## 2. 등록처에서 파생되는 카탈로그

`NODE_CATALOG` 상수 배열을 없앴다. 목 게이트웨이는 다음 등록 파일을 읽어 노드 종류와
기본 설정을 만든다.

- `contracts/examples/component-descriptor/valid-*.json`
- `contracts/examples/renderer/valid-*.json`
- `contracts/examples/datasource/valid-*.json`

포트 타입은 디스크립터 `field.type`과 렌더러 `acceptsFieldTypes`에서 가져온다.
`verify:catalog-derived`는 임시 렌더러 예시 하나를 추가했을 때 TypeScript 변경 없이
카탈로그가 14종에서 15종으로 늘고, 파일 제거 뒤 14종으로 돌아오는 것을 확인한다.

## 3. 반영 그래프 역방향 관측

`GET /pipelines/observation`과 화면의 **운영 그래프 관측** 영역을 추가했다. 활성 그래프의
각 노드에 최근 수신 시각, 누적 건수, 마지막 값 요약, 붙은 실제 대상을 표시한다.
초안의 시험 실행 결과는 기존 **모의 시험 결과** 영역에 `rows`·`elapsed_ms`로 남아 있어
운영 관측과 응답 모양 및 시각 표현이 섞이지 않는다.

여기에는 중요한 경계가 있다.

- source 노드는 기존 게이트웨이가 발행한 실제 목 장치 봉투를 관측한다.
- 하류 transform·sink 값은 **목 파이프라인 실행기**가 전달한 값이다.
- 따라서 노드별 필드 수준의 실물 실행 관측이나 영속 이력은 아직 아니다. 응답의
  `executor`와 노드별 `origin`, 화면 문구가 이 사실을 숨기지 않는다.

## 4. 대상 ID 고정 해제와 문서 정정

- `NodeGraphView.tsx`의 `robot-01` 직접 조회와 네 대상짜리 근거 상수를 제거했다.
- `MissionView.tsx`의 `PLAN_ENTITY`를 제거했다. 임무 대상과 근거 후보는 레지스트리에서
  파생되며 등록 대상이 늘면 화면 후보도 함께 늘어난다.
- 구현 현황은 `VZ-U-04`를 `REQ-1001`~`1007`로 풀어 근거를 적었다. 완료 수 `27/33`은
  시트의 `VZ-*` 행을 세는 숫자라 유지했다. 이번 변경은 행 수가 아니라 한 행의 근거를
  네 요건에서 일곱 요건으로 복구한 것이다.
- 이전 15:25 보고서는 지우지 않고 과장된 계약 재사용 서술을 후속 정정으로 남겼다.
- 작업 계획, 백엔드 회신의 문서명, README 규칙과 검증 명령을 현행에 맞췄다.
- 문서 검증 D는 `npm run`과 `npm.cmd run`을 모두 읽고, 등록됐지만 어느 문서도 부르지
  않는 `verify:*` 스크립트도 찾는다.

## 5. 검증

| 명령 | 결과 |
|---|---|
| `npm.cmd run typecheck` | 통과 |
| `npm.cmd run build` | 통과 · Vite 62 modules · JS 307.17 kB (gzip 96.09 kB) |
| `npm.cmd run verify:cache` | 통과 · 금지 채널 재생 0 · 허용 밖 채널 0 · 원본 `ts` 보존 |
| `npm.cmd run verify:pipeline` | 통과 · 카탈로그 14종 · 거부 5종 · 시험/반영/복구/감사/관측 |
| `npm.cmd run verify:mission-graph` | 통과 · 별도 깨끗한 목 서버에서 승인 전 진행 0건 · 실패 뒤 건너뜀 |
| `npm.cmd run verify:contract-roundtrip` | 통과 · 왕복 · 좌표 격리 · 스키마 검증 |
| `npm.cmd run verify:catalog-derived` | 통과 · 예시 파일만으로 14→15종 |
| `python docs/verify_docs.py` | 통과 · A~F 이상 없음 · 미발견 참조 0건 |
| `git diff --check` | 통과 |

임무 그래프 검증은 기존 8787 서버가 과거 `plan_progress`를 캐시한 상태에서는 검증기 자체의
"전체 수신 건수 0" 가정 때문에 실패했다. 사용자 서버를 종료하지 않고 8791 포트에 깨끗한
서버를 띄워 재실행했으며 기존 임무 흐름의 회귀가 아님을 확인했다.

## 남은 경계

- 카탈로그 입력과 파이프라인 실행기는 여전히 목이다. 운영 등록 서비스와 실물 실행기로
  교체할 때 HTTP 어댑터와 실행 경계를 연결해야 한다.
- 하류 노드 관측은 목 전달값이다. 실물 실행기가 노드별 관측 봉투를 내기 전에는 필드 수준
  계보나 영속 관측 이력을 주장하지 않는다.
- LLM 그래프 초안 생성(`VZ-L-04`)은 이번 범위가 아니며 기존 대기 상태를 유지한다.
- 이번 작업에서 계약 스키마를 고쳐야만 풀리는 지점은 발견하지 않았다.
