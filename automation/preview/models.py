"""Contracts for synthetic, review-only preview artifacts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from automation.discovery.models import DraftDashboardSchema


class PreviewOutput(StrEnum):
    WEB = "web"
    EXCEL = "xlsx"
    PDF = "pdf"


class PreviewLanguage(StrEnum):
    ENGLISH = "en"
    PORTUGUESE = "pt"


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    dashboard_schema: DraftDashboardSchema = Field(alias="schema")
    outputs: list[PreviewOutput] = Field(min_length=1)
    language: PreviewLanguage
    synthetic_record_count: int = Field(ge=1, le=500)


class PreviewArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: PreviewOutput
    filename: str
    media_type: str
    content_base64: str
    size_bytes: int = Field(ge=0)


class PreviewPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    synthetic: bool = True
    record_count: int
    artifacts: list[PreviewArtifact]
    warnings: list[str]
