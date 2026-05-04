"""ORM: eligibility records (anti-collusion / lifetime / cooldown blocks)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ...core.enums import EligibilityRestriction
from ..base import Base


class EligibilityRecord(Base):
    """One row per active restriction. EligibilityService reads them all."""

    __tablename__ = "eligibility_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    restriction_type: Mapped[EligibilityRestriction] = mapped_column(
        SAEnum(EligibilityRestriction)
    )
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
