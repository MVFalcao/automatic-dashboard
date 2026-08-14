"""Sanitized local diagnostics and support-bundle endpoints."""

from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
import zipfile
import importlib.metadata
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import Response

from automation.agent.managed import managed_hermes
from automation.release.diagnostics import run_diagnostics
from automation.release.support import support_events


router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


def _root() -> Path:
    return Path(os.environ.get("DASHBOARD_APPLICATION_ROOT", Path.cwd())).resolve()


def _node(root: Path) -> str:
    candidates = (root / "runtime" / "node" / "node.exe", root / "runtime" / "node" / "bin" / "node")
    return str(next((item for item in candidates if item.is_file()), "node"))


def _reachable(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


def _clean_detail(value: str, root: Path) -> str:
    cleaned = value.replace(str(root), "<application-root>").replace(str(Path.home()), "<user-home>")
    return cleaned


def _version(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
        return (result.stdout or result.stderr).strip().splitlines()[0] if result.returncode == 0 else "unavailable"
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def runtime_versions() -> dict[str, str]:
    root = _root()
    runtime = Path(os.environ.get("DASHBOARD_HERMES_RUNTIME", root / ".hermes-runtime"))
    hermes_python = runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    browser = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", root / ".playwright"))
    chromium = ",".join(sorted(item.name for item in browser.iterdir() if item.is_dir())) if browser.is_dir() else "unavailable"
    try:
        playwright = importlib.metadata.version("playwright")
    except importlib.metadata.PackageNotFoundError:
        playwright = "unavailable"
    return {
        "application": "0.2.1",
        "python": sys.version.split()[0],
        "node": _version([_node(root), "--version"]).lstrip("v"),
        "hermes": _version([str(hermes_python), "-c", "import importlib.metadata; print(importlib.metadata.version('hermes-agent'))"]),
        "playwright": playwright,
        "chromium": chromium,
    }


def diagnostic_payload() -> dict[str, object]:
    root = _root()
    runtime = Path(os.environ.get("DASHBOARD_HERMES_RUNTIME", root / ".hermes-runtime"))
    browser = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", root / ".playwright"))
    report = run_diagnostics(
        root=root,
        python_executable=sys.executable,
        node_executable=_node(root),
        hermes_environment=runtime,
        browser_path=browser,
    )
    hermes = managed_hermes.status()
    from dashboard.api.hermes import provider_registry

    providers = provider_registry.list()
    codex = next((item for item in providers if item.provider.value == "codex"), None)
    components = {
        "api": {"ok": True, "remediation": None},
        "web": {"ok": _reachable(3000), "remediation": "Restart Universal Dashboard Agent."},
        "hermes": {"ok": bool(hermes.get("ready")), "remediation": "Restart the managed Hermes runtime."},
        "browser": {"ok": any(item.name == "playwright-chromium" and item.ok for item in report.checks), "remediation": "Repair the bundled Chromium runtime."},
        "storage": {"ok": root.is_dir() and os.access(root, os.W_OK), "remediation": "Check write access to the application directory."},
        "provider": {"ok": bool(providers), "remediation": "Connect an AI provider in Project operations."},
        "codex_model": {
            "ok": codex is None or codex.model == "gpt-5.5",
            "remediation": "Reconnect Codex and select gpt-5.5.",
        },
    }
    checks = [
        {"name": item.name, "ok": item.ok, "detail": _clean_detail(item.detail, root), "remediation": item.remediation}
        for item in report.checks
    ]
    return {
        "schema_version": 1,
        "diagnostic_id": uuid4().hex,
        "ok": report.ok and all(item["ok"] for item in components.values()),
        "platform": report.platform,
        "components": components,
        "checks": checks,
    }


@router.get("")
def diagnostics() -> dict[str, object]:
    return diagnostic_payload()


@router.post("/support-bundle")
def support_bundle() -> Response:
    payload = diagnostic_payload()
    identifier = str(payload["diagnostic_id"])
    versions = runtime_versions()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("diagnostics.json", json.dumps(payload, indent=2) + "\n")
        archive.writestr("runtime-versions.json", json.dumps(versions, indent=2) + "\n")
        archive.writestr("events.json", json.dumps(support_events.snapshot(), indent=2) + "\n")
        archive.writestr("README.txt", "Sanitized Universal Dashboard Agent diagnostics. No credentials, project data, prompts, or subprocess output are included.\n")
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="dashboard-support-{identifier}.zip"', "X-Diagnostic-Id": identifier},
    )
