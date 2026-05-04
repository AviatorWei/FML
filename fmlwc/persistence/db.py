"""SQLAlchemy engine + session factory.

Thin file so unit tests can swap in `make_engine("sqlite:///:memory:")`.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from .base import Base


def make_engine(url: str, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine.

    For SQLite, sets check_same_thread=False so the same engine can be
    shared across the orchestrator's coroutines.
    """
    raise NotImplementedError("TODO: create engine, attach pragmas for SQLite")


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a configured sessionmaker."""
    raise NotImplementedError("TODO")


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Transactional scope. Commits on success, rolls back on exception."""
    raise NotImplementedError("TODO: yield session, commit/rollback/close")


def create_all(engine: Engine) -> None:
    """Bootstrap empty schema. Dev/demo only — production uses Alembic."""
    # Ensure every model module is imported so its class registers on Base.metadata
    from . import models  # noqa: F401

    raise NotImplementedError("TODO: Base.metadata.create_all(engine)")
