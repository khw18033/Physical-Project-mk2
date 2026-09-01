"""Versioned full/delta configuration apply (AI-N-02).

implements: AI-N-01, AI-N-02

The first apply (no baseline yet) always needs the full configuration;
afterward only changed items need to be delivered. A failed validation
must leave the existing good configuration untouched, and the on-device
safety feature (AI-N-01) must be able to keep working with zero
external configuration at all (AI-N-02: "갱신 실패나 검증 실패 시 기존
정상 구성을 유지하고, 외부 구성이 없어도 로컬 안전 기능은 계속 동작해야
한다").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ConfigUpdate:
    version: int
    full: bool
    items: dict


class ConfigApplier:
    def __init__(self, *, validate_fn: Callable[[dict], bool] | None = None) -> None:
        self._validate_fn = validate_fn or (lambda config: True)
        self._active_config: dict = {}
        self._active_version: int | None = None

    @property
    def active_config(self) -> dict:
        return dict(self._active_config)

    @property
    def active_version(self) -> int | None:
        return self._active_version

    def apply(self, update: ConfigUpdate) -> bool:
        if self._active_version is None and not update.full:
            return False  # no baseline yet -- a delta alone is meaningless

        candidate = dict(update.items) if update.full else {**self._active_config, **update.items}

        if not self._validate_fn(candidate):
            return False  # existing good configuration is left untouched

        self._active_config = candidate
        self._active_version = update.version
        return True
