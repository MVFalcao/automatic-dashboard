"""Assemble a checksum-verified, user-scoped offline release bundle.

Runtime archives are supplied by the release workflow after their upstream
checksums have been verified.  This script never downloads mutable "latest"
artifacts and refuses incomplete bundles.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT_EXCLUDED = {
    ".git", ".github", ".venv", ".hermes-runtime", ".playwright", "node_modules",
    "build", "coverage", "data", "dist", "reports",
    "tests", "private_source_dashboard.xlsx",
}
ALWAYS_EXCLUDED = {"__pycache__", ".pytest_cache", "test-results", "playwright-report"}


def copy_tree(source: Path, destination: Path) -> None:
    root = source.resolve()

    def ignore(directory: str, names: list[str]) -> set[str]:
        # A Next.js standalone build legitimately contains its own runtime
        # node_modules; every other dependency tree is a development artifact.
        directory_path = Path(directory).resolve()
        relative_parts = directory_path.relative_to(root).parts
        in_standalone = any(
            relative_parts[index:index + 2] == (".next", "standalone")
            for index in range(len(relative_parts) - 1)
        )
        ignored = set(names) & ALWAYS_EXCLUDED
        ignored.update(name for name in names if name == ".env" or name.startswith(".env.") or name.startswith("private_source_"))
        ignored.update(name for name in names if name.endswith((".egg-info", ".tsbuildinfo")))
        if not in_standalone and "node_modules" in names:
            ignored.add("node_modules")
        if directory_path.name == ".next":
            ignored.update(set(names) & {"cache", "dev"})
        if directory_path == root:
            ignored.update(set(names) & ROOT_EXCLUDED)
        return ignored

    shutil.copytree(source, destination, ignore=ignore, dirs_exist_ok=True)


def require(path: Path, label: str) -> Path:
    if not path.exists():
        raise SystemExit(f"{label} is missing: {path}")
    return path.resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description="Assemble an offline Universal Dashboard Agent bundle")
    parser.add_argument("--source", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python-runtime", type=Path, required=True)
    parser.add_argument("--node-runtime", type=Path, required=True)
    parser.add_argument("--hermes-runtime", type=Path, required=True)
    parser.add_argument("--playwright-browsers", type=Path, required=True)
    args = parser.parse_args()
    source = require(args.source, "Application source")
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"Output already exists: {output}")
    standalone = require(source / "dashboard" / "web" / ".next" / "standalone", "Next.js standalone build")
    require(source / "dashboard" / "web" / ".next" / "static", "Next.js static assets")
    output.mkdir(parents=True)
    copy_tree(source, output / "app")
    packaged_web = output / "app" / "dashboard" / "web"
    copy_tree(source / "dashboard" / "web" / ".next" / "static", packaged_web / ".next" / "standalone" / ".next" / "static")
    if (source / "dashboard" / "web" / "public").is_dir():
        copy_tree(source / "dashboard" / "web" / "public", packaged_web / ".next" / "standalone" / "public")
    copy_tree(require(args.python_runtime, "Pinned Python runtime"), output / "runtime" / "python")
    copy_tree(require(args.node_runtime, "Pinned Node runtime"), output / "runtime" / "node")
    copy_tree(require(args.playwright_browsers, "Playwright Chromium"), output / "runtime" / "playwright")
    wheels = output / "wheels"
    wheels.mkdir()
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(source), "--wheel-dir", str(wheels), "--disable-pip-version-check"],
        check=True,
    )
    # Assert the exact managed Hermes pin from its own environment rather than
    # trusting a directory name supplied by packaging automation.
    supplied_hermes = require(args.hermes_runtime, "Managed Hermes runtime")
    hermes_python = supplied_hermes / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    version = subprocess.run(
        [str(hermes_python), "-c", "import importlib.metadata; print(importlib.metadata.version('hermes-agent'))"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if version != "0.13.0":
        raise SystemExit(f"Managed Hermes must be 0.13.0, found {version}")
    hermes_wheels = output / "hermes-wheels"
    hermes_wheels.mkdir()
    subprocess.run(
        [str(hermes_python), "-m", "pip", "wheel", "hermes-agent==0.13.0", "--wheel-dir", str(hermes_wheels), "--disable-pip-version-check"],
        check=True,
    )
    manifest: list[str] = []
    for path in sorted(item for item in output.rglob("*") if item.is_file()):
        relative = path.relative_to(output).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest.append(f"{digest}  {relative}")
    (output / "manifest.sha256").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
