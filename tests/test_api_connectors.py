from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from automation.agent.credentials import CredentialReference, MemoryCredentialStore
from automation.connectors.client import ApiClient, ApiRequestError, _safe_url
from automation.connectors.models import (
    ApiAuthMethod,
    ApiSourceConfig,
    ApiSyncRequest,
    PaginationConfig,
    PaginationKind,
)
from dashboard.api.main import app


def source(**kwargs) -> ApiSourceConfig:
    values = {
        "id": "test-api",
        "name": "Test API",
        "endpoint": "https://api.example.test/v1/records",
    }
    values.update(kwargs)
    return ApiSourceConfig(**values)


def client_for(handler):
    store = MemoryCredentialStore()
    return ApiClient(store, transport=httpx.MockTransport(handler)), store


def approved_request(api_source: ApiSourceConfig, **kwargs) -> ApiSyncRequest:
    values = {
        "source": api_source,
        "approved_mappings": {"id": "id", "amount": "amount"},
        "approval_confirmed": True,
        "inspection_version": "inspection-v1",
    }
    values.update(kwargs)
    return ApiSyncRequest(**values)


def test_inspection_infers_nested_fields_and_plain_language_mappings() -> None:
    client = ApiClient()
    inspection = client.inspect(
        source(),
        {"data": [{"id": 1, "updated_at": "2026-01-01T00:00:00Z", "owner": {"name": "A"}}]},
        target_fields={"id": "Identifier", "owner.name": "Owner"},
    )
    assert inspection.records_path == "data"
    assert {field.path for field in inspection.fields} == {"id", "owner.name", "updated_at"}
    assert next(item for item in inspection.mappings if item.source_path == "id").confidence == "high"
    assert "review" in next(item for item in inspection.mappings if item.source_path == "updated_at").explanation.casefold()
    assert inspection.requires_approval is True


def test_openapi_inspection_extracts_json_response_contract() -> None:
    client = ApiClient()
    inspection = client.inspect(source(), openapi_document={
        "openapi": "3.0.0",
        "paths": {"/records": {"get": {"responses": {"200": {"content": {
            "application/json": {"schema": {"type": "array", "items": {
                "type": "object", "properties": {"id": {"type": "integer"}, "title": {"type": "string"}}
            }}}
        }}}}}},
    })
    assert inspection.record_shape == "openapi-schema"
    assert [(field.path, field.type) for field in inspection.fields] == [("id", "integer"), ("title", "string")]


def test_api_source_never_accepts_raw_secret_and_serialization_is_reference_only() -> None:
    configured = source(
        auth_method=ApiAuthMethod.API_KEY,
        credential_reference=CredentialReference(service="dashboard", account="test"),
    )
    serialized = configured.model_dump_json()
    assert "secret" not in serialized.casefold()
    with pytest.raises(ValueError):
        source(auth_method=ApiAuthMethod.API_KEY)


def test_page_pagination_and_deterministic_flattening() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page")
        body = [{"id": 1, "amount": 10}] if page == "1" else ([{"id": 2, "amount": 20}] if page == "2" else [])
        return httpx.Response(200, json=body, headers={"content-type": "application/json"})

    client, _ = client_for(handler)
    result = client.sync(approved_request(source(pagination=PaginationConfig(kind=PaginationKind.PAGE, page_size=1))))
    assert result.records == [{"amount": 10, "id": 1}, {"amount": 20, "id": 2}]
    assert result.pages_fetched == 3
    assert len(result.provenance) == 2


def test_cursor_and_link_pagination() -> None:
    def cursor_handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cursor"):
            return httpx.Response(200, json={"items": [{"id": 2}], "next_cursor": None}, headers={"content-type": "application/json"})
        return httpx.Response(200, json={"items": [{"id": 1}], "next_cursor": "abc"}, headers={"content-type": "application/json"})

    client, _ = client_for(cursor_handler)
    result = client.sync(approved_request(source(pagination=PaginationConfig(kind=PaginationKind.CURSOR))))
    assert [record["id"] for record in result.records] == [1, 2]


def test_cross_origin_pagination_link_is_rejected_before_request() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"items": [{"id": 1}], "links": {"next": "https://attacker.example/steal"}}, headers={"content-type": "application/json"})

    client, _ = client_for(handler)
    with pytest.raises(ApiRequestError, match="origin"):
        client.sync(approved_request(source(pagination=PaginationConfig(kind=PaginationKind.LINK, next_link_path="links.next"))))
    assert calls == ["https://api.example.test/v1/records"]

    def link_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/next"):
            body = {"items": [{"id": 2}], "links": {"next": None}}
        else:
            body = {"items": [{"id": 1}], "links": {"next": "/next"}}
        return httpx.Response(200, json=body, headers={"content-type": "application/json"})

    link_client, _ = client_for(link_handler)
    result = link_client.sync(approved_request(source(
        pagination=PaginationConfig(kind=PaginationKind.LINK, next_link_path="links.next")
    )))
    assert [record["id"] for record in result.records] == [1, 2]


def test_url_credentials_fragments_private_dns_and_rebinding_are_rejected() -> None:
    configured = source()
    with pytest.raises(ApiRequestError, match="credentials"):
        _safe_url(configured, "https://user:pass@api.example.test/v1/records")
    with pytest.raises(ApiRequestError, match="fragments"):
        _safe_url(configured, "https://api.example.test/v1/records#hidden")
    with pytest.raises(ApiRequestError, match="non-public"):
        _safe_url(configured, str(configured.endpoint), resolver=lambda host, port: ["127.0.0.1"])
    calls = 0
    def rebinding(host: str, port: int) -> list[str]:
        nonlocal calls
        calls += 1
        return ["8.8.8.8"] if calls == 1 else ["10.0.0.1"]
    assert _safe_url(configured, str(configured.endpoint), resolver=rebinding) == "8.8.8.8"
    with pytest.raises(ApiRequestError, match="non-public"):
        _safe_url(configured, str(configured.endpoint), resolver=rebinding)


def test_bounded_retry_rate_limit_and_auth_header() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        assert request.headers["x-api-key"] == "private-key"
        if attempts == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, json=[{"id": 1}], headers={"content-type": "application/json"})

    client, store = client_for(handler)
    reference = CredentialReference(service="dashboard", account="test")
    store.put(reference, "private-key")
    result = client.sync(approved_request(source(
        auth_method=ApiAuthMethod.API_KEY,
        credential_reference=reference,
        max_retries=1,
        backoff_seconds=0,
    )))
    assert result.record_count == 1
    assert attempts == 2


def test_incremental_requires_confirmation_and_produces_checkpoint() -> None:
    with pytest.raises(ValueError, match="Incremental"):
        ApiSyncRequest(source=source(), mode="incremental", approval_confirmed=True, approved_mappings={"id": "id"}, inspection_version="inspection-v1")
    configured = source(incremental_field="updated_at", incremental_confirmed=True)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["updated_since"] == "2026-01-01T00:00:00+00:00"
        return httpx.Response(200, json=[{"id": 1, "updated_at": "2026-01-02T00:00:00Z"}], headers={"content-type": "application/json"})

    client, _ = client_for(handler)
    result = client.sync(approved_request(
        configured,
        mode="incremental",
        checkpoint=datetime(2026, 1, 1, tzinfo=timezone.utc),
    ))
    assert result.next_checkpoint == "2026-01-02T00:00:00Z"


def test_schema_drift_classifies_added_and_blocks_removed_fields() -> None:
    client = ApiClient(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, json=[{"id": 1, "new": "x"}], headers={"content-type": "application/json"}
    )))
    expected = client.inspect(source(), [{"id": 1, "old": "x"}])
    with pytest.raises(ApiRequestError, match="blocking"):
        client.sync(approved_request(source()), expected_inspection=expected)


def test_local_api_inspection_endpoint_and_sync_requires_approval() -> None:
    api = TestClient(app)
    inspected = api.post("/api/api-sources/inspect", json={
        "source": source().model_dump(mode="json"),
        "representative_json": {"items": [{"id": 1}]},
    })
    assert inspected.status_code == 200
    assert inspected.json()["records_path"] == "items"
    rejected = api.post("/api/api-sources/sync", json={
        "request": {"source": source().model_dump(mode="json"), "approved_mappings": {"id": "id"}},
    })
    assert rejected.status_code == 422


def test_api_sync_requires_inspection_version_and_nonempty_approved_mappings() -> None:
    with pytest.raises(ValueError, match="persisted inspection"):
        ApiSyncRequest(source=source(), approval_confirmed=True)
