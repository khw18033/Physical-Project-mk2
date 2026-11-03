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
pip install -e ".[dev]"                            # 선택 extra: mqtt / kafka / otel
pytest -q
```

빈 기계에서 그렇게 돌린 결과는 **2004 passed · 47 skipped** 이다. skip 은 "안 되는
것"이 아니라 "이 기계에 그 도구·자산·브로커가 없다"는 뜻이고 사유가 각각 적힌다.

선택 extra 가 없으면 그 provider 만 비활성이다. 다만 **브로커가 떠 있는 기계**에서는
extra 를 같이 깔아야 한다 — 통합 시험 일부가 "브로커에 닿는가" 만 보고 클라이언트
라이브러리가 깔렸는지는 보지 않기 때문에, 포트는 열려 있고 `paho`/`kafka` 는 없는
조합에서 skip 대신 실패한다.

```bash
pip install -e ".[dev,mqtt,kafka,otel]"           # 1883/9092/4317 이 열려 있는 기계
```

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

```bash
docker build -t mission-runtime:dev .     # 패키징도 같은 시험으로 확인한다
docker run --rm mission-runtime:dev       # 이 노드가 가진 자원 태그를 찍는다
```

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
