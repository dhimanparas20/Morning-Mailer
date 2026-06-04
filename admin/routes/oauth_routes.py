from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from admin import services

router = APIRouter(prefix="/oauth")
templates = Jinja2Templates(directory="admin/templates")


@router.get("/{keyword}")
async def oauth_start(request: Request, keyword: str):
    auth_url = services.generate_oauth_url(keyword)
    if not auth_url:
        raise HTTPException(500, "Could not generate OAuth URL. Check client_secret files.")
    return templates.TemplateResponse(request, "oauth_redirect.html", {"auth_url": auth_url, "keyword": keyword})


@router.get("/{keyword}/callback")
async def oauth_callback(request: Request, keyword: str, code: str = "", error: str = ""):
    if error:
        return templates.TemplateResponse(request, "oauth_result.html", {"success": False, "keyword": keyword, "error": error})
    if not code:
        return templates.TemplateResponse(request, "oauth_result.html", {"success": False, "keyword": keyword, "error": "No authorization code received"})

    success = services.exchange_oauth_code(code, keyword)
    return templates.TemplateResponse(request, "oauth_result.html", {
        "success": success, "keyword": keyword,
        "error": None if success else "Failed to exchange code for token",
    })
