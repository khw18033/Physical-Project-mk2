"""Independent execution lifecycle + versioned config deploy/rollback
(AI-B-05).

implements: AI-B-05

A failed deploy/update of one *optional* component must never restart
or stop an already-running *core* component (AI-B-05: "선택 기능의
배치·갱신 실패가 핵심 기능을 종료시키거나 연쇄 재시작하게 해서는 안
된다"). A failed deploy falls back to the last known-good version
instead of leaving the component broken.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ComponentState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    STOPPED = "STOPPED"


@dataclass
class ComponentLifecycle:
    component_id: str
    is_core: bool
    active_version: str | None = None
    last_good_version: str | None = None
    state: ComponentState = ComponentState.PENDING


class LifecycleManager:
    def __init__(self) -> None:
        self._components: dict[str, ComponentLifecycle] = {}

    def register(self, component_id: str, *, is_core: bool) -> ComponentLifecycle:
        component = ComponentLifecycle(component_id, is_core)
        self._components[component_id] = component
        return component

    def deploy(self, component_id: str, version: str, *, health_check_passes: bool) -> ComponentLifecycle:
        component = self._components[component_id]
        if health_check_passes:
            component.active_version = version
            component.last_good_version = version
            component.state = ComponentState.RUNNING
        elif component.last_good_version is not None:
            # Roll back rather than leave the component broken.
            component.active_version = component.last_good_version
            component.state = ComponentState.RUNNING
        else:
            component.state = ComponentState.STOPPED if component.is_core else ComponentState.DEGRADED
        return component

    def state_of(self, component_id: str) -> ComponentState:
        return self._components[component_id].state

    def core_components_all_running(self) -> bool:
        return all(c.state == ComponentState.RUNNING for c in self._components.values() if c.is_core)
