-- =============================================================================
-- 레지스트리 조회 — 선언 축과 관측 축을 겹쳐 본다
--
-- implements: BE-Q-03(구성 조회), BE-C-02(식별자 계층)
-- 근거: docs/be/tasks/작업지시_phase2_저장축.md §5 단계 7 · 완료 판정 23
--
-- 적용: 조회만 한다. `mk2_app` 계정으로도 돌고, 관리자 계정으로도 돈다.
--   docker exec -i capstone_mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" mk2' \
--       < registry-declared-vs-observed.sql
--
-- ⚠ **이 파일은 Phase 2의 산출물이지 조회 API가 아니다.** 조회 API(BE-Q-03의 나머지 절반)와
--    capability 등록(AI-C-18)은 Phase 5/6이다. 여기 있는 것은 "저장이 조회를 가능하게
--    하는가"를 확인하는 질의다.
--
-- `-- @@QUERY: <이름>` 표기는 pytest 가 절 하나를 꺼내 그대로 돌리기 위한 것이다
-- (`tests/conftest.py` 의 `sql_query` fixture). **테스트가 SQL 을 다시 적지 않는다** —
-- 두 벌이 되면 문서와 동작이 조용히 갈린다. `gap-detection.sql` 과 같은 규약이다.
-- =============================================================================

USE mk2;

-- ── 1) 존재해야 할 개체 전체 — **미배포·미관측 대상 포함** ──────────────────
--
-- **이것이 BE-Q-03의 핵심이다.** VZ-I-03이 *"값을 발행하지 않는 미배포 대상도 이 목록으로
-- 화면에 표시"* 를 요구한다. 텔레메트리에서 자동으로 대장을 채우면 **아직 배포되지 않은
-- 대상은 영원히 화면에 나타나지 않는다** — 값을 보낸 적이 없으니까.
--
-- 그래서 기준(FROM)이 **선언 축**이고 관측 축을 LEFT JOIN 으로 얹는다. 반대로 짜면
-- (관측을 기준으로 선언을 붙이면) 미배포 대상이 결과에서 사라진다.

-- @@QUERY: declared_with_observed
-- 선언 축 전체 + 관측 여부. 선언된 개체는 관측이 없어도 한 행씩 반드시 나온다.
SELECT
    d.entity_id,
    d.zone_id,
    d.entity_type,
    d.display_name,
    d.deployed                              AS declared_deployed,   -- 0이어도 목록에 나온다
    (o.entity_id IS NOT NULL)               AS observed,            -- 값을 보내온 적이 있는가
    o.last_seen,
    o.last_event,
    o.node_id                               AS observed_node_id,
    CASE
        WHEN o.entity_id IS NULL AND d.deployed = 0 THEN '미배포(정상)'
        WHEN o.entity_id IS NULL AND d.deployed = 1 THEN '배포됐다는데 값이 없다'
        ELSE '관측됨'
    END                                     AS status_note
FROM registry_entity_declared d
LEFT JOIN registry_entity_observed o ON o.entity_id = d.entity_id
ORDER BY d.zone_id, d.entity_id;


-- ── 2) 관측됐는데 선언에 없는 것 — 대장 누락 탐지 ──────────────────────────
--
-- 값을 보내오는데 "존재해야 할 목록"에 없는 개체다. 채번 사고이거나 대장 갱신 누락이다.
-- 1)의 반대 방향이며, 둘을 같이 봐야 대장과 현실의 차이가 양쪽으로 드러난다.

-- @@QUERY: observed_not_declared
-- 관측됐는데 선언에 없는 개체. 1)에 나오지 않는 것들이 여기 나온다(방향이 반대다).
SELECT
    o.entity_id,
    o.zone_id,
    o.entity_type,
    o.node_id,
    o.first_seen,
    o.last_seen,
    o.last_event
FROM registry_entity_observed o
LEFT JOIN registry_entity_declared d ON d.entity_id = o.entity_id
WHERE d.entity_id IS NULL
ORDER BY o.last_seen DESC;


-- ── 3) 노드 도달 정보와 신원 이력 ──────────────────────────────────────────
--
-- MAC·IP 는 **도달성 정보이지 개체 정체성이 아니다**(BE-C-02). 정체성은 논리 식별자
-- (entity_id·node_id·zone_id)이고, 이 표는 "지금 어디로 가면 닿는가"를 답한다.

-- @@QUERY: node_reachability
-- 노드별 도달 정보와 그 노드에 붙어 있는 개체 수.
SELECT n.node_id, n.fw_version, n.mac, n.ip, n.last_seen,
       COUNT(DISTINCT o.entity_id) AS entities_on_node
FROM registry_node_observed n
LEFT JOIN registry_entity_observed o ON o.node_id = n.node_id
GROUP BY n.node_id, n.fw_version, n.mac, n.ip, n.last_seen
ORDER BY n.last_seen DESC;

-- 신원이 바뀐 내력. `(zone_id, mac, ip)` 가 이전과 다를 때만 1행 쌓인다
-- (하드웨어 `Identity.fingerprint()` 와 같은 조합).

-- @@QUERY: identity_history
-- 신원 변경 이력 전량(append). 같은 값을 다시 보내면 행이 늘지 않는다.
SELECT id, entity_id, changed_at, zone_id, node_id, mac, ip, fw_version, change_reason
FROM registry_identity_history
ORDER BY entity_id, changed_at, id;


-- =============================================================================
-- 부록 — 선언 축 넣기 (예시)
--
-- **선언 축은 사람이 넣는다.** `mk2_app` 에는 SELECT 권한만 있어서 앱이 이 줄을 쓸 수 없다.
-- 아래는 완료 판정 23을 확인할 때 쓴 예시이며, 실제 배포 목록은 운영자가 채운다.
-- =============================================================================
-- INSERT INTO registry_zone (zone_id, parent_zone_id, display_name)
-- VALUES ('zoneA', NULL, '상류 감시구역');
--
-- -- 실제로 값을 보내는 개체
-- INSERT INTO registry_entity_declared
--     (entity_id, zone_id, entity_type, node_id, display_name, deployed, note)
-- VALUES ('wl-001', 'zoneA', 'sensor', 'pi7', '수위계 1호', 1, NULL);
--
-- -- ★ 아직 배포되지 않아 **값을 보낸 적이 없는** 개체. 이것이 조회에 나와야 한다.
-- INSERT INTO registry_entity_declared
--     (entity_id, zone_id, entity_type, node_id, display_name, deployed, note)
-- VALUES ('wl-002', 'zoneA', 'sensor', NULL, '수위계 2호(미설치)', 0, '2026-10 설치 예정');
