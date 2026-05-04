"""Tests for fmlwc.domain.auction.bids — per-bid validation."""

from __future__ import annotations

from datetime import datetime, timezone

from fmlwc.core.enums import BidStatus, EligibilityRestriction, Position
from fmlwc.domain.auction.bids import BidValidator, RawBid

from tests.fakes import FakePlayer, make_repos
from tests.sample_rules import default_rules


NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _setup():
    rules = default_rules()
    players = [
        FakePlayer(id=1, name="P1", position=Position.F),
        FakePlayer(id=2, name="P2", position=Position.M),
        FakePlayer(id=3, name="P3", position=Position.D),
    ]
    mgr, plr, elig = make_repos(players=players)
    return rules, plr, elig, BidValidator(rules, plr, elig)


def test_valid_bid_passes():
    rules, plr, elig, v = _setup()
    out = v.validate_one(
        RawBid(manager_id=1, player_id=1, amount=20, rank_in_position=1),
        balance_at_close=600, at=NOW,
    )
    assert out.status is BidStatus.VALID


def test_amount_below_min_bid():
    rules, plr, elig, v = _setup()
    out = v.validate_one(
        RawBid(1, 1, amount=5, rank_in_position=1),
        balance_at_close=600, at=NOW,
    )
    assert out.status is BidStatus.INVALID_PER_BID
    assert "min_bid" in out.reason


def test_amount_above_balance():
    rules, plr, elig, v = _setup()
    out = v.validate_one(
        RawBid(1, 1, amount=10, rank_in_position=1),
        balance_at_close=5, at=NOW,
    )
    assert out.status is BidStatus.INVALID_PER_BID
    assert "exceeds balance" in out.reason


def test_rank_must_be_positive():
    rules, plr, elig, v = _setup()
    out = v.validate_one(
        RawBid(1, 1, amount=20, rank_in_position=0),
        balance_at_close=600, at=NOW,
    )
    assert out.status is BidStatus.INVALID_PER_BID
    assert "positive" in out.reason


def test_eligibility_block_for_others_after_auction():
    rules, plr, elig, v = _setup()
    # Manager 99 won player 1 in a previous auction; manager 1 now blocked.
    elig.add(
        manager_id=99, player_id=1,
        restriction=EligibilityRestriction.AUCTION_OTHERS_NEXT_WINDOW,
        valid_until=None,
    )
    out = v.validate_one(
        RawBid(manager_id=1, player_id=1, amount=20, rank_in_position=1),
        balance_at_close=600, at=NOW,
    )
    assert out.status is BidStatus.INVALID_INELIGIBLE


def test_eligibility_block_does_not_affect_winner():
    """The same record holds the winner (manager 99); 99 is still allowed."""
    rules, plr, elig, v = _setup()
    elig.add(
        manager_id=99, player_id=1,
        restriction=EligibilityRestriction.AUCTION_OTHERS_NEXT_WINDOW,
        valid_until=None,
    )
    out = v.validate_one(
        RawBid(manager_id=99, player_id=1, amount=20, rank_in_position=1),
        balance_at_close=600, at=NOW,
    )
    assert out.status is BidStatus.VALID


def test_lifetime_release_block_self():
    rules, plr, elig, v = _setup()
    elig.add(
        manager_id=1, player_id=2,
        restriction=EligibilityRestriction.RELEASED_LIFETIME,
        valid_until=None,
    )
    out = v.validate_one(
        RawBid(manager_id=1, player_id=2, amount=20, rank_in_position=1),
        balance_at_close=600, at=NOW,
    )
    assert out.status is BidStatus.INVALID_INELIGIBLE


def test_duplicate_rank_within_position_invalidates_both():
    rules, plr, elig, v = _setup()
    # players 1 and (new) 4 are both Fwds with rank 1.
    plr.add(FakePlayer(id=4, name="P4", position=Position.F))
    bids = [
        RawBid(manager_id=1, player_id=1, amount=20, rank_in_position=1),
        RawBid(manager_id=1, player_id=4, amount=15, rank_in_position=1),
        RawBid(manager_id=1, player_id=2, amount=10, rank_in_position=1),  # mid, OK
    ]
    outs = v.validate_submission(bids, balance_at_close=600, at=NOW)
    assert outs[0].status is BidStatus.INVALID_PER_BID
    assert outs[1].status is BidStatus.INVALID_PER_BID
    assert "duplicate rank" in outs[0].reason
    assert outs[2].status is BidStatus.VALID  # different position, fine
