"""Contracts for reviewable dashboard schema approval."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from automation.discovery.models import DraftDashboardSchema


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    BLOCKED = "blocked"


class SectionApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    depends_on: list[str] = Field(default_factory=list)
    feedback: str | None = Field(default=None, max_length=4_000)


class ApprovalPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: UUID
    draft_schema: DraftDashboardSchema
    sections: dict[str, SectionApproval]
    ready_to_activate: bool = False


class CreateApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_schema: DraftDashboardSchema
    dependencies: dict[str, list[str]] = Field(default_factory=dict)


class SectionDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approve: bool
    feedback: str | None = Field(default=None, max_length=4_000)
