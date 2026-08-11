"""Synthetic preview generation endpoint."""

from fastapi import APIRouter

from automation.preview import PreviewPackage, PreviewRequest, generate_preview


router = APIRouter(prefix="/api/previews", tags=["previews"])


@router.post("", response_model=PreviewPackage, status_code=201)
def create_preview(payload: PreviewRequest) -> PreviewPackage:
    return generate_preview(payload)
