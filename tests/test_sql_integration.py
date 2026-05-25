"""Integration tests: db.py + sql_repos.py against SQLite in-memory.

These tests exercise the full SQLAlchemy stack without hitting a real file.
They do NOT use the fake repos.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from fmlwc.core.enums import (
    AcquisitionVia,
    AuctionRoundStatus,
    BidStatus,
    EligibilityRestriction,
    GameweekPhase,
    GameweekStatus,
    Position,
    RealEventType,
    TransferWindowStatus,
)
from fmlwc.persistence.db import create_all, make_engine, make_session_factory, session_scope
from fmlwc.persistence.models import (
    AuctionRound,
    EligibilityRecord,
    Fixture,
    Gameweek,
    Lineup,
    Manager,
    Player,
    TransferWindow,
)
from fmlwc.persistence.sql_repos import (
    SqlAthleticsRepo,
    SqlAuctionResultRepo,
    SqlAuctionRoundRepo,
    SqlBidRepo,
    SqlEligibilityRepo,
    SqlFixtureRepo,
    SqlGameweekRepo,
    SqlManagerRepo,
    SqlMatchEventRepo,
    SqlPlayerRepo,
    SqlSubmissionRepo,
    SqlTransferRepo,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine():
    eng = make_engine("sqlite:///:memory:", echo=False)
    create_all(eng)
    return eng


@pytest.fixture()
def factory(engine):
    return make_session_factory(engine)


@pytest.fixture()
def session(factory):
    """Yield a single open session; roll back after the test."""
    sess = factory()
    yield sess
    sess.rollback()
    sess.close()


def _make_manager(session, *, id=1, name="Alice", balance=600) -> Manager:
    mgr = Manager(id=id, display_name=name, balance=balance)
    session.add(mgr)
    session.flush()
    return mgr


def _make_player(session, *, id=1, name="Ronaldo", pos=Position.F) -> Player:
    p = Player(id=id, name=name, position=pos, real_team="POR", market_value=100)
    session.add(p)
    session.flush()
    return p


def _make_round(session, *, id=1, index=1) -> AuctionRound:
    rnd = AuctionRound(
        id=id,
        index=index,
        opens_at=datetime(2026, 6, 1),
        closes_at=datetime(2026, 6, 2),
        status=AuctionRoundStatus.OPEN,
    )
    session.add(rnd)
    session.flush()
    return rnd


NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
NOW_NAIVE = datetime(2026, 6, 1, 12, 0, 0)


# ---------------------------------------------------------------------------
# db helpers
# ---------------------------------------------------------------------------

class TestDbHelpers:
    def test_session_scope_commits(self, factory, engine):
        with session_scope(factory) as s:
            s.add(Manager(id=99, display_name="Temp", balance=0))
        # open a new session to verify commit
        with session_scope(factory) as s:
            mgr = s.get(Manager, 99)
            assert mgr is not None
            assert mgr.display_name == "Temp"

    def test_session_scope_rolls_back_on_error(self, factory):
        try:
            with session_scope(factory) as s:
                s.add(Manager(id=88, display_name="Bad", balance=0))
                raise RuntimeError("intentional")
        except RuntimeError:
            pass
        with session_scope(factory) as s:
            assert s.get(Manager, 88) is None

    def test_create_all_creates_tables(self, engine):
        from sqlalchemy import inspect
        insp = inspect(engine)
        tables = insp.get_table_names()
        assert "managers" in tables
        assert "players" in tables
        assert "bids" in tables
        assert "auction_rounds" in tables
        assert "submissions" in tables
        assert "auction_results" in tables
        assert "transfer_windows" in tables
        assert "eligibility_records" in tables
        assert "roster_entries" in tables


# ---------------------------------------------------------------------------
# SqlManagerRepo
# ---------------------------------------------------------------------------

class TestSqlManagerRepo:
    def test_get(self, session):
        _make_manager(session, id=1, name="Alice", balance=600)
        repo = SqlManagerRepo(session)
        mgr = repo.get(1)
        assert mgr.display_name == "Alice"
        assert mgr.balance == 600

    def test_list_active(self, session):
        _make_manager(session, id=1, name="Alice", balance=600)
        _make_manager(session, id=2, name="Bob", balance=500)
        repo = SqlManagerRepo(session)
        managers = repo.list_active()
        assert len(managers) == 2

    def test_adjust_balance_positive(self, session):
        _make_manager(session, id=1, balance=600)
        repo = SqlManagerRepo(session)
        repo.adjust_balance(1, -100, reason="bid")
        assert repo.get(1).balance == 500

    def test_adjust_balance_negative_raises(self, session):
        _make_manager(session, id=1, balance=50)
        repo = SqlManagerRepo(session)
        with pytest.raises(ValueError, match="negative"):
            repo.adjust_balance(1, -100, reason="bid")

    def test_add_and_list_roster(self, session):
        _make_manager(session, id=1)
        _make_player(session, id=10, pos=Position.F)
        repo = SqlManagerRepo(session)
        repo.add_to_roster(1, 10, acquired_at=NOW, via=AcquisitionVia.AUCTION, price=50)
        entries = repo.list_roster(1)
        assert len(entries) == 1
        assert entries[0].player_id == 10

    def test_list_roster_excludes_released(self, session):
        _make_manager(session, id=1)
        _make_player(session, id=10)
        repo = SqlManagerRepo(session)
        repo.add_to_roster(1, 10, acquired_at=NOW, via=AcquisitionVia.AUCTION, price=50)
        repo.release_from_roster(1, 10, NOW)
        assert repo.list_roster(1) == []

    def test_position_count(self, session):
        _make_manager(session, id=1)
        _make_player(session, id=10, pos=Position.F)
        _make_player(session, id=11, pos=Position.M)
        repo = SqlManagerRepo(session)
        repo.add_to_roster(1, 10, acquired_at=NOW, via=AcquisitionVia.AUCTION, price=0)
        repo.add_to_roster(1, 11, acquired_at=NOW, via=AcquisitionVia.AUCTION, price=0)
        assert repo.position_count(1, Position.F) == 1
        assert repo.position_count(1, Position.M) == 1
        assert repo.position_count(1, Position.G) == 0

    def test_release_from_roster_raises_if_not_on_roster(self, session):
        _make_manager(session, id=1)
        _make_player(session, id=10)
        repo = SqlManagerRepo(session)
        with pytest.raises(KeyError):
            repo.release_from_roster(1, 10, NOW)

    def test_timezone_aware_datetime_stored_as_naive(self, session):
        """Datetime stored should strip timezone."""
        _make_manager(session, id=1)
        _make_player(session, id=10)
        repo = SqlManagerRepo(session)
        repo.add_to_roster(1, 10, acquired_at=NOW, via=AcquisitionVia.AUCTION, price=0)
        entry = repo.list_roster(1)[0]
        # SQLite stores naive UTC
        assert entry.acquired_at.tzinfo is None
        assert entry.acquired_at == NOW_NAIVE


# ---------------------------------------------------------------------------
# SqlPlayerRepo
# ---------------------------------------------------------------------------

class TestSqlPlayerRepo:
    def test_get(self, session):
        _make_player(session, id=5, name="Messi", pos=Position.M)
        repo = SqlPlayerRepo(session)
        p = repo.get(5)
        assert p.name == "Messi"
        assert p.position is Position.M

    def test_is_free_agent_true_when_no_roster(self, session):
        _make_player(session, id=5)
        repo = SqlPlayerRepo(session)
        assert repo.is_free_agent(5, NOW) is True

    def test_is_free_agent_false_when_rostered(self, session):
        _make_manager(session, id=1)
        _make_player(session, id=5)
        mgr_repo = SqlManagerRepo(session)
        mgr_repo.add_to_roster(1, 5, acquired_at=NOW, via=AcquisitionVia.AUCTION, price=0)
        player_repo = SqlPlayerRepo(session)
        assert player_repo.is_free_agent(5, NOW) is False

    def test_is_free_agent_true_after_release(self, session):
        _make_manager(session, id=1)
        _make_player(session, id=5)
        mgr_repo = SqlManagerRepo(session)
        mgr_repo.add_to_roster(1, 5, acquired_at=NOW, via=AcquisitionVia.AUCTION, price=0)
        released_at = datetime(2026, 6, 2, tzinfo=timezone.utc)
        mgr_repo.release_from_roster(1, 5, released_at)
        after_release = datetime(2026, 6, 3, tzinfo=timezone.utc)
        player_repo = SqlPlayerRepo(session)
        assert player_repo.is_free_agent(5, after_release) is True


# ---------------------------------------------------------------------------
# SqlAuctionRoundRepo
# ---------------------------------------------------------------------------

class TestSqlAuctionRoundRepo:
    def test_get(self, session):
        _make_round(session, id=1, index=1)
        repo = SqlAuctionRoundRepo(session)
        rnd = repo.get(1)
        assert rnd.index == 1
        assert rnd.status is AuctionRoundStatus.OPEN

    def test_set_status(self, session):
        _make_round(session, id=1)
        repo = SqlAuctionRoundRepo(session)
        repo.set_status(1, AuctionRoundStatus.CLOSED)
        assert repo.get(1).status is AuctionRoundStatus.CLOSED


# ---------------------------------------------------------------------------
# SqlSubmissionRepo + SqlBidRepo
# ---------------------------------------------------------------------------

class TestSqlSubmissionAndBidRepo:
    def _setup(self, session):
        _make_manager(session, id=1)
        _make_player(session, id=10)
        _make_round(session, id=1)

    def test_upsert_creates_new(self, session):
        self._setup(session)
        sub_repo = SqlSubmissionRepo(session)
        sub_id = sub_repo.upsert(1, 1, NOW)
        assert sub_id == 1

    def test_upsert_idempotent(self, session):
        self._setup(session)
        sub_repo = SqlSubmissionRepo(session)
        id1 = sub_repo.upsert(1, 1, NOW)
        id2 = sub_repo.upsert(1, 1, NOW)
        assert id1 == id2
        # only one submission row
        assert len(sub_repo.for_round(1)) == 1

    def test_upsert_updates_received_at(self, session):
        self._setup(session)
        sub_repo = SqlSubmissionRepo(session)
        sub_repo.upsert(1, 1, NOW)
        later = datetime(2026, 6, 1, 13, 0, 0, tzinfo=timezone.utc)
        sub_repo.upsert(1, 1, later)
        sub = sub_repo.get(1)
        assert sub.received_at == datetime(2026, 6, 1, 13, 0, 0)

    def test_bid_create_and_for_submission(self, session):
        self._setup(session)
        sub_repo = SqlSubmissionRepo(session)
        bid_repo = SqlBidRepo(session)
        sub_id = sub_repo.upsert(1, 1, NOW)
        bid_id = bid_repo.create(sub_id, 10, 50, 1)
        assert bid_id is not None
        bids = bid_repo.for_submission(sub_id)
        assert len(bids) == 1
        assert bids[0].amount == 50

    def test_bid_for_round(self, session):
        self._setup(session)
        sub_repo = SqlSubmissionRepo(session)
        bid_repo = SqlBidRepo(session)
        sub_id = sub_repo.upsert(1, 1, NOW)
        bid_repo.create(sub_id, 10, 50, 1)
        bids = bid_repo.for_round(1)
        assert len(bids) == 1

    def test_bid_update_status(self, session):
        self._setup(session)
        sub_repo = SqlSubmissionRepo(session)
        bid_repo = SqlBidRepo(session)
        sub_id = sub_repo.upsert(1, 1, NOW)
        bid_id = bid_repo.create(sub_id, 10, 50, 1)
        bid_repo.update_status(bid_id, BidStatus.AWARDED)
        bids = bid_repo.for_submission(sub_id)
        assert bids[0].status is BidStatus.AWARDED

    def test_clear_for_submission(self, session):
        self._setup(session)
        sub_repo = SqlSubmissionRepo(session)
        bid_repo = SqlBidRepo(session)
        sub_id = sub_repo.upsert(1, 1, NOW)
        bid_repo.create(sub_id, 10, 50, 1)
        assert len(bid_repo.for_submission(sub_id)) == 1
        bid_repo.clear_for_submission(sub_id)
        assert len(bid_repo.for_submission(sub_id)) == 0

    def test_resubmit_clears_stale_bids(self, session):
        """Simulates the service.submit() re-submit pattern."""
        self._setup(session)
        sub_repo = SqlSubmissionRepo(session)
        bid_repo = SqlBidRepo(session)
        sub_id = sub_repo.upsert(1, 1, NOW)
        bid_repo.create(sub_id, 10, 50, 1)
        # re-submit
        sub_id2 = sub_repo.upsert(1, 1, NOW)
        assert sub_id == sub_id2
        bid_repo.clear_for_submission(sub_id2)
        bid_repo.create(sub_id2, 10, 80, 1)  # updated bid
        bids = bid_repo.for_submission(sub_id)
        assert len(bids) == 1
        assert bids[0].amount == 80


# ---------------------------------------------------------------------------
# SqlAuctionResultRepo
# ---------------------------------------------------------------------------

class TestSqlAuctionResultRepo:
    def test_create_and_for_round(self, session):
        _make_manager(session, id=1)
        _make_player(session, id=10)
        _make_round(session, id=1)
        repo = SqlAuctionResultRepo(session)
        repo.create(round_id=1, player_id=10, winner_manager_id=1, price=50)
        results = repo.for_round(1)
        assert len(results) == 1
        assert results[0].price == 50
        assert results[0].winner_manager_id == 1


# ---------------------------------------------------------------------------
# SqlTransferRepo
# ---------------------------------------------------------------------------

class TestSqlTransferRepo:
    def _make_window(self, session, *, id=1, opens, closes):
        w = TransferWindow(
            id=id,
            opens_at=opens,
            closes_at=closes,
            free_sign_period_seconds=86400,
            status=TransferWindowStatus.OPEN,
        )
        session.add(w)
        session.flush()
        return w

    def test_current_window(self, session):
        self._make_window(session, id=1,
                          opens=datetime(2026, 6, 3),
                          closes=datetime(2026, 6, 7))
        repo = SqlTransferRepo(session)
        at = datetime(2026, 6, 5, tzinfo=timezone.utc)
        w = repo.current_window(at)
        assert w is not None
        assert w.id == 1

    def test_current_window_none_outside(self, session):
        self._make_window(session, id=1,
                          opens=datetime(2026, 6, 3),
                          closes=datetime(2026, 6, 7))
        repo = SqlTransferRepo(session)
        at = datetime(2026, 6, 1, tzinfo=timezone.utc)
        assert repo.current_window(at) is None

    def test_previous_window(self, session):
        self._make_window(session, id=1,
                          opens=datetime(2026, 5, 1),
                          closes=datetime(2026, 5, 5))
        repo = SqlTransferRepo(session)
        at = datetime(2026, 6, 1, tzinfo=timezone.utc)
        w = repo.previous_window(at)
        assert w is not None
        assert w.id == 1

    def test_previous_window_returns_most_recent(self, session):
        self._make_window(session, id=1,
                          opens=datetime(2026, 4, 1),
                          closes=datetime(2026, 4, 5))
        self._make_window(session, id=2,
                          opens=datetime(2026, 5, 1),
                          closes=datetime(2026, 5, 5))
        repo = SqlTransferRepo(session)
        at = datetime(2026, 6, 1, tzinfo=timezone.utc)
        w = repo.previous_window(at)
        assert w.id == 2

    def test_next_window(self, session):
        self._make_window(session, id=1,
                          opens=datetime(2026, 7, 1),
                          closes=datetime(2026, 7, 5))
        repo = SqlTransferRepo(session)
        at = datetime(2026, 6, 1, tzinfo=timezone.utc)
        w = repo.next_window(at)
        assert w is not None
        assert w.id == 1

    def test_next_window_returns_earliest(self, session):
        self._make_window(session, id=1,
                          opens=datetime(2026, 8, 1),
                          closes=datetime(2026, 8, 5))
        self._make_window(session, id=2,
                          opens=datetime(2026, 7, 1),
                          closes=datetime(2026, 7, 5))
        repo = SqlTransferRepo(session)
        at = datetime(2026, 6, 1, tzinfo=timezone.utc)
        w = repo.next_window(at)
        assert w.id == 2


# ---------------------------------------------------------------------------
# SqlEligibilityRepo
# ---------------------------------------------------------------------------

class TestSqlEligibilityRepo:
    def test_add_and_list_for_player(self, session):
        _make_manager(session, id=1)
        _make_player(session, id=10)
        repo = SqlEligibilityRepo(session)
        valid_until = datetime(2026, 6, 10, tzinfo=timezone.utc)
        repo.add(1, 10, EligibilityRestriction.RELEASED_LIFETIME, valid_until)
        records = repo.list_for_player(10, NOW)
        assert len(records) == 1
        assert records[0].restriction_type is EligibilityRestriction.RELEASED_LIFETIME

    def test_expired_record_not_returned(self, session):
        _make_manager(session, id=1)
        _make_player(session, id=10)
        repo = SqlEligibilityRepo(session)
        past = datetime(2026, 5, 1, tzinfo=timezone.utc)
        repo.add(1, 10, EligibilityRestriction.FREE_SIGN_SAME_WINDOW, past)
        records = repo.list_for_player(10, NOW)
        assert records == []

    def test_none_valid_until_always_returned(self, session):
        _make_manager(session, id=1)
        _make_player(session, id=10)
        repo = SqlEligibilityRepo(session)
        repo.add(1, 10, EligibilityRestriction.RELEASED_LIFETIME, None)
        records = repo.list_for_player(10, datetime(2099, 1, 1, tzinfo=timezone.utc))
        assert len(records) == 1

    def test_filters_by_player(self, session):
        _make_manager(session, id=1)
        _make_player(session, id=10)
        _make_player(session, id=11)
        repo = SqlEligibilityRepo(session)
        repo.add(1, 10, EligibilityRestriction.RELEASED_LIFETIME, None)
        repo.add(1, 11, EligibilityRestriction.RELEASED_LIFETIME, None)
        assert len(repo.list_for_player(10, NOW)) == 1
        assert len(repo.list_for_player(11, NOW)) == 1


# ---------------------------------------------------------------------------
# Helpers for match tests
# ---------------------------------------------------------------------------

def _make_gameweek(session, *, id=1, index=1,
                   phase=GameweekPhase.GROUP,
                   status=GameweekStatus.PENDING) -> Gameweek:
    gw = Gameweek(
        id=id, index=index, phase=phase,
        lineup_deadline=datetime(2026, 6, 10),
        status=status,
    )
    session.add(gw)
    session.flush()
    return gw


def _make_fixture(session, *, id=1, gameweek_id=1,
                  home_manager_id=1, away_manager_id=2) -> Fixture:
    f = Fixture(
        id=id, gameweek_id=gameweek_id,
        home_manager_id=home_manager_id,
        away_manager_id=away_manager_id,
    )
    session.add(f)
    session.flush()
    return f


def _make_lineup(session, *, fixture_id=1, manager_id=1,
                 starters: list[dict]) -> Lineup:
    lu = Lineup(
        fixture_id=fixture_id,
        manager_id=manager_id,
        starters=starters,
        posted_at=datetime(2026, 6, 10),
    )
    session.add(lu)
    session.flush()
    return lu


# ---------------------------------------------------------------------------
# SqlGameweekRepo
# ---------------------------------------------------------------------------

class TestSqlGameweekRepo:
    def test_get(self, session):
        _make_gameweek(session, id=1, index=1)
        repo = SqlGameweekRepo(session)
        gw = repo.get(1)
        assert gw.index == 1
        assert gw.status is GameweekStatus.PENDING

    def test_set_status(self, session):
        _make_gameweek(session, id=1)
        repo = SqlGameweekRepo(session)
        repo.set_status(1, GameweekStatus.LIVE)
        assert repo.get(1).status is GameweekStatus.LIVE

    def test_set_status_missing_raises(self, session):
        repo = SqlGameweekRepo(session)
        with pytest.raises(KeyError):
            repo.set_status(99, GameweekStatus.LIVE)

    def test_fixtures_for(self, session):
        _make_manager(session, id=1, name="M1")
        _make_manager(session, id=2, name="M2")
        _make_gameweek(session, id=1)
        _make_gameweek(session, id=2, index=2)
        _make_fixture(session, id=1, gameweek_id=1)
        _make_fixture(session, id=2, gameweek_id=1, home_manager_id=2, away_manager_id=1)
        _make_fixture(session, id=3, gameweek_id=2)
        repo = SqlGameweekRepo(session)
        fixtures = repo.fixtures_for(1)
        assert len(fixtures) == 2
        assert all(f.gameweek_id == 1 for f in fixtures)

    def test_create_returns_id(self, session):
        repo = SqlGameweekRepo(session)
        gw_id = repo.create(index=1, phase=GameweekPhase.GROUP,
                            lineup_deadline=datetime(2026, 6, 10))
        assert isinstance(gw_id, int)
        gw = repo.get(gw_id)
        assert gw.index == 1
        assert gw.phase is GameweekPhase.GROUP
        assert gw.status is GameweekStatus.PENDING

    def test_create_default_status_pending(self, session):
        repo = SqlGameweekRepo(session)
        gw_id = repo.create(1, GameweekPhase.GROUP, datetime(2026, 6, 10))
        assert repo.get(gw_id).status is GameweekStatus.PENDING

    def test_fixtures_for_empty(self, session):
        _make_gameweek(session, id=1)
        repo = SqlGameweekRepo(session)
        assert repo.fixtures_for(1) == []


# ---------------------------------------------------------------------------
# SqlFixtureRepo
# ---------------------------------------------------------------------------

class TestSqlFixtureRepo:
    def test_get(self, session):
        _make_manager(session, id=1, name="M1")
        _make_manager(session, id=2, name="M2")
        _make_gameweek(session, id=1)
        _make_fixture(session, id=5, gameweek_id=1)
        repo = SqlFixtureRepo(session)
        f = repo.get(5)
        assert f.home_manager_id == 1
        assert f.away_manager_id == 2

    def test_lineup_for_found(self, session):
        _make_manager(session, id=1, name="M1")
        _make_manager(session, id=2, name="M2")
        _make_gameweek(session, id=1)
        _make_fixture(session, id=1, gameweek_id=1)
        _make_lineup(session, fixture_id=1, manager_id=1,
                     starters=[{"player_id": 10, "slot_position": "F"}])
        repo = SqlFixtureRepo(session)
        lu = repo.lineup_for(1, 1)
        assert lu is not None
        assert lu.manager_id == 1

    def test_lineup_for_missing_returns_none(self, session):
        _make_manager(session, id=1, name="M1")
        _make_manager(session, id=2, name="M2")
        _make_gameweek(session, id=1)
        _make_fixture(session, id=1, gameweek_id=1)
        repo = SqlFixtureRepo(session)
        assert repo.lineup_for(1, 1) is None

    def test_player_manager_map(self, session):
        _make_manager(session, id=1, name="M1")
        _make_manager(session, id=2, name="M2")
        _make_gameweek(session, id=1)
        _make_fixture(session, id=1, gameweek_id=1,
                      home_manager_id=1, away_manager_id=2)
        _make_lineup(session, fixture_id=1, manager_id=1,
                     starters=[{"player_id": 10, "slot_position": "F"},
                                {"player_id": 11, "slot_position": "M"}])
        _make_lineup(session, fixture_id=1, manager_id=2,
                     starters=[{"player_id": 20, "slot_position": "G"}])
        repo = SqlFixtureRepo(session)
        mapping = repo.player_manager_map(gameweek_id=1)
        assert mapping == {10: 1, 11: 1, 20: 2}

    def test_player_manager_map_multiple_fixtures(self, session):
        _make_manager(session, id=1, name="M1")
        _make_manager(session, id=2, name="M2")
        _make_manager(session, id=3, name="M3")
        _make_manager(session, id=4, name="M4")
        _make_gameweek(session, id=1)
        _make_fixture(session, id=1, gameweek_id=1,
                      home_manager_id=1, away_manager_id=2)
        _make_fixture(session, id=2, gameweek_id=1,
                      home_manager_id=3, away_manager_id=4)
        _make_lineup(session, fixture_id=1, manager_id=1,
                     starters=[{"player_id": 10, "slot_position": "F"}])
        _make_lineup(session, fixture_id=2, manager_id=3,
                     starters=[{"player_id": 30, "slot_position": "D"}])
        repo = SqlFixtureRepo(session)
        mapping = repo.player_manager_map(gameweek_id=1)
        assert mapping[10] == 1
        assert mapping[30] == 3

    def test_create_returns_id(self, session):
        _make_manager(session, id=1, name="M1")
        _make_manager(session, id=2, name="M2")
        _make_gameweek(session, id=1)
        repo = SqlFixtureRepo(session)
        fid = repo.create(1, 1, 2, group_letter="A")
        assert isinstance(fid, int)
        f = repo.get(fid)
        assert f.gameweek_id == 1
        assert f.home_manager_id == 1
        assert f.away_manager_id == 2
        assert f.group_letter == "A"
        assert f.bracket_slot is None

    def test_create_bracket_slot(self, session):
        _make_manager(session, id=1, name="M1")
        _make_manager(session, id=2, name="M2")
        _make_gameweek(session, id=1)
        repo = SqlFixtureRepo(session)
        fid = repo.create(1, 1, 2, bracket_slot="QF1")
        assert repo.get(fid).bracket_slot == "QF1"

    def test_save_lineup_creates(self, session):
        _make_manager(session, id=1, name="M1")
        _make_manager(session, id=2, name="M2")
        _make_gameweek(session, id=1)
        repo = SqlFixtureRepo(session)
        fid = repo.create(1, 1, 2)
        starters = [{"player_id": 10, "slot_position": "G"},
                    {"player_id": 11, "slot_position": "F"}]
        lid = repo.save_lineup(fid, 1, starters, datetime(2026, 6, 10))
        assert isinstance(lid, int)
        lu = repo.lineup_for(fid, 1)
        assert lu is not None
        assert lu.starters == starters

    def test_save_lineup_upserts(self, session):
        _make_manager(session, id=1, name="M1")
        _make_manager(session, id=2, name="M2")
        _make_gameweek(session, id=1)
        repo = SqlFixtureRepo(session)
        fid = repo.create(1, 1, 2)
        lid1 = repo.save_lineup(fid, 1,
                                [{"player_id": 10, "slot_position": "G"}],
                                datetime(2026, 6, 10))
        lid2 = repo.save_lineup(fid, 1,
                                [{"player_id": 99, "slot_position": "F"}],
                                datetime(2026, 6, 10, 1))
        assert lid1 == lid2                       # same row updated
        lu = repo.lineup_for(fid, 1)
        assert lu.starters[0]["player_id"] == 99  # new starters

    def test_save_lineup_with_pk_order(self, session):
        _make_manager(session, id=1, name="M1")
        _make_manager(session, id=2, name="M2")
        _make_gameweek(session, id=1)
        repo = SqlFixtureRepo(session)
        fid = repo.create(1, 1, 2)
        repo.save_lineup(fid, 1, [], datetime(2026, 6, 10), pk_order=[10, 11, 12])
        assert repo.lineup_for(fid, 1).pk_order == [10, 11, 12]


# ---------------------------------------------------------------------------
# SqlMatchEventRepo
# ---------------------------------------------------------------------------

class TestSqlMatchEventRepo:
    def _setup(self, session):
        _make_manager(session, id=1, name="M1")
        _make_manager(session, id=2, name="M2")
        _make_player(session, id=10)
        _make_gameweek(session, id=1, status=GameweekStatus.LIVE)

    def test_add_returns_id(self, session):
        self._setup(session)
        repo = SqlMatchEventRepo(session)
        eid = repo.add(1, 10, RealEventType.GOAL)
        assert isinstance(eid, int)

    def test_add_persists_fields(self, session):
        self._setup(session)
        repo = SqlMatchEventRepo(session)
        eid = repo.add(1, 10, RealEventType.ASSIST,
                       minute=67, is_extra_time=False, is_shootout=False)
        ev = session.get(__import__(
            "fmlwc.persistence.models", fromlist=["MatchEvent"]
        ).MatchEvent, eid)
        assert ev.gameweek_id == 1
        assert ev.player_id == 10
        assert ev.event_type is RealEventType.ASSIST
        assert ev.minute == 67

    def test_remove_deletes_event(self, session):
        self._setup(session)
        repo = SqlMatchEventRepo(session)
        eid = repo.add(1, 10, RealEventType.GOAL)
        repo.remove(eid)
        evs = repo.for_players_in_gameweek(1, {10})
        assert evs == []

    def test_for_players_in_gameweek_filters_player(self, session):
        self._setup(session)
        _make_player(session, id=11)
        repo = SqlMatchEventRepo(session)
        repo.add(1, 10, RealEventType.GOAL)
        repo.add(1, 11, RealEventType.YELLOW)
        evs = repo.for_players_in_gameweek(1, {10})
        assert len(evs) == 1
        assert evs[0].player_id == 10

    def test_for_players_in_gameweek_filters_gameweek(self, session):
        self._setup(session)
        _make_gameweek(session, id=2, index=2)
        repo = SqlMatchEventRepo(session)
        repo.add(1, 10, RealEventType.GOAL)
        repo.add(2, 10, RealEventType.GOAL)
        evs = repo.for_players_in_gameweek(1, {10})
        assert len(evs) == 1


# ---------------------------------------------------------------------------
# SqlAthleticsRepo
# ---------------------------------------------------------------------------

class TestSqlAthleticsRepo:
    def test_increment_player_creates_row(self, session):
        _make_player(session, id=10)
        repo = SqlAthleticsRepo(session)
        repo.increment_player(10, {"goals": 2, "assists": 1})
        from fmlwc.persistence.models import PlayerAthletics
        row = session.get(PlayerAthletics, 10)
        assert row.goals == 2
        assert row.assists == 1
        assert row.yellows == 0

    def test_increment_player_accumulates(self, session):
        _make_player(session, id=10)
        repo = SqlAthleticsRepo(session)
        repo.increment_player(10, {"goals": 1})
        repo.increment_player(10, {"goals": 2})
        from fmlwc.persistence.models import PlayerAthletics
        assert session.get(PlayerAthletics, 10).goals == 3

    def test_increment_manager_creates_row(self, session):
        _make_manager(session, id=1)
        repo = SqlAthleticsRepo(session)
        repo.increment_manager(1, {"goals": 3})
        from fmlwc.persistence.models import ManagerStats
        row = session.get(ManagerStats, 1)
        assert row.goals == 3

    def test_increment_manager_accumulates(self, session):
        _make_manager(session, id=1)
        repo = SqlAthleticsRepo(session)
        repo.increment_manager(1, {"reds": 1})
        repo.increment_manager(1, {"reds": 1})
        from fmlwc.persistence.models import ManagerStats
        assert session.get(ManagerStats, 1).reds == 2

    def test_increment_manager_player_creates_row(self, session):
        _make_manager(session, id=1)
        _make_player(session, id=10)
        repo = SqlAthleticsRepo(session)
        repo.increment_manager_player(1, 10, {"goals": 1, "assists": 2})
        from fmlwc.persistence.models import ManagerPlayerAthletics
        row = session.get(ManagerPlayerAthletics, (1, 10))
        assert row.goals == 1
        assert row.assists == 2

    def test_increment_manager_player_separate_rows_per_manager(self, session):
        _make_manager(session, id=1, name="M1")
        _make_manager(session, id=2, name="M2")
        _make_player(session, id=10)
        repo = SqlAthleticsRepo(session)
        repo.increment_manager_player(1, 10, {"goals": 2})
        repo.increment_manager_player(2, 10, {"goals": 1})
        from fmlwc.persistence.models import ManagerPlayerAthletics
        assert session.get(ManagerPlayerAthletics, (1, 10)).goals == 2
        assert session.get(ManagerPlayerAthletics, (2, 10)).goals == 1

    def test_create_all_includes_new_tables(self, engine):
        from sqlalchemy import inspect
        tables = inspect(engine).get_table_names()
        assert "match_events" in tables
        assert "player_athletics" in tables
        assert "manager_stats" in tables
        assert "manager_player_athletics" in tables
