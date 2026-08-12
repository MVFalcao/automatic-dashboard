"""Validated, domain-neutral deterministic metric contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MetricOperation(StrEnum):
    COUNT = "count"
    SUM = "sum"
    AVERAGE = "average"
    RATIO = "ratio"


class MetricDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    operation: MetricOperation
    field: str | None = None
    numerator_field: str | None = None
    denominator_field: str | None = None
    group_by: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    approved: bool = False

    @model_validator(mode="after")
    def validate_operands(self) -> "MetricDefinition":
        if self.operation in {MetricOperation.SUM, MetricOperation.AVERAGE} and not self.field:
            raise ValueError("sum and average metrics require a field")
        if self.operation is MetricOperation.RATIO and not (self.numerator_field and self.denominator_field):
            raise ValueError("ratio metrics require numerator_field and denominator_field")
        return self


class MetricResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_id: str
    value: float | int | None = None
    groups: dict[str, float | int | None] = Field(default_factory=dict)


class QualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_count: int = Field(ge=0)
    missing_by_field: dict[str, int]
    duplicate_count: int = Field(ge=0)
    invalid_by_field: dict[str, int]
