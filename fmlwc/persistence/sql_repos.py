"""Concrete SQLAlchemy 2.0 repository implementations.

Each class wraps a ``Session`` and satisfies the matching Protocol defined in
``repositories.py``.  Domain services only depend on the Protocols — they
never import this module directly.

Datetime convention
-------------------
SQLite stores datetimes as TEXT without timezone info.  All ``datetime``
objects accepted by these repos may be timezone-aware; they are normalised to
naive UTC before storage via ``_dt()``.  Objects returned from the DB are
already naive UTC.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..core.enums import (
    AcquisitionVia,
    AuctionRoundStatus,
    BidStatus,
    EligibilityRestriction,
    Position,
)
from .models import (
    AuctionResult,
    AuctionRound,
    Bid,
    EligibilityRecord,
    Manager,
    Player,
    RosterEntry,
    Submission,
    TransferWindow,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dt(dt: datetime) -> datetime:
    """Strip timezone info, converting to UTC first if needed."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------

class SqlManagerRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def get(self, manager_id: int) -> Manager:
        return self.s.get(Manager, manager_id)  # type: ignore[return-value]

    def list_active(self) -> list[Manager]:
        return list(self.s.scalars(select(Manager)))

    def adjust_balance(self, manager_id: int, delta: int, *, reason: str) -> None:  # noqa: ARG002
        mgr = self.s.get(Manager, manager_id)
        if mgr is None:
            raise KeyError(f"Manager {manager_id} not found")
        new_balance = mgr.balance + delta
        if new_balance < 0:
            raise ValueError(
                f"Balance would go negative for manager {manager_id}: "
                f"{mgr.balance} + {delta} = {new_balance}"
            )
        mgr.balance = new_balance
        self.s.flush()

    def list_roster(self, manager_id: int) -> list[RosterEntry]:
        stmt = (
            select(RosterEntry)
            .where(RosterEntry.manager_id == manager_id)
            .where(RosterEntry.released_at.is_(None))
        )
        return list(self.s.scalars(stmt))

    def position_count(self, manager_id: int, position: Position) -> int:
        entries = self.list_roster(manager_id)
        count = 0
        for entry in entries:
            player = self.s.get(Player, entry.player_id)
            if player is not None and player.position is position:
                count += 1
        return count

    def add_to_roster(
        self,
        manager_id: int,
        player_id: int,
        *,
        acquired_at: datetime,
        via: AcquisitionVia,
        price: int,
    ) -> None:
        entry = RosterEntry(
            manager_id=manager_id,
            player_id=player_id,
            acquired_at=_dt(acquired_at),
            acquired_via=via,
            acquired_price=price,
        )
        self.s.add(entry)
        self.s.flush()

    def release_from_roster(
        self, manager_id: int, player_id: int, released_at: datetime
    ) -> None:
        stmt = (
            select(RosterEntry)
            .where(RosterEntry.manager_id == manager_id)
            .where(RosterEntry.player_id == player_id)
            .where(RosterEntry.released_at.is_(None))
        )
        entry = self.s.scalars(stmt).first()
        if entry is None:
            raise KeyError(
                f"Player {player_id} not on active roster of manager {manager_id}"
            )
        entry.released_at = _dt(released_at)
        self.s.flush()


class SqlPlayerRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def get(self, player_id: int) -> Player:
        return self.s.get(Player, player_id)  # type: ignore[return-value]

    def is_free_agent(self, player_id: int, at: datetime) -> bool:
        """A player is a free agent if they have no active roster entry."""
        at_naive = _dt(at)
        stmt = (
            select(RosterEntry)
            .where(RosterEntry.player_id == player_id)
            .where(RosterEntry.acquired_at <= at_naive)
            .where(
                (RosterEntry.released_at.is_(None))
                | (RosterEntry.released_at > at_naive)
            )
        )
        return self.s.scalars(stmt).first() is None


# ---------------------------------------------------------------------------
# Auction
# ---------------------------------------------------------------------------

class SqlAuctionRoundRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def get(self, round_id: int) -> AuctionRound:
        return self.s.get(AuctionRound, round_id)  # type: ignore[return-value]

    def set_status(self, round_id: int, status: AuctionRoundStatus) -> None:
        rnd = self.s.get(AuctionRound, round_id)
        if rnd is None:
            raise KeyError(f"AuctionRound {round_id} not found")
        rnd.status = status
        self.s.flush()


class SqlSubmissionRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def upsert(
        self,
        round_id: int,
        manager_id: int,
        received_at: datetime,
        source_file: str | None = None,
    ) -> int:
        stmt = (
            select(Submission)
            .where(Submission.round_id == round_id)
            .where(Submission.manager_id == manager_id)
        )
        existing = self.s.scalars(stmt).first()
        if existing is not None:
            existing.received_at = _dt(received_at)
            existing.source_file = source_file
            self.s.flush()
            return existing.id
        sub = Submission(
            round_id=round_id,
            manager_id=manager_id,
            received_at=_dt(received_at),
            source_file=source_file,
        )
        self.s.add(sub)
        self.s.flush()
        return sub.id

    def get(self, submission_id: int) -> Submission:
        return self.s.get(Submission, submission_id)  # type: ignore[return-value]

    def for_round(self, round_id: int) -> list[Submission]:
        stmt = select(Submission).where(Submission.round_id == round_id)
        return list(self.s.scalars(stmt))


class SqlBidRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def create(
        self,
        submission_id: int,
        player_id: int,
        amount: int,
        rank_in_position: int,
    ) -> int:
        bid = Bid(
            submission_id=submission_id,
            player_id=player_id,
            amount=amount,
            rank_in_position=rank_in_position,
        )
        self.s.add(bid)
        self.s.flush()
        return bid.id

    def clear_for_submission(self, submission_id: int) -> None:
        self.s.execute(
            delete(Bid).where(Bid.submission_id == submission_id)
        )
        self.s.flush()

    def for_round(self, round_id: int) -> list[Bid]:
        sub_ids_stmt = select(Submission.id).where(Submission.round_id == round_id)
        stmt = select(Bid).where(Bid.submission_id.in_(sub_ids_stmt))
        return list(self.s.scalars(stmt))

    def for_submission(self, submission_id: int) -> list[Bid]:
        stmt = select(Bid).where(Bid.submission_id == submission_id)
        return list(self.s.scalars(stmt))

    def update_status(
        self, bid_id: int, status: BidStatus, reason: str | None = None
    ) -> None:
        bid = self.s.get(Bid, bid_id)
        if bid is None:
            raise KeyError(f"Bid {bid_id} not found")
        bid.status = status
        bid.invalid_reason = reason
        self.s.flush()


class SqlAuctionResultRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def create(
        self,
        round_id: int,
        player_id: int,
        winner_manager_id: int,
        price: int,
    ) -> None:
        result = AuctionResult(
            round_id=round_id,
            player_id=player_id,
            winner_manager_id=winner_manager_id,
            price=price,
        )
        self.s.add(result)
        self.s.flush()

    def for_round(self, round_id: int) -> list[AuctionResult]:
        stmt = select(AuctionResult).where(AuctionResult.round_id == round_id)
        return list(self.s.scalars(stmt))


# ---------------------------------------------------------------------------
# Transfer
# ---------------------------------------------------------------------------

class SqlTransferRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def current_window(self, at: datetime) -> Optional[TransferWindow]:
        at_naive = _dt(at)
        stmt = (
            select(TransferWindow)
            .where(TransferWindow.opens_at <= at_naive)
            .where(TransferWindow.closes_at > at_naive)
        )
        return self.s.scalars(stmt).first()

    def previous_window(self, at: datetime) -> Optional[TransferWindow]:
        at_naive = _dt(at)
        stmt = (
            select(TransferWindow)
            .where(TransferWindow.closes_at <= at_naive)
            .order_by(TransferWindow.closes_at.desc())
        )
        return self.s.scalars(stmt).first()

    def next_window(self, at: datetime) -> Optional[TransferWindow]:
        at_naive = _dt(at)
        stmt = (
            select(TransferWindow)
            .where(TransferWindow.opens_at > at_naive)
            .order_by(TransferWindow.opens_at.asc())
        )
        return self.s.scalars(stmt).first()


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------

class SqlEligibilityRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def list_for_player(
        self, player_id: int, at: datetime
    ) -> list[EligibilityRecord]:
        at_naive = _dt(at)
        stmt = (
            select(EligibilityRecord)
            .where(EligibilityRecord.player_id == player_id)
            .where(
                (EligibilityRecord.valid_until.is_(None))
                | (EligibilityRecord.valid_until > at_naive)
            )
        )
        return list(self.s.scalars(stmt))

    def add(
        self,
        manager_id: int,
        player_id: int,
        restriction: EligibilityRestriction,
        valid_until: datetime | None,
        reason: str | None = None,
    ) -> None:
        record = EligibilityRecord(
            manager_id=manager_id,
            player_id=player_id,
            restriction_type=restriction,
            valid_until=_dt(valid_until) if valid_until is not None else None,
            reason=reason,
        )
        self.s.add(record)
        self.s.flush()
