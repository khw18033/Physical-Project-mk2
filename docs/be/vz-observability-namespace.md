# 관측 지표 이름 공간 통지 — 가시화 파트

| | |
|---|---|
| 보내는 쪽 | 백엔드(BE·DT) / 이대규 |
| 받는 쪽 | 가시화(VZ) / 김현우 |
| 작성일 | 2026-09-16 |
| 근거 | Phase 3(관측 파이프라인) 구현·검증 결과(pytest 184건 전건 통과, 서버 실측) · 요구사항 정의서 **VZ-O-04**(자체 관측 지표 발행) · BE-S-02 · [`00-architecture.md`](00-architecture.md) §8-3(관측 신호 3층)·§8-4(표준 형식) · [`contracts/common/README.md`](../../contracts/common/README.md) 「관측 신호 힌트와 라벨 금지」 · HW `pi/common/otel_metrics.py`(2026-09-09 스냅샷) |
| 대상 안건 | **VZ-O-04** — 가시화가 자체 관측 지표를 같은 관측 스택에 직접 발행할 때의 **이름 공간·라벨·발신 대상** |
| 우선순위 | 🟡 — **가시화가 지표 발행을 시작하기 전**에 읽어 주면 된다. 그전엔 할 일이 없다 |

> ✅ **회신 받음 — 2026-09-17.** 원문은 [`received/2026-09-17_vz-observability-namespace-reply.md`](received/2026-09-17_vz-observability-namespace-reply.md).
> VZ가 정한 것 5: ① 접두사 `vz.` 수용(자기 문서 `viz.*` 네 곳 정정) ② 발행 주기 **60초**(VZ-O-04·HW-C-05 원문) + "HW 실제 주기 확인" 요청
> ③ **브라우저 발신 경로로 Collector OTLP/HTTP 4318 + CORS 개방 요청**("Phase 4 Tailscale·BE-T-08과 함께") ④ `service.name` = `vz-viewer`·`vz-stt`·`vz-gen`
> (Unity 트윈은 담당 미정이라 제외) ⑤ 금지 라벨에 VZ 식별자 6종 추가 제안. 로그·트레이스는 안 보내고 지표만.
> **우리 통지의 오류 하나:** §4 "주기 15초 — HW·백엔드와 같다" → HW `config.py` 기본값은 15초이나 `otel_metrics.py` 독스트링과 HW-C-05는
> **60초**(HW 코드 내부 불일치). 주기는 발신자 몫이고 Collector(batch 5s)는 어떤 주기든 받는다 — VZ 60초 OK.
> **답할 것:** 즉답 3(60초 OK · `service.name` 셋 OK · 로그/트레이스 없음 OK) · **결정 1 — 브라우저 발신 경로**(A Collector HTTP+CORS 공개 /
> B WSS 게이트웨이 중계 / C 답만 Phase 4·구현 Phase 5 — **Phase 4 결정 7에서 정한다**, 우리 §4가 tailnet 밖 브라우저를 빠뜨린 것이
> 원인) · **규격 1 — 라벨 목록 확장**(`mission_id`·`node_ref`·`client_request_id`·`plan_id`·`event_key`·발화 원문. ⚠ VZ가 적은
> `node_id`는 DAG 노드 뜻이라 `node_ref`로만 넣는다 — 우리 공통 헤더 `node_id`는 물리 노드라 저카디널리티·허용). 라벨 확장은
> `contracts/common/README.md`·`backend/observability.py FORBIDDEN_LABELS`·`tests/test_observability_labels.py`를 함께 고쳐야 하므로
> **Phase 4 구현 항목**. 답은 Phase 4 VZ 통지 문서에 절로 넣는다(문서를 따로 만들지 않는다).

---

<a id="s0"></a>

## §0 한 장 요약

**이름 공간이 겹치지 않게 미리 정한다.** 관측 스택(Collector → Prometheus·Loki·Tempo)에 지표를 내는 주체가
이제 셋이다 — 하드웨어(`hw.`), 백엔드(`be.`), 그리고 VZ-O-04가 예고한 가시화. [`00-architecture.md`](00-architecture.md)
§8-3의 3층(A 백엔드 자기 관측 / B 말단 노드 / C 업무 값의 관측 표현)에는 **가시화 자리가 없어 네 번째 생산자**가
된다. 규약이 없으면 같은 이름이 다른 뜻으로 겹치고, 나중에 분리할 수 없다.

| 우선순위 | 무엇 | 항목 |
|---|---|---|
| 🟡 **먼저** | **지표 이름 접두사 `vz.`** — `hw.`·`be.`와 같은 규칙. 표준 이름(`system.*` 등)은 접두사 없이 | [§1](#s1) |
| 🟡 **먼저** | **라벨 금지 목록 전수** — `session_id`·`internal_seq`·`sequence_id`·시각·프레임 식별자. 하나만 들어가도 시계열이 폭증한다 | [§2](#s2) |
| 🟡 곧 필요 | `service.name`을 **컴포넌트별**로 가른다(`vz-<컴포넌트>`) | [§3](#s3) |
| 🟡 곧 필요 | **발신 대상은 서버 Collector `127.0.0.1:4316`**(OTLP gRPC). Prometheus·Loki·Tempo에 직접 쓰지 않는다 | [§4](#s4) |
| ⚪ 정보 | 지금 Prometheus에 `vz_` 접두사 충돌 **0건**(실측) | [§5](#s5) |

**답이 없으면 이 기본값으로 간다:** *백엔드는 `be.`만 쓰므로 충돌은 나지 않는다. 다만 가시화가 접두사 없이
발행하면 나중에 분리가 어렵다* — 그 비용은 가시화 쪽에서 난다. 회신은 "이 규약대로 간다" 한 줄이면 충분하다.

> **이 통지가 정하지 않는 것:** 가시화가 **무엇을** 계측할지(그건 VZ-O-04의 몫). 여기서는 **이름·라벨·보내는
> 곳**만 정한다. 관측 화면을 Grafana로 할지 자체 웹으로 할지("투 트랙")도 대상이 아니다 — 백엔드는 어느 쪽이든
> 같은 신호를 낸다([`00-architecture.md`](00-architecture.md) §8-4).

---

<a id="s1"></a>

## §1 지표 이름 — 파트 접두사 규약

| 파트 | 접두사 | 상태 | 예 |
|---|---|---|---|
| 하드웨어(말단) | **`hw.`** | 기존 — `otel_metrics.py:101-104` (`hw.publish.count`·`hw.publish.duration`) | Prometheus 표기 `hw_publish_count_total` |
| 백엔드 | **`be.`** | Phase 3 신설 — A층 `be.ingest.*`·`be.kafka.*`·`be.storage.*`·`be.registry.*`·`be.gateway.*`·`be.pipeline.*`, C층 `be.telemetry.*` | `be_ingest_received_total`·`be_telemetry_water_level_m` |
| **가시화** | **`vz.`** (권고) | 이 통지 | 예: `vz.render.frame_time`·`vz.ws.reconnect` → `vz_render_frame_time_*` |
| 표준 시멘틱 | 접두사 없음 | `system.cpu.utilization`·`system.memory.utilization` 등 OTel 시멘틱 컨벤션 이름은 **그대로** | HW가 이미 이렇게 낸다(`otel_metrics.py:95-99`) |

**우리는 이렇게 읽었다:** VZ-O-04 *"자체 관측 지표 발행"* 은 가시화 프로세스(뷰어·트윈 렌더러·WS 클라이언트)의
**자기 관측(A층에 해당)**이다. 업무 값의 관측 표현(C층)은 백엔드가 `be.telemetry.*`로 이미 내고 있으므로
가시화가 **같은 값을 다시 내지 않는다**(원본은 TSDB, 관측 표현은 사본 — 두 군데서 내면 세 벌이 된다).

**규칙 셋:**

1. 이름은 **점(`.`) 구분 소문자** OTel 이름으로 낸다. Prometheus에서는 Collector가 `_`로 바꾸고 단위·`_total`을
   붙인다(`hw.publish.count` → `hw_publish_count_total`). 가시화가 `_`를 직접 넣지 않는다.
2. **단위는 OTel `unit`으로** 준다(`ms`·`s`·`By`·`1`). 이름에 단위를 넣지 않는다 — Collector가 `_milliseconds`·
   `_seconds`·`_bytes` 접미사를 붙인다. ⚠ gauge에 `unit="1"`을 주면 `_ratio`가 붙는다(`system_cpu_utilization_ratio`).
3. **counter는 단조 증가만**(재기동하면 0부터 — 조회는 `rate()`/`increase()`), 오르내리는 값(접속 수 등)은
   UpDownCounter, 마지막 값은 gauge. 백엔드 어댑터가 같은 구분을 쓴다(`backend/observability.py`).

---

<a id="s2"></a>

## §2 라벨 — 금지 목록 전수와 이유

**라벨(속성)은 값의 종류가 한정된 것만 쓴다.** Prometheus는 라벨 값의 조합마다 시계열을 하나씩 만들므로, 값이
계속 달라지는 것을 라벨에 넣으면 시계열이 **무한히 늘어난다**(메모리·디스크·조회 전부 무너진다).

| ⛔ 금지 라벨 | 왜 |
|---|---|
| `session_id` | **재기동마다 새 값** — 노드를 껐다 켤 때마다 시계열이 영구히 하나씩 는다 |
| `sequence_id` · `internal_seq` | 메시지마다 다르다 — 표본 수만큼 시계열이 는다(로봇 `internal_seq`는 50Hz) |
| 시각(`timestamp`·`ts`·`capture_timestamp` 등) | 값이 매번 다르다. 시각은 표본의 타임스탬프이지 라벨이 아니다 |
| 프레임 식별자(`frame_id`·`frame_ref` 등) | 프레임마다 다르다 |
| `command_id`·`correlation_id` | 명령마다 다르다 — trace 속성으로는 되지만 **metric 라벨로는 안 된다** |

백엔드는 이 목록을 **코드로 막는다** — 어댑터가 금지 라벨을 받으면 `ValueError`로 거부한다(`backend/observability.py`
`FORBIDDEN_LABELS`, 테스트 `tests/test_observability_labels.py`). 조용히 버리면 나중에 누가 넣어도 아무도
모르기 때문이다. 가시화도 같은 방식(발신 전 검사)을 권한다.

**허용 라벨의 예** — 값의 종류가 한정된 것: `component`(컴포넌트 이름) · `outcome`(`ok`/`fail`) · `channel` ·
`zone_id` · `source_id`(장치별 지표에만 — 장치 수만큼 시계열이 곱해지므로 **자기 관측 지표에는 넣지 않는다**).
백엔드는 A층(자기 관측)에 `source_id`를 금지하고 C층(업무 값)에만 허용한다 — 층에 따라 기준이 다르다.

---

<a id="s3"></a>

## §3 `service.name` — 컴포넌트별로 가른다

resource 속성 `service.name`이 Loki에서 `service_name` 라벨, Tempo에서 `service.name` 태그가 되어 **누가 낸
신호인지**를 가르는 첫 축이다. 고정값 하나로 두면 모든 컴포넌트가 한 이름으로 뭉친다 — HW가 실제로 겪었다
(`otel_metrics.py:63-64` 주석: *"고정값이면 로봇 지표까지 hw-sensor-node로 들어온다"*).

| 파트 | `service.name` | `service.namespace` |
|---|---|---|
| 하드웨어 | `hw-{entity_type}-node` (`hw-sensor-node`·`hw-robot-node`·…) | — |
| 백엔드 | `be-ingest` · `be-storage` · `be-gateway` | `mk2` |
| **가시화(권고)** | **`vz-<컴포넌트>`** — 예: `vz-viewer`·`vz-twin`·`vz-console` | `mk2` |

> ⚠ **Prometheus에서 `service.name`은 `job`이 아니라 `exported_job`으로 보인다.** Collector의 prometheus exporter가
> `service.name`을 `job` 라벨로 내보내는데, 스크레이프 잡에 `honor_labels`가 없어 Prometheus가 `exported_job`으로
> 바꾼다(`exported_job="mk2/be-ingest"` 식으로 namespace가 앞에 붙는다). **지표에서 컴포넌트를 가르려면 `component`
> 같은 라벨을 직접 붙이는 편이 안전하다** — 백엔드는 그래서 A층 전 지표에 `component`를 단다. Loki·Tempo는 다르다 —
> `service_name`/`service.name`이 그대로 색인된다.

---

<a id="s4"></a>

## §4 발신 대상 — 서버 Collector, 저장소 직접 쓰기 금지

| 무엇 | 값 |
|---|---|
| 프로토콜 | **OTLP gRPC** (Collector receiver가 gRPC만 연다 — HTTP 4318은 열려 있지 않다) |
| 주소 | **`127.0.0.1:4316`** — 가시화 프로세스가 서버 안에서 돌 때. 서버 밖(다른 호스트)이면 Phase 4에서 Tailscale 인터페이스에 열리는 `<서버 tailscale IP>:4316`(TLS·인증은 BE-T-08) |
| 세 신호 | metric·log·trace 셋 다 같은 주소로. Collector가 metric→Prometheus(8889 scrape)·log→Loki·trace→Tempo로 분배한다 |
| 하지 말 것 | **Prometheus(7861)·Loki(3100)·Tempo(4317)에 직접 쓰지 않는다.** Collector를 거쳐야 저장소가 바뀌어도 발신 코드가 안 바뀐다([`00-architecture.md`](00-architecture.md) §6-3). Tempo 4317이 열려 있지만 그것은 Phase 0 유물이며 입구가 아니다 |
| 주기 | metric export **15초**(HW·백엔드와 같음) |
| 장애 시 | Collector가 죽어도 가시화가 멈추면 안 된다 — SDK가 없거나 주소가 비어 있으면 **no-op**으로 떨어지는 규율(HW `otel_metrics.create()`·백엔드 `observability.setup()`과 같다). 관측은 업무의 전제조건이 아니다 |

---

<a id="s5"></a>

## §5 실측 근거

- 2026-09-14 서버 Prometheus 지표 이름 326종 중 `vz_`·`be_`·`hw_`·`mk2_` 접두사 **전부 0건** — 지금은 빈 이름 공간이다.
  Phase 3 이후 `be_*`가 21종(A층 9 + C층 12) 들어왔고 `hw_*`는 검증용 가짜 발신으로만 들어왔다 뺐다.
- 백엔드 라벨 가드 음성 대조: `tests/test_observability_labels.py` 45건(금지 라벨 7종 × 계기, A층 `source_id` 거부 27건) 통과.
- HW 접두사·resource 규약: `pi/common/otel_metrics.py:62-71`(resource)·`:95-104`(이름).

---

## 가시화가 할 일

1. 🟡 자체 지표 이름을 **`vz.`** 로 시작하고, 표준 이름은 그대로 둔다(§1).
2. 🟡 §2 금지 라벨을 발신 전 검사로 막는다. `source_id`는 장치별 지표에만.
3. 🟡 `service.name`을 컴포넌트별 `vz-<컴포넌트>`로, `service.namespace=mk2`(§3).
4. 🟡 발신 대상은 서버 Collector(OTLP gRPC `127.0.0.1:4316`). 저장소 직접 쓰기 금지, Collector 장애 시 no-op(§4).
5. ⚪ 회신은 "이대로 간다" 한 줄. 다른 접두사·라벨이 필요하면 항목 이름과 이유를 적어 달라 —
   [`contracts/common/README.md`](../../contracts/common/README.md) 「관측 신호 힌트와 라벨 금지」에 반영한다.

**답이 늦어도 백엔드는 멈추지 않는다.** 백엔드는 `be.`만 쓰고 가시화 지표를 읽지 않으므로 가시화 발행 시점까지
아무것도 달라지지 않는다.
