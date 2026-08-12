"""Renderer-neutral report document contracts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from automation.specification.models import DashboardSpec, OutputKind


class ReportDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    specification: DashboardSpec
    records: list[dict[str, Any]]
    metrics: dict[str, int | float | None]
    synthetic: bool = False


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: ReportDocument
    outputs: list[OutputKind] = Field(min_length=1)
    confidential: bool = False
    confidential_lifecycle_approved: bool = False


class ReportArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    output: OutputKind
    filename: str
    media_type: str
    confidential: bool
    one_time_download: bool
    size_bytes: int = Field(ge=0)
