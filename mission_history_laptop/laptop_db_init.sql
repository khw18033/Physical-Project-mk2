-- =============================================================================
-- 임무 이력 서버 — 노트북 WSL PostgreSQL 18: DB · 계정 · 표 · 권한 (261125)
-- 원격 서버에는 MK2 DB(mk2)와 프로그램 계정(mk2_app)이 이미 있었다. 노트북에는 없어서 이 파일이 만든다.
-- 표 · 권한은 원격 서버와 같은 schema_v2.sql 을 고치지 않고 그대로 읽어 들인다(\ir — 이 파일과 같은 폴더).
--
-- 적용(WSL 에서 사람이 · 관리자 postgres 로 · 한 번) — 묶음 자리에서 돌린다(postgres 는 /home/khw67 안을 읽지 못한다):
--   cd /mnt/c/mk2_edge/mission_history_laptop
--   sudo -u postgres psql -X -v ON_ERROR_STOP=1 -f laptop_db_init.sql
-- 다시 돌려도 된다 — 이미 있는 계정 · DB 는 그대로 두고 지나간다(표는 schema_v2.sql 의 IF NOT EXISTS).
--
-- 만드는 것:
--   계정 mk2_app — 임무 이력 프로그램이 쓴다. 비밀번호는 이 파일에 없다 → 다음에 사람이
--                  sudo -u postgres psql -X -c '\password mk2_app' 로 넣고, 같은 값을 mission-history.env 에 적는다.
--   계정 khw67   — 백업(backup.sh)이 쓴다. 비밀번호 없이 같은 기기 소켓으로만 붙는다(peer 인증 — WSL 사용자 khw67).
--                  두 표를 읽기(SELECT)만 한다 — 넣기 · 고치기 · 지우기 없음.
--   DB mk2       — 원격 서버와 같은 이름(나중에 L3 를 하면 계측 표가 같은 DB 에 들어간다). UTF8 로 만든다.
-- =============================================================================
\set ON_ERROR_STOP on
SET client_encoding = 'UTF8';

SELECT 'CREATE ROLE mk2_app LOGIN' WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mk2_app') \gexec
SELECT 'CREATE ROLE khw67 LOGIN'   WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'khw67') \gexec
SELECT $$CREATE DATABASE mk2 ENCODING 'UTF8' LOCALE 'C.UTF-8' TEMPLATE template0$$
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'mk2') \gexec

GRANT CONNECT ON DATABASE mk2 TO mk2_app, khw67;

\connect mk2

-- 표 두 개 + mk2_app 권한 + 확인 1 · 2 — 원격 서버와 같은 파일
\ir schema_v2.sql

-- 백업용 읽기 계정 — 두 표를 읽기만
GRANT SELECT ON mission_runs, mission_run_images TO khw67;

-- 확인 3 — 계정마다 권한: mk2_app = INSERT, SELECT, UPDATE · khw67 = SELECT
SELECT grantee, table_name, string_agg(privilege_type, ', ' ORDER BY privilege_type) AS privileges
FROM information_schema.role_table_grants
WHERE grantee IN ('mk2_app', 'khw67') AND table_name IN ('mission_runs', 'mission_run_images')
GROUP BY grantee, table_name
ORDER BY grantee, table_name;

-- 확인 4 — 계정: 둘 다 로그인 · 관리자 아님. mk2_app 비밀번호는 다음 단계에서 넣는다(처음엔 has_password = f)
SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, (rolpassword IS NOT NULL) AS has_password
FROM pg_authid WHERE rolname IN ('mk2_app', 'khw67') ORDER BY rolname;

-- 확인 5 — DB 글자 체계: mk2 가 UTF8
SELECT datname, pg_encoding_to_char(encoding) AS encoding, datcollate FROM pg_database WHERE datname = 'mk2';
