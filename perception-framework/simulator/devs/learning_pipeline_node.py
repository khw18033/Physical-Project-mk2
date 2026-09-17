"""DEVS atomic model wrapping the real continual-learning candidate/lineage
machinery (AI-L-01~08) — synchronous reactive, same posture as
`registry_node.py`: judging a candidate and advancing a lineage stage are
pure computation, not something with its own simulated delay in this
framework (the actual training/validation *work* behind a stage transition
is out of scope for a DEVS timing model, same as `execution/lifecycle.py`
already treats it: a stage transition is a recorded decision, not a
simulated compute job).

implements: AI-L-01, AI-L-02, AI-L-03, AI-L-04, AI-L-05, AI-L-06, AI-L-07,
AI-L-08

Calls the real `continual.h2st.HierarchicalTwoSampleDetector` (candidate
judgment) and `continual.lineage.LearningLineage` (candidate -> quarantined
-> reviewed -> strategy_selected -> validated -> approval_pending ->
approved -> deployed -> verified, or rollback from deployed/verified)
directly, never reimplementing their decision logic.
"""

from __future__ import annotations

from pyjevsim.behavior_model import BehaviorModel
from pyjevsim.definition import Infinite

from perception_framework.continual.h2st import HierarchicalTwoSampleDetector
from perception_framework.continual.lineage import LearningLineage


class LearningPipelineNode(BehaviorModel):
    def __init__(self, name: str, *, alpha: float = 0.05) -> None:
        super().__init__(name)
        self.insert_input_port("control")
        self.insert_output_port("state")
        self.init_state("IDLE")
        self.insert_state("IDLE", Infinite)

        self.detector = HierarchicalTwoSampleDetector(alpha=alpha)
        self.lineages: dict[str, LearningLineage] = {}

        self.trace: list[dict] = []
        self.last_resolutions: dict = {}  # unused here; runner.py reads it unconditionally
        self.last_states: dict = {"last_decision_in_distribution": None, "lineage_states": {}}

    def ext_trans(self, port, msg) -> None:
        for op in msg.retrieve():
            self._apply(op)
            self.trace.append({"direction": "in", "port": port, "payload": op})

    def output(self, md) -> None:
        return

    def int_trans(self) -> None:
        return

    def _set_lineage_state(self, lineage_id: str, state) -> None:
        # `runner.py` snapshots a checkpoint via `dict(node.last_states)` --
        # a *shallow* copy, so mutating the nested `lineage_states` dict in
        # place would silently corrupt every earlier checkpoint's snapshot
        # too (they all still point at the same dict object). Replacing the
        # whole dict on every change keeps each checkpoint's shallow copy
        # genuinely independent.
        self.last_states["lineage_states"] = {**self.last_states["lineage_states"], lineage_id: state}

    def _apply(self, op: dict) -> None:
        kind = op["op"]
        if kind == "add_reference_task":
            self.detector.add_task(op["task_id"], op["reference_features"])
        elif kind == "candidate_check":
            decision = self.detector.decide(op["target_features"])
            self.last_states["last_decision_in_distribution"] = decision.in_distribution
            if not decision.in_distribution:
                lineage_id = op["lineage_id"]
                self.lineages[lineage_id] = LearningLineage(
                    lineage_id, actor=op.get("actor", "sim"),
                    evidence_ref=op.get("evidence_ref", "sim-evidence"),
                    reason=op.get("reason", "ood_candidate_detected"),
                )
                self._set_lineage_state(lineage_id, self.lineages[lineage_id].state)
        elif kind == "lineage_advance":
            lineage = self.lineages[op["lineage_id"]]
            lineage.advance(actor=op["actor"], evidence_ref=op["evidence_ref"], reason=op["reason"])
            self._set_lineage_state(op["lineage_id"], lineage.state)
        elif kind == "lineage_rollback":
            lineage = self.lineages[op["lineage_id"]]
            lineage.rollback(actor=op["actor"], evidence_ref=op["evidence_ref"], reason=op["reason"])
            self._set_lineage_state(op["lineage_id"], lineage.state)
        else:
            raise ValueError(f"unknown control op: {kind!r}")
