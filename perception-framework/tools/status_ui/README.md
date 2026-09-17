# 기능 상태 패널 (검토용)

프레임워크가 지금 계산하는 것을 눈으로 확인하는 **로컬 검토 도구**다. 운영 UI가
아니다 — 운영 UI는 가시화 파트 담당이고(AI-C-19,
`docs/ai/design/capability-ui-orchestration-plan.md` §3-4), 이 패널은 payload
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
3. **장치의 계층(role)** — `nodes[].role`(`ondevice` / `edge` / `server` …). 자유
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

"표시 등급(파생)" READY/DEGRADED/MISSING/STALE/BLOCKED는 (CapabilityState, 사유
토큰)에서 이 도구가 파생한 값이고 프레임워크 상태가 아니다(§3-2). 장치 가용성은
건드리지 않는다(원칙 #15).

## 화면 (탭 3개 + KO | EN)

- 헤더의 **`KO | EN`** 버튼이 언어를 즉시 바꾼다(재조회 없음, 라벨 파일에서 다시
  그림). 선택은 `localStorage`에 남기며(실패해도 무시) 기본은 ko. 모든 문자열은
  `config/status_ui.labels.json`의 `t(key)` 조회이고 라벨이 없는 id는 원문 id 그대로
  보인다. **API 응답에는 라벨이 없다** — id만 싣는다(신원·권한·대상별 필터링은 이
  도구 범위 밖이며 그 위에 얹을 수 있게 응답은 additive로 유지한다).
- **기능** (기본 탭): 기능마다 카드 — 라벨, 평문 상태 칩(`가능 / 일부만 가능 / 불가`,
  색 + 글자), 한 줄 설명, 불가·일부면 "왜" 한 줄(supplement). 클릭 → 상세 서랍:
  필수·선택 kind 행(계층 + provider_id, 노드는 흐리게), 계층별 자원, 최소 보충 목록.
  What-if 중이면 카드에 `이전 → 이후` 칩.
- **계층·자원**: 계층(role)별 섹션 — 제공 중인 kind, 그 계층의 노드(이름 작게):
  태그 핀(체크 = what-if 토글), 예산, provider 제외, 이 노드가 제공 중인 kind,
  배치(`배치 적용` + 액션/바인딩/감사 로그). 변경은 `/api/functions/whatif`를 부르고
  기능 탭이 이전→이후를 보여준다. 이벤트 패널도 여기.
- **개발자**: 예전 노드별 표 그대로 — CapabilityState, 파생 등급, provider, 사유
  토큰(원문 id, mono) + 번역, 대안 표, cost/priority/nodeSelector, vocabulary,
  라벨 누락 id.

## 실행

```bash
cd perception-framework
python tools/status_ui/serve.py --config config/status_ui.example.json
# → status_ui: http://127.0.0.1:8765/  control=local
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
curl -s $B/api/vocabulary                   # state_change_reasons / grades / capability_states
curl -s "$B/api/resolve?node_id=pi6"        # 기준선 resolve (rows[].alternatives, priority, required_hw_tags 포함)
curl -s -X POST $B/api/whatif -H 'content-type: application/json' \
  -d '{"node_id":"pi6","tags":["compute.cpu","compute.gpu"],"budget":{"compute_units":6},"exclude_providers":["unidepth"]}'
                                            # 노드 하나: baseline + override + diff[]
curl -s -X POST $B/api/placement -H 'content-type: application/json' \
  -d '{"node_id":"edge-gpu"}'               # reconciler.apply → actions[] + state
curl -s "$B/api/placement?node_id=edge-gpu" # 바인딩된 provider + nodeSelector + audit_log 꼬리
curl -s $B/api/events                       # placement_applied / control_fallback / reset 이벤트
curl -s -X POST $B/api/reset                # reconciler·이벤트·control 상태 초기화
```

`overrides`는 `node_id` → `{tags?, budget?, exclude_providers?}`. 키 `"*"`는 모든 노드의
기본값이고 노드별 항목이 그 위에 덮인다. `budget`은 일부 필드만 줘도 되고 나머지는
노드 설정값을 쓴다. 모르는 node_id는 404.

`functions[].supplement[]`는 `{kind, role, reason, reason_token, reason_data, provider_id, node_id}`,
`functions[].resources`는 `{by_role: {role: {compute_units, memory_mb}}, by_kind: [...], required_hw_tags: [...]}`.
`required[]/optional[]` 행은 `{kind, activated, served_by: [...], missing, why: [{node_id, role, reason, reason_token, reason_data, alternatives}]}` —
`activated: false`는 배포 프로파일이 그 kind를 켜지 않았다는 뜻이다.

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

### `config/providers.status_ui.example.json`

`providers_manifest`가 가리키는 manifest의 `providers[]`에 항목 하나. 형식은
`registry/manifest.py` 참조. 컨테이너로 띄우는 provider는 `deployment`(`image`,
`command`)를 두면 "배치 적용"에서 `start`/`stop`이 나오고, 없으면 `in_process`로 한
번만 인정된다.

### `config/status_ui.labels.json`

`{"languages": ["ko","en"], "ui": {key: {ko,en}}, "capability_kinds": {kind: {ko,en}},
"functions": {id: {"label": {ko,en}, "description": {ko,en}}}, "states", "grades",
"reasons"(STATE_CHANGE_REASONS 토큰 전부), "roles", "commands"(start/stop/in_process)}`.
설정·manifest에 나타나는 모든 id에 두 언어가 있어야 하며
`tests/test_status_ui.py::test_labels_cover_every_id_in_both_languages`가 강제한다.
누락은 `/api/config`의 `labels_missing`(개발자 탭)에 나열된다.

예시 설정에서는 `go1-onboard`가 로봇 온디바이스, `pi6`·`pi4`는 고정 카메라
계층이다. 이동 제어는 `go1-onboard`의 `go1-adapter`가 제공한다(Go1 구성은 미실측
가정). `local_safety`·`door_detection`·`go_to_door`는 가능하며 `risk_analysis`는
`risk.event_input` provider가 없어 불가다. What-if에서 `unidepth`를 전체 제외하면
`go_to_door`는 불가, `local_safety`는 일부만 가능으로 바뀐다.

가시화 담당자에게 전달할 목적·실행·연동·한계는
[가시화 전달 문서](../../../docs/ai/status-ui-visualization-handoff.md)를 참조한다.

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
