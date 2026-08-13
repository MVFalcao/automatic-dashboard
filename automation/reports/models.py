"""Renderer-neutral report document contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from automation.specification.models import DashboardSpec, OutputKind


class ReportDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    specification: DashboardSpec
    records: list[dict[str, Any]]
    metrics: dict[str, int | float | None]
    synthetic: bool = False
    filter_values: dict[str, Any] = Field(default_factory=dict)
    insights: list[dict[str, str]] = Field(default_factory=list)
    quality_findings: list[dict[str, str]] = Field(default_factory=list)


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: ReportDocument
    outputs: list[OutputKind] = Field(min_length=1)
    confidential: bool = False
    confidential_lifecycle_approved: bool = False
    non_confidential_destination: Path | None = None

    @model_validator(mode="after")
    def confidentiality_must_match_specification(self) -> "ReportRequest":
        expected = bool(self.document.specification.privacy.confidential_fields)
        if self.confidential != expected:
            raise ValueError("Report confidentiality must match the approved specification")
        enabled = set(self.document.specification.outputs.enabled)
        if not set(self.outputs) <= enabled:
            raise ValueError("Report outputs must be enabled by the approved specification")
        if self.confidential and self.non_confidential_destination is not None:
            raise ValueError("Confidential reports cannot use a persistent destination")
        return self


class ReportArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    output: OutputKind
    filename: str
    media_type: str
    confidential: bool
    one_time_download: bool
    size_bytes: int = Field(ge=0)
    expires_at: str | None = None
