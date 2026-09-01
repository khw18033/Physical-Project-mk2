"""Deterministic continual-learning control primitives.

These components implement *functional validation* of AI-L-01~08.  They do not
train or fine-tune a model, reproduce paper accuracy, or invoke a vendor SDK.
"""

from .dgs import DynamicTaskGrouper, TaskGroup
from .ekya import MicroProfile, ResourceAllocator, ResourceJob
from .h2st import H2STDecision, HierarchicalTwoSampleDetector
from .lineage import LearningLineage, LearningState, LineageEvent
from .replay import Box, PseudoLabel, ReplayCandidate, ReplaySelector

__all__ = [
    "Box",
    "DynamicTaskGrouper",
    "H2STDecision",
    "HierarchicalTwoSampleDetector",
    "LearningLineage",
    "LearningState",
    "LineageEvent",
    "MicroProfile",
    "PseudoLabel",
    "ReplayCandidate",
    "ReplaySelector",
    "ResourceAllocator",
    "ResourceJob",
    "TaskGroup",
]
