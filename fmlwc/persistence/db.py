"""SQLAlchemy engine + session factory.

Thin file so unit tests can swap in `make_engine("sqlite:///:memory:")`.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from .base import Base


def make_engine(url: str, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine.

    For SQLite, sets check_same_thread=False so the same engine can be
    shared across the orchestrator's coroutines, and attaches a connect
    listener that enables WAL mode and foreign-key enforcement.
    """
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_engine(url, echo=echo, connect_args=connect_args)

    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, connection_record):  # noqa: ARG001
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a configured sessionmaker."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Transactional scope. Commits on success, rolls back on exception."""
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all(engine: Engine) -> None:
    """Bootstrap empty schema. Dev/demo only — production uses Alembic."""
    # Ensure every model module is imported so its class registers on Base.metadata
    from . import models  # noqa: F401

    Base.metadata.create_all(engine)
    ensure_schema_upgrades(engine)


def ensure_schema_upgrades(engine: Engine) -> None:
    """Additive, idempotent column upgrades for pre-existing SQLite files.

    ``create_all`` never alters existing tables, so columns added after a
    database was first created must be patched in here. Dev/demo only —
    production uses Alembic.
    """
    if not str(engine.url).startswith("sqlite"):
        return
    upgrades = [
        # (table, column, DDL fragment)
        ("gameweeks", "competition",
         "ALTER TABLE gameweeks ADD COLUMN competition VARCHAR(6) "
         "NOT NULL DEFAULT 'LEAGUE'"),
        ("managers", "cup_balance",
         "ALTER TABLE managers ADD COLUMN cup_balance INTEGER "
         "NOT NULL DEFAULT 0"),
        ("match_results", "home_reserve_goals",
         "ALTER TABLE match_results ADD COLUMN home_reserve_goals INTEGER"),
        ("match_results", "away_reserve_goals",
         "ALTER TABLE match_results ADD COLUMN away_reserve_goals INTEGER"),
    ]
    with engine.connect() as conn:
        for table, column, ddl in upgrades:
            cols = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            if not cols:
                continue  # table doesn't exist yet (created fresh above)
            if column not in {c[1] for c in cols}:
                conn.execute(text(ddl))
        conn.commit()
