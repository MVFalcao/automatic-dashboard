"""Temporary, metadata-only inspection of dashboard reference uploads."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from fastapi import UploadFile
from pydantic import BaseModel, ConfigDict

from automation.discovery import (
    DraftDashboardSchema,
    SampleManifest,
    analyze_excel,
    analyze_image,
    analyze_pdf,
    propose_dashboard_schema,
)


SUPPORTED_SUFFIXES = {".xlsx", ".pdf", ".png", ".jpg", ".jpeg", ".svg"}
SIGNATURES = {
    ".xlsx": (b"PK\x03\x04",),
    ".pdf": (b"%PDF",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
}


class UploadInspection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    format: str
    size_bytes: int
    sha256: str
    confidential: bool
    extracted_data_permitted: bool
    temporary_copy_deleted: bool
    manifest: SampleManifest
    draft_schema: DraftDashboardSchema


def _validate_signature(suffix: str, header: bytes) -> None:
    expected = SIGNATURES.get(suffix)
    if expected and not any(header.startswith(signature) for signature in expected):
        raise ValueError("File content does not match its extension")
    if suffix == ".svg" and b"<svg" not in header.lower():
        raise ValueError("File content does not match its extension")


async def inspect_upload(
    upload: UploadFile,
    *,
    confidential: bool,
    extracted_data_permitted: bool,
) -> UploadInspection:
    """Inspect an upload and guarantee deletion of its temporary copy."""
    filename = Path(upload.filename or "").name
    suffix = Path(filename).suffix.casefold()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError("Supported reference formats: XLSX, PDF, PNG, JPEG, and SVG")
    descriptor, temporary_name = tempfile.mkstemp(prefix="dashboard-reference-", suffix=suffix)
    temporary_path = Path(temporary_name)
    digest = hashlib.sha256()
    size = 0
    header = b""
    manifest: SampleManifest | None = None
    try:
        with os.fdopen(descriptor, "wb") as destination:
            while chunk := await upload.read(1024 * 1024):
                if len(header) < 4096:
                    header += chunk[: 4096 - len(header)]
                destination.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        _validate_signature(suffix, header)
        try:
            if suffix == ".xlsx":
                manifest = analyze_excel(
                    temporary_path,
                    permit_data_extraction=extracted_data_permitted,
                )
            elif suffix == ".pdf":
                manifest = analyze_pdf(
                    temporary_path,
                    permit_data_extraction=extracted_data_permitted,
                )
            else:
                manifest = analyze_image(
                    temporary_path,
                    permit_data_extraction=extracted_data_permitted,
                )
        except Exception as exc:
            raise ValueError("The reference file could not be analyzed safely") from exc
    finally:
        await upload.close()
        temporary_path.unlink(missing_ok=True)

    if manifest is None:  # pragma: no cover - guarded by the supported suffix check
        raise ValueError("The reference file could not be analyzed safely")
    return UploadInspection(
        filename=filename,
        format=suffix.removeprefix("."),
        size_bytes=size,
        sha256=digest.hexdigest(),
        confidential=confidential,
        extracted_data_permitted=extracted_data_permitted,
        temporary_copy_deleted=not temporary_path.exists(),
        manifest=manifest,
        draft_schema=propose_dashboard_schema(manifest),
    )
