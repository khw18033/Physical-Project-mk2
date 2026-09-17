"""DEVS atomic model wrapping the real tracking/association/coverage/risk
family (AI-S-01/02/03/04, AI-R-01/02) — same posture as `registry_node.py`:
reacts synchronously to every "control" input (own deadline stays
`Infinite`), because these are all pure-computation reactions to an
already-arrived observation, not something with its own simulated delay.

implements: AI-S-01, AI-S-02, AI-S-03, AI-S-04, AI-R-01, AI-R-02

This node calls the *real* framework classes (`perception.tracking.
ByteTracker`, `perception.coverage.CoverageEstimator`, `risk.fsm.
RiskAnalysisFsm`, `risk.scoring.RuleBasedRiskScorer`) directly — it does not
reimplement any of their logic, the same rule `registry_node.py` follows for
`CapabilityRegistry`/`ZoneApplication`.
"""

from __future__ import annotations

from pyjevsim.behavior_model import BehaviorModel
from pyjevsim.definition import Infinite

from perception_framework.perception.coverage import CoverageEstimator, CoverageObservation, SourceStatus
from perception_framework.perception.tracking import ByteTracker, Detection
from perception_framework.risk.fsm import RiskAnalysisFsm, RiskEvent
from perception_framework.risk.scoring import RuleBasedRiskScorer


class PerceptionRiskNode(BehaviorModel):
    def __init__(
        self,
        name: str,
        *,
        risk_event_kinds: list[str] | None = None,
        risk_weights: dict[str, float] | None = None,
        observe_threshold: float = 0.3,
        alert_threshold: float = 0.7,
    ) -> None:
        super().__init__(name)
        self.insert_input_port("control")
        self.insert_output_port("state")
        self.init_state("IDLE")
        self.insert_state("IDLE", Infinite)

        self.tracker = ByteTracker()
        self.coverage = CoverageEstimator()
        self.risk_fsm = RiskAnalysisFsm(
            set(risk_event_kinds or ()), observe_threshold=observe_threshold, alert_threshold=alert_threshold,
        )
        self.risk_scorer = RuleBasedRiskScorer(risk_weights or {})

        self.trace: list[dict] = []
        self.last_resolutions: dict = {}  # unused here; runner.py reads it unconditionally
        self.last_states: dict = {
            "track_count": 0,
            "unconfirmed_labels": 0,
            "risk_state": self.risk_fsm.state,
            "last_risk_score": None,
            "blind_spot_count": 0,
        }

    def ext_trans(self, port, msg) -> None:
        for op in msg.retrieve():
            self._apply(op)
            self.trace.append({"direction": "in", "port": port, "payload": op})

    def output(self, md) -> None:
        return  # no independent simulated delay -- see class docstring

    def int_trans(self) -> None:
        return

    def _apply(self, op: dict) -> None:
        kind = op["op"]
        if kind == "detect_frame":
            detections = [Detection(tuple(d["box"]), d.get("label"), d.get("score", 1.0)) for d in op["detections"]]
            tracks = self.tracker.update(detections)
            self.last_states["track_count"] = len(tracks)
            self.last_states["unconfirmed_labels"] = sum(1 for t in tracks if t.label is None)
        elif kind == "coverage_observation":
            self.coverage.assign_source(op["region_id"], op["source_id"])
            observation = CoverageObservation(
                observation_id=op["observation_id"], source_id=op["source_id"], frame_ref=op.get("frame_ref", ""),
                observed_at=op["observed_at"], observed_fraction=op["observed_fraction"], confidence=op.get("confidence", 0.8),
            )
            self.coverage.ingest(op["region_id"], observation)
            statuses = {op["source_id"]: SourceStatus(op["source_id"], available=True, last_observed_at=op["observed_at"])}
            self.last_states["blind_spot_count"] = len(self.coverage.blind_spots(op["observed_at"], statuses))
        elif kind == "risk_event":
            self.risk_fsm.process(RiskEvent(op["kind"], op["severity"]))
            self.last_states["risk_state"] = self.risk_fsm.state
        elif kind == "risk_score":
            score = self.risk_scorer.score(op["inputs"])
            self.last_states["last_risk_score"] = score
        else:
            raise ValueError(f"unknown control op: {kind!r}")
