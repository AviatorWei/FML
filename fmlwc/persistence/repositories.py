"""Repository layer.

Domain services depend on these Protocols, never on Session directly.
Protocols are defined without importing concrete ORM rows so that
pure-algorithmic code can import them without pulling in SQLAlchemy.

The default SQLAlchemy implementations (`Sql*Repo`) are skeleton stubs.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional, Protocol

from ..core.enums import (
    AcquisitionVia,
    AuctionRoundStatus,
    BidStatus,
    EligibilityRestriction,
    Position,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from . import models as m
    Manager = m.Manager
    Player = m.Player
    RosterEntry = m.RosterEntry
    Bid = m.Bid
    Submission = m.Submission
    AuctionRound = m.AuctionRound
    AuctionResult = m.AuctionResult
    EligibilityRecord = m.EligibilityRecord
    TransferWindow = m.TransferWindow
else:
    Manager = Any
    Player = Any
    RosterEntry = Any
    Bid = Any
    Submission = Any
    AuctionRound = Any
    AuctionResult = Any
    EligibilityRecord = Any
    TransferWindow = Any


# ===========================================================================
# Protocols
# ===========================================================================

class ManagerRepo(Protocol):
    def get(self, manager_id: int) -> "Manager": ...
    def list_active(self) -> list["Manager"]: ...
    def adjust_balance(self, manager_id: int, delta: int, *, reason: str) -> None: ...
    def list_roster(self, manager_id: int) -> list["RosterEntry"]: ...
    def position_count(self, manager_id: int, position: Position) -> int: ...
    def add_to_roster(
        self,
        manager_id: int,
        player_id: int,
        *,
        acquired_at: datetime,
        via: AcquisitionVia,
        price: int,
    ) -> None: ...
    def release_from_roster(
        self, manager_id: int, player_id: int, released_at: datetime
    ) -> None: ...


class PlayerRepo(Protocol):
    def get(self, player_id: int) -> "Player": ...
    def is_free_agent(self, player_id: int, at: datetime) -> bool: ...


class BidRepo(Protocol):
    def create(
        self,
        submission_id: int,
        player_id: int,
        amount: int,
        rank_in_position: int,
    ) -> int: ...
    """Insert a new bid row; returns the new bid_id."""

    def for_round(self, round_id: int) -> list["Bid"]: ...
    def for_submission(self, submission_id: int) -> list["Bid"]: ...
    def update_status(
        self, bid_id: int, status: BidStatus, reason: str | None = None
    ) -> None: ...


class SubmissionRepo(Protocol):
    def upsert(
        self,
        round_id: int,
        manager_id: int,
        received_at: datetime,
        source_file: str | None = None,
    ) -> int: ...
    """Create or replace the (round_id, manager_id) submission; returns submission_id."""

    def get(self, submission_id: int) -> "Submission": ...
    def for_round(self, round_id: int) -> list["Submission"]: ...


class AuctionRoundRepo(Protocol):
    def get(self, round_id: int) -> "AuctionRound": ...
    def set_status(self, round_id: int, status: AuctionRoundStatus) -> None: ...


class AuctionResultRepo(Protocol):
    def create(
        self,
        round_id: int,
        player_id: int,
        winner_manager_id: int,
        price: int,
    ) -> None: ...
    def for_round(self, round_id: int) -> list["AuctionResult"]: ...


class TransferRepo(Protocol):
    def current_window(self, at: datetime) -> Optional["TransferWindow"]: ...
    def previous_window(self, at: datetime) -> Optional["TransferWindow"]: ...
    def next_window(self, at: datetime) -> Optional["TransferWindow"]: ...


class EligibilityRepo(Protocol):
    def list_for_player(self, player_id: int, at: datetime) -> list["EligibilityRecord"]: ...
    def add(
        self,
        manager_id: int,
        player_id: int,
        restriction: EligibilityRestriction,
        valid_until: datetime | None,
        reason: str | None = None,
    ) -> None: ...


# ===========================================================================
# SQLAlchemy skeleton implementations (not yet implemented)
# ===========================================================================

class SqlManagerRepo:
    def __init__(self, session) -> None:
        self.s = session

    def get(self, manager_id: int): raise NotImplementedError
    def list_active(self): raise NotImplementedError
    def adjust_balance(self, manager_id, delta, *, reason): raise NotImplementedError
    def list_roster(self, manager_id): raise NotImplementedError
    def position_count(self, manager_id, position): raise NotImplementedError
    def add_to_roster(self, manager_id, player_id, *, acquired_at, via, price): raise NotImplementedError
    def release_from_roster(self, manager_id, player_id, released_at): raise NotImplementedError


class SqlPlayerRepo:
    def __init__(self, session) -> None:
        self.s = session

    def get(self, player_id): raise NotImplementedError
    def is_free_agent(self, player_id, at): raise NotImplementedError


class SqlBidRepo:
    def __init__(self, session) -> None:
        self.s = session

    def create(self, submission_id, player_id, amount, rank_in_position): raise NotImplementedError
    def for_round(self, round_id): raise NotImplementedError
    def for_submission(self, submission_id): raise NotImplementedError
    def update_status(self, bid_id, status, reason=None): raise NotImplementedError


class SqlSubmissionRepo:
    def __init__(self, session) -> None:
        self.s = session

    def upsert(self, round_id, manager_id, received_at, source_file=None): raise NotImplementedError
    def get(self, submission_id): raise NotImplementedError
    def for_round(self, round_id): raise NotImplementedError


class SqlAuctionRoundRepo:
    def __init__(self, session) -> None:
        self.s = session

    def get(self, round_id): raise NotImplementedError
    def set_status(self, round_id, status): raise NotImplementedError


class SqlAuctionResultRepo:
    def __init__(self, session) -> None:
        self.s = session

    def create(self, round_id, player_id, winner_manager_id, price): raise NotImplementedError
    def for_round(self, round_id): raise NotImplementedError


class SqlTransferRepo:
    def __init__(self, session) -> None:
        self.s = session

    def current_window(self, at): raise NotImplementedError
    def previous_window(self, at): raise NotImplementedError
    def next_window(self, at): raise NotImplementedError


class SqlEligibilityRepo:
    def __init__(self, session) -> None:
        self.s = session

    def list_for_player(self, player_id, at): raise NotImplementedError
    def add(self, manager_id, player_id, restriction, valid_until, reason=None): raise NotImplementedError
