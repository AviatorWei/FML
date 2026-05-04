"""ORM: auction rounds, submissions, bids, results."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ...core.enums import AuctionRoundStatus, BidStatus
from ..base import Base


class AuctionRound(Base):
    __tablename__ = "auction_rounds"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    index: Mapped[int] = mapped_column(Integer, unique=True)
    opens_at: Mapped[datetime] = mapped_column(DateTime)
    closes_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[AuctionRoundStatus] = mapped_column(
        SAEnum(AuctionRoundStatus), default=AuctionRoundStatus.OPEN
    )


class Submission(Base):
    """One manager's full bid sheet for one round."""

    __tablename__ = "submissions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("auction_rounds.id"))
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"))
    received_at: Mapped[datetime] = mapped_column(DateTime)
    source_file: Mapped[str | None] = mapped_column(String(256), nullable=True)
    __table_args__ = (UniqueConstraint("round_id", "manager_id"),)


class Bid(Base):
    __tablename__ = "bids"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    amount: Mapped[int] = mapped_column(Integer)  # unit: million EUR
    rank_in_position: Mapped[int] = mapped_column(Integer)
    status: Mapped[BidStatus] = mapped_column(
        SAEnum(BidStatus), default=BidStatus.SUBMITTED
    )
    invalid_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AuctionResult(Base):
    __tablename__ = "auction_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("auction_rounds.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    winner_manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"))
    price: Mapped[int] = mapped_column(Integer)  # unit: million EUR
    __table_args__ = (UniqueConstraint("round_id", "player_id"),)
