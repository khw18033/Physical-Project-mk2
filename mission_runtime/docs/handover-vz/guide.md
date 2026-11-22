# 가시화 파트 인계 — 패치 하나와 이 문서 하나

보내는 쪽: AI 파트(`mission_runtime`) · 받는 쪽: 가시화 파트(`khw_VZ`)
갱신 2026-11-20 · 계약 판 `FMS/2.2`

## 0-0. 패치는 **선택이다** (2026-11-22 추가)

가시화를 고치지 않고 **백엔드만 붙이는** 구성이 기본이다. 그쪽 앱은 우리 쪽으로
무엇을 밀어 넣지 않는다 — 떠 있는 것을 읽어 간다(`data_stream` 과 같은 모양).
받는 쪽에서 할 일은 **주소 둘**이고 코드는 한 줄도 바뀌지 않는다.

```bash
VITE_GATEWAY_HTTP=http://<백엔드>:8899 VITE_GATEWAY_WS=ws://<백엔드>:8899 npm run dev
#  「기능」 카드까지 채우려면 capability 주소도 — 기본값이 127.0.0.1:8765 이므로
#  백엔드가 같은 기계면 그대로 두면 된다. 다른 기계면 연결 관리에서 바꾼다.
```

원본이 우리에게서 읽는 창구 전체와, 아직 우리가 내지 않는 다섯(`/actions` ·
`/audit` · `/insight/` · `/server-metrics` · `/observability/client-metrics`)은
`docs/guides/deployment.md` §3-0-1 의 표에 있다. **그 다섯이 없어도 화면은 깨지지
않는다** — 그 카드만 비고 나머지는 돈다.

아래 패치는 그 위에 **FMS 노드 여섯**을 더하는 선택 묶음이다(백엔드 스택을 화면에서
켜고 끄는 노드 포함). 적용하지 않아도 백엔드 연결은 성립한다.

---

이 디렉터리에는 둘만 있다.

```text
guide.md                        이 문서
patch/mission-runtime-viz.patch 가시화 앱에 바로 적용하는 패치 (13 파일 · +2152)
```

전에 있던 이미지·계약 사본·옛 패치 다섯은 치웠다. 계약의 정본은 사본이 아니라
`mission_runtime/docs/view-contract.md` 와 `mission_runtime/schemas/view_*.schema.json`
이고, 사본을 두면 한쪽만 고쳐지는 날 어느 쪽이 참인지 알 수 없다.

---

## 0. 세 줄 요약

1. **백엔드는 하나의 주소다.** 게이트웨이 한 포트에 조회 30(GET) · 쓰기 20(POST)이
   선다. 그 주소는 **그 기계의 Tailscale 주소**이고, 기계를 옮기면 주소도 따라간다 —
   선언에 박히지 않는다.
2. **그 기계 앞에서 사람이 하는 일은 하나뿐이다: 백엔드를 켜 두는가.** 전송 스택 ·
   실증 스트림(`data_stream`) · 추론은 **이 앱에서** 켜고 끈다(`POST /api/stack`).
3. 패치 하나를 적용하면 그 화면이 바로 생긴다. 앱 코드를 직접 고칠 필요는 없다.

---

## 1. 패치 적용

```bash
cd <khw_VZ 클론>
git apply docs/handover-vz/patch/mission-runtime-viz.patch   # 경로는 받은 자리에 맞게
cd viz-debugger && npm run typecheck && npm run verify:view-nodes
```

깨끗한 `khw_VZ` 헤드(`3b0e972`)에 **그대로 붙는 것을 확인했다.** 적용 후 그쪽 자체
검사 13개를 돌려 전부 통과하는 것까지 봤다: `typecheck` · `view-nodes` · `dep-rules` ·
`single-egress` · `one-gateway` · `no-physical` · `clean` · `crlf-safe` · `layout` ·
`no-llm` · `verify-hygiene` · `dict-shape` · `no-raw-korean` · `i18n-scope-leak` ·
`node-scope`.

### 패치가 더하는 것

| 뷰 노드 | 무엇 | 읽는 계약 |
|---|---|---|
| `fms-twin` | 디지털 트윈 맵 — 객체·근거·동일성 | `/api/twin` · `/api/object` |
| `fms-recommend` | 추천 임무와 **촉발 근거**. 막힌 후보도 사유와 함께 | `/api/recommend` |
| `fms-subtasks` | 서브태스크의 capability 접지. 거부 사유가 단계마다 | `/api/subtasks` |
| `fms-tiers` | 계층별 지표(하드웨어/서비스 분리 · 미측정 구분) | `/api/dashboard` |
| `fms-deployment` | 장치 들이기 · 보정 · 학습 · 모델 교체 네 단계 | `/api/deployment` 외 |
| **`fms-stack`** | **백엔드 스택을 켜고 끈다** (261120 신설) | `/api/services` + `POST /api/stack` |

앞의 다섯은 조회만 한다. 여섯째가 **쓰기 계약을 쓰는 첫 FMS 노드**다.

---

## 2. 주소 — 전부 Tailscale, 그리고 기계를 따라간다

### 2-1. 백엔드 주소

```bash
# 백엔드 기계에서
make open            # = serve.py --host 0.0.0.0
# 또는 오버레이 주소에만 묶는다(권장 — 오버레이 밖으로는 열리지 않는다)
.venv/bin/python tools/vz_gateway/serve.py --host overlay --port 8899 \
    --domains profiles/domains.example.json --config config/status_ui.fms.example.json \
    --stack-units config/stack_units.json
```

기동 로그가 **붙을 수 있는 주소**를 찍는다.

```
vz_gateway: ws://100.83.37.9:8899  ·  http://100.83.37.9:8899/registry
vz_gateway: 듣는 주소는 0.0.0.0:8899 이고 위 주소는 오버레이에서 본 이 기계다
vz_gateway: 뷰어를 이렇게 띄운다 — VITE_GATEWAY_WS=ws://100.83.37.9:8899 … npm run dev
```

전에는 `--host 0.0.0.0` 일 때 안내문도 `0.0.0.0` 을 적었다 — 그 주소로는 다른
노트북이 **붙을 수 없다.** 지금은 와일드카드일 때 오버레이가 말하는 이 기계의
주소를 적고, 오버레이를 물어볼 수 없으면 주소를 지어내지 않는다.

앱 쪽에서 할 일은 환경변수 둘이다.

```bash
VITE_GATEWAY_WS=ws://<백엔드 Tailscale 주소>:8899 \
VITE_GATEWAY_HTTP=http://<백엔드 Tailscale 주소>:8899 npm run dev
```

### 2-2. 로봇 주소는 **지금 이 앱이 붙어 있는 주소**다

로봇 SDK 를 들고 있는 기계가 가시화 노트북이다. 그 주소를 우리 선언에 박으면
노트북을 바꿀 때마다 선언을 고쳐야 하고, 고치는 것을 잊으면 운영자는 "명령이 안
간다" 만 본다. 그래서 선언은 이름으로 적고 런타임에 푼다.

```jsonc
// 우리 쪽 끝점 선언
{ "node_id": "go1-001", "url": "mqtt://viewer:1883", "scope": "overlay" }
```

`viewer` 는 **이 앱의 WebSocket 이 붙어 온 주소**로 풀린다. 그 주소가 오버레이
대역(100.64.0.0/10 또는 `*.ts.net`)이 아니면 **쓰지 않고 사유를 남긴다** — 랜 주소를
로봇 주소로 쓰면 원칙(구간은 오버레이 위에서만)이 조용히 깨진다. 못 푼 줄은 목록에서
빠지지 않고 `url: null` 과 `unresolved` 사유로 남는다.

`GET /registry` 의 `broker_candidates[]` 가 그 결과다 — 앱은 고를 순서대로 받은
목록에서 고르기만 하면 되고, 주소를 코드에 박을 필요가 없다.

---

## 3. 백엔드 스택을 이 앱에서 켠다 (261120 신설)

### 3-1. 조회 — `GET /api/services`

```json
{
  "configured": true,
  "reason": null,
  "units": [
    {"unit_id": "integration-stack", "kind": "compose",
     "label": {"ko": "전송·관측 스택 (mosquitto · kafka · otel)"},
     "status": "RUNNING", "ready": true, "ready_port": 1883,
     "depends_on": [], "log_path": null, "exit_code": null, "last_output": null},
    {"unit_id": "data-stream-server", "kind": "process",
     "status": "STOPPED", "ready": false, "ready_port": 10001,
     "depends_on": ["data-stream-redis"],
     "log_path": "~/.local/state/mission_runtime/stack/data-stream-server.log",
     "exit_code": 1,
     "last_output": "robot1 주소가 없습니다: --robot1 로 주거나 hosts.local.json 에 적으세요"}
  ]
}
```

네 칸을 **각각** 읽어야 한다. 섞으면 운영자가 다음에 무엇을 할지 모른다.

| 칸 | 뜻 | 섞으면 |
|---|---|---|
| `status` | 제어면이 본 프로세스 상태 | — |
| `ready` | **다른 축이다.** `true`/`false`/**`null`(묻지 않았다)** | 떠 있는데 준비 안 된 정상 상태가 사라진다 |
| `exit_code` | 끝났으면 그 코드. `null` 은 **돌고 있다 또는 띄운 적 없다** | `0`(정상 종료)과 섞이면 "안 띄웠다"가 "성공"이 된다 |
| `last_output` | **왜 멈췄는지** 한 줄 | 없으면 사유가 저쪽 기계의 로그에만 남는다 |

`configured: false` 는 **빈 목록과 다른 사실**이다 — 그 설치는 스택을 띄우지 않는다
(백엔드에 `--stack-units` 선언이 없다). 빈 목록으로 그리면 운영자가 선언 파일을
찾아 헤맨다.

### 3-1-1. 누구로 왔나 — `GET /api/identity` (신설)

```json
{"actor": "unconfigured", "authenticated": false, "auth_mode": "demo_roles",
 "permissions": ["may_view"], "session_expires_in_s": null,
 "selectable_accounts": [{"account_id": "admin", "display_name": "관리자", "role": "admin"}, …]}
```

**권한을 요구하지 않는다** — 답이 "아무도 아니다" 일 수 있어야 하므로 능력을 걸면
들어올 길이 없다. 이 경로가 생긴 이유: 토큰은 새로고침을 넘어 남는데 능력 목록은
로그인 응답에만 있었다. 그래서 새로고침한 앱은 **토큰은 있는데 자기가 무엇을 할 수
있는지 모르는** 상태가 되고, 그 상태에서 단추를 그리면 눌러 보고 403 을 받는다.

패치의 스택 노드는 이것을 먼저 읽고, `may_operate_stack` 이 없으면 **그 자리에
들어가는 길**을 띄운다: 계정 파일이 없는 설치에서는 예시 계정 단추(관리자·사용자 1…),
계정이 있는 설치에서는 계정·비밀번호 칸. 들어오면 단추가 열린다.

### 3-2. 쓰기 — `POST /api/stack`

```http
POST /api/stack
Authorization: Bearer <세션 토큰>
{"unit_id": "data-stream-redis", "action": "start"}     # start · stop · restart
→ 200 {"unit_id":"data-stream-redis","action":"start","accepted":true,
        "status":"RUNNING","reason":null,"actor":"demo:admin"}
```

**보내는 것은 단위 이름뿐이다.** 명령줄을 받는 칸은 계약에 없다 — 받으면 쓰기 계약
하나가 원격 코드 실행 창구가 된다. 무엇을 띄울 수 있는지는 백엔드 기계의 선언
(`config/stack_units.json`)이 정하고, 앱은 그 목록에서 고른다. 선언 밖 이름은
**404 `unit_not_declared`** 다.

거절도 답이다 — 사유 토큰을 그대로 보여 주면 된다.

| 사유 | 뜻 |
|---|---|
| `dependency_not_running:<단위>` | 먼저 서야 하는 단위가 있다 |
| `executable_not_found:<이름>` | 그 기계에 그 실행 파일이 없다 |
| `docker_not_available` | compose 단위인데 docker 가 없다 |
| `declared_file_missing:<자리>` | 선언이 가리키는 파일이 없다 |
| `start_failed:…` · `stop_failed:…` | 띄우거나 내리다 실패했다(뒤에 마지막 줄) |

필요한 능력은 `may_operate_stack` 이고 `operator` · `developer` · `admin` 에 있다.
**물리 명령 권한(`may_issue_command`)과 다른 칸이다** — 프로세스를 띄우는 것과 로봇을
움직이는 것은 같은 권한이 아니다.

### 3-3. 멱등하다

같은 `start` 를 두 번 받아도 **두 번 띄우지 않는다.** 이미 돌고 있으면 수락하고 상태를
그대로 돌려준다. `stop` 도 이미 멈춰 있으면 수락이다. 그래서 앱이 단추를 두 번 눌러도
안전하고, 눌린 횟수를 세어 둘 필요가 없다.

---

## 4. 세션은 쿠키가 아니라 Bearer 다

우리와 앱은 **다른 출처**다. 교차 출처 쿠키를 허용하려면 자격증명을 열어야 하고, 그
순간 운영자가 방문한 아무 사이트가 그 브라우저로 명령을 보낼 수 있다(CSRF).

```http
POST /api/assume  {"account": "admin"}        # 계정 파일이 없는 설치의 예시 자세
POST /api/login   {"account_id": "...", "password": "..."}
→ 200 { "session_token": "...", "permissions": [...], "session_expires_in_s": 28800 }
```

토큰은 응답 **본문**에 있다(`Set-Cookie` 는 없다). 이후 `Authorization: Bearer …` 로
붙인다. 패치의 `src/fms/fmsApi.ts` 가 이미 그렇게 한다.

교차 출처로 부르는 데 필요한 것은 서버가 낸다 — 실측(다른 Tailscale 출처에서):

| 확인 | 결과 |
|---|---|
| `GET /api/scene` | `200` · `Server: FMS/2.2` |
| CORS | `Allow-Origin: *` · `Allow-Methods: GET, HEAD, OPTIONS, POST` · `Allow-Headers: Content-Type, Authorization` |
| 사전 요청 `OPTIONS` | `204` |
| 토큰 없이 쓰기 / 틀린 토큰 | `403` / `401` |
| **조회 경로에 POST** | 유효한 토큰이 있어도 **`405`** (본문 읽기 전) |

마지막 줄이 계약의 성질이다: 관찰이 실행에 개입할 수 없다(AI-O-06). 읽는 이름과
쓰는 이름은 겹치지 않는다 — `/api/services`(읽기) ↔ `/api/stack`(쓰기).

---

## 5. 그 밖에 새로 나가는 칸

### 5-1. 충전 상태 — `GET /api/robot` 의 `charge`

```json
"charge": {"level_pct": 61.0, "charging": true, "observed_age_s": 3.5}
```

**충전소 노드는 어느 배치에도 선언되어 있지 않다.** 그래서 운영자가 아는 충전 사실은
자리 예약이 아니라 이 관측이고, 값은 장치가 이미 보내고 있던 것이다.

- `charge: null` = 그 장치의 충전 상태를 **한 번도 들은 적이 없다**.
- `level_pct: null` = 장치가 말을 하면서 그 칸만 비웠다. **0% 가 아니다.**
- `charging: null` = **거짓과 다르다.** "물려 있지 않다" 와 "모른다" 는 할 일이 다르다.
- `observed_age_s` 는 `last_seen_age_s` 와 **다른 축**이다 — 장치가 계속 말하면서
  배터리 칸만 빼고 보낼 수 있고, 그때 30분 전 값을 지금 값으로 그리면 "충전 중" 이
  거짓이 된다.

### 5-2. 계약 판은 머리에도 실린다

`Server: FMS/<major>.<minor>`. major 가 다르면 해석을 거부하는 쪽이 맞다.
지금은 `2.2` 이고, 이번에 **더해지기만** 했다(조회 28→30 · 쓰기 19→20).

---

## 6. 아직 받을 자리가 없는 것 — 목록

화면이 틀리게 되지는 않지만, 우리가 내는데 앱이 받는 자리가 없는 것들이다.

| ID | 무엇을 내는가 | 어디로 |
|---|---|---|
| AI-O-06 | 통합 운영 상태 **한 스냅샷**(소스별 미수신을 그 구역에만 격리) | `status_snapshot` 채널(백엔드 채널 개설 대기) |
| AI-L-10 | 어느 모델 버전을 어느 가속기에 배정했고 **왜** 그랬는지 | 상태 스냅샷 |
| AI-L-08 | 지금 도는 모델이 어떤 사건·데이터·승인을 거쳐 왔는지 | 계보 참조 |
| AI-L-05 | 새 성능과 **회귀**를 두 축으로(한 수로 합치면 옛 것을 잊은 후보가 통과한다) | 검증 결과 |
| AI-C-18 | 장치가 **스스로 선언한** 입출력·단위·취소 가능 여부·멱등성 | capability 선언 |
| AI-C-20 | 전달 ≠ 수락 ≠ 완료. 긴급정지는 일반 취소와 다르다 | 물리 명령 계약 |
| AI-S-08 | 선언된 사전정보와 **실제 관측**의 구분 | 객체·환경 레코드 |
| AI-O-03 | 오류 재현에 필요한 원본 입력·구성·버전 참조 | 재현 참조 |

## 7. 우리 쪽에 남은 요청 둘

1. **폐기된 요구사항 ID 를 아직 쓴다.** `AI-D-01`~`D-04`(159회) ·
   `AI-C-09`/`C-11`/`C-14`/`C-17`(91회) · `AI-R-03`(6회) · `AI-E-03`(2회) ·
   `AI-P-01`~`P-03`(12회). 서브태스크 산출은 AI 파트로 복귀하면서 `AI-B-14`·`AI-B-15`
   로 재부여됐고 옛 번호는 재사용하지 않는다. `AI-D-01` 은 `plans.ts` 의 계획 출처
   모델에 박혀 **화면에 그대로 뜬다.**
2. **`verify:emergency-stop` 이 깨져 있다**(우리가 클론해 돌려 봤다). 긴급정지는 일반
   취소와 다른 경로여야 한다는 그쪽 자체 검사이고, 그 검사가 지키는 성질은
   AI-C-20 과 같은 것이다.

---

## 8. 백엔드를 처음 받았다면

받는 쪽이 하는 일은 한 줄이다. 자세한 절차·폐쇄망·기계 이식은
`mission_runtime/README.md` 와 `mission_runtime/docs/guides/deployment.md` 에 있다.

```bash
git clone -b jny_AI <원격> && cd mission_runtime
bash tools/install_check.sh      # 설치 · 자가점검 · 계약 시험 · 기동 확인
make open                        # 다른 기계에서 붙을 수 있게 세운다
```
