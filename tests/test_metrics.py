from automation.metrics import (
    MetricDefinition,
    MetricOperation,
    calculate_metric,
    compare_periods,
    quality_report,
    rank_groups,
)


RECORDS = [
    {"id": "1", "team": "A", "amount": 10, "cost": 4, "active": True, "date": "2026-01-01"},
    {"id": "2", "team": "A", "amount": 20, "cost": 6, "active": True, "date": "bad"},
    {"id": "2", "team": "B", "amount": None, "cost": 5, "active": False, "date": "2026-01-03"},
]


def metric(operation: MetricOperation, **kwargs: object) -> MetricDefinition:
    return MetricDefinition(id="metric", operation=operation, approved=True, **kwargs)


def test_counts_sums_averages_ratios_filters_and_groups() -> None:
    assert calculate_metric(RECORDS, metric(MetricOperation.COUNT)).value == 3
    assert calculate_metric(RECORDS, metric(MetricOperation.SUM, field="amount")).value == 30
    assert calculate_metric(RECORDS, metric(MetricOperation.AVERAGE, field="amount")).value == 15
    assert calculate_metric(RECORDS, metric(MetricOperation.RATIO, numerator_field="amount", denominator_field="cost")).value == 2
    grouped = calculate_metric(RECORDS, metric(MetricOperation.SUM, field="amount", group_by="team"))
    assert grouped.groups == {"A": 30, "B": None}
    assert rank_groups(grouped, limit=1) == [("A", 30)]
    assert calculate_metric(RECORDS, metric(MetricOperation.COUNT, filters={"active": True})).value == 2


def test_unapproved_metrics_and_empty_denominators_are_safe() -> None:
    definition = MetricDefinition(id="draft", operation=MetricOperation.COUNT)
    try:
        calculate_metric(RECORDS, definition)
    except ValueError as exc:
        assert "not been approved" in str(exc)
    else:
        raise AssertionError("unapproved metric executed")
    assert calculate_metric([], metric(MetricOperation.RATIO, numerator_field="amount", denominator_field="cost")).value is None
    assert compare_periods(10, 0) is None
    assert compare_periods(12, 10) == 0.2


def test_quality_checks_are_deterministic() -> None:
    report = quality_report(RECORDS, {"amount": "number", "date": "date"}, identifier="id")
    assert report.missing_by_field == {"amount": 1, "date": 0}
    assert report.invalid_by_field == {"amount": 0, "date": 1}
    assert report.duplicate_count == 1
