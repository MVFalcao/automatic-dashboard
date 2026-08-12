"""Pinned Hermes runtime provisioning and executable resolution."""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from automation.agent.gateway import GatewayConfig, HermesGateway


# Keep this pin in one place so installers and diagnostics can report exactly
# which runtime is managed by the dashboard application.
HERMES_PACKAGE = "hermes-agent"
HERMES_VERSION = "0.13.0"


class HermesRuntimeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_dir: Path
    package: str = Field(default=HERMES_PACKAGE, pattern="^hermes-agent$")
    version: str = Field(default=HERMES_VERSION, pattern=r"^\d+\.\d+\.\d+$")
    python_executable: str | None = None

    @property
    def python(self) -> str:
        if self.python_executable:
            return self.python_executable
        binary = "Scripts/python.exe" if platform.system() == "Windows" else "bin/python"
        return str(self.environment_dir / binary)

    @property
    def hermes_executable(self) -> str:
        binary = "Scripts/hermes.exe" if platform.system() == "Windows" else "bin/hermes"
        return str(self.environment_dir / binary)

    @property
    def requirement(self) -> str:
        return f"{self.package}=={self.version}"


class HermesRuntime:
    """Manage a private virtual environment; never use a global Hermes binary."""

    def __init__(self, spec: HermesRuntimeSpec) -> None:
        self.spec = spec

    def install_command(self) -> list[str]:
        return [self.spec.python, "-m", "pip", "install", "--upgrade", self.spec.requirement]

    def install(self, *, check: bool = True) -> subprocess.CompletedProcess[str]:
        self.spec.environment_dir.mkdir(parents=True, exist_ok=True)
        return subprocess.run(self.install_command(), check=check, text=True, capture_output=True)

    def gateway_command(self) -> list[str]:
        return [self.spec.hermes_executable, "gateway"]

    def start_gateway(
        self,
        gateway: HermesGateway,
        config: GatewayConfig,
        *,
        dry_run: bool = False,
    ):
        return gateway.start(config, self.spec.hermes_executable, dry_run=dry_run)

