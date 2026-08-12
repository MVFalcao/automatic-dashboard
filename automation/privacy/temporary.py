"""Small, testable lifecycle primitives for confidential temporary files."""

from __future__ import annotations

from pathlib import Path
from typing import Self


def delete_temporary_file(path: Path | str) -> bool:
    """Delete one temporary file and report whether it no longer exists."""

    candidate = Path(path)
    try:
        candidate.unlink(missing_ok=True)
    except OSError:
        return False
    return not candidate.exists()


class TemporaryFileGuard:
    """Ensure a confidential temporary source is removed on every exit path."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.deleted = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.deleted = delete_temporary_file(self.path)
