#!/usr/bin/env bash
# Local pre-push release checks. The Windows artifact acceptance phase is
# implemented in test-windows-release.ps1 and is also called by GitHub Actions.
set -euo pipefail

project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project_root"

expected_node=$(tr -d '[:space:]' < .nvmrc)
actual_node=$(node --version 2>/dev/null | sed 's/^v//' || true)
if [[ "$actual_node" != "$expected_node" ]]; then
    printf 'Node.js %s is required (found %s). Run: source ~/.nvm/nvm.sh && nvm use\n' "$expected_node" "${actual_node:-missing}" >&2
    exit 1
fi

python_cmd=.venv/bin/python
if [[ ! -x "$python_cmd" ]]; then python_cmd=python3; fi
"$python_cmd" scripts/check-version.py
"$python_cmd" -m pytest -q tests/test_release_packaging.py
npm --prefix dashboard/web ci
npm --prefix dashboard/web run check
npm --prefix dashboard/web run build
git diff --check

if command -v powershell.exe >/dev/null 2>&1 && command -v wslpath >/dev/null 2>&1; then
    checker_path=$(wslpath -w "$project_root/scripts/check-powershell-syntax.ps1")
    for script in scripts/install-windows.ps1 scripts/uninstall-windows.ps1 scripts/smoke-test-install.ps1 scripts/test-windows-release.ps1; do
        windows_path=$(wslpath -w "$project_root/$script")
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$checker_path" -Path "$windows_path"
    done
fi

printf 'PASS: local version, packaging, frontend, diff, and PowerShell checks passed.\n'
