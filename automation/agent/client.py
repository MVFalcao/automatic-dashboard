"""Small authenticated client boundary around the Hermes localhost API."""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from automation.agent.models import ProviderName, TaskRequest, TaskResponse
from automation.agent.routing import ProviderRouter, ProviderSelection
from automation.agent.validation import StructuredResponseValidator
from automation.observability.logging import StructuredLogger


class HermesTransport(Protocol):
    def submit(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class HermesExecutionError(RuntimeError):
    """The selected provider failed; fallback always needs user approval."""

    fallback_requires_confirmation = True


T = TypeVar("T", bound=BaseModel)


class HermesTaskRunner:
    def __init__(self, router: ProviderRouter, transport: HermesTransport) -> None:
        self.router = router
        self.transport = transport

    def execute(self, request: TaskRequest, response_type: type[T]) -> tuple[ProviderSelection, T]:
        selection = self.router.route(request)
        payload = request.model_dump(mode="json")
        payload["provider"] = selection.provider.value
        payload["model"] = selection.model
        try:
            raw = self.transport.submit(payload)
        except Exception as exc:
            raise HermesExecutionError(
                f"Hermes task failed on explicitly selected provider {selection.provider}; confirmation is required before retrying elsewhere"
            ) from exc
        response = StructuredResponseValidator.validate(raw, response_type)
        return selection, response

    def execute_after_fallback_confirmation(
        self,
        request: TaskRequest,
        response_type: type[T],
        *,
        fallback_provider: ProviderName,
        user_confirmed: bool,
    ) -> tuple[ProviderSelection, T]:
        if not user_confirmed:
            raise HermesExecutionError("Cross-provider fallback requires explicit user confirmation")
        fallback_request = request.model_copy(update={"requested_provider": fallback_provider})
        return self.execute(fallback_request, response_type)

    def execute_optional(
        self,
        request: TaskRequest,
        response_type: type[T],
        *,
        logger: StructuredLogger | None = None,
    ) -> tuple[ProviderSelection, T] | None:
        """Run optional narrative analysis without blocking deterministic reports.

        Provider failures and malformed structured responses are recorded only
        by class.  The caller can continue publishing authoritative metrics.
        Cross-provider fallback remains explicit through ``execute_after...``.
        """

        try:
            return self.execute(request, response_type)
        except Exception as exc:
            if logger is not None:
                logger.emit("optional_hermes_failed", level="WARNING", details={"failure_class": type(exc).__name__})
            return None
