"""Strict, provider-neutral models used by the Hermes adapter."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from automation.agent.credentials import CredentialReference, NativeOAuthReference


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderName(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"
    GEMINI = "gemini"
    DEEPSEEK = "deepseek"


class AuthMethod(StrEnum):
    API_KEY = "api_key"
    OAUTH = "oauth"


class TaskCapability(StrEnum):
    CONVERSATION = "conversation"
    DISCOVERY = "discovery"
    STRUCTURED_OUTPUT = "structured_output"
    VISION = "vision"
    INSIGHTS = "insights"


class TokenEstimate(StrictModel):
    """Expected input/output usage for one provider/model pair.

    Estimates are routing hints only.  They never replace usage reported by
    Hermes after execution.
    """

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    fixed_overhead_tokens: int = Field(default=0, ge=0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.fixed_overhead_tokens


class ProviderConnection(StrictModel):
    provider: ProviderName
    account_id: str = Field(min_length=1, max_length=160)
    model: str = Field(min_length=1, max_length=200)
    auth_method: AuthMethod
    credential: CredentialReference | NativeOAuthReference
    capabilities: set[TaskCapability] = Field(default_factory=lambda: {TaskCapability.CONVERSATION})
    token_estimate: TokenEstimate
    connected: bool = True

    @model_validator(mode="after")
    def validate_credential_kind(self) -> "ProviderConnection":
        if self.auth_method is AuthMethod.API_KEY and not isinstance(self.credential, CredentialReference):
            raise ValueError("API-key connections require an OS credential reference")
        if self.auth_method is AuthMethod.OAUTH and not isinstance(self.credential, NativeOAuthReference):
            raise ValueError("OAuth connections require a Hermes/provider protected-store reference")
        return self


class ProviderSetupInstructions(StrictModel):
    provider: ProviderName
    hermes_provider: str
    supported_auth: list[AuthMethod] = Field(min_length=1)
    api_key_environment_variable: str | None = None
    setup_command: list[str] = Field(min_length=1)
    oauth_command: list[str] | None = None
    documentation_url: str = Field(min_length=1)
    credential_policy: str = Field(min_length=1)


class TaskRequest(StrictModel):
    task_id: str = Field(min_length=1, max_length=160)
    task: str = Field(min_length=1, max_length=200)
    input: dict[str, Any] = Field(default_factory=dict)
    estimated_input_tokens: int = Field(default=0, ge=0)
    estimated_output_tokens: int = Field(default=0, ge=0)
    required_capabilities: set[TaskCapability] = Field(default_factory=lambda: {TaskCapability.CONVERSATION})
    requested_provider: ProviderName | None = None


class TaskResponse(StrictModel):
    task_id: str = Field(min_length=1)
    provider: ProviderName
    model: str = Field(min_length=1)
    output: dict[str, Any]
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    structured: bool = True

