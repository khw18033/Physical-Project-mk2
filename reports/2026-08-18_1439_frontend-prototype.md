# 작업 보고서 — 프런트엔드 초안(계약 검증용 프로토타입)

**작업 일시**: 2026-08-18 14:39:37 (KST)
**작업자**: Claude Code (요청자: Hyunwoo Kim)
**직전 보고서**: `2026-08-18_1400_phase0-remaining-contracts.md`

---

## 1. 작업 개요

"프런트엔드 초안을 지금 만들 수 있는가"라는 질문에서 출발했다. Phase 0에서
계약이 확정되었으므로 **가능하고, 오히려 지금이 적기**라고 판단했다. 프런트엔드가
필요한 것은 Go 백엔드가 아니라 계약 형태의 데이터이고, 그것은 이미
`contracts/examples/`에 존재하기 때문이다. 계약 우선 설계의 목적 자체가 양쪽의
병렬 진행이다.

더 중요한 판단 근거는, 프런트 초안이 **계약 검증 수단**이 된다는 점이었다.
"디스크립터 + 파이프라인 + 렌더러 계약만으로 실제 대시보드를 그릴 수 있는가"는
지금 확인하면 싸고 Go 코어를 다 만든 뒤 발견하면 비싸다. 이 판단은 실제로
회수되었다 — 아래 3장의 계약 결함 2건을 조기에 발견했다.

**선택한 형태**: 무빌드 단일 HTML 프로토타입 (사용자 결정)
**선택한 범위**: 렌더러 3종 + 파이프라인 해석 + 라이프사이클 상태 표시(F2) (사용자 결정)

## 2. 산출물

| 파일 | 내용 |
|---|---|
| `web-dashboard/prototype.html` | 무빌드 단일 HTML 프로토타입. 빌드·npm 없이 브라우저에서 바로 동작한다. |
| `web-dashboard/README.md` | 실행 방법, 요구사항 매핑, 프로토타입의 한계 5가지 명시. |
| `contracts/examples/renderer/valid-text.json` | text 렌더러 카탈로그 항목(신규). |
| `contracts/examples/renderer/valid-table.json` | table 렌더러 카탈로그 항목(신규). |
| `contracts/examples/component-descriptor/valid-batch-processor.json` | array 필드를 가진 디스크립터(table 렌더러 검증용). |
| `contracts/examples/component-descriptor/valid-camera-stream.json` | binary-stream 필드를 가진 디스크립터(REQ-502 검증용). |
| `contracts/examples/pipeline/valid-status-text.json` | enum → text 직접 해석 경로. |
| `contracts/examples/pipeline/valid-batch-table.json` | array → table 직접 해석 경로. |
| `contracts/examples/pipeline/valid-camera-stream.json` | stream → video-stream 경로. |
| `contracts/examples/datasource/valid-stream-gateway.json` | Prometheus가 아닌 두 번째 DataSource 타입(NFR-005 검증용). |
| `reports/assets/*.png` | 렌더링 결과 스크린샷 2장. |

프로토타입은 계약 파일의 **사본을 두지 않고** `../contracts/examples/`를 직접
읽는다. 계약이 바뀌면 화면도 즉시 따라 바뀌므로 드리프트가 발생하지 않는다.

## 3. 이번 작업이 발견한 계약 결함 2건 (수정 완료)

프런트엔드를 붙이는 과정에서 계약 스스로는 드러내지 못한 문제가 나왔다.

### 3.1 `binary-stream` 타입 부재로 스트리밍 렌더러가 도달 불가능

- **증상**: `video-stream` 렌더러는 `acceptsFieldTypes: ["binary-stream"]`을
  선언하는데, 컴포넌트 디스크립터의 `field.type` enum에는 `binary-stream`이
  없었다. 즉 **어떤 디스크립터도 스트리밍 렌더러가 받을 수 있는 필드를 선언할
  수 없는** 상태였다.
- **영향**: REQ-502(스트리밍을 1급 컴포넌트로 승격)가 계약 수준에서 무력화됨.
  기존 12개 예시로는 두 스키마를 각각 검증할 뿐 교차 검증하지 않아 드러나지 않았다.
- **조치**: `component-descriptor.schema.json`의 `field.type`에 `binary-stream`
  추가.

### 3.2 `datasource.schema.json`에만 `description` 속성 누락

- **증상**: 나머지 4개 계약에는 모두 있는 `description`이 datasource에만 없어,
  `additionalProperties: false`에 걸려 정상적인 예시가 거부되었다.
- **조치**: 스키마에 `description` 추가. (예시가 아니라 스키마 쪽 누락이었다)

## 4. 검증 결과

### 4.1 계약 검증

`python contracts/validate_examples.py` → **20건 전체 통과, 실패 0건**
(직전 12건 → 예시 8건 추가)

### 4.2 실제 브라우저 렌더링 검증

정적 서버(`python -m http.server 8000`)를 띄우고 **헤드리스 Chrome으로 실제
렌더링 결과를 캡처해 눈으로 확인**했다. 서빙 성공 여부만으로 갈음하지 않았다.

**스크린샷 1 — 라이프사이클 3상태 구분 (`assets/2026-08-18_1439_prototype-lifecycle-states.png`)**

- 정상: 실선 테두리 + 초록 배지, 데이터 렌더링
- 의도적 미배포: **점선 테두리** + 회색 배지 + "데이터 없음이 정상입니다" 안내
- 장애: **빨간 테두리** + 빨간 배지 + "응답이 없습니다" 안내
- → REQ-203이 요구하는 "의도적 미배포와 장애의 구분 표시"가 화면에서 실제로
  구별된다.

**스크린샷 2 — 렌더러 4종 전부 (`assets/2026-08-18_1439_prototype-all-active.png`)**

| 렌더러 | 확인 내용 |
|---|---|
| graph | 직접 해석: `celsius · min 38.5 / max 86.7 / now 75.4` |
| graph | 간접 해석: `resample@server → unit-convert@client` 적용 후 `fahrenheit`로 단위 변환됨. 리샘플로 꺾은선 정점 수가 눈에 띄게 줄어 변환이 실제 동작함을 확인. |
| text | enum 필드 값(`error`)을 `emphasis: strong` 설정대로 강조 표시 |
| table | `rendererConfig.columns`(batchId/durationMs/result)와 `maxRows: 8`을 그대로 반영 |
| video-stream | LIVE 배지 + `codec=h264 autoplay=true` (rendererConfig 반영) |

**검증 과정에서의 수정**: 첫 스크린샷에서 table과 video-stream 렌더러가 화면에
없었다. 초기 시연 상태를 미배포/장애로 설정해 두어 4종 중 2종이 시각적으로
검증되지 않는 상태였다. 이를 발견하고 URL 파라미터
(`?lifecycle=camera-01:active,...`)로 초기 상태를 지정할 수 있게 추가한 뒤
전 상태를 다시 캡처했다. 이 기능은 특정 상태 화면을 공유·캡처할 때도 유용하다.

## 5. 프로토타입의 한계 (실제 구현과 다른 부분)

`web-dashboard/README.md`에도 동일하게 기록했다.

1. **데이터 소스가 목(mock)이다.** 실제 코어는 `source.query`(PromQL 등)를
   DataSource에 넘기지만, 프로토타입은 질의 문법을 해석할 수 없어 sink가
   가리키는 디스크립터 필드의 메타데이터(`valueRange`/`enumValues`/`unit`)로부터
   값을 합성한다. 역으로 이는 **REQ-103 시맨틱 메타데이터만으로 그럴듯한
   데이터를 만들 수 있는가**에 대한 검증이 되었고, 결과는 "충분하다"였다.
2. 파이프라인 그래프를 **선형 체인으로만** 순회한다. 분기·합류(join) DAG 미지원.
3. 영상 스트림은 플레이스홀더다.
4. F8 validator가 없어 참조 무결성 오류는 런타임 패널 내 오류 표시로만 드러난다.
5. F6 이벤트 규칙은 이번 범위에서 제외했다.

## 6. 미결 사항

### 6.1 이월 (변동 없음)

1. **버전 호환성 판단 로직** — "메이저 다르면 비호환" 정책의 실제 구현 미정.
2. **`valueRange` 조건부 적용** — `type=number`일 때만 유효하도록 `if/then`으로
   강제할지 여부. 기술적으로 가능함은 확인됨.

### 6.2 신규

3. **SPA 프레임워크 미확정** — 정식 이관 시 React/Vue 결정 필요.
4. **코어↔SPA API 계약 미정의** — 목 데이터를 실제 Go 코어 API로 교체하는
   시점에 OpenAPI 등으로 고정해야 한다(`구현계획서.md` 3장 리스크와 동일 항목).
5. **교차 계약 검증의 부재가 3.1 결함을 놓치게 했다.** 현재 validator는 각
   스키마를 독립적으로만 검사한다. F8 착수 시 **계약 간 정합성 검사**(렌더러
   `acceptsFieldTypes` ↔ 디스크립터 `field.type` 등)를 반드시 포함해야 하며,
   이는 직전 보고서 5.2절의 F8 과제 목록에 추가된다.

## 7. 계획서 반영

`구현계획서.md`에 **Phase 0.5 — 프런트엔드 프로토타입(병렬 트랙, 완료)** 절을
추가했다. 아울러 F5 렌더러가 스키마상 대부분 `executionLocation: client`이므로
**렌더러 구현의 상당 부분이 실질적으로 프런트엔드 작업**이라는 점을 명시했다.
계획서 모듈 표는 `renderers/`와 `web-dashboard/`를 분리하고 있으나, 실제 작업
단위는 겹친다.

## 8. 다음 단계

Phase 1(코어 스켈레톤, Go)로 진행한다. 프로토타입이 계약의 실행 가능성을
입증했으므로, Go 코어는 이 프로토타입이 목으로 대체한 부분(DataSource 질의,
프로비저닝, 참조 무결성 검증)을 실제로 채우는 방향이 된다.
