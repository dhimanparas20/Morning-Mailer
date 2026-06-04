import time
import secrets
from pathlib import Path
from typing import Optional

from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from admin.config import get_settings

settings = get_settings()

_sessions: dict[str, float] = {}
_CSRF_TOKENS: dict[str, float] = {}


def create_session() -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time()
    return token


def validate_session(token: Optional[str]) -> bool:
    if not token or token not in _sessions:
        return False
    created = _sessions[token]
    if time.time() - created > settings.SESSION_EXPIRE_MINUTES * 60:
        _sessions.pop(token, None)
        return False
    return True


def destroy_session(token: str) -> None:
    _sessions.pop(token, None)


def generate_csrf_token() -> str:
    token = secrets.token_urlsafe(32)
    _CSRF_TOKENS[token] = time.time()
    return token


def validate_csrf_token(token: Optional[str]) -> bool:
    if not token or token not in _CSRF_TOKENS:
        return False
    created = _CSRF_TOKENS.pop(token)
    return time.time() - created < 3600


class AuthMiddleware(BaseHTTPMiddleware):
    EXEMPT_PATHS = {"/login", "/static", "/favicon.ico", "/oauth/callback"}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if any(path.startswith(p) for p in self.EXEMPT_PATHS):
            return await call_next(request)

        session_token = request.cookies.get("session_token")
        if not validate_session(session_token):
            if path.startswith("/api/"):
                raise HTTPException(status_code=401, detail="Unauthorized")
            return RedirectResponse(url="/login", status_code=302)

        return await call_next(request)


def require_auth(request: Request) -> None:
    session_token = request.cookies.get("session_token")
    if not validate_session(session_token):
        raise HTTPException(status_code=401, detail="Unauthorized")


def require_csrf(request: Request) -> None:
    token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    if not validate_csrf_token(token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
