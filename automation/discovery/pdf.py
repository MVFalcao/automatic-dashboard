"""Structural analysis for PDF dashboard references."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from automation.discovery.models import SampleManifest, SectionEvidence


def analyze_pdf(path: Path, *, permit_data_extraction: bool) -> SampleManifest:
    reader = PdfReader(path, strict=False)
    sections: list[SectionEvidence] = []
    warnings: list[str] = []

    if reader.is_encrypted:
        warnings.append("The PDF is encrypted and may require a password for full analysis.")

    for index, page in enumerate(reader.pages, start=1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        text_lines = 0
        if permit_data_extraction:
            text = page.extract_text() or ""
            text_lines = sum(1 for line in text.splitlines() if line.strip())
        sections.append(
            SectionEvidence(
                name=f"Page {index}",
                source_location=f"page[{index}]",
                rows=0,
                columns=0,
                non_empty_cells=text_lines,
                formula_cells=0,
                merged_ranges=0,
                chart_count=0,
                hidden=False,
                attributes={
                    "width_points": round(width, 2),
                    "height_points": round(height, 2),
                    "rotation": int(page.rotation or 0),
                    "text_lines_detected": text_lines,
                },
            )
        )

    assumptions = [
        "PDF pages are treated as visual report sections; calculations cannot be recovered reliably from appearance alone."
    ]
    if not permit_data_extraction:
        assumptions.append("Page text was not extracted because data extraction was not permitted.")
    return SampleManifest(
        format="pdf",
        sections=sections,
        extraction_permitted=permit_data_extraction,
        assumptions=assumptions,
        warnings=warnings,
    )
