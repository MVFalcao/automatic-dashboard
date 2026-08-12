"""Managed, authenticated loopback gateway for Hermes Agent."""

from __future__ import annotations

import ipaddress
import os
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path
from subprocess import Popen

from pydantic import BaseModel, ConfigDict, Field, field_validator

from automation.agent.credentials import CredentialReference, CredentialStore


def _is_loopback(value: str) -> bool:
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


class GatewayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    port: int = Field(default=8642, ge=1024, le=65535)
    api_key_reference: CredentialReference
    cors_origins: tuple[str, ...] = ()

    @field_validator("host")
    @classmethod
    def loopback_only(cls, value: str) -> str:
        if not _is_loopback(value):
            raise ValueError("Hermes gateway must bind to loopback (127.0.0.1 or localhost)")
        return value


@dataclass
class GatewayProcess:
    process: Popen[bytes]
    config: GatewayConfig

    @property
    def address(self) -> str:
        return f"http://{self.config.host}:{self.config.port}"

    def stop(self, timeout: float = 5.0) -> None:
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=timeout)


class HermesGateway:
    """Build and start a Hermes gateway without ever writing its API key."""

    def __init__(self, credential_store: CredentialStore) -> None:
        self.credential_store = credential_store
        self._process: GatewayProcess | None = None

    @staticmethod
    def create_api_key_reference(service: str = "universal-dashboard-agent") -> CredentialReference:
        return CredentialReference(service=service, account=secrets.token_urlsafe(18))

    def start(
        self,
        config: GatewayConfig,
        executable: str,
        *,
        extra_environment: dict[str, str] | None = None,
        dry_run: bool = False,
    ) -> GatewayProcess | list[str]:
        if self._process is not None and self._process.process.poll() is None:
            raise RuntimeError("Hermes gateway is already running")
        secret = self.credential_store.get(config.api_key_reference)
        if not secret:
            raise RuntimeError("Hermes gateway API key is missing from the OS credential store")
        command = [executable, "gateway"]
        environment = os.environ.copy()
        environment.update(
            {
                "API_SERVER_ENABLED": "true",
                "API_SERVER_HOST": config.host,
                "API_SERVER_PORT": str(config.port),
                "API_SERVER_KEY": secret,
            }
        )
        if config.cors_origins:
            environment["API_SERVER_CORS_ORIGINS"] = ",".join(config.cors_origins)
        if extra_environment:
            environment.update(extra_environment)
        if dry_run:
            return command
        process = subprocess.Popen(command, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self._process = GatewayProcess(process=process, config=config)
        return self._process

    def stop(self) -> None:
        if self._process is not None:
            self._process.stop()
            self._process = None

    @property
    def process(self) -> GatewayProcess | None:
        return self._process

