"""Curated dashboard templates used during guided intake."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import ConfigDict

from automation.specification.models import (
    FieldDefinition,
    FieldKind,
    FieldMapping,
    MetricDefinition,
    SectionKind,
    SectionSpec,
    StrictModel,
    VisualizationKind,
    VisualizationSpec,
)


class DomainTemplate(StrictModel):
    """A fixed, reviewable dashboard structure for a common domain."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    summary: str
    fields: list[FieldDefinition]
    sections: list[SectionSpec]
    metrics: list[MetricDefinition]
    visualizations: list[VisualizationSpec]


_SENSITIVE_LABEL_TERMS = (
    "ssn", "social security", "tax id", "tin", "passport", "national id",
    "driver license", "salary", "compensation", "payroll", "bank account",
    "routing number", "credit card", "cvv", "iban",
    "medical record number", "diagnosis code", "biometric", "password",
    "credential", "date of birth", "dob",
)


def find_sensitive_labels(labels: list[str]) -> list[str]:
    """Return labels containing a case-insensitive sensitive-data term."""

    return [
        label for label in labels
        if any(term in label.casefold() for term in _SENSITIVE_LABEL_TERMS)
    ]


def _field(identifier: str, label: str, kind: FieldKind) -> FieldDefinition:
    return FieldDefinition(id=identifier, label=label, kind=kind)


def _metric(identifier: str, label: str, operation: str, explanation: str, field: str | None = None) -> MetricDefinition:
    return MetricDefinition(
        id=identifier,
        label=label,
        operation=operation,
        field=field,
        explanation=explanation,
        approved=True,
    )


def _template(
    identifier: str,
    name: str,
    summary: str,
    fields: list[FieldDefinition],
    metrics: list[MetricDefinition],
) -> DomainTemplate:
    text_field = next((item.id for item in fields if item.kind is FieldKind.TEXT), None)
    number_field = next((item.id for item in fields if item.kind is FieldKind.NUMBER), None)
    visualization = VisualizationSpec(
        id="distribution",
        kind=VisualizationKind.BAR,
        title="Distribution",
        dimension_field=text_field,
        value_field=number_field,
    )
    return DomainTemplate(
        id=identifier,
        name=name,
        summary=summary,
        fields=fields,
        sections=[
            SectionSpec(id="summary", title="Summary", kind=SectionKind.METRICS, metric_ids=[item.id for item in metrics], order=0),
            SectionSpec(id="distribution", title="Distribution", kind=SectionKind.CHART, visualization_ids=[visualization.id], depends_on=["summary"], order=1),
            SectionSpec(id="details", title="Details", kind=SectionKind.TABLE, field_ids=[item.id for item in fields], depends_on=["summary"], order=2),
        ],
        metrics=metrics,
        visualizations=[visualization],
    )


def build_generic_template(
    *,
    language: str = "en",
    terminology: Mapping[str, str] | None = None,
    chart_type: str = "bar",
    section_order: Sequence[str] = ("summary", "distribution", "details"),
) -> DomainTemplate:
    """Build the original guided-intake structure, including its labels."""

    terminology = terminology or {}
    portuguese = language == "pt"
    fields = [
        _field("group", terminology.get("group", "Grupo" if portuguese else "Group"), FieldKind.TEXT),
        _field("value", terminology.get("value", "Valor" if portuguese else "Value"), FieldKind.NUMBER),
    ]
    titles = {
        "summary": "Resumo" if portuguese else "Summary",
        "distribution": "Distribuição" if portuguese else "Distribution",
        "details": "Detalhes" if portuguese else "Details",
    }
    metric_records = "Contagem de registros." if portuguese else "Count of records."
    metric_total = "Soma determinística dos valores." if portuguese else "Deterministic sum of values."
    positions = {identifier: index for index, identifier in enumerate(section_order)}
    visualization = VisualizationSpec(
        id="distribution",
        kind=VisualizationKind(chart_type),
        title=titles["distribution"],
        dimension_field="group",
        value_field="value",
    )
    metrics = [
        _metric("records", "Registros" if portuguese else "Records", "count", metric_records),
        _metric("total", "Total", "sum", metric_total, field="value"),
    ]
    return DomainTemplate(
        id="generic",
        name="Generic",
        summary="A simple generic dashboard for grouped records and values.",
        fields=fields,
        sections=[
            SectionSpec(id="summary", title=titles["summary"], kind=SectionKind.METRICS, metric_ids=["records", "total"], order=positions["summary"]),
            SectionSpec(id="distribution", title=titles["distribution"], kind=SectionKind.CHART, visualization_ids=["distribution"], depends_on=["summary"], order=positions["distribution"]),
            SectionSpec(id="details", title=titles["details"], kind=SectionKind.TABLE, field_ids=["group", "value"], depends_on=["summary"], order=positions["details"]),
        ],
        metrics=metrics,
        visualizations=[visualization],
    )


DOMAIN_TEMPLATES: dict[str, DomainTemplate] = {
    "financial": _template(
        "financial", "Financial / Revenue", "Track transactions, revenue, and account performance.",
        [_field("date", "Date", FieldKind.DATE), _field("category", "Category", FieldKind.TEXT), _field("amount", "Amount", FieldKind.NUMBER), _field("account", "Account", FieldKind.TEXT)],
        [_metric("total_revenue", "Total revenue", "sum", "Sum of all transaction amounts.", "amount"), _metric("average_transaction", "Average transaction", "average", "Average value of a transaction.", "amount"), _metric("transaction_count", "Transaction count", "count", "Number of transactions.")],
    ),
    "health": _template(
        "health", "Health / Clinical", "Track patient encounters, departments, diagnoses, and length of stay.",
        [_field("encounter_date", "Encounter date", FieldKind.DATE), _field("department", "Department", FieldKind.TEXT), _field("diagnosis_category", "Diagnosis category", FieldKind.TEXT), _field("length_of_stay_days", "Length of stay (days)", FieldKind.NUMBER)],
        [_metric("total_encounters", "Total encounters", "count", "Number of patient encounters."), _metric("average_length_of_stay", "Average length of stay", "average", "Average number of days in a stay.", "length_of_stay_days")],
    ),
    "attendance": _template(
        "attendance", "Attendance / Presence", "Track attendance records by person, status, and department.",
        [_field("date", "Date", FieldKind.DATE), _field("person_name", "Person name", FieldKind.TEXT), _field("status", "Status", FieldKind.TEXT), _field("department", "Department", FieldKind.TEXT)],
        [_metric("total_records", "Total records", "count", "Number of attendance records.")],
    ),
    "sales": _template(
        "sales", "Sales / CRM", "Track deals, pipeline value, stages, close dates, and owners.",
        [_field("deal_name", "Deal name", FieldKind.TEXT), _field("stage", "Stage", FieldKind.TEXT), _field("value", "Value", FieldKind.NUMBER), _field("close_date", "Close date", FieldKind.DATE), _field("owner", "Owner", FieldKind.TEXT)],
        [_metric("total_pipeline_value", "Total pipeline value", "sum", "Sum of all deal values.", "value"), _metric("average_deal_size", "Average deal size", "average", "Average value of a deal.", "value"), _metric("deal_count", "Deal count", "count", "Number of deals.")],
    ),
    "hr": _template(
        "hr", "HR / Workforce", "Track employee records by department, role, hire date, and status.",
        [_field("department", "Department", FieldKind.TEXT), _field("role", "Role", FieldKind.TEXT), _field("hire_date", "Hire date", FieldKind.DATE), _field("status", "Status", FieldKind.TEXT)],
        [_metric("headcount", "Headcount", "count", "Number of employee records.")],
    ),
    "marketing": _template(
        "marketing", "Marketing / Campaign", "Track campaign channels, spend, conversions, and performance over time.",
        [_field("campaign_name", "Campaign name", FieldKind.TEXT), _field("channel", "Channel", FieldKind.TEXT), _field("spend", "Spend", FieldKind.NUMBER), _field("conversions", "Conversions", FieldKind.NUMBER), _field("date", "Date", FieldKind.DATE)],
        [_metric("total_spend", "Total spend", "sum", "Sum of campaign spend.", "spend"), _metric("total_conversions", "Total conversions", "sum", "Sum of campaign conversions.", "conversions")],
    ),
    "inventory": _template(
        "inventory", "Inventory / Supply Chain", "Track stock quantities and inventory movements by SKU and warehouse.",
        [_field("sku", "SKU", FieldKind.TEXT), _field("warehouse", "Warehouse", FieldKind.TEXT), _field("quantity", "Quantity", FieldKind.NUMBER), _field("movement_type", "Movement type", FieldKind.TEXT), _field("date", "Date", FieldKind.DATE)],
        [_metric("total_quantity", "Total quantity", "sum", "Sum of recorded quantities.", "quantity"), _metric("movement_count", "Movement count", "count", "Number of inventory movements.")],
    ),
    "operations": _template(
        "operations", "Operations / Project", "Track tasks, due dates, owners, statuses, and projects.",
        [_field("task_name", "Task name", FieldKind.TEXT), _field("status", "Status", FieldKind.TEXT), _field("due_date", "Due date", FieldKind.DATE), _field("owner", "Owner", FieldKind.TEXT), _field("project", "Project", FieldKind.TEXT)],
        [_metric("task_count", "Task count", "count", "Number of tasks.")],
    ),
    "support": _template(
        "support", "Customer Support / Helpdesk", "Track support tickets by category, priority, status, and opening time.",
        [_field("ticket_id", "Ticket ID", FieldKind.TEXT), _field("category", "Category", FieldKind.TEXT), _field("priority", "Priority", FieldKind.TEXT), _field("status", "Status", FieldKind.TEXT), _field("opened_at", "Opened at", FieldKind.DATE)],
        [_metric("ticket_count", "Ticket count", "count", "Number of support tickets.")],
    ),
    "education": _template(
        "education", "Education / Academic", "Track students, courses, grades, and terms.",
        [_field("student_id", "Student ID", FieldKind.TEXT), _field("course", "Course", FieldKind.TEXT), _field("grade", "Grade", FieldKind.NUMBER), _field("term", "Term", FieldKind.TEXT)],
        [_metric("average_grade", "Average grade", "average", "Average recorded grade.", "grade"), _metric("enrollment_count", "Enrollment count", "count", "Number of enrollment records.")],
    ),
    "generic": build_generic_template(),
}


def apply_template_overrides(template: DomainTemplate, overrides: Mapping[str, Mapping[str, str]]) -> DomainTemplate:
    """Apply only known, non-empty labels to a template copy."""

    field_ids = {item.id for item in template.fields}
    section_ids = {item.id for item in template.sections}
    metric_ids = {item.id for item in template.metrics}

    fields = [
        item.model_copy(update={"label": overrides.get("fields", {}).get(item.id, item.label)})
        if item.id in field_ids and overrides.get("fields", {}).get(item.id, "").strip()
        else item
        for item in template.fields
    ]
    sections = [
        item.model_copy(update={"title": overrides.get("sections", {}).get(item.id, item.title)})
        if item.id in section_ids and overrides.get("sections", {}).get(item.id, "").strip()
        else item
        for item in template.sections
    ]
    metrics = [
        item.model_copy(update={"label": overrides.get("metrics", {}).get(item.id, item.label)})
        if item.id in metric_ids and overrides.get("metrics", {}).get(item.id, "").strip()
        else item
        for item in template.metrics
    ]
    return template.model_copy(update={"fields": fields, "sections": sections, "metrics": metrics})


__all__ = [
    "DOMAIN_TEMPLATES",
    "DomainTemplate",
    "apply_template_overrides",
    "build_generic_template",
    "find_sensitive_labels",
]
