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
상위 AI 모듈의 필수 의존성이 아니다. 자세한 구조는 [AI 아키텍처](docs/ai/architecture.md)를
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

전체 회귀 결과는 실행 환경에 설치된 선택 의존성(MQTT/Kafka/OTel/K3s/OpenCL 등)에 따라
달라진다 — 미설치 provider의 테스트만 skip되고 나머지는 통과한다(§설치와 테스트 참고).

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
├── perception-framework/
│   ├── perception_framework/       # AI 프레임워크 Python 패키지
│   ├── simulator/           # 시나리오 시뮬레이터 (하드웨어 없이 프레임워크 성질 확인)
│   │   └── scenarios/       # 도메인 프로파일 포함, JSON 시나리오
│   └── tests/               # 모듈 단위 검증 + 시나리오 자동 검증
├── contracts/ai/           # 파트 간 JSON Schema와 예제 payload
├── interface-spec/         # 파트 경계를 넘는 통신 규약(물리 명령 wire 규약 등)
├── docs/ai/                # 아키텍처, 설계 결정, 요구사항 추적, 검증 계획
├── docs/ops/                # 이 PC(엣지+서버 겸용)의 네트워크·보안 운영 설정
├── docs/obsidian/          # KCI 확장 연구 — 재현 대상 논문·아이디어·구현 계획
├── models/                 # 실험용 AI 모델 artifact와 모델 카드
├── reports/                 # 개인 기록(git 미추적)
└── CLAUDE.md               # AI 요구사항 원문과 개발 규칙
```

세부 Python 패키지 구조는 [perception-framework/README.md](perception-framework/README.md)에서 확인할 수 있다.

## 설치와 테스트

Python 3.10 이상이 필요하다.

```bash
cd perception-framework
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e ".[dev]"

# 전체 회귀 테스트
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q

# 실행 가능한 시뮬레이터 (하드웨어 없이 프레임워크 성질 확인)
PYTHONPATH=. python3 simulator/simulation.py

# 프레임워크 특성 시나리오만 실행 (simulator/scenarios/*.json 전체)
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q tests/test_scenarios.py
```

컨테이너 검증:

```bash
cd perception-framework
docker build -t perception-framework:0.1.0 .
docker run --rm perception-framework:0.1.0 python -m pytest -q
```

실 MQTT, Kafka, OTel Collector, K3s 검증 환경은
[인프라·mock 계획](docs/ai/validation/infra-mock-plan.md)을 참고한다.

## 새 기기에서 환경 복원

이 저장소는 **코드·문서·실험 결과만** 담고 있다. 데이터셋과 모델 가중치는 용량 때문에
제외돼 있으므로(`.gitignore`의 `datasets/`, `models/`) 아래 절차로 내려받아야 원래
작업 디렉터리와 같은 상태가 된다. 각 자산의 출처·체크섬·라이선스는 내려받은 뒤
생성되는 `PROVENANCE.json`이 아니라 **이 문서가 기준**이다.

복원 후 검증 기준: `pytest` **471 passed / 2 skipped**, 시나리오 러너 전체 통과.

### 1. 시스템 요건

- Linux (검증 환경: Ubuntu, 커널 6.8)
- Python 3.10 이상
- 디스크 여유 **최소 15GB** (데이터셋 5.0GB + 모델 0.5GB + torch 1GB + 여유)
- k3s 시나리오를 돌리려면 k3s와 `kubectl`. 없으면 해당 시나리오만 건너뛴다.

### 2. 파이썬 패키지

```bash
cd perception-framework
pip install -e ".[dev]"          # jsonschema, numpy, opencv-python, pytest
```

실험 코드가 추가로 요구하는 것:

```bash
pip install onnxruntime psutil tokenizers
pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU 전용, ~1GB
```

전송 provider는 **선택 의존성**이다. 미설치 시 해당 provider만 비활성화되고 나머지는
그대로 동작한다(AI-C-11).

```bash
pip install -e ".[mqtt,kafka,otel]"   # paho-mqtt / kafka-python-ng / opentelemetry
pip install -e ".[sim]"               # pyjevsim — simulator/ 전용 DEVS 엔진
```

> 시스템 pytest 6.2.5 + anyio 플러그인 충돌로 collection이 깨지면:
> `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q`

### 3. 데이터셋

#### 3-1. MDDRobots — 실내 로봇 RGB 시퀀스 (5.0GB)

인지·추적·미학습 객체·지속학습 실험의 주 입력이다.

- 출처: Zenodo record **15340287** — DOI `10.5281/zenodo.15340287`
- 제목: *Multi-Domain Dataset for Robots (MDDRobots)*
- 라이선스: **CC BY 4.0**
- 전체는 36GB이며 아래 **부분집합만** 받는다(카메라 다양성 기준, 디스크 제약).

`datasets/mddrobots_subset/` 에 배치한다. **ZIP은 풀지 않는다** — 실험 코드가 zip을
스트리밍으로 읽는다.

| 파일 | 크기 | MD5 |
|---|---:|---|
| `README.md` | 3.9KB | `d076e1a12cfd1abd9e8c12e4e625e3c8` |
| `Visual-Anomaly-Dataction-for-Robots-MDDRobots-main.zip` | 1.6MB | `ed134c5f95506e37cea22af376f4202b` |
| `DataSet_P40PRO_RGB_test3.zip` | 578.8MB | `d063fc911cf5c611137b6d247b51af27` |
| `DataSet_XTION_RGB_test1.zip` | 730.5MB | `01953d274b3dcd18241d21a5f9807123` |
| `DataSet_RobotPiCamera_RGB_test1.zip` | 1683.0MB | `b8d0cdbf8b803db3eedda9aee5538960` |
| `DataSet_GOPRO_RGB_test3.zip` | 2291.0MB | `5a89be0b05d6ac4d8f98c736e3cda100` |

```bash
mkdir -p datasets/mddrobots_subset && cd datasets/mddrobots_subset
for f in README.md Visual-Anomaly-Dataction-for-Robots-MDDRobots-main.zip \
         DataSet_P40PRO_RGB_test3.zip DataSet_XTION_RGB_test1.zip \
         DataSet_RobotPiCamera_RGB_test1.zip DataSet_GOPRO_RGB_test3.zip; do
  curl -L -O "https://zenodo.org/records/15340287/files/$f?download=1"
done
md5sum -c <<'SUM'
d076e1a12cfd1abd9e8c12e4e625e3c8  README.md
ed134c5f95506e37cea22af376f4202b  Visual-Anomaly-Dataction-for-Robots-MDDRobots-main.zip
d063fc911cf5c611137b6d247b51af27  DataSet_P40PRO_RGB_test3.zip
01953d274b3dcd18241d21a5f9807123  DataSet_XTION_RGB_test1.zip
b8d0cdbf8b803db3eedda9aee5538960  DataSet_RobotPiCamera_RGB_test1.zip
5a89be0b05d6ac4d8f98c736e3cda100  DataSet_GOPRO_RGB_test3.zip
SUM
```

데이터 성격: 4개 카메라(GOPRO / P40PRO / RobotPiCamera / XTION)가 **동일한 6개 방**을
촬영했다. Test1은 학습 조건에 가깝고 **Test3은 조명·배치·시간대·경로가 바뀐 자연
분포 변화**다. 라벨은 **방 단위뿐이며 객체 bbox는 없다**.

#### 3-2. 기후 관측 (76KB)

하천·기후 위험 시나리오 입력. 2022-08-08 서울 호우 실측이다.

- 출처: WAMIS open API (국가수자원관리종합정보시스템) — `http://www.wamis.go.kr:8080/wamis/openapi/`
- 기간: 2022-08-05 ~ 2022-08-14, API 키 불필요

```bash
PYTHONPATH=perception-framework python3 tools/acquire_climate.py
```

`datasets/climate_hrfco_2022_08/` 에 관측소별 CSV와 `PROVENANCE.json`이 생성된다.

#### 3-3. 링크 품질 트레이스 (19MB)

AI-N-03 링크 기반 실행 전환 시나리오 입력. **원시 데이터를 먼저 받아야 한다.**

- 출처: Zenodo record **1219249** — DOI `10.5281/zenodo.1219249`
- 제목: *RSSI-based mobile robot localization datasets*
- 라이선스: **CC BY 4.0**

```bash
mkdir -p datasets/link_quality/zenodo_1219249_raw
# Zenodo 1219249 의 아카이브를 받아 위 디렉터리에 풀면 ex/ 하위 트리가 생긴다.
#   https://zenodo.org/records/1219249
PYTHONPATH=perception-framework python3 tools/curate_link_trace.py
```

`tools/curate_link_trace.py` 는 `datasets/link_quality/zenodo_1219249_raw/ex` 를 읽어
`datasets/link_quality/robot_rssi_zenodo_1219249` 를 만든다. 원시 트리가 없으면 스크립트가
바로 실패하므로 압축 해제 위치를 반드시 확인한다.

### 4. 모델

#### 4-1. closed-set ONNX 5종 (178MB) → `models/onnx/`

ONNX Model Zoo 미러(Hugging Face `onnxmodelzoo/*`)에서 받는다. 전부 표준 공개 모델이다.

| 파일 | 크기 | 용도 |
|---|---:|---|
| `tiny-yolov3-11.onnx` | 34MB | 객체 검출, pseudo-GT 생성 |
| `ssd_mobilenet_v1_10.onnx` | 28MB | 객체 검출 (대체 provider) |
| `resnet50-v1-12.onnx` | 98MB | 분류, 고비용 보조 provider |
| `mobilenetv2-12.onnx` | 14MB | 분류, 중간 비용 |
| `squeezenet1.1-7.onnx` | 4.8MB | 분류, 최저 비용 baseline |

`models/squeezenet/squeezenet1.1-7.onnx` 는 위 파일의 사본이며
`models/squeezenet/MODEL_CARD.md`(저장소에 포함됨)에 SHA256이 기록돼 있다.

#### 4-2. open-vocabulary ONNX 3종 (356MB) → `models/openvocab/`

전부 **int8 동적 양자화** 내보내기본이며 `onnxruntime` CPUExecutionProvider로 돈다.

| 디렉터리 | HF repo | 크기 | 라이선스 | 실측 지연 |
|---|---|---:|---|---|
| `clip-vit-base-patch32/` | `Xenova/clip-vit-base-patch32` | 157MB | **상업 제약 있음** | vision 15.4ms |
| `owlvit-base-patch32/` | `Xenova/owlvit-base-patch32` | 159MB | **Apache-2.0, 제약 없음** | 탐지 170–255ms |
| `mobileclip_s0/` | `Xenova/mobileclip_s0` | 57MB | **Apple AMLR — 연구 한정** | vision 55ms |

각 repo에서 `onnx/*_quantized.onnx`, `config.json`, `preprocessor_config.json`,
`tokenizer.json`, `tokenizer_config.json` 을 받아 위 디렉터리 구조로 둔다.

> **라이선스 주의.** 상업적 제약이 없는 것은 **OWL-ViT 하나뿐**이다. CLIP은 상위 모델
> 카드가 배포 사용을 out-of-scope로 명시하고, MobileCLIP-S0은 Apple AMLR로 상업 사용을
> 금지한다. 연구·비교 실험 용도로만 쓰고 제품 배포 후보로 간주하지 않는다.
>
> **MobileCLIP-S0 caveat.** 전처리 상수·토크나이저를 상위 카드 기준으로 재검증하지
> 않았고 스모크 테스트에서 zero-shot 분포가 무의미했다. 사용 전
> `preprocessor_config.json` 기준 재검증이 필요하다.

#### 4-3. 폐쇄망 원칙 (AI-C-16)

모델 조달은 **1회성**이며 런타임 추론 경로에는 네트워크 의존이 없다. 로컬 `.onnx` +
로컬 `tokenizer.json` + CPUExecutionProvider만 사용한다. `huggingface_hub`·
`transformers`는 **의도적으로 설치하지 않는다** — 런타임 자동 다운로드를 유발하기
때문이다. 토크나이저는 순수 로컬 파일을 읽는 `tokenizers` 패키지만 쓴다.

### 5. 인프라 (선택)

실제 broker·수집기·오케스트레이터를 쓰는 시나리오용이다. 없으면 해당 시나리오만
건너뛰고 나머지는 fake provider로 동작한다.

```bash
./tools/start_experiment_infra.sh      # MQTT(Mosquitto) / Kafka(Redpanda) / OTel Collector
sudo ./tools/k3s_local_only.sh         # k3s를 로컬 전용으로 고정
```

> `k3s_local_only.sh` 는 과거 k3s 유닛이 Tailscale IP에 고정돼 1,179회 크래시 루프한
> 사고를 막기 위한 것이다. 새 기기에서는 **Tailscale IP가 다르므로** 스크립트 안의
> 주소를 그대로 쓰지 말고 현재 노드 기준으로 확인한 뒤 실행한다.
>
> 디스크가 90%를 넘으면 kubelet이 `DiskPressure` taint를 걸어 파드가 **전혀** 스케줄되지
> 않는다. 시나리오가 전부 실패하면 `df -h /` 부터 확인한다.

### 6. 복원 검증

```bash
cd perception-framework
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
```

OpenCL 플랫폼이 없거나 OTel collector 출력 경로가 지정되지 않은 노드에서는 해당
테스트만 skip된다. 회귀가 아니다.

### 7. 저장소에 없는 것 정리

| 경로 | 용량 | 복원 방법 |
|---|---:|---|
| `datasets/` | 5.0GB | §3 |
| `models/` | 534MB | §4 |
| `.venv/`, `__pycache__/` | — | §2 재설치 |

## 다른 파트와의 계약

파트 경계의 단일 기준은 Python dataclass가 아니라 [공통 AI 계약](contracts/ai/README.md)이다.
하드웨어·백엔드·가시화는 AI 내부 Python 타입을 직접 import하지 않고
`contracts/ai/*.schema.json`과 예제 payload만 소비한다.

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
