"""Apply an explicitly approved import to caller-owned in-memory records."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import openpyxl

from automation.importing.inspector import SUPPORTED_SUFFIXES
from automation.importing.models import ImportApproval, ImportMode, ImportPlan, ImportResult


Record = dict[str, Any]


def _files(location: Path) -> list[Path]:
    if not location.exists():
        raise ValueError("The selected local data location does not exist")
    files = (
        sorted(p for p in location.iterdir() if p.is_file() and p.suffix.casefold() in SUPPORTED_SUFFIXES)
        if location.is_dir()
        else [location]
    )
    if not files or any(p.suffix.casefold() not in SUPPORTED_SUFFIXES for p in files):
        raise ValueError("Dashboard population supports local CSV and XLSX files only")
    return files


def _read_records(path: Path) -> list[Record]:
    if path.suffix.casefold() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            return [dict(row) for row in csv.DictReader(source)]
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True, keep_links=False)
    records: list[Record] = []
    try:
        for sheet in workbook.worksheets:
            rows = sheet.iter_rows(values_only=True)
            headers = [str(value).strip() if value is not None else "" for value in next(rows, ())]
            for row in rows:
                if any(value is not None and value != "" for value in row):
                    records.append({header: value for header, value in zip(headers, row, strict=False) if header})
    finally:
        workbook.close()
    return records


def _mapped(records: Iterable[Mapping[str, Any]], mappings: Mapping[str, str]) -> list[Record]:
    return [
        {target: record.get(source) for source, target in mappings.items()}
        for record in records
    ]


def apply_import(
    location: Path,
    inspection: ImportPlan,
    approval: ImportApproval,
    current_records: Iterable[Mapping[str, Any]] = (),
) -> tuple[list[Record], ImportResult]:
    """Return imported records and a value-free audit result; no implicit persistence."""
    if not approval.approved:
        raise ValueError("Import approval is required")
    if inspection.requires_relationship_confirmation and not approval.relationships_confirmed:
        raise ValueError("The relationship between source files must be confirmed")
    if approval.permit_persistence and approval.confidential_columns:
        raise ValueError("Confidential imported data cannot be persisted")
    if approval.mode is ImportMode.UPDATE and (
        not approval.update_identifier or not approval.update_identifier_confirmed
    ):
        raise ValueError("Update mode requires a confirmed update identifier")
    inspected_columns = {column for source in inspection.sources for column in source.columns}
    proposed_targets = {
        mapping.source_column: mapping.target_field
        for mapping in inspection.mappings
        if mapping.target_field is not None
    }
    if not approval.mappings or any(source not in inspected_columns for source in approval.mappings):
        raise ValueError("Approved mappings must refer to inspected source columns")
    if any(proposed_targets.get(source) != target for source, target in approval.mappings.items()):
        raise ValueError("A changed field mapping requires a new inspection and approval")
    if len(set(approval.mappings.values())) != len(approval.mappings):
        raise ValueError("Multiple source columns cannot map to the same target field")
    if approval.update_identifier and approval.update_identifier not in approval.mappings.values():
        raise ValueError("The update identifier must be an approved target field")
    if approval.permit_persistence:
        detected = {
            column: column in {
                detected_column
                for source in inspection.sources
                for detected_column in source.likely_confidential_columns
            }
            for column in inspected_columns
        }
        if set(approval.field_classifications) != inspected_columns:
            raise ValueError("Every inspected field requires an explicit confidentiality classification")
        effective = dict(detected)
        effective.update(approval.classification_overrides)
        if set(approval.classification_overrides) - inspected_columns:
            raise ValueError("Confidentiality overrides must refer to inspected fields")
        if approval.field_classifications != effective:
            raise ValueError("Field classifications must match detection or an explicit override")
        if any(approval.field_classifications[column] for column in inspected_columns):
            raise ValueError("Confidential imported data cannot be persisted")

    raw = [record for path in _files(location) for record in _read_records(path)]
    incoming = _mapped(raw, approval.mappings)
    current = [dict(record) for record in current_records]
    inserted = updated = skipped = 0

    if approval.mode is ImportMode.REPLACE:
        output = incoming
        inserted = len(incoming)
    elif approval.mode is ImportMode.APPEND:
        output = current + incoming
        inserted = len(incoming)
    else:
        identifier = approval.update_identifier
        assert identifier is not None
        index = {record.get(identifier): position for position, record in enumerate(current) if record.get(identifier) not in (None, "")}
        output = current
        for record in incoming:
            key = record.get(identifier)
            if key in (None, ""):
                skipped += 1
            elif key in index:
                output[index[key]] = record
                updated += 1
            else:
                index[key] = len(output)
                output.append(record)
                inserted += 1

    result = ImportResult(
        mode=approval.mode,
        source_rows=len(incoming),
        output_rows=len(output),
        inserted_rows=inserted,
        updated_rows=updated,
        skipped_rows=skipped,
        validation_issues=list(inspection.validation_issues),
        persisted=approval.permit_persistence,
    )
    return output, result
