"""권고된 조치에 "사람이 어디까지 개입해야 하는가"를 등급으로 붙인다.

implements: AI-C-19, AI-S-05, AI-R-02

2026-09-17, LOTUSim-Energy(docs/obsidian/papers/lotusim-energy.md) 반영. 그
논문은 모든 O&M 태스크에 Teleoperation / Shared / Autonomous 세 모드를 1급
속성으로 붙이고, 같은 점검 작업이라도 위험·불확실성에 따라 사람이 개입하는
정도를 바꾼다. 우리 저장소에는 이 개념이 **코드에 전혀 없었다** — AI-C-19가
"AI는 물리 명령 발급과 실제 제어를 직접 소유하지 않는다"까지만 정하고 있어서,
위험도와 무관하게 모든 권고가 같은 모양으로 나가고 있었다.

**이 모듈이 하지 않는 것(경계)**: 승인 게이트를 구현하지 않는다. 등급을
판단해 권고에 붙이는 것까지가 AI의 몫이고, 실제 승인 절차·버튼·물리 명령
발급은 백엔드·가시화 몫이다(AI-C-19, docs/ai/design/hw-vz-integration-boundary.md
§2-3). 그래서 여기엔 "승인됨/거부됨" 같은 상태가 없다 — 그건 우리가 소유하면
안 되는 상태다.

판단 규칙 자체는 교체 가능해야 한다(AI-C-13: 특정 점수식을 프레임워크 필수
방식으로 고정하지 않는다). 기본 규칙은 근거 충분도와 되돌릴 수 있는지만 보는
최소 형태이고, 배포마다 다른 규칙을 넣고 싶으면 `AutonomyPolicy`를 구현해
갈아끼운다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class AutonomyLevel(str, Enum):
    """사람 개입 정도. 값은 `contracts/data_dictionary.py::AUTONOMY_LEVEL`에
    등록된 어휘와 같다.

    순서에 의미가 있다: 위로 갈수록 사람이 더 많이 개입한다. 판단이 애매하면
    **더 보수적인(사람이 더 개입하는) 등급**으로 올리는 것이 기본 방향이다 --
    로컬 안전 판단이 확신이 없을 때 SAFE_STOP으로 가는 것과 같은 이유
    (reference/local_safety.py).
    """

    AUTONOMOUS = "autonomous"        # 자동 수행 가능
    SHARED = "shared"                # 사람 승인 후 자동 수행
    TELEOPERATED = "teleoperated"    # 사람이 직접 조종


#: 보수적인 순서(자동 -> 조종). 두 판단을 합칠 때 더 보수적인 쪽을 고르는 데 쓴다.
_CONSERVATISM = {
    AutonomyLevel.AUTONOMOUS: 0,
    AutonomyLevel.SHARED: 1,
    AutonomyLevel.TELEOPERATED: 2,
}


def more_conservative(a: AutonomyLevel, b: AutonomyLevel) -> AutonomyLevel:
    """둘 중 사람이 더 많이 개입하는 등급. 서로 다른 근거가 다른 등급을
    가리킬 때 낮은 쪽으로 타협하지 않는다."""
    return a if _CONSERVATISM[a] >= _CONSERVATISM[b] else b


@dataclass(frozen=True)
class ActionContext:
    """등급 판단에 쓰는 입력. 전부 이미 이 프레임워크가 만들어 내는 값이라
    새로 측정해야 하는 것이 없다.

    `evidence_sufficient`: AI-S-03/AI-S-07의 근거 충분도 판정 결과
        (`perception/purpose_requirements.py::EvidenceGap.sufficient` 등).
    `reversible`: 이 조치를 되돌릴 수 있는가. 되돌릴 수 없는 조치(물리적
        접촉, 방류 등)는 근거가 충분해도 사람을 거치게 하는 것이 기본이다.
    `safety_critical`: 안전 판단과 직접 얽힌 조치인가
        (`reference/local_safety.py`가 보수 상태일 때 등).
    """

    evidence_sufficient: bool
    reversible: bool = True
    safety_critical: bool = False


class AutonomyPolicy(Protocol):
    """등급 판단 규칙. 배포마다 교체 가능하다(AI-C-13)."""

    def level_for(self, context: ActionContext) -> AutonomyLevel: ...


class DefaultAutonomyPolicy:
    """최소 기본 규칙 -- 세 입력만 본다.

    이 규칙이 "정답"이라고 주장하지 않는다. 실측으로 정당화된 점수식이 아직
    없으므로, 근거 없는 가중치를 만들어 넣는 대신 뒤집기 어려운 세 조건만
    쓴다:

    1. 안전과 직접 얽힌 조치는 사람이 조종한다 -- 근거가 충분하든 아니든.
    2. 되돌릴 수 없는 조치는 최소한 사람 승인을 거친다.
    3. 근거가 부족하면 사람 승인을 거친다(AI-S-03: 근거 충분도가 확보되지
       않은 결과를 확정 상태로 승격하지 않는다).
    그 외에만 자동 수행을 허용한다.
    """

    def level_for(self, context: ActionContext) -> AutonomyLevel:
        if context.safety_critical:
            return AutonomyLevel.TELEOPERATED
        if not context.reversible or not context.evidence_sufficient:
            return AutonomyLevel.SHARED
        return AutonomyLevel.AUTONOMOUS


@dataclass(frozen=True)
class GradedRecommendation:
    """권고 + 그 권고를 수행할 때의 사람 개입 등급 + 그렇게 판단한 이유.

    `recommendation`/`autonomy_level`은 `contracts/data_dictionary.py`의
    RECOMMENDATION/AUTONOMY_LEVEL과 같은 이름이며, 그대로 업무 경로에 실어
    보낼 수 있다. `basis`는 왜 이 등급인지를 사람이 읽을 수 있게 남긴 것이다 --
    등급만 보내면 소비자가 "왜 승인을 받아야 하지?"에 답할 수 없다.
    """

    recommendation: str
    autonomy_level: AutonomyLevel
    basis: tuple[str, ...]


def grade(
    recommendation: str,
    context: ActionContext,
    policy: AutonomyPolicy | None = None,
) -> GradedRecommendation:
    level = (policy or DefaultAutonomyPolicy()).level_for(context)
    basis = []
    if context.safety_critical:
        basis.append("safety_critical")
    if not context.reversible:
        basis.append("irreversible")
    if not context.evidence_sufficient:
        basis.append("insufficient_evidence")
    return GradedRecommendation(recommendation, level, tuple(basis))
