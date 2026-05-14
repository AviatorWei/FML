"""Tests for fmlwc.domain.match.scoring -- Valid-goal calculation."""

from __future__ import annotations

from dataclasses import dataclass

from fmlwc.core.enums import MatchOutcome, RealEventType
from fmlwc.domain.match.scoring import ValidGoalCalculator

from tests.sample_rules import default_rules


@dataclass
class Ev:
    player_id: int
    event_type: RealEventType
    is_shootout: bool = False
    is_extra_time: bool = False


def test_simple_goal_count():
    rules = default_rules()
    calc = ValidGoalCalculator(rules)
    events = [
        Ev(10, RealEventType.GOAL),
        Ev(10, RealEventType.GOAL),
        Ev(20, RealEventType.GOAL),
    ]
    score = calc.score(
        fixture_id=1,
        home_starter_ids={10, 11}, away_starter_ids={20, 21},
        events=events,
    )
    assert score.home_goals == 2
    assert score.away_goals == 1
    assert score.outcome is MatchOutcome.HOME_WIN


def test_own_goal_credits_own_team():
    """Per rule 零.4.(2): own goal by your starter counts for YOUR team."""
    rules = default_rules()
    calc = ValidGoalCalculator(rules)
    events = [Ev(10, RealEventType.OWN_GOAL)]
    score = calc.score(
        fixture_id=1,
        home_starter_ids={10}, away_starter_ids={20},
        events=events,
    )
    assert score.home_goals == 1
    assert score.away_goals == 0
    assert score.outcome is MatchOutcome.HOME_WIN


def test_saved_penalty_by_gk_counts():
    rules = default_rules()
    calc = ValidGoalCalculator(rules)
    events = [Ev(10, RealEventType.SAVED_PENALTY_BY_GK)]
    score = calc.score(
        fixture_id=1,
        home_starter_ids={10}, away_starter_ids={20},
        events=events,
    )
    assert score.home_goals == 1


def test_shootout_excluded():
    rules = default_rules()
    calc = ValidGoalCalculator(rules)
    events = [
        Ev(10, RealEventType.GOAL, is_shootout=True),
        Ev(10, RealEventType.GOAL, is_shootout=False),
    ]
    score = calc.score(
        fixture_id=1,
        home_starter_ids={10}, away_starter_ids={20},
        events=events,
    )
    assert score.home_goals == 1


def test_player_not_a_starter_ignored():
    rules = default_rules()
    calc = ValidGoalCalculator(rules)
    events = [Ev(99, RealEventType.GOAL)]
    score = calc.score(
        fixture_id=1,
        home_starter_ids={10}, away_starter_ids={20},
        events=events,
    )
    assert score.home_goals == 0 and score.away_goals == 0


def test_other_event_types_ignored():
    rules = default_rules()
    calc = ValidGoalCalculator(rules)
    events = [
        Ev(10, RealEventType.ASSIST),
        Ev(10, RealEventType.YELLOW),
        Ev(10, RealEventType.RED),
    ]
    score = calc.score(
        fixture_id=1,
        home_starter_ids={10}, away_starter_ids={20},
        events=events,
    )
    assert score.home_goals == 0


def test_draw_outcome():
    rules = default_rules()
    calc = ValidGoalCalculator(rules)
    events = [
        Ev(10, RealEventType.GOAL),
        Ev(20, RealEventType.GOAL),
    ]
    score = calc.score(
        fixture_id=1,
        home_starter_ids={10}, away_starter_ids={20},
        events=events,
    )
    assert score.outcome is MatchOutcome.DRAW
