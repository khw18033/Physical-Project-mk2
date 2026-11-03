"""Grounds a generated task-template proposal in capabilities that actually exist.

implements: AI-B-14 (서브태스크 산출의 capability 접지)
관련: AI-B-13 (수행 불가 → 외부 개발 요청), AI-B-08 (실행 제공자 추상화),
      AI-C-05 (생성이 꺼져도 나머지는 돈다), AI-C-19 (AI 는 명령을 발급하지 않는다),
      AI-C-16 (폐쇄망에서 외부 서비스는 선택 기능)

`planning/decomposition.py` 는 처음부터 이 자리를 비워 두었다 — "LLM planner 를 쓰고
싶다면 `TaskTemplate` 를 생성하는 선택 provider 로 붙이면 되고, 이 모듈의 검증·구체화
계약은 그대로 유지된다." 이 파일이 그 provider 경계와 **접지 검사**다. 생성된 것을
그대로 쓰지 않는다.

## 왜 접지가 핵심인가

생성 모델은 그럴듯한 단계를 만든다. 그럴듯함과 **이 기계에서 실행 가능함**은 다른
문제이고, 둘을 구분하지 않으면 계획은 통과하고 실행만 실패한다. 그래서 두 가지를 한다.

1. **어휘를 먼저 좁힌다.** 모델에게 자유 문장을 받지 않고, 지금 registry 에 provider 가
   있는 capability kind 목록(`CapabilityMenu`)만 쓰게 한다.
2. **목록 밖을 거부한다.** 거부한 것은 버리지 않고 **외부 개발 요청 후보**로 남긴다
   (AI-B-13) — "이 기능이 필요한데 여기에 없다"는 사실이 그 자체로 쓸 정보다.

## 의존은 모델이 만들지 않는다

가시화 파트가 같은 결론에 먼저 도달했다(`generate/solveDeps.ts`): 모델은 노드 목록만
내고 의존은 규칙으로 계산한다. 근거 없는 상태에서 의존 배열을 직접 내게 하면 순환·고아
노드가 나온다. 여기서는 `StepTemplate` 순서열이 곧 실행 순서이므로 **모델이 순환을
만들 수 있는 자리가 아예 없다.**

## 참고한 최근 연구와 그 중 무엇을 가져왔나

| 연구 | 가져온 것 |
|---|---|
| EmboTeam (arXiv 2601.11063) — 로봇 팀의 skill graph 로 분해하고 물리 능력에 따라 배정 | **어휘를 능력 목록으로 좁힌다**는 축. 우리 쪽 대응물이 capability registry 이고, 배정은 기존 `select_executor` 가 한다 |
| Embodied Zero-Shot Task Planning (arXiv 2610.14106) — LLM 은 **스키마 검증을 통과한 기호 산출만** 내고 접지·제어는 결정적 모듈이 한다 | 생성물을 dict 로만 받고 검증 뒤에만 우리 자료구조로 올린다. 저수준 제어는 애초에 우리 소관이 아니다(AI-C-19) |
| AgentVLA (Embodied AI 2026) — 단계별 진단 기록 | 거부 사유를 단계별 토큰으로 남긴다. "생성 실패" 한 줄로 뭉치지 않는다 |
| SkillWrapper (arXiv 2511.18203) — 계획을 위한 술어 발명 | **가져오지 않았다.** 새 술어를 모델이 만들면 접지할 대상이 사라진다. 어휘 확장은 사람이 capability 를 등록하는 일로 둔다 |

우열을 주장하지 않는다 — 이 선택들은 "우리 구조와 맞는 부분만 취했다"는 뜻이고,
어느 방법이 더 나은지는 동일 조건 비교로 정할 일이다(AI-B-01).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence

from mission_runtime.contracts.capability import CapabilityRequirement
from mission_runtime.planning.decomposition import StepTemplate, TaskTemplate
from mission_runtime.registry.capability_registry import CapabilityRegistry

#: 거부 사유 토큰. 표시 문구는 화면이 만든다.
REASON_ACCEPTED = "accepted"
REASON_UNKNOWN_CAPABILITY = "unknown_capability"
REASON_NO_CAPABILITY_NAMED = "no_capability_named"
REASON_MISSING_ACTION = "missing_action"
REASON_DUPLICATE_ACTION = "duplicate_action"
REASON_TOO_MANY_STEPS = "too_many_steps"
REASON_NOT_A_MAPPING = "not_a_mapping"
REASON_PARAMS_NOT_A_MAPPING = "params_not_a_mapping"
REASON_EMPTY_PROPOSAL = "empty_proposal"
REASON_NO_PROVIDER = "no_generation_provider"
REASON_PROVIDER_FAILED = "generation_provider_failed"
REASON_NO_STEP_ACCEPTED = "no_step_accepted"

#: 한 제안에서 받아들일 최대 단계 수. 상한이 없으면 모델이 끝없이 늘릴 수 있고, 그
#: 계획은 사람이 승인 화면에서 읽을 수 없다. 배포가 바꿀 수 있는 값이다.
DEFAULT_MAX_STEPS = 12


@dataclass(frozen=True)
class CapabilityMenu:
    """생성에 **허용된 어휘**. 지금 provider 가 있는 capability kind 뿐이다.

    목록을 만들 때 "등록된 전부"가 아니라 "지금 쓸 수 있는 것"을 쓴다 — 등록만 되어
    있고 provider 가 없는 kind 를 어휘에 넣으면, 접지는 통과하고 실행에서 떨어진다.
    """

    kinds: tuple[str, ...] = ()

    @staticmethod
    def from_registry(registry: CapabilityRegistry) -> CapabilityMenu:
        usable = sorted(
            kind for kind in registry.known_capability_kinds()
            if registry.available_providers(kind)
        )
        return CapabilityMenu(tuple(usable))

    def __contains__(self, kind: object) -> bool:
        return kind in self.kinds

    def as_prompt_lines(self) -> str:
        """생성 제공자에게 넘길 어휘 목록. 사람이 읽어도 같은 뜻이어야 한다."""
        return "\n".join(f"- {kind}" for kind in self.kinds)


@dataclass(frozen=True)
class ProposalRequest:
    """무엇을 위한 계획인가. `goal_text` 는 사람이 준 문장 원문이다."""

    goal_kind: str
    goal_text: str
    menu: CapabilityMenu
    max_steps: int = DEFAULT_MAX_STEPS

    def __post_init__(self) -> None:
        if not self.goal_kind:
            raise ValueError("goal_kind must not be empty")
        if self.max_steps < 1:
            raise ValueError("max_steps must be at least 1")


class TemplateProposalProvider(Protocol):
    """생성 제공자 경계. **우리 자료구조를 넘기지도 받지도 않는다.**

    오가는 것은 평평한 dict 뿐이다 — 그래야 어떤 외부 런타임을 꽂아도 그 SDK 가 우리
    계약 타입을 보지 않고, 우리도 그 타입을 보지 않는다(AI-B-08, AI-C-04).
    """

    provider_id: str

    def propose(self, request: ProposalRequest) -> Sequence[Mapping[str, Any]]: ...


@dataclass(frozen=True)
class StepRejection:
    """받아들이지 못한 단계 하나와 그 이유."""

    index: int
    reason: str
    detail: str | None = None
    #: 목록 밖 capability 를 가리켰다면 그 이름. 외부 개발 요청의 재료다(AI-B-13).
    requested_capability: str | None = None


@dataclass(frozen=True)
class GroundingResult:
    """접지 결과. 받아들인 것과 거부한 것을 **함께** 낸다.

    `template is None` 은 오류가 아니라 "쓸 수 있는 단계가 하나도 없었다"는 상태다.
    호출자는 기존 템플릿 라이브러리로 돌아가거나 외부 요청을 올린다.
    """

    template: TaskTemplate | None
    reason: str
    rejected: tuple[StepRejection, ...] = ()
    provider_id: str | None = None

    @property
    def escalation_capabilities(self) -> tuple[str, ...]:
        """외부 개발 요청으로 올릴 capability 이름들(중복 제거, 순서 고정)."""
        seen: list[str] = []
        for rejection in self.rejected:
            name = rejection.requested_capability
            if name and name not in seen:
                seen.append(name)
        return tuple(seen)


#: 단계 dict 에서 우리가 읽는 칸. 그 밖의 칸은 **무시한다**(거부하지 않는다) — 생성
#: 제공자가 자기 진단 정보를 붙여 보내는 것을 막을 이유가 없고, 모르는 칸을 이유로
#: 계획을 버리면 쓸 수 있는 계획을 잃는다.
STEP_FIELDS = ("action", "capability", "optional_capabilities", "preconditions",
               "forbidden_if", "params")


@dataclass
class TemplateGrounder:
    """생성된 제안을 검사해 `TaskTemplate` 로 올린다. 올리지 못한 것은 사유로 남는다."""

    menu: CapabilityMenu
    version_prefix: str = "proposed"

    def ground(
        self,
        request: ProposalRequest,
        raw_steps: Sequence[Mapping[str, Any]],
        *,
        provider_id: str | None = None,
    ) -> GroundingResult:
        if not raw_steps:
            return GroundingResult(None, REASON_EMPTY_PROPOSAL, (), provider_id)

        steps: list[StepTemplate] = []
        rejected: list[StepRejection] = []
        seen_actions: set[str] = set()

        for index, raw in enumerate(raw_steps):
            if len(steps) >= request.max_steps:
                rejected.append(StepRejection(index, REASON_TOO_MANY_STEPS,
                                              f"max_steps={request.max_steps}"))
                continue
            step, rejection = self._one(index, raw, seen_actions)
            if step is None:
                rejected.append(rejection)  # type: ignore[arg-type]
                continue
            seen_actions.add(step.action)
            steps.append(step)

        if not steps:
            return GroundingResult(None, REASON_NO_STEP_ACCEPTED, tuple(rejected), provider_id)

        template = TaskTemplate(
            goal_kind=request.goal_kind,
            # 버전에 제공자를 적는다 — 어느 생성물에서 나온 계획인지 되짚을 수 있어야
            # 한다(AI-L-08 계보). 사람이 쓴 템플릿과 섞이지 않게 접두어를 붙인다.
            version=f"{self.version_prefix}:{provider_id or 'unknown'}:{len(steps)}",
            steps=tuple(steps),
        )
        return GroundingResult(template, REASON_ACCEPTED, tuple(rejected), provider_id)

    def _one(
        self, index: int, raw: Mapping[str, Any], seen_actions: set[str]
    ) -> tuple[StepTemplate | None, StepRejection | None]:
        if not isinstance(raw, Mapping):
            return None, StepRejection(index, REASON_NOT_A_MAPPING)

        action = raw.get("action")
        if not isinstance(action, str) or not action.strip():
            return None, StepRejection(index, REASON_MISSING_ACTION)
        action = action.strip()
        if action in seen_actions:
            return None, StepRejection(index, REASON_DUPLICATE_ACTION, action)

        capability = raw.get("capability")
        if not isinstance(capability, str) or not capability.strip():
            return None, StepRejection(index, REASON_NO_CAPABILITY_NAMED, action)
        capability = capability.strip()
        if capability not in self.menu:
            # 목록 밖이다. 버리지 않고 외부 요청 후보로 남긴다(AI-B-13).
            return None, StepRejection(index, REASON_UNKNOWN_CAPABILITY, action, capability)

        optional = tuple(
            name.strip() for name in _as_str_tuple(raw.get("optional_capabilities"))
            # 선택 capability 는 목록 밖이면 **조용히 뺀다** — 없으면 DEGRADED 로만
            # 내려가는 자리이므로 계획을 버릴 이유가 아니다(AI-C-05).
            if name.strip() in self.menu
        )

        params = raw.get("params", {})
        if not isinstance(params, Mapping):
            return None, StepRejection(index, REASON_PARAMS_NOT_A_MAPPING, action)

        return StepTemplate(
            action=action,
            requirement=CapabilityRequirement(required=(capability,), optional=optional),
            preconditions=_as_str_tuple(raw.get("preconditions")),
            forbidden_if=_as_str_tuple(raw.get("forbidden_if")),
            params=dict(params),
        ), None


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(item for item in value if isinstance(item, str) and item.strip())
    return ()


# ---------------------------------------------------------------------------
# 제공자 둘 — 생성 서비스가 없는 배치가 기본형이다
# ---------------------------------------------------------------------------


@dataclass
class KeywordTemplateProposalProvider:
    """**모델이 아니다.** 선언된 낱말-capability 대응으로 단계를 만든다.

    생성 서비스가 없는 배치(심사·폐쇄망·현장 단독)가 기본형이고, 그때도 계획이 나와야
    한다. 가시화 쪽이 같은 규칙을 코드로 붙잡아 둔 것과 같은 이유다 — 꺼지는 것은
    생성 하나뿐이어야 한다(AI-C-05, AI-C-16).

    대응표는 **데이터**다. 새 낱말을 넣는 것이 코드 변경이 아니고, 표에 있어도 메뉴에
    없는 capability 는 접지에서 걸러진다.
    """

    provider_id: str = "keyword_template"
    #: {낱말: (action, capability kind)} — 배포가 준다.
    vocabulary: Mapping[str, tuple[str, str]] = field(default_factory=dict)

    def propose(self, request: ProposalRequest) -> Sequence[Mapping[str, Any]]:
        text = request.goal_text.lower()
        steps: list[Mapping[str, Any]] = []
        for word, (action, capability) in self.vocabulary.items():
            if word.lower() in text:
                steps.append({"action": action, "capability": capability})
        return steps


#: 생성 호출 하나. 문자열을 넣고 문자열을 받는다 — **어떤 SDK 도 여기 들어오지 않는다.**
CompletionCallable = Callable[[str], str]

PROMPT_TEMPLATE = """\
다음 목표를 실행 단계 목록으로 나눠라.

목표: {goal_text}

규칙:
- 아래 **capability 목록에 있는 것만** 쓴다. 목록에 없는 기능이 필요하면 그 이름을
  그대로 적되, 그 단계는 받아들여지지 않고 "기능 없음"으로 보고된다.
- 단계 수는 {max_steps} 개 이하.
- 의존 관계를 적지 않는다. 목록 순서가 실행 순서다.
- JSON 배열만 출력한다. 각 원소는 {{"action": "...", "capability": "..."}} 이고
  필요하면 "optional_capabilities", "preconditions", "params" 를 더할 수 있다.

capability 목록:
{menu}
"""


@dataclass
class LlmTemplateProposalProvider:
    """생성 모델 어댑터. 모델이 내놓은 **기호 산출만** 받는다.

    세 가지를 지킨다.
      - 프롬프트에 **메뉴를 실어 보낸다**(어휘 접지).
      - 출력은 JSON 배열만 받고, 모양이 틀리면 **조용히 빈 제안**으로 내려간다 —
        예외를 올리면 생성 실패가 운영 실행을 멈춘다(AI-C-05).
      - 모델이 무엇을 냈는지 `last_raw_output` 에 남긴다. 승인 화면과 재현에 필요하다.

    실제 호출은 `complete` 콜러블이 한다. 그래서 이 모듈은 어떤 공급자·엔드포인트·
    인증도 모르고, 폐쇄망에서는 콜러블이 없을 뿐이다(AI-C-16).
    """

    complete: CompletionCallable
    provider_id: str = "llm_template"
    last_raw_output: str | None = field(default=None, repr=False)

    def propose(self, request: ProposalRequest) -> Sequence[Mapping[str, Any]]:
        import json

        prompt = PROMPT_TEMPLATE.format(
            goal_text=request.goal_text,
            max_steps=request.max_steps,
            menu=request.menu.as_prompt_lines() or "- (없음)",
        )
        try:
            raw = self.complete(prompt)
        except Exception:
            self.last_raw_output = None
            return ()
        self.last_raw_output = raw
        try:
            parsed = json.loads(_strip_code_fence(raw))
        except (ValueError, TypeError):
            return ()
        if isinstance(parsed, Mapping):
            parsed = parsed.get("steps", [])
        if not isinstance(parsed, list):
            return ()
        return [item for item in parsed if isinstance(item, Mapping)]


def _strip_code_fence(text: str) -> str:
    """```json 울타리를 벗긴다. 모델이 자주 붙이고, 그것 때문에 버릴 이유는 없다."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = [line for line in stripped.splitlines() if not line.strip().startswith("```")]
    return "\n".join(lines)


@dataclass
class ProposalPipeline:
    """메뉴 → 생성 → 접지. 제공자가 없으면 그 기능만 비활성이다."""

    grounder: TemplateGrounder
    provider: TemplateProposalProvider | None = None

    def run(self, request: ProposalRequest) -> GroundingResult:
        if self.provider is None:
            return GroundingResult(None, REASON_NO_PROVIDER)
        try:
            raw = self.provider.propose(request)
        except Exception:
            # 생성 제공자의 실패가 운영 실행으로 번지지 않는다(AI-C-05).
            return GroundingResult(None, REASON_PROVIDER_FAILED,
                                   provider_id=getattr(self.provider, "provider_id", None))
        return self.grounder.ground(request, raw,
                                    provider_id=getattr(self.provider, "provider_id", None))
