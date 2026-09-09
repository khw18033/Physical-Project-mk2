# 작업 지시서 — Phase 2 저장 축 (계측 TSDB + 감사·레지스트리·실행 기록 MySQL)

## 1. 머리말

| | |
|---|---|
| **대상** | Phase 2 — 저장 축을 실제로 세운다 |
| **착수** | Phase 1(얇은 파이프라인 관통, 2026-09-07) 완료 + 기반문서 보강 3라운드(2026-09-09) 이후 |
| **근거 문서** | [`docs/be/01-standalone-implementation-plan.md`](../01-standalone-implementation-plan.md) Phase 2 절 · [`docs/be/00-architecture.md`](../00-architecture.md) §5~§6(특히 §6-2 저장 분리)·§8-3(관측 신호 3층)·§8-5(유예 항목) · [`docs/be/requirement-traceability.md`](../requirement-traceability.md) · [`../../CLAUDE.md`](../../../CLAUDE.md) §1·§1-A·§2 |
| **관련 요구사항** | BE-S-01(시계열 저장) · BE-S-05(감사 MySQL) · BE-S-08(임무 실행 기록) · BE-C-01(공통 규격, 본문 확장) · BE-C-02(식별자 계층) · BE-Q-03(레지스트리) |
| **저장 위치** | `docs/be/tasks/작업지시_phase2_저장축.md`. Phase 2 구현이 끝나면 `docs/be/tasks/_archive/`로 옮긴다(누적 참조 대상이 아니다) |

> 이 문서는 VS Code Claude Code가 읽고 구현하는 인수인계 문서다. `CLAUDE.md`와 이 지시서를 함께 읽고, 지시서 범위대로 구현한다. **설계는 끝났으므로 새로 설계하지 않는다.**

---

## 2. 배경

### 2-1. 무엇을 딛고 서는가

Phase 1이 **얇은 파이프라인을 관통**시켰다 — 가짜 발행자·실노드 양쪽에서 `state`·`status`·`heartbeat` 3채널이 MQTT → 공통 헤더 strict 검증 → Kafka 3토픽 → 저장 sink + WS까지 도달했고, 공통 헤더 불합격은 격리됐다(pytest 6건 통과, 종단 지연 약 9ms 실측).

그때 **저장은 일부러 비워 두었다.** `backend/storage/writer.py`의 `TelemetryWriter.write()`는 목적 인터페이스이고 구현은 JSONL placeholder다. **Phase 2는 그 인터페이스 뒤만 갈아끼운다** — 그러라고 나눠 둔 지점이다.

> ⚠ **"호출부 무변경"의 정확한 범위.** plan Phase 2의 *"이 몸통만 TSDB writer로 갈아끼우고 ingest·소비자·인터페이스는 건드리지 않는다"* 는 **계측 저장 제품 교체에 한정된 말**이다. 이번 Phase에는 **새 기능 둘이 함께 들어오므로 호출부가 늘어난다** — `ingest_at`·`entity_type` 헤더(단계 5)와 레지스트리 관측 축 쓰기(단계 7). 이 둘은 "저장 제품 교체"가 아니라 신규 배선이다.
>
> **지켜야 하는 것은 문장이 아니라 그 문장의 목적이다** — 상위 로직이 저장 제품 API를 직접 부르지 않는 것(원칙 1). 그래서 늘어나는 배선도 **목적 인터페이스 뒤**에 둔다:
>
> | 무엇 | 호출부 | 인터페이스 | 구현 |
> |---|---|---|---|
> | 계측 | `consumer.py` | `TelemetryWriter.write(record)` **(기존, 시그니처 무변경)** | TSDB writer로 교체 |
> | 레지스트리 | `consumer.py` | **`RegistryWriter.observe(record)` (신설)** | MySQL writer |
>
> `consumer.py`는 이 **두 인터페이스만** 알고 MySQL·psycopg 클라이언트를 직접 만들지 않는다. `TelemetryWriter`가 레지스트리까지 겸하게 만들지 않는다 — 이름과 책임이 어긋나고, 계측 저장을 갈아끼울 때 레지스트리가 딸려 온다.

MySQL은 Phase 0부터 컨테이너만 돌고 있고 **MK2 전용 DB·계정·테이블이 없다.** TSDB는 제품 미확정이라 Phase 0에서 제외됐다.

### 2-2. 이번에 저장하는 것은 넷이다

옛 계획서가 "저장 2축"이라 부르던 것이 BE-S-08(임무 실행 기록)이 Phase 2로 들어오면서 넷이 됐다.

| 저장 대상 | 저장소 | 답하는 질문 | 이번 범위 |
|---|---|---|---|
| **계측 추이** | TimescaleDB | 값이 시간에 따라 어떻게 변했나 | 전부 |
| **신원 대장(레지스트리)** | MySQL | 무엇이 있는가 | 스키마 + 관측 축 쓰기 경로 |
| **사건 책임(감사)** | MySQL | 무슨 일이 일어났는가 | **스키마만** |
| **임무 사건 열(실행 기록)** | MySQL | 임무가 어디까지 갔는가 | **스키마 + append 경로만** |

감사와 실행 기록은 둘 다 사건이지만 **조회 패턴이 다르다** — 감사는 대상·기간·조작자로 **검색**하고, 실행 기록은 시점을 지정해 그 시점 상태를 **복원**한다. 그래서 같은 MySQL의 다른 테이블로 나눈다(`00-architecture.md` §6-2).

### 2-3. 착수 전 확정된 결정 다섯 (설계방, 2026-09-09)

| # | 결정 | 요지 |
|---|---|---|
| 1 | **TSDB 제품** | **TimescaleDB**(PostgreSQL 확장, Community Edition, 자체 운영) |
| 2 | **MySQL DB·계정·테이블 범위** | DB `mk2` / 계정 `mk2_app` / 레지스트리는 **선언·관측 2축** / 실행 기록은 골격 + append / 감사는 **대상 일반화** |
| 3 | **적재 시각 기준** | 시간축 = 발행 `timestamp`, `ingest_at` 신설, `replayed` + `lag_s` 보관, **UTC 저장**, 유일 키 = **스트림 좌표** |
| 4 | **`sequence_id` 의미** | `(source_id, channel, session_id)` 단위 · 채널별 의미 차등 · **`session_id` 신설** · 검출은 조회 시점 |
| 5 | **채널 본문 규격** | 본문 스키마 신설 + **느슨한 2단 검증** · **etype로 타입 분기** · 누락값 목록 확정 |

각 결정의 근거·트레이드오프·대안 배제 사유는 §11 부록 A에 남겨 두었다. **구현 중 이 결정을 바꾸지 않는다.**

### 2-4. 설계 중 실물에서 확인된 것 (구현이 반드시 알아야 함)

HW 브랜치 전체(75개 파일)와 요구사항 정의서 3종을 대조하며 나온 사실이다. **추측이 아니라 소스·로그 근거가 있는 것만 적는다.**

| # | 사실 | 근거 | 구현에 미치는 영향 |
|---|---|---|---|
| F1 | **로봇의 `sequence_id`는 항상 0이다** | `pi/robot/robot_node.py:99`가 `envelope(seq=self.seq)`를 쓰는데 그 파일에 `self.seq += 1`이 **없다**. 센서(`sensor_node.py:115`)·액추에이터(`actuator_node.py:107`)에는 있다 | 유일 키·갭 검출을 `sequence_id`에 의존시키면 **로봇 20Hz 데이터가 사라진다** |
| F2 | **`received_at`은 "서버 수신 시각"이 아니라 "소비 시각"이다** | `received_at`은 `writer.py:37`의 `default_factory`에서만 생성되고, 그 객체를 만드는 것은 `consumer.py`다. `bridge.py`에는 `received_at`이 없다 | 재기동·오프셋 리셋마다 같은 메시지에 다른 값이 찍힌다 → `ingest_at` 신설 |
| F3 | **공통 헤더 `timestamp`가 초 해상도다** | `pi/common/schema.py`의 `iso_now()`가 `timespec="seconds"` | 로봇 20Hz면 1초에 20건이 같은 `timestamp`를 갖는다 |
| F4 | **`status`에는 순번이 없다** | `node.py:200`이 `envelope(self.identity)`를 순번 없이 호출. LWT(`node.py:92`)도 같다 | 갭 검출 대상에서 제외 |
| F5 | **`heartbeat`는 QoS 0, `state`는 QoS 1(로봇만 0)** | `node.py:237`(hb, qos=0) / `sensor_node.py:113`(qos=1) / `config.py`의 `ROBOT_STATE_QOS=0` | 갭의 의미가 채널·타입마다 다르다 |
| F6 | **`analyzer`가 `state` 토픽에 완전히 다른 본문을 보낸다** | `pi/augment/analyzer.py:136`이 `{ZONE}/analysis/{dev}/state`로 발행하는데 본문에 `"channel":"analysis"`이고 `device_status`·`reason`이 **없다** | 공통 코어를 강제하면 **가동 중인 생산자가 전량 격리된다** |
| F7 | **`analyzer`의 `mac`·`ip`가 빈 문자열이다** | `analyzer.py:123`의 `schema.Identity(dev, node_id, ZONE, "", "", "analysis")` | 레지스트리 upsert가 기존 값을 지울 수 있다 |
| F8 | **`analyzer`의 `seq`가 모듈 전역이라 대상별로 갭이 생긴다** | `analyzer.py`의 전역 `seq`가 모든 `dev`에 걸쳐 공유 | `analysis`는 갭 검출 대상 아님 |
| F9 | **실노드는 `entity_id`·`origin_kind`를 보내지 않는다** | `schema.py`의 `envelope()`에 두 필드가 없다. Phase 1 실측 공통 헤더에도 없다. 가짜 발행자(`tests/publisher.py`)에는 **있다** | 가짜 발행자로만 테스트하면 "통과하는데 실제로는 항상 NULL"인 칼럼이 생긴다 |
| F10 | **구역 변경 시 빈 payload가 격리된다** | `node.py:253`이 옛 토픽에 `""`를 retained로 발행(유령 장치 제거). ingest의 `json.loads("")`가 실패 | 정상 동작인데 격리 파일이 오염된다 |
| F11 | **재접속과 세션은 다르게 움직인다** | 브로커 끊김·구역 변경은 `_connect()` 재호출이라 프로세스가 유지되고 순번도 유지된다. 반면 `birth`는 **세 경우 모두** 발행된다 | `birth` 경계만으로는 순번 리셋을 잘못 판정한다 → `session_id` 신설 근거 |
| F12 | **두절 후 재전송 시 연속 표본이 솎인다** | `pi/common/spool.py`의 `_downsample()`. 평시 `state`는 `reason="periodic"` → `CONTINUOUS` | `replayed` 구간의 성긴 `state`는 유실이 아니다 |
| F13 | **`replayed` 표식은 신뢰할 수 없다** | `spool.replay()`가 표식을 넣은 뒤 파일에서 지우므로, 그 사이에 죽으면 표식 없이 나간다. `status`·`heartbeat`는 `allow_spool=False`라 애초에 spool을 안 탄다 | 지연 도착 판정을 표식에만 의존하면 안 된다 → `lag_s` 병행 |
| F14 | **저장 소비자는 구조적으로 재소비한다** | `consumer.py`의 `auto.offset.reset=earliest` + `enable.auto.commit=True` | 유일 키 없이는 재기동마다 중복 행이 쌓인다 |
| F15 | **로봇은 임무 중 하트비트를 끈다** | `robot_node.py`의 `heartbeat_enabled()`가 `not self.in_mission()` | 하트비트 침묵을 장애로 단정하면 안 된다(Phase 5 재료) |

### 2-5. 요구사항 파일이 세 곳에 흩어져 있다 — 기준을 정했다

| 시트 | 최신 위치 | 근거 |
|---|---|---|
| **조병현(HW)** | **HW 브랜치 사본** | 전체 스프레드시트와 10곳 다르고, 그 10곳이 HW의 `SRS.md` §9.11 개정 6건 + `METHODOLOGY.md` §2-5 정정 4건과 **정확히 일치**한다. 반대 방향(전체가 더 새로운 경우)은 0건 |
| **김현우(VZ)** | **전체 공유 스프레드시트** | 시각화 브랜치 사본과 **0셀 차이** — 브랜치 고유 수정이 없다 |
| **진나영(AI)** | 전체 공유 스프레드시트 | 시각화 브랜치와 0셀 차이. HW 사본은 삭제된 11건을 보유하고 `AI-C-20`·`AI-L-08`이 없다 |
| **이대규(BE)** | 전체 공유 스프레드시트 | 48건(47 + `BE-C-08`). `BE-C-08`은 전 Phase 종료 후 항목이므로 **추적은 47건 기준 유지** |

> **역설 하나:** HW가 브랜치에서 고친 값(하트비트 5초·OTel export 15초·로봇 대기 5초)은 **백엔드 아키텍처 v8을 채택한 결과**다. 즉 전체 스프레드시트 쪽이 백엔드와 어긋나 있다. 반영 요청을 HW 회신에 넣는다(§9-1).

---

## 3. 제약 — 반드시 지킬 것

1. **저장 제품을 상위 로직에 하드코딩하지 않는다**(원칙 1). `backend/storage/consumer.py`·`backend/ingest/`는 저장 제품 클라이언트(psycopg·MySQL 드라이버)를 **직접 만들지 않는다.** 계측은 `TelemetryWriter.write()`, 레지스트리는 신설 `RegistryWriter.observe()` — **두 목적 인터페이스 뒤에서만** 제품이 드러난다(§2-1의 표).
2. **성격별 저장 모델을 분리한다**(원칙 4). 계측=TimescaleDB, 감사·레지스트리·실행 기록=MySQL(테이블 분리). **MongoDB는 도입하지 않는다.** 트윈·명령 진행·가용성은 저장하지 않는다.
3. **감사는 요약하지 않는다**(원칙 5). 이번엔 스키마만 만들지만, 요약·필터를 전제한 구조를 만들지 않는다.
4. **파트가 나뉘는 지점의 기준은 JSON Schema다**(원칙 9). `contracts/common/`이 기준이며 파이썬 타입을 다른 파트에 노출하지 않는다. 공통 헤더 필수 5항목을 지킨다.
5. **Kafka를 장기 저장소로 쓰지 않는다**(원칙 11). 보존 기간은 TSDB 사안이다.
6. **Phase 1이 확정한 것을 다시 설계하지 않는다** — 토픽 규약 `mk2.telemetry.<채널>`(파티션1·RF1), 파티션 키 `source_id`, **Kafka value는 HW가 보낸 원본 JSON 바이트 그대로**, 컨슈머 그룹 `mk2-storage`/`mk2-ws`, Kafka advertised `localhost`·바인딩 `127.0.0.1:9092`, `store(...)` 인터페이스.
7. **서버에 이미 도는 것을 지웠다 다시 깔지 않는다.** `docker compose up -d`에는 **반드시 서비스 이름을 명시**한다. 현재 12개 서비스가 한 compose 프로젝트(`capstone-db`)로 돌고 있고 다른 파트가 쓰는 것이 섞여 있다.
8. **이미지 태그를 고정한다. `:latest` 금지.** (사례: InfluxDB Docker `latest`가 2026-09-15부터 3 Core를 가리키게 바뀐다. 같은 이름으로 다른 물건이 뜬다.)
9. **ufw에 서비스의 외부 포트를 반드시 연다.** docker가 ufw를 우회한다는 서술과 무관하게 연다 — 장애 시 방화벽을 용의선상에서 빼기 위해서다(사용자 확정 규칙, 근거는 **§10-4의 실측 반증**).
10. **새로 여는 포트는 `127.0.0.1`에 바인딩한다.** 기존 Kafka(`127.0.0.1:9092`)·OTel Collector(`127.0.0.1:4316`)와 같은 방침. MySQL의 `0.0.0.0:7858`을 반복하지 않는다.
    > 제약 9와 10은 충돌하지 않는다 — **층이 다르다.** 바인딩이 `127.0.0.1`이면 애초에 loopback에서만 듣기 때문에 ufw를 열어도 외부 접근이 생기지 않는다. 9는 "장애 원인에서 방화벽을 제외하기 위해", 10은 "실질 노출을 만들지 않기 위해"다.
11. **비밀값을 커밋하지 않는다.** 저장소는 Public이다. 비밀값은 저장소 **바깥**(`/home/dg/capstone-db/.env`, chmod 600)에 둔다.
12. **인코딩 UTF-8, 줄바꿈 LF.** `.gitattributes`가 강제한다.
13. **서버 파일을 직접 수정하지 않는다.** 서버 상태가 필요하면 **확인 명령을 제시하고 결과를 받은 뒤** 판단한다(§1-A 규율 2·3). 편집은 컴퓨터에서, 실행·pytest·서버 명령은 사람이 서버(`sysai-server2`)에서.
14. **스키마 적용은 사람이 MySQL `root`로 1회 수행한다.** 앱 계정 `mk2_app`에는 **DDL 권한을 주지 않는다** — 코드가 스키마를 바꿀 수 없어야 한다. (리눅스 root·sudo가 아니라 **MySQL의 root 계정**이다.)
15. **요구사항 파일 기준은 §2-5의 표를 따른다.** BE·AI·VZ는 전체 공유 스프레드시트, HW는 HW 브랜치 사본.
16. **용어를 지킨다** — 산문에서 "계약" 대신 **공통 규격**, "봉투" 대신 **공통 헤더**, 문서를 가리키는 "정본" 대신 **기준 문서**. 단 코드·규격 파일·경로·필드명(`contracts/common/message.schema.json`, `schema_version`, `source_id` 등)은 그대로 쓴다.
17. **막히거나 결정이 필요하면 임의로 정하지 말고 `reports/`에 남기고 멈춘다.** 특히 공통 규격 변경·채널 추가·저장 모델 변경은 프로젝트 전체가 걸린 결정이다.

---

## 4. 먼저 읽을 것

| 대상 | 왜 |
|---|---|
| `CLAUDE.md` §1(절대 원칙 15개)·§1-A(구현 규율 8개)·§2(금지) | 어기면 재작업이다. 특히 규율 2(사실을 다 받기 전에 해법 금지)·규율 8(이월은 plan·traceability 두 곳에) |
| `docs/be/00-architecture.md` §6-2(저장 분리)·§6-5(상관·감사)·§8-3(관측 3층)·§8-5(유예 항목) | §6-2가 저장 대상 넷의 근거, §8-3은 Phase 3이 이번 본문 규격에서 C층 대상을 고른다는 약속, §8-5는 "이번에 안 하는 것"의 근거 |
| `docs/be/01-standalone-implementation-plan.md` Phase 2 절 | 이번 임무의 명세와 Phase 1 이월 목록 |
| `docs/be/requirement-traceability.md` BE-S-01·S-05·S-08·C-01·C-02·Q-03 행 | 각 행의 gap 칸에 무엇이 왜 남아 있는지 적혀 있다. 작업 끝에 이 파일을 갱신한다 |
| `backend/storage/writer.py`·`consumer.py`·`backend/settings.py` | 교체할 실물과 그 경계. `TelemetryRecord`가 무엇을 담고 있는지 |
| `backend/ingest/envelope.py`·`bridge.py` | 본문 검증이 붙는 자리(`envelope.py`)와 Kafka 헤더를 싣는 자리(`bridge.py`) |
| `tests/publisher.py`·`tests/conftest.py`·`tests/test_pipeline.py` | **단계 4-A의 대상.** 지금 publisher가 채널과 무관하게 state 본문을 쓴다는 것을 눈으로 확인하고 시작한다 |
| `contracts/common/README.md` "값이 없을 때의 표현" | 이번에 본문 규격에 반영할 누락값 규칙 |
| `contracts/common/message.schema.json` | `session_id`를 추가할 대상 |
| `docs/be/hw-envelope-conformance.md` §1-3·§5 | "Phase 2에서 확정해 회신"으로 약속해 둔 항목 |
| HW `pi/common/schema.py`·`node.py`·`spool.py`, `pi/robot/robot_node.py`, `pi/sensor/sensor_node.py`, `pi/actuator/actuator_node.py`, `pi/augment/analyzer.py` | 본문 규격의 유일한 실물 근거. §2-4의 F1~F15가 전부 여기서 나왔다 |

---

## 5. 단계와 각 단계 DoD

### 단계 0 — 서버 현재 상태 확인 (착수 전 필수)

**아무것도 만들기 전에 확인 명령을 제시하고 사람이 서버에서 돌린 결과를 받는다.** 아래는 이미 확인된 것과 아직 확인되지 않은 것이다.

**이미 확인된 서버 상태 (2026-09-09, 재확인 불필요)**

| 항목 | 값 |
|---|---|
| MySQL | `capstone_mysql` / `mysql:8.0.44` / compose 서비스 이름 **`mysql-db`** / 포트 **`0.0.0.0:7858`→3306** |
| MySQL 설정 | charset `utf8mb4`, collation `utf8mb4_0900_ai_ci`, `global_tz=SYSTEM`, `system_tz=KST`(**중요**), 타임존 테이블 **1795건 적재**, sql_mode 8.0 기본(strict), `innodb_buffer_pool=128MB`, `max_connections=151` |
| MySQL DB | `information_schema`·`mysql`·`performance_schema`·`robot_capstone`·`sys` — **MK2 전용 DB 없음** |
| MySQL 계정 | `robot_user@%`(robot_capstone만), `root@%`, `root@localhost` |
| 기존 테이블 | `robot_capstone.robot_info`(0행), `robot_capstone.robot_logs`(2591행) — **이름 충돌 없음** |
| 마운트 | `/home/dg/capstone-db/db_data → /var/lib/mysql`, `/home/dg/capstone-db/conf → /etc/mysql/conf.d` |
| TSDB | **컨테이너 없음.** 이미지만 캐시됨(`postgres:15-alpine`·`influxdb:1.8`·clickhouse). 볼륨 없음 |
| 포트 | 8086·8181·5432·8428 **비어 있음**. 9092는 `127.0.0.1`, 7858은 `0.0.0.0` |
| compose | 프로젝트 `capstone-db`, 서비스 12개, 파일 `/home/dg/capstone-db/docker-compose.yml`, 네트워크 `capstone-db_default` |
| docker 네트워크 | subnet `172.18.0.0/16`, gateway **`172.18.0.1`** |
| **접속 원천 주소** | 호스트에서 `127.0.0.1:7858`로 붙으면 MySQL은 **`172.18.0.1`**로 본다(processlist 실측) → `'mk2_app'@'localhost'`는 **붙지 못한다** |
| 자원 | 디스크 2.5T 여유(29% 사용), 메모리 237Gi 가용 |
| `.env` | `~/capstone-db`에 **없음** |
| 파이썬 | venv `~/capstone-db/phase1_work/venv_phase1`, **Python 3.14.4**. `psycopg[binary]` cp314 휠 설치 가능 확인 |
| Kafka | 토픽 `mk2.telemetry.{state,status,heartbeat}`, 그룹 `mk2-storage`·`mk2-ws` |
| 검증 재료 | `telemetry_sink.jsonl` **315줄**, `quarantine.jsonl` **4줄** |

**아직 확인되지 않은 것 — 이 넷을 먼저 받는다**

```bash
echo "=== [0-1] 7859 포트가 비었는가 (Timescale 후보 포트) ==="
ss -tulpn 2>/dev/null | grep -E ':(7859|7864)\b' || echo "(7859·7864 모두 비어 있음)"

echo "=== [0-2] TimescaleDB 이미지 확보와 고정할 값 확인 ==="
# 이동 태그로 한 번 받아 실제 버전을 읽는다. compose 에는 이 이동 태그를 쓰지 않는다.
docker pull timescale/timescaledb:latest-pg16 2>&1 | tail -3
docker images --digests | grep -i timescale
docker run --rm --entrypoint postgres timescale/timescaledb:latest-pg16 --version 2>&1 | tail -2

echo "=== [0-3] MySQL conf.d 에 들어 있는 것 (실효값과 충돌하는 설정이 있는가) ==="
ls -la /home/dg/capstone-db/conf/ && cat /home/dg/capstone-db/conf/*.cnf 2>/dev/null | head -40

echo "=== [0-4] ufw 현재 규칙 (7859 개방 전 기준선) ==="
sudo ufw status numbered

echo "=== [0-5] 저장소 클라이언트가 Python 3.14 에서 설치되는가 (실제 설치 안 함) ==="
source ~/capstone-db/phase1_work/venv_phase1/bin/activate
pip install --dry-run "psycopg[binary]" 2>&1 | tail -3      # 확인 완료분 재확인
pip install --dry-run PyMySQL          2>&1 | tail -3      # 순수 파이썬 — 1순위 후보
pip install --dry-run mysqlclient      2>&1 | tail -3      # C 확장 — 3.14 휠이 없을 수 있다
```

> **0-5 주의 — 드라이버가 정해져 있지 않다.** TSDB 쪽은 `psycopg[binary]`의 cp314 휠을 이미 확인했지만 **MySQL 드라이버는 아직 고르지 않았다.** `mysqlclient`는 C 확장이라 Python 3.14 휠이 없으면 빌드가 필요하고, 서버에 빌드 도구가 없으면 거기서 막힌다. **`PyMySQL`(순수 파이썬)을 1순위로 두되, 0-5 결과를 받은 뒤 확정한다.** 셋 다 실패하면 임의로 다른 것을 고르지 말고 멈추고 물어본다.
>
> **0-2 주의:** `latest-pg16`은 **이동 태그다** — 같은 이름으로 내용이 바뀐다. 받아서 실제 버전을 읽는 용도로만 쓰고, **compose에는 절대 넣지 않는다**(제약 8). 고정 방법은 둘 중 하나이며 `docker images --digests` 출력을 보고 고른다.
> - **(권장) digest 고정**: `timescale/timescaledb@sha256:<digest>` — 같은 이름으로 다른 물건이 뜰 여지가 0이다.
> - **구체 버전 태그**: `postgres --version`이 돌려준 PG 버전에 맞는 명시 태그.
>
> pull이 실패하면 그 자체가 정보이므로 그대로 회신받는다. 커뮤니티 이미지 이름이 다르면(`timescale/timescaledb-ha` 등) **임의로 고르지 말고 멈추고 물어본다.**

**DoD (단계 0):** 위 넷의 결과를 받았고, 7859(또는 대체 포트)가 비어 있음을 확인했으며, 고정할 Timescale 이미지 태그가 정해졌다. **결과 없이 다음 단계로 가지 않는다.**

---

### 단계 1 — TimescaleDB 기동 (신규 서비스 1개만 추가)

서버 compose 파일에 **`timescale-db` 서비스 블록만 추가**한다. 기존 12개 서비스 정의는 한 줄도 건드리지 않는다. 컴퓨터의 `infra/docker-compose.yml`(작업본, gitignore)에서 편집해 사람이 서버에 적용한다.

| 항목 | 값 |
|---|---|
| compose 서비스 이름 | `timescale-db` |
| 컨테이너 이름 | `capstone_timescaledb` |
| 이미지 | `timescale/timescaledb:<단계 0에서 정한 구체 태그>` — **`:latest` 금지** |
| 포트 | **`127.0.0.1:7859:5432`**. 7859가 막혀 있으면 7864 — 그 경우 **함께 고칠 곳 넷**: compose · ufw 규칙 · `settings.py`의 `MK2_TSDB_PORT` 기본값 · `infra/README.md` §3 포트 표 |
| 볼륨 | `./timescale_data:/var/lib/postgresql/data` → 실제 경로 `/home/dg/capstone-db/timescale_data` |
| 환경변수 | `POSTGRES_DB=mk2`, `POSTGRES_USER=postgres`, `POSTGRES_PASSWORD=${MK2_TSDB_ROOT_PASSWORD}`, **`TZ=UTC`** |
| restart | `always` (기존 관행) |
| healthcheck | `pg_isready -U postgres -d mk2` |

> **`TZ`만 기존 관행(다른 11개는 `Asia/Seoul`)과 다르게 `UTC`로 둔다.** 저장 기준이 UTC(결정 3-D)인데 컨테이너 기본 표시가 KST면 `psql`로 손검증할 때 값이 KST로 보여 **"UTC로 저장됐나"를 눈으로 확인할 수 없다.** 저장되는 값 자체는 `TIMESTAMPTZ`라 `TZ`와 무관하지만(항상 UTC로 보관), **검증을 헷갈리게 만들지 않기 위해** 표시 기준도 맞춘다. 애플리케이션은 어차피 접속 시 `SET TIME ZONE 'UTC'`를 명시하므로 `TZ`에 의존하지 않는다(단계 2).

**부대 작업**

- **`/home/dg/capstone-db/.env` 신설**(chmod 600, 소유자 `dg`). compose가 같은 디렉터리의 `.env`를 자동으로 읽으므로 `${...}` 치환이 그대로 된다. 기존 12개 서비스는 `${...}`를 안 쓰므로 영향이 없다.
  ```
  MK2_TSDB_ROOT_PASSWORD=<영숫자만 32자>
  MK2_TSDB_PASSWORD=<영숫자만 32자>
  MK2_MYSQL_PASSWORD=<영숫자만 32자>
  ```
  **특수문자를 넣지 않는다** — 셸 `source`와 compose dotenv 파서의 규칙이 달라 한쪽만 다르게 읽는 사고가 난다.
- **볼륨 디렉터리 권한.** Kafka에서 겪은 것과 같은 함정을 예상한다 — 컨테이너 내부 uid와 서버 계정 uid가 다르면 기동이 실패한다. postgres 이미지는 내부 uid 999(postgres)로 돈다. `mkdir -p timescale_data` 후 소유자를 맞춘다.
- **ufw에 7859를 연다**(제약 9).
- **`pg_hba.conf`**: `host mk2 mk2_app 172.18.0.0/16 scram-sha-256`. 백엔드가 호스트 프로세스라 컨테이너에서는 `172.18.0.1`로 보인다(단계 0 실측).
- `infra/README.md` §2 스택 표에 TimescaleDB 행을 추가하고 §3 포트 표에 7859를 추가한다.

**DoD (단계 1):** `docker compose up -d timescale-db` 후 `docker compose ps timescale-db`가 `Up (healthy)`. `psql`로 `mk2` DB 접속 성공. `CREATE EXTENSION IF NOT EXISTS timescaledb;` 성공. **다른 11개 서비스가 재생성되지 않았음을 `docker ps`의 `Up N days`로 확인**한다.

---

### 단계 2 — DB·계정·권한 (사람이 root로 1회)

Claude Code는 **SQL 파일을 만들고**, 사람이 서버에서 관리자 계정으로 적용한다.

**SQL 산출물 배치 규약 (이번 Phase 전체에 적용)**

| 파일 | 무엇 | 커밋 |
|---|---|---|
| `infra/sql/mk2_mysql_schema.sql` | MySQL DB·테이블 DDL | ✅ **커밋한다** — 비밀값이 없고, 다음 재구축의 재현 수단이다 |
| `infra/sql/mk2_tsdb_schema.sql` | TimescaleDB 테이블·하이퍼테이블·인덱스 DDL | ✅ 커밋 |
| `infra/sql/mk2_grants.sql.example` | 계정 생성·GRANT **템플릿**(비밀번호 자리는 `<...>` 자리표시자) | ✅ 커밋 |
| `infra/sql/mk2_grants.sql` | 실제 비밀번호가 들어간 적용본 | ❌ **gitignore** |
| `docs/be/queries/gap-detection.sql` | 갭 검출 조회(주석 포함) | ✅ 커밋 |

> `infra/`는 지금 통째로 gitignore돼 있다(compose·config에 비밀값이 있어서). **`infra/sql/`만 예외로 추적하도록 `.gitignore`에 부정 패턴을 추가한다.** 추가한 뒤 `git check-ignore -v`로 실제로 추적되는지 확인한다 — `.gitignore`의 `!.env.example` 패턴이 줄 끝 주석 때문에 무효였던 기존 이슈(Phase 1 미결표)와 같은 함정이 있다.

**MySQL (`mk2` DB)**

| 항목 | 값 |
|---|---|
| DB | `mk2` (charset `utf8mb4`, collation `utf8mb4_0900_ai_ci`) |
| 앱 계정 | `'mk2_app'@'172.18.%'` (`caching_sha2_password`) |
| 권한 | 아래 표대로 **테이블 단위 차등**. `CREATE`·`ALTER`·`DROP` **없음** |

> ⚠ **MySQL `GRANT`에는 테이블 이름 와일드카드가 없다.** 아래 표의 `registry_*_observed` 같은 표기는 **묶어 읽으라는 뜻이지 SQL 문법이 아니다.** `GRANT ... ON mk2.registry_entity_observed TO ...` 처럼 **테이블마다 한 줄씩** 쓴다. `GRANT ... ON mk2.*` 로 뭉뚱그리면 테이블 단위 차등이 무너져 `mission_event`에도 UPDATE가 붙는다 — 이 설계의 핵심이 그 차등이다.

| 테이블군 | 부여 권한 | 왜 |
|---|---|---|
| `registry_*_observed`, `registry_identity_history` | `SELECT, INSERT, UPDATE` | 관측 축은 갱신된다 |
| `registry_*_declared`, `registry_zone` | `SELECT` | 선언 축은 사람이 넣는다 |
| `audit_log` | `SELECT, INSERT` | **UPDATE·DELETE를 권한으로 막는다**(원칙 5) |
| `mission_event` | `SELECT, INSERT` | **append-only를 코드 규율이 아니라 권한으로 강제**(BE-S-08 "수정·삭제하지 않으며") |

**TimescaleDB (`mk2` DB)**

- 앱 계정 `mk2_app` — `telemetry` 테이블에 **`SELECT, INSERT`만**, **DDL 없음**. 삽입이 `INSERT ... ON CONFLICT DO NOTHING`이라 `UPDATE` 권한이 필요 없다 — 없는 편이 계측 원본을 덮어쓸 경로 자체를 없앤다
- 스키마 적용은 `postgres` 계정으로 사람이 1회
- **부대 권한 둘을 빠뜨리지 않는다:** ① `GRANT USAGE ON SCHEMA public TO mk2_app` ② 하이퍼테이블은 내부 청크로 쪼개지므로 **새 청크에 권한이 전파되는지 확인**한다(TimescaleDB는 하이퍼테이블 GRANT를 청크로 상속하지만, 청크가 실제로 생긴 뒤 `mk2_app`으로 INSERT·SELECT가 되는지 **테스트로 확인**한다 — 상속이 안 되면 데이터가 쌓이다가 어느 순간 권한 오류가 난다)

**세션 타임존 고정.** 백엔드가 접속할 때 MySQL은 `SET time_zone='+00:00'`, PostgreSQL은 `SET TIME ZONE 'UTC'`를 명시한다. **컨테이너 `TZ` 값에 기대지 않는다** — 컨테이너 설정이 바뀌면 과거 데이터 해석이 통째로 흔들린다.

**`backend/settings.py` 추가 (이름만, 값은 환경변수)**

| 환경변수 | 기본값 | 누가 쓰나 |
|---|---|---|
| `MK2_MYSQL_HOST` / `MK2_MYSQL_PORT` | `127.0.0.1` / `7858` | 감사·레지스트리·실행 기록. 드라이버는 **단계 0-5 결과로 확정**(1순위 `PyMySQL`) |
| `MK2_MYSQL_DB` / `MK2_MYSQL_USER` | `mk2` / `mk2_app` | |
| `MK2_MYSQL_PASSWORD` | **기본값 없음(필수)** | 없으면 기동 실패시킨다 |
| `MK2_TSDB_HOST` / `MK2_TSDB_PORT` | `127.0.0.1` / `7859` | 계측 |
| `MK2_TSDB_DB` / `MK2_TSDB_USER` | `mk2` / `mk2_app` | |
| `MK2_TSDB_PASSWORD` | **기본값 없음(필수)** | |
| `MK2_STORE_TZ` | `UTC` | 저장 시각 기준 |

**DoD (단계 2):** `mk2_app`으로 각 저장소에 접속되고, `SELECT`·`INSERT`가 되며, **`mission_event`에 `UPDATE`·`DELETE`가 권한 거부되고**, **`CREATE TABLE`이 권한 거부된다**. `settings.py`에 표가 추가됐고 비밀번호는 기본값이 없다.

---

### 단계 3 — 공통 헤더 확장 (`session_id` 신설)

**`contracts/common/message.schema.json`**

- 선택 속성 `session_id` 추가 (`type: string`, `minLength: 1`)
- 설명: *"생산자 프로세스의 1회 기동을 가리키는 식별자. 기동마다 새로 생성하며 저장하지 않는다. `sequence_id`가 재기동 시 리셋되므로 순번 열의 경계를 이 값으로 가른다(BE-S-01). 없으면 소비자가 `status`의 `birth`를 경계로 폴백한다."*
- **버전 정책상 MINOR 인상** — `contracts/common/README.md`가 "선택 필드 추가처럼 구버전 소비자가 깨지지 않는 변경은 MINOR"로 정해 두었다. 규격 현재 버전을 `1.1`로 올린다.
- `examples/envelope-valid.json`과 음성 fixture 2개의 `schema_version`을 `"1.1"`로 갱신한다. **정규식이 `^[0-9]+\.[0-9]+$`라 HW가 보내는 `"1.0"`도 계속 통과한다** — 혼재 기간에 격리가 나면 안 된다.

**`tests/publisher.py`** — `make_state_message()`에 `session_id` 추가(프로세스 1회 생성).

> **HW는 아직 이 필드를 보내지 않는다.** 그래서 Phase 2 검증에서 `session_id` 경로는 가짜 발행자로만 확인되고, **실노드는 폴백 경로로 동작한다.** 완료 판정에 이 구분을 명시한다(§7).

**DoD (단계 3):** 규격에 `session_id`가 선택으로 추가됐고, `session_id`가 있는 메시지와 없는 메시지가 **둘 다 통과**한다(pytest 양성 2건).

---

### 단계 4 — 채널 본문 규격 신설과 2단 검증

**파일 구성**

```
contracts/common/payload/
  state.robot.schema.json        ← 로봇 우선. 실물 근거로 지금 만든다
  state.sensor.schema.json
  state.actuator.schema.json
  state.analysis.schema.json     ← 없으면 가동 중인 analyzer가 전량 격리된다(F6)
  status.schema.json
  heartbeat.schema.json
contracts/common/examples/          ← 전부 **공통 헤더 + 본문이 합쳐진 완전한 메시지**다
  payload-state-robot-valid.json      (검증이 완전한 메시지 단위로 이뤄지므로 본문만 담으면 못 돌린다)
  payload-state-sensor-valid.json
  payload-state-actuator-valid.json
  payload-state-analysis-valid.json
  payload-status-birth-valid.json
  payload-status-lwt-valid.json                     ← LWT가 통과하는지 양성 확인
  payload-state-robot-invalid-missing-device-status.json   ← 음성
  payload-state-robot-unknown-field.json            ← 모르는 필드가 통과하는지(양성)
```

**본문 항목 (전부 HW 소스 실물 근거)**

| 채널·타입 | 필수 | 선택 | `reason` 어휘 |
|---|---|---|---|
| `state` / robot | `reason`·`device_status`·`battery_pct`·`position`·`speed_mps`·`robot_mode`·`internal_seq` | `mission`·`replayed` | `periodic`·`mode_changed`·`battery_low` |
| `state` / sensor | `reason`·`device_status`·`water_level_m`·`unit`·`alert`·`mode` | `replayed` | `periodic`·`threshold_exceeded`·`threshold_cleared`·`rapid_change` |
| `state` / actuator | `reason`·`device_status`·`actuator_state`·`position`·`progress`·`feedback_ok`·`control_locked` | `lock_reason`(null 허용)·`detail`·`replayed` | `periodic`·`progress`·`state_{idle\|moving\|done\|error\|unknown}` |
| `state` / analysis | `subject_id`·`value`·`window_s`·`samples`·`above_threshold`·`threshold_m` | `trend_m_per_min`(null)·`eta_to_threshold_min`(null) | (없음) |
| `status` (공통) | `event`·`status` | `device_status`·`registration`·`uptime_s`·`buffer`·`publish_failures`·`reason` + 노드 고유 필드 | — |
| `heartbeat` | (없음) | — | — |

> ⚠ **`position`이 로봇에서는 객체 `{x,y,heading_deg}`, 액추에이터에서는 문자열 `"open"`이다.** 같은 이름 다른 타입이라 **공통 코어에 넣으면 한쪽이 반드시 깨진다.** 타입별 확장에만 둔다.
> ⚠ **액추에이터의 `progress`는 필드 이름이자 `reason` 값이다.** 필드 `progress`는 0.0~1.0 진행률이고, `reason: "progress"`는 "동작 중 진행 보고"라는 뜻이다(`actuator_node.py:77`). 스키마에서 둘을 헷갈리지 않게 설명을 붙인다.
> ⚠ **`status`의 필수를 `event`·`status` 둘로만 잡는 이유**는 LWT다. LWT 본문에는 `registration`도 `buffer`도 없다(`node.py:92`). 세게 걸면 급사 신호가 격리된다.

**검증 방식 — 느슨한 2단**

- `backend/ingest/envelope.py`에 본문 검증을 추가한다. 순서는 **공통 헤더 → 본문**.
- **`additionalProperties`를 `false`로 두지 않는다.** 모르는 필드는 통과시키고 저장한다. HW가 필드를 하나 추가하는 순간 전량 격리되는 사고(편집 ② 전 `+0900`과 같은 모양)를 만들지 않는다.
- **필수 필드 누락은 격리한다.** 저장 층이 기대는 값이 없으면 스키마가 성립하지 않는다.
- **타입 판별은 MQTT 토픽 2번째 칸(etype)으로 한다.** `backend/settings.py`에 `entity_type_of_mqtt_topic()`을 추가한다. 구독 패턴이 `+/+/+/{channel}` 4칸이라 `parts[1]`이 etype이다.
- ⚠ **etype은 ingest에서만 알 수 있다.** Kafka 토픽은 `mk2.telemetry.<채널>`이라 **채널만 담고 etype을 담지 않는다**(토픽 규약은 Phase 1 확정이라 바꾸지 않는다). 저장 소비자는 MQTT 토픽을 보지 못하므로, **ingest가 파싱한 etype을 Kafka 헤더로 실어 보낸다**(단계 5). 저장 층이 레지스트리를 조회해 타입을 알아내려 하면 닭-달걀이 된다 — 대장에 없는 새 노드가 첫 메시지부터 막힌다.
- **토픽 의존은 이미 있는 것이라 새로 늘지 않는다.** `bridge.py`가 이미 `channel_of_mqtt_topic()`으로 토픽을 쪼개고 있고, `hw-envelope-conformance.md` §2-1·2-3에서 `{zone}/{etype}/{eid}/{channel}` 4칸 구조와 etype 어휘 4종(`sensor`·`robot`·`actuator`·`analysis`)을 **이미 확정으로 회신**해 두었다.
- **모르는 etype은 본문 검증을 건너뛰고 통과시킨 뒤 기록한다.** 새 노드 타입이 첫 메시지부터 격리되면 안 된다.
- **본문의 `channel` 필드는 검증하지 않는다.** 라우팅은 토픽 기준이다. `analyzer`가 토픽 `state`에 본문 `channel: "analysis"`를 보내고 있어(F6) 일치를 강제하면 격리된다. 불일치는 **기록만** 하고, 필드 존치 여부는 HW·AI 회신 항목으로 넘긴다.

**누락값 표현 (BE-C-01 gap 해소)**

`contracts/common/README.md`가 확정한 규칙 — 명시적 `null` 기본, 부재 사유 구분이 필요한 항목만 `{value, state}` 형태(`unsupported` / `unavailable`) — 을 본문 규격에 반영한다.

| 구분 필요 항목(확정) | 왜 |
|---|---|
| `state`의 계측값(`water_level_m`·`battery_pct` 등) | 센서 읽기가 실패하면 **발행 자체가 안 되고**(`sensor_node.py:69-72`의 `except → return`), 3회 연속이면 `device_status`가 `fault`가 된다(`:150-151`). 화면은 "센서 없음"과 "센서 고장"을 달리 그려야 한다 |
| `status.registration` | LWT엔 원래 없다(`unsupported`) vs 있어야 하는데 없다(`unavailable`) |

**나머지는 기본형(`null`).** `status.buffer`는 `node.py`(공통 코어)에서 항상 채워지고 안 채워지는 경우가 LWT뿐이라 `registration`과 중복이므로 **기본형으로 내린다.**

> **원본 저장과의 관계 — 앞선 논의를 좁힌다.** 저장은 **원본 그대로**다(원칙 4: 계측의 원본은 TSDB). 저장 시점에 `null`을 채워 넣으면 저장된 것이 원본이 아니게 된다. 대신 **읽기 함수**를 둔다 — `backend/storage/normalize.py`의 `normalize_payload(channel, entity_type, payload) -> dict`가 규격의 항목 목록대로 없는 키를 채워 돌려준다. **항목 목록은 파이썬에 다시 적지 않고 `contracts/common/payload/*.schema.json`을 직접 읽어 얻는다** — `envelope.py`가 `message.schema.json`을 그대로 로드하는 것과 같은 방식이다(원칙 9: 두 벌이 되면 조용히 어긋난다). 조회 층(Phase 5/6)이 이 함수를 쓴다. Phase 2는 함수와 pytest까지.

**Phase 3을 위한 표시 (계측하지 않는다)**

각 본문 항목에 신호 종류 힌트를 스키마 주석(`$comment`)으로 단다. `00-architecture.md` §8-3의 매핑 원칙 그대로다.

| 항목 | 힌트 |
|---|---|
| `water_level_m`·`battery_pct`·`speed_mps`·`progress`·`uptime_s` | gauge |
| `buffer.dropped`·`buffer.thinned`·`publish_failures` | counter |
| `alert`·`device_status`·`event`·`actuator_state`·`robot_mode` | log/event |

**라벨 금지도 함께 적는다** — `source_id`·`zone_id`·채널처럼 값 종류가 한정된 것만 라벨로 쓴다. **`session_id`·시각·`sequence_id`·`internal_seq`는 라벨에 넣지 않는다.** 특히 `session_id`는 재기동마다 새 값이라 시계열이 무한 증식한다.

**DoD (단계 4):** 6개 본문 스키마와 fixture가 있고, 양성(로봇·센서·액추에이터·analysis·status birth·status LWT)이 통과하며, **음성(필수 누락)이 실제로 격리되고**, **모르는 필드가 통과하고**, **analyzer 형식 메시지가 격리되지 않는다.**

---

### 단계 4-A — 검증 재료 정비 (가짜 발행자 확장) ★ 단계 5로 가기 전에 반드시

**단계 4가 본문 검증을 켜는 순간 현재 `tests/publisher.py`가 깨진다.** 지금 구조가 이렇다.

```python
payload = make_state_message(...)     # state 본문(water_level_m·unit·alert·reason)
payload["channel"] = args.channel     # ← channel 만 덮어쓴다
```

즉 `--channel status`로 보내도 **본문은 여전히 state**다. `event`·`status`가 없으므로 단계 4의 `status.schema.json` 필수 검사에 걸려 **격리된다.** `heartbeat`도 같다(본문이 있으면 안 되는데 state 본문이 실린다 — 이쪽은 느슨한 2단이라 통과하지만 의미가 틀렸다).

**이걸 손보지 않으면 완료 판정 #31(기존 6건 통과)이 무너진다.** 단계 4의 부수 효과이므로 같은 자리에서 닫는다.

**확장할 것 (`tests/publisher.py`)**

| 무엇 | 왜 필요한가 | 어느 완료 판정 |
|---|---|---|
| **채널별 본문** — `status`(`event`·`status`·`registration`·`buffer`…)·`heartbeat`(본문 없음) | 본문 검증을 켠 뒤 기존 회귀가 살아 있어야 한다 | 31 |
| **타입별 본문** — `--etype robot\|sensor\|actuator\|analysis`. 토픽 2번째 칸과 본문이 함께 바뀐다 | 4종 본문 양성 검증 | 13·17 |
| **`--timestamp`** — 임의 시각으로 발행(과거·미래) | **지연 도착**과 **음수 lag**를 만들 수단이 지금 없다 | 8·10 |
| **`--replayed`** — 본문에 `replayed: true` | 재전송 보관 확인 | 9 |
| **`--session-id` / `--no-session-id`** | `session_id` 경로와 `birth` 폴백 경로를 **둘 다** 돌려야 한다 | 28·29 |
| **`--seq`** — 순번 지정(리셋·갭 주입) | 갭 검출·세션 경계 | 27·28 |
| **`--registration`** — `status`에 registration 블록(빈 `mac`·`ip` 주입 포함) | 레지스트리 5건 전부 | 19~22 |

**지킬 것**

- **실노드가 안 보내는 것을 기본으로 보내지 않는다.** `entity_id`·`origin_kind`는 지금 publisher가 보내고 실노드는 안 보낸다(F9). **기본을 실노드에 맞추고**(안 보냄), 옵션으로만 켠다. 안 그러면 "가짜로는 통과하는데 실물에서는 항상 NULL"인 칼럼을 못 잡는다.
- **본문은 HW 소스를 그대로 베낀다.** 단계 4의 표가 아니라 `sensor_node.py`·`robot_node.py`·`actuator_node.py`·`analyzer.py`의 실제 `payload.update({...})`를 근거로 삼는다. 표는 요약이고 소스가 근거다.
- **`analyzer` 형식은 그 결함까지 그대로 재현한다** — 토픽 끝은 `state`, 본문 `channel`은 `analysis`, `device_status`·`reason` 없음, `mac`·`ip` 빈 문자열(F6·F7). **결함을 고쳐서 흉내 내면 #17·#22가 실제로는 아무것도 검증하지 못한다.**
- publisher는 지금처럼 **`paho-mqtt`와 표준 라이브러리만** 쓴다(Kafka·백엔드 패키지 의존 없음). 컴퓨터에서도 돌아야 한다.

**DoD (단계 4-A):** 확장된 publisher로 **기존 pytest 6건이 그대로 통과**하고, 4종 타입·3채널·임의 시각·registration 발행이 전부 가능하며, **기본 발행이 실노드와 같은 필드 집합**(`entity_id`·`origin_kind` 없음)이다.

---

### 단계 5 — 시각 3종과 Kafka 헤더

**`backend/ingest/bridge.py`** — produce 시 Kafka **헤더**에 `ingest_at`(ingest가 MQTT로 받은 순간, UTC ISO-8601)을 싣는다.

```python
self.producer.produce(
    kafka_topic,
    key=message["source_id"].encode("utf-8"),
    value=payload,                                   # 원본 바이트 그대로 — 변경 금지
    headers=[
        ("ingest_at",   ingest_at_iso.encode("utf-8")),
        ("entity_type", entity_type.encode("utf-8")),   # MQTT 토픽 2번째 칸 — Kafka 토픽에는 없다
    ],
    on_delivery=_on_delivery,
)
```

> **본문에 넣지 않는 이유:** Phase 1이 확정한 "Kafka value는 HW가 보낸 원본 JSON 바이트 그대로"를 깨지 않기 위해서다. 재직렬화하면 필드 순서·수치 표현이 달라져 원본이 사라진다. 헤더는 value 바깥이다.

**`backend/storage/consumer.py`** — `msg.headers()`에서 `ingest_at`·`entity_type`을 읽어 `TelemetryRecord`에 넘긴다. 헤더가 없으면(Phase 1에 쌓인 옛 메시지) `None` — 옛 메시지가 소비돼도 죽지 않아야 한다.

**`backend/storage/writer.py`의 `TelemetryRecord`** — 필드 추가: `ingest_at`, `entity_type`, `stream_topic`, `stream_partition`, `stream_offset`. **`received_at`의 의미를 "저장 소비자가 소비한 시각"으로 문서화한다**(F2 — 지금까지 "서버 수신 시각"으로 잘못 서술돼 있었다).

**시각 셋의 역할**

| 시각 | 누가 | 저장 칼럼 | 용도 |
|---|---|---|---|
| `timestamp` | 말단 노드 | `ts` | **하이퍼테이블 시간축.** 정렬·조회·되감기의 기준 |
| `ingest_at` | ingest(`bridge.py`) | `ingest_at` | 서버 도달 시각. `lag_s`의 재료 |
| `received_at` | 저장 소비자 | `received_at` | 소비 시각. 재기동마다 달라진다 |

**파생 값**

- `lag_s = ingest_at - ts` (초, 실수). 저장 시점에 계산해 칼럼으로 둔다 — 매 조회마다 빼지 않아도 되고, **BE-S-07(재난 모드 지연 상한)의 측정 재료가 그대로 생긴다**(Phase 3의 A층이 이 값을 읽어 간다).
- `clock_skew = (lag_s < 0)`. 말단 시계가 서버보다 앞선 경우다. **버리지 않고 그대로 저장하되 플래그를 세운다** — 버리면 재난 데이터가 사라지고, 조용히 보정하면 원본이 아니게 된다. 임계는 **초기 기준으로만 두고 통합 시험 후 확정**한다.
- `replayed` — 본문의 `replayed`를 그대로 보관한다. **유일한 근거로 삼지 않는다**(F13). 지연 도착 판정은 `lag_s`로 하고 `replayed`는 "HW가 스스로 재전송이라고 말한 것"이라는 보조 증거다.

**저장은 UTC.** MySQL은 `DATETIME(6)`에 UTC 값, PostgreSQL은 `TIMESTAMPTZ`(내부 UTC). MySQL `TIMESTAMP` 타입은 세션 타임존으로 자동 변환되므로 **쓰지 않는다.** 표시 시각 변환은 조회하는 쪽의 몫이다.

> **옛 메시지 주의.** Kafka에는 Phase 1에 쌓인 메시지가 남아 있고(retention 7일) 그것들에는 헤더가 없다. `mk2-storage` 그룹이 오프셋을 이어받으면 다시 읽지 않지만, **오프셋을 리셋하거나 새 그룹으로 읽으면 헤더 없는 메시지가 온다.** 그때 `ingest_at`·`entity_type`·`lag_s`가 **NULL인 것이 정상**이며 소비자가 죽으면 안 된다. 아래 DoD의 "세 시각 전부"는 **새로 발행한 메시지 기준**이다.

**DoD (단계 5):** **새로 발행한** 메시지가 저장될 때 세 시각이 전부 기록되고, `lag_s`가 계산되며, 음수 lag가 `clock_skew=true`로 **저장된다(버려지지 않는다)**. **헤더 없는 옛 메시지를 소비해도 예외 없이 NULL로 저장된다.**

---

### 단계 6 — 계측 저장 교체 (TSDB writer)

**`TelemetryWriter.write()` 뒤 구현만 교체한다.** 인터페이스·호출부는 그대로다. `JsonlTelemetryWriter`는 **지우지 말고 남긴다** — 인프라 없이 도는 테스트에 쓰인다.

**`telemetry` 하이퍼테이블 (TimescaleDB)**

| 칼럼 | 타입 | 출처 |
|---|---|---|
| `ts` | `TIMESTAMPTZ NOT NULL` | 공통 헤더 `timestamp` — **하이퍼테이블 시간축** |
| `channel` | `TEXT NOT NULL` | **Kafka 토픽 마지막 칸**(기존 `consumer.py` 동작 그대로) |
| `entity_type` | `TEXT` | **Kafka 헤더**(ingest가 MQTT 토픽 2번째 칸에서 파싱). 옛 메시지는 NULL |
| `source_id`·`node_id`·`zone_id` | `TEXT NOT NULL` | 공통 헤더 필수 |
| `entity_id` | `TEXT` | 공통 헤더 선택 — **실노드는 안 보낸다(F9)** |
| `session_id` | `TEXT` | 공통 헤더 선택 — HW 적용 전에는 NULL |
| `sequence_id` | `BIGINT` | 공통 헤더 선택 — `status`엔 없고 로봇은 0(F1·F4) |
| `schema_version` | `TEXT NOT NULL` | 혼재 기간에 1.0/1.1을 가른다 |
| `origin_kind` | `TEXT` | **실노드는 안 보낸다(F9).** 미기재는 조회 시 `real`로 해석 |
| `ingest_at`·`received_at` | `TIMESTAMPTZ` | 단계 5 |
| `lag_s` | `DOUBLE PRECISION` | 파생 |
| `clock_skew`·`replayed` | `BOOLEAN NOT NULL DEFAULT false` | 파생 / 본문 |
| `reason`·`device_status` | `TEXT` | 본문 공통 코어 |
| `stream_topic` | `TEXT NOT NULL` | Kafka 토픽 |
| `stream_partition` | `INTEGER NOT NULL` | Kafka 파티션 |
| `stream_offset` | `BIGINT NOT NULL` | Kafka 오프셋 |
| `payload` | `JSONB NOT NULL` | **원본 메시지 전체**(공통 헤더 포함) |

**유일 키 — 스트림 좌표**

```sql
CREATE UNIQUE INDEX telemetry_stream_uq
  ON telemetry (ts, stream_topic, stream_partition, stream_offset);
```

삽입은 `INSERT ... ON CONFLICT DO NOTHING`.

**왜 스트림 좌표인가.** 3-E가 막으려는 것은 **재소비 중복**이다(F14). 재소비는 도착 계층의 현상이므로 도착 좌표로 잡는 것이 정확하다. 업무 내용 키(`sequence_id`)에 의존하면 **로봇(항상 0)·`status`(없음)·`analysis`(전역 공유)가 전부 깨진다.** 스트림 좌표는 생산자 결함과 무관하다.

> **Timescale 제약:** 하이퍼테이블의 UNIQUE 인덱스는 파티션 키(`ts`)를 반드시 포함해야 한다. 그래서 `ts`가 맨 앞에 있다. 같은 메시지를 다시 읽으면 `ts`도 같으므로 목적은 그대로 달성된다.
> **정직한 약점:** Kafka 토픽을 지웠다 다시 만들면 오프셋이 0부터 재시작해 옛 행과 충돌할 수 있다. 확률은 낮지만 기록해 둔다.

**인덱스**

```sql
CREATE INDEX ON telemetry (source_id, channel, ts DESC);   -- 장치별 추이
CREATE INDEX ON telemetry (zone_id, ts DESC);              -- 구역별 (VZ-N-02의 조회 범위)
CREATE INDEX ON telemetry (channel, ts DESC);
```

**`payload`를 JSONB로 두는 판단.** 칼럼은 인덱스를 위한 **추출**이지 원본 대체가 아니다. JSONB는 값을 정확히 보존하지만 키 순서는 잃는다. 값 보존이 목적이므로 이 손실은 수용한다. **바이트 단위 재현이 필요하다는 근거가 나오면 임의로 결정하지 말고 멈추고 물어본다**(`raw BYTEA` 추가는 저장량이 배가 된다).

**보존 기간·압축은 이번에 설정하지 않는다.** BE-S-04(재난 구간 장기 보존)가 별도 요구사항이고 발동 조건이 아직 아니다(`00-architecture.md` §8-5). 다만 **hypertable로 만들어 두어 나중에 정책만 붙이면 되게** 한다.

**DoD (단계 6):** 발행값이 `telemetry`에 들어가고 `ts` 순으로 조회되며, **같은 Kafka 메시지를 두 번 소비해도 행이 하나**다.

---

### 단계 7 — 레지스트리 (선언 축 + 관측 축)

**왜 두 축인가.** BE-Q-03·VZ-I-03이 *"**존재해야 할** Entity 목록, Entity↔Node 소속, Node 원점의 전역 배치, Zone 트리, 표시 이름·별칭... **값을 발행하지 않는 미배포 대상도 이 목록으로 화면에 표시**"* 를 요구한다. 텔레메트리에서 자동으로 채우면 **미배포 대상이 영원히 안 나타난다.** 그리고 `registration()`이 주는 8개(`entity_id`·`node_id`·`zone_id`·`entity_type`·`device_type`·`fw_version`·`mac`·`ip`)에는 원점 배치·Zone 트리·표시 이름이 **없다** — 사람이 넣는 값이다.

**테이블 (MySQL `mk2`)**

| 테이블 | 축 | 주요 칼럼 |
|---|---|---|
| `registry_zone` | 선언 | `zone_id`(PK) · `parent_zone_id` · `display_name` · 시각 2 |
| `registry_entity_declared` | 선언 | `entity_id`(PK) · `zone_id` · `entity_type` · `node_id` · `display_name` · `alias`(JSON) · `deployed`(TINYINT) · `note` · 시각 2 |
| `registry_node_declared` | 선언 | `node_id`(PK) · `zone_id` · `display_name` · `origin`(**JSON**) · 시각 2 |
| `registry_entity_observed` | 관측 | `entity_id`(PK, 공통 헤더 `source_id`) · `entity_type` · `device_type` · `node_id` · `zone_id` · `schema_version` · `last_session_id` · `first_seen` · `last_seen` · `last_event` · `last_recorded_at` |
| `registry_node_observed` | 관측 | `node_id`(PK) · `fw_version` · `mac` · `ip` · `last_seen` · `last_recorded_at` |
| `registry_identity_history` | 관측(append) | `id`(PK) · `entity_id` · `changed_at` · `recorded_at` · `zone_id` · `node_id` · `mac` · `ip` · `fw_version` · `change_reason` |

> **`origin`을 JSON으로 두는 이유:** 좌표계 규약이 BE-C-04(Phase 7 연동)로 미확정이다. 지금 `x/y/z` 칼럼을 박으면 좌표 표현을 미리 고정하게 된다. 확정 후 승격한다.

**쓰기 경로 (관측 축만)**

저장 소비자가 `channel == "status"`이고 본문에 `registration`이 있을 때 **`RegistryWriter.observe(record)`를 부른다**(§2-1의 인터페이스 표). **새 소비자·새 컨슈머 그룹을 만들지 않고 이미 도는 `mk2-storage` 경로에 호출 한 줄을 더한다.** `consumer.py`는 MySQL 클라이언트를 직접 만들지 않고 이 인터페이스만 안다(제약 1).

`registration`이 없는 `status`(LWT·가짜 발행자 기본)는 **아무 일도 하지 않고 지나간다** — 예외를 내지 않는다.

**반드시 지킬 가드 셋**

1. **시각 가드.** 들어온 공통 헤더 `timestamp`가 저장된 `last_seen`보다 **이후일 때만** 갱신한다. `status`는 retained라 구독 즉시 마지막 1건이 밀려오고, 저장 소비자는 `earliest`라 재기동 시 옛 `status`를 다시 읽는다. 게다가 `status`에는 `sequence_id`가 없어(F4) 순번으로 신구를 못 가린다. **이 가드가 없으면 재기동할 때마다 대장이 과거로 되돌아간다.**
2. **빈 문자열 가드.** `mac`·`ip`가 빈 문자열이면 갱신하지 않는다. `analyzer`가 `Identity(dev, node_id, ZONE, "", "", "analysis")`로 빈 값을 보낸다(F7).
3. **이력 기록 조건.** `(zone_id, mac, ip)`가 이전과 다를 때만 `registry_identity_history`에 1행 추가한다. **이 셋은 HW의 `Identity.fingerprint()`와 같은 조합**이다 — 생산자의 재등록 판정 기준과 저장의 이력 기준이 어긋나지 않게 한다.

**DoD (단계 7):** `registration`이 실린 `status`를 발행하면 관측 축에 행이 생기고, **과거 시각 `status`가 최신값을 덮지 않으며**, `(zone, mac, ip)` 변경 시 이력이 1행 늘고, **빈 `mac`·`ip`가 기존 값을 지우지 않으며**, **선언만 있고 관측이 없는 미배포 대상이 조회에 나온다.**

---

### 단계 8 — 감사·실행 기록 스키마 (골격만)

#### `audit_log` (MySQL) — 스키마만, 쓰기 경로 없음

| 칼럼 | 비고 |
|---|---|
| `id` BIGINT AUTO_INCREMENT PK | |
| `occurred_at`·`recorded_at` DATETIME(6) | **서버 시각을 백엔드가 주입**(위조 불가, 원칙 5) |
| **`subject_kind` VARCHAR(32)** | `command` \| `plan` \| `model` — **대상 일반화** |
| **`subject_id` VARCHAR(128)** | `command_id` \| `plan_id` \| 모델 버전 |
| `action`·`target_entity_id`·`zone_id` | |
| `actor_kind`·`actor_id` | actor는 토큰에서(Phase 6) |
| `origin_kind` | 실물/시뮬 구분(BE-C-07·VZ-C-06) |
| `result`·`failure_code`·`correlation_id`·`origin_path` | |
| `detail` JSON · `record_version` VARCHAR(16) | |
| 인덱스 | `(subject_kind, subject_id)` · `(occurred_at)` · `(target_entity_id, occurred_at)` · `(actor_id, occurred_at)` |

**왜 일반화하나.** AI-L-06이 *"백엔드는 **승인 주체·시간·대상 버전과 적용 범위의 authoritative 기록**을 담당한다"*, AI-L-08이 *"기존 백엔드 저장·감사 인프라와 연결한다"*, VZ-U-08이 *"임무 계획 승인과 **별개 화면** — 승인 대상이 모델·정책·지식"* 을 요구한다. 성격은 감사와 같다(누가·언제·무엇을·어떤 결과로). **`command_id` 전용으로 좁게 만들면 나중에 넣을 자리가 없고, 지금 칼럼 하나 비용이면 끝난다.** 대응 BE-* 요구사항이 없다는 사실은 §10의 gap으로 기록한다.

#### `mission_event` (MySQL) — 스키마 + append 경로

| 칼럼 | 근거 |
|---|---|
| `seq` BIGINT AUTO_INCREMENT PK | VZ-D-02 **순번**. 서버가 부여하는 단조 증가 — 같은 시각의 사건 순서가 확정된다. 공통 헤더의 `sequence_id`(생산자 순번)와 **다른 것**이라 이름을 분리했다 |
| `occurred_at`·`recorded_at` DATETIME(6) | VZ-D-02 **시각** |
| **`layer` VARCHAR(16)** | VZ-D-02 **계층** = `milestone` \| `task` \| `action_item` (VZ-D-01의 3계층) |
| **`node_ref` VARCHAR(128)** | VZ-D-02 **노드** = 그 계층의 DAG 노드 식별자 |
| **`parent_ref` VARCHAR(128)** | VZ-D-01 "파생 출처를 유지" · VZ-D-05 "파생 관계를 역방향으로 따라가" |
| **`attempt` INT DEFAULT 1** | VZ-D-06 "재실행은 회차를 함께 표시" · VZ-D-08 "회차를 누적" |
| `event_type` VARCHAR(64) | VZ-D-02 **사건 종류**. **ENUM으로 박지 않는다** — 실패 단계 어휘가 미확정이다 |
| `actor_kind`·`actor_id` | VZ-D-02 "산출 주체(AI·백엔드·사람)를 **반드시** 포함" |
| `mission_id` VARCHAR(128) | VZ-D-04 "지난 임무를 이력에서 선택" |
| **`target_entity_id` VARCHAR(64)** | VZ-D-07 "레지스트리의 대상 목록을 마일스톤에 배정" · VZ-N-02 "태스크의 대상 장비·구역이 조회 범위" |
| `origin_kind` VARCHAR(16) | VZ-C-06 |
| `correlation_id` VARCHAR(128) | BE-X-01 명령 사슬. 이번엔 빈 채로 |
| **`event_key` VARCHAR(255) UNIQUE NULL** | 재삽입 멱등. MySQL UNIQUE는 NULL을 여럿 허용하므로 **키 없는 사건은 그냥 들어간다** — 생산자가 Phase 6에 붙는 이번 울타리와 충돌하지 않는다. utf8mb4 기준 1020바이트라 InnoDB 인덱스 상한(DYNAMIC 3072) 안 |
| `detail` JSON | VZ-D-02 **상세**. 미확정분은 전부 여기 |
| `record_version` VARCHAR(16) | 나중에 칼럼이 늘 때 옛 행을 구분 |
| 인덱스 | `(mission_id, seq)` · `(occurred_at)` · `(layer, node_ref, seq)` · `(target_entity_id, occurred_at)` |

> **"계층·노드"를 물리 축으로 읽으면 안 된다.** VZ-D-06 *"**노드** 상태를 대기·진행·완료·실패·건너뜀·평가 대기·미수행·재실행 8종"*, VZ-D-05 *"실패한 **노드**에서 의존·파생 관계를 역방향으로"* 가 전부 DAG 노드를 가리킨다. 물리 대상은 `target_entity_id` 하나로 충분하고 나머지는 레지스트리 조인으로 얻는다.
> **파티셔닝을 넣지 않는다.** 보존 기간이 미확정이라 파티션 경계를 정할 근거가 없다.
> **UPDATE·DELETE는 권한으로 막는다**(단계 2). 코드 규율이 아니라 DB가 지킨다.

**append 경로**는 저장 모듈에 함수 하나(`append_mission_event(...)`)로 두고 pytest로만 호출한다. **실제 생산자는 가시화·엣지이고(BE-S-08 전달 경로) 그 배선은 Phase 6/7이다.**

**DoD (단계 8):** 두 테이블이 서고, `mk2_app`으로 `UPDATE`·`DELETE`·`CREATE TABLE`이 **거부**되며, 같은 `event_key`를 두 번 append해도 1행이고, `subject_kind`가 `command`·`model`인 두 행이 같은 테이블에 들어간다.

---

### 단계 9 — 유실·역전 검출 (저장은 원본, 검출은 조회)

**Phase 2가 만드는 것은 "검출 로직"이 아니라 "검출이 가능한 저장"이다.**

적재 시점에 실시간 판정하면 **결정 3-A(지연 도착을 원래 시각에 꽂는다)와 정면 충돌한다** — 7분 뒤에 도착해 갭을 메울 데이터를 두고 미리 "유실"이라고 못 박을 수 없다. 그래서 **원본만 넣고 갭은 조회 시 `LAG()` 윈도우 함수로 계산**한다. TimescaleDB를 고른 이유 중 하나가 이 질의였다.

**검출 단위: `(source_id, channel, session_id)`**

- `session_id`가 있으면 그것이 경계다.
- **없으면(HW 적용 전 혼재 기간) `status`의 `birth`를 경계로 폴백**한다. `_on_connect`가 항상 `publish_status("birth")`를 부르므로 신뢰할 수 있는 표식이다. 보조 안전망으로 **순번이 크게 감소했는데 경계 표식이 없으면 경보만 남기고 새 구간으로 본다.**
- **경계 판정은 조회 시점에 SQL로 한다.** 적재 시 상태를 들고 있는 칼럼(`seq_epoch` 등)을 두지 않는다 — 무상태 원칙과 충돌하고 재기동 시 상태가 소실된다.

**채널별 의미 차등**

| 채널 | QoS | spool | 갭의 의미 | 판정 |
|---|---|---|---|---|
| `state`(센서·액추에이터) | 1 | 탄다 | 비정상 | **유실 후보로 기록** |
| `state`(로봇) | **0** | 탄다 | 유실 허용이 설계 | 갭은 세되 **유실로 단정하지 않는다** |
| `heartbeat` | 0 | 안 탄다 | 유실이 설계된 동작(F5). **로봇은 임무 중 아예 끈다(F15)** | 갭은 세되 유실로 단정하지 않는다 |
| `status` | 1 | 안 탄다 | **순번 없음** | **검출 제외** |
| `state`(analysis) | 0 | — | 전역 seq 공유(F8) | **검출 제외** |

**함께 저장해야 갭을 되짚을 수 있는 것 둘**

- **`reason`** — `replayed=true` 구간의 `reason="periodic"`(연속 표본)은 **다운샘플로 솎인 것이지 유실이 아니다**(F12). 이 구분이 없으면 정상 동작을 유실로 오판한다.
- **`status`의 `buffer.dropped`** — HW가 spool 상한 초과로 **스스로 버린 건수**다(`node.py:208`). 이때 갭은 진짜 손실이지만 원인이 네트워크가 아니라 버퍼 고갈이다. `payload` JSONB에 이미 들어 있으므로 조회로 대조할 수 있게 문서화한다.

**산출물:** `docs/be/queries/gap-detection.sql`(주석 포함)과 그것을 도는 pytest.

**DoD (단계 9):** 갭이 있는 데이터를 넣고 갭 조회가 그것을 집어내며, **세션 경계의 순번 리셋이 갭으로 잡히지 않고**, `status`가 검출 대상에서 빠지고, `heartbeat` 갭이 유실로 분류되지 않는다.

---

### 단계 10 — pytest 회귀

**기존 6건이 계속 통과해야 한다**(`test_contract_fixtures`·`test_valid_roundtrip`·`test_storage_sink_receives`·`test_ws_delivery`·`test_invalid_quarantined[missing-zone]`·`test_invalid_quarantined[timestamp]`).

**신규 (§7의 완료 판정과 1:1)**

**skip 장치를 먼저 만든다.** "인프라가 없으면 해당 테스트만 skip하고 나머지는 통과한다"는 저절로 되지 않는다. `tests/conftest.py`에 **접속 실패를 `pytest.skip`으로 바꾸는 fixture 둘**(`mysql_conn`·`tsdb_conn`)을 추가한다. 기존 Kafka fixture와 같은 방식이다. 이 격리 자체가 요구사항(핵심·선택 분리)의 증거이고, 없으면 인프라 하나가 없을 때 전건이 빨갛게 되어 **무엇이 진짜 실패인지 안 보인다.**

| 테스트(권장 이름) | 확인하는 완료 판정 |
|---|---|
| `test_tsdb_write_and_order` | 7 |
| `test_late_arrival_ordered_by_timestamp` | **8** (plan Phase 2 DoD 핵심) |
| `test_replayed_and_lag` | 9 |
| `test_clock_skew_kept_not_dropped` | 10 |
| `test_stream_offset_dedup` | 11 |
| `test_utc_storage_session_tz_invariant` | 12 |
| `test_payload_valid[robot\|sensor\|actuator\|analysis]` | 13 |
| `test_payload_status_birth_and_lwt` | 14 |
| `test_payload_invalid_quarantined` ★음성 | 15 |
| `test_payload_unknown_field_passes` | 16 |
| `test_analysis_not_quarantined` | 17 |
| `test_normalize_payload_fills_keys` | 18 |
| `test_registry_upsert_from_status` | 19 |
| `test_registry_time_guard` ★음성 | 20 |
| `test_registry_identity_history` | 21 |
| `test_registry_empty_mac_ip_not_overwrite` | 22 |
| `test_registry_declared_visible_without_telemetry` | 23 |
| `test_mission_event_idempotent` | 25 |
| `test_mission_event_update_denied` ★음성 | 24·26의 근거 |
| `test_ddl_denied` ★음성 | 6 |
| `test_audit_subject_generalized` | 26 |
| `test_gap_detection_query` | 27 |
| `test_session_boundary_not_gap` | 28 |
| `test_birth_fallback_when_no_session` | 29 |
| `test_status_excluded_from_gap` ★음성 | 30 |
| `test_publisher_default_matches_real_node` | 30-a — 기본 발행에 `entity_id`·`origin_kind`가 **없음**을 확인 |
| (conftest fixture) | 30-b |

**★음성 5건이 "검증이 무력하지 않은지"를 담당한다.** 이 다섯이 없으면 나머지는 "통과했다"만 말할 뿐 "잘못된 것을 실제로 막는다"를 말하지 못한다. Phase 1에서 `+0900`을 실제로 거부하는지 본 것과 같은 자리다.

**DoD (단계 10):** `python -m pytest -q` 전건 통과. 실행 위치는 서버(`~/capstone-db/phase1_work/Physical-Project-mk2`) — 검증 대상(Kafka·MySQL·TSDB·격리 파일)이 전부 서버 localhost에서만 보이기 때문이다(Phase 1과 같은 이유).

---

## 6. 이번에 하지 않는 것 (범위 울타리)

| 안 하는 것 | 어디로 |
|---|---|
| **명령·감사를 기록하는 로직** — 감사 테이블은 만들지만 명령이 실제로 흘러 들어가게 하지 않는다 | Phase 6 |
| **인증·인가(RBAC)** — 계정·권한 모델을 설계하지 않는다. `mk2_app`은 앱 접속 계정이지 사용자 권한 모델이 아니다 | Phase 6 (감사와 동시) |
| **실행 기록의 되감기 질의·구체 필드·실패 단계 어휘·보존 기간** — BE-S-08 원문이 *"상세 계약은 본 요구사항의 범위가 아니며 실제 소비 시점에 구체화한다"* | 가시화 회신 후 |
| **실행 기록의 실제 쓰기 배선** — 생산자가 가시화·엣지다(BE-S-08 전달 경로) | Phase 6/7 |
| **레지스트리 조회 API·capability 등록**(AI-C-18) | Phase 5/6 |
| **가용성 판정** — `status`·LWT·`heartbeat`를 저장만 하고 판정하지 않는다 | Phase 5 |
| **WS 게이트웨이 본구현·외부 노출** | Phase 5/7, 노출은 Phase 4 |
| **관측 신호 계측** — §8-3의 A·B·C 어느 층도 붙이지 않는다. 다만 C층 대상이 이번 본문 규격에서 나오므로 신호 종류 힌트만 표시한다 | Phase 3 |
| **미디어·Kafka 원격 노출** | Phase 4 |
| **TSDB 보존 기간·압축·재난 구간 아카이브**(BE-S-04) | 발동 조건 충족 시(§8-5) |
| **MySQL의 `0.0.0.0:7858`·`root@%` 노출 수정** — 다른 파트가 쓰는 컨테이너다 | 기록만, Phase 6 |
| **compose `version: '3.3'` 경고 제거** — 무해하고, 도는 12개를 건드리는 쪽이 더 위험하다 | 하지 않는다 |
| **Phase 1 확정분 재설계** | 하지 않는다 |

---

## 7. 완료 판정 (아래가 전부 참이어야 끝난 것)

### 인프라·계정

- [ ] **1.** 단계 0의 서버 확인 결과를 **받은 뒤에** 착수했다.
- [ ] **2.** `timescale-db`가 `Up (healthy)`이고 **다른 11개 서비스가 재생성되지 않았다**(`docker ps`의 가동 시간으로 확인).
- [ ] **3.** 이미지 태그가 **구체 버전으로 고정**돼 있다(`:latest` 없음).
- [ ] **4.** 새 포트가 `127.0.0.1`에 바인딩됐고 **ufw에도 열려 있다**.
- [ ] **5.** 비밀값이 `/home/dg/capstone-db/.env`(저장소 밖, chmod 600)에 있고 커밋되지 않았다(`git status`·`git check-ignore`로 확인).
- [ ] **6.** `mk2_app`으로 두 저장소에 접속되고, **`CREATE TABLE`·`mission_event` UPDATE·DELETE가 권한 거부**된다.

### 계측 (TSDB)

- [ ] **7.** 발행값이 `telemetry`에 도달하고 **`ts`(발행 시각) 순으로** 조회된다.
- [ ] **8.** **지연 도착이 원래 측정 시각 위치에 꽂힌다** — 과거 시각 메시지를 나중에 발행하면 과거 자리에 정렬된다. (plan Phase 2 DoD의 핵심 항목)
- [ ] **9.** `replayed=true`가 보관되고 `lag_s`가 계산된다.
- [ ] **10.** 음수 `lag_s`가 **버려지지 않고** `clock_skew=true`로 저장된다.
- [ ] **11.** **같은 Kafka 메시지를 두 번 소비해도 행이 하나다**(스트림 좌표 유일 키).
- [ ] **12.** 세션 타임존을 바꿔도 **같은 순간**을 가리킨다 — MySQL `DATETIME(6)`은 저장 값이 그대로이고, TSDB `TIMESTAMPTZ`는 표현이 달라져도 같은 시각이다.

### 본문 규격 (2단 검증)

- [ ] **13.** 로봇·센서·액추에이터·analysis 4종 본문이 **전부 통과**한다.
- [ ] **14.** `status`의 birth와 **LWT가 둘 다 통과**한다.
- [ ] **15.** **필수 필드 누락이 실제로 격리되고 토픽에 나타나지 않는다**(음성, 10초 관측).
- [ ] **16.** **모르는 필드가 통과한다**(느슨한 2단 확인).
- [ ] **17.** **analyzer 형식 메시지가 격리되지 않는다**(F6 사고 방지).
- [ ] **18.** `normalize_payload()`가 없는 키를 규격대로 채워 돌려준다 — **값이 없는 항목이 키를 유지한 채 나온다.**

### 레지스트리

- [ ] **19.** `registration`이 실린 `status`로 관측 축이 채워진다.
- [ ] **20.** **과거 시각 `status`가 최신값을 덮지 않는다**(음성).
- [ ] **21.** `(zone, mac, ip)` 변경 시 이력이 1행 늘어난다.
- [ ] **22.** **빈 `mac`·`ip`가 기존 값을 지우지 않는다**.
- [ ] **23.** **선언만 있고 관측이 없는 미배포 대상이 조회에 나온다**(BE-Q-03 핵심).

### 감사·실행 기록

- [ ] **24.** 두 테이블이 서고 스키마가 §5 단계 8과 일치한다.
- [ ] **25.** 같은 `event_key`를 두 번 append해도 1행이다.
- [ ] **26.** `subject_kind`가 `command`·`model`인 두 행이 같은 감사 테이블에 들어간다.

### 순번 검출

- [ ] **27.** 갭 조회 SQL이 갭을 집어낸다.
- [ ] **28.** **세션 경계의 순번 리셋이 갭으로 잡히지 않는다**(`session_id` 경로).
- [ ] **29.** `session_id`가 없을 때 **`birth` 폴백**이 동작한다(혼재 기간).
- [ ] **30.** **`status`가 검출 대상에서 빠지고**(음성), `heartbeat` 갭이 유실로 분류되지 않는다.

### 회귀·산출물

- [ ] **30-a.** `tests/publisher.py`가 단계 4-A대로 확장됐고, **기본 발행 필드 집합이 실노드와 같다**(`entity_id`·`origin_kind` 없음). `analyzer` 형식은 **결함까지 그대로 재현**한다.
- [ ] **30-b.** `tests/conftest.py`에 `mysql_conn`·`tsdb_conn` skip fixture가 있고, 인프라 하나가 없을 때 **그 테스트만 skip되고 나머지는 통과**한다.
- [ ] **31.** `python -m pytest -q` **전건 통과**(기존 6건 포함). **본문 검증을 켠 뒤에도 기존 6건이 살아 있다**(단계 4-A가 없으면 여기서 깨진다).
- [ ] **32.** 음성 대조 5건이 실제로 거부·차단을 확인한다.
- [ ] **33.** HW 회신 초안(§9-1)과 가시화 문의 초안(§9-2)이 **§9-0의 규율 6개를 지켜** 작성됐다 — 특히 **모든 물음에 「우리는 이렇게 읽었다」와 「답이 없을 때의 기본값」이 붙어 있다.**
- [ ] **33-a.** HW 회신은 새 파일이 아니라 `hw-envelope-conformance.md`의 §6이며, **§1-3의 "Phase 2에서 확정해 회신한다"에 링크가 걸리고** §5 표와 「HW가 할 일」 요약이 함께 갱신됐다.
- [ ] **33-b.** 가시화 문의는 §9-2의 골격(§0~§4)을 따르고, `mission_event` 칼럼마다 **어느 요구사항 문장에서 나왔는지**가 붙어 있다.
- [ ] **34.** §10의 보고 3종이 남았다.
- [ ] **35.** 인코딩 UTF-8·LF, 비밀값·내부망 IP 미커밋.

> **검증 범위의 한계를 완료 판정에 함께 적는다.** `session_id`·본문 4종 중 로봇·액추에이터·analysis는 **가짜 발행자로만 검증된다** — HW가 `session_id`를 아직 안 보내고, 로봇·액추에이터·analyzer 실노드가 서버 브로커에 붙어 있지 않다. **실노드 검증은 조병현이 회신을 반영한 뒤로 넘긴다.** 이것을 "검증됨"으로 적지 않는다.
> **실노드로 저장을 검증하려면** 조병현이 공통 헤더 편집 4개를 HW 저장소에 적용했는지 **먼저 확인**해야 한다(안 하면 전량 격리). 다만 Phase 2 저장 검증은 가짜 발행자와 기존 sink 데이터(315줄)로도 되므로 실노드가 필수는 아니다.

---

## 8. 작업 방식

- **편집·생성은 컴퓨터(Claude Code), 실제 실행·pytest·서버 명령은 사람이 서버(`sysai-server2`)에서.** Claude Code는 서버에 붙지 않고, 서버 파일을 직접 고치지 않으며, **명령을 제시해 결과를 받아 반영한다.**
- 서버 배포는 `git pull`이 아니다. `infra/`에서 편집 → 사람이 서버에 복사·적용 → 결과 회수.
- 서버 상태 조회 결과·설정 사본은 `_serverinfo/`(gitignore)에 둔다. **커밋 금지** — 서버 포트·방화벽·내부 IP가 노출되면 안 된다.
- 코드 docstring 상단에 `implements: BE-X-NN`을 남긴다.
- **막히면 임의로 정하지 말고 `reports/`에 남기고 멈춘다.**

---

## 9. 타 파트 회신·문의 초안 (산출물)

### 9-0. 회신·문의 문서를 쓰는 규율 (둘 다 적용)

**이 문서들은 "우리가 뭘 했는지"를 알리는 글이 아니라 상대가 읽고 바로 판단·행동할 수 있는 문서다.** 아래 여섯을 지킨다.

1. **머리말 표를 먼저 둔다** — 보내는 쪽 / 받는 쪽 / 참조 / 작성일 / 근거 / 대상 안건. 몇 달 뒤 이 파일만 보고도 "누가 무엇에 답한 것인지"가 서야 한다.
2. **모든 주장에 근거를 붙인다.** 소스면 `파일:줄`, 요구사항이면 ID, 실측이면 그 수치. **탁상 검토와 실측을 섞어 쓰지 않는다** — 실측이면 실측이라고 적는다.
3. **각 물음에 「우리는 이렇게 읽었다」와 「답이 없으면 이 기본값으로 간다」를 반드시 붙인다.** 상대가 백지에서 설계하는 대신 **확인만 하면 되게** 만든다. 이건 HW가 `BACKEND_AGENDA` §0에서 쓴 방식 그대로다 — *"회신이 늦어져도 개발이 멈추지 않도록 각 미결에 기본값을 정해 구현했다. 원칙은 하나 — 회신이 오면 코드가 아니라 설정·구성요소 하나만 바뀌게 만든다."* 그 방식이 실제로 통했으므로 같은 규율을 우리도 쓴다.
4. **상대 파트에 코드 변경을 요구할 때는 파일·상수·before/after를 그대로 적는다.** 추상적으로 "고쳐 달라"고 하지 않는다. 선례는 `hw-envelope-conformance.md` §1-1의 편집 4개다 — 그래서 조병현이 한 파일만 고쳐 끝냈다.
5. **우선순위를 매긴다.** 🔴 지금 막고 있는 것 / 🟡 곧 필요한 것 / ⚪ 나중. 전부 급하다고 쓰면 아무것도 안 급해진다.
6. **끝에 「상대가 할 일」 요약을 둔다.** 본문이 길어도 그 표만 보면 행동이 나오게.

> **전달 시점 (둘 다):** 초안은 이번 Phase에서 만들고, **확정·전달은 Phase 2 구현이 끝난 뒤** 보고서·추적표 갱신과 같은 묶음으로 한다. 구현하며 드러나는 것이 초안에 반영되어야 두 번 보내지 않는다. **답을 기다리느라 Phase 2를 멈추지 않는다.**

### 9-1. HW 회신 — `docs/be/hw-envelope-conformance.md` §6 후속 회신

> 수신: 하드웨어(조병현) / **참조: AI(진나영)** — 본문 항목 이름 통일은 AI-C-18이 "실제 변수명은 팀 공통 규격에서 최종 통일"로 남겨 둔 사안이라 AI도 확정 대상이다.

**형식:** 새 파일을 만들지 말고 **기존 `hw-envelope-conformance.md`에 `## §6` 절을 이어 붙인다.** 그 파일의 기존 골격(머리말 표 → 안건별 절 → 검증 결과 → 아직 회신하지 않은 안건 → 「HW가 할 일」 요약)을 그대로 따른다. 아래 셋은 반드시 함께 갱신한다.

- **§1-3의 "Phase 2에서 확정해 회신한다"** 문장에 §6을 가리키는 링크를 붙인다 — 약속한 자리에 답이 없으면 상대가 못 찾는다.
- **§5「아직 회신하지 않은 안건」표**에서 이번에 답한 행을 처리 완료로 옮긴다.
- **§요약「HW가 할 일」**에 이번 요청(편집·확인·반영)을 더한다.

담을 내용:

1. **`sequence_id` 의미 확정 (§1-3 약속 이행).** 채널별 독립 순번을 그대로 확정. 검출 단위는 `(source_id, channel, session_id)`. `status`에 순번이 없는 것을 정상으로 확정. `heartbeat`(QoS 0)·로봇 `state`(QoS 0)의 갭을 유실로 판정하지 않는다. 재전송 구간의 `continuous` 다운샘플을 유실로 오판하지 않는다.
2. **`session_id` 신설 요청 (HW 변경 4줄, `pi/common/schema.py` 한 파일).** `import uuid` + `SESSION_ID = uuid.uuid4().hex[:12]`(모듈 전역, 파일 저장 안 함) + `envelope()`에 한 줄 + `SCHEMA_VERSION = "1.1"`. `envelope()` 한 곳이라 전 노드에 자동 반영되고 노드별 작업이 없다. **재접속(브로커 끊김·구역 변경)에서는 프로세스가 유지되므로 세션도 순번도 유지되고, 프로세스 재시작에서만 둘이 함께 바뀐다** — `birth` 경계가 못 주던 보장이다. spool 재전송분이 원래 세션을 달고 오는 것도 이 방식의 이점이다.
3. **결함 보고: `pi/robot/robot_node.py`에 `self.seq += 1`이 없다.** 로봇 `state`가 항상 `sequence_id: 0`으로 나간다. 센서·액추에이터에는 있다. 안 고치면 로봇 `state`의 유실·역전 검출이 성립하지 않는다.
4. **`origin_kind` 미발행.** BE-C-07(원천 종류 표기 규약)이 **HW 브랜치의 요구사항 사본에 없다** — 구현 누락이 아니라 사본이 낡은 것이다. 전체 스프레드시트에는 있다.
5. **`entity_id` 미발행.** 선택 필드라 무해하지만, 노드=개체가 1:1이 아닌 배포에서는 필요해진다.
6. **`analyzer` 3건.** ① 토픽 마지막 칸은 `state`인데 본문 `channel`은 `analysis`다 — 백엔드는 토픽으로 라우팅하므로 무해하나, 본문 `channel` 필드를 유지할지 정해야 한다. ② `seq`가 모듈 전역이라 대상별로 순번에 구멍이 뚫린다. ③ `Identity(..., "", "", "analysis")`의 빈 `mac`·`ip`가 레지스트리로 들어온다(백엔드가 가드를 넣었다).
7. **`state`의 `reason` 어휘 확인 요청.** 센서 4종·로봇 3종·액추에이터 7종으로 읽었다. 맞는지, 늘어날 계획이 있는지. 저장 층이 `periodic`을 다운샘플 대상으로 구분하는 근거로 쓴다.
8. **`timestamp` 해상도 권고(선택, F3).** 현재 `timespec="seconds"`라 로봇 20Hz에서 1초에 20건이 같은 시각을 갖는다. 유일 키를 스트림 좌표로 잡아 저장에는 문제가 없으나, `lag_s` 정밀도와 되감기 해상도에는 영향이 있다. `milliseconds` 권고.
9. **본문 항목 목록·누락값 형태 확정 통지** (§5 단계 4의 표 전체). 구분 필요 항목은 `state`의 계측값과 `status.registration` 둘.
10. **요청: HW 브랜치의 요구사항 시트를 전체 공유 스프레드시트에 반영해 달라.** 10곳이 어긋나 있고, 그 값들은 백엔드 v8을 채택한 결과라 **스프레드시트 쪽이 백엔드와 어긋난 상태**다.

**참고(변경 요청 아님):** 발행 실패로 spool에 들어가도 순번은 증가한다. 백엔드는 순번을 "발행 시도 번호"로 해석하며 이 동작을 바꿀 필요는 없다.

### 9-2. 가시화 문의 — `docs/be/vz-mission-record-inquiry.md` (신규)

> 수신: 가시화(김현우) / 참조: AI(진나영 — 7번 항목)

**형식:** 선례가 없는 신규 파일이므로 아래 골격으로 쓴다. `hw-envelope-conformance.md`의 구조를 문의 방향으로 뒤집은 것이다.

```
# 실행 기록 규격 문의 — 가시화 파트

| | |                          ← 머리말 표(규율 1)
|---|---|
| 보내는 쪽 | 백엔드(BE·DT) / 이대규 |
| 받는 쪽   | 가시화(VZ) / 김현우 |
| 참조      | AI / 진나영 (§2-7) |
| 작성일    | |
| 근거      | Phase 2(저장 축) 구현 결과 · 요구사항 정의서 VZ-D-02·D-04·D-05·D-06·D-08·N-02·N-03 · BE-S-08 |
| 대상 안건 | VZ-D-02 「기록 계약 미정」 · VZ-D-05 「실패 단계 어휘 합의 필요」 |

## §0 한 장 요약
    무엇을 물어보는지 · 답이 없으면 백엔드가 어떻게 진행하는지 · 우선순위

## §1 백엔드가 이미 만들어 둔 것
    mission_event 칼럼 표 — 칼럼마다 **어느 요구사항 문장에서 나왔는지**를 붙인다.
    (예: layer ← VZ-D-02 "계층", node_ref ← VZ-D-02 "노드", attempt ← VZ-D-06·D-08 "회차")
    "우리가 원문을 이렇게 읽었다"를 드러내는 것이 이 절의 목적이다 —
    읽기가 틀렸으면 여기서 바로 잡힌다.

## §2 확인·보완 요청 (항목마다 네 줄 고정)
    ① 묻는 것  ② 우리는 이렇게 읽었다(근거 ID)  ③ 왜 필요한가
    ④ **답이 없을 때 백엔드가 쓰는 기본값**            ← 규율 3

## §3 답이 오면 무엇이 바뀌나
    항목별 전환 비용 표. "칼럼 추가"인지 "스키마 변경"인지 "재작업"인지 구분한다.
    대부분 detail JSON → 칼럼 승격이라 저렴하다는 것을 보여 준다.

## §4 가시화가 할 일 (요약)                ← 규율 6
```

**§2에 넣을 항목 7개:**

1. **실행 기록의 구체 필드** — 우리가 만든 골격(§5 단계 8)을 제시하고 확인·보완을 요청한다. VZ-D-02의 `[기록 계약 미정]`을 이걸로 닫자는 제안.
2. **실패 단계 어휘** — VZ-D-05의 `[실패 단계 어휘 합의 필요]`. `event_type`을 ENUM으로 박지 않고 VARCHAR로 둔 것이 이 때문이다.
3. **보존 기간.** 사건 밀도가 초당 수십 건(VZ-D-02: 로봇 상태 50ms·액추에이터 50ms)이라 보존 기간이 용량을 좌우한다.
4. **`node_ref` 식별자 체계 — 누가 부여하나.** 마일스톤·태스크·액션 아이템을 만드는 주체가 가시화(VZ-G-01/02/04)이므로 가시화가 부여하는 것으로 이해했다. 확인 요청.
5. **`attempt`(회차)의 증가 규칙.** VZ-D-08의 "파라미터 수정은 회차를 누적"이 노드 단위인지 태스크 단위인지.
6. **VZ-N-02·N-03이 요구하는 구간 질의.** 재생 머리를 과거로 옮기면 **지표(TSDB) 뷰 노드도 그 시점 값을 보여야 한다.** 태스크의 실행 구간·대상 장비로 TSDB를 구간 질의하는 인터페이스 형태를 정해야 한다(백엔드 질의 프록시 BE-Q-01, Phase 5/6).
7. **VZ-U-08의 모델 적용 승인 기록.** AI-L-06이 "백엔드가 승인 주체·시간·대상 버전·적용 범위의 authoritative 기록"을 요구하는데 **대응 BE-* 요구사항이 없다.** 감사 테이블을 `subject_kind`로 일반화해 자리를 만들어 두었다. 이 해석이 맞는지, 요구사항 신설이 필요한지.


---

## 10. 보고 (작업 끝에 반드시 남기는 것)

### 10-1. `reports/YYYY-MM-DD_HHMM_phase2_저장축.md`

배경 / 한 일 / 검증 / 다음. 특히 **지시서와 다르게 이행한 것**과 **작업 중 발견한 것**을 반드시 적는다.

### 10-2. `docs/be/requirement-traceability.md` 갱신

| 행 | 갱신 방향 |
|---|---|
| **BE-S-01** | 부분 → 상태 재판정. 구현 위치를 실제 파일로. gap에 남는 것: 보존 기간·재난 아카이브(BE-S-04), 실노드 검증 미완 |
| **BE-S-05** | 미착수 → **부분(스키마까지)**. gap: 쓰기 경로·actor 주입은 Phase 6 |
| **BE-S-08** | 미착수 → **부분(골격·append 경로)**. gap: 구체 필드·실패 단계 어휘·보존 기간·되감기 질의 |
| **BE-C-01** | gap 갱신 — 채널 본문 스키마 신설, 누락값 규칙 적용, `session_id` 추가로 규격 `1.1` |
| **BE-C-02** | 미착수 → **부분(레지스트리 관측 축)**. gap: 조회 API |
| **BE-Q-03** | gap 갱신 — 선언·관측 2축 테이블은 섰으나 조회 API·capability 등록은 미착수 |
| **BE-C-07** | gap 추가 — **HW의 요구사항 사본에 이 항목이 없어 실노드가 `origin_kind`를 발행하지 않는다** |
| **BE-S-07** | gap 갱신 — `lag_s`가 지연 측정 재료로 저장되기 시작했다(A층 계측은 Phase 3) |
| **(신규 gap)** | **모델 적용 승인 기록(AI-L-06/07/08·VZ-U-08)에 대응하는 BE-* 요구사항이 없다.** 감사 테이블을 `subject_kind`로 일반화해 자리만 확보 |
| **요약 절** | 총계·상태 갱신. 요구사항 파일 기준(§2-5)을 명시 — 다음 세션이 또 헤매지 않도록 |

### 10-3. `docs/be/01-standalone-implementation-plan.md` 갱신

「지금 당장 할 일」 ④ 체크 + 발견한 이월을 **그 조치가 이뤄질 Phase 항목에** 적는다(규율 8 — 보고서에만 적으면 몇 Phase 뒤에 죽는다).

| 이월 | 어느 Phase |
|---|---|
| C층 대상은 이번 본문 규격에서 고른다. 라벨 금지 목록에 `session_id`·`internal_seq` 추가 | **Phase 3** |
| **VZ-C-07** — 가시화가 WS 게이트웨이 주소를 화면에서 설정한다. 외부 노출이 전제 | **Phase 4/5** |
| 구역 변경 시 빈 payload가 격리 파일을 오염시킨다(F10) — ingest 손질 | **Phase 5** |
| 엣지 `availability.py`의 1차 판정과 백엔드 최종 판정의 관계 / `device_status` 주체 | **Phase 5** |
| **VZ-N-02·N-03** — 재생 머리 하나가 실행 기록·계측·감사를 묶는다. 조회 프록시가 구간 질의를 지원해야 한다 | **Phase 5/6** |
| 감사 쓰기 경로·actor 토큰 주입·RBAC | **Phase 6** |
| **모델 적용 승인 기록** — BE-* 신규 요구사항 필요 | **Phase 6** |
| MySQL `0.0.0.0:7858` + `root@%` 노출 | **Phase 6**(인증·인가와 함께) |
| TSDB 보존 기간·재난 구간 아카이브(BE-S-04) | 발동 조건 시(§8-5) |

### 10-4. `infra/README.md` 정정 2건 (근거가 실측으로 뒤집혔다)

1. **§5의 "docker publish는 DNAT라 ufw를 상당부분 우회하므로 실질 통제는 인터페이스 바인딩" 서술.** 서버에서 **9100 포트를 ufw에 열자마자 Prometheus 수집이 정상화된 실측**이 이 서술을 반증한다. 이 문장을 믿고 Phase 4에서 "ufw는 안 열어도 된다"고 판단하면 같은 사고가 반복된다. **"서비스의 외부 포트는 ufw에도 반드시 연다"**로 고친다.
2. **§5 Kafka 리스너 사용처.** 현재 Kafka에 붙는 백엔드 3개(ingest·저장 sink·WS 게이트웨이)는 **호스트 프로세스**라 `localhost:9092`의 **PLAINTEXT 리스너**를 쓴다. INTERNAL(9094)은 같은 docker 네트워크 컨테이너용이며 **현재 쓰는 클라이언트가 없다.** 따라서 Phase 4에서 PLAINTEXT advertised를 바꾸면 **백엔드도 영향을 받는다.** (서버 compose 파일의 주석은 gitignore라 남지 않으므로 커밋되는 이 문서에 적는다.)
3. §2 스택 표에 TimescaleDB 행, §3 포트 표에 7859 추가.

---

## 11. 부록 A — 결정 다섯의 근거 요약

구현 중 "왜 이렇게 정했나"를 되짚어야 할 때 본다. **바꾸라는 뜻이 아니다.**

### 결정 1 — TimescaleDB

- **InfluxDB 3 Core 배제:** 질의 시간 범위가 기본 약 72시간으로 제한되며(최근·과거 양쪽), 공식 문서가 기본값 유지를 권고한다. **계측 원본 보존(§8-3 제약 2)·BE-S-04 장기 보존·되감기와 정면 충돌**한다.
- **InfluxDB 2.9 배제:** 동작은 하지만 공식 문서가 v2를 이전 버전으로, v3 Core를 최신 안정 버전으로 표기한다. 조회 어휘도 SQL이 아니라 MySQL 축과 갈린다.
- **채택 근거 셋:** ① 결정 3·4가 전부 윈도우 함수로 푸는 SQL 문제다 ② 감사·레지스트리·실행 기록이 MySQL이라 조회 어휘가 한 벌로 통일된다 ③ 공통 칼럼 + `JSONB` 구조라 본문 규격 확정 전에도 테이블이 선다.
- **정직한 약점:** 관계형 엔진이 둘이 된다(MySQL + PostgreSQL). 백업·계정·모니터링이 두 벌이다.
- 교체 지점은 `TelemetryWriter.write()` 뒤 하나뿐이라 **잠금 범위는 이미 좁게 설계돼 있다**(원칙 1).

### 결정 2 — MySQL·레지스트리·실행 기록

- 계정 host를 `172.18.%`로 두는 근거는 실측이다 — 호스트에서 `127.0.0.1:7858`로 붙은 연결이 MySQL 쪽에서 `172.18.0.1`로 보인다. `'localhost'`는 붙지 못한다.
- 권한 차등의 목적은 **append-only를 코드 규율이 아니라 DB가 지키게** 하는 것이다.
- 레지스트리 2축의 근거는 BE-Q-03·VZ-I-03의 "미배포 대상도 목록에 표시".
- 감사 일반화의 근거는 AI-L-06/07/08·VZ-U-08.

### 결정 3 — 적재 시각

- **시간축 = `timestamp`**: `message.schema.json`이 이미 *"저장소가 이 시각 기준으로 병합·정렬하며, 재전송된 지연 도착 데이터도 원래 측정 시각으로 정합한다"*를 명시하고, **BE-S-01 원문(전체 스프레드시트 신판)이 같은 문장을 요구사항으로 못박는다.** `received_at` 축은 plan Phase 2 DoD를 원천적으로 만족할 수 없다.
- **`ingest_at`을 Kafka 헤더로**: 본문 주입은 Phase 1 확정("원본 바이트 그대로")을 깬다.
- **UTC 저장**: MySQL `TIMESTAMP`는 세션 타임존으로 변환돼 클라이언트마다 다르게 읽힌다. 컨테이너 `TZ: Asia/Seoul`이 `system_tz=KST`의 원인이므로 거기에 기대지 않는다.
- **스트림 좌표 유일 키**: 재소비는 도착 계층의 현상이다. 업무 내용 키는 로봇(F1)·`status`(F4)·analysis(F8)에서 전부 깨진다.

### 결정 4 — `sequence_id`

- 소스별 합산은 성립하지 않는다 — 카운터가 물리적으로 둘(`self.seq`/`self.hb_seq`)이라 매 메시지가 갭으로 잡힌다.
- `birth` 경계의 오판은 두 방향이다. 놓쳤을 때뿐 아니라 **순번이 안 끊겼는데 `birth`가 와서 구간이 쪼개지는 쪽이 더 흔하다**(F11). `session_id`가 그것을 없앤다.
- 검출을 적재 시점에 하면 결정 3-A와 충돌한다 — 나중에 도착해 갭을 메울 데이터를 두고 미리 유실이라 못 박을 수 없다.

### 결정 5 — 채널 본문

- `additionalProperties: false`는 **HW가 필드 하나 추가하는 순간 전량 격리**를 부른다. `status_extra()`는 노드마다 다른 필드를 반환하도록 설계된 훅이라 필드가 느는 것이 정상 동작이다.
- 헤더만 검증하면 저장 층이 값의 존재를 가정할 수 없다.
- etype 판별을 토픽에서 하는 근거: `bridge.py`가 이미 토픽을 쪼개고 있고, `{zone}/{etype}/{eid}/{channel}` 4칸 구조와 etype 어휘 4종을 `hw-envelope-conformance.md` §2-1·2-3에서 이미 확정으로 회신했다. 레지스트리 조회가 아니라 닭-달걀이 없다.
- 공통 코어가 `reason` + `device_status` 둘인 근거: 3종 `state` 본문의 교집합이 정확히 이 둘이다. `position`은 이름이 같고 타입이 달라 공통에 넣을 수 없다.

---

## 12. 부록 B — 이 지시서가 딛고 선 실물 근거

구현 중 사실 확인이 필요하면 여기를 먼저 본다.

| 사실 | 근거 위치 |
|---|---|
| 서버 상태 전부 | `260909_phase2_서버확인로그1.txt` (A~H 블록) |
| 로봇 `seq` 미증가 | `pi/robot/robot_node.py:99` + 같은 파일에 `self.seq += 1` 부재 |
| `received_at` 생성 지점 | `backend/storage/writer.py:37` · `backend/storage/consumer.py:64` |
| `timestamp` 해상도 | `pi/common/schema.py`의 `iso_now()` |
| `status`에 순번 없음 | `pi/common/node.py:200` · LWT는 `:92` |
| analyzer 토픽·본문 불일치 | `pi/augment/analyzer.py:126, 136` |
| analyzer 빈 mac/ip | `pi/augment/analyzer.py:123` |
| 다운샘플 정책 | `pi/common/spool.py`의 `_downsample()` |
| `replayed` 표식 한계 | `pi/common/spool.py`의 `replay()` |
| 재소비 구조 | `backend/storage/consumer.py:35-38` |
| 구역 변경 빈 payload | `pi/common/node.py:253` |
| 실행 기록 필드 원문 | 전체 스프레드시트 김현우 시트 VZ-D-02·D-04·D-05·D-06·D-08 |
| 레지스트리 요구 원문 | 전체 스프레드시트 이대규 BE-Q-03 · 김현우 VZ-I-03 |
| 모델 승인 기록 요구 | 전체 스프레드시트 진나영 AI-L-06·L-07·L-08 · 김현우 VZ-U-08 |
| 되감기가 지표까지 묶음 | 전체 스프레드시트 김현우 VZ-N-02·N-03 |
| BE-S-08 범위 한계 원문 | 전체 스프레드시트 이대규 BE-S-08 |
