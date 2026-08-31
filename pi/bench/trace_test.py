"""
피지컬팀 mk2 — 명령 경로 trace 로컬 검증 (BACKEND_AGENDA 10-3)
================================================================
실물·Collector 없이 검증한다. InMemorySpanExporter 로 span 을 붙잡아
**실제 CommandEngine** 을 통과한 명령이 남기는 사슬을 바이트 그대로 검사한다.

검증 항목:
  1. 정상 명령: cmd.receive → cmd.execute → cmd.result×단계 — 부모 관계·속성
  2. 백엔드 traceparent 를 실으면 그 trace 의 자식으로 붙는다 (trace_id 일치)
  3. rejected(미지원 액션): receive 하나로 끝, status=ERROR, 사유 속성
  4. 실패 명령: execute 가 status=ERROR, stage.failed 이벤트
  5. no-op: 엔드포인트 없이도 엔진이 똑같이 동작한다 (관측은 업무의 전제조건이 아니다)

사용:
    python -m bench.trace_test        (pi/ 디렉터리에서, 어느 OS 든)
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import otel_trace, schema
from common.commands import BASE_ACTIONS, CommandEngine, CommandError


# ---------------------------------------------------------------- 시험용 노드
def act_ok(node, params):
    yield "executing", None
    yield "state_changed", {"pos": 1}
    yield "completed", None


def act_boom(node, params):
    yield "executing", None
    raise CommandError("actuator_jammed")


class FakeNode:
    ACTIONS = dict(BASE_ACTIONS, ok=act_ok, boom=act_boom)
    PHYSICAL_ACTIONS = {"ok", "boom"}

    def __init__(self):
        self.identity = schema.Identity("t-01", "test-host", "zoneA",
                                        "00:00:00:00:00:00", "127.0.0.1",
                                        entity_type="sensor")
        self.started = time.time()
        self.published = []

    def validate(self, action, params):
        if params.get("bad"):
            raise CommandError("bad_param")

    def diagnostics(self):
        return {}

    def publish(self, topic, payload, qos=0, kind=None):
        self.published.append((topic, payload))


class FakeClient:
    def publish(self, topic, payload, qos=0):
        pass


def run_command(engine, node, cmd, wait_stage=None):
    engine.on_message(FakeClient(), json.dumps(cmd).encode())
    if wait_stage:
        deadline = time.time() + 5
        while time.time() < deadline:
            if any(p.get("stage") == wait_stage for _, p in node.published):
                return
            time.sleep(0.05)
        raise AssertionError(f"{wait_stage} 단계가 오지 않았다")


def spans_of(exporter):
    time.sleep(0.2)                      # 워커 스레드의 end 가 export 되도록
    return {s.name: s for s in exporter.get_finished_spans()}, exporter.get_finished_spans()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )
    print("명령 경로 trace 로컬 검증 (Collector 불필요)")

    # ---- 1) 정상 명령: 사슬 전체 ----
    exp = InMemorySpanExporter()
    node = FakeNode()
    tracer = otel_trace.create(node.identity, exporter=exp)
    assert tracer.enabled
    eng = CommandEngine(node, node.publish, "zoneA/sensor/t1", log=lambda *a: None,
                        tracer=tracer)
    run_command(eng, node, {"command_id": "c-1", "action": "ok"}, wait_stage="completed")
    by_name, all_spans = spans_of(exp)
    recv, exe = by_name["cmd.receive"], by_name["cmd.execute"]
    results = [s for s in all_spans if s.name == "cmd.result"]
    assert exe.parent.span_id == recv.context.span_id, "execute 는 receive 의 자식이어야"
    assert all(r.parent.span_id == exe.context.span_id for r in results)
    assert len(results) == 3, f"result span {len(results)} != 단계 3"
    assert recv.attributes["hw.command.action"] == "ok"
    assert recv.attributes["hw.command.id"] == "c-1"
    assert recv.attributes["hw.command.result"] == "accepted"
    events = [e.name for e in exe.events]
    assert events == ["stage.executing", "stage.state_changed", "stage.completed"], events
    assert {r.attributes["hw.command.stage"] for r in results} == \
           {"executing", "state_changed", "completed"}
    print(f"  1) 정상 사슬: receive→execute→result×3, 부모 관계·속성·이벤트 ✓")

    # ---- 2) 백엔드 traceparent 에 잇기 ----
    exp.clear()
    backend_trace = "0af7651916cd43dd8448eb211c80319c"
    cmd = {"command_id": "c-2", "action": "ok",
           "traceparent": f"00-{backend_trace}-b7ad6b7169203331-01"}
    run_command(eng, node, cmd, wait_stage="completed")
    by_name, all_spans = spans_of(exp)
    recv = by_name["cmd.receive"]
    assert format(recv.context.trace_id, "032x") == backend_trace, \
        "백엔드 trace_id 를 이어받아야 한다"
    assert format(recv.parent.span_id, "016x") == "b7ad6b7169203331"
    assert all(format(s.context.trace_id, "032x") == backend_trace for s in all_spans)
    print(f"  2) traceparent 상속: 전 span 이 백엔드 trace {backend_trace[:8]}… 의 자식 ✓")

    # ---- 3) rejected: receive 하나로 끝 ----
    exp.clear()
    eng.on_message(FakeClient(), json.dumps(
        {"command_id": "c-3", "action": "no_such"}).encode())
    by_name, all_spans = spans_of(exp)
    assert set(by_name) == {"cmd.receive"}, f"rejected 인데 {set(by_name)}"
    recv = by_name["cmd.receive"]
    assert recv.attributes["hw.command.result"] == "rejected"
    assert recv.attributes["hw.command.error"] == "unsupported_action"
    assert not recv.status.is_ok
    print(f"  3) rejected: receive 단독 종결, ERROR + 사유 ✓")

    # ---- 4) 수행 실패 ----
    exp.clear()
    run_command(eng, node, {"command_id": "c-4", "action": "boom"}, wait_stage="failed")
    by_name, all_spans = spans_of(exp)
    exe = by_name["cmd.execute"]
    assert not exe.status.is_ok and "actuator_jammed" in exe.status.description
    assert [e.name for e in exe.events] == ["stage.executing", "stage.failed"]
    print(f"  4) 수행 실패: execute=ERROR(actuator_jammed), stage.failed 이벤트 ✓")

    # ---- 5) no-op 에서도 엔진은 동일 동작 ----
    node2 = FakeNode()
    eng2 = CommandEngine(node2, node2.publish, "zoneA/sensor/t2", log=lambda *a: None)
    run_command(eng2, node2, {"command_id": "c-5", "action": "ok"}, wait_stage="completed")
    stages = [p.get("stage") for _, p in node2.published if p.get("channel") == "cmd/result"]
    assert stages == ["executing", "state_changed", "completed"], stages
    print(f"  5) no-op: tracer 없이 4단계 승격 동일 — 관측은 업무의 전제조건이 아니다 ✓")

    print("전부 통과")


if __name__ == "__main__":
    main()
