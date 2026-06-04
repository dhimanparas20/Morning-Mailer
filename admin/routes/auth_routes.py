from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from admin.auth import create_session, destroy_session, generate_csrf_token, validate_csrf_token, require_auth
from admin.config import get_settings
from admin import services

router = APIRouter()
templates = Jinja2Templates(directory="admin/templates")
settings = get_settings()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    csrf = generate_csrf_token()
    return templates.TemplateResponse(request, "login.html", {"csrf_token": csrf, "error": None})


@router.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...), csrf_token: str = Form(...)):
    if not validate_csrf_token(csrf_token):
        csrf = generate_csrf_token()
        return templates.TemplateResponse(request, "login.html", {"csrf_token": csrf, "error": "Invalid form submission"})

    if username != settings.ADMIN_USERNAME or password != settings.ADMIN_PASSWORD:
        csrf = generate_csrf_token()
        return templates.TemplateResponse(request, "login.html", {"csrf_token": csrf, "error": "Invalid credentials"})

    session_token = create_session()
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie("session_token", session_token, httponly=True, samesite="strict", max_age=settings.SESSION_EXPIRE_MINUTES * 60)
    return response


@router.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("session_token")
    if token:
        destroy_session(token)
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("session_token")
    return response
