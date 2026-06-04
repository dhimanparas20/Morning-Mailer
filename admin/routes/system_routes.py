from fastapi import APIRouter
from fastapi.responses import JSONResponse

from admin import services

router = APIRouter(prefix="/system")


@router.get("/redis")
async def redis_status():
    return JSONResponse(services.get_redis_status())


@router.get("/scheduler")
async def scheduler_status():
    return JSONResponse(services.get_scheduler_status())


@router.get("/tokens")
async def tokens_status():
    return JSONResponse(services.check_tokens())
