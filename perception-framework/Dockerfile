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

COPY pyproject.toml README.md ./
COPY perception_framework ./perception_framework

RUN pip install --no-cache-dir -e ".[dev]" \
    && pip install --no-cache-dir --force-reinstall opencv-python-headless

COPY tests ./tests
COPY profiles ./profiles
COPY examples ./examples
COPY contracts ./contracts

# 상태 확인 규약은 오케스트레이터와 분리돼 있어 K3s probe에도, standalone
# supervisor에도 같은 명령이 쓰인다 (AI-B-07).
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "from perception_framework.providers.compute import discover_node_tags; discover_node_tags()"

CMD ["python", "examples/demo.py"]
