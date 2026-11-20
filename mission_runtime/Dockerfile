# implements: AI-B-02
#
# 실행환경 패키징·재현성 관리. 컨테이너는 "현재 운영 후보 패키징 방식"일 뿐이며,
# 이 이미지 안의 코드는 컨테이너·오케스트레이터 없이도 그대로 실행된다
# (AI-B-02: "애플리케이션 기능이 특정 컨테이너 엔진이나 오케스트레이터를 직접
# 요구해서는 안 된다").
#
# 벤더 가속기 런타임을 베이스 이미지에 넣지 않는다 — 가속기는 노드 태그로 발견되는
# 선택 자원이다 (원칙 #1, AI-B-04).

# 빌드 대상 셋. 받는 쪽이 **자기 환경에 맞는 것을 고른다** —
#
#   docker build --target cpu       -t mission-runtime:cpu .        (기본)
#   docker build --target cuda      -t mission-runtime:cuda .
#   docker build --target detectors -t mission-runtime:detectors .
#
# 왜 하나로 하지 않는가
# ---------------------
# 셋이 **서로 다른 세 가지 이유**로 갈린다. 하나로 합치면 셋 중 하나만 필요한
# 사람이 나머지 둘의 대가를 함께 치른다.
#
# `cpu`
#     벤더 가속기 런타임을 넣지 않는다(원칙 #1). 관제·트윈·판단·계획이 전부
#     여기서 돈다. 받는 사람 대부분이 이것이면 된다.
# `cuda`
#     GPU 가속이 필요한 배치. **드라이버는 이 이미지에 들어가지 않는다** — 커널
#     모듈은 호스트에 있고, 호스트가 `--gpus` 로 넘겨주지 않으면 이 이미지도
#     GPU 를 못 쓴다. 호스트 드라이버가 깨져 있으면 컨테이너도 함께 깨진다.
#     Docker 가 고쳐 주지 않는 자리이고, `tools/preflight.py` 가 그 경우를
#     사유와 함께 말한다.
# `detectors`
#     ultralytics 기반 탐지기(YOLO-World·YOLOE·FastSAM)를 더한다. **이 패키지는
#     AGPL-3.0 이고 나머지 의존성과 라이센스가 다르다** — 네트워크로 서비스하는
#     결합 저작물에 소스 공개 의무가 따른다. 기본 이미지에 넣지 않는 이유가
#     그것이고, 쓰기로 하는 것은 받는 쪽의 선택이다. 이 프로젝트의 라이센스는
#     아직 정해지지 않았으므로 **여기서도 정하지 않는다** — 분리만 해 둔다.
FROM python:3.10-slim AS cpu

# opencv-python-headless를 쓰므로 GUI 라이브러리는 설치하지 않는다.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 이 프로젝트는 루트가 곧 패키지 루트다(`mission_runtime/mission_runtime` 이중 경로를
# 두지 않는다). 그래서 디렉터리를 하나씩 세는 대신 프로젝트를 그대로 넣고, 넣지 않을
# 것은 `.dockerignore` 한 곳에서 정한다 — 모듈을 하나 추가할 때마다 Dockerfile 을
# 고쳐야 하는 구조는 결국 빠뜨린다.
COPY . .

RUN pip install --no-cache-dir -e ".[dev]" \
    && pip install --no-cache-dir --force-reinstall opencv-python-headless

# 상태 확인 규약은 오케스트레이터와 분리돼 있어 K3s probe에도, standalone
# supervisor에도 같은 명령이 쓰인다 (AI-B-07).
# 자가 점검을 상태 확인으로 쓴다 — 핵심이 막혔을 때만 0 이 아니고, 선택 기능
# 결손으로는 실패하지 않는다(AI-C-05). 태그만 세면 "모듈이 import 된다" 까지만
# 알 수 있고 "이 환경에서 무엇이 되는가" 는 알 수 없다.
HEALTHCHECK --interval=30s --timeout=20s --start-period=10s --retries=3 \
    CMD python tools/preflight.py >/dev/null

# 기본 명령은 상태 확인 한 번이다 — 이미지가 무엇을 "서비스"로 띄울지는
# 배포가 정한다(AI-B-02: 기능이 특정 실행 기술을 요구하지 않는다).
CMD ["python", "-c", "from mission_runtime.providers.compute import discover_node_tags; print(sorted(discover_node_tags()))"]


# --- GPU 가속 변종 -----------------------------------------------------------
#
# 베이스 이미지가 벤더를 가리키는 것은 **배포 프로파일의 선택**이고 핵심 코드는
# 이 사실을 모른다(원칙 #1·#2, AI-B-02). 상위 기능은 `compute.gpu` 태그로
# 발견되는 선택 자원만 보고, 태그가 없으면 CPU 로 내려간다(AI-C-05).
#
# 호스트가 넘겨주지 않으면 이 이미지도 GPU 를 못 쓴다:
#   docker run --gpus all mission-runtime:cuda python tools/preflight.py
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04 AS cuda

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

RUN python3 -m pip install --no-cache-dir --upgrade pip \
    && python3 -m pip install --no-cache-dir -e ".[dev]" \
    && python3 -m pip install --no-cache-dir --force-reinstall opencv-python-headless \
    && python3 -m pip install --no-cache-dir onnxruntime-gpu

# 자가 점검을 상태 확인으로 쓴다. 태그만 세면 "떴다" 와 "쓸 수 있다" 가 구분되지
# 않는다 — GPU 변종에서는 그 차이가 이 이미지의 존재 이유다.
HEALTHCHECK --interval=30s --timeout=20s --start-period=10s --retries=3 \
    CMD python3 tools/preflight.py >/dev/null

CMD ["python3", "tools/preflight.py"]


# --- 탐지기 변종 (AGPL-3.0 의존성 포함) --------------------------------------
#
# **이 이미지를 쓰는 것은 라이센스 선택이다.** `ultralytics` 가 AGPL-3.0 이므로
# 이것으로 서비스를 네트워크 제공하면 결합 저작물에 소스 공개 의무가 따른다.
# `cpu` 위에 얹는 이유: 탐지기가 필요한 사람이 GPU 까지 필요한 것은 아니다 —
# 두 축이 독립이어서 합치면 한쪽만 필요한 사람이 양쪽 대가를 치른다.
FROM cpu AS detectors

RUN pip install --no-cache-dir ultralytics

CMD ["python", "tools/preflight.py"]
