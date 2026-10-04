#!/usr/bin/env bash
# 드론 파트(SAR) Pi 설치 — 한 번에.
#
#   sudo ./install.sh                 # RTK 전달 · 상태판 텔레메트리 · .ulg 회수 · 데이터 서버
#   sudo ./install.sh --with-agent    # + 드론 에이전트에 sar_start/sar_abort (HW 담당과 협의 후)
#   sudo ./install.sh --with-gpstime  # + Pi 시계를 FC 의 GPS 시각에 맞춤(PPS 선 없이, 1 ms 안팎) — 레이더가 Pi 시계로 찍을 때
#   sudo ./install.sh --with-pps      # + GPS PPS 시각 동기(µs, PPS 선 필요 · 부팅 설정 · 재부팅) — pps/README.md
#   sudo ./install.sh --status        # 지금 상태만
#   sudo ./install.sh --uninstall     # 우리가 넣은 것만 걷어 낸다 (HW 의 drone-node 는 원래대로)
#   ./install.sh --dry-run ...        # 실제로 바꾸지 않고 할 일만 보여 준다
#
# 바꾸는 것: /etc/sar-drone.env(처음 한 번) · /etc/systemd/system/sar-*.service ·
#            --with-agent 면 /etc/systemd/system/drone-node.service.d/50-sar.conf
# 바꾸지 않는 것: HW 의 drone-node.service · ~/hw 코드 · mavlink-router 설정
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRONE_DIR="$(cd "$HERE/../.." && pwd)"          # viz-debugger/drone
ENV_FILE="${SAR_ENV_FILE:-/etc/sar-drone.env}"
UNIT_DIR=/etc/systemd/system
UNITS=(sar-rtk.service sar-ulog.service sar-data.service)
OPT_UNITS=(sar-chrony.service)
AGENT_DROPIN="$UNIT_DIR/drone-node.service.d/50-sar.conf"
SVC_USER="${SAR_USER:-physical}"

DRY=0; MODE=install; AGENT=0; PPS=0; GPSTIME=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --with-agent) AGENT=1 ;;
    --with-pps) PPS=1 ;;
    --with-gpstime) GPSTIME=1 ;;
    --status) MODE=status ;;
    --uninstall) MODE=uninstall ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "모르는 옵션: $a" >&2; exit 2 ;;
  esac
done

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
run()  { if [ "$DRY" = 1 ]; then printf '  [dry-run] %s\n' "$*"; else "$@"; fi; }

need_root() {
  if [ "$DRY" = 0 ] && [ "$(id -u)" != 0 ]; then echo "sudo 로 실행한다: sudo $0 $*" >&2; exit 1; fi
}

env_get() {  # 설치된 env 파일(없으면 예시)에서 값 하나
  local f="$ENV_FILE"; [ -f "$f" ] || f="$HERE/sar-drone.env.example"
  sed -n "s/^$1=//p" "$f" | tail -1
}

status() {
  step "서비스"
  for u in "${UNITS[@]}"; do
    if systemctl list-unit-files "$u" >/dev/null 2>&1 && systemctl cat "$u" >/dev/null 2>&1; then
      if systemctl is-active --quiet "$u"; then ok "$u 동작 중"; else bad "$u 멈춤 — journalctl -u ${u%.service} -n 50"; fi
    else warn "$u 설치 안 됨"; fi
  done
  if [ -f "$AGENT_DROPIN" ]; then
    if journalctl -u drone-node -n 200 --no-pager 2>/dev/null | grep -q "SAR 명령 준비"; then ok "drone-node: SAR 명령 준비됨"
    else warn "drone-node 덮어쓰기는 있는데 「SAR 명령 준비」 로그가 안 보인다 — journalctl -u drone-node -n 80"; fi
  else warn "드론 에이전트 연동 안 함 (--with-agent)"; fi
  step "끝점"
  local port; port="$(env_get SAR_DATA_PORT)"
  if command -v curl >/dev/null && curl -s -m 2 "http://127.0.0.1:${port:-8766}/api/health" >/dev/null; then ok "데이터 서버 :${port:-8766}"
  else warn "데이터 서버 :${port:-8766} 응답 없음"; fi
  if systemctl is-active --quiet mavlink-router 2>/dev/null; then ok "mavlink-router 동작 중"; else warn "mavlink-router 가 안 보인다 — FC 연결 확인"; fi
  local ld; ld="$(env_get SAR_LOG_DIR)"
  [ -d "$ld" ] && ok "비행 기록 폴더 $ld ($(find "$ld" -maxdepth 1 -name 'flight_*' 2>/dev/null | wc -l)개 비행)" || warn "비행 기록 폴더 $ld 없음"
}

uninstall() {
  need_root
  step "우리가 넣은 것만 걷어 낸다"
  for u in "${UNITS[@]}" "${OPT_UNITS[@]}"; do
    run systemctl disable --now "$u" 2>/dev/null || true
    run rm -f "$UNIT_DIR/$u"
  done
  if [ -f /etc/chrony/conf.d/sar-pps.conf ]; then
    run rm -f /etc/chrony/conf.d/sar-pps.conf; run systemctl restart chrony || true
    warn "PPS 부팅 설정(dtoverlay)은 남겨 둔다 — 원본은 config.txt.sar-backup"
  fi
  if [ -f "$AGENT_DROPIN" ]; then
    run rm -f "$AGENT_DROPIN"
    run systemctl daemon-reload
    run systemctl restart drone-node || true
    ok "drone-node 를 원래 실행 명령으로 되돌렸다"
  fi
  run systemctl daemon-reload
  warn "$ENV_FILE 과 비행 기록은 남겨 둔다 (지우려면 직접)"
}

install() {
  need_root
  step "1. 확인"
  id "$SVC_USER" >/dev/null 2>&1 || { bad "사용자 $SVC_USER 가 없다"; exit 1; }
  ok "사용자 $SVC_USER"
  [ -f "$DRONE_DIR/pyproject.toml" ] || { bad "$DRONE_DIR 에 pyproject.toml 이 없다"; exit 1; }
  ok "코드 $DRONE_DIR"
  local venv; venv="$(env_get SAR_VENV)"
  if [ ! -x "$venv/bin/python3" ]; then
    bad "venv $venv 가 없다 — drone-node 가 쓰는 venv 경로를 $ENV_FILE 의 SAR_VENV 에 맞춘다"; exit 1
  fi
  ok "venv $venv ($("$venv/bin/python3" -V 2>&1))"
  systemctl is-active --quiet mavlink-router 2>/dev/null && ok "mavlink-router 동작 중" || warn "mavlink-router 가 안 보인다 — FC 와 연결을 먼저 확인"

  step "2. 파이썬 패키지 (편집 가능 설치 — git pull 만 하면 바로 반영)"
  run sudo -u "$SVC_USER" "$venv/bin/pip" install -q -e "$DRONE_DIR"
  if [ "$DRY" = 0 ]; then
    "$venv/bin/python3" -c "import sar_pass, rtk_relay, fc_watch, sar_data, mavsdk_grpc" || { bad "import 실패 — 위 pip 출력을 본다"; exit 1; }
    ok "import 확인"
  fi

  step "3. 설정 · 폴더"
  if [ -f "$ENV_FILE" ]; then ok "$ENV_FILE 있음 — 그대로 둔다"
  else run install -m 0644 "$HERE/sar-drone.env.example" "$ENV_FILE"; ok "$ENV_FILE 만듦 — MQTT 주소 등 현장값을 확인한다"; fi
  local ld; ld="$(env_get SAR_LOG_DIR)"
  run install -d -o "$SVC_USER" -g "$SVC_USER" "$ld"
  ok "비행 기록 폴더 $ld"
  local rj; rj="$(env_get SAR_RADAR_JSON)"
  if [ -n "$rj" ] && [ ! -f "$rj" ]; then
    run install -m 0644 -o "$SVC_USER" -g "$SVC_USER" "$DRONE_DIR/sar_image/example_radar_cansar.json" "$rj"
    warn "$rj 을 CANSAR-2 예시로 만들었다 — 레버암 · 빔 · side 를 실측값으로 고친다"
  fi
  if [ -z "$(env_get SAR_CANSAR_QUICK)" ]; then
    warn "레이더 팀 quick-look 꺼짐 — 쓰려면 $ENV_FILE 의 SAR_CANSAR_QUICK 에 cansar_quick.py 경로를 넣는다"
  fi

  step "4. 서비스"
  for u in "${UNITS[@]}"; do run install -m 0644 "$HERE/$u" "$UNIT_DIR/$u"; done
  run systemctl daemon-reload
  for u in "${UNITS[@]}"; do run systemctl enable --now "$u"; done
  ok "${UNITS[*]}"

  if [ "$GPSTIME" = 1 ] && [ "$PPS" = 0 ]; then
    step "Pi 시계 ← FC GPS 시각 (chrony, PPS 없이)"
    command -v chronyc >/dev/null || run apt-get install -y chrony
    run install -d /etc/chrony/conf.d
    run install -m 0644 "$HERE/pps/chrony-sar-fc.conf" /etc/chrony/conf.d/sar-pps.conf
    if ! grep -qs '^confdir /etc/chrony/conf.d' /etc/chrony/chrony.conf; then
      run sh -c 'echo "confdir /etc/chrony/conf.d" >> /etc/chrony/chrony.conf'
    fi
    run install -m 0644 "$HERE/sar-chrony.service" "$UNIT_DIR/sar-chrony.service"
    run systemctl daemon-reload
    run systemctl enable --now sar-chrony.service
    run systemctl restart chrony
    ok "chrony · sar-chrony — 몇 분 뒤 chronyc sources -v 에 FC 줄 앞 '*' 이면 GPS 시각으로 맞추는 중"
  fi

  if [ "$PPS" = 1 ]; then
    step "PPS 시각 동기 (chrony)"
    command -v chronyc >/dev/null || run apt-get install -y chrony pps-tools
    run install -d /etc/chrony/conf.d
    run install -m 0644 "$HERE/pps/chrony-sar.conf" /etc/chrony/conf.d/sar-pps.conf
    if ! grep -qs '^confdir /etc/chrony/conf.d' /etc/chrony/chrony.conf; then
      warn "/etc/chrony/chrony.conf 에 'confdir /etc/chrony/conf.d' 가 없다 — 그 줄을 넣는다"
      run sh -c 'echo "confdir /etc/chrony/conf.d" >> /etc/chrony/chrony.conf'
    fi
    local boot=/boot/firmware/config.txt; [ -f "$boot" ] || boot=/boot/config.txt
    if grep -qs '^dtoverlay=pps-gpio' "$boot"; then ok "$boot 에 pps-gpio 있음"
    else
      run cp "$boot" "$boot.sar-backup"
      run sh -c "echo 'dtoverlay=pps-gpio,gpiopin=18' >> '$boot'"
      warn "$boot 에 dtoverlay=pps-gpio,gpiopin=18 을 넣었다 (원본 $boot.sar-backup) — 재부팅해야 /dev/pps0 이 생긴다"
    fi
    run install -m 0644 "$HERE/sar-chrony.service" "$UNIT_DIR/sar-chrony.service"
    run systemctl daemon-reload
    run systemctl enable --now sar-chrony.service
    run systemctl restart chrony
    ok "chrony · sar-chrony — 재부팅 뒤 chronyc sources -v 로 PPS 확인"
  fi

  if [ "$AGENT" = 1 ]; then
    step "5. 드론 에이전트 연동 (drone-node 실행 명령만 바꾼다)"
    systemctl cat drone-node >/dev/null 2>&1 || { bad "drone-node.service 가 없다"; exit 1; }
    local wd; wd="$(systemctl show -p WorkingDirectory --value drone-node)"
    if [ "$DRY" = 0 ] && ! (cd "$wd" && sudo -u "$SVC_USER" "$venv/bin/python3" -c "import drone.drone_node, common.node, sar_pass.agent"); then
      bad "$wd 에서 drone.drone_node · common.node · sar_pass.agent 를 못 불러온다 — 바꾸지 않는다"; exit 1
    fi
    ok "import 확인 ($wd)"
    run install -d "$UNIT_DIR/drone-node.service.d"
    run install -m 0644 "$HERE/drone-node-sar.conf" "$AGENT_DROPIN"
    run systemctl daemon-reload
    run systemctl restart drone-node
    if [ "$DRY" = 0 ]; then
      local i
      for i in $(seq 1 20); do
        journalctl -u drone-node --since "-30s" --no-pager 2>/dev/null | grep -q "SAR 명령 준비" && break
        sleep 1
      done
      if journalctl -u drone-node --since "-40s" --no-pager 2>/dev/null | grep -q "SAR 명령 준비"; then ok "「SAR 명령 준비」 — 화면의 「패스 시작」이 열린다"
      else
        bad "20 초 안에 「SAR 명령 준비」가 안 보인다 — 원래대로 되돌린다"
        rm -f "$AGENT_DROPIN"; systemctl daemon-reload; systemctl restart drone-node
        journalctl -u drone-node -n 40 --no-pager || true
        exit 1
      fi
    fi
  fi
  status
  step "되돌리기: sudo $0 --uninstall"
}

case "$MODE" in
  status) status ;;
  uninstall) uninstall ;;
  install) install ;;
esac
