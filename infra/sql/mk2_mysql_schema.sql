-- =============================================================================
-- MK2 Phase 2 — MySQL 스키마 (레지스트리 · 감사 · 임무 실행 기록)
--
-- implements: BE-Q-03(레지스트리 조회) · BE-C-02(식별자 계층) · BE-S-05(감사 중앙 저장)
--             BE-S-08(임무 실행 추적 기록) · BE-C-07(원천 종류 표기)
-- 근거: docs/be/tasks/작업지시_phase2_저장축.md §5 단계 2·7·8
--       docs/be/00-architecture.md §6-2(저장소 분리 — 성격이 다르면 테이블을 나눈다)
--
-- 적용: **사람이 MySQL root 로 1회.** 앱 계정(mk2_app)에는 DDL 권한을 주지 않는다 —
--       코드가 스키마를 바꿀 수 없어야 한다(작업지시 제약 14).
--
--   docker exec -i capstone_mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD"' \
--       < mk2_mysql_schema.sql
--
-- 이 파일은 커밋한다(비밀값이 없고, 다음 재구축의 재현 수단이다).
-- =============================================================================
--
-- ── 규약 1. 시각은 전부 UTC 를 담은 DATETIME(6) 이다 ─────────────────────────
--    MySQL 의 TIMESTAMP 타입은 **세션 타임존으로 자동 변환**돼 클라이언트마다 다르게
--    읽힌다. 이 서버는 system_tz=KST 라 특히 위험하다. 그래서 TIMESTAMP 를 쓰지 않고
--    DATETIME(6) 에 UTC 값을 넣는다(결정 3-D). 표시 시각 변환은 조회하는 쪽의 몫이다.
--    기본값에 CURRENT_TIMESTAMP 를 쓰지 않는 이유도 같다 — 그것은 세션 타임존을 탄다.
--    대신 타임존과 무관한 UTC_TIMESTAMP(6) 를 쓴다.
--    백엔드는 접속 시 SET time_zone='+00:00' 을 명시한다(컨테이너 TZ 에 기대지 않는다).
--
-- ── 규약 2. 식별자 칼럼은 대소문자를 구별한다(utf8mb4_bin) ───────────────────
--    DB 기본 collation 은 utf8mb4_0900_ai_ci 지만, **MK2 테이블은 utf8mb4_bin 을
--    기본으로 둔다.** 이유는 계측 저장소(TimescaleDB)의 TEXT 가 대소문자를 구별하기
--    때문이다. 한쪽은 zoneA == zonea 로 보고 다른 쪽은 다르게 보면, 두 저장소를 잇는
--    조회(Phase 5/6 조회 프록시)에서 같은 대상이 다르게 취급된다.
--    사람이 읽는 자유 문자열(display_name·note)만 명시적으로 ai_ci 로 되돌린다.
--    ⚠ **이 스키마에 테이블을 추가할 때도 반드시 COLLATE=utf8mb4_bin 을 붙인다.**
--      빠뜨리면 DB 기본(ai_ci)이 적용돼 기존 칼럼과 조인할 때
--      "Illegal mix of collations" 로 터진다.
--
-- ── 규약 3. 이 파일은 재실행 가능해야 한다(CREATE ... IF NOT EXISTS) ─────────
--    다만 IF NOT EXISTS 는 "이미 있으면 건드리지 않는다"이지 "맞춰 준다"가 아니다.
--    칼럼을 바꿔야 하면 사람이 ALTER 를 따로 수행한다.
--
-- ── 규약 4. FOREIGN KEY 를 일절 걸지 않는다 ─────────────────────────────────
--    이 스키마에는 FK 가 **하나도 없다. 의도한 것이다.** 이유가 테이블마다 조금씩 다르다:
--
--    (1) 선언 축 내부(registry_zone.parent_zone_id, *_declared.zone_id/node_id)
--        — 트리·소속을 위에서부터 넣어야 하는 순서 제약이 생기고, 구역 개편 중
--          일시적으로 부모가 없는 상태를 표현할 수 없게 된다.
--    (2) 관측 축 → 선언 축 (observed.entity_id → declared.entity_id)
--        — **선언되지 않은 개체가 값을 보내오는 것이 정상 상황**이다(새 노드가 붙었는데
--          아직 대장에 안 넣은 경우). FK 를 걸면 그 메시지가 저장 자체를 못 한다.
--          "존재해야 할 것"과 "실제로 온 것"의 차이를 보는 것이 이 두 축의 목적인데,
--          FK 는 그 차이를 없애 버린다.
--    (3) 사건 열 → 레지스트리 (mission_event/audit_log.target_entity_id)
--        — append-only 원장이 **대장의 현재 상태에 묶이면 안 된다.** 지금 대장에 없는
--          대상에 대한 과거 사건도 그대로 남아야 한다(그것이 기록의 목적이다).
--
--    **무결성은 조회 층에서 본다** — LEFT JOIN 으로 "선언만 있는 것 / 관측만 있는 것"을
--    가려내는 것이 오히려 요구사항이다(docs/be/queries/registry-declared-vs-observed.sql).
--    ⚠ 테이블을 추가할 때도 FK 를 걸지 않는다. 걸어야 할 근거가 생기면 이 규약부터 고친다.
-- =============================================================================

CREATE DATABASE IF NOT EXISTS mk2
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

USE mk2;


-- #############################################################################
-- 1. 레지스트리 — 선언 축 (사람이 넣는다)
-- #############################################################################
-- BE-Q-03·VZ-I-03 이 "**존재해야 할** Entity 목록 ... 값을 발행하지 않는 **미배포
-- 대상도 이 목록으로 화면에 표시**"를 요구한다. 텔레메트리에서 자동으로 채우면
-- 미배포 대상이 영원히 나타나지 않는다. 그래서 선언 축이 따로 있다.
-- HW 의 registration() 이 주는 8개에는 원점 배치·Zone 트리·표시 이름이 **없다** —
-- 그것들이 여기 있는 값이다.
-- #############################################################################

CREATE TABLE IF NOT EXISTS registry_zone (
  zone_id         VARCHAR(64)   NOT NULL                                   COMMENT '구역 식별자(공통 헤더 zone_id)',
  parent_zone_id  VARCHAR(64)   NULL                                       COMMENT '상위 구역. NULL 이면 최상위. Zone 트리(BE-C-02)',
  display_name    VARCHAR(255)  COLLATE utf8mb4_0900_ai_ci NULL            COMMENT '화면 표시 이름(사람이 읽는 문자열)',
  created_at      DATETIME(6)   NOT NULL DEFAULT (UTC_TIMESTAMP(6))        COMMENT 'UTC',
  updated_at      DATETIME(6)   NOT NULL DEFAULT (UTC_TIMESTAMP(6))        COMMENT 'UTC. 갱신 시 애플리케이션이 명시적으로 넣는다',
  PRIMARY KEY (zone_id),
  KEY idx_zone_parent (parent_zone_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
  COMMENT='레지스트리 선언 축 — 구역 트리. 사람이 넣는다(BE-Q-03)';
-- parent_zone_id 에 자기참조 FK 를 걸지 않는다 — 규약 4 의 (1). 트리를 위에서부터 넣어야
-- 하는 제약이 생기고, 구역 개편 중 일시적으로 부모가 없는 상태를 표현할 수 없게 된다.


CREATE TABLE IF NOT EXISTS registry_entity_declared (
  entity_id       VARCHAR(64)   NOT NULL                                   COMMENT '논리 개체 식별자. 관측 축의 registry_entity_observed.entity_id 와 같은 축',
  zone_id         VARCHAR(64)   NOT NULL                                   COMMENT '소속 구역',
  entity_type     VARCHAR(32)   NOT NULL                                   COMMENT 'sensor|robot|actuator|analysis (MQTT 토픽 2번째 칸 어휘). 새 타입이 늘 수 있어 ENUM 으로 박지 않는다',
  node_id         VARCHAR(128)  NULL                                       COMMENT '배치될 물리 노드. 미배포면 NULL',
  display_name    VARCHAR(255)  COLLATE utf8mb4_0900_ai_ci NULL            COMMENT '화면 표시 이름',
  alias           JSON          NULL                                       COMMENT '별칭 목록(VZ-I-03 "표시 이름·별칭"). 예: ["수위계1","상류센서"]',
  deployed        TINYINT(1)    NOT NULL DEFAULT 0                         COMMENT '1=배포됨, 0=미배포. **0 이어도 목록에 나와야 한다** — 이 칼럼이 BE-Q-03 의 핵심',
  note            TEXT          COLLATE utf8mb4_0900_ai_ci NULL            COMMENT '운영 메모(사람이 읽는 문자열)',
  created_at      DATETIME(6)   NOT NULL DEFAULT (UTC_TIMESTAMP(6))        COMMENT 'UTC',
  updated_at      DATETIME(6)   NOT NULL DEFAULT (UTC_TIMESTAMP(6))        COMMENT 'UTC',
  PRIMARY KEY (entity_id),
  KEY idx_entity_declared_zone (zone_id),
  KEY idx_entity_declared_node (node_id),
  KEY idx_entity_declared_deployed (deployed)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
  COMMENT='레지스트리 선언 축 — 존재해야 할 개체 목록. 미배포 대상 포함(BE-Q-03·VZ-I-03)';


CREATE TABLE IF NOT EXISTS registry_node_declared (
  node_id         VARCHAR(128)  NOT NULL                                   COMMENT '물리 실행 노드 식별자(공통 헤더 node_id). hostname 폴백이 있어 넉넉히 잡는다',
  zone_id         VARCHAR(64)   NOT NULL                                   COMMENT '소속 구역',
  display_name    VARCHAR(255)  COLLATE utf8mb4_0900_ai_ci NULL            COMMENT '화면 표시 이름',
  origin          JSON          NULL                                       COMMENT '노드 원점의 전역 배치(BE-Q-03 "Node 원점의 전역 배치").',
  created_at      DATETIME(6)   NOT NULL DEFAULT (UTC_TIMESTAMP(6))        COMMENT 'UTC',
  updated_at      DATETIME(6)   NOT NULL DEFAULT (UTC_TIMESTAMP(6))        COMMENT 'UTC',
  PRIMARY KEY (node_id),
  KEY idx_node_declared_zone (zone_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
  COMMENT='레지스트리 선언 축 — 물리 노드와 원점 배치. 사람이 넣는다';
-- origin 을 x/y/z 칼럼이 아니라 JSON 으로 두는 이유: 좌표계 규약(BE-C-04)이 Phase 7
-- 연동으로 미확정이다. 지금 칼럼을 박으면 좌표 표현을 미리 고정하게 된다. 확정 후 승격한다.


-- #############################################################################
-- 2. 레지스트리 — 관측 축 (텔레메트리가 채운다)
-- #############################################################################
-- 저장 소비자가 channel=="status" 이고 본문에 registration 이 있을 때만 갱신한다.
-- 쓰기 경로는 backend/storage/writer.py 의 RegistryWriter.observe(record).
-- #############################################################################

CREATE TABLE IF NOT EXISTS registry_entity_observed (
  entity_id         VARCHAR(64)   NOT NULL                                 COMMENT '⚠ 값의 출처는 **공통 헤더의 source_id** 다. 선언 축의 entity_id 와 같은 축이라 이 이름을 쓴다 — 봉투의 선택 필드 entity_id 가 아니다(실노드는 그 필드를 보내지 않는다, F9)',
  entity_type       VARCHAR(32)   NULL                                     COMMENT 'registration.entity_type. 없으면 NULL',
  device_type       VARCHAR(64)   NULL                                     COMMENT 'registration.device_type (예: water_level)',
  node_id           VARCHAR(128)  NULL                                     COMMENT '공통 헤더 node_id',
  zone_id           VARCHAR(64)   NULL                                     COMMENT '공통 헤더 zone_id',
  schema_version    VARCHAR(16)   NULL                                     COMMENT '혼재 기간에 1.0/1.1 을 가른다',
  last_session_id   VARCHAR(64)   NULL                                     COMMENT '마지막으로 본 session_id. HW 적용 전에는 NULL(단계 3)',
  first_seen        DATETIME(6)   NOT NULL                                 COMMENT 'UTC. 처음 관측한 메시지의 공통 헤더 timestamp',
  last_seen         DATETIME(6)   NOT NULL                                 COMMENT 'UTC. 마지막 관측 메시지의 공통 헤더 timestamp. **시각 가드의 기준** — 이 값보다 이후일 때만 갱신한다',
  last_event        VARCHAR(32)   NULL                                     COMMENT 'birth|summary|rebirth|shutdown|death',
  last_recorded_at  DATETIME(6)   NOT NULL DEFAULT (UTC_TIMESTAMP(6))      COMMENT 'UTC. 백엔드가 이 행을 쓴 시각(발행 시각과 구분)',
  PRIMARY KEY (entity_id),
  KEY idx_entity_observed_zone (zone_id),
  KEY idx_entity_observed_node (node_id),
  KEY idx_entity_observed_last_seen (last_seen)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
  COMMENT='레지스트리 관측 축 — 실제로 값을 보내온 개체. status.registration 으로 채운다';
-- ⚠ 시각 가드(작업지시 단계 7): status 는 retained 라 구독 즉시 마지막 1건이 밀려오고,
--   저장 소비자는 auto.offset.reset=earliest 라 재기동 시 옛 status 를 다시 읽는다.
--   게다가 status 에는 sequence_id 가 없어(F4) 순번으로 신구를 가릴 수 없다.
--   그래서 last_seen 보다 **이후일 때만** 갱신한다. 없으면 재기동마다 대장이 과거로 돌아간다.


CREATE TABLE IF NOT EXISTS registry_node_observed (
  node_id           VARCHAR(128)  NOT NULL                                 COMMENT '공통 헤더 node_id',
  fw_version        VARCHAR(32)   NULL                                     COMMENT 'registration.fw_version',
  mac               VARCHAR(32)   NULL                                     COMMENT 'registration.mac. **빈 문자열이면 갱신하지 않는다**(F7 — analyzer 형식이 빈 값을 보낸다)',
  ip                VARCHAR(45)   NULL                                     COMMENT 'registration.ip. IPv6 최대 길이 기준 45. 빈 문자열이면 갱신하지 않는다',
  last_seen         DATETIME(6)   NOT NULL                                 COMMENT 'UTC. 공통 헤더 timestamp. 시각 가드 기준',
  last_recorded_at  DATETIME(6)   NOT NULL DEFAULT (UTC_TIMESTAMP(6))      COMMENT 'UTC. 백엔드가 쓴 시각',
  PRIMARY KEY (node_id),
  KEY idx_node_observed_last_seen (last_seen)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
  COMMENT='레지스트리 관측 축 — 물리 노드의 도달성 정보(MAC·IP는 정체성이 아니라 도달 정보다, BE-C-02)';


CREATE TABLE IF NOT EXISTS registry_identity_history (
  id              BIGINT        NOT NULL AUTO_INCREMENT,
  entity_id       VARCHAR(64)   NOT NULL                                   COMMENT '대상 개체(공통 헤더 source_id)',
  changed_at      DATETIME(6)   NOT NULL                                   COMMENT 'UTC. 변경을 관측한 메시지의 공통 헤더 timestamp',
  recorded_at     DATETIME(6)   NOT NULL DEFAULT (UTC_TIMESTAMP(6))        COMMENT 'UTC. 백엔드가 쓴 시각',
  zone_id         VARCHAR(64)   NULL                                       COMMENT '변경 **후** 값',
  node_id         VARCHAR(128)  NULL                                       COMMENT '변경 후 값',
  mac             VARCHAR(32)   NULL                                       COMMENT '변경 후 값',
  ip              VARCHAR(45)   NULL                                       COMMENT '변경 후 값',
  fw_version      VARCHAR(32)   NULL                                       COMMENT '변경 후 값',
  change_reason   VARCHAR(64)   NULL                                       COMMENT '무엇이 바뀌어 기록했는지. 구현이 실제로 쓰는 값: first_seen(처음 본 개체 — 비교 대상이 없어 초기 상태를 남긴다) / zone_changed / ip_changed / mac_changed',
  PRIMARY KEY (id),
  KEY idx_identity_history_entity (entity_id, changed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
  COMMENT='레지스트리 관측 축 — 신원 변경 이력(append). (zone_id, mac, ip) 가 이전과 다를 때만 1행 추가';
-- ⚠ 이력 기록 조건이 (zone_id, mac, ip) 인 이유: **HW 의 Identity.fingerprint() 와 같은
--   조합**이다(_hwsrc/upstream_260909/pi/common/schema.py). 생산자의 재등록 판정 기준과
--   저장의 이력 기준이 어긋나지 않게 한다.
-- ⚠ **처음 보는 개체에도 1행을 남긴다**(change_reason='first_seen'). 지시서는 "다를 때만"
--   이었으나 처음에는 비교 대상이 없다. 초기 상태를 남겨야 **이력만으로 임의 시점의 신원을
--   복원**할 수 있다. 같은 값을 다시 보내면 늘어나지 않으므로 "변경 시 1행" 판정은 그대로다.


-- #############################################################################
-- 3. 감사 (audit_log) — Phase 2 는 스키마만. 쓰기 경로는 Phase 6
-- #############################################################################
-- 원칙 5: 감사는 요약하지 않는다. 요약·필터를 전제한 구조를 만들지 않는다.
-- actor 는 토큰에서, 시각은 서버 시각으로 백엔드가 주입한다(위조 불가).
-- 명령 이력(감사)과 기술 추적(Tempo)은 목적이 달라 섞지 않는다.
-- #############################################################################

CREATE TABLE IF NOT EXISTS audit_log (
  id                BIGINT        NOT NULL AUTO_INCREMENT,
  occurred_at       DATETIME(6)   NOT NULL                                 COMMENT 'UTC. 사건이 일어난 시각. **백엔드가 서버 시각으로 주입**한다(원칙 5)',
  recorded_at       DATETIME(6)   NOT NULL DEFAULT (UTC_TIMESTAMP(6))      COMMENT 'UTC. 원장에 기록된 시각',
  subject_kind      VARCHAR(32)   NOT NULL                                 COMMENT 'command | plan | model — **대상 일반화**. ENUM 으로 박지 않는다(어휘가 늘 수 있다)',
  subject_id        VARCHAR(128)  NOT NULL                                 COMMENT 'command_id | plan_id | 모델 버전',
  action            VARCHAR(64)   NULL                                     COMMENT '무엇을 했나(예: actuate, approve_model)',
  target_entity_id  VARCHAR(64)   NULL                                     COMMENT '조작 대상 개체',
  zone_id           VARCHAR(64)   NULL                                     COMMENT '대상 구역(권한 범위의 기준, BE-Q-04)',
  actor_kind        VARCHAR(32)   NULL                                     COMMENT '조작 주체의 종류. Phase 6 에서 토큰으로 채운다. ⚠ 어휘가 mission_event.actor_kind(ai|backend|human) 와 아직 다르다 — 아래 주 참조',
  actor_id          VARCHAR(128)  NULL                                     COMMENT '조작 주체. **토큰에서 주입**(클라이언트가 보낸 값을 믿지 않는다)',
  origin_kind       VARCHAR(16)   NULL                                     COMMENT 'real | simulation | replay (BE-C-07·VZ-C-06). 실물 조작과 시뮬 조작을 구분',
  result            VARCHAR(32)   NULL                                     COMMENT '최종 결과(성공/실패). **중간 진행 단계는 저장하지 않는다**(원칙 4)',
  failure_code      VARCHAR(64)   NULL                                     COMMENT '실패 사유 코드',
  correlation_id    VARCHAR(128)  NULL                                     COMMENT '명령 사슬 상관키(BE-X-01). 백엔드가 발급',
  origin_path       VARCHAR(255)  NULL                                     COMMENT '요청이 들어온 경로(화면·API 등)',
  detail            JSON          NULL                                     COMMENT '위 칼럼으로 표현되지 않는 나머지 전부',
  record_version    VARCHAR(16)   NULL                                     COMMENT '나중에 칼럼이 늘 때 옛 행을 구분',
  PRIMARY KEY (id),
  KEY idx_audit_subject (subject_kind, subject_id),
  KEY idx_audit_occurred (occurred_at),
  KEY idx_audit_target (target_entity_id, occurred_at),
  KEY idx_audit_actor (actor_id, occurred_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
  COMMENT='감사 원장 — 누가·언제·무엇을·어떤 결과로. UPDATE·DELETE 는 권한으로 막는다(BE-S-05)';
-- **왜 subject_kind 로 일반화했나.** AI-L-06 이 "백엔드는 승인 주체·시간·대상 버전과
-- 적용 범위의 authoritative 기록을 담당한다", AI-L-08 이 "기존 백엔드 저장·감사 인프라와
-- 연결한다", VZ-U-08 이 "임무 계획 승인과 별개 화면 — 승인 대상이 모델·정책·지식"을
-- 요구한다. 성격은 감사와 같다(누가·언제·무엇을·어떤 결과로).
-- command_id 전용으로 좁게 만들면 나중에 넣을 자리가 없고, 지금은 칼럼 하나 비용이면 끝난다.
-- ⚠ 이 요구에 대응하는 BE-* 요구사항이 **없다** — requirement-traceability.md 에 gap 으로 기록.
--
-- ⚠ **actor_kind 어휘가 mission_event 와 갈려 있다(2026-09-14 발견, 통일은 Phase 6).**
--     mission_event.actor_kind : ai | backend | human   (VZ-D-02 "산출 주체(AI·백엔드·사람)" 원문)
--     audit_log.actor_kind     : user | system | ai …   (이 테이블의 초안 어휘)
--   user↔human, system↔backend 로 **같은 개념을 다르게 부른다.** 되감기 화면에서 임무 사건과
--   감사를 겹쳐 보면 같은 주체가 다르게 표기된다. 이쪽은 쓰기가 Phase 6(토큰 주입)이라
--   **그때 하나로 맞춘다** — 지금 바꾸면 mission_event 쪽 VZ 회신(§1-2 ②)보다 앞서게 된다.
--   NOT NULL 로 조이는 것도 그때다(actor 는 토큰에서 오므로 인증이 선행조건이다).


-- #############################################################################
-- 4. 임무 실행 기록 (mission_event) — 스키마 + append 경로만
-- #############################################################################
-- 감사와 같은 사건이지만 **조회 패턴이 다르다** — 감사는 대상·기간·조작자로 검색하고,
-- 실행 기록은 시점을 지정해 그 시점 상태를 복원한다(되감기). 그래서 테이블을 나눈다.
--
-- ⚠ "계층·노드"를 물리 축으로 읽으면 안 된다. VZ-D-06 "노드 상태를 대기·진행·완료·
--    실패·건너뜀·평가 대기·미수행·재실행 8종", VZ-D-05 "실패한 노드에서 의존·파생 관계를
--    역방향으로" 가 전부 **DAG 노드**를 가리킨다. 물리 대상은 target_entity_id 하나로
--    충분하고 나머지는 레지스트리 조인으로 얻는다.
-- #############################################################################

CREATE TABLE IF NOT EXISTS mission_event (
  seq               BIGINT        NOT NULL AUTO_INCREMENT                  COMMENT 'VZ-D-02 순번. **서버가 부여하는 단조 증가** — 같은 시각의 사건 순서가 확정된다. 공통 헤더의 sequence_id(생산자 순번)와 다른 것이라 이름을 분리했다',
  occurred_at       DATETIME(6)   NOT NULL                                 COMMENT 'UTC. VZ-D-02 시각',
  recorded_at       DATETIME(6)   NOT NULL DEFAULT (UTC_TIMESTAMP(6))      COMMENT 'UTC. 기록된 시각',
  layer             VARCHAR(16)   NOT NULL                                 COMMENT 'VZ-D-02 계층 = milestone | task | action_item (VZ-D-01 의 3계층)',
  node_ref          VARCHAR(128)  NOT NULL                                 COMMENT 'VZ-D-02 노드 = 그 계층의 **DAG 노드** 식별자',
  parent_ref        VARCHAR(128)  NULL                                     COMMENT 'VZ-D-01 "파생 출처를 유지" · VZ-D-05 "파생 관계를 역방향으로 따라가"',
  attempt           INT           NOT NULL DEFAULT 1                       COMMENT 'VZ-D-06 "재실행은 회차를 함께 표시" · VZ-D-08 "회차를 누적"',
  event_type        VARCHAR(64)   NOT NULL                                 COMMENT 'VZ-D-02 사건 종류. **ENUM 으로 박지 않는다** — 실패 단계 어휘가 미확정(VZ-D-05)',
  actor_kind        VARCHAR(32)   NOT NULL                                 COMMENT 'VZ-D-02 "산출 주체(AI·백엔드·사람)를 반드시 포함" — 그래서 NOT NULL. 어휘(ai|backend|human)는 VZ 회신 전이라 ENUM 으로 박지 않는다',
  actor_id          VARCHAR(128)  NULL                                     COMMENT 'VZ-D-02 산출 주체의 개별 식별자. 종류(actor_kind)만 필수이고 개별 식별자는 비워도 된다',
  mission_id        VARCHAR(128)  NULL                                     COMMENT 'VZ-D-04 "지난 임무를 이력에서 선택"',
  target_entity_id  VARCHAR(64)   NULL                                     COMMENT 'VZ-D-07 "레지스트리의 대상 목록을 마일스톤에 배정" · VZ-N-02 "태스크의 대상 장비·구역이 조회 범위"',
  origin_kind       VARCHAR(16)   NULL                                     COMMENT 'VZ-C-06 실물/시뮬 구분',
  correlation_id    VARCHAR(128)  NULL                                     COMMENT 'BE-X-01 명령 사슬. 이번엔 빈 채로 둔다',
  event_key         VARCHAR(255)  NULL                                     COMMENT '재삽입 멱등 키. **MySQL UNIQUE 는 NULL 을 여럿 허용**하므로 키 없는 사건은 그냥 들어간다 — 생산자가 Phase 6 에 붙을 때 이 울타리와 충돌하지 않는다. utf8mb4 기준 1020바이트라 InnoDB DYNAMIC 인덱스 상한(3072) 안',
  detail            JSON          NULL                                     COMMENT 'VZ-D-02 상세. 미확정분은 전부 여기 — 확정되면 칼럼으로 승격한다',
  record_version    VARCHAR(16)   NULL                                     COMMENT '나중에 칼럼이 늘 때 옛 행을 구분',
  PRIMARY KEY (seq),
  UNIQUE KEY uq_mission_event_key (event_key),
  KEY idx_mission_event_mission (mission_id, seq),
  KEY idx_mission_event_occurred (occurred_at),
  KEY idx_mission_event_node (layer, node_ref, seq),
  KEY idx_mission_event_target (target_entity_id, occurred_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
  COMMENT='임무 실행 기록 — append-only 사건 열. UPDATE·DELETE 를 권한으로 막는다(BE-S-08)';
-- **파티셔닝을 넣지 않는다.** 보존 기간이 미확정이라 파티션 경계를 정할 근거가 없다.
-- **UPDATE·DELETE 는 코드 규율이 아니라 DB 권한이 막는다**(mk2_grants_mysql.sql).
--   "수정·삭제하지 않으며"(BE-S-08)를 코드가 지키기로 하면 언젠가 누군가 깬다.
-- ⚠ 2026-09-14 정정: actor_kind 는 처음(2026-09-10) NULL 로 만들었다가 재검수에서 VZ-D-02
--   "반드시 포함" 과 어긋난다고 잡혀 NOT NULL 로 바꿨다. 이미 만들어진 서버 테이블은
--   CREATE TABLE IF NOT EXISTS 로는 바뀌지 않으므로 root 가 아래를 따로 적용했다:
--     ALTER TABLE mission_event MODIFY actor_kind VARCHAR(32) NOT NULL COMMENT '...';
--   (MODIFY 는 칼럼을 통째로 다시 정의하므로 COMMENT 를 같이 적어야 지워지지 않는다.)


-- =============================================================================
-- 적용 확인 (root 로 실행)
-- =============================================================================
SELECT TABLE_NAME, TABLE_COLLATION, TABLE_COMMENT
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'mk2'
ORDER BY TABLE_NAME;
