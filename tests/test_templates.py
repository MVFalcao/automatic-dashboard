import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from automation.agent.models import AuthMethod, ProviderConnection, ProviderName, TaskCapability, TokenEstimate
from automation.agent.credentials import CredentialReference
from automation.specification.templates import DOMAIN_TEMPLATES, find_sensitive_labels
from dashboard.api.hermes import provider_registry
from dashboard.api.intake_workspace import select_template_for_intake
from dashboard.api.main import app


client = TestClient(app)


def _connect_synthetic_provider() -> None:
    provider_registry.connect(ProviderConnection(
        provider=ProviderName.GEMINI,
        account_id="synthetic",
        model="gemini-default",
        auth_method=AuthMethod.API_KEY,
        credential=CredentialReference(service="test", account="synthetic"),
        capabilities={TaskCapability.CONVERSATION, TaskCapability.STRUCTURED_OUTPUT},
        token_estimate=TokenEstimate(input_tokens=0, output_tokens=0),
    ))


def test_template_registry_and_generic_shape() -> None:
    assert set(DOMAIN_TEMPLATES) == {
        "financial", "health", "attendance", "sales", "hr", "marketing",
        "inventory", "operations", "support", "education", "generic",
    }
    generic = DOMAIN_TEMPLATES["generic"]
    assert [(field.id, field.label, field.kind.value) for field in generic.fields] == [
        ("group", "Group", "text"), ("value", "Value", "number"),
    ]
    assert [(section.id, section.kind.value, section.order) for section in generic.sections] == [
        ("summary", "metrics", 0), ("distribution", "chart", 1), ("details", "table", 2),
    ]
    assert [metric.id for metric in generic.metrics] == ["records", "total"]
    assert generic.visualizations[0].model_dump(mode="json") == {
        "id": "distribution", "kind": "bar", "title": "Distribution", "metric_ids": [],
        "dimension_field": "group", "value_field": "value", "options": {},
    }


def test_templates_have_three_sections_and_approved_contracts() -> None:
    for identifier, template in DOMAIN_TEMPLATES.items():
        assert identifier == template.id
        assert len(template.sections) == 3
        assert [section.kind.value for section in template.sections] == ["metrics", "chart", "table"]
        assert all(metric.approved and metric.explanation for metric in template.metrics)
        assert all(
            visualization.dimension_field is None or visualization.dimension_field in {field.id for field in template.fields}
            for visualization in template.visualizations
        )


def test_find_sensitive_labels_uses_case_insensitive_substrings() -> None:
    assert find_sensitive_labels(["Passport number", "Employee salary band", "Revenue"]) == [
        "Passport number", "Employee salary band",
    ]
    assert find_sensitive_labels(["Revenue", "Department"]) == []


def _session_context() -> SimpleNamespace:
    return SimpleNamespace(confirmed_context={"goal": "Track sales", "audience": "Sales leaders", "outputs": "web"})


def test_selection_falls_back_without_hermes(monkeypatch) -> None:
    monkeypatch.setattr("dashboard.api.main.managed_hermes.client", None)
    template_id, template, reasoning = select_template_for_intake(_session_context())
    assert (template_id, template.id, reasoning) == ("generic", "generic", None)


class _SelectionHermes:
    def __init__(self, selections: list[dict]) -> None:
        self.selections = selections
        self.calls: list[dict] = []

    def chat(self, **kwargs: object) -> dict:
        self.calls.append(kwargs)
        return {"choices": [{"message": {"content": json.dumps(self.selections[min(len(self.calls) - 1, len(self.selections) - 1)])}}]}


def test_selection_picks_template_and_applies_known_override(monkeypatch) -> None:
    hermes = _SelectionHermes([{
        "template_id": "sales",
        "reasoning": "The goal is pipeline visibility.",
        "field_label_overrides": {"deal_name": "Opportunity"},
        "section_title_overrides": {},
        "metric_label_overrides": {},
    }])
    monkeypatch.setattr("dashboard.api.main.managed_hermes.client", hermes)
    _connect_synthetic_provider()
    try:
        template_id, template, reasoning = select_template_for_intake(_session_context())
    finally:
        provider_registry.remove(ProviderName.GEMINI)
    assert template_id == "sales"
    assert template.fields[0].label == "Opportunity"
    assert reasoning == "The goal is pipeline visibility."
    assert len(hermes.calls) == 1


def test_sensitive_override_is_rejected_without_failing_selection(monkeypatch) -> None:
    hermes = _SelectionHermes([{
        "template_id": "sales", "reasoning": "Pipeline is the closest match.",
        "field_label_overrides": {"deal_name": "Salary history"},
        "section_title_overrides": {}, "metric_label_overrides": {},
    }])
    monkeypatch.setattr("dashboard.api.main.managed_hermes.client", hermes)
    _connect_synthetic_provider()
    try:
        template_id, template, reasoning = select_template_for_intake(_session_context())
    finally:
        provider_registry.remove(ProviderName.GEMINI)
    assert template_id == "sales"
    assert template.fields[0].label == "Deal name"
    assert reasoning == "Pipeline is the closest match."
    assert len(hermes.calls) == 2
    repair_prompt = json.loads(hermes.calls[1]["messages"][0]["content"])
    assert repair_prompt["rejected_override_labels"] == [{
        "label": "Salary history",
        "reason": "Sensitive-sounding labels are not permitted in model-proposed display labels.",
    }]


def _complete_intake() -> str:
    state = client.post("/api/intake", json={"language": "en"}).json()
    answers = [
        ("goal", "Track operations"),
        ("audience", "Managers"),
        ("reference_sample", "No"),
        ("outputs", "web"),
        ("project_location", "/tmp/dashboard"),
        ("confirmation", "Yes"),
    ]
    for step, answer in answers:
        response = client.post(f"/api/intake/{state['session_id']}/answers", json={"step": step, "answer": answer})
        assert response.status_code == 200
    return state["session_id"]


def test_retry_template_returns_conflict_after_two_attempts(monkeypatch) -> None:
    monkeypatch.setattr("dashboard.api.main.managed_hermes.client", None)
    session_id = _complete_intake()
    preview = client.get(f"/api/intake/{session_id}/preview")
    assert preview.status_code == 200
    assert preview.json()["template_id"] is None
    first_retry = client.post(f"/api/intake/{session_id}/retry-template")
    assert first_retry.status_code == 200
    second_retry = client.post(f"/api/intake/{session_id}/retry-template")
    assert second_retry.status_code == 409
    assert second_retry.json()["detail"] == "No more template attempts remain"
