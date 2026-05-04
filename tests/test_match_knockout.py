"""Tests for fmlwc.domain.match.knockout."""

from __future__ import annotations

from dataclasses import dataclass

from fmlwc.core.enums import Position, RealEventType
from fmlwc.domain.match.knockout import PkResolver

from tests.sample_rules import default_rules


@dataclass
class Ev:
    event_type: RealEventType
    is_shootout: bool = False


def test_player_pk_score_goals_and_assists():
    r = PkResolver(default_rules())
    score = r.player_pk_score(
        player_id=1,
        events_for_player=[
            Ev(RealEventType.GOAL),
            Ev(RealEventType.GOAL),
            Ev(RealEventType.ASSIST),
        ],
        real_team_advanced=False,
    )
    assert score == 5.0   # 2*2 + 1


def test_player_pk_score_cards_and_advance_bonus():
    r = PkResolver(default_rules())
    score = r.player_pk_score(
        player_id=1,
        events_for_player=[
            Ev(RealEventType.YELLOW),
            Ev(RealEventType.RED),
        ],
        real_team_advanced=True,
    )
    # -0.3 + -1.0 + 0.5 = -0.8
    assert abs(score - (-0.8)) < 1e-9


def test_player_pk_score_excludes_shootout():
    r = PkResolver(default_rules())
    score = r.player_pk_score(
        player_id=1,
        events_for_player=[Ev(RealEventType.GOAL, is_shootout=True)],
        real_team_advanced=False,
    )
    assert score == 0.0


def test_resolve_top5_decides():
    r = PkResolver(default_rules())
    # Home: 5 starters with 1 goal each = 5*2 = 10. Away: 5 starters all 0.
    home_order = [1, 2, 3, 4, 5]
    away_order = [11, 12, 13, 14, 15]
    events = {pid: [Ev(RealEventType.GOAL)] for pid in home_order}
    out = r.resolve(home_order, away_order, events, {}, home_manager_id=100, away_manager_id=200)
    assert out.winner_manager_id == 100
    assert out.decided_at_position == 5
    assert out.home_total_top5 == 10.0
    assert out.away_total_top5 == 0.0


def test_resolve_drops_to_position_6():
    """Top-5 tied at 0; position 6 differs."""
    r = PkResolver(default_rules())
    home_order = [1, 2, 3, 4, 5, 6]
    away_order = [11, 12, 13, 14, 15, 16]
    events = {6: [Ev(RealEventType.GOAL)]}    # only home #6 scored
    out = r.resolve(home_order, away_order, events, {}, home_manager_id=100, away_manager_id=200)
    assert out.winner_manager_id == 100
    assert out.decided_at_position == 6


def test_resolve_one_side_runs_out():
    r = PkResolver(default_rules())
    home_order = [1, 2, 3, 4, 5, 6]   # 6 starters
    away_order = [11, 12, 13, 14, 15] # 5 starters
    events = {}   # all 0 — top5 ties
    out = r.resolve(home_order, away_order, events, {}, home_manager_id=100, away_manager_id=200)
    # Position 6: home has it, away doesn't -> home wins immediately
    assert out.winner_manager_id == 100
    assert out.decided_at_position == 6


def test_resolve_full_tie_is_draw():
    r = PkResolver(default_rules())
    home_order = [1, 2, 3, 4, 5]
    away_order = [11, 12, 13, 14, 15]
    out = r.resolve(home_order, away_order, {}, {}, home_manager_id=100, away_manager_id=200)
    assert out.winner_manager_id is None


def test_default_pk_order_F_M_D_G():
    r = PkResolver(default_rules())
    starters = [
        (1, Position.G),
        (2, Position.D),
        (3, Position.M),
        (4, Position.F),
        (5, Position.D),
        (6, Position.M),
        (7, Position.F),
    ]
    order = r.default_pk_order(starters)
    # Order should be: F (4, 7), M (3, 6), D (2, 5), G (1)
    assert order == [4, 7, 3, 6, 2, 5, 1]
