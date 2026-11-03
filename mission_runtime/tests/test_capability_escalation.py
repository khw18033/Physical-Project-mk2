"""implements: AI-B-13
tests: judgement from the live registry, optional loss is not a request reason,
       three-valued sim/real comparison, request id issued outside, stages 1-2
       recorded with their own times
"""

from __future__ import annotations

import pytest

from mission_runtime.contracts.profile import CompatibilityProfile, ResourceBudget, ResourceCost
from mission_runtime.execution.capability_escalation import (
    REASON_REQUIRED_KIND_NO_CANDIDATE,
    REASON_REQUIRED_KIND_UNREGISTERED,
    REASON_SIM_REAL_DIVERGED,
    CapabilityNeed,
    CollectingSink,
    Comparability,
    EscalationRejected,
    EscalationRequester,
    LocalSequentialIssuer,
    MismatchFinding,
    OnDeviceFeasibilityJudge,
    OutcomeSample,
    RelativeToleranceComparator,
    SimRealMismatchJudge,
    UnsupportedFinding,
)
from mission_runtime.execution.external_request import RequestReason, RequestStage
from mission_runtime.contracts.capability import CapabilityState
from mission_runtime.registry.capability_registry import (
    CapabilityRegistry,
    ProviderRegistration,
)


def _registry(*kinds: str, cost: float = 1.0) -> CapabilityRegistry:
    reg = CapabilityRegistry()
    for kind in kinds:
        reg.register_local(ProviderRegistration(
            capability_kind=kind,
            provider_id=f"prov-{kind}",
            version="1.0",
            compatibility=CompatibilityProfile(cost=ResourceCost(compute_units=cost)),
        ))
    return reg


# -- 1단계: 수행 가능성 판정 -------------------------------------------------


def test_unregistered_required_kind_is_a_request_reason():
    judge = OnDeviceFeasibilityJudge(_registry("perception.detect"))
    finding = judge.judge(CapabilityNeed("T-1", ("manipulation.grasp",)), at=10.0)
    assert finding.unsupported is True
    assert finding.missing_required == ("manipulation.grasp",)
    assert finding.reason_token == REASON_REQUIRED_KIND_UNREGISTERED
    assert finding.judged_at == 10.0


def test_registered_required_kind_is_not_a_request_reason():
    judge = OnDeviceFeasibilityJudge(_registry("perception.detect"))
    finding = judge.judge(CapabilityNeed("T-1", ("perception.detect",)))
    assert finding.unsupported is False
    assert finding.missing_required == ()
    assert finding.reason_token is None


def test_missing_optional_kind_is_recorded_but_is_not_a_request_reason():
    """AI-C-05: 선택 기능 결손은 정상 축소다 — 외부 개발 요청 사유가 아니다."""
    judge = OnDeviceFeasibilityJudge(_registry("perception.detect"))
    finding = judge.judge(
        CapabilityNeed("T-1", ("perception.detect",), ("perception.depth",))
    )
    assert finding.unsupported is False
    assert finding.degraded_optional == ("perception.depth",)


def test_registering_a_provider_flips_the_judgement_without_code_change():
    """AI-C-10: 모델·장치 이름이 아니라 등록된 기능으로 판정한다."""
    registry = _registry()
    judge = OnDeviceFeasibilityJudge(registry)
    need = CapabilityNeed("T-1", ("manipulation.grasp",))
    assert judge.judge(need).unsupported is True
    registry.register_local(ProviderRegistration(
        capability_kind="manipulation.grasp", provider_id="p", version="1",
    ))
    assert judge.judge(need).unsupported is False


def test_budget_exhaustion_is_distinguished_from_being_unregistered():
    judge = OnDeviceFeasibilityJudge(_registry("perception.detect", cost=100.0))
    finding = judge.judge(
        CapabilityNeed("T-1", ("perception.detect",)),
        node_tags=set(),
        budget=ResourceBudget(compute_units=1.0, memory_mb=512.0),
    )
    assert finding.unsupported is True
    assert finding.reason_token == REASON_REQUIRED_KIND_NO_CANDIDATE


def test_capability_state_reuses_the_existing_degrade_rule():
    """축소 규칙을 여기서 다시 구현하지 않는다 — 기존 계약에 위임한다."""
    judge = OnDeviceFeasibilityJudge(_registry("perception.detect"))
    assert judge.capability_state(
        CapabilityNeed("T", ("perception.detect",), ("perception.depth",))
    ) is CapabilityState.DEGRADED
    assert judge.capability_state(
        CapabilityNeed("T", ("perception.detect",))
    ) is CapabilityState.ACTIVE
    assert judge.capability_state(
        CapabilityNeed("T", ("manipulation.grasp",))
    ) is CapabilityState.DISABLED


# -- 시뮬–실물 비교 ----------------------------------------------------------


def test_agreement_within_tolerance_is_a_match():
    judge = SimRealMismatchJudge(RelativeToleranceComparator(tolerance=0.1))
    finding = judge.judge(
        "T-1",
        OutcomeSample("grasp_success_rate", "ratio", 0.90),
        OutcomeSample("grasp_success_rate", "ratio", 0.86),
        at=5.0,
    )
    assert finding.comparability is Comparability.MATCH
    assert finding.unsupported is False
    assert finding.divergence == pytest.approx(0.0444, abs=1e-3)


def test_divergence_beyond_tolerance_is_a_mismatch():
    judge = SimRealMismatchJudge(RelativeToleranceComparator(tolerance=0.1))
    finding = judge.judge(
        "T-1",
        OutcomeSample("grasp_success_rate", "ratio", 0.90),
        OutcomeSample("grasp_success_rate", "ratio", 0.20),
    )
    assert finding.comparability is Comparability.MISMATCH
    assert finding.unsupported is True
    assert finding.reason_token == REASON_SIM_REAL_DIVERGED


@pytest.mark.parametrize("expected,actual,why", [
    (None, OutcomeSample("m", "ratio", 1.0), "absent"),
    (OutcomeSample("m", "ratio", 1.0), None, "absent"),
    (OutcomeSample("m", "ratio", None), OutcomeSample("m", "ratio", 1.0), "not measured"),
    (OutcomeSample("a", "ratio", 1.0), OutcomeSample("b", "ratio", 1.0), "different metrics"),
    (OutcomeSample("m", "ratio", 1.0), OutcomeSample("m", "ms", 1.0), "different units"),
])
def test_incomparable_pairs_are_not_mismatches(expected, actual, why):
    """비교 불가를 불일치로 세면 요청이 쌓이고, 일치로 세면 실물 실패가 묻힌다."""
    finding = SimRealMismatchJudge().judge("T-1", expected, actual)
    assert finding.comparability is Comparability.NOT_COMPARABLE
    assert finding.unsupported is False
    assert why in finding.not_comparable_because


def test_comparability_has_exactly_three_values():
    assert {c.value for c in Comparability} == {"MATCH", "MISMATCH", "NOT_COMPARABLE"}


def test_comparator_is_replaceable():
    class AlwaysMismatch:
        def compare(self, expected, actual):
            return (False, 99.0)

    finding = SimRealMismatchJudge(AlwaysMismatch()).judge(
        "T-1", OutcomeSample("m", "ratio", 1.0), OutcomeSample("m", "ratio", 1.0)
    )
    assert finding.comparability is Comparability.MISMATCH
    assert finding.divergence == 99.0


def test_negative_tolerance_is_rejected():
    with pytest.raises(ValueError, match="tolerance"):
        RelativeToleranceComparator(tolerance=-0.1)


# -- 2단계: 요청 조립과 발신 -------------------------------------------------


def test_request_identifier_comes_from_the_injected_issuer():
    """AI-C-19: 발급 주체는 외부다 — 이 모듈이 만들지 않는다."""
    calls: list[tuple[str, RequestReason]] = []

    class RecordingIssuer:
        def issue(self, *, task_node_id, reason):
            calls.append((task_node_id, reason))
            return "backend-req-77"

    requester = EscalationRequester(issuer=RecordingIssuer())
    request = requester.from_unsupported(
        UnsupportedFinding("T-1", ("manipulation.grasp",),
                           reason_token=REASON_REQUIRED_KIND_UNREGISTERED, judged_at=1.0),
        at=2.0,
    )
    assert request.request_id == "backend-req-77"
    assert calls == [("T-1", RequestReason.UNSUPPORTED_CAPABILITY)]


def test_both_first_stages_are_recorded_with_their_own_times():
    requester = EscalationRequester(issuer=LocalSequentialIssuer())
    request = requester.from_unsupported(
        UnsupportedFinding("T-1", ("x",), reason_token="r", judged_at=1.0), at=2.0
    )
    assert request.stage is RequestStage.SENT
    assert request.stage_entered_at(RequestStage.JUDGED) == 1.0
    assert request.stage_entered_at(RequestStage.SENT) == 2.0
    assert request.requested_at == 2.0


def test_request_carries_the_missing_kinds_as_its_reason_detail():
    requester = EscalationRequester(issuer=LocalSequentialIssuer())
    request = requester.from_unsupported(
        UnsupportedFinding("T-1", ("manipulation.grasp", "sensor.force"),
                           reason_token=REASON_REQUIRED_KIND_UNREGISTERED)
    )
    assert "manipulation.grasp" in request.reason_detail
    assert "sensor.force" in request.reason_detail
    assert request.origin_node_id == "T-1"


def test_mismatch_request_names_both_sides_and_the_divergence():
    requester = EscalationRequester(issuer=LocalSequentialIssuer())
    finding = SimRealMismatchJudge(RelativeToleranceComparator(tolerance=0.1)).judge(
        "T-2", OutcomeSample("grasp_success_rate", "ratio", 0.9),
        OutcomeSample("grasp_success_rate", "ratio", 0.2), at=3.0,
    )
    request = requester.from_mismatch(finding, at=4.0)
    assert request.reason is RequestReason.SIM_REAL_MISMATCH
    assert "expected=0.9" in request.reason_detail
    assert "actual=0.2" in request.reason_detail
    assert "divergence=" in request.reason_detail


def test_a_feasible_task_cannot_be_escalated():
    requester = EscalationRequester(issuer=LocalSequentialIssuer())
    with pytest.raises(EscalationRejected, match="nothing is missing"):
        requester.from_unsupported(UnsupportedFinding("T-1"))


def test_an_incomparable_outcome_cannot_be_escalated():
    requester = EscalationRequester(issuer=LocalSequentialIssuer())
    finding = SimRealMismatchJudge().judge("T-1", None, None)
    with pytest.raises(EscalationRejected, match="not comparable"):
        requester.from_mismatch(finding)


def test_an_agreeing_outcome_cannot_be_escalated():
    requester = EscalationRequester(issuer=LocalSequentialIssuer())
    finding = SimRealMismatchJudge().judge(
        "T-1", OutcomeSample("m", "ratio", 1.0), OutcomeSample("m", "ratio", 1.0)
    )
    with pytest.raises(EscalationRejected, match="agree"):
        requester.from_mismatch(finding)


def test_an_empty_request_id_is_rejected():
    class EmptyIssuer:
        def issue(self, *, task_node_id, reason):
            return ""

    requester = EscalationRequester(issuer=EmptyIssuer())
    with pytest.raises(EscalationRejected, match="empty request id"):
        requester.from_unsupported(UnsupportedFinding("T-1", ("x",)))


def test_sink_receives_the_request_and_transport_stays_outside():
    sink = CollectingSink()
    requester = EscalationRequester(issuer=LocalSequentialIssuer(), sink=sink)
    request = requester.from_unsupported(UnsupportedFinding("T-1", ("x",)))
    assert sink.sent == [request]


def test_local_issuer_marks_itself_as_a_stand_in():
    issuer = LocalSequentialIssuer(prefix="edge-a")
    first = issuer.issue(task_node_id="T", reason=RequestReason.UNSUPPORTED_CAPABILITY)
    second = issuer.issue(task_node_id="T", reason=RequestReason.UNSUPPORTED_CAPABILITY)
    assert first == "edge-a-req-0001" and second == "edge-a-req-0002"


def test_no_transport_technology_in_the_module():
    import io
    import tokenize
    from pathlib import Path

    import mission_runtime.execution.capability_escalation as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    banned = ("mqtt", "kafka", "topic", "urllib", "httpx", "uuid")
    leaked = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE):
            continue
        low = token.string.lower()
        leaked += [(n, token.start[0]) for n in banned if n in low]
    assert not leaked, f"leaked into code: {leaked}"
