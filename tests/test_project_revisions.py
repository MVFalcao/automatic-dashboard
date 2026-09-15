from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from automation.approval.service import ApprovalStore
from automation.specification.versioning import load_active_spec, save_approved_spec
from dashboard.api.projects import ProjectDefinition, ProjectRepository
from dashboard.api.models import Language, OutputFormat
from dashboard.api.revisions import (
    ProjectRevisionActivationRequest,
    ProjectRevisionRequest,
    activate_project_revision,
    create_project_revision,
    get_project_revision,
)
from test_dashboard_spec import valid_spec


class _Hermes:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def chat(self, **_: object) -> dict:
        self.calls += 1
        return {"choices": [{"message": {"content": json.dumps({
            "answer": "I reorganized the presentation and kept every approved calculation unchanged.",
            "specification": self.payload,
        })}}]}


def _project(tmp_path: Path) -> tuple[ProjectRepository, ProjectDefinition]:
    repository = ProjectRepository(tmp_path / "state" / "projects.json")
    directory = (tmp_path / "project").resolve()
    project = ProjectDefinition(
        name="Example",
        language=Language.ENGLISH,
        outputs=[OutputFormat.WEB],
        project_directory=directory,
        active_specification_version=1,
        specification_versions=[1],
        non_confidential_confirmed=True,
    )
    repository.save(project)
    save_approved_spec(directory, valid_spec(), approved_by="synthetic-user", approval_id="approval-1")
    return repository, project


def test_existing_project_revision_is_previewed_approved_and_activated(monkeypatch, tmp_path: Path) -> None:
    repository, project = _project(tmp_path)
    approvals = ApprovalStore(tmp_path / "state" / "approvals.json")
    proposal = valid_spec("Updated presentation").model_dump(mode="json")
    proposal["style"]["palette"] = ["#123456"]
    hermes = _Hermes(proposal)
    monkeypatch.setattr("dashboard.api.revisions.project_repository", repository)
    monkeypatch.setattr("dashboard.api.revisions.approval_store", approvals)
    monkeypatch.setattr("dashboard.api.revisions.managed_hermes.client", hermes)

    draft = create_project_revision(project.id, ProjectRevisionRequest(
        instruction="Use a compact navy presentation",
        instruction_non_confidential=True,
        mode="update",
    ))

    assert draft.preview.synthetic is True
    assert draft.hermes_response == "I reorganized the presentation and kept every approved calculation unchanged."
    assert draft.active_specification_unchanged is True
    assert load_active_spec(project.project_directory).title == "Example Dashboard"
    persisted = (project.project_directory / ".dashboard" / "metadata" / "revision-drafts" / f"{draft.id}.json").read_text(encoding="utf-8")
    assert "Use a compact navy presentation" not in persisted
    assert get_project_revision(project.id, draft.id).specification.title == "Updated presentation"

    for section_id in draft.approval.sections:
        approvals.decide(draft.approval.approval_id, section_id, approve=True, feedback=None)
    workspace = activate_project_revision(project.id, draft.id, ProjectRevisionActivationRequest(
        approved_by="local-user",
        confirmed_non_confidential=True,
    ))

    assert workspace.project.active_specification_version == 2
    assert workspace.specification.title == "Updated presentation"
    assert load_active_spec(project.project_directory).title == "Updated presentation"


def test_revision_rejects_changed_calculation_contract_after_one_retry(monkeypatch, tmp_path: Path) -> None:
    repository, project = _project(tmp_path)
    proposal = valid_spec().model_dump(mode="json")
    proposal["metrics"][0]["explanation"] = "A model-authored calculation change."
    hermes = _Hermes(proposal)
    monkeypatch.setattr("dashboard.api.revisions.project_repository", repository)
    monkeypatch.setattr("dashboard.api.revisions.approval_store", ApprovalStore(tmp_path / "state" / "approvals.json"))
    monkeypatch.setattr("dashboard.api.revisions.managed_hermes.client", hermes)

    with pytest.raises(HTTPException) as problem:
        create_project_revision(project.id, ProjectRevisionRequest(
            instruction="Re-create the layout",
            instruction_non_confidential=True,
            mode="recreate",
        ))

    assert problem.value.status_code == 422
    assert hermes.calls == 2
    assert load_active_spec(project.project_directory).metrics[0].explanation == "Adds every approved amount."


def test_revision_requires_non_confidential_instruction(monkeypatch, tmp_path: Path) -> None:
    repository, project = _project(tmp_path)
    monkeypatch.setattr("dashboard.api.revisions.project_repository", repository)

    with pytest.raises(HTTPException) as problem:
        create_project_revision(project.id, ProjectRevisionRequest(
            instruction="Change the dashboard",
            instruction_non_confidential=False,
        ))

    assert problem.value.status_code == 409
