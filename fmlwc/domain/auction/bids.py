"""Bid value object + per-bid validation (rule 二.3).

Separates raw input from persisted ORM Bid so we can validate before
touching the DB.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from ...core.config import GameRules
from ...core.enums import BidStatus, EligibilityRestriction


@dataclass(frozen=True)
class RawBid:
    manager_id: int
    player_id: int
    amount: int  # unit: million EUR
    rank_in_position: int


@dataclass(frozen=True)
class ValidationOutcome:
    bid: RawBid
    status: BidStatus
    reason: str | None = None


class BidValidator:
    """Per-bid Step-0 checks (rule 二.3) plus rank-uniqueness check."""

    def __init__(self, rules: GameRules, players, eligibility) -> None:
        self.rules = rules
        self.players = players
        self.eligibility = eligibility

    def validate_one(self, bid, *, balance_at_close: int, at: datetime) -> ValidationOutcome:
        # 二.3.(1) integers only
        if not isinstance(bid.amount, int) or isinstance(bid.amount, bool):
            return ValidationOutcome(bid, BidStatus.INVALID_PER_BID, "amount not integer")
        if not isinstance(bid.rank_in_position, int) or isinstance(bid.rank_in_position, bool):
            return ValidationOutcome(bid, BidStatus.INVALID_PER_BID, "rank not integer")

        # 二.3.(3) rank must be positive
        if bid.rank_in_position <= 0:
            return ValidationOutcome(bid, BidStatus.INVALID_PER_BID, "rank not positive")

        # 二.3.(2) min bid + budget
        if bid.amount < self.rules.auction.min_bid:
            return ValidationOutcome(bid, BidStatus.INVALID_PER_BID, "amount below min_bid")
        if bid.amount > balance_at_close:
            return ValidationOutcome(bid, BidStatus.INVALID_PER_BID, "amount exceeds balance")

        # 二.3.(4) signing eligibility
        records = self.eligibility.list_for_player(bid.player_id, at)
        for rec in records:
            if rec.restriction_type in (
                EligibilityRestriction.AUCTION_OTHERS_NEXT_WINDOW,
                EligibilityRestriction.FREE_SIGN_SAME_WINDOW,
            ):
                if rec.manager_id != bid.manager_id:
                    return ValidationOutcome(
                        bid, BidStatus.INVALID_INELIGIBLE,
                        f"blocked by {rec.restriction_type.value}",
                    )
            elif rec.manager_id == bid.manager_id:
                return ValidationOutcome(
                    bid, BidStatus.INVALID_INELIGIBLE,
                    f"blocked by {rec.restriction_type.value}",
                )

        return ValidationOutcome(bid, BidStatus.VALID)

    def validate_submission(self, bids, *, balance_at_close, at):
        """Run validate_one across the submission, then enforce
        within-position rank uniqueness (rule 二.2).
        """
        outcomes = [self.validate_one(b, balance_at_close=balance_at_close, at=at) for b in bids]

        seen = {}
        for i, o in enumerate(outcomes):
            if o.status is not BidStatus.VALID:
                continue
            pos = self.players.get(o.bid.player_id).position
            key = (pos.value if hasattr(pos, "value") else pos, o.bid.rank_in_position)
            seen.setdefault(key, []).append(i)
        for key, idxs in seen.items():
            if len(idxs) > 1:
                for i in idxs:
                    outcomes[i] = ValidationOutcome(
                        outcomes[i].bid,
                        BidStatus.INVALID_PER_BID,
                        "duplicate rank within position",
                    )
        return outcomes
