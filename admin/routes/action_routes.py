from fastapi import APIRouter, HTTPException, Form
from fastapi.responses import JSONResponse

from admin.auth import validate_csrf_token
from admin import services

router = APIRouter(prefix="/actions")


# ── Status polling ─────────────────────────────────────────────────────────

@router.get("/status/{task_id}")
async def action_task_status(task_id: str):
    result = services.check_task_status(task_id)
    return JSONResponse(result)


# ── Scheduled (respects user schedule) ─────────────────────────────────────

@router.post("/email/summary")
async def action_daily_email_summary():
    try:
        result = services.run_daily_email_summary()
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/whatsapp/summary")
async def action_daily_whatsapp_summary():
    try:
        result = services.run_daily_whatsapp_summary()
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Force (ignores schedule, ALL users) ────────────────────────────────────

@router.post("/email/force")
async def action_force_email():
    try:
        result = services.run_force_email_summary()
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/whatsapp/force")
async def action_force_whatsapp():
    try:
        result = services.run_force_whatsapp_summary()
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Per-user email ─────────────────────────────────────────────────────────

@router.post("/email/send/{keyword}")
async def action_send_email(keyword: str):
    try:
        result = services.run_send_email_summary(keyword)
        return JSONResponse({"ok": True, "result": result})
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Per-user WhatsApp ──────────────────────────────────────────────────────

@router.post("/whatsapp/send/{keyword}")
async def action_send_whatsapp(keyword: str):
    try:
        result = services.run_send_whatsapp_summary(keyword)
        return JSONResponse({"ok": True, "result": result})
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Per-user calendar ──────────────────────────────────────────────────────

@router.post("/calendar/fetch/{keyword}")
async def action_fetch_calendar(keyword: str, days: int = 2):
    try:
        result = services.run_fetch_calendar(keyword, days)
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/calendar/email/{keyword}")
async def action_calendar_email(keyword: str, days: int = 2):
    try:
        result = services.run_send_calendar_email(keyword, days)
        return JSONResponse({"ok": True, "result": result})
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/calendar/whatsapp/{keyword}")
async def action_calendar_whatsapp(keyword: str, days: int = 2):
    try:
        result = services.run_send_calendar_whatsapp(keyword, days)
        return JSONResponse({"ok": True, "result": result})
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/calendar/both/{keyword}")
async def action_calendar_both(keyword: str, days: int = 2):
    try:
        result = services.run_send_calendar_both(keyword, days)
        return JSONResponse({"ok": True, "result": result})
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Test ───────────────────────────────────────────────────────────────────

@router.post("/test/email")
async def action_test_email(subject: str = Form(...), body: str = Form(...)):
    try:
        result = services.run_send_test_email(subject, body)
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/test/whatsapp")
async def action_test_whatsapp(mobile: str = Form(...), message: str = Form(...)):
    try:
        result = services.run_send_test_whatsapp(mobile, message)
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        raise HTTPException(500, str(e))


# ── System ─────────────────────────────────────────────────────────────────

@router.post("/model/switch")
async def action_switch_model(provider: str = Form(...), model_name: str = Form(""), temperature: str = Form("")):
    try:
        temp = float(temperature) if temperature else None
        result = services.run_switch_model(provider, model_name or None, temp)
        return JSONResponse({"ok": True, "message": result})
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/clear/last-run")
async def action_clear_last_run(keyword: str = Form("")):
    try:
        result = services.run_clear_last_run(keyword or None)
        return JSONResponse({"ok": True, "message": result})
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/import")
async def action_import(filepath: str = Form("users.json")):
    try:
        n = services.import_users(filepath)
        return JSONResponse({"ok": True, "count": n})
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/export")
async def action_export(filepath: str = Form("users.json")):
    try:
        n = services.export_users(filepath)
        return JSONResponse({"ok": True, "count": n})
    except Exception as e:
        raise HTTPException(500, str(e))
