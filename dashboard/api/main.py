"""Local-only API for guided dashboard project setup."""

from fastapi import FastAPI

from dashboard.api.models import SetupCapabilities


app = FastAPI(
    title="Universal Dashboard Agent",
    version="0.1.0",
    description="Local API for creating and managing dashboard projects.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/setup/capabilities", response_model=SetupCapabilities)
def setup_capabilities() -> SetupCapabilities:
    """Return only product capabilities confirmed in context.md."""
    return SetupCapabilities()
