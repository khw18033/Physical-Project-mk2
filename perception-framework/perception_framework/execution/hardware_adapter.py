"""Connect the command lifecycle supervisor to a replaceable hardware provider."""

from __future__ import annotations

from perception_framework.contracts.physical_command import Command


class HardwareAdapterHandler:
    def __init__(self, provider) -> None:
        self.provider = provider

    def __call__(self, command: Command) -> tuple[bool, dict | None, str | None]:
        supported = {capability.name for capability in self.provider.capabilities()}
        if command.action not in supported:
            return False, None, f"unsupported_action:{command.action}"
        return self.provider.execute(command)

    def cancel(self, command_id: str) -> bool:
        return bool(self.provider.cancel(command_id))
