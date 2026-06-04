from fastapi import APIRouter
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
