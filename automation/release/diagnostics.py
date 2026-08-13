"""Dependency and local-security checks used by the installers.

The checks are deliberately read-only.  They can be run after installation or
from a support bundle without exposing credentials or project data.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

MIN_PYTHON = (3, 11)
MIN_NODE = (24, 0)
ALLOWED_CORS = frozenset(
    {
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    }
)


@dataclass(frozen=True)
class Diagnostic:
    name: str
    ok: bool
    detail: str
    remediation: str | None = None


@dataclass(frozen=True)
class DiagnosticReport:
    platform: str
    checks: tuple[Diagnostic, ...]

    @property
    def ok(self) -> bool:
        return all(item.ok for item in self.checks)

    def as_dict(self) -> dict[str, object]:
        return {
            "platform": self.platform,
            "ok": self.ok,
            "checks": [asdict(item) for item in self.checks],
        }


def _version(value: str) -> tuple[int, ...] | None:
    numbers: list[int] = []
    for part in value.strip().lstrip("v").split("."):
        digits = "".join(character for character in part if character.isdigit())
        if not digits:
            break
        numbers.append(int(digits))
    return tuple(numbers) if numbers else None


def _run_version(command: Sequence[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode:
        return None
    return (result.stdout or result.stderr).strip().splitlines()[0] if (result.stdout or result.stderr).strip() else None


def _check_version(name: str, command: Sequence[str], minimum: tuple[int, ...], label: str) -> Diagnostic:
    raw = _run_version(command)
    parsed = _version(raw or "")
    if parsed is None:
        return Diagnostic(name, False, f"{label} was not found", f"Install {label} {'.'.join(map(str, minimum))} or newer.")
    if parsed[: len(minimum)] < minimum:
        return Diagnostic(name, False, f"{label} {raw} is too old", f"Upgrade {label} to {'.'.join(map(str, minimum))} or newer.")
    return Diagnostic(name, True, f"{label} {raw}")


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    if ":" in host:
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_network_configuration(*, api_host: str, web_host: str, cors_origins: Sequence[str]) -> tuple[Diagnostic, ...]:
    checks: list[Diagnostic] = []
    checks.append(
        Diagnostic(
            "loopback-api",
            _is_loopback(api_host),
            f"API host is {api_host}",
            "Set DASHBOARD_API_HOST=127.0.0.1; never bind the API to a LAN address.",
        )
    )
    checks.append(
        Diagnostic(
            "loopback-web",
            _is_loopback(web_host),
            f"Web host is {web_host}",
            "Set the Next.js host to 127.0.0.1.",
        )
    )
    origins = frozenset(origin.rstrip("/") for origin in cors_origins if origin)
    checks.append(
        Diagnostic(
            "narrow-cors",
            origins <= ALLOWED_CORS,
            f"CORS origins: {', '.join(sorted(origins)) or '(none)'}",
            "Allow only the local web origin(s), never '*'.",
        )
    )
    token_present = bool(os.environ.get("DASHBOARD_LOCAL_AUTH_TOKEN"))
    checks.append(
        Diagnostic(
            "local-auth",
            token_present,
            "Local API authentication token is configured" if token_present else "Local API authentication token is not configured",
            "Set DASHBOARD_LOCAL_AUTH_TOKEN from the OS credential store before exposing the API beyond the browser proxy.",
        )
    )
    return tuple(checks)


def _browser_check(python_executable: str, browser_path: Path | None) -> Diagnostic:
    try:
        result = subprocess.run(
            [python_executable, "-c", "import importlib.metadata; print(importlib.metadata.version('playwright'))"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        result = None
    if result is None or result.returncode:
        return Diagnostic("playwright", False, "Playwright is not importable", "Run: python -m pip install playwright")
    if browser_path is not None and browser_path.exists():
        return Diagnostic("playwright-chromium", True, f"Chromium browser directory exists at {browser_path}")
    return Diagnostic(
        "playwright-chromium",
        False,
        "Playwright is installed but Chromium was not found",
        "Run: python -m playwright install chromium",
    )


def run_diagnostics(
    *,
    root: Path,
    python_executable: str | None = None,
    node_executable: str | None = None,
    hermes_environment: Path | None = None,
    browser_path: Path | None = None,
    api_host: str = "127.0.0.1",
    web_host: str = "127.0.0.1",
    cors_origins: Sequence[str] = ("http://127.0.0.1:3000",),
    require_node: bool = True,
    require_browser: bool = True,
) -> DiagnosticReport:
    """Return a support-friendly report without reading project/source files."""

    python = python_executable or sys.executable
    node = node_executable or shutil.which("node") or "node"
    runtime = hermes_environment or root / ".hermes-runtime"
    browser = browser_path or Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", root / ".playwright"))
    checks: list[Diagnostic] = [
        _check_version("python", [python, "--version"], MIN_PYTHON, "Python"),
    ]
    if require_node:
        checks.append(_check_version("node", [node, "--version"], MIN_NODE, "Node.js"))
    package_json = root / "dashboard" / "web" / "package.json"
    checks.append(Diagnostic("application", package_json.is_file(), f"Application root: {root}", "Reinstall the application files."))
    hermes_binary = runtime / ("Scripts/hermes.exe" if platform.system() == "Windows" else "bin/hermes")
    checks.append(Diagnostic("hermes-runtime", hermes_binary.is_file(), f"Managed Hermes runtime: {runtime}", "Run the installer again to provision Hermes."))
    if require_browser:
        checks.append(_browser_check(python, browser))
    checks.extend(check_network_configuration(api_host=api_host, web_host=web_host, cors_origins=cors_origins))
    return DiagnosticReport(platform=platform.system().lower(), checks=tuple(checks))


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Read-only local installation diagnostics")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--browser-path", type=Path)
    parser.add_argument("--python", dest="python_executable")
    parser.add_argument("--node", dest="node_executable")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--no-node", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    report = run_diagnostics(
        root=args.root,
        python_executable=args.python_executable,
        node_executable=args.node_executable,
        hermes_environment=args.runtime,
        browser_path=args.browser_path,
        require_node=not args.no_node,
        require_browser=not args.no_browser,
    )
    if args.as_json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print(f"Universal Dashboard diagnostics: {'PASS' if report.ok else 'ATTENTION REQUIRED'}")
        for check in report.checks:
            print(f"{'OK' if check.ok else '!!'} {check.name}: {check.detail}")
            if not check.ok and check.remediation:
                print(f"   {check.remediation}")
    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover - exercised by installers
    raise SystemExit(_cli())
