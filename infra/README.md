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
| `sql/` | MK2 스키마 DDL 2 + 권한 템플릿 2 (**Phase 2 신설**) | ✅ (단 실제 비밀번호가 든 `mk2_grants_*.sql`은 ❌) |
| `systemd/` | 백엔드 상주 3개 unit (`mk2-ingest`·`mk2-storage-consumer`·`mk2-ws-echo`) (**Phase 3 신설**) | ✅ — 비밀값 없음, `.env` **경로**만 참조 |

**커밋하지 않는 이유:** compose에 평문 비밀번호가, `prometheus.yml` 주석에 내부망 IP·Tailscale 주소가 들어
있다. 이 저장소는 Public이다.

### 서버 쪽 — 저장소 밖에 있는 것 (Phase 2 신설)

| 경로 | 내용 |
|---|---|
| **`/home/dg/capstone-db/.env`** | `MK2_TSDB_ROOT_PASSWORD`·`MK2_TSDB_PASSWORD`·`MK2_MYSQL_PASSWORD` 3개. `-rw-------`(600), 소유자 `dg`, **영숫자 32자**(특수문자 금지 — 아래 파서 셋의 인용부호 규칙이 달라 한쪽만 다르게 읽는다) |
| `/home/dg/capstone-db/mk2_sql/` | 위 `sql/`의 서버 사본(사람이 root로 적용) |
| `/etc/systemd/system/mk2-*.service` | 위 `systemd/`의 설치본(**Phase 3**). 저장소 사본 `…/Physical-Project-mk2/infra/systemd/`에서 `sudo cp` |
| `/home/dg/capstone-db/phase1_work/phase3_new/` | Phase별 설정 대기 위치(컴퓨터에서 올린 파일을 여기 두고 블록이 `config/`로 옮긴다). 다음 Phase는 `phase4_new/` |
| **`tailscaled`** (시스템 패키지) | **Phase 3 설치**. 1.102.4, enabled, **팀 공용 계정** 로그인. 서버 주소는 `tailscale ip -4` / `_serverinfo/260916_phase3_tailscale.txt`. **되돌리지 않았다 — Phase 4(미디어·Kafka 원격 노출)가 그대로 쓴다.** 다시 `tailscale up`을 치지 않는다 |

**저장소 밖에 둔 이유:** 이 저장소는 Public이고, compose가 같은 디렉터리의 `.env`를 자동으로
읽으므로 `${MK2_TSDB_ROOT_PASSWORD}` 치환이 그대로 된다. 기존 서비스들은 `${...}`를 안 쓰므로
영향이 없다.

**`.env`를 읽는 파서가 이제 셋이다** (Phase 3에서 systemd가 더해졌다):

| 파서 | 누가 | 인용부호 규칙 |
|---|---|---|
| 셸 `source` | 사람이 pytest·발행자를 돌릴 때 `set -a; . /home/dg/capstone-db/.env; set +a` | 셸 문법 — `$`·따옴표·공백이 해석된다 |
| compose dotenv | `docker compose`가 `${MK2_TSDB_ROOT_PASSWORD}` 치환 | 따옴표를 벗기되 셸과 다르게 |
| **systemd `EnvironmentFile`** | 유닛 3개(`infra/systemd/`) | 따옴표 안의 공백 허용, `\`이스케이프, `$` 미해석 |

값에 특수문자를 넣는 순간 셋 중 하나가 다르게 읽는다 — **영숫자만 쓰는 이유가 하나 더 늘었다.**

> ⚠ **손으로 백엔드를 띄울 때는 환경변수를 먼저 올린다**(systemd 유닛은 `EnvironmentFile`이 대신한다).
> 저장 소비자는 `.env` 없이는 뜨지 않는다(접속 정보가 없으면 **조용히 폴백하지 않고 이름을 대며 죽는다**).
> ```bash
> set -a; . /home/dg/capstone-db/.env; set +a
> ```
> Phase 3부터 상주 3개는 systemd다 — 손으로 띄우기 전에 `sudo systemctl stop mk2-ingest …`로 먼저 내린다
> (ingest는 `client_id=mk2-ingest`가 고정이라 둘이 붙으면 서로 밀어낸다).

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

## 2. 스택 9개 — 신규 설치 vs 기존 가동

Phase 0(2026-09-04)에 8개, **Phase 2(2026-09-10)에 TimescaleDB가 더해져 9개**다.

> ⚠️ **MK2 스택은 9개지만 서버 compose 프로젝트(`capstone-db`)에는 서비스가 13개 있다.**
> 나머지는 다른 파트가 쓰는 것이라 건드리지 않는다. **`docker compose up -d`에는 반드시
> 서비스 이름을 명시한다** — 이름 없이 실행하면 다른 서비스가 재생성될 수 있다.

| 구성요소 | 역할 (5구간) | 처리 |
|---|---|---|
| **Kafka** | 엣지↔서버 업무 백본 + 서버 다중 소비자 구조 | **신규 설치** |
| Mosquitto | 엣지 MQTT 브로커, 말단 발행 수용 | 기존 가동 — 헬스 확인만 |
| OTel Collector | 관측 3종 수집·**분배**(metric→Prometheus·log→Loki·trace→Tempo) | 기존 가동 — **Phase 3이 설정을 처음 고침**(파이프라인 3종, digest 고정) |
| Prometheus | 관측 metric 저장·요약(+페더레이션 중앙) | 기존 가동 — **Phase 3이 `otel_collector` 잡 주기만 5s로**(global 무변경) |
| Grafana | 개발용 종착지 | 기존 가동 — 헬스 확인만 |
| Loki | log 저장 | 기존 가동 — **Phase 3이 v13/tsdb + 보존 14d로 재구성**(데이터 백업 후 비움) |
| Tempo | trace 저장 | 기존 가동 — **Phase 3이 `block_retention` 24h → 168h** |
| MySQL | 감사·레지스트리·임무 실행 기록 (관계형 축) | 컨테이너는 기존 가동 — **Phase 2가 그 안에 `mk2` DB를 신설**(아래 §2-1) |
| **TimescaleDB** | 계측 시계열 저장 (BE-S-01) | **신규 설치 (Phase 2, 2026-09-10)** |

### 2-0. 서버 자원 분류 — "떠 있으니 쓴다"로 가지 않는다 (Phase 3 신설)

서버 compose 프로젝트에는 MK2가 만든 것, 기존 가동인데 MK2가 **역할만 배정한** 것, MK2와 **무관한** 것이
섞여 있다. 역할은 기준 문서(`docs/be/00-architecture.md`)가 먼저 정했고, Phase 0이 이미 있던 컨테이너를 그
역할에 대응시킨 것이다. **분류 ②를 고칠 때는 "지금 누가 쓰나"를 실측하고 근거를 남긴다. 분류 ③은 읽기만.**

| 분류 | 무엇 | 고쳐도 되나 |
|---|---|---|
| **① MK2가 만든 것** | Kafka `capstone_kafka` · TimescaleDB `capstone_timescaledb` · MySQL 안의 `mk2` DB·`mk2_app`·테이블 8 · 토픽 `mk2.telemetry.*` · 컨슈머 그룹 `mk2-*` · systemd 유닛 `mk2-*` 3개 · 백엔드 venv | 자유롭게 |
| **② 기존 가동 + MK2가 역할 배정(공유)** | **OTel Collector · Prometheus · Loki · Tempo** · Grafana · Mosquitto | **근거를 남기고.** Phase 3 근거: Collector 10일간 OTLP 수신 0건·Tempo 이력 전체 trace 0건·Loki 7개월간 로그 0건(2026-09-14 실측) — 잃을 데이터가 없었다. Prometheus만 살아 있었고 그 데이터는 전부 분류 ③의 것이라 global·잡 본문을 건드리지 않았다 |
| **③ MK2와 무관** | Redis · MongoDB · `rpi_pushgateway` · `thermal_pushgateway` · `robot_server` 타깃 · `conntest`(출처 미상) · MySQL 컨테이너 자체(`robot_capstone`) | **설정 무변경.** `prometheus.yml`의 해당 잡 본문은 주석만 고쳤다 |

**컨테이너는 13개**(MK2 스택 9 + 무관 4). `docker compose up -d`·`restart`에 **반드시 서비스 이름**을 붙인다.

- **TSDB 확정 — TimescaleDB**(PostgreSQL 16 확장, Community Edition, 자체 운영). Phase 2에서
  정했다. 배제한 후보와 사유:
  - **InfluxDB 3 Core** — 질의 시간 범위가 기본 약 72시간으로 제한된다(최근·과거 양쪽).
    계측 원본 보존·BE-S-04 장기 보존·되감기와 정면 충돌한다.
  - **InfluxDB 2.9** — 동작은 하나 공식 문서가 v2를 이전 버전으로 표기하고, 조회 어휘가
    SQL이 아니라 MySQL 축과 갈린다.
  - 채택 근거: ① 유실·역전 검출이 전부 윈도우 함수로 풀리는 SQL 문제다 ② 감사·레지스트리·
    실행 기록이 MySQL이라 조회 어휘가 한 벌로 통일된다 ③ 공통 칼럼 + `JSONB` 구조라 채널
    본문 규격 확정 전에도 테이블이 선다.
  - **정직한 약점:** 관계형 엔진이 둘이 된다(MySQL + PostgreSQL). 백업·계정·모니터링이 두
    벌이다. 교체 지점은 `TelemetryWriter.write()` 뒤 하나뿐이라 잠금 범위는 좁다(원칙 1).
  - **이미지는 digest 로 고정한다**(`timescale/timescaledb@sha256:8adb9b8d…`). `latest-pg16`
    은 이동 태그라 같은 이름으로 내용이 바뀐다 — `:latest` 금지와 같은 이유다.
- **MongoDB 없음** — 현재 채택 없음(CLAUDE.md 원칙 4). 영구 배제가 아니라 타당한 근거가
  있을 때 재검토한다.

### 2-1. MySQL 안의 MK2 — 컨테이너는 기존 것, 내용물은 Phase 2가 만들었다 (2026-09-10)

**컨테이너(`capstone_mysql`)는 다른 파트도 쓴다. 건드리지 않았다.** 그 안에 **MK2 전용 DB를
따로 만들었다** — 기존 테스트 DB(`robot_capstone`)에 얹지 않았다.

| 항목 | 값 |
|---|---|
| DB | `mk2` (DB 기본 collation `utf8mb4_0900_ai_ci`) |
| **테이블 collation** | **`utf8mb4_bin`** — 계측 저장소(TimescaleDB)의 `TEXT`가 대소문자를 구별하는데 MySQL `ai_ci`는 안 한다. 한쪽이 `zoneA == zonea`로 보면 두 저장소를 잇는 조회에서 같은 대상이 다르게 취급된다. **테이블을 추가할 때도 반드시 `COLLATE=utf8mb4_bin`을 붙인다** |
| 앱 계정 | `'mk2_app'@'172.18.%'` — 호스트에서 `127.0.0.1:7858`로 붙은 연결이 컨테이너에서는 **`172.18.0.1`로 보인다**(실측). `'…'@'localhost'`는 붙지 못한다 |
| 권한 | **테이블 단위 차등.** DDL(`CREATE`·`ALTER`·`DROP`) **없음** — 코드가 스키마를 바꿀 수 없어야 한다 |
| 테이블 8개 | 레지스트리 선언 축 3(`registry_zone`·`registry_entity_declared`·`registry_node_declared`) · 관측 축 3(`registry_entity_observed`·`registry_node_observed`·`registry_identity_history`) · `audit_log` · `mission_event` |
| **append-only 강제** | `audit_log`·`mission_event`에는 **`SELECT, INSERT`만** 준다. *"수정·삭제하지 않으며"*(BE-S-08)를 **코드 규율이 아니라 DB 권한이** 지킨다 |
| 스키마 적용 | **사람이 MySQL `root`로 1회.** `docker exec -i capstone_mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD"' < mk2_mysql_schema.sql` |
| 시각 | 전부 **UTC를 담은 `DATETIME(6)`**. `TIMESTAMP`는 세션 타임존으로 자동 변환돼 쓰지 않는다(이 서버는 `system_tz=KST`) |

**지우면 안 되는 시드 데이터:** `registry_entity_declared`의 **`wl-002`(미배포)** — *"값을 발행하지
않는 미배포 대상도 목록에 나온다"*(BE-Q-03)를 보이는 근거 행이다.
- **RBAC는 스택 구성요소가 아니다** — 채택은 확정이나 조회·명령 경로의 강제 축이라
  Phase 6(인증·감사)에서 구현한다(BE-Q-04).
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
| MySQL | 7858 | 3306 | `0.0.0.0` 바인딩 — 다른 파트가 쓰는 컨테이너라 이번에 고치지 않는다(Phase 6, 인증·인가와 함께) |
| **TimescaleDB** | **127.0.0.1:7859** | 5432 | 로컬 전용. 붙는 것이 전부 서버 안 호스트 프로세스(저장 소비자·pytest)다. ufw에는 이미 열려 있다(아래 주 참조) |
| Prometheus | 7861 | 9090 | `otel_collector` 잡 5s(Phase 3), global 1s 무변경. 보존은 CLI 기본값 15d |
| Grafana | 7862 | 3000 | |
| Loki | 3100 | 3100 | Collector가 `http://loki:3100/otlp`(도커 망)로 log를 넣는다. 호스트 3100은 조회용 |
| Tempo | 3200 | 3200 | 조회용 |
| Tempo (OTLP) | 4317 | 4317 | Phase 0 유물 — **Collector 우회 입구**. Collector는 도커 망 `tempo:4317`로 넣으므로 호스트 4317은 쓰지 않는다. 닫지 않고 기록만(§6 ⓓ) |
| **OTel Collector** | **127.0.0.1:4316** | 4317 | 백엔드 3개(호스트 프로세스)가 이 길로 metric·log를 낸다. **Tailscale 인터페이스 추가 바인딩은 Phase 3 검증 뒤 주석으로 내렸다**(§6 ⓗ) |
| OTel Collector (exporter) | — | 8889 | Prometheus가 docker 네트워크 안에서 직접 scrape |
| WS echo | 127.0.0.1:8765 | — | 호스트 프로세스(systemd `mk2-ws-echo`). 외부 노출은 Phase 4/5(인증과 한 묶음) |

### 7859 — ufw는 이미 열려 있고, 실질 노출은 없다

**바인딩(`127.0.0.1`)과 방화벽(ufw)은 층이 다르다.** 둘을 같은 것으로 읽으면 판단이 어긋난다.

- **ufw에 7859는 이미 열려 있었다**(2026-09-10 실측 — `ufw status numbered` 규칙 8·23·44).
  Phase 2에서 새로 열 것이 없었다. "서비스의 외부 포트는 ufw에도 반드시 연다"는 방침(§5의
  정정 참조)은 이미 충족된 상태다.
- 그런데도 **실질 노출은 생기지 않는다.** 바인딩이 `127.0.0.1`이라 애초에 loopback에서만
  듣기 때문이다. ufw를 여는 목적은 접근을 만드는 것이 아니라 **장애 시 방화벽을 용의선상에서
  빼는 것**이다.
- **7864는 쓰지 않았다.** 조회 시점엔 비어 있었으나 상시 가동이 아닌 다른 파일이 실행될 때
  점유하는 포트다(사용자 확인). 지금 비어 있다고 잡으면 나중에 충돌한다.

포트를 7859에서 바꿔야 하면 **네 곳을 함께 고친다** — compose · ufw 규칙 · `backend/settings.py`의
`MK2_TSDB_PORT` 기본값 · 위 §3 포트 표.

### 4316 / 4317 — 두 사안으로 가른다

이전 판은 아래 둘을 한 문단에 붙여 두어 *"Phase 3에서 포트를 옮긴다"* 로 읽혔다(실제로 그렇게 읽힌 일이
있었다). **구조와 포트 번호는 별개 사안**이다.

**ⓐ 구조 — Collector가 log·trace를 분배한다 (= Phase 3이 한 일).** Phase 0 시점에는 Tempo가 OTLP 4317을
직접 받고 Loki는 Collector에 exporter가 없어 직접 수신 구조였다. 기준(아키텍처 §5-3·§6-3)은 Collector가
log→Loki·trace→Tempo로 분배하는 것이고, **2026-09-15에 그렇게 고쳤다** — Collector 파이프라인 3종
(`metrics`→prometheus 8889 · `traces`→`otlp_grpc` `tempo:4317` · `logs`→`otlp_http` `http://loki:3100/otlp`).
**Collector→Tempo·Loki는 도커 네트워크 안 서비스 이름으로 가므로 호스트 포트를 거치지 않는다.**

**ⓑ 호스트 포트 번호 — 4316에 둔 채로 둔다 (= 바꾸지 않았고 바꿀 이유가 없다).** 컨테이너 안에서는 Collector도
Tempo도 4317을 듣지만 서로 다른 컨테이너라 겹치지 않는다. 호스트에서 4317은 Tempo가 점유하고 있어 Collector는
4316이며, 백엔드 3개가 `MK2_OTEL_ENDPOINT` 기본값 `http://127.0.0.1:4316`으로 그 길을 쓴다. 포트를 옮기는 것은
ⓐ의 선행 조건이 아니었고(설계 세션에서 검토 후 기각), 옮기면 백엔드 기본값·문서·ufw가 같이 바뀐다.

**지금 계측을 보낼 곳은 `127.0.0.1:4316`(Collector) 하나다.** `4317`(Tempo 직접 수신)은 Phase 0 유물로 열려
있으나 **입구가 아니다** — 닫지 않고 기록만 했다(§6 ⓓ).

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

### 서버를 재부팅한 뒤 — 뜬 걸로 치지 말고 확인한다 (Phase 3 신설)

컨테이너는 `restart: always`(Mosquitto만 `unless-stopped`)라 알아서 올라오고, 백엔드 상주 3개도
systemd `enabled`라 자동으로 뜬다. **그런데 둘의 순서가 보장되지 않는다** — 유닛의
`After=docker.service`는 *dockerd가 떴다*는 뜻이지 *컨테이너가 준비됐다*는 뜻이 아니다. 유닛이 먼저
시작하면 실패할 수 있고, 재시작을 몇 번 하다 멈추면 `failed`로 남는다.

**그래서 재부팅 뒤에는 자동으로 떴으려니 하지 말고 확인한다.**

```bash
cd ~/capstone-db
docker compose ps                                     # 컨테이너 13개가 다 올라왔나
systemctl is-active mk2-ingest mk2-storage-consumer mk2-ws-echo
systemctl --failed | grep mk2                         # failed 로 남은 유닛이 있나
journalctl -u mk2-ingest -n 30 --no-pager -q          # 있으면 로그부터
```

되살릴 때:

```bash
sudo systemctl restart mk2-ingest mk2-storage-consumer mk2-ws-echo

# "start request repeated too quickly" 가 나오면 재시작 한도에 걸린 것이다. 먼저 풀고 다시:
sudo systemctl reset-failed mk2-ingest mk2-storage-consumer mk2-ws-echo
sudo systemctl start        mk2-ingest mk2-storage-consumer mk2-ws-echo
```

**되살려도 안 되면 원인을 추측하지 말고 위 네 명령의 결과와 `journalctl` 로그를 들고 시작한다.**
흐르는지까지 보려면 아래 「"떠 있다"가 아니라 "흐른다"를 본다」. 재시작 정책 값과 그 이유,
`session.timeout.ms` 손잡이는 §6.

### TimescaleDB 접속 제한 (pg_hba) — 기동 **뒤에** 사람이 1회

**초기화 스크립트(`/docker-entrypoint-initdb.d`)로 하지 않는다.** 그 경로에 호스트
디렉터리를 마운트하면 timescale 이미지가 거기 넣어 둔 자기 초기화 스크립트(timescaledb
확장 설치·튜닝)가 통째로 가려진다. 게다가 그 스크립트는 **최초 1회만** 돌아서, 실패하면
기본값이 조용히 남고 재기동으로는 고쳐지지 않는다 — 잘못된 상태가 조용히 성립하는 자리다.

대신 컨테이너가 healthy가 된 뒤 **bind mount 안의 파일을 직접 고친다.** 눈으로 확인되고,
언제든 되돌릴 수 있다.

```bash
cd ~/capstone-db
HBA=timescale_data/pg_hba.conf

sudo cp $HBA $HBA.bak_before_mk2                 # 되돌릴 자리

# 기본값은 'host all all all scram-sha-256'(전면 허용)이다. pg_hba 는 **첫 매치가
# 이기므로**, 이 줄을 남긴 채 한정 규칙을 뒤에 붙이면 한정 규칙에 영원히 도달하지 못한다.
# 그래서 지우고 대체한다.
sudo sed -i -E '/^[[:space:]]*host[[:space:]]+all[[:space:]]+all[[:space:]]+all[[:space:]]/d' $HBA

sudo tee -a $HBA >/dev/null <<'EOF'

# ── MK2 Phase 2 (BE-S-01 계측 저장) ───────────────────────────────────────
# 백엔드(저장 소비자·pytest)는 서버의 호스트 프로세스라 127.0.0.1:7859 로 붙지만,
# 컨테이너 안에서는 docker 브리지 게이트웨이 172.18.0.1 로 보인다(실측).
# 그래서 'localhost' 가 아니라 172.18.0.0/16 이다.
host    mk2     mk2_app     172.18.0.0/16     scram-sha-256
EOF

docker exec capstone_timescaledb psql -U postgres -c "SELECT pg_reload_conf();"

# 확인: 전면 허용이 없고 한정 규칙이 있어야 한다
docker exec capstone_timescaledb sh -c 'grep -v "^#" /var/lib/postgresql/data/pg_hba.conf | grep -v "^$"'
```

**무엇이 달라지나:** `postgres` 슈퍼유저는 TCP(7859)로 붙지 못하고 컨테이너 안 unix
소켓으로만 붙는다 — 스키마 적용(사람이 1회)은 `docker exec -it capstone_timescaledb psql
-U postgres -d mk2` 로 하며 이 경로는 영향을 받지 않는다. 애플리케이션(`mk2_app`)의
TCP 접속은 그대로 된다.

**되돌리기:** `sudo cp $HBA.bak_before_mk2 $HBA` 후 `pg_reload_conf()`.

### 헬스 확인 (9개)

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
#   적재 설정 6개 (Phase 3): schema v13 · store tsdb · allow_structured_metadata true · retention_enabled true · retention_period 2w · delete_request_store filesystem
curl -s localhost:3100/config | grep -nE 'allow_structured_metadata|retention_enabled|delete_request_store|schema: v|store: tsdb'

# 7. Tempo
curl -s localhost:3200/ready
curl -s localhost:3200/status/config | grep -n block_retention | head -1      # 168h0m0s

# 8. OTel Collector
ss -tulpn | grep 4316                                                      # 127.0.0.1:4316 (Tailscale 바인딩은 주석 상태)
docker inspect capstone_otel_collector --format '{{.Config.Image}}'         # @sha256:… digest 형태여야 한다
docker logs --tail 20 capstone_otel_collector                                # "Everything is ready" — 파이프라인별 줄은 info 로그에 없다(validate 로 판정)

# 9. TimescaleDB (Phase 2 신설)
docker compose ps timescale-db                      # Up (healthy) 여야 한다
docker exec capstone_timescaledb pg_isready -U postgres -d mk2
#   확장·버전 + MK2 테이블이 서 있는지 (postgres 는 컨테이너 안 소켓으로만 붙는다 — §4 pg_hba)
docker exec capstone_timescaledb psql -U postgres -d mk2 -c \
  "SELECT extname, extversion FROM pg_extension WHERE extname='timescaledb';"
docker exec capstone_timescaledb psql -U postgres -d mk2 -c \
  "SELECT hypertable_name FROM timescaledb_information.hypertables;"
```

**MK2 MySQL(`mk2` DB)도 함께 본다** — 위 3번은 컨테이너 생사만 보고 MK2 내용물은 안 본다.

```bash
docker exec -i capstone_mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -t' <<'SQL'
SELECT TABLE_NAME, TABLE_COLLATION FROM information_schema.TABLES
 WHERE TABLE_SCHEMA='mk2' ORDER BY TABLE_NAME;          -- 8행 · 전부 utf8mb4_bin
SHOW GRANTS FOR 'mk2_app'@'172.18.%';                    -- DDL 없음 · append-only 테이블은 SELECT,INSERT 만
SQL
```

### "떠 있다"가 아니라 "흐른다"를 본다 (Phase 3 신설)

위 9개 블록은 **컨테이너가 살아 있는지**만 본다. 2026-09-14 실측에서 Collector·Tempo·Loki는 전부 `Up`이었지만
Collector는 10일간 OTLP 수신 0건, Tempo는 이력 전체 trace 0건, Loki는 7개월간 로그 0건이었다. **파이프라인 3종에
실제로 데이터가 흐르는지는 아래로 판정한다** — 상주 3개(systemd)가 떠 있어야 한다.

```bash
# 0. 백엔드 상주 3개 (Phase 3부터 systemd)
systemctl is-active mk2-ingest mk2-storage-consumer mk2-ws-echo
journalctl -u mk2-ingest -n 5 --no-pager -q                 # "관측 활성: service.name=be-ingest → http://127.0.0.1:4316 …"

# metric — Prometheus 에 be_* 가 있고, 발행하면 늘고, 멈추면 더 안 는다 (잔상이 아닌 살아 있는 표본)
curl -s 'localhost:7861/api/v1/label/__name__/values' | python3 -c "import sys,json;print([x for x in json.load(sys.stdin)['data'] if x.startswith('be_')])"
curl -s 'localhost:7861/api/v1/query' --data-urlencode 'query=sum(be_ingest_received_total)'     # 발행 전후 비교 (재기동 시 0 부터 — rate() 로 본다)

# log — Loki 에 백엔드 로그가 방금 시각 범위로 있다 (service_name 은 be-ingest · be-storage · be-gateway)
curl -s localhost:3100/loki/api/v1/label/service_name/values
curl -s -G 'localhost:3100/loki/api/v1/query_range' --data-urlencode 'query={service_name="be-ingest"}' --data-urlencode 'limit=3'

# trace — Tempo 의 service.name 태그값 (백엔드 span 은 Phase 6. 지금은 pytest 의 가짜 span 이 남긴 be-test-span-* 뿐)
curl -s localhost:3200/api/search/tag/service.name/values

# C층 — 장치별 업무 값의 관측 표현. 값이 흐를 때만 존재한다 (5분 갱신 없으면 exporter 가 내린다 — "장치가 안 보내면 시계열도 없다")
curl -s 'localhost:7861/api/v1/query' --data-urlencode 'query=count by (__name__) ({__name__=~"be_telemetry_.*"})'
```

**Phase 0은 헬스체크로 판정한다(pytest 아님).** Phase 1부터 pytest를 쓴다.
**Phase 2가 더한 두 저장소(9번·MySQL `mk2`)는 pytest로도 덮인다** —
`tests/conftest.py`의 `tsdb_conn`·`mysql_conn` fixture가 접속 실패를 `pytest.skip`으로 바꾸므로,
**인프라가 없으면 그 테스트만 건너뛰고 나머지는 통과**한다. **Phase 3의 관측 3종도 같다** —
`prometheus_url`·`loki_url`·`tempo_url` fixture(`tests/conftest.py`)가 `/-/healthy`·`/ready`로 확인해 없으면 skip.
서버 전건은 **184건**(2026-09-16, skip 0).

---

## 5. Kafka 설정값과 근거 · 언제 바꾸나

Kafka와, Phase 3이 고친 관측 4개(§5-0)만 적는다. 나머지는 기존 설정 그대로다.

### 5-0. 관측 스택 설정 — Phase 3이 고친 것과 근거 (2026-09-15)

| 무엇 | 값 | 근거 | 되돌리기 |
|---|---|---|---|
| Collector 이미지 | **digest 고정** `otel/opentelemetry-collector-contrib@sha256:7087dcbb…`(v0.150.1) | `:latest`는 이동 태그라 같은 이름으로 내용이 바뀐다. 특히 **컴포넌트 이름이 스네이크 케이스로 개명 중**(`otlp`→`otlp_grpc`, `otlphttp`→`otlp_http` 등, 옛 별칭은 폐기 예정)이라 설정에 쓴 이름이 다음 `:latest`에서 **조용히 깨질 수 있다.** TimescaleDB와 같은 규칙 | `docker-compose.yml.bak_before_phase3` |
| Collector 파이프라인 | `metrics`·`traces`·`logs` 3종 + `batch`(5s/512). exporter 정식명 `otlp_grpc`(→`tempo:4317`)·`otlp_http`(→`http://loki:3100/otlp`) | 기준 §5-3·§6-3. **컴포넌트 유무는 `components` 목록이 아니라 `validate`로 판정한다** — 목록이 정식명+별칭 쌍 4개(`otlp/otlp_grpc`·`otlphttp/otlp_http`·`azureblob/azure_blob`·`googlecloudstorage/google_cloud_storage`)를 빠뜨린다(2026-09-14 실측) | `config/otel-collector-config.yaml.bak_before_phase3` |
| Loki | v13/**tsdb** 단일 스키마 · `allow_structured_metadata: true` · `retention_enabled: true` · `retention_period: 14d` · `delete_request_store: filesystem` | boltdb-shipper는 구조화 메타데이터도 네이티브 OTLP 수집도 지원하지 않는다. 기존 데이터는 7개월 전 단일 스트림 172K라 백업 후 비웠다. **보존 3줄은 함께 있어야 집행된다** | `config/loki-config.yaml.bak_before_phase3` + `/home/dg/loki_data.bak_before_phase3.tgz`(옛 데이터). `loki_data`는 `root:root 777`로 재생성(Loki가 uid 10001로 쓴다) |
| Tempo | `block_retention: 168h` | 24h면 Phase 6에서 "어제 그 명령"을 못 본다. trace는 명령 경로에만 붙어 양이 적다 | `config/tempo-config.yaml.bak_before_phase3` |
| Prometheus | `otel_collector` 잡 `scrape_interval: 5s`. **global 무변경**(1s) · 보존 무변경(CLI 기본 15d) | 백엔드 export 15초 × 표본 3. ⚠ global `scrape_timeout > scrape_interval`인 잡이 하나라도 있으면 설정 전체가 거부된다 — `rpi`·`thermal`이 잡별 5s에 global timeout 1s를 상속하므로 global을 올리지 않는다 | `config/prometheus.yml.bak_before_phase3` |
| 상주 3개 | systemd `mk2-ingest`·`mk2-storage-consumer`·`mk2-ws-echo`(`Restart=on-failure`, `StartLimitBurst=3/60s`, `EnvironmentFile=/home/dg/capstone-db/.env`, enabled) | A층은 셋이 상시 떠 있어야 계측이 나온다. `Restart=always`면 `.env` 없을 때 무한 루프 | `sudo systemctl disable --now mk2-*` |

**설정을 고치기 전에 반드시 `validate`/`promtool check config`를 돌린다** — 기동 실패로 알기보다 먼저 안다.

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

채널별 3토픽이며 **장치별·구역별 토픽이 아니다** — `zone_id`·`source_id`는 공통 헤더 안에 있다.
파티션 키는 `source_id`(장치별 순서 보장). 이름은 점 구분 소문자이며 **언더스코어를 섞지 않는다**
(생성 시 뜨는 `.`/`_` 경고는 둘을 섞을 때의 충돌을 알리는 것이라 점만 쓰는 현 규약에서는 무해).

```bash
docker exec capstone_kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list
```

### 컨슈머 그룹 (2026-09-10 현재)

| 그룹 | 무엇 | 상시 |
|---|---|---|
| `mk2-storage` | 저장 소비자(TSDB + 레지스트리) | ✅ |
| `mk2-ws` | WS 게이트웨이 | ✅ |
| `mk2-headerless-check` · `mk2-dedup-a` · `mk2-dedup-b` | Phase 2 검증용 1회성 | ❌ 남아 있음 |
| `mk2-test-*` | pytest 1회용 | ❌ 남아 있음 |

**서버 안에서 소비자가 느는 것은 Kafka 설정 변경 사유가 아니다** — 그룹만 추가하면 된다.

> ⚠ **검증용 그룹은 정리 여부가 미결이다.** 특히 `mk2-dedup-*`는 **`earliest`로 전량 재소비한
> 그룹**이라 같은 이름으로 다시 돌리면 **오프셋이 남아 있어 예상과 다르게 동작한다.**
> 지우려면 `kafka-consumer-groups.sh --bootstrap-server localhost:9092 --delete --group <이름>`.

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

> **이건 "영구 고정"이 아니라 "지금 조건에서는 불필요"라는 뜻이다.** 기준 아키텍처(§5-1·§6-1)는
> 엣지↔서버 Kafka 백본을 전제하므로 **노출 변경은 예정된 일**이다. 이 절은 변경을 막는 것이
> 아니라 **바꿀 때 안전하게 바꾸는 방법**을 적어둔 것이다.

**바꿔야 하는 조건 — 페이즈 번호가 아니라 이 조건이 기준이다.** 아래 중 하나라도 생기면 시점이
Phase 4보다 이르더라도 바꾼다(그때 이 문서를 갱신한다).

- 원격 엣지가 Kafka에 직접 붙는다 (가장 흔한 경우, 예상 Phase 4)
- 다른 파트(AI·가시화)의 소비자가 **서버 밖에서** Kafka에 붙어야 한다
- 브로커나 소비자를 다른 호스트로 옮긴다

반대로 **서버 안에서만 붙는 소비자가 늘어나는 것은 변경 사유가 아니다** — 컨슈머 그룹만 추가하면
된다(Phase 2의 TSDB writer, Phase 5·6의 소비자 등이 여기 해당한다).

#### 지금 어느 리스너를 누가 쓰나 (2026-09-10 확인 — Phase 4에서 중요하다)

`KAFKA_LISTENERS`에 셋이 선언돼 있지만 **실제로 쓰이는 것은 PLAINTEXT 하나뿐이다.**

| 리스너 | 지금 쓰는 클라이언트 |
|---|---|
| **PLAINTEXT** (`localhost:9092`) | **백엔드 3개 전부** — `backend.ingest.bridge`(producer) · `backend.storage.consumer`(그룹 `mk2-storage`) · `backend.gateway.ws_echo`(그룹 `mk2-ws`) |
| INTERNAL (`kafka:9094`) | **없다.** 같은 docker 네트워크의 컨테이너용인데 현재 Kafka에 붙는 컨테이너가 하나도 없다 |
| CONTROLLER (`:9093`) | KRaft 합의(브로커 자기 자신) |

**백엔드 3개는 컨테이너가 아니라 서버의 호스트 프로세스**다(venv에서 `python -m ...`으로 돈다).
그래서 docker 네트워크 안이 아니라 **호스트 loopback `localhost:9092`** 로 붙는다.

> ⚠️ **따라서 Phase 4에서 PLAINTEXT advertised를 바꾸면 백엔드 3개가 함께 영향을 받는다.**
> "원격 엣지만 영향"이 아니다. 바꿀 때 `MK2_KAFKA_BOOTSTRAP` 환경변수(`backend/settings.py`)도
> 함께 맞춰야 한다. INTERNAL을 쓰는 클라이언트가 없으므로 **그쪽은 지금 바꿔도 아무 영향이 없다.**
>
> (서버 compose 파일의 주석은 gitignore라 저장소에 남지 않으므로 커밋되는 이 문서에 적는다.)

#### 바꿀 때 정확히 이 3가지 (예상 시점: Phase 4, 원격 엣지·Tailscale)

포트만 열어서는 안 되고, **열더라도 모든 인터페이스에 열면 안 된다**(현재 PLAINTEXT·인증 없음).

1. **`ports` → Tailscale 인터페이스 IP에 바인딩** (`<tailscale-ip>:9092:9092`). `9092:9092`는
   공인 IP를 포함한 전 인터페이스 노출이라 쓰지 않는다. ~~Tailscale 설치가 선행돼야 한다.~~
   **Tailscale은 Phase 3(2026-09-16)에서 서버에 설치됐다**(1.102.4, `tailscaled` enabled,
   팀 공용 계정) — 설치 선행 조건은 이미 충족이다. ⚠ 다시 `tailscale up`을 치지 않는다(계정이
   갈릴 수 있다). 주소는 `tailscale ip -4`로 읽고 `_serverinfo/`에만 적는다.
   ⚠ **없는 IP에는 docker가 바인딩하지 못한다** — `tailscaled`가 뜨기 전에 `up -d`를 하면
   `cannot assign requested address`로 기동이 실패하고, 재부팅 시 `restart: always`가 루프에
   빠질 수 있다(§6 ⓗ와 같은 함정).
2. **`KAFKA_ADVERTISED_LISTENERS`의 `PLAINTEXT` 호스트** → 엣지가 실제로 도달하는 그 주소
   (위 1의 주소). 이걸 안 바꾸면 포트를 열어도 위 2단계 연결에서 실패한다.
3. **ufw를 엣지 소스로 제한하고, 그 포트를 ufw에 반드시 연다.**

> ### ⚠️ 정정 (2026-09-10) — "ufw는 안 열어도 된다"로 읽으면 안 된다
>
> **이 항목 3은 원래 이렇게 쓰여 있었다:**
>
> > ~~단 **docker publish는 DNAT라 ufw INPUT을 상당부분 우회**하므로, 실질적인 통제는 3이 아니라
> > **1의 인터페이스 바인딩**이다. ufw는 보조 수단으로 본다.~~
>
> **실측이 이 서술을 반증했다.** 서버에서 **9100 포트를 ufw에 열자마자 Prometheus 수집이
> 정상화됐다.** DNAT가 ufw를 우회한다는 서술이 맞다면 일어날 수 없는 일이다.
>
> **그래서 규칙을 이렇게 고친다: 서비스의 외부 포트는 ufw에도 반드시 연다.**
> 이유는 두 가지다 — ① 위 실측대로 **실제로 막힐 수 있다** ② 장애가 났을 때
> **방화벽을 용의선상에서 빼기 위해서**다. 원인을 하나씩 지우지 못하면 디버깅이 몇 배로 늘어난다.
>
> **바인딩과 ufw는 층이 다르며 충돌하지 않는다.** 바인딩이 `127.0.0.1`이면 애초에 loopback에서만
> 듣기 때문에 **ufw를 열어도 외부 접근이 생기지 않는다.** 1(바인딩)은 "실질 노출을 만들지 않기
> 위해", 3(ufw)은 "장애 원인에서 방화벽을 제외하기 위해" 하는 것이다. **둘 다 한다.**
>
> 이 문장을 믿고 Phase 4에서 "ufw는 안 열어도 된다"고 판단하면 같은 사고가 반복된다.
> Phase 2에서 TimescaleDB(7859)를 세울 때도 이 규칙을 적용했다(§3의 7859 주 참조).

(현재 ufw에 `9092 ALLOW Anywhere` 규칙이 있으나 바인딩이 `127.0.0.1`이라 실제 노출은 없다 —
바로 위에서 말한 "층이 다르다"의 실례다.)

### 데이터 디렉터리 권한

`apache/kafka` 이미지는 컨테이너 안에서 **uid 1000(appuser)**으로 돈다. 서버 작업 계정의 uid가
다르면 그냥 `mkdir`한 폴더에 컨테이너가 쓰지 못해 기동이 실패한다.

```bash
mkdir -p kafka_data
sudo chown -R 1000:$(id -g) kafka_data   # 소유자=컨테이너 appuser, 그룹=작업 계정
chmod 775 kafka_data
```

**TimescaleDB(`timescale_data/`)는 다르다 — `chown` 하지 않는다.**

`timescale/timescaledb`는 Alpine 기반이라 컨테이너 안 postgres가 **uid 70**이고(공식 postgres
이미지의 999가 아니다), **entrypoint가 스스로 소유권을 잡는다**(실측 `drwx------ 70 dg`).
그냥 `mkdir`만 하면 된다.

> ⚠ **두 가지가 따라온다.**
> - **지울 때 `sudo`가 필요하다** — `sudo rm -rf timescale_data`. 소유자가 `dg`가 아니다.
> - **디렉터리 권한이 `700`이면 컨테이너가 못 읽어 기동이 실패한다.** Phase 2에서
>   `/docker-entrypoint-initdb.d`에 마운트한 디렉터리가 `umask 077` 잔존으로 `700`이 되어
>   **컨테이너가 36회 재시작**했다. `.env` 때문에 건 `umask`는 그 직후 되돌린다.

---

## 6. 알려진 사항 — 조치는 해당 Phase에서

아래는 **설정 파일과 실측에서 확인한 사실, 그리고 처리 시점**이다. Phase 0이 남긴 관측 4건은
**Phase 3(2026-09-15)에서 처리했고 그 결과를 같은 행에 적었다.** 뒤쪽은 Phase 2·3이 남긴 것이다.

### 6-0. 관측 3종의 실사용 현황 — Phase 3 착수 시 실측 (2026-09-14)

**"떠 있다"와 "흐른다"는 다르다.** compose 주석이 말하는 생산자들이 실제로는 보내고 있지 않았다.

| 저장소 | 실측 | 뜻 |
|---|---|---|
| Collector | `job="otel_collector"` 지표가 스크레이프 메타 5종뿐, `service_name` 값 `[]`, 4316·4317 TCP 연결 0 | **2026-09-03 재기동 이후 10일간 OTLP 수신 0건** |
| Tempo | `blocks/`에 `tempo_cluster_seed.json` 하나, `service.name` 태그값 `[]` | **이력 전체 trace 0건.** compose 주석 *"파이썬 서버가 데이터 보내는 문"* 은 주장이지 실측이 아니었다 |
| Loki | 29일 창 라벨 질의 스트림 0, chunk 23개/172K, 단일 스트림, 2026-01-26~02-09 | **7개월간 새 로그 0건** |
| Prometheus | 950M · 1,215 시계열 · 326종 | **유일하게 살아 있었고 그 데이터는 전부 분류 ③의 것**(`rpi_*`·`thermal_*`·`conntest`·`push_*`) |

Phase 3 뒤: 셋 다 흐른다 — `be_*` 21종(A 9 + C 12)·`{service_name="be-*"}` 로그·가짜 span. 판정 방법은 §4.

| 파일 | 확인된 것 → 처리 | 언제 |
|---|---|---|
| `otel-collector-config.yaml` | **`logs`·`traces` 파이프라인이 없었다 (metric만).** → ✅ **파이프라인 3종**(`traces`→`otlp_grpc` `tempo:4317`, `logs`→`otlp_http` `http://loki:3100/otlp`) + `batch`. Collector가 분배하는 기준 구조로 정리됐고 **호스트 포트는 무변경**(§3 ⓐ·ⓑ). 이미지 digest 고정 | ✅ Phase 3 (2026-09-15) |
| `prometheus.yml` | `global.scrape_interval: 1s` — 기준(15초~1분)과 다르다 → ✅ **global은 그대로 두고 `otel_collector` 잡만 5s**로. global을 올리면 `rpi`·`thermal`(잡별 5s, timeout 상속 1s)이 `timeout > interval`로 설정 전체가 거부되고, 그 대시보드는 다른 파트 것이다(§5-0) | ✅ Phase 3 |
| `prometheus.yml` | 페더레이션 없음 → ✅ **`edge_federate` 잡을 만들어 임시 엣지(컴퓨터, Tailscale)로 실증**(`agg_layer="edge"` 보존, `match[]` 한정, 음성 대조 통과) 후 **주석으로 내렸다** — 엣지 실물이 오면 주소만 바꿔 되살린다 | ✅ Phase 3 / 되살리기 Phase 4 |
| `loki-config.yaml` | ~~retention 없음 → 로그를 흘리기 전에 걸어야 한다~~ **정정:** 정확히는 **보존을 집행할 기능이 꺼져 있었다** — `retention_enabled: false`·`retention_period: 0s`·`delete_request_store: ""` **세 줄이 함께** 꺼져 있었고 하나만 켜면 조용히 아무 일도 안 일어난다. 그리고 **retention은 compactor가 나이 기준으로 소급 집행**하므로 "흘리기 전에" 걸 필요는 없었다(순서는 권장이지 강제가 아니다). → ✅ 셋 다 켜고 `retention_period: 14d` | ✅ Phase 3 |
| `loki-config.yaml` | schema v11 + boltdb-shipper — "동작에 문제 없다"고 적었으나 **구조화 메타데이터도 네이티브 OTLP 수집도 지원하지 않아 Collector→Loki 경로가 애초에 성립하지 않았다.** → ✅ 데이터 백업(`/home/dg/loki_data.bak_before_phase3.tgz`) 후 `loki_data`를 비우고 **v13/tsdb 단일 스키마 + `allow_structured_metadata: true`** | ✅ Phase 3 |
| `tempo-config.yaml` | OTLP 직접 수신 (4317/4318) → 구조는 ⓐ로 해소(Collector가 `tempo:4317`로 넣는다). **호스트 4317은 그대로 열려 있다 — Collector 우회 입구.** `0.0.0.0` 바인딩 + ufw `Anywhere`. 이번에 닫지 않고 기록만 — 닫으려면 compose `ports` 한 줄 삭제 + ufw 규칙 삭제 + 재생성, 그리고 그 포트로 직접 쏘는 주체가 없음을 먼저 확인 | 기록 (ⓓ) |
| `tempo-config.yaml` | `block_retention: 24h` → ✅ **168h** | ✅ Phase 3 |
| Prometheus 보존 | compose `command:`에 플래그 없음 → **CLI 기본값 15d에 기대고 있다.** 바꾸면 컨테이너 재생성이 따라온다. 기준 문서가 값을 규정하지 않아 그대로 둠 | 기록 (ⓔ) — Phase 4에서 digest 고정과 묶어서 |
| `prometheus.yml` | `conntest` 잡 라벨이 들어오는데 **출처 미상**(scrape 잡이 아니라 pushgateway로 밀어 넣는 쪽). 분류 ③ | 기록 (ⓕ) |
| Collector 4316 | **Tailscale 인터페이스 추가 바인딩(`<서버 tailscale IP>:4316:4317`)과 ufw 규칙(엣지 IP `/32` 한정)은 Phase 3 검증(8-7) 뒤 되돌렸다** — compose는 주석 한 줄로 남아 있다. 되살리는 조건: 엣지 실물 + BE-T-08(TLS·인증). 되살릴 때 ① `tailscale ip -4`가 주소를 주는지(없는 IP에는 바인딩 실패 → 재부팅 시 `restart: always` 루프) ② ufw는 엣지 IP `/32`로만(**이 수신단에는 인증이 없다** — `Anywhere` 금지) ③ 엣지 Agent exporter 주소 | 기록 (ⓗ) — Phase 4 |
| `mosquitto.conf` | `allow_anonymous true`, ACL 없음. 개발 단계라 의도된 상태이며 **Phase 1 브릿지 연결에는 오히려 유리하다** | 운영 전환 시 |
| `mosquitto.conf` | `persistence` 미설정 → 브로커 재시작 시 retained 소실 | Phase 1/5 |
| (요구사항) | **가용성 판정 파라미터** — 하트비트 1초 1회, **4회 연속 미수신(약 4초)** 시 장애 판정. 기준은 조병현 HW-S-05·HW-A-05이며 김현우 VZ-U-01도 4초 판정을 전제한다. **Phase 1 실측 5초는 테스트 편의값이지 요구사항이 아니다** | Phase 5 |
| **MySQL** | **`0.0.0.0:7858` 전 인터페이스 바인딩 + `root@%`** — 다른 파트가 쓰는 컨테이너라 Phase 2에서 손대지 않았다(기록만). MK2 앱 계정은 이미 `'mk2_app'@'172.18.%'`로 호스트 제한돼 있다 | **Phase 6**(인증·인가와 함께) |
| **MySQL `mk2`** | **`registry_identity_history`에 `UPDATE` 권한이 있다.** 이 테이블은 append 성격인데(같은 성격인 `mission_event`는 `SELECT, INSERT`만) 지시서 권한 표가 관측 축 셋을 한 묶음으로 적어 표대로 넣었다. **회수는 한 줄이고 즉시 적용된다:** `REVOKE UPDATE ON mk2.registry_identity_history FROM 'mk2_app'@'172.18.%';` | 검수 후 결정 |
| **MySQL `mk2`** | **`actor_kind` 어휘가 두 테이블에서 다르다** — `mission_event`는 `ai\|backend\|human`(VZ-D-02 원문), `audit_log`는 `user\|system\|ai 등`. 감사 쓰기를 세울 때 하나로 맞춘다 | **Phase 6** |
| **TimescaleDB** | `timescaledb-tune`이 서버 사양(247GB·다코어)에 맞춰 `max_worker_processes=115`·`max_parallel_workers=96`·`work_mem=21MB`로 잡았다. **공용 서버라** 부하가 보이면 조일 여지가 있다 | 필요해지면 |
| **TimescaleDB** | **보존 기간·압축 정책이 없다.** 하이퍼테이블로 만들어 두어 **정책만 붙이면 된다** — BE-S-04가 별도 요구사항이고 발동 조건이 아직 아니다 | 발동 조건 충족 시 |
| Kafka | **검증용 컨슈머 그룹 3개가 남아 있다**(§5 「컨슈머 그룹」) | 정리 여부 미결 |
| 백엔드 상주 프로세스 | ~~터미널 수동 기동~~ → ✅ **systemd 유닛 3개**(`infra/systemd/`, enabled). ⚠ 재부팅 시 Kafka·Mosquitto 컨테이너가 `3회×5초` 안에 안 올라오면 `StartLimitBurst`에 걸려 실패 상태로 멈출 수 있다 — 그때는 `sudo systemctl start mk2-*`. 그리고 **`kill -9`·OOM처럼 신호 없이 죽으면 재기동한 소비자가 세션 타임아웃까지 파티션을 못 받는다**(SIGTERM은 Phase 3에서 그룹을 깨끗이 떠나게 고쳤다 — 정상 재기동은 6초).<br>**손잡이:** `session.timeout.ms` — Kafka 소비자 설정, `backend/storage/consumer.py::build_consumer()`·`backend/gateway/ws_echo.py::build_consumer()`의 `Consumer({...})` 딕셔너리에 키를 더하면 된다. **기본값 45000(librdkafka)** — 지금은 안 적어 기본값. 낮추면(예: `10000`) 비정상 죽음 뒤 재할당이 빨라지는 대신, 소비자가 잠깐 멈추기만 해도(GC·TSDB 재접속 대기 등) 브로커가 죽은 것으로 오판해 리밸런스가 잦아진다. 함께 보는 값 `heartbeat.interval.ms`(기본 3000, timeout의 1/3 이하). Phase 3에서는 **바꾸지 않았다**(지시서에 없음) | ✅ Phase 3 |
| OTel Logs SDK | `LoggingHandler`가 SDK 1.44에서 **deprecated** — `opentelemetry-instrumentation-logging`의 핸들러로 옮기라는 경고(pytest 경고 2건). 동작엔 영향 없음 | Phase 4 (패키지 교체 1건) |
| A층 counter | **재기동마다 0으로 리셋**되고 Collector exporter가 옛 프로세스 값을 5분간 더 내보낸다. 절대값을 읽지 말고 `rate()`/`increase()`로 본다. ingest 재기동 시 retained `status` 재유입(지금 **6건** — sensor·robot·actuator·analysis wl-001 + reg-a zoneA/zoneB)만큼 `be_ingest_received_total{channel="status"}`가 튄다 — 정상.<br>**손잡이 없음** — counter가 프로세스 수명을 따르는 것은 OTel 규격이라 설정으로 못 바꾼다. 조회 규칙(`rate()`)이 답이다. "옛 값 5분"은 아래 C층 행의 `metric_expiration`과 같은 값이다 | 기록 |
| C층 gauge | 값이 흐를 때만 존재한다 — 5분 갱신이 없으면 exporter가 내리고 Prometheus가 stale 처리한다("장치가 안 보내면 시계열도 없다"). `state.analysis` 3종은 증강 분석이 돌지 않아 **가짜 발행자로만 값이 있었다**.<br>**손잡이:** `metric_expiration` — Collector 설정 `config/otel-collector-config.yaml`의 `exporters.prometheus:` 아래에 한 줄(예: `metric_expiration: 30m`). **기본값 5m** — 지금은 안 적어 기본값. 늘리면 장치가 침묵해도 마지막 값이 그 시간만큼 `/metrics`에 남아 대시보드에 "살아 있는 것처럼" 보이고(잔상), 줄이면 더 빨리 사라진다. 이 값은 A층 counter의 "옛 프로세스 값 잔류 시간"도 함께 바꾼다(같은 exporter). 바꾸면 `validate` → `config/` 교체 → `docker compose up -d otel-collector`(단계 4-3·4-4와 같은 절차). **장치 침묵을 "시계열 부재"로 읽을지 "마지막 값 유지"로 읽을지는 가용성 판정(Phase 5)의 결정 사항**이라 Phase 3에서는 기본값을 두었다. 또 하나 관련 기본값: SDK gauge는 새 값이 들어온 주기에만 데이터를 낸다(OTel last-value 집계) — 이건 손잡이가 없다 | 기록 |
| WS echo 로그 | `be-gateway`는 접속 사건 때만 로그를 내므로 Loki `service_name` 목록에 안 보일 때가 있다 — 이상 아님 | 기록 |
| **TimescaleDB `telemetry`** | **745행**(2026-09-16). 그중 테스트 잔여 **342행** — `st-*`·`wl-obs-*`·`wl-test-*`·`gap-*`·`wl-null`·`tsdb-*`. `mk2_app`에 DELETE 권한이 없어 정리하지 않았다(의도). **단계 0에서 행 수가 안 맞으면 먼저 이 접두사들로 설명되는지 본다** — Phase 3 단계 0이 476≠415에서 멈춰 조사한 전례가 있다 | 기록 |

관측 3종의 현재 실제 경로 (2026-09-16):

| 신호 | 기준 경로 | 현재 실제 |
|---|---|---|
| metric | Collector → Prometheus | ✅ (백엔드 A·C층 + `batch`). 엣지 raw는 페더레이션 요약만(`edge_federate`, 지금은 주석) |
| trace | Collector → Tempo | ✅ Collector `otlp_grpc` → `tempo:4317`(도커 망). 실 생산자는 아직 없음(백엔드 span Phase 6, HW span 미수신) — pytest 가짜 span으로 경로만 확인 |
| log | Collector → Loki | ✅ Collector `otlp_http` → `http://loki:3100/otlp`. 백엔드 3개가 OTel Logs SDK로 낸다(journald 병존) |
