"""Canonical dashboard specification and immutable version history."""

from automation.specification.models import (
    ApprovalVersion,
    DashboardSpec,
    FieldMapping,
    MetricDefinition,
    PrivacyPolicy,
    SectionSpec,
    VisualizationSpec,
)
from automation.specification.versioning import load_active_spec, load_spec_version, rollback_spec, save_approved_spec

__all__ = ["ApprovalVersion", "DashboardSpec", "FieldMapping", "MetricDefinition", "PrivacyPolicy", "SectionSpec", "VisualizationSpec", "load_active_spec", "load_spec_version", "rollback_spec", "save_approved_spec"]
