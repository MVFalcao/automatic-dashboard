"""Structural analysis for raster and SVG dashboard references."""

from __future__ import annotations

from pathlib import Path

from defusedxml import ElementTree
from PIL import Image

from automation.discovery.models import SampleManifest, SectionEvidence


def _svg_attributes(path: Path) -> dict[str, str | int | float | bool]:
    root = ElementTree.parse(path).getroot()
    return {
        "width": root.attrib.get("width", "unknown"),
        "height": root.attrib.get("height", "unknown"),
        "view_box": root.attrib.get("viewBox", "unknown"),
        "element_count": sum(1 for _ in root.iter()),
    }


def _raster_attributes(path: Path) -> dict[str, str | int | float | bool]:
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        return {
            "width_pixels": image.width,
            "height_pixels": image.height,
            "color_mode": image.mode,
            "image_format": image.format or path.suffix.removeprefix(".").upper(),
            "frame_count": getattr(image, "n_frames", 1),
        }


def analyze_image(path: Path, *, permit_data_extraction: bool) -> SampleManifest:
    suffix = path.suffix.casefold()
    attributes = _svg_attributes(path) if suffix == ".svg" else _raster_attributes(path)
    return SampleManifest(
        format=suffix.removeprefix("."),
        sections=[
            SectionEvidence(
                name="Image 1",
                source_location="image[1]",
                rows=0,
                columns=0,
                non_empty_cells=0,
                formula_cells=0,
                merged_ranges=0,
                chart_count=0,
                hidden=False,
                attributes=attributes,
            )
        ],
        extraction_permitted=permit_data_extraction,
        assumptions=[
            "The image is treated as a visual layout reference; semantic labels require a later vision-agent review."
        ],
    )
