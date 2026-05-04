"""Tests for fmlwc.domain.auction.service -- AuctionService end-to-end."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from fmlwc.core.enums import AcquisitionVia, AuctionRoundStatus, BidStatus, Position
from fmlwc.domain.auction.bids import RawBid
from fmlwc.domain.auction.service import AuctionService, BidAnnouncementRow
from fmlwc.domain.eligibility import EligibilityService
from fmlwc.io.announcement import AuctionAnnouncementFormatter

from tests.fakes import (
    FakeAuctionRound,
    FakeManager,
    FakePlayer,
    FakeTransferWindow,
    make_auction_repos,
)
from tests.sample_rules import default_rules, raw_dict
from fmlwc.core import GameRules

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ROUND_ID = 1
T0 = datetime(2026, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 6, 1, 11, 0, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 6, 2, 0, 0, 0, tzinfo=timezone.utc)  # round close
NEXT_W_OPEN  = datetime(2026, 6, 3, 0, 0, 0, tzinfo=timezone.utc)
NEXT_W_CLOSE = datetime(2026, 6, 7, 0, 0, 0, tzinfo=timezone.utc)


def _make_service(rules=None, managers=None, players=None, with_cr=False):
    if with_cr:
        cfg = raw_dict()
        cfg["auction"]["conditional_release"] = {"enabled": True}
        rules = GameRules.from_dict(cfg)
    else:
        rules = rules or default_rules()

    mgr_r, plr_r, elig_r, sub_r, bid_r, rnd_r, res_r, trn_r = make_auction_repos(
        managers=managers, players=players
    )
    mgr_r.attach_player_repo(plr_r)

    # Add a transfer window so eligibility blocks have an expiry
    trn_r.windows.append(FakeTransferWindow(
        id=1, opens_at=NEXT_W_OPEN, closes_at=NEXT_W_CLOSE
    ))

    # Register the auction round
    rnd_r.add(FakeAuctionRound(
        id=ROUND_ID, index=1,
        opens_at=datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc),
        closes_at=T2,
    ))

    elig_svc = EligibilityService(rules, mgr_r, plr_r, elig_r)
    svc = AuctionService(
        rules=rules,
        managers=mgr_r,
        players=plr_r,
        bids=bid_r,
        submissions=sub_r,
        rounds=rnd_r,
        results=res_r,
        eligibility_repo=elig_r,
        eligibility_service=elig_svc,
        transfer_repo=trn_r,
    )
    return svc, mgr_r, plr_r, elig_r, sub_r, bid_r, rnd_r, res_r


def _setup_two_players():
    """Two managers, two players — ready for standard auction tests."""
    managers = [
        FakeManager(id=1, display_name="ENG", balance=600),
        FakeManager(id=2, display_name="GER", balance=600),
    ]
    players = [
        FakePlayer(id=10, name="Kane", position=Position.F, real_team="ENG"),
        FakePlayer(id=20, name="Musiala", position=Position.M, real_team="GER"),
    ]
    return _make_service(managers=managers, players=players)


# ---------------------------------------------------------------------------
# open_round / close_round
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_open_round_sets_status(self):
        svc, *_, rnd_r, _ = _setup_two_players()
        svc.open_round(ROUND_ID)
        assert rnd_r.get(ROUND_ID).status is AuctionRoundStatus.OPEN

    def test_close_round_sets_resolving(self):
        svc, *_, rnd_r, _ = _setup_two_players()
        svc.close_round(ROUND_ID, at=T2)
        assert rnd_r.get(ROUND_ID).status is AuctionRoundStatus.RESOLVING


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------

class TestSubmit:
    def test_returns_submission_id(self):
        svc, *rest = _setup_two_players()
        sub_id = svc.submit(ROUND_ID, 1, [RawBid(1, 10, 100, 1)], T0)
        assert isinstance(sub_id, int)

    def test_bids_persisted_with_valid_status(self):
        svc, _, _, _, sub_r, bid_r, *_ = _setup_two_players()
        sub_id = svc.submit(ROUND_ID, 1, [RawBid(1, 10, 100, 1)], T0)
        bids = bid_r.for_submission(sub_id)
        assert len(bids) == 1
        assert bids[0].status is BidStatus.VALID

    def test_invalid_bid_stored_with_invalid_status(self):
        """Bid below min_bid (10m) → INVALID_PER_BID."""
        svc, _, _, _, sub_r, bid_r, *_ = _setup_two_players()
        sub_id = svc.submit(ROUND_ID, 1, [RawBid(1, 10, 5, 1)], T0)
        bids = bid_r.for_submission(sub_id)
        assert bids[0].status is BidStatus.INVALID_PER_BID

    def test_resubmit_overwrites(self):
        """Second submit for same (round, manager) replaces the first."""
        svc, _, _, _, sub_r, bid_r, *_ = _setup_two_players()
        svc.submit(ROUND_ID, 1, [RawBid(1, 10, 100, 1)], T0)
        sub_id2 = svc.submit(ROUND_ID, 1, [RawBid(1, 10, 150, 1)], T1)
        subs = sub_r.for_round(ROUND_ID)
        assert len(subs) == 1  # still only one submission
        bids = bid_r.for_submission(sub_id2)
        assert bids[-1].amount == 150

    def test_source_file_stored(self):
        svc, _, _, _, sub_r, *_ = _setup_two_players()
        sub_id = svc.submit(ROUND_ID, 1, [RawBid(1, 10, 100, 1)], T0,
                            source_file="FME_2024_Bid1_ENG.xlsx")
        assert sub_r.get(sub_id).source_file == "FME_2024_Bid1_ENG.xlsx"


# ---------------------------------------------------------------------------
# resolve — basic winner selection
# ---------------------------------------------------------------------------

class TestResolve:
    def test_single_bidder_wins(self):
        svc, mgr_r, *_ = _setup_two_players()
        svc.submit(ROUND_ID, 1, [RawBid(1, 10, 100, 1)], T0)
        res = svc.resolve(ROUND_ID, T2)
        assert len(res.awards) == 1
        player_id, winner_id, price = res.awards[0]
        assert player_id == 10
        assert winner_id == 1
        assert price == 100

    def test_winner_balance_deducted(self):
        svc, mgr_r, *_ = _setup_two_players()
        svc.submit(ROUND_ID, 1, [RawBid(1, 10, 100, 1)], T0)
        svc.resolve(ROUND_ID, T2)
        assert mgr_r.get(1).balance == 500   # 600 - 100

    def test_winner_added_to_roster(self):
        svc, mgr_r, *_ = _setup_two_players()
        svc.submit(ROUND_ID, 1, [RawBid(1, 10, 100, 1)], T0)
        svc.resolve(ROUND_ID, T2)
        roster = mgr_r.list_roster(1)
        assert any(e.player_id == 10 for e in roster)

    def test_higher_bid_wins_over_lower(self):
        svc, mgr_r, *_ = _setup_two_players()
        svc.submit(ROUND_ID, 1, [RawBid(1, 10, 200, 1)], T0)
        svc.submit(ROUND_ID, 2, [RawBid(2, 10, 150, 1)], T1)
        res = svc.resolve(ROUND_ID, T2)
        _, winner_id, price = res.awards[0]
        assert winner_id == 1
        assert price == 200

    def test_losing_bid_marked_lost(self):
        svc, _, _, _, _, bid_r, *_ = _setup_two_players()
        svc.submit(ROUND_ID, 1, [RawBid(1, 10, 200, 1)], T0)
        svc.submit(ROUND_ID, 2, [RawBid(2, 10, 150, 1)], T1)
        svc.resolve(ROUND_ID, T2)
        bids = bid_r.for_round(ROUND_ID)
        statuses = {b.amount: b.status for b in bids}
        assert statuses[200] is BidStatus.AWARDED
        assert statuses[150] is BidStatus.LOST

    def test_no_bids_no_awards(self):
        svc, *_ = _setup_two_players()
        res = svc.resolve(ROUND_ID, T2)
        assert res.awards == []
        assert res.total_spend == 0

    def test_round_closed_after_resolve(self):
        svc, *_, rnd_r, _ = _setup_two_players()
        svc.resolve(ROUND_ID, T2)
        assert rnd_r.get(ROUND_ID).status is AuctionRoundStatus.CLOSED

    def test_result_row_created(self):
        svc, _, _, _, _, _, _, res_r = _setup_two_players()
        svc.submit(ROUND_ID, 1, [RawBid(1, 10, 100, 1)], T0)
        svc.resolve(ROUND_ID, T2)
        results = res_r.for_round(ROUND_ID)
        assert len(results) == 1
        assert results[0].winner_manager_id == 1
        assert results[0].price == 100

    def test_invalidated_count_includes_cascade_drops(self):
        """Manager 1 bids 2 Fs but F cap = 4 and they already have 3 → 1 drop."""
        managers = [FakeManager(id=1, display_name="ENG", balance=600)]
        players = [
            FakePlayer(id=10, name="Kane",    position=Position.F, real_team="ENG"),
            FakePlayer(id=11, name="Watkins", position=Position.F, real_team="ENG"),
        ]
        svc, mgr_r, *_ = _make_service(managers=managers, players=players)
        # Pre-fill roster so F count = 3 (cap = 4)
        for pid in [101, 102, 103]:
            mgr_r.rosters.setdefault(1, [])
            from tests.fakes import FakeRosterEntry
            mgr_r.rosters[1].append(
                FakeRosterEntry(1, pid, T0, AcquisitionVia.AUCTION, 10)
            )
        mgr_r._players.players[101] = FakePlayer(101, "A", Position.F)
        mgr_r._players.players[102] = FakePlayer(102, "B", Position.F)
        mgr_r._players.players[103] = FakePlayer(103, "C", Position.F)

        # 2 F bids: cap = 4, current = 3 → only 1 can fit → 1 dropped
        svc.submit(ROUND_ID, 1, [
            RawBid(1, 10, 200, 1),
            RawBid(1, 11, 100, 2),
        ], T0)
        res = svc.resolve(ROUND_ID, T2)
        assert res.invalidated == 1

    def test_total_spend_correct(self):
        managers = [
            FakeManager(id=1, display_name="ENG", balance=600),
            FakeManager(id=2, display_name="GER", balance=600),
        ]
        players = [
            FakePlayer(id=10, name="Kane",    position=Position.F, real_team="ENG"),
            FakePlayer(id=20, name="Musiala", position=Position.M, real_team="GER"),
        ]
        svc, *_ = _make_service(managers=managers, players=players)
        svc.submit(ROUND_ID, 1, [RawBid(1, 10, 100, 1)], T0)
        svc.submit(ROUND_ID, 2, [RawBid(2, 20, 80, 1)], T1)
        res = svc.resolve(ROUND_ID, T2)
        assert res.total_spend == 180


# ---------------------------------------------------------------------------
# resolve — tiebreaker: higher rank wins when amount ties
# ---------------------------------------------------------------------------

class TestTiebreaker:
    def test_same_amount_lower_rank_wins(self):
        """Equal bid: manager 1 submits rank 1, manager 2 submits rank 2 → mgr 1 wins."""
        svc, *_ = _setup_two_players()
        svc.submit(ROUND_ID, 1, [RawBid(1, 10, 100, 1)], T0)
        svc.submit(ROUND_ID, 2, [RawBid(2, 10, 100, 2)], T1)
        res = svc.resolve(ROUND_ID, T2)
        _, winner_id, _ = res.awards[0]
        assert winner_id == 1

    def test_same_amount_same_rank_earlier_submission_wins(self):
        """Equal amount and rank: earlier received_at wins."""
        svc, *_ = _setup_two_players()
        svc.submit(ROUND_ID, 1, [RawBid(1, 10, 100, 1)], T1)   # later
        svc.submit(ROUND_ID, 2, [RawBid(2, 10, 100, 1)], T0)   # earlier
        res = svc.resolve(ROUND_ID, T2)
        _, winner_id, _ = res.awards[0]
        assert winner_id == 2


# ---------------------------------------------------------------------------
# resolve — eligibility blocks
# ---------------------------------------------------------------------------

class TestEligibilityBlocks:
    def test_non_winners_blocked_after_resolve(self):
        svc, _, _, elig_r, *_ = _setup_two_players()
        svc.submit(ROUND_ID, 1, [RawBid(1, 10, 200, 1)], T0)  # wins
        svc.submit(ROUND_ID, 2, [RawBid(2, 10, 100, 1)], T1)  # loses
        svc.resolve(ROUND_ID, T2)
        # manager 2 should be blocked for player 10
        records = elig_r.list_for_player(10, T2)
        # record is keyed to the winner (manager 1) to identify the holder
        assert any(r.manager_id == 1 for r in records)

    def test_winner_not_blocked_for_own_player(self):
        """The eligibility block tags the winner's id; the winner themselves can still sign."""
        svc, _, _, elig_r, *_ = _setup_two_players()
        svc.submit(ROUND_ID, 1, [RawBid(1, 10, 200, 1)], T0)
        svc.resolve(ROUND_ID, T2)
        records = elig_r.list_for_player(10, T2)
        # Only one record: the block tagged to winner's id (meaning others are blocked)
        assert len(records) == 1
        assert records[0].manager_id == 1


# ---------------------------------------------------------------------------
# resolve — conditional releases
# ---------------------------------------------------------------------------

class TestConditionalReleases:
    def _setup_cr(self):
        managers = [
            FakeManager(id=1, display_name="ENG", balance=600),
        ]
        players = [
            FakePlayer(id=10, name="Kane",    position=Position.F, real_team="ENG"),
            FakePlayer(id=50, name="OldGuy",  position=Position.M, real_team="ENG"),
        ]
        svc, mgr_r, plr_r, *rest = _make_service(managers=managers, players=players, with_cr=True)
        # Put player 50 on manager 1's roster already
        mgr_r.add_to_roster(1, 50, acquired_at=T0, via=AcquisitionVia.AUCTION, price=20)
        return svc, mgr_r, *rest

    def test_cr_player_released_when_win(self):
        svc, mgr_r, *_ = self._setup_cr()
        svc.submit(ROUND_ID, 1, [
            RawBid(1, 10, 100, 1),       # acquire Kane
            RawBid(1, 50, 0, -1),        # conditional release OldGuy at rank -1
        ], T0)
        svc.resolve(ROUND_ID, T2)
        assert mgr_r.list_roster(1) == [
            e for e in mgr_r.rosters[1] if e.released_at is None
        ]
        # OldGuy should now be released
        all_entries = mgr_r.rosters.get(1, [])
        old_guy = next(e for e in all_entries if e.player_id == 50)
        assert old_guy.released_at == T2

    def test_no_cr_when_no_win(self):
        """If the manager wins nothing, no conditional releases happen."""
        managers = [
            FakeManager(id=1, display_name="ENG", balance=600),
            FakeManager(id=2, display_name="GER", balance=600),
        ]
        players = [
            FakePlayer(id=10, name="Kane",    position=Position.F, real_team="ENG"),
            FakePlayer(id=50, name="OldGuy",  position=Position.M, real_team="ENG"),
        ]
        svc, mgr_r, *_ = _make_service(managers=managers, players=players, with_cr=True)
        mgr_r.add_to_roster(1, 50, acquired_at=T0, via=AcquisitionVia.AUCTION, price=20)
        # Manager 2 outbids manager 1; manager 1 gets nothing
        svc.submit(ROUND_ID, 1, [
            RawBid(1, 10, 100, 1),
            RawBid(1, 50, 0, -1),
        ], T0)
        svc.submit(ROUND_ID, 2, [RawBid(2, 10, 200, 1)], T1)
        svc.resolve(ROUND_ID, T2)
        # OldGuy must NOT be released
        all_entries = mgr_r.rosters.get(1, [])
        old_guy = next(e for e in all_entries if e.player_id == 50)
        assert old_guy.released_at is None


# ---------------------------------------------------------------------------
# announcement_views + formatter
# ---------------------------------------------------------------------------

class TestAnnouncement:
    def test_views_include_valid_bids(self):
        svc, *_ = _setup_two_players()
        svc.submit(ROUND_ID, 1, [RawBid(1, 10, 200, 1)], T0)
        svc.submit(ROUND_ID, 2, [RawBid(2, 10, 150, 1)], T1)
        svc.resolve(ROUND_ID, T2)
        views = svc.announcement_views(ROUND_ID)
        amounts = {v.amount for v in views}
        assert 200 in amounts
        assert 150 in amounts

    def test_views_sorted_by_player_then_amount_desc(self):
        managers = [
            FakeManager(id=1, display_name="ENG", balance=600),
            FakeManager(id=2, display_name="GER", balance=600),
        ]
        players = [
            FakePlayer(id=10, name="Kane",    position=Position.F, real_team="ENG"),
            FakePlayer(id=20, name="Musiala", position=Position.M, real_team="GER"),
        ]
        svc, *_ = _make_service(managers=managers, players=players)
        svc.submit(ROUND_ID, 1, [RawBid(1, 10, 200, 1), RawBid(1, 20, 50, 1)], T0)
        svc.submit(ROUND_ID, 2, [RawBid(2, 10, 150, 1), RawBid(2, 20, 80, 1)], T1)
        svc.resolve(ROUND_ID, T2)
        views = svc.announcement_views(ROUND_ID)
        pids = [v.player_id for v in views]
        # player 10 rows come before player 20 rows
        last_10 = max(i for i, v in enumerate(views) if v.player_id == 10)
        first_20 = min(i for i, v in enumerate(views) if v.player_id == 20)
        assert last_10 < first_20
        # within player 10: 200 before 150
        p10_amounts = [v.amount for v in views if v.player_id == 10]
        assert p10_amounts == sorted(p10_amounts, reverse=True)

    def test_invalid_per_bid_excluded_from_announcement(self):
        svc, *_ = _setup_two_players()
        # amount=5 < min_bid=10 → INVALID_PER_BID
        svc.submit(ROUND_ID, 1, [RawBid(1, 10, 5, 1)], T0)
        views = svc.announcement_views(ROUND_ID)
        assert all(v.amount != 5 for v in views)

    def test_formatter_produces_non_empty_text(self):
        svc, *_ = _setup_two_players()
        svc.submit(ROUND_ID, 1, [RawBid(1, 10, 200, 1)], T0)
        svc.resolve(ROUND_ID, T2)
        views = svc.announcement_views(ROUND_ID)
        text = AuctionAnnouncementFormatter().format(views)
        assert len(text) > 0
        assert "Kane" in text
        assert "ENG" in text

    def test_formatter_includes_amount_with_m(self):
        svc, *_ = _setup_two_players()
        svc.submit(ROUND_ID, 1, [RawBid(1, 10, 131, 1)], T0)
        svc.resolve(ROUND_ID, T2)
        text = AuctionAnnouncementFormatter().format(svc.announcement_views(ROUND_ID))
        assert "131m" in text

    def test_formatter_player_groups_separated_by_blank_line(self):
        managers = [
            FakeManager(id=1, display_name="ENG", balance=600),
            FakeManager(id=2, display_name="GER", balance=600),
        ]
        players = [
            FakePlayer(id=10, name="Kane",    position=Position.F, real_team="ENG"),
            FakePlayer(id=20, name="Musiala", position=Position.M, real_team="GER"),
        ]
        svc, *_ = _make_service(managers=managers, players=players)
        svc.submit(ROUND_ID, 1, [RawBid(1, 10, 100, 1), RawBid(1, 20, 50, 1)], T0)
        svc.resolve(ROUND_ID, T2)
        text = AuctionAnnouncementFormatter().format(svc.announcement_views(ROUND_ID))
        assert "\n\n" in text  # blank line between player groups

    def test_formatter_empty_input(self):
        text = AuctionAnnouncementFormatter().format([])
        assert text == ""
