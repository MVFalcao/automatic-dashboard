"""Validated contracts shared by local setup workflows."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Language(StrEnum):
    ENGLISH = "en"
    PORTUGUESE = "pt"


class ReferenceFormat(StrEnum):
    EXCEL = "xlsx"
    PDF = "pdf"
    PNG = "png"
    JPEG = "jpeg"
    SVG = "svg"


class PopulationFormat(StrEnum):
    CSV = "csv"
    EXCEL = "xlsx"


class OutputFormat(StrEnum):
    WEB = "web"
    EXCEL = "xlsx"
    PDF = "pdf"


class Provider(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"
    GEMINI = "gemini"
    DEEPSEEK = "deepseek"


class SetupCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    languages: list[Language] = Field(
        default_factory=lambda: [Language.ENGLISH, Language.PORTUGUESE]
    )
    reference_formats: list[ReferenceFormat] = Field(
        default_factory=lambda: [
            ReferenceFormat.EXCEL,
            ReferenceFormat.PDF,
            ReferenceFormat.PNG,
            ReferenceFormat.JPEG,
            ReferenceFormat.SVG,
        ]
    )
    population_formats: list[PopulationFormat] = Field(
        default_factory=lambda: [PopulationFormat.CSV, PopulationFormat.EXCEL]
    )
    output_formats: list[OutputFormat] = Field(
        default_factory=lambda: [OutputFormat.WEB, OutputFormat.EXCEL, OutputFormat.PDF]
    )
    providers: list[Provider] = Field(
        default_factory=lambda: [
            Provider.CLAUDE,
            Provider.CODEX,
            Provider.GEMINI,
            Provider.DEEPSEEK,
        ]
    )
    local_only: bool = True
    scheduled_generation: bool = False


class ProjectConfig(BaseModel):
    """Persistable configuration; source/report values are intentionally absent."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    name: str = Field(min_length=1, max_length=120)
    language: Language
    outputs: list[OutputFormat] = Field(min_length=1)
    reference_is_confidential: bool
    approved_sections: list[str] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=list)
    terminology: dict[str, str] = Field(default_factory=dict)
