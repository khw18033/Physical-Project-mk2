# AI 요구사항 추적표 (담당: 진나영)

CLAUDE.md §7 규칙에 따라 요구사항 ID별 구현 위치·테스트·충족 여부를 기록한다.
이번 단계는 §6 구현 순서의 1~4단계(공통 경계·Registry·프로파일 설계)와 7단계 일부
(선택 기능 부재·장애·자원 부족 시 동작)를 우선 구현했고, AI-N-01을 수직 슬라이스로
전체 패턴을 실증했다. 나머지는 이 골격 위에 이어서 구현한다.

상태 값: **완료** = 요구사항이 정의한 동작·경계가 테스트로 보장됨 /
**부분(인터페이스만)** = 공통 인터페이스/자료구조는 정의했으나 구체 provider·업무 로직은
미구현 / **미착수**.

## 온디바이스

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-N-01 | 완료 | `ai-framework/ai_framework/reference/local_safety.py` | `tests/test_local_safety.py` |
| AI-N-02 | 미착수 | - | - |

## 감시·인지 (엣지)

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-E-01 | 미착수 | - | - |
| AI-E-02 | 미착수 | - | - |
| AI-E-03 | 미착수 | - | - |
| AI-E-04 | 미착수 (선택기능 실행 패턴은 `CapabilitySelector`로 재사용 가능) | - | - |

## 의사결정

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-D-01 | 미착수 | - | - |
| AI-D-02 | 미착수 | - | - |
| AI-D-03 | 미착수 | - | - |
| AI-D-04 | 미착수 | - | - |

## 감시·인지 (추적/판단)

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-S-01 | 미착수 | - | - |
| AI-S-02 | 미착수 | - | - |
| AI-S-03 | 미착수| - | - |
| AI-S-04 | 미착수 | - | - |
| AI-S-05 | 미착수 (근거: `CapabilityRegistry` + `CapabilitySelector` 재사용 가능) | - | - |

## 위험도

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-R-01 | 미착수 | - | - |
| AI-R-02 | 미착수 | - | - |
| AI-R-03 | 미착수 | - | - |
| AI-R-04 | 미착수 (근거: `select_with_degrade`로 관측·분석 수준 단계적 조정 가능) | - | - |

## 자원·배포

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-B-01 | 완료 | `contracts/profile.py` (`CompatibilityProfile`, `ResourceCost`, `ResourceBudget`) | `tests/test_selector.py` |
| AI-B-02 | 미착수 | - | - |
| AI-B-03 | 부분(인터페이스만) | `providers/adapters.py::ControlProvider` | - |
| AI-B-04 | 부분 | `contracts/profile.py::CompatibilityProfile` (required/preferred hw 태그 구분). preferred 태그는 선언만 되고 선택 가중치에는 아직 미반영 | `tests/test_selector.py` |
| AI-B-05 | 미착수 | - | - |
| AI-B-06 | 부분 | `selection/selector.py::CapabilitySelector.select_with_degrade` | `tests/test_selector.py` |
| AI-B-07 | 부분 (health 실패 격리만, 버전 롤백 미구현) | `registry/capability_registry.py::ProviderRegistration.is_healthy` | `tests/test_capability_registry.py` |
| AI-B-08 | 부분(인터페이스만) | `providers/adapters.py::AIRuntimeProvider` | - |
| AI-B-09 | 미착수 (등록 지점은 `CapabilityRegistry.register_local`로 이미 존재, 검증 파이프라인 없음) | - | - |
| AI-B-10 | 미착수 | - | - |

## 관측

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-O-01 | 부분(인터페이스만) | `providers/adapters.py::ObservabilityProvider` | - |
| AI-O-02 | 부분(인터페이스만) | `providers/adapters.py::ObservabilityProvider.record_event` | - |
| AI-O-03 | 미착수 | - | - |
| AI-O-04 | 미착수 | - | - |

## 공통

| ID | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|
| AI-C-01 | 미착수 (의도적 보류 — §6-8: 전체 기능 구현 후 데이터 사전 통일) | - | - |
| AI-C-02 | 미착수 | - | - |
| AI-C-03 | 미착수 | - | - |
| AI-C-04 | 부분(인터페이스만) | `providers/adapters.py` 전체 | - |
| AI-C-05 | 완료 | `contracts/capability.py` (`CapabilityState`, `CapabilityRequirement`) | `tests/test_local_safety.py` 등 |
| AI-C-06 | 부분(인터페이스만) | `providers/adapters.py::TransportProvider` | - |
| AI-C-07 | 부분(인터페이스만) | `providers/adapters.py::SerializerProvider` | - |
| AI-C-08 | 부분(인터페이스만) | `providers/adapters.py::MediaSourceProvider` | - |
| AI-C-09 | 미착수 (근거: `AIRuntimeProvider` 재사용 가능) | - | - |
| AI-C-10 | 완료 | `registry/capability_registry.py::CapabilityRegistry` | `tests/test_capability_registry.py` |
| AI-C-11 | 완료 | `contracts/capability.py::CapabilityRequirement.evaluate` + registry 조합 | `tests/test_local_safety.py`, `tests/test_capability_registry.py` |
| AI-C-12 | 부분 | `providers/adapters.py` 전체 (Protocol 기반 provider 인터페이스) | - |
| AI-C-13 | 완료 | `selection/selector.py::CapabilitySelector.select` | `tests/test_selector.py` |
| AI-C-14 | 미착수 (Provider 인터페이스 분리까지만 되어 있고 실제 라우팅 정책 없음) | - | - |
| AI-C-15 | 완료 (데이터 구조만; 실제 도메인 프로파일 로딩·적용은 미구현) | `contracts/profile.py::DeploymentProfile` | - |

## 요약

- 완료: AI-N-01, AI-B-01, AI-C-05, AI-C-10, AI-C-11, AI-C-13, AI-C-15 (7개)
- 부분(인터페이스/골격만): AI-B-03, AI-B-04, AI-B-06, AI-B-07, AI-B-08, AI-O-01, AI-O-02, AI-C-04, AI-C-06, AI-C-07, AI-C-08, AI-C-12 (12개)
- 미착수: 나머지 29개

**추가 요구사항 필요 여부**: 없음. 이번 단계는 CLAUDE.md §6 순서를 따른 공통 골격
우선 구현이며, 문서에 없는 기능을 임의로 추가하지 않았다.
