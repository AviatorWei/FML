"""Tests for fmlwc.domain.transfer.dismiss.DismissService."""

from __future__ import annotations

from datetime import datetime

import pytest

from fmlwc.core.enums import AcquisitionVia, EligibilityRestriction, Position
from fmlwc.domain.eligibility import EligibilityService
from fmlwc.domain.transfer.dismiss import DismissService
from tests.fakes import (
    FakeDismissalRepo,
    FakeManager,
    FakePlayer,
    make_repos,
)
from tests.sample_rules import default_rules as make_rules

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2024, 6, 15, 12, 0, 0)


def _make_service(mgr_repo, plr_repo, elig_repo):
    rules = make_rules()
    elig_svc = EligibilityService(rules, mgr_repo, plr_repo, elig_repo)
    dismissals = FakeDismissalRepo()
    svc = DismissService(rules, mgr_repo, dismissals, elig_svc)
    return svc, dismissals, elig_repo


def _setup(balance: int = 500):
    mgr_repo, plr_repo, elig_repo = make_repos(
        managers=[FakeManager(id=1, display_name="MGR1", balance=balance)],
        players=[FakePlayer(id=10, name="Havertz", position=Position.M)],
    )
    mgr_repo.add_to_roster(
        1, 10,
        acquired_at=datetime(2024, 1, 1),
        via=AcquisitionVia.AUCTION,
        price=50,
    )
    return mgr_repo, plr_repo, elig_repo


# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------

class TestDismissHappyPath:
    def test_returns_dismissal_id(self):
        mgr_repo, plr_repo, elig_repo = _setup()
        svc, dismissals, _ = _make_service(mgr_repo, plr_repo, elig_repo)
        did = svc.dismiss(1, 10, NOW)
        assert did == 1

    def test_roster_entry_released(self):
        mgr_repo, plr_repo, elig_repo = _setup()
        svc, _, _ = _make_service(mgr_repo, plr_repo, elig_repo)
        svc.dismiss(1, 10, NOW)
        assert mgr_repo.list_roster(1) == []

    def test_roster_released_at_timestamp(self):
        mgr_repo, plr_repo, elig_repo = _setup()
        svc, _, _ = _make_service(mgr_repo, plr_repo, elig_repo)
        svc.dismiss(1, 10, NOW)
        entry = mgr_repo.rosters[1][0]
        assert entry.released_at == NOW

    def test_audit_record_persisted(self):
        mgr_repo, plr_repo, elig_repo = _setup()
        svc, dismissals, _ = _make_service(mgr_repo, plr_repo, elig_repo)
        svc.dismiss(1, 10, NOW, reason="conduct")
        recs = dismissals.for_player(10)
        assert len(recs) == 1
        assert recs[0].manager_id == 1
        assert recs[0].dismissed_at == NOW
        assert recs[0].reason == "conduct"

    def test_audit_reason_optional(self):
        mgr_repo, plr_repo, elig_repo = _setup()
        svc, dismissals, _ = _make_service(mgr_repo, plr_repo, elig_repo)
        svc.dismiss(1, 10, NOW)
        assert dismissals.for_player(10)[0].reason is None


# ---------------------------------------------------------------------------
# Eligibility block
# ---------------------------------------------------------------------------

class TestDismissEligibilityBlock:
    def test_dismissed_lifetime_restriction_added(self):
        mgr_repo, plr_repo, elig_repo = _setup()
        svc, _, _ = _make_service(mgr_repo, plr_repo, elig_repo)
        svc.dismiss(1, 10, NOW)
        records = elig_repo.list_for_player(10, NOW)
        types = [r.restriction_type for r in records]
        assert EligibilityRestriction.DISMISSED_LIFETIME in types

    def test_restriction_has_no_expiry(self):
        mgr_repo, plr_repo, elig_repo = _setup()
        svc, _, _ = _make_service(mgr_repo, plr_repo, elig_repo)
        svc.dismiss(1, 10, NOW)
        rec = next(
            r for r in elig_repo.records
            if r.restriction_type is EligibilityRestriction.DISMISSED_LIFETIME
        )
        assert rec.valid_until is None

    def test_check_blocks_manager_from_resigning(self):
        mgr_repo, plr_repo, elig_repo = _setup()
        svc, _, _ = _make_service(mgr_repo, plr_repo, elig_repo)
        svc.dismiss(1, 10, NOW)

        rules = make_rules()
        elig_svc = EligibilityService(rules, mgr_repo, plr_repo, elig_repo)
        verdict = elig_svc.check(1, 10, AcquisitionVia.FREE_SIGN, fee=10, at=NOW)
        assert not verdict.allowed
        assert "DISMISSED_LIFETIME" in verdict.reason

    def test_check_does_not_block_other_managers(self):
        mgr_repo, plr_repo, elig_repo = make_repos(
            managers=[
                FakeManager(id=1, display_name="MGR1", balance=500),
                FakeManager(id=2, display_name="MGR2", balance=500),
            ],
            players=[FakePlayer(id=10, name="Havertz", position=Position.M)],
        )
        mgr_repo.add_to_roster(
            1, 10, acquired_at=datetime(2024, 1, 1),
            via=AcquisitionVia.AUCTION, price=50,
        )
        svc, _, _ = _make_service(mgr_repo, plr_repo, elig_repo)
        svc.dismiss(1, 10, NOW)

        rules = make_rules()
        elig_svc = EligibilityService(rules, mgr_repo, plr_repo, elig_repo)
        verdict = elig_svc.check(2, 10, AcquisitionVia.FREE_SIGN, fee=10, at=NOW)
        assert verdict.allowed


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestDismissErrors:
    def test_raises_if_player_not_on_roster(self):
        mgr_repo, plr_repo, elig_repo = make_repos(
            managers=[FakeManager(id=1, display_name="MGR1", balance=500)],
            players=[FakePlayer(id=10, name="Havertz", position=Position.M)],
        )
        svc, _, _ = _make_service(mgr_repo, plr_repo, elig_repo)
        with pytest.raises(KeyError):
            svc.dismiss(1, 10, NOW)

    def test_raises_if_already_released(self):
        mgr_repo, plr_repo, elig_repo = _setup()
        svc, _, _ = _make_service(mgr_repo, plr_repo, elig_repo)
        svc.dismiss(1, 10, NOW)
        with pytest.raises(KeyError):
            svc.dismiss(1, 10, NOW)


# ---------------------------------------------------------------------------
# History preservation
# ---------------------------------------------------------------------------

class TestDismissHistoryPreservation:
    def test_player_appears_as_free_agent_after_dismiss(self):
        """query_player_list relies on released_at IS NULL — dismissed players
        must show as unowned."""
        from fmlwc.io.player_list_exporter import PlayerListRow

        mgr_repo, plr_repo, elig_repo = _setup()
        svc, _, _ = _make_service(mgr_repo, plr_repo, elig_repo)
        svc.dismiss(1, 10, NOW)

        active = mgr_repo.list_roster(1)
        assert active == []

        # The roster entry still exists in history (just with released_at set)
        all_entries = mgr_repo.rosters.get(1, [])
        assert len(all_entries) == 1
        assert all_entries[0].released_at == NOW
