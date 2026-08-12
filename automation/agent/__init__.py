"""Hermes runtime integration contracts.

The dashboard application talks to Hermes through these small, provider-neutral
interfaces.  The integration intentionally keeps credentials and source data
outside project specifications and model memory.
"""

from automation.agent.credentials import (
    CredentialReference,
    CredentialStore,
    KeyringCredentialStore,
    MemoryCredentialStore,
    NativeOAuthReference,
    NativeOAuthStore,
)
from automation.agent.gateway import GatewayConfig, HermesGateway
from automation.agent.memory import MemoryEntry, MemoryKind, SafeMemoryStore
from automation.agent.models import (
    ProviderConnection,
    ProviderName,
    ProviderSetupInstructions,
    TaskRequest,
    TaskResponse,
    TokenEstimate,
)
from automation.agent.routing import ProviderRouter, ProviderSelection
from automation.agent.providers import ProviderRegistry
from automation.agent.runtime import HermesRuntime, HermesRuntimeSpec
from automation.agent.validation import StructuredResponseValidator

__all__ = [
    "CredentialReference",
    "CredentialStore",
    "GatewayConfig",
    "HermesGateway",
    "HermesRuntime",
    "HermesRuntimeSpec",
    "KeyringCredentialStore",
    "MemoryCredentialStore",
    "MemoryEntry",
    "MemoryKind",
    "NativeOAuthReference",
    "NativeOAuthStore",
    "ProviderConnection",
    "ProviderName",
    "ProviderRouter",
    "ProviderSelection",
    "ProviderRegistry",
    "ProviderSetupInstructions",
    "SafeMemoryStore",
    "StructuredResponseValidator",
    "TaskRequest",
    "TaskResponse",
    "TokenEstimate",
]
