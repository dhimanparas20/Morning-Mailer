from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from admin import services
from modules.logger import get_logger

log = get_logger("Admin OAuth")
router = APIRouter(prefix="/oauth")
templates = Jinja2Templates(directory="admin/templates")


@router.get("/callback")
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
async def oauth_start(request: Request, keyword: str):
    log.info(f"OAuth flow started for '{keyword}'")
    auth_url = services.generate_oauth_url(keyword)
    if not auth_url:
        log.error(f"OAuth URL generation failed for '{keyword}'")
        raise HTTPException(500, "Could not generate OAuth URL. Check client_secret files.")
    return templates.TemplateResponse(request, "oauth_redirect.html", {"auth_url": auth_url, "keyword": keyword})
