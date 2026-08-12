"""Validated contracts for local schedules and their run history.

The models deliberately contain no source records or credentials.  A schedule
points at a project and a local destination; the pipeline responsible for
producing report bytes is injected into :class:`LocalPipelineRunner`.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScheduleFrequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CRON = "cron"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"
    SKIPPED = "skipped"


class ScheduleDefinition(StrictModel):
    """A secret-free, local report schedule.

    ``project_non_confidential_confirmed`` and
    ``source_non_confidential_confirmed`` are separate on purpose: a project
    may be safe while a newly connected source is not.  Both confirmations and
    ``approval_confirmed`` are required before activation.
    """

    id: str = Field(default_factory=lambda: uuid4().hex, min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    project_id: str = Field(min_length=1, max_length=160)
    project_directory: Path
    name: str = Field(min_length=1, max_length=160)
    frequency: ScheduleFrequency
    timezone: str = Field(default="UTC", min_length=1, max_length=80)
    hour: int = Field(default=0, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    weekday: int | None = Field(default=None, ge=0, le=6, description="Monday=0 through Sunday=6")
    monthday: int | None = Field(default=None, ge=1, le=31)
    cron_expression: str | None = Field(default=None, max_length=200)
    output_directory: Path
    outputs: list[str] = Field(min_length=1, max_length=10)
    retention_limit: int = Field(default=10, ge=1, le=1000)
    project_non_confidential_confirmed: bool = False
    source_non_confidential_confirmed: bool = False
    approval_confirmed: bool = False
    approved_by: str | None = Field(default=None, max_length=160)
    enabled: bool = False
    notify_on_failure: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("outputs")
    @classmethod
    def output_names_are_safe(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Schedule outputs must be unique")
        if any(not item or len(item) > 40 for item in value):
            raise ValueError("Schedule output names must be non-empty")
        return value

    @model_validator(mode="after")
    def validate_frequency_and_approval(self) -> "ScheduleDefinition":
        if self.frequency is ScheduleFrequency.CRON:
            if not self.cron_expression:
                raise ValueError("Cron schedules require cron_expression")
            if self.weekday is not None or self.monthday is not None:
                raise ValueError("Cron schedules cannot include weekday or monthday")
        elif self.cron_expression:
            raise ValueError("cron_expression is only valid for cron schedules")
        if self.frequency is ScheduleFrequency.WEEKLY and self.weekday is None:
            raise ValueError("Weekly schedules require weekday")
        if self.frequency is not ScheduleFrequency.WEEKLY and self.weekday is not None:
            raise ValueError("weekday is only valid for weekly schedules")
        if self.frequency is ScheduleFrequency.MONTHLY and self.monthday is None:
            raise ValueError("Monthly schedules require monthday")
        if self.frequency is not ScheduleFrequency.MONTHLY and self.monthday is not None:
            raise ValueError("monthday is only valid for monthly schedules")
        if self.enabled and not self.can_activate:
            raise ValueError("Scheduling requires explicit non-confidential approval")
        if self.approval_confirmed and not self.approved_by:
            raise ValueError("An approval must identify who confirmed scheduling")
        return self

    @property
    def can_activate(self) -> bool:
        return (
            self.project_non_confidential_confirmed
            and self.source_non_confidential_confirmed
            and self.approval_confirmed
        )


class RunRecord(StrictModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    schedule_id: str
    idempotency_key: str
    status: RunStatus
    scheduled_for: datetime
    started_at: datetime
    finished_at: datetime | None = None
    artifact_set_id: str | None = None
    error: str | None = None
    notification_sent: bool = False
    duration_seconds: float | None = Field(default=None, ge=0)
    freshness_at: datetime | None = None
    token_input: int = Field(default=0, ge=0)
    token_output: int = Field(default=0, ge=0)
    provider: str | None = Field(default=None, max_length=80)


class ArtifactRecord(StrictModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    schedule_id: str
    run_id: str
    artifact_set_id: str
    output: str
    path: Path
    created_at: datetime
    size_bytes: int = Field(ge=0)


class PipelineArtifact(StrictModel):
    """Bytes produced by a deterministic report pipeline for one output."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    output: str = Field(min_length=1, max_length=40)
    filename: str = Field(min_length=1, max_length=180)
    content: bytes = Field(min_length=1)

    @field_validator("filename")
    @classmethod
    def filename_is_single_component(cls, value: str) -> str:
        candidate = Path(value)
        if candidate.name != value or value in {".", ".."}:
            raise ValueError("Artifact filename must be a single local filename")
        return value
