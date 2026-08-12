"""Excel and shared HTML/PDF renderers driven only by ReportDocument."""

from __future__ import annotations

import html
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from playwright.sync_api import sync_playwright

from automation.reports.models import ReportDocument
from automation.reports.localization import format_value


SYNTHETIC_NOTICE = {
    "en": "Synthetic data — all values are invented for design review.",
    "pt": "Dados sintéticos — todos os valores são inventados para revisão do design.",
}


def _excel_safe(value: object) -> object:
    if isinstance(value, str) and value[:1] in {"=", "+", "-", "@"}:
        return "'" + value
    return value


def _language(document: ReportDocument) -> str:
    return document.specification.localization.language.split("-")[0]


def render_excel(document: ReportDocument) -> bytes:
    language = _language(document)
    workbook = Workbook()
    summary = workbook.active
    summary.title = "Resumo" if language == "pt" else "Summary"
    summary.append([document.specification.title])
    summary["A1"].font = Font(size=18, bold=True, color="FFFFFF")
    summary["A1"].fill = PatternFill("solid", fgColor="23543C")
    if document.synthetic:
        summary.append([SYNTHETIC_NOTICE[language]])
    for metric in document.specification.metrics:
        summary.append([metric.label, document.metrics.get(metric.id), metric.explanation])
    summary.column_dimensions["A"].width = 34
    summary.column_dimensions["B"].width = 18
    summary.column_dimensions["C"].width = 64

    details = workbook.create_sheet("Dados" if language == "pt" else "Data")
    details.append([field.label for field in document.specification.fields])
    for cell in details[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="23543C")
    for record in document.records:
        details.append([_excel_safe(format_value(record.get(field.id), language=language, currency=document.specification.localization.currency)) for field in document.specification.fields])
    details.freeze_panes = "A2"
    details.auto_filter.ref = details.dimensions
    destination = BytesIO()
    workbook.save(destination)
    workbook.close()
    return destination.getvalue()


def render_html(document: ReportDocument) -> str:
    language = _language(document)
    notice = f'<p class="notice">{html.escape(SYNTHETIC_NOTICE[language])}</p>' if document.synthetic else ""
    metrics = "".join(
        f'<article><span>{html.escape(metric.label)}</span><strong data-metric="{html.escape(metric.id)}">{html.escape(str(document.metrics.get(metric.id, "—")))}</strong><small>{html.escape(metric.explanation)}</small></article>'
        for metric in document.specification.metrics
    )
    headers = "".join(f"<th>{html.escape(field.label)}</th>" for field in document.specification.fields)
    rows = "".join("<tr>" + "".join(f"<td>{html.escape(str(record.get(field.id, '')))}</td>" for field in document.specification.fields) + "</tr>" for record in document.records)
    sections = "".join(f'<h2 data-section="{html.escape(section.id)}">{html.escape(section.title)}</h2>' for section in sorted(document.specification.sections, key=lambda item: item.order))
    return f'''<!doctype html><html lang="{language}"><head><meta charset="utf-8"><style>
@page{{size:{html.escape(document.specification.outputs.pdf_page_size)};margin:16mm}}body{{font-family:Arial,sans-serif;color:#17221b}}h1{{font-size:26px}}.notice{{padding:10px;background:#fff4cf}}.metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}article{{padding:14px;border:1px solid #d6ddd8}}article span,article small{{display:block;color:#667168}}article strong{{display:block;font-size:22px;margin:6px 0}}table{{width:100%;border-collapse:collapse;font-size:9px}}th,td{{padding:6px;border-bottom:1px solid #dde2de;text-align:left}}th{{background:#23543c;color:white}}
</style></head><body><h1>{html.escape(document.specification.title)}</h1>{notice}<div class="metrics">{metrics}</div>{sections}<table><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table></body></html>'''


def render_pdf(document: ReportDocument) -> bytes:
    source = render_html(document)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(source, wait_until="load")
            return page.pdf(print_background=True, prefer_css_page_size=True)
        finally:
            browser.close()


def excel_metric_values(content: bytes) -> dict[str, int | float | None]:
    """Test/diagnostic helper that reads renderer values without desktop Excel."""
    workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    try:
        sheet = workbook.worksheets[0]
        start = 3 if sheet["A2"].value in SYNTHETIC_NOTICE.values() else 2
        return {str(sheet.cell(row, 1).value): sheet.cell(row, 2).value for row in range(start, sheet.max_row + 1)}
    finally:
        workbook.close()
