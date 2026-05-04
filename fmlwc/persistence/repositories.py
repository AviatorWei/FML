"""Repository layer.

Domain services depend on these Protocols, never on Session directly.
Protocols are defined without importing concrete ORM rows so that
pure-algorithmic code can import them without pulling in SQLAlchemy.

The default SQLAlchemy implementations (`Sql*Repo`) DO need SQLAlchemy
and are conditionally imported.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional, Protocol

from ..core.enums import BidStatus, EligibilityRestriction, Position

if TYPE_CHECKING:  # avoid eager SQLAlchemy import
    from sqlalchemy.orm import Session
    from . import models as m
    Manager = m.Manager
    Player = m.Player
    RosterEntry = m.RosterEntry
    Bid = m.Bid
    EligibilityRecord = m.EligibilityRecord
    TransferWindow = m.TransferWindow
else:
    Manager = Any
    Player = Any
    RosterEntry = Any
    Bid = Any
    EligibilityRecord = Any
    TransferWindow = Any


# === Protocols =============================================================

class ManagerRepo(Protocol):
    def get(self, manager_id: int) -> "Manager": ...
    def list_active(self) -> list["Manager"]: ...
    def adjust_balance(self, manager_id: int, delta: int, *, reason: str) -> None: ...
    def list_roster(self, manager_id: int) -> list["RosterEntry"]: ...
    def position_count(self, manager_id: int, position: Position) -> int: ...


class PlayerRepo(Protocol):
    def get(self, player_id: int) -> "Player": ...
    def is_free_agent(self, player_id: int, at: datetime) -> bool: ...


class BidRepo(Protocol):
    def for_round(self, round_id: int) -> list["Bid"]: ...
    def for_submission(self, submission_id: int) -> list["Bid"]: ...
    def update_status(self, bid_id: int, status: BidStatus, reason: str | None = None) -> None: ...


class TransferRepo(Protocol):
    def current_window(self, at: datetime) -> Optional["TransferWindow"]: ...
    def previous_window(self, at: datetime) -> Optional["TransferWindow"]: ...


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


# === SQLAlchemy implementations (skeleton) =================================
# These require SQLAlchemy; safe to keep at module top-level only because
# the import is inside a function-scope lazy guard.

def _sa_session_class():
    from sqlalchemy.orm import Session
    return Session


class SqlManagerRepo:
    def __init__(self, session) -> None:
        self.s = session

    def get(self, manager_id: int):
        raise NotImplementedError("TODO")

    def list_active(self):
        raise NotImplementedError("TODO")

    def adjust_balance(self, manager_id: int, delta: int, *, reason: str) -> None:
        raise NotImplementedError("TODO: SELECT ... FOR UPDATE then UPDATE")

    def list_roster(self, manager_id: int):
        raise NotImplementedError("TODO")

    def position_count(self, manager_id: int, position: Position) -> int:
        raise NotImplementedError("TODO")


class SqlPlayerRepo:
    def __init__(self, session) -> None:
        self.s = session

    def get(self, player_id: int):
        raise NotImplementedError("TODO")

    def is_free_agent(self, player_id: int, at: datetime) -> bool:
        raise NotImplementedError("TODO")


class SqlBidRepo:
    def __init__(self, session) -> None:
        self.s = session

    def for_round(self, round_id: int):
        raise NotImplementedError("TODO")

    def for_submission(self, submission_id: int):
        raise NotImplementedError("TODO")

    def update_status(self, bid_id: int, status: BidStatus, reason: str | None = None) -> None:
        raise NotImplementedError("TODO")


class SqlTransferRepo:
    def __init__(self, session) -> None:
        self.s = session

    def current_window(self, at: datetime):
        raise NotImplementedError("TODO")

    def previous_window(self, at: datetime):
        raise NotImplementedError("TODO")


class SqlEligibilityRepo:
    def __init__(self, session) -> None:
        self.s = session

    def list_for_player(self, player_id: int, at: datetime):
        raise NotImplementedError("TODO")

    def add(
        self,
        manager_id: int,
        player_id: int,
        restriction: EligibilityRestriction,
        valid_until: datetime | None,
        reason: str | None = None,
    ) -> None:
        raise NotImplementedError("TODO")
