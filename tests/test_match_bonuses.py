"""Tests for fmlwc.domain.match.bonuses."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from fmlwc.core.enums import RealEventType
from fmlwc.domain.match.bonuses import (
    AssistBonus,
    BlueTeamBonus,
    BonusContext,
    BonusEngine,
    MissedPenaltyBonus,
    RedCardBonus,
    _safe_eval,
)

from tests.sample_rules import default_rules


@dataclass
class Ev:
    real_player_id: int
    event_type: RealEventType
    is_shootout: bool = False


def _ctx(home_starters, away_starters, events, *, home_goals=0, away_goals=0):
    return BonusContext(
        fixture_id=1,
        home_manager_id=10, away_manager_id=20,
        home_goals=home_goals, away_goals=away_goals,
        home_starter_ids=home_starters,
        away_starter_ids=away_starters,
        events=events,
    )


def test_assist_bonus_per_event():
    rule = AssistBonus(per_event=5)
    awards = rule.compute(_ctx([1, 2], [3], [
        Ev(1, RealEventType.ASSIST),
        Ev(1, RealEventType.ASSIST),
        Ev(3, RealEventType.ASSIST),
    ]))
    by_mgr = {a.manager_id: a.amount for a in awards}
    assert by_mgr[10] == 10   # 2 assists
    assert by_mgr[20] == 5    # 1 assist


def test_red_card_counts_both_red_and_2yc():
    rule = RedCardBonus(per_event=5)
    awards = rule.compute(_ctx([1], [2], [
        Ev(1, RealEventType.RED),
        Ev(1, RealEventType.SECOND_YELLOW_RED),
        Ev(2, RealEventType.YELLOW),  # not red, ignored
    ]))
    by_mgr = {a.manager_id: a.amount for a in awards}
    assert by_mgr[10] == 10
    assert 20 not in by_mgr


def test_missed_penalty_bonus():
    rule = MissedPenaltyBonus(per_event=3)
    awards = rule.compute(_ctx([1], [2], [
        Ev(1, RealEventType.MISSED_PENALTY),
        Ev(2, RealEventType.MISSED_PENALTY),
        Ev(2, RealEventType.MISSED_PENALTY),
    ]))
    by_mgr = {a.manager_id: a.amount for a in awards}
    assert by_mgr[10] == 3
    assert by_mgr[20] == 6


def test_blue_team_threshold_not_met_no_award():
    rule = BlueTeamBonus(conceded_gt=5, net_lt=-2, formula="2*conceded - scored")
    awards = rule.compute(_ctx([1], [2], [], home_goals=0, away_goals=5))   # conceded=5, not > 5
    assert awards == []


def test_blue_team_threshold_met_pays_formula():
    """conceded=6, scored=2 -> net=-4 (< -2), pay 2*6-2 = 10m."""
    rule = BlueTeamBonus(conceded_gt=5, net_lt=-2, formula="2*conceded - scored")
    awards = rule.compute(_ctx([1], [2], [], home_goals=2, away_goals=6))
    assert len(awards) == 1
    assert awards[0].manager_id == 10  # the team that conceded 6
    assert awards[0].amount == 10


def test_blue_team_both_sides_can_qualify_independently():
    """Symmetric — only the side with conceded>5 AND net<-2 gets paid."""
    rule = BlueTeamBonus(conceded_gt=5, net_lt=-2, formula="2*conceded - scored")
    # home: scored=8, conceded=10 -> net=-2 (NOT < -2, skip).
    # away: scored=10, conceded=8 -> net=+2 (skip).
    awards = rule.compute(_ctx([1], [2], [], home_goals=8, away_goals=10))
    assert awards == []


def test_safe_eval_arithmetic_only():
    assert _safe_eval("2*conceded - scored", {"conceded": 6, "scored": 2}) == 10
    assert _safe_eval("conceded // 2 + scored", {"conceded": 7, "scored": 1}) == 4


def test_safe_eval_rejects_calls():
    with pytest.raises(ValueError, match="forbidden"):
        _safe_eval("__import__('os')", {})


def test_safe_eval_rejects_unknown_name():
    with pytest.raises(ValueError, match="unknown name"):
        _safe_eval("totally_random", {})


def test_bonus_engine_runs_all_enabled_rules():
    rules = default_rules()
    engine = BonusEngine(rules)
    awards = engine.run(_ctx(
        [1], [2],
        [Ev(1, RealEventType.ASSIST), Ev(2, RealEventType.RED)],
        home_goals=0, away_goals=6,
    ))
    types = {a.bonus_type for a in awards}
    assert "ASSIST" in types
    assert "RED_CARD" in types
    # home conceded 6, scored 0 -> net -6 < -2 -> blue team awarded
    assert "BLUE_TEAM" in types


def test_bonus_engine_skips_disabled_rules():
    from tests.sample_rules import raw_dict
    cfg = raw_dict()
    cfg["bonuses"]["assist"]["enabled"] = False
    cfg["bonuses"]["blue_team"]["enabled"] = False
    cfg["bonuses"]["missed_penalty"]["enabled"] = False
    from fmlwc.core import GameRules
    rules = GameRules.from_dict(cfg)
    engine = BonusEngine(rules)
    awards = engine.run(_ctx([1], [2], [
        Ev(1, RealEventType.ASSIST),
        Ev(1, RealEventType.RED),
    ], home_goals=0, away_goals=10))
    types = {a.bonus_type for a in awards}
    assert types == {"RED_CARD"}
