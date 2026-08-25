"""tests for: AI-R-01"""

from ai_framework.risk.fsm import RiskAnalysisFsm, RiskAnalysisState, RiskEvent


def test_no_registered_event_kinds_stays_inactive_and_ignores_events():
    fsm = RiskAnalysisFsm(registered_event_kinds=set())

    fsm.process(RiskEvent("water_level", severity=0.99))

    assert fsm.state == RiskAnalysisState.INACTIVE


def test_low_severity_stays_normal():
    fsm = RiskAnalysisFsm({"water_level"})

    fsm.process(RiskEvent("water_level", severity=0.1))

    assert fsm.state == RiskAnalysisState.NORMAL


def test_mid_severity_moves_to_observing():
    fsm = RiskAnalysisFsm({"water_level"})

    fsm.process(RiskEvent("water_level", severity=0.5))

    assert fsm.state == RiskAnalysisState.OBSERVING


def test_high_severity_moves_to_alert():
    fsm = RiskAnalysisFsm({"water_level"})

    fsm.process(RiskEvent("water_level", severity=0.9))

    assert fsm.state == RiskAnalysisState.ALERT


def test_alert_recovers_through_recovery_state_back_to_normal():
    fsm = RiskAnalysisFsm({"water_level"})
    fsm.process(RiskEvent("water_level", severity=0.9))
    assert fsm.state == RiskAnalysisState.ALERT

    fsm.process(RiskEvent("water_level", severity=0.1))
    assert fsm.state == RiskAnalysisState.RECOVERY

    fsm.process(RiskEvent("water_level", severity=0.1))
    assert fsm.state == RiskAnalysisState.NORMAL


def test_unregistered_event_kind_is_ignored_not_an_error():
    fsm = RiskAnalysisFsm({"water_level"})

    fsm.process(RiskEvent("unregistered_sensor", severity=0.99))

    assert fsm.state == RiskAnalysisState.NORMAL
