#!/bin/sh
# 가상 실험 배치 한 번 실행:  ./run_batch.sh configs/<name>.json
# Unity 에디터가 이 프로젝트를 열고 있으면 실행하지 않는다 (먼저 닫을 것).
set -e

CFG="$1"
[ -n "$CFG" ] || { echo "usage: $0 configs/<name>.json" >&2; exit 2; }

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
UNITY="/d/editor/6000.3.5f2/Editor/Unity.exe"
EVAL="$ROOT/GO1_Proactive_Evaluation"
[ -f "$EVAL/$CFG" ] || { echo "config not found: $EVAL/$CFG" >&2; exit 2; }

if tasklist //FI "IMAGENAME eq Unity.exe" 2>/dev/null | grep -qi "Unity.exe"; then
  echo "Unity is running. Close it first." >&2
  exit 3
fi
rm -f "$ROOT/Temp/UnityLockfile"

NAME=$(basename "$CFG" .json)
mkdir -p "$EVAL/logs"
LOG="$EVAL/logs/$NAME.log"
rm -f "$LOG"
cp "$EVAL/$CFG" "$EVAL/batch_config.json"

echo "== launching $NAME (log: $LOG) =="
"$UNITY" -batchmode \
         -projectPath "$(cygpath -w "$ROOT")" \
         -executeMethod ProactiveBatchLauncher.Run \
         -logFile "$(cygpath -w "$LOG")" || echo "unity exit code: $?"

grep -E "\[ProactiveBatch\]|error CS" "$LOG" | tail -n 40 || true
