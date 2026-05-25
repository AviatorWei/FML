"""Tests for fmlwc.domain.transfer.free_sign.FreeSignService."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from fmlwc.core.enums import AcquisitionVia, EligibilityRestriction, Position
from fmlwc.core.exceptions import EligibilityError, TransferError
from fmlwc.domain.eligibility import EligibilityService
from fmlwc.domain.transfer.free_sign import FreeSignResult, FreeSignService

from tests.fakes import (
    FakeEligibilityRecord,
    FakeManager,
    FakeFreeSignRepo,
    FakePlayer,
    FakeTransferWindow,
    make_repos,
)
from tests.sample_rules import default_rules


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WINDOW_OPEN  = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)
WINDOW_CLOSE = datetime(2026, 6, 7, 12, 0, 0, tzinfo=timezone.utc)
PERIOD = 3600  # 1-hour cooldown for tests
SIGN_AT = datetime(2026, 6, 4, 10, 0, 0, tzinfo=timezone.utc)


def _make_window(**kw) -> FakeTransferWindow:
    defaults = dict(
        id=1,
        opens_at=WINDOW_OPEN,
        closes_at=WINDOW_CLOSE,
        free_sign_period_seconds=PERIOD,
    )
    defaults.update(kw)
    return FakeTransferWindow(**defaults)


def _setup(
    balance: int = 100,
    roster_size: int = 0,
    window: FakeTransferWindow | None = None,
):
    """Build a minimal service with one manager and one free-agent player."""
    rules = default_rules()
    player = FakePlayer(id=42, name="Neuer", position=Position.G)
    manager = FakeManager(id=1, display_name="GER", balance=balance)

    mgr_repo, plr_repo, elig_repo = make_repos(
        managers=[manager], players=[player]
    )

    # Optionally pre-fill the roster
    for i in range(roster_size):
        extra = FakePlayer(id=100 + i, name=f"Extra{i}", position=Position.M)
        plr_repo.add(extra)
        mgr_repo.add_to_roster(1, 100 + i, acquired_at=SIGN_AT,
                               via=AcquisitionVia.AUCTION, price=10)

    fs_repo = FakeFreeSignRepo()
    trn_repo = mgr_repo._players and None  # unused; build directly
    from tests.fakes import FakeTransferRepo
    trn_repo = FakeTransferRepo()
    if window is not None:
        trn_repo.windows.append(window)
    else:
        trn_repo.windows.append(_make_window())

    elig_svc = EligibilityService(rules, mgr_repo, plr_repo, elig_repo)

    svc = FreeSignService(
        rules=rules,
        managers=mgr_repo,
        players=plr_repo,
        transfers=trn_repo,
        free_signs=fs_repo,
        eligibility=elig_svc,
    )
    return svc, mgr_repo, plr_repo, elig_repo, fs_repo


# ---------------------------------------------------------------------------
# propose — happy path
# ---------------------------------------------------------------------------

def test_propose_happy_path():
    svc, mgr_repo, _, _, fs_repo = _setup()
    fid = svc.propose(1, 42, SIGN_AT)
    assert fid == 1
    fs = fs_repo.get(fid)
    assert fs.manager_id == 1
    assert fs.player_id == 42
    assert fs.fee == 10
    assert not fs.revoked
    assert not fs.effective


def test_propose_returns_result_on_try():
    svc, _, _, _, _ = _setup()
    result = svc.try_propose(1, 42, SIGN_AT)
    assert isinstance(result, FreeSignResult)
    assert result.success
    assert result.free_sign_id == 1
    assert result.error is None


# ---------------------------------------------------------------------------
# propose — validation failures
# ---------------------------------------------------------------------------

def test_propose_no_window_raises():
    svc, _, _, _, _ = _setup(window=FakeTransferWindow(
        id=1,
        opens_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        closes_at=datetime(2026, 7, 7, tzinfo=timezone.utc),
        free_sign_period_seconds=PERIOD,
    ))
    with pytest.raises(TransferError, match="no transfer window"):
        svc.propose(1, 42, SIGN_AT)


def test_propose_player_not_free_agent_raises():
    svc, _, plr_repo, _, _ = _setup()
    plr_repo.mark_signed(42)
    with pytest.raises(TransferError, match="not a free agent"):
        svc.propose(1, 42, SIGN_AT)


def test_propose_balance_too_low_raises():
    svc, _, _, _, _ = _setup(balance=5)
    with pytest.raises(EligibilityError, match="balance"):
        svc.propose(1, 42, SIGN_AT)


def test_propose_roster_full_raises():
    rules = default_rules()
    svc, mgr_repo, plr_repo, _, _ = _setup(roster_size=rules.roster.total_cap)
    with pytest.raises(EligibilityError, match="roster full"):
        svc.propose(1, 42, SIGN_AT)


def test_propose_eligibility_block_raises():
    svc, _, _, elig_repo, _ = _setup()
    elig_repo.add(
        manager_id=2,          # manager 2 won the player
        player_id=42,
        restriction=EligibilityRestriction.FREE_SIGN_SAME_WINDOW,
        valid_until=WINDOW_CLOSE,
        reason="test block",
    )
    with pytest.raises(EligibilityError, match="FREE_SIGN_SAME_WINDOW"):
        svc.propose(1, 42, SIGN_AT)


def test_propose_try_returns_failure_result_on_error():
    svc, _, _, _, _ = _setup(balance=0)
    result = svc.try_propose(1, 42, SIGN_AT)
    assert not result.success
    assert result.free_sign_id is None
    assert result.error is not None


# ---------------------------------------------------------------------------
# cooldown (rule 三.6)
# ---------------------------------------------------------------------------

def test_propose_blocked_by_cooldown():
    svc, _, _, _, fs_repo = _setup()
    # First sign succeeds
    svc.propose(1, 42, SIGN_AT)
    # Second sign within the period (30 min later) is blocked
    later = SIGN_AT + timedelta(minutes=30)
    # Need a different free player
    from tests.fakes import FakePlayer
    svc.players.add(FakePlayer(id=99, name="Other", position=Position.M))
    with pytest.raises(TransferError, match="cooldown"):
        svc.propose(1, 99, later)


def test_propose_allowed_after_cooldown_expires():
    svc, _, _, _, fs_repo = _setup()
    fid1 = svc.propose(1, 42, SIGN_AT)
    # Manually mark effective so cooldown is based on real effective sign
    fs_repo.mark_effective(fid1)
    # Now propose again after period has elapsed
    after_period = SIGN_AT + timedelta(seconds=PERIOD + 1)
    from tests.fakes import FakePlayer
    svc.players.add(FakePlayer(id=99, name="Other", position=Position.M))
    fid2 = svc.propose(1, 99, after_period)
    assert fid2 == 2


def test_revoked_sign_does_not_block_cooldown():
    svc, _, _, _, fs_repo = _setup()
    fid = svc.propose(1, 42, SIGN_AT)
    # Revoke it immediately
    svc.revoke(fid, SIGN_AT + timedelta(minutes=5))
    # Should be able to propose again immediately (revoked sign skipped in cooldown)
    from tests.fakes import FakePlayer
    svc.players.add(FakePlayer(id=99, name="Other", position=Position.M))
    fid2 = svc.propose(1, 99, SIGN_AT + timedelta(minutes=6))
    assert fid2 == 2


# ---------------------------------------------------------------------------
# revoke
# ---------------------------------------------------------------------------

def test_revoke_within_window_succeeds():
    svc, _, _, _, fs_repo = _setup()
    fid = svc.propose(1, 42, SIGN_AT)
    svc.revoke(fid, SIGN_AT + timedelta(minutes=10))
    assert fs_repo.get(fid).revoked is True


def test_revoke_after_window_raises():
    svc, _, _, _, _ = _setup()
    fid = svc.propose(1, 42, SIGN_AT)
    too_late = SIGN_AT + timedelta(seconds=default_rules().transfer.revoke_window_seconds + 1)
    with pytest.raises(TransferError, match="revoke window expired"):
        svc.revoke(fid, too_late)


def test_revoke_already_revoked_raises():
    svc, _, _, _, _ = _setup()
    fid = svc.propose(1, 42, SIGN_AT)
    svc.revoke(fid, SIGN_AT + timedelta(minutes=5))
    with pytest.raises(TransferError, match="already revoked"):
        svc.revoke(fid, SIGN_AT + timedelta(minutes=6))


def test_revoke_already_effective_raises():
    svc, _, _, _, fs_repo = _setup()
    fid = svc.propose(1, 42, SIGN_AT)
    fs_repo.mark_effective(fid)
    with pytest.raises(TransferError, match="already effective"):
        svc.revoke(fid, SIGN_AT + timedelta(minutes=5))


def test_try_revoke_returns_result():
    svc, _, _, _, _ = _setup()
    fid = svc.propose(1, 42, SIGN_AT)
    result = svc.try_revoke(fid, SIGN_AT + timedelta(minutes=5))
    assert result.success
    assert result.free_sign_id == fid


# ---------------------------------------------------------------------------
# commit_due
# ---------------------------------------------------------------------------

def test_commit_due_charges_fee_and_adds_to_roster():
    svc, mgr_repo, _, _, fs_repo = _setup(balance=100)
    fid = svc.propose(1, 42, SIGN_AT)
    # Advance past revoke window
    commit_at = SIGN_AT + timedelta(seconds=default_rules().transfer.revoke_window_seconds + 1)
    count = svc.commit_due(commit_at)
    assert count == 1
    assert fs_repo.get(fid).effective is True
    assert mgr_repo.get(1).balance == 90  # 100 - 10
    roster = mgr_repo.list_roster(1)
    assert any(e.player_id == 42 for e in roster)


def test_commit_due_skips_signs_still_in_revoke_window():
    svc, _, _, _, fs_repo = _setup()
    svc.propose(1, 42, SIGN_AT)
    # Still within revoke window
    commit_at = SIGN_AT + timedelta(minutes=5)
    count = svc.commit_due(commit_at)
    assert count == 0
    assert fs_repo.get(1).effective is False


def test_commit_due_records_eligibility_block():
    svc, _, _, elig_repo, _ = _setup()
    svc.propose(1, 42, SIGN_AT)
    commit_at = SIGN_AT + timedelta(seconds=default_rules().transfer.revoke_window_seconds + 1)
    svc.commit_due(commit_at)
    records = elig_repo.list_for_player(42, SIGN_AT)
    assert any(
        r.restriction_type == EligibilityRestriction.FREE_SIGN_SAME_WINDOW
        for r in records
    )


def test_commit_due_no_window_returns_zero():
    svc, _, _, _, _ = _setup(window=FakeTransferWindow(
        id=1,
        opens_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        closes_at=datetime(2026, 7, 7, tzinfo=timezone.utc),
        free_sign_period_seconds=PERIOD,
    ))
    count = svc.commit_due(SIGN_AT)
    assert count == 0


def test_commit_due_skips_revoked():
    svc, mgr_repo, _, _, fs_repo = _setup()
    fid = svc.propose(1, 42, SIGN_AT)
    svc.revoke(fid, SIGN_AT + timedelta(minutes=5))
    commit_at = SIGN_AT + timedelta(seconds=default_rules().transfer.revoke_window_seconds + 1)
    count = svc.commit_due(commit_at)
    assert count == 0
    assert mgr_repo.get(1).balance == 100  # unchanged
