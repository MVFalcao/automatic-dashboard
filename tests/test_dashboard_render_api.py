from fastapi.testclient import TestClient

from dashboard.api.main import app
from test_dashboard_spec import valid_spec


client = TestClient(app)


def test_canonical_spec_renders_deterministic_synthetic_dashboard() -> None:
    payload = {"specification": valid_spec().model_dump(mode="json"), "record_count": 8}

    first = client.post("/api/dashboard-specs/render", json=payload)
    second = client.post("/api/dashboard-specs/render", json=payload)

    assert first.status_code == 200
    assert first.json() == second.json()
    assert first.json()["synthetic"] is True
    assert first.json()["metrics"]["total"] is not None
    assert len(first.json()["records"]) == 8


def test_confidential_display_requires_explicit_temporary_authorization() -> None:
    payload = valid_spec().model_dump(mode="json")
    payload["fields"][0]["confidential"] = True
    payload["privacy"]["confidential_fields"] = ["category"]
    payload["privacy"]["allow_persistence"] = False

    denied = client.post("/api/dashboard-specs/render", json={"specification": payload})
    allowed = client.post(
        "/api/dashboard-specs/render",
        json={"specification": payload, "authorize_confidential_display": True},
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["temporary_in_memory"] is True
