"""Canonical, domain-neutral specification shared by every renderer."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldKind(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"


class SectionKind(StrEnum):
    SUMMARY = "summary"
    METRICS = "metrics"
    CHART = "chart"
    TABLE = "table"
    INSIGHTS = "insights"


class VisualizationKind(StrEnum):
    CARD = "card"
    TABLE = "table"
    BAR = "bar"
    LINE = "line"
    AREA = "area"
    PIE = "pie"
    DONUT = "donut"
    FUNNEL = "funnel"


class OutputKind(StrEnum):
    WEB = "web"
    EXCEL = "xlsx"
    PDF = "pdf"


class FieldDefinition(StrictModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: FieldKind
    nullable: bool = True
    confidential: bool = False


class FieldMapping(StrictModel):
    source_field: str = Field(min_length=1)
    target_field: str = Field(min_length=1)
    approved: bool = False


class MetricDefinition(StrictModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    operation: str = Field(pattern="^(count|sum|average|ratio)$")
    field: str | None = None
    numerator_field: str | None = None
    denominator_field: str | None = None
    group_by: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    explanation: str = Field(min_length=1)
    approved: bool = False

    @model_validator(mode="after")
    def operands_match_operation(self) -> "MetricDefinition":
        if self.operation in {"sum", "average"} and not self.field:
            raise ValueError("sum and average metrics require field")
        if self.operation == "ratio" and not (self.numerator_field and self.denominator_field):
            raise ValueError("ratio metrics require numerator_field and denominator_field")
        return self


class FilterSpec(StrictModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    field: str = Field(min_length=1)
    multiple: bool = False


class VisualizationSpec(StrictModel):
    id: str = Field(min_length=1)
    kind: VisualizationKind
    title: str = Field(min_length=1)
    metric_ids: list[str] = Field(default_factory=list)
    dimension_field: str | None = None
    value_field: str | None = None
    options: dict[str, str | int | float | bool] = Field(default_factory=dict)


class LayoutSpec(StrictModel):
    columns: int = Field(default=12, ge=1, le=24)
    row_height: int = Field(default=80, ge=20, le=400)
    positions: dict[str, tuple[int, int, int, int]] = Field(default_factory=dict)


class SectionSpec(StrictModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    kind: SectionKind
    visualization_ids: list[str] = Field(default_factory=list)
    field_ids: list[str] = Field(default_factory=list)
    metric_ids: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    order: int = Field(ge=0)


class LocalizationSpec(StrictModel):
    language: str = Field(pattern="^(en|pt)(-[A-Z]{2})?$")
    locale: str = Field(min_length=2)
    timezone: str = Field(min_length=1)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    date_format: str = Field(default="YYYY-MM-DD", min_length=1)
    number_format: str = Field(default="1,234.56", min_length=1)


class PrivacyPolicy(StrictModel):
    confidential_fields: list[str] = Field(default_factory=list)
    allow_temporary_display: bool = False
    allow_persistence: bool = True
    redact_logs: bool = True


class OutputSpec(StrictModel):
    enabled: list[OutputKind] = Field(min_length=1)
    excel_sheet_names: dict[str, str] = Field(default_factory=dict)
    pdf_page_size: str = "A4"


class StyleSpec(StrictModel):
    palette: list[str] = Field(default_factory=lambda: ["#23543C"])
    font_family: str = Field(default="Arial", min_length=1, max_length=120)
    border_color: str = Field(default="#D6DDD8", pattern=r"^#[0-9A-Fa-f]{6}$")
    spacing: int = Field(default=10, ge=0, le=80)

    @field_validator("palette")
    @classmethod
    def valid_palette(cls, value: list[str]) -> list[str]:
        if not value or len(value) > 12 or any(not re.fullmatch(r"#[0-9A-Fa-f]{6}", item) for item in value):
            raise ValueError("Style palette requires one to twelve hex colors")
        return value


class ApprovalVersion(StrictModel):
    version: int = Field(ge=1)
    approved_at: datetime
    approved_by: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    checksum_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    rolled_back_from: int | None = Field(default=None, ge=1)


class DashboardSpec(StrictModel):
    """The only approved input accepted by web, Excel, and PDF renderers."""

    schema_version: int = Field(default=1, ge=1)
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    fields: list[FieldDefinition]
    mappings: list[FieldMapping]
    metrics: list[MetricDefinition]
    filters: list[FilterSpec] = Field(default_factory=list)
    visualizations: list[VisualizationSpec] = Field(default_factory=list)
    sections: list[SectionSpec]
    layout: LayoutSpec = Field(default_factory=LayoutSpec)
    terminology: dict[str, str] = Field(default_factory=dict)
    localization: LocalizationSpec
    privacy: PrivacyPolicy = Field(default_factory=PrivacyPolicy)
    outputs: OutputSpec
    style: StyleSpec = Field(default_factory=StyleSpec)

    @model_validator(mode="after")
    def validate_references_and_approvals(self) -> "DashboardSpec":
        def ids(items: list[Any], label: str) -> set[str]:
            values = [item.id for item in items]
            if len(values) != len(set(values)):
                raise ValueError(f"Duplicate {label} id")
            return set(values)

        field_ids = ids(self.fields, "field")
        metric_ids = ids(self.metrics, "metric")
        visualization_ids = ids(self.visualizations, "visualization")
        section_ids = ids(self.sections, "section")
        ids(self.filters, "filter")

        for mapping in self.mappings:
            if mapping.target_field not in field_ids:
                raise ValueError(f"Mapping targets unknown field: {mapping.target_field}")
            if not mapping.approved:
                raise ValueError(f"Mapping is not approved: {mapping.source_field}")
        for metric in self.metrics:
            if not metric.approved:
                raise ValueError(f"Metric is not approved: {metric.id}")
            referenced = {metric.field, metric.numerator_field, metric.denominator_field, metric.group_by}
            referenced.update(metric.filters)
            unknown = referenced - {None} - field_ids
            if unknown:
                raise ValueError(f"Metric {metric.id} references unknown field: {sorted(unknown)[0]}")
        for filter_spec in self.filters:
            if filter_spec.field not in field_ids:
                raise ValueError(f"Filter references unknown field: {filter_spec.field}")
        for visualization in self.visualizations:
            if not set(visualization.metric_ids) <= metric_ids:
                raise ValueError(f"Visualization {visualization.id} references unknown metric")
            for field in (visualization.dimension_field, visualization.value_field):
                if field is not None and field not in field_ids:
                    raise ValueError(f"Visualization {visualization.id} references unknown field: {field}")
        dependencies: dict[str, list[str]] = {}
        for section in self.sections:
            if not set(section.visualization_ids) <= visualization_ids:
                raise ValueError(f"Section {section.id} references unknown visualization")
            if not set(section.field_ids) <= field_ids or not set(section.metric_ids) <= metric_ids:
                raise ValueError(f"Section {section.id} references unknown field or metric")
            if not set(section.depends_on) <= section_ids or section.id in section.depends_on:
                raise ValueError(f"Section {section.id} has an invalid dependency")
            dependencies[section.id] = section.depends_on

        visiting: set[str] = set()
        visited: set[str] = set()
        def visit(section_id: str) -> None:
            if section_id in visiting:
                raise ValueError("Section dependencies contain a cycle")
            if section_id in visited:
                return
            visiting.add(section_id)
            for dependency in dependencies[section_id]:
                visit(dependency)
            visiting.remove(section_id)
            visited.add(section_id)
        for section_id in section_ids:
            visit(section_id)

        confidential = set(self.privacy.confidential_fields)
        declared_confidential = {field.id for field in self.fields if field.confidential}
        if confidential - field_ids or confidential != declared_confidential:
            raise ValueError("Privacy confidential_fields must exactly match confidential field definitions")
        if confidential and self.privacy.allow_persistence:
            raise ValueError("Specifications with confidential fields cannot allow data persistence")
        if set(self.layout.positions) - visualization_ids:
            raise ValueError("Layout positions reference unknown visualizations")
        return self
