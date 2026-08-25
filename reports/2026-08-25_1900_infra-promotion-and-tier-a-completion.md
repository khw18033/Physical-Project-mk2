# 실 인프라 승격 + 잔여 Tier A 구현 보고

- 일시: 2026-08-25
- 범위: `docs/ai/02-infra-mock-plan.md` §3 권장 순서 1~3단계 + §4-4 가속기 검증 시나리오
- 결과: 요구사항 충족 **40/48 → 46/48**

## 1. 구현 내역

### 잔여 Tier A 4건 (인프라 불필요)

| ID | 모듈 | 핵심 결정 |
|---|---|---|
| AI-C-02 | `common/coordinates.py` | 영상 좌표는 보정 프로파일이 **있을 때만** 카메라 로컬로 승격. 전역 변환은 `NotImplementedError`로 명시적 차단 — AI 안에서 전역 좌표를 만들려는 시도가 즉시 드러남 |
| AI-C-03 | `common/timing.py` | 벽시계(`observed_at`)와 노드 로컬 순번(`local_sequence`)을 분리. 시계가 뒤로 점프해도 로컬 순서 불변, 노드 간 정합만 DEGRADED |
| AI-C-14 | `common/data_plane.py` | 업무/관측/미디어 평면 + 제어 데이터 전용 정책(전달보장·순서·결과회신·감사). 영상 픽셀의 업무·관측 평면 진입은 `DataPlaneViolation`으로 거부 |
| AI-D-03 | `decision/info_request.py` | AI-D-02의 `missing_evidence`를 입력받아, **등록된 정보원만** 요청하고 없으면 `unresolved`로 명시. 예외 아님 |

### 갭 수정 2건

- **AI-B-04**: `preferred_hw_tags`가 선언만 되고 선택에 반영되지 않던 문제를 수정.
  `CompatibilityProfile.preference_penalty()`를 selector 정렬 키에 `(priority, penalty, cost)`로
  추가했다. 선호 태그는 **순위만 바꾸고 배제하지 않는다**는 요구사항 문구를 그대로 코드에 반영.
- **AI-C-15**: 데이터 구조만 있던 상태에서 `contracts/profile_loader.py` + `profiles/{robot,facility,river}.json`
  추가. 도메인 추가 = 파일 추가임을 새 도메인 생성 테스트로 고정.

### 실 인프라 승격 3건

| ID | 이전 | 지금 |
|---|---|---|
| AI-C-06 | fake in-memory transport만 | `providers/mqtt.py` — 동작 중인 mosquitto(1883)에 **실제 pub/sub 왕복 검증**. paho import는 이 파일 1개로 제한되며 정적 검사로 고정 |
| AI-B-02 | 독립 실행 계약만(부분) | `Dockerfile` — OCI 이미지 빌드 + **컨테이너 안에서 pytest 통과**. 벤더 가속기 런타임을 베이스 이미지에 넣지 않음 |
| AI-B-08 | 스텁 provider만 | `providers/compute.py` — CPU/OpenCL 런타임 2종이 같은 Protocol로 교체됨을 실증 |

## 2. 검증 결과

```
호스트   : 157 passed, 1 skipped   (skip = OpenCL 플랫폼 부재)
컨테이너 : 151 passed, 7 skipped   (skip = paho-mqtt·브로커·OpenCL 부재)
```

**skip 자체가 검증 항목이다.** 선택 구성요소(MQTT 클라이언트, 브로커, OpenCL 플랫폼)가
없는 환경에서 관련 기능만 빠지고 나머지가 전부 통과하는 것이 AI-C-11/AI-C-05가 요구하는
동작이다. 이를 위해 `paho-mqtt`는 필수 의존성이 아니라 `[mqtt]` optional extra로 선언했다.

신규 테스트 47건 중 **정적 불변식 검사 3건**을 추가해 규칙이 시간이 지나도 썩지 않게 했다:

- 패키지 실행 코드에 벤더명(`nvidia`/`cuda`/`tensorrt`/`rocm`/`cudnn`/`cupy`) 부재
  — 토큰화로 주석·docstring을 제외하고 검사 (원칙 #1)
- 패키지 실행 코드에 도메인 ID(`robot_autonomy_support` 등) 부재 (원칙 #3)
- `paho` import가 `providers/mqtt.py` 한 파일에만 존재 (AI-C-06)

## 3. NVIDIA 비종속성 실증

이 노드는 Intel Iris Xe(`i915` 동작) + RTX 3070(드라이버 미설치) 구성이다.

- 전체 스위트가 `nvidia-smi` 없이 통과 → 벤더 종속이 실제로 없음을 회귀 시험으로 고정.
- `discover_node_tags()` 실행 결과: `['compute.cpu', 'media.hw_decode']`. 가속기 부재는
  오류가 아니라 **태그가 없는 상태**이며, selector가 CPU provider로 자동 대체한다.
- 태그는 벤더명이 아닌 능력 기준(`compute.opencl`)으로 명명했고, 공통 데이터 사전(AI-C-01)
  확정 전까지 `providers/compute.py` 지역 상수로만 유지한다 (원칙 #8).
- `intel-opencl-icd` 설치 시 OpenCL 테스트 1건이 skip에서 pass로 바뀌며 CPU 결과와의
  수치 동등성까지 검증된다. 설치는 sudo가 필요해 이번 범위에서 제외했다.

## 4. 남은 작업과 사유

| 항목 | 사유 |
|---|---|
| AI-C-06 Kafka + 엣지 Bridge | Kafka 미기동. Docker KRaft 단일 노드로 로컬 진행 가능하나 별도 작업 단위 |
| AI-B-05 K3s 실배포 | k3s는 Ready 상태. 이미지를 containerd로 import하려면 sudo 필요 |
| AI-O-01 실제 OTel/Prometheus | Collector 미기동. Grafana는 이미 동작 중이라 연결만 남음 |
| AI-C-10 백엔드 가용성 연계 | 백엔드 API 필요 — 타 파트 산출물 대기 |
| AI-N-01 최소 처리주기 | 요구사항이 실측 시험으로 확정하도록 규정 — 실물 필요 |
| AI-B-10 말단 경량 실행 | 실물 말단 하드웨어 필요 |

## 5. 추가 요구사항 필요 여부

없음. 모든 작업은 기존 요구사항 ID의 구현·승격에 해당한다.

한 가지 판단을 기록해 둔다: `paho-mqtt`를 필수 의존성이 아닌 optional extra로 둔 것은
요구사항에 명시된 문구는 아니지만, 원칙 #1·#7과 AI-C-12("현재 배포의 구현 선택일 뿐
필수 기술로 하드코딩하지 않는다")에서 직접 따라 나오는 결론이라 별도 승인 없이 적용했다.
