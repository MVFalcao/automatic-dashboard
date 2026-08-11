"""Permission-aware structural analysis for Excel dashboard samples."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.cell.cell import Cell

from automation.discovery.models import (
    Confidence,
    FieldEvidence,
    FieldType,
    SampleManifest,
    SectionEvidence,
)


def _value_type(value: Any) -> FieldType:
    if isinstance(value, bool):
        return FieldType.BOOLEAN
    if isinstance(value, datetime):
        return FieldType.DATETIME
    if isinstance(value, date):
        return FieldType.DATE
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return FieldType.NUMBER
    if isinstance(value, str):
        return FieldType.TEXT
    return FieldType.UNKNOWN


def _header_row(sheet: openpyxl.worksheet.worksheet.Worksheet) -> int | None:
    candidates: list[tuple[int, int]] = []
    for row_number in range(1, min(sheet.max_row, 20) + 1):
        text_cells = sum(
            1
            for cell in sheet[row_number]
            if isinstance(cell.value, str) and cell.value and not cell.value.startswith("=")
        )
        candidates.append((text_cells, row_number))
    count, row_number = max(candidates, default=(0, 0))
    return row_number if count >= 2 else None


def _infer_fields(
    sheet: openpyxl.worksheet.worksheet.Worksheet,
    header_row: int,
) -> list[FieldEvidence]:
    fields: list[FieldEvidence] = []
    for column in range(1, sheet.max_column + 1):
        header = sheet.cell(header_row, column).value
        if not isinstance(header, str) or not header.strip() or header.startswith("="):
            continue
        observed: list[FieldType] = []
        for row in range(header_row + 1, min(sheet.max_row, header_row + 50) + 1):
            value = sheet.cell(row, column).value
            if value is None or (isinstance(value, str) and value.startswith("=")):
                continue
            observed.append(_value_type(value))
        counts = Counter(observed)
        inferred = counts.most_common(1)[0][0] if counts else FieldType.UNKNOWN
        confidence = Confidence.HIGH if observed and counts[inferred] == len(observed) else Confidence.MEDIUM
        if not observed:
            confidence = Confidence.LOW
        fields.append(
            FieldEvidence(
                name=header.strip(),
                source_location=f"{sheet.title}!{sheet.cell(header_row, column).coordinate}",
                inferred_type=inferred,
                confidence=confidence,
                non_empty_samples=len(observed),
            )
        )
    return fields


def _has_formula(cell: Cell) -> bool:
    return cell.data_type == "f" or (
        isinstance(cell.value, str) and cell.value.startswith("=")
    )


def analyze_excel(path: Path, *, permit_data_extraction: bool) -> SampleManifest:
    workbook = openpyxl.load_workbook(path, data_only=False, keep_links=False)
    sections: list[SectionEvidence] = []
    warnings: list[str] = []
    try:
        for index, sheet in enumerate(workbook.worksheets, start=1):
            non_empty = 0
            formulas = 0
            for row in sheet.iter_rows():
                for cell in row:
                    if cell.value is not None:
                        non_empty += 1
                    if _has_formula(cell):
                        formulas += 1

            fields: list[FieldEvidence] = []
            display_name = f"Sheet {index}"
            source_location = f"worksheet[{index}]"
            if permit_data_extraction:
                display_name = sheet.title
                source_location = sheet.title
                header_row = _header_row(sheet)
                if header_row is not None:
                    fields = _infer_fields(sheet, header_row)

            sections.append(
                SectionEvidence(
                    name=display_name,
                    source_location=source_location,
                    rows=sheet.max_row,
                    columns=sheet.max_column,
                    non_empty_cells=non_empty,
                    formula_cells=formulas,
                    merged_ranges=len(sheet.merged_cells.ranges),
                    chart_count=len(sheet._charts),
                    hidden=sheet.sheet_state != "visible",
                    fields=fields,
                )
            )
        if workbook._external_links:
            warnings.append("The workbook contains external links; they were not followed.")
    finally:
        workbook.close()

    assumptions = []
    if not permit_data_extraction:
        assumptions.append(
            "Worksheet names, labels, and field candidates were withheld because data extraction was not permitted."
        )
    return SampleManifest(
        format="xlsx",
        sections=sections,
        extraction_permitted=permit_data_extraction,
        assumptions=assumptions,
        warnings=warnings,
    )
