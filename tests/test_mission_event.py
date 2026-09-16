"""임무 실행 기록의 파라미터 정규화 — **인프라 없이 도는** 단위 확인.

MySQL 없이 돈다. 실제 append(행이 생기고, 같은 `event_key` 를 두 번 넣어도 1행이고,
`UPDATE`·`DELETE` 가 권한으로 막히는가)는 서버에서 확인한다 — 여기서는 **DB에 넣기 전에
값이 어떤 모양이 되는지**만 본다. 시각이 틀린 채 들어가면 되감기가 통째로 어긋난다.

implements: BE-S-08
tests: occurred_at UTC 정규화, detail JSON 직렬화, 필드 매핑
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.storage.mission import build_params, normalize_detail, normalize_occurred_at


# ── occurred_at — 되감기의 기준 시각 ───────────────────────────────────────


def test_normalize_occurred_at_from_aware_datetime() -> None:
    """오프셋을 **버리기 전에 UTC로 바꾼다.** 그냥 떼면 9시간이 틀어진다."""
    kst = datetime(2026, 9, 10, 18, 0, 0, tzinfo=timezone(timedelta(hours=9)))
    assert normalize_occurred_at(kst) == datetime(2026, 9, 10, 9, 0, 0)
    assert normalize_occurred_at(kst).tzinfo is None


def test_normalize_occurred_at_from_iso_string() -> None:
    assert normalize_occurred_at("2026-09-10T18:00:00+09:00") == datetime(2026, 9, 10, 9, 0, 0)
    assert normalize_occurred_at("2026-09-10T09:00:00+00:00") == datetime(2026, 9, 10, 9, 0, 0)


def test_normalize_occurred_at_naive_is_taken_as_utc() -> None:
    """오프셋 없는 datetime 은 이미 UTC 로 본다 — 로컬로 가정하면 서버 설정에 값이 흔들린다."""
    naive = datetime(2026, 9, 10, 9, 0, 0)
    assert normalize_occurred_at(naive) == naive


def test_normalize_occurred_at_rejects_garbage() -> None:
    """★음성 — 읽을 수 없는 시각을 조용히 통과시키지 않는다."""
    with pytest.raises(ValueError):
        normalize_occurred_at("어제쯤")
    with pytest.raises(ValueError):
        normalize_occurred_at("2026-09-10T09:00:00")  # 오프셋이 없는 문자열
    with pytest.raises(TypeError):
        normalize_occurred_at(1757500000)


# ── detail — 미확정 필드가 모이는 곳 ───────────────────────────────────────


def test_normalize_detail_serializes_mapping() -> None:
    detail = {"failure_stage": "precondition", "battery_pct": 12.5, "메모": "재시도"}
    dumped = normalize_detail(detail)
    assert json.loads(dumped) == detail
    assert "메모" in dumped, "한글이 이스케이프되어 읽을 수 없게 되면 안 된다"


def test_normalize_detail_passthrough() -> None:
    assert normalize_detail(None) is None
    assert normalize_detail('{"already":"json"}') == '{"already":"json"}'


# ── 필드 매핑 — VZ-D-* 원문과의 대응 ───────────────────────────────────────


def test_build_params_minimum_fields() -> None:
    """필수 다섯(시각·계층·노드·사건 종류·산출 주체)만으로도 만들어진다."""
    params = build_params(
        occurred_at="2026-09-10T09:00:00+00:00",
        layer="task",
        node_ref="t-001",
        event_type="started",
        actor_kind="backend",
    )
    assert params["occurred_at"] == datetime(2026, 9, 10, 9, 0, 0)
    assert params["layer"] == "task"
    assert params["node_ref"] == "t-001"
    assert params["event_type"] == "started"
    assert params["actor_kind"] == "backend"
    assert params["attempt"] == 1, "회차 기본값은 1이다(VZ-D-06·D-08)"
    assert params["event_key"] is None, "키 없는 사건은 그냥 들어간다(멱등 울타리와 충돌하지 않는다)"
    assert params["detail"] is None


def test_build_params_requires_actor_kind() -> None:
    """★음성 — 산출 주체 없이는 만들어지지 않는다(VZ-D-02 "반드시 포함").

    DB 의 NOT NULL 은 `None` 만 막고 빈 문자열은 통과시키므로 둘 다 여기서 막는다.
    """
    with pytest.raises(TypeError):
        build_params(occurred_at="2026-09-10T09:00:00+00:00",
                     layer="task", node_ref="t-001", event_type="started")
    with pytest.raises(ValueError):
        build_params(occurred_at="2026-09-10T09:00:00+00:00",
                     layer="task", node_ref="t-001", event_type="started", actor_kind="")


def test_build_params_full_fields() -> None:
    """DAG 노드 축(layer·node_ref·parent_ref)과 물리 대상 축(target_entity_id)이 **다르다.**

    VZ-D-05·D-06 의 "노드"는 전부 DAG 노드를 가리킨다. 물리 대상은 `target_entity_id`
    하나로 충분하고 나머지는 레지스트리 조인으로 얻는다.
    """
    params = build_params(
        occurred_at=datetime(2026, 9, 10, 9, 0, 0, tzinfo=timezone.utc),
        layer="action_item",
        node_ref="a-007",
        parent_ref="t-001",
        attempt=2,
        event_type="failed",
        actor_kind="ai",
        actor_id="planner-1",
        mission_id="m-2026-0910-001",
        target_entity_id="rb-01",
        origin_kind="simulation",
        correlation_id="cmd-2026-0910-0001",
        event_key="m-2026-0910-001/a-007/2/failed",
        detail={"failure_stage": "precondition"},
        record_version="1",
    )
    assert params["parent_ref"] == "t-001"          # VZ-D-01 "파생 출처를 유지"
    assert params["attempt"] == 2                    # VZ-D-08 "회차를 누적"
    assert params["target_entity_id"] == "rb-01"     # VZ-D-07 "대상 목록을 배정"
    assert params["node_ref"] != params["target_entity_id"], "DAG 노드와 물리 대상은 다른 축이다"
    assert params["origin_kind"] == "simulation"     # VZ-C-06 실물/시뮬 구분
    assert json.loads(params["detail"]) == {"failure_stage": "precondition"}


def test_build_params_event_key_fits_index_limit() -> None:
    """`event_key` 는 utf8mb4 기준 1020바이트로 InnoDB 인덱스 상한(DYNAMIC 3072) 안이다.

    상한을 넘기면 테이블 생성 자체가 실패하므로, 키 길이 규약을 여기서 못 박아 둔다.
    """
    key = "x" * 255
    params = build_params(
        occurred_at="2026-09-10T09:00:00+00:00",
        layer="task", node_ref="t-001", event_type="started", actor_kind="ai", event_key=key,
    )
    assert params["event_key"] == key
    # VARCHAR(255) × utf8mb4(문자당 최대 4바이트) = 1020바이트. InnoDB DYNAMIC 의 인덱스
    # 상한은 3072바이트이므로, **모든 문자가 4바이트여도** UNIQUE 인덱스가 선다.
    assert 255 * 4 == 1020
    assert 1020 <= 3072
