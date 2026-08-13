from pathlib import Path
from uuid import uuid4

from dashboard.api.models import Language, OutputFormat
from dashboard.api.projects import ProjectDefinition, ProjectRepository


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
