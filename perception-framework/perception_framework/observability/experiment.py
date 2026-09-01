"""Experiment capture: turning a demonstration run into analysable data.

implements: AI-O-01, AI-O-02, AI-O-03, AI-C-05, AI-C-14

A field demonstration is the only place some conditions occur — a real link
drop, real thermal pressure, a real node leaving. Those runs are worth
measuring, so this module records what a run did in a form that can be
replayed and compared offline.

Boundaries this respects:

* Capture is an **optional** capability. Every entry point swallows its own
  failures, because a recorder problem must never stop the function being
  recorded (AI-C-05, AI-O-01: "외부 관측 기능 장애가 실제 기능 실행을 중단시키지
  않아야 한다").
* Records live on the observation plane, never mixed into business messages,
  and no media pixels are captured — only references to them (AI-C-14, AI-C-08).
* Device liveness and fatal errors stay individual entries and are never
  folded into the numeric summary (AI-O-01).
* A run bundle carries the configuration and version it ran under so the run
  can be reproduced later (AI-O-03).

The module is domain-agnostic: a river, facility or reconnaissance demo differ
only by the profile recorded in the bundle header, never by a branch here.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RunHeader:
    """Identifies the conditions a run happened under."""

    run_id: str
    domain_id: str
    profile_id: str | None = None
    node_id: str | None = None
    started_at: float = field(default_factory=time.time)
    versions: dict[str, str] = field(default_factory=dict)
    notes: str = ""


@dataclass(frozen=True)
class Entry:
    """One captured item. `channel` separates what must not be aggregated."""

    at: float
    channel: str          # "evidence" | "record" | "capability" | "resource"
                          # | "network" | "reconfiguration" | "liveness"
                          # | "fault" | "note"
    payload: dict[str, Any]


#: Channels whose entries carry individual meaning and are therefore excluded
#: from any numeric summarisation (AI-O-01, AI-O-02).
NON_AGGREGATABLE = frozenset({"liveness", "fault", "capability", "reconfiguration"})


class ExperimentRecorder:
    """Collects a run in memory and writes it out as a replayable bundle.

    Usage is deliberately trivial so that instrumenting a demo path costs one
    line and cannot introduce a new failure mode:

        recorder.capture("capability", kind="perception.segment",
                         state="DISABLED", reason="thermal")
    """

    def __init__(self, header: RunHeader, *, limit: int = 500_000) -> None:
        self.header = header
        self.entries: list[Entry] = []
        self.limit = limit
        self.dropped = 0
        self.enabled = True

    # -- capture ---------------------------------------------------------

    def capture(self, channel: str, **payload: Any) -> None:
        if not self.enabled:
            return
        try:
            if len(self.entries) >= self.limit:
                self.dropped += 1
                return
            self.entries.append(Entry(time.time(), channel, payload))
        except Exception:
            # Capture is best-effort by contract; disable rather than raise
            # into the caller's control flow.
            self.enabled = False

    def capture_evidence(self, evidence: Any) -> None:
        """Record a provider result. Regions and labels only — no pixels."""
        try:
            data = asdict(evidence) if hasattr(evidence, "__dataclass_fields__") else dict(evidence)
        except Exception:
            self.enabled = False
            return
        data.pop("payload", None)
        self.capture("evidence", **{k: _plain(v) for k, v in data.items()})

    def capture_record(self, record: Any) -> None:
        try:
            data = asdict(record) if hasattr(record, "__dataclass_fields__") else dict(record)
        except Exception:
            self.enabled = False
            return
        self.capture("record", **{k: _plain(v) for k, v in data.items()})

    def capture_resource(self, **samples: float) -> None:
        """Latency, memory, cpu, power — whatever the node can actually read."""
        self.capture("resource", **samples)

    def capture_network(self, **samples: Any) -> None:
        """Link and transport state such as heartbeat, delay, queue depth."""
        self.capture("network", **samples)

    def capture_reconfiguration(self, **event: Any) -> None:
        """Provider/node selection changes that must stay individually visible."""
        self.capture("reconfiguration", **event)

    # -- read-out --------------------------------------------------------

    def summarize(self) -> dict[str, Any]:
        """Aggregate numeric channels; leave individual-meaning ones intact."""
        numeric: dict[str, list[float]] = {}
        for entry in self.entries:
            if entry.channel in NON_AGGREGATABLE:
                continue
            for key, value in entry.payload.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    numeric.setdefault(f"{entry.channel}.{key}", []).append(float(value))
        summary = {
            name: {
                "count": len(values),
                "avg": sum(values) / len(values),
                "min": min(values),
                "max": max(values),
                "p50": sorted(values)[len(values) // 2],
            }
            for name, values in numeric.items()
        }
        individual = [asdict(e) for e in self.entries if e.channel in NON_AGGREGATABLE]
        return {"summary": summary, "individual": individual,
                "dropped": self.dropped, "capture_enabled": self.enabled}

    def bundle(self) -> dict[str, Any]:
        return {
            "header": asdict(self.header),
            "entries": [asdict(e) for e in self.entries],
            "summary": self.summarize(),
        }

    def write(self, directory: str | Path) -> Path | None:
        """Persist the run. Returns None if persisting failed — by design."""
        try:
            target = Path(directory) / f"{self.header.run_id}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(self.bundle(), ensure_ascii=False,
                                         indent=2, default=str), encoding="utf-8")
            return target
        except Exception:
            self.enabled = False
            return None


class NullRecorder(ExperimentRecorder):
    """Used where capture is not part of the deployment profile."""

    def __init__(self) -> None:
        super().__init__(RunHeader(run_id="null", domain_id="none"))
        self.enabled = False


def replay(bundle_path: str | Path, channel: str) -> list[dict[str, Any]]:
    """Read one channel back out of a stored run, for offline comparison."""
    data = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
    return [e["payload"] for e in data["entries"] if e["channel"] == channel]


def _plain(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return str(value)
