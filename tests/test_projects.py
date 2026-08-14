from pathlib import Path
from uuid import uuid4

from dashboard.api.models import Language, OutputFormat
from dashboard.api.projects import ProjectDefinition, ProjectRepository, get_project_workspace
from automation.specification.versioning import save_approved_spec
from test_dashboard_spec import valid_spec


def test_project_definition_round_trips_without_secrets(tmp_path: Path) -> None:
    project = ProjectDefinition(
        id=uuid4(), name="Example", language=Language.ENGLISH,
        outputs=[OutputFormat.WEB, OutputFormat.EXCEL], project_directory=tmp_path,
        source_ids=["source-1"], terminology={"amount": "Value"},
    )
    repository = ProjectRepository()
    repository.save(project)
    loaded = repository.load(tmp_path)
    assert loaded == project
    assert "secret" not in (tmp_path / "project.yaml").read_text(encoding="utf-8").casefold()


def test_project_registry_reopens_after_repository_restart_and_migrates(tmp_path: Path) -> None:
    registry = tmp_path / "state" / "projects.json"
    directory = (tmp_path / "legacy").resolve()
    directory.mkdir()
    (directory / "project.yaml").write_text("name: Legacy\nlanguage: en\noutputs: [web]\n", encoding="utf-8")
    first = ProjectRepository(registry)
    migrated = first.load(directory)
    assert migrated.schema_version == 2
    assert (directory / "project.yaml.pre-v2.bak").exists()
    second = ProjectRepository(registry)
    assert second.get(migrated.id) == migrated


def test_existing_project_workspace_reopens_active_specification(monkeypatch, tmp_path: Path) -> None:
    registry = tmp_path / "state" / "projects.json"
    directory = (tmp_path / "existing-project").resolve()
    repository = ProjectRepository(registry)
    project = ProjectDefinition(
        name="Existing project", language=Language.ENGLISH,
        outputs=[OutputFormat.WEB], project_directory=directory,
        active_specification_version=1, specification_versions=[1],
    )
    repository.save(project)
    save_approved_spec(directory, valid_spec(), approved_by="synthetic-user", approval_id="synthetic-approval")
    monkeypatch.setattr("dashboard.api.projects.project_repository", repository)

    workspace = get_project_workspace(project.id)

    assert workspace.project.name == "Existing project"
    assert workspace.specification.title == "Example Dashboard"
