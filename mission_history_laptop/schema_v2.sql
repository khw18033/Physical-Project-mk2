-- =============================================================================
-- 임무 이력 서버 — 표 두 개 + 권한  (v2 · 261119)
-- 명세 「임무이력서버_요청_VZ_261119.md」 §5 권장안 그대로. 그림은 사용자 결정(261119)대로
-- 바이트(bytes BYTEA) 대신 명세가 적어 둔 다른 길 「storage_path TEXT」 — 디스크에 두고 경로만 넣는다.
--
-- v1 과 다른 점 (v1 은 명세를 따르지 않았다):
--   mission_runs.record_kind   TEXT  → VARCHAR(16)   (명세대로)
--   mission_runs.mission_id    TEXT  → VARCHAR(90)   (명세대로)
--   mission_run_images.content_type  TEXT → VARCHAR(32)  (명세대로)
--   mission_run_images.storage_path  NOT NULL 을 뺐다  (명세의 bytes BYTEA 자리 — NOT NULL 이 없다)
--   mission_run_images.byte_size · created_at  뺐다     (명세에 없는 칸)
--
-- 이 파일은 표가 없는 DB 에 처음 만들 때 쓴다.
-- 지금 서버처럼 v1 표가 이미 있으면 이 파일이 아니라 schema_v1_to_v2.sql 을 돌린다
-- (IF NOT EXISTS 때문에 이 파일은 v1 표를 그대로 두고 지나간다).
--
-- 적용(서버에서 사람이, postgres 로 컨테이너 안에서):
--   docker exec -i capstone_timescaledb psql -U postgres -d mk2 -v ON_ERROR_STOP=1 < schema_v2.sql
-- =============================================================================

SET client_encoding = 'UTF8';

-- 판 하나 = 한 줄. mission_doc 이 NULL 이면 목록(GET /api/v1/runs)에 안 나온다.
CREATE TABLE IF NOT EXISTS mission_runs (
  date          CHAR(6)      NOT NULL,          -- '261021'
  run           VARCHAR(90)  NOT NULL,          -- '102025_MSN-260909-01'
  mission_doc   JSONB,                          -- mission.json 전체 (view 포함). NULL 이면 목록에 안 나옴
  progress_doc  JSONB,                          -- progress.json 전체
  -- 색인용으로 mission_doc 에서 꺼낸 칸
  record_kind   VARCHAR(16)  GENERATED ALWAYS AS (COALESCE(mission_doc->>'recordKind', 'mission')) STORED,
  mission_id    VARCHAR(90)  GENERATED ALWAYS AS (mission_doc->>'missionId') STORED,
  created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
  PRIMARY KEY (date, run)
);

-- 그림 = 한 줄. 파일은 디스크(그림 폴더/<date>/<run>/<kind>/<name>), 여기는 그림 폴더 기준 상대 경로.
CREATE TABLE IF NOT EXISTS mission_run_images (
  date          CHAR(6)      NOT NULL,
  run           VARCHAR(90)  NOT NULL,
  kind          VARCHAR(8)   NOT NULL,          -- 'detect' | 'robot'
  name          VARCHAR(130) NOT NULL,
  content_type  VARCHAR(32)  NOT NULL,
  storage_path  TEXT,                           -- 명세의 「bytes BYTEA (또는 storage_path TEXT)」
  updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
  PRIMARY KEY (date, run, kind, name)
);

-- 프로그램 계정(mk2_app) — 읽기 · 넣기 · 덮어쓰기. 지우기(DELETE)는 주지 않는다(사용자 결정 (가)).
GRANT SELECT, INSERT, UPDATE ON mission_runs, mission_run_images TO mk2_app;

-- 확인 1 — 칸 이름 · 형이 명세 §5 와 같아야 한다.
SELECT table_name, column_name, data_type, character_maximum_length AS len, is_nullable, is_generated
FROM information_schema.columns
WHERE table_name IN ('mission_runs', 'mission_run_images')
ORDER BY table_name, ordinal_position;

-- 확인 2 — mk2_app 권한이 표마다 INSERT, SELECT, UPDATE 셋이어야 한다.
SELECT table_name, string_agg(privilege_type, ', ' ORDER BY privilege_type) AS mk2_app_privileges
FROM information_schema.role_table_grants
WHERE grantee = 'mk2_app' AND table_name IN ('mission_runs', 'mission_run_images')
GROUP BY table_name
ORDER BY table_name;
