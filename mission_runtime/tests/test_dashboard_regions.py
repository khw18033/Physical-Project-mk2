"""implements: AI-O-05, AI-O-06, AI-B-12, AI-B-13
covers: 종합상황정보 Dashboard 기능정의서
        (`internal/docs-dev/20260928-종합상황정보_Dashboard_기능정의서_2.docx`)가
        요구하는 화면 구역 B~I 각각에 대해, 그 구역이 쓸 데이터가 `tools/status_ui`
        의 통합 상태 뷰 응답에 **실제로 들어 있는지**를 고정한다.

왜 자료구조 시험과 따로 두는가
------------------------------
`tests/test_dashboard_view.py` 와 `tests/test_status_wire.py` 는 계약과 직렬화가
옳은지를 본다. 그런데 2026-11-03 감사에서 드러난 결손은 그 둘이 아니라 **배선**이었다
— 계약은 다 있는데 `tools/status_ui/serve.py` 가 어느 것도 import 하지 않아
`GET /api/dashboard` 가 404 였다. 자료형이 옳아도 화면이 받을 경로가 없으면 구역은
비어 있다. 그래서 이 파일은 조립된 **응답 한 장**을 기준으로 구역별 칸의 존재를
고정한다.

무엇을 고정하지 않는가
----------------------
수치의 값과 화면 레이아웃은 고정하지 않는다. 기능정의서 §1 이 "본 문서에 기술된
화면 구성과 수치는 개념 예시(Mock)"라고 적었고 표시는 가시화 책임이다(AI-C-19).
여기서 고정하는 것은 "그 구역이 요구하는 정보의 자리가 응답에 있는가"다.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

FRAMEWORK_DIR = Path(__file__).resolve().parents[1]
SERVE_PY = FRAMEWORK_DIR / "tools" / "status_ui" / "serve.py"
#: 구역 B~I 선언이 들어 있는 설정. 가속기·서비스·작업 노드는 전부 등록 데이터다
#: (문서 §3 요구사항 2: "화면에 고정 값으로 기술되어서는 안 된다").
DASHBOARD_CONFIG = FRAMEWORK_DIR / "config" / "status_ui.dashboard.example.json"
#: dashboard 블록이 **없는** 설정. 선언이 없는 배치도 정상이어야 한다(AI-C-05).
PLAIN_CONFIG = FRAMEWORK_DIR / "config" / "status_ui.example.json"


def _import_serve():
    name = "status_ui_serve_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SERVE_PY)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def serve():
    return _import_serve()


@pytest.fixture(scope="module")
def payload(serve) -> dict:
    """구역 B~I 가 선언된 배치의 통합 스냅샷 한 장."""
    service = serve.StatusService(serve.load_ui_config(DASHBOARD_CONFIG), control_mode="local")
    return service.dashboard()


def _node(payload: dict, node_id: str) -> dict:
    for node in payload["task_nodes"]:
        if node["task_node_id"] == node_id:
            return node
    raise AssertionError(f"task node {node_id!r} is not in the payload")


def _indicators(payload: dict) -> list[dict]:
    return [i for s in payload["services"] for i in s.get("indicators", [])]


# --- [B] 미션 상태 요약 · 서비스·가속기 배치 (문서 §4.1) ----------------------


def test_region_b_carries_mission_status_counts_and_accelerator_placement(payload):
    """미션 원문·상태·접수시각 / 상태별 노드 수 / 가속기→서비스 배치 / 미할당 표시.

    문서 §4.1: 미션명은 "사용자 입력 자연어 명령 **원문**", 배치는 "가속기 → 배치
    서비스" 방향이며 "미할당 가속기는 목록에서 생략하지 않고 미할당 상태로 표시한다".
    """
    mission = payload["mission"]
    assert mission["mission_id"]
    # 원문이다 — 요약·번역본이 아니라 사용자가 준 문장이 그대로 있어야 한다.
    assert mission["utterance_text"]
    assert mission["mission_status"]
    assert mission["accepted_at"]
    # 경과 시간은 접수 시각에서 파생한다(실시간 증가).
    assert payload["derived"]["mission_elapsed_s"] is not None

    derived = payload["derived"]
    assert derived["task_node_total"] == len(payload["task_nodes"])
    # 상태별 집계는 6상태 **전부**가 칸으로 있어야 한다 — 0 건도 아는 사실이다.
    assert len(derived["task_node_counts_by_state"]) == 6
    assert sum(derived["task_node_counts_by_state"].values()) == derived["task_node_total"]

    # 기준축이 가속기다. 배치된 서비스가 없는 가속기도 키로 남는다.
    placement = derived["accelerator_placement"]
    declared = {a["accelerator_instance_id"] for a in payload["accelerators"]}
    assert set(placement) == declared
    assert derived["idle_accelerator_instance_ids"], "미할당 가속기 예시가 사라졌다"
    for instance_id in derived["idle_accelerator_instance_ids"]:
        assert placement[instance_id] == []


def test_region_b_counts_are_derived_from_the_graph_not_sent_twice(payload):
    """집계와 그래프가 어긋날 수 없다 (문서 §4.1·§5 상태 일관성).

    "상태별 노드 수는 실행 그래프(C)의 노드 상태를 집계한 값이며, 그래프와 항상
    일치해야 한다." 그래서 집계를 따로 받아 적지 않고 같은 목록에서 센다.
    """
    counted: dict[str, int] = {}
    for node in payload["task_nodes"]:
        counted[node["task_node_state"]] = counted.get(node["task_node_state"], 0) + 1
    by_state = payload["derived"]["task_node_counts_by_state"]
    for state, total in counted.items():
        assert by_state[state] == total


# --- [C] 실행 그래프 (문서 §4.2) ---------------------------------------------


def test_region_c_carries_six_node_states_order_dependency_and_parallel_groups(payload):
    """노드 6상태 어휘 / 실행 순서(실선) / 의존(점선) / 병렬 그룹 / 상태 전이 시각.

    문서 §4.2 는 순서와 의존을 **다른 선**으로 요구하므로 한 칸에 합치면 그래프가
    복원되지 않는다. 그래서 `order_after` 와 `depends_on` 이 따로 나간다.
    """
    states = {"PENDING", "BLOCKED", "EXECUTING", "SUCCEEDED", "FAILED", "EXTERNAL_REQUESTED"}
    assert set(payload["derived"]["task_node_counts_by_state"]) == states
    # 예시 배치는 6상태를 전부 한 번씩 보여 준다 — 어휘가 있는 것과 쓰이는 것은 다르다.
    assert {n["task_node_state"] for n in payload["task_nodes"]} == states

    for node in payload["task_nodes"]:
        # 빈 목록이어도 칸은 있다. 칸이 없으면 "선행이 없다"와 "모른다"를 구분할 수 없다.
        assert isinstance(node["order_after"], list)
        assert isinstance(node["depends_on"], list)
    assert any(n["order_after"] for n in payload["task_nodes"]), "실행 순서 간선이 없다"
    assert any(n["depends_on"] for n in payload["task_nodes"]), "의존 간선이 없다"
    assert any(n.get("parallel_group") for n in payload["task_nodes"]), "병렬 그룹이 없다"
    assert any(n.get("state_changed_at") for n in payload["task_nodes"])


def test_region_c_node_cards_name_service_and_accelerator_together(payload):
    """노드 카드에 담당 서비스와 실행 가속기가 함께 적힌다 (문서 §4.2).

    "서비스명만으로는 어떤 가속기가 부하를 받고 있는지 판단할 수 없다."
    """
    on_device = [n for n in payload["task_nodes"] if n.get("service_id")]
    assert on_device
    for node in on_device:
        if node["task_node_state"] != "EXTERNAL_REQUESTED":
            assert node.get("accelerator_instance_id"), node["task_node_id"]


def test_region_c_keeps_the_producer_status_alongside_the_display_vocabulary(payload):
    """환산이 손실이 되지 않는다 (AI-B-12).

    작업 그래프의 정본은 생성 주체의 계약이고 우리는 소비한다. 표시 어휘 6종으로
    환산한 뒤에도 원본 상태 문자열이 남아야 "생성 주체의 상태 어휘가 소비 측 표시
    어휘보다 넓은 경우 원본 상태를 손실 없이 함께 유지"가 성립한다.
    """
    assert all(n.get("source_status") for n in payload["task_nodes"])


def test_region_c_reexecution_does_not_overwrite_the_original_node(payload):
    """재실행은 회차를 들고 다닌다 (문서 §4.2: "원 실패 노드의 이력이 소실되어서는
    안 된다")."""
    assert all("task_attempt" in n for n in payload["task_nodes"])
    assert all(n["task_attempt"] >= 1 for n in payload["task_nodes"])


# --- [D] 이벤트 / 알람 (문서 §4.3) -------------------------------------------


def test_region_d_carries_time_severity_kind_node_and_message(payload):
    """시각 / 심각도 / 관련 노드 / 메시지, 그리고 SDI 유형의 분리.

    문서 §4.3 은 "INFO / WARN / ERROR / SDI 등 등급·유형 구분"을 요구하지만 SDI 는
    등급이 아니라 **유형**이다. 한 칸에 섞으면 SDI 사건의 심각도를 적을 자리가
    사라지므로 `event_severity` 와 `event_kind` 를 따로 둔다.
    """
    events = payload["events"]
    assert events
    for event in events:
        assert event["event_severity"] in {"INFO", "WARN", "ERROR"}
        assert event["event_kind"] in {"EXECUTION", "EXTERNAL_REQUEST", "RESOURCE"}
        assert "event_message" in event
    # SDI 연계 사건이 일반 실행 사건과 섞이지 않고 식별된다.
    sdi = [e for e in events if e["event_kind"] == "EXTERNAL_REQUEST"]
    assert sdi, "SDI 유형 사건이 없다"
    assert all(e.get("external_request_id") for e in sdi)
    # 관련 노드로 그래프 강조·상세 전환의 진입점이 된다.
    assert any(e.get("task_node_id") for e in events)


def test_region_d_also_carries_what_the_panel_itself_recorded(serve):
    """실행 중에 생긴 사건이 [D] 에 들어온다 (문서 §4.3).

    선언된 사건만 보내면 화면은 "그래프에 드러나지 않는 미세한 상태 변화"를 추적할
    수 없다. 와이어 어휘(info/warning/critical)와 화면 등급(INFO/WARN/ERROR)은 서로
    다른 어휘이고 한쪽으로 합치지 않는다 — 변환만 한다.
    """
    service = serve.StatusService(serve.load_ui_config(DASHBOARD_CONFIG), control_mode="local")
    before = len(service.dashboard()["events"])

    service.record_event("placement_applied", "info")
    service.record_event("control_fallback", "warning")
    service.record_event("provider_lost", "critical")

    events = service.dashboard()["events"]
    assert len(events) == before + 3
    recorded = {e["event_message"]: e["event_severity"] for e in events}
    assert recorded["placement_applied"] == "INFO"
    assert recorded["control_fallback"] == "WARN"
    assert recorded["provider_lost"] == "ERROR"


# --- [E] 리소스 현황 (문서 §4.4) ---------------------------------------------


def test_region_e_separates_layer1_hardware_from_layer2_services(payload):
    """L1 과 L2 를 한 목록에 섞지 않는다 (문서 §4.4).

    "본 구역은 Layer 1 과 Layer 2 를 명시적으로 구분하여 표시한다." 두 계층이 한
    배열로 오면 화면은 "무엇이 느린가"를 계층으로 좁힐 수 없다(AI-O-05).
    """
    assert "accelerators" in payload and "services" in payload
    accel_ids = {a["accelerator_instance_id"] for a in payload["accelerators"]}
    service_ids = {s["service_id"] for s in payload["services"]}
    # 두 목록이 서로의 원소를 담지 않는다.
    assert not accel_ids & service_ids
    for accelerator in payload["accelerators"]:
        assert "service_id" not in accelerator
        assert "indicators" not in accelerator
    # 보드 수준 자원은 가속기 목록이 아니라 자기 칸에 있다.
    assert "memory_utilization" in payload["board"] and "power" in payload["board"]


def test_region_e_every_service_names_the_accelerator_it_runs_on(payload):
    """서비스 카드에 배치 가속기가 **필수 표기**된다 (문서 §4.4).

    "서비스 지연이 모델의 문제인지 가속기의 문제인지를 이 화면에서 좁힐 수 있어야
    한다." 그래서 서비스 지표에도 가속기가 함께 붙는다.
    """
    declared = {a["accelerator_instance_id"] for a in payload["accelerators"]}
    for service in payload["services"]:
        assert service["accelerator_instance_id"] in declared, service["service_id"]
        for indicator in service.get("indicators", []):
            assert indicator["accelerator_instance_id"] == service["accelerator_instance_id"]
            assert indicator["service_id"] == service["service_id"]


def test_region_e_individuates_accelerators_of_the_same_kind(payload):
    """같은 종류가 여럿일 때 서로 구분된다 (AI-O-05).

    문서 §1.2 의 구성은 외장 NPU 3종을 전제한다. 종류(`kind`)로만 식별하면 동종
    가속기 사이의 부하 편중을 볼 수 없으므로 개체는 `instance_id` 가 가른다.
    """
    ids = [a["accelerator_instance_id"] for a in payload["accelerators"]]
    assert len(ids) == len(set(ids)), "가속기 개체 식별자가 중복이다"

    by_kind: dict[str, list[str]] = {}
    for accelerator in payload["accelerators"]:
        by_kind.setdefault(accelerator["accelerator_kind"], []).append(
            accelerator["accelerator_instance_id"]
        )
    repeated = {kind: ids for kind, ids in by_kind.items() if len(ids) > 1}
    assert repeated, "같은 kind 가 여럿인 구성이 예시에서 사라졌다 — 개체 구분을 볼 수 없다"
    for kind, instance_ids in repeated.items():
        assert len(set(instance_ids)) == len(instance_ids), kind
    # 벤더 라벨은 표시용이고 식별자가 아니다 — 라벨이 없는 개체도 정상이다.
    assert any("accelerator_vendor_label" not in a for a in payload["accelerators"])


def test_region_e_keeps_idle_accelerators_in_the_list(payload):
    """배치된 기능이 없는 가속기도 목록에서 생략되지 않는다 (문서 §4.1·§4.4).

    "가속기 목록의 완전성이 유지되어야 자원 여유를 판단할 수 있다."
    """
    idle = payload["derived"]["idle_accelerator_instance_ids"]
    assert idle
    listed = {a["accelerator_instance_id"] for a in payload["accelerators"]}
    placed = {s["accelerator_instance_id"] for s in payload["services"]}
    for instance_id in idle:
        assert instance_id in listed, "유휴 가속기가 목록에서 빠졌다"
        assert instance_id not in placed


def test_region_e_not_measured_is_not_zero(payload):
    """미측정은 0 이 아니라 **값 칸의 부재**로 나간다 (문서 §4.4, AI-O-05).

    "서비스가 대기 상태여서 지표가 산출되지 않는 경우, 0이 아니라 측정 없음으로
    표시해야 한다." 측정된 0(유휴)과 못 잰 것을 같은 모양으로 보내면 유휴와 고장을
    구분할 수 없다.
    """
    unmeasured = payload["derived"]["unmeasured_accelerator_instance_ids"]
    assert unmeasured, "미측정 가속기 예시가 사라졌다 — 구분을 볼 수 없다"

    by_id = {a["accelerator_instance_id"]: a for a in payload["accelerators"]}
    for instance_id in unmeasured:
        utilization = by_id[instance_id]["utilization"]
        # 단위는 남고 값은 없다. 0.0 으로 채우지 않는다.
        assert "value" not in utilization
        assert utilization["unit"]
        assert "measured_at" not in utilization

    # 측정된 0 은 미측정과 다른 모양이다 — 값 칸이 있고 그 값이 0 이다.
    measured_zero = [
        a for a in payload["accelerators"]
        if a["utilization"].get("value") == 0.0
    ]
    assert measured_zero, "측정된 0(유휴) 예시가 사라졌다 — 미측정과 대조할 수 없다"
    for accelerator in measured_zero:
        assert accelerator["accelerator_instance_id"] not in unmeasured


def test_region_e_says_where_each_number_came_from(payload):
    """같은 칸의 숫자가 **실측인지 선언인지** 응답에서 갈린다 (AI-O-05, AI-C-01).

    2026-11-03 감사: "구역을 채우는 것은 선언 데이터다." 선언을 지우는 것이 답이
    아니라(§1 수치는 개념 예시) 어느 값이 계측인지 소비자가 **추측 없이** 알 수
    있어야 한다. 그래서 측정 묶음마다 출처가 붙고, 값이 없는 자리에는 붙지 않는다.
    """
    from mission_runtime.observability.layered_metrics import MEASUREMENT_SOURCES

    seen = set()
    for accelerator in payload["accelerators"]:
        for slot in ("utilization", "temperature"):
            measurement = accelerator[slot]
            source = measurement.get("measurement_source")
            if source is not None:
                assert source in MEASUREMENT_SOURCES, source
                seen.add(source)
            if "value" in measurement:
                # 숫자가 있으면 출처가 있다 — 출처 없는 숫자는 추측을 강요한다.
                assert source in ("measured", "declared"), accelerator
            else:
                # 값이 없으면 "재려 했으나 못 얻었다"이거나 아무도 채우지 않은 자리다.
                assert source in (None, "unavailable"), accelerator
    assert "declared" in seen, "선언값 예시가 사라졌다 — 실측과 대조할 수 없다"
    # 파생 목록은 세 상태를 둘로 줄이지 않는다.
    derived = payload["derived"]
    measured = set(derived["measured_accelerator_instance_ids"])
    unmeasured = set(derived["unmeasured_accelerator_instance_ids"])
    assert not measured & unmeasured


def test_region_e_measured_slots_name_the_probe_that_read_them(payload):
    """실측이 된 개체는 **어느 계측 지점이 읽었는지**를 함께 싣는다 (AI-O-05).

    못 읽은 칸의 사유도 같은 응답에 있다 — 관측 실패는 응답을 멈추지 않고 사유로
    남는다(AI-O-01: "외부 관측 기능 장애가 실제 기능 실행을 중단시키지 않아야 한다").
    """
    from mission_runtime.observability.host_resources import HOST_PROBE_REASONS

    probed = [a for a in payload["accelerators"] if "host_probe_id" in a]
    assert probed, "계측 지점을 지목한 개체 선언이 사라졌다"
    for accelerator in probed:
        for slot in ("utilization", "temperature"):
            # 지목한 칸은 실측이거나 미측정이다 — 선언 숫자가 그 자리를 채우지 않는다.
            assert accelerator[slot].get("measurement_source") in ("measured", "unavailable"), (
                accelerator["accelerator_instance_id"], slot
            )
    status = payload["derived"]["host_probe_status"]
    assert status, "계측 지점 상태가 비었다 — 무엇을 왜 못 읽었는지 알 수 없다"
    for key, reason in status.items():
        assert reason in HOST_PROBE_REASONS, (key, reason)


def test_region_e_power_is_present_even_when_this_machine_cannot_read_it(payload):
    """전력은 칸을 지우지 않는다 (문서 §4.4 구역 E, AI-O-01).

    RAPL 이 없는 기계(WSL 등)에서는 값이 없고 **그 사실이 응답**이다. 선언된 예시
    숫자로 메우지도, 0 으로 메우지도 않는다.
    """
    power = payload["board"]["power"]

    assert power["unit"] == "watt"
    assert power.get("measurement_source") in ("measured", "unavailable")
    if "value" in power:
        assert power["measurement_source"] == "measured"
        assert power["value"] >= 0.0
    else:
        assert power["measurement_source"] == "unavailable"


def test_region_e_measuring_drops_nothing_from_the_accelerator_list(payload):
    """실측이 붙어도 선언된 개체 수는 그대로다 (문서 §4.1·§4.4 완전성)."""
    declared = json.loads(DASHBOARD_CONFIG.read_text(encoding="utf-8"))
    expected = [a["instance_id"] for a in declared["dashboard"]["accelerators"]]

    assert [a["accelerator_instance_id"] for a in payload["accelerators"]] == expected


def test_region_e_a_broken_reader_does_not_take_the_response_down(serve):
    """계측기가 터져도 아홉 구역은 그대로 나간다 (AI-O-01, AI-C-05).

    선택 구성요소의 결손은 축소이지 전체 실패가 아니다. 실측이 없으면 선언값만
    남고, 못 읽었다는 사실이 사유로 적힌다.
    """
    class Exploding:
        def readout(self):
            raise RuntimeError("계측기가 죽었다")

    service = serve.StatusService(serve.load_ui_config(DASHBOARD_CONFIG),
                                  control_mode="local", host_reader=Exploding())
    payload = service.dashboard()

    assert payload["derived"]["unavailable_region_ids"] == []
    assert payload["derived"]["measured_accelerator_instance_ids"] == []
    assert "tool_failed" in payload["derived"]["host_probe_status"]["host_reader"]
    # 실측이 없으면 선언값이 선언이라고 적힌 채 남는다 — 구역이 비지 않는다.
    by_id = {a["accelerator_instance_id"]: a for a in payload["accelerators"]}
    assert by_id["cpu-0"]["utilization"]["measurement_source"] == "declared"


def test_region_e_a_deployment_without_the_reader_serves_declared_values(serve):
    """실측 경로가 없는 배치도 정상이다 — 선언값만 나가고 그렇게 적힌다."""
    service = serve.StatusService(serve.load_ui_config(DASHBOARD_CONFIG),
                                  control_mode="local", host_reader=False)
    payload = service.dashboard()

    assert payload["derived"]["measured_accelerator_instance_ids"] == []
    assert payload["derived"]["host_probe_status"] == {"host_reader": "tool_missing"}
    assert not any("host_probe_id" in a for a in payload["accelerators"])


# --- [E′] 주요 성능 지표 (문서 §4.5) ----------------------------------------


def test_region_e_prime_carries_value_target_and_trend_with_producer(payload):
    """지표별 현재값 / 목표 기준선 / 추이, 그리고 산출 서비스·가속기 병기.

    문서 §4.5: 지표명은 "산출 서비스 및 가속기를 병기", 목표 기준선은 "그래프상
    실제 값 위치에 표시되어야 한다" — 그래서 기준선과 표본이 같은 단위로 나간다.
    """
    indicators = _indicators(payload)
    assert indicators
    for indicator in indicators:
        assert indicator["indicator_name"]
        assert indicator["service_id"]
        assert indicator["accelerator_instance_id"]
        assert indicator["measurement"]["unit"]
        if indicator.get("target"):
            assert indicator["target"]["unit"] == indicator["measurement"]["unit"]
            assert indicator["target"]["direction"] in {"AT_LEAST", "AT_MOST"}
    assert any(i.get("trend") for i in indicators), "추이 표본이 있는 지표가 없다"


def test_region_e_prime_target_verdict_has_three_values(payload):
    """충족 / 미달 / **미측정** 세 값이며 둘로 줄지 않는다 (문서 §4.5, AI-O-05).

    "서비스 대기 등으로 지표가 산출되지 않는 구간은 '미달'이 아니라 측정 없음으로
    구분 표시해야 한다."
    """
    indicators = _indicators(payload)
    seen = {i["target_meet_state"] for i in indicators}
    assert seen == {"MET", "UNMET", "NOT_MEASURED"}, f"3값 판정이 보이지 않는다: {seen}"

    not_measured = payload["derived"]["not_measured_indicator_names"]
    unmet = payload["derived"]["unmet_indicator_names"]
    assert not_measured and unmet
    # 미측정이 미달 목록에 섞여 집계되지 않는다.
    assert not set(not_measured) & set(unmet)

    by_name = {i["indicator_name"]: i for i in indicators}
    for name in not_measured:
        assert by_name[name]["target_meet_state"] == "NOT_MEASURED"
        # 미측정 지표는 값 칸이 없다 — 0 으로 메우지 않는다.
        assert "value" not in by_name[name]["measurement"]
    for name in unmet:
        assert by_name[name]["measurement"].get("value") is not None


# --- [F] 선택 노드 상세 (문서 §4.6) ------------------------------------------


def test_region_f_focus_follows_automatically_and_pins_on_request(serve):
    """자동 추종(기본)과 수동 고정 두 모드, 그리고 고정 해제 (문서 §2).

    "두 모드는 모두 제공되어야 하며, 현재 어떤 모드인지가 화면에 명시되어야 한다."
    고정은 **관찰 방식의 변경**이므로 조회 경로에 있다(§1.1).
    """
    service = serve.StatusService(serve.load_ui_config(DASHBOARD_CONFIG), control_mode="local")

    auto = service.dashboard()["focus"]
    assert auto["focus_pinned"] is False
    assert auto["focus_reason"]
    # 실행 중인 노드가 복수일 때의 선택 기준이 결정적이다 — 같은 입력에 같은 답.
    assert service.dashboard()["focus"] == auto

    pinned = service.dashboard(pin="n2")["focus"]
    assert pinned["task_node_id"] == "n2"
    assert pinned["focus_pinned"] is True
    assert pinned["focus_reason"] != auto["focus_reason"]

    # 고정 해제는 자동 추종으로 되돌린다.
    assert service.dashboard(pin="")["focus"]["focus_pinned"] is False


def test_region_f_detail_fields_are_present_for_a_running_node(payload):
    """노드 식별 / 담당 서비스 / 실행 가속기 / 시작·예상완료 / 진행률 / 입력 명령 원문.

    문서 §4.6: 담당 서비스와 실행 가속기는 "별도 항목으로 분리 표시되어야 하며,
    하나의 '수행 위치' 항목으로 합쳐서는 안 된다". 입력 명령 원문은 "생략되어서는
    안 된다".
    """
    running = [n for n in payload["task_nodes"] if n["task_node_state"] == "EXECUTING"]
    assert running
    node = running[0]
    assert node["task_node_id"] and node["node_title"]
    # 두 계층이 다른 칸이다.
    assert node["service_id"] and node["accelerator_instance_id"]
    assert node["service_id"] != node["accelerator_instance_id"]
    assert node["started_at"] and node["estimated_completion_at"]
    assert node["progress_ratio"] is not None
    assert node["input_command"]


def test_region_f_marks_a_node_that_runs_off_device(payload):
    """온디바이스 가속기에서 수행되지 않는 노드 (문서 §4.6).

    "외부 기능 요청 노드와 같이 온디바이스 가속기에서 수행되지 않는 노드는 실행
    가속기 항목에 온디바이스 외부임을 명시한다." 가속기 칸의 **부재**가 그 사실이고
    빈 문자열이나 가짜 가속기 id 로 가리지 않는다.
    """
    external = [n for n in payload["task_nodes"] if n["task_node_state"] == "EXTERNAL_REQUESTED"]
    assert external
    for node in external:
        assert "accelerator_instance_id" not in node
        # 어느 요청 때문에 온디바이스 밖에 있는지로 [I] 와 이어진다.
        assert node["external_request_id"]


# --- [G] 조건 및 판정 (문서 §4.7) --------------------------------------------


def test_region_g_carries_three_condition_axes_item_by_item(payload):
    """완료 / 실패 / 자원 3축을 **항목 단위**로 (문서 §4.7).

    "각 조건은 상태가 개별 항목 단위로 표시되어야 하며, 요약 수치만 제공해서는 안
    된다." 집계만 받으면 화면이 그 요구를 지킬 수 없으므로 집계를 싣지 않는다.
    """
    assert payload["verdicts"]
    for verdict in payload["verdicts"]:
        assert verdict["task_node_id"]
        for axis in ("completion", "failure", "resource"):
            assert axis in verdict, axis
            for item in verdict[axis]:
                assert item["condition_item_id"]
        # 요약 수치는 응답에 없다 — 항목에서 파생시킨다.
        assert "completion_tally" not in verdict
        assert "satisfied_count" not in verdict


def test_region_g_unknown_condition_is_not_false(payload):
    """판정할 근거가 없는 조건은 미충족과 다른 상태다.

    `condition_satisfied` 칸의 부재가 "미확인"이고, False(미충족)와 같은 칸에 담지
    않는다. 섞으면 "아직 모른다"가 "실패했다"로 보인다.
    """
    items = [i for v in payload["verdicts"] for a in ("completion", "failure", "resource")
             for i in v[a]]
    assert items
    unknown = [i for i in items if "condition_satisfied" not in i]
    assert unknown, "미확인 조건 예시가 사라졌다 — 미충족과 대조할 수 없다"
    assert any(i.get("condition_satisfied") is False for i in items)
    for item in unknown:
        # 왜 모르는지는 통제 어휘 토큰으로 남는다. 표시 문구는 화면이 만든다.
        assert item.get("condition_reason")


def test_region_g_escalation_links_the_verdict_to_the_external_request(payload):
    """승격 표시 — 판정 결과와 후속 조치가 끊기지 않는다 (문서 §4.7).

    "실패 조건이 충족되고 온디바이스 대체 수단이 없다고 판정된 경우, 해당 노드가
    외부 기능 요청으로 승격되었음과 **그 요청 식별자**를 본 구역에 함께 표시해야
    한다."
    """
    escalated = [v for v in payload["verdicts"] if v.get("escalated_request_id")]
    assert escalated, "승격된 판정 예시가 없다"
    known = {r["external_request_id"] for r in payload["external_requests"]}
    for verdict in escalated:
        # 식별자가 실제 요청을 가리킨다 — 끊긴 참조는 추적이 아니다.
        assert verdict["escalated_request_id"] in known


# --- [H] 노드별 이벤트 로그 (문서 §4.8) --------------------------------------


def test_region_h_events_can_be_filtered_by_node_and_keep_attempts(payload):
    """선택 노드로 필터되는 뷰이고 회차별 이력이 보존된다 (문서 §4.8).

    "재실행된 노드는 회차별 이력이 모두 조회 가능해야 한다. 재실행이 이전 회차의
    로그를 덮어써서는 안 된다." 그래서 사건이 `task_attempt` 를 들고 다니고, 같은
    사건을 [D] 와 [H] 두 목록으로 보내지 않는다 — 둘이 어긋나는 날이 온다.
    """
    events = payload["events"]
    with_node = [e for e in events if e.get("task_node_id")]
    assert with_node, "노드로 필터할 수 있는 사건이 없다"
    # 필터 축이 작업 노드다(장치 노드가 아니다).
    known = {n["task_node_id"] for n in payload["task_nodes"]}
    assert {e["task_node_id"] for e in with_node} <= known

    with_attempt = [e for e in events if e.get("task_attempt")]
    assert with_attempt, "회차가 붙은 사건 예시가 사라졌다"

    # [H] 전용 중복 목록이 없다.
    assert "node_events" not in payload
    assert "events_by_node" not in payload


# --- [I] 외부 기능 요청 (SDI 연계) (문서 §4.9, AI-B-13) ----------------------


def test_region_i_covers_all_six_stages(payload):
    """6단계 스테퍼가 전부 표현된다 (문서 §4.9 "요청 처리 단계")."""
    stages = {
        transition["external_request_stage"]
        for request in payload["external_requests"]
        for transition in request["stage_times"]
    }
    assert stages == {
        "JUDGED", "SENT", "SERVER_WORKING", "DEPLOYED", "RE_EXECUTING", "SETTLED",
    }, f"6단계가 다 보이지 않는다: {sorted(stages)}"
    # 각 단계의 전이 시각이 함께 나간다.
    for request in payload["external_requests"]:
        for transition in request["stage_times"]:
            assert transition.get("stage_entered_at")


def test_region_i_carries_identifier_reason_node_and_final_verdict(payload):
    """요청 식별자 / 요청 사유(두 종) / 발생 노드 / 배포 버전 / 재실행 회차 / 최종 판정.

    요청이 발생하는 조건은 미지원 기능과 시뮬–실물 불일치 두 가지이고, 둘을 구분해야
    한다(문서 §4.9, AI-B-13: "판정 사유는 기능 미탑재와 시뮬·실물 결과 불일치를
    구분해야").
    """
    requests = payload["external_requests"]
    assert requests
    for request in requests:
        assert request["external_request_id"]
        assert request["external_request_reason"] in {
            "UNSUPPORTED_CAPABILITY", "SIM_REAL_MISMATCH"
        }
        assert request["external_request_reason_detail"]
        assert request["task_node_id"]
        assert request["requested_at"]
        assert request["external_request_verdict"] in {"PENDING", "SUCCEEDED", "FAILED"}
        assert isinstance(request["re_execution_count"], int)
    # 두 사유가 모두 표현 가능하다는 것을 예시가 보여 준다.
    assert {r["external_request_reason"] for r in requests} == {
        "UNSUPPORTED_CAPABILITY", "SIM_REAL_MISMATCH"
    }


def test_region_i_server_interior_is_not_observable(payload):
    """3단계는 "처리 중" 여부만이고 서버 내부는 칸이 없다 (문서 §4.9, AI-B-13).

    "서버측 개발 진척도·담당·빌드 상태 등은 표시 대상이 아니다." 칸을 만들어 두면
    언젠가 채워지므로 **부재**로 구현하고 그 부재를 시험이 고정한다.
    """
    forbidden = (
        "server_progress", "progress", "assignee", "owner", "build_status",
        "build_number", "server_internal", "review_state", "commit",
    )
    for request in payload["external_requests"]:
        for key in forbidden:
            assert key not in request, f"서버 내부 칸이 생겼다: {key}"
        # 대신 "지금 그 구간에 있다"만 알린다.
        assert isinstance(request["server_work_is_opaque"], bool)

    opaque = [r for r in payload["external_requests"] if r["server_work_is_opaque"]]
    assert opaque, "서버 처리 중인 요청 예시가 없다"
    for request in opaque:
        assert request["external_request_stage"] == "SERVER_WORKING"


def test_region_i_distinguishes_deployment_not_received_from_received(payload):
    """배포 미수신을 받은 것과 구분한다 (문서 §4.9: "미수신 시 미수신으로 표시").

    미수신을 `deployment_version: null` 로 적지 않는다 — 버전 칸은 받았을 때만
    생기고, 받았다는 사실은 따로 나간다. 한 칸의 유무로 두 뜻을 겸하면 흐려진다.
    """
    received = [r for r in payload["external_requests"] if r["deployment_received"]]
    not_received = [r for r in payload["external_requests"] if not r["deployment_received"]]
    assert received and not_received, "두 경우가 모두 있는 예시가 아니다"
    for request in received:
        assert request["deployment_version"]
    for request in not_received:
        assert "deployment_version" not in request


def test_region_i_stays_on_screen_when_there_is_no_request(serve):
    """진행 중인 요청이 없는 배치에서도 구역이 사라지지 않는다 (문서 §4.9).

    "요청 없음 상태를 명시한다." 요청이 없는 것은 정상 상태이고 기능 비활성이
    다른 구역을 막지 않는다(AI-C-05, AI-B-13: "요청이 없는 배치에서도 이 기능은
    비활성 상태로 정상 동작해야 한다").
    """
    payload = serve.StatusService(
        serve.load_ui_config(PLAIN_CONFIG), control_mode="local"
    ).dashboard()
    assert payload["external_requests"] == []
    assert payload["derived"]["has_external_requests"] is False
    # 구역 I 가 응답에서 빠지지 않는다.
    assert "I" in {r["region_id"] for r in payload["regions"]}


# --- §2·§3 구역 목록과 소스별 결손 격리 --------------------------------------


def test_every_declared_region_b_through_i_is_reported(payload):
    """구역 9개가 모두 응답에 있다 (문서 §2 구역 표).

    A(글로벌 내비게이션)는 문서가 정의 범위 외로 둔다. 남은 9개는 B·C·D·E·E′·F·G·H·I 다.
    """
    reported = {r["region_id"] for r in payload["regions"]}
    assert reported == {"B", "C", "D", "E", "E_PRIME", "F", "G", "H", "I"}
    assert "A" not in reported
    # 선언이 온 배치에서는 아홉 구역 전부가 표시 가능하다.
    assert payload["derived"]["unavailable_region_ids"] == []
    for state in payload["regions"]:
        assert state["region_available"] is True


def test_a_silent_source_degrades_only_its_own_region(serve):
    """한 소스가 조용해도 나머지 구역은 정상이다 (문서 §3 요구사항 5, AI-C-05).

    "일부 소스가 일시적으로 응답하지 않더라도 나머지 구역은 정상 표시되어야 하며,
    해당 구역은 데이터 미수신 상태를 명시해야 한다." 한 번도 받지 못한 소스는
    시각이 없고, 그것이 "수신했으나 오래된 상태"와 구분된다(문서 §5).

    구역이 비는 것은 그 구역을 먹이는 소스가 **전부** 조용할 때다. 한 소스만 끊겨도
    다른 소스가 같은 구역을 먹이면 구역은 그대로 나온다 — 그래서 이 시험은 SDI
    채널을 구역 I 의 유일한 소스로 두고 그 하나를 침묵시킨다.
    """
    raw = json.loads(DASHBOARD_CONFIG.read_text(encoding="utf-8"))
    sources = []
    for source in raw["dashboard"]["sources"]:
        if source["source_id"] == "sdi-channel":
            continue
        # 구역 I 를 먹이는 다른 소스를 떼어 내 SDI 채널만 남긴다.
        source = dict(source, feeds=[f for f in source["feeds"] if f != "I"])
        sources.append(source)
    # 한 번도 수신하지 않은 소스 — `last_received_at` 칸 자체가 없다.
    sources.append({"source_id": "sdi-channel", "layer": "external", "feeds": ["I"]})
    raw["dashboard"]["sources"] = sources
    # 상대경로(providers_manifest·labels)가 원래 자리를 가리키도록 같은 폴더에서 읽게 한다.
    target = DASHBOARD_CONFIG.parent / "status_ui.silent.test.json"
    target.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    try:
        payload = serve.StatusService(
            serve.load_ui_config(target), control_mode="local"
        ).dashboard()
    finally:
        target.unlink()

    states = {r["region_id"]: r for r in payload["regions"]}
    assert states["I"]["region_available"] is False
    assert states["I"]["region_reason"] == "source_not_received"
    assert states["I"]["missing_sources"] == ["sdi-channel"]
    # 결손은 축소이지 전체 실패가 아니다 — 나머지 여덟 구역은 그대로다.
    for region_id, state in states.items():
        if region_id != "I":
            assert state["region_available"] is True, region_id

    silent = [s for s in payload["sources"] if s["source_id"] == "sdi-channel"][0]
    # 한 번도 못 받았으면 시각 칸이 없다 — 시각을 지어내지 않는다.
    assert "last_received_at" not in silent
    assert silent["source_stale"] is False


def test_a_config_without_a_dashboard_block_still_serves_the_regions(serve):
    """선언이 없는 배치도 정상이다 (AI-C-05).

    구역을 지우지 않고 "아직 데이터가 없다"는 사실을 적는 것이 요구다. 작업 그래프를
    받지 못한 배치에서 L3 구역만 비고 나머지는 그대로 나와야 한다.
    """
    payload = serve.StatusService(
        serve.load_ui_config(PLAIN_CONFIG), control_mode="local"
    ).dashboard()

    assert {r["region_id"] for r in payload["regions"]} == {
        "B", "C", "D", "E", "E_PRIME", "F", "G", "H", "I"
    }
    states = {r["region_id"]: r for r in payload["regions"]}
    # 작업 그래프와 판정이 없으면 그 두 구역은 사유와 함께 비었다고 적는다.
    assert states["C"]["region_available"] is False
    assert states["C"]["region_reason"] == "no_data_yet"
    assert states["G"]["region_available"] is False
    assert payload["task_nodes"] == []
    # 미측정을 0 으로 채우지 않는다 — 가속기 선언이 없으면 목록이 비는 것이 사실이다.
    assert payload["accelerators"] == []
    assert "value" not in payload["board"]["power"]


# --- §1.1·§5 조회 전용 원칙 ---------------------------------------------------


def test_the_snapshot_carries_no_control_surface(payload):
    """상태 뷰 계약으로는 실행 상태를 바꿀 수 없다 (문서 §5 조회 전용 원칙, AI-O-06).

    "상태 뷰는 조회 전용이어야 하며 이 경로를 통해 실행 상태를 변경하는 수단을
    제공해서는 안 된다."
    """
    text = json.dumps(payload)
    for token in ("\"start\"", "\"stop\"", "\"deploy\"", "\"rollback\"", "\"cancel\""):
        assert token not in text, f"상태 뷰에 제어 어휘가 섞였다: {token}"
    for key in ("commands", "actions", "controls", "mutations"):
        assert key not in payload


def test_the_dashboard_path_refuses_post_before_reading_the_body(serve):
    """조회 경로의 POST 는 본문을 읽기 전에 405 다 (AI-O-06).

    제어가 필요한 기능은 상태 조회 계약과 **분리된 별도 계약**으로 제공한다. 본문을
    먼저 읽으면 거부한 요청의 내용이 처리 경로에 들어온다.
    """
    service = serve.StatusService(serve.load_ui_config(DASHBOARD_CONFIG), control_mode="local")
    server = serve.make_server(service, host="127.0.0.1", port=0, ui_dir=SERVE_PY.parent)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = serve.server_url(server)
        with urllib.request.urlopen(f"{base}/api/dashboard", timeout=10) as response:
            assert response.status == 200
            body = json.loads(response.read())
        assert {r["region_id"] for r in body["regions"]} == {
            "B", "C", "D", "E", "E_PRIME", "F", "G", "H", "I"
        }

        request = urllib.request.Request(
            f"{base}/api/dashboard", data=b"{\"pin\": \"n2\"}", method="POST"
        )
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=10)
        assert caught.value.code == 405
        refusal = json.loads(caught.value.read())
        assert refusal["error"] == "query_only_path"
        assert refusal["allowed_methods"] == ["GET"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# --- AI-O-05 계층·개체 축이 등록 데이터라는 것 --------------------------------


def test_new_accelerator_needs_no_core_code_change(serve, tmp_path):
    """가속기 종류·부착 형태는 벤더 열거형이 아니라 등록 데이터다 (AI-O-05).

    "새 하드웨어 추가가 핵심 코드 변경을 요구하지 않아야 한다." 처음 보는 kind 와
    attachment 문자열이 그대로 통과하는지로 고정한다 — 코드가 값으로 갈라지면
    여기서 거부당한다.
    """
    raw = json.loads(DASHBOARD_CONFIG.read_text(encoding="utf-8"))
    raw["dashboard"]["accelerators"].append({
        "instance_id": "made-up-accel-0",
        "kind": "wafer_scale_doodad",
        "attachment": "pcie_riser",
        "vendor_label": "존재하지 않는 제품",
        "utilization": {"value": 0.11, "unit": "ratio"},
    })
    raw["dashboard"]["services"].append({
        "service_id": "made-up-service",
        "accelerator_id": "made-up-accel-0",
        "role": "처음 보는 역할",
    })
    target = DASHBOARD_CONFIG.parent / "status_ui.newhw.test.json"
    target.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    try:
        payload = serve.StatusService(
            serve.load_ui_config(target), control_mode="local"
        ).dashboard()
    finally:
        target.unlink()

    by_id = {a["accelerator_instance_id"]: a for a in payload["accelerators"]}
    assert by_id["made-up-accel-0"]["accelerator_kind"] == "wafer_scale_doodad"
    assert by_id["made-up-accel-0"]["accelerator_attachment"] == "pcie_riser"
    assert payload["derived"]["accelerator_placement"]["made-up-accel-0"] == ["made-up-service"]
    # 새 개체가 들어와도 다른 구역은 그대로다.
    assert payload["derived"]["unavailable_region_ids"] == []


def test_a_service_on_an_unknown_accelerator_is_rejected_at_load(serve, tmp_path):
    """배치 가속기가 목록에 없으면 로드 시점에 거부한다.

    기능정의서 §4.4 가 배치 가속기를 필수 표기로 두는 이유는 서비스 지연의 원인을
    계층으로 좁히는 것이다. 없는 가속기를 가리키는 배치는 그 추적을 끊으므로
    화면 요청 때까지 숨겨 두지 않고 설정을 읽을 때 거절한다.
    """
    raw = json.loads(DASHBOARD_CONFIG.read_text(encoding="utf-8"))
    raw["dashboard"]["services"].append({
        "service_id": "orphan-service", "accelerator_id": "no-such-accelerator",
    })
    target = DASHBOARD_CONFIG.parent / "status_ui.orphan.test.json"
    target.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    try:
        with pytest.raises(serve.UiConfigError) as caught:
            serve.load_ui_config(target)
    finally:
        target.unlink()
    assert "no-such-accelerator" in str(caught.value)


def test_a_measurement_without_a_value_never_becomes_zero(serve):
    """선언에 값이 없으면 미측정이고, 0 으로 바뀌지 않는다 (AI-O-05).

    로더 한 단계만 따로 고정한다 — 조립 전체를 돌리지 않아도 "0 으로 메우지 않는다"가
    깨지면 여기서 먼저 걸린다.
    """
    assert serve._dash_measurement("t", None, "ratio").value is None
    assert serve._dash_measurement("t", {"unit": "ratio"}, "ratio").value is None
    assert serve._dash_measurement("t", {"value": None, "unit": "ratio"}, "ratio").value is None
    # 측정된 0 은 0 으로 남는다 — 미측정으로 바꿔 읽지 않는다.
    measured = serve._dash_measurement("t", {"value": 0.0, "unit": "ratio"}, "ratio")
    assert measured.value == 0.0 and measured.measured is True
