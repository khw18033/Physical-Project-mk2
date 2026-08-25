# 프레임워크 특성 검증 시나리오 구현 보고

- 일시: 2026-08-25
- 범위: 하드웨어 없이 실행 가능한 15개 시나리오 + §18 지표 산출 + 13단계 최종 데모
- 결과: 시나리오 62건 통과, 전체 249 passed / 6 skipped

## 1. 새로 만든 것

### 실행 조립 계층 (`ai_framework/runtime/`)

- `application.py::ZoneApplication` — `DeploymentProfile` + `CapabilityRegistry`를 받아
  활성 capability의 ACTIVE/DEGRADED/DISABLED와 담당 provider를 결정한다. 도메인 이름도,
  센서 이름도, 프로토콜 이름도 등장하지 않는다. **로봇·감시·하천이 같은 클래스로 도는
  지점이 여기다.**
- `reconfiguration.py::ResourceAdaptiveReconfigurer` — 관측된 자원 스냅샷을 예산으로 바꿔
  재해결하고, 상태 전이를 개별 사건으로 보고한다(AI-O-02). 지표(축소/복구 횟수, 전이 지연)도
  여기서 나온다.

### 가상 말단 (`ai_framework/simulation/`)

- `terminals.py` — `VirtualRobotTerminal`(카메라 replay·배터리·위치·액추에이터),
  `VirtualRiverTerminal`(수위·강우 replay·차수벽). 명령은 RECEIVED → SUCCESS/REJECTED/FAILED로
  회신하며, 사전조건 위반은 **거부**로 표현된다(전송 실패와 구분).
- `sources.py` — 스크립트/CSV 시계열, 합성 mp4 생성 및 `VideoFileMediaSource`.
- `backend.py` — **백엔드의** 가용성 통합 판정 mock. 원칙 #15에 따라 이 규칙은 AI 핵심이
  아니라 백엔드 책임이므로 의도적으로 `simulation/` 아래에 뒀다.

### 시나리오 테스트 (`tests/scenarios/`, 62건)

S1·S2(hot plug·노드 변경), S3·S4(자원 포화·provider 장애), S5·S14(단절·엣지 장애),
S6·S7(평면 불일치·경로 분리), S8·S9(명령 성공·거부), S10·S11(구성 delta·캘리브레이션),
S12·S13(도메인 전환·사후 추가), S15(Kafka burst), 그리고 지표 산출.

### 최종 데모 (`examples/scenario_demo.py`)

Robot 프로파일 기동 → 가상 로봇·카메라 등록 → 기능 탐색 → 경로 분리 확인 → provider 강제
종료 → CPU 포화 → 새 카메라 동적 추가 → River 프로파일 전환 → 수위 센서 등록 → 위험 FSM →
가용성 판정·제어 명령 → core LOC 0 확인, 13단계.

## 2. 지표 (`reports/framework-indicators.json`, 테스트가 자동 갱신)

| 지표 | 값 |
|---|---|
| 새 카메라 / 센서 / AI provider / 전송 provider / 도메인 추가 시 core LOC 변경 | **0** (5종 전부) |
| 선택 provider 1개 소실 시 영향 기능 수 | **1 / 6** |
| 자원 포화 → 회복 시 실행 기능 수 | 6 → 2 → 6 |
| 포화 중 핵심 기능 유지 | true |
| 잘못된 평면 라우팅 건수 (11종 데이터 전수 검사) | **0** |
| 동일 Application 클래스로 구동되는 도메인 | 3 |
| 상태 전이 지연 | < 1 ms |

"0 LOC"는 주장이 아니라 **정적 토큰 검사로 강제**된다. 핵심 디렉터리(perception, decision,
risk, runtime, execution, registry, selection, contracts)의 실행 토큰에 장치명·도메인명·
벤더명이 나타나면 테스트가 실패한다. 주석·docstring의 예시 언급은 허용한다.

## 3. 시나리오가 잡아낸 실제 결함 3건

시나리오는 통과 도장이 아니라 결함 검출기로 동작했다.

1. **Bridge 무한 루프** — 양쪽 전송이 자기가 publish하는 토픽을 구독하므로 전달한 메시지를
   되받아 무한 전달했다. 실제 브로커에서도 동일하게 터지는 구조적 결함.
   → payload 지문 기반 echo 억제 + 회귀 테스트 2건.
2. **Kafka `is_connected()` 오판** — 메타데이터 캐시 후 bootstrap 소켓이 닫히면 False가 되어,
   이를 게이트로 쓰던 bridge가 uplink를 전부 `server_link_down`으로 폐기했다. 실 브로커
   E2E 시나리오가 아니었으면 발견되지 않았을 것이다. → 마지막 성공 상태 fallback + 회귀 테스트.
3. **핵심 기능 미배치 중 선택 기능이 자원 점유** — 자원 부족으로 core perception이 배치되지
   못했는데 optional tracking이 남은 여유로 계속 실행됐다. "핵심 기능은 유지"(AI-B-06)의
   취지에 반한다. → core 미배치 시 optional을 `core_capability_unplaced`로 중단하고 여유를
   핵심 기능 복구용으로 남긴다.

## 4. 검증 결과

```
호스트(인프라 기동)      : 249 passed,  6 skipped
최소 컨테이너            : 230 passed, 25 skipped
시나리오만               :  62 passed  (약 21초)
```

호스트 skip 6건 = OpenCL 플랫폼 1 + K3s API 재기동 중 5. 컨테이너 skip 25건 = 선택
의존성·인프라 전부 부재. **두 숫자의 차이 자체가 AI-C-11(선택 기능 격리)의 증거다.**

## 5. 남은 항목

여전히 실물이 필요한 것: AI-N-01 최소 처리주기 실측, 실제 렌즈·조명 하의 인지 성능,
thermal throttling, 가속기 자원 프로파일 수치, AI-B-10 말단 실물 검증, AI-C-10 백엔드 실연동
(현재는 mock 대역).

다음 작업 후보는 **AI-C-01 공통 데이터 사전 통일**이다. §6-8이 요구한 "전체 기능 구현 후"
조건이 이제 충족됐고, 시나리오가 생산자·소비자 관계를 실제 코드로 드러내 준 상태라 통일
작업의 근거 자료가 갖춰졌다.

## 6. 추가 요구사항 필요 여부

없음. 다만 `runtime/application.py`와 `runtime/reconfiguration.py`는 기존 요구사항
(AI-B-06, AI-C-05/13/15)이 요구하는 동작을 실행 가능한 형태로 모으기 위해 새로 추가한
모듈임을 기록해 둔다. 기존 인터페이스만 조합하며 새 개념을 도입하지 않는다.
