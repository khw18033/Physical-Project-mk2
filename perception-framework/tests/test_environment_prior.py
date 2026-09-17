"""implements: AI-S-08
covers: prior-info provenance/version/validity, revision-not-overwrite, re-evaluation candidates
"""

from perception_framework.perception.environment_prior import (
    PriorInfoRecord,
    PriorInfoStore,
    PriorKind,
)


def record(**overrides) -> PriorInfoRecord:
    base = dict(
        record_id="p-1",
        kind=PriorKind.INFRASTRUCTURE.value,
        source="facility_db",
        scope=("zone-1",),
        created_at=100.0,
        updated_at=100.0,
        version="v1",
    )
    base.update(overrides)
    return PriorInfoRecord(**base)


def test_record_tracks_source_scope_version_and_availability():
    r = record()

    assert r.source == "facility_db"
    assert r.scope == ("zone-1",)
    assert r.version == "v1"
    assert r.is_valid_at(now=200.0)  # 실제 관측과 별개로 사용 가능 여부만 판단


def test_unavailable_record_is_never_valid_regardless_of_window():
    r = record(available=False, valid_from=0.0, valid_until=1000.0)

    assert not r.is_valid_at(now=500.0)


def test_record_outside_valid_window_is_not_valid():
    r = record(valid_from=100.0, valid_until=200.0)

    assert not r.is_valid_at(now=50.0)
    assert r.is_valid_at(now=150.0)
    assert not r.is_valid_at(now=250.0)


def test_revise_links_new_version_to_previous_without_erasing_identity():
    store = PriorInfoStore()
    store.register(record(record_id="p-1", version="v1"))

    revised = store.revise("p-1", record(record_id="p-2", version="v2"))

    assert revised.revision_of == "p-1"
    # 이전 레코드는 지워지지 않고 그대로 조회 가능하다 (PROV-O wasRevisionOf).
    assert store.get("p-1") is not None
    assert store.get("p-2").version == "v2"


def test_report_conflict_accumulates_without_invalidating_the_record():
    store = PriorInfoStore()
    store.register(record())

    updated = store.report_conflict("p-1")

    assert updated.conflict_count == 1
    assert updated.is_valid_at(now=200.0)  # 충돌 기록만으로 자동 폐기하지 않는다


def test_repeated_conflicts_mark_record_as_needing_reevaluation():
    store = PriorInfoStore()
    store.register(record())

    for _ in range(3):
        store.report_conflict("p-1")

    candidates = store.reevaluation_candidates(now=200.0, conflict_threshold=3)

    assert [r.record_id for r in candidates] == ["p-1"]


def test_stale_record_is_flagged_for_reevaluation_by_age_alone():
    store = PriorInfoStore()
    store.register(record(updated_at=0.0))

    candidates = store.reevaluation_candidates(now=1000.0, max_age=500.0)

    assert [r.record_id for r in candidates] == ["p-1"]


def test_usable_filters_by_scope():
    store = PriorInfoStore()
    store.register(record(record_id="p-zone1", scope=("zone-1",)))
    store.register(record(record_id="p-zone2", scope=("zone-2",)))

    zone1_only = store.usable(now=200.0, scope="zone-1")

    assert [r.record_id for r in zone1_only] == ["p-zone1"]
