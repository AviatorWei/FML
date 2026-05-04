"""Tests for fmlwc.domain.prize."""

from __future__ import annotations

from fmlwc.domain.prize import PrizeDistributor, round_half_up

from tests.sample_rules import default_rules


def test_round_half_up():
    # 1.5m -> 2m, 1.4m -> 1m, 0.5m -> 1m (half-up)
    assert round_half_up(1.5) == 2
    assert round_half_up(1.4) == 1
    assert round_half_up(0.5) == 1
    assert round_half_up(2.5) == 3   # half-up not banker's


def test_qualify_distribution_two_managers():
    """Two equal-weight qualifiers split pool 50/50 + 80m extra each."""
    rules = default_rules()
    pd = PrizeDistributor(rules)
    payouts = pd.distribute_qualify(
        eliminated_balances={3: 200, 4: 100},  # pool 300m
        qualifier_stats={
            1: {"points": 6, "goals_for": 4},
            2: {"points": 6, "goals_for": 4},
        },
    )
    by_mgr = {p.manager_id: p.amount for p in payouts}
    # Each weight=8, total=16, base share = 300m*0.5 = 150m, +80m = 230m
    assert by_mgr[1] == 230
    assert by_mgr[2] == 230


def test_qualify_weighting_skews_to_better_record():
    rules = default_rules()
    pd = PrizeDistributor(rules)
    payouts = pd.distribute_qualify(
        eliminated_balances={3: 100},   # 100m pool
        qualifier_stats={
            1: {"points": 9, "goals_for": 6},   # weight = 9 + 3 = 12
            2: {"points": 3, "goals_for": 2},   # weight = 3 + 1 = 4
        },
    )
    by_mgr = {p.manager_id: p.amount for p in payouts}
    # 1: 100*12/16 = 75m + 80m = 155m
    # 2: 100*4/16  = 25m + 80m = 105m
    assert by_mgr[1] == 155
    assert by_mgr[2] == 105


def test_advance_distribution():
    rules = default_rules()
    pd = PrizeDistributor(rules)
    payouts = pd.distribute_advance(
        round_label="QF",
        eliminated_balances={3: 100, 4: 100},   # 200m
        advancer_stats={
            1: {"net_goals": 3},   # weight = 4
            2: {"net_goals": -1},  # weight = 0
        },
    )
    by_mgr = {p.manager_id: p.amount for p in payouts}
    # Weights: 4 + 0 = 4; 1 gets 100% of pool, 2 gets 0
    # Wait: weight 0 means sum >0 still, 1 gets 200m + 80m = 280m, 2 gets 0 + 80m
    assert by_mgr[1] == 280
    assert by_mgr[2] == 80


def test_advance_zero_total_weight_no_pool_share():
    rules = default_rules()
    pd = PrizeDistributor(rules)
    # Edge case: all advancers had net_goals = -1 -> weights = 0, division skipped
    payouts = pd.distribute_advance(
        round_label="QF",
        eliminated_balances={3: 100},
        advancer_stats={
            1: {"net_goals": -1},
            2: {"net_goals": -1},
        },
    )
    by_mgr = {p.manager_id: p.amount for p in payouts}
    # No pool share, just extra
    assert by_mgr[1] == 80
    assert by_mgr[2] == 80


def test_qualify_payout_label():
    rules = default_rules()
    pd = PrizeDistributor(rules)
    payouts = pd.distribute_qualify(
        eliminated_balances={3: 100},
        qualifier_stats={1: {"points": 3, "goals_for": 2}},
    )
    assert payouts[0].bucket == "QUALIFY"
