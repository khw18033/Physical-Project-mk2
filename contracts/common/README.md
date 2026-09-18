# 공통 규격 (Common Contracts)

이 디렉터리는 파트(하드웨어·AI·가시화)가 나뉘는 지점을 통과하는 JSON 메시지의 기준이다.
**파트가 나뉘는 지점의 단일 기준은 각 파트의 내부 타입(Python dataclass·TypeScript type)이 아니라
여기 있는 JSON Schema다.** 각 파트는 언어별 타입을 독립적으로 유지하되, 이 스키마와 예제로
호환성을 검증한다. AI·하드웨어·가시화는 백엔드 내부 타입을 직접 import하거나 복사하지 않는다.

## 소유권

**공통 메시지 식별자·상관키·공통 헤더는 백엔드가 정의·유지한다.** 요구사항 근거:

- **BE-C-01** — 공통 메시지 스키마·필드 규약(백엔드 정의 → 전 파트 준수)
- **BE-C-02** — 식별자 계층(Entity/Node/Zone) 규약
- **BE-C-03** — 프레임 참조·시간 동기 규약
- **BE-C-07** — 원천 종류(실물·시뮬·기록재생) 표기 규약

AI 파트도 이 소유권을 전제한다 — AI-C-01: "AI가 생산·소비하는 데이터는 백엔드가 정의한 공통
식별·시간·버전 규약과 의미 체계를 따라야 한다." 따라서 이 규격을 기준으로 하고, 다른 파트의
공통 헤더 표현(예: AI 쪽 `contracts/ai/message.schema.json`, 가시화 Envelope)은 이 규격에
정렬한다.

## 파일

| 파일 | 무엇 | 근거 |
|---|---|---|
| `message.schema.json` | 모든 메시지의 공통 헤더(머리) | BE-C-01·BE-C-02·BE-C-07 |
| `frame-reference.schema.json` | 원본 관측 프레임 역추적 참조(frame_ref) | BE-C-03 |
| `object-reference.schema.json` | 구역을 넘어 유지되는 지속 객체 참조(object_id) | DT-06·AI-S-06 |
| `media-header.schema.json` | **미디어 경로(방식 B) 메시지의 JSON 헤더** — `frame_ref`(`$ref`)·`encoding`·`keyframe`·`width`·`height` (+선택 `codec`·`correlation_id`). 서버는 필수·타입만 검증하고 값 어휘를 보지 않으며 페이로드를 열지 않는다. **루트에 둔다** — `payload/`는 MQTT 토픽으로 고르는 채널 본문 자리다(**Phase 4 신설**) | BE-T-07·BE-C-03 |
| `detections.schema.json` | **탐지 결과 초안** — 생산자 AI, 소비자 가시화. 메시지 단위 `alignment`·`origin{tier,kind}`·`coord`·`boxes[]`. ⚠ **초안이며 어떤 검증 경로도 로드하지 않는다**(AI·VZ 회신 뒤 확정). 채널·토픽은 신설하지 않았으므로 역시 **루트**(**Phase 4 신설**) | BE-C-03·VZ-I-07 |
| `payload/state.{sensor,robot,actuator,analysis}.schema.json` | `state` 채널 본문 — **개체 타입마다 다르다** | BE-C-01 |
| `payload/status.schema.json` | `status` 채널 본문(등록·요약·종료·급사). 타입 공통 | BE-C-01·BE-T-04 |
| `payload/heartbeat.schema.json` | `heartbeat` 채널 — 본문 없음 | BE-C-01 |
| `examples/envelope-valid.json` | 공통 헤더를 통과하는 정상 메시지 예제 | 위 스키마 |
| `examples/envelope-valid-session.json` | 위와 같되 `session_id`가 실린 형태(규격 1.1) | 위 스키마 |
| `examples/payload-*.json` | 채널 본문 예제(양성·음성). **공통 헤더 + 본문이 합쳐진 완전한 메시지**다 — 검증이 메시지 단위로 이뤄지므로 본문만 담으면 돌릴 수 없다 | 위 스키마 |
| `examples/media-header-*.json` | 미디어 헤더 예제 — 양성 2(정상 · **모르는 `encoding`이 통과한다**) · 음성 4(`encoding` 누락 · `keyframe` 타입 · `frame_ref.capture_timestamp` `+0900` · `frame_ref` 안쪽 추가 필드). `tests/test_contract_media.py`가 돌린다 | `media-header.schema.json` |
| `examples/detections-draft-*.json` | 탐지 초안 예제 — `alignment` 있음/없음 둘 다 통과 | `detections.schema.json` |

**파일 간 `$ref`는 레지스트리로 해석한다(Phase 4 결정 12).** `media-header`·`object-reference`·`detections`가
`frame-reference.schema.json`을 `$ref`한다. 검증기(`backend/ingest/envelope.py`)는 이 디렉터리의 규격 전부를
`$id → 파일 내용`으로 `referencing.Registry`에 등록해 넘기며, **`$id`가 URL이어도 네트워크로 가져오지 않는다** —
등록에 없는 참조는 즉시 실패한다. Phase 7의 `object-reference` 검증 경로도 같은 레지스트리를 쓴다.

## 프레임 참조와 객체 참조 — 다른 축

`frame-reference.schema.json`과 `object-reference.schema.json`은 비슷해 보이지만 **서로 다른
축**이라 합치지 않는다. 프레임 참조는 **"무엇을 언제 찍었나"**(낱장 관측의 근거)이고, 객체 참조는
**"그 대상이 무엇인가"**(시간에 걸쳐 지속되는 정체성)다. 진나영 AI-S-06이 "지속 객체 레코드는
특정 프레임의 탐지 결과와 구분하여 관리"를 요구하는 근거가 이것이다 — 한 값으로 뭉치면 낱장
탐지와 지속 대상을 되짚어 구분할 수 없다.

**부여 주체가 나뉜다:**

- **구역 내 추적 식별자(`zone_local_track_id`) = AI가 부여.** 구역 안에서만 유일하다.
- **전역 객체 ID(`object_id`) = 백엔드가 부여·매핑.** 구역 경계를 넘어도 같은 대상을 가리킨다
  (DT-06 핸드오프). 구역마다 track 번호 체계가 독립이므로, 구역을 가로지르는 하나의 궤적
  (가시화 VZ-I-09)은 전역 ID 없이는 이어지지 않는다.

`frame_ref`는 엣지가 **프레임 경계를 확정하는 시점(액세스 유닛 재조립 또는 디코드)**에 한 번 부여해
전파할 뿐 백엔드·AI가 재생성하지 않는다는 규칙(BE-C-03)이 여기서도 그대로 유지된다. 말단(온디바이스)은
부여하지 않는다.

- **`capture_timestamp`의 뜻(2026-09-18 확정):** 엣지가 프레임 경계를 확정한 시각(도착)이며 **촬영 시각이
  아니다.** 말단 내부 지연이 포함되고 보정되지 않았다(크기 근거로만 HW 실측 1회 ≈0.3초 — 상수가 아니며
  규격값이 아니다). 형식은 **ISO date-time 문자열**이지 epoch ms 정수가 아니다(결정 2). 상관키
  (`correlation_id`)는 `frame_ref` 밖 — 공통 헤더·미디어 헤더에 둔다.
- **`additionalProperties: false` 예외:** 「payload에는 쓰지 않는다」(아래 「느슨한 2단」)는 **채널 본문
  규격**에 대한 규칙이다. `frame-reference`·`object-reference` 같은 **참조 규격**은 필드 집합이 닫혀 있어야
  정합(F==F 비교)이 성립하므로 예외다. 그래서 `media-header`·`detections`는 바깥에 필드를 더할 수 있지만
  `frame_ref` **안쪽**에는 더할 수 없다.

## 공통 헤더와 채널의 관계

`message.schema.json`은 **공통 헤더만** 정의한다 — 모든 메시지에 공통인 머리
(`schema_version` · `source_id` · `entity_id` · `node_id` · `zone_id` · `timestamp` ·
`sequence_id` · `session_id` · `correlation_id` · `origin_kind`).

채널별 본문(계측값 `water_level_m`, 탐지 `boxes`, 위험 `risk_state` 등)은 이 공통 헤더 위에
얹히며, 각 채널 payload 스키마에서 따로 정의한다. `examples/envelope-valid.json`이 공통 헤더 위에
채널 본문(`channel: "state"` + 계측 필드)이 얹힌 실제 모양을 보여준다.

- **필수 필드**: `schema_version` · `source_id` · `node_id` · `zone_id` · `timestamp`.
  이 다섯은 모든 메시지에 무조건 있어야 한다.
- **선택 필드**: `entity_id`(노드=개체가 1:1이면 생략) · `sequence_id`(연속 메시지에만) ·
  `session_id`(생산자 프로세스의 1회 기동. 없으면 소비자가 `status`의 `birth`로 폴백) ·
  `correlation_id`(명령 사슬에만) · `origin_kind`(미기재 시 실물로 간주).

## 값이 없을 때의 표현

생산자 구성은 배포마다 다르므로, 어떤 채널 본문의 일부 항목을 채우지 못한다. 예를 들어 어떤
배포에서는 한 부속 시스템이 a·b·d·e를 주고 c를 주지 않으며, 나중에 다른 센서가 붙으면 그때부터
c가 채워진다.

이 규칙의 목적은 하나다 — **소비자(트윈·로봇 제어·화면)가 생산자 구성 변화에 흔들리지 않게
하는 것.** 생산자 하나를 빼고 다른 것을 붙여도 소비자 코드가 그대로여야 한다.

### 규칙

1. **항목을 없애지 않고 명시적으로 `null`을 넣는다.**
   항목을 생략하면 소비자가 매번 키 존재를 확인해야 하고, **"아예 없는 항목"과 "지금 값이 없는
   것"을 구분할 수 없다.** 키 구조를 고정하면 생산자가 바뀌어도 소비자 코드가 그대로다.

2. **왜 없는지를 두 가지로 구분한다.**
   - `unsupported` — **이 배포 구성에 그 생산자가 없다.** 생산자가 추가되기 전까지 앞으로도
     값이 오지 않는다. 화면에 "해당 없음"으로 그린다.
   - `unavailable` — **있을 수 있는데 지금 값이 없다.** 생산자는 있으나 아직 보내지 못했거나
     실패했다. 화면에 "값 없음"으로 그리며, 장애 신호가 될 수 있다.

   이 둘을 하나로 뭉치면 화면이 **"아예 없는 항목"과 "일시 고장"을 똑같이 그린다.**

3. **구분이 필요한 항목만 상태를 함께 준다.**
   기본형은 `"c": null`이다. 부재 사유를 구분해야 하는 항목만 아래 형태를 쓴다.

   ```json
   { "c": { "value": null, "state": "unsupported" } }
   ```

   어느 항목이 어느 형태인지는 각 채널 본문 규격에서 정한다. 전부 상태를 달면 본문이
   불필요하게 무거워진다.

4. **값이 오래된 것은 여기서 다루지 않는다.**
   "값은 왔으나 낡았다"는 부재가 아니라 시의성 문제이며, 트윈 시의성 판정(DT-05)이 담당한다.
   여기서 `stale`을 만들지 않는다 — 두 곳에서 같은 판단을 하면 화면이 어긋난다.

### 적용 범위

이 규칙은 **채널 본문에만 적용된다.** 공통 헤더의 필수 5항목(`schema_version`·`source_id`·
`node_id`·`zone_id`·`timestamp`)은 언제나 존재해야 하며 `null`을 허용하지 않는다 — 없으면
수신 시 통과하지 못하고 걸러진다. 따라서 `message.schema.json`은 이 규칙 때문에 바뀌지 않는다.

### 확정된 항목 (2026-09-10, Phase 2)

**부재 사유를 구분하는 형태(`{value, state}`)를 쓰는 항목은 둘뿐이다.** 나머지는 전부
기본형(명시적 `null`)이다 — 전부 상태를 달면 본문이 불필요하게 무거워진다.

| 구분 필요 항목 | 왜 |
|---|---|
| `state`의 계측값 — `water_level_m`(sensor) · `battery_pct`(robot) | 센서 읽기가 실패하면 **발행 자체가 되지 않고**, 연속 실패하면 `device_status`가 `fault`가 된다. 화면은 "센서 없음"과 "센서 고장"을 달리 그려야 한다 |
| `status.registration` | LWT엔 원래 없다(`unsupported`) vs 있어야 하는데 없다(`unavailable`) |

> `status.buffer`는 **기본형으로 내렸다.** 공통 코어에서 항상 채워지고 빠지는 경우가 LWT
> 뿐이라 `registration`의 부재 사유와 중복이기 때문이다.

규격 파일에서는 해당 항목에 `x-mk2-absence: "stateful"` 표시가 붙어 있다. JSON Schema는
모르는 키워드를 무시하므로 검증에 영향이 없고, **어느 항목이 어느 형태인지를 규격이
알려주는 기계 판독 표시**로만 쓰인다 — 그래야 소비자 코드가 목록을 따로 들고 있지 않아도 된다.

**저장은 이 규칙의 적용 대상이 아니다.** 저장은 원본 그대로이며(저장 시점에 `null`을 채워
넣으면 저장된 것이 원본이 아니게 된다), 키를 채우는 것은 **읽기 함수**의 몫이다
(`backend/storage/normalize.py`의 `normalize_payload()`).

이 확정 내용은 생산자 파트(하드웨어)에 회신한다.

## 채널 본문 검증 — 느슨한 2단

수신 측은 `message.schema.json`(공통 헤더)을 먼저 보고, 그다음 채널 본문 스키마를 본다.
본문 스키마는 **MQTT 토픽으로 고른다** — 채널은 마지막 칸, 개체 타입은 2번째 칸이다.

세게 거는 곳과 느슨하게 두는 곳이 나뉘며, 그 경계마다 이유가 있다.

| 규칙 | 왜 |
|---|---|
| **필수 필드 누락은 격리한다** | 저장 층이 값의 존재를 가정할 수 있어야 한다 |
| **모르는 필드는 통과시킨다**(`additionalProperties: false`를 쓰지 않는다) | 생산자가 필드를 하나 추가하는 순간 전량 격리되는 사고를 만들지 않는다. 노드마다 다른 필드를 덧붙이는 훅이 있어 **필드가 느는 것이 정상 동작**이다 |
| **모르는 개체 타입은 검증을 건너뛰고 통과시킨다** | 새 노드 타입이 첫 메시지부터 격리되면 파이프라인이 그 자리에서 막힌다 |
| **본문의 `channel` 필드는 검증하지 않는다** | 라우팅은 토픽 기준이다. 증강 분석이 토픽 `state`에 본문 `channel: "analysis"`를 보내고 있어 일치를 강제하면 가동 중인 생산자가 전량 격리된다. 불일치는 기록만 한다 |
| **값 어휘(`reason`·`device_status` 등)를 `enum`으로 고정하지 않는다** | 같은 이유다. 관측된 어휘는 각 스키마의 `$comment`에 적어 두고, 확정·확장 여부는 생산자 파트 회신으로 닫는다 |

## 관측 신호 힌트와 라벨 금지

각 본문 항목의 `$comment`에 **관측 신호 종류 힌트**(`관측 신호 힌트: <종류>`)를 달아 두었다. 업무 값의
관측 표현(관측 3층의 C층)을 만들 때 **어떤 항목을 어떤 종류로 낼지는 규격 파일이 정한다** —
`backend/contracts.py::observation_hints()`가 `$comment`를 읽어 목록을 만들고, 파이썬에 목록을 다시 적지
않는다(두 벌이 되면 조용히 어긋난다). **아래 표는 그 결과의 사본이지 기준이 아니다.**

**전수(2026-09-16, 규격 6종):** 힌트가 붙은 곳 **27**(sensor 4 · robot 5 · actuator 6 · analysis 4 · status 8 ·
heartbeat 0), 항목 이름으로 중복(`reason` ×3 · `device_status` ×4)을 접으면 **gauge 9 · counter 3 ·
log/event 10 = 22**. `tests/test_c_layer_extract.py`가 이 숫자를 못 박는다.

| 종류 | 해당 항목 (전수) | Phase 3 처리 |
|---|---|---|
| gauge(연속 수치) **9** | `water_level_m` · `battery_pct` · `speed_mps` · `progress` · `value` · `trend_m_per_min` · `eta_to_threshold_min` · `uptime_s` · `buffer.pending` | ✅ 계측 — `be.telemetry.<항목>` (`state.analysis`의 셋만 `be.telemetry.analysis.<항목>`) |
| counter(사건 횟수) **3** | `buffer.dropped` · `buffer.thinned` · `publish_failures` | ✅ 계측 — 단 **gauge 계기로**(말단이 보내는 절대 누적값이라 델타를 만들려면 상태를 들어야 한다 — 무상태 원칙). 이름에 `_total`을 붙이지 않고, 증가분은 조회에서 `delta()`/`deriv()` |
| log/event(사건 서술) **10** | `reason` · `device_status` · `alert` · `robot_mode` · `actuator_state` · `feedback_ok` · `control_locked` · `above_threshold` · `event` · `status` | ⏭ **Phase 5 이월** — 전부 상태 어휘라 "언제 바뀌었나" 판정이 가용성의 일이고, 지금 그대로 내면 로봇 1대당 초당 60줄이 Loki로 간다 |

> 이전 판의 표는 부분 목록이었다(gauge 7·log/event 9 — `eta_to_threshold_min`·`buffer.pending`·`status`가 빠짐).
> 규격 파일이 기준이므로 표가 규격을 못 따라간 것이며, 그래서 코드가 표가 아니라 파일을 읽는다.

**값이 없으면 기록하지 않는다.** `{"value": null, "state": "…"}`·명시적 `null`·부재(LWT의 `buffer`)는 시계열을
만들지 않는다 — 0을 넣으면 "값 없음"이 "0"이 된다.

**라벨은 값의 종류가 한정된 것만 쓴다.** 그리고 **층에 따라 기준이 다르다**(Phase 3 결정 4-b):

| 층 | 라벨 | 이유 |
|---|---|---|
| **A층** 백엔드 자기 관측(`be.ingest.*`·`be.kafka.*`·`be.storage.*`·`be.registry.*`·`be.gateway.*`·`be.pipeline.*`) | `component` · `channel` · `outcome` · `stage` · `endpoint`(Phase 3 추가 — `/state`·`/media` 구분) — **`source_id`·`zone_id`·`entity_type`을 넣지 않는다** | 질문이 "백엔드가 잘 도는가"라 장치별로 가를 필요가 없고, 달면 장치 수만큼 시계열이 곱해진다 |
| **C층** 업무 값의 관측 표현(`be.telemetry.*`) | `source_id` · `zone_id` · `entity_type` · `channel` | 장치별이어야 의미가 있다 |

> ⛔ **어느 층에도 넣지 않는다 — 금지 라벨 전수(2026-09-18, Phase 4 확장):**
>
> | 묶음 | 라벨 | 왜 |
> |---|---|---|
> | 기존 7종(Phase 3) | `session_id` · `internal_seq` · `sequence_id` · 시각(`timestamp`·`ts`·`capture_timestamp`) · `frame_id` | 값이 계속 달라진다. 특히 `session_id`는 **재기동마다 새 값**이라 노드를 껐다 켤 때마다 시계열이 하나씩 영구히 는다 |
> | **Phase 4 확장 8종(확정)** | `frame_ref` · `correlation_id` · `command_id` · `mission_id` · `node_ref` · `client_request_id` · `plan_id` · `event_key` | 프레임·명령·임무·판마다 다르다. 앞의 셋은 VZ 통지(`docs/be/vz-observability-namespace.md` §2)가 "막는다"고 적었는데 코드에 없던 것을 맞췄고, 뒤의 다섯은 VZ 회신(2026-09-17)이 제안한 VZ 식별자다. `command_id`·`correlation_id`는 trace 속성으로는 되지만 metric 라벨로는 안 된다 |
> | **9번째 — 자리만(대기)** | 발화 원문(잠정 `utterance`·`transcript`) | VZ가 제안했으나 **실제 키 이름을 아직 받지 못했다**(`docs/be/vz-media-interface.md` 10⑤ 문의). `FORBIDDEN_LABELS`는 문자열 집합이라 이름 없이 넣을 수 없다 — 빠진 것이 아니라 대기다 |
>
> ⚠ **`node_id`는 넣지 않는다.** VZ의 `node_id`는 DAG 노드 뜻이지만 우리 공통 헤더 `node_id`는 물리 노드
> (pi1·pi7)라 저카디널리티·허용이다. DAG 노드 식별자는 `node_ref`라는 이름으로 내보내 달라고 VZ에 요청했다.
>
> 백엔드 어댑터(`backend/observability.py` `FORBIDDEN_LABELS`)는 이 목록을 **`ValueError`로 막는다** — 조용히
> 버리지 않는다(`tests/test_observability_labels.py`가 전 항목을 parametrize로 돌린다).

## 식별자 원칙 (BE-C-02)

장치·이동체·구역을 **IP·MAC 같은 가변값이 아니라 논리 식별자 계층**으로 참조한다.

- **Entity(개체)** — `entity_id`. 논리 대상. 로봇 한 노드가 여러 개체를 대리할 수 있다.
- **Node(물리 노드)** — `node_id`. 실행 노드. 물리 노드 레지스트리에 연결.
- **Zone(구역)** — `zone_id`. 권한·라우팅·범위(scope)의 기준.

네트워크 주소(IP·MAC)는 도달성 정보이며 개체 정체성이 아니다. 공통 헤더에 IP·MAC·broker topic을
논리 식별자 대신 넣지 않는다. (device_id↔MAC/IP 매핑은 백엔드 레지스트리·라우팅의 내부 관심사
이며 공통 헤더 규격에 포함하지 않는다. `source_id`가 기준이고 device_id 별칭은 규격에서
제외한다 — 생산자는 source_id 단일 필드로 정렬한다.)

## 버전 정책

**현재 규격 버전: `1.1`** (2026-09-10). 이력:

| 버전 | 변경 | 왜 이 자리인가 |
|---|---|---|
| `1.0` | 최초 공통 헤더 | — |
| `1.1` | **선택 필드 `session_id` 추가** | 구버전 소비자가 깨지지 않는 추가라 MINOR. `sequence_id`가 재기동 시 리셋되므로 순번 열의 경계를 가를 값이 필요하다(BE-S-01) |

> **혼재 기간이 정상이다.** `schema_version` 정규식은 형식만 보므로 `"1.0"`을 보내는
> 생산자도 계속 통과한다. 하드웨어는 아직 `session_id`를 보내지 않으며, 그동안 소비자는
> `status`의 `birth`를 경계로 폴백한다. **버전이 올랐다고 옛 생산자를 격리하지 않는다.**

- 기존 필드의 의미·타입 변경은 `schema_version`의 MAJOR 또는 MINOR를 올린다.
- 선택 필드는 누락 대신 명시적 `null`을 쓸 수 있으나, 공통 헤더 선택 필드는 아예 생략도 허용한다
  (required가 아니므로). 채널 본문의 누락 표현은 위 "값이 없을 때의 표현"에서 정한 규칙에 따른다.
- 새로운 채널은 payload 스키마·예제·검증을 함께 추가한다.
- 실제 브로커 topic 문자열, 저장소 제품, 전송 기술은 이 규격에 포함하지 않는다 — 배포 adapter가
  결정한다(BE-C-05: 계약 축 {entity, node, channel}은 프로토콜 문자열이 아니다).

## 검증

각 파트는 수신 시 `message.schema.json`을 먼저 검증하고, `channel`에 따라 payload 스키마를
선택한다. 검증 실패 메시지는 정상 topic으로 재발행하지 말고 격리·기록한다(백엔드 수신 규약).
`examples/envelope-valid.json`이 회귀 검증의 기준 fixture다.
