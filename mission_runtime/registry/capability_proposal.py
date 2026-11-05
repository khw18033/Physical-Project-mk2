"""기능 하나를 **선언으로 들이는** 길 — 되는지, 어디에 둘지, 안 되면 무엇이 더 필요한지.

implements: AI-B-09 (신규 확장 등록·호환성 검증), AI-B-04 (실행 노드 자원 등록·배치),
            AI-C-18 (구성요소 Capability 선언 규약)
관련: AI-B-01 (미측정 항목은 구분한다), AI-B-13 (수행 불가 기능의 외부 개발 요청),
      AI-C-15 (도메인 차이는 분기문이 아니라 구성), AI-L-10 (조건 기반 배정),
      AI-O-06 (한 스냅샷), AI-C-19 (AI 는 추천하고 발령하지 않는다)
tests: tests/test_capability_proposal.py

## 무엇이 없어서 이 모듈이 생겼나

"3D 맵 구성 기능이 없는데 추가하고 싶다" 를 하려면 지금은 `config/status_ui*.json` 의
`functions[]` 와 `config/providers.*.json` 의 `providers[]` 에 **손으로 한 줄씩** 적고,
그게 어느 노드에 올라갈지는 적용한 **뒤에** 화면에서 본다. 선언 모양 자체는 이미
있고 좋다 — 빠진 것은 **적용 전에 물어보는 입구**다.

`tools/status_ui/serve.py` 에 이미 `/api/whatif` 가 있지만 그것은 **노드 축**이다
("이 노드에 태그·예산을 더하면 어떻게 되나"). 선언 축("이 기능을 선언하면 어디에
들어가나")이 없었다.

## 판정을 새로 만들지 않는다

배치의 정본은 `tools/status_ui/serve.py::StatusService.fleet()` 이고 CLAUDE.md 가
"콘솔이 같은 판정을 다시 하면 두 화면이 서로 다른 답을 말한다" 고 못 박는다. 그래서
이 모듈은 **제안을 정본에 먹이고 그 답을 읽는다**. `PlacementOracle` 이 그 경계이고,
패키지가 `tools/` 를 import 하지 않도록 Protocol 로 받는다(AI-C-04).

이 모듈이 **스스로 하는 판정은 둘뿐**이고, 둘 다 배치와 무관해서 정본에 물어볼
것이 없는 사실이다:

1. **선언이 성립하는가** — 필수 capability 마다 그것을 낼 provider 가 제안 안에
   있는가. 없으면 배치를 물어볼 것도 없다.
2. **비용을 쟀는가** — 아래가 이 모듈의 요점이다.

## 안 쟀으면 0 이 아니다 (AI-B-01, AI-B-09)

새 모델의 `compute_units`·`memory_mb` 를 아무도 재지 않았을 때 그것을 0 으로 두면
**어느 노드에나 들어가는 공짜 기능**이 되고, 배치는 "들어갑니다" 라고 답한다. 실제로
올리면 그 노드가 넘친다. AI-B-09 가 "다른 조합의 품질·비용 프로파일을 자동으로
재사용해서는 안 된다" 고, AI-B-01 이 "미측정 항목은 구분해야 한다" 고 적는 자리가
바로 이것이다.

그래서 비용이 `None` 인 제안은 **거절이 아니라 `needs_measurement`** 다 — 되는지
안 되는지를 아직 말할 수 없고, 운영자가 할 일은 "자원을 더하는 것" 이 아니라 "재는
것" 이다. 둘을 한 사유로 뭉개면 운영자가 엉뚱한 하드웨어를 산다.

## 추천까지이고 발령은 아니다 (AI-C-19)

이 모듈이 내는 것은 후보와 사유다. 선언 파일을 **고치지 않는다** — 적용은 사람이
하는 별개의 행위이고 운영자 수정은 append-only 장부에 쌓인다(AI-L-03,
`tools/fms_console/overlay.py`). 그래서 `ProposalAssessment` 에 "적용했다" 는 칸이
없다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

from mission_runtime.contracts.profile import ResourceCost

#: 제안이 성립하지 않는다 — 필수 capability 를 낼 provider 가 제안 안에 없다.
#: 배치를 물어볼 것도 없는 상태라 정본을 부르지 않는다.
REASON_NO_PROVIDER_FOR_REQUIRED = "no_proposed_provider_for_required_capability"
#: 비용을 재지 않았다. **거절이 아니다** — 아직 말할 수 없다는 뜻이고, 할 일은
#: 자원을 더하는 것이 아니라 재는 것이다(AI-B-01).
REASON_COST_NOT_MEASURED = "resource_cost_not_measured"
#: 선언 자체가 규약에 맞지 않는다(빈 id, 중복 provider_id 등).
REASON_DECLARATION_INVALID = "declaration_invalid"
#: 어느 노드도 필수 태그를 갖추지 못했다. 이때 `missing_tags` 가 무엇이 모자란지 낸다.
REASON_NO_NODE_SATISFIES = "no_node_satisfies_required_tags"
#: 태그는 맞는데 예산이 모자라다. 위와 **다른 사유**다 — 할 일이 다르다(장비를
#: 바꾸는 것 vs 예산을 늘리거나 다른 기능을 줄이는 것).
REASON_BUDGET_EXCEEDED = "node_budget_exceeded"
#: 정본에 물어보지 못했다. "둘 곳이 없다" 가 아니다.
REASON_ORACLE_UNAVAILABLE = "placement_source_unavailable"

PROPOSAL_REASONS: tuple[str, ...] = (
    REASON_NO_PROVIDER_FOR_REQUIRED,
    REASON_COST_NOT_MEASURED,
    REASON_DECLARATION_INVALID,
    REASON_NO_NODE_SATISFIES,
    REASON_BUDGET_EXCEEDED,
    REASON_ORACLE_UNAVAILABLE,
)


class ProposalError(ValueError):
    """선언이 규약에 맞지 않는다. 배치 불가와 **다른 종류**라 예외로 가른다."""


@dataclass(frozen=True)
class ProposedProvider:
    """제안에 들어오는 provider 한 줄. `config/providers.*.json` 과 같은 모양이다.

    모양을 새로 만들지 않는 것이 요점이다 — 제안이 통과하면 그 줄을 **그대로**
    선언 파일에 붙일 수 있어야 하고, 모양이 다르면 옮기면서 번역이 생긴다.
    """

    capability_kind: str
    provider_id: str
    #: 어느 모델·구현인가. 사용자가 "이 모델로" 를 말하는 칸이다.
    implementation_ref: str = ""
    version: str = "1"
    required_hw_tags: tuple[str, ...] = ()
    preferred_hw_tags: tuple[str, ...] = ()
    #: **`None` 은 안 쟀다는 뜻이고 0 이 아니다**(AI-B-01). 0 으로 두면 공짜 기능이
    #: 되어 배치가 "들어갑니다" 라고 답하고, 올리면 그 노드가 넘친다.
    cost: ResourceCost | None = None
    priority: int = 50
    supported_inputs: tuple[str, ...] = ()
    supported_outputs: tuple[str, ...] = ()

    @property
    def cost_measured(self) -> bool:
        return self.cost is not None

    def as_manifest_row(self) -> dict:
        """선언 파일에 그대로 붙일 수 있는 한 줄.

        비용이 미측정이면 `cost` 키를 **싣지 않는다** — 0 을 적으면 그 0 이 실측처럼
        읽히고, 그것이 이 모듈이 막으려는 바로 그 일이다.
        """
        compatibility: dict[str, Any] = {
            "required_hw_tags": list(self.required_hw_tags),
            "preferred_hw_tags": list(self.preferred_hw_tags),
            "priority": self.priority,
        }
        if self.cost is not None:
            compatibility["cost"] = {"compute_units": self.cost.compute_units,
                                     "memory_mb": self.cost.memory_mb}
        row: dict[str, Any] = {
            "capability_kind": self.capability_kind,
            "provider_id": self.provider_id,
            "version": self.version,
            "compatibility": compatibility,
            "requirement": {"required": [], "optional": []},
            "supported_inputs": list(self.supported_inputs),
            "supported_outputs": list(self.supported_outputs),
        }
        if self.implementation_ref:
            # 어느 모델로 돌릴지는 **선언 항목**이고 provider_id 와 다르다 — 같은
            # provider 가 다른 가중치로 도는 것은 다른 실행 구성이다(AI-B-01).
            row["implementation_ref"] = self.implementation_ref
        return row


@dataclass(frozen=True)
class CapabilityProposal:
    """기능 하나를 들이자는 제안. `functions[]` 한 줄 + `providers[]` 몇 줄.

    `optional_capabilities` 는 없어도 되는 것들이다 — 결손이 DEGRADED 까지만
    내리고 DISABLED 로 가지 않는다는 규칙은 `contracts/capability.py` 가 소유하고
    여기서 다시 적지 않는다(AI-C-05).
    """

    function_id: str
    required_capabilities: tuple[str, ...] = ()
    optional_capabilities: tuple[str, ...] = ()
    providers: tuple[ProposedProvider, ...] = ()
    #: 사람이 읽는 한 줄. 판정에 쓰이지 않는다.
    label: str = ""
    #: 왜 이 기능이 필요한가. 거절됐을 때 외부 개발 요청(AI-B-13)으로 넘어가는
    #: 자리이고, 사유 없는 요청은 뒤에서 설명할 수 없다.
    rationale: str = ""

    def __post_init__(self) -> None:
        if not self.function_id.strip():
            raise ProposalError("function_id 가 비어 있다")
        if not self.required_capabilities and not self.optional_capabilities:
            raise ProposalError(
                f"{self.function_id}: capability 를 하나도 적지 않았다 — "
                "무엇을 하는 기능인지가 선언에 없다")
        seen: set[str] = set()
        for provider in self.providers:
            if not provider.capability_kind.strip() or not provider.provider_id.strip():
                raise ProposalError(
                    f"{self.function_id}: provider 의 capability_kind·provider_id 는 "
                    "비울 수 없다")
            if provider.provider_id in seen:
                raise ProposalError(
                    f"{self.function_id}: provider_id 가 겹친다: {provider.provider_id}")
            seen.add(provider.provider_id)

    @property
    def kinds_offered(self) -> frozenset[str]:
        return frozenset(p.capability_kind for p in self.providers)

    def required_without_provider(self) -> tuple[str, ...]:
        """필수인데 제안 안에 그것을 낼 provider 가 없는 kind 들.

        **기존 배치에 이미 그 kind 의 provider 가 있을 수 있다** — 그 판정은 정본이
        하므로 여기서 묻지 않는다. 이 함수는 "제안만으로는 못 채운다" 를 낸다.
        """
        offered = self.kinds_offered
        return tuple(k for k in self.required_capabilities if k not in offered)

    def unmeasured_providers(self) -> tuple[ProposedProvider, ...]:
        return tuple(p for p in self.providers if not p.cost_measured)

    def as_function_row(self) -> dict:
        """`functions[]` 에 그대로 붙일 수 있는 한 줄."""
        return {"function_id": self.function_id,
                "required_capabilities": list(self.required_capabilities),
                "optional_capabilities": list(self.optional_capabilities)}


@dataclass(frozen=True)
class NodeVerdict:
    """한 노드에서 이 기능이 어떻게 되는가. **되는 이유도, 안 되는 이유도 적는다.**"""

    node_id: str
    state: str
    #: 되는 경우에도 비는 것이 있을 수 있다(선택 capability 결손 → DEGRADED).
    reason: str = ""
    #: 그 노드에 **없는 필수 태그**. 운영자가 "무엇을 들여야 하나" 를 읽는 칸이다.
    missing_tags: tuple[str, ...] = ()
    #: 태그는 맞는데 **예산이 모자란** kind 들. 없는 태그와 다른 칸인 이유는 할 일이
    #: 다르기 때문이다 — 하드웨어를 들이는 것과 예산을 늘리거나 다른 기능을 줄이는 것.
    #: 요약 토큰(`no_compatible_provider_within_budget`)은 둘을 한 칸에 담으므로
    #: 그것만 읽으면 운영자가 엉뚱한 쪽을 고친다.
    over_budget_kinds: tuple[str, ...] = ()
    #: 이 기능을 올리면 쓰게 되는 자원. 미측정이면 `None` 이고 0 이 아니다.
    cost: ResourceCost | None = None

    @property
    def usable(self) -> bool:
        return self.state in ("ACTIVE", "DEGRADED")


@dataclass(frozen=True)
class ProposalAssessment:
    """제안 하나에 대한 답 — **되는 곳 · 안 되는 이유 · 더 필요한 것.**

    `checked` 를 따로 두는 이유는 이 파일 전체를 지배하는 규칙과 같다: 정본에
    물어보지 못한 것과 "둘 곳이 없다" 는 다른 사실이고, 빈 목록 하나로 합치면
    선언을 더 손볼 필요가 없는 것처럼 보인다.
    """

    proposal: CapabilityProposal
    verdicts: tuple[NodeVerdict, ...] = ()
    #: 선언·측정 단계에서 걸린 사유들. 비어 있으면 배치 단계까지 갔다는 뜻이다.
    blocking: tuple[str, ...] = ()
    checked: bool = True
    #: 정본에 못 물어봤으면 그 사유.
    reason: str = ""
    #: 어느 노드에도 없는 필수 태그의 합집합 — 운영자가 조달할 목록이다.
    missing_tags: tuple[str, ...] = ()
    #: 재야 할 provider 들(비용 미측정). **이것이 있으면 되는지 안 되는지 모른다.**
    needs_measurement: tuple[str, ...] = ()
    #: 예산을 늘리면 될 노드들. 조달 목록(`missing_tags`)과 **다른 답**이다.
    needs_budget: tuple[str, ...] = ()

    @property
    def recommended(self) -> NodeVerdict | None:
        """추천 한 자리. **갈리지 않으면 고르지 않는다** 가 아니라, 정본이 이미
        선택 규칙(priority → cost → 선언 순서)으로 줄 세운 것의 머리를 집는다 —
        그 규칙을 여기서 다시 만들면 두 화면이 다른 답을 말한다.
        """
        usable = [v for v in self.verdicts if v.usable]
        return usable[0] if usable else None

    @property
    def assignable(self) -> bool:
        """지금 둘 곳이 있는가. **미측정이면 참이 될 수 없다**(AI-B-01)."""
        return (self.checked and not self.blocking
                and self.recommended is not None)

    def as_payload(self) -> dict:
        """화면이 그대로 읽는 한 덩어리. 색·픽셀·표현 결정은 없다."""
        return {
            "function_id": self.proposal.function_id,
            "label": self.proposal.label,
            "assignable": self.assignable,
            "checked": self.checked,
            "reason": self.reason,
            "blocking": list(self.blocking),
            "recommended": (None if self.recommended is None
                            else self.recommended.node_id),
            "nodes": [
                {"node_id": v.node_id, "state": v.state, "reason": v.reason,
                 "missing_tags": list(v.missing_tags),
                 "over_budget_kinds": list(v.over_budget_kinds),
                 "cost": (None if v.cost is None
                          else {"compute_units": v.cost.compute_units,
                                "memory_mb": v.cost.memory_mb})}
                for v in self.verdicts
            ],
            # 운영자가 조달할 것과 **재야 할 것**을 가른다. 뭉개면 재면 되는 일에
            # 하드웨어를 산다.
            # 셋은 **서로 다른 할 일**이다: 하드웨어를 들인다 / 예산을 늘린다 /
            # 재 본다. 하나로 뭉개면 운영자가 엉뚱한 것을 고친다.
            "missing_tags": list(self.missing_tags),
            "needs_budget": list(self.needs_budget),
            "needs_measurement": list(self.needs_measurement),
            # 통과하면 이 두 덩어리를 선언 파일에 그대로 붙인다. 이 모듈은
            # 붙이지 않는다 — 적용은 사람이 하는 별개의 행위다(AI-C-19, AI-L-03).
            "declaration": {
                "function": self.proposal.as_function_row(),
                "providers": [p.as_manifest_row() for p in self.proposal.providers],
            },
        }


class PlacementOracle(Protocol):
    """배치 정본과의 경계. 패키지가 `tools/` 를 import 하지 않는 자리(AI-C-04).

    구현은 `tools/status_ui/serve.py::StatusService` 쪽에 있고, 이 Protocol 은 그
    서비스가 **이미 내는 답**만 요구한다 — 새 판정을 요구하면 정본이 둘이 된다.
    """

    def assess_proposal(
        self, function_row: Mapping[str, Any], provider_rows: Sequence[Mapping[str, Any]]
    ) -> Sequence[Mapping[str, Any]]:
        """제안을 얹었을 때 노드별 결과. 각 항목은 적어도 `node_id` 와 `state` 를
        들고, 있으면 `reason` · `missing_tags` 를 함께 낸다."""
        ...


def assess(proposal: CapabilityProposal, oracle: PlacementOracle | None) -> ProposalAssessment:
    """제안 하나를 재 본다. **선언 파일을 고치지 않는다.**

    순서가 요점이다 — 선언이 성립하는지, 비용을 쟀는지를 **먼저** 보고 그 다음에
    배치를 묻는다. 거꾸로 하면 미측정 비용(0 으로 읽힌)으로 배치가 "들어갑니다" 를
    먼저 말하고, 운영자는 그 답을 기억한 채 측정 경고를 읽는다.
    """
    blocking: list[str] = []

    missing_required = proposal.required_without_provider()
    if missing_required:
        blocking.append(
            f"{REASON_NO_PROVIDER_FOR_REQUIRED}:{','.join(missing_required)}")

    unmeasured = proposal.unmeasured_providers()
    if unmeasured:
        blocking.append(
            f"{REASON_COST_NOT_MEASURED}:{','.join(p.provider_id for p in unmeasured)}")

    if blocking:
        # 배치를 묻지 않는다. 물어봐야 그 답이 **미측정을 0 으로 읽은 답**이다.
        return ProposalAssessment(
            proposal=proposal, blocking=tuple(blocking),
            needs_measurement=tuple(p.provider_id for p in unmeasured))

    if oracle is None:
        return ProposalAssessment(proposal=proposal, checked=False,
                                  reason=REASON_ORACLE_UNAVAILABLE)

    rows = oracle.assess_proposal(proposal.as_function_row(),
                                  [p.as_manifest_row() for p in proposal.providers])
    verdicts = tuple(
        NodeVerdict(
            node_id=str(row.get("node_id") or ""),
            state=str(row.get("state") or "DISABLED"),
            reason=str(row.get("reason") or ""),
            missing_tags=tuple(str(t) for t in (row.get("missing_tags") or ())),
            over_budget_kinds=tuple(str(k) for k in (row.get("over_budget_kinds") or ())),
            cost=_cost_of(row.get("cost")),
        )
        for row in rows
    )
    # 어느 노드에도 없는 태그만 모은다. 한 노드에서만 빠진 태그를 조달 목록에 넣으면
    # 운영자가 이미 되는 구성을 두고 장비를 산다.
    shared_missing: frozenset[str] | None = None
    for verdict in verdicts:
        tags = frozenset(verdict.missing_tags)
        shared_missing = tags if shared_missing is None else (shared_missing & tags)
    return ProposalAssessment(
        proposal=proposal, verdicts=verdicts,
        missing_tags=tuple(sorted(shared_missing or ())),
        # 예산은 **노드마다 따로 늘리는 것**이라 교집합을 쓰지 않는다. 한 노드만
        # 늘려도 그 노드에 둘 수 있으므로 "어디를 늘리면 되는가" 가 답이다.
        needs_budget=tuple(sorted(v.node_id for v in verdicts
                                  if not v.usable and v.over_budget_kinds)))


def _cost_of(raw: Any) -> ResourceCost | None:
    if not isinstance(raw, Mapping):
        return None
    try:
        return ResourceCost(compute_units=float(raw["compute_units"]),
                            memory_mb=float(raw["memory_mb"]))
    except (KeyError, TypeError, ValueError):
        # 비용 칸이 있는데 읽히지 않으면 **0 으로 두지 않는다**. 모른다가 답이다.
        return None


def provider_from_dict(raw: Mapping[str, Any]) -> ProposedProvider:
    """선언 한 줄 → 자료형. `config/providers.*.json` 의 모양을 그대로 받는다."""
    compat = raw.get("compatibility") if isinstance(raw.get("compatibility"), Mapping) else {}
    return ProposedProvider(
        capability_kind=str(raw.get("capability_kind") or ""),
        provider_id=str(raw.get("provider_id") or ""),
        implementation_ref=str(raw.get("implementation_ref") or ""),
        version=str(raw.get("version") or "1"),
        required_hw_tags=tuple(str(t) for t in (compat.get("required_hw_tags") or ())),
        preferred_hw_tags=tuple(str(t) for t in (compat.get("preferred_hw_tags") or ())),
        # `cost` 키가 **없으면** 미측정이다. 있고 읽히지 않아도 미측정이다.
        cost=_cost_of(compat.get("cost")),
        priority=int(compat.get("priority", 50)),
        supported_inputs=tuple(str(s) for s in (raw.get("supported_inputs") or ())),
        supported_outputs=tuple(str(s) for s in (raw.get("supported_outputs") or ())),
    )


def proposal_from_dict(raw: Mapping[str, Any]) -> CapabilityProposal:
    """제안 하나를 JSON 한 덩어리로 받는다 — 웹 폼이 보내는 모양이다."""
    if not isinstance(raw, Mapping):
        raise ProposalError("제안은 JSON 객체여야 한다")
    return CapabilityProposal(
        function_id=str(raw.get("function_id") or ""),
        required_capabilities=tuple(str(k) for k in (raw.get("required_capabilities") or ())),
        optional_capabilities=tuple(str(k) for k in (raw.get("optional_capabilities") or ())),
        providers=tuple(provider_from_dict(p) for p in (raw.get("providers") or ())
                        if isinstance(p, Mapping)),
        label=str(raw.get("label") or ""),
        rationale=str(raw.get("rationale") or ""),
    )
