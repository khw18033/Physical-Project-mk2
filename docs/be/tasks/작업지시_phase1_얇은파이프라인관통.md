# 작업 지시서 — Phase 1: 얇은 파이프라인 관통

> 저장 위치: `docs/be/tasks/작업지시_phase1_얇은파이프라인관통.md`
> 구현이 끝나면 `docs/be/tasks/_archive/`로 옮긴다(누적 참조 대상 아님).

---

## 1. 머리말

- **대상:** Phase 1 — 얇은 파이프라인 관통 (가짜 발행자 → `ingest` → Kafka → 저장 sink → WS echo)
- **착수:** Phase 0(인프라 기동, 2026-09-04) 완료 직후. 다음 작업 사이클.
- **근거 문서:**
  - [`docs/be/01-standalone-implementation-plan.md`](../01-standalone-implementation-plan.md) — Phase 1 항목(관통 순서·DoD·발행자 C→A)
  - [`docs/be/00-architecture.md`](../00-architecture.md) — §4-2(브릿지 실체), §5-1(Kafka 근거), §6-1(다중 소비자 팬아웃), §7-1(WS 게이트웨이)
  - [`docs/be/requirement-traceability.md`](../requirement-traceability.md) — BE-C-01 / BE-T-01 / BE-T-02 / BE-T-03 / BE-S-01
  - [`contracts/common/`](../../../contracts/common/) — 봉투 계약 정본
  - [`infra/README.md`](../../../infra/README.md) — 포트·기동·헬스·Kafka 설정
  - [`reports/2026-09-04_1620_phase0_인프라기동.md`](../../../reports/2026-09-04_1620_phase0_인프라기동.md) — Phase 0 미결/이월표

> 이 문서는 VS Code Claude Code가 읽고 구현하는 인수인계 문서다. CLAUDE.md와 이 지시서를 함께
> 읽고, 지시서 범위대로 구현한다. **설계는 끝났으므로 새로 설계하지 않는다.** 아래 구조 결정(발행자
> 순서·브릿지 구현체·토픽 규약·저장 경계·검증 정책·WS 범위)은 설계 단계에서 이미 확정됐다 —
> 임의로 되돌리거나 다른 선택지를 열지 않는다.

> ⚠️ **이 문서는 완료된 지시서다(2026-09-07 완료). 살아 있는 제약이 아니다.**
> 아래 제약·완료 판정은 **착수 시점의 결정**을 그대로 담고 있으며, 이후 바뀐 것이 있다.
> - **RBAC는 그 뒤 채택으로 확정됐다**(BE-Q-04, 구현은 Phase 6). §3 제약 6번의 "RBAC·MongoDB·
>   TSDB를 도입하지 않는다"는 Phase 1 당시의 범위 울타리다(MongoDB 미채택과 TSDB는 Phase 2라는
>   부분은 지금도 유효하다).
> - **저장 축은 그 뒤 셋이 됐다**(계측 TSDB / 감사·레지스트리 MySQL / 임무 실행 기록 MySQL).
>   아래 "2축" 표기는 당시 기준이다.
>
> 현재 기준은 [`CLAUDE.md`](../../../CLAUDE.md) §1과
> [`00-architecture.md`](../00-architecture.md) §6-2다. **본문은 기록 보존을 위해 고치지 않는다**
> — 이 지시서의 완료 판정 항목은 `reports/2026-09-07_1300_phase1_얇은파이프라인관통.md`의 검증
> 결과와 번호로 짝을 이룬다.

> **실행 주체 — CLAUDE.md §0 워크플로 그대로(어기면 Phase 0 재발).** 편집·생성은 **Claude Code가
> 컴퓨터(이 저장소)에서** 한다. 실제 실행 — 코드 서버 반영, 컨테이너/`docker exec`(토픽 생성),
> pytest, 서버 상태 확인 — 은 **사람이 서버(sysai-server2)에서** 한다. Claude Code는 서버에 붙지
> 않고, 서버 파일을 직접 수정하지 않으며, 서버에 저장소를 clone·`git pull`하지 않는다(깃허브는
> 코드·문서 동기화용이지 서버 배포 통로가 아니다). **Claude Code는 실행할 명령·코드를 제시하고,
> 사람이 서버에서 돌린 결과를 받아 반영한다** — 서버 상태·명령 결과를 추측하거나 지어내지 않는다
> (§1-A 규율 2·3). 컴퓨터→서버 코드 반영은 사람이 기존 방식대로 복사·적용한다.
>
> **실행 위치 분해(중요).** 서버에서 도는 것: `ingest`·저장 sink·WS·Kafka·`docker exec`(토픽
> 생성)·서버 상태 확인·pytest의 파이프라인 대상. **발행자(단계 5의 최소 스크립트, 단계 6의
> 실노드)만 컴퓨터에서 실행**해 **서버 Mosquitto(`210.110.250.33:1883`, 익명)로 발행**한다 —
> 실제 배치(발행자=말단/엣지, 브로커=서버)와 같은 방향이라 발행자↔브로커 네트워크 경로까지 함께
> 검증된다. 발행자는 MQTT만 쏘고 Kafka를 모르므로 이 구성에서 **Kafka는 여전히 서버 localhost
> 전용**이고 노출이 필요 없다 — 그래서 Kafka advertised=localhost·`127.0.0.1:9092`를 이번
> Phase에서 바꾸지 않는다(제약 5). Kafka에 붙는 코드(`ingest`·sink·WS)는 전부 서버에 있다.

---

## 2. 배경

Phase 0에서 스택 8개를 세웠고(Kafka만 신규, 나머지 7개는 헬스 확인), 지금은 그 위에 **첫 데이터
경로를 한 줄로 관통**시킨다. 관통의 목적은 두 가지다: (1) 방금 확정한 봉투 계약이 실제로 도는가,
(2) 파이프라인의 모양 — 봉투 검증 → Kafka 팬아웃 → 저장 수신 → WS push — 이 성립하는가. 이 얇은
관통 위에 Phase 2~(저장 2축·관측·미디어·가용성·감사·트윈)가 얹힌다. 먼저 뚫고 그 위에 기능을
얹는 전략(계획 §0-1)이다.

**딛고 서는 것:** 가동 중인 Mosquitto(서버 `1883`, `0.0.0.0`·익명 → 컴퓨터에서 `210.110.250.33:1883`
으로 도달)·Kafka(서버 `127.0.0.1:9092`, KRaft 단일 노드, healthy → 서버 localhost 전용), 확정된
봉투 계약, 조병현 노드(로컬 사본으로 실행). 발행자는 컴퓨터에서 서버 Mosquitto로 발행하고,
Kafka에 붙는 코드는 서버에서 돈다(머리말 실행 위치 분해 참조).

**Phase 0에서 이월돼 이번에 닫는 것:**
- Kafka `advertised.listeners`가 `localhost` → **이번 Phase는 단일 머신이라 localhost로 충분**하다.
  변경하지 않는다(원격은 §6·미래작업).
- 토픽 이름 규약 미정 + "`.`과 `_`를 섞지 말 것" 경고 → §단계 1·D4 규약으로 확정.
- 브릿지 구현체 미정 → **파이썬 직접**으로 확정(§단계 2).

**설계 단계에서 새로 확인된 구조(범위에 직접 영향):** 명령 경로는 텔레메트리와 **완전히 다른
프로토콜**이다. `common/physical_command.py`가 정본이고 "구 JSON 4단계 엔진은 폐기"됐다. 명령은
`terminal/<device_id>/downlink|uplink` 위에서 **protobuf**(`PhysicalCommandEnvelope`)로 흐르며
JSON 봉투 계약이 이를 지배하지 않는다. **따라서 Phase 1은 JSON 텔레메트리 3채널
(`state`/`status`/`heartbeat`)만 다루고 명령 경로는 손대지 않는다(Phase 6).**

---

## 3. 제약 — 반드시 지킬 것

1. **봉투 계약이 파트 경계다.** `contracts/common/message.schema.json`이 정본이며, 봉투 필드명을
   임의로 짓지 않는다(CLAUDE.md §1 원칙 9). 파이썬 타입을 다른 파트에 노출·강제하지 않는다.
2. **ingest는 수신 즉시 strict 검증한다(포맷 포함).** 봉투 스키마 + `date-time` 포맷을 실제로
   assert하고(FormatChecker), **불합격 메시지는 정상 토픽으로 재발행하지 않고 격리·기록한다.**
   전환/관용 모드 없음 — 처음부터 fail-closed다.
3. **영상 픽셀·명령 protobuf를 텔레메트리 경로에 싣지 않는다.** ingest는 `terminal/#`을 구독하지
   않는다(명령은 Phase 6). MQTT/Kafka 텔레메트리 메시지에 JPEG를 넣지 않는다(원칙 3).
4. **특정 제품을 상위 로직에 하드코딩하지 않는다.** 저장은 목적 수준 인터페이스(`store(...)`) 뒤에
   두고, Kafka produce/consume은 `ingest`/`gateway` 경계 안에 가둔다(원칙 1). 상위에서 Influx/
   Timescale 클라이언트를 직접 부르지 않는다.
5. **서버에 도는 것을 지웠다 다시 깔지 않는다.** `docker compose up -d`에는 반드시 서비스 이름을
   명시한다(이름 없이 실행하면 `:latest` 서비스가 재생성될 수 있다). **Kafka 설정(advertised·포트
   바인딩·ufw)은 이번 Phase에서 바꾸지 않는다.**
6. **RBAC·MongoDB·TSDB를 도입하지 않는다**(정본 결정; TSDB는 Phase 2). 트윈·명령진행·가용성은
   저장하지 않는다(Phase 1은 어차피 판정하지 않음).
7. **인증·TLS·ACL을 이번에 하지 않는다.** Mosquitto 익명·Kafka PLAINTEXT를 그대로 쓴다(Phase 1
   브릿지 연결에 오히려 유리 — Phase 0 보고서 확인).
8. **비밀값·`infra/docker-compose.yml`·내부망 IP를 커밋하지 않는다**(저장소는 Public). 파일 인코딩
   UTF-8, 줄바꿈 LF.
9. **ingest의 MQTT `client_id`는 노드와 겹치지 않는 고유값**(예: `mk2-ingest`)을 쓴다. 노드는
   `client_id=entity_id`로 붙고(`common/node.py`), 같은 id가 겹치면 "session taken over" 플래핑이
   난다(노드에 중복 경보 로직이 있다).
10. **저장 소비자와 WS 소비자는 서로 다른 Kafka 컨슈머 그룹**(독립 오프셋)을 쓴다 — 이 독립성이
    다중 소비자 팬아웃(§6-1)의 얇은 실현이며 완료 판정의 일부다.
11. **구독이 먼저, 발행이 나중.** ingest가 구독을 건 뒤에 발행한다(발행자가 먼저 쏘면 클린 세션
    ingest는 그 메시지를 못 받는다). 관통 확인·pytest·실노드 실행 모두 이 순서를 지킨다.
12. **컴퓨터→서버 Mosquitto(`210.110.250.33:1883`) 도달은 착수 전 사람이 확인한다.** 발행자가
    컴퓨터에서 붙으므로 전제다. 닿지 않으면 멈추고 `reports/`에 남긴다 — **방화벽·바인딩을 임의로
    바꾸지 않는다**(Kafka 노출과 별개 사안, 임의 변경 금지).

---

## 4. 먼저 읽을 것

- **CLAUDE.md 전체** — §0(워크플로·서버 배포 방식), §1(절대 원칙), §1-A(구현 규율), §2(금지),
  §3(요구사항 추적). 특히 §1-A: 사실 다 받기 전 해법 금지, 지시서-현실 차이는 보고 후 결정, 범위
  임의 확장 금지, 이월사항을 미래 Phase에 흘려보내기.
- **`docs/be/01-standalone-implementation-plan.md` Phase 1** — 발행자 C→A 순서, 관통 순서(저장 →
  WS), DoD.
- **`docs/be/00-architecture.md`** — §4-2(브릿지는 두 개의 TCP 연결일 뿐), §5-1(Kafka 근거=다중
  소비자), §6-1(팬아웃), §7-1(WS 게이트웨이=Kafka 소비자+WebSocket 서버).
- **`contracts/common/message.schema.json` + `README.md` + `examples/envelope-valid.json`** — 봉투
  필수 5필드(`schema_version`·`source_id`·`node_id`·`zone_id`·`timestamp`)·선택 필드·검증 규약
  (실패 시 정상 topic 재발행 금지, 격리). `envelope-valid.json`이 회귀 양성 fixture다.
- **`infra/README.md`** — §3(포트: Kafka `127.0.0.1:9092`), §4(기동·헬스), §5(Kafka 설정값,
  특히 **서비스 이름 명시 경고**와 9092 로컬 바인딩·`AUTO_CREATE_TOPICS_ENABLE=false`).
- **`reports/2026-09-04_1620_phase0_인프라기동.md` 미결표** — advertised·토픽 `.`/`_`·브릿지
  구현체 항목(이번에 반영).
- **HW 공통 패키지(참조용, 편집 대상 아님 — §단계 6 로컬 사본 제외):**
  - `common/node.py` — 텔레메트리 발행 경로의 실체. `base = {zone}/{etype}/{eid}`, 채널
    `{base}/state|status|heartbeat`, LWT(death)는 `{base}/status`에 retained. `_on_message`가
    `terminal/<id>/downlink`만 처리(그 외 무시).
  - `common/schema.py` — `envelope()`가 봉투를 만든다. **현재 `seq`·`device_id`를 싣고 timestamp
    오프셋에 콜론이 없다**(§단계 6·부록에서 정합).
  - `sensor_node.py` — `state` 채널 페이로드 형태(하천 수위).
  - `common/config.py` — `TOPIC_TEMPLATE="{zone}/{etype}/{eid}"`, `BROKER_HOST`(임시 노트북 IP),
    주기·임계값. 모두 `HW_*` 환경변수로 덮어쓸 수 있다.

---

## 5. 단계 + 각 단계 DoD

### 단계 0 — 서버 현재 상태 확인 (먼저, §1-A 규율 2)

착수 전 서버 상태가 아래 **확정 기준선**과 같은지 확인한다. 다르면 멈추고 보고한다(혼자 절충하지
않는다).

```bash
docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}' | grep -iE 'kafka|mosquitto'
docker inspect capstone_kafka --format '{{range .Config.Env}}{{println .}}{{end}}' | grep ADVERTISED
docker inspect capstone_kafka --format '{{json .HostConfig.PortBindings}}'
```

**확정 기준선(변하지 않았어야 함):**
- `capstone_kafka` = `Up (healthy)`, 포트 바인딩 `127.0.0.1:9092`, `KAFKA_ADVERTISED_LISTENERS`에
  `PLAINTEXT://localhost:9092`.
- `capstone_mosquitto` = `Up`, `1883` 노출, 익명 허용.

**DoD:** 기준선 일치 확인. Kafka가 없거나 advertised/포트가 바뀌었으면 **멈추고 `reports/`에
기록** 후 결정을 받는다(단일 머신 관통은 localhost advertised 전제이므로 이게 깨지면 진행 불가).

### 단계 1 — Kafka 텔레메트리 토픽 3개 생성

`AUTO_CREATE_TOPICS_ENABLE=false`이므로 명시적으로 만든다.

```bash
for ch in state status heartbeat; do
  docker exec capstone_kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 \
    --create --topic "mk2.telemetry.$ch" --partitions 1 --replication-factor 1
done
docker exec capstone_kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list
```

- **토픽 규약(확정):** 채널별 3토픽 `mk2.telemetry.state` · `mk2.telemetry.status` ·
  `mk2.telemetry.heartbeat`. **파티션 1, 복제 인자 1**(단일 노드). 이름은 점 구분 소문자,
  **언더스코어 금지**(Kafka 메트릭 이름 변환 충돌 회피). **장치별 토픽이 아니다** — `zone`·
  `source_id`는 봉투 안에 있고 토픽 이름에 넣지 않는다.

**DoD:** `--list`에 3개 토픽이 보인다.

### 단계 2 — ingest 브릿지 (MQTT → Kafka), 파이썬 직접

`backend/ingest/`에 파이썬으로 구현한다(Kafka Connect·브로커 네이티브 아님 — 이 경계에서 봉투
검증·격리·라우팅을 해야 하므로).

- **MQTT:** `paho-mqtt`, **고유 `client_id`**(예: `mk2-ingest`), `localhost:1883` 접속(익명).
  구독은 정확히 **`+/+/+/state`, `+/+/+/status`, `+/+/+/heartbeat`** 세 패턴 — 이렇게 하면
  `terminal/#`(명령, Phase 6)이 자연히 제외된다.
  - **etype는 `sensor` 하나가 아니다.** HW는 `{zone}/{etype}/{eid}/{channel}`에서
    etype ∈ `{sensor, robot, actuator, analysis}`를 쓴다(예: `zoneA/analysis/wl-001/state` =
    증강 분석 워크로드). `+/+/+/<채널>` 구독은 **타입 무관이라 이들 전부를 잡는다 — 코드 변경
    없음.** Phase 1 (A)는 sensor로 검증하되, robot/actuator/analysis 메시지가 와도 같은 봉투
    검증→produce 경로로 처리된다(본문만 다름).
- **메시지 처리(각 수신마다):**
  1. JSON 파싱.
  2. `contracts/common/message.schema.json`으로 **strict 검증** — `jsonschema` +
     `FormatChecker`(+`rfc3339-validator`)로 `date-time` 포맷까지 실제로 assert. 봉투만 검증한다
     (채널 본문 payload 스키마는 아직 없음 → 통과시킨다. 본문 검증은 채널 스키마 작성 후, 범위
     밖).
  3. **불합격** → 격리 기록(예: `backend/ingest/quarantine.jsonl` — 런타임 산출물, gitignore):
     `{수신시각, topic, 사유, raw}`. **Kafka로 produce하지 않는다.**
  4. **합격** → MQTT topic의 말단 세그먼트(`state`/`status`/`heartbeat`)로 `mk2.telemetry.<세그먼트>`
     결정. `confluent-kafka` 프로듀서로 `localhost:9092`에 produce. **key = 봉투의 `source_id`,
     value = 원본 JSON 바이트**(생산자가 계약에 맞으므로 정규화하지 않는다).
- **MQTT 수신 특성 — 구현·검증 때 헛디디지 않도록(설계 변경 아님, 주의):**
  - **구독이 먼저, 발행이 나중.** node.py의 `state`는 QoS 1이지만, ingest가 구독을 걸기 전에
    발행된 메시지는 브로커가 (ingest가 클린 세션이면) 버린다. 관통 확인·pytest는 **ingest 구독이
    올라온 뒤 발행**하는 순서로 한다. (영속 세션·QoS 보존 정책은 Phase 5 운영 몫 — 여기선 순서만.)
  - **`status`는 retained다.** node.py가 `{base}/status`를 `retain=true`로 발행하므로, ingest가
    구독하는 **순간 브로커가 마지막 retained `status` 1건을 즉시 밀어준다.** "발행 안 했는데
    status가 하나 뜬다"는 정상이다 — 다른 메시지와 똑같이 검증→produce하면 된다.
  - **`heartbeat`는 QoS 0다.** 유실 허용이라 관통 확인 때 heartbeat가 몇 개 빠져도 정상이다
    (완료 판정을 heartbeat 개수로 걸지 않는다).
  - **LWT(death)도 `status` 채널로 온다.** node.py의 LWT는 `{base}/status`에 death 페이로드
    (retained)다. Phase 1 ingest는 이걸 **그냥 status로 흘려보내기만** 하고 가용성 판정은 하지
    않는다(판정은 Phase 5).
- docstring 상단: `implements: BE-T-01, BE-T-02, BE-C-01`.
- 추가 의존성(pyproject): `paho-mqtt`, `confluent-kafka`, `jsonschema`, `rfc3339-validator`.

**DoD:** 콘솔 consumer(`kafka-console-consumer.sh`)를 띄운 상태에서 — **ingest 구독이 올라온 뒤**
계약에 맞는 `state` 메시지를 수동 발행하면 `mk2.telemetry.state`에 도착하고, `zone_id` 누락
메시지는 **토픽에 안 뜨고** 격리 파일에 사유와 함께 남는다. (구독 즉시 도착하는 retained `status`
1건은 정상이며 격리 대상이 아니다.)

### 단계 3 — 저장 sink 소비자 (관통 ①: 저장 확인)

`backend/storage/`에 **목적 인터페이스 + placeholder 구현**을 둔다.

- 인터페이스: `store(record)` 한 함수(예: `TelemetryWriter.write(record)`). `record`는 검증 통과한
  봉투+본문(dict)과 어느 채널/토픽에서 왔는지. **Phase 1 구현은 placeholder** — 로그로 찍거나
  파일에 append해 "받았다"만 보이면 된다. **Phase 2에서 이 함수 몸통만 TSDB로 교체하고 ingest·
  인터페이스는 건드리지 않는다.**
- Kafka consumer(**그룹 `mk2-storage`**)가 3토픽을 구독 → 각 메시지에 `store(...)` 호출.
- docstring: `implements: BE-S-01`(현 단계 placeholder임을 명시).

**DoD:** 발행한 값이 sink 기록(로그/파일)에 나타난다.

### 단계 4 — WS echo 소비자 (관통 ②: 화면 확인)

`backend/gateway/`에 최소 WebSocket echo를 둔다(§7-1의 WS 게이트웨이의 얇은 선행 — 본구현은
Phase 5/7).

- Kafka consumer(**그룹 `mk2-ws`**, 저장과 **독립 오프셋**)가 최소 `mk2.telemetry.state`를 구독
  (원하면 3토픽) → `websockets` 서버로 연결된 클라이언트에 JSON push. **인증·구독관리·캐시 없음**
  (그건 Phase 5/7).
- 확인용 최소 클라이언트(간단한 HTML 콘솔 또는 `wscat`)로 값 도달을 본다.
- docstring: `implements: BE-T-03`(현 단계 echo임을 명시).

**DoD:** 브라우저 콘솔/클라이언트에 실시간 값이 뜬다. **저장 그룹과 WS 그룹이 같은 메시지를 각자
독립으로 수신**하는 것으로 팬아웃을 확인한다.

### 단계 5 — (C) 최소 발행자 + pytest 회귀

`tests/` 아래에 **계약에 맞춘 최소 발행 스크립트**(테스트 헬퍼)를 만든다 — 팀원 의존 0, 내 계약이
실제로 도는지 검증.

- **발행 위치 = 컴퓨터.** 발행자는 MQTT만 쏘고 Kafka를 모르므로 **컴퓨터에서 실행해 서버
  Mosquitto(`210.110.250.33:1883`, 익명)로 발행**한다. 실제 배치(발행자=말단/엣지, 브로커=서버)와
  같은 방향이라 발행자↔브로커 네트워크 경로까지 함께 검증된다. (브로커에 붙는 것은 발행자이고,
  Kafka에 붙는 것은 서버의 `ingest`이므로 Kafka 노출은 필요 없다 — advertised 그대로.)
  - 브로커 주소는 하드코딩하지 말고 환경변수/인자로(예: `MK2_BROKER_HOST`, 기본
    `210.110.250.33`, 포트 `1883`). pytest도 이 변수로 브로커를 가리킨다.
  - **전제 확인(사람):** 컴퓨터에서 서버 `1883`에 실제로 닿는지 한 번 확인한다(예: 서버 밖에서
    `nc -vz 210.110.250.33 1883` 또는 `mosquitto_pub -h 210.110.250.33 -t t -m x`). 닿지 않으면
    멈추고 원인부터(막히면 `reports/`에 남긴다 — 임의로 방화벽 등을 건드리지 않는다).
- 봉투: `schema_version:"1.0"`, `source_id`, `node_id`, `zone_id`, `timestamp`(콜론 오프셋
  `+09:00`), `sequence_id`, `origin_kind:"real"` + `channel:"state"` 본문(예: `water_level_m`).
  `zoneA/sensor/wl-001/state`에 발행.
- **pytest(§검증 방침 = Phase 1부터 pytest):** 발행자는 컴퓨터에서, 검증 대상 파이프라인
  (`ingest`·Kafka·sink·WS)은 서버에서 돈다. pytest는 컴퓨터에서 서버 Mosquitto로 발행하고, 결과가
  나타나는 곳(서버 Kafka 토픽·sink 기록·WS)을 확인한다. Kafka 토픽 확인처럼 서버 localhost에서만
  보이는 것은 사람이 서버에서 확인해 결과를 회수한다.
  - `test_valid_roundtrip` — 발행 → `mk2.telemetry.state`에 **key=source_id·동일 value** 도착.
  - `test_invalid_quarantined`(**음성 대조**) — `zone_id` 누락 / 콜론 없는 `timestamp`(`+0900`)
    각각 → 토픽에 **안 뜨고** 격리 기록에 남는다. (검증이 무력하지 않은지 실제로 거부하는 것을
    본다 — CLAUDE.md §3.)
  - `test_ws_delivery` — 발행 → WS 클라이언트가 수신(WS는 서버가 서빙; 클라이언트는 컴퓨터에서
    서버 WS 주소로 붙어 확인 가능).
- 음성 대조 fixture 추가: `contracts/common/examples/envelope-invalid-missing-zone.json`,
  `envelope-invalid-timestamp.json`.
- Mosquitto·Kafka(서버) 가동을 전제한다(둘은 Phase 1 파이프라인의 필수 요소라 skip 대상이 아니다).

**DoD:** `pytest -q` 양성 + 음성 + WS 통과(발행은 컴퓨터→서버 Mosquitto 경로로 이뤄진다).

### 단계 6 — (A) 실노드 로컬 연결 검증

조병현 HW 공통 패키지의 **로컬 사본**(컴퓨터)에 봉투 정합 편집 4개를 적용한 뒤(정확한 편집은
**부록**), 실노드를 **컴퓨터에서 실행해 서버 Mosquitto로** 붙여 전 구간 관통을 확인한다. 단계 5의
(C)와 같은 방향(발행자=컴퓨터, 브로커=서버)이다.

```bash
# HW repo 로컬 사본의 pi/ 에서 (컴퓨터. common/ 에 부록 4개 편집 적용 후)
HW_ENTITY_ID=wl-001 HW_BROKER_HOST=210.110.250.33 python3 -m sensor.sensor_node
# 임계 초과 이벤트를 보려면 별도 터미널에서: touch /tmp/rain   (HW_RAIN_FLAG 기본 경로)
```

- `HW_BROKER_HOST`를 **서버 주소(`210.110.250.33`)**로 준다(노드 기본값은 임시 노트북 IP라
  반드시 덮어쓴다). 포트는 기본 `1883`.
- 노드는 `zoneA/sensor/wl-001/{state,status,heartbeat}`를 발행하고, `terminal/wl-001/*`(명령)도
  건드리지만 ingest가 무시하므로 무해하다.
- **ingest·sink·WS가 먼저 떠 있는 상태에서 노드를 켠다**(제약 11). 노드 접속 직후 `status`
  birth가 retained로 오고, 이어 `state`/`heartbeat`가 흐른다.
- Kafka 토픽·sink 기록처럼 서버 localhost에서만 보이는 것은 사람이 서버에서 확인해 결과를 회수한다.

**DoD:** `state`·`status`·`heartbeat`가 Kafka 3토픽 + 저장 sink + WS에 관통한다(발행은 컴퓨터→서버
Mosquitto 경로). 4개 편집 덕분에 봉투 strict 검증을 통과한다(격리로 안 빠진다).

### 단계 7 — 조병현 인계 문서 작성 (= `BACKEND_AGENDA §1·§2 회신`)

(A) 검증이 끝난 뒤(잘 되는 것을 확인한 뒤) HW 팀원(조병현)에게 전달할 문서를 만든다 — 예:
`docs/be/hw-envelope-conformance.md`. HW는 미결을 `docs/BACKEND_AGENDA.md`(HW 브랜치)로 정리해
두었으므로, 이 문서는 그 **§1(스키마 필드 확정)과 §2(토픽·Kafka 매핑)에 대한 백엔드 회신** 형태로
**자세히** 쓴다:

- **`§1` 스키마 회신 — 편집 4개(부록 그대로)와 각각의 이유(공통 봉투 계약 정합):**
  - `seq → sequence_id`, timestamp RFC3339 콜론 오프셋, `LEGACY_DEVICE_ID=False`, `SCHEMA_VERSION="1.0"`.
  - **`schema_version` 표기 규칙 명시(HW 질문 §1.2 "semver? 정수?"에 대한 답):** `MAJOR.MINOR`
    **문자열**, 현재 값 `"1.0"`(백엔드 소유 봉투 계약 버전이지 펌웨어 버전 아님 — 펌웨어는
    `fw_version` 별도). HW의 `1.3`은 드리프트라 `1.0`으로 맞춘다.
  - **`seq`(→`sequence_id`) 범위(HW 질문 §1.3에 대한 답):** 현재 **채널별 독립 순번**을 그대로
    수용한다. 유실·역전 검출의 정확한 의미(채널별/소스별)는 **Phase 2에서 확정**한다. Phase 1은
    값을 실어 나르기만 한다.
- **`§2` 토픽 회신(HW엔 대부분 정보성 — HW는 MQTT만 발행):**
  - MQTT 토픽 구조 `{zone}/{etype}/{eid}/{channel}` 유지. etype 어휘 `{sensor,robot,actuator,analysis}` 확인.
  - **MQTT→Kafka 매핑(BE 내부, §2.4 답):** 원본 미러가 **아니라** 채널별 `mk2.telemetry.<채널>`,
    파티션 키 `source_id`. HW 코드 변경 불필요.
- **주의(device_id 제거의 영향 — 완화됨):** `LEGACY_DEVICE_ID=False`는 `device_id` 별칭을 없앤다.
  **`pi/edge/monitor.py`는 이미 `source_id`를 우선 읽고 device_id는 폴백이라 안전하다**(확인함).
  다만 **그 외에** `device_id`를 직접 읽는 HW 내부 소비자가 있으면 함께 갱신하라고 안내한다.

**DoD:** 문서가 존재하고 위(§1 편집·이유·표기·seq / §2 토픽·Kafka 매핑 / device_id 주의)를 담는다.

---

## 6. 이번에 하지 않는 것 (범위 울타리)

- **명령 경로(protobuf `terminal/*`)** → **Phase 6**. Kafka `mk2.command.*` 토픽·protobuf 계약
  정합은 그때. Phase 1 ingest는 `terminal/#`을 구독하지 않는다.
- **실제 TSDB 제품·스키마·retention** → **Phase 2**. Phase 1은 `store(...)` 인터페이스 뒤
  placeholder까지. spool이 붙이는 `replayed:true`의 지연 도착 정합도 Phase 2.
- **관측 logs/traces 파이프라인·페더레이션** → **Phase 3**(Collector가 log→Loki·trace→Tempo
  분배, Loki retention 등).
- **미디어 경로** → **Phase 4**.
- **가용성 판정(LWT·heartbeat 통합, 세션 우선)** → **Phase 5**. Phase 1은 `status`·`heartbeat`를
  흘려보내기만 하고 판정하지 않는다.
- **채널 본문(payload) 스키마 검증** → 채널 payload 스키마 작성 후. Phase 1은 봉투만 검증.
- **Kafka 원격 노출** → 원격 엣지/Tailscale 도입 시(≈Phase 4). 이번엔 localhost·`127.0.0.1:9092`
  그대로. (미래작업: 아래.)
- **인증·TLS·ACL·Mosquitto persistence** → 운영 전환/후속.
- **파티션 증설·`etype` 분할 토픽**(`mk2.telemetry.sensor.state` 식) → 규모가 요구할 때.

**HW 브랜치 전수조사(2026-09-07)로 확인된 이월 — Phase 1 무관, 해당 Phase에서 처리:**
- **frame_ref 계약 정합 → Phase 4(미디어).** 우리 `contracts/common/frame-reference.schema.json`은
  `capture_timestamp`를 **ISO date-time 문자열**로 정의했는데, HW/v8 §6-9 구현은 **epoch ms 정수**다
  (`BACKEND_AGENDA §8`이 "봉투 timestamp(ISO)와 frame_ref(epoch ms) 공존이 의도냐" 질의). 미디어
  착수 전 계약을 어느 쪽으로 정합할지 결정.
- **명령 문자열 파라미터 → Phase 6.** `sensor_node`의 `set_mode(mode="normal")`·`levee(position="open")`는
  문자열 파라미터인데 protobuf 명령은 `map<string,double>`이라 현재 호출 불가(`BACKEND_AGENDA §3`).
  명령 스키마에 문자열/열거형 파라미터 지원 추가.
- **엣지 가용성 판정 ↔ BE 최종 판정 → Phase 5.** HW엔 `pi/edge/monitor.py`·`edge/availability.py`가
  엣지에서 up/offline을 판정한다. BE-T-04는 "백엔드 단일 지점 최종 판정, 업무 평면 우선"이므로,
  엣지 1차 판정과 BE 최종 판정의 관계를 Phase 5에서 정리한다.
- **device_status 발행 주체 → Phase 5.** HW가 ok/degraded/fault를 자기보고(`BACKEND_AGENDA §5`).
  BE가 이를 수용할지, metric/log에서 파생할지 결정.

> **미래작업(원격 Kafka 노출 시 정확히 바꿀 3가지, 지금은 하지 않음):**
> ① 포트 바인딩 `127.0.0.1:9092:9092` → Tailscale 인터페이스 IP 바인딩(공인 `0.0.0.0` 노출 회피,
> Tailscale 설치 선행). ② `KAFKA_ADVERTISED_LISTENERS`의 PLAINTEXT 호스트 `localhost` → 엣지가
> 실제 도달하는 그 주소. ③ ufw `9092 ALLOW Anywhere` → 엣지 소스로 제한(단 docker publish는
> DNAT라 ufw INPUT을 상당부분 우회 → 실질 통제는 ①의 인터페이스 바인딩).

---

## 7. 완료 판정 (체크리스트)

아래가 전부 참이어야 이 작업이 끝난 것이다.

- [ ] 단계 0: 서버 상태가 확정 기준선과 일치(Kafka healthy·`127.0.0.1:9092`·advertised localhost /
      Mosquitto 1883 익명), **그리고 컴퓨터→서버 `210.110.250.33:1883` 도달 확인**(제약 12).
- [ ] 단계 1: `mk2.telemetry.{state,status,heartbeat}` 3토픽 존재(파티션 1·RF 1).
- [ ] 단계 2: ingest가 고유 client_id로 3패턴 구독, 봉투 strict 검증(포맷 포함), 불합격 격리·기록,
      합격은 `key=source_id`로 매칭 토픽에 produce. (구독 즉시 오는 retained `status` 1건은 정상.)
- [ ] 단계 3: 저장 sink(그룹 `mk2-storage`)가 `store(...)`로 수신 기록.
- [ ] 단계 4: WS echo(그룹 `mk2-ws`)가 클라이언트에 push, 최소 클라이언트로 값 확인.
- [ ] 팬아웃: 저장·WS 두 그룹이 같은 메시지를 각자 독립 수신.
- [ ] 단계 5: `pytest` 양성(왕복) + 음성(격리) + WS 도달 통과. **발행(컴퓨터)은 ingest 구독이
      올라온 뒤** 이뤄진다(제약 11).
- [ ] 단계 6: 실노드(로컬 4편집, 컴퓨터 실행→서버 브로커)의 `state`/`status`/`heartbeat`가
      Kafka+sink+WS로 관통(ingest·sink·WS를 먼저 띄운 뒤 노드 실행).
- [ ] 단계 7: 조병현 인계 문서 작성(편집 4개·이유·내부 소비자 주의).
- [ ] 비밀값·`infra/docker-compose.yml`·내부망 IP 미커밋, LF·UTF-8, 격리 파일·`venv_phase1` gitignore.

**검증 수단:** 자동은 pytest(단계 5), 실노드 통합(단계 6)은 수동 확인 후 보고서에 기록. **완료
판정은 특정 기술 사용 여부가 아니라 동작·경계가 실제로 보장되는지로 한다**(테스트 없는 완료 금지,
음성 대조 필수 — CLAUDE.md §3).

---

## 8. 보고 (작업 끝에 남기는 것) — 반드시

- **`reports/YYYY-MM-DD_HHMM_phase1_얇은파이프라인관통.md`** 생성 — 배경 / 한 일 / 검증 / 다음.
- **`docs/be/requirement-traceability.md` 갱신** — 이 Phase가 건드린 요구사항의 상태·구현 위치·
  테스트·gap:
  - **BE-C-01** — 구현 위치 `backend/ingest/`(봉투 수신 검증). 테스트: 봉투 검증 격리(양성+음성).
    상태는 실제 테스트 커버리지대로(수신 검증·격리가 테스트로 보장되면 그 범위에서 완료; 식별자
    레지스트리 소비 BE-C-02는 여전히 미착수).
  - **BE-T-01** — 구독·발행 수용 동작. gap: LWT·인증·ACL 미구현(부분 유지).
  - **BE-T-02** — MQTT→Kafka 브릿지 왕복(테스트로 보장 시 완료 판단). gap: advertised가 localhost
    라 원격 미지원(미래작업).
  - **BE-T-03** — WS echo(부분). gap: 구독 관리·인증·재접속 캐시·명령 번역 없음(Phase 5/7).
  - **BE-S-01** — `store(...)` 인터페이스 + placeholder 소비자 수신(부분). gap: 실제 TSDB 제품·
    스키마·시각 정렬·`replayed` 정합은 Phase 2.
- **`docs/be/01-standalone-implementation-plan.md` 갱신** — "지금 당장 할 일" ③(Phase 1) 체크,
  그리고 **발견/이월사항을 그 조치가 이뤄질 미래 Phase 항목에** 적는다:
  - Phase 2: `store(...)` 인터페이스 뒤에 TSDB 구현 교체, `replayed:true` 지연 도착 정합,
    `sequence_id`(채널별) 기반 유실·역전 검출 의미 확정.
  - Phase 4: 원격 Kafka 노출 3수정(§6 미래작업, Tailscale 선행), **frame_ref 계약 정합**
    (`frame-reference.schema.json` ISO 문자열 ↔ HW/v8 epoch ms).
  - Phase 5: **엣지 가용성 판정(`monitor.py`·`edge/availability.py`) ↔ BE 최종 판정 관계 정리**,
    **device_status 발행 주체**(HW 자기보고 수용 vs metric 파생).
  - Phase 6: 명령 경로 protobuf 토픽(`mk2.command.*`)·`PhysicalCommandEnvelope` 계약 정합,
    **문자열/열거형 파라미터 지원**(`set_mode`·`levee`가 `map<string,double>`로 불가).
- **크로스파트 의존:** HW 봉투 정합(편집 4개)은 조병현이 HW repo에 적용한다 — 인계 문서로 전달
  했음을 보고서에 남긴다.
- 막히거나 결정이 필요하면 **임의로 정하지 말고** `reports/`에 남기고 멈춘다(§1-A 규율 7).

---

## 부록 — `common/schema.py` 정확한 편집 4개

**용도:** 단계 6에서 **로컬 사본**에 적용해 실노드를 검증하고, 단계 7에서 조병현 인계 문서의 내용이
된다. HW repo에 직접 커밋하지 않는다(적용은 조병현). 편집은 전부 `envelope()`·`iso_now()`·모듈
상단 플래그에 있다.

**① 순번 필드명 `seq` → `sequence_id`** (계약은 `sequence_id`; 안 맞추면 순번 추적이 조용히 죽음)

```python
# before
if seq is not None:
    env["seq"] = seq
# after
if seq is not None:
    env["sequence_id"] = seq
```

**② timestamp를 RFC3339 콜론 오프셋으로** (`strftime("%z")`는 `+0900`을 내는데 `date-time` 포맷은
`+09:00`을 요구 → strict 검증에서 거부됨)

```python
# before
import time
def iso_now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")
# after
from datetime import datetime, timezone
def iso_now():
    # 로컬 타임존 aware → 콜론 있는 오프셋(+09:00). RFC3339/계약 date-time 정합.
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
```

**③ `device_id` 별칭 제거** (HW 내부 `pi/edge/monitor.py`는 `source_id`를 우선 읽고 device_id는
폴백이라 이 제거에 안전함 — 확인함. 그 외 device_id 직접 소비자만 조병현이 확인)

```python
# before
LEGACY_DEVICE_ID = True
# after
LEGACY_DEVICE_ID = False
```

**④ 봉투 계약 버전을 계약값으로** (계약 현재 버전 `1.0`. HW의 `1.3`은 드리프트이며, 이는 봉투
계약 버전이지 펌웨어 버전이 아니다 — 펌웨어는 `fw_version` 별도)

```python
# before
SCHEMA_VERSION = "1.3"
# after
SCHEMA_VERSION = "1.0"
```

> 편집 후 `state`/`heartbeat`는 `sequence_id`를 싣고(선택 필드), `status`·LWT는 순번 없이 나간다
> (정상 — 봉투 필수 5필드만 있으면 통과). `source_id`가 항상 있어 Kafka 파티션 키로 쓸 수 있다.
