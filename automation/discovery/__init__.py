"""Reference-sample discovery without persistent source-data storage."""

from automation.discovery.excel import analyze_excel
from automation.discovery.image import analyze_image
from automation.discovery.models import DraftDashboardSchema, SampleManifest
from automation.discovery.pdf import analyze_pdf
from automation.discovery.schema import propose_dashboard_schema

__all__ = [
    "DraftDashboardSchema",
    "SampleManifest",
    "analyze_excel",
    "analyze_image",
    "analyze_pdf",
    "propose_dashboard_schema",
]
