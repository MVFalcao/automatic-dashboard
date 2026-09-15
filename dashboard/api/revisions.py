"""Approval-first Hermes revisions for an existing dashboard project."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from automation.agent.managed import managed_hermes
from automation.approval.models import ApprovalPackage, CreateApprovalRequest
from automation.approval.service import approval_store
from automation.discovery.models import Confidence, DraftDashboardSchema, FieldType, ProposedField, ProposedSection
from automation.persistence.workflow import ProjectWorkflowRepository, _atomic_json
from automation.privacy.redaction import redact_text
from automation.specification.models import DashboardSpec
from automation.specification.versioning import load_active_spec, save_approved_spec
from dashboard.api.dashboard_specs import DashboardRender, DashboardRenderRequest, render_dashboard
from dashboard.api.projects import ProjectWorkspace, project_repository


RevisionMode = Literal["update", "recreate"]


class ProjectRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(min_length=3, max_length=4_000)
    instruction_non_confidential: bool = False
    mode: RevisionMode = "update"


class ProjectRevisionActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_by: str = Field(min_length=1, max_length=160)
    confirmed_non_confidential: bool = False


class ProjectRevisionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    id: str = Field(default_factory=lambda: uuid4().hex)
    project_id: UUID
    base_version: int = Field(ge=1)
    mode: RevisionMode
    hermes_response: str = Field(min_length=1, max_length=2_000)
    specification: DashboardSpec
    approval_id: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProjectRevisionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    project_id: UUID
    base_version: int
    mode: RevisionMode
    hermes_response: str
    specification: DashboardSpec
    approval: ApprovalPackage
    preview: DashboardRender
    active_specification_unchanged: bool = True


router = APIRouter(prefix="/api/projects", tags=["project-revisions"])


class HermesRevisionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=2_000)
    specification: DashboardSpec


def _workflow(project_directory) -> ProjectWorkflowRepository:
    return ProjectWorkflowRepository(project_directory)


def _approval_schema(specification: DashboardSpec, base_version: int) -> DraftDashboardSchema:
    return DraftDashboardSchema(
        source_format="hermes-project-revision",
        fields=[
            ProposedField(
                id=field.id,
                display_name=field.label,
                inferred_type=FieldType(field.kind.value),
                confidence=Confidence.HIGH,
                evidence=[f"Approved active specification v{base_version}"],
                requires_approval=False,
            )
            for field in specification.fields
        ],
        sections=[
            ProposedSection(
                id=section.id,
                display_name=section.title,
                source_section="Hermes revision proposal",
                presentation=section.kind.value,
                confidence=Confidence.MEDIUM,
            )
            for section in specification.sections
        ],
        assumptions=[
            "The preview contains synthetic values only.",
            "The active approved specification remains unchanged until every proposed section is approved.",
            "Approved fields, mappings, filters, and deterministic metric calculations were preserved.",
        ],
    )


def _protected_contract(specification: DashboardSpec) -> dict:
    payload = specification.model_dump(mode="json")
    return {
        key: payload[key]
        for key in ("schema_version", "id", "fields", "mappings", "metrics", "filters", "localization", "privacy", "outputs")
    }


def _validate_proposal(proposal: DashboardSpec, active: DashboardSpec) -> DashboardSpec:
    if _protected_contract(proposal) != _protected_contract(active):
        raise ValueError("Hermes changed the approved data or calculation contract")
    return proposal


def _hermes_proposal(active: DashboardSpec, payload: ProjectRevisionRequest) -> HermesRevisionProposal:
    client = managed_hermes.client
    if client is None:
        raise HTTPException(status_code=503, detail={
            "code": "provider_not_ready",
            "message": "Hermes is not ready. Connect the configured provider and restart the local agent runtime.",
            "fields": [{"field": "provider", "message": "A healthy Hermes runtime is required for dashboard revisions."}],
        })
    current = active.model_dump(mode="json")
    for attempt in range(2):
        message = {
            "instruction": (
                "Return one strict JSON object with answer and specification only. In answer, concisely explain what "
                "you changed and why, without repeating the user's instruction or including source values. The "
                "specification must be one complete DashboardSpec. Preserve schema_version, id, fields, mappings, "
                "metrics, filters, localization, privacy, and outputs exactly. You may change title, visualizations, "
                "sections, layout, terminology, and style. Preserve unspecified presentation choices when mode is "
                "update; propose a fresh presentation when mode is recreate. Never add or alter calculations."
            ),
            "mode": payload.mode,
            "user_request": payload.instruction,
            "current_specification": current,
            "repair_attempt": attempt == 1,
        }
        try:
            raw = client.chat(
                model="hermes-agent",
                messages=[{"role": "user", "content": json.dumps(message, ensure_ascii=False)}],
                response_format={"type": "json_object"},
            )
            content = raw["choices"][0]["message"]["content"]
            proposed = HermesRevisionProposal.model_validate_json(content) if isinstance(content, str) else HermesRevisionProposal.model_validate(content)
            specification = _validate_proposal(proposed.specification, active)
            answer = redact_text(proposed.answer).strip()
            if not answer:
                raise ValueError("Hermes returned an empty revision explanation")
            return proposed.model_copy(update={"answer": answer, "specification": specification})
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=503, detail={
                "code": "provider_unavailable",
                "message": "The configured provider could not complete the dashboard revision.",
                "fields": [{"field": "provider", "message": "Check the provider connection and try again."}],
            }) from exc
        except HTTPException:
            raise
        except Exception as exc:
            if attempt == 1:
                raise HTTPException(status_code=422, detail={
                    "code": "invalid_hermes_revision",
                    "message": "Hermes could not produce a valid dashboard revision after one retry. The active dashboard was not changed.",
                    "fields": [{"field": "instruction", "message": "Clarify the requested presentation change and try again."}],
                }) from exc
    raise AssertionError("unreachable")


def _response(record: ProjectRevisionRecord, project_directory) -> ProjectRevisionDraft:
    try:
        approval = approval_store.get(record.approval_id)
    except KeyError as exc:
        raise HTTPException(status_code=409, detail="The revision approval package is unavailable") from exc
    # _validate_proposal locks privacy (and the rest of the protected contract)
    # identical to the already-approved active specification, so this preview
    # never carries confidential shape beyond what was already approved.
    preview = render_dashboard(DashboardRenderRequest(
        specification=record.specification,
        record_count=24,
        authorize_confidential_display=True,
    ))
    return ProjectRevisionDraft(
        id=record.id,
        project_id=record.project_id,
        base_version=record.base_version,
        mode=record.mode,
        hermes_response=record.hermes_response,
        specification=record.specification,
        approval=approval,
        preview=preview,
    )


@router.post("/{project_id}/revisions", response_model=ProjectRevisionDraft, status_code=201)
def create_project_revision(project_id: UUID, payload: ProjectRevisionRequest) -> ProjectRevisionDraft:
    if not payload.instruction_non_confidential:
        raise HTTPException(status_code=409, detail="Confirm the instruction is non-confidential before sending it to Hermes")
    try:
        project = project_repository.get(project_id)
        if project.active_specification_version is None:
            raise FileNotFoundError
        active = load_active_spec(project.project_directory)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="The project does not have a readable active dashboard specification") from exc

    proposal = _hermes_proposal(active, payload)
    schema = _approval_schema(proposal.specification, project.active_specification_version)
    approval = approval_store.create(CreateApprovalRequest(
        draft_schema=schema,
        dependencies={section.id: section.depends_on for section in proposal.specification.sections},
    ))
    record = ProjectRevisionRecord(
        project_id=project.id,
        base_version=project.active_specification_version,
        mode=payload.mode,
        hermes_response=proposal.answer,
        specification=proposal.specification,
        approval_id=approval.approval_id,
    )
    repository = _workflow(project.project_directory)
    _atomic_json(repository._path("revision-drafts", record.id), record.model_dump(mode="json"))
    return _response(record, project.project_directory)


@router.get("/{project_id}/revisions/{revision_id}", response_model=ProjectRevisionDraft)
def get_project_revision(project_id: UUID, revision_id: str) -> ProjectRevisionDraft:
    try:
        project = project_repository.get(project_id)
        record = ProjectRevisionRecord.model_validate(_workflow(project.project_directory)._read("revision-drafts", revision_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project revision not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="The project revision is invalid") from exc
    if record.project_id != project_id:
        raise HTTPException(status_code=404, detail="Project revision not found")
    return _response(record, project.project_directory)


@router.post("/{project_id}/revisions/{revision_id}/activate", response_model=ProjectWorkspace)
def activate_project_revision(
    project_id: UUID,
    revision_id: str,
    payload: ProjectRevisionActivationRequest,
) -> ProjectWorkspace:
    try:
        project = project_repository.get(project_id)
        record = ProjectRevisionRecord.model_validate(_workflow(project.project_directory)._read("revision-drafts", revision_id))
        approval = approval_store.get(record.approval_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project revision not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="The project revision is invalid") from exc
    if record.project_id != project_id:
        raise HTTPException(status_code=404, detail="Project revision not found")
    if project.active_specification_version != record.base_version:
        raise HTTPException(status_code=409, detail="The active dashboard changed after this revision was created. Ask Hermes for a new revision.")
    if not approval.ready_to_activate:
        raise HTTPException(status_code=409, detail="Approve every proposed section before activating the revision")
    if not record.specification.privacy.confidential_fields and not payload.confirmed_non_confidential:
        raise HTTPException(status_code=409, detail="Non-confidential persistence requires explicit confirmation")
    metadata = save_approved_spec(
        project.project_directory,
        record.specification,
        approved_by=payload.approved_by,
        approval_id=str(record.approval_id),
    )
    updated = project_repository.save(project.model_copy(update={
        "active_specification_version": metadata.version,
        "specification_versions": sorted(set([*project.specification_versions, metadata.version])),
    }))
    return ProjectWorkspace(project=updated, specification=record.specification)
