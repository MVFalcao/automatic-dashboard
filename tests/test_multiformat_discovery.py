from pathlib import Path

from PIL import Image
from pypdf import PdfWriter

from automation.discovery import analyze_image, analyze_pdf, propose_dashboard_schema


def test_pdf_analysis_reports_page_geometry_without_text(tmp_path: Path) -> None:
    path = tmp_path / "reference.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with path.open("wb") as destination:
        writer.write(destination)

    manifest = analyze_pdf(path, permit_data_extraction=False)

    assert manifest.format == "pdf"
    assert len(manifest.sections) == 1
    assert manifest.sections[0].attributes["width_points"] == 612.0
    assert manifest.sections[0].attributes["text_lines_detected"] == 0
    assert manifest.assumptions


def test_raster_analysis_reports_dimensions_without_pixel_data(tmp_path: Path) -> None:
    path = tmp_path / "reference.png"
    Image.new("RGB", (320, 180), color="white").save(path)

    manifest = analyze_image(path, permit_data_extraction=False)

    assert manifest.sections[0].attributes["width_pixels"] == 320
    assert manifest.sections[0].attributes["height_pixels"] == 180
    assert "white" not in manifest.model_dump_json().casefold()


def test_svg_analysis_uses_safe_xml_parser(tmp_path: Path) -> None:
    path = tmp_path / "reference.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect /></svg>',
        encoding="utf-8",
    )

    manifest = analyze_image(path, permit_data_extraction=False)

    assert manifest.sections[0].attributes["width"] == "640"
    assert manifest.sections[0].attributes["element_count"] == 2


def test_draft_schema_is_explicitly_unapproved(tmp_path: Path) -> None:
    path = tmp_path / "reference.png"
    Image.new("RGB", (100, 100)).save(path)
    manifest = analyze_image(path, permit_data_extraction=False)

    schema = propose_dashboard_schema(manifest)

    assert schema.requires_user_approval is True
    assert all(section.requires_approval for section in schema.sections)
    assert "no KPI formula" in schema.assumptions[-1]
