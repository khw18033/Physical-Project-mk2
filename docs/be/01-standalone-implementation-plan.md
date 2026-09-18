# 백엔드 구현 착수 계획 (담당: 이대규)

> 목적: 하드웨어(실 센서·카메라)·AI(실 모델)·가시화(Unity 트윈)가 아직 없어도 **지금 로컬에서
> 구현하고 검증할 수 있는 범위**를 가려내고, 무엇을 어떤 순서로 언제까지 만드는지 정한다.
> 근거: [`00-architecture.md`](00-architecture.md)(5구간 구조) · [`02-media-path.md`](02-media-path.md)(미디어) ·
> [`requirement-traceability.md`](requirement-traceability.md)(BE-* 47건 상태) · 요구사항 정의서(엑셀) 이대규 시트.

---

## 0. 핵심 전제 — 백엔드 스택은 거의 전부 "지금 되는 것"이다

막힌 것을 두 종류로 분리한다(AI 파트 `01-standalone-implementation-plan`의 Tier 통찰을 백엔드에
적용).

- **(1) 실 인프라 소프트웨어** — Kafka · Mosquitto · OpenTelemetry Collector · Prometheus ·
  Grafana · Loki · Tempo · MySQL · TSDB · WebSocket 게이트웨이. 이것들은 *하드웨어가 아니라
  소프트웨어*이며 **개발 머신 한 대에서 Docker Compose로 전부 실행 가능**하다. 즉 "타 파트
  대기"가 아니라 **지금 바로 착수 가능**하다. (AI 파트가 같은 머신에서 mosquitto·Kafka(KRaft)·
  OTel Collector·K3s를 실제로 띄워 이미 증명했다.)
- **(2) 실 하드웨어 / 물리 현장** — 카메라·센서·GPU/NPU·로봇 제어계·현장 회선·Unity 트윈 렌더.
  이것만 mock 대체 대상이다.

**결론: 백엔드가 "다른 파트 없어서 못 하는" 것은 거의 없다.** 관측 백엔드·저장·라우팅·가용성
판정·WS push는 전부 Tier A/B다. 진짜 막히는 것은 디지털 트윈의 Unity 렌더 연결(가시화 대기)과
현장 실측(회선 QoS·콜드스타트 지연 등)뿐이다.

### 0-1. 공짜 가짜 발행자 — 실 센서·실 AI 없이 파이프라인을 관통한다

두 팀원의 산출물이 백엔드에 실제 MQTT 발행자를 제공한다.

- **조병현 `sensor_node.py`** — 이미 BE-C-01/02 공통 헤더 형식으로 실제 MQTT를 발행한다
  (`status`/`heartbeat`/`state`/`cmd`/`cmd/ack`/`cmd/result` 6채널). 하천 도메인(수위)이라 과업
  A(하천 감시·제어)와도 맞는다.
  > ⚠ 낡은 서술 — Phase 1에서 확인: 구 JSON `cmd/*` 3채널은 **폐기**됐고 명령은 protobuf
  > `terminal/<id>/downlink|uplink`로 흐른다. 텔레메트리는 `state`·`status`·`heartbeat` **3채널**이다
  > (Phase 6 이월 참조). Phase 2에서 이 3채널의 **본문 규격 6종**을 만들었다.
- **진나영 `simulation/terminals.py`의 `VirtualRiverTerminal`** — 하천/로봇 시뮬 MQTT 발행자.

이는 조병현이 실 센서 없이 가짜 수위값(`read_water_level()`)으로 파이프라인부터 뚫은 것과 같은
전략이다 — **먼저 파이프라인을 관통시키고 그 위에 기능을 얹는다.**

### 0-2. 백엔드의 허브 위치

- 방금 정의한 공통 헤더([`../../contracts/common/`](../../contracts/common/))가 세 팀원을 정렬시킨다.
  조병현 `schema.py`가 `LEGACY_DEVICE_ID`로 대기하던 것이 이 확정으로 정리된다.
  > ⚠ 2026-09-14 현재 **HW 브랜치에 그 편집(4개)이 아직 반영되지 않았다**(9-9 스냅샷 기준,
  > `hw-envelope-conformance.md` §6-3). 지금 실노드를 붙이면 전량 격리된다.
- 가용성 판정(BE-T-04, "MQTT 세션 우선")은 진나영이 `simulation/backend.py` mock으로 대기 중인
  바로 그것이다 — 백엔드가 채우면 mock이 실물로 교체된다.

### 0-3. 산출물 요구 (260908)

백엔드 파트의 산출물은 **"백엔드에서 가시화 → 정보가 다 모이고 있다"를 보여주는 것**이다.

Phase 순서는 이 요구 때문에 바뀌지 않는다.

---

## 1. Tier 분류 — 무엇이 지금 되고 무엇이 막혀 있나

완료 판정 기준은 "특정 기술 사용 여부"가 아니라 **"요구사항이 정의한 동작과 허용 범위가 실제로
보장되는가"**다(진나영·김현우 공통 원칙).

### Tier A — 지금 바로 구현+검증 완결 (인프라 소프트웨어 + 가짜 발행자로 100% 검증)

| 영역 | 무엇 | 검증 방법 |
|---|---|---|
| 공통 헤더 수신 검증 (BE-C-01/02/07) ✅ Phase 1·2 | 가짜 발행자 메시지를 `message.schema.json`으로 검증·격리 + **채널 본문 6종 2단 검증**(Phase 2) | 유효/무효 fixture 쌍으로 통과·거부 확인 — `test_payload_contract` 34건 |
| MQTT→Kafka 브릿지 (BE-T-02) ✅ Phase 1 | 엣지 Mosquitto 구독 → 서버 Kafka produce | 가짜 발행자 → 브릿지 → Kafka 토픽에 도착 |
| WS 게이트웨이 (BE-T-03) ✅ Phase 1 echo까지 | Kafka 소비자 + WebSocket 서버, 구독 push | 브라우저(콘솔)에 실시간 값 도달 |
| 저장 축 (BE-S-01/05/08) ✅ Phase 2 | TimescaleDB 계측 write + MySQL 감사·레지스트리·실행 기록 | write 후 조회로 정합 확인 — 지연 도착 정렬·재소비 중복·권한 음성까지 pytest 6파일 62건(`tsdb_storage`7·`mysql_storage`10·`gap_detection`11·`storage_record`9·`registry_guards`15·`mission_event`10) |
| 가용성 판정 (BE-T-04) | MQTT LWT + 하트비트 → 세션 우선 통합 상태 | LWT/타임아웃 주입 → online/offline 판정 |
| 상관·감사 (BE-X-01/02/03) | command_id 발급, actor·시각 주입, 4단계 승격 | 명령 사슬 fixture로 상관·승격 확인 |
| 관측 파이프라인 (BE-S-02/03) | OTel Collector 수집 → Prometheus 저장/요약. 계측 대상 3층(백엔드 자기 관측 / 말단 노드 / 업무 값의 관측 표현, §8-3) | 가짜 지표 발신 → Collector → Prometheus 조회 |
| 재접속 캐시 (BE-T-06) | 채널별 캐시/비캐시, ts 원본 유지 | 재접속 시뮬 → 캐시 채널만 즉시 push |

### Tier B — 가벼운 계산/구성 필요 (실 하드웨어 불필요)

| 영역 | 무엇 | 검증 방법 |
|---|---|---|
| 미디어 중계 (BE-T-07) | 엣지 영상 WS(방식 B, native 코덱) → 서버 중계(drop-old) → 뷰어 `ws`+토큰 | 합성 H.264·JPEG 프레임 재생으로 frame_ref 관통 확인 — ✅ Phase 4 |
| 좌표 변환·트윈 반영 (BE-C-04/DT-03) | 이미지 좌표 → 전역 좌표 변환 로직 | 합성 좌표 fixture로 변환 정확도 검증 |
| 커버리지·사각지대 (DT-04) | FOV 바닥 투영, 사각 영역 산출 | 알려진 카메라 배치로 커버리지 계산 검증 |
| 위치·클래스 융합 (DT-01/02) | 불확실도 가중 융합, 베이지안 클래스 융합 | 합성 다중 검출 fixture로 융합 결과 검증 |

### Tier C — 실제로 막혀 있음 (타 파트/실 하드웨어/현장 필요)

| 영역 | 막힌 이유 |
|---|---|
| 미디어 회선 QoS·콜드스타트 실측 | 현장 회선(좁은 업링크)이 있어야 실측 — 로직은 Tier B로 검증 |
| Unity 트윈 렌더 연결 (VZ-U-02) | 가시화 파트 Unity 뷰어 필요 — 백엔드는 전역 좌표까지 산출 |
| Tailscale 직접 연결·DERP 폴백 실측 | 현장 엣지-서버 물리 배치 필요 — 구성은 Tier A/B |
| 실 센서·실 AI 통합 | 조병현 실 센서 입고·진나영 실 모델 — 가짜 발행자로 공통 규격·경로 검증까지 |
| 재난 SLA 지연 상한 실측 (BE-S-07) | 재난 고주기 실데이터 필요 — 구조는 Tier A |

**요약:** mock은 *동작과 허용 범위*를 커버하고, 커버 못 하는 것은 *현장 실측 수치와 실 하드웨어
통합*뿐이다. 하드웨어 없이도 완료 판정은 가능하며 남는 것은 실측 파라미터 확정이다.

---

## 2. Phase 순서

**우선순위 원칙:** ① 규격이 코드보다 먼저 — 이미 완료. ② 얇은 파이프라인을 끝까지 먼저
뚫고 그 위에 기능을 얹는다. ③ **다른 경로의 기반이 되는 것(관측·미디어)을 먼저, 그 위에 얹히는
것(가용성·감사·트윈)을 나중.**

> Phase 3·4(관측·미디어)를 5·6(가용성·감사)보다 앞에 둔 이유: 관측 파이프라인과 미디어 경로는
> **다른 기능이 딛고 서는 기반 경로**다(가용성의 관측 평면 신호가 관측 파이프라인에서 나오고,
> 트윈·오버레이가 미디어 경로에 의존). 가용성 판정·상관·감사는 그 위에 얹히는 것이라 나중에
> 만들어도 앞이 안 막힌다.

```
Phase 0  인프라 기동        compose 스택 올리고 헬스 확인
   ↓
Phase 1  얇은 파이프라인     가짜 발행자 → ingest → Kafka → (저장 확인) → (WS push 확인)
   ↓
Phase 2  저장 축            TSDB(계측) + MySQL(감사·레지스트리·실행 기록)
   ↓
Phase 3  관측 파이프라인     OTel Agent+Gateway → Prometheus/Loki/Tempo, 페더레이션   [기반 경로]
   ↓
Phase 4  미디어 경로         WS 중계(방식 B, 길 A·B), drop-old, frame_ref 관통, ws+토큰  [기반 경로]
   ↓
Phase 5  가용성 판정기       MQTT 세션 우선 통합(진나영 mock 대체)
   ↓
Phase 6  상관·감사·명령      command_id, actor 주입, 4단계 승격, 감사 조회
   ↓
Phase 7  디지털 트윈         DT 7건 (좌표 변환·융합·커버리지는 Tier B, Unity 연결은 Tier C)
```

### Phase 0 — 인프라 기동 ✅ 완료 (2026-09-04)

**목표:** compose 스택이 뜨고 각 구성요소가 살아있는 상태.

- 서버에 이미 도는 스택(Mosquitto·OTel Collector·Prometheus·Grafana·Loki·Tempo·MySQL)에
  **Kafka만 신규로 추가**한다. TSDB는 Phase 2로 미룬다.
- **배포 방침(결정 5, Phase 0에서 확정된 실제 방식):** 서버에 이미 도는 compose
  (`~/capstone-db/docker-compose.yml`)를 **수정**하는 것이 배포다. `git pull` 배포가 아니다.
  `infra/docker-compose.yml`은 그 서버 파일의 작업본(청사진)이며 비밀값을 담아 커밋하지 않는다
  (`.gitignore`). 컴퓨터 `infra/`에서 편집 → 사람이 서버에 복사·적용 → 결과 회수. 이미 도는
  기반은 지웠다 다시 깔지 않고, `docker compose up -d`에 서비스 이름을 명시한다.
- **DoD:** `docker compose up` 후 각 서비스 헬스 확인(Kafka 토픽 생성 가능, Mosquitto :1883
  접속, Prometheus/Grafana UI 응답, MySQL 접속). 헬스체크로 판정(pytest 아님).
- **외부 의존성:** 없음(전부 이 머신 소프트웨어).

### Phase 1 — 얇은 파이프라인 관통 ✅ 완료 (2026-09-07)

**목표:** 발행자 → 백엔드 → 저장/화면이 한 줄로 관통.

- **발행자(결정 1):** 먼저 **(C) 공통 규격(`message.schema.json`)에 맞춘 최소 발행 스크립트**를 새로
  만들어 공통 헤더 형식만 쏜다(팀원 의존 0, 내 규격이 실제로 도는가 검증). 그다음 **(A) 조병현
  `sensor_node.py`**를 붙여 실제 팀원 발행자와도 맞물리는지 확인.
- **관통 순서(결정 2):** `backend/ingest/`가 MQTT 구독 → Kafka produce → Kafka에서 갈라져
  **① 저장 확인(TSDB write 후 조회)** → **② WS push 확인(브라우저 콘솔에 값 도달)**. 저장(A)
  먼저, 화면(B) 나중.
- **DoD:** 최소 발행자와 조병현 노드 양쪽에서, 발행한 값이 Kafka를 거쳐 저장되고 브라우저
  콘솔에 실시간으로 뜬다. 공통 헤더 검증 실패 메시지는 격리·기록된다.
- **외부 의존성:** 조병현 `sensor_node.py`(가져와 실행 — 이미 확보).
- 관련: BE-C-01(공통 헤더 검증)·BE-T-01(MQTT)·BE-T-02(브릿지)·BE-T-03(WS 게이트웨이).

### Phase 2 — 저장 축 ✅ **완료 (2026-09-10)**

**결과:** pytest **103건 전건 통과**(서버, 음성 대조 5건 포함). **완료 판정 35개 전부 충족.**
보고: [`../../reports/2026-09-10_2200_phase2_저장축.md`](../../reports/2026-09-10_2200_phase2_저장축.md)
/ 지시서: [`tasks/작업지시_phase2_저장축.md`](tasks/작업지시_phase2_저장축.md)
/ 회신·문의: [`hw-envelope-conformance.md`](hw-envelope-conformance.md) §6 · [`vz-mission-record-inquiry.md`](vz-mission-record-inquiry.md)

**확정된 것 — 다음 Phase가 딛고 서는 지점:**

- **TSDB 제품 = TimescaleDB**(PG 16.15 + timescaledb 2.30.0 Community, `127.0.0.1:7859`, digest 고정)
- **시간축 = 발행 `timestamp`.** 지연 도착이 원래 측정 시각 자리에 꽂힌다(실측 `lag_s=420.527`)
- **유일 키 = 스트림 좌표**(`ts, stream_topic, stream_partition, stream_offset`). 재소비 중복을
  도착 계층에서 흡수한다(실측 `346 → 346`)
- **검출은 저장이 아니라 조회에서** — `docs/be/queries/gap-detection.sql`, 판정 4갈래
- **공통 헤더 규격 v1.1** — 선택 필드 `session_id` 추가(MINOR). **`"1.0"`도 계속 통과**
- **채널 본문 규격 6종 + 느슨한 2단 검증** — 필수 누락은 격리, **모르는 필드는 통과**
- **레지스트리 2축**(선언·관측) + 가드 3개 · **감사·실행 기록 append-only를 DB 권한이 강제**
- **MySQL 드라이버 = PyMySQL**, TSDB 드라이버 = `psycopg[binary]`

> 아래는 **착수 전 계획 원문**이다. 이월 항목마다 처리 결과를 ✅로 달았다.

**목표:** 성격별 저장 모델이 실제로 갈라져 쌓인다. ✅

- `backend/storage/`: 계측(센서·로봇 상태 추이)은 **TSDB**, 감사(명령 이력)·레지스트리(장치·구역·
  식별자)는 **MySQL**(테이블 분리). 타임스탬프 기준 병합·정렬, 지연 도착 데이터 정합.
- MongoDB는 두지 않는다(현재 채택 없음). **RBAC는 채택하되 저장 축이 아니라 조회·명령
  경로의 강제 축이라 Phase 6**에서 인증과 함께 만든다(BE-Q-04). 트윈·명령진행·가용성은
  저장하지 않고 WS push.
- **Phase 0 이월:** ✅ MySQL 컨테이너는 가동 중이나 MK2 전용 DB·계정은 없다(Phase 0 범위 밖으로
  미룸). 여기서 MK2 감사·레지스트리용 DB·계정을 만든다. 기존 테스트 DB(`robot_capstone`)에
  얹지 않는다. → `mk2` DB · `'mk2_app'@'172.18.%'` · 테이블 8개, 테이블 단위 차등 권한.
- **Phase 1 이월 (여기서 처리):**
  - ✅ **`store(...)` 뒤 구현 교체.** `backend/storage/writer.py`의 `TelemetryWriter.write()`가 지금
    JSONL placeholder다. **이 몸통만 TSDB writer로 갈아끼우고 ingest·소비자·인터페이스는 건드리지
    않는다**(그러라고 나눠 둔 지점이다). 소비자는 `backend/storage/consumer.py`(그룹 `mk2-storage`).
    → `tsdb_writer.py` 신설. `consumer.py`·`bridge.py` 한 줄도 안 바뀜.
  - ✅ **두 시각의 정합.** 기록에 공통 헤더 `timestamp`(발행 시각)와 `received_at`(서버 수신 시각)이 이미
    분리 보존된다. Phase 1 실측에서 **7분 늦게 도착한 메시지**가 원래 시각을 유지하는 것을 확인했다
    — TSDB 적재 시 어느 시각을 기준으로 정렬할지, 지연 도착(HW spool 재전송, `replayed:true`)을
    어떻게 정합할지 여기서 확정한다. → **시간축 = `timestamp`**, `ingest_at` 신설(Kafka 헤더),
    `lag_s`·`clock_skew`·`replayed` 보관. ⚠ `received_at`은 "서버 수신"이 아니라 **"소비 시각"**이었다.
  - ✅ **`sequence_id` 의미 확정.** 실측 결과 HW의 순번은 **채널별 독립**이다(같은 시각에
    heartbeat=12 / state=1, `status`·LWT는 순번 없음). 유실·역전 검출을 채널별로 볼지 소스별로
    합칠지, 재기동 시 리셋을 어떻게 다룰지 정하고 **HW에 회신**한다(`BACKEND_AGENDA §1.3`,
    [`hw-envelope-conformance.md`](hw-envelope-conformance.md) §1-3에서 "Phase 2에서 확정"으로 답해 둠).
    → 단위 `(source_id, channel, session_id)`, 경계는 `session_id`(없으면 `birth` 폴백). 회신 §6-1·§6-2.
  - ✅ **채널 본문(payload) 스키마.** Phase 1은 공통 헤더만 검증한다. 계측을 실제로 저장하려면
    채널별 본문 스키마가 필요하다 — `contracts/common/`에 추가하고 ingest 검증을 2단(공통 헤더→
    본문)으로 넓힌다. → `contracts/common/payload/` 6종, 느슨한 2단(모르는 필드 통과·필수 누락 격리).
  - ✅ **채널 본문의 누락값 표현.** 본문 규격을 만들 때, 값이 없는 항목을 어떻게 표현할지 함께
    확정한다 — **명시적 `null`이 기본**이고, 부재 사유 구분이 필요한 항목만 `unsupported`(이
    배포에 생산자 없음) / `unavailable`(있는데 지금 값 없음) 상태를 함께 준다(규칙은
    [`../../contracts/common/README.md`](../../contracts/common/README.md) "값이 없을 때의 표현").
    **어느 항목이 어느 형태인지 목록을 정하고 생산자 파트(HW)에 확정**한다. 근거는 260908 지도
    방향 — 생산자 구성이 바뀌어도 소비자(트윈·로봇 제어)가 안 흔들려야 한다.
    → 구분 필요 항목은 **`state` 계측값 + `status.registration` 둘**로 확정, 나머지 `null`. 회신 §6-8.
- **DoD:** ✅ 계측이 TSDB에 시각 순으로, 감사·레지스트리가 MySQL에 정합성 있게 쌓이고 조회로
  확인된다. 재전송(지연 도착) 데이터가 원래 측정 시각으로 정렬된다.
  채널 본문 규격에 누락값 표현 규칙이 반영되고, 값이 없는 항목이 키를 유지한 채 내려간다.
- **외부 의존성:** 없음.
- ✅ **임무 실행 기록 축(BE-S-08).** 감사·레지스트리와 같은 MySQL의 **별도 테이블**로 append-only
  사건 열을 둔다(§6-2). 이번 Phase에서는 **테이블 골격과 append 경로까지**만 만들고, 구체 필드·
  실패 단계 어휘·보존 기간은 소비자(가시화 되감기 VZ-D-02·VZ-D-04) 요구가 확정된 뒤 합의해 채운다.
  되감기 질의는 소비자가 붙는 시점에 구현한다. → `mission_event` + `append_mission_event()` 멱등.
  문의 발송 대기: `vz-mission-record-inquiry.md`.
- 관련: BE-S-01(TSDB)·BE-S-05(감사 MySQL)·BE-S-08(실행 기록)·BE-C-02(식별자)·BE-Q-03(레지스트리).
- **Phase 2가 남긴 미결 (검수 후 결정):** `registry_identity_history`의 `UPDATE` 권한. 지시서
  권한 표는 관측 축 셋을 한 묶음(`SELECT, INSERT, UPDATE`)으로 적었지만, 같은 지시서가 이
  테이블을 "관측(**append**)"으로 정의한다. 회수는 한 줄이고 즉시 적용된다 —
  `REVOKE UPDATE ON mk2.registry_identity_history FROM 'mk2_app'@'172.18.%';`
- **🆕 이월 — Phase가 아니라 「발동 조건 충족 시」:** **TSDB 보존 기간·압축·재난 구간
  아카이브(BE-S-04).** 이번에 설정하지 않았다 — BE-S-04가 별도 요구사항이고 발동 조건이 아직
  아니다([`00-architecture.md`](00-architecture.md) §8-5). 다만 `telemetry`를 **하이퍼테이블로
  만들어 두어 나중에 정책만 붙이면 되게** 했다. ⚠ **Kafka retention과 헷갈리지 않는다** —
  재난 데이터 장기 보존은 **TSDB 보존 사안**이지 Kafka retention이 아니다(원칙 11).

### Phase 3 — 관측 파이프라인 완성 ✅ **완료 (2026-09-16)** [기반 경로]

**결과:** pytest **184건 전건 통과**(서버, 기준선 104 + 신규 80, skip 0; 음성 대조 7건 전부 실제 거부·유지 확인).
**완료 판정 48개 전부 충족.** 보고: [`../../reports/2026-09-16_1900_phase3_관측파이프라인.md`](../../reports/2026-09-16_1900_phase3_관측파이프라인.md)
/ 지시서: [`tasks/작업지시_phase3_관측파이프라인.md`](tasks/작업지시_phase3_관측파이프라인.md)
/ 회신·통지: [`hw-envelope-conformance.md`](hw-envelope-conformance.md) **§7**(traceparent) · [`vz-observability-namespace.md`](vz-observability-namespace.md)(이름 공간)

**확정된 것 — 다음 Phase가 딛고 서는 지점:**

- **상주 3개 = systemd 유닛**(`infra/systemd/mk2-{ingest,storage-consumer,ws-echo}.service`, enabled, `EnvironmentFile=.env`).
  소비자 둘은 SIGTERM에 그룹을 깨끗이 떠난다(없으면 재기동 후 45초 파티션 미할당 — 실측 78초).
- **Collector = Gateway.** 파이프라인 3종(metric→Prometheus 8889 · trace→`tempo:4317` · log→`loki:3100/otlp`) + `batch`.
  **호스트 포트 4316 무변경.** 이미지 digest 고정(v0.150.1). 컴포넌트 유무는 `components`가 아니라 **`validate`로**.
- **Loki v13/tsdb + 보존 14d**(3줄 함께) · **Tempo 168h** · **Prometheus `otel_collector` 잡 5s**(global 1s·보존 15d 무변경).
- **관측 어댑터 `backend/observability.py`** — `opentelemetry`를 import하는 유일한 파일. 인터페이스 `setup`·`count`·
  `updown`·`gauge`·`observe`·`log_handler`·`shutdown`. no-op 규율 · **금지 라벨 `ValueError`** · A층에 `source_id` 금지.
- **이름 공간 `hw.`/`be.`/`vz.`(권고)**, `service.name`은 컴포넌트별(`be-ingest`·`be-storage`·`be-gateway`). Prometheus에서는
  `exported_job`으로 밀려나므로 **컴포넌트 구분은 `component` 라벨**.
- **A층 9종**(`component`·`channel`·`outcome`·`stage`) — `be.pipeline.lag`가 BE-S-07의 측정 수단(값의 출처 `telemetry.lag_s`,
  **음수는 절대값 + `outcome=clock_skew`** — OTel 히스토그램이 음수를 받지 않는다, 사용자 결정 안 A).
- **C층 12종**(`source_id`·`zone_id`·`entity_type`·`channel`) — 대상은 규격 `$comment`에서 읽는다(`contracts.observation_hints()`,
  27곳 → gauge 9·counter 3·log/event 10 = 22). 파생 지점은 **저장 소비자**, 저장 성공과 무관, 예외 삼킴.
  **counter 힌트 3개는 gauge 계기**(절대 누적값). `null`·`{value:null}`·부재는 시계열을 만들지 않는다.
- **집약 계층 경계 표기(BE-S-06) = `agg_layer="edge"`**(엣지 external_labels, 중앙 `honor_labels` 보존). **부재 = 중앙 원본.**
- **로그 경로 = OTel Logs SDK → Collector → Loki**(journald 병존). 로그 SDK 경로는 `opentelemetry.sdk._logs`(밑줄, 1.44.0).
- **Tailscale이 서버에 설치됐다**(1.102.4, 팀 공용 계정). Phase 4가 Kafka 노출에 그대로 쓴다.
- **counter는 재기동마다 0** — 조회는 `rate()`/`increase()`. C층 gauge는 **값이 흐를 때만 존재**(5분 갱신 없으면 사라진다).

> 아래는 **착수 전 계획 원문**이다. 이월 항목마다 처리 결과를 ✅로 달았다.

**목표:** 시스템 자기 관측이 업무 데이터와 분리된 평면으로 흐른다. ✅

**계측 대상은 세 층이다**([`00-architecture.md`](00-architecture.md) §8-3):

- **(A) 백엔드 자기 관측** — ingest·저장 소비자·WS 게이트웨이의 처리 건수·거부 건수·구간
  지연·produce 실패. Phase 1에서 손으로 세던 값들이 여기 해당한다.
- **(B) 말단 노드 관측** — 노드 CPU·메모리·전송 성공/실패·지연(조병현 HW-C-05).
- **(C) 업무 값의 관측 표현** — 수위·배터리 등. **어떤 항목을 낼지는 Phase 2에서 확정된 채널
  본문 규격을 보고 여기서 고른다.** 파생 지점은 값을 **받은 쪽**이며 말단이 두 번 보내지
  않는다. 원본은 여전히 TSDB이고 관측 표현은 파생이다.

라벨은 값의 종류가 한정된 것만 쓴다 — **층에 따라 다르다**: A층(백엔드 자기 관측)은 `component`·`channel`·
`outcome`·`stage`이고 `source_id`를 넣지 않는다(장치 수만큼 곱해진다), C층(업무 값)은 `source_id`·`zone_id`·
`entity_type`·`channel`. 어느 층에도 넣지 않는 것 **전수**: `session_id`·`internal_seq`·`sequence_id`·시각
(`timestamp`·`ts`·`capture_timestamp`)·프레임 식별자(`frame_id`). ✅ 어댑터가 `ValueError`로 막는다.

- ✅ OTel Collector(Agent) 수집 → 가공 → 백엔드 Collector(Gateway) → metric은 Prometheus,
  log는 Loki, trace는 Tempo. 엣지 Prometheus raw 보관 + 페더레이션 요약 pull. → 서버 Collector 파이프라인 3종 +
  임시 엣지(컴퓨터, Tailscale)의 Agent·Prometheus로 **Agent→Gateway 사슬과 페더레이션을 실증**했다(검증 뒤 되돌림).
- ✅ Grafana로 확인. metric은 요약 가능(분산), log·trace는 원본 전달(요약하면 의미 깨짐). → 조회는 API로 판정했다
  (`infra/README.md` §4 「흐른다」 블록). Grafana 대시보드는 만들지 않았다(범위 밖 — 확인 수단일 뿐).
- **DoD:** ✅ 가짜 지표 발신 → Collector → Prometheus 저장·조회(`hw_*`·`system_*` 엣지 → 서버 `agg_layer="edge"`),
  페더레이션 요약이 당겨지는 것 확인(#31). 치명 오류·장치 생사 신호가 일반 metric 요약에 섞이지 않고 개별 유지
  (`match[]`에 `up`·생사 없음, #34). A층 지표 9종이 Prometheus에 나타난다(#16). C층 12종이 선정·계측되며(#23), 그
  값의 원본이 여전히 TSDB임이 문서와 구현 양쪽에서 유지된다(#26 — 같은 발행분이 `telemetry`에 `null` 그대로).
- **외부 의존성:** 없음(조병현 HW-C-05 실 지표는 나중, 지금은 가짜 발신). ✅ 그대로였다.
- **Phase 0 이월 (현재 서버 관측 스택의 실제 상태 — 기준과의 gap):**
  - ✅ 관측 3종이 Collector를 안 거친다 → **Collector가 분배한다.** `traces`→`otlp_grpc` `tempo:4317`, `logs`→
    `otlp_http` `http://loki:3100/otlp`(도커 망 — 호스트 포트를 거치지 않는다). **호스트 포트 4316은 무변경** —
    포트 재배치는 파이프라인 신설의 선행 조건이 아니었다(설계에서 검증·기각). Tempo 호스트 4317은 우회 입구로
    남아 있다(기록만, `infra/README.md` §6 ⓓ).
  - ✅ ~~**Loki에 retention이 없다. 로그를 흘리기 "전에" 걸어야 한다** — 흘린 뒤 걸면 이미 쌓인 것은 안 지워진다~~
    **⚠ 정정: 이 서술은 틀렸다.** Loki retention은 compactor가 **나이 기준으로 소급 집행**해 이미 저장된 청크도
    지운다. 따라서 순서는 **권장**이지 강제가 아니다(먼저 거는 편이 디스크상 깔끔할 뿐). 오류의 출처는
    `reports/2026-09-04_1620_phase0_인프라기동.md`였고 여기까지 전파됐다. 정확한 서술은 *"보존을 집행할 기능이
    꺼져 있었다"* — `retention_enabled: false`·`retention_period: 0s`·`delete_request_store: ""` 세 줄이 함께 꺼져
    있었고 하나만 켜면 조용히 아무 일도 안 일어난다. → 셋 다 켜고 `14d`. 그리고 v11/boltdb-shipper가 네이티브 OTLP
    수집을 지원하지 않아 데이터(7개월 전 172K, 백업 `/home/dg/loki_data.bak_before_phase3.tgz`)를 비우고 v13/tsdb로.
  - ✅ Prometheus `scrape_interval: 1s` → **global은 건드리지 않고 `otel_collector` 잡만 5s.** global을 올리면
    `rpi`·`thermal`(잡별 5s에 global timeout 1s 상속)이 `timeout > interval`로 걸려 **설정 전체가 거부**되고, 그
    대시보드는 다른 파트 것이다. "사전 고지 후 조정"은 필요 없어졌다(다른 파트 잡·global 무변경).
  - ✅ Tempo `block_retention: 24h` → 168h · Collector `batch`(5s/512) 추가.
  - 상세: `reports/2026-09-04_1620_phase0_인프라기동.md`, `infra/README.md` §5-0·§6.
- ✅ **요청 추적 문맥 전달 회신(HW `BACKEND_AGENDA` §10-3).** → [`hw-envelope-conformance.md`](hw-envelope-conformance.md)
  **§7**: 싣는다, W3C `traceparent`, protobuf 본문 필드(`Command.traceparent`), `tracestate` 없음, 실배선 Phase 6.
  스냅샷 `260909`에는 `begin(cmd)` 호출부가 없고 `extract(carrier=cmd)`가 protobuf 객체를 그대로 받아 dict 배선이
  필요하다는 것을 확인 요청으로 넣었다.
- **🆕 Phase 2 이월 (여기서 처리):**
  - ✅ **착수 전 결정 — 백엔드 3개를 어떻게 띄우나.** → **systemd unit 3개**(`User=dg`·`Restart=on-failure`·
    `StartLimitBurst=3/60s`·`EnvironmentFile=/home/dg/capstone-db/.env`·enabled). 재기동 시 retained `status`가
    다시 흘러 들어오는 것은 정상(지금 6건)이며 레지스트리 시각 가드가 대장 오염을 막는다. 재소비로 TSDB 행이
    늘지 않는다(스트림 좌표 유일 키, 479→479 실측).
  - ✅ **C층 대상은 본문 규격에서 꺼낸다.** → `contracts.observation_hints()`가 `$comment`를 `properties` 재귀로 훑어
    **27곳 → gauge 9·counter 3·log/event 10 = 22**를 얻는다(`tests/test_c_layer_extract.py`가 못 박는다). 이번엔
    gauge 9 + counter 3 = **12개**만 계측, log/event 10개는 Phase 5.
  - ✅ ~~**라벨 금지 목록에 `session_id`·`internal_seq`를 추가한다.**~~ **⚠ 정정:** 이 이월은 둘만 적었는데 규격
    파일(`contracts/common/README.md`)의 전수는 **`sequence_id`·시각·프레임 식별자**를 포함한다. 전수와 맞췄다 —
    `session_id`·`internal_seq`·`sequence_id`·`timestamp`·`ts`·`frame_id`·`capture_timestamp`(어댑터 `FORBIDDEN_LABELS`).
  - ✅ **A층이 셀 값 셋** — ① `telemetry.lag_s` → `be.pipeline.lag` 히스토그램 ② TSDB 적재 실패 →
    `be.storage.write{outcome="fail"}` ③ 레지스트리 갱신 실패 → `be.registry.observe{outcome="fail"}`.
  - ⏭ **`clock_skew` 임계 확정** → **확정하지 못했다.** `lag_s`가 채워진 행이 적고 양 끝(`-30.000`·retained 재유입
    ~434,000초)이 전부 인공물이라 분포를 정할 재료가 못 된다. 이제 `be_pipeline_lag_seconds{outcome="clock_skew"}`로
    쌓이므로 **Phase 5에서 확정**(아래 이월).
- 관련: BE-S-02(파이프라인)·BE-S-03(계층화)·BE-S-06(집약 표기)·**BE-S-07(지연 상한 — 측정 수단)**.
- **🆕 Phase 3 이월 — 어디로 갔는지:**
  - **Phase 4:** ① Collector의 **Tailscale 바인딩(compose 주석 한 줄)과 ufw 규칙을 되살린다** — 엣지 OTLP 수신단의
    **TLS·인증은 BE-T-08**(Phase 3은 터널 안 평문, ufw를 엣지 IP `/32`로 제한) ② Tailscale 계정은 **이미 팀 공용
    계정**이라 "임시 계정 → IP 변경" 이월은 소멸 — 다만 **엣지 실물의 IP로 `prometheus.yml` `edge_federate` 타깃과
    Collector 바인딩을 바꾼다** ③ Prometheus 이미지 digest 고정(컨테이너 재생성이 따라오므로 다른 작업과 묶어서)
    ④ `LoggingHandler`(SDK 1.44 deprecated) → `opentelemetry-instrumentation-logging` 핸들러로 교체(패키지 1개)
    ⑤ Kafka 원격 노출 3수정은 Phase 3에서 설치한 Tailscale을 그대로 쓴다.
  - **Phase 5:** ① **C층 log/event 10개**(`reason`·`device_status`·`alert`·`robot_mode`·`actuator_state`·`feedback_ok`·
    `control_locked`·`above_threshold`·`event`·`status`)를 **상태 전이 판정과 함께** 계측한다(결정 5-b — 그대로 내면
    로봇 1대당 초당 60줄) ② **`clock_skew` 임계 확정** — A층 `be_pipeline_lag_seconds{outcome="clock_skew"}` 분포로
    ③ `be.pipeline.lag` 상한 판정·경보(BE-S-07의 나머지).
  - **Phase 6:** **`.proto` 개정에 `Command.traceparent` 필드를 함께 넣는다** — `BACKEND_AGENDA` §3(문자열/열거형
    파라미터)와 같은 개정. HW 확인 2건(필드 번호·옛 말단 호환)은 §7-4. **안 적으면 그 시점에 따로 떠오르지 않는다.**
    백엔드 span 생산(명령 경로)도 여기.
- **문서 정합 패치 완료(2026-09-16):** `CLAUDE.md`·루트 `README.md`·`00-architecture.md`·`infra/README.md`·
  `02-media-path.md`·HW 회신 §5-1 표·보고 대상 목록(설계_규칙·템플릿). 근거 지시서 `작업지시_phase3후_문서정합패치.md`,
  기록은 Phase 3 보고서 끝 「후속 정합 패치」.

### Phase 4 — 미디어 경로 ✅ **완료 (2026-09-19 — 단계 0~10 전부. 서버 pytest 272 passed + relay 12 skip(8766 닫힘이 정상))** [기반 경로]

**목표:** 영상이 엣지→서버→뷰어로 관통하고 frame_ref가 정합된다.

- **한 일(단계 0~8, 지시서 [`tasks/작업지시_phase4_미디어경로.md`](tasks/작업지시_phase4_미디어경로.md) v4·작업로그
  [`../../reports/2026-09-18_2100_phase4_작업로그.md`](../../reports/2026-09-18_2100_phase4_작업로그.md)):**
  엣지→서버(`/ingest` 8766)→뷰어(`/media` 8765) **방식 B 중계**(`[4B 헤더길이][JSON 헤더][native AU]`, 서버는 헤더의
  필수·타입만 검증하고 페이로드를 열지 않는다) · **GOP 인지 drop-old**(`T_drop` = 150ms × 배출률, `T_hard`, `WAIT_IDR`/
  `FLOWING`, 첫 전송·재개는 keyframe) · **영상/상태 채널 분리**(같은 포트 경로 분리 + `write_limit`·`SO_SNDBUF`) · **터널
  위 `ws` + URL 쿼리 토큰**(loopback이 아니면 토큰 필수, 4401) · **바인딩 두 주소**(`127.0.0.1,<서버 tailscale IP>`) ·
  규격 `media-header.schema.json`·`detections.schema.json`(초안)·`$ref` 레지스트리(결정 12) · 라벨 금지 8종 추가 ·
  `LoggingHandler` 교체 · Prometheus digest 고정 · Kafka **EDGE 리스너**(9095)·Collector 4316 Tailscale 바인딩·
  `edge_federate` 잡을 되살려 **컴퓨터 임시 엣지로 2계층 실측 1회 뒤 되돌림**(단계 8 — 8765만 남김).
  **서버 pytest 256 → 되돌림 뒤 244 passed + relay 12 skip(8766 닫힘이 정상).** 실측: 직접 경로 2ms/22ms, 브라우저 2954장
  gaps 0·WebCodecs 표시, 링크 500kbit로 조여 드롭 207·GOP 절단 20·불연속 전부 IDR 재개, 지연 p90 2.34s
  (= `(T_drop + write_limit + sndbuf)/링크율`). 상세 근거·정정 자리는 [`02-media-path.md`](02-media-path.md).
- **DoD(결정 1·5로 갱신):** 합성 **native 코덱**(H.264 fixture·JPEG) 프레임 재생 → 엣지 WS → 서버 중계 → 뷰어에서
  디코드·표시, frame_ref가 **바이트 그대로** 관통해 탐지 박스가 정확한 프레임에 겹쳐진다. 서버→뷰어는 **터널 위 `ws`+토큰**
  (tailnet 밖 뷰어용 WSS는 Phase 6). ✅ 관통·정합·drop-old·토큰은 pytest 59건(+라벨 13)과 실측으로 닫혔고, **탐지 오버레이의
  실제 겹침은 VZ 뷰어가 붙어야** 한다(형식 초안은 단계 9 통지).
- **외부 의존성:** 실 카메라·현장 회선·실물 엣지 노트북은 Tier C(실측). 여기선 합성 프레임 + 컴퓨터 임시 엣지.
- **이월 처리 결과:**
  - **Phase 3 이월 5건 → ✅ 전부.** ① 4316 Tailscale 바인딩 + ufw `/32` 되살려 실측 뒤 다시 주석(인증 없음 — OTLP 토큰 확장
    조사는 ⏭ Phase 6) ② `edge_federate` 되살려 `up`·15s·음성 대조 뒤 다시 주석 ③ Prometheus `sha256:b5a5ad00…` 고정
    ④ `opentelemetry.instrumentation.logging.handler.LoggingHandler`(최상위 export 아님) ⑤ Tailscale 설치는 완료 사실.
  - **Phase 1 이월 3건 → ✅ 전부.** **원격 Kafka 노출은 「3수정」이 아니라 EDGE 리스너 하나 추가로 풀었다**(결정 6 —
    PLAINTEXT `localhost:9092`는 한 줄도 안 바꿔 호스트 백엔드 3개 무영향). 컴퓨터에서 produce/consume 왕복 + TSDB 적재
    확인 뒤 주석으로 되돌림(실 엣지 시 주소만 교체). **frame_ref 규격 정합 = ISO 유지**(결정 2 — 우리 문서 쪽이 어긋나
    있었다. epoch ms 서술은 `02-media-path.md` §1-6-2·이 문서·Phase 1 지시서에서 정정, v8 docx §6-9는 사용자 몫; HW
    회신은 단계 9). **WS 게이트웨이 외부 노출 = 두 주소 바인딩 + 토큰**(결정 5).
    > ⚠ **재정정(2026-09-19).** 2026-09-10 정정 박스(*"실측이 반증했다 — ufw를 열자 수집이 정상화됐다"*)는 **한 경로만
    > 본 것이었다.** 09-18 iptables 실측: 트래픽 경로가 둘이다 — **컨테이너發 → 호스트 주소**는 DNAT를 안 타고 `INPUT`으로
    > 가므로 ufw가 적용되고(9100 사례가 이것), **외부 기기發 → 도커 발행 포트**는 `DOCKER-FORWARD`가 ufw보다 먼저 ACCEPT
    > 하므로 ufw가 통제가 아니다. **도커 발행 포트의 실질 통제는 compose 바인딩 주소**이고, 호스트 파이썬 포트(8765·8766·
    > 8767)는 ufw가 진짜 통제다. ufw 규칙은 도커 포트에도 적되 「통제」로 세지 않는다. tailnet 안 다른 기기까지 막는
    > `DOCKER-USER`는 미룸. `infra/README.md` §5의 재정정과 같은 내용이다.
  - **Phase 2 이월(VZ-C-07) → ✅ 코드 변경 0.** 주소·토큰은 화면에서 입력(`ws://<서버 tailscale IP>:8765/media?source_id=…&token=…`).
    `/state`의 VZ 와이어 계약 정합은 **Phase 5/7**(그때까지 VZ는 목 게이트웨이 8790).
  - **2026-09-17 대조 이월 → 역할 경계·#15 결정 9·회신 범위·VZ 통지·결정 2/3/5/7은 지시서 §2-3·§2-5로 확정돼 그대로 이행.**
    결정 7은 **A**(4318 Tailscale IP 바인딩 + CORS + ufw `/32`, 브라우저는 tailnet 안)이며 **구현은 VZ 주소·origin 회신 뒤**
    — 이번에 4318은 손대지 않았다. 라벨 6종 확장은 8종으로(`frame_ref`·`correlation_id` 추가), 「발화 원문」은 키 이름
    회신 뒤.
- **단계 9 ✅(2026-09-19):** HW 회신 [`hw-envelope-conformance.md`](hw-envelope-conformance.md) §8 · VZ 통지
  [`vz-media-interface.md`](vz-media-interface.md)(관측 회신 답 §9 포함) · AI 통지 [`ai-detections-interface.md`](ai-detections-interface.md)
  — 셋 다 §8 문서 갱신 커밋 **뒤**에(DoD 9-6). **단계 10 ✅(2026-09-19, 4b 촬영본 저장소 — HW #15):** `backend/gateway/capture.py`
  (별도 유닛 `mk2-capture`, 8767 `<서버 tailscale IP>`, ufw pi7 `/32`) · `infra/sql/mk2_media_capture.sql`(DDL + GRANT
  `SELECT, INSERT, UPDATE`, DELETE 없음 — root 1회 적용, 서버 `mk2_sql/mk2_mysql_schema.sql`도 09-14 정정판으로 교체) ·
  합성 업로더 `tests/capture_uploader.py` · `tests/test_capture_upload.py` 28건(10-1~10-3 · C1~C5). PUT 두 번(매니페스트
  먼저)·최종 경로는 매니페스트·`INSERT`→rename→`COMMIT`·멱등·`kind` 보존·`started_at` NULL 규칙·`frame_ref_base` 없음·
  보존 dry-run. 서버 실측 5회 전부 기대대로. 4b는 앞 단계와 코드를 공유하지 않는다. **최종 보고:**
  [`../../reports/2026-09-19_0600_phase4_미디어경로.md`](../../reports/2026-09-19_0600_phase4_미디어경로.md).
- **🆕 이 Phase가 미래 Phase로 보내는 것(규율 8 — 아래 각 Phase 항목에도 적었다):**
  - **Phase 5:** `video_meta` 상태 채널 발행(실체·시점은 정했다) · `/state` VZ 와이어 계약 정합(`hello`·`subscribed`·구독 즉시
    스냅샷·`unsubscribe`) · 레지스트리(BE-Q-03)로 entity↔`source_id` 목록(그때까지 화면에서 직접 설정) · `MK2_MEDIA_SNDBUF`
    하향 여부(지연 vs DERP 처리량 — 결정 항목).
  - **Phase 6:** 서버→엣지 온디맨드 개폐 배선(길 B의 절약 — HW `stream_start`/`stream_stop` 우회 전제) · `.proto` 개정(문자열
    파라미터·`traceparent`와 같은 커밋) · **Kafka EDGE SASL** · **OTLP 4316 토큰(확장 조사)** · **4318 브라우저 입구**(VZ 회신 뒤,
    결정 7 A) · **tailnet 밖 뷰어용 WSS** · `DOCKER-USER`로 tailnet 안 좁히기 · 탐지 채널·토픽(AI→Kafka→`/state`) · 촬영본
    세 곳 중복 정리(pi·VZ·4b).
  - **Phase 7:** 소스별 촬영 시각 보정(imageai 프레임의 촬영 시각 유무 — HW 답 뒤) · 트윈 형식(#14) · `object-reference.schema.json`을
    `$ref` 레지스트리 검증 경로에 편입 · 다중 소스 병합 규칙(#14) 뒤 `media_capture` 파생.
- 관련: BE-T-07(미디어 중계 — 부분)·BE-C-03(frame_ref·미디어 헤더 — 부분)·BE-T-08(오버레이 터널 — 부분)·BE-T-03(경로
  분리·토큰)·BE-T-02(EDGE 실증)·**VZ-C-07(WS 주소 설정)**·**BE-S-09(#15 촬영본 저장소 — 부분, 4b 구현)**.

### Phase 5 — 가용성 판정기

**목표:** 두 평면 신호를 하나의 권위 있는 가용성으로 통합.

- `backend/availability/`: 업무 평면(MQTT LWT·하트비트) + 관측 평면(Prometheus up/absent)
  이중 감지 → 단일 통합, **충돌 시 업무 평면 우선**(MQTT 세션 online이면 가용, offline이면
  up=1이어도 불가용). 상태 3층(자기보고·서버판정·오케스트레이터) 원본 유지. 제어 잠금 산출.
- 이것이 진나영 `simulation/backend.py` mock을 실물로 교체하는 지점.
- **DoD:** LWT/하트비트 타임아웃/지표 침묵을 주입해 online/offline이 세션 우선 규칙대로 판정되고,
  두 평면 불일치 케이스(세션 online·지표 결손 / 세션 offline·지표 존재)가 구분된다.
- **외부 의존성:** Phase 3 관측 평면 신호(그래서 Phase 3 이후).
- **Phase 1 이월 (여기서 처리):**
  - **엣지 1차 판정 ↔ 백엔드 최종 판정의 관계.** HW 브랜치에 `pi/edge/monitor.py`·
    `edge/availability.py`가 있어 **엣지가 이미 하트비트·LWT·상태 이벤트로 up/offline을 판정**하고
    Prometheus 텍스트로 노출한다(`BACKEND_AGENDA §10-2`의 임의 진행분). BE-T-04는 "백엔드 단일
    지점 최종 판정, 업무 평면 우선"이므로 **둘의 관계를 여기서 정리**한다 — 엣지 판정을 신호로
    받아들이되 최종 판정은 백엔드가 한다는 구분을 명시하고 HW에 회신한다.
  - **`device_status` 발행 주체(`BACKEND_AGENDA §5`).** HW가 ok/degraded/fault를 자기보고 중이다
    (판정 기준: 버퍼 적재·폐기·단절·센서 3회 실패 등). 이를 그대로 수용할지, 백엔드가 metric·log
    에서 파생할지 결정해 회신한다. 상태 3층(자기보고·서버판정·오케스트레이터)의 구분 문제다.
  - **Phase 1이 흘려보내기만 한 신호들.** `status`(birth/summary/**shutdown**)와 LWT(**death**),
    `heartbeat`가 이미 파이프라인을 통과해 저장·WS까지 온다. 계획 종료(`reason=graceful_shutdown`)
    와 급사(`reason=lwt`)가 payload로 구분돼 있어(VZ-U-01) 판정기의 입력이 이미 갖춰져 있다.
  - **Mosquitto `persistence` 미설정** — 브로커 재시작 시 retained `status`가 소실된다(Phase 0
    이월). 재접속 스냅샷을 retained가 아니라 백엔드 캐시(BE-T-06)로 가는 확정 결정과 함께 정리.
- **🆕 Phase 2 이월 (여기서 처리):**
  - **구역 변경 시 빈 payload가 격리 파일을 오염시킨다.** `pi/common/node.py:253`이 구역이 바뀌면
    **옛 토픽에 `""`를 retained로 발행**한다(그 구역에 유령 장치가 남지 않게 하는 **정상 동작**이다).
    그런데 ingest의 `json.loads("")`가 실패해 **격리 파일에 쌓인다.** 정상 동작인데 격리 기록이
    오염되므로, ingest가 **빈 payload를 "등록 취소 신호"로 인지**하도록 손질한다. 가용성·레지스트리
    판정과 같은 자리라 여기서 처리한다.
  - **`status`·LWT·`heartbeat`가 이미 전부 저장돼 있다.** Phase 2가 세 채널을 TSDB에 그대로
    쌓고 있고(`payload` JSONB에 원본 전체), 레지스트리 관측 축도 `status`로 채워진다. **판정기의
    입력이 조회 한 번으로 나온다** — 새 소비자를 만들 필요가 없다.
  - **`device_status` 주체 결정에 쓸 재료가 생겼다.** HW 자기보고 값이 `telemetry.device_status`
    칼럼으로 추출돼 있어 **분포를 조회로 볼 수 있다**. 수용할지 파생할지 판단을 실측으로 할 수 있다.
  - **로봇은 임무 중 하트비트를 끈다**(`robot_node.py`의 `heartbeat_enabled()`가 `not in_mission()`).
    **하트비트 침묵을 장애로 단정하면 임무 중인 로봇이 전부 장애가 된다.** 갭 검출은 이미 이것을
    반영해 하트비트 갭을 `loss_not_implied`로 분류한다 — 가용성 판정도 같은 규칙을 따라야 한다.
  - **VZ-N-02·N-03 — 재생 머리 하나가 실행 기록·계측·감사를 묶는다**(Phase 5/6 걸침). 재생 머리를
    과거로 옮기면 **지표(TSDB) 뷰 노드도 그 시점 값을 보여야 한다.** 조회 프록시(BE-Q-01)가 구간
    질의를 지원해야 하며, **인터페이스 형태를 가시화에 물어 두었다**
    ([`vz-mission-record-inquiry.md`](vz-mission-record-inquiry.md) §2-6). 저장은 이미 양쪽 다
    준비됐다 — 계측이 발행 시각 축으로 정렬돼 임의 구간을 그대로 잘라낼 수 있다.
- **🆕 Phase 3 이월 (여기서 처리):**
  - **C층 log/event 10개를 상태 전이 판정과 함께 계측한다**(Phase 3 결정 5-b). 대상은 규격 `$comment`의
    log/event 힌트 — `reason`·`device_status`·`alert`·`robot_mode`·`actuator_state`·`feedback_ok`·`control_locked`·
    `above_threshold`·`event`·`status`(`contracts.observation_hints()`로 읽는다, `backend/storage/derive.py`의
    `METRIC_KINDS`에 `log/event`를 더하는 자리가 아니라 **전이 판정기가 "바뀌었을 때만"** 내는 구조). 전부 상태
    어휘라 "언제 바뀌었나"가 의미의 전부이고, 그대로 내면 로봇 1대당 초당 60줄이 Loki로 간다.
  - **`clock_skew` 임계 확정.** Phase 3부터 `be_pipeline_lag_seconds{outcome="clock_skew"}` 히스토그램이 쌓인다 —
    그 분포로 `lag_s < 0` 무조건 플래그를 임계로 바꾼다. 인공물(가짜 발행자 `--timestamp +30`, retained 재유입)은
    빼고 본다.
  - **`be.pipeline.lag` 상한 판정·경보**(BE-S-07의 나머지) — 관측 평면 신호로 판정하는 첫 사례라 가용성 판정기와
    같은 자리에서.
  - **관측 신호는 가용성의 보조 평면이다.** 업무 평면(MQTT 세션) 우선 규칙은 그대로 — A층·B층 지표 침묵(`absent`)은
    "지표 결손 플래그"이지 불가용 판정이 아니다(원칙 7). `edge_federate`는 Phase 4에서 되살려 재실증한 뒤 **다시 주석**
    상태다 — B층은 실 엣지가 서야 온다.
- **🆕 Phase 4 이월 (여기서 처리):**
  - **`video_meta` 상태 채널 발행(BE-T-06 캐시 7종의 하나).** Phase 4가 실체(`source_id`별 `encoding`·`width`·`height`·`codec`
    + 마지막 도착 시각)와 발행 시점(`/ingest` 첫 프레임·해상도 변경 = 스트림 재개 사건)을 정했고 **발행은 하지 않았다**
    (`02-media-path.md` §1-5-4·`00-architecture.md` §7-4). 카메라 영상 가용성은 장치 가용성과 **별개 신호** — 판정기가
    섞지 않는다.
  - **`/state`의 VZ 와이어 계약 정합.** 지금 `/state`는 Phase 1 echo 그대로라 VZ `WsTransport`가 붙으면 전량 버린다(`type`
    필드 없음). `hello`·`subscribed`·**구독 즉시 캐시 1회 푸시**(화면이 실제로 비는 것은 이것뿐)·`unsubscribe`. 재접속
    캐시(BE-T-06)와 같은 자리. `stale_threshold_ms`는 state payload의 `layers.stale_threshold_ms`가 실제 표시를 하므로 그쪽을
    먼저 맞춘다.
  - **레지스트리(BE-Q-03)로 entity ↔ `source_id`(카메라) 목록.** `/media`는 카메라 단위(`go1-001_front`)이고 `target_entity_id`는
    개체 키(`go1-001`)다 — 같은 식별 체계, 다른 값. 목록이 나오기 전까지 VZ는 화면에서 `source_id`를 직접 설정한다.
  - **`MK2_MEDIA_SNDBUF` 하향 여부(결정 항목).** 64KB(실효 128KB)가 느린 링크에서 지연의 대부분(≈2.06s @500kbit)을 차지한다.
    16KB로 내리면 같은 링크에서 ≈0.7s이지만 DERP(72ms) 경유 처리량 상한이 444KB/s로 내려간다. 현장 회선 실측 뒤 정한다.
- 관련: BE-T-04(가용성)·BE-X-07(제어 잠금)·**BE-Q-01(구간 질의)**·BE-T-06(`video_meta`·재접속 캐시)·BE-T-03(`/state` 계약).

### Phase 6 — 상관·감사·명령

**목표:** 명령 사슬이 한 키로 이어지고 책임이 기록된다.

- command_id 백엔드 발급(BE-X-01), actor(토큰)·시각(서버) 주입 감사 작성 → MySQL 직행,
  명령 결과 4단계 승격(ACK→수행중→물리변화→완료/실패), 감사 조회 API. 계획 승인 중계,
  AI 실패 이벤트 중계.
- **DoD:** 명령 사슬 fixture로 가시화 요청→발급→디바이스→결과→감사가 한 command_id로 추적되고,
  되돌리기 어려운 명령이 ACK가 아니라 물리 결과로 확정 표시된다. 감사 조회로 "누가 언제 무엇을"
  질의된다.
- **외부 의존성:** 진나영 AI-O-02(AI 실패)·AI-R-02(위험도·근거·권고 산정) 수신 연동은 공통 규격 기준
  (가짜 이벤트로 검증). 명령 의미 규격은 AI-C-20을 근거로 맞춘다.
- **Phase 1 이월 (여기서 처리):**
  - **명령 경로는 텔레메트리와 프로토콜이 다르다.** HW 기준은 `common/physical_command.py`이며
    **구 JSON 4단계 엔진은 폐기**됐다. 명령은 `terminal/<device_id>/downlink|uplink` 위에서
    **protobuf**(`PhysicalCommandEnvelope`)로 흐르므로 **JSON 공통 헤더 규격이 이를 지배하지 않는다.**
    Phase 1 ingest는 `terminal/#`을 구독하지 않아(구독 패턴이 4칸이라 3칸 토픽은 배달되지 않음)
    자연히 격리돼 있다. 여기서 `mk2.command.*` 토픽과 protobuf 규격 정합을 설계한다.
  - **문자열/열거형 파라미터 지원(`BACKEND_AGENDA §3`).** `sensor_node`의 `set_mode(mode="normal")`·
    `levee(position="open")`는 문자열 파라미터인데 protobuf 명령은 `map<string,double>`이라
    **현재 호출할 수 없다.** 명령 스키마에 문자열/열거형 파라미터를 추가해야 한다.
  - **4단계 stage 값 확인(`BACKEND_AGENDA §7`).** HW가 `accepted|rejected` / `executing|
    state_changed|completed|failed` + `physical:true|false`를 발행한다. `physical:false`(설정 명령)
    는 물리 변화 단계가 없으므로 소비자가 `state_changed`를 무한정 기다리지 않게 승격 매핑을
    확정하고 회신한다.
- **인증·인가(BE-Q-04).** 감사가 "actor는 토큰에서 주입"을 전제하므로 **인증이 감사의 선행조건**이다.
  로그인·토큰 발급/검증과 역할·범위 조회 API를 여기서 만든다. 역할 강제는 캡스톤 포함 적용하고,
  구역 범위 강제는 국가 인프라 축이되 가능하면 캡스톤에서도 적용한다. 화면 차단은 사용자 편의이며
  실제 허용 여부는 백엔드가 검증한다(김현우 VZ-C-01·VZ-C-04가 백엔드 강제를 전제).
- **명령 수락/거부·취소·멱등(BE-X-01·X-03 확장).** 진행 4단계와 별개로 **수락/거부**를 표현하고,
  **취소 요청 수락과 실제 취소 완료를 구분**하며 **긴급정지를 일반 취소와 구분**한다. 동일
  command_id 재전달 시 물리 실행을 반복하지 않는다. 가시화가 보내는 **클라이언트 요청 식별자와
  유효기한**을 받아 백엔드 발급 command_id와 매핑하고 중복 발행을 막는다(김현우 VZ-O-01).
  상태 어휘는 진나영 AI-C-20을 근거로 공통 규격에 고정한다.
- **임무 하달·위험 대응 제어(BE-A-03·BE-A-04).** §6-7의 역할 구분대로 구현한다. 임무 분해는
  가시화가 하므로 백엔드는 투입 판단 결과의 하달과 위험 판정의 제어 번역만 담당한다.
- **🆕 Phase 2 이월 (여기서 처리):**
  - **감사 테이블은 이미 서 있다 — 남은 것은 쓰기 경로다.** `mk2.audit_log`(17칼럼 + 인덱스 4)가
    `infra/sql/mk2_mysql_schema.sql`에 있고 **UPDATE·DELETE가 권한으로 막혀 있다**(음성 대조 확인).
    여기서 만들 것은 ① **명령이 실제로 흘러 들어가는 배선** ② **actor를 토큰에서 주입**
    ③ **시각을 서버 시각으로 주입**(위조 불가)이다. **인증(BE-Q-04)이 선행조건**이라 같은 Phase다.
  - **🆕 모델 적용 승인 기록 — BE-* 요구사항 신설 여부를 결정한다.** AI-L-06/07/08·VZ-U-08이
    요구하는데 **백엔드 47건에 대응 행이 없다**(추적표에 gap으로 기록). Phase 2가 감사 테이블의
    대상을 `subject_kind`(`command`|`plan`|`model`)로 **일반화해 자리만 확보**해 두었으므로
    스키마 변경 없이 받을 수 있다. **요구사항을 신설할지, gap으로 둘지**를 가시화·AI 회신 후
    결정한다([`vz-mission-record-inquiry.md`](vz-mission-record-inquiry.md) §2-8).
  - **MySQL 노출 정리 — `0.0.0.0:7858` + `root@%`.** Phase 2 단계 0에서 실측됐으나 **다른 파트가
    쓰는 컨테이너라 손대지 않았다**(기록만). 인증·인가를 세우는 이 Phase에서 함께 정리한다.
    참고로 MK2 앱 계정은 이미 `'mk2_app'@'172.18.%'`로 **호스트 제한 + 테이블 단위 차등**이다.
  - **실행 기록의 실제 쓰기 배선(BE-S-08).** 생산자는 가시화·엣지이고, 지금 `append_mission_event()`를
    부르는 것은 테스트뿐이다. **가시화 회신(§9-2)이 오면 `detail` JSON에서 칼럼으로 승격**하는
    작업이 여기 붙는다 — 전환 비용은 문의서 §3에 정리해 두었다.
    > ⚠ **생산자 제약 둘을 배선 전에 전달해야 한다.** ① `mission_event`의 **`actor_kind`가
    > `NOT NULL`** 이다(2026-09-14 정정, VZ-D-02 *"산출 주체를 반드시 포함"*) — 안 보내면 INSERT가
    > 실패하고, `build_params()`는 빈 문자열도 `ValueError`로 막는다. ② **`occurred_at`은 UTC**다
    > (서버가 `system_tz=KST`라 로컬 시각을 그대로 보내면 9시간 어긋난다). 둘 다 가시화 문의
    > §1 표·§1-2에 적어 두었다.
  - **`actor_kind` 어휘를 `audit_log`와 통일한다.** `mission_event`는 `ai|backend|human`,
    `audit_log`는 `user|system|ai 등`으로 **어휘가 갈려 있다**(추적표 BE-S-05 gap ④). 감사 쓰기를
    세우는 이 Phase에서 하나로 맞춘다 — 안 맞추면 되감기 화면에서 같은 주체가 다르게 표기된다.
- **🆕 Phase 3 이월 (여기서 처리):**
  - **`.proto` 개정에 `Command.traceparent` 필드를 함께 넣는다.** 위 「문자열/열거형 파라미터」(`BACKEND_AGENDA` §3)와
    **같은 개정**이다 — 두 번 고치면 말단 재배포가 두 번이다. 백엔드가 `command_id`(BE-X-01)와 함께 W3C `traceparent`를
    만들어 싣는다(`tracestate` 없음). HW 확인 2건(필드 번호를 누가 정하나·옛 말단 호환)과 정보(스냅샷 `260909`에
    `begin(cmd)` 호출부가 없고 `extract(carrier=cmd)`에 dict 배선이 필요)는 [`hw-envelope-conformance.md`](hw-envelope-conformance.md)
    §7-3·§7-4. **안 적으면 그 시점에 따로 떠오르지 않는다.**
  - **백엔드 span 생산.** Phase 3은 Collector→Tempo 경로만 가짜 span으로 확인했다. 명령 경로(요청 수신 → command_id
    발급 → 하달 → 결과)에 span을 붙이고 HW `cmd.receive`가 그 자식이 되게 한다 — 관제 클릭부터 물리 동작까지 한
    사슬(`00-architecture.md` §5-3·§6-5). 고빈도 경로(텔레메트리)에는 span을 만들지 않는다(HW와 같은 범위).
- **🆕 VZ 회신(2026-09-17, `received/2026-09-17_vz-mission-record-reply.md`) 이월 — 실행 기록 배선(BE-S-08) 때 처리:**
  - **임무 정의 저장 자리 신설.** 사건 열만으로는 되감기(VZ-D-04)·격리(VZ-D-05)가 안 선다 — 태스크 목록·마일스톤 소속·
    배정 대상·deps(선행 노드 여럿, `parent_ref` 한 칸에 안 담김)가 사건과 **별도로** 필요하다. 형태는 우리가 정한다:
    ① 임무(판)당 1행(정의 JSON + 시작·끝·결과 — VZ-D-04 이력 목록에도 쓰임) 또는 ② 첫 사건 `detail`. 파생 태스크로
    구조가 바뀌면 새 정의를 다시 넣을 수 있어야 한다(VZ-D-01).
  - `mission_event.layer`에 **`mission`** 값 추가(VARCHAR라 DDL 없음, COMMENT 갱신). DAG 밖 사건(장비 명령·임무 생성·승인·
    재시작)은 `layer=mission`·`node_ref=임무 ID`·`target_entity_id=장비`.
  - 실패 4단계 어휘 확정: `plan_failed`·`dispatch_failed`·`execution_failed`·`evaluation_failed`(자유 문자열이라 변경 없음).
    `actor_kind`는 `ai|backend|human` 그대로, 엣지·AI 서버는 `actor_id`로(`pi1`·`detect-server`). **`audit_log.actor_kind`
    통일(§2-14 발견)도 이때.**
  - `event_key` = `{mission_id}:{VZ 내부 순번}`(권고 형태 대신). `mission_id`는 판마다 새로(대본 ID + 판 시작 시각).
  - `origin_kind`: 어휘 `real|simulation|replay` 유지(VZ 표시 어휘 `physical`은 VZ가 대응). **발행 주체를 백엔드·HW가
    정해야 한다**(VZ-C-06 — VZ는 소비자). `audit_log.subject_kind`가 모델·판단 정책·환경 지식 3종을 담는 방식 결정.
  - `correlation_id`: VZ는 사람 조작을 **명령 발행 전에** 기록하므로 command_id는 **뒤따르는 사건**으로 잇는다(수정 아님).
  - 조회 API: `mission_id`로 사건 열을 `seq` 순 반환 + 임무 정의. 8종 상태 파생·구간 계산은 VZ가 한다(BE-Q-01은 (대상,
    시작, 끝) 구간 질의만).
  - VZ 질문 답: 실제 Go1 `source_id` = `go1-001`, EP = `ep-001`(HW `hw-robot*.env.example`).
- **🆕 Phase 4 이월 (여기서 처리):**
  - **서버→엣지 온디맨드 개폐 배선(길 B의 절약).** Phase 4는 길 A·B 동시 지원(결정 10)으로 홉2를 열어 두었고 뷰어 쪽 신호는
    연결 자체다(결정 4-b). 서버가 엣지에 스트림을 열고 닫으라고 보내는 명령(명령 평면 Kafka → HW)이 여기다. ⚠ **HW `stream`
    명령은 지금 호출 불가**(`Command.parameters`가 `map<string,double>`인데 `validate()`가 문자열 `action`을 요구) — Phase 4
    회신에서 `stream_start`/`stream_stop` 우회를 요청했다. 그 답 위에 배선한다.
  - **`.proto` 개정 범위가 넓다** — 문자열/열거형 파라미터(§3)·`traceparent`(Phase 3 이월)에 더해 **`Command.parameters`가
    `map<string,double>`이라 명령에 문자열을 실을 자리가 애초에 없다**(`physical_command.proto:32`). SDP 같은 세션 정보는
    `CommandStatus.detail`로 충분하니 `.proto`를 앞당기지 않는다.
  - **Kafka EDGE 리스너 SASL**(BE-Q-04와 함께 — Phase 4는 평문 + 바인딩 + ufw `/32`) · **OTLP 4316 토큰**(Collector 토큰 확장
    조사 ⏭ — 없거나 receiver 분리가 필요하면 ufw `/32`만) · **4318 브라우저 관측 입구**(결정 7 A — VZ가 tailnet 주소·CORS
    origin·exporter 종류·https 여부를 회신한 뒤 Tailscale IP 바인딩 + CORS + ufw `/32`) · **tailnet 밖 뷰어용 WSS**(결정 5 —
    외부 관제·시연장 게스트가 필요해지면 관측 대체 경로와 함께) · **`DOCKER-USER`로 도커 발행 포트를 tailnet 안 특정 기기로
    좁히기**(실 엣지 상시 연결 시).
  - **탐지 채널·토픽(AI→Kafka→`/state`).** `detections.schema.json` 초안이 AI·VZ 회신 뒤 `payload/`로 오르면 그 규격을 싣는
    Kafka 토픽과 `/state` 분기가 여기다(원칙 2 — 새 채널은 백엔드가 연다). AI 통지(Phase 4 단계 9)가 초안을 전달한다.
  - **촬영본 세 곳 중복 정리** — pi 로컬(HW 기본값)·VZ `mission-history/images/robot/`·우리 4b 저장소. AI 저장본과의 관계도
    함께. 감사·인증과 같은 Phase에서 보관 주체를 정한다.
- 관련: BE-X-01~05(상관·감사·승격·승인·중계)·BE-A-01/02/03/04(명령 번역·임무·제어)·
  BE-Q-02(감사 조회)·BE-Q-04(인증·인가)·**BE-S-05(감사 쓰기)·BE-S-08(실행 기록 쓰기)**·BE-T-08(평면별 인증 나머지).

### Phase 7 — 디지털 트윈

**목표:** 구역 트윈이 전역으로 종합되고 로봇 투입 판단이 나온다.

- `backend/twin/`: 위치 융합(불확실도 가중, DT-01)·클래스 융합(베이지안, DT-02)·트윈 반영(좌표
  변환, DT-03)·커버리지·사각지대(DT-04)·시의성(DT-05)·핸드오프(DT-06)·로봇 투입 결정(DT-07).
- **Tier 구분:** 좌표 변환·융합·커버리지 로직은 Tier B(합성 fixture로 검증 가능). **Unity 트윈
  렌더 연결(VZ-U-02)은 Tier C**(가시화 파트 대기) — 백엔드는 전역 좌표까지 산출하고 가시화가
  렌더만.
- **DoD:** 합성 다중 검출·카메라 배치로 융합·커버리지·시의성이 계산되고, 전역 좌표가 산출된다.
  Unity 실제 렌더 정합은 가시화 통합 후.
- **외부 의존성:** AI-S-02(연계 신뢰도)·AI-E-02(카메라 보정) 입력은 공통 규격 기준. Unity는 가시화.
- **AI 관측 요청의 편입(DT-07).** 진나영 AI-S-05가 "재관측 등 물리 행동이 필요하면 AI는 대상·
  관측 조건·사유만 제시하고 실제 장치 선택·명령은 백엔드"로 넘긴다. 이 요청을 **사각지대·최신성·
  현재 임무 상태와 함께 투입 판단의 입력**으로 받는다(별도 우회 경로를 만들지 않는다 — 결정 지점을
  한 곳에 유지).
- **전역 객체 ID(DT-06).** AI가 구역 내 지속 객체 레코드를 구성하고(AI-S-06), 백엔드는 **구역 경계를
  넘을 때 전역 객체 ID를 부여·매핑**한다. 원본 프레임 참조(frame_ref)와 지속 객체 ID는 구분해 유지한다.
- **🆕 Phase 4 이월 (여기서 처리):**
  - **`object-reference.schema.json`을 `$ref` 레지스트리 검증 경로에 편입.** Phase 4가 `backend/ingest/envelope.py::schema_registry()`
    (`$id` → 로컬 파일, `referencing.Registry`)를 세웠고 `media-header`가 `frame-reference`를 그 경로로 참조한다(결정 12).
    `object-reference`도 같은 경로를 쓴다 — 인라인 복제하지 않는다(`tests/test_contract_media.py::test_registry_resolves_object_reference_like_media_header`가
    이미 해석을 확인한다).
  - **소스별 촬영 시각 보정.** `frame_ref.capture_timestamp`는 엣지가 프레임 경계를 확정한 시각(말단 지연 포함·미보정)이다.
    HW에 "imageai 웹소켓 프레임에 Go1이 찍은 촬영 시각이 실려 있는가"를 물었다(Phase 4 회신) — 있으면 편향이 사라지고,
    없으면 여기서 소스별 보정을 설계한다. 시연의 자세 정합(`rotation_deg`)은 DT-01·DT-04의 pose 부착으로 일반화한다.
  - **트윈 형식(HW #14)·다중 소스 병합 규칙.** 좌표 규약 ENU 이행·객체 핸드오프(DT-06)와 한 묶음. 병합 규칙이 정해지면
    4b `media_capture`(세션 1행·매니페스트 원본 통째)에서 파생한다.
- 관련: DT-01~07·BE-C-04(좌표 규약)·BE-A-03(하달 경로)·BE-C-03(`object-reference`).

---

## 3. 지금 당장 할 일 Top 3

- [x] **① 공통 규격 v1 확정** — 공통 헤더·frame_ref 스키마 정의 완료
  ([`../../contracts/common/`](../../contracts/common/)).
- [x] **② 인프라 스택 compose 기동 + 헬스 확인 (Phase 0)** — 완료(2026-09-04). 서버에 7개가 이미
  가동 중이어서 **Kafka만 신규 설치**하고 나머지는 헬스 확인. 8개 전부 헬스 통과.
  보고: [`../../reports/2026-09-04_1620_phase0_인프라기동.md`](../../reports/2026-09-04_1620_phase0_인프라기동.md)
- [x] **③ 가짜 발행자로 얇은 파이프라인 관통 (Phase 1)** — 완료(2026-09-07). 최소 발행자(C)와
  조병현 노드(A) 양쪽에서 `state`·`status`·`heartbeat`가 ingest(공통 헤더 strict 검증) → Kafka 3토픽 →
  저장 sink + WS까지 관통. 공통 헤더 불합격은 격리(pytest 음성 대조). 착수 전 결정 항목은 이렇게
  닫혔다: **토픽 규약** = 채널별 `mk2.telemetry.<채널>`(파티션1·RF1), **브릿지 구현체** = 파이썬
  직접, **Kafka advertised·포트** = 단일 머신이므로 `localhost`·`127.0.0.1:9092` **유지**(원격
  노출은 Phase 4로 이월).
  보고: [`../../reports/2026-09-07_1300_phase1_얇은파이프라인관통.md`](../../reports/2026-09-07_1300_phase1_얇은파이프라인관통.md)
  / HW 인계: [`hw-envelope-conformance.md`](hw-envelope-conformance.md)
- [x] **④ 저장 축 (Phase 2)** — 완료(2026-09-10). `TelemetryWriter.write()` 뒤를 **TimescaleDB로
  교체**(호출부 무변경)하고, MySQL에 **레지스트리 2축 + 감사 + 실행 기록** 8테이블을 세웠다.
  공통 헤더 규격이 **1.1**로 오르고(`session_id`) **채널 본문 규격 6종 + 느슨한 2단 검증**이
  켜졌다. 유실·역전 **검출은 조회 시점**으로 확정(`docs/be/queries/gap-detection.sql`).
  **pytest 103건 전건 통과**(음성 대조 5건 포함).
  착수 전 **기반 문서 보강이 선행되었다**(2026-09-09) — 관측 범위 3층(§8-3)·누락값 표현 규칙·
  용어 정리. 보고: [`../../reports/2026-09-09_1138_기반문서_보강.md`](../../reports/2026-09-09_1138_기반문서_보강.md)
  / Phase 2 보고: [`../../reports/2026-09-10_2200_phase2_저장축.md`](../../reports/2026-09-10_2200_phase2_저장축.md)
  / 회신·문의: [`hw-envelope-conformance.md`](hw-envelope-conformance.md) §6 ·
  [`vz-mission-record-inquiry.md`](vz-mission-record-inquiry.md)
- [x] **⑤ 관측 파이프라인 완성 (Phase 3)** — 완료(2026-09-16). Collector가 log→Loki·trace→Tempo를 **분배**하고
  (파이프라인 3종, digest 고정, 호스트 포트 무변경), Loki v13/tsdb+보존 14d·Tempo 168h·Prometheus `otel_collector` 5s.
  **A층 9종·C층 12종**이 관측 어댑터(`backend/observability.py`) 뒤에서 Prometheus·Loki로 흐르고, 상주 3개는 systemd다.
  **2계층 페더레이션과 Agent→Gateway 사슬을 임시 엣지(컴퓨터·Tailscale)로 실증**한 뒤 되돌렸다(`agg_layer="edge"` 규약 확정).
  **pytest 184건 전건 통과**(음성 대조 7건). 보고: [`../../reports/2026-09-16_1900_phase3_관측파이프라인.md`](../../reports/2026-09-16_1900_phase3_관측파이프라인.md)
  / 회신·통지: [`hw-envelope-conformance.md`](hw-envelope-conformance.md) §7 · [`vz-observability-namespace.md`](vz-observability-namespace.md)
- [x] **⑥ 미디어 경로 (Phase 4)** — 완료(2026-09-19). 방식 B 중계(native 코덱)·GOP 인지 drop-old·frame_ref 바이트 관통·
  경로 분리·터널 위 `ws`+토큰이 서버 pytest + 컴퓨터 임시 엣지 실측으로 닫혔고, Phase 1·2·3 이월 전부 처리(Kafka는 3수정
  대신 EDGE 리스너, frame_ref는 ISO 유지, WS는 두 주소+토큰, 4316·`edge_federate` 재실증 뒤 되돌림, Prometheus digest,
  `LoggingHandler`). 회신·통지 3건(HW §8·VZ·AI) 발송, 4b 촬영본 저장소(8767·`media_capture`) 개통. **서버 pytest 272 passed
  + 12 skip.** 보고: [`../../reports/2026-09-19_0600_phase4_미디어경로.md`](../../reports/2026-09-19_0600_phase4_미디어경로.md)
  / 작업로그: [`../../reports/2026-09-18_2100_phase4_작업로그.md`](../../reports/2026-09-18_2100_phase4_작업로그.md)
  / 회신·통지: [`hw-envelope-conformance.md`](hw-envelope-conformance.md) §8 · [`vz-media-interface.md`](vz-media-interface.md) ·
  [`ai-detections-interface.md`](ai-detections-interface.md)
- [ ] **⑦ 가용성 판정기 (Phase 5)** ← **다음** — `video_meta` 발행·`/state` VZ 계약 정합·레지스트리 목록·`MK2_MEDIA_SNDBUF`
  결정이 Phase 4에서 이월됐다. 회신 대기: HW 3(`stream_start/stop`·촬영 시각·IDR 간격) · VZ 5+1 · AI 2.

---

## 4. 외부 의존성 체크리스트

| 의존 대상 | 관련 Phase | 필요한 것 |
|---|---|---|
| 조병현 (HW) | Phase 1 | `sensor_node.py`(가져와 실행 — 확보) / 실 센서 입고는 Tier C |
| 조병현 (HW) | ~~**Phase 2 회신 대기**~~ → ✅ **반영 확인(2026-09-17, HW 브랜치 0914 대조)** ([`hw-envelope-conformance.md`](hw-envelope-conformance.md) §6) | ~~🔴 공통 헤더 편집 4개~~ · ~~🔴 `robot_node.py` 순번 결함~~ · ~~🟡 `session_id`~~ — `schema.py` 1.1·`sequence_id`·RFC3339·별칭 중단·`session_id`·`seq += 1` 전부 브랜치에 있다. ⚠ **pi7 배포본은 09-14에도 구판(1.3)** — 실노드 관통은 Phase 4 범위 밖(가짜 발행자 기본값 유지). 🟡 `reason` 어휘 확인은 남음. 근거: `reports/2026-09-17_1159_팀브랜치_최신화_대조.md` §1-1 |
| 조병현 (HW) | ✅ **Phase 4 회신 작성 완료 2026-09-19** · ⏳ **전달은 사용자 몫 — 상대 수신 미확인**(작업로그 단계 9 「검증하지 못한 것」) — [`hw-envelope-conformance.md`](hw-envelope-conformance.md) **§8**(`BACKEND_AGENDA` §8·§10-4~7·#14~#18, `ARCHITECTURE_ALIGNMENT.md`) → **HW 회신 대기 4건**(`stream_start/stop` 수용 · imageai 촬영 시각 유무 · IDR 간격 조절 가능 여부 · **실 스트림 장당 바이트·초당 장수** — `MK2_MEDIA_SNDBUF` 결정의 입력) | 상태 갱신(2026-09-19): 🔴 #14 트윈 스키마 소유(→Phase 7, 이유를 적는다 — 좌표 규약·핸드오프와 한 묶음. 단 다중 소스 병합 규칙은 4b 적재에도 걸리므로 4b는 병합 없이 세션 1행) · 🔴 **#15 촬영본 저장 0.7GB/h**(→ **결정 9 설계 확정, 구현은 단계 10** — 파일시스템 + PUT 두 번(매니페스트 먼저)·8767·`frame_ref_base` 없음·용량 상한 보존. ✅ **입구 8767은 2026-09-19 개통**(단계 10)) · 🔴 #16 로봇 상태 서버 경유(→ 경로는 이미 있음 + Unity 직결 대체 여부·전환 시점은 Phase 7) · 🟡 #17 Grafana 명령 API(→Phase 6) · ⚪ #18 엣지 2개 시점(→백엔드, Phase 5/7). **답이 없어도**: HW 기본값(null·로컬 적재·직결 유지)이 우리 설계와 충돌하지 않는다. 회신 골격은 지시서 부록 A(8-0~8-11): §10-7 = 권고 ① 수용(native 코덱, `HW_MEDIA_SENDER=go1_relay`) · §8 = ISO 유지 · §10-4 = ㉰ `alignment` · §10-5 = q 우선·해상도 변경은 재개 사건 · §10-6 = 소스가 정한다 · 인식 안내 7건(Collector 있음·`OTEL_ENDPOINT` 잠정 비움·구간 3은 Kafka·**MAC은 라우팅 키 아님(세 곳)**·라벨 기준·JSON→protobuf 번역 토픽 금지·**`up` 지표 개명**) · **신설 8-11: `stream` 명령이 규약 경로로 호출 불가** → `stream_start`/`stream_stop` 우회 요청 |
| 조병현 (HW) | 상시 | **HW 최신 push 요청** — pi7 작업 트리가 브랜치보다 앞선다(`turn`·`sdk_*`·`scan_hold/continue`·`forward_m=0` 수정). 브랜치를 HW 실체로 믿지 않는다 |
| 조병현 (HW) | Phase 6 | `detection-protocol_0914.md` §4 "탐지용 JSON→protobuf 번역 토픽을 열겠다" — 명령 번역은 백엔드 몫(BE-A-01·원칙 13). Phase 6 회신에서 이중화 방지 |
| 조병현 (HW) | **Phase 6 전 회신 대기** ([`hw-envelope-conformance.md`](hw-envelope-conformance.md) §7) | ⚪ **`.proto`에 `Command.traceparent` 필드 1개** + `otel_trace.py:77` carrier를 dict로 넘기는 한 줄. `BACKEND_AGENDA` §3(문자열/열거형 파라미터) 개정과 **같은 커밋**으로. 확인 2건 — 필드 번호를 누가 정하나 · 옛 말단 호환. **답이 없어도 백엔드는 멈추지 않는다**(필드가 없으면 말단이 새 trace를 시작하는 지금 동작이 곧 기본값) |
| 진나영 (AI) | Phase 4 | ✅ **시연 문서 2건 확보(2026-09-17)** — `_hwsrc/ai_docs_260914/탐지_로봇데이터요구_260914.md`(AI→HW) + `detection-protocol_0914.md`(HW→AI). **AI의 정식 요구는 스프레드시트(AI-C-08·AI-C-14·AI-E-*)이고 이 둘은 시연(45°×8 문 탐색)의 사례다.** 사례에서 남는 일반형: ⓐ 프레임 ↔ **촬영 시점 자세** 정합(시연의 "각도"는 특수 사례) ⓑ 프레임·탐지가 어느 명령의 산출인지 ⓒ 원본 무가공 ⓓ AI가 전송안 **B(RTP 스트림 + MQTT 캡처 이벤트)** 를 열어 둠 = 우리 경로 모양. 시연 특수(정지 후 촬영·한 장씩·스캔 경계·~2초/프레임)는 설계 대상 아님. **2026-09-19:** `capture_timestamp` 뜻(엣지가 프레임 경계를 확정한 시각·촬영 시각 아님) ✅ 통지([`ai-detections-interface.md`](ai-detections-interface.md) §5) · 남은 문의 1건(자율주행 편 영상이 우리 서버 7864에 닿는 경로) ✅ **같은 통지 §4에서 세 물음으로 보냈다** — 답 대기 |
| 진나영 (AI) | ✅ **Phase 4 통지 작성 완료 2026-09-19** · ⏳ **전달은 사용자 몫 — 상대 수신 미확인** — [`ai-detections-interface.md`](ai-detections-interface.md)(신설, 지시서 부록 D) → **AI 회신 대기 2건**(§1 규격 초안 · §4 7864 세 물음) | **`detections.schema.json` 초안의 생산자가 AI다** — 소비자(VZ)에게만 통지하고 생산자에게 하지 않는 구조를 고친다. 담을 것: 방식 B 프레임을 `/media`에서 받는 법(뷰어와 같은 소켓, `origin.tier="server"` 자리) · `frame_ref`를 헤더에서 읽어 그대로 붙인다(재생성 금지, 원칙 10) · `alignment`·`origin{tier,kind}`·`coord`(`top-left`)·`boxes[]` · 산출물은 좌표 JSON(번인 금지) · 탐지 채널·토픽은 Phase 6 · 7864 경로 답. **답이 없으면** 초안 그대로 `payload/`로 올리지 않고 초안 상태 유지 |
| 진나영 (AI) | Phase 6 | AI가 스캔 결과로 **이동 지시(`turn_deg`·`forward_distance_cm`)를 로봇에 직접 보낼 토픽**을 HW에 물었다(요구 §4, "지금은 보내지 않고 있다"). HW는 JSON 번역 토픽을 열겠다고 답함. **둘 다 백엔드 명령 경로(BE-A-01·원칙 8 command_id)를 우회** — Phase 6 회신에서 AI→백엔드→장치로 정리(AI-S-05 "AI는 제시만, 장치 선택·명령은 백엔드"와 같은 원칙) |
| 진나영 (AI) | Phase 6·7 | AI 실패·위험 판정·연계 신뢰도 규격(가짜 이벤트로 검증 / 실 모델은 Tier C) · 명령 의미 규격(AI-C-20) · **모델 승인 기록의 BE-* 신설 여부**(AI-L-06/07/08 — Phase 2가 감사 테이블에 자리만 확보). **AI 요구사항은 공유 스프레드시트에서 읽으면 되고 Phase 6 전까지 별도 문의가 필요 없다** |
| 김현우 (가시화) | Phase 4·7 | 뷰어 canvas 표시·오버레이 / Unity 트윈 렌더(Tier C). **2026-09-17 대조:** VZ-C-07 구현됨(주소 런타임 설정, 전송층에 인증 훅 없음) · 와이어 계약은 `viz-debugger/src/transport/types.ts`·`gateway/protocol.ts`(영상이 상태와 같은 소켓, `frame_ref` 정수) · 뷰어는 도형+`frame_seq` 목 상태로 **백엔드 형식 초안 대기** · VZ 미결 §7.4(뷰어 출력 분기·소유 파트)·§7.10(카메라 연결 상태) → **Phase 4 통지에서 답한다** |
| 김현우 (가시화) | ✅ **Phase 4 통지 작성 완료 2026-09-19** · ⏳ **전달은 사용자 몫 — 상대 수신 미확인** — [`vz-media-interface.md`](vz-media-interface.md)(신설, 지시서 부록 B 13항목 + 관측 회신 답 §9) → **회신 대기 항목 5개(§10) + 탐지 규격 이름 선택(§6)** | **VZ가 알려 줄 것:** ① 관제 웹 기기의 **tailnet 주소**(8765·4318 ufw `/32` — 받기 전에는 VZ 입구를 열지 않는다) ② Collector **CORS origin**·exporter 종류(protobuf/json) ③ 관제 웹 **https 여부**(mixed content — https면 4318 TLS가 필요해 결정 7 범위를 넘는다) ④ 실제 `source_id`(우리 답: `go1-001`, 카메라는 `go1-001_front`) ⑤ **「발화 원문」 라벨의 실제 키 이름**(`FORBIDDEN_LABELS` 9종째). **VZ 쪽 변경:** `ws.binaryType='arraybuffer'`·텍스트/바이너리 분기·`[4B][JSON][페이로드]` 파서·WebCodecs/`createImageBitmap` 디코드·`frame_ref` 객체(정수 `frame_seq` 아님)·`coord`↔`bbox_space`·`origin.tier`에 `server`·`node_ref` 이름·`catch{return}`에 카운터. **답이 없어도**: 8765는 사용자 컴퓨터 `/32`로만 열려 있고 VZ는 목 게이트웨이를 계속 쓴다 |
| 김현우 (가시화) | Phase 5 · Phase 6 | VZ 요구사항정의서 §7.6 — HW-C-05 60초 export vs BE-S-03 15초 pull 불일치(→Phase 5) · §7.3 — 감사 `origin.path`를 `input.mode`·`decision.source` 두 축으로 분리 요청 중(→Phase 6 감사 규격) |
| 김현우 (가시화) | ~~**Phase 6 전 회신 대기**~~ → ✅ **회신 받음 2026-09-17** ([`received/2026-09-17_vz-mission-record-reply.md`](received/2026-09-17_vz-mission-record-reply.md)) | 골격 맞음(재작성 없음). 확정: 실패 4단계 `plan_failed`·`dispatch_failed`·`execution_failed`·`evaluation_failed` · `node_ref`·`mission_id` VZ 부여(판마다 새 `mission_id`) · 8종 파생·구간 계산 VZ · 보존 무기한 · `event_key`=`{mission_id}:{VZ 순번}`. **백엔드가 할 것(Phase 6 이월):** 임무 정의 저장 자리 · `layer`에 `mission` · `subject_kind` 3종 방식 · `origin_kind` 발행 주체 · Go1 `source_id`=`go1-001` 답 |
| 김현우 (가시화) | ~~**지표 발행 시작 전 회신 대기**~~ → ✅ **회신 받음 2026-09-17** ([`received/2026-09-17_vz-observability-namespace-reply.md`](received/2026-09-17_vz-observability-namespace-reply.md)) | 수용: `vz.` · `service.name` = `vz-viewer`·`vz-stt`·`vz-gen` · 지표만(로그·트레이스 없음). **백엔드의 답 ✅ 2026-09-19 — [`vz-media-interface.md`](vz-media-interface.md) §9(+§11 우리 통지 §4 정정):** ① 발행 주기 60초 OK — 단 근거 정정: HW는 15초로 **공식 채택·정의서 개정 완료**(`BACKEND_AGENDA` §10-1·SRS §9.11), 주기는 발신자 몫이라 VZ 60초는 그대로 괜찮다 ② **브라우저 발신 경로 = 결정 7 A**(Collector OTLP/HTTP **4318을 Tailscale IP에만** + CORS + ufw `/32` — 뷰어는 tailnet 안이라 인터넷 노출 아님). **구현은 tailnet 주소·CORS origin·exporter 종류·https 여부 회신 뒤**(위 행) · `vz-stt`·`vz-gen`은 별도 프로세스라 발신 주소를 따로 묻는다 · 우리 통지 §4의 세 문장(4318 닫힘·4316·TLS)을 **개정 고지** ③ ✅ 라벨 8종 `FORBIDDEN_LABELS`에 반영(`node_id` 제외 → DAG 노드는 **`node_ref`라는 이름으로** 내보내 달라 요청) — 「발화 원문」은 키 이름 회신 뒤. Unity 트윈 담당 미정은 Phase 7 메모 |
| 현장/실측 | Phase 4·5 | 회선 QoS·콜드스타트(Tier C) · **Tailscale은 연구실 환경에서 Phase 3(DERP 72ms → 직접 3ms)·Phase 4(직접 2ms/22ms, 미디어·Kafka·관측이 한 터널 공유)에 실측** · **느린 링크는 서버 `tc tbf 500kbit` 한 조건만**(drop-old IDR 재개·지연 p90 2.34s) — 현장 엣지-서버 배치·DERP 경유·실물 로봇 영상·실물 엣지 노트북·GOP 경계 프레임률 불균일은 남아 있다 |

> **HW 소스의 최신본은 `_hwsrc/upstream_<날짜>/`** 에 둔다(gitignore, 절대 고치지 않는다). 새 브랜치가
> 오면 이전 것과 해시 비교한다 — 절차는 `_hwsrc/README.md`. 우리가 편집을 얹은 실행 사본은
> `local_patched_*/`이며 **근거로 쓰지 않는다**(Phase 2 보고서 「발견한 것 ⑧」).
> **2026-09-17 현재 최신 사본은 `_hwsrc/` 밖에 있다** — HW 0914 = `C:\Users\asdfa\physical mk2\compare\Physical-Project-mk2-HW_260917\`,
> VZ 0916 = `…\compare\Physical-Project-mk2-khw_VZ_260917\`(이동하지 않기로 함). 대조 결과와 위치는
> `reports/2026-09-17_1159_팀브랜치_최신화_대조.md`.

---

## 5. 검증 방침 (완료 판정 수단)

- **Phase 0(인프라 기동):** compose 헬스체크 + 수동 확인(pytest 아님).
- **Phase 1 이후:** **pytest** — "가짜 발행자 → 파이프라인 → 예상 저장/중계" 회귀. 진나영과
  도구를 통일해 나중 통합 검증이 수월하게 한다.
- 선택 구성요소(예: 실 Grafana 연동)가 없으면 해당 테스트만 skip하고 나머지는 통과 — 이 격리
  자체가 요구사항(핵심·선택 분리)의 증거다. **Phase 2에서 실현됐다** — `tests/conftest.py`의
  `tsdb_conn`·`mysql_conn` fixture가 접속 실패를 `pytest.skip`으로 바꾼다(서버 skip 0 / 컴퓨터 28 skip,
  양방향 확인). 새 저장소·외부 의존이 생기면 같은 방식으로 fixture를 더한다. **Phase 3에서 관측 3종에도
  같은 fixture를 더했다**(`prometheus_url`·`loki_url`·`tempo_url`, 표준 `urllib`만). 서버 전건 **184건**(2026-09-16,
  skip 0) → **Phase 4 뒤 272 passed + 12 skip**(2026-09-19, skip은 8766 닫힘이 정상), 컴퓨터는 단위 파일만
  돌려 **139 passed / 2 skipped**(Phase 3) → **133 + 28 passed**(Phase 4, 4b 포함) — Mosquitto·Kafka를 필수로 두는 `test_pipeline.py`와
  저장소 전용 파일 셋은 컴퓨터에서 돌리지 않는다.
- **"떠 있다"로 판정하지 않는다.** 관측 스택은 컨테이너가 `Up`이어도 데이터가 0건일 수 있었다(Phase 3 착수 시
  실측). 판정은 **발행 전후의 차분**(counter는 리셋을 `rate()`처럼 처리)·최근 시각 범위의 로그·태그값의 출현으로 한다
  (`infra/README.md` §4 「흐른다」).
- 상태를 **완료**로 올릴 때는 반드시 동작과 허용 범위를 검증하는 테스트를 [`requirement-traceability.md`](requirement-traceability.md)에
  함께 기록한다(테스트 없는 완료 금지). 검증 스크립트가 무력하지 않은지(무효 입력을 실제로
  거부하는지) 음성 대조도 포함한다.
