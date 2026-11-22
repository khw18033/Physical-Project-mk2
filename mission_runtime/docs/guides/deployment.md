# 다른 기계에 배포하기 — 이 폴더 하나로 백엔드를 세운다

대상: `mission_runtime/` 폴더만 받은 사람. 상위 디렉터리도, 자산(`local/`)도, 내부
문서도 필요 없다 — 없으면 **그 기능만** 비활성이고 그 사실이 응답과 기동 로그에
적힌다(AI-C-05).

이 폴더가 오는 길은 둘이다.

```bash
git clone -b jny_AI <팀 저장소> mission-runtime && cd mission-runtime/mission_runtime
```

그 브랜치는 **이 폴더 하나만** 담는다(상위에 `internal/` · `local/` 이 없다) — 작업
저장소의 같은 이름 브랜치와 달리 공개 범위만 들어 있고, 그 모양을 만드는 것이 아래
도구다. 보내는
쪽에서 그 브랜치를 만드는 것도 손이 아니라 도구다 — 공개 목록의 정본은
`git ls-files mission_runtime` 이고 `tools/release/make_dist.py` 가 그것을 그대로
옮긴다. 커밋되지 않은 변경이 공개 폴더에 남아 있으면 **거절한다**: 그대로 올리면 그
변경은 들어가지 않고 들어가지 않았다는 사실도 받는 쪽에 보이지 않는다.

```bash
python tools/release/make_dist.py                 # 무엇을 담을지 보기만 한다
python tools/release/make_dist.py --export /tmp/d  # 그 트리를 꺼내 확인한다
python tools/release/make_dist.py --write          # 브랜치를 옮긴다(푸시는 사람이 한다)
```

---

## 0. 한 줄로 끝내기

```bash
bash tools/install_check.sh
```

가상환경을 만들고, 설치하고, 이 기계에서 무엇이 되는지 보고, 계약 시험을 돌리고,
게이트웨이를 **실제로 띄워** 조회 계약이 서는지까지 확인한 뒤 다음 명령을 찍어 준다.
종료 코드는 **핵심이 서지 못했을 때만** 0 이 아니다 — 선택 기능 결손은 축소이지
실패가 아니다.

```bash
bash tools/install_check.sh --extras mqtt,redis   # 선택 전송·스트림까지
bash tools/install_check.sh --skip-tests          # 빠른 확인
bash tools/install_check.sh --offline             # 내부 wheelhouse 만 쓴다(폐쇄망)
```

기준 기계에서 받은 그대로 돌린 결과는 **정상 17 · 축소 8 · 막힘 0** 이고 시험은
**실패 0** 이다. 축소 8 은 고장 8 이 아니다 — MQTT·Kafka·Redis·OTel·ONNX·PyTorch·
ultralytics·모델 자산이 없다는 뜻이고, 핵심은 전부 돈다.

---

## 1. 무엇이 필요한가

| | |
|---|---|
| **필수** | Python >= 3.10, 그리고 `python3-venv`(데비안 계열) |
| 핵심 의존성 | `jsonschema` · `numpy` · `opencv-python` · `protobuf` — 설치가 받아 온다 |
| 선택 | `.[mqtt]` `.[kafka]` `.[redis]` `.[otel]` `.[metrics]` · `onnxruntime` · `torch` · `ultralytics`(**AGPL-3.0**) |
| 선택 외부 도구 | `docker`(브로커 스택) · `kubectl`(오케스트레이터 배치) · `mosquitto` · `ssh` |

인터넷이 없는 기계는 `--offline` 과 wheelhouse 를 쓴다(§7).

---

## 2. 손으로 하는 설치

```bash
cd mission_runtime
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python tools/preflight.py      # 이 기계에서 무엇이 되고 왜 안 되는가
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 OTEL_SDK_DISABLED=true .venv/bin/python -m pytest -q
```

`preflight` 의 세 상태를 섞어 읽지 않는다.

| 표시 | 뜻 | 할 일 |
|---|---|---|
| `[o]` | 그대로 된다 | 없다 |
| `[~]` | **그 기능만** 꺼지고 나머지는 돈다 | 그 기능이 필요하면 「얻는 방법」 줄을 따른다 |
| `[x]` | 쓸 수 없다 | 무엇을 하면 되는지 함께 적힌다 |

`pytest` 의 skip 도 같다 — "안 되는 것" 이 아니라 "이 기계에 그 도구·자산·브로커가
없다" 는 뜻이고, 사유에 **무엇이 없어서 어느 묶음만 비활성인지** 적힌다.

---

## 3. 백엔드를 세우는 명령

### 3-1. 게이트웨이 — 이것 하나가 백엔드다

```bash
.venv/bin/python tools/vz_gateway/serve.py --port 8899 \
    --domains profiles/domains.example.json \
    --config  config/status_ui.fms.example.json
```

같은 포트에 **다른 계약 둘**이 선다(AI-O-06).

```
vz_gateway: ws://127.0.0.1:8899  ·  http://127.0.0.1:8899/registry
vz_gateway: FMS 조회 계약 — 조회 경로 28개
vz_gateway: FMS 쓰기 계약 — 쓰기 경로 19개 · Bearer 세션
```

- 읽는 이름과 쓰는 이름이 겹치지 않고, **조회 경로의 POST 는 본문을 읽기 전에 405** 다.
- 세션은 쿠키가 아니라 `Authorization: Bearer` 다 — 가시화 앱이 다른 출처라
  교차 출처 쿠키는 CSRF 를 연다. 토큰은 `/api/login`·`/api/assume` 응답 **본문**에 있다.
- 자주 쓰는 깃발

  | 깃발 | 무엇 |
  |---|---|
  | `--accounts PATH` | 계정 파일의 자리. 없으면 조회만 열린다 |
  | `--no-write-api` | 쓰기를 열지 않는다(관찰 전용 포트가 된다) |
  | `--overlay PATH` | 운영자 수정 장부. 파일도 디렉터리도 받는다 |
  | `--fleet` | 선언된 로봇을 이 프로세스에서 세운다(장치 러너가 이미 돌면 주지 않는다) |
  | `--broker H:P` | 실제 MQTT 브로커로 장치 경로를 돌린다 |
  | `--camera URL\|N\|FILE` + `--weights PATH` | 탐지를 켠다(§4) |
  | `--redis URL` | 실증 스트림에서 탐지를 **받아 온다**(§4) |

설정 파일을 옮길 때 주의: 선언 파일은 **형제 파일을 상대 경로로** 가리킨다
(`providers.hardware.example.json` 등). 옮기면 게이트웨이가 조용히 좁은 쪽을 쓰지 않고
사유와 함께 **API 를 세우지 않는다**.

```
vz_gateway: FMS 조회 계약 — 세우지 못했다 — FileNotFoundError: …/providers.hardware.example.json
```

### 3-2. 첫 계정

계정 파일이 하나라도 생기면 비밀번호 없는 예시 자세(`/api/assume`)가 닫히고 익명 조회도
닫힌다. 그때는 `/api/login` 으로 들어온다.

```bash
.venv/bin/python -m tools.view_service.accounts add admin --role admin --path ./accounts.json
.venv/bin/python tools/vz_gateway/serve.py --port 8899 --accounts ./accounts.json \
    --domains profiles/domains.example.json --config config/status_ui.fms.example.json
```

### 3-0. 한 줄로 세우고 한 줄로 내린다 (받은 기계에서 쓰는 길)

```bash
make backend          # = bash tools/backend.sh start
make backend-status   # 주소와 상태
make backend-stop     # 내린다
```

**도커가 있으면 컨테이너로 세운다**(`deploy/backend/docker-compose.yml`) —
`restart: unless-stopped` 라 터미널을 닫아도, 기계를 다시 켜도 돈다. 도커가 없는
기계도 정상이다: 그때는 프로세스로 띄우고 **그렇다고 말한다**(AI-C-05).
`AIF_MODE=bare` 로 강제할 수 있다.

**세우는 것은 둘이다** — 가시화가 읽는 자리가 둘이기 때문이다.

| 포트 | 무엇 | 없으면 화면에서 |
|---|---|---|
| 8899 | `/registry` · WS 채널 · FMS 조회 30(쓰기 20 은 Bearer) | 「게이트웨이 연결 안 됨」 |
| 8765 | capability — `config` · `labels` · `functions` · `functions/whatif` | 「기능 · HTTP 502」 ← 실제로 이 증상이 있었다 |

이미지는 **소스보다 오래되면 다시 굽는다**. 태그만 보면 2 주 전 이미지로 오늘
코드를 돌리게 되고, 그때 컨테이너는 모르는 깃발로 재시작 루프에 빠진다(실측).
받는 쪽에서는 더 조용히 틀린다 — 옛 계약을 내면서 멀쩡히 돈다.

pid·로그는 설치 트리가 아니라 상태 뿌리(`~/.local/state/mission_runtime/backend/`)다.
`git pull` 이 충돌하지 않는다.

#### 호스트의 docker·k3s 를 몰아야 한다면

컨테이너 안에서는 `docker` 도 `kubectl` 도 없다. `POST /api/stack` 의 compose 단위는
`docker_not_available` 로 거절되고 **그 사유가 화면에 그대로 뜬다**(조용히 빠지지
않는다). 그 기능까지 쓰려면 둘 중 하나다.

```bash
AIF_MODE=bare bash tools/backend.sh start          # 호스트에서 프로세스로 (개발 기계에 간단)
AIF_HOST_CONTROL=1 bash tools/backend.sh start     # 컨테이너에 호스트 docker·kubeconfig 를 얹는다
```

뒤쪽은 **권한을 주는 일**이다 — 소켓을 얹은 컨테이너는 호스트에서 아무 컨테이너나
띄울 수 있다(사실상 호스트 root). 그래서 기본이 아니고, 쓰는 쪽이 한 번 더 말해야 붙는다.

---

### 3-0-1. 원본 가시화(khw_VZ)가 우리에게서 **읽어 가는 것**

가시화를 고치지 않는 구성에서, 그쪽이 백엔드에 거는 창구는 아래가 전부다. 앱은
우리 쪽으로 무엇을 밀어 넣지 않는다 — **떠 있는 것을 읽어 간다**(`data_stream` 과
같은 모양이다).

| 가시화가 읽는 것 | 어디서 고르나 | 우리가 내나 |
|---|---|---|
| WS 채널 구독 (`subscribe`·`unsubscribe`·`role`) | `VITE_GATEWAY_WS` · 연결 관리 | **낸다** (8899) |
| `GET /registry` | `VITE_GATEWAY_HTTP` | **낸다** |
| `GET /actions?entity=` | 같은 주소 | **없다**(404) — 명령 센터의 action 목록이 빈다 |
| `GET /audit?` | 같은 주소 | **없다** — 데이터 탭의 감사·음성 감사 |
| `GET /insight/<id>` | 같은 주소 | **없다** — 위험 패널의 설명 |
| `GET /server-metrics` | 같은 주소 | **없다** — 셸의 서버 상태 카드 |
| `POST /observability/client-metrics` | 같은 주소 | **없다** — 앱의 자기 관측 적재 |
| capability `config`·`labels`·`functions` | `VITE_CAPABILITY_URL`(기본 `http://127.0.0.1:8765`) | **낸다** (`/api/...`) |
| capability `POST functions/whatif` | 같은 주소 | **낸다** (계산만 한다) |
| 장치 WS(MQTT) · 미디어 · 탐지 · STT · 생성 | `VITE_PHYSICAL_WS` · `VITE_MEDIA_WS` · `VITE_DETECT_URL` · 8801 · 8802 | **우리 것이 아니다** — 브로커·미디어 경로·`data_stream` 추론·가시화 자체 서비스 |

**없는 다섯은 화면을 깨뜨리지 않는다.** 그 카드만 비거나 사유가 뜨고 나머지는 돈다
(그쪽 앱이 결손을 축소로 그린다). 채우려면 게이트웨이에 그 다섯 경로를 더하면 되고,
그것은 우리 조회 계약(30)과 **다른 이름 공간**이라 섞이지 않는다.

---

### 3-2-1. 프론트가 다른 기계일 때 (가시화 앱)

백엔드와 가시화 앱이 서로 다른 노트북이면 세 가지만 다르다.

```bash
# 백엔드 — 모든 인터페이스에서 듣는다
.venv/bin/python tools/vz_gateway/serve.py --host 0.0.0.0 --port 8899 \
    --domains profiles/domains.example.json --config config/status_ui.fms.example.json
```

```
vz_gateway: ws://100.83.37.9:8899  ·  http://100.83.37.9:8899/registry
vz_gateway: 듣는 주소는 0.0.0.0:8899 이고 위 주소는 오버레이에서 본 이 기계다
```

**듣는 주소와 붙는 주소는 다르다.** 안내문에 `0.0.0.0` 이 적히면 다른 노트북이 그
주소로 붙을 수 없으므로, 와일드카드로 열었을 때 기동 로그는 **오버레이가 말하는 이
기계의 주소**를 적는다. 오버레이를 물어볼 수 없으면 주소를 지어내지 않고 자리표를
넣는다 — 구역 엣지와 서버 사이는 공개 인터넷을 경유하지 않고 보안 오버레이(현재
Tailscale) 위에서만 연결한다(원칙 #10).

가시화 앱 쪽에서 할 일은 **환경변수 둘**이고 그쪽 코드는 고치지 않는다.

```bash
VITE_GATEWAY_WS=ws://100.83.37.9:8899 VITE_GATEWAY_HTTP=http://100.83.37.9:8899 npm run dev
```

교차 출처로 부르는 데 필요한 것은 서버가 이미 낸다 — 실측(2026-11-20, 같은
Tailscale 망의 다른 출처에서):

| 확인한 것 | 결과 |
|---|---|
| `GET /api/scene` (오버레이 주소) | `200` · `Server: FMS/2.2` |
| CORS | `Allow-Origin: *` · `Allow-Methods: GET, HEAD, OPTIONS, POST` · `Allow-Headers: Content-Type, Authorization` |
| 사전 요청 `OPTIONS` | `204` + 같은 머리들 |
| `POST /api/assume` | `200`, 토큰은 응답 **본문**(`session_token`) · `Set-Cookie` **0개** |
| 그 토큰으로 쓰기 | 통과(그 뒤는 업무 검증 — 없는 객체를 고치려 하면 `400`) |
| 토큰 없이 쓰기 | `403` · 틀린 토큰 `401` |
| 조회 경로에 `POST` | 유효한 토큰이 있어도 `405` (본문 읽기 전) |

쿠키를 쓰지 않는 것은 선택이 아니라 경계다 — 앱이 다른 출처이므로 교차 출처 쿠키는
CSRF 를 연다.

### 3-3. 상태 화면 (선택)

```bash
make view        # 운영 상태 화면 (+ 가시화 콘솔이 있으면 함께) → http://127.0.0.1:8770
make view-solo   # 우리 화면만
make preview     # 서버 없이 열리는 한 장으로 내보내기
```

### 3-4. 전송·관측 스택 (선택, docker)

```bash
make up          # mosquitto 1883 · kafka · otel-collector 4317
make down
```

엣지 박스에서 바깥에 열려면 `AIF_BIND=<ip> make up`.

---

## 4. 영상과 탐지를 넣는 세 가지 길

이 백엔드는 **픽셀을 상태 계약으로 내보내지 않는다**(AI-C-08). 아래는 탐지를 만드는
입구이고, 셋 중 **무엇도 없으면 `detections` 를 발행하지 않는다** — 빈 배열조차 보내지
않는다. "보지 않았다" 와 "보았는데 없다" 는 다른 사실이다.

### ① 이 기계가 직접 연다 — 카메라 · 파일 · 네트워크 스트림

```bash
.venv/bin/python tools/vz_gateway/serve.py --port 8899 \
    --camera 0                                   `# 로컬 장치 번호` \
    --camera-id cam-01 --weights /path/to/yoloe.pt
.venv/bin/python tools/vz_gateway/serve.py --camera rtsp://cam/stream --weights …
.venv/bin/python tools/vz_gateway/serve.py --camera http://pi7:8090/stream/1 --weights …
```

마지막 줄이 요점이다 — 로봇이 내는 MJPEG 을 **그대로 한 줄기** 열 수 있다. 가중치는
이 저장소에 없고 `MISSION_RUNTIME_ASSETS` 가 가리키는 자리에서 찾는다(§6).

### ② 브로커에서 받는다

```bash
.venv/bin/python tools/vz_gateway/serve.py --broker 127.0.0.1:1883 …
```

capability 공지와 신선도를 **구독**한다(발행하지 않는다). 브로커를 주지 않으면 화면의
장치는 선언뿐이고 availability 가 offline 으로 남는다.

### ③ 실증 데이터 스트림에서 받는다 (`physical_demo` · `data_stream`)

```bash
pip install -e ".[redis]"
.venv/bin/python tools/vz_gateway/serve.py --redis redis://127.0.0.1:6380/0 --redis-model yoloe …
```

`vision_stream:<소스>:<모델>` 을 읽어 탐지 계약으로 옮긴다. **우리가 카메라를 다시 열지
않는다** — 같은 프레임에 추론기를 두 번 돌리면 GPU 를 두 배로 쓰고 두 화면이 서로 다른
탐지를 말한다(AI-C-19). 읽는 것은 `vision_stream:*` 뿐이고 `camera_stream:*`(원본
픽셀)은 읽지 않는다.

> **이 입구의 생산자는 이 폴더에 없다.** 무엇이 포함되고 무엇이 아닌지는 §5 가 적는다.

---

## 5. `physical_demo` · `data_stream` 과의 경계

같은 현장에서 둘이 함께 돈다. **계약과 소비는 여기 있고, 수집과 중계는 거기 있다.**

| data_stream 이 하는 일 | 이 폴더에 | 자리 |
|---|---|---|
| 소스별 HTTP 풀러(포트 10001~10012) · `/stream` · `/frame?since=` · `/state` 서빙 | **없다** | — |
| Redis 로 흘리기(`camera_stream:*` · `state_stream:*` 쓰기) | **없다** — 읽기만 한다 | `integration/vz_redis_source.py` |
| `stream_data/<소스>/<실행>/` 디스크 기록 | **없다** — 읽기만 한다 | `continual/operational_stream.py` |
| 로봇·파이·360 쪽 송출(`picam_work` · `realsense_work` · `360camera_work`) | **없다** — 장치 쪽 코드다 | — |
| 비전 추론 루프(`vision/vision_infer.py`) | **다른 모양으로 있다** | `integration/vz_detection_feed.py` + `edge/*_provider.py` |
| YOLOE · 깊이 · open-vocabulary 모델 | 있다 | `edge/{yoloe,yolo_world,fastsam,grounding_dino,zipdepth}_provider.py` |
| 360 파노라마 → 원근 뷰 슬라이스(`e2p/`) | 있다 | `edge/equirect_views.py` |
| 검출·추적·거리 | 있다 | `perception/{detection,tracking,obstacle_evidence}.py` |
| 위험물 근거 **카드 그리기**(`vision/hazard_overlay.py`) | **없다 — 외부 트리를 부른다** | §5-1 |

### 5-1. 외부 트리를 부르는 도구 셋

아래 셋은 `physical_demo`(data_stream)의 `vision/` 을 **경로로 불러 쓴다**. 그리는 코드의
주인이 하나여야 두 화면이 같은 검출을 각자 조립하지 않기 때문이다.

```
tools/hazard_card.py              vision/hazard_overlay.py
tools/label_review/draft_vision.py  vision/vision_infer.py
tools/label_review/propagate.py     vision/vision_infer.py
```

자리를 정하는 규칙은 셋이고 **개발 기계의 홈 경로를 박지 않는다** — 남의 기계에 없는
경로는 기본값이 될 수 없다(`tests/test_publishable_surface.py` 가 그것을 고정한다).

1. `PD_DATA_STREAM` 이 있으면 그것이 이긴다.
2. 없으면 홈 아래 `~/data_stream` · `~/physical_demo_data_stream` 중 **실제로 있는** 것.
3. 둘 다 없으면 `~/data_stream` 을 이름으로 들고 있다가 사유 문구에 그 자리를 적는다.

```bash
PD_DATA_STREAM=~/data_stream .venv/bin/python tools/hazard_card.py --draft … --out …
```

**없어도 백엔드는 선다.** 셋 다 라벨·데이터셋 도구이고 런타임 경로가 아니다. 트리가
없거나 그쪽 의존(Pillow 등)이 빠지면 그 도구만 사유와 함께 거절하고, 해당 시험은
`skip` 된다.

---

## 6. 바깥에 쓰는 것, 바깥에서 읽는 것

패키지는 자기 트리 밖에 쓰지 않는다. 자리는 둘이고 둘 다 환경변수로 옮긴다.

| 환경변수 | 무엇 | 기본값 |
|---|---|---|
| `MISSION_RUNTIME_ASSETS` | 모델 가중치·참조 사진 등 **읽기** 전용 자산의 뿌리 | 개발 배치의 `../local` 이 있으면 그것, 없으면 **없음** |
| `MISSION_RUNTIME_STATE` | 운영자 수정 장부처럼 런타임이 **쓰는** 상태의 뿌리 | `$XDG_STATE_HOME/mission_runtime`, 없으면 `~/.local/state/mission_runtime` |

설치 트리에는 쓰지 않는다 — 설치물은 패키지 관리자의 것이고 거기에 런타임 상태가
섞이면 같은 버전이 기계마다 다른 것이 된다(AI-B-02). 홈이 쓰기 불가한 컨테이너·폐쇄망
에서는 `MISSION_RUNTIME_STATE` 로 자리를 준다.

자산 뿌리가 없어도 계약은 전부 뜬다 — 근거 경로만 꺼지고 `/api/samples` 가
`available: false` 와 사유를, `/api/explain` 이 `503 no_evidence_path:<사유>` 를 낸다.

---

## 7. 폐쇄망 (AI-C-16)

인터넷이 닿는 기계에서 바퀴를 모아 두고, 받는 기계에서는 그것만 쓴다.

```bash
# 인터넷이 되는 기계에서
pip wheel -w wheelhouse -e ".[dev,mqtt,redis]"

# 폴더와 wheelhouse 를 함께 옮긴 뒤, 받는 기계에서
bash tools/install_check.sh --offline            # 기본 자리: ./wheelhouse
MISSION_RUNTIME_WHEELHOUSE=/media/usb/wheels bash tools/install_check.sh --offline
```

배경 지도 타일의 **기본값은 타일 없음**이다. 공개 타일 서버를 기본으로 두면 폐쇄망에서
메인 화면이 깨지고 배치 전 검증에 걸린다. 외부 연결을 요구하는 레이어는 선언에
`requires_external_connection` 과 호스트를 적어야 하고, 폐쇄망 선언에서는 그런 레이어를
켜는 선언 자체가 거절된다.

---

## 8. 컨테이너로 받았다면

```bash
docker compose up                        # 게이트웨이 + 브로커 (CPU)
docker compose --profile gpu up          # GPU 가속 변종
docker compose --profile detectors up    # ultralytics 탐지기 (AGPL-3.0)
docker compose run --rm preflight        # 이 환경에서 무엇이 되는지만 본다
```

**하드웨어 환경은 docker 가 고쳐 주지 않는다.** 커널 모듈은 호스트에 있고 호스트가
`--gpus` 로 넘기지 않으면 컨테이너도 GPU 를 못 쓴다. 그래서 자가 점검을 띄운 **안에서**
돌린다.

---

## 9. 받은 뒤 처음 10분

```bash
bash tools/install_check.sh                                   # ① 설치·점검·시험·기동
.venv/bin/python tools/vz_gateway/serve.py --port 8899 \
    --domains profiles/domains.example.json \
    --config  config/status_ui.fms.example.json &             # ② 백엔드
curl -s localhost:8899/api/scene     | python3 -m json.tool | head -20   # ③ 현장·구역
curl -s localhost:8899/api/dashboard | python3 -m json.tool | head -20   # ④ 계층별 지표
curl -s -D- -o /dev/null localhost:8899/api/scene | grep -i '^server'    # ⑤ 계약 판
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8899/api/scene  # ⑥ 405 여야 한다
```

⑥ 이 405 가 아니면 조회와 제어가 한 계약에 섞인 것이고, 그건 관찰이 실행에 개입할 수
있다는 뜻이다(AI-O-06).

구조 전체는 [architecture.md](../architecture.md), 어떤 외부 기술이 어떤 경계 뒤에
있는지는 [technology-boundaries.md](../technology-boundaries.md), 새 센서·모델·런타임을
붙이는 법은 [extending.md](extending.md) 를 본다.
