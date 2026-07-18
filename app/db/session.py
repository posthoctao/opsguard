from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def configure_database(database_url: str | None = None) -> None:
    global _engine, _session_factory

    url = database_url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine_kwargs: dict = {"pool_pre_ping": True, "connect_args": connect_args}
    if url in {"sqlite://", "sqlite:///:memory:"}:
        engine_kwargs["poolclass"] = StaticPool

    if _engine is not None:
        _engine.dispose()

    _engine = create_engine(url, **engine_kwargs)
    _session_factory = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)


def get_engine() -> Engine:
    if _engine is None:
        configure_database()
    assert _engine is not None
    return _engine


def create_tables() -> None:
    Base.metadata.create_all(bind=get_engine())


def drop_tables() -> None:
    Base.metadata.drop_all(bind=get_engine())


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    if _session_factory is None:
        configure_database()
    assert _session_factory is not None
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    with session_scope() as session:
        yield session
