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
_ANSI_ESCAPE_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_MAX_LIFETIME = 15 * 60


@dataclass
class _Session:
    session_id: str
    project_id: str | None
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
        # Hermes is a Python CLI. When stdout is a pipe, its device-login
        # instructions would otherwise remain buffered until the process exits.
        environment["PYTHONUNBUFFERED"] = "1"
        runtime = Path(os.environ.get("DASHBOARD_HERMES_RUNTIME", Path.cwd() / ".hermes-runtime"))
        home = Path(os.environ.get("DASHBOARD_HERMES_HOME", runtime.parent / ".hermes-data")).resolve()
        environment["HERMES_HOME"] = str(home)
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

    def start(self, project_id: str | None = None) -> dict[str, object]:
        with self._lock:
            for session in self._sessions.values():
                if session.project_id == project_id and session.status == "pending":
                    return self.public_status(session.session_id)
            session = _Session(session_id=uuid4().hex, project_id=project_id)
            self._sessions[session.session_id] = session

        if self._already_connected():
            connected = self._select_model()
            with session.lock:
                if connected:
                    session.status = "connected"
                else:
                    session.status = "failed"
                    session.error_message = "Codex is authenticated but gpt-5.5 could not be selected"
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
            # The read loop below blocks on process output, which never arrives
            # while Hermes is only waiting on the user. This timer enforces the
            # lifetime bound even when the loop never observes it.
            timer = threading.Timer(_MAX_LIFETIME + 1, self._terminate, args=(session, "expired"))
            timer.daemon = True
            timer.start()
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
            try:
                return_code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                return_code = process.wait()
            if return_code == 0:
                if self._select_model():
                    status, error_message = "connected", None
                else:
                    status, error_message = "failed", "Codex is authenticated but gpt-5.5 could not be selected"
            else:
                status, error_message = "failed", "Provider authentication failed"
            changed = False
            with session.lock:
                if session.status == "pending":
                    session.status = status
                    session.error_message = error_message
                    changed = True
            if changed:
                support_events.record("codex_oauth_completed", level="INFO" if status == "connected" else "WARNING", details={"status": status, "component": "oauth"})
        except (OSError, subprocess.SubprocessError):
            with session.lock:
                if session.status == "pending":
                    session.status = "failed"
                    session.error_message = "Provider authentication failed"
        finally:
            if process.stdin:
                try:
                    process.stdin.close()
                except OSError:
                    pass

    @staticmethod
    def _parse_line(session: _Session, line: str) -> None:
        sanitized = _ANSI_ESCAPE_RE.sub("", line)
        lowered = sanitized.casefold()
        if "use existing credentials" in lowered and session.process and session.process.stdin:
            try:
                session.process.stdin.write("y\n")
                session.process.stdin.flush()
            except OSError:
                pass
        url = _URL_RE.search(sanitized)
        if url and ("verification" in lowered or "auth" in lowered or "open this url" in lowered):
            session.verification_url = url.group(0).rstrip(".,")
        stripped = sanitized.strip().upper()
        codes = _CODE_RE.findall(stripped) if "code" in lowered else []
        if not codes and _CODE_RE.fullmatch(stripped):
            codes = [stripped]
        if codes:
            candidate = codes[-1].replace(" ", "-")
            if "-" in candidate:
                session.user_code = candidate

    def _select_model(self) -> bool:
        return select_hermes_model("openai-codex", "gpt-5.5")

    def _terminate(self, session: _Session, status: str) -> None:
        with session.lock:
            if session.status != "pending":
                return
            session.status = status
            process = session.process
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        if process and process.stdin:
            try:
                process.stdin.close()
            except OSError:
                pass
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
        self._terminate(session, "cancelled")

    def public_status(self, session_id: str) -> dict[str, object]:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
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
            self._terminate(session, "cancelled")


def select_hermes_model(hermes_provider: str, model: str) -> bool:
    """Point the local Hermes config at the given provider/model pair.

    Shared by the Codex OAuth flow and the API-key connect flow so switching
    providers always repoints Hermes instead of leaving it pinned to
    whichever provider last called this.
    """

    environment = CodexOAuthManager._environment()
    executable = CodexOAuthManager._executable()
    selected = True
    for key, value in (("model.provider", hermes_provider), ("model.default", model)):
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


codex_oauth = CodexOAuthManager()
