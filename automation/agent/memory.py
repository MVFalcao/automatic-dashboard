"""Compact, non-confidential Hermes learning memory."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MemoryKind(StrEnum):
    GLOBAL_PREFERENCE = "global_preference"
    PROJECT_TERMINOLOGY = "project_terminology"
    PROJECT_LAYOUT = "project_layout"
    FEEDBACK = "feedback"


class MemoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: MemoryKind
    project_id: str | None = Field(default=None, max_length=160)
    key: str = Field(min_length=1, max_length=120)
    value: str | int | float | bool | list[str] = Field()
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("value")
    @classmethod
    def no_empty_value(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            raise ValueError("Memory values cannot be empty")
        if isinstance(value, list) and len(value) > 20:
            raise ValueError("Memory lists are limited to 20 items")
        return value


_SENSITIVE_KEY = re.compile(
    r"(?:secret|token|password|credential|api[_-]?key|authorization|cookie|record|rows?|source|transcript|message|prompt|response|email|phone|address|ssn|cpf|cnpj|document)",
    re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(
    r"(?:[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:\+?\d[\d ()-]{7,}\d)|sk-[A-Za-z0-9_-]{12,})"
)


def _safe_value(value: Any, *, key: str) -> str | int | float | bool | list[str]:
    if _SENSITIVE_KEY.search(key):
        raise ValueError(f"Memory key is not allowed: {key}")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        if len(value) > 500:
            raise ValueError("Memory value is too large")
        if _SENSITIVE_VALUE.search(value):
            raise ValueError("Memory value appears to contain confidential data")
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        if len(value) > 20 or any(len(item) > 120 for item in value):
            raise ValueError("Memory list is too large")
        if any(_SENSITIVE_VALUE.search(item) for item in value):
            raise ValueError("Memory value appears to contain confidential data")
        return list(value)
    raise ValueError("Memory values must be compact scalar values or short string lists")


class SafeMemoryStore:
    """Store only approved preference/terminology/layout/feedback entries."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._entries: list[MemoryEntry] = []
        if path is not None and path.exists():
            self._load()

    @property
    def entries(self) -> tuple[MemoryEntry, ...]:
        return tuple(self._entries)

    def remember(
        self,
        *,
        kind: MemoryKind,
        key: str,
        value: Any,
        project_id: str | None = None,
    ) -> MemoryEntry:
        safe = _safe_value(value, key=key)
        entry = MemoryEntry(kind=kind, key=key, value=safe, project_id=project_id)
        self._entries = [existing for existing in self._entries if not (
            existing.kind == kind and existing.project_id == project_id and existing.key == key
        )]
        self._entries.append(entry)
        self._persist()
        return entry

    def project_context(self, project_id: str | None = None) -> list[dict[str, Any]]:
        return [
            entry.model_dump(mode="json")
            for entry in self._entries
            if entry.project_id is None or entry.project_id == project_id
        ]

    def _persist(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps([entry.model_dump(mode="json") for entry in self._entries], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError("Memory file must contain a list")
            loaded = []
            for item in raw:
                if not isinstance(item, dict):
                    raise ValueError("Memory entry must be an object")
                # Re-run the same redaction rules on every load, including files
                # edited externally.
                loaded.append(
                    MemoryEntry(
                        kind=item["kind"],
                        project_id=item.get("project_id"),
                        key=item["key"],
                        value=_safe_value(item["value"], key=item["key"]),
                        recorded_at=item.get("recorded_at"),
                    )
                )
            self._entries = loaded
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError("Memory file failed confidential-data validation") from exc

