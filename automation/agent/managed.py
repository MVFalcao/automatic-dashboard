"""Application-lifespan owner for the pinned Hermes gateway."""

from __future__ import annotations

import os
import secrets
import time
from pathlib import Path
from threading import RLock
from typing import Any

from automation.agent.client import HermesClient
from automation.agent.credentials import CredentialReference, KeyringCredentialStore
from automation.agent.gateway import GatewayConfig, HermesGateway
from automation.agent.runtime import HERMES_PACKAGE, HERMES_VERSION, HermesRuntime, HermesRuntimeSpec


class ManagedHermesService:
    def __init__(self) -> None:
        self._lock = RLock()
        self.gateway: HermesGateway | None = None
        self.client: HermesClient | None = None
        self.home: Path | None = None
        self._status: dict[str, Any] = {
            "managed": True, "package": HERMES_PACKAGE, "version": HERMES_VERSION,
            "process_running": False, "gateway_authenticated": False,
            "healthy": False, "ready": False, "provider_count": 0,
            "remediation": "Managed Hermes has not started.",
        }

    def start(self) -> None:
        runtime_root = Path(os.environ.get("DASHBOARD_HERMES_RUNTIME", Path.cwd() / ".hermes-runtime")).resolve()
        runtime = HermesRuntime(HermesRuntimeSpec(environment_dir=runtime_root))
        executable = Path(runtime.spec.hermes_executable)
        if not executable.is_file():
            self._set(remediation="Install the bundled hermes-agent==0.13.0 runtime and restart the application.")
            return
        try:
            credentials = KeyringCredentialStore()
            reference = CredentialReference(service="universal-dashboard-agent", account="managed-hermes-gateway")
            secret = credentials.get(reference)
            if not secret:
                secret = secrets.token_urlsafe(48)
                credentials.put(reference, secret)
            port = int(os.environ.get("DASHBOARD_HERMES_PORT", "8642"))
            hermes_home = Path(os.environ.get("DASHBOARD_HERMES_HOME", runtime_root.parent / ".hermes-data")).resolve()
            (hermes_home / "scripts").mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(hermes_home, 0o700)
                os.chmod(hermes_home / "scripts", 0o700)
            except OSError:
                pass
            config = GatewayConfig(
                host="127.0.0.1", port=port, api_key_reference=reference,
                cors_origins=tuple(origin for origin in os.environ.get("DASHBOARD_ALLOWED_ORIGINS", "").split(",") if origin),
            )
            gateway = HermesGateway(credentials)
            gateway_process = gateway.start(config, runtime.spec.hermes_executable, extra_environment={"HERMES_HOME": str(hermes_home)})
            client = HermesClient(gateway_process.address, secret)
            deadline = time.monotonic() + 8
            last_error: Exception | None = None
            while time.monotonic() < deadline:
                if gateway_process.process.poll() is not None:
                    break
                try:
                    client.health()
                    self.gateway, self.client, self.home = gateway, client, hermes_home
                    self._set(process_running=True, gateway_authenticated=True, healthy=True, ready=True, remediation=None)
                    return
                except Exception as exc:  # gateway needs a short boot window
                    last_error = exc
                    time.sleep(0.2)
            gateway.stop()
            self._set(remediation="Hermes started but did not pass its authenticated health check.")
        except Exception as exc:
            # Never expose backend/keyring exception messages: some backends
            # include paths or account details.
            self._set(remediation="The OS credential store is unavailable. Enable a supported keyring backend and restart.")

    def stop(self) -> None:
        with self._lock:
            if self.gateway is not None:
                self.gateway.stop()
            self.gateway = None
            self.client = None
            self.home = None
            self._status.update({"process_running": False, "gateway_authenticated": False, "healthy": False, "ready": False})

    def _set(self, **values: Any) -> None:
        with self._lock:
            self._status.update(values)

    def status(self) -> dict[str, Any]:
        with self._lock:
            status = dict(self._status)
            if self.gateway and self.gateway.process:
                status["process_running"] = self.gateway.process.process.poll() is None
                status["ready"] = bool(status["process_running"] and status["healthy"] and status["gateway_authenticated"])
            return status


managed_hermes = ManagedHermesService()
