"""Deterministic construction of the sole renderer input."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from automation.metrics import calculate_metric
from automation.metrics.models import MetricDefinition as ExecutableMetric, MetricOperation
from automation.reports.models import ReportDocument
from automation.specification.models import DashboardSpec


def _filter_records(spec: DashboardSpec, records: Iterable[Mapping[str, Any]], values: Mapping[str, Any]) -> list[dict[str, Any]]:
    filters = {item.id: item for item in spec.filters}
    unknown = set(values) - set(filters)
    if unknown:
        raise ValueError(f"Unknown report filter: {sorted(unknown)[0]}")
    result: list[dict[str, Any]] = []
    for source in records:
        include = True
        for identifier, expected in values.items():
            definition = filters[identifier]
            choices = expected if definition.multiple and isinstance(expected, list) else [expected]
            if source.get(definition.field) not in choices:
                include = False
                break
        if include:
            result.append(dict(source))
    return result


def build_report_document(
    specification: DashboardSpec,
    records: Iterable[Mapping[str, Any]],
    *,
    filter_values: Mapping[str, Any] | None = None,
    synthetic: bool = False,
    insights: list[dict[str, str]] | None = None,
    quality_findings: list[dict[str, str]] | None = None,
) -> ReportDocument:
    """Apply filters and calculate authoritative metrics exactly once."""

    filtered = _filter_records(specification, records, filter_values or {})
    metrics: dict[str, int | float | None] = {}
    for definition in specification.metrics:
        executable = ExecutableMetric(
            id=definition.id, operation=MetricOperation(definition.operation),
            field=definition.field, numerator_field=definition.numerator_field,
            denominator_field=definition.denominator_field, group_by=definition.group_by,
            filters=definition.filters, approved=definition.approved,
        )
        metrics[definition.id] = calculate_metric(filtered, executable).value
    return ReportDocument(
        specification=specification, records=filtered, metrics=metrics,
        synthetic=synthetic, filter_values=dict(filter_values or {}),
        insights=insights or [], quality_findings=quality_findings or [],
    )
