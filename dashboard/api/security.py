"""Opt-in local security policy used by installed app launches."""

from __future__ import annotations

import ipaddress
import os

from fastapi import Request
from fastapi.responses import JSONResponse


def is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    hostname = host
    if host.count(":") == 1:
        hostname = host.split(":", 1)[0]
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def security_enabled() -> bool:
    return os.environ.get("DASHBOARD_ENFORCE_LOCAL_SECURITY", "").casefold() in {"1", "true", "yes"}


async def enforce_local_security(request: Request, call_next):
    """FastAPI middleware callback; health remains available for smoke checks."""
    if not security_enabled():
        return await call_next(request)
    if not is_loopback_host(request.client.host if request.client else None):
        return JSONResponse(status_code=403, content={"detail": "Local access only"})
    if request.url.path == "/health":
        return await call_next(request)
    expected = os.environ.get("DASHBOARD_LOCAL_AUTH_TOKEN")
    supplied = request.headers.get("authorization", "")
    if not expected or supplied != f"Bearer {expected}":
        return JSONResponse(status_code=401, content={"detail": "Local authentication required"})
    return await call_next(request)
