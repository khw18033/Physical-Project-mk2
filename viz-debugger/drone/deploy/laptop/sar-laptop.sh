#!/usr/bin/env bash
# SAR 드론 — 노트북(지상국) 한 번에 켜기 (Linux · macOS). Windows 는 sar-laptop.bat.
#   1) RTK 베이스 보정 → Pi   2) Pi 의 끝난 패스를 가져와 영상 자동 생성(미러)
# 현장값은 환경변수나 아래 기본값. Ctrl-C 로 둘 다 끈다.
set -euo pipefail
PI="${PI:-192.168.137.2}"
BASE_COM="${BASE_COM:-}"                  # 예: /dev/ttyUSB0 (비우면 RTK 건너뜀)
BASE_BAUD="${BASE_BAUD:-115200}"
RTCM_PORT="${RTCM_PORT:-14660}"
PORT="${PORT:-8765}"
MIRROR_DIR="${MIRROR_DIR:-$HOME/sar_mirror}"
TILE_DIR="${TILE_DIR:-$HOME/sar_tiles}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRONE="$(cd "$HERE/../.." && pwd)"
RADAR_JSON="${RADAR_JSON:-$HERE/radar.json}"
ADAPTER="${ADAPTER:-sar_image.sdr:iq_npy}"
VENV="$HERE/.venv"

if [ ! -x "$VENV/bin/python" ]; then
  echo "[준비] 파이썬 환경을 만든다 — 처음 한 번"
  python3 -m venv "$VENV"
  "$VENV/bin/python" -m pip install -q --upgrade pip
  "$VENV/bin/python" -m pip install -q -e "$DRONE[base,image]"
fi
[ -f "$RADAR_JSON" ] || { echo "[안내] radar.json 이 없어 예시 값으로 시작한다 — 화면에서 내려받아 $RADAR_JSON 에 둔다"; cp "$DRONE/sar_image/example_radar_sdr.json" "$RADAR_JSON"; }
extra=()
[ -n "${FORMER:-}" ] && extra+=(--former "$FORMER")
[ -n "${FOCUSER:-}" ] && extra+=(--focuser "$FOCUSER")
[ -f "$HERE/reflectors.csv" ] && extra+=(--reflectors "$HERE/reflectors.csv")

pids=()
trap 'kill "${pids[@]}" 2>/dev/null; exit 0' INT TERM
if [ -n "$BASE_COM" ]; then
  "$VENV/bin/python" -m rtk_relay.base_sender --port "$BASE_COM" --baud "$BASE_BAUD" --to "$PI:$RTCM_PORT" &
  pids+=($!)
fi
"$VENV/bin/python" -m sar_data --flights "$MIRROR_DIR" --mirror "http://$PI:8765" --bind 127.0.0.1 --port "$PORT" \
  --radar-json "$RADAR_JSON" --adapter "$ADAPTER" --auto-image --tile-cache "$TILE_DIR" "${extra[@]}" &
pids+=($!)
echo "켰다 — 화면의 「연결 관리 → 드론 데이터 서버」를 http://127.0.0.1:$PORT 로. Ctrl-C 로 끈다."
wait
