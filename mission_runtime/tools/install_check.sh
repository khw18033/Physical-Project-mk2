#!/usr/bin/env bash
# 배포 점검 — **받은 폴더 하나로** 백엔드가 서는지 끝까지 본다.
#
# implements: AI-B-02 (실행환경 패키징·재현성), AI-C-05 (선택 결손은 축소),
#             AI-C-16 (폐쇄망 배포 경계)
# tests: tests/test_install_check.py
#
# 왜 스크립트인가: 설치 절차를 문서에만 적으면 코드와 어긋난다. 받는 사람이 **한 줄**로
# 돌려서 "이 기계에서 무엇이 되고 무엇이 안 되는가" 를 직접 보게 한다.
#
# 이 스크립트는 **판정을 새로 만들지 않는다.** 환경 사실은 tools/preflight.py, 계약은
# pytest, 게이트웨이가 실제로 서는지는 그 프로세스 자신이 답한다. 여기서는 순서만 잡고
# 각 단계가 낸 답을 모아 한 장으로 낸다.
#
#   bash tools/install_check.sh                      # 설치 + 점검 + 시험 + 기동 확인
#   bash tools/install_check.sh --extras mqtt,redis  # 선택 extra 를 함께 설치
#   bash tools/install_check.sh --skip-tests         # 시험은 건너뛴다(빠른 확인)
#   bash tools/install_check.sh --offline            # 내부 wheelhouse 만 쓴다(폐쇄망)
#
# 종료 코드: **핵심이 서지 못했을 때만** 0 이 아니다. 선택 기능 결손은 축소이지
# 실패가 아니다(README 「세 상태」와 같은 규칙).

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE" || exit 2

EXTRAS=""
SKIP_TESTS=0
OFFLINE=0
WHEELHOUSE="${MISSION_RUNTIME_WHEELHOUSE:-$HERE/wheelhouse}"
VENV="${MISSION_RUNTIME_VENV:-$HERE/.venv}"

while [ $# -gt 0 ]; do
  case "$1" in
    --extras) EXTRAS="$2"; shift 2 ;;
    --extras=*) EXTRAS="${1#*=}"; shift ;;
    --skip-tests) SKIP_TESTS=1; shift ;;
    --offline) OFFLINE=1; shift ;;
    --venv) VENV="$2"; shift 2 ;;
    -h|--help) sed -n '1,30p' "$0"; exit 0 ;;
    *) echo "모르는 인자: $1 (--help)"; exit 2 ;;
  esac
done

FAIL=0
declare -a NOTES=()

say() { printf '\n== %s\n' "$1"; }
ok()   { printf '  [o] %s\n' "$1"; }
warn() { printf '  [~] %s\n' "$1"; NOTES+=("$1"); }
bad()  { printf '  [x] %s\n' "$1"; FAIL=1; }

# ---------------------------------------------------------------- 1. 파이썬
say "1/6  파이썬"
PY_BIN="${PYTHON:-python3}"
if ! command -v "$PY_BIN" >/dev/null 2>&1; then
  bad "python3 가 없다 — 3.10 이상을 설치한다"
  echo; echo "핵심이 서지 못했다."; exit 1
fi
PY_VER="$("$PY_BIN" -c 'import sys; print("%d.%d"%sys.version_info[:2])')"
if "$PY_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)'; then
  ok "python $PY_VER (요구: >= 3.10)"
else
  bad "python $PY_VER — 3.10 이상이 필요하다"
  echo; echo "핵심이 서지 못했다."; exit 1
fi

# ---------------------------------------------------------------- 2. 가상환경
say "2/6  가상환경"
if [ -x "$VENV/bin/python" ]; then
  ok "이미 있다: $VENV (다시 만들지 않는다)"
else
  if "$PY_BIN" -m venv "$VENV" >/dev/null 2>&1; then
    ok "만들었다: $VENV"
  else
    bad "venv 를 만들지 못했다 — 데비안 계열이면 apt install python3-venv"
    echo; echo "핵심이 서지 못했다."; exit 1
  fi
fi
VPY="$VENV/bin/python"

# ---------------------------------------------------------------- 3. 설치
say "3/6  설치"
SPEC=".[dev]"
[ -n "$EXTRAS" ] && SPEC=".[dev,$EXTRAS]"
PIP_ARGS=(-m pip install -q)
if [ "$OFFLINE" -eq 1 ]; then
  if [ -d "$WHEELHOUSE" ]; then
    PIP_ARGS+=(--no-index --find-links "$WHEELHOUSE")
    ok "폐쇄망 — 내부 wheelhouse 만 쓴다: $WHEELHOUSE"
  else
    bad "--offline 인데 wheelhouse 가 없다: $WHEELHOUSE (MISSION_RUNTIME_WHEELHOUSE 로 자리를 준다)"
    echo; echo "핵심이 서지 못했다."; exit 1
  fi
fi
# 파이프의 종료 코드는 tail 의 것이다 — pip 의 것을 봐야 한다.
INSTALL_OUT="$("$VPY" "${PIP_ARGS[@]}" -e "$SPEC" 2>&1)"; INSTALL_RC=$?
if [ "$INSTALL_RC" -eq 0 ]; then
  ok "pip install -e \"$SPEC\""
else
  echo "$INSTALL_OUT" | tail -5 | sed 's/^/      /'
  bad "설치 실패 — 위 출력을 본다"
  echo; echo "핵심이 서지 못했다."; exit 1
fi
"$VPY" - <<'PY' || FAIL=1
import importlib.util, sys
missing = [m for m in ("jsonschema", "numpy", "cv2", "google.protobuf") if not importlib.util.find_spec(m)]
print("  [x] 핵심 의존성이 빠졌다: %s" % ", ".join(missing)) if missing else print("  [o] 핵심 의존성 넷이 import 된다")
sys.exit(1 if missing else 0)
PY

# ---------------------------------------------------------------- 4. 자가 점검
say "4/6  이 기계에서 무엇이 되는가 (tools/preflight.py)"
PRE_OUT="$("$VPY" tools/preflight.py 2>&1)"; PRE_RC=$?
echo "$PRE_OUT" | tail -3 | sed 's/^/  /'
if [ "$PRE_RC" -eq 0 ]; then
  ok "막힘 없음 — 축소는 그 기능만 꺼진 정상 상태다"
else
  bad "막힌 항목이 있다 — 위 표의 [x] 줄이 할 일을 적는다"
fi

# ---------------------------------------------------------------- 5. 시험
say "5/6  계약 시험"
if [ "$SKIP_TESTS" -eq 1 ]; then
  warn "건너뛰었다 (--skip-tests)"
else
  TEST_OUT="$(PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 OTEL_SDK_DISABLED=true \
              "$VPY" -m pytest -q -p no:cacheprovider 2>&1 | tail -3)"
  echo "$TEST_OUT" | sed 's/^/  /'
  if echo "$TEST_OUT" | grep -qE "[0-9]+ (failed|error)"; then
    bad "실패가 있다 — skip 은 '이 기계에 그 도구·자산이 없다'는 뜻이고 실패와 다르다"
  else
    ok "실패 0 (skip 은 결손이지 실패가 아니다)"
  fi
fi

# ---------------------------------------------------------------- 6. 기동
say "6/6  게이트웨이가 실제로 서는가"
PORT="$("$VPY" - <<'PY'
import socket
s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()
PY
)"
LOG="$(mktemp)"
"$VPY" -u tools/vz_gateway/serve.py --port "$PORT" \
    --domains profiles/domains.example.json \
    --config config/status_ui.fms.example.json > "$LOG" 2>&1 &
GW_PID=$!
# **기다린다.** 닫힌 포트로의 curl 은 즉시 실패하므로 대기가 없으면 40번을 몇
# 밀리초에 다 돌고 "서지 않았다" 고 적는다 — 서버는 그 뒤에 뜬다(2026-11-19 실측).
CODE=000
for _ in $(seq 1 60); do
  CODE="$(curl -s --max-time 2 -o /dev/null -w '%{http_code}' \
          "http://127.0.0.1:$PORT/api/scene" 2>/dev/null)"
  [ "$CODE" = "200" ] && break
  kill -0 "$GW_PID" 2>/dev/null || break      # 죽었으면 더 기다리지 않는다
  sleep 0.5
done
if [ "${CODE:-000}" = "200" ]; then
  VER="$(curl -s -D- -o /dev/null "http://127.0.0.1:$PORT/api/scene" | tr -d '\r' | awk -F': ' '/^Server:/{print $2}')"
  ok "조회 계약이 선다 — GET /api/scene 200 · 계약 판 ${VER:-?}"
  grep -E "조회 계약|쓰기 계약" "$LOG" | sed 's/^/      /'
  for p in dashboard bootstrap deployment; do
    C="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/api/$p")"
    [ "$C" = "200" ] && ok "GET /api/$p 200" || bad "GET /api/$p -> $C"
  done
  C="$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/api/scene")"
  [ "$C" = "405" ] && ok "조회 경로의 POST 는 405 (관찰이 실행에 개입하지 않는다 · AI-O-06)" \
                   || bad "조회 경로의 POST 가 405 가 아니다 -> $C"
else
  bad "게이트웨이가 서지 않았다 — 아래가 그 사유다"
  grep -v RuntimeWarning "$LOG" | tail -8 | sed 's/^/      /'
fi
kill "$GW_PID" 2>/dev/null; wait "$GW_PID" 2>/dev/null
rm -f "$LOG"

# ---------------------------------------------------------------- 판정
echo
if [ "$FAIL" -eq 0 ]; then
  echo "핵심이 전부 섰다. 다음은 한 줄이다:"
  echo
  echo "    $VENV/bin/python tools/vz_gateway/serve.py --port 8899 \\"
  echo "        --domains profiles/domains.example.json \\"
  echo "        --config config/status_ui.fms.example.json"
  echo
  [ ${#NOTES[@]} -gt 0 ] && printf '남긴 것: %s\n' "${NOTES[*]}"
  exit 0
fi
echo "핵심이 서지 못했다. 위의 [x] 줄이 무엇을 하면 되는지 적는다."
exit 1
