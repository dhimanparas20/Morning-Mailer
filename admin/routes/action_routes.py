from fastapi import APIRouter, HTTPException, Form, Request
from fastapi.responses import JSONResponse

from admin.auth import validate_csrf_token
from admin import services
from modules.logger import get_logger

log = get_logger("Admin Actions")
router = APIRouter(prefix="/actions")


# ── History ────────────────────────────────────────────────────────────────

@router.get("/history/{keyword}")
async def action_user_history(keyword: str, limit: int = 20):
    result = services.get_history(keyword, limit)
    return JSONResponse({"ok": True, "history": result})


# ── Status polling ─────────────────────────────────────────────────────────

@router.get("/status/{task_id}")
async def action_task_status(task_id: str):
    result = services.check_task_status(task_id)
    return JSONResponse(result)


# ── Scheduled (respects user schedule) ─────────────────────────────────────

@router.post("/email/summary")
async def action_daily_email_summary():
    try:
        log.info("Triggering daily email summary")
        result = services.run_daily_email_summary()
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        log.error(f"Daily email summary failed: {e}")
        raise HTTPException(500, str(e))


@router.post("/whatsapp/summary")
async def action_daily_whatsapp_summary():
    try:
        log.info("Triggering daily WhatsApp summary")
        result = services.run_daily_whatsapp_summary()
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        log.error(f"Daily WhatsApp summary failed: {e}")
        raise HTTPException(500, str(e))


# ── Force (ignores schedule, ALL users) ────────────────────────────────────

@router.post("/email/force")
async def action_force_email():
    try:
        log.info("Triggering force email for ALL users")
        result = services.run_force_email_summary()
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        log.error(f"Force email failed: {e}")
        raise HTTPException(500, str(e))


@router.post("/whatsapp/force")
async def action_force_whatsapp():
    try:
        log.info("Triggering force WhatsApp for ALL users")
        result = services.run_force_whatsapp_summary()
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        log.error(f"Force WhatsApp failed: {e}")
        raise HTTPException(500, str(e))


# ── Per-user email ─────────────────────────────────────────────────────────

@router.post("/email/send/{keyword}")
async def action_send_email(keyword: str):
    try:
        log.info(f"Sending email for user '{keyword}'")
        result = services.run_send_email_summary(keyword)
        return JSONResponse({"ok": True, "result": result})
    except ValueError as e:
        log.warning(f"Email send failed for '{keyword}': {e}")
        raise HTTPException(400, str(e))
    except Exception as e:
        log.error(f"Email send failed for '{keyword}': {e}")
        raise HTTPException(500, str(e))


# ── Per-user WhatsApp ──────────────────────────────────────────────────────

@router.post("/whatsapp/send/{keyword}")
async def action_send_whatsapp(keyword: str):
    try:
        log.info(f"Sending WhatsApp for user '{keyword}'")
        result = services.run_send_whatsapp_summary(keyword)
        return JSONResponse({"ok": True, "result": result})
    except ValueError as e:
        log.warning(f"WhatsApp send failed for '{keyword}': {e}")
        raise HTTPException(400, str(e))
    except Exception as e:
        log.error(f"WhatsApp send failed for '{keyword}': {e}")
        raise HTTPException(500, str(e))


# ── Per-user calendar ──────────────────────────────────────────────────────

@router.post("/calendar/fetch/{keyword}")
async def action_fetch_calendar(keyword: str, days: int = 2):
    try:
        log.info(f"Fetching calendar for user '{keyword}' (days={days})")
        result = services.run_fetch_calendar(keyword, days)
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        log.error(f"Calendar fetch failed for '{keyword}': {e}")
        raise HTTPException(500, str(e))


@router.post("/calendar/email/{keyword}")
async def action_calendar_email(keyword: str, days: int = 2):
    try:
        log.info(f"Sending calendar email for user '{keyword}' (days={days})")
        result = services.run_send_calendar_email(keyword, days)
        return JSONResponse({"ok": True, "result": result})
    except ValueError as e:
        log.warning(f"Calendar email failed for '{keyword}': {e}")
        raise HTTPException(400, str(e))
    except Exception as e:
        log.error(f"Calendar email failed for '{keyword}': {e}")
        raise HTTPException(500, str(e))


@router.post("/calendar/whatsapp/{keyword}")
async def action_calendar_whatsapp(keyword: str, days: int = 2):
    try:
        log.info(f"Sending calendar WhatsApp for user '{keyword}' (days={days})")
        result = services.run_send_calendar_whatsapp(keyword, days)
        return JSONResponse({"ok": True, "result": result})
    except ValueError as e:
        log.warning(f"Calendar WhatsApp failed for '{keyword}': {e}")
        raise HTTPException(400, str(e))
    except Exception as e:
        log.error(f"Calendar WhatsApp failed for '{keyword}': {e}")
        raise HTTPException(500, str(e))


@router.post("/calendar/both/{keyword}")
async def action_calendar_both(keyword: str, days: int = 2):
    try:
        log.info(f"Sending calendar both channels for user '{keyword}' (days={days})")
        result = services.run_send_calendar_both(keyword, days)
        return JSONResponse({"ok": True, "result": result})
    except ValueError as e:
        log.warning(f"Calendar both failed for '{keyword}': {e}")
        raise HTTPException(400, str(e))
    except Exception as e:
        log.error(f"Calendar both failed for '{keyword}': {e}")
        raise HTTPException(500, str(e))


# ── Test ───────────────────────────────────────────────────────────────────

@router.post("/test/email")
async def action_test_email(subject: str = Form(...), body: str = Form(...)):
    try:
        log.info(f"Test email enqueued: subject='{subject}'")
        result = services.run_send_test_email(subject, body)
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        log.error(f"Test email failed: {e}")
        raise HTTPException(500, str(e))


@router.post("/test/whatsapp")
async def action_test_whatsapp(mobile: str = Form(...), message: str = Form(...)):
    try:
        log.info(f"Test WhatsApp enqueued: mobile='{mobile}'")
        result = services.run_send_test_whatsapp(mobile, message)
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        log.error(f"Test WhatsApp failed: {e}")
        raise HTTPException(500, str(e))


# ── System ─────────────────────────────────────────────────────────────────

@router.post("/model/switch")
async def action_switch_model(provider: str = Form(...), model_name: str = Form(""), temperature: str = Form("")):
    try:
        log.info(f"Switching model to {provider} ({model_name or 'default'})")
        temp = float(temperature) if temperature else None
        result = services.run_switch_model(provider, model_name or None, temp)
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        log.error(f"Model switch failed: {e}")
        raise HTTPException(500, str(e))


@router.post("/clear/last-run")
async def action_clear_last_run(keyword: str = Form("")):
    try:
        log.info(f"Clearing last_run for {keyword or 'all'}")
        result = services.run_clear_last_run(keyword or None)
        return JSONResponse({"ok": True, "message": result})
    except Exception as e:
        log.error(f"Clear last_run failed: {e}")
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


# ── Bulk actions ──────────────────────────────────────────────────────────

@router.post("/bulk/email")
async def action_bulk_email(request: Request):
    try:
        body = await request.json()
        keywords = body.get("keywords", [])
        if not keywords:
            raise HTTPException(400, "No keywords provided")
        log.info(f"Bulk email for {len(keywords)} user(s)")
        result = services.bulk_send_email(keywords)
        return JSONResponse({"ok": True, "result": result})
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Bulk email failed: {e}")
        raise HTTPException(500, str(e))


@router.post("/bulk/whatsapp")
async def action_bulk_whatsapp(request: Request):
    try:
        body = await request.json()
        keywords = body.get("keywords", [])
        if not keywords:
            raise HTTPException(400, "No keywords provided")
        log.info(f"Bulk WhatsApp for {len(keywords)} user(s)")
        result = services.bulk_send_whatsapp(keywords)
        return JSONResponse({"ok": True, "result": result})
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Bulk WhatsApp failed: {e}")
        raise HTTPException(500, str(e))


@router.post("/bulk/revoke")
async def action_bulk_revoke(request: Request):
    try:
        body = await request.json()
        keywords = body.get("keywords", [])
        if not keywords:
            raise HTTPException(400, "No keywords provided")
        log.info(f"Bulk revoke for {len(keywords)} user(s)")
        result = services.bulk_revoke_tokens(keywords)
        return JSONResponse({"ok": True, "result": result})
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Bulk revoke failed: {e}")
        raise HTTPException(500, str(e))
