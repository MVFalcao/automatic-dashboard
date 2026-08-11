"""Immutable local version history for approved non-confidential schemas."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import yaml

from automation.approval.models import ApprovalPackage


JSON_SIZE_THRESHOLD = 16_000


def _atomic_write(destination: Path, content: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
            temporary.write(content)
        os.replace(temporary_name, destination)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def save_approved_version(
    project_directory: Path,
    package: ApprovalPackage,
    *,
    confirmed_non_confidential: bool,
) -> Path:
    if not package.ready_to_activate:
        raise ValueError("Every unblocked section must be approved before activation")
    if not confirmed_non_confidential:
        raise ValueError("Schema persistence requires explicit non-confidential confirmation")

    versions_directory = project_directory / "versions"
    existing = [
        int(path.name)
        for path in versions_directory.iterdir()
        if path.is_dir() and path.name.isdigit()
    ] if versions_directory.exists() else []
    version = max(existing, default=0) + 1
    version_directory = versions_directory / f"{version:04d}"

    payload = {
        "version": version,
        "approval_id": str(package.approval_id),
        "schema": package.draft_schema.model_dump(mode="json"),
        "sections": {
            key: value.model_dump(mode="json")
            for key, value in package.sections.items()
        },
    }
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(compact.encode("utf-8")) >= JSON_SIZE_THRESHOLD:
        destination = version_directory / "dashboard-schema.json"
        content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    else:
        destination = version_directory / "dashboard-schema.yaml"
        content = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    _atomic_write(destination, content)
    _atomic_write(project_directory / "current-version", f"{version:04d}\n")
    return destination
