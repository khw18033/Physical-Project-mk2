"""VZ 와이어 어댑터 — 계약 축 매칭 · 봉투 변환 11칸 · 구독표.

소켓 없이 딕셔너리만으로 돈다(`backend/gateway/vz_wire.py` 는 소켓을 모른다). **음성 대조가 본체다** —
구역 식별자가 어긋나면 **0건**이고(연결은 되고 화면만 비는 실패의 원인), `status` 는 VZ 어휘에 없어
걸리며, 봉투 필드가 통째로 빠져도 변환은 **죽지 않는다**(`_broadcast` 루프를 끊으면 그 뒤 모든
클라이언트에게 전송이 멈춘다).

implements: BE-T-03 (가시화 실시간 채널 — 실측대비 최소 어댑터)
tests: 매칭 양성 5 + 음성 5 · 변환 11칸 · 견고성 3 · 잠정값 고정 · 구독표 4
"""

from __future__ import annotations

import pytest

from backend.gateway import vz_wire

# 실제 로봇 상태 봉투(`contracts/common/examples/payload-state-robot-valid.json` 모양)
ROBOT = {
    "schema_version": "1.1", "source_id": "go1-001", "entity_id": "go1-001",
    "node_id": "pi7", "zone_id": "zoneA", "timestamp": "2026-09-21T09:00:00+09:00",
    "sequence_id": 4837, "channel": "state", "reason": "periodic",
    "battery_pct": 87.5, "position": {"x": 12.34, "y": -3.5, "heading_deg": 91.2},
    "robot_mode": "mission", "device_status": "ok",
}

# 센서 봉투 — `entity_id` 가 없다(노드=개체 1:1 이면 선택 필드라 생략된다)
SENSOR = {
    "schema_version": "1.1", "source_id": "wl-001", "node_id": "pi7", "zone_id": "zoneA",
    "timestamp": "2026-09-21T09:00:30+09:00", "sequence_id": 12, "channel": "state",
    "water_level_m": 2.53, "unit": "m",
}

# VZ 가 실제로 보내는 선택자 둘
VZ_DATA_LAYER = {"entity": "*", "node": "zoneA", "channel": "*"}      # src/tabs/data/index.ts:60
VZ_VISION = {"entity": "go1-001", "node": "*", "channel": "*"}        # src/tabs/data/vision.ts:441


# ── 매칭 — 양성 ─────────────────────────────────────────────────────────────

def test_vz_데이터레이어_선택자가_로봇과_센서_둘다_잡는다():
    """`{entity:'*', node:'zoneA', channel:'*'}` — 구역 안 전부."""
    assert vz_wire.selector_matches(VZ_DATA_LAYER, ROBOT, "state")
    assert vz_wire.selector_matches(VZ_DATA_LAYER, SENSOR, "state")
    assert vz_wire.selector_matches(VZ_DATA_LAYER, ROBOT, "heartbeat")


def test_vz_비전_선택자는_그_개체만_잡는다():
    assert vz_wire.selector_matches(VZ_VISION, ROBOT, "state")
    assert not vz_wire.selector_matches(VZ_VISION, SENSOR, "state")


def test_node_축에_물리_노드를_넣어도_잡는다():
    """구역(위 규약)뿐 아니라 실제 `node_id` 로도 좁힐 수 있어야 한다."""
    assert vz_wire.selector_matches({"entity": "*", "node": "pi7", "channel": "*"}, ROBOT, "state")


def test_채널_축을_좁힐_수_있다():
    sel = {"entity": "*", "node": "*", "channel": "heartbeat"}
    assert vz_wire.selector_matches(sel, ROBOT, "heartbeat")
    assert not vz_wire.selector_matches(sel, ROBOT, "state")


def test_축이_빠지면_와일드카드로_본다():
    """없는 축 때문에 조용히 0건이 되는 쪽보다 넓게 받는 쪽이 진단하기 낫다."""
    assert vz_wire.selector_matches({}, ROBOT, "state")
    assert vz_wire.selector_matches({"node": None}, ROBOT, "state")


# ── 매칭 — 음성 (본체) ──────────────────────────────────────────────────────

def test_구역_식별자가_어긋나면_0건이다():
    """🔴 VZ 기본 상수가 `zone-503` 이고 우리 값은 `zoneA` 다.

    그대로면 **연결은 되고 화면만 빈다** — 실측에서 제일 먼저 의심할 자리라 시험으로 못 박는다.
    """
    sel = {"entity": "*", "node": "zone-503", "channel": "*"}
    assert not vz_wire.selector_matches(sel, ROBOT, "state")
    assert not vz_wire.selector_matches(sel, SENSOR, "state")


def test_status_채널은_걸러진다():
    """VZ `Channel` 타입에 `status` 가 없다 — 보내면 화면이 무엇을 할지 계약에 없다."""
    assert not vz_wire.selector_matches(VZ_DATA_LAYER, ROBOT, "status")
    # 와일드카드 선택자라도 채널 자체가 어휘 밖이면 막힌다
    assert not vz_wire.selector_matches({"entity": "*", "node": "*", "channel": "*"}, ROBOT, "status")


def test_모르는_채널도_걸러진다():
    assert not vz_wire.selector_matches(VZ_DATA_LAYER, ROBOT, "detections")


def test_깨진_선택자는_매칭하지_않는다():
    """전량 푸시로 물러서지 않는다 — 구독 계약이 깨졌는데 데이터를 쏟으면 원인이 묻힌다."""
    for broken in (None, "zoneA", 3, [], ["entity", "*"]):
        assert not vz_wire.selector_matches(broken, ROBOT, "state")


def test_축_값이_문자열이_아니면_매칭하지_않는다():
    assert not vz_wire.selector_matches({"entity": 1, "node": "*", "channel": "*"}, ROBOT, "state")


# ── 개체 키 ─────────────────────────────────────────────────────────────────

def test_entity_id가_있으면_그것을_없으면_source_id를_쓴다():
    assert vz_wire.entity_of(ROBOT) == "go1-001"
    assert vz_wire.entity_of(SENSOR) == "wl-001"          # entity_id 없음 → source_id
    assert vz_wire.entity_of({"entity_id": "", "source_id": "wl-001"}) == "wl-001"   # 빈 문자열도 폴백
    assert vz_wire.entity_of({}) is None


# ── 변환 ────────────────────────────────────────────────────────────────────

def test_봉투_11칸이_전부_채워진다():
    env = vz_wire.to_vz_envelope("state", ROBOT, scope="all")
    assert set(env) == {
        "zone", "node", "entity", "channel", "ts", "seq",
        "payload", "quality", "aggregation", "scope", "coordinate_frame",
    }
    assert env["zone"] == "zoneA"
    assert env["node"] == "pi7"
    assert env["entity"] == "go1-001"
    assert env["channel"] == "state"
    assert env["ts"] == "2026-09-21T09:00:00+09:00"
    assert env["seq"] == 4837
    assert env["scope"] == "all"


def test_payload는_봉투를_통째로_싣는다():
    """봉투 칸을 걷어내지 않는다 — 걷어내면 VZ 화면이 무엇을 읽는지 몰라 빈 화면이 날 수 있다."""
    env = vz_wire.to_vz_envelope("state", ROBOT)
    assert env["payload"] is ROBOT
    assert env["payload"]["battery_pct"] == 87.5
    assert env["payload"]["position"]["heading_deg"] == 91.2


def test_구독_요청의_scope를_되돌려준다():
    assert vz_wire.to_vz_envelope("state", ROBOT, scope="all")["scope"] == "all"
    assert vz_wire.to_vz_envelope("state", ROBOT, scope={"zones": ["zoneA"]})["scope"] == {"zones": ["zoneA"]}
    assert vz_wire.to_vz_envelope("state", ROBOT, scope=None)["scope"] == vz_wire.DEFAULT_SCOPE


# ── 변환 — 견고성 (🔴 예외를 던지면 그 뒤 모든 클라이언트 전송이 끊긴다) ──────

def test_빈_봉투로도_죽지_않는다():
    env = vz_wire.to_vz_envelope("state", {})
    assert env["zone"] is None          # VZ 타입이 `string | null`
    assert env["node"] == ""
    assert env["entity"] == ""
    assert env["ts"] == ""
    assert env["seq"] == 0
    assert env["payload"] == {}


def test_순번이_없거나_이상해도_0으로_간다():
    """`sequence_id` 는 선택 필드다. `bool` 은 `int` 의 하위형이라 따로 막는다."""
    assert vz_wire.to_vz_envelope("state", {})["seq"] == 0
    assert vz_wire.to_vz_envelope("state", {"sequence_id": None})["seq"] == 0
    assert vz_wire.to_vz_envelope("state", {"sequence_id": "4837"})["seq"] == 0
    assert vz_wire.to_vz_envelope("state", {"sequence_id": True})["seq"] == 0
    assert vz_wire.to_vz_envelope("state", {"sequence_id": 0})["seq"] == 0
    assert vz_wire.to_vz_envelope("state", {"sequence_id": 7})["seq"] == 7


def test_타입이_어긋난_값은_빈_값으로_떨어진다():
    env = vz_wire.to_vz_envelope("state", {"zone_id": 5, "node_id": None, "timestamp": 12345})
    assert env["zone"] is None and env["node"] == "" and env["ts"] == ""


# ── 잠정값 — Phase 5 에서 바뀔 자리를 못 박는다 ─────────────────────────────

def test_잠정값_셋이_문서와_같다():
    """진짜 값이 아니다. 바뀌면 vz-media-interface.md·실측준비 v2 §3-1-1 도 같이 고쳐야 한다."""
    env = vz_wire.to_vz_envelope("state", ROBOT)
    assert env["quality"] == "good"                  # 진짜 판정은 Phase 5 가용성
    assert env["aggregation"] == "raw"               # 집약을 하지 않는다
    assert env["coordinate_frame"] is None           # BE-C-04 좌표계 미정의


# ── VZ 가 받는 한 가지 모양 ─────────────────────────────────────────────────

def test_data_메시지_모양():
    """VZ `case 'data'` 가 `msg.sub` 로 자기 구독을 찾고 `msg.envelope` 를 핸들러에 넘긴다."""
    msg = vz_wire.data_message("sub-1", "state", ROBOT, scope="all")
    assert msg["type"] == "data"
    assert msg["sub"] == "sub-1"
    assert msg["envelope"]["entity"] == "go1-001"


# ── 구독표 ──────────────────────────────────────────────────────────────────

def test_구독과_해제가_반영된다():
    subs = {}
    assert vz_wire.apply_subscription(subs, {
        "type": "subscribe", "id": "sub-1", "selector": VZ_DATA_LAYER, "scope": "all",
    }) == "subscribe"
    assert subs["sub-1"]["selector"] == VZ_DATA_LAYER
    assert subs["sub-1"]["scope"] == "all"

    assert vz_wire.apply_subscription(subs, {"type": "unsubscribe", "id": "sub-1"}) == "unsubscribe"
    assert subs == {}


def test_없는_구독을_해제하면_아무_일도_없다():
    subs = {}
    assert vz_wire.apply_subscription(subs, {"type": "unsubscribe", "id": "sub-9"}) is None
    assert subs == {}


def test_scope가_없으면_기본값으로_넣는다():
    subs = {}
    vz_wire.apply_subscription(subs, {"type": "subscribe", "id": "sub-1", "selector": VZ_DATA_LAYER})
    assert subs["sub-1"]["scope"] == vz_wire.DEFAULT_SCOPE


def test_그_밖의_메시지는_무시한다():
    """`role`·`command`·`video`·`ping` 은 Phase 5/6 이다. VZ 목의 `video{entity,open}` 도 무해하다."""
    subs = {}
    for msg in (
        {"type": "role"},
        {"type": "video", "entity": "go1-001", "open": True},
        {"type": "ping", "t": 1},
        {"type": "subscribe"},                       # id 없음
        {"type": "subscribe", "id": ""},             # 빈 id
        None, "subscribe", 7, [],
    ):
        assert vz_wire.apply_subscription(subs, msg) is None
    assert subs == {}


def test_선택자가_깨져도_구독은_받되_매칭은_0건이다():
    """🔴 구독 자체를 거부하면 VZ 는 이유를 모른다 — 받아 두고 **매칭에서** 막는다.

    그리고 깨진 선택자를 `{}` 로 정규화하지 않는다. `{}` 는 와일드카드라 **전량 푸시**가 되기
    때문이다 — 구독 계약이 깨졌는데 데이터를 쏟으면 원인이 묻힌다.
    """
    subs = {}
    vz_wire.apply_subscription(subs, {"type": "subscribe", "id": "sub-1", "selector": "zoneA"})
    assert subs["sub-1"]["selector"] == "zoneA"                                  # 받은 그대로 둔다
    assert not vz_wire.selector_matches(subs["sub-1"]["selector"], ROBOT, "state")

    # selector 키가 아예 없는 경우도 같다 — 0건이지 전량이 아니다
    vz_wire.apply_subscription(subs, {"type": "subscribe", "id": "sub-2"})
    assert not vz_wire.selector_matches(subs["sub-2"]["selector"], ROBOT, "state")
