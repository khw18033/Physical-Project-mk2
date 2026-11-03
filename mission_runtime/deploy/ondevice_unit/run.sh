#!/usr/bin/env bash
# Entrypoint contract for an on-device unit (AI-B-02, AI-B-05).
#
# The supervisor (providers/ondevice_agent.sh) execs exactly this file and
# nothing else, with PF_UNIT_ID / PF_UNIT_DIR / PF_READY_FILE in the
# environment. Everything the unit needs beyond a Python interpreter must be
# either inside the artifact or declared in unit.config.json — 말단에 서버형
# 미들웨어를 요구하지 않는다 (AI-B-10).
set -u
cd "$(dirname "$0")"

# Interpreter resolution order is data, not a branch on any device identity:
# an optional prepared runtime, then a plain interpreter. A device without the
# venv still starts the unit; it simply reports the reduced capability
# (AI-C-05: 선택 조건이 없으면 가능한 축소 모드로 전환).
PY="python3"
for candidate in "${PF_PYTHON:-}" "$HOME/pf_runtime/venv/bin/python"; do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then PY="$candidate"; break; fi
done

exec "$PY" unit.py
