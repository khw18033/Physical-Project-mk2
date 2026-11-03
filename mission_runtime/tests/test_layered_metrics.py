"""implements: AI-O-05
tests: not-measured != 0, three-valued target evaluation, accelerator-axis
       placement, idle accelerators kept in the list, unit mismatch rejected,
       L1/L2 separation, vendor neutrality
"""

from __future__ import annotations

import pytest

from mission_runtime.observability.layered_metrics import (
    AcceleratorInstance,
    BoardResources,
    Direction,
    Indicator,
    LayeredResourceView,
    Measurement,
    MeetState,
    ServiceRuntime,
    TargetBaseline,
    UnitMismatch,
)


def _view() -> LayeredResourceView:
    """가속기 4개 중 2개에만 서비스가 배치된 구성 — 유휴가 드러나야 한다."""
    return LayeredResourceView(
        accelerators=(
            AcceleratorInstance("acc-cpu", "cpu", attachment="builtin",
                                utilization=Measurement(0.42, "ratio"),
                                temperature=Measurement(51.0, "celsius")),
            AcceleratorInstance("acc-igpu", "integrated_gpu", attachment="builtin",
                                utilization=Measurement(0.10, "ratio")),
            AcceleratorInstance("acc-npu-1", "npu", attachment="external",
                                vendor_label="제품-A",
                                utilization=Measurement(0.88, "ratio"),
                                temperature=Measurement(72.0, "celsius")),
            AcceleratorInstance("acc-npu-2", "npu", attachment="external",
                                vendor_label="제품-B"),
        ),
        services=(
            ServiceRuntime(
                "svc-control", "acc-cpu", role="오케스트레이션",
                model_name="m-a", model_version="1.3.0",
                indicators=(
                    Indicator("throughput", Measurement(24.0, "hz"),
                              service_id="svc-control", accelerator_id="acc-cpu",
                              target=TargetBaseline(20.0, Direction.AT_LEAST, "hz"),
                              trend=(Measurement(21.0, "hz"), Measurement(24.0, "hz"))),
                ),
            ),
            ServiceRuntime(
                "svc-vision", "acc-npu-1", role="장면 해석",
                indicators=(
                    Indicator("latency", Measurement(180.0, "ms"),
                              service_id="svc-vision", accelerator_id="acc-npu-1",
                              target=TargetBaseline(120.0, Direction.AT_MOST, "ms")),
                    Indicator("throughput", Measurement.not_measured("hz"),
                              service_id="svc-vision", accelerator_id="acc-npu-1",
                              target=TargetBaseline(10.0, Direction.AT_LEAST, "hz")),
                ),
            ),
        ),
        board=BoardResources(
            memory_utilization=Measurement(0.63, "ratio"),
            power=Measurement(18.4, "watt"),
            power_trend=(Measurement(17.9, "watt"), Measurement(18.4, "watt")),
        ),
    )


# -- 측정 없음 ≠ 0 -----------------------------------------------------------


def test_absent_measurement_is_none_not_zero():
    m = Measurement.not_measured("hz")
    assert m.value is None
    assert m.measured is False
    assert m.value != 0


def test_unmeasured_indicator_is_not_measured_not_unmet():
    """문서 §4.5: 산출되지 않는 구간은 "미달"이 아니라 측정 없음."""
    view = _view()
    idle_throughput = view.services[1].indicator("throughput")
    assert idle_throughput.meet_state is MeetState.NOT_MEASURED
    assert idle_throughput not in view.unmet_indicators()
    assert idle_throughput in view.not_measured_indicators()


def test_meet_state_has_exactly_three_values():
    assert {s.value for s in MeetState} == {"MET", "UNMET", "NOT_MEASURED"}


def test_unmeasured_accelerators_are_reported_so_they_are_not_drawn_as_zero():
    assert _view().unmeasured_accelerators() == ("acc-npu-2",)


def test_measured_trend_drops_gaps_instead_of_filling_them_with_zero():
    ind = Indicator(
        "throughput", Measurement(10.0, "hz"),
        trend=(Measurement(9.0, "hz"), Measurement.not_measured("hz"),
               Measurement(11.0, "hz")),
    )
    assert [s.value for s in ind.measured_trend()] == [9.0, 11.0]


# -- 목표 기준선 -------------------------------------------------------------


def test_at_least_target_is_met_and_unmet_correctly():
    target = TargetBaseline(20.0, Direction.AT_LEAST, "hz")
    assert target.evaluate(Measurement(24.0, "hz")) is MeetState.MET
    assert target.evaluate(Measurement(20.0, "hz")) is MeetState.MET
    assert target.evaluate(Measurement(19.9, "hz")) is MeetState.UNMET


def test_at_most_target_handles_latency_style_goals():
    target = TargetBaseline(120.0, Direction.AT_MOST, "ms")
    assert target.evaluate(Measurement(100.0, "ms")) is MeetState.MET
    assert target.evaluate(Measurement(180.0, "ms")) is MeetState.UNMET


def test_unit_mismatch_between_target_and_measurement_is_rejected():
    """문서 §4.5: 임의 위치에 고정된 기준선은 허용되지 않는다 — 단위가 다르면
    위치를 정할 수 없으므로 조립 시점에 막는다."""
    with pytest.raises(UnitMismatch):
        Indicator("latency", Measurement(100.0, "ms"),
                  target=TargetBaseline(10.0, Direction.AT_LEAST, "hz"))
    with pytest.raises(UnitMismatch):
        TargetBaseline(10.0, Direction.AT_LEAST, "hz").evaluate(Measurement(5.0, "ms"))


def test_trend_sample_unit_mismatch_is_rejected():
    with pytest.raises(UnitMismatch, match="trend sample"):
        Indicator("latency", Measurement(100.0, "ms"),
                  trend=(Measurement(0.1, "s"),))


def test_series_range_includes_the_baseline_so_it_cannot_be_drawn_off_screen():
    ind = Indicator(
        "throughput", Measurement(24.0, "hz"),
        target=TargetBaseline(40.0, Direction.AT_LEAST, "hz"),
        trend=(Measurement(21.0, "hz"), Measurement(24.0, "hz")),
    )
    assert ind.series_range() == (21.0, 40.0)


def test_series_range_is_none_when_nothing_was_measured():
    ind = Indicator("throughput", Measurement.not_measured("hz"),
                    target=TargetBaseline(10.0, Direction.AT_LEAST, "hz"))
    assert ind.series_range() is None


def test_unmet_indicator_is_listed():
    assert [i.name for i in _view().unmet_indicators()] == ["latency"]


# -- 가속기 축 ---------------------------------------------------------------


def test_placement_is_keyed_by_accelerator_not_by_service():
    """문서 §4.1: 가속기를 기준 축으로 삼아야 유휴와 편중이 드러난다."""
    placement = _view().placement()
    assert placement == {
        "acc-cpu": ("svc-control",),
        "acc-igpu": (),
        "acc-npu-1": ("svc-vision",),
        "acc-npu-2": (),
    }


def test_idle_accelerators_stay_in_the_list():
    """문서 §4.1·§4.4: 미할당·유휴 가속기도 생략하지 않는다."""
    view = _view()
    assert [a.instance_id for a in view.idle_accelerators()] == ["acc-igpu", "acc-npu-2"]
    assert len(view.accelerators) == 4      # 목록의 완전성


def test_same_kind_accelerators_are_distinguished_as_instances():
    """태그(무엇을 할 수 있는가)만으로는 npu 두 개를 가를 수 없다."""
    view = _view()
    npus = [a for a in view.accelerators if a.kind == "npu"]
    assert [a.instance_id for a in npus] == ["acc-npu-1", "acc-npu-2"]
    assert npus[0].utilization.measured and not npus[1].utilization.measured


def test_duplicate_accelerator_ids_are_rejected():
    with pytest.raises(ValueError, match="duplicate accelerator ids"):
        LayeredResourceView(accelerators=(
            AcceleratorInstance("a", "cpu"), AcceleratorInstance("a", "npu"),
        ))


def test_service_on_unknown_accelerator_is_rejected():
    with pytest.raises(ValueError, match="unknown accelerator"):
        LayeredResourceView(
            accelerators=(AcceleratorInstance("a", "cpu"),),
            services=(ServiceRuntime("s", "ghost"),),
        )


def test_utilization_range_is_validated():
    with pytest.raises(ValueError, match="utilization out of range"):
        AcceleratorInstance("a", "cpu", utilization=Measurement(1.4, "ratio"))


# -- 계층 분리 ---------------------------------------------------------------


def test_layer1_and_layer2_are_separate_collections():
    """문서 §4.4: 두 계층을 명시적으로 구분해 표시한다 — 한 목록에 섞지 않는다."""
    view = _view()
    assert all(isinstance(a, AcceleratorInstance) for a in view.accelerators)
    assert all(isinstance(s, ServiceRuntime) for s in view.services)


def test_service_always_carries_its_accelerator_or_declares_none():
    view = _view()
    assert view.services[0].accelerator_id == "acc-cpu"
    unplaced = ServiceRuntime("svc-new", None)
    assert unplaced.accelerator_id is None      # 미배치가 정보다


def test_indicator_cannot_claim_a_different_accelerator_than_its_service():
    """지표가 다른 가속기를 주장하면 '모델 문제인가 가속기 문제인가'를 좁힐 수 없다."""
    with pytest.raises(ValueError, match="claims accelerator"):
        ServiceRuntime("s", "acc-a", indicators=(
            Indicator("x", Measurement(1.0, "hz"), accelerator_id="acc-b"),
        ))


def test_board_level_resources_are_separate_from_per_accelerator_ones():
    board = _view().board
    assert board.memory_utilization.value == 0.63
    assert board.power.unit == "watt"
    assert len(board.power_trend) == 2


# -- 구성 가변성 -------------------------------------------------------------


def test_adding_an_accelerator_needs_no_structural_change():
    """문서 §3·§5: 가속기가 추가·교체되어도 화면 구조 변경 없이 반영."""
    view = _view().with_accelerator(AcceleratorInstance("acc-npu-3", "npu"))
    assert len(view.accelerators) == 5
    assert "acc-npu-3" in view.placement()
    assert view.placement()["acc-npu-3"] == ()


def test_replacing_an_accelerator_keeps_the_identifier():
    view = _view().with_accelerator(
        AcceleratorInstance("acc-npu-2", "npu", utilization=Measurement(0.5, "ratio"))
    )
    assert len(view.accelerators) == 4
    assert view.unmeasured_accelerators() == ()


def test_snapshots_are_not_mutated_in_place():
    view = _view()
    grown = view.with_service(ServiceRuntime("svc-x", "acc-igpu"))
    assert len(view.services) == 2
    assert len(grown.services) == 3


# -- 벤더 중립 ---------------------------------------------------------------


def test_vendor_label_is_display_only_and_no_logic_branches_on_it():
    import io
    import tokenize
    from pathlib import Path

    import mission_runtime.observability.layered_metrics as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    banned = ("mobilint", "deepx", "xdna", "nvidia", "cuda", "coral", "hailo",
              "모빌린트", "딥엑스", "vla", "vlm")
    leaked: list[tuple[str, int]] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE):
            continue
        low = token.string.lower()
        leaked += [(n, token.start[0]) for n in banned if n in low]
    assert not leaked, f"vendor name leaked into code: {leaked}"


def test_kind_and_attachment_are_free_strings_with_no_enum():
    """새 가속기 종류가 와도 코드를 고치지 않는다."""
    exotic = AcceleratorInstance("acc-x", "some_future_accelerator",
                                 attachment="over_network")
    view = LayeredResourceView(accelerators=(exotic,))
    assert view.placement() == {"acc-x": ()}
