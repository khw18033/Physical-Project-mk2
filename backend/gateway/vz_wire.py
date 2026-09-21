"""VZ 와이어 어댑터 — 우리 봉투를 가시화 계약(`{type:'data', sub, envelope}`)으로 옮긴다. **소켓을 모른다.**

⚠ **실측대비를 위해 임시로 구현한 것이다**(2026-09-21). 정식 상태 채널 계약 — `hello`·`subscribed`·
**구독 즉시 캐시 1회 푸시(VZ-I-02 / BE-T-06)**·명령 경로 — 는 **Phase 5/7 그대로 남는다.** 여기서는
「업무 데이터가 뷰어까지 도달한다」를 이번 실측에서 보이는 데 필요한 **최소**만 만든다.
(성격상 Phase 5 의 절반을 미리 만드는 것이라 버려지는 코드는 거의 없다 — 실측준비 v2 §3-1-1.)

## 왜 필요한가

VZ 수신부(`viz-debugger/src/transport/WsTransport.ts`)는 받은 JSON 의 `type` 으로 분기하는데,
우리 `/state` 가 내보내는 `{channel, topic, key, message}` 에는 **`type` 이 없다** → `default: return`
으로 **전량 버려진다.** 연결은 되고 화면만 빈다.

VZ 가 실제로 소비하는 것은 `case 'data'` 하나뿐이다:

    case 'data': {
      const sub = this.subs.get(msg.sub);   // sub 는 VZ 가 붙인 구독 ID('sub-1' …)
      if (!sub) return;                     // 못 찾으면 그냥 버린다
      sub.handler(msg.envelope);
    }

`msg.sub` 가 **VZ 가 자기 안에서 만든 ID** 라, 서버가 그것을 알려면 **VZ 가 보내는 구독 메시지를
읽어야** 한다. 그 자리가 `ws_echo.py::state_session` 이고, 이 모듈은 그 뒤의 **매칭과 변환**만 한다.

✅ **`subscribed`·`unsubscribed` 는 만들지 않는다** — VZ `switch` 에 **처리 가지 자체가 없어서**
보내도 무시된다. `hello` 도 없어도 깨지지 않는다(표시용 두 값이 비어 있을 뿐이다).

## 이 모듈이 소켓을 모르는 이유

`media.py` 와 같은 구조다 — 매칭·변환이 **딕셔너리만으로** 단위 검증돼야 한다. 구독표 관리·전송·
이중 형식 분기는 `ws_echo.py` 가 감싼다. 그래서 이 파일은 **표준 라이브러리만 쓴다**(kafka·websockets
없이 시험이 돈다).

## 🔴 이 모듈은 예외를 던지지 않는다

`to_vz_envelope()` 는 `_broadcast` 루프 안에서 불린다. 거기서 `KeyError` 가 나면 **그 뒤의 모든
클라이언트에게 전송이 끊긴다.** 봉투 필수 5필드는 브릿지의 2단 검증을 통과한 것이라 있어야 정상이지만,
Kafka 에 무엇이 들어 있든 **변환은 성공해야 한다.** 그래서 전부 `.get()` 이고 폴백이 있다.

## 잠정값 셋 — 진짜 값이 아니다

백엔드가 판정해야 하는 값인데 판정기가 아직 없다. 실측 뒤 화면이 이 셋으로 판단을 내리고 있으면
그 자리를 먼저 맞춘다(실측준비 v2 §3-3).

- `quality="good"` — 진짜 판정은 **Phase 5 가용성**이다. `"unknown"` 을 주면 화면이 전부 회색으로 떠
  관통 판정이 흐려진다.
- `aggregation="raw"` — 집약을 하지 않으니 정직한 값이다.
- `coordinate_frame=None` — 로봇 `state` 에 위치(`position`)가 실리므로 **엄밀히는 정확하지 않다**
  (BE-C-04 좌표계가 아직 정의되지 않았다). VZ 에 「지금 null 로 보낸다」를 알렸다.

implements: BE-T-03 (가시화 클라이언트 실시간 채널 게이트웨이 — 실측대비 최소 어댑터)
tests: tests/test_vz_wire.py — 매칭 표 전수 · 변환 11칸 · 음성 대조(필드가 빠져도 죽지 않는다)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ── 어휘 ────────────────────────────────────────────────────────────────────

WILDCARD = "*"

#: VZ `Channel` 타입에 있는 것만 내보낸다.
#: 우리 채널 셋(`state`·`status`·`heartbeat`) 중 **`status` 는 VZ 어휘에 없다** — 보내면 화면이
#: 무엇을 할지 계약에 없으므로 이번 실측에서는 거른다(실측준비 v2 §3-1-1 변환 표).
#: VZ 가 `status` 를 받기로 하면 여기 한 줄을 더한다.
VZ_CHANNELS = frozenset({"state", "heartbeat"})

#: 잠정값 셋 — Phase 5 에서 진짜 판정이 생기면 **여기부터** 지운다.
PROVISIONAL_QUALITY = "good"
PROVISIONAL_AGGREGATION = "raw"
PROVISIONAL_COORDINATE_FRAME = None

#: 구독 요청에 `scope` 가 없을 때 되돌려줄 값(VZ-I-11 — 현 단계 'all' 고정).
DEFAULT_SCOPE = "all"


# ── 축 값 뽑기 ──────────────────────────────────────────────────────────────

def _as_str(value: Any) -> Optional[str]:
    """비교 가능한 문자열로. 숫자·None 등은 매칭 후보에서 뺀다(`str(None)=='None'` 같은 사고 방지)."""
    return value if isinstance(value, str) and value else None


def entity_of(message: Dict[str, Any]) -> Optional[str]:
    """개체 키.

    `entity_id` 는 **선택 필드**다 — 센서처럼 노드=개체가 1:1 이면 생략되고 그때는 `source_id` 가
    개체를 가리킨다(`message.schema.json`). 그래서 `entity_id` → `source_id` 순으로 본다.

    ⚠ 미디어의 `source_id`(카메라 키 `go1-001_front`)와 **다른 축이다.** 여기 오는 것은 업무 봉투의
    `source_id`(개체 키 `go1-001`)다 — 같은 식별 체계, 다른 값(vz-media-interface.md §12).
    """
    return _as_str(message.get("entity_id")) or _as_str(message.get("source_id"))


def _axis_ok(want: Any, candidates: List[Optional[str]]) -> bool:
    """한 축의 매칭. `None`·`'*'` 는 와일드카드다.

    선택자에 축이 아예 없으면 와일드카드로 본다 — VZ 는 셋을 다 보내지만, 없는 축 때문에 조용히
    0건이 되는 쪽보다 넓게 받는 쪽이 진단하기 낫다.
    """
    if want is None or want == WILDCARD:
        return True
    if not isinstance(want, str):
        return False
    return want in [c for c in candidates if c is not None]


# ── 매칭 ────────────────────────────────────────────────────────────────────

def selector_matches(selector: Any, message: Dict[str, Any], channel: str) -> bool:
    """VZ 계약 축 `{entity, node, channel}` 매칭.

    VZ 가 실제로 보내는 것은 `{entity: '*', node: <구역>, channel: '*'}`(`src/tabs/data/index.ts`)와
    `{entity: <개체>, node: '*', channel: '*'}`(`src/tabs/data/vision.ts`) 둘이다.

    🔴 **`node` 축은 둘을 받는다.** VZ 주석이 *"node 축에 zone 식별자를 주면 그 zone 의 모든 node 에
    매칭된다"* 로 적혀 있다 — **백엔드가 동의한 적 없는 규약이지만 이번엔 그대로 받는다.** 이 조건이
    없으면 VZ 가 `node: 'zoneA'` 로 구독할 때 우리 `node_id`(`pi7` 등)와 안 맞아 **매칭이 0건**이 되고,
    연결은 되는데 화면만 비는 가장 진단하기 나쁜 실패가 된다. 규약의 정식화는 실측 뒤 VZ 와 정한다.

    깨진 선택자(딕셔너리가 아님)는 **매칭하지 않는다** — 전량 푸시로 물러서지 않는다.
    """
    if channel not in VZ_CHANNELS:
        return False
    if not isinstance(selector, dict):
        return False
    if not _axis_ok(selector.get("channel"), [channel]):
        return False
    if not _axis_ok(selector.get("entity"), [entity_of(message)]):
        return False
    # ↓ 물리 노드와 구역 둘 다 후보다(위 🔴).
    return _axis_ok(selector.get("node"), [_as_str(message.get("node_id")), _as_str(message.get("zone_id"))])


# ── 변환 ────────────────────────────────────────────────────────────────────

def to_vz_envelope(channel: str, message: Dict[str, Any], scope: Any = DEFAULT_SCOPE) -> Dict[str, Any]:
    """우리 봉투 → VZ `Envelope` 11칸. **절대 예외를 던지지 않는다**(모듈 독스트링 🔴).

    | VZ 칸 | 우리 값 | 비고 |
    |---|---|---|
    | `zone` | `zone_id` | 없으면 `None`(VZ 타입이 `string \\| null`) |
    | `node` | `node_id` | |
    | `entity` | `entity_id` → `source_id` | `entity_of()` |
    | `channel` | Kafka 토픽 마지막 칸 | `VZ_CHANNELS` 로 이미 걸렀다 |
    | `ts` | `timestamp` | ⚠ VZ 정의는 *"서버 시각"* 인데 우리 값은 **생산 시각**이다. 실측엔 지장 없고 Phase 5 에서 정리 |
    | `seq` | `sequence_id` | **선택 필드**라 없으면 0 |
    | `payload` | `message` **통째로** | 봉투 칸을 걷어내지 않는다 — 걷어내면 VZ 화면이 무엇을 읽는지 몰라 빈 화면이 날 수 있다 |
    | `quality` | 잠정 `"good"` | |
    | `aggregation` | 잠정 `"raw"` | |
    | `scope` | 구독 요청의 값을 **되돌려준다** | |
    | `coordinate_frame` | 잠정 `None` | |
    """
    seq = message.get("sequence_id")
    if isinstance(seq, bool) or not isinstance(seq, int):   # bool 은 int 의 하위형이라 먼저 뺀다
        seq = 0

    return {
        "zone": _as_str(message.get("zone_id")),
        "node": _as_str(message.get("node_id")) or "",
        "entity": entity_of(message) or "",
        "channel": channel,
        "ts": _as_str(message.get("timestamp")) or "",
        "seq": seq,
        "payload": message,
        "quality": PROVISIONAL_QUALITY,
        "aggregation": PROVISIONAL_AGGREGATION,
        "scope": scope if scope is not None else DEFAULT_SCOPE,
        "coordinate_frame": PROVISIONAL_COORDINATE_FRAME,
    }


def data_message(sub_id: str, channel: str, message: Dict[str, Any], scope: Any = DEFAULT_SCOPE) -> Dict[str, Any]:
    """VZ 가 소비하는 한 가지 모양 — `{type:'data', sub, envelope}`."""
    return {"type": "data", "sub": sub_id, "envelope": to_vz_envelope(channel, message, scope)}


# ── 구독표 ──────────────────────────────────────────────────────────────────

def apply_subscription(subs: Dict[str, Dict[str, Any]], msg: Any) -> Optional[str]:
    """VZ 가 보낸 제어 메시지 한 건을 구독표에 반영한다. 반영했으면 그 종류를, 아니면 `None`.

    받는 것은 둘뿐이다(`gateway/protocol.ts` 의 클라이언트→서버 메시지 중):
      - `{type:'subscribe',   id, selector, scope}`
      - `{type:'unsubscribe', id}`

    그 밖(`role`·`command`·`video`·`ping`·`scenario`·`plan_decision`)은 **Phase 5/6** 이라 무시한다.
    VZ 목 게이트웨이용 `video{entity, open}` 도 여기로 올 수 있는데 **무해하다**(결정 4-b — 연결이 곧 켜기).
    """
    if not isinstance(msg, dict):
        return None
    kind = msg.get("type")
    sub_id = msg.get("id")
    if not isinstance(sub_id, str) or not sub_id:
        return None
    if kind == "subscribe":
        # 🔴 선택자를 **정규화하지 않는다.** 깨진 값을 `{}` 로 바꾸면 그것이 와일드카드가 되어
        #    구독 계약이 깨졌는데 **전량 푸시**가 된다. 받은 그대로 두고 `selector_matches()` 가
        #    0건으로 막는다 — 판정을 한 곳에만 둔다.
        subs[sub_id] = {"selector": msg.get("selector"), "scope": msg.get("scope", DEFAULT_SCOPE)}
        return "subscribe"
    if kind == "unsubscribe":
        return "unsubscribe" if subs.pop(sub_id, None) is not None else None
    return None
