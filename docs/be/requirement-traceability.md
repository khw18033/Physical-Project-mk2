# 백엔드 요구사항 추적표 (담당: 이대규)

요구사항 정의서(엑셀) 이대규 시트 47건의 ID별 구현 위치·테스트·충족 여부를 기록한다.
코드를 추가할 때마다 해당 행의 **상태 · 구현 위치 · 테스트**를 갱신한다(코드 docstring 상단의
`implements: BE-X-NN` 태그와 짝을 이룬다 — [`../../CLAUDE.md`](../../CLAUDE.md) 코드 규약).

아키텍처 맥락은 [`00-architecture.md`](00-architecture.md), 미디어 경로 상세는
[`02-media-path.md`](02-media-path.md).

## 상태 값

- **미착수** — 아직 구현하지 않음.
- **부분** — 핵심 일부만 구현, 명시된 gap 있음.
- **완료** — 요구사항이 정의한 동작과 허용 범위가 테스트로 보장됨. 완료 판정은 특정 기술 사용
  여부가 아니라 **시스템 동작과 허용 범위가 실제로 보장되는지**로 한다.

## 요약

- **총 47건 · 완료 2 · 부분 5 · 미착수 40**
- 완료 2건(BE-C-01·BE-T-02)은 Phase 1(얇은 파이프라인 관통)에서 **동작과 허용 범위가 pytest로
  보장**된 것이다(양성 왕복 + 음성 격리 + 실노드 관통). 각 행에 남은 범위 한계를 gap으로 적었다
  (보고: [`../../reports/2026-09-07_1300_phase1_얇은파이프라인관통.md`](../../reports/2026-09-07_1300_phase1_얇은파이프라인관통.md)).
- 부분 5건: BE-T-01(LWT·인증·ACL 미구현) · BE-T-03(echo까지) · BE-S-01(placeholder까지) ·
  BE-S-02·BE-S-03(Phase 0 인프라 기반만, 테스트 없음).
- 관측 범위가 확장됐다(2026-09-08 문서 갱신). BE-S-02는 이제 시스템 지표뿐 아니라 **백엔드
  자기 관측과 업무 값의 관측 표현**까지 포함한다 — 상태는 그대로 **부분**이나 남은 범위가
  넓어졌다. 근거는 [`00-architecture.md`](00-architecture.md) §8-3.
- Phase 0으로 기반만 놓인 BE-S-02·BE-S-03은 헬스체크로 기동을 확인했을 뿐 동작과 허용 범위를 검증하는
  테스트가 없으므로 **완료가 아니다**
  (보고: [`../../reports/2026-09-04_1620_phase0_인프라기동.md`](../../reports/2026-09-04_1620_phase0_인프라기동.md)).
- 대분류: 공통 규약(C) 7 · 전송·연결(T) 8 · 번역·조립(A) 5 · 저장·관측(S) 9 · 질의·소비(Q) 4 ·
  상관·감사(X) 7 · 디지털 트윈(DT) 7
- **발표본과의 관계:** 캡스톤2 중간발표용으로 이 47건을 SRS 양식 28건으로 통합한 문서가 별도로
  있다(ECR 2·SFR 7·PER 2·SIR 4·DAR 4·TER 2·SER 2·QUR 2·COR 1·PMR 1·PSR 1). **구현과 추적의
  기준은 이 문서(47건)이며 발표본은 표현 형식**이다. 발표본 ID ↔ 기준 문서 ID 대응은 발표본 문서의
  부록 대응표에서 관리한다.
- 공통 규격 계열(BE-C-01/02/03/07)의 공통 헤더·frame_ref는 [`../../contracts/common/`](../../contracts/common/)에
  스키마로 정의됨 — 규격 자체는 존재하나 이를 소비하는 백엔드 구현(수신 검증·저장·라우팅)은 미착수.

---

## 공통 규약 (C)

| ID | 소분류 | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|---|
| BE-C-01 | 공통 메시지 스키마·필드 규약 | **완료(공통 헤더 범위)** | 규격: `contracts/common/message.schema.json` (기준) / 소비: `backend/ingest/envelope.py`(규격 파일을 직접 로드해 strict 검증 + 격리), `backend/ingest/bridge.py`(수신 즉시 검증)<br>파트 회신: `docs/be/hw-envelope-conformance.md`(HW 공통 헤더 정합 4편집 — 실노드로 검증)<br>**gap:** 채널 본문(payload) 스키마는 미정의(공통 헤더만 검증) · AI·가시화 파트 정합은 미확인 · 채널 본문의 누락값 표현 규칙은 확정됐으나(`contracts/common/README.md` "값이 없을 때의 표현") **적용할 본문 규격 자체가 미정** — Phase 2에서 항목 목록 확정 후 생산자 파트에 확정 | `tests/test_pipeline.py::test_contract_fixtures`(양성 1 + 음성 2) · `::test_valid_roundtrip` · `::test_invalid_quarantined`(zone_id 누락 / `+0900` 포맷 → 토픽에 안 뜨고 격리) |
| BE-C-02 | 식별자 계층(Entity/Node/Zone) 규약 | 미착수 | 규격: `contracts/common/message.schema.json` (정의됨) / 레지스트리 구현 미착수 | — |
| BE-C-03 | 프레임 참조·시간 동기 규약 | 미착수 | 규격: `contracts/common/frame-reference.schema.json` (정의됨) / 소비 구현 미착수 | — |
| BE-C-04 | 좌표계 경계·전역 변환 규약 | 미착수 | — (디지털 트윈 DT-03과 연동) | — |
| BE-C-05 | 계약 축·미배포 대상 표현 규약 | 미착수 | — | — |
| BE-C-06 | 도메인·배포 프로파일 분리 | 미착수 | — (AI-C-15의 백엔드 짝) | — |
| BE-C-07 | 원천 종류(실물·시뮬·기록재생) 표기 규약 | 미착수 | 규격: `contracts/common/message.schema.json` `origin_kind` (정의됨) / 감사 소비 미착수 | — |

## 전송·연결 (T)

| ID | 소분류 | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|---|
| BE-T-01 | 전송 프로토콜 확정(말단↔엣지 MQTT) | **부분** | 인프라: Mosquitto 가동 (`infra/config/mosquitto.conf`, 서버). 소비: `backend/ingest/bridge.py` — 고유 `client_id`(`mk2-ingest`)로 `+/+/+/{state,status,heartbeat}` 3패턴 구독, 텔레메트리 수용. 실노드(`sensor_node`)의 3채널 수신을 실측 확인<br>**gap:** LWT·인증(TLS)·ACL 미구현. LWT는 `status`로 흘려보내기만 하고 가용성 판정 없음(Phase 5) | `tests/test_pipeline.py::test_valid_roundtrip`(발행→수신 왕복) · 실노드 관통은 수동 확인(보고서 §검증) |
| BE-T-02 | 엣지↔백엔드 브릿지(Kafka) | **완료(단일 머신 범위)** | `backend/ingest/bridge.py`(MQTT→Kafka produce, key=`source_id`, value=원본 JSON 바이트) · `backend/settings.py`(토픽 규약 `mk2.telemetry.<채널>`, 파티션1·RF1) · 소비 측 `backend/storage/consumer.py`(`mk2-storage`)·`backend/gateway/ws_echo.py`(`mk2-ws`)로 다중 소비자 구조 실측<br>**gap:** `advertised.listeners`가 `localhost`·포트 바인딩 `127.0.0.1:9092`라 **원격 엣지는 아직 붙지 못한다**(Phase 4 Tailscale 도입 시 3수정) | `tests/test_pipeline.py::test_valid_roundtrip`(key·value 동일성) · `::test_storage_sink_receives`(다중 소비자 ①) · `::test_ws_delivery`(다중 소비자 ②) |
| BE-T-03 | 가시화 클라이언트 실시간 채널 게이트웨이(WebSocket) | **부분** | `backend/gateway/ws_echo.py` — Kafka 소비자(그룹 `mk2-ws`, 저장 그룹과 독립 오프셋) + WebSocket 서버. 3토픽을 연결된 클라이언트에 push. 확인용 최소 클라이언트 `backend/gateway/console.html`<br>**gap:** echo까지다 — 구독 관리·인증·재접속 캐시(BE-T-06)·명령 번역 없음(Phase 5/7). 바인딩이 `127.0.0.1`이라 외부 뷰어 미연결 | `tests/test_pipeline.py::test_ws_delivery` |
| BE-T-04 | 장치 등록·구역 소속 및 가용성 관리(Birth/Death) | 미착수 | `backend/availability/` (예정) | — |
| BE-T-05 | 사설 IP 라우팅·프록시 중계 | 미착수 | — | — |
| BE-T-06 | 재접속 시 현재값 즉시 제공(백엔드 캐시) | 미착수 | `backend/gateway/` (예정) | — |
| BE-T-07 | 미디어 뷰어 중계 | 미착수 | `backend/gateway/` 또는 별도 미디어 모듈 (예정) | — |
| BE-T-08 | 엣지↔서버 보안 오버레이 | 미착수 | `infra/` (Tailscale 구성) (예정) | — |

## 번역·조립 (A)

| ID | 소분류 | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|---|
| BE-A-01 | 액션 어휘집(디바이스 명령 번역) | 미착수 | — | — |
| BE-A-02 | 액추에이터 명령 번역(수문·차수벽·펌프) | 미착수 | — (하천 배포 프로파일) | — |
| BE-A-03 | 메인 임무 하달(전역 종합 → 엣지) | 미착수 | — (Phase 6 예정)<br>**범위 재정의:** 임무 분해는 가시화(VZ-G)가 담당하므로 백엔드는 DT-07 판단 결과의 하달 경로만. 구 AI-D-01/D-02 참조는 무효(삭제됨) | — |
| BE-A-04 | 위험 판정 기반 제어 발행 | 미착수 | — (AI-R-02 수신 — 구 AI-R-03은 존재하지 않음) | — |
| BE-A-05 | 환경 사전정보 제공 | 미착수 | — | — |

## 저장·관측 (S)

| ID | 소분류 | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|---|
| BE-S-01 | 시계열·상태 이력 저장 | **부분** | `backend/storage/writer.py` — 목적 인터페이스 `TelemetryWriter.write(record)` + **Phase 1 placeholder**(`JsonlTelemetryWriter`). `backend/storage/consumer.py`(그룹 `mk2-storage`)가 3토픽을 구독해 `store(...)` 호출. 공통 헤더 `timestamp`(발행 시각)와 `received_at`(서버 수신 시각)을 분리 보존<br>**gap:** 실제 TSDB 제품·스키마·retention 미정(Phase 2). 시각 기준 정렬·지연 도착 정합(`replayed:true`)·`sequence_id` 기반 유실 검출 미구현 · **업무 데이터의 원본 저장 위치가 여기다** — 같은 값의 관측 표현은 파생이며 원본을 대체하지 않는다(`00-architecture.md` §8-3) | `tests/test_pipeline.py::test_storage_sink_receives`(발행값이 sink 기록에 도달) |
| BE-S-02 | OTel 관측 파이프라인(Agent+Gateway) | **부분** | `infra/config/otel-collector-config.yaml` (서버) — Collector 가동, **metric 파이프라인만** 동작(OTLP 수신 → Prometheus exporter)<br>**gap: `logs`·`traces` 파이프라인 없음.** Loki·Tempo가 각각 직접 수신 중이라 기준(Collector가 log→Loki, trace→Tempo 분배)과 다르다. `batch` processor도 없음 · 계측 대상 3층(A 백엔드 자기 관측 / B 말단 노드 / C 업무 값의 관측 표현)이 §8-3에 정의됐으나 **어느 층도 계측 미착수** — Phase 3. 특히 **백엔드 자신을 관측하는 A층이 현재 전무**하다 | — (Phase 0 헬스체크로 기동만 확인: OTLP 포트 수신, 정상 로그) |
| BE-S-03 | 관측 저장 계층화(엣지 로컬 + 페더레이션 요약) | **부분** | `infra/config/prometheus.yml` (서버) — 단일 Prometheus 가동, Collector scrape 동작<br>**gap:** 엣지 raw 보관 + 중앙 페더레이션 요약 2계층 없음. `scrape_interval: 1s`로 기준(15초~1분)과 상이 | — (Phase 0 헬스체크로 기동만 확인: `/-/healthy`, 타깃 up) |
| BE-S-04 | 재난 구간 업무 데이터 장기 보존(지속 학습 재료) | 미착수 | `backend/storage/` (예정) | — |
| BE-S-05 | 감사 중앙 저장(MySQL 직행 예외) | 미착수 | `backend/storage/` (MySQL) (예정) | — |
| BE-S-06 | 집약 계층 경계 표기 | 미착수 | — | — |
| BE-S-07 | 재난 모드 지연 상한(SLA) | 미착수 | —<br>**gap:** 지연 상한을 재는 수단이 없다 — 백엔드 자기 관측(`00-architecture.md` §8-3 A층)이 그 측정 수단이며 Phase 3. 재난 고주기 실측 자체는 Tier C | — |
| BE-S-08 | 임무 실행 추적 기록 저장·시점 복원 | 미착수 | `backend/storage/` (Phase 2 — 테이블 골격·append 경로)<br>**저장 축 확정:** MySQL 별도 테이블(감사와 분리, append-only)<br>**gap:** 구체 필드·실패 단계 어휘·보존 기간은 소비자(VZ-D-02·D-04) 확정 후 합의 | — |
| BE-S-09 | 미디어 저장 모드·이벤트 캡처 | 미착수 | — (현재 배포는 중계만)<br>**유예 항목** — 저장 배포 선택 시 설계(아키텍처 §8-5). 사건 이전 구간 확보를 위한 **엣지 단기 버퍼는 필요**하며 "상시 링버퍼 배제"로 읽히지 않도록 읽는다 | — |

## 질의·소비 (Q)

| ID | 소분류 | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|---|
| BE-Q-01 | 지표 질의 프록시 | 미착수 | `backend/gateway/` 또는 질의 모듈 (예정) | — |
| BE-Q-02 | 감사 이력 조회 API | 미착수 | — | — |
| BE-Q-03 | 구성(레지스트리) 조회 API | 미착수 | — (BE-C-02·BE-T-04와 레지스트리 구성)<br>**확장:** 대상이 수행 가능한 action 목록(capability)을 포함한다 — 진나영 AI-C-18 선언을 **논리 식별자(entity/source) 기준**으로 등록. BE-A-01(액션 번역)·김현우 VZ-D-07(대상 상태 조회)이 소비 | — |
| BE-Q-04 | **인증**·역할·범위 조회 및 권한 강제(RBAC) | 미착수 | — (Phase 6, 감사와 동시)<br>**확장:** 인증(로그인·토큰 발급/검증)을 포함한다 — 감사(BE-X-02)의 "actor는 토큰에서" 전제조건<br>역할 강제는 캡스톤 포함, 구역 범위 강제는 국가 인프라 축이되 가능하면 캡스톤에서도 적용 | — |

## 상관·감사 (X)

| ID | 소분류 | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|---|
| BE-X-01 | 상관키(command_id) 발급·매핑 | 미착수 | — (Phase 6)<br>**확장:** 가시화의 **클라이언트 요청 식별자·유효기한**을 받아 command_id와 매핑하고(김현우 VZ-O-01), 동일 command_id 재전달 시 물리 실행을 반복하지 않는다(멱등, AI-C-20) | — |
| BE-X-02 | 감사 기록 작성(actor·시각 주입) | 미착수 | `backend/storage/` (MySQL) (예정) | — |
| BE-X-03 | 명령 결과 4단계 승격 | 미착수 | — (Phase 6)<br>**확장:** 진행 4단계는 유지하되 **수락/거부를 별도 결과로**, **취소는 요청 수락과 완료를 구분**, **긴급정지는 일반 취소와 구분**한다(진나영 AI-C-20 근거). `physical:false` 설정 명령의 완료 승격 매핑을 함께 확정 | — |
| BE-X-04 | 계획 승인 워크플로우 중계 | 미착수 | — | — |
| BE-X-05 | AI 실패 이벤트 중계 | 미착수 | — (AI-O-02 수신) | — |
| BE-X-06 | AI 프로세스 실행 관리 접점 | 미착수 | — (실제 배포는 엣지 K3s) | — |
| BE-X-07 | 제어 잠금(control_lock) 상태 산출 | 미착수 | `backend/availability/` (예정) | — |

## 디지털 트윈 (DT)

| ID | 소분류 | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|---|
| DT-01 | 트윈 좌표 위치 융합(불확실도 가중) | 미착수 | `backend/twin/` (예정) | — |
| DT-02 | 클래스 베이지안 융합 | 미착수 | `backend/twin/` (예정) | — |
| DT-03 | 디지털 트윈 반영(좌표 변환 포함) | 미착수 | `backend/twin/` (예정) | — |
| DT-04 | 커버리지 맵·사각지대 산출 | 미착수 | `backend/twin/` (예정) — AI-E-02 보정 결과 소비 | — |
| DT-05 | 트윈 시의성(staleness) 판정 | 미착수 | `backend/twin/` (예정) | — |
| DT-06 | 교차 구역 핸드오프·전역 트윈 | 미착수 | `backend/twin/` (Phase 7)<br>**규격:** 구역 내 track ID는 AI(AI-S-06)가, **전역 객체 ID는 백엔드**가 부여·매핑한다. `contracts/common/object-reference.schema.json` 참조 | — |
| DT-07 | 로봇 투입 결정 | 미착수 | `backend/twin/` (Phase 7)<br>**입력 확장:** 사각지대·최신성·현재 임무 상태에 더해 **AI의 추가 관측 요청**(진나영 AI-S-05)을 입력으로 받는다. 구 AI-D-01 참조는 무효(삭제됨 — 임무 분해는 가시화 VZ-G가 인수) | — |

---

## 갱신 규칙

- 코드를 추가하면 그 파일 docstring 상단에 `implements: BE-X-NN`을 남기고, 이 표의 해당 행
  **상태 · 구현 위치 · 테스트**를 함께 갱신한다.
- "구현 위치 (예정)"은 계획상 배치이며 실제 구현 시 정확한 파일 경로로 교체한다.
- 상태를 **완료**로 올릴 때는 반드시 그 동작과 허용 범위를 검증하는 테스트를 함께 명시한다(테스트 없는
  완료 판정 금지).
- 타 파트가 소유하고 백엔드가 소비/연동만 하는 항목(예: AI-R-02 수신, AI-O-02 수신)은 연동
  지점이 동작하는지를 기준으로 판정한다.
