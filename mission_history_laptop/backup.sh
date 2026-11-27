#!/usr/bin/env bash
# =============================================================================
# 임무 이력 서버 백업 — DB 표 두 개(mission_runs · mission_run_images) + 그림 폴더
# v2 (261119): 매일 백업 보관을 「최근 30개」에서 사용자 결정 「최근 30일(한 달치)」로 고쳤다.
#
#   bash /home/khw67/mission_history/server/backup.sh manual ["메모"]   수동 — 필요할 때 직접. 지우지 않는다
#   bash /home/khw67/mission_history/server/backup.sh daily             매일 자동(systemd 타이머가 22:00 KST 에 부른다)
#                                                                    daily_* 는 최근 30일치만 남긴다(만든 지 30일 지난 것을 지운다)
#
# 남는 곳: /home/khw67/mission_history/backups/<manual|daily>_<YYMMDD_HHMMSS>/
#   db.dump       pg_dump 사용자 지정 형식(표 두 개의 구조 · 데이터 · 권한)
#   images.tar    그림 폴더 통째(tar, 압축 안 함 — JPEG 는 이미 압축돼 있다)
#   info.txt      시각 · 메모 · 판 수 · 그림 수 · md5
#
# 읽기만 한다 — DB 와 그림 폴더를 바꾸지 않는다. 같은 때 두 번 돌면 뒤의 것은 기다리지 않고 끝난다.
# 노트북판(261125) — 원격 서버판 v2 에서 경로(사용자 dg → khw67)와 DB 를 부르는 세 줄만 바꿨다.
#   원격 서버는 컨테이너 안 관리자로 덤프했다. 노트북 WSL 에는 컨테이너가 없어, WSL PostgreSQL 에
#   읽기만 하는 계정 khw67 로 붙는다(이 스크립트를 도는 사용자 · 같은 기기 소켓 · 비밀번호 없음 — laptop_db_init.sql).
# =============================================================================
set -euo pipefail

BASE="/home/khw67/mission_history"
IMAGES="$BASE/images"
DEST="$BASE/backups"
KEEP_DAYS=30                   # 매일 백업 보관 기간(일) — 사용자 결정 「최근 30일, 한 달치」

usage() { sed -n '6,9p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

mode="${1:-}"
memo="${2:-}"
case "$mode" in
    manual|daily) ;;
    *) usage ;;
esac

mkdir -p "$DEST"
exec 9>"$DEST/.lock"
if ! flock -n 9; then
    echo "다른 백업이 돌고 있다 — 이번 것은 건너뛴다"
    exit 0
fi

stamp="$(TZ=Asia/Seoul date +%y%m%d_%H%M%S)"
name="${mode}_${stamp}"
work="$DEST/.tmp_${name}"
final="$DEST/${name}"
rm -rf "$DEST"/.tmp_*          # 앞서 끊긴 백업의 찌꺼기
mkdir -p "$work"

echo "백업 시작: $name"

# 1) DB 표 두 개 — WSL PostgreSQL 에 읽기 계정 khw67 로(비밀번호 없이 소켓으로 붙는다)
pg_dump -d mk2 -Fc -t mission_runs -t mission_run_images > "$work/db.dump"

# 2) 그림 폴더
if [ -d "$IMAGES" ]; then
    tar -C "$BASE" -cf "$work/images.tar" images
else
    tar -cf "$work/images.tar" --files-from /dev/null
fi

# 3) 기록
runs="$(psql -d mk2 -tAc "SELECT count(*) FROM mission_runs WHERE mission_doc IS NOT NULL")"
images="$(psql -d mk2 -tAc "SELECT count(*) FROM mission_run_images")"
{
    echo "백업: $name"
    echo "시각(KST): $(TZ=Asia/Seoul date '+%F %T')"
    echo "메모: ${memo:-(없음)}"
    echo "목록에 나오는 판 수: $runs"
    echo "그림 행 수: $images"
    echo "그림 파일 수: $(find "$IMAGES" -type f ! -name '.*.tmp' 2>/dev/null | wc -l)"
    echo
    (cd "$work" && md5sum db.dump images.tar && ls -la db.dump images.tar)
} > "$work/info.txt"

mv "$work" "$final"
echo "백업 끝: $final"
cat "$final/info.txt"

# 4) 매일 백업은 최근 KEEP_DAYS 일치만 남긴다 — 폴더 이름의 시각(KST)이 지금보다 KEEP_DAYS 일 넘게 앞선 것을 지운다.
#    개수가 아니라 날짜로 센다(서버가 며칠 꺼져 있었어도 30일 지난 것만 지운다). 수동 백업은 건드리지 않는다.
if [ "$mode" = "daily" ]; then
    cutoff="daily_$(TZ=Asia/Seoul date -d "-${KEEP_DAYS} days" +%y%m%d_%H%M%S)"
    old=""
    for d in "$DEST"/daily_*; do
        [ -d "$d" ] || continue
        b="$(basename "$d")"
        [[ "$b" =~ ^daily_[0-9]{6}_[0-9]{6}$ ]] || continue
        if [[ "$b" < "$cutoff" ]]; then
            old+="$d"$'\n'
        fi
    done
    if [ -n "$old" ]; then
        echo "${KEEP_DAYS}일 지난 매일 백업 정리 (기준 ${cutoff#daily_} 보다 앞선 것):"
        printf '%s' "$old"
        printf '%s' "$old" | xargs -r -d '\n' rm -rf
    fi
fi
