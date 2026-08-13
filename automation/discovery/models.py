"""Format-neutral evidence contracts produced by reference analysis."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FieldType(StrEnum):
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    NUMBER = "number"
    TEXT = "text"
    UNKNOWN = "unknown"


class FieldEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    source_location: str
    inferred_type: FieldType
    confidence: Confidence
    non_empty_samples: int = Field(ge=0)


class SectionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    source_location: str
    rows: int = Field(ge=0)
    columns: int = Field(ge=0)
    non_empty_cells: int = Field(ge=0)
    formula_cells: int = Field(ge=0)
    merged_ranges: int = Field(ge=0)
    chart_count: int = Field(ge=0)
    hidden: bool
    fields: list[FieldEvidence] = Field(default_factory=list)
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict)


class StyleEvidence(BaseModel):
    """Value-free visual evidence that may be approved for renderer styling."""

    model_config = ConfigDict(extra="forbid")

    palette: list[str] = Field(default_factory=list)
    font_families: list[str] = Field(default_factory=list)
    font_sizes: list[float] = Field(default_factory=list)
    row_heights: list[float] = Field(default_factory=list)
    column_widths: list[float] = Field(default_factory=list)
    border_styles: list[str] = Field(default_factory=list)
    chart_types: list[str] = Field(default_factory=list)
    organization: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.LOW
    requires_review: bool = True


class SampleManifest(BaseModel):
    """Structural evidence only; it never contains source record values."""

    model_config = ConfigDict(extra="forbid")

    format: str
    sections: list[SectionEvidence]
    extraction_permitted: bool
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    style: StyleEvidence = Field(default_factory=StyleEvidence)


class ProposedField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str
    inferred_type: FieldType
    confidence: Confidence
    evidence: list[str]
    requires_approval: bool = True


class ProposedSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str
    source_section: str
    presentation: str
    confidence: Confidence
    requires_approval: bool = True


class DraftDashboardSchema(BaseModel):
    """A reviewable proposal. It is never an approved executable schema."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    source_format: str
    fields: list[ProposedField]
    sections: list[ProposedSection]
    assumptions: list[str]
    requires_user_approval: bool = True
