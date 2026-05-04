"""End-to-end auction round orchestration.

Typical flow:

    svc = AuctionService(rules, deps...)
    svc.open_round(round_id)
    svc.submit(round_id, manager_id, raw_bids, received_at)
    ...                                                # other managers submit
    svc.close_round(round_id, at=closes_at)            # status -> RESOLVING
    result = svc.resolve(round_id)                     # cascade + winners

Everything from `close_round` onward must run in a single DB transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from ...core.config import GameRules
from ...persistence.repositories import (
    BidRepo,
    EligibilityRepo,
    ManagerRepo,
    PlayerRepo,
)
from ..eligibility import EligibilityService
from .bids import BidValidator, RawBid
from .cascade import CascadeInvalidator
from .tiebreaker import TiebreakerStrategy, get_strategy


@dataclass
class RoundResolution:
    """Returned by AuctionService.resolve."""

    round_id: int
    awards: list[tuple[int, int, int]]   # (player_id, winner_manager_id, price)
    invalidated: int
    total_spend: int


class AuctionService:
    def __init__(
        self,
        rules: GameRules,
        managers: ManagerRepo,
        players: PlayerRepo,
        bids: BidRepo,
        eligibility_repo: EligibilityRepo,
        eligibility_service: EligibilityService,
    ) -> None:
        self.rules = rules
        self.managers = managers
        self.players = players
        self.bids = bids
        self.eligibility_repo = eligibility_repo
        self.eligibility = eligibility_service
        self.validator = BidValidator(rules, managers, players, eligibility_repo)
        self.cascade = CascadeInvalidator(rules)
        self.tiebreaker: TiebreakerStrategy = get_strategy(rules.auction.tiebreaker)

    # -- lifecycle ---------------------------------------------------------
    def open_round(self, round_id: int) -> None:
        raise NotImplementedError("TODO: set status OPEN, emit event")

    def submit(
        self,
        round_id: int,
        manager_id: int,
        raw_bids: Sequence[RawBid],
        received_at: datetime,
    ) -> int:
        """Persist a Submission + N Bid rows after Step-0 per-bid checks.

        Returns submission_id. Idempotent: re-submission overwrites prior
        submission for (round, manager) per rule 二.2.
        """
        raise NotImplementedError("TODO")

    def close_round(self, round_id: int, *, at: datetime) -> None:
        raise NotImplementedError("TODO: status -> RESOLVING; freeze submissions")

    # -- resolution --------------------------------------------------------
    def resolve(self, round_id: int) -> RoundResolution:
        """Run cascade per submission, then per-player tiebreaker, then
        commit awards + balance deductions + eligibility blocks.

        Steps:
            1. for each submission:
                  ctx = CascadeContext(...)
                  cascade.run(ctx)
                  persist updated bid statuses
            2. group remaining VALID bids by player
            3. for each player: tiebreaker.select_winner -> Award row
            4. deduct winners' balances; insert RosterEntry; create
               eligibility records (rule 二.7) for OTHER managers covering
               the next transfer window.
            5. status -> CLOSED
        """
        raise NotImplementedError("TODO")

    # -- helpers -----------------------------------------------------------
    def _draw_seed(self, round_id: int, player_id: int, manager_id: int) -> int:
        """Deterministic last-resort tiebreak seed."""
        raise NotImplementedError("TODO: hash(round_id, player_id, manager_id) % 2**31")
