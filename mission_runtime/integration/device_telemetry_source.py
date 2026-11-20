"""말단이 **실제로 올리는 것**을 받아 탐지·신선도를 채운다.

implements: AI-O-04 (실행 가용성 신호 연계), AI-C-18 (Capability 선언 규약)
관련: AI-C-06 (업무 평면), AI-C-04 (전송은 provider 뒤), AI-C-20 (uplink 의미 계약),
      원칙 #15 (장치 최종 가용성은 백엔드가 판정한다 — 여기서 하지 않는다)
tests: tests/test_device_telemetry_source.py

## 무엇이 없어서 이 모듈이 생겼나

`tools/view_service/fleet.py::Discovery` 의 docstring 이 "**게이트웨이가 capability
공지를 받아 채운다**" 고 적어 두었는데, **그 받는 쪽이 없었다.** 그래서 화면의 장치는
언제나 선언뿐이었고 `presence` 가 `discovered` 가 되지 못해 `availability` 가 영원히
`offline`, `quality` 가 영원히 `unknown` 이었다.

2026-11-05 에 실기기를 켜고 보니 로봇은 **이미 말하고 있었다** — pi7 의 브로커로
`zoneA/robot/go1-001/{state,status,heartbeat}` 가 몇 초마다, `terminal/go1-001/uplink`
에 capability 공지가 retained 로. 듣는 쪽만 없었다.

## 판정하지 않는다 — 두 가지를 **기록**할 뿐이다

1. **무엇을 할 수 있다고 공지했나** — `terminal/<device>/uplink` 의 capability 를
   우리 직렬화 provider 로 해독해 action 이름을 `Discovery.note()` 에 넘긴다.
   그 공지에 없는 선언 항목(`undeclared_items`)은 **그대로 남긴다**: 와이어가 싣지
   못하는 것과 장치가 '없다'고 말한 것은 다른 사실이다(AI-C-18 의 세 값).
2. **마지막으로 말한 시각** — heartbeat·status 가 올 때마다 갱신한다. 봉투가 적은
   **중계 노드도 함께** 갱신한다: 와이어가 로봇과 그것을 싣고 있는 온디바이스를 한
   봉투에 담으므로(`source_id` · `node_id`), 로봇 소리가 들렸다는 것은 그 소리가
   지나온 노드가 살아 있다는 관측이다. 둘을 분리해 관리하지 않는다.

**최종 가용성은 여기서 정하지 않는다**(원칙 #15). 이 모듈이 내는 것은 "언제 마지막으로
들었나" 이고, 그것을 online/stale/offline 로 읽는 규칙은 소비하는 쪽(`state_tick`)이
이미 들고 있다. 여기서 또 판정하면 같은 사실에 주인이 둘이 된다.

## 수치는 여전히 해석하지 않는다 — 다만 **충전 상태는 옮긴다**(2026-11-20)

아래 `_on_telemetry` 는 오래 "payload 의 수치를 읽지 않는다" 였다. 그 규칙의 목적은
*해석의 주인이 둘이 되는 것*을 막는 데 있었고 그 목적은 그대로다 — 이 모듈에는
임계도, "배터리 부족" 판정도 없다. 그런데 **충전 상태만은 옮긴다.**

이유는 2026-11-05 와 같은 모양의 실패다. 콘솔은 "이 콘솔은 배터리·CPU·메모리를 아직
재지 않는다" 고 적고 있었는데, 장치는 **이미 말하고 있었다** —
`third_party/data_stream/360camera_work/stream_to_server.py` 가 매 보고마다
`battery{level_pct, charging}` 를 싣는다. 듣는 쪽만 없었다. 그리고 충전은 예외가
아니라 정상 운용이다(`tools/vz_gateway/serve.py`: "충전하러 내려간 로봇이 돌아오는
것은 예외가 아니다"). **충전소 노드는 어느 배치에도 선언되어 있지 않으므로**, 지금
운영자가 알아야 하는 것은 "어느 자리를 예약할까" 가 아니라 "저 장치가 지금 충전
중인가" 다.

옮기는 것과 해석하는 것의 경계를 셋으로 지킨다.

* `None` 은 **그 장치가 말하지 않은 것**이고 0% 도 "충전 안 함" 도 아니다.
* 범위를 벗어난 값(0..100 밖)은 **조용히 고치지 않고 센다** — 고치면 센서 고장이
  정상값으로 보이고, 지어내면 없는 측정이 생긴다.
* 이름은 종류마다 다르므로 **받은 것을 읽고 우리가 고르지 않는다**(`CHARGE_PATHS`).
  `report_interval_s`·`state_interval_s` 를 둘 다 읽는 것과 같은 선례다.

## 픽셀도 명령도 다루지 않는다

구독만 한다. 이 모듈에는 발행 경로가 **없다** — 물리 명령 발급은 AI 소유가 아니고
(AI-C-19), 영상은 업무 평면으로 오지 않는다(AI-C-08).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

#: 장치가 스스로 알리는 capability 공지. `specs/physical-command-interface.md` 의
#: `terminal/<device-id>/uplink` 다.
UPLINK_TOPIC = "terminal/+/uplink"
#: 구역 업무 평면의 상태 3채널. 신선도만 여기서 읽는다.
TELEMETRY_TOPICS = ("+/+/+/heartbeat", "+/+/+/status", "+/+/+/state")

#: 공지를 해독하지 못했다. **조용히 버리지 않고 센다** — 와이어가 바뀌면 이 수가 는다.
REASON_UNDECODABLE = "uplink_not_decodable"
#: 장치 id 를 알 수 없는 봉투. 토픽에서도 payload 에서도 못 찾았다.
REASON_NO_DEVICE_ID = "device_id_absent"
#: 배터리 값이 0..100 밖이다. **고치지 않고 센다** — 고치면 고장이 정상으로 보인다.
REASON_CHARGE_OUT_OF_RANGE = "battery_level_out_of_range"

#: 충전 잔량이 적히는 자리들. 종류마다 이름이 다르므로 **받은 것을 읽는다**:
#: 360 카메라는 `battery.level_pct`(`third_party/data_stream/360camera_work/`),
#: data_stream 의 점검 도구는 `battery.pct` 를 본다(`check_v2.py`). 선언으로 늘린다.
CHARGE_LEVEL_PATHS: tuple[tuple[str, ...], ...] = (
    ("battery", "level_pct"),
    ("battery", "pct"),
    ("battery", "soc_pct"),
)
#: 충전 중인가가 적히는 자리들. **참/거짓/없음 세 값**이다.
CHARGING_PATHS: tuple[tuple[str, ...], ...] = (
    ("battery", "charging"),
)


def _dig(body: dict, paths: tuple[tuple[str, ...], ...]):
    """선언된 자리들을 순서대로 보고 **처음 적힌 것**을 낸다. 없으면 `None`.

    여러 이름을 보는 이유는 장치 종류마다 다르게 부르기 때문이고, 우리가 이름을
    고르지 않는다는 뜻이다(AI-C-18). 순서가 선언 순서인 것은 결정적이어야 하기
    때문이다 — 둘이 동시에 적혀 있으면 앞의 것을 쓴다.
    """
    for path in paths:
        cursor: object = body
        for key in path:
            if not isinstance(cursor, dict) or key not in cursor:
                cursor = None
                break
            cursor = cursor[key]
        if cursor is not None:
            return cursor
    return None


class DiscoverySink(Protocol):
    """`tools/view_service/fleet.py::Discovery` 가 이 모양이다.

    Protocol 로 받는 이유: 이 모듈이 `tools/` 를 import 하면 패키지가 도구에 의존한다
    (AI-C-04). 소비자가 자기 Discovery 를 넘긴다.
    """

    def note(self, device_id: str, actions: Any, *, at: float | None = None) -> None: ...


@dataclass
class TelemetryObservation:
    """한 장치에 대해 **관측된** 사실. 선언이 아니다."""

    device_id: str
    #: 그 장치가 스스로 알린 action 이름들. 공지를 못 받았으면 빈 튜플이다.
    actions: tuple[str, ...] = ()
    #: 공지에서 **비어 있던** 선언 항목들(AI-C-18). 비어 있다는 사실 자체가 정보다.
    undeclared_items: tuple[str, ...] = ()
    #: 마지막으로 무엇이든 들은 시각(monotonic 아님 — `Discovery` 와 같은 축을 쓴다).
    last_heard: float | None = None
    #: 어느 채널로 들었나. 공지만 왔는지 텔레메트리도 오는지 가른다.
    channels: set[str] = field(default_factory=set)
    #: 봉투가 적은 구역·노드. 우리가 추측하지 않고 받은 것을 적는다.
    zone_id: str = ""
    node_id: str = ""
    #: **장치가 스스로 말한 보고 주기(초).** 모르면 `None` 이고 0 이 아니다.
    #:
    #: 이 칸이 있는 이유: 하나의 고정 임계로 모든 장치의 신선도를 재면 **두 장치가
    #: 정반대로 틀린다.** 실측(2026-11-05) — go1-001 은 5 초마다, wl-001 은 60 초마다
    #: 보고한다. 60 초 고정이면 움직이는 로봇이 죽고도 1 분 동안 online 이고(보고 12 회
    #: 놓침), 수위계는 멀쩡한데 늘 stale 경계에 걸린다.
    report_interval_s: float | None = None
    #: **장치가 스스로 말한** 충전 잔량(%). `None` 은 말하지 않은 것이고 0 이 아니다.
    battery_level_pct: float | None = None
    #: 충전 중인가. `None` 은 말하지 않은 것이고 **"충전 안 함" 과 다르다.**
    charging: bool | None = None
    #: 그 충전 값을 들은 시각. `last_heard` 와 다른 축이다 — 장치가 말을 계속 하면서
    #: 배터리 칸만 빼고 보낼 수 있고, 그때 옛 값을 지금 값처럼 보여서는 안 된다.
    charge_observed_at: float | None = None


@dataclass
class DeviceTelemetrySource:
    """브로커를 **구독만** 해서 공지와 신선도를 모은다.

    `transport` 는 `providers/mqtt.py::MqttTransportProvider` 모양이면 된다
    (`subscribe(topic, handler)`). 가짜로도 시험한다.

    `serializer` 는 capability 공지를 해독한다 — 없으면 공지는 셈만 하고 action 은
    비운다. **없는 것을 지어내지 않는다**(AI-C-05: 그 조각만 축소).
    """

    transport: Any
    serializer: Any | None = None
    sink: DiscoverySink | None = None
    clock: Callable[[], float] = time.time

    observations: dict[str, TelemetryObservation] = field(default_factory=dict)
    #: 사유별 버린 수. 조용히 버리지 않기 위한 계수기다.
    dropped: dict[str, int] = field(default_factory=dict)

    def start(self) -> None:
        """구독을 건다. **발행하지 않는다.**"""
        self.transport.subscribe(UPLINK_TOPIC, self._on_uplink)
        for topic in TELEMETRY_TOPICS:
            self.transport.subscribe(topic, self._on_telemetry)

    # ── 공지 ────────────────────────────────────────────────────────────────

    def _on_uplink(self, payload: bytes) -> None:
        """capability 공지. 해독되면 action 을 `Discovery` 에 넘긴다."""
        decoded = self._decode(payload)
        if decoded is None:
            self._drop(REASON_UNDECODABLE)
            return
        body = decoded.get("payload") if isinstance(decoded, dict) else None
        if not isinstance(body, dict):
            self._drop(REASON_UNDECODABLE)
            return
        device_id = str(body.get("device_id") or "")
        if not device_id:
            self._drop(REASON_NO_DEVICE_ID)
            return
        actions = tuple(str(a) for a in (body.get("actions") or ()))
        obs = self._obs(device_id)
        obs.actions = actions
        # **비어 있던 항목을 그대로 들고 간다.** 와이어가 싣지 못하는 것과 장치가
        # "없다" 고 말한 것은 다른 사실이고, 그 구분이 AI-C-18 의 요점이다.
        obs.undeclared_items = tuple(str(u) for u in (body.get("undeclared_items") or ()))
        obs.channels.add("uplink")
        obs.last_heard = self.clock()
        if self.sink is not None:
            # `Discovery` 가 소유한 자료형에 넘긴다. 여기서 presence 를 정하지
            # 않는다 — 그 규칙은 소비자가 들고 있다(원칙 #15).
            self.sink.note(device_id, actions, at=obs.last_heard)

    def _decode(self, payload: bytes) -> dict | None:
        if self.serializer is None:
            return None
        try:
            return self.serializer.decode(payload, schema_hint="capability")
        except Exception:                                       # noqa: BLE001
            # 해독 실패는 **사유로 센다**. 예외를 올리면 한 장치의 낡은 공지가
            # 다른 장치의 관측까지 끊는다(AI-C-05).
            return None

    # ── 신선도 ──────────────────────────────────────────────────────────────

    def _on_telemetry(self, payload: bytes) -> None:
        """heartbeat·status·state. **마지막으로 들은 시각만** 본다.

        payload 의 수치를 읽지 않는 이유: 배터리·자세 같은 값의 주인은 그것을 내는
        쪽이고, 여기서 다시 해석하면 같은 사실에 주인이 둘이 된다. 이 모듈이 더하는
        것은 "들었다" 하나다.
        """
        try:
            body = json.loads(payload.decode("utf-8"))
        except Exception:                                       # noqa: BLE001
            self._drop(REASON_UNDECODABLE)
            return
        if not isinstance(body, dict):
            self._drop(REASON_UNDECODABLE)
            return
        device_id = str(body.get("source_id") or "")
        if not device_id:
            self._drop(REASON_NO_DEVICE_ID)
            return
        obs = self._obs(device_id)
        obs.last_heard = self.clock()
        obs.channels.add(str(body.get("channel") or "telemetry"))
        # 봉투가 적은 것만 적는다 — 구역·노드를 우리가 추측하지 않는다.
        obs.zone_id = str(body.get("zone_id") or obs.zone_id)
        obs.node_id = str(body.get("node_id") or obs.node_id)
        # 장치가 자기 주기를 말하면 그대로 받는다. 이름이 둘인 이유는 종류마다
        # 다르게 부르기 때문이고(로봇 `state_interval_s` · 센서
        # `report_interval_s`), **우리가 고르지 않고 적힌 것을 읽는다**.
        for field_name in ("state_interval_s", "report_interval_s"):
            declared = body.get(field_name)
            if isinstance(declared, (int, float)) and declared > 0:
                obs.report_interval_s = float(declared)
                break

        # **충전 상태를 옮긴다**(해석하지 않는다 — 위 docstring).
        self._read_charge(obs, body)

        # **중계한 노드도 들은 것이다**(2026-11-05).
        #
        # 와이어는 로봇과 그것을 싣고 있는 온디바이스를 **한 봉투에** 담는다 —
        # `source_id: go1-001` · `node_id: pi7`. 로봇 소리만 기록하면 pi7 은 영원히
        # offline 으로 남는데, 그 메시지가 **pi7 을 통해 왔다**는 것이 pi7 이 살아
        # 있다는 관측이다(선언보다 강한 근거다). 둘을 따로 관리하지 않는다는 결정이
        # 여기에 그대로 들어간다.
        #
        # **action 은 넘기지 않는다.** pi7 은 자기 action 을 공지한 적이 없고, 중계
        # 노드의 기능은 선언(`media.ingest`)이 말한다. 로봇의 action 을 pi7 에 붙이면
        # "pi7 이 걸을 수 있다" 가 되고, 그것은 관측이 아니라 거짓이다.
        node_id = obs.node_id
        if node_id and node_id != device_id:
            relay = self._obs(node_id)
            relay.last_heard = obs.last_heard
            relay.zone_id = relay.zone_id or obs.zone_id
            relay.channels.add("relayed")
            if self.sink is not None:
                self.sink.note(node_id, relay.actions, at=relay.last_heard)

        if self.sink is not None:
            # **action 을 덮지 않는다.** 텔레메트리는 "무엇을 할 수 있다" 를 말하지
            # 않으므로, 공지로 받은 목록을 그대로 두고 시각만 민다. 빈 목록으로
            # 덮으면 공지를 받은 장치가 "아무것도 못 하는 장치" 가 된다.
            self.sink.note(device_id, obs.actions, at=obs.last_heard)

    def _read_charge(self, obs: TelemetryObservation, body: dict) -> None:
        """적혀 있으면 옮기고, 없으면 **이전 값을 그대로 둔다.**

        없을 때 `None` 으로 덮지 않는 이유: heartbeat 처럼 배터리 칸이 없는 채널도
        같은 구독으로 들어온다. 덮으면 1 초마다 값이 생기고 사라지는 화면이 된다.
        """
        level = _dig(body, CHARGE_LEVEL_PATHS)
        charging = _dig(body, CHARGING_PATHS)
        if level is None and charging is None:
            return
        if level is not None:
            if not isinstance(level, (int, float)) or isinstance(level, bool):
                self._drop(REASON_CHARGE_OUT_OF_RANGE)
                return
            if not 0.0 <= float(level) <= 100.0:
                self._drop(REASON_CHARGE_OUT_OF_RANGE)
                return
            obs.battery_level_pct = float(level)
        if charging is not None:
            obs.charging = bool(charging)
        obs.charge_observed_at = obs.last_heard
        if self.sink is not None and hasattr(self.sink, "note_charge"):
            # **선택 기능이다.** 이 메서드를 모르는 sink 는 그대로 동작한다(AI-C-05).
            self.sink.note_charge(obs.device_id, level_pct=obs.battery_level_pct,
                                  charging=obs.charging, at=obs.charge_observed_at)

    # ── 조회 ────────────────────────────────────────────────────────────────

    def _obs(self, device_id: str) -> TelemetryObservation:
        obs = self.observations.get(device_id)
        if obs is None:
            obs = TelemetryObservation(device_id=device_id)
            self.observations[device_id] = obs
        return obs

    def _drop(self, reason: str) -> None:
        self.dropped[reason] = self.dropped.get(reason, 0) + 1

    def note_for_screen(self) -> str:
        """화면·로그가 그대로 적는 한 줄. **빈 상태도 사유로 말한다.**"""
        if not self.observations:
            dropped = sum(self.dropped.values())
            if dropped:
                return f"장치 공지 0건 — 받았으나 해독하지 못함 {dropped}건"
            return "장치 공지 0건 — 아직 아무것도 오지 않았다(브로커 연결은 별개다)"
        heard = sorted(self.observations)
        with_actions = [d for d in heard if self.observations[d].actions]
        return (f"장치 {len(heard)}대 관측 — {', '.join(heard)}"
                f" · capability 공지 {len(with_actions)}대")

    def declared_interval_s(self, device_id: str) -> float | None:
        """그 장치가 **스스로 말한** 보고 주기. 말한 적 없으면 `None`.

        중계 노드는 자기 주기를 말하지 않으므로, 자기 값이 없으면 **자기가 실어
        나르는 장치들 중 가장 짧은 주기**를 쓴다 — 그 소리가 지나오는 동안은 중계도
        살아 있다는 뜻이고, 가장 자주 오는 것이 중계의 신선도를 정한다.
        """
        obs = self.observations.get(device_id)
        if obs is None:
            return None
        if obs.report_interval_s is not None:
            return obs.report_interval_s
        relayed = [o.report_interval_s for o in self.observations.values()
                   if o.node_id == device_id and o.report_interval_s is not None]
        return min(relayed) if relayed else None
