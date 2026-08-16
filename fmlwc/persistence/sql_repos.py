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
    GameweekPhase,
    GameweekStatus,
    Position,
    RealEventType,
)
from .models import (
    AuctionResult,
    AuctionRound,
    Bid,
    EligibilityRecord,
    Fixture,
    FreeSign,
    Gameweek,
    Lineup,
    Manager,
    ManagerPlayerAthletics,
    ManagerStats,
    MatchEvent,
    Player,
    PlayerAthletics,
    RosterEntry,
    Submission,
    TransferWindow,
)

_STAT_FIELDS = (
    "goals", "own_goals", "saved_penalties", "missed_penalties",
    "assists", "yellows", "second_yellow_reds", "reds",
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


class CupWalletManagerRepo(SqlManagerRepo):
    """ManagerRepo view that reads/writes the CUP wallet (FMC 第十三条).

    Use this when running FMC-scoped services (e.g. cup auction rounds) so
    balance checks and debits hit ``Manager.cup_balance`` instead of the
    league wallet. ``get``/``list_active`` return lightweight proxies whose
    ``.balance`` is the cup balance; all roster methods are inherited.
    """

    class _Proxy:
        __slots__ = ("_row",)

        def __init__(self, row: Manager) -> None:
            self._row = row

        def __getattr__(self, name):
            if name == "balance":
                return self._row.cup_balance
            return getattr(self._row, name)

    def get(self, manager_id: int):
        row = super().get(manager_id)
        return self._Proxy(row) if row is not None else None

    def list_active(self):
        return [self._Proxy(m) for m in super().list_active()]

    def adjust_balance(self, manager_id: int, delta: int, *, reason: str) -> None:  # noqa: ARG002
        mgr = self.s.get(Manager, manager_id)
        if mgr is None:
            raise KeyError(f"Manager {manager_id} not found")
        new_balance = mgr.cup_balance + delta
        if new_balance < 0:
            raise ValueError(
                f"Cup balance would go negative for manager {manager_id}: "
                f"{mgr.cup_balance} + {delta} = {new_balance}"
            )
        mgr.cup_balance = new_balance
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


# ---------------------------------------------------------------------------
# Match — gameweek, fixtures, events
# ---------------------------------------------------------------------------

class SqlGameweekRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def get(self, gameweek_id: int) -> Gameweek:
        return self.s.get(Gameweek, gameweek_id)  # type: ignore[return-value]

    def create(self, index: int, phase: GameweekPhase, lineup_deadline: datetime) -> int:
        gw = Gameweek(
            index=index,
            phase=phase,
            lineup_deadline=_dt(lineup_deadline),
            status=GameweekStatus.PENDING,
        )
        self.s.add(gw)
        self.s.flush()
        return gw.id

    def set_status(self, gameweek_id: int, status: GameweekStatus) -> None:
        gw = self.s.get(Gameweek, gameweek_id)
        if gw is None:
            raise KeyError(f"Gameweek {gameweek_id} not found")
        gw.status = status
        self.s.flush()

    def fixtures_for(self, gameweek_id: int) -> list[Fixture]:
        stmt = select(Fixture).where(Fixture.gameweek_id == gameweek_id)
        return list(self.s.scalars(stmt))


class SqlFixtureRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def get(self, fixture_id: int) -> Fixture:
        return self.s.get(Fixture, fixture_id)  # type: ignore[return-value]

    def create(
        self,
        gameweek_id: int,
        home_manager_id: int,
        away_manager_id: int,
        *,
        group_letter: str | None = None,
        bracket_slot: str | None = None,
    ) -> int:
        f = Fixture(
            gameweek_id=gameweek_id,
            home_manager_id=home_manager_id,
            away_manager_id=away_manager_id,
            group_letter=group_letter,
            bracket_slot=bracket_slot,
        )
        self.s.add(f)
        self.s.flush()
        return f.id

    def save_lineup(
        self,
        fixture_id: int,
        manager_id: int,
        starters: list[dict],
        posted_at: datetime,
        pk_order: list[int] | None = None,
    ) -> int:
        stmt = (
            select(Lineup)
            .where(Lineup.fixture_id == fixture_id)
            .where(Lineup.manager_id == manager_id)
        )
        existing = self.s.scalars(stmt).first()
        if existing is not None:
            existing.starters = starters
            existing.pk_order = pk_order
            existing.posted_at = _dt(posted_at)
            self.s.flush()
            return existing.id
        lu = Lineup(
            fixture_id=fixture_id,
            manager_id=manager_id,
            starters=starters,
            pk_order=pk_order,
            posted_at=_dt(posted_at),
        )
        self.s.add(lu)
        self.s.flush()
        return lu.id

    def lineup_for(self, fixture_id: int, manager_id: int) -> Optional[Lineup]:
        stmt = (
            select(Lineup)
            .where(Lineup.fixture_id == fixture_id)
            .where(Lineup.manager_id == manager_id)
        )
        return self.s.scalars(stmt).first()

    def player_manager_map(self, gameweek_id: int) -> dict[int, int]:
        """Return {player_id: manager_id} for every starter in the gameweek.

        Reads all Lineup rows whose fixture belongs to the gameweek and
        unpacks the starters JSON.  Used by RoundService to attribute events
        to the manager who fielded each player at match time.
        """
        lineups = list(self.s.scalars(
            select(Lineup)
            .join(Fixture, Lineup.fixture_id == Fixture.id)
            .where(Fixture.gameweek_id == gameweek_id)
        ))
        result: dict[int, int] = {}
        for lineup in lineups:
            for starter in (lineup.starters or []):
                pid = starter["player_id"] if isinstance(starter, dict) else starter.player_id
                result[pid] = lineup.manager_id
        return result


class SqlMatchEventRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def add(
        self,
        gameweek_id: int,
        player_id: int,
        event_type: RealEventType,
        *,
        minute: int | None = None,
        is_extra_time: bool = False,
        is_shootout: bool = False,
    ) -> int:
        ev = MatchEvent(
            gameweek_id=gameweek_id,
            player_id=player_id,
            event_type=event_type,
            minute=minute,
            is_extra_time=is_extra_time,
            is_shootout=is_shootout,
        )
        self.s.add(ev)
        self.s.flush()
        return ev.id

    def remove(self, event_id: int) -> None:
        self.s.execute(delete(MatchEvent).where(MatchEvent.id == event_id))
        self.s.flush()

    def for_players_in_gameweek(
        self, gameweek_id: int, player_ids: set[int]
    ) -> list[MatchEvent]:
        stmt = (
            select(MatchEvent)
            .where(MatchEvent.gameweek_id == gameweek_id)
            .where(MatchEvent.player_id.in_(player_ids))
        )
        return list(self.s.scalars(stmt))


# ---------------------------------------------------------------------------
# Athletics — player, manager aggregate, per-player-per-manager breakdown
# ---------------------------------------------------------------------------

class SqlAthleticsRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def increment_player(self, player_id: int, delta: dict[str, int]) -> None:
        row = self.s.get(PlayerAthletics, player_id)
        if row is None:
            row = PlayerAthletics(player_id=player_id, **{f: 0 for f in _STAT_FIELDS})
            self.s.add(row)
        for field, amount in delta.items():
            setattr(row, field, getattr(row, field) + amount)
        self.s.flush()

    def increment_manager(self, manager_id: int, delta: dict[str, int]) -> None:
        row = self.s.get(ManagerStats, manager_id)
        if row is None:
            row = ManagerStats(manager_id=manager_id, **{f: 0 for f in _STAT_FIELDS})
            self.s.add(row)
        for field, amount in delta.items():
            setattr(row, field, getattr(row, field) + amount)
        self.s.flush()

    def increment_manager_player(
        self, manager_id: int, player_id: int, delta: dict[str, int]
    ) -> None:
        row = self.s.get(ManagerPlayerAthletics, (manager_id, player_id))
        if row is None:
            row = ManagerPlayerAthletics(
                manager_id=manager_id, player_id=player_id,
                **{f: 0 for f in _STAT_FIELDS},
            )
            self.s.add(row)
        for field, amount in delta.items():
            setattr(row, field, getattr(row, field) + amount)
        self.s.flush()


# ---------------------------------------------------------------------------
# Transfer — free signs
# ---------------------------------------------------------------------------

class SqlFreeSignRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def create(
        self,
        window_id: int,
        manager_id: int,
        player_id: int,
        fee: int,
        posted_at: datetime,
    ) -> int:
        row = FreeSign(
            window_id=window_id,
            manager_id=manager_id,
            player_id=player_id,
            fee=fee,
            posted_at=_dt(posted_at),
            revoked=False,
            effective=False,
        )
        self.s.add(row)
        self.s.flush()
        return row.id

    def get(self, free_sign_id: int) -> FreeSign:
        row = self.s.get(FreeSign, free_sign_id)
        if row is None:
            raise KeyError(f"FreeSign {free_sign_id} not found")
        return row

    def pending_in_window(self, window_id: int) -> list[FreeSign]:
        stmt = (
            select(FreeSign)
            .where(FreeSign.window_id == window_id)
            .where(FreeSign.revoked.is_(False))
            .where(FreeSign.effective.is_(False))
        )
        return list(self.s.scalars(stmt))

    def for_manager_in_window(
        self, manager_id: int, window_id: int
    ) -> list[FreeSign]:
        stmt = (
            select(FreeSign)
            .where(FreeSign.manager_id == manager_id)
            .where(FreeSign.window_id == window_id)
        )
        return list(self.s.scalars(stmt))

    def mark_revoked(self, free_sign_id: int) -> None:
        self.s.execute(
            update(FreeSign)
            .where(FreeSign.id == free_sign_id)
            .values(revoked=True)
        )
        self.s.flush()

    def mark_effective(self, free_sign_id: int) -> None:
        self.s.execute(
            update(FreeSign)
            .where(FreeSign.id == free_sign_id)
            .values(effective=True)
        )
        self.s.flush()


# ---------------------------------------------------------------------------
# Transfer — releases, trades, dismissals
# ---------------------------------------------------------------------------

class SqlReleaseRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def create(self, manager_id: int, player_id: int, posted_at: datetime) -> int:
        from .models.transfer import Release
        row = Release(manager_id=manager_id, player_id=player_id,
                      posted_at=_dt(posted_at), revoked=False, effective=False)
        self.s.add(row)
        self.s.flush()
        return row.id

    def get(self, release_id: int):
        from .models.transfer import Release
        return self.s.get(Release, release_id)

    def pending(self):
        from .models.transfer import Release
        stmt = (select(Release)
                .where(Release.revoked.is_(False))
                .where(Release.effective.is_(False)))
        return list(self.s.scalars(stmt))

    def pending_for_manager(self, manager_id: int):
        from .models.transfer import Release
        stmt = (select(Release)
                .where(Release.manager_id == manager_id)
                .where(Release.revoked.is_(False))
                .where(Release.effective.is_(False)))
        return list(self.s.scalars(stmt))

    def mark_revoked(self, release_id: int) -> None:
        from .models.transfer import Release
        self.s.execute(update(Release).where(Release.id == release_id)
                       .values(revoked=True))
        self.s.flush()

    def mark_effective(self, release_id: int) -> None:
        from .models.transfer import Release
        self.s.execute(update(Release).where(Release.id == release_id)
                       .values(effective=True))
        self.s.flush()


class SqlTradeRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def create(self, window_id, initiator_id, counterparty_id, legs, proposed_at) -> int:
        from ..core.enums import TradeSide, TradeStatus
        from .models.transfer import Trade, TradeLeg
        trade = Trade(window_id=window_id, initiator_id=initiator_id,
                      counterparty_id=counterparty_id,
                      status=TradeStatus.PROPOSED, proposed_at=_dt(proposed_at))
        self.s.add(trade)
        self.s.flush()
        for leg in legs:
            side = leg.side if isinstance(leg.side, TradeSide) else TradeSide(leg.side)
            self.s.add(TradeLeg(trade_id=trade.id, side=side,
                                player_id=leg.player_id,
                                cash_amount=leg.cash_amount))
        self.s.flush()
        return trade.id

    def get(self, trade_id: int):
        from .models.transfer import Trade
        return self.s.get(Trade, trade_id)

    def legs_for(self, trade_id: int):
        from .models.transfer import TradeLeg
        return list(self.s.scalars(
            select(TradeLeg).where(TradeLeg.trade_id == trade_id)))

    def set_status(self, trade_id: int, status, resolved_at: datetime | None = None) -> None:
        from .models.transfer import Trade
        trade = self.s.get(Trade, trade_id)
        if trade is None:
            raise KeyError(f"Trade {trade_id} not found")
        trade.status = status
        if resolved_at is not None:
            trade.resolved_at = _dt(resolved_at)
        self.s.flush()

    def proposed_in_window(self, window_id: int):
        from ..core.enums import TradeStatus
        from .models.transfer import Trade
        stmt = (select(Trade)
                .where(Trade.window_id == window_id)
                .where(Trade.status == TradeStatus.PROPOSED))
        return list(self.s.scalars(stmt))

    def distinct_owners(self, player_id: int) -> set[int]:
        stmt = (select(RosterEntry.manager_id)
                .where(RosterEntry.player_id == player_id)
                .distinct())
        return set(self.s.scalars(stmt))

    def accepted_trades_in_window(self, player_id: int, window_id: int) -> int:
        from ..core.enums import TradeStatus
        from .models.transfer import Trade, TradeLeg
        stmt = (select(Trade.id)
                .join(TradeLeg, TradeLeg.trade_id == Trade.id)
                .where(Trade.window_id == window_id)
                .where(Trade.status == TradeStatus.ACCEPTED)
                .where(TradeLeg.player_id == player_id)
                .distinct())
        return len(list(self.s.scalars(stmt)))


class SqlDismissalRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def create(self, manager_id: int, player_id: int, dismissed_at: datetime,
               reason: str | None = None) -> int:
        from .models.transfer import Dismissal
        row = Dismissal(manager_id=manager_id, player_id=player_id,
                        dismissed_at=_dt(dismissed_at), reason=reason)
        self.s.add(row)
        self.s.flush()
        return row.id

    def for_manager(self, manager_id: int):
        from .models.transfer import Dismissal
        return list(self.s.scalars(
            select(Dismissal).where(Dismissal.manager_id == manager_id)))

    def for_player(self, player_id: int):
        from .models.transfer import Dismissal
        return list(self.s.scalars(
            select(Dismissal).where(Dismissal.player_id == player_id)))


# ---------------------------------------------------------------------------
# Knockout — snapshots, picks; injuries
# ---------------------------------------------------------------------------

class SqlSnapshotRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def create(self, manager_id: int, taken_at: datetime, reason: str,
               entries: list[dict]) -> int:
        from .models.knockout import RosterSnapshot
        row = RosterSnapshot(manager_id=manager_id, taken_at=_dt(taken_at),
                             reason=reason, entries=entries)
        self.s.add(row)
        self.s.flush()
        return row.id

    def for_reason(self, reason: str):
        from .models.knockout import RosterSnapshot
        return list(self.s.scalars(
            select(RosterSnapshot).where(RosterSnapshot.reason == reason)))


class SqlPickRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def create(self, knockout_fixture_id: int, picker_manager_id: int,
               picked_player_id: int, picked_at: datetime) -> int:
        from .models.knockout import Pick
        row = Pick(knockout_fixture_id=knockout_fixture_id,
                   picker_manager_id=picker_manager_id,
                   picked_player_id=picked_player_id,
                   picked_at=_dt(picked_at))
        self.s.add(row)
        self.s.flush()
        return row.id

    def for_fixture(self, knockout_fixture_id: int):
        from .models.knockout import Pick
        return list(self.s.scalars(
            select(Pick).where(Pick.knockout_fixture_id == knockout_fixture_id)))


class SqlInjuryRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def create(self, *, real_player_id: int, removed_at: datetime,
               refund_amount: int, free_sign_grant: bool,
               granted_to_manager_id: int | None) -> int:
        from .models.injury import InjuryAdjustment
        row = InjuryAdjustment(real_player_id=real_player_id,
                               removed_at=_dt(removed_at),
                               refund_amount=refund_amount,
                               free_sign_grant=free_sign_grant,
                               granted_to_manager_id=granted_to_manager_id)
        self.s.add(row)
        self.s.flush()
        return row.id
