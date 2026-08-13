"""In-memory draft approval with explicit dependency propagation."""

from __future__ import annotations

from copy import deepcopy
import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4

from automation.approval.models import (
    ApprovalPackage,
    ApprovalStatus,
    CreateApprovalRequest,
    SectionApproval,
)
from automation.observability.models import AuditEvent


def _validate_dependencies(section_ids: set[str], dependencies: dict[str, list[str]]) -> None:
    for section_id, required in dependencies.items():
        if section_id not in section_ids:
            raise ValueError(f"Unknown section dependency target: {section_id}")
        unknown = set(required) - section_ids
        if unknown:
            raise ValueError(f"Unknown dependency for {section_id}: {sorted(unknown)[0]}")
        if section_id in required:
            raise ValueError(f"Section {section_id} cannot depend on itself")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(section_id: str) -> None:
        if section_id in visiting:
            raise ValueError("Section dependencies contain a cycle")
        if section_id in visited:
            return
        visiting.add(section_id)
        for dependency in dependencies.get(section_id, []):
            visit(dependency)
        visiting.remove(section_id)
        visited.add(section_id)

    for section_id in section_ids:
        visit(section_id)


class ApprovalStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(os.environ.get("DASHBOARD_APPROVAL_STATE", Path(tempfile.gettempdir()) / "universal-dashboard-agent" / "approvals.json"))
        self._packages: dict[UUID, ApprovalPackage] = {}
        self._audit: list[AuditEvent] = []
        self._lock = RLock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            packages = [ApprovalPackage.model_validate(item) for item in payload.get("packages", [])]
            self._packages = {item.approval_id: item for item in packages}
            self._audit = [AuditEvent.model_validate(item) for item in payload.get("audit", [])]
        except (OSError, ValueError, TypeError):
            self._packages, self._audit = {}, []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        packages = []
        for item in self._packages.values():
            sanitized = item.model_dump(mode="json")
            for section in sanitized["sections"].values():
                section["feedback"] = None
            packages.append(sanitized)
        payload = {
            "schema_version": 1,
            "packages": packages,
            "audit": [item.model_dump(mode="json") for item in self._audit],
        }
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".approvals-", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def create(self, request: CreateApprovalRequest) -> ApprovalPackage:
        section_ids = {section.id for section in request.draft_schema.sections}
        _validate_dependencies(section_ids, request.dependencies)
        package = ApprovalPackage(
            approval_id=uuid4(),
            draft_schema=request.draft_schema,
            sections={
                section_id: SectionApproval(
                    section_id=section_id,
                    depends_on=request.dependencies.get(section_id, []),
                )
                for section_id in section_ids
            },
        )
        with self._lock:
            self._packages[package.approval_id] = package
            self._audit.append(AuditEvent(action="approval_created", details={"approval_id": str(package.approval_id), "section_count": len(package.sections)}))
            self._save()
        return deepcopy(package)

    def get(self, approval_id: UUID) -> ApprovalPackage:
        with self._lock:
            package = self._packages.get(approval_id)
            if package is None:
                raise KeyError(approval_id)
            return deepcopy(package)

    def decide(
        self,
        approval_id: UUID,
        section_id: str,
        *,
        approve: bool,
        feedback: str | None,
    ) -> ApprovalPackage:
        with self._lock:
            package = self._packages.get(approval_id)
            if package is None:
                raise KeyError(approval_id)
            section = package.sections.get(section_id)
            if section is None:
                raise ValueError(f"Unknown section: {section_id}")
            if section.status == ApprovalStatus.BLOCKED:
                raise ValueError(f"Section {section_id} is blocked by a rejected dependency")

            section.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
            section.feedback = feedback
            self._refresh(package)
            self._audit.append(AuditEvent(action="section_decided", details={
                "approval_id": str(approval_id), "section_id": section_id, "decision": section.status.value,
            }))
            self._save()
            return deepcopy(package)

    def audit_history(self, *, approval_id: UUID | None = None) -> list[AuditEvent]:
        with self._lock:
            events = list(self._audit)
        if approval_id:
            marker = str(approval_id)
            events = [event for event in events if event.details.get("approval_id") == marker]
        return events

    @staticmethod
    def _refresh(package: ApprovalPackage) -> None:
        rejected = {
            section_id
            for section_id, section in package.sections.items()
            if section.status == ApprovalStatus.REJECTED
        }
        for section in package.sections.values():
            if section.status in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}:
                continue
            section.status = (
                ApprovalStatus.BLOCKED
                if rejected.intersection(section.depends_on)
                else ApprovalStatus.PENDING
            )
        package.ready_to_activate = bool(package.sections) and all(
            section.status == ApprovalStatus.APPROVED
            for section in package.sections.values()
        )


approval_store = ApprovalStore()
