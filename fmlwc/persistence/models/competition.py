"""ORM: dual-competition (league + cup) roster fork.

Semantics per FMC 规则 第七十七条/第七十八条:

* During the cup GROUP stage the two games share one roster: any owned
  player whose real team plays the cup is implicitly in the manager's cup
  list (FMC大名单), and sign/release/trade operations affect both games.
  No rows exist in ``cup_roster_entries`` during this phase — the cup list
  is a derived view.

* When the cup enters its knockout stage, the games become independent:
  ``CupState.separated_at`` is stamped and every cup-eligible owned player
  is copied into ``cup_roster_entries``. From then on the cup list is
  authoritative and league/cup operations no longer affect each other —
  a dual player can remain in BOTH rosters and start in both competitions.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from ...core.enums import AcquisitionVia
from ..base import Base


class CupState(Base):
    """Single-row table recording whether/when the cup fork happened."""

    __tablename__ = "cup_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    separated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CupRosterEntry(Base):
    """A manager's cup-list membership AFTER separation (mirror of RosterEntry)."""

    __tablename__ = "cup_roster_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    acquired_at: Mapped[datetime] = mapped_column(DateTime)
    acquired_via: Mapped[AcquisitionVia] = mapped_column(SAEnum(AcquisitionVia))
    acquired_price: Mapped[int] = mapped_column(Integer, default=0)  # unit: million EUR
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
