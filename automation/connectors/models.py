"""Strict, secret-free contracts for JSON API sources.

Only credential *references* are accepted here.  A source configuration can
therefore safely be written to a project YAML/JSON file.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from automation.agent.credentials import CredentialReference, NativeOAuthReference


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApiAuthMethod(StrEnum):
    NONE = "none"
    API_KEY = "api_key"
    BEARER = "bearer"
    OAUTH = "oauth"


class PaginationKind(StrEnum):
    NONE = "none"
    PAGE = "page"
    CURSOR = "cursor"
    LINK = "link"


class DriftClass(StrEnum):
    SAFE = "safe"
    REVIEW_REQUIRED = "review_required"
    BLOCKING = "blocking"


class PaginationConfig(StrictModel):
    kind: PaginationKind = PaginationKind.NONE
    page_param: str = Field(default="page", min_length=1, max_length=80)
    page_size_param: str = Field(default="page_size", min_length=1, max_length=80)
    page_size: int = Field(default=100, ge=1, le=1000)
    start_page: int = Field(default=1, ge=0)
    cursor_param: str = Field(default="cursor", min_length=1, max_length=80)
    next_cursor_path: str = Field(default="next_cursor", min_length=1, max_length=200)
    next_link_path: str = Field(default="next", min_length=1, max_length=200)
    max_pages: int = Field(default=100, ge=1, le=10000)


class ApiSourceConfig(StrictModel):
    """Persistable source definition; it intentionally has no secret fields."""

    id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    name: str = Field(min_length=1, max_length=160)
    endpoint: HttpUrl
    auth_method: ApiAuthMethod = ApiAuthMethod.NONE
    credential_reference: CredentialReference | NativeOAuthReference | None = None
    api_key_header: str = Field(default="X-API-Key", min_length=1, max_length=100)
    records_path: str | None = Field(default=None, max_length=200)
    pagination: PaginationConfig = Field(default_factory=PaginationConfig)
    timeout_seconds: float = Field(default=20.0, gt=0, le=300)
    max_retries: int = Field(default=3, ge=0, le=8)
    backoff_seconds: float = Field(default=0.25, ge=0, le=30)
    requests_per_second: float | None = Field(default=None, gt=0, le=100)
    incremental_field: str | None = Field(default=None, max_length=160)
    incremental_confirmed: bool = False

    @model_validator(mode="after")
    def validate_auth_reference(self) -> "ApiSourceConfig":
        if self.auth_method is ApiAuthMethod.NONE and self.credential_reference is not None:
            raise ValueError("Unauthenticated sources cannot include a credential reference")
        if self.auth_method in {ApiAuthMethod.API_KEY, ApiAuthMethod.BEARER}:
            if not isinstance(self.credential_reference, CredentialReference):
                raise ValueError("API-key and Bearer sources require an OS credential reference")
        if self.auth_method is ApiAuthMethod.OAUTH:
            if not isinstance(self.credential_reference, NativeOAuthReference):
                raise ValueError("OAuth sources require a Hermes/provider protected-store reference")
        if self.incremental_confirmed and not self.incremental_field:
            raise ValueError("Incremental refresh confirmation requires an updated-time field")
        return self


class ApiField(StrictModel):
    path: str = Field(min_length=1, max_length=300)
    name: str = Field(min_length=1, max_length=160)
    type: str = Field(min_length=1, max_length=40)
    nullable: bool = True
    sample_count: int = Field(default=0, ge=0)
    evidence: str = Field(default="Inferred from representative JSON", max_length=500)


class ApiFieldMapping(StrictModel):
    source_path: str = Field(min_length=1, max_length=300)
    target_field: str = Field(min_length=1, max_length=160)
    confidence: str = Field(pattern=r"^(high|medium|low|unmapped)$")
    explanation: str = Field(min_length=1, max_length=500)
    approved: bool = False


class ApiInspection(StrictModel):
    source_id: str = Field(min_length=1, max_length=160)
    fields: list[ApiField]
    mappings: list[ApiFieldMapping] = Field(default_factory=list)
    record_shape: str = Field(min_length=1, max_length=80)
    records_path: str | None = None
    validation_issues: list[str] = Field(default_factory=list)
    requires_approval: bool = True
    inspected_at: datetime


class ApiSyncRequest(StrictModel):
    source: ApiSourceConfig
    mode: str = Field(default="full", pattern=r"^(full|incremental)$")
    checkpoint: str | int | float | datetime | None = None
    approved_mappings: dict[str, str] = Field(default_factory=dict)
    approval_confirmed: bool = False

    @model_validator(mode="after")
    def validate_incremental(self) -> "ApiSyncRequest":
        if self.mode == "incremental" and not self.source.incremental_confirmed:
            raise ValueError("Incremental refresh requires confirmation of a cursor or updated-time field")
        if self.approved_mappings and not self.approval_confirmed:
            raise ValueError("Field mappings must be approved before synchronization")
        return self


class ExtractionProvenance(StrictModel):
    endpoint: str
    fetched_at: datetime
    page: int = Field(ge=1)
    record_index: int = Field(ge=0)
    cursor: str | None = None


class SchemaDriftEvent(StrictModel):
    path: str
    kind: str
    classification: DriftClass
    detail: str


class ApiSyncResult(StrictModel):
    source_id: str
    mode: str
    records: list[dict[str, Any]]
    provenance: list[ExtractionProvenance]
    record_count: int = Field(ge=0)
    pages_fetched: int = Field(ge=0)
    next_checkpoint: str | int | float | datetime | None = None
    schema_drift: list[SchemaDriftEvent] = Field(default_factory=list)
    complete: bool = True
    warnings: list[str] = Field(default_factory=list)

