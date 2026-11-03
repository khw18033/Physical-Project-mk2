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

from mission_runtime.contracts.profile import ResourceBudget

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


class JoinStep(str, Enum):
    """조인 뒤에 남는 할 일. **자동으로 되지 않는 것만** 여기 들어간다."""

    CALIBRATE_CAMERA = "calibrate_camera"
    LEARN_APPEARANCE = "learn_appearance"
    CONFIRM_PLACEMENT = "confirm_placement"
    VERIFY_PROFILE = "verify_execution_profile"


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
    has_camera: bool = False
    calibration_profile_version: str | None = None
    #: 오버레이에서 이 장치를 가리키는 피어 이름. 제품 이름은 provider 뒤에 있다.
    overlay_peer: str | None = None
    #: 어댑터가 구현한 명령 어휘. 실제 탐지는 `Capability` 공지가 하고, 여기 적힌
    #: 것은 "구현했다고 주장한 목록"이다 — 둘이 다르면 그 사실이 드러나야 한다.
    declared_actions: tuple[str, ...] = ()
    contract_version: str = JOIN_CONTRACT_VERSION
    extra: Mapping[str, Any] = field(default_factory=dict)

    def appearance_dir(self, *, root: str) -> str:
        return APPEARANCE_ASSET_TEMPLATE.format(root=root.rstrip("/"),
                                                device_id=self.device_id)


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
        }


def manifest_from_dict(raw: Mapping[str, Any]) -> NodeJoinManifest:
    """wire 에서 올라온 선언을 계약 객체로. 모르는 칸은 `extra` 로 통과시킨다(R12)."""
    known = {
        "device_id", "role", "node_tags", "budget", "appearance_assets",
        "appearance_class", "has_camera", "calibration_profile_version",
        "overlay_peer", "declared_actions", "contract_version",
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
        announced_actions: Iterable[str] = (),
        replace: bool = False,
    ) -> JoinOutcome:
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

        announced = tuple(sorted(set(announced_actions)))
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
        return tuple(steps)

    # -- 조회 -------------------------------------------------------------

    def manifest(self, device_id: str) -> NodeJoinManifest | None:
        return self._manifests.get(device_id)

    def outcome(self, device_id: str) -> JoinOutcome | None:
        return self._outcomes.get(device_id)

    def joined(self) -> tuple[str, ...]:
        return tuple(sorted(self._manifests))

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
    return entry
