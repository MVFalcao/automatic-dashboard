"""First-run diagnostics and provider login guidance.

Provider authentication is intentionally delegated to Hermes.  This command
prints commands and links only; it never asks for or stores a provider secret.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from automation.agent.models import ProviderName
from automation.agent.routing import setup_instructions


def main() -> int:
    parser = argparse.ArgumentParser(description="Guide the first local dashboard setup")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--diagnostics-only", action="store_true")
    args = parser.parse_args()
    from automation.release.diagnostics import run_diagnostics

    report = run_diagnostics(root=args.root, hermes_environment=args.runtime)
    print(f"Diagnostics: {'PASS' if report.ok else 'ATTENTION REQUIRED'}")
    for check in report.checks:
        if not check.ok:
            print(f"- {check.name}: {check.detail}. {check.remediation or ''}")
    if args.diagnostics_only:
        return 0 if report.ok else 1
    print("\nConnect an AI provider through the managed Hermes runtime (no secrets are stored in project files):")
    for provider in ProviderName:
        instructions = setup_instructions(provider)
        command = " ".join(instructions.oauth_command or ["Set the provider key in the OS credential store"])
        print(f"- {provider.value}: {command}")
    print("\nAfter login, open http://127.0.0.1:3000 in your browser.")
    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
