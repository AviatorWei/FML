"""ORM: real-squad injury adjustment records."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class InjuryAdjustment(Base):
    __tablename__ = "injury_adjustments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    real_player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    removed_at: Mapped[datetime] = mapped_column(DateTime)
    refund_amount: Mapped[int] = mapped_column(Integer, default=0)  # unit: million EUR
    free_sign_grant: Mapped[bool] = mapped_column(Boolean, default=False)
    granted_to_manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("managers.id"), nullable=True
    )
