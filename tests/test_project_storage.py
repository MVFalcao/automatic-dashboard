from pathlib import Path

from dashboard.api.models import Language, OutputFormat, ProjectConfig, SetupCapabilities
from dashboard.api.storage import save_project_config


def test_capabilities_match_confirmed_first_release() -> None:
    capabilities = SetupCapabilities()

    assert set(capabilities.languages) == {Language.ENGLISH, Language.PORTUGUESE}
    assert capabilities.local_only is True
    assert capabilities.scheduled_generation is True
    assert "csv" in capabilities.population_formats
    assert "pdf" in capabilities.output_formats


def test_small_project_configuration_is_saved_as_yaml(tmp_path: Path) -> None:
    config = ProjectConfig(
        name="Monthly Operations",
        language=Language.ENGLISH,
        outputs=[OutputFormat.WEB, OutputFormat.PDF],
        reference_is_confidential=False,
    )

    destination = save_project_config(tmp_path, config)

    assert destination == tmp_path / "monthly-operations" / "project.yaml"
    assert "Monthly Operations" in destination.read_text(encoding="utf-8")


def test_project_config_rejects_source_values() -> None:
    allowed_fields = set(ProjectConfig.model_fields)

    assert "records" not in allowed_fields
    assert "source_data" not in allowed_fields
    assert "report_values" not in allowed_fields
