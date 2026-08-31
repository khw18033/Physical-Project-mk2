# Physical Project mk2 — 백엔드 (BE) 파트

국가 인프라 전제의 **엣지-클라우드 관측 백엔드 + 디지털 트윈**. 담당: 이대규.

센서·이동체·엣지·AI가 발행하는 데이터를 **성격(업무·관측·영상)에 따라** 저장·중계·번역하고,
여러 구역의 트윈을 종합해 관제 화면과 로봇 임무 판단으로 잇는다. 특정 장치·프로토콜·저장 제품을
핵심에 고정하지 않고, MQTT·Kafka·OpenTelemetry·K3s·Tailscale은 **어댑터 뒤의 현재 배포
선택**으로 둔다(교체 가능).

이 저장소는 하나의 프로젝트를 파트별 브랜치로 나눠 개발한다. 이 문서는 `ldg_BE`(백엔드)
브랜치 기준이다.

## 핵심 원칙

- **데이터 성격이 채널을 결정한다** — 업무=MQTT(말단)/Kafka(백본), 관측=OpenTelemetry, 영상=별개
  미디어 경로, 브라우저=WebSocket. 기능이 늘어도 채널은 안 늘어난다("채널 선택의 결정론화").
- **부하가 구역 수에 비례한다** — 엣지가 브로커·수집기·관측 raw를 1차 수용해 중앙 부하를 억제한다.
- **파트 경계의 기준은 JSON Schema다** — 각 파트의 내부 타입이 아니라
  [`contracts/common/`](contracts/common/)의 공통 계약이 정본. 백엔드가 공통 봉투·식별자·상관키를
  소유한다.
- **상태는 성격별로 분리 저장한다** — 계측 시계열은 TSDB, 감사·레지스트리는 MySQL, 관측은
  Prometheus/Loki/Tempo. 트윈·명령 진행·가용성은 저장하지 않고 실시간 push한다.
- **국가 인프라급으로 설계하고, 캡스톤은 특수 사례로 자동 포함된다** — 각 결정을 "추상 요구 +
  현재 배포 프로파일"로 서술한다.

## 담당 범위 — 요구사항 요약 (BE-* 47건)

상세 정의는 요구사항 정의서(엑셀) 이대규 시트, 구현·테스트 추적은
[요구사항 추적표](docs/be/requirement-traceability.md)를 기준으로 한다.

| 구분 | ID | 수 | 요약 | 상태 |
|---|---|---:|---|---|
| 공통 규약 | BE-C | 7 | 공통 봉투·식별자 계층·frame_ref·좌표·계약축·도메인 프로파일·원천 종류 | 계약 정의됨 / 소비 미착수 |
| 전송·연결 | BE-T | 8 | 말단 MQTT·엣지 Kafka 브릿지·WS 게이트웨이·장치 등록/가용성·사설IP·재접속 캐시·미디어 중계·보안 오버레이 | 미착수 |
| 번역·조립 | BE-A | 5 | 액션 어휘집·액추에이터 명령·메인 임무 하달·위험 판정 제어·환경 사전정보 | 미착수 |
| 저장·관측 | BE-S | 9 | 시계열 저장·OTel 파이프라인·관측 계층화·재난 보존·감사 MySQL·집약 표기·재난 SLA·임무 추적·미디어 저장 | 미착수 |
| 질의·소비 | BE-Q | 4 | 지표 프록시·감사 조회·레지스트리 조회·RBAC | 미착수 |
| 상관·감사 | BE-X | 7 | command_id·감사 작성·4단계 승격·계획 승인·AI 실패 중계·실행 관리 접점·제어 잠금 | 미착수 |
| 디지털 트윈 | DT | 7 | 위치 융합·클래스 융합·트윈 반영·커버리지/사각지대·시의성·핸드오프·로봇 투입 | 미착수 |

**총 47건 · 완료 0 · 미착수 47.** 공통 계약(봉투·frame_ref)은 스키마로 정의됐고, 이를 소비하는
백엔드 구현은 착수 전이다. 상세 상태는 [추적표](docs/be/requirement-traceability.md).

## 저장소 구조

```text
Physical-Project-mk2/            (ldg_BE 브랜치)
├── backend/                     백엔드 코드
│   ├── ingest/                  MQTT 구독 → Kafka 브릿지 (엣지 소비자)
│   ├── storage/                 TSDB writer + MySQL writer (2축 저장)
│   ├── availability/            가용성 판정기 (MQTT 세션 우선)
│   ├── gateway/                 WS 게이트웨이 (Kafka 소비자 + WebSocket 서버)
│   └── twin/                    디지털 트윈 (좌표 융합·커버리지·시의성)
├── contracts/common/           파트 간 JSON Schema 계약 (백엔드 소유)
│   ├── message.schema.json      공통 봉투
│   ├── frame-reference.schema.json  frame_ref
│   └── examples/                정상 메시지 예제
├── infra/                      docker-compose · OTel Collector · Grafana 등 설정
├── docs/be/                    아키텍처 · 구현 계획 · 요구사항 추적
├── reports/                    작업 단위 보고서 (YYYY-MM-DD_HHMM_주제.md)
├── tests/                      파이프라인 검증 (pytest)
└── CLAUDE.md                   Claude Code 작업 규칙 + 요구사항 참조
```

## 아키텍처 개요 (5구간)

```text
[말단]          [구역 엣지노드]           [중앙 서버(백엔드)]          [사용자(가시화)]
센서/로봇/     Mosquitto(MQTT)          Kafka(다중 소비자 팬아웃)     관제 화면(브라우저)
카메라/       MQTT→Kafka 브릿지         ├─ AI 추론 / TSDB / 트윈       Grafana(개발용)
액추에이터  ─┐  OTel Collector           ├─ MySQL(감사·레지스트리)
  │  업무    │  엣지 Prometheus          ├─ 가용성 통합(업무평면 우선)
  ├─MQTT────▶│  K3s                      ├─ Collector(Gateway)→Loki·Tempo
  │  관측    │      │  ══ Tailscale ═════ │  WS 게이트웨이(서버 안)
  ├─OTLP────▶│      ├─Kafka──────────────▶│  = Kafka 소비자 + WebSocket 서버 ─▶ 화면
  │  영상    │      ├─페더레이션 요약─────▶│  질의 프록시 ◀── 조회
  └─RTP/UDP─▶│      └─영상 WS(방식 B)─────▶│  중계 ─WSS+인증─▶ 뷰어(영상+오버레이)
```

- **엣지↔서버는 단일 Tailscale 터널**을 업무·관측·영상이 공유한다(논리 채널은 분리).
- **WS 게이트웨이는 서버 내부 컴포넌트**다 — Kafka 소비자이면서 WebSocket 서버. 브라우저는
  Kafka를 모르고 이 게이트웨이하고만 대화한다.

상세는 [아키텍처 정본](docs/be/00-architecture.md), 미디어 경로는
[미디어 경로 문서](docs/be/02-media-path.md).

## 저장 결정 요약

| 데이터 | 저장소 | 비고 |
|---|---|---|
| 센서 계측·로봇 상태 추이·액추에이터 상태 추이 | **TSDB** (InfluxDB/TimescaleDB 후보, 제품 미확정) | 시간축 위 수치 |
| 명령 감사·계획 승인 | **MySQL** (감사 테이블) | 요약·필터 없이 전량 직행, 위조 불가 |
| 장치·구역·식별자 등록 | **MySQL** (레지스트리 테이블) | 준정적 관계 |
| metric / log / trace | Prometheus / Loki / Tempo | 관측 평면(별개) |
| 트윈 상태·명령 진행·장치 가용성 | 저장 안 함 (WS push) | 도착 즉시 화면으로 밀어줌 |

RBAC·MongoDB는 채택하지 않는다. 미디어(영상) 저장 여부는 미결(현재 배포는 중계만).

## 구현 계획

무엇을 어떤 순서로 만드는지는 [구현 착수 계획](docs/be/01-standalone-implementation-plan.md)에
있다. 핵심: **백엔드 스택은 거의 전부 소프트웨어라 지금 한 대에서 검증 가능**하고, 두 팀원의
발행자(조병현 `sensor_node.py`, 진나영 `VirtualRiverTerminal`)가 실 센서·실 AI 없이 파이프라인을
관통시킬 재료를 제공한다.

Phase 0 인프라 기동 → Phase 1 얇은 파이프라인 관통 → Phase 2 저장 2축 → Phase 3 관측 파이프라인 →
Phase 4 미디어 경로 → Phase 5 가용성 판정기 → Phase 6 상관·감사·명령 → Phase 7 디지털 트윈.

**지금 당장 할 일:** ① 공통 계약 확정(완료) → ② 인프라 스택 compose 기동(Phase 0) → ③ 가짜
발행자로 파이프라인 관통(Phase 1).

## 설치와 실행

> 코드 착수 전이라 실행 절차는 Phase 0(인프라 기동) 구현 시 채운다. 인프라 스택(Kafka·Mosquitto·
> OTel Collector·Prometheus·Grafana·Loki·Tempo·MySQL·TSDB)은 `infra/` 아래 Docker Compose로
> 정의·기동할 예정이다. 검증은 Phase 0은 헬스체크, Phase 1부터 pytest.

## 다른 파트와 통합

파트 경계의 단일 기준은 내부 타입이 아니라 [공통 계약](contracts/common/README.md)이다.

- **하드웨어(조병현):** 봉투(BE-C-01/02)·frame_ref(BE-C-03)를 따르는 발행자. `source_id` 정본
  확정으로 `LEGACY_DEVICE_ID` 과도기 종료.
- **AI(진나영):** 공통 봉투·식별자·시간 규약을 따른다(AI-C-01). AI 쪽 `contracts/ai/` 봉투는 이
  계약에 정렬. 가용성 최종 판정은 백엔드(진나영 `simulation/backend.py` mock을 실물로 교체).
- **가시화(김현우):** 뷰어가 canvas 표시·탐지 오버레이(frame_ref 정합). 미디어 뷰어 출력 담당은
  백엔드 중계 / 가시화 표시로 확정(VZ-I-06 해소).

## 남은 검증 (실 하드웨어·현장 필요 — Tier C)

- 미디어 회선 QoS·온디맨드 콜드스타트 지연 실측(현장 좁은 회선)
- Tailscale 직접 연결/DERP 폴백 실측(현장 엣지-서버 배치)
- Unity 트윈 렌더 정합(가시화 파트 통합 후)
- 실 센서·실 AI 통합(가짜 발행자로 계약·경로 검증까지 완료 후)
- 재난 SLA 지연 상한 실측(재난 고주기 실데이터)

## 공개 저장소 보안

이 저장소는 **Public**이다.

- 실제 `.env`·토큰·비밀번호·개인키·인증서·내부망 endpoint를 커밋하지 않는다(`.gitignore`가 차단).
- 예제 설정에는 placeholder만 쓰고 운영 값은 환경변수/secret manager로 주입한다.
- 영상·재현 데이터에 개인정보·위치정보·비공개 시설 정보가 없는지 별도 확인한다.
- 공개 push 전 staged diff와 비밀정보 패턴을 점검한다.
