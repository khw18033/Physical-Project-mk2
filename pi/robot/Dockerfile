# 로봇 온보드 노드 컨테이너 (HW-R)
# ===================================
# 기종은 이미지가 아니라 **환경변수**로 고른다. `HW_CONTROLLER_LINK=go1|ep|sim`
# 하나로 갈리므로 이미지는 하나면 된다 — 기종별로 이미지를 나누면 공통 코어가
# 두 벌이 되고, schema.py 를 고칠 때마다 둘 다 재빌드해야 한다.
#
#   docker buildx build --platform linux/arm64 -t hw-robot:<태그> \
#          -f pi/robot/Dockerfile pi
#
# ⚠ 말단은 aarch64 다. amd64 로 빌드해 밀어 넣으면 exec format error 로 죽는다.
#
# ⚠ 파이썬 3.11 을 쓴다(호스트 pi1 은 3.13). robomaster SDK 가 상정한 버전대이고,
#   컨테이너가 호스트 파이썬과 무관해지는 것이 컨테이너를 쓰는 이유 중 하나다.
FROM python:3.11-slim-bookworm

# libopus: robomaster SDK 의 오디오 경로가 링크한다. 없으면 import 단계에서 죽는다.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libopus0 \
    && rm -rf /var/lib/apt/lists/*

# 공통 의존. robomaster 는 EP 를 쓸 때만 필요하지만, 이미지를 하나로 두는 대가로
# 항상 넣는다 — 기종 전환이 재빌드 없이 env 한 줄이 되는 편이 낫다.
RUN pip install --no-cache-dir \
        paho-mqtt==2.1.0 \
        protobuf==7.36.1 \
        psutil \
        robomaster

WORKDIR /app
COPY common/ /app/common/
COPY robot/ /app/robot/

# 비루트. 단, USB 시리얼(/dev/ttyACM0)을 쓸 때는 compose 에서 dialout 그룹을 준다.
RUN useradd -r -u 10002 hwrobot
USER hwrobot

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python3", "-m", "robot.robot_node"]
