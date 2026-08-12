"""Generic JSON REST source adapter used by the deterministic pipeline."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from automation.connectors.client import ApiClient, ApiRequestError
from automation.connectors.models import ApiInspection, ApiSourceConfig, ApiSyncRequest, ApiSyncResult


@runtime_checkable
class SourceAdapter(Protocol):
    def inspect(self, sample: Any, *, target_fields: dict[str, str] | None = None) -> ApiInspection: ...
    def authenticate(self) -> bool: ...
    def test(self) -> bool: ...
    def fetch(self, request: ApiSyncRequest) -> ApiSyncResult: ...
    def normalize(self, result: ApiSyncResult) -> list[dict[str, Any]]: ...
    def checkpoint(self, result: ApiSyncResult) -> Any: ...


class JsonApiSourceAdapter:
    """Adapter boundary keeps reporting code independent of HTTP details."""

    def __init__(self, source: ApiSourceConfig, client: ApiClient) -> None:
        self.source = source
        self.client = client

    def inspect(self, sample: Any, *, target_fields: dict[str, str] | None = None) -> ApiInspection:
        return self.client.inspect(self.source, sample, target_fields=target_fields)

    def authenticate(self) -> bool:
        # Credential lookup intentionally returns only connection state.
        try:
            self.client._auth_headers(self.source)  # noqa: SLF001 - adapter boundary
        except ApiRequestError:
            return False
        return True

    def test(self) -> bool:
        try:
            self.client.sync(ApiSyncRequest(source=self.source))
        except ApiRequestError:
            return False
        return True

    def fetch(self, request: ApiSyncRequest) -> ApiSyncResult:
        if request.source.id != self.source.id:
            raise ValueError("The request source does not match this adapter")
        return self.client.sync(request)

    def normalize(self, result: ApiSyncResult) -> list[dict[str, Any]]:
        return [dict(record) for record in result.records]

    def checkpoint(self, result: ApiSyncResult) -> Any:
        return result.next_checkpoint

