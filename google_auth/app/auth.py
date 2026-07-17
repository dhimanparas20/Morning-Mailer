from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.templating import Jinja2Templates
from authlib.integrations.starlette_client import OAuth

from google_auth.app.config import settings
from google_auth.app.dependencies import (
    create_access_token,
    create_refresh_token,
    revoke_token,
    verify_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="google_auth/templates")
security = HTTPBearer(auto_error=False)

oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

# Valid error codes to prevent XSS via error param
VALID_ERROR_CODES = {"auth_failed", "no_user_info", "session_expired"}


@router.get("/login")
async def login(request: Request):
    redirect_uri = settings.GOOGLE_REDIRECT_URI
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/callback")
async def callback(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception:
        return RedirectResponse(url="/login?error=auth_failed")

    user_info = token.get("userinfo")
    if not user_info:
        return RedirectResponse(url="/login?error=no_user_info")

    user_data = {
        "sub": user_info["sub"],
        "email": user_info["email"],
        "name": user_info.get("name", ""),
        "picture": user_info.get("picture", ""),
    }

    access_token = create_access_token(data=user_data)
    refresh_token = create_refresh_token(data=user_data)

    # Use signed session cookie to pass tokens (avoids URL leakage)
    response = RedirectResponse(url="/auth/success")
    response.set_cookie(
        key="_auth_tokens",
        value=f"{access_token}|{refresh_token}",
        httponly=True,
        secure=settings.APP_BASE_URL.startswith("https"),
        samesite="lax",
        max_age=60,  # Short-lived - only for the redirect
    )
    return response


@router.get("/success")
async def auth_success(request: Request):
    # Retrieve tokens from signed session cookie
    tokens = request.cookies.get("_auth_tokens")
    if not tokens or "|" not in tokens:
        return RedirectResponse(url="/login?error=session_expired")

    parts = tokens.split("|", 1)
    if len(parts) != 2:
        return RedirectResponse(url="/login?error=session_expired")

    access_token, refresh_token = parts

    response = templates.TemplateResponse(
        request,
        "pages/auth_success.html",
        {
            "request": request,
            "project_name": settings.PROJECT_NAME,
            "access_token": access_token,
            "refresh_token": refresh_token,
        },
    )
    # Clear the cookie after use
    response.delete_cookie("_auth_tokens")
    return response


@router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Revoke the current access token so it can no longer be used."""
    if credentials:
        payload = verify_token(credentials.credentials, token_type="access")
        jti = payload.get("jti")
        if jti:
            revoke_token(jti)
    return {"message": "Logged out"}


@router.get("/logout")
async def logout_get():
    """GET logout for browser navigation (clears client-side tokens)."""
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
