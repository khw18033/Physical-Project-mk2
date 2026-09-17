"""Thin pytest wrapper around every `simulator/scenarios/*.json` file.

implements: AI-B-01, AI-B-04, AI-B-06, AI-B-07, AI-B-09, AI-C-04, AI-C-05,
AI-C-10, AI-C-11, AI-C-13, AI-C-15

Each scenario file is simultaneously the input `simulator/simulation.py`
narrates for a human and the fixture this test asserts against — one
scenario, two consumers (시나리오=자동검증 겸용). See `simulator/README.md`
for the scenario JSON schema and how to add a new one.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SIMULATOR_DIR = Path(__file__).resolve().parents[1] / "simulator"
if str(SIMULATOR_DIR) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_DIR))

from runner import load_scenario, run  # noqa: E402

SCENARIO_FILES = sorted((SIMULATOR_DIR / "scenarios").glob("*.json"))


@pytest.mark.parametrize("scenario_path", SCENARIO_FILES, ids=[p.stem for p in SCENARIO_FILES])
def test_scenario(scenario_path: Path):
    scenario = load_scenario(scenario_path)
    result = run(scenario)
    assert result.passed, "\n" + "\n".join(result.check_failures)
