"""Coverage for the real production pipeline orchestrator (Step 17/19).

``ProductionPipelineExecutor`` wires together source sync, the schema-drift
gate, report-document construction, and multi-output rendering.  It was
previously only exercised through ``tests/test_scheduling.py``, which stubs
the executor out entirely — so this file drives the real implementation.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from automation.connectors.client import ApiClient
from automation.connectors.models import ApiSourceConfig, PaginationConfig, PaginationKind
from automation.persistence.workflow import (
    ApiSourceApprovalRecord,
    ApiSourceInspectionRecord,
    ProjectWorkflowRepository,
    canonical_checksum,
)
from automation.pipeline.executor import ProductionPipelineExecutor
from automation.scheduling.models import ScheduleDefinition, ScheduleFrequency
from automation.scheduling.runner import PipelineExecution
from automation.specification.models import OutputKind
from automation.specification.versioning import save_approved_spec
from dashboard.api.models import Language, OutputFormat
from dashboard.api.projects import ProjectDefinition, ProjectRepository
from test_dashboard_spec import valid_spec


def _handler(records: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=records, headers={"content-type": "application/json"})
    return handler


def _source(**overrides) -> ApiSourceConfig:
    values = {"id": "source", "name": "Source", "endpoint": "https://api.example.test/records"}
    values.update(overrides)
    return ApiSourceConfig(**values)


def _spec_with_outputs(*outputs: OutputKind):
    spec = valid_spec()
    payload = spec.model_dump(mode="json")
    payload["outputs"]["enabled"] = [output.value for output in outputs]
    return type(spec).model_validate(payload)


def _setup_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    spec=None,
    with_source: bool = True,
    with_spec: bool = True,
    pagination: PaginationConfig | None = None,
    inspect_sample: dict | None = None,
) -> tuple[ProjectDefinition, Path]:
    monkeypatch.setenv("DASHBOARD_PROJECT_REGISTRY", str(tmp_path / "state" / "registry.json"))
    directory = (tmp_path / "project").resolve()
    project_repository = ProjectRepository(tmp_path / "state" / "projects.json")

    active_source_id = active_inspection_id = active_approval_id = None
    if with_source:
        api_source = _source(**({"pagination": pagination} if pagination else {}))
        workflow = ProjectWorkflowRepository(directory)
        workflow.save_source(api_source)
        sample = inspect_sample or {"category": "A", "amount": 10, "note": "hello"}
        inspection = ApiClient(transport=None).inspect(api_source, [sample])

        project_id = uuid4()
        inspection_record = ApiSourceInspectionRecord(
            project_id=project_id, source_id=api_source.id,
            source_checksum=canonical_checksum(api_source),
            inspection_checksum=canonical_checksum(inspection),
            inspection=inspection,
        )
        workflow.save_inspection(inspection_record)

        fields = {field.path for field in inspection.fields}
        approval_record = ApiSourceApprovalRecord(
            project_id=project_id, source_id=api_source.id, inspection_id=inspection_record.id,
            source_checksum=inspection_record.source_checksum, inspection_checksum=inspection_record.inspection_checksum,
            mappings={"category": "category", "amount": "amount"},
            field_classifications={path: False for path in fields},
            approved_by="local-user",
        )
        workflow.save_approval(approval_record)
        active_source_id, active_inspection_id, active_approval_id = api_source.id, inspection_record.id, approval_record.id
    else:
        project_id = uuid4()

    project = ProjectDefinition(
        id=project_id,
        name="Example",
        language=Language.ENGLISH,
        outputs=[OutputFormat.PDF],
        project_directory=directory,
        active_specification_version=1 if with_spec else None,
        specification_versions=[1] if with_spec else [],
        non_confidential_confirmed=True,
        active_source_id=active_source_id,
        active_source_inspection_id=active_inspection_id,
        active_source_approval_id=active_approval_id,
    )
    project_repository.save(project)
    if with_spec:
        save_approved_spec(directory, spec or valid_spec(), approved_by="synthetic-user", approval_id="approval-1")
    return project, directory


def _schedule(project: ProjectDefinition, directory: Path, tmp_path: Path, **overrides) -> ScheduleDefinition:
    values = {
        "id": "schedule-1",
        "project_id": str(project.id),
        "project_directory": directory,
        "name": "Daily report",
        "frequency": ScheduleFrequency.DAILY,
        "timezone": "America/Sao_Paulo",
        "hour": 9,
        "minute": 30,
        "output_directory": tmp_path / "reports",
        "outputs": ["pdf"],
        "project_non_confidential_confirmed": True,
        "source_non_confidential_confirmed": True,
        "approval_confirmed": True,
        "approved_by": "owner",
        "enabled": True,
    }
    values.update(overrides)
    return ScheduleDefinition(**values)


def test_happy_path_builds_document_and_renders_selected_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, directory = _setup_project(tmp_path, monkeypatch)
    handler = _handler([{"category": "A", "amount": 10, "note": "hello"}])
    executor = ProductionPipelineExecutor(api_client=ApiClient(transport=httpx.MockTransport(handler)))

    loaded_project, source, sync, document = executor.build_document(directory)

    assert loaded_project.id == project.id
    assert source.id == "source"
    assert sync.complete is True
    assert sync.schema_drift == []
    assert document.metrics == {"total": 10}

    schedule = _schedule(project, directory, tmp_path, outputs=["pdf"])
    execution = executor(schedule)

    assert isinstance(execution, PipelineExecution)
    assert [artifact.output for artifact in execution.artifacts] == ["pdf"]
    assert execution.artifacts[0].content.startswith(b"%PDF")
    assert execution.freshness_at is not None
    assert execution.metrics == {"total": 10}
    assert execution.pending_checkpoint_source_id == "source"
    assert execution.project_id == str(project.id)
    assert execution.project_directory == directory


def test_schema_drift_requires_review_and_persists_draft(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, directory = _setup_project(tmp_path, monkeypatch)
    # "note" was a string at inspection time; a live type change is unapproved
    # drift and is always classified as review-required (never auto-blocked).
    handler = _handler([{"category": "A", "amount": 10, "note": 42}])
    executor = ProductionPipelineExecutor(api_client=ApiClient(transport=httpx.MockTransport(handler)))

    with pytest.raises(RuntimeError, match="Schema drift requires review"):
        executor.build_document(directory)

    drift_dir = directory / ".dashboard" / "metadata" / "drift-drafts"
    drafts = list(drift_dir.glob("*.json"))
    assert len(drafts) == 1
    payload = json.loads(drafts[0].read_text(encoding="utf-8"))
    assert payload["classification"] == "review_required"
    assert any(change["path"] == "note" for change in payload["changes"])

    reloaded = ProjectRepository(tmp_path / "state" / "projects.json").load(directory)
    assert drafts[0].stem in reloaded.drift_draft_ids


def test_no_active_specification_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _project, directory = _setup_project(tmp_path, monkeypatch, with_spec=False)
    executor = ProductionPipelineExecutor(api_client=ApiClient(transport=httpx.MockTransport(_handler([]))))

    with pytest.raises(RuntimeError, match="no active approved specification"):
        executor.build_document(directory)


def test_no_active_source_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _project, directory = _setup_project(tmp_path, monkeypatch, with_source=False)
    executor = ProductionPipelineExecutor(api_client=ApiClient(transport=httpx.MockTransport(_handler([]))))

    with pytest.raises(RuntimeError, match="no active approved source"):
        executor.build_document(directory)


def test_schedule_project_mismatch_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, directory = _setup_project(tmp_path, monkeypatch)
    handler = _handler([{"category": "A", "amount": 10, "note": "hello"}])
    executor = ProductionPipelineExecutor(api_client=ApiClient(transport=httpx.MockTransport(handler)))
    schedule = _schedule(project, directory, tmp_path, project_id="a-different-project")

    with pytest.raises(RuntimeError, match="Schedule project association is invalid"):
        executor(schedule)


def test_schedule_output_not_enabled_by_specification_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, directory = _setup_project(tmp_path, monkeypatch, spec=_spec_with_outputs(OutputKind.PDF))
    handler = _handler([{"category": "A", "amount": 10, "note": "hello"}])
    executor = ProductionPipelineExecutor(api_client=ApiClient(transport=httpx.MockTransport(handler)))
    schedule = _schedule(project, directory, tmp_path, outputs=["xlsx"])

    with pytest.raises(RuntimeError, match="not enabled by the active specification"):
        executor(schedule)


def test_incomplete_pagination_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pagination = PaginationConfig(kind=PaginationKind.PAGE, page_size=1, max_pages=1)
    _project, directory = _setup_project(tmp_path, monkeypatch, pagination=pagination)
    handler = _handler([{"category": "A", "amount": 10, "note": "hello"}])
    executor = ProductionPipelineExecutor(api_client=ApiClient(transport=httpx.MockTransport(handler)))

    with pytest.raises(RuntimeError, match="Source pagination did not complete"):
        executor.build_document(directory)
