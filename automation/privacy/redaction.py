"""Deterministic redaction for operational output.

The redactor is deliberately conservative: known credentials are replaced
first, then common credential and personal-data shapes are masked.  It is
used at the boundary of logs and prompts, never as a substitute for the
application's explicit confidentiality approval.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


_PATTERNS = (
    # Authorization headers and common API key formats.
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)((?:api[_-]?key|token|secret|password|authorization)\s*[:=]\s*)[^,;\s]+"), r"\1[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "[REDACTED]"),
    # Email, phone, CPF/CNPJ-like identifiers, and long opaque tokens.
    (re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
    (re.compile(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)"), "[REDACTED_PHONE]"),
    (re.compile(r"(?<!\w)\d{3}[.]?\d{3}[.]?\d{3}[- ]?\d{2}(?!\w)"), "[REDACTED_ID]"),
    (re.compile(r"(?<!\w)\d{2}[.]?\d{3}[.]?\d{3}/?\d{4}[- ]?\d{2}(?!\w)"), "[REDACTED_ID]"),
)
_SENSITIVE_KEY = re.compile(r"(?i)(?:secret|token|password|credential|api[_-]?key|authorization|cookie|private[_-]?key)")


def redact_text(value: str, *, secrets: Sequence[str] = ()) -> str:
    """Return ``value`` with supplied secrets and known sensitive patterns masked."""

    result = value
    # Longest first avoids leaking a suffix when secrets overlap.
    for secret in sorted({item for item in secrets if isinstance(item, str) and item}, key=len, reverse=True):
        result = result.replace(secret, "[REDACTED]")
    for pattern, replacement in _PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def redact_payload(value: Any, *, secrets: Sequence[str] = ()) -> Any:
    """Recursively redact strings in a JSON-compatible payload.

    Mapping keys are retained because field names are useful for diagnostics;
    values are sanitized before they can reach SQLite or a log sink.
    """

    if isinstance(value, str):
        return redact_text(value, secrets=secrets)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            # Key-aware masking handles opaque credentials that do not match a
            # recognizable token prefix (for example ``api_key: abc123``).
            result[str(key)] = "[REDACTED]" if _SENSITIVE_KEY.search(str(key)) else redact_payload(item, secrets=secrets)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [redact_payload(item, secrets=secrets) for item in value]
    return value
