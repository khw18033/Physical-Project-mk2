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
                  # profile_loader: 도메인 프로파일 파일 로더 (AI-C-15)
  common/         # 좌표계/프레임참조·시간/데이터평면 공통 규약 (AI-C-02, AI-C-03, AI-C-14)
  providers/      # Transport/Serializer/Media/Runtime/Control/Observability Protocol + fake impl (AI-C-04/06/07/08/09/12, AI-B-08)
                  # mqtt/kafka: 실 전송 provider, otel: 실 OTLP 관측, k3s: 오케스트레이터 제어
                  # compute: CPU·OpenCL 런타임 (벤더 비종속 실증)
  registry/       # CapabilityRegistry: local + remote-snapshot provider bookkeeping (AI-C-10, AI-B-07)
  selection/      # CapabilitySelector: 호환성 필터 + 최소자원 선택 + 단계적 축소 (AI-B-01/04/06, AI-C-13)
  reference/      # LocalSafetyJudge: AI-N-01
  decision/       # 서브태스크 생성/검증/재생성 + 보조정보 요청 (AI-D-01/02/03/04)
  perception/     # 추적/연계/불확실성/미확인객체/추가정보선택/인지/보조기능 (AI-S-01~05, AI-E-01/04)
  risk/           # 위험분석 FSM/점수/출력/수준조정 (AI-R-01~04)
  execution/      # 실행제어/lifecycle/conformance (AI-B-03/05/09)
  observability/  # metric/event/재현정보/가용성 신호 (AI-O-01~04)
  edge/           # 카메라 캘리브레이션/프로파일 + 말단↔서버 양방향 Bridge (AI-E-02/03, AI-C-06)
  runtime/        # 도메인 무관 애플리케이션 조립 + 자원 기반 재구성 (AI-C-05/13/15, AI-B-06)
  simulation/     # 가상 말단·replay 소스·백엔드 mock — 하드웨어 없이 시나리오 검증 (AI-B-09)
  ondevice/       # 환경·보정 설정 적용 (AI-N-02)
```

전체 구현 상태는 [docs/ai/requirement-traceability.md](../docs/ai/requirement-traceability.md)
참고 (48개 중 46개 완료, 1개 부분). 실 인프라 승격·하드웨어 mock 계획은
[docs/ai/02-infra-mock-plan.md](../docs/ai/02-infra-mock-plan.md) 참고.

## 실행

```bash
pip install -e ".[dev]"                    # 선택 extra: mqtt / kafka / otel
pytest -q                                  # 249 passed, 6 skipped (인프라 기동 시)
# 시스템 pytest 플러그인 충돌 시:
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
PYTHONPATH=. python3 examples/demo.py            # 기능별 데모
PYTHONPATH=. python3 examples/scenario_demo.py   # 13단계 최종 데모
pytest -q tests/scenarios                        # 프레임워크 특성 시나리오 15종
```

시나리오·지표 설명은
[docs/ai/03-framework-property-scenarios.md](../docs/ai/03-framework-property-scenarios.md),
산출 지표는 [reports/framework-indicators.json](../reports/framework-indicators.json).

컨테이너로도 동일하게 동작한다 (AI-B-02):

```bash
docker build -t ai-framework:0.1.0 .
docker run --rm ai-framework:0.1.0 python -m pytest -q   # 230 passed, 25 skipped
```

선택 의존성·인프라(paho-mqtt, Kafka, OTel Collector, K3s, OpenCL 플랫폼)가 없으면 **해당
테스트만 skip되고 나머지는 통과**한다. 두 실행 결과의 차이가 곧 선택 기능 격리(AI-C-11)의
증거다. 인프라 기동 방법은 [docs/ai/02-infra-mock-plan.md](../docs/ai/02-infra-mock-plan.md) §3.
NVIDIA 드라이버·GPU가 없는 노드에서 전체 스위트가 통과하는 것이 벤더 비종속성(원칙 #1)의
회귀 시험이다.
