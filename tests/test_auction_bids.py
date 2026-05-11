"""Tests for fmlwc.domain.auction.bids -- per-bid validation."""

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
    return rules, plr, elig, BidValidator(rules, mgr, plr, elig)


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


def test_rank_zero_invalid():
    rules, plr, elig, v = _setup()
    out = v.validate_one(
        RawBid(1, 1, amount=20, rank_in_position=0),
        balance_at_close=600, at=NOW,
    )
    assert out.status is BidStatus.INVALID_PER_BID
    assert "zero" in out.reason


def test_eligibility_block_for_others_after_auction():
    rules, plr, elig, v = _setup()
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


def test_duplicate_rank_within_position_reassigned():
    # First duplicate keeps its rank; later duplicates are reassigned to 100+.
    # Different positions don't affect each other.
    rules, plr, elig, v = _setup()
    plr.add(FakePlayer(id=4, name="P4", position=Position.F))
    bids = [
        RawBid(manager_id=1, player_id=1, amount=20, rank_in_position=1),  # F rank1 — first
        RawBid(manager_id=1, player_id=4, amount=15, rank_in_position=1),  # F rank1 — dup → 100
        RawBid(manager_id=1, player_id=2, amount=10, rank_in_position=1),  # M rank1 — independent
    ]
    outs = v.validate_submission(bids, balance_at_close=600, at=NOW)
    assert outs[0].status is BidStatus.VALID
    assert outs[0].bid.rank_in_position == 1      # first keeps original rank
    assert outs[1].status is BidStatus.VALID
    assert outs[1].bid.rank_in_position == 100    # duplicate reassigned
    assert outs[2].status is BidStatus.VALID
    assert outs[2].bid.rank_in_position == 1      # different position — unaffected


# --- conditional release tests -------------------------------------------

def _setup_cr():
    """Same as _setup but with conditional_release_enabled=True."""
    from tests.sample_rules import raw_dict
    from fmlwc.core import GameRules
    from tests.fakes import AcquisitionVia

    cfg = raw_dict()
    cfg["auction"]["conditional_release"] = {"enabled": True}
    rules = GameRules.from_dict(cfg)

    players = [
        FakePlayer(id=1, name="P1", position=Position.F),
        FakePlayer(id=2, name="P2", position=Position.M),
        FakePlayer(id=10, name="Owned", position=Position.D),
    ]
    mgr, plr, elig = make_repos(players=players)
    mgr.add_to_roster(1, 10, acquired_at=NOW, via=AcquisitionVia.AUCTION, price=20)
    return rules, mgr, plr, elig, BidValidator(rules, mgr, plr, elig)


def test_conditional_release_disabled_rejects_negative_rank():
    rules, plr, elig, v = _setup()  # conditional_release_enabled=False
    out = v.validate_one(
        RawBid(manager_id=1, player_id=1, amount=20, rank_in_position=-1),
        balance_at_close=600, at=NOW,
    )
    assert out.status is BidStatus.INVALID_PER_BID
    assert "disabled" in out.reason


def test_conditional_release_valid_for_owned_player():
    rules, mgr, plr, elig, v = _setup_cr()
    out = v.validate_one(
        RawBid(manager_id=1, player_id=10, amount=0, rank_in_position=-1),
        balance_at_close=600, at=NOW,
    )
    assert out.status is BidStatus.VALID


def test_conditional_release_rejects_unowned_player():
    rules, mgr, plr, elig, v = _setup_cr()
    out = v.validate_one(
        RawBid(manager_id=1, player_id=1, amount=0, rank_in_position=-1),
        balance_at_close=600, at=NOW,
    )
    assert out.status is BidStatus.INVALID_PER_BID
    assert "not on manager" in out.reason


def test_conditional_release_not_counted_in_rank_uniqueness():
    """Negative-rank (conditional release) bids do not collide with positive-rank bids."""
    rules, mgr, plr, elig, v = _setup_cr()
    bids = [
        RawBid(manager_id=1, player_id=1, amount=20, rank_in_position=1),
        RawBid(manager_id=1, player_id=10, amount=0, rank_in_position=-1),
    ]
    outs = v.validate_submission(bids, balance_at_close=600, at=NOW)
    assert outs[0].status is BidStatus.VALID
    assert outs[1].status is BidStatus.VALID


def test_conditional_release_duplicate_rank_invalidates_both():
    """rank -1 is a global slot; two conditional releases at -1 are invalid."""
    rules, mgr, plr, elig, v = _setup_cr()
    # add a second owned player
    from tests.fakes import AcquisitionVia
    plr.add(FakePlayer(id=11, name="Owned2", position=Position.F))
    mgr.add_to_roster(1, 11, acquired_at=NOW, via=AcquisitionVia.AUCTION, price=20)

    bids = [
        RawBid(manager_id=1, player_id=1, amount=20, rank_in_position=1),   # acquisition
        RawBid(manager_id=1, player_id=10, amount=0, rank_in_position=-1),  # cr slot -1
        RawBid(manager_id=1, player_id=11, amount=0, rank_in_position=-1),  # duplicate cr slot -1
    ]
    outs = v.validate_submission(bids, balance_at_close=600, at=NOW)
    assert outs[0].status is BidStatus.VALID
    assert outs[1].status is BidStatus.INVALID_PER_BID
    assert outs[2].status is BidStatus.INVALID_PER_BID
    assert "conditional release rank" in outs[1].reason
