"""What carries what, and how a capability is actually reached.

implements: AI-C-18 (구성요소 capability 선언 규약), AI-B-04 (자원 등록·배치)
관련: AI-C-10, AI-C-05, AI-B-10 (말단 경량 경계), AI-B-11, AI-C-15, AI-O-04, AI-C-19

왜 이 모듈이 있는가
-------------------
실제 지형에서 **연산 장치는 로봇에 실려 있다** — Pi 가 랜선으로 로봇에 붙고, 그
Pi 가 컨테이너·오케스트레이터를 들고 있어서 로봇 종류에 상한이 없어진다. 그런데
선언은 `go1-001` 과 `pi7` 을 **서로 무관한 두 노드**로 적고 있었다. 그 평평한
모델에서 생기는 일 셋.

1. **공유 운명이 사라진다.** 랜선으로 붙은 Pi 는 로봇이 꺼지면 함께 꺼진다. 두
   노드가 무관하면 "로봇은 죽었는데 Pi 는 살아 있다" 는 상태가 표현 가능해지고,
   그 상태를 보고 원격 기능을 고르면 닿지 않는 곳으로 보낸다(AI-O-04).
2. **움직이는지 모른다.** 로봇에 실린 Pi 는 움직인다. `tier.edge` 로 적혀 있으면
   배치가 구역 엣지 몫(브로커·수집기 급)을 **움직이는 로봇에** 올린다 —
   AI-B-10 이 막으라고 한 바로 그것이다.
3. **카메라가 어디 붙었는지 모른다.** `has_camera: bool` 하나로는 셋을 가를 수
   없다. 로봇 내부 카메라는 로봇 SDK 로 오고, 드론처럼 내부 카메라가 없는 기체는
   Pi 에 카메라를 달아 로컬 캡처로 오고, 360 유닛은 송수신기 연결과 **자기 실행
   코드**가 먼저 떠야 아무것도 내지 않는다.

그래서 축을 셋으로 가른다 — 부착(무엇에 실렸나) · 링크(무엇으로 붙었나) ·
도달(capability 를 어떻게 얻나). 합치면 하나가 다른 둘을 가린다.

이것이 "로봇 종류 제한 없는 확장" 의 형태다
-------------------------------------------
새 로봇을 들이는 쪽이 하는 일은 선언 한 건이다 — 무엇에 실렸고, 무엇으로 붙었고,
각 capability 를 어떻게 얻는가. 핵심 코드에 로봇 이름 분기가 생기지 않는다
(원칙 #1·#3·#7). 어휘는 전부 **자유 문자열**이고 새 링크·새 도달 방식은 선언에
문자열 하나를 더하는 일이다.

가용성을 여기서 판정하지 않는다
-------------------------------
공유 운명은 **선언된 관계**일 뿐이고 "지금 살아 있는가" 의 답이 아니다. 장치 최종
가용성은 백엔드가 업무·관측 상태를 통합해 판정하고(원칙 #15, AI-C-19) 이 모듈은
그 판정을 **입력으로 소비할 수 있는 관계**만 제공한다. 여기서 살아 있음을 계산하면
같은 사실에 주인이 둘이 된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

# ── 부착 ────────────────────────────────────────────────────────────────────

#: 자기 발로 서 있다. 구역 엣지·서버·고정 카메라가 이쪽이다.
ATTACHMENT_STANDALONE = "standalone"
#: 다른 장치에 실려 다닌다. 실린 쪽의 운명과 이동성을 물려받는다.
ATTACHMENT_CARRIED_BY = "carried_by"
ATTACHMENTS: tuple[str, ...] = (ATTACHMENT_STANDALONE, ATTACHMENT_CARRIED_BY)

# ── 링크 ────────────────────────────────────────────────────────────────────
# **유선인지가 공유 운명의 근거다.** 랜선으로 붙은 것은 함께 꺼지고, 무선으로
# 붙은 것은 따로 살아 있을 수 있다 — 그 차이를 링크가 말한다.

LINK_INTERNAL_BUS = "internal_bus"
LINK_ETHERNET = "ethernet"
LINK_USB = "usb"
LINK_SERIAL = "serial"
LINK_WIRELESS = "wireless"
#: 함께 꺼지는 링크들. 무선은 들어가지 않는다.
WIRED_LINKS: frozenset[str] = frozenset({
    LINK_INTERNAL_BUS, LINK_ETHERNET, LINK_USB, LINK_SERIAL})

# ── 도달 ────────────────────────────────────────────────────────────────────
# capability 를 **실제로 어떻게 얻는가**. 같은 "카메라 영상" 이라도 이 축이 다르면
# 상류 코드가 다른 일을 해야 하고, 그 차이를 선언이 흡수해야 분기가 안 생긴다.

#: 로봇 내부 장비 — 로봇 SDK·어댑터를 거쳐 온다(go1 전면 카메라).
REACH_ROBOT_SDK = "robot_sdk"
#: 이 노드에 직접 달렸다 — 로컬 캡처로 온다(Pi 에 단 카메라).
REACH_HOST_CAPTURE = "host_capture"
#: 별개 유닛이고 **송수신기 연결과 자기 실행 코드가 먼저 떠야** 한다(360 유닛).
REACH_TRANSCEIVER = "transceiver"
#: 네트워크로 받는다(고정 IP 카메라 등).
REACH_NETWORK_STREAM = "network_stream"
REACHES: tuple[str, ...] = (REACH_ROBOT_SDK, REACH_HOST_CAPTURE,
                            REACH_TRANSCEIVER, REACH_NETWORK_STREAM)

#: 준비 상태 사유 토큰. **"없다" 와 "아직 안 떴다" 는 다른 사실이다** — 후자는
#: 할 일이 남은 것이고 전자는 그 배치에 그 기능이 없는 것이다(AI-C-05).
REASON_READY = "ready"
REASON_PREREQUISITE_MISSING = "prerequisite_not_satisfied"
REASON_CARRIER_UNDECLARED = "carrier_not_declared"
REASON_CARRIER_UNKNOWN = "carrier_not_in_fleet"
REASON_SELF_CARRIED = "node_carries_itself"


@dataclass(frozen=True)
class CapabilityReach:
    """한 capability 를 **어떻게 얻는가**. 무엇을 얻는가는 capability kind 가 말한다."""

    capability_kind: str
    reach: str
    #: 그 장비의 식별자(카메라 id 등). 없으면 노드 자체가 제공자다.
    unit_id: str = ""
    #: 떠 있어야 하는 것들. `transceiver` 도달이 비어 있으면 그 선언은 거짓이다 —
    #: 송수신기와 실행 코드 없이 영상이 나오지 않는다.
    prerequisites: tuple[str, ...] = ()
    #: 이 도달이 **내주지 않는** 것. 선언된 결손이고 추측이 아니다.
    missing_outputs: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.capability_kind:
            raise ValueError("capability_kind must not be empty")
        if not self.reach:
            raise ValueError("reach must not be empty")

    @property
    def needs_bring_up(self) -> bool:
        """쓰기 전에 따로 띄워야 하는가. 송수신기 도달이 그렇다."""
        return bool(self.prerequisites)

    def readiness(self, satisfied: frozenset[str] | set[str] | None = None) -> tuple[bool, str]:
        """(준비됐나, 사유). 전제가 없으면 바로 준비됨이다.

        만족 목록을 **받아서** 판정한다 — 여기서 프로세스를 확인하면 이 모듈이
        런타임을 알게 되고, 그것은 provider 경계 뒤에 있어야 하는 일이다(AI-C-04).
        """
        if not self.prerequisites:
            return True, REASON_READY
        have = frozenset(satisfied or ())
        missing = tuple(p for p in self.prerequisites if p not in have)
        if missing:
            return False, f"{REASON_PREREQUISITE_MISSING}:{','.join(missing)}"
        return True, REASON_READY

    def as_dict(self) -> dict:
        body: dict = {"capability_kind": self.capability_kind, "reach": self.reach}
        # 빈 칸은 싣지 않는다 — 빈 목록을 보내면 "확인했고 없었다" 로 읽힌다.
        if self.unit_id:
            body["unit_id"] = self.unit_id
        if self.prerequisites:
            body["prerequisites"] = list(self.prerequisites)
        if self.missing_outputs:
            body["missing_outputs"] = list(self.missing_outputs)
        if self.notes:
            body["notes"] = self.notes
        return body


@dataclass(frozen=True)
class DeviceAttachment:
    """이 노드가 무엇에 실려 있고 각 capability 를 어떻게 얻는가."""

    device_id: str
    attachment: str = ATTACHMENT_STANDALONE
    #: 실려 있는 상대. `carried_by` 일 때만 뜻이 있다.
    carrier_id: str = ""
    #: 무엇으로 붙었나. 유선이면 공유 운명이다.
    link: str = ""
    #: 이 노드가 제공하는 capability 들의 도달 방식.
    reaches: tuple[CapabilityReach, ...] = ()
    #: 선언 그대로 지나가는 자리. 모르는 칸을 버리지 않는다.
    extra: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.device_id:
            raise ValueError("device_id must not be empty")
        if self.attachment not in ATTACHMENTS:
            # 자유 문자열 축이지만 **부착은 둘뿐**이다 — 실렸거나 아니거나다.
            # 셋째가 필요하면 그것은 계약 변경이고 조용히 늘어날 일이 아니다.
            raise ValueError(f"unknown attachment: {self.attachment}")
        if self.attachment == ATTACHMENT_CARRIED_BY and self.carrier_id == self.device_id:
            raise ValueError(REASON_SELF_CARRIED)

    @property
    def is_carried(self) -> bool:
        return self.attachment == ATTACHMENT_CARRIED_BY and bool(self.carrier_id)

    @property
    def shares_fate_with(self) -> str:
        """함께 꺼지는 상대. 무선으로 붙었으면 **빈 문자열이다** — 따로 살아 있을 수 있다.

        이것은 선언된 관계이고 "지금 살아 있는가" 의 답이 아니다. 최종 가용성은
        백엔드가 판정한다(원칙 #15).
        """
        if self.is_carried and self.link in WIRED_LINKS:
            return self.carrier_id
        return ""

    @property
    def carrier_declaration_reason(self) -> str:
        """부착 선언이 성립하는가. 성립하면 `ready`, 아니면 사유."""
        if self.attachment != ATTACHMENT_CARRIED_BY:
            return REASON_READY
        if not self.carrier_id or not self.link:
            return REASON_CARRIER_UNDECLARED
        return REASON_READY

    def reach_for(self, capability_kind: str) -> CapabilityReach | None:
        for reach in self.reaches:
            if reach.capability_kind == capability_kind:
                return reach
        return None

    def reaches_by(self, reach: str) -> tuple[CapabilityReach, ...]:
        return tuple(r for r in self.reaches if r.reach == reach)

    @property
    def bring_up_required(self) -> tuple[str, ...]:
        """쓰기 전에 떠야 하는 것 전부. 360 유닛의 송수신기·실행 코드가 여기 모인다."""
        out: list[str] = []
        for reach in self.reaches:
            out += [p for p in reach.prerequisites if p not in out]
        return tuple(out)

    def as_dict(self) -> dict:
        body: dict = {"device_id": self.device_id, "attachment": self.attachment}
        if self.carrier_id:
            body["carrier_id"] = self.carrier_id
        if self.link:
            body["link"] = self.link
        if self.reaches:
            body["reaches"] = [r.as_dict() for r in self.reaches]
        # 유도되는 값은 **유도된 자리에** 둔다. 선언과 같은 층에 섞으면 누가 적은
        # 값인지 알 수 없다(AI-S-08).
        body["derived"] = {
            "is_carried": self.is_carried,
            "shares_fate_with": self.shares_fate_with or None,
            "bring_up_required": list(self.bring_up_required),
            "declaration_reason": self.carrier_declaration_reason,
        }
        if self.extra:
            body["extra"] = dict(self.extra)
        return body


@dataclass(frozen=True)
class AttachmentGraph:
    """현장의 부착 관계 전부. 실려 있는 것과 싣고 있는 것을 양방향으로 본다."""

    attachments: tuple[DeviceAttachment, ...] = ()

    def get(self, device_id: str) -> DeviceAttachment | None:
        for attachment in self.attachments:
            if attachment.device_id == device_id:
                return attachment
        return None

    def carried_by(self, carrier_id: str) -> tuple[str, ...]:
        """그 장치가 싣고 있는 노드들. 로봇이 꺼질 때 함께 꺼지는 목록이다."""
        return tuple(sorted(a.device_id for a in self.attachments
                            if a.is_carried and a.carrier_id == carrier_id))

    def mobile_nodes(self) -> tuple[str, ...]:
        """움직이는 노드들 — 실려 있으면 움직인다.

        배치가 이 목록을 보고 구역 엣지 몫을 올리지 않아야 한다(AI-B-10). 여기서
        배치를 결정하지는 않는다 — 목록만 낸다.
        """
        return tuple(sorted(a.device_id for a in self.attachments if a.is_carried))

    def dangling(self) -> tuple[tuple[str, str], ...]:
        """선언이 성립하지 않는 것들. `(노드, 사유)`.

        **조용히 빼지 않는다** — 싣고 있다고 적힌 상대가 현장에 없으면 그 사실이
        드러나야 하고, 그것은 조인 거절이 아니라 남은 할 일이다(원칙 #15).
        """
        known = {a.device_id for a in self.attachments}
        out: list[tuple[str, str]] = []
        for attachment in self.attachments:
            reason = attachment.carrier_declaration_reason
            if reason != REASON_READY:
                out.append((attachment.device_id, reason))
            elif attachment.is_carried and attachment.carrier_id not in known:
                out.append((attachment.device_id,
                            f"{REASON_CARRIER_UNKNOWN}:{attachment.carrier_id}"))
        return tuple(out)

    def providers_of(self, capability_kind: str) -> tuple[tuple[str, CapabilityReach], ...]:
        """그 capability 를 **어떻게** 얻을 수 있는 노드들. 같은 kind 가 서로 다른
        도달로 올 수 있고, 그 차이가 상류에 보여야 한다."""
        out = []
        for attachment in self.attachments:
            reach = attachment.reach_for(capability_kind)
            if reach is not None:
                out.append((attachment.device_id, reach))
        return tuple(out)


def reach_from_dict(raw: Mapping[str, object]) -> CapabilityReach:
    return CapabilityReach(
        capability_kind=str(raw.get("capability_kind") or ""),
        reach=str(raw.get("reach") or ""),
        unit_id=str(raw.get("unit_id") or ""),
        prerequisites=tuple(str(p) for p in (raw.get("prerequisites") or ())),
        missing_outputs=tuple(str(m) for m in (raw.get("missing_outputs") or ())),
        notes=str(raw.get("notes") or ""),
    )


def attachment_from_dict(raw: Mapping[str, object]) -> DeviceAttachment:
    return DeviceAttachment(
        device_id=str(raw.get("device_id") or ""),
        attachment=str(raw.get("attachment") or ATTACHMENT_STANDALONE),
        carrier_id=str(raw.get("carrier_id") or ""),
        link=str(raw.get("link") or ""),
        reaches=tuple(reach_from_dict(r) for r in (raw.get("reaches") or ())),
        extra={k: v for k, v in raw.items()
               if k not in {"device_id", "attachment", "carrier_id", "link", "reaches"}},
    )


def graph_from_dict(raw: Mapping[str, object]) -> AttachmentGraph:
    rows = raw.get("attachments") if isinstance(raw, Mapping) else None
    return AttachmentGraph(tuple(attachment_from_dict(r) for r in (rows or ())))
