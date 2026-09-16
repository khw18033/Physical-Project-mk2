-- =============================================================================
-- MK2 Phase 2 — TimescaleDB 스키마 (계측 시계열)
--
-- implements: BE-S-01(시계열·상태 이력 저장) · BE-C-01(공통 헤더) · BE-C-07(원천 종류)
-- 근거: docs/be/tasks/작업지시_phase2_저장축.md §5 단계 2·5·6·9
--       docs/be/00-architecture.md §6-2(계측 = TSDB)
--
-- 적용: **사람이 postgres 계정으로 1회.** 앱 계정(mk2_app)에는 DDL 권한을 주지 않는다.
--       pg_hba 제한으로 postgres 는 TCP 로 붙지 못하므로 컨테이너 안 소켓으로 들어간다:
--
--   docker exec -i capstone_timescaledb psql -U postgres -d mk2 -v ON_ERROR_STOP=1 \
--       < mk2_tsdb_schema.sql
--
-- 이 파일은 커밋한다(비밀값 없음, 재구축의 재현 수단).
-- =============================================================================
--
-- ── 저장 원칙 ────────────────────────────────────────────────────────────────
-- 1. **원본 그대로 넣는다.** 칼럼은 인덱스를 위한 *추출*이지 원본 대체가 아니다.
--    원본 메시지 전체는 payload(JSONB)에 그대로 들어간다. 저장 시점에 없는 값을
--    채워 넣지 않는다 — 채우면 저장된 것이 원본이 아니게 된다(원칙 4).
--    없는 키를 규격대로 채워 돌려주는 것은 **읽기 함수**(backend/storage/normalize.py)의 몫이다.
-- 2. **시간축은 발행 시각(ts)이다.** 지연 도착 데이터가 원래 측정 시각 자리에 꽂혀야
--    한다(BE-S-01 원문 · message.schema.json). received_at 축으로는 이것이 원천적으로
--    불가능하다.
-- 3. **검출은 저장이 아니라 조회에서 한다.** 적재 시점에 "유실"을 판정하면 7분 뒤
--    도착해 갭을 메울 데이터와 정면 충돌한다. 그래서 원본만 넣고 갭은 조회 시
--    LAG() 윈도우 함수로 계산한다(docs/be/queries/gap-detection.sql).
-- 4. **TIMESTAMPTZ 는 내부적으로 항상 UTC 로 보관**된다. 표시만 세션 타임존을 탄다.
--    애플리케이션은 접속 시 SET TIME ZONE 'UTC' 를 명시한다(컨테이너 TZ 에 기대지 않는다).
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS timescaledb;


-- #############################################################################
-- telemetry — 계측 하이퍼테이블
-- #############################################################################

CREATE TABLE IF NOT EXISTS telemetry (
    -- ── 시간축 ───────────────────────────────────────────────────────────────
    ts                TIMESTAMPTZ       NOT NULL,
    -- ── 라우팅 좌표 ──────────────────────────────────────────────────────────
    channel           TEXT              NOT NULL,
    entity_type       TEXT,
    -- ── 공통 헤더 ────────────────────────────────────────────────────────────
    source_id         TEXT              NOT NULL,
    node_id           TEXT              NOT NULL,
    zone_id           TEXT              NOT NULL,
    entity_id         TEXT,
    session_id        TEXT,
    sequence_id       BIGINT,
    schema_version    TEXT              NOT NULL,
    origin_kind       TEXT,
    -- ── 시각 3종과 파생 ──────────────────────────────────────────────────────
    ingest_at         TIMESTAMPTZ,
    received_at       TIMESTAMPTZ,
    lag_s             DOUBLE PRECISION,
    clock_skew        BOOLEAN           NOT NULL DEFAULT false,
    replayed          BOOLEAN           NOT NULL DEFAULT false,
    -- ── 본문 공통 코어 ───────────────────────────────────────────────────────
    reason            TEXT,
    device_status     TEXT,
    -- ── 스트림 좌표 (유일 키) ────────────────────────────────────────────────
    stream_topic      TEXT              NOT NULL,
    stream_partition  INTEGER           NOT NULL,
    stream_offset     BIGINT            NOT NULL,
    -- ── 원본 ─────────────────────────────────────────────────────────────────
    payload           JSONB             NOT NULL
);

COMMENT ON TABLE  telemetry IS
    '계측 시계열 원본(BE-S-01). 칼럼은 인덱스용 추출이고 원본 메시지 전체는 payload 에 있다.';

COMMENT ON COLUMN telemetry.ts IS
    '공통 헤더 timestamp — 말단 노드가 찍은 발행 시각. **하이퍼테이블 시간축이자 정렬·조회·되감기의 기준.** '
    'HW 의 iso_now() 가 초 해상도라 로봇 20Hz 면 1초에 20건이 같은 값을 갖는다(F3) — 그래서 유일 키를 이 값에 의존시키지 않는다.';
COMMENT ON COLUMN telemetry.channel IS
    'state | status | heartbeat. Kafka 토픽 마지막 칸에서 얻는다(Phase 1 확정 규약 mk2.telemetry.<채널>).';
COMMENT ON COLUMN telemetry.entity_type IS
    'sensor | robot | actuator | analysis. **Kafka 헤더로 실려 온다** — Kafka 토픽은 채널만 담고 etype 을 담지 않아, '
    'MQTT 토픽 2번째 칸을 파싱할 수 있는 ingest 가 헤더에 넣어 보낸다. Phase 1 에 쌓인 옛 메시지는 NULL 이 정상.';
COMMENT ON COLUMN telemetry.source_id IS
    '메시지를 생산한 논리 개체(BE-C-02). Kafka 파티션 키이기도 하다.';
COMMENT ON COLUMN telemetry.entity_id IS
    '공통 헤더 선택 필드. **실노드는 보내지 않는다**(F9 — HW envelope() 에 이 필드가 없다). 가짜 발행자만 옵션으로 보낸다.';
COMMENT ON COLUMN telemetry.session_id IS
    '생산자 프로세스의 1회 기동 식별자(단계 3 신설). sequence_id 가 재기동 시 리셋되므로 순번 열의 경계를 이 값으로 가른다. '
    'HW 적용 전에는 NULL 이며, 그때는 status 의 birth 를 경계로 폴백한다.';
COMMENT ON COLUMN telemetry.sequence_id IS
    '생산자별 순번. **status 에는 없고(F4) 로봇 state 는 항상 0 이다(F1 — robot_node.py 에 self.seq += 1 이 없다).** '
    '그래서 유일 키로 쓰지 않는다.';
COMMENT ON COLUMN telemetry.origin_kind IS
    'real | simulation | replay (BE-C-07). **실노드는 보내지 않는다**(F9) — 미기재는 조회 시 real 로 해석한다.';
COMMENT ON COLUMN telemetry.ingest_at IS
    'ingest(bridge.py)가 MQTT 로 받은 순간. Kafka 헤더로 전달된다. 옛 메시지는 NULL.';
COMMENT ON COLUMN telemetry.received_at IS
    '**저장 소비자가 Kafka 에서 소비한 시각.** "서버 수신 시각"이 아니다(F2) — 재기동·오프셋 리셋마다 같은 메시지에 다른 값이 찍힌다.';
COMMENT ON COLUMN telemetry.lag_s IS
    'ingest_at - ts (초). 저장 시점에 계산해 칼럼으로 둔다 — 매 조회마다 빼지 않아도 되고, BE-S-07(재난 모드 지연 상한)의 측정 재료가 그대로 생긴다.';
COMMENT ON COLUMN telemetry.clock_skew IS
    'lag_s < 0. 말단 시계가 서버보다 앞선 경우. **버리지 않고 그대로 저장하되 플래그를 세운다** — '
    '버리면 재난 데이터가 사라지고, 조용히 보정하면 원본이 아니게 된다.';
COMMENT ON COLUMN telemetry.replayed IS
    '본문의 replayed 를 그대로 보관. **지연 도착 판정의 유일한 근거로 쓰지 않는다**(F13) — '
    'status·heartbeat 는 allow_spool=False 라 애초에 spool 을 타지 않아 지연돼도 이 표식이 없다. 판정은 lag_s 로 한다.';
COMMENT ON COLUMN telemetry.reason IS
    'state 본문의 reason. **replayed=true 구간의 reason="periodic" 은 다운샘플로 솎인 것이지 유실이 아니다**(F12) — '
    '이 구분이 없으면 정상 동작을 유실로 오판한다.';
COMMENT ON COLUMN telemetry.payload IS
    '원본 메시지 전체(공통 헤더 포함). JSONB 는 값을 정확히 보존하지만 키 순서는 잃는다 — 값 보존이 목적이므로 이 손실은 수용한다. '
    '바이트 단위 재현이 필요하다는 근거가 나오면 임의로 결정하지 말고 멈추고 물어본다(raw BYTEA 추가는 저장량이 배가 된다).';


-- ── 하이퍼테이블 전환 ────────────────────────────────────────────────────────
-- TimescaleDB 2.13 부터 by_range() 시그니처가 표준이고 옛 위치인자 형태는 폐기 예정이다.
-- 어느 판올림에서도 서게 새 형태를 먼저 시도하고, 없으면 옛 형태로 떨어진다.
-- chunk_time_interval 은 기본값(7일)을 쓴다 — 보존 기간·압축은 이번 범위가 아니다(BE-S-04).
DO $mk2$
BEGIN
    EXECUTE $q$ SELECT create_hypertable('telemetry', by_range('ts'), if_not_exists => TRUE) $q$;
    RAISE NOTICE '[mk2] create_hypertable: by_range() 시그니처로 생성';
EXCEPTION WHEN undefined_function THEN
    EXECUTE $q$ SELECT create_hypertable('telemetry', 'ts', if_not_exists => TRUE) $q$;
    RAISE NOTICE '[mk2] create_hypertable: 옛 위치인자 시그니처로 생성';
END
$mk2$;


-- ── 유일 키 — 스트림 좌표 ────────────────────────────────────────────────────
-- 막으려는 것은 **재소비 중복**이다. 저장 소비자는 auto.offset.reset=earliest +
-- enable.auto.commit=True 라 구조적으로 재소비한다(F14) — 유일 키가 없으면 재기동마다
-- 중복 행이 쌓인다.
--
-- 왜 업무 내용 키가 아니라 도착 좌표인가: 재소비는 **도착 계층의 현상**이므로 도착
-- 좌표로 잡는 것이 정확하다. sequence_id 에 의존하면 로봇(항상 0)·status(없음)·
-- analysis(전역 공유)가 전부 깨진다. 스트림 좌표는 생산자 결함과 무관하다.
--
-- ⚠ Timescale 제약: 하이퍼테이블의 UNIQUE 인덱스는 파티션 키(ts)를 반드시 포함해야
--    한다. 그래서 ts 가 맨 앞에 있다. 같은 메시지를 다시 읽으면 ts 도 같으므로 목적은
--    그대로 달성된다.
-- ⚠ 정직한 약점: Kafka 토픽을 지웠다 다시 만들면 오프셋이 0 부터 재시작해 옛 행과
--    충돌할 수 있다. 확률은 낮지만 기록해 둔다.
CREATE UNIQUE INDEX IF NOT EXISTS telemetry_stream_uq
    ON telemetry (ts, stream_topic, stream_partition, stream_offset);


-- ── 조회 인덱스 ──────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS telemetry_source_channel_ts_idx
    ON telemetry (source_id, channel, ts DESC);   -- 장치별 추이
CREATE INDEX IF NOT EXISTS telemetry_zone_ts_idx
    ON telemetry (zone_id, ts DESC);              -- 구역별 (VZ-N-02 의 조회 범위)
CREATE INDEX IF NOT EXISTS telemetry_channel_ts_idx
    ON telemetry (channel, ts DESC);


-- =============================================================================
-- 적용 확인 (postgres 로 실행)
-- =============================================================================
SELECT hypertable_schema, hypertable_name, num_dimensions
FROM timescaledb_information.hypertables
WHERE hypertable_name = 'telemetry';

SELECT indexname FROM pg_indexes WHERE tablename = 'telemetry' ORDER BY indexname;

SHOW timezone;
