from __future__ import annotations

import os
import importlib.util
from pathlib import Path

from automation.release.diagnostics import check_network_configuration, run_diagnostics
from dashboard.api.security import is_loopback_host, security_enabled

_ASSEMBLER = Path(__file__).parents[1] / "scripts" / "assemble-release.py"
_ASSEMBLER_SPEC = importlib.util.spec_from_file_location("dashboard_release_assembler", _ASSEMBLER)
assert _ASSEMBLER_SPEC and _ASSEMBLER_SPEC.loader
_ASSEMBLER_MODULE = importlib.util.module_from_spec(_ASSEMBLER_SPEC)
_ASSEMBLER_SPEC.loader.exec_module(_ASSEMBLER_MODULE)
copy_tree = _ASSEMBLER_MODULE.copy_tree


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


def test_release_diagnostics_detects_installed_playwright(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_LOCAL_AUTH_TOKEN", "test-token")
    (tmp_path / "dashboard" / "web").mkdir(parents=True)
    (tmp_path / "dashboard" / "web" / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".hermes-runtime" / "bin").mkdir(parents=True)
    (tmp_path / ".hermes-runtime" / "bin" / "hermes").write_text("managed", encoding="utf-8")
    browser_path = tmp_path / ".playwright"
    browser_path.mkdir()

    report = run_diagnostics(
        root=tmp_path,
        python_executable=os.sys.executable,
        require_node=False,
        browser_path=browser_path,
    )

    assert report.ok
    assert next(check for check in report.checks if check.name == "playwright-chromium").ok


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
        assert "aiohttp==3.13.3" in installer
        assert "playwright" in installer.casefold()
    assert "\nsudo " not in linux
    assert 'runtime/node/bin/node' in linux
    assert '--browser-path "$BASE_DIR/.playwright"' in linux
    assert '--node "$BASE_DIR/runtime/node/bin/node"' in linux
    assert "--exclude=./reports" in linux
    assert "--exclude=reports" not in linux
    assert "robocopy" in windows
    assert '"dashboard\\web\\node_modules"' in windows
    assert '"dashboard\\web\\.next"' in windows
    assert 'Join-Path $Source $_' in windows
    assert "gateway stop" in windows
    assert "--browser-path '$playwright'" in windows
    assert "--node '$node'" in windows


def test_release_copy_preserves_standalone_dependencies_only(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "node_modules").mkdir(parents=True)
    (source / "node_modules" / "development.js").write_text("private build dependency", encoding="utf-8")
    web_modules = source / "dashboard" / "web" / "node_modules"
    web_modules.mkdir(parents=True)
    (web_modules / "development.js").write_text("web build dependency", encoding="utf-8")
    standalone = source / "dashboard" / "web" / ".next" / "standalone" / "node_modules" / "next"
    standalone.mkdir(parents=True)
    (standalone / "server.js").write_text("packaged runtime dependency", encoding="utf-8")
    (source / "dashboard" / "web" / ".next" / "cache").mkdir(parents=True)
    (source / "dashboard" / "web" / ".next" / "cache" / "trace").write_text("build cache", encoding="utf-8")

    destination = tmp_path / "bundle"
    copy_tree(source, destination)

    assert not (destination / "node_modules").exists()
    assert not (destination / "dashboard" / "web" / "node_modules").exists()
    assert not (destination / "dashboard" / "web" / ".next" / "cache").exists()
    assert (destination / "dashboard" / "web" / ".next" / "standalone" / "node_modules" / "next" / "server.js").is_file()


def test_release_copy_excludes_local_test_and_secret_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "build").mkdir(parents=True)
    (source / "build" / "local-wheel.whl").write_bytes(b"development build")
    (source / "dashboard" / "web" / ".next" / "cache").mkdir(parents=True)
    (source / "dashboard" / "web" / ".next" / "cache" / "compiler.bin").write_bytes(b"cache")
    (source / "dashboard" / "web" / ".next" / "dev").mkdir(parents=True)
    (source / "dashboard" / "web" / ".next" / "dev" / "development.log").write_text("local path", encoding="utf-8")
    (source / "dashboard" / "web" / "test-results").mkdir(parents=True)
    (source / "dashboard" / "web" / "test-results" / "trace.zip").write_bytes(b"trace")
    (source / "dashboard" / "web" / "tsconfig.tsbuildinfo").write_text("local path", encoding="utf-8")
    (source / ".env").write_text("SECRET=value", encoding="utf-8")
    (source / "private_source_example.xlsx").write_bytes(b"private")

    destination = tmp_path / "bundle"
    copy_tree(source, destination)

    assert not (destination / "build").exists()
    assert not (destination / "dashboard" / "web" / ".next" / "cache").exists()
    assert not (destination / "dashboard" / "web" / ".next" / "dev").exists()
    assert not (destination / "dashboard" / "web" / "test-results").exists()
    assert not (destination / "dashboard" / "web" / "tsconfig.tsbuildinfo").exists()
    assert not (destination / ".env").exists()
    assert not (destination / "private_source_example.xlsx").exists()
