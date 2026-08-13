from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from automation.agent.client import HermesClient, HermesExecutionError, HermesTaskRunner
from automation.agent.credentials import (
    CredentialReference,
    MemoryCredentialStore,
    NativeOAuthReference,
)
from automation.agent.gateway import GatewayConfig, HermesGateway
from automation.agent.memory import MemoryKind, SafeMemoryStore
from automation.agent.models import (
    AuthMethod,
    ProviderConnection,
    ProviderName,
    TaskCapability,
    TaskRequest,
    TokenEstimate,
)
from automation.agent.routing import ProviderRouter, ProviderUnavailableError, setup_instructions
from automation.agent.runtime import HERMES_VERSION, HermesRuntime, HermesRuntimeSpec
from automation.agent.validation import StructuredResponseError, StructuredResponseValidator
from dashboard.api.main import app


def connection(
    provider: ProviderName,
    *,
    output: int,
    auth_method: AuthMethod = AuthMethod.API_KEY,
    capabilities: set[TaskCapability] | None = None,
) -> ProviderConnection:
    credential = (
        CredentialReference(service="dashboard-test", account=provider.value)
        if auth_method is AuthMethod.API_KEY
        else NativeOAuthReference(backend="hermes-auth-store", provider=provider.value, account="test")
    )
    return ProviderConnection(
        provider=provider,
        account_id="test-account",
        model=f"{provider.value}-model",
        auth_method=auth_method,
        credential=credential,
        capabilities=capabilities or {TaskCapability.CONVERSATION, TaskCapability.STRUCTURED_OUTPUT},
        token_estimate=TokenEstimate(input_tokens=100, output_tokens=output),
    )


def test_router_selects_lowest_total_tokens_and_honors_explicit_provider() -> None:
    router = ProviderRouter([
        connection(ProviderName.CLAUDE, output=500),
        connection(ProviderName.GEMINI, output=100),
    ])
    request = TaskRequest(task_id="one", task="discover", required_capabilities={TaskCapability.STRUCTURED_OUTPUT})
    assert router.route(request).provider is ProviderName.GEMINI

    explicit = request.model_copy(update={"requested_provider": ProviderName.CLAUDE})
    assert router.route(explicit).provider is ProviderName.CLAUDE


def test_router_does_not_fallback_when_explicit_provider_is_unavailable() -> None:
    router = ProviderRouter([connection(ProviderName.GEMINI, output=100)])
    request = TaskRequest(task_id="one", task="discover", requested_provider=ProviderName.CLAUDE)
    with pytest.raises(ProviderUnavailableError) as error:
        router.route(request)
    assert error.value.fallback_requires_confirmation is True


def test_task_failure_requires_confirmation_before_fallback() -> None:
    class Output(BaseModel):
        model_config = ConfigDict(extra="forbid")

        answer: str

    class FailingTransport:
        def submit(self, payload):
            raise RuntimeError("provider unavailable")

    router = ProviderRouter([connection(ProviderName.CLAUDE, output=100)])
    runner = HermesTaskRunner(router, FailingTransport())
    request = TaskRequest(task_id="one", task="structured", requested_provider=ProviderName.CLAUDE)
    with pytest.raises(HermesExecutionError) as error:
        runner.execute(request, Output)
    assert error.value.fallback_requires_confirmation is True
    with pytest.raises(HermesExecutionError, match="confirmation"):
        runner.execute_after_fallback_confirmation(
            request,
            Output,
            fallback_provider=ProviderName.GEMINI,
            user_confirmed=False,
        )


def test_gateway_requires_loopback_and_keeps_key_out_of_command() -> None:
    with pytest.raises(ValueError, match="loopback"):
        GatewayConfig(
            host="0.0.0.0",
            api_key_reference=CredentialReference(service="test", account="gateway"),
        )
    store = MemoryCredentialStore()
    reference = CredentialReference(service="test", account="gateway")
    store.put(reference, "super-secret")
    gateway = HermesGateway(store)
    config = GatewayConfig(api_key_reference=reference, cors_origins=("http://127.0.0.1:3000",))
    assert gateway.start(config, "/private/hermes", dry_run=True) == ["/private/hermes", "gateway"]
    for invalid in (
        "http://127.0.0.1.evil.test:8642",
        "https://127.0.0.1:8642",
        "http://user@127.0.0.1:8642",
        "http://127.0.0.1:8642/path",
        "http://127.0.0.1",
    ):
        with pytest.raises(ValueError):
            HermesClient(invalid, "token")


def test_gateway_discards_unconsumed_child_output(monkeypatch) -> None:
    captured = {}

    class Process:
        def poll(self):
            return None

    def popen(command, **kwargs):
        captured.update(kwargs)
        return Process()

    monkeypatch.setattr(subprocess, "Popen", popen)
    store = MemoryCredentialStore()
    reference = CredentialReference(service="test", account="gateway")
    store.put(reference, "super-secret")

    HermesGateway(store).start(GatewayConfig(api_key_reference=reference), "/private/hermes")

    assert captured["stdout"] is subprocess.DEVNULL
    assert captured["stderr"] is subprocess.DEVNULL


def test_runtime_is_pinned_and_uses_managed_executable(tmp_path: Path) -> None:
    runtime = HermesRuntime(HermesRuntimeSpec(environment_dir=tmp_path / "hermes"))
    assert HERMES_VERSION
    assert runtime.spec.requirement == f"hermes-agent=={HERMES_VERSION}"
    assert runtime.gateway_command()[-1] == "gateway"
    assert str(tmp_path / "hermes") in runtime.gateway_command()[0]


def test_provider_setup_flows_are_documented_and_secret_free() -> None:
    codex = setup_instructions(ProviderName.CODEX)
    assert codex.oauth_command == ["hermes", "auth", "add", "openai-codex"]
    assert "secret" not in codex.model_dump_json().lower()
    gemini = setup_instructions(ProviderName.GEMINI)
    assert gemini.api_key_environment_variable == "GEMINI_API_KEY"


def test_structured_response_rejects_unknown_or_missing_fields() -> None:
    class Output(BaseModel):
        model_config = ConfigDict(extra="forbid")

        answer: str

    assert StructuredResponseValidator.validate({"answer": "ok"}, Output).answer == "ok"
    with pytest.raises(StructuredResponseError):
        StructuredResponseValidator.validate({"answer": "ok", "metric": 10}, Output)
    with pytest.raises(StructuredResponseError):
        StructuredResponseValidator.validate({"metric": 10}, Output)


def test_memory_persists_only_compact_non_confidential_context(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    memory = SafeMemoryStore(path)
    memory.remember(kind=MemoryKind.GLOBAL_PREFERENCE, key="accent_color", value="#123456")
    memory.remember(kind=MemoryKind.PROJECT_TERMINOLOGY, project_id="project-1", key="revenue", value="Receita")
    assert len(memory.project_context("project-1")) == 2
    assert "source" not in path.read_text()
    with pytest.raises(ValueError):
        memory.remember(kind=MemoryKind.FEEDBACK, key="source_records", value="private")
    with pytest.raises(ValueError):
        memory.remember(kind=MemoryKind.FEEDBACK, key="note", value="user@example.com")


def test_provider_api_exposes_setup_without_accepting_raw_secrets() -> None:
    from fastapi.testclient import TestClient

    client = TestClient(app)
    response = client.get("/api/providers/setup/codex")
    assert response.status_code == 200
    assert response.json()["oauth_command"] == ["hermes", "auth", "add", "openai-codex"]
    rejected = client.post(
        "/api/providers/connect",
        json={"connection": {"provider": "gemini", "account_id": "a", "model": "m", "auth_method": "api_key", "api_key": "raw"}},
    )
    assert rejected.status_code == 422
