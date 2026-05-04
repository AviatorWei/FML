"""In-memory fake repositories implementing the Protocols in
`fmlwc.persistence.repositories`.

Used by unit tests to avoid pulling in SQLAlchemy. Each fake matches the
shape of the protocol it replaces; missing methods raise NotImplementedError
so we catch accidental usage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from fmlwc.core.enums import (
    AcquisitionVia,
    BidStatus,
    EligibilityRestriction,
    Position,
)


# --- mini value objects standing in for ORM rows ----------------------------

@dataclass
class FakeManager:
    id: int
    display_name: str
    balance: int
    group_letter: str | None = None
    total_points: int = 0


@dataclass
class FakePlayer:
    id: int
    name: str
    position: Position
    real_team: str = "TEAM"
    market_value: int = 0
    jersey_no: int | None = None


@dataclass
class FakeRosterEntry:
    manager_id: int
    player_id: int
    acquired_at: datetime
    acquired_via: AcquisitionVia
    acquired_price: int
    released_at: datetime | None = None


@dataclass
class FakeEligibilityRecord:
    manager_id: int
    player_id: int
    restriction_type: EligibilityRestriction
    valid_until: datetime | None = None
    reason: str | None = None


@dataclass
class FakeBid:
    id: int
    submission_id: int
    player_id: int
    amount: int
    rank_in_position: int
    status: BidStatus = BidStatus.SUBMITTED
    invalid_reason: str | None = None


@dataclass
class FakeTransferWindow:
    id: int
    opens_at: datetime
    closes_at: datetime


# --- fake repos -------------------------------------------------------------

class FakeManagerRepo:
    def __init__(self) -> None:
        self.managers: dict[int, FakeManager] = {}
        self.rosters: dict[int, list[FakeRosterEntry]] = {}

    # protocol surface
    def get(self, manager_id: int) -> FakeManager:
        return self.managers[manager_id]

    def list_active(self) -> list[FakeManager]:
        return list(self.managers.values())

    def adjust_balance(self, manager_id: int, delta: int, *, reason: str) -> None:
        m = self.managers[manager_id]
        if m.balance + delta < 0:
            raise ValueError(f"balance would go negative for manager {manager_id}")
        m.balance += delta

    def list_roster(self, manager_id: int) -> list[FakeRosterEntry]:
        return [e for e in self.rosters.get(manager_id, []) if e.released_at is None]

    def position_count(self, manager_id: int, position: Position) -> int:
        return sum(1 for e in self.list_roster(manager_id)
                   if self._player_pos(e.player_id) is position)

    # test helpers (not in protocol)
    _player_pos_lookup: dict[int, Position] = {}

    def attach_player_repo(self, players: "FakePlayerRepo") -> None:
        self._players = players

    def _player_pos(self, player_id: int) -> Position:
        return self._players.get(player_id).position

    def add_to_roster(
        self,
        manager_id: int,
        player_id: int,
        *,
        acquired_at: datetime,
        via: AcquisitionVia = AcquisitionVia.AUCTION,
        price: int = 0,
    ) -> None:
        self.rosters.setdefault(manager_id, []).append(
            FakeRosterEntry(manager_id, player_id, acquired_at, via, price)
        )


class FakePlayerRepo:
    def __init__(self) -> None:
        self.players: dict[int, FakePlayer] = {}

    def add(self, p: FakePlayer) -> FakePlayer:
        self.players[p.id] = p
        return p

    def get(self, player_id: int) -> FakePlayer:
        return self.players[player_id]

    def is_free_agent(self, player_id: int, at: datetime) -> bool:
        # Caller may patch this for specific tests; default True.
        return True


class FakeEligibilityRepo:
    def __init__(self) -> None:
        self.records: list[FakeEligibilityRecord] = []

    def list_for_player(self, player_id: int, at: datetime) -> list[FakeEligibilityRecord]:
        out: list[FakeEligibilityRecord] = []
        for r in self.records:
            if r.player_id != player_id:
                continue
            if r.valid_until is not None and r.valid_until <= at:
                continue
            out.append(r)
        return out

    def add(
        self,
        manager_id: int,
        player_id: int,
        restriction: EligibilityRestriction,
        valid_until: datetime | None,
        reason: str | None = None,
    ) -> None:
        self.records.append(
            FakeEligibilityRecord(manager_id, player_id, restriction, valid_until, reason)
        )


class FakeBidRepo:
    def __init__(self) -> None:
        self.by_id: dict[int, FakeBid] = {}
        self.by_submission: dict[int, list[int]] = {}
        self.by_round: dict[int, list[int]] = {}

    def add(self, bid: FakeBid, *, round_id: int) -> None:
        self.by_id[bid.id] = bid
        self.by_submission.setdefault(bid.submission_id, []).append(bid.id)
        self.by_round.setdefault(round_id, []).append(bid.id)

    def for_round(self, round_id: int) -> list[FakeBid]:
        return [self.by_id[i] for i in self.by_round.get(round_id, [])]

    def for_submission(self, submission_id: int) -> list[FakeBid]:
        return [self.by_id[i] for i in self.by_submission.get(submission_id, [])]

    def update_status(
        self, bid_id: int, status: BidStatus, reason: str | None = None
    ) -> None:
        b = self.by_id[bid_id]
        b.status = status
        b.invalid_reason = reason


class FakeTransferRepo:
    def __init__(self) -> None:
        self.windows: list[FakeTransferWindow] = []

    def current_window(self, at: datetime) -> Optional[FakeTransferWindow]:
        for w in self.windows:
            if w.opens_at <= at < w.closes_at:
                return w
        return None

    def previous_window(self, at: datetime) -> Optional[FakeTransferWindow]:
        prev: Optional[FakeTransferWindow] = None
        for w in self.windows:
            if w.closes_at <= at:
                if prev is None or w.closes_at > prev.closes_at:
                    prev = w
        return prev


# --- helper builders --------------------------------------------------------

def make_repos(
    managers: list[FakeManager] | None = None,
    players: list[FakePlayer] | None = None,
) -> tuple[FakeManagerRepo, FakePlayerRepo, FakeEligibilityRepo]:
    mgr = FakeManagerRepo()
    plr = FakePlayerRepo()
    elig = FakeEligibilityRepo()
    for m in managers or []:
        mgr.managers[m.id] = m
    for p in players or []:
        plr.add(p)
    mgr.attach_player_repo(plr)
    return mgr, plr, elig
