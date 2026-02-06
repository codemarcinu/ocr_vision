"""Authentication middleware for FastAPI API and Web UI."""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from app.config import settings

logger = logging.getLogger(__name__)

# In-memory session store (single-user app, no need for DB)
SESSION_MAX_AGE = 8 * 3600  # 8 hours
_active_sessions: dict[str, datetime] = {}  # token -> creation time


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
    if not session_token or not _is_session_valid(session_token):
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
        "/health", "/login", "/logout", "/static",
        "/sw.js", "/offline.html", "/manifest.json",  # PWA files
        "/api/push/vapid-key",  # Push subscription key (public for PWA)
        "/metrics",  # Prometheus scraping
        "/favicon.ico",
    )
    if any(path.startswith(p) for p in public_paths):
        return await call_next(request)

    # Accept Bearer token on any path (API clients + scripts)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if secrets.compare_digest(token, settings.AUTH_TOKEN):
            return await call_next(request)

    # Accept session cookie on any path (browser / mobile PWA)
    session_token = request.cookies.get("session_token", "")
    if session_token and _is_session_valid(session_token):
        return await call_next(request)

    # Unauthenticated: web UI paths get redirect, API paths get 401 JSON
    web_ui_paths = ("/app", "/m")
    is_web_ui = any(path == p or path.startswith(p + "/") for p in web_ui_paths) or path == "/"

    if is_web_ui:
        from urllib.parse import quote
        login_url = f"/login?next={quote(path, safe='/')}"
        return RedirectResponse(url=login_url, status_code=303)

    return JSONResponse(status_code=401, content={"detail": "Brak autoryzacji"})


def _is_session_valid(token: str) -> bool:
    """Check if session token is valid and not expired."""
    if token not in _active_sessions:
        return False
    created = _active_sessions[token]
    if (datetime.utcnow() - created).total_seconds() > SESSION_MAX_AGE:
        _active_sessions.pop(token, None)
        return False
    return True


def create_session() -> str:
    """Create a new session token."""
    token = secrets.token_urlsafe(32)
    _active_sessions[token] = datetime.utcnow()
    return token


def destroy_session(token: str) -> None:
    """Destroy a session."""
    _active_sessions.pop(token, None)
