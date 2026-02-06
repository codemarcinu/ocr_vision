"""Authentication middleware for FastAPI API and Web UI."""

import hashlib
import logging
import secrets
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from app.config import settings

logger = logging.getLogger(__name__)

# In-memory session store (single-user app, no need for DB)
_active_sessions: set[str] = set()


def _auth_enabled() -> bool:
    """Check if authentication is configured."""
    return bool(settings.AUTH_TOKEN)


def verify_api_token(request: Request) -> None:
    """FastAPI dependency: verify Bearer token for API endpoints."""
    if not _auth_enabled():
        return

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Brak tokena autoryzacji")

    token = auth_header[7:]
    if not secrets.compare_digest(token, settings.AUTH_TOKEN):
        raise HTTPException(status_code=401, detail="Nieprawidłowy token")


def verify_web_session(request: Request) -> None:
    """FastAPI dependency: verify session cookie for Web UI."""
    if not _auth_enabled():
        return

    session_token = request.cookies.get("session_token", "")
    if not session_token or session_token not in _active_sessions:
        raise HTTPException(
            status_code=303,
            headers={"Location": "/login"},
        )


async def web_auth_middleware(request: Request, call_next):
    """Middleware to redirect unauthenticated web requests to login page."""
    if not _auth_enabled():
        return await call_next(request)

    path = request.url.path

    # Public paths - no auth required
    public_paths = (
        "/health", "/login", "/logout", "/static", "/metrics",
        "/docs", "/openapi.json", "/redoc",
        "/sw.js", "/offline.html", "/manifest.json",  # PWA files
        "/api/push/vapid-key"  # Push subscription key (public for PWA)
    )
    if any(path.startswith(p) for p in public_paths):
        return await call_next(request)

    # Web UI paths: check session cookie (includes /app/, /m/, and API calls from PWA)
    web_ui_paths = ("/app/", "/m/", "/", "/api/push/")
    is_web_ui = any(path == p or path.startswith(p.rstrip("/") + "/") for p in web_ui_paths if p != "/") or path == "/"

    # API endpoints: check Bearer token
    if not is_web_ui:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if secrets.compare_digest(token, settings.AUTH_TOKEN):
                return await call_next(request)
        raise HTTPException(status_code=401, detail="Brak autoryzacji")

    # Web UI: check session cookie
    session_token = request.cookies.get("session_token", "")
    if session_token and session_token in _active_sessions:
        return await call_next(request)

    # Redirect to login
    return RedirectResponse(url="/login", status_code=303)


def create_session() -> str:
    """Create a new session token."""
    token = secrets.token_urlsafe(32)
    _active_sessions.add(token)
    return token


def destroy_session(token: str) -> None:
    """Destroy a session."""
    _active_sessions.discard(token)
