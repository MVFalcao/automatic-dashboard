"""Prompt minimization: aggregate facts go to Hermes, source records do not."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from automation.privacy.redaction import redact_payload


def minimize_prompt(
    *,
    context: Mapping[str, Any] | None = None,
    metrics: Mapping[str, Any] | None = None,
    quality: Mapping[str, Any] | None = None,
    records: Iterable[Mapping[str, Any]] | None = None,
    confidential_fields: Iterable[str] = (),
    include_record_sample: bool = False,
    secrets: Iterable[str] = (),
) -> dict[str, Any]:
    """Build the smallest structured prompt payload needed for interpretation.

    Records are excluded by default.  If a small sample is explicitly needed,
    confidential fields are removed before the sample is redacted.
    """

    confidential = set(confidential_fields)
    payload: dict[str, Any] = {
        "context": redact_payload(dict(context or {}), secrets=tuple(secrets)),
        "metrics": redact_payload(dict(metrics or {}), secrets=tuple(secrets)),
        "quality": redact_payload(dict(quality or {}), secrets=tuple(secrets)),
    }
    if include_record_sample and records is not None:
        sample: list[dict[str, Any]] = []
        for record in records:
            sample.append(redact_payload({key: value for key, value in record.items() if key not in confidential}, secrets=tuple(secrets)))
            if len(sample) >= 3:
                break
        payload["record_sample"] = sample
    return payload


def build_minimal_prompt(
    metrics: Mapping[str, Any],
    quality: Mapping[str, Any] | None = None,
    *,
    context: Mapping[str, Any] | None = None,
    confidential_fields: Iterable[str] = (),
    records: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Convenience wrapper used by production pipelines."""

    return minimize_prompt(
        context=context,
        metrics=metrics,
        quality=quality,
        records=records,
        confidential_fields=confidential_fields,
    )
