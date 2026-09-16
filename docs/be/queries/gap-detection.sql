-- =============================================================================
-- 유실·역전 검출 조회 (TimescaleDB)
--
-- implements: BE-S-01 (유실·역전 검출), BE-C-01 (sequence_id 의미)
-- 근거: docs/be/tasks/작업지시_phase2_저장축.md §5 단계 9 · 완료 판정 27~30
-- =============================================================================
--
-- ## Phase 2가 만든 것은 "검출 로직"이 아니라 "검출이 가능한 저장"이다
--
-- **적재 시점에 유실을 판정하지 않는다.** 7분 뒤에 도착해 갭을 메울 데이터를 두고 미리
-- "유실"이라고 못 박을 수 없기 때문이다(실측: `lag_s = 420.527`인 메시지가 원래 시각
-- 자리에 꽂혔다). 그래서 원본만 넣고 **갭은 조회 시 `LAG()` 윈도우 함수로 계산**한다.
-- TimescaleDB를 고른 이유 중 하나가 이 질의다.
--
-- 같은 이유로 적재 시 상태를 들고 있는 칼럼(`seq_epoch` 같은)을 두지 않는다 — 무상태
-- 원칙과 충돌하고, 재기동하면 그 상태가 소실된다.
--
-- ## 검출 단위: (source_id, channel, session_id)
--
-- - **채널마다 순번이 독립이다.** 카운터가 물리적으로 둘이다(`BaseNode.seq` / `hb_seq`).
--   소스별로 합치면 매 메시지가 갭으로 잡힌다.
-- - **`session_id`가 구간의 경계다.** `sequence_id`는 프로세스가 다시 뜨면 리셋된다.
-- - **`session_id`가 없으면 `status`의 `birth`를 경계로 폴백한다.** 하드웨어가 아직
--   `session_id`를 보내지 않는 혼재 기간의 경로다. `_on_connect`가 항상
--   `publish_status("birth")`를 부르므로 신뢰할 수 있는 표식이다.
-- - **보조 안전망:** 순번이 크게 감소했는데 경계 표식이 없으면 **경보만 남기고 새 구간으로
--   본다**(`seq_reset_without_boundary`). 갭으로 세지 않는다.
--
-- ## 실행
--
--   docker exec -i capstone_timescaledb psql -U postgres -d mk2 < gap-detection.sql
--
-- 특정 대상만 보려면 세션 설정으로 좁힌다(기본은 전체):
--
--   SET mk2.source_filter = 'wl-%';
--
-- =============================================================================


-- @@QUERY: gap_scan
-- 갭·정체·역전을 찾아 채널별 의미로 분류한다. `verdict = 'ok'`인 행은 제외한다.
WITH params AS (
    -- 세션 설정으로 대상을 좁힌다. 안 주면 전체(`%`). `true`는 "없어도 오류 내지 말라"는 뜻.
    SELECT COALESCE(NULLIF(current_setting('mk2.source_filter', true), ''), '%') AS source_filter
),
births AS (
    -- `session_id` 폴백용 경계. `status`의 `birth`만 센다.
    -- ⚠ `status`는 순번이 없어 검출 대상이 아니지만, **경계 표식으로는 쓰인다.**
    SELECT t.source_id, t.ts
    FROM telemetry t, params p
    WHERE t.channel = 'status'
      AND t.source_id LIKE p.source_filter
      AND t.payload ->> 'event' = 'birth'
),
detectable AS (
    SELECT t.ts, t.source_id, t.channel, t.entity_type, t.session_id, t.sequence_id,
           t.reason, t.replayed, t.stream_offset
    FROM telemetry t, params p
    WHERE t.source_id LIKE p.source_filter
      -- 순번이 없으면 애초에 셀 것이 없다.
      AND t.sequence_id IS NOT NULL
      -- ⚠ `status` 제외: 순번이 아예 없다(`envelope(identity)`를 순번 없이 호출).
      --    위 sequence_id IS NOT NULL 로도 대부분 걸러지지만, 옛 메시지 중에는 state 본문을
      --    status 채널로 보낸 것이 있어 순번이 붙어 있다. 채널로 명시적으로 제외한다.
      AND t.channel <> 'status'
      -- ⚠ 증강 분석 제외: 순번이 **모듈 전역**이라 모든 대상에 걸쳐 공유된다. 대상별로 보면
      --    구멍이 뚫린 것처럼 보이는데 그것은 유실이 아니라 생산자 구조다.
      AND NOT (t.channel = 'state' AND t.entity_type = 'analysis')
),
segmented AS (
    SELECT d.*,
           COALESCE(
               d.session_id,
               -- 폴백: 이 메시지 시각 이전의 birth 개수가 곧 구간 번호다.
               'birth#' || (
                   SELECT COUNT(*) FROM births b
                   WHERE b.source_id = d.source_id AND b.ts <= d.ts
               )::text
           ) AS session_key
    FROM detectable d
),
scanned AS (
    SELECT s.*,
           LAG(s.sequence_id) OVER w AS prev_sequence_id,
           LAG(s.ts)          OVER w AS prev_ts
    FROM segmented s
    -- ⚠ 정렬은 **시각 순**이다(순번 순이 아니다). 순번으로 정렬하면 리셋된 순번이 옛 값과
    --    섞여 정렬돼 역전이 보이지 않는다. `timestamp`가 초 해상도라 같은 값이 여럿이므로
    --    도착 좌표(stream_offset)로 동률을 깬다.
    WINDOW w AS (
        PARTITION BY s.source_id, s.channel, s.session_key
        ORDER BY s.ts, s.stream_offset
    )
),
classified AS (
    SELECT sc.*,
           sc.sequence_id - sc.prev_sequence_id AS delta,
           CASE
               WHEN sc.prev_sequence_id IS NULL THEN 'segment_start'
               WHEN sc.sequence_id - sc.prev_sequence_id = 1 THEN 'ok'
               -- 순번이 안 움직였다. 로봇 `state`가 항상 0인 결함이거나(HW `robot_node.py`에
               -- `self.seq += 1`이 없다) 같은 메시지의 재전송이다. **유실이 아니다.**
               WHEN sc.sequence_id - sc.prev_sequence_id = 0 THEN 'seq_stalled'
               -- 경계 표식 없이 순번이 줄었다. 보조 안전망 — **경보만 남기고 새 구간으로 본다.**
               WHEN sc.sequence_id - sc.prev_sequence_id < 0 THEN 'seq_reset_without_boundary'
               ELSE 'gap'
           END AS verdict
    FROM scanned sc
)
SELECT
    c.source_id,
    c.channel,
    c.entity_type,
    c.session_key,
    c.prev_sequence_id,
    c.sequence_id,
    c.delta,
    GREATEST(COALESCE(c.delta, 1) - 1, 0) AS missing_count,
    c.prev_ts,
    c.ts,
    c.reason,
    c.replayed,
    c.verdict,
    -- ── 채널별 의미 차등 — **갭이 곧 유실이 아니다** ────────────────────────
    CASE
        WHEN c.verdict <> 'gap' THEN NULL
        -- 하트비트: QoS 0 이고 `allow_spool=False`라 두절 중 버퍼에도 안 쌓인다. 게다가
        -- **로봇은 임무 중 하트비트를 아예 끈다**(상태 20Hz가 겸한다). 침묵을 장애로
        -- 단정하면 임무 중인 로봇이 전부 장애로 보고된다.
        WHEN c.channel = 'heartbeat' THEN 'loss_not_implied'
        -- 로봇 `state`: QoS 0 이라 유실이 설계된 동작이다(다음 표본이 50ms 뒤 온다).
        WHEN c.channel = 'state' AND c.entity_type = 'robot' THEN 'loss_not_implied'
        -- 센서·액추에이터 `state`: QoS 1 + spool 을 타므로 갭이 비정상이다.
        ELSE 'loss_candidate'
    END AS loss_class,
    -- ⚠ `loss_candidate` 라도 곧장 유실로 확정하지 않는다. 아래 두 질의로 대조한다:
    --   ① replayed 구간의 reason='periodic' 은 **다운샘플로 솎인 것**이지 유실이 아니다
    --   ② status 의 buffer.dropped 가 늘어난 구간이면 원인이 네트워크가 아니라 버퍼 고갈이다
    CASE
        WHEN c.replayed AND c.reason = 'periodic' THEN '재전송 구간의 연속 표본 — 다운샘플 가능성'
        ELSE NULL
    END AS note
FROM classified c
WHERE c.verdict <> 'ok'
ORDER BY c.source_id, c.channel, c.session_key, c.ts, c.sequence_id;


-- @@QUERY: buffer_cross_check
-- 갭의 **원인**을 가른다. `status`의 `buffer.dropped`는 노드가 spool 상한 초과로 **스스로
-- 버린 건수**다. 이 값이 늘어난 구간의 갭은 진짜 손실이지만 원인이 네트워크가 아니라 버퍼
-- 고갈이다. `thinned`는 다운샘플로 솎은 것이라 **유실이 아니다** — 둘을 구분해서 본다.
SELECT
    t.source_id,
    t.ts,
    (t.payload -> 'buffer' ->> 'pending')::bigint AS buffer_pending,
    (t.payload -> 'buffer' ->> 'dropped')::bigint AS buffer_dropped,
    (t.payload -> 'buffer' ->> 'thinned')::bigint AS buffer_thinned,
    (t.payload ->> 'publish_failures')::bigint    AS publish_failures,
    t.payload ->> 'event'                         AS event
FROM telemetry t, (
    SELECT COALESCE(NULLIF(current_setting('mk2.source_filter', true), ''), '%') AS source_filter
) p
WHERE t.channel = 'status'
  AND t.source_id LIKE p.source_filter
  AND t.payload -> 'buffer' IS NOT NULL
ORDER BY t.source_id, t.ts;


-- @@QUERY: excluded_summary
-- **무엇이 검출 대상에서 빠졌고 왜인지**를 보여 준다. 제외가 조용히 일어나면 "갭이 0건"이
-- 좋은 소식인지 검출이 안 도는 것인지 알 수 없다.
SELECT
    CASE
        WHEN t.channel = 'status' THEN 'status — 순번이 없다(검출 제외)'
        WHEN t.channel = 'state' AND t.entity_type = 'analysis'
            THEN 'analysis — 순번이 대상 간 공유(검출 제외)'
        WHEN t.sequence_id IS NULL THEN '순번 없음(검출 불가)'
        WHEN t.channel = 'heartbeat' THEN 'heartbeat — 검출은 하되 유실로 단정 안 함'
        WHEN t.channel = 'state' AND t.entity_type = 'robot'
            THEN 'robot state — 검출은 하되 유실로 단정 안 함(QoS 0)'
        ELSE 'state(sensor/actuator) — 갭이 유실 후보'
    END AS detection_scope,
    COUNT(*) AS rows,
    COUNT(DISTINCT t.source_id) AS sources
FROM telemetry t, (
    SELECT COALESCE(NULLIF(current_setting('mk2.source_filter', true), ''), '%') AS source_filter
) p
WHERE t.source_id LIKE p.source_filter
GROUP BY 1
ORDER BY 1;


-- @@QUERY: segment_overview
-- 구간(세션) 단위 요약. `session_key`가 `birth#N` 이면 폴백 경로로 잡힌 구간이고,
-- 그 밖이면 생산자가 보낸 `session_id` 다 — **혼재 기간에 어느 경로로 잡혔는지**가 보인다.
WITH params AS (
    SELECT COALESCE(NULLIF(current_setting('mk2.source_filter', true), ''), '%') AS source_filter
),
births AS (
    SELECT t.source_id, t.ts FROM telemetry t, params p
    WHERE t.channel = 'status' AND t.source_id LIKE p.source_filter
      AND t.payload ->> 'event' = 'birth'
),
segmented AS (
    SELECT t.source_id, t.channel, t.sequence_id, t.ts,
           COALESCE(
               t.session_id,
               'birth#' || (SELECT COUNT(*) FROM births b
                            WHERE b.source_id = t.source_id AND b.ts <= t.ts)::text
           ) AS session_key,
           (t.session_id IS NOT NULL) AS from_session_id
    FROM telemetry t, params p
    WHERE t.source_id LIKE p.source_filter
      AND t.sequence_id IS NOT NULL
      AND t.channel <> 'status'
      AND NOT (t.channel = 'state' AND t.entity_type = 'analysis')
)
SELECT source_id, channel, session_key,
       BOOL_OR(from_session_id) AS boundary_from_session_id,
       COUNT(*)                 AS rows,
       MIN(sequence_id)         AS min_seq,
       MAX(sequence_id)         AS max_seq,
       MIN(ts)                  AS first_ts,
       MAX(ts)                  AS last_ts
FROM segmented
GROUP BY source_id, channel, session_key
ORDER BY source_id, channel, first_ts;
