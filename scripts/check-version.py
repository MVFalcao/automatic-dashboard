"""Check that release metadata and an optional tag agree."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


root = Path(__file__).parents[1]
pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
python_version = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
package = json.loads((root / "dashboard" / "web" / "package.json").read_text(encoding="utf-8"))
api = (root / "dashboard" / "api" / "main.py").read_text(encoding="utf-8")
api_version = re.search(r'version\s*=\s*"([^"]+)"', api)
if not python_version or package.get("version") != python_version.group(1) or not api_version or api_version.group(1) != python_version.group(1):
    raise SystemExit("Python, frontend, and API versions do not match")
version = python_version.group(1)
parser = argparse.ArgumentParser()
parser.add_argument("--tag")
args = parser.parse_args()
if args.tag and args.tag != f"v{version}":
    raise SystemExit(f"Tag {args.tag} does not match application version v{version}")
print(version)
