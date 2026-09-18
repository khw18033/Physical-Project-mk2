# Physical Project mk2 — 백엔드 (BE) 파트

국가 인프라 전제의 **엣지-클라우드 관측 백엔드 + 디지털 트윈**. 담당: 이대규.

센서·이동체·엣지·AI가 발행하는 데이터를 **성격(업무·관측·영상)에 따라** 저장·중계·번역하고,
여러 구역의 트윈을 종합해 관제 화면과 로봇 임무 판단으로 잇는다. 특정 장치·프로토콜·저장 제품을
핵심에 고정하지 않고, MQTT·Kafka·OpenTelemetry·K3s·Tailscale은 **지금 쓰는
구현(교체 가능)**으로 둔다.

이 저장소는 하나의 프로젝트를 파트별 브랜치로 나눠 개발한다. 이 문서는 `ldg_BE`(백엔드)
브랜치 기준이다.

## 핵심 원칙

- **데이터 성격이 채널을 결정한다** — 업무=MQTT(말단)/Kafka(백본), 관측=OpenTelemetry, 영상=별개
  미디어 경로, 브라우저=WebSocket. 기능이 늘어도 채널은 안 늘어난다("채널 선택의 결정론화").
  관측 평면에는 시스템 지표뿐 아니라 **업무 값의 관측 표현**도 파생으로 실린다 — 전송을
  대체하는 것이 아니라 사본 성격의 신호가 추가되는 것이다(아키텍처 §8-3).
- **부하가 구역 수에 비례한다** — 엣지가 브로커·수집기·관측 raw를 1차 수용해 중앙 부하를 억제한다.
- **파트가 나뉘는 지점의 기준은 JSON Schema다** — 각 파트의 내부 타입이 아니라
  [`contracts/common/`](contracts/common/)의 공통 규격이 기준. 백엔드가 공통 헤더·식별자·상관키를
  소유한다.
- **상태는 성격별로 분리 저장한다** — 계측 시계열은 TSDB, 감사·레지스트리·임무 실행 기록은
  MySQL(테이블 분리), 관측은 Prometheus/Loki/Tempo. 트윈·명령 진행·가용성은 저장하지 않고
  실시간 push한다.
- **국가 인프라급으로 설계하고, 캡스톤은 특수 사례로 자동 포함된다** — 각 결정을 "추상 요구 +
  현재 배포 프로파일"로 서술한다.
- **백엔드 자신도 관측한다** — 장치만 관측하면 "장치가 안 보내는 것"과 "백엔드가 못 받는 것"을
  구분할 수 없다.

## 담당 범위 — 요구사항 요약 (BE-* 47건)

상세 정의는 요구사항 정의서(엑셀) 이대규 시트, 구현·테스트 추적은
[요구사항 추적표](docs/be/requirement-traceability.md)를 기준으로 한다.

| 구분 | ID | 수 | 요약 | 상태 |
|---|---|---:|---|---|
| 공통 규약 | BE-C | 7 | 공통 헤더·식별자 계층·frame_ref·좌표·계약축·도메인 프로파일·원천 종류 | 완료 1 · 부분 2 · 미착수 4 |
| 전송·연결 | BE-T | 8 | 말단 MQTT·엣지 Kafka 브릿지·WS 게이트웨이·장치 등록/가용성·사설IP·재접속 캐시·미디어 중계·보안 오버레이 | 완료 1 · 부분 4 · 미착수 3 |
| 번역·조립 | BE-A | 5 | 액션 어휘집·액추에이터 명령·메인 임무 하달·위험 판정 제어·환경 사전정보 | 미착수 5 |
| 저장·관측 | BE-S | 9 | 시계열 저장·OTel 파이프라인·관측 계층화·재난 보존·감사 MySQL·집약 표기·재난 SLA·임무 추적·미디어 저장 | 완료 1 · 부분 7 · 미착수 1 |
| 질의·소비 | BE-Q | 4 | 지표 프록시·감사 조회·레지스트리 조회·RBAC | 미착수 4 |
| 상관·감사 | BE-X | 7 | command_id·감사 작성·4단계 승격·계획 승인·AI 실패 중계·실행 관리 접점·제어 잠금 | 미착수 7 |
| 디지털 트윈 | DT | 7 | 위치 융합·클래스 융합·트윈 반영·커버리지/사각지대·시의성·핸드오프·로봇 투입 | 미착수 7 |

**총 47건 · 완료 3 · 부분 13 · 미착수 31** (2026-09-19, Phase 4 종료 시점).
완료는 BE-C-01(공통 헤더 범위)·BE-T-02(단일 머신 범위 + 원격 엣지 EDGE 리스너 실증)·BE-S-01(계측
저장 범위)이며 pytest로 보장됐다(양성 + 음성 대조 + 실측). 부분 13건은 BE-T-01·BE-T-03·**BE-T-07**·
**BE-T-08**·BE-C-02·**BE-C-03**·BE-S-02·BE-S-03·BE-S-05·BE-S-06·BE-S-07·BE-S-08·**BE-S-09**이다(굵은 넷이
Phase 4에서 미착수 → 부분). 각 행의 남은 범위와 gap은 [추적표](docs/be/requirement-traceability.md).

## 저장소 구조

```text
Physical-Project-mk2/            (ldg_BE 브랜치)
├── backend/                     백엔드 코드
│   ├── ingest/                  MQTT 구독 → Kafka 브릿지 (엣지 소비자)
│   ├── storage/                 TSDB writer + MySQL writer (계측 / 감사·레지스트리·실행 기록)
│   ├── availability/            가용성 판정기 (MQTT 세션 우선)
│   ├── gateway/                 WS 게이트웨이 (Kafka 소비자 + WebSocket 서버) — ws_echo.py(/state·/media·/ingest) · media.py(방식 B·drop-old)
│   └── twin/                    디지털 트윈 (좌표 융합·커버리지·시의성)
├── contracts/common/           파트 간 JSON Schema 규격 (백엔드 소유)
│   ├── message.schema.json      공통 헤더
│   ├── frame-reference.schema.json  frame_ref
│   ├── media-header.schema.json  미디어 헤더(방식 B, Phase 4) — frame_ref 를 $ref 로 품는다
│   ├── detections.schema.json   탐지 좌표·정합 선언(초안 — AI·VZ 회신 뒤 payload/ 로)
│   ├── object-reference.schema.json  지속 객체 참조(object_id)
│   ├── payload/                 채널 본문 규격 6종
│   └── examples/                정상·음성 예제
├── infra/                      docker-compose · OTel Collector · Grafana 등 설정
├── docs/be/                    아키텍처 · 구현 계획 · 요구사항 추적
├── reports/                    작업 단위 보고서 (YYYY-MM-DD_HHMM_주제.md)
├── tests/                      파이프라인 검증 (pytest)
└── CLAUDE.md                   Claude Code 작업 규칙 + 요구사항 참조
```

## 아키텍처 개요 (5구간)

```text
[말단]          [구역 엣지노드]           [중앙 서버(백엔드)]          [사용자(가시화)]
센서/로봇/     Mosquitto(MQTT)          Kafka(다중 소비자 구조)       관제 화면(브라우저)
카메라/       MQTT→Kafka 브릿지         ├─ AI 추론 / TSDB / 트윈       Grafana(개발용)
액추에이터  ─┐  OTel Collector           ├─ MySQL(관계형 축)
  │  업무    │  엣지 Prometheus          ├─ 가용성 통합(업무평면 우선)
  ├─MQTT────▶│  K3s                      ├─ Collector(Gateway)→Loki·Tempo
  │  관측    │      │  ══ Tailscale ═════ │  WS 게이트웨이(서버 안)
  ├─OTLP────▶│      ├─Kafka──────────────▶│  = Kafka 소비자 + WebSocket 서버 ─▶ 화면
  │  영상    │      ├─페더레이션 요약─────▶│  질의 프록시 ◀── 조회
  └─RTP/UDP─▶│      └─영상 WS(방식 B)─────▶│  중계(drop-old) ─ws+토큰─▶ 뷰어(디코드+오버레이)
   (native 코덱) AU 재조립·frame_ref        헤더만 읽음        (tailnet 안. 밖이면 WSS — Phase 6)
```

- **엣지↔서버는 단일 Tailscale 터널**을 업무·관측·영상이 공유한다(논리 채널은 분리). **Phase 4
  (2026-09-19)에서 미디어·Kafka·관측이 실제로 한 터널을 타는 것을 컴퓨터 임시 엣지로 실측**했다.
- **WS 게이트웨이는 서버 내부 컴포넌트**다 — Kafka 소비자이면서 WebSocket 서버. 브라우저는
  Kafka를 모르고 이 게이트웨이하고만 대화한다.

상세는 [아키텍처 기준 문서](docs/be/00-architecture.md), 미디어 경로는
[미디어 경로 문서](docs/be/02-media-path.md).

## 저장 결정 요약

| 데이터 | 저장소 | 비고 |
|---|---|---|
| 센서 계측·로봇 상태 추이·액추에이터 상태 추이 | **TSDB** (InfluxDB/TimescaleDB 후보, 제품 미확정) | 시간축 위 수치 |
| 명령 감사·계획 승인 | **MySQL** (감사 테이블) | 요약·필터 없이 전량 직행, 위조 불가 |
| 임무 실행 기록(사건 열·되감기) | **MySQL** (실행 기록 테이블) | append-only 사건 열, 표시 상태는 파생 |
| 장치·구역·식별자 등록 | **MySQL** (레지스트리 테이블) | 준정적 관계 |
| metric / log / trace | Prometheus / Loki / Tempo | 관측 평면(별개) |
| 업무 값의 관측 표현(파생) | Prometheus | **원본 아님** — 관측·가시화용. 원본은 TSDB(계측)·MySQL(감사) |
| 트윈 상태·명령 진행·장치 가용성 | 저장 안 함 (WS push) | 도착 즉시 화면으로 밀어줌 |

**MongoDB는 현재 채택 없음**이며 영구 배제가 아니다 — 타당한 근거가 있을 때만 도입한다.
**인가(RBAC)는 채택한다** — 다만 저장 모델 축이 아니라 조회·명령 경로의 강제 축이라 이 표에
없다(BE-Q-04, 구현은 Phase 6). 미디어(영상) 스트림 저장은 미결(현재 배포는 중계만)이고, 로봇
**촬영본(정지 촬영 세션)은 파일시스템 + MySQL 메타 한 행**으로 받는다(Phase 4 4b, `02-media-path.md` §1-3-4).

## 구현 계획

무엇을 어떤 순서로 만드는지는 [구현 착수 계획](docs/be/01-standalone-implementation-plan.md)에
있다. 핵심: **백엔드 스택은 거의 전부 소프트웨어라 지금 한 대에서 검증 가능**하고, 두 팀원의
발행자(조병현 `sensor_node.py`, 진나영 `VirtualRiverTerminal`)가 실 센서·실 AI 없이 파이프라인을
관통시킬 재료를 제공한다.

Phase 0 인프라 기동 → Phase 1 얇은 파이프라인 관통 → Phase 2 저장 축 → Phase 3 관측 파이프라인 →
Phase 4 미디어 경로 → Phase 5 가용성 판정기 → Phase 6 상관·감사·명령 → Phase 7 디지털 트윈.

**지금 당장 할 일:** ① 공통 규격 확정(완료) → ② 인프라 스택 compose 기동(Phase 0, 완료
2026-09-04) → ③ 가짜 발행자로 파이프라인 관통(Phase 1, 완료 2026-09-07) → ④ 저장 축
(Phase 2, 완료 2026-09-10 — TimescaleDB 계측 저장 + 감사·레지스트리 MySQL) → ⑤ 관측
파이프라인(Phase 3, 완료 2026-09-16 — A층 9종·C층 12종·Collector 분배·2계층 페더레이션
실증) → ⑥ 미디어 경로(Phase 4, 완료 2026-09-19 — 엣지→서버→뷰어 방식 B 중계(native 코덱·GOP
인지 drop-old·터널 위 `ws`+토큰)와 frame_ref 바이트 관통이 서버 pytest + 컴퓨터 임시 엣지 실측으로
닫혔고, 회신·통지 3건(HW·VZ·AI)과 4b 촬영본 저장소(8767) 개통) → **⑦ 가용성 판정기(Phase 5) ← 다음**.

## 설치와 실행

**Phase 0(인프라 기동) 완료 — 2026-09-04.** MK2 스택 9개가 서버에서 가동 중이다(Phase 2에서 TimescaleDB 추가). 운영 상세는
[`infra/README.md`](infra/README.md), 작업 경위는
[Phase 0 보고서](reports/2026-09-04_1620_phase0_인프라기동.md).

### 인프라 스택 9개

| 구성요소 | 역할 (5구간) | 상태 |
|---|---|---|
| Mosquitto | 엣지 MQTT 브로커 — 말단 업무 발행·명령 하달 수용 (구간 1·2) | 기존 가동 |
| **Kafka** | 엣지↔서버 업무 백본 + 서버 다중 소비자 구조 (구간 3·4) | **Phase 0에서 신규 설치** |
| OTel Collector | 관측 3종(metric·log·trace) 수집·분배 — metric→Prometheus·log→Loki·trace→Tempo (구간 2·4) | 기존 가동 — Phase 3에서 파이프라인 3종·digest 고정 |
| Prometheus | 관측 metric 저장·요약 (구간 2·3) | 기존 가동 |
| Loki | log 저장 (구간 4) | 기존 가동 — Phase 3에서 v13/tsdb·보존 14d |
| Tempo | trace 저장 (구간 4) | 기존 가동 — Phase 3에서 보존 168h |
| MySQL | 감사·레지스트리·임무 실행 기록·촬영본 세션 메타 — 관계형 저장 축 (구간 4) | 기존 가동 — Phase 2에서 `mk2` DB 신설, Phase 4에서 `media_capture` 추가 |
| **TimescaleDB** | 계측 시계열 저장 — 센서·로봇 상태 추이 (구간 4, BE-S-01) | **Phase 2에서 신규 설치** |
| Grafana | 개발용 종착지 (구간 5) | 기존 가동 |

**TSDB는 TimescaleDB로 확정됐다**(Phase 2, 2026-09-10) — PostgreSQL 16 + timescaledb 2.30 Community, `telemetry` 하이퍼테이블. 제품이 드러나는 파일은 `backend/storage/tsdb_writer.py` 하나다.
**MongoDB는 스택에 없다** — 현재 채택 없음이며 필요해지면 근거와 함께 재검토한다.
**RBAC는 채택했으나 스택 구성요소가 아니다** — 조회·명령 경로의 강제 축이라 Phase 6
(인증·감사)에서 구현한다(BE-Q-04).

### 포트

| 서비스 | 외부 | 내부 |
|---|---|---|
| Mosquitto | 1883 | 1883 |
| Kafka | 9092 *(현재 로컬 바인딩)* | 9092 · 9093(controller) · 9094(internal) |
| MySQL | 7858 | 3306 |
| Prometheus | 7861 | 9090 |
| Grafana | 7862 | 3000 |
| Loki | 3100 | 3100 |
| Tempo | 3200 · 4317(OTLP) | 3200 · 4317 |
| OTel Collector | 4316 *(로컬 바인딩)* | 4317 · 8889(exporter, 미공개) |
| **WS 게이트웨이**(호스트 python) | **8765** `/state`·`/media` *(loopback + 서버 tailscale 주소, 토큰)* | — |
| 엣지 미디어 입구(호스트 python) | 8766 `/ingest` *(tailscale 주소 — Phase 4 실측 뒤 `MK2_MEDIA_INGEST_PORT=0`으로 닫아 둠)* | — |
| Kafka EDGE 리스너 | 9095 *(tailscale 주소 — 실측 뒤 compose 주석, 실 엣지 시 되살림)* | 9095 |
| **촬영본 PUT 입구**(호스트 python, 4b) | **8767** `/capture` *(tailscale 주소, ufw pi7 `/32`, 토큰)* | — |

> **4316 / 4317** — OTLP gRPC 표준 포트는 4317인데 Tempo가 그 포트를 직접 받고 있어, OTel
> Collector가 4316으로 밀렸다. **Phase 3(2026-09-16)에서 Collector가 log→Loki·trace→Tempo를
> 분배하도록 정리했고, 호스트 포트 번호는 4316 그대로 두었다** — 구조 정리와 포트 재배치는
> 별개 사안이며 후자는 필요하지 않았다(`infra/README.md` §3 ⓐ·ⓑ).

### 기동과 헬스 확인

서버의 compose 디렉터리에서:

```bash
docker compose up -d <서비스명>     # 서비스명을 반드시 명시 (아래 주의)
docker compose ps
```

> ⚠️ `docker compose up -d`를 서비스명 없이 실행하면 compose 파일의 모든 서비스가 대상이 되어,
> `:latest` 태그를 쓰는 기존 서비스가 재생성될 수 있다. **이미 도는 것을 건드리지 않는 것이 이
> 스택의 원칙이다.**

헬스 확인 명령 8종은 [`infra/README.md`](infra/README.md) §4에 있다. 예를 들어 Kafka는
토픽 생성·조회·삭제로, Mosquitto는 발행 성공으로, Prometheus·Grafana·Loki·Tempo는 각자의
헬스 엔드포인트로 판정한다.

**검증 수단:** Phase 0은 헬스체크(pytest 아님). **Phase 1부터 pytest**로 "가짜 발행자 →
파이프라인 → 예상 저장/중계" 회귀를 검증한다.

### 작업 흐름 — 이 저장소는 서버에 `git pull`로 배포하지 않는다

```text
[작업 폴더]  infra/ 에서 편집
     ↓  사람이 복사
[서버]      compose 디렉터리의 실제 파일에 적용
     ↓  결과·에러를 가져옴
[작업 폴더]  수정
```

서버 실제 파일(`docker-compose.yml`, 설정 5개)의 사본을 `infra/` 아래에 두고 편집한다.
**그 사본은 평문 비밀번호와 내부망 주소를 담고 있어 커밋하지 않는다**(`.gitignore`).
저장소에 커밋되는 것은 이 README, `infra/README.md`, 보고서, 공통 규격, 문서다.

## 다른 파트와 통합

파트가 나뉘는 지점의 단일 기준은 내부 타입이 아니라 [공통 규격](contracts/common/README.md)이다.

- **하드웨어(조병현):** 공통 헤더(BE-C-01/02)·frame_ref(BE-C-03)를 따르는 발행자. `source_id`
  기준 확정으로 `LEGACY_DEVICE_ID` 과도기 종료.
- **AI(진나영):** 공통 헤더·식별자·시간 규약을 따른다(AI-C-01). AI 쪽 `contracts/ai/` 공통
  헤더는 이 규격에 정렬. 가용성 최종 판정은 백엔드(진나영 `simulation/backend.py` mock을 실물로 교체).
- **가시화(김현우):** 뷰어가 프레임을 디코드해 canvas 표시·탐지 오버레이(frame_ref 정합). 미디어 뷰어
  출력 담당은 백엔드 중계 / 가시화 표시로 확정(VZ-I-06 해소). 방식 B 형식·`frame_ref` 객체·`/media`
  연결 규약은 Phase 4 통지(`docs/be/vz-media-interface.md`)로 전달.

## 남은 검증 (실 하드웨어·현장 필요 — Tier C)

- 미디어 회선 QoS·온디맨드 콜드스타트 지연 실측(현장 좁은 회선) — **Phase 4는 연구실 배치에서 링크를
  500kbit로 조인 한 조건만** 실측(drop-old IDR 재개, 지연 p90 2.34s). 실물 엣지·실물 로봇 영상은 0장
- Tailscale 직접 연결/DERP 폴백 실측 — **연구실 환경에서는 Phase 3(DERP 72ms → 직접 3ms)·Phase 4(직접 2ms/22ms)에서 확인**. **현장 엣지-서버 배치에서의 실측은 남아 있다**
- Unity 트윈 렌더 정합(가시화 파트 통합 후)
- 실 센서·실 AI 통합(가짜 발행자로 공통 규격·경로 검증까지 완료 후)
- 재난 SLA 지연 상한 실측(재난 고주기 실데이터)

## 공개 저장소 보안

이 저장소는 **Public**이다.

- 실제 `.env`·토큰·비밀번호·개인키·인증서·내부망 endpoint를 커밋하지 않는다(`.gitignore`가 차단).
- 예제 설정에는 placeholder만 쓰고 운영 값은 환경변수/secret manager로 주입한다.
- 영상·재현 데이터에 개인정보·위치정보·비공개 시설 정보가 없는지 별도 확인한다.
- 공개 push 전 staged diff와 비밀정보 패턴을 점검한다.
