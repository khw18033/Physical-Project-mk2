# 프레임워크 특성 검증 시나리오 (하드웨어 없이 실행)

이 문서는 "AI 모델이 얼마나 정확한가"가 아니라 **"범용 프레임워크가 하드웨어·기능·실행환경
변화에 견디는가"**를 검증하는 시나리오 세트를 정의하고, 각 시나리오가 어디에 구현돼 있는지
기록한다.

검증 질문은 다섯 개다.

| # | 질문 | 주요 요구사항 |
|---|---|---|
| ① | 새로운 것을 꽂아도 핵심 코드를 안 고치는가? | AI-B-09, AI-C-04/10/12/15 |
| ② | 일부 기능이 없어져도 나머지가 계속 도는가? | AI-C-05/11, AI-B-07 |
| ③ | 실행 환경이 바뀌면 자동으로 재구성되는가? | AI-B-01/04/06, AI-C-13 |
| ④ | 로봇·감시·하천이 동일 프레임워크로 돌아가는가? | AI-C-15 |
| ⑤ | 전송·관측·제어 계층이 서로 섞이지 않는가? | AI-C-06/14, AI-O-04 |

## 1. 테스트 환경 (실제 장치 0대)

```text
┌───────────────── Server ─────────────────┐
│ Backend Mock  (simulation/backend.py)     │  ← 가용성 통합 판정만 대행
│ Kafka         (docker apache/kafka)       │
│ OTel Collector(docker otel-collector)     │
└──────────────────▲────────────────────────┘
                   │ Kafka
┌──────────────── Edge ────────────────────┐
│ MQTT Broker   (docker mosquitto)          │
│ MQTT↔Kafka Bridge (edge/bridge.py)        │
│ K3s           (기존 클러스터)              │
│ Capability Registry / ZoneApplication     │
└──────────────────▲────────────────────────┘
                   │ MQTT
      ┌────────────┴────────────┐
 virtual_robot_01         virtual_river_01
 (카메라 replay,          (수위·강우 CSV/스크립트 replay,
  배터리·위치 mock,        차수벽 액추에이터 시뮬레이터)
  액추에이터 시뮬레이터)
```

가상 말단은 `perception_framework/simulation/terminals.py`의 `VirtualRobotTerminal` /
`VirtualRiverTerminal`이고, 입력은 CSV·스크립트 시계열(`sources.py::ScriptedSeriesSource`,
`CsvReplaySource`)과 합성 영상 파일(`write_synthetic_video`, `VideoFileMediaSource`)이다.

**중요**: `simulation/` 아래 모듈은 전부 adapter/provider 구현이며, 배포에서 통째로 지워도
핵심 코드는 영향받지 않는다. 백엔드 가용성 판정 규칙을 여기에 둔 것도 의도적이다 —
원칙 #15에 따라 그 판정은 AI 핵심이 아니라 백엔드 책임이기 때문이다.

## 2. 시나리오 구현 위치

**(2026-09 갱신)** S1~S4, S12~S13은 registry/profile/자원재구성만 다뤄 데이터로 표현하기
자연스러웠기 때문에 `simulator/scenarios/*.json`(하드웨어 없이 실행하는 시뮬레이터 입력이자
`tests/test_scenarios.py`의 자동 검증 입력)으로 옮겼다. 실 MQTT/Kafka 브로커, 카메라 보정
파일, 명령 supervisor SQLite 상태가 필요한 나머지는 여전히 개별 pytest 파일로 남아 있다 —
그 이유는 `simulator/README.md` "이 시스템이 다루는 범위" 참고.

**(2026-09, 추가 갱신)** 시뮬레이터 자체를 DEVS 엔진(pyjevsim)으로 재설계했다 — 시나리오는
더 이상 평평한 이벤트 리스트가 아니라 실제 시뮬레이션 시간 축을 가진 노드 토폴로지다
(`simulator/devs/README.md`). 이 덕분에 물리 명령 lifecycle처럼 "장치가 accept하는 데
시간이 걸리고, 그 사이 취소가 도착하면 완료보다 우선한다" 같은 **시간 의존 경쟁 조건**을
처음으로 시나리오로 표현할 수 있게 됐다 — `physical-command-{success,rejection,cancel}.json`
(신규, `simulator/devs/physical_command_device.py`가 interface-spec 장치측 lifecycle을
흉내낸다). `execution/physical_command_gateway.py`의 기존 pytest(`tests/
test_physical_command_gateway.py`)는 in-memory 즉시응답 fake라 이 시간 의존 경로를
표현하지 못했었다 — 두 검증은 서로 대체가 아니라 보완 관계다.

| # | 시나리오 | 구현 | 비고 |
|---|---|---|---|
| S1 | 새 센서 Hot Plug | `simulator/scenarios/s01-hotplug-*.json` | 실행 중 등록만으로 활성화, conformance 통과, core 언급 0 |
| S2 | 실행 노드 환경 변경 | `simulator/scenarios/s02-*.json` | CPU 노드/가속기 노드에서 동일 요청, 태그만 바꿔 provider 전환 |
| S3 | Edge CPU 포화 | `simulator/scenarios/s03-resource-shedding.json` | 축소 → 복구, 핵심 유지, 극단 포화 시 은폐 없이 DISABLED 보고 |
| S4 | 선택 Provider 강제 종료 | `simulator/scenarios/s04-failure-isolation.json` | 의존 기능만 DISABLED, 자기 health probe가 죽어도 격리 |
| S5 | 말단↔엣지 네트워크 단절 | `tests/test_partition_and_multizone.py` | 원격 기능만 비활성, 로컬 안전은 계속 |
| S14 | 엣지 1대 완전 장애 | 동일 파일 | Zone A/C 무영향 |
| S6 | 업무/관측 평면 불일치 | `tests/test_data_planes_and_backend_mock.py` | metric만 죽으면 AVAILABLE, 업무 세션 끊기면 UNAVAILABLE |
| S7 | 데이터 경로 분리 | 동일 파일 | 4종 데이터가 4개 경로로, wrong-plane 0건 |
| S8 | 명령 E2E 성공 | `tests/test_legacy_terminal_command_e2e.py` | fake 스택 + 실제 Kafka·MQTT 스택 양쪽(`simulation/terminals.py` 경로 — AI-C-20 물리 명령의 새 MQTT gateway 경로는 `tests/test_physical_command_gateway.py` 별도) |
| S9 | 명령 거부 | 동일 파일 | 전송 성공 ≠ 실행 성공, 사유는 업무 데이터 |
| 신규 | 물리 명령 성공/거부/취소(시간축 포함) | `simulator/scenarios/physical-command-*.json` | accept_delay·exec_time 실제 지연, 취소가 완료보다 우선(AI-C-20) |
| S10 | 전체/Delta 구성 갱신 | `tests/test_config_and_calibration.py` | delta만 반영, 검증 실패 시 이전 버전 유지 |
| S11 | 새 카메라 자동 캘리브레이션 | 동일 파일 | 불안정하면 미배포 + 영상좌표 인지 유지 |
| S12 | Robot → River 전환 | `simulator/scenarios/domain-robot.json`, `domain-river.json` | 같은 스키마, `profile` 필드만 다름 |
| S13 | 감시 도메인 사후 추가 | `simulator/scenarios/domain-new-surveillance.json` | 시나리오 파일 하나만 추가 |
| S15 | Kafka 재난 Burst | `tests/test_burst_delivery.py` | 소비자 그룹별 독립 소비, 발행이 소비 속도에 묶이지 않음 |
| S16 | 폐쇄망 배치 | `tests/test_airgap.py` | 내부 자산만으로 배치, 선택 외부 의존성만 비활성화 |
| S17 | 보안 오버레이 단절 | `tests/test_overlay_and_clusters.py` | 원격 기능만 축소, 업무·관측 장애와 별도 사유 유지 |
| S18 | 서버·엣지 멀티클러스터 | `tests/test_overlay_and_clusters.py` | 동일 제어 계약으로 배치, 한쪽 제어면 장애 격리 |
| 지표 | §18 지표 산출 | `tests/test_framework_indicators.py` | `reports/framework-indicators.json` 생성 |
| 모듈 단위 통합 확인 | registry/selector/물리명령 계약·gateway/risk FSM/tracking/공통 계약 등 | `tests/test_integration_functional_check.py` | 이름 붙은 개별 check 목록, 실패 시 어떤 check인지 출력에 그대로 드러남 |

## 3. 실행 방법

```bash
cd perception-framework
pip install -e ".[sim]"   # 최초 1회 — simulator/가 쓰는 pyjevsim(DEVS 엔진)

# 시나리오 관점만 (인프라 없으면 관련 항목 자동 skip)
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q \
  tests/test_scenarios.py tests/test_integration_functional_check.py \
  tests/test_airgap.py tests/test_overlay_and_clusters.py

# 시뮬레이터 (하드웨어 없이 프레임워크 성질 확인)
PYTHONPATH=. python3 simulator/simulation.py
```

인프라(mosquitto/Kafka/OTel/K3s) 기동 명령은 `infra-mock-plan.md` §3 참고.

## 4. 결과 지표

`reports/framework-indicators.json`이 테스트 실행 시 갱신된다. 현재 값:

| 지표 | 값 | 의미 |
|---|---|---|
| 새 카메라·센서·AI provider·전송 provider·도메인 추가 시 core LOC 변경 | **0** (5종 전부) | 확장은 등록·설정으로만 이뤄진다 |
| 선택 provider 1개 소실 시 영향 기능 | **1 / 6** | 장애가 의존 기능에만 국한 |
| 자원 포화 시 실행 기능 | 6 → 2 → (회복) 6 | 축소·복구가 자동 |
| 포화 중 핵심 기능 유지 | **true** | |
| 잘못된 평면 라우팅 | **0건** (11개 데이터 종류 전수) | 영상→MQTT, metric→Kafka 같은 사고 없음 |
| 동일 Application 클래스로 구동되는 도메인 | **5개** | robot / facility / river / defense / new-surveillance |
| 상태 전이 지연 | < 1 ms | 재구성 자체가 병목이 아님 |

지표는 "0 LOC"처럼 주장하기 쉬운 값을 **정적 토큰 검사로 강제**한다. 핵심 코드(perception,
decision, risk, runtime, execution, registry, selection, contracts)의 실행 토큰에 장치명·
도메인명·벤더명이 등장하면 테스트가 즉시 실패한다. 주석·docstring의 예시 언급은 허용된다.

## 5. 이 시나리오들이 실제로 잡아낸 결함

시나리오는 통과 도장이 아니라 **결함 검출기**로 동작했다. 지금까지 3건:

1. **Bridge 무한 루프** — 양쪽 전송이 자기가 publish하는 토픽을 구독하므로 전달한 메시지를
   되받아 무한 전달. 실제 브로커에서도 동일하게 발생하는 구조적 결함이었다.
   → payload 지문 기반 echo 억제 + 회귀 테스트.
2. **Kafka `is_connected()` 오판** — 메타데이터 캐시 후 bootstrap 소켓이 닫히면 False를
   반환해, 이를 게이트로 쓰던 bridge가 uplink를 전부 `server_link_down`으로 폐기했다.
   → 마지막 성공 상태를 fallback으로 사용 + 회귀 테스트.
3. **핵심 기능 미배치 상태에서 선택 기능이 자원 점유** — 자원이 부족해 core perception이
   배치되지 못했는데 optional tracking이 남은 여유로 계속 실행됐다. "핵심 기능은 유지"의
   취지에 반한다. → core 미배치 시 optional은 `core_capability_unplaced`로 중단하고 여유를
   핵심 기능 복구용으로 남긴다.

## 6. 아직 하드웨어가 필요한 항목

| 항목 | 왜 |
|---|---|
| AI-N-01 최소 처리주기 확정 | 요구사항이 실측 시험으로 정하도록 규정 |
| 실제 렌즈·조명 하의 인지 성능 | 합성 프레임은 계약만 증명 |
| 발열·thermal throttling | 부하 주입은 흉내일 뿐 |
| 가속기 자원 프로파일 수치 | 해당 하드웨어에서 측정 필요 |
| AI-B-10 말단 실물 검증 | 실제 보드 성능·메모리 |
| AI-C-10 백엔드 실연동 | 현재는 `simulation/backend.py` mock |

## 7. 추가 요구사항 필요 여부

없음. 시나리오는 기존 요구사항 ID의 검증 방법이며 새 기능이 아니다. 단
`runtime/application.py`(도메인 무관 조립)와 `runtime/reconfiguration.py`(자원 기반 재구성
루프)는 AI-B-06/AI-C-05/AI-C-13/AI-C-15가 요구하는 동작을 실행 가능한 형태로 모으기 위해
새로 추가한 모듈이다. 기존 인터페이스만 조합하며 새로운 개념을 도입하지 않는다.
