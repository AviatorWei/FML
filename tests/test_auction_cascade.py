"""Tests for fmlwc.domain.auction.cascade — position-cap & budget cascades."""

from __future__ import annotations

from fmlwc.core.enums import BidStatus, Position
from fmlwc.domain.auction.bids import RawBid, ValidationOutcome
from fmlwc.domain.auction.cascade import CascadeContext, CascadeInvalidator

from tests.sample_rules import default_rules


def _outcome(player_id, amount, rank, status=BidStatus.VALID):
    return ValidationOutcome(
        RawBid(manager_id=1, player_id=player_id, amount=amount, rank_in_position=rank),
        status,
    )


def test_no_op_when_within_caps_and_budget():
    rules = default_rules()
    ctx = CascadeContext(
        manager_id=1,
        balance_at_close=600,
        current_position_counts={Position.G: 0, Position.D: 0, Position.M: 0, Position.F: 0},
        bids=[_outcome(1, 50, 1)],
        bid_positions={1: Position.F},
    )
    out = CascadeInvalidator(rules).run(ctx)
    assert all(o.status is BidStatus.VALID for o in out)


def test_position_cap_invalidates_highest_first():
    """F cap = 4, current count = 4 -> any new F bid must drop the highest first."""
    rules = default_rules()
    bids = [
        _outcome(1, 100, 1),
        _outcome(2, 50, 2),
        _outcome(3, 30, 3),
    ]
    ctx = CascadeContext(
        manager_id=1, balance_at_close=600,
        current_position_counts={Position.F: 4, Position.G: 0, Position.D: 0, Position.M: 0},
        bids=bids,
        bid_positions={1: Position.F, 2: Position.F, 3: Position.F},
    )
    out = CascadeInvalidator(rules).run(ctx)
    # All 3 F bids must be invalidated: 4 + 3 = 7 > 4.
    statuses = {o.bid.player_id: o.status for o in out}
    assert statuses[1] is BidStatus.INVALID_POS_CAP
    assert statuses[2] is BidStatus.INVALID_POS_CAP
    assert statuses[3] is BidStatus.INVALID_POS_CAP


def test_position_cap_keeps_lower_priced_when_one_drop_enough():
    """F cap = 4, current = 3, 2 new F bids -> drop the higher one."""
    rules = default_rules()
    bids = [
        _outcome(1, 100, 1),
        _outcome(2, 50, 2),
    ]
    ctx = CascadeContext(
        manager_id=1, balance_at_close=600,
        current_position_counts={Position.F: 3, Position.G: 0, Position.D: 0, Position.M: 0},
        bids=bids,
        bid_positions={1: Position.F, 2: Position.F},
    )
    out = CascadeInvalidator(rules).run(ctx)
    statuses = {o.bid.player_id: o.status for o in out}
    assert statuses[1] is BidStatus.INVALID_POS_CAP
    assert statuses[2] is BidStatus.VALID


def test_position_tie_break_F_over_M_over_D_over_G():
    """Three positions exactly tied at the highest price.
    Position priority: F > M > D > G — so F drops first."""
    rules = default_rules()
    # All three are budget-violating ties at 200m on a balance of 100m.
    bids = [
        _outcome(1, 200, 1),  # F
        _outcome(2, 200, 1),  # M
        _outcome(3, 200, 1),  # D
    ]
    ctx = CascadeContext(
        manager_id=1, balance_at_close=100,
        current_position_counts={Position.G: 0, Position.D: 0, Position.M: 0, Position.F: 0},
        bids=bids,
        bid_positions={1: Position.F, 2: Position.M, 3: Position.D},
    )
    out = CascadeInvalidator(rules).run(ctx)
    statuses = {o.bid.player_id: o.status for o in out}
    # Drop F first (highest priority for invalidation), then M and D until budget OK.
    # Total starts 600m, balance 100m. After dropping F: 400m. Drop M: 200m. Drop D: 0m -> ok
    assert statuses[1] is BidStatus.INVALID_BUDGET
    assert statuses[2] is BidStatus.INVALID_BUDGET
    assert statuses[3] is BidStatus.INVALID_BUDGET


def test_within_position_lower_rank_drops_first_on_tie():
    rules = default_rules()
    # Two F bids tied at 200m, balance only allows one. Lower rank (1) drops first.
    bids = [
        _outcome(1, 200, 1),
        _outcome(2, 200, 2),
    ]
    ctx = CascadeContext(
        manager_id=1, balance_at_close=200,
        current_position_counts={Position.G: 0, Position.D: 0, Position.M: 0, Position.F: 0},
        bids=bids,
        bid_positions={1: Position.F, 2: Position.F},
    )
    out = CascadeInvalidator(rules).run(ctx)
    statuses = {o.bid.player_id: o.status for o in out}
    assert statuses[1] is BidStatus.INVALID_BUDGET   # rank 1 dropped
    assert statuses[2] is BidStatus.VALID


def test_budget_drops_highest_iteratively():
    rules = default_rules()
    bids = [
        _outcome(1, 300, 1),  # F
        _outcome(2, 200, 1),  # M
        _outcome(3, 50, 1),   # D
    ]
    ctx = CascadeContext(
        manager_id=1, balance_at_close=100,
        current_position_counts={Position.G: 0, Position.D: 0, Position.M: 0, Position.F: 0},
        bids=bids,
        bid_positions={1: Position.F, 2: Position.M, 3: Position.D},
    )
    out = CascadeInvalidator(rules).run(ctx)
    statuses = {o.bid.player_id: o.status for o in out}
    # 550m total > 100m. Drop 300 (F) -> 250 > 100. Drop 200 (M) -> 50 <= 100. OK.
    assert statuses[1] is BidStatus.INVALID_BUDGET
    assert statuses[2] is BidStatus.INVALID_BUDGET
    assert statuses[3] is BidStatus.VALID


def test_position_loop_runs_F_M_D_G_in_order():
    """If both F and M caps are violated, F is processed first per
    invalidate_tie_priority. Verify order doesn't accidentally invalidate
    extra bids."""
    rules = default_rules()
    bids = [
        _outcome(1, 100, 1),  # F (cap 4, current 4 -> overflow)
        _outcome(2, 80, 1),   # M (cap 8, current 8 -> overflow)
    ]
    ctx = CascadeContext(
        manager_id=1, balance_at_close=600,
        current_position_counts={Position.F: 4, Position.M: 8, Position.D: 0, Position.G: 0},
        bids=bids,
        bid_positions={1: Position.F, 2: Position.M},
    )
    out = CascadeInvalidator(rules).run(ctx)
    statuses = {o.bid.player_id: o.status for o in out}
    assert statuses[1] is BidStatus.INVALID_POS_CAP
    assert statuses[2] is BidStatus.INVALID_POS_CAP


def test_existing_invalid_bids_unchanged():
    rules = default_rules()
    bids = [
        ValidationOutcome(RawBid(1, 1, 100, 1),
                          BidStatus.INVALID_PER_BID, "below min"),
        _outcome(2, 50, 1),
    ]
    ctx = CascadeContext(
        manager_id=1, balance_at_close=600,
        current_position_counts={Position.G: 0, Position.D: 0, Position.M: 0, Position.F: 0},
        bids=bids,
        bid_positions={1: Position.F, 2: Position.F},
    )
    out = CascadeInvalidator(rules).run(ctx)
    statuses = {o.bid.player_id: o.status for o in out}
    assert statuses[1] is BidStatus.INVALID_PER_BID  # untouched
    assert statuses[2] is BidStatus.VALID
