"""Safe, process-owned OAuth session orchestration for local provider setup."""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from automation.release.support import support_events


_URL_RE = re.compile(r"https?://[^\s)]+", re.IGNORECASE)
_CODE_RE = re.compile(r"\b([A-Z0-9]{4,}(?:[- ][A-Z0-9]{3,})+)\b")
_MAX_LIFETIME = 15 * 60


@dataclass
class _Session:
    session_id: str
    project_id: str
    status: str = "pending"
    verification_url: str | None = None
    user_code: str | None = None
    expires_at: float = field(default_factory=lambda: time.monotonic() + _MAX_LIFETIME)
    process: subprocess.Popen[str] | None = None
    error_message: str | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)


class CodexOAuthManager:
    """Own one bounded Hermes device-login process per dashboard session.

    Only sanitized device-login metadata leaves this class. Hermes continues to
    own the OAuth tokens in its protected auth store.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _executable() -> str:
        configured = os.environ.get("DASHBOARD_HERMES_EXECUTABLE")
        if configured:
            return configured
        runtime = Path(os.environ.get("DASHBOARD_HERMES_RUNTIME", Path.cwd() / ".hermes-runtime"))
        return str(runtime / ("Scripts/hermes.exe" if os.name == "nt" else "bin/hermes"))

    @staticmethod
    def _environment() -> dict[str, str]:
        environment = os.environ.copy()
        home = os.environ.get("DASHBOARD_HERMES_HOME")
        if home:
            environment["HERMES_HOME"] = home
        return environment

    def _already_connected(self) -> bool:
        try:
            result = subprocess.run(
                [self._executable(), "auth", "list"],
                env=self._environment(),
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        # Do not retain or expose command output; only inspect the provider id.
        return result.returncode == 0 and "openai-codex" in (result.stdout or "")

    def start(self, project_id: str) -> dict[str, object]:
        with self._lock:
            for session in self._sessions.values():
                if session.project_id == project_id and session.status == "pending":
                    return self.public_status(session.session_id)
            session = _Session(session_id=uuid4().hex, project_id=project_id)
            self._sessions[session.session_id] = session

        if self._already_connected():
            if self._select_model() is False:
                session.status = "failed"
                session.error_message = "Codex is authenticated but gpt-5.5 could not be selected"
            else:
                session.status = "connected"
            support_events.record("codex_oauth_existing", details={"status": session.status, "component": "oauth"})
            return self.public_status(session.session_id)

        try:
            process = subprocess.Popen(
                [self._executable(), "auth", "add", "openai-codex", "--type", "oauth", "--no-browser"],
                env=self._environment(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            session.process = process
            threading.Thread(target=self._consume, args=(session,), daemon=True, name=f"codex-oauth-{session.session_id[:8]}").start()
        except OSError:
            session.status = "failed"
            session.error_message = "Managed Hermes OAuth is unavailable"
            support_events.record("codex_oauth_start_failed", level="ERROR", details={"status": "failed", "component": "oauth"})
        return self.public_status(session.session_id)

    def _consume(self, session: _Session) -> None:
        process = session.process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                self._parse_line(session, line)
                if time.monotonic() >= session.expires_at:
                    self._terminate(session, "expired")
                    return
            return_code = process.wait(timeout=5)
            if session.status == "pending":
                if return_code == 0:
                    if self._select_model() is False:
                        session.status = "failed"
                        session.error_message = "Codex is authenticated but gpt-5.5 could not be selected"
                    else:
                        session.status = "connected"
                else:
                    session.status = "failed"
                    session.error_message = "Provider authentication failed"
                support_events.record("codex_oauth_completed", level="INFO" if session.status == "connected" else "WARNING", details={"status": session.status, "component": "oauth"})
        except (OSError, subprocess.SubprocessError):
            if session.status == "pending":
                session.status = "failed"
                session.error_message = "Provider authentication failed"

    @staticmethod
    def _parse_line(session: _Session, line: str) -> None:
        lowered = line.casefold()
        if "use existing credentials" in lowered and session.process and session.process.stdin:
            try:
                session.process.stdin.write("y\n")
                session.process.stdin.flush()
            except OSError:
                pass
        url = _URL_RE.search(line)
        if url and "verification" in lowered or (url and "auth" in lowered):
            session.verification_url = url.group(0).rstrip(".,")
        if "code" in lowered:
            tail = line.upper().rsplit("CODE", 1)[-1]
            codes = _CODE_RE.findall(tail)
            if codes:
                session.user_code = codes[-1].replace(" ", "-")

    def _select_model(self) -> bool:
        environment = self._environment()
        executable = self._executable()
        selected = True
        for key, value in (("model.provider", "openai-codex"), ("model.default", "gpt-5.5")):
            try:
                result = subprocess.run(
                    [executable, "config", "set", key, value],
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=15,
                    check=False,
                )
                selected = selected and result.returncode == 0
            except (OSError, subprocess.SubprocessError):
                selected = False
        return selected

    def _terminate(self, session: _Session, status: str) -> None:
        process = session.process
        session.status = status
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        support_events.record("codex_oauth_terminated", details={"status": status, "component": "oauth"})

    def status(self, session_id: str) -> dict[str, object]:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        if session.status == "pending" and time.monotonic() >= session.expires_at:
            self._terminate(session, "expired")
        return self.public_status(session_id)

    def cancel(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        if session.status == "pending":
            self._terminate(session, "cancelled")

    def public_status(self, session_id: str) -> dict[str, object]:
        with self._lock:
            session = self._sessions[session_id]
        recoverable = session.status in {"failed", "expired", "cancelled"}
        return {
            "session_id": session.session_id,
            "project_id": session.project_id,
            "status": session.status,
            "verification_url": session.verification_url,
            "user_code": session.user_code,
            "expires_in": max(0, int(session.expires_at - time.monotonic())),
            "error": session.error_message,
            "recoverable": recoverable,
            "remediation": "Start a new browser login." if recoverable else None,
            "provider": "openai-codex",
            "model": "gpt-5.5",
            "compatible": session.status == "connected",
        }

    def stop(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            if session.status == "pending":
                self._terminate(session, "cancelled")


codex_oauth = CodexOAuthManager()
