"""Tests for fmlwc.domain.auction.tiebreaker."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from fmlwc.domain.auction.tiebreaker import (
    AmountRankTimeDraw,
    CandidateBid,
    deterministic_draw_seed,
    get_strategy,
)


def _bid(bid_id, mgr, amount, rank, t_offset_sec=0, draw=0):
    return CandidateBid(
        bid_id=bid_id,
        manager_id=mgr,
        amount=amount,
        rank_in_position=rank,
        submission_received_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc).replace(
            second=t_offset_sec
        ),
        draw_seed=draw,
    )


def test_higher_amount_wins():
    strat = AmountRankTimeDraw()
    a = _bid(1, 10, amount=20, rank=1)
    b = _bid(2, 11, amount=30, rank=1)
    assert strat.select_winner([a, b]).manager_id == 11


def test_tied_amount_lower_rank_wins():
    strat = AmountRankTimeDraw()
    a = _bid(1, 10, amount=20, rank=2)
    b = _bid(2, 11, amount=20, rank=1)
    assert strat.select_winner([a, b]).manager_id == 11


def test_tied_amount_and_rank_earlier_time_wins():
    strat = AmountRankTimeDraw()
    a = _bid(1, 10, amount=20, rank=1, t_offset_sec=30)
    b = _bid(2, 11, amount=20, rank=1, t_offset_sec=10)
    assert strat.select_winner([a, b]).manager_id == 11


def test_full_tie_breaks_on_draw_seed():
    strat = AmountRankTimeDraw()
    a = _bid(1, 10, amount=20, rank=1, t_offset_sec=10, draw=999)
    b = _bid(2, 11, amount=20, rank=1, t_offset_sec=10, draw=42)
    assert strat.select_winner([a, b]).manager_id == 11


def test_single_candidate():
    strat = AmountRankTimeDraw()
    a = _bid(1, 10, 10, 1)
    assert strat.select_winner([a]) is a


def test_empty_candidates_raises():
    strat = AmountRankTimeDraw()
    with pytest.raises(ValueError):
        strat.select_winner([])


def test_factory_returns_default():
    assert isinstance(get_strategy("amount_rank_time_draw"), AmountRankTimeDraw)


def test_factory_unknown_raises():
    with pytest.raises(ValueError, match="unknown tiebreaker"):
        get_strategy("nope")


def test_draw_seed_deterministic():
    assert deterministic_draw_seed(1, 100, 5) == deterministic_draw_seed(1, 100, 5)
    assert deterministic_draw_seed(1, 100, 5) != deterministic_draw_seed(1, 100, 6)
