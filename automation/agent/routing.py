"""Deterministic provider selection with explicit fallback consent."""

from __future__ import annotations

from dataclasses import dataclass

from automation.agent.models import (
    ProviderConnection,
    ProviderName,
    TaskRequest,
)


class ProviderRoutingError(RuntimeError):
    """Base class for routing failures."""


class NoProviderAvailableError(ProviderRoutingError):
    pass


class ProviderUnavailableError(ProviderRoutingError):
    """The requested provider is unavailable; another provider may be proposed."""

    fallback_requires_confirmation = True


@dataclass(frozen=True)
class ProviderSelection:
    provider: ProviderName
    model: str
    estimated_total_tokens: int
    reason: str
    actual_input_tokens: int = 0
    actual_output_tokens: int = 0


class ProviderRouter:
    """Choose the connected capable provider with the smallest token estimate.

    The sort key includes the enum value as a stable tie-breaker, making choices
    reproducible in tests and across local runs.  An explicit provider is never
    replaced automatically.
    """

    def __init__(self, connections: list[ProviderConnection] | None = None) -> None:
        self._connections: dict[ProviderName, ProviderConnection] = {}
        for connection in connections or []:
            self.add(connection)

    def add(self, connection: ProviderConnection) -> None:
        self._connections[connection.provider] = connection

    def remove(self, provider: ProviderName) -> None:
        self._connections.pop(provider, None)

    def connections(self) -> tuple[ProviderConnection, ...]:
        return tuple(self._connections.values())

    def route(self, request: TaskRequest) -> ProviderSelection:
        if request.requested_provider is not None:
            connection = self._connections.get(request.requested_provider)
            if connection is None or not connection.connected:
                raise ProviderUnavailableError(
                    f"Requested provider is not connected: {request.requested_provider}"
                )
            if not request.required_capabilities <= connection.capabilities:
                missing = sorted(set(request.required_capabilities) - connection.capabilities)
                raise ProviderUnavailableError(
                    f"Requested provider lacks capabilities: {', '.join(missing)}"
                )
            return self._selection(connection, request, explicit=True)

        candidates = [
            connection
            for connection in self._connections.values()
            if connection.connected and request.required_capabilities <= connection.capabilities
        ]
        if not candidates:
            raise NoProviderAvailableError("No connected provider supports this task")
        selected = min(
            candidates,
            key=lambda connection: (
                connection.token_estimate.total_tokens
                + request.estimated_input_tokens
                + request.estimated_output_tokens,
                connection.provider.value,
                connection.model,
            ),
        )
        return self._selection(selected, request, explicit=False)

    @staticmethod
    def _selection(
        connection: ProviderConnection, request: TaskRequest, *, explicit: bool
    ) -> ProviderSelection:
        total = (
            connection.token_estimate.total_tokens
            + request.estimated_input_tokens
            + request.estimated_output_tokens
        )
        reason = (
            "Explicit provider selection was honored"
            if explicit
            else "Selected the connected capable provider with the lowest estimated total input/output tokens"
        )
        return ProviderSelection(
            provider=connection.provider,
            model=connection.model,
            estimated_total_tokens=total,
            reason=reason,
        )


def setup_instructions(provider: ProviderName):
    """Return the documented Hermes setup flow for one supported provider."""

    from automation.agent.models import AuthMethod, ProviderSetupInstructions

    descriptors = {
        ProviderName.CLAUDE: ProviderSetupInstructions(
            provider=provider,
            hermes_provider="anthropic",
            supported_auth=[AuthMethod.API_KEY, AuthMethod.OAUTH],
            api_key_environment_variable="ANTHROPIC_API_KEY",
            setup_command=["hermes", "model"],
            oauth_command=["hermes", "auth", "add", "anthropic", "--type", "oauth"],
            documentation_url="https://hermes-agent.nousresearch.com/docs/integrations/providers",
            credential_policy="API keys use the OS keychain; OAuth tokens remain in Hermes/Claude protected storage.",
        ),
        ProviderName.CODEX: ProviderSetupInstructions(
            provider=provider,
            hermes_provider="openai-codex",
            supported_auth=[AuthMethod.OAUTH],
            setup_command=["hermes", "model"],
            oauth_command=["hermes", "auth", "add", "openai-codex"],
            documentation_url="https://hermes-agent.nousresearch.com/docs/integrations/providers",
            credential_policy="Codex device-code credentials remain in Hermes' protected auth store.",
        ),
        ProviderName.GEMINI: ProviderSetupInstructions(
            provider=provider,
            hermes_provider="gemini",
            supported_auth=[AuthMethod.API_KEY],
            api_key_environment_variable="GEMINI_API_KEY",
            setup_command=["hermes", "model"],
            documentation_url="https://hermes-agent.nousresearch.com/docs/integrations/providers",
            credential_policy="The Gemini API key is kept in the OS keychain and injected only into the managed process.",
        ),
        ProviderName.DEEPSEEK: ProviderSetupInstructions(
            provider=provider,
            hermes_provider="deepseek",
            supported_auth=[AuthMethod.API_KEY],
            api_key_environment_variable="DEEPSEEK_API_KEY",
            setup_command=["hermes", "model"],
            documentation_url="https://hermes-agent.nousresearch.com/docs/integrations/providers",
            credential_policy="The DeepSeek API key is kept in the OS keychain and injected only into the managed process.",
        ),
    }
    return descriptors[provider]
