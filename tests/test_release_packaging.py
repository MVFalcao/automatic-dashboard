from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_release_version_is_coherent() -> None:
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "check-version.py"), "--tag", "v0.1.0"], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "0.1.0"


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
        "0.1.0",
        "--setup",
        str(setup),
        "--bundle",
        str(bundle),
        "--output",
        str(output),
    ], check=True)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["platform"] == "windows"
    assert payload["installer"]["filename"] == "setup.exe"
