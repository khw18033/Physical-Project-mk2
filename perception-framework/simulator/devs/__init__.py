"""DEVS atomic model implementations used by `simulator/runner.py`.

implements: AI-B-01, AI-B-04, AI-B-06, AI-B-07, AI-C-05, AI-C-10, AI-C-11,
AI-C-13, AI-C-15, AI-C-20

Built on `pyjevsim` (https://github.com/eventsim/pyjevsim) — a simulator-
only dependency (`pyproject.toml`'s `sim` extra). `perception_framework`
itself never imports this package or pyjevsim (원칙 #1/#3, AI-C-04):
these are test/demo tooling, not core AI logic.
"""
