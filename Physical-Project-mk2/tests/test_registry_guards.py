"""레지스트리 가드 판정 — **인프라 없이 도는** 단위 확인.

MySQL 없이 돈다. 실제 대장 갱신(행이 생기고, 과거가 덮지 못하고, 이력이 1행 느는가)은
서버에서 확인한다 — 여기서는 **무엇을 갱신할지 판정하는 규칙**만 본다. 판정이 틀리면 그
위의 모든 조회가 조용히 틀린다.

가드 셋이 각각 무엇을 막는지:

- **시각 가드** — retained `status` 재전달과 재소비가 대장을 **과거로 되돌리는 것**
- **빈 문자열 가드** — 증강 분석의 빈 `mac`·`ip`가 **멀쩡한 값을 지우는 것**
- **이력 조건** — 바뀌지 않았는데 이력이 쌓이는 것, 빈 값이 "변경"으로 기록되는 것

implements: BE-Q-03, BE-C-02
tests: registration 추출, 빈 문자열 가드, 시각 가드, 이력 판정, UTC 변환
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.storage.registry import (
    FINGERPRINT_FIELDS,
    changed_fields,
    is_newer,
    pick,
    registration_of,
    to_mysql_utc,
)

REGISTRATION = {
    "entity_id": "wl-001",
    "node_id": "pi7",
    "zone_id": "zoneA",
    "entity_type": "sensor",
    "device_type": "water_level",
    "fw_version": "0.3.0",
    "mac": "b8:27:eb:aa:bb:cc",
    "ip": "192.168.50.31",
}


# ── registration 블록 추출 ─────────────────────────────────────────────────


def test_registration_of_plain() -> None:
    assert registration_of({"registration": REGISTRATION}) == REGISTRATION


def test_registration_of_unwraps_stateful_form() -> None:
    """누락값 규칙의 `{value, state}` 형태로 와도 벗겨서 읽는다."""
    wrapped = {"registration": {"value": REGISTRATION, "state": "unavailable"}}
    assert registration_of(wrapped) == REGISTRATION


def test_registration_of_absent_forms() -> None:
    """★ LWT에는 registration이 **아예 없다** — 그때 대장 쓰기는 아무 일도 하지 않아야 한다."""
    assert registration_of({"event": "death", "status": "offline", "reason": "lwt"}) is None
    assert registration_of({"registration": None}) is None
    # 값 없이 사유만 온 경우도 "등록 정보 없음"이다.
    assert registration_of({"registration": {"value": None, "state": "unsupported"}}) is None


# ── 빈 문자열 가드 ─────────────────────────────────────────────────────────


def test_pick_keeps_old_on_blank() -> None:
    """★ 증강 분석이 `Identity(..., "", "", ...)`로 보내는 빈 값이 기존 값을 지우지 않는다."""
    assert pick("", "b8:27:eb:aa:bb:cc") == "b8:27:eb:aa:bb:cc"
    assert pick("   ", "192.168.50.31") == "192.168.50.31"
    assert pick(None, "192.168.50.31") == "192.168.50.31", "안 보낸 것이 '지워라'가 되면 안 된다"


def test_pick_takes_new_when_present() -> None:
    assert pick("aa:bb:cc:dd:ee:ff", "b8:27:eb:aa:bb:cc") == "aa:bb:cc:dd:ee:ff"
    assert pick("sensor", None) == "sensor"
    # 값이 없던 자리에는 그대로 들어간다.
    assert pick(None, None) is None


# ── 시각 가드 ──────────────────────────────────────────────────────────────


def _t(seconds: int) -> datetime:
    return datetime(2026, 9, 10, 9, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds)


def test_is_newer_first_observation() -> None:
    assert is_newer(_t(0), None) is True


def test_is_newer_rejects_past_and_equal() -> None:
    """★ retained `status` 재전달과 재소비가 대장을 과거로 되돌리지 못한다.

    실측(2026-09-10): ingest 재기동 뒤 **47분 전 `ts`를 가진 retained status**가 그대로 다시
    흘렀다. 같은 시각도 막는다 — `timestamp`가 초 해상도라 같은 값이 여러 번 오고, 다시 써도
    얻는 것이 없다.
    """
    assert is_newer(_t(0), _t(60)) is False, "과거 status가 최신값을 덮으면 안 된다"
    assert is_newer(_t(60), _t(60)) is False, "같은 시각은 갱신하지 않는다"
    assert is_newer(_t(61), _t(60)) is True


def test_is_newer_without_timestamp() -> None:
    """시각을 못 읽었으면 갱신하지 않는다 — 모르는 것을 최신으로 단정하지 않는다."""
    assert is_newer(None, _t(0)) is False
    assert is_newer(None, None) is False


# ── 이력 기록 조건 ─────────────────────────────────────────────────────────


def test_fingerprint_fields_match_hardware() -> None:
    """이력 판정 조합이 HW `Identity.fingerprint()`와 같아야 한다.

    생산자의 재등록 판정 기준과 저장의 이력 기준이 어긋나면, 노드는 재등록했다고 보는데
    대장에는 이력이 안 남거나 그 반대가 된다.
    """
    assert FINGERPRINT_FIELDS == ("zone_id", "mac", "ip")


def test_changed_fields_none_when_same() -> None:
    previous = {"zone_id": "zoneA", "mac": "b8:27:eb:aa:bb:cc", "ip": "192.168.50.31"}
    assert changed_fields(previous, dict(previous)) == ()


def test_changed_fields_detects_each() -> None:
    previous = {"zone_id": "zoneA", "mac": "b8:27:eb:aa:bb:cc", "ip": "192.168.50.31"}
    assert changed_fields(previous, dict(previous, zone_id="zoneB")) == ("zone_id",)
    assert changed_fields(previous, dict(previous, ip="192.168.50.99")) == ("ip",)
    assert changed_fields(previous, {"zone_id": "zoneB", "mac": "aa:bb:cc:dd:ee:ff",
                                     "ip": "10.0.0.2"}) == ("zone_id", "mac", "ip")


def test_changed_fields_ignores_blank_incoming() -> None:
    """★ 빈 값이 **"변경"으로 기록되지 않는다.**

    빈 문자열 가드를 통과한 뒤의 값끼리 비교하기 때문이다. 이 순서가 뒤바뀌면 증강 분석이
    status를 보낼 때마다 "mac이 바뀌었다"는 이력이 무한히 쌓인다.
    """
    previous = {"zone_id": "zoneA", "mac": "b8:27:eb:aa:bb:cc", "ip": "192.168.50.31"}
    incoming = {"zone_id": "zoneA", "mac": "", "ip": ""}
    assert changed_fields(previous, incoming) == ()


def test_changed_fields_first_observation() -> None:
    """처음 보는 개체는 전부 '다름'이다 — 이력이 초기 상태부터 자립하게 한다."""
    previous = {"zone_id": None, "mac": None, "ip": None}
    incoming = {"zone_id": "zoneA", "mac": "b8:27:eb:aa:bb:cc", "ip": "192.168.50.31"}
    assert changed_fields(previous, incoming) == ("zone_id", "mac", "ip")


# ── MySQL 시각 변환 ────────────────────────────────────────────────────────


def test_to_mysql_utc_strips_offset_after_converting() -> None:
    """오프셋을 **버리기 전에 UTC로 바꾼다.** 그냥 떼면 9시간이 틀어진다."""
    kst = datetime(2026, 9, 10, 18, 0, 0, tzinfo=timezone(timedelta(hours=9)))
    assert to_mysql_utc(kst) == datetime(2026, 9, 10, 9, 0, 0)
    assert to_mysql_utc(kst).tzinfo is None, "DATETIME 칼럼은 오프셋을 받지 못한다"
    assert to_mysql_utc(None) is None


def test_to_mysql_utc_roundtrip_is_comparable() -> None:
    """읽어 올 때도 naive UTC라, 비교가 대칭이 된다(시각 가드가 성립하는 근거)."""
    earlier = to_mysql_utc(datetime(2026, 9, 10, 9, 0, 0, tzinfo=timezone.utc))
    later = to_mysql_utc(datetime(2026, 9, 10, 18, 0, 1, tzinfo=timezone(timedelta(hours=9))))
    assert later > earlier
    assert is_newer(later, earlier) is True
    assert is_newer(earlier, later) is False
