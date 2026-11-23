"""공통 규격에 맞춘 발행 스크립트 (테스트 헬퍼 겸 수동 확인용).

**발행 위치는 컴퓨터다.** 발행자는 MQTT만 쏘고 Kafka를 모르므로, 컴퓨터에서 실행해 서버
Mosquitto로 발행한다 — 실제 배치(발행자=말단/엣지, 브로커=서버)와 같은 방향이라 발행자↔브로커
네트워크 경로까지 함께 검증된다. 그래서 이 파일은 `paho-mqtt`와 표준 라이브러리만 쓴다
(백엔드 패키지·Kafka 의존 없음).

브로커 주소는 하드코딩하지 않고 `backend/settings.py`의 환경변수 표를 그대로 참조한다:
`MK2_BROKER_HOST`(기본 `210.110.250.33`), `MK2_BROKER_PORT`(기본 `1883`). `settings`는
표준 라이브러리만 쓰므로, 이 파일을 컴퓨터에서 돌릴 때 필요한 것은 여전히 `paho-mqtt`뿐이다.

**구독이 먼저, 발행이 나중** — ingest 로그에 `READY` 가 뜬 뒤에 발행한다. 클린 세션 ingest는
구독 전에 발행된 메시지를 받지 못한다.

---

## 이 발행자가 지키는 원칙 셋

1. **본문은 하드웨어 소스를 그대로 베낀다.** 규격 문서의 요약표가 아니라
   `sensor_node.py`·`robot_node.py`·`actuator_node.py`·`analyzer.py`의 실제
   `payload.update({...})`가 근거다. 표는 요약이고 소스가 근거다.
2. **실노드가 안 보내는 것을 기본으로 보내지 않는다.** `entity_id`·`origin_kind`는 실노드
   봉투에 없다 — 기본을 실노드에 맞추고 옵션으로만 켠다. 안 그러면 "가짜로는 통과하는데
   실물에서는 항상 NULL"인 칼럼을 못 잡는다.
3. **증강 분석 형식은 그 결함까지 그대로 재현한다.** 토픽 끝은 `state`인데 본문 `channel`은
   `analysis`이고, `device_status`·`reason`이 없으며, `mac`·`ip`가 빈 문자열이다.
   **결함을 고쳐서 흉내 내면 그 결함을 막는 테스트가 실제로는 아무것도 검증하지 못한다.**

수동 실행:
    python tests/publisher.py                                  # zoneA/sensor/wl-001/state 로 1건
    python tests/publisher.py --etype robot --channel state     # 로봇 본문
    python tests/publisher.py --etype analysis                  # 증강 분석 형식(결함 포함)
    python tests/publisher.py --channel status --event death     # LWT(급사) 형식
    python tests/publisher.py --channel heartbeat --count 5
    python tests/publisher.py --timestamp -420                   # 7분 전 시각으로(지연 도착)
    python tests/publisher.py --timestamp +30                    # 30초 미래(음수 lag → clock_skew)
    python tests/publisher.py --replayed                         # 재전송 표식
    python tests/publisher.py --no-session-id                    # birth 폴백 경로
    python tests/publisher.py --seq 1 --seq-step 1 --count 5      # 순번 열 만들기
    python tests/publisher.py --etype analysis --channel status --blank-mac-ip   # 빈 mac/ip 주입
    python tests/publisher.py --water-level-state unavailable    # {value:null,state} 형태(C층 시계열 미생성 음성, Phase 3)
    python tests/publisher.py --invalid missing-zone             # 격리 확인용(음성)

implements: BE-C-01, BE-T-01
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import paho.mqtt.publish as mqtt_publish

# 저장소를 그대로 복사해 쓰는 배치에서도 `backend.settings`를 찾도록(설치 없이 실행 가능).
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend import settings  # noqa: E402  (위 sys.path 보정 뒤에 import)

DEFAULT_ZONE = "zoneA"
DEFAULT_ETYPE = "sensor"
DEFAULT_EID = "wl-001"
DEFAULT_NODE_ID = "pi7"

ETYPES = ("sensor", "robot", "actuator", "analysis")
CHANNELS = ("state", "status", "heartbeat")
STATUS_EVENTS = ("birth", "summary", "rebirth", "shutdown", "death")

# 공통 헤더 규격의 현재 버전. `session_id`가 선택 필드로 추가되며 1.1로 올랐다.
# 이 발행자는 1.1을 구현하므로 그대로 선언한다 — 하드웨어는 아직 "1.0"을 보내고 있고,
# 정규식이 형식만 보므로 둘 다 통과한다(혼재 기간이 정상이다).
SCHEMA_VERSION = "1.1"

# 생산자 프로세스의 1회 기동 식별자. **모듈 전역이라 프로세스당 한 번만 생성**되고
# 파일에 저장하지 않으므로, 다시 띄우면 반드시 달라진다 — 그것이 이 값의 목적이다.
# HW에 요청할 구현(`pi/common/schema.py`의 모듈 전역 `SESSION_ID`)과 같은 방식이다.
SESSION_ID = uuid.uuid4().hex[:12]

# 실노드 registration()이 싣는 값들의 발행자 쪽 대응값.
DEVICE_TYPE_BY_ETYPE = {
    "sensor": "water_level",
    "robot": "quadruped",
    "actuator": "gate",
    "analysis": "analysis",
}
FW_VERSION = "0.3.0"
SAMPLE_MAC = "b8:27:eb:aa:bb:cc"
SAMPLE_IP = "192.168.50.31"

EXAMPLES_DIR = settings.contracts_dir() / "examples"
INVALID_FIXTURES = {
    # 공통 헤더(1단)에서 걸리는 것
    "missing-zone": EXAMPLES_DIR / "envelope-invalid-missing-zone.json",
    "timestamp": EXAMPLES_DIR / "envelope-invalid-timestamp.json",
    # 채널 본문(2단)에서 걸리는 것 — 공통 헤더는 통과하고 본문에서 거부된다
    "payload-missing-device-status": EXAMPLES_DIR / "payload-state-robot-invalid-missing-device-status.json",
}
# 음성 fixture를 어느 토픽으로 쏴야 의도한 검증기가 걸리는지.
INVALID_ETYPE = {"payload-missing-device-status": "robot"}


def broker_host() -> str:
    return settings.broker_host()


def broker_port() -> int:
    return settings.broker_port()


def iso_now() -> str:
    """RFC3339 콜론 오프셋(+09:00). 규격의 date-time 포맷 정합."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def resolve_timestamp(spec: Optional[str]) -> str:
    """`--timestamp` 값을 ISO-8601 문자열로 바꾼다.

    두 형태를 받는다:

    - **상대 초**(`-420`, `+30`) — 지금으로부터의 오프셋. **지연 도착과 음수 lag를 만드는
      수단**이 지금까지 없었다. 과거 시각으로 발행하면 저장 층이 원래 자리에 꽂는지 볼 수
      있고, 미래 시각으로 발행하면 `lag_s`가 음수가 되어 `clock_skew` 경로를 탄다.
    - **ISO-8601 문자열** — 그대로 쓴다.
    """
    if spec is None:
        return iso_now()
    text = spec.strip()
    if text and (text[0] in "+-" or text.replace(".", "", 1).isdigit()):
        try:
            offset = float(text)
        except ValueError:
            return text
        moment = datetime.now(timezone.utc) + timedelta(seconds=offset)
        return moment.astimezone().isoformat(timespec="seconds")
    return text


def unique_source_id(prefix: str = "wl-test") -> str:
    """테스트 간 교차 수신을 막기 위한 1회용 논리 식별자."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def topic_for(channel: str, zone: str = DEFAULT_ZONE, etype: str = DEFAULT_ETYPE, eid: str = DEFAULT_EID) -> str:
    """HW 토픽 구조 `{zone}/{etype}/{eid}/{channel}`.

    ⚠ 증강 분석도 **토픽 마지막 칸은 `state`**다(`{zone}/analysis/{eid}/state`) — 본문
    `channel`만 `analysis`다. 그 불일치가 실물이며 여기서 고치지 않는다.
    """
    return f"{zone}/{etype}/{eid}/{channel}"


# ── 봉투 ────────────────────────────────────────────────────────────────────


def make_envelope(
    source_id: str = DEFAULT_EID,
    node_id: str = DEFAULT_NODE_ID,
    zone_id: str = DEFAULT_ZONE,
    *,
    sequence_id: Optional[int] = None,
    session_id: Optional[str] = SESSION_ID,
    timestamp: Optional[str] = None,
    entity_id: Optional[str] = None,
    origin_kind: Optional[str] = None,
    schema_version: str = SCHEMA_VERSION,
) -> Dict[str, Any]:
    """공통 헤더. **기본 필드 집합을 실노드에 맞춘다.**

    실노드 `envelope()`가 싣는 것은 `schema_version`·`source_id`·`node_id`·`zone_id`·
    `timestamp`와 선택적 `sequence_id`·`correlation_id`뿐이다. `entity_id`·`origin_kind`는
    **없다** — 기본으로 보내면 "가짜로는 채워지는데 실물에서는 항상 NULL"인 칼럼을 못 잡는다.
    """
    envelope: Dict[str, Any] = {
        "schema_version": schema_version,
        "source_id": source_id,
        "node_id": node_id,
        "zone_id": zone_id,
        "timestamp": timestamp or iso_now(),
    }
    if sequence_id is not None:
        envelope["sequence_id"] = sequence_id
    if session_id is not None:
        envelope["session_id"] = session_id
    if entity_id is not None:
        envelope["entity_id"] = entity_id
    if origin_kind is not None:
        envelope["origin_kind"] = origin_kind
    return envelope


def make_registration(
    source_id: str,
    node_id: str,
    zone_id: str,
    etype: str,
    *,
    blank_mac_ip: bool = False,
) -> Dict[str, Any]:
    """실노드 `Identity.registration()`이 싣는 8개 항목.

    ⚠ **증강 분석은 `mac`·`ip`가 빈 문자열이다** — `Identity(dev, node_id, ZONE, "", "",
    "analysis")`로 만들기 때문이다. 레지스트리가 빈 값으로 기존 값을 덮지 않는지 보려면
    이 결함을 그대로 재현해야 한다.
    """
    blank = blank_mac_ip or etype == "analysis"
    return {
        "entity_id": source_id,
        "node_id": node_id,
        "zone_id": zone_id,
        "entity_type": etype,
        "device_type": DEVICE_TYPE_BY_ETYPE.get(etype, etype),
        "fw_version": FW_VERSION,
        "mac": "" if blank else SAMPLE_MAC,
        "ip": "" if blank else SAMPLE_IP,
    }


# ── 채널·타입별 본문 (HW 소스의 payload.update({...}) 그대로) ──────────────


def _body_state_sensor(*, water_level_m: Any, reason: str) -> Dict[str, Any]:
    """`pi/sensor/sensor_node.py` on_sample() 그대로.

    `water_level_m`은 규격상 `{"value": null, "state": "unsupported|unavailable"}` 형태도 허용한다
    (`x-mk2-absence: stateful`). 그 형태를 그대로 넣어 주면 부재 사유 경로를 재현한다.
    """
    return {
        "channel": "state",
        "water_level_m": water_level_m,
        "unit": "m",
        "alert": False,
        "reason": reason,
        "mode": "normal",
        "device_status": "ok",
    }


def _body_state_robot(*, reason: str, internal_seq: int) -> Dict[str, Any]:
    """`pi/robot/robot_node.py` _publish_state() 그대로.

    `mission`은 임무가 없으면 **키 자체가 없다** — 실물이 그렇다.
    """
    return {
        "channel": "state",
        "reason": reason,
        "battery_pct": 87.5,
        "position": {"x": 12.34, "y": -3.5, "heading_deg": 91.2},
        "speed_mps": 0.42,
        "robot_mode": "idle",
        "internal_seq": internal_seq,
        "device_status": "ok",
    }


def _body_state_actuator(*, reason: str) -> Dict[str, Any]:
    """`pi/actuator/actuator_node.py` _publish_state() 그대로.

    `detail`은 값이 비어 있으면 키 자체가 없다. `lock_reason`은 잠기지 않았어도
    **명시적 null로** 실린다(키가 사라지지 않는다).
    """
    return {
        "channel": "state",
        "reason": reason,
        "actuator_state": "idle",
        "position": "close",
        "progress": 0.0,
        "feedback_ok": True,
        "control_locked": False,
        "lock_reason": None,
        "device_status": "ok",
    }


def _body_state_analysis(*, subject_id: str) -> Dict[str, Any]:
    """`pi/augment/analyzer.py` main() 그대로 — **결함 포함**.

    본문 `channel`이 `"analysis"`인데 토픽 마지막 칸은 `state`이고, `device_status`도
    `reason`도 없다. 공통 코어를 강제하거나 본문 `channel`을 토픽과 대조하면 이 생산자가
    전량 격리된다 — 그것을 잡는 것이 이 형식의 존재 이유다.
    """
    return {
        "channel": "analysis",
        "subject_id": subject_id,
        "window_s": 300.0,
        "samples": 37,
        "value": 2.87,
        "trend_m_per_min": 0.0412,
        "eta_to_threshold_min": 3.2,
        "above_threshold": False,
        "threshold_m": 3.0,
    }


def _status_extra(etype: str) -> Dict[str, Any]:
    """노드별 `status_extra()` 훅이 덧붙이는 고유 필드.

    노드마다 다른 필드가 붙는 것이 **정상 동작**이며, 그래서 본문 규격이
    `additionalProperties: false`를 쓰지 않는다. 여기서도 타입마다 다르게 붙인다.
    """
    if etype == "sensor":
        return {
            "mode": "normal",
            "mode_source": "auto",
            "report_interval_s": 60.0,
            "alert": False,
            "last_value": 2.53,
        }
    if etype == "robot":
        return {
            "robot_mode": "idle",
            "in_mission": False,
            "state_interval_s": 5.0,
            "heartbeat_active": True,
            "link": "ok",
            "internal_seq": 15832,
            "media": {"streaming": False},
            "battery_pct": 87.5,
        }
    if etype == "actuator":
        return {
            "control_locked": False,
            "lock_reason": None,
            "actuator_state": "idle",
            "position": "close",
            "feedback_ok": True,
        }
    return {}


def _body_status(
    *,
    event: str,
    etype: str,
    source_id: str,
    node_id: str,
    zone_id: str,
    registration: bool,
    blank_mac_ip: bool,
) -> Dict[str, Any]:
    """`pi/common/node.py` publish_status()와 LWT(:92-94) 그대로.

    ⚠ `event == "death"`는 **브로커가 대신 발행하는 급사 신호(LWT)**라 모양이 다르다 —
    `registration`도 `buffer`도 `uptime_s`도 없다. 이 차이를 재현하지 않으면 "LWT가
    격리되지 않는가"를 검증할 수 없다.
    """
    if event == "death":
        return {
            "channel": "status",
            "event": "death",
            "status": "offline",
            "device_status": "fault",
            "reason": "lwt",
        }

    body: Dict[str, Any] = {
        "channel": "status",
        "event": event,
        "status": "offline" if event == "shutdown" else "online",
        "device_status": "ok",
    }
    if registration:
        body["registration"] = make_registration(
            source_id, node_id, zone_id, etype, blank_mac_ip=blank_mac_ip
        )
    body.update(
        {
            "uptime_s": 12.3,
            "buffer": {"pending": 0, "dropped": 0, "thinned": 0},
            "publish_failures": 0,
        }
    )
    body.update(_status_extra(etype))
    if event == "shutdown":
        body["reason"] = "graceful_shutdown"
    return body


def make_body(
    channel: str,
    etype: str,
    *,
    source_id: str = DEFAULT_EID,
    node_id: str = DEFAULT_NODE_ID,
    zone_id: str = DEFAULT_ZONE,
    event: str = "birth",
    registration: bool = True,
    blank_mac_ip: bool = False,
    reason: str = "periodic",
    water_level_m: Any = 2.53,
    internal_seq: int = 15832,
) -> Dict[str, Any]:
    """(채널, 개체 타입) → 본문. 규격 요약표가 아니라 HW 소스가 근거다."""
    if channel == "heartbeat":
        # 하트비트는 본문이 없다 — 공통 헤더만으로 의미가 성립한다.
        return {"channel": "heartbeat"}
    if channel == "status":
        return _body_status(
            event=event,
            etype=etype,
            source_id=source_id,
            node_id=node_id,
            zone_id=zone_id,
            registration=registration,
            blank_mac_ip=blank_mac_ip,
        )
    if etype == "robot":
        return _body_state_robot(reason=reason, internal_seq=internal_seq)
    if etype == "actuator":
        return _body_state_actuator(reason=reason)
    if etype == "analysis":
        return _body_state_analysis(subject_id=source_id)
    return _body_state_sensor(water_level_m=water_level_m, reason=reason)


# ── 봉투 + 본문 ─────────────────────────────────────────────────────────────


def default_sequence_id(channel: str, etype: str) -> Optional[int]:
    """순번의 기본값을 실물에 맞춘다.

    - `status`에는 순번이 **없다**(`envelope(self.identity)`를 순번 없이 호출).
    - 로봇 `state`는 항상 **0**이다 — `robot_node.py`가 `envelope(seq=self.seq)`를 쓰면서
      `self.seq`를 증가시키지 않는다. 이 결함을 기본값으로 재현해야 "유일 키를 순번에
      의존시키면 로봇 데이터가 사라진다"는 것이 테스트에 드러난다.
    - 나머지는 1부터.
    """
    if channel == "status":
        return None
    if channel == "state" and etype == "robot":
        return 0
    return 1


def default_sequence_step(channel: str, etype: str) -> int:
    """`--count`로 여러 건 보낼 때 순번 증가폭. 로봇 `state`는 0(실물 재현)."""
    if channel == "state" and etype == "robot":
        return 0
    return 1


def make_message(
    channel: str = "state",
    etype: str = DEFAULT_ETYPE,
    *,
    source_id: str = DEFAULT_EID,
    node_id: str = DEFAULT_NODE_ID,
    zone_id: str = DEFAULT_ZONE,
    sequence_id: Optional[int] = None,
    session_id: Optional[str] = SESSION_ID,
    timestamp: Optional[str] = None,
    entity_id: Optional[str] = None,
    origin_kind: Optional[str] = None,
    schema_version: str = SCHEMA_VERSION,
    replayed: bool = False,
    event: str = "birth",
    registration: bool = True,
    blank_mac_ip: bool = False,
    reason: str = "periodic",
    water_level_m: Any = 2.53,
    internal_seq: int = 15832,
) -> Dict[str, Any]:
    """공통 헤더 + 채널 본문이 합쳐진 완전한 메시지.

    `sequence_id`를 주지 않으면 채널·타입별 실물 기본값을 쓴다
    (`status`는 없음, 로봇 `state`는 0).
    """
    if sequence_id is None:
        sequence_id = default_sequence_id(channel, etype)
    if channel == "status":
        sequence_id = None  # 실물에 없다 — 주더라도 싣지 않는다

    message = make_envelope(
        source_id=source_id,
        node_id=node_id,
        zone_id=zone_id,
        sequence_id=sequence_id,
        session_id=session_id,
        timestamp=timestamp,
        entity_id=entity_id,
        origin_kind=origin_kind,
        schema_version=schema_version,
    )
    message.update(
        make_body(
            channel,
            etype,
            source_id=source_id,
            node_id=node_id,
            zone_id=zone_id,
            event=event,
            registration=registration,
            blank_mac_ip=blank_mac_ip,
            reason=reason,
            water_level_m=water_level_m,
            internal_seq=internal_seq,
        )
    )
    if replayed and channel == "state":
        # spool.replay()가 재전송분에 붙이는 표식. `status`·`heartbeat`는 spool을 타지
        # 않으므로(allow_spool=False) 이 표식이 붙을 일이 없다 — 그것도 실물 그대로다.
        message["replayed"] = True
    return message


def make_state_message(
    source_id: str = DEFAULT_EID,
    node_id: str = DEFAULT_NODE_ID,
    zone_id: str = DEFAULT_ZONE,
    sequence_id: int = 1,
    water_level_m: float = 2.53,
    session_id: Optional[str] = SESSION_ID,
) -> Dict[str, Any]:
    """센서 `state` 메시지 — 기존 회귀 테스트가 쓰는 이름 그대로 유지한다.

    `make_message(channel="state", etype="sensor", ...)`의 얇은 별칭이다. Phase 1 테스트가
    이 이름으로 부르고 있어 시그니처를 바꾸지 않는다.
    """
    return make_message(
        channel="state",
        etype="sensor",
        source_id=source_id,
        node_id=node_id,
        zone_id=zone_id,
        sequence_id=sequence_id,
        session_id=session_id,
        water_level_m=water_level_m,
    )


def load_invalid(kind: str, source_id: Optional[str] = None) -> Dict[str, Any]:
    """음성 대조 fixture를 읽는다. `source_id`만 1회용으로 바꿔 추적 가능하게 한다."""
    payload = json.loads(INVALID_FIXTURES[kind].read_text(encoding="utf-8"))
    if source_id:
        payload["source_id"] = source_id
        if "entity_id" in payload:
            payload["entity_id"] = source_id
    return payload


def publish(
    topic: str,
    payload: Dict[str, Any],
    host: Optional[str] = None,
    port: Optional[int] = None,
    qos: int = 1,
    retain: bool = False,
) -> Dict[str, Any]:
    """서버 Mosquitto로 1건 발행하고, 발행한 payload를 그대로 돌려준다."""
    mqtt_publish.single(
        topic,
        payload=json.dumps(payload, ensure_ascii=False),
        qos=qos,
        retain=retain,
        hostname=host or broker_host(),
        port=port if port is not None else broker_port(),
        client_id=f"mk2-pub-{uuid.uuid4().hex[:8]}",  # 노드 client_id와 겹치지 않게
    )
    return payload


def main() -> int:
    # 이 스크립트는 컴퓨터(윈도우)에서도 돌아야 한다. 윈도우 콘솔 기본 코드페이지(cp949)에
    # 없는 문자를 찍으면 UnicodeEncodeError 로 죽는데, **발행은 끝난 뒤 출력에서 죽는** 것이라
    # 원인을 오해하기 쉽다. 못 찍는 문자는 대체 문자로 흘려보낸다.
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="replace")
        except (ValueError, OSError):  # pragma: no cover - 리다이렉트된 스트림 등
            pass

    parser = argparse.ArgumentParser(description="MK2 발행자 (공통 규격 -> 서버 Mosquitto)")
    parser.add_argument("--host", default=broker_host())
    parser.add_argument("--port", type=int, default=broker_port())
    parser.add_argument("--zone", default=DEFAULT_ZONE)
    parser.add_argument("--etype", default=None, choices=ETYPES,
                        help=f"개체 타입(토픽 2번째 칸). 기본 {DEFAULT_ETYPE}")
    parser.add_argument("--eid", default=DEFAULT_EID)
    parser.add_argument("--channel", default="state", choices=list(CHANNELS))
    parser.add_argument("--node-id", default=DEFAULT_NODE_ID)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--interval", type=float, default=1.0)

    parser.add_argument("--timestamp", default=None,
                        help="ISO-8601 문자열 또는 지금 기준 상대 초(예: -420, +30). "
                             "과거 시각으로 지연 도착을, 미래 시각으로 음수 lag를 만든다")
    parser.add_argument("--seq", type=int, default=None,
                        help="시작 순번. 기본은 실물 기준(status 없음 / 로봇 state 0 / 나머지 1)")
    parser.add_argument("--seq-step", type=int, default=None,
                        help="--count 로 여러 건 보낼 때 순번 증가폭. 기본은 로봇 state 0, 나머지 1")
    parser.add_argument("--session-id", default=None, help="session_id 를 이 값으로 지정")
    parser.add_argument("--no-session-id", action="store_true",
                        help="session_id 를 아예 싣지 않는다(하드웨어 적용 전 폴백 경로 재현)")
    parser.add_argument("--entity-id", action="store_true",
                        help="entity_id 를 싣는다. 실노드는 보내지 않으므로 기본은 꺼짐")
    parser.add_argument("--origin-kind", default=None, choices=["real", "simulation", "replay"],
                        help="origin_kind 를 싣는다. 실노드는 보내지 않으므로 기본은 꺼짐")
    parser.add_argument("--schema-version", default=SCHEMA_VERSION,
                        help=f"공통 헤더 규격 버전. 기본 {SCHEMA_VERSION}(실노드는 아직 1.0)")
    parser.add_argument("--replayed", action="store_true", help="본문에 replayed: true 를 넣는다")
    parser.add_argument("--reason", default="periodic")

    parser.add_argument("--event", default="birth", choices=list(STATUS_EVENTS),
                        help="status 채널의 사건 종류. death 는 LWT(급사) 모양이 된다")
    parser.add_argument("--no-registration", action="store_true",
                        help="status 에 registration 블록을 싣지 않는다")
    parser.add_argument("--blank-mac-ip", action="store_true",
                        help="registration 의 mac·ip 를 빈 문자열로(증강 분석 형식 재현)")
    parser.add_argument("--retain", action="store_true",
                        help="retained 로 발행한다(실노드의 status 가 그렇다)")
    parser.add_argument("--water-level-state", default=None, choices=["unsupported", "unavailable"],
                        help="센서 state 의 water_level_m 을 {value: null, state: <이 값>} 형태로 보낸다 — "
                             "값이 없는 항목이 C층 시계열을 만들지 않는지(음성) 확인할 때 쓴다")

    parser.add_argument("--invalid", choices=sorted(INVALID_FIXTURES), help="음성 대조 fixture를 발행한다")
    args = parser.parse_args()

    etype = args.etype or INVALID_ETYPE.get(args.invalid or "", DEFAULT_ETYPE)
    channel = args.channel
    topic = topic_for(channel, args.zone, etype, args.eid)

    seq = args.seq if args.seq is not None else default_sequence_id(channel, etype)
    step = args.seq_step if args.seq_step is not None else default_sequence_step(channel, etype)
    session_id = None if args.no_session_id else (args.session_id or SESSION_ID)
    timestamp = resolve_timestamp(args.timestamp)
    retain = args.retain or channel == "status"

    for i in range(args.count):
        if args.invalid:
            payload = load_invalid(args.invalid)
        else:
            payload = make_message(
                channel=channel,
                etype=etype,
                source_id=args.eid,
                node_id=args.node_id,
                zone_id=args.zone,
                sequence_id=seq,
                session_id=session_id,
                timestamp=timestamp,
                entity_id=args.eid if args.entity_id else None,
                origin_kind=args.origin_kind,
                schema_version=args.schema_version,
                replayed=args.replayed,
                event=args.event,
                registration=not args.no_registration,
                blank_mac_ip=args.blank_mac_ip,
                reason=args.reason,
                water_level_m=(
                    {"value": None, "state": args.water_level_state} if args.water_level_state else 2.53
                ),
            )
        publish(topic, payload, host=args.host, port=args.port, retain=retain)
        print(f"published -> {args.host}:{args.port} {topic} :: {json.dumps(payload, ensure_ascii=False)}")
        if seq is not None:
            seq += step
        if i + 1 < args.count:
            time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
