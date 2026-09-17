# 실 인프라(K3s·MQTT 등) 로컬 검증 범위와 하드웨어 Mock 대체 계획

`01-standalone-implementation-plan.md`는 "하드웨어·타 파트 없이 fake provider로 로직을
검증한다"까지를 다뤘고, 그 결과 48개 중 40개가 완료 상태다. 남은 것은 Tier C, 즉
**"fake를 실제 구현으로 교체해도 상위 코드가 안 바뀌는가"** 하는 통합 검증이다.

이 문서는 Tier C를 다시 두 종류로 분리한다.

- **(1) 실 인프라 소프트웨어** — K3s, MQTT, Kafka, OpenTelemetry, 컨테이너. 이것들은
  *하드웨어가 아니라 소프트웨어*이며 이 개발 머신 한 대에서 전부 실행 가능하다. 즉
  "타 파트 대기"가 아니라 **지금 바로 승격 가능한 항목**이다.
- **(2) 실 하드웨어 / 물리 현장** — 카메라, 센서, GPU/NPU, 로봇 제어계, 다중 카메라
  시간동기화, 말단 저사양 보드. 이것만 mock 대체 대상이다.

## 0. 이 머신의 실측 현황 (2026-08-25 확인)

| 항목 | 상태 | 확인 방법 |
|---|---|---|
| Docker | 29.5.3, 데몬 접근 가능 | `docker info` |
| K3s | **동작 중, 노드 Ready** (v1.34.3+k3s3, control-plane) | `kubectl get nodes` |
| Helm | v3.14.4 설치됨 | `helm version` |
| MQTT Broker | **동작 중** — `eclipse-mosquitto:2` 컨테이너, `0.0.0.0:1883` | `docker ps`, `ss -ltn` |
| MQTT 클라이언트 | `paho-mqtt` 2.1.0, `mosquitto_pub` 설치됨 | `pip list` |
| Redis | 동작 중 (`redis:7-alpine`, 7860→6379) — 미디어 경로 provider 후보 | `docker ps` |
| Grafana | 동작 중 (3000) | `docker ps` |
| Kafka | **없음** — 필요 시 Docker(KRaft 단일 노드)로 기동 | `ss -ltn`에 9092 없음 |
| OTel Collector / Prometheus | **없음** — Docker 또는 K3s에 배포 가능 | 4317 미개방 |
| GPU / NVIDIA 드라이버 | **없음** (`nvidia-smi` 부재). 요구사항상 이는 결함이 아니라 **원칙 #1(벤더 하드코딩 금지)의 검증 조건** — 이 노드에서 전체 스위트가 그대로 통과해야 정상 | `nvidia-smi` 부재 상태에서 `pytest -q` 통과 |
| 카메라 | **없음** (`/dev/video*` 부재) → 합성 프레임 필요 | - |

결론: **K3s와 MQTT는 이미 있다.** 이 두 개에 대한 Tier C는 "타 파트 대기"가 아니라
바로 착수 가능한 상태다.

### 0-1. NVIDIA 부재에 대한 해석

이 노트북은 Ubuntu + NVIDIA 드라이버 없음이다. 요구사항 설계상 프레임워크는 GPU/NPU 벤더에
종속되면 안 되므로(원칙 #1, AI-B-08), **이 환경은 "제약"이 아니라 "회귀 시험 환경"이다.**

- 핵심 코드·테스트는 CUDA·`nvidia-smi`·GPU 런타임을 전혀 요구하지 않아야 하고, 실제로
  현재 110개 테스트가 이 노드에서 전부 통과한다. 이 사실 자체가 AI-B-08/AI-C-12의 증거다.
- `"gpu.cuda"` 같은 값은 **문자열 노드 태그**일 뿐이며 `CompatibilityProfile`이 이를
  해석하지 않는다. GPU가 없는 노드에서는 해당 태그를 요구하는 provider가 단순히 후보에서
  빠지고, `CapabilitySelector`가 CPU provider로 자동 대체한다(AI-B-04의 "선호 자원이 없으면
  호환 가능한 일반 자원으로 대체").
- 따라서 아래 표에서 GPU는 **mock 대체 대상이 아니라 "그냥 없는 게 정상인 선택 자원"**이다.
  실물 GPU가 필요한 것은 오직 자원 프로파일의 *수치*(compute_units, latency) 실측뿐이며,
  그 수치가 없어도 선택·축소 로직의 완료 판정에는 영향이 없다.
- 향후 GPU 노드가 추가되더라도 코드 수정 없이 태그+프로파일 등록만으로 붙어야 하며,
  이를 어기는 순간(예: 핵심 코드에서 `torch.cuda` 직접 참조) 이 노트북에서 테스트가 깨지는
  것으로 즉시 드러난다. **GPU 없는 이 환경을 CI 기준 환경으로 유지할 것을 권장한다.**

## 1. 인프라 항목별 — 지금 로컬에서 어디까지 승격 가능한가

| 요구사항 | 지금 상태 | 로컬에서 가능한 승격 | 그래도 남는 갭 |
|---|---|---|---|
| AI-C-06 (메시지 전송) | fake in-memory Transport | 실행 중인 mosquitto에 붙는 `MqttTransportProvider`(paho) 구현. `InMemoryTransportProvider`와 **같은 Protocol·같은 conformance 테스트**를 통과하는지로 검증 | 실제 현장 네트워크 단절/지연 특성, BE가 운영할 서버 Kafka 토픽 규약 |
| AI-C-06 (엣지 Bridge) | 미구현 | Docker로 단일 노드 Kafka(KRaft) 기동 → MQTT↔Kafka 양방향 Bridge를 별도 프로세스로 구현하고 "엣지엔 Kafka 서버 없음"(원칙 #11) 배치를 그대로 재현 | 실제 다중 엣지·다중 구역 규모, BE 스키마 |
| AI-B-02 (패키징) | 부분 — 독립 실행 계약만 | Dockerfile 작성 → `docker build`로 OCI 이미지 생성, 컨테이너 안에서 `pytest` 통과 확인 → **"부분"을 "완료"로 승격 가능** | ARM 말단 보드용 크로스 빌드(buildx는 설치돼 있어 시도 자체는 가능) |
| AI-B-05 (배포·생명주기) | fake lifecycle 상태기계 | 위 이미지를 K3s에 Deployment/Helm chart로 올려 기동·업데이트·롤백을 실제로 수행. `ControlProvider`의 K3s 구현체 추가 | 실제 구역 엣지 하드웨어의 자원 제약 |
| AI-B-07 (복구·롤백) | fake | K3s liveness/readiness probe에 기존 health 계약을 연결하고, **K3s를 정지시킨 상태에서도** 동일 코드가 standalone supervisor로 동작하는지 검증(요구사항의 핵심 주장) | - |
| AI-O-01/02 (관측) | in-memory sink | OTel Collector + Prometheus를 Docker/K3s로 띄우고 `ObservabilityProvider`의 OTLP 구현 추가. 이미 떠 있는 Grafana로 확인 | 서버측 요약 정책은 BE-S-02 확정 후 |
| AI-C-10 (백엔드 가용성 연계) | fake 판정 입력 | **승격 불가** — 백엔드 API가 진짜 필요. 단 MQTT LWT + Prometheus `up`을 실제로 발생시켜 "두 신호가 불일치할 때" 입력 케이스는 재현 가능 | 최종 판정 주체는 BE |
| AI-B-10 (말단 경량 경계) | 미착수 | 컨테이너 자원 제한(`--memory`, `--cpus`)으로 저사양 말단을 흉내내 "브로커 없이 클라이언트만으로 동작"을 검증 | 실물 보드 성능·발열 |

## 2. 하드웨어 → Mock 대체 가능성 판정

핵심 질문에 대한 답: **대부분 가능하다.** 이 프레임워크는 애초에 상위 로직이
Provider Protocol에만 의존하도록 설계돼 있어서, 하드웨어는 "또 하나의 provider 구현"에
불과하다. 다만 mock으로 **원리상 대체 불가능한 항목**이 분명히 있으므로 구분한다.

### 2-1. Mock으로 충분한 것 (지금 진행 가능)

| 하드웨어 | Mock 방식 | 이 방식으로 보장되는 것 |
|---|---|---|
| 카메라 (AI-E-01, AI-C-08) | 합성 프레임(numpy 도형/노이즈) + 동영상 파일 재생 provider. 이미 `SyntheticMediaSourceProvider` 존재 | 인지 인터페이스 계약, 영상 소스 없을 때 영상 기능만 비활성화되는 격리 |
| 카메라 보정 (AI-E-02/03) | 알려진 K/dist로 `cv2.projectPoints` 역산한 합성 코너 (이미 구현·검증됨) | 추정 알고리즘 정확도와 프로파일 버전·검증·롤백 로직 |
| 센서 시계열 (AI-R-01/02) | 결정론적 numpy 시계열 + 이벤트 스트림 fixture | FSM 전이, 위험도 산정, 근거 충분도 분리 |
| 로봇 상태·임무 (AI-D-*) | JSON fixture | 서브태스크 생성/검증/재생성 규칙 |
| GPU/NPU (AI-B-01/08) | mock이 아니라 **선택 자원 부재 상태 그 자체**로 검증한다. 필요하면 가짜 노드 태그(`"gpu.cuda"` 등)를 주입해 "GPU 노드가 있는 척"하는 반대 방향 테스트만 추가 | GPU 없는 노드에서 CPU provider로 자동 대체되는지 = AI-B-04/AI-B-08 충족. **NVIDIA 종속이 생기면 이 노드에서 즉시 실패로 드러남** |
| 다중 카메라 (AI-S-02) | 두 개의 합성 track + 가짜 임베딩 | 연계/미연계 판정, 단일 카메라에서도 정상 동작 |
| 장치 급사 (AI-O-04) | mosquitto에 실제 LWT 등록 후 클라이언트 강제 종료 | 업무/관측 신호 불일치 케이스 |
| 저사양 말단 (AI-B-10) | 컨테이너 cgroup 자원 제한 | 경량 클라이언트만으로 기동되는지 |

### 2-2. Mock으로 대체 **불가능**한 것 (실물 필요 — 지금은 "미검증"으로 명시)

| 항목 | 왜 불가능한가 |
|---|---|
| AI-N-01 최소 처리주기 확정 | 요구사항 자체가 "이동속도·제동거리·센서취득·추론·제어 지연을 합산한 실측 시험으로 확정"이라고 규정. 합성 데이터로는 로직만 검증되고 **주기 수치는 확정 불가** |
| 실제 렌즈 왜곡·조명·모션블러 하의 인지 정확도 | 합성 프레임은 계약만 증명하고 성능은 증명하지 않음 (요구사항상 성능은 완료 판정 기준이 아님 — AI-B-09) |
| 발열·자원 포화로 인한 재구성 (AI-B-06) | 부하 주입으로 *흉내*는 가능하나 실제 thermal throttling 특성은 실물 필요 |
| GPU/NPU 실행 자원 특성 프로파일 *수치* (AI-B-01) | 프로파일 구조·선택 로직은 GPU 없이 완결되지만, 등록될 `compute_units`/`max_latency_ms` 실제 값은 해당 하드웨어에서 측정해야 한다. 이는 프레임워크 종속성이 아니라 provider 등록 데이터의 문제다 |
| 다중 노드 시간 동기화 정확도 (AI-C-03) | NTP 오차 특성은 실제 네트워크·노드 필요. 동기화 깨짐 시 fallback 로직은 가짜 clock으로 검증 가능 |

**정리**: mock은 *동작과 경계*(= CLAUDE.md §7의 완료 판정 기준)를 100% 커버하고,
커버하지 못하는 것은 *수치 튜닝과 성능*뿐이다. 요구사항이 정의한 완료 판정이 "특정 모델
정확도나 특정 기술 사용 여부가 아니라 시스템 동작과 경계"이므로, **하드웨어 없이도 완료
판정은 가능하며 남는 것은 실측 파라미터 확정뿐**이다.

## 3. 진행 순서와 현재 상태 (2026-08-25 기준 갱신)

| # | 항목 | 상태 |
|---|---|---|
| 1 | 미착수 Tier A 4건 (AI-D-03, C-02, C-03, C-14) | **완료** |
| 2 | AI-B-02 OCI 이미지 + 컨테이너 내 테스트 | **완료** |
| 3 | 실 MQTT provider (mosquitto:1883) | **완료** |
| 4 | K3s 배포·상태·롤백 연계 (AI-B-03/05/07) | **완료** — `providers/k3s.py`, kubectl CLI만 사용 |
| 5 | Kafka + 엣지 양방향 Bridge (AI-C-06) | **완료** — `providers/kafka.py`, `edge/bridge.py` |
| 6 | OTel Collector/Prometheus 연계 (AI-O-01/02) | **완료** — `providers/otel.py`, Collector 수신 파일로 e2e 확인 |
| 7 | 실물 대기 항목 | AI-N-01 주기 실측, AI-B-10 말단 실물, AI-C-10 백엔드 연계 |

인프라 기동 명령(개발용):

```bash
# MQTT — 이미 기동 중인 컨테이너 사용 (eclipse-mosquitto:2, :1883)
docker run -d --name aif-kafka -p 9092:9092 \
  -e KAFKA_NODE_ID=1 -e KAFKA_PROCESS_ROLES=broker,controller \
  -e KAFKA_LISTENERS=PLAINTEXT://:9092,CONTROLLER://:9093 \
  -e KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://127.0.0.1:9092 \
  -e KAFKA_CONTROLLER_QUORUM_VOTERS=1@localhost:9093 \
  -e KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER \
  -e KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT \
  -e KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1 \
  -e KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=1 \
  -e KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=1 apache/kafka:3.9.0

docker run -d --name aif-otel -p 4317:4317 -p 4318:4318 \
  -v "$PWD/otel-config.yaml:/etc/otelcol-contrib/config.yaml:ro" \
  -v "$PWD/otel-output:/output" otel/opentelemetry-collector-contrib:latest
```

Kafka는 개발용 단일 노드이며 **엣지가 아니라 "서버" 역할로만 사용**한다. 엣지에는
Kafka 서버를 두지 않는다는 원칙 #11이 코드 구조(`edge/bridge.py`는 두 개의
`TransportProvider`만 알고 있음)로 표현돼 있다.

## 4. NVIDIA 의존성 제거 방식과 비-NVIDIA GPU 사용 가능성

### 4-1. 요구사항이 NVIDIA 의존성을 제거하려 한 4가지 장치

원본 요구사항은 "NVIDIA를 쓰지 말라"고 한 적이 없다. **어떤 벤더든 핵심 코드가 알지
못하게 만드는 구조**를 요구한다. 구체적으로 네 겹이다.

| 장치 | 원문 근거 | 코드 구현 |
|---|---|---|
| ① 하드코딩 금지 | 원칙 #1 "GPU/NPU 벤더 … 하드코딩하지 않는다", AI-C-04 "상위 기능은 GPU 벤더를 직접 참조해서는 안 된다" | 핵심 코드에 `cuda`/`nvidia`/벤더 API 문자열이 **하나도 없음** (grep으로 확인; `"gpu"`는 `tests/test_selector.py`의 fixture 태그뿐) |
| ② 공통 실행 인터페이스 | AI-B-08 "특정 모델 파일 형식, 추론 엔진, **가속기 API**나 로컬·원격 실행 방식에 직접 의존하지 않고" | `providers/adapters.py::AIRuntimeProvider` — `infer(capability_kind, inputs)` / `is_available()` 두 개뿐. 로컬 ONNX든 TensorRT든 원격 API든 호출부가 동일 |
| ③ 자유 문자열 태그 + 추상 자원 단위 | AI-B-01 "연산·메모리·지연 특성을 공통 프로파일로 관리", AI-B-04 "가속기 … 등록" | `contracts/profile.py` — `required_hw_tags`가 enum이 아닌 `tuple[str, ...]`, 비용은 벤더 벤치마크가 아닌 추상 `compute_units`. 새 가속기는 태그 문자열 추가만으로 등록 |
| ④ 없을 때의 동작 규정 | AI-B-04 "선호 자원이 없으면 호환 가능한 일반 자원으로 대체", AI-C-05/11, 금지사항 "GPU/NPU가 항상 존재한다고 가정하지 않는다" | `selection/selector.py` — 태그 불일치 provider는 후보에서 빠지고 CPU provider가 선택됨. 후보가 0이면 예외가 아니라 `SelectionResult(None, reason=...)` |

즉 제거 전략은 **"추상화(②) + 데이터화(③) + 부재 시 축소 경로 명시(④)"**이며, ①은 그것이
지켜졌는지 확인하는 검사 규칙이다. 이 설계 덕분에 벤더 교체는 "provider 등록 데이터 변경"
이지 "코드 변경"이 아니다.

**확인된 갭 1건**: `preferred_hw_tags`는 선언은 되지만 `CapabilitySelector`가 선택 점수에
반영하지 않는다(정렬 키가 `(priority, compute_units)`뿐). "GPU 있으면 선호, 없으면 CPU"를
표현하려면 현재는 priority를 수동으로 맞춰야 한다 — 추적표의 AI-B-04 "부분" 항목이 이것이다.

### 4-2. 이 노트북에는 사실 GPU가 두 개 있다

| 장치 | 상태 |
|---|---|
| Intel Iris Xe (TigerLake-LP GT2, `8086:9A49`) | **드라이버 동작 중** — `i915`, `/dev/dri/renderD128` 존재 |
| NVIDIA RTX 3070 Mobile (GA104M) | 하드웨어는 있으나 **드라이버 미설치** (`nvidia-smi` 없음) |

즉 정확히는 "GPU가 없는 환경"이 아니라 **"NVIDIA 드라이버만 없는 환경"**이고, 비-NVIDIA
GPU 가속 경로는 열려 있다. 현재 미설치라 즉시 쓰지 못할 뿐이다:

- `/etc/OpenCL/vendors/`에 `nvidia.icd`만 등록돼 있어 `cv2.ocl.haveOpenCL()` = **False**
  (ICD 로더 `libOpenCL`은 있으나 사용 가능한 플랫폼이 없음).
- `intel-opencl-icd` 패키지 미설치 (candidate 22.14.22890-1 존재).
- 반면 Vulkan Intel 드라이버(`libvulkan_intel.so`)는 설치돼 있고, OpenCV videoio가
  `INTEL_MFX`·`GSTREAMER`·`V4L2` 백엔드를 이미 노출한다(하드웨어 영상 디코드 경로).

### 4-3. 비-NVIDIA GPU 사용 경로

| 경로 | 대상 하드웨어 | 이 노트북에서 | 프레임워크상 위치 |
|---|---|---|---|
| **OpenCL + OpenCV T-API(`UMat`)** | Intel/AMD/ARM Mali 등 대부분 | `intel-opencl-icd` 설치만 하면 즉시 (`cv2.ocl.setUseOpenCL(True)`) | `AIRuntimeProvider` 구현 하나 추가, 태그로 선언 |
| **OpenVINO** | Intel CPU/iGPU/NPU | 설치 가능, iGPU 타깃 | 상동 |
| **oneAPI Level Zero** | Intel GPU/NPU | 설치 가능 | 상동 |
| **Vulkan compute** | 벤더 무관 | Intel Vulkan 드라이버 이미 존재 | 상동 |
| **ONNX Runtime Execution Provider** | EP만 바꿔 CPU/OpenVINO/ROCm/DirectML/CUDA 전환 | CPU·OpenVINO EP 사용 가능 | **가장 권장** — ONNX Runtime 자체가 ②와 같은 추상화라 provider 1개로 다수 백엔드 커버 |
| **ROCm / HIP** | AMD | 해당 없음 | 태그 등록만 |
| **VAAPI / QSV 디코드** | Intel iGPU | `/dev/dri/renderD128` + `INTEL_MFX` 백엔드 존재 | `MediaSourceProvider` 구현 |
| **전용 NPU (Coral, Hailo, Jetson 등)** | 말단 보드 | 해당 없음 | 태그 + provider 등록 |

**결론: 가능하다.** 그리고 이것을 가능하게 만드는 것이 위 ②③④의 목적 그 자체다. 비-NVIDIA
가속기를 붙이는 작업은 요구사항상 "핵심 코드 수정"이 아니라 **AI-B-09(신규 확장 등록·호환성
검증)의 정상 절차** — provider 구현 + 태그·프로파일 등록 + conformance 통과 — 로 처리된다.

### 4-4. 권장 검증 시나리오 (하드웨어 추가 구매 없이 가능)

지금 이 노트북에서 **"NVIDIA 없이 GPU를 쓴다"는 명제를 실증**할 수 있다:

1. `intel-opencl-icd` 설치 → `cv2.ocl.haveOpenCL()`이 True로 바뀌는지 확인.
2. 동일 `capability_kind`에 provider 2개 등록 — CPU(`UMat` 미사용)와 OpenCL(`UMat` 사용).
3. 노드 태그를 `{"cpu"}` → `{"cpu", <가속 태그>}`로 바꾸는 것만으로 선택이 전환되고,
   **호출부 코드는 한 줄도 바뀌지 않음**을 테스트로 고정.
4. OpenCL 런타임을 제거/실패시켰을 때 CPU provider로 자동 축소되는지 확인(AI-B-06).

이 시나리오는 NVIDIA 하드웨어에서 검증하는 것보다 오히려 **벤더 비종속성 증명으로서 더
강력하다** — 프레임워크가 실제로 서로 다른 벤더 백엔드 사이를 오갈 수 있음을 보이기 때문.

### 4-5. 태그 명명에 대한 주의

`"gpu"`, `"accel.opencl"` 같은 태그 문자열은 지금 확정하지 않는다. 원칙 #8과 AI-C-01이
"전체 기능 구현 후 데이터 사전에서 일괄 통일"을 규정하므로, 그때까지는 각 테스트·프로파일
안의 지역 값으로만 쓰고 공통 상수로 승격하지 않는다. 다만 벤더명(`"cuda"`, `"nvidia"`)을
태그로 쓰는 것은 피하고 **능력 기준**(예: "OpenCL 실행 가능", "FP16 지원")으로 표현하는 편이
①의 취지에 맞다 — 이는 데이터 사전 확정 시 반영할 제안 사항으로 남긴다.

## 5. 추가 요구사항 필요 여부

없음. 위 항목은 모두 기존 요구사항 ID의 Tier C 통합 검증 또는 AI-B-09 확장 절차에 해당하며
새 기능이 아니다.
단 실 provider 구현 시 필요한 접속 정보(브로커 주소·토픽 규약·Kafka 토픽명)는 BE 파트와의
데이터 사전 통일(AI-C-01) 전까지 **배포 프로파일 설정값으로만 두고 코드에 고정하지 않는다.**
