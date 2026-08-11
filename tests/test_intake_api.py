from io import BytesIO

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from dashboard.api.intake import IntakeStep
from dashboard.api.main import app


client = TestClient(app)


def test_intake_asks_one_localized_question_at_a_time() -> None:
    started = client.post("/api/intake", json={"language": "pt"})
    assert started.status_code == 201
    state = started.json()
    assert state["step"] == "goal"
    assert state["question"].startswith("O que")

    answered = client.post(
        f"/api/intake/{state['session_id']}/answers",
        json={"step": "goal", "answer": "Acompanhar operações"},
    )
    assert answered.status_code == 200
    next_state = answered.json()
    assert next_state["step"] == "audience"
    assert next_state["confirmed_context"] == {"goal": "Acompanhar operações"}


def test_intake_rejects_an_answer_for_the_wrong_step() -> None:
    state = client.post("/api/intake", json={"language": "en"}).json()

    response = client.post(
        f"/api/intake/{state['session_id']}/answers",
        json={"step": IntakeStep.OUTPUTS, "answer": "PDF"},
    )

    assert response.status_code == 409
    assert "Expected answer for goal" in response.json()["detail"]


def test_intake_session_can_be_discarded() -> None:
    state = client.post("/api/intake", json={"language": "en"}).json()

    deleted = client.delete(f"/api/intake/{state['session_id']}")
    missing = client.post(
        f"/api/intake/{state['session_id']}/answers",
        json={"step": "goal", "answer": "Anything"},
    )

    assert deleted.status_code == 204
    assert missing.status_code == 404


def test_reference_upload_is_inspected_and_temporary_copy_deleted() -> None:
    pdf = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(pdf)
    response = client.post(
        "/api/references/inspect",
        files={"file": ("../reference.pdf", pdf.getvalue(), "application/pdf")},
        data={"confidential": "true", "permit_data_extraction": "false"},
    )

    assert response.status_code == 200
    inspection = response.json()
    assert inspection["filename"] == "reference.pdf"
    assert inspection["format"] == "pdf"
    assert inspection["confidential"] is True
    assert inspection["temporary_copy_deleted"] is True
    assert inspection["manifest"]["format"] == "pdf"
    assert inspection["draft_schema"]["requires_user_approval"] is True


def test_reference_upload_rejects_unsupported_or_spoofed_files() -> None:
    unsupported = client.post(
        "/api/references/inspect",
        files={"file": ("reference.csv", b"a,b\n1,2", "text/csv")},
        data={"confidential": "false"},
    )
    spoofed = client.post(
        "/api/references/inspect",
        files={"file": ("reference.pdf", b"not a pdf", "application/pdf")},
        data={"confidential": "false"},
    )

    assert unsupported.status_code == 415
    assert spoofed.status_code == 415
