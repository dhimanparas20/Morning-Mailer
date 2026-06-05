from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from admin import services
from modules.logger import get_logger

log = get_logger("Admin System")
router = APIRouter(prefix="/system")


@router.get("/redis")
async def redis_status():
    result = services.get_redis_status()
    log.info(f"Redis status: connected={result.get('connected', False)}")
    return JSONResponse(result)


@router.get("/scheduler")
async def scheduler_status():
    return JSONResponse(services.get_scheduler_status())


@router.get("/tokens")
async def tokens_status():
    return JSONResponse(services.check_tokens())


@router.get("/audit-log")
async def audit_log(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    task: str | None = Query(None),
    keyword: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    q: str | None = Query(None),
):
    result = services.get_audit_log(limit=limit, offset=offset, task=task,
                                    keyword=keyword, status_filter=status_filter, q=q)
    return JSONResponse(result)
