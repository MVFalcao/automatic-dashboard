"""Immutable DashboardSpec persistence, migration, activation, and rollback."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from automation.specification.models import ApprovalVersion, DashboardSpec


CURRENT_SCHEMA_VERSION = 1
Migration = Callable[[dict[str, Any]], dict[str, Any]]
MIGRATIONS: dict[int, Migration] = {}


def migrate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(payload)
    version = migrated.get("schema_version")
    if not isinstance(version, int) or version < 1:
        raise ValueError("DashboardSpec has an invalid schema_version")
    if version > CURRENT_SCHEMA_VERSION:
        raise ValueError("DashboardSpec was created by a newer application version")
    while version < CURRENT_SCHEMA_VERSION:
        migration = MIGRATIONS.get(version)
        if migration is None:
            raise ValueError(f"No DashboardSpec migration exists for version {version}")
        migrated = migration(migrated)
        next_version = migrated.get("schema_version")
        if next_version != version + 1:
            raise ValueError("DashboardSpec migration did not advance exactly one version")
        version = next_version
    return migrated


def _atomic_write(destination: Path, content: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=destination.parent, prefix=f".{destination.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def _version_directories(project_directory: Path) -> list[int]:
    root = project_directory / "specifications"
    return sorted(int(path.name) for path in root.iterdir() if path.is_dir() and path.name.isdigit()) if root.exists() else []


def save_approved_spec(project_directory: Path, spec: DashboardSpec, *, approved_by: str, approval_id: str) -> ApprovalVersion:
    canonical = json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    version = max(_version_directories(project_directory), default=0) + 1
    version_directory = project_directory / "specifications" / f"{version:04d}"
    if version_directory.exists():
        raise FileExistsError(f"Specification version {version} already exists")
    version_directory.mkdir(parents=True)
    metadata = ApprovalVersion(
        version=version,
        approved_at=datetime.now(UTC),
        approved_by=approved_by,
        approval_id=approval_id,
        checksum_sha256=checksum,
    )
    _atomic_write(version_directory / "dashboard-spec.json", json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n")
    _atomic_write(version_directory / "approval.yaml", yaml.safe_dump(metadata.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
    _atomic_write(project_directory / "active-specification", f"{version:04d}\n")
    return metadata


def load_spec_version(project_directory: Path, version: int) -> DashboardSpec:
    version_directory = project_directory / "specifications" / f"{version:04d}"
    payload = json.loads((version_directory / "dashboard-spec.json").read_text(encoding="utf-8"))
    metadata = ApprovalVersion.model_validate(yaml.safe_load((version_directory / "approval.yaml").read_text(encoding="utf-8")))
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != metadata.checksum_sha256:
        raise ValueError("Stored DashboardSpec checksum does not match approval metadata")
    return DashboardSpec.model_validate(migrate_payload(payload))


def load_active_spec(project_directory: Path) -> DashboardSpec:
    version = int((project_directory / "active-specification").read_text(encoding="utf-8").strip())
    return load_spec_version(project_directory, version)


def rollback_spec(project_directory: Path, version: int) -> DashboardSpec:
    spec = load_spec_version(project_directory, version)
    active_path = project_directory / "active-specification"
    previous = int(active_path.read_text(encoding="utf-8").strip())
    if previous == version:
        return spec
    _atomic_write(active_path, f"{version:04d}\n")
    event = {
        "activated_version": version,
        "rolled_back_from": previous,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    _atomic_write(project_directory / "last-rollback.yaml", yaml.safe_dump(event, sort_keys=False))
    return spec
