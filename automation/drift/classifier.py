"""Conservative, deterministic schema-drift classification."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from automation.connectors.models import ApiInspection, DriftClass, SchemaDriftEvent


def _approved_paths(inspection: ApiInspection) -> set[str]:
    return {item.source_path for item in inspection.mappings if item.approved}


def classify_schema_drift(expected: ApiInspection, actual: ApiInspection) -> list[SchemaDriftEvent]:
    """Compare inspections and classify only changes that could affect reports.

    Unmapped additive fields are safe.  Changes to an approved mapping or a
    missing/type-changed field are blocking because publishing could silently
    alter an approved calculation.  Other changes require a new draft review.
    """

    old = {field.path: field for field in expected.fields}
    new = {field.path: field for field in actual.fields}
    approved = _approved_paths(expected)
    events: list[SchemaDriftEvent] = []
    for path in sorted(new.keys() - old.keys()):
        events.append(SchemaDriftEvent(
            path=path,
            kind="added_field",
            classification=DriftClass.REVIEW_REQUIRED if path in approved else DriftClass.SAFE,
            detail=(f"The API added field {path}; it is not used by the approved dashboard."
                    if path not in approved else
                    f"The API added mapped field {path}; review the dashboard mapping before use."),
        ))
    for path in sorted(old.keys() - new.keys()):
        classification = DriftClass.BLOCKING if path in approved or old[path].nullable is False else DriftClass.REVIEW_REQUIRED
        events.append(SchemaDriftEvent(
            path=path,
            kind="removed_field",
            classification=classification,
            detail=f"The approved API field {path} is missing from the response.",
        ))
    for path in sorted(new.keys() & old.keys()):
        if old[path].type != new[path].type:
            classification = DriftClass.BLOCKING if path in approved else DriftClass.REVIEW_REQUIRED
            events.append(SchemaDriftEvent(
                path=path,
                kind="type_changed",
                classification=classification,
                detail=f"Field {path} changed from {old[path].type} to {new[path].type}.",
            ))
    # A mapping target can disappear even when the source field is present.
    actual_paths = set(new)
    for mapping in expected.mappings:
        if mapping.approved and mapping.source_path not in actual_paths:
            if not any(event.path == mapping.source_path for event in events):
                events.append(SchemaDriftEvent(
                    path=mapping.source_path,
                    kind="approved_mapping_invalid",
                    classification=DriftClass.BLOCKING,
                    detail=f"The approved mapping for {mapping.source_path} can no longer be applied.",
                ))
    return sorted(events, key=lambda event: (event.path, event.kind))


def classify_category_drift(
    expected_values: Mapping[str, Iterable[str]],
    actual_values: Mapping[str, Iterable[str]],
    *,
    approved_values: Mapping[str, Iterable[str]] | None = None,
) -> list[SchemaDriftEvent]:
    """Classify newly observed categorical values without assuming a domain."""

    approved = {field: set(values) for field, values in (approved_values or {}).items()}
    events: list[SchemaDriftEvent] = []
    for field in sorted(set(expected_values) | set(actual_values)):
        old = set(expected_values.get(field, ()))
        new = set(actual_values.get(field, ()))
        for value in sorted(new - old):
            if field in approved and value not in approved[field]:
                classification = DriftClass.REVIEW_REQUIRED
            else:
                classification = DriftClass.SAFE
            events.append(SchemaDriftEvent(
                path=field,
                kind="new_category",
                classification=classification,
                detail=f"A new value appeared for {field}; review whether the approved dashboard should include it.",
            ))
    return events


def highest_classification(events: Iterable[SchemaDriftEvent]) -> DriftClass | None:
    values = list(events)
    if not values:
        return None
    rank = {DriftClass.SAFE: 0, DriftClass.REVIEW_REQUIRED: 1, DriftClass.BLOCKING: 2}
    return max((event.classification for event in values), key=lambda value: rank[value])
