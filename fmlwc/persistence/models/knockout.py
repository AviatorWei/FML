"""ORM: knockout-only artefacts — roster snapshots and picks."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class RosterSnapshot(Base):
    __tablename__ = "roster_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"))
    taken_at: Mapped[datetime] = mapped_column(DateTime)
    reason: Mapped[str] = mapped_column(String(32))
    entries: Mapped[list[dict[str, Any]]] = mapped_column(JSON)


class Pick(Base):
    __tablename__ = "picks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    knockout_fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"))
    picker_manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"))
    picked_player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    picked_at: Mapped[datetime] = mapped_column(DateTime)
