"""Section-based schema approval and dependency handling."""

from automation.approval.service import ApprovalStore
from automation.approval.versioning import save_approved_version

__all__ = ["ApprovalStore", "save_approved_version"]
