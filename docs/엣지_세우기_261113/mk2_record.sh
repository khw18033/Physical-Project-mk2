#!/usr/bin/env bash
# =============================================================================
# mk2_record.sh — MK2 합동 실측 서버 기록 도구 (BE 가 서버 창에서 돌린다)
#
#   bash ~/mk2_joint/mk2_record.sh start  <이름>            시작 상태를 파일로 남긴다
#   bash ~/mk2_joint/mk2_record.sh mark   <이름> "<메모>"   지금 시각 · 메모 · 계측 한 벌을 남긴다(몇 번이든)
#   bash ~/mk2_joint/mk2_record.sh end    <이름>            끝 상태 · 서비스 로그 · 세션별 집계를 남기고 묶는다
#   bash ~/mk2_joint/mk2_record.sh status <이름>            그 기록이 시작됐는지 · 끝났는지
#
# 남는 곳: ~/mk2_joint/<이름>/  →  end 뒤 ~/mk2_joint/<이름>.tar.gz  (이 묶음 하나를 PC 로 가져온다)
#
# - 서버 설정 · 서비스는 바꾸지 않는다(전부 읽기만). 뒤에서 도는 프로세스도 없다 — 서비스 로그는 end 때
#   journalctl --since <시작 시각> 으로 한 번에 받는다. 그래서 start 뒤 서버 창을 닫아도 된다.
# - .env 를 읽지 않는다. 서비스 로그의 token= 값은 서버가 이미 *** 로 가리지만, 묶기 전에 한 번 더 가린다.
# - 시각: 파일 안의 T0 · T1 은 UTC. 사람이 볼 곳에는 KST 를 같이 적는다.
# =============================================================================
set -u

REPO="${MK2_REPO:-/home/dg/capstone-db/phase1_work/Physical-Project-mk2}"
BASE="${MK2_JOINT_DIR:-$HOME/mk2_joint}"
PROM="${MK2_PROM_URL:-http://localhost:7861}"
TSDB_CONTAINER="${MK2_TSDB_CONTAINER:-capstone_timescaledb}"
UNITS=(mk2-ingest mk2-storage-consumer mk2-ws-echo mk2-capture)

usage() {
    sed -n '5,8p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
}

kst() { TZ=Asia/Seoul date '+%F %T'; }

# PromQL 하나 → "라벨들 값" 한 줄씩. 결과가 없으면 「없음」(= 그 프로세스가 뜬 뒤로 한 번도 안 늘었다).
promq() {
    curl -s --max-time 5 "$PROM/api/v1/query" --data-urlencode "query=$1" | python3 -c '
import sys, json
try:
    result = json.load(sys.stdin)["data"]["result"]
except Exception as exc:
    print("조회 실패:", exc)
    sys.exit(0)
if not result:
    print("없음")
for series in result:
    labels = ",".join(k + "=" + v for k, v in sorted(series["metric"].items())) or "(전체)"
    print(labels, series["value"][1])
'
}

counters() {
    echo "## 계측 (Prometheus $PROM — 프로세스가 다시 뜨면 0부터 센다)"
    local query
    for query in \
        'sum by (channel) (be_ingest_received_total)' \
        'sum by (channel, stage) (be_ingest_rejected_total)' \
        'sum by (channel, outcome) (be_kafka_produce_total)' \
        'sum by (channel) (be_storage_consumed_total)' \
        'sum by (channel, outcome) (be_storage_write_total)' \
        'sum by (channel) (be_gateway_push_total)' \
        'sum(be_gateway_media_ingress_total)' \
        'sum by (outcome) (be_gateway_media_frames_total)' \
        'sum by (stage) (be_gateway_media_rejected_total)' \
        'sum by (endpoint) (be_gateway_clients)'; do
        echo "### $query"
        promq "$query"
    done
}

tsdb() {
    docker exec -i "$TSDB_CONTAINER" psql -U postgres -d mk2 -tA -c "$1" 2>&1
}

quarantine_lines() {
    if [ -f "$REPO/backend/ingest/quarantine.jsonl" ]; then
        wc -l < "$REPO/backend/ingest/quarantine.jsonl"
    else
        echo 0
    fi
}

snapshot() {   # $1 = start | end
    echo "# $1 — $(hostname) · UTC $(date -u '+%F %T') · KST $(kst)"
    echo
    echo "## 재부팅 뒤 기동 시각"
    uptime -s
    echo
    echo "## 상주 넷 (상태 · 마지막으로 뜬 시각)"
    local unit
    for unit in "${UNITS[@]}"; do
        printf '%-22s %-9s %s\n' "$unit" "$(systemctl is-active "$unit")" "$(systemctl show -p ActiveEnterTimestamp --value "$unit")"
    done
    echo
    echo "## 듣는 포트"
    ss -ltn | grep -E ':(1883|8765|8766|8767|9092|9095|4316|4318|7861)[[:space:]]' || echo "(없음)"
    echo
    echo "## 붙어 있는 연결 — 8765 뷰어(/state · /media) · 8766 엣지 영상 입구"
    ss -tn state established '( sport = :8765 or sport = :8766 )' || true
    echo
    echo "## 저장소 사본 판 (md5)"
    (cd "$REPO" && md5sum backend/settings.py backend/ingest/bridge.py backend/gateway/ws_echo.py backend/gateway/media.py) 2>&1
    echo
    echo "## 서버 격리 파일 줄 수"
    quarantine_lines
    echo
    echo "## 서버 미전송 파일 줄 수 (서버 브릿지가 못 보내고 버린 것 — 평소 0)"
    if [ -f "$REPO/backend/ingest/unsent.jsonl" ]; then wc -l < "$REPO/backend/ingest/unsent.jsonl"; else echo "0 (파일 없음)"; fi
    echo
    counters
    echo
    echo "## TSDB telemetry 전체 행 수"
    tsdb "SELECT count(*) FROM telemetry;"
}

need_dir() {
    DIR="$BASE/$1"
    if [ ! -f "$DIR/T0" ]; then
        echo "시작 기록이 없다: $DIR — 먼저 start $1"
        exit 1
    fi
}

cmd_start() {
    local name="$1"
    DIR="$BASE/$name"
    if [ -e "$DIR" ]; then
        echo "이미 있다: $DIR — 다른 이름을 쓴다"
        exit 1
    fi
    mkdir -p "$DIR"
    date -u '+%F %T' > "$DIR/T0"
    quarantine_lines > "$DIR/quarantine_lines_at_start"
    snapshot start > "$DIR/start.txt" 2>&1
    echo "기록 시작: $DIR"
    echo "  T0 = $(cat "$DIR/T0") UTC (KST $(kst))"
    echo "  지금 상태: $DIR/start.txt"
    echo "  서비스 로그를 눈으로 보려면(선택, 다른 서버 창): journalctl -f -u mk2-ingest -u mk2-ws-echo -u mk2-storage-consumer"
    echo "  끝나면: bash $0 end $name"
}

cmd_mark() {
    local name="$1"
    shift
    need_dir "$name"
    {
        echo "================================================================"
        echo "MARK UTC $(date -u '+%F %T') · KST $(kst) | $*"
        counters
    } >> "$DIR/marks.txt" 2>&1
    echo "남김: KST $(kst) | $* → $DIR/marks.txt"
}

cmd_status() {
    local name="$1"
    need_dir "$name"
    echo "$DIR"
    echo "  T0 = $(cat "$DIR/T0") UTC"
    if [ -f "$DIR/T1" ]; then
        echo "  T1 = $(cat "$DIR/T1") UTC — 끝났다. 묶음: $BASE/$name.tar.gz"
    else
        echo "  아직 진행 중 (end 전)"
    fi
}

cmd_end() {
    local name="$1"
    need_dir "$name"
    if [ -f "$DIR/T1" ]; then
        echo "이미 끝났다: $DIR (T1 $(cat "$DIR/T1") UTC)"
        exit 1
    fi
    local t0 t1 start_lines
    t0="$(cat "$DIR/T0")"
    t1="$(date -u '+%F %T')"
    echo "$t1" > "$DIR/T1"
    start_lines="$(cat "$DIR/quarantine_lines_at_start")"

    snapshot end > "$DIR/end.txt" 2>&1

    # 서비스 로그 — 시작부터 끝까지 한 번에 (token= 값은 한 번 더 가린다)
    TZ=UTC journalctl -q -o short-iso --no-pager --since "$t0" --until "$t1" \
        -u mk2-ingest -u mk2-storage-consumer -u mk2-ws-echo -u mk2-capture 2>&1 \
        | sed -E 's/(token=)[^&[:space:]]*/\1***/g' > "$DIR/journal.log"

    # 서버 격리 파일 — 이번에 더해진 줄만
    if [ -f "$REPO/backend/ingest/quarantine.jsonl" ]; then
        tail -n +"$((start_lines + 1))" "$REPO/backend/ingest/quarantine.jsonl" > "$DIR/quarantine_new.jsonl"
    else
        : > "$DIR/quarantine_new.jsonl"
    fi

    {
        echo "# 서비스 로그에서 뽑은 것 — T0 $t0 ~ T1 $t1 (UTC)"
        echo
        echo "## 서버 브릿지(mk2-ingest)가 produce 한 건수 — 장치별 (엣지 경로면 0 이어야 한다)"
        grep -o 'produce: .*source_id=[^,]*' "$DIR/journal.log" | grep -o 'source_id=[^,]*' | sort | uniq -c || echo "(없음)"
        echo
        echo "## 서버 브릿지 격리 · 실패 줄"
        grep -E '격리|Kafka produce 실패|대기열 가득' "$DIR/journal.log" || echo "(없음)"
        echo
        echo "## 영상 — 엣지 입구(/ingest) · 뷰어(/media) · 거부"
        grep -E '/ingest|/media|엣지접속|거부' "$DIR/journal.log" || echo "(없음)"
        echo
        echo "## 상태 — 뷰어 접속(/state) · 구독"
        grep -E 'mk2\.gateway .*/state' "$DIR/journal.log" || echo "(없음)"
        echo
        echo "## 오류 · 경고 줄"
        grep -E ' (ERROR|WARNING|CRITICAL) |Traceback' "$DIR/journal.log" || echo "(없음)"
    } > "$DIR/journal_digest.txt" 2>&1

    # TSDB — T0 이후 서버에 저장된 것 (장치 · 채널 · 세션별)
    {
        echo "# TSDB — received_at >= T0($t0 UTC). 칸: source_id | channel | session_id | 행 | 순번 종류 | 첫 순번 | 끝 순번 | 첫 도착(KST) | 끝 도착(KST) | 가장 오래 기다린 초(received_at − ingest_at)"
        tsdb "SELECT source_id, channel, coalesce(session_id, '-'), count(*), count(DISTINCT sequence_id), min(sequence_id), max(sequence_id),
                     to_char(min(received_at) AT TIME ZONE 'Asia/Seoul', 'HH24:MI:SS'), to_char(max(received_at) AT TIME ZONE 'Asia/Seoul', 'HH24:MI:SS'),
                     round(max(extract(epoch FROM received_at - ingest_at))::numeric, 1)
              FROM telemetry WHERE received_at >= '$t0+00'
              GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;"
        echo
        echo "# 빠진 순번 구간 — 순번이 둘 이상인 세션만(로봇 v1 처럼 순번이 늘 0 이면 빠진다). 칸: source_id | channel | session_id | 처음 | 끝 | 건수"
        tsdb "WITH s AS (SELECT source_id, channel, session_id, sequence_id FROM telemetry
                         WHERE received_at >= '$t0+00' AND sequence_id IS NOT NULL AND session_id IS NOT NULL),
                   b AS (SELECT source_id, channel, session_id, min(sequence_id) AS lo, max(sequence_id) AS hi FROM s
                         GROUP BY 1, 2, 3 HAVING count(DISTINCT sequence_id) > 1 AND max(sequence_id) - min(sequence_id) < 1000000),
                   m AS (SELECT b.source_id, b.channel, b.session_id, g AS seq FROM b, generate_series(b.lo, b.hi) AS g
                         EXCEPT SELECT source_id, channel, session_id, sequence_id FROM s)
              SELECT source_id, channel, session_id, min(seq), max(seq), count(*)
              FROM (SELECT m.*, seq - row_number() OVER (PARTITION BY source_id, channel, session_id ORDER BY seq) AS grp FROM m) t
              GROUP BY source_id, channel, session_id, grp ORDER BY 1, 2, 3, 4;"
        echo "(위가 비었으면 빠진 구간 없음)"
        echo
        echo "# 도착 순서 — Kafka 오프셋 순으로 순번이 거꾸로 간 수 · 같은 순번이 연달아 온 수. 칸: source_id | channel | session_id | 행 | 역전 | 연속 중복"
        tsdb "SELECT source_id, channel, coalesce(session_id, '-'), count(*), count(*) FILTER (WHERE d < 0), count(*) FILTER (WHERE d = 0)
              FROM (SELECT source_id, channel, session_id,
                           sequence_id - lag(sequence_id) OVER (PARTITION BY source_id, channel, session_id, stream_partition ORDER BY stream_offset) AS d
                    FROM telemetry WHERE received_at >= '$t0+00') t
              GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;"
    } > "$DIR/tsdb.txt" 2>&1

    tar -czf "$BASE/$name.tar.gz" -C "$BASE" "$name"
    echo "기록 끝: $DIR"
    echo "  T0 = $t0 UTC · T1 = $t1 UTC (KST $(kst))"
    echo "  서비스 로그 $(wc -l < "$DIR/journal.log")줄 · 이번 격리 $(wc -l < "$DIR/quarantine_new.jsonl")줄"
    echo "  가져올 묶음: $BASE/$name.tar.gz"
    md5sum "$BASE/$name.tar.gz"
}

[ $# -ge 2 ] || usage
command="$1"
name="$2"
shift 2
case "$name" in
    *[!A-Za-z0-9._-]*|'') echo "이름은 영문 · 숫자 · . _ - 만 쓴다: $name"; exit 2 ;;
esac
case "$command" in
    start)  cmd_start "$name" ;;
    mark)   cmd_mark "$name" "$@" ;;
    end)    cmd_end "$name" ;;
    status) cmd_status "$name" ;;
    *)      usage ;;
esac
