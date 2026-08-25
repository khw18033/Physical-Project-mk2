# ai-framework

CLAUDE.md 요구사항(AI-N/E/D/S/R/B/O/C, 48개, 담당: 진나영)을 구현하는 온디바이스·엣지 AI
실행 프레임워크. 특정 센서·모델·런타임·전송 프로토콜을 핵심 코드에 하드코딩하지 않고,
Capability/Provider 인터페이스와 Registry, 실행 호환성·자원·배포 프로파일을 통해
교체·축소·확장 가능한 구조를 지향한다.

이번 단계 범위와 전체 요구사항 대비 구현 상태는
[docs/ai/requirement-traceability.md](../docs/ai/requirement-traceability.md) 참고.
구조 설명은 [docs/ai/00-architecture.md](../docs/ai/00-architecture.md) 참고.

## 구조

```text
ai_framework/
  contracts/      # Capability, CapabilityRequirement, CapabilityState (AI-C-05, AI-C-11)
                  # CompatibilityProfile, ResourceBudget, DeploymentProfile (AI-B-01, AI-C-13, AI-C-15)
  providers/      # Transport/Serializer/Media/Runtime/Control/Observability Protocol + fake impl (AI-C-04/06/07/08/09/12, AI-B-08)
  registry/       # CapabilityRegistry: local + remote-snapshot provider bookkeeping (AI-C-10, AI-B-07)
  selection/      # CapabilitySelector: 호환성 필터 + 최소자원 선택 + 단계적 축소 (AI-B-01/04/06, AI-C-13)
  reference/      # LocalSafetyJudge: AI-N-01
  decision/       # 서브태스크 생성/검증/재생성 (AI-D-01/02/04)
  perception/     # 추적/연계/불확실성/미확인객체/추가정보선택/인지/보조기능 (AI-S-01~05, AI-E-01/04)
  risk/           # 위험분석 FSM/점수/출력/수준조정 (AI-R-01~04)
  execution/      # 실행제어/lifecycle/conformance (AI-B-03/05/09)
  observability/  # metric/event/재현정보/가용성 신호 (AI-O-01~04)
  edge/           # 카메라 캘리브레이션/프로파일 (AI-E-02/03)
  ondevice/       # 환경·보정 설정 적용 (AI-N-02)
```

전체 구현 상태는 [docs/ai/requirement-traceability.md](../docs/ai/requirement-traceability.md)
참고 (48개 중 40개 완료).

## 실행

```bash
pip install -e ".[dev]"
pytest -q   # 110 passed
```
