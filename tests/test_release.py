from __future__ import annotations

import os
from pathlib import Path

from automation.release.diagnostics import check_network_configuration, run_diagnostics
from dashboard.api.security import is_loopback_host, security_enabled


def test_release_diagnostics_reports_managed_components_without_reading_project_data(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_LOCAL_AUTH_TOKEN", "test-token")
    (tmp_path / "dashboard" / "web").mkdir(parents=True)
    (tmp_path / "dashboard" / "web" / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".hermes-runtime" / "bin").mkdir(parents=True)
    (tmp_path / ".hermes-runtime" / "bin" / "hermes").write_text("managed", encoding="utf-8")
    report = run_diagnostics(
        root=tmp_path,
        python_executable=os.environ.get("PYTHON", os.sys.executable),
        require_node=False,
        require_browser=False,
    )
    assert report.ok
    assert {check.name for check in report.checks} >= {"python", "application", "hermes-runtime", "local-auth"}


def test_release_network_checks_reject_lan_hosts_and_wildcard_cors() -> None:
    checks = check_network_configuration(
        api_host="0.0.0.0",
        web_host="192.168.1.20",
        cors_origins=("*",),
    )
    assert all(not check.ok for check in checks[:3])
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("::1")
    assert not is_loopback_host("192.168.1.20")


def test_local_security_is_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("DASHBOARD_ENFORCE_LOCAL_SECURITY", raising=False)
    assert security_enabled() is False
    monkeypatch.setenv("DASHBOARD_ENFORCE_LOCAL_SECURITY", "true")
    assert security_enabled() is True


def test_installers_are_user_scoped_and_loopback_only() -> None:
    root = Path(__file__).parents[1]
    linux = (root / "scripts" / "install-linux.sh").read_text(encoding="utf-8")
    windows = (root / "scripts" / "install-windows.ps1").read_text(encoding="utf-8")
    for installer in (linux, windows):
        assert "127.0.0.1" in installer
        assert "hermes-agent==0.13.0" in installer
        assert "playwright" in installer.casefold()
    assert "\nsudo " not in linux
    assert "robocopy" in windows
