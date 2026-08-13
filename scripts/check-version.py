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
package_lock = json.loads((root / "dashboard" / "web" / "package-lock.json").read_text(encoding="utf-8"))
api = (root / "dashboard" / "api" / "main.py").read_text(encoding="utf-8")
api_version = re.search(r'version\s*=\s*"([^"]+)"', api)
inno = (root / "scripts" / "UniversalDashboardAgent.iss").read_text(encoding="utf-8")
inno_version = re.search(r'#define AppVersion "([^"]+)"', inno)
versions = {
    python_version.group(1) if python_version else None,
    package.get("version"),
    package_lock.get("version"),
    package_lock.get("packages", {}).get("", {}).get("version"),
    api_version.group(1) if api_version else None,
    inno_version.group(1) if inno_version else None,
}
if None in versions or len(versions) != 1:
    raise SystemExit("Python, frontend, and API versions do not match")
version = python_version.group(1)
node_version = (root / ".nvmrc").read_text(encoding="utf-8").strip()
if node_version != "24.18.0" or package.get("engines", {}).get("node") != ">=24.0.0":
    raise SystemExit("Node runtime pin and frontend engine requirement do not match the v0.2.0 release contract")
parser = argparse.ArgumentParser()
parser.add_argument("--tag")
args = parser.parse_args()
if args.tag and args.tag != f"v{version}":
    raise SystemExit(f"Tag {args.tag} does not match application version v{version}")
print(version)
