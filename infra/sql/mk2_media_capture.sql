-- =============================================================================
-- MK2 Phase 4 (4b) — 촬영본 저장소 메타 (media_capture) + 권한
--
-- implements: BE-S-09(미디어 저장 모드 — 촬영본 갈래, HW #15) · BE-C-02(식별자 계층)
-- 근거: docs/be/tasks/작업지시_phase4_미디어경로.md §5 단계 10-3·10-4
--       docs/be/02-media-path.md §1-3-4 · docs/be/hw-envelope-conformance.md §8-8
--
-- 적용: **사람이 MySQL root 로 1회.** 순서가 강제된다 — ① 이 파일의 DDL → ② 같은 파일 끝의 GRANT.
--       MySQL 은 없는 테이블에 테이블 단위 GRANT 를 걸 수 없고, GRANT 에는 테이블 와일드카드가 없어
--       mk2_app 이 새 테이블에 권한을 자동으로 얻지 못한다(제약 27).
--
--   ⚠ 서버 적용 경로는 infra/sql/ 이 아니라 /home/dg/capstone-db/mk2_sql/ 이다(제약 30 — 폴더 이름이 다르다).
--   ⚠ mk2_mysql_schema.sql 을 먼저 적용해 둔 서버에서만 돈다(DB mk2 · 계정 'mk2_app'@'172.18.%').
--
--   docker exec -i capstone_mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot' \
--       < /home/dg/capstone-db/mk2_sql/mk2_media_capture.sql
--
-- 이 파일은 커밋한다(비밀값이 없고, 다음 재구축의 재현 수단이다).
-- =============================================================================
--
-- mk2_mysql_schema.sql 의 규약 4가지를 그대로 따른다:
--   ① 시각은 UTC 를 담은 DATETIME(6). 기본값은 CURRENT_TIMESTAMP 가 아니라 UTC_TIMESTAMP(6)
--      (서버 time_zone=SYSTEM 이라 TIMESTAMP 타입은 세션 시간대 변환을 탄다 — 쓰지 않는다).
--   ② 테이블·칼럼 양쪽에 COLLATE utf8mb4_bin — 서버 기본(collation_server=utf8mb4_0900_ai_ci)과
--      다르므로 빠뜨리면 zoneA = zonea 가 되고 기존 테이블과 조인할 때 Illegal mix of collations.
--   ③ CREATE TABLE IF NOT EXISTS (재실행 가능. 칼럼 변경은 사람이 ALTER).
--   ④ FOREIGN KEY 를 걸지 않는다 — 레지스트리에 없는 source_id 의 촬영본도 그대로 남아야 한다.
--
-- 서버 sql_mode 실측(09-18)이 강제하는 것:
--   · STRICT_TRANS_TABLES — varchar 를 넘기면 잘리지 않고 INSERT 가 실패한다. 인덱스가 걸리는 칸은 128 이하,
--     archive_path 처럼 길이를 예측하기 어려운 칸은 넉넉히(512, 인덱스 없음).
--   · NO_ZERO_DATE — started_at 을 '0000-00-00' 으로 채울 수 없다 → 오프셋 없는 값은 NULL(10-2).
-- =============================================================================

USE mk2;

-- #############################################################################
-- 촬영본 세션 — 한 행 = 세션 하나 (session_id UNIQUE = 재전송 멱등)
-- #############################################################################
-- 기존 8개 중 성격이 맞는 것이 없다 — audit_log 는 승인·명령, mission_event 는 임무 사건.
-- 아카이브(tar.gz)는 파일시스템(MK2_CAPTURE_DIR/<source_id>/<세션>.tar.gz)에, 여기는 메타와
-- 매니페스트 원본(JSON 통째)만. **아카이브 안을 뒤지지 않는다** — 매니페스트를 먼저 별도 PUT 으로 받는다.
--
-- 보존(10-4): 용량 상한 초과분은 **아카이브만** 지우고 archive_path·archive_bytes 를 NULL, purged_at 을
-- 채운다. **행과 manifest 는 남는다** — 무엇이 있었는지는 계속 조회된다. mk2_app 에 DELETE 를 주지 않는다
-- (mission_event 「권한이 막는다」 규율에 첫 예외를 만들지 않기 위해 — VZ 회신 §2-3 동의 확정).
-- 이 상한은 촬영본 아카이브에만 적용되고 mission_event 무기한 보관 규약을 건드리지 않는다.
-- #############################################################################

CREATE TABLE IF NOT EXISTS media_capture (
  id              BIGINT        NOT NULL AUTO_INCREMENT                 COMMENT '서버 부여 순번',
  session_id      VARCHAR(128)  COLLATE utf8mb4_bin NOT NULL             COMMENT 'HW 매니페스트 session_id = "{entity_id}/{세션디렉터리명}". UNIQUE — 같은 세션 재전송은 멱등(1062 만 골라 잡는다)',
  source_id       VARCHAR(64)   COLLATE utf8mb4_bin NOT NULL             COMMENT '공통 헤더 source_id 와 같은 식별 체계(HW 는 entity_id 를 넣는다). 최종 경로 <루트>/<source_id>/ 의 첫 칸',
  node_id         VARCHAR(64)   COLLATE utf8mb4_bin NULL                 COMMENT '공통 헤더 node_id(발행 물리 노드). 매니페스트에 있다(capture_upload.py:73)',
  zone_id         VARCHAR(64)   COLLATE utf8mb4_bin NULL                 COMMENT '공통 헤더 zone_id',
  kind            VARCHAR(32)   COLLATE utf8mb4_bin NOT NULL             COMMENT '매니페스트 kind — capture_session | scan_capture_session … **보존한다**(ENUM 으로 박지 않는다)',
  started_at      DATETIME(6)   NULL                                     COMMENT 'UTC. frames.t0_unix(epoch) 우선. started_at 문자열은 오프셋이 있을 때만 — 없으면 NULL(서버가 시간대를 추측하지 않는다, NO_ZERO_DATE)',
  duration_s      DOUBLE        NULL                                     COMMENT '매니페스트 duration_s 그대로(fps·frames 둘 다 있을 때만 HW 가 채운다)',
  frames_count    INT           NULL                                     COMMENT 'capture_session 은 frames.count, 스캔 세션은 shots[] 길이',
  frames_bytes    BIGINT        NULL                                     COMMENT 'frames.bytes 또는 shots[].bytes 합',
  archive_path    VARCHAR(512)  COLLATE utf8mb4_bin NULL                 COMMENT '서버 파일시스템의 최종 경로. purge 되면 NULL',
  archive_bytes   BIGINT        NULL                                     COMMENT '수신하며 서버가 잰 크기(매니페스트에 없다). purge 되면 NULL',
  manifest        JSON          NOT NULL                                 COMMENT '매니페스트 원본 통째. 승격 전 미확정 칸(shots·motion·pose_track·labels·frame_ref_base)은 전부 여기',
  correlation_id  VARCHAR(128)  COLLATE utf8mb4_bin NULL                 COMMENT 'BE-X-01 명령 사슬 — HW 에 선택 칸으로 추가 요청. 없으면 NULL',
  received_at     DATETIME(6)   NOT NULL DEFAULT (UTC_TIMESTAMP(6))      COMMENT 'UTC. 서버가 아카이브 수신을 마친 시각. 보존 선정의 「오래된 순」 기준',
  purged_at       DATETIME(6)   NULL                                     COMMENT 'UTC. 아카이브를 보존 규칙으로 지운 시각. NULL 이면 파일이 있다',
  PRIMARY KEY (id),
  UNIQUE KEY uq_media_capture_session_id (session_id),
  KEY idx_media_capture_source (source_id, received_at),
  KEY idx_media_capture_received (received_at),
  KEY idx_media_capture_purged (purged_at, received_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
  COMMENT='촬영본 세션 메타(HW #15). 아카이브는 파일시스템, 여기는 한 행 + 매니페스트 원본. DELETE 를 권한으로 막는다(BE-S-09)';
-- frame_ref_base 칼럼을 두지 않는다 — 오프라인 촬영본은 엣지를 거치지 않아 발급 주체가 없다(원칙 10).
-- 다중 소스 병합(HW #14)은 정해지지 않았다 — 세션 1행·매니페스트 원본 보존으로 두고 병합 규칙이 오면 파생한다.


-- =============================================================================
-- 권한 — DDL 뒤에 (없는 테이블에는 GRANT 가 걸리지 않는다)
-- =============================================================================
-- mk2_app: SELECT, INSERT, UPDATE. **DELETE 없음.** UPDATE 는 보존 규칙(purged_at) 용이다.
-- 같은 줄을 mk2_grants_mysql.sql.example 에도 두었다(적용본 mk2_grants_mysql.sql 은 gitignore).
GRANT SELECT, INSERT, UPDATE ON mk2.media_capture TO 'mk2_app'@'172.18.%';


-- =============================================================================
-- 적용 확인 (root 로 실행)
-- =============================================================================
-- TABLE_COLLATION 이 utf8mb4_bin 이어야 하고, SHOW GRANTS 에 media_capture 행이 SELECT, INSERT, UPDATE 로
-- 보여야 한다(DELETE·CREATE·ALTER·DROP 이 보이면 안 된다).
SELECT TABLE_NAME, TABLE_COLLATION, TABLE_COMMENT
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'mk2' AND TABLE_NAME = 'media_capture';
SHOW GRANTS FOR 'mk2_app'@'172.18.%';
