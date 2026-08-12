import csv
from pathlib import Path

from automation.discovery.models import (
    Confidence,
    DraftDashboardSchema,
    FieldType,
    ProposedField,
)
import pytest

from automation.importing import ImportApproval, ImportMode, apply_import, inspect_data_location


def schema() -> DraftDashboardSchema:
    return DraftDashboardSchema(
        source_format="xlsx",
        fields=[
            ProposedField(
                id="email",
                display_name="Email",
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
        sections=[],
        assumptions=[],
    )


def write_csv(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as destination:
        csv.writer(destination).writerows(rows)


def test_csv_import_plan_excludes_values_and_requires_mapping_approval(tmp_path: Path) -> None:
    path = tmp_path / "records.csv"
    write_csv(path, [["Email", "Amount"], ["private@example.com", "20"]])

    plan = inspect_data_location(path, schema())

    assert plan.sources[0].row_count == 1
    assert plan.sources[0].likely_confidential_columns == ["Email"]
    assert [mapping.target_field for mapping in plan.mappings] == ["email", "amount"]
    assert all(mapping.requires_confirmation for mapping in plan.mappings)
    assert "private@example.com" not in plan.model_dump_json()


def test_folder_import_requires_relationship_confirmation(tmp_path: Path) -> None:
    write_csv(tmp_path / "first.csv", [["Email"], ["one@example.com"]])
    write_csv(tmp_path / "second.csv", [["Amount"], ["10"]])

    plan = inspect_data_location(tmp_path, schema())

    assert len(plan.sources) == 2
    assert plan.requires_relationship_confirmation is True


def test_update_requires_confirmed_identifier_and_applies_deterministically(tmp_path: Path) -> None:
    path = tmp_path / "records.csv"
    write_csv(path, [["Email", "Amount"], ["one@example.com", "20"], ["two@example.com", "30"]])
    plan = inspect_data_location(path, schema())
    approval = ImportApproval(
        approved=True,
        mode=ImportMode.UPDATE,
        mappings={"Email": "email", "Amount": "amount"},
        update_identifier="email",
        update_identifier_confirmed=True,
        confidential_columns=["Email"],
    )

    records, result = apply_import(path, plan, approval, [{"email": "one@example.com", "amount": "10"}])

    assert records == [
        {"email": "one@example.com", "amount": "20"},
        {"email": "two@example.com", "amount": "30"},
    ]
    assert result.updated_rows == 1
    assert result.inserted_rows == 1
    assert "one@example.com" not in result.model_dump_json()


def test_confidential_import_cannot_be_marked_for_persistence(tmp_path: Path) -> None:
    path = tmp_path / "records.csv"
    write_csv(path, [["Email", "Amount"], ["one@example.com", "20"]])
    plan = inspect_data_location(path, schema())
    approval = ImportApproval(
        approved=True,
        mode=ImportMode.REPLACE,
        mappings={"Email": "email"},
        confidential_columns=["Email"],
        permit_persistence=True,
    )

    with pytest.raises(ValueError, match="cannot be persisted"):
        apply_import(path, plan, approval)


def test_persistence_requires_reviewed_classification_for_every_field(tmp_path: Path) -> None:
    path = tmp_path / "records.csv"
    write_csv(path, [["Email", "Amount"], ["one@example.com", "20"]])
    plan = inspect_data_location(path, schema())
    approval = ImportApproval(
        approved=True,
        mode=ImportMode.REPLACE,
        mappings={"Email": "email", "Amount": "amount"},
        field_classifications={"Email": False, "Amount": False},
        permit_persistence=True,
    )

    with pytest.raises(ValueError, match="match detection"):
        apply_import(path, plan, approval)


def test_inspection_reports_malformed_csv_rows(tmp_path: Path) -> None:
    path = tmp_path / "records.csv"
    write_csv(path, [["Email", "Amount"], ["one@example.com"]])

    plan = inspect_data_location(path, schema())

    assert "different number" in plan.validation_issues[0]
