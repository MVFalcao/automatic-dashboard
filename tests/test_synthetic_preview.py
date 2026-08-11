import base64
from io import BytesIO

import openpyxl
from pypdf import PdfReader

from automation.discovery.models import (
    Confidence,
    DraftDashboardSchema,
    FieldType,
    ProposedField,
    ProposedSection,
)
from automation.preview import PreviewRequest, generate_preview
from automation.preview.models import PreviewLanguage, PreviewOutput


def preview_request() -> PreviewRequest:
    return PreviewRequest(
        schema=DraftDashboardSchema(
            source_format="xlsx",
            fields=[
                ProposedField(
                    id="contact_email",
                    display_name="Contact email",
                    inferred_type=FieldType.TEXT,
                    confidence=Confidence.HIGH,
                    evidence=["Data!A1"],
                ),
                ProposedField(
                    id="amount",
                    display_name="Amount",
                    inferred_type=FieldType.NUMBER,
                    confidence=Confidence.HIGH,
                    evidence=["Data!B1"],
                ),
            ],
            sections=[
                ProposedSection(
                    id="summary",
                    display_name="Summary",
                    source_section="Dashboard",
                    presentation="visual_reference",
                    confidence=Confidence.MEDIUM,
                )
            ],
            assumptions=[],
        ),
        outputs=[PreviewOutput.WEB, PreviewOutput.EXCEL, PreviewOutput.PDF],
        language=PreviewLanguage.ENGLISH,
        synthetic_record_count=5,
    )


def test_all_artifacts_use_the_same_synthetic_record_count() -> None:
    package = generate_preview(preview_request())

    assert package.synthetic is True
    assert package.record_count == 5
    assert {artifact.format for artifact in package.artifacts} == {
        PreviewOutput.WEB,
        PreviewOutput.EXCEL,
        PreviewOutput.PDF,
    }
    assert all(artifact.size_bytes > 0 for artifact in package.artifacts)


def test_excel_and_web_contain_only_obvious_synthetic_identifiers() -> None:
    package = generate_preview(preview_request())
    by_format = {artifact.format: artifact for artifact in package.artifacts}

    html = base64.b64decode(by_format[PreviewOutput.WEB].content_base64).decode("utf-8")
    assert "person001@example.invalid" in html

    workbook = openpyxl.load_workbook(
        BytesIO(base64.b64decode(by_format[PreviewOutput.EXCEL].content_base64)),
        data_only=True,
    )
    assert workbook["Data"]["A2"].value == "person001@example.invalid"


def test_pdf_artifact_is_valid() -> None:
    package = generate_preview(preview_request())
    pdf = next(artifact for artifact in package.artifacts if artifact.format == PreviewOutput.PDF)

    reader = PdfReader(BytesIO(base64.b64decode(pdf.content_base64)))

    assert len(reader.pages) >= 1
