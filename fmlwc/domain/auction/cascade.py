"""Cascade invalidation (rules 二.4 and 二.5).

Runs *after* per-bid validation. Iteratively invalidates the highest-priced
remaining acquisition bid until ALL three constraints hold:

    * position caps:  count(remaining acquisition bids of pos) + current_roster[pos]
                      <= rules.roster.position_caps[pos]
    * total budget:   sum(remaining acquisition amounts) <= balance_at_close
    * total roster:   current_total_roster + remaining_acquisitions
                      - valid_conditional_releases <= rules.roster.total_cap
                      (conditional releases only count when the feature is
                      enabled; when disabled their bids are already INVALID
                      so _release_bids returns [] anyway)

Conditional release bids (rank_in_position < 0) are carried in ctx.bids but
are never chosen as drop victims; they are factored into the total-roster
constraint check only.

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
    current_total_roster_count: int = 0
    """Total active players currently on this manager's roster (all positions).
    Used by the total-roster-cap loop."""


class CascadeInvalidator:
    """Pure-function-style runner; no DB writes here."""

    def __init__(self, rules: GameRules) -> None:
        self.rules = rules

    def run(self, ctx: CascadeContext) -> list[ValidationOutcome]:
        """Apply all loops in sequence; return the same list (mutated)."""
        self._position_cap_loop(ctx)
        self._budget_loop(ctx)
        self._total_roster_cap_loop(ctx)
        return ctx.bids

    # -- helpers: acquisition vs. conditional release bids -----------------

    @staticmethod
    def _acquisition_bids(bids: list[ValidationOutcome]) -> list[ValidationOutcome]:
        """VALID bids that are trying to acquire a new player (rank > 0)."""
        return [o for o in bids if o.status is BidStatus.VALID and not o.bid.is_conditional_release]

    @staticmethod
    def _release_bids(bids: list[ValidationOutcome]) -> list[ValidationOutcome]:
        """VALID conditional-release markers (rank < 0).
        Returns [] when conditional_release is disabled because those bids
        will already have been marked INVALID by validate_one."""
        return [o for o in bids if o.status is BidStatus.VALID and o.bid.is_conditional_release]

    # -- position-cap loop -------------------------------------------------
    def _position_cap_loop(self, ctx: CascadeContext) -> None:
        """For each position in the configured priority order, invalidate
        the highest-priced VALID acquisition bid in that position until the
        cap holds.
        """
        for pos in self.rules.auction.cascade.position_priority:
            cap = self.rules.roster.position_caps.get(pos)
            if cap is None:
                continue
            current = ctx.current_position_counts.get(pos, 0)
            while True:
                pos_bids = [
                    o for o in self._acquisition_bids(ctx.bids)
                    if ctx.bid_positions[o.bid.player_id] is pos
                ]
                if current + len(pos_bids) <= cap:
                    break
                victim = self._select_drop(pos_bids, ctx.bid_positions)
                self._mark(ctx, victim, BidStatus.INVALID_POS_CAP, "exceeds position cap")

    # -- budget loop -------------------------------------------------------
    def _budget_loop(self, ctx: CascadeContext) -> None:
        while True:
            acq = self._acquisition_bids(ctx.bids)
            total = sum(o.bid.amount for o in acq)
            if total <= ctx.balance_at_close:
                break
            victim = self._select_drop(acq, ctx.bid_positions)
            self._mark(ctx, victim, BidStatus.INVALID_BUDGET, "exceeds budget")

    # -- total roster cap loop ---------------------------------------------
    def _total_roster_cap_loop(self, ctx: CascadeContext) -> None:
        """Always runs. Drops the highest-priced acquisition bid while:
            current_total_roster + acquisitions - conditional_releases > total_cap
        When conditional_release is disabled, _release_bids returns [] so
        the formula reduces to: current_total_roster + acquisitions > total_cap.
        """
        total_cap = self.rules.roster.total_cap
        while True:
            acq = self._acquisition_bids(ctx.bids)
            releases = self._release_bids(ctx.bids)
            projected = ctx.current_total_roster_count + len(acq) - len(releases)
            if projected <= total_cap:
                break
            if not acq:
                break
            victim = self._select_drop(acq, ctx.bid_positions)
            self._mark(ctx, victim, BidStatus.INVALID_BUDGET, "exceeds total roster cap")

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
