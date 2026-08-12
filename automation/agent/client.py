"""Hermes task execution and authenticated localhost API transport."""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel

from automation.agent.models import ProviderName, TaskRequest
from automation.agent.routing import ProviderRouter, ProviderSelection
from automation.agent.validation import StructuredResponseValidator
from automation.observability.logging import StructuredLogger


class HermesTransport(Protocol):
    def submit(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class HermesExecutionError(RuntimeError):
    fallback_requires_confirmation = True


T = TypeVar("T", bound=BaseModel)


class HermesTaskRunner:
    def __init__(self, router: ProviderRouter, transport: HermesTransport) -> None:
        self.router = router
        self.transport = transport

    def execute(self, request: TaskRequest, response_type: type[T]) -> tuple[ProviderSelection, T]:
        selection = self.router.route(request)
        payload = request.model_dump(mode="json")
        payload.update({"provider": selection.provider.value, "model": selection.model})
        try:
            raw = self.transport.submit(payload)
        except Exception as exc:
            raise HermesExecutionError(f"Hermes task failed on {selection.provider}; fallback confirmation is required") from exc
        return selection, StructuredResponseValidator.validate(raw, response_type)

    def execute_after_fallback_confirmation(self, request: TaskRequest, response_type: type[T], *, fallback_provider: ProviderName, user_confirmed: bool) -> tuple[ProviderSelection, T]:
        if not user_confirmed:
            raise HermesExecutionError("Cross-provider fallback requires explicit user confirmation")
        return self.execute(request.model_copy(update={"requested_provider": fallback_provider}), response_type)

    def execute_optional(self, request: TaskRequest, response_type: type[T], *, logger: StructuredLogger | None = None) -> tuple[ProviderSelection, T] | None:
        try:
            return self.execute(request, response_type)
        except Exception as exc:
            if logger is not None:
                logger.emit("optional_hermes_failed", level="WARNING", details={"failure_class": type(exc).__name__})
            return None


class HermesClient:
    """Authenticated OpenAI-compatible client for the managed Hermes gateway."""

    def __init__(self, base_url: str, api_key: str, transport: httpx.BaseTransport | None = None) -> None:
        if not base_url.startswith(("http://127.0.0.1:", "http://localhost:")):
            raise ValueError("Hermes client must use the loopback gateway")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.transport = transport

    def health(self) -> dict[str, Any]:
        with httpx.Client(base_url=self.base_url, transport=self.transport, timeout=10) as client:
            response = client.get("/health", headers={"Authorization": f"Bearer {self.api_key}"})
            response.raise_for_status()
            return response.json()

    def chat(self, *, model: str, messages: list[dict[str, str]], response_format: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": model, "messages": messages}
        if response_format is not None:
            payload["response_format"] = response_format
        with httpx.Client(base_url=self.base_url, transport=self.transport, timeout=120) as client:
            response = client.post("/v1/chat/completions", json=payload, headers={"Authorization": f"Bearer {self.api_key}"})
            response.raise_for_status()
            return response.json()
