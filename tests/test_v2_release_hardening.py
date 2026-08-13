from __future__ import annotations

import io
import json
import zipfile

from fastapi.testclient import TestClient

from automation.agent.oauth import CodexOAuthManager
from automation.agent.credentials import NativeOAuthReference
from automation.agent.models import AuthMethod, ProviderConnection, ProviderName, TaskCapability, TokenEstimate
from dashboard.api.hermes import provider_registry
from dashboard.api.main import app


client = TestClient(app)


def _complete_intake() -> str:
    state = client.post("/api/intake", json={"language": "en"}).json()
    answers = {
        "goal": "Review synthetic operations",
        "audience": "Local team",
        "reference_sample": "No",
        "outputs": "Web, Excel and PDF",
        "project_location": "/tmp/synthetic-dashboard-project",
        "confirmation": "Yes",
    }
    while state["step"] != "complete":
        state = client.post(
            f"/api/intake/{state['session_id']}/answers",
            json={"step": state["step"], "answer": answers[state["step"]]},
        ).json()
    return state["session_id"]


class _Memory:
    def remember(self, **_: object) -> None:
        return None


def test_hermes_draft_has_one_bounded_repair_attempt(monkeypatch) -> None:
    session_id = _complete_intake()

    class Client:
        calls = 0

        def chat(self, **_: object) -> dict:
            self.calls += 1
            content = "{}" if self.calls == 1 else json.dumps({
                "accent_color": "#1D4ED8",
                "chart_type": "bar",
                "section_order": ["summary", "distribution", "details"],
                "terminology": {},
            })
            return {"choices": [{"message": {"content": content}}]}

    hermes = Client()
    monkeypatch.setattr("dashboard.api.main.managed_hermes.client", hermes)
    monkeypatch.setattr("dashboard.api.main.SafeMemoryStore", lambda: _Memory())
    response = client.post(f"/api/intake/{session_id}/draft", json={
        "accent_color": "#1D4ED8",
        "chart_type": "bar",
        "section_order": ["summary", "distribution", "details"],
        "terminology": {},
        "feedback": "Use the approved blue style",
        "feedback_non_confidential": True,
    })
    assert response.status_code == 201
    assert response.json()["feedback_applied_by_hermes"] is True
    assert hermes.calls == 2


def test_invalid_hermes_draft_is_safe_and_structured(monkeypatch) -> None:
    session_id = _complete_intake()

    class Client:
        calls = 0

        def chat(self, **_: object) -> dict:
            self.calls += 1
            return {"choices": [{"message": {"content": "{}"}}]}

    hermes = Client()
    monkeypatch.setattr("dashboard.api.main.managed_hermes.client", hermes)
    monkeypatch.setattr("dashboard.api.main.SafeMemoryStore", lambda: _Memory())
    response = client.post(f"/api/intake/{session_id}/draft", json={
        "accent_color": "#1D4ED8", "chart_type": "bar",
        "section_order": ["summary", "distribution", "details"],
        "terminology": {}, "feedback": "Keep synthetic labels", "feedback_non_confidential": True,
    })
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_hermes_draft"
    assert hermes.calls == 2
    assert client.get(f"/api/intake/{session_id}/draft").json() is None


def test_validation_errors_do_not_echo_rejected_values() -> None:
    marker = "PRIVATE-PATH-MARKER"
    response = client.post("/api/projects", json={
        "schema_version": 2,
        "name": "Synthetic",
        "language": "en",
        "outputs": ["web"],
        "project_directory": marker,
    })
    assert response.status_code == 422
    body = response.json()
    assert body["detail"]["code"] == "validation_error"
    assert marker not in response.text


def test_support_bundle_is_redacted_and_contains_expected_files(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DASHBOARD_APPLICATION_ROOT", str(tmp_path))
    monkeypatch.setenv("DASHBOARD_LOCAL_AUTH_TOKEN", "SHOULD-NOT-APPEAR-IN-SUPPORT")
    response = client.post("/api/diagnostics/support-bundle")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert b"SHOULD-NOT-APPEAR-IN-SUPPORT" not in response.content
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {"diagnostics.json", "runtime-versions.json", "events.json", "README.txt"}
        diagnostics = json.loads(archive.read("diagnostics.json"))
        assert diagnostics["diagnostic_id"] == response.headers["x-diagnostic-id"]
        assert str(tmp_path).encode() not in response.content


def test_existing_codex_login_recovers_after_application_restart(monkeypatch) -> None:
    manager = CodexOAuthManager()
    monkeypatch.setattr(manager, "_already_connected", lambda: True)
    monkeypatch.setattr(manager, "_select_model", lambda: True)
    status = manager.start("synthetic-project")
    assert status["status"] == "connected"
    assert status["provider"] == "openai-codex"
    assert status["model"] == "gpt-5.5"
    assert status["compatible"] is True


def test_incompatible_codex_model_blocks_authenticated_revision(monkeypatch) -> None:
    session_id = _complete_intake()
    connection = ProviderConnection(
        provider=ProviderName.CODEX,
        account_id="synthetic",
        model="unsupported-model",
        auth_method=AuthMethod.OAUTH,
        credential=NativeOAuthReference(backend="hermes-auth-store", provider="openai-codex", account="synthetic"),
        capabilities={TaskCapability.STRUCTURED_OUTPUT},
        token_estimate=TokenEstimate(input_tokens=0, output_tokens=0),
    )
    provider_registry.connect(connection)
    monkeypatch.setattr("dashboard.api.main.SafeMemoryStore", lambda: _Memory())
    try:
        response = client.post(f"/api/intake/{session_id}/draft", json={
            "accent_color": "#1D4ED8", "chart_type": "bar",
            "section_order": ["summary", "distribution", "details"],
            "terminology": {}, "feedback": "Keep synthetic labels", "feedback_non_confidential": True,
        })
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "provider_model_incompatible"
    finally:
        provider_registry.remove(ProviderName.CODEX)
