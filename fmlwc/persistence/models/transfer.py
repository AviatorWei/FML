"""ORM: transfer windows, free signs, trades, releases, dismissals."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ...core.enums import TradeSide, TradeStatus, TransferWindowStatus
from ..base import Base


class TransferWindow(Base):
    __tablename__ = "transfer_windows"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opens_at: Mapped[datetime] = mapped_column(DateTime)
    closes_at: Mapped[datetime] = mapped_column(DateTime)
    free_sign_period_seconds: Mapped[int] = mapped_column(Integer)
    status: Mapped[TransferWindowStatus] = mapped_column(
        SAEnum(TransferWindowStatus), default=TransferWindowStatus.PENDING
    )


class FreeSign(Base):
    __tablename__ = "free_signs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    window_id: Mapped[int] = mapped_column(ForeignKey("transfer_windows.id"))
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    fee: Mapped[int] = mapped_column(Integer)  # unit: million EUR
    posted_at: Mapped[datetime] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    effective: Mapped[bool] = mapped_column(Boolean, default=False)


class Trade(Base):
    __tablename__ = "trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    window_id: Mapped[int] = mapped_column(ForeignKey("transfer_windows.id"))
    initiator_id: Mapped[int] = mapped_column(ForeignKey("managers.id"))
    counterparty_id: Mapped[int] = mapped_column(ForeignKey("managers.id"))
    status: Mapped[TradeStatus] = mapped_column(
        SAEnum(TradeStatus), default=TradeStatus.PROPOSED
    )
    proposed_at: Mapped[datetime] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TradeLeg(Base):
    """One side's contribution to a trade.

    Either `player_id` or `cash_amount` is non-null.
    """

    __tablename__ = "trade_legs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id"))
    side: Mapped[TradeSide] = mapped_column(SAEnum(TradeSide))
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    cash_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)  # unit: million EUR


class Release(Base):
    __tablename__ = "releases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    posted_at: Mapped[datetime] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    effective: Mapped[bool] = mapped_column(Boolean, default=False)


class Dismissal(Base):
    """Admin-forced removal of a player from a manager's roster.

    Unlike Release there is no revoke window — the effect is immediate.
    The eligibility block (DISMISSED_LIFETIME) prevents the dismissing
    manager from re-signing the player for the rest of the season.
    """

    __tablename__ = "dismissals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    dismissed_at: Mapped[datetime] = mapped_column(DateTime)
    reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
