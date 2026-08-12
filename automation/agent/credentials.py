"""Credential references and secure-store adapters.

Project configuration stores only opaque references.  API keys are held by the
OS keychain (via ``keyring`` when installed); OAuth tokens remain in Hermes or
the provider's protected native store and are never returned by this module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CredentialReference(_Strict):
    """An opaque reference to an API key/app secret in the OS keychain."""

    backend: str = Field(default="os-keyring", pattern="^os-keyring$")
    service: str = Field(min_length=1, max_length=200)
    account: str = Field(min_length=1, max_length=200)


class NativeOAuthReference(_Strict):
    """An opaque pointer to a token managed by Hermes/provider auth storage."""

    backend: str = Field(pattern="^(hermes-auth-store|provider-auth-store)$")
    provider: str = Field(min_length=1, max_length=80)
    account: str = Field(min_length=1, max_length=200)
    profile: str = Field(default="default", min_length=1, max_length=100)


class CredentialStore(Protocol):
    """Minimal secret-store protocol; implementations never serialize secrets."""

    def put(self, reference: CredentialReference, secret: str) -> None: ...

    def get(self, reference: CredentialReference) -> str | None: ...

    def delete(self, reference: CredentialReference) -> None: ...


class MemoryCredentialStore:
    """Ephemeral store useful for tests and a single process session.

    It deliberately has no export or persistence method.
    """

    def __init__(self) -> None:
        self._values: dict[tuple[str, str], str] = {}

    def put(self, reference: CredentialReference, secret: str) -> None:
        if not secret:
            raise ValueError("Credential cannot be empty")
        self._values[(reference.service, reference.account)] = secret

    def get(self, reference: CredentialReference) -> str | None:
        return self._values.get((reference.service, reference.account))

    def delete(self, reference: CredentialReference) -> None:
        self._values.pop((reference.service, reference.account), None)


class KeyringCredentialStore:
    """OS-backed credential store using the standard Python keyring API."""

    def __init__(self, keyring_module: object | None = None) -> None:
        if keyring_module is None:
            try:
                import keyring as keyring_module  # type: ignore[import-not-found]
            except ImportError as exc:  # pragma: no cover - depends on install
                raise RuntimeError(
                    "The keyring package is required for OS credential storage"
                ) from exc
        self._keyring = keyring_module

    def put(self, reference: CredentialReference, secret: str) -> None:
        if not secret:
            raise ValueError("Credential cannot be empty")
        self._keyring.set_password(reference.service, reference.account, secret)

    def get(self, reference: CredentialReference) -> str | None:
        return self._keyring.get_password(reference.service, reference.account)

    def delete(self, reference: CredentialReference) -> None:
        try:
            self._keyring.delete_password(reference.service, reference.account)
        except Exception as exc:  # keyring backends differ in their missing-key error
            if exc.__class__.__name__ not in {"PasswordDeleteError", "KeyringError"}:
                raise


class NativeOAuthStore(Protocol):
    """Provider/Hermes-owned OAuth store boundary.

    ``begin_login`` returns user-facing instructions or a device-code payload,
    while the token itself stays in the protected native store.
    """

    def begin_login(self, provider: str, profile: str = "default") -> dict[str, str]: ...

    def is_connected(self, reference: NativeOAuthReference) -> bool: ...


class UnsupportedNativeOAuthStore:
    """Safe default used until the managed Hermes process is installed."""

    def begin_login(self, provider: str, profile: str = "default") -> dict[str, str]:
        raise RuntimeError("Hermes runtime is not installed; OAuth login is unavailable")

    def is_connected(self, reference: NativeOAuthReference) -> bool:
        return False

