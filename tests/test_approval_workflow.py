from pathlib import Path

from automation.approval.models import ApprovalStatus, CreateApprovalRequest
from automation.approval.service import ApprovalStore
from automation.approval.versioning import save_approved_version
from automation.discovery.models import (
    Confidence,
    DraftDashboardSchema,
    ProposedSection,
)


def draft_schema() -> DraftDashboardSchema:
    return DraftDashboardSchema(
        source_format="xlsx",
        fields=[],
        sections=[
            ProposedSection(
                id="summary",
                display_name="Summary",
                source_section="Dashboard",
                presentation="visual_reference",
                confidence=Confidence.MEDIUM,
            ),
            ProposedSection(
                id="details",
                display_name="Details",
                source_section="Records",
                presentation="table",
                confidence=Confidence.HIGH,
            ),
        ],
        assumptions=[],
    )


def test_rejected_section_blocks_only_dependents() -> None:
    store = ApprovalStore()
    package = store.create(
        CreateApprovalRequest(
            draft_schema=draft_schema(),
            dependencies={"summary": ["details"]},
        )
    )

    package = store.decide(
        package.approval_id,
        "details",
        approve=False,
        feedback="Needs another column",
    )

    assert package.sections["details"].status == ApprovalStatus.REJECTED
    assert package.sections["summary"].status == ApprovalStatus.BLOCKED
    assert package.ready_to_activate is False


def test_independent_sections_can_be_approved_separately() -> None:
    store = ApprovalStore()
    package = store.create(CreateApprovalRequest(draft_schema=draft_schema()))

    package = store.decide(package.approval_id, "summary", approve=True, feedback=None)
    assert package.sections["summary"].status == ApprovalStatus.APPROVED
    assert package.sections["details"].status == ApprovalStatus.PENDING

    package = store.decide(package.approval_id, "details", approve=True, feedback=None)
    assert package.ready_to_activate is True


def test_dependency_cycles_are_rejected() -> None:
    store = ApprovalStore()

    try:
        store.create(
            CreateApprovalRequest(
                draft_schema=draft_schema(),
                dependencies={"summary": ["details"], "details": ["summary"]},
            )
        )
    except ValueError as exc:
        assert "cycle" in str(exc)
    else:
        raise AssertionError("Expected cyclic dependencies to be rejected")


def test_only_fully_approved_non_confidential_schema_is_versioned(tmp_path: Path) -> None:
    store = ApprovalStore()
    package = store.create(CreateApprovalRequest(draft_schema=draft_schema()))

    try:
        save_approved_version(tmp_path, package, confirmed_non_confidential=True)
    except ValueError as exc:
        assert "approved" in str(exc)
    else:
        raise AssertionError("Expected unapproved schema persistence to fail")

    package = store.decide(package.approval_id, "summary", approve=True, feedback=None)
    package = store.decide(package.approval_id, "details", approve=True, feedback=None)

    try:
        save_approved_version(tmp_path, package, confirmed_non_confidential=False)
    except ValueError as exc:
        assert "non-confidential" in str(exc)
    else:
        raise AssertionError("Expected confidentiality confirmation to be required")

    first = save_approved_version(tmp_path, package, confirmed_non_confidential=True)
    second = save_approved_version(tmp_path, package, confirmed_non_confidential=True)

    assert first == tmp_path / "versions" / "0001" / "dashboard-schema.yaml"
    assert second == tmp_path / "versions" / "0002" / "dashboard-schema.yaml"
    assert (tmp_path / "current-version").read_text(encoding="utf-8") == "0002\n"
