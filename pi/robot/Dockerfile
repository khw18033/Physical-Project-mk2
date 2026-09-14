# 로봇 온보드 노드 컨테이너 (HW-R)
# ===================================
# 기종은 이미지가 아니라 **환경변수**로 고른다. `HW_CONTROLLER_LINK=go1|ep|sim`
# 하나로 갈리므로 이미지는 하나면 된다 — 기종별로 이미지를 나누면 공통 코어가
# 두 벌이 되고, schema.py 를 고칠 때마다 둘 다 재빌드해야 한다.
#
#   docker build -t hw-robot:latest -f pi/robot/Dockerfile pi
#
# 파이에서 직접 빌드하므로 이미 arm64 다. 크로스 빌드(buildx --platform)는 필요 없고,
# 쓰면 amd64 이미지를 밀어 넣어 exec format error 로 죽는 사고만 는다.
#
# ⚠ 파이썬 3.11 을 쓴다(호스트 pi1 은 3.13). RoboMaster SDK 가 상정한 범위이고,
#   컨테이너가 호스트 파이썬과 무관해지는 것이 컨테이너를 쓰는 이유 중 하나다.
FROM python:3.11-slim-bookworm

# ⚠ PyPI 의 `robomaster` 는 쓸 수 없다 — DJI 가 x86·구버전 파이썬용만 올려두어
#   aarch64/3.11 에는 **배포본이 아예 없다**(pip: "from versions: none").
#   그래서 robomaster_ros 저자의 포크를 git 에서 설치한다. 공식 저장소의 결함을
#   고쳐 둔 것이고, 나중에 ROS 2 경로로 가더라도 같은 포크를 쓴다.
#
# libopus-dev / build-essential / git 은 빌드에만 필요해서 같은 레이어에서 지운다.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        git ca-certificates build-essential libopus-dev; \
    pip install --no-cache-dir \
        paho-mqtt==2.1.0 \
        protobuf==7.36.1 \
        psutil \
        numpy numpy-quaternion pyyaml; \
    pip install --no-cache-dir git+https://github.com/jeguzzi/RoboMaster-SDK.git; \
    # 미디어 코덱은 카메라 경로에만 쓴다. EpLink 는 섀시·배터리만 읽으므로 없어도
    # 되지만, 있으면 나중에 영상까지 열 수 있어 최선노력으로 시도한다.
    pip install --no-cache-dir -i https://test.pypi.org/simple/ rm-libmedia-codec \
        || echo "[build] rm-libmedia-codec 미설치 — 카메라 경로만 비활성, 구동에는 무관"; \
    # 여기가 진짜 관문이다. import 가 안 되면 런타임이 아니라 빌드에서 멈춘다.
    python -c "from robomaster import robot; print('[build] robomaster import ok')"; \
    apt-get purge -y --auto-remove git build-essential libopus-dev; \
    apt-get install -y --no-install-recommends libopus0; \
    rm -rf /var/lib/apt/lists/*

# 검증 도구용. Pillow 로 numpy 프레임을 JPEG 로 굽는다(bench/ep_cam_view.py).
# opencv 를 쓰지 않는다 — 90MB 가 늘고, 하는 일은 JPEG 인코딩 하나뿐이다.
# SDK 레이어 뒤에 따로 둔다 — 이 줄이 바뀌어도 위의 긴 빌드가 캐시로 남는다.
RUN pip install --no-cache-dir pillow

WORKDIR /app
COPY common/ /app/common/
COPY robot/ /app/robot/

# 비루트. 단, USB 시리얼(/dev/ttyACM0)을 쓸 때는 compose 에서 dialout 그룹을 준다.
#
# ⚠ spool 디렉터리를 **이미지 안에서** 만들고 소유권을 준다. 도커 named volume 은
#   비어 있을 때 마운트 지점의 내용·소유권을 그대로 복사하는데, 이미지에 그 경로가
#   없으면 root:root 로 생겨 비루트 프로세스가 못 쓴다(실측: spool.py append 에서
#   PermissionError 로 노드가 죽었다). 볼륨이 이미 root 로 생긴 뒤라면 이미지를
#   고쳐도 소용없다 — `docker compose ... down -v` 로 볼륨을 지우고 다시 띄워야 한다.
RUN useradd -r -u 10002 hwrobot \
    && mkdir -p /var/lib/hw-node \
    && chown 10002:10002 /var/lib/hw-node
USER hwrobot

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python3", "-m", "robot.robot_node"]
