"""가시화 와이어 — 우리 상태를 가시화 계약의 봉투로 옮긴다. **소켓을 모른다.**

가시화 대시보드(`khw_VZ`)의 수신부는 받은 JSON 의 `type` 으로 분기하고, 실제로
소비하는 것은 `case 'data'` 하나다::

    { "type": "data", "sub": "<구독 id>", "envelope": { ... } }

`sub` 는 **뷰어가 자기 안에서 만든 id** 라, 서버가 그것을 알려면 뷰어가 보낸 구독
메시지를 읽어야 한다. 그 자리는 소켓을 아는 쪽(`providers/ws_server.py` 를 쓰는
`tools/vz_gateway/`)이고 이 모듈은 **매칭과 변환만** 한다.

왜 소켓을 모르는가: 매칭·변환이 딕셔너리만으로 검증돼야 하기 때문이다. 그래서 이
파일은 **표준 라이브러리만** 쓰고, 전송 구현이 바뀌어도 그대로 남는다(AI-C-04 ·
AI-C-06 — 상위 로직은 구간별 전송 기술을 직접 호출하지 않는다).

## 여기서 지키는 것 셋

1. **`quality` 를 지어내지 않는다.** 신선도에서 유도하고, 한 번도 받지 못한 것과
   오래된 것을 구분한다. 고정 `"good"` 을 내보내면 화면이 끊긴 장치를 정상으로
   그린다(AI-O-04 · AI-O-05 — 미측정은 0 도 정상도 아니다).
2. **`coordinate_frame` 에 전역을 적지 않는다.** 좌표를 담은 채널만 자기 기준계
   이름을 들고 가고, 담지 않는 채널은 `None` 이다. datum 이 검증되지 않은 현장에서
   전역 프레임을 주장하지 않는다(AI-C-02).
3. **어휘 밖 채널은 조용히 버리지 않는다.** 뷰어가 모르는 채널은 보내 봐야 `sub`
   매칭에서 사라지므로, 내보내기 전에 걸러 내고 사유를 남긴다.

## 예외를 던지지 않는다

`to_envelope()` 는 모든 구독자에게 보내는 루프 안에서 불린다. 거기서 예외가 나면 그
뒤의 클라이언트 전송이 통째로 끊긴다. 그래서 전부 `.get()` 이고 폴백이 있다.

implements: AI-C-01, AI-C-02, AI-C-04, AI-C-06, AI-O-04, AI-O-06
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

#: 뷰어가 아는 채널. 이 밖의 이름을 보내면 뷰어가 `sub` 를 찾지 못해 버린다 —
#: 보내기 전에 거르고 사유를 남기는 편이 "연결은 됐는데 화면이 빈" 것보다 낫다.
VIEWER_CHANNELS: frozenset[str] = frozenset({
    "state", "telemetry", "heartbeat", "video_meta", "actuator_state",
    "command_result", "control_lock", "plan", "plan_progress", "video_frame",
    "detections", "metrics", "risk_state", "ai_failure",
})

#: 좌표를 담는 채널만 기준계를 들고 간다. 나머지는 `None` 이고, 그 `None` 이
#: "좌표가 없다" 는 뜻이지 "전역이다" 가 아니다(AI-C-02).
SPATIAL_CHANNELS: frozenset[str] = frozenset({"state", "detections", "plan"})

QUALITY_GOOD, QUALITY_DEGRADED, QUALITY_UNKNOWN = "good", "degraded", "unknown"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def quality_of(*, last_seen_s: float | None, stale_after_s: float | None) -> str:
    """신선도 → 뷰어의 세 값.

    **한 번도 받지 못한 것**(`last_seen_s is None`)은 `unknown` 이지 `degraded` 가
    아니다 — 둘을 합치면 "아직 안 붙은 장치" 와 "붙었다가 끊긴 장치" 가 같은 색으로
    보인다(AI-O-04).
    """
    if last_seen_s is None:
        return QUALITY_UNKNOWN
    if stale_after_s is None:
        return QUALITY_GOOD
    return QUALITY_GOOD if last_seen_s <= stale_after_s else QUALITY_DEGRADED


@dataclass(frozen=True)
class Selector:
    """뷰어가 보낸 구독 축. 토픽 문자열이 아니라 계약 축 그대로다."""

    entity: str
    node: str
    channel: str

    @classmethod
    def from_wire(cls, raw: dict | None) -> "Selector":
        raw = raw or {}
        return cls(entity=str(raw.get("entity") or "*"),
                   node=str(raw.get("node") or "*"),
                   channel=str(raw.get("channel") or "*"))

    def matches(self, *, entity: str, node: str, channel: str) -> bool:
        """`*` 는 전체다. 세 축이 모두 맞아야 보낸다."""
        return ((self.entity in ("*", entity))
                and (self.node in ("*", node))
                and (self.channel in ("*", channel)))


@dataclass
class Subscription:
    sub_id: str
    selector: Selector
    scope: object = "all"


def to_envelope(
    *,
    entity: str,
    node: str,
    zone: str | None,
    channel: str,
    payload: object,
    seq: int,
    last_seen_s: float | None = None,
    stale_after_s: float | None = None,
    coordinate_frame: str | None = None,
    scope: object = "all",
    ts: str | None = None,
) -> dict:
    """우리 값 하나를 뷰어 봉투로. 예외를 던지지 않는다.

    `coordinate_frame` 은 **좌표를 담은 채널에서만** 쓰인다. 좌표가 없는 채널에
    프레임 이름을 적으면 받는 쪽이 그 값으로 무언가를 환산하려 든다.
    """
    frame = coordinate_frame if channel in SPATIAL_CHANNELS else None
    return {
        "zone": zone,
        "node": node,
        "entity": entity,
        "channel": channel,
        "ts": ts or _now_iso(),
        "seq": seq,
        "payload": payload,
        "quality": quality_of(last_seen_s=last_seen_s, stale_after_s=stale_after_s),
        "aggregation": "raw",
        "scope": scope,
        "coordinate_frame": frame,
    }


def data_frame(sub_id: str, envelope: dict) -> dict:
    """뷰어가 실제로 분기하는 유일한 모양."""
    return {"type": "data", "sub": sub_id, "envelope": envelope}


def hello_frame(*, stale_threshold_ms: int) -> dict:
    return {"type": "hello", "server_time": _now_iso(),
            "stale_threshold_ms": stale_threshold_ms}


def error_frame(message: str) -> dict:
    return {"type": "error", "message": message}


@dataclass
class SubscriptionTable:
    """구독표. 어느 봉투를 어느 `sub` 로 보낼지만 정한다."""

    subs: dict[str, Subscription] = field(default_factory=dict)
    #: 어휘 밖 채널을 내보내려 한 횟수. 조용히 버리지 않기 위한 계수기다.
    dropped: dict[str, int] = field(default_factory=dict)

    def add(self, raw: dict) -> Subscription | None:
        sub_id = raw.get("id")
        if not isinstance(sub_id, str) or not sub_id:
            return None
        sub = Subscription(sub_id=sub_id,
                           selector=Selector.from_wire(raw.get("selector")),
                           scope=raw.get("scope", "all"))
        self.subs[sub_id] = sub
        return sub

    def remove(self, raw: dict) -> None:
        sub_id = raw.get("id")
        if isinstance(sub_id, str):
            self.subs.pop(sub_id, None)

    def frames_for(self, envelope: dict) -> list[dict]:
        """이 봉투를 받아야 하는 구독 전부에 대한 전송 프레임.

        어휘 밖 채널이면 **아무에게도 보내지 않고** 계수기에 남긴다.
        """
        channel = str(envelope.get("channel") or "")
        if channel not in VIEWER_CHANNELS:
            self.dropped[channel] = self.dropped.get(channel, 0) + 1
            return []
        entity = str(envelope.get("entity") or "")
        node = str(envelope.get("node") or "")
        return [data_frame(s.sub_id, envelope) for s in self.subs.values()
                if s.selector.matches(entity=entity, node=node, channel=channel)]
