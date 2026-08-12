"""Machine-readable contract generation for release and integration checks."""

from __future__ import annotations

import json
from pathlib import Path

from automation.specification.models import DashboardSpec


def write_json_schema(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(DashboardSpec.model_json_schema(), indent=2) + "\n", encoding="utf-8")
