"""Bounded, authenticated HTTP client for JSON-only API sources."""

from __future__ import annotations

import json
import ipaddress
import socket
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Callable, Protocol
from urllib.parse import urljoin, urlsplit

import httpx

from automation.agent.credentials import CredentialReference, CredentialStore, NativeOAuthReference, NativeOAuthStore
from automation.connectors.inference import extract_records, flatten_record, infer_api_schema, infer_openapi_schema
from automation.connectors.models import (
    ApiAuthMethod,
    ApiInspection,
    ApiSourceConfig,
    ApiSyncRequest,
    ApiSyncResult,
    DriftClass,
    ExtractionProvenance,
    SchemaDriftEvent,
)


class OAuthTokenProvider(Protocol):
    def get_access_token(self, reference: NativeOAuthReference) -> str | None: ...


class ApiRequestError(RuntimeError):
    """An API error whose text never contains response bodies or credentials."""

    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


def _get_path(value: Any, path: str | None) -> Any:
    for part in path.split(".") if path else []:
        if isinstance(value, Mapping):
            value = value.get(part)
        else:
            return None
    return value


def _checkpoint_value(record: Mapping[str, Any], field: str | None) -> Any:
    if not field:
        return None
    return _get_path(record, field)


def _newest(values: list[Any]) -> Any:
    present = [value for value in values if value not in (None, "")]
    if not present:
        return None
    try:
        return max(present)
    except TypeError:
        return max(str(value) for value in present)


def _drift(expected: ApiInspection, actual: ApiInspection) -> list[SchemaDriftEvent]:
    from automation.drift.classifier import classify_schema_drift

    return classify_schema_drift(expected, actual)


Resolver = Callable[[str, int], list[str]]


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ApiRequestError("API URL must use HTTP or HTTPS")
    return parsed.scheme, parsed.hostname.casefold(), parsed.port or (443 if parsed.scheme == "https" else 80)


def _system_resolver(host: str, port: int) -> list[str]:
    try:
        return sorted({item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
    except socket.gaierror as exc:
        raise ApiRequestError("API endpoint DNS resolution failed", retryable=True) from exc


def _safe_url(source: ApiSourceConfig, url: str, *, resolver: Resolver | None = None) -> str | None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ApiRequestError("API URL must use HTTP or HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ApiRequestError("API URLs may not contain user credentials")
    if parsed.fragment:
        raise ApiRequestError("API URLs may not contain fragments")
    host = parsed.hostname.casefold()
    blocked_names = {"localhost", "localhost.localdomain", "metadata.google.internal"}
    if host in blocked_names or host.endswith(".localhost") or host.endswith(".local") or host.endswith(".internal"):
        raise ApiRequestError("API endpoint resolves to a local or internal host")
    if _origin(url) != _origin(str(source.endpoint)):
        raise ApiRequestError("Redirects and pagination links may not change API origin")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    addresses = [str(address)] if address is not None else (resolver(host, _origin(url)[2]) if resolver else [])
    for candidate in addresses:
        resolved = ipaddress.ip_address(candidate)
        if not resolved.is_global:
            raise ApiRequestError("API endpoint resolves to a non-public address")
    if resolver is not None and not addresses:
        raise ApiRequestError("API endpoint DNS resolution returned no addresses")
    return addresses[0] if addresses else None


class ApiClient:
    """Fetch JSON responses with authentication, pagination and bounded retries."""

    def __init__(
        self,
        credential_store: CredentialStore | None = None,
        oauth_store: OAuthTokenProvider | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        resolver: Resolver | None = None,
    ) -> None:
        self.credential_store = credential_store
        self.oauth_store = oauth_store
        self.transport = transport
        # Mock transports deliberately keep their logical URL.  Production
        # requests always resolve and pin a validated public address.
        self.resolver = resolver or (None if transport is not None else _system_resolver)
        self._last_request_at: float | None = None

    def _auth_headers(self, source: ApiSourceConfig) -> dict[str, str]:
        if source.auth_method is ApiAuthMethod.NONE:
            return {}
        reference = source.credential_reference
        secret: str | None = None
        if source.auth_method in {ApiAuthMethod.API_KEY, ApiAuthMethod.BEARER}:
            if self.credential_store is None or not isinstance(reference, CredentialReference):
                raise ApiRequestError("The API credential store is unavailable")
            secret = self.credential_store.get(reference)
        elif source.auth_method is ApiAuthMethod.OAUTH:
            if self.oauth_store is None or not isinstance(reference, NativeOAuthReference):
                raise ApiRequestError("The OAuth provider store is unavailable")
            secret = self.oauth_store.get_access_token(reference)
        if not secret:
            raise ApiRequestError("The API credential is not connected")
        if source.auth_method is ApiAuthMethod.API_KEY:
            return {source.api_key_header: secret}
        return {"Authorization": f"Bearer {secret}"}

    def _wait_rate_limit(self, source: ApiSourceConfig) -> None:
        if source.requests_per_second is None:
            return
        minimum_interval = 1.0 / source.requests_per_second
        if self._last_request_at is not None:
            delay = minimum_interval - (time.monotonic() - self._last_request_at)
            if delay > 0:
                time.sleep(delay)
        self._last_request_at = time.monotonic()

    def _request(self, source: ApiSourceConfig, url: str, params: dict[str, Any]) -> Any:
        redirects = 0
        headers = self._auth_headers(source)
        for attempt in range(source.max_retries + 1):
            self._wait_rate_limit(source)
            try:
                with httpx.Client(timeout=source.timeout_seconds, transport=self.transport, follow_redirects=False) as client:
                    current_url = str(httpx.URL(url, params=params))
                    while True:
                        address = _safe_url(source, current_url, resolver=self.resolver)
                        logical = httpx.URL(current_url)
                        request_headers = dict(headers)
                        request_url = logical
                        if address is not None and self.transport is None:
                            port = logical.port or (443 if logical.scheme == "https" else 80)
                            default_port = (logical.scheme == "https" and port == 443) or (logical.scheme == "http" and port == 80)
                            request_headers["Host"] = logical.host if default_port else f"{logical.host}:{port}"
                            request_url = logical.copy_with(host=address)
                        request = client.build_request("GET", request_url, headers=request_headers)
                        if address is not None and logical.scheme == "https":
                            request.extensions["sni_hostname"] = logical.host.encode("idna")
                        response = client.send(request)
                        if response.status_code not in {301, 302, 303, 307, 308}:
                            break
                        location = response.headers.get("location")
                        if not location:
                            raise ApiRequestError("API redirect did not include a destination")
                        redirects += 1
                        if redirects > 5:
                            raise ApiRequestError("API redirect limit exceeded")
                        current_url = urljoin(current_url, location)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt >= source.max_retries:
                    raise ApiRequestError("The API request failed after bounded retries", retryable=True) from exc
                time.sleep(min(source.backoff_seconds * (2**attempt), 30))
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= source.max_retries:
                    raise ApiRequestError(
                        f"The API returned retryable HTTP status {response.status_code}",
                        status_code=response.status_code,
                        retryable=True,
                    )
                retry_after = response.headers.get("retry-after")
                try:
                    delay = min(float(retry_after or 0), 30)
                except ValueError:
                    delay = 0
                time.sleep(max(delay, min(source.backoff_seconds * (2**attempt), 30)))
                continue
            if response.status_code >= 400:
                raise ApiRequestError(
                    f"The API returned HTTP status {response.status_code}", status_code=response.status_code
                )
            content_type = response.headers.get("content-type", "").casefold()
            try:
                payload = response.json()
            except (ValueError, json.JSONDecodeError) as exc:
                raise ApiRequestError("The API response was not valid JSON") from exc
            if "xml" in content_type or isinstance(payload, (str, bytes)):
                raise ApiRequestError("Only JSON API responses are supported")
            return payload
        raise AssertionError("bounded retry loop did not return")

    def inspect(
        self,
        source: ApiSourceConfig,
        sample: Any = None,
        *,
        target_fields: dict[str, str] | None = None,
        openapi_document: dict[str, Any] | None = None,
    ) -> ApiInspection:
        if openapi_document is not None:
            return infer_openapi_schema(openapi_document, source_id=source.id, target_fields=target_fields)
        if sample is None:
            raise ValueError("Provide representative JSON or an OpenAPI/Swagger document")
        return infer_api_schema(sample, source_id=source.id, records_path=source.records_path, target_fields=target_fields)

    def sync(
        self,
        request: ApiSyncRequest,
        *,
        expected_inspection: ApiInspection | None = None,
    ) -> ApiSyncResult:
        source = request.source
        if request.mode == "incremental" and not source.incremental_confirmed:
            raise ApiRequestError("Incremental refresh requires an approved updated-time field")
        records: list[dict[str, Any]] = []
        observed_records: list[dict[str, Any]] = []
        checkpoint_values: list[Any] = []
        provenance: list[ExtractionProvenance] = []
        url = str(source.endpoint)
        _safe_url(source, url, resolver=self.resolver)
        params: dict[str, Any] = {}
        if request.mode == "incremental":
            params["updated_since"] = request.checkpoint.isoformat() if isinstance(request.checkpoint, datetime) else request.checkpoint
        pages = 0
        cursor: str | None = None
        while pages < source.pagination.max_pages:
            pages += 1
            if source.pagination.kind.value == "page":
                params[source.pagination.page_param] = source.pagination.start_page + pages - 1
                params[source.pagination.page_size_param] = source.pagination.page_size
            elif source.pagination.kind.value == "cursor" and cursor:
                params[source.pagination.cursor_param] = cursor
            fetched_at = datetime.now(timezone.utc)
            payload = self._request(source, url, params)
            batch, _, _ = extract_records(payload, source.records_path)
            for index, record in enumerate(batch):
                checkpoint_values.append(_checkpoint_value(record, source.incremental_field))
                flattened = flatten_record(record)
                observed_records.append(flattened)
                if request.approved_mappings:
                    normalized = {
                        target: flattened.get(path)
                        for path, target in request.approved_mappings.items()
                    }
                else:
                    normalized = flattened
                records.append(normalized)
                provenance.append(ExtractionProvenance(
                    endpoint=url,
                    fetched_at=fetched_at,
                    page=pages,
                    record_index=index,
                    cursor=cursor,
                ))
            pagination = source.pagination
            if pagination.kind.value == "none":
                break
            if pagination.kind.value == "page":
                if len(batch) < pagination.page_size:
                    break
            elif pagination.kind.value == "cursor":
                next_cursor = _get_path(payload, pagination.next_cursor_path)
                if not next_cursor or str(next_cursor) == cursor:
                    break
                cursor = str(next_cursor)
            else:
                next_link = _get_path(payload, pagination.next_link_path)
                if not next_link:
                    break
                url = urljoin(url, str(next_link))
                params = {}
        complete = pages < source.pagination.max_pages
        warnings = [] if complete else ["Pagination stopped at the configured maximum page limit"]
        drift: list[SchemaDriftEvent] = []
        if expected_inspection is not None:
            actual = infer_api_schema(observed_records, source_id=source.id)
            drift = _drift(expected_inspection, actual)
            if any(item.classification is DriftClass.BLOCKING for item in drift):
                raise ApiRequestError("The API response has blocking schema drift; review is required")
        checkpoint = _newest(checkpoint_values)
        return ApiSyncResult(
            source_id=source.id,
            mode=request.mode,
            records=records,
            provenance=provenance,
            record_count=len(records),
            pages_fetched=pages,
            next_checkpoint=checkpoint,
            schema_drift=drift,
            complete=complete,
            warnings=warnings,
        )
