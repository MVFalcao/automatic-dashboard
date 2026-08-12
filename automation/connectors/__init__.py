"""Provider-neutral JSON API discovery and synchronization."""

from automation.connectors.client import ApiClient, ApiRequestError
from automation.connectors.inference import infer_api_schema
from automation.connectors.models import (
    ApiAuthMethod,
    ApiField,
    ApiFieldMapping,
    ApiInspection,
    ApiSourceConfig,
    ApiSyncRequest,
    ApiSyncResult,
    PaginationKind,
)

__all__ = [
    "ApiAuthMethod",
    "ApiClient",
    "ApiField",
    "ApiFieldMapping",
    "ApiInspection",
    "ApiRequestError",
    "ApiSourceConfig",
    "ApiSyncRequest",
    "ApiSyncResult",
    "PaginationKind",
    "infer_api_schema",
]
