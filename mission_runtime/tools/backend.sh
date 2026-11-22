#!/usr/bin/env bash
# 백엔드를 **한 줄로** 세우고 내린다. 가시화는 건드리지 않는다.
#
# implements: AI-B-02(재현 가능한 실행), AI-B-05(lifecycle), AI-C-05(없으면 그 조각만)
# tests: tests/test_backend_sh.py
#
#   bash tools/backend.sh start     세운다 (터미널을 닫아도, 기계를 다시 켜도 돈다)
#   bash tools/backend.sh stop      내린다
#   bash tools/backend.sh status    주소와 상태를 적는다
#   bash tools/backend.sh restart
#
# ## 왜 스크립트 하나인가
#
# 백엔드는 **프로세스 둘**이다 — 가시화가 읽는 자리가 둘이기 때문이다:
#   게이트웨이(8899)  /registry · WS 채널 · FMS 조회 30 · 쓰기 20
#   상태 패널(8765)   가시화 「기능」 카드의 원천(capability: config · labels · functions)
# 손으로 둘을 띄우면 하나를 잊고, 잊은 쪽은 화면에서 **빨간 줄 하나**로만 보인다
# (실측 2026-11-22: 8765 를 안 띄워 「기능 · HTTP 502」가 떠 있었다).
#
# ## 자리는 상태 뿌리다
#
# pid·로그는 설치 트리가 아니라 `$MISSION_RUNTIME_STATE` →
# `$XDG_STATE_HOME/mission_runtime` → `~/.local/state/mission_runtime` 아래 `backend/`
# 다. 설치 트리에 쓰면 설치된 패키지를 고치는 것이 되고, `git pull` 이 충돌한다.
#
# ## 컨테이너가 먼저다
#
# 도커가 있으면 `deploy/backend/docker-compose.yml` 로 띄운다 — 같은 소스에서 같은
# 것이 서고(AI-B-02) `restart: unless-stopped` 라 기계를 다시 켜도 돈다. 도커가 없는
# 기계도 **정상이다**: 그때는 프로세스로 띄우고 그렇다고 말한다(AI-C-05).
# `AIF_MODE=bare` 로 강제할 수 있다.
#
# 모델 워크로드는 여기서 띄우지 않는다 — 그것은 k3s 의 몫이고(`providers/k3s.py`),
# 가시화가 `POST /api/stack` 으로 켜고 끈다.
#
# ## 바꾸는 것은 환경변수뿐이다
#
#   AIF_HOST     듣는 주소. 기본 0.0.0.0 (WSL 안에서 띄우고 윈도 브라우저로 볼 때 필요).
#                `overlay` 를 주면 이 기계의 Tailscale 주소에만 묶는다.
#   AIF_PORT     게이트웨이 포트(기본 8899) · AIF_UI_PORT 상태 패널(기본 8765)
#   AIF_CONFIG · AIF_DOMAINS · AIF_UNITS · AIF_ACCOUNTS   선언 파일 자리
#   AIF_MODE          auto(기본) · docker · bare
#   AIF_HOST_CONTROL  1 이면 컨테이너가 호스트 docker·k3s 를 몬다(권한을 주는 일이다)
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE" || exit 1

PY="${AIF_PY:-}"
if [ -z "$PY" ]; then
  for candidate in "$HERE/.venv/bin/python" "$HERE/../.venv/bin/python" "$(command -v python3 || true)"; do
    [ -x "$candidate" ] && { PY="$candidate"; break; }
  done
fi

HOST="${AIF_HOST:-0.0.0.0}"
PORT="${AIF_PORT:-8899}"
UI_PORT="${AIF_UI_PORT:-8765}"
CONFIG="${AIF_CONFIG:-config/status_ui.fms.example.json}"
DOMAINS="${AIF_DOMAINS:-profiles/domains.example.json}"
UNITS="${AIF_UNITS:-config/stack_units.example.json}"
ACCOUNTS="${AIF_ACCOUNTS:-}"

state_root() {
  if [ -n "${MISSION_RUNTIME_STATE:-}" ]; then echo "$MISSION_RUNTIME_STATE/backend"
  elif [ -n "${XDG_STATE_HOME:-}" ]; then echo "$XDG_STATE_HOME/mission_runtime/backend"
  else echo "$HOME/.local/state/mission_runtime/backend"; fi
}
STATE="$(state_root)"
mkdir -p "$STATE"

alive() { [ -f "$1" ] && kill -0 "$(cat "$1" 2>/dev/null)" 2>/dev/null; }

# 하나를 띄운다. **이미 돌고 있으면 다시 띄우지 않는다** — 둘이 서면 같은 포트에
# 둘이 답하거나 뒤의 것이 조용히 죽는다.
spawn() {
  local name="$1"; shift
  local pidfile="$STATE/$name.pid"
  local log="$STATE/$name.log"
  if alive "$pidfile"; then
    echo "  [~] $name 은 이미 돈다 (pid $(cat "$pidfile"))"
    return 0
  fi
  setsid nohup "$@" >>"$log" 2>&1 &
  echo $! > "$pidfile"
  echo "  [o] $name 세웠다 (pid $(cat "$pidfile")) · 로그 $log"
}

reap() {
  # `local a=$1 b=$a` 를 한 줄에 쓰지 않는다 — `set -u` 아래에서 두 번째 확장이
  # 아직 없는 변수를 읽는다(실측: `name: unbound variable`).
  local name="$1"
  local pidfile="$STATE/$name.pid"
  if ! alive "$pidfile"; then
    rm -f "$pidfile"
    echo "  [~] $name 은 이미 멈춰 있다"
    return 0
  fi
  local pid; pid="$(cat "$pidfile")"
  kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null
  for _ in $(seq 1 40); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
  kill -0 "$pid" 2>/dev/null && kill -9 -- "-$pid" 2>/dev/null
  rm -f "$pidfile"
  echo "  [o] $name 내렸다"
}

shown_host() {
  # 듣는 주소와 **붙는 주소**는 다르다. 와일드카드면 안내는 오버레이 주소로 한다.
  if [ "$HOST" = "0.0.0.0" ] || [ "$HOST" = "overlay" ]; then
    "$PY" - <<'PY' 2>/dev/null || echo "localhost"
from mission_runtime.providers.overlay import TailscaleOverlayProvider, advertised_host
shown, origin = advertised_host("0.0.0.0", TailscaleOverlayProvider())
print(shown if origin == "overlay" else "localhost")
PY
  else
    echo "$HOST"
  fi
}

probe() {  # URL → HTTP 코드. 못 붙으면 curl 이 스스로 000 을 찍는다
  curl -s -o /dev/null -m 3 -w "%{http_code}" "$1" 2>/dev/null
}

COMPOSE_FILE="deploy/backend/docker-compose.yml"

# 도커로 띄울까. **있는지만 본다** — 판정을 새로 만들지 않는다.
use_docker() {
  [ "${AIF_MODE:-auto}" = "bare" ] && return 1
  [ "${AIF_MODE:-auto}" = "docker" ] && return 0
  command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 \
    && [ -f "$COMPOSE_FILE" ]
}

HOST_CONTROL_FILE="deploy/backend/docker-compose.host-control.yml"

# `AIF_HOST_CONTROL=1` 이면 호스트의 docker·kubectl 을 컨테이너에 얹는다. 기본은
# **얹지 않는다** — 소켓을 얹는 것은 그 컨테이너에 호스트 root 를 주는 일이다.
compose() {
  if [ "${AIF_HOST_CONTROL:-0}" = "1" ] && [ -f "$HOST_CONTROL_FILE" ]; then
    PWD="$HERE" docker compose -f "$COMPOSE_FILE" -f "$HOST_CONTROL_FILE" "$@"
  else
    docker compose -f "$COMPOSE_FILE" "$@"
  fi
}

# 이미지가 지금 소스를 담고 있나. **시각으로 가른다** — 태그만 보면 옛 이미지가
# 오늘 코드인 척한다. 소스 쪽은 추적되는 파일의 가장 최근 수정 시각이다.
image_is_fresh() {
  local created newest
  created="$(docker image inspect -f '{{.Created}}' mission-runtime:cpu 2>/dev/null)" || return 1
  [ -n "$created" ] || return 1
  created="$(date -d "$created" +%s 2>/dev/null)" || return 1
  newest="$(git ls-files -z 2>/dev/null | xargs -0 stat -c %Y 2>/dev/null | sort -n | tail -1)"
  # git 이 없는 배포본이면 비교할 기준이 없다 — 그때는 있는 이미지를 믿는다.
  [ -n "$newest" ] || return 0
  [ "$created" -ge "$newest" ]
}

case "${1:-status}" in
  start)
    if use_docker; then
      echo "백엔드를 **컨테이너로** 세운다 (restart=unless-stopped)"
      # **이미지가 소스보다 오래됐으면 다시 굽는다.** 있다는 것만 보면 2 주 전
      # 이미지로 오늘 코드를 돌리게 되고, 그때 컨테이너는 "모르는 깃발" 로 재시작
      # 루프에 빠진다(실측 2026-11-22: `--stack-units` 를 모르는 이미지였다).
      # 받는 쪽에서는 더 조용히 틀린다 — 옛 계약을 내면서 멀쩡히 돈다.
      if ! image_is_fresh; then
        echo "  [~] 이미지가 없거나 소스보다 오래됐다 — 굽는다 (처음 한 번, 몇 분)"
        compose build || { echo "  [x] 굽지 못했다"; exit 2; }
      fi
      compose up -d || { echo "  [x] 세우지 못했다"; exit 2; }
      sleep 3
      exec "$0" status
    fi
    echo "  [~] 도커가 없다 — **프로세스로** 띄운다(그 조각만 다르다, AI-C-05)"
    [ -x "$PY" ] || { echo "[x] 파이썬을 찾지 못했다 — AIF_PY 로 준다"; exit 2; }
    echo "백엔드를 세운다 (host=$HOST)"
    gw=( "$PY" -u tools/vz_gateway/serve.py --host "$HOST" --port "$PORT"
         --domains "$DOMAINS" --config "$CONFIG" )
    [ -f "$UNITS" ] && gw+=( --stack-units "$UNITS" )
    [ -n "$ACCOUNTS" ] && gw+=( --accounts "$ACCOUNTS" )
    spawn gateway "${gw[@]}"
    # 상태 패널은 **선택이다.** 없으면 가시화의 「기능」 카드만 비고 나머지는 돈다.
    spawn status-ui "$PY" -u tools/status_ui/serve.py --config "$CONFIG" \
          --host "$HOST" --port "$UI_PORT" --control local
    sleep 2
    exec "$0" status
    ;;
  stop)
    echo "백엔드를 내린다"
    if use_docker && [ -n "$(compose ps -q 2>/dev/null)" ]; then
      compose down
      echo "  [o] 컨테이너 둘을 내렸다 (다시 켜도 뜨지 않는다)"
    fi
    reap gateway
    reap status-ui
    ;;
  restart)
    "$0" stop; exec "$0" start
    ;;
  status)
    H="$(shown_host)"
    echo "백엔드 상태 · 상태 뿌리 $STATE"
    if use_docker && [ -n "$(compose ps -q 2>/dev/null)" ]; then
      compose ps --format "  {{.Service}}\t{{.State}}\t{{.Status}}" 2>/dev/null \
        || compose ps
    else
      for name in gateway status-ui; do
        if alive "$STATE/$name.pid"; then
          printf "  %-10s 돈다 (pid %s · 프로세스)\n" "$name" "$(cat "$STATE/$name.pid")"
        else
          printf "  %-10s 멈춰 있다\n" "$name"
        fi
      done
    fi
    # **듣는 주소 하나에 붙는 주소가 둘일 수 있다.** 0.0.0.0 으로 열면 같은 기계
    # (WSL 안에서 띄우고 윈도 브라우저로 볼 때 포함)는 localhost 로 닿고, 다른
    # 노트북은 오버레이 주소로 닿는다. 하나만 적으면 반드시 한쪽이 못 붙는다 —
    # 실제로 오버레이 주소만 적어 윈도 브라우저가 못 열었다(2026-11-22).
    echo "  주소 — 가시화의 연결 관리나 환경변수에 넣는다"
    if [ "$HOST" = "0.0.0.0" ]; then
      echo "    같은 기계(윈도 브라우저 포함) : http://localhost:$PORT · ws://localhost:$PORT · capability http://localhost:$UI_PORT"
      [ "$H" != "localhost" ] && \
      echo "    다른 노트북(오버레이)         : http://$H:$PORT · ws://$H:$PORT · capability http://$H:$UI_PORT"
    else
      echo "    http://$H:$PORT · ws://$H:$PORT · capability http://$H:$UI_PORT"
    fi
    echo "  지금 응답 — /registry $(probe "http://127.0.0.1:$PORT/registry") ·" \
         "/api/scene $(probe "http://127.0.0.1:$PORT/api/scene") ·" \
         "capability $(probe "http://127.0.0.1:$UI_PORT/api/functions")"
    ;;
  *)
    sed -n '3,12p' "$0"
    exit 2
    ;;
esac
