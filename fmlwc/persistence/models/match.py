"""ORM: gameweeks, fixtures, lineups, real events, results, bonuses."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ...core.enums import GameweekPhase, MatchOutcome, RealEventType
from ..base import Base


class Gameweek(Base):
    __tablename__ = "gameweeks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    index: Mapped[int] = mapped_column(Integer, unique=True)
    phase: Mapped[GameweekPhase] = mapped_column(SAEnum(GameweekPhase))
    lineup_deadline: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")


class Fixture(Base):
    __tablename__ = "fixtures"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gameweek_id: Mapped[int] = mapped_column(ForeignKey("gameweeks.id"))
    home_manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"))
    away_manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"))
    group_letter: Mapped[str | None] = mapped_column(String(1), nullable=True)
    bracket_slot: Mapped[str | None] = mapped_column(String(8), nullable=True)


class Lineup(Base):
    __tablename__ = "lineups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"))
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"))
    starters: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    pk_order: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    posted_at: Mapped[datetime] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("fixture_id", "manager_id"),)


class RealMatchEvent(Base):
    """Normalised event sourced from external feed (UEFA/Whoscored/manual)."""

    __tablename__ = "real_match_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gameweek_id: Mapped[int] = mapped_column(ForeignKey("gameweeks.id"))
    real_match_id: Mapped[str] = mapped_column(String(64))
    real_player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    event_type: Mapped[RealEventType] = mapped_column(SAEnum(RealEventType))
    value: Mapped[float] = mapped_column(default=1.0)
    minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_extra_time: Mapped[bool] = mapped_column(Boolean, default=False)
    is_shootout: Mapped[bool] = mapped_column(Boolean, default=False)


class MatchResult(Base):
    __tablename__ = "match_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), unique=True)
    home_goals: Mapped[int] = mapped_column(Integer)
    away_goals: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[MatchOutcome] = mapped_column(SAEnum(MatchOutcome))
    pk_winner_id: Mapped[int | None] = mapped_column(ForeignKey("managers.id"), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class BonusAward(Base):
    __tablename__ = "bonus_awards"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"))
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"))
    bonus_type: Mapped[str] = mapped_column(String(32))
    amount: Mapped[int] = mapped_column(Integer)  # unit: million EUR
