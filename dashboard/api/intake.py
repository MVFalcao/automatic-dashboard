"""Deterministic guided intake with no transcript persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from automation.agent.managed import managed_hermes
from dashboard.api.models import Language, OutputFormat


class IntakeStep(StrEnum):
    GOAL = "goal"
    AUDIENCE = "audience"
    REFERENCE_SAMPLE = "reference_sample"
    OUTPUTS = "outputs"
    PROJECT_LOCATION = "project_location"
    CONFIRMATION = "confirmation"
    COMPLETE = "complete"


QUESTION_ORDER = (
    IntakeStep.GOAL,
    IntakeStep.AUDIENCE,
    IntakeStep.REFERENCE_SAMPLE,
    IntakeStep.OUTPUTS,
    IntakeStep.PROJECT_LOCATION,
    IntakeStep.CONFIRMATION,
)


QUESTIONS = {
    Language.ENGLISH: {
        IntakeStep.GOAL: "What should this dashboard help you understand or decide?",
        IntakeStep.AUDIENCE: "Who will use this dashboard?",
        IntakeStep.REFERENCE_SAMPLE: "Do you have an Excel, PDF, or image reference sample?",
        IntakeStep.OUTPUTS: "Which outputs do you want: web dashboard, Excel, or PDF?",
        IntakeStep.PROJECT_LOCATION: "Where should this dashboard project be saved?",
        IntakeStep.CONFIRMATION: "Is this understanding correct?",
    },
    Language.PORTUGUESE: {
        IntakeStep.GOAL: "O que este dashboard deve ajudar você a entender ou decidir?",
        IntakeStep.AUDIENCE: "Quem usará este dashboard?",
        IntakeStep.REFERENCE_SAMPLE: "Você possui uma amostra de referência em Excel, PDF ou imagem?",
        IntakeStep.OUTPUTS: "Quais saídas você deseja: dashboard web, Excel ou PDF?",
        IntakeStep.PROJECT_LOCATION: "Onde este projeto de dashboard deve ser salvo?",
        IntakeStep.CONFIRMATION: "Este entendimento está correto?",
    },
}


class StartIntakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: Language


class IntakeAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step: IntakeStep
    answer: str = Field(min_length=1, max_length=4_000)
    persist_non_confidential: bool = False


class IntakeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: UUID
    language: Language
    step: IntakeStep
    question: str | None
    confirmed_context: dict[str, str]


class HermesIntakeClarification(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    needs_clarification: bool
    clarifying_question: str | None = None


def _hermes_clarification(
    step: IntakeStep,
    language: Language,
    question: str,
    answer: str,
) -> HermesIntakeClarification | None:
    """Ask Hermes for at most one targeted clarification, failing open."""

    client = managed_hermes.client
    if client is None:
        return None

    request = {
        "task": (
            "Judge whether the user's answer to this one guided dashboard intake question is ambiguous enough "
            "to need one targeted clarification. Return needs_clarification=true only when clarification is "
            "necessary. If true, provide exactly one concise follow-up question for the same intake step; if "
            "false, set clarifying_question to null. Do not start a conversation or ask multiple questions. "
            "Write the follow-up in the language of the original question."
        ),
        "intake_step": step.value,
        "language": language.value,
        "question": question,
        "answer": answer,
    }
    for attempt in range(2):
        try:
            raw = client.chat(
                model="hermes-agent",
                messages=[{
                    "role": "user",
                    "content": json.dumps({**request, "repair_attempt": attempt == 1}, ensure_ascii=False),
                }],
                response_format={"type": "json_object"},
            )
        except Exception:
            return None

        try:
            content = raw["choices"][0]["message"]["content"]
            if isinstance(content, str):
                return HermesIntakeClarification.model_validate_json(content)
            return HermesIntakeClarification.model_validate(content)
        except Exception:
            if attempt == 1:
                return None
    return None


@dataclass
class IntakeSession:
    session_id: UUID
    language: Language
    step: IntakeStep = IntakeStep.GOAL
    confirmed_context: dict[str, str] = field(default_factory=dict)
    persisted_context: dict[str, str] = field(default_factory=dict)
    pending_clarification: str | None = None


class IntakeStore:
    """Restart-safe compact answers, never full conversation transcripts."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(os.environ.get("DASHBOARD_INTAKE_STATE", Path(tempfile.gettempdir()) / "universal-dashboard-agent" / "intake.json"))
        self._sessions: dict[UUID, IntakeSession] = {}
        self._lock = RLock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            for item in payload.get("sessions", []):
                session = IntakeSession(
                    session_id=UUID(item["session_id"]), language=Language(item["language"]),
                    step=IntakeStep(item["step"]), confirmed_context=dict(item.get("confirmed_context", {})),
                    persisted_context=dict(item.get("confirmed_context", {})),
                )
                self._sessions[session.session_id] = session
        except (OSError, ValueError, KeyError, TypeError):
            self._sessions = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, "sessions": [
            {"session_id": str(item.session_id), "language": item.language.value, "step": item.step.value, "confirmed_context": item.persisted_context}
            for item in self._sessions.values()
        ]}
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".intake-", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def start(self, language: Language) -> IntakeResponse:
        session = IntakeSession(session_id=uuid4(), language=language)
        with self._lock:
            self._sessions[session.session_id] = session
            self._save()
        return self._response(session)

    def get(self, session_id: UUID) -> IntakeResponse:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(session_id)
            return self._response(session)

    def set_resource(self, session_id: UUID, key: str, value: str) -> None:
        if not key.startswith("_"):
            raise ValueError("Internal intake resource keys must start with an underscore")
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(session_id)
            session.confirmed_context[key] = value
            session.persisted_context[key] = value
            self._save()

    def get_resource(self, session_id: UUID, key: str) -> str | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(session_id)
            return session.confirmed_context.get(key)

    def answer(self, session_id: UUID, payload: IntakeAnswerRequest) -> IntakeResponse:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(session_id)
            if payload.step != session.step:
                raise ValueError(f"Expected answer for {session.step.value}")

            answer = payload.answer.strip()
            if session.pending_clarification is not None:
                session.confirmed_context[payload.step.value] = (
                    f"{session.confirmed_context.get(payload.step.value, '').strip()} {answer}"
                ).strip()
                session.pending_clarification = None
                if payload.persist_non_confidential:
                    session.persisted_context[payload.step.value] = session.confirmed_context[payload.step.value]
            else:
                session.confirmed_context[payload.step.value] = answer
                if payload.persist_non_confidential:
                    session.persisted_context[payload.step.value] = answer

                if managed_hermes.client is not None:
                    clarification = _hermes_clarification(
                        step=payload.step,
                        language=session.language,
                        question=QUESTIONS[session.language][session.step],
                        answer=answer,
                    )
                    if clarification and clarification.needs_clarification and clarification.clarifying_question:
                        question = clarification.clarifying_question.strip()
                        if question:
                            session.pending_clarification = question
                            self._save()
                            return self._response(session)

            current_index = QUESTION_ORDER.index(session.step)
            if current_index + 1 == len(QUESTION_ORDER):
                session.step = IntakeStep.COMPLETE
            else:
                session.step = QUESTION_ORDER[current_index + 1]
            self._save()
            return self._response(session)

    def discard(self, session_id: UUID) -> None:
        with self._lock:
            if self._sessions.pop(session_id, None) is None:
                raise KeyError(session_id)
            self._save()

    @staticmethod
    def _response(session: IntakeSession) -> IntakeResponse:
        question = None
        if session.step != IntakeStep.COMPLETE:
            question = session.pending_clarification or QUESTIONS[session.language][session.step]
        return IntakeResponse(
            session_id=session.session_id,
            language=session.language,
            step=session.step,
            question=question,
            confirmed_context={key: value for key, value in session.confirmed_context.items() if not key.startswith("_")},
        )


intake_store = IntakeStore()
