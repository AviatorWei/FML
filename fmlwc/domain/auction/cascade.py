"""Cascade invalidation (rules 二.4 and 二.5).

Runs *after* per-bid validation. Iteratively invalidates the highest-priced
remaining bid until BOTH constraints hold:

    * position caps: count(remaining bids of pos) + current_roster[pos]
                     <= rules.roster.position_caps[pos]
    * total budget:  sum(remaining amounts) <= balance_at_close

Tie-break when several remaining bids share the highest amount:
    * across positions: rules.auction.cascade.invalidate_tie_priority
      (default: F > M > D > G)
    * within position: smaller rank_in_position first
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...core.config import GameRules
from ...core.enums import BidStatus, Position
from .bids import ValidationOutcome


@dataclass
class CascadeContext:
    """Data needed to run the cascade for one submission."""

    manager_id: int
    balance_at_close: int
    current_position_counts: dict[Position, int]
    bids: list[ValidationOutcome]                 # input + INVALID flags get added
    bid_positions: dict[int, Position] = field(default_factory=dict)
    """player_id -> Position, supplied by caller via PlayerRepo.get(...).position"""


class CascadeInvalidator:
    """Pure-function-style runner; no DB writes here."""

    def __init__(self, rules: GameRules) -> None:
        self.rules = rules

    def run(self, ctx: CascadeContext) -> list[ValidationOutcome]:
        """Apply both loops in sequence; return the same list (mutated)."""
        self._position_cap_loop(ctx)
        self._budget_loop(ctx)
        return ctx.bids

    # -- position-cap loop -------------------------------------------------
    def _position_cap_loop(self, ctx: CascadeContext) -> None:
        """For each position in the configured priority order, invalidate
        the highest-priced VALID bid in that position until the cap holds.
        """
        for pos in self.rules.auction.cascade.position_priority:
            cap = self.rules.roster.position_caps.get(pos)
            if cap is None:
                continue
            current = ctx.current_position_counts.get(pos, 0)
            while True:
                pos_bids = [
                    o for o in ctx.bids
                    if o.status is BidStatus.VALID
                    and ctx.bid_positions[o.bid.player_id] is pos
                ]
                if current + len(pos_bids) <= cap:
                    break
                victim = self._select_drop(pos_bids, ctx.bid_positions)
                self._mark(ctx, victim, BidStatus.INVALID_POS_CAP, "exceeds position cap")

    # -- budget loop -------------------------------------------------------
    def _budget_loop(self, ctx: CascadeContext) -> None:
        while True:
            valids = [o for o in ctx.bids if o.status is BidStatus.VALID]
            total = sum(o.bid.amount for o in valids)
            if total <= ctx.balance_at_close:
                break
            victim = self._select_drop(valids, ctx.bid_positions)
            self._mark(ctx, victim, BidStatus.INVALID_BUDGET, "exceeds budget")

    # -- tie-break ---------------------------------------------------------
    def _select_drop(
        self,
        candidates: list[ValidationOutcome],
        bid_pos: dict[int, Position],
    ) -> ValidationOutcome:
        tie_priority = self.rules.auction.cascade.invalidate_tie_priority
        priority_index = {p: i for i, p in enumerate(tie_priority)}

        def key(o: ValidationOutcome):
            pos = bid_pos[o.bid.player_id]
            # primary: highest amount first => negate
            # secondary: position priority (F first => index 0 first)
            # tertiary: lower rank first (rule 二.5)
            return (-o.bid.amount, priority_index.get(pos, 999), o.bid.rank_in_position)

        return min(candidates, key=key)

    # -- helper ------------------------------------------------------------
    def _mark(
        self,
        ctx: CascadeContext,
        target: ValidationOutcome,
        status: BidStatus,
        reason: str,
    ) -> None:
        for i, o in enumerate(ctx.bids):
            if o is target:
                ctx.bids[i] = ValidationOutcome(o.bid, status, reason)
                return
        raise AssertionError("victim not found in ctx.bids")
