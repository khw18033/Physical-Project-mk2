"""tests for: AI-C-03
covers: frame reference, local ordering under clock failure, cross-node fusion gate
"""

from ai_framework.common.timing import (
    DerivedResult,
    FrameReferenceFactory,
    TimeSyncState,
    in_local_order,
)


class FakeClock:
    """Wall clock we can freeze or run backwards, as a sync outage would."""

    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now


def test_reference_carries_source_frame_and_monotonic_sequence():
    factory = FrameReferenceFactory("cam-1", clock=FakeClock())

    first = factory.next_reference("f1")
    second = factory.next_reference("f2")

    assert first.source_id == "cam-1"
    assert first.frame_id == "f1"
    assert second.local_sequence > first.local_sequence


def test_local_order_survives_a_backwards_clock_jump():
    clock = FakeClock()
    factory = FrameReferenceFactory("cam-1", clock=clock)

    a = factory.next_reference("f1")
    clock.now -= 50  # NTP correction jumps the wall clock backwards
    b = factory.next_reference("f2")

    results = [DerivedResult(b, "second"), DerivedResult(a, "first")]
    ordered = in_local_order(results)

    # 단일 노드의 로컬 처리와 순서는 유지되어야 한다 (AI-C-03) — even though
    # b.observed_at < a.observed_at.
    assert b.observed_at < a.observed_at
    assert [r.payload for r in ordered] == ["first", "second"]


def test_cross_node_fusion_is_gated_on_sync_state_only():
    factory = FrameReferenceFactory("cam-1", clock=FakeClock())
    synced = factory.next_reference("f1")

    factory.set_sync_state(TimeSyncState.DEGRADED)
    degraded = factory.next_reference("f2")

    assert synced.supports_cross_node_fusion()
    # 노드 간 정합 기능만 정확도 저하 상태로 처리하고, 프레임 생성 자체는 계속된다.
    assert not degraded.supports_cross_node_fusion()
    assert degraded.local_sequence > synced.local_sequence
