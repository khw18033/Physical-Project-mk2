# 작업 지시서 — Phase 4 미디어 경로

> 저장 위치: `docs/be/tasks/작업지시_phase4_미디어경로.md` — 끝난 뒤에도 제자리(일회용 인수인계 문서, 파일 이름으로 구별).
> ✅ **2026-09-19 Phase 4 완료.** 결과는 `reports/2026-09-19_0600_phase4_미디어경로.md`. 아래 본문의 실주소는 자리표시자로 바꿨다(제약 11).

---

## 1. 머리말

| | |
|---|---|
| **대상** | **Phase 4 — 미디어 경로**: 온디맨드 영상이 뷰어까지 관통하고 frame_ref가 정합된다. 그 경로를 세우는 김에 원격 엣지가 붙을 수 있게 만든다 |
| **착수** | 2026-09-17 설계 세션에서 **착수 결정 9개 확정** → **2026-09-18 전면 재검토 2건(설계방 49건 + Cowork 검토 29건)을 합본해 반영**(결정 10·11·12 신설). ✅ **단계 0의 서버 상태 표는 2026-09-18 서버 실측본이다 — 착수 시 대조만 한다**(§5 단계 0 머리말) |
| **판본** | **v4 (2026-09-18 최종).** v1(2026-09-17) 대비 변경점은 `reports/2026-09-18_1700_phase4_지시서_합본수정안.md`의 번호 대응표에 전건 기록돼 있다.<br>**v2·v3에서:** 단계 0 표의 `[재실행 대기]` 5행이 전부 실측으로 채워졌고, **제약 16**(ufw가 통하는 입구와 통하지 않는 입구가 다르다)과 제약 **29·30·31**이 신설됐다.<br>**v4에서: 범위를 도로 좁혔다.** 「범위 밖 노출 발견」 절 삭제 · 결정 6 β를 **바인딩 주소 한 줄**로 축소(`DOCKER-USER`는 ⏭ 다음으로) · OTLP 토큰 확장 조사 ⏭ · 7-h를 판정에서 **기록 1회**로 · 탐지 오버레이 ⏭ 선택. **⏭ 표시는 「이번에 하지 않고 다음에 한다」는 뜻이다.** |
| **근거 문서** | [`docs/be/01-standalone-implementation-plan.md`](../01-standalone-implementation-plan.md) **Phase 4 절**(이월 전수) · [`docs/be/02-media-path.md`](../02-media-path.md) **전문**(이번 Phase의 명세) · [`docs/be/00-architecture.md`](../00-architecture.md) §5-6·§6-3·§7-5·§8-5 · [`docs/be/requirement-traceability.md`](../requirement-traceability.md) BE-T-07·T-08·T-03·T-05·T-06·BE-C-03·BE-S-09 · [`reports/2026-09-16_1900_phase3_관측파이프라인.md`](../../../reports/2026-09-16_1900_phase3_관측파이프라인.md) 「서버에 남은 것」 · [`reports/2026-09-17_1159_팀브랜치_최신화_대조.md`](../../../reports/2026-09-17_1159_팀브랜치_최신화_대조.md) · [`docs/be/hw-envelope-conformance.md`](../hw-envelope-conformance.md) §5-1 · [`docs/be/vz-observability-namespace.md`](../vz-observability-namespace.md) + [`received/2026-09-17_vz-observability-namespace-reply.md`](../received/2026-09-17_vz-observability-namespace-reply.md) · [`infra/README.md`](../../../infra/README.md) §2-0·§3·§4·§5·§6 |
| **관련 요구사항** | BE-T-07(미디어 뷰어 중계) · BE-T-08(엣지↔서버 보안 오버레이) · BE-C-03(프레임 참조·시간 규약) · BE-T-03(WS 게이트웨이) · BE-T-05(사설 IP 중계) · BE-T-06(재접속 캐시 — 규약만) · BE-S-09(미디어 저장 모드 — #15 갈래) · BE-T-02(Kafka 원격 노출) · BE-S-02/S-03/S-06(③ 묶음) · VZ-C-07 |

> 이 문서는 **VS Code Claude Code가 읽고 구현하는 인수인계 문서**다. `CLAUDE.md`와 이 지시서를 함께 읽고, **지시서 범위대로** 구현한다. **설계는 끝났으므로 새로 설계하지 않는다.** 결정이 필요해 보이면 §3 제약 22를 따른다.

---

## 2. 배경

### 2-1. 딛고 서는 것 (Phase 0~3의 결과)

- **Phase 1** — 공통 헤더 검증 → Kafka 3토픽 → 저장 sink + WS echo가 관통한다. 토픽 규약 `mk2.telemetry.<채널>`, 파티션 키 `source_id`, Kafka value는 원본 JSON 바이트 그대로.
- **Phase 2** — 계측은 TimescaleDB(`telemetry` 하이퍼테이블, 시간축 = **발행 `timestamp`**, UTC), 감사·레지스트리·실행 기록은 MySQL 8테이블. 채널 본문 규격 6종 + **느슨한 2단 검증**.
- **Phase 3** — 관측 어댑터 `backend/observability.py`가 `opentelemetry`를 import하는 유일한 파일. **A층 9계기(이름 11) · C층 12계기(이름 17 — 09-18 실측)**. Collector가 metric→Prometheus·log→Loki·trace→Tempo로 분배. 상주 3개는 **systemd**. **Tailscale이 서버에 설치**됐다(1.102.4, 팀 공용 계정). 2계층 페더레이션을 임시 엣지(컴퓨터)로 실증한 뒤 **되돌렸다**.
- **pytest 184건**이 v1 시점의 기준선이었다(2026-09-17 재실행 확인). ⚠ **이 숫자를 DoD 기준으로 그대로 쓰지 않는다** — 단계 5-3의 라벨 확장이 `parametrize`로 수집 수를 늘린다. 기준선은 **단계 0-5에서 측정하는 N**이다(제약 24).

### 2-2. 이번 Phase는 네 묶음이다

| | 묶음 | 내용 |
|---|---|---|
| ① | **미디어 경로 본체** | 방식 B(`[4B 헤더길이][JSON 헤더][페이로드]`) 서버 중계 · drop-old · 영상/상태 채널 분리 · 뷰어 입구 노출 + 최소 인증 · frame_ref 관통 |
| ② | **Phase 1 이월 3건** | Kafka 원격 노출(→ **EDGE 리스너**) · frame_ref 규격 정합(§8 회신) · WS 게이트웨이 외부 노출 + 인증(VZ-C-07 포함) |
| ③ | **Phase 3 이월 4건** | Collector 4316 Tailscale 바인딩 + ufw 되살리기 · `edge_federate` 잡 되살리기 · Prometheus digest 고정 · `LoggingHandler` 교체. ⚠ plan이 "5건"이라 세지만 다섯째(Tailscale 설치)는 **작업 항목이 아니라 완료 사실**이다 |
| ④ | **회신·통지 + 4b** | HW 회신 §8(§8·§10-4~7 + #14~#18 + 인식 안내) · VZ 통지(미디어 형식·관측 회신 답) · **AI 통지 신설**(부록 D — `detections` 생산자가 AI다) · **4b 촬영본 저장소**(HW #15) |

### 2-2b. 계층 이름 — pi7은 엣지가 아니라 말단이다

2026-09-18 정정. HW 문서·코드 배치가 처음부터 이렇게 되어 있고, `02-media-path.md`의 서술(말단→엣지 / 엣지→서버)이 옳았다.

```
로봇 본체 ─ pi7(온디바이스·말단) ─홉1─ 엣지 노트북 ─홉2─ 서버 ─홉3(뷰어 분기)─ 뷰어
            pi/robot/go1_relay.py       edge/media_gateway.py
```

| 항목 | 맞는 것 |
|---|---|
| `frame_ref`를 찍는 곳 | **엣지 노트북**(AU 재조립 지점). 말단이 아니다 |
| 8766 `/ingest`에 붙는 주체 | **엣지 노트북** |
| pi7이 하는 일 | H.264를 디코드 없이 RTP로 패킷화해 엣지로 송출 |
| `origin.tier` 3종의 실제 배치 | `device`=pi7 온디바이스 / `edge`=노트북 / `server`=서버(결정 11) |

> 🔴 **엣지 실물이 지금 없다.** HW `README.md:24-25` — *"미디어 게이트웨이(**예정**) ※ 전용 장비 확보 전"*, WSL2 임시 구성은 2026-08-31 철수. 그래서 이번 Phase의 "엣지"는 **결정 4의 컴퓨터 임시 엣지 + 합성 fixture**다. Phase 4 뒤 실측의 첫 관문이 엣지 노트북을 세우는 일이다.

### 2-3. 역할 경계 — 백엔드가 구현하는 것과 아닌 것

**미디어 경로에서 백엔드의 몫은 "형식을 주고 중계한다"다**(02-media-path §1-5-3). 로봇에서 영상을 직접 수집·추출할 수 없어 검증이 **합성 프레임**이다.

| 백엔드가 구현한다 | 백엔드가 구현하지 않는다 |
|---|---|
| 서버 미디어 중계(엣지 수신 → 뷰어 분기 · drop-old · 토큰 인증) | 카메라 수집·홉1·**실물 엣지 송신기** — HW(`go1_relay`·`media_gateway`)가 우리 형식에 맞춰 붙는다 |
| **규격** — frame_ref · 미디어 헤더 · 탐지 좌표 선언(`contracts/common/`) | 미디어 어댑터(AI-C-08)·탐지 — AI |
| **합성 엣지 송신 fixture**(Phase 3 `edge_probe_publisher` 같은 성격 — 실물 엣지 송신기가 아니다) | canvas 표시·오버레이 — VZ(우리는 형식 초안만 준다) |
| 뷰어 확인용(`backend/gateway/console.html` 수준) | VZ 앱을 대신 만들지 않는다 |
| ②·③ 묶음의 서버 설정 · 회신·통지 문서 | 로봇 자세·pose 페이로드·트윈 형식 — Phase 7 |

**"HW가 이렇게 구현했으니 그쪽 코드에 맞춘다"도, "우리가 엣지 송신기까지 만든다"도 아니다.** 어느 쪽으로든 경계를 넘는 설계가 필요해 보이면 **멈추고 묻는다**.

### 2-4. 시연 임시 경로는 설계 대상이 아니다

2026-09-16 캡스톤 계획발표 시연은 서버 완성 전이라 **팀이 합의해 백엔드를 우회한 임시 경로**다. 아래 세 갈래를 섞지 않는다(근거: `reports/2026-09-17_1159_팀브랜치_최신화_대조.md` §4-2).

| 시연 특수 — 설계 대상 아님 | 일반형 — 설계 대상 | 임시 경로 — 우리 경로로 바뀜 |
|---|---|---|
| 45°×8 회전, `rotation_deg`가 정합 키, 문 탐지, 단상 역산 | frame_ref 시각이 상태 채널과 **같은 시각 축**인지 확인(Phase 2 확정: 발행 `timestamp`·UTC) | **JPEG base64를 MQTT `frame` 토픽에**(원칙 3 위반) |
| `mission_id`가 8장 묶음 키 | 프레임·탐지가 **어느 명령의 산출**인지(BE-X-01 상관키) | 구판 봉투(`1.3`·`device_id`·`+0900`) |
| 정지 후 촬영·0.6초 settle·한 장씩 | 원본 무가공(좌표 기준 해상도) | 탐지 결과 AI→VZ HTTP 직결 |
| `/scan` 경계 신호 | 카메라 프리즈는 타임스탬프로 못 잡는다 | AI→로봇 직접 명령 토픽 / HW JSON 번역 토픽 |
| AI 처리 ~2초/프레임 | **464×400 실측**(q2 ~25KB) · AI가 B안(RTP + 캡처 이벤트)을 열어 둠 | 파이에서의 H.264→JPEG 디코드 |

**계산 기준은 464×400 · q2 ~25KB다.** `status.media`의 `1280x720`은 테스트 패턴 송출기 값이지 카메라가 아니다.

### 2-5. 착수 전 결정 **12개**(+4-b) — **설계방이 확정했다. 다시 설계하지 않는다**

| # | 결정 | 확정 내용 |
|---|---|---|
| **1** | 로봇 영상 코덱(§10-7) | **D — 소스 native 코덱을 그대로 중계한다.** 미디어 헤더 `encoding`이 그 코덱을 **선언**하고(알려진 값 `h264`·`jpeg`는 `$comment`, **enum 아님**), 서버는 **필수·타입만 검증하고 값 어휘를 보지 않으며 페이로드를 열지 않는다.** 현재 배포 프로파일 = 로봇 H.264 종단 / 고정 CCTV JPEG 종단 |
| **2** | frame_ref 형식(§8) | **`capture_timestamp`는 ISO date-time 문자열 유지.** epoch ms는 **우리 문서(v8 §6-9·02-media-path §1-6-2 예시)와 우리 규격 파일이 어긋난 것**이었다. 상관키는 **frame_ref 밖** — 공통 헤더/미디어 헤더의 `correlation_id`(선택), `frame-reference.schema.json`은 **개정하지 않는다** |
| **3** | 온디바이스 frame_ref(§10-4) | **㉰ 정합 등급을 규격에 둔다.** 탐지 메시지에 **메시지 단위 `alignment`**(string, 알려진 값 `frame`·`unaligned`는 `$comment`). 뷰어 규칙은 **fail-safe**: `alignment=="frame"`이고 `frame_ref`가 있을 때만 프레임 정합, **그 외(부재·모르는 값 포함) 전부 unaligned 취급** |
| **4** | 엣지 역할 | **ㄷ — 서버 안에서 먼저 관통해 pytest에 못 박고, 그다음 컴퓨터 임시 엣지로 2계층 실측 1회, 그리고 되돌린다.** 파이 실물은 쓰지 않는다 |
| **4-b** | 연결 방향·open 신호 | 홉2는 **엣지가 클라이언트**로 서버에 붙는다. open 신호는 **연결 자체** — `/media?source_id=…`에 붙는 것이 켜기, 끊는 것이 끄기. **상시(페이지 로드 시 연결)와 온디맨드(패널 열 때 연결)가 같은 메커니즘**이고 서버는 그 차이를 모른다 |
| **5** | WS 노출·인증·주소 | **B — 터널 위 `ws` + 토큰.** 인증은 **URL 쿼리 토큰**. **같은 포트 경로 분리**(`/state`·`/media`), **엣지 입구는 별도 포트 8766**.<br>🔴 **2026-09-18 정합 — 뷰어는 tailnet 「안」이다.** v1은 *"WSS는 뷰어가 tailnet 밖인 프로파일"*이라 적어 **뷰어가 밖에 있을 수 있다**는 전제를 남겼는데, 결정 7 A는 4318을 **Tailscale IP에만** 바인딩해 **뷰어가 안에 있다**고 전제한다. **터널로 붙지 않은 브라우저는 4318에 닿지 못하므로 두 전제가 양립하지 않는다.** VZ 코드 주석(*"관제 웹(노트북)·로봇(pi7)·탐지(데스크톱)가 전부 테일넷으로 붙는다"*)에 맞춰 **「뷰어는 tailnet 구성원」으로 통일한다.** tailnet 밖 뷰어(외부 관제·시연장 게스트)가 필요해지면 **WSS + 관측 대체 경로를 Phase 6에서 함께 연다** — 이번 범위가 아니다 |
| **6** | Kafka 원격 노출 | **㉯ EDGE 리스너를 하나 더 둔다**(PLAINTEXT `localhost:9092`는 **한 줄도 안 바꾼다**). **β 평문 + `<서버 tailscale IP>` 바인딩**(ufw는 도커 발행 포트에 통제가 아니다 — 제약 16). SASL은 BE-Q-04와 함께 Phase 6 |
| **7** | BE-T-08 범위·브라우저 입구 | **(ii) 평면별 최소 인증**(OTLP 토큰은 확장 유무를 `validate`로 판정, 없거나 receiver 분리가 필요하면 (i)). 브라우저 자체 지표는 **A — Collector OTLP/HTTP 4318을 Tailscale IP에만 바인딩 + CORS + ufw `/32`** |
| **8** | §10-5·§10-6·회신 형태 | **8-1 ㄱ**(q 우선, **해상도 변경은 스트림 재개 사건**) · **8-2 확인 회신**(소스가 정한다 + 홉1/홉2 층 구분 + 개폐 배선은 Phase 6) · **8-3 A**(`hw-envelope-conformance.md`에 **§8**로 이어 붙인다) |
| **9** | HW #15 촬영본 저장 | **ㄱ 파일시스템 + 작은 PUT 수신단**(새 저장 제품 없음) · **ㄴ 입구는 남긴다**(4b 완료 후 HW에 통지) · **`frame_ref_base`는 채우지 않는다** + 매니페스트에 선택 `correlation_id` · 보존은 **용량 상한 + 오래된 세션부터** · **4b는 이 지시서의 마지막 독립 단계** |
| **10** | 홉2 전송 모드 *(2026-09-18 신설)* | **길 A·B를 둘 다 지원한다.** `02-media-path.md` §1-3-1의 *"현재 배포 = 길 B"*를 **"길 A·B 동시 지원, 소스별 프로파일. 현재 개발 단계 = 길 A"**로 고친다. **구현 변경 0** — 결정 4-b(엣지가 클라이언트로 붙어 계속 보냄) + §2-3(엣지 입구에서 안 버림) + "뷰어가 없으면 버린다"를 합치면 **홉2는 이미 길 A로 돈다.** 길 B의 절약은 서버→엣지 개폐 명령(Phase 6)에 있다. ⚠ 길 A를 실제로 **켜려면** HW `stream` 명령이 필요한데 지금 호출 불가다(부록 A 8-11) |
| **11** | 서버 비전 소비자 자리 *(2026-09-18 신설)* | **문만 열어 두고 만들지는 않는다.** 제약 9의 주어를 **"중계 경로는"**으로 좁히고, `detections` 초안의 `origin.tier`에 **`server`를 미리 넣는다.** frame_ref 단일 출처는 깨지지 않는다 — 서버 비전은 헤더의 값을 **읽어서 그대로 붙일 뿐 새로 만들지 않는다**(원칙 10의 금지는 "재생성"이다). 산출물 형식은 **좌표 JSON**(이미지 번인 금지). 지연 예산은 **VZ 버퍼 48프레임 = 15fps 기준 약 3.2초** 안. **실제 모델·추론 배선·GPU 예산·중복 제거는 이번 범위 밖** |
| **12** | 파일 간 `$ref` 해석 *(2026-09-18 신설)* | **레지스트리 방식.** `referencing.Registry`에 `$id → 로컬 파일`을 등록해 `backend/ingest/envelope.py`의 두 검증기(`build_validator()`·`payload_validator()`)에 넘긴다. 인라인 복제(㉮)를 쓰지 않는 이유는 원칙 9(규격이 기준)와, **Phase 7의 `object-reference.schema.json`이 같은 경로를 쓰기 때문**이다. 착수 전에 `python -c "import referencing"`로 설치 여부를 확인한다(jsonschema 4.18+ 동봉). 없으면 그때 인라인으로 내려도 늦지 않다 |

> ⚠ **번호 주의.** 결정 10·11·12는 2026-09-18 합본에서 신설한 것이다. **설계방 수정안 문서의 "결정 8·결정 9·결정 E"가 각각 여기의 결정 10·11·12다.** 원래 결정 8(§10-5·§10-6)·결정 9(HW #15)와 헷갈리지 않게 번호를 이어 붙였다.

---

## 3. 제약 — 반드시 지킬 것

### 절대 원칙(CLAUDE.md §1) 중 이번에 걸리는 것

1. **영상 픽셀을 업무·관측 메시지에 싣지 않는다**(원칙 3). MQTT/Kafka/OTLP에 JPEG·H.264를 넣지 않는다. **시연의 `zoneA/robot/go1-001/frame` 토픽을 구독하지 않는다.** ⚠ 원칙 3 원문은 경로까지 적고 있다 — *"영상은 별도 미디어 경로(**RTP/UDP → WS 방식 B → WSS**)로만 흐른다."* **결정 5가 그 괄호의 `WSS`를 바꿨으므로**, 원문을 지우지 말고 `CLAUDE.md` 원칙 3과 `02-media-path.md` §1-5-0에 **프로파일 구분**을 적는다: *"현재 프로파일 — 뷰어는 tailnet 구성원이다. 터널 위 `ws` + 토큰. **tailnet 밖 뷰어용 WSS는 Phase 6**(결정 5가 「뷰어는 tailnet 구성원」으로 통일했다)."* (§8 갱신 대상)
2. **frame_ref는 엣지가 한 번 부여하고 전파한다**(원칙 10). **서버는 재생성하지 않는다.** 이번 Phase에서 그 "엣지"는 **합성 송신 fixture**이고, 부여 시점은 **액세스 유닛 재조립 시점**이다.
3. **엣지↔서버는 터널이 강제다**(원칙 12). 미디어·명령(Kafka)·관측(OTLP)이 **하나의 Tailscale 터널**을 공유한다.
4. **WS 게이트웨이는 서버 내부 컴포넌트다**(원칙 13). 브라우저는 Kafka·MQTT에 직접 붙지 않는다. **단 관측 평면은 생산자 직접 발신이 설계다**(v8 §5-3·5-8) — 결정 7 A가 원칙 13과 충돌하지 않는 이유가 이것이다.
5. **`opentelemetry`를 `backend/observability.py` 밖에서 import하지 않는다.** 새 미디어 지표도 어댑터의 `count`·`updown`·`gauge`·`observe` 인터페이스만 쓴다.
6. **관측 라벨**: 금지 7종(`session_id`·`internal_seq`·`sequence_id`·`timestamp`·`ts`·`frame_id`·`capture_timestamp`)은 **접두사와 무관하게 전 계기**에 걸린다. **A층 전용 금지 3종**(`source_id`·`zone_id`·`entity_type`)만 **접두사 6개**(`be.ingest.`·`be.kafka.`·`be.storage.`·`be.registry.`·`be.gateway.`·`be.pipeline.`)에 걸린다 — 그래서 미디어 지표는 전부 **`be.gateway.*`** 아래 둔다. `be.media.*`로 만들면 **A층도 C층도 아닌 무방비 이름 공간**이 되어 `source_id`를 붙여도 아무도 못 막는다.
   ⚠ **`frame_ref`는 지금 막히지 않는다.** `FORBIDDEN_LABELS`에 `frame_id`만 있고 `frame_ref`가 없다(`observability.py:64-66`). 그런데 우리가 VZ에 보낸 통지(`vz-observability-namespace.md:91`)는 *"프레임 식별자(`frame_id`·**`frame_ref`** 등)"*로 **둘 다 막는다고 적었다.** 통지와 코드가 어긋나 있으므로 단계 5-3에서 함께 닫는다(§5 단계 5-3 #10). **없는 방어를 근거로 쓰지 않는다.**
7. **MongoDB는 "현재 채택하지 않는다"이며 영구 배제가 아니다**(원칙 4 원문: *"타당한 근거 없이 도입하지 않는다"*). 4b에 객체 저장소(MinIO 등)를 새로 들이지 않되, **`00-architecture.md` §8-5의 MongoDB 발동 조건이 하필 "프레임 낱장 증거+메타 동시 보관"이다** — 4b 보고에 *"이번에는 파일시스템으로 충분해 그 조건을 충족하지 않는다"*를 한 줄 남긴다.
8. **Kafka는 장기 저장소가 아니다**(원칙 11).

### 이 작업 고유 제약

9. **중계 경로는 미디어 페이로드를 열지 않는다.** 헤더만 읽는다(`keyframe`·`frame_ref`). 중계에서 디코드·재인코딩·트랜스코딩을 하지 않는다 — 그것이 방식 B 중계의 성립 근거다(02-media-path §1-3-3). ⚠ **주어가 "서버"가 아니라 "중계 경로"다**(결정 11). *별도 소비자가 `/media`에 붙어 자기 프로세스에서 프레임을 디코드하는 것은 중계와 무관하며 금지가 아니다.* 이번 Phase에서 그 소비자를 **만들지는 않는다.**
10. **생산자 어휘를 `enum`으로 잠그지 않는다.** `encoding`·`codec`·`alignment`는 **string + `$comment`**. 알려진 값 목록은 주석이지 검증 대상이 아니다(`contracts/common/README.md` 「느슨한 2단」 149행 규칙 그대로).
11. **비밀값·내부망 IP·Tailscale 주소·토큰을 커밋하지 않는다.** 이 저장소는 Public이다. 문서·주석에는 `<서버 tailscale IP>`·`<엣지 tailscale IP>`·`<VZ PC tailscale IP>` 같은 **자리표시자**만 쓴다. 실값은 `_serverinfo/`(gitignore)와 서버 `.env`에만 둔다.
12. **UTF-8 · LF.** 배포 대상이 리눅스라 CRLF 금지(`.gitattributes`).
13. **`docker compose up -d`·`restart`에 반드시 서비스 이름을 명시한다.** 컨테이너 13개 중 4개는 다른 파트 것이다(분류 ③). **이미 도는 것을 지웠다 다시 깔지 않는다.**
14. **이미지는 digest로 고정한다. `:latest` 금지.**
15. **없는 IP에는 docker가 바인딩하지 못한다.** `tailscaled`가 뜨기 전에 `up -d`를 하면 `cannot assign requested address`로 기동이 실패하고, 재부팅 시 `restart: always`가 루프에 빠진다. Tailscale 인터페이스 바인딩 전에 **반드시 `tailscale ip -4`로 주소가 있는지 확인**한다.
16. **ufw가 통하는 입구와 통하지 않는 입구가 다르다**(2026-09-18 iptables 실측).
    - 🔴 **8765·8766·8767은 호스트 파이썬 프로세스**라 DNAT를 안 타고 `INPUT`으로 들어온다 — **여기서는 ufw가 진짜 통제다.** 미디어 경로의 입구 셋이 전부 여기 속한다.
    - 🔴 **9095·4316·4318은 도커 발행 포트**라 ufw `INPUT`을 타지 않는다(`DOCKER-FORWARD`가 ufw 체인보다 먼저 ACCEPT하고 `DOCKER-USER`는 비어 있다). **여기서 실제로 막는 것은 compose의 바인딩 주소다** — nat `DOCKER`에서 `-d 127.0.0.1/32`가 붙은 9092·7859·4316만 실제로 제한되고 있는 것이 그 증거다.
    - **그래서 도커 포트에는 바인딩 주소를 정확히 쓰고**(단계 6), **ufw 규칙도 적되 「통제」로 세지 않는다**(장애 원인 배제·문서용).
    - ⚠ **`infra/README.md` §5의 「실측이 compose 주석을 반증했다」는 틀렸다** — compose 주석 쪽이 옳았다. 단계 6-b에서 고친다.
    - ⚠ **2026-09-19 정정(Phase 종료 후):** 4318은 **Phase 4에서 발행하지 않았다** — Collector에 HTTP receiver가 없어 열 게 없었다. 위 규칙은 실제로 **9095·4316에 적용됐고**, 4318은 결정 7 A로 **열 때** 같은 규칙을 적용한다. (추적표 BE-T-08 · `infra/README.md` §5)
17. **`tailscale up`을 다시 치지 않는다.** 팀 공용 계정이 갈릴 수 있다. 주소는 `tailscale ip -4`로만 읽는다.
18. **서버 파일이 기준이다.** `infra/docker-compose.yml`(작업본)은 **서버 파일과 이미 다르다**(단계 0 실측: 서버 `2fa97cc7…` ↔ 작업본 `16a704a9…`, 주석 분량 차이). **compose를 처음 고치기 전에 서버 파일을 내려받아 작업본을 덮고 md5를 기록한다.**
19. **상주 프로세스는 systemd다.** 손으로 띄워야 하면 **먼저 유닛을 내린다**(`ingest`는 `client_id=mk2-ingest`가 고정이라 둘이 붙으면 서로 밀어낸다).
20. **코드를 고치면 서버 사본에 복사하고 `systemctl restart` 해야 반영된다.** 서버는 저장소 사본이고 `git pull` 배포가 아니다. 복사 시점을 각 단계에 명시해 두었다.
21. **상주 프로세스나 엣지 프로세스를 띄우는 명령은 터미널을 나눠 준다.** 한 코드블록에 여러 줄을 주면 첫 줄만 실행된다(Phase 2 실측).
22. **막히거나 결정이 필요하면 임의로 정하지 말고 `reports/`에 남기고 멈춘다.** 특히 §2-5의 결정 **12개**를 바꾸는 판단, 역할 경계를 넘는 설계, 새 채널·토픽 신설.
23. **용어** — 산문에서 "계약" 대신 **공통 규격**, "봉투" 대신 **공통 헤더**, 문서를 가리키는 "정본" 대신 **기준 문서**. 코드·규격 파일·경로·필드명(`contracts/common/message.schema.json`·`schema_version`·`source_id`)은 그대로 쓴다.
24. **테스트 없는 완료 금지.** 새 기능에는 **음성 대조**(잘못된 것을 실제로 막는지)를 붙인다.
    ⚠ **기준선은 "184"라는 고정 숫자가 아니라 「착수 시 수집 수」다.** `tests/test_observability_labels.py:41`이 `sorted(obs.FORBIDDEN_LABELS)`를, `:79`가 `sorted(obs.A_LAYER_FORBIDDEN)`를 `parametrize` 인자로 쓰므로 **단계 5-3에서 금지 라벨을 늘리면 수집 수가 저절로 늘어난다**(현재 184 → 라벨 8종 추가 시 약 192, `:74`와 스택되는 A층 목록을 건드리면 3배로 증폭). 단계 0에서 `pytest --collect-only -q`로 **기준선 N을 측정해 적어 두고**, 이후 DoD는 *"N + 라벨 증가분 + 신규 전건 통과"*로 판정한다. **기존 문서의 "184"를 그대로 옮겨 적지 않는다.**
25. **새 파일 이름에 `token`·`secret`을 넣지 않는다.** `.gitignore:22-23`의 `*token*`·`*secret*`이 **경로 어디에 있든** 잡아, `tests/test_media_token.py` 같은 파일이 **조용히 커밋에서 빠진다.** 이번 Phase는 토큰을 대거 도입하므로 특히 걸린다. 새 파일을 만든 뒤 `git status`에 보이는지 눈으로 확인한다.
26. **`tests/fixtures/*.h264`는 커밋되지만 `.gitattributes`에 바이너리 선언이 없다.** `.gitattributes:4`의 `* text=auto eol=lf`가 전역이고 바이너리 목록에 `.h264`가 없다. **`*.h264 binary` 한 줄을 `.gitattributes`에 추가**한 뒤 fixture를 커밋한다(제약 12와 충돌하지 않는다 — 바이너리는 EOL 변환 대상이 아니다).
27. **MySQL GRANT에는 테이블 와일드카드가 없다.** 4b의 새 테이블 `media_capture`는 **DDL 적용 → 그다음 GRANT** 순서로만 권한이 붙는다(MySQL은 없는 테이블에 테이블 단위 GRANT를 걸지 못한다). 계정 host는 기존과 같은 **`'mk2_app'@'172.18.%'`**. `CREATE`·`ALTER`·`DROP`은 어디에도 주지 않는다.
28. **`hw-envelope-conformance.md`에 새로 만드는 `§8`은 우리 절 번호다.** 같은 문서가 HW `BACKEND_AGENDA`의 `§8`(frame_ref 안건)도 가리키므로, **절 제목에 출처를 박는다** — `§8 회신 — 미디어 경로 (BACKEND_AGENDA §8 · §10-4~7 · #14~#18)`.

29. 🟠 **Phase 4 동안 `docker compose down`을 치지 않는다. `up -d <서비스>`만 쓴다.** compose에 **`ipam`·`subnet` 블록이 없어 브리지 대역 `172.18.0.0/16`이 고정돼 있지 않다**(09-18 실측: grep 0건). 네트워크가 재생성되면 대역이 밀리고 **① MySQL 계정 `mk2_app@'172.18.%'` 인증 ② ufw `[36]`·`[37]`의 `172.18.0.0/16` 규칙**이 **동시에, 조용히** 깨진다. `ipam` 고정 자체가 네트워크 정의 변경이라 전체 스택 재기동을 부르므로 **이번 Phase가 아니라 별도 유지보수 창**에서 한다(§8 `infra/README.md` 「미고정 잔여」에 적는다).

30. **서버 경로와 저장소 경로는 이름이 다르다. 헷갈리면 엉뚱한 파일을 고친다.**

    | 저장소(컴퓨터 작업본) | 서버 |
    |---|---|
    | `infra/sql/` | **`/home/dg/capstone-db/mk2_sql/`** ← **이름이 다르다** |
    | `infra/docker-compose.yml` | `/home/dg/capstone-db/docker-compose.yml` |
    | `infra/config/` | `/home/dg/capstone-db/config/` |
    | **없다** (`infra/.env`는 존재하지 않는다) | **`/home/dg/capstone-db/.env` 하나뿐** (`600 dg dg`, 159바이트) |
    | 저장소 루트 | `/home/dg/capstone-db/phase1_work/Physical-Project-mk2/` |
    | — | venv `/home/dg/capstone-db/phase1_work/venv_phase1/` (**시스템에 `python`이 없다**) |

    ⚠ **`mk2_sql/`의 내용도 이미 저장소와 다르다** — 서버 `mk2_mysql_schema.sql` **23,864바이트(09-14 03:18)** ↔ 저장소 **26,931바이트(09-14 03:47)**, 그리고 **서버에만 있는 `registry-declared-vs-observed.sql`**. **단계 10의 DDL을 적용하기 전에 이 차이가 「저장소가 앞선 것」인지 확인한다**(DoD 0-6).

31. **서버 확인 명령 규칙 셋** — 2026-09-18 실패에서 나왔다. 앞으로 서버 명령을 쓸 때 항상 적용한다.
    - **MySQL은 `.env`를 경유하지 않는다. 컨테이너 자기 환경변수를 쓴다.** 호스트에서 `. .env`로 읽으려다 실패했고(변수명이 다르다), 비밀번호가 셸 히스토리·`ps`에 남는다.
      ```
      docker exec -i capstone_mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -t' <<'SQL'
      SHOW GRANTS FOR 'mk2_app'@'172.18.%';
      SQL
      ```
    - **Loki·Tempo 조회에는 `start`·`end`를 반드시 붙인다.** 기본 조회 범위가 **6시간**이라 데이터가 있어도 **빈 응답**(`{"status":"success"}`만, `data` 없음)이 온다.
    - **진단 명령에 `2>/dev/null`을 붙이지 않는다.** 값이 빈 이유가 「파일이 없어서」인지 「이름이 달라서」인지 구분되지 않는다.

---

## 4. 먼저 읽을 것

| 순서 | 무엇 | 왜 |
|---|---|---|
| 1 | `CLAUDE.md` §1·§1-A·§2·§4 | 절대 원칙·구현 규율·금지. 특히 원칙 3·10·12·13 |
| 2 | `docs/be/02-media-path.md` **전문** | 이번 Phase의 명세. §1-0 전체 경로·§1-2·§1-3·§1-4·§1-5·§1-6·§3 |
| 3 | `docs/be/01-standalone-implementation-plan.md` **Phase 4 절 + §4** | 이월 전수와 외부 의존성 |
| 4 | `docs/be/requirement-traceability.md` BE-T-07·T-08·C-03·T-03·T-05·T-06·S-09 | 각 행의 **gap 칸**이 "무엇이 왜 남아 있는가"다 |
| 5 | `reports/2026-09-16_1900_phase3_관측파이프라인.md` 「서버에 남은 것」·「검증 범위의 한계」 | 단계 0 대조의 기준 |
| 6 | `reports/2026-09-17_1159_팀브랜치_최신화_대조.md` §4-2·§5 | 세 갈래 구분과 사용자 결정 |
| 7 | `infra/README.md` §2-0 자원 분류표·§3 포트·§4 「흐른다」·§5 Kafka·§6 알려진 사항 ⓓⓔⓗ | 서버를 건드리기 전에 |
| 8 | `contracts/common/README.md` + `message.schema.json`·`frame-reference.schema.json` | 규격 정책·식별자 원칙·라벨 금지 |
| 9 | `backend/gateway/ws_echo.py`·`backend/settings.py`·`backend/observability.py` | 고칠 코드의 현재 모습 |
| 10 | `docs/be/hw-envelope-conformance.md` §5-1·§6-0·§7 | 회신 규율의 실례(머리말 표·근거·기본값·「상대가 할 일」) |
| 11 | `docs/be/vz-observability-namespace.md` + `received/2026-09-17_…reply.md` | VZ 통지가 겹치지 않게 |

---

## 5. 단계와 DoD

> 각 단계의 DoD가 전부 참이어야 다음 단계로 간다. **DoD가 안 되면 멈추고 보고한다.**

---

### 단계 0. 서버 현재 상태 확인 — 재확인이 아니라 **대조**

**Phase 3 보고서의 「서버에 남은 것」은 근거로 쓴다.** 단계 0은 그 표와 지금이 같은지 대조하는 것뿐이고, **어긋나는 항목이 하나라도 있으면 멈추고 보고한다.**

> ✅ **2026-09-18 실측 완료 — 이 표는 서버에서 직접 받은 출력이다.**
> 원본은 `_serverinfo/260918_phase4_단계0_실측.txt`(커밋 금지). 착수 시점에 이 표와 같은지만 **대조**한다.
>
> **v1(2026-09-17)에서 무엇이 어긋나 있었나** — 기록으로 남긴다.
> v1 표는 머리에 「2026-09-17」이 붙어 있었지만 그날 서버에서 실제로 돌아 결과가 돌아온 명령은 3회뿐이었고, 나머지는 09-04~09-16 문서 전사였다. 그래서 09-18 실측과 대조하니 이렇게 갈렸다:
>
> | v1이 적은 것 | 09-18 실측 | 판정 |
> |---|---|---|
> | tailnet에 `pi4`·`pi6` | **둘 다 실재한다**(주소는 `_serverinfo/`) | ⚠ **v1이 맞았다.** 2026-09-18 검토에서 *"전 출처 0건이므로 지어낸 값"*으로 판정했으나 **그 판정이 틀렸다** — 저장소 문서에 근거가 없었을 뿐 실물에는 있었다. 다만 v1 목록도 불완전했다(아래) |
> | tailnet 9대 | **11대.** `desktop-0ib285f`·`pi2`가 v1에 없고, v1·대조 보고서가 적은 `jin03`은 **실제 이름에 없다** | 목록을 실측으로 교체 |
> | 컨슈머 그룹 4종 | **2종이다** — `mk2-storage`·`mk2-ws`. LAG 전부 0, 오프셋 heartbeat 200 · status 140 · state 127 | v1 과다 |
> | 브로커 `localhost:9092 (id: 1)` 응답 | ✅ **맞다** (`KAFKA_NODE_ID=1`, `PLAINTEXT://localhost:9092`) | v1이 맞았다 |
> | `be_*` 이름 28개 / A층 11 | ✅ **둘 다 맞다** — 이름 **28종**, A층(6접두사) **11종**, C층(`be.telemetry.`) **17종** | **v1이 맞았다.** 2026-09-18 1차 조회가 `localhost:9090`으로 가서 0이 나왔던 것뿐이다(Prometheus 호스트 포트는 **7861**) |
> | C층 instant 0건 | **틀렸다** — C층 17종이 이름 목록에 있다 | 교체 |
>
> **교훈은 그대로다:** 근거 없는 값을 실측으로 적지 않는다. **다만 「저장소에 근거가 없다」가 곧 「사실이 아니다」는 아니다** — 09-18 검토가 그 둘을 붙여 읽어 pi4·pi6을 잘못 지웠다.

| 항목 | 근거 | 확인된 값 (2026-09-18 실측) |
|---|---|---|
| 컨테이너 | `[실측 09-18]` | **13개.** Collector `…@sha256:7087dcbb…`(digest 고정) · 포트 `127.0.0.1:4316->4317`. ⚠ **4318·55679는 컨테이너 EXPOSE 표기일 뿐이고 Collector 설정에 HTTP receiver 자체가 없다**(아래 Collector 행) |
| **포트 지도** | `[실측 09-18]` | 🔴 **Prometheus 호스트 포트는 9090이 아니라 7861이다.** Grafana 7862 · Mongo 7863 · Redis 7860 · MySQL 7858 · TSDB `127.0.0.1:7859` · Loki 3100 · Tempo 3200+4317 · mosquitto 1883 · pushgateway 9100·9101. **v1의 조회 명령이 9090으로 가 있어 `be_*`가 0으로 나왔다** |
| digest 고정 | `[실측 09-18]` | **`otel_collector`·`timescaledb` 둘만 digest.** `:latest` 잔여 **7개** — grafana · loki · mongo · **prometheus** · tempo · pushgateway 2개. 단계 5는 Prometheus만 고정하고 **나머지 6개를 `infra/README.md` §6에 「digest 미고정 잔여」로 기록**한다 |
| systemd 3개 | `[실측 09-18]` | `mk2-ingest`·`mk2-storage-consumer`·`mk2-ws-echo` **active·enabled**, failed 없음 |
| Kafka 설정 | `[실측 09-18]` | `ports: 127.0.0.1:9092:9092` · `KAFKA_LISTENERS=PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093,INTERNAL://0.0.0.0:9094` · `KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://localhost:9092,INTERNAL://kafka:9094` · `INTER_BROKER_LISTENER_NAME=INTERNAL`(compose 226-229행) |
| Kafka 런타임 | `[실측 09-18]` | 토픽 **4개**(`__consumer_offsets` + `mk2.telemetry.{heartbeat,state,status}`) · 컨슈머 그룹 **2개**(`mk2-storage`·`mk2-ws`, **LAG 전부 0**) · 오프셋 heartbeat 200 · status 140 · state 127.<br>⚠ 두 그룹의 `HOST`가 **`/172.18.0.1`**(도커 브리지 게이트웨이)다 — 호스트 프로세스가 발행 포트를 거쳐 들어온다는 뜻이고, **MySQL 계정이 `@'172.18.%'`인 이유와 같다**(제약 29).<br>⚠ **`KAFKA_AUTO_CREATE_TOPICS_ENABLE=false`** — 없는 토픽에 발행하면 조용히 실패한다. **Phase 4는 새 토픽을 만들지 않는다**(엣지도 기존 3개에만 쓴다). |
| Kafka 클라이언트 | `[전사]` | **백엔드 3개뿐**(host 프로세스, `settings.kafka_bootstrap()` 기본 `localhost:9092`). `INTERNAL`을 쓰는 클라이언트 **0**. ⚠ compose 주석 232-233이 **사실과 반대**(단계 6-b) |
| ufw | `[실측 09-18]` | **9092 규칙 없음** · **4316 규칙 없음** · `4317/tcp ALLOW Anywhere`[12] · 7859[8]·7862[4]·7864[2]·9101[3]·8522·5000~5002·8100·7865·7866·9000·6443 등, DENY 8종.<br>🔴 **9100이 두 줄이다** — `[6] ALLOW IN 172.16.0.0/12 # rpi pushgateway <- docker` + `[7] ALLOW IN Anywhere`. 같은 패턴이 `[36] 9110 <- 172.18.0.0/16 # node-exporter <- dg prometheus`·`[37] 9120`에도 있다. **§5 정정의 9100 실측은 [6](컨테이너→호스트) 경로였다** — 단계 6-b·7-h의 결정적 근거 |
| LISTEN | `[실측 09-18]` | `127.0.0.1:8765`(python) · `127.0.0.1:9092` · `127.0.0.1:4316` · `127.0.0.1:7859` · `0.0.0.0:4317`(+v6) · `0.0.0.0:3100`·`3200`·`1883`·`7858`·`7860`·`7861`·`7862`·`7863`·`9100`·`9101`. **7864 없음**(AI 파트가 필요할 때만 켠다 — 건드리지 않는다). **8766·8767·9095·4318 없음** = Phase 4가 여는 자리 |
| Tailscale | `[실측 09-18]` | 팀 공용 계정 · 서버 `<서버 tailscale IP>`(실값 `_serverinfo/`). **tailnet 11대** — 서버 · **컴퓨터(임시 엣지)** · `desktop-0ib285f` · `desktop-oaujese`(AI 탐지) · `laptop-isk6l1rq`(offline) · `pi1`(offline) · `pi2` · `pi4`(offline) · `pi6` · `pi7`(offline) · `ubuntu3`. **`jin03`이라는 이름은 없다.** ⚠ **VZ 관제 노트북이 어느 것인지 확인되지 않았다**(`laptop-isk6l1rq`가 후보) — 부록 B 10①에서 직접 묻는다 |
| 설정 md5 | `[실측 09-18]` | collector `e7a888c8…` · loki `678db4b0…` · tempo `416750de…` · prometheus `d7e1304d…` — **Phase 3 값과 전부 일치** |
| **compose md5** | `[실측 09-18]` | **서버 `2fa97cc75b123162b24e8108bec02cbc` ↔ 컴퓨터 작업본 `16A704A9A7BF2736ED82F4F4B4E4EEBD` — 다르다.** 제약 18. ⚠ `infra/docker-compose.yml`은 gitignore이고 git에 추적된 적이 없어 **대조 수단이 md5뿐**이다 |
| Collector receiver | `[실측 09-18]` | 🔴 **`http:` 블록·`4318`·`cors`가 설정 파일에 없다.** grep에 걸린 3줄은 전부 **Loki 향 exporter(`otlp_http`)**다. 결정 7 A는 **receiver 신설 + CORS + compose + ufw 네 곳**이다 |
| 관측 흐름 | `[실측 09-18]` | **`be_*` 이름 28종** = **A층 11**(`be_ingest_received_total`·`be_ingest_rejected_total`·`be_kafka_produce_total`·`be_storage_consumed_total`·`be_storage_write_total`·`be_registry_observe_total`·`be_gateway_push_total`·`be_gateway_clients`·`be_pipeline_lag_seconds_{bucket,sum,count}`) + **C층 17**(`be_telemetry_*`, `C_LAYER_PREFIX`가 `"be.telemetry."`이므로 **전부 우리 것이다**).<br>**Loki 라벨 3종만** — `service_name`·`service_namespace`·`service_instance_id`. `service_name` 값 **4개**: `be-gateway`·`be-ingest`·`be-storage`·`hw-sensor-node`. **금지 라벨은 하나도 새 나가지 않았다**(단계 5-3 기준선).<br>🔴 **Tempo `resource.service.name`에 우리 3개가 없다** — 값은 `be-test-span-*` 4개 + `hw-sensor-node`뿐이다. **Phase 3은 로그·지표만 붙였고 트레이스는 테스트 스팬이 전부다.** Phase 4도 트레이스를 새로 붙이지 않는다(결정 7 4318 이월과 일관).<br>⚠ **Loki·Tempo 조회에는 `start`·`end`가 필수다**(기본 6시간 — 제약 31). 1차 조회가 빈 배열이었던 원인이 이것이다.<br>🟠 **Prometheus 스크레이프 타깃 `host.docker.internal:8000`이 `down`이다**(나머지 4개는 `up`). `ss`에 8000 LISTEN이 없으니 **옛 타깃이 남은 것**이다. Phase 4는 고치지 않되 기준선에 적는다 — DoD에 *"타깃 전부 up"*을 쓰지 않는다 |
| TSDB | `[실측 09-18]` | `telemetry` **813행**(745 → **+68**) = `wl` 448 · `gap` 252 · `st` 94 · `reg` 14 · `tsdb` 5. **증가분 68 = gap 42 + st 17 + wl 9 → 전부 테스트 접두사.** DoD 0-2 충족 |
| MySQL `mk2` | `[실측 09-18]` | **8.0.44.** `mk2_app` 권한이 **`@'172.18.%'`**에 붙어 있다(제약 27이 맞았다 — `@'%'`는 존재하지 않는다). 테이블별: `audit_log`·`mission_event` **SELECT,INSERT** · `registry_*_observed`·`registry_identity_history` **SELECT,INSERT,UPDATE** · `registry_*_declared`·`registry_zone` **SELECT**. **DELETE·CREATE·ALTER·DROP 어디에도 없다** — 「권한이 삭제를 막는다」가 실제로 그렇다.<br>🔴 **`sql_mode`에 `STRICT_TRANS_TABLES`·`NO_ZERO_DATE`가 있다** — 값이 잘리거나 `'0000-00-00'`이면 **경고가 아니라 오류**다. 단계 10의 `varchar` 길이를 넉넉히 잡고 `started_at`을 **`NULL`**로 두기로 한 결정이 이것과 맞는다.<br>⚠ **`time_zone=SYSTEM`** · `character_set_server=utf8mb4` / `collation_server=utf8mb4_0900_ai_ci`인데 **`mission_event` 테이블은 `utf8mb4_bin`을 따로 명시**하고 있다 → `media_capture`도 **반드시 명시**한다(안 적으면 서버 기본값이 되어 대소문자 구분이 달라진다). `TIMESTAMP` 금지·`DATETIME(6)` UTC·`DEFAULT (utc_timestamp(6))`는 `mission_event` DDL이 쓰는 그대로다.<br>**`media_capture`는 9번째 신설이며 GRANT가 따로 필요하다**(제약 27) |
| 디스크 | `[실측 09-18]` | `/` 단일 볼륨 **3.6T, 979G 사용, 2.5T 여유(29%)**. TSDB·MySQL·Loki·docker가 전부 같은 볼륨 |
| **파이썬 환경** | `[실측 09-18]` | venv = `/home/dg/capstone-db/phase1_work/venv_phase1/`(**시스템에 `python`이 없다 — venv 안에서만 있다**).<br>`jsonschema` **4.26.0** · `websockets` **17.1** · **`referencing` 설치됨 → 결정 12를 새 의존성 없이 그대로 간다** |
| **websockets 기본값** | `[실측 09-18]` | 🔴 **세 값이 전부 설계를 바꾼다** — `max_size` **1048576(1MB)** · `write_limit` **32768(32KB)** · `compression` **`deflate`**(켜져 있다) · `ping_interval`/`ping_timeout` 20/20.<br>**`write_limit` 32KB는 H.264 `T_drop ≈ 10.3KB`의 3배다** — 큐 회계에서 빠지는 바이트가 임계보다 커서 150ms 바운드가 그대로는 성립하지 않는다(단계 2-3·2-4) |
| **pytest 기준선 N** | `[실측 09-18]` | **N = 184.** 파일별: `test_observability_labels` 45 · `payload_contract` 34 · `c_layer_extract` 24 · `registry_guards` 15 · `gap_detection` 11 · `mysql_storage` 10 · `mission_event` 10 · `storage_record` 9 · `pipeline` 8 · `tsdb_storage` 7 · `observability_pipeline` 7 · `observability_isolation` 4.<br>⚠ **단계 5-3에서 금지 라벨을 9종 더하면 `test_observability_labels.py`가 자동으로 +9 → 193**이 된다 |
| **iptables** | `[실측 09-18]` | **제약 16의 근거.** `DOCKER-USER`가 비어 있고(규칙 0개), `FORWARD` 순서가 `… DOCKER-USER → DOCKER-FORWARD → … → ufw-before-forward …`라 **도커 발행 포트는 ufw 체인에 닿기 전에 ACCEPT된다.** nat `DOCKER`에서 `-d 127.0.0.1/32`가 붙은 것은 **9092·7859·4316 셋뿐** → **실제로 막는 것은 compose 바인딩 주소다.**<br>⚠ `-P FORWARD DROP`이고 **k3s·kube-router·flannel이 `FORWARD`를 동적 관리**한다 — 이 체인을 건드릴 일이 생기면 `iptables-save` 전체 덤프를 쓰지 않는다 |
| 되돌린 자리 | `[전사]` | compose 4316 Tailscale 줄 **주석** · `prometheus.yml` `edge_federate` 잡 **주석**(타깃은 검증 때 쓴 컴퓨터 주소 `<컴퓨터 tailscale IP>:9090`이 그대로 — 이번 임시 엣지 검증에 그 값을 쓴다) |

**착수 시 돌릴 명령(대조용) — 전부 읽기 전용이다. 상태를 바꾸는 명령은 이 블록에 없다.**

```bash
# ── 블록 1. 컨테이너·유닛 ────────────────────────────────────────────────
cd /home/dg/capstone-db
docker compose ps --format '{{.Name}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
docker inspect capstone_otel_collector capstone_prometheus --format '{{.Name}} {{.Config.Image}} {{index .RepoDigests 0}}'
systemctl is-active  mk2-ingest mk2-storage-consumer mk2-ws-echo
systemctl is-enabled mk2-ingest mk2-storage-consumer mk2-ws-echo
systemctl --failed | grep -i mk2 || echo "failed 유닛 없음"
```

```bash
# ── 블록 2. tailnet (pi4·pi6·jin03 판정) ─ tailscale up 을 치지 않는다(제약 17)
tailscale ip -4
tailscale status
```

```bash
# ── 블록 3. 네트워크 노출 ────────────────────────────────────────────────
sudo ufw status numbered
sudo ss -tulpn | grep LISTEN
sudo iptables -t nat -S DOCKER | head -20      # 제약 16 · 단계 7-h 의 근거
sudo iptables -S DOCKER-USER
```

```bash
# ── 블록 4. Kafka 실값 ──────────────────────────────────────────────────
cd /home/dg/capstone-db
grep -n 'KAFKA_LISTENERS\|ADVERTISED\|SECURITY_PROTOCOL_MAP\|INTER_BROKER\|9092' docker-compose.yml
# ⚠ apache/kafka 이미지는 CLI 가 /opt/kafka/bin/*.sh 다. 확장자 없이 부르면 127 로 끝난다(09-18 실측)
docker exec capstone_kafka /opt/kafka/bin/kafka-broker-api-versions.sh --bootstrap-server localhost:9092 | head -3
docker exec capstone_kafka /opt/kafka/bin/kafka-topics.sh              --bootstrap-server localhost:9092 --list
docker exec capstone_kafka /opt/kafka/bin/kafka-consumer-groups.sh     --bootstrap-server localhost:9092 --list
```

```bash
# ── 블록 5. 관측 평면 실값 (be_* 전수가 핵심) ─────────────────────────────
# ⚠ Prometheus 호스트 포트는 9090 이 아니라 7861 이다(09-18 실측). 9090 으로 물으면 조용히 0 이 나온다
curl -s 'http://localhost:7861/api/v1/label/__name__/values' | tr ',' '\n' | grep -o 'be_[a-z_]*' | sort -u
curl -s 'http://localhost:7861/api/v1/label/__name__/values' | tr ',' '\n' | grep -c 'be_'
curl -s 'http://localhost:7861/api/v1/targets' | grep -o '"job":"[^"]*"' | sort -u
# Loki — 09-18 에는 라벨값이 빈 목록이었다. 조회 창을 넓혀 다시 본다
curl -s 'http://localhost:3100/loki/api/v1/labels'
curl -s "http://localhost:3100/loki/api/v1/label/service_name/values?start=$(date -d '7 days ago' +%s)000000000"
# Tempo — v2 는 식별자 파싱이 까다롭다. v1 과 resource 접두 둘 다 시도
curl -s 'http://localhost:3200/api/search/tag/service.name/values' | head -c 600; echo
curl -s 'http://localhost:3200/api/v2/search/tag/resource.service.name/values' | head -c 600
```

```bash
# ── 블록 6. 저장 축 ─────────────────────────────────────────────────────
docker exec capstone_timescaledb psql -U postgres -d mk2 -tAc "SELECT count(*) FROM telemetry;"
docker exec capstone_timescaledb psql -U postgres -d mk2 -tAc "SELECT split_part(source_id,'-',1) AS pre, count(*) FROM telemetry GROUP BY 1 ORDER BY 2 DESC;"
# MySQL — 🔴 .env 를 경유하지 않는다(제약 31). 컨테이너 자기 환경변수를 쓴다
docker exec -i capstone_mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -e "SHOW TABLES IN mk2;"'
df -h /
```

```bash
# ── 블록 7. 설정 지문 + Collector receiver ───────────────────────────────
md5sum /home/dg/capstone-db/docker-compose.yml /home/dg/capstone-db/config/*.yaml /home/dg/capstone-db/config/prometheus.yml
grep -n 'http:\|4318\|cors' /home/dg/capstone-db/config/otel-collector-config.yaml || echo "4318/http/cors 없음"
```

```bash
# ── 블록 8. 파이썬 실행 환경 (결정 12 · 단계 2-4 · 단계 2-3 회계) ──────────
# ⚠ 시스템에 `python` 이 없다(python3 만 있다). venv 를 먼저 켠다 — 09-18 실측 경로:
cd /home/dg/capstone-db/phase1_work && . venv_phase1/bin/activate && cd Physical-Project-mk2
python -c "import jsonschema, websockets; print('jsonschema', jsonschema.__version__); print('websockets', websockets.__version__)"
python -c "import referencing; print('referencing OK')" || echo "referencing 없음 → 결정 12 를 인라인(㉮)으로 내릴지 판단"
python - <<'EOF'
import inspect
from websockets.asyncio.server import serve
sig = inspect.signature(serve)
for k in ('max_size','write_limit','compression','ping_interval','ping_timeout'):
    p = sig.parameters.get(k)
    print(k, '=', p.default if p else '(없음)')
EOF
```

```bash
# ── 블록 9. pytest 기준선 N (제약 24) ────────────────────────────────────
cd /home/dg/capstone-db/phase1_work && . venv_phase1/bin/activate && cd Physical-Project-mk2
python -m pytest --collect-only -q 2>&1 | tail -3
python -m pytest --collect-only -q 2>&1 | grep '::' | cut -d: -f1 | sort | uniq -c | sort -rn
```

```bash
# ── 블록 10. 서버↔저장소 SQL 대조 (제약 30 · 단계 10 선행) ─────────────
ls -l /home/dg/capstone-db/mk2_sql/                # 서버 SQL 폴더 (저장소 infra/sql/ 과 이름이 다르다)
md5sum /home/dg/capstone-db/mk2_sql/mk2_mysql_schema.sql
docker exec -i capstone_mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -t' <<'SQL'
SHOW TABLES IN mk2;
SQL
```

> **컴퓨터(PowerShell)에서 두 줄 더:** `Get-FileHash .\infra\docker-compose.yml -Algorithm MD5`(서버 md5와 대조 — 제약 18) · `Get-FileHash .\infra\sql\mk2_mysql_schema.sql -Algorithm MD5`(서버 `mk2_sql/` 값과 대조 — 제약 30).

**DoD**

- **0-1** `[실측 09-18]` 등급 행과 어긋나면 **멈추고 보고한다.** `[전사]` 등급 행과 어긋나면 **차이를 기록하고 진행**하되, **Kafka 리스너·ufw·바인딩**에 관한 행이 어긋나면 멈춘다.
- **0-1b** ✅ **`[재실행 대기]` 5행이 전부 채워졌다(2026-09-18 2차).** 표는 실측본이다. 착수 시 다시 돌려 **어긋나면 멈춘다.** 기준선 넷을 그대로 쓴다:
  - **`be_*` 28종** = A층 11 + C층 17. `observability.py:74`의 `C_LAYER_PREFIX = "be.telemetry."`가 근거이므로 **`be_telemetry_*` 17종도 우리 것이다** — 남의 이름공간이 섞인 것이 아니다. 히스토그램 하나가 `_bucket`·`_sum`·`_count` 세 이름을 만드는 것은 정상이다. 🔴 **Phase 4가 미디어 계기 5개를 더하는데 `media_coldstart`가 히스토그램이라 이름은 7개가 늘어 35종이 된다**(A층 11 → 18).
  - **Loki 라벨 3종**(`service_name`·`service_namespace`·`service_instance_id`), `service_name` 값 4개. **금지 라벨은 하나도 새 나가지 않았다.**
  - **Tempo에 우리 서비스가 없다**(테스트 스팬 4 + `hw-sensor-node`). **Phase 4가 이것을 바꾸지 않는다.**
  - **Kafka 토픽 4 · 그룹 2 · LAG 0.**
- **0-1c** ✅ **`referencing`은 설치돼 있다**(09-18 실측) — 결정 12를 **레지스트리 방식 그대로** 간다. 인라인(㉮)으로 내리지 않는다.
- **0-1d** 🔴 **`websockets` 기본값 셋이 확정됐다**(09-18 실측: `max_size` **1048576(1MB)** · `write_limit` **32768(32KB)** · `compression` **deflate**). 따라서 단계 2-4의 **`MK2_MEDIA_MAX_FRAME_BYTES`·`MK2_MEDIA_WRITE_LIMIT`·`compression=None`은 선택이 아니라 필수**다.
  - `write_limit` 32KB는 H.264 `T_drop ≈ 10.3KB`의 **3배**다. 그대로 두면 **큐 회계에서 빠지는 바이트가 임계보다 커서 150ms 바운드가 성립하지 않는다.** 단계 2-3대로 **8KB로 내리고**, DoD 7-c의 실측을 `T_drop + write_limit` 기준으로 판정한다.
- **0-2** ✅ **`telemetry` 813행**(745 → +68). 증가분이 `gap` 42 · `st` 17 · `wl` 9로 **전부 테스트 접두사**임을 확인했다. 착수 시점에 다시 세어 **설명되지 않는 접두사가 새로 생기면 멈추고 보고한다.**
- **0-3** **compose 작업본을 서버 파일로 덮고 md5를 기록**했다(제약 18). 이 단계 뒤에는 작업본 md5 = 서버 md5여야 한다.
  - **방법:** Claude Code는 서버에 붙지 않는다. **사람이** 서버 `/home/dg/capstone-db/docker-compose.yml`을 내려받아 `infra/docker-compose.yml`에 **통째로 덮어쓴다**. 작업본은 gitignore라 평문 비밀번호가 있어도 커밋되지 않는다(그대로 둔다).
  - **대조:** 서버 `md5sum …/docker-compose.yml` ↔ 컴퓨터 PowerShell `Get-FileHash .\infra\docker-compose.yml -Algorithm MD5`. **두 값이 같아야 한다.**
  - ⚠ **줄바꿈이 CRLF로 바뀌면 md5가 달라진다.** 복사 후 LF인지 확인한다(제약 12).
- **0-4** `tailscale ip -4`가 주소를 준다(제약 15의 선행 확인).
- **0-6** **서버 `mk2_sql/`와 저장소 `infra/sql/`의 `mk2_mysql_schema.sql` md5를 대조했다**(제약 30 — 09-18에 크기가 달랐다: 서버 23,864 ↔ 저장소 26,931). **단계 10 전에만 필요하다** — 차이가 있으면 어느 쪽이 앞선 것인지 한 줄로 `reports/`에 적고, 저장소가 앞서면 그 델타를 단계 10보다 먼저 적용한다. `SHOW TABLES IN mk2`(09-18 기준 8개)도 같이 적는다.
- **0-4b** **tailnet 기기 목록을 실측으로 받았다**(09-18: 11대). ⚠ **VZ 관제 노트북이 그중 어느 것인지는 아직 모른다** — 부록 B 10①에서 받기 전까지 **8765·4318의 VZ 쪽 ufw `/32`를 열지 않는다.**
- **0-5** ✅ **pytest 기준선 N = 184**(09-18 실측, 12개 파일). 이후 모든 DoD의 "184"는 **N**으로 읽고, **단계 5-3의 라벨 9종 확장이 `test_observability_labels.py`를 +9 시켜 193이 되는 것**을 정상으로 본다.

---

### 단계 1. 공통 규격 신설·개정 — **규격이 코드보다 먼저**

plan §2의 우선순위 원칙 ①이다. 여기서 정한 것이 단계 2~3의 입력이 된다.

#### 1-1. `contracts/common/media-header.schema.json` **신설**

방식 B 메시지의 **JSON 헤더** 규격이다. 삼중항을 평면으로 펴지 말고 **`frame_ref` 객체가 `frame-reference.schema.json`을 `$ref`** 한다(정의는 한 곳 — `object-reference.schema.json:47-49`가 같은 방식이다).

| 필드 | 타입 | 필수 | 비고 |
|---|---|---|---|
| `frame_ref` | `$ref frame-reference.schema.json` | ✅ | `source_id`·`capture_timestamp`(ISO)·`sequence_id` |
| `encoding` | string (minLength 1) | ✅ | **enum 없음.** `$comment`에 *"알려진 값: `h264`·`jpeg`. 생산자 어휘이므로 고정하지 않는다"* |
| `keyframe` | boolean | ✅ | **서버가 drop-old에 쓰는 유일한 값.** JPEG는 항상 `true` |
| `width` / `height` | integer (≥1) | ✅ | 탐지 좌표의 기준 해상도(`coord.ref_width/ref_height`)와 같은 값. ⚠ **VZ는 프레임 자신에도 좌표 선언을 들고 있다**(`VideoFrame.reference{width,height}`) — 그쪽 주석이 *"탐지의 `bbox_space.reference`와 **같은 값을 공유해야** 둘을 같은 화면에 겹칠 수 있다"*고 못 박았다. **이 두 칸이 그 자리다**(부록 B 6번에 그대로 적는다) |
| `codec` | string \| null | | RFC 6381(예 `avc1.…`). **뷰어 WebCodecs `configure()`가 쓴다.** `h264`면 채운다 |
| `correlation_id` | string \| null | | **결정 2** — 어느 명령의 산출인가(상관키는 `frame_ref` 밖이다). 발급은 백엔드 Phase 6이라 지금은 자리만 |

- `additionalProperties`를 **`false`로 두지 않는다** — 생산자가 필드를 하나 더해 전량 거부되는 사고를 만들지 않는다(payload 6종과 같은 규칙).
  ⚠ **단 `frame_ref`가 `$ref`하는 `frame-reference.schema.json:7`에는 `additionalProperties: false`가 있다.** 즉 `frame_ref` **안쪽**에는 필드를 더할 수 없다(결정 2의 "개정하지 않는다"와 일관). 미디어 헤더 **바깥**에만 자유가 있다. 이 예외 관계가 `contracts/common/README.md:146`(*"payload에는 `additionalProperties: false`를 쓰지 않는다"*)과 충돌해 보이므로 **단계 1-4에서 한 줄로 적는다.**
- `$comment`에 **"서버는 이 헤더의 필수·타입만 검증하고 값 어휘를 보지 않는다. 페이로드는 열지 않는다"**를 적는다.
- **검증기는 한 번만 만들어 재사용한다.** 30fps × 소스 수만큼 초당 검증이 돌아가므로 프레임마다 `Draft202012Validator(...)`를 새로 만들지 않는다(`envelope.py`의 `_payload_validators` 캐시와 같은 방식).

#### 1-2. `contracts/common/frame-reference.schema.json` **description 개정**(구조 무개정)

- `capture_timestamp` description에 추가: **"엣지가 프레임 경계를 확정한 시각(도착)이며 촬영 시각이 아니다. 말단 내부 지연이 포함되고 보정되지 않았다."** 크기 근거로만 *"HW 실측 1회 ≈0.3초(상수 아님)"*. **이 숫자를 규격값으로 쓰지 않는다.**
- 전체 description의 *"엣지가 **디코드 시점**에 단 한 번 부여"* → **"엣지가 프레임 경계를 확정하는 시점(액세스 유닛 재조립 또는 디코드)에 단 한 번 부여"**.
- **구조는 바꾸지 않는다** — `additionalProperties: false` 유지, 필드 추가 없음(결정 2 — 구조 무개정).

#### 1-3. `contracts/common/detections.schema.json` **초안 신설**

⚠ **`payload/` 아래에 두지 않는다.** `payload/`는 **MQTT 토픽으로 고르는 채널 본문** 자리이고(`contracts/common/README.md` 「느슨한 2단」), `detections`는 이번에 라우팅하지 않는 채널이다. `frame-reference`·`object-reference`와 같은 **`contracts/common/` 루트**에 둔다.

> ⚠ **v1의 근거 한 줄을 정정했다.** v1은 *"`observation_hints()`가 `payload/`를 **재귀로** 훑으므로 27→22 검산에 영향을 준다"*고 적었는데 **코드가 다르다** — 재귀는 **스키마 안의 `properties` 트리**에 대한 것이고, 폴더 스캔은 `known_entity_types()`가 **`glob("state.*.schema.json")`(비재귀)** 로만 한다. 따라서 `detections.schema.json`을 `payload/`에 둬도 **검산에는 영향이 0**이다. **결론(루트에 둔다)은 그대로 옳고 근거만 바꾼다.**

02-media-path §1-6-2의 `type:"detections"` 모양을 규격 파일로 만든다. **생산자는 AI이고 우리는 형식 초안을 준다**(§1-5-3).

- `frame_ref`: `$ref frame-reference.schema.json`(선택 — 온디바이스 결과는 없을 수 있다)
- **`alignment`**: string, **선택**. `$comment`에 *"알려진 값: `frame`·`unaligned`. **메시지 단위**다. **이 키가 없으면 `unaligned`로 취급한다**"*
  ⚠ **v1은 「필수」였는데 결정 3의 fail-safe 규칙(*"부재·모르는 값 포함 전부 unaligned 취급"*)과 모순이었다.** 필수면 부재는 unaligned가 아니라 **거부**이고, 생산자인 AI는 이 필드를 아직 모르므로 현행 메시지가 전량 격리 대상이 된다. 「느슨한 2단」 철학대로 **선택 + 기본 의미**로 둔다.
- **`origin`**: **메시지 단위 객체**, 선택. `{tier(string), kind(string)}`.
  🔴 **이것이 없으면 VZ가 탐지를 통째로 버린다.** VZ `src/tabs/data/vision.ts:217-224`의 `FrameBuffer.pushDetection`이 `const tier = result.origin?.tier; if (tier !== 'device' && tier !== 'edge') return;` 다. **박스 단위 `boxes[].source`로는 이 검사를 통과하지 못한다** — 층이 다르고 값도 다르다(`ondevice` ≠ `device`).
  - `tier` 알려진 값 **`device`·`edge`·`server`**(`$comment`, enum 아님). **실제 배치와 1:1이다** — `device`=pi7 온디바이스 / `edge`=엣지 노트북 / `server`=서버(결정 11).
  - `kind` 알려진 값 `safety_minimal`·`precise`(VZ `DetectionOrigin` 타입과 같은 어휘).
    🔴 **`origin_kind`(공통 헤더)와 이름이 겹치지만 뜻이 다르다 — 그 사실을 `$comment`에 박는다.** 공통 헤더 `origin_kind`는 **실물/시뮬/재생**(VZ-C-06, VZ 확정 어휘 `physical`·`simulation`·`replay`)이고, 여기 `origin.kind`는 **탐지 정밀도 등급**이다. 두 축이 같은 낱말을 쓰면 회신에서 반드시 엉킨다. `$comment`에 *"공통 헤더의 `origin_kind`(실물/시뮬/재생)와는 다른 축이다"*를 적고, **부록 B·D 양쪽에 같은 문장을 넣는다.**
    ⚠ **서버가 중계분에 `origin`을 채우지 않는다.** 우리가 HW에 *"`origin_kind` 미기재는 조회 시 `real`로 해석한다 … **둘 다 백엔드가 임의로 채워 넣지 않는다** — 채우면 '생산자가 안 보낸 것'과 '백엔드가 채운 것'을 나중에 구분할 수 없다"*(`hw-envelope-conformance.md` §6)라고 이미 확정 통보했다. **결정 11의 서버 비전이 자기 산출물에 `tier="server"`를 붙이는 것은 생산자 기입이라 허용**이고, **중계하는 남의 탐지에 붙이는 것은 금지**다. 이 구분을 `$comment`와 부록 D에 적는다.
  - ⚠ **`server`를 지금 넣는다.** VZ 쪽은 `tier`가 타입·`Map` 키·`resolveAlignment` 루프 세 곳에 박혀 있어, 나중에 넣으면 **VZ에 계약 변경을 다시 요청해야 한다**(부록 B 6번).
- `coord`: `{normalized(boolean), origin(string), ref_width(int), ref_height(int)}`. **`normalized: true`를 기본으로 권장**(0~1, 해상도 무관).
  ⚠ **`origin` 값은 `top-left`(하이픈)다.** VZ가 리터럴 하나로 고정했고(`src/tabs/data/vision.ts:47`·`gateway/vision.ts:72,313`), VZ 저장소에 `top_left`(밑줄)는 **0건**이다. 우리 `02-media-path.md` §1-6-2 예시가 밑줄이었으므로 **그쪽을 하이픈으로 고친다**(§8 갱신 대상).
  ⚠ VZ는 이 선언을 `bbox_space{format, origin, reference{width,height}}`로 들고 있다 — **이름·타입·구조가 넷 중 셋 다르다.** 어느 쪽 이름으로 맞출지는 부록 B 6번에서 묻는다. **`normalized`는 VZ가 이미 지원한다**(`format:'normalized'` 분기가 렌더러에 있다) — 기본값만 `absolute`라 전환 요청이다.
- `boxes[]`: `{x,y,w,h,label,confidence?}`. ⚠ **박스 단위 `source`는 버린다** — 출처는 위의 메시지 단위 `origin`이 담당한다.
- ⚠ **채널·토픽을 신설하지 않는다.** 이 규격은 **통지용 초안**이고, `mk2.telemetry.detections` 토픽·ingest 구독 패턴 변경·`entity_type` 판별은 **이번 범위가 아니다**(§6 울타리). 필요해 보이면 멈추고 묻는다.
- ⚠ **파일 머리의 `$comment`에 이렇게 적는다:** *"초안 — 2026-09-18 현재 어떤 검증 경로도 이 파일을 로드하지 않는다. AI(생산자)·VZ(소비자) 회신 뒤 확정한다."* `object-reference.schema.json`이 이미 그 상태(아무도 안 읽는 규격)라, 같은 상태의 파일을 말없이 하나 더 늘리지 않는다.

#### 1-4. `contracts/common/README.md` 갱신

- 「파일」 표에 `media-header.schema.json`·`detections.schema.json` 행 추가(**둘 다 `payload/`가 아니라 `contracts/common/` 루트**).
- `frame_ref` 뜻(1-2의 문구)을 「프레임 참조와 객체 참조 — 다른 축」 절에 한 줄.
- **`additionalProperties: false` 예외를 한 줄 적는다** — *"「payload에는 쓰지 않는다」는 채널 본문 규격에 대한 규칙이다. `frame-reference`·`object-reference` 같은 **참조 규격**은 필드 집합이 닫혀 있어야 정합이 성립하므로 예외다."*
- **라벨 금지 목록에 9종을 더한다**: `mission_id`·`node_ref`·`client_request_id`·`plan_id`·`event_key` + **발화 원문**(이름은 VZ 통지에서 확인 — 잠정 `utterance`·`transcript`) + **`frame_ref`** + **`correlation_id`** + **`command_id`**.
  - ⚠ **`frame_ref`·`correlation_id`·`command_id` 셋이 v1에 없었다.** 우리가 VZ에 보낸 통지(`vz-observability-namespace.md` §2)가 *"프레임 식별자(`frame_id`·**`frame_ref`** 등)"*와 *"**`command_id`**·`correlation_id` — 명령마다 다르다. trace 속성으로는 되지만 metric 라벨로는 안 된다"*를 **막는다고 적었는데 코드(`observability.py:64-66`, 7종)에도 `contracts/common/README.md:182`에도 없다.** 같은 절이 *"백엔드는 이 목록을 **코드로 막는다**"*라고 VZ에 약속해 놨다 — **약속을 절반만 이행한 상태를 이번에 닫는다.**
  - ⚠ **`node_id`는 넣지 않는다** — VZ의 `node_id`는 DAG 노드 뜻이고 우리 공통 헤더 `node_id`는 물리 노드(pi1·pi7)라 저카디널리티·허용이다. **다만 VZ 코드에 `node_ref`라는 이름은 0건이고 와이어에 나가는 `node_id`는 전부 물리 노드다** — 그래서 `node_ref`만 막으면 **오늘 VZ가 실제로 내보내는 것 중 막히는 게 없다.** 부록 B 9번에 *"DAG 노드 라벨은 `node_ref`로 내보내 달라"*를 **명시적 요청**으로 적는다.
- ⚠ **"분기하는 필드만 enum" 같은 새 기준선을 넣지 않는다.** 기존 enum(`origin_kind`·`time_sync_state`)은 이번 범위 밖이라 손대지 않는다.

#### 1-5. `$ref` 해석 레지스트리 (결정 12) — **`contracts.py`가 아니라 `envelope.py`다**

`backend/contracts.py`는 스키마를 **dict로 읽기만** 하고 `jsonschema`를 import하지 않는다. 검증기는 전부 `backend/ingest/envelope.py`에 있다.

- 고칠 곳 **두 군데**: `envelope.py:89-92 build_validator()` · `envelope.py:102-112 payload_validator()`. 둘 다 `Draft202012Validator(schema, format_checker=…)`를 **레지스트리 없이** 만든다.
- `referencing.Registry`에 `contracts/common/` 아래 규격을 **`$id` → 로컬 파일**로 등록하고 두 생성자에 `registry=`로 넘긴다. 미디어 헤더 검증기도 같은 레지스트리를 쓴다.
- ⚠ **네트워크로 `$id` URL을 가져오려 하면 안 된다.** `$id`가 `https://github.com/khw18033/…`라 실제로 가져와도 HTML이고, 서버는 tailnet 안이라 막힌다.
- ⚠ **`referencing` 설치 여부를 단계 0에서 확인한다**(jsonschema 4.18+ 동봉). 없으면 **새 의존성을 임의로 추가하지 말고 멈추고 묻는다**(제약 22).

**DoD**

- **1-1** 세 규격 파일이 `jsonschema`로 로드되고 `$ref`가 **레지스트리로** 해석된다(네트워크 접근 0). `object-reference.schema.json`도 같은 레지스트리로 해석되는지 함께 확인한다 — **Phase 7이 그 경로를 그대로 쓴다**(추적표 BE-C-03에 한 줄 남긴다).
- **1-1b** `contracts.observation_hints()`의 **27 → 9·3·10 = 22 검산이 그대로다**(`tests/test_c_layer_extract.py` 통과).
- **1-2** `media-header.schema.json` 양성 fixture 1 + **음성 fixture 3**(`encoding` 누락 · `keyframe` 타입 오류 · `frame_ref.capture_timestamp`가 `+0900`)이 **의도대로 통과/거부**된다.
- **1-3** `encoding`에 **모르는 값**(예 `"av1"`)을 넣은 fixture가 **통과한다**(enum이 아님을 못 박는 음성 대조의 반대 축). `alignment`가 **없는** fixture도 통과한다(선택이므로).
- **1-4** 라벨 금지 **9종**이 `contracts/common/README.md`에 적혔고, `node_id`가 **들어가지 않았다**.

---

### 단계 2. 서버 미디어 중계 구현

> 이 단계는 **loopback 바인딩으로만** 만든다. 외부 노출은 단계 7이다.

#### 2-1. 파일 배치

| 파일 | 무엇 |
|---|---|
| `backend/gateway/media.py` **신설** | 방식 B 프레이밍(인코드·디코드) · **drop-old 상태 기계** · 중계 코어. **소켓을 모른다** — 그래야 패킷 배열만으로 단위 검증된다(HW `media_gateway.py`가 같은 구조다) |
| `backend/gateway/ws_echo.py` 갱신 | 경로 분기(`/state`·`/media`) · 토큰 검사 · 엣지 입구(`/ingest`, 별도 포트) 서버 추가. **파일명·유닛명은 바꾸지 않는다**(범위 확대 — docstring만 갱신) |
| `backend/gateway/console.html` 갱신 | 확인용 뷰어. §2-4 |
| `backend/settings.py` 갱신 | 환경변수(부록 C) |

#### 2-2. 방식 B 프레이밍

`[4바이트 빅엔디언 헤더 길이][JSON 헤더(UTF-8)][페이로드 바이트]`. **한 메시지 = 한 프레임**(H.264면 **한 액세스 유닛**). 반쪽 NAL을 절대 만들지 않는다.

- 수신: 앞 4바이트 → 헤더 길이 → JSON 파싱 → `media-header.schema.json` 검증(**필수·타입만**) → 나머지가 페이로드.
- **헤더 길이 상한**을 둔다(예 64KB). 넘으면 프레임을 버리고 기록한다 — 악의적/손상 입력에 메모리를 내주지 않는다.
- **순번 역전·불연속은 기록만 한다.** 거부하지 않는다 — 재접속 시 `sequence_id`가 정상적으로 리셋된다(`frame-reference.schema.json` 설명).
- **거부 대상은 헤더 필수·타입 위반뿐**이다.

#### 2-2b. 경로·쿼리를 어떻게 읽나 — 추측하지 말 것

⚠ **`ws_echo.py`의 핸들러는 `(websocket, path=None)`로 선언돼 있고, 서버 설치본은 websockets 17.1이다.** 새 asyncio 구현은 핸들러를 **인자 1개**로 부르므로 **`path` 인자는 항상 `None`이다.** 경로와 쿼리는 **`websocket.request.path`**에서 읽는다(websockets ≥14). 13 이하로 내려갈 때만 두 번째 인자로 물러선다 — 지금 코드의 import 폴백과 같은 방식으로 **양쪽에서 도는 작은 헬퍼 하나**를 둔다.

#### 2-2c. 라우팅 — `source_id`가 두 입구를 잇는다

- 서버는 **`source_id → 뷰어 소켓 집합`** 라우팅 테이블 하나를 들고 있다. `/ingest?source_id=X`로 들어온 프레임을 **그 `X`를 구독 중인 `/media` 소켓에만** 분기한다.
- ⚠ **헤더의 `frame_ref.source_id`와 쿼리의 `source_id`가 다르면 거부한다**(둘 중 하나를 믿고 나머지를 무시하면 조용히 엉뚱한 뷰어로 간다). 이것도 「헤더 필수·타입 위반」과 같은 거부 사유로 센다.
- **엣지가 없는 `source_id`에 뷰어가 붙으면** 소켓은 열리고 프레임이 오지 않는다 — 정상이며 뷰어에서 staleness로 보인다(§1-5-4).
- **같은 `source_id`로 엣지가 둘 붙으면 나중 것을 거부한다**(close 4409). 기본값이며, 다른 동작이 필요해 보이면 멈추고 묻는다.

#### 2-3. drop-old 상태 기계 (`02-media-path.md` §1-5-2 + 2026-09-18 수정 5건)

```
FLOWING   : keyframe=true  && buffered <= T_hard  → 보낸다
            keyframe=true  && buffered >  T_hard  → 버린다 + WAIT_IDR
            keyframe=false && buffered >  T_drop  → 버린다 + WAIT_IDR   (GOP 절단)
            keyframe=false && buffered <= T_drop  → 보낸다
WAIT_IDR  : keyframe=false                        → 전부 버린다
            keyframe=true  && buffered <= T_hard  → 보낸다 + FLOWING
            keyframe=true  && buffered >  T_hard  → 버린다 (계속 WAIT_IDR)
```

- **뷰어 소켓의 초기 상태는 `WAIT_IDR`이다.** 새로 붙은 뷰어에게 P프레임부터 주면 디코더가 구성조차 못 한다. **JPEG는 모든 프레임이 `keyframe=true`라 즉시 풀린다 — 코드가 한 벌이다.**
> ⚠ **`buffered`가 무엇인지 먼저 못박는다 — 서버에는 `bufferedAmount`가 없다.**
> `bufferedAmount`는 **브라우저 WebSocket API**의 속성이고, 파이썬 `websockets` 서버에는 그런 공개 속성이 없다(`transport.get_write_buffer_size()`는 내부 구현에 기댄다).
> **그래서 백프레셔를 우리가 들고 있는다.** 뷰어 소켓마다 **송신 큐(`asyncio.Queue`) + 전용 writer 태스크**를 둔다. writer는 `await websocket.send(...)`로 한 장씩 비우고, **큐에 쌓인 바이트 합계가 곧 `buffered`다.** 중계 코어는 `send`를 직접 부르지 않고 **큐에 넣을지 버릴지만** 판단한다.
> 이 구조가 세 가지를 동시에 해결한다 — ① `websockets` 내부에 의존하지 않는다 ② **느린 뷰어가 이벤트 루프를 막지 않는다**(§1-5-2 head-of-line) ③ 상태 기계가 소켓 없이 단위 테스트된다.
>
> ⚠ **그런데 큐 바이트만으로는 회계가 닫히지 않는다.** `await websocket.send(...)`가 반환해도 바이트는 링크에 나가지 않았고, **`websockets`의 전송 버퍼(`write_limit`)에 들어가 있으며 그 바이트는 우리 큐에 없다.** H.264의 `T_drop ≈ 10.3KB`보다 그 버퍼가 크면 **실제 지연은 `T_drop`이 아니라 `T_drop + write_limit`에 바운드된다** — 150ms를 목표로 잡고 실측이 몇 배로 나오는 전형적인 원인이다.
> **그래서 `write_limit`를 기본값에 맡기지 않고 소켓 생성 시 명시한다**(작게, 예 8KB). 단계 0 블록 8에서 그 판본의 기본값을 먼저 읽고, 지연 바운드를 **`T_drop + write_limit`**로 문서에 적는다. 실측은 `ss -tno`의 `Send-Q`와 함께 본다.

- **임계는 시간 기준이다**(고정 바이트가 아니다):
  - `T_drop = 150ms × 바이트율`.
    ⚠ **바이트율은 「도착률」이 아니라 「배출률」이다** — **writer 태스크가 실제로 비운 바이트 ÷ 시간**의 **소켓별 EWMA(최근 60프레임)**. 큐 지연 = 쌓인 바이트 ÷ **빠져나가는 속도**이고, 링크가 느려졌을 때(= drop-old가 필요한 바로 그때) 도착률과 배출률은 크게 벌어진다. 도착률로 재면 임계가 실제 지연을 바운드하지 못한다.
  - **하한 = 최근 60프레임 AU 평균 바이트 × 2**, **상한 1MB**.
  - `T_hard = max(4 × T_drop, 최근 IDR 5개 중 최대 바이트 × 2)` — IDR 하나가 통째로 들어갈 여유를 보장한다.
  - 🔴 **GOP가 없는 스트림에는 `T_hard`를 적용하지 않는다.** 최근 창(60프레임)에 `keyframe=false`가 **0건**이면 **`T_hard := T_drop`**으로 둔다.
    **이유:** `T_hard`의 존재 이유는 *"IDR을 버리면 GOP가 통째로 날아간다"*인데, **모든 프레임이 독립인 스트림에는 절단할 GOP가 없다.** 이 규칙이 없으면 **JPEG는 `T_drop`을 단 한 번도 쓰지 않는다**(모든 프레임이 `keyframe=true`라 항상 `T_hard` 분기로 간다). 15fps·25KB 기준으로 `T_hard = 4×56KB = 224KB`, 배출률 375KB/s → **실효 지연 상한이 150ms가 아니라 약 600ms**가 되어 DoD 7-c가 JPEG에서 어긋난다. 고정 CCTV가 JPEG 종단이므로 실배포에 그대로 걸린다.
  - 창(60프레임·IDR 5개)은 **기본값**이고 `media.py` 상수로 둔다. 표본이 그만큼 안 모인 초기에는 하한이 지배한다.
  - 검산: H.264 0.55Mbps → `T_drop ≈ 10.3KB`(하한 4.6KB보다 큼) / JPEG 15fps·25KB → `≈56KB`(하한 50KB보다 큼, **그리고 위 규칙으로 실제 임계도 56KB다**). **고정 하한 64KB는 H.264에서 0.93초 큐라 쓰지 않는다.**
- **느린 소비자의 수신 프레임률은 능력치가 아니라 GOP 경계로 결정된다**(기록 수준). H.264에서 P프레임 하나를 버리면 `WAIT_IDR`로 들어가 **다음 키프레임까지 전부 버린다** — 평균은 능력 근처인데 들쭉날쭉해진다. 필요하면 HW에 IDR 간격 축소를 요청하거나(현재 실측 0.48초) 그 소켓의 `T_drop`을 넉넉히 잡는다. **이번 Phase에서 고치지 않는다 — 보고서 「검증 범위의 한계」에 적는다.**
- **드롭은 뷰어 향 소켓마다 독립**이다. 느린 브라우저 하나가 다른 뷰어를 굶기지 않는다(§3-2).
- **엣지 입구에서는 버리지 않는다.** 받아서 분기만 한다 — 버리는 것은 엣지 몫(같은 상태 기계를 홉2 송신기 규격에 넣는다, 단계 9).
- **뷰어가 없으면 버린다**(`ws_echo.py:94`의 `if not clients: continue`와 같은 모양).

#### 2-4. 경로·포트·인증

| 입구 | 경로 | 포트 | 인증 | 바인딩(단계 2) | 바인딩(단계 7) |
|---|---|---|---|---|---|
| 뷰어 상태 | `/state?token=…` | 8765 | `MK2_WS_TOKEN` | `127.0.0.1` | **`127.0.0.1` + `<서버 tailscale IP>` 둘 다** |
| 뷰어 영상 | `/media?source_id=…&token=…` | 8765 | `MK2_WS_TOKEN` | `127.0.0.1` | **`127.0.0.1` + `<서버 tailscale IP>` 둘 다** |
| 엣지 수신 | `/ingest?source_id=…&token=…` | **8766** | `MK2_EDGE_TOKEN` | `127.0.0.1` | `<서버 tailscale IP>` |

- **`/media`에 붙는 것이 켜기, 끊는 것이 끄기다.** 제어 메시지가 없다. 소켓 하나당 소스 하나.
- **상시와 온디맨드가 같은 메커니즘이다** — 뷰어가 페이지 로드 때 붙으면 상시(**개발 프로파일 = 상시 모드**, §3-1), 패널 열 때 붙으면 온디맨드. 서버는 구분하지 않는다.
- 토큰은 **`hmac.compare_digest`**로 비교한다. 불일치·부재는 **close code 4401**.
- ⚠ **토큰이 로그에 남지 않게 한다.** 쿼리 문자열이 접속 로그·예외 메시지에 그대로 찍히면 `journalctl`과 Loki에 토큰이 평문으로 쌓인다. **로그에 경로를 남길 때 `token=` 값을 마스킹**하고, `websockets` 라이브러리 로거가 요청 줄을 찍는지 확인한다(찍으면 그 로거 레벨을 올린다).
- ⚠ **토큰 환경변수가 비었을 때의 동작을 하나로 통일한다.** v1은 여기서 *"그 입구를 열지 않는다"*, 부록 C에서 *"비면 외부 노출을 하지 않는다"*로 **서로 다르게** 적혀 있었다(앞은 리스너 없음, 뒤는 loopback으로 염). **`default_writer()`의 규율을 따른다** — 조용히 폴백하지 않는다:
  - **`MK2_WS_HOST`가 loopback이 아닌데 `MK2_WS_TOKEN`이 비어 있으면 기동 시점에 이름을 대며 죽는다.**
  - **loopback 바인딩일 때는 토큰 없이 연다**(개발·테스트 기본값). 로그에 한 줄 남긴다.
  - 엣지 입구(`/ingest`)도 같은 규칙을 `MK2_EDGE_TOKEN`에 적용한다.
- 🔴 **루트 경로(`/`)로 온 연결은 `/state`로 취급한다**(Phase 1 호환). 현재 핸들러는 경로를 **아예 보지 않으므로**(`ws_echo.py:115`) 이 하위호환에 깨지는 기존 동작이 없다.
  ⚠ **그래도 기존 테스트 2건은 토큰 때문에 깨진다.** `tests/conftest.py:54`의 `ws_url` fixture가 `settings.ws_url()`을 그대로 쓰고 그 기본값이 `ws://127.0.0.1:8765`(**경로도 토큰도 없다**, `settings.py:163`)인데, DoD 2-2·음성 대조 M1이 **무토큰 접속의 성공을 금지**하므로 토큰 하위호환을 둘 수 없다. **그래서 이 단계의 산출물에 다음을 명시적으로 넣는다:**
  - `settings.ws_url()`의 기본값을 **`ws://127.0.0.1:8765/state`**로 바꾸고, **`MK2_WS_TOKEN`이 설정돼 있으면 `?token=…`을 붙여 돌려준다.**
  - 영향받는 테스트는 `tests/test_pipeline.py::test_ws_delivery`와 `tests/test_observability_pipeline.py::test_gateway_metrics_with_ws_client` **둘뿐이다**(`grep -rn "ws_url" tests/` 전수).
  - 부록 C 환경변수 표에 **`MK2_WS_URL` 행을 추가**한다(v1에 빠져 있었다).
- 🔴 **소켓 옵션 셋을 기본값에 맡기지 않는다.** `/state`(작은 JSON)와 `/media`·`/ingest`(큰 바이너리)에 **따로** 준다.
  - **`max_size`** — `websockets` 기본값이 판본에 따라 **1MB**다. 방식 B 메시지 하나가 **AU 하나**이므로 큰 IDR·고해상도 JPEG가 오면 **close 1009로 엣지 연결이 끊긴다.** 단계 0 블록 8에서 기본값을 확인하고, `MK2_MEDIA_MAX_FRAME_BYTES`(기본 8MB)로 **넉넉히 올린 뒤 상한 판정은 우리 코드에서** 한다 — 넘는 프레임은 **연결을 끊지 말고 프레임만 버리고 기록**한다(순번 불연속과 같은 취급).
  - **`compression=None`** — 이미 압축된 JPEG/H.264를 permessage-deflate로 다시 압축하는 것은 순수 CPU 낭비다. `websockets`는 기본으로 켠다.
  - **`write_limit`** — 위 2-3의 백프레셔 회계.
- 두 포트는 **같은 프로세스의 두 서버**다(유닛을 늘리지 않는다). `MK2_MEDIA_INGEST_PORT=0`이면 엣지 입구를 열지 않는다 — **단계 8 되돌림이 환경변수 하나로 끝난다.**
- 🔴 **8765는 `127.0.0.1`과 `<서버 tailscale IP>`에 「둘 다」 바인딩한다.** 단계 7에서 Tailscale IP 하나로만 옮기면 **서버 loopback에서 붙는 pytest 2건과 `console.html`이 끊긴다**(`settings.ws_url()`이 `ws_host()`를 참조하지 않고 `127.0.0.1`을 하드코딩한다). Collector가 단계 5-1에서 *"loopback + Tailscale IP 둘 다 LISTEN"*을 요구하는 것과 같은 처방이다.
  - `MK2_WS_HOST`를 **콤마 구분 목록**으로 읽는다(`ws_host() -> list[str]`). `websockets`의 `serve(handler, host, port)`는 `host`를 `asyncio.loop.create_server`에 넘기고 그 함수는 **문자열 시퀀스를 받아 모든 주소에 바인딩**한다 — **이 동작을 단계 2에서 `ss -tlnp`로 실측해 판정한다.** 목록이 안 먹으면 같은 핸들러로 서버를 둘 열어(`asyncio.gather`) 같은 결과를 만든다.
  - **`settings.ws_url()`은 loopback을 유지한다.** Tailscale 주소로 바꾸면 컴퓨터에서 도는 단위 테스트가 서버 주소를 찾게 된다.

#### 2-5. 관측 (A층 — 전부 `be.gateway.*`)

| 계기 | 종류 | 라벨 | 뜻 |
|---|---|---|---|
| `be.gateway.media_frames` | counter | `component`·`outcome`(`sent`\|`dropped`) | 뷰어 향 전송·드롭 |
| `be.gateway.media_gop_cut` | counter | `component` | GOP 절단 횟수 |
| `be.gateway.media_coldstart` | histogram | `component`·`outcome` | **뷰어 연결 → 첫 프레임 전송**까지(초). 초기 `WAIT_IDR` 때문에 최대 GOP 길이가 더해진다. **버킷 `0.1 0.25 0.5 1 2 5 10 30`**을 View로 준다(`be.pipeline.lag` 선례). 값은 항상 양수라 음수 문제가 없다 |
| `be.gateway.media_rejected` | counter | `component`·`stage`(`header`\|`schema`\|`auth`) | 거부 |
| **`be.gateway.media_ingress`** | counter | `component` | **엣지 입구에서 받아 헤더 검증을 통과한 프레임 수.** 이것이 없으면 "영상이 안 나온다"에서 *엣지가 안 보냄*과 *서버가 버림*을 가르지 못한다 — `infra/README.md` §4 「떠 있다가 아니라 흐른다」가 경계하는 상태 |
| `be.gateway.clients` | updown | `component`·**`endpoint`**(`state`\|`media`\|`ingest`) | 기존 계기에 `endpoint` 라벨을 더한다 |

⚠ **라벨 이름을 `channel`로 쓰지 않는다.** `be.gateway.push`가 이미 `channel`을 **업무 채널**(`state`·`status`·`heartbeat` — Kafka 토픽 꼬리) 뜻으로 쓰고 있어(`ws_echo.py:104`), 값 `"state"`가 **같은 이름·다른 뜻**으로 겹친다. 대시보드에서 조용히 틀린다.

⚠ **라벨에 `source_id`·`sequence_id`·시각을 넣지 않는다** — 어댑터가 `ValueError`로 막는다(제약 6). **`frame_ref`는 지금 막히지 않으므로**(단계 5-3 #10에서 목록에 넣는다) 그 전까지는 **사람이 지킨다.** `be.gateway.clients`에 `endpoint`를 더하면 기존 호출부에도 `endpoint="state"`를 붙여 일관되게 한다. `tests/test_observability_pipeline.py:160`은 `sum(be_gateway_clients)` 집계라 라벨 추가로 깨지지 않지만, 라벨 검사를 새로 넣으면 그 파일도 함께 고친다.

#### 2-6. 확인용 뷰어 (`console.html`)

**판정용(필수)** — 도착 프레임 수 · keyframe 수 · `frame_ref` 원문 · 순번 연속성 · 드롭 구간을 **텍스트로** 찍는다.
**눈 확인(보조)** — JPEG는 `createImageBitmap`+`drawImage`, H.264는 WebCodecs. HW가 문서화한 브라우저 결함 5건을 적용한다(`prefer-software` · 최신 프레임만 rAF 주기로 · 보조 타이머 · `desynchronized` 제거 · `Cache-Control: no-store`). **판정 근거로 쓰지 않는다.**
**탐지 오버레이** — ⏭ **선택.** F==F 대조는 pytest 음성 대조 M6이 이미 판정하므로 **화면 오버레이는 시간이 남을 때만** 만든다. 뷰어 규칙만 주석으로 적어 둔다 — **결정 3 fail-safe**(`alignment=="frame"` + `frame_ref` 있을 때만 정합).

**DoD**

- **2-1** `media.py`의 프레이밍·상태 기계가 **소켓 없이** 단위 테스트된다(패킷 배열 입력 → 전송/드롭 판정 출력).
- **2-2** 토큰 없이 붙으면 **4401로 닫히고 프레임이 한 장도 나가지 않는다.**
- **2-3** 새 뷰어 소켓의 첫 전송이 **반드시 keyframe**이다.
- **2-4** `be_gateway_media_*` **5종**(`media_frames`·`media_gop_cut`·`media_coldstart`·`media_rejected`·**`media_ingress`**)이 어댑터를 통해 나가고 **금지 라벨이 없다.**
- **2-5** 코드를 서버 사본(`/home/dg/capstone-db/phase1_work/Physical-Project-mk2/`)에 복사하고 `sudo systemctl restart mk2-ws-echo` 했다(제약 20).

---

### 단계 3. 합성 fixture — 우리가 만든다

#### 3-1. 합성 H.264 Annex-B 파일 (커밋한다)

**컴퓨터에서 한 번 생성해 `tests/fixtures/`에 커밋한다.** 서버 ffmpeg를 전제조건으로 두지 않는다.

- 규격: **464×400**, 수 초, **IDR 간격 고정**, **파라미터 세트 반복**(매 IDR에 SPS·PPS 인밴드), Annex-B.
- 생성 스크립트(`tests/fixtures/make_h264_fixture.sh`)를 **함께 커밋**한다 — 재생성 가능해야 한다. 출발점:

  ```bash
  ffmpeg -f lavfi -i testsrc2=size=464x400:rate=30 -t 4 \
         -c:v libx264 -profile:v baseline -pix_fmt yuv420p \
         -g 15 -keyint_min 15 -sc_threshold 0 -b:v 600k \
         -f h264 tests/fixtures/synthetic_464x400.h264
  ```

  ⚠ **v1의 `-bsf:v dump_extra`를 뺐다.** raw h264 출력(`-f h264`)은 global header를 쓰지 않으므로 libx264가 **기본으로 매 IDR에 SPS·PPS를 인밴드로 반복한다.** bsf는 대개 불필요하고 실패 경우의 수만 늘린다.
  ⚠ **판정은 옵션이 아니라 실측으로 한다**: 바이트스트림에서 **NAL 타입 7(SPS)이 IDR 개수만큼 나오는지** 센다(스크립트에 그 검산을 넣는다). **한 번만 나오면 fixture가 틀린 것이다** — 뷰어가 중간부터 붙으면 디코더를 구성하지 못한다. 검산이 실패할 때만 `-x264-params repeat-headers=1`을 붙인다.
  ⚠ **`.gitattributes`에 `*.h264 binary` 한 줄을 먼저 추가한다**(제약 26). 지금 바이너리 목록에 `.h264`가 없고 `* text=auto eol=lf`가 전역이다.
- 합성 testsrc라 개인정보·비밀값이 없다. 크기는 수백 KB 수준이어야 한다(넘으면 길이를 줄인다).

**액세스 유닛 경계를 어떻게 자르나 — 추측하지 말 것.** Annex-B를 NAL로 자른 뒤(HW `go1_relay.py::split_annexb`와 같은 규칙: 3·4바이트 시작 코드) 이렇게 묶는다:

- **SPS(7)·PPS(8)·SEI(6)·AUD(9)는 뒤따르는 VCL NAL과 한 AU로 묶는다.**
- **VCL NAL(1=non-IDR, 5=IDR)을 만나면 그 AU를 닫는다**(이 fixture는 프레임당 슬라이스 1개다).
- **`keyframe = AU 안에 타입 5(IDR)가 있는가.**
- 이 규칙이 HW `go1_relay.py::packetize(nals, timestamp)`가 *"한 액세스 유닛의 NAL 들"*을 받는 전제와 같다 — **같은 규칙이어야 홉2 송신기 규격이 성립한다.**
  🔴 **주의 — HW는 이 규칙을 구현하고 있지 않다.** `go1_relay.py:163-170`은 **웹소켓 메시지 1개 = AU 1개**로 그냥 믿을 뿐이고, **NAL 타입 분류도 `keyframe` 판정도 HW 양끝(`go1_relay.py`·`edge/media_gateway.py`) 어디에도 없다**(`keyframe` grep 0건, 타임스탬프도 스트림이 아니라 벽시계다). 즉 **§3-1의 AU 규칙과 `keyframe` 플래그는 우리가 새로 정하는 것**이고, 그래서 §8 회신에서 **홉2 송신기 규격으로 요청**한다. *"HW가 이미 그렇게 한다"*로 읽으면 안 된다 — 로봇이 한 메시지에 AU 2개를 실으면 두 규칙이 갈린다.

#### 3-2. 합성 엣지 송신 fixture (`tests/media_publisher.py`)

**이것이 홉2 송신기의 참조 구현이다**(HW 회신에 그렇게 적는다).

- Annex-B 파일을 **액세스 유닛 단위로 잘라** 읽고, AU마다 **`frame_ref`를 부여**한다 — `source_id`(인자), `capture_timestamp`(**ISO, 부여 시각**), `sequence_id`(단조 증가).
- 방식 B로 인코드해 `/ingest?source_id=…&token=…`로 보낸다. `keyframe`은 **IDR 여부**로 채운다.
- JPEG 프로파일: 커밋된 JPEG 몇 장을 반복 재생, `keyframe=true` 고정, `encoding="jpeg"`.
- **같은 `frame_ref`를 담은 가짜 탐지 메시지를 JSON 파일로 남긴다**(`alignment:"frame"`, `coord.normalized:true`) — 확인용 뷰어의 오버레이 대조 재료.
- CLI: `--source-id`·`--encoding`·`--fps`·`--loop`·`--url`. **MQTT·Kafka에 붙지 않는다**(원칙 3).

#### 3-3. 느린 뷰어 fixture

수신 후 sleep하는 클라이언트. **drop-old를 실제로 발동시키는 유일한 수단**이다(loopback에서는 큐가 안 찬다).

**DoD**

- **3-1** fixture가 보낸 AU 수와 서버가 받은 AU 수가 **같다**(느린 뷰어 없이).
- **3-2** fixture가 부여한 `frame_ref`가 뷰어 도착분과 **바이트 동일**하다 — 서버가 재생성하지 않았다.
- **3-3** 느린 뷰어를 붙이면 **드롭이 실제로 발생**하고, **드롭 직후 첫 전송이 keyframe**이다.

---

### 단계 4. 서버 안 관통 + pytest 회귀

**이 단계에서 회귀를 못 박는다.** 매 세션 재현되는 테스트가 있어야 Phase 5 이후가 그 위에 선다.

| 테스트 파일 | 무엇 | 인프라 |
|---|---|---|
| `tests/test_media_frame.py` | 방식 B 프레이밍 왕복 · 헤더 검증(양성/음성) · 헤더 길이 상한 · 순번 역전 기록 | 없음 |
| `tests/test_media_dropold.py` | 상태 기계 전이 전수 · `T_drop`/`T_hard` 계산 · JPEG가 같은 코드로 도는지 | 없음 |
| `tests/test_media_relay.py` | 실제 소켓: 송신 fixture → 서버 → 뷰어 도착 · 토큰 · frame_ref 관통 · 느린 뷰어 드롭 | 상주 3개 + **8766 도달** |
| `tests/test_contract_media.py` | `media-header`·`detections` 규격 fixture(양성/음성) | 없음 |

⚠ **단계 4의 판정은 전부 pytest의 WS 클라이언트로 한다. 서버에 브라우저가 없다.** `console.html`(브라우저 확인)은 **단계 7에서 컴퓨터 브라우저로** 연다. 여기서 브라우저를 띄우려 하지 않는다.

🔴 **`test_media_relay.py`에 `ingest_url` skip fixture를 붙인다 — 단계 8과의 모순을 여기서 푼다.**
단계 8이 8766을 닫는데(DoD 8-1) DoD 8-4는 *"되돌린 뒤 pytest 전건 통과"*를 요구한다. **`conftest.py`의 기존 패턴이 그대로 답이다** — `prometheus_url`·`loki_url`·`tempo_url`이 헬스 엔드포인트를 때려 보고 실패하면 **그 테스트만 skip**한다(`conftest.py:164-190`). 같은 모양으로 **8766 도달 실패 시 `test_media_relay.py`만 skip**한다.
⚠ **pytest 안에서 게이트웨이를 임시 포트로 띄우지 않는다.** 기존 테스트 중 서버를 직접 띄우는 것이 **하나도 없고**(전수 확인), `ws_echo.serve()`는 **Kafka 소비 스레드를 함께 띄우고 `loop.add_signal_handler`로 SIGTERM을 건다** — 테스트 안에서 띄우면 컨슈머 그룹 오프셋 오염과 시그널 핸들러 충돌이 따라온다.

**음성 대조(반드시 포함)**

| # | 무엇을 막는가 | 판정 |
|---|---|---|
| M1 | **토큰 없는 접속** | 4401 + 프레임 0장 |
| M2 | **헤더 필수 누락·타입 오류** | 거부 + `be_gateway_media_rejected{stage}` 증가 + 뷰어에 안 나감 |
| M3 | **드롭이 GOP 경계에서만** | 느린 뷰어에서 드롭 발생 후 **첫 전송이 keyframe** |
| M4 | **미디어 WS가 죽어도 상태·명령 채널이 계속 돈다** | `/media`를 끊어도 `/state`가 Kafka 메시지를 계속 받는다 |
| M5 | **모르는 `encoding`을 거부하지 않는다** | `"av1"` 헤더가 통과한다(enum이 아님) |
| M6 | **서버가 frame_ref를 재생성하지 않는다** | 송신 원본과 도착분 바이트 동일 |
| M7 | **영상이 상태를 밀지 않는다**(§1-5-2 head-of-line) | **느린 뷰어가 `/media`에 붙어 드롭이 일어나는 동안**, 같은 프로세스의 `/state` 소켓이 받는 Kafka 메시지의 **도착 지연이 늘지 않는다.** 두 채널을 한 프로세스에 둔 대가를 여기서 갚는다 — 늘어나면 writer 태스크 분리가 안 된 것이다 |
| **M8** | **JPEG에서도 지연 바운드가 같은 기준으로 잡힌다** | 느린 뷰어 + **JPEG 프로파일**에서 큐 바이트 최대치가 **`T_drop` 근처**에 머문다(`4×T_drop`이 아니다). 2-3의 「GOP 없는 스트림에는 `T_hard`를 적용하지 않는다」가 실제로 도는지 보는 유일한 대조 |
| **M9** | **모르는 `encoding`·헤더 과대 프레임이 연결을 끊지 않는다** | `max_size`를 넘는 프레임이 와도 **close 1009가 아니라 프레임만 버려지고 기록**된다. 엣지 연결은 살아 있다 |

**DoD**

- **4-1** 서버에서 **기준선 N(단계 0-5) + 신규 전건 통과, skip 0**. ⚠ **"184"를 그대로 쓰지 않는다**(제약 24).
- **4-2** 음성 대조 **M1~M9**가 **전부 실제로 거부·유지**된다. ⚠ M7(영상이 상태를 밀지 않는다)·M8(JPEG `T_hard`)·M9(과대 프레임이 연결을 안 끊는다)는 2-3·2-4의 🔴 규칙을 보는 **유일한** 대조다.
- **4-3** 관측 평면으로 판정한다 — 발행 전후 `be_gateway_media_frames{outcome="sent"}` **차분 증가**, 멈추면 더 안 는다(`infra/README.md` §4 「흐른다」 방식, counter는 `rate()` 규칙).
- **4-4** 컴퓨터에서 단위 파일만 돌려도 통과한다(인프라 필요분만 skip).

---

### 단계 5. Phase 3 이월 ③ 묶음 + 관측 확장

**Collector·Prometheus 재생성이 따라오므로 묶어서 한 번에 한다.**

#### 5-1. Collector 설정

1. **Tailscale 바인딩 되살리기** — compose의 주석 한 줄(`# - "<서버 tailscale IP>:4316:4317"`)을 되살린다. **제약 15·16·17을 먼저 확인**한다.
2. **ufw** — `allow from <엣지 tailscale IP>/32 to any port 4316 proto tcp`. **`Anywhere` 금지**(이 수신단에는 인증이 없다).
3. **OTLP 토큰(결정 7)** — ⏭ **이번에는 (i)로 간다. 확장 조사를 하지 않는다.** 터널 + ufw `/32` + 평문 = Phase 3과 같은 수준이며, 엣지는 임시이고 단계 8에서 되돌린다. 근거: receiver가 `otlp/grpc` 하나뿐이라 auth를 걸면 **loopback으로 붙는 백엔드 3개도 토큰을 보내야 하고**, 나누려면 receiver 신설 = 범위 확대다. **인증은 BE-Q-04와 함께 Phase 6**이며 추적표 BE-T-08에 한 줄로 남긴다.
4. **OTLP/HTTP 4318(결정 7 A)** — ⚠ **포트 한 줄이 아니라 receiver 신설이다.** 현재 `otel-collector-config.yaml`의 receiver에는 **`grpc:` 블록 하나뿐이고 `http:` 블록이 아예 없다**(주석이 *"gRPC만 연다"*로 못 박고 있다). 그래서 최소 네 곳이 바뀐다 — ① `receivers.otlp.protocols.http` 신설(`endpoint: "0.0.0.0:4318"`) ② `cors.allowed_origins` ③ compose `"<서버 tailscale IP>:4318:4318"` ④ ufw **VZ PC `/32`**. 컨테이너 재생성이 따라온다.
   ⚠ **`allowed_headers`도 필요할 수 있다** — 브라우저 OTLP/HTTP는 `Content-Type: application/x-protobuf`(또는 `application/json`)로 preflight를 보내고, Collector CORS 기본값이 그것을 허용하지 않으면 preflight에서 막힌다.
   🔴 **이번 Phase에서는 「준비」도 하지 않고 통째로 보류한다.** `allowed_origins`(VZ 회신 대기)와 **VZ PC의 tailnet 주소**(아무도 모른다 — 부록 B 10번에서 묻는다) 둘 다 없어 **포트를 열 수 없고**, 설정 파일을 반쯤 고쳐 두면 나중에 열 때 `validate`와 재생성을 어차피 다시 해야 한다. **결정 7 A(방향)는 유지하고, 구현 시점은 「VZ 답 이후」로 미룬다.** 단계 9 통지에서 두 값을 묻는 것까지가 이번 몫이다.
   ⚠ **브라우저는 tailnet 「밖」이 아니다.** VZ 코드 주석이 *"관제 웹(노트북)·로봇(pi7)·탐지(데스크톱)가 전부 테일넷으로 붙는다"*이고 기본 주소도 MagicDNS 이름이다 — 그래서 결정 7 A(Tailscale IP에만 바인딩)가 **성립한다.** 우리 통지 §4와 대조 보고서의 *"브라우저는 tailnet 밖"* 서술이 틀렸다. 다만 **「성립한다」(설계)와 「된다」(실측)는 다르다** — VZ가 우리 서버에 tailnet으로 붙어 본 실적은 0이다.
5. **모든 Collector 설정 변경 전 `validate`(exit=0)로 판정한다.** 컴포넌트 유무는 `components` 목록이 아니라 `validate`로 본다(정식명+별칭 쌍 4개를 빠뜨린다).

#### 5-2. Prometheus

6. **`edge_federate` 잡 되살리기** — 주석 해제 + `targets`를 **임시 엣지 주소**로. `honor_labels: true`·`scrape_interval: 15s`·`match[]` 두 줄은 **그대로 둔다**(`up`·생사·치명 오류를 넣지 않는다 — 원칙 6).
7. **이미지 digest 고정** — `prom/prometheus:latest` → digest. **컨테이너 재생성이 따라온다**(보존은 CLI 기본 15d에 기대고 있고 이번에 바꾸지 않는다).
   ✅ **데이터는 살아남는다** — compose에 `./prometheus_data:/prometheus` bind mount와 `--storage.tsdb.path=/prometheus`가 있다(실물 확인). 재생성으로 시계열이 날아가지 않는다. **다른 파트의 대시보드 데이터가 여기 있으므로**(분류 ③) 이 사실을 확인하지 않고 재생성하지 않는다.
   ⚠ digest는 **지금 도는 이미지의 것**을 읽어 박는다: `docker inspect capstone_prometheus --format '{{index .RepoDigests 0}}'`. 최신 `:latest`를 새로 당겨오지 않는다 — 그러면 "고정"이 아니라 "갱신"이 된다.
8. ⚠ **global을 건드리지 않는다.** `scrape_timeout > scrape_interval`인 잡이 하나라도 있으면 설정 전체가 거부된다(`rpi`·`thermal`). `promtool check config`로 먼저 판정한다.

#### 5-3. 코드

9. **`LoggingHandler` 교체** — `opentelemetry-instrumentation-logging`의 핸들러로. `pyproject.toml`에 의존성 추가. **API가 다를 수 있으므로 실측으로 판정**한다(pytest 경고 2건이 사라지는지).
10. **라벨 금지 9종 확장** — `backend/observability.py`의 `FORBIDDEN_LABELS` + `tests/test_observability_labels.py` + `contracts/common/README.md`(단계 1-4)를 **함께** 고친다.
    - 9종: `mission_id`·`node_ref`·`client_request_id`·`plan_id`·`event_key`·발화 원문 + **`frame_ref`** + **`correlation_id`** + **`command_id`**.
    - ⚠ **「발화 원문」은 필드 이름이 아니다.** `FORBIDDEN_LABELS`는 **문자열 리터럴 집합**이라 실제 키 이름이 있어야 넣을 수 있다. **부록 B 10⑤에서 VZ에 그 키 이름을 묻고**, 답이 오기 전에는 **나머지 8종만 넣는다**(빠뜨린 것이 아니라 대기임을 보고서에 적는다).
    - ⚠ **셋이 v1에 없었다.** 우리가 VZ에 보낸 통지가 이미 *"막는다"*고 적은 것들이라(§2 금지 라벨 표) **통지와 코드가 어긋난 상태**다. 지시서 §2-5도 *"`frame_ref`를 넣으면 어댑터가 `ValueError`로 막는다"*고 썼는데 **지금은 막지 않는다** — 없는 방어를 근거로 쓰지 않는다.
    - ⚠ **`node_id`는 넣지 않는다**(제약·근거는 단계 1-4).
    - 🔴 **이 변경이 pytest 수집 수를 늘린다.** `tests/test_observability_labels.py:41`이 `sorted(obs.FORBIDDEN_LABELS)`를 `parametrize` 인자로 쓴다 — **8종을 더하면 184 → 192, 발화 원문까지 9종이면 193**이 된다. DoD에 그 증가분을 명시한다(제약 24).

**DoD**

- **5-1** `ss`로 4316이 **loopback + Tailscale IP 둘 다** LISTEN. ufw에 **엣지 IP `/32`** 규칙만(Anywhere 없음).
- **5-2** Collector `validate exit=0`, 기동 로그에 `Everything is ready`, `.Config.Image`가 digest.
- **5-3** `edge_federate` 잡이 `up`이고 15s(단계 7에서 임시 엣지로 확인).
- **5-4** Prometheus `.Config.Image`가 digest, **기존 타깃 5개가 그대로이고 `edge_federate` 1개가 더해져 6개**, global **무변경**(값을 바꾸지 않았다는 뜻 — `scrape_timeout > scrape_interval` 잡이 있어 global을 건드리면 설정 전체가 거부된다).
  ⚠ **digest 미고정이 Prometheus 하나가 아니다** — compose에서 `grafana`·`loki`·`tempo`·`mongo`·pushgateway 2개도 `:latest`다. **이번에 Prometheus만 고정하고, 나머지 목록을 `infra/README.md` §6에 「digest 미고정 잔여」로 기록**한다(규율 8 — 다음 Phase가 알아야 한다).
- **5-5** pytest 경고 2건이 **사라졌다**. **N + 8(라벨 증가분) + 신규** 전건 통과.
- **5-6** 금지 라벨 테스트가 **추가분을 실제로 거부**한다 — **`frame_ref`·`correlation_id`·`command_id`가 실제로 `ValueError`로 막히는 것**까지 확인한다. `node_id`는 **허용**되는 것까지 음성 대조.
- **5-7b** 4318은 **손대지 않았다**(설정·compose에 변경 0). 대신 부록 B 10번에 **CORS origin과 VZ PC tailnet 주소 문의**가 들어갔다.
- **5-7** **Collector·Prometheus 말고 다른 11개 컨테이너가 재생성되지 않았다**(매 단계 `docker compose ps`로 `Up <기간>` 확인). ⚠ **`docker compose down`을 치지 않는다**(제약 29 — 브리지 대역 미고정).
- **5-8** 관측 기준선 — **`be_*` 28종 → 35종**(A층 11 → **18**. 미디어 계기 5개 중 `media_coldstart`가 히스토그램이라 `_bucket`·`_sum`·`_count` 셋을 만든다. C층 17 무변경)이고 **Loki 라벨은 3종 그대로**다(늘면 금지 라벨이 샌 것이므로 멈춘다). ⚠ 조회에 `start`·`end` 필수(제약 31). ⚠ `host.docker.internal:8000` 타깃은 09-18에도 `down`이었으므로 **"타깃 전부 up"을 판정 기준으로 쓰지 않는다.**

---

### 단계 6. Kafka EDGE 리스너 (결정 6 ㉯)

**PLAINTEXT `localhost:9092`를 한 줄도 바꾸지 않는다.** 엣지용 리스너를 하나 더 둔다.

```
KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093,INTERNAL://0.0.0.0:9094,EDGE://0.0.0.0:9095
KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092,INTERNAL://kafka:9094,EDGE://<서버 tailscale IP>:9095
KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT,INTERNAL:PLAINTEXT,EDGE:PLAINTEXT
ports:  - "<서버 tailscale IP>:9095:9095"
```

⚠ **두 곳의 `0.0.0.0`은 뜻이 다르다.** `KAFKA_LISTENERS`의 `EDGE://0.0.0.0:9095`는 **컨테이너 안에서 듣는 주소**라 그대로 맞다. 금지되는 것은 **`ports:`의 `0.0.0.0`**(= 호스트 노출 주소)이다.
⚠ **`ADVERTISED_LISTENERS`의 `EDGE://`에 반드시 `<서버 tailscale IP>`를 넣는다.** `localhost`로 두면 엣지가 접속은 되는데 브로커가 *"localhost로 오라"*고 답해 **엣지가 자기 자신에게 되돌아간다**(Phase 0 미결이 Phase 1까지 끌었던 바로 그 함정).
⚠ **`SECURITY_PROTOCOL_MAP`에 `EDGE:PLAINTEXT`를 빠뜨리면 브로커가 기동에 실패한다.**
⚠ **`INTER_BROKER_LISTENER_NAME`은 `INTERNAL` 그대로 둔다.**
⚠ 제약 15(없는 IP 바인딩) — `tailscale ip -4` 확인 뒤에 `up -d kafka`.
**결정 6 β — 이번에 하는 것은 한 줄뿐이다.**

- 🔴 **`ports`에 `0.0.0.0`을 쓰지 않는다. `"<서버 tailscale IP>:9095:9095"`로 적는다.** 이것이 실질 통제다 — DNAT 규칙에 `-d <서버 tailscale IP>/32`가 붙어 **tailnet 밖(공인 IP·LAN 인터페이스)에서는 매치되지 않는다.** `9095:9095`로만 적으면 `0.0.0.0`이 되어 **인증 없는 Kafka가 서버의 모든 인터페이스에 열린다.** 작업량 차이는 **문자열 하나**다.
- **ufw 규칙도 적는다** — `allow from <엣지 tailscale IP>/32 to any port 9095 proto tcp`. 다만 도커 발행 포트에 대해서는 **통제가 아니다**(제약 16). **장애 원인 배제·문서용**이며, 보고서·추적표 **BE-T-08**에 그렇게 적는다. 없는 통제를 있다고 적지 않는다.
- **SASL은 BE-Q-04와 함께 Phase 6.** 바뀌지 않는다.

> ⏭ **다음으로 미룬다 — `DOCKER-USER` 규칙.** tailnet **안**의 나머지 기기까지 막으려면 `iptables -I DOCKER-USER 1 -p tcp --dport 9095 ! -s <엣지 tailscale IP>/32 -j DROP` 한 줄과 그것을 부팅마다 다시 넣을 oneshot 유닛이 필요하다(체인이 비어 있고 `DOCKER-FORWARD`보다 먼저라 기술적으로는 된다 — 단 k3s가 `FORWARD`를 동적 관리하므로 `iptables-save` 전체 덤프는 쓰지 않는다). **이번 Phase의 엣지는 임시이고 단계 8에서 9095를 통째로 닫으므로 하지 않는다.** 실 엣지 장비가 상시로 붙을 때 한다 — `infra/README.md` §5와 추적표 **BE-T-08**에 **한 줄로만** 남긴다.

#### 6-b. compose 주석 두 곳을 같은 작업에서 고친다

단계 6이 편집할 **바로 그 블록**이다. 고치지 않으면 다음 사람이 이 주석을 근거로 정반대 판단을 한다.

| 위치 | 현재 | 무엇이 문제인가 | 어떻게 고치나 |
|---|---|---|---|
| `docker-compose.yml:229-233` | *"INTERNAL `:9094` … → **Phase 1의 브릿지·WS 게이트웨이가 여기로 붙는다**"* | 🔴 **사실과 반대다.** 백엔드 3개는 호스트 프로세스라 전부 `settings.kafka_bootstrap()` = **`localhost:9092`(PLAINTEXT)**로 붙고 **INTERNAL을 쓰는 클라이언트는 0개**다(`bridge.py:81`·`consumer.py:111`·`ws_echo.py:49`). `infra/README.md:484-489`와 plan이 이미 정확히 적고 있는데 **여기만 반대로 남았다** | 233행을 *"→ **쓰는 클라이언트가 현재 없다.** 백엔드 3개는 호스트 프로세스라 PLAINTEXT `localhost:9092`로 붙는다"*로 |
| `docker-compose.yml:213-216` | *"Docker의 포트 publish는 UFW 규칙을 우회한다 … 0.0.0.0으로 열면 방화벽에 허용 규칙이 없어도 인터넷에서 접근된다"* | 🟡 **지우면 안 된다.** `infra/README.md` §5가 *"실측이 이 서술을 반증했다"*고 적었으나, 그 9100 실측은 **Prometheus 컨테이너 → `host.docker.internal:9100`**(브리지로 들어와 DNAT를 안 타고 `INPUT`으로 가는 경로)이고, 이 주석은 **외부 기기 → 발행 포트**(DNAT 후 `FORWARD`) 경로를 말한다. **두 문장은 서로 다른 경로이며 어느 쪽도 반증되지 않았다** | 주석을 **두 경로로 갈라 적는다** — *"컨테이너·호스트에서 오는 트래픽은 `INPUT`을 타므로 ufw가 적용된다(9100 실측). 외부 기기에서 오는 트래픽은 DNAT 후 `FORWARD`를 타므로 ufw `INPUT`을 타지 않는다. 그래서 바인딩(노출 통제)과 ufw(장애 원인 배제)를 둘 다 한다."* 그리고 **`infra/README.md` §5 정정 박스의 「반증했다」도 같은 문장으로 고친다**(§8 갱신 대상) |

> ⚠ **`infra/docker-compose.yml`은 gitignore이고 git에 추적된 적이 없다.** 이 주석 수정은 **커밋되지 않는다** — 그래서 같은 내용을 **커밋되는 `infra/README.md`에 반드시 옮겨 적는다**(§5 정정 박스 + §6). 이것이 §5 머리말이 *"서버 compose 파일의 주석은 gitignore라 저장소에 남지 않으므로 커밋되는 이 문서에 적는다"*고 한 이유다.

**작업 순서(터미널 분리)**

- 터미널 1(서버): compose 백업(`docker-compose.yml.bak_before_phase4_kafka`) → 편집 → `docker compose up -d kafka`
- 터미널 2(서버): `docker compose ps kafka` · `journalctl`/`docker logs`로 기동 확인
- 터미널 3(서버): 백엔드 3개 상태 확인(`systemctl is-active …`)

⚠ **재생성 중 백엔드 3개가 Kafka 연결 오류를 로그에 남기는 것은 정상이다.** librdkafka가 재연결하고 소비자는 리밸런스한다. **프로세스는 죽지 않으므로** `Restart=on-failure`가 발동하지 않는다(그건 종료 시에만). **죽으면** 그때 멈추고 보고한다 — 그건 다른 문제다.

**되돌리기(실패 시)** — `docker-compose.yml.bak_before_phase4_kafka` 복원 → **상주 3개 `stop`**(재생성 중 Kafka를 잃으면 `StartLimitBurst 3/60s`에 걸려 `failed`로 멈춘다) → `docker compose up -d kafka` → 3개 `start` → 판정 셋(브로커가 `localhost:9092`로 답하는지 · 그룹 `describe`에 `CONSUMER-ID` 재할당 · TSDB 행 증가). `kafka_data`는 bind mount라 토픽·오프셋이 유지된다.

**DoD**

- **6-1** `kafka-broker-api-versions.sh --bootstrap-server localhost:9092`가 **여전히 `localhost:9092`로 답한다**(기존 경로 무변경).
- **6-2** 백엔드 3개가 **재기동 없이** 계속 돈다. `ss -tnp | grep 9092`에 셋 그대로.
- **6-3** **우리 토픽 3개(+`__consumer_offsets` = 4)**·그룹 오프셋이 그대로다.
- **6-4** `ss`에 **`<서버 tailscale IP>:9095` LISTEN**(`0.0.0.0`이 아니다) · ufw에 엣지 `/32` 규칙(문서용).

---

### 단계 7. 외부 노출 + 임시 엣지 2계층 실측 **1회**

> **여기서만 컴퓨터를 엣지로 쓴다.** Phase 3과 같은 방식이며 검증 후 되돌린다(단계 8).

#### 7-1. 서버 — 입구 셋을 Tailscale 인터페이스로

> **입구마다 무엇이 막는지가 다르다**(제약 16). **8765·8766은 호스트 파이썬**이라 `INPUT`으로 들어오므로 **ufw가 진짜 통제**이고, **9095·4316은 도커 발행 포트**라 **바인딩 주소가 통제**다.

| 입구 | 무엇이 막나 | 바인딩 | ufw |
|---|---|---|---|
| 8765(뷰어 `/state`·`/media`) | **ufw + 토큰** | **`127.0.0.1` + `<서버 tailscale IP>` 둘 다**(단계 2-4) | **`<사용자 컴퓨터 tailscale IP>/32`**. ⚠ **VZ PC 주소를 아무도 모른다 — 부록 B 10번에서 받는다. 받기 전에는 사용자 컴퓨터 `/32`만 연다** |
| 8766(엣지 `/ingest`) | **ufw + 토큰** | `<서버 tailscale IP>` | `<엣지 tailscale IP>/32` |
| **9095**(Kafka EDGE) | **바인딩** — ufw는 문서용 | `<서버 tailscale IP>` | 엣지 `/32` |
| 4316 | **바인딩** | 단계 5에서 이미 | 엣지 `/32` |

⚠ **8767(4b PUT 입구)은 여기 없다** — 단계 10에서 열리고 거기서 같은 방식(바인딩 `<서버 tailscale IP>` + ufw `pi7 /32` + 토큰)으로 연다. 순서를 앞당기지 않는다.

⚠ **8765를 Tailscale IP에 바인딩하면 `mk2-ws-echo`가 `tailscaled`에 의존한다.** 유닛에 **`After=tailscaled.service`·`Wants=tailscaled.service`**를 넣는다. 그래도 tailscaled가 늦으면 `StartLimitBurst`에 걸릴 수 있으므로 `RestartSec` 상향을 함께 검토하고, **재부팅 후 확인 절차(`systemctl --failed | grep mk2`)에 이 유닛을 포함**시킨다.

#### 7-2. 컴퓨터 — 임시 엣지

- **Windows 인바운드 방화벽은 `edge_federate`(서버→엣지 9090) 한 건만** 연다. 미디어·OTLP·Kafka는 **엣지→서버 outbound**라 인바운드가 필요 없다(결정 4-b — 엣지가 클라이언트로 붙는다).
- 엣지 Prometheus·Collector(Agent) 설정은 `_serverinfo/edge_probe_260916/`의 사본이 출발점이다(`agg_layer="edge"` external_labels, `match[]` 한정).
- 터미널을 나눈다:
  - **터미널 1(컴퓨터)** — 엣지 Prometheus
  - **터미널 2(컴퓨터)** — 엣지 Collector(Agent)
  - **터미널 3(컴퓨터)** — `tests/media_publisher.py`(방식 B 송신 → 서버 8766)
  - **터미널 4(컴퓨터)** — Kafka 왕복 확인(`confluent-kafka` 클라이언트 하나로 produce/consume 1회).
    ⚠ **컴퓨터 venv에 `confluent-kafka`가 없다** — Phase 1에 `paho-mqtt`·`protobuf`, Phase 3에 OTel SDK·`psutil`·`pytest`·`jsonschema`만 깔았다. **이 단계 전에 설치한다**(작업 폴더 venv, gitignore).
  - **터미널 5(서버)** — 조회·판정

#### 7-3. 실측 항목

| # | 무엇 | 판정 |
|---|---|---|
| 7-a | `tailscale ping <서버>` | `via <ip>:<port>`(직접) 또는 `via DERP`. **둘 다 허용**하되 값을 기록 |
| 7-b | **미디어 관통** | 컴퓨터 fixture → 서버 → 컴퓨터 브라우저 뷰어에 도착. AU 수·keyframe 수 일치, frame_ref 바이트 동일 |
| 7-c | **터널 위 drop-old** | 느린 뷰어에서 드롭이 GOP 경계에서만. `T_drop`이 **시간 기준**이라 링크가 느려져도 지연이 150ms 근처로 바운드되는지 기록 |
| 7-d | **Kafka 원격** | 컴퓨터 클라이언트가 `<서버 tailscale IP>:9095`로 **produce/consume 왕복 1회 성공** → **BE-T-02의 gap이 실제로 닫힌다** |
| 7-e | **OTLP 2계층** | 엣지 Agent의 log·trace가 서버 Collector를 거쳐 Loki·Tempo에 도달, `be-*`와 구분 |
| 7-f | **페더레이션** | `hw_*{agg_layer="edge"}`가 서버 Prometheus에 · **음성**: `go_*`·`up`·`system_filesystem`이 `agg_layer="edge"`로 **0건** |
| 7-g | **백엔드 경로 유지** | 바인딩 상태에서 발행 2건 → `be_ingest_received_total` 증가 |
| **7-h** | **9095가 tailnet 밖에서 안 보이는가 (기록 1회)** | 허용 목록에 없는 tailnet 기기 한 대에서 `nc -vz <서버 tailscale IP> 9095` **한 번** 돌리고 **결과를 그대로 적는다.** tailnet 안이므로 **연결되는 것이 정상**이다(tailnet 안까지 좁히는 `DOCKER-USER`는 미뤘다 — 단계 6). **판정이 아니라 기록**이며, 이 값이 추적표 **BE-T-08**의 「현재 통제 수준」 근거가 된다. 단계 8에서 9095를 닫으면 해소된다 |
| **7-i** | **8765가 두 주소에 뜬다** | `ss -tlnp`에 8765가 `127.0.0.1`과 `<서버 tailscale IP>` **둘 다** LISTEN. 서버에서 pytest가, 컴퓨터 브라우저가 **동시에** 붙는다 |

**DoD**

- **7-1** 7-a~7-i **전부 확인**되고 값이 `_serverinfo/`에 기록됐다(커밋 금지).
- **7-1b** 추적표 **BE-T-08**에 현재 통제 수준을 그대로 적었다 — *"9095는 `<서버 tailscale IP>` 바인딩으로 tailnet 밖은 막히고, tailnet 안에서는 열려 있다. 좁히려면 `DOCKER-USER` 한 줄이 필요하며 실 엣지 장비 상시 연결 시 한다. SASL은 Phase 6."* **없는 통제를 있다고 적지 않는다.**
  🔴 **`nc`가 tailnet 밖(공인 IP)에서도 연결되면 그때는 멈추고 보고한다** — 바인딩이 안 먹은 것이고, 그건 이번 Phase가 만든 문제다.
- **7-2** 검증 중 **다른 컨테이너가 재생성되지 않았다.**
- **7-3** pytest **N + 라벨 증가분 + 신규**가 **여전히 전건 통과**한다. ⚠ **8765를 Tailscale IP 하나로만 옮기면 여기서 깨진다** — 7-i(두 주소 LISTEN)가 선행 조건이다.

---

### 단계 8. 되돌림 — 남기는 것과 되돌리는 것

| | 항목 |
|---|---|
| **남긴다** | **8765 뷰어 입구**(**loopback + Tailscale 둘 다 바인딩** · ufw **사용자 컴퓨터 `/32`**, VZ PC는 주소를 받으면 추가 · 토큰) — VZ가 Phase 4 뒤에도 붙어야 한다(결정 5·VZ-C-07) · `mk2-ws-echo`의 `After=tailscaled.service` · 단계 1·2·3·4의 규격·코드·테스트 · 단계 5의 코드 변경(`LoggingHandler`·**라벨 8종**(+「발화 원문」 1종은 VZ 회신 뒤)) · 단계 6-b의 compose 주석 수정과 그 내용을 옮긴 `infra/README.md` |
| **되돌린다** | **8766 엣지 입구**(`MK2_MEDIA_INGEST_PORT=0`) · ufw 엣지 `/32`(8766·4316·9095) · **Collector 4316 Tailscale 바인딩**(주석으로) · **`edge_federate` 잡**(주석으로, 타깃은 다음에 교체할 수 있게 남긴다) · **Kafka `EDGE` 3줄 + `ports` 줄**(주석으로) · Windows 9090 인바운드 규칙 삭제 · 컴퓨터의 엣지 폴더(설정 사본은 `_serverinfo/`에 보관) |

⚠ **4318(브라우저 관측 입구)은 이번에 아예 손대지 않았으므로 되돌릴 것도 남길 것도 없다**(단계 5-1 #4). 결정 7 A의 방향만 문서에 남고, 구현은 VZ가 CORS origin과 tailnet 주소를 회신한 뒤다.
⚠ **8767(4b PUT 입구)은 이 단계 시점에 아직 없다.** 단계 10에서 열리고 **그대로 남는다**(되돌리지 않는다). 순서를 헷갈리지 않는다.

**DoD**

- **8-1** `ss`에 8766·`<서버 tailscale IP>:4316`·9095가 **없다**. 8765는 **있다**.
- **8-2** ufw에 엣지 `/32` 규칙이 **없고**, 뷰어 `/32` 규칙은 **있다**.
- **8-3** compose에 Kafka `EDGE`·Collector Tailscale 줄이 **주석**으로 남아 있다(지우지 않는다 — 실 엣지가 오면 주소만 바꾼다).
- **8-4** 되돌린 뒤 **pytest 전건 통과**, 상주 3개 `active`. ⚠ **여기서는 `skip 0`을 요구하지 않는다** — 8766이 닫혀 `test_media_relay.py`는 `ingest_url` fixture로 **skip되는 것이 정상**이다(단계 4). 그 외 skip은 허용하지 않는다.
- **8-6** **8765는 여전히 `127.0.0.1` + `<서버 tailscale IP>` 둘 다** LISTEN이고, 서버 pytest가 loopback으로 붙는다.
- **8-5** 컴퓨터에 엣지 흔적이 없다(`Test-Path` False, 방화벽 규칙 없음).

---

### 단계 9. 회신·통지 문서

**세 건이다**(v1은 둘이었다). 규율은 정착된 것을 따른다 — 머리말 표(보내는 쪽/받는 쪽/작성일/근거/대상 안건/우선순위) · 모든 주장에 근거(`파일:줄` 또는 요구사항 ID) · 각 물음에 **「우리는 이렇게 읽었다」**와 **「답이 없으면 이 기본값으로 간다」** · 상대 코드 변경 요청은 **before/after** · 우선순위 표시 · 끝에 **「상대가 할 일」** 요약.

- **HW 회신** = `docs/be/hw-envelope-conformance.md`에 **§8로 이어 붙인다**(새 파일을 만들지 않는다 — §5-1 단일 목록을 유지하는 것이 이번에 빠짐없이 회신할 수 있었던 이유다). 골격은 **부록 A**. ⚠ 절 제목에 출처를 박는다(제약 28).
- **VZ 통지** = `docs/be/vz-media-interface.md` **신설**. 골격은 **부록 B**. 기존 두 문서(`vz-mission-record-inquiry.md`·`vz-observability-namespace.md`)와 **겹치지 않게** 하고, 관측 회신에 대한 답은 **새 문서를 만들지 말고 이 통지 안의 한 절**로 넣는다.
- 🔴 **AI 통지 신설** = `docs/be/ai-detections-interface.md`. 골격은 **부록 D**. **v1에 없었다** — 단계 1이 `detections.schema.json`을 신설하는데 **그 규격의 생산자가 AI이고**, 소비자(VZ)에게만 통지하고 생산자에게는 하지 않는 구조였다. plan §4의 *"진나영 Phase 4 — 남은 문의 1건: 자율주행 편 영상이 우리 서버 7864에 닿는 경로"*도 여기서 닫는다.

🔴 **순서를 못 박는다 — §8 갱신(02-media-path 등)이 끝난 뒤에 회신이 나간다.** 부록 A 8-3·8-6이 *"02-media-path를 정정했다"*고 말하는데, **그 수정이 실제로 커밋돼 있지 않으면 조병현 씨가 문서를 열어 보는 순간 드러난다.** (v1은 그 수정이 어느 커밋에도 없는 상태에서 과거형으로 적혀 있었다 — `git log -- docs/be/02-media-path.md`로 확인된 사실이다.)

⚠ **세 문서 모두 커밋된다. 주소는 자리표시자, 토큰은 본문에 적지 않고 "별도 경로로 전달"로 쓴다.**

**DoD**

- **9-1** HW 회신 §8이 **§8·§10-4·§10-5·§10-6·§10-7 + #14~#18 + 인식 안내 + 우리가 요청하는 것**을 빠짐없이 담았다.
- **9-2** `hw-envelope-conformance.md` **§5-1 표**에서 회신한 안건이 §5-0(처리 완료)으로 옮겨졌다(§5-0은 실재하며 이동 표기 선례도 있다).
  🔴 **같은 작업에서 §5-0·§5-1 표의 안건 이름에 출처를 박는다.** 지금 표는 `§8`·`§3`·`§10-3`처럼 **HW `BACKEND_AGENDA`의 절 번호를 맨몸으로** 쓰는데, 우리 문서에 `§8`을 새로 만드는 순간 **표의 「§8」이 자기 문서 §8로 오독된다.** `BACKEND_AGENDA §8`처럼 출처를 붙인다(제약 28은 절 **제목**만 다뤘다).
- **9-3** VZ 통지가 **부록 B의 13항목 + 「—」 요약행**을 담았고 「관측 회신에 대한 답」 절이 들어 있다. ⚠ **10~13번(VZ tailnet 주소·CORS origin 문의 · 관측 통지 §4 정정 · `target_entity_id`↔`source_id` · `origin.kind`↔`origin_kind`)을 빠뜨리지 않는다** — 단계 5-1·5-3·7-1이 10번의 답에 걸려 있다.
- **9-4** 세 문서에 **실주소·토큰·비밀값이 없다**(`git check-ignore`와 눈으로 확인). ⚠ **반대 방향도 본다** — 새 파일이 `.gitignore`의 `*token*`·`*secret*`에 걸려 **조용히 빠지지 않았는지** `git status`로 확인한다(제약 25).
- **9-5** **AI 통지가 나갔고**, plan §4의 진나영 행 「7864 문의 1건」이 그 문서로 연결됐다.
- **9-6** ⚠ **§8 문서 갱신이 회신보다 먼저 끝났다** — `git log`로 `02-media-path.md` 커밋이 회신 문서 커밋보다 앞서는지 확인한다.

---

### 단계 10. (4b) 촬영본 저장소 — 마지막 독립 단계

> **이 단계는 앞 단계들과 코드를 공유하지 않는다.** 앞이 막혀도 여기만 따로 진행할 수 있고, 반대로 여기가 막혀도 Phase 4 본체는 완료로 판정한다.
>
> ✅ **별도 지시서로 떼지 않는다 (2026-09-18 확정).** 2026-09-18 합본이 한 번 분리를 권했으나 **철회했다.** 근거:
> - **HW 답을 기다릴 이유가 없다.** HW #15는 **HW가 먼저 "목적지를 알려 달라"고 물은 것**이고(`hw-envelope-conformance.md` §5-1), 우리가 저장소를 만들어야 그 답이 나간다. **저장소가 선행이지 HW가 선행이 아니다.**
> - **HW 쪽 네 건(URL `entity_id` · `started_at` 오프셋 · 매니페스트 전송 방식 · `correlation_id`)은 전부 우리 쪽에서 방어된다** — 저장 경로는 매니페스트가 정하고(10-1), `started_at`은 오프셋이 없으면 `NULL` + `t0_unix`로 채우고(10-2), 매니페스트 전송 방식은 **우리가 정해 통보하는 것**이며, `correlation_id`는 선택 필드다. **HW가 고치기 전에도 합성 업로더로 기본값 검증이 끝난다.**
> - 실측은 어차피 그 뒤이고, 실측하면 어디든 고친다. **먼저 만들고 회신하는 것이 순서다.**
>
> **사용자 결정 ㉡(2026-09-17)대로 이 지시서 안에서 끝낸다.**

#### 10-1. 수신단

- `backend/gateway/capture.py` **신설** — `PUT <base>/<파일명>`을 받는 작은 HTTP 수신단. 포트 **8767**, 토큰 `MK2_CAPTURE_TOKEN`(쿼리 또는 헤더), 바인딩은 `<서버 tailscale IP>`, ufw는 **pi7 `/32`**.
- ⚠ **HW `capture_upload.py:118-125`는 S3 API가 아니라 단순 HTTP PUT 한 방이다**(서명·presign 없음, `Content-Type: application/gzip`, 2xx면 성공). **S3 호환 저장소를 새로 들이지 않는다**(원칙 4).
- 🔴 **수신은 PUT 두 번이다**(10-2에서 v1을 바꿨다) — ① `PUT <base>/<session>.manifest.json`(수 KB) → 2xx → ② `PUT <base>/<session>.tar.gz`. **아카이브 안을 뒤지지 않는다.**
- 🔴 **URL의 파일명으로 최종 저장 위치를 정하지 않는다.** HW 업로더는 `url = base.rstrip("/") + "/" + os.path.basename(path)`이고 `path`가 `{세션디렉터리명}.tar.gz`라, **`entity_id`가 URL에 한 번도 실리지 않는다**(`capture_upload.py:120`). `session_id`는 `go1-001/20260910-134818`처럼 슬래시를 포함하지만 그 앞칸이 URL에 없어서, **로봇 2대가 같은 분에 세션을 시작하면 파일명이 같아 서로 덮어쓴다.**
  - **순서를 이렇게 한다: ① 아카이브를 임시 파일로 수신 → ② **앞서 받아 둔 매니페스트 PUT에서** `source_id`·`session_id` 확정(아카이브를 열지 않는다) → ③ `MK2_CAPTURE_DIR/<source_id>/<session 마지막 칸>.tar.gz`로 원자적 rename.** **최종 경로는 매니페스트가 정하고 URL은 정하지 않는다.**
  - 그 위치에 이미 파일이 있으면 **`session_id` UNIQUE 충돌과 같은 취급**(멱등, 10-3)으로 본다.
  - **경로 순회 방어의 대상이 URL이 아니라 매니페스트 값으로 옮겨간다** — `source_id`·`session_id`에서 `..`·`/`·`\`·절대경로·널바이트를 거부한다(`session_id`의 첫 슬래시 하나만 허용하고 나머지는 거부).
  - 부록 A 8-10에 **"업로드 URL에 `entity_id`를 포함시켜 달라"**를 요청으로 넣는다 — 있으면 수신 **전에** 판정할 수 있다.
- ⚠ **새 의존성을 들이지 않는다.** 표준 라이브러리 `http.server.ThreadingHTTPServer` + `BaseHTTPRequestHandler.do_PUT`으로 충분하다. **FastAPI·aiohttp 같은 웹 프레임워크를 추가하지 않는다**(`pyproject.toml` 11행 *"각 Phase에서 실제로 쓰는 것만 둔다"*).
- ⚠ **대용량 PUT은 블로킹이다.** WS 게이트웨이의 asyncio 루프에 올리지 않는다. 본문은 `Content-Length`만큼 **청크로 읽어 파일에 흘린다** — 메모리에 통째로 올리지 않는다(0.7GB/h짜리 아카이브다).
  🟠 **격리 수준: `capture.py`는 별도 systemd 유닛 `mk2-capture`로 둔다.** 같은 프로세스의 별도 스레드로 두면 업로드 쪽 예외·OOM이 **미디어 중계를 같이 넘어뜨린다.** 유닛 골격은 기존 3개와 동일하게 쓴다 — `[Unit] After/Wants=docker.service` · **`StartLimitBurst=3`·`StartLimitIntervalSec=60`은 반드시 `[Unit]`에**(v229 이후 `[Service]`에 두면 **경고와 함께 무시되어 재시작 루프가 안 끊긴다**) · `[Service] Type=simple`·`User=dg`·`EnvironmentFile=/home/dg/capstone-db/.env`·`Environment=PYTHONUNBUFFERED=1`·`Restart=on-failure`·`RestartSec=5`. **`Restart=always`를 쓰지 않는다**(설정 오류로 죽는 것을 무한 재시작하면 원인이 묻힌다). **§8 `CLAUDE.md`·`infra/README.md` 갱신 대상에 새 유닛을 넣는다.**
  ⚠ **`mk2-capture`는 단계 8의 되돌림 대상이 아니다**(입구를 남긴다 — 결정 9 ㄴ).
- **임시 파일 → fsync → 원자적 rename.** 중간에 끊기면 최종 위치에 불완전 파일이 남지 않는다.
- 저장 위치: `MK2_CAPTURE_DIR`(서버 기본 `/home/dg/capstone-db/media_capture`). ⚠ **`/`가 단일 볼륨이고 TSDB·MySQL·Loki·docker가 전부 같은 볼륨이다** — 차면 전부 멈춘다.

#### 10-2. 매니페스트 — 실물에서 나온 제약

**HW 업로더는 tar.gz만 PUT하고 `manifest.json`은 로컬에 남긴다.** 게다가 `json.dump`가 `pack()` **뒤**에 있어 아카이브 안에 들어가는 것은 *"그 시점 디렉터리에 있던 매니페스트"*다 — `go1_capture_teleop` 세션의 첫 실행이면 **아예 없고**, 재실행이면 **직전 실행 것**이며, `go1_scan_capture` 세션이면 촬영 도구가 쓴 것이 들어간다.

🔴 **v1의 규약을 바꾼다 — 아카이브 안을 뒤지지 않고 매니페스트를 먼저 따로 받는다.**

| v1 | v2 (확정) |
|---|---|
| 아카이브 안에 `*/manifest.json`이 있어야 한다. 없으면 거부 | **매니페스트를 별도 PUT으로 먼저 보낸다** — `PUT <base>/<session>.manifest.json`(수 KB) → 2xx → `PUT <base>/<session>.tar.gz` |

**이유 둘.**
1. `tarfile.add()`는 디렉터리를 `sorted(os.listdir())` 순서로 담는다. 파일명이 `frame_000001.jpg` … `manifest.json`이라 **매니페스트가 수만 장의 JPEG 뒤에 온다.** gzip은 seek이 안 되므로 **한 줄을 읽으려고 0.7GB를 통째로 압축 해제**해야 한다.
2. v1이 요청하려던 *"`json.dump`를 `pack()` 앞으로 옮기는 **한 줄** 순서 변경"*은 **정확하지 않다.** `man["frames"]["uri"]`가 **업로드 성공 뒤**에 채워지므로, dump를 앞으로만 옮기면 **HW 로컬 매니페스트에 업로드 주소가 영영 안 남는다.** 순서 변경으로 가더라도 **dump는 두 번**이어야 한다(아카이브용 한 번, `uri` 기록용 한 번).

- **우리 수신단은 매니페스트 PUT을 먼저 받아 파싱하고**, 그다음 오는 아카이브를 그 세션의 것으로 붙인다. 매니페스트 없이 아카이브만 오면 **거부한다**(부분 적재 금지 — 음성 대조 C2).
- 매니페스트 검증: `kind`·`session_id`·`source_id` 필수. **`kind`는 보존한다** — `capture_session`이 아닌 다른 종류(`scan_capture_session`)를 덮어쓰거나 거부하지 않는다.
  ⚠ HW 쪽 규율에 구멍이 하나 있다 — 매니페스트 JSON이 깨지면 `man = None`이 되어 **재생성**되고, 스캔 세션의 `shots[]` 방위 대응표가 소실된다. **인식 안내로 알린다**(부록 A 8-9).
- 🔴 **`started_at`을 그대로 `DATETIME(6)`에 넣을 수 없다.** 매니페스트의 값은 촬영 도구의 `time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(...))` — **오프셋도 밀리초도 없는 naive 로컬 시각**이고, HW 자신의 `pi/common/schema.py:55-59`가 못 박은 RFC3339 규칙(콜론 오프셋 + 밀리초)을 **촬영 경로만 위반**한다.
  - **서버가 시간대를 추측해 채우지 않는다**(없는 정보를 만들지 않는다). 오프셋이 없으면 **`started_at`은 `NULL`로 넣고 매니페스트 원본에는 원값을 보존**한다.
  - 대신 **`frames.t0_unix`(epoch)가 있으면 그것으로 `started_at`을 채운다** — 이쪽은 모호하지 않다.
  - 부록 A 8-10에 **오프셋을 붙여 달라**를 before/after로 요청한다.
- **채울 수 없는 칸을 미리 안다:** `archive_bytes`는 매니페스트에 없다(**서버가 수신하며 잰다**), `correlation_id`도 없다(**HW에 추가 요청**), `resolution`은 HW 제안 스키마엔 있고 구현엔 빠져 있다, `duration_s`는 fps·frames가 둘 다 있을 때만 채워진다. `node_id`·`zone_id`는 **있다**(`capture_upload.py:74-75`).
- 매니페스트 검증: `kind`·`session_id`·`source_id` 필수. **`kind`는 보존한다** — `capture_session`이 아닌 다른 종류(8방향 스캔)를 덮어쓰거나 거부하지 않는다(HW `capture_upload.py:144-155`의 규율과 같은 방향).
- **`frame_ref_base`는 채우지 않는다.** 오프라인 촬영본은 엣지를 거치지 않으므로 발급 주체가 없고, 서버가 채우면 **원칙 10 위반**이다. 프레임 시각은 `t0_unix + n × interval_s`로 복원한다(HW 설계 그대로). **결정 3의 `unaligned`와 같은 뜻이다.**
- **매니페스트에 선택 `correlation_id` 한 칸**을 더해 달라고 요청한다(어느 명령의 산출인지, 기본 `null` — *"모르는 값은 키를 지우지 않고 `null`"*이라는 HW 자신의 규칙과 같은 모양).

#### 10-3. 메타 저장

- **`mk2.media_capture` 테이블 신설**(기존 8개 중 성격이 맞는 것이 없다 — `audit_log`는 승인·명령, `mission_event`는 임무 사건).
- 칼럼: `session_id`(**UNIQUE**) · `source_id` · `node_id` · `zone_id` · `kind` · **`started_at DATETIME(6) NULL`** · `duration_s` · `frames_count` · `frames_bytes` · `archive_path` · `archive_bytes` · `manifest JSON`(원본 통째로) · `correlation_id` · `received_at DATETIME(6)` · **`purged_at DATETIME(6) NULL`**(10-4).
- **`COLLATE=utf8mb4_bin`**(제약 — 저장소 간 조회에서 `zoneA`≠`zonea`) · 시각은 **UTC를 담은 `DATETIME(6)`**(`TIMESTAMP` 금지).
- 권한: `mk2_app`에 **`SELECT, INSERT, UPDATE`**. **`DELETE`는 주지 않는다**(10-4). DDL은 **사람이 root로 1회**.
  🔴 **GRANT 문을 담을 파일이 v1의 새 파일 목록에 없었다.** MySQL GRANT에는 **테이블 와일드카드가 없어** `mk2_app`이 `media_capture`에 자동으로 권한을 얻지 못한다. 그리고 **없는 테이블에는 테이블 단위 GRANT를 걸 수 없으므로 순서가 강제된다** — **`infra/sql/mk2_media_capture.sql`(DDL) 적용 → 그다음 GRANT.** GRANT 문은 **같은 파일 끝에 넣고**, `infra/sql/mk2_grants_mysql.sql.example`에도 같은 줄을 더한다(적용본은 gitignore).
  - 🔴 **서버에 적용할 때의 경로는 `infra/sql/`이 아니라 `/home/dg/capstone-db/mk2_sql/`이다**(제약 30 — **폴더 이름이 다르다**). 저장소에 새 파일을 만들고, 서버 `mk2_sql/`로 **복사한 뒤** root로 1회 적용한다. 09-18 실측 기준 그 폴더에는 `mk2_mysql_schema.sql`·`mk2_tsdb_schema.sql`·`mk2_grants_{mysql,tsdb}.sql.example`·`registry-declared-vs-observed.sql` **5개**가 있다(저장소에는 4개 — **`registry-declared-vs-observed.sql`이 서버에만 있다**).
  - 계정 host는 기존과 같은 **`'mk2_app'@'172.18.%'`** — ✅ **09-18 실측으로 확인**(`@'%'`는 존재하지 않는다). 호스트 loopback 접속이 MySQL processlist에 `172.18.0.1`로 보이기 때문이고, Kafka 컨슈머 그룹의 `HOST`도 같은 `/172.18.0.1`이다. `@'localhost'`로 쓰면 붙지 못한다.
    ⚠ **이 값이 제약 29와 직결된다** — `docker compose down`으로 네트워크가 재생성되면 대역이 밀려 **이 GRANT가 조용히 무력해진다.**
  - `CREATE`·`ALTER`·`DROP`은 **어디에도 주지 않는다**(제약 27).
- **DDL 규약 4가지를 그대로 따른다**(`infra/sql/mk2_mysql_schema.sql:18-57`): ① 시각은 `DATETIME(6)`·UTC, 기본값은 `CURRENT_TIMESTAMP`가 아니라 **`UTC_TIMESTAMP(6)`** ② 테이블에 **`COLLATE=utf8mb4_bin`** 필수(빠뜨리면 조회에서 *Illegal mix of collations*로 터진다) ③ `CREATE TABLE IF NOT EXISTS` ④ **FK를 걸지 않는다**. 인덱스 명명은 `KEY idx_media_capture_<칼럼>` · 멱등 키는 `UNIQUE KEY uq_media_capture_session_id`.
- 🔴 **서버 설정 실측이 이 규약을 강제로 만든다**(09-18).
  - **`character_set_server=utf8mb4` / `collation_server=utf8mb4_0900_ai_ci`인데 `mission_event`는 `utf8mb4_bin`을 따로 명시하고 있다.** 즉 **서버 기본값과 테이블 값이 다르다** — `media_capture`에 `COLLATE`를 안 적으면 `_0900_ai_ci`가 되어 `zoneA`=`zonea`가 되고 조인에서 터진다. **테이블·칼럼 양쪽에 명시한다**(`mission_event`가 칼럼마다 `COLLATE utf8mb4_bin`을 적은 이유).
  - **`sql_mode`에 `STRICT_TRANS_TABLES`가 있다** — `varchar` 길이를 넘기면 **잘리는 게 아니라 INSERT가 실패한다.** `archive_path`처럼 길이를 예측하기 어려운 칸은 넉넉히 잡되, **UNIQUE·인덱스가 걸리는 칸은 `varchar(128)` 이하로 묶는다**(utf8mb4는 1문자 4바이트 → `varchar(255)`가 1020바이트. InnoDB DYNAMIC 인덱스 상한 3072바이트 안이긴 하나 `mission_event`가 그 계산을 주석으로 남겨 둔 이유가 이것이다).
  - **`NO_ZERO_DATE`가 있다** — `started_at`을 `'0000-00-00'`으로 채울 수 없다. **`NULL`로 두는 10-2의 결정이 이것과 맞는다.**
  - **`time_zone=SYSTEM`** — `TIMESTAMP` 타입은 세션 시간대 변환을 타므로 **쓰지 않는다.** `DATETIME(6)`에 UTC를 담고 칼럼 주석에 `UTC`라고 적는다(`mission_event`가 그렇게 한다).
  - **`explicit_defaults_for_timestamp=1`**·**`default_storage_engine=InnoDB`**·**MySQL 8.0.44** — 전부 `mission_event` DDL이 전제한 그대로다. **`mission_event`를 본보기로 삼는다**(`SHOW CREATE TABLE mk2.mission_event`).
- **파일 저장과 DB 삽입의 순서를 못 박는다** — **① 임시 수신 → ② 매니페스트 파싱·검증 → ③ DB `INSERT`(멱등) → ④ 원자적 rename.** DB가 실패하면 파일은 최종 위치에 놓이지 않고, rename이 실패하면 그 행을 롤백한다. **음성 대조 C2("파일만 놓이고 행이 없거나 그 반대가 되지 않는다")가 이 순서로만 참이 된다.**
- **재전송 멱등** — `session_id` UNIQUE + 중복 오류 1062만 골라 잡는다(`backend/storage/mission.py` 선례. `INSERT IGNORE`를 쓰지 않는 이유는 값 잘림 같은 다른 오류까지 삼키기 때문).

#### 10-4. 보존

- **`MK2_CAPTURE_MAX_BYTES` 기본 100GB.** 근거: 0.7GB/h × 약 143시간. `/`에 2.5T 여유가 있으나 **공용 단일 볼륨**이라 전체의 4%로 묶는다.
- 초과 시 **오래된 세션부터** 고른다. **이번 Phase에서는 실제 삭제를 하지 않고 `--dry-run`으로 선정만 확인**한다.
- 🔴 **행은 지우지 않는다 — 아카이브만 지우고 그 사실을 칼럼으로 남긴다.**
  **왜:** 우리가 VZ에 보낸 실행 기록 문의(`vz-mission-record-inquiry.md`)에서 *"`mk2_app` 계정에는 **`SELECT, INSERT`만** 있다 — **수정·삭제를 코드 규율이 아니라 DB 권한이 막는다.** 코드로 약속하면 언젠가 누군가 깬다"*, *"답이 없으면 **무기한 보관**한다(**삭제 경로를 만들지 않았다 — 권한도 없다**)"*라고 적었고 VZ가 그 기본값에 **동의 확정**했다(`received/2026-09-17_vz-mission-record-reply.md` §2-3). 그 약속은 `mission_event`에 대한 것이지만, **`media_capture`에 `DELETE`를 주는 순간 「권한이 막는다」는 우리 규율에 첫 예외가 생긴다.**
  **그래서:** ① `mk2_app` 권한은 **`SELECT, INSERT, UPDATE`**까지만 — **`DELETE`는 주지 않는다.** ② 칼럼에 **`purged_at DATETIME(6) NULL`**을 더한다. ③ 아카이브를 지우면 `archive_path = NULL` · `archive_bytes = NULL` · `purged_at = UTC_TIMESTAMP(6)`로 **갱신**한다. **행과 `manifest` 원본은 남는다** — 무엇이 있었는지는 계속 조회된다.
  **그리고 회신에 명시한다:** *"`media_capture`의 용량 상한은 **촬영본 아카이브에만** 적용되고 `mission_event`의 무기한 보관 규약을 건드리지 않는다."* VZ가 *"요약만 남기는 방식은 안 된다 — 지난 임무를 골라 되감으려면 사건 열 전체가 남아야 한다"*로 못 박은 자리라 **명시하지 않으면 확장으로 읽힌다.**
- BE-S-04(재난 구간 장기 보존)와 **별개다** — 그건 TSDB 계측 보존이고 이건 학습 데이터셋이다.

#### 10-5. DoD

- **10-1** 🔴 **v2 규약으로 판정한다**(10-2에서 바꿨다 — 아카이브 안을 뒤지지 않는다). 가짜 업로더가 **① `PUT <base>/<session>.manifest.json` → 2xx → ② `PUT <base>/<session>.tar.gz`** 순서로 보내면, 지정 위치에 **아카이브가 바이트 동일하게 놓이고**, `mk2.media_capture`에 **한 행**이 생기며, **매니페스트 원본이 통째로 보존**된다.
- **10-2** **`kind`가 그대로 남는다**(`capture_session`이 아닌 값도).
- **10-3** **같은 세션을 두 번 PUT해도 행이 하나다.**
- **10-4** 규약이 문서에 적혔다 — 추적표 BE-S-09 · 02-media-path §1-3-4 · `00-architecture.md` §8-5.

**음성 대조**

| # | 무엇을 막는가 | 판정 |
|---|---|---|
| C1 | **토큰 불일치·부재** | 401 + **파일도 행도 생기지 않는다** |
| C2 | **매니페스트 필수 누락 · 또는 매니페스트 PUT 없이 아카이브만 옴** | 거부 + **부분 적재가 남지 않는다**(파일만 놓이고 행이 없거나 그 반대가 되지 않는다). HW는 2xx가 아니면 원본을 지우지 않으므로(`:196-202`) **데이터 손실이 없다** |
| C3 | **경로 순회**(`../../etc/passwd` 같은 파일명) | 거부 + 지정 디렉터리 밖에 아무것도 생기지 않는다 |
| C4 | **전송 중 끊김** | 불완전 파일이 최종 위치에 남지 않는다 |
| C5 | **보존 규칙 dry-run** | 상한 초과를 합성으로 만들어 **오래된 세션부터 골라지고 최신 세션은 안 골라지는 것**을 실제 삭제 없이 확인 |

---

## 6. 이번에 하지 않는 것 (범위 울타리)

1. **온디맨드 스트림 저장·이벤트 트리거 캡처**(BE-S-09 원문) — 하지 않는다. **#15 데이터셋 저장소(4b)는 만든다.**
2. **저레이트 상시 프리뷰**(§8-5) — 하지 않는다. ⚠ **개발 프로파일의 "상시 모드"와 혼동하지 않는다** — 그건 뷰어가 계속 붙어 있는 것이고 **풀레이트**라 대역을 아끼지 않는다.
3. **서버→엣지 온디맨드 개폐 명령(MQTT `stream`, §10-6) = Phase 6.** 이번 fixture는 **붙으면 계속 송출**한다.
4. **탐지 채널·토픽 신설** — `mk2.telemetry.detections`·ingest 구독 패턴 변경·`entity_type` 판별을 하지 않는다. **규격 초안만** 낸다.
5. **가용성 판정 = Phase 5.** 관측 신호로 "장치가 살았나"를 판정하지 않는다.
6. **명령·감사 로직과 인증·인가(RBAC) = Phase 6.** **단 외부 노출에 붙일 최소 인증(토큰)은 이번 범위다.** 역할·범위 모델을 설계하라는 뜻이 아니다.
7. **`.proto` 개정 = Phase 6.** §10-7의 SDP는 **홉1 사안**이고 HW가 `CommandStatus.detail`(문자열)에 JSON을 넣는 우회를 이미 쓰고 있으며(`mission-command.md` §3), 홉2는 헤더의 `encoding`으로 해결된다 — **앞당길 필요가 없다**(회신에 확인 요청으로 넣는다).
8. **Kafka SASL = Phase 6**(BE-Q-04와 함께). ⏭ **`DOCKER-USER`로 9095를 tailnet 안에서 엣지 1대로 좁히는 것도 이번에 하지 않는다**(단계 6). 이번 엣지는 임시이고 단계 8에서 9095를 통째로 닫는다. 실 엣지 장비가 상시로 붙을 때 한다 — `infra/README.md` §5·추적표 BE-T-08에 **한 줄로만** 남긴다.
   ⏭ **OTLP 인증 확장 조사도 하지 않는다**(단계 5-1 #3 — (i) 평문으로 간다).
   ⏭ **도커 발행 포트 전반의 노출 점검·정리도 하지 않는다.** Phase 0부터 있던 상태이고 다른 파트 포트가 섞여 있다(분류 ③). 이번 Phase가 새로 여는 9095·8765·8766만 책임진다.
9. 🔴 **`/state`의 VZ 계약 정합 = Phase 5/7. 이번에 하지 않는다.**
   v1은 *"VZ 계약을 깨지 않는 바인딩·인증인가만 확인한다"*고 적었는데, **봉투 자체가 이미 계약을 깨고 있어 그 DoD가 참이 될 수 없다.** 우리 `ws_echo.py:79-84`가 보내는 것은 `{channel, topic, key, message}`이고 VZ `WsTransport.onMessage`는 `switch (msg.type)` + **`default: return`**이라 **`type` 필드가 없어 전량 버려진다.** 소켓은 열리고 배지는 「연결됨」인데 값이 하나도 안 온다. 게다가 `type:'data'`만 붙여도 안 된다 — `msg.sub`(구독 id)로 구독을 찾고 없으면 `return`이라 **구독 세션 관리가 선행조건**이다.
   **이번 Phase에 붙는 것은 `/media` 하나뿐이고, `/state`는 Phase 1 echo 그대로다.** 그때까지 VZ는 목 게이트웨이(8790)를 그대로 쓴다. **부록 B 3번에 이 사실을 명시하지 않으면**, 김현우 씨가 주소를 우리 8765로 바꾸고 「연결됨」을 보고 값이 안 와서 원인을 찾게 된다.
   ⚠ 다만 우선순위를 정확히 적는다 — VZ 서버가 보내는 넷 중 **실제로 없으면 화면이 비는 것은 「구독 즉시 캐시 1회 푸시(VZ-I-02)」 하나뿐이다.** `hello`·`subscribed`·`unsubscribed`는 VZ 클라이언트가 **값을 받아도 쓰는 코드가 없거나(`stale_threshold_ms`·`serverTime` 참조 0건) `default: return`으로 버린다.** Phase 5/7에서 이 셋에 공수를 먼저 쓰지 않는다.
10. **재접속 캐시(BE-T-06) 구현 = Phase 5/7.** 이번에는 **규약을 문서·통지로 확인만** 한다.
    ⚠ **「금지 3종만」이 아니다.** 금지 3종(`command_result`·`video_frame`·`detections`)은 **BE-T-06의 예외 목록**이고, 본체는 **캐시하는 7종 + 구독 즉시 1회 푸시 + 원래 발행 시각 유지**다(`00-architecture.md` §7-4). 특히 **`video_meta`가 그 7종에 이미 들어 있는데 v1 지시서 전체에서 한 번도 다뤄지지 않았다** — 미디어 헤더와 같은 항목(fps·해상도·`encoding`)을 담는 자리이고, VZ 주석이 *"**패널 열 때** fps·해상도 규격 판단. 픽셀이 아니라 메타만"*이라 **붙기 전에** 알아야 하는 값이다. 우리는 그 값을 **바이너리 스트림 안에만** 싣고 있어 순서가 거꾸로다.
    → **이번 Phase는 미디어 헤더 규격만 정하고, `video_meta` 상태 채널 발행은 Phase 5(BE-T-06 본구현)로 이월한다.** 그 사실을 **부록 B 8번과 plan Phase 5 이월에 적는다.** 캐시 확인은 **금지 3종이 아니라 10종 전체**로 한다.
11. **실행 기록 필드·되감기 질의 = Phase 6/7.**
12. **디지털 트윈·객체 핸드오프(DT-06)·좌표 규약 ENU·HW #14·#16 형식 = Phase 7.**
13. **C층 log/event 10개 · `clock_skew` 임계 · `be.pipeline.lag` 상한 판정 = Phase 5.**
14. **실노드 관통 = 범위 밖.** 가짜 발행자·합성 fixture 기본값을 유지한다(pi7 배포본이 09-14에도 구판이다).
15. **Phase 1·2·3이 확정한 것을 다시 설계하지 않는다** — 공통 헤더 규격, 토픽 규약 `mk2.telemetry.<채널>`, `store()` 인터페이스, 스트림 좌표 유일 키, 시각 축(발행 `timestamp`·UTC), 관측 어댑터가 `opentelemetry`의 유일한 문, A층/C층 라벨 기준, `agg_layer="edge"`, Collector 호스트 포트 4316.
16. **`ws_echo.py` 파일명·systemd 유닛명을 바꾸지 않는다**(범위 확대 — docstring만 갱신).
17. **7864(AI 파트 서버)를 건드리지 않는다.** 떠 있는지만 본다.

---

## 7. 완료 판정 (체크리스트)

**아래가 전부 참이어야 이 작업이 끝난 것이다.**

### 규율·안전

1. 단계 0 대조 결과를 받은 뒤 착수했다.
2. 다른 컨테이너가 재생성되지 않았다(매 단계 `docker compose ps`).
3. compose·설정 파일을 고치기 전에 백업했다(`*.bak_before_phase4*`).
4. **compose 작업본을 서버 파일로 덮고 md5를 기록한 뒤** 편집했다.
5. 비밀값·내부망 IP·Tailscale 주소·토큰을 커밋하지 않았다(`git check-ignore` + 눈 확인).
6. 산출물이 UTF-8·LF다(CRLF 0·BOM 없음).
7. `tailscale up`을 치지 않았다.

### 규격 (단계 1)

8. `media-header.schema.json`이 `frame_ref`를 **`$ref`**로 참조한다(평면이 아니다).
9. `encoding`·`codec`·`alignment`에 **`enum`이 없고** 알려진 값은 `$comment`에 있다.
10. `frame-reference.schema.json`의 **구조가 바뀌지 않았고**(필드 추가 0), description에 **`capture_timestamp` 뜻**이 적혔다.
11. `detections.schema.json` 초안에 **메시지 단위 `alignment`**와 `coord`가 있다.
12. `contracts/common/README.md`에 파일 2행·`frame_ref` 뜻·**라벨 금지 목록**이 반영됐고 **`node_id`는 들어가지 않았다**. ⚠ 종수는 **판정 61**을 따른다(코드·테스트는 8종 확정 + 「발화 원문」 1종은 VZ 회신 대기).

### 미디어 본체 (단계 2~4)

13. 방식 B 프레이밍이 **한 메시지 = 한 프레임(H.264면 한 AU)**이다.
14. 서버가 **페이로드를 열지 않는다**(헤더만 파싱).
15. drop-old 상태 기계가 **§5 단계 2-3의 전이표대로** 동작한다.
16. 뷰어 소켓의 **초기 상태가 `WAIT_IDR`**이고 **첫 전송이 반드시 keyframe**이다.
17. `T_drop`이 **시간 기준**(150ms × 바이트율, 하한 AU 평균×2, 상한 1MB)이고 `T_hard = max(4×T_drop, 최근 IDR 최대×2)`다.
18. **JPEG가 같은 코드로 돈다**(분기 없음).
19. 드롭이 **뷰어 소켓마다 독립**이고 **엣지 입구에서는 버리지 않는다**.
20. **frame_ref가 재생성 없이 관통한다**(송신 원본과 도착분 바이트 동일).
21. **순번 역전·불연속은 기록만** 하고 거부하지 않는다.
22. 토큰 없는 접속이 **4401**로 닫힌다.
23. 미디어 지표 **5종**이 **`be.gateway.*`** 아래 있고 금지 라벨이 없다(`media_ingress` 포함 — 판정 62).
24. 확인용 뷰어가 **판정용 텍스트 출력**을 낸다(눈 확인은 보조).
25. **(오버레이를 만들었다면)** 대조가 **fail-safe 규칙**(`alignment=="frame"` + `frame_ref` 있을 때만 정합)을 따른다. **안 만들었으면 그 규칙이 `console.html` 주석으로 적혀 있다**(2-6 — 오버레이 자체는 ⏭ 선택).
26. **기준선 N(단계 0-5) + 라벨 증가분 + 신규 전건 통과, skip 0**(서버). ⚠ **"184"를 그대로 쓰지 않는다**(제약 24).
27. **음성 대조 M1~M9**가 전부 실제로 거부·유지된다(**M7 = 영상이 상태를 밀지 않는다** · **M8 = JPEG 지연 바운드** · **M9 = 과대 프레임이 연결을 안 끊는다**).
27-a. 뷰어 소켓마다 **송신 큐 + writer 태스크**가 있고, 중계 코어가 `send`를 직접 부르지 않는다(브라우저 `bufferedAmount`에 기대지 않는다).
27-b. 경로·쿼리를 **`websocket.request.path`**에서 읽는다(핸들러의 `path` 인자는 `None`이다).
27-c. **헤더 `frame_ref.source_id`와 쿼리 `source_id`가 다르면 거부**되고, 같은 `source_id` 중복 ingest는 **4409**로 거부된다.
27-d. **토큰이 로그에 남지 않는다**(`journalctl`·Loki를 실제로 조회해 확인).

### ③ 묶음 (단계 5)

28. Collector가 **loopback + Tailscale IP 둘 다** LISTEN하고 ufw는 **엣지 `/32`만**이다. *(단계 8 되돌림 **전** 시점 판정 — 되돌린 뒤에는 거짓이 되는 것이 정상이다)*
29. Collector 설정이 **`validate exit=0`**으로 판정됐다.
30. OTLP는 **(i) 터널 + ufw `/32` + 평문**으로 갔고 그 근거가 보고됐다. ⏭ **확장 유무 조사는 하지 않았다**(5-1 #3 — 인증은 BE-Q-04와 함께 Phase 6).
31. 4318은 **아예 손대지 않았다** — 설정·compose에 **변경 0**이고(DoD 5-7b), 부록 B 10번에 **CORS origin과 VZ PC tailnet 주소 문의**만 나갔다. ⚠ **줄을 「준비」해 두지도 않는다**(5-1 #4).
32. `edge_federate` 잡이 되살아났고 `match[]`에 **`up`·생사·치명 오류가 없다**. *(단계 8 되돌림 **전** 시점 판정 — 되돌린 뒤에는 거짓이 되는 것이 정상이다)*
33. Prometheus 이미지가 **digest**이고 global·다른 잡이 무변경이다.
34. **`LoggingHandler` 경고 2건이 사라졌다.**
35. ~~라벨 금지 6종~~ → **판정 61로 통합됐다**(2026-09-18 합본에서 9종으로 늘었다). 여기서는 **`node_id`가 허용되는 것**만 음성 대조로 확인한다.

### Kafka (단계 6)

36. PLAINTEXT `localhost:9092`가 **한 줄도 바뀌지 않았다.**
37. `EDGE` 리스너가 `LISTENERS`·`ADVERTISED`·`SECURITY_PROTOCOL_MAP` **셋 다**에 들어갔다.
38. 백엔드 3개가 **재기동 없이** 계속 돌고 토픽·오프셋이 그대로다.
39. `<서버 tailscale IP>:9095`가 LISTEN이다(**`0.0.0.0`이 아니다**). ufw 규칙도 있되 **통제로 세지 않는다**(제약 16). *(단계 8 되돌림 **전** 시점 판정 — 되돌린 뒤에는 거짓이 되는 것이 정상이다)*

### 2계층 실측 (단계 7)

40. **미디어가 터널 위로 관통**했다(7-b).
41. **Kafka 원격 왕복 1회 성공** → BE-T-02 gap이 닫혔다(7-d).
42. **OTLP 2계층**이 Loki·Tempo에 도달하고 `be-*`와 구분된다(7-e).
43. **페더레이션 요약이 당겨지고**, `match[]` 밖이 `agg_layer="edge"`로 **0건**이다(7-f).
44. 바인딩 상태에서 **백엔드 경로가 유지**된다(7-g).
45. 실측값이 `_serverinfo/`에 기록됐다(커밋 금지).

### 되돌림 (단계 8)

46. 되돌릴 것이 전부 되돌아갔고(8-1·8-2), **남길 것은 남았다**.
47. compose에 `EDGE`·Collector Tailscale 줄이 **주석으로 보존**됐다.
48. 되돌린 뒤 **pytest 전건 통과**, 상주 3개 `active`. ⚠ `test_media_relay.py`의 skip은 정상이다(8-4).

### 회신·통지 (단계 9)

49. HW 회신 §8이 **§8·§10-4~7 + #14~#18 + 부록 A 8-9(인식 안내)·8-10(HW가 할 일) 전건 + 8-11(`stream` 요청)**을 담았다. **숫자를 세지 말고 부록 A의 표를 따른다.**
50. `hw-envelope-conformance.md` §5-1 표가 갱신됐다(회신한 것은 §5-0으로).
51. VZ 통지가 **부록 B 13항목**과 「관측 회신에 대한 답」 절을 담았다.
52. **세 문서**(HW §8 · VZ 통지 · AI 통지)에 **실주소·토큰이 없다.**

### 4b (단계 10)

53. DoD 10-1~10-4가 전부 참이다.
54. **음성 대조 C1~C5**가 전부 실제로 막는다.
55. **PUT 입구가 남았고**(ufw pi7 `/32`), 주소·토큰 전달 방법이 회신에 적혔다(주소는 자리표시자).

### 보고

56. §8의 **갱신 대상 표 전건**이 처리됐다(**`02-media-path.md`와 `설계_규칙.md`·`작업지시_템플릿.md` 행 포함**). ⚠ v1은 *"7개"*라 적었는데 표는 8행이었고, 이제 **`02-media-path.md`와 규칙 문서 2개가 더해져 10행**이다 — **숫자를 세지 말고 표를 따른다.**

### 2026-09-18 합본으로 더해진 판정

57. **단계 0 표가 2026-09-18 실측본이고 `[재실행 대기]` 5행이 전부 채워졌다.** `pi4`·`pi6`은 **실재가 확인됐고**(지우지 않는다), `be_*`는 **28종이 맞다**.
58. **결정 10·11·12가 `02-media-path.md`에 반영됐다** — §1-3-1이 「길 A·B 동시 지원」으로, §1-1에 서버 비전 소비자 자리가, `$ref`가 **레지스트리로** 해석된다. *(지시서 §3 제약 9의 주어는 이미 「중계 경로는」이다 — 확인 대상이 아니다.)*
59. **`02-media-path.md`가 실제로 고쳐졌고 그 커밋이 회신 문서 커밋보다 앞선다**(DoD 9-6). 부록 A·B에 **"이미 고쳤다"는 과거형이 남아 있지 않다.**
60. **`detections.schema.json`에 메시지 단위 `origin{tier, kind}`가 있고 `tier`에 `server`가 들어 있다.** `alignment`는 **선택**이다. `coord.origin` 값이 **`top-left`(하이픈)**이다.
61. **라벨 금지 8종(확정분)**(`frame_ref`·`correlation_id`·**`command_id`** 포함)이 `FORBIDDEN_LABELS`·테스트·`contracts/common/README.md` **셋 다**에 있고, 셋이 실제로 `ValueError`로 막힌다. **9번째 「발화 원문」은 키 이름을 VZ에게 받은 뒤이므로 빠진 것이 아니라 대기다 — README에는 자리를 표기한다**. 「발화 원문」의 키 이름은 VZ 회신 대기라 **빠진 것이 아니라 대기**임이 보고서에 적혔다.
62. **미디어 지표에 `endpoint` 라벨을 쓴다**(`channel` 아님) — `be.gateway.push`의 `channel`과 뜻이 겹치지 않는다. **`be.gateway.media_ingress`가 있다.**
63. **8765가 `127.0.0.1`과 `<서버 tailscale IP>` 둘 다 LISTEN**이고, `settings.ws_url()`이 `/state`(+토큰)를 만들어 **기존 테스트 2건이 그대로 통과**한다.
64. **소켓 옵션 셋**(`max_size`·`write_limit`·`compression=None`)이 **명시적으로 지정**됐고, 지연 바운드가 **`T_drop + write_limit`**로 문서에 적혔다.
65. **`T_hard`가 GOP 없는 스트림에서 `T_drop`으로 축소**된다(M8).
66. **7-h를 돌렸고 결과가 추적표 BE-T-08과 보고서에 그대로 적혔다.** 「현재 통제 수준 = tailnet 밖은 바인딩이 막고, tailnet 안은 열려 있다」가 명시됐다.
67. **compose 주석 두 곳을 고쳤고**(단계 6-b), **그 내용이 커밋되는 `infra/README.md`에도 옮겨졌다**(compose는 gitignore다).
68. **AI 통지가 나갔다**(부록 D). plan §4 진나영 행의 「7864 문의 1건」이 그 문서로 연결됐다.
69. **4b:** 최종 저장 경로를 **매니페스트가 정하고 URL이 정하지 않는다** · **매니페스트를 별도 PUT으로 먼저 받는다** · `media_capture` **GRANT가 DDL 뒤에 붙었다** · `started_at`에 오프셋이 없으면 **`NULL`로 두고 `t0_unix`로 채운다** · **`mk2-capture` 유닛의 `StartLimit*`가 `[Unit]`에 있다**.
70. **새 파일 중 `.gitignore`의 `*token*`·`*secret*`에 걸려 빠진 것이 없다**(제약 25). `*.h264 binary`가 `.gitattributes`에 있다.
71. 🔴 **9095가 `0.0.0.0`이 아니라 `<서버 tailscale IP>`에 바인딩돼 있다**(결정 6 β). 문서 어디에도 *"ufw가 9095를 막는다"*가 남아 있지 않고, **`DOCKER-USER`는 미뤘다는 한 줄**이 `infra/README.md` §5와 추적표 BE-T-08에 있다. *(단계 8 되돌림 **전** 시점 판정 — 되돌린 뒤에는 거짓이 되는 것이 정상이다)*
72. 🔴 **Phase 4 전 구간에서 `docker compose down`이 한 번도 실행되지 않았다**(제약 29). `docker network inspect capstone-db_default`의 서브넷이 **`172.18.0.0/16` 그대로**이고 `SHOW GRANTS FOR 'mk2_app'@'172.18.%'`가 여전히 답한다.
73. **관측 기준선이 설명된다**(DoD 5-8) — `be_*` **28 → 35**(A층 11 → 18), Loki 라벨 **3종 그대로**.
74. **DoD 0-6의 SQL 대조 결과가 `reports/`에 한 줄 남았다**(단계 10을 한 경우).

---

## 8. 보고 (작업 끝에 무엇을 남기나)

> **Phase 2·3이 `CLAUDE.md`·루트 `README.md`·`00-architecture.md`를 연달아 놓쳤다.** 목록이 3개였기 때문이고, 그래서 7개로 늘렸다. **그런데 이번 Phase는 그 7개에도 없던 `02-media-path.md`를 놓칠 뻔했다** — 「먼저 읽을 것」 2번에 *"이번 Phase의 명세"*로 올려 놓고 갱신 대상 표에는 없었다. **읽기 목록에는 있고 쓰기 목록에는 없었다.** 판단이 애매하면 **넣는다** — 안 넣어서 낡는 비용이 더 크다.

| 대상 | 언제 | 이번 Phase에서 무엇 |
|---|---|---|
| `reports/YYYY-MM-DD_HHMM_phase4_미디어경로.md` | **항상** | 배경 / 한 일 / 검증 / 다음. **「서버에 남은 것」 표**(다음 지시서의 재료 — **근거 등급 칸을 유지한다**) · **「검증 범위의 한계」**(온디맨드 미검증 · 실물 로봇 영상 0장 · 현장 회선 아님 · VZ 미접속 · 실노드 범위 밖 · GOP 경계로 인한 프레임률 불균일) · **「지시서와 다르게 이행한 것」** · **「사용자가 결정한 것」** |
| 🔴 **`docs/be/02-media-path.md`** | **항상 — 이 Phase의 명세서다** | **v1에서 빠져 있던 행이다.** 결정 1·2·5·8·10·11이 이 문서의 아래를 거짓으로 만든다:<br>§1-2-2 *"JPEG로 통일. H.264 폐기"* → **소스 native 코덱 종단 중계**(결정 1) · 같은 절 폐기 이유 (1) *"엣지가 이미 JPEG를 쥐어"* → **엣지는 AU 재조립만 하고 디코드하지 않는다** · §1-2-3 *"pull 기본"* → **소스가 정한다**(결정 8-2) · §1-3-1 *"현재 배포 = 길 B"* → **길 A·B 동시 지원, 현재 개발 단계 = 길 A**(결정 10) · §1-3-3 *"왜 WebSocket인가"* 근거 (1)이 디코드 전제이므로 **근거를 갈아 끼운다**(결론은 유지 — 근거 2·3·4가 살아 있다) · §1-3-4 저장(결정 9·4b) · §1-5-0·§1-5-1 *"WSS(TLS)+인증"* → **터널 위 `ws`+토큰 프로파일**(결정 5) · §1-5-3 *"백엔드가 frame_ref 부착"* → **엣지가 부착한다** · §1-5-4 staleness 기준을 **도착 기준**으로 · §1-6-2 예시 `capture_timestamp: 1735120000123` → **ISO 문자열**, `origin:"top_left"` → **`"top-left"`** · §1-6-3 *"엣지 = 디코드 지점"* → **AU 재조립 지점** · §3-2 온디맨드 트리거 → **결정 4-b**(연결 자체가 신호) · **§1-1에 서버 비전 소비자 자리 한 절**(결정 11) |
| `requirement-traceability.md` | **항상** | **BE-T-07**(중계 구현·drop-old·상태) · **BE-C-03**(규격 확정·`capture_timestamp` 뜻·**`$ref` 레지스트리를 Phase 4에서 세웠고 Phase 7의 `object-reference`가 같은 경로를 쓴다**·gap 갱신) · **BE-T-03**(외부 노출+토큰·경로 분리·**`/state`의 VZ 계약 정합은 Phase 5/7**) · **BE-T-08**(터널+ufw `/32`+평면별 인증, **Kafka만 평문인 이유와 Phase 6**, **7-h 결과**) · **BE-T-05**(MAC이 라우팅 키가 아님 명시) · **BE-T-06**(**캐시 10종 규약 + `video_meta`는 Phase 5 이월**) · **BE-S-09**(#15 저장소) · **BE-T-02**(*"검증됨 · 되돌림 · 실 엣지 시 되살림"*) · **BE-S-02/S-03/S-06**(③ 묶음 반영, 브라우저 입구 gap ⑦ 정정)<br>⚠ **BE-C-01을 "미디어 헤더 규격 신설"로 적지 않는다** — BE-C-01은 「공통 메시지 스키마·필드 규약」이고 **이미 완료** 상태다. 미디어 헤더는 **BE-T-07·BE-C-03** 소관이다. 새 번호가 필요하면 **BE-C-08이 비어 있다** |
| `01-standalone-implementation-plan.md` | **항상** | Phase 4 ✅ + **DoD 문구를 결정 1·5 결과로 갱신**(353행 *"서버→뷰어 WSS+인증"* → 터널 위 `ws`+토큰 · 356행 *"합성 JPEG 프레임"* → native 코덱 · **384-385행의 `WSS`도 같은 건이다**) + 이월을 미래 Phase에(**Phase 5: `video_meta` 발행 · `/state` VZ 계약 정합 · 레지스트리로 entity↔source_id 목록** / **Phase 6: 온디맨드 개폐 배선 · `.proto` 개정 · Kafka SASL · 탐지 채널·토픽** / **Phase 7: 소스별 촬영 시각 보정 · 트윈 형식 · `object-reference` 검증 경로 편입**) + **§4 외부 의존성**은 두 종류로 — ① 이미 들어간 행(조병현 #14~18 · 진나영 Phase 4 · 김현우 Phase 4)은 **상태만 갱신**(진나영 행에 **`capture_timestamp` 뜻 통지 예정** 한 줄 추가) ② Phase 4가 새로 보내는 **회신 2건 + 통지 2건(VZ·AI)**은 **새 회신 대기 행** |
| `CLAUDE.md` | 바뀌었으면 | **거의 확실히 해당** — 폴더 블록에 `backend/gateway/media.py`·`capture.py`, 환경변수 표에 부록 C의 새 항목, 명령 블록에 미디어 fixture, **systemd 유닛 목록에 `mk2-capture`**, **원칙 3의 전송 경로 괄호에 프로파일 구분**(제약 1)<br>🔴 **폴더 블록에 「저장소 ↔ 서버 경로 대응표」를 넣는다**(제약 30). `infra/sql/` ↔ `~/capstone-db/mk2_sql/`(**이름이 다르다**) · `infra/docker-compose.yml` ↔ `~/capstone-db/docker-compose.yml` · `infra/config/` ↔ `~/capstone-db/config/` · **`.env`는 서버 `~/capstone-db/.env` 하나뿐**(저장소에 `infra/.env`는 없다) · 저장소 루트 = `~/capstone-db/phase1_work/Physical-Project-mk2/` · venv = `~/capstone-db/phase1_work/venv_phase1/`. **상시 정보라 지시서가 아니라 여기에 있어야 한다** |
| 루트 `README.md` | 바뀌었으면 | 요구사항 상태 총계 · 「지금 당장 할 일」 ⑥ 완료·⑦ 다음 · 스택 구성(포트 추가) |
| `00-architecture.md` | 바뀌었으면 | **해당** — §2 그림의 `RTP/UDP`·`(JPEG)` 두 줄 → **`(native 코덱)`** · §7-4 **캐시 정책 절에 `video_meta`의 실체와 발행 시점**(Phase 5 이월) · §7-5 영상 절(**어댑터가 "재생 가능 규격으로 흡수"한다는 서술이 native 중계와 어긋난다** · `WSS` 프로파일) · §8-5 **「Kafka 원격 노출」 행**(EDGE 리스너로 처리됨) · §8-5 **「미디어 저장(BE-S-09)」 행**(#15 갈래로 **유예 부분 해제** + **「개발 프로파일에서 스트림을 파일로 탭해 두는 카드」**를 함께 기록) |
| 🔴 `infra/README.md` | 서버 설정을 건드렸으면 | **확실히 해당 — 이번 Phase에서 가장 많이 바뀐다.** §3 포트 표에 **8765·8766·8767·9095** · §5 Kafka **"3수정" 서술을 EDGE 리스너로 교체**(항목 1·3은 여전히 필요하다는 것까지) · §6 ⓗ(Collector 바인딩) 갱신 · ufw 9092 규칙 삭제 기록 · **compose 작업본↔서버 동기화 절차** · **§6에 「digest 미고정 잔여」 7개 목록**<br>🔴 **§5 정정 박스를 고친다** — 「실측이 compose 주석을 반증했다」는 **틀렸다.** 09-18 iptables 실측으로 **compose 주석 쪽이 옳았음이 확정**됐다(제약 16·단계 6-b). 두 경로(컨테이너發 `INPUT` / 외부發 `FORWARD`)로 갈라 적고, **도커 발행 포트의 실질 통제는 바인딩 주소**임을 한 줄로 적는다.<br>**`DOCKER-USER`로 tailnet 안까지 좁히는 것은 미뤘다** — 한 줄.<br>🟠 **브리지 대역 `172.18.0.0/16` 미고정**(`ipam` 없음)과 `docker compose down` 금지 이유(제약 29).<br>**7-h 결과 한 줄** |
| `contracts/common/README.md` | 공통 규격을 건드렸으면 | **해당** — 단계 1-4(파일 2행 · `frame_ref` 뜻 · `additionalProperties` 예외 · **라벨 금지 8종 + 「발화 원문」 자리**) |
| 🔴 **`docs/be/설계_규칙.md` §3 · `docs/be/작업지시_템플릿.md` §8** | **이번에 해당** | 보고 대상 목록에 **「그 Phase의 명세서 문서」**를 한 줄 더한다 — *"설계방이 읽고 결정을 내린 문서이므로, 결정이 그 문서의 문장을 바꾸면 되돌려 적어야 한다."* **이 두 파일은 2026-09-18 합본에서 이미 고쳤다**(§8 맨 아래 「이미 반영된 것」 참조) — 구현방은 **확인만** 한다 |

**규율 8:** 몇 Phase 뒤에 쓰일 발견은 **보고서에만 적지 말고** `plan`·`추적표`에 적는다. 보고서는 직전 세션만 읽는다.

### 이미 반영된 것 (2026-09-18 합본에서 먼저 처리했다 — 다시 하지 않는다)

| 파일 | 무엇 |
|---|---|
| `docs/be/설계_규칙.md` §3 | 보고 대상 표에 **「그 Phase의 명세서 문서」** 행 추가 |
| `docs/be/작업지시_템플릿.md` §8 | 같은 항목을 상시 문서 목록에 추가 |

**아직 안 한 것(구현방 몫):** `02-media-path.md` 본문 수정 · `compose` 주석 2곳 · 나머지 §8 대상 전부. **특히 `02-media-path.md`는 단계 9(회신) 전에 끝내야 한다**(DoD 9-6).

---

## 부록 A. HW 회신 `hw-envelope-conformance.md` §8 골격

머리말 표(보내는 쪽 백엔드/이대규 · 받는 쪽 HW/조병현 · 작성일 · 근거: Phase 4 구현·검증 결과 + HW 브랜치 0914 대조 + `contracts/common/media-header.schema.json` · 대상 안건: §8·§10-4·§10-5·§10-6·§10-7·#14~#18 · 우선순위).

| 절 | 내용 |
|---|---|
| **8-0** | 한 장 요약(표) + 「답이 없어도 백엔드는 멈추지 않는다」 |
| **8-0b** | 🔴 **미디어 평면이 봉투 규약 밖임을 먼저 선언한다.** 우리가 §3에서 *"수신 즉시 봉투를 **strict 검증**한다 … **전환기·관용 모드는 없다**"*, *"불합격은 정상 토픽으로 재발행하지 않는다"*를 **채널 무관하게** 통보해 놨다. 미디어 헤더는 그 규약을 따르지 않는다(필수·타입만 보고 값 어휘를 안 본다) — **예외를 명시하지 않으면 HW가 같은 strict 규율을 기대한다.** 그리고 §2에서 우리가 HW에 *"**새 채널이 필요하면 백엔드에 먼저 알려 달라**"*고 걸어 둔 규율의 **역방향**으로, **우리가 `detections` 규격 초안을 새로 연다는 사실을 통지**한다 |
| **8-1** | **세 갈래 구분**(시연 특수 / 일반형 / 임시 경로) 표. **"JPEG-on-MQTT(`zoneA/robot/go1-001/frame`)는 시연 임시이고 백엔드 인터페이스가 아니다(원칙 3). 정식 경로는 홉1 RTP + 홉2 WebSocket 방식 B다. 우리 브릿지는 `frame`·`scan` 토픽을 구독하지 않는다 — 구독 패턴이 `+/+/+/{state,status,heartbeat}` 셋뿐이라 배달 자체가 되지 않는다(Phase 1의 `terminal/wl-001/*` 선례). 시연 뒤에도 그 토픽을 유지하는 것은 자유이나 백엔드는 소비하지 않으며 그 프레임은 저장·중계·트윈 어디에도 들어가지 않는다."** |
| **8-2** | **§10-7 회신 — ① 수용(소스별 협상), 종단까지 native 코덱.** ⚠ **"충돌"이 아니라 "권고 ① 수용"으로 쓴다** — HW가 §10-7에서 회신을 기다리던 바로 그 안이고, HW 쪽 변경은 `HW_MEDIA_SENDER=go1_relay` 한 줄이다(현재 기본값이 `rtp_jpeg`일 뿐 `go1_relay` 구현은 이미 있다). · 미디어 헤더 규격 링크 · **홉2 방식 B 송신기 규격**(한 메시지=한 AU, IDR에 SPS/PPS 인밴드, 헤더 필드 표, **drop-old 상태 기계를 송신 측에도**) · **우리 합성 fixture가 그 참조 구현** · 🔴 **AU 경계 판정과 `keyframe` 플래그는 HW 구현에 없다**(`go1_relay`는 웹소켓 메시지 1개를 AU 1개로 믿을 뿐이고 NAL 타입 분류가 양끝 어디에도 없다) — **우리가 새로 정하는 규칙임을 명시하고 홉2 송신기 규격으로 요청한다** · **HW가 이미 가진 것이 어디에 쓰이나**(`go1_relay`·`media_gateway`는 홉1 그대로, C안 HTTP multipart는 §1-3-3 폴백 카드) · **SDP는 홉1 사안이고 `CommandStatus.detail`로 충분해 `.proto`를 앞당기지 않는다** — ⚠ **근거를 넓힌다**: `CommandResult.result`뿐 아니라 **`Command.parameters`도 `map<string,double>`**이라 명령에 문자열을 실을 자리가 **애초에 없다**(`physical_command.proto:32`). 그래서 Phase 6 개정 범위가 넓고, **그 대신 `stream` 하나만 8-11의 우회로 푼다** |
| **8-2b** | 🔴 **IDR 간격 실측 요청을 철회한다.** HW `pi/bench/go1_cam_view.py` 머리말에 **실측이 이미 있다** — *"464×400 H.264 baseline, 도착 간격 33.3ms(30fps, p90 34.1), 프레임 평균 **2.4KB**, 키프레임 약 **0.48초** 간격"*(2026-08-31). **대신 두 가지를 묻는다:** ① *"그 IDR 간격이 `HW_*` 환경변수로 조절 가능한가"*(느린 소비자의 프레임률이 GOP 경계로 불균일해지는 문제 — 단계 2-3) ② *"그 값이 로봇 펌웨어 인코더의 `IDR 15` 설정에서 오는 것이라면, 말단에서 바꿀 수 있는가"*<br>⚠ **`go1_cam_view.py`를 「홉3 참조 구현」이라고 쓰지 않는다.** 파일 자신이 *"운영 구성요소가 아니다 — 말단에서 영상이 실제로 나오는가를 사람이 확인하기 위한 것"*이라 적었고, 경로가 **나노 → pi7 → 브라우저**라 **중앙 서버 구간이 통째로 빠져 있다.** drop-old도 GOP 인지 상태기계가 아니라 **`QUEUE_MAX=8` 큐 길이 제한**이고 키프레임 여부를 보지 않는다(복구는 브라우저 쪽 `decodeQueueSize>30` 재동기로 한다). **「기법 참조로 가치가 크다」로 쓴다** — WS 프레이밍·WebCodecs 클라이언트·NTP식 시계 보정·브라우저 결함 5건 수정이 전부 거기서 나왔고, **MJPEG 폴백이 이미 있다**(WebCodecs 없는 브라우저로 자동 분기, 단 파이에서 H.264→MJPEG **완전 재인코딩**이라 대가가 크다) |
| **8-3** | **§8 회신 — ISO 유지.** *"우리 문서 불일치였다. 기준은 `frame-reference.schema.json`(ISO date-time). **02-media-path §1-6-2 예시는 이번 Phase에서 정정한다**(§8 갱신 대상 — 회신 전에 끝낸다). ⚠ **저장소 안의 epoch ms 서술이 그 하나가 아니다** — `01-standalone-implementation-plan.md:380-381`, `docs/be/tasks/작업지시_phase1_얇은파이프라인관통.md:358-359,422`도 같이 고친다(§8 plan 행). v8 docx §6-9 정정은 저장소 밖이라 사용자가 한다. **SDD §5.5.2와 SRS §9.7 「해소된 미결」 O-8 행을 이에 맞춰 달라**"* — ⚠ **SRS §9.7에도 같은 `epoch ms` 서술이 있다**(v1은 SDD만 지목했다). + **`capture_timestamp` 뜻**(엣지가 프레임 경계를 확정한 시각·촬영 시각 아님·말단 지연 포함·미보정, 크기 근거로만 HW 실측 1회 ≈0.3초 — 규격값 아님) + **사실 질문: "imageai 웹소켓 프레임에 Go1이 찍은 촬영 시각이 실려 있는가."** 있으면 편향이 사라지고, 없으면 소스별 보정은 Phase 7 |
| **8-4** | **§10-4 회신 — ㉰.** `alignment`(메시지 단위, string, `$comment`) + 뷰어 fail-safe 규칙 + **온디바이스 실물이 없어 이번에 검증하지 않는다**(HW 자신이 *"구현 전에 규약만 정하면 되는 사안"*이라 적은 그대로) + ⚠ **§10-4는 하위 질문이 둘이다** — ⓐ 선택지 ①②③ 중 택일(우리 답 = ㉰ `alignment`) **ⓑ "BE-C-03·VZ-I-07이 「HW가 frame_ref를 쓴다」를 전제하는데 v8 엣지 단일 발급과 어긋나니 어느 쪽으로 정리할지도 알려 달라"**. **ⓑ에 답한다**: *"두 요구사항의 문면을 「엣지가 발급한 frame_ref를 그대로 실어 나른다」로 읽는다. 말단은 발급하지 않는다 — 하드웨어 쪽 조치는 없다."* ⚠ **SRS §9.10의 `rb-01_ondevice` 제안은 이미 철회된 것이므로 충돌로 다루지 않는다**(`BACKEND_AGENDA` §10-4 머리말이 *"하드웨어는 v8을 그대로 따른다"*로 정리해 두었다) + **온디바이스 실물이 없어 이번에 검증하지 않는다** |
| **8-5** | **§10-5 회신 — q 우선.** 근거는 **HW 자신의 실측**(1080p q5→12: 9.7→5.5Mbps, CPU 불변) **+ `go1_cam_view.py` 실측(프레임 평균 2.4KB)**. **해상도 변경은 스트림 재개 사건**인 이유 셋 — ① 헤더 `width`/`height`·`coord` 기준 재선언 ② H.264면 SPS가 바뀌어 새 IDR + 뷰어 디코더 재구성 ③ AI가 원본 해상도를 기대(자르기·리사이즈·보정 금지, 탐지 튜닝이 464×400에 묶임). **대역 상한은 우리가 정하지 않는다**(현장 회선 미실측, §3-2 QoS는 미결) |
| **8-6** | **§10-6 회신 — 해석이 맞다.** *"소스가 정한다"*(로봇 push / 표준 IP 카메라 pull, 전송 계층 동일) — **§1-2-3 문구를 "pull 기본"에서 그렇게 이번 Phase에서 손질한다**(§8 갱신 대상) + ⚠ **"소스 종류별 정적 정책"임을 명시한다**(런타임 협상이 아니다 — HW는 `config.py`의 `MEDIA_SENDER` 한 줄로 결정한다). HW가 쓴 *"표준 IP 카메라만 pull(RTSP)"*을 **그대로 승인한다**고 적는다 + ⚠ **홉1의 push/pull과 홉2의 연결 방향은 다른 층**이다(홉2는 **엣지가 클라이언트**로 서버에 붙는다 — 엣지에 인바운드를 열 필요 없다) + 개폐 명령의 우리 쪽 배선은 **Phase 6** |
| **8-7** | **#14~#18 시점 배정** — 14→Phase 7 · **15→이번(8-8)** · 16→*"경로는 이미 있다(`…/state` → 브릿지 → Kafka → WS 게이트웨이). 트윈 형식·Unity 직결(15101/15201) 철거는 Phase 7"* · 17→Phase 6(원칙 2) · 18→백엔드, Phase 5/7 + ⚠ **#14를 미루는 이유를 적는다** — `BACKEND_AGENDA:519`가 *"**14·15·16이 회신 순서상 먼저다**"*라고 명시했는데 우리는 #15만 이번에 답한다. *"트윈 형식이 좌표 규약 ENU 이행·객체 핸드오프(DT-06)와 한 묶음이라 그 둘 없이 필드를 정하면 두 번 정하게 됩니다. **다만 #14의 「다중 소스 병합 규칙」은 #15 적재에도 걸리므로, 이번 4b는 병합하지 않고 `session_id` 하나에 한 행·매니페스트 원본 통째 보존으로 갑니다** — 병합 규칙이 정해지면 그때 파생합니다."* + **#16**은 *"경로는 이미 있다"*에 더해 **"그 경로가 Unity 직결 UDP를 대체하는가와 전환 시점"**까지 적어야 유효하다(HW가 회신 없으면 Unity 직결 유지라고 적어 뒀다) |
| **8-8** | **#15 회신** — 수신 방식(단순 HTTP PUT, S3 API 아님) · 주소 `<서버 tailscale IP>:8767`(**자리표시자**, 토큰은 별도 경로) · **입구가 실제로 열리는 시점은 4b 완료 후 알린다** · 🔴 **매니페스트 규약이 v1에서 바뀌었다** — *"아카이브 안에 `manifest.json`"*이 아니라 **`PUT <base>/<session>.manifest.json`을 먼저 보내고 2xx 뒤 tar.gz를 보낸다**(이유: `tarfile`이 `sorted(listdir())` 순서라 매니페스트가 수만 장의 JPEG 뒤에 오고, gzip은 seek이 안 돼 **0.7GB를 통째로 풀어야** 한 줄을 읽는다). ⚠ *"`json.dump`를 `pack()` 앞으로 한 줄 이동"* 요청은 **철회한다** — `man["frames"]["uri"]`가 업로드 성공 **뒤**에 채워지므로 앞으로만 옮기면 **HW 로컬 매니페스트에 업로드 주소가 영영 안 남는다**(가더라도 dump가 두 번이어야 한다) · **`frame_ref_base`는 채우지 않는다**(엣지를 거치지 않으므로 발급 주체가 없다. 시각은 `t0_unix + n×interval_s`) · 보존(용량 상한 + 오래된 세션부터) · §3-4가 물은 **세 가지 중 우리가 답하는 것**을 명시한다 — 저장소 종류·업로드 방식 ✅ / 업로드 시점(**임무 종료 시 일괄**로 답한다) / 보존 기간·용량 상한 ✅ · *"그전까지 HW 기본값(파이 로컬 적재)이 맞다"* · AI 저장본·**VZ의 `mission-history/images/robot/`**과의 중복 정리는 **Phase 5/6 안건으로 올린다**(촬영본이 세 곳에 쌓인다) |
| **8-9** | **인식 안내** — ① 서버 Collector는 Phase 3부터 있다(Gateway). **`HW_OTEL_ENDPOINT`는 구성에 따라 다르다**: 기대 구성은 **말단 → 엣지 Agent → 서버**이고 그 자리는 **엣지 Agent 주소**다. 엣지 실물이 없으므로 **잠정은 비워 둔다**(발신 off = 노드 정상, `hw-node.env.example:18` 문구 그대로). **말단이 서버 4316에 직접 보내는 구성을 택한다면** 주소는 `<서버 tailscale IP>:4316`이고 ufw `/32`에 그 노드를 넣어야 하니 알려 달라. ⚠ **토큰 헤더 문장은 단계 5-1의 판정 결과에 맞춘다** — (ii)로 확정되면 *"토큰 헤더까지 함께"*, **(i)로 떨어졌으면** *"터널 안 평문이며 인증은 ufw `/32`로 대신한다. TLS·토큰은 Phase 6"*. **회신에 없는 인증을 있다고 쓰지 않는다** ② 엣지↔서버는 이미 Kafka(BE-T-02)라 HW가 별도 상향 경로를 만들 필요 없다 — ⚠ **`ARCHITECTURE_ALIGNMENT` §4-3이 Kafka 전환 조건을 「구독자 3개 이상 AND 리플레이 필요 AND 엣지 2개 이상」으로 명문화해 뒀으므로, 그 조건을 그대로 인용해 답한다**(조건을 빼고 "지금은 MQTT로 충분" 만 인용하면 근거가 약해진다) ③ **BE-T-05는 MAC을 라우팅 키로 쓰지 않는다** — ⚠ **한 줄이 아니라 세 곳이다**(`schema.py:10-11` 모듈 독스트링 · `:72-73` `_mac()` docstring · `:178-179` `registration()`) + `BACKEND_AGENDA:475`. **그 전제가 `_mac()` 폴백 로직 전체를 정당화하고 있으므로 문구를 고칠 때 로직도 함께 보라**고 적는다 ④ 로봇 지표 6종에 우리 **A/C층 라벨 기준**(`robot_id`는 C층 라벨로 허용) ⑤ **JSON→protobuf 번역 토픽을 열지 마라** — 명령 번역은 백엔드 몫(BE-A-01·원칙 13), Phase 6 ⑥ 🔴 **`edge/availability.py`가 Prometheus 예약 지표 `up`을 그대로 발행한다**(`hw_*_up`이 아니다). `up`은 Prometheus가 scrape마다 자동 생성하는 것이라 우리 `edge_federate`가 긁으면 **두 `up`이 부딪혀 엣지가 죽었는데 살아 있는 것으로 보일 수 있다.** **HW 자신의 `SRS.md` §9.8이 "②는 `up`이 아니라 파생 지표다"라고 적어 두었다** — `hw_entity_up` 등으로 개명 요청 ⑦ **매니페스트 JSON이 깨지면 재생성되어 스캔 세션의 `shots[]` 방위 대응표가 소실된다**(`capture_upload.py:152-155`) — `kind` 보존 규율의 구멍 |
| **8-10** | **「HW가 할 일」 — ⚠ 번호를 15부터 이어 붙인다.** 이 문서는 누적 번호를 쓴다(§6 뒤의 「요약 — HW가 할 일」이 **1~10**, §7-8이 **11~14**). 원문자로 다시 시작하면 HW가 어느 목록인지 알 수 없다. 그리고 **§8 머리에 한 줄** — *"이 문서의 「요약 — HW가 할 일」(§6까지)과 §7-8, §8-10을 합쳐야 전체다"*(그 요약 블록이 §6과 §7 **사이**에 물리적으로 놓여 있어 전체 요약처럼 보인다).<br>요청 목록: ① **홉2 방식 B 송신기**(엣지 실물이 서면. `go1_cam_view.py`의 WS 중계부를 재사용할 수 있는지 함께 묻는다) ② **`HW_MEDIA_SENDER=go1_relay`로 전환**(현재 기본값이 `rtp_jpeg`다) ③ **imageai 프레임의 촬영 시각 유무** ④ **`source_id` 명명 규약**(`<entity_id>_<position>`, 예 `go1-001_front`) ⑤ **매니페스트를 별도 PUT으로 먼저**(8-8) + **선택 `correlation_id` 한 칸** + **`started_at`에 오프셋을 붙여 달라** — before/after:<br>`# before` `time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started))`<br>`# after` `datetime.fromtimestamp(started, tz=timezone.utc).astimezone().isoformat(timespec="milliseconds")`<br>지금 값은 **오프셋도 밀리초도 없는 naive 로컬 시각**이라 서버가 UTC로 변환할 수 없고, **HW 자신의 `pi/common/schema.py:55-59` 규칙(콜론 오프셋 + 밀리초)을 촬영 경로만 위반**한다 ⑥ **업로드 URL에 `entity_id` 포함**(`<base>/<entity_id>/<session>.tar.gz`) — 지금은 파일명만 실려 로봇 2대가 같은 분에 시작하면 **충돌한다**(`capture_upload.py:120`) ⑦ **`up` 지표 개명**(8-9 ⑥) ⑧ **최신 push**(pi7 작업 트리가 브랜치보다 앞선다 — `turn`·`sdk_*`·`scan_hold/continue`·`forward_m=0`) |
| **8-11** | 🔴 **신설 — `stream` 명령이 규약 경로로 호출 불가하다.** `Command.parameters`가 `map<string,double>`인데 `robot_node.py::validate()`가 `params.get("action")`이 문자열 `"start"`/`"stop"`이길 요구해 **ACK 이전에 100% `INVALID_ARGUMENT`로 거부**된다. 그런데 `stream`이 `ACTIONS`·`PHYSICAL_ACTIONS`에 등록돼 **Capability로는 「지원한다」고 선언**된다. HW `README.md`의 *"영상 온디맨드 6.8Mbps ✅"*는 **2026-09-03에 완전 폐기된 레거시 JSON `cmd` 토픽**으로 한 검증이다(`HW-interface/README.md` §4).<br>**이것이 길 A(결정 10)와 Phase 6 개폐 배선을 둘 다 막는다.** 우리 문서에 함정 자체는 적혀 있었으나(`hw-envelope-conformance.md` §5-1 주석) 예시가 `set_mode`·`levee`뿐이라 **`stream`이 같은 함정이라는 것을 아무도 연결하지 않았다.**<br>**요청:** `.proto` 개정 없이 **action 이름을 `stream_start`/`stream_stop`으로 쪼갠다**(HW가 `mission-command.md`에서 이미 쓰는 우회법).<br>⚠ **무비용이 아니라는 것까지 적는다** — ⓐ `dest_host`·`session_id`도 문자열이라 **명령별 목적지·세션 지정 능력을 잃는다**(폴백은 있다) ⓑ `validate()`의 중복 start 가드(*"두 번째 ffmpeg가 같은 포트로 붙어 엣지가 두 스트림을 섞어 받는다"*)를 **함께 옮겨 써야 한다**.<br>**그리고 `hw-envelope-conformance.md` §5-1 표의 §3 행을 고친다** — *"명령 문자열 파라미터 → Phase 6"* → *"Phase 6. **단 `stream`은 Phase 4에서 action 이름 우회로 먼저 푼다** — 온디맨드 개폐·길 A가 여기 걸린다"* |

---

## 부록 B. VZ 통지 `docs/be/vz-media-interface.md` 골격

머리말 표(보내는 쪽/받는 쪽 김현우/작성일/근거: Phase 4 구현·검증 + VZ 브랜치 0916 코드 대조/대상 안건: 미디어 인터페이스 + VZ 미결 §7.4·§7.10 + 관측 회신 답/우선순위).

| # | 담을 것 |
|---|---|
| 1 | **방식 B 프레임 포맷** — `[4B 헤더길이][JSON 헤더][페이로드]`. **`frame_ref`는 객체다**(VZ 목의 정수 `frame_seq`가 아니다). 헤더 필드 표(부록 C). ⚠ **VZ 쪽 변경은 타입 하나가 아니다** — 버퍼 조회 키(`frameAt(seq)`가 `f.frame_seq === seq` 정수 동등 비교)·`frameLag` 계산(정수 뺄셈)·표시까지 걸린다. 그리고 **재접속 시 `sequence_id`가 리셋되므로** `frameLag`를 순번 차로 계산하면 그 순간 음수·거대값이 된다 — **리셋 경계는 `session_id`**다. ⚠ **VZ 목의 정수 `frame_ref`는 VZ 스스로 "미결·가정"이라 적어 둔 값**이다(*"AI와 하드웨어의 프레임 참조 형식이 다르다 … 여기서는 정수 frame_seq로 가정한다"*) — VZ-I-07 원문은 **복합키(원천 식별자·촬영 시각·시퀀스 번호)**를 요구하므로 **우리 객체안이 VZ 요구사항과 같은 방향**이다 |
| 2 | **연결 = 켜기** — `/media?source_id=…&token=…`에 **붙는 것이 켜기, 끊는 것이 끄기**. `video{entity, open}` 제어 메시지를 쓰지 않는다. **페이지 로드 때 붙으면 상시, 패널 열 때 붙으면 온디맨드** — 같은 메커니즘이다 |
| 3 | 🔴 **전면 교체 — 이번에 붙을 것은 `/media` 하나뿐이다.** *"상태는 `/state`, 영상은 `/media`"*로만 적으면 김현우 씨가 `connections.ts`의 `gateway.ws`를 우리 8765로 바꾸고 「연결됨」을 본 뒤 값이 안 와서 원인을 찾는다. **정확히 이렇게 적는다:**<br>*"**`/media`만 이번 Phase의 대상입니다.** `/state`는 **Phase 1 echo 그대로**이고 아직 가시화 와이어 계약(`{type:'data', sub, envelope}`)을 말하지 않습니다 — 지금 붙으면 `WsTransport.onMessage`의 `default: return`으로 **전량 버려집니다**(우리 봉투에 `type` 필드가 없습니다). `hello`·`subscribed`·구독 즉시 스냅샷(VZ-I-02)·`unsubscribe`도 아직 없습니다. **상태 채널 본구현은 Phase 5/7**이며, 그때까지 목 게이트웨이(8790)를 그대로 쓰시면 됩니다."*<br>⚠ **우선순위를 함께 적는다** — 그 넷 중 **화면이 실제로 비는 것은 「구독 즉시 캐시 1회 푸시」 하나뿐**이다. `stale_threshold_ms`는 `hello`로 받아도 **읽는 화면 코드가 0건**이고 실제 표시는 **state payload의 `layers.stale_threshold_ms`**가 한다 — Phase 5에서 그쪽을 먼저 맞춘다.<br>**영상 소켓은 상태와 별도 TCP다** — §1-5-2의 네 근거(head-of-line·손실 의미·수명 주기·채널별 캐시)를 그대로 만족한다. **주소·포트는 같고 경로만 다르다.** VZ는 두 번째 소켓을 연다. ⚠ **`verify:one-gateway`의 「출구 하나」 검사는 파일 단위 정규식이라 `index.ts` 안에서는 통과하지만, VZ-C-07 요구사항 문면(*"구독·명령 출구는 여전히 하나다"*)은 우회되지 않는다 — 문면 재협상이 필요하다는 점을 알린다** |
| 4 | **`entity` ↔ `source_id` 대응** — `/media`는 **카메라 단위**다. `entity`(로봇) 하나에 `source_id`(카메라)가 여럿일 수 있고, 목록은 **레지스트리(BE-Q-03)가 준다 — Phase 5/6**. 그때까지는 화면에서 `source_id`를 직접 설정한다. 명명 규약 권고 `<entity_id>_<position>` |
| 5 | 🔴 **디코드보다 앞선 단계가 있다 — 전송층에 바이너리 수신 경로 자체가 없다.** `WsTransport.onMessage`는 `JSON.parse(String(ev.data))`로 시작하고 실패하면 `catch { return }`이라, 방식 B 프레임(Blob)이 오면 **아무 로그 없이 조용히 버려진다** — 「연결됨인데 영상만 안 옴」으로 보이는 **가장 진단하기 나쁜 실패 모드**다. 저장소 전체에서 `binaryType`·`ArrayBuffer`·`createImageBitmap`·`drawImage`가 **전부 0건**이다.<br>필요한 순서: ① **`ws.binaryType = 'arraybuffer'`**(Blob이면 `.arrayBuffer()`가 비동기라 `sub.handler(envelope)`의 동기 계약이 깨진다) ② `onMessage`를 `typeof ev.data === 'string'` 기준으로 **텍스트/바이너리 2갈래 분기** ③ `[4B][JSON][페이로드]` 파서 ④ 디코드 — JPEG는 `createImageBitmap`+`drawImage`, **H.264는 WebCodecs**. `codec`(RFC 6381)을 헤더에 싣고 `description`은 주지 않는다(Annex-B in-band).<br>**`catch { return }`에 최소한 카운터 하나를 붙여 달라** — 지금 구조에서는 형식이 틀려도 화면에 아무 신호가 없다.<br>**HW가 실기에서 고친 브라우저 결함 5건 전달** — `prefer-software` · 최신 프레임만 rAF 주기로 · 보조 타이머 · `desynchronized` 제거 · `Cache-Control: no-store`. **MJPEG 폴백 참조 구현도 HW에 이미 있다**(`bench/go1_cam_view.py` — WebCodecs 없는 브라우저로 자동 분기). **모르는 `encoding`은 디코드하지 않고 상태로 표시한다** |
| 6 | **탐지 좌표·출처 선언 정합 — 「이름 정합」이 아니라 타입·구조·값이 다르다.**<br>① 우리 `coord{normalized(bool), origin, ref_width, ref_height}` ↔ VZ `bbox_space{format('normalized'\|'absolute'), origin, reference{width,height}}` — **4칸 중 2칸은 타입·구조까지 다르다.** 어느 쪽 이름으로 맞출지 묻는다. **`normalized`는 VZ가 이미 지원한다**(렌더러에 `format === 'normalized'` 분기와 전용 시나리오 버튼이 있다) — 기본값만 `absolute`라 **전환 요청**이다.<br>② ⚠ **`origin` 값은 `top-left`(하이픈)다.** VZ가 리터럴 하나로 고정했고 VZ 저장소에 `top_left`(밑줄)는 0건 — **우리 §1-6-2 예시를 하이픈으로 고친다**(이름이 아니라 값이 달랐다).<br>③ 🔴 **메시지 단위 `origin{tier, kind}`를 우리 규격에 넣는다.** 없으면 `FrameBuffer.pushDetection`이 `tier !== 'device' && tier !== 'edge'` 로 **탐지를 통째로 드롭한다.** **`tier`에 `server`를 추가해 달라** — VZ 쪽은 `tier`가 타입·`Map` 키·`resolveAlignment` 루프 **세 곳**에 박혀 있어 나중에 넣으면 계약을 다시 바꿔야 한다(결정 11). 3종이 실제 배치와 1:1이다 — `device`=pi7 온디바이스 / `edge`=엣지 노트북 / `server`=서버.<br>④ **프레임에도 좌표 선언이 있다** — VZ `VideoFrame.reference{width,height}`가 탐지의 `bbox_space.reference`와 **같은 값을 공유해야** 겹쳐진다(VZ 주석). **우리 미디어 헤더의 `width`/`height`가 그 자리다.**<br>⑤ **`alignment` fail-safe 규칙**(`frame`이라고 명시된 경우에만 프레임 정합, 부재·모르는 값은 unaligned) |
| 7 | **인증** — URL 쿼리 토큰(VZ-C-07이 주소를 통째로 받으므로 **코드 변경 0**). **토큰은 화면에서 입력한다 — 코드·설정 파일에 넣어 커밋하지 마라.** 불일치·부재는 close 4401. RBAC는 Phase 6 |
| 8 | **VZ 미결 답 — 범위를 정직하게 적는다.**<br>**§7.4**(미디어 뷰어 출력 분기·소유 파트) = **닫는다.** 출력 형식 = WS 방식 B, 소유 파트 = 백엔드 중계 / VZ 표시·오버레이(§1-5-3). ⚠ **다만 원문이 *"뷰어별로 원본 재생 능력에 의존하지 않고 공통 계약으로"*이고 후보로 WebRTC·HLS를 든다.** 우리 WS 방식 B는 **뷰어가 디코더를 만들어야 한다** — **그 선택의 이유와 대가를 적는다**: frame_ref를 프레임과 **한 메시지로 원자적으로** 묶는 것이 오버레이 정합의 성립 조건이고, WebRTC·HLS는 메타를 따로 실어 재정합 드리프트가 돌아온다. **대가는 VZ가 디코드 경로를 만드는 것**이고, 그래서 5번의 4단계와 HW의 브라우저 결함 5건을 함께 전달한다.<br>**§7.5**(MAC 라벨 정정) = 우리 `contracts/common/README.md` 「식별자 원칙」에 **이미 *"MAC·IP는 도달성 정보이며 정체성이 아니다"*로 적혀 있고** BE-T-05 행에 이번에 명시했다. ⚠ **§7.5의 나머지 두 항목(선택형 인지 capability·신뢰도 축)은 답이 아니라 구현 과제다** — VZ가 이미 `DetectionOrigin{tier,kind,label,optional}`을 만들어 뒀으니 **우리가 그 필드를 관통시켜 주는 것**이 답이다(6번 ③).<br>**§7.10**(카메라 연결 상태) = ⚠ **축을 바꿔치기하지 않는다.** VZ가 물은 것은 **`VZ-D-07` 대상 상태 조회의 한 칸**(배터리·RSSI·지연·IP·펌웨어·관절 온도와 같은 줄)이고 상대는 **`Hardware` 계약**이다. 우리가 줄 수 있는 것은 **§1-5-4의 미디어 스트림 staleness**(*"X ms간 새 프레임 없음"*, **도착 기준**) 뿐이고 **이건 다른 축**이다. 둘을 갈라 적고 **카메라 하드웨어 연결 상태는 "HW에 물어라"로 넘긴다**(새 신호를 정의하지 않는다).<br>**`video_meta`** = 캐시 7종에 이미 들어 있다. **Phase 4는 미디어 헤더 규격만 정하고 상태 채널 발행은 Phase 5로 이월한다**(§6-10) |
| 9 | **「관측 회신에 대한 답」 절** — 60초 OK · `service.name` `vz-viewer`·`vz-stt`·`vz-gen` OK · 지표만(로그·트레이스 없음) OK · 라벨 확장 수용.<br>🔴 **HW 주기 서술을 고친다.** v1은 *"HW `config.py`는 15초, 독스트링·HW-C-05는 60초(HW 코드 내부 불일치)"*라 적었는데 **HW 쪽에서 이미 종결됐다** — `BACKEND_AGENDA` §10-1 *"OTel export 주기 — **백엔드 값(15초) 채택으로 종결**"*, `config.py:80-81`에 근거 주석까지 있고, **SRS §9.11이 정의서 HW-C-05 자체를 15초로 개정**했다. `otel_metrics.py` 독스트링이 갱신 안 된 잔재다. **VZ 회신이 *"HW가 실제로 15초라면 그때 다시 맞춘다"*는 조건을 달았으므로 흐릿하게 답하면 그 판단을 못 한다.** → *"HW는 15초로 공식 채택·정의서 개정 완료. **주기는 발신자 몫이라 VZ 60초는 그대로 괜찮습니다** — 다만 「HW-C-05가 60초니까」라는 근거는 HW 쪽에서 바뀌었습니다."*<br>**라벨 확장 8종 수용, 단 `node_id`만 뜻이 다르다**(우리 = 발행 물리 노드, VZ = 임무 대상 → **`node_ref`**). ⚠ **여기에 요청을 하나 붙인다** — **VZ 코드에 `node_ref`라는 이름이 0건이고 와이어에 나가는 `node_id`는 전부 물리 노드다.** 그래서 `node_ref`만 막으면 **오늘 VZ가 내보내는 것 중 막히는 게 없다.** *"DAG 노드 식별자는 **`node_ref`라는 이름으로** 내보내 주세요"*를 명시한다. **`frame_ref`·`correlation_id`도 함께 막는다**(우리 통지가 이미 그렇게 적었는데 코드에 없어 이번에 맞췄다).<br>**브라우저 발신 경로 = A**(Collector OTLP/HTTP **4318을 Tailscale IP에만** 바인딩 + CORS + ufw `/32`). **인터넷 노출이 아니다** — 우리 통지 §4가 브라우저를 tailnet 밖으로 본 것이 틀렸다(VZ 코드 주석이 *"관제 웹(노트북)·로봇(pi7)·탐지(데스크톱)가 전부 테일넷으로 붙는다"*). ⚠ **구현 시점은 아래 10번의 두 값을 받은 뒤다** — 이번 Phase에서는 포트를 열지 않는다 |
| 10 | 🔴 **신설 — 우리에게 알려 줄 것**<br>① **관제 웹이 도는 기기의 tailnet 주소**(`tailscale ip -4` 출력). **8765(뷰어 WS)와 4318(관측 수집기) 두 입구의 ufw를 그 `/32`로 연다. 받기 전에는 VZ 쪽 입구를 열지 않는다.** 기기가 여럿이면 전부, 시연 때 바뀌면 다시.<br>② **Collector CORS 허용 origin**과 **브라우저가 쓸 exporter 종류**(protobuf / json — preflight `allowed_headers`가 갈린다).<br>③ **관제 웹을 https로 서빙하는가.** https 페이지에서 `http://<tailscale ip>:4318`로 보내면 브라우저가 **mixed content로 차단**한다. https라면 4318에 TLS가 필요하고 그건 결정 7의 범위를 넘는다.<br>⑤ **「발화 원문」 라벨의 실제 키 이름**(`utterance`? `transcript`?) — `FORBIDDEN_LABELS`는 문자열 집합이라 **이름 없이는 코드에 못 넣는다.** 받기 전에는 나머지 8종만 넣는다.<br>④ **실제 `source_id`** — VZ가 회신에서 직접 물었다(*"목 레지스트리의 로봇 ID는 `robot-01`이다. 실제 Go1의 `source_id`가 무엇인지 알려 달라"*). **답: 현재 `go1-001`, 카메라를 붙이면 `go1-001_front`.** VZ 목의 `robot-01`·`robot-01-cam`이 아니다. 목록은 **레지스트리(BE-Q-03)가 Phase 5/6에** 준다 — 그때까지 화면에서 직접 설정한다 |
| 11 | 🔴 **우리 관측 통지 §4의 세 문장을 정정한다.** 그대로 두면 VZ가 **없는 경로로 발신 코드를 짠다**.<br>① *"**HTTP 4318은 열려 있지 않다**"* → **결정 7 A로 열린다**(구현은 origin·주소를 받은 뒤).<br>② *"서버 밖이면 **`<서버 tailscale IP>:4316`**(TLS·인증은 BE-T-08)"* → 🔴 **두 군데가 바뀐다.** 우리는 **4316이 아니라 4318**을 열고, **TLS가 아니라 평문 + ufw `/32`**다. BE-T-08은 **엣지↔서버 터널**용이라 이 입구의 인증은 다른 행이다.<br>③ **`vz-stt`·`vz-gen`의 발신 주소가 비어 있다.** 이 둘은 브라우저가 아니라 **별도 프로세스**(Python·LLM 사이드카)라 gRPC를 쓸 수 있다 — *"브라우저는 4318(HTTP), `vz-stt`·`vz-gen`은 **어디로 보낼지 알려 주면 그 주소를 연다**"*를 물어야 한다. 셋이 **다른 기계에 있을 수도 있다**(ufw `/32` 대상이 갈린다).<br>④ 「가시화가 할 일」 ④(*"Collector OTLP gRPC `127.0.0.1:4316`"*)도 같은 이유로 **개정 고지**한다 |
| 12 | 🔴 **`target_entity_id`(개체)와 미디어 `source_id`(카메라)가 같은 이름으로 다른 축을 가리킨다.** VZ 실행 기록 문의에서 우리가 *"`target_entity_id`는 레지스트리 개체 키 = **공통 헤더의 `source_id`**"*라 적었고, VZ가 *"실제 Go1의 `source_id`를 알려 달라"*고 물었다. 그런데 미디어의 `source_id`는 **카메라 단위**(`go1-001_front`)다. **그대로 답하면 VZ가 `target_entity_id`에 카메라 키를 넣어 레지스트리 조인이 깨진다.**<br>→ **갈라서 적는다:** *"`target_entity_id`에는 **개체 키 `go1-001`**, `/media` 구독에는 **카메라 키 `go1-001_front`**. `frame-reference.schema.json`의 *「봉투의 source_id와 **같은 식별 체계**를 쓴다」*는 **체계가 같을 뿐 값이 같지 않다**는 뜻이다."* |
| 13 | **`origin.kind`(탐지 정밀도)와 공통 헤더 `origin_kind`(실물/시뮬/재생)는 다른 축이다.** VZ가 회신에서 *"VZ-C-06 원문은 **실물·시뮬레이션·기록 재생 3종**이고 우리 어휘는 `physical`·`simulation`·`replay`다. **'가시화가 채운다'보다 「원천이 준 값을 옮긴다」로 읽어 달라**"*고 정정했다. 두 축이 섞이지 않게 **양쪽 이름과 어휘를 표로** 적고, **백엔드가 중계분에 채우지 않는다**(HW에 이미 확정 통보한 규율)를 함께 적는다 |
| — | **캐시 정책 확인은 「금지 3종」이 아니라 10종 전체**(`video_meta` 포함 캐시 7 + 금지 3). ⚠ VZ `config.ts`는 이후 5채널이 더해져 실제로 **8/10**이고 헤더 주석의 「7/3」은 낡은 숫자다 — **우리 `00-architecture.md` §7-4가 명시한 10종은 VZ와 한 건도 어긋나지 않는다**고 적되 *"VZ가 8종을 더 관리 중"*까지 적는다 + `capture_timestamp` 뜻 한 줄 + **VZ도 `mission-history/images/robot/`에 영상 프레임을 따로 저장하고 있다** — 촬영본이 세 곳(pi·VZ·우리 4b)에 쌓이므로 **중복 정리를 Phase 5/6 안건으로 올린다**(단 VZ 쪽은 *"DB가 보관할 이력의 자리표시"*라 적혀 있어 "VZ가 하니 우리는 안 해도 된다"로 읽지 않는다) + **「가시화가 할 일」** 요약 |

---

## 부록 C. 환경변수 · 포트 · 새 파일 일람

### 환경변수(`backend/settings.py` — 단일 출처)

| 변수 | 기본값 | 뜻 |
|---|---|---|
| `MK2_WS_HOST` / `MK2_WS_PORT` | `127.0.0.1` / `8765` | 뷰어 입구(`/state`·`/media`). ⚠ **콤마 구분 목록을 받는다** — 단계 7 이후 `127.0.0.1,<서버 tailscale IP>` |
| **`MK2_WS_URL`** | `ws://127.0.0.1:8765/state`(토큰이 있으면 `?token=…` 부착) | **v1에 빠져 있던 행.** `tests/conftest.py`의 `ws_url` fixture가 이 값을 쓴다 — 경로 분기·토큰이 들어오면 **이 기본값을 안 고치면 기존 테스트 2건이 깨진다**(단계 2-4) |
| `MK2_WS_TOKEN` | **없음** | 뷰어 토큰. **loopback 바인딩이면 없어도 연다. loopback이 아닌데 비어 있으면 기동 시점에 이름을 대며 죽는다**(단계 2-4) |
| `MK2_MEDIA_INGEST_PORT` | `8766`(**`0`이면 열지 않는다**) | 엣지 입구(`/ingest`) |
| `MK2_EDGE_TOKEN` | **없음** | 엣지 토큰(`MK2_WS_TOKEN`과 같은 규칙) |
| `MK2_MEDIA_DROP_WINDOW_MS` | `150` | `T_drop`의 시간 기준 |
| `MK2_MEDIA_BUFFER_MAX_BYTES` | `1048576` | `T_drop` 상한 |
| **`MK2_MEDIA_MAX_FRAME_BYTES`** | `8388608`(8MB) | **신설.** `websockets`의 `max_size`를 이 값으로 올리고 **상한 판정은 우리 코드에서** 한다. 기본값(1MB)에 맡기면 큰 AU·JPEG이 **close 1009로 엣지를 끊는다**(단계 2-4) |
| **`MK2_MEDIA_WRITE_LIMIT`** | `8192` | **신설.** `websockets`의 전송 버퍼 상한. **이 값이 곧 `buffered` 회계에서 빠지는 바이트**이므로 작게 잡아 `T_drop`보다 작게 만든다(단계 2-3) |
| `MK2_CAPTURE_PORT` | `8767`(**`0`이면 열지 않는다**) | 4b PUT 입구 |
| `MK2_CAPTURE_TOKEN` | **없음** | 4b 토큰 |
| `MK2_CAPTURE_DIR` | **`<서버 작업 경로>/media_capture`** (실값은 서버 `.env`) | 4b 저장 위치(**저장소 밖**). ⚠ 문서에 실제 경로를 적지 않는다 — 이 지시서는 Public 저장소에 커밋된다(제약 11) |
| `MK2_CAPTURE_MAX_BYTES` | `107374182400`(100GB) | 4b 보존 상한 |

⚠ 토큰은 **영숫자만**(특수문자 금지 — `.env`를 읽는 파서가 셋이고 인용부호 규칙이 다르다: 셸 `source`·compose dotenv·systemd `EnvironmentFile`). `.env`는 `600`·소유자 `dg`.

### 포트 (`infra/README.md` §3에 추가)

| 포트 | 무엇 | 바인딩 | ufw |
|---|---|---|---|
| 8765 | 뷰어 `/state`·`/media` | **`127.0.0.1` + `<서버 tailscale IP>` 둘 다**(단계 7 이후 유지) | 사용자 컴퓨터 `/32` (+ **VZ PC `/32`는 주소를 받은 뒤**) |
| 8766 | 엣지 `/ingest` | `<서버 tailscale IP>`(단계 8에서 내림) | 엣지 `/32` |
| 8767 | 4b PUT | `<서버 tailscale IP>`(4b 후 유지) | pi7 `/32` |
| 9095 | Kafka `EDGE` | `<서버 tailscale IP>`(단계 8에서 내림) | 엣지 `/32` |
| ~~4318~~ | ~~Collector OTLP/HTTP~~ | **이번 Phase에서 열지 않는다** — CORS origin과 VZ PC 주소를 받은 뒤(단계 5-1 #4 · 부록 B 10번) | — |

### 새 파일

```
contracts/common/media-header.schema.json          신설
contracts/common/detections.schema.json            신설(초안 — payload/ 아님)
backend/gateway/media.py                           신설 (프레이밍·drop-old·중계 코어)
backend/gateway/capture.py                         신설 (4b PUT 수신단)
infra/sql/mk2_media_capture.sql                    신설 (4b DDL + GRANT, 사람이 root로 1회)
                                                   ⚠ 서버 적용 경로는 ~/capstone-db/mk2_sql/ — 이름이 다르다(제약 30)
infra/systemd/mk2-capture.service                  신설 (4b 별도 유닛 — 단계 10-1)
tests/fixtures/synthetic_464x400.h264              신설 (커밋 · .gitattributes 에 `*.h264 binary` 선행)
tests/fixtures/make_h264_fixture.sh                신설 (생성 스크립트 + NAL 7 검산)
tests/media_publisher.py                           신설 (합성 엣지 송신 fixture = 홉2 참조 구현)
tests/test_media_frame.py / test_media_dropold.py / test_media_relay.py
tests/test_contract_media.py / test_capture_upload.py
docs/be/vz-media-interface.md                      신설 (VZ 통지)
docs/be/ai-detections-interface.md                 신설 (AI 통지 — 부록 D)
```

⚠ **새 파일 이름에 `token`·`secret`을 넣지 않는다**(제약 25). 만든 뒤 `git status`로 보이는지 확인한다.

---

## 부록 D. AI 통지 `docs/be/ai-detections-interface.md` 골격 — **신설**

머리말 표(보내는 쪽 백엔드/이대규 · 받는 쪽 AI/진나영 · 작성일 · 근거: `contracts/common/detections.schema.json` 초안 + 2026-09-17 대조 보고서 §4-2 + plan §4 · 대상 안건: 탐지 규격 · 시연/정식 경로 구분 · 7864 · 우선순위).

**왜 이 문서가 필요한가:** 단계 1이 `detections.schema.json`을 신설하는데 **그 규격의 생산자가 AI다.** v1은 소비자(VZ)에게만 통지하고 생산자에게는 하지 않았다. v1 지시서 안에서 AI 언급은 네 곳뿐이고 전부 지나가는 말이었다(역할 경계 표 · `7864` · §6 울타리 17(7864를 건드리지 않는다) · §8 plan 행).

| # | 담을 것 |
|---|---|
| 1 | **`detections.schema.json` 초안 공유** — `frame_ref`(**객체**, `$ref frame-reference`) · **메시지 단위 `origin{tier, kind}`**(박스 단위가 아니다 — VZ가 그렇게 소비한다) · `alignment`(선택, 없으면 `unaligned`) · `coord{normalized, origin:"top-left", ref_width, ref_height}` · `boxes[]`. **AI가 생산자다.** 각 필드에 「우리는 이렇게 읽었다」와 「답이 없으면 이 기본값으로 간다」를 붙인다 |
| 2 | **시연 경로와의 구분**(대조 보고서 §4-2 세 갈래 그대로) — `zoneA/robot/go1-001/frame`(JPEG base64 + `rotation_deg`)은 **시연 임시**이고 **우리 브릿지는 구독하지 않는다**(구독 패턴이 `+/+/+/{state,status,heartbeat}` 셋뿐이라 배달 자체가 되지 않는다). 정식 경로는 **홉1 RTP + 홉2 WS 방식 B**다. 시연 뒤에도 그 토픽을 유지하는 것은 자유이나 **백엔드는 소비하지 않으며 그 프레임은 저장·중계·트윈 어디에도 들어가지 않는다**(원칙 3) |
| 3 | **B안이 우리 경로와 같은 모양이다** — AI가 요구 문서에서 열어 둔 *"B: RTP 스트림 + MQTT 캡처 이벤트"*가 바로 이것이다. **시연 뒤 그쪽으로 합칠 수 있다**고 적는다 |
| 4 | **질문: 7864 MJPEG 경로** — `<서버 공인 IP>:7864/stream/ai/go1_front`가 VZ의 영상 경로다. ⚠ **평소에는 내려 있다** — 09-18 실측에서 7864는 LISTEN에 없었고 AI 파트가 필요할 때만 켠다(§6 울타리 17). **이 경로와 Phase 4 미디어 경로의 관계를 정리해야 한다** — 누가 켜고 끄나, Go1 영상이 거기까지 어떻게 가나, 계속 쓸 것인가. **plan §4의 「남은 문의 1건」이 이것이다** |
| 5 | **`capture_timestamp` 뜻 통지** — *"엣지가 프레임 경계를 확정한 시각이며 촬영 시각이 아니다. 말단 내부 지연이 포함되고 보정되지 않았다."* **탐지 결과에 그 값을 그대로 실어 나르고 새로 만들지 않는다**(원칙 10) |
| 6 | **`AI-S-05` 확인** — AI가 `turn_deg`·`forward_distance_cm`를 로봇에 직접 보낼 토픽을 HW에 물었다. **명령은 백엔드 경로(BE-A-01·원칙 13)를 지나야 한다** — Phase 6에서 정리한다고 알린다 |
| — | 끝에 **「AI가 할 일」** 요약. 규율은 부록 A·B와 같다(머리말 표·근거·기본값·우선순위) |

---
