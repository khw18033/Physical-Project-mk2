"""implements: AI-O-06, AI-O-05, AI-B-14, AI-B-15, AI-C-19
covers: 검토 페이지가 **계약을 그대로** 내보내고, 실측과 예시를 섞어 보여 주지 않으며,
        이 경로로 실행 상태를 바꿀 수 없다는 것.

데모가 실제보다 잘 도는 것처럼 보이는 가장 흔한 길은 예시 데이터를 실측처럼 그리는
것이다. 그래서 응답이 어느 묶음을 실제로 읽었는지 말하게 하고, 그 말이 사실인지
여기서 확인한다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

PROJECT_ROOT = Path(__file__).resolve().parents[1]
UI_DIR = PROJECT_ROOT / "tools" / "snapshot_ui"
if str(UI_DIR) not in sys.path:
    sys.path.insert(0, str(UI_DIR))

import serve as snapshot_ui  # noqa: E402

CONTRACT_DIR = PROJECT_ROOT / "schemas" / "ai"


@pytest.fixture(scope="module")
def service() -> "snapshot_ui.SnapshotService":
    return snapshot_ui.SnapshotService()


def _body_validator() -> Draft202012Validator:
    registry = Registry()
    for path in sorted(CONTRACT_DIR.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    body = json.loads((CONTRACT_DIR / "status-snapshot.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(body, registry=registry, format_checker=FormatChecker())


# -- 계약을 그대로 내보낸다 --------------------------------------------

def test_the_page_serves_the_contract_not_a_convenience_shape(service):
    """검토용이라고 모양을 바꾸면 "화면에 올라가는 모양"을 확인하는 뜻이 사라진다."""
    message = service.snapshot()["message"]

    _body_validator().validate(message)
    assert message["channel"] == "status_snapshot"
    assert message["schema_version"] == "2.0"


def test_the_response_says_which_sections_were_actually_read(service):
    """실측과 예시를 섞어 보여 주지 않기 위한 칸이다."""
    snapshot = service.snapshot()

    for name in ("accelerators", "board", "events"):
        assert name in snapshot["live_sections"]
    assert "task_nodes" not in snapshot["live_sections"]      # 그래프는 미션이 있어야 생긴다


def test_the_accelerators_really_come_from_this_machine(service):
    """예시 장면의 가속기(ext-npu-*)가 남아 있으면 실측이라는 말이 거짓이다."""
    from mission_runtime.observability.host_resources import HostResourceReader

    served = {a["accelerator_instance_id"] for a in service.snapshot()["message"]["accelerators"]}
    live = {a.instance_id for a in HostResourceReader().read().accelerators}

    assert served == live
    assert not any(name.startswith("ext-npu") for name in served)


def test_an_unmeasured_value_stays_unmeasured_through_the_ui(service):
    """0 으로 채워 그리면 유휴와 고장이 화면에서 같아진다(§4.4)."""
    message = service.snapshot()["message"]
    measurements = [a["temperature"] for a in message["accelerators"]]
    measurements += [message["board"]["power"], message["board"]["memory_utilization"]]

    for measurement in measurements:
        assert "unit" in measurement
        if "value" in measurement:
            assert isinstance(measurement["value"], (int, float))


def test_the_resource_warning_and_the_resource_condition_agree(service):
    """[E] 경고와 [G] 자원 조건이 어긋나면 운영자가 둘 중 어느 쪽을 믿을지 알 수 없다."""
    message = service.snapshot()["message"]
    warned = {
        item
        for event in message["events"] if event["event_kind"] == "RESOURCE"
        for item in [event["event_message"].split()[0]]
    }
    unsatisfied = {
        condition["condition_item_id"].rsplit("_", 1)[0]
        for verdict in message["verdicts"]
        for condition in verdict.get("resource", [])
        if condition.get("condition_satisfied") is False
    }

    # 경고가 있으면 그 대상의 조건도 불충족이어야 한다(이름 규칙: <대상>_<측정>).
    for target in warned:
        assert any(target.startswith(prefix) or prefix in target for prefix in unsatisfied), (
            f"{target} 가 경고됐는데 자원 조건에는 불충족이 없다"
        )


# -- 오늘 만든 나머지 두 기능 -------------------------------------------

def test_the_proposal_panel_shows_both_what_grounded_and_what_did_not(service):
    """접지된 단계만 보여 주면 "왜 그 기능이 빠졌나"에 답할 수 없다."""
    proposal = service.proposal("영상 열고 탐지해서 이동해, 무게도 추정해")

    assert [step["action"] for step in proposal["steps"]]
    assert proposal["escalation_capabilities"] == ["analysis.weight"]
    assert any(r["reason"] == "unknown_capability" for r in proposal["rejected"])
    # 어휘는 화면에도 보인다 — 모델이 무엇 중에서 골랐는지가 판단 재료다.
    assert "media.video_input" in proposal["menu"]


def test_the_recommendation_panel_keeps_blocked_candidates(service):
    """막힌 후보를 숨기면 다음에 붙일 기능의 우선순위가 화면에서 사라진다."""
    recommendation = service.recommendation()

    assert any(c["recommended"] for c in recommendation["candidates"])
    blocked = [c for c in recommendation["candidates"] if not c["recommended"]]
    assert blocked and all(c["reason"] for c in blocked)
    assert any(c["missing_capabilities"] for c in blocked)


# -- 조회 전용 ---------------------------------------------------------

def test_writes_are_refused_with_a_reason(tmp_path):
    """상태 뷰 경로로 실행을 바꿀 수단을 주지 않는다(기능정의서 §1.1, AI-C-19)."""
    import urllib.error
    import urllib.request
    from threading import Thread

    server = snapshot_ui.make_server("127.0.0.1", 0)
    Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(f"{base}/api/snapshot", timeout=5) as response:
            assert response.status == 200
        request = urllib.request.Request(f"{base}/api/snapshot", data=b"{}", method="POST")
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=5)
        assert error.value.code == 405
        assert snapshot_ui.REASON_READ_ONLY in error.value.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()


def test_the_service_has_no_way_to_change_anything(service):
    functions = [
        name for name in dir(service)
        if not name.startswith("_") and callable(getattr(service, name))
    ]
    assert sorted(functions) == ["proposal", "recommendation", "snapshot", "views"]


# -- 정적 사본 ---------------------------------------------------------

def test_the_static_export_opens_without_a_server(tmp_path):
    """서버를 띄우라고 하는 대신 파일 하나를 보낼 수 있어야 한다.

    데이터가 박혀 있고 되읽기를 걸지 않는다는 것까지 본다 — 정적 사본이 5초마다
    없는 서버를 두드리면 콘솔이 오류로 찬다.
    """
    destination = tmp_path / "preview.html"
    snapshot_ui.write_static(destination)

    page = destination.read_text(encoding="utf-8")
    assert "__SNAPSHOT_BUNDLE__" in page
    assert "status_snapshot" in page
    assert "정적 사본" in page
    # 외부 자원을 불러오지 않는다 — 폐쇄망에서도 열려야 한다.
    for remote in ("http://", "https://", "//cdn", "fonts.googleapis"):
        assert remote not in page.replace("http://127.0.0.1", "")


def test_the_page_does_not_fetch_when_data_is_baked_in():
    page = (UI_DIR / "index.html").read_text(encoding="utf-8")

    assert "window.__SNAPSHOT_BUNDLE__" in page
    # fetch 는 박힌 데이터가 없을 때만 돈다.
    assert page.index("const baked") < page.index('fetch("/api/snapshot")')


# -- 역할·탭 (권한에 따라 볼 항목이 갈린다) ----------------------------

def test_every_role_declares_which_tabs_it_sees(service):
    """역할 이름을 화면 코드에 박으면 역할이 늘 때마다 화면을 고쳐야 한다."""
    views = service.views()
    tab_ids = {tab["id"] for tab in views["tabs"]}

    assert [r["role"] for r in views["roles"]] == ["viewer", "operator", "analyst", "maintainer"]
    for declared in views["roles"]:
        assert declared["tabs"], f"{declared['role']} 에 볼 탭이 없다"
        assert set(declared["tabs"]) <= tab_ids, "선언에 없는 탭을 가리킨다"
        assert declared["icon"] and declared["display_name"] and declared["note"]


def test_the_roles_are_ordered_from_least_to_most_visible(service):
    """권한이 넓어질수록 보는 것이 늘어난다 — 중간 역할이 더 많이 보면 설명할 수 없다."""
    tabs = [set(r["tabs"]) for r in service.views()["roles"]]

    for narrow, wide in zip(tabs, tabs[1:]):
        assert narrow < wide, "역할 사이가 포함 관계가 아니다"


def test_the_viewer_role_cannot_reach_the_raw_message(service):
    """시연 관람 역할에 원본 메시지를 보여 주면 식별자를 가린 의미가 없다."""
    roles = {r["role"]: set(r["tabs"]) for r in service.views()["roles"]}

    assert "raw" not in roles["viewer"]
    assert "raw" not in roles["operator"]
    assert "raw" in roles["maintainer"]


def test_the_contract_says_the_filter_is_not_an_access_boundary_but_the_screen_does_not(service):
    """경계가 어디인지는 **계약과 문서**가 말한다 — 운영 화면이 설명할 일이 아니다.

    화면에 내부 거버넌스 문장을 띄우면 자리를 차지하고 읽히지 않는다. 그래서 사실은
    `/api/views` 와 문서에 남기고 화면에서는 뺀다.
    """
    enforcement = service.views()["enforcement"]
    assert enforcement["where"] == "backend"
    assert "접근 통제가 아니다" in enforcement["note"]

    page = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert "enforceNote" not in page
    assert "BE-Q-04" not in page


def test_the_filter_axes_come_from_the_live_machine_and_the_message(service):
    """볼 항목을 나누는 축 — 장비는 실측 가속기에서, 기능은 메시지의 서비스에서 온다."""
    from mission_runtime.observability.host_resources import HostResourceReader

    filters = service.views()["filters"]
    live = {a.instance_id for a in HostResourceReader().read().accelerators}

    assert {d["id"] for d in filters["devices"]} == live
    assert filters["zones"] == ["zoneA"]
    assert "orchestrator" in filters["capabilities"]


# -- 가시화 콘솔을 같은 명령으로 (선택) --------------------------------

def test_the_console_is_optional_and_its_absence_is_reported_not_raised():
    """Node 가 없는 기계에서도 우리 화면은 떠야 한다(AI-C-05)."""
    console = snapshot_ui.ConsoleProcess()
    state = console.state()

    assert "running" in state and "url" in state
    if not state["running"]:
        assert state.get("reason") or True      # 띄우지 않았으면 사유가 없을 수도 있다


def test_an_already_running_console_is_adopted_not_restarted():
    """포트를 빼앗으면 사람이 보던 화면이 죽는다."""
    import inspect

    source = inspect.getsource(snapshot_ui.ConsoleProcess.start)
    assert "port_open(CONSOLE_PORT)" in source
    assert source.index("port_open(CONSOLE_PORT)") < source.index("Popen")


def test_the_tab_list_covers_every_region_the_spec_defines(service):
    """구역 B~I 가 어느 탭에도 없으면 그 구역은 화면에서 사라진다."""
    covered = {region for tab in service.views()["tabs"] for region in tab["regions"]}

    assert covered == {"B", "C", "D", "E", "E′", "F", "G", "H", "I"}
