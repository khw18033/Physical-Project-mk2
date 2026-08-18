# 작업 보고서 — 프로젝트 킥오프 & F1 Component Descriptor 계약

**작업 일시**: 2026-08-18 13:54:14 (KST)
**작업자**: Claude Code (요청자: Hyunwoo Kim)

---

## 1. 작업 개요

빈 저장소에서 프로젝트를 킥오프하고, `구현계획서.md`의 로드맵 중 **Phase 0 —
계약 고정**의 첫 산출물인 F1(Component Descriptor) JSON Schema를 작성·검증했다.

## 2. 산출물

| 파일 | 내용 |
|---|---|
| `요구사항정의서.md` | 공통(범용) 요구사항 정의서. REQ-101~906, NFR-001~007, 확장점 E1~E6, 분야별(캡스톤/하천/국방) 매핑표 포함. |
| `구현계획서.md` | 요구사항정의서 기반 구현 로드맵. ADR-001(기술 스택: Go 확정), 모듈 분해, Phase 0~6 단계별 계획. |
| `contracts/component-descriptor.schema.json` | F1(REQ-101~104) 컴포넌트 디스크립터 JSON Schema. 필수/선택 필드, 단위·값범위·샘플링주기 메타데이터, 버전(semver) 필드 정의. |
| `contracts/examples/valid-temperature-sensor.json` | 스키마 통과를 확인하는 유효 예시 인스턴스. |
| `contracts/examples/invalid-missing-required-field.json` | 필드 정의에 `required` 키가 누락된 무효 예시 인스턴스(거부 확인용). |
| `contracts/validate_examples.py` | 위 예시들을 `jsonschema` 라이브러리로 검증하는 스크립트. |

## 3. 주요 결정 사항

- **기술 스택**: 코어 엔진(백엔드)은 성능(컨테이너 이벤트 처리량, 동시성)을
  최우선 기준으로 **Go**를 채택 (ADR-001, `구현계획서.md` 0장).
- **MVP 범위**: 코어 레이어(F1~F8)만 우선 구현. F9(제어 액션)와 확장점(E1~E6)
  실증은 2차(Phase 6)로 연기.
- **계약 우선(Contract-First) 접근**: 구현 언어와 무관하게 JSON Schema로 계약을
  먼저 고정한 뒤 코드를 작성.

## 4. 검증 결과

`python contracts/validate_examples.py` 실행 결과:

```
[OK] valid-temperature-sensor.json against component-descriptor.schema.json (expected_valid=True, actual_valid=True)
[OK] invalid-missing-required-field.json against component-descriptor.schema.json (expected_valid=False, actual_valid=False)

All cases passed.
```

## 5. 리뷰 대기 중인 설계 포인트 (미결 사항)

1. **버전 호환성 판단 로직**: 스키마는 `version` 필드가 semver 형식인지만 강제.
   "메이저 버전이 다르면 비호환"이라는 정책은 문서화만 되어 있고, 실제 판단
   로직은 이후 core-engine/validator(F8) 구현 시점에 확정 필요.
2. **`representationHint` 필드**: 현재 자유 문자열. F5 렌더러 카탈로그 계약이
   확정되면 `["text","table","graph","image","video-stream","audio"]` 같은
   enum으로 제한할 예정.
3. **`valueRange`의 조건부 적용**: `type=number`일 때만 의미가 있다는 제약을
   JSON Schema의 `if/then`으로 강제할지 여부 미결.

## 6. 다음 단계

`구현계획서.md` Phase 0 로드맵에 따라 F4(파이프라인 노드 계약: source/transform/
sink), F5(렌더러 계약), F6(이벤트 규칙 DSL), F7(DataSource 인터페이스) 계약을
같은 방식(JSON Schema + 예시 인스턴스 + 검증 스크립트)으로 이어서 작성한다.
