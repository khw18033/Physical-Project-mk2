# Physical Project mk2

센서, AI 모델, 연산 장치, 실행 위치와 전송 기술이 달라져도 핵심 로직을 수정하지 않고
확장·교체·축소 운용할 수 있도록 설계한 Physical AI 실행 프레임워크다. 현재 저장소는
`jny_AI` 브랜치 기준 AI·엣지 프레임워크와 다른 파트가 사용할 공통 계약을 포함한다.

이 프로젝트의 목표는 특정 모델 정확도나 특정 로봇 SDK에 최적화된 단일 애플리케이션이
아니다. 필수·선택 capability를 구분하고, 사용 가능한 provider와 자원에 따라 실행 구성을
선택하며, 일부 기능·노드·네트워크가 사라져도 가능한 기능을 계속 운용하는 것이 핵심이다.

## 핵심 원칙

- 인지·판단·위험 분석·실행관리 로직은 특정 센서, GPU/NPU, 모델, SDK, broker를 직접 알지 않는다.
- 새 기능과 장치는 adapter/provider 등록 및 배포 프로파일 추가로 연결한다.
- 선택 기능 장애는 관련 기능만 축소하며 로컬 안전 기능과 무관한 기능을 함께 중단하지 않는다.
- 업무·제어 데이터, metric/log/trace, 영상 픽셀을 서로 다른 데이터 평면으로 유지한다.
- 명령 전달 ACK와 실제 실행 완료·거부·실패 결과를 구분하고 감사 이력과 기술 trace도 분리한다.
- 공개 인터넷이 없는 환경에서도 내부 이미지·모델·패키지 저장소만으로 배포할 수 있어야 한다.

## 요구사항 요약

상세 정의는 [CLAUDE.md](CLAUDE.md), 구현·테스트 추적은
[요구사항 추적표](docs/ai/requirement-traceability.md)를 기준으로 한다.

| 구분 | ID | 수 | 요약 | 현재 상태 |
|---|---|---:|---|---|
| 온디바이스 | AI-N | 2 | 네트워크 독립 로컬 안전 판단, 환경·보정 설정 적용 | 완료 |
| 감시·인지 | AI-E | 4 | 인지 provider, 엣지 캘리브레이션, 보정 프로파일, 보조 AI | 완료 |
| 의사결정 | AI-D | 4 | 서브태스크 생성·검증·보조정보 요청·재생성 | 완료 |
| 상황 추적 | AI-S | 5 | 객체 추적, 다중 소스 연계, 불확실성, 미확인 객체, 정보 선택 | 완료 |
| 위험도 | AI-R | 4 | 상태기계, 점수화, 근거 포함 판단 결과, 입력 수준별 조정 | 완료 |
| 실행·배포 | AI-B | 11 | 호환성·자원 선택, lifecycle, 격리·롤백, 멀티클러스터 | 10 완료, AI-B-10 부분 |
| 관측 | AI-O | 4 | metric/event 분리, 재현 참조, 가용성 신호 | 완료 |
| 공통 기반 | AI-C | 17 | provider, Registry, 데이터 사전·평면, 프로파일, 폐쇄망·오버레이 | 완료 |

총 51개 중 **50개 완료, 1개 부분, 미착수 0개**다. 여기서 완료는 현재 브랜치의 코드와
자동화 테스트로 요구 동작과 경계를 검증했다는 의미다. AI-B-10의 실제 말단 성능·메모리·발열
검증과 AI-N-01의 최소 안전 처리주기 확정은 실물 하드웨어 측정이 추가로 필요하다.

## 활용 시나리오

- **이동형 로봇 안전**: 네트워크가 끊겨도 로컬 영상으로 접근 위험을 판단하고 입력 자체가
  사라지면 `SAFE_STOP`으로 전이한다.
- **시설·하천 감시**: 동일 Application과 provider 경계를 유지한 채 프로파일과 입력 adapter만
  바꿔 객체 감시, 시설 이상, 수위·강우 기반 기능을 구성한다.
- **센서·가속기 교체**: 새 카메라, CPU/OpenCL 런타임 또는 외부 AI 기능을 등록하고 호환 태그와
  자원 예산으로 실행 대상을 선택한다.
- **자원 부족·기능 장애**: 선택 기능을 우선 축소하고 자원이 회복되면 다시 구성한다. 한 provider의
  예외가 Registry 전체를 중단시키지 않는다.
- **구역 엣지·서버 운용**: 말단 MQTT와 서버 Kafka 사이를 엣지 Bridge로 연결하고 서버·엣지 K3s를
  동일 `ControlProvider` 계약 뒤에서 선택한다.
- **모델 갱신**: 내부 artifact를 다운로드·검증·활성화하고 실패하면 직전 정상 버전으로 롤백한 뒤
  결과를 공통 메시지로 보고한다.
- **디지털 트윈·관제 연동**: 탐지, 위험, AI 실패, 기능 상태와 계획 제안을 JSON Schema로 전달해
  영상 프레임과 오버레이를 정합하고 승인 전 계획이 실행 명령으로 오인되지 않게 한다.

## 아키텍처

```text
Perception / Decision / Risk / Local Safety
                    |
Capability + Profile + Registry + Selector
                    |
Provider Protocols
  Media | AI Runtime | Transport | Serializer | Control
  Observability | Network Overlay | Model Deployment
                    |
MQTT / Kafka / OTel / K3s / Tailscale / CPU·OpenCL / concrete adapters
                    |
contracts/ai JSON Schema + integration/wire.py
                    |
Hardware | Backend | Visualization
```

현재 배포 원칙은 말단↔엣지 업무·제어·하트비트에 MQTT, 엣지↔서버 업무·제어에 Kafka,
관측에 OpenTelemetry, 영상에 별도 미디어 경로를 사용하는 것이다. 이 기술들은 provider 구현이며
상위 AI 모듈의 필수 의존성이 아니다. 자세한 구조는 [AI 아키텍처](docs/ai/00-architecture.md)를
참고한다.

## 현재 구현

| 영역 | 구현 내용 |
|---|---|
| 계약 | capability·호환성·자원·배포 프로파일, 공통 데이터 사전, 좌표·시간·데이터 평면 |
| 실행 선택 | local/remote Registry, required/optional 평가, 최소 자원 선택, 단계적 축소·복구 |
| AI 흐름 | 탐지, 추적·연계·불확실성, 서브태스크 생성·검증, 위험 FSM·점수·결과 |
| 안전·설정 | 로컬 안전 fallback, 전체/delta 설정 적용, 카메라 캘리브레이션·프로파일 |
| 인프라 provider | MQTT, Kafka, OTel, K3s, CPU·OpenCL, Tailscale와 테스트용 fake |
| 배포 경계 | OCI 실행, lifecycle·rollback, 폐쇄망 자산 정책, 서버·엣지 멀티클러스터, 모델 배포 |
| 파트 간 계약 | AI message envelope와 payload JSON Schema 8종, 정상 예제 6종, Python wire adapter |
| 검증 | 단위·계약·시나리오·선택 인프라 테스트, 가상 로봇·하천·백엔드 mock |

현재 전체 회귀 결과는 **293 passed, 19 skipped**다. skip은 MQTT/Kafka/OTel/K3s/OpenCL 등
선택 의존성이나 외부 인프라가 없는 환경에서 해당 provider 테스트만 격리된 결과다.

## 제어 프로토콜 경계

현재 `ControlProvider`와 K3s 구현은 AI 실행 단위의 시작·중지·재시작·상태 조회를 추상화한다.
물리 로봇 명령은 AI의 위험 `recommendation`이나 `plan_proposal`과 동일하지 않으며, 백엔드 승인과
하드웨어 adapter를 거쳐야 한다. mk2의 물리 제어 계약을 통합할 때는 다음 속성을 유지한다.

- 명령은 상관 가능한 고유 ID, 논리 대상, 동작, 자유 형식 파라미터를 가진다.
- adapter는 지원하지 않는 명령을 무시하지 않고 최종 거부·실패 사유를 업무 결과로 회신한다.
- 전달 성공, 명령 수락, 물리 실행 완료를 같은 상태로 취급하지 않는다.
- 로봇별 SDK와 명령 번역은 하드웨어 adapter 내부에 두고 플랫폼·AI 핵심에서 분기하지 않는다.
- 상태·생존 신호·비동기 사건은 명령 결과와 구분하고 확장 telemetry는 pass-through할 수 있게 한다.

이 원칙은 실물 RoboMaster 이동·LED와 명령 ACK까지 검증된 mk1의 SDK 독립 제어 계약을
참고했다. 다만 mk1의 Redis 키나 특정 SDK를 mk2 공통 규격으로 복사하지 않았으며, 현재 배포의
MQTT/Kafka adapter 뒤에서 동일 의미를 보존하도록 설계한다. 물리 명령용 최종 JSON Schema는
하드웨어·백엔드 파트 합의가 필요한 통합 항목이다.

## 저장소 구조

```text
Physical-Project-mk2/
├── ai-framework/
│   ├── ai_framework/       # AI 프레임워크 Python 패키지
│   ├── profiles/           # robot/facility/river 배포 프로파일
│   ├── examples/           # 기능 및 통합 시나리오 데모
│   └── tests/              # 단위·계약·인프라·시나리오 테스트
├── contracts/ai/           # 파트 간 JSON Schema와 예제 payload
├── docs/ai/                # 아키텍처, 구현 계획, 요구사항 추적
├── docs/integration/       # 하드웨어·백엔드·가시화 병합 안내
├── reports/                # 작업 보고서와 프레임워크 지표
└── CLAUDE.md               # 51개 AI 요구사항 원문과 개발 규칙
```

세부 Python 패키지 구조는 [ai-framework/README.md](ai-framework/README.md)에서 확인할 수 있다.

## 설치와 테스트

Python 3.10 이상이 필요하다.

```bash
cd ai-framework
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e ".[dev]"

# 전체 회귀 테스트
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q

# 실행 가능한 데모
PYTHONPATH=. python3 examples/demo.py
PYTHONPATH=. python3 examples/scenario_demo.py

# 프레임워크 특성 시나리오만 실행
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q tests/scenarios
```

컨테이너 검증:

```bash
cd ai-framework
docker build -t ai-framework:0.1.0 .
docker run --rm ai-framework:0.1.0 python -m pytest -q
```

실 MQTT, Kafka, OTel Collector, K3s 검증 환경은
[인프라·mock 계획](docs/ai/02-infra-mock-plan.md)을 참고한다.

## 다른 파트와 통합

파트 경계의 단일 기준은 Python dataclass가 아니라 [공통 AI 계약](contracts/ai/README.md)이다.

1. 백엔드가 `contracts/ai/`를 먼저 반영하고 수신 검증·격리·라우팅을 구현한다.
2. 하드웨어가 프레임 참조와 모델 배포 결과, 로컬 안전·제어 경계를 연결한다.
3. 가시화가 동일 예제를 fixture로 사용해 TypeScript 타입과 bbox/frame/risk 변환을 맞춘다.
4. 영상 파일 또는 가상 장치로 E2E를 통과한 뒤 실물 장치 검증으로 승격한다.

파트별 상세 절차:

- [통합 준비 개요](docs/integration/README.md)
- [하드웨어 병합 가이드](docs/integration/hardware-merge-guide.md)
- [백엔드 병합 가이드](docs/integration/backend-merge-guide.md)
- [가시화 병합 가이드](docs/integration/visualization-merge-guide.md)

Google Sheet에 남아 있는 존재하지 않는 AI 요구사항 참조와 의미 불일치는
[통합 준비 개요](docs/integration/README.md#요구사항-표-정정-필요)에 기록했다. 해당 ID를 임의로
재사용하지 않고 담당자 합의 후 정정해야 한다.

## 남은 검증

- Raspberry Pi 등 실제 말단에서 처리주기, 메모리, 발열, thermal throttling 측정
- 실제 렌즈·조명·카메라 조건의 캘리브레이션 및 인지 품질 검증
- 백엔드 업무·관측 상태를 결합한 최종 장치 가용성 API 연결
- 하드웨어·백엔드 합의에 따른 물리 명령·최종 실행 결과 공통 Schema 확정
- 다른 파트 브랜치 반영 후 frame/bbox/risk/plan/model deployment E2E 검증

## 참고 프로젝트

- [fleet_mission-dashboard](https://github.com/JNY03/fleet_mission-dashboard): mk1 플랫폼·로봇 adapter와
  SDK 독립 제어 프로토콜. `main`은 일부 실물 하드웨어·도구 검증 기록을 포함하며
  [vision 브랜치](https://github.com/JNY03/fleet_mission-dashboard/tree/vision)는 프레임 수집,
  추론 결과와 시각화 스트림 분리, 제한된 로컬 버퍼 실험을 참고할 수 있다.
- [come-capstone26-physicalAI](https://github.com/HBNU-SWUNIV/come-capstone26-physicalAI):
  로봇·서버·Unity/VR 3단 구조, 구역 핸드오프, 디지털 트윈 활용 시나리오 등 프로젝트 초기
  설계와 시도 기록.

참고 저장소는 설계 근거이며 이 저장소의 런타임 의존성이나 vendored source가 아니다.

## 공개 저장소 보안

- 실제 `.env`, `config.yaml`, 토큰, 비밀번호, 개인키, 인증서와 내부망 endpoint를 커밋하지 않는다.
- 예제 설정에는 placeholder만 사용하고 운영 값은 환경변수나 별도 secret manager로 주입한다.
- 모델·영상·재현 데이터에는 개인정보, 위치정보, 비공개 시설 정보가 없는지 별도로 확인한다.
- 공개 푸시 전 staged diff와 비밀정보 패턴 검사를 수행한다.
