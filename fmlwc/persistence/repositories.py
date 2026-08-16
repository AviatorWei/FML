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
    GameweekPhase,
    GameweekStatus,
    Position,
    RealEventType,
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
    Dismissal = m.Dismissal
    Gameweek = m.Gameweek
    Fixture = m.Fixture
    Lineup = m.Lineup
    MatchEvent = m.MatchEvent
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
    Dismissal = Any
    Gameweek = Any
    Fixture = Any
    Lineup = Any
    MatchEvent = Any


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

    def clear_for_submission(self, submission_id: int) -> None: ...
    """Delete all bids for this submission (used on re-submit)."""

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


class FreeSignRepo(Protocol):
    def create(
        self,
        window_id: int,
        manager_id: int,
        player_id: int,
        fee: int,
        posted_at: datetime,
    ) -> int: ...
    """Insert a new FreeSign row; returns the new free_sign_id."""

    def get(self, free_sign_id: int) -> "FreeSign": ...
    def pending_in_window(self, window_id: int) -> list["FreeSign"]: ...
    """All non-revoked, non-effective rows in this window (for commit_due)."""

    def for_manager_in_window(
        self, manager_id: int, window_id: int
    ) -> list["FreeSign"]: ...
    """All rows (including revoked) for this manager in this window (for cooldown check)."""

    def mark_revoked(self, free_sign_id: int) -> None: ...
    def mark_effective(self, free_sign_id: int) -> None: ...


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


class DismissalRepo(Protocol):
    def create(
        self,
        manager_id: int,
        player_id: int,
        dismissed_at: datetime,
        reason: str | None = None,
    ) -> int: ...
    """Persist a Dismissal audit record; returns its id."""

    def for_manager(self, manager_id: int) -> list["Dismissal"]: ...
    def for_player(self, player_id: int) -> list["Dismissal"]: ...


class ReleaseRepo(Protocol):
    def create(self, manager_id: int, player_id: int, posted_at: datetime) -> int: ...
    """Insert a pending Release row; returns its id."""

    def get(self, release_id: int) -> Any: ...
    def pending(self) -> list[Any]: ...
    """All non-revoked, non-effective releases (for commit_due)."""

    def pending_for_manager(self, manager_id: int) -> list[Any]: ...
    def mark_revoked(self, release_id: int) -> None: ...
    def mark_effective(self, release_id: int) -> None: ...


class TradeRepo(Protocol):
    def create(
        self,
        window_id: int | None,
        initiator_id: int,
        counterparty_id: int,
        legs: Any,           # sequence of objects with .side/.player_id/.cash_amount
        proposed_at: datetime,
    ) -> int: ...
    """Insert Trade (PROPOSED) + TradeLeg rows; returns the trade id."""

    def get(self, trade_id: int) -> Any: ...
    def legs_for(self, trade_id: int) -> list[Any]: ...
    def set_status(self, trade_id: int, status: Any,
                   resolved_at: datetime | None = None) -> None: ...
    def proposed_in_window(self, window_id: int) -> list[Any]: ...
    def distinct_owners(self, player_id: int) -> set[int]: ...
    """Every manager id that has ever held the player (rule 第五十条)."""

    def accepted_trades_in_window(self, player_id: int, window_id: int) -> int: ...
    """How many ACCEPTED trades in this window moved the player (第五十条)."""


class SnapshotRepo(Protocol):
    def create(self, manager_id: int, taken_at: datetime, reason: str,
               entries: list[dict]) -> int: ...
    """Persist a RosterSnapshot; returns its id."""

    def for_reason(self, reason: str) -> list[Any]: ...


class PickRepo(Protocol):
    def create(self, knockout_fixture_id: int, picker_manager_id: int,
               picked_player_id: int, picked_at: datetime) -> int: ...
    def for_fixture(self, knockout_fixture_id: int) -> list[Any]: ...


class InjuryRepo(Protocol):
    def create(self, *, real_player_id: int, removed_at: datetime,
               refund_amount: int, free_sign_grant: bool,
               granted_to_manager_id: int | None) -> int: ...
    """Persist an InjuryAdjustment audit record; returns its id."""


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
    def clear_for_submission(self, submission_id): raise NotImplementedError
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


class SqlFreeSignRepo:
    def __init__(self, session) -> None:
        self.s = session

    def create(self, window_id, manager_id, player_id, fee, posted_at): raise NotImplementedError
    def get(self, free_sign_id): raise NotImplementedError
    def pending_in_window(self, window_id): raise NotImplementedError
    def for_manager_in_window(self, manager_id, window_id): raise NotImplementedError
    def mark_revoked(self, free_sign_id): raise NotImplementedError
    def mark_effective(self, free_sign_id): raise NotImplementedError


class SqlEligibilityRepo:
    def __init__(self, session) -> None:
        self.s = session

    def list_for_player(self, player_id, at): raise NotImplementedError
    def add(self, manager_id, player_id, restriction, valid_until, reason=None): raise NotImplementedError


class SqlDismissalRepo:
    def __init__(self, session) -> None:
        self.s = session

    def create(self, manager_id, player_id, dismissed_at, reason=None): raise NotImplementedError
    def for_manager(self, manager_id): raise NotImplementedError
    def for_player(self, player_id): raise NotImplementedError


class GameweekRepo(Protocol):
    def get(self, gameweek_id: int) -> "Gameweek": ...
    def create(self, index: int, phase: GameweekPhase, lineup_deadline: datetime) -> int: ...
    """Insert a new PENDING gameweek; returns its id."""
    def set_status(self, gameweek_id: int, status: GameweekStatus) -> None: ...
    def fixtures_for(self, gameweek_id: int) -> list["Fixture"]: ...


class FixtureRepo(Protocol):
    def get(self, fixture_id: int) -> "Fixture": ...
    def create(
        self,
        gameweek_id: int,
        home_manager_id: int,
        away_manager_id: int,
        *,
        group_letter: str | None = None,
        bracket_slot: str | None = None,
    ) -> int: ...
    """Insert one fixture; returns its id."""
    def save_lineup(
        self,
        fixture_id: int,
        manager_id: int,
        starters: list[dict],
        posted_at: datetime,
        pk_order: list[int] | None = None,
    ) -> int: ...
    """Upsert the lineup for (fixture_id, manager_id); returns lineup id.

    starters is a list of {"player_id": int, "slot_position": str} dicts,
    produced by serialising ValidatedLineup.accepted.
    Re-submitting before the deadline replaces the previous lineup.
    """
    def lineup_for(self, fixture_id: int, manager_id: int) -> Optional["Lineup"]: ...
    def player_manager_map(self, gameweek_id: int) -> dict[int, int]: ...
    """Returns {player_id: manager_id} for every starter across all fixtures in the gameweek."""


class MatchEventRepo(Protocol):
    def add(
        self,
        gameweek_id: int,
        player_id: int,
        event_type: RealEventType,
        *,
        minute: int | None = None,
        is_extra_time: bool = False,
        is_shootout: bool = False,
    ) -> int: ...
    """Persist one event; returns the new event_id."""

    def remove(self, event_id: int) -> None: ...
    """Delete one event (only valid while gameweek is LIVE)."""

    def for_players_in_gameweek(
        self, gameweek_id: int, player_ids: set[int]
    ) -> list["MatchEvent"]: ...
    """Return all events for the given players in this gameweek."""


class AthleticsRepo(Protocol):
    def increment_player(self, player_id: int, delta: dict[str, int]) -> None: ...
    """Upsert a PlayerAthletics row, adding delta values to existing counts."""

    def increment_manager(self, manager_id: int, delta: dict[str, int]) -> None: ...
    """Upsert a ManagerStats row, adding delta values to existing counts."""

    def increment_manager_player(
        self, manager_id: int, player_id: int, delta: dict[str, int]
    ) -> None: ...
    """Upsert a ManagerPlayerAthletics row for this (manager, player) pair."""


# ---------------------------------------------------------------------------
# SQL skeleton stubs
# ---------------------------------------------------------------------------

class SqlGameweekRepo:
    def __init__(self, session) -> None:
        self.s = session

    def get(self, gameweek_id): raise NotImplementedError
    def create(self, index, phase, lineup_deadline): raise NotImplementedError
    def set_status(self, gameweek_id, status): raise NotImplementedError
    def fixtures_for(self, gameweek_id): raise NotImplementedError


class SqlFixtureRepo:
    def __init__(self, session) -> None:
        self.s = session

    def get(self, fixture_id): raise NotImplementedError
    def create(self, gameweek_id, home_manager_id, away_manager_id, *,
               group_letter=None, bracket_slot=None): raise NotImplementedError
    def save_lineup(self, fixture_id, manager_id, starters, posted_at,
                    pk_order=None): raise NotImplementedError
    def lineup_for(self, fixture_id, manager_id): raise NotImplementedError
    def player_manager_map(self, gameweek_id): raise NotImplementedError


class SqlMatchEventRepo:
    def __init__(self, session) -> None:
        self.s = session

    def add(self, gameweek_id, player_id, event_type, *, minute=None,
            is_extra_time=False, is_shootout=False): raise NotImplementedError
    def remove(self, event_id): raise NotImplementedError
    def for_players_in_gameweek(self, gameweek_id, player_ids): raise NotImplementedError


class SqlAthleticsRepo:
    def __init__(self, session) -> None:
        self.s = session

    def increment_player(self, player_id, delta): raise NotImplementedError
    def increment_manager(self, manager_id, delta): raise NotImplementedError
    def increment_manager_player(self, manager_id, player_id, delta): raise NotImplementedError
