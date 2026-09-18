#!/usr/bin/env bash
# 합성 H.264 Annex-B fixture 생성 + 검산 (Phase 4 단계 3-1). 컴퓨터에서 한 번 만들어 커밋한다 —
# 서버 ffmpeg 를 전제조건으로 두지 않는다. 재생성 가능해야 하므로 스크립트도 함께 커밋한다.
#
# 규격: 464×400(HW 실측 해상도) · 4초 · 30fps · IDR 간격 15 고정 · baseline · 매 IDR 에 SPS·PPS 인밴드 · Annex-B.
# 판정은 옵션이 아니라 실측이다 — 바이트스트림에서 NAL 타입 7(SPS)이 IDR(타입 5) 개수만큼 나오는지 센다.
# 한 번만 나오면 fixture 가 틀린 것이다(뷰어가 중간부터 붙으면 디코더를 구성하지 못한다). 검산이 실패할 때만
# `-x264-params repeat-headers=1` 을 붙여 다시 만든다. raw h264 출력(-f h264)은 global header 를 쓰지 않아
# libx264 가 기본으로 매 IDR 에 SPS·PPS 를 반복한다 — 그래서 v1 의 `-bsf:v dump_extra` 를 뺐다.
#
# JPEG 프로파일 3장(synthetic_464x400_NN.jpg, q:v 2 → HW 실측 ~25KB 급)도 같이 만든다.
#
# 사용:  bash tests/fixtures/make_h264_fixture.sh
#        FFMPEG=/path/to/ffmpeg PYTHON=/path/to/python bash tests/fixtures/make_h264_fixture.sh
#   (컴퓨터에는 시스템 ffmpeg 가 없어 venv 의 imageio-ffmpeg 바이너리를 FFMPEG 로 넘겼다 — 2026-09-18)
#
# implements: BE-T-07 (합성 fixture — 실물 카메라 없이 경로·정합 검증)
set -euo pipefail
cd "$(dirname "$0")"
FFMPEG="${FFMPEG:-ffmpeg}"
PYTHON="${PYTHON:-python3}"
OUT="synthetic_464x400.h264"
EXTRA_PARAMS="${EXTRA_PARAMS:-}"

encode() {
  # $1 = 추가 x264 파라미터("" 또는 "-x264-params repeat-headers=1")
  # shellcheck disable=SC2086
  "$FFMPEG" -y -hide_banner -loglevel error \
    -f lavfi -i testsrc2=size=464x400:rate=30 -t 4 \
    -c:v libx264 -profile:v baseline -pix_fmt yuv420p \
    -g 15 -keyint_min 15 -sc_threshold 0 -b:v 600k $1 \
    -f h264 "$OUT"
}

check() {
  # AU 규칙·NAL 분류는 tests/media_publisher.py 것을 그대로 쓴다(두 벌이 되면 갈린다).
  PYTHONPATH=.. "$PYTHON" - <<'EOF'
import sys
from media_publisher import count_nal_types, load_access_units, H264_FIXTURE
counts = count_nal_types(H264_FIXTURE)
units = load_access_units(H264_FIXTURE)
sps, pps, idr, p = counts.get(7, 0), counts.get(8, 0), counts.get(5, 0), counts.get(1, 0)
kf = sum(1 for u in units if u.keyframe)
print(f"NAL: SPS={sps} PPS={pps} IDR={idr} nonIDR={p} SEI={counts.get(6,0)} AUD={counts.get(9,0)} | AU={len(units)} keyframe AU={kf} bytes={H264_FIXTURE.stat().st_size}")
ok = sps == idr and pps == idr and idr >= 2 and kf == idr and len(units) == idr + p
print("검산:", "OK" if ok else "FAIL — SPS/PPS 가 IDR 마다 반복되지 않는다")
sys.exit(0 if ok else 1)
EOF
}

encode "$EXTRA_PARAMS"
if ! check; then
  echo "재시도: -x264-params repeat-headers=1"
  encode "-x264-params repeat-headers=1"
  check
fi

# JPEG 프로파일 — 3장, 464×400, q:v 2
"$FFMPEG" -y -hide_banner -loglevel error \
  -f lavfi -i testsrc2=size=464x400:rate=1 -t 3 -q:v 2 -f image2 "synthetic_464x400_%02d.jpg"
ls -l synthetic_464x400_*.jpg "$OUT"
