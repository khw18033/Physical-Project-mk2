#!/usr/bin/env bash
# =============================================================================
# collect_env.sh — 360° 카메라 파이프라인 서버 환경 수집기
#
# [무엇을 하나]
#   팀원이 같은 환경을 다시 만들 수 있도록, 서버의 파이썬/CUDA/패키지/파일 상태를
#   텍스트 파일 하나로 모은다. 아무것도 설치하거나 바꾸지 않는다. 읽기만 한다.
#
# [사용]
#   서버에서:
#     bash collect_env.sh                 # 결과가 ./env_report_<host>_<날짜>.txt
#     bash collect_env.sh -o /tmp/x.txt   # 출력 경로 지정
#
#   venv 를 켜고 돌려도 되고 안 켜고 돌려도 된다. 스크립트가 알아서 켜서 본다.
#
# [안전]
#   - 비밀번호로 보이는 줄은 마스킹한다(redis password 등).
#   - 실패하는 명령이 있어도 끝까지 돈다.
#   - 쓰기는 출력 파일 하나뿐.
# =============================================================================

OUT=""
while getopts "o:" opt; do
  case "$opt" in
    o) OUT="$OPTARG" ;;
    *) echo "usage: bash collect_env.sh [-o 출력파일]"; exit 1 ;;
  esac
done

HOST="$(hostname 2>/dev/null || echo unknown)"
STAMP="$(date +%Y%m%d_%H%M%S)"
[ -z "$OUT" ] && OUT="./env_report_${HOST}_${STAMP}.txt"

# ── 경로 설정 (다르면 여기만 고칠 것) ────────────────────────────────────────
CAP="${CAP:-$HOME/capstone-db}"
VENV="${VENV:-$CAP/venv_image}"
IMGSRV="${IMGSRV:-$CAP/image_server}"
DOCX="${DOCX:-$CAP/docx2026}"
CONDA_SH="${CONDA_SH:-/home/jny/miniconda3/etc/profile.d/conda.sh}"
CONDA_ENV="${CONDA_ENV:-unidepth}"

# ── 유틸 ─────────────────────────────────────────────────────────────────────
sec() { printf '\n\n%s\n%s\n%s\n' "============================================================" "  $*" "============================================================"; }
sub() { printf '\n--- %s ---\n' "$*"; }
run() { printf '$ %s\n' "$*"; eval "$@" 2>&1 | sed 's/^/  /'; }
# 비밀번호로 보이는 줄 마스킹
mask() { sed -E 's/(password|passwd|secret|token|api_key)([[:space:]]*[:=][[:space:]]*).*/\1\2<<MASKED>>/I'; }

finfo() {  # finfo <경로> — 존재/크기/권한/소유자/시각/해시
  if [ -e "$1" ]; then
    if [ -d "$1" ]; then
      printf '  [DIR ] %s\n' "$1"
      printf '         %s\n' "$(du -sh "$1" 2>/dev/null | cut -f1) / $(find "$1" -type f 2>/dev/null | wc -l) files"
      printf '         %s\n' "$(stat -c '%A %U:%G  %y' "$1" 2>/dev/null)"
    else
      printf '  [FILE] %s\n' "$1"
      printf '         %s\n' "$(stat -c '%s bytes  %A  %U:%G  %y' "$1" 2>/dev/null)"
      case "$1" in
        *.pt|*.pth|*.onnx|*.trt|*.bin|*.safetensors)
          printf '         md5 %s\n' "$(md5sum "$1" 2>/dev/null | cut -d' ' -f1)" ;;
      esac
    fi
  else
    printf '  [MISS] %s   ← 없음\n' "$1"
  fi
}

pytest_import() {  # pytest_import <python> <모듈명> [표시이름]
  local PY="$1" MOD="$2" NAME="${3:-$2}"
  local V
  V="$("$PY" -c "
import importlib,sys
try:
    m=importlib.import_module('$MOD')
    print(getattr(m,'__version__','(버전정보 없음)'))
except Exception as e:
    print('IMPORT FAIL: %s: %s' % (type(e).__name__, e))
" 2>&1 | head -3)"
  printf '  %-22s %s\n' "$NAME" "$V"
}

# =============================================================================
exec > >(tee "$OUT") 2>&1

cat <<HEADER
=============================================================================
 360도 카메라 파이프라인 — 서버 환경 리포트
=============================================================================
 수집 시각 : $(date '+%Y-%m-%d %H:%M:%S %Z')
 호스트    : $HOST
 사용자    : $(whoami)   (uid=$(id -u))
 홈        : $HOME
 스크립트  : collect_env.sh
 출력 파일 : $OUT
-----------------------------------------------------------------------------
 ※ 이 파일에 비밀번호가 들어가지 않도록 password/token 류는 마스킹했습니다.
   그래도 외부 공유 전에 한 번 훑어보세요.
=============================================================================
HEADER

# ── 1. OS / 커널 ─────────────────────────────────────────────────────────────
sec "1. OS / 커널"
run "cat /etc/os-release"
run "uname -a"
sub "glibc"
run "ldd --version | head -1"

# ── 2. GPU / 드라이버 / CUDA ─────────────────────────────────────────────────
sec "2. GPU / 드라이버 / CUDA"
if command -v nvidia-smi >/dev/null 2>&1; then
  run "nvidia-smi"
else
  echo "  nvidia-smi 없음"
fi
sub "nvcc (CUDA 툴킷 — 없어도 pip torch 는 동작함)"
if command -v nvcc >/dev/null 2>&1; then run "nvcc --version"; else echo "  nvcc 없음 (정상일 수 있음)"; fi
sub "/usr/local/cuda*"
run "ls -d /usr/local/cuda* 2>/dev/null || echo '  없음'"

# ── 3. 시스템 파이썬 ─────────────────────────────────────────────────────────
sec "3. 시스템 파이썬"
run "which -a python3 python 2>/dev/null"
run "python3 -V"
sub "설치된 python3.x 들"
run "ls /usr/bin/python3* 2>/dev/null"

# ── 4. venv_image ────────────────────────────────────────────────────────────
sec "4. venv_image — 360 파이프라인이 실제로 쓰는 환경"
echo "경로: $VENV"
if [ -d "$VENV" ]; then
  sub "pyvenv.cfg  (★ base 파이썬 절대경로 — 복사 시 문제되는 부분)"
  run "cat '$VENV/pyvenv.cfg'"
  sub "크기 / 권한"
  finfo "$VENV"
  run "stat -c '%A %U:%G' '$VENV'"
  sub "bin/ 목록"
  run "ls '$VENV/bin'"
  sub "bin/pip 의 shebang  (★ 절대경로라 복사 시 깨지는 부분)"
  run "head -1 '$VENV/bin/pip' 2>/dev/null"
  sub "activate 안의 VIRTUAL_ENV  (★ 문자열로 박혀 있음)"
  run "grep -m2 'VIRTUAL_ENV=' '$VENV/bin/activate' 2>/dev/null"
  PY="$VENV/bin/python"
  sub "venv 파이썬 버전"
  run "'$PY' -V"
else
  echo "  !! venv 없음: $VENV"
  PY="$(command -v python3)"
  echo "  → 시스템 python3 로 계속 진행: $PY"
fi

# ── 5. pip freeze (★ 재구성의 핵심) ──────────────────────────────────────────
sec "5. pip freeze — 전체 패키지 목록 (★ requirements 의 원본)"
echo "아래 블록을 그대로 잘라내면 requirements-server.txt 가 됩니다."
echo "-------------------- BEGIN requirements-server.txt --------------------"
"$PY" -m pip freeze 2>&1
echo "--------------------  END  requirements-server.txt --------------------"

sub "pip / setuptools / wheel 버전"
run "'$PY' -m pip -V"

sub "패키지 개수"
run "'$PY' -m pip freeze 2>/dev/null | wc -l"

# ── 6. 핵심 패키지 import 확인 ───────────────────────────────────────────────
sec "6. 핵심 패키지 import 확인 (실제로 되는지)"
echo "[360 파이프라인 필수]"
pytest_import "$PY" numpy
pytest_import "$PY" cv2            "opencv (cv2)"
pytest_import "$PY" yaml           "pyyaml (yaml)"
pytest_import "$PY" py360convert
pytest_import "$PY" ultralytics
pytest_import "$PY" torch
pytest_import "$PY" torchvision
pytest_import "$PY" fastapi
pytest_import "$PY" uvicorn
pytest_import "$PY" requests
pytest_import "$PY" PIL            "pillow (PIL)"

echo
echo "[UniDepth 를 붙이려면 필요 — ★ 이 줄이 이번 작업의 관문]"
pytest_import "$PY" unidepth       "unidepth"
"$PY" -c "
try:
    from unidepth.models import UniDepthV2
    print('  UniDepthV2 import    OK  ← venv_image 에서 바로 쓸 수 있음')
except Exception as e:
    print('  UniDepthV2 import    FAIL: %s: %s' % (type(e).__name__, e))
    print('                       → §9 의 conda unidepth 환경을 봐야 함')
" 2>&1

echo
echo "[GO1 계통 (참고)]"
pytest_import "$PY" redis
pytest_import "$PY" orjson
pytest_import "$PY" xformers

# ── 7. torch 상세 (★ CUDA 빌드 식별) ─────────────────────────────────────────
sec "7. torch 상세 — ★ 이게 있어야 같은 빌드를 재설치할 수 있다"
"$PY" - <<'PYEOF' 2>&1
try:
    import torch
    print(f"  torch.__version__        : {torch.__version__}")
    print(f"  torch.version.cuda       : {torch.version.cuda}")
    try:
        print(f"  cudnn                    : {torch.backends.cudnn.version()}")
    except Exception as e:
        print(f"  cudnn                    : (조회 실패) {e}")
    print(f"  torch.cuda.is_available(): {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"  device_count             : {torch.cuda.device_count()}")
        for i in range(torch.cuda.device_count()):
            print(f"    [{i}] {torch.cuda.get_device_name(i)}  "
                  f"capability={torch.cuda.get_device_capability(i)}")
    print()
    v = torch.__version__
    if "+cu" in v:
        cu = v.split("+")[1]
        print(f"  ▶ 재설치 명령:")
        print(f"      pip install torch=={v.split('+')[0]} torchvision --index-url "
              f"https://download.pytorch.org/whl/{cu}")
    else:
        print(f"  ▶ 버전 문자열에 +cuXXX 가 없습니다. conda 설치이거나 CPU 빌드일 수 있음.")
        print(f"      pip show torch / conda list torch 로 출처를 확인하세요.")
except Exception as e:
    print(f"  torch import 실패: {type(e).__name__}: {e}")
PYEOF

sub "pip show torch"
run "'$PY' -m pip show torch 2>&1 | head -12"

# ── 8. pip 설치 출처 ─────────────────────────────────────────────────────────
sec "8. pip 설정 / 인덱스 출처"
run "'$PY' -m pip config list 2>&1"
for f in /etc/pip.conf "$HOME/.pip/pip.conf" "$HOME/.config/pip/pip.conf"; do
  if [ -f "$f" ]; then sub "$f"; cat "$f" | mask | sed 's/^/  /'; fi
done

# ── 9. conda 환경 (unidepth 는 여기 있을 가능성이 큼) ────────────────────────
sec "9. conda 환경 — UniDepth 의 실제 위치 추적"
if [ -f "$CONDA_SH" ]; then
  echo "  conda.sh 발견: $CONDA_SH"
  # shellcheck disable=SC1090
  . "$CONDA_SH" 2>/dev/null
  sub "conda 버전 / 환경 목록"
  run "conda --version"
  run "conda env list"
  sub "'$CONDA_ENV' 환경 안의 파이썬·torch·unidepth"
  if conda activate "$CONDA_ENV" 2>/dev/null; then
    run "python -V"
    run "python -c \"import torch;print('torch',torch.__version__, torch.version.cuda, torch.cuda.is_available())\""
    run "python -c \"from unidepth.models import UniDepthV2;print('UniDepthV2 OK')\""
    run "python -c \"import unidepth,os;print('unidepth 위치:',os.path.dirname(unidepth.__file__))\""
    echo
    echo "---------- BEGIN requirements-unidepth.txt (conda 환경 pip freeze) ----------"
    python -m pip freeze 2>&1
    echo "----------  END  requirements-unidepth.txt ----------"
    sub "conda list (요약)"
    run "conda list | head -80"
    sub "★ conda 환경 통째 내보내기 (권장)"
    echo "  conda env export -n $CONDA_ENV > unidepth_env.yml"
    echo "  # 또는 경로 독립 아카이브:"
    echo "  conda install -n base conda-pack && conda pack -n $CONDA_ENV -o unidepth.tar.gz"
    conda deactivate 2>/dev/null
  else
    echo "  '$CONDA_ENV' 활성화 실패 — 권한이 없거나 환경명이 다릅니다."
    echo "  위 'conda env list' 결과에서 실제 이름을 확인하세요."
  fi
else
  echo "  conda.sh 없음: $CONDA_SH"
  echo "  → 다른 위치를 찾아봅니다."
  run "ls -d /home/*/miniconda3 /home/*/anaconda3 /opt/conda 2>/dev/null || echo '  못 찾음'"
fi

# ── 10. UniDepth 소스/체크포인트 위치 ────────────────────────────────────────
sec "10. UniDepth 소스 · 체크포인트"
echo "[체크포인트]"
finfo "$IMGSRV/checkpoints"
finfo "$IMGSRV/checkpoints/unidepth-v2-vitb14"
run "ls -la '$IMGSRV/checkpoints/unidepth-v2-vitb14' 2>/dev/null"
echo
echo "[UniDepth 소스 트리 (pip install -e 로 깔렸을 수 있음)]"
run "find /home -maxdepth 4 -type d -name 'UniDepth*' 2>/dev/null | head"
run "find /home -maxdepth 5 -name 'unidepth' -type d 2>/dev/null | head"
echo
echo "[HuggingFace 캐시]"
finfo "$HOME/.cache/huggingface"
run "ls '$HOME/.cache/huggingface/hub' 2>/dev/null | head -20"

# ── 11. 파일 인벤토리 ────────────────────────────────────────────────────────
sec "11. 파일 인벤토리 — 360 파이프라인"

sub "11-1. image_server"
for f in \
  "$IMGSRV/pano_receiver.py" \
  "$IMGSRV/unidepth_dual_yolo_config.yaml" \
  "$IMGSRV/yolov8s-world.pt" \
  "$IMGSRV/best_finetune_train3.pt" \
  "$IMGSRV/unidepth_dual_yolo.py" \
  "$IMGSRV/server_stream_depth_v2.py" \
  ; do finfo "$f"; done

sub "11-2. docx2026"
for f in \
  "$DOCX/anchor360_live.py" \
  "$DOCX/e2p.py" \
  "$DOCX/detect_ground_3b1.py" \
  "$DOCX/detect_send_3b2.py" \
  "$DOCX/detect_send_3b2_timed.py" \
  "$DOCX/relay_loop.py" \
  "$DOCX/weights/clip/ViT-B-32.pt" \
  "$DOCX/live_out" \
  ; do finfo "$f"; done

sub "11-3. 디렉터리 전체 목록"
run "ls -la '$IMGSRV' 2>/dev/null"
run "ls -la '$DOCX' 2>/dev/null"

sub "11-4. config 의 절대경로 항목 (★ 계정이 바뀌면 고쳐야 하는 줄)"
run "grep -n -E 'weight:|model_name:|/home/' '$IMGSRV/unidepth_dual_yolo_config.yaml' 2>/dev/null | head -20"

sub "11-5. anchor360_live.py 패치 적용 여부"
run "grep -n -- 'no.wait.stable' '$DOCX/anchor360_live.py' 2>/dev/null"
echo "  ※ 두 줄(argparse 하이픈 + 코드 밑줄)이 나와야 정상입니다."

sub "11-6. 데이터 폴더 크기"
run "du -sh '$IMGSRV/pano_captures' 2>/dev/null"
run "du -sh '$DOCX/live_out' 2>/dev/null"
run "ls '$IMGSRV/pano_captures/pro2_anchor' 2>/dev/null | wc -l"

# ── 12. 디스크 / 포트 ────────────────────────────────────────────────────────
sec "12. 디스크 · 포트"
sub "디스크"
run "df -h '$HOME' '$CAP' 2>/dev/null | sort -u"
run "du -sh '$VENV' 2>/dev/null"
echo "  ※ venv 1벌당 이 크기가 사람 수만큼 필요합니다(안 2로 갈 경우)."
sub "열려 있는 포트 (7864 GO1 / 7866 pano / 5010 Anchor360 / 7860 redis)"
if command -v ss >/dev/null 2>&1; then
  run "ss -tulpn 2>/dev/null | grep -E '7860|7864|7865|7866|5009|5010|5011' || echo '  해당 포트 없음'"
else
  run "netstat -tulpn 2>/dev/null | grep -E '7860|7864|7866|5010' || echo '  netstat 없음'"
fi
sub "돌고 있는 관련 프로세스"
run "ps -ef | grep -E 'pano_receiver|anchor360_live|unidepth_dual|server_stream_depth' | grep -v grep || echo '  없음'"

# ── 13. 요약 ─────────────────────────────────────────────────────────────────
sec "13. 요약 — 팀원에게 전달할 때 확인할 것"
cat <<'SUMEOF'
  [ ] §5 의 BEGIN~END 블록 → requirements-server.txt 로 저장
  [ ] §7 의 "▶ 재설치 명령" 줄 → requirements 맨 위에 주석으로 복사
  [ ] §6 의 'UniDepthV2 import' 가 OK 인지 FAIL 인지 확인
        OK   → venv_image 그대로 쓰면 됨
        FAIL → §9 의 conda 환경을 써야 함 (conda env export 또는 conda-pack)
  [ ] §9 의 BEGIN~END 블록(있다면) → requirements-unidepth.txt 로 저장
  [ ] §11 에서 [MISS] 로 뜬 파일이 있는지 확인
  [ ] §12 의 디스크 여유가 (venv 크기 × 인원수) 보다 큰지 확인
  [ ] 이 파일에 비밀번호/키가 남아 있지 않은지 눈으로 한 번 확인
SUMEOF

printf '\n\n=== 수집 완료: %s ===\n' "$OUT"
