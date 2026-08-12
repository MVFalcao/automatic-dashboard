"""Strict contracts for audit events and operational measurements."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from automation.privacy.redaction import redact_payload


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LogEvent(_Strict):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    level: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR)$")
    event: str = Field(min_length=1, max_length=120)
    project_id: str | None = Field(default=None, max_length=160)
    run_id: str | None = Field(default=None, max_length=160)
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("details", mode="before")
    @classmethod
    def redact_details(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("Log details must be an object")
        return redact_payload(value)


class AuditEvent(_Strict):
    id: str = Field(default_factory=lambda: uuid4().hex, min_length=1, max_length=160)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    action: str = Field(min_length=1, max_length=120)
    actor: str = Field(default="system", min_length=1, max_length=160)
    project_id: str | None = Field(default=None, max_length=160)
    run_id: str | None = Field(default=None, max_length=160)
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("details", mode="before")
    @classmethod
    def redact_details(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("Audit details must be an object")
        return redact_payload(value)


class RunObservation(_Strict):
    run_id: str = Field(min_length=1, max_length=160)
    status: str = Field(min_length=1, max_length=40)
    started_at: datetime
    finished_at: datetime | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    freshness_at: datetime | None = None
    token_input: int = Field(default=0, ge=0)
    token_output: int = Field(default=0, ge=0)
    token_total: int = Field(default=0, ge=0)
    failure_class: str | None = Field(default=None, max_length=120)

