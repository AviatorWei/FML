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


# --- total roster cap loop tests ------------------------------------------

def _cr_outcome(player_id, rank_neg):
    """A VALID conditional-release bid (rank < 0)."""
    return ValidationOutcome(
        RawBid(manager_id=1, player_id=player_id, amount=0, rank_in_position=rank_neg),
        BidStatus.VALID,
    )


def test_total_roster_cap_no_cr_drops_highest():
    """Without conditional release: if current_total_roster + acquisitions > total_cap,
    the most expensive acquisition bids are dropped until the cap holds.
    total_cap = 20; current_total_roster_count = 19; 2 acq bids -> 21 > 20 -> drop 1."""
    rules = default_rules()
    bids = [
        _outcome(1, 100, 1),   # F, higher amount -> should be dropped
        _outcome(2, 50, 1),    # M, lower  -> should survive
    ]
    ctx = CascadeContext(
        manager_id=1, balance_at_close=600,
        current_position_counts={Position.G: 0, Position.D: 0, Position.M: 0, Position.F: 0},
        bids=bids,
        bid_positions={1: Position.F, 2: Position.M},
        current_total_roster_count=19,
    )
    out = CascadeInvalidator(rules).run(ctx)
    statuses = {o.bid.player_id: o.status for o in out}
    assert statuses[1] is BidStatus.INVALID_BUDGET   # "exceeds total roster cap"
    assert statuses[2] is BidStatus.VALID


def test_total_roster_cap_no_cr_all_dropped_when_full():
    """Roster already at cap (20/20); any acquisition must be dropped."""
    rules = default_rules()
    bids = [_outcome(1, 50, 1)]
    ctx = CascadeContext(
        manager_id=1, balance_at_close=600,
        current_position_counts={Position.G: 0, Position.D: 0, Position.M: 0, Position.F: 0},
        bids=bids,
        bid_positions={1: Position.F},
        current_total_roster_count=20,
    )
    out = CascadeInvalidator(rules).run(ctx)
    assert out[0].status is BidStatus.INVALID_BUDGET


def test_total_roster_cap_no_cr_within_cap_unchanged():
    """current_total_roster + acquisitions == total_cap: no drops needed."""
    rules = default_rules()
    bids = [
        _outcome(1, 100, 1),
        _outcome(2, 80, 1),
    ]
    ctx = CascadeContext(
        manager_id=1, balance_at_close=600,
        current_position_counts={Position.G: 0, Position.D: 0, Position.M: 0, Position.F: 0},
        bids=bids,
        bid_positions={1: Position.F, 2: Position.M},
        current_total_roster_count=18,  # 18 + 2 == 20 -> exactly at cap
    )
    out = CascadeInvalidator(rules).run(ctx)
    assert all(o.status is BidStatus.VALID for o in out)


def test_total_roster_cap_with_cr_releases_create_room():
    """With conditional_release enabled: one CR bid frees a slot, so 2 acq + 1 CR at
    current_count=20 projects to 20+2-1=21 -> one acquisition must drop."""
    from tests.sample_rules import raw_dict
    from fmlwc.core import GameRules

    cfg = raw_dict()
    cfg["auction"]["conditional_release"] = {"enabled": True}
    rules = GameRules.from_dict(cfg)

    bids = [
        _outcome(1, 100, 1),    # F  -- higher, drops first
        _outcome(2, 50, 1),     # M  -- lower, survives
        _cr_outcome(10, -1),    # conditional release
    ]
    ctx = CascadeContext(
        manager_id=1, balance_at_close=600,
        current_position_counts={Position.G: 0, Position.D: 0, Position.M: 0, Position.F: 0},
        bids=bids,
        bid_positions={1: Position.F, 2: Position.M, 10: Position.D},
        current_total_roster_count=20,  # 20 + 2 - 1 = 21 -> one drop
    )
    out = CascadeInvalidator(rules).run(ctx)
    statuses = {o.bid.player_id: o.status for o in out}
    assert statuses[1] is BidStatus.INVALID_BUDGET
    assert statuses[2] is BidStatus.VALID
    assert statuses[10] is BidStatus.VALID   # CR bid untouched


def test_total_roster_cap_with_cr_enough_room_no_drops():
    """With conditional_release enabled: 2 CRs free 2 slots; 2 acq at count=20 =>
    20 + 2 - 2 = 20 -> exactly at cap, no drops needed."""
    from tests.sample_rules import raw_dict
    from fmlwc.core import GameRules

    cfg = raw_dict()
    cfg["auction"]["conditional_release"] = {"enabled": True}
    rules = GameRules.from_dict(cfg)

    bids = [
        _outcome(1, 100, 1),
        _outcome(2, 80, 1),
        _cr_outcome(10, -1),
        _cr_outcome(11, -2),
    ]
    ctx = CascadeContext(
        manager_id=1, balance_at_close=600,
        current_position_counts={Position.G: 0, Position.D: 0, Position.M: 0, Position.F: 0},
        bids=bids,
        bid_positions={1: Position.F, 2: Position.M, 10: Position.D, 11: Position.D},
        current_total_roster_count=20,  # 20 + 2 - 2 = 20 -> ok
    )
    out = CascadeInvalidator(rules).run(ctx)
    statuses = {o.bid.player_id: o.status for o in out}
    assert statuses[1] is BidStatus.VALID
    assert statuses[2] is BidStatus.VALID
    assert statuses[10] is BidStatus.VALID
    assert statuses[11] is BidStatus.VALID
