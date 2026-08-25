# 2026-08-25 AI 프레임워크 공통 골격 구현

담당: 진나영 (AI-N/E/D/S/R/B/O/C 48개 요구사항 전담)

## 배경

레포가 `CLAUDE.md` 요구사항 문서 외에는 비어 있는 상태였다. 문서상 48개 요구사항 전부가
담당자로 명시되어 있어, 한 번에 전체를 프로덕션 수준으로 구현하는 대신 §6 구현 순서를
따라 공통 경계부터 세우기로 사용자와 합의했다.

## 이번 단계에서 한 일

1. `ai-framework/` 파이썬 패키지 신설 (`pip install -e ".[dev]"` + pytest).
2. Capability 계약 (`CapabilityState`, `CapabilityRequirement`) — required/optional 구분,
   optional 누락은 DEGRADED, required 누락만 DISABLED로 평가 (AI-C-05, AI-C-11).
3. 실행 호환성·자원·배포 프로파일 (`CompatibilityProfile`, `ResourceBudget`,
   `DeploymentProfile`) — 하드웨어/런타임은 문자열 태그로만 표현, 도메인은 데이터로만
   구분 (AI-B-01, AI-C-13, AI-C-15).
4. 6종 provider Protocol (Transport/Serializer/Media/Runtime/Control/Observability) —
   상위 코드가 MQTT/Kafka/OTel/K3s 등 구체 기술을 직접 참조하지 않도록 경계 정의
   (AI-C-04/06/07/08/12, AI-B-03/08).
5. `CapabilityRegistry` — local 등록과 remote 스냅샷을 분리해, 중앙 레지스트리가 일시
   불통이어도 마지막 스냅샷으로 계속 서비스하도록 구현 (AI-C-10). health_check 예외를
   흡수해 한 provider 장애가 레지스트리 전체를 죽이지 않도록 함 (AI-B-07).
6. `CapabilitySelector` — 호환성 필터 + 최소비용 우선순위 선택 + capability kind 목록을
   따라 내려가는 단계적 축소(`select_with_degrade`) (AI-B-04, AI-B-06, AI-C-13).
7. `LocalSafetyJudge` (AI-N-01 수직 슬라이스) — 위 패턴을 실제로 관통 구현: 인지/추적/
   거리추정 중 무엇이 빠져도 판단 수준만 낮추고, 영상 입력이 사라지는 순간에만 사전 정의된
   `SAFE_STOP`으로 전이.
8. 테스트 18개 (registry 7, selector 6, local safety 5) — 모두 "정상 경로보다 먼저 실패
   경로"를 검증하는 방식으로 작성 (§6-7: 선택 기능 부재·장애·자원 부족을 우선 명시).
9. `docs/ai/00-architecture.md`, `docs/ai/requirement-traceability.md` — 48개 ID 전체에
   대해 완료/부분/미착수 상태를 기록 (§7 추적 규칙).

## 검증

```
cd ai-framework && pytest -q
18 passed
```

## 다음 단계 (미착수 29개, 부분구현 12개)

- 인지(AI-E-01~04), 추적(AI-S-01~05), 의사결정(AI-D-01~04), 위험도(AI-R-01~04) 등
  실제 업무 로직은 이번 골격 위에 순차 구현 필요.
- Provider Protocol에 대응하는 실제 MQTT/Kafka/RTSP 등 구현체는 아직 없음 — 현재는
  인터페이스 경계만 존재.
- 공통 데이터 사전 기반 변수명 통일(AI-C-01)은 §6-8 순서상 전체 기능 구현 후 진행 예정.

추가 요구사항 필요 사항 없음 — 문서에 정의된 범위 내에서만 구현함.
