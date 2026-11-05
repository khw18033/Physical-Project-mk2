"""Adding a robot is four steps and no core-code change.

implements: AI-B-09 (신규 확장 등록·호환성 검증), AI-C-18 (capability 선언 규약)
관련: AI-C-10 (등록·탐색), AI-C-04 (provider 경계), AI-E-02 (보정 lifecycle),
      AI-B-04 (자원 등록), AI-C-19 (가용성 판정은 백엔드)
tests: tests/test_onboarding.py

## 통합하는 사람이 알아야 하는 것 (이것이 전부다)

로봇을 들고 오는 쪽은 이 프레임워크의 코드를 읽지 않는다. 네 가지만 한다.

1. **오버레이에 들어온다** — 같은 보안 오버레이 계정으로 말단을 붙인다. 어떤 제품을
   쓰는지는 `providers/overlay.py` 뒤에 숨고, 이 계약은 "피어 이름으로 닿는다"만
   요구한다.
2. **조인 선언을 한 번 올린다** — `terminal/<device_id>/uplink` 로 `JOIN_MESSAGE_TYPE`
   한 건. 자기 자원 태그, 예산, 외형 이미지 경로, 보정 필요 여부를 적는다.
3. **명령 어휘를 알린다** — 같은 uplink 로 `Capability` 공지(AI-C-18). 이것이 탐지의
   근거이고, 이 목록에 없는 action 은 시스템이 보내지 않는다.
4. **어댑터를 구현한다** — 정본 물리 명령 계약(AI-C-20)을 그 로봇 SDK 호출로 옮기는
   얇은 어댑터. `providers/adapters.py::RobotControlBackend` 네 메서드가 전부다.

그 다음은 시스템이 한다 — 자원·명령을 읽어 레지스트리에 올리고, 화면에 띄우고,
보정과 외형 학습을 할 일 목록에 넣고, 가능한 기능을 산출한다. 이 모듈이 그 "그
다음"의 입구다.

## 선언은 받되 판정은 하지 않는다

조인 선언은 **입력**이다. 장치의 최종 가용성은 백엔드가 업무·관측 상태를 통합해
판정하고(절대 준수 원칙 #15, AI-O-04), 여기서 다시 판정하지 않는다. 그래서
`JoinOutcome.accepted` 는 "쓸 수 있다"가 아니라 "선언이 계약에 맞는다"는 뜻이다.

## 무엇에 실렸고 어떻게 닿는지도 선언이다 (2026-11-04)

실제 지형은 선언이 적던 것과 달랐다 — Pi 가 랜선으로 로봇에 붙어 컨테이너를 들고
있는데, 선언은 로봇과 Pi 를 **서로 무관한 두 노드**로 적었다. `has_camera: bool`
하나로는 로봇 내부 카메라 · Pi 에 단 카메라 · 송수신기가 먼저 떠야 하는 360 유닛을
가를 수 없다. 그래서 선언에 세 축이 더 붙는다 — 부착 · 링크 · 도달
(`contracts/device_attachment.py`). 추가는 **덧붙임**이다: 그 축을 적지 않은
선언은 지금까지처럼 `standalone` 으로 읽히고 `has_camera` 는 카메라 도달이
선언됐을 때 함께 참이 된다. 어긋남(실린 노드가 `tier.edge` 로 적혀 있는 것)은
`runtime/environment_profile.py::report_attachment_conflicts` 가 보고하고, 그것은
**조인 거절이 아니라 남은 할 일이다**(원칙 #15). 어느 역할 태그가 고정 노드를
전제하는지는 **선언이 정한다**(`carried_node_excluded_tags`) — 코드가 목록을 들면
새 현장마다 코드를 고쳐야 한다(원칙 #1·#3). 어휘를 아무도 선언하지 않았으면 그
보고는 "충돌 없음" 이 아니라 `checked=False` 다.

## 빠진 칸을 채워 넣지 않는다

외형 이미지가 없으면 외형 학습을 **할 일로 남기고** 분류를 흉내내지 않는다. 예산을
안 적었으면 0 이 아니라 미측정이다(AI-C-18). 빠진 것을 기본값으로 메우면 그 장치는
"다 갖춘 것"으로 보이고, 실제로 안 되는 순간에야 드러난다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping

from mission_runtime.contracts.device_attachment import (
    ATTACHMENT_STANDALONE,
    REASON_READY,
    AttachmentGraph,
    CapabilityReach,
    DeviceAttachment,
    reach_from_dict,
)
from mission_runtime.contracts.physical_command import Capability as ActionDeclaration
from mission_runtime.contracts.profile import ResourceBudget

#: 이름만 공지된 action 이 적지 못한 AI-C-18 항목 전부. 손으로 적지 않고 계약에
#: 묻는다 — 선언 항목이 늘어나는 날 이 목록이 저절로 따라간다.
ALL_DECLARATION_ITEMS: tuple[str, ...] = ActionDeclaration(name="_probe").undeclared_items()

#: uplink 로 올라오는 조인 선언의 message_type.
JOIN_MESSAGE_TYPE = "node_join"

#: 이 계약의 버전. 선언이 다른 버전을 말하면 받되 그 사실을 남긴다.
JOIN_CONTRACT_VERSION = "1"

#: 외형 이미지가 놓이는 **규약 경로**. 통합하는 쪽은 이 경로만 알면 된다.
#: `{root}` 는 배포가 정하는 자산 루트이고, 픽셀은 업무·관측 메시지가 아니라 미디어
#: 경로로 옮긴다(AI-C-08).
APPEARANCE_ASSET_TEMPLATE = "{root}/appearance/{device_id}/"

#: 장치 id 규약. 토픽과 파일 경로에 그대로 들어가므로 좁게 잡는다.
_DEVICE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")

#: 카메라 영상을 내는 capability kind. `has_camera` 가 말하던 사실을 도달 축에서
#: 다시 찾는 근거이고(AI-E-02 — 카메라가 있으면 보정이 할 일로 남는다), 어휘는
#: `config/status_ui*.json` 의 capability kind 와 같은 것을 쓴다. 장치 이름이나
#: 벤더로 가르지 않는다(원칙 #1·#3).
CAMERA_CAPABILITY_KIND = "media.video_input"


class JoinStep(str, Enum):
    """조인 뒤에 남는 할 일. **자동으로 되지 않는 것만** 여기 들어간다."""

    CALIBRATE_CAMERA = "calibrate_camera"
    LEARN_APPEARANCE = "learn_appearance"
    CONFIRM_PLACEMENT = "confirm_placement"
    VERIFY_PROFILE = "verify_execution_profile"
    #: 송수신기 연결과 자기 실행 코드가 **먼저 떠야** 아무것도 내지 않는 유닛
    #: (360 유닛)이 있다. "없다" 와 "아직 안 떴다" 는 다른 사실이다(AI-C-05).
    BRING_UP_UNIT = "bring_up_attached_unit"
    #: 부착 선언이 성립하지 않는다(싣고 있다는데 상대나 링크가 없다). 조인을
    #: 거절하지 않는 이유는 조인이 가용성 판정이 아니기 때문이다(원칙 #15).
    RESOLVE_ATTACHMENT = "resolve_attachment_declaration"


class JoinRejection(str, Enum):
    MISSING_FIELD = "missing_field"
    BAD_DEVICE_ID = "bad_device_id"
    NO_ACTION_VOCABULARY = "no_action_vocabulary"
    NOT_ON_OVERLAY = "not_reachable_on_overlay"
    DUPLICATE_DEVICE_ID = "duplicate_device_id"


@dataclass(frozen=True)
class NodeJoinManifest:
    """새 장치가 **한 번** 올리는 선언.

    적지 않은 칸은 비어 있는 것이고 기본값이 아니다 — `budget` 이 None 이면 미측정,
    `appearance_assets` 가 비면 외형 학습이 할 일로 남는다.
    """

    device_id: str
    role: str
    #: 자원·하드웨어·런타임을 자유 문자열 태그로. 벤더 enum 이 아니다(AI-B-04).
    node_tags: frozenset[str] = frozenset()
    budget: ResourceBudget | None = None
    #: 규약 경로에 올려 둔 외형 이미지 파일 이름들. 픽셀은 여기 담지 않는다.
    appearance_assets: tuple[str, ...] = ()
    #: 이 장치가 외형 분류에서 가리킬 class 이름(go1 / ep01 / ...). 없으면 학습 대상.
    appearance_class: str | None = None
    #: 카메라를 달고 왔는가 — 달았으면 보정이 할 일로 남는다(AI-E-02).
    #:
    #: **이 한 칸으로는 셋을 가를 수 없다**(로봇 내부 카메라 · 이 노드에 직접 단
    #: 카메라 · 송수신기가 먼저 떠야 하는 별개 유닛). 그래서 아래 부착·링크·도달
    #: 세 축이 생겼고, 이 칸은 그 축의 **유도값**으로 남는다 — 선언이 카메라
    #: 도달을 적으면 여기도 참이 된다. 기존 호출자 여덟 곳은 그대로 돈다.
    has_camera: bool = False
    calibration_profile_version: str | None = None
    #: 무엇에 실려 있나 — `standalone` 또는 `carried_by`(AI-C-18, AI-B-04).
    #: 실린 노드는 **움직인다**. 배치가 그것을 모르면 구역 엣지 몫(브로커·수집기
    #: 급)을 움직이는 로봇에 올린다 — AI-B-10 이 막으라고 한 것이다.
    attachment: str = ATTACHMENT_STANDALONE
    #: 실려 있는 상대. `carried_by` 일 때만 뜻이 있다.
    carrier_id: str = ""
    #: 무엇으로 붙었나(`ethernet`/`usb`/`wireless`/...). 유선이면 공유 운명이다.
    link: str = ""
    #: 각 capability 를 **어떻게 얻는가**. 같은 "카메라 영상" 도 로봇 SDK·호스트
    #: 캡처·송수신기로 오는 길이 다르고, 그 차이를 선언이 흡수해야 상위 코드에
    #: 분기가 생기지 않는다(AI-C-18).
    capability_reaches: tuple[CapabilityReach, ...] = ()
    #: 오버레이에서 이 장치를 가리키는 피어 이름. 제품 이름은 provider 뒤에 있다.
    overlay_peer: str | None = None
    #: 어댑터가 구현한 명령 어휘. 실제 탐지는 `Capability` 공지가 하고, 여기 적힌
    #: 것은 "구현했다고 주장한 목록"이다 — 둘이 다르면 그 사실이 드러나야 한다.
    declared_actions: tuple[str, ...] = ()
    contract_version: str = JOIN_CONTRACT_VERSION
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """카메라 도달을 선언했으면 `has_camera` 도 참이다.

        **빈 칸을 기본값으로 메우는 것이 아니다**(이 모듈의 머리말이 금지하는
        그것) — 같은 사실을 새 축으로 적었을 때 옛 축이 그것을 부정하지 않게
        하는 것이다. 반대 방향으로는 유도하지 않는다: `has_camera=True` 만 적은
        선언에서 도달 방식을 지어내면 그것은 관측이 아니라 추측이다(AI-S-08).
        """
        if self.has_camera:
            return
        if any(reach.capability_kind == CAMERA_CAPABILITY_KIND
               for reach in self.capability_reaches):
            object.__setattr__(self, "has_camera", True)

    def appearance_dir(self, *, root: str) -> str:
        return APPEARANCE_ASSET_TEMPLATE.format(root=root.rstrip("/"),
                                                device_id=self.device_id)

    def attachment_declaration(self) -> DeviceAttachment:
        """세 축을 `contracts/device_attachment.py` 의 계약 객체 하나로.

        여기서 가용성을 계산하지 않는다 — 공유 운명은 선언된 관계이고 "지금 살아
        있는가" 의 답이 아니다(원칙 #15, AI-C-19).
        """
        return DeviceAttachment(
            device_id=self.device_id,
            attachment=self.attachment,
            carrier_id=self.carrier_id,
            link=self.link,
            reaches=self.capability_reaches,
        )


@dataclass(frozen=True)
class JoinOutcome:
    """선언을 받은 결과. 받아들였다는 뜻이 "쓸 수 있다"는 아니다."""

    device_id: str
    accepted: bool
    #: 조인 뒤 남는 할 일. 비어 있으면 바로 쓸 수 있는 상태다.
    next_steps: tuple[JoinStep, ...] = ()
    rejections: tuple[tuple[JoinRejection, str], ...] = ()
    #: 선언한 action 과 실제 공지된 action 의 차이. 어댑터 구현 누락이 여기 보인다.
    undeclared_announcements: tuple[str, ...] = ()
    unannounced_declarations: tuple[str, ...] = ()
    contract_version_mismatch: str | None = None
    notes: tuple[str, ...] = ()
    #: action 이름 -> 그 공지가 **적지 않은** AI-C-18 항목들. 이름만 공지한
    #: 장치는 여기에 항목 전부가 적힌다. 조인을 거절하지 않는 이유는 선언이
    #: 덜 찬 것이 정상 상태이기 때문이고(AI-C-18), 적어 두는 이유는 그 사실이
    #: 보이지 않으면 "선언이 다 왔다" 와 구분되지 않기 때문이다.
    under_declared_actions: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "accepted": self.accepted,
            "next_steps": [step.value for step in self.next_steps],
            "rejections": [{"code": code.value, "detail": detail}
                           for code, detail in self.rejections],
            "undeclared_announcements": list(self.undeclared_announcements),
            "unannounced_declarations": list(self.unannounced_declarations),
            "contract_version_mismatch": self.contract_version_mismatch,
            "notes": list(self.notes),
            "under_declared_actions": {name: list(items) for name, items
                                       in self.under_declared_actions.items()},
        }


def manifest_from_dict(raw: Mapping[str, Any]) -> NodeJoinManifest:
    """wire 에서 올라온 선언을 계약 객체로. 모르는 칸은 `extra` 로 통과시킨다(R12)."""
    known = {
        "device_id", "role", "node_tags", "budget", "appearance_assets",
        "appearance_class", "has_camera", "calibration_profile_version",
        "overlay_peer", "declared_actions", "contract_version",
        "attachment", "carrier_id", "link", "reaches",
    }
    budget_raw = raw.get("budget")
    budget = None
    if isinstance(budget_raw, Mapping):
        # 둘 중 하나라도 없으면 미측정으로 둔다 — 반쪽 예산을 0 으로 메우지 않는다.
        if budget_raw.get("compute_units") is not None and budget_raw.get("memory_mb") is not None:
            budget = ResourceBudget(
                compute_units=float(budget_raw["compute_units"]),
                memory_mb=float(budget_raw["memory_mb"]),
            )
    return NodeJoinManifest(
        device_id=str(raw.get("device_id") or ""),
        role=str(raw.get("role") or ""),
        node_tags=frozenset(raw.get("node_tags") or ()),
        budget=budget,
        appearance_assets=tuple(raw.get("appearance_assets") or ()),
        appearance_class=raw.get("appearance_class") or None,
        has_camera=bool(raw.get("has_camera", False)),
        calibration_profile_version=raw.get("calibration_profile_version") or None,
        overlay_peer=raw.get("overlay_peer") or None,
        declared_actions=tuple(raw.get("declared_actions") or ()),
        contract_version=str(raw.get("contract_version") or JOIN_CONTRACT_VERSION),
        # 와이어에 부착 축이 없는 선언은 `standalone` 으로 읽힌다 — 지금까지의
        # 선언 전부가 그 모양이고, 그래서 추가가 **덧붙임**이다.
        attachment=str(raw.get("attachment") or ATTACHMENT_STANDALONE),
        carrier_id=str(raw.get("carrier_id") or ""),
        link=str(raw.get("link") or ""),
        capability_reaches=tuple(reach_from_dict(r) for r in (raw.get("reaches") or ())),
        extra={k: v for k, v in raw.items() if k not in known},
    )


@dataclass
class NodeOnboarding:
    """조인 선언을 받아 등록과 할 일로 바꾼다. 아무것도 판정하지 않는다."""

    #: 오버레이에서 닿는지 묻는 쪽. 없으면 오버레이 확인을 건너뛰고 그 사실을 남긴다.
    overlay: Any | None = None
    #: 이미 아는 장치 id. 중복 조인을 조용히 덮어쓰지 않는다.
    known_device_ids: set[str] = field(default_factory=set)
    _manifests: dict[str, NodeJoinManifest] = field(default_factory=dict, init=False)
    _outcomes: dict[str, JoinOutcome] = field(default_factory=dict, init=False)
    #: 받아들이지 못한 선언들. **따로** 쌓는 이유는 아래 `submit` 의 주석에 있다.
    _refused: list[JoinOutcome] = field(default_factory=list, init=False)

    def submit(
        self,
        manifest: NodeJoinManifest,
        *,
        announced_actions: Iterable[Any] = (),
        replace: bool = False,
    ) -> JoinOutcome:
        """`announced_actions` 는 action **이름**이거나 AI-C-18 선언 객체
        (`contracts/physical_command.py::Capability`)다. 이름만 주면 그 action 의
        선언 항목은 전부 미선언으로 기록된다 — 지금 와이어가 이름까지만 싣기
        때문에(spec §8-3 P7) 실제 장치는 이 경로로 들어온다.
        """
        rejections: list[tuple[JoinRejection, str]] = []
        notes: list[str] = []

        if not _DEVICE_ID.match(manifest.device_id or ""):
            rejections.append((JoinRejection.BAD_DEVICE_ID, manifest.device_id))
        for field_name in ("role",):
            if not getattr(manifest, field_name):
                rejections.append((JoinRejection.MISSING_FIELD, field_name))
        if not manifest.node_tags:
            # 태그가 없으면 어떤 provider 도 이 노드에 해소되지 않는다 — 조용히 통과시키면
            # "등록은 됐는데 아무 기능도 없는" 장치가 된다.
            rejections.append((JoinRejection.MISSING_FIELD, "node_tags"))

        # 이름과 선언 객체를 같은 입구로 받는다. 이름만 온 공지를 거절하지
        # 않는 것이 요점이다 — 덜 찬 선언도 유효한 선언이다(AI-C-18).
        under_declared: dict[str, tuple[str, ...]] = {}
        names: list[str] = []
        for item in announced_actions:
            if isinstance(item, str):
                names.append(item)
                under_declared[item] = ALL_DECLARATION_ITEMS
                continue
            name = getattr(item, "name", None)
            if not name:
                continue
            names.append(str(name))
            missing = getattr(item, "undeclared_items", None)
            under_declared[str(name)] = tuple(missing()) if callable(missing) else ()
        announced = tuple(sorted(set(names)))
        if not announced and not manifest.declared_actions:
            rejections.append((JoinRejection.NO_ACTION_VOCABULARY, "none announced or declared"))

        if manifest.device_id in self.known_device_ids and not replace:
            rejections.append((JoinRejection.DUPLICATE_DEVICE_ID, manifest.device_id))

        if self.overlay is not None and manifest.overlay_peer:
            if not self.overlay.can_reach(manifest.overlay_peer):
                rejections.append((JoinRejection.NOT_ON_OVERLAY, manifest.overlay_peer))
        elif self.overlay is None:
            notes.append("overlay_not_checked")

        mismatch = (None if manifest.contract_version == JOIN_CONTRACT_VERSION
                    else manifest.contract_version)
        if mismatch:
            notes.append(f"contract_version_declared:{mismatch}")

        declared = set(manifest.declared_actions)
        outcome = JoinOutcome(
            device_id=manifest.device_id,
            accepted=not rejections,
            next_steps=self._next_steps(manifest),
            rejections=tuple(rejections),
            # 공지했지만 선언에 없는 것, 선언했지만 공지되지 않은 것 — 어댑터 구현
            # 누락은 보통 후자로 나타난다.
            undeclared_announcements=tuple(a for a in announced if a not in declared),
            unannounced_declarations=tuple(sorted(declared - set(announced))),
            contract_version_mismatch=mismatch,
            notes=tuple(notes),
            under_declared_actions={name: items for name, items
                                    in sorted(under_declared.items()) if items},
        )
        if outcome.accepted:
            self._manifests[manifest.device_id] = manifest
            self.known_device_ids.add(manifest.device_id)
            self._outcomes[manifest.device_id] = outcome
            return outcome

        # 거절은 **이미 들어온 장치의 결과를 덮지 않는다.** 덮으면 같은 id 로
        # 실수로 한 번 더 올린 순간 그 장치의 `accepted` 가 거짓이 되고, 남아 있던
        # 보정·외형학습·자리확인이 `pending()` 에서 조용히 사라진다 — 할 일이
        # 없어진 것처럼 보이지만 실제로는 아무것도 끝나지 않았다.
        if manifest.device_id in self._outcomes and self._outcomes[manifest.device_id].accepted:
            self._refused.append(outcome)
            return outcome
        self._outcomes[manifest.device_id] = outcome
        return outcome

    @staticmethod
    def _next_steps(manifest: NodeJoinManifest) -> tuple[JoinStep, ...]:
        steps: list[JoinStep] = []
        if manifest.has_camera and not manifest.calibration_profile_version:
            steps.append(JoinStep.CALIBRATE_CAMERA)
        if not manifest.appearance_assets or not manifest.appearance_class:
            # 외형 이미지가 없으면 분류를 흉내내지 않고 학습을 할 일로 남긴다.
            steps.append(JoinStep.LEARN_APPEARANCE)
        steps.append(JoinStep.CONFIRM_PLACEMENT)
        if manifest.budget is None:
            steps.append(JoinStep.VERIFY_PROFILE)
        declaration = manifest.attachment_declaration()
        if declaration.bring_up_required:
            # 송수신기·실행 코드가 떠야 영상이 나오는 유닛. 선언만으로 쓸 수 있는
            # 것처럼 두면 "없다" 와 "아직 안 떴다" 가 한 칸에 들어간다.
            steps.append(JoinStep.BRING_UP_UNIT)
        if declaration.carrier_declaration_reason != REASON_READY:
            # 실렸다고 적었는데 상대나 링크가 없다. 거절이 아니라 남은 할 일이다.
            steps.append(JoinStep.RESOLVE_ATTACHMENT)
        return tuple(steps)

    # -- 조회 -------------------------------------------------------------

    def manifest(self, device_id: str) -> NodeJoinManifest | None:
        return self._manifests.get(device_id)

    def outcome(self, device_id: str) -> JoinOutcome | None:
        return self._outcomes.get(device_id)

    def joined(self) -> tuple[str, ...]:
        return tuple(sorted(self._manifests))

    def attachment_graph(self) -> AttachmentGraph:
        """받아들인 선언들의 부착 관계 전부.

        소비자는 이 그래프로 "무엇이 무엇에 실렸나" 와 "어느 노드가 움직이나" 를
        묻는다(AI-B-10 의 배치 제약, AI-O-04 의 공유 운명). **가용성은 여기서
        나오지 않는다** — 백엔드가 판정한다(원칙 #15).
        """
        return AttachmentGraph(tuple(
            manifest.attachment_declaration()
            for _, manifest in sorted(self._manifests.items())
        ))

    def refused(self) -> tuple[JoinOutcome, ...]:
        """받아들이지 못한 선언들. 조용히 버리지 않는다 — 운영자가 "올렸는데 왜
        안 보이나" 를 물을 수 있어야 거절과 미제출이 구분된다."""
        return tuple(self._refused)

    def pending(self, step: JoinStep) -> tuple[str, ...]:
        """그 할 일이 남아 있는 장치들. 화면의 '해야 할 것' 목록이 이것이다."""
        return tuple(sorted(
            device_id for device_id, outcome in self._outcomes.items()
            if step in outcome.next_steps and outcome.accepted
        ))

    def resolve_step(self, device_id: str, step: JoinStep) -> JoinOutcome | None:
        """할 일 하나를 끝낸 것으로 표시한다. 선언 자체는 바꾸지 않는다."""
        outcome = self._outcomes.get(device_id)
        if outcome is None:
            return None
        updated = JoinOutcome(
            device_id=outcome.device_id,
            accepted=outcome.accepted,
            next_steps=tuple(s for s in outcome.next_steps if s is not step),
            rejections=outcome.rejections,
            undeclared_announcements=outcome.undeclared_announcements,
            unannounced_declarations=outcome.unannounced_declarations,
            contract_version_mismatch=outcome.contract_version_mismatch,
            notes=outcome.notes + (f"resolved:{step.value}",),
            under_declared_actions=outcome.under_declared_actions,
        )
        self._outcomes[device_id] = updated
        return updated


def node_config_entry(manifest: NodeJoinManifest, *, verified: bool = False) -> dict:
    """조인 선언을 `config/status_ui*.json` 의 nodes[] 한 줄로 바꾼다.

    이것이 "시스템이 자원을 자동으로 읽는다"의 구체적인 뜻이다 — 사람이 설정 파일을
    손으로 고치는 대신, 선언이 그대로 배치 계산의 입력이 된다. `verified` 는 기본이
    false 다: 현장 실측 전이라는 표시이고, 기존 설정의 같은 필드와 같은 뜻이다.
    """
    entry: dict[str, Any] = {
        "node_id": manifest.device_id,
        "label": manifest.extra.get("label") or manifest.device_id,
        "role": manifest.role,
        "tags": sorted(manifest.node_tags),
        "verified": verified,
    }
    if manifest.declared_actions:
        # 어휘를 설정 행에 실어 보낸다. 이것이 없으면 소비하는 쪽이 역할 **이름** 으로
        # 어휘를 추측해야 하고, 새 역할의 장치는 그 표에 없다는 이유로 세워지지 않는다
        # (절대 준수 원칙 #3·#7). 장치가 선언한 것을 그대로 옮기는 것이 옳다(AI-C-18).
        entry["declared_actions"] = list(manifest.declared_actions)
    if manifest.budget is not None:
        entry["budget"] = {"compute_units": manifest.budget.compute_units,
                           "memory_mb": manifest.budget.memory_mb}
    if manifest.attachment != ATTACHMENT_STANDALONE or manifest.capability_reaches:
        # **적은 것만 싣는다.** 모든 줄에 `attachment: standalone` 을 붙이면
        # "확인했고 혼자 서 있다" 와 "그 축을 아예 안 적었다" 가 같아진다.
        declaration = manifest.attachment_declaration()
        body: dict[str, Any] = {"attachment": declaration.attachment}
        if declaration.carrier_id:
            body["carrier_id"] = declaration.carrier_id
        if declaration.link:
            body["link"] = declaration.link
        if declaration.reaches:
            body["reaches"] = [reach.as_dict() for reach in declaration.reaches]
        entry["device_attachment"] = body
    return entry
