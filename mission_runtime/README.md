# mission_runtime

자율행동체의 **실행 런타임**. 하나의 임무가 작업 그래프로 분해되면, 각 노드를 지금
실제로 쓸 수 있는 추론 서비스와 가속기에 배정해 실행하고, 쓸 수 없으면 축소하고,
무엇이 왜 그렇게 됐는지를 운영 화면이 읽을 수 있는 상태로 낸다.

설계의 중심은 하나다 — **무엇을 실행할 수 있는가를 런타임에 정한다.** 센서·모델·
가속기·실행 위치·전송 기술·적용 도메인이 바뀌어도 상위 인지·판단 코드는 고치지 않는다.

```python
from mission_runtime.contracts.capability import CapabilityRequirement
from mission_runtime.registry.capability_registry import CapabilityRegistry
from mission_runtime.selection.selector import CapabilitySelector

# 선택 기능이 없으면 DEGRADED 로만 내려간다 — DISABLED 가 되지 않는다.
requirement = CapabilityRequirement(
    required=("media.video_input",), optional=("perception.distance",)
)
state = requirement.evaluate({"media.video_input"})      # ACTIVE / DEGRADED / DISABLED
```

## 이 런타임이 지키는 네 가지

| | 무엇을 | 왜 |
|---|---|---|
| **능력 선언** | 기능은 필수·선택 조건을 선언하고 런타임에 `ACTIVE`/`DEGRADED`/`DISABLED` 로 환산된다 | 선택 기능의 결손이 관련 없는 기능을 멈추게 하지 않는다 |
| **provider 경계** | 전송·직렬화·미디어·추론 런타임·오케스트레이터·관측·보안은 전부 Protocol 뒤에 있다 | MQTT·Kafka·OTel·K3s·Tailscale 은 현재 배포가 고른 구현일 뿐이다 |
| **모른다를 아니다와 섞지 않음** | 측정 없음·미확인·미수신이 0·거짓·정상으로 접히지 않는다 | 접힌 구분은 화면에서 복원되지 않는다 |
| **판단과 권한의 분리** | 인지·판단·추천은 하되 물리 명령 발급·전역 좌표·최종 가용성은 소유하지 않는다 | 같은 사실에 두 주인이 있으면 반드시 어긋난다 |

## 배치

이 디렉터리가 **프로젝트 루트이면서 파이썬 패키지 루트**다(`mission_runtime/mission_runtime`
같은 이중 경로를 두지 않는다).

```text
# 패키지 모듈
contracts/      capability·호환 프로파일·공통 데이터 사전·물리 명령 의미 계약
registry/       capability kind 별 provider 등록부 (로컬 + 중앙 스냅샷)
selection/      호환 후보 중 최소 자원 선택과 단계적 축소
providers/      Transport·Serializer·Media·Runtime·Control·Observability·Overlay·ModelDeployment
perception/     인지·추적·다중관측 연계·불확실성·미확인 객체·추가 정보 선택
risk/           위험 분석 상태기계와 위험도·근거·권고
planning/       작업 분해, 생성 제안의 capability 접지, 상황 기반 임무 추천
execution/      실행 제어·lifecycle·작업 그래프 상태·외부 개발 요청·물리 명령 게이트웨이
observability/  계층별 자원 지표·임계 감시·사건 기록·통합 상태 뷰
continual/      운영 스트림 기반 지속학습 후보·파라미터 평가
runtime/         도메인 무관 조립·자원 재구성·모델 배정·폐쇄망·모델 배포
ondevice/       외부 구성 적용·링크 품질 기반 축소
edge/           카메라 보정 lifecycle·말단↔상위 양방향 Bridge
integration/    도메인 객체 → 공통 wire 메시지, 현재 배포의 전송 지형
simulation/     하드웨어 없이 시나리오를 돌리는 가상 말단·replay·소비자 mock

# 코드가 아닌 것
schemas/ai/     파트 경계 JSON 계약과 **생산 코드에서 생성한** 예시
schemas/viz/    가시화 파이프라인용 컴포넌트·데이터소스 선언
specs/          파트 경계 통신 규약(물리 명령 등)
docs/           구조·기술 경계·확장 절차·통합 인수인계
config/         설정 예시(`*.example.json`) — 현장 값은 저장소에 두지 않는다
profiles/       도메인별 배포 프로파일
deploy/         개발·시험용 compose 스택과 말단 systemd 유닛
services/       엣지 노드 서비스와 장치 에이전트
tools/          상태 UI·장비 스모크·인프라 도구
tests/          시험 (실제 모델·자원·브로커로 도는 통합 시험 포함)
```

`pyproject.toml` 의 `packages` 와 `package-data`, 그리고 `MANIFEST.in` 이 "무엇이
배포물에 들어가는가"를 정한다. 패키지 루트가 프로젝트 루트여서 자동 탐색이 통하지
않으므로 둘 다 손으로 적고, 빠진 것이 없는지는 `tests/test_packaging.py` 가 본다.

## 시작하기

이 디렉터리 하나만 있으면 된다. 자산(`local/`)도, 상위 디렉터리도, 내부 문서도 필요
없다 — 없으면 **그 기능만** 비활성이고 그 사실이 응답과 기동 로그에 적힌다.

```bash
python -m venv .venv && . .venv/bin/activate      # Python >= 3.10
pip install -e ".[dev]"                            # 선택 extra: mqtt / kafka / otel / redis / metrics
python tools/preflight.py                          # 이 기계에서 무엇이 되는지 먼저 본다
pytest -q
```

**받은 그대로** — 선택 패키지도 모델 자산도 브로커도 없는 상태 — 로 돌리면 **실패가
없다.** skip 은 "안 되는 것"이 아니라 "이 기계에 그 도구·자산·브로커가 없다"는 뜻이고,
사유에 **무엇이 없어서 어느 provider 만 비활성인지**가 적힌다. 이 저장소의 기준
기계에서 선택 패키지(`psutil`·`paho`·`ultralytics`)와 외부 도구(`ssh-keygen`·`ping`)와
자산 뿌리를 가린 채 돌린 결과는 **3417 passed · 108 skipped · 0 failed** 이다. 절대 수는
시험이 늘면 바뀌지만 **failed 가 0 인 것이 기준이다.**

2026-11-04 까지 이 자리에는 **11 failed** 가 있었다. 받는 쪽의 환경 잘못이 아니라
**선택 결손을 축소로 다루지 못한 우리 쪽 결함**이었고(AI-C-05 · 원칙 #4/#6) 전부 고쳤다.
일곱은 선언되지 않은 외부 도구·패키지를 전제했다 — `psutil` 셋 · `ssh-keygen` 둘 ·
`paho` 하나 · `ping` 하나. 넷은 자산 뿌리가 없는 상태를 축소로 다루지 못했고 그중 둘은
`edge/detector_catalog.py` 가 `Path(None)` 에서 죽었다. 지금은 앞의 일곱이 **무엇이
없는지 적은 사유와 함께** skip 이고, 자산 뿌리가 없는 상태에는 고정된 답이 있다 —
`weights_present` 가 `False`("자리를 보고 없었다")가 아니라 `None` +
`presence_reason=no_asset_root`("물어볼 자리가 없다")로 나간다. 그 둘을 한 값으로
접으면 운영자가 "뿌리를 가리키면 되는 일"과 "가중치를 받아와야 하는 일"을 구분할 수
없다. `psutil` 은 이제 선언된 extra 다(`.[metrics]`) — 선언되지 않은 전제로 두면 받는
쪽이 "왜 값이 없나"를 추적할 수 없다.

선택 extra 가 없으면 그 provider 만 비활성이다. **브로커가 떠 있는데 클라이언트
라이브러리가 없는 조합도 skip 이다** — 전에는 통합 시험 일부가 "브로커에 닿는가" 만
보고 클라이언트가 깔렸는지는 보지 않아서 그 조합에서 skip 대신 실패했다. 이제 서버와
클라이언트를 함께 본다.

```bash
pip install -e ".[dev,mqtt,kafka,otel]"           # 1883/9092/4317 이 열려 있는 기계
```

### 이 기계에서 무엇이 되고 무엇이 안 되는가

받아서 **띄우기 전에** 알아야 하는 것은 셋이다 — 무엇이 그대로 돌고, 무엇이 줄어들고,
무엇이 아예 안 되는가. 그리고 왜 그런가. 이 답을 문서에 적어 두면 코드와 어긋나므로
**도구가 답한다.**

```bash
python tools/preflight.py          # 사람이 읽는 표
python tools/preflight.py --json   # 기계가 읽는 한 덩어리
```

핵심 의존성이 깔린 **다음**이 이 명령의 자리다 — 설치 전에 돌리면 `cv2` import 에서
죽는다. 여섯 절을 돌되 **판정을 새로 하지 않는다**: 환경 사실은
`runtime/environment_profile.py`, 이번 실행이 쓸 device 는 `ondevice/rpn_propose.py`,
탐지기 조달 가능성은 `edge/detector_catalog.py` 가 소유하고 이 도구는 그 답을 모아 한
장으로 낸다. 같은 판정을 두 곳에서 하면 설치 화면과 운영 화면이 다른 말을 한다.

| 절 | 무엇을 묻는가 |
|---|---|
| 핵심 | Python 3.10+ · jsonschema · numpy · opencv · protobuf |
| 플랫폼 | 리눅스 계측 경로 셋 — 온도 · 전력 · 무선 링크 |
| 가속기 | `nvidia-smi` 가 **무엇을 말했는가** · 이번 실행이 쓸 device |
| 선택 기능 | MQTT · Kafka · Redis · OTel · ONNX · PyTorch · ultralytics |
| 외부 도구 | kubectl · mosquitto · ssh · docker |
| 모델 자산 | 선언된 탐지기 가중치가 이 노드에 있는가 |

#### 세 상태 — 그리고 축소는 실패가 아니다

| 표시 | 뜻 | 받는 쪽이 할 일 |
|---|---|---|
| `[o]` 정상 | 그대로 된다 | 없다 |
| `[~]` 축소 | **그 기능만** 꺼지고 나머지는 돈다. 결손이 정상 배치인 경우다(AI-C-05) | 그 기능이 필요하면 「얻는 방법」 줄을 따른다. 필요 없으면 없다 |
| `[x]` 막힘 | 그 기능을 쓸 수 없다 | 무엇을 하면 되는지 함께 적힌다 |

아무것도 더 깔지 않은 기본 이미지에서 이 명령은 **`정상 11 · 축소 13 · 막힘 0`** 을
내고 마지막 줄에 "핵심 기능은 그대로 뜬다" 고 적는다. **노란 줄 13 개는 고장 13 개가
아니다.** 그것을 "이건 내 환경에서 안 되는구나" 로 읽으면 핵심이 전부 도는 시스템을
두고 그만두게 된다 — 이 도구가 축소와 막힘을 한 수로 합치지 않는 이유가 그것이다.
종료 코드도 같은 규칙이라 **막힘이 있을 때만** 0 이 아니고, 그래서 `Dockerfile` 의
HEALTHCHECK 이 이 명령이다(선택 기능이 없는 컨테이너가 unhealthy 로 재시작되지 않는다).

#### 제약은 세 종류이고, 섞으면 답할 수 없는 질문이 생긴다

**1. 리눅스 계측 경로 — 없으면 미측정이고 0 이 아니다.**
`/sys/class/thermal`(온도) · `/sys/class/powercap`(전력) · `/proc/net/wireless`(무선
링크 품질) 셋을 본다. 없으면 그 값이 0 이 아니라 **미측정**으로 나가고(AI-O-05), 무선이
없으면 링크 품질 기반 실행 전환만 비활성이다(AI-N-03). 센서 없는 커널은 흔하므로
**이 줄에는 처방이 적히지 않는다** — 받는 쪽이 할 일이 없는데 할 일을 지어내지 않는다.
처방 없는 노란 줄은 빠뜨린 것이 아니다.

이 점검이 묻는 것은 "커널이 그 경로를 내놓는가" 까지다. 경로가 있어도 **그 안에 잴
것이 없는** 기계가 있다 — 이 저장소의 기준 기계(WSL2)에서는 세 경로가 모두 있어서 점검은
`정상` 이지만, `/sys/class/thermal` 에는 `thermal_zone*` 이 없고
`/sys/class/powercap` 에는 전력 zone 이 하나도 없고 `/proc/net/wireless` 에는 머리글만
있다. 그래서 실제 CPU 온도와 소비 전력은 `source=unavailable` 로 나온다(같은 기계에서
보드 메모리와 GPU 사용률·온도는 실측으로 나왔다). **`정상` 은 "경로가 있다"까지만
보증한다.** 어느 쪽이든 0 이 되지 않는다 — `observability/host_resources.py` 가 사유를
붙여 미측정으로 둔다.

**2. NVIDIA — 세 상태를 하나로 합치지 않는다.**

| `nvidia-smi` 가 | 판정 | 뜻과 할 일 |
|---|---|---|
| 없다 | 축소 | 이 기계에 NVIDIA 가속기가 없다는 뜻이다. GPU 기능이 CPU 로 내려가고 핵심은 그대로 돈다 — **필요 없으면 할 일이 없다** |
| 있는데 답하지 못한다 | **막힘** | 드라이버 충돌의 관측 모양이다. GPU 기능이 전부 CPU 로 내려가 느리지만 **동작은 한다**. GPU 가 필요하면 Windows 의 Docker Desktop 또는 WSL2 에서 띄운다 |
| 답해서 0개라고 말한다 | 축소 | 도구와 드라이버는 살아 있고 가속기가 없다 |

가운데 줄이 이 도구를 만든 이유다. 셋을 "GPU 없음" 하나로 접으면 **"왜 GPU 를 안 쓰는가"
를 끝까지 추적할 수 없다**(AI-B-01 의 미측정 구분, AI-O-05). 둘째 줄은 이 프로젝트가
실제로 만난 상태이고 `runtime/environment_profile.py` 의 모듈 docstring 이 그것을 현장
확정 사실로 적어 둔다 — 네이티브 리눅스에서 nvidia 드라이버가 충돌해 GPU 를 쓸 수 없고,
GPU 가 필요하면 윈도에서 Docker 또는 WSL 로 가상환경을 만들어 쓴다. 이 저장소의 기준
기계(WSL2)에서는 `nvidia-smi` 가 응답하고 가속기 1 개를 보고한다.

**3. 되는 것처럼 보이면서 틀린 값을 내는 함정.**
`CUDA_VISIBLE_DEVICES=""` 로 가속기를 숨기지 않는다. CUDA 휠이 깔린 기계에서 이렇게
숨기면 NVBLAS 가 CPU BLAS 를 가로채 **예외 없이 틀린 값**이 나온다 — 화면 밖 박스, 음수
좌표, 빈 라벨, 계단지는 점수. 실측으로 확인된 모양이고 예외가 없으니 "CPU 에서도 되네"
로 읽힌다. **조용히 틀린 값은 실패보다 나쁘다** — 실패는 눈에 띄고 이것은 안 띈다.
그래서 자가 점검은 이 변수가 빈 값으로 설정돼 있으면 축소가 아니라 **막힘**으로 잡는다.

가속기를 쓰지 않기로 하는 지원된 길은 하나다.

```bash
MISSION_RUNTIME_NO_GPU=1 pytest -q    # 고르는 쪽만 바꾼다. 계산을 바꾸지 않는다
```

이 선언은 **기본 device 선택**만 바꾸고 노드 태그는 가속기가 있다고 그대로 보고한다 —
"이 기계에 GPU 가 없다" 와 "이번에는 쓰지 않는다" 는 다른 사실이고, 한 칸에 합치면
기계를 옮겼을 때 원래 선언이 무엇이었는지 복원할 수 없다.

### 바깥에 쓰는 것, 바깥에서 읽는 것

패키지는 자기 트리 밖에 쓰지 않는다. 쓸 것이 생기는 자리는 하나뿐이고 둘 다 환경변수로
옮길 수 있다.

| 환경변수 | 무엇 | 기본값 |
|---|---|---|
| `MISSION_RUNTIME_ASSETS` | 모델 가중치·외형 참조 사진 등 **읽기** 전용 자산의 뿌리 | 개발 배치의 `../local` 이 실제로 있으면 그것, 없으면 **없음** |
| `MISSION_RUNTIME_STATE` | 운영자 수정 장부처럼 런타임이 **쓰는** 상태의 뿌리 | `$XDG_STATE_HOME/mission_runtime`, 없으면 `~/.local/state/mission_runtime` |

설치 트리에는 쓰지 않는다 — 설치물은 패키지 관리자의 것이고 거기에 런타임 상태가
섞이면 같은 버전이 기계마다 다른 것이 된다(AI-B-02). 홈 디렉터리가 쓰기 가능하지
않은 컨테이너·폐쇄망에서는 `MISSION_RUNTIME_STATE` 로 자리를 준다(AI-C-16).

자산 뿌리가 없는 배치에서도 관제 콘솔은 그대로 뜬다:

```bash
python tools/fms_console/serve.py --port 8800     # http://127.0.0.1:8800/
#   assets: none (set $MISSION_RUNTIME_ASSETS to enable model-backed evidence)
#   evidence path: disabled (no_embedding_model_available)
```

`/api/bootstrap` · `/api/scene` · `/api/domain` · `/api/zone` · `/api/robot` 는 전부
200 이고, 근거 경로만 꺼진다 — `/api/samples` 가 `available: false` 와 사유를,
`/api/explain` 이 `503 no_evidence_path:<사유>` 를 낸다. 자산 유무를 **인자 실수와
구분해서** 답하는 것이 요점이다(AI-C-05).

콘솔에서 **개발자가 아닌 사람이** 하는 일은 「배포」 탭에 모여 있고, 네 가지가 실제
순서대로 선다.

| 하는 일 | 필요한 능력 | 뒤에서 판정하는 쪽 |
|---|---|---|
| 로봇·카메라 들이기(조인 선언 1건 → 설정 한 줄 + 남은 할 일) | `may_onboard_device` | `registry/onboarding.py` |
| 카메라 정보 입력 → 보정 실행 | `may_calibrate` | `edge/calibration_profile.py` |
| 확인된 후보로 학습 · 검증 · 승인 요청 | `may_request_training` | `continual/` |
| 승인 · 기기별 모델 교체 · 범위 넓히기 · 되돌리기 | `may_deploy_model` | `runtime/model_assignment.py` + `runtime/mlops_pipeline.py` |

권한이 없는 구역은 비는 대신 **무슨 능력이 필요한지**를 적는다 — 빈 목록은 "할 일이
없다"와 "볼 수 없다"를 구분하지 못한다. 적어 넣은 카메라 제원은 관측이 아니므로
그것만으로 활성 보정 프로파일이 되지 않고, 보정판이 실제로 측정한 값과 비교되는
기준이 된다. 보정판 캡처가 없는 설치에서는 선언만 받고 `not_measured` 로 남는다.

### 실제로 다 올려서 돌리기

시험의 skip 은 "안 되는 것"이 아니라 "이 기계에 그 도구·자산이 없다"는 뜻이다. 전부
올리면 skip 이 줄고 같은 시험이 실물로 돈다.

```bash
# 1) 전송·관측 스택 (docker)
make up                                   # mosquitto 1883 · kafka · otel-collector 4317

# 2) 모델 가중치 — 공개 트리 밖(local/)에 둔다
#    CLIP ONNX · OWL-ViT ONNX · yolov8n · yolov8s-worldv2 · FastSAM-s
#    자리는 MISSION_RUNTIME_ASSETS 로 바꿀 수 있다(기본 ../local).

# 3) 선택 파이썬 패키지
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install ultralytics transformers

# 4) 가시화 콘솔 (Node 22.6+)
cd third_party/vz-web-dashboard && npm install && cd -

# 5) 전부 올린 상태로
AIF_OTEL_OUTPUT="$PWD/deploy/integration/artifacts/output.json" pytest -q
```

이 저장소의 기준 기계에서 그렇게 돌린 결과는 **1696 passed · 8 skipped** 이고, 남은
8 개는 성격이 분명하다 — 6 개는 실제 SSH 장치·무선 신호가 필요하고(하드웨어),
1 개는 이 노드에 OpenCL 플랫폼이 없고, 1 개는 `transformers` **부재** 경로를 검증하는
시험이라 설치된 환경에서는 대상이 아니다.

무엇이 실물로 도는지:

| 시험 | 실물 |
|---|---|
| `test_real_stack.py` | CLIP ONNX 가중치 · 이 기계의 가속기 계측 · mosquitto 왕복 |
| `test_clip_dictionary_provider.py` | CLIP ONNX + 실제 스캔 프레임 + 기록된 근거 박스 |
| `test_open_vocabulary.py` | OWL-ViT ONNX + 사람이 찍힌 실제 사진 |
| `test_rpn_propose.py` · `test_yolo_world_provider.py` · `test_fastsam_provider.py` | 실제 YOLO 가중치 추론(CPU) |
| `test_grounding_dino_provider.py` | transformers + 실제 모델 |
| `test_mqtt_transport.py` · `test_kafka_bridge.py` · `test_otel_observability.py` | 실제 브로커·Kafka·OTel 수집기(수집기 출력 파일에 우리 데이터가 들어온 것까지) |
| `test_model_config.py` | 설정 파일 하나로 provider 다섯을 실제 가중치로 조립 |

### 컨테이너로 받았다면 — docker 는 소프트웨어 환경만 고정한다

```bash
docker compose up                        # 관제 콘솔 + 브로커 (CPU). 가장 짧은 길
docker compose --profile gpu up          # GPU 가속 변종
docker compose --profile detectors up    # ultralytics 탐지기 (AGPL-3.0)
docker compose run --rm preflight        # 이 환경에서 무엇이 되는지만 본다
```

빌드 대상은 셋이고 **서로 다른 세 이유로** 갈려 있다. 하나로 합치면 셋 중 하나만 필요한
사람이 나머지 둘의 대가를 함께 치른다.

| 대상 | 무엇이 더 들어가는가 | 대가 |
|---|---|---|
| `cpu`(기본) | 없다 — 벤더 가속기 런타임을 넣지 않는다(원칙 #1) | 없다. 받는 사람 대부분이 이것이면 된다 |
| `cuda` | CUDA 런타임 베이스 이미지 · `onnxruntime-gpu` | 이미지가 수 GB 로 커진다. **드라이버는 들어가지 않는다** |
| `detectors` | `ultralytics`(YOLO-World · YOLOE · FastSAM) | **AGPL-3.0** — 쓰기로 하는 것이 라이센스 선택이다 |

```bash
docker build --target cpu       -t mission-runtime:cpu .         # 기본
docker build --target cuda      -t mission-runtime:cuda .        # GPU 변종
docker build --target detectors -t mission-runtime:detectors .   # AGPL 탐지기
docker run --rm mission-runtime:cpu                              # 이 노드가 가진 자원 태그를 찍는다
```

**하드웨어 환경은 docker 가 고쳐 주지 않는다.** 커널 모듈은 호스트에 있고 호스트가
`--gpus` 로 넘기지 않으면 컨테이너도 GPU 를 못 쓴다. 호스트 드라이버가 깨져 있으면
컨테이너도 **함께** 깨진다 — 이미지를 바꿔서 빠져나갈 수 있는 자리가 아니다. 그래서
자가 점검을 띄운 **안에서** 돌린다(`docker compose run --rm preflight`): 호스트가
무엇을 넘겼는지는 띄워 보고 물어야 안다.

`ultralytics` 는 **AGPL-3.0** 이고 핵심 의존성 넷(jsonschema MIT · numpy BSD-3 ·
opencv-python Apache-2.0 · protobuf BSD-3)과 성격이 다르다.
이것을 쓰는 서비스를 네트워크로 제공하면 그 결합 저작물에 소스 공개 의무가 따른다. 기본
이미지에 넣지 않은 이유가 그것이고, 쓰기로 하는 것은 받는 쪽의 선택이다. **이 프로젝트
자신의 라이센스는 아직 정해지지 않았다** — 그래서 여기서도 정하지 않고 분리만 해 둔다.
어느 쪽으로 정해도 이미지를 다시 설계하지 않는다.

실제 현장 선언(`profiles/domains.json` · `config/status_ui.json`)은 **일부러 이미지에서
빠진다**(`.dockerignore`). 들어가면 받는 사람이 우리 현장의 구역·좌표·장치 식별자를 함께
받게 되고, 선언은 배치가 공급하는 자료이지 배포물의 일부가 아니다(AI-C-15). 콘솔 기본값은
아직 그 현장 파일을 가리키므로 compose 가 `--ui-config`·`--zone-profile` 로 **예시 선언을
명시로** 넘긴다 — 자기 현장을 쓸 때는 그 두 플래그를 자기 선언으로 바꾸고 그 디렉터리를
볼륨으로 넣는다. 자격증명·모델 가중치·운영자 수정 장부도 같은 이유로 이미지에 굽지 않고
볼륨으로 받는다. 그래서 처음 띄우면 compose 가 `./assets` 디렉터리를 만든다 — 자기
가중치를 그 자리에 넣고, 비워 두면 모델 기반 근거만 비활성이다.

확인한 범위를 분명히 해 둔다. `cpu` 대상은 이 기계에서 **그 이미지 안에서** 자가 점검과
전체 시험을 돌려 확인했다(위의 `정상 11 · 축소 13 · 막힘 0` 과 `3251 passed` 가 그
측정이다). `cuda` 대상은 **이 기계에서 빌드하지 않았다** — 베이스 이미지가 수 GB 이고
가속기를 다른 작업이 쓰고 있었다. 셋의 경계 자체는
`tests/test_distribution_images.py` 가 고정한다: 기본 이미지에 벤더 런타임이 없는가 ·
AGPL 의존성이 자기 대상에만 있는가 · 현장 선언과 자격증명이 빠지는가 · 어떤 서비스도
라이센스를 선점하지 않는가.

## 눈으로 확인하는 법 — 명령 하나

```bash
make view          # 운영 상태 화면 + 가시화 콘솔을 함께 → http://127.0.0.1:8770
make view-solo     # 우리 화면만
make preview       # 서버 없이 열리는 한 장으로 내보내기
```

`make view` 는 우리 화면을 띄우고, `third_party/vz-web-dashboard` 에 `npm install` 이
끝나 있으면 가시화 콘솔도 같은 명령으로 함께 올려 **「가시화 콘솔」 탭**에 붙인다. Node 가
없거나 콘솔이 없으면 우리 화면만 뜬다 — 선택 구성요소 결손은 축소이지 실패가 아니다.
이미 떠 있는 콘솔은 다시 띄우지 않고 그대로 쓴다(포트를 빼앗지 않는다).

### 탭 — 역할에 따라 보이는 것이 다르다

| 탭 | 구역 | 무엇 |
|---|---|---|
| 🛰️ 종합 | B · D | 상태 집계 타일 · 미션 · 가속기별 배치 · 최근 사건 · 지금 할 만한 일 |
| 🗺️ 실행 그래프 | C | 노드 카드(상태·서비스·가속기·회차) · 실선/점선/병렬 · 참조 간선 |
| 🔎 노드 상세 | F · G · H | 담당 서비스와 실행 가속기를 **따로** · 판정 3축 · 노드별 로그 |
| 📮 외부 요청 | I | 6단계 스테퍼(③ 서버 구간은 빗금) · 배포 · 재실행 · 최종 판정 |
| 🖥️ 자원·지표 | E · E′ | 가속기 개체별 사용률·온도 · 보드 · 서비스 모델 · 지표 추이와 목표선 |
| 🧠 산출·추천 | — | 접지된 단계 · 거부 사유 · 외부 요청 후보 · 임무 후보와 막힌 사유 |
| 🧾 원본 메시지 | — | 와이어 메시지 그대로 |
| 🖼️ 가시화 콘솔 | — | 복사해 온 가시화 콘솔(돌고 있을 때만 나타난다) |

역할은 **서버가 데이터로 선언**한다(`/api/views`). 새 역할은 그 표에 한 줄이고 화면
코드를 고치지 않는다.

| 역할 | 보이는 탭 | 왜 |
|---|---|---|
| 👀 관람(시연) | 종합 | 외부 관람용. 식별자와 내부 사유 토큰을 가린다 |
| 🎛️ 운영자 | + 그래프 · 노드 상세 · 외부 요청 | 지금 무엇이 돌고 무엇이 막혔는지 |
| 📊 분석 | + 자원·지표 · 산출·추천 | 추이와 근거까지 |
| 🧰 관리자 | + 원본 메시지 | 계약을 확인하는 역할 |

**화면에서 가리는 것은 보기 편하게 하려는 것이고 접근 통제가 아니다.** 실제 차단은
백엔드가 역할·범위로 한다(BE-Q-04). 화면 바닥에 그 문장을 띄워 둔다.

### 볼 항목을 나누는 축

필터 한 줄이 네 축을 준다 — **역할 · 구역 · 장비(가속기) · 기능(서비스)**. 장비·기능을
좁히면 그래프·자원·사건이 그 대상만 남는다. 축의 값은 화면에 박혀 있지 않고 실측
가속기와 수신한 메시지에서 나온다.

### 표시 규칙 몇 가지

- **상태는 색·아이콘·글자를 항상 함께** 쓴다. 색만으로 뜻을 전달하지 않는다.
- 크기(사용률)는 한 색의 농도로, 상태는 상태색으로 가른다 — 두 축을 섞지 않는다.
- 임계는 막대 위 **실제 값 위치**에 눈금으로 서고, 목표 기준선도 추이 그래프의 실제
  값 축에 놓인다. 임의 위치에 고정된 기준선은 쓰지 않는다.
- 측정이 없으면 "측정 없음"이라고 적는다. 0 으로 그리면 미달로 보인다.
- 실측과 예시를 배지로 가른다. 섞어 보여 주면 데모가 실제보다 잘 도는 것처럼 보인다.
- 색 팔레트는 검증기(`validate_palette.js`)를 통과한 것을 쓴다.

### 기능별로 따로 보려면

```bash
curl -s localhost:8770/api/views        | python3 -m json.tool   # 역할·탭·필터 축
curl -s localhost:8770/api/snapshot     | python3 -m json.tool | head -40
curl -s localhost:8770/api/proposal      # 서브태스크 접지
curl -s localhost:8770/api/recommendation
curl -s localhost:8770/api/console       # 가시화 콘솔 상태
```

쓰기 요청은 405 와 사유 토큰으로 거절한다.

### 같은 것을 시험으로

```bash
pytest -q tests/test_snapshot_ui.py tests/test_status_wire.py tests/test_real_stack.py
```

`tests/test_real_stack.py` 는 실제 모델 가중치·이 기계의 가속기 계측·실제 MQTT
브로커로 돈다(없으면 그 묶음만 skip).

### 가시화 콘솔은 복사해 온 것이다

`third_party/vz-web-dashboard/` 는 가시화 파트의 운영 콘솔을
`github.com/choBottle/Physical-Project-mk2` · `main` @ `30f5ee9` 에서 **그대로
복사(clone)해 온 것**이다. 우리가 만든 코드가 아니고 내용을 고치지 않는다 — 출처와
경계는 [third_party/README.md](third_party/README.md) 에 적었다. 처음 한 번:

```bash
cd third_party/vz-web-dashboard && npm install     # Node 22.6+ 필요
```

두 화면의 데이터가 아직 붙지 않는 이유는 그쪽 게이트웨이 채널 목록에 `status_snapshot`
이 없기 때문이고, 채널 개설은 백엔드 결정이다([docs/integration-handover.md](docs/integration-handover.md)).

## 확장하는 법

새 센서·모델·런타임·전송 기술은 **핵심 코드 수정이 아니라 등록**으로 붙인다.

1. 해당 Protocol(`providers/adapters.py`)을 구현한다.
2. capability kind 와 실행 조건을 `ProviderRegistration` 으로 등록한다 — 코드가
   아니라 `config/providers.example.json` 같은 데이터로도 된다.
3. 실측 전에는 품질·지연·자원을 다른 구성의 값으로 채우지 않는다. 미측정은 미측정으로
   남긴다.

절차와 예시는 [docs/guides/extending.md](docs/guides/extending.md), 어떤 외부 기술이
어떤 경계 뒤에 있는지는 [docs/technology-boundaries.md](docs/technology-boundaries.md),
구조 전체는 [docs/architecture.md](docs/architecture.md) 를 본다.

## 다른 파트와 붙일 때

파트 경계를 넘는 계약은 `schemas/` 와 `specs/` 에 있고, 메시지 예시는 손으로 적지
않고 **생산 코드에서 생성해** 커밋한다(시험이 둘이 같은지 매번 확인한다). 통합 시점에
다른 파트가 바꿔야 하는 것은 [docs/integration-handover.md](docs/integration-handover.md)
에 모여 있다.
