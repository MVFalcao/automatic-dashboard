"""In-memory draft registry; approved specifications remain immutable on disk."""

from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Iterable

from automation.connectors.models import DriftClass, SchemaDriftEvent
from automation.drift.models import DriftDraft, DriftPreview
from automation.specification.models import DashboardSpec


def create_draft(
    baseline: DashboardSpec,
    events: Iterable[SchemaDriftEvent],
    *,
    proposed: DashboardSpec | None = None,
    base_version: int | None = None,
    record_count: int = 24,
) -> DriftDraft:
    changes = list(events)
    if not changes:
        raise ValueError("A drift draft requires at least one schema change")
    candidate = deepcopy(proposed or baseline)
    field_ids = {field.id for field in candidate.fields}
    metric_fields = {
        value
        for metric in candidate.metrics
        for value in (metric.field, metric.numerator_field, metric.denominator_field, metric.group_by)
        if value
    }
    affected = [section.id for section in candidate.sections if any(
        event.path in field_ids or event.path in metric_fields
        or event.path in {metric.id for metric in candidate.metrics}
        for event in changes
    )]
    warnings = [event.detail for event in changes if event.classification is not DriftClass.SAFE]
    return DriftDraft(
        specification_id=baseline.id,
        base_version=base_version,
        events=changes,
        baseline=deepcopy(baseline),
        proposed=candidate,
        preview=DriftPreview(record_count=record_count, affected_sections=sorted(set(affected)), warnings=warnings),
    )


class DriftDraftStore:
    def __init__(self) -> None:
        self._drafts: dict[str, DriftDraft] = {}
        self._lock = RLock()

    def create(self, draft: DriftDraft) -> DriftDraft:
        with self._lock:
            self._drafts[draft.id] = deepcopy(draft)
        return deepcopy(draft)

    def get(self, draft_id: str) -> DriftDraft:
        with self._lock:
            if draft_id not in self._drafts:
                raise KeyError(draft_id)
            return deepcopy(self._drafts[draft_id])

    def list(self, *, specification_id: str | None = None) -> list[DriftDraft]:
        with self._lock:
            drafts = list(self._drafts.values())
        if specification_id:
            drafts = [item for item in drafts if item.specification_id == specification_id]
        return deepcopy(drafts)
