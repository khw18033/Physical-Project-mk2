# 작업 보고서 — Phase 0 잔여 계약(F4·F5·F6·F7) 작성 및 Phase 0 완료

**작업 일시**: 2026-08-18 14:00:41 (KST)
**작업자**: Claude Code (요청자: Hyunwoo Kim)
**직전 보고서**: `2026-08-18_1354_project-kickoff-and-f1-descriptor.md`

---

## 1. 작업 개요

`구현계획서.md`의 **Phase 0 — 계약 고정** 잔여 항목인 F4(해석 파이프라인),
F5(렌더러 카탈로그), F6(이벤트 규칙 DSL), F7(DataSource) 계약을 JSON Schema로
작성하고, 각 계약마다 유효/무효 예시 인스턴스로 검증했다. 이로써 Phase 0의
계약 5종(F1·F4·F5·F6·F7)이 모두 확정되어 **Phase 0을 완료**한다.

## 2. 산출물

### 2.1 신규 계약 스키마

| 파일 | 대응 | 핵심 내용 |
|---|---|---|
| `contracts/pipeline.schema.json` | F4 (REQ-401~404) | source/transform/sink 노드 그래프. 직접 해석(REQ-401)과 간접 해석(REQ-402)을 **동일 스키마**로 표현 — transform 노드 유무로만 구분된다. 노드별 `executionLocation`(server/client, REQ-404), `serializationFormat`(REQ-403) 포함. |
| `contracts/renderer.schema.json` | F5 (REQ-501~503) | 렌더러 카탈로그 등록 단위. `streaming` 플래그로 REQ-502(스트리밍 1급 승격)를 표현하고, `acceptsFieldTypes`로 어떤 필드 타입을 받을 수 있는지 선언한다. |
| `contracts/event-rule-set.schema.json` | F6 (REQ-601~602) | 조건→뷰 액션 규칙. `and`/`or`/`not`으로 재귀 결합 가능한 조건식과 액션 목록. 규칙 엔진은 공통, 규칙 내용은 확장점 E4로 표기. |
| `contracts/datasource.schema.json` | F7 (REQ-701~702) | 데이터 소스 인스턴스 선언. `capabilities`(instant/range/stream)로 지원 질의 방식을 선언하고, `type` 값 교체만으로 관측 스택을 바꿀 수 있다(NFR-005). |

### 2.2 예시 인스턴스 (12건)

| 계약 | 유효 예시 | 무효 예시 |
|---|---|---|
| component-descriptor | `valid-temperature-sensor.json` | `invalid-missing-required-field.json` |
| pipeline | `valid-direct-interpretation.json`, `valid-indirect-interpretation.json` | `invalid-source-node-with-sink-config.json` |
| renderer | `valid-graph.json`, `valid-video-stream.json` | `invalid-empty-accepts-field-types.json` |
| event-rule-set | `valid-threshold-focus.json` | `invalid-in-operator-with-scalar-value.json` |
| datasource | `valid-prometheus.json` | `invalid-auth-without-secret-ref.json` |

### 2.3 구조 변경

- 예시 파일을 스키마별 폴더로 재배치: `contracts/examples/<schema-name>/`.
- `contracts/validate_examples.py`를 **규약 기반**으로 재작성했다. 하드코딩된
  케이스 목록을 없애고, `contracts/*.schema.json`을 순회하며 대응 폴더의 예시를
  자동 수집한다. 파일명이 `valid-`면 통과를, `invalid-`면 거부를 기대한다.
  → 앞으로 계약을 추가할 때 스크립트를 수정할 필요가 없다.

## 3. 주요 설계 결정

### 3.1 확장 가능한 타입 키는 enum으로 닫지 않는다 (일관 원칙)

`representationHint`(F1), `rendererType`/`operator`(F4), `action.type`(F6),
`datasource.type`(F7)은 모두 **자유 문자열 + 패턴 제약**으로 정의하고 enum으로
고정하지 않았다.

- **이유**: enum으로 닫으면 신규 렌더러 등록(REQ-503)이나 확장 액션 추가가
  코어 스키마 수정을 강제하게 되어 NFR-006(코어 무변경 확장)에 정면으로
  위배된다.
- **대신**: 값이 실제로 레지스트리에 등록된 키인지, 그리고 타입 정합성이
  맞는지(예: 렌더러의 `acceptsFieldTypes`가 해당 필드 `type`을 받는지)는
  **F8 validator가 카탈로그와 대조**해 검사한다. 즉 "형식 검증은 스키마,
  참조 무결성 검증은 F8"로 책임을 분리했다.
- 이 결정에 따라 F1 `representationHint`에 패턴 제약을 추가하고 설명을
  갱신했다(직전 보고서의 미결 사항 2번을 이 방향으로 정리).

### 3.2 직접/간접 해석을 하나의 스키마로 통합

REQ-401(직접)과 REQ-402(간접)를 별도 스키마로 나누지 않고, transform 노드의
유무로 구분되는 단일 그래프 스키마로 표현했다. 파이프라인 실행기가 두 경로를
분기 없이 동일하게 다룰 수 있어 구현이 단순해진다.

### 3.3 자격 증명은 디스크립터에 기록 금지

`datasource.auth`는 `secretRef`(외부 시크릿 저장소 참조)만 허용하고 비밀번호·
토큰 값 자체를 담을 필드를 두지 않았다. 디스크립터가 형상 관리 대상이 될 것을
전제한 조치다. `mode`가 `none`이 아니면 `secretRef`를 필수로 강제한다.

## 4. 검증 결과

`python contracts/validate_examples.py` → **12건 전체 통과, 실패 0건**

```
== component-descriptor.schema.json (2 example(s)) ==   [OK] x2
== datasource.schema.json (2 example(s)) ==             [OK] x2
== event-rule-set.schema.json (2 example(s)) ==         [OK] x2
== pipeline.schema.json (3 example(s)) ==               [OK] x3
== renderer.schema.json (3 example(s)) ==               [OK] x3

12 example(s) checked, 0 failure(s).
```

추가로 **무효 예시가 의도한 이유로 거부되는지**를 개별 확인했다(통과 여부만
보면 엉뚱한 이유로 실패해도 OK로 보이므로):

| 무효 예시 | 실제 거부 사유 | 의도 일치 |
|---|---|---|
| pipeline / source 노드에 sink 설정 | `nodes/0/sink: False schema does not allow ...` | ✓ 조건부 스키마 작동 확인 |
| datasource / bearer 인증에 secretRef 없음 | `auth: 'secretRef' is a required property` | ✓ if/then 작동 확인 |
| event-rule-set / in 연산자에 스칼라 값 | `rules/0/when: ... is not valid under any of the given schemas` | ✓ (단, 메시지 불명확 — 5.2 참고) |
| renderer / acceptsFieldTypes 빈 배열 | `acceptsFieldTypes: [] is too short` | ✓ |
| component-descriptor / required 키 누락 | `fields/0: 'required' is a required property` | ✓ |

## 5. 미결 사항 및 다음 단계로 넘기는 과제

### 5.1 이월된 미결 사항 (직전 보고서에서)

1. **버전 호환성 판단 로직** — 스키마는 semver 형식만 강제. "메이저 버전이
   다르면 비호환" 정책의 실제 판단은 F8/core-engine 구현 시 확정 필요. (미해결)
2. ~~`representationHint`의 enum 제한 여부~~ → **3.1에서 결정 완료**
   (열어두고 F8이 대조). 되돌릴 수 있는 결정이므로 이견 있으면 알려주십시오.
3. **`valueRange`의 조건부 적용** — `type=number`일 때만 유효하다는 제약을
   `if/then`으로 강제할지 여부. 이번에 pipeline·datasource에서 `if/then`이
   정상 작동함을 확인했으므로 **기술적으로는 적용 가능**하다. 다만 리뷰
   대기 중인 항목이라 임의로 바꾸지 않았다. (판단 필요)

### 5.2 이번 작업에서 새로 발견된 사항

4. **`oneOf` 기반 조건식의 오류 메시지가 불명확하다.** F6 조건식은
   비교식/and/or/not 중 하나를 만족해야 하는 `oneOf` 구조인데, 위반 시
   "is not valid under any of the given schemas"만 나오고 어느 분기에서 왜
   틀렸는지 알 수 없다. **F8 validator 구현 시 조건식을 직접 파싱해 사람이
   읽을 수 있는 오류를 내는 로직이 필요하다.**
5. **스키마로 표현 불가능해 F8이 맡아야 할 검사 항목**이 다음과 같이
   누적되었다. F8 착수 시 이 목록이 요구사항이 된다.
   - 파이프라인 그래프의 비순환성, `edges`가 참조하는 노드 id의 존재 여부
   - source 노드의 `queryMode`를 대상 DataSource의 `capabilities`가 지원하는지
   - sink의 `rendererType`/`componentRef`/`fieldRef`가 실제 등록된 대상인지
   - 렌더러의 `acceptsFieldTypes`와 대상 필드 `type`의 정합성
   - 렌더러의 `executionLocation`과 sink 노드 `executionLocation`의 정합성
   - 규칙 조건식의 `field`("<componentId>.<fieldName>")가 실존하는지

### 5.3 다음 단계

`구현계획서.md` 로드맵상 **Phase 1 — 코어 스켈레톤**으로 진행한다. Go 프로젝트
구조를 잡고(ADR-001), 디스크립터 등록·검증과 렌더러 3종(텍스트/테이블/그래프)의
정적 렌더링까지 구현한다. 착수 전 5.1의 미결 사항 1·3에 대한 판단이 있으면
반영하겠다.
