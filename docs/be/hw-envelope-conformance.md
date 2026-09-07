# HW 봉투 정합 인계 — `BACKEND_AGENDA` §1·§2 백엔드 회신

| | |
|---|---|
| 보내는 쪽 | 백엔드(BE·DT) / 이대규 |
| 받는 쪽 | 하드웨어(HW) / 조병현 |
| 작성일 | 2026-09-07 |
| 근거 | Phase 1(얇은 파이프라인 관통) 구현·검증 결과, `contracts/common/message.schema.json` |
| 대상 질문 | `docs/BACKEND_AGENDA.md`(HW 브랜치) **§1 스키마 필드 확정**, **§2 토픽 도메인 체계** |

이 문서는 두 안건에 대한 **회신**이다. §1은 HW 코드 변경 4줄을 요청하고, §2는 대부분 정보성
(HW는 MQTT만 발행하므로 코드 변경 없음)이다.

**이 회신은 탁상 검토가 아니라 실측 결과다.** 아래 편집 4개를 적용한 `sensor_node`를 백엔드
파이프라인(MQTT → 봉투 검증 → Kafka → 저장 sink → WebSocket)에 붙여 약 13분간 실제로 흘렸고,
`state`·`status`·`heartbeat` 3채널이 전 구간을 관통하며 **검증 격리 0건**을 확인했다(§4).

---

## §1 회신 — 스키마 필드 확정

### 1-1. 요청: `pi/common/schema.py` 편집 4개

이 파일 하나만 고치면 전 노드에 반영된다(HW가 어댑터를 한 곳에 모아둔 설계 그대로다).

**① 순번 필드명 `seq` → `sequence_id`**

```python
# before
    if seq is not None:
        env["seq"] = seq
# after
    if seq is not None:
        env["sequence_id"] = seq
```

계약(`contracts/common/message.schema.json`)의 필드명이 `sequence_id`다. 이름이 다르면 백엔드는
그 필드를 **없는 것으로 취급**한다 — 오류가 나지 않고 순번 추적만 조용히 죽으므로 발견이 늦다.
`envelope(seq=...)` **인자 이름은 그대로 두었다** — 호출부(`node.py`·`analyzer.py`)는 무변경이다.

**② timestamp를 RFC3339 콜론 오프셋으로**

```python
# before
import time
def iso_now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")
# after
from datetime import datetime, timezone
def iso_now():
    # 로컬 타임존 aware → 콜론 있는 오프셋(+09:00). RFC3339/계약 date-time 정합.
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
```

**이것이 4개 중 가장 중요하다.** `strftime("%z")`는 `+0900`을 내는데 계약의 `date-time` 포맷은
`+09:00`을 요구한다. 백엔드는 수신 즉시 포맷까지 실제로 검증하며(fail-closed), **불합격 메시지는
정상 토픽으로 재발행하지 않고 격리**한다. 즉 이 편집 전에는 **모든 메시지가 전량 격리**된다
(백엔드 음성 테스트에서 실제로 거부되는 것을 확인했다).

> 부수 효과: `schema.py`에서 `time` 모듈 사용처가 사라진다(`import time`을 지워도 되고 남겨도
> 무해하다). 편집 전후 모두 `time.` 사용을 전수 확인했다.

**③ `device_id` 별칭 제거**

```python
LEGACY_DEVICE_ID = True   →   LEGACY_DEVICE_ID = False
```

§1.1의 "`source_id` 단일화 시점"에 대한 답이다 — **지금 확정한다.** 계약은 `source_id`를 정본으로
하고 `device_id` 별칭을 포함하지 않는다. 별칭이 계속 나가면 대역·저장이 낭비되고, 파서가 어느
쪽을 정본으로 볼지 모호해진다(HW가 지적한 그대로다).

**④ 봉투 계약 버전을 계약값으로**

```python
SCHEMA_VERSION = "1.3"   →   SCHEMA_VERSION = "1.0"
```

`1.3`은 드리프트다. 이 필드는 **봉투 계약의 버전**이지 펌웨어 버전이 아니다(펌웨어는
`fw_version`으로 이미 별도로 싣고 있다). 계약 현재 버전은 `1.0`이다.

### 1-2. `schema_version` 표기 규칙 (§1.2 "semver? 정수?"에 대한 답)

**`MAJOR.MINOR` 형식의 문자열**이다. 현재 값은 `"1.0"`.

- 스키마 정규식: `^[0-9]+\.[0-9]+$` — 정수 단독(`1`)도, PATCH 포함 semver(`1.0.0`)도 거부된다.
- 올리는 기준: **기존 필드의 의미·타입이 바뀌면** MAJOR 또는 MINOR를 올린다. 선택 필드 추가처럼
  구버전 소비자가 깨지지 않는 변경은 MINOR.
- 소유·발급은 백엔드다. HW는 계약이 올라갈 때 이 상수만 따라 바꾸면 된다.

### 1-3. `seq`(→`sequence_id`) 범위 (§1.3 "채널별 독립 순번 vs 전역"에 대한 답)

**현재의 채널별 독립 순번을 그대로 수용한다. HW는 바꾸지 않아도 된다.**

실측에서 확인된 현재 동작이다(같은 시각의 한 노드):

| 채널 | 순번 | 근거 |
|---|---|---|
| `heartbeat` | 12 | `BaseNode.hb_seq` |
| `state` | 1 | `BaseNode.seq` |
| `status`·LWT | **없음** | `envelope(identity)`를 순번 없이 호출 |

Phase 1은 이 값을 **실어 나르기만** 한다. 유실·역전 검출의 정확한 의미(채널별로 볼지, 소스별로
합칠지, 재기동 시 리셋 규칙을 어떻게 둘지)는 **백엔드 Phase 2(저장 2축)에서 확정**해 다시
회신한다. 그때 필요한 변경이 생기면 상수·설정 수준이지 구조 변경은 아닐 것으로 본다.

`status`에 순번이 없는 것은 정상으로 받아들인다 — 봉투 필수 5필드
(`schema_version`·`source_id`·`node_id`·`zone_id`·`timestamp`)만 있으면 통과한다.

### 1-4. `device_id` 제거의 내부 영향 — HW 브랜치 전수 확인 결과

편집 ③이 HW 내부 소비자를 깨뜨리는지 백엔드가 코드로 확인했다. **둘 다 안전하다.**

| 위치 | 코드 | 판정 |
|---|---|---|
| `pi/edge/monitor.py:56` | `payload.get("source_id") or payload.get("device_id") or topic.split("/")[2]` | ✅ `source_id` 우선 |
| `pi/augment/analyzer.py:92` | `p.get("source_id") or p.get("device_id") or msg.topic.split("/")[2]` | ✅ `source_id` 우선 |

그 밖의 `device_id` 검출은 봉투와 무관하다 — protobuf 명령의 `Capability.device_id`,
`/etc/device_id` 파일 경로, 중복 채번 경보 문구.

**요청:** 위 2곳 외에 봉투의 `device_id`를 직접 읽는 소비자(대시보드·스크립트·노트북 코드 등)가
있으면 `source_id`로 갱신해 달라. 백엔드가 볼 수 있는 범위(HW 브랜치 `*.py`·`*.js`·`*.html`)
에서는 위 2곳이 전부였다.

**`seq` 이름 변경도 안전하다:** HW 전체에서 **봉투의 `seq` 필드를 읽는 소비자가 없다.** 검출된
`seq`는 전부 RTP 시퀀스 번호(미디어 경로, 무관)이거나 `envelope(seq=...)` 호출 인자였다.

---

## §2 회신 — 토픽 도메인 체계

HW는 MQTT만 발행하므로 **§2는 코드 변경이 없다.** 확인과 정보 전달이다.

### 2-1. `{domain}` 자리에 구역(zoneA) — 그대로 유지

현재 구조 `{zone}/{etype}/{eid}/{channel}`을 **확정으로 받는다.** 백엔드 ingest는 이 구조를 전제로
구독한다.

### 2-2. `{type}`(etype) 어휘 — `sensor / robot / actuator / analysis` 확인

이 넷을 그대로 쓴다. 백엔드는 **etype에 무관하게** 잡도록 구독하므로(§2-3), 어휘가 늘어도 백엔드
코드는 바뀌지 않는다.

### 2-3. 채널 이름 — 텔레메트리 3채널은 **한 칸을 더 쓰지 않는다**

백엔드 ingest의 구독 패턴은 정확히 셋이다:

```
+/+/+/state      +/+/+/status      +/+/+/heartbeat
```

MQTT의 `+`는 **한 계층만** 대응하므로 이 패턴은 **정확히 4칸인 토픽만** 잡는다. 따라서:

- `zoneA/sensor/wl-001/state` → 잡힌다.
- `zoneA/analysis/wl-001/state`(증강 분석) → **같은 경로로 잡힌다.** 백엔드 코드 변경 없음.
- `terminal/wl-001/downlink`(명령, 3칸) → **패턴에 안 맞아 배달 자체가 되지 않는다.**

§2.3의 걱정("`cmd/ack`처럼 한 칸 더 들어가는 채널이 와일드카드 구독에 영향")은 **소멸했다.**
명령 경로가 `common/physical_command.py`의 규약(`terminal/<device_id>/downlink|uplink` +
protobuf)으로 이동해 구 JSON `cmd/*` 채널이 폐기됐기 때문이다. 텔레메트리 평면과 명령 평면이
토픽 형태부터 분리되어, 백엔드는 명령을 **구독하지 않는 것으로** 격리한다.

**따라서 요청한다: 텔레메트리 채널은 4칸 구조를 유지하고, 계층을 더 파지 말아 달라.** 새 채널이
필요하면 백엔드에 먼저 알려 달라 — 채널이 늘면 Kafka 토픽과 저장 경로가 함께 생겨야 한다.

### 2-4. MQTT → Kafka 매핑 (§2.4에 대한 답)

**원본 미러가 아니다.** 채널별로 3개의 Kafka 토픽에 싣는다.

| MQTT 토픽 | Kafka 토픽 | 파티션 키 |
|---|---|---|
| `{zone}/{etype}/{eid}/state` | `mk2.telemetry.state` | `source_id` |
| `{zone}/{etype}/{eid}/status` | `mk2.telemetry.status` | `source_id` |
| `{zone}/{etype}/{eid}/heartbeat` | `mk2.telemetry.heartbeat` | `source_id` |

- **장치별·구역별 토픽을 만들지 않는다.** `zone_id`·`source_id`는 이미 봉투 안에 있고, 토픽에는
  **데이터의 성격(채널)만** 담는다. 구역·장치가 늘어도 토픽 수가 늘지 않는다.
- **파티션 키가 `source_id`**라 한 장치의 메시지는 항상 같은 파티션에 들어간다 → **장치별 순서가
  보장**된다. 이것이 `source_id`를 필수로 두는 실용적 이유다.
- **값은 HW가 보낸 JSON 바이트 그대로** 싣는다. 백엔드는 재직렬화하지 않는다(필드 순서·수치
  표현이 원본 그대로 보존된다).
- 이름은 점 구분 소문자이며 **언더스코어를 섞지 않는다**(Kafka 메트릭 이름 변환 충돌 회피).

**HW 코드 변경은 필요 없다.** 이 매핑은 백엔드 내부 규약이다.

---

## §3 백엔드 수신 규약 — HW가 알아두면 좋은 것

1. **수신 즉시 봉투를 strict 검증한다(포맷 포함).** 필수 5필드와 `date-time` 형식을 실제로
   assert한다. 전환기·관용 모드는 없다.
2. **불합격은 정상 토픽으로 재발행하지 않는다.** 사유·원문·수신시각과 함께 격리 파일에 남는다.
   즉 **형식이 틀리면 조용히 통과하는 대신 조용히 사라진다** — 그래서 편집 ②가 중요하다.
3. **채널 본문(payload)은 아직 검증하지 않는다.** 봉투만 본다. `water_level_m` 같은 본문 필드의
   스키마는 채널별로 따로 만들 때 다시 알린다. 지금은 본문에 무엇이 있든 통과한다.
4. **retained `status`를 그대로 받는다.** 백엔드가 구독을 걸면 브로커가 마지막 retained `status`
   1건을 즉시 밀어주며, 이는 다른 메시지와 똑같이 처리된다.
5. **Phase 1은 가용성을 판정하지 않는다.** `status`(birth/summary/shutdown)와 LWT(death),
   `heartbeat`를 **흘려보내기만** 한다. 최종 가용성 판정은 백엔드 단일 지점에서 하며(Phase 5),
   그때 엣지의 1차 판정(`pi/edge/monitor.py`·`edge/availability.py`)과의 관계를 정리해 회신한다
   (`BACKEND_AGENDA §10-2`·§5 관련).

---

## §4 검증 결과 — 이 회신의 근거

편집 4개를 적용한 `sensor_node`(로컬 사본)를 **개발 PC에서 실행**해 **서버 Mosquitto로 발행**하고,
서버의 백엔드 파이프라인으로 관통시켰다. 실제 배치(말단=엣지 쪽, 브로커=서버)와 같은 방향이다.

| 항목 | 결과 |
|---|---|
| 관통 경로 | 노드(PC) → MQTT → ingest 봉투 검증 → Kafka 3토픽 → 저장 sink + WebSocket push |
| 채널 | `state`(60초)·`status`(10초)·`heartbeat`(5초) **3채널 전부 도달** |
| 지속 | 약 13분 (heartbeat 순번 1→163 **연속, 유실 0**) |
| **봉투 검증 격리** | **0건** — 4편집 적용 후 단 한 건도 거부되지 않았다 |
| 실제 봉투 | `{"schema_version":"1.0","source_id":"wl-001","node_id":"DESKTOP-...","zone_id":"zoneA","timestamp":"2026-09-07T21:29:25+09:00","sequence_id":159,"channel":"heartbeat"}` |
| 버퍼(HW-R-09) | 접속 완료 전 첫 계측이 spool에 적재됐다가 접속 후 재전송되는 것을 확인 |
| 명령 경로 | `terminal/wl-001/*`는 백엔드가 구독하지 않아 무해하게 무시됨 |

`node_id`는 `/etc/node_id`가 없어 hostname으로 채워졌다(설계된 폴백). 실배포에서는 `/etc/node_id`
또는 `HW_NODE_ID`로 지정하면 된다.

---

## §5 아직 회신하지 않은 안건 (처리 Phase 명시)

`BACKEND_AGENDA`의 나머지는 Phase 1 범위 밖이며, 아래 시점에 회신한다. **잊은 것이 아니라 그
Phase의 작업 항목으로 등록해 두었다.**

| 안건 | 회신 시점 |
|---|---|
| §8 frame_ref — 봉투 `timestamp`(ISO)와 frame_ref(epoch ms) 공존이 의도냐 | **Phase 4(미디어)**. 백엔드 `frame-reference.schema.json`이 ISO 문자열로 정의돼 있어 v8 §6-9(epoch ms)와 어긋난다 — 어느 쪽으로 정합할지 그때 확정 |
| §5 `device_status` 발행 주체 (HW 자기보고 수용 vs metric 파생) | **Phase 5(가용성)** |
| §10-2 엣지 파생 `up` ↔ 백엔드 최종 판정의 관계 | **Phase 5(가용성)** |
| §3 명령 문자열 파라미터(`set_mode(mode="normal")`가 `map<string,double>`로 불가) | **Phase 6(명령)** |
| §7 4단계 stage 값 확인 | **Phase 6(명령)** |
| §10-3 traceparent 전달 계획 | **Phase 3(관측)** 이후 |

---

## 요약 — HW가 할 일

1. `pi/common/schema.py`의 **편집 4개** 적용(위 §1-1 그대로).
2. 봉투의 `device_id`를 직접 읽는 소비자가 `monitor.py`·`analyzer.py` 외에 있으면 `source_id`로
   갱신(둘은 이미 안전).
3. 그 외 **코드 변경 없음** — 토픽 구조·채널·주기 전부 현행 유지.
