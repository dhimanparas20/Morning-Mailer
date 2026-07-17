import secrets
import hashlib
import base64
import httpx
from urllib.parse import urlencode

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from slowapi import Limiter
from slowapi.util import get_remote_address

from admin.auth import (
    create_session,
    destroy_session,
    validate_session,
    _get_redis,
)
from admin.config import get_settings
from modules.logger import get_logger

log = get_logger("Admin Auth")
router = APIRouter()
templates = Jinja2Templates(directory="admin/templates")
settings = get_settings()
limiter = Limiter(key_func=get_remote_address, storage_uri=settings.REDIS_URL)

# ── Google OAuth Config ────────────────────────────────────────────────────────

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"

# ── OAuth State Store (Redis) ──────────────────────────────────────────────────

_OAUTH_STATE_PREFIX = "mm:oauth_state:"
_OAUTH_STATE_TTL = 600  # 10 minutes


def _save_oauth_state(state: str) -> None:
    r = _get_redis()
    r.setex(_OAUTH_STATE_PREFIX + state, _OAUTH_STATE_TTL, "1")


def _verify_oauth_state(state: str) -> bool:
    if not state:
        return False
    r = _get_redis()
    key = _OAUTH_STATE_PREFIX + state
    if r.exists(key):
        r.delete(key)
        return True
    return False


def _generate_pkce():
    """Generate PKCE code_verifier and code_challenge."""
    code_verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


# ── Routes (all under /admin prefix from main.py) ─────────────────────────────

@router.get("/login", response_class=HTMLResponse)
@limiter.limit("30 per minute")
async def login_page(request: Request):
    """Show login page with Google Sign-In button."""
    session_token = request.cookies.get("session_token")
    if validate_session(session_token):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.get("/auth/login")
async def google_login(request: Request):
    """Initiate Google OAuth flow."""
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        return RedirectResponse(url="/admin/login?error=oauth_not_configured", status_code=302)

    state = secrets.token_urlsafe(32)
    _save_oauth_state(state)

    code_verifier, code_challenge = _generate_pkce()

    # Store code_verifier in Redis for token exchange
    r = _get_redis()
    r.setex(f"mm:oauth_pkce:{state}", _OAUTH_STATE_TTL, code_verifier)

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    }

    auth_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/auth/callback")
@limiter.limit("10 per minute")
async def google_callback(request: Request):
    """Handle Google OAuth callback."""
    # Check for error from Google
    error = request.query_params.get("error")
    if error:
        log.warning(f"Google OAuth error: {error}")
        return RedirectResponse(url="/admin/login?error=auth_failed", status_code=302)

    state = request.query_params.get("state", "")
    code = request.query_params.get("code", "")

    if not state or not code:
        log.warning("OAuth callback: missing state or code")
        return RedirectResponse(url="/admin/login?error=auth_failed", status_code=302)

    # Verify state from Redis
    if not _verify_oauth_state(state):
        log.warning("OAuth callback: invalid or expired state parameter")
        return RedirectResponse(url="/admin/login?error=auth_failed", status_code=302)

    # Retrieve code_verifier from Redis
    r = _get_redis()
    code_verifier = r.get(f"mm:oauth_pkce:{state}")
    r.delete(f"mm:oauth_pkce:{state}")

    # Exchange code for tokens
    token_data = {
        "code": code,
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    if code_verifier:
        token_data["code_verifier"] = code_verifier

    try:
        async with httpx.AsyncClient() as client:
            token_response = await client.post(GOOGLE_TOKEN_URL, data=token_data)
            token_response.raise_for_status()
            tokens = token_response.json()
    except Exception as e:
        log.error(f"Google token exchange failed: {e}")
        return RedirectResponse(url="/admin/login?error=auth_failed", status_code=302)

    access_token = tokens.get("access_token")
    if not access_token:
        log.error("Google token response missing access_token")
        return RedirectResponse(url="/admin/login?error=auth_failed", status_code=302)

    # Get user info
    try:
        async with httpx.AsyncClient() as client:
            userinfo_response = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo_response.raise_for_status()
            user_info = userinfo_response.json()
    except Exception as e:
        log.error(f"Google userinfo fetch failed: {e}")
        return RedirectResponse(url="/admin/login?error=auth_failed", status_code=302)

    email = user_info.get("email", "").lower()
    name = user_info.get("name", "")
    picture = user_info.get("picture", "")

    if not email:
        log.warning("Google userinfo missing email")
        return RedirectResponse(url="/admin/login?error=no_user_info", status_code=302)

    # Check if email is in allowed list
    if email not in settings.admin_email_set:
        log.warning(f"Login denied: '{email}' not in ADMIN_EMAILS")
        return RedirectResponse(url="/admin/access-denied", status_code=302)

    # Create session
    session_token = create_session(user_email=email, user_name=name, user_picture=picture)
    log.success(f"Google login successful: '{email}'")

    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        "session_token",
        session_token,
        httponly=True,
        samesite="lax",
        max_age=settings.SESSION_EXPIRE_MINUTES * 60,
    )
    return response


@router.get("/auth/success")
async def auth_success(request: Request):
    """Fallback: redirect to dashboard after auth."""
    return RedirectResponse(url="/", status_code=302)


@router.get("/access-denied", response_class=HTMLResponse)
async def access_denied(request: Request):
    """Show access denied page for unauthorized emails."""
    return templates.TemplateResponse(request, "access_denied.html", {})


@router.get("/logout")
async def logout(request: Request):
    """Log out and destroy session."""
    token = request.cookies.get("session_token")
    if token:
        destroy_session(token)
    log.info("User logged out")
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie("session_token")
    return response
