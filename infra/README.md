# infra — 인프라 스택 운영 메모

Phase 0(인프라 기동)에서 세운 스택의 현재 상태와 운영 방법. 작업 경위와 그때의 판단은
[`reports/2026-09-04_1620_phase0_인프라기동.md`](../reports/2026-09-04_1620_phase0_인프라기동.md)에
있다. 이 문서는 **계속 갱신되는 현재 상태**, 보고서는 **그 시점의 스냅샷**이다.

---

## 1. 이 폴더의 성격

| 경로 | 내용 | 커밋 |
|---|---|---|
| `docker-compose.yml` | **서버 compose 파일의 작업본** | ❌ `.gitignore` |
| `config/` | 서버 설정 파일 5개 사본 (mosquitto·otel-collector·prometheus·loki·tempo) | ❌ `.gitignore` |
| `README.md` | 이 문서 | ✅ |

**커밋하지 않는 이유:** compose에 평문 비밀번호가, `prometheus.yml` 주석에 내부망 IP가 들어
있다. 이 저장소는 Public이다.

### 작업 흐름 — `git pull`로 배포하지 않는다

```
[작업 폴더]  infra/ 에서 편집
     ↓  사람이 복사
[서버]      compose 디렉터리의 실제 파일에 붙여넣고 적용
     ↓  결과·에러를 가져옴
[작업 폴더]  수정
```

서버에 저장소를 clone해서 `git pull`로 배포하는 방식이 **아니다.** 서버 실제 파일의 사본을
여기 두고 편집한 뒤, 필요한 부분만 사람이 서버에 옮긴다.

---

## 2. 스택 8개 — 신규 설치 vs 기존 가동

Phase 0 시점(2026-09-04) 기준.

| 구성요소 | 역할 (5구간) | 처리 |
|---|---|---|
| **Kafka** | 엣지↔서버 업무 백본 + 서버 다중 소비자 팬아웃 | **신규 설치** |
| Mosquitto | 엣지 MQTT 브로커, 말단 발행 수용 | 기존 가동 — 헬스 확인만 |
| OTel Collector | 관측 3종 수집·라우팅 | 기존 가동 — 헬스 확인만 |
| Prometheus | 관측 metric 저장·요약 | 기존 가동 — 헬스 확인만 |
| Grafana | 개발용 종착지 | 기존 가동 — 헬스 확인만 |
| Loki | log 저장 | 기존 가동 — 헬스 확인만 |
| Tempo | trace 저장 | 기존 가동 — 헬스 확인만 |
| MySQL | 감사·레지스트리 (2축 중 관계형) | 기존 가동 — 헬스 확인만 |

- **TSDB 없음** — 제품(InfluxDB vs TimescaleDB) 미확정. Phase 2에서 정한다.
- **RBAC·MongoDB 없음** — 정본 결정(CLAUDE.md 원칙 4).
- 서버 compose에는 MK2 스택 외의 서비스도 함께 들어 있다. **다른 파트가 쓰고 있을 수 있으므로
  건드리지 않는다.**

---

## 3. 포트

| 서비스 | 외부 | 내부 | 비고 |
|---|---|---|---|
| Mosquitto | 1883 | 1883 | 모든 인터페이스. 익명 접속 허용 |
| **Kafka** | **127.0.0.1:9092** | 9092 | 로컬 전용(현재 클라이언트가 전부 서버 안). 서버 밖 클라이언트가 생기면 변경 — 예상 시점 Phase 4 (§5) |
| Kafka (controller) | — | 9093 | KRaft 합의용, 미공개 |
| Kafka (internal) | — | 9094 | 같은 docker 네트워크 컨테이너용, 미공개 |
| MySQL | 7858 | 3306 | |
| Prometheus | 7861 | 9090 | |
| Grafana | 7862 | 3000 | |
| Loki | 3100 | 3100 | |
| Tempo | 3200 | 3200 | 조회용 |
| Tempo (OTLP) | 4317 | 4317 | **Tempo가 OTLP를 직접 수신** |
| **OTel Collector** | **127.0.0.1:4316** | 4317 | **4317을 Tempo가 이미 점유해 4316을 쓴다** |
| OTel Collector (exporter) | — | 8889 | Prometheus가 docker 네트워크 안에서 직접 scrape |

### 4316 / 4317 사연

OTLP gRPC 표준 포트는 4317인데, **Tempo가 그 포트를 직접 받고 있다.** 그래서 OTel Collector가
4316으로 밀렸다. 포트 충돌은 증상이고, 원인은 **"Collector를 거치지 않고 Tempo가 직접 받는
구조"**다. 정본(아키텍처 §5-3·§6-3)은 Collector가 log→Loki, trace→Tempo로 분배하는 구조이며,
이 정리는 **Phase 3**에서 한다.

**지금 계측을 보낼 때는 `localhost:4316`이 Collector, `localhost:4317`이 Tempo다.**

---

## 4. 기동 · 헬스 확인

### 기동

```bash
# 서버의 compose 디렉터리에서
docker compose up -d kafka
docker compose ps kafka
```

> ⚠️ **서비스 이름을 반드시 명시한다.** `docker compose up -d`만 치면 compose 파일의 모든
> 서비스가 대상이 되고, `:latest` 태그를 쓰는 기존 서비스들이 이미지 갱신 시 **재생성**될 수
> 있다. 이미 도는 것을 건드리지 않는 것이 이 스택의 원칙이다.

### 헬스 확인 (8개)

```bash
# 1. Kafka — 토픽 생성 → 조회 → 삭제
docker exec capstone_kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 \
  --create --topic healthcheck.phase0 --partitions 1 --replication-factor 1
docker exec capstone_kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list
docker exec capstone_kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 \
  --delete --topic healthcheck.phase0

# 2. Mosquitto
docker exec capstone_mosquitto mosquitto_pub -h localhost -t 'phase0/health' -m 'ok' && echo "MQTT OK"

# 3. MySQL (컨테이너 안 환경변수를 써서 비밀번호가 셸 히스토리에 남지 않게)
docker exec capstone_mysql sh -c 'mysqladmin ping -uroot -p"$MYSQL_ROOT_PASSWORD"'

# 4. Prometheus
curl -s localhost:7861/-/healthy
curl -s 'localhost:7861/api/v1/targets' | python3 -m json.tool | grep -E '"(job|health)"'

# 5. Grafana
curl -s localhost:7862/api/health

# 6. Loki
curl -s localhost:3100/ready

# 7. Tempo
curl -s localhost:3200/ready

# 8. OTel Collector
ss -tulpn | grep 4316
docker logs --tail 20 capstone_otel_collector
```

**Phase 0은 헬스체크로 판정한다(pytest 아님).** Phase 1부터 pytest를 쓴다.

---

## 5. Kafka 설정값과 근거 · 언제 바꾸나

다른 7개는 기존 설정을 그대로 쓰므로 Kafka만 적는다.

| 설정 | 값 | 근거 | 언제 바꾸나 |
|---|---|---|---|
| `KAFKA_NODE_ID` | `1` | 단일 노드 | 브로커 추가 시 |
| `KAFKA_PROCESS_ROLES` | `broker,controller` | KRaft 겸용, ZooKeeper 불필요 | 노드 분리 시 |
| `KAFKA_CONTROLLER_QUORUM_VOTERS` | `1@localhost:9093` | 투표자가 자기 자신뿐 | 브로커 추가 시 |
| `KAFKA_LISTENERS` | `PLAINTEXT :9092`<br>`CONTROLLER :9093`<br>`INTERNAL :9094` | 외부 / KRaft 합의 / docker 네트워크 내부 | — |
| **`KAFKA_ADVERTISED_LISTENERS`** | `PLAINTEXT://localhost:9092`<br>`INTERNAL://kafka:9094` | 브로커가 클라이언트에게 알려주는 자기 주소 | **서버 밖 클라이언트가 생길 때**(원격 엣지 등) — 예상 Phase 4, 아래 주의 참조 |
| 복제 인자 4종 | 전부 `1` | 기본값 3이면 내부 토픽 생성이 즉시 실패 | 브로커 추가 시 |
| `KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS` | `0` | 기본 3000ms 대기가 개발 중 불편 | 운영 전환 시 상향 |
| `KAFKA_LOG_DIRS` | `/var/lib/kafka/data` | 기본값 `/tmp/...` 회피 | — |
| `KAFKA_LOG_RETENTION_HOURS` | `168` (7일) | **Kafka는 장기 저장소가 아니다**(원칙 11). 단기 버퍼·단기 replay용 | 디스크·replay 요구에 따라 |
| `KAFKA_AUTO_CREATE_TOPICS_ENABLE` | `"false"` | 오타 토픽이 자동 생성되면, 발행자는 성공했다고 믿는데 아무도 안 읽는 상황이 생긴다 | 유지 권장 |
| `ports` | `127.0.0.1:9092:9092` | Phase 0은 로컬 헬스체크, Phase 1은 Kafka에 붙는 코드가 전부 서버에 있어 노출 불필요 | **서버 밖 클라이언트가 생길 때** — 예상 Phase 4 |

### 토픽 (Phase 1에서 생성)

`AUTO_CREATE_TOPICS_ENABLE=false`라 명시적으로 만든다. 현재 존재하는 MK2 토픽:

| 토픽 | 파티션 | 복제 | 무엇 |
|---|---|---|---|
| `mk2.telemetry.state` | 1 | 1 | 계측값(수위 등) |
| `mk2.telemetry.status` | 1 | 1 | 등록·상태 요약·종료·LWT |
| `mk2.telemetry.heartbeat` | 1 | 1 | 생존 신호 |

채널별 3토픽이며 **장치별·구역별 토픽이 아니다** — `zone_id`·`source_id`는 봉투 안에 있다.
파티션 키는 `source_id`(장치별 순서 보장). 이름은 점 구분 소문자이며 **언더스코어를 섞지 않는다**
(생성 시 뜨는 `.`/`_` 경고는 둘을 섞을 때의 충돌을 알리는 것이라 점만 쓰는 현 규약에서는 무해).

```bash
docker exec capstone_kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list
```

### ⚠️ 외부에서 Kafka에 붙으려면 — 포트만 열어서는 안 된다

Kafka 연결은 2단계다.

```
1) 클라이언트 → 서버:9092         "브로커 어디 있어?"
2) 브로커 → 클라이언트            "나한테 오려면 <advertised 주소>로 와"
3) 클라이언트 → <advertised 주소>  실제 데이터 송수신
```

`KAFKA_ADVERTISED_LISTENERS`가 지금 `localhost:9092`라서, 외부 클라이언트가 서버 주소로 붙어도
브로커가 **"localhost로 오라"**고 답하고 클라이언트는 자기 자신을 찾아가 실패한다.

#### 지금 이 값인 이유 (Phase 1 시점의 상태)

Phase 1에서는 그대로 두었다. 근거: Kafka에 붙는 코드(`ingest`·저장 sink·WS 게이트웨이)가 **전부
서버 안**에 있고, 바깥에서 오는 것은 MQTT를 쓰는 발행자뿐이었다. 발행자는 Kafka를 모르므로
**Kafka는 서버 localhost 전용으로 충분**했고, 이 구성으로 실노드 관통·pytest 회귀가 통과했다
([`../reports/2026-09-07_1300_phase1_얇은파이프라인관통.md`](../reports/2026-09-07_1300_phase1_얇은파이프라인관통.md)).

> **이건 "영구 고정"이 아니라 "지금 조건에서는 불필요"라는 뜻이다.** 정본 아키텍처(§5-1·§6-1)는
> 엣지↔서버 Kafka 백본을 전제하므로 **노출 변경은 예정된 일**이다. 이 절은 변경을 막는 것이
> 아니라 **바꿀 때 안전하게 바꾸는 방법**을 적어둔 것이다.

**바꿔야 하는 조건 — 페이즈 번호가 아니라 이 조건이 기준이다.** 아래 중 하나라도 생기면 시점이
Phase 4보다 이르더라도 바꾼다(그때 이 문서를 갱신한다).

- 원격 엣지가 Kafka에 직접 붙는다 (가장 흔한 경우, 예상 Phase 4)
- 다른 파트(AI·가시화)의 소비자가 **서버 밖에서** Kafka에 붙어야 한다
- 브로커나 소비자를 다른 호스트로 옮긴다

반대로 **서버 안에서만 붙는 소비자가 늘어나는 것은 변경 사유가 아니다** — 컨슈머 그룹만 추가하면
된다(Phase 2의 TSDB writer, Phase 5·6의 소비자 등이 여기 해당한다).

#### 바꿀 때 정확히 이 3가지 (예상 시점: Phase 4, 원격 엣지·Tailscale)

포트만 열어서는 안 되고, **열더라도 모든 인터페이스에 열면 안 된다**(현재 PLAINTEXT·인증 없음).

1. **`ports` → Tailscale 인터페이스 IP에 바인딩** (`<tailscale-ip>:9092:9092`). `9092:9092`는
   공인 IP를 포함한 전 인터페이스 노출이라 쓰지 않는다. Tailscale 설치가 선행돼야 한다.
2. **`KAFKA_ADVERTISED_LISTENERS`의 `PLAINTEXT` 호스트** → 엣지가 실제로 도달하는 그 주소
   (위 1의 주소). 이걸 안 바꾸면 포트를 열어도 위 2단계 연결에서 실패한다.
3. **ufw를 엣지 소스로 제한.** 단 **docker publish는 DNAT라 ufw INPUT을 상당부분 우회**하므로,
   실질적인 통제는 3이 아니라 **1의 인터페이스 바인딩**이다. ufw는 보조 수단으로 본다.

(현재 ufw에 `9092 ALLOW Anywhere` 규칙이 있으나 바인딩이 `127.0.0.1`이라 실제 노출은 없다.)

### 데이터 디렉터리 권한

`apache/kafka` 이미지는 컨테이너 안에서 **uid 1000(appuser)**으로 돈다. 서버 작업 계정의 uid가
다르면 그냥 `mkdir`한 폴더에 컨테이너가 쓰지 못해 기동이 실패한다.

```bash
mkdir -p kafka_data
sudo chown -R 1000:$(id -g) kafka_data   # 소유자=컨테이너 appuser, 그룹=작업 계정
chmod 775 kafka_data
```

---

## 6. 알려진 사항 — 조치는 해당 Phase에서

Phase 0에서 고칠 것은 없다. 아래는 설정 파일에서 확인한 사실과 처리 시점이다.

| 파일 | 확인된 것 | 언제 |
|---|---|---|
| `otel-collector-config.yaml` | **`logs`·`traces` 파이프라인이 없다 (metric만).** Loki·Tempo가 각각 직접 수신하고 있어 정본(Collector가 분배)과 다르다 | **Phase 3 핵심** |
| `otel-collector-config.yaml` | `batch` processor 없음 — 수신 즉시 export | Phase 3 |
| `prometheus.yml` | `global.scrape_interval: 1s` — 정본이 상정한 15초~1분과 다르다. **바꾸면 기존 대시보드 해상도가 떨어지므로 단독 변경 불가** | 근거 확보됨 — 정본 BE-S-03(요약 15초) + 타 파트 문서화(일반 metric 60초). Phase 3에서 조정. 기존 대시보드 해상도 영향은 사전 고지 후 진행 |
| `prometheus.yml` | 페더레이션 없음 (단일 Prometheus) | Phase 3 |
| `loki-config.yaml` | **retention 없음 → 로그가 무제한으로 쌓인다.** 로그를 흘리기 **전에** 걸어야 한다. 흘린 뒤 걸면 이미 쌓인 것은 안 지워진다 | **Phase 3, 순서 주의** |
| `loki-config.yaml` | schema v11 + boltdb-shipper (Loki 3.x 기준 구식). `allow_structured_metadata: false`로 호환 유지 중이며 동작에 문제는 없다 | 필요해지면 |
| `tempo-config.yaml` | OTLP 직접 수신 (4317/4318) — 위 4316/4317 사연의 원인 | Phase 3 |
| `tempo-config.yaml` | `block_retention: 24h` — trace가 하루만 남는다 | Phase 3 |
| `mosquitto.conf` | `allow_anonymous true`, ACL 없음. 개발 단계라 의도된 상태이며 **Phase 1 브릿지 연결에는 오히려 유리하다** | 운영 전환 시 |
| `mosquitto.conf` | `persistence` 미설정 → 브로커 재시작 시 retained 소실 | Phase 1/5 |
| (요구사항) | **가용성 판정 파라미터** — 하트비트 1초 1회, **4회 연속 미수신(약 4초)** 시 장애 판정. 정본은 조병현 HW-S-05·HW-A-05이며 김현우 VZ-U-01도 4초 판정을 전제한다. **Phase 1 실측 5초는 테스트 편의값이지 요구사항이 아니다** | Phase 5 |

관측 3종의 현재 실제 경로:

| 신호 | 정본 경로 | 현재 실제 |
|---|---|---|
| metric | Collector → Prometheus | ✅ 그대로 |
| trace | Collector → Tempo | ❌ 애플리케이션 → **Tempo 직접** |
| log | Collector → Loki | ❌ Collector에 Loki exporter 없음 |
