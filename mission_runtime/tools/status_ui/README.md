# 기능 상태 패널 (검토용)

프레임워크가 지금 계산하는 것을 눈으로 확인하는 **로컬 검토 도구**다. 운영 UI가
아니다 — 운영 UI는 가시화 파트 담당이고(AI-C-19,
`capability·상태 UI 연동 설계 노트(비공개)` §3-4), 이 패널은 payload
모양을 확인하는 용도까지만이다. 표준 라이브러리만 쓰고 외부 자원(CDN·폰트)을 전혀
불러오지 않으므로 폐쇄망에서도 뜬다.

## 축: 장치가 아니라 기능·자원·계층

장치는 provider 하나일 뿐이다. 화면의 기준은 다음 세 가지다.

1. **지금 어떤 기능이 가능한가** — `config`의 `functions[]`(required/optional
   capability kind)를 `contracts/capability_contract.py::TaskIntent.evaluate_availability()`로
   판정한다. 입력은 "어느 노드든 ACTIVE/DEGRADED로 제공 중인 kind의 집합"이다.
2. **그 기능에 어떤 자원이 필요한가** — 제공 kind마다 한 번씩, 선택된 provider의
   cost를 **계층(role)별**로 합산한다. kind를 여러 노드가 제공하면 priority 숫자가
   가장 낮은 provider, 같으면 비용이 가장 낮은 것, 그다음 설정 순서(규칙은
   `serve.py::StatusService.fleet/functions` docstring).
3. **장치의 계층(role)** — `nodes[].role`(`fixed_camera` / `ugv` / `uav` / `edge` / `server` …). 자유
   문자열이며 enum이 아니다: 새 계층은 새 문자열 + 라벨 한 줄. 노드 이름은 상세 행에서만
   흐리게 보인다.

불가/일부만 가능한 기능에는 **최소 보충(supplement)**이 붙는다: 빠진 필수 kind마다
계층별로 "왜 그 계층이 제공하지 못하는지"(예: `엣지: 필요한 장비/가속기 태그가 없음
(compute.gpu)`). 사유는 노드의 집계 사유보다 **가장 우선순위 높은 대안 후보의 탈락
사유**를 우선한다 — 더 실행 가능한 힌트이기 때문이다.

| 항목 | 출처 |
|---|---|
| 기능별 가능/일부/불가 + 필수·선택 kind별 제공 노드/계층 + 계층별 자원 + 최소 보충 | `TaskIntent.evaluate_availability()` over `ZoneApplication.resolve()` (모든 노드) |
| 노드별 capability 상태 + 선택된 provider + 사유 + **대안 후보와 탈락 사유** (P1) | `runtime/application.py::ZoneApplication.resolve()` → `CapabilityResolution.alternatives` |
| 사유 통제 어휘 (P2) | `contracts/data_dictionary.py::STATE_CHANGE_REASONS` |
| JSON manifest에서 읽은 provider 등록 (P3) | `registry/manifest.py::load_provider_manifest` |
| 배치 액션·`nodeSelector` (P4) | `runtime/placement.py::PlacementReconciler`, `node_selector_for` |
| **온디바이스 상주** — 등록된 장치 하나가 어떤 기능을 자기 안에 두는가와 그 사유 | `runtime/residency.py::decide_residency` over `contracts/profile.py::DevicePurposeProfile` + 그 장치의 링크 특성 |
| 배치 축 사유 통제 어휘 | `contracts/data_dictionary.py::RESIDENCY_DECISION_REASONS`, `LINK_POSTURE_REASONS`, `RESIDENCY_VIOLATIONS`, `OUTAGE_BEHAVIOR_VALUES` |
| **단독 수행 가능 계층 / 조합** (`solo_roles`, `combo_roles`) | `served_by`의 role 집합 위에서 `serve.py::solo_and_combo_roles` (규칙은 아래) |
| **실패 추적** (`trace[]`) — 기능 → 빠진 kind → 계층 사유 → 후보 provider → 빠진 태그 | `supplement`와 같은 사유 선택 + `required_hw_tag_missing:<a,b>` 데이터를 쉼표로 분리 |
| **freshness** — "마지막 검증 n초 전 / 미검증" | `contracts/capability_contract.py::RuntimeInstance.health_checked_at` ← `tools/hw_smoke` 보고서(최신 1개) + 이 프로세스가 직접 잰 장치 probe |
| **실행 계획** (`plan_id`) — 배치 요청 1건의 resolve + 액션 묶음 | `runtime/execution_plan.py::build_plan` / `ExecutionPlanLog` (인메모리, 마지막 N개) |

**단독/조합 규칙** (`serve.py::StatusService.functions` docstring이 원본):
`roles_by_kind[kind]` = 그 kind를 ACTIVE/DEGRADED로 제공하는 노드가 하나라도 있는
계층(설정 순서). `solo_roles` = 필수 kind **전부**를 혼자 제공하는 계층. `combo_roles`
= 탐욕적 최소 덮개 — 아직 못 채운 필수 kind를 가장 많이 채우는 계층을 고르고(동점은
설정 순서) 다 채울 때까지 반복; 어떤 계층도 제공하지 않는 필수 kind가 있으면 덮개가
불가능하므로 `[]`(왜인지는 `trace`가 말한다). 단독 계층은 자동으로 자기 자신이
조합이다. 필수 kind가 없는 기능은 모든 계층이 단독(공허하게 참).

"표시 등급(파생)" READY/DEGRADED/MISSING/STALE/BLOCKED는 (CapabilityState, 사유
토큰)에서 이 도구가 파생한 값이고 프레임워크 상태가 아니다(§3-2). 장치 가용성은
건드리지 않는다(원칙 #15).

## 화면 (탭 4개 + KO | EN)

- 헤더의 **`KO | EN`** 버튼이 언어를 즉시 바꾼다(재조회 없음, 라벨 파일에서 다시
  그림). 선택은 `localStorage`에 남기며(실패해도 무시) 기본은 ko. 모든 문자열은
  `config/status_ui.labels.json`의 `t(key)` 조회이고 라벨이 없는 id는 원문 id 그대로
  보인다. **API 응답에는 라벨이 없다** — id만 싣는다(신원·권한·대상별 필터링은 이
  도구 범위 밖이며 그 위에 얹을 수 있게 응답은 additive로 유지한다).
- **기능** (기본 탭): 설정의 `functions[]` 전부(하드웨어 설정이면 15개 — 문 시연 4개 +
  임무 M1~M11) 카드 — 라벨, 평문 상태 칩(`가능 / 일부만 가능 / 불가`, 색 + 글자),
  `미검증 장비 포함` 배지(배정된 노드가 `verified:false`이거나 검증 기록이 없을 때),
  한 줄 설명, **단독 수행 가능 계층 / 조합** 한 줄, 불가·일부면 "왜" **첫 줄
  하나**(supplement; 나머지는 `+n`). kind 이름 옆에는 라벨 파일 `aliases.capability_kinds`의
  `C-xx` 코드가 작게 붙는다(있을 때만). 클릭 → 상세 서랍: 단독/조합 + 규칙, 필수·선택
  kind 행(계층 + provider_id, 노드는 흐리게), 계층별 자원, 최소 보충 목록, 그리고
  **실패 추적** — `기능 → 빠진 kind → 계층: 사유 토큰(+데이터) → 가장 가까운 후보
  provider → 고치려면: <태그> @ <계층>` 한 경로. 전부 `/api/functions`의 `trace[]`
  데이터이고 화면은 재계산하지 않는다. What-if 중이면 카드에 `이전 → 이후` 칩.
- **계층·자원**: 계층(role)별 섹션 — 제공 중인 kind, 그 계층의 노드(이름 작게 +
  freshness 칩 `마지막 검증 n초 전` / `미검증`, `verified:false`면 `미확정 장비` 배지):
  태그 핀(체크 = what-if 토글), 예산, provider 제외, 이 노드가 제공 중인 kind,
  배치(`배치 적용` + 액션/바인딩/감사 로그). 변경은 `/api/functions/whatif`를 부르고
  기능 탭이 이전→이후를 보여준다. 이벤트 패널도 여기.
- **실행**: 왼쪽 `/api/plans` 목록(시각, plan_id, 기능, 노드/계층, 제공/미제공 수,
  수락/거부 수, 요청자, 상관 id) → 오른쪽 상세: kind → provider(또는 사유) →
  노드/계층 → 배치 액션(명령 + 수락/거부 사유) 트리(HTML 리스트, 캔버스 없음).
  아래 **재선택 트레이스**: `/api/events`의 `capability_state_changed`·`placement_applied`를
  kind별로 시간순 "이전 → 이후 (사유)". `배치 적용`마다 계획이 하나 늘고 `초기화`가 비운다.
- **개발자**: 예전 노드별 표 그대로 — CapabilityState, 파생 등급, provider, 사유
  토큰(원문 id, mono) + 번역, 대안 표, cost/priority/nodeSelector, vocabulary,
  라벨 누락 id. 그리고 **온디바이스 상주** 패널: 선택한 장치의 목적·링크 자세와
  사유, kind별 `말단 상주 / 엣지 제공` 배지와 배치 사유, 엣지 행에는 그것을
  담당하는 엣지 서비스와 **단절 시 동작**, 상주 행에는 기존 resolve 결과.
  `링크 저하 what-if` 버튼이 같은 목적·같은 장치를 나쁜 링크로 다시 판정한다
  (목적을 선언하지 않은 노드에서는 그 사실만 한 줄로 표시된다).

## 실행

```bash
cd mission_runtime
python tools/status_ui/serve.py --config config/status_ui.example.json
# → status_ui: http://127.0.0.1:8765/  control=local

# 온디바이스 상주 축까지 보려면 장치 목적이 선언된 설정으로 띄운다
python tools/status_ui/serve.py --config config/status_ui.ondevice.example.json
```

옵션: `--host 127.0.0.1` `--port 8765`(0이면 빈 포트를 골라 출력) `--control local|k3s`
`--namespace default` `--verbose`(access log).

## 엔드포인트

전부 JSON(UTF-8, `Cache-Control: no-store`). 모르는 경로는 404 JSON. 응답은 언어 중립(id만).

```bash
B=http://127.0.0.1:8765
curl -s $B/api/labels                       # 라벨 파일 그대로 (languages/ui/capability_kinds/functions/states/grades/reasons/roles/commands)
curl -s $B/api/functions                    # 기능 축: functions[] {state, derived_grade, required[], optional[], resources, supplement[]} + served + nodes
curl -s $B/api/fleet                        # 모든 노드 resolve + served{kind: [{node_id, role, provider_id, priority, cost, ...}]}
curl -s -X POST $B/api/functions/whatif -H 'content-type: application/json' \
  -d '{"overrides":{"edge-gpu":{"tags":["compute.cpu","tier.edge"]},"*":{"exclude_providers":["unidepth"]}}}'
                                            # before + after + diff[] {function_id, before_state, after_state, changed}
curl -s $B/api/config                       # 노드(role 포함)·roles·functions·capability spec·provider·태그 합집합·control·labels_missing
curl -s $B/api/vocabulary                   # state_change_reasons / grades / capability_states / link_postures / residency_reasons / outage_behaviors
curl -s "$B/api/resolve?node_id=pi6"        # 기준선 resolve (rows[].alternatives, priority, required_hw_tags 포함)
curl -s -X POST $B/api/whatif -H 'content-type: application/json' \
  -d '{"node_id":"pi6","tags":["compute.cpu","compute.gpu"],"budget":{"compute_units":6},"exclude_providers":["unidepth"]}'
                                            # 노드 하나: baseline + override + diff[]
curl -s -X POST $B/api/placement -H 'content-type: application/json' \
  -d '{"node_id":"edge-gpu"}'               # reconciler.apply → actions[] + state + plan_id (실행 계획 1건 기록)
curl -s -X POST $B/api/placement -H 'content-type: application/json' \
  -d '{"node_id":"edge-gpu","function_id":"door_detection","requester":{"role":"operator","id":"jny"},"correlation_id":"corr-1"}'
                                            # 같은 배치 + 계획 봉투의 식별 자리(function_id 기본 "*", requester는 모양만 검사·값은 불투명)
curl -s "$B/api/placement?node_id=edge-gpu" # 바인딩된 provider + nodeSelector + audit_log 꼬리
curl -s "$B/api/plans?limit=20"             # 실행 계획 요약, 최신순: {count, capacity, plans[]{plan_id, correlation_id, function_id, node_id, node_role, created_at, requester, served_kinds, unserved_kinds, actions, accepted, rejected}}
curl -s "$B/api/plans?correlation_id=corr-1"  # 한 상관 id의 계획들
curl -s $B/api/plans/plan-091edb812665      # ExecutionPlan.as_dict() 전체 + node_role + 액션 집계 (모르는 id는 404)
curl -s "$B/api/residency?node_id=drone-1"  # 그 장치의 상주 결정: purpose + link(자세·사유) + rows[] + outage + violations
curl -s -X POST $B/api/residency/whatif -H 'content-type: application/json' \
  -d '{"node_id":"go1-onboard","link":{"source":"whatif","quality":0.2,"stability":0.4,"samples":10}}'
                                            # "링크가 나빠지면": baseline + override + diff[] {kind, before_placement, after_placement}
curl -s $B/api/events                       # placement_applied / control_fallback / reset 이벤트
curl -s $B/api/dashboard                    # 종합상황정보 Dashboard 구역 B~I 한 장 (아래)
curl -s "$B/api/dashboard?pin=n2"           # 기준 노드 수동 고정 (pin= 빈 값이면 자동 추종으로 복귀)
curl -s -X POST $B/api/reset                # reconciler·이벤트·control 상태 초기화
```

### 종합상황정보 Dashboard 구역 B~I (`/api/dashboard`)

`internal/docs-dev/20260928-종합상황정보_Dashboard_기능정의서_2.docx` 의 구역 B~I 를
**한 스냅샷**으로 낸다(A 글로벌 내비게이션은 문서가 정의 범위 외로 둔다).
구역별로 따로 조회하면 문서 §3 "통합된 상태 뷰를 구독"과 §5 "같은 사실이 여러 구역에
나타나도 값이 상충하지 않는다"를 동시에 지킬 수 없다 — 그래서 한 번에 조립한다
(AI-O-06).

| 응답 칸 | 구역 | 무엇 |
|---|---|---|
| `mission` + `derived.task_node_counts_by_state` + `derived.accelerator_placement` | B | 미션 원문·상태·경과, 상태별 노드 수, 가속기→서비스 배치(미할당 포함) |
| `task_nodes` + `reference_edges` | C | 노드 6상태, `order_after`(실선)/`depends_on`(점선), `parallel_group`, `task_attempt` |
| `events` | D | 시각·`event_severity`·`event_kind`(SDI 분리)·`task_node_id`·메시지 |
| `accelerators` / `services` / `board` | E | L1 과 L2 를 **다른 목록**으로. 서비스마다 `accelerator_instance_id` 병기 |
| `services[].indicators` | E′ | 현재값·목표 기준선·`target_meet_state` 3값·추이 |
| `focus` + `task_nodes[]` | F | 기준 노드(자동 추종/수동 고정), 담당 서비스와 실행 가속기 **분리**, 진행률·예상완료·입력 명령 원문 |
| `verdicts` | G | 완료·실패·자원 3축을 항목 단위로. `escalated_request_id` 로 [I] 와 이어진다 |
| `events[].task_node_id` + `task_attempt` | H | 노드로 필터하는 뷰. 회차가 붙어 재실행이 이전 회차를 덮지 않는다 |
| `external_requests` | I | 6단계 `stage_times`, 요청 식별자·사유, 배포 수신 여부, 재실행 회차, 최종 판정 |
| `regions` + `sources` | §3·§5 | 구역별 표시 가능 여부와 소스별 수신 상태 |

세 가지를 이 경로가 지킨다.

- **미측정은 0 이 아니다.** 측정값이 없으면 `{"unit": ...}` 만 나가고 `value` 칸이
  없다. 측정된 0(유휴)은 `value: 0.0` 이라 둘이 구분된다. 지표의
  `target_meet_state` 는 `MET` / `UNMET` / `NOT_MEASURED` 세 값이고 미측정은 미달
  집계에 섞이지 않는다(`derived.not_measured_indicator_names` ≠
  `derived.unmet_indicator_names`).
- **가속기는 개체다.** 같은 `accelerator_kind` 가 여럿이어도
  `accelerator_instance_id` 로 서로 구분된다. 배치된 서비스가 없는 개체도 목록에
  남고 `derived.idle_accelerator_instance_ids` 로 드러난다. 종류·부착 형태·벤더
  라벨은 전부 등록 데이터이고 벤더 열거형이 아니다(AI-O-05).
- **계층이 섞이지 않는다.** `accelerators`(L1)와 `services`(L2)가 다른 배열이고
  서로의 원소를 담지 않는다. 서비스 지표에도 그것이 도는 가속기가 붙어 지연의
  원인을 계층으로 좁힐 수 있다.

**조회 전용이다.** `POST /api/dashboard` 는 어느 모드에서도 **본문을 읽기 전에** 405
(`query_only_path`)다 — 상태 뷰 계약으로 실행 상태를 바꿀 수 없다(문서 §5 조회 전용
원칙). `?pin=` 은 표시 대상의 선택이므로 조회에 속한다(문서 §1.1).

데이터는 설정의 `dashboard` 블록에서 온다(`config/status_ui.dashboard.example.json`
가 구역 B~I 전부를 채운 예시다). 블록이 없는 설정도 정상이며 그때는 해당 구역이
`region_available: false` + `region_reason`("no_data_yet" / "source_not_received")으로
나오고 다른 구역은 그대로 동작한다(AI-C-05). 한 번도 수신하지 않은 소스는
`last_received_at` 칸이 아예 없어서 "받았지만 오래됐다"(`source_stale: true`)와
구분된다.

작업 그래프의 생성은 **우리 것이 아니다** — 생성 주체(가시화)의 계약을 소비하고
`source_status` 로 원본 상태 문자열을 함께 보존한다(AI-B-12). SDI 요청 식별자의 발급
주체도 외부이고 서버 내부 진척(담당·빌드 상태)은 칸 자체를 두지 않는다(AI-B-13).

`overrides`는 `node_id` → `{tags?, budget?, exclude_providers?}`. 키 `"*"`는 모든 노드의
기본값이고 노드별 항목이 그 위에 덮인다. `budget`은 일부 필드만 줘도 되고 나머지는
노드 설정값을 쓴다. 모르는 node_id는 404.

`functions[].supplement[]`는 `{kind, role, reason, reason_token, reason_data, provider_id, node_id}`,
`functions[].resources`는 `{by_role: {role: {compute_units, memory_mb}}, by_kind: [...], required_hw_tags: [...]}`.
`required[]/optional[]` 행은 `{kind, activated, served_by: [...], missing, why: [{node_id, role, reason, reason_token, reason_data, alternatives}]}` —
`activated: false`는 배포 프로파일이 그 kind를 켜지 않았다는 뜻이다.

2차 UI 필드(전부 additive): `roles_by_kind: {kind: [role]}`(필수 kind별 제공 계층),
`solo_roles: [role]`, `combo_roles: [role]`(규칙은 위), `trace: [{kind, required, role, node_id,
reason, reason_token, reason_data, best_candidate, missing_tags}]`(ACTIVE면 빈 목록; 빠진
필수 kind 먼저, 그다음 빠진 선택 kind, 각각 × 모든 계층; `missing_tags`는
`required_hw_tag_missing` / `required_runtime_tag_missing`의 데이터를 쉼표로 나눈 것이고
그 외 사유면 `[]`), `unverified_nodes: [node_id]`(자원을 부담하는 노드 중 `verified:false`
또는 freshness가 없는 것). `/api/fleet`·`/api/resolve`·`/api/config`의 노드에는
`verified`와 `freshness: {healthy, checked_at, age_s, ttl_s, fresh, source, deployment_ref} | null`이
붙는다 — `null`은 "아무도 검증한 적 없음"이고 시각을 지어내지 않는다.

`POST /api/placement`·`POST /api/devices/command`(deploy)는 `function_id`(기본 `"*"` =
모든 기능), `requester: {role, id?}`, `correlation_id`를 받아 실행 계획에 그대로 싣는다.
`requester`는 **자리**다 — 모양(`role` 문자열 필수)만 검사하고 값·권한은 판정하지 않는다
(인증·권한 설계는 사용자 몫, 계획 §3 "요청자 자리"). 계획 로그는 **인메모리**(기본 마지막
200개, `StatusService(plan_capacity=)`)이고 `POST /api/reset`이 비운다 — 실행 이력의 저장은
백엔드 책임이다(AI-O-03).

### 연결 검증 freshness (`hw_smoke_reports`)

설정에 `"hw_smoke_reports": "../reports/hw_smoke"`(설정 파일 기준 상대경로)가 있으면 그
디렉터리의 **가장 새 `*.json`**(mtime, 같으면 이름) 하나를 읽어 장치별 `RuntimeInstance`를
만든다: 장치마다 가장 깊이 도달한 단계의 `ok`가 `healthy`, 단계별 TTL(L1 60s / L2 300s /
L3 600s — `tools/hw_smoke/smoke.py::LEVEL_TTL_S`와 같고 테스트가 동일함을 확인한다)이
`ttl_s`, `probed_at`이 `checked_at`. 필드명은 데이터 사전 이름(`device_probe_level`,
`device_probe_reason`)과 짧은 이름(`level`, `reason`) 둘 다 읽는다. 디렉터리가 없거나
비어 있거나 파일이 깨져 있으면 오류가 아니라 "미검증"이며 `/api/config`의 `hw_smoke`가
`{reports_dir, report, devices, reason}`으로 이유를 말한다. 이 프로세스가 직접 잰
관측(`probe_link`, 장치 명령 뒤의 도달 여부 읽기)도 같은 표에 `source: device_probe`로
들어간다(TTL 60s). 생성자 인자 `runtime_instances={node_id: RuntimeInstance}`로 직접
넣을 수도 있다(`source: injected`). freshness는 **관측**이지 가용성 판정이 아니다 —
장치 최종 가용성은 여전히 백엔드가 판정한다(원칙 #15, AI-O-04).

### 온디바이스 상주 축 (`/api/residency`)

설정에 `device_purposes`(목적 파일 경로)가 있고 노드가 `purpose`를 선언했을 때만
나타난다. 없으면 기존 화면 그대로다 — 목적을 선언하지 않은 노드는 정상 구성이지
오류가 아니다.

응답의 `rows[]`는 `{kind, placement(ondevice|edge), policy, reason, reason_token,
reason_data, survives_outage, quality_is_safety_affecting, outage_behavior,
edge_service, local_fallback_kind, edge_payload, min_link_quality, is_core,
degrade_rank, resolution}`. `resolution`은 **온디바이스 행에만** 있고 기존
`ZoneApplication.resolve()` 결과 그대로다(엣지 kind는 이 장치가 돌릴 것이 아니라
상태가 없다). `link`는 `{source, quality, stability, declared_posture, samples,
posture, reason, reason_token, permits_remote}`이고 `link_origin`이 그 값이
what-if인지 노드 관측인지 목적 선언인지 말한다.

`violations[]`는 판정 실패가 아니라 **목적 데이터 자체의 모순**이다(예: 단절 중에도
살아야 한다고 선언한 기능이 엣지로 결정됨). 배치 전에 사람이 봐야 하는 것이라
화면에서도 따로 표시한다.

`node_id`를 `link`와 함께 POST하면 그 링크로 다시 판정한다 — 목적 데이터는 손대지
않으므로 diff를 "링크 때문에 옮겨진 것"으로 읽을 수 있다. `tags`/`budget`/
`exclude_providers`도 같이 줄 수 있고, 이것들은 배치가 아니라 그 뒤의 해석에만
영향을 준다.

### `config/device_purposes.example.json`

`{"purposes": [{purpose_id, description, node_tags, preferred_node_tags, budget,
link, link_thresholds, capabilities: [{kind, policy, survives_outage,
quality_is_safety_affecting, edge_service, outage_behavior, local_fallback_kind,
min_link_quality, edge_payload, is_core, degrade_rank, requirement}]}]}`.
`policy`는 `resident` | `link_dependent` | `edge_served`. 모르는 키는 거부된다
(`contracts/profile_loader.py::device_purpose_from_dict`).

## 설정 편집

### `config/status_ui.example.json`

- **노드 추가**: `nodes[]`에 `{"node_id", "label", "role", "tags": [...], "budget": {"compute_units", "memory_mb"}}`.
  `role`은 자유 문자열 계층, `tags`는 `providers/compute.py::discover_node_tags()`가
  돌려주는 것과 같은 자유 문자열(관례상 `tier.<role>`도 넣어 provider가
  `required_hw_tags`로 계층을 요구할 수 있게 한다 — `go1-adapter`가 그 예).
- **기능 추가**: `functions[]`에 `{"function_id", "required_capabilities": [...], "optional_capabilities": [...]}`.
  라벨·설명은 라벨 파일에.
- **capability kind 추가**: `deployment.active_capability_kinds`에 kind를 넣고
  `capabilities[]`에 `{"kind", "is_core", "degrade_rank", "requirement": {"required": [...], "optional": [...]}}`
  를 추가한다. `deployment`는 `profile_from_dict`가 그대로 읽으므로 모르는 키는 거부된다.
- `labels`: 라벨 파일 경로(이 파일 기준 상대경로, 기본 `status_ui.labels.json`).
- `hw_smoke_reports`(선택): `tools/hw_smoke` 보고서 디렉터리(이 파일 기준 상대경로). 없으면
  freshness는 전부 `미검증`이다. `config/status_ui.hardware.example.json`은 `../reports/hw_smoke`.
- `nodes[].verified`(선택, 기본 `true`): `false`면 원문 `[확인]` 항목 — 판정은 바뀌지 않고
  계층 탭에 `미확정 장비` 배지, 그 노드가 자원을 부담하는 기능 카드에 `미검증 장비 포함`이
  붙는다(상태 어휘를 늘리지 않는 2026-09-28 결정).

### `config/providers.status_ui.example.json`

`providers_manifest`가 가리키는 manifest의 `providers[]`에 항목 하나. 형식은
`registry/manifest.py` 참조. 컨테이너로 띄우는 provider는 `deployment`(`image`,
`command`)를 두면 "배치 적용"에서 `start`/`stop`이 나오고, 없으면 `in_process`로 한
번만 인정된다.

### `config/status_ui.labels.json`

`{"languages": ["ko","en"], "ui": {key: {ko,en}}, "capability_kinds": {kind: {ko,en}},
"functions": {id: {"label": {ko,en}, "description": {ko,en}}}, "states", "grades",
"reasons"(STATE_CHANGE_REASONS 토큰 전부), "roles", "commands"(start/stop/in_process),
그리고 장치 목적을 선언한 설정에서만 필요한 "purposes", "residencies"(ondevice/edge),
"link_postures", "residency_reasons"(링크 자세 사유 + 배치 사유 + 모순 토큰),
"outage_behaviors"}`.
설정·manifest에 나타나는 모든 id에 두 언어가 있어야 하며
`tests/test_status_ui.py::test_labels_cover_every_id_in_both_languages`가 강제한다.
누락은 `/api/config`의 `labels_missing`(개발자 탭)에 나열된다.

예시 설정에서는 `go1-onboard`가 로봇 온디바이스, `pi6`·`pi4`는 고정 카메라
계층이다. 이동 제어는 `go1-onboard`의 `go1-adapter`가 제공한다(Go1 구성은 미실측
가정). `local_safety`·`door_detection`·`go_to_door`는 가능하며 `risk_analysis`는
`risk.event_input` provider가 없어 불가다. What-if에서 `unidepth`를 전체 제외하면
`go_to_door`는 불가, `local_safety`는 일부만 가능으로 바뀐다.

가시화 담당자에게 전달할 목적·실행·연동·한계는
가시화 전달 문서(비공개)를 참조한다.

## k3s 모드

```bash
python tools/status_ui/serve.py --config config/status_ui.example.json --control k3s --namespace default
```

`kubectl version`이 성공하면 `K3sControlProvider`로 실제 Deployment를 만든다
(이미지는 `example.invalid/...`이므로 pull은 실패한다 — 배치 계약 확인용). kubectl이
없거나 클러스터가 응답하지 않으면 **local로 폴백**하고 `/api/config`의 `control`에
`{"requested": "k3s", "active": "local", "reason": "orchestrator_unavailable"}`가 남으며
헤더 배지가 경고색으로 바뀐다. 서버는 죽지 않는다(AI-B-05).

한 프로세스에 ControlProvider는 하나이므로 두 노드가 같은 provider_id를 바인딩하면
같은 target을 두 번 start한다 — 검토용 한계다.

## 테스트

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_status_ui.py
```
