from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


_engine = None
_session_factory = None
_resolved_database_url = None
_initialized = False


def _default_sqlite_url() -> str:
    """Get default SQLite URL for fallback."""
    db_path = Path(__file__).resolve().parents[2] / "data" / "pdf_converter.db"
    return f"sqlite:///{db_path.as_posix()}"


def _pick_database_url() -> str:
    """Pick database URL - use test DB if running tests."""
    if os.getenv("PYTEST_CURRENT_TEST"):
        return _default_sqlite_url()
    return settings.database_url


def get_engine():
    """Get or create database engine with automatic fallback to SQLite."""
    global _engine, _resolved_database_url
    
    if _engine is not None:
        return _engine

    primary_url = _pick_database_url()
    fallback_url = _default_sqlite_url()
    
    # Try primary database first
    safe_url = primary_url.split("@")[-1] if "@" in primary_url else "database"
    log.info("Attempting to connect to database at %s", safe_url)

    try:
        connect_args = {"check_same_thread": False} if primary_url.startswith("sqlite") else {"connect_timeout": 10}
        engine = create_engine(
            primary_url, 
            future=True, 
            pool_pre_ping=True, 
            connect_args=connect_args,
            echo=False  # Disable echo to reduce noise
        )
        
        # Test connection
        with engine.connect() as connection:
            log.info("Testing database connection...")
            connection.execute(text("SELECT 1"))
            log.info("✓ Primary database connection established")
        
        _engine = engine
        _resolved_database_url = primary_url
        return _engine
        
    except Exception as exc:
        log.warning("Primary database unavailable, using SQLite fallback: %s", exc)
        
        # Fallback to SQLite
        try:
            connect_args = {"check_same_thread": False}
            _engine = create_engine(
                fallback_url, 
                future=True, 
                pool_pre_ping=True, 
                connect_args=connect_args
            )
            log.info("✓ Fallback SQLite database ready")
            _resolved_database_url = fallback_url
            return _engine
        except Exception as exc2:
            log.error("Even SQLite fallback failed: %s", exc2)
            raise


def get_resolved_database_url() -> str:
    """Get the actual database URL being used."""
    get_engine()
    return _resolved_database_url or _default_sqlite_url()


def get_session_factory():
    """Get or create session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, future=True)
    init_database()
    return _session_factory


@contextmanager
def db_session() -> Session:
    """Context manager for database sessions."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_database() -> None:
    """Initialize database schema if needed."""
    global _initialized
    if _initialized:
        return

    try:
        Base.metadata.create_all(bind=get_engine())
        _initialized = True
        log.info("✓ Database schema initialized")
    except Exception as exc:
        log.error("Failed to initialize database schema: %s", exc)
        # Don't raise - app can still run
