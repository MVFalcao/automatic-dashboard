"""In-process provider connection registry for the local setup API."""

from __future__ import annotations

from automation.agent.models import ProviderConnection, ProviderName, ProviderSetupInstructions
from automation.agent.routing import setup_instructions


class ProviderRegistry:
    def __init__(self) -> None:
        self._connections: dict[ProviderName, ProviderConnection] = {}

    def connect(self, connection: ProviderConnection) -> ProviderConnection:
        self._connections[connection.provider] = connection
        return connection

    def get(self, provider: ProviderName) -> ProviderConnection | None:
        return self._connections.get(provider)

    def remove(self, provider: ProviderName) -> None:
        self._connections.pop(provider, None)

    def list(self) -> list[ProviderConnection]:
        return list(self._connections.values())

    @staticmethod
    def setup(provider: ProviderName) -> ProviderSetupInstructions:
        return setup_instructions(provider)

