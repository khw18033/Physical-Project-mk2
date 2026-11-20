"""임무가 요구하는 증거의 계약 — 무엇이 모이면 "충분한가".

implements: AI-S-07, AI-S-03, AI-C-01, AI-C-18

**기존 `perception/purpose_requirements.py`와의 관계**(2026-09-22): 그 모듈이 이미
AI-S-07의 required/preferred 분리와 존재 여부 기반 gap 평가를 구현하고 있다. 여기서
그것을 다시 만들지 않는다 — `as_purpose_requirement()`로 **같은 정의를 내보내** 존재
층은 한 곳에만 둔다. 이 모듈이 더하는 것은 네 가지다.

  * `tolerance`  — 있다/없다가 아니라 **쓸 만한가**. 성긴 증거를 충족으로 세면
    조기 정지가 틀린 확정을 만든다(AI-S-03).
  * `granularity` — 목적이 정하는 요구 해상도(Clio). 임계로 암묵 결정하지 않는다.
  * `revision`   — 임무는 운용 중 바뀐다(FOUND-IT). 어느 계약으로 내린 판정인지 남긴다.
  * `unobtainable` — 만들 수 없는 증거는 실패가 아니라 축소 경로다(AI-C-05).

그래서 이 모듈은 **목적 쪽**만 기술한다. 어떤 provider가 그 증거를 만드는지는
`capability_contract.Capability`가 선언하고(AI-C-18), 둘을 대조하는 일은
`decision/evidence_gap.py`가 한다. 세 곳이 같은 `evidence kind` 어휘를 쓰지 않으면
대조 자체가 성립하지 않으므로, 이름은 전부 `contracts/data_dictionary.py`에서 온다.

**tolerance가 없으면 "충족"을 판정할 수 없다.** IoU ≥ τ, 거리오차 ≤ ε 같은 경계가
있어야 비로소 정지 조건이 성립한다. 경계 없이 "있다/없다"로만 보면, 쓸모없이 성긴
증거도 충족으로 세어 조기 정지가 틀린 확정을 만든다(AI-S-03).

**granularity는 목적이 정한다.** 같은 가스레인지라도 조작 임무에서는 손잡이까지,
주행 임무에서는 레인지 전체가 맞는 해상도다(Clio, internal/docs-dev/obsidian/papers/clio.md).
임계를 조정해 암묵적으로 정하지 않고 계약에 적는다.

**revision은 임무가 바뀐다는 사실을 표현한다.** 운용 중 임무가 바뀌면 필요한 증거와
해상도가 함께 바뀐다(FOUND-IT, internal/docs-dev/obsidian/papers/found-it.md). 계약을 불변으로 두고
개정 번호를 올리면, 어느 계약으로 내린 판정인지 사후에 추적할 수 있다(AI-L-08).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mission_runtime.contracts.data_dictionary import (
    REQUIRED_EVIDENCE_NECESSITIES,
    SATISFYING_SUFFICIENCY_STATES,
    SUFFICIENCY_STATES,
)

#: 증거 종류 어휘. provider의 capability kind와 **같은 축**이어야 대조가 된다.
#: 새 종류가 필요하면 여기와 데이터 사전을 먼저 고친다(AI-C-01 원칙 #8).
EVIDENCE_KINDS: tuple[str, ...] = (
    "existence",        # 그 자리에 무언가 있다
    "semantic_class",   # 그것이 무엇인가
    "region_2d",        # 영상 좌표 영역
    "mask",             # 화소 단위 영역
    "geometry_3d",      # 로컬 3D 범위·자세 (전역 변환은 백엔드, AI-C-02)
    "distance",         # 관측점으로부터의 거리
    "track_identity",   # 관측을 가로질러 같은 물체인가
    "calibration",      # 위 값들을 미터로 바꿀 수 있는가
    "cause_hypothesis",  # 관측된 손상의 원인 후보 (도메인 적용층, 확정 아님)
)


@dataclass(frozen=True)
class RequiredEvidence:
    """계약 한 줄 — 어떤 증거가, 얼마나 정밀하게, 필수인가 선택인가."""

    kind: str
    tolerance: float | None = None
    granularity: str | None = None
    necessity: str = "required"

    def __post_init__(self) -> None:
        if self.kind not in EVIDENCE_KINDS:
            raise ValueError(f"모르는 증거 종류: {self.kind} (가능: {EVIDENCE_KINDS})")
        if self.necessity not in REQUIRED_EVIDENCE_NECESSITIES:
            raise ValueError(f"necessity는 {REQUIRED_EVIDENCE_NECESSITIES} 중 하나")

    @property
    def is_required(self) -> bool:
        return self.necessity == "required"


@dataclass(frozen=True)
class MissionContract:
    """한 임무(또는 subtask)가 요구하는 증거 전체.

    `revision`은 **비교 대상이지 순서 번호가 아니다** — 판정 결과에 함께 남겨,
    나중에 "그때 어떤 요구로 충족이라고 봤는가"를 되짚을 수 있게 한다(AI-L-08).
    """

    mission_id: str
    required: tuple[RequiredEvidence, ...]
    revision: int = 1
    zone_id: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        seen = [r.kind for r in self.required]
        dup = {k for k in seen if seen.count(k) > 1}
        if dup:
            # 같은 종류를 두 줄로 요구하면 어느 tolerance를 쓸지 모호해진다.
            raise ValueError(f"증거 종류가 중복됐다: {sorted(dup)}")

    @property
    def required_kinds(self) -> tuple[str, ...]:
        return tuple(r.kind for r in self.required if r.is_required)

    @property
    def preferred_kinds(self) -> tuple[str, ...]:
        return tuple(r.kind for r in self.required if not r.is_required)

    def spec(self, kind: str) -> RequiredEvidence | None:
        for r in self.required:
            if r.kind == kind:
                return r
        return None

    def as_purpose_requirement(self):
        """존재 층을 기존 AI-S-07 구현에 그대로 넘긴다.

        required/preferred가 무엇인가의 정의를 두 곳에 두면 반드시 어긋난다.
        품질(tolerance)·해상도·개정은 이 모듈이 얹고, **무엇이 필수인가는
        `purpose_requirements`가 유일한 정의**로 남는다.
        """
        from mission_runtime.perception.purpose_requirements import (
            PurposeRequirement,
        )
        return PurposeRequirement(
            purpose_id=self.mission_id,
            required_fields=self.required_kinds,
            preferred_fields=self.preferred_kinds,
        )


@dataclass(frozen=True)
class SufficiencyItem:
    """증거 한 종류에 대한 충족 판정과 **그 근거**."""

    kind: str
    state: str
    necessity: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.state not in SUFFICIENCY_STATES:
            raise ValueError(f"state는 {SUFFICIENCY_STATES} 중 하나")


@dataclass(frozen=True)
class SufficiencyVerdict:
    """계약 대비 현재 레코드의 충족 판정.

    **`complete`는 "잘 맞혔다"가 아니라 "계약이 요구한 근거가 모였다"이다.**
    모델 신뢰도와 근거 충분도를 나누라는 AI-S-03이 여기서 실제로 쓰인다 — 이 값이
    True여도 판정이 옳다는 보장은 없고, 조기 정지의 대가는 FCR로 따로 센다.
    """

    mission_id: str
    revision: int
    items: tuple[SufficiencyItem, ...] = field(default_factory=tuple)

    def _by(self, *states: str, required_only: bool = True) -> tuple[SufficiencyItem, ...]:
        return tuple(i for i in self.items
                     if i.state in states
                     and (not required_only or i.necessity == "required"))

    @property
    def complete(self) -> bool:
        """필수 증거가 전부 met인가. **선택 증거는 보지 않는다**(AI-S-07).

        충족 상태를 **열거해서** 묻는다(`SATISFYING_SUFFICIENCY_STATES`). 반대로
        "충족이 아닌 것들" 을 열거하면 새 상태가 그 목록에 빠진 채 조용히 충족으로
        세어진다 — 2026-11-05 에 실제로 그랬다(`provider_mapping_undeclared` 를
        더하고 이 줄을 잊었고, provider 를 한 번도 부르지 않은 레코드가 "계약 충족"
        으로 나왔다).
        """
        return all(item.state in SATISFYING_SUFFICIENCY_STATES
                   for item in self.items if item.necessity == "required")

    @property
    def blocked(self) -> bool:
        """더 해볼 것이 없는가 — provider 를 더 불러도 달라지지 않는 상태다(AI-C-05).

        `unobtainable`(현장에 만들 provider 가 없다)과 `provider_mapping_undeclared`
        (무엇이 만드는지 선언되지 않았다)를 **함께** 센다: 둘 다 provider 호출로는
        풀리지 않는다. 다만 **고칠 곳은 다르다** — 앞은 현장, 뒤는 선언이고, 그
        구분은 `decision/evidence_gap.unanswerable_kinds()` 가 낸다.
        """
        stuck = self._by("unobtainable", "provider_mapping_undeclared")
        return bool(stuck) and not self._by("unmet", "contested")

    @property
    def unmet_kinds(self) -> tuple[str, ...]:
        return tuple(i.kind for i in self._by("unmet"))

    @property
    def contested_kinds(self) -> tuple[str, ...]:
        return tuple(i.kind for i in self._by("contested"))
