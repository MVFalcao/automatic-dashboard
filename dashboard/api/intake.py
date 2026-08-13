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


@dataclass
class IntakeSession:
    session_id: UUID
    language: Language
    step: IntakeStep = IntakeStep.GOAL
    confirmed_context: dict[str, str] = field(default_factory=dict)
    persisted_context: dict[str, str] = field(default_factory=dict)


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

            session.confirmed_context[payload.step.value] = payload.answer.strip()
            if payload.persist_non_confidential:
                session.persisted_context[payload.step.value] = payload.answer.strip()
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
            question = QUESTIONS[session.language][session.step]
        return IntakeResponse(
            session_id=session.session_id,
            language=session.language,
            step=session.step,
            question=question,
            confirmed_context={key: value for key, value in session.confirmed_context.items() if not key.startswith("_")},
        )


intake_store = IntakeStore()
