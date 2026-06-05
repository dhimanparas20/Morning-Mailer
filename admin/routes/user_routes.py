import os
import json
from fastapi import APIRouter, Request, Form, HTTPException, Query, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from admin.auth import generate_csrf_token, validate_csrf_token, require_auth
from admin import services
from modules.logger import get_logger

log = get_logger("Admin Routes")
router = APIRouter(prefix="/users")
templates = Jinja2Templates(directory="admin/templates")


@router.get("", response_class=HTMLResponse)
async def users_list(request: Request, search: str = "", sort: str = "name", order: str = "asc"):
    users = services.list_users()

    if search:
        q = search.lower()
        users = [u for u in users if q in u.get("name", "").lower() or q in u.get("email", "").lower() or q in u.get("keyword", "").lower()]

    reverse = order == "desc"
    users.sort(key=lambda u: str(u.get(sort, "")).lower(), reverse=reverse)

    token_status = {t["keyword"]: t["has_token"] for t in services.check_tokens()}
    csrf = generate_csrf_token()

    return templates.TemplateResponse(request, "users.html", {
        "users": users, "token_status": token_status,
        "search": search, "sort": sort, "order": order, "csrf_token": csrf,
    })


@router.get("/api/json")
async def users_json(request: Request, search: str = "", sort: str = "name", order: str = "asc"):
    users = services.list_users()
    if search:
        q = search.lower()
        users = [u for u in users if q in u.get("name", "").lower() or q in u.get("email", "").lower() or q in u.get("keyword", "").lower()]
    reverse = order == "desc"
    users.sort(key=lambda u: str(u.get(sort, "")).lower(), reverse=reverse)
    token_status = {t["keyword"]: t for t in services.check_tokens()}
    for u in users:
        tok = token_status.get(u.get("keyword"), {})
        u["_has_token"] = tok.get("has_token", False) if isinstance(tok, dict) else bool(tok)
    return JSONResponse(users)


@router.get("/api/fields")
async def user_fields_json():
    return JSONResponse(services.user_fields())


@router.get("/api/stats")
async def user_stats_json():
    from admin.services import get_last_summary_stats
    return JSONResponse(get_last_summary_stats())


@router.get("/api/tokens")
async def tokens_json():
    return JSONResponse(services.check_tokens())


@router.get("/add", response_class=HTMLResponse)
async def add_user_page(request: Request):
    csrf = generate_csrf_token()
    return templates.TemplateResponse(request, "user_form.html", {
        "user": None, "csrf_token": csrf, "mode": "add",
        "env_smtp_user": os.getenv("EMAIL_HOST_USER", ""),
        "env_smtp_password": os.getenv("EMAIL_HOST_PASSWORD", ""),
    })


@router.post("/add")
async def add_user_submit(
    request: Request,
    name: str = Form(...), email: str = Form(...), keyword: str = Form(...),
    active: str = Form("false"), use_email: str = Form("false"), use_whatsapp: str = Form("false"),
    fetch_calendar: str = Form("false"), max_email_results: str = Form(""), days_threshold: str = Form(""),
    schedule_time: str = Form(""), smtp_host_user: str = Form(""), smtp_host_password: str = Form(""),
    mobile: str = Form(""), summary_template: str = Form(""), csrf_token: str = Form(...),
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(403, "Invalid CSRF token")

    data = {
        "name": name, "email": email, "keyword": keyword,
        "active": active == "true", "use_email": use_email == "true",
        "use_whatsapp": use_whatsapp == "true", "fetch_calendar": fetch_calendar == "true",
    }
    if max_email_results:
        data["max_email_results"] = int(max_email_results)
    if days_threshold:
        data["days_threshold"] = int(days_threshold)
    if schedule_time:
        data["schedule_time"] = schedule_time
    if smtp_host_user:
        data["smtp_host_user"] = smtp_host_user
    if smtp_host_password:
        data["smtp_host_password"] = smtp_host_password
    if mobile:
        data["mobile"] = mobile
    if summary_template:
        data["summary_template"] = summary_template

    try:
        services.create_user(data)
        log.success(f"Created user '{keyword}' via form")
    except ValueError as e:
        users = services.list_users()
        token_status = {t["keyword"]: t for t in services.check_tokens()}
        csrf = generate_csrf_token()
        return templates.TemplateResponse(request, "users.html", {
            "users": users, "token_status": token_status,
            "search": "", "sort": "name", "order": "asc", "csrf_token": csrf,
            "error": str(e),
        })

    return {"ok": True, "message": f"User '{keyword}' created"}


@router.get("/api/{keyword}")
async def get_user_json(keyword: str):
    user = services.get_user(keyword)
    if not user:
        raise HTTPException(404, "User not found")
    user["_has_token"] = services.has_valid_token(keyword)
    return JSONResponse(user)


@router.get("/{keyword}/edit", response_class=HTMLResponse)
async def edit_user_page(request: Request, keyword: str, updated: str = ""):
    user = services.get_user(keyword)
    if not user:
        raise HTTPException(404, "User not found")
    csrf = generate_csrf_token()
    return templates.TemplateResponse(request, "user_form.html", {
        "user": user, "csrf_token": csrf, "mode": "edit",
        "env_smtp_user": os.getenv("EMAIL_HOST_USER", ""),
        "env_smtp_password": os.getenv("EMAIL_HOST_PASSWORD", ""),
        "success_msg": "User updated successfully" if updated == "1" else None,
    })


@router.post("/{keyword}/edit")
async def edit_user_submit(
    request: Request, keyword: str,
    name: str = Form(...), email: str = Form(...),
    active: str = Form("true"), use_email: str = Form("true"), use_whatsapp: str = Form("true"),
    fetch_calendar: str = Form("false"), max_email_results: str = Form(""), days_threshold: str = Form(""),
    schedule_time: str = Form(""), smtp_host_user: str = Form(""), smtp_host_password: str = Form(""),
    mobile: str = Form(""), summary_template: str = Form(""), csrf_token: str = Form(...),
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(403, "Invalid CSRF token")

    data = {
        "name": name, "email": email,
        "active": active == "true", "use_email": use_email == "true",
        "use_whatsapp": use_whatsapp == "true", "fetch_calendar": fetch_calendar == "true",
    }
    if max_email_results:
        data["max_email_results"] = int(max_email_results)
    if days_threshold:
        data["days_threshold"] = int(days_threshold)
    if schedule_time:
        data["schedule_time"] = schedule_time
    # Always include SMTP fields to allow clearing them (empty = remove key, use .env defaults)
    data["smtp_host_user"] = smtp_host_user
    data["smtp_host_password"] = smtp_host_password
    if mobile:
        data["mobile"] = mobile
    if summary_template:
        data["summary_template"] = summary_template

    try:
        services.update_user(keyword, data)
    except ValueError as e:
        raise HTTPException(400, str(e))

    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"/users/{keyword}/edit?updated=1", status_code=303)


@router.post("/{keyword}/delete")
async def delete_user_submit(keyword: str, csrf_token: str = Form(...)):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(403, "Invalid CSRF token")
    services.delete_user(keyword)
    log.success(f"Deleted user '{keyword}' via form")
    return {"ok": True, "message": f"User '{keyword}' deleted"}


@router.post("/{keyword}/activate")
async def activate_user_submit(keyword: str, csrf_token: str = Form(...)):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(403, "Invalid CSRF token")
    services.activate_user(keyword)
    log.success(f"Activated user '{keyword}' via form")
    return {"ok": True, "message": f"User '{keyword}' activated"}


@router.post("/{keyword}/deactivate")
async def deactivate_user_submit(keyword: str, csrf_token: str = Form(...)):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(403, "Invalid CSRF token")
    services.deactivate_user(keyword)
    log.success(f"Deactivated user '{keyword}' via form")
    return {"ok": True, "message": f"User '{keyword}' deactivated"}


@router.post("/{keyword}/token/revoke")
async def revoke_token_submit(keyword: str, csrf_token: str = Form(...)):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(403, "Invalid CSRF token")
    revoked = services.revoke_token(keyword)
    if revoked:
        log.success(f"Revoked token for '{keyword}'")
        return {"ok": True, "message": f"Token revoked for '{keyword}'"}
    raise HTTPException(404, "Token not found")


@router.post("/import")
async def import_users_submit(request: Request, file: UploadFile = File(None), csrf_token: str = Form(...)):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(403, "Invalid CSRF token")
    if file and file.filename:
        content = await file.read()
        try:
            users = json.loads(content)
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"Invalid JSON: {e}")
        if not isinstance(users, list):
            raise HTTPException(400, "JSON must be an array of user objects")
        n = services.import_users_from_list(users)
        log.success(f"Imported {n} user(s) from uploaded file '{file.filename}'")
        return {"ok": True, "message": f"Imported {n} user(s)", "count": n}
    filepath: str = "users.json"
    n = services.import_users(filepath)
    log.success(f"Imported {n} user(s) from {filepath}")
    return {"ok": True, "message": f"Imported {n} user(s)", "count": n}


@router.post("/export")
async def export_users_submit(filepath: str = Form("users.json"), csrf_token: str = Form(...)):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(403, "Invalid CSRF token")
    n = services.export_users(filepath)
    log.success(f"Exported {n} user(s) to {filepath}")
    return {"ok": True, "message": f"Exported {n} user(s)", "count": n}


@router.get("/export/csv")
async def export_users_csv():
    import io
    from fastapi.responses import StreamingResponse
    csv_data = services.export_users_csv()
    if not csv_data:
        raise HTTPException(404, "No users to export")
    return StreamingResponse(
        io.StringIO(csv_data),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=users.csv"},
    )


@router.get("/export/json")
async def export_users_json():
    from fastapi.responses import StreamingResponse
    import io
    users = services.list_users()
    if not users:
        raise HTTPException(404, "No users to export")
    data = json.dumps(users, indent=2, default=str)
    return StreamingResponse(
        io.StringIO(data),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=users.json"},
    )


@router.post("/clear")
async def clear_users_submit(csrf_token: str = Form(...)):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(403, "Invalid CSRF token")
    n = services.clear_users()
    log.success(f"Cleared {n} user(s)")
    return {"ok": True, "message": f"Cleared {n} user(s)", "count": n}
