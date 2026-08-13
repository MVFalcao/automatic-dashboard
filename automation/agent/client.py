"""Hermes task execution and authenticated localhost API transport."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Protocol, TypeVar
from urllib.parse import urlsplit

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
        usage = raw.pop("_hermes_usage", {}) if isinstance(raw, dict) else {}
        if isinstance(usage, dict):
            selection = replace(
                selection,
                actual_input_tokens=max(0, int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)),
                actual_output_tokens=max(0, int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)),
            )
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
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "http"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or parsed.query
            or parsed.path not in {"", "/"}
            or parsed.port is None
            or parsed.hostname is None
        ):
            raise ValueError("Hermes client requires an explicit loopback HTTP origin")
        from automation.agent.gateway import _is_loopback

        if not _is_loopback(parsed.hostname.casefold()):
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

    def _jobs_request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        try:
            with httpx.Client(base_url=self.base_url, transport=self.transport, timeout=30) as client:
                response = client.request(method, path, json=payload, headers={"Authorization": f"Bearer {self.api_key}"})
                response.raise_for_status()
                return None if response.status_code == 204 else response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HermesExecutionError("Hermes jobs API is unavailable") from exc

    def list_jobs(self) -> list[dict[str, Any]]:
        payload = self._jobs_request("GET", "/api/jobs")
        jobs = payload.get("jobs", []) if isinstance(payload, dict) else payload
        if not isinstance(jobs, list):
            raise HermesExecutionError("Hermes jobs API returned an invalid response")
        return [item for item in jobs if isinstance(item, dict)]

    def create_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._jobs_request("POST", "/api/jobs", payload)
        if not isinstance(result, dict):
            raise HermesExecutionError("Hermes job creation returned an invalid response")
        return result

    def update_job(self, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._jobs_request("PATCH", f"/api/jobs/{job_id}", payload)
        if not isinstance(result, dict):
            raise HermesExecutionError("Hermes job update returned an invalid response")
        return result

    def delete_job(self, job_id: str) -> None:
        self._jobs_request("DELETE", f"/api/jobs/{job_id}")

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Implement :class:`HermesTransport` over the compatible chat API.

        The task input is serialized as one structured user message.  Only the
        assistant's JSON content and usage counters cross the transport boundary.
        """

        model = str(payload.get("model", "")).strip()
        if not model:
            raise HermesExecutionError("Hermes request is missing a selected model")
        safe_payload = {
            "task_id": payload.get("task_id"),
            "task": payload.get("task"),
            "input": payload.get("input", {}),
        }
        try:
            response = self.chat(
                model=model,
                messages=[{"role": "user", "content": json.dumps(safe_payload, ensure_ascii=False, separators=(",", ":"))}],
                response_format={"type": "json_object"},
            )
            content = response["choices"][0]["message"]["content"]
            result = json.loads(content) if isinstance(content, str) else content
            if not isinstance(result, dict):
                raise ValueError("structured response is not an object")
            usage = response.get("usage", {})
            if isinstance(usage, dict):
                result["_hermes_usage"] = usage
            return result
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise HermesExecutionError("Hermes returned an invalid or unavailable structured response") from exc
