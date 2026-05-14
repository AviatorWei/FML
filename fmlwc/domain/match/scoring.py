"""Valid-goal calculation (rule 零.4 + 五.2).

team_goals(manager, fixture) =
    Sum events such that
        event.player_id in lineup.starters
        event.event_type in rules.valid_goal.count_event_types
        event not in penalty shootout (if exclude_penalty_shootout)

Events are pre-scoped to the fixture by the caller (RoundService); no
gameweek_id filter is needed here.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...core.config import GameRules
from ...core.enums import MatchOutcome


@dataclass(frozen=True)
class FixtureScore:
    fixture_id: int
    home_goals: int
    away_goals: int
    outcome: MatchOutcome


class ValidGoalCalculator:
    def __init__(self, rules: GameRules) -> None:
        self.rules = rules

    def score(
        self,
        fixture_id: int,
        home_starter_ids: set[int],
        away_starter_ids: set[int],
        events,
    ) -> FixtureScore:
        cfg = self.rules.valid_goal
        counted_types = set(cfg.count_event_types)

        home_goals = 0
        away_goals = 0
        for ev in events:
            if cfg.exclude_penalty_shootout and getattr(ev, "is_shootout", False):
                continue
            etype = ev.event_type.value if hasattr(ev.event_type, "value") else ev.event_type
            if etype not in counted_types:
                continue
            if ev.player_id in home_starter_ids:
                home_goals += 1
            elif ev.player_id in away_starter_ids:
                away_goals += 1

        if home_goals > away_goals:
            outcome = MatchOutcome.HOME_WIN
        elif away_goals > home_goals:
            outcome = MatchOutcome.AWAY_WIN
        else:
            outcome = MatchOutcome.DRAW
        return FixtureScore(fixture_id, home_goals, away_goals, outcome)
