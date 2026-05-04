"""Tests for fmlwc.domain.eligibility."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from fmlwc.core.enums import (
    AcquisitionVia,
    EligibilityRestriction,
    Position,
)
from fmlwc.core.exceptions import EligibilityError
from fmlwc.domain.eligibility import EligibilityService

from tests.fakes import FakeManager, FakePlayer, make_repos
from tests.sample_rules import default_rules


NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _setup():
    rules = default_rules()
    players = [FakePlayer(id=i, name=f"P{i}", position=Position.F) for i in range(1, 5)]
    mgr, plr, elig = make_repos(players=players)
    mgr.managers[1] = FakeManager(id=1, display_name="M1", balance=100)
    mgr.managers[2] = FakeManager(id=2, display_name="M2", balance=5)
    return rules, mgr, plr, elig, EligibilityService(rules, mgr, plr, elig)


def test_clean_check_passes():
    rules, mgr, plr, elig, svc = _setup()
    v = svc.check(1, 1, AcquisitionVia.FREE_SIGN, fee=10, at=NOW)
    assert v.allowed is True


def test_balance_insufficient_blocks_free_sign():
    rules, mgr, plr, elig, svc = _setup()
    v = svc.check(2, 1, AcquisitionVia.FREE_SIGN, fee=10, at=NOW)
    assert v.allowed is False
    assert "balance" in v.reason


def test_balance_not_checked_for_ko_pick():
    rules, mgr, plr, elig, svc = _setup()
    v = svc.check(2, 1, AcquisitionVia.KO_PICK, fee=0, at=NOW)
    assert v.allowed is True


def test_position_cap_blocks():
    rules, mgr, plr, elig, svc = _setup()
    # Default F cap = 4. Stuff manager 1's roster with 4 Fwds.
    for pid in [1, 2, 3, 4]:
        mgr.add_to_roster(1, pid, acquired_at=NOW)
    plr.add(FakePlayer(id=5, name="P5", position=Position.F))
    v = svc.check(1, 5, AcquisitionVia.FREE_SIGN, fee=10, at=NOW)
    assert v.allowed is False
    assert "position F cap" in v.reason


def test_total_roster_cap_blocks():
    rules, mgr, plr, elig, svc = _setup()
    # Default total = 20. Stuff with 20 entries (use varied positions to avoid pos cap).
    for pid in range(100, 120):
        plr.add(FakePlayer(id=pid, name=f"P{pid}", position=Position.D))
        mgr.add_to_roster(1, pid, acquired_at=NOW)
    plr.add(FakePlayer(id=200, name="P200", position=Position.F))
    v = svc.check(1, 200, AcquisitionVia.FREE_SIGN, fee=10, at=NOW)
    assert v.allowed is False
    assert "roster full" in v.reason


def test_auction_collusion_blocks_others():
    rules, mgr, plr, elig, svc = _setup()
    elig.add(
        manager_id=99,
        player_id=1,
        restriction=EligibilityRestriction.AUCTION_OTHERS_NEXT_WINDOW,
        valid_until=NOW + timedelta(days=7),
    )
    # Manager 1 (not the winner) is blocked
    v = svc.check(1, 1, AcquisitionVia.FREE_SIGN, fee=10, at=NOW)
    assert v.allowed is False
    assert "AUCTION_OTHERS_NEXT_WINDOW" in v.reason
    # Manager 99 (the winner) is allowed
    mgr.managers[99] = FakeManager(id=99, display_name="winner", balance=100)
    v2 = svc.check(99, 1, AcquisitionVia.FREE_SIGN, fee=10, at=NOW)
    assert v2.allowed is True


def test_release_lifetime_blocks_self():
    rules, mgr, plr, elig, svc = _setup()
    elig.add(
        manager_id=1,
        player_id=2,
        restriction=EligibilityRestriction.RELEASED_LIFETIME,
        valid_until=None,
    )
    v = svc.check(1, 2, AcquisitionVia.FREE_SIGN, fee=10, at=NOW)
    assert v.allowed is False
    assert "RELEASED_LIFETIME" in v.reason


def test_assert_allowed_raises_eligibility_error():
    rules, mgr, plr, elig, svc = _setup()
    with pytest.raises(EligibilityError, match="balance"):
        svc.assert_allowed(2, 1, AcquisitionVia.FREE_SIGN, fee=10, at=NOW)


def test_record_auction_block_writes_record():
    rules, mgr, plr, elig, svc = _setup()
    deadline = NOW + timedelta(days=7)
    svc.record_auction_block(except_winner_id=99, player_id=1, next_window_until=deadline)
    records = elig.list_for_player(1, NOW)
    assert any(r.manager_id == 99
               and r.restriction_type is EligibilityRestriction.AUCTION_OTHERS_NEXT_WINDOW
               for r in records)


def test_expired_record_does_not_block():
    rules, mgr, plr, elig, svc = _setup()
    elig.add(
        manager_id=99,
        player_id=1,
        restriction=EligibilityRestriction.AUCTION_OTHERS_NEXT_WINDOW,
        valid_until=NOW - timedelta(seconds=1),  # expired
    )
    v = svc.check(1, 1, AcquisitionVia.FREE_SIGN, fee=10, at=NOW)
    assert v.allowed is True
