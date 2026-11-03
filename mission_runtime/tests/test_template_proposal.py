"""implements: AI-B-14, AI-B-13, AI-B-08, AI-C-05, AI-C-16, AI-C-19
covers: 생성된 계획을 **그대로 쓰지 않는다**는 것. 그럴듯한 단계와 이 기계에서 실행
        가능한 단계는 다른 문제이고, 둘을 구분하지 않으면 계획은 통과하고 실행만
        실패한다.
"""

from __future__ import annotations

import json

import pytest

from mission_runtime.contracts.capability import CapabilityRequirement
from mission_runtime.contracts.profile import CompatibilityProfile, ResourceCost
from mission_runtime.planning.template_proposal import (
    REASON_ACCEPTED,
    REASON_DUPLICATE_ACTION,
    REASON_EMPTY_PROPOSAL,
    REASON_MISSING_ACTION,
    REASON_NO_CAPABILITY_NAMED,
    REASON_NO_PROVIDER,
    REASON_NO_STEP_ACCEPTED,
    REASON_NOT_A_MAPPING,
    REASON_PARAMS_NOT_A_MAPPING,
    REASON_PROVIDER_FAILED,
    REASON_TOO_MANY_STEPS,
    REASON_UNKNOWN_CAPABILITY,
    CapabilityMenu,
    KeywordTemplateProposalProvider,
    LlmTemplateProposalProvider,
    ProposalPipeline,
    ProposalRequest,
    TemplateGrounder,
)
from mission_runtime.registry.capability_registry import CapabilityRegistry, ProviderRegistration

MENU = CapabilityMenu(("media.video_input", "perception.detect", "perception.distance"))


def _request(text: str = "문 앞까지 이동해", **kw) -> ProposalRequest:
    return ProposalRequest("APPROACH_TARGET", text, MENU, **kw)


def _ground(raw, **kw):
    return TemplateGrounder(MENU).ground(_request(**kw), raw, provider_id="t")


# -- 어휘 접지 ----------------------------------------------------------

def test_the_menu_only_offers_kinds_that_have_a_provider_right_now():
    """등록만 되어 있고 provider 가 없는 kind 를 어휘에 넣으면 실행에서 떨어진다."""
    registry = CapabilityRegistry()
    registry.register_local(ProviderRegistration(
        capability_kind="perception.detect", provider_id="p1", version="1",
        compatibility=CompatibilityProfile(cost=ResourceCost(1.0, 16.0)),
    ))
    menu = CapabilityMenu.from_registry(registry)

    assert "perception.detect" in menu
    assert "analysis.weight" not in menu


def test_a_step_naming_a_capability_outside_the_menu_is_refused():
    result = _ground([{"action": "estimate_weight", "capability": "analysis.weight"}])

    assert result.template is None
    assert result.reason == REASON_NO_STEP_ACCEPTED
    assert result.rejected[0].reason == REASON_UNKNOWN_CAPABILITY


def test_a_refused_capability_becomes_an_escalation_candidate():
    """버리지 않는다 — "이 기능이 필요한데 없다"가 외부 개발 요청의 재료다(AI-B-13)."""
    result = _ground([
        {"action": "open_stream", "capability": "media.video_input"},
        {"action": "estimate_weight", "capability": "analysis.weight"},
        {"action": "estimate_volume", "capability": "analysis.weight"},
    ])

    assert [s.action for s in result.template.steps] == ["open_stream"]
    # 같은 capability 가 두 단계에서 걸려도 요청 후보는 하나다.
    assert result.escalation_capabilities == ("analysis.weight",)


def test_an_optional_capability_outside_the_menu_is_dropped_not_refused():
    """선택 결손은 DEGRADED 로만 내려가는 자리다 — 계획을 버릴 이유가 아니다(AI-C-05)."""
    result = _ground([{
        "action": "detect", "capability": "perception.detect",
        "optional_capabilities": ["perception.distance", "analysis.pose"],
    }])

    requirement = result.template.steps[0].requirement
    assert requirement.required == ("perception.detect",)
    assert requirement.optional == ("perception.distance",)
    assert result.rejected == ()


# -- 모델이 만들 수 없는 것 ---------------------------------------------

def test_the_generator_cannot_express_a_dependency_at_all():
    """의존을 모델이 만들면 순환·고아 노드가 나온다. 순서열에는 그 자리가 없다.

    가시화 쪽 생성기가 같은 결론에 먼저 도달했고(모델은 노드만, 의존은 규칙),
    우리 쪽은 `StepTemplate` 순서열이라 **구조적으로** 순환이 불가능하다.
    """
    result = _ground([
        {"action": "a", "capability": "perception.detect", "deps": ["b"]},
        {"action": "b", "capability": "media.video_input", "deps": ["a"]},
    ])

    # deps 는 읽지 않는다 — 모르는 칸은 무시하고 순서만 남는다.
    assert [s.action for s in result.template.steps] == ["a", "b"]
    assert not any(hasattr(step, "deps") for step in result.template.steps)


def test_an_unknown_field_does_not_throw_the_plan_away():
    """생성 제공자가 자기 진단 정보를 붙여 보내는 것을 막을 이유가 없다."""
    result = _ground([{
        "action": "detect", "capability": "perception.detect",
        "confidence": 0.8, "rationale": "모델이 적은 설명",
    }])

    assert result.reason == REASON_ACCEPTED
    assert result.rejected == ()


# -- 거부 사유가 단계별로 남는다 ----------------------------------------

@pytest.mark.parametrize("raw, reason", [
    ([{"capability": "perception.detect"}], REASON_MISSING_ACTION),
    ([{"action": "   ", "capability": "perception.detect"}], REASON_MISSING_ACTION),
    ([{"action": "a"}], REASON_NO_CAPABILITY_NAMED),
    ([{"action": "a", "capability": "perception.detect", "params": [1, 2]}],
     REASON_PARAMS_NOT_A_MAPPING),
    (["not a mapping"], REASON_NOT_A_MAPPING),
])
def test_each_malformed_step_is_refused_with_its_own_reason(raw, reason):
    """"생성 실패" 한 줄로 뭉치면 무엇을 고쳐야 하는지 알 수 없다."""
    result = _ground(raw)

    assert result.rejected[0].reason == reason


def test_a_repeated_action_is_refused_because_the_plan_would_be_ambiguous():
    result = _ground([
        {"action": "detect", "capability": "perception.detect"},
        {"action": "detect", "capability": "media.video_input"},
    ])

    assert [s.action for s in result.template.steps] == ["detect"]
    assert result.rejected[0].reason == REASON_DUPLICATE_ACTION


def test_steps_beyond_the_limit_are_refused_rather_than_truncated_silently():
    """상한이 없으면 사람이 승인 화면에서 읽을 수 없는 계획이 나온다."""
    raw = [{"action": f"a{i}", "capability": "perception.detect"} for i in range(5)]
    # 같은 action 중복 금지를 피하려 이름을 달리 두고 capability 는 같아도 된다.
    result = _ground(raw, max_steps=2)

    assert len(result.template.steps) == 2
    assert [r.reason for r in result.rejected] == [REASON_TOO_MANY_STEPS] * 3


def test_an_empty_proposal_is_a_state_not_an_error():
    assert _ground([]).reason == REASON_EMPTY_PROPOSAL


# -- 생성이 꺼진 배치가 기본형이다 --------------------------------------

def test_without_a_provider_the_pipeline_reports_it_and_does_not_raise():
    """심사·폐쇄망 배치에는 생성 서비스가 없다. 꺼지는 것은 생성 하나뿐이다."""
    result = ProposalPipeline(TemplateGrounder(MENU)).run(_request())

    assert result.template is None
    assert result.reason == REASON_NO_PROVIDER


def test_a_failing_provider_does_not_propagate_into_execution():
    class Exploding:
        provider_id = "boom"

        def propose(self, request):
            raise RuntimeError("service down")

    result = ProposalPipeline(TemplateGrounder(MENU), Exploding()).run(_request())

    assert result.reason == REASON_PROVIDER_FAILED
    assert result.provider_id == "boom"


def test_the_keyword_provider_works_with_no_model_at_all():
    """모델이 아니다 — 선언된 대응표다. 그래도 계획이 나와야 한다."""
    provider = KeywordTemplateProposalProvider(vocabulary={
        "이동": ("move_forward", "perception.distance"),
        "탐지": ("detect_target", "perception.detect"),
    })
    result = ProposalPipeline(TemplateGrounder(MENU), provider).run(
        _request("대상을 탐지하고 그 앞까지 이동해")
    )

    assert sorted(s.action for s in result.template.steps) == ["detect_target", "move_forward"]


# -- 생성 모델 어댑터 ---------------------------------------------------

def test_the_llm_adapter_sends_the_menu_in_the_prompt():
    """어휘 접지는 프롬프트에서 시작한다 — 목록을 안 보내면 목록 밖을 받는다."""
    seen = {}

    def complete(prompt: str) -> str:
        seen["prompt"] = prompt
        return json.dumps([{"action": "detect", "capability": "perception.detect"}])

    provider = LlmTemplateProposalProvider(complete)
    ProposalPipeline(TemplateGrounder(MENU), provider).run(_request())

    for kind in MENU.kinds:
        assert kind in seen["prompt"]
    assert "문 앞까지 이동해" in seen["prompt"]


@pytest.mark.parametrize("output", [
    "이건 JSON 이 아니다",
    "",
    "{}",
    "[1, 2, 3]",
    '{"steps": "not a list"}',
])
def test_malformed_model_output_degrades_instead_of_raising(output):
    """생성 실패가 예외로 올라오면 운영 실행이 멈춘다(AI-C-05)."""
    provider = LlmTemplateProposalProvider(lambda prompt: output)
    result = ProposalPipeline(TemplateGrounder(MENU), provider).run(_request())

    assert result.template is None
    assert result.reason in {REASON_EMPTY_PROPOSAL, REASON_NO_STEP_ACCEPTED}


def test_a_code_fenced_json_array_is_still_read():
    """모델이 ```json 울타리를 자주 붙인다. 그것 때문에 계획을 버릴 이유는 없다."""
    fenced = '```json\n[{"action": "detect", "capability": "perception.detect"}]\n```'
    provider = LlmTemplateProposalProvider(lambda prompt: fenced)

    result = ProposalPipeline(TemplateGrounder(MENU), provider).run(_request())

    assert [s.action for s in result.template.steps] == ["detect"]


def test_the_raw_output_is_kept_for_review_and_replay():
    """무엇을 받았는지 남지 않으면 승인 화면도 재현도 할 수 없다(AI-L-08)."""
    provider = LlmTemplateProposalProvider(
        lambda prompt: json.dumps([{"action": "detect", "capability": "perception.detect"}])
    )
    ProposalPipeline(TemplateGrounder(MENU), provider).run(_request())

    assert provider.last_raw_output is not None and "detect" in provider.last_raw_output


def test_no_vendor_sdk_crosses_this_boundary():
    """제공자는 문자열을 넣고 문자열을 받는 콜러블 하나다 — SDK 가 여기 들어오지 않는다."""
    import inspect

    from mission_runtime.planning import template_proposal

    source = inspect.getsource(template_proposal)
    for vendor in ("openai", "anthropic", "google.generativeai", "ollama", "transformers"):
        assert vendor not in source


# -- 접지된 템플릿은 기존 분해 계약으로 이어진다 -------------------------

def test_the_grounded_template_is_the_same_type_the_decomposer_already_takes():
    """새 계획 경로를 만들지 않는다 — 기존 검증·구체화를 그대로 통과해야 한다."""
    from mission_runtime.planning.decomposition import TaskTemplate, TaskTemplateLibrary

    result = _ground([{"action": "detect", "capability": "perception.detect"}])
    library = TaskTemplateLibrary()
    library.register(result.template)

    assert isinstance(result.template, TaskTemplate)
    assert library.get("APPROACH_TARGET") is result.template
    assert isinstance(result.template.steps[0].requirement, CapabilityRequirement)


def test_the_template_version_records_which_generator_made_it():
    """사람이 쓴 템플릿과 생성된 것을 구분할 수 있어야 한다(AI-L-08)."""
    result = _ground([{"action": "detect", "capability": "perception.detect"}])

    assert result.template.version.startswith("proposed:t:")
