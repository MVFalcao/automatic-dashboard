"""Deterministic guided intake with no transcript persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
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


class IntakeStore:
    """Process-local state that intentionally stores answers, not conversation text."""

    def __init__(self) -> None:
        self._sessions: dict[UUID, IntakeSession] = {}
        self._lock = RLock()

    def start(self, language: Language) -> IntakeResponse:
        session = IntakeSession(session_id=uuid4(), language=language)
        with self._lock:
            self._sessions[session.session_id] = session
        return self._response(session)

    def answer(self, session_id: UUID, payload: IntakeAnswerRequest) -> IntakeResponse:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(session_id)
            if payload.step != session.step:
                raise ValueError(f"Expected answer for {session.step.value}")

            session.confirmed_context[payload.step.value] = payload.answer.strip()
            current_index = QUESTION_ORDER.index(session.step)
            if current_index + 1 == len(QUESTION_ORDER):
                session.step = IntakeStep.COMPLETE
            else:
                session.step = QUESTION_ORDER[current_index + 1]
            return self._response(session)

    def discard(self, session_id: UUID) -> None:
        with self._lock:
            if self._sessions.pop(session_id, None) is None:
                raise KeyError(session_id)

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
            confirmed_context=dict(session.confirmed_context),
        )


intake_store = IntakeStore()
