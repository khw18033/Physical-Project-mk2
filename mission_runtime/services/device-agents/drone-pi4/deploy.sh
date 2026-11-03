#!/usr/bin/env bash
# drone_pi4/ 환경을 pi4에 그대로 배포한다. 재실행 안전(멱등).
#
# 이 디렉터리에는 **말단이 하는 일만** 들어 있다 — RPN, 엣지 통신, 지연 판정의
# 시점 반영, 링크 단절 스풀. 의미 해석(OVD/CLIP/LLM/VLM)은 ../edge/ 에 있고
# 말단에는 그 코드도 의존성도 올라가지 않는다(AI-B-10 말단 경량 실행 경계).
#
# implements: AI-B-02 (재현 가능한 실행 단위), AI-N-02 (버전 구성 적용)
#
#   ./deploy.sh                 # 기본 대상으로 배포
#   ./deploy.sh --host pi9 --user physical --key ~/.ssh/other
#   ./deploy.sh --no-venv       # 코드만 갱신(의존성 설치 건너뜀)
set -euo pipefail

# 기본값을 두지 않는다 — 공개 저장소에 현장 주소를 박으면 그것이 곧 신원 유출이다.
HOST="${DRONE_PI4_HOST:?DRONE_PI4_HOST 를 지정해야 한다 (보안 오버레이 안의 말단 주소)}"
USER="${DRONE_PI4_USER:-physical}"
KEY="${DRONE_PI4_KEY:-$HOME/.ssh/id_ed25519_pi}"
REMOTE_DIR="drone_pi4"
DO_VENV=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2;;
    --user) USER="$2"; shift 2;;
    --key)  KEY="$2"; shift 2;;
    --dir)  REMOTE_DIR="$2"; shift 2;;
    --no-venv) DO_VENV=0; shift;;
    *) echo "모르는 인자: $1" >&2; exit 2;;
  esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSH=(ssh -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=10)
TARGET="$USER@$HOST"

echo "== 대상: $TARGET:~/$REMOTE_DIR"
"${SSH[@]}" "$TARGET" "mkdir -p ~/$REMOTE_DIR"

# 코드·설정·모델·샘플 이미지를 보낸다. 산출물(out/, edge_out/, *.jsonl)은 뺀다 —
# 말단에서 생긴 결과를 개발 기기 것으로 덮어쓰면 안 된다.
rsync -az --delete-after \
  --exclude 'out/' --exclude 'edge_out/' --exclude '__pycache__/' \
  --exclude '*.jsonl' --exclude 'venv/' --exclude '*.json.bak' \
  --exclude '*.onnx' --exclude 'spool/' --exclude 'pi4_records*.json' \
  -e "ssh -i $KEY -o IdentitiesOnly=yes -o BatchMode=yes" \
  "$HERE/" "$TARGET:$REMOTE_DIR/"

# RPN 모델은 저장소 정본에서 따로 보낸다. rsync 대상에 두면 --delete-after가
# 말단의 모델을 지우고(실제로 한 번 겪었다), drone_pi4/에 20MB 바이너리를
# 복제하게 된다. 경로는 config.json의 rpn.source_path 한 곳에서만 온다.
SRC_MODEL="$(python3 -c "
import json,os,sys
c=json.load(open('$HERE/config.json'))
print(os.path.normpath(os.path.join('$HERE', c['rpn']['source_path'])))")"
DST_MODEL="$(python3 -c "
import json; print(json.load(open('$HERE/config.json'))['rpn']['model'])")"
echo "== 모델 전송: $(basename "$SRC_MODEL") -> $REMOTE_DIR/$DST_MODEL"
if "${SSH[@]}" "$TARGET" "test -f ~/$REMOTE_DIR/$DST_MODEL"; then
  echo "   (이미 있음 — 건너뜀. 강제로 다시 보내려면 원격에서 지운다)"
else
  scp -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes \
      "$SRC_MODEL" "$TARGET:$REMOTE_DIR/$DST_MODEL"
fi

if [[ "$DO_VENV" == "1" ]]; then
  echo "== venv 구성(이미 있으면 갱신만)"
  "${SSH[@]}" "$TARGET" "
    set -e
    cd ~/$REMOTE_DIR
    [ -d venv ] || python3 -m venv venv
    ./venv/bin/pip install -q --upgrade pip
    ./venv/bin/pip install -q -r requirements-pi4.txt
    ./venv/bin/python -c 'import numpy,onnxruntime,cv2,requests; print(\"deps OK\")'
  "
fi

echo "== 배포 완료"
"${SSH[@]}" "$TARGET" "cd ~/$REMOTE_DIR && ls && echo '---' && ./venv/bin/python -c \"
import json; c=json.load(open('config.json')); print('엣지 대상:', c['edge']['host'], c['edge']['port'])\" 2>/dev/null || true"
echo
echo "실행:  ssh $TARGET 'cd ~/$REMOTE_DIR && ./venv/bin/python pi4_agent.py'"
