import time
import secrets
import json
from typing import Optional
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from functools import lru_cache

from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from jose import JWTError, jwt
import redis

from admin.config import get_settings

settings = get_settings()

ALGORITHM = "HS256"

# ── Redis Connection ───────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_redis() -> redis.Redis:
    """Lazy Redis connection, cached singleton."""
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


# ── Session Store (Redis-backed) ───────────────────────────────────────────────

_SESSION_PREFIX = "mm:session:"
_CSRF_PREFIX = "mm:csrf:"


def create_session(user_email: str, user_name: str = "", user_picture: str = "") -> str:
    """Create a new session in Redis and return the session token."""
    r = _get_redis()
    token = secrets.token_urlsafe(32)
    data = json.dumps({
        "email": user_email,
        "name": user_name,
        "picture": user_picture,
    })
    r.setex(
        _SESSION_PREFIX + token,
        settings.SESSION_EXPIRE_MINUTES * 60,
        data,
    )
    return token


def validate_session(token: Optional[str]) -> Optional[dict]:
    """Validate session token from Redis. Returns session data dict or None."""
    if not token:
        return None
    r = _get_redis()
    raw = r.get(_SESSION_PREFIX + token)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def destroy_session(token: str) -> None:
    r = _get_redis()
    r.delete(_SESSION_PREFIX + token)


# ── CSRF Tokens (Redis-backed) ────────────────────────────────────────────────

CSRF_TTL = 3600  # 1 hour


def generate_csrf_token() -> str:
    r = _get_redis()
    token = secrets.token_urlsafe(32)
    r.setex(_CSRF_PREFIX + token, CSRF_TTL, "1")
    return token


def validate_csrf_token(token: Optional[str]) -> bool:
    if not token:
        return False
    r = _get_redis()
    key = _CSRF_PREFIX + token
    if r.exists(key):
        r.delete(key)
        return True
    return False


def require_csrf(request: Request) -> None:
    token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    if not validate_csrf_token(token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


# ── JWT Helpers (for OAuth callback state) ─────────────────────────────────────

def create_oauth_state_token(email: str) -> str:
    """Create a short-lived JWT for passing user data through OAuth callback."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=5)
    payload = {
        "email": email,
        "exp": expire,
        "jti": uuid4().hex,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)


def verify_oauth_state_token(token: str) -> Optional[str]:
    """Verify OAuth state token. Returns email or None."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("email")
    except JWTError:
        return None


# ── Middleware ──────────────────────────────────────────────────────────────────

class AuthMiddleware(BaseHTTPMiddleware):
    # /admin/login, /admin/auth/* are the admin login routes
    # /oauth/* is Gmail/Calendar per-user OAuth (requires auth)
    # /static, /favicon are assets
    EXEMPT_PATHS = {
        "/admin/login",
        "/admin/auth/login",
        "/admin/auth/callback",
        "/admin/auth/logout",
        "/admin/auth/success",
        "/admin/access-denied",
        "/static",
        "/favicon.ico",
    }

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Always set default user state (templates may reference it)
        request.state.user_email = ""
        request.state.user_name = ""
        request.state.user_picture = ""

        if any(path.startswith(p) for p in self.EXEMPT_PATHS):
            return await call_next(request)

        session_token = request.cookies.get("session_token")
        session = validate_session(session_token)
        if not session:
            if path.startswith("/api/"):
                raise HTTPException(status_code=401, detail="Unauthorized")
            return RedirectResponse(url="/admin/login", status_code=302)

        # Attach user info to request state for templates
        request.state.user_email = session.get("email", "")
        request.state.user_name = session.get("name", "")
        request.state.user_picture = session.get("picture", "")

        return await call_next(request)


def require_auth(request: Request) -> None:
    session_token = request.cookies.get("session_token")
    if not validate_session(session_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
