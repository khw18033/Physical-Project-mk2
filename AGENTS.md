# Repository Guidelines

## Project Structure & Module Organization

The installable Python package lives in `perception-framework/perception_framework/`. Its modules follow framework responsibilities: `contracts/` defines shared types, `providers/` isolates infrastructure adapters, and `perception/`, `planning/`, `risk/`, and `runtime/` contain domain-neutral behavior. Module-level checks are consolidated under `perception-framework/tests/`; end-to-end framework-property cases are data-driven JSON scenarios in `perception-framework/simulator/scenarios/`, run by both `simulator/simulation.py` (human-readable) and `tests/test_scenarios.py` (pytest). Cross-component JSON Schemas and valid payloads belong in `contracts/ai/`. Use `docs/ai/` for architecture and requirement-status docs, and `docs/obsidian/` for the KCI extension research (baseline papers, ideas, implementation plan). Large datasets and model weights are intentionally excluded from Git.

## Build, Test, and Development Commands

Run Python commands from `perception-framework/`:

```bash
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install -e ".[dev]"          # editable development install
python3 -m pytest -q                       # full test suite
python3 -m pytest tests/test_selector.py -q # focused module tests
python3 -m pytest -q tests/test_scenarios.py # framework-property scenarios (simulator/scenarios/*.json)
PYTHONPATH=. python3 simulator/simulation.py # runnable scenario simulator
docker build -t perception-framework:0.1.0 .       # container build
```

If system pytest plugins conflict, set `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`. MQTT, Kafka, OpenTelemetry, K3s, and OpenCL are optional; tests requiring unavailable infrastructure should skip cleanly.

## Coding Style & Naming Conventions

Use four-space indentation, type hints, descriptive `snake_case` functions and variables, and `PascalCase` classes. No formatter or linter is currently configured, so match nearby Python style. Begin module and test docstrings with `implements: AI-X-NN`. Reuse names from `perception_framework/contracts/data_dictionary.py`; register new shared fields there first. Keep core logic domain- and vendor-neutral: concrete sensors, runtimes, transports, and orchestration belong behind provider/adapter interfaces. Update `docs/ai/requirement-traceability.md` when implementation status changes.

## Testing Guidelines

Pytest discovers `tests/test_*.py`, including `tests/test_scenarios.py` (parametrized over every `simulator/scenarios/*.json` file — see `simulator/README.md` to add one) and `tests/test_integration_functional_check.py` (one consolidated, named-check functional check for module-level behavior that a declarative scenario can't express). Add focused tests for normal, degraded, and unavailable-provider paths; optional capability loss must not disable unrelated behavior. Prefer deterministic fakes over required external services. Run the full suite before submitting changes.

## Experiment Approval Gate

Never start an experiment without explicit user approval for that run. Before requesting approval, print the exact dataset paths, execution environment and hardware, purpose and hypothesis, comparison arms, controlled variables, objective expected outcomes (including null or unfavorable outcomes), known limitations, estimated cost or duration, and raw artifact paths. Generate metrics with committed code from a frozen manifest; do not manually select samples or transcribe favorable results. A prior approval does not authorize a materially changed dataset, method, threshold, or environment—present the changed protocol and request approval again.

## Commit & Pull Request Guidelines

History uses concise imperative subjects, sometimes Conventional Commit scope (for example, `feat(ai): complete framework and cross-part contracts`). Keep each commit focused. Pull requests should explain behavior and requirement IDs, list verification commands, link relevant issues or design docs, and include screenshots only for visual changes. Call out skipped infrastructure or hardware validation.

## Security & Configuration

Never commit `.env` files, credentials, private keys, certificates, internal endpoints, or sensitive image/location data. Use placeholders and environment-injected secrets, then inspect staged changes before pushing.
