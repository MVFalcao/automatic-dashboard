from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_release_version_is_coherent() -> None:
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "check-version.py"), "--tag", "v0.2.0"], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "0.2.0"


def test_release_version_rejects_mismatched_tag() -> None:
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "check-version.py"), "--tag", "v9.9.9"], capture_output=True, text=True)
    assert result.returncode != 0


def test_inno_setup_is_user_scoped_and_offline() -> None:
    script = (ROOT / "scripts" / "UniversalDashboardAgent.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in script
    assert "UniversalDashboardAgent-bundle" in script
    assert "install-windows.ps1" in script
    assert "Uninstallable=no" in script
    # Inno Setup escapes embedded quotes by doubling them, not with backslashes.
    assert '\\"' not in script
    assert '#define AppVersion "0.2.0"' in script
    assert 'InstallDir ""{app}""' in script


def test_release_workflow_has_dry_run_artifacts_and_manual_publish_gate() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "dry-run" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "Create draft GitHub Release" in workflow
    assert "gh release create" in workflow
    assert "gh release edit" not in workflow
    assert "--draft" in workflow
    assert "$releaseExists = $LASTEXITCODE -eq 0" in workflow
    assert "$global:LASTEXITCODE = 0" in workflow
    assert "scripts\\test-windows-release.ps1" in workflow
    assert "Windows release acceptance test failed" in workflow


def test_windows_installer_has_transactional_upgrade_guards() -> None:
    installer = (ROOT / "scripts" / "install-windows.ps1").read_text(encoding="utf-8")
    assert "[string]$Source," in installer
    assert "if (-not $Source) { $Source = Split-Path -Parent $PSScriptRoot }" in installer
    assert "$originalError = $_" in installer
    assert "throw $originalError" in installer
    assert ".upgrade-backup" in installer
    assert "Move-Item -LiteralPath $backupDir -Destination $InstallDir" in installer
    assert '".hermes-data", "config", "projects.json"' in installer
    assert "application-version.json" in installer


def test_windows_release_acceptance_is_shared_and_checks_installed_files() -> None:
    script = (ROOT / "scripts" / "test-windows-release.ps1").read_text(encoding="utf-8")
    assert "$process = Start-Process" in script
    assert "-Wait -PassThru" in script
    assert "$process.ExitCode" in script
    assert '"scripts\\smoke-test-install.ps1"' in script
    assert '"scripts\\uninstall-windows.ps1"' in script
    assert "Synthetic failed upgrade unexpectedly succeeded" in script
    assert "Uninstall left the test installation behind" in script
    preflight = (ROOT / "scripts" / "test-release-local.sh").read_text(encoding="utf-8")
    assert "check-powershell-syntax.ps1" in preflight


def test_inno_setup_propagates_application_install_failure() -> None:
    script = (ROOT / "scripts" / "UniversalDashboardAgent.iss").read_text(encoding="utf-8")
    assert "procedure CurStepChanged" in script
    assert "ExecAndLogOutput" in script
    assert "ewWaitUntilTerminated" in script
    assert "if ResultCode <> 0 then" in script
    assert "Application installation failed with exit code" in script


def test_release_manifest_writer_records_artifact_metadata(tmp_path: Path) -> None:
    setup = tmp_path / "setup.exe"
    setup.write_bytes(b"synthetic setup")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.sha256").write_text("synthetic\n", encoding="utf-8")
    output = tmp_path / "manifest.json"
    subprocess.run([
        sys.executable,
        str(ROOT / "scripts" / "write-release-manifest.py"),
        "--version",
        "0.2.0",
        "--setup",
        str(setup),
        "--bundle",
        str(bundle),
        "--output",
        str(output),
        "--python-version", "3.12.10",
        "--node-version", "24.18.0",
        "--hermes-version", "0.13.0",
        "--playwright-version", "1.55.1",
        "--chromium-version", "synthetic-revision",
        "--installer-version", "Inno Setup 6.7.1",
    ], check=True)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["platform"] == "windows"
    assert payload["installer"]["filename"] == "setup.exe"
    assert payload["schema_version"] == 2
    assert payload["runtimes"]["node"] == "24.18.0"
