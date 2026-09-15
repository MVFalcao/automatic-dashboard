from __future__ import annotations

import time

from automation.agent.oauth import CodexOAuthManager, _Session


class _FakeProcess:
    def __init__(self, lines: list[str], returncode: int = 0) -> None:
        self.stdout = iter(lines)
        self.stdin = self
        self.returncode = returncode
        self.terminated = False

    def write(self, _: str) -> None:
        return None

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None

    def poll(self) -> int | None:
        return None if not self.terminated else -15

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.terminated = True


def test_oauth_public_status_contains_only_device_metadata(monkeypatch) -> None:
    manager = CodexOAuthManager()
    fake = _FakeProcess([
        "To continue, follow these steps:\n",
        "  1. Open this URL in your browser:\n",
        "     \x1b[94mhttps://auth.example.test/device\x1b[0m\n",
        "  2. Enter this code:\n",
        "     \x1b[94mABCD-EFGH\x1b[0m\n",
    ])
    monkeypatch.setattr(manager, "_already_connected", lambda: False)
    monkeypatch.setattr(manager, "_select_model", lambda: True)
    monkeypatch.setattr("automation.agent.oauth.subprocess.Popen", lambda *args, **kwargs: fake)

    result = manager.start("project-1")
    for _ in range(20):
        result = manager.status(result["session_id"])
        if result["status"] != "pending":
            break
        time.sleep(0.01)

    assert result["status"] == "connected"
    assert result["verification_url"] == "https://auth.example.test/device"
    assert result["user_code"] == "ABCD-EFGH"
    assert "token" not in str(result).casefold()
    assert "access" not in str(result).casefold()


def test_oauth_process_output_is_unbuffered_and_uses_application_home(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DASHBOARD_HERMES_RUNTIME", str(tmp_path / ".hermes-runtime"))
    monkeypatch.delenv("DASHBOARD_HERMES_HOME", raising=False)
    environment = CodexOAuthManager._environment()
    assert environment["PYTHONUNBUFFERED"] == "1"
    assert environment["HERMES_HOME"] == str((tmp_path / ".hermes-data").resolve())


def test_oauth_start_is_idempotent_per_project(monkeypatch) -> None:
    manager = CodexOAuthManager()
    monkeypatch.setattr(manager, "_already_connected", lambda: False)
    monkeypatch.setattr(manager, "_select_model", lambda: None)
    monkeypatch.setattr(manager, "_consume", lambda session: None)
    monkeypatch.setattr("automation.agent.oauth.subprocess.Popen", lambda *args, **kwargs: _FakeProcess([]))
    first = manager.start("project-1")
    second = manager.start("project-1")
    assert first["session_id"] == second["session_id"]


def test_oauth_start_is_global_before_a_project_exists(monkeypatch) -> None:
    manager = CodexOAuthManager()
    monkeypatch.setattr(manager, "_already_connected", lambda: False)
    monkeypatch.setattr(manager, "_consume", lambda session: None)
    monkeypatch.setattr("automation.agent.oauth.subprocess.Popen", lambda *args, **kwargs: _FakeProcess([]))
    first = manager.start()
    second = manager.start()
    assert first["project_id"] is None
    assert first["session_id"] == second["session_id"]


def test_oauth_cancel_terminates_pending_process(monkeypatch) -> None:
    manager = CodexOAuthManager()
    fake = _FakeProcess([])
    monkeypatch.setattr(manager, "_already_connected", lambda: False)
    monkeypatch.setattr(manager, "_select_model", lambda: None)
    monkeypatch.setattr(manager, "_consume", lambda session: None)
    monkeypatch.setattr("automation.agent.oauth.subprocess.Popen", lambda *args, **kwargs: fake)
    result = manager.start("project-1")
    manager.cancel(result["session_id"])
    assert manager.status(result["session_id"])["status"] == "cancelled"
    assert fake.terminated is True


def test_oauth_expiration_is_publicly_sanitized() -> None:
    manager = CodexOAuthManager()
    session = _Session(session_id="session", project_id="project")
    session.expires_at = 0
    manager._sessions[session.session_id] = session
    result = manager.status(session.session_id)
    assert result["status"] == "expired"
    assert result["expires_in"] == 0


def test_oauth_process_failure_is_recoverable(monkeypatch) -> None:
    manager = CodexOAuthManager()
    fake = _FakeProcess([], returncode=1)
    monkeypatch.setattr(manager, "_already_connected", lambda: False)
    monkeypatch.setattr("automation.agent.oauth.subprocess.Popen", lambda *args, **kwargs: fake)
    result = manager.start("project-1")
    for _ in range(20):
        result = manager.status(result["session_id"])
        if result["status"] != "pending":
            break
        time.sleep(0.01)
    assert result["status"] == "failed"
    assert result["recoverable"] is True
    assert result["remediation"] == "Start a new browser login."


def test_oauth_model_incompatibility_is_reported(monkeypatch) -> None:
    manager = CodexOAuthManager()
    monkeypatch.setattr(manager, "_already_connected", lambda: True)
    monkeypatch.setattr(manager, "_select_model", lambda: False)
    result = manager.start("project-1")
    assert result["status"] == "failed"
    assert result["compatible"] is False
    assert "gpt-5.5" in str(result["error"])
