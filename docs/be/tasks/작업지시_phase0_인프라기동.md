# 작업 지시: Phase 0 — 인프라 스택 기동

**대상:** Phase 0 (인프라 기동)
**착수:** 지금 (공통 계약 v1 확정 직후, 첫 사이클)
**근거 문서:**
- [`docs/be/01-standalone-implementation-plan.md`](../01-standalone-implementation-plan.md) §2 Phase 0 (이 작업의 명세)
- [`docs/be/00-architecture.md`](../00-architecture.md) (스택 구성요소가 5구간 어디에 쓰이는지)
- [`CLAUDE.md`](../../../CLAUDE.md) (절대 원칙·코드 규약)

> 이 문서는 VS Code Claude Code가 읽고 구현하는 인수인계 문서다. `CLAUDE.md`와 이 지시서를
> 함께 읽고, 지시서 범위대로 구현한다. 설계는 이미 끝났으므로 새로 설계하지 않는다.

---

## 배경

백엔드 파이프라인(Phase 1~)이 딛고 설 **인프라 스택을 먼저 세운다.** Phase 2(저장)·Phase
3(관측)을 하려면 전체 파이프라인이 돌아야 하고, 그러려면 풀 스택이 미리 깔려 있어야 한다.
따라서 **인프라는 Phase 0에서 한 번에 다 깔고, 이후 Phase에서는 그 위에 코드·설정·파이프라인만
올린다** — 인프라를 Phase마다 찔끔 까는 방식을 쓰지 않는다.

단, 스택 중 일부는 **서버에 이미 깔려 돌고 있으므로**(Mosquitto·OpenTelemetry·Grafana 등),
지웠다 다시 깔지 않고 compose 정의만 MK2 구조로 정리하고 헬스만 확인한다. **새로 설치할 것과
이관할 것을 구분**하는 것이 이 작업의 핵심 판단이다.

---

## 스택 구성 (무엇을, 새로 vs 이관)

Phase 0에서 올리는 것은 아래 8개다. **TSDB는 제외**한다 — 제품(InfluxDB vs TimescaleDB)이
미확정이고 Phase 2(저장)에서 처음 쓰이므로, Phase 2 설계에서 정한다.

| 구성요소 | 역할(5구간) | 처리 |
|---|---|---|
| **Kafka** (KRaft 단일 노드) | 엣지↔서버 백본 + 서버 다중 소비자 팬아웃 | **새로 설치** |
| **Mosquitto** (MQTT 브로커) | 엣지 브로커, 말단 발행 수용 | 이관·헬스 확인 (이미 도는 경우) / 없으면 새로 |
| **OTel Collector** | 관측 3종 수집·라우팅 | 이관·헬스 확인 / 없으면 새로 |
| **Prometheus** | 관측 metric 저장·요약 | 이관·헬스 확인 / 없으면 새로 |
| **Grafana** | 개발용 종착지(관측·지표 시각화) | 이관·헬스 확인 (이미 도는 경우) |
| **Loki** | log 저장 | 이관·헬스 확인 / 없으면 새로 |
| **Tempo** | trace 저장 | 이관·헬스 확인 / 없으면 새로 |
| **MySQL** | 감사·레지스트리(2축 중 관계형) | **새로 설치** (제품 확정, 골격 곧 필요) |

- **Kafka:** KRaft 모드 단일 노드(ZooKeeper 없이). 복제 없이 작게 — 국가 프로파일(3AZ·RF=3)이
  아니다(CLAUDE.md 원칙 15). 나중에 브로커 추가·파티션 확장으로 키울 수 있다.
- **이관 대상(Mosquitto·OTel·Prometheus·Grafana·Loki·Tempo):** 서버에 이미 도는 것은 지우지
  않는다. 기존 `docker-compose_260617.yml`·Grafana 대시보드·OTel Collector 설정을 참고해
  **compose 정의만 MK2 구조로 정리**하고, 기동/헬스만 확인한다. "이미 도는지"는 구현 시 서버
  상태로 판단하고, 도는 것은 정의 정리+헬스, 없는 것은 새로 설치한다.

---

## 제약 — 반드시 지킬 것

1. **RBAC·MongoDB를 넣지 않는다.** 정본 결정(CLAUDE.md 원칙 4). 저장은 TSDB(Phase 2)+MySQL
   2축이며 이 스택에 다른 DB를 추가하지 않는다.
2. **이미 서버에 도는 기반을 지웠다 다시 깔지 않는다.** Mosquitto·OTel·Grafana 등은 이관(정의
   정리)만 한다. 기반은 그대로 쓰고 정의 파일만 MK2로 정리.
3. **compose는 `infra/docker-compose.yml` 하나로** 시작한다(나누지 않는다).
4. **비밀정보를 커밋하지 않는다.** 이 저장소는 Public이다. 비밀번호·토큰·내부망 endpoint는
   `.env`(gitignore됨)로 빼고, compose·설정에는 placeholder만 둔다. `.env.example`에 필요한 키
   목록만(값 없이) 남긴다.
5. **파일 인코딩 UTF-8, 줄바꿈 LF.** `.gitattributes`가 강제한다. 특히 compose·설정·env는 CRLF가
   섞이면 값 끝에 `\r`이 붙어 조용히 깨진다.
6. **Kafka를 크게 배포하지 않는다.** KRaft 단일 노드, 복제/멀티 AZ 없음.
7. **이 단계는 인프라 기동까지다.** 파이프라인 코드(ingest·gateway 등)는 Phase 1이므로 여기서
   만들지 않는다. `backend/` 아래 코드를 작성하지 않는다.

---

## 먼저 읽을 것

1. `docs/be/01-standalone-implementation-plan.md` §2 Phase 0 — 이 작업의 DoD·의존성.
2. `docs/be/00-architecture.md` §3~§6 — 각 구성요소가 어느 구간에서 무엇을 하는지(특히 §4 엣지
   내부: Collector+Prometheus 이원, §6 서버 내부: Kafka 팬아웃·MySQL).
3. 기존 `docker-compose_260617.yml`·Grafana 대시보드·OTel Collector 설정 — 이관 대상. 무엇이
   있는지 파악한 뒤 MK2 구조로 정리.
4. `CLAUDE.md` §1 절대 원칙 — 특히 4(2축·RBAC/Mongo 금지)·6(관측 metric만 요약)·15(Kafka 작게).

---

## 단계

### 1단계 — 기준선 확인 (먼저 한다)

1. `git status`가 깨끗한지 확인.
2. 서버에 이미 도는 컨테이너/서비스를 확인한다(`docker ps`, 포트 점검). 무엇이 이미 있고
   무엇이 없는지 목록화 — 이관 대상과 새 설치 대상을 가른다.
3. 기존 `docker-compose_260617.yml`·설정 파일을 읽어 현재 구성을 파악한다.

### 2단계 — compose 골격 작성

`infra/docker-compose.yml` 하나에 8개 서비스를 정의한다.

- **새로 설치(Kafka·MySQL):** 이미지·환경변수·포트·볼륨 정의. Kafka는 KRaft 단일 노드 구성
  (`KAFKA_PROCESS_ROLES=broker,controller`, `KAFKA_NODE_ID=1`, 단일 controller quorum). MySQL은
  감사·레지스트리용(초기 스키마는 Phase 2·6에서, 여기선 컨테이너 기동까지).
- **이관(Mosquitto·OTel·Prometheus·Grafana·Loki·Tempo):** 기존 설정을 참고해 MK2 구조로 정의.
  이미 서버에 도는 것은 그 정의를 정리하는 수준(새로 안 깖).
- 볼륨은 `.gitignore`에 이미 제외된 이름(`kafka-data/`·`mysql-data/`·`prometheus-data/` 등)을
  쓴다 — 로컬 데이터가 저장소에 올라가지 않게.
- 비밀값은 `.env`로 빼고 compose에서 `${VAR}`로 참조. `infra/.env.example`에 키 목록만 남긴다.

### 3단계 — 구성요소별 설정 파일

compose가 참조하는 설정을 `infra/` 아래 둔다.

- OTel Collector 설정(`otel-collector-config.yaml`): receiver(OTLP) → processor → exporter
  (metric→Prometheus, log→Loki, trace→Tempo). 관측 3종 라우팅.
- Prometheus 설정(`prometheus.yml`): scrape 대상(방식 A: Collector의 /metrics). 국가 프로파일의
  페더레이션은 Phase 3에서.
- Mosquitto 설정(`mosquitto.conf`): listener :1883. 개발 단계 인증은 최소로(운영 인증·TLS는
  나중), Public 저장소이므로 실제 자격증명 금지.
- Loki·Tempo·Grafana 설정: 기본 기동에 필요한 최소. Grafana 데이터소스(Prometheus·Loki·Tempo)
  연결.
- 기존에 이미 있던 설정은 이관해 재사용한다(새로 안 짬).

### 4단계 — 기동 + 헬스 확인 (완료 판정 수단)

`docker compose -f infra/docker-compose.yml up -d` 후 각 서비스 헬스를 확인한다. **이 단계는
pytest가 아니라 헬스체크로 판정한다.**

- Kafka: 토픽 생성/조회가 되는지(`kafka-topics --list` 등).
- Mosquitto: :1883 접속(`mosquitto_pub/sub` 또는 포트 확인).
- OTel Collector: OTLP 포트(:4317/:4318) 열림, 샘플 지표 수신 시 exporter로 전달되는지.
- Prometheus: UI(:9090) 응답, Collector scrape 타깃이 up인지.
- Grafana: UI(:3000) 응답, 데이터소스 연결 확인.
- Loki·Tempo: 응답 확인.
- MySQL: 접속 확인.

헬스 결과를 기록한다(다음 보고에 넣는다).

### 5단계 — 실행 방법 문서화

- `README.md`(루트)의 "설치와 실행" 섹션을 실제 명령으로 채운다(compose up·헬스 확인 방법).
- `infra/`에 간단한 README나 주석으로 기동 순서·포트·이관/새설치 구분을 남긴다.

---

## 이번에 하지 않는 것

- **파이프라인 코드** (ingest·gateway·storage 등 `backend/` 아래) — Phase 1.
- **TSDB** — Phase 2(제품 확정과 함께).
- **관측 페더레이션** (엣지 Prometheus raw + 요약 pull) — Phase 3. Phase 0은 단일 Prometheus
  기동까지.
- **인증·TLS 운영 구성** — 개발 단계 최소만. 운영 인증·Tailscale은 나중.
- **MySQL 스키마** (감사·레지스트리 테이블) — Phase 2·6. Phase 0은 컨테이너 기동까지.

---

## 완료 판정

아래가 전부 참이어야 이 작업이 끝난 것이다.

1. `infra/docker-compose.yml` 하나로 8개 서비스(Kafka·Mosquitto·OTel Collector·Prometheus·
   Grafana·Loki·Tempo·MySQL)가 정의되어 있다. (TSDB 없음)
2. `docker compose up` 후 8개 서비스가 전부 기동하고 4단계 헬스 확인을 통과한다.
3. 새로 설치한 것(Kafka·MySQL)과 이관한 것(나머지)이 구분되어 있고, 이미 도는 기반을 지웠다 다시
   깐 흔적이 없다.
4. 비밀값이 compose·설정에 하드코딩되어 있지 않다(`.env` 참조, `.env.example`에 키 목록만).
5. compose·설정 파일이 LF·UTF-8이다.
6. `README.md` "설치와 실행"이 실제 명령으로 채워졌다.
7. RBAC·MongoDB·TSDB가 스택에 없다.

---

## 보고

작업이 끝나면 아래를 기록·커밋한다.

- **`reports/YYYY-MM-DD_HHMM_phase0_인프라기동.md` 생성** — 형식: 배경 / 한 일 / 검증(4단계
  헬스 결과) / 다음. 담을 것:
  - 서버에서 이미 돌던 것 vs 새로 설치한 것 목록(기준선 확인 결과)
  - 8개 서비스 헬스 확인 결과
  - 이관 시 바꾼 것(기존 설정 → MK2 구조로 무엇을 어떻게 정리했는지)
  - 미결/다음 단계로 넘긴 것 → **다음: Phase 1(얇은 파이프라인 관통) 착수 예정**
- **`docs/be/requirement-traceability.md` 갱신** — Phase 0이 기반을 놓은 요구사항의 상태·구현
  위치를 갱신한다. 특히 BE-S-02(OTel 파이프라인)·BE-S-03(관측 계층화, 부분)·BE-T-01(MQTT
  브로커 기동)·BE-T-02(Kafka 기동) 등 인프라 기동으로 진전된 항목을 `미착수 → 부분`으로.
- **`docs/be/01-standalone-implementation-plan.md` §3 "지금 당장 할 일" 체크박스 갱신** —
  `[ ] ② Phase 0` → `[x]`, 다음 할 일을 Phase 1로.

**막히면 임의로 정하지 말고 보고서에 남기고 멈춘다.** 특히 기존 인프라 이관 중 "이걸 지우고
새로 깔지, 두고 정리할지"가 애매하면 지우지 말고 남긴다 — 이미 도는 기반을 건드리는 것은 신중히
한다.
