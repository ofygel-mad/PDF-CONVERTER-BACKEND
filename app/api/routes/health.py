from __future__ import annotations

from sqlalchemy import text

from fastapi import APIRouter
from redis import Redis

from app.core.config import settings
from app.core.database import get_engine
from app.services.storage_service import get_storage_health

router = APIRouter()


@router.get("/health")
async def healthcheck() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.environment,
    }


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness() -> dict:
    db_ok = _database_ready()
    redis_ok = _redis_ready()
    storage_ok, storage_reason = get_storage_health()
    status = "ok" if db_ok and redis_ok and storage_ok else "degraded"
    return {
        "status": status,
        "database": "ok" if db_ok else "error",
        "redis": "ok" if redis_ok else "error",
        "storage": storage_reason if storage_ok else storage_reason,
    }


def _database_ready() -> bool:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _redis_ready() -> bool:
    try:
        client = Redis.from_url(settings.redis_url)
        return bool(client.ping())
    except Exception:
        return False
