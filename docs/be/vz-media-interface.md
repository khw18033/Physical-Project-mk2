# 미디어 인터페이스 통지 — 가시화 파트 (Phase 4 결과)

| | |
|---|---|
| 보내는 쪽 | 백엔드(BE·DT) / 이대규 |
| 받는 쪽 | 가시화(VZ) / 김현우 |
| 작성일 | 2026-09-19 |
| 근거 | **Phase 4(미디어 경로) 구현·검증 결과** — 서버 pytest 256건(미디어 59 + 라벨 13 신규) + 컴퓨터 임시 엣지 실측(2026-09-19, 브라우저 뷰어 2954장·WebCodecs 표시·링크 500kbit drop-old) · **VZ 브랜치 0916 코드 대조** — `viz-debugger/src/transport/WsTransport.ts`·`src/tabs/data/vision.ts`·`gateway/vision.ts`·`gateway/protocol.ts`·`gateway/server.ts`·`src/detect/presets.ts`·`web-dashboard/README.md`·`contracts/twin-viewer.md`·`package.json` · 백엔드 규격 [`contracts/common/media-header.schema.json`](../../contracts/common/media-header.schema.json)·[`detections.schema.json`](../../contracts/common/detections.schema.json)(초안)·[`frame-reference.schema.json`](../../contracts/common/frame-reference.schema.json) · [`02-media-path.md`](02-media-path.md) · VZ 관측 회신 [`received/2026-09-17_vz-observability-namespace-reply.md`](received/2026-09-17_vz-observability-namespace-reply.md) |
| 대상 안건 | **미디어 인터페이스**(방식 B 프레임 형식·`/media` 연결 규약·인증·탐지 좌표/출처 선언) · **VZ 미결 §7.4·§7.5·§7.10** · **관측 회신(2026-09-17)에 대한 답**(§9) · **우리에게 알려 줄 것 5개**(§10) |
| 우선순위 | 🔴 §3(이번에 붙을 것은 `/media` 하나 — `/state`를 바꾸지 마라) · §5(바이너리 수신 경로가 없다) · §6(탐지 규격 정합) · §10(주소·origin 회신 전에는 VZ 입구를 열지 않는다) / 🟡 §1·§2·§4·§7·§9 / ⚪ §8·§11·§12·§13 |

> 이 통지는 기존 두 문서와 **겹치지 않는다** — [`vz-mission-record-inquiry.md`](vz-mission-record-inquiry.md)(실행 기록, 회신 받음)·
> [`vz-observability-namespace.md`](vz-observability-namespace.md)(관측 이름 공간, 회신 받음). 관측 회신에 대한 답은 새 문서가 아니라
> **이 통지의 [§9](#s9) 한 절**이다. 주소는 자리표시자(`<서버 tailscale IP>`), 토큰은 **별도 경로로 전달**한다.
>
> **바쁘면 [§0](#s0)과 [「가시화가 할 일」](#todo)만 봐도 된다.** 각 항목에 「우리는 이렇게 읽었다」와 「답이 없으면 이 기본값으로 간다」를 붙였다.

---

<a id="s0"></a>

## §0 한 장 요약

| # | 무엇 | 한 줄 | 절 |
|---|---|---|---|
| 1 | 방식 B 프레임 형식 | `[4B 헤더길이][JSON 헤더][페이로드]`. **`frame_ref`는 객체**(정수 `frame_seq`가 아니다) | [§1](#s1) |
| 2 | 연결 = 켜기 | `/media?source_id=…&token=…`에 **붙는 것이 켜기, 끊는 것이 끄기**. 제어 메시지 없음 | [§2](#s2) |
| 3 | 🔴 이번에 붙을 것 | **`/media` 하나뿐.** `/state`는 Phase 1 echo 그대로 — 지금 `connections.ts`의 주소를 우리 8765로 바꾸면 값이 전량 버려진다 | [§3](#s3) |
| 4 | `entity` ↔ `source_id` | `/media`는 **카메라 단위**(`go1-001_front`). 목록은 레지스트리(Phase 5/6) — 그때까지 화면에서 직접 설정 | [§4](#s4) |
| 5 | 🔴 바이너리 수신 경로 | `WsTransport.onMessage`가 `JSON.parse`로 시작해 Blob을 조용히 버린다 — `binaryType`·분기·파서·디코더 4단계 | [§5](#s5) |
| 6 | 🔴 탐지 좌표·출처 선언 | 이름 정합이 아니라 타입·구조·값이 다르다 — `coord`↔`bbox_space`, `origin.tier`에 `server`, `top-left`, `alignment` fail-safe | [§6](#s6) |
| 7 | 인증 | URL 쿼리 토큰. 코드 변경 0(VZ-C-07). 불일치 4401. 토큰은 화면 입력 — 커밋 금지 | [§7](#s7) |
| 8 | VZ 미결 §7.4·§7.5·§7.10 | §7.4 닫음(WS 방식 B·백엔드 중계/VZ 표시) · §7.5 MAC 정정 완료 · §7.10은 축이 다르다(스트림 staleness만) · `video_meta`는 Phase 5 | [§8](#s8) |
| 9 | 관측 회신에 대한 답 | 60초 OK · `service.name` 셋 OK · 지표만 OK · 라벨 8종 반영(+`node_ref` 이름 요청) · **브라우저 발신 = A(4318 tailnet 바인딩 + CORS)**, 구현은 §10 회신 뒤 | [§9](#s9) |
| 10 | 🔴 우리에게 알려 줄 것 | ① 관제 웹 tailnet 주소 ② CORS origin·exporter 종류 ③ https 여부 ④ 실제 `source_id` 확인 ⑤ 「발화 원문」 키 이름 | [§10](#s10) |
| 11 | 관측 통지 §4 정정 | "4318 닫힘" → 열린다(A) · "4316·TLS" → 4318·평문+ufw `/32` · `vz-stt`·`vz-gen` 주소 문의 | [§11](#s11) |
| 12 | `target_entity_id` ≠ 미디어 `source_id` | 개체 키 `go1-001` vs 카메라 키 `go1-001_front` — 같은 체계, 다른 값 | [§12](#s12) |
| 13 | `origin.kind` ≠ `origin_kind` | 탐지 정밀도 축 vs 실물/시뮬/재생 축. 백엔드는 중계분에 채우지 않는다 | [§13](#s13) |
| — | 캐시 10종 · `capture_timestamp` 뜻 · 촬영본 세 곳 | 10종 전부 VZ와 어긋남 0 · 시각의 뜻 · 중복 정리 Phase 5/6 | [§14](#s14) |

**답이 없어도 백엔드는 멈추지 않는다.** 8765는 지금 사용자 컴퓨터 `/32`로만 열려 있고, VZ는 목 게이트웨이(8790)를 계속 쓰면
된다. VZ 입구는 [§10](#s10) ①②③이 온 뒤에 연다.

---

<a id="s1"></a>

## §1 방식 B 프레임 형식 — `frame_ref`는 객체다

**웹소켓 바이너리 메시지 하나 = 프레임(액세스 유닛) 하나.**

```
[4바이트 big-endian: 헤더 길이][JSON 헤더(UTF-8)][페이로드 바이트]
```

```json
{
  "frame_ref": { "source_id": "go1-001_front", "capture_timestamp": "2026-09-18T12:00:00.123+09:00", "sequence_id": 4837 },
  "encoding": "h264", "keyframe": true, "width": 464, "height": 400,
  "codec": "avc1.42E01E", "correlation_id": null
}
```

| 필드 | 필수 | 뜻 | 우리는 이렇게 읽었다 |
|---|---|---|---|
| `frame_ref` | ✅ | **객체** `{source_id, capture_timestamp(ISO), sequence_id}` — [`frame-reference.schema.json`](../../contracts/common/frame-reference.schema.json). 엣지가 부여, 서버는 바이트 그대로 전파 | VZ 목의 `frame_ref: number`(`vision.ts:84`)·`frame_seq`(`:36`)는 **VZ 스스로 "미결·가정"이라 적어 둔 값**이다(`gateway/vision.ts:142-143` *"AI와 하드웨어의 프레임 참조 형식이 다르다 … 여기서는 정수 frame_seq로 가정한다"*). **VZ-I-07 원문은 복합키(원천 식별자·촬영 시각·시퀀스 번호)**이므로 우리 객체안이 VZ 요구사항과 같은 방향이다 |
| `encoding` | ✅ | 페이로드 코덱 **선언**. string, 알려진 값 `h264`·`jpeg`는 `$comment`(enum 아님) | **모르는 값은 디코드하지 않고 상태로 표시**한다 — 서버도 값을 검증하지 않는다 |
| `keyframe` | ✅ | 이 프레임만으로 디코드를 시작할 수 있는가(IDR). JPEG는 항상 `true` | 뷰어는 **첫 keyframe까지 디코더에 넣지 않는다** — 서버가 첫 전송·드롭 뒤 재개를 항상 keyframe으로 보장하지만 재연결 직후 방어는 뷰어 몫 |
| `width`·`height` | ✅ | 원본 해상도 | **VZ `VideoFrame.reference{width,height}`가 이 자리다**(`vision.ts:40-41` *"탐지의 bbox_space.reference와 같은 값이어야 한다"*) — [§6](#s6) ④ |
| `codec` | 선택 | RFC 6381 문자열 = WebCodecs `VideoDecoderConfig.codec`. `description`은 없다(Annex-B in-band) | H.264 디코더 구성에 그대로 쓴다 |
| `correlation_id` | 선택 | 명령 산출물일 때의 상관키 | 표시용. `frame_ref` 밖에 있다(결정 2) |

⚠ **VZ 쪽 변경은 타입 하나가 아니다.** `frame_ref`가 객체가 되면 — 버퍼 조회 키(`frameAt(seq)`가 `f.frame_seq === seq` 정수 동등 비교, `vision.ts:240-241`) · `frameLag` 계산(`:337` 정수 뺄셈) · 표시(`VideoOverlayView.tsx`의 `{report.frameLag}프레임`)까지 걸린다. 키는 `(source_id, sequence_id)` 쌍으로, `frameLag`는 같은 `source_id` 안의 `sequence_id` 차로.

⚠ **재접속하면 `sequence_id`가 리셋된다**(엣지가 붙을 때마다 0부터). `frameLag`를 순번 차로 계산하면 그 순간 음수·거대값이 된다 — **리셋 경계는 세션**(엣지 재연결)이다. 순번이 줄어들면 새 세션으로 보고 버퍼를 비운다.

**답이 없으면:** 객체 그대로 간다 — 이것이 규격 파일이다.

---

<a id="s2"></a>

## §2 연결 = 켜기 — 제어 메시지가 없다

`ws://<서버 tailscale IP>:8765/media?source_id=<카메라 키>&token=<토큰>`에 **붙는 것이 켜기, 끊는 것이 끄기**다.
`video{entity, open}` 같은 제어 메시지를 쓰지 않는다(VZ 목 `protocol.ts`의 그 메시지는 우리 게이트웨이에 보내지 않는다 — 보내도 무시된다).

- **페이지 로드 때 붙으면 상시, 패널 열 때 붙으면 온디맨드** — 같은 메커니즘이고 서버는 그 차이를 모른다(Phase 4 결정 4-b).
- 첫 프레임은 항상 `keyframe=true`다. 붙은 뒤 첫 프레임까지의 시간(콜드스타트)은 서버 지표로 재고 있다 — 직접 경로 실측 215ms(GOP 0.5초).
- 엣지가 아직 안 붙어 있으면 소켓은 열리고 프레임만 안 온다 — "연결됨인데 영상 없음"은 정상 상태일 수 있다. 엣지가 붙으면 그때부터 흐른다.
- 서버는 뷰어 소켓마다 **GOP 인지 drop-old**를 건다 — 느린 뷰어 하나가 다른 뷰어를 막지 않는다. 다만 [§5](#s5) 끝의 주의를 보라.

**답이 없으면:** 이대로. VZ 코드의 `video{open}` 발신부는 지워도 되고 남겨도 된다(무해).

---

<a id="s3"></a>

## §3 🔴 이번에 붙을 것은 `/media` 하나뿐이다 — `/state`는 바꾸지 마라

**`/media`만 이번 Phase의 대상입니다.** `/state`는 **Phase 1 echo 그대로**이고 아직 가시화 와이어 계약(`{type:'data', sub, envelope}`)을
말하지 않습니다 — 지금 붙으면 `WsTransport.onMessage`의 `switch (msg.type)` … `default`(`WsTransport.ts:183-`)에 걸려 **전량 버려집니다**
(우리 봉투 `{channel, topic, key, message}`에 `type` 필드가 없습니다). `hello`·`subscribed`·구독 즉시 스냅샷(VZ-I-02)·`unsubscribe`도 아직 없습니다.
**상태 채널 본구현은 Phase 5/7**이며, 그때까지 목 게이트웨이(8790)를 그대로 쓰시면 됩니다.

*(위 문단을 이렇게 강조하는 이유: "상태는 `/state`, 영상은 `/media`"로만 적으면 `connections.ts`의 `gateway.ws`를 우리 8765로 바꾸고 「연결됨」을 본 뒤 값이 안 와서 원인을 찾게 된다.)*

⚠ **우선순위를 함께 적는다** — `/state`에서 VZ 서버가 보내는 넷(`hello`·`subscribed`·구독 즉시 스냅샷·`unsubscribed`) 중 **화면이 실제로 비는 것은 「구독 즉시 캐시 1회 푸시」(VZ-I-02) 하나뿐**이다. `stale_threshold_ms`는 `hello`로 받아도 **읽는 화면 코드가 0건**이고, 실제 표시는 **state payload의 `layers.stale_threshold_ms`**가 한다(`contracts/twin-viewer.md:190`). Phase 5에서 그쪽을 먼저 맞춘다.

**영상 소켓은 상태와 별도 TCP다.** [`02-media-path.md`](02-media-path.md) §1-5-2의 네 근거(head-of-line·손실 의미·수명 주기·채널별 캐시)를 그대로 만족한다 — 영상이 명령을 밀지 못하고, 영상에만 drop-old가 걸린다. **주소·포트는 같고 경로만 다르다** — VZ는 **두 번째 소켓**을 연다.

⚠ **VZ-C-07 문면과의 관계:** `verify:one-gateway`(`package.json:34`)의 「출구 하나」 검사는 파일 단위 정규식이라 `index.ts` 안에서 두 소켓을 열어도 통과하지만, **VZ-C-07 요구사항 문면(*"구독·명령 출구는 여전히 하나다"*)은 우회되지 않는다.** "게이트웨이 주소는 하나, 소켓은 경로별 둘"로 **문면 재협상이 필요하다** — 우리는 그렇게 읽는다.

**답이 없으면:** VZ는 `/state`를 건드리지 않고 `/media`만 새 소켓으로 붙인다.

---

<a id="s4"></a>

## §4 `entity` ↔ `source_id` 대응 — `/media`는 카메라 단위다

`entity`(로봇, `go1-001`) 하나에 `source_id`(카메라)가 여럿일 수 있다 — Go1은 5카메라다. `/media`의 `source_id`는 **카메라 키**다.

- **명명 규약(HW에 요청함):** `<entity_id>_<position>` — `go1-001_front`·`go1-001_chin`·`go1-001_left`·`go1-001_right`·`go1-001_belly`.
- **목록은 레지스트리(BE-Q-03)가 준다 — Phase 5/6.** 그때까지 화면에서 `source_id`를 **직접 설정**한다(VZ-C-07이 주소를 화면에서 받는 것과 같은 자리).
- VZ 목의 `robot-01`·`robot-01-cam`이 아니다 — [§12](#s12).

**답이 없으면:** 화면 설정값으로 간다.

---

<a id="s5"></a>

## §5 🔴 디코드보다 앞선 단계 — 전송층에 바이너리 수신 경로 자체가 없다

`WsTransport.onMessage`는 `JSON.parse(String(ev.data))`(`WsTransport.ts:178`)로 시작하고 실패하면 `catch { return }`(`:179-181`)이라,
방식 B 프레임(Blob)이 오면 **아무 로그 없이 조용히 버려진다** — 「연결됨인데 영상만 안 옴」으로 보이는 **가장 진단하기 나쁜 실패 모드**다.
VZ 저장소 전체에서 `binaryType`·`ArrayBuffer`·`createImageBitmap`·`drawImage`가 **0건**이다(2026-09-17 대조).

**필요한 순서:**

| # | 무엇 | 왜 |
|---|---|---|
| ① | **`ws.binaryType = 'arraybuffer'`** | 기본값 `blob`이면 `.arrayBuffer()`가 비동기라 `sub.handler(envelope)`의 **동기 계약이 깨진다** |
| ② | `onMessage`를 **`typeof ev.data === 'string'`** 기준으로 텍스트/바이너리 2갈래 분기 | 텍스트는 지금 코드, 바이너리는 ③으로 |
| ③ | `[4B][JSON][페이로드]` 파서 | `DataView.getUint32(0)` → 헤더 → 나머지 슬라이스. 헤더 JSON 실패·길이 초과는 **카운터 + 상태 표시** |
| ④ | 디코드 — JPEG는 `createImageBitmap(new Blob([payload]))` + `drawImage`, **H.264는 WebCodecs `VideoDecoder`**(`codec` = 헤더의 `codec`, `description` 없음, `hardwareAcceleration: 'prefer-software'`) | 모르는 `encoding`은 디코드하지 않고 상태로 표시 |

**`catch { return }`에 최소한 카운터 하나를 붙여 달라** — 지금 구조에서는 형식이 틀려도 화면에 아무 신호가 없다.

**HW가 실기에서 고친 브라우저 결함 5건**(`pi/bench/go1_cam_view.py`, 464×400 H.264 실기) — 우리 확인용 뷰어(`backend/gateway/console.html`)에도 옮겨 적었다:

1. `hardwareAcceleration: 'prefer-software'` — 이 해상도에서는 소프트웨어 디코드가 밀리초대이고 하드웨어 경로가 오히려 늦는다.
2. **최신 프레임만 rAF 주기로** 그린다 — 디코더 출력을 전부 그리면 밀린다.
3. **보조 타이머** — 탭이 뒤로 가면 rAF가 멈춘다.
4. `desynchronized` 제거 — vsync 한 주기를 아끼려던 옵션이 오히려 찢김.
5. `Cache-Control: no-store` — 옛 JS를 캐시로 재사용.

**MJPEG 폴백 참조 구현도 HW에 이미 있다**(`go1_cam_view.py:172-` — WebCodecs 없는 브라우저로 자동 분기, 단 파이에서 H.264→MJPEG **완전 재인코딩**이라 대가가 크다). 우리 경로에서는 폴백이 아니라 **JPEG 소스(고정 CCTV)**가 그 자리다.

⚠ **서버가 못 지켜 주는 것 하나 — 뷰어 앱이 느릴 때.** 링크는 빠른데 브라우저가 디코드·렌더를 못 따라가면 초과분이 **브라우저·OS 수신 버퍼**에 쌓이고 서버 `send()`가 막히지 않아 **서버 drop-old가 발동하지 않는다**(Phase 4 실측: Windows 뷰어를 5초 정지시켜도 서버 드롭 0, 지연은 뷰어 안에서 5초). **뷰어가 자기 큐를 관리해야 한다** — 위 2번(최신 프레임만)과 `decodeQueueSize` 임계 재동기(HW `:499`)가 그것이다.

**답이 없으면:** 이 4단계 없이는 `/media`가 화면에 나오지 않는다 — 기본값이 없다.

---

<a id="s6"></a>

## §6 🔴 탐지 좌표·출처 선언 정합 — 이름이 아니라 타입·구조·값이 다르다

규격 초안: [`contracts/common/detections.schema.json`](../../contracts/common/detections.schema.json)(생산자 AI, 소비자 VZ — AI에는 [`ai-detections-interface.md`](ai-detections-interface.md)로 같은 것을 통지했다). ⚠ **초안이며 어떤 검증 경로도 아직 로드하지 않는다** — AI·VZ 회신 뒤 확정한다.

```json
{
  "type": "detections",
  "frame_ref": { "source_id": "go1-001_front", "capture_timestamp": "2026-09-18T12:00:00.123+09:00", "sequence_id": 4837 },
  "alignment": "frame",
  "origin": { "tier": "edge", "kind": "precise" },
  "coord": { "normalized": true, "origin": "top-left", "ref_width": 464, "ref_height": 400 },
  "boxes": [ { "x": 0.34, "y": 0.51, "w": 0.12, "h": 0.20, "label": "person", "confidence": 0.88 } ]
}
```

| # | 우리 | VZ(`vision.ts`) | 우리는 이렇게 읽었다 → 묻는 것 |
|---|---|---|---|
| ① | `coord{normalized(bool), origin, ref_width, ref_height}` | `bbox_space{format('normalized'\|'absolute'), origin, reference{width,height}}`(`:45-49`) | **4칸 중 2칸은 타입·구조까지 다르다**(`normalized` bool ↔ `format` 문자열 / `ref_*` 평면 ↔ `reference{}` 중첩). **어느 쪽 이름으로 맞출지 묻는다** — 우리는 VZ 이름(`bbox_space`·`format`·`reference`)으로 바꿀 용의가 있다(초안이라 비용이 0). **`normalized`는 VZ가 이미 지원한다**(`:277-278` `format === 'normalized'` 분기 + 전용 시나리오) — 기본값만 `absolute`라 **기본값 전환 요청** |
| ② | `origin: "top-left"` | `origin: 'top-left'`(`:47` 리터럴) | ⚠ **하이픈이다.** 우리 옛 문서 예시가 `top_left`(밑줄)였고 VZ 저장소에 `top_left`는 0건 — **우리 §1-6-2 예시를 하이픈으로 고쳤다**(이름이 아니라 값이 달랐다) |
| ③ | 메시지 단위 `origin{tier, kind}` | `DetectionOrigin{tier:'device'\|'edge', kind, label, optional}`(`:57-63`) | 🔴 **`tier`에 `server`를 추가해 달라.** 없으면 `FrameBuffer.pushDetection`(`:217-221`)이 `tier !== 'device' && tier !== 'edge'`로 **탐지를 통째로 드롭**한다. VZ 쪽은 `tier`가 타입·`Map` 키(`:209-210`)·`resolveAlignment` 루프 **세 곳**에 박혀 있어 나중에 넣으면 계약을 다시 바꿔야 한다(Phase 4 결정 11 — 서버 비전 소비자 자리). 3종이 실제 배치와 1:1이다 — `device`=pi7 온디바이스 / `edge`=엣지 노트북 / `server`=서버. `label`·`optional`은 VZ 표시용이라 우리 규격에 없다(있어도 통과) |
| ④ | 미디어 헤더 `width`·`height` | `VideoFrame.reference{width,height}`(`:40-41`) | **프레임에도 좌표 선언이 있다** — VZ 주석대로 탐지의 `bbox_space.reference`와 **같은 값을 공유해야** 겹쳐진다. **우리 미디어 헤더의 `width`/`height`가 그 자리다**([§1](#s1)) |
| ⑤ | `alignment`(string, 선택) | (없음) | **fail-safe 규칙(Phase 4 결정 3):** `alignment=="frame"`이고 `frame_ref`가 있을 때만 프레임 정합, **그 외(부재·모르는 값 포함) 전부 unaligned**로 그린다 — 최신 프레임 위에 참고 표시. 온디바이스(pi7) 결과는 엣지를 거치지 않아 `frame_ref` 시각 축이 다르므로 시각 근사 정합을 하지 않는다. VZ `resolveAlignment(buffer, aligned, frame)`(`:381`)의 `aligned` 인자가 이 값을 받는 자리로 보인다 |

**답이 없으면:** 우리 초안 이름 그대로 `payload/`로 올린다 — 그러면 VZ가 `coord`→`bbox_space` 변환을 자기 쪽에서 한다.

---

<a id="s7"></a>

## §7 인증 — URL 쿼리 토큰, 코드 변경 0

`/media`·`/state` 모두 **URL 쿼리 `token=`**으로 받는다. VZ-C-07이 주소를 통째로 화면에서 받으므로 **코드 변경이 없다** — 주소에 토큰을 붙여 입력하면 된다.

- **토큰은 화면에서 입력한다 — 코드·설정 파일·시나리오 JSON에 넣어 커밋하지 마라.** 값은 별도 경로로 전달.
- 불일치·부재는 **close 4401**, 경로 밖 4404, `source_id` 없음 4400. 재시도해도 같은 코드가 온다 — 재연결 루프에서 4401은 **재시도하지 않는다**.
- 서버 로그·관측 스택에 토큰은 `***`로만 찍힌다(실측 0건).
- RBAC(역할·범위)는 Phase 6 — 그때 `role` 메시지가 생긴다(지금 `WsTransport.ts:199`의 `role` 분기는 목 전용).

**답이 없으면:** 이대로.

---

<a id="s8"></a>

## §8 VZ 미결 §7.4·§7.5·§7.10에 대한 답 — 범위를 정직하게

| VZ 미결 | 답 |
|---|---|
| **§7.4** 미디어 뷰어 출력 분기·소유 파트 | **닫는다.** 출력 형식 = **WS 방식 B**, 소유 파트 = **백엔드 중계 / VZ 표시·오버레이**([`02-media-path.md`](02-media-path.md) §1-5-3). ⚠ 원문이 *"뷰어별로 원본 재생 능력에 의존하지 않고 공통 계약으로"*이고 후보로 WebRTC·HLS를 든다 — **우리 WS 방식 B는 뷰어가 디코더를 만들어야 한다.** 그 선택의 이유: `frame_ref`를 프레임과 **한 메시지로 원자적으로** 묶는 것이 오버레이 정합의 성립 조건이고, WebRTC·HLS는 메타를 따로 실어 재정합 드리프트가 돌아온다. **대가는 VZ가 디코드 경로를 만드는 것**이고, 그래서 [§5](#s5)의 4단계와 HW의 브라우저 결함 5건을 함께 전달한다 |
| **§7.5** MAC 라벨 정정 | 우리 [`contracts/common/README.md`](../../contracts/common/README.md) 「식별자 원칙」에 **이미 *"MAC·IP는 도달성 정보이며 정체성이 아니다"*로 적혀 있고**, 추적표 BE-T-05 행에 이번에 명시했다(HW에도 세 곳 정정 요청). ⚠ §7.5의 나머지 두 항목(선택형 인지 capability·신뢰도 축)은 답이 아니라 구현 과제다 — VZ가 이미 `DetectionOrigin{tier,kind,label,optional}`을 만들어 뒀으니 **우리가 그 필드를 관통시켜 주는 것**이 답이다([§6](#s6) ③) |
| **§7.10** 카메라 연결 상태 | ⚠ **축을 바꿔치기하지 않는다.** VZ가 물은 것은 **VZ-D-07 대상 상태 조회의 한 칸**(배터리·RSSI·지연·IP·펌웨어·관절 온도와 같은 줄)이고 상대는 **`Hardware` 계약**이다. 우리가 줄 수 있는 것은 [`02-media-path.md`](02-media-path.md) §1-5-4의 **미디어 스트림 staleness**(*"X ms간 새 프레임 없음"*, **도착 기준** — `capture_timestamp`가 아니라 뷰어의 마지막 도착 시각으로 판정한다)뿐이고 **이건 다른 축**이다. **카메라 하드웨어 연결 상태는 HW에 물어라** — 백엔드가 새 신호를 정의하지 않는다 |
| **`video_meta`** | 캐시 7종에 이미 들어 있다(VZ `protocol.ts:30`·`web-dashboard/README.md:381`). **Phase 4는 미디어 헤더 규격만 정하고 상태 채널 발행은 Phase 5로 이월한다** — 실체는 `source_id`별 `encoding`·`width`·`height`·`codec` + 마지막 도착 시각, 발행 시점은 엣지 첫 프레임·해상도 변경. VZ 주석대로 *"패널 열 때 fps·해상도 규격 판단"*은 그때부터 가능하고, 그전까지는 첫 프레임 헤더로 판단한다 |

---

<a id="s9"></a>

## §9 관측 회신(2026-09-17)에 대한 답

| VZ가 정한 것 / 물은 것 | 답 |
|---|---|
| ① 접두사 `vz.` | OK — 정의서 v1.3 정정 확인 |
| ② 발행 주기 **60초** + "HW 실제 주기 확인" | **60초 OK — 주기는 발신자 몫이고 Collector(batch 5s)는 어떤 주기든 받는다.** 🔴 **HW 주기 서술을 고친다:** 우리 통지 머리말이 *"HW `config.py`는 15초, 독스트링·HW-C-05는 60초(HW 코드 내부 불일치)"*라 적었는데 **HW 쪽에서 이미 종결됐다** — `BACKEND_AGENDA` §10-1 *"OTel export 주기 — 백엔드 값(15초) 채택으로 종결"*, `config.py:81` `OTEL_EXPORT_INTERVAL = 15.0`, **SRS §9.11이 정의서 HW-C-05 자체를 15초로 개정**했다. `otel_metrics.py` 독스트링이 갱신 안 된 잔재다. **즉 "HW-C-05가 60초니까"라는 근거는 HW 쪽에서 바뀌었고, 그래도 VZ 60초는 그대로 괜찮다** — VZ 회신이 *"HW가 실제로 15초라면 그때 다시 맞춘다"*는 조건을 달았으므로 이 사실을 흐리지 않고 적는다 |
| ③ 브라우저 발신 경로 — 4318 + CORS 개방 요청 | **A — Collector OTLP/HTTP 4318을 Tailscale IP에만 바인딩 + CORS + ufw `/32`**(Phase 4 결정 7). **인터넷 노출이 아니다** — 우리 통지 §4가 브라우저를 tailnet 밖으로 본 것이 틀렸다(VZ `presets.ts:10` *"관제 웹(노트북)·로봇(pi7)·탐지(데스크톱)가 전부 테일넷으로 붙는다"*). ⚠ **구현 시점은 [§10](#s10) ①②③을 받은 뒤다** — Phase 4에서는 4318을 열지 않았다(0건 변경). B(게이트웨이 중계)는 백엔드에 중계 코드가 늘고 C(답만)는 VZ가 막힌다 |
| ④ `service.name` = `vz-viewer`·`vz-stt`·`vz-gen` | OK. `service.namespace=mk2`. Unity 트윈 제외 OK |
| ⑤ 금지 라벨에 VZ 식별자 6종 추가 제안 | **8종을 반영했다**(`backend/observability.py FORBIDDEN_LABELS`·`contracts/common/README.md`·`tests/test_observability_labels.py` +13건): `frame_ref`·`correlation_id`(우리 통지가 "막는다"고 적었는데 코드에 없던 것을 맞췄다) + `mission_id`·`node_ref`·`client_request_id`·`plan_id`·`event_key`. **단 `node_id`만 뜻이 다르다** — 우리 공통 헤더 `node_id`는 **발행 물리 노드**(저카디널리티, 허용), VZ의 것은 **임무 DAG 노드**다. **VZ 코드에 `node_ref`라는 이름이 0건이고 와이어에 나가는 `node_id`는 전부 물리 노드**라, `node_ref`만 막으면 오늘 VZ가 내보내는 것 중 막히는 게 없다 → **DAG 노드 식별자는 `node_ref`라는 이름으로 내보내 주세요.** 「발화 원문」은 **실제 키 이름**을 받아야 넣는다([§10](#s10) ⑤) |
| 로그·트레이스 없이 지표만 | OK |
| 60초 창 집계는 이미 돌고 발행 상대만 비어 있다 | 알았다 — 발행 상대는 ③의 4318이며 [§10](#s10) 회신 뒤 연다 |

---

<a id="s10"></a>

## §10 🔴 우리에게 알려 줄 것 — 받기 전에는 VZ 입구를 열지 않는다

| # | 무엇 | 왜 | 답이 없으면 |
|---|---|---|---|
| ① | **관제 웹이 도는 기기의 tailnet 주소**(`tailscale ip -4` 출력). 기기가 여럿이면 전부, 시연 때 바뀌면 다시 | **8765(뷰어 WS)와 4318(관측 수집기) 두 입구의 ufw를 그 `/32`로 연다**(호스트 파이썬 8765는 ufw가 진짜 통제, 도커 4318은 바인딩 + ufw). tailnet 11대 중 어느 것이 관제 노트북인지 우리는 모른다(`laptop-isk6l1rq`가 후보) | 열지 않는다. VZ는 목 게이트웨이 유지 |
| ② | **Collector CORS 허용 origin**(관제 웹의 origin 문자열) + **브라우저가 쓸 OTLP exporter 종류**(protobuf / json) | Collector `otlp/http` receiver의 `cors.allowed_origins`와 preflight `allowed_headers`가 갈린다 | 4318을 열지 않는다 |
| ③ | **관제 웹을 https로 서빙하는가** | https 페이지에서 `http://<tailscale IP>:4318`로 보내면 브라우저가 **mixed content로 차단**한다. https라면 4318에 TLS가 필요하고 그건 결정 7의 범위를 넘는다(Phase 6) | http로 간주 |
| ④ | **실제 `source_id` 확인** — VZ가 회신에서 직접 물었다(*"목 레지스트리의 로봇 ID는 `robot-01`이다. 실제 Go1의 `source_id`가 무엇인지 알려 달라"*) | **답: 개체는 `go1-001`, 카메라를 붙이면 `go1-001_front`**(HW `hw-robot*.env.example`). VZ 목의 `robot-01`·`robot-01-cam`이 아니다. 목록은 레지스트리(Phase 5/6) | 화면 설정값으로 |
| ⑤ | **「발화 원문」 라벨의 실제 키 이름**(`utterance`? `transcript`?) | `FORBIDDEN_LABELS`는 문자열 집합이라 **이름 없이는 코드에 못 넣는다** | 나머지 8종만 막힌 상태 |

---

<a id="s11"></a>

## §11 우리 관측 통지 §4의 세 문장을 정정한다

그대로 두면 VZ가 **없는 경로로 발신 코드를 짠다.** [`vz-observability-namespace.md`](vz-observability-namespace.md) §4는 그대로 두고(받은 문서와의 대조를 위해) 여기서 개정 고지한다.

| 통지 §4 원문 | 정정 |
|---|---|
| *"HTTP 4318은 열려 있지 않다"* | **결정 7 A로 열린다** — Tailscale IP 바인딩 + CORS + ufw `/32`. 구현은 [§10](#s10) ①②③ 회신 뒤 |
| *"서버 밖이면 `<서버 tailscale IP>:4316`(TLS·인증은 BE-T-08)"* | 🔴 **두 군데가 바뀐다.** 브라우저는 **4316(gRPC)이 아니라 4318(HTTP)**이고, **TLS가 아니라 평문 + ufw `/32`**다. BE-T-08은 **엣지↔서버 터널**용 행이라 이 입구의 인증은 다른 행(Phase 6 BE-Q-04) |
| (`vz-stt`·`vz-gen`의 발신 주소가 비어 있다) | 이 둘은 브라우저가 아니라 **별도 프로세스**(Python·LLM 사이드카)라 gRPC를 쓸 수 있다 — **"브라우저는 4318(HTTP), `vz-stt`·`vz-gen`은 어디서 도는지(같은 노트북? 다른 기계?) 알려 주면 그 주소·프로토콜을 연다."** 셋이 다른 기계면 ufw `/32` 대상이 갈린다 |
| 「가시화가 할 일」 ④ *"Collector OTLP gRPC `127.0.0.1:4316`"* | 같은 이유로 **개정 고지** — 브라우저는 `http://<서버 tailscale IP>:4318`, 사이드카는 회신 뒤 |

---

<a id="s12"></a>

## §12 `target_entity_id`(개체)와 미디어 `source_id`(카메라)가 같은 이름으로 다른 축을 가리킨다

실행 기록 문의에서 우리가 *"`target_entity_id`는 레지스트리 개체 키 = 공통 헤더의 `source_id`"*라 적었고, VZ가 *"실제 Go1의 `source_id`를 알려 달라"*고 물었다. 그런데 미디어의 `source_id`는 **카메라 단위**(`go1-001_front`)다. **그대로 답하면 VZ가 `target_entity_id`에 카메라 키를 넣어 레지스트리 조인이 깨진다.**

→ **갈라서 적는다:** `target_entity_id`에는 **개체 키 `go1-001`**, `/media` 구독과 탐지 `frame_ref.source_id`에는 **카메라 키 `go1-001_front`**. [`frame-reference.schema.json`](../../contracts/common/frame-reference.schema.json)의 *「봉투의 source_id와 같은 식별 체계를 쓴다」*는 **체계가 같을 뿐 값이 같지 않다**는 뜻이다.

---

<a id="s13"></a>

## §13 `origin.kind`(탐지 정밀도)와 공통 헤더 `origin_kind`(실물/시뮬/재생)는 다른 축이다

VZ 회신이 *"VZ-C-06 원문은 실물·시뮬레이션·기록 재생 3종이고 우리 어휘는 `physical`·`simulation`·`replay`다. '가시화가 채운다'보다 「원천이 준 값을 옮긴다」로 읽어 달라"*고 정정했다. 두 축이 섞이지 않게:

| 축 | 어디 | 이름 | 어휘 | 누가 채우나 |
|---|---|---|---|---|
| **원천 종류** | 공통 헤더(봉투) | `origin_kind` | 우리 `real`·`simulation`·`replay`(VZ 표시 어휘 `physical`은 VZ가 대응) | **원천(생산자)**이 채운다. **백엔드는 중계분에 채우지 않는다**(HW에 이미 확정 통보 — 채우면 "안 보낸 것"과 "백엔드가 채운 것"을 구분할 수 없다). 미기재는 조회 시 `real`로 해석 |
| **탐지 출처·정밀도** | 탐지 메시지 | `origin{tier, kind}` | `tier` `device`·`edge`·`server` / `kind` `safety_minimal`·`precise` | 탐지 생산자(pi7·엣지·서버 비전) |

VZ `vision.ts:54-55` 주석(*"VZ-C-06의 원천 종류와 다른 축이다"*)이 이미 이 구분을 적어 두었다 — 같은 뜻이다.

---

<a id="s14"></a>

## §14 그 밖 — 캐시 10종 · `capture_timestamp` 뜻 · 촬영본 세 곳

- **캐시 정책 확인은 「금지 3종」이 아니라 10종 전체다.** 우리 [`00-architecture.md`](00-architecture.md) §7-4의 캐시 7(`state`·`telemetry`·`actuator_state`·`control_lock`·`plan`·`plan_progress`·`video_meta`) + 금지 3(`command_result`·`video_frame`·`detections`)은 **VZ `web-dashboard/README.md:381-382`·`gateway/server.ts:752`와 한 건도 어긋나지 않는다.** ⚠ VZ `config.ts`는 이후 5채널이 더해져 실제로 **8/10**이고 헤더 주석의 「7/3」은 낡은 숫자다 — *"VZ가 8종을 더 관리 중"*까지 적어 둔다. 캐시값 ts는 원래 발행 시각 유지.
- **`capture_timestamp`의 뜻:** **엣지가 프레임 경계를 확정한 시각**이다. 촬영 시각이 아니고 말단 내부 지연이 포함되며 보정되지 않았다. ISO date-time(콜론 오프셋 + 밀리초). 그래서 **스트림 staleness는 이 값이 아니라 도착 시각으로 판정한다**([§8](#s8) §7.10).
- **VZ도 `mission-history/images/robot/`에 영상 프레임을 따로 저장하고 있다** — 촬영본이 세 곳(pi 로컬·VZ·우리 4b 저장소)에 쌓이므로 **중복 정리를 Phase 5/6 안건으로 올렸다.** 단 VZ 쪽은 *"DB가 보관할 이력의 자리표시"*라 적혀 있어 "VZ가 하니 우리는 안 해도 된다"로 읽지 않는다.

---

<a id="todo"></a>

## 가시화가 할 일

1. 🔴 **`/state`는 건드리지 않는다** — 우리 8765의 `/media`만 **두 번째 소켓**으로 붙인다([§3](#s3)). 목 게이트웨이(8790)는 그대로.
2. 🔴 **바이너리 수신 4단계** — `binaryType='arraybuffer'` · 텍스트/바이너리 분기 · `[4B][JSON][페이로드]` 파서 · JPEG/H.264 디코드([§5](#s5)) + `catch{return}`에 카운터.
3. 🔴 **`frame_ref`를 객체로** — 버퍼 키 `(source_id, sequence_id)`, `frameLag`는 같은 소스 안 순번 차, 순번이 줄면 새 세션([§1](#s1)).
4. 🔴 **탐지 규격 정합 회신** — `coord`↔`bbox_space` 이름 선택 · `format` 기본값 `normalized` 전환 · **`origin.tier`에 `server` 추가** · `alignment` fail-safe([§6](#s6)).
5. 🔴 **[§10](#s10) 5개 회신** — tailnet 주소 · CORS origin·exporter 종류 · https 여부 · `source_id` 확인 · 「발화 원문」 키 이름. **①②③ 전에는 8765·4318 VZ 입구를 열지 않는다.**
6. 🟡 토큰은 화면 입력, 4401은 재시도 안 함([§7](#s7)). 관측 통지 §4 세 문장 개정 반영([§11](#s11)) — `vz-stt`·`vz-gen` 위치도 알려 달라.
7. 🟡 `target_entity_id`=개체 키, 미디어=카메라 키([§12](#s12)) · `origin.kind`≠`origin_kind`([§13](#s13)) · DAG 노드 식별자는 `node_ref` 이름으로([§9](#s9) ⑤).
8. ⚪ VZ-C-07 문면 재협상(게이트웨이 주소 하나, 소켓은 경로별 둘)([§3](#s3)) · 캐시 10종·`capture_timestamp` 뜻·촬영본 세 곳([§14](#s14))은 정보.

**답이 늦어도 백엔드는 멈추지 않는다.** `/media`는 합성 fixture와 우리 확인용 뷰어로 검증이 끝났고, VZ 뷰어가 붙는 시점에 바뀌는 것은 ufw `/32` 한 줄과 4318 바인딩뿐이다.
