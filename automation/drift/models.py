"""Reviewable drift and preview contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from automation.connectors.models import DriftClass, SchemaDriftEvent
from automation.specification.models import DashboardSpec


class DraftStatus(StrEnum):
    PREVIEW = "preview"
    APPROVED = "approved"
    REJECTED = "rejected"


class DriftPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    synthetic: bool = True
    record_count: int = Field(default=24, ge=1, le=500)
    affected_sections: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DriftDraft(BaseModel):
    """Immutable reference to the approved baseline and a proposed revision."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: uuid4().hex, min_length=1, max_length=160)
    specification_id: str = Field(min_length=1, max_length=160)
    base_version: int | None = Field(default=None, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: DraftStatus = DraftStatus.PREVIEW
    events: list[SchemaDriftEvent] = Field(min_length=1)
    baseline: DashboardSpec
    proposed: DashboardSpec
    preview: DriftPreview
    requires_approval: bool = True

    @property
    def classification(self) -> DriftClass:
        rank = {DriftClass.SAFE: 0, DriftClass.REVIEW_REQUIRED: 1, DriftClass.BLOCKING: 2}
        return max((event.classification for event in self.events), key=lambda value: rank[value])
