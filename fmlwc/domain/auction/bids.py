"""Bid value object + per-bid validation (rule 二.3).

Separates raw input from persisted ORM Bid so we can validate before
touching the DB.

Conditional release (条件解约, rule 二.X):
    A bid with rank_in_position < 0 marks an existing roster player for
    conditional release. If any acquisition bid in the same submission wins,
    the player at rank -1 is released first, rank -2 second, and so on.
    Conditional release bids skip amount/balance checks; the player_id must
    already be on the submitting manager's active roster.
    This feature is gated by rules.auction.conditional_release_enabled.

Negative ranks are GLOBALLY scoped (not per-position):
    rank -1 = first player to release if any bid wins
    rank -2 = second player to release if two bids win
    etc.
    Duplicate negative ranks within a submission are therefore invalid.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ...core.config import GameRules
from ...core.enums import BidStatus, EligibilityRestriction


@dataclass(frozen=True)
class RawBid:
    manager_id: int
    player_id: int
    amount: int  # unit: million EUR
    rank_in_position: int = 100  # default rank when not explicitly specified

    @property
    def is_conditional_release(self) -> bool:
        """True when this bid marks an existing roster player for conditional release."""
        return self.rank_in_position < 0


@dataclass(frozen=True)
class ValidationOutcome:
    bid: RawBid
    status: BidStatus
    reason: str | None = None


class BidValidator:
    """Per-bid Step-0 checks (rule 二.3) plus rank-uniqueness check."""

    def __init__(self, rules: GameRules, managers, players, eligibility) -> None:
        self.rules = rules
        self.managers = managers
        self.players = players
        self.eligibility = eligibility

    def validate_one(self, bid, *, balance_at_close: int, at: datetime) -> ValidationOutcome:
        # 二.3.(1) integers only
        if not isinstance(bid.amount, int) or isinstance(bid.amount, bool):
            return ValidationOutcome(bid, BidStatus.INVALID_PER_BID, "amount not integer")
        if not isinstance(bid.rank_in_position, int) or isinstance(bid.rank_in_position, bool):
            return ValidationOutcome(bid, BidStatus.INVALID_PER_BID, "rank not integer")

        # rank == 0 is never valid
        if bid.rank_in_position == 0:
            return ValidationOutcome(bid, BidStatus.INVALID_PER_BID, "rank must not be zero")

        # Conditional release branch (negative rank)
        if bid.rank_in_position < 0:
            if not self.rules.auction.conditional_release_enabled:
                return ValidationOutcome(
                    bid, BidStatus.INVALID_PER_BID,
                    "conditional release is disabled in this league",
                )
            # The referenced player must be on this manager's active roster
            active_ids = {e.player_id for e in self.managers.list_roster(bid.manager_id)}
            if bid.player_id not in active_ids:
                return ValidationOutcome(
                    bid, BidStatus.INVALID_PER_BID,
                    "conditional release player not on manager's active roster",
                )
            return ValidationOutcome(bid, BidStatus.VALID)

        # --- Acquisition bid (positive rank) ---

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
        """Run validate_one across the submission, then enforce rank uniqueness.

        Acquisition bids (rank > 0): unique per (position, rank).
        Conditional release bids (rank < 0): unique globally across the
        whole submission — negative ranks are release-order slots, not
        per-position.
        """
        outcomes = [self.validate_one(b, balance_at_close=balance_at_close, at=at) for b in bids]

        # Acquisition rank uniqueness: per (position, rank)
        seen_acq: dict = {}
        for i, o in enumerate(outcomes):
            if o.status is not BidStatus.VALID or o.bid.is_conditional_release:
                continue
            pos = self.players.get(o.bid.player_id).position
            key = (pos.value if hasattr(pos, "value") else pos, o.bid.rank_in_position)
            seen_acq.setdefault(key, []).append(i)
        for key, idxs in seen_acq.items():
            if len(idxs) > 1:
                for i in idxs:
                    outcomes[i] = ValidationOutcome(
                        outcomes[i].bid,
                        BidStatus.INVALID_PER_BID,
                        "duplicate rank within position",
                    )

        # Conditional release rank uniqueness: global (rank -1 is unique regardless of position)
        seen_cr: dict = {}
        for i, o in enumerate(outcomes):
            if o.status is not BidStatus.VALID or not o.bid.is_conditional_release:
                continue
            seen_cr.setdefault(o.bid.rank_in_position, []).append(i)
        for rank, idxs in seen_cr.items():
            if len(idxs) > 1:
                for i in idxs:
                    outcomes[i] = ValidationOutcome(
                        outcomes[i].bid,
                        BidStatus.INVALID_PER_BID,
                        "duplicate conditional release rank",
                    )

        return outcomes
