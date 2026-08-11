"""Create an approval-required dashboard proposal from structural evidence."""

from __future__ import annotations

import re

from automation.discovery.models import (
    Confidence,
    DraftDashboardSchema,
    ProposedField,
    ProposedSection,
    SampleManifest,
)


def _identifier(value: str, fallback: str) -> str:
    identifier = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    return identifier or fallback


def propose_dashboard_schema(manifest: SampleManifest) -> DraftDashboardSchema:
    fields: dict[str, ProposedField] = {}
    sections: list[ProposedSection] = []

    for section_index, section in enumerate(manifest.sections, start=1):
        section_id = _identifier(section.name, f"section_{section_index}")
        presentation = "table" if section.fields else "visual_reference"
        confidence = Confidence.HIGH if section.fields else Confidence.LOW
        sections.append(
            ProposedSection(
                id=section_id,
                display_name=section.name,
                source_section=section.source_location,
                presentation=presentation,
                confidence=confidence,
            )
        )
        for field_index, evidence in enumerate(section.fields, start=1):
            field_id = _identifier(evidence.name, f"field_{field_index}")
            existing = fields.get(field_id)
            location = evidence.source_location
            if existing:
                existing.evidence.append(location)
                if existing.inferred_type != evidence.inferred_type:
                    existing.confidence = Confidence.LOW
            else:
                fields[field_id] = ProposedField(
                    id=field_id,
                    display_name=evidence.name,
                    inferred_type=evidence.inferred_type,
                    confidence=evidence.confidence,
                    evidence=[location],
                )

    assumptions = list(manifest.assumptions)
    assumptions.append(
        "Every proposed field and section requires user approval; no KPI formula has been inferred or activated."
    )
    return DraftDashboardSchema(
        source_format=manifest.format,
        fields=list(fields.values()),
        sections=sections,
        assumptions=assumptions,
    )
