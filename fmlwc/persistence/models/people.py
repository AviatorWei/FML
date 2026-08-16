"""ORM: managers, real players, roster entries."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ...core.enums import AcquisitionVia, Position
from ..base import Base


class Manager(Base):
    __tablename__ = "managers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(64), unique=True)
    manager_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)  # unit: million EUR
    # Cup wallet (FMC 第十三条/第七十八条): separate funds for the cup game;
    # during the cup group stage it may only pay for cup-exclusive players.
    cup_balance: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0")  # unit: million EUR
    group_letter: Mapped[str | None] = mapped_column(String(1), nullable=True)
    total_points: Mapped[int] = mapped_column(Integer, default=0)
    eliminated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Player(Base):
    __tablename__ = "players"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    jersey_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[Position] = mapped_column(SAEnum(Position))
    real_team: Mapped[str] = mapped_column(String(64))
    market_value: Mapped[int] = mapped_column(Integer, default=0)  # unit: million EUR


class RosterEntry(Base):
    __tablename__ = "roster_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    acquired_at: Mapped[datetime] = mapped_column(DateTime)
    acquired_via: Mapped[AcquisitionVia] = mapped_column(SAEnum(AcquisitionVia))
    acquired_price: Mapped[int] = mapped_column(Integer, default=0)  # unit: million EUR
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
