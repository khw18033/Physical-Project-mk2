# 파트 통합 준비 개요

이 문서는 `jny_AI` 브랜치에서 준비한 공통 계약을 다른 파트가 자기 브랜치에 반영할 때의
기준이다. 이 작업에서는 다른 브랜치를 checkout, merge, rebase, cherry-pick하지 않았다.

## 준비된 산출물

- `contracts/ai/*.schema.json`: 언어 중립 JSON Schema 8종
- `contracts/ai/examples/*.json`: 정상 메시지 예제 6종
- `ai-framework/ai_framework/integration/wire.py`: AI 도메인 객체의 공통 메시지 변환기
- `ai-framework/ai_framework/runtime/model_deployment.py`: 모델 적용·검증·롤백 lifecycle
- `ai-framework/tests/test_integration_contract_schemas.py`: Schema·예제 회귀 검증
- `ai-framework/tests/test_wire_integration.py`: AI 출력 변환 검증
- `ai-framework/tests/test_model_deployment.py`: HW-R-10 lifecycle 검증

계약 버전은 `1.0`이다. MQTT/Kafka topic, WebSocket URL, 저장소 제품, 모델 파일 형식은
계약에 포함하지 않는다. 이 값들은 각 배포 adapter가 결정한다.

## 적용 순서

1. AI 변경을 계약·어댑터·문서 단위의 작은 커밋으로 확정한다.
2. 백엔드가 `contracts/ai/`를 먼저 반영하고 수신 검증·라우팅을 구현한다.
3. 하드웨어가 프레임 참조와 모델 적용 결과 계약을 반영한다.
4. 가시화가 동일 예제를 사용해 TypeScript 수신 타입과 화면 변환을 맞춘다.
5. 마지막에 영상 파일/가상 장치 기반 E2E를 실행한다.

각 파트는 AI 내부 Python dataclass를 직접 import하거나 복사하지 않는다. 파트 경계의 기준은
오직 `contracts/ai/message.schema.json`과 payload Schema다.

## 브랜치 적용 원칙

- 공통 계약 커밋을 먼저 반영하고 파트별 구현 커밋은 그 다음에 둔다.
- 현재 remote ref 기준 `jny_AI`와 `khw_VZ`의 공통 변경 파일은 `.gitignore`뿐이다.
- `.gitignore` 충돌 시 Python 항목과 Node/Unity 항목을 합집합으로 유지한다.
- `origin/HW`는 현재 `origin/main`과 동일하므로 공개된 하드웨어 구현 충돌은 확인되지 않았다.
- 병합 전 각 파트의 미커밋 변경을 보존하고, 깨끗한 통합 브랜치에서 검증한다.

## 요구사항 표 정정 필요

코드 병합과 별도로 요구사항 정의서의 다음 참조는 담당자 합의 후 수정해야 한다.

| 원본 행 | 현재 참조 | 문제 |
|---|---|---|
| `HW-R-04` | `AI-P-01` | 존재하지 않는 ID |
| `BE-S-04` | `AI-L-01` | 존재하지 않는 ID |
| `VZ-U-06` | `AI-L-01`, `AI-L-02` | 존재하지 않는 ID |
| `HW-R-04`, `HW-R-10` | `AI-R-03` 모델 배포 설명 | 실제 AI-R-03은 위험 판단 결과 출력 |
| `BE-X-06` | `AI-B-02` 프로세스 활성화 설명 | 실제 AI-B-02는 실행환경 패키징 |

의도 해석과 지속학습은 현재 AI 요구사항 51개에 담당 기능이 없다. ID를 임의 재사용하지 말고
범위에 포함할지 먼저 결정한 뒤 새 요구사항으로 추가한다.

## 파트별 문서

- [하드웨어 병합 안내](hardware-merge-guide.md)
- [백엔드 병합 안내](backend-merge-guide.md)
- [가시화 병합 안내](visualization-merge-guide.md)
