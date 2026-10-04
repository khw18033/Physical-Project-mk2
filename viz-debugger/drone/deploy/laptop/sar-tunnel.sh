#!/usr/bin/env bash
# SAR 드론 — 노트북 ↔ 처리 서버 SSH 터널 (Linux · macOS). Windows 는 sar-tunnel.bat.
#   -R 서버 127.0.0.1:18766 → 노트북 데이터 서버(8766)   : 서버가 끝난 패스를 가져간다
#   -L 노트북 127.0.0.1:8767 → 서버 데이터 서버(8768)    : 화면이 서버에서 만든 영상을 본다
# 휴대폰 핫스팟(LTE)이 끊겨도 5 초마다 다시 붙는다. 먼저 sar-laptop.sh 를 켠다. 서버 쪽은 deploy/server/sar-server.sh.
set -uo pipefail
SERVER="${SERVER:?SERVER=사용자@서버주소 를 넣는다 (예: SERVER=me@203.0.113.5)}"
LOCAL_DATA="${LOCAL_DATA:-8766}"
REMOTE_IN="${REMOTE_IN:-18766}"
REMOTE_DATA="${REMOTE_DATA:-8768}"
LOCAL_VIEW="${LOCAL_VIEW:-8767}"
echo "터널 — 화면 「연결 관리 → 드론 데이터 서버」를 http://127.0.0.1:$LOCAL_VIEW 로 두면 서버 영상을 본다 (Ctrl-C 로 끈다)"
while true; do
  ssh -N -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes \
      -R "$REMOTE_IN:127.0.0.1:$LOCAL_DATA" -L "$LOCAL_VIEW:127.0.0.1:$REMOTE_DATA" "$SERVER"
  echo "[터널] 끊김 — 5 초 뒤 다시"
  sleep 5
done
