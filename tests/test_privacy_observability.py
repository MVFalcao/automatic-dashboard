from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from automation.connectors.client import ApiClient
from automation.connectors.models import ApiFieldMapping, ApiSourceConfig, DriftClass
from automation.drift.classifier import classify_schema_drift
from automation.drift.service import DriftDraftStore, create_draft
from automation.observability.logging import StructuredLogger
from automation.observability.models import AuditEvent
from automation.observability.store import ObservabilityStore
from automation.privacy import TemporaryFileGuard, build_minimal_prompt, redact_text
from automation.scheduling.models import PipelineArtifact, ScheduleDefinition, ScheduleFrequency
from automation.scheduling.runner import LocalPipelineRunner, PipelineExecution
from automation.scheduling.store import ScheduleStore
from automation.specification.models import (
    DashboardSpec,
    FieldDefinition,
    FieldKind,
    FieldMapping,
    LocalizationSpec,
    MetricDefinition as SpecMetricDefinition,
    OutputKind,
    OutputSpec,
    SectionKind,
    SectionSpec,
)
from automation.agent.client import HermesTaskRunner
from automation.agent.models import ProviderConnection, ProviderName, TaskCapability, TaskRequest, TokenEstimate, AuthMethod
from automation.agent.credentials import CredentialReference
from automation.agent.routing import ProviderRouter
from automation.metrics.engine import calculate_metric
from automation.metrics.models import MetricDefinition, MetricOperation
from pydantic import BaseModel, ConfigDict


def spec() -> DashboardSpec:
    return DashboardSpec(
        id="drift-demo", title="Demo", fields=[
            FieldDefinition(id="amount", label="Amount", kind=FieldKind.NUMBER),
        ], mappings=[FieldMapping(source_field="amount", target_field="amount", approved=True)],
        metrics=[SpecMetricDefinition(id="total", label="Total", operation="sum", field="amount", explanation="Adds amounts", approved=True)],
        sections=[SectionSpec(id="summary", title="Summary", kind=SectionKind.SUMMARY, metric_ids=["total"], order=0)],
        localization=LocalizationSpec(language="en", locale="en-US", timezone="UTC"),
        outputs=OutputSpec(enabled=[OutputKind.PDF]),
    )


def schedule(tmp_path: Path) -> ScheduleDefinition:
    return ScheduleDefinition(
        id="observed", project_id="project", project_directory=tmp_path / "project", name="Observed",
        frequency=ScheduleFrequency.DAILY, output_directory=tmp_path / "reports", outputs=["pdf"],
        project_non_confidential_confirmed=True, source_non_confidential_confirmed=True,
        approval_confirmed=True, approved_by="owner", enabled=True,
    )


def test_redaction_and_prompt_minimization_remove_secrets_and_records() -> None:
    assert "private-secret" not in redact_text("Authorization: Bearer private-secret", secrets=["private-secret"])
    payload = build_minimal_prompt({"total": 10}, {"row_count": 2}, records=[{"amount": 10, "email": "person@example.com"}], confidential_fields={"email"})
    assert "record_sample" not in payload
    assert "person@example.com" not in json.dumps(payload)


def test_temporary_guard_deletes_file_on_failure(tmp_path: Path) -> None:
    path = tmp_path / "confidential.csv"
    path.write_text("person@example.com", encoding="utf-8")
    with TemporaryFileGuard(path):
        assert path.exists()
    assert not path.exists()


def test_drift_classification_and_draft_preserve_approved_baseline() -> None:
    client = ApiClient()
    expected = client.inspect(ApiSourceConfig(id="source", name="Source", endpoint="https://example.test"), [{"amount": 1}])
    expected = expected.model_copy(update={"mappings": [ApiFieldMapping(source_path="amount", target_field="amount", confidence="high", explanation="approved", approved=True)]})
    actual = client.inspect(ApiSourceConfig(id="source", name="Source", endpoint="https://example.test"), [{"amount": "one", "new": 2}])
    events = classify_schema_drift(expected, actual)
    assert next(item for item in events if item.kind == "type_changed").classification is DriftClass.BLOCKING
    assert next(item for item in events if item.kind == "added_field").classification is DriftClass.SAFE
    draft = create_draft(spec(), events)
    assert draft.baseline.model_dump() == spec().model_dump()
    draft.proposed.title = "Mutated draft"
    assert draft.baseline.title == "Demo"
    store = DriftDraftStore()
    assert store.get(store.create(draft).id).requires_approval


def test_structured_logs_and_sqlite_audit_redact_values(tmp_path: Path) -> None:
    log_path = tmp_path / "events.jsonl"
    logger = StructuredLogger(log_path)
    logger.emit("source_checked", details={"email": "person@example.com", "api_key": "private-secret"}, secrets=["private-secret"])
    text = log_path.read_text(encoding="utf-8")
    assert "person@example.com" not in text and "private-secret" not in text
    store = ObservabilityStore(tmp_path / "observability.sqlite3")
    store.record_audit(AuditEvent(action="approval", project_id="project", details={"email": "person@example.com"}))
    raw = (tmp_path / "observability.sqlite3").read_bytes()
    assert b"person@example.com" not in raw
    assert store.list_audit()[0].action == "approval"


def test_schedule_records_duration_and_run_audit(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path / "schedule.sqlite3")
    store.create_schedule(schedule(tmp_path))
    runner = LocalPipelineRunner(store, lambda _: PipelineExecution(
        artifacts=[PipelineArtifact(output="pdf", filename="report.pdf", content=b"deterministic")],
        freshness_at=datetime(2026, 1, 1, tzinfo=timezone.utc), token_input=12, token_output=4, provider="fake",
    ))
    result = runner.run("observed", scheduled_for=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert result.duration_seconds is not None and result.token_input == 12
    assert result.freshness_at is not None and result.provider == "fake"
    assert {event.action for event in store.list_audit()} >= {"run_started", "run_succeeded"}


def test_optional_hermes_failure_does_not_block_deterministic_work() -> None:
    class Narrative(BaseModel):
        model_config = ConfigDict(extra="forbid")
        summary: str

    connection = ProviderConnection(
        provider=ProviderName.GEMINI, account_id="local", model="fake", auth_method=AuthMethod.API_KEY,
        credential=CredentialReference(service="dashboard", account="fake"),
        capabilities={TaskCapability.STRUCTURED_OUTPUT}, token_estimate=TokenEstimate(input_tokens=1, output_tokens=1),
    )
    class FailingTransport:
        def submit(self, payload):
            raise RuntimeError("provider unavailable")

    optional = HermesTaskRunner(ProviderRouter([connection]), FailingTransport()).execute_optional(
        TaskRequest(task_id="narrative", task="summarize", required_capabilities={TaskCapability.STRUCTURED_OUTPUT}),
        Narrative,
    )
    assert optional is None
    result = calculate_metric([{"amount": 2}, {"amount": 3}], MetricDefinition(id="total", operation=MetricOperation.SUM, field="amount", approved=True))
    assert result.value == 5  # deterministic report calculations remain independent
