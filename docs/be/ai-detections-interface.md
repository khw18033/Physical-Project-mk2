# 탐지 결과 규격 초안 통지 — AI 파트 (Phase 4 결과)

| | |
|---|---|
| 보내는 쪽 | 백엔드(BE·DT) / 이대규 |
| 받는 쪽 | AI(인지) / 진나영 |
| 작성일 | 2026-09-19 |
| 근거 | [`contracts/common/detections.schema.json`](../../contracts/common/detections.schema.json) 초안 + 예시 [`examples/detections-draft-*.json`](../../contracts/common/examples/) · [`media-header.schema.json`](../../contracts/common/media-header.schema.json)·[`frame-reference.schema.json`](../../contracts/common/frame-reference.schema.json) · Phase 4(미디어 경로) 구현·검증 결과 · 2026-09-17 팀 브랜치 대조 보고서 §4-2(세 갈래) · AI 시연 문서 2건(`_hwsrc/ai_docs_260914/탐지_로봇데이터요구_260914.md`·HW `detection-protocol_0914.md`) · [`01-standalone-implementation-plan.md`](01-standalone-implementation-plan.md) §4 「남은 문의 1건」 · [`02-media-path.md`](02-media-path.md) |
| 대상 안건 | **탐지 결과 규격 초안**(생산자 = AI) · **시연 경로 / 정식 경로 구분** · **7864 MJPEG 경로의 자리** · `capture_timestamp` 뜻 · AI-S-05(이동 지시 토픽) |
| 우선순위 | 🔴 §1(규격 초안 — AI가 생산자인데 지금까지 소비자(VZ)에게만 통지돼 있었다) · §4(7864 경로 답) / 🟡 §2·§3·§5 / ⚪ §6 |

> **왜 이 문서가 따로 필요한가.** Phase 4가 `detections.schema.json`을 신설했는데 **그 규격의 생산자가 AI다.** 그런데 통지는 소비자(가시화)에게만
> 갔고 생산자에게는 가지 않는 구조였다 — 이 문서가 그 빈자리다. 요구사항의 기준은 공유 스프레드시트(AI-C-08·AI-C-14·AI-E-*)이고, 시연 문서
> 2건은 그 사례다. **답이 없어도 백엔드는 멈추지 않는다** — 각 항목에 기본값을 적었다. 주소는 자리표시자, 토큰은 별도 경로.

---

<a id="s0"></a>

## §0 한 장 요약

| # | 무엇 | 한 줄 | 답이 없으면 |
|---|---|---|---|
| 1 | 🔴 탐지 규격 초안 | `frame_ref`(**객체**)·메시지 단위 `origin{tier,kind}`·`alignment`(선택)·`coord{normalized, origin:"top-left", ref_width, ref_height}`·`boxes[]`. **AI가 생산자** | 초안 그대로 확정하지 않고 **초안 상태 유지**(어떤 검증 경로도 로드하지 않는다). 시연은 지금 경로 그대로 |
| 2 | 시연 경로 ≠ 정식 경로 | `zoneA/robot/go1-001/frame`(JPEG base64 + `rotation_deg`)은 **시연 임시** — 백엔드는 구독하지 않는다. 정식은 홉1 RTP + 홉2 WS 방식 B | 시연 뒤에도 그 토픽을 쓰는 것은 자유이나 백엔드는 소비하지 않는다 |
| 3 | B안 = 우리 경로 | AI가 요구 문서에서 열어 둔 *"B: RTP 스트림 + MQTT 캡처 이벤트"*가 곧 이것이다 — 시연 뒤 합칠 수 있다 | — |
| 4 | 🔴 7864 MJPEG 경로 | `<서버 공인 IP>:7864/stream/ai/go1_front`(평소 내려 있음)와 Phase 4 미디어 경로의 관계 — **누가 켜고 끄나, Go1 영상이 거기까지 어떻게 가나, 계속 쓸 것인가** | 백엔드는 7864를 건드리지 않는다. 시연 전용으로 간주 |
| 5 | `capture_timestamp` 뜻 | **엣지가 프레임 경계를 확정한 시각**, 촬영 시각 아님, 미보정. 탐지에 **그대로 실어 나르고 새로 만들지 않는다**(원칙 10) | — (규격 설명에 적혀 있다) |
| 6 | AI-S-05 이동 지시 | AI→로봇 직접 토픽·HW JSON 번역 토픽 **둘 다 백엔드 명령 경로를 우회** — Phase 6에서 정리 | 그때까지 시연 경로 유지 |

---

<a id="s1"></a>

## §1 🔴 탐지 결과 규격 초안 — AI가 생산자다

파일: [`contracts/common/detections.schema.json`](../../contracts/common/detections.schema.json) · 예시 [`detections-draft-valid.json`](../../contracts/common/examples/detections-draft-valid.json)·[`detections-draft-valid-no-alignment.json`](../../contracts/common/examples/detections-draft-valid-no-alignment.json).
**초안이며 2026-09-19 현재 백엔드의 어떤 검증 경로도 이 파일을 로드하지 않는다** — AI(생산자)·가시화(소비자) 회신 뒤 `contracts/common/payload/`로 올리고 채널·토픽을 연다(Phase 6).

```json
{
  "type": "detections",
  "frame_ref": { "source_id": "go1-001_front", "capture_timestamp": "2026-09-18T12:00:00.123+09:00", "sequence_id": 4837 },
  "alignment": "frame",
  "origin": { "tier": "edge", "kind": "precise" },
  "coord": { "normalized": true, "origin": "top-left", "ref_width": 464, "ref_height": 400 },
  "boxes": [
    { "x": 0.34, "y": 0.51, "w": 0.12, "h": 0.20, "label": "person", "confidence": 0.88 },
    { "x": 0.70, "y": 0.30, "w": 0.08, "h": 0.15, "label": "obstacle", "confidence": null }
  ]
}
```

| 필드 | 필수 | 우리는 이렇게 읽었다 | 답이 없으면 |
|---|---|---|---|
| `frame_ref` | 선택(정합하려면 필수) | **객체** `{source_id, capture_timestamp, sequence_id}` — [`frame-reference.schema.json`](../../contracts/common/frame-reference.schema.json) 그대로, 추가 필드 금지. **엣지가 미디어 헤더에 붙인 값을 그대로 옮긴다**(원칙 10 — AI가 자기 번호를 새로 만들면 오버레이가 어긋난다). `source_id`는 **카메라 키**(`go1-001_front`)이지 개체 키(`go1-001`)가 아니다 | 없으면 `alignment`가 `frame`이어도 unaligned로 그려진다 |
| `origin` | 선택 | **메시지 단위** `{tier, kind}` — 박스 단위가 아니다(VZ가 그렇게 소비한다: `tier`별 `Map`). `tier`: `device`(pi7 온디바이스, HW-R-04) / `edge`(엣지 노트북 — AI 정밀 탐지) / `server`(서버 비전, 자리만 — Phase 4 결정 11). `kind`: `safety_minimal` / `precise`. string + `$comment`, **enum 아님** | 없으면 VZ가 출처 구분 없이 그린다 — `tier`는 꼭 실어 달라 |
| `alignment` | 선택 | `"frame"` = 이 탐지의 `frame_ref`가 가리키는 프레임과 **정합**(엣지 프레임에서 추론했다). 그 외·부재 = **unaligned**(최신 프레임 위 참고 표시). **fail-safe** — 모르는 값도 unaligned. 온디바이스(pi7) 결과는 엣지를 거치지 않아 `unaligned`가 정상 | 부재 = unaligned |
| `coord` | ✅ | `normalized:true`(0~1 비율, 권장) / `origin:"top-left"`(**하이픈** — VZ 리터럴) / `ref_width`·`ref_height` = **미디어 헤더의 `width`·`height`와 같은 값**(원본 해상도, 464×400). ⚠ 가시화가 `bbox_space{format, origin, reference{width,height}}` 이름을 쓰고 있어 **이름을 어느 쪽으로 맞출지 VZ와 정하는 중**이다 — AI는 값(정규화·원점·기준 해상도)만 지키면 이름 변경은 우리가 흡수한다 | 우리 이름 그대로 |
| `boxes[]` | ✅ | `{x, y, w, h, label, confidence?}` — 좌상단 기준 폭·높이. `confidence`는 `null` 허용(온디바이스는 분류를 안 한다). **박스 단위 `source`는 없다**(출처는 메시지 단위 `origin`) | — |
| `type` | 선택 | `"detections"` — 상태 채널 분기용 | — |

**우리가 정한 것과 AI가 정할 것:** 백엔드는 **틀**(필드·타입·정합 규칙)을 정하고, **`label` 어휘·`confidence` 임계·추론 주기**는 AI가 정한다(AI-C-14·AI-E-*). 어휘를 `enum`으로 잠그지 않는다 — 알려진 값은 `$comment`에만.

**산출물 형식은 좌표 JSON이다 — 이미지 번인 금지.** 박스가 그려진 프레임을 다시 보내지 않는다(원칙 3 — 영상 픽셀을 업무 메시지에 싣지 않는다). 겹치는 것은 가시화가 한다(VZ-I-07).

**전송 경로(예정, Phase 6):** 탐지는 **업무 데이터**라 기존 간선을 탄다 — 엣지 MQTT → 브릿지 → Kafka → WS 게이트웨이 `/state` → 가시화. 토픽·채널 이름은 Phase 6에서 백엔드가 연다(원칙 2 — 새 채널은 백엔드가 연다). **AI가 VZ로 HTTP 직결하는 지금 시연 경로는 임시**다(§2).

**서버 비전 소비자 자리(정보):** 서버에서 도는 추론기가 필요해지면 **뷰어와 똑같이 `/media?source_id=…`에 붙어 자기 프로세스에서 디코드**하고 `origin.tier="server"`로 낸다 — 중계 경로(헤더만 읽는다)와 무관하며 금지가 아니다. Phase 4는 자리만 잡았고 모델·GPU 예산·중복 제거는 범위 밖이다.

---

<a id="s2"></a>

## §2 시연 경로와 정식 경로 — 세 갈래 (2026-09-17 대조 §4-2 그대로)

| 시연 특수 — 설계 대상 아님 | 일반형 — 설계 대상 | 임시 경로 — 우리 경로로 바뀜 |
|---|---|---|
| 45°×8 회전, `rotation_deg`가 정합 키, 문 탐지, 단상 역산 | frame_ref 시각이 상태 채널과 같은 시각 축인지(발행 `timestamp`·UTC) | **JPEG base64를 MQTT `zoneA/robot/go1-001/frame` 토픽에** |
| `mission_id`가 8장 묶음 키 | 프레임·탐지가 **어느 명령의 산출**인지(`correlation_id`) | 구판 봉투(`1.3`·`device_id`·`+0900`) |
| 정지 후 촬영·0.6초 settle·한 장씩 | **원본 무가공**(좌표 기준 해상도 — 자르기·리사이즈·보정 금지, 탐지 튜닝이 464×400에 묶임) | **탐지 결과 AI→VZ HTTP 직결** |
| `/scan` 경계 신호 · AI 처리 ~2초/프레임 | 카메라 프리즈는 타임스탬프로 못 잡는다 | AI→로봇 직접 명령 토픽 / HW JSON 번역 토픽 |

- **`zoneA/robot/go1-001/frame`(JPEG base64 + `rotation_deg`)은 시연 임시이고 백엔드 인터페이스가 아니다.** 우리 브릿지는 그 토픽을 **구독하지 않는다** — 구독 패턴이 `+/+/+/{state,status,heartbeat}` 셋뿐이라 **배달 자체가 되지 않는다.** 시연 뒤에도 그 토픽을 유지하는 것은 자유이나 **백엔드는 소비하지 않으며 그 프레임은 저장·중계·트윈 어디에도 들어가지 않는다**(원칙 3).
- **정식 경로는 홉1 RTP + 홉2 WebSocket 방식 B다.** 로봇(pi7) → 엣지 노트북(RTP, native H.264) → 서버 `/ingest`(방식 B) → 뷰어·서버 비전 `/media`. AI가 엣지에서 추론하면 **엣지가 재조립한 AU + `frame_ref`**가 입력이다 — 디코드는 AI 어댑터(AI-C-08) 안에서.
- 시연의 자세 정합(`rotation_deg`)은 일반화하면 "프레임이 촬영 시점 자세와 정합돼야 한다"이고, 그것은 **Phase 7(트윈 DT-01·DT-04)의 pose 부착**으로 간다 — Phase 4는 설계하지 않았다.

---

<a id="s3"></a>

## §3 B안이 우리 경로와 같은 모양이다

AI 요구 문서(`탐지_로봇데이터요구_260914.md`)가 열어 둔 *"B: RTP 스트림 + MQTT 캡처 이벤트"*가 **바로 Phase 4 미디어 경로**다 — RTP(홉1) + 캡처 이벤트는 `frame_ref`(엣지가 AU 경계를 확정하며 부여)로 표현되고, 명령 산출물이면 `correlation_id`가 붙는다. **시연 뒤 그쪽으로 합칠 수 있다.** 합칠 때 AI 쪽이 바꿀 것은 입력 어댑터 하나(JPEG-on-MQTT → 엣지 AU 또는 `/media` 구독)이고, 출력(§1 규격)은 같다.

---

<a id="s4"></a>

## §4 🔴 질문 — 7864 MJPEG 경로의 자리

2026-09-16 시연에서 VZ의 영상은 **`<서버 공인 IP>:7864`의 AI 서버**가 MJPEG(`/stream/ai/go1_front`, ~3.5장/초)와 장애물 JSON을 내고 VZ가 `<img>`로 띄우는 구조였다(대조 보고서 §4-2). ⚠ **평소에는 내려 있다** — 2026-09-18 서버 실측에서 7864는 LISTEN에 없었고 AI 파트가 필요할 때만 켠다. 백엔드는 이 포트를 **건드리지 않는다**(Phase 4 범위 울타리).

**이 경로와 Phase 4 미디어 경로의 관계를 정리해야 한다 — 세 가지를 묻는다:**

| # | 물음 | 우리 기본값(답이 없으면) |
|---|---|---|
| ① | **누가 켜고 끄나** — 시연 때만 손으로? 상시? | 시연 전용으로 간주. 상시가 되려면 공인 IP 평문 HTTP는 노출이라(원칙 12·`02-media-path.md` §1-4-3) 터널 안으로 옮겨야 한다 |
| ② | **Go1 정면 H.264가 7864까지 어떻게 갔나** — pi7에서 직접? 어느 경로로 디코드했나 | 자료에 없다(대조 보고서 「확인하지 못한 것」). 정식 경로에서는 엣지가 재조립한 AU를 `/media`로 받는다 — 7864가 그 소비자가 될 수 있다 |
| ③ | **계속 쓸 것인가** — 시연 뒤에도 MJPEG 출력을 유지? | 유지한다면 **탐지 결과는 §1 규격으로 상태 채널에**, 영상은 `/media`로 — 7864의 MJPEG는 AI 내부 디버그 출력으로만 |

**plan §4의 「남은 문의 1건」이 이것이다.** 답이 오면 plan과 `02-media-path.md` §1-1-1에 반영한다.

---

<a id="s5"></a>

## §5 `capture_timestamp`의 뜻 — 그대로 실어 나른다

- **`frame_ref.capture_timestamp`는 엣지가 프레임 경계(AU)를 확정한 시각이다.** 촬영 시각이 아니고, 말단 내부 지연(카메라→인코더→pi7→RTP→엣지 재조립)이 포함되며, 보정되지 않았다. ISO date-time(콜론 오프셋 + 밀리초), epoch ms가 아니다(Phase 4 결정 2 — 우리 옛 문서가 어긋나 있었다).
- **탐지 결과에 그 값을 그대로 실어 나르고 새로 만들지 않는다**(원칙 10). 추론에 걸린 시간은 `capture_timestamp`를 고치는 것이 아니라 별도 필드(VZ 목의 `inference_delay_ms` 같은 것)로 — 필요하면 초안에 넣자고 알려 달라.
- 촬영 시각이 정말 필요하면(예: 자세 정합) **HW에 "imageai 프레임에 Go1이 찍은 촬영 시각이 실려 있는가"를 물어 두었다** — 있으면 엣지가 옮기고, 없으면 소스별 보정은 Phase 7.
- 오프라인 촬영본(HW #15 세션, 4b 저장소)은 엣지를 거치지 않아 `frame_ref`가 없다 — 그 프레임 시각은 매니페스트의 `t0_unix + (n-1)×interval_s`이고, 라벨링 산출물은 `frame_ref`가 아니라 세션·프레임 번호로 잇는다(Phase 5/6에서 AI 저장본과의 관계를 정리한다).

---

<a id="s6"></a>

## §6 AI-S-05 확인 — 이동 지시는 백엔드 명령 경로를 지난다

AI가 스캔 결과로 **이동 지시(`turn_deg`·`forward_distance_cm`)를 로봇에 직접 보낼 토픽**을 HW에 물었고(요구 §4, *"지금은 보내지 않고 있다"*), HW는 JSON→protobuf **번역 토픽을 열겠다**고 답했다(`detection-protocol_0914.md` §4). **둘 다 백엔드 명령 경로를 우회한다** — 명령 번역은 백엔드 몫(BE-A-01·원칙 13 — 브라우저·AI는 게이트웨이만 통한다), 상관키 `command_id`는 백엔드가 발급(원칙 8), 결과는 감사에 남는다(원칙 5). AI-S-05 자신이 *"AI는 대상·관측 조건·사유만 제시하고 실제 장치 선택·명령은 백엔드"*라 적은 것과 같은 원칙이다.

**Phase 6에서 정리한다** — AI → 백엔드(관측 요청 / 위험 판정, AI-S-05·AI-R-02) → 장치. 그때까지 시연 경로를 바꾸라는 뜻이 아니다 — **새 우회 토픽을 더 만들지 말아 달라**는 뜻이다. HW에도 같은 내용(번역 토픽 금지)을 통지했다.

---

<a id="todo"></a>

## AI가 할 일

1. 🔴 **§1 규격 초안 회신** — 필드별로 "이대로" 또는 "이렇게 바꿔 달라"(특히 `origin.tier/kind` 어휘, `alignment`를 엣지 추론에서 `frame`으로 낼 수 있는지, `label` 어휘, `confidence null` 허용). 답이 없으면 초안 상태로 둔다.
2. 🔴 **§4 7864 세 물음** — 누가 켜고 끄나 · Go1 영상이 거기까지 간 경로 · 계속 쓸 것인가.
3. 🟡 **`frame_ref`를 재생성하지 않는다** — 엣지 헤더의 값을 그대로 옮긴다(§5). `source_id`는 카메라 키.
4. 🟡 **산출물은 좌표 JSON** — 번인 이미지 없음(§1).
5. ⚪ 시연 토픽(`…/frame`)은 백엔드가 소비하지 않는다는 것을 알고 있으면 된다(§2). B안으로 합칠 시점은 AI가 정한다(§3).
6. ⚪ AI→로봇 직접 토픽·HW 번역 토픽을 **새로 만들지 않는다** — Phase 6 백엔드 명령 경로(§6).

**답이 늦어도 백엔드는 멈추지 않는다.** 탐지 채널·토픽은 Phase 6이고, 그전까지 시연 경로는 백엔드와 독립이다.
