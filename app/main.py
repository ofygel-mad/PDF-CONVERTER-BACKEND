from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.database import get_resolved_database_url, init_database
from app.services.storage_service import ensure_storage_buckets


def _run_migrations() -> None:
    """Apply pending Alembic migrations, fall back to create_all for SQLite."""
    db_url = get_resolved_database_url()
    if db_url.startswith("sqlite"):
        init_database()
        return
    try:
        from alembic import command
        from alembic.config import Config

        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)
        command.upgrade(alembic_cfg, "head")
    except Exception:
        # Graceful fallback: create all tables directly (no migration history)
        init_database()


@asynccontextmanager
async def lifespan(_: FastAPI):
    _run_migrations()
    try:
        ensure_storage_buckets()
    except Exception:
        pass
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "health": f"{settings.api_v1_prefix}/health",
    }
