#!/usr/bin/env bash
# SAR 드론 — 처리 서버(GPU) 켜기. 노트북이 연 SSH 역터널로 노트북 데이터 서버를 보고, 끝난 패스를 가져와 영상을 만든다.
#
#   Pi ──(핫스팟)──▶ 노트북 sar_data(8766) ──(SSH 역터널, 서버 127.0.0.1:18766)──▶ 이 서버 sar_data(8768)
#                                         ◀──(SSH 터널, 노트북 127.0.0.1:8767)── 영상 · 결과
#
# 서버 포트는 바깥에 열지 않는다(127.0.0.1 에만) — 노트북은 SSH 로만 들어온다. 노트북 쪽은 deploy/laptop/sar-tunnel.*.
# 현장값은 환경변수. Ctrl-C 로 끈다. 늘 켜 두려면 setsid nohup … 또는 systemd --user.
set -euo pipefail
PORT="${PORT:-8768}"                       # 이 서버의 데이터 서버(노트북이 -L 로 본다)
LAPTOP_PORT="${LAPTOP_PORT:-18766}"        # 노트북이 -R 로 열어 준 자리
FLIGHTS="${FLIGHTS:-$HOME/sar_server}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRONE="$(cd "$HERE/../.." && pwd)"
RADAR_JSON="${RADAR_JSON:-$HERE/radar.json}"
ADAPTER="${ADAPTER:-sar_image.cansar:cansar_iq}"
WORKERS="${WORKERS:-16}"
PY="${PY:-$DRONE/.venv/bin/python}"

[ -x "$PY" ] || { echo "[준비] $DRONE 에서: python3 -m venv .venv && .venv/bin/pip install -e '.[base,image]'"; exit 1; }
[ -f "$RADAR_JSON" ] || { echo "[안내] radar.json 이 없어 예시 값으로 시작한다 — 노트북 것과 같게 $RADAR_JSON 에 둔다"; cp "$DRONE/sar_image/example_radar_cansar.json" "$RADAR_JSON"; }
extra=()
[ -n "${FORMER:-}" ] && extra+=(--former "$FORMER")
[ -n "${FOCUSER:-}" ] && extra+=(--focuser "$FOCUSER")
[ -n "${REFLECTORS:-}" ] && extra+=(--reflectors "$REFLECTORS")
mkdir -p "$FLIGHTS"
cd "$DRONE"
echo "처리 서버 — 노트북(127.0.0.1:$LAPTOP_PORT)에서 패스를 가져와 영상을 만든다. 결과: 127.0.0.1:$PORT"
exec "$PY" -m sar_data --flights "$FLIGHTS" --mirror "http://127.0.0.1:$LAPTOP_PORT" --bind 127.0.0.1 --port "$PORT" \
  --radar-json "$RADAR_JSON" --adapter "$ADAPTER" --auto-image --image-workers "$WORKERS" "${extra[@]}"
