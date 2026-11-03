"""구역을 넘나드는 말단의 피어·구역 전환 판단.

implements: AI-N-03, AI-C-05, AI-C-19, AI-N-02, AI-B-10
tests: tests/test_zone_handover.py

`ondevice/link_handover.py`는 "지금 원격 기능에 기대도 되는가"(자세)와 "같은
구역 안에서 더 나은 피어가 있는가"(피어 교체)를 이미 판정한다. 여기서 더해지는
질문은 하나뿐이다 — **이 말단이 지금 다른 구역으로 넘어가고 있는가.**

왜 구역이 피어와 다른 축인가
----------------------------
피어를 바꾸는 것은 같은 구역 안에서 더 좋은 상대에게 붙는 일이다. 구역을 바꾸는
것은 그보다 비싸다: 새 구역의 실행 설정·환경 정보·보정 프로파일을 다시 적용해야
하고(AI-N-02), 임무·구성 버전이 구역별로 다를 수 있다. 같은 여유(margin)로 두
전환을 다루면 경계에서 왔다 갔다 할 때마다 구성 재적용이 따라붙는다. 그래서
구역 전환에는 **더 넓은 여유 + 연속 표본 + 최소 체류시간**이라는 세 겹의
이력 조건을 둔다.

세 겹인 이유는 각각 다른 흔들림을 막기 때문이다.

* `zone_switch_margin` — 순간적으로 살짝 더 좋은 옆 구역에 끌려가지 않게 한다.
* `zone_hold_samples` — 한 번 튄 값이 아니라 **연속으로** 우세해야 인정한다.
* `min_zone_dwell_seconds` — 방금 넘어온 구역에서 즉시 되돌아가지 못하게 한다.
* `return_penalty` — 직전에 떠난 구역으로 되돌아갈 때만 추가로 붙는 여유.
  A→B→A→B를 막는 것은 이 항이다. 시간이 지나면(`penalty_decay_seconds`) 사라져
  실제로 되돌아가야 하는 상황까지 막지는 않는다.

바닥 아래에서는 이력 조건을 완화한다
------------------------------------
현재 링크가 이미 floor 이하라면 "지키고 있는 것"이 없다. 이때까지 체류시간을
채우라고 요구하는 것은 안정성이 아니라 그냥 갇혀 있는 것이다. 그래서 자세가
LOCAL_ONLY이고 후보 구역이 floor 위에 있으면 체류시간 조건을 면제한다. 연속
표본 조건은 남긴다 — 후보를 실제로 보긴 해야 한다.

판단과 실행의 경계 (AI-N-03, AI-C-19)
--------------------------------------
이 모듈은 전환을 **요청**할 뿐 수행하지 않는다. 실제 무선 연결 전환·피어 선택은
네트워크·실행 provider의 책임이므로 `observe()`가 `switch_to_zone`을 내놓아도
현재 구역은 바뀌지 않는다. 구역이 실제로 바뀌는 시점은 provider가 성공을 알려
`confirm_zone()`을 호출할 때뿐이다. 요청과 사실을 같은 변수에 담으면 "요청했는데
실패한 전환"이 성공한 것처럼 보인다.

`confirm_zone()`이 돌려주는 `ZoneEntry.requires_config_refresh`는 "이 구역의
외부 구성을 다시 받아 적용해야 한다"는 신호다(AI-N-02). 무엇을 받을지와 검증·
last-known-good은 `ondevice/config_apply.py`의 몫이고 여기서 다시 구현하지 않는다.

지표 중립 (AI-N-03)
-------------------
`PeerObservation.quality`는 `LinkSample.quality`와 같은 정규화 값이다. 무선 규격
이름도 지표 이름도 이 파일에 없다 — 그 이름들이 나타나도 되는 자리는
`providers/rssi_link_quality.py` 같은 provider 구현뿐이다.

측정 실패는 정상 경로다 (AI-C-05)
----------------------------------
`observe_unknown()`은 "못 쟀다"를 "나빴다"로 바꾸지 않고 그대로 센다. 연속으로
못 재는 횟수가 `unknown_tolerance`를 넘으면 그때는 원격 의존을 내린다 — 측정할
수 없는 링크에 계속 기대는 쪽이 더 위험하기 때문이며, 그 경우에도 0.0짜리 가짜
표본을 만들지 않고 `force_local_only()`를 쓴다.

도메인 중립 (절대 준수 원칙 #3)
-------------------------------
`zone_id`는 불투명 문자열이다. 이 파일에는 구역의 종류도, 드론/로봇 분기도 없다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mission_runtime.ondevice.link_handover import (
    LinkDecision,
    LinkPosture,
    LinkSample,
    LinkTransitionPolicy,
)

# --- 사유 통제 어휘 ----------------------------------------------------------
# ':' 앞이 토큰, 뒤가 데이터. 등록처는
# `contracts/data_dictionary.py::ZONE_HANDOVER_REASONS`.

ZONE_UNKNOWN = "zone_unknown"                              # 아직 어느 구역인지 모른다
ZONE_ENTRY_REQUESTED = "zone_entry_requested"              # + ":<zone>" 최초 진입 요청
ZONE_STABLE = "zone_stable"                                # 현재 구역 유지
ZONE_NO_CANDIDATE = "zone_no_other_candidate"              # 다른 구역 후보 자체가 없음
ZONE_CANDIDATE_BELOW_MARGIN = "zone_candidate_below_margin"  # + ":<delta>/<needed>"
ZONE_HOLDING_SAMPLES = "zone_holding_samples"              # + ":<n>/<m>"
ZONE_HOLDING_DWELL = "zone_holding_dwell"                  # + ":<remaining>s"
ZONE_SWITCH_REQUESTED = "zone_switch_requested"            # + ":<zone>"
ZONE_SWITCH_FORCED_BY_FLOOR = "zone_switch_forced_by_floor"  # + ":<zone>"
ZONE_ENTERED = "zone_entered"                              # + ":<zone>" confirm_zone 결과
ZONE_RETURN_PENALISED = "zone_return_penalised"            # + ":<zone>"
LINK_UNKNOWN = "link_quality_unmeasured"                   # + ":<n>/<tolerance>"
LINK_UNKNOWN_FORCED_LOCAL = "link_unmeasured_forced_local"  # + ":<n>"

ZONE_HANDOVER_REASONS: tuple[str, ...] = (
    ZONE_UNKNOWN,
    ZONE_ENTRY_REQUESTED,
    ZONE_STABLE,
    ZONE_NO_CANDIDATE,
    ZONE_CANDIDATE_BELOW_MARGIN,
    ZONE_HOLDING_SAMPLES,
    ZONE_HOLDING_DWELL,
    ZONE_SWITCH_REQUESTED,
    ZONE_SWITCH_FORCED_BY_FLOOR,
    ZONE_ENTERED,
    ZONE_RETURN_PENALISED,
    LINK_UNKNOWN,
    LINK_UNKNOWN_FORCED_LOCAL,
)


@dataclass(frozen=True)
class PeerObservation:
    """지금 보이는 상대 하나. `quality`는 `LinkSample.quality`와 같은 정규화 값.

    `zone_id`가 `None`이면 "이 상대가 어느 구역인지 모른다"는 뜻이고, 구역
    전환 후보로는 쓰이지 않는다 — 모르는 구역으로 넘어가면 어떤 구성을 적용해야
    하는지도 모른다.
    """

    peer_id: str
    quality: float
    zone_id: str | None = None


@dataclass(frozen=True)
class ZoneHandoverDecision:
    """한 번의 관측이 만든 판단. 전환은 여기서 **요청**될 뿐 일어나지 않는다."""

    posture: LinkPosture
    #: 지금 붙어 있다고 확인된 구역(`confirm_zone`으로만 바뀐다).
    zone_id: str | None
    peer_id: str | None
    #: 같은 구역 안에서의 피어 교체 제안(기존 정책이 판정).
    switch_to_peer: str | None
    #: 다른 구역으로 넘어가자는 요청. provider가 수행하고 결과를 confirm한다.
    switch_to_zone: str | None
    switch_to_zone_peer: str | None
    zone_reason: str
    link: LinkDecision | None
    quality: float | None = None

    @property
    def requests_zone_switch(self) -> bool:
        return self.switch_to_zone is not None


@dataclass(frozen=True)
class ZoneEntry:
    """구역 전환이 실제로 일어났다는 사실. 요청과 구분된다."""

    zone_id: str
    previous_zone: str | None
    #: AI-N-02: 새 구역의 외부 구성을 다시 받아 검증·적용해야 한다.
    requires_config_refresh: bool
    reason: str
    #: 직전에 떠났던 구역으로 곧장 되돌아온 전환인가(경계 진동의 흔적).
    is_return: bool = False


@dataclass
class ZoneHandoverPolicy:
    """구역 인지형 전환 판단. 링크 자세 판정은 기존 정책에 위임한다.

    상속이 아니라 합성인 이유: 자세 판정(축소·복귀·피어 교체)은
    `LinkTransitionPolicy`가 이미 소유하고 있고, 그 규칙을 여기서 다시 쓰면
    배치 시점 판정(`runtime/residency.py`)과 기준이 갈라진다.
    """

    transition: LinkTransitionPolicy = field(default_factory=LinkTransitionPolicy)
    #: 구역 전환에 요구하는 품질 우세폭. 같은 구역 내 피어 교체
    #: (`LinkTransitionPolicy.switch_margin`)보다 넓어야 한다 — 구역 전환은
    #: 구성 재적용을 동반하므로 더 비싸다.
    zone_switch_margin: float = 0.25
    #: 후보 구역이 연속으로 우세해야 하는 표본 수.
    zone_hold_samples: int = 3
    #: 방금 넘어온 구역에서 다시 넘어가기까지의 최소 체류시간(초).
    min_zone_dwell_seconds: float = 5.0
    #: 직전에 떠난 구역으로 되돌아갈 때만 붙는 추가 여유.
    return_penalty: float = 0.10
    #: 그 추가 여유가 유지되는 시간. 지나면 정상 여유로 돌아간다.
    penalty_decay_seconds: float = 30.0
    #: 연속으로 이만큼 측정에 실패하면 원격 의존을 내린다.
    unknown_tolerance: int = 3

    _zone: str | None = None
    _zone_since: float | None = None
    _left_zone: str | None = None
    _left_at: float | None = None
    _pending_zone: str | None = None
    _pending_run: int = 0
    _unknown_run: int = 0
    #: 실제로 일어난 구역 전환 횟수와 그중 되돌아간 횟수. 후자가 경계 진동이다.
    zone_changes: int = 0
    zone_returns: int = 0

    # --- 조회 ---------------------------------------------------------------

    @property
    def zone_id(self) -> str | None:
        return self._zone

    @property
    def posture(self) -> LinkPosture:
        return self.transition.posture

    # --- 관측 ---------------------------------------------------------------

    def observe(
        self,
        sample: LinkSample,
        peers: list[PeerObservation] | tuple[PeerObservation, ...] = (),
    ) -> ZoneHandoverDecision:
        """관측 1건 → 판단. 현재 구역은 절대 여기서 바뀌지 않는다."""
        self._unknown_run = 0
        current = self._zone

        # 같은 구역 후보만 기존 정책에 넘긴다. 다른 구역 후보를 섞으면 구역
        # 전환이 피어 교체의 여유(좁은 쪽)로 결정돼 버린다.
        same_zone = [p for p in peers if current is not None and p.zone_id == current]
        link = self.transition.observe(
            sample, [(p.peer_id, p.quality) for p in same_zone]
        )

        zone_reason, switch_zone, switch_peer = self._evaluate_zone(sample, peers, link)
        return ZoneHandoverDecision(
            posture=link.posture,
            zone_id=current,
            peer_id=sample.peer_id,
            switch_to_peer=link.switch_to,
            switch_to_zone=switch_zone,
            switch_to_zone_peer=switch_peer,
            zone_reason=zone_reason,
            link=link,
            quality=sample.quality,
        )

    def observe_unknown(self, at: float, reason: str = "") -> ZoneHandoverDecision:
        """측정하지 못했다. "나쁘다"가 아니라 "모른다"로 센다(AI-C-05).

        연속 실패가 `unknown_tolerance`를 넘으면 원격 의존만 내린다. 가짜
        표본을 만들지 않으므로 추세·복귀 판정이 오염되지 않는다.
        """
        self._unknown_run += 1
        if self._unknown_run >= self.unknown_tolerance:
            self.transition.force_local_only()
            zone_reason = f"{LINK_UNKNOWN_FORCED_LOCAL}:{self._unknown_run}"
        else:
            zone_reason = f"{LINK_UNKNOWN}:{self._unknown_run}/{self.unknown_tolerance}"
        return ZoneHandoverDecision(
            posture=self.transition.posture, zone_id=self._zone, peer_id=None,
            switch_to_peer=None, switch_to_zone=None, switch_to_zone_peer=None,
            zone_reason=zone_reason if not reason else f"{zone_reason}|{reason}",
            link=None, quality=None,
        )

    def _evaluate_zone(
        self,
        sample: LinkSample,
        peers,
        link: LinkDecision,
    ) -> tuple[str, str | None, str | None]:
        current = self._zone
        if current is None:
            # 아직 어느 구역에 있는지 확인된 적이 없다. 관측에서 보이는 구역으로의
            # 진입을 요청할 뿐, 스스로 들어갔다고 치지 않는다.
            target = sample.zone_id or self._best_known_zone(peers)
            if target is None:
                return ZONE_UNKNOWN, None, None
            peer = self._best_peer_in(peers, target)
            self._pending_zone = None
            self._pending_run = 0
            return (
                f"{ZONE_ENTRY_REQUESTED}:{target}",
                target,
                peer.peer_id if peer else sample.peer_id,
            )

        candidate = self._best_other_zone_peer(peers, current)
        if candidate is None:
            self._pending_zone = None
            self._pending_run = 0
            return ZONE_NO_CANDIDATE, None, None

        at_floor = sample.quality <= self.transition.floor
        needed = self.zone_switch_margin
        penalised = False
        if (
            self._left_zone == candidate.zone_id
            and self._left_at is not None
            and sample.at - self._left_at < self.penalty_decay_seconds
        ):
            needed += self.return_penalty
            penalised = True

        delta = candidate.quality - sample.quality
        if at_floor:
            # 지킬 것이 없는 상태에서는 우세폭 대신 "후보가 실제로 쓸 만한가"만 본다.
            usable = candidate.quality > self.transition.floor
            if not usable:
                self._pending_zone = None
                self._pending_run = 0
                return ZONE_NO_CANDIDATE, None, None
        elif delta < needed:
            self._pending_zone = None
            self._pending_run = 0
            reason = f"{ZONE_CANDIDATE_BELOW_MARGIN}:{delta:.3f}/{needed:.3f}"
            return (f"{reason}|{ZONE_RETURN_PENALISED}:{candidate.zone_id}" if penalised
                    else reason), None, None

        if self._pending_zone == candidate.zone_id:
            self._pending_run += 1
        else:
            self._pending_zone = candidate.zone_id
            self._pending_run = 1

        if self._pending_run < self.zone_hold_samples:
            return (
                f"{ZONE_HOLDING_SAMPLES}:{self._pending_run}/{self.zone_hold_samples}",
                None,
                None,
            )

        if not at_floor and self._zone_since is not None:
            elapsed = sample.at - self._zone_since
            if elapsed < self.min_zone_dwell_seconds:
                remaining = self.min_zone_dwell_seconds - elapsed
                return f"{ZONE_HOLDING_DWELL}:{remaining:.2f}s", None, None

        token = ZONE_SWITCH_FORCED_BY_FLOOR if at_floor else ZONE_SWITCH_REQUESTED
        return f"{token}:{candidate.zone_id}", candidate.zone_id, candidate.peer_id

    # --- 사실 반영 -----------------------------------------------------------

    def confirm_zone(self, zone_id: str, *, at: float) -> ZoneEntry:
        """provider가 전환에 성공했다고 알려 올 때만 현재 구역이 바뀐다."""
        previous = self._zone
        is_return = previous is not None and zone_id == self._left_zone
        if previous is not None and zone_id == previous:
            return ZoneEntry(zone_id, previous, False, f"{ZONE_STABLE}:{zone_id}")
        self._left_zone = previous
        self._left_at = at if previous is not None else None
        self._zone = zone_id
        self._zone_since = at
        self._pending_zone = None
        self._pending_run = 0
        self.zone_changes += 1
        if is_return:
            self.zone_returns += 1
        return ZoneEntry(
            zone_id=zone_id,
            previous_zone=previous,
            requires_config_refresh=True,
            reason=f"{ZONE_ENTERED}:{zone_id}",
            is_return=is_return,
        )

    # --- 보조 ---------------------------------------------------------------

    @staticmethod
    def _best_peer_in(peers, zone_id: str) -> PeerObservation | None:
        in_zone = [p for p in peers if p.zone_id == zone_id]
        return max(in_zone, key=lambda p: p.quality) if in_zone else None

    @staticmethod
    def _best_known_zone(peers) -> str | None:
        known = [p for p in peers if p.zone_id is not None]
        return max(known, key=lambda p: p.quality).zone_id if known else None

    @staticmethod
    def _best_other_zone_peer(peers, current: str) -> PeerObservation | None:
        others = [p for p in peers if p.zone_id is not None and p.zone_id != current]
        return max(others, key=lambda p: p.quality) if others else None

    def status(self) -> dict:
        """구역 전환은 링크 품질과 **다른 신호**다. 한 칸에 합치지 않는다."""
        return {
            "signal": "zone_handover",
            "zone_id": self._zone,
            "posture": self.transition.posture.value,
            "zone_changes": self.zone_changes,
            "zone_returns": self.zone_returns,
            "pending_zone": self._pending_zone,
            "unmeasured_run": self._unknown_run,
        }
