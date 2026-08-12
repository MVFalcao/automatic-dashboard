"""Validated synthetic dashboard rendering for the local review UI."""

from __future__ import annotations

import random
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from automation.metrics import calculate_metric
from automation.metrics.models import MetricDefinition as ExecutableMetric
from automation.metrics.models import MetricOperation
from automation.specification.models import DashboardSpec


class DashboardRenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    specification: DashboardSpec
    record_count: int = Field(default=24, ge=1, le=500)
    authorize_confidential_display: bool = False


class DashboardRender(BaseModel):
    model_config = ConfigDict(extra="forbid")

    specification: DashboardSpec
    synthetic: bool = True
    records: list[dict[str, Any]]
    metrics: dict[str, int | float | None]
    temporary_in_memory: bool
    warnings: list[str]


router = APIRouter(prefix="/api/dashboard-specs", tags=["dashboard-specs"])


def _records(spec: DashboardSpec, count: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        row: dict[str, Any] = {}
        for field in spec.fields:
            randomizer = random.Random(f"{spec.id}:{field.id}:{index}")
            if field.kind == "number":
                row[field.id] = round(randomizer.uniform(100, 2500), 2)
            elif field.kind == "boolean":
                row[field.id] = index % 2 == 0
            elif field.kind in {"date", "datetime"}:
                row[field.id] = f"2026-{((index - 1) % 12) + 1:02d}-{((index - 1) % 28) + 1:02d}"
            else:
                row[field.id] = f"{field.label} {((index - 1) % 5) + 1}"
        rows.append(row)
    return rows


def render_dashboard(payload: DashboardRenderRequest) -> DashboardRender:
    confidential = bool(payload.specification.privacy.confidential_fields)
    if confidential and not payload.authorize_confidential_display:
        raise ValueError("Confidential dashboard display requires explicit authorization")
    records = _records(payload.specification, payload.record_count)
    metrics: dict[str, int | float | None] = {}
    for definition in payload.specification.metrics:
        executable = ExecutableMetric(
            id=definition.id,
            operation=MetricOperation(definition.operation),
            field=definition.field,
            numerator_field=definition.numerator_field,
            denominator_field=definition.denominator_field,
            group_by=definition.group_by,
            filters=definition.filters,
            approved=definition.approved,
        )
        result = calculate_metric(records, executable)
        metrics[definition.id] = result.value
    return DashboardRender(
        specification=payload.specification,
        records=records,
        metrics=metrics,
        temporary_in_memory=confidential,
        warnings=["Synthetic values are used for structure and design approval."],
    )


@router.post("/render", response_model=DashboardRender)
def create_render(payload: DashboardRenderRequest) -> DashboardRender:
    try:
        return render_dashboard(payload)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
