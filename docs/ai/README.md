# 문서 안내

목적별로 분류한다 — 작성 순서가 아니라 "무엇을 답하는가"로 찾는다.

## 구조와 상태

| 문서 | 무엇을 답하는가 |
|---|---|
| [architecture.md](architecture.md) | 구조와 경계. 새로 합류하면 여기부터 |
| [requirement-traceability.md](requirement-traceability.md) | 요구사항 ID별 구현 위치·테스트·상태 |

## `design/` — 기술·계약 설계 결정

| 문서 | 무엇을 답하는가 |
|---|---|
| [design/external-technology-decisions.md](design/external-technology-decisions.md) | 어떤 외부 기술을 core dependency로 두고 어떤 것을 provider/설계 근거 뒤에 숨겼는가, 물리 명령 계약과 Capability 계약 계층의 설계 근거 |
| [design/ondevice-pipeline.md](design/ondevice-pipeline.md) | 온디바이스 파이프라인 단계별 모델 선정 근거, Pi5 실측치, 에이전트별(로봇/고정카메라) 요구 기능, 성능 목표별 가속기 비용 |
| [design/edge-position-identity-constraints.md](design/edge-position-identity-constraints.md) | 엣지 Step 1(노드 위치·신원 발행)의 카메라 배치·로봇 마커 제약사항과 출처(원문 확인/검색 요약 구분) |
| [design/hw-vz-integration-boundary.md](design/hw-vz-integration-boundary.md) | HW·가시화 브랜치를 코드 의존성 없이 병합하기 위한 정보 교환 지점 3곳과 확인된 격차 |
| [design/river-domain-capability-extension.md](design/river-domain-capability-extension.md) | 하천 도메인(SAR/UAV/수위 등)을 배포 프로파일·provider 등록만으로 얹는 확장 설계 |
| [design/lotusim-reflection-plan.md](design/lotusim-reflection-plan.md) | LOTUSim-Energy 논문 대조 — 플랫폼·센서 태그 어휘, 자율 수준, Gazebo/ROS 2/Unity를 provider로 다루는 판단과 착수 결과 |
| [design/capability-ui-orchestration-plan.md](design/capability-ui-orchestration-plan.md) | 외부 검토(ChatGPT)의 상태 UI·k3s 폐루프·툴 스택 제안을 현재 코드에 대조한 판정표와 채택 계획(P1~P4) |

## `guides/` — 외부 대상 절차 가이드

| 문서 | 무엇을 답하는가 |
|---|---|
| [guides/hardware-extension-guide.md](guides/hardware-extension-guide.md) | 새 카메라·센서·가속기·로봇을 핵심 코드 수정 없이 추가하는 절차 |
| [guides/status-ui-runbook.md](guides/status-ui-runbook.md) | 검토용 상태 UI(`tools/status_ui/`) 실행법 — 실행 파일, 포트·주소, 확장 시 고칠 설정 파일, k3s 실측 절차, 되돌리는 법 |

## `validation/` — 검증·실험 계획

| 문서 | 무엇을 답하는가 |
|---|---|
| [validation/infra-mock-plan.md](validation/infra-mock-plan.md) | 실 인프라(MQTT/Kafka/K3s 등) 로컬 검증 범위와 하드웨어 mock 대체 계획 |
| [validation/framework-property-scenarios.md](validation/framework-property-scenarios.md) | `simulator/scenarios/`+`tests/test_scenarios.py`가 검증하는 프레임워크 특성 |
| [validation/demonstration-data-collection.md](validation/demonstration-data-collection.md) | 시연 실행이 어떻게 실험 데이터가 되는가(`observability/experiment.py`) |
| [validation/unified-hardware-mock-experiment-plan.md](validation/unified-hardware-mock-experiment-plan.md) | 실제 데이터·인프라와 동일 core를 사용한 하드웨어 mock 시나리오 실험 계획(종료, 결과는 `reports/`) |
| [validation/edge-step1-experiment-plan.md](validation/edge-step1-experiment-plan.md) | 엣지 Step 1(노드 위치·신원 발행) 실측 계획 — 카메라 높이/마커 크기·각도 스윕, RSSI 히스테리시스 재검증 (계획 단계, 미실행) |

## 다른 곳에 있는 것

| 대상 | 위치 |
|---|---|
| 이 PC(엣지+서버 겸용)의 네트워크·보안 운영 설정 — AI 프레임워크 설계가 아니라 이 장비의 운영 문서라 분리 | `docs/ops/` |
| KCI 확장 연구 — 재현 대상 논문·아이디어와 각 논문의 실제 활용처 | `docs/obsidian/` (특히 `docs/obsidian/papers/README.md`) |
| 파트 경계를 넘는 통신 규약(현재: 물리 명령 wire 규약) | `interface-spec/` |
| 하드웨어·백엔드·가시화 파트 연동 JSON Schema 계약 | `perception-framework/contracts/ai/` |
| 매일의 고민·실험·결과 개인 기록(git 미추적) | `reports/` |
| 작업 규약(Skill) | `.claude/skills/` |

재사용 계획이 없어 제거한 것: `experiments/`(설정·결과는 `reports/`로 문서화 후 코드 삭제),
`tools/`(1회성 환경 세팅 스크립트), `stubs/`(미사용 — 실제 쓰이던 부분은
`perception_framework/simulation/`으로 이식), `profiles/`+`examples/`(→ `simulator/`로 통합),
`docs/integration/`(1회성 공개 업로드 계획, 완료됨). 필요하면 Git 이력에서 확인한다.
