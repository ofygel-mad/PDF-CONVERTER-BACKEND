from __future__ import annotations

import os
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


_engine = None
_session_factory = None
_resolved_database_url = None
_initialized = False


def _default_sqlite_url() -> str:
    db_path = Path(__file__).resolve().parents[2] / "data" / "pdf_converter.db"
    return f"sqlite:///{db_path.as_posix()}"


def _pick_database_url() -> str:
    if os.getenv("PYTEST_CURRENT_TEST"):
        return _default_sqlite_url()
    return settings.database_url


def get_engine():
    global _engine, _resolved_database_url
    if _engine is not None:
        return _engine

    primary_url = _pick_database_url()
    fallback_url = _default_sqlite_url()
    connect_args = {"check_same_thread": False} if primary_url.startswith("sqlite") else {}
    try:
        engine = create_engine(primary_url, future=True, pool_pre_ping=True, connect_args=connect_args)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        _engine = engine
        _resolved_database_url = primary_url
        return _engine
    except SQLAlchemyError:
        connect_args = {"check_same_thread": False}
        _engine = create_engine(fallback_url, future=True, pool_pre_ping=True, connect_args=connect_args)
        _resolved_database_url = fallback_url
        return _engine


def get_resolved_database_url() -> str:
    get_engine()
    return _resolved_database_url or _default_sqlite_url()


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, future=True)
    init_database()
    return _session_factory


@contextmanager
def db_session() -> Session:
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
    global _initialized
    if _initialized:
        return
    from app.models.persistence import CorrectionMemoryRecord
    from app.models.persistence import JobRecord
    from app.models.persistence import OCRMappingTemplateRecord
    from app.models.persistence import OCRReviewRecord
    from app.models.persistence import OnboardingProjectRecord
    from app.models.persistence import OnboardingSampleRecord
    from app.models.persistence import PreferenceRecordDB
    from app.models.persistence import SessionRecord
    from app.models.persistence import TransformationTemplateRecord

    Base.metadata.create_all(bind=get_engine())
    _initialized = True
