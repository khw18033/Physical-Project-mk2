"""Collecting experiment data from live heterogeneous perception execution.

implements: AI-S-06, AI-O-01, AI-O-03, AI-C-08, AI-C-11, AI-C-14

This runs the real thing and writes down what happened. Frames come from a
media source, every registered perception worker runs on the same frame, and
each result is turned into evidence at the moment it actually finishes. The
completion times are therefore measured on the node doing the work rather than
assumed, which is the whole reason for collecting here instead of replaying a
stored profile.

What the session guarantees:

* Workers run concurrently and results are consumed **in completion order**,
  so a slow worker delays only its own evidence.
* A worker that fails or is unavailable produces no evidence and does not stop
  the frame, the other workers, or the session (AI-C-11).
* Frames are pulled through a MediaSourceProvider and pixels are never written
  into the run bundle — only regions, labels and references (AI-C-08, AI-C-14).
* Every run records the conditions it ran under, so a bundle can be compared
  against another run or replayed offline (AI-O-03).
"""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Protocol

from perception_framework.collection.sampler import ResourceSampler
from perception_framework.observability.experiment import ExperimentRecorder, RunHeader
from perception_framework.perception.object_record import (
    Evidence, ProgressiveRecordBuilder,
)


@dataclass(frozen=True)
class WorkerResult:
    """One worker's output for one frame, with the time it became available."""

    worker_id: str
    source_group: str
    started_at: float
    completed_at: float
    items: list[dict]          # {"kind", "confidence", "region"/"label"}
    error: str | None = None

    @property
    def latency_ms(self) -> float:
        return (self.completed_at - self.started_at) * 1000.0


class PerceptionWorker(Protocol):
    """One heterogeneous perception capability.

    Deliberately thin: whatever the concrete model, runtime or accelerator is,
    it lives behind `run` and is registered rather than imported here.
    """

    worker_id: str
    source_group: str

    def run(self, frame: Any) -> list[dict]: ...
    def is_available(self) -> bool: ...


@dataclass
class CollectionSession:
    """Drives one data-collection run over a media source."""

    recorder: ExperimentRecorder
    workers: list[PerceptionWorker] = field(default_factory=list)
    builder: ProgressiveRecordBuilder = field(default_factory=ProgressiveRecordBuilder)
    sampler: ResourceSampler | None = None
    #: Populated by whoever tracks capability availability (registry, link
    #: posture). Evidence from a source outside this set is not consumed.
    available_groups: set[str] | None = None
    max_workers: int = 8

    frames_seen: int = 0
    evidence_seen: int = 0

    def add_worker(self, worker: PerceptionWorker) -> None:
        self.workers.append(worker)

    # -- availability ----------------------------------------------------

    def set_available_groups(self, groups: set[str] | None, reason: str = "") -> None:
        """Record an availability change as its own individual entry.

        Availability transitions are what make a collected run usable as an
        experiment condition later, so they are captured with a reason rather
        than inferred from missing evidence.
        """
        previous = self.available_groups
        self.available_groups = groups
        self.recorder.capture(
            "capability",
            available_groups_before=sorted(previous) if previous is not None else None,
            available_groups_after=sorted(groups) if groups is not None else None,
            state_change_reason=reason)

    # -- run -------------------------------------------------------------

    def run(self, media, max_frames: int | None = None) -> ExperimentRecorder:
        if self.sampler is not None:
            self.sampler.start()
        try:
            while max_frames is None or self.frames_seen < max_frames:
                if not media.is_available():
                    self.recorder.capture("fault", error_code="media_unavailable",
                                          source_id=media.source_id())
                    break
                frame = media.read_frame()
                if frame is None:
                    break
                self.process_frame(frame, media.source_id())
        finally:
            if self.sampler is not None:
                self.sampler.stop()
                for sample in self.sampler.samples:
                    self.recorder.capture_resource(**sample.as_payload())
        return self.recorder

    def process_frame(self, frame: Any, source_id: str) -> list[WorkerResult]:
        frame_ref = f"{source_id}#{self.frames_seen}"
        self.frames_seen += 1
        origin = time.perf_counter()
        results: list[WorkerResult] = []

        seen_objects: set[str] = set()
        runnable = [w for w in self.workers if self._usable(w)]
        if not runnable:
            self.recorder.capture("fault", error_code="no_worker_available",
                                  frame_ref=frame_ref)
            return results

        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(runnable))) as pool:
            futures = {pool.submit(self._invoke, w, frame, origin): w for w in runnable}
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                if result.error:
                    # One worker failing is a recorded event, not a frame failure.
                    self.recorder.capture("fault", error_code="worker_failed",
                                          worker_id=result.worker_id,
                                          frame_ref=frame_ref, error_detail=result.error)
                    continue
                seen_objects |= self._absorb(result, frame_ref, origin)

        # Objects not touched by this frame age toward stale/expired.
        self.builder.close_observation(seen_objects)
        return results

    def _usable(self, worker: PerceptionWorker) -> bool:
        if self.available_groups is not None and worker.source_group not in self.available_groups:
            return False
        try:
            return worker.is_available()
        except Exception:
            return False

    def _invoke(self, worker: PerceptionWorker, frame: Any, origin: float) -> WorkerResult:
        started = time.perf_counter()
        try:
            items = list(worker.run(frame))
            error = None
        except Exception as exc:
            items, error = [], f"{type(exc).__name__}: {exc}"
        return WorkerResult(worker.worker_id, worker.source_group,
                            started - origin, time.perf_counter() - origin,
                            items, error)

    def _absorb(self, result: WorkerResult, frame_ref: str, origin: float) -> set[str]:
        self.recorder.capture("worker", worker_id=result.worker_id,
                              source_group=result.source_group,
                              frame_ref=frame_ref, latency_ms=result.latency_ms,
                              item_count=len(result.items))
        touched: set[str] = set()
        for index, item in enumerate(result.items):
            evidence = Evidence(
                evidence_id=f"{frame_ref}:{result.worker_id}:{index}",
                frame_ref=frame_ref,
                source_group=result.source_group,
                observed_at=origin,
                available_at=result.completed_at,
                kind=item.get("kind", "region"),
                confidence=float(item.get("confidence", 0.0)),
                region=tuple(item["region"]) if item.get("region") else None,
                label=item.get("label"),
            )
            self.evidence_seen += 1
            self.recorder.capture_evidence(evidence)
            object_id = item.get("object_id") or f"{frame_ref}:{index}"
            touched.add(object_id)
            revision = self.builder.ingest(object_id, evidence, self.available_groups)
            if revision is not None:
                self.recorder.capture_record(revision)
        return touched


def new_session(domain_id: str, *, profile_id: str | None = None,
                node_id: str | None = None, versions: dict | None = None,
                sample_interval: float = 1.0) -> CollectionSession:
    """Convenience constructor wiring a recorder and a sampler together."""
    header = RunHeader(run_id=f"{domain_id}-{uuid.uuid4().hex[:8]}",
                       domain_id=domain_id, profile_id=profile_id,
                       node_id=node_id, versions=versions or {})
    return CollectionSession(recorder=ExperimentRecorder(header),
                             sampler=ResourceSampler(interval=sample_interval))
