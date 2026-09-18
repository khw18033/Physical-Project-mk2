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

- **총 47건 · 완료 3 · 부분 9 · 미착수 35** (2026-09-16, Phase 3 관측 파이프라인 종료 시점)
- 완료 3건(BE-C-01·BE-T-02·**BE-S-01**)은 **동작과 허용 범위가 pytest로 보장**된 것이다
  (양성 + **음성 대조** + 실측). 각 행에 남은 범위 한계를 gap으로 적었다.
- 부분 9건: BE-T-01(LWT·인증·ACL 미구현) · BE-T-03(echo + 계측까지) · **BE-S-02**(파이프라인 3종·A층 9·
  C층 12 — 엣지 실물·인증·백엔드 span 없음) · **BE-S-03**(2계층을 임시 엣지로 실증) · **BE-S-06**(경계 표기
  규약 확정·적용) · **BE-S-07**(측정 수단만) · BE-C-02(레지스트리 관측 축까지) · BE-S-05(감사 스키마까지) ·
  BE-S-08(실행 기록 골격·append 경로까지).
- **Phase 3(관측 파이프라인)에서 바뀐 행:** BE-S-02·BE-S-03(부분 유지 — 구현·테스트가 생기고 gap이 좁아짐) ·
  **BE-S-06·BE-S-07(미착수 → 부분)** · BE-S-01(gap ③ 해소)·BE-T-02·BE-T-03(계측·systemd 추가)
  (보고: [`../../reports/2026-09-16_1900_phase3_관측파이프라인.md`](../../reports/2026-09-16_1900_phase3_관측파이프라인.md)).
- **Phase 2(저장 축)에서 바뀐 행:** BE-S-01(부분 → **완료**) · BE-C-02·BE-S-05·BE-S-08(미착수 →
  **부분**) · BE-C-01·BE-C-07·BE-S-07·BE-Q-03(gap 갱신)
  (보고: [`../../reports/2026-09-10_2200_phase2_저장축.md`](../../reports/2026-09-10_2200_phase2_저장축.md),
  Phase 1: [`../../reports/2026-09-07_1300_phase1_얇은파이프라인관통.md`](../../reports/2026-09-07_1300_phase1_얇은파이프라인관통.md)).

### ⚠ 요구사항 파일의 기준 사본 (2026-09-09 확정 — 다음 세션이 또 헤매지 않도록)

요구사항 정의서가 **세 곳에 흩어져 있고 내용이 다르다.** 파트별로 기준을 이렇게 정했다.

| 파트 | 기준 사본 | 근거 |
|---|---|---|
| **하드웨어(조병현)** | **HW 브랜치 사본** | 전체 스프레드시트와 10곳 다르고, 그 10곳이 HW의 `SRS.md` §9.11 개정 6건 + `METHODOLOGY.md` §2-5 정정 4건과 **정확히 일치**한다. 반대 방향(전체가 더 새로운 경우)은 **0건**. 게다가 그 값들은 **백엔드 아키텍처 v8을 채택한 결과**라 스프레드시트 쪽이 백엔드와 어긋나 있다 |
| 가시화(김현우) | 전체 공유 스프레드시트 | 시각화 브랜치 사본과 **0셀 차이** |
| AI(진나영) | 전체 공유 스프레드시트 | 시각화 브랜치와 0셀 차이. HW 사본은 삭제된 11건을 보유하고 `AI-C-20`·`AI-L-08`이 없다 |
| **백엔드(이대규)** | 전체 공유 스프레드시트 | 48건(47 + `BE-C-08`). `BE-C-08`은 전 Phase 종료 후 항목이므로 **이 표는 47건 기준 유지** |

→ HW에 시트 반영을 요청해 두었다: `hw-envelope-conformance.md` §6-10.
- 관측 범위가 확장됐다(2026-09-08 문서 갱신). BE-S-02는 이제 시스템 지표뿐 아니라 **백엔드
  자기 관측과 업무 값의 관측 표현**까지 포함한다 — 상태는 그대로 **부분**이나 남은 범위가
  넓어졌다. 근거는 [`00-architecture.md`](00-architecture.md) §8-3.
- ~~Phase 0으로 기반만 놓인 BE-S-02·BE-S-03은 헬스체크로 기동을 확인했을 뿐 동작과 허용 범위를 검증하는
  테스트가 없으므로 완료가 아니다~~ → **Phase 3(2026-09-16)에서 파이프라인 3종·A층·C층·페더레이션이 pytest로
  검증됐다.** 그래도 완료로 올리지 않는 이유는 각 행의 gap(엣지 실물·인증·백엔드 span·다구역)에 있다.
- 대분류: 공통 규약(C) 7 · 전송·연결(T) 8 · 번역·조립(A) 5 · 저장·관측(S) 9 · 질의·소비(Q) 4 ·
  상관·감사(X) 7 · 디지털 트윈(DT) 7
- **발표본과의 관계:** 캡스톤2 중간발표용으로 이 47건을 SRS 양식 28건으로 통합한 문서가 별도로
  있다(ECR 2·SFR 7·PER 2·SIR 4·DAR 4·TER 2·SER 2·QUR 2·COR 1·PMR 1·PSR 1). **구현과 추적의
  기준은 이 문서(47건)이며 발표본은 표현 형식**이다. 발표본 ID ↔ 기준 문서 ID 대응은 발표본 문서의
  부록 대응표에서 관리한다.
- 공통 규격 계열(BE-C-01/02/03/07)의 공통 헤더·frame_ref는 [`../../contracts/common/`](../../contracts/common/)에
  스키마로 정의됨. **2026-09-10 현재:** 공통 헤더(C-01)는 수신 검증·저장·라우팅까지 소비되고
  채널 본문 규격 6종이 신설됐다(`contracts/common/payload/`). 식별자 계층(C-02)은 레지스트리
  관측 축까지. **frame_ref(C-03)와 `origin_kind`(C-07)는 여전히 소비 구현이 없다.**

### 🆕 대응 요구사항이 없는 gap (2026-09-10 발견)

- **모델·정책·지식의 적용 승인 기록에 대응하는 BE-* 요구사항이 없다.**
  AI-L-06이 *"백엔드는 **승인 주체·시간·대상 버전과 적용 범위의 authoritative 기록**을
  담당한다"*, AI-L-08이 *"기존 백엔드 저장·감사 인프라와 연결한다"*, VZ-U-08이 *"임무 계획
  승인과 **별개 화면** — 승인 대상이 모델·정책·지식"* 을 요구하는데 **백엔드 47건 어디에도
  대응 행이 없다.** 성격은 감사(BE-S-05·BE-X-02)와 같아(누가·언제·무엇을·어떤 결과로),
  Phase 2에서 감사 테이블의 대상을 `subject_kind`(`command`|`plan`|`model`)로 **일반화해 자리만
  확보**했다(`infra/sql/mk2_mysql_schema.sql`, `tests/test_mysql_storage.py::test_audit_subject_generalized`).
  **요구사항 신설이 필요한지는 가시화 회신 후 결정**한다
  (문의: [`vz-mission-record-inquiry.md`](vz-mission-record-inquiry.md) §2-8).
  **AI에 별도 문의는 하지 않는다** — AI-L-06 자신이 *"백엔드는 승인 주체·시간·대상 버전과 적용
  범위의 authoritative 기록을 담당한다"* 로 백엔드 역할을 이미 명시하고 있어, 통지가 없어도
  AI가 다른 것을 만들 위험이 없다. 백엔드 쪽 쓰기 배선이 Phase 6이므로 그때 함께 다룬다.
  → 조치 Phase: **Phase 6**(인증·감사와 동시).

---

## 공통 규약 (C)

| ID | 소분류 | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|---|
| BE-C-01 | 공통 메시지 스키마·필드 규약 | **완료(공통 헤더 + 채널 본문 범위)** | 규격: `contracts/common/message.schema.json` **v1.1**(선택 필드 `session_id` 추가 = MINOR) + `contracts/common/payload/` **본문 규격 6종**(`state.{sensor,robot,actuator,analysis}`·`status`·`heartbeat`) / 로더: `backend/contracts.py` / 소비: `backend/ingest/envelope.py`(**느슨한 2단 검증** — 공통 헤더 → 본문), `bridge.py`(수신 즉시), `backend/settings.py::entity_type_of_mqtt_topic()`(타입 판별) / 읽기 정규화: `backend/storage/normalize.py`(규격 파일을 직접 읽어 없는 키를 채운다 — 파이썬에 목록을 다시 적지 않는다)<br>파트 회신: `docs/be/hw-envelope-conformance.md` §1(공통 헤더 4편집)·**§6-8**(본문 항목·누락값 확정 통지)<br>**누락값 규칙 적용 완료:** 구분 필요 항목은 `state`의 계측값과 `status.registration` **둘로 확정**, 나머지는 명시적 `null`<br>**gap:** ① **어휘를 `enum`으로 고정하지 않았다** — `reason`·`device_status`·`actuator_state`는 관측된 값을 `$comment`에만 적었고 검증하지 않는다(어휘가 하나 늘면 전량 격리되는 사고 회피). HW 확정 회신 대기(§6-7) ② AI·가시화 파트 정합 미확인 ③ **본문 `channel` 필드 존치 여부 미확정** — 증강 분석이 토픽 `state`에 본문 `analysis`를 보내 불일치를 기록만 한다(§6-6) | `tests/test_payload_contract.py`(34건: 4종 양성 · birth/LWT · **음성 필수누락** · 모르는 필드 통과 · analyzer 비격리 · normalize) · `tests/test_pipeline.py::test_contract_fixtures`·`::test_session_id_optional`(양성 2 + 음성 1) · `::test_invalid_quarantined`(공통 헤더 음성 2) · **`::test_payload_invalid_quarantined`(본문 음성 — 격리 + 10초 부재 관측)** |
| BE-C-02 | 식별자 계층(Entity/Node/Zone) 규약 | **부분(레지스트리 관측 축)** | 규격: `contracts/common/message.schema.json` / 저장: `infra/sql/mk2_mysql_schema.sql` — 관측 축 3(`registry_entity_observed`·`registry_node_observed`·`registry_identity_history`) + 선언 축 3(`registry_entity_declared`·`registry_node_declared`·`registry_zone`) / 쓰기: `backend/storage/registry.py` `RegistryWriter.observe()`(목적 인터페이스) + MySQL 구현 + **가드 3개**(시각·빈 문자열·이력 조건)<br>**대장의 키는 공통 헤더 `source_id`다** — 봉투가 필수로 보장하는 값이 그것뿐이고 실노드는 `entity_id`를 보내지 않는다<br>**MAC·IP는 도달성 정보이지 정체성이 아니다** — 정체성은 논리 식별자(`entity_id`·`node_id`·`zone_id`)<br>**gap:** ① **조회 API 미착수**(BE-Q-03) ② `entity_id`를 실노드가 발행하지 않아 칼럼이 항상 NULL — 노드 1:개체 N 배포에서 필요해진다(§6-5) ③ 실노드 검증은 센서만(로봇·액추에이터·증강 분석은 가짜 발행자로만) ④ **🆕 증강 분석은 관측 축에 구조적으로 들어오지 않는다** — 관측 축은 `status`의 `registration`으로만 채워지는데 `analyzer.py`는 `status`를 발행하지 않는다(`c.publish`가 `:136` 한 곳뿐). 검증 범위의 한계(③)와 달리 **나중에도 해소되지 않는 구조**다. 증강 분석 대상을 화면에 띄우려면 **선언 축에 넣어야** 한다 | `tests/test_registry_guards.py`(15건, 가드 판정 단위) · `tests/test_mysql_storage.py`(관측 축 upsert · **시각 가드 음성** · 이력 · **빈 mac/ip 음성** · 미배포 대상 조회) |
| BE-C-03 | 프레임 참조·시간 동기 규약 | 미착수 | 규격: `contracts/common/frame-reference.schema.json` (정의됨) / 소비 구현 미착수<br>**gap(2026-09-17 대조, 13시 범위 확정):** ① 시연 문서(`_hwsrc/ai_docs_260914/`)에서 **Phase 4가 취하는 논점은 하나** — 프레임·탐지가 **어느 명령의 산출인지**(BE-X-01): frame_ref에 `correlation_id` 자리를 둘지(결정 2). 시연의 "각도" 요구는 일반화하면 "프레임이 촬영 시점 자세와 정합돼야 한다"인데 **pose를 쓰는 건 DT-01·DT-04(Phase 7)** — Phase 4는 frame_ref 시각이 상태 채널과 같은 축(발행 timestamp·UTC, Phase 2 확정)인지 확인만 하고 **자세 부착 방법은 설계하지 않는다.** 시연의 정합 키 `(mission_id, rotation_deg)`·45°×8·정지 후 촬영·스캔 경계 신호는 설계 대상 아님. AI 스스로 전송안 B(RTP 스트림 + MQTT 캡처 이벤트)를 열어 뒀고 그것이 우리 미디어 경로와 같은 모양이다 ② 카메라 프리즈는 30fps가 계속 나오며 그림만 멈춘다 — 타임스탬프로 못 잡고 HW는 `sha1`/`duplicate_of_prev`로 잡는다. 미디어 헤더의 내용 해시 자리는 **후보**(기본값: 이번엔 넣지 않음, 실물 카메라 없이 검증 불가) ③ HW `capture_upload.py`가 `frame_ref_base: null`로 엣지 발급을 기대 — 오프라인 촬영본과 frame_ref의 관계(#15) | — |
| BE-C-04 | 좌표계 경계·전역 변환 규약 | 미착수 | — (디지털 트윈 DT-03과 연동) | — |
| BE-C-05 | 계약 축·미배포 대상 표현 규약 | 미착수 | — | — |
| BE-C-06 | 도메인·배포 프로파일 분리 | 미착수 | — (AI-C-15의 백엔드 짝) | — |
| BE-C-07 | 원천 종류(실물·시뮬·기록재생) 표기 규약 | 미착수 | 규격: `contracts/common/message.schema.json` `origin_kind` (정의됨) / 저장 칼럼은 준비됨(`telemetry.origin_kind`·`audit_log.origin_kind`·`mission_event.origin_kind`) / 감사 소비 미착수<br>**🆕 gap(2026-09-10):** **실노드가 `origin_kind`를 발행하지 않는다** — `pi/common/schema.py:119-134`의 `envelope()`에 그 필드가 없다. **구현 누락이 아니라 요구사항 사본이 낡은 것이다: BE-C-07이 HW 브랜치의 요구사항 정의서 사본에 없다**(전체 공유 스프레드시트에는 있다). 즉 HW는 이 항목을 애초에 받지 못했다. HW 회신 §6-5로 통지했다.<br>**기본값:** 미기재는 조회 시 **`real`(실물)로 해석**한다. 백엔드가 저장 시점에 채워 넣지 않는다 — 채우면 "생산자가 안 보낸 것"과 "백엔드가 채운 것"을 구분할 수 없다 | — (실노드 발행 전까지 검증 불가. 가짜 발행자는 옵션으로만 싣는다) |

## 전송·연결 (T)

| ID | 소분류 | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|---|
| BE-T-01 | 전송 프로토콜 확정(말단↔엣지 MQTT) | **부분** | 인프라: Mosquitto 가동 (`infra/config/mosquitto.conf`, 서버). 소비: `backend/ingest/bridge.py` — 고유 `client_id`(`mk2-ingest`)로 `+/+/+/{state,status,heartbeat}` 3패턴 구독, 텔레메트리 수용. 실노드(`sensor_node`)의 3채널 수신을 실측 확인<br>**gap:** LWT·인증(TLS)·ACL 미구현. LWT는 `status`로 흘려보내기만 하고 가용성 판정 없음(Phase 5) | `tests/test_pipeline.py::test_valid_roundtrip`(발행→수신 왕복) · 실노드 관통은 수동 확인(보고서 §검증) |
| BE-T-02 | 엣지↔백엔드 브릿지(Kafka) | **완료(단일 머신 범위)** | `backend/ingest/bridge.py`(MQTT→Kafka produce, key=`source_id`, value=원본 JSON 바이트) · `backend/settings.py`(토픽 규약 `mk2.telemetry.<채널>`, 파티션1·RF1) · 소비 측 `backend/storage/consumer.py`(`mk2-storage`)·`backend/gateway/ws_echo.py`(`mk2-ws`)로 다중 소비자 구조 실측<br>**Phase 3(2026-09-16):** 상주 3개가 systemd 유닛(`infra/systemd/`)으로 승격·enabled. 소비자 둘이 **SIGTERM에 그룹을 깨끗이 떠난다**(`consumer.close()` — 없으면 재기동 후 세션 타임아웃 45초까지 파티션 미할당, 실측 78초). 브릿지에 1초 주기 `producer.poll` 스레드(전달 콜백 즉시 처리)<br>**gap:** `advertised.listeners`가 `localhost`·포트 바인딩 `127.0.0.1:9092`라 **원격 엣지는 아직 붙지 못한다**(Phase 4 Tailscale 도입 시 3수정 — Tailscale은 Phase 3에서 서버에 설치됐다) | `tests/test_pipeline.py::test_valid_roundtrip`(key·value 동일성) · `::test_storage_sink_receives`(다중 소비자 ①) · `::test_ws_delivery`(다중 소비자 ②) · 수동: 재기동 6초 뒤 `kafka-consumer-groups --describe`에 할당(2026-09-16) |
| BE-T-03 | 가시화 클라이언트 실시간 채널 게이트웨이(WebSocket) | **부분** | `backend/gateway/ws_echo.py` — Kafka 소비자(그룹 `mk2-ws`, 저장 그룹과 독립 오프셋) + WebSocket 서버. 3토픽을 연결된 클라이언트에 push. 확인용 최소 클라이언트 `backend/gateway/console.html`. **Phase 3:** A층 `be.gateway.push`·`be.gateway.clients`(±1) 계측, systemd `mk2-ws-echo`<br>**gap:** echo까지다 — 구독 관리·인증·재접속 캐시(BE-T-06)·명령 번역 없음(Phase 5/7). 바인딩이 `127.0.0.1`이라 외부 뷰어 미연결 | `tests/test_pipeline.py::test_ws_delivery` · `tests/test_observability_pipeline.py::test_gateway_metrics_with_ws_client` |
| BE-T-04 | 장치 등록·구역 소속 및 가용성 관리(Birth/Death) | 미착수 | `backend/availability/` (예정) | — |
| BE-T-05 | 사설 IP 라우팅·프록시 중계 | 미착수 | —<br>**메모(2026-09-17 대조):** 라우팅 근거는 논리 식별자(`node_id`·`zone_id`)와 Tailscale 주소이지 **MAC이 아니다**(BE-C-02 — MAC·IP는 도달성 정보). HW `schema.py` `_mac()` 주석은 "BE-T-05가 MAC↔구역 매핑을 쓴다"로 알고 있고, VZ 요구사항정의서 §7.5도 "백엔드 옛 MAC 매핑 라벨 정정"을 남겨 뒀다. **Phase 4가 이 행을 채울 때 명시하고 HW 회신에 넣는다** | — |
| BE-T-06 | 재접속 시 현재값 즉시 제공(백엔드 캐시) | 미착수 | `backend/gateway/` (예정) | — |
| BE-T-07 | 미디어 뷰어 중계 | 미착수 | `backend/gateway/` 또는 별도 미디어 모듈 (예정) | — |
| BE-T-08 | 엣지↔서버 보안 오버레이 | 미착수 | `infra/` (Tailscale 구성) (예정)<br>**메모(2026-09-17 VZ 관측 회신):** 이 행은 엣지↔서버 **터널**(tailnet 안)의 TLS·인증이다. VZ가 "브라우저 자체 지표 발신을 Phase 4 Tailscale·BE-T-08과 함께 열어 달라"고 했으나 **브라우저는 tailnet 밖**이라 이 행의 대상이 아니다 — 서버↔뷰어는 WSS+인증(02-media-path §1-5-0). 브라우저 관측 입구(Collector HTTP 공개 vs 게이트웨이 중계)는 **Phase 4 결정 7**에서 어느 행의 인증에 얹을지 정한다 | — |

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
| BE-S-01 | 시계열·상태 이력 저장 | **완료(계측 저장 범위)** | **제품: TimescaleDB**(PostgreSQL 16.15 + timescaledb 2.30.0 Community, `127.0.0.1:7859`) / 스키마: `infra/sql/mk2_tsdb_schema.sql` — `telemetry` 하이퍼테이블(시간축 = 발행 `timestamp`) + 유일 키 + 인덱스 3 / 구현: `backend/storage/tsdb_writer.py`(**저장 제품이 드러나는 유일한 파일**) / 인터페이스: `backend/storage/writer.py` `TelemetryWriter.write()` — **호출부 무변경**(`consumer.py`·`bridge.py` 한 줄도 안 바뀜) / 구성: `MK2_TELEMETRY_WRITERS`(기본 `tsdb,jsonl` — **TSDB가 운영 저장·원본**, JSONL은 관측용 흔적) / 검출: `docs/be/queries/gap-detection.sql`(조회 시 `LAG()`, 판정 4갈래)<br>**보장되는 동작:** ① **시간축 = 발행 시각** — 지연 도착이 원래 측정 시각 자리에 정렬(실측 `lag_s=420.527`) ② `ingest_at`·`received_at`·`lag_s`·`clock_skew`·`replayed` 보관, **음수 lag를 버리지 않는다**(실측 `-29.388`) ③ **재소비 중복을 스트림 좌표 유일 키가 흡수**(실측 `346 → 346`) ④ 유실·역전 **검출은 조회 시점**에 하고 채널별로 의미를 가른다 ⑤ 세션 타임존 불변 ⑥ 원본 메시지 전체가 `payload` JSONB에<br>**gap:** ① **보존 기간·압축·재난 구간 아카이브 없음** — BE-S-04가 별도 요구사항이고 발동 조건 미충족(`00-architecture.md` §8-5). hypertable로 만들어 두어 정책만 붙이면 된다 ② **실노드 검증 부분적** — TSDB에 들어 있는 실노드 데이터는 Phase 1 센서 구간(2026-09-07 12:16~12:32, heartbeat 193건)뿐이고 그것은 Phase 1 ingest가 만든 것이라 **Kafka 헤더가 없어 `ingest_at`·`entity_type`·`lag_s`가 NULL**이다. **새 ingest를 통한 실노드 관통은 HW 편집 4개 적용 후 가능**(§6-3). 로봇·액추에이터·증강 분석은 가짜 발행자로만 검증 ③ ~~적재 실패 건수를 세는 계측이 없다~~ → ✅ Phase 3 A층 `be.storage.write{outcome="fail"}`(`tsdb_writer._fail()`)로 센다 ④ Kafka 토픽을 지웠다 다시 만들면 오프셋이 0부터 재시작해 옛 행과 충돌할 수 있다(확률 낮음, 기록만)<br>**업무 데이터의 원본 저장 위치가 여기다** — 같은 값의 관측 표현은 파생이며 원본을 대체하지 않는다(`00-architecture.md` §8-3) | `tests/test_tsdb_storage.py`(7건: 적재·`ts` 정렬 · **지연 도착** · replayed·lag · **clock_skew 보존** · **스트림 좌표 중복 흡수** · 세션 tz 불변 · **DDL·UPDATE·DELETE 음성**) · `tests/test_gap_detection.py`(11건: 갭 · **세션 경계 비갭** · birth 폴백 · **status 제외 음성** · analysis 제외 · heartbeat 비유실 · 로봇 정체 · 다운샘플 힌트 · buffer 대조) · `tests/test_storage_record.py`(9건, 파생값 단위) · `tests/test_pipeline.py::test_storage_sink_receives` |
| BE-S-02 | OTel 관측 파이프라인(Agent+Gateway) | **부분** | **Gateway(서버 Collector):** `infra/config/otel-collector-config.yaml`(서버, digest 고정 v0.150.1) — **파이프라인 3종** `metrics`→Prometheus(8889) · `traces`→`otlp_grpc` `tempo:4317` · `logs`→`otlp_http` `http://loki:3100/otlp` + `batch`. Loki v13/tsdb·보존 14d, Tempo `block_retention` 168h(`infra/README.md` §5-0)<br>**어댑터:** `backend/observability.py` — `opentelemetry`를 import하는 유일한 파일(원칙 1). no-op 규율(엔드포인트 비움·SDK 없음·초기화 실패 → 업무 경로 계속) · 라벨 가드 **`ValueError`**(금지 7종 + A층 `source_id`·`zone_id`·`entity_type`) · 계기 캐시 · `be.pipeline.lag` View 버킷 · OTel Logs SDK 핸들러(→ Loki)<br>**A층 9종**(`component`·`channel`·`outcome`·`stage`, `source_id` 없음): `be.ingest.received`·`be.ingest.rejected{stage}`(`bridge.py`) · `be.kafka.produce{outcome}`(`_on_delivery` + 1초 poll 스레드) · `be.storage.consumed`·`be.pipeline.lag`(`consumer.py`) · `be.storage.write{outcome}`(`tsdb_writer.py`) · `be.registry.observe{outcome}`(`registry.py`) · `be.gateway.push`·`be.gateway.clients`(`ws_echo.py`). `service.name` = `be-ingest`·`be-storage`·`be-gateway`<br>**C층 12종**(`source_id`·`zone_id`·`entity_type`·`channel`): `backend/storage/derive.py` — 대상은 `contracts.observation_hints()`가 규격 `$comment`에서 읽는다(파이썬 목록 없음). 저장 소비자 안, 저장 성공 여부와 무관, 예외 삼킴. counter 힌트 3개는 절대 누적값이라 gauge 계기. `null`·`{value:null}`·부재는 기록 안 함<br>**Agent→Gateway 사슬 실증:** 임시 엣지(컴퓨터, Tailscale) Collector가 log·trace 원본을 서버 Collector(Tailscale 바인딩)로 넘겨 Loki(`service_name=hw-sensor-node`)·Tempo(`service.name` 태그값)에 도달, `be-*`와 구분 확인(2026-09-16). 바인딩·ufw는 검증 후 되돌림<br>**상주:** `infra/systemd/mk2-*.service` 3개(A층의 전제)<br>**gap — 완료로 올리지 않는 이유:** ① **Agent는 컴퓨터 대역이고 전용 엣지 장비가 없다. 엣지 OTLP 수신단에 인증·TLS가 없다**(BE-T-08, Phase 4 — 그래서 Tailscale 바인딩을 검증 뒤 주석으로 내렸다) ② **B층 실 지표는 `HW_OTEL_ENDPOINT`가 꺼져 있어 가짜 발신(`tests/edge_probe_publisher.py`)으로만 검증** ③ **백엔드 span 생산은 Phase 6** — Tempo 경로는 pytest 가짜 span 1건으로만 ④ C층 log/event 10개는 Phase 5 ⑤ `state.analysis` 3종은 생산자(증강 분석)가 돌지 않아 가짜 값만 ⑥ `LoggingHandler` deprecation(SDK 1.44) — 패키지 교체는 Phase 4 ⑦ **(2026-09-17 VZ 회신) 브라우저 자체 지표의 발신 입구가 없다** — Collector는 gRPC 4317만 열려 있고 브라우저는 tailnet 밖·gRPC 불가. VZ는 OTLP/HTTP 4318+CORS 개방을 요청. A(HTTP+CORS 공개) / B(WSS 게이트웨이 중계) / C(답만) — **Phase 4 결정 7**. ⑧ **라벨 금지 목록 확장 대기** — VZ 식별자 6종(`mission_id`·`node_ref`·`client_request_id`·`plan_id`·`event_key`·발화 원문; `node_id`는 물리 노드라 제외). README·`FORBIDDEN_LABELS`·테스트 함께, Phase 4 구현. 우리 통지의 "15초 — HW와 같다"는 HW `config.py` 기본값이고 HW-C-05는 60초(발신자 몫, 무관) | `tests/test_observability_labels.py`(45: **금지 라벨 거부 음성 N1** · **A층 source_id 거부 음성 N2** · 허용 통과 · no-op) · `tests/test_c_layer_extract.py`(24: 27/22 검산 · 12종 이름 · **null 미기록 음성 N4** · 타입 무관 status 이름) · `tests/test_observability_pipeline.py`(7: A층 5종 차분 · **rejected{stage=payload} 증가** · C층 출현+**null 시계열 0** · 게이트웨이 · Loki · **가짜 span→Tempo** · `be_*`에 `agg_layer` 없음) · `tests/test_observability_isolation.py`(4: **죽은 엔드포인트·빈 엔드포인트에서 저장 지속 N3** · 파생 예외 격리) · 수동: Collector 정지 중 TSDB +3 (2026-09-16) |
| BE-S-03 | 관측 저장 계층화(엣지 로컬 + 페더레이션 요약) | **부분** | `infra/config/prometheus.yml`(서버) — `otel_collector` 잡 5s(global 1s 무변경), **`edge_federate` 잡**(`honor_labels: true` · 15s · `/federate` · `match[]` = `hw_.*`·`system_(cpu\|memory)_.*`) — **임시 엣지(컴퓨터, prometheus 3.9.1 + otelcol-contrib 0.150.1, Tailscale)로 2계층 실증**(2026-09-16): 엣지 Prometheus가 raw(`hw_*`·`system_*`·`go_*`) 보관, 중앙은 요약만 당김. 검증 뒤 잡을 **주석으로 내림**(엣지 실물이 오면 주소만 교체) · 엣지 설정 사본 `_serverinfo/edge_probe_260916/`(gitignore)<br>**음성 대조(2026-09-16 실측):** `match[]` 밖(`go_*`·`system_filesystem`·`up`·`scrape_*`)이 `agg_layer="edge"`로 **0건**(원칙 14) · `agg_layer` 없는 `hw_*`/`system_*` **0건**(Agent metrics가 OTLP 직송으로 새지 않음) · `match[]`에 `up`·생사·치명 오류 없음(원칙 6)<br>**gap:** ① 전용 엣지 장비·다구역 미검증(발동 조건 `00-architecture.md` §8-5 — 구역 2개 이상) ② Tailscale은 팀 공용 계정이고 컴퓨터가 엣지 대역 ③ Prometheus 보존은 CLI 기본 15d에 기댐 | `tests/test_observability_pipeline.py::test_central_series_have_no_agg_layer`(중앙 직접 수집분에 `agg_layer` 없음) · 수동: 서버 질의 8건(`reports/2026-09-16_1900_phase3_관측파이프라인.md` 단계 8) |
| BE-S-04 | 재난 구간 업무 데이터 장기 보존(지속 학습 재료) | 미착수 | `backend/storage/` (예정)<br>**🆕 받을 자리는 준비돼 있다(2026-09-10):** Phase 2가 `telemetry`를 **하이퍼테이블로** 만들어 두어(`infra/sql/mk2_tsdb_schema.sql`) **보존·압축 정책만 붙이면 된다** — 처음부터 만드는 것이 아니다. 이번에 정책을 걸지 않은 것은 **발동 조건이 아직 아니기 때문**이다(`00-architecture.md` §8-5). ⚠ **Kafka retention과 헷갈리지 않는다** — 장기 보존은 TSDB 사안이다(원칙 11) | — |
| BE-S-05 | 감사 중앙 저장(MySQL 직행 예외) | **부분(스키마까지)** | `infra/sql/mk2_mysql_schema.sql` — `mk2.audit_log` 테이블(17칼럼 + 인덱스 4). **대상 일반화**: `subject_kind`(`command`\|`plan`\|`model`) + `subject_id` — `command_id` 전용으로 좁히지 않았다(AI-L-06/07/08·VZ-U-08의 모델 승인 기록 자리 확보)<br>**수정·삭제를 권한이 막는다**: `mk2_app`에 `SELECT, INSERT`만. 요약·필터를 전제한 구조를 만들지 않았다(원칙 5)<br>**gap:** ① **쓰기 경로가 없다** — 명령이 실제로 흘러 들어가게 하지 않았다(§6 울타리) ② **actor 주입(토큰에서)·서버 시각 주입은 Phase 6** — 인증(BE-Q-04)이 감사의 선행조건이다 ③ 감사 이력 조회 API(BE-Q-02) 미착수 ④ **🆕 `actor_kind` 어휘가 `mission_event`와 다르다**(2026-09-14 발견) — 이 테이블 COMMENT는 `user|system|ai 등`인데 `mission_event`는 VZ-D-02 원문대로 `ai|backend|human`이다(`user`↔`human`, `system`↔`backend`). 같은 이름·같은 개념·다른 어휘라 **되감기 화면에서 임무 사건과 감사를 겹쳐 보면 같은 주체가 다르게 표기된다.** 이쪽은 *"등"* 이 붙어 있고 쓰기가 Phase 6이라 **그때 통일**한다 | `tests/test_mysql_storage.py::test_audit_subject_generalized`(`command`·`model` 두 행이 같은 테이블에) · `::test_mission_event_update_denied`(**`audit_log` UPDATE·DELETE 음성**) · `::test_ddl_denied` |
| BE-S-06 | 집약 계층 경계 표기 | **부분** | **규약 확정(2026-09-16):** 엣지 Prometheus가 `global.external_labels`로 **`agg_layer="edge"`**(+`zone_id`)를 붙이고, 중앙 페더레이션 잡이 `honor_labels: true`로 보존한다. **중앙이 직접 수집한 시계열에는 `agg_layer`가 없다 — 부재가 곧 "중앙 원본".** 중앙 `global.external_labels`는 건드리지 않는다(분류 ② 접촉 최소화). 적용: `infra/config/prometheus.yml` `edge_federate` 잡(주석 상태) · 엣지 설정 `_serverinfo/edge_probe_260916/prometheus.yml`<br>**실증:** 서버에서 `hw_publish_count_total{agg_layer="edge",zone_id="zoneA"}` 조회, `be_*`에는 `agg_layer` 없음(2026-09-16)<br>**gap:** 다구역에서의 표기 확장(구역별 `zone_id`·엣지 여러 대) 미검증 — 발동 조건은 BE-S-03과 같다 | `tests/test_observability_pipeline.py::test_central_series_have_no_agg_layer`(부재 = 중앙, 음성) · 수동: 페더레이션 시계열 `agg_layer="edge"` 질의 |
| BE-S-07 | 재난 모드 지연 상한(SLA) | **부분(측정 수단)** | **측정 수단이 생겼다(2026-09-16):** `be.pipeline.lag` 히스토그램(`backend/storage/consumer.py::observe_lag`) — `TelemetryRecord.lag_s`를 **새로 계산하지 않고 그대로** 관측 평면에 올린다. 버킷 `0.1 0.5 1 5 15 60 300 1800 7200 86400`(실측 범위 -30 ~ 344,000초). **음수(clock_skew)는 버리지 않는다** — OTel 히스토그램이 음수를 받지 않아(규격) 절대값 + `outcome="clock_skew"` 라벨로 보존(사용자 결정, 안 A). Prometheus `be_pipeline_lag_seconds_{bucket,sum,count}{component,channel,outcome}`<br>저장 재료(Phase 2): `telemetry.lag_s`(= `ingest_at - ts`) · 실측 `-29.388` ~ `2836.224`초, retained `status` 재유입은 ~434,000초<br>**gap:** ① **상한을 판정·경보하는 로직이 없다** — 값만 쌓인다 ② 재난 고주기 실측은 Tier C ③ **`clock_skew` 임계를 이번에 확정하지 못했다** — `lag_s`가 채워진 행이 적고 양 끝(`-30.000`·retained 재유입 344,000초)이 전부 인공물이라 분포를 정할 재료가 못 된다. A층으로 쌓은 뒤 **Phase 5에서 확정** | `tests/test_observability_pipeline.py::test_a_layer_metrics_increase_after_publish`(`be_pipeline_lag_seconds_count` 증가) · `tests/test_observability_labels.py::test_lag_buckets_cover_measured_range`·`::test_counter_rejects_negative_and_histogram_drops_negative_quietly` · 값 보관은 `tests/test_tsdb_storage.py::test_replayed_and_lag`·`::test_clock_skew_kept_not_dropped` |
| BE-S-08 | 임무 실행 추적 기록 저장·시점 복원 | **부분(골격·append 경로)** | `infra/sql/mk2_mysql_schema.sql` — `mk2.mission_event` 테이블(17칼럼 + 인덱스 4 + `event_key` UNIQUE) / `backend/storage/mission.py` — `append_mission_event()` **재삽입 멱등**(중복 오류 1062만 골라 잡는다. `INSERT IGNORE`를 쓰지 않는 이유는 값 잘림 같은 다른 오류까지 삼키기 때문)<br>**append-only를 권한이 지킨다**: `mk2_app`에 `SELECT, INSERT`만 — BE-S-08 원문 *"수정·삭제하지 않으며"* 를 코드 규율이 아니라 DB가 지킨다<br>**설계 판단:** ① 「계층·노드」를 **DAG 축**으로 읽었다(`layer`·`node_ref`), 물리 대상은 `target_entity_id` 하나 ② 상태를 값으로 저장하지 않고 **사건 열에서 파생** ③ `event_type`을 `ENUM`으로 박지 않았다(실패 단계 어휘 미확정) ④ **`actor_kind`는 `NOT NULL`**(2026-09-14 정정 — VZ-D-02 *"산출 주체를 반드시 포함"*. 처음 `NULL`로 만든 것이 오독. 서버는 root ALTER로 반영, `build_params()`도 필수 인자 + 빈 값 `ValueError`)<br>**gap:** ① **실제 쓰기 배선이 없다** — 생산자는 가시화·엣지이고 Phase 6/7이다. 지금 부르는 것은 테스트뿐 ② ~~구체 필드·실패 단계 어휘·보존 기간·되감기 질의 미확정~~ → ✅ **VZ 회신 받음(2026-09-17, [`received/2026-09-17_vz-mission-record-reply.md`](received/2026-09-17_vz-mission-record-reply.md))** — 골격 맞음(재작성 없음). 실패 4단계 `plan_failed`·`dispatch_failed`·`execution_failed`·`evaluation_failed` · `node_ref`·`mission_id` VZ 부여(판마다 새 `mission_id`) · 보존 무기한(요약 불가) · 8종 파생·구간 계산 VZ · `event_key`=`{mission_id}:{VZ 순번}`. **새 gap(Phase 6 이월, plan Phase 6 참조):** ㉠ **임무 정의(태스크 목록·마일스톤 소속·deps·대상) 저장 자리가 없다** — 사건 열만으로 되감기·격리 불가. 형태는 우리가 정한다 ㉡ `layer`에 `mission` 추가(COMMENT만) ㉢ `subject_kind` 3종 방식 ㉣ `origin_kind` 발행 주체(원천이 붙인다 — VZ는 소비자) ㉤ `correlation_id`는 뒤따르는 사건으로 ③ **파티셔닝 없음**(보존 무기한이라 경계는 운영 판단) ④ ⚠ **`seq`는 단조 증가하지만 연속이 아니다**(실패한 INSERT도 AUTO_INCREMENT를 소비. 실측 `2→4→5`) — VZ가 확인했다(연속을 가정하지 않는다) | `tests/test_mission_event.py`(10건, 파라미터 정규화 단위 — **`actor_kind` 누락·빈 값 음성** 포함) · `tests/test_mysql_storage.py::test_mission_event_idempotent`(같은 키 1행 / 키 없는 사건 둘 다) · `::test_mission_event_update_denied`(**UPDATE·DELETE 음성**) |
| BE-S-09 | 미디어 저장 모드·이벤트 캡처 | 미착수 | — (현재 배포는 중계만)<br>**유예 항목** — 저장 배포 선택 시 설계(아키텍처 §8-5). 사건 이전 구간 확보를 위한 **엣지 단기 버퍼는 필요**하며 "상시 링버퍼 배제"로 읽히지 않도록 읽는다<br>**gap(2026-09-17 대조, HW #15):** HW가 주행 중 촬영본(10fps JPEG 464×400, **0.7GB/h**)을 매니페스트(`kind: capture_session`)+tar.gz로 묶어 S3 호환 PUT 할 업로더(`capture_upload.py`)를 만들어 두고 **목적지를 백엔드에 묻는 중** — 온디맨드 스트림(BE-T-07)도 이벤트 캡처(이 행 원문)도 아닌 **오프라인 데이터셋 일괄 적재**라 자리가 없었다. **사용자 결정 ㉡(2026-09-17, 13시 범위 확정): 이 행의 저장 모드 한 갈래로 수용. Phase 4에서는 「저장소 자체」까지** — 수신 방식(S3 호환 PUT을 서버가 받나·엣지 경유)·저장 위치·메타 자리(MySQL 한 행)·보존 규칙·`frame_ref_base`와의 관계·회신. 검증은 가짜 업로더(HW 매니페스트 모양의 합성 tar.gz)로 "받아서 놓인다"까지. **실제 HW 데이터 적재·운영과 AI 저장본과의 관계 정리는 그 뒤.** Phase 4 마지막 독립 단계(무거우면 4b 분리). 그전까지 HW 기본값(파이 로컬 적재)이 맞다 | — |

## 질의·소비 (Q)

| ID | 소분류 | 상태 | 구현 위치 | 테스트 |
|---|---|---|---|---|
| BE-Q-01 | 지표 질의 프록시 | 미착수 | `backend/gateway/` 또는 질의 모듈 (예정) | — |
| BE-Q-02 | 감사 이력 조회 API | 미착수 | — | — |
| BE-Q-03 | 구성(레지스트리) 조회 API | 미착수 | (BE-C-02·BE-T-04와 레지스트리 구성)<br>**🆕 저장은 섰다(2026-09-10):** **선언 축 3 + 관측 축 3** 테이블이 `infra/sql/mk2_mysql_schema.sql`에. **축이 둘인 이유가 이 요구사항이다** — BE-Q-03·VZ-I-03이 *"값을 발행하지 않는 **미배포 대상**도 이 목록으로 화면에 표시"* 를 요구하는데, 텔레메트리에서 자동으로 채우면 미배포 대상이 영원히 안 나타난다. **선언 축은 사람이 넣는다**(`mk2_app`은 `SELECT`만). 조회 예시: `docs/be/queries/registry-declared-vs-observed.sql` — 기준(FROM)이 선언 축이고 관측 축을 LEFT JOIN으로 얹는다(방향이 뒤집히면 미배포 대상이 사라진다)<br>**확장:** 대상이 수행 가능한 action 목록(capability)을 포함한다 — 진나영 AI-C-18 선언을 **논리 식별자(entity/source) 기준**으로 등록. BE-A-01(액션 번역)·김현우 VZ-D-07(대상 상태 조회)이 소비<br>**gap:** ① **조회 API 자체가 미착수** — 지금 있는 것은 커밋된 `.sql` 파일이지 API가 아니다(Phase 5/6) ② **capability 등록(AI-C-18) 미착수** ③ 원점 배치(`registry_node_declared.origin`)를 JSON으로 둔 것은 **좌표계 규약(BE-C-04)이 미확정**이라서다 — 확정 후 칼럼 승격 | `tests/test_mysql_storage.py::test_registry_declared_visible_without_telemetry`(**미배포 대상이 조회에 나오고**, 선언 축 행이 하나도 빠지지 않으며, 관측만 있는 개체는 반대 질의에 나온다) |
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
