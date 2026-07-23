from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from slowapi import Limiter
from slowapi.util import get_remote_address

from admin import services
from admin.config import get_settings
from modules.logger import get_logger

log = get_logger("Admin OAuth")
router = APIRouter(prefix="/oauth")
templates = Jinja2Templates(directory="admin/templates")
settings = get_settings()
limiter = Limiter(key_func=get_remote_address, storage_uri=settings.REDIS_URL)


@router.get("/callback")
@limiter.limit("10 per minute")
async def oauth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    """OAuth callback — keyword comes from state parameter."""
    keyword = state or "default"
    log.info(f"OAuth callback received for '{keyword}'")

    if error:
        log.error(f"OAuth callback error for '{keyword}': {error}")
        return templates.TemplateResponse(request, "oauth_result.html", {"success": False, "keyword": keyword, "error": error})
    if not code:
        log.warning(f"OAuth callback missing code for '{keyword}'")
        return templates.TemplateResponse(request, "oauth_result.html", {"success": False, "keyword": keyword, "error": "No authorization code received"})

    # Validate keyword format (alphanumeric + underscore/hyphen, max 64 chars)
    import re
    if not re.match(r'^[a-zA-Z0-9_-]{1,64}$', keyword):
        log.warning(f"Invalid keyword format in callback: '{keyword}'")
        return templates.TemplateResponse(request, "oauth_result.html", {"success": False, "keyword": keyword, "error": "Invalid keyword format"})

    success = services.exchange_oauth_code(code, keyword)
    if success:
        log.success(f"OAuth token saved for '{keyword}'")
    else:
        log.error(f"OAuth token exchange failed for '{keyword}'")

    return templates.TemplateResponse(request, "oauth_result.html", {
        "success": success, "keyword": keyword,
        "error": None if success else "Failed to exchange code for token",
    })


@router.get("/{keyword}")
@limiter.limit("20 per minute")
async def oauth_start(request: Request, keyword: str):
    # Validate keyword format
    import re
    if not re.match(r'^[a-zA-Z0-9_-]{1,64}$', keyword):
        log.warning(f"Invalid keyword format: '{keyword}'")
        raise HTTPException(400, "Invalid keyword format")

    # Check if keyword exists in user database
    user = services.get_user(keyword)
    if not user:
        log.warning(f"OAuth flow attempted for non-existent keyword: '{keyword}'")
        raise HTTPException(404, f"User '{keyword}' not found")

    log.info(f"OAuth flow started for '{keyword}'")
    auth_url = services.generate_oauth_url(keyword)
    if not auth_url:
        log.error(f"OAuth URL generation failed for '{keyword}'")
        raise HTTPException(500, "Could not generate OAuth URL. Check client_secret files.")
    return templates.TemplateResponse(request, "oauth_redirect.html", {"auth_url": auth_url, "keyword": keyword})
