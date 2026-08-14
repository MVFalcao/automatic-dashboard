"""Write a public, secret-free release manifest for an assembled artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


parser = argparse.ArgumentParser()
parser.add_argument("--version", required=True)
parser.add_argument("--setup", type=Path, required=True)
parser.add_argument("--bundle", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--python-version", required=True)
parser.add_argument("--node-version", required=True)
parser.add_argument("--hermes-version", required=True)
parser.add_argument("--playwright-version", required=True)
parser.add_argument("--chromium-version", required=True)
parser.add_argument("--installer-version", required=True)
args = parser.parse_args()

if not re.fullmatch(r"Inno Setup [1-9][0-9]*(?:\.[0-9]+)+", args.installer_version):
    raise SystemExit(f"Invalid Inno Setup version: {args.installer_version}")

setup = args.setup.resolve()
bundle = args.bundle.resolve()
manifest = {
    "schema_version": 2,
    "application_version": args.version,
    "platform": "windows",
    "architecture": "x64",
    "installer": {
        "filename": setup.name,
        "sha256": digest(setup),
        "size_bytes": setup.stat().st_size,
    },
    "bundle": {
        "directory": bundle.name,
        "size_bytes": sum(path.stat().st_size for path in bundle.rglob("*") if path.is_file()),
        "manifest": "manifest.sha256",
    },
    "runtimes": {
        "python": args.python_version,
        "node": args.node_version,
        "hermes": args.hermes_version,
        "playwright": args.playwright_version,
        "chromium": args.chromium_version,
        "installer": args.installer_version,
    },
}
if manifest["installer"]["size_bytes"] >= 2 * 1024 * 1024 * 1024:
    raise SystemExit("Setup.exe exceeds the 2 GiB GitHub asset limit")
args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
