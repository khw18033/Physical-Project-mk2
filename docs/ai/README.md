# 문서 안내

현재 요구사항 구현과 검증에 사용하는 문서만 정리한다. 번호는 작성 순서이며 읽는 순서가 아니다.

## 지금 살아 있는 문서

| 문서 | 무엇을 답하는가 |
|---|---|
| [00-architecture](00-architecture.md) | 구조와 경계. 새로 합류하면 여기부터 |
| [requirement-traceability](requirement-traceability.md) | 요구사항 ID별 구현 위치·테스트·상태 |
| [02-infra-mock-plan](02-infra-mock-plan.md) | 실 인프라(MQTT/Kafka/K3s 등) 로컬 검증 범위와 하드웨어 mock 대체 계획 |
| [03-framework-property-scenarios](03-framework-property-scenarios.md) | `perception-framework/tests/scenarios/`가 검증하는 프레임워크 특성 |
| [04-demonstration-data-collection](04-demonstration-data-collection.md) | 시연 실행이 어떻게 실험 데이터가 되는가(`observability/experiment.py`) |

## 다른 곳에 있는 것

| 대상 | 위치 |
|---|---|
| KCI 확장 연구 — 재현 대상 논문·아이디어·구현 계획 | `docs/obsidian/` |
| 하드웨어·백엔드·가시화 파트 연동 계약 | `contracts/ai/` |
| 작업 규약(Skill) | `.claude/skills/` |

과거 실험 기록(`experiments/`, `reports/`, `scenarios/`), 파트 통합 가이드(`docs/integration/`),
선행연구·아이디어 vault는 재사용 계획이 없어 제거했다(2026-09-01). 필요하면 Git 이력에서
확인한다.
