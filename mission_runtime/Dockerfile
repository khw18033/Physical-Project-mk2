# implements: AI-B-02
#
# 실행환경 패키징·재현성 관리. 컨테이너는 "현재 운영 후보 패키징 방식"일 뿐이며,
# 이 이미지 안의 코드는 컨테이너·오케스트레이터 없이도 그대로 실행된다
# (AI-B-02: "애플리케이션 기능이 특정 컨테이너 엔진이나 오케스트레이터를 직접
# 요구해서는 안 된다").
#
# 벤더 가속기 런타임을 베이스 이미지에 넣지 않는다 — 가속기는 노드 태그로 발견되는
# 선택 자원이다 (원칙 #1, AI-B-04).

FROM python:3.10-slim

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
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "from mission_runtime.providers.compute import discover_node_tags; discover_node_tags()"

# 기본 명령은 상태 확인 한 번이다 — 이미지가 무엇을 "서비스"로 띄울지는
# 배포가 정한다(AI-B-02: 기능이 특정 실행 기술을 요구하지 않는다).
CMD ["python", "-c", "from mission_runtime.providers.compute import discover_node_tags; print(sorted(discover_node_tags()))"]
