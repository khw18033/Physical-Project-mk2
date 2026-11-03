# 통합 인수인계 — 다른 파트에서 반드시 고쳐야 하는 것

작성: 2026-11-02 · 개정: 2026-11-03(관측 평면 추가 — §1-나 · §2-나 · §4; 전역 좌표 소유권 재합의 요청 — §6; ＋ 조인 인계 — §7; 지도 계층 — §8)
기준: 통합 저장소 `main` @ `30f5ee94a`(개정 시점 재확인), HW 브랜치, 가시화 브랜치
우리 쪽 대응: 전부 끝났고 시험으로 고정했다(`tests/test_deployment_topology.py`,
`tests/test_real_prometheus_path.py`, `tests/test_server_contract_conformance.py`,
`tests/test_viz_descriptors.py`).

이 문서는 **우리가 할 수 없는 일**만 적는다. 우리 쪽에서 고칠 수 있었던 것은 이미
고쳤고, 그 목록은 §5 에 있다.

---

## 1. 배포·하드웨어 — 엣지가 AI 신호를 중앙으로 넘기지 않는다 (막힘)

벽이 **둘**이고 모양이 같다. 업무 평면은 브릿지 토픽 목록(1-가), 관측 평면은 페더레이션
`match[]`(1-나)이다. 둘 다 "엣지에서는 보이는데 중앙에서는 오지 않는다"로 나타나고,
오류도 로그도 없다.

### 1-가 업무 평면 — 브릿지 토픽 목록

#### 사실

엣지 Mosquitto 의 브릿지는 아래만 중앙으로 넘긴다.

| 방향 | 토픽 |
|---|---|
| 엣지 → 중앙 | `+/+/+/state` · `+/+/+/status` · `+/+/+/heartbeat` |
| 엣지 → 중앙 | `terminal/+/uplink` |
| 중앙 → 엣지 | `terminal/+/downlink` |

그 밖의 토픽은 **엣지 안에 머문다.** 우리 채널 여섯(`detections` · `risk_state` ·
`ai_failure` · `capability_status` · `model_deployment_result` · `status_snapshot`)은
목록에 없으므로 엣지에서 발행해도 중앙에 도달하지 않는다 — 오류도, 로그도 없이
그냥 오지 않는다.

#### 필요한 변경

둘 중 하나를 골라야 하고, 고르는 것은 배포·백엔드의 결정이다.

**안 ① 브릿지 토픽 추가** — 고칠 자리가 **셋**이고 하나만 고치면 조용히 막힌다.

| 순서 | 파일 · 줄 | 무엇을 |
|---|---|---|
| ① | `deploy/edge/config/mosquitto-entrypoint.sh:36-38` (`for ch in state status heartbeat`) | 브릿지 `out` 토픽에 AI 채널을 더한다 |
| ② | `server/backend/settings.py:102` (`TELEMETRY_CHANNELS`) | 채널을 등재한다. `bridge.py:61` 의 `SUBSCRIPTIONS` 가 이 튜플에서 패턴을 만들므로 ① 만 넓히면 중앙은 구독하지 않는다 |
| ③ | `server/contracts/common/payload/` | 채널별 본문 규격을 둔다. 없으면 ②를 해도 `topic_for_channel()`(`settings.py:112-115`)과 2단 검증이 `unknown_channel` 로 격리하고, 그 사실은 `be_ingest_rejected_total{stage="unknown_channel"}` 로만 보인다 |

토픽 모양은 기존과 같게 `{zone}/ai/{node}/{channel}` 를 제안한다.

**안 ② 기존 `status` 채널에 태움** — 봉투에 이미 `channel` 이 있으므로 토픽을 늘리지
않고 `{zone}/ai/{node}/status` 로 보내고 소비자가 `channel` 로 가른다. 위 표의 ①·②가
필요 없다는 장점과(③ 은 `status` 규격을 넓히는 형태로 여전히 필요하다), 한 토픽에
성격이 다른 본문이 섞인다는 단점이 있다.

우리 쪽은 둘 다 **코드 변경 없이** 된다 — 토픽은 provider 설정이고 상위 로직은 채널
이름만 쓴다. 정해지면 알려 주면 된다. 우리 채널 여섯의 본문 규격은
`schemas/ai/` 에 이미 있고 `tests/test_server_contract_conformance.py` 가 그쪽 정본
형식을 매번 대조한다 — ③ 에 그대로 넣을 수 있다.

#### 왜 우리가 못 하나

브릿지 설정과 중앙 ingest 구독·본문 규격은 배포·백엔드 자산이고 우리 저장소 밖이다.

### 1-나 관측 평면 — 엣지 페더레이션 `match[]`

#### 사실

중앙 Prometheus 는 엣지 raw 전량을 받지 않고 `/federate` 로 `match[]` 가 고른 것만
당겨 간다(`deploy/server/config/prometheus.yml:64-73`). 지금 그 목록은 둘이다.

```yaml
params:
  "match[]":
    - '{__name__=~"hw_.*"}'
    - '{__name__=~"system_cpu_.*|system_memory_.*"}'
```

우리 계측 이름(`ai_*`)은 여기에 없다. 그래서 **엣지 Prometheus 에는 있고 중앙
Prometheus 에는 없다.** 브릿지 토픽 목록과 같은 모양의 벽이다.

#### 필요한 변경 — 그리고 **먼저 읽어야 할 것**

⚠ **"요약을 넓히자"는 잘못된 해법이다.** 두 가지를 먼저 적어 둔다.

1. **상세가 엣지에 남는 것은 설계대로다**(원칙 #14, AI-O-01 "엣지에 상세·서버에
   요약"). 우리 실패 분석도 중앙이 아니라 엣지 엔드포인트(`:9090`)를 본다. `match[]`
   를 넓혀 엣지 raw 를 전량 끌어오면 2계층의 의미가 없어진다 — 그쪽 설정 주석이
   같은 말을 적어 두었다.
2. **치명 사건·장치 생사는 이 벽과 무관하다.** 그것은 계측이 아니라 log·trace 로
   가고, 엣지 Collector 가 요약 없이 **원본 그대로** 중앙으로 보낸다
   (`deploy/edge/config/otel-collector.yaml:47-53`). 집계하면 안 되는 상태를 계측
   요약에서 찾지 않는 것이 원칙 #14 이고, 우리 쪽도 계측 reader 가 사건 축에서
   "여기에 없다"고 답하도록 만들어 두었다.

그래서 필요한 것은 "넓히기"가 아니라 **결정 하나**다.

| 선택 | 내용 | 우리 쪽 영향 |
|---|---|---|
| **가** 좁은 요약만 등재 | `match[]` 에 항목 하나를 더한다. 전량이 아니라 운영 화면이 실제로 쓰는 소수만 — 예: `{__name__=~"ai_capability_.*\|ai_degraded_.*"}`. 이름 목록은 우리가 확정해 드린다 | 중앙 운영 뷰(AI-O-06)가 AI 축을 읽을 수 있다 |
| **나** 중앙은 AI 계측을 읽지 않는다 | `match[]` 를 그대로 둔다. 중앙이 필요한 AI 상태는 계측이 아니라 업무 채널(`status_snapshot` — §2)로 받는다 | 우리는 지금 그대로. **이쪽이면 §1-가 결정이 더 급해진다** |

**우리 선호는 「나」다.** 상태 스냅샷은 이미 업무 평면 계약으로 있고(`integration/status_wire.py`),
같은 사실을 계측과 업무 두 평면으로 보내면 두 값이 어긋나는 날이 온다(AI-O-06 의
"같은 사실은 한 출처에서 파생"). 「가」를 고른다면 이름 목록만 주면 된다.

#### 왜 우리가 못 하나

`prometheus.yml` 은 "현장에서 고치지 않는다"고 그쪽이 머리글에 적어 둔 추적 파일이고
(`deploy/server/config/prometheus.yml:6-12`), `match[]` 는 현장 폴더(`deploy/site/`)로
뺄 수 있는 항목도 아니다 — 잡 자체가 추적 파일에 있다.

#### 우리가 쓰지 않는 길 하나

remote-write 는 제안하지 않는다. 그쪽은 2계층 페더레이션을 **선택했고** 그 이유를
적어 두었다(중앙 부하가 장치 수가 아니라 구역 수에 비례하게). 우리 때문에 그 선택을
뒤집을 이유가 없다.

### 1-다 장치 선언 — 와이어가 AI-C-18 항목을 **하나도** 싣지 못한다

우리 쪽에서 유일하게 "부분" 으로 남아 있는 요구사항이고, 남은 이유가 전부 이 칸에
있다. 상세와 제안은 `specs/physical-command-interface.md` §8-3 에 P2~P7 로 적혀 있고
여기서는 가장 막혀 있는 둘만 옮긴다.

| # | 지금 오는 것 | 없어서 생기는 일 | 제안 |
|---|---|---|---|
| **P7** | `Capability` 는 `device_id` + action **이름 목록**뿐 | AI-C-18 이 요구하는 입출력 schema · 단위 · 좌표 · 시간 기준 · **취소 가능 여부** · **멱등성** · 동기/비동기 · 버전 · 품질·지연·자원 중 **하나도 못 싣는다.** 상위 기능이 "이 장치가 이 동작을 취소할 수 있는가" 를 장치 선언에서 알 수 없다 | 별도 `CapabilityDetail` 메시지(봉투 슬롯 8) 또는 `Capability` 에 `repeated ActionDetail details = 3` |
| **P2** | `parameters`·`result` 가 `map<string,double>` | 문자열·불리언·중첩이 못 간다. 그쪽도 이 제약 때문에 `assign_mission` 을 못 쓰고 **action 이름 자체를 어휘로 쓰는 우회**를 택했다(HW README §7 "우선순위 높음") | `map<string,string> parameters_text = 7` / `result_text = 5`, 또는 공용 Value 타입 |

우리 쪽 현재 처리: 이 경로로 온 선언은 `is_fully_declared() == False` 로 **구분해서**
들고 있고, 버려지는 칸은 직렬화기의 `wire_gaps` 카운터에 남아 관측 경로로 흘러간다
(`on_gap`). 없는 값을 채워 넣지 않으므로 지금도 돌지만, 채워지기 전까지 AI-C-18 은
"부분" 이다. 시각 3종(P3·P4·P5)은 엣지 수신 시각으로 대체되며 `time_source=
"edge_receipt"` 가 그 사실을 함께 들고 다닌다 — **장치가 그 동작을 실제로 한 시각이
아니다.**

---

## 2. 백엔드 — 이름과 채널 등재 (막힘)

### 2-가 업무 평면의 이름·채널

| 항목 | 지금 | 필요한 것 |
|---|---|---|
| `status_snapshot` 채널 | 우리 쪽 계약·예제·스키마 완비 | 공통 규약에 채널 등재, 구독 경로 개설 |
| `mission_id` · `utterance_text` | 우리 사전에 등재해 쓰는 중 | 공통 이름 사전에 등재하거나 다른 이름을 지정 |
| `sequence_id` ↔ `seq` | 우리 봉투는 `sequence_id` | 가시화 게이트웨이는 대상별 단조 증가 `seq` 로 유실·역전을 감지한다. **같은 값인지 확정 필요** — 다르면 둘 다 필요하고, 같으면 이름 하나로 통일 |
| `command_id` 발급 주체 | 백엔드 발급을 전제로 소비 준비됨 | 확정 회신 |
| 전역 좌표·트윈 상태의 주인(BE-C-04) | 그쪽 계약은 백엔드 단독 수행으로 적혀 있고 우리 요구사항은 2026-11-03 개정으로 AI 소유로 적는다 | **§6** — 재합의 회신. 그때까지 우리는 전역 숫자를 뷰 계약으로 내보내지 않는다 |

`detections` 모양 통일(통합 저장소 RFC)은 **더 결정할 것이 없다** — 우리 detections 는
이미 평평하고 `server/contracts/common/detections.schema.json` 을 그대로 통과한다.
검증은 `tests/test_server_contract_conformance.py` 가 매번 돌린다(정본 사본을
`schemas/ai/vendor/server/` 에 두고 비교).

### 2-나 관측 평면 — AI 계측 이름 접두가 등재되어 있지 않다

#### 사실

파트별 계측 이름 접두 규약이 있고(`server/docs/be/vz-observability-namespace.md` §1,
줄 56-62) 세 파트가 올라 있다 — 하드웨어 `hw.` · 백엔드 `be.` · 가시화 `vz.`.
**AI 자리는 없다.** 관측 문서는 아직 옛 패키지 이름으로 우리 자리를 적고 있다.

> `docs/deployment/observability.md:54` — "다른 파트의 지표 이름 공간(`hw.*`,
> `perception_framework.*`, 화면 자체 지표)은 각 파트 문서"

`perception_framework` 는 2026-11 재분류 이전의 우리 패키지 이름이다(지금은
`mission_runtime`). 그리고 접두로 쓰기에 길어서 `hw.`·`be.`·`vz.` 와 모양이 다르다.

#### 필요한 변경

| 항목 | 필요한 것 |
|---|---|
| 접두 등재 | `ai.` 를 §1 표에 한 줄 더한다. Prometheus 표기는 `ai_*` 가 된다 |
| 옛 이름 정정 | `docs/deployment/observability.md:54` 의 `perception_framework.*` → `ai.*` |
| 라벨 표에 AI 행 | `server/contracts/common/README.md:208-213` 의 층별 라벨 표는 A층·C층(백엔드)뿐이다. 우리 자기 관측 지표가 쓸 라벨(`component` · `outcome` · `stage`)과 장치별 지표에만 쓰는 것(`source_id` · `zone_id`)을 같은 기준으로 한 줄 더해 주면 양쪽이 같은 표를 읽는다 |
| 금지 라벨 가드 | 그쪽 어댑터(`backend/observability.py` `FORBIDDEN_LABELS`)와 **같은 목록**을 우리 쪽도 데이터로 들고 있다(`integration/deployment_topology.FORBIDDEN_METRIC_LABELS`, 19종). 목록이 늘어나면 알려 주면 된다 — 우리 시험이 그 목록을 못 박고 있다 |
| `ai/` 스냅샷 | 통합 저장소의 `ai/` 사본이 재분류 이전 배치(`ai/perception-framework/perception_framework/`)다. 미러링 시점 문제이고 우리가 급히 필요한 것은 아니지만, 그 사본을 읽고 우리 경로를 적는 문서가 생기면 두 번 어긋난다 |

`ai.` 는 답을 기다리는 동안에도 충돌을 만들지 않는다 — `hw.`·`be.`·`vz.` 중 어느
것과도 겹치지 않고(시험으로 고정), 그쪽은 `be.` 만 읽는다. 다른 접두를 원하면
이름만 알려 주면 우리 상수 한 줄과 시험이 따라간다.

---

## 3. 가시화 — 계약 결정 셋이 우리 소비를 막는다 (막힘)

가시화 쪽 작업보고(2026-10-22 「태스크 식별자 걷어내기」)가 **코드를 고치지 않고
멈춘 상태**이고, 그 결정 셋은 우리가 그 계획을 읽는 방식까지 정한다.

| 결정 | 우리에게 미치는 것 |
|---|---|
| ① `action` 을 `action-item.schema.json` 에 올리는가 | 올라오면 우리 importer 가 `action_items` 를 `unmapped` 로 흘리지 않고 환산 대상으로 받는다 |
| ② `sense` 둘·`decide` 둘을 무엇으로 가르는가 | 노드 종류만으로 못 가르는 넷이 있다. 우리는 `node_kind` 를 분기 근거로 쓰지 않으므로 지금도 돌지만, 화면이 그 넷을 구분하려면 계약에 재료가 필요하다 |
| ③ `viewpoints` 를 `mission.schema.json` 에 올리는가 | 각도 칸(스캔 8칸)을 계약으로 받을 수 있는지가 정해진다 |

우리 입장: **①-나 + ②-나 + ③ 등재**가 우리 importer 에도 유리하다(계약 밖 대본 필드에
기대지 않게 된다). 다만 셋 다 백엔드·하드웨어도 읽는 계약이라 우리가 정할 수 없다.

### 추가로 필요한 것

- **컴포넌트 디스크립터 등재**: `schemas/viz/` 에 우리 상태 소스와 컴포넌트 5종을
  그쪽 계약 형식(`component-descriptor` · `datasource`)으로 선언해 두었다. 그쪽
  파이프라인 편집기가 이 파일들을 카탈로그에 등재하면 **화면 코드 변경 없이** 우리
  상태를 그릴 수 있다. 렌더러는 내장 6종(`text`·`table`·`graph`·`image`·
  `video-stream`·`audio`)만 쓴다.
- **전역 좌표(BE-C-04 · DT-03)**: 로봇 자리를 전역 좌표로 그리는 화면은 §6 의 재합의가
  끝나야 재료를 받는다. 가시화 쪽 규칙("좌표 변환 로직을 만들지 않는다")은 그대로
  유지되고, 바뀌는 것은 그 값을 만드는 주체뿐이다.
- **`target=box`**: 10편(MSN-261027-01)이 탐지 창구에 `target=box` 로 묻는데 탐지
  클래스는 `door`·`pedestal`·`person` 셋이다. 이것은 **우리 쪽 작업**이고 §5 에 있다.

---

## 4. 전제를 맞췄다 (정보 — 그쪽이 할 일은 없다)

### 4-가 오케스트레이터·터널·업무 평면

| 사실 | 우리 쪽 반영 |
|---|---|
| 1.0 배포에서 구역 엣지는 **Kafka 에 붙지 않는다**(엣지 Mosquitto → 중앙 Mosquitto MQTT 브릿지, Kafka 는 중앙 `be-ingest` 뒤) | `integration/deployment_topology.py` 가 이 지형을 정본으로 적고, 우리 `edge/bridge.py` 는 처음부터 transport 쌍에 무관해 코드 변경이 없었다. 개발용 compose 에 Kafka 가 있는 이유를 머리글에 적어 혼동을 막았다 |
| K3s 는 **증강 워크로드 전용**, 제어평면은 엣지에만, 말단은 agent, 안전 루프는 systemd 에 두고 절대 k3s 에 넣지 않는다 | 우리 말단 배포는 systemd 유닛 한 장(`deploy/ondevice_unit/`)이고 k3s provider 는 선택이다. AI-B-11 의 "모든 실행영역이 같은 오케스트레이터를 쓴다고 전제하지 않는다"와 같은 결론 |
| 엣지↔중앙은 터널(Tailscale) 강제 | `deployment_topology.is_tunnel_or_private()` 가 중앙 접점 주소를 검사한다. 설정 실수를 잡는 검사이고 보안 장치가 아니라고 적어 두었다 |
| 사이트 환경변수는 `MK2_*` | 같은 이름을 쓰도록 상수로 고정했다(`ENV_ZONE_ID` 등) |

### 4-나 관측 평면에서 맞춘 전제 (2026-11-03)

통합 저장소 설정 파일에서 **옮겨 적고** 상수로 고정했다
(`integration/deployment_topology.py` §관측, `tests/test_deployment_topology.py`).
그쪽이 바꾸면 우리 시험이 깨진다 — 깨지지 않으면 우리는 옛 전제로 계속 질의하고
그 질의는 오류 없이 빈다.

| 사실 | 출처 | 우리 쪽 반영 |
|---|---|---|
| 엣지 Prometheus `:9090`(터널 바인딩) · Collector exporter `:8889` · Collector 자기 관측 `:8888` | `deploy/edge/{docker-compose.yml,config/prometheus.yml}` | `PORT_EDGE_METRIC_QUERY` 등. 우리 기본 질의 엔드포인트가 **엣지**를 가리킨다(실패 분석은 요약이 아니라 상세를 본다) |
| 수집 간격 global 15초, Collector exporter 잡만 5초 | `deploy/{edge,server}/config/prometheus.yml` | `MetricQueryEndpoint.step_s` 기본값을 5초로 묶었다 — 더 굵으면 표본이 있는데 건너뛴 점이 생긴다 |
| `metric_expiration: 5m` — 생산자가 멈추면 시계열이 **사라진다**(0 이 되지 않는다) | `deploy/edge/config/otel-collector.yaml:30` | 그 공백을 `NOT_SCRAPED` 로 읽는다. 반대로 "값이 보인다"가 "지금 보내고 있다"는 뜻이 아니라는 것도 시험에 적었다 |
| 보존 엣지 7일 · 중앙 15일 | `deploy/edge/.env.example:17`, `deploy/.env.example:71` | 장기 재현은 계측이 아니라 업무 저장소·아카이브 참조로 간다(AI-O-03, 원칙 #17) |
| `service.name` 은 `job` 이 아니라 **`exported_job`** 으로 들어온다 | `server/docs/be/vz-observability-namespace.md` §3 | 실물로 확인했다. 컴포넌트는 `component` 라벨로 가른다 |
| `external_labels`(`agg_layer=edge`)는 `/federate`·remote-write 에만 실린다 | 2026-11-03 실측 | 엣지 엔드포인트에 `agg_layer` 선택자를 걸면 표본 0 이다 — 중앙 질의를 그대로 가져오면 조용히 빈다 |
| 중앙 Collector 는 OTLP `4316` 과 `4317` 을 같은 수신단으로 연다 | `docs/PORTS.md:12` | 우리는 표준 번호(4317)를 쓴다. 다른 쪽 설정이 4316 이어도 틀린 것이 아니라고 적어 두었다 |
| `MK2_EDGE_BIND`(중앙이 엣지에게 여는 입구)와 `MK2_EDGE_LAN_BIND`(엣지에서 말단이 붙는 입구)는 **다른 기계**다 | `deploy/.env.example:21`, `deploy/edge/.env.example:14` | 상수 둘로 갈라 두고 시험이 섞이는 것을 막는다. 우리가 한쪽만 들고 있었던 자리다 |

**하드웨어 쪽에 확인만 부탁**: 우리는 이제 `Command.traceparent`(정본 필드 6)를
유효한 W3C traceparent 일 때만 싣는다. 말단이 그 값을 무시해도 동작은 같다(proto3)
— 받아서 trace 를 이을지는 그쪽 결정이다.

---

## 5. 우리가 이미 한 것 (확인용)

| 한 일 | 자리 |
|---|---|
| 와이어 proto 를 정본과 **필드 단위로 동일**하게(`traceparent` 포함), descriptor 바이트 일치 | `contracts/proto/`, `tests/test_physical_command_wire_alignment.py` |
| proto·JSON 사본 제거 — 정본 한 벌 + 생성용 사본 하나 | `specs/README.md` |
| `detections` 평평한 모양 + 백엔드 정본 스키마 통과 | `tests/test_server_contract_conformance.py` |
| 통합 상태 스냅샷 채널 신설(구역 B~I 한 장) | `integration/status_wire.py`, `schemas/ai/status-snapshot.schema.json` |
| 계층별 자원 실측(가속기 개체·보드) | `observability/host_resources.py` |
| 임계 초과 경고와 자원 조건을 **한 판정**에서 | `observability/resource_watch.py` |
| 가시화 파이프라인용 선언 6종 | `schemas/viz/` |
| 실제 모델·실제 자원·실제 브로커 통합 시험 | `tests/test_real_stack.py` |
| **실물 Prometheus 를 개발 스택에 세우고** 우리가 낸 계측이 Collector exporter 를 거쳐 긁혀 귀속 판정까지 가는 한 바퀴를 시험으로 돌린다(스택이 없으면 그 묶음만 skip) | `deploy/integration/{docker-compose.yml,prometheus.yml,otel-collector.yaml}`, `tests/test_real_prometheus_path.py` |
| 개발 스택의 Collector 를 그쪽 엣지와 **같은 계열(0.150)** 로 올렸다 — 0.150 에서 컴포넌트 이름이 바뀌었으므로 두 계열을 섞어 두면 우리 설정만 통과하는 조합을 못 잡는다 | `deploy/integration/docker-compose.yml` |
| 질의 **거부(4xx)** 와 **못 닿음**을 가른다. 점 구분 OTel 이름을 그대로 물으면 질의 문법에 걸리는데, 그것을 "수집기가 죽었다"로 적으면 사람이 수집기·망을 본다 — 실물에서 발견해 고쳤다 | `providers/observability_query.py` |
| 금지 라벨 선택자는 질의를 **보내지 않고** 사유를 적는다(그 라벨의 시계열은 애초에 생기지 않는다) | `providers/observability_query.py`, `integration/deployment_topology.FORBIDDEN_METRIC_LABELS` |
| 관측 평면의 포트·간격·보존·라벨·이름 변환을 상수로 고정하고 시험이 못 박는다 | `integration/deployment_topology.py` §관측, `tests/test_deployment_topology.py` |
| 사이트 IP·자격증명 공개 트리에서 분리, 시험 주소를 RFC 5737 로 | `config/*.example.json` |

### 우리 쪽 남은 일

- 탐지 창구에 `box` 클래스 추가(프롬프트·관문·임계). 임계는 기존 둘처럼 sweep 으로 정한다.
- 탐지 근거(`evidence.json`)에 **기준 해상도와 crop 규약**을 더한다. 지금 기록된
  `box_xyxy` 만으로는 `median_saturation` 이 재현되지 않는다(실측: 기록 108 vs 재측정 50).
- 색상(H) 게이트 범위(85~112)는 2026-09-15 자료로 맞춘 값이라 2026-09-10 스캔의 실제
  문(측정 127)을 탈락시킨다. 스캔별 재측정이 필요하고, 그 사실은 시험으로 고정해 두었다
  (`tests/test_real_stack.py`).

---

## 6. 전역 좌표 소유권 — BE-C-04 · DT-03 과의 재합의 요청 (막힘)

읽는 사람: 백엔드에서 좌표 변환·디지털 트윈 상태를 들고 있는 담당자, 가시화에서
로봇 자리를 그리는 담당자. **지금 당장 코드를 고칠 일은 없다** — 필요한 것은 회신
하나와, 합의했다면 그 기록이 어디 있는지다.

### 6-가 세 문서가 같은 사실의 주인을 서로 다르게 적고 있다

| 문서 | 지금 적혀 있는 것 |
|---|---|
| **BE-C-04**(백엔드 좌표 규약) | "로컬→글로벌 변환과 축 변환은 **백엔드가 단독 수행**하며 가시화는 이 배치를 받아 놓기만 한다"(가시화 대시보드 `mock-gateway/registry.json` 의 REQ-302/BE-C-04 주석). 같은 결론이 그쪽 README 에 세 번 적혀 있다 — "`BE-C-04`로 백엔드 단독 책임이 확정됐다", 봉투의 `coordinate_frame`(`"site-global"`)은 "**표시만** 한다", "이 값을 근거로 무언가를 환산하는 코드는 계약 위반이다" |
| **DT-03**(디지털 트윈 상태) | 최종 트윈 상태의 authoritative 주인을 백엔드로 적고 있다고 우리 요구사항 표가 가리킨다. 우리 쪽에 원문 사본이 없어 **문구는 인용하지 못한다** — 정확한 문장은 그쪽에서 확인해 주어야 한다 |
| **AI-C-02 · AI-C-19**(우리, 2026-11-03 개정) | 전역 좌표 변환과 최종 트윈 상태의 authoritative 소유를 **AI** 로 옮겼다. 다만 같은 요구사항이 "백엔드와의 **경계 재합의가 선행되어야 한다**"를 함께 적는다 |

소유권만 옮기면 옛 규칙이 막고 있던 실패가 없어지지 않고 **자리만 바뀐다** — "같은
사실에 authoritative 주인이 둘"이다. 그래서 우리는 개정을 근거로 숫자를 내보내지
않고 있다.

### 6-나 그래서 지금 우리가 하는 것과 하지 않는 것

- **한다**: 현장 로컬 좌표(미터)로 모든 자리를 낸다. 현장 기준점(site datum)은 출처·
  생성 시점·판·**선언된 정확도**를 가진 근거로 관리한다. 전역 계층의 상태와 사유를
  낸다(`geo.layer` · `geo.reason`).
- **하지 않는다**: 전역 좌표 **숫자**를 뷰 계약으로 내보내지 않는다. 그 사실을
  `geo.coordinates_in_view_contract: false` 와 사유 토큰
  `geo.coordinates_withheld_reason` 으로 적어 보낸다(현재 실제 현장 둘의 사유는
  `datum_unverified`, 그 다음 사유는 `boundary_not_reagreed`).
- **적지 않는다**: 없는 합의를 "있다"고 적을 길을 코드에 두지 않았다. 현장 선언의
  합의 기록은 누가·언제·어느 문서로·무엇을 대체했는지를 모두 요구하고, 하나라도
  빠지면 서버가 선언을 **거절한다**. 실제 현장 둘에는 그 기록이 **없다**.

### 6-다 합의되면 계약에 정확히 무엇이 나타나는가

모양은 이미 고정해 두었다(`docs/view-contract.md` §3.5,
`schemas/view_snapshot.schema.json` 의 `boundary_agreement` · `global_point`). 합의
뒤에 더해지는 칸은 **셋**이고, 전부 선택 칸이라 모르는 칸을 통과시키는 뷰어는 그대로
돈다.

| 어디에 | 칸 | 내용 |
|---|---|---|
| 도메인 `geo` | `boundary_agreement` | `subject`(=`global_coordinate_ownership`) · `agreed_by[]`(`ai`·`backend` 필수) · `agreed_at` · `document{name,url,section}` · `supersedes[]`(=`["BE-C-04","DT-03"]`) · `example` |
| 도메인 `geo` | `coordinates_in_view_contract` | 거짓→참으로 바뀐다. `coordinates_withheld_reason` 은 사라진다 |
| 자리 칸이 있는 모든 원소(`robots[]` · `infrastructure[]` · `access_point`) | `at_global` | `lat` · `lon` · `crs` · `verified` · `accuracy_m` · `accuracy_state` · `datum_id` · `datum_version` · `derived_from{kind,domain_id,level_id,unit}` |

로컬 칸(`at`)은 **그대로 남는다.** 전역 값은 형제 칸에 따로 붙고 같은 칸에 섞이지
않는다(AI-C-02: "로컬 값과 전역 값은 같은 칸에 담지 않는다"). `at_global` 은 재료인
datum 의 **선언된 정확도**를 함께 들고 다니므로, 받는 쪽이 전역 숫자를 그 재료인
로컬 측정보다 정확한 값으로 오해할 수 없다.

숫자가 나가는 조건은 코드 상수가 아니라 **현장 선언**이고 네 조건의 논리곱이다:
datum 이 있다 · `verified` 가 참이다 · `accuracy_m` 이 선언됐다(미측정은 0 이 아니다)
· 경계 재합의가 기록됐다. 앞의 셋은 **우리 쪽 숙제**다(현장 GNSS 실측). 넷째가 이
요청이다.

### 6-라 그쪽에 필요한 것 — 넷

1. **회신**: 전역 좌표 변환과 최종 트윈 상태의 authoritative 주인을 AI 로 옮기는 데
   동의하는가. 동의하지 않으면 그것도 답이다 — 우리는 지금 상태(로컬 값 + 상태·사유)를
   유지하고 `at_global` 은 영구히 내지 않는다. 그 경우 우리 요구사항 쪽을 되돌려야
   하므로 사유를 함께 알려 주면 좋다.
2. **BE-C-04 · DT-03 의 개정**: 동의한다면 두 문서에서 "백엔드 단독 수행"을 고쳐야
   한다. 고치지 않고 우리만 내보내면 두 계약이 같은 사실을 서로 다르게 적는 상태가
   되고, 그것이 이 요청이 막고 있는 바로 그 결과다.
3. **합의 기록의 참조**: 회의록·결정문 어디에 남았는지(이름 · URL · 절). 우리는 그것을
   현장 선언 한 블록으로 옮긴다 — 현장마다 적으므로 **현장별로** 알려 주어야 한다
   (지금 대상은 `college`(한밭대 N4) 와 `river`(하천실험센터) 둘이다). 날짜와 참여
   파트도 함께 필요하다.
4. **`coordinate_frame` 과의 관계**: 지금 백엔드 봉투에는 `coordinate_frame:
   "site-global"` 이 실린다. 전역 변환이 AI 로 넘어오면 **그 칸을 누가 채우는가**를
   함께 정해야 한다. 우리 제안: 전역 값의 생산자가 그 프레임을 적고(=AI), 백엔드는
   받은 값을 재변환하지 않는다. 가시화 쪽 규칙("표시만 한다", "환산하는 코드는 계약
   위반")은 **그대로 유지**된다 — 바뀌는 것은 그 값을 만드는 주체뿐이다.

### 6-마 왜 우리가 못 하나

소유권은 한쪽이 선언해서 옮겨지지 않는다. 우리 요구사항을 우리가 고쳤다는 사실은
그쪽 계약의 문장을 바꾸지 못하고, 두 계약이 같은 사실을 각자 권위 있게 적는 동안
숫자를 내보내면 어느 화면이 맞는지 말할 수 없게 된다. 그 상태는 틀렸다고 말해 주는
사람이 없어서 오래 살아남는다.

그 전까지 막혀 있는 일: 배경 지도 타일을 전역 좌표에 맞춰 놓는 것, 외부 지도 위에
로봇을 올리는 것, 서로 다른 현장을 한 전역 평면에서 함께 보는 것. 세 가지 다 로컬
좌표 화면으로는 대체되지 않는다.

> 선언된 경로가 어떻게 생겼는지 보려면 `profiles/domains.example.json` 의
> `logistics` 도메인을 보면 된다 — **예시 현장**이고 합의 기록도 `example: true` 로
> 표시돼 있다(예시 현장은 예시 합의만, 실제 현장은 실제 합의만 가질 수 있고 서버가
> 그 짝을 검사한다). 그 도메인에서 `GET /api/domain?id=logistics` 를 받아 보면 합의
> 뒤의 응답 모양이 그대로 나온다.

## 7. ＋ 로 들인 장치를 가시화가 받는 길

장치를 들이는 일이 우리 화면 안에서만 끝나면 확장이 아니다. 가시화 파트의
`contracts/equipment.schema.json` 이 그 사실을 직접 적는다 — **"여기 없는 것은
`assigned_targets` 에 쓸 수 없다."** 그쪽 장비 목록에 들어가지 않은 장치에는 임무를
걸 수 없다.

그래서 `POST /api/join` 이 받아들여지면 응답에 `visualisation_entry` 가 함께 나간다.
모양은 **그쪽 계약 그대로**이고, 우리 시험이 그쪽 스키마 파일로 검증한다
(`tests/test_visualisation_handoff.py`).

```json
{ "equipment_id": "rc-001", "label": null, "aliases": [],
  "kind": "rail_crawler", "zone_id": "zone-503" }
```

지키는 규칙 셋.

1. **이름을 지어내지 않는다.** 선언에 사람이 부르는 이름이 없으면 `label` 은
   `null` 이다. 장치 id 를 이름 자리에 복사해 넣으면 그쪽 화면이 그것을 사람이 지은
   이름으로 읽고, 나중에 진짜 이름이 생겨도 이미 이름이 있는 줄 알고 덮지 않는다.
   그쪽 계약의 `label` 주석이 같은 규칙을 적고 있다.
2. **모르는 역할도 넘긴다.** 역할→종류 표는 **기본값이지 관문이 아니다.** 표에 없는
   역할(`rail_crawler` 등)은 그 이름 그대로 나간다 — 표에 없다고 빠뜨리면 새 역할의
   로봇이 그쪽 목록에 영영 못 들어가 임무를 걸 수 없게 되고, 그 표가 곧 확장의
   문턱이 된다(절대 준수 #3·#7).
3. **우리가 아는 것을 더 실어 보내지 않는다.** 그쪽 계약은
   `additionalProperties: false` 다. 자원 예산도 공지 어휘도 그쪽 칸에 자리가
   없으므로 우리 계약으로 따로 나간다. 두 계약을 섞지 않는 것이 경계다(AI-C-04).

### 아직 합의가 필요한 것

지금은 **응답에 실어 보내는 데까지**다. 그 칸을 그쪽 `equipment.json` 에 넣는 일은
파일을 가진 쪽이 한다 — 우리가 그 파일을 고치면 생성 주체가 둘이 된다. 밀어 넣는
채널을 열 것인지(그렇다면 §2 의 전송 규약 위에서), 아니면 이 응답을 받아 그쪽이
반영할 것인지는 **결정이 필요하다.**

---

## 8. 지도 계층 — Unity 뷰어가 그대로 받아 그릴 수 있는 모양 (정보 + 결정 하나)

2026-11-03 에 메인 맵을 **현장 지도**로 바꿨다. 그 전에는 추상 격자 위에 도메인을
네모로 늘어놓을 뿐이라 "어디인가" 에 답하지 못했고, 실제 지도는 도메인을 한 번 열어야
나왔다. 지금은 **현장 → 층 → 구역** 세 단이고 각 단의 맵 포인트를 눌러 내려간다.

웹 콘솔(`tools/fms_console/`)은 **예시**다. 여기 적는 것은 그 화면이 아니라 Unity
뷰어가 같은 그림을 그리기 위해 읽어야 하는 **계약**이다. 전부 기존 경로이고 새 채널은
없다.

### 8-가 평면이 두 모양이라는 것부터

`GET /api/scene` 의 `space.unit` 이 둘 중 하나다.

| `unit` | 언제 | 도메인을 무엇으로 그리는가 |
|---|---|---|
| `index` | 현장 배경 그림이 없을 때 (**기본값**) | `rect` — 무차원 격자 위의 네모. 자리가 아니라 **목록**이다 |
| `meter` | 현장 배경 그림이 걸렸을 때 | `site_at` — 현장 평면 위의 **점** |

미터일 때 `space` 가 `origin`·`frame`·`datum_id`·`background_layer` 를 함께 낸다.
**`origin` 을 무시하면 안 된다** — 현장 평면의 원점은 (0,0) 이 아니라 datum 이
가리키는 점이고, 평면은 그 둘레로 음수 쪽까지 뻗는다. 0 에서 그리면 지도 한쪽이
잘린다. 이 배치의 실제 값: `origin (-277.778, -267.581)` · 615.681 m 정사각 ·
`frame: site-local`.

### 8-나 바탕 그림은 자리마다 걸리고, 자리마다 **프레임이 다르다**

```
GET /api/background                                → 현장 그림   (앵커 = 현장 로컬, 원점 = datum)
GET /api/background?domain=&level=                 → 층 도면     (앵커 = 구역 로컬)
GET /api/background?domain=&level=&zone=           → 구역 도면
```

좁은 자리가 이긴다. `scale`·`offset` 은 `px = local * scale + offset` 의 계수이고
**서버에서 한 번만** 계산한다 — 뷰어가 앵커 두 점에서 다시 계산하면 두 화면이 반올림
한 자리에서 갈린다. 그림 **바이트**는 `GET /api/media?kind=map&file=<layer_id>` 로만
나간다(AI-C-08).

**여기서 한 번 틀렸던 것을 적어 둔다.** 캠퍼스 그림의 앵커는 현장 로컬 좌표인데 선언이
그것을 도메인 scope 로 걸고 있었다. 같은 그림을 두 프레임에 깔면 한쪽 자리가 **조용히**
틀어진다 — 핀은 여전히 "건물 위" 로 보이므로 틀어진 줄 아무도 모른다. 뷰어 쪽에서도
같은 실수가 가능하므로 `scope` 를 반드시 보고 깔 자리를 정한다(AI-C-02).

### 8-다 자리는 선언이지 측량값이 아니다

`site_at` 은 공개 지도(OSM way 469892616)가 적어 둔 건물 윤곽의 중심이고 우리가 잰 값이
아니다. 그래서 `verified: false` 와 `source` 가 값과 함께 다닌다. **측량된 자리처럼
보이게 그리지 않는다**(AI-S-08). 자리를 모르는 도메인은 칸 자체가 없다 — 0 으로 채우면
지도 왼쪽 위 구석에 건물이 하나 생긴다.

같은 이유로 datum 자체가 `verified: false` 다. 이 평면 위의 모든 자리가 그만큼
미검증이고, 그 사실은 `GET /api/domain` 의 `geo` 가 말한다(§6 과 같은 뿌리다).

### 8-라 더 들어갈 수 있는 방

`GET /api/zone` 이 `interiors[]` 를 낸다 — `room_id`·`label`·`rect`(구역 로컬)·
`size_m`·`verified`, 그리고 실내 장면 **참조**인 `interior`. 지금 이 배치에는 한 건이고
그 `interior.scene` 이 **그쪽 씬**을 가리킨다(`Unity_Map/Assets/XRI/lab.unity`,
anchor `Door ↔ door-503`).

기하가 선언된 방만 들어온다. 이름만 있는 방 20 곳은 `rooms[]` 에 남고 `interiors[]` 에
들어오지 않는다 — 화면이 "들어갈 수 있다" 고 말한 자리가 실제로 열려야 하기 때문이다.

### 결정이 필요한 것 하나

**실내 씬을 누가 여는가.** 우리는 "더 들어갈 자리가 있다" 는 사실과 그 참조까지만
낸다(AI-C-19 — 표현은 가시화 몫이다). 그 참조로 `lab.unity` 를 여는 것이 그쪽 뷰어
안에서 일어나는 일인지, 아니면 우리가 방 도면 그림을 한 장 더 내주면 되는 일인지는
**그쪽 결정**이다. 후자라면 이미 있다 — `tools/profiles/draw_room_plan.py` 가 선언된
경계에서 `room-503.png`(584×704 px, 7.4 × 9.4 m)를 그려 내고 앵커 두 점을 함께
출력한다. 레이어 선언 한 줄이면 `GET /api/background?...&zone=` 으로 나간다.
