"""Loopback-only provider setup and Hermes status endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from uuid import UUID

from automation.agent.credentials import CredentialReference, KeyringCredentialStore, NativeOAuthReference
from automation.agent.models import AuthMethod, ProviderConnection, ProviderName, TaskCapability, TokenEstimate
from automation.agent.oauth import codex_oauth
from automation.agent.providers import ProviderRegistry
from automation.agent.runtime import HERMES_PACKAGE, HERMES_VERSION
from automation.agent.managed import managed_hermes
from automation.persistence.workflow import ProjectWorkflowRepository, _atomic_json
from dashboard.api.projects import project_repository


class ProviderSetupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection: ProviderConnection


class ProviderKeySetupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    provider: ProviderName
    account_id: str = Field(min_length=1, max_length=160)
    model: str = Field(min_length=1, max_length=200)
    api_key: SecretStr
    capabilities: set[TaskCapability] = Field(default_factory=lambda: {TaskCapability.CONVERSATION, TaskCapability.STRUCTURED_OUTPUT})
    estimated_input_tokens: int = Field(default=0, ge=0)
    estimated_output_tokens: int = Field(default=0, ge=0)


class CodexOAuthStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID


class CodexOAuthStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    project_id: str
    status: str
    verification_url: str | None = None
    user_code: str | None = None
    expires_in: int = Field(ge=0)
    error: str | None = None


router = APIRouter(prefix="/api", tags=["hermes"])
provider_registry = ProviderRegistry()


@router.get("/providers", response_model=list[ProviderConnection])
def list_providers(project_id: UUID | None = None) -> list[ProviderConnection]:
    if project_id is None:
        return provider_registry.list()
    try:
        project = project_repository.get(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    repository = ProjectWorkflowRepository(project.project_directory)
    connections: list[ProviderConnection] = []
    for identifier in project.provider_ids:
        try:
            connection = ProviderConnection.model_validate(repository._read("providers", identifier))
            connections.append(connection)
            provider_registry.connect(connection)
        except (KeyError, ValueError):
            continue
    return connections


@router.get("/providers/setup/{provider}")
def provider_setup(provider: ProviderName) -> dict:
    return provider_registry.setup(provider).model_dump(mode="json")


@router.post("/providers/connect", response_model=ProviderConnection, status_code=201)
def connect_provider(payload: ProviderSetupRequest) -> ProviderConnection:
    return provider_registry.connect(payload.connection)


@router.post("/providers/connect-api-key", response_model=ProviderConnection, status_code=201)
def connect_provider_api_key(payload: ProviderKeySetupRequest) -> ProviderConnection:
    try:
        project = project_repository.get(payload.project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    reference = CredentialReference(
        service="universal-dashboard-agent-provider",
        account=f"{project.id}:{payload.provider.value}:{payload.account_id}",
    )
    try:
        store = KeyringCredentialStore()
        store.put(reference, payload.api_key.get_secret_value())
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="The OS credential store is unavailable. Enable a supported keyring backend; plaintext fallback is disabled.",
        ) from exc
    connection = ProviderConnection(
        provider=payload.provider, account_id=payload.account_id, model=payload.model,
        auth_method=AuthMethod.API_KEY, credential=reference,
        capabilities=payload.capabilities,
        token_estimate=TokenEstimate(input_tokens=payload.estimated_input_tokens, output_tokens=payload.estimated_output_tokens),
    )
    repository = ProjectWorkflowRepository(project.project_directory)
    identifier = f"{payload.provider.value}-{payload.account_id}"
    _atomic_json(repository._path("providers", identifier), connection.model_dump(mode="json"))
    if identifier not in project.provider_ids:
        project_repository.save(project.model_copy(update={"provider_ids": [*project.provider_ids, identifier]}))
    return provider_registry.connect(connection)


def _persist_codex_connection(project_id: UUID) -> ProviderConnection:
    try:
        project = project_repository.get(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    connection = ProviderConnection(
        provider=ProviderName.CODEX,
        account_id="local",
        model="gpt-5.5",
        auth_method=AuthMethod.OAUTH,
        credential=NativeOAuthReference(
            backend="hermes-auth-store",
            provider="openai-codex",
            account="local",
        ),
        capabilities={TaskCapability.CONVERSATION, TaskCapability.STRUCTURED_OUTPUT, TaskCapability.INSIGHTS},
        token_estimate=TokenEstimate(input_tokens=0, output_tokens=0),
    )
    repository = ProjectWorkflowRepository(project.project_directory)
    identifier = "codex-local"
    _atomic_json(repository._path("providers", identifier), connection.model_dump(mode="json"))
    if identifier not in project.provider_ids:
        project_repository.save(project.model_copy(update={"provider_ids": [*project.provider_ids, identifier]}))
    return provider_registry.connect(connection)


@router.post("/providers/oauth/codex/start", response_model=CodexOAuthStatus, status_code=201)
def start_codex_oauth(payload: CodexOAuthStartRequest) -> CodexOAuthStatus:
    try:
        project_repository.get(payload.project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    return CodexOAuthStatus.model_validate(codex_oauth.start(str(payload.project_id)))


@router.get("/providers/oauth/codex/{session_id}", response_model=CodexOAuthStatus)
def poll_codex_oauth(session_id: str) -> CodexOAuthStatus:
    try:
        result = codex_oauth.status(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="OAuth session not found") from exc
    response = CodexOAuthStatus.model_validate(result)
    if response.status == "connected":
        _persist_codex_connection(UUID(response.project_id))
    return response


@router.delete("/providers/oauth/codex/{session_id}", status_code=204)
def cancel_codex_oauth(session_id: str) -> None:
    try:
        codex_oauth.cancel(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="OAuth session not found") from exc


@router.delete("/providers/{provider}", status_code=204)
def disconnect_provider(provider: ProviderName) -> None:
    if provider_registry.get(provider) is None:
        raise HTTPException(status_code=404, detail="Provider is not connected")
    provider_registry.remove(provider)


@router.get("/hermes/status")
def hermes_status() -> dict:
    """Expose runtime metadata without exposing credential values or paths."""

    status = managed_hermes.status()
    status["provider_count"] = len(provider_registry.list())
    status["provider_ready"] = any(item.connected for item in provider_registry.list())
    return status
