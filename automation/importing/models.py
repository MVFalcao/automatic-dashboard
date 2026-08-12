"""Contracts for import summaries that exclude source record values."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ImportMode(StrEnum):
    REPLACE = "replace"
    APPEND = "append"
    UPDATE = "update"


class DataSourceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    format: str
    section: str
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    columns: list[str]
    likely_confidential_columns: list[str]
    validation_issues: list[str] = Field(default_factory=list)


class ProposedMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_column: str
    target_field: str | None
    confidence: str
    requires_confirmation: bool = True


class ImportPlan(BaseModel):
    """Review-only plan; it does not contain imported row values."""

    model_config = ConfigDict(extra="forbid")

    sources: list[DataSourceSummary]
    mappings: list[ProposedMapping]
    validation_issues: list[str]
    requires_relationship_confirmation: bool
    requires_user_approval: bool = True
    allowed_modes: list[ImportMode] = Field(
        default_factory=lambda: [ImportMode.REPLACE, ImportMode.APPEND, ImportMode.UPDATE]
    )


class ImportApproval(BaseModel):
    """The explicit decisions required before source records may be applied."""

    model_config = ConfigDict(extra="forbid")

    approved: bool
    mode: ImportMode
    mappings: dict[str, str]
    relationships_confirmed: bool = False
    confidential_columns: list[str] = Field(default_factory=list)
    field_classifications: dict[str, bool] = Field(default_factory=dict)
    classification_overrides: dict[str, bool] = Field(default_factory=dict)
    update_identifier: str | None = None
    update_identifier_confirmed: bool = False
    permit_persistence: bool = False


class ImportResult(BaseModel):
    """Deterministic import outcome containing counts, never source values."""

    model_config = ConfigDict(extra="forbid")

    mode: ImportMode
    source_rows: int = Field(ge=0)
    output_rows: int = Field(ge=0)
    inserted_rows: int = Field(ge=0)
    updated_rows: int = Field(ge=0)
    skipped_rows: int = Field(ge=0)
    validation_issues: list[str] = Field(default_factory=list)
    persisted: bool = False


# Public name used by API and later persisted-project contracts.
ImportInspection = ImportPlan
