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

- **조병현 `sensor_node.py`** — 이미 BE-C-01/02 봉투 형식으로 실제 MQTT를 발행한다
  (`status`/`heartbeat`/`state`/`cmd`/`cmd/ack`/`cmd/result` 6채널). 하천 도메인(수위)이라 과업
  A(하천 감시·제어)와도 맞는다.
- **진나영 `simulation/terminals.py`의 `VirtualRiverTerminal`** — 하천/로봇 시뮬 MQTT 발행자.

이는 조병현이 실 센서 없이 가짜 수위값(`read_water_level()`)으로 파이프라인부터 뚫은 것과 같은
전략이다 — **먼저 파이프라인을 관통시키고 그 위에 기능을 얹는다.**

### 0-2. 백엔드의 허브 위치

- 방금 정의한 공통 봉투([`../../contracts/common/`](../../contracts/common/))가 세 팀원을 정렬시킨다.
  조병현 `schema.py`가 `LEGACY_DEVICE_ID`로 대기하던 것이 이 확정으로 정리된다.
- 가용성 판정(BE-T-04, "MQTT 세션 우선")은 진나영이 `simulation/backend.py` mock으로 대기 중인
  바로 그것이다 — 백엔드가 채우면 mock이 실물로 교체된다.

---

## 1. Tier 분류 — 무엇이 지금 되고 무엇이 막혀 있나

완료 판정 기준은 "특정 기술 사용 여부"가 아니라 **"요구사항이 정의한 동작과 경계가 실제로
보장되는가"**다(진나영·김현우 공통 원칙).

### Tier A — 지금 바로 구현+검증 완결 (인프라 소프트웨어 + 가짜 발행자로 100% 검증)

| 영역 | 무엇 | 검증 방법 |
|---|---|---|
| 봉투 수신 검증 (BE-C-01/02/07) | 가짜 발행자 메시지를 `message.schema.json`으로 검증·격리 | 유효/무효 fixture 쌍으로 통과·거부 확인 |
| MQTT→Kafka 브릿지 (BE-T-02) | 엣지 Mosquitto 구독 → 서버 Kafka produce | 가짜 발행자 → 브릿지 → Kafka 토픽에 도착 |
| WS 게이트웨이 (BE-T-03) | Kafka 소비자 + WebSocket 서버, 구독 push | 브라우저(콘솔)에 실시간 값 도달 |
| 저장 2축 (BE-S-01/05) | TSDB 계측 write + MySQL 감사·레지스트리 | write 후 조회로 정합 확인 |
| 가용성 판정 (BE-T-04) | MQTT LWT + 하트비트 → 세션 우선 통합 상태 | LWT/타임아웃 주입 → online/offline 판정 |
| 상관·감사 (BE-X-01/02/03) | command_id 발급, actor·시각 주입, 4단계 승격 | 명령 사슬 fixture로 상관·승격 확인 |
| 관측 파이프라인 (BE-S-02/03) | OTel Collector 수집 → Prometheus 저장/요약 | 가짜 지표 발신 → Collector → Prometheus 조회 |
| 재접속 캐시 (BE-T-06) | 채널별 캐시/비캐시, ts 원본 유지 | 재접속 시뮬 → 캐시 채널만 즉시 push |

### Tier B — 가벼운 계산/구성 필요 (실 하드웨어 불필요)

| 영역 | 무엇 | 검증 방법 |
|---|---|---|
| 미디어 온디맨드 중계 (BE-T-07) | 엣지 영상 WS(방식 B) → 서버 중계 → 뷰어 WSS | 합성 JPEG 프레임 재생으로 frame_ref 관통 확인 |
| 좌표 변환·트윈 반영 (BE-C-04/DT-03) | 이미지 좌표 → 전역 좌표 변환 로직 | 합성 좌표 fixture로 변환 정확도 검증 |
| 커버리지·사각지대 (DT-04) | FOV 바닥 투영, 사각 영역 산출 | 알려진 카메라 배치로 커버리지 계산 검증 |
| 위치·클래스 융합 (DT-01/02) | 불확실도 가중 융합, 베이지안 클래스 융합 | 합성 다중 검출 fixture로 융합 결과 검증 |

### Tier C — 실제로 막혀 있음 (타 파트/실 하드웨어/현장 필요)

| 영역 | 막힌 이유 |
|---|---|
| 미디어 회선 QoS·콜드스타트 실측 | 현장 회선(좁은 업링크)이 있어야 실측 — 로직은 Tier B로 검증 |
| Unity 트윈 렌더 연결 (VZ-U-02) | 가시화 파트 Unity 뷰어 필요 — 백엔드는 전역 좌표까지 산출 |
| Tailscale 직접 연결·DERP 폴백 실측 | 현장 엣지-서버 물리 배치 필요 — 구성은 Tier A/B |
| 실 센서·실 AI 통합 | 조병현 실 센서 입고·진나영 실 모델 — 가짜 발행자로 계약·경로 검증까지 |
| 재난 SLA 지연 상한 실측 (BE-S-07) | 재난 고주기 실데이터 필요 — 구조는 Tier A |

**요약:** mock은 *동작과 경계*를 커버하고, 커버 못 하는 것은 *현장 실측 수치와 실 하드웨어
통합*뿐이다. 하드웨어 없이도 완료 판정은 가능하며 남는 것은 실측 파라미터 확정이다.

---

## 2. Phase 순서

**우선순위 원칙:** ① 규격(계약)이 코드보다 먼저 — 이미 완료. ② 얇은 파이프라인을 끝까지 먼저
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
Phase 2  저장 2축           TSDB(계측) + MySQL(감사·레지스트리)
   ↓
Phase 3  관측 파이프라인     OTel Agent+Gateway → Prometheus/Loki/Tempo, 페더레이션   [기반 경로]
   ↓
Phase 4  미디어 경로         온디맨드 WS 중계(방식 B), frame_ref 관통, WSS+인증        [기반 경로]
   ↓
Phase 5  가용성 판정기       MQTT 세션 우선 통합(진나영 mock 대체)
   ↓
Phase 6  상관·감사·명령      command_id, actor 주입, 4단계 승격, 감사 조회
   ↓
Phase 7  디지털 트윈         DT 7건 (좌표 변환·융합·커버리지는 Tier B, Unity 연결은 Tier C)
```

### Phase 0 — 인프라 기동

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

### Phase 1 — 얇은 파이프라인 관통

**목표:** 발행자 → 백엔드 → 저장/화면이 한 줄로 관통.

- **발행자(결정 1):** 먼저 **(C) 계약(`message.schema.json`)에 맞춘 최소 발행 스크립트**를 새로
  만들어 봉투 형식만 쏜다(팀원 의존 0, 내 계약이 실제로 도는가 검증). 그다음 **(A) 조병현
  `sensor_node.py`**를 붙여 실제 팀원 발행자와도 맞물리는지 확인.
- **관통 순서(결정 2):** `backend/ingest/`가 MQTT 구독 → Kafka produce → Kafka에서 갈라져
  **① 저장 확인(TSDB write 후 조회)** → **② WS push 확인(브라우저 콘솔에 값 도달)**. 저장(A)
  먼저, 화면(B) 나중.
- **DoD:** 최소 발행자와 조병현 노드 양쪽에서, 발행한 값이 Kafka를 거쳐 저장되고 브라우저
  콘솔에 실시간으로 뜬다. 봉투 검증 실패 메시지는 격리·기록된다.
- **외부 의존성:** 조병현 `sensor_node.py`(가져와 실행 — 이미 확보).
- 관련: BE-C-01(봉투 검증)·BE-T-01(MQTT)·BE-T-02(브릿지)·BE-T-03(WS 게이트웨이).

### Phase 2 — 저장 2축

**목표:** 성격별 저장 모델이 실제로 갈라져 쌓인다.

- `backend/storage/`: 계측(센서·로봇 상태 추이)은 **TSDB**, 감사(명령 이력)·레지스트리(장치·구역·
  식별자)는 **MySQL**(테이블 분리). 타임스탬프 기준 병합·정렬, 지연 도착 데이터 정합.
- RBAC·MongoDB는 두지 않는다(정본 결정). 트윈·명령진행·가용성은 저장하지 않고 WS push.
- **Phase 0 이월:** MySQL 컨테이너는 가동 중이나 MK2 전용 DB·계정은 없다(Phase 0 범위 밖으로
  미룸). 여기서 MK2 감사·레지스트리용 DB·계정을 만든다. 기존 테스트 DB(`robot_capstone`)에
  얹지 않는다.
- **DoD:** 계측이 TSDB에 시각 순으로, 감사·레지스트리가 MySQL에 정합성 있게 쌓이고 조회로
  확인된다. 재전송(지연 도착) 데이터가 원래 측정 시각으로 정렬된다.
- **외부 의존성:** 없음.
- 관련: BE-S-01(TSDB)·BE-S-05(감사 MySQL)·BE-C-02(식별자)·BE-Q-03(레지스트리).

### Phase 3 — 관측 파이프라인 완성 [기반 경로]

**목표:** 시스템 자기 관측이 업무 데이터와 분리된 평면으로 흐른다.

- OTel Collector(Agent) 수집 → 가공 → 백엔드 Collector(Gateway) → metric은 Prometheus,
  log는 Loki, trace는 Tempo. 엣지 Prometheus raw 보관 + 페더레이션 요약 pull.
- Grafana로 확인. metric은 요약 가능(분산), log·trace는 원본 전달(요약하면 의미 깨짐).
- **DoD:** 가짜 지표 발신 → Collector → Prometheus 저장·조회, 페더레이션 요약이 당겨지는 것
  확인. 치명 오류·장치 생사 신호가 일반 metric 요약에 섞이지 않고 개별 유지.
- **외부 의존성:** 없음(조병현 HW-C-05 실 지표는 나중, 지금은 가짜 발신).
- **Phase 0 이월 (현재 서버 관측 스택의 실제 상태 — 정본과의 gap):**
  - 관측 3종이 Collector를 안 거친다. **Tempo가 OTLP 4317을 직접 수신**(그래서 Collector가
    4316으로 밀림), **Loki는 Collector에 exporter가 없어** 직접 수신. metric만 Collector→
    Prometheus. 여기서 Collector가 log→Loki·trace→Tempo로 분배하도록 정리한다.
  - **Loki에 retention이 없다. 로그를 흘리기 "전에" 걸어야 한다** — 흘린 뒤 걸면 이미 쌓인
    것은 안 지워진다(순서 주의).
  - Prometheus `scrape_interval: 1s`가 정본(15초~1분)과 다르다. **바꾸면 기존 대시보드
    해상도에 영향** → 팀원 합의 후 변경(단독 변경 불가).
  - Tempo `block_retention: 24h`, Collector `batch` processor 없음도 함께 정리.
  - 상세: `reports/2026-09-04_1620_phase0_인프라기동.md`, `infra/README.md` §6.
- 관련: BE-S-02(파이프라인)·BE-S-03(계층화)·BE-S-06(집약 표기).

### Phase 4 — 미디어 경로 [기반 경로]

**목표:** 온디맨드 영상이 뷰어까지 관통하고 frame_ref가 정합된다.

- 엣지→서버 원본 중계 WebSocket(방식 B: `[헤더길이][JSON frame_ref][JPEG]`), Tailscale 터널
  위. 서버→뷰어 WSS+인증. drop-old로 버퍼블로트 방지. 영상 채널과 상태·명령 채널 분리.
- frame_ref 단일 출처(엣지가 한 번 부여, 전파). 영상(미디어 경로)과 탐지(업무 경로)가 뷰어에서
  합류할 때 frame_ref F==F 정합.
- **DoD:** 합성 JPEG 프레임 재생 → 엣지 WS → 서버 중계 → 뷰어 canvas 표시, frame_ref가 관통해
  탐지 박스가 정확한 프레임에 겹쳐진다. 상세 근거는 [`02-media-path.md`](02-media-path.md).
- **외부 의존성:** 실 카메라·현장 회선은 Tier C(실측). 여기선 합성 프레임으로 경로·정합 검증.
- 관련: BE-T-07(미디어 중계)·BE-C-03(frame_ref)·BE-T-08(오버레이 터널).

### Phase 5 — 가용성 판정기

**목표:** 두 평면 신호를 하나의 권위 있는 가용성으로 통합.

- `backend/availability/`: 업무 평면(MQTT LWT·하트비트) + 관측 평면(Prometheus up/absent)
  이중 감지 → 단일 통합, **충돌 시 업무 평면 우선**(MQTT 세션 online이면 가용, offline이면
  up=1이어도 불가용). 상태 3층(자기보고·서버판정·오케스트레이터) 원본 유지. 제어 잠금 산출.
- 이것이 진나영 `simulation/backend.py` mock을 실물로 교체하는 지점.
- **DoD:** LWT/하트비트 타임아웃/지표 침묵을 주입해 online/offline이 세션 우선 규칙대로 판정되고,
  두 평면 불일치 케이스(세션 online·지표 결손 / 세션 offline·지표 존재)가 구분된다.
- **외부 의존성:** Phase 3 관측 평면 신호(그래서 Phase 3 이후).
- 관련: BE-T-04(가용성)·BE-X-07(제어 잠금).

### Phase 6 — 상관·감사·명령

**목표:** 명령 사슬이 한 키로 이어지고 책임이 기록된다.

- command_id 백엔드 발급(BE-X-01), actor(토큰)·시각(서버) 주입 감사 작성 → MySQL 직행,
  명령 결과 4단계 승격(ACK→수행중→물리변화→완료/실패), 감사 조회 API. 계획 승인 중계,
  AI 실패 이벤트 중계.
- **DoD:** 명령 사슬 fixture로 가시화 요청→발급→디바이스→결과→감사가 한 command_id로 추적되고,
  되돌리기 어려운 명령이 ACK가 아니라 물리 결과로 확정 표시된다. 감사 조회로 "누가 언제 무엇을"
  질의된다.
- **외부 의존성:** 진나영 AI-O-02(AI 실패)·AI-R-03(위험 판정) 수신 연동은 계약 기준(가짜 이벤트로 검증).
- 관련: BE-X-01~05(상관·감사·승격·승인·중계)·BE-A-01/02/04(명령 번역)·BE-Q-02(감사 조회).

### Phase 7 — 디지털 트윈

**목표:** 구역 트윈이 전역으로 종합되고 로봇 투입 판단이 나온다.

- `backend/twin/`: 위치 융합(불확실도 가중, DT-01)·클래스 융합(베이지안, DT-02)·트윈 반영(좌표
  변환, DT-03)·커버리지·사각지대(DT-04)·시의성(DT-05)·핸드오프(DT-06)·로봇 투입 결정(DT-07).
- **Tier 구분:** 좌표 변환·융합·커버리지 로직은 Tier B(합성 fixture로 검증 가능). **Unity 트윈
  렌더 연결(VZ-U-02)은 Tier C**(가시화 파트 대기) — 백엔드는 전역 좌표까지 산출하고 가시화가
  렌더만.
- **DoD:** 합성 다중 검출·카메라 배치로 융합·커버리지·시의성이 계산되고, 전역 좌표가 산출된다.
  Unity 실제 렌더 정합은 가시화 통합 후.
- **외부 의존성:** AI-S-02(연계 신뢰도)·AI-E-02(카메라 보정) 입력은 계약 기준. Unity는 가시화.
- 관련: DT-01~07·BE-C-04(좌표 규약).

---

## 3. 지금 당장 할 일 Top 3

- [x] **① 공통 계약 v1 확정** — 봉투·frame_ref 스키마 정의 완료
  ([`../../contracts/common/`](../../contracts/common/)).
- [x] **② 인프라 스택 compose 기동 + 헬스 확인 (Phase 0)** — 완료(2026-09-04). 서버에 7개가 이미
  가동 중이어서 **Kafka만 신규 설치**하고 나머지는 헬스 확인. 8개 전부 헬스 통과.
  보고: [`../../reports/2026-09-04_1620_phase0_인프라기동.md`](../../reports/2026-09-04_1620_phase0_인프라기동.md)
- [ ] **③ 가짜 발행자로 얇은 파이프라인 관통 (Phase 1)** ← **다음** — 최소 발행자(C) → ingest →
  Kafka → 저장 확인 → WS push 확인, 그다음 조병현 노드(A) 병행. 착수 전 결정 필요:
  Kafka `advertised.listeners` 주소·포트 바인딩, 토픽 이름 규약, 브릿지 구현체
  (Phase 0 보고서 "미결" 절 참조).

---

## 4. 외부 의존성 체크리스트

| 의존 대상 | 관련 Phase | 필요한 것 |
|---|---|---|
| 조병현 (HW) | Phase 1 | `sensor_node.py`(가져와 실행 — 확보) / 실 센서 입고는 Tier C |
| 진나영 (AI) | Phase 6·7 | AI 실패·위험 판정·연계 신뢰도 계약(가짜 이벤트로 검증 / 실 모델은 Tier C) |
| 김현우 (가시화) | Phase 4·7 | 뷰어 canvas 표시·오버레이 / Unity 트윈 렌더(Tier C) |
| 현장/실측 | Phase 4·5 | 회선 QoS·콜드스타트·Tailscale 실측(Tier C) |

---

## 5. 검증 방침 (완료 판정 수단)

- **Phase 0(인프라 기동):** compose 헬스체크 + 수동 확인(pytest 아님).
- **Phase 1 이후:** **pytest** — "가짜 발행자 → 파이프라인 → 예상 저장/중계" 회귀. 진나영과
  도구를 통일해 나중 통합 검증이 수월하게 한다.
- 선택 구성요소(예: 실 Grafana 연동)가 없으면 해당 테스트만 skip하고 나머지는 통과 — 이 격리
  자체가 요구사항(핵심·선택 분리)의 증거다.
- 상태를 **완료**로 올릴 때는 반드시 동작·경계를 검증하는 테스트를 [`requirement-traceability.md`](requirement-traceability.md)에
  함께 기록한다(테스트 없는 완료 금지). 검증 스크립트가 무력하지 않은지(무효 입력을 실제로
  거부하는지) 음성 대조도 포함한다.
