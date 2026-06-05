import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from admin.config import get_settings
from admin.auth import AuthMiddleware
from admin.routes import auth_routes, user_routes, action_routes, oauth_routes, system_routes
from modules.generics import format_timestamp as _fmt_ts

settings = get_settings()

app = FastAPI(title="Morning Mailer Admin", docs_url=None, redoc_url=None)

app.add_middleware(AuthMiddleware)

app.mount("/static", StaticFiles(directory="admin/static"), name="static")

app.include_router(auth_routes.router)
app.include_router(user_routes.router)
app.include_router(action_routes.router)
app.include_router(oauth_routes.router)
app.include_router(system_routes.router)

templates = Jinja2Templates(directory="admin/templates")
templates.env.filters["format_timestamp"] = _fmt_ts
templates.env.filters["fmt_duration"] = lambda d: f"{d:.2f}s" if isinstance(d, (int, float)) else "-"


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    from admin import services
    users = services.list_users()
    redis_status = services.get_redis_status()
    scheduler = services.get_scheduler_status()
    tokens = services.check_tokens()
    return templates.TemplateResponse(request, "dashboard.html", {
        "users": users,
        "redis_status": redis_status, "scheduler": scheduler, "tokens": tokens,
        "user_stats": services.get_last_summary_stats(),
    })


@app.get("/audit-log", response_class=HTMLResponse)
async def audit_log_page(request: Request):
    from admin import services
    result = services.get_audit_log(limit=100)
    return templates.TemplateResponse(request, "audit_log.html", {
        "entries": result["entries"],
        "total": result["total"],
        "limit": result["limit"],
        "all_tasks": result["tasks"],
        "all_keywords": result["keywords"],
        "all_statuses": result["statuses"],
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("admin.main:app", host=settings.ADMIN_HOST, port=settings.ADMIN_PORT, reload=True)
