"""Production deterministic pipeline used by on-demand and scheduled runs."""

from __future__ import annotations

from datetime import datetime, timezone

from automation.agent.credentials import KeyringCredentialStore
from automation.connectors.client import ApiClient
from automation.connectors.models import ApiSyncRequest, DriftClass
from automation.persistence.workflow import ProjectWorkflowRepository, _atomic_json
from automation.reports import build_report_document
from automation.reports.renderers import render_excel, render_html, render_pdf
from automation.scheduling.models import PipelineArtifact, ScheduleDefinition
from automation.scheduling.runner import PipelineExecution
from automation.specification.models import OutputKind
from automation.specification.versioning import load_spec_version
from dashboard.api.projects import ProjectRepository


class ProductionPipelineExecutor:
    """Fetch, validate, calculate, build once, and render selected outputs."""

    def __init__(self, api_client: ApiClient | None = None) -> None:
        if api_client is None:
            try:
                credentials = KeyringCredentialStore()
            except RuntimeError:
                credentials = None
            api_client = ApiClient(credentials)
        self.api_client = api_client

    def build_document(self, project_directory, *, specification_version: int | None = None, filter_values=None):
        project_repository = ProjectRepository()
        project = project_repository.load(project_directory)
        version = specification_version or project.active_specification_version
        if version is None:
            raise RuntimeError("Project has no active approved specification")
        if specification_version is not None and specification_version not in project.specification_versions and specification_version != project.active_specification_version:
            raise RuntimeError("The requested specification version is not approved for this project")
        if not (project.active_source_id and project.active_source_inspection_id and project.active_source_approval_id):
            raise RuntimeError("Project has no active approved source")
        workflow = ProjectWorkflowRepository(project.project_directory)
        source, inspection, approval = workflow.verify(
            project.id, project.active_source_id,
            project.active_source_inspection_id, project.active_source_approval_id,
        )
        specification = load_spec_version(project.project_directory, version)
        sync = self.api_client.sync(ApiSyncRequest(
            source=source,
            mode="incremental" if source.incremental_confirmed else "full",
            checkpoint=project.checkpoints.get(source.id),
            approved_mappings=approval.mappings,
            approval_confirmed=True,
            inspection_version=inspection.inspection_checksum,
        ), expected_inspection=inspection.inspection)
        if not sync.complete:
            raise RuntimeError("Source pagination did not complete")
        review = [item for item in sync.schema_drift if item.classification is DriftClass.REVIEW_REQUIRED]
        if review:
            draft = {
                "schema_version": 1,
                "id": datetime.now(timezone.utc).strftime("drift-%Y%m%dT%H%M%S%fZ"),
                "project_id": str(project.id),
                "source_id": source.id,
                "classification": "review_required",
                "changes": [item.model_dump(mode="json") for item in review],
                "synthetic_preview_required": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            _atomic_json(workflow._path("drift-drafts", draft["id"]), draft)
            project_repository.save(project.model_copy(update={"drift_draft_ids": [*project.drift_draft_ids, draft["id"]]}))
            raise RuntimeError("Schema drift requires review before publication")
        document = build_report_document(specification, sync.records, filter_values=filter_values)
        return project, source, sync, document

    def __call__(self, schedule: ScheduleDefinition) -> PipelineExecution:
        project, source, sync, document = self.build_document(schedule.project_directory)
        if str(project.id) != schedule.project_id:
            raise RuntimeError("Schedule project association is invalid")
        specification = document.specification
        renderers = {
            OutputKind.WEB.value: lambda: render_html(document).encode("utf-8"),
            OutputKind.EXCEL.value: lambda: render_excel(document),
            OutputKind.PDF.value: lambda: render_pdf(document),
        }
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        suffix = {"web": "html", "xlsx": "xlsx", "pdf": "pdf"}
        artifacts: list[PipelineArtifact] = []
        for output in schedule.outputs:
            if output not in renderers or output not in {item.value for item in specification.outputs.enabled}:
                raise RuntimeError("Schedule selected an output not enabled by the active specification")
            artifacts.append(PipelineArtifact(
                output=output,
                filename=f"dashboard-{project.id.hex[:8]}-{stamp}.{suffix[output]}",
                content=renderers[output](),
            ))
        freshness = max((item.fetched_at for item in sync.provenance), default=None)
        return PipelineExecution(
            artifacts=artifacts, freshness_at=freshness,
            pending_checkpoint_source_id=source.id,
            pending_checkpoint=sync.next_checkpoint,
            project_id=str(project.id), project_directory=project.project_directory,
        )
