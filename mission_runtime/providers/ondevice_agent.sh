#!/usr/bin/env bash
# pf_agent — on-device unit supervisor for OnDeviceSshControlProvider.
#
# implements: AI-B-03, AI-B-05, AI-B-10, AI-B-02
#
# 절대 준수 원칙 #11 / AI-B-10: 말단은 오케스트레이터 제어면을 필수 설치 대상으로
# 요구하지 않는다. 이 스크립트가 말단에 놓이는 "전부"이며, 브로커도 수집기도
# 제어면도 아니다 — POSIX 셸 + coreutils 만 쓰는 단일 파일이다.
#
# Every subcommand prints one line to stdout: `ok:...` or `error:<reason>`,
# and exits non-zero on error, so the controlling side never has to parse
# free-form output to decide what happened.
#
# Layout per unit (all under $PF_ROOT, default ~/pf_units):
#   <unit>/versions/<version>/   staged artifact contents
#   <unit>/versions/<version>.sha256
#   <unit>/current   -> versions/<version>   (relative symlink)
#   <unit>/previous  -> versions/<version>   last-known-good (AI-B-05)
#   <unit>/incoming/                         in-flight uploads only
#   <unit>/run/{pid,ready,unit.log}

set -u

ROOT="${PF_ROOT:-$HOME/pf_units}"
ME="$(id -un)"

die() { printf 'error:%s\n' "$1"; exit "${2:-1}"; }
ok() { printf 'ok:%s\n' "$1"; }

unit_dir() { printf '%s/%s' "$ROOT" "$1"; }

# --- backend resolution -------------------------------------------------
# systemd --user is preferred, but ONLY when lingering is enabled: without
# lingering the user manager is torn down at logout and would take every
# deployed unit with it. A supervisor that dies when the deploying SSH
# session closes is not a supervisor, so in that case we fall back to a
# setsid/pidfile supervisor rather than pretend (AI-B-05).
resolve_backend() {
  if [ -n "${PF_BACKEND:-}" ] && [ "$PF_BACKEND" != "auto" ]; then
    printf '%s' "$PF_BACKEND"
    return
  fi
  if [ -f "$ROOT/.backend" ]; then
    cat "$ROOT/.backend"
    return
  fi
  backend=script
  if command -v systemctl >/dev/null 2>&1 && systemctl --user is-system-running >/dev/null 2>&1; then
    linger="$(loginctl show-user "$ME" -p Linger --value 2>/dev/null || printf 'no')"
    if [ "$linger" != "yes" ]; then
      # Best effort, never with sudo. Permitted for self on a stock Debian
      # polkit config; if it is refused we simply stay on the script backend.
      loginctl enable-linger >/dev/null 2>&1 || true
      linger="$(loginctl show-user "$ME" -p Linger --value 2>/dev/null || printf 'no')"
    fi
    [ "$linger" = "yes" ] && backend=systemd
  fi
  mkdir -p "$ROOT"
  printf '%s' "$backend" > "$ROOT/.backend"
  printf '%s' "$backend"
}

active_version() {
  d="$(unit_dir "$1")"
  [ -L "$d/current" ] || return 1
  target="$(readlink "$d/current")"
  printf '%s' "${target#versions/}"
}

previous_version() {
  d="$(unit_dir "$1")"
  [ -L "$d/previous" ] || return 1
  target="$(readlink "$d/previous")"
  printf '%s' "${target#versions/}"
}

# --- systemd --user backend ---------------------------------------------
systemd_unit_name() { printf 'pf-%s.service' "$1"; }
systemd_unit_path() { printf '%s/.config/systemd/user/pf-%s.service' "$HOME" "$1"; }

systemd_write_unit() {
  u="$1"; d="$(unit_dir "$u")"; p="$(systemd_unit_path "$u")"
  mkdir -p "$(dirname "$p")"
  cat > "$p" <<UNIT
[Unit]
Description=mission_runtime on-device unit ${u}

[Service]
Type=simple
WorkingDirectory=${d}/current
Environment=PF_UNIT_ID=${u}
Environment=PF_UNIT_DIR=${d}
Environment=PF_READY_FILE=${d}/run/ready
ExecStart=/bin/bash ${d}/current/run.sh
Restart=on-failure
RestartSec=3
StandardOutput=append:${d}/run/unit.log
StandardError=append:${d}/run/unit.log

[Install]
WantedBy=default.target
UNIT
  systemctl --user daemon-reload >/dev/null 2>&1 || true
}

# --- script backend ------------------------------------------------------
script_pid() {
  d="$(unit_dir "$1")"
  [ -f "$d/run/pid" ] || return 1
  pid="$(cat "$d/run/pid" 2>/dev/null)"
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  printf '%s' "$pid"
}

script_start() {
  u="$1"; d="$(unit_dir "$u")"
  if script_pid "$u" >/dev/null; then ok "already_running"; return 0; fi
  rm -f "$d/run/ready"
  # setsid gives the unit its own process group, so stop can signal the whole
  # tree instead of orphaning children.
  ( cd "$d/current" 2>/dev/null || exit 9
    PF_UNIT_ID="$u" PF_UNIT_DIR="$d" PF_READY_FILE="$d/run/ready" \
      setsid nohup /bin/bash "$d/current/run.sh" >> "$d/run/unit.log" 2>&1 &
    printf '%s' "$!" > "$d/run/pid"
  ) || die start_failed 10
  ok "started"
}

script_stop() {
  u="$1"; d="$(unit_dir "$u")"
  pid="$(script_pid "$u" || true)"
  rm -f "$d/run/ready"
  if [ -z "$pid" ]; then rm -f "$d/run/pid"; ok "already_stopped"; return 0; fi
  kill -TERM -"$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  i=0
  while [ "$i" -lt 50 ]; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.1
    i=$((i + 1))
  done
  kill -0 "$pid" 2>/dev/null && { kill -KILL -"$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true; }
  rm -f "$d/run/pid"
  ok "stopped"
}

# --- subcommands ---------------------------------------------------------
cmd_ensure() {
  u="$1"; d="$(unit_dir "$u")"
  mkdir -p "$d/versions" "$d/incoming" "$d/run" || die mkdir_failed 2
  ok "ensured:$(resolve_backend)"
}

cmd_stage() {
  u="$1"; v="$2"; sum="$3"; d="$(unit_dir "$u")"
  pkg="$d/incoming/$v.tar.gz"
  [ -f "$pkg" ] || die package_missing 3
  actual="$(sha256sum "$pkg" | awk '{print $1}')"
  if [ "$actual" != "$sum" ]; then
    # A partial upload (link dropped mid-transfer) lands here. Delete it so a
    # retry cannot resume into a half-file, and leave `current` untouched.
    rm -f "$pkg"
    die "checksum_mismatch" 4
  fi
  tmp="$d/versions/.stage.$$"
  rm -rf "$tmp"; mkdir -p "$tmp"
  if ! tar -xzf "$pkg" -C "$tmp" 2>/dev/null; then
    rm -rf "$tmp"; rm -f "$pkg"; die extract_failed 5
  fi
  rm -rf "$d/versions/$v"
  mv -T "$tmp" "$d/versions/$v" || { rm -rf "$tmp"; die install_failed 5; }
  printf '%s' "$sum" > "$d/versions/$v.sha256"
  rm -f "$pkg"
  ok "staged:$v"
}

cmd_verify() {
  u="$1"; v="$2"; sum="$3"; d="$(unit_dir "$u")"
  [ -d "$d/versions/$v" ] || die version_not_staged 6
  recorded="$(cat "$d/versions/$v.sha256" 2>/dev/null || printf '')"
  [ "$recorded" = "$sum" ] || die checksum_mismatch 4
  ok "verified:$v"
}

cmd_activate() {
  u="$1"; v="$2"; d="$(unit_dir "$u")"
  [ -d "$d/versions/$v" ] || die version_not_staged 6
  if [ -L "$d/current" ]; then
    cur="$(readlink "$d/current")"
    [ "$cur" != "versions/$v" ] && ln -sfn "$cur" "$d/previous"
  fi
  ln -sfn "versions/$v" "$d/current" || die activate_failed 6
  ok "active:$v"
}

cmd_rollback() {
  u="$1"; d="$(unit_dir "$u")"
  [ -L "$d/previous" ] || die no_previous_version 7
  prev="$(readlink "$d/previous")"
  [ -d "$d/$prev" ] || die previous_version_missing 7
  cur=""
  [ -L "$d/current" ] && cur="$(readlink "$d/current")"
  ln -sfn "$prev" "$d/current" || die rollback_failed 7
  [ -n "$cur" ] && ln -sfn "$cur" "$d/previous"
  ok "active:${prev#versions/}"
}

cmd_start() {
  u="$1"; d="$(unit_dir "$u")"
  [ -L "$d/current" ] || die no_active_version 8
  [ -f "$d/current/run.sh" ] || die entrypoint_missing 8
  case "$(resolve_backend)" in
    systemd)
      rm -f "$d/run/ready"
      systemd_write_unit "$u"
      systemctl --user enable "$(systemd_unit_name "$u")" >/dev/null 2>&1 || true
      systemctl --user restart "$(systemd_unit_name "$u")" >/dev/null 2>&1 || die start_failed 10
      ok "started"
      ;;
    *) script_start "$u" ;;
  esac
}

cmd_stop() {
  u="$1"
  case "$(resolve_backend)" in
    systemd)
      systemctl --user stop "$(systemd_unit_name "$u")" >/dev/null 2>&1 || true
      rm -f "$(unit_dir "$u")/run/ready"
      ok "stopped"
      ;;
    *) script_stop "$u" ;;
  esac
}

cmd_restart() { cmd_stop "$1" >/dev/null; cmd_start "$1"; }

liveness_of() {
  u="$1"
  case "$(resolve_backend)" in
    systemd)
      state="$(systemctl --user is-active "$(systemd_unit_name "$u")" 2>/dev/null || true)"
      case "$state" in
        active) printf 'ALIVE' ;;
        activating|reloading) printf 'STARTING' ;;
        inactive|failed|"") printf 'DEAD' ;;
        *) printf 'UNKNOWN' ;;
      esac
      ;;
    *)
      if script_pid "$u" >/dev/null; then printf 'ALIVE'; else printf 'DEAD'; fi
      ;;
  esac
}

cmd_status() {
  u="$1"
  [ -d "$(unit_dir "$u")" ] || die unknown_target 11
  case "$(liveness_of "$u")" in
    ALIVE) ok "RUNNING" ;;
    *) ok "STOPPED" ;;
  esac
}

# Device operational state is collected separately from process state and is
# never allowed to stand in for it (AI-B-05: "프로세스의 시작·liveness·readiness와
# 실제 장치의 운용 상태·안전 상태를 구분해야 하며 하나를 다른 상태의 근거로
# 대체해서는 안 된다").
device_json() {
  temp=""; throttled=""
  if command -v vcgencmd >/dev/null 2>&1; then
    temp="$(vcgencmd measure_temp 2>/dev/null | tr -dc '0-9.')"
    throttled="$(vcgencmd get_throttled 2>/dev/null | cut -d= -f2)"
  fi
  if [ -z "$temp" ] && [ -r /sys/class/thermal/thermal_zone0/temp ]; then
    raw="$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || printf '')"
    [ -n "$raw" ] && temp="$(awk -v r="$raw" 'BEGIN{printf "%.1f", r/1000}')"
  fi
  load1="$(awk '{print $1}' /proc/loadavg 2>/dev/null || printf '')"
  uptime_s="$(awk '{printf "%d", $1}' /proc/uptime 2>/dev/null || printf '')"
  avail_kb="$(awk '/MemAvailable/{print $2}' /proc/meminfo 2>/dev/null || printf '')"
  printf '{"temperature_c":%s,"throttled":"%s","load1":%s,"uptime_s":%s,"mem_available_kb":%s}' \
    "${temp:-null}" "${throttled:-}" "${load1:-null}" "${uptime_s:-null}" "${avail_kb:-null}"
}

cmd_health() {
  u="$1"; d="$(unit_dir "$u")"
  [ -d "$d" ] || die unknown_target 11
  live="$(liveness_of "$u")"
  ready="NOT_READY"; ready_age="null"
  if [ -f "$d/run/ready" ]; then
    ready="READY"
    mtime="$(stat -c %Y "$d/run/ready" 2>/dev/null || printf '')"
    [ -n "$mtime" ] && ready_age="$(( $(date +%s) - mtime ))"
  fi
  ver="$(active_version "$u" || printf '')"
  prev="$(previous_version "$u" || printf '')"
  printf '{"unit":"%s","backend":"%s","liveness":"%s","readiness":"%s","ready_age_s":%s,"version":"%s","previous_version":"%s","device":%s}\n' \
    "$u" "$(resolve_backend)" "$live" "$ready" "$ready_age" "$ver" "$prev" "$(device_json)"
}

cmd_versions() {
  u="$1"; d="$(unit_dir "$u")"
  [ -d "$d/versions" ] || die unknown_target 11
  printf 'ok:%s|%s|' "$(active_version "$u" || printf '')" "$(previous_version "$u" || printf '')"
  for path in "$d"/versions/*/; do
    [ -d "$path" ] || continue
    name="$(basename "$path")"
    case "$name" in .stage.*) continue ;; esac
    printf '%s,' "$name"
  done
  printf '\n'
}

cmd_remove() {
  u="$1"
  case "$(resolve_backend)" in
    systemd)
      systemctl --user stop "$(systemd_unit_name "$u")" >/dev/null 2>&1 || true
      systemctl --user disable "$(systemd_unit_name "$u")" >/dev/null 2>&1 || true
      rm -f "$(systemd_unit_path "$u")"
      systemctl --user daemon-reload >/dev/null 2>&1 || true
      ;;
    *) script_stop "$u" >/dev/null 2>&1 || true ;;
  esac
  rm -rf "$(unit_dir "$u")"
  ok "removed"
}

cmd_prune() {
  # Keep only the active and previous versions; everything else is dead weight
  # on a 말단 with a small card (AI-B-10).
  u="$1"; d="$(unit_dir "$u")"
  keep_a="$(active_version "$u" || printf '')"
  keep_b="$(previous_version "$u" || printf '')"
  for path in "$d"/versions/*/; do
    [ -d "$path" ] || continue
    name="$(basename "$path")"
    [ "$name" = "$keep_a" ] && continue
    [ "$name" = "$keep_b" ] && continue
    rm -rf "$path" "$d/versions/$name.sha256"
  done
  ok "pruned"
}

case "${1:-}" in
  ensure)    shift; cmd_ensure "$@" ;;
  stage)     shift; cmd_stage "$@" ;;
  verify)    shift; cmd_verify "$@" ;;
  activate)  shift; cmd_activate "$@" ;;
  rollback)  shift; cmd_rollback "$@" ;;
  start)     shift; cmd_start "$@" ;;
  stop)      shift; cmd_stop "$@" ;;
  restart)   shift; cmd_restart "$@" ;;
  status)    shift; cmd_status "$@" ;;
  health)    shift; cmd_health "$@" ;;
  versions)  shift; cmd_versions "$@" ;;
  remove)    shift; cmd_remove "$@" ;;
  prune)     shift; cmd_prune "$@" ;;
  backend)   printf 'ok:%s\n' "$(resolve_backend)" ;;
  *)         die "unsupported_command:${1:-}" 64 ;;
esac
