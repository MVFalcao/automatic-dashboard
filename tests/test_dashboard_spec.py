import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from automation.specification.models import (
    DashboardSpec,
    FieldDefinition,
    FieldKind,
    FieldMapping,
    FilterSpec,
    LocalizationSpec,
    MetricDefinition,
    OutputKind,
    OutputSpec,
    PrivacyPolicy,
    SectionKind,
    SectionSpec,
    VisualizationKind,
    VisualizationSpec,
)
from automation.specification.versioning import (
    load_active_spec,
    load_spec_version,
    rollback_spec,
    save_approved_spec,
)


def valid_spec(title: str = "Example Dashboard") -> DashboardSpec:
    return DashboardSpec(
        id="example",
        title=title,
        fields=[
            FieldDefinition(id="category", label="Category", kind=FieldKind.TEXT),
            FieldDefinition(id="amount", label="Amount", kind=FieldKind.NUMBER),
        ],
        mappings=[
            FieldMapping(source_field="Category", target_field="category", approved=True),
            FieldMapping(source_field="Amount", target_field="amount", approved=True),
        ],
        metrics=[
            MetricDefinition(
                id="total",
                label="Total",
                operation="sum",
                field="amount",
                explanation="Adds every approved amount.",
                approved=True,
            )
        ],
        filters=[FilterSpec(id="category-filter", label="Category", field="category")],
        visualizations=[
            VisualizationSpec(
                id="total-card",
                kind=VisualizationKind.CARD,
                title="Total",
                metric_ids=["total"],
            )
        ],
        sections=[
            SectionSpec(
                id="summary",
                title="Summary",
                kind=SectionKind.SUMMARY,
                visualization_ids=["total-card"],
                metric_ids=["total"],
                order=0,
            )
        ],
        localization=LocalizationSpec(
            language="en",
            locale="en-US",
            timezone="America/Sao_Paulo",
            currency="USD",
        ),
        outputs=OutputSpec(enabled=[OutputKind.WEB, OutputKind.EXCEL, OutputKind.PDF]),
    )


def test_unknown_fields_and_unapproved_calculations_are_rejected() -> None:
    payload = valid_spec().model_dump(mode="json")
    payload["unexpected"] = True
    with pytest.raises(ValidationError, match="extra_forbidden"):
        DashboardSpec.model_validate(payload)

    payload.pop("unexpected")
    payload["metrics"][0]["approved"] = False
    with pytest.raises(ValidationError, match="not approved"):
        DashboardSpec.model_validate(payload)


def test_unknown_references_and_dependency_cycles_are_rejected() -> None:
    payload = valid_spec().model_dump(mode="json")
    payload["metrics"][0]["field"] = "unknown"
    with pytest.raises(ValidationError, match="unknown field"):
        DashboardSpec.model_validate(payload)

    payload = valid_spec().model_dump(mode="json")
    payload["sections"].append(
        {
            "id": "details",
            "title": "Details",
            "kind": "table",
            "depends_on": ["summary"],
            "order": 1,
        }
    )
    payload["sections"][0]["depends_on"] = ["details"]
    with pytest.raises(ValidationError, match="cycle"):
        DashboardSpec.model_validate(payload)


def test_confidential_field_policy_must_be_consistent() -> None:
    payload = valid_spec().model_dump(mode="json")
    payload["fields"][0]["confidential"] = True
    payload["privacy"] = PrivacyPolicy(
        confidential_fields=["category"],
        allow_persistence=True,
    ).model_dump(mode="json")
    with pytest.raises(ValidationError, match="cannot allow data persistence"):
        DashboardSpec.model_validate(payload)


def test_versions_are_immutable_verified_and_rollback_only_moves_pointer(tmp_path: Path) -> None:
    first = valid_spec("First")
    second = valid_spec("Second")
    first_metadata = save_approved_spec(tmp_path, first, approved_by="local-user", approval_id="approval-1")
    second_metadata = save_approved_spec(tmp_path, second, approved_by="local-user", approval_id="approval-2")

    assert first_metadata.version == 1
    assert second_metadata.version == 2
    assert load_active_spec(tmp_path).title == "Second"
    assert rollback_spec(tmp_path, 1).title == "First"
    assert load_active_spec(tmp_path).title == "First"
    assert load_spec_version(tmp_path, 2).title == "Second"
    assert (tmp_path / "specifications/0001/dashboard-spec.json").exists()
    assert (tmp_path / "specifications/0001/approval.yaml").exists()


def test_modified_approved_version_fails_checksum_validation(tmp_path: Path) -> None:
    save_approved_spec(tmp_path, valid_spec(), approved_by="local-user", approval_id="approval-1")
    path = tmp_path / "specifications/0001/dashboard-spec.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["title"] = "Silently changed"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="checksum"):
        load_spec_version(tmp_path, 1)


def test_checked_in_json_schema_matches_canonical_model() -> None:
    path = Path(__file__).parents[1] / "config/schemas/dashboard-spec-v1.json"

    assert json.loads(path.read_text(encoding="utf-8")) == DashboardSpec.model_json_schema()
