"""Authoritative calculations over caller-provided canonical records."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from automation.metrics.models import MetricDefinition, MetricOperation, MetricResult, QualityReport


def _number(value: Any) -> Decimal | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _filtered(records: list[Mapping[str, Any]], filters: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [record for record in records if all(record.get(field) == value for field, value in filters.items())]


def _calculate(records: list[Mapping[str, Any]], definition: MetricDefinition) -> int | float | None:
    if definition.operation is MetricOperation.COUNT:
        return len(records) if definition.field is None else sum(record.get(definition.field) not in (None, "") for record in records)
    if definition.operation in {MetricOperation.SUM, MetricOperation.AVERAGE}:
        values = [value for record in records if (value := _number(record.get(definition.field))) is not None]
        if not values:
            return None
        result = sum(values, Decimal())
        if definition.operation is MetricOperation.AVERAGE:
            result /= len(values)
    else:
        numerator = sum((_number(record.get(definition.numerator_field)) or Decimal()) for record in records)
        denominator = sum((_number(record.get(definition.denominator_field)) or Decimal()) for record in records)
        if denominator == 0:
            return None
        result = numerator / denominator
    return int(result) if result == result.to_integral_value() else float(result)


def calculate_metric(records: Iterable[Mapping[str, Any]], definition: MetricDefinition) -> MetricResult:
    if not definition.approved:
        raise ValueError(f"Metric {definition.id!r} has not been approved")
    selected = _filtered(list(records), definition.filters)
    if not definition.group_by:
        return MetricResult(metric_id=definition.id, value=_calculate(selected, definition))
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in selected:
        groups[str(record.get(definition.group_by, ""))].append(record)
    return MetricResult(metric_id=definition.id, groups={key: _calculate(groups[key], definition) for key in sorted(groups)})


def rank_groups(result: MetricResult, *, limit: int, descending: bool = True) -> list[tuple[str, float | int]]:
    values = [(key, value) for key, value in result.groups.items() if value is not None]
    return sorted(values, key=lambda item: (item[1], item[0]), reverse=descending)[:limit]


def compare_periods(current: float | int | None, previous: float | int | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return (float(current) - float(previous)) / float(previous)


def quality_report(records: Iterable[Mapping[str, Any]], field_types: Mapping[str, str], identifier: str | None = None) -> QualityReport:
    rows = list(records)
    missing = {field: sum(row.get(field) in (None, "") for row in rows) for field in field_types}
    invalid: dict[str, int] = {}
    for field, kind in field_types.items():
        count = 0
        for row in rows:
            value = row.get(field)
            if value in (None, ""):
                continue
            if kind == "number" and _number(value) is None:
                count += 1
            elif kind in {"date", "datetime"} and not isinstance(value, (date, datetime)):
                try:
                    datetime.fromisoformat(str(value))
                except ValueError:
                    count += 1
        invalid[field] = count
    duplicate_count = 0
    if identifier:
        counts = Counter(row.get(identifier) for row in rows if row.get(identifier) not in (None, ""))
        duplicate_count = sum(count - 1 for count in counts.values() if count > 1)
    return QualityReport(row_count=len(rows), missing_by_field=missing, duplicate_count=duplicate_count, invalid_by_field=invalid)
