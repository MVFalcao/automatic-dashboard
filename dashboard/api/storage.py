"""Readable local project configuration storage."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from dashboard.api.models import ProjectConfig


JSON_SIZE_THRESHOLD = 16_000


def safe_project_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    if not slug:
        raise ValueError("Project name must contain a letter or number")
    return slug


def save_project_config(parent: Path, config: ProjectConfig) -> Path:
    """Save only the validated non-confidential project configuration."""
    serialized = config.model_dump(mode="json")
    compact_json = json.dumps(serialized, ensure_ascii=False, separators=(",", ":"))
    project_directory = parent / safe_project_name(config.name)
    project_directory.mkdir(parents=True, exist_ok=True)

    if len(compact_json.encode("utf-8")) >= JSON_SIZE_THRESHOLD:
        destination = project_directory / "project.json"
        destination.write_text(
            json.dumps(serialized, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        destination = project_directory / "project.yaml"
        destination.write_text(
            yaml.safe_dump(serialized, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    return destination
