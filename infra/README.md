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
| **Kafka** | **127.0.0.1:9092** | 9092 | 로컬 전용. Phase 1에서 변경 (§5) |
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
| **`KAFKA_ADVERTISED_LISTENERS`** | `PLAINTEXT://localhost:9092`<br>`INTERNAL://kafka:9094` | 브로커가 클라이언트에게 알려주는 자기 주소 | **Phase 1 — 아래 주의 참조** |
| 복제 인자 4종 | 전부 `1` | 기본값 3이면 내부 토픽 생성이 즉시 실패 | 브로커 추가 시 |
| `KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS` | `0` | 기본 3000ms 대기가 개발 중 불편 | 운영 전환 시 상향 |
| `KAFKA_LOG_DIRS` | `/var/lib/kafka/data` | 기본값 `/tmp/...` 회피 | — |
| `KAFKA_LOG_RETENTION_HOURS` | `168` (7일) | **Kafka는 장기 저장소가 아니다**(원칙 11). 단기 버퍼·단기 replay용 | 디스크·replay 요구에 따라 |
| `KAFKA_AUTO_CREATE_TOPICS_ENABLE` | `"false"` | 오타 토픽이 자동 생성되면, 발행자는 성공했다고 믿는데 아무도 안 읽는 상황이 생긴다 | 유지 권장 |
| `ports` | `127.0.0.1:9092:9092` | Phase 0은 로컬 헬스체크만 필요 | **Phase 1** |

### ⚠️ 외부에서 Kafka에 붙으려면 — 포트만 열어서는 안 된다

Kafka 연결은 2단계다.

```
1) 클라이언트 → 서버:9092         "브로커 어디 있어?"
2) 브로커 → 클라이언트            "나한테 오려면 <advertised 주소>로 와"
3) 클라이언트 → <advertised 주소>  실제 데이터 송수신
```

`KAFKA_ADVERTISED_LISTENERS`가 지금 `localhost:9092`라서, 외부 클라이언트가 서버 주소로 붙어도
브로커가 **"localhost로 오라"**고 답하고 클라이언트는 자기 자신을 찾아가 실패한다.

**Phase 1에서 엣지를 붙이려면 둘 다 바꿔야 한다:**
1. `ports` → `9092:9092`
2. `KAFKA_ADVERTISED_LISTENERS`의 `PLAINTEXT` 호스트 → 엣지가 실제로 도달할 수 있는 서버 주소

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
| `prometheus.yml` | `global.scrape_interval: 1s` — 정본이 상정한 15초~1분과 다르다. **바꾸면 기존 대시보드 해상도가 떨어지므로 단독 변경 불가** | Phase 3, 팀원 합의 후 |
| `prometheus.yml` | 페더레이션 없음 (단일 Prometheus) | Phase 3 |
| `loki-config.yaml` | **retention 없음 → 로그가 무제한으로 쌓인다.** 로그를 흘리기 **전에** 걸어야 한다. 흘린 뒤 걸면 이미 쌓인 것은 안 지워진다 | **Phase 3, 순서 주의** |
| `loki-config.yaml` | schema v11 + boltdb-shipper (Loki 3.x 기준 구식). `allow_structured_metadata: false`로 호환 유지 중이며 동작에 문제는 없다 | 필요해지면 |
| `tempo-config.yaml` | OTLP 직접 수신 (4317/4318) — 위 4316/4317 사연의 원인 | Phase 3 |
| `tempo-config.yaml` | `block_retention: 24h` — trace가 하루만 남는다 | Phase 3 |
| `mosquitto.conf` | `allow_anonymous true`, ACL 없음. 개발 단계라 의도된 상태이며 **Phase 1 브릿지 연결에는 오히려 유리하다** | 운영 전환 시 |
| `mosquitto.conf` | `persistence` 미설정 → 브로커 재시작 시 retained 소실 | Phase 1/5 |

관측 3종의 현재 실제 경로:

| 신호 | 정본 경로 | 현재 실제 |
|---|---|---|
| metric | Collector → Prometheus | ✅ 그대로 |
| trace | Collector → Tempo | ❌ 애플리케이션 → **Tempo 직접** |
| log | Collector → Loki | ❌ Collector에 Loki exporter 없음 |
