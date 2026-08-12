"""Local onboarding and execution endpoints for JSON API sources."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from automation.agent.credentials import MemoryCredentialStore
from automation.connectors.client import ApiClient, ApiRequestError
from automation.connectors.models import ApiInspection, ApiSourceConfig, ApiSyncRequest, ApiSyncResult


class ApiInspectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: ApiSourceConfig
    representative_json: Any | None = None
    openapi_document: dict[str, Any] | None = None
    target_fields: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_source_description(self) -> "ApiInspectRequest":
        if self.representative_json is None and self.openapi_document is None:
            raise ValueError("Provide representative JSON or an OpenAPI/Swagger document")
        return self


class ApiSyncEndpointRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: ApiSyncRequest
    expected_inspection: ApiInspection | None = None

    @model_validator(mode="after")
    def require_approved_inspection(self) -> "ApiSyncEndpointRequest":
        if self.expected_inspection is None:
            raise ValueError("A persisted inspection is required before synchronization")
        if self.expected_inspection.source_id != self.request.source.id:
            raise ValueError("Inspection source does not match the configured source")
        paths = {field.path for field in self.expected_inspection.fields}
        if set(self.request.approved_mappings) - paths:
            raise ValueError("Approved mappings must come from the inspected source")
        return self


router = APIRouter(prefix="/api/api-sources", tags=["api-sources"])
_credential_store = MemoryCredentialStore()
_api_client = ApiClient(_credential_store)
_sources: dict[str, ApiSourceConfig] = {}


@router.get("", response_model=list[ApiSourceConfig])
def list_api_sources() -> list[ApiSourceConfig]:
    return list(_sources.values())


@router.put("/{source_id}", response_model=ApiSourceConfig)
def save_api_source(source_id: str, source: ApiSourceConfig) -> ApiSourceConfig:
    if source.id != source_id:
        raise HTTPException(status_code=400, detail="Source id in the URL must match the configuration")
    _sources[source_id] = source
    return source


@router.delete("/{source_id}", status_code=204)
def delete_api_source(source_id: str) -> None:
    if source_id not in _sources:
        raise HTTPException(status_code=404, detail="API source not found")
    _sources.pop(source_id)


@router.post("/inspect", response_model=ApiInspection)
def inspect_api_source(payload: ApiInspectRequest) -> ApiInspection:
    return _api_client.inspect(
        payload.source,
        payload.representative_json,
        target_fields=payload.target_fields,
        openapi_document=payload.openapi_document,
    )


@router.post("/sync", response_model=ApiSyncResult)
def sync_api_source(payload: ApiSyncEndpointRequest) -> ApiSyncResult:
    try:
        result = _api_client.sync(payload.request, expected_inspection=payload.expected_inspection)
    except ApiRequestError as exc:
        code = 409 if "drift" in str(exc).casefold() or "approval" in str(exc).casefold() else 502
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return result
