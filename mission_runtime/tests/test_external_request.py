"""implements: AI-B-13
tests: 6-stage order, opaque server stage, deployment-not-received vs received,
       re-execution rounds, re-request vs mission-failure, backend-issued id
"""

from __future__ import annotations

import dataclasses

import pytest

from mission_runtime.execution.external_request import (
    DEPLOYMENT_NOT_RECEIVED,
    ExternalRequest,
    ExternalRequestLog,
    FinalVerdict,
    OPAQUE_STAGE,
    RequestReason,
    RequestStage,
    StageRejected,
)


def _request(request_id: str = "req-1") -> ExternalRequest:
    return ExternalRequest(
        request_id=request_id,
        reason=RequestReason.UNSUPPORTED_CAPABILITY,
        reason_detail="해당 작업을 수행할 기능이 온디바이스에 없다",
        origin_node_id="n2",
    )


def _through_deployment(req: ExternalRequest) -> ExternalRequest:
    req = req.advance(RequestStage.SENT, at=100.0)
    req = req.advance(RequestStage.SERVER_WORKING, at=101.0)
    return req.advance(RequestStage.DEPLOYED, at=200.0, deployment_version="v1.2.0")


# -- 식별자 발급 경계 --------------------------------------------------------


def test_request_id_must_be_supplied_because_the_backend_issues_it():
    """AI-C-19: AI 는 요청 사유·필요 정보만 내고 식별자를 발급하지 않는다."""
    with pytest.raises(ValueError, match="issued by the backend"):
        ExternalRequest(
            request_id="",
            reason=RequestReason.UNSUPPORTED_CAPABILITY,
            reason_detail="x",
            origin_node_id="n1",
        )


def test_module_has_no_identifier_generator():
    """uuid·random 으로 식별자를 만들지 않는다는 것을 소스로 확인한다."""
    from pathlib import Path

    import mission_runtime.execution.external_request as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    for banned in ("import uuid", "uuid4", "import random", "secrets"):
        assert banned not in source, f"identifier generation leaked: {banned}"


def test_origin_node_is_required():
    with pytest.raises(ValueError, match="origin_node_id"):
        ExternalRequest(
            request_id="r",
            reason=RequestReason.SIM_REAL_MISMATCH,
            reason_detail="x",
            origin_node_id="",
        )


# -- 두 가지 발생 조건 -------------------------------------------------------


def test_both_documented_reasons_exist_and_nothing_else():
    assert {r.value for r in RequestReason} == {
        "UNSUPPORTED_CAPABILITY", "SIM_REAL_MISMATCH",
    }


# -- 6단계 ------------------------------------------------------------------


def test_six_stages_are_exactly_the_documented_set():
    assert [s.value for s in RequestStage] == [
        "JUDGED", "SENT", "SERVER_WORKING", "DEPLOYED", "RE_EXECUTING", "SETTLED",
    ]


def test_initial_stage_is_the_judgement():
    assert _request().stage is RequestStage.JUDGED


def test_stages_cannot_be_skipped():
    req = _request()
    with pytest.raises(StageRejected, match="skipped"):
        req.advance(RequestStage.DEPLOYED, at=1.0, deployment_version="v1")


def test_stages_cannot_go_backwards():
    req = _through_deployment(_request())
    with pytest.raises(StageRejected, match="does not advance"):
        req.advance(RequestStage.SENT, at=300.0)


def test_each_stage_records_its_transition_time():
    """문서 §4.9: "각 단계의 전이 시각"."""
    req = _through_deployment(_request())
    assert req.stage_entered_at(RequestStage.SENT) == 100.0
    assert req.stage_entered_at(RequestStage.DEPLOYED) == 200.0
    assert req.stage_entered_at(RequestStage.RE_EXECUTING) is None


def test_elapsed_is_measured_from_the_send_time_and_is_none_when_unknown():
    assert _request().elapsed_s(now=500.0) is None
    req = _request().advance(RequestStage.SENT, at=100.0)
    assert req.elapsed_s(now=250.0) == 150.0


# -- 서버 내부 비가시화 ------------------------------------------------------


def test_server_internal_fields_do_not_exist_on_the_record():
    """문서 §4.9: 서버측 개발 진척도·담당·빌드 상태는 표시 대상이 아니다.

    칸을 두지 않는 것이 비가시화의 구조적 보장이다 — 있으면 언젠가 채워진다.
    """
    names = {f.name for f in dataclasses.fields(ExternalRequest)}
    for banned in ("progress", "assignee", "owner", "build_status", "build",
                   "developer", "ticket", "server_state", "internal_status"):
        assert banned not in names, f"server-internal field present: {banned}"


def test_third_stage_reports_only_that_work_is_in_progress():
    req = _request().advance(RequestStage.SENT, at=1.0)
    req = req.advance(RequestStage.SERVER_WORKING, at=2.0)
    assert req.stage is OPAQUE_STAGE
    assert req.server_work_is_opaque is True
    assert req.deployment_received is False


# -- 배포 수신 ---------------------------------------------------------------


def test_deployment_version_is_absent_until_received_and_is_not_faked():
    req = _request().advance(RequestStage.SENT, at=1.0)
    req = req.advance(RequestStage.SERVER_WORKING, at=2.0)
    assert req.deployment_version is DEPLOYMENT_NOT_RECEIVED
    assert req.deployment_version is None       # 0 이나 "" 가 아니다


def test_deployed_stage_requires_a_version():
    req = _request().advance(RequestStage.SENT, at=1.0)
    req = req.advance(RequestStage.SERVER_WORKING, at=2.0)
    with pytest.raises(StageRejected, match="deployment_version"):
        req.advance(RequestStage.DEPLOYED, at=3.0)


# -- 재실행 ------------------------------------------------------------------


def test_re_execution_counts_rounds_and_names_the_nodes():
    req = _through_deployment(_request())
    req = req.advance(RequestStage.RE_EXECUTING, at=300.0, re_executed_node_id="n2-r2")
    assert req.re_execution_count == 1
    assert req.re_executed_nodes == ("n2-r2",)


def test_re_executing_stage_requires_the_node_it_re_runs():
    req = _through_deployment(_request())
    with pytest.raises(StageRejected, match="re-executed node"):
        req.advance(RequestStage.RE_EXECUTING, at=300.0)


# -- 최종 판정 ---------------------------------------------------------------


def test_settle_records_the_verdict():
    req = _through_deployment(_request())
    req = req.advance(RequestStage.RE_EXECUTING, at=300.0, re_executed_node_id="n2-r2")
    settled = req.settle(FinalVerdict.SUCCEEDED, at=400.0)
    assert settled.stage is RequestStage.SETTLED
    assert settled.verdict is FinalVerdict.SUCCEEDED


def test_a_settled_request_cannot_stay_pending():
    req = _through_deployment(_request())
    req = req.advance(RequestStage.RE_EXECUTING, at=300.0, re_executed_node_id="n2-r2")
    with pytest.raises(StageRejected, match="cannot stay PENDING"):
        req.settle(FinalVerdict.PENDING, at=400.0)


def test_verdict_starts_pending():
    assert _request().verdict is FinalVerdict.PENDING


# -- 재실패: 재요청 vs 미션 실패 종결 ---------------------------------------


def _failed(request_id: str = "req-1") -> ExternalRequest:
    req = _through_deployment(_request(request_id))
    req = req.advance(RequestStage.RE_EXECUTING, at=300.0, re_executed_node_id="n2-r2")
    return req.settle(FinalVerdict.FAILED, at=400.0)


def test_re_request_links_to_the_failed_request():
    """문서 §4.9: 재요청으로 이어지는지가 화면에서 구분되어야 한다."""
    failed = _failed()
    again = failed.as_re_request(request_id="req-2", reason_detail="같은 기능 재요청")
    assert again.re_request_of == "req-1"
    assert again.stage is RequestStage.JUDGED
    assert again.verdict is FinalVerdict.PENDING
    assert again.origin_node_id == failed.origin_node_id
    assert again.reason is failed.reason


def test_mission_failure_termination_makes_no_new_request():
    """종결은 FAILED 로 끝나는 것이고 재요청 레코드가 생기지 않는다 — 둘이 구분된다."""
    failed = _failed()
    log = ExternalRequestLog("m-1", (failed,))
    assert log.open_requests() == ()
    assert len(log.requests) == 1
    assert log.chain("req-1") == (failed,)


def test_only_a_failed_request_can_be_re_requested():
    req = _through_deployment(_request())
    with pytest.raises(StageRejected, match="only a FAILED"):
        req.as_re_request(request_id="req-2", reason_detail="x")


def test_re_request_chain_is_listed_from_the_first_request():
    first = _failed("req-1")
    second = first.as_re_request(request_id="req-2", reason_detail="2차")
    log = ExternalRequestLog("m-1", (first, second))
    assert [r.request_id for r in log.chain("req-2")] == ["req-1", "req-2"]
    assert [r.request_id for r in log.chain("req-1")] == ["req-1", "req-2"]


# -- 로그 --------------------------------------------------------------------


def test_empty_log_is_a_normal_state_so_the_region_never_disappears():
    """문서 §4.9: 진행 중 요청이 없어도 구역은 사라지지 않고 "요청 없음"을 명시."""
    log = ExternalRequestLog("m-1")
    assert log.is_empty is True
    assert log.open_requests() == ()


def test_completed_requests_are_kept_for_later_lookup():
    settled = _through_deployment(_request())
    settled = settled.advance(RequestStage.RE_EXECUTING, at=3.0, re_executed_node_id="n2-r2")
    settled = settled.settle(FinalVerdict.SUCCEEDED, at=4.0)
    log = ExternalRequestLog("m-1", (settled,))
    assert log.is_empty is False
    assert log.open_requests() == ()
    assert log.get("req-1").verdict is FinalVerdict.SUCCEEDED


def test_requests_are_traceable_from_the_origin_node_and_the_re_executed_node():
    req = _through_deployment(_request())
    req = req.advance(RequestStage.RE_EXECUTING, at=3.0, re_executed_node_id="n2-r2")
    log = ExternalRequestLog("m-1", (req,))
    assert log.for_node("n2") == (req,)        # 원 실패 노드
    assert log.for_node("n2-r2") == (req,)     # 재실행 노드
    assert log.for_node("n9") == ()


def test_duplicate_request_ids_are_rejected():
    with pytest.raises(ValueError, match="duplicate request ids"):
        ExternalRequestLog("m-1", (_request("r"), _request("r")))


def test_advance_returns_a_new_record_leaving_the_snapshot_untouched():
    req = _request()
    advanced = req.advance(RequestStage.SENT, at=1.0)
    assert req.stage is RequestStage.JUDGED
    assert advanced.stage is RequestStage.SENT


def test_no_transport_technology_appears_in_the_contract():
    """AI-C-04: 어떤 경로로 요청이 나가는지는 provider 의 몫이다.

    주석·docstring 은 제외한다 — 그 단어를 "여기서 쓰지 않는다"는 반례로 인용할 수
    있어야 한다. 식별자·값으로 새어 들어오는 것만 막는다.
    """
    import io
    import tokenize
    from pathlib import Path

    import mission_runtime.execution.external_request as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    banned = ("mqtt", "kafka", "topic", "publish", "socket", "urllib", "httpx")
    leaked: list[tuple[str, int]] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE):
            continue
        low = token.string.lower()
        leaked += [(name, token.start[0]) for name in banned if name in low]
    assert not leaked, f"transport leaked into the contract: {leaked}"
