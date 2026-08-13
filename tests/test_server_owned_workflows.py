from __future__ import annotations

import json
from pathlib import Path

import pytest

from automation.connectors.models import ApiSourceConfig
from automation.persistence.workflow import (
    ApiSourceApprovalRecord,
    ApiSourceInspectionRecord,
    ProjectWorkflowRepository,
    canonical_checksum,
)
from automation.connectors.client import ApiClient


def test_source_approval_is_bound_to_immutable_source_and_complete_classification(tmp_path: Path) -> None:
    repository = ProjectWorkflowRepository(tmp_path)
    source = ApiSourceConfig(id="source", name="Source", endpoint="https://api.example.test/records")
    repository.save_source(source)
    inspection = ApiClient(transport=None).inspect(source, [{"id": 1, "amount": 10}])
    inspected = ApiSourceInspectionRecord(
        project_id="00000000-0000-0000-0000-000000000001",
        source_id=source.id,
        source_checksum=canonical_checksum(source),
        inspection_checksum=canonical_checksum(inspection),
        inspection=inspection,
    )
    repository.save_inspection(inspected)
    approval = ApiSourceApprovalRecord(
        project_id=inspected.project_id,
        source_id=source.id,
        inspection_id=inspected.id,
        source_checksum=inspected.source_checksum,
        inspection_checksum=inspected.inspection_checksum,
        mappings={"id": "id"},
        field_classifications={"id": False, "amount": False},
        approved_by="local-user",
    )
    repository.save_approval(approval)
    repository.verify(inspected.project_id, source.id, inspected.id, approval.id)

    changed = source.model_copy(update={"name": "Changed"})
    repository.save_source(changed)
    with pytest.raises(ValueError, match="source changed"):
        repository.verify(inspected.project_id, source.id, inspected.id, approval.id)


def test_tampered_inspection_checksum_is_rejected(tmp_path: Path) -> None:
    repository = ProjectWorkflowRepository(tmp_path)
    source = ApiSourceConfig(id="source", name="Source", endpoint="https://api.example.test/records")
    repository.save_source(source)
    inspection = ApiClient().inspect(source, [{"id": 1}])
    record = ApiSourceInspectionRecord(
        project_id="00000000-0000-0000-0000-000000000001", source_id=source.id,
        source_checksum=canonical_checksum(source), inspection_checksum=canonical_checksum(inspection), inspection=inspection,
    )
    repository.save_inspection(record)
    path = repository._path("inspections", record.id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["inspection"]["record_shape"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        repository.get_inspection(record.id)
