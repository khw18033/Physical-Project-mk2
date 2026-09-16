# 작업 지시서 — Phase 3 관측 파이프라인 완성

## 1. 머리말

| | |
|---|---|
| **대상** | Phase 3 — 관측 파이프라인 완성 (시스템 자기 관측이 업무 데이터와 분리된 평면으로 흐른다) |
| **착수** | Phase 2(저장 축) 종료 이후. 착수 결정 7개는 설계 세션(2026-09-14)에서 전부 확정됨 |
| **근거 문서** | [`docs/be/01-standalone-implementation-plan.md`](../01-standalone-implementation-plan.md) Phase 3 절 · [`docs/be/00-architecture.md`](../00-architecture.md) §8-3(관측 신호의 범위 3층)·§8-4(관측 표준)·§5-3(log·trace 원본 전달)·§6-3(서버 Collector→Loki·Tempo)·§8-5(유예 항목) · [`docs/be/requirement-traceability.md`](../requirement-traceability.md) BE-S-02·S-03·S-06·S-07 · [`infra/README.md`](../../../infra/README.md) §3·§6 · [`reports/2026-09-10_2200_phase2_저장축.md`](../../../reports/2026-09-10_2200_phase2_저장축.md) |
| **선행 보고** | [`reports/2026-09-04_1620_phase0_인프라기동.md`](../../../reports/2026-09-04_1620_phase0_인프라기동.md)(Phase 0 이월 4건의 뿌리) · [`reports/2026-09-07_1300_phase1_얇은파이프라인관통.md`](../../../reports/2026-09-07_1300_phase1_얇은파이프라인관통.md)(A층이 손으로 세던 값) |

> 이 문서는 VS Code Claude Code가 읽고 구현하는 인수인계 문서다. `CLAUDE.md`와 이 지시서를
> 함께 읽고, **지시서 범위대로 구현한다. 설계는 끝났으므로 새로 설계하지 않는다.**

---

## 2. 배경

Phase 2가 저장 축을 세우면서 **관측은 일부러 비워 두었다.** 채널 본문 규격 6종에 신호 종류
힌트(`$comment`)만 달아 두고 계측하지 않았다. Phase 3은 그 힌트를 실제 계측으로 바꾸고,
Phase 0이 남긴 서버 관측 스택의 gap을 정리한다.

**딛고 서는 것:** 가동 중인 관측 5개(Collector·Prometheus·Loki·Tempo·Grafana) · Phase 1이
확정한 토픽 규약과 3채널 · Phase 2가 확정한 본문 규격 6종과 `$comment` 힌트 · TimescaleDB의
`telemetry.lag_s`(BE-S-07 측정 재료) · pytest **104건 전건 통과** 기준선.

**이 Phase가 메우는 구멍 셋:**

1. **백엔드 자신을 관측하는 A층이 전무하다.** 그래서 값이 안 보일 때 *"장치가 안 보내는 것"*과
   *"백엔드가 못 받는 것"*을 구분할 수 없다(`00-architecture.md` §8-3).
2. **관측 3종이 Collector를 안 거친다.** Tempo가 OTLP 4317을 직접 받고 Loki는 Collector에
   exporter가 없어 직접 수신 구조다. metric만 Collector→Prometheus로 간다.
3. **추적을 만드는 주체가 없다.** Tempo가 스택에 있고 `00-architecture.md` §5-3·§6-3·§6-5가 trace를 계속 전제하는데
   그것을 생산하는 쪽이 문서 어디에도 없었다.

**⚠ 관측 스택은 「기존 가동」과 「MK2 신설」이 섞여 있다.** Phase 3은 **기존 가동 자산의 설정을
처음으로 고치는 Phase**다. 제약 2의 분류표를 먼저 읽고, 분류 ②를 건드릴 때마다 근거를 남긴다.

---

## 3. 제약 — 반드시 지킬 것

### 3-1. CLAUDE.md 절대 원칙 중 이 작업에 걸리는 것

1. **원칙 4 — 성격별 저장 분리.** 업무 데이터의 **원본은 TSDB·MySQL이고, 같은 값의 관측 표현은
   파생이다.** C층이 원본을 대체하지 않는다. 조회·감사·학습 재료를 관측 저장소에서 끌어오지 않는다.
2. **원칙 11 — Kafka는 장기 저장소가 아니다.** 이번에 거는 보존은 **관측 저장소**(Loki·Tempo·
   Prometheus)의 것이다. 업무 데이터 보존(TSDB, BE-S-04)과 **다른 사안**이며 이번 범위가 아니다.
3. **원칙 9 — 규격의 기준은 JSON Schema다.** C층 대상 목록을 파이썬에 다시 적지 않는다.
   `contracts/common/payload/*.schema.json`의 `$comment`가 기준이다.
4. **원칙 1 — 특정 기술을 핵심에 하드코딩하지 않는다.** OTel SDK 호출은 관측 어댑터 뒤에 두고,
   `bridge.py`·`consumer.py`·`ws_echo.py`가 `opentelemetry` 패키지를 직접 import하지 않는다.
5. **원칙 2 — 명령과 영상은 관측 평면에 싣지 않는다.**
6. **원칙 6 — 치명 오류·장치 생사를 일반 metric 요약에 섞지 않는다.** 페더레이션 `match[]`가
   그 둘을 요약에 뭉개지 않는지 확인한다.
7. **원칙 14 — 부하를 구역 수에 비례하게 유지한다.** 엣지 raw를 중앙으로 끌어오지 않는다.

### 3-2. 이 작업 고유 제약

8. **서버 자원을 두 가지로 분류하고, 분류 ②를 건드릴 때마다 근거를 남긴다.**

   | 분류 | 무엇 | 이번 Phase에서 |
   |---|---|---|
   | **① MK2가 만든 것** | Kafka `capstone_kafka` · TimescaleDB `capstone_timescaledb` · MySQL 안의 `mk2` DB·`mk2_app`·테이블 8 · 토픽 `mk2.telemetry.*` · 컨슈머 그룹 `mk2-*` · 백엔드 상주 3개 | 자유롭게 고친다 |
   | **② 기존 가동 + MK2가 역할만 배정(공유)** | **OTel Collector · Prometheus · Loki · Tempo** · Grafana · Mosquitto | **고치기 전에 "지금 누가 쓰나"를 실측으로 확인하고 근거를 남긴다** |
   | **③ MK2와 무관** | Redis · MongoDB · `rpi_pushgateway` · `thermal_pushgateway` · `robot_server` 타깃 · `conntest`(출처 미상) · MySQL 컨테이너 자체(`robot_capstone`) | **설정 무변경.** 읽기만 |

   "서버에 떠 있으니 쓴다"로 가지 않는다. 역할은 기준 문서가 먼저 정했고 Phase 0이 이미 있던
   컨테이너를 그 역할에 대응시킨 것이다.

9. **서버에 도는 것을 지웠다 다시 깔지 않는다.** `docker compose up -d`·`restart`에 **반드시
   서비스 이름을 명시**한다. 이름 없이 실행하면 `:latest` 태그를 쓰는 다른 파트 서비스가
   재생성될 수 있다. 현재 컨테이너는 **13개**다.
10. **설정 파일을 고치기 전에 백업한다.** `cp <파일> <파일>.bak_before_phase3`. 방화벽·네트워크·
    저장소 설정은 **반드시 원본 백업에서 작업**하고 기억으로 재구성하지 않는다.
11. **이미지는 digest로 고정한다.** `:latest`는 이동 태그라 같은 이름으로 내용이 바뀐다
    (Phase 2가 TimescaleDB에 적용한 규칙과 같다). 주석에 버전을 병기한다.
12. **서비스의 외부 포트는 ufw에도 반드시 연다.** 9100을 ufw에 열자마자 Prometheus 수집이
    정상화된 실측이 근거다(`infra/README.md` §5 정정). 바인딩(노출 통제)과 ufw(장애 원인 배제)는
    층이 다르며 **둘 다 한다.**
13. **비밀값·내부망 IP·Tailscale 주소를 커밋하지 않는다.** 이 저장소는 Public이다. 서버 상태
    조회 결과는 `_serverinfo/`(gitignore)에 둔다.
14. **편집은 컴퓨터, 실행은 사람이 서버에서.** Claude Code는 서버에 붙지 않고, 서버 파일을 직접
    고치지 않는다. **명령을 제시해 결과를 받아 반영한다.** 서버 상태·명령 결과를 추측하거나
    지어내지 않는다(`CLAUDE.md` §1-A 규율 2·3).
15. **상주 프로세스는 터미널을 나눠 지시한다.** 한 코드블록에 여러 줄로 적으면 첫 줄만 실행된다
    (Phase 2 사고 ③). **터미널 1/2/3/4로 명시**한다.
16. **테스트 없는 완료 금지.** pytest **104건이 계속 통과**해야 하고, 신규 항목에는 **음성 대조**를
    붙인다. "지표가 나온다"만 보는 판정은 무력하다.
17. **용어.** 산문에서 "계약" 대신 **공통 규격**, "봉투" 대신 **공통 헤더**, 문서를 가리키는
    "정본" 대신 **기준 문서**를 쓴다. 코드·규격 파일·경로·필드명
    (`contracts/common/message.schema.json`·`schema_version`·`source_id` 등)은 그대로 쓴다.
18. **UTF-8 · LF.** 배포 대상이 리눅스다. CRLF 금지.
19. **Phase 1·2가 확정한 것을 다시 설계하지 않는다** — 공통 헤더 규격, 토픽 규약
    `mk2.telemetry.<채널>`, Kafka advertised `localhost`, `store()` 인터페이스, 계측 저장의
    스트림 좌표 유일 키, 시각 축은 발행 `timestamp`, UTC 저장.
20. **관측이 업무의 전제조건이 아니다.** 관측 SDK 미설치·엔드포인트 미설정·저장소 장애에서
    **조용히 no-op으로 떨어지고 업무 경로는 계속 돈다.** HW `otel_metrics.py`·`otel_trace.py`가
    같은 규율을 쓰며, AI 파트 요구사항이 *"외부 관측 기능 장애가 실제 기능 실행을 중단시키지
    않아야 한다"*를 요구한다.

---

## 4. 먼저 읽을 것

| 무엇 | 왜 |
|---|---|
| `CLAUDE.md` §1(절대 원칙)·§1-A(구현 규율)·§2(금지)·§4(작업 방식) | 이 지시서가 그 위에 선다 |
| `docs/be/00-architecture.md` **§8-3** | 관측 3층(A·B·C)의 정의와 C층 제약 셋. **이번 Phase의 출발점** |
| 〃 §8-4 · §5-3 · §6-3 | 관측 표준 유지 · log·trace 원본 전달 · Collector가 분배 |
| 〃 **§8-5** | 유예 항목 표. "이번에 하지 않는 것"의 근거 |
| `docs/be/01-standalone-implementation-plan.md` Phase 3 절 | 이번 임무의 명세. **Phase 0 이월 4건 + Phase 2 이월 4건**이 그 안에 있다 |
| `docs/be/requirement-traceability.md` BE-S-02·S-03·S-06·S-07 | 각 행의 **gap 칸**에 무엇이 왜 남아 있는지가 적혀 있다. 끝에서 이 파일을 갱신한다 |
| `infra/README.md` §2·§3·§4·§6 | 스택 현재 상태·포트·헬스·알려진 사항. **§6이 거의 전부 Phase 3 항목** |
| `contracts/common/README.md` 「관측 신호 힌트와 라벨 금지」 | **C층 대상과 라벨 금지 목록의 출처.** 단 이 절의 표는 부분 목록이다(§10-2 정정 대상) |
| `contracts/common/payload/*.schema.json` 6종 | **C층 대상의 기준.** `$comment`의 신호 종류 힌트를 그대로 읽는다 |
| `backend/ingest/bridge.py` · `envelope.py` | A층 수신·1단/2단 거부·produce 실패를 꽂을 자리 |
| `backend/storage/consumer.py` · `tsdb_writer.py` · `registry.py` | 소비 건수·구간 지연·적재 실패·갱신 실패. **C층 파생 지점도 여기** |
| `backend/gateway/ws_echo.py` | push 건수·접속 수 |
| `backend/settings.py` | 환경변수 표. 관측 환경변수가 붙을 자리 |
| `tests/conftest.py` | Phase 2가 만든 skip fixture 패턴. A층 테스트가 같은 방식을 쓴다 |
| `pyproject.toml` | 주석에 *"관측 SDK·미디어는 그 Phase에서 추가한다"*가 있다. **여기가 그 Phase다** |
| `_hwsrc/upstream_260909/pi/common/otel_metrics.py` | **B층 실물.** metric 5종·resource 속성·no-op 규율. A층 이름 규약이 이것과 짝을 이룬다 |
| 〃 `otel_trace.py` | HW가 추적 문맥을 어떻게 이어받는지(결정 7의 근거) |
| 〃 `docs/BACKEND_AGENDA.md` **§10-3** | 회신할 질문 원문 |
| 〃 `docs/EDGE_SETUP.md` §1·§4-1·§5·§6 | 엣지 현재 상태(철수됨)와 말단 경량 실행 경계 |
| `docs/be/hw-envelope-conformance.md` §5·§6 | §5가 *"§10-3은 Phase 3 이후 회신"*으로 약속해 둔 것. **§7로 갚는다.** §6이 회신 규율의 실례 |

---

## 5. 착수 전 확정 사항 — 설계 세션에서 닫은 결정 7개

**이 표가 이 지시서의 척추다. 여기서 벗어나는 구현은 재작업이다.**

| # | 결정 | 확정 내용 | 근거 |
|---|---|---|---|
| **1** | 상주 프로세스 기동 | **systemd unit 3개** — `mk2-ingest` · `mk2-storage-consumer` · `mk2-ws-echo`. `User=dg` · `Restart=on-failure` + `StartLimitBurst=3` + `StartLimitIntervalSec=60` · **`enable`(부팅 자동 기동)** · `EnvironmentFile=/home/dg/capstone-db/.env` · `WorkingDirectory`=저장소 루트 · venv 절대경로 · `After=docker.service` | A층은 이 셋이 상시 떠 있어야 계측이 나온다. 단계 0 실측에서 **셋 다 죽어 있었다**(sink 마지막 기록 9-10 13:17) |
| **2** | Collector 파이프라인·포트 | **호스트 포트 무변경**(Collector `127.0.0.1:4316`, Tempo `4317`). traces → **`otlp_grpc`** → `tempo:4317`(도커 네트워크 안). logs → **`otlp_http`** → `http://loki:3100/otlp`. metrics 현행 + **`batch`**. receiver는 **gRPC만**. **이미지 digest 고정** | 컨테이너 안 포트는 서로 겹치지 않고(둘 다 4317을 듣는다), Collector→Tempo는 호스트 포트를 거치지 않는다. **포트 재배치는 파이프라인 신설의 선행 조건이 아니다** |
| **3-a** | Prometheus 수집 주기 | **global 무변경**(`scrape_interval: 1s` · `scrape_timeout: 1s`). **`otel_collector` 잡에만 `scrape_interval: 5s`** | 사용자 결정. 백엔드 export가 15초라 5초면 한 주기당 표본 3개가 들어와 주기가 미끄러지지 않는다. `rpi`·`thermal`이 이미 5초라 파일이 한 결로 정리된다 |
| **3-b** | Prometheus 보존 | **무변경**(CLI 기본값 `15d`). `infra/README.md` §6에 *"기본값에 기대고 있다"*고 **기록만** | 보존은 `prometheus.yml`이 아니라 compose `command:` 플래그라 **컨테이너 재생성**이 따라온다. 기준 문서가 값을 규정하지 않았다 |
| **3-c** | Loki 보존·스키마 | **`loki_data`를 백업 후 비우고 v13/tsdb 단일 스키마로 시작.** `retention_period: 14d` · `retention_enabled: true` · `delete_request_store` 지정 · `tsdb_shipper` 설정 · compactor 동반 · **`allow_structured_metadata: true`** | boltdb-shipper는 구조화 메타데이터도 네이티브 OTLP 수집도 지원하지 않고 둘 다 tsdb를 요구한다. 기존 데이터는 **7개월 전·172K·단일 스트림**이라 버리는 값이 사실상 0 |
| **3-d** | Tempo 보존 | `block_retention: 24h` → **`168h`(7일)** | 24시간이면 Phase 6에서 *"어제 그 명령"*을 못 본다. trace는 명령 경로에만 붙어 양이 적다 |
| **4-a** | 지표 이름 공간 | 파트 접두사 — `hw.`(기존) / **`be.`(신설)** / `vz.`(가시화 권고). 표준 이름(`system.*`)은 그대로. **`service.name`은 컴포넌트별** — `be-ingest`·`be-storage`·`be-gateway` | HW가 이미 `hw.`를 쓴다. 실측 확인: `be_`·`hw_`·`vz_`·`mk2_` **충돌 0**. HW가 `service.name` 고정값 때문에 로봇 지표까지 sensor로 들어오던 문제를 고친 것과 같은 이유 |
| **4-b** | 라벨 | **A층: `component`·`channel`·`outcome`·`stage` — `source_id`를 쓰지 않는다.** C층: `source_id`·`zone_id`·`entity_type`·`channel`. 금지: `session_id`·`internal_seq`·`sequence_id`·시각·프레임 식별자 | A층의 질문은 *"백엔드가 잘 도는가"*라 장치별로 가를 필요가 없고, `source_id`를 달면 장치 수만큼 시계열이 곱해진다. C층은 장치별이어야 의미가 있다 |
| **4-c** | 로그 경로 | **OTel Logs SDK → OTLP → Collector → Loki.** journald는 운영자용으로 병존 | systemd로 올리면 stdout이 journald로 간다. Collector는 컨테이너라 호스트 journald를 못 읽는다. 지표와 같은 경로·같은 resource 속성을 쓰면 Grafana에서 같은 주체로 묶인다 |
| **5-a** | C층 파생 지점 | **저장 소비자(`consumer.py`) 안.** 새 소비자·새 컨슈머 그룹을 만들지 않는다(레지스트리와 같은 방식). 조건 둘 — 파생 실패가 저장을 막지 않고, **저장 성공 여부와 무관하게 파생** | `tsdb_writer._fail()`이 예외를 삼키고 계속 도는 것을 코드로 확인했다. **TSDB가 죽어도 소비는 계속되므로 C층은 계속 나온다.** ingest에서 파생하면 produce 실패 시 원본과 어긋난다 |
| **5-b** | C층 범위 | `$comment` 전수 **22개를 대상으로 확정**하되, 이번 Phase는 **gauge 9 + counter 3 = 12개**를 계측. **log/event 10개는 Phase 5 이월** | log/event 10개는 전부 상태 어휘이고 *"언제 바뀌었나"*가 의미의 전부다. 그 판정이 Phase 5(가용성)의 일이다. 지금 그대로 내면 **로봇 1대당 초당 60줄**이 Loki로 간다(임무 중 20Hz × 항목 3) |
| **6** | 엣지 2계층 | **컴퓨터를 엣지로 쓴다**(서버 안 임시 컨테이너 아님). **Tailscale**로 연결. **엣지 Collector(Agent) + 엣지 Prometheus 둘 다.** 실행 파일 2개, Docker 없음. **DoD 원문 유지.** **8-D 포함** — 엣지 log·trace 원본을 서버 Collector로 넘겨 Agent→Gateway 사슬을 닫는다 | 서버 안에서 자기 자신을 긁는 것은 2계층이 아니라 네트워크 경로·구역 비례가 검증되지 않는다. 컴퓨터가 Wi-Fi 사설망(`192.168.50.203`)이라 직접 도달 불가, 공유기 포워딩 불가, sshd는 `gatewayports no`. **Tailscale은 Phase 4 자산을 앞당겨 쓰는 것**이고 sshd를 건드리지 않는다 |
| **7** | traceparent 회신 | **싣는다.** protobuf **본문에 `traceparent` 필드**(W3C Trace Context 형식). `tracestate`는 넣지 않는다. **실배선은 Phase 6**, 이번엔 회신 초안만 | HW `otel_trace.py`가 `extract(carrier=cmd)`로 **본문에서 찾도록 이미 짜 뒀다.** 명령은 백엔드가 만드는 메시지라 *"원본 무손상"*의 대상이 아니다(Phase 2가 Kafka 헤더를 쓴 이유가 여기엔 없다) |

### 5-A. 결정 7에 딸린 주의 — protobuf는 필드를 "그냥 추가"할 수 없다

protobuf는 미리 약속한 틀(`.proto`)에 맞춰 이진으로 싣는다. **틀에 없는 값은 넣을 자리 자체가
없다.** JSON처럼 키 하나를 더 얹는 것과 다르다. 따라서 HW 작업량은 **"코드 변경 없음"이 아니다**:

- `.proto`에 `traceparent` 필드 **1개 추가**(양쪽 파트가 같은 틀을 공유해야 한다)
- HW의 `extract(carrier=cmd)`는 **dict**를 전제한다. protobuf 객체에서 값을 꺼내 dict로 넘기는
  **배선 한 줄이 필요할 수 있다** — 이건 HW가 확인할 사안이다
- **옛 말단이 새 필드가 붙은 명령을 받아도 깨지지 않는지**를 HW에 확인 요청한다

`.proto`는 Phase 6에서 **문자열/열거형 파라미터 추가**(`BACKEND_AGENDA` §3 — `set_mode(mode="normal")`이
`map<string,double>`이라 지금 못 부른다) 때문에 어차피 한 번 고친다. **같은 개정에서 함께 넣는다.**

---

## 6. 이미 확인된 서버 상태 (2026-09-14 실측)

**아래는 설계 세션이 서버에서 직접 받은 결과다.** 단계 0은 이 표와 실제가 같은지만 대조한다.
**추측이 아니라 실측이며, 어긋나면 서버 쪽이 기준이다.**

### 6-1. 컨테이너·포트

| 항목 | 실측 |
|---|---|
| 컨테이너 | **13개.** 관측 5개 전부 `Up 10 days`, TimescaleDB `Up 4 days (healthy)`, Kafka `Up 10 days (healthy)` |
| Collector | `capstone_otel_collector` · `127.0.0.1:4316→4317` · 4318·55679는 **호스트에 공개 안 됨** · **v0.150.1** |
| Tempo | `capstone_tempo` · `0.0.0.0:4317→4317` · `0.0.0.0:3200→3200` · **4318은 호스트에 공개 안 됨** |
| Loki | `capstone_loki` · `0.0.0.0:3100→3100` · **v3.6.3** |
| Prometheus | `capstone_prometheus` · `0.0.0.0:7861→9090` · **v3.9.1** |
| Grafana | `capstone_grafana` · `0.0.0.0:7862→3000` |
| 이미지 digest | Collector `otel/opentelemetry-collector-contrib@sha256:7087dcbbba9c9f5c919a86c1a1cf2aa483bb585a3efa10ddb4e74cb0c4ca03eb`<br>Prometheus `prom/prometheus@sha256:b5a5ad001253b37e72eb2a264c95e57ff60bb0fe45f9a110a7c3b269e0889112` |
| 설정 파일 md5 | `otel-collector-config.yaml` `f1aad0ec6295248339491dcbc64ad38c` · `loki-config.yaml` `678fd90037fc3ee09ad2761e3257e8f6` · `tempo-config.yaml` `eb6d50cf6cfaa3805ae2abcd2cae3e82` |

### 6-2. ⚠ 관측 3종 중 **둘은 아무것도 담고 있지 않다**

**이것이 이번 Phase의 가장 중요한 실측이다.** compose 주석이 말하는 생산자들이 실제로는 보내고
있지 않다. **"떠 있다"와 "흐른다"는 다르다.**

| 저장소 | 실측 | 뜻 |
|---|---|---|
| **Collector** | `job="otel_collector"`로 들어온 지표 이름이 **5종뿐이고 전부 스크레이프 메타**(`up`·`scrape_duration_seconds`·`scrape_samples_scraped`·`scrape_samples_post_metric_relabeling`·`scrape_series_added`). `service_name` 라벨값 `[]`. 4316·4317에 **붙어 있는 TCP 연결 0** | 8889 엔드포인트가 비어 있다. **2026-09-03 11:02 재기동 이후 10일간 OTLP 수신 0건.** compose 주석의 *"otel_data 라이브러리에서는 localhost:4316으로 전송합니다"*는 **지금 일어나고 있지 않다** |
| **Tempo** | `blocks/`에 `tempo_cluster_seed.json` 하나. `service.name` 태그값 `{"tagValues":[]}`. 로그는 5분마다 blocklist poll뿐 | **trace 0건.** compose 주석의 *"파이썬 서버가 데이터 보내는 문"*이 누구인지는 **확인되지 않았다**(주석의 주장이며 실측이 아니다) |
| **Loki** | 29일 창 라벨 질의가 `{"status":"success"}`만 반환(= 스트림 0). chunk 파일 **23개 / 172K**, 테넌트 `fake`, **단일 스트림 지문 `3413e3ccb9ab137d`**, 시간 범위 **2026-01-26 ~ 2026-02-09** | **7개월간 새 로그 0건** |
| **Prometheus** | `prometheus_data` **950M**, `numSeries` **1,215**, 지표 **326종** | **유일하게 살아 있다. 그리고 그 데이터는 전부 분류 ③의 것이다** |

### 6-3. Prometheus 타깃과 설정

| job | scrapeUrl | health | interval |
|---|---|---|---|
| `otel_collector` | `http://otel-collector:8889/metrics` | up | **1s**(global) |
| `prometheus` | `http://localhost:9090/metrics` | up | 1s(global) |
| `robot_server` | `http://host.docker.internal:8000/metrics` | **down** | 1s(global) |
| `rpi_pushgateway` | `http://host.docker.internal:9100/metrics` | up | **5s**(잡별) |
| `thermal_pushgateway` | `http://host.docker.internal:9101/metrics` | up | **5s**(잡별) |

- 적재된 설정: `global.scrape_interval: 1s` · **`global.scrape_timeout: 1s`** · `evaluation_interval: 1m`
- 보존 플래그: **`storage.tsdb.retention.time: 15d`**(CLI 기본값, compose에 플래그 없음) · `retention.size: 0B`
- **`job` 라벨은 8종이고 그중 셋(`rpi`·`thermal`·`conntest`)은 scrape 잡이 아니다** —
  `honor_labels: true`라 밀어 넣은 쪽의 라벨이 보존된다. 실제로 밀려 들어온 업무·장치 지표는
  14종(`rpi_*` 10 · `thermal_temp_celsius` · `conntest` · `push_time_seconds` · `push_failure_time_seconds`)
- **접두사 충돌 0** — `be_`·`hw_`·`vz_`·`mk2_` 전부 빈 목록

> ⚠ **`scrape_timeout` 함정.** Prometheus는 `scrape_timeout > scrape_interval`인 잡이 하나라도
> 있으면 **설정 적재를 거부**한다. `rpi`·`thermal`은 잡별 `5s`에 timeout은 global `1s`를 상속하므로,
> **global timeout을 5초 넘게 올리면 그 둘이 걸려 설정 전체가 거부된다.** 결정 3-a가 global을
> 건드리지 않는 이유 중 하나다.

### 6-4. Loki 설정 (결정 3-c의 출발점)

```
schema: v11  ·  store: boltdb-shipper  ·  object_store: filesystem
compactor.retention_enabled: false  ·  retention_period: 0s  ·  delete_request_store: ""
allow_structured_metadata: false   ← 파일에 명시. 주석 사유: "v11 스키마를 쓰기 위한 호환성 설정"
```

**"보존 설정이 없다"가 아니라 "보존을 집행할 기능이 꺼져 있다"가 정확하다.** 세 줄이 함께
꺼져 있고, 하나만 켜면 조용히 아무 일도 안 일어난다.

> **⚠ 정정 — 「흘리기 전에 걸어야 한다」는 틀렸다.** Loki retention은 compactor가 **나이 기준으로
> 집행**해서 이미 저장된 청크도 지운다(**소급된다**). 따라서 **순서는 권장이지 강제가 아니다.**
> 먼저 거는 게 디스크상 깔끔할 뿐이며, **단계 순서를 여기에 묶지 않는다.** 이 오류의 출처는
> `reports/2026-09-04_1620_phase0_인프라기동.md`이고 plan Phase 3까지 전파됐다 — §10-2에서 정정한다.

### 6-5. Collector exporter 가용성 (결정 2의 실물 근거)

`components` 목록만 보면 `otlp`·`otlp_http`·`loki`가 안 보이지만, **`validate`로 확정했다.**

| 시험 | 결과 |
|---|---|
| `otlp_grpc` + `otlp_http` | **`exit=0` 통과** |
| `otlp` + `otlphttp`(옛 별칭) | `exit=0` 통과 |
| **음성 대조** — 없는 이름 | **`exit=1` 거부** + 유효한 exporter **53종 전체 목록**을 반환 |
| `loki` exporter | **목록에 없다** — 폐기·제거됨. `components`에 보이던 `loki`는 **receiver**(282줄이 `receivers:` 구간 안) |

> `components`가 8개를 빠뜨린 이유: 정식명+폐기 예정 별칭을 함께 가진 네 쌍
> (`otlp`/`otlp_grpc` · `otlphttp`/`otlp_http` · `azureblob`/`azure_blob` ·
> `googlecloudstorage`/`google_cloud_storage`)이 목록에서 누락된다. **스네이크 케이스 일괄 개명
> 중이며 정식명을 쓴다.** 앞으로 컴포넌트 유무 판정은 `components`가 아니라 **`validate`로** 한다.

### 6-6. 백엔드·저장소·회귀

| 항목 | 실측 |
|---|---|
| 상주 3개 | **전부 죽어 있음.** systemd 유닛 **0개**. sink·격리 파일 마지막 기록 **9-10 13:17**(360줄 / 18줄) |
| Kafka 그룹 | `mk2-storage`(`no active members`, **lag 0** — 죽기 전 전량 소비) · `mk2-ws` · `mk2-headerless-check` · `mk2-dedup-a` · `mk2-dedup-b`. **`mk2-test-*`는 오프셋 보존 만료로 사라졌다** |
| TimescaleDB | healthy · `telemetry` 하이퍼테이블 · **415행** · oldest `2026-09-01` / newest `2026-09-10 13:17` · **`lag_s`가 채워진 행은 41개뿐**(나머지는 헤더 없는 Phase 1 재소비분) · `lag_min -30.000` / `lag_max 10943.838`(3.04시간) · `clock_skew` **3행** |
| MySQL `mk2` | 테이블 8개 전부 `utf8mb4_bin` · `audit_log` 4 · `mission_event` 4 · `registry_entity_declared` 2 · `registry_entity_observed` 14 · `registry_identity_history` 19 · **`registry_node_declared` 0** · `registry_node_observed` 14 · `registry_zone` 2 |
| ⚠ 권한 | **`registry_identity_history`에 `UPDATE`가 아직 있다**(Phase 2 미결). 이번 범위 아님 — §10-4에 기록 |
| **pytest** | **`104 passed in 34.68s`, skip 0** — 기준선 녹색. 음성 대조 3건이 실물 로그로 찍혔다(공통 헤더 2 + **본문 1**) |
| ufw | `4317/tcp ALLOW Anywhere`(12·48) · `7859`(8·44) · `9092`(36·63) · `9100`(6·7) · `9101`(3) · `7862`(4). **`3100`·`3200`·`7861`·`1883`·`7858`은 규칙 없음**(0.0.0.0 바인딩인데도). 도커 서브넷 선례: `9110`(37)·`9120`(38)이 `172.18.0.0/16` |

### 6-7. 엣지·HW 쪽

| 항목 | 실측 |
|---|---|
| **`HW_OTEL_ENDPOINT`** | `hw-node.env.example`에 **주석 처리**돼 있고 값은 `http://192.168.50.244:4317` — **엣지**(`EDGE_SETUP.md`의 `edge-wsl`) 주소다. **우리 서버가 아니다.** `config.OTEL_ENDPOINT`가 비면 `create()`가 `_Noop()`을 돌려주므로 **말단은 지금 관측을 아예 발신하지 않는다** |
| HW export 주기 | **15초.** `BACKEND_AGENDA` §10-1이 *"백엔드 값(15초) 채택으로 종결"*이고 부록 B에도 ✅. 전체 공유 스프레드시트의 60초만 낡았다. `otel_metrics.py` 머리말 주석에 60초가 남아 있으나 **동작은 `config.OTEL_EXPORT_INTERVAL`을 읽으므로 15초** |
| 엣지 실물 | **철수됨**(`EDGE_SETUP.md` §6, 2026-08-31). K3s 정지, pi7은 원래 클러스터로 복귀 |
| 증강 분석 | **돌고 있지 않다** — 이미지 미빌드(매니페스트에 digest 자리표시자), K3s 제어평면 철수 |
| 서버 Tailscale | **미설치**(`which tailscale` 빈손). `prometheus.yml`의 비활성 `k8s-nodes` 잡 주석이 *"서버에 tailscale 없음"*이라 적은 것과 일치 |
| 컴퓨터 | 공인 `203.230.104.168`(공유기) · Wi-Fi 사설 `192.168.50.203` · **Docker 없음** · venv `C:\Users\asdfa\physical mk2` |
| 서버 sshd | `gatewayports no` · `allowtcpforwarding yes` — **읽기만 했고 변경하지 않았다** |


---

## 7. 단계와 각 단계 DoD

> **실행 규율.** 편집은 컴퓨터에서, 실행은 **사람이 서버에서.** 각 단계는 ① 컴퓨터에서 파일을
> 만들고 ② 사람에게 적용·실행 명령을 주고 ③ **결과를 받은 뒤** 다음 단계로 간다. 결과를 받기
> 전에 다음 단계를 진행하지 않는다. 상주 프로세스는 **터미널 1/2/3/4로 나눠** 적는다.

### 단계 0 — 서버 현재 상태 대조

§6의 실측표와 지금 서버가 같은지만 확인한다. **전수 재확인이 아니라 대조**다.

```bash
cd ~/capstone-db
docker compose ps otel-collector prometheus grafana loki tempo timescale-db kafka
docker ps --format 'table {{.Names}}\t{{.Status}}' | wc -l          # 머리말 포함 14줄이면 13개
cd ~/capstone-db/config && md5sum otel-collector-config.yaml loki-config.yaml tempo-config.yaml
ps -eo pid,etime,cmd | grep -E 'backend\.(ingest\.bridge|storage\.consumer|gateway\.ws_echo)' | grep -v grep
systemctl list-unit-files 2>/dev/null | grep -iE 'mk2|capstone'
docker exec capstone_timescaledb psql -U postgres -d mk2 -c "SELECT count(*) FROM telemetry;"
```

**DoD:** 컨테이너 13개·관측 5개 가동·md5 3개 일치·상주 3개 상태 확인·systemd 유닛 유무 확인.
**어긋나는 항목이 하나라도 있으면 멈추고 보고한다.** 특히 md5가 다르면 서버 설정이 §6-1 이후
바뀐 것이므로 **서버 파일을 받아 대조한 뒤** 진행한다.

---

### 단계 1 — 백엔드 상주 3개를 systemd로 승격 (결정 1)

**A층의 선행 조건이다.** 지금 셋 다 죽어 있고 터미널 수동 기동이라 계측이 터미널 수명에 묶인다.

**만들 것:** `infra/systemd/mk2-ingest.service` · `mk2-storage-consumer.service` ·
`mk2-ws-echo.service` (저장소에 커밋한다 — 비밀값이 없다. `.env` 경로만 참조한다).

각 unit의 뼈대:

```ini
[Unit]
Description=MK2 <역할>
After=docker.service
Wants=docker.service
# ⚠ StartLimit* 는 [Service] 가 아니라 [Unit] 이다(systemd v229 이후).
#    [Service] 에 두면 경고와 함께 무시되어 재시작 루프가 안 끊긴다.
StartLimitBurst=3
StartLimitIntervalSec=60

[Service]
Type=simple
User=dg
WorkingDirectory=/home/dg/capstone-db/phase1_work/Physical-Project-mk2
EnvironmentFile=/home/dg/capstone-db/.env
ExecStart=/home/dg/capstone-db/phase1_work/venv_phase1/bin/python -m backend.<모듈>
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

> **⚠ 코드를 고치면 서버 사본에 다시 복사하고 `systemctl restart` 해야 반영된다.**
> 서버는 저장소 사본이고 `git pull` 배포가 아니다(Phase 1 보고서가 「서버 사본과 저장소의
> 동기화」를 미결로 남긴 그 지점이다). **어긋난 채 검증하면 무엇을 검증한 것인지 흐려진다.**
> 단계 6·7에서 코드가 바뀔 때마다: 컴퓨터에서 편집 → 사람이 서버로 복사 →
> `sudo systemctl restart mk2-ingest mk2-storage-consumer mk2-ws-echo`.

- 모듈: `ingest.bridge` · `storage.consumer` · `gateway.ws_echo`
- **`Restart=always`를 쓰지 않는다** — `.env`가 없으면 `settings.MissingSetting`으로 죽고
  무한 재시작 루프가 된다. `on-failure` + `StartLimitBurst`가 그것을 3회에서 끊는다.
- **`EnvironmentFile` 파서 주의.** 이제 `.env`를 읽는 파서가 **셋**이다 — 셸 `source`, compose
  dotenv, systemd `EnvironmentFile`. 셋의 인용부호 규칙이 다르다. 현재 비밀번호가 **영숫자
  32자**라 안전하지만, 값을 바꿀 때 특수문자를 넣으면 한쪽만 다르게 읽는다.

**사람에게 줄 명령** (사본 위치는 사람이 정하되, 유닛 파일은 `/etc/systemd/system/`으로):

```bash
sudo cp <사본경로>/mk2-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mk2-ingest mk2-storage-consumer mk2-ws-echo
systemctl status mk2-ingest mk2-storage-consumer mk2-ws-echo --no-pager | head -40
journalctl -u mk2-ingest -n 20 --no-pager
```

**DoD:**
1. 셋 다 `active (running)`이고 `journalctl`에 각자의 `READY`/기동 로그가 보인다.
2. `enable` 되어 `systemctl is-enabled`가 셋 다 `enabled`.
3. **재기동 시 retained `status`가 다시 흘러 들어오는 것을 로그로 확인한다** — ingest 로그에
   `lag_s`가 큰 `status` 몇 건이 즉시 produce된다. **이것은 정상이다**(레지스트리 시각 가드가
   대장 오염을 막는다). 단계 6 이후 이 값이 A층 카운터에 잡히는 것도 정상이며, 구분 라벨은
   이번에 달지 않는다.
4. `sudo systemctl restart mk2-storage-consumer` 후에도 TSDB 행 수가 **재소비로 늘지 않는다**
   (스트림 좌표 유일 키가 흡수). 재시작 전후 `SELECT count(*) FROM telemetry;` 대조.

---

### 단계 2 — Loki 재구성 (결정 3-c)

**분류 ② 자산이고 데이터를 지운다. 백업이 선행이다.**

**2-1. 백업 (반드시 먼저)**

```bash
cd ~/capstone-db
sudo tar czf ~/loki_data.bak_before_phase3.tgz loki_data
ls -lh ~/loki_data.bak_before_phase3.tgz
cp config/loki-config.yaml config/loki-config.yaml.bak_before_phase3
```

**2-2. 설정 교체** — `infra/config/loki-config.yaml`을 아래 방향으로 고친다.

| 무엇 | 값 | 왜 |
|---|---|---|
| `schema_config.configs` | **v13 / tsdb / filesystem 단일 항목**, `from`은 과거 날짜(예: `2020-10-24` 유지) | 데이터를 비우므로 v11 항목을 끌고 갈 이유가 없고, **기존 데이터가 있을 때만 걸리는 "미래 날짜" 제약이 사라진다** |
| `storage_config.tsdb_shipper` | `active_index_directory: /loki/tsdb-index` · `cache_location: /loki/tsdb-cache` | tsdb 인덱스의 필수 설정 |
| `limits_config.allow_structured_metadata` | **`true`** | OTLP 수집의 전제. v11에서 `false`였던 이유가 스키마였고, v13에서 해소된다 |
| `limits_config.retention_period` | **`14d`** | |
| `compactor.retention_enabled` | **`true`** | 이게 꺼져 있으면 보존 기간을 적어도 **아무것도 지워지지 않는다** |
| `compactor.delete_request_store` | `filesystem` | 삭제 요청을 적을 곳. 비어 있으면 보존이 성립하지 않는다 |
| `compactor.working_directory` | `/loki/compactor` | |

**2-2-a. 완성본** — 위 표를 조립하다 빠뜨리지 않게 전체를 적는다. 기존 파일에서 바뀐 곳은
`schema_config` · `storage_config`(신설) · `compactor`(신설) · `limits_config`다.

```yaml
auth_enabled: false

server:
  http_listen_port: 3100

common:
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory

# v13/tsdb 단일 항목. 데이터를 비우므로 v11 항목을 끌고 가지 않는다.
# (기존 데이터가 있을 때만 "새 period 의 from 은 미래 날짜여야 한다"는 제약이 걸린다.)
schema_config:
  configs:
    - from: 2020-10-24
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h

storage_config:
  tsdb_shipper:
    active_index_directory: /loki/tsdb-index
    cache_location: /loki/tsdb-cache

# ⚠ 셋이 함께 있어야 보존이 집행된다. 하나만 켜면 조용히 아무 일도 안 일어난다.
compactor:
  working_directory: /loki/compactor
  retention_enabled: true
  delete_request_store: filesystem

limits_config:
  allow_structured_metadata: true      # OTLP 수집의 전제 (v13 에서 켤 수 있다)
  retention_period: 14d

ruler:
  alertmanager_url: http://localhost:9093
```

**2-3. 적용** — 컨테이너를 지우지 않고 데이터 디렉터리만 비운다.

```bash
cd ~/capstone-db
docker compose stop loki                      # 서비스 이름 명시
sudo rm -rf loki_data && mkdir -p loki_data
cp <새 설정> config/loki-config.yaml
docker compose up -d loki                     # 서비스 이름 명시
docker compose ps loki
curl -s localhost:3100/ready; echo
curl -s localhost:3100/config | grep -nE 'allow_structured_metadata|retention_enabled|retention_period|schema:|store:|delete_request_store'
```

**DoD:**
1. `/ready`가 `ready`.
2. 적재된 설정에 **`schema: v13` · `store: tsdb` · `allow_structured_metadata: true` ·
   `retention_enabled: true` · `retention_period: 14d` · `delete_request_store` 비어 있지 않음**이
   전부 보인다. **여섯 개를 하나씩 눈으로 확인한다** — 하나라도 빠지면 보존이 성립하지 않는다.
3. `docker logs capstone_loki`에 스키마·컴팩터 관련 오류가 없다.
4. **다른 12개 컨테이너가 재생성되지 않았다**(`docker ps`의 `Up ...`이 유지된다).
5. 백업 파일이 존재한다.

> ⚠ **순서는 권장이지 강제가 아니다.** retention은 소급 집행되므로 로그를 흘린 뒤에 켜도 지워진다.
> 그래도 먼저 켜는 편이 디스크상 깔끔해서 이 자리에 두었다.

---

### 단계 3 — Tempo 보존 (결정 3-d)

```bash
cd ~/capstone-db
cp config/tempo-config.yaml config/tempo-config.yaml.bak_before_phase3
# compactor.compaction.block_retention: 24h → 168h
# ⚠ compose 가 안 바뀌었으므로 `up -d` 는 아무 일도 하지 않는다(설정이 반영되지 않는다).
#    Tempo 는 설정을 기동 시점에 읽으므로 반드시 restart 다.
docker compose restart tempo                  # 서비스 이름 명시
curl -s localhost:3200/ready; echo
docker exec capstone_tempo sh -c 'grep -n block_retention /etc/tempo.yaml' 2>/dev/null || \
  grep -n block_retention ~/capstone-db/config/tempo-config.yaml
```

- **`distributor.receivers.otlp`는 그대로 둔다.** Collector가 그 자리로 보낸다.
- **compose의 `ports`도 그대로 둔다**(결정 2 — 호스트 포트 무변경).

**DoD:** `/ready`가 `ready` · 적재된 값이 `168h` · 다른 컨테이너 무변경.

---

### 단계 4 — Collector 재구성 (결정 2)

**분류 ② 자산. 지금 이 Collector를 거치는 데이터가 0건이라 잃을 것이 없다**(§6-2).

**4-1. compose — 이미지 digest 고정**

```yaml
  otel-collector:
    # v0.150.1 (2026-09-14 서버 실물). :latest 는 이동 태그라 같은 이름으로 내용이 바뀐다.
    image: otel/opentelemetry-collector-contrib@sha256:7087dcbbba9c9f5c919a86c1a1cf2aa483bb585a3efa10ddb4e74cb0c4ca03eb
```

적용 전에 digest가 실제로 resolve되는지 확인한다(틀리면 기동이 실패한다):

```bash
docker image inspect otel/opentelemetry-collector-contrib@sha256:7087dcbbba9c9f5c919a86c1a1cf2aa483bb585a3efa10ddb4e74cb0c4ca03eb --format '{{.Id}}'
```

**4-2. 설정 — 파이프라인 3종**

`infra/config/otel-collector-config.yaml`을 아래 구조로 만든다. **exporter 이름은 정식명을 쓴다**
(`otlp_grpc`·`otlp_http`. 옛 별칭 `otlp`·`otlphttp`도 지금은 통하지만 폐기 예정이다).

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: "0.0.0.0:4317"      # 컨테이너 안. 호스트 공개는 127.0.0.1:4316 (무변경)

processors:
  batch:
    timeout: 5s
    send_batch_size: 512

exporters:
  prometheus:
    endpoint: "0.0.0.0:8889"          # 현행 유지 — Prometheus 가 docker 망에서 scrape
  otlp_grpc:                          # traces → Tempo (도커 네트워크 안, 호스트 포트 안 거침)
    endpoint: "tempo:4317"
    tls:
      insecure: true
  otlp_http:                          # logs → Loki 네이티브 OTLP 수신
    endpoint: "http://loki:3100/otlp"

service:
  pipelines:
    metrics: { receivers: [otlp], processors: [batch], exporters: [prometheus] }
    traces:  { receivers: [otlp], processors: [batch], exporters: [otlp_grpc] }
    logs:    { receivers: [otlp], processors: [batch], exporters: [otlp_http] }
```

**4-3. 적용 전에 반드시 `validate`** — 기동 실패로 알기보다 먼저 안다.

```bash
docker run --rm -v ~/capstone-db/config/otel-collector-config.yaml:/tmp/c.yaml \
  otel/opentelemetry-collector-contrib@sha256:7087dcbbba9c9f5c919a86c1a1cf2aa483bb585a3efa10ddb4e74cb0c4ca03eb validate --config=/tmp/c.yaml; echo "exit=$?"
```

**4-4. 적용**

```bash
cd ~/capstone-db
cp config/otel-collector-config.yaml config/otel-collector-config.yaml.bak_before_phase3
cp <새 설정> config/otel-collector-config.yaml
docker compose up -d otel-collector           # digest 변경이라 재생성된다. 서비스 이름 명시
docker compose ps otel-collector
docker logs --tail 40 capstone_otel_collector
```

**DoD:**
1. `validate`가 `exit=0`.
2. 기동 로그에 **`Starting GRPC server`**와 `Everything is ready`가 보이고, **파이프라인 3종이
   전부 기동 로그에 나타난다**(metrics·traces·logs).
3. `docker inspect capstone_otel_collector --format '{{.Config.Image}}'`가 **digest 형태**다.
4. **다른 12개 컨테이너가 재생성되지 않았다.**
5. 아직 데이터는 0이다 — 이 단계의 판정은 "떠 있다"가 아니라 **"설정이 유효하고 파이프라인 3종이
   섰다"**까지다. 실제로 흐르는지는 단계 6·9에서 본다.

---

### 단계 5 — Prometheus 잡 주기 (결정 3-a)

**global은 건드리지 않는다.** `otel_collector` 잡에만 한 줄을 더한다.

```yaml
  - job_name: 'otel_collector'
    scrape_interval: 5s          # ← 이 한 줄만 추가 (백엔드 export 15초 × 표본 3)
    static_configs:
      - targets: ['otel-collector:8889']
```

```bash
cd ~/capstone-db
cp config/prometheus.yml config/prometheus.yml.bak_before_phase3
cp <새 설정> config/prometheus.yml
docker exec capstone_prometheus kill -HUP 1          # 재생성 아님 — 설정 reload
sleep 3
curl -s localhost:7861/api/v1/targets?state=any | python3 -c "
import sys,json
for x in json.load(sys.stdin)['data']['activeTargets']:
    print(x['labels'].get('job'), x['health'], x.get('scrapeInterval'))"
```

**DoD:**
1. `otel_collector`의 interval이 **`5s`**, health `up`.
2. **다른 네 잡의 interval·health가 단계 0과 동일하다** — `rpi_pushgateway`·`thermal_pushgateway`
   가 `5s`/up 그대로이고 `robot_server`는 `down` 그대로다(원래 down이며 우리 것이 아니다).
3. `prometheus.yml` **주석 두 곳을 이번에 함께 고친다**(§10-3) — 머리말의 `before/after` 블록과
   본문 `[수정 260903]` 주석이 `rpi-pushgateway:9091` 우회를 말하는데 **그 우회는 폐기됐고 실제
   타깃은 `host.docker.internal:9100`이며 up이다.** **잡 본문은 건드리지 않는다**(분류 ③).

---

### 단계 6 — 관측 어댑터와 A층 계측 (결정 4)

**이 Phase의 본체다.**

**6-1. 의존성** — `pyproject.toml`의 *"관측 SDK·미디어는 그 Phase에서 추가한다"* 자리에 넣는다.

```toml
    # ── Phase 3 (관측 파이프라인) ──
    "opentelemetry-sdk>=1.27",
    "opentelemetry-exporter-otlp-proto-grpc>=1.27",
```

서버 venv에 설치한 뒤 **버전을 보고한다**(Python 3.14 호환 확인 — Phase 2에서 `mysqlclient`가
빌드에 실패한 전례가 있다).

**6-2. 관측 어댑터** — `backend/observability.py` 신설.

**원칙 1을 지키는 자리다.** `bridge.py`·`consumer.py`·`ws_echo.py`·`tsdb_writer.py`·`registry.py`는
`opentelemetry`를 **직접 import하지 않는다.** 이 모듈의 목적 인터페이스만 쓴다.

```python
def setup(service_name: str) -> None: ...      # 프로세스 기동 시 1회
def count(name: str, value: int = 1, **labels) -> None: ...
def gauge(name: str, value: float, **labels) -> None: ...
def observe(name: str, value: float, **labels) -> None: ...   # histogram
def log_handler() -> logging.Handler | None: ...              # 4-c, 없으면 None
def shutdown() -> None: ...
```

**반드시 지킬 것 넷:**

1. **no-op 규율(제약 20).** `MK2_OTEL_ENDPOINT`가 비었거나 SDK가 없거나 초기화가 실패하면
   **조용히 no-op으로 떨어지고 업무 경로는 계속 돈다.** HW `otel_metrics.create()`와 같은 구조다.
   기동 시 한 줄 로그로 활성/비활성을 남긴다.
2. **라벨 가드.** 금지 라벨(`session_id`·`internal_seq`·`sequence_id`·`timestamp`·`ts`·
   `frame_id`·`capture_timestamp`)이 들어오면 **`ValueError`로 막는다.** 조용히 버리지 않는다 —
   버리면 나중에 누가 넣어도 아무도 모른다. **이것이 음성 대조 대상이다.**
3. **A층에는 `source_id`를 넣지 않는다.** 가드가 A층 계기 이름(`be.ingest.*`·`be.kafka.*`·
   `be.storage.*`·`be.registry.*`·`be.gateway.*`·`be.pipeline.*`)에 `source_id`·`zone_id`·
   `entity_type`이 붙으면 막는다.
4. **계측 호출이 예외를 밖으로 내보내지 않는다.** 어댑터 안에서 전부 삼킨다.

> **⚠ 구현 함정 셋 — 모르면 여기서 헤맨다.**
> 1. **계기는 한 번만 만들고 재사용한다.** `count()`를 부를 때마다 `create_counter()`를 새로
>    부르면 중복 계기 경고가 나고 값이 갈린다. 어댑터가 **이름별로 계기를 캐시**한다.
> 2. **히스토그램 버킷은 `View`로 준다.** OTel Python은 기본 버킷 상한이 10초 근처라 우리 값이
>    전부 `+Inf`에 몰린다. `MeterProvider(views=[View(instrument_name="be.pipeline.lag",
>    aggregation=ExplicitBucketHistogramAggregation(
>    [0.1, 0.5, 1, 5, 15, 60, 300, 1800, 7200, 86400]))])` — **단계 6-3의 버킷을 그대로 쓴다.**
> 3. **로그 SDK 모듈 경로가 밑줄일 수 있다**(`opentelemetry.sdk._logs`). 버전에 따라 갈리므로
>    **설치 직후 import 경로를 확인하고 지시서에 실제 경로를 적어 보고한다.** 없으면 4-c는
>    no-op으로 떨어뜨리고 그 사실을 보고한다 — 추측으로 진행하지 않는다.
> 4. **`_on_delivery(err, msg)`에는 채널이 안 넘어온다.** `msg.topic().rsplit(".", 1)[-1]`로
>    꺼낸다(토픽 규약이 `mk2.telemetry.<채널>`이다).

**6-3. A층 계기 9종** — 이름·라벨·꽂을 자리를 아래 표대로 정확히 만든다.

| OTel 이름 | 종류 | 라벨 | Prometheus 표기 | 꽂을 자리 |
|---|---|---|---|---|
| `be.ingest.received` | counter | `component`·`channel` | `be_ingest_received_total` | `bridge.handle()` — 2단 검증 통과 후 produce 직전 |
| `be.ingest.rejected` | counter | `component`·`channel`·`stage` | `be_ingest_rejected_total` | `quarantine()` 호출 **3곳 전부**. `stage` = `envelope`(1단) / `payload`(2단) / `unknown_channel` |
| `be.kafka.produce` | counter | `component`·`channel`·`outcome` | `be_kafka_produce_total` | `_on_delivery()` — `err`가 있으면 `fail`, 없으면 `ok` |
| `be.storage.consumed` | counter | `component`·`channel` | `be_storage_consumed_total` | `consumer.run()` 소비 루프에서 레코드 1건마다 |
| `be.storage.write` | counter | `component`·`channel`·`outcome` | `be_storage_write_total` | `tsdb_writer.write()` 성공 / `_fail()` 실패 |
| `be.registry.observe` | counter | `component`·`outcome` | `be_registry_observe_total` | `registry.observe()` 성공 / 예외 경로 |
| `be.gateway.push` | counter | `component`·`channel` | `be_gateway_push_total` | `ws_echo._broadcast()` 전송 1건마다 |
| `be.gateway.clients` | UpDownCounter | `component` | `be_gateway_clients` | `handler()`의 접속 `+1` / 종료 `-1` |
| `be.pipeline.lag` | histogram | `component`·`channel` | `be_pipeline_lag_seconds_{bucket,sum,count}` | `consumer.run()` — `record.lag_s`가 `None`이 아닐 때만 |

- `component` 값은 `ingest` · `storage` · `gateway` 셋.
- `service.name`은 프로세스별 — `be-ingest` · `be-storage` · `be-gateway`.
- **`be.pipeline.lag`가 BE-S-07의 측정 수단이다.** 값의 출처는 `TelemetryRecord.lag_s`이며
  **새로 계산하지 않는다.** 음수(`clock_skew`)도 버리지 않고 그대로 기록한다.
- 히스토그램 버킷은 실측 범위를 덮어야 한다 — 지금 `-30.000` ~ `10943.838`초이고 재기동마다
  retained `status`가 **3.98일(≈344,000초)**로 들어온다. 기본 버킷(상한 10초)으로는 전부 `+Inf`에
  몰린다. **명시적 버킷을 준다**(예: `0.1 0.5 1 5 15 60 300 1800 7200 86400`).

> **⚠ `service.name`은 Prometheus에서 `job`이 아니라 `exported_job`으로 나타난다.**
> Collector의 `prometheus` exporter는 `service.name`·`service.instance.id`를 `job`·`instance`
> 라벨로 내보내는데, 스크레이프 잡 `otel_collector`에 `honor_labels`가 없어 **Prometheus가
> 충돌을 `exported_job`·`exported_instance`로 바꾼다.** `job="be-ingest"`를 찾으면 안 나온다.
> **컴포넌트 구분은 우리가 붙인 `component` 라벨로 한다** — 그래서 A층 라벨에 `component`가
> 있는 것이다. `honor_labels: true`를 이 잡에 붙이는 안도 있으나, 그러면 `job="otel_collector"`가
> 사라져 **경로를 식별할 수 없게 되므로 붙이지 않는다.** DoD 질의는 `component`를 쓴다.
> (Loki는 다르다 — OTLP 수집에서 `service.name`이 `service_name` 라벨로 색인되므로
> `{service_name="be-ingest"}` 질의가 그대로 된다.)

**6-4. 로그 경로 (4-c)** — `observability.log_handler()`가 OTel `LoggingHandler`를 돌려주고, 각
프로세스의 `main()`이 `logging.basicConfig` 뒤에 그것을 **루트 로거에 추가**한다. stdout은 그대로
두어 journald에도 남긴다(운영자용). 어댑터가 비활성이면 `None`을 돌려주고 아무 일도 하지 않는다.

**6-4-a. 재기동하면 counter가 0으로 리셋된다 — 정상이다.**

systemd `Restart=on-failure`, 코드 반영을 위한 `systemctl restart`, 단계 8-7(a)의 Collector
재생성까지 이번 Phase에는 재기동이 잦다. **counter는 프로세스와 수명을 같이 하므로 그때마다
0에서 다시 센다.** Prometheus의 `rate()`·`increase()`는 리셋을 감지해 처리하므로 **조회에서는
무해하다** — 다만 **누적 절대값을 그대로 읽으면 안 된다.** 대시보드·알람을 만들 때 `rate()`를
쓰고, 보고서에 이 사실을 한 줄 남긴다.

> 함께 기억할 것: **ingest를 재기동할 때마다 retained `status` 3건이 다시 흘러 들어와**
> `be_ingest_received_total`이 3만큼 튄다(단계 1 DoD 3). 이것도 정상이며 구분 라벨은 달지 않는다.

**6-5. 환경변수** — `backend/settings.py`의 표에 추가한다.

| 환경변수 | 기본값 | 누가 쓰나 |
|---|---|---|
| `MK2_OTEL_ENDPOINT` | `http://127.0.0.1:4316` | 관측 발신 대상(서버 Collector). **비어 있으면 계측 전체 no-op** |
| `MK2_OTEL_EXPORT_INTERVAL` | `15` (초) | HW와 같은 값. **검증 중에는 낮춰서 즉시 확인**한다 |
| `MK2_OTEL_SERVICE_NAME` | 프로세스별 기본값 | `be-ingest`·`be-storage`·`be-gateway` |

**DoD:**
1. 셋을 `systemctl restart`한 뒤 journald에 **관측 활성 로그 한 줄**이 각각 보인다.
2. `tests/publisher.py`로 몇 건 발행한 뒤 **Prometheus에서 `be_*` 지표가 조회된다**:
   ```bash
   curl -s -G 'localhost:7861/api/v1/label/__name__/values' | python3 -c "
   import sys,json;v=json.load(sys.stdin)['data'];print([x for x in v if x.startswith('be_')])"
   ```
   **`be_ingest_received_total`·`be_storage_consumed_total`·`be_pipeline_lag_seconds_count`가
   최소한 보여야 한다.**
3. **라벨에 `source_id`가 없다**(A층 지표 하나를 골라 `/api/v1/series`로 라벨 집합 확인).
4. **Loki에 백엔드 로그가 쌓인다** — `{service_name="be-ingest"}` 질의로 최소 1건.
5. **Tempo는 아직 0건이어도 된다**(백엔드 span 생산은 이번 범위가 아니다 — 단계 9에서 가짜 span).
6. `MK2_OTEL_ENDPOINT=""`로 띄우면 **계측 없이 정상 동작**한다(제약 20 확인).

---

### 단계 7 — C층 파생 (결정 5)

**저장 소비자 안에서, 저장 성공 여부와 무관하게, 예외를 삼키고 파생한다.**

**7-1. 대상은 스키마에서 읽는다.** `backend/contracts.py`에 `observation_hints()`를 더해
`contracts/common/payload/*.schema.json`의 `$comment`에서 **신호 종류 힌트를 파싱**한다.
**파이썬에 목록을 다시 적지 않는다**(원칙 9). 중첩 항목(`status.buffer.*`)도 훑어야 한다.

**파싱 규약을 못 박는다** — 안 적으면 구현자가 다르게 파싱해 개수가 갈리고 DoD 22가
헷갈리게 실패한다.

- 마커 문자열: **`관측 신호 힌트:`** 뒤의 첫 낱말(`gauge` · `counter` · `log/event`).
- **`properties` 안을 재귀로 훑는다** — `status.buffer`의 `pending`·`dropped`·`thinned` 셋이
  **중첩**에 있어서, 최상위만 보면 셋을 놓친다.
- 키는 **(채널, 개체 타입, 항목 경로)** — `state`는 타입별 규격 4종, `status`·`heartbeat`는 공통.
- **힌트가 없는 항목은 C층 대상이 아니다.**
- 전수 검산: **27곳에 힌트가 붙어 있고, 항목 이름으로 중복을 접으면 gauge 9 · counter 3 ·
  log/event 10 = 22개**다(`reason`·`device_status`가 여러 규격에 나온다). **이 숫자가 안 나오면
  파싱이 틀린 것이다.**

**7-2. 이번 Phase의 계측 대상은 gauge 9 + counter 3 = 12개.** 아래가 전수이며 **새로 고르지 않는다.**

| OTel 이름 | 출처(규격:항목) | 힌트 |
|---|---|---|
| `be.telemetry.water_level_m` | `state.sensor` : `water_level_m` | gauge |
| `be.telemetry.battery_pct` | `state.robot` : `battery_pct` | gauge |
| `be.telemetry.speed_mps` | `state.robot` : `speed_mps` | gauge |
| `be.telemetry.progress` | `state.actuator` : `progress` | gauge |
| `be.telemetry.analysis.value` | `state.analysis` : `value` | gauge |
| `be.telemetry.analysis.trend_m_per_min` | `state.analysis` : `trend_m_per_min` | gauge |
| `be.telemetry.analysis.eta_to_threshold_min` | `state.analysis` : `eta_to_threshold_min` | gauge |
| `be.telemetry.uptime_s` | `status` : `uptime_s` | gauge |
| `be.telemetry.buffer.pending` | `status` : `buffer.pending` | gauge |
| `be.telemetry.buffer.dropped` | `status` : `buffer.dropped` | **counter(아래 주의)** |
| `be.telemetry.buffer.thinned` | `status` : `buffer.thinned` | **counter(아래 주의)** |
| `be.telemetry.publish_failures` | `status` : `publish_failures` | **counter(아래 주의)** |

**라벨: `source_id` · `zone_id` · `entity_type` · `channel`** (4-b).

> ⚠ **counter 3개는 말단이 보내는 「절대 누적값」이다.** 델타를 구하려면 직전 값을 들고 있어야
> 하는데, 그건 Phase 2가 세운 무상태 원칙과 충돌한다(*"적재 시 상태를 들고 있는 칼럼을 두지
> 않았다"*). 그래서 **gauge 계기로 절대값을 그대로 기록하고 이름에 `_total`을 붙이지 않는다.**
> 조회에서 증가분이 필요하면 `increase()`가 아니라 `delta()`/`deriv()`를 쓴다.
> **이 판단을 보고서에 「발견한 것」으로 남긴다** — `$comment`는 counter인데 계기는 gauge다.

**7-3. 값 꺼내기 주의 셋** (규격을 안 읽으면 여기서 틀린다):

1. **`{value, state}` 형태를 벗겨야 한다.** `water_level_m`·`battery_pct`는 `x-mk2-absence:
   stateful`이라 `{"value": null, "state": "unavailable"}`로 올 수 있다. **`value`가 `null`이면
   기록하지 않는다**(0을 넣으면 "값 없음"이 "0"이 된다).
2. **명시적 `null`은 기록하지 않는다.** `trend_m_per_min`·`eta_to_threshold_min`은 판단 보류를
   `null`로 표현한다 — *"0을 주면 소비자가 '변화 없음'으로 오해한다"*가 규격에 적혀 있다.
3. **`status.buffer`가 통째로 없을 수 있다**(LWT). 없으면 그 셋을 건너뛴다.

**7-3-a. `entity_type`이 `None`일 수 있다.** 헤더 없는 옛 메시지(Phase 1 적재분)를 다시
소비하면 `record.entity_type`이 `None`이다 — Phase 2가 *"헤더가 없는 것이 오류가 아니다"*로
확정한 그 경우다. **`unknown`으로 채워 넣고 기록은 계속한다**(그 값 하나만 늘어 시계열 폭증이
없다). 라벨을 비우거나 건너뛰면 "왜 안 나오나"를 나중에 헤맨다.

**7-4. 배선.** `consumer.run()`의 `writer.write(record)` **다음 줄**에, `registry.observe()`와
같은 방식으로 목적 인터페이스 한 줄을 더한다. 예외는 파생 쪽에서 삼킨다.

**DoD:**
1. `tests/publisher.py`로 4종 타입 × 3채널을 발행하면 **Prometheus에 `be_telemetry_*`가 나타난다.**
2. **라벨에 `source_id`·`zone_id`·`entity_type`·`channel`이 있고 금지 라벨이 없다.**
3. **`state.analysis`의 gauge 3종은 값이 안 나올 수 있다** — 증강 분석이 지금 돌지 않기 때문이며
   **정상이다**(가짜 발행자로는 나온다). 이 사실을 보고서와 `infra/README.md`에 적는다.
4. **`water_level_m`을 `{"value": null, "state": "unavailable"}`로 발행하면 시계열이 생기지 않는다**
   (음성 대조).
5. **원본이 여전히 TSDB다** — 같은 발행분이 `telemetry` 테이블에도 그대로 들어가 있다(행 수 대조).

---

### 단계 8 — 엣지 2계층과 페더레이션 (결정 6)

**컴퓨터를 엣지로 쓴다.** 서버 안에 임시 컨테이너를 만들지 않는다.

**8-1. Tailscale** — 서버·컴퓨터 양쪽에 설치하고 같은 계정으로 로그인한다.

```bash
# [서버]
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
tailscale status
tailscale ip -4
```

컴퓨터는 Windows 설치본을 쓴다. **양쪽 주소는 `_serverinfo/`에만 적고 커밋하지 않는다**(제약 13).

> **계정은 임시다.** 나중에 팀 계정으로 옮기면 **IP가 바뀌고** `prometheus.yml` 타깃 한 줄을
> 고쳐야 한다. **plan Phase 4에 이월**로 적는다(§10-2).

**8-2. 엣지 실행 파일 2개** — `C:\Users\asdfa\physical mk2\edge_probe\`에 푼다. **Docker를 깔지
않는다.** 검증 후 폴더 하나를 지우면 흔적이 없다.

| 무엇 | 버전 | 왜 |
|---|---|---|
| `prometheus.exe` | **3.9.1** | 서버와 동일. 다르면 대조가 성립하지 않는다 |
| `otelcol-contrib.exe` | **0.150.1** | 〃 |

**8-3. 엣지 Collector(Agent) 설정**

```yaml
receivers:
  otlp: { protocols: { grpc: { endpoint: "0.0.0.0:4317" } } }
processors:
  batch: { timeout: 5s }
exporters:
  prometheus: { endpoint: "0.0.0.0:8889" }    # 엣지 Prometheus 가 긁는다
service:
  pipelines:
    metrics: { receivers: [otlp], processors: [batch], exporters: [prometheus] }
```

**8-4. 엣지 Prometheus 설정 — BE-S-06(집약 계층 경계 표기)이 여기 있다**

```yaml
global:
  scrape_interval: 15s          # 엣지가 raw 를 짊어진다
  external_labels:
    zone_id: zoneA
    agg_layer: edge             # ← BE-S-06 표기
scrape_configs:
  - job_name: 'edge_collector'
    static_configs:
      - targets: ['localhost:8889']
```

**집약 계층 경계 표기 규약(BE-S-06):** 엣지가 `agg_layer="edge"`를 external label로 붙이고,
중앙 페더레이션 잡이 `honor_labels: true`로 **그것을 보존한다.** 중앙이 직접 수집한 시계열에는
`agg_layer`가 **없다** — 부재가 곧 "중앙 원본"이다. **중앙 `global.external_labels`를 건드리지
않는다**(분류 ② 접촉 최소화).

**8-5. 가짜 B층 발신** — `tests/edge_probe_publisher.py`를 새로 만든다. HW `otel_metrics.py`의
**metric 5종과 resource 속성을 그대로 흉내 낸다**: `system.cpu.utilization`·
`system.memory.utilization`·`system.filesystem.free`·`hw.publish.count`(`outcome` 속성)·
`hw.publish.duration`, resource는 `service.name = hw-{entity_type}-node` ·
`hw.entity_id`·`hw.node_id`·`hw.zone_id`. **export 주기 15초.**

> 말단이 `/metrics`를 열지 않는다 — OTLP로 엣지 Collector에 **push**한다.
> `EDGE_SETUP.md` §1과 AI-B-10(말단 경량 실행 경계)이 요구하는 구조다.

**8-5-a. 엣지 실행과 Windows 방화벽 — 여기서 가장 많이 막힌다**

```powershell
cd "C:\Users\asdfa\physical mk2\edge_probe"
# 터미널 1
.\otelcol-contrib.exe --config=otel-agent.yaml
# 터미널 2
.\prometheus.exe --config.file=prometheus.yml --storage.tsdb.path=.\data
# 터미널 3 (가짜 B층 발신) — venv 에 opentelemetry SDK 가 필요하다
"C:\Users\asdfa\physical mk2\venv_phase1\Scripts\python.exe" edge_probe_publisher.py
```

> **⚠ Windows Defender 방화벽이 인바운드를 막는다.** Prometheus가 `0.0.0.0:9090`을 들어도
> **Tailscale 인터페이스로 들어오는 연결이 차단**되면 서버의 `edge_federate` 타깃이 `down`으로만
> 보이고 원인이 안 드러난다. **소프트웨어·설정을 먼저 본다**(물리 배선 의심은 그다음이다):
> ```powershell
> # 관리자 PowerShell — 검증 동안만. 끝나면 Remove-NetFirewallRule 로 지운다.
> New-NetFirewallRule -DisplayName "MK2 edge Prometheus (phase3)" `
>   -Direction Inbound -Protocol TCP -LocalPort 9090 -Action Allow
> ```
> 도달 확인 순서: ① `tailscale ping <엣지>` ② 서버에서 `curl -s http://<엣지>:9090/-/healthy`
> ③ 그다음에 `/federate`. **①이 되는데 ②가 안 되면 방화벽이다.**
> 검증이 끝나면 **방화벽 규칙을 지우고** `edge_probe\` 폴더를 지운다.

**8-5-b. 엣지 venv 의존성.** 컴퓨터 venv(`venv_phase1`, Python 3.12)에는 `paho-mqtt`·`protobuf`만
있다. 가짜 B층 발신에는 `opentelemetry-sdk`·`opentelemetry-exporter-otlp-proto-grpc`가 더 필요하다.
**서버 venv(3.14)와 버전이 갈릴 수 있으므로 양쪽 설치 버전을 함께 보고한다.**

**8-6. 중앙 페더레이션 잡** — `prometheus.yml`에 추가한다.

```yaml
  - job_name: 'edge_federate'
    honor_labels: true                 # 엣지의 agg_layer·zone_id 를 보존
    scrape_interval: 15s               # ⚠ 안 적으면 global 1초로 당긴다
    metrics_path: '/federate'
    params:
      'match[]':
        - '{__name__=~"hw_.*"}'                     # B층 요약
        - '{__name__=~"system_(cpu|memory)_.*"}'
    static_configs:
      - targets: ['<엣지 tailscale IP>:9090']
```

- **`match[]`로 대상을 한정한다.** raw를 통째로 당기면 원칙 14가 깨진다.
- **`up`·장치 생사·치명 오류를 요약에 섞지 않는다**(원칙 6) — `match[]`에 넣지 않는다.
- **ufw:** 중앙이 엣지로 **나가는** 연결이라 서버 인바운드 규칙은 필요 없다. 그래도 도달 실패 시
  방화벽을 용의선상에서 빼려면 **`tailscale ping`으로 경로를 먼저 확인**한다(제약 12의 취지).

**DoD:**
1. `tailscale status`에 양쪽 기기가 보이고 `tailscale ping <엣지>`가 `via <ip>`(직접) 또는
   `via DERP`로 성공한다.
2. 엣지 Prometheus(`localhost:9090`)에 `hw_*`·`system_*` 시계열이 있다.
3. **서버에서 `edge_federate` 타깃이 `up`이고 interval이 `15s`다.**
4. **서버 Prometheus에서 `hw_publish_count_total`(또는 그에 준하는 이름)이 조회되고
   `agg_layer="edge"`·`zone_id="zoneA"` 라벨이 붙어 있다.** ← **페더레이션 요약이 당겨졌다는
   DoD 원문의 충족 근거다.**
5. **음성 대조 — raw가 안 온다.** 엣지에만 있고 `match[]`에 없는 지표(예: 엣지 Prometheus 자신의
   `go_*`)를 서버에서 질의하면 **`agg_layer="edge"` 라벨이 붙은 결과가 0건**이어야 한다.
6. **음성 대조 — 경계 표기가 실제로 갈린다.** 서버 자체 수집분(`be_*`)에는 `agg_layer` 라벨이
   **없다.**
7. **8-7(엣지 log·trace 전달)의 DoD는 그 절에 따로 있다**(아래 「8-7 DoD」 8항목). 이 목록은 metric 페더레이션까지의 판정이다.
8. 검증 후 엣지 프로세스를 내리고 **Windows 방화벽 규칙을 지우고** `edge_probe\` 폴더를 지우면 **서버에는 `prometheus.yml`의
   `edge_federate` 잡만 남는다.** 그 잡은 지우지 않고 **주석으로 내려** 엣지 실물이 왔을 때
   주소만 바꿔 되살리는 자리로 둔다.

**8-7. 엣지 log·trace 원본 전달 (8-D — 사용자 확인 완료, 이번에 한다)**

`00-architecture.md` §5-3·§6-3이 요구하는 **Agent→Gateway 사슬**을 여기서 닫는다. 엣지 Collector가 log·trace 원본을
서버 Collector로 넘기고, 서버 Collector가 log→Loki·trace→Tempo로 분배한다. metric은 단계 8-6의
페더레이션으로 가므로 **엣지 Collector에서 서버로 보내는 것은 log·trace뿐이다**(원칙 14 — raw
metric을 중앙에 몰지 않는다).

> **⚠ 이건 결정 2의 「포트 무변경」과 충돌하지 않는다.** 4316이라는 **번호를 바꾸는 것이 아니라
> 노출 인터페이스를 하나 더하는 것**이다. `127.0.0.1:4316`은 그대로 살아 있고 백엔드 3개가 계속
> 그 길로 보낸다. Phase 4가 Kafka에 하려는 조치(`infra/README.md` §5 「바꿀 때 정확히 이 3가지」)와
> 같은 형태다.

**(a) 서버 Collector를 Tailscale 인터페이스에도 바인딩한다.** 주소는 단계 8-1에서 받은 서버 tailscale
IP다. **compose가 바뀌므로 컨테이너가 다시 재생성된다**(단계 4에서 digest 때문에 한 번, 여기서
한 번 — Tailscale IP를 단계 4 시점에는 알 수 없어 나눌 수밖에 없다).

```yaml
  otel-collector:
    ports:
      - "127.0.0.1:4316:4317"          # 기존 — 백엔드 3개(호스트 프로세스)가 쓰는 길. 그대로 둔다
      - "<서버 tailscale IP>:4316:4317" # 신설 — 엣지 Agent 가 들어오는 길
```

```bash
cd ~/capstone-db
docker compose up -d otel-collector     # 서비스 이름 명시
docker compose ps otel-collector
sudo ss -tulpn | grep 4316              # 두 주소에 LISTEN 이 보여야 한다
```

> **⚠ Tailscale이 떠 있어야 이 바인딩이 성립한다.** docker는 **존재하지 않는 IP에는 바인딩하지
> 못한다** — `tailscaled`가 올라오기 전에 `up -d`를 하면 `cannot assign requested address`로
> 기동이 실패한다. **서버가 재부팅되면 같은 이유로 `restart: always`가 재시작 루프에 빠질 수
> 있다.** 그래서 이 바인딩은 **검증 기간 한정**이고 8-7(e)로 되돌리는 것이다. 적용 전에
> `tailscale ip -4`가 주소를 돌려주는지 먼저 확인한다.

**(b) ufw를 연다 — 엣지 주소로 제한한다.** 제약 12(외부 포트는 ufw에도 연다)이고, 서버에 이미
소스 제한 선례가 있다(규칙 37·38이 `9110`·`9120`을 `172.18.0.0/16`으로 제한).

```bash
sudo ufw allow from <엣지 tailscale IP>/32 to any port 4316 proto tcp comment 'MK2 phase3 edge agent'
sudo ufw status numbered | grep 4316
```

> **`Anywhere`로 열지 않는다.** 이 OTLP 수신단에는 인증이 없다. Tempo 4317이 `0.0.0.0` + ufw
> `Anywhere`로 열려 있는 상태를 **되풀이하지 않는다**(그건 이번에 닫지 않고 기록만 하는 기존
> 항목이다 — §10-3 ⓓ).

> **안 뚫리면 진단 순서.** ① `tailscale ping <서버>` ② 엣지에서 `Test-NetConnection <서버
> tailscale IP> -Port 4316` ③ 서버에서 `sudo ss -tulpn | grep 4316`에 **두 주소**가 보이는지
> ④ `sudo ufw status numbered | grep 4316` ⑤ `docker logs capstone_otel_collector`.
> **①~⑤를 다 본 뒤에 물리 배선·회선을 의심한다.**

**(c) 엣지 Collector 설정에 log·traces 파이프라인을 더한다.** 단계 8-3의 설정을 이렇게 넓힌다.

```yaml
exporters:
  prometheus: { endpoint: "0.0.0.0:8889" }        # metric — 엣지 Prometheus 가 긁는다(8-4)
  otlp_grpc:                                       # log·trace 원본 → 서버 Collector(Gateway)
    endpoint: "<서버 tailscale IP>:4316"
    tls:
      insecure: true                               # 터널 안이라 평문. TLS 는 BE-T-08(Phase 4)

service:
  pipelines:
    metrics: { receivers: [otlp], processors: [batch], exporters: [prometheus] }
    logs:    { receivers: [otlp], processors: [batch], exporters: [otlp_grpc] }
    traces:  { receivers: [otlp], processors: [batch], exporters: [otlp_grpc] }
```

**적용 전에 `validate`한다**(서버 Collector와 같은 규율):

```powershell
.\otelcol-contrib.exe validate --config=otel-agent.yaml ; echo "exit=$LASTEXITCODE"
```

**(d) 가짜 B층 발신자가 log·span도 낸다.** `tests/edge_probe_publisher.py`가 metric 5종에 더해
**로그 1건 이상**과 **span 1건 이상**을 낸다. resource 속성은 metric과 **똑같이** 쓴다
(`service.name = hw-{entity_type}-node` 등) — 그래야 Collector·Grafana에서 같은 주체로 묶인다.
span은 HW `otel_trace.py`의 범위를 흉내 내 **명령 경로 모양**(`cmd.receive` → `cmd.execute`)으로
만든다. 고빈도 경로에는 span을 만들지 않는다.

**(d-1) 발신자의 엔드포인트는 서버가 아니라 엣지 Collector다.** `edge_probe_publisher.py`의
OTLP 엔드포인트는 **`localhost:4317`(엣지 Collector)**이다. 서버로 직접 쏘면 Agent를 건너뛰어
**8-7이 검증하려는 사슬이 성립하지 않는다.**

**(d-2) 엣지 포트 선점을 먼저 확인한다.** 컴퓨터에서 `4317`(엣지 Collector 수신)·`8889`(엣지
Collector exporter)·`9090`(엣지 Prometheus)이 비어 있어야 한다.

```powershell
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in 4317,8889,9090 }
```

**비어 있지 않으면 포트를 바꾸고 그 사실을 보고한다** — 서버 설정(페더레이션 타깃 포트)이
함께 바뀐다.

**(e) 검증 후 되돌린다 — 엣지를 먼저 내린다.** 바인딩을 먼저 지우면 엣지 Collector가 전송 실패를
쌓는다. 순서는 **엣지 프로세스 정지 → ufw 규칙 삭제 → compose 바인딩 주석 → `up -d`**다.
엣지는 임시물이고 Tailscale 계정도 임시다. **인증 없는 OTLP 포트를
tailnet에 열어둔 채 두지 않는다.**

```bash
sudo ufw delete allow from <엣지 tailscale IP>/32 to any port 4316 proto tcp
# compose 의 tailscale 바인딩 한 줄을 주석으로 내린다 → Phase 4 에서 주소만 바꿔 되살린다
docker compose up -d otel-collector
```

**8-7 DoD:**
1. `ss`에 **4316이 두 주소에 LISTEN**한다(`127.0.0.1`과 서버 tailscale IP).
2. 엣지 Collector `validate`가 `exit=0`이고 기동 로그에 **파이프라인 3종**이 나타난다.
3. **엣지에서 보낸 로그가 서버 Loki에서 조회된다** — `{service_name="hw-sensor-node"}`(또는
   발신자가 쓴 이름)가 방금 시각 범위로 나온다. **서버 백엔드 로그(`be-*`)와 구분되어야 한다.**
4. **엣지에서 보낸 span이 서버 Tempo에서 조회된다** — `service.name` 태그값에 엣지 서비스 이름이
   나타난다(단계 0에서 `[]`였다).
5. **음성 — 엣지 metric은 이 길로 오지 않는다.** 엣지 Collector의 `metrics` 파이프라인 exporter가
   `prometheus` 하나뿐이고, 서버 Prometheus에 들어온 B층 시계열은 **전부 `agg_layer="edge"`**다
   (= 페더레이션으로 온 것이지 OTLP 직송이 아니다).
6. **음성 — 백엔드 경로가 안 깨졌다.** 바인딩을 더한 뒤에도 `127.0.0.1:4316`으로 보내는 백엔드
   3개의 `be_*` 지표가 계속 갱신된다.
7. **음성 — ufw가 엣지로 제한됐다.** `ufw status`에 `Anywhere`가 아니라 엣지 주소가 보인다.
8. (e)를 이행해 **ufw 규칙이 지워지고 compose의 tailscale 바인딩이 주석**으로 내려갔다.

---

### 단계 9 — pytest 회귀와 음성 대조

**기준선은 104건이다. 이것이 계속 통과해야 한다.**

**9-A. 새 테스트** — `tests/conftest.py`의 skip fixture 패턴을 그대로 쓴다. Prometheus·Loki 접속
실패는 `pytest.skip`으로 바꾼다(인프라가 없으면 그 테스트만 건너뛴다).

| 파일 | 무엇 | 인프라 |
|---|---|---|
| `tests/test_observability_labels.py` | 라벨 가드 단위 — **금지 라벨 거부(음성)** · A층에 `source_id` 거부(음성) · 허용 라벨 통과(양성) | 없음 |
| `tests/test_c_layer_extract.py` | `$comment` 힌트 파싱이 **gauge 9 · counter 3 · log/event 10**을 뽑는다 · 중첩(`buffer.*`) 포함 · `{value,state}` 벗기기 · `null` 미기록(음성) | 없음 |
| `tests/test_observability_pipeline.py` | 발행 → `be_*` 지표가 Prometheus에 도달 · Loki에 백엔드 로그 도달 · **가짜 span 1건이 Tempo에 꽂힘** | Prometheus·Loki·Tempo |
| `tests/test_observability_isolation.py` | **관측 저장소가 죽어도 업무 경로가 계속 돈다**(음성 대조의 핵심) | Kafka·TSDB |

> **테스트에서 Prometheus·Loki·Tempo를 질의할 때 새 의존성을 만들지 않는다.** `requests`를
> 넣지 말고 **표준 라이브러리 `urllib.request`**를 쓴다. 접속 실패는 `conftest.py`의 기존 패턴대로
> `pytest.skip`으로 바꾼다.

**9-B. 음성 대조 7건 — "지표가 나온다"만 보는 판정을 막는다**

| 음성 | 무엇을 막는가 | 어떻게 확인하나 |
|---|---|---|
| N1 | **금지 라벨이 실제로 거부된다** | `observability.count("be.ingest.received", session_id="x")` → `ValueError`. 조용히 버리지 않는다 |
| N2 | **A층에 `source_id`가 못 들어간다** | 위와 같은 방식으로 `ValueError` |
| N3 | **관측이 죽어도 업무가 산다** | `docker compose stop otel-collector` → 발행 → **TSDB 행 수가 늘고** 소비자가 죽지 않는다 → `docker compose up -d otel-collector`로 복구. **`MK2_OTEL_ENDPOINT=""`로도 같은 확인** |
| N4 | **없는 값이 0으로 둔갑하지 않는다** | `water_level_m`을 `{"value":null,"state":"unavailable"}`로 발행 → 해당 시계열 **미생성** |
| N5 | **페더레이션이 raw를 안 당긴다** | `match[]` 밖 지표가 서버에 `agg_layer="edge"`로 **0건** |
| N6 | **엣지 metric이 OTLP 직송으로 새지 않는다** | 서버의 B층 시계열이 **전부 `agg_layer="edge"`**(= 페더레이션 경유). 하나라도 라벨이 없으면 Agent 의 metrics 파이프라인이 서버로 새고 있는 것이다 |
| N7 | **Tailscale 바인딩을 더해도 백엔드 경로가 안 깨진다** | 8-7(a) 적용 뒤 `127.0.0.1:4316` 으로 가는 `be_*` 지표가 계속 갱신된다 |

**9-C. 실제로 흐른 것을 무엇으로 판정하나** — "떠 있다"로 판정하지 않는다.

| 대상 | 판정 근거 |
|---|---|
| metric | Prometheus에 `be_*` 시계열이 **존재하고, 발행을 멈춘 뒤 값이 더 이상 갱신되지 않는다**(살아 있는 표본이지 잔상이 아님) |
| log | Loki에서 `{service_name="be-ingest"}`가 **방금 시각 범위**로 조회된다 |
| trace | Tempo의 `service.name` 태그값에 **가짜 span의 서비스 이름이 나타난다**(단계 0에서 `[]`였다) |
| 페더레이션 | 서버에서 `agg_layer="edge"` 라벨이 붙은 시계열이 조회된다 |
| A층 | `be_ingest_rejected_total{stage="payload"}`가 **음성 fixture 발행 후 실제로 증가**한다 |

**DoD:**
1. **`pytest -q`가 104 + 신규 전건 통과.** skip은 인프라가 없는 경우에만.
2. **단계 9-B의 음성 대조 7건**이 전부 실제로 거부·유지되는 것을 확인했다.
3. **단계 9-C의 다섯 판정**이 전부 참이다.

---

### 단계 10 — 타 파트 회신·통지 초안

**Phase 2가 쓴 규율을 따른다** — 머리말 표(보내는 쪽/받는 쪽/작성일/근거/대상 안건) · 모든 주장에
근거(`파일:줄` 또는 요구사항 ID) · 각 물음에 **「우리는 이렇게 읽었다」**와 **「답이 없으면 이
기본값으로 간다」** · 상대 코드 변경 요청은 **before/after** · 우선순위 표시 · 끝에 **「상대가 할 일」**.
실례는 `hw-envelope-conformance.md` §6과 `vz-mission-record-inquiry.md`다.

**10-1. HW 회신 — `hw-envelope-conformance.md`에 §7 신설 (확정 산출물)**

`BACKEND_AGENDA` §10-3 *"명령에 trace 컨텍스트를 실어 보낼 계획이 있는가? 있다면 W3C
`traceparent`인가?"*에 답한다.

담을 것:
- **답: 싣는다. W3C `traceparent`, protobuf 본문 필드.** `tracestate`는 넣지 않는다.
- **왜 본문인가** — Phase 2가 `ingest_at`·`entity_type`을 Kafka 헤더에 실은 것은 *"HW가 보낸 원본
  JSON 바이트를 건드리지 않는다"*는 이유였는데, **명령은 백엔드가 만드는 메시지라 지킬 원본이 없다.**
  그리고 `otel_trace.py`의 `_CmdTrace.__init__`이 `extract(carrier=cmd)`로 **본문에서 찾도록 이미
  짜여 있다.**
- **HW 작업량(§5-A)** — `.proto`에 필드 1개, 그리고 **protobuf 객체에서 값을 꺼내 dict로 넘기는
  배선 한 줄이 필요할 수 있다.** *"코드 변경 없음"이 아니다.*
- **확인 요청 2건:** ① `.proto` 필드 번호를 누가 정하나 ② **옛 말단이 새 필드가 붙은 명령을
  받아도 깨지지 않는가**
- **시점:** 실배선은 **Phase 6**. `BACKEND_AGENDA` §3(문자열/열거형 파라미터)이 같은 `.proto`를
  어차피 고치므로 **한 번에 처리한다.**
- **답이 없으면의 기본값:** *"HW는 현행대로 두면 된다. 필드가 없으면 새 trace를 시작하는 지금
  동작이 맞고, Phase 6에서 필드가 들어오면 자동으로 이어 붙는다."*
- **우선순위 ⚪** — Phase 6 착수 전까지면 재작업이 없다.
- **정보 한 줄:** `otel_metrics.py` 머리말 주석이 아직 *"export 주기 60초"*라고 적고 있으나
  **동작은 `config.OTEL_EXPORT_INTERVAL`(15초)**이고 §10-1이 15초로 종결했다. 주석만 낡았다.
- **§5의 *"§10-3 → Phase 3 이후 회신"*을 ✅로 닫고 §7을 가리키게 한다.**

**10-2. 가시화 통지 — `docs/be/vz-observability-namespace.md` 신설**

VZ-O-04(*"자체 관측 지표 발행"*)가 가시화도 같은 관측 스택에 직접 발행할 것을 예고한다.
**`00-architecture.md` §8-3의 3층에 가시화 자리가 없어 네 번째 생산자가 된다.** 이름 공간이 충돌하지 않게 통지한다.

담을 것: 파트 접두사 규약(`hw.`/`be.`/**`vz.` 권고**) · **라벨 금지 목록 전수**(`session_id`·
`internal_seq`·`sequence_id`·시각·프레임 식별자)와 그 이유(시계열 폭증) · `service.name`을
컴포넌트별로 가르기 · **발신 대상은 서버 Collector `127.0.0.1:4316`** · 실측 근거(현재 `vz_`
접두사 충돌 0) · 답이 없으면의 기본값(*"백엔드는 `be.`만 쓰므로 충돌은 나지 않는다. 다만 가시화가
접두사 없이 발행하면 나중에 분리가 어렵다"*) · 우선순위 **🟡**(가시화가 발행을 시작하기 전).

**DoD:** 두 문서가 위 규율대로 작성되고, 모든 주장에 근거가 붙어 있다. **전달 여부는 사용자가
정한다** — 지시서는 초안까지다.

---

## 8. 이번에 하지 않는 것 (범위 울타리)

**하나라도 넘으면 범위 확대다.** 필요해 보이면 한 줄로 묻고 넘어간다(`CLAUDE.md` §1-A 규율 5).

1. **가용성 판정 = Phase 5.** 관측 신호로 *"장치가 살았나"*를 판정하지 않는다. Phase 3은 신호가
   흐르게만 하고, 통합 판정(업무 평면 우선)은 Phase 5다.
2. **C층 log/event 10개 = Phase 5.** 상태 전이 판정과 같은 자리다(결정 5-b).
3. **미디어 = Phase 4.** **Kafka 원격 노출 = Phase 4.**
4. **WS 게이트웨이 본구현 = Phase 5/7.** 이번엔 push 건수·접속 수 계측만.
5. **명령·감사 기록 로직과 인증·인가(RBAC) = Phase 6.** **traceparent를 실제 명령에 싣는 배선도
   Phase 6이다** — 이번엔 답과 회신 초안까지.
6. **지표 질의 프록시(BE-Q-01)·조회 API = Phase 5/6.** 이번엔 저장·수집까지다.
7. **실행 기록의 구체 필드·되감기 질의 = 가시화 회신 후(Phase 6/7).**
8. **TSDB 보존 기간·재난 구간 아카이브(BE-S-04) = 발동 조건 충족 시.** ⚠ **관측 쪽 보존(Loki·
   Tempo·Prometheus)은 이번 범위다.** 업무 데이터 보존과 관측 데이터 보존은 다른 사안이다.
9. **Prometheus 보존 변경 = 하지 않는다**(결정 3-b). 기록만.
10. **호스트 포트 번호 변경 = 하지 않는다**(결정 2). Collector는 4316, Tempo는 4317 그대로.
11. **`registry_identity_history`의 `UPDATE` 권한 회수 = 하지 않는다.** Phase 2 미결이며 검수 후
    결정 사항이다. 기록만(§10-4).
12. **MySQL `0.0.0.0:7858` + `root@%` = Phase 6.** 다른 파트가 쓰는 컨테이너다.
13. **검증용 컨슈머 그룹 정리 = 하지 않는다.** 무해하며 정리 여부는 미결이다.
14. **분류 ③ 자산 무변경** — Redis·MongoDB·두 Pushgateway·`robot_server` 잡·`conntest`.
    `prometheus.yml`의 `rpi_pushgateway`·`thermal_pushgateway` **잡 본문을 건드리지 않는다**
    (주석만 고친다).
15. **Phase 1·2가 확정한 것을 재설계하지 않는다**(제약 19).
16. **엣지 OTLP 수신단에 인증·TLS를 붙이지 않는다.** 8-7은 터널 안 평문이고 ufw를 엣지 주소로 제한한다. TLS·인증은 BE-T-08(Phase 4)이다. **그리고 검증이 끝나면 8-7(e)로 되돌린다.**
17. **compose `version` 경고 = 하지 않는다.** Phase 2 울타리를 유지한다.

---

## 9. 완료 판정 (체크리스트)

**아래가 전부 참이어야 이 작업이 끝난 것이다.** 각 항목에 검증 수단을 붙였다.
`CLAUDE.md` §3 — **테스트 없는 완료 금지**, 완료는 "특정 기술을 썼나"가 아니라 **"동작과 허용
범위가 실제로 보장되는가"**로 판정한다.

### 9-1. 착수·규율

| # | 항목 | 검증 |
|---|---|---|
| 1 | 단계 0 결과를 **받은 뒤** 착수했다 | 대조 로그 |
| 2 | 관측 5개 외 **다른 컨테이너가 재생성되지 않았다** | `docker ps`의 `Up ...` 유지 |
| 3 | 설정 파일 4개를 고치기 전에 **백업했다** | `.bak_before_phase3` 존재 |
| 4 | `loki_data`를 **백업한 뒤** 비웠다 | `~/loki_data.bak_before_phase3.tgz` 존재 |
| 5 | 비밀값·내부망 IP·**Tailscale 주소**가 커밋되지 않았다 | `git status` + `git check-ignore` |
| 6 | 전 산출물이 **UTF-8 · LF** | CRLF 0 · BOM 없음 |

### 9-2. 상주 프로세스 (결정 1)

| # | 항목 | 검증 |
|---|---|---|
| 7 | unit 3개가 `active (running)` · `enabled` | `systemctl status` · `is-enabled` |
| 8 | 재기동해도 **TSDB 행이 재소비로 늘지 않는다** | 재시작 전후 `count(*)` 대조 |
| 9 | 재기동 시 retained `status` 재유입이 **로그로 확인**되고 정상으로 문서화됐다 | journald + 보고서 |

### 9-3. 관측 스택 (결정 2·3)

| # | 항목 | 검증 |
|---|---|---|
| 10 | Collector 이미지가 **digest로 고정**됐다 | `docker inspect ... .Config.Image` |
| 11 | Collector 설정이 **`validate` 통과**하고 파이프라인 **3종**이 기동 로그에 나타난다 | `validate exit=0` + 로그 |
| 12 | **Loki가 v13/tsdb**이고 `allow_structured_metadata: true` | `/config` 실측 |
| 13 | **Loki 보존 3줄이 전부 켜졌다** — `retention_enabled: true` · `retention_period: 14d` · `delete_request_store` 비어 있지 않음 | `/config` 실측 |
| 14 | Tempo `block_retention: 168h` | `/ready` + 설정 실측 |
| 15 | **`otel_collector` 잡만 `5s`**이고 **global·다른 네 잡이 단계 0과 동일** | `/api/v1/targets` 대조 |

### 9-4. A층 (결정 4) — **BE-S-02·BE-S-07의 핵심**

| # | 항목 | 검증 |
|---|---|---|
| 16 | **A층 지표 9종이 Prometheus에서 조회된다** | `__name__` 목록에 `be_*` |
| 17 | **A층 라벨에 `source_id`가 없다** | `/api/v1/series` 라벨 집합 |
| 18 | **`be_ingest_rejected_total{stage="payload"}`가 음성 fixture 발행 후 증가한다** | 발행 전후 값 대조 |
| 19 | **`be_pipeline_lag_seconds`가 `telemetry.lag_s`를 담는다** — 음수도 버리지 않는다 | 히스토그램 `_sum`/`_count` + TSDB 대조 |
| 20 | **백엔드 로그가 Loki에 도달한다** | `{service_name="be-ingest"}` 최근 범위 질의 |
| 21 | **가짜 span 1건이 Tempo에 꽂힌다** | `service.name` 태그값이 단계 0의 `[]`에서 늘어난다 |

### 9-5. C층 (결정 5)

| # | 항목 | 검증 |
|---|---|---|
| 22 | **`$comment` 파싱이 gauge 9 · counter 3 · log/event 10을 뽑는다**(중첩 포함) | `test_c_layer_extract` |
| 23 | **`be_telemetry_*` 12종이 Prometheus에서 조회된다** | `__name__` 목록 |
| 24 | C층 라벨이 `source_id`·`zone_id`·`entity_type`·`channel`이고 금지 라벨이 없다 | `/api/v1/series` |
| 25 | **`{value:null,state:...}`·명시적 `null`이 시계열을 만들지 않는다**(음성) | `test_c_layer_extract` + 실발행 |
| 26 | **원본이 여전히 TSDB다** — 같은 발행분이 `telemetry`에 그대로 있다 | 행 수·값 대조 |
| 27 | log/event 10개는 **계측하지 않았고** Phase 5 이월로 적혔다 | plan 갱신분 |

### 9-6. 2계층 (결정 6) — **BE-S-03·BE-S-06**

| # | 항목 | 검증 |
|---|---|---|
| 28 | Tailscale로 서버↔엣지가 붙는다 | `tailscale status` · `ping` |
| 29 | 엣지 Prometheus에 **B층 5종**이 쌓인다 | 엣지 `__name__` 목록 |
| 30 | **서버에서 `edge_federate` 타깃이 `up`, interval `15s`** | `/api/v1/targets` |
| 31 | **페더레이션 요약이 실제로 당겨졌다** — 서버에서 `agg_layer="edge"` 라벨이 붙은 B층 시계열이 조회된다 | 서버 질의 ← **plan DoD 원문의 충족 근거** |
| 32 | **음성 — raw가 안 온다.** `match[]` 밖 지표가 서버에 `agg_layer="edge"`로 0건 | 서버 질의 |
| 33 | **음성 — 경계가 갈린다.** 서버 자체 수집분(`be_*`)에 `agg_layer` 라벨이 없다 | 서버 질의 |
| 34 | **원칙 6 — 장치 생사·치명 오류가 요약에 섞이지 않았다** | `match[]` 내용 확인 |
| 35 | **Agent→Gateway 사슬이 닫혔다** — 엣지가 보낸 **로그가 서버 Loki에**, **span이 서버 Tempo에** 조회되고 서버 백엔드(`be-*`) 것과 구분된다 | Loki·Tempo 질의 |
| 36 | **음성 — 엣지 metric은 OTLP 직송으로 오지 않는다.** 서버의 B층 시계열이 전부 `agg_layer="edge"`(= 페더레이션 경유) | 서버 질의 |
| 37 | **음성 — 백엔드 경로가 안 깨졌다.** Tailscale 바인딩을 더한 뒤에도 `127.0.0.1:4316`으로 가는 `be_*`가 계속 갱신된다 | 서버 질의 |
| 38 | **ufw 4316이 `Anywhere`가 아니라 엣지 주소로 제한됐다** | `ufw status numbered` |
| 39 | **8-7(e)로 되돌렸다** — ufw 규칙 삭제 + compose의 tailscale 바인딩 주석 처리 | 규칙·파일 확인 |
| 40 | 엣지 흔적이 `edge_probe\` 폴더 하나로 격리됐고, **Windows 방화벽 규칙이 지워졌으며**, 서버에는 **주석 처리된 `edge_federate` 잡**만 남는다 | 파일·규칙 확인 |

### 9-7. 회귀와 격리

| # | 항목 | 검증 |
|---|---|---|
| 41 | **pytest 104 + 신규 전건 통과**, skip 0(서버) | `pytest -q` |
| 42 | **음성 대조 7건이 실제로 거부·유지된다**(**단계 9-B** 표) | 각 테스트 |
| 43 | **관측 저장소가 죽어도 업무 경로가 계속 돈다** | Collector 정지 중 TSDB 적재 지속 |
| 44 | **`MK2_OTEL_ENDPOINT=""`로도 정상 동작**(no-op 규율) | 기동 + 발행 |
| 45 | 컴퓨터에서 돌리면 **인프라 의존 테스트만 skip**되고 나머지는 통과 | 양방향 확인 |

### 9-8. 산출물

| # | 항목 |
|---|---|
| 46 | HW 회신 `hw-envelope-conformance.md` **§7** 작성, §5의 해당 줄을 ✅로 닫음 |
| 47 | 가시화 통지 `docs/be/vz-observability-namespace.md` 작성 |
| 48 | **§10-1 ~ §10-6을 전부 이행**했다 — 보고서 · plan · `infra/README.md` · 추적표 · `contracts/common/README.md` · `prometheus.yml` 주석. **개수로 세지 말고 절 단위로 대조한다**(Phase 2 지시서가 *"§10의 보고 3종"*이라 적고 본문은 넷이었던 전례) |

> **검증 범위의 한계 — "검증됨"으로 적지 않을 것.** ① **엣지는 컴퓨터 대역이다.** 전용 장비·현장
> 회선·다구역은 검증되지 않는다. ② **B층은 가짜 지표 발신이다.** 실 말단은 `HW_OTEL_ENDPOINT`가
> 꺼져 있다. ③ **`state.analysis` C층 3종은 생산자가 없어 실값이 없다.** ④ **백엔드 span은 가짜
> 1건**이고 실제 추적 생산은 Phase 6이다. ⑤ **Tailscale은 임시 계정**이다.

---

## 10. 보고 — 작업 끝에 무엇을 남기나

`CLAUDE.md` §1-A **규율 8**을 이 Phase에서 발동시키는 자리다. **보고서에만 적고 끝내지 않는다** —
보고서는 직전 세션만 읽으므로, 몇 Phase 뒤에 쓰일 발견은 **plan·추적표에 적어야 그 시점에 살아난다.**

### 10-1. `reports/2026-MM-DD_HHMM_phase3_관측파이프라인.md` 생성

배경 / 한 일 / 검증 / 다음. **반드시 담을 절 넷:**

- **「서버에 남은 것」** — 다음 지시서의 「이미 확인된 서버 상태」 재료. Phase 2 보고서가 이 절을
  빠뜨렸다가 재검수에서 추가한 전례가 있다. **로그로 확인된 것만 적는다.**
- **「검증 범위의 한계」** — §9 끝의 다섯 항목.
- **「발견한 것」** — 최소 이 셋을 포함한다:
  ① **C층 counter 3개는 절대 누적값이라 gauge 계기로 기록했다**(`$comment`와 계기 종류가 다르다).
  ② `components` 목록이 정식명+별칭 쌍 4개를 빠뜨린다 — **컴포넌트 유무는 `validate`로 판정한다.**
  ③ 재기동마다 retained `status`가 A층 카운터에 잡힌다.
- **「사용자가 결정한 것」** — 착수 결정 7개 중 사용자가 정한 것과 구현자 판단을 가른다.

### 10-2. `docs/be/01-standalone-implementation-plan.md` 갱신

- Phase 3 절에 **✅ 완료**와 확정 결과를 단다. Phase 0 이월 4건 · Phase 2 이월 4건에 **항목마다
  ✅와 한 줄 결과**를 붙인다(처리 후에도 현재형으로 읽히지 않게).
- **§3 「지금 당장 할 일」의 ⑤를 닫고 ⑥(Phase 4)을 다음으로 표시.**
- **⚠ 정정 — Loki 소급.** Phase 3 절의 *"로그를 흘리기 전에 걸어야 한다. 흘린 뒤 걸면 이미 쌓인
  것은 안 지워진다"*는 **틀렸다.** retention은 compactor가 나이 기준으로 집행해 **소급된다.**
  *"순서 주의"* 표기를 내리고 **권장**으로 고친다.
- **⚠ 정정 — 라벨 금지 목록.** Phase 3 이월이 `session_id`·`internal_seq` **둘만** 적었는데
  규격 파일의 전수는 `sequence_id`·시각·프레임 식별자를 포함한다. 전수와 맞춘다.
- **이월 신설:**
  - **Phase 4** — ① **Collector의 Tailscale 바인딩과 ufw 규칙을 되살린다**(8-7(e)에서 주석으로 내려둔
    한 줄). **엣지 OTLP 수신단의 TLS·인증은 BE-T-08이다** — Phase 3은 터널 안 평문이었다
    ② **Tailscale 계정을 팀 계정으로 옮기면 IP가 바뀌어 `prometheus.yml` 타깃과 Collector 바인딩을
    고쳐야 한다** ③ Prometheus 이미지 digest 고정(컨테이너 재생성이 따라오므로 다른 작업과 묶어서)
  - **Phase 5** — **C층 log/event 10개를 상태 전이 판정과 함께 계측한다**(결정 5-b)
  - **Phase 6** — **`.proto` 개정에 `traceparent` 필드를 함께 넣는다.** §3(문자열/열거형 파라미터)와
    같은 개정이다. **안 적으면 그 시점에 따로 떠오르지 않는다**

### 10-3. `infra/README.md` 갱신 — **이번 Phase가 관측 스택을 직접 고쳤으므로 필수다**

| 절 | 무엇 |
|---|---|
| **§2 스택 표** | **분류표 신설**(① MK2 신설 / ② 기존 가동+역할 배정 / ③ 무관). *"떠 있으니 쓰자"*를 막는 장치 |
| **§3 포트 표** | **「4316/4317 사연」을 두 절로 가른다.** 지금은 *"포트 충돌은 증상이고 원인은 구조 … 이 정리는 Phase 3에서 한다"*가 한 문단이라 **"Phase 3에서 포트를 옮긴다"로 읽힌다.** ⓐ 구조: Collector가 log·trace를 분배한다(= Phase 3이 한 일) ⓑ 호스트 포트 번호: 4316에 둔 채로 둔다(= 별개 사안, 바꾸지 않음). **한 절에 붙여 두면 한 덩어리로 읽힌다는 것이 이번에 실제로 일어난 일이다** |
| **§4 헬스 확인** | 9개 블록에 **"무엇이 실제로 흐르는지"**를 더한다 — Collector 파이프라인 3종 각각(Prometheus `be_*` 조회 · Loki `{service_name=...}` · Tempo `service.name` 태그). **"떠 있다"만 보는 확인을 고친다** |
| **§5** | Collector 이미지 digest 고정 사유. **컴포넌트 이름이 스네이크 케이스로 개명 중**이라 설정에 쓰는 이름이 버전에 따라 갈린다는 것(`:latest`와 겹치면 조용히 깨진다) |
| **§6 알려진 사항** | ⓐ Collector 행 — *"Phase 3 핵심"*을 **한 일로** 구체화 ⓑ Loki 행 — *"retention 없음"* → **"보존을 집행할 기능이 꺼져 있었다(세 줄)"**, 그리고 **v11+boltdb-shipper가 폐기 대상이며 그래서 OTLP를 못 받았다**는 결과 ⓒ **관측 3종의 실사용 현황 신설** — Collector 10일간 0건 · Tempo 이력 전체 0건 · Loki 7개월간 0건 · **Prometheus만 살아 있고 그 데이터는 전부 분류 ③의 것** ⓓ Tempo 4317이 `0.0.0.0`+ufw 개방이라 **Collector 우회 입구가 열려 있다 — 이번에 닫지 않고 기록만** ⓔ Prometheus 보존은 **CLI 기본값 15d에 기대고 있다** ⓕ `prometheus.yml`에 **`conntest` 출처 미상** ⓖ `registry_identity_history` `UPDATE` 미결 유지 ⓗ **Collector 4316의 Tailscale 바인딩과 ufw 규칙은 Phase 3 검증 후 되돌렸다**(주석 한 줄) — 되살리는 조건·절차와 **인증이 없다는 사실**을 함께 적는다 |
| **§1 `.env`** | **systemd `EnvironmentFile`을 파서 목록에 추가.** 이제 셋이고 인용부호 규칙이 다르다 — 특수문자 금지의 이유가 하나 더 늘었다 |

### 10-4. `docs/be/requirement-traceability.md` 갱신

| ID | 상태 | 담을 내용 |
|---|---|---|
| **BE-S-02** | **부분 유지** | 구현 위치에 파이프라인 3종·A층 9종·어댑터·테스트를 적는다. **Agent→Gateway 사슬이 실증됐다**(엣지 log·trace 원본이 서버 Collector를 거쳐 Loki·Tempo에 도달). **gap:** ① **Agent는 컴퓨터 대역이고 전용 엣지 장비가 없다. 수신단에 인증·TLS가 없다(BE-T-08, Phase 4)** ② B층 실 지표는 `HW_OTEL_ENDPOINT`가 꺼져 있어 가짜 발신으로만 검증 ③ 백엔드 span 생산은 Phase 6. **완료로 올리지 않는 이유를 명시한다** |
| **BE-S-03** | **부분 유지** | 페더레이션 2계층이 **임시 엣지로 실증**됐음을 적는다. **gap:** 전용 엣지 장비·다구역 미검증, 발동 조건은 `00-architecture.md` §8-5 |
| **BE-S-06** | 미착수 → **부분** | **집약 계층 경계 표기 규약 확정**(`agg_layer="edge"`, 부재=중앙) + 페더레이션에 적용·음성 대조. **gap:** 다구역에서의 표기 확장 미검증 |
| **BE-S-07** | 미착수 → **부분** | **측정 수단이 생겼다** — `be.pipeline.lag`가 `telemetry.lag_s`를 관측 평면에 올린다. **gap:** ① **상한을 판정·경보하는 로직이 없다**(값만 쌓인다) ② 재난 고주기 실측은 Tier C ③ **`clock_skew` 임계를 이번에 확정하지 못했다** — `lag_s`가 채워진 행이 415 중 41뿐이고 양 끝(`-30.000`·retained 재유입 344,000초)이 전부 인공물이라 **분포를 정할 재료가 못 된다.** A층으로 쌓은 뒤 Phase 5에서 확정 |
| 요약 | 갱신 | 총계·「Phase 3에서 바뀐 행」 절 추가 |

### 10-5. `contracts/common/README.md` 갱신

**「관측 신호 힌트와 라벨 금지」 절의 표가 부분 목록이다.** 규격 파일 전수와 어긋난다.

| 종류 | 표에 적힌 것 | 실제 전수 | 빠진 것 |
|---|---|---|---|
| gauge | 7개 | **9개** | `eta_to_threshold_min` · `buffer.pending` |
| counter | 3개 | 3개 | — |
| log/event | 9개 | **10개** | `status`(`status.schema.json`의 `status` 항목) |

**기준은 스키마 파일이라는 원칙은 그대로 두고, 표를 전수와 맞춘다.** 그리고 라벨 금지 목록이
이미 전수(`sequence_id` 포함)인 것을 확인하고, **A층/C층의 라벨 기준이 다르다**는 결정 4-b를
이 절에 한 줄로 더한다.

### 10-6. `infra/config/prometheus.yml` 주석 정정

머리말의 `before/after` 블록과 본문 `[수정 260903]` 주석이 `rpi-pushgateway:9091` 우회를 말하는데
**그 우회는 폐기됐다.** ufw에 9100을 열어 해결했고 실제 타깃은 `host.docker.internal:9100`이며
`up`이다. **주석만 고치고 잡 본문은 건드리지 않는다**(분류 ③).

### 10-7. 막히면

**임의로 정하지 말고 `reports/`에 남기고 멈춘다.** 특히 공통 규격 변경·채널 추가·저장 모델 변경·
가용성 판정 규칙·포트/주소/인증은 프로젝트 전체가 걸린 결정이라 혼자 바꾸지 않는다.
**지시서와 현실이 다르면 차이를 먼저 보고하고 결정을 받는다**(규율 3).
