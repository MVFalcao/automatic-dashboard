"""Loopback-only provider setup and Hermes status endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from automation.agent.models import ProviderConnection, ProviderName
from automation.agent.providers import ProviderRegistry
from automation.agent.runtime import HERMES_PACKAGE, HERMES_VERSION


class ProviderSetupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection: ProviderConnection


router = APIRouter(prefix="/api", tags=["hermes"])
provider_registry = ProviderRegistry()


@router.get("/providers", response_model=list[ProviderConnection])
def list_providers() -> list[ProviderConnection]:
    return provider_registry.list()


@router.get("/providers/setup/{provider}")
def provider_setup(provider: ProviderName) -> dict:
    return provider_registry.setup(provider).model_dump(mode="json")


@router.post("/providers/connect", response_model=ProviderConnection, status_code=201)
def connect_provider(payload: ProviderSetupRequest) -> ProviderConnection:
    return provider_registry.connect(payload.connection)


@router.delete("/providers/{provider}", status_code=204)
def disconnect_provider(provider: ProviderName) -> None:
    if provider_registry.get(provider) is None:
        raise HTTPException(status_code=404, detail="Provider is not connected")
    provider_registry.remove(provider)


@router.get("/hermes/status")
def hermes_status() -> dict[str, str | bool]:
    """Expose runtime metadata without exposing credential values or paths."""

    return {
        "managed": True,
        "package": HERMES_PACKAGE,
        "version": HERMES_VERSION,
        "gateway_host": "127.0.0.1",
        "gateway_authenticated": True,
    }

