"""External capability request lifecycle: judged -> sent -> (opaque server work)
-> deployment received -> applied/re-executed -> verdict.

implements: AI-B-13 (수행 불가 기능의 외부 개발 요청)
관련: AI-C-05 (필수 조건 미충족 시 해당 기능만 비활성), AI-S-05 (부족 근거를 남긴다),
      AI-C-19 (발급·제어는 AI 소관이 아니다), AI-B-05 (버전 배포·롤백)

요구사항 출처는 `docs/20260928-종합상황정보_Dashboard_기능정의서_2.docx` §4.9 이며
2026-10-27 에 AI-B-13 으로 요구사항 시트에 등재했다(CLAUDE.md §5).

두 가지 경계를 구조로 지킨다
----------------------------
1. **서버 내부는 담지 않는다.** 문서 §4.9: "서버측 개발 진척도·담당·빌드 상태 등은
   표시 대상이 아니다." 그래서 이 레코드에는 그런 칸이 **없고**, 3단계는 "처리 중"
   여부만 표현한다. 칸을 두지 않는 것이 비가시화의 구조적 보장이다.
2. **요청 식별자를 우리가 만들지 않는다.** `request_id` 는 생성자 인자이며 비울 수
   없다. AI 는 필요한 정보·관측 조건·요청 사유만 산출하고 발급은 백엔드를 거친다
   (AI-C-19). 이 모듈에 uuid 생성이 없는 것이 그 경계의 증거다.

전송 기술도 담지 않는다 — 요청이 어떤 경로(Kafka·브리지·MQTT·HTTP)로 나가는지는
provider 의 몫이고 여기 있는 것은 의미 계약뿐이다(AI-C-04).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class RequestReason(str, Enum):
    """요청이 발생하는 두 가지 조건 (문서 §4.9).

    UNSUPPORTED_CAPABILITY 미지원 기능 — 수행할 기능이 온디바이스에 없다.
                           판정 시점: 세부 작업 도출 단계 또는 실행 시도 시.
    SIM_REAL_MISMATCH      시뮬–실물 불일치 — 시뮬레이션에서는 수행 가능으로
                           판정됐으나 실물에서 실패. 판정 시점: 실행 후 판정 단계.
    """

    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    SIM_REAL_MISMATCH = "SIM_REAL_MISMATCH"


class RequestStage(str, Enum):
    """문서 §4.9 "요청 처리 단계" 6단계.

    JUDGED          1 기능 미지원 판정 (판정 시각, 발생 노드)
    SENT            2 요청 전송 (요청 식별자, 전송 시각, 요청 사유)
    SERVER_WORKING  3 서버 처리 — **진행 중 여부만**. 내부 과정은 담지 않는다.
    DEPLOYED        4 SW 배포 수신 (배포 버전, 수신 시각)
    RE_EXECUTING    5 배포 적용·재실행 (적용 시각, 재실행 회차, 대상 노드)
    SETTLED         6 성공 여부 판정 (재실행 결과에 대한 최종 판정)
    """

    JUDGED = "JUDGED"
    SENT = "SENT"
    SERVER_WORKING = "SERVER_WORKING"
    DEPLOYED = "DEPLOYED"
    RE_EXECUTING = "RE_EXECUTING"
    SETTLED = "SETTLED"


#: 단계는 되돌아가지 않는다. 재실행이 다시 실패하면 단계를 뒤로 돌리는 대신
#: **새 요청**을 만들어 이어 붙인다(`re_request_of`) — 문서 §4.9 가 "재요청으로
#: 이어지는지, 미션 실패로 종결되는지가 화면에서 구분되어야 한다"고 요구한다.
_ORDER: tuple[RequestStage, ...] = (
    RequestStage.JUDGED,
    RequestStage.SENT,
    RequestStage.SERVER_WORKING,
    RequestStage.DEPLOYED,
    RequestStage.RE_EXECUTING,
    RequestStage.SETTLED,
)

#: 3단계에서 내부가 보이지 않는 구간임을 화면이 시각적으로 구분하도록 내보내는 표식
#: (문서 §4.9 "화면상 해당 단계는 내부가 보이지 않는 구간임이 시각적으로 구분").
OPAQUE_STAGE = RequestStage.SERVER_WORKING

#: 배포 버전 미수신. 0 이나 빈 문자열을 넣지 않는다.
DEPLOYMENT_NOT_RECEIVED = None


class FinalVerdict(str, Enum):
    """최종 판정 (문서 §4.9 구성 요소 "최종 판정").

    PENDING   판정 대기
    SUCCEEDED 재실행 성공
    FAILED    재실행 실패 — 이 뒤는 재요청이거나 미션 실패 종결이고, 둘을 섞지 않는다.
    """

    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class StageRejected(Exception):
    """단계 역행이나 선행 단계 누락."""


@dataclass(frozen=True)
class StageTransition:
    stage: RequestStage
    at: float | None


@dataclass(frozen=True)
class ExternalRequest:
    """요청 1건. 서버 내부 상태를 담는 칸이 없다는 점이 설계의 핵심이다."""

    #: 백엔드가 발급한 식별자. 이 모듈은 만들지 않는다(AI-C-19).
    request_id: str
    reason: RequestReason
    #: 사유 상세. 사람이 읽는 문장이고 분기 근거로 쓰지 않는다.
    reason_detail: str
    #: 요청을 유발한 작업 그래프 노드.
    origin_node_id: str
    requested_at: float | None = None
    transitions: tuple[StageTransition, ...] = ()
    #: 수신된 SW 패키지 버전. 미수신이면 None 이고 화면은 "미수신"으로 적는다.
    deployment_version: str | None = DEPLOYMENT_NOT_RECEIVED
    #: 배포 적용 후 재실행한 횟수.
    re_execution_count: int = 0
    #: 재실행 대상 노드들(회차마다 새 노드이므로 여러 개가 쌓인다).
    re_executed_nodes: tuple[str, ...] = ()
    verdict: FinalVerdict = FinalVerdict.PENDING
    #: 이 요청이 어떤 요청의 재요청인지. 최초 요청은 None.
    re_request_of: str | None = None

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError(
                "request_id is issued by the backend and must be supplied (AI-C-19)"
            )
        if not self.origin_node_id:
            raise ValueError("origin_node_id must name the node that caused the request")
        if self.re_execution_count < 0:
            raise ValueError("re_execution_count must not be negative")
        seen = [t.stage for t in self.transitions]
        if seen and seen != sorted(seen, key=_ORDER.index):
            raise StageRejected(f"stages out of order: {[s.value for s in seen]}")

    # -- 조회 ------------------------------------------------------------

    @property
    def stage(self) -> RequestStage:
        return self.transitions[-1].stage if self.transitions else RequestStage.JUDGED

    @property
    def server_work_is_opaque(self) -> bool:
        """3단계에 있는 동안은 "처리 중"만 알 수 있다."""
        return self.stage is OPAQUE_STAGE

    @property
    def deployment_received(self) -> bool:
        return self.deployment_version is not None

    def stage_entered_at(self, stage: RequestStage) -> float | None:
        for t in self.transitions:
            if t.stage is stage:
                return t.at
        return None

    def elapsed_s(self, now: float) -> float | None:
        """요청 발신 이후 경과. 발신 시각을 모르면 None — 0 을 내지 않는다."""
        if self.requested_at is None:
            return None
        return max(0.0, now - self.requested_at)

    # -- 전이 (항상 새 레코드) -------------------------------------------

    def advance(
        self,
        stage: RequestStage,
        *,
        at: float | None = None,
        deployment_version: str | None = None,
        re_executed_node_id: str | None = None,
    ) -> ExternalRequest:
        """다음 단계로 간다. 건너뛰기와 역행을 모두 거부한다.

        전이 기록이 비어 있어도 요청은 이미 1단계(판정)에 **있다** — 레코드가
        존재한다는 것 자체가 "기능 미지원 판정이 났다"는 뜻이다. 그 판정 시각을
        남기고 싶으면 `advance(JUDGED, at=...)` 를 한 번 호출한다.
        """
        current = _ORDER.index(self.stage)
        target = _ORDER.index(stage)
        if not self.transitions and stage is RequestStage.JUDGED:
            return replace(self, transitions=(StageTransition(stage, at),))
        if target <= current:
            raise StageRejected(
                f"{self.request_id}: {self.stage.value} -> {stage.value} does not advance"
            )
        if target != current + 1:
            skipped = [s.value for s in _ORDER[current + 1:target]]
            raise StageRejected(f"{self.request_id}: stages skipped: {skipped}")
        if stage is RequestStage.DEPLOYED and deployment_version is None:
            raise StageRejected(f"{self.request_id}: DEPLOYED needs a deployment_version")
        if stage is RequestStage.RE_EXECUTING and re_executed_node_id is None:
            raise StageRejected(
                f"{self.request_id}: RE_EXECUTING needs the re-executed node id"
            )
        return replace(
            self,
            transitions=self.transitions + (StageTransition(stage, at),),
            requested_at=at if stage is RequestStage.SENT else self.requested_at,
            deployment_version=(deployment_version if deployment_version is not None
                                else self.deployment_version),
            re_execution_count=(self.re_execution_count + 1
                                if stage is RequestStage.RE_EXECUTING
                                else self.re_execution_count),
            re_executed_nodes=(self.re_executed_nodes + (re_executed_node_id,)
                               if re_executed_node_id is not None
                               else self.re_executed_nodes),
        )

    def settle(self, verdict: FinalVerdict, *, at: float | None = None) -> ExternalRequest:
        """6단계 판정. PENDING 으로 종결할 수는 없다."""
        if verdict is FinalVerdict.PENDING:
            raise StageRejected("a settled request cannot stay PENDING")
        advanced = self.advance(RequestStage.SETTLED, at=at)
        return replace(advanced, verdict=verdict)

    def as_re_request(self, *, request_id: str, reason_detail: str) -> ExternalRequest:
        """재실행이 다시 실패한 뒤 **새 요청**으로 이어 붙인다.

        미션 실패 종결과 구분되는 쪽이다 — 종결은 새 요청을 만들지 않고 이 요청의
        `verdict` 를 FAILED 로 둔 채 끝낸다(문서 §4.9 마지막 동작 규칙).
        """
        if self.verdict is not FinalVerdict.FAILED:
            raise StageRejected(
                f"{self.request_id}: only a FAILED request is re-requested"
            )
        return ExternalRequest(
            request_id=request_id,
            reason=self.reason,
            reason_detail=reason_detail,
            origin_node_id=self.origin_node_id,
            re_request_of=self.request_id,
        )


@dataclass(frozen=True)
class ExternalRequestLog:
    """한 미션의 요청들. 진행 중인 요청이 없어도 이 구역은 사라지지 않는다.

    문서 §4.9: "진행 중인 요청이 없는 미션에서도 본 구역은 화면에서 사라지지 않으며,
    요청 없음 상태를 명시한다." 그래서 빈 로그가 정상 상태이고 `is_empty` 로 드러낸다.
    완료된 요청도 지우지 않는다(같은 절: "완료된 요청의 이력은 미션 종료 후에도 조회
    가능해야 한다").
    """

    mission_id: str
    requests: tuple[ExternalRequest, ...] = ()

    def __post_init__(self) -> None:
        ids = [r.request_id for r in self.requests]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate request ids: {sorted({i for i in ids if ids.count(i) > 1})}")

    @property
    def is_empty(self) -> bool:
        return not self.requests

    def get(self, request_id: str) -> ExternalRequest:
        for r in self.requests:
            if r.request_id == request_id:
                return r
        raise KeyError(request_id)

    def open_requests(self) -> tuple[ExternalRequest, ...]:
        return tuple(r for r in self.requests if r.verdict is FinalVerdict.PENDING)

    def for_node(self, node_id: str) -> tuple[ExternalRequest, ...]:
        """그 노드가 유발했거나 그 노드로 재실행된 요청. 문서 §4.9 의 "요청과 관련된
        노드(원 실패 노드, 요청 노드, 재실행 노드)는 서로 연결된 관계로 추적 가능"."""
        return tuple(
            r for r in self.requests
            if r.origin_node_id == node_id or node_id in r.re_executed_nodes
        )

    def chain(self, request_id: str) -> tuple[ExternalRequest, ...]:
        """재요청 사슬을 최초 요청부터."""
        root = self.get(request_id)
        while root.re_request_of is not None:
            root = self.get(root.re_request_of)
        chain = [root]
        changed = True
        while changed:
            changed = False
            have = {r.request_id for r in chain}
            for r in self.requests:
                if r.re_request_of in have and r.request_id not in have:
                    chain.append(r)
                    changed = True
        return tuple(chain)

    def replace_request(self, request: ExternalRequest) -> ExternalRequestLog:
        if not any(r.request_id == request.request_id for r in self.requests):
            raise KeyError(request.request_id)
        return replace(self, requests=tuple(
            request if r.request_id == request.request_id else r for r in self.requests
        ))

    def add(self, request: ExternalRequest) -> ExternalRequestLog:
        return replace(self, requests=self.requests + (request,))
