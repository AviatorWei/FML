"""In-memory fake repositories implementing the Protocols in
`fmlwc.persistence.repositories`.

Used by unit tests to avoid pulling in SQLAlchemy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from fmlwc.core.enums import (
    AcquisitionVia,
    AuctionRoundStatus,
    BidStatus,
    EligibilityRestriction,
    Position,
)


# ---------------------------------------------------------------------------
# Value objects (stand-ins for ORM rows)
# ---------------------------------------------------------------------------

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
class FakeSubmission:
    id: int
    round_id: int
    manager_id: int
    received_at: datetime
    source_file: str | None = None


@dataclass
class FakeAuctionRound:
    id: int
    index: int
    opens_at: datetime
    closes_at: datetime
    status: AuctionRoundStatus = AuctionRoundStatus.OPEN


@dataclass
class FakeAuctionResult:
    id: int
    round_id: int
    player_id: int
    winner_manager_id: int
    price: int


@dataclass
class FakeTransferWindow:
    id: int
    opens_at: datetime
    closes_at: datetime
    free_sign_period_seconds: int = 86400  # 24 h default


@dataclass
class FakeFreeSign:
    id: int
    window_id: int
    manager_id: int
    player_id: int
    fee: int
    posted_at: datetime
    revoked: bool = False
    effective: bool = False


# ---------------------------------------------------------------------------
# Fake repos
# ---------------------------------------------------------------------------

class FakeManagerRepo:
    def __init__(self) -> None:
        self.managers: dict[int, FakeManager] = {}
        self.rosters: dict[int, list[FakeRosterEntry]] = {}
        self._players: FakePlayerRepo | None = None

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
        return sum(
            1 for e in self.list_roster(manager_id)
            if self._player_pos(e.player_id) is position
        )

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

    def release_from_roster(
        self, manager_id: int, player_id: int, released_at: datetime
    ) -> None:
        for entry in self.rosters.get(manager_id, []):
            if entry.player_id == player_id and entry.released_at is None:
                entry.released_at = released_at
                return
        raise KeyError(f"player {player_id} not on active roster of manager {manager_id}")

    # test helper
    def attach_player_repo(self, players: "FakePlayerRepo") -> None:
        self._players = players

    def _player_pos(self, player_id: int) -> Position:
        assert self._players is not None
        return self._players.get(player_id).position


class FakePlayerRepo:
    def __init__(self) -> None:
        self.players: dict[int, FakePlayer] = {}
        self._signed: set[int] = set()  # player_ids currently on some roster

    def add(self, p: FakePlayer) -> FakePlayer:
        self.players[p.id] = p
        return p

    def get(self, player_id: int) -> FakePlayer:
        return self.players[player_id]

    def is_free_agent(self, player_id: int, at: datetime) -> bool:
        return player_id not in self._signed

    def mark_signed(self, player_id: int) -> None:
        self._signed.add(player_id)


class FakeEligibilityRepo:
    def __init__(self) -> None:
        self.records: list[FakeEligibilityRecord] = []

    def list_for_player(self, player_id: int, at: datetime) -> list[FakeEligibilityRecord]:
        return [
            r for r in self.records
            if r.player_id == player_id
            and (r.valid_until is None or r.valid_until > at)
        ]

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


class FakeSubmissionRepo:
    def __init__(self) -> None:
        self._by_id: dict[int, FakeSubmission] = {}
        self._by_round_manager: dict[tuple[int, int], int] = {}  # (round_id, manager_id) -> sub_id
        self._next_id = 1

    def upsert(
        self,
        round_id: int,
        manager_id: int,
        received_at: datetime,
        source_file: str | None = None,
    ) -> int:
        key = (round_id, manager_id)
        if key in self._by_round_manager:
            # overwrite: update received_at / source_file
            sub_id = self._by_round_manager[key]
            s = self._by_id[sub_id]
            s.received_at = received_at
            s.source_file = source_file
            return sub_id
        sub_id = self._next_id
        self._next_id += 1
        sub = FakeSubmission(
            id=sub_id, round_id=round_id, manager_id=manager_id,
            received_at=received_at, source_file=source_file,
        )
        self._by_id[sub_id] = sub
        self._by_round_manager[key] = sub_id
        return sub_id

    def get(self, submission_id: int) -> FakeSubmission:
        return self._by_id[submission_id]

    def for_round(self, round_id: int) -> list[FakeSubmission]:
        return [s for s in self._by_id.values() if s.round_id == round_id]


class FakeBidRepo:
    """Fake BidRepo. Requires a FakeSubmissionRepo to resolve for_round() queries."""

    def __init__(self, submission_repo: FakeSubmissionRepo) -> None:
        self._submissions = submission_repo
        self._by_id: dict[int, FakeBid] = {}
        self._by_submission: dict[int, list[int]] = {}
        self._next_id = 1

    def create(
        self,
        submission_id: int,
        player_id: int,
        amount: int,
        rank_in_position: int,
    ) -> int:
        bid_id = self._next_id
        self._next_id += 1
        bid = FakeBid(
            id=bid_id, submission_id=submission_id, player_id=player_id,
            amount=amount, rank_in_position=rank_in_position,
        )
        self._by_id[bid_id] = bid
        self._by_submission.setdefault(submission_id, []).append(bid_id)
        return bid_id

    def for_round(self, round_id: int) -> list[FakeBid]:
        sub_ids = {s.id for s in self._submissions.for_round(round_id)}
        return [b for b in self._by_id.values() if b.submission_id in sub_ids]

    def for_submission(self, submission_id: int) -> list[FakeBid]:
        return [self._by_id[i] for i in self._by_submission.get(submission_id, [])]

    def clear_for_submission(self, submission_id: int) -> None:
        bid_ids = self._by_submission.pop(submission_id, [])
        for bid_id in bid_ids:
            self._by_id.pop(bid_id, None)

    def update_status(
        self, bid_id: int, status: BidStatus, reason: str | None = None
    ) -> None:
        b = self._by_id[bid_id]
        b.status = status
        b.invalid_reason = reason


class FakeAuctionRoundRepo:
    def __init__(self) -> None:
        self._by_id: dict[int, FakeAuctionRound] = {}

    def add(self, rnd: FakeAuctionRound) -> None:
        self._by_id[rnd.id] = rnd

    def get(self, round_id: int) -> FakeAuctionRound:
        return self._by_id[round_id]

    def set_status(self, round_id: int, status: AuctionRoundStatus) -> None:
        self._by_id[round_id].status = status


class FakeAuctionResultRepo:
    def __init__(self) -> None:
        self._results: list[FakeAuctionResult] = []
        self._next_id = 1

    def create(
        self,
        round_id: int,
        player_id: int,
        winner_manager_id: int,
        price: int,
    ) -> None:
        self._results.append(
            FakeAuctionResult(
                id=self._next_id, round_id=round_id, player_id=player_id,
                winner_manager_id=winner_manager_id, price=price,
            )
        )
        self._next_id += 1

    def for_round(self, round_id: int) -> list[FakeAuctionResult]:
        return [r for r in self._results if r.round_id == round_id]


@dataclass
class FakeDismissal:
    id: int
    manager_id: int
    player_id: int
    dismissed_at: datetime
    reason: str | None = None


class FakeDismissalRepo:
    def __init__(self) -> None:
        self._records: list[FakeDismissal] = []
        self._next_id = 1

    def create(
        self,
        manager_id: int,
        player_id: int,
        dismissed_at: datetime,
        reason: str | None = None,
    ) -> int:
        rec = FakeDismissal(
            id=self._next_id,
            manager_id=manager_id,
            player_id=player_id,
            dismissed_at=dismissed_at,
            reason=reason,
        )
        self._records.append(rec)
        self._next_id += 1
        return rec.id

    def for_manager(self, manager_id: int) -> list[FakeDismissal]:
        return [r for r in self._records if r.manager_id == manager_id]

    def for_player(self, player_id: int) -> list[FakeDismissal]:
        return [r for r in self._records if r.player_id == player_id]


class FakeFreeSignRepo:
    def __init__(self) -> None:
        self._by_id: dict[int, FakeFreeSign] = {}
        self._next_id = 1

    def create(
        self,
        window_id: int,
        manager_id: int,
        player_id: int,
        fee: int,
        posted_at: datetime,
    ) -> int:
        fid = self._next_id
        self._next_id += 1
        self._by_id[fid] = FakeFreeSign(
            id=fid, window_id=window_id, manager_id=manager_id,
            player_id=player_id, fee=fee, posted_at=posted_at,
        )
        return fid

    def get(self, free_sign_id: int) -> FakeFreeSign:
        return self._by_id[free_sign_id]

    def pending_in_window(self, window_id: int) -> list[FakeFreeSign]:
        return [
            fs for fs in self._by_id.values()
            if fs.window_id == window_id and not fs.revoked and not fs.effective
        ]

    def for_manager_in_window(
        self, manager_id: int, window_id: int
    ) -> list[FakeFreeSign]:
        return [
            fs for fs in self._by_id.values()
            if fs.manager_id == manager_id and fs.window_id == window_id
        ]

    def mark_revoked(self, free_sign_id: int) -> None:
        self._by_id[free_sign_id].revoked = True

    def mark_effective(self, free_sign_id: int) -> None:
        self._by_id[free_sign_id].effective = True


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

    def next_window(self, at: datetime) -> Optional[FakeTransferWindow]:
        future = [w for w in self.windows if w.opens_at > at]
        return min(future, key=lambda w: w.opens_at) if future else None


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------

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


def make_auction_repos(
    managers: list[FakeManager] | None = None,
    players: list[FakePlayer] | None = None,
) -> tuple[
    FakeManagerRepo, FakePlayerRepo, FakeEligibilityRepo,
    FakeSubmissionRepo, FakeBidRepo, FakeAuctionRoundRepo, FakeAuctionResultRepo,
    FakeTransferRepo,
]:
    mgr, plr, elig = make_repos(managers, players)
    sub_repo = FakeSubmissionRepo()
    bid_repo = FakeBidRepo(sub_repo)
    rnd_repo = FakeAuctionRoundRepo()
    res_repo = FakeAuctionResultRepo()
    trn_repo = FakeTransferRepo()
    return mgr, plr, elig, sub_repo, bid_repo, rnd_repo, res_repo, trn_repo
