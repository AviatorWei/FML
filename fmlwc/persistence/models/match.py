"""ORM: gameweeks, fixtures, lineups, match events, results, bonuses, athletics."""

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

from ...core.enums import GameweekPhase, GameweekStatus, MatchOutcome, RealEventType
from ..base import Base


class Gameweek(Base):
    __tablename__ = "gameweeks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    index: Mapped[int] = mapped_column(Integer, unique=True)
    phase: Mapped[GameweekPhase] = mapped_column(SAEnum(GameweekPhase))
    lineup_deadline: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[GameweekStatus] = mapped_column(
        SAEnum(GameweekStatus), default=GameweekStatus.PENDING
    )


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


class MatchEvent(Base):
    """A single in-match event (goal, assist, card, …) for one player.

    Keyed by (gameweek, player) — not fixture — so the user-facing API
    never needs to supply a fixture_id. The DAL converts player→manager
    via lineup snapshots at finalization time.
    """

    __tablename__ = "match_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gameweek_id: Mapped[int] = mapped_column(ForeignKey("gameweeks.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    event_type: Mapped[RealEventType] = mapped_column(SAEnum(RealEventType))
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


class PlayerAthletics(Base):
    """Career scoring stats for one player across the whole season.

    Always reflects the player's total regardless of transfers.
    Per-manager attribution lives in ManagerPlayerAthletics.
    """

    __tablename__ = "player_athletics"
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), primary_key=True)
    goals: Mapped[int] = mapped_column(Integer, default=0)
    own_goals: Mapped[int] = mapped_column(Integer, default=0)
    saved_penalties: Mapped[int] = mapped_column(Integer, default=0)
    missed_penalties: Mapped[int] = mapped_column(Integer, default=0)
    assists: Mapped[int] = mapped_column(Integer, default=0)
    yellows: Mapped[int] = mapped_column(Integer, default=0)
    second_yellow_reds: Mapped[int] = mapped_column(Integer, default=0)
    reds: Mapped[int] = mapped_column(Integer, default=0)


class ManagerStats(Base):
    """Team-level aggregate: sum of all starters a manager has ever fielded.

    Answers "how much has Team X contributed this season?" without a
    per-player breakdown. Attribution is fixed at the gameweek each player
    was fielded, not their current owner.
    """

    __tablename__ = "manager_stats"
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"), primary_key=True)
    goals: Mapped[int] = mapped_column(Integer, default=0)
    own_goals: Mapped[int] = mapped_column(Integer, default=0)
    saved_penalties: Mapped[int] = mapped_column(Integer, default=0)
    missed_penalties: Mapped[int] = mapped_column(Integer, default=0)
    assists: Mapped[int] = mapped_column(Integer, default=0)
    yellows: Mapped[int] = mapped_column(Integer, default=0)
    second_yellow_reds: Mapped[int] = mapped_column(Integer, default=0)
    reds: Mapped[int] = mapped_column(Integer, default=0)


class ManagerPlayerAthletics(Base):
    """Per-player breakdown within a manager's team.

    Answers "which of my players scored what, and when they were on my roster?"
    Composite PK (manager_id, player_id); a player who moves teams gets one
    row per manager they played for.
    """

    __tablename__ = "manager_player_athletics"
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"), primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), primary_key=True)
    goals: Mapped[int] = mapped_column(Integer, default=0)
    own_goals: Mapped[int] = mapped_column(Integer, default=0)
    saved_penalties: Mapped[int] = mapped_column(Integer, default=0)
    missed_penalties: Mapped[int] = mapped_column(Integer, default=0)
    assists: Mapped[int] = mapped_column(Integer, default=0)
    yellows: Mapped[int] = mapped_column(Integer, default=0)
    second_yellow_reds: Mapped[int] = mapped_column(Integer, default=0)
    reds: Mapped[int] = mapped_column(Integer, default=0)
